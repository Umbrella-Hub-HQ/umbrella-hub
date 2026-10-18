#!/usr/bin/env python3
"""contrarian.py - PAPER ONLY experiment 'contrarian_1p5x' (reference install 2026-10-18). Never trades live, signs, posts or touches wallets.

Question: do the calls our filters SKIP still pay if we just take +50% and leave?
Entry: a candidate from the owner's own sources (Telegram channels tg_watch watches = tools/tg_watch/config.json + the lists it merges,
caller watch = tools/wallet_watch/config.json caller_feeds, wallet watch / flywheel watched wallets) that the gem engine would NOT
paper-enter (score below thresholds.paper_entry, or a SOFT veto such as 'already dumped from peak'), with score >= min_score and a
fresh call (last input <= fresh_min). TRUE hard vetoes are never entered: live mint/freeze authority, honeypot/no sell route,
Rugcheck rugged, Rug Shield REJECT, liquidity < $5K, m5 <= -50%. Fail-closed: no Rugcheck report or liquidity unknown -> no entry;
sell route must be OK when require_sell_route_ok.
Size: fixed size_usd per entry (default $5) from its OWN sub-book (contrarian_1p5x_book.json, start = paper_config.json bankroll
unless start_usd is set). It never touches the main paper book, the -12% halt, the loss ladder or exit rules v3.2a.
Exit: first of take-profit at tp_x (1.5x the entry fill), stop at stop_pct (-35% vs fill), timeout_h (24 h); RUG if liquidity
< $100. Fills: same model as gem_paper (entry 1.5% + impact + chase; exit 1.5% + impact), at the price actually observed (45-s
polling: a gap through the level is booked at the observed price, not the level).
Tracking: every entry keeps being priced for track_h (24 h) after ENTRY, even after the exit: max multiple, time of max, and
whether 1.5x / 2x / 3x was reached (multiples vs the entry fill). A tick > 10x the last accepted price needs a 2nd cycle to confirm.
Config: scoring/weights.json experiments.contrarian_1p5x (reloaded by gem_paper every 5 min)."""
import json,os,time,datetime as D
ROOT=os.environ.get("UMBRELLA_HOME") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root (holds desk/ and tools/)
HERE=os.path.dirname(os.path.abspath(__file__)); PAPER=os.path.join(ROOT,"desk","paper")
BOOK=os.path.join(PAPER,"contrarian_1p5x_book.json"); JOURNAL=os.path.join(PAPER,"contrarian_1p5x_journal.jsonl")
LOCK=os.path.join(PAPER,"contrarian_1p5x_book.lock"); PAPER_CFG=os.path.join(PAPER,"paper_config.json")
TG_CFG=ROOT+"/tools/tg_watch/config.json"; WW_CFG=ROOT+"/tools/wallet_watch/config.json"; WSRC=ROOT+"/tools/data/watched_sources.json"
NAME="contrarian_1p5x"; EXIT_COST=0.015; JUMP_X=10; RUG_LIQ=100
DEFAULTS=dict(active=False,size_usd=5.0,start_usd=None,tp_x=1.5,stop_pct=-35.0,timeout_h=24,track_h=24,min_score=30,fresh_min=20,
              max_open=25,max_entries_per_day=60,max_checks_per_cycle=6,require_sell_route_ok=True,soft_vetoes=["already dumped"],
              reach_levels=[1.5,2.0,3.0])
HARD_PREFIX=("live mint authority","live freeze authority","honeypot","Rugcheck: rugged","Rug Shield REJECT","liquidity $","dump in progress")
def ET(): return D.timezone(D.timedelta(hours=-4))
def jl(p,d):
    try: return json.load(open(p))
    except Exception: return d
def config(cfg):
    x=dict(DEFAULTS); x.update(((cfg or {}).get("experiments") or {}).get(NAME) or {}); return x
def bankroll(xc):
    if xc.get("start_usd"): return float(xc["start_usd"])
    return float(jl(PAPER_CFG,{}).get("starting_bankroll_usd") or 250.0)
