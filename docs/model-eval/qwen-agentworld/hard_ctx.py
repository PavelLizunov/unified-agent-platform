#!/usr/bin/env python3
"""Phase 4: HARD long-context on the RECOMMENDED config (q4_0 KV + YaRN, temp 0, think off).
Fixes v1's easy-NIAH: PARAPHRASED needle (semantic, not verbatim), MULTI-KEY interference (5 similar facts),
REASONING over scattered facts (which is largest). Higher-entropy filler. Seed varies per sample = real replication.
Grade: exact value / correct entity. Wilson CI in scorer. Cells: ctx {32,64,96,128k}.
"""
import json,os,re,random,time
import tune
D=os.path.dirname(os.path.abspath(__file__))
RES=os.path.join(D,"hard_ctx_results.jsonl"); RAW=os.path.join(D,"hard_ctx_raw"); os.makedirs(RAW,exist_ok=True)
PROG=os.path.join(D,"hard_ctx_progress.log"); DONEMARK=os.path.join(D,"HARDCTX_DONE")
def logp(m): s=f"{time.strftime('%H:%M:%S')} {m}"; print(s,flush=True); open(PROG,"a",encoding="utf-8").write(s+"\n")
def emit(r):
    with open(RES,"a",encoding="utf-8") as f: f.write(json.dumps(r,ensure_ascii=False)+"\n"); f.flush(); os.fsync(f.fileno())
def dset():
    d=set()
    if os.path.exists(RES):
        for l in open(RES,encoding="utf-8"):
            try: x=json.loads(l); d.add((x["ctx"],x["task"],x["seed"]))
            except: pass
    return d
DONE=dset()
# higher-entropy filler pool (40 distinct sentences)
POOL=("""The cartographer folded the map twice before the wind could claim it. A kettle whistled somewhere down the
corridor. Rust had crept along the iron railing overlooking the bay. The auditor initialed each page without reading
it. Three sparrows quarreled over a crust on the windowsill. The elevator groaned between the fourth and fifth floors.
A violinist tuned an open string until it rang true. The greenhouse smelled of wet loam and bruised basil. Someone had
chalked a hopscotch grid across the loading dock. The archivist labeled the crate in careful block capitals. Frost
etched ferns across the inside of the pane. The night bus idled at the terminus, engine ticking. A moth circled the
desk lamp in tightening loops. The bakery's ovens had been cold for a decade. Gravel shifted under the weight of the
parked lorry. The lighthouse beam swept the harbor once every twelve seconds. A clerk stamped the ledger and slid it
back. The orchard's last apples hung dark and unpicked. Static hissed from a radio left between stations. The tailor
measured twice and cut once, as always. Pigeons roosted in the clock tower's broken face. A child traced circuits in
a fogged shop window. The ferry's horn flattened against the low grey sky. Salt had seized the padlock on the boathouse
door. The librarian reshelved the atlas under the wrong century. Wind turbines turned slow on the far ridge. A courier
leaned his bicycle against the fountain. The cellar flooded again after the spring thaw. Someone practiced scales two
floors up, never finishing. The market stalls came down as the rain began.""").replace("\n"," ")
SENTS=[s.strip()+"." for s in POOL.split(".") if s.strip()]
NAMES=["Aurora","Basalt","Cinder","Dovetail","Ember","Fathom","Gossamer","Halcyon","Iris","Juniper"]
def build(ctx_tokens, seed):
    rnd=random.Random(seed)
    names=rnd.sample(NAMES,5)
    budgets={n: rnd.randrange(10000,990000,1000) for n in names}
    facts=[f"Project {n}'s allocated budget is {v} dollars." for n,v in budgets.items()]
    words=int(ctx_tokens*0.82/1.35); body=[]; w=0
    while w<words:
        s=rnd.choice(SENTS); body.append(s); w+=len(s.split())
    for fct in facts:  # scatter the 5 facts at spread positions
        pos=rnd.randrange(0,len(body)); body.insert(pos,fct)
    prefix="\n".join(body)
    target=names[0]; other=names[3]
    top=max(budgets,key=budgets.get)
    Q=[("paraphrase", f"How much money was set aside for the {target} initiative? Reply with ONLY the dollar number.", str(budgets[target])),
       ("multikey",   f"What is the budget of Project {other}? Reply with ONLY the dollar number.", str(budgets[other])),
       ("reasoning",  "Of all the projects mentioned, which single project has the LARGEST budget? Reply with ONLY the project name.", top)]
    return prefix,Q
def check(kind,content,gt):
    if kind=="reasoning": return gt.lower() in (content or "").lower()
    return gt in re.findall(r"\d+",(content or "").replace(",",""))
def run(ctx,seeds):
    for seed in range(seeds):
        prefix,Q=build(ctx,1000+seed)
        for kind,q,gt in Q:
            if (ctx,kind,seed) in DONE: continue
            row=dict(ctx=ctx,task=kind,seed=seed,gt=gt)
            try:
                r=tune.chat([{"role":"user","content":prefix+"\n\nQuestion: "+q}],temp=0.0,think=False,max_tokens=300,ctx_hint=ctx)
                ok=check(kind,r["content"],gt) and r.get("finish")!="length"
                rp=os.path.join(RAW,f"c{ctx//1024}k__{kind}__{seed}.json"); json.dump({"content":r["content"],"gt":gt,"finish":r.get("finish"),"ptok":r.get("ptok")},open(rp,"w",encoding="utf-8"),ensure_ascii=False,indent=1)
                row.update(ok=ok,ptok=r.get("ptok"),status="ok",raw=os.path.relpath(rp,D))
            except tune.TripError as e:
                row.update(ok=False,status="trip",note=str(e)); emit(row); logp(f"TRIP c{ctx//1024}k"); return "trip"
            except Exception as e:
                row.update(ok=False,status="err",note=str(e)[:100])
            emit(row); DONE.add((ctx,kind,seed)); logp(f"  c{ctx//1024}k/{kind}/seed{seed} ok={row.get('ok')} pt={row.get('ptok')}")

def main():
    import argparse; ap=argparse.ArgumentParser(); ap.add_argument("--seeds",type=int,default=5); ap.add_argument("--smoke",action="store_true"); a=ap.parse_args()
    logp(f"=== hard_ctx start seeds={a.seeds} smoke={a.smoke} resume={len(DONE)} ===")
    CTX=[32768] if a.smoke else [32768,65536,98304,131072]
    seeds=1 if a.smoke else a.seeds
    for ctx in CTX:
        ncm=20 if ctx>=98304 else (16 if ctx>=65536 else 12)
        if not tune.start_server(ctx,"q4_0",ncm,yarn=True,tag=f"hc_{ctx//1024}k"):
            logp(f"!! server {ctx} failed"); emit(dict(ctx=ctx,task="STARTUP",seed=0,ok=False,status="server_failed")); continue
        try:
            v=tune.vram_used_mib(); logp(f"c{ctx//1024}k up VRAM={v}")
            run(ctx,seeds)
        finally:
            tune.stop_server()
    if not a.smoke: open(DONEMARK,"w").write("done\n"); logp("=== HARDCTX DONE ===")
    logp("=== hard_ctx end ===")
if __name__=="__main__": main()
