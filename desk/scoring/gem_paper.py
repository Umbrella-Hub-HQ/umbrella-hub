#!/usr/bin/env python3
"""gem_paper.py - PAPER ONLY gem-score engine (paper-trade coins that look like they will run). Never trades live, signs, posts, messages or touches wallets. Public GETs only.

Every LOOP_S seconds:
 1. folds new lines of tools/tg_watch/tg_alerts.jsonl, tools/wallet_watch/alerts.jsonl (solana buys) and
    flywheel_alerts.jsonl (watched-wallet launch/receive) into candidate state (gem_state.json);
 2. re-scores every active candidate (seen in the last ACTIVE_H hours) with LIVE DexScreener data (one batched call),
    adding Rugcheck when the coin is near a threshold and a Jupiter sell-route check before any entry;
 3. writes score changes to gem_journal.jsonl, ping candidates to gem_alerts.jsonl (score >= ping threshold or paper
    entry; one ping per contract per label), and opens a PAPER position in desk/paper/paper_book.json when
    score >= paper_entry threshold and the book's -12% daily halt / loss ladder allow it. Exits are NOT done here:
    desk/paper/adaptive_watcher.py applies exit rules v3.2a (protocols/exit-rules.md) to every open book position;
 4. journals CLOSE records for gem positions the watcher closed, refreshes the scorecard every ~15 min,
    and writes gem_status.json (heartbeat).
 5. (paper250 2026-10-18) runs experiment contrarian_1p5x (contrarian.py): paper-enters calls from the owner's sources that the filters
    above SKIP (soft fails only; never a hard veto), $5 fixed, own sub-book desk/paper/contrarian_1p5x_book.json, TP 1.5x / stop -35% /
    24 h, tracks every entry 24 h for max multiple. It never reads or writes the main book's cash, halt or ladder.
Usage: python3 gem_paper.py [--once] [--dry-run]"""
import json,os,sys,time,math,subprocess,traceback,datetime as D
ROOT=os.environ.get("UMBRELLA_HOME") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root (holds desk/ and tools/)
HERE=os.path.dirname(os.path.abspath(__file__)); PAPER=os.path.join(ROOT,"desk","paper")
sys.path.insert(0,HERE); sys.path.insert(0,PAPER); sys.path.insert(0,ROOT+"/rug-shield")
import gem_score as G
import paper_monitor as PM
import contrarian as CX   # paper250 2026-10-18: PAPER-ONLY experiment contrarian_1p5x (own sub-book; see contrarian.py)
ET=G.ET; DRY="--dry-run" in sys.argv; ONCE="--once" in sys.argv
STATE=os.path.join(HERE,"gem_state.json"); JOURNAL=os.path.join(PAPER,"gem_journal.jsonl"); ALERTS_OUT=os.path.join(HERE,"gem_alerts.jsonl")
STATUS=os.path.join(HERE,"gem_status.json"); LOG=os.path.join(HERE,"gem_paper.log")
TG_ALERTS=os.environ.get("TG_ALERTS",ROOT+"/tools/tg_watch/tg_alerts.jsonl"); WW_ALERTS=os.environ.get("WW_ALERTS",ROOT+"/tools/wallet_watch/alerts.jsonl"); FW_ALERTS=os.environ.get("FW_ALERTS",ROOT+"/tools/flywheel_watch/flywheel_alerts.jsonl")
LOOP_S=45; ACTIVE_H=6; MAX_ACTIVE=60; RUGCHECK_MARGIN=10
SIZE_MIN_PCT=0.02; SIZE_MAX_PCT=0.05; MAX_OPEN_GEM=6; MAX_GEM_EXPOSURE_PCT=0.25; REENTRY_H=24; MIN_SIZE_USD=1.0; ENTRY_FRESH_MIN=45   # entry needs a new call/wallet input within 45 min (no stale tops)
def now(): return D.datetime.now(ET)
def log(m):
    line=f"[{now():%Y-%m-%d %H:%M:%S} ET] {m}"; print(line,flush=True)
    try:
        with open(LOG,"a") as f: f.write(line+"\n")
    except Exception: pass
def jload(p,d):
    try: return json.load(open(p))
    except Exception: return d