# ---------------- the owner's sources ----------------
def owner_channels():
    """Same merge as tg_watch.load_channels(): wallet_watch caller_feeds tg + watched_sources telegram + tg_watch extra_channels."""
    tg=jl(TG_CFG,{}); ww=jl(WW_CFG,{}); dis=set(tg.get("disabled_channels") or []); out={}; callers=set()
    for n,f in (ww.get("caller_feeds") or {}).items():
        ch=(f or {}).get("tg")
        if ch: out[ch.lower()]=ch; callers.add(ch.lower())
    for s in jl(WSRC,{}).get("sources",[]):
        if s.get("type")=="telegram" and s.get("enabled",True) and s.get("channel"): out.setdefault(s["channel"].lower(),s["channel"])
    for e in tg.get("extra_channels") or []:
        if e.get("channel"): out.setdefault(e["channel"].lower(),e["channel"])
    for d in dis: out.pop(d.lower(),None)
    return out,callers
def owner_sources(coin,chans=None,callers=None):
    """-> list of source tags for this coin: tg:<ch>, caller_watch:<ch>, wallet_watch[:caller], flywheel. Empty = not the owner's sources."""
    if chans is None: chans,callers=owner_channels()
    tags=[]
    for s in sorted((coin.get("sources") or {}).values(),key=lambda s:s.get("post_ts") or 0):
        ch=(s.get("channel") or "").lower()
        if s.get("kind") not in (None,"call") or ch not in chans: continue
        t=("caller_watch:" if ch in (callers or set()) else "tg:")+chans[ch]
        if t not in tags: tags.append(t)
    for w in coin.get("wallet") or []:
        src=w.get("src") or ("wallet_watch" if str(w.get("wallet","")).startswith("late:") else "tg_overlap")
        t={"wallet_watch":"wallet_watch"+(":"+str(w["caller"]) if w.get("caller") else ""),"flywheel":"flywheel"}.get(src)
        if t and t not in tags: tags.append(t)
    return tags
def source_kind(tag): return tag.split(":",1)[0]
# ---------------- why our filters skip it ----------------
def hard_vetoes(r): return [v for v in r.get("vetoes") or [] if v.startswith(HARD_PREFIX)]
def soft_vetoes(r,xc): return [v for v in r.get("vetoes") or [] if not v.startswith(HARD_PREFIX)]
def skip_reasons(c,r,cfg):
    """Why the main engine would not paper-enter it (soft only). Priority order = primary first."""
    thr=cfg["thresholds"]["paper_entry"]; F=r.get("factors") or {}; out=[]
    for v in soft_vetoes(r,None): out.append("dumped_from_peak" if "dumped" in v else "soft_veto")
    pids={p["id"] for p in r.get("penalties") or []}
    liq=c.get("liq") or c.get("liq_est"); m5=c.get("m5"); h1=c.get("h1")
    if (m5 is not None and m5<0) or (h1 is not None and h1<-30) or (F.get("momentum",{}).get("value",1)<0.4): out.append("momentum")
    if m5 is not None and m5>=100: out.append("vertical")
    if c.get("vol_h1") and liq and c["vol_h1"]/liq>15: out.append("fake_volume")
    if "chase" in pids: out.append("already_ran")
    if "off_peak_50" in pids and "dumped_from_peak" not in out: out.append("dumped_from_peak")
    if liq is not None and (liq<25000 or (c.get("mcap") and liq/c["mcap"]<0.06)): out.append("liquidity_cap")
    if c.get("age_min") is not None and c["age_min"]<60: out.append("fresh_lt_1h")
    for k in ("promo_only","ring_flag","copycat","x_paid_promo"):
        if k in pids: out.append(k)
    if r.get("score",0)<thr: out.append("low_score")
    return out
def primary_reason(reasons):
    for k in ("dumped_from_peak","soft_veto","already_ran","fake_volume","momentum","vertical","liquidity_cap","ring_flag","copycat","promo_only","x_paid_promo","fresh_lt_1h","low_score"):
        if k in reasons: return k
    return reasons[0] if reasons else None
