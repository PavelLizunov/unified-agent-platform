#!/usr/bin/env python3
"""A/B: recommended 64k-no-yarn vs 128k-yarn, large battery, head-to-head.
Isolates the ONLY real difference (YaRN) — does 128k cost quality on normal tasks?
Reuses server/chat/watchdog/checkers from tune.py. Own results file. Resumable.
"""
import json,os,re,subprocess,sys,random,time
import tune  # reuse: chat, start_server, stop_server, TripError, extract_code, ck_* , tool defs
DIR=os.path.dirname(os.path.abspath(__file__))
RES=os.path.join(DIR,"ab_results.jsonl"); RAW=os.path.join(DIR,"ab_raw"); os.makedirs(RAW,exist_ok=True)
PROG=os.path.join(DIR,"ab_progress.log"); DONEMARK=os.path.join(DIR,"AB_DONE")
def logp(m):
    s=f"{time.strftime('%H:%M:%S')} {m}"; print(s,flush=True)
    open(PROG,"a",encoding="utf-8").write(s+"\n")
def emit(r):
    with open(RES,"a",encoding="utf-8") as f: f.write(json.dumps(r,ensure_ascii=False)+"\n"); f.flush(); os.fsync(f.fileno())
def save_raw(cell,task,i,res):
    p=os.path.join(RAW,f"{cell}__{task}__{i}.json"); json.dump(res,open(p,"w",encoding="utf-8"),ensure_ascii=False,indent=1)
    return os.path.relpath(p,DIR)
def load_done():
    d=set()
    if os.path.exists(RES):
        for l in open(RES,encoding="utf-8"):
            try: r=json.loads(l); d.add((r["cell"],r["task"],r["i"]))
            except: pass
    return d
DONE=load_done()

# ---- FIXED code grader: alias first user-defined fn to expected entry if missing ----
def run_code(src, entry, test_src, timeout=20):
    code=(src+"\n"
      f"_g=dict(globals())\n"
      f"if '{entry}' not in _g or not callable(_g.get('{entry}')):\n"
      f"    _c=[k for k,v in _g.items() if callable(v) and getattr(v,'__module__',None)=='__main__' and not k.startswith('_')]\n"
      f"    if _c: globals()['{entry}']=_g[_c[-1]]\n"
      +test_src+"\nprint('OK_PASS')\n")
    fn=os.path.join(RAW,f"_t_{random.randint(0,10**9)}.py"); open(fn,"w",encoding="utf-8").write(code)
    try:
        r=subprocess.run([sys.executable,fn],capture_output=True,text=True,timeout=timeout)
        return "OK_PASS" in r.stdout
    except Exception: return False
    finally:
        try: os.remove(fn)
        except: pass

