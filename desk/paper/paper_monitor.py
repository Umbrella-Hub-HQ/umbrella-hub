#!/usr/bin/env python3
"""paper_monitor.py - PAPER ONLY, stdlib, read-only network (GET DexScreener; DexPaprika price-only fallback since 2026-10-17). Never trades/signs/touches wallets.
Reloads paper_book.json, prices open positions, applies: stop -30% (from fill), 24h time stop, and momentum rules at
every gain level with a scaling profit lock (no 2x trigger - reference install 2026-10-13). Exits cost 1.5% (3% round trip with entry). Idempotent: each exit
is a state transition (qty_open/tp1_done) so re-running at the same price changes nothing. Atomic write.
Usage: python3 paper_monitor.py [--tg]   (--tg also runs the Telegram mention check via tg_mentions.py)"""
import json,os,sys,time,urllib.request,datetime as D
HERE=os.path.dirname(os.path.abspath(__file__)); BOOK=os.path.join(HERE,"paper_book.json")
ET=D.timezone(D.timedelta(hours=-4)); EXIT_COST=0.015
# ---- DexPaprika price-only FALLBACK (added 2026-10-17, research/dexpaprika-ccxt-eval-2026-10-17.md) ----
# Used ONLY when DexScreener fails or returns no pair for a mint. Keyless GET, read-only, no key/wallet.
# Price only: DexPaprika's buy/sell counts disagree with DexScreener/GeckoTerminal, so flow-based momentum is NOT
# fed from it (callers pass pair=None -> apply_rules runs the price rules only, same as the hourly no-pair path).
# Keyless budget is 10,000 credits per IP per rolling 30 days and 15 req/min (box IP is shared), so a local ledger
# caps us at DP_DAILY credits/day and DP_PER_MIN requests/min. Over budget -> returns {} (old behavior).
# UA matters (tested 2026-10-17): a browser-like "Mozilla/5.0 ..." UA is billed as "anonymous" and got 402, Python's
# default UA gets Cloudflare 1010; a plain tool UA gets the normal keyless tier.
DP_URL="https://api.dexpaprika.com/networks/solana/multi/prices?tokens="
DP_USAGE=os.path.join(HERE,"dexpaprika_usage.json"); DP_DAILY=int(os.environ.get("DP_DAILY_CREDITS","250")); DP_PER_MIN=8; DP_MAX_AGE_S=600
def dexpaprika_prices(mints):
    """{mint: (price_usd, last_updated_iso)} for up to 10 mints per request. {} on any error or when over budget."""
    mints=[m for m in dict.fromkeys(mints) if m][:10]
    if not mints: return {}
    now=time.time(); day=D.datetime.now(ET).strftime("%Y-%m-%d")
    try: u=json.load(open(DP_USAGE))
    except Exception: u={}
    recent=[t for t in u.get("recent",[]) if now-t<60]
    if u.get(day,0)+len(mints)>DP_DAILY or len(recent)>=DP_PER_MIN: return {}
    u[day]=u.get(day,0)+len(mints); u["recent"]=recent+[now]
    for k in [k for k in u if k[:2]=="20" and k<(D.datetime.now(ET)-D.timedelta(days=31)).strftime("%Y-%m-%d")]: u.pop(k)
    try: tmp=DP_USAGE+".tmp"; open(tmp,"w").write(json.dumps(u)); os.replace(tmp,DP_USAGE)
    except Exception: pass
    try:
        d=json.load(urllib.request.urlopen(urllib.request.Request(DP_URL+",".join(mints),headers={"User-Agent":"desk-paper-fallback/1.0 (read-only)"}),timeout=15))
        out={}
        for x in d:   # skip zero/missing prices and prices older than DP_MAX_AGE_S (no fallback beats a stale fallback)
            try: age=time.time()-D.datetime.fromisoformat(x["last_updated"].replace("Z","+00:00")).timestamp()
            except Exception: age=1e9
            if x.get("price_usd") and float(x["price_usd"])>0 and age<=DP_MAX_AGE_S: out[x["id"]]=(float(x["price_usd"]),x.get("last_updated"))
        return out
    except Exception: return {}
