#!/usr/bin/env python3
"""Overnight auto-tuner for Qwen-AgentWorld-35B-A3B on RTX 5060 Ti 16GB (llama.cpp).
stdlib only. Self-managing server. Watchdog (VRAM+RAM+hang). Append-only JSONL + resume.
Grades: deterministic (NIAH/FC/format/code-exec) inline; quality captured for blind judge.
Run:   python tune.py            (full matrix, unlimited time, resumable)
       python tune.py --smoke    (tiny validation grid)
"""
import argparse, csv, ctypes, json, os, random, re, socket, subprocess, sys, threading, time, urllib.request, urllib.error

EXE   = r"C:\Users\x3d_mutant\llama.cpp\llama-server.exe"
MODEL = r"C:\Users\x3d_mutant\Downloads\Qwen-AgentWorld-35B-A3B-UD-IQ4_NL.gguf"
HOST, PORT = "127.0.0.1", 8080
BASE = f"http://{HOST}:{PORT}"
DIR  = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(DIR, "results.jsonl")
RAWDIR  = os.path.join(DIR, "raw"); os.makedirs(RAWDIR, exist_ok=True)
PROG    = os.path.join(DIR, "progress.log")
DONEMARK= os.path.join(DIR, "DONE")

# ---- VRAM feasibility model (from measured points) ----
BASE_NCM16 = 12480          # MiB weights-on-GPU at ncm=16
PER_NCM    = 362.5          # MiB freed per +1 ncm (experts -> RAM)
KIB_TOK    = 20.0           # f16 KV per token
VRAM_TARGET= 14800          # pick ncm so predicted <= this (headroom)
VRAM_KILL  = 15600          # runtime: 2 consecutive samples above -> kill
RAM_FLOOR_GB = 2.0          # available RAM below -> kill
STALL_S    = 150            # no /slots progress this long -> hung -> kill
KV_BPW = {"f16":16.0, "q8_0":8.5, "q5_1":6.0, "q4_0":4.5, "iq4_nl":4.5}

