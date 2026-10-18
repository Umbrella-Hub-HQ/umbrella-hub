#!/usr/bin/env python3
"""backtest.py - score every tg_alerts.jsonl alert AT ITS DETECTION TIME (using only that alert's DexScreener snapshot and the
sources/wallet overlap known by then), enter at the first alert whose score >= threshold, and simulate exit rules v3 on
GeckoTerminal 1-min candles. PAPER/RESEARCH ONLY.
Look-ahead guards: Rugcheck is fetched NOW, so only near-static fields are used (mint/freeze authority, LP lock %, score
minus 'Low Liquidity'); top-10 % and dev-holding are dropped. Txn counts / h1 change are not in the snapshots -> neutral.
Usage: python3 backtest.py [outcomes.json] [--weights w.json] [--json out.json]"""
import json,sys,os,glob,datetime as D
ROOT=os.environ.get("UMBRELLA_HOME") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root (holds desk/ and tools/)
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE)
import gem_score as G
ALERTS=os.environ.get("TG_ALERTS",ROOT+"/tools/tg_watch/tg_alerts.jsonl")
FEE=0.015; SIZE=3.0
def ts_of(s): return D.datetime.fromisoformat(s).timestamp()
def build_states(alerts,outcomes,cfg):
    """Yield (alert, candidate, t) in time order; candidate = cumulative state of that contract at the alert's detect time."""
    st={}
    for a in alerts:
        ca=G.update_from_alert(st,a)
        if not ca: continue
        t=ts_of(a.get("detect_time_et") or a["ts"]); dx=a.get("dex") or {}
        if not dx.get("price_usd"): continue
        rcd=((outcomes.get(ca) or {}).get("rugcheck")); rc=None
        if rcd:
            full=G.rugcheck_digest(ca,raw=rcd); rc={k:full.get(k) for k in ("mint_authority","freeze_authority","lp_locked_pct","rc_score_adj")}
        c=G.candidate_from_state(st,ca,t,G.normalize_snapshot(dx,t)); c["rugcheck"]=rc
        st["coins"][ca]["peak"]=max(st["coins"][ca]["peak"],dx["price_usd"])
        yield a,c,t
VARIANT=os.environ.get("EXIT_VARIANT","v3")
def sim_exit(candles,t0,p_mkt,liq):
    """Exit rules v3 (simplified for candles: NEUTRAL 25% trail, no FADING partials). Returns (pnl_pct, reason, peak_x, entry)."""
    cs=[c for c in candles if c[0]>=t0-59]
    if not cs: return None
    nxt=[c for c in cs if c[0]>=t0+60]          # ~60 s decision latency: fill at the next minute's open when available
    p=nxt[0][1] if nxt else p_mkt
    if p_mkt and (p>2*p_mkt or p<0.5*p_mkt): p=p_mkt   # alt-pool scale guard
    imp=SIZE/((liq or 20000)/2+SIZE); e=p*(1+FEE)*(1+imp)
    stop=e*0.70; peak=p; be=e/(1-FEE)
    for c in (nxt or cs):
        o,h,l,cl=c[1],c[2],c[3],c[4]
        if l<=stop:
            fill=o if o<stop else (stop if l>=stop*0.9 else max(l,stop*0.9))
            return (fill*(1-FEE)/e-1)*100,"STOP/TRAIL",peak/e,e
        peak=max(peak,h); g=peak/e
        if VARIANT=="wide":   # RESEARCH ONLY (not the protocol): lock at +50%, keep half the gain from 2x, 35% trail below 3x
            if g>=1.5:
                fl=be if g<2 else max(be,e*(1+0.5*(g-1))); trail=0.35 if g<3 else (0.30 if g<5 else 0.25)
                stop=max(stop,fl,peak*(1-trail))
        elif g>=1.10:
            fl=be
            if g>=1.5: fl=max(fl,e*(1+0.5*(g-1)))
            trail=0.30 if g<3 else (0.25 if g<5 else 0.20)
            stop=max(stop,fl,peak*(1-trail))
    last=cs[-1][4]; return (last*(1-FEE)/e-1)*100,"OPEN(mark)",peak/e,e
def run(outcomes,cfg,thr=None,verbose=False):
    thr=thr if thr is not None else cfg["thresholds"]["paper_entry"]
    alerts=[json.loads(l) for l in open(ALERTS) if l.strip()]
    coins={}
    for a,c,t in build_states(alerts,outcomes,cfg):
        r=G.score(c,cfg); k=c["contract"]; o=coins.setdefault(k,{"ticker":c["ticker"],"first_score":r["score"],"max_score":0,"entry":None,"scores":[]})
        o["scores"].append((a["alert_id"],r["score"],r["label"]))
        o["max_score"]=max(o["max_score"],r["score"] if not r["vetoes"] else 0)
        if o["entry"] is None and not r["vetoes"] and r["score"]>=thr:
            oc=outcomes.get(k) or {}; sim=sim_exit(oc.get("ohlcv") or [],t,c["price"],c.get("liq") or c.get("liq_est"))
            o["entry"]={"alert_id":a["alert_id"],"t":a.get("detect_time_et"),"score":r["score"],"mcap":c.get("mcap"),"why":r["why"],
                        "sim":None if not sim else {"pnl_pct":round(sim[0],1),"exit":sim[1],"peak_x":round(sim[2],2)}}
    return coins