def price(mint,pair):
    try:
        d=json.load(urllib.request.urlopen(urllib.request.Request(f"https://api.dexscreener.com/latest/dex/tokens/{mint}",headers={"User-Agent":"Mozilla/5.0"}),timeout=20))
        ps=[p for p in d.get("pairs") or [] if p.get("chainId")=="solana" and p.get("priceUsd")]
        p=next((p for p in ps if p.get("pairAddress")==pair),None) or max(ps,key=lambda p:(p.get("liquidity") or {}).get("usd") or 0)
        return float(p["priceUsd"]),p.get("marketCap"),p
    except Exception:
        fb=dexpaprika_prices([mint]).get(mint)   # price-only fallback; pair=None -> price rules only
        return (fb[0],None,None) if fb else (None,None,None)
def impact(pos,qty,px):
    """Constant-product price impact of selling qty into the pool (x*y=k, USD side = liquidity/2). 0 if liquidity unknown.
    Added 2026-10-13 (bot-trading comparison): flat 1.5% exit cost ignored size vs pool depth."""
    liq=pos.get("last_liq") or 0; v=qty*px
    return v/(liq/2+v) if liq>0 else 0.0
def sell(b,pos,qty,px,reason,now):
    imp=impact(pos,qty,px)
    proceeds=qty*px*(1-EXIT_COST)*(1-imp); cost=qty*pos["entry_price"]
    pos["qty_open"]-=qty; pos["realized_usd"]+=proceeds-cost; b["cash"]+=proceeds
    b["closed_trades"].append({"id":pos["id"],"symbol":pos["symbol"],"event":"CLOSE" if pos["qty_open"]<=1e-12 else "PARTIAL_CLOSE",
        "reason":reason,"exit_time":now.isoformat(timespec="seconds"),"exit_mkt_price":px,"qty":qty,"proceeds_usd":round(proceeds,4),
        "pnl_usd":round(proceeds-cost,4),"pnl_pct":round((px*(1-EXIT_COST)*(1-imp)/pos["entry_price"]-1)*100,2),"impact_pct":round(imp*100,3)})
    return f"{pos['symbol']} {reason}: sold {qty/pos['qty']*100:.0f}% @ {px:.8g} pnl ${proceeds-cost:+.2f}"
