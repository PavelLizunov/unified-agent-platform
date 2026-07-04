#!/usr/bin/env python3
# Clean speed sweep: pp (prefill) + tg (decode) tok/s per (ctx x kv). stdlib only.
import json,os,subprocess,time,urllib.request,socket
EXE=r"C:\Users\x3d_mutant\llama.cpp\llama-server.exe"
MODEL=r"C:\Users\x3d_mutant\Downloads\Qwen-AgentWorld-35B-A3B-UD-IQ4_NL.gguf"
HOST,PORT="127.0.0.1",8080; BASE=f"http://{HOST}:{PORT}"
DIR=os.path.dirname(os.path.abspath(__file__))
OUT=os.path.join(DIR,"speed_results.csv")
BASE_NCM16,PER_NCM=12480,362.5; KVB={"f16":16.0,"q8_0":8.5,"q4_0":4.5}
def pred(ncm,ctx,bpw): return BASE_NCM16-(ncm-16)*PER_NCM+ctx*20*(bpw/16)/1024
def pick(ctx,kv):
    for n in(12,16,20,24,28):
        if pred(n,ctx,KVB[kv])<=14800: return n
    return 32
def portopen():
    s=socket.socket();s.settimeout(1)
    try:s.connect((HOST,PORT));return True
    except:return False
    finally:s.close()
def health():
    try:
        import urllib.request as u
        with u.urlopen(BASE+"/health",timeout=3) as r:return json.loads(r.read())["status"]=="ok"
    except:return False
def vram():
    try:return int(subprocess.check_output(["nvidia-smi","--query-gpu=memory.used","--format=csv,noheader,nounits"]).decode().split()[0])
    except:return -1
proc=None
def start(ctx,kv,ncm,yarn,tag):
    global proc
    stop()
    a=[EXE,"-m",MODEL,"--host",HOST,"--port",str(PORT),"-ngl","999","--n-cpu-moe",str(ncm),
       "-c",str(ctx),"--jinja","--no-mmap","--no-webui","-fa","on"]
    if kv!="f16":a+=["-ctk",kv,"-ctv",kv]
    if yarn and ctx>32768:a+=["--rope-scaling","yarn","--rope-scale",f"{ctx/32768:.4f}","--yarn-orig-ctx","32768"]
    lf=open(os.path.join(DIR,f"spd_{tag}.log"),"w")
    proc=subprocess.Popen(a,stdout=lf,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    dl=time.time()+300
    while time.time()<dl:
        if proc.poll() is not None:return False
        if health():time.sleep(1);return True
        time.sleep(2)
    return False
def stop():
    global proc
    if proc and proc.poll() is None:
        subprocess.run(["taskkill","/F","/T","/PID",str(proc.pid)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for _ in range(15):
        if not portopen():break
        time.sleep(1)
    proc=None
FILL=("The harbor town woke slowly under a pale sky. Merchants counted crates along the pier. "
      "A gray cat slept on a coil of rope. Rain polished the cobblestones to a dull shine. ")
def prompt_of(ctx):
    words=int(ctx*0.80/1.35); s=[]; w=0
    while w<words: s.append(FILL); w+=len(FILL.split())
    return " ".join(s)
rows=[]
CTX=[8192,16384,32768,65536,98304,131072]; KV=["f16","q8_0","q4_0"]
open(OUT,"w").write("ctx,kv,ncm,vram_MiB,prompt_tok,pp_tps,tg_tps\n")
for ctx in CTX:
    p=prompt_of(ctx)
    for kv in KV:
        ncm=pick(ctx,kv); tag=f"{ctx//1024}k_{kv}"
        if not start(ctx,kv,ncm,True,tag):
            print(f"{tag}: START FAIL",flush=True); open(OUT,"a").write(f"{ctx},{kv},{ncm},,,,\n"); continue
        v=vram()
        body=json.dumps({"prompt":p,"n_predict":200,"temperature":0,"cache_prompt":False}).encode()
        try:
            req=urllib.request.Request(BASE+"/completion",data=body,headers={"Content-Type":"application/json"})
            with urllib.request.urlopen(req,timeout=1200) as r: t=json.loads(r.read())["timings"]
            pp=round(t.get("prompt_per_second",0),1); tg=round(t.get("predicted_per_second",0),1); pt=int(t.get("prompt_n",0))
        except Exception as e:
            pp=tg=pt=f"err:{str(e)[:20]}"
        print(f"{tag}: ncm{ncm} vram{v} pp={pp} tg={tg} ptok={pt}",flush=True)
        open(OUT,"a").write(f"{ctx},{kv},{ncm},{v},{pt},{pp},{tg}\n")
        stop()
stop()
print("=== speed sweep done ===",flush=True)