def eligible(c,r,cfg,xc,sources,last_alert_ts,now_ts):
    """-> (ok, why, reasons). Pure: needs c with rugcheck/sell_route already filled. Never ok on a hard veto or missing safety data."""
    hv=hard_vetoes(r)
    if hv: return False,"HARD_VETO: "+hv[0],[]
    if not sources: return False,"not from the owner's sources",[]
    if now_ts-(last_alert_ts or 0)>xc["fresh_min"]*60: return False,"call not fresh",[]
    if r.get("label")=="PAPER_ENTRY" and not soft_vetoes(r,xc): return False,"main engine entry (not a skip)",[]
    if r.get("score",0)<xc["min_score"]: return False,f"score {r.get('score')} < min_score {xc['min_score']}",[]
    rc=c.get("rugcheck")
    if not rc or rc.get("error"): return False,"UNVERIFIED: no Rugcheck report (hard vetoes unknown)",[]
    liq=c.get("liq") or c.get("liq_est")
    if liq is None or liq<5000: return False,"UNVERIFIED/HARD: liquidity unknown or < $5K",[]
    if c.get("m5") is not None and c["m5"]<=-50: return False,"HARD: m5 <= -50%",[]
    if c.get("sell_route")=="NO_ROUTE": return False,"HARD: honeypot / no sell route",[]
    if xc.get("require_sell_route_ok") and c.get("sell_route")!="OK": return False,f"UNVERIFIED: sell route {c.get('sell_route')}",[]
    rs=skip_reasons(c,r,cfg)
    if not rs: return False,"no skip reason",[]
    return True,"ok",rs
# ---------------- book ----------------
def lock():
    import fcntl; f=open(LOCK,"a"); fcntl.flock(f,fcntl.LOCK_EX); return f
def load_book(xc,now):
    b=jl(BOOK,None)
    if b is None:
        s=bankroll(xc)
        b={"mode":"PAPER_EXPERIMENT","experiment":NAME,"starting_balance":s,"cash":s,"equity":s,"started_et":now.isoformat(timespec="seconds"),
           "bankroll_source":"weights.json experiments.contrarian_1p5x.start_usd" if xc.get("start_usd") else "paper_config.json starting_bankroll_usd",
           "positions":[],"closed_trades":[]}
    return b
def save_book(b):
    tmp=BOOK+".tmp"; json.dump(b,open(tmp,"w"),indent=1,default=str); os.replace(tmp,BOOK)
def journal(rec,dry=False):
    if dry: return
    with open(JOURNAL,"a") as f: f.write(json.dumps(rec,default=str)+"\n")
def equity(b):
    return b["cash"]+sum(p["qty_open"]*p["last_price"]*(1-EXIT_COST) for p in b["positions"] if p["qty_open"]>1e-12)
def impact(qty,px,liq):
    v=qty*px; return v/(liq/2+v) if liq and liq>0 else 0.0
def open_position(b,xc,c,r,pair,sources,reasons,now,fill_fn):
    size=float(xc["size_usd"])
    if b["cash"]<size: return None,f"cash ${b['cash']:.2f} < ${size:.2f}"
    px=float(pair["priceUsd"]); liq=c.get("liq") or c.get("liq_est")
    e,imp,chase=fill_fn(px,liq,size,c.get("m5")); qty=size/e
    sym=(pair.get("baseToken") or {}).get("symbol") or c.get("ticker") or "?"
    t=now.isoformat(timespec="seconds")
    p=dict(id=f"CTR-{now:%Y%m%d%H%M%S}-{sym[:10]}",experiment=NAME,symbol=sym,mint=c["contract"],pair=pair.get("pairAddress"),size_usd=size,qty=qty,qty_open=qty,
           mkt_price_at_entry=px,entry_price=e,entry_liq=liq,entry_mcap=pair.get("marketCap"),entry_time=t,
           tp_price=e*xc["tp_x"],stop_price=e*(1+xc["stop_pct"]/100),timeout_at=(now+D.timedelta(hours=xc["timeout_h"])).isoformat(timespec="seconds"),
           track_until=(now+D.timedelta(hours=xc["track_h"])).isoformat(timespec="seconds"),
           skip_reasons=list(reasons),primary_skip=primary_reason(reasons),sources=list(sources),primary_source=sources[-1] if sources else None,
           score=r["score"],label=r["label"],why=r["why"],soft_vetoes=soft_vetoes(r,xc),
           safety={"mint_authority":(c.get("rugcheck") or {}).get("mint_authority"),"freeze_authority":(c.get("rugcheck") or {}).get("freeze_authority"),
                   "rugged":(c.get("rugcheck") or {}).get("rugged"),"sell_route":c.get("sell_route"),"ring":c.get("ring"),"liq":liq,"m5":c.get("m5")},
           entry_cost_model={"fee_pct":EXIT_COST*100,"impact_pct":round(imp*100,3),"chase_pct":round(chase*100,3)},
           last_price=px,last_good_price=px,last_liq=liq,realized_usd=0.0,exit=None,
           track={"peak_px":px,"peak_x":round(px/e,4),"peak_time":t,"min_x":round(px/e,4),"reached":{},"done":False,"post_exit_peak_x":None})
    b["cash"]-=size; b["positions"].append(p); return p,f"${size:.2f} @ {e:.8g}"