# ---- Exit rules v3 (reference install 2026-10-13): NO 2x trigger anywhere. Momentum applies at every gain level. ----
LOCK_START=1.10       # peak >= +10% vs fill -> PROFIT LOCK active (stop can't fall below breakeven after exit cost)
BE_MULT=1/(1-EXIT_COST)   # ~1.0152x fill = net breakeven
LOCK_KEEP_FROM=1.50   # peak >= +50% -> floor also keeps at least half of the peak gain: entry*(1+0.5*(peak/entry-1))
TRAIL_STRONG=[(3,0.30),(5,0.25),(1e9,0.20)]   # trail off peak by peak multiple when STRONG
TRAIL_NEUTRAL=0.25; TRAIL_FADING=0.20; TRAIL_EXTENDED=0.20
FADE_MIN_MULT=1.25    # FADING partial sale only when price >= +25% vs fill (never partial-sell a loss or a rounding gain)
FADE_SELL_FRAC=[0.40,0.50]; FADE_COOLDOWN_S=300
PRELOCK_BREAK_M5=-5   # below the lock zone, BREAKING (sell-flow / liquidity-pull) also needs m5 <= -5% to exit
HOT_MULT=1.25         # watcher forces HOT 15s once price >= +25% (or the lock is active and within 10% of the stop)
def momentum(pair,pos,m1=None,liq_prev=None):
    """Classify a runner's momentum from a DexScreener pair -> (STRONG|NEUTRAL|FADING|BREAKING, reason, metrics).
    DexScreener has no unique-buyer count, so the buy/sell txn counts stand in for it."""
    if not pair: return "NEUTRAL","no pair data",{}
    pc=pair.get("priceChange") or {}; tx=pair.get("txns") or {}; vol=pair.get("volume") or {}
    px=float(pair["priceUsd"]); m5=pc.get("m5") or 0; h1=pc.get("h1") or 0
    b5=(tx.get("m5") or {}).get("buys",0); s5=(tx.get("m5") or {}).get("sells",0)
    vavg=(vol.get("h1") or 0)/12; vr=(vol.get("m5") or 0)/vavg if vavg>0 else 0
    liq=(pair.get("liquidity") or {}).get("usd") or 0; mc=pair.get("marketCap") or pair.get("fdv") or 0
    liq_ref=liq_prev or pos.get("runner_liq_peak") or liq
    dliq=(liq/liq_ref-1) if liq_ref else 0; lmc=liq/mc if mc else 0
    dpk=1-px/max(pos["peak_price"],px)
    met=dict(m1=m1,m5=m5,h1=h1,buys5=b5,sells5=s5,vol_ratio=round(vr,2),liq=liq,liq_chg=round(dliq*100,1),liq_mcap=round(lmc*100,1),mcap=mc,from_peak_pct=round(dpk*100,1))
    br=[]
    if dpk>=0.15 and m5<0: br.append(f"{dpk*100:.0f}% off peak with m5 {m5:+.1f}%")
    if s5>=10 and s5>=2*max(b5,1): br.append(f"sell flow {s5} vs {b5} buys")
    if dliq<=-0.20: br.append(f"liquidity pulled {dliq*100:.0f}%")
    if br: return "BREAKING","; ".join(br),met
    fd=[]
    if m5<=0.5: fd.append(f"m5 flat/neg {m5:+.1f}%")
    if m1 is not None and m1<0: fd.append(f"m1 {m1:+.1f}%")
    if s5>b5: fd.append(f"sells {s5}>buys {b5}")
    if vr<1: fd.append(f"vol {vr:.1f}x avg")
    if dpk>=0.08: fd.append(f"{dpk*100:.0f}% off peak")
    if dliq<=-0.08: fd.append(f"liq {dliq*100:.0f}%")
    if lmc and lmc<0.03: fd.append(f"thin liq/mcap {lmc*100:.1f}%")
    if len(fd)>=2: return "FADING","; ".join(fd),met
    if m5>0 and b5>=1.2*max(s5,1) and vr>=1 and dliq>-0.05 and (m1 is None or m1>=0):
        return "STRONG",f"m5 {m5:+.1f}%, buys {b5} vs sells {s5}, vol {vr:.1f}x, liq {dliq*100:+.0f}%",met
    return "NEUTRAL","mixed: "+("; ".join(fd) or f"m5 {m5:+.1f}%, b/s {b5}/{s5}, vol {vr:.1f}x"),met
# ---- Per-position exit EXPERIMENTS (PAPER ONLY). reference install 2026-10-17: test the wider exit on gem paper positions.
# A position opts in with pos["exit_experiment"]; positions without it keep exit rules v3.2a exactly (protocols/exit-rules.md unchanged).
# exit_lock_50 = desk/scoring/backtest.py EXIT_VARIANT=wide: profit lock (stop >= net breakeven) only at peak >= +50%; keep half the
# peak gain from 2x; trail 35% below 3x, 30% at 3-5x, 25% above 5x (STRONG and NEUTRAL); FADING 25%; past 24h 20%.
# Unchanged for it: -30% hard stop until the lock, RUG/SANITY guards, BREAKING (pre-lock still needs m5 <= -5%), FADING partials at >= +25%, 24h time stop.
EXIT_EXPERIMENTS={"exit_lock_50":{"lock_start":1.50,"keep_from":2.00,"trail_strong":[(3,0.35),(5,0.30),(1e9,0.25)],"trail_neutral":[(3,0.35),(5,0.30),(1e9,0.25)],"trail_fading":0.25}}
def exit_params(pos):
    x=EXIT_EXPERIMENTS.get((pos or {}).get("exit_experiment") or "")
    if not x: return {"lock_start":LOCK_START,"keep_from":LOCK_KEEP_FROM,"trail_strong":TRAIL_STRONG,"trail_neutral":TRAIL_NEUTRAL,"trail_fading":TRAIL_FADING,"name":"v3.2a"}
    return dict(x,name=pos["exit_experiment"])