# ================= BATTERY =================
# Coding: (id, prompt, entrypoint, test)
CODE=[
 ("fizzbuzz","Write fizzbuzz(n) -> list of strings for 1..n ('Fizz'/'Buzz'/'FizzBuzz'/str(num)). ONLY a python code block.","fizzbuzz","assert fizzbuzz(15)[2]=='Fizz' and fizzbuzz(15)[4]=='Buzz' and fizzbuzz(15)[14]=='FizzBuzz'"),
 ("anagram","Write is_anagram(a,b)->bool, case-insensitive, ignore spaces. ONLY code block.","is_anagram","assert is_anagram('Listen','Silent') and not is_anagram('a','ab')"),
 ("primes","Write primes_upto(n)->list of primes <= n. ONLY code block.","primes_upto","assert primes_upto(10)==[2,3,5,7]"),
 ("roman","Write to_roman(n) for 1..3999 -> roman numeral. ONLY code block.","to_roman","assert to_roman(4)=='IV' and to_roman(1994)=='MCMXCIV'"),
 ("balanced","Write is_balanced(s)->bool for ()[]{}. ONLY code block.","is_balanced","assert is_balanced('([]{})') and not is_balanced('([)]')"),
 ("flatten","Write flatten(lst) fully flattening nested lists of ints. ONLY code block.","flatten","assert flatten([1,[2,[3,[4]],5]])==[1,2,3,4,5]"),
 ("two_sum","Write two_sum(nums,target)->indices [i,j] with nums[i]+nums[j]==target. ONLY code block.","two_sum","assert sorted(two_sum([2,7,11,15],9))==[0,1]"),
 ("rle","Write rle(s) run-length-encoding: 'aaabb'->'a3b2'. ONLY code block.","rle","assert rle('aaabb')=='a3b2' and rle('abc')=='a1b1c1'"),
 ("palindrome","Write is_palindrome(s)->bool ignoring case, spaces, punctuation. ONLY code block.","is_palindrome","assert is_palindrome('A man, a plan, a canal: Panama') and not is_palindrome('abc')"),
 ("gcd","Write my_gcd(a,b)->greatest common divisor. ONLY code block.","my_gcd","assert my_gcd(48,36)==12 and my_gcd(17,5)==1"),
 ("fib","Write fib(n)->nth Fibonacci (fib(0)=0,fib(1)=1). ONLY code block.","fib","assert fib(10)==55 and fib(0)==0"),
 ("vowels","Write count_vowels(s)->int number of vowels (aeiou, case-insensitive). ONLY code block.","count_vowels","assert count_vowels('Hello World')==3"),
 ("merge","Write merge_sorted(a,b) merging two sorted lists into one sorted list. ONLY code block.","merge_sorted","assert merge_sorted([1,3,5],[2,4,6])==[1,2,3,4,5,6]"),
 ("caesar","Write caesar(s,k) shifting letters by k (wrap, keep case, non-letters unchanged). ONLY code block.","caesar","assert caesar('abc',1)=='bcd' and caesar('xyz',3)=='abc'"),
 ("mode","Write most_frequent(lst)->the most common element. ONLY code block.","most_frequent","assert most_frequent([1,2,2,3,2,1])==2"),
 ("dedup","Write dedup(lst) removing duplicates preserving first-seen order. ONLY code block.","dedup","assert dedup([1,2,1,3,2,4])==[1,2,3,4]"),
]
# Format/instruction: (id, prompt, checker(content)->bool)
def _wc(s): return len(s.split())
FMT=[
 ("json_keys",'Output ONLY a JSON object with keys "city" and "population" for Tokyo. No prose.', lambda c: tune.ck_json(c,["city","population"])),
 ("list5","List exactly 5 primary colors, comma-separated, one line, nothing else.", tune.ck_list5),
 ("no_e","Write one sentence about a dog WITHOUT the letter e.", lambda c: len(c)>5 and "e" not in c.lower()),
 ("le10","Answer in 10 words or fewer: why is the sky blue?", lambda c: 0<_wc(c)<=10),
 ("upper","Reply with the word 'hello' in ALL CAPS and nothing else.", lambda c: "HELLO" in c and c.strip().isupper()),
 ("three_lines","Write exactly three lines, each a color name. Nothing else.", lambda c: len([x for x in c.strip().splitlines() if x.strip()])==3),
 ("json_arr","Output ONLY a JSON array of the first 3 even numbers.", lambda c: (lambda m: bool(m) and json.loads(m.group(0))==[2,4,6])(re.search(r"\[.*?\]",c,re.S))),
 ("prefix","Answer the question, starting your reply with the word 'Because'. Why do we sleep?", lambda c: c.strip().startswith("Because")),
]
# Reasoning/math: (id, prompt, answer-substring)
MATH=[
 ("mul","What is 23*17? Reply only the number.","391"),
 ("div","What is 144 divided by 12? Only the number.","12"),
 ("pow","What is 2 to the power 10? Only the number.","1024"),
 ("word1","A train travels 60 km in 1.5 hours. Its average speed in km/h? Only the number.","40"),
 ("word2","If 3 apples cost 90 cents, how many cents does 1 apple cost? Only the number.","30"),
 ("km","How many meters are in 2.5 kilometers? Only the number.","2500"),
 ("seq","Next number in 2,4,8,16,...? Only the number.","32"),
 ("pct","What is 15% of 200? Only the number.","30"),
]