def logp(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(PROG, "a", encoding="utf-8") as f: f.write(line+"\n")

# ---------- system metrics (stdlib) ----------
class _MEMSTAT(ctypes.Structure):
    _fields_=[("dwLength",ctypes.c_ulong),("dwMemoryLoad",ctypes.c_ulong),
      ("ullTotalPhys",ctypes.c_ulonglong),("ullAvailPhys",ctypes.c_ulonglong),
      ("ullTotalPageFile",ctypes.c_ulonglong),("ullAvailPageFile",ctypes.c_ulonglong),
      ("ullTotalVirtual",ctypes.c_ulonglong),("ullAvailVirtual",ctypes.c_ulonglong),
      ("ullAvailExtendedVirtual",ctypes.c_ulonglong)]
def avail_ram_gb():
    m=_MEMSTAT(); m.dwLength=ctypes.sizeof(m)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPhys/2**30
def vram_used_mib():
    try:
        out=subprocess.check_output(["nvidia-smi","--query-gpu=memory.used","--format=csv,noheader,nounits"],timeout=10)
        return int(out.decode().strip().splitlines()[0])
    except Exception:
        return -1

# ---------- feasibility / ncm picker ----------
def predicted_vram(ncm, ctx, bpw):
    base = BASE_NCM16 - (ncm-16)*PER_NCM
    kv   = ctx * KIB_TOK * (bpw/16.0) / 1024.0
    return base + kv
def pick_ncm(ctx, kv):
    bpw = KV_BPW[kv]
    for ncm in (12,16,20,24,28,32,36):
        if predicted_vram(ncm, ctx, bpw) <= VRAM_TARGET:
            return ncm
    return None  # infeasible even all-CPU experts

# ---------- server lifecycle ----------
_proc=None
def _port_open():
    s=socket.socket(); s.settimeout(1)
    try: s.connect((HOST,PORT)); return True
    except Exception: return False
    finally: s.close()
def health_ok():
    try:
        with urllib.request.urlopen(BASE+"/health", timeout=3) as r:
            return json.loads(r.read().decode()).get("status")=="ok"
    except Exception: return False
def kill_tree(proc):
    if proc and proc.poll() is None:
        subprocess.run(["taskkill","/F","/T","/PID",str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def stop_server():
    global _proc
    kill_tree(_proc); _proc=None
    for _ in range(20):
        if not _port_open(): break
        time.sleep(1)

def server_cmd(ctx, kv, ncm, yarn):
    a=[EXE,"-m",MODEL,"--host",HOST,"--port",str(PORT),"-ngl","999",
       "--n-cpu-moe",str(ncm),"-c",str(ctx),"--jinja","--no-mmap","--no-webui","-fa","on"]
    if kv!="f16": a+=["-ctk",kv,"-ctv",kv]
    if yarn and ctx>32768:
        a+=["--rope-scaling","yarn","--rope-scale",f"{ctx/32768:.4f}","--yarn-orig-ctx","32768"]
    return a
def start_server(ctx, kv, ncm, yarn, tag):
    global _proc
    stop_server()
    cmd=server_cmd(ctx,kv,ncm,yarn)
    logp(f"  launch {tag}: ncm={ncm} ctx={ctx} kv={kv} yarn={bool(yarn and ctx>32768)}")
    lf=open(os.path.join(DIR,f"srv_{tag}.log"),"w")
    _proc=subprocess.Popen(cmd,stdout=lf,stderr=subprocess.STDOUT,
                           creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    deadline=time.time()+360   # no-mmap + big ctx + quant KV can be slow to load
    while time.time()<deadline:
        if _proc.poll() is not None:
            logp(f"  !! {tag} exited during load (rc={_proc.returncode}) -> likely OOM/flag"); return False
        if health_ok():
            time.sleep(1)
            v=vram_used_mib(); logp(f"  {tag} up. VRAM={v} MiB, RAM_avail={avail_ram_gb():.1f} GB"); return True
        time.sleep(2)
    logp(f"  !! {tag} health timeout"); kill_tree(_proc); return False

# ---------- slots progress (hang detection) ----------
def slot_progress():
    try:
        with urllib.request.urlopen(BASE+"/slots", timeout=4) as r:
            slots=json.loads(r.read().decode())
        best=0
        for s in slots:
            for k in ("n_past","n_prompt_tokens_processed","prompt_n","n_decoded","n_ctx"):
                v=s.get(k)
                if isinstance(v,(int,float)): best=max(best,int(v))
        return best
    except Exception:
        return -1

# ---------- guarded HTTP chat ----------
class TripError(Exception): pass
def _chat_blocking(payload, box, timeout):
    try:
        data=json.dumps(payload).encode()
        req=urllib.request.Request(BASE+"/v1/chat/completions",data=data,headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(req,timeout=timeout) as r:
            box["resp"]=json.loads(r.read().decode())
    except Exception as e:
        box["err"]=e

def chat(messages, temp=0.6, top_p=0.95, top_k=20, min_p=0.05, max_tokens=1024,
         tools=None, think=True, ctx_hint=8192):
    payload={"model":"local","stream":False,"messages":messages,"temperature":temp,
             "top_p":top_p,"top_k":top_k,"min_p":min_p,"max_tokens":max_tokens}
    if tools: payload["tools"]=tools
    if not think: payload["chat_template_kwargs"]={"enable_thinking":False}
    total_to=300 + ctx_hint/100.0     # 128k -> ~1610s ceiling
    box={}; th=threading.Thread(target=_chat_blocking,args=(payload,box,total_to+60),daemon=True);
    t0=time.time(); th.start()
    last_prog=-1; last_change=time.time(); breach=0
    while th.is_alive():
        time.sleep(3)
        v=vram_used_mib()
        breach = breach+1 if v>VRAM_KILL else 0
        ram=avail_ram_gb()
        if breach>=2 or ram<RAM_FLOOR_GB:
            raise TripError(f"resource_kill vram={v} ram={ram:.1f}")
        p=slot_progress()
        if p>=0:  # only run stall detection when /slots actually reports progress
            if p>last_prog: last_prog=p; last_change=time.time()
            if time.time()-last_change>STALL_S:
                raise TripError(f"hang_stall vram={v}")
        if time.time()-t0>total_to:
            raise TripError("total_timeout")
    if "err" in box: raise box["err"]
    r=box["resp"]; dt=time.time()-t0
    ch=r["choices"][0]; msg=ch["message"]; u=r.get("usage",{})
    ct=u.get("completion_tokens",0)
    return {"content":(msg.get("content") or "").strip(),
            "reasoning":(msg.get("reasoning_content") or ""),
            "tool_calls":msg.get("tool_calls"),"finish":ch.get("finish_reason"),
            "ctok":ct,"ptok":u.get("prompt_tokens",0),
            "tps":round(ct/dt,1) if dt>0 else 0,"dt":round(dt,1)}

# ---------- persistence ----------
_wlock=threading.Lock()
def emit(row):
    with _wlock:
        with open(RESULTS,"a",encoding="utf-8") as f:
            f.write(json.dumps(row,ensure_ascii=False)+"\n"); f.flush(); os.fsync(f.fileno())
def save_raw(cell, task, i, res, extra=None):
    p=os.path.join(RAWDIR,f"{cell}__{task}__{i}.json")
    with open(p,"w",encoding="utf-8") as f:
        json.dump({"cell":cell,"task":task,"i":i,"res":res,"extra":extra},f,ensure_ascii=False,indent=1)
    return os.path.relpath(p,DIR)
def load_done():
    d=set()
    if os.path.exists(RESULTS):
        for ln in open(RESULTS,encoding="utf-8"):
            try:
                r=json.loads(ln); d.add((r["cell"],r["task"],r["i"]))
            except Exception: pass
    return d
DONE=load_done()
def is_done(cell,task,i): return (cell,task,i) in DONE

# ---------- deterministic checkers ----------
def nums(t): return re.findall(r"-?\d+", (t or "").replace(",",""))
def ck_num(t,val): return str(val) in nums(t)
def run_code(candidate_src, test_src, timeout=20):
    """exec candidate + tests via subprocess python; exit 0 = pass."""
    code=candidate_src+"\n\n"+test_src+"\nprint('OK_PASS')\n"
    fn=os.path.join(RAWDIR,f"_tmp_{random.randint(0,10**9)}.py")
    open(fn,"w",encoding="utf-8").write(code)
    try:
        r=subprocess.run([sys.executable,fn],capture_output=True,text=True,timeout=timeout)
        return "OK_PASS" in r.stdout
    except Exception: return False
    finally:
        try: os.remove(fn)
        except Exception: pass
def extract_code(text):
    m=re.search(r"```(?:python|py)?\s*(.*?)```",text,re.S)
    return m.group(1) if m else text
def ck_fc(res,name,args):
    tc=res.get("tool_calls")
    if not tc: return False
    f=tc[0].get("function",{})
    if f.get("name")!=name: return False
    try: a=json.loads(f.get("arguments") or "{}")
    except Exception: return False
    return all(str(a.get(k,"")).strip().lower()==str(v).strip().lower() for k,v in args.items())
def ck_nofc(res): return not res.get("tool_calls")
def ck_json(text,keys):
    m=re.search(r"\{.*\}",text,re.S)
    if not m: return False
    try: o=json.loads(m.group(0))
    except Exception: return False
    return all(k in o for k in keys)
def ck_list5(text): return len([x for x in text.strip().split(",") if x.strip()])==5

# ---------- task batteries ----------
CODING=[  # (id, prompt, test_src using the model's function)
 ("code_fizz","Write a Python function fizzbuzz(n) returning a list of strings for 1..n: 'Fizz','Buzz','FizzBuzz' or the number as str. Return ONLY a python code block.",
  "r=fizzbuzz(15)\nassert r[2]=='Fizz' and r[4]=='Buzz' and r[14]=='FizzBuzz' and r[0]=='1'"),
 ("code_anagram","Write is_anagram(a,b) -> bool, case-insensitive, ignoring spaces. Return ONLY a python code block.",
  "assert is_anagram('Listen','Silent') and not is_anagram('a','ab')"),
 ("code_primes","Write primes_upto(n) returning a list of all primes <= n. Return ONLY a python code block.",
  "assert primes_upto(10)==[2,3,5,7]"),
 ("code_roman","Write to_roman(n) for 1..3999 -> roman numeral string. Return ONLY a python code block.",
  "assert to_roman(4)=='IV' and to_roman(1994)=='MCMXCIV'"),
 ("code_balanced","Write is_balanced(s) -> bool for brackets ()[]{}. Return ONLY a python code block.",
  "assert is_balanced('([]{})') and not is_balanced('([)]')"),
 ("code_flatten","Write flatten(lst) that fully flattens an arbitrarily nested list of ints. Return ONLY a python code block.",
  "assert flatten([1,[2,[3,[4]],5]])==[1,2,3,4,5]"),
 ("code_lru","Write a function two_sum(nums,target) returning indices [i,j] with nums[i]+nums[j]==target. Return ONLY a python code block.",
  "r=two_sum([2,7,11,15],9); assert sorted(r)==[0,1]"),
 ("code_rle","Write rle(s) run-length-encoding: 'aaabb'->'a3b2'. Return ONLY a python code block.",
  "assert rle('aaabb')=='a3b2' and rle('abc')=='a1b1c1'"),
]
WEATHER=[{"type":"function","function":{"name":"get_weather","description":"Current weather for a city",
  "parameters":{"type":"object","properties":{"city":{"type":"string"},"units":{"type":"string","enum":["c","f"]}},"required":["city"]}}}]
ADDTOOL=[{"type":"function","function":{"name":"add","description":"Add two integers",
  "parameters":{"type":"object","properties":{"a":{"type":"integer"},"b":{"type":"integer"}},"required":["a","b"]}}}]
DISTRACT=WEATHER+ADDTOOL+[
 {"type":"function","function":{"name":"get_time","description":"Current time in a city","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}},
 {"type":"function","function":{"name":"translate","description":"Translate text","parameters":{"type":"object","properties":{"text":{"type":"string"},"lang":{"type":"string"}},"required":["text","lang"]}}}]

def fc_battery(common):
    R=[]
    R.append(("fc_simple", lambda: (lambda r: (ck_fc(r,"get_weather",{"city":"Berlin"}),r))(chat([{"role":"user","content":"What's the weather in Berlin?"}],tools=WEATHER,max_tokens=800,**common))))
    R.append(("fc_enum", lambda: (lambda r: (ck_fc(r,"get_weather",{"city":"Paris","units":"c"}),r))(chat([{"role":"user","content":"Weather in Paris in Celsius?"}],tools=WEATHER,max_tokens=800,**common))))
    R.append(("fc_pick", lambda: (lambda r: (ck_fc(r,"add",{"a":41,"b":59}),r))(chat([{"role":"user","content":"Use a tool to add 41 and 59."}],tools=ADDTOOL,max_tokens=800,**common))))
    R.append(("fc_distract", lambda: (lambda r: (ck_fc(r,"get_weather",{"city":"Tokyo"}),r))(chat([{"role":"user","content":"I need the current weather in Tokyo."}],tools=DISTRACT,max_tokens=800,**common))))
    R.append(("fc_abstain", lambda: (lambda r: (ck_nofc(r),r))(chat([{"role":"user","content":"Write a two-line poem about rain."}],tools=WEATHER,max_tokens=400,**common))))
    return R
def fmt_battery(common):
    R=[]
    R.append(("fmt_json", lambda: (lambda r:(ck_json(r["content"],["city","population"]),r))(chat([{"role":"user","content":'Output ONLY a JSON object with keys "city","population" for Tokyo. No prose.'}],max_tokens=800,**common))))
    R.append(("fmt_list5", lambda: (lambda r:(ck_list5(r["content"]),r))(chat([{"role":"user","content":"List exactly 5 primary colors, comma-separated, one line, nothing else."}],max_tokens=400,**common))))
    R.append(("fmt_forbid", lambda: (lambda r:("e" not in r["content"].lower(),r))(chat([{"role":"user","content":"Write one sentence about a dog WITHOUT using the letter e."}],max_tokens=900,**common))))
    R.append(("fmt_words", lambda: (lambda r:(len(r["content"].split())<=10,r))(chat([{"role":"user","content":"Answer in 10 words or fewer: why is the sky blue?"}],max_tokens=900,**common))))
    return R
def code_battery(common):
    R=[]
    for cid,prompt,test in CODING:
        def mk(cid=cid,prompt=prompt,test=test):
            def f():
                r=chat([{"role":"user","content":prompt}],max_tokens=2048,**common)
                ok=run_code(extract_code(r["content"]),test)
                return ok,r
            return f
        R.append((cid,mk()))
    return R

# ---------- long-context battery (one prefix, many Q) ----------
FILLER=("The harbor town woke slowly under a pale sky. Merchants counted crates of salted fish along the pier. "
 "A gray cat slept on a coil of rope. Rain had polished the cobblestones to a dull shine. Somewhere a bell marked the hour. "
 "The baker opened his shutters and warm bread drifted out. Two fishermen argued about the price of nets. Gulls wheeled above the masts. "
 "A child chased a wooden hoop down the quay. The lighthouse keeper wrote the weather in his ledger. Ropes creaked as the tide lifted the boats. "
 "Sailors carried barrels of fresh water down a gangway. The market filled with a hundred voices. A woman sold apples from a cart. "
 "Fog rolled in from the sea and softened the town. The blacksmith's hammer rang against cold iron. Lanterns swung outside the tavern doors. ")
def make_prefix(target_tokens, seed):
    rnd=random.Random(seed)
    words=int(target_tokens/1.35)
    body=[]; w=0
    para=FILLER.split(". ")
    while w<words:
        s=rnd.choice(para).strip();
        if s: body.append(s+"."); w+=len(s.split())
    # embed items at depths
    items={}
    def put(depth, text):
        pos=max(0,min(len(body),int(len(body)*depth))); body.insert(pos,text)
    codes={}
    for d in (0.10,0.35,0.60,0.85):
        key={0.10:"north",0.35:"south",0.60:"east",0.85:"west"}[d]
        val=str(100000+(seed*7919+int(d*1000))%899999)
        codes[key]=val; put(d,f"The magic access code for the {key} lighthouse is {val}.")
    base=1000+(seed%9000)
    put(0.20,f"VAR_A7 equals {base}.")
    put(0.70,"VAR_M8 equals VAR_A7 plus 0.")
    err=(seed%4)+2
    for j in range(err): put(0.5+0.01*j, f"System logged error code E{500+j}.")
    prefix="\n".join(body)
    return prefix, {"codes":codes,"hop":str(base),"errcount":str(err)}
def ctx_battery(prefix, gt):
    """returns list of (task_id, question, checker(content)->bool)"""
    Q=[]
    for key,val in gt["codes"].items():
        Q.append((f"niah_{key}", f"What is the magic access code for the {key} lighthouse? Reply ONLY the number.",
                  (lambda v: (lambda c: ck_num(c,v)))(val)))
    Q.append(("hop", "What is the numeric value of VAR_M8? Reply ONLY the number.", lambda c: ck_num(c,gt["hop"])))
    Q.append(("aggr", "How many distinct 'System logged error code' lines appear? Reply ONLY the number.", lambda c: ck_num(c,gt["errcount"])))
    return Q

# ---------- cell runners ----------
def run_tasks(cell, tasks, n, meta):
    """tasks: list of (task_id, thunk->(ok,res)). Persist each sample."""
    for tid, thunk in tasks:
        for i in range(n):
            if is_done(cell,tid,i): continue
            row=dict(cell=cell,task=tid,i=i,**meta)
            try:
                ok,res=thunk()
                raw=save_raw(cell,tid,i,{"content":res.get("content"),"reasoning":res.get("reasoning","")[:4000],
                                         "tool_calls":res.get("tool_calls")}, meta)
                row.update(ok=bool(ok),tps=res.get("tps"),ptok=res.get("ptok"),ctok=res.get("ctok"),
                           finish=res.get("finish"),raw=raw,status="ok")
            except TripError as e:
                row.update(ok=False,status="trip",note=str(e)); emit(row)
                logp(f"    !! TRIP on {cell}/{tid}: {e} -> abort cell"); return "trip"
            except Exception as e:
                row.update(ok=False,status="err",note=str(e)[:120])
            emit(row); DONE.add((cell,tid,i))
            logp(f"    {cell}/{tid}#{i} ok={row.get('ok')} tps={row.get('tps')} pt={row.get('ptok')}")
    return "ok"

def context_cell(ctx, kv, think, n=2):
    ncm=pick_ncm(ctx,kv)
    tag=f"c{ctx//1024}k_{kv}_th{int(think)}"
    if ncm is None:
        emit(dict(cell=tag,task="PREFLIGHT",i=0,ok=False,status="skip",note="infeasible_vram",ctx=ctx,kv=kv,think=int(think)))
        logp(f"  SKIP {tag}: infeasible even all-CPU"); return
    if predicted_vram(ncm,ctx,KV_BPW[kv])>15100:
        emit(dict(cell=tag,task="PREFLIGHT",i=0,ok=False,status="skip",note="preflight_vram",ctx=ctx,kv=kv,think=int(think)))
        logp(f"  SKIP {tag}: preflight vram {predicted_vram(ncm,ctx,KV_BPW[kv]):.0f}"); return
    if not start_server(ctx,kv,ncm,yarn=True,tag=tag):
        emit(dict(cell=tag,task="STARTUP",i=0,ok=False,status="skip",note="server_failed",ctx=ctx,kv=kv,think=int(think)))
        return
    try:
        seed=ctx+sum(ord(c) for c in kv)  # stable across process restarts (no hash())
        prefix,gt=make_prefix(int(ctx*0.85), seed)  # fill ~85% of window
        common=dict(temp=0.0,think=think,ctx_hint=ctx,max_tokens=(1400 if think else 200))
        qs=ctx_battery(prefix,gt)
        tasks=[]
        for tid,q,chk in qs:
            def mk(q=q,chk=chk):
                def f():
                    r=chat([{"role":"user","content":prefix+"\n\nQuestion: "+q}],**common)
                    return chk(r["content"]),r
                return f
            tasks.append((tid,mk()))
        meta=dict(track="ctx",ctx=ctx,kv=kv,ncm=ncm,think=int(think))
        run_tasks(tag,tasks,n,meta)
    finally:
        stop_server()

def behavior_cell(temp, think, n=5):
    tag=f"beh_t{temp}_th{int(think)}"
    common=dict(temp=temp,think=think,ctx_hint=32768)
    meta=dict(track="beh",temp=temp,think=int(think))
    tasks=code_battery(common)+fc_battery(common)+fmt_battery(common)
    run_tasks(tag,tasks,n,meta)

# ---------- anchor via claude -p ----------
def anchor():
    tag="anchor_claude"
    def call(prompt,timeout=180):
        try:
            r=subprocess.run(["powershell","-NoProfile","-Command",f"claude -p @'\n{prompt}\n'@"],
                             capture_output=True,text=True,timeout=timeout)
            return r.stdout.strip()
        except Exception as e:
            return f"__ERR__{e}"
    # coding
    for cid,prompt,test in CODING:
        if is_done(tag,cid,0): continue
        out=call(prompt); ok=False if out.startswith("__ERR__") else run_code(extract_code(out),test)
        emit(dict(cell=tag,task=cid,i=0,track="anchor",ok=bool(ok),raw=save_raw(tag,cid,0,{"content":out}),
                  status=("err" if out.startswith("__ERR__") else "ok")))
        DONE.add((tag,cid,0)); logp(f"    anchor/{cid} ok={ok}")

# ---------- main ----------
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--smoke",action="store_true"); a=ap.parse_args()
    t0=time.time()
    logp(f"=== tune start (smoke={a.smoke}) resume: {len(DONE)} done rows ===")
    try:
        if a.smoke:
            # validate each mechanism once, fast
            if start_server(32768,"f16",pick_ncm(32768,"f16"),yarn=False,tag="smoke_beh"):
                try:
                    off=dict(temp=0.0,think=False,ctx_hint=32768)
                    on =dict(temp=0.6,think=True, ctx_hint=32768)
                    run_tasks("smoke_beh", code_battery(off)[:1], 1, dict(track="beh"))   # code-exec grader
                    run_tasks("smoke_beh", fc_battery(off)[:1],   1, dict(track="beh"))   # FC parse
                    run_tasks("smoke_beh", fmt_battery(on)[:1],   1, dict(track="beh"))   # enable_thinking path
                finally: stop_server()
            context_cell(8192,"f16",think=False,n=1)      # short ctx, no yarn
            context_cell(65536,"q4_0",think=False,n=1)    # yarn + quant KV + adaptive ncm
            logp("smoke done")
        else:
            # Tier 1: behavior (A/B/D) on ref-ish server @32k f16 (no yarn). Small ctx server hosts these.
            if start_server(32768,"f16",pick_ncm(32768,"f16"),yarn=False,tag="beh_server"):
                try:
                    for think,temp,n in [(True,0.6,5),(True,0.9,5),(True,0.0,3),(False,0.7,5)]:
                        behavior_cell(temp,think,n=n)
                finally: stop_server()
            # Anchor for absolute scoring
            anchor()
            # Tier 2-4: context ladder, ALL kv tiers, think OFF then ON (off first = faster core)
            CTX=[8192,16384,32768,65536,98304,131072]
            KVS=["f16","q8_0","q5_1","q4_0"]
            for think in (False,True):
                for ctx in CTX:
                    for kv in KVS:
                        context_cell(ctx,kv,think=think,n=2)
            open(DONEMARK,"w").write("done\n")
            logp("=== ALL CELLS COMPLETE ===")
    finally:
        stop_server()
        logp(f"=== tune end, runtime {round((time.time()-t0)/60,1)} min, {len(DONE)} rows ===")

if __name__=="__main__":
    main()
