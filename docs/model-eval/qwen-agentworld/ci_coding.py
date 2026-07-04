#!/usr/bin/env python3
"""Phase 3: contamination-resistant coding + gpt-oss:20b baseline (discriminative check).
NOVEL/mutated specs (not tutorial canon), EXACT function name required (no alias), edge-case asserts.
Run on BOTH Qwen (llama.cpp) and gpt-oss:20b (ollama) -> if both ceiling, battery too easy.
N>=5 @ temp 0.6, think off. Wilson CI in scorer.
"""
import json,os,re,subprocess,sys,time,urllib.request
import tune
D=os.path.dirname(os.path.abspath(__file__))
RES=os.path.join(D,"ci_coding_results.jsonl"); RAW=os.path.join(D,"ci_coding_raw"); os.makedirs(RAW,exist_ok=True)
PROG=os.path.join(D,"ci_coding_progress.log"); DONEMARK=os.path.join(D,"CICODING_DONE")
OLLAMA="http://192.168.31.203:11434/v1/chat/completions"
def logp(m): s=f"{time.strftime('%H:%M:%S')} {m}"; print(s,flush=True); open(PROG,"a",encoding="utf-8").write(s+"\n")
def emit(r):
    with open(RES,"a",encoding="utf-8") as f: f.write(json.dumps(r,ensure_ascii=False)+"\n"); f.flush(); os.fsync(f.fileno())
def dset():
    d=set()
    if os.path.exists(RES):
        for l in open(RES,encoding="utf-8"):
            try: x=json.loads(l); d.add((x["model"],x["task"],x["i"]))
            except: pass
    return d
DONE=dset()

# NOVEL tasks: (id, prompt-with-EXACT-name, entrypoint, test with EDGE cases)
TASKS=[
 ("mutfizz","Write mutfizz(n): list of strings for 1..n where multiples of 4 -> 'Fizz', of 7 -> 'Buzz', of both -> 'FizzBuzz', else str(i). Return ONLY a python code block defining exactly `mutfizz`.",
  "mutfizz","assert mutfizz(28)[27]=='FizzBuzz' and mutfizz(8)[7]=='Fizz' and mutfizz(7)[6]=='Buzz' and mutfizz(3)[0]=='1' and mutfizz(0)==[]"),
 ("vowel_ascii","Write vowel_ascii(s): sum of the ASCII codes of the vowel characters (a,e,i,o,u — lowercase only) in s. Return ONLY code defining exactly `vowel_ascii`.",
  "vowel_ascii","assert vowel_ascii('abce')==ord('a')+ord('e') and vowel_ascii('')==0 and vowel_ascii('xyz')==0"),
 ("digit_letter","Write digit_letter(s): replace each digit d (1..26) in s with the d-th lowercase letter (1->a); leave non-digits; multi-digit runs are single numbers. Return ONLY code defining exactly `digit_letter`.",
  "digit_letter","assert digit_letter('1')=='a' and digit_letter('26')=='z' and digit_letter('a3b')=='acb' and digit_letter('')==''"),
 ("distinct_sort","Write distinct_sort(words): sort by number of DISTINCT chars asc, then length asc, then lexicographically. Return ONLY code defining exactly `distinct_sort`.",
  "distinct_sort","assert distinct_sort(['aab','bb','abc','a'])==['a','bb','aab','abc'] and distinct_sort([])==[]"),
 ("even_digitsum","Write even_digitsum(n): count of integers in 1..n whose decimal digit-sum is even. Return ONLY code defining exactly `even_digitsum`.",
  "even_digitsum","assert even_digitsum(1)==0 and even_digitsum(11)==5 and even_digitsum(0)==0"),
 ("kv_parse","Write kv_parse(s): parse 'a=1;b=2;c=3' into {'a':'1','b':'2','c':'3'}; empty string -> {}; ignore trailing ';'. Return ONLY code defining exactly `kv_parse`.",
  "kv_parse","assert kv_parse('a=1;b=2')=={'a':'1','b':'2'} and kv_parse('')=={} and kv_parse('x=9;')=={'x':'9'}"),
 ("max_depth","Write max_depth(s): max nesting depth of parentheses in s; unbalanced -> return -1. Return ONLY code defining exactly `max_depth`.",
  "max_depth","assert max_depth('(())')==2 and max_depth('')==0 and max_depth('(()')==-1 and max_depth(')(')==-1"),
 ("safe_div","Write safe_div(a,b): a/b, but return None if b==0. Return ONLY code defining exactly `safe_div`.",
  "safe_div","assert safe_div(6,3)==2 and safe_div(1,0) is None and safe_div(-6,4)==-1.5"),
 ("ragged_t","Write ragged_t(rows): transpose a list of rows of unequal length, padding missing cells with None. Return ONLY code defining exactly `ragged_t`.",
  "ragged_t","assert ragged_t([[1,2],[3]])==[[1,3],[2,None]] and ragged_t([])==[]"),
 ("run_compress","Write run_compress(s): replace runs of length>=3 of the same char with char+count, runs<3 unchanged: 'aaabb'->'a3bb'. Return ONLY code defining exactly `run_compress`.",
  "run_compress","assert run_compress('aaabb')=='a3bb' and run_compress('')=='' and run_compress('ab')=='ab' and run_compress('xxxx')=='x4'"),
]
def extract(t):
    m=re.search(r"```(?:python|py)?\s*(.*?)```",t,re.S); return m.group(1) if m else t
