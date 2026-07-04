#!/usr/bin/env python3
import json, os, collections
DIR=os.path.dirname(os.path.abspath(__file__))
rows=[json.loads(l) for l in open(os.path.join(DIR,"results.jsonl"),encoding="utf-8")]
def cat(t):
    if t.startswith("code_"): return "A_code"
    if t.startswith("fc_"):   return "B_fc"
    if t.startswith("fmt_"):  return "D_fmt"
    return "C_ctx"
ok=lambda r: r.get("status")=="ok"
def rate(rs):
    rs=[r for r in rs if ok(r)]
    return (sum(1 for r in rs if r.get("ok"))/len(rs), len(rs)) if rs else (float('nan'),0)

print("="*70,"\nRUN SUMMARY")
st=collections.Counter(r.get("status") for r in rows)
print("rows:",len(rows),"statuses:",dict(st))

# ---------- BEHAVIOR (A/B/D) ----------
print("\n"+"="*70,"\nBEHAVIOR  (pass-rate by sampling config x category)")
beh=[r for r in rows if r.get("track")=="beh"]
cfgs=sorted({(r["temp"],r["think"]) for r in beh})
cats=["A_code","B_fc","D_fmt"]
hdr=f"{'temp':>5} {'think':>5} | "+" | ".join(f"{c:>10}" for c in cats)+" |   AVG  tps"
print(hdr); print("-"*len(hdr))
for temp,think in cfgs:
    sub=[r for r in beh if r["temp"]==temp and r["think"]==think]
    cells=[]; avg=[]
    for c in cats:
        rr,n=rate([r for r in sub if cat(r["task"])==c]); cells.append(f"{rr*100:5.0f}% n{n:<3}");
        if n: avg.append(rr)
    tps=[r["tps"] for r in sub if ok(r) and isinstance(r.get("tps"),(int,float))]
    a=sum(avg)/len(avg)*100 if avg else float('nan')
    print(f"{temp:>5} {think:>5} | "+" | ".join(cells)+f" | {a:4.0f}% {sum(tps)/len(tps) if tps else 0:5.1f}")

# per-coding-task reliability at best configs
print("\nPer-coding-task pass-rate (think=1,temp=0.6 vs think=0,temp=0.7):")
for temp,think in [(0.6,1),(0.7,0)]:
    sub=[r for r in beh if r["temp"]==temp and r["think"]==think and cat(r["task"])=="A_code"]
    by=collections.defaultdict(list)
    for r in sub:
        if ok(r): by[r["task"]].append(r["ok"])
    line=" ".join(f"{t.split('_')[1]}:{int(sum(v)/len(v)*100)}%" for t,v in sorted(by.items()))
    print(f"  t{temp}/th{think}: {line}")

# ---------- CONTEXT (C) ----------
print("\n"+"="*70,"\nCONTEXT  (NIAH+hop recall by ctx x kv, think split)")
ctx=[r for r in rows if r.get("track")=="ctx"]
CTX=sorted({r["ctx"] for r in ctx if "ctx" in r})
KVS=["f16","q8_0","q5_1","q4_0"]
for think in (0,1):
    print(f"\n-- think={think} --")
    hdr=f"{'ctx':>7} | "+" | ".join(f"{k:>12}" for k in KVS)
    print(hdr); print("-"*len(hdr))
    for c in CTX:
        cells=[]
        for kv in KVS:
            sub=[r for r in ctx if r.get("ctx")==c and r.get("kv")==kv and r.get("think")==think
                 and r["task"].startswith(("niah_","hop"))]
            done=[r for r in sub if ok(r)]
            if not sub: cells.append(f"{'-':>12}")
            elif not done: cells.append(f"{'TRIP':>12}")
            else:
                rr=sum(1 for r in done if r.get("ok"))/len(done); cells.append(f"{rr*100:6.0f}% n{len(done):<3}")
        print(f"{c:>7} | "+" | ".join(cells))
# aggregation task separately
print("\nAggregation task pass-rate by ctx (f16, think=0):")
for c in CTX:
    sub=[r for r in ctx if r.get("ctx")==c and r.get("kv")=="f16" and r.get("think")==0 and r["task"]=="aggr" and ok(r)]
    if sub: print(f"  {c}: {int(sum(1 for r in sub if r['ok'])/len(sub)*100)}% (n{len(sub)})")

# ---------- ANCHOR ----------
print("\n"+"="*70,"\nANCHOR")
anc=[r for r in rows if r.get("track")=="anchor"]
print(f"anchor rows: {len(anc)}, all ok={all(not r.get('ok') for r in anc)} (BROKEN: claude CLI not logged in)")

# ---------- trips ----------
print("\nTRIPS (aborted cells):")
for r in rows:
    if r.get("status")=="trip": print(f"  {r['cell']}/{r['task']}: {r.get('note')}")