def build_tasks(common):
    T=[]
    for cid,prompt,entry,test in CODE:
        def mk(prompt=prompt,entry=entry,test=test):
            def f():
                r=tune.chat([{"role":"user","content":prompt}],max_tokens=1024,**common)
                return run_code(tune.extract_code(r["content"]),entry,test),r
            return f
        T.append(("code_"+cid,mk()))
    # FC
    W=tune.WEATHER; A=tune.ADDTOOL; D=tune.DISTRACT
    fc=[
     ("fc_simple",lambda: (lambda r:(tune.ck_fc(r,"get_weather",{"city":"Berlin"}),r))(tune.chat([{"role":"user","content":"What's the weather in Berlin?"}],tools=W,max_tokens=700,**common))),
     ("fc_enum",lambda: (lambda r:(tune.ck_fc(r,"get_weather",{"city":"Paris","units":"c"}),r))(tune.chat([{"role":"user","content":"Weather in Paris in Celsius?"}],tools=W,max_tokens=700,**common))),
     ("fc_pick",lambda: (lambda r:(tune.ck_fc(r,"add",{"a":41,"b":59}),r))(tune.chat([{"role":"user","content":"Use a tool to add 41 and 59."}],tools=A,max_tokens=700,**common))),
     ("fc_distract",lambda: (lambda r:(tune.ck_fc(r,"get_weather",{"city":"Tokyo"}),r))(tune.chat([{"role":"user","content":"Current weather in Tokyo please."}],tools=D,max_tokens=700,**common))),
     ("fc_abstain",lambda: (lambda r:(tune.ck_nofc(r),r))(tune.chat([{"role":"user","content":"Write a two-line poem about rain."}],tools=W,max_tokens=400,**common))),
     ("fc_abstain2",lambda: (lambda r:(tune.ck_nofc(r),r))(tune.chat([{"role":"user","content":"Translate 'hello' to French."}],tools=A,max_tokens=400,**common))),
     ("fc_parallel",lambda: (lambda r:(_par_ok(r),r))(tune.chat([{"role":"user","content":"Get the weather in Paris and in Tokyo."}],tools=W,max_tokens=700,**common))),
     ("fc_multiturn",lambda: (lambda r:(("15" in r["content"]),r))(tune.chat([
         {"role":"user","content":"What's the weather in Rome?"},
         {"role":"assistant","content":"","tool_calls":[{"id":"c1","type":"function","function":{"name":"get_weather","arguments":"{\"city\":\"Rome\"}"}}]},
         {"role":"tool","tool_call_id":"c1","content":"15C and sunny"}],tools=W,max_tokens=500,**common))),
    ]
    T+=fc
    for fid,prompt,chk in FMT:
        def mkf(prompt=prompt,chk=chk):
            def f():
                r=tune.chat([{"role":"user","content":prompt}],max_tokens=600,**common)
                try: ok=bool(chk(r["content"]))
                except Exception: ok=False
                return ok,r
            return f
        T.append(("fmt_"+fid,mkf()))
    for mid,prompt,ans in MATH:
        def mkm(prompt=prompt,ans=ans):
            def f():
                r=tune.chat([{"role":"user","content":prompt}],max_tokens=500,**common)
                return (ans in re.findall(r"-?\d+", r["content"].replace(",",""))),r
            return f
        T.append(("math_"+mid,mkm()))
    return T
def _par_ok(r):
    tc=r.get("tool_calls") or []
    cities={json.loads(c["function"]["arguments"]).get("city","").lower() for c in tc if c.get("function",{}).get("name")=="get_weather"}
    return {"paris","tokyo"}<=cities or len(cities)>=2

CONFIGS=[
 dict(tag="A_rec64k",  ctx=65536, kv="f16", ncm=12, yarn=False),
 dict(tag="B_yarn128k",ctx=131072,kv="f16", ncm=20, yarn=True),
]
def run_config(cfg,N):
    tag=cfg["tag"]
    if not tune.start_server(cfg["ctx"],cfg["kv"],cfg["ncm"],cfg["yarn"],tag):
        logp(f"!! {tag} start failed"); emit(dict(cell=tag,task="STARTUP",i=0,ok=False,status="server_failed")); return
    try:
        common=dict(temp=0.6,think=False,ctx_hint=cfg["ctx"])
        tasks=build_tasks(common)
        v=tune.vram_used_mib(); logp(f"{tag} up VRAM={v}. {len(tasks)} tasks x N={N}")
        for tid,thunk in tasks:
            for i in range(N):
                if (tag,tid,i) in DONE: continue
                row=dict(cell=tag,task=tid,i=i,cfg=tag)
                try:
                    ok,res=thunk()
                    row.update(ok=bool(ok),tps=res.get("tps"),ptok=res.get("ptok"),finish=res.get("finish"),
                               status="ok",raw=save_raw(tag,tid,i,{"content":res.get("content"),"tool_calls":res.get("tool_calls"),"reasoning":res.get("reasoning","")[:2000]}))
                except tune.TripError as e:
                    row.update(ok=False,status="trip",note=str(e)); emit(row); logp(f"  TRIP {tag}/{tid}: {e}"); return
                except Exception as e:
                    row.update(ok=False,status="err",note=str(e)[:100])
                emit(row); DONE.add((tag,tid,i))
            logp(f"  {tag}/{tid} done")
    finally:
        tune.stop_server()

def main():
    import argparse; ap=argparse.ArgumentParser(); ap.add_argument("--n",type=int,default=4); a=ap.parse_args()
    logp(f"=== A/B start N={a.n} resume={len(DONE)} ===")
    try:
        for cfg in CONFIGS: run_config(cfg,a.n)
        open(DONEMARK,"w").write("done\n"); logp("=== A/B DONE ===")
    finally:
        tune.stop_server()

if __name__=="__main__": main()