def atomic(p,obj):
    tmp=p+".tmp"; open(tmp,"w").write(json.dumps(obj,indent=1,default=str)); os.replace(tmp,p)
def append(p,rec):
    if DRY: return
    with open(p,"a") as f: f.write(json.dumps(rec,default=str)+"\n")
def read_new(path,st,key):
    """Append-only JSONL tail by byte offset (resets if the file shrank)."""
    try: sz=os.path.getsize(path)
    except OSError: return []
    off=st.setdefault("offsets",{}).get(key,0)
    if sz<off: off=0
    if sz==off: return []
    out=[]
    with open(path) as f:
        f.seek(off)
        for ln in f:
            if not ln.endswith("\n"): break      # partial line being written: read next time
            off+=len(ln.encode())
            try: out.append(json.loads(ln))
            except ValueError: pass
    st["offsets"][key]=off; return out
def _ats(a):
    for k in ("ts","buy_time_et","time_et"):
        try: return D.datetime.fromisoformat(a[k]).timestamp()
        except Exception: pass
    return time.time()
def ingest(st):
    n=0
    for a in read_new(TG_ALERTS,st,"tg"):
        if G.update_from_alert(st,a): n+=1
    for a in read_new(WW_ALERTS,st,"ww"):   # watched-wallet buys on Solana = smart-money overlap
        if a.get("chain")=="solana" and a.get("contract") and str(a.get("kind","")).startswith(("BUY","CLUSTER","PRE_POST")):
            G.add_wallet(st,a["contract"],{"wallet":a.get("wallet"),"caller":a.get("caller"),"grade":a.get("grade"),"src":"wallet_watch"},a.get("symbol"),_ats(a)); n+=1
    for a in read_new(FW_ALERTS,st,"fw"):
        if a.get("contract") and a.get("kind") in ("LAUNCH_BY_WATCHED","WATCHED_RECEIVE","WATCHED_BUY") and a.get("chain","solana")=="solana":
            G.add_wallet(st,a["contract"],{"wallet":a.get("wallet") or a.get("creator"),"grade":"STRONG" if a.get("priority")=="HIGH" else "","src":"flywheel"},a.get("symbol"),_ats(a)); n+=1
    return n
def entry_fill(px,liq,size,m5):
    """Honest paper fill: 1.5% fee/slippage convention + constant-product impact on half the pool + chase slippage
    (fast coins move between our quote and a real fill): 0.5% + 0.02% per +1% m5, capped at 3%."""
    imp=size/((liq or 0)/2+size) if liq else 0.05
    chase=min(0.03,0.005+max(m5 or 0,0)*0.0002)
    return px*(1+PM.EXIT_COST)*(1+imp)*(1+chase),imp,chase
def size_for(score,thr,equity,mult):
    pct=SIZE_MIN_PCT+(SIZE_MAX_PCT-SIZE_MIN_PCT)*G.clamp((score-thr)/20)
    return round(equity*pct*(mult or 1.0),2),pct
def active_exit_experiment(cfg):
    """weights.json exit_experiment, only if listed in experiments with active=true AND known to paper_monitor (else None = v3.2a)."""
    x=cfg.get("exit_experiment")
    return x if x and (cfg.get("experiments") or {}).get(x,{}).get("active") and x in getattr(PM,"EXIT_EXPERIMENTS",{}) else None