def sell_all(b,p,px,liq,reason,now):
    imp=impact(p["qty_open"],px,liq); proceeds=p["qty_open"]*px*(1-EXIT_COST)*(1-imp); cost=p["qty_open"]*p["entry_price"]
    pnl=proceeds-cost; b["cash"]+=proceeds; p["realized_usd"]+=pnl; p["qty_open"]=0.0
    p["exit"]=dict(reason=reason,time=now.isoformat(timespec="seconds"),mkt_price=px,x_at_exit=round(px/p["entry_price"],4),proceeds_usd=round(proceeds,4),
                   pnl_usd=round(p["realized_usd"],4),pnl_pct=round(p["realized_usd"]/p["size_usd"]*100,2),impact_pct=round(imp*100,3))
    b["closed_trades"].append(dict(id=p["id"],symbol=p["symbol"],**p["exit"]))
    return p["exit"]
def step_position(b,p,xc,px,liq,now):
    """One price observation. Updates tracking (for track_h after entry) and applies the exits. Returns exit dict or None."""
    if px is None or p["track"]["done"]: return None
    tr=p["track"]; e=p["entry_price"]; t=now.isoformat(timespec="seconds")
    ref=p.get("last_good_price") or p["mkt_price_at_entry"]
    liq_max=max(p.get("entry_liq") or 0,p.get("liq_max_seen") or 0)
    rug=liq is not None and liq<RUG_LIQ and liq_max>=RUG_LIQ
    if px>JUMP_X*ref and not rug:   # sanity: unconfirmed spike -> needs the next observation to agree within 2x
        pend=p.get("pending_jump")
        if not (pend and pend/2<=px<=pend*2): p["pending_jump"]=px; return None
    p.pop("pending_jump",None); p["last_good_price"]=px
    if liq is not None: p["last_liq"]=liq; p["liq_max_seen"]=max(p.get("liq_max_seen") or 0,liq)
    in_window=now<=D.datetime.fromisoformat(p["track_until"])
    if in_window and not rug:
        x=px/e
        if x>tr["peak_x"]: tr["peak_x"]=round(x,4); tr["peak_px"]=px; tr["peak_time"]=t
        tr["min_x"]=round(min(tr["min_x"],x),4)
        for lv in xc.get("reach_levels") or [1.5,2,3]:
            k=f"{lv:g}x"
            if x>=lv and k not in tr["reached"]: tr["reached"][k]=t
        if p.get("exit"): tr["post_exit_peak_x"]=round(max(tr.get("post_exit_peak_x") or 0,x),4)
    ex=None
    if p["qty_open"]>1e-12:
        p["last_price"]=px
        if rug: ex=sell_all(b,p,px,liq,"RUG",now)
        elif px>=p["tp_price"]: ex=sell_all(b,p,px,liq,f"TP_{xc['tp_x']:g}X",now)
        elif px<=p["stop_price"]: ex=sell_all(b,p,px,liq,f"STOP_{xc['stop_pct']:g}",now)
        elif now>=D.datetime.fromisoformat(p["timeout_at"]): ex=sell_all(b,p,px,liq,f"TIMEOUT_{xc['timeout_h']:g}H",now)
    if rug: tr["done"]=True; tr["done_reason"]="rug"
    if not in_window: tr["done"]=True; tr["done_reason"]=f"{xc['track_h']}h tracking window over"
    return ex
def force_timeouts(b,xc,now):
    """No price for a position past its timeout (pair vanished): close at the last good price, flagged STALE."""
    out=[]
    for p in b["positions"]:
        if p["qty_open"]>1e-12 and now>=D.datetime.fromisoformat(p["timeout_at"])+D.timedelta(minutes=10):
            out.append((p,sell_all(b,p,p["last_price"],p.get("last_liq"),f"TIMEOUT_{xc['timeout_h']:g}H_STALE_PRICE",now)))
        if not p["track"]["done"] and now>D.datetime.fromisoformat(p["track_until"])+D.timedelta(minutes=10):
            p["track"]["done"]=True; p["track"]["done_reason"]="tracking window over (no fresh price)"
    return out
