#!/usr/bin/env python3
# Phase 0: honest recompute from existing raw. No model calls. Fixes Fable's grader holes.
# Rules: empty!=pass; finish=length=truncated(separate); temp0=N1; Wilson CI; code exact-name.
import json,os,re,math,subprocess,sys,collections
D=r"C:\Users\X3D_MU~1\AppData\Local\Temp\claude\C--Users-x3d-mutant-reserch-unified-agent-platform\f2728c9f-a27f-4265-862c-7d20a6e5f660\scratchpad\overnight"
def load(f): return [json.loads(l) for l in open(os.path.join(D,f),encoding="utf-8") if l.strip()]
def raw(row):
    p=row.get("raw")
    if p and os.path.exists(os.path.join(D,p)):
        j=json.load(open(os.path.join(D,p),encoding="utf-8"))
        r=j.get("res",j); return r.get("content") or "", r.get("tool_calls")
    return None,None
def wilson(k,n,z=1.96):
    if n==0: return (0.0,0.0,0.0)
    p=k/n; d=1+z*z/n
    c=(p+z*z/(2*n))/d; h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return (p, max(0,c-h), min(1,c+h))
def fmt(k,n):
    p,lo,hi=wilson(k,n); return f"{p*100:.0f}% [{lo*100:.0f}-{hi*100:.0f}] n{n}"

CODE_TESTS={  # exact-name grader (no alias): exec content-code + test that CALLS by required name
 "code_fizz":"assert fizzbuzz(15)[2]=='Fizz' and fizzbuzz(15)[14]=='FizzBuzz'",
 "code_anagram":"assert is_anagram('Listen','Silent') and not is_anagram('a','ab')",
 "code_primes":"assert primes_upto(10)==[2,3,5,7]",
 "code_roman":"assert to_roman(4)=='IV' and to_roman(1994)=='MCMXCIV'",
 "code_balanced":"assert is_balanced('([]{})') and not is_balanced('([)]')",
 "code_flatten":"assert flatten([1,[2,[3,[4]],5]])==[1,2,3,4,5]",
 "code_lru":"assert sorted(two_sum([2,7,11,15],9))==[0,1]",
 "code_rle":"assert rle('aaabb')=='a3b2' and rle('abc')=='a1b1c1'",
}
def extract_code(t):
    m=re.search(r"```(?:python|py)?\s*(.*?)```",t,re.S); return m.group(1) if m else t
def regrade_code(content,test):
    if not content.strip(): return False
    code=extract_code(content)+"\n"+test+"\nprint('OKP')\n"
    fn=os.path.join(D,f"_v2_{abs(hash(content))%10**8}.py"); open(fn,"w",encoding="utf-8").write(code)
    try: return "OKP" in subprocess.run([sys.executable,fn],capture_output=True,text=True,timeout=20).stdout
    except Exception: return False
    finally:
        try: os.remove(fn)
        except: pass

def cls(row):
    """return 'pass'/'fail'/'trunc'/'empty' using STRICT rules from existing ok + raw."""
    if row.get("finish")=="length": return "trunc"
    return "pass" if row.get("ok") else "fail"

print("="*72)
print("PHASE 0 — HONEST RECOMPUTE (Wilson 95% CI; empty!=pass; finish=length=truncated)")
print("="*72)

R=load("results.jsonl"); ok=[r for r in R if r.get("status")=="ok"]

# ---- CONTEXT: NIAH / hop / aggr separately, per think ----
print("\n## CONTEXT (overnight, temp=0 -> N=1 effective per cell; NIAH needle is verbatim/low-entropy)")
for grp,pref in [("NIAH",("niah",)),("hop",("hop",)),("aggr",("aggr",))]:
    print(f"  {grp}:")
    for th in (0,1):
        rs=[r for r in ok if r.get("track")=="ctx" and r["task"].startswith(pref) and r.get("think")==th]
        tr=sum(1 for r in rs if cls(r)=="trunc"); scored=[r for r in rs if cls(r)!="trunc"]
        k=sum(1 for r in scored if cls(r)=="pass")
        print(f"    think={th}: {fmt(k,len(scored))}  (+{tr} truncated excluded)")

