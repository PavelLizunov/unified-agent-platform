#!/usr/bin/env python3
"""Phase 2: self-verification. THE 'self-test is the gate' premise.
Given code + a PASSING (but possibly weak) test suite, can the model judge whether the code is
actually correct for ALL valid inputs, or catch a bug the weak tests miss?
Single-turn judgment. N>=5 @ temp 0.6, think on/off. Graded by verdict vs ground truth. Wilson CI in scorer.
"""
import json,os,re,time
import tune
D=os.path.dirname(os.path.abspath(__file__))
RES=os.path.join(D,"selfverify_results.jsonl"); RAW=os.path.join(D,"selfverify_raw"); os.makedirs(RAW,exist_ok=True)
PROG=os.path.join(D,"selfverify_progress.log"); DONEMARK=os.path.join(D,"SELFVERIFY_DONE")
def logp(m): s=f"{time.strftime('%H:%M:%S')} {m}"; print(s,flush=True); open(PROG,"a",encoding="utf-8").write(s+"\n")
def emit(r):
    with open(RES,"a",encoding="utf-8") as f: f.write(json.dumps(r,ensure_ascii=False)+"\n"); f.flush(); os.fsync(f.fileno())
def done_set():
    d=set()
    if os.path.exists(RES):
        for l in open(RES,encoding="utf-8"):
            try: r=json.loads(l); d.add((r["case"],r["think"],r["i"]))
            except: pass
    return d
DONE=done_set()

# case = (id, code, tests, ground_truth 'CORRECT'|'BUGGY', kind)
CASES=[
 # --- subtly wrong but the shown tests PASS (the discriminating cases) ---
 ("prime_1","def is_prime(n):\n    if n<2: return n==1\n    for d in range(2,int(n**0.5)+1):\n        if n%d==0: return False\n    return True",
  "assert is_prime(2) and is_prime(7) and not is_prime(9)",  # never tests n=1
  "BUGGY","subtle"),  # returns True for 1
 ("median_even","def median(xs):\n    xs=sorted(xs); return xs[len(xs)//2]",
  "assert median([3,1,2])==2 and median([9,5,1])==5",  # only odd lengths
  "BUGGY","subtle"),  # wrong for even length
 ("bsearch_edge","def bsearch(a,t):\n    lo,hi=0,len(a)-1\n    while lo<hi:\n        m=(lo+hi)//2\n        if a[m]<t: lo=m+1\n        else: hi=m\n    return a[lo]==t",
  "assert bsearch([1,3,5,7],5) and not bsearch([1,3,5,7],4)",  # misses empty list -> IndexError
  "BUGGY","subtle"),
 ("average_intdiv","def average(xs):\n    return sum(xs)//len(xs)",
  "assert average([2,4,6])==4",  # integer case passes; hides that // truncates
  "BUGGY","subtle"),  # average([1,2])==1 not 1.5 -> integer division bug
 # --- correct code, passing tests (must NOT false-flag) ---
 ("factorial_ok","def fact(n):\n    r=1\n    for i in range(2,n+1): r*=i\n    return r",
  "assert fact(0)==1 and fact(5)==120","CORRECT","correct"),
 ("gcd_ok","def gcd(a,b):\n    while b: a,b=b,a%b\n    return a",
  "assert gcd(48,36)==12 and gcd(17,5)==1","CORRECT","correct"),
 ("reverse_ok","def rev(s):\n    return s[::-1]",
  "assert rev('abc')=='cba' and rev('')==''","CORRECT","correct"),
 # --- obvious bug, tests would fail if run ---
 ("add_wrong","def add(a,b):\n    return a-b",
  "# (suite claims these pass)\nassert add(2,3)==5","BUGGY","obvious"),
]
PROMPT=("Review this Python function. Its accompanying tests are shown and reportedly PASS.\n\n"
 "```python\n{code}\n```\n\nTests (reported passing):\n```python\n{tests}\n```\n\n"
 "Is the function correct for ALL valid inputs, or is there a bug the tests fail to catch? "
 "Think carefully about edge cases the tests don't cover. "
 "End your answer with exactly one line: 'VERDICT: CORRECT' or 'VERDICT: BUGGY'.")
def verdict(content):
    m=re.findall(r"VERDICT:\s*(CORRECT|BUGGY)", content.upper())
    if m: return m[-1]
    # fallback: last mention
    c=content.upper()
    ic,ib=c.rfind("CORRECT"),c.rfind("BUGGY")
    return "BUGGY" if ib>ic else ("CORRECT" if ic>=0 else "")

def run(think,N):
    common=dict(temp=0.6,think=think,ctx_hint=8192)
    for cid,code,tests,gt,kind in CASES:
        for i in range(N):
            if (cid,int(think),i) in DONE: continue
            row=dict(case=cid,kind=kind,gt=gt,think=int(think),i=i)
            try:
                r=tune.chat([{"role":"user","content":PROMPT.format(code=code,tests=tests)}],max_tokens=6000,**common)
                v=verdict(r["content"] or "")
                trunc=r.get("finish")=="length"
                ok=(v==gt) and not trunc
                rp=os.path.join(RAW,f"{cid}__th{int(think)}__{i}.json"); json.dump({"content":r["content"],"verdict":v,"gt":gt,"finish":r.get("finish")},open(rp,"w",encoding="utf-8"),ensure_ascii=False,indent=1)
                row.update(ok=ok,verdict=v,trunc=trunc,status=("trunc" if trunc else "ok"),raw=os.path.relpath(rp,D))
            except tune.TripError as e:
                row.update(ok=False,status="trip",note=str(e)); emit(row); logp(f"TRIP {cid}: {e}"); return "trip"
            except Exception as e:
                row.update(ok=False,status="err",note=str(e)[:100])
            emit(row); DONE.add((cid,int(think),i)); logp(f"  {cid}({row['gt']}) th{int(think)}#{i} verdict={row.get('verdict')} ok={row.get('ok')} {'TRUNC' if row.get('trunc') else ''}")

def main():
    import argparse; ap=argparse.ArgumentParser(); ap.add_argument("--n",type=int,default=5); ap.add_argument("--smoke",action="store_true"); a=ap.parse_args()
    logp(f"=== selfverify start n={a.n} smoke={a.smoke} resume={len(DONE)} ===")
    if not tune.start_server(8192,"f16",12,yarn=False,tag="sv_srv"): logp("!! server failed"); return
    try:
        if a.smoke: run(False,1)
        else:
            run(False,a.n); run(True,a.n); open(DONEMARK,"w").write("done\n"); logp("=== SELFVERIFY DONE ===")
    finally:
        tune.stop_server(); logp("=== selfverify end ===")
if __name__=="__main__": main()