def outcome_label(ca,outcomes,alerts_first):
    oc=outcomes.get(ca) or {}; a=alerts_first.get(ca) or {}; p0=(a.get("dex") or {}).get("price_usd")
    t0=ts_of(a.get("detect_time_et") or a.get("ts")); cs=[c for c in oc.get("ohlcv") or [] if c[0]>=t0-60]
    n=oc.get("ds_now") or {}; pn=float(n.get("priceUsd") or 0)
    pk=max([c[2] for c in cs],default=None)
    if not p0: return "NO_DATA",None,None
    px=pk/p0 if pk else None; nx=pn/p0 if pn else None
    if nx is not None and nx<=0.25: lab="RUG/DUMP"
    elif (px or 0)>=2 and (nx or 0)>=1: lab="RUNNER"
    elif (px or 0)>=2: lab="SPIKE_THEN_FADE"
    else: lab="FLAT/DOWN"
    return lab,px,nx
def main():
    av=sys.argv[1:]; args=[x for i,x in enumerate(av) if not x.startswith("--") and not (i>0 and av[i-1] in ("--weights","--json"))]
    fn=args[0] if args else sorted(glob.glob(os.path.join(HERE,"data","outcomes_*.json")))[-1]
    wpath=sys.argv[sys.argv.index("--weights")+1] if "--weights" in sys.argv else G.CFG_PATH
    cfg=G.load_cfg(wpath); outcomes=json.load(open(fn))
    alerts=[json.loads(l) for l in open(ALERTS) if l.strip()]; first={}
    for a in alerts:
        if a.get("contract") and (a.get("dex") or {}).get("price_usd"): first.setdefault(a["contract"],a)
    T=cfg["thresholds"]; coins=run(outcomes,cfg)
    rows=[]
    for ca,o in coins.items():
        lab,px,nx=outcome_label(ca,outcomes,first); e=o["entry"]
        rows.append(dict(ticker=o["ticker"],ca=ca,outcome=lab,peak_x_first=round(px,2) if px else None,now_x_first=round(nx,2) if nx else None,
                         first_score=o["first_score"],max_score=o["max_score"],entry=e))
    rows.sort(key=lambda r:-r["max_score"])
    print(f"weights {wpath}  thresholds {T}  outcomes {os.path.basename(fn)}")
    print(f"{'ticker':10} {'ca':6} {'outcome':16} {'pk_x':>6} {'now_x':>6} {'1st':>5} {'max':>5} | entry@thr")
    for r in rows:
        e=r["entry"]; es=f"#{e['alert_id']} s{e['score']} mc{(e['mcap'] or 0)/1e3:.0f}K sim {e['sim']}" if e else "-"
        print(f"{r['ticker'][:10]:10} {r['ca'][:6]} {r['outcome']:16} {str(r['peak_x_first']):>6} {str(r['now_x_first']):>6} {r['first_score']:5.1f} {r['max_score']:5.1f} | {es}")
    print("\nthreshold sweep (entry = first alert >= thr; $3/trade; sim = exit rules v3 on 1-min candles):")
    sweep=[]
    for thr in range(40,81,3):
        cs=run(outcomes,cfg,thr); ents=[(ca,o["entry"]) for ca,o in cs.items() if o["entry"]]
        sims=[e["sim"] for _,e in ents if e["sim"]]; lab={ca:outcome_label(ca,outcomes,first)[0] for ca,_ in ents}
        run_n=sum(1 for ca,_ in ents if lab[ca] in ("RUNNER","SPIKE_THEN_FADE")); rug_n=sum(1 for ca,_ in ents if lab[ca]=="RUG/DUMP")
        win=sum(1 for s in sims if s["pnl_pct"]>0); pnl=sum(SIZE*s["pnl_pct"]/100 for s in sims); p2=sum(1 for s in sims if s["peak_x"]>=2)
        sweep.append(dict(thr=thr,entries=len(ents),simulated=len(sims),winners=win,peak2x_after_entry=p2,runner_coins=run_n,rug_coins=rug_n,pnl_usd=round(pnl,2)))
        print(f"  thr {thr}: entries {len(ents):2} (sim {len(sims)}) | runner/spike coins {run_n} rug coins {rug_n} | sim winners {win}/{len(sims)} | >=2x after entry {p2} | P&L ${pnl:+.2f} on ${SIZE*len(sims):.0f}")
    if "--json" in sys.argv: json.dump({"rows":rows,"sweep":sweep,"cfg":cfg},open(sys.argv[sys.argv.index("--json")+1],"w"),indent=1,default=str)
if __name__=="__main__": main()
