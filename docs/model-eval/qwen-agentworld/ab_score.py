import json,os,collections
d=r"C:\Users\X3D_MU~1\AppData\Local\Temp\claude\C--Users-x3d-mutant-reserch-unified-agent-platform\f2728c9f-a27f-4265-862c-7d20a6e5f660\scratchpad\overnight"
rows=[json.loads(l) for l in open(os.path.join(d,"ab_results.jsonl"),encoding="utf-8") if l.strip()]
rows=[r for r in rows if r.get("status")=="ok"]
def cat(t): return t.split("_")[0]
CFG=["A_rec64k","B_yarn128k"]; CATS=["code","fc","fmt","math"]
def rate(rs): rs=list(rs); return (sum(1 for r in rs if r.get("ok"))/len(rs),len(rs)) if rs else (0,0)
print("="*64)
print(f"{'category':>8} | {'A (64k no-yarn)':>18} | {'B (128k yarn)':>16} | delta")
print("-"*64)
tot={c:[0,0] for c in CFG}
for cat_ in CATS:
    line=f"{cat_:>8} |"
    vals={}
    for cfg in CFG:
        rr,n=rate(r for r in rows if r["cfg"]==cfg and cat(r["task"])==cat_)
        vals[cfg]=rr; line+=f" {rr*100:5.0f}% (n{n:<3}) |"
    dlt=(vals["B_yarn128k"]-vals["A_rec64k"])*100
    print(line+f" {dlt:+5.1f}%")
print("-"*64)
for cfg in CFG:
    rr,n=rate(r for r in rows if r["cfg"]==cfg)
    print(f"{'OVERALL':>8} {cfg:>12}: {rr*100:5.1f}%  (n{n})")

# per-task A vs B (spot yarn-sensitive tasks)
print("\nPer-task A vs B (only tasks where they DIFFER):")
tasks=sorted({r["task"] for r in rows})
any_diff=False
for t in tasks:
    a,_=rate(r for r in rows if r["cfg"]=="A_rec64k" and r["task"]==t)
    b,_=rate(r for r in rows if r["cfg"]=="B_yarn128k" and r["task"]==t)
    if abs(a-b)>1e-9:
        any_diff=True; print(f"  {t:20} A={a*100:3.0f}%  B={b*100:3.0f}%")
if not any_diff: print("  (none — A and B identical on every task)")

# tasks failing in BOTH (model weaknesses, not config)
print("\nTasks <100% in BOTH configs (model weak spots):")
for t in tasks:
    a,_=rate(r for r in rows if r["cfg"]=="A_rec64k" and r["task"]==t)
    b,_=rate(r for r in rows if r["cfg"]=="B_yarn128k" and r["task"]==t)
    if a<1 and b<1: print(f"  {t:20} A={a*100:3.0f}% B={b*100:3.0f}%")