def run_code(content,entry,test):
    if not content.strip(): return False
    code=extract(content)+"\n"+test+"\nprint('OKP')\n"
    fn=os.path.join(RAW,f"_c_{abs(hash(content))%10**8}.py"); open(fn,"w",encoding="utf-8").write(code)
    try: return "OKP" in subprocess.run([sys.executable,fn],capture_output=True,text=True,timeout=20).stdout
    except Exception: return False
    finally:
        try: os.remove(fn)
        except: pass
def chat_ollama(prompt,timeout=180):
    body=json.dumps({"model":"gpt-oss:20b","stream":False,"messages":[{"role":"user","content":prompt}],
        "temperature":0.6,"max_tokens":4000}).encode()
    req=urllib.request.Request(OLLAMA,data=body,headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=timeout) as r: j=json.loads(r.read())
    m=j["choices"][0]["message"]; return {"content":m.get("content") or "","finish":j["choices"][0].get("finish_reason")}

def run_model(model,N):
    common=dict(temp=0.6,think=False,ctx_hint=8192)
    for tid,prompt,entry,test in TASKS:
        for i in range(N):
            if (model,tid,i) in DONE: continue
            row=dict(model=model,task=tid,i=i)
            try:
                if model=="qwen": r=tune.chat([{"role":"user","content":prompt}],max_tokens=2000,**common)
                else: r=chat_ollama(prompt)
                trunc=r.get("finish")=="length"
                ok=run_code(r["content"],entry,test) and not trunc
                rp=os.path.join(RAW,f"{model}__{tid}__{i}.json"); json.dump({"content":r["content"],"finish":r.get("finish")},open(rp,"w",encoding="utf-8"),ensure_ascii=False,indent=1)
                row.update(ok=ok,trunc=trunc,status=("trunc" if trunc else "ok"),raw=os.path.relpath(rp,D))
            except tune.TripError as e:
                row.update(ok=False,status="trip",note=str(e)); emit(row); logp(f"TRIP {tid}"); return "trip"
            except Exception as e:
                row.update(ok=False,status="err",note=str(e)[:100])
            emit(row); DONE.add((model,tid,i)); logp(f"  {model}/{tid}#{i} ok={row.get('ok')} {'T' if row.get('trunc') else ''}")

def main():
    import argparse; ap=argparse.ArgumentParser(); ap.add_argument("--n",type=int,default=5); ap.add_argument("--smoke",action="store_true"); a=ap.parse_args()
    logp(f"=== ci_coding start n={a.n} smoke={a.smoke} resume={len(DONE)} ===")
    N=1 if a.smoke else a.n
    # ensure ollama's gpt-oss is UNLOADED from GPU before Qwen starts (avoid VRAM contention)
    for exe in (r"C:\Users\x3d_mutant\AppData\Local\Programs\Ollama\ollama.exe","ollama"):
        try: subprocess.run([exe,"stop","gpt-oss:20b"],timeout=30,capture_output=True); break
        except Exception: continue
    time.sleep(3)
    # QWEN FIRST (llama.cpp uses GPU); stop frees GPU before gpt-oss loads -> no VRAM contention
    if not tune.start_server(8192,"f16",12,yarn=False,tag="ci_srv"): logp("!! qwen server failed"); return
    try:
        logp("-- qwen --"); run_model("qwen",N)
    finally:
        tune.stop_server()
    time.sleep(5)  # let GPU free
    # gpt-oss:20b baseline (ollama loads it now that GPU is free)
    logp("-- gpt-oss:20b baseline --"); run_model("gptoss",N)
    if not a.smoke: open(DONEMARK,"w").write("done\n"); logp("=== CICODING DONE ===")
    logp("=== ci_coding end ===")
if __name__=="__main__": main()