def runner_trail(pos,mom,extended=False):
    e=pos["entry_price"]; g=pos["peak_price"]/e; xp=exit_params(pos)
    if g<xp["lock_start"]: return 0.0,None
    tn=xp["trail_neutral"]
    if extended: t=TRAIL_EXTENDED
    elif mom=="STRONG": t=next(t for lim,t in xp["trail_strong"] if g<lim)
    elif mom=="FADING": t=xp["trail_fading"]
    else: t=next(t for lim,t in tn if g<lim) if isinstance(tn,list) else tn
    floor=e*BE_MULT
    if g>=xp["keep_from"]: floor=max(floor,e*(1+0.5*(g-1)))
    return max(floor,pos["peak_price"]*(1-t)),t
# ---- Rug / sanity guard (reference install 2026-10-17, paper only). Origin (reference install, 2026-10-16):
# liquidity fell to $0.08 and DexScreener printed 16.063 (83,424x fill), which the rules took as a peak -> lock/FADE/trail.
JUMP_X=10          # a tick > 10x the last accepted price must be confirmed by a 2nd source before it can set a peak
CONFIRM_TOL=2.0    # 2nd-source price must be within 2x of the tick to confirm it
RUG_LIQ_USD=100    # pair liquidity below $100 (or <1% of the max seen) -> sell all, reason RUG
def second_price(mint):
    """2nd-source USD price: GeckoTerminal simple token price, then DexPaprika (budget-capped). None if both fail.
    NOTE (2026-10-17 readiness): neither is proof of freshness by itself; see sanity_check() for what counts as confirmation."""
    try:
        d=json.load(urllib.request.urlopen(urllib.request.Request(f"https://api.geckoterminal.com/api/v2/simple/networks/solana/token_price/{mint}",headers={"User-Agent":"desk-paper-sanity/1.0 (read-only)","Accept":"application/json"}),timeout=15))
        v=float(((d.get("data") or {}).get("attributes") or {}).get("token_prices",{}).get(mint) or 0)
        if v>0: return v,"geckoterminal"
    except Exception: pass
    fb=dexpaprika_prices([mint]).get(mint)
    return (fb[0],"dexpaprika") if fb else (None,None)
# ---- v3.2a on-chain reserve check (reference install 2026-10-17 "proceed", paper only). DexScreener
# AND DexPaprika were both hours stale on VEILTRUMP (~5x) and HUMPH (~2x) vs the pool vaults, so API agreement is not proof.
# Order: (1) pool vault reserves via the PUBLIC Solana RPC (keyless, no Helius credits) decide when readable;
# (2) if the vaults can't be read (e.g. Raydium shared-authority vaults), only a DexPaprika price stamped <= DP_MAX_AGE_S old
#     may confirm; GeckoTerminal (no timestamp) can only LOWER the price, never confirm a jump; (3) otherwise skip the tick.
import onchain_price as OP
def chain_price(pos,pair):
    sol=OP.sol_usd_from_pair(pair) if pair else None
    sol=sol or pos.get("sol_usd")
    try: return OP.reserve_price(pos.get("pair"),pos["mint"],sol)
    except Exception as e: return {"status":"ERROR","detail":f"{type(e).__name__}: {e}"[:160]}
def sanity_check(pos,px,ref,pair):
    """-> (decision, price, source, detail). decision CONFIRMED | USE_OTHER | SKIP. Only called for ticks > JUMP_X*ref."""
    cp=chain_price(pos,pair)
    if cp.get("status")=="VERIFIED":
        c=cp["price_usd"]
        if px/CONFIRM_TOL<=c<=px*CONFIRM_TOL: return "CONFIRMED",px,"onchain",f"vault price {c:.8g} ({cp.get('quote')})"
        return "USE_OTHER",c,"onchain",f"vault price {c:.8g} ({cp.get('quote')}) disagrees with tick"
    dp=dexpaprika_prices([pos["mint"]]).get(pos["mint"])   # only returns prices stamped <= DP_MAX_AGE_S old
    if dp and px/CONFIRM_TOL<=dp[0]<=px*CONFIRM_TOL:
        return "CONFIRMED",px,"dexpaprika_fresh",f"vaults {cp.get('status')}; DexPaprika {dp[0]:.8g} stamped {dp[1]}"
    sp,src=(dp[0],"dexpaprika_fresh") if dp else second_price(pos["mint"])
    if sp and sp<=JUMP_X*ref: return "USE_OTHER",sp,src,f"vaults {cp.get('status')}; {src} {sp:.8g} (lower, used)"
    return "SKIP",None,src,f"vaults {cp.get('status')} ({cp.get('detail','')[:60]}); 2nd source {src or 'unavailable'} {sp} not proof of freshness"