def gem_positions(b): return [p for p in b["positions"] if str(p.get("source","")).startswith("gem_score")]
def try_enter(st,cfg,c,r,pair,t):
    """Under the book lock. Returns (action, why, pos|None)."""
    thr=cfg["thresholds"]["paper_entry"]; lk=PM.book_lock()
    try:
        b=json.load(open(PM.BOOK))
        if b.get("day")!=t.date().isoformat(): b["day"]=t.date().isoformat(); b["day_start_equity"]=None   # ET-day reset (same as paper_monitor/watcher)
        PM.update_equity(b,t)
        ll=b.get("loss_ladder") or {}
        if b.get("daily_halt_new_entries"): return "SKIP_DAILY_HALT",f"paper book day {b.get('day_pnl_pct')}% <= -12% (incl. unrealized); resumes on the next ET day",None
        if not ll.get("new_entries_allowed",True): return "SKIP_LADDER",f"loss ladder {ll.get('state')}",None
        if any(p["mint"]==c["contract"] and p["qty_open"]>1e-12 for p in b["positions"]): return "SKIP_DUP","already open",None
        recent=[p for p in gem_positions(b)+(b.get("reentry_block") or []) if p["mint"]==c["contract"] and (t-D.datetime.fromisoformat(p["entry_time"])).total_seconds()<REENTRY_H*3600]   # reentry_block: gem entries carried over from an archived book (reset_paper_book.py)
        if recent: return "SKIP_REENTRY",f"gem position on this mint in the last {REENTRY_H}h",None
        og=[p for p in gem_positions(b) if p["qty_open"]>1e-12]
        if len(og)>=MAX_OPEN_GEM: return "SKIP_MAX_OPEN",f"{len(og)} gem positions open (max {MAX_OPEN_GEM})",None
        eq=b.get("equity") or b["cash"]; expo=sum(p["qty_open"]*p["last_price"] for p in og)
        size,pct=size_for(r["score"],thr,eq,ll.get("size_mult"))
        size=min(size,b["cash"],max(0.0,eq*MAX_GEM_EXPOSURE_PCT-expo))
        if size<MIN_SIZE_USD: return "SKIP_SIZE",f"size ${size:.2f} < ${MIN_SIZE_USD} (cash ${b['cash']:.2f}, gem exposure ${expo:.2f})",None
        px=float(pair["priceUsd"]); liq=c.get("liq") or c.get("liq_est")
        xexp=active_exit_experiment(cfg)
        e,imp,chase=entry_fill(px,liq,size,c.get("m5")); qty=size/e
        sym=(pair.get("baseToken") or {}).get("symbol") or c.get("ticker") or "?"
        pos=dict(id=f"PAPER-GEM-{t:%Y%m%d%H%M%S}-{sym[:10]}",symbol=sym,mint=c["contract"],pair=pair["pairAddress"],size_usd=round(size,2),qty=qty,qty_open=qty,
                 mkt_price_at_entry=px,entry_price=e,entry_mcap=pair.get("marketCap"),entry_liq=liq,entry_time=t.isoformat(timespec="seconds"),
                 stop_price=e*0.70,peak_price=px,time_stop_at=(t+D.timedelta(hours=24)).isoformat(timespec="seconds"),realized_usd=0.0,
                 last_price=px,last_liq=liq,source="gem_score",exit_experiment=xexp,
                 rules=f"entry=gem_score>={thr} (reference install 2026-10-17, PAPER ONLY; not a Rug Shield CLEAR); exits="+(f"v3.2a + experiment {xexp} (reference install)" if xexp else "v3.2a (protocols/exit-rules.md)"),
                 entry_cost_model={"fee_pct":PM.EXIT_COST*100,"impact_pct":round(imp*100,3),"chase_pct":round(chase*100,3),"size_pct_equity":round(pct*100,2)},
                 gem={"score":r["score"],"label":r["label"],"why":r["why"],"n_independent":r["n_independent"],"sources":r["source_groups"],
                      "factors":{k:{"v":f["value"],"pts":f["points"],"note":f["note"]} for k,f in r["factors"].items()},"penalties":r["penalties"]})
        if globals().get("RS_DISABLED"): pos["rug_shield_extra"]={"skipped":"test"}
        else:
          try:
            import checks as RS
            pos["rug_shield_extra"]={k:(v or {}).get("status") for k,v in RS.shield_extra(c["contract"],pair["pairAddress"],px,G.sol_usd_from_pair(pair)).items() if k in ("T1","T4","T7")}
          except Exception as ex: pos["rug_shield_extra"]={"error":f"{type(ex).__name__}"[:60]}
        if DRY: return "DRY_OPEN",f"would open ${size:.2f}",pos
        b["cash"]-=size; b["positions"].append(pos); PM.update_equity(b,t)
        tmp=PM.BOOK+".tmp"; json.dump(b,open(tmp,"w"),indent=1); os.replace(tmp,PM.BOOK)
        PM.record(b,[dict(ts=t.isoformat(timespec="seconds"),type="OPEN",symbol=sym,id=pos["id"],price=px,
                          reason=f"gem paper entry ${size:.2f} ({pct*100:.1f}% eq): {r['why']} | fill {e:.8g} (fee 1.5%, impact {imp*100:.2f}%, chase {chase*100:.2f}%)")],[],t)
        return "OPEN",f"${size:.2f} @ {e:.8g}",pos
    finally: lk.close()
