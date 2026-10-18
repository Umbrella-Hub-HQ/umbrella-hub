#!/usr/bin/env python3
"""adaptive_watcher.py - PAPER ONLY. stdlib, read-only GETs to DexScreener. Never trades, signs, or touches wallets.
Exit rules come from paper_monitor.apply_rules / sell / update_equity (single source of truth), and book writes use
paper_monitor.book_lock() (fcntl on paper_book.lock) so this and the hourly paper_monitor.py can't clash.

Each loop it fetches every coin that's due in ONE batched call (api.dexscreener.com/tokens/v1/solana/<a,b,c>, up to 30),
uses the book's pair (or falls back to the deepest Solana pair), applies the rules, then picks the next check per coin:
  PROFIT (>= +25% vs fill): always HOT 15s. No 2x trigger (reference install 2026-10-13). Momentum STRONG/NEUTRAL/FADING/
               BREAKING, the profit lock and the ratcheting stop live in paper_monitor.momentum/runner_trail/apply_rules. m1 is computed from
               this watcher's own price history (~45-180s back); liquidity change vs the previous check is passed in.
  HOT    15s : within 10% of a trigger (stop, 2x, trail level after TP1, or <15 min to the time stop);
               |m5 change| > 8%; m5 sells >= 2x buys (with >=10 sells); liquidity down >5% since last check
               or >10% from the session max; m5 volume >= 3x the h1 per-5m average.
  ACTIVE 30-60s : within 20% of a trigger; |m5| > 3% or |h1| > 15%; m5 sells > 1.3x buys; m5 vol >= 1.5x avg.
               45s by default, 30s when two or more ACTIVE signals hit at once.
  CALM   90-120s: everything else. 120s when |h1| < 5% and >40% from every trigger, otherwise 90s (was 180-300s until
               2026-10-13: our own data shows peak->dump medians of 7-12 min, so 5-min gaps could miss most of a dump).
  If a fetch fails the coin goes to 30s. Since 2026-10-17 a failed DexScreener fetch (or missing pair) falls back to
               DexPaprika keyless price-only (PM.dexpaprika_prices, budget-capped); price rules only, flow rules skipped. On HTTP 429 or other errors: exponential backoff (15s -> 300s max).
DexScreener's limit is about 300 req/min for this endpoint; we use at most ~4/min per batch, so we stay well under it.
Outputs: paper_book.json + paper_log.md (only when something changes, written atomically under the lock),
events.jsonl (one line per exit, half-sale, or halt flip), watcher_status.json (heartbeat every loop).
Usage: python3 adaptive_watcher.py [--dry-run] [--once]   (--dry-run = fetch+classify+report, never writes the book/log/events)
"""
import json,os,sys,time,urllib.request,urllib.error,datetime as D
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE)
import paper_monitor as PM
BOOK=PM.BOOK; LOG=os.path.join(HERE,"paper_log.md"); EVENTS=os.path.join(HERE,"events.jsonl")
STATUS=os.path.join(HERE,"watcher_status.json"); ET=PM.ET
DRY="--dry-run" in sys.argv; ONCE="--once" in sys.argv
UA={"User-Agent":"Mozilla/5.0 (paper-watcher)"}
def now(): return D.datetime.now(ET)
def log(m): print(f"[{now():%Y-%m-%d %H:%M:%S} ET] {m}",flush=True)

class RateLimited(Exception): pass
def fetch_batch(mints):
    out={}
    for i in range(0,len(mints),30):
        url="https://api.dexscreener.com/tokens/v1/solana/"+",".join(mints[i:i+30])
        try: d=json.load(urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=20))
        except urllib.error.HTTPError as e:
            if e.code==429: raise RateLimited()
            raise
        for p in d if isinstance(d,list) else d.get("pairs") or []:
            if p.get("chainId")=="solana" and p.get("priceUsd"):
                out.setdefault(p["baseToken"]["address"],[]).append(p)
    return out
def pick(pairs,pair):
    return next((p for p in pairs if p.get("pairAddress")==pair),None) or max(pairs,key=lambda p:(p.get("liquidity") or {}).get("usd") or 0)

def fallback(positions,status,due,t,why):
    """DexScreener failed (or had no pair) for these positions -> DexPaprika price-only (added 2026-10-17).
    Returns {mint:(px,None,None,None,None)} for commit(): pair=None so apply_rules runs price rules only
    (stop, lock/trail, time stop), never flow-based momentum. Next check >=30s, never sooner than an active backoff. {} if DexPaprika also fails/over budget."""
    fb=PM.dexpaprika_prices([p["mint"] for p in positions]); out={}
    for p in positions:
        if p["mint"] not in fb: continue
        px,upd=fb[p["mint"]]; out[p["mint"]]=(px,None,None,None,None); due[p["mint"]]=max(due.get(p["mint"],0),time.time()+30)  # never shortens a 429 backoff
        status[p["symbol"]]={"tier":"FALLBACK","interval_s":30,"reason":f"{why}; DexPaprika price-only (updated {upd})","price":px,"source":"dexpaprika","checked":t.isoformat(timespec="seconds")}
    if out: log(f"FALLBACK DexPaprika price-only for {len(out)} coin(s): {why}")
    return out