# ---- -12% pre-lock stop SHADOW (reference install 2026-10-17, LOG ONLY: never changes a real fill, cash or decision). Until the profit lock
# turns on, a hypothetical full exit at the first tick <= fill x 0.88 (same exit cost + impact model). After the lock is on, or
# if the real position closes first, the shadow follows the real result. State in pos["shadow_m12"]; events in shadow_m12.ndjson.
SHADOW_STOP=0.88; SHADOW_LOG=os.path.join(HERE,"shadow_m12.ndjson"); SHADOW_SINCE="2026-10-17T03:55:00-04:00"
def shadow_m12(b,pos,px,now):
    ts=now.isoformat(timespec="seconds")
    s=pos.get("shadow_m12")
    if s is None:
        s=pos["shadow_m12"]={"state":"OPEN","start":ts,"late_start":pos.get("entry_time","")<SHADOW_SINCE}
    if s["state"]!="OPEN": return
    ev=None
    if px is not None and px<=pos["entry_price"]*SHADOW_STOP and not pos.get("lock_active"):
        imp=impact(pos,pos["qty"],px); pnl=pos["qty"]*px*(1-EXIT_COST)*(1-imp)-pos["qty"]*pos["entry_price"]
        s.update(state="STOPPED",exit_time=ts,exit_px=px,pnl_usd=round(pnl,4),pnl_pct=round(pnl/pos["size_usd"]*100,2),impact_pct=round(imp*100,3)); ev="SHADOW_STOP_-12"
    elif pos.get("lock_active"): s.update(state="FOLLOWS_REAL",since=ts,why="lock on"); ev="SHADOW_FOLLOWS_REAL"
    elif pos["qty_open"]<=1e-12: s.update(state="FOLLOWS_REAL",since=ts,why="real closed first"); ev="SHADOW_FOLLOWS_REAL"
    if ev:
        try:
            with open(SHADOW_LOG,"a") as f: f.write(json.dumps(dict(ts=ts,book=b.get("variant","main"),type=ev,id=pos["id"],symbol=pos["symbol"],price=px,**s))+"\n")
        except Exception: pass
def apply_rules(b,pos,px,now,pair=None,m1=None,liq_prev=None):
    """Real rules (_apply_rules) then the LOG-ONLY -12% shadow. Same signature/returns as before."""
    ex,dc=_apply_rules(b,pos,px,now,pair,m1,liq_prev)
    try: shadow_m12(b,pos,pos.get("last_price") if any(d.get("type")=="SANITY_REJECT" for d in dc) else px,now)
    except Exception: pass
    return ex,dc