# ---------------- engine hook (called by gem_paper.cycle) ----------------
def run_cycle(st,cfg,cands,now,G,fill_fn,dry=False,fetch=True,exclude=()):
    """cands = [(ca, coin_state, c, r, pair)] scored this cycle by gem_paper. exclude = mints the main gem engine paper-entered in the
    last 24 h (those calls were taken, not skipped). Returns a summary dict."""
    xc=config(cfg)
    if not xc.get("active"): return {"active":False}
    lk=lock()
    try:
        b=load_book(xc,now); ts=now.timestamp(); ev=[]
        # 1) price every position still in its 24-h tracking window (one batched DexScreener call per 30 mints)
        live=[p for p in b["positions"] if not p["track"]["done"]]
        pairs={ca:pr for ca,_,_,_,pr in cands if pr}   # already fetched this cycle by gem_paper
        miss=sorted({p["mint"] for p in live}-set(pairs))
        if miss and fetch: pairs.update(G.fetch_pairs(miss,ttl=15))
        for p in live:
            pr=pairs.get(p["mint"])
            if not pr: continue
            ex=step_position(b,p,xc,float(pr["priceUsd"]),(pr.get("liquidity") or {}).get("usd"),now)
            if ex: ev.append(f"EXIT {p['symbol']} {ex['reason']} {ex['pnl_pct']:+.1f}%"); journal(dict(ts=now.isoformat(timespec="seconds"),type="CTR_EXIT",id=p["id"],symbol=p["symbol"],mint=p["mint"],
                     primary_skip=p["primary_skip"],skip_reasons=p["skip_reasons"],sources=p["sources"],peak_x_so_far=p["track"]["peak_x"],**ex),dry)
            if p["track"]["done"]:
                journal(dict(ts=now.isoformat(timespec="seconds"),type="CTR_TRACK_DONE",id=p["id"],symbol=p["symbol"],mint=p["mint"],track=p["track"],
                             exit=p.get("exit"),primary_skip=p["primary_skip"],sources=p["sources"]),dry)
        for p,ex in force_timeouts(b,xc,now):
            ev.append(f"EXIT {p['symbol']} {ex['reason']}"); journal(dict(ts=now.isoformat(timespec="seconds"),type="CTR_EXIT",id=p["id"],symbol=p["symbol"],mint=p["mint"],**ex),dry)
        # 2) new entries: skipped calls from the owner's sources
        chans,callers=owner_channels(); checks=0
        today=now.date().isoformat(); n_today=sum(1 for p in b["positions"] if p["entry_time"][:10]==today)
        n_open=sum(1 for p in b["positions"] if p["qty_open"]>1e-12)
        held={p["mint"] for p in b["positions"] if (now-D.datetime.fromisoformat(p["entry_time"])).total_seconds()<24*3600}
        done=st.setdefault("ctr_decided",{})
        for k in [k for k,v in done.items() if ts-v.get("ts",0)>48*3600]: done.pop(k)
        for ca,s,c,r,pr in sorted(cands,key=lambda x:-(x[1].get("last_alert") or 0)):
            if ca in held or ca in exclude or not pr: continue
            if n_open>=xc["max_open"] or n_today>=xc["max_entries_per_day"]: break
            if hard_vetoes(r) or r.get("score",0)<xc["min_score"] or ts-(s.get("last_alert") or 0)>xc["fresh_min"]*60: continue
            if r.get("label")=="PAPER_ENTRY" and not soft_vetoes(r,xc): continue
            srcs=owner_sources(s,chans,callers)
            if not srcs: continue
            key=f"{ca}:{int(s.get('last_alert') or 0)}"
            if done.get(key,{}).get("final"): continue
            if not c.get("rugcheck") or c["rugcheck"].get("error") or (xc.get("require_sell_route_ok") and c.get("sell_route")!="OK"):
                if checks>=xc["max_checks_per_cycle"]: continue
                checks+=1
                if not c.get("rugcheck") or c["rugcheck"].get("error"): c["rugcheck"]=G.rugcheck_digest(ca)
                if c.get("sell_route")!="OK" and not (c.get("rugcheck") or {}).get("error"):
                    c["sell_route"],_=G.sell_route(ca,(c.get("rugcheck") or {}).get("decimals"))
                r=G.score(c,cfg)
            ok,why,reasons=eligible(c,r,cfg,xc,srcs,s.get("last_alert"),ts)
            if not ok:
                final=why.startswith(("HARD","not from","main engine","no skip"))
                if done.get(key,{}).get("why")!=why:
                    journal(dict(ts=now.isoformat(timespec="seconds"),type="CTR_SKIP",mint=ca,ticker=r.get("ticker"),score=r.get("score"),why=why,sources=srcs),dry)
                done[key]={"ts":ts,"why":why,"final":final}; continue
            if dry: ev.append(f"DRY_OPEN {r.get('ticker')} {primary_reason(reasons)}"); done[key]={"ts":ts,"why":"dry","final":True}; continue
            p,msg=open_position(b,xc,c,r,pr,srcs,reasons,now,fill_fn)
            done[key]={"ts":ts,"why":msg if p else "no cash: "+msg,"final":bool(p)}
            if not p: continue
            held.add(ca); n_open+=1; n_today+=1; ev.append(f"OPEN {p['symbol']} [{p['primary_skip']}] via {p['primary_source']}")
            journal(dict(ts=p["entry_time"],type="CTR_ENTER",id=p["id"],symbol=p["symbol"],mint=ca,score=p["score"],label=p["label"],primary_skip=p["primary_skip"],
                         skip_reasons=reasons,sources=srcs,size_usd=p["size_usd"],entry_price=p["entry_price"],mkt_price=p["mkt_price_at_entry"],
                         tp_price=p["tp_price"],stop_price=p["stop_price"],timeout_at=p["timeout_at"],safety=p["safety"],why=p["why"],cost_model=p["entry_cost_model"]),dry)
        b["equity"]=round(equity(b),4); b["last_run"]=now.isoformat(timespec="seconds"); b["config"]={k:xc[k] for k in ("size_usd","tp_x","stop_pct","timeout_h","track_h","min_score","fresh_min","max_open")}
        if not dry: save_book(b)
        return {"active":True,"equity":b["equity"],"cash":round(b["cash"],2),"open":n_open,"events":ev,"checks":checks}
    finally: lk.close()