def classify(b,pos,p,mem,t):
    px=float(p["priceUsd"]); pc=p.get("priceChange") or {}; tx=p.get("txns") or {}; vol=p.get("volume") or {}
    m5=pc.get("m5") or 0; h1=pc.get("h1") or 0
    b5=(tx.get("m5") or {}).get("buys",0); s5=(tx.get("m5") or {}).get("sells",0)
    v5=vol.get("m5") or 0; vavg=(vol.get("h1") or 0)/12; vr=v5/vavg if vavg>0 else 0
    liq=(p.get("liquidity") or {}).get("usd") or 0
    prev=mem.get("liq"); mx=max(mem.get("liq_max",0),liq); mem["liq"]=liq; mem["liq_max"]=mx
    dliq=(liq/prev-1)*100 if prev else 0; dmax=(liq/mx-1)*100 if mx else 0
    d={}  # distance to each trigger, as % of price
    ls=PM.exit_params(pos)["lock_start"]   # per-position exit experiment (exit_lock_50 = +50%); v3.2a default +10%
    if pos.get("lock_active") or max(pos["peak_price"],px)>=pos["entry_price"]*ls:
        stop,_=PM.runner_trail(dict(pos,peak_price=max(pos["peak_price"],px)),pos.get("last_momentum") or "NEUTRAL")
        d["lock_stop"]=(px/max(stop,pos.get("runner_stop",0))-1)*100
    else: d["stop"]=(px/pos["stop_price"]-1)*100; d["lock_on"]=(pos["entry_price"]*ls/px-1)*100
    mins_left=(D.datetime.fromisoformat(pos["time_stop_at"])-t).total_seconds()/60
    near=min(d,key=d.get); nd=d[near]
    hot=[]; act=[]
    if px>=pos["entry_price"]*PM.HOT_MULT: hot.append(f"in profit {px/pos['entry_price']:.2f}x fill (momentum {pos.get('last_momentum') or 'new'})")
    if nd<=10: hot.append(f"{nd:.1f}% from {near}")
    if mins_left<=15: hot.append(f"time stop in {mins_left:.0f}m")
    if abs(m5)>8: hot.append(f"m5 {m5:+.1f}%")
    if s5>=10 and s5>=2*max(b5,1): hot.append(f"sells {s5}>>buys {b5} (m5)")
    if dliq<-5 or dmax<-10: hot.append(f"liq dropping ({dliq:+.1f}% vs last, {dmax:+.1f}% vs max)")
    if vr>=3: hot.append(f"vol spike {vr:.1f}x h1 avg")
    if hot: return "HOT",15,"; ".join(hot),px
    if nd<=20: act.append(f"{nd:.1f}% from {near}")
    if abs(m5)>3: act.append(f"m5 {m5:+.1f}%")
    if abs(h1)>15: act.append(f"h1 {h1:+.1f}%")
    if s5>1.3*max(b5,1): act.append(f"sells {s5}>buys {b5}")
    if vr>=1.5: act.append(f"vol {vr:.1f}x avg")
    if act: return "ACTIVE",(30 if len(act)>=2 else 45),"; ".join(act),px
    iv=120 if abs(h1)<5 and nd>40 else 90   # was 180-300s; tightened 2026-10-13: called coins dump ~7-12 min after peak (research/caller_2x_survival)
    return "CALM",iv,f"flat (m5 {m5:+.1f}%, h1 {h1:+.1f}%), b/s {b5}/{s5}, vol {vr:.1f}x, nearest {near} {nd:.0f}% away",px

def atomic_write(path,text):
    tmp=path+".tmp"; open(tmp,"w").write(text); os.replace(tmp,path)

def commit(prices,t):
    """Under the lock: reload the book fresh, apply rules to the prices we just got, write if anything changed."""
    lk=PM.book_lock()
    try:
        b=json.load(open(BOOK)); exits=[]; ev=[]; dec=[]
        if b.get("day")!=t.date().isoformat(): b["day"]=t.date().isoformat(); b["day_start_equity"]=None
        halt0=bool(b.get("daily_halt_new_entries")); lad0=(b.get("loss_ladder") or {}).get("state","OK")
        for pos in b["positions"]:
            if pos["qty_open"]<=1e-12 or pos["mint"] not in prices: continue
            px,mc,pair,m1,lp=prices[pos["mint"]]
            pos["last_price"]=px; pos["last_mcap"]=mc if mc is not None else pos.get("last_mcap"); pos["last_checked"]=t.isoformat(timespec="seconds")
            n0=len(b["closed_trades"]); ex,dc=PM.apply_rules(b,pos,px,t,pair,m1,lp); exits+=ex; dec+=dc
            for ct in b["closed_trades"][n0:]: ev.append({"ts":t.isoformat(timespec="seconds"),"type":ct["event"],**ct})
        PM.update_equity(b,t)
        if b["loss_ladder"]["state"]!=lad0:
            ev.append({"ts":t.isoformat(timespec="seconds"),"type":"LOSS_LADDER_"+b["loss_ladder"]["state"],"day_pnl_pct":b["day_pnl_pct"],"equity":b["equity"],"ladder":b["loss_ladder"]})
        if bool(b["daily_halt_new_entries"])!=halt0:
            ev.append({"ts":t.isoformat(timespec="seconds"),"type":"DAILY_HALT_ON" if b["daily_halt_new_entries"] else "DAILY_HALT_OFF","day_pnl_pct":b["day_pnl_pct"],"equity":b["equity"]})
        for e in ev:
            if e["type"].startswith(("DAILY","LOSS_LADDER")): dec.append(dict(e,symbol="BOOK",price=e["equity"],reason=f"day {e['day_pnl_pct']:+.1f}% equity; ladder {b['loss_ladder']}"))
            else: dec.append(dict(e,price=e["exit_mkt_price"]))
        if DRY: return b,exits,dec
        atomic_write(BOOK,json.dumps(b,indent=1))
        PM.record(b,dec,exits,t)
        return b,exits,dec
    finally: lk.close()