def _apply_rules(b,pos,px,now,pair=None,m1=None,liq_prev=None):
    """Single source of exit rules (shared with adaptive_watcher.py). Mutates b/pos. Returns (exit strings, decisions)."""
    exits=[]; dec=[]; ts=now.isoformat(timespec="seconds"); e=pos["entry_price"]
    def note(kind,why,**kw): dec.append(dict(ts=ts,type=kind,symbol=pos["symbol"],id=pos["id"],price=px,reason=why,**kw))
    liq=((pair or {}).get("liquidity") or {}).get("usd")
    # RUG first: liquidity ~$0 -> sell everything, labelled RUG (fill priced against the ~$0 pool, so proceeds ~0)
    liq_max=max(pos.get("liq_max_seen") or 0,pos.get("entry_liq") or 0,pos.get("runner_liq_peak") or 0,pos.get("last_liq") or 0)
    if liq is not None and (liq<RUG_LIQ_USD or (liq_max>0 and liq<0.01*liq_max)) and liq_max>=RUG_LIQ_USD:
        pos["last_liq"]=max(liq,1e-9); bad=px
        px=min(px,pos.get("last_good_price") or pos.get("last_price") or px) if px>JUMP_X*(pos.get("last_good_price") or max(pos["peak_price"],e)) else px
        pos["last_price"]=px; exits.append(sell(b,pos,pos["qty_open"],px,"RUG",now)); pos["rug"]=True
        if bad!=px: note("SANITY_REJECT",f"RUG tick printed {bad:.8g}; exit priced at last good {px:.8g}",bad_price=bad)
        note("EXIT",f"RUG: liquidity ${liq:,.2f} (max seen ${liq_max:,.0f}); peak not updated from this tick"); return exits,dec
    # SANITY: a >10x jump vs the last accepted price can't set a peak until on-chain reserves (or a fresh-stamped source) confirm it
    ref=pos.get("last_good_price") or max(pos["peak_price"],e)
    if px>JUMP_X*ref:
        dcs,p2,src,why=sanity_check(pos,px,ref,pair)
        if dcs=="CONFIRMED": note("SANITY_CONFIRMED",f"{px/ref:.1f}x jump confirmed by {src}: {why}")
        elif dcs=="USE_OTHER":
            note("SANITY_REJECT",f"{px/ref:.0f}x jump not confirmed ({why}); using {src} price",bad_price=px)
            px=p2; pos["last_price"]=px
        else:
            note("SANITY_REJECT",f"{px/ref:.0f}x jump unconfirmed ({why}); tick skipped",bad_price=px)
            pos["last_price"]=pos.get("last_good_price") or pos["last_price"]; return exits,dec
    pos["last_good_price"]=px
    if pair and OP.sol_usd_from_pair(pair): pos["sol_usd"]=round(OP.sol_usd_from_pair(pair),4)
    pos["peak_price"]=max(pos["peak_price"],px)
    if liq: pos["last_liq"]=liq; pos["liq_max_seen"]=max(pos.get("liq_max_seen") or 0,liq)
    xp=exit_params(pos)
    if pos["peak_price"]>=e*xp["lock_start"] and not pos.get("lock_active"):
        pos["lock_active"]=True; pos["lock_since"]=ts; pos["runner_liq_peak"]=liq or 0
        note("LOCK_ON",f"peak {pos['peak_price']/e:.2f}x fill -> profit lock on ({xp['name']}: at +{(xp['lock_start']-1)*100:.0f}%), stop >= breakeven {e*BE_MULT:.8g}")
    if px<=pos["stop_price"] and not pos.get("lock_active"):
        exits.append(sell(b,pos,pos["qty_open"],px,"STOP_-30",now)); return exits,dec
    if pair is None:   # no flow data (hourly fallback): only price rules
        mom,why,met=(pos.get("last_momentum") or "NEUTRAL"),"no pair data",{}
    else: mom,why,met=momentum(pair,pos,m1,liq_prev)
    if liq: pos["runner_liq_peak"]=max(pos.get("runner_liq_peak") or 0,liq)
    if mom!=pos.get("last_momentum"): note("MOMENTUM",f"{pos.get('last_momentum')} -> {mom}: {why}",momentum=mom,metrics=met)
    pos["last_momentum"]=mom
    lock=pos.get("lock_active",False)
    past=now>=D.datetime.fromisoformat(pos["time_stop_at"])
    if past and not (lock and mom=="STRONG"):
        exits.append(sell(b,pos,pos["qty_open"],px,"TIME_STOP_24H",now)); note("EXIT",f"24h time stop (lock {lock}, momentum {mom}): {why}",momentum=mom,metrics=met); return exits,dec
    if past and not pos.get("time_extended"):
        pos["time_extended"]=True; note("TIME_EXTEND",f"past 24h, in profit lock and STRONG ({why}); held on {TRAIL_EXTENDED*100:.0f}% trail",momentum=mom,metrics=met)
    if lock:
        stop,t=runner_trail(pos,mom,past)
        if stop>pos.get("runner_stop",0)*1.0001:
            note("TRAIL_RATCHET",f"stop {pos.get('runner_stop',0):.8g} -> {stop:.8g} ({t*100:.0f}% off peak {pos['peak_price']:.8g}; floor breakeven{' + half of peak gain' if pos['peak_price']>=e*xp['keep_from'] else ''}), {mom}, exits {xp['name']}",momentum=mom,metrics=met)
            pos["runner_stop"]=stop
        if px<=pos["runner_stop"]:
            exits.append(sell(b,pos,pos["qty_open"],px,"LOCK_TRAIL",now)); note("EXIT",f"hit profit-lock stop {pos['runner_stop']:.8g} ({mom}: {why})",momentum=mom,metrics=met); return exits,dec
    if mom=="BREAKING" and (lock or (met.get("m5") or 0)<=PRELOCK_BREAK_M5):
        exits.append(sell(b,pos,pos["qty_open"],px,"BREAKING",now)); note("EXIT",f"BREAKING: {why}",momentum=mom,metrics=met); return exits,dec
    if mom=="FADING" and px>=e*FADE_MIN_MULT and pos.get("fade_sells",0)<len(FADE_SELL_FRAC):
        last=pos.get("last_fade_sell")
        if not last or (now-D.datetime.fromisoformat(last)).total_seconds()>=FADE_COOLDOWN_S:
            f=FADE_SELL_FRAC[pos.get("fade_sells",0)]
            exits.append(sell(b,pos,pos["qty_open"]*f,px,f"FADE_{int(f*100)}PCT",now))
            pos["fade_sells"]=pos.get("fade_sells",0)+1; pos["last_fade_sell"]=ts
            note("PARTIAL",f"FADING at {px/e:.2f}x -> sold {f*100:.0f}% of open: {why}",momentum=mom,metrics=met)
    return exits,dec