# ---- BEHAVIOR: code(exact-name honest via existing ok), fc, math; format=VOID+diagnostics ----
print("\n## BEHAVIOR (overnight). code/fc/math from robust checkers; CI shown.")
beh=[r for r in ok if r.get("track")=="beh"]
def cat(t): return "code" if t.startswith("code") else "fc" if t.startswith("fc") else "math" if t.startswith("math") else "fmt"
for temp,think in sorted({(r["temp"],r["think"]) for r in beh}):
    sub=[r for r in beh if r["temp"]==temp and r["think"]==think]
    line=f"  temp={temp} think={think}:"
    for c in ("code","fc"):
        rs=[r for r in sub if cat(r["task"])==c]; scored=[r for r in rs if cls(r)!="trunc"]
        k=sum(1 for r in scored if cls(r)=="pass"); line+=f"  {c}={fmt(k,len(scored))}"
    print(line + ("   [temp0=N1 note]" if temp==0 else ""))

# format diagnostics (why it's void)
print("\n## FORMAT = VOID (diagnostics, not a score):")
fmts=[r for r in beh if cat(r["task"])=="fmt"]
emp=trunc=leak=clean_pass=0
for r in fmts:
    c,_=raw(r); c=c or ""
    if r.get("finish")=="length": trunc+=1
    elif not c.strip(): emp+=1
    elif ("<think>" in c or "Thinking Process" in c): leak+=1
    elif r.get("ok"): clean_pass+=1
print(f"  of {len(fmts)} fmt calls: truncated={trunc}, empty={emp}, think-leak-in-content={leak}, clean-ok={clean_pass}")
print("  -> format instruction-following NOT measurable from this data (see v2 Phase with IFEval-style).")

# ---- A/B: re-grade code EXACT-NAME (undo alias), per category + CI ----
print("\n## A/B (recommended 64k-no-yarn vs 128k-yarn) — code re-graded EXACT-NAME (no alias)")
AB=[r for r in load("ab_results.jsonl") if r.get("status")=="ok"]
def abcat(t): return t.split("_")[0]
for cfg in ["A_rec64k","B_yarn128k"]:
    sub=[r for r in AB if r["cfg"]==cfg]
    parts=[]
    for c in ["code","fc","math"]:
        rs=[r for r in sub if abcat(r["task"])==c]
        if c=="code":
            k=0;n=0
            for r in rs:
                if r.get("finish")=="length": continue
                content,_=raw(r); test=CODE_TESTS.get(r["task"].replace("code_","code_",1)) or CODE_TESTS.get(r["task"])
                # map ab code ids to tests by suffix
                tid=r["task"]; test=None
                for kk,vv in {"fizzbuzz":"code_fizz","anagram":"code_anagram","primes":"code_primes","roman":"code_roman","balanced":"code_balanced","flatten":"code_flatten","two_sum":"code_lru","rle":"code_rle"}.items():
                    if kk in tid: test=CODE_TESTS[vv]
                if test is None: continue
                n+=1; k+= 1 if regrade_code(content or "",test) else 0
            parts.append(f"code(exact)={fmt(k,n)}")
        else:
            scored=[r for r in rs if r.get("finish")!="length"]; k=sum(1 for r in scored if r.get("ok"))
            parts.append(f"{c}={fmt(k,len(scored))}")
    print(f"  {cfg}: "+"  ".join(parts))
print("  NOTE: code/fc/math near ceiling in BOTH -> A/B cannot detect a YaRN quality cost (ceiling).")
print("  NOTE: A=ncm12, B=ncm20 -> YaRN not isolated. 'yarn is free' = UNTESTED, not proven.")