def kick_watcher():
    if DRY: return
    try: subprocess.Popen(["bash",os.path.join(PAPER,"ensure_watcher.sh")],cwd=PAPER,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    except Exception as e: log(f"kick_watcher failed {e}")
def ping_text(r,c,pair,action=None,pos=None):
    mc=c.get("mcap") or 0; liq=c.get("liq") or c.get("liq_est") or 0
    head=f"GEM {r['score']:.0f}/100" + (" PAPER ENTRY" if action=="OPEN" else "")
    tail=f" | paper ${pos['size_usd']:.2f} @ {pos['entry_price']:.6g} (exits "+(pos.get('exit_experiment') or 'v3.2a')+")" if (action=="OPEN" and pos) else ""
    return (f"{head} ${r['ticker']} {c['contract']} | mc ${mc/1e3:.0f}K liq ${liq/1e3:.0f}K | why: {r['why'].split(': ',1)[-1]}"
            f" | src: {', '.join(r['source_groups']) or 'wallets only'}{tail} | {pair.get('url','')} | PAPER/read-only, no live trade")
def journal_closes(st,t):
    b=jload(PM.BOOK,{}); done=set(st.setdefault("closed_journaled",[]))
    for p in gem_positions(b):
        if p["qty_open"]>1e-12 or p["id"] in done: continue
        ct=[x for x in b.get("closed_trades",[]) if x["id"]==p["id"]]
        pnl=sum(x["pnl_usd"] for x in ct)
        rec=dict(ts=t.isoformat(timespec="seconds"),type="CLOSE",id=p["id"],symbol=p["symbol"],mint=p["mint"],score=(p.get("gem") or {}).get("score"),
                 size_usd=p["size_usd"],pnl_usd=round(pnl,4),pnl_pct=round(pnl/p["size_usd"]*100,2),peak_x=round(p["peak_price"]/p["entry_price"],3),
                 exits=[{"reason":x["reason"],"time":x["exit_time"],"pnl_usd":x["pnl_usd"]} for x in ct],exit_rules=p.get("exit_experiment") or "v3.2a",why_entered=(p.get("gem") or {}).get("why"))
        append(JOURNAL,rec); done.add(p["id"]); log(f"CLOSE journaled {p['symbol']} pnl ${pnl:+.2f}")
    st["closed_journaled"]=sorted(done)
def cycle(st,cfg):
    t=now(); ts=t.timestamp(); T=cfg["thresholds"]; n_new=ingest(st)
    coins=st.setdefault("coins",{})
    for ca in [k for k,v in coins.items() if ts-(v.get("last_alert") or 0)>48*3600]: coins.pop(ca)   # forget > 48 h
    active=sorted([k for k,v in coins.items() if ts-(v.get("last_alert") or v.get("first_seen") or 0)<=ACTIVE_H*3600],key=lambda k:-(coins[k].get("last_alert") or 0))[:MAX_ACTIVE]
    pairs=G.fetch_pairs(active,ttl=15) if active else {}
    sol=next((G.sol_usd_from_pair(p) for p in pairs.values() if G.sol_usd_from_pair(p)),None)
    scored=0; events=[]; top=[]; cands=[]
    for ca in active:
        p=pairs.get(ca); s=coins[ca]
        if not p: continue
        mk=G.normalize_pair(p,sol,ts); c=G.candidate_from_state(st,ca,ts,mk)
        s["peak_live"]=max(s.get("peak_live") or 0,mk["price"] or 0); s["last_price"]=mk["price"]
        c["peak_price_seen"]=max(c.get("peak_price_seen") or 0,s["peak_live"]) or None
        c["ring"]=G.ring_status(ca); r=G.score(c,cfg); scored+=1
        need_rc=(not r["vetoes"]) and r["score"]>=T["watch"]-RUGCHECK_MARGIN
        if need_rc:
            c["rugcheck"]=G.rugcheck_digest(ca)
            if c["rugcheck"].get("error"): c["rugcheck"]=None
            r=G.score(c,cfg)
        if (not r["vetoes"]) and r["score"]>=T["paper_entry"]:
            dec=(c.get("rugcheck") or {}).get("decimals")
            c["sell_route"],_imp=G.sell_route(ca,dec); r=G.score(c,cfg)
        s["last_score"]=r["score"]; s["max_score"]=max(s.get("max_score") or 0,r["score"] if not r["vetoes"] else 0)
        if r["score"]>=T["watch"] and not s.get("first_watch_ts"): s["first_watch_ts"]=ts; s["first_watch_price"]=mk["price"]; s["first_watch_score"]=r["score"]
        prev=s.get("label")
        rank={"VETO":0,"PASS":1,"WATCH":2,"PING":3,"PAPER_ENTRY":4}
        if r["label"]!=prev and (rank[r["label"]]>=2 or rank.get(prev,0)>=2):
            rec=dict(ts=t.isoformat(timespec="seconds"),type="SCORE",mint=ca,ticker=r["ticker"],score=r["score"],label=r["label"],prev=prev,vetoes=r["vetoes"],why=r["why"],
                     price=mk["price"],mcap=mk.get("mcap"),liq=mk.get("liq") or mk.get("liq_est"),n_independent=r["n_independent"],sources=r["source_groups"],
                     factors={k:[f["value"],f["points"],f["note"]] for k,f in r["factors"].items()},penalties=r["penalties"],sell_route=c.get("sell_route"))
            append(JOURNAL,rec)
        s["label"]=r["label"]
        action=None; pos=None
        if r["label"]=="PAPER_ENTRY":
            if ts-(s.get("last_alert") or 0)>ENTRY_FRESH_MIN*60: action,why=("SKIP_STALE",f"no new call/wallet input for {(ts-(s.get('last_alert') or 0))/60:.0f} min")
            else: action,why,pos=try_enter(st,cfg,c,r,p,t)
            if action!=s.get("last_entry_action"):
                append(JOURNAL,dict(ts=t.isoformat(timespec="seconds"),type="ENTER" if action=="OPEN" else "ENTRY_SKIP",mint=ca,ticker=r["ticker"],score=r["score"],action=action,
                                    detail=why,why=r["why"],id=(pos or {}).get("id") if action=="OPEN" else None,
                                    factors={k:[f["value"],f["points"],f["note"]] for k,f in r["factors"].items()},penalties=r["penalties"],
                                    cost_model=(pos or {}).get("entry_cost_model") if action=="OPEN" else None,
                                    exit_experiment=(pos or {}).get("exit_experiment") if action=="OPEN" else None))
                s["last_entry_action"]=action
            if action=="OPEN": log(f"PAPER ENTRY {r['ticker']} {ca[:6]} {why} | {r['why']}"); kick_watcher(); events.append(f"OPEN {r['ticker']}")
        top.append((r["score"],r["ticker"],ca[:6],r["label"],action,(r["vetoes"] or [""])[0][:40]))
        cands.append((ca,s,c,r,p))
        pinged=set(s.setdefault("pinged",[]))
        key="OPEN" if action=="OPEN" else ("PING" if r["label"] in ("PING","PAPER_ENTRY") else None)
        if key and key not in pinged:
            append(ALERTS_OUT,dict(ts=t.isoformat(timespec="seconds"),kind="GEM_"+key,contract=ca,ticker=r["ticker"],score=r["score"],label=r["label"],
                                    paper_action=action,why=r["why"],ping_text=ping_text(r,c,p,action,pos),dedupe_key=f"GEM:{ca}:{key}"))
            pinged.add(key)
            if key=="OPEN": pinged.add("PING")   # an entry ping already covers the score ping
            s["pinged"]=sorted(pinged)
    journal_closes(st,t)
    ctr=None
    try:   # contrarian_1p5x (PAPER ONLY, own sub-book): never blocks or changes the main engine's decisions above
        bk=jload(PM.BOOK,{})
        taken={p["mint"] for p in gem_positions(bk)+(bk.get("reentry_block") or []) if (t-D.datetime.fromisoformat(p["entry_time"])).total_seconds()<REENTRY_H*3600}
        ctr=CX.run_cycle(st,cfg,cands,t,G,entry_fill,dry=DRY,exclude=taken)
        for e in (ctr or {}).get("events",[]): log("CONTRARIAN "+e); events.append("CTR "+e)
    except Exception as e:
        ctr={"error":f"{type(e).__name__}: {e}"[:200]}; log("CONTRARIAN ERROR "+ctr["error"])
    top.sort(reverse=True)
    return dict(active=len(active),priced=len(pairs),scored=scored,new_inputs=n_new,events=events,top=[" ".join(str(x) for x in r if x) for r in top[:8]],contrarian=ctr)
def main():
    st=jload(STATE,{}); cfg=G.load_cfg(); last_cfg=time.time(); last_card=0
    if not st.get("offsets"):   # first start: back-fill tonight's alerts into candidate state, but treat them as history
        st["offsets"]={}; log("first start: folding existing alert history into state")
    log(f"start pid {os.getpid()} dry={DRY} thresholds {cfg['thresholds']} exit_experiment {active_exit_experiment(cfg) or 'none (v3.2a)'}")
    xe=active_exit_experiment(cfg)
    if xe and st.get("exit_experiment_logged")!=xe and not DRY:
        append(JOURNAL,dict(ts=now().isoformat(timespec="seconds"),type="EXPERIMENT",experiment=xe,detail=(cfg.get("experiments") or {}).get(xe)))
        st["exit_experiment_logged"]=xe
    cx=CX.config(cfg)
    log(f"contrarian_1p5x {'ACTIVE' if cx.get('active') else 'off'}: ${cx['size_usd']}/entry tp {cx['tp_x']}x stop {cx['stop_pct']}% timeout {cx['timeout_h']}h book {CX.BOOK}")
    if cx.get("active") and not st.get("contrarian_logged") and not DRY:
        append(JOURNAL,dict(ts=now().isoformat(timespec="seconds"),type="EXPERIMENT",experiment="contrarian_1p5x",detail=(cfg.get("experiments") or {}).get("contrarian_1p5x"),book=CX.BOOK,journal=CX.JOURNAL))
        st["contrarian_logged"]=True
    while True:
        t0=time.time(); info={}; err=None
        try:
            if time.time()-last_cfg>300: cfg=G.load_cfg(); last_cfg=time.time()
            info=cycle(st,cfg)
            if not DRY: atomic(STATE,st)
            if time.time()-last_card>900 and not DRY:
                subprocess.run([sys.executable,os.path.join(HERE,"gem_scorecard.py"),"--quiet"],timeout=120,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); last_card=time.time()
        except Exception as e:
            err=f"{type(e).__name__}: {e}"[:300]; log("ERROR "+err+" | "+traceback.format_exc().splitlines()[-2][:200])
        b=jload(PM.BOOK,{})
        stt={"heartbeat":now().isoformat(timespec="seconds"),"pid":os.getpid(),"dry_run":DRY,"loop_s":LOOP_S,"thresholds":cfg["thresholds"],"exit_experiment":active_exit_experiment(cfg),"contrarian_1p5x":(info or {}).get("contrarian"),"last_cycle":info,"last_error":err,
             "book":{"equity":b.get("equity"),"cash":b.get("cash"),"day":b.get("day"),"day_pnl_pct":b.get("day_pnl_pct"),"daily_halt_new_entries":b.get("daily_halt_new_entries"),
                     "loss_ladder":(b.get("loss_ladder") or {}).get("state"),"open_gem":[p["symbol"] for p in gem_positions(b) if p["qty_open"]>1e-12] if b else []}}
        if not DRY: atomic(STATUS,stt)
        if ONCE: print(json.dumps(stt,indent=1)); return
        time.sleep(max(5,LOOP_S-(time.time()-t0)))
if __name__=="__main__": main()