def record(b,dec,exits,now):
    """Append decisions/exits to paper_log.md (atomic) and events.jsonl. Caller holds the lock."""
    if not dec and not exits: return
    BD=os.path.dirname(os.path.abspath(BOOK)); LOG=os.path.join(BD,"paper_log.md"); EV=os.path.join(BD,"events.jsonl")   # next to the book (temp books in tests stay in temp)
    lines=[f"- {now:%Y-%m-%d %H:%M:%S} ET [{d['type']}] {d['symbol']} @ {d['price']:.8g}: {d['reason']}" for d in dec]
    lines+=[f"- {now:%Y-%m-%d %H:%M:%S} ET [SELL] {e}" for e in exits]
    t=(open(LOG).read() if os.path.exists(LOG) else "# Paper log (PAPER ONLY)\n").rstrip("\n")+"\n"+"\n".join(lines)+"\n"; tmp=LOG+".tmp"; open(tmp,"w").write(t); os.replace(tmp,LOG)
    with open(EV,"a") as f:
        for d in dec: f.write(json.dumps(d)+"\n")
def update_equity(b,now):
    mv=sum(p["qty_open"]*p["last_price"]*(1-EXIT_COST) for p in b["positions"] if p["qty_open"]>1e-12)
    eq=b["cash"]+mv
    if b.get("day_start_equity") is None: b["day_start_equity"]=round(eq,4)
    b["equity"]=round(eq,4); b["last_run"]=now.isoformat(timespec="seconds")
    b["day_pnl_pct"]=round((eq/b["day_start_equity"]-1)*100,2)
    # 2026-10-17 (owner): daily halt -12% (was -20%). day_pnl_pct is EQUITY-based = cash + open positions marked at last price net of
    # exit cost, so unrealized losses count. Backup: paper_monitor.py.bak-2026-10-17-halt12
    DAILY_HALT_PCT=-12
    b["daily_halt_new_entries"]=b["day_pnl_pct"]<=DAILY_HALT_PCT
    b["loss_ladder"]=loss_ladder(b,now)
    return eq