def main():
    log(f"start pid {os.getpid()} dry_run={DRY}")
    due={}; mem={}; status={}; backoff=0
    while True:
        b=json.load(open(BOOK)); t=now()
        open_pos=[p for p in b["positions"] if p["qty_open"]>1e-12]
        if not open_pos:
            log("no open positions - exiting"); atomic_write(STATUS,json.dumps({"heartbeat":t.isoformat(timespec="seconds"),"pid":os.getpid(),"state":"EXITED_NO_POSITIONS","coins":{}},indent=1)); return
        ready=[p for p in open_pos if due.get(p["mint"],0)<=time.time()+10]  # coalesce coins due within 10s into one call
        err=None
        if ready:
            try:
                data=fetch_batch([p["mint"] for p in ready]); backoff=0
            except RateLimited: err="HTTP 429"; data=None
            except Exception as e: err=f"{type(e).__name__}: {e}"; data=None
            if data is None:
                backoff=min(300,max(15,backoff*2)); log(f"fetch failed ({err}), backing off {backoff}s")
                for p in ready: due[p["mint"]]=time.time()+backoff
                fbp=fallback(ready,status,due,t,f"DexScreener {err}")
                if fbp:
                    b2,exits,ev=commit(fbp,t)
                    for e in exits: log(("DRY " if DRY else "")+"EXIT "+e)
                    for e in ev: log(("DRY " if DRY else "")+f"DECISION {e['type']} {e.get('symbol')}: {e.get('reason')}")
            else:
                prices={}; nopair=[]
                for p in ready:
                    pairs=data.get(p["mint"])
                    if not pairs:
                        status[p["symbol"]]={"tier":"ACTIVE","interval_s":30,"reason":"no pair data in response"}; due[p["mint"]]=time.time()+30; nopair.append(p); continue
                    pr=pick(pairs,p["pair"]); m=mem.setdefault(p["mint"],{})
                    tier,iv,reason,px=classify(b,p,pr,m,t)
                    h=m.setdefault("hist",[]); h.append((time.time(),px)); m["hist"]=h=[x for x in h if time.time()-x[0]<=180]
                    old=[x for x in h if time.time()-x[0]>=45]; m1=(px/old[-1][1]-1)*100 if old else None
                    prices[p["mint"]]=(px,pr.get("marketCap"),pr,m1,m.get("liq_prev"))
                    m["liq_prev"]=(pr.get("liquidity") or {}).get("usd")
                    status[p["symbol"]]={"tier":tier,"interval_s":iv,"reason":reason,"price":px,"liq_usd":(pr.get("liquidity") or {}).get("usd"),"checked":t.isoformat(timespec="seconds")}
                    due[p["mint"]]=time.time()+iv
                if nopair: prices.update(fallback(nopair,status,due,t,"DexScreener returned no pair"))
                if prices:
                    b2,exits,ev=commit(prices,t)
                    for e in exits: log(("DRY " if DRY else "")+"EXIT "+e)
                    for e in ev: log(("DRY " if DRY else "")+f"DECISION {e['type']} {e.get('symbol')}: {e.get('reason')}")
                    for sym in list(status):
                        pos=next((q for q in b2["positions"] if q["symbol"]==sym),None)
                        if pos and pos["qty_open"]<=1e-12: status[sym]={"tier":"CLOSED","reason":"position closed"}
                    log(" | ".join(f"{s}:{v['tier']}" for s,v in status.items())+f" | equity ${b2['equity']:.2f}")
        nxt=min([due.get(p["mint"],0) for p in open_pos]+[time.time()+300])
        st={"heartbeat":now().isoformat(timespec="seconds"),"pid":os.getpid(),"dry_run":DRY,"last_error":err,"backoff_s":backoff,
            "next_fetch_in_s":round(max(0,nxt-time.time())),"coins":status}
        if not DRY: atomic_write(STATUS,json.dumps(st,indent=1))
        if ONCE: print(json.dumps(st,indent=1)); return
        # sleep in short slices so the heartbeat stays fresh even when everything is CALM
        time.sleep(max(1,min(60,nxt-time.time())))
if __name__=="__main__": main()