# ---------------- scorecard ----------------
def _stats(ps):
    cl=[p for p in ps if p.get("exit")]
    if not ps: return {"n":0}
    tp=[p for p in cl if p["exit"]["reason"].startswith("TP_")]
    tracked=[p for p in ps if p["track"]["done"]]
    def reach(lst,k): return round(sum(1 for p in lst if k in p["track"]["reached"])/len(lst)*100,1) if lst else None
    pnl=[p["exit"]["pnl_pct"] for p in cl]
    return {"n":len(ps),"closed":len(cl),"open":len(ps)-len(cl),"tp_hits":len(tp),"tp_hit_rate_pct":round(len(tp)/len(cl)*100,1) if cl else None,
            "avg_result_pct":round(sum(pnl)/len(pnl),2) if pnl else None,"pnl_usd":round(sum(p["exit"]["pnl_usd"] for p in cl),2),
            "staked_usd":round(sum(p["size_usd"] for p in cl),2),
            "reached_1.5x_pct":reach(ps,"1.5x"),"reached_2x_pct":reach(ps,"2x"),"reached_3x_pct":reach(ps,"3x"),
            "reached_1.5x_pct_tracked24h":reach(tracked,"1.5x"),"n_tracked_24h":len(tracked),
            "median_max_x":sorted(p["track"]["peak_x"] for p in ps)[len(ps)//2],
            "exits":{k:sum(1 for p in cl if p["exit"]["reason"]==k) for k in sorted({p["exit"]["reason"] for p in cl})}}
def scorecard(book_path=BOOK):
    b=jl(book_path,None)
    if not b: return None
    ps=b.get("positions",[]); by_reason={}; by_primary={}; by_src={}; by_kind={}
    for p in ps:
        by_primary.setdefault(p.get("primary_skip") or "?",[]).append(p)
        for k in p.get("skip_reasons") or []: by_reason.setdefault(k,[]).append(p)
        by_src.setdefault(p.get("primary_source") or "?",[]).append(p)
        for k in {source_kind(t) for t in p.get("sources") or []}: by_kind.setdefault(k,[]).append(p)
    return {"experiment":NAME,"start_usd":b.get("starting_balance"),"equity":round(equity(b),2),"cash":round(b["cash"],2),"started_et":b.get("started_et"),
            "config":b.get("config"),"overall":_stats(ps),"by_primary_skip":{k:_stats(v) for k,v in sorted(by_primary.items())},
            "by_any_skip_reason":{k:_stats(v) for k,v in sorted(by_reason.items())},"by_primary_source":{k:_stats(v) for k,v in sorted(by_src.items())},
            "by_source_kind":{k:_stats(v) for k,v in sorted(by_kind.items())},
            "trades":[{k:p.get(k) for k in ("id","symbol","mint","entry_time","score","primary_skip","skip_reasons","primary_source","size_usd")}|
                      {"exit":p.get("exit"),"peak_x":p["track"]["peak_x"],"reached":p["track"]["reached"],"tracking_done":p["track"]["done"],"post_exit_peak_x":p["track"].get("post_exit_peak_x")} for p in ps]}
def fmt(s):
    if not s.get("n"): return "none"
    return (f"n {s['n']} ({s['closed']} closed), TP {s['tp_hits']}/{s['closed']} ({s['tp_hit_rate_pct']}%), avg {s['avg_result_pct']}%/closed, P&L ${s['pnl_usd']:+.2f}, "
            f"reached 1.5x/2x/3x {s['reached_1.5x_pct']}/{s['reached_2x_pct']}/{s['reached_3x_pct']}%, median max {s['median_max_x']}x")
def scorecard_md(sc,now):
    if not sc: return [f"## Experiment {NAME}: no book yet (no entries)"]
    o=sc["overall"]; cf=sc.get("config") or {}
    md=[f"## Experiment {NAME} (PAPER ONLY, separate sub-book; not mixed into the gem/main numbers above)",
        f"Calls our filters skipped (soft fails, score >= {cf.get('min_score')}) from the owner's sources; ${cf.get('size_usd')} each; exit TP {cf.get('tp_x')}x / stop {cf.get('stop_pct')}% / {cf.get('timeout_h')} h; every entry tracked {cf.get('track_h')} h for max multiple. Multiples vs entry fill (incl. 1.5% entry cost).",
        f"- Sub-book: equity ${sc['equity']} (start ${sc['start_usd']}, cash ${sc['cash']}), started {sc.get('started_et')}",
        f"- Overall: {fmt(o)}",
        "- By primary skip reason: "+("; ".join(f"{k}: {fmt(v)}" for k,v in sc["by_primary_skip"].items()) or "none"),
        "- By any skip reason (a trade counts under each): "+("; ".join(f"{k}: n {v['n']}, TP {v['tp_hit_rate_pct']}%, avg {v['avg_result_pct']}%" for k,v in sc["by_any_skip_reason"].items()) or "none"),
        "- By source kind: "+("; ".join(f"{k}: {fmt(v)}" for k,v in sc["by_source_kind"].items()) or "none"),
        "- By primary source (latest call): "+("; ".join(f"{k}: n {v['n']}, TP {v['tp_hit_rate_pct']}%, avg {v['avg_result_pct']}%, med max {v.get('median_max_x')}x" for k,v in sc["by_primary_source"].items()) or "none"),
        "","### Contrarian trades"]
    for t in sc["trades"][-40:]:
        ex=t["exit"]
        md.append(f"- {t['symbol']} {t['mint'][:6]}.. {t['entry_time'][5:16]} score {t['score']} [{t['primary_skip']}; {','.join(t['skip_reasons'] or [])}] via {t['primary_source']}: "
                  +(f"{ex['reason']} {ex['pnl_pct']:+.1f}%" if ex else "OPEN")+f", max {t['peak_x']}x"+(f" (after exit {t['post_exit_peak_x']}x)" if t.get("post_exit_peak_x") else "")
                  +f", reached {'/'.join(t['reached']) or '-'}"+("" if t["tracking_done"] else " (tracking)"))
    if not sc["trades"]: md.append("- none yet")
    return md