def loss_ladder(b,now):
    """Locked SKILL loss ladder (realized LOSING trades summed, gross of winners = conservative; % of starting balance). Gates NEW entries; never forces sells.
    5%/1h: pause 2h. 8%/day: 3h cooldown then half size. 12%/day: done for day. 15%/week: 24h cooldown then half size. 20%/week: done for week."""
    bal=b["starting_balance"]; ct=b.get("closed_trades",[])
    def lost(h): 
        r=sum(min(0,c["pnl_usd"]) for c in ct if (now-D.datetime.fromisoformat(c["exit_time"])).total_seconds()<=h*3600)
        return -r/bal*100
    day=-sum(min(0,c["pnl_usd"]) for c in ct if c["exit_time"][:10]==now.date().isoformat())/bal*100
    h1,wk=lost(1),lost(24*7)
    st,allow,mult="OK",True,1.0
    if wk>=20: st,allow="DONE_FOR_WEEK",False
    elif day>=12: st,allow="DONE_FOR_DAY",False
    elif wk>=15: st,allow,mult="WEEK_COOLDOWN_24H_THEN_HALF",False,0.5
    elif day>=8: st,allow,mult="DAY_COOLDOWN_3H_THEN_HALF",False,0.5
    elif h1>=5: st,allow="PAUSE_1_2H",False
    return {"state":st,"new_entries_allowed":allow and not b.get("daily_halt_new_entries"),"size_mult":mult,
            "realized_loss_pct":{"1h":round(h1,2),"day":round(day,2),"week":round(wk,2)}}
LOCK=os.path.join(HERE,"paper_book.lock")
def book_lock():
    import fcntl; f=open(LOCK,"a"); fcntl.flock(f,fcntl.LOCK_EX); return f
def main():
    _lk=book_lock()
    b=json.load(open(BOOK)); now=D.datetime.now(ET); exits=[]; lines=[]; decs=[]
    if b.get("day")!=now.date().isoformat():
        b["day"]=now.date().isoformat(); b["day_start_equity"]=None
    for pos in b["positions"]:
        if pos["qty_open"]<=1e-12: continue
        px,mc,pr=price(pos["mint"],pos["pair"])
        if px is None: lines.append(f"  {pos['symbol']:6} price UNKNOWN (fetch failed) - no action"); continue
        pos["last_price"]=px; pos["last_mcap"]=mc if mc is not None else pos.get("last_mcap"); pos["last_checked"]=now.isoformat(timespec="seconds")
        if pr is None: lines.append(f"  {pos['symbol']:6} DexScreener failed -> DexPaprika price-only fallback")
        n0=len(b["closed_trades"]); ex,dc=apply_rules(b,pos,px,now,pr); exits+=ex; decs+=dc
        decs+=[{"ts":now.isoformat(timespec="seconds"),"type":c["event"],**c} for c in b["closed_trades"][n0:]]
        if pos["qty_open"]>1e-12:
            lines.append(f"  {pos['symbol']:6} {(px/pos['mkt_price_at_entry']-1)*100:+7.1f}% mkt (net of costs {(px*(1-EXIT_COST)/pos['entry_price']-1)*100:+.1f}%)  px {px:.8g}  mc {mc}")
    eq=update_equity(b,now)
    tmp=BOOK+".tmp"; json.dump(b,open(tmp,"w"),indent=1); os.replace(tmp,BOOK); record(b,decs,exits,now); _lk.close()
    print(f"PAPER {now:%Y-%m-%d %H:%M} ET | cash ${b['cash']:.2f} | equity ${eq:.2f} ({(eq/b['starting_balance']-1)*100:+.1f}% vs start, day {b['day_pnl_pct']:+.1f}%)"+(" | DAILY -12% HALT (incl. unrealized)" if b["daily_halt_new_entries"] else ""))
    print("Open:"); print("\n".join(lines) or "  none")
    print("Exits this run:"); print("\n".join("  "+e for e in exits) or "  none")
    if "--tg" in sys.argv:
        sys.path.insert(0,HERE); import tg_mentions
        r=tg_mentions.check([p["mint"] for p in b["positions"] if p["qty_open"]>1e-12])
        sym={p["mint"]:p["symbol"] for p in b["positions"]}
        print("Telegram:"); [print(f"  {sym[m]:6} {v['n_channels']} ch {v['channels']} first={v['first']}") for m,v in r.items()]
if __name__=="__main__": main()
