#!/usr/bin/env python3
"""gem_score.py - weighted 0-100 "gem score" for Solana memecoin candidates. PAPER/READ-ONLY: public GETs only
(DexScreener, Rugcheck, Jupiter lite quote, GeckoTerminal). Never trades, signs, posts or touches wallets.

Replaces the caller-watch hard cutoffs ($25K liquidity floor, fresh<1h, 'vertical', v/l>15, cheap screen) with weighted
factors. Only TRUE hard vetoes remain (see VETOES). Channel text is untrusted data: only regex-extracted numbers are used.

Core API (pure, unit-tested):  score(cand, cfg=None) -> {"score","vetoes","factors","penalties","why","label",...}
Candidate dict fields (all optional except contract): see normalize_pair()/build_candidates().
Live helpers: fetch_pairs(), rugcheck_digest(), sell_route(), enrich(cand).   CLI: python3 gem_score.py <mint> [...]
Design goal: weigh all factors together instead of stacking hard liquidity caps.
"""
import json,math,os,re,time,urllib.request,urllib.error,datetime as D
ROOT=os.environ.get("UMBRELLA_HOME") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root (holds desk/ and tools/)
HERE=os.path.dirname(os.path.abspath(__file__)); CFG_PATH=os.path.join(HERE,"weights.json")
ET=D.timezone(D.timedelta(hours=-4)); UA={"User-Agent":"desk-gem-score/1.0 (read-only)","Accept":"application/json"}
WALLET_CFG=ROOT+"/tools/wallet_watch/config.json"
VETO_MIN_LIQ=5000; VETO_M5_DUMP=-50; VETO_DUMPED_FROM_PEAK=0.80
def load_cfg(path=CFG_PATH):
    c=json.load(open(path))
    try:   # the owner's tracked callers, live from wallet_watch config (fallback: weights.json list)
        f=json.load(open(WALLET_CFG)).get("caller_feeds") or {}
        live=[v.get("tg") for v in f.values() if isinstance(v,dict) and v.get("tg")]
        if live: c["owner_caller_channels"]=sorted(set(live))
    except Exception: pass
    return c
def clamp(x,a=0.0,b=1.0): return max(a,min(b,x))
def interp(x,pts):
    """piecewise-linear through [(x,y),...] sorted by x; flat outside."""
    if x<=pts[0][0]: return pts[0][1]
    for (x0,y0),(x1,y1) in zip(pts,pts[1:]):
        if x<=x1: return y0+(y1-y0)*(x-x0)/(x1-x0) if x1>x0 else y1
    return pts[-1][1]
# ---------------- factor sub-scores: each returns (value 0..1, note) ; None input -> neutral 0.5 "unknown" ------------
def f_sources(n):
    return {0:0.0,1:0.15,2:0.5,3:0.85}.get(n,1.0) if n<4 else 1.0, f"{n} independent source(s)"
def f_owner(names): return (1.0,"owner caller: "+",".join(names)) if names else (0.0,"no owner caller")
def f_smart(ov):
    if not ov: return 0.0,"no watched-wallet overlap"
    strong=any(str(o.get("grade","")).upper() in ("STRONG","CONFIRMED") for o in ov); n=len({o.get("wallet") for o in ov})
    return (1.0 if (n>=2 or strong) else 0.7), f"{n} watched wallet(s)"+(" (strong)" if strong else "")
def f_liq(liq,est=False):
    if liq is None: return 0.5,"liquidity unknown"
    v=interp(math.log10(max(liq,1)),[(math.log10(5000),0.0),(4.0,0.3),(math.log10(20000),0.6),(math.log10(40000),0.85),(math.log10(80000),1.0)])
    return v,f"liq ${liq/1e3:.1f}K"+(" (est. bonding curve)" if est else "")
def f_liq_mcap(liq,mc):
    if not liq or not mc: return 0.5,"liq/mcap unknown"
    r=liq/mc; v=interp(r,[(0.03,0.0),(0.06,0.4),(0.10,0.75),(0.12,1.0),(0.45,1.0),(0.8,0.6)])
    return v,f"liq/mcap {r*100:.0f}%"
def f_vol_liq(vh1,liq):
    if vh1 is None or not liq: return 0.5,"vol/liq unknown"
    r=vh1/liq; v=interp(r,[(0.3,0.1),(1,0.4),(3,0.8),(4,1.0),(15,1.0),(30,0.7),(60,0.4),(100,0.2)])
    return v,f"h1 vol/liq {r:.1f}"
def f_flow(b5,s5,bh1=None,sh1=None):
    if b5 is None or s5 is None or (b5+s5)==0: return 0.5,"buy/sell flow unknown"
    r=b5/max(s5,1); v=interp(r,[(0.7,0.0),(1.0,0.4),(1.3,0.8),(1.6,1.0)])
    note=f"m5 buys/sells {b5}/{s5}"
    if bh1:   # buyer-count trend: m5 buys vs the h1 per-5-min average (DexScreener has txn counts, not unique buyers)
        tr=b5/(bh1/12); v=0.7*v+0.3*interp(tr,[(0.5,0.0),(1.0,0.5),(1.5,1.0)]); note+=f", buy pace {tr:.1f}x h1 avg"
    return v,note
def f_momentum(m5,h1=None):
    if m5 is None: return 0.5,"m5 unknown"
    v=interp(m5,[(-30,0.0),(-10,0.2),(0,0.4),(5,0.6),(8,1.0),(60,1.0),(150,0.7),(400,0.4)])   # extreme spikes only partly penalised
    note=f"m5 {m5:+.0f}%"
    if h1 is not None:
        note+=f", h1 {h1:+.0f}%"
        if h1<-30: v*=0.6
    return v,note
def f_age(mins):
    if mins is None: return 0.5,"age unknown"
    v=interp(mins,[(0,0.4),(3,0.4),(10,0.8),(15,1.0),(60,1.0),(360,0.8),(1440,0.5),(2880,0.3)])
    return v,(f"age {mins:.0f}m" if mins<120 else f"age {mins/60:.1f}h")
def f_migration(dex_id):
    if not dex_id: return 0.5,"venue unknown"
    if dex_id in ("pumpfun","moonshot","launchlab","bonk","letsbonk","boop"): return 0.5,f"bonding curve ({dex_id})"
    return 1.0,f"migrated ({dex_id})"
def f_safety(rc,bundle_pct=None):
    """rc = rugcheck_digest() or None. Composite of LP lock, top-10 (ex-AMM), Rugcheck score (ex 'Low Liquidity'), bundle %, dev holding."""
    parts=[]; notes=[]
    rc=rc or {}
    lp=rc.get("lp_locked_pct")
    if lp is not None: parts.append(interp(lp,[(50,0.0),(90,0.8),(99,1.0)])); notes.append(f"LP {lp:.0f}% locked")
    t10=rc.get("top10_pct")
    if t10 is not None: parts.append(interp(t10,[(15,1.0),(25,0.75),(35,0.4),(50,0.1)])); notes.append(f"top10 {t10:.0f}%")
    s=rc.get("rc_score_adj")
    if s is not None: parts.append(interp(s,[(10,1.0),(30,0.6),(60,0.3),(100,0.0)])); notes.append(f"rugcheck {s}")
    if bundle_pct is not None: parts.append(interp(bundle_pct,[(15,1.0),(30,0.6),(50,0.3),(70,0.0)])); notes.append(f"bundle {bundle_pct:.0f}%")
    if rc.get("dev_holds") is not None: parts.append(1.0 if rc["dev_holds"] else 0.6); notes.append("dev holds" if rc["dev_holds"] else "dev sold/0")
    if not parts: return 0.5,"safety data unknown"
    return sum(parts)/len(parts),", ".join(notes)
# ------------------------------------------------------------------------------------------------------------------
def independent_sources(sources,cfg,now_ts=None):
    """sources: [{channel, post_ts, kind}] call posts. Brag/results posts never count. Channels share a source only if cfg source_groups says so (empty by default)."""
    win=cfg.get("source_window_h",3)*3600; grp=cfg.get("source_groups",{})
    g={}
    for s in sources or []:
        if s.get("kind") not in (None,"call"): continue
        if now_ts and s.get("post_ts") and (now_ts-s["post_ts"]>win or s["post_ts"]>now_ts+60): continue
        ch=s.get("channel") or "?"; g.setdefault(grp.get(ch,ch),set()).add(ch)
    return g
def score(c,cfg=None):
    cfg=cfg or load_cfg(); W=cfg["weights"]; P=cfg["penalties"]; T=cfg["thresholds"]
    now_ts=c.get("now_ts") or time.time()
    groups=independent_sources(c.get("sources"),cfg,now_ts); n_ind=len(groups)
    chans={ch for v in groups.values() for ch in v}
    own=sorted(chans & set(cfg.get("owner_caller_channels",[]))) + list(c.get("owner_x_callers") or [])
    liq=c.get("liq"); est=False
    if (not liq) and c.get("liq_est"): liq=c["liq_est"]; est=True
    fac={}
    def add(name,vn): fac[name]={"value":round(vn[0],3),"weight":W.get(name,0),"points":round(vn[0]*W.get(name,0),2),"note":vn[1]}
    add("sources",f_sources(n_ind)); add("owner_callers",f_owner(own)); add("smart_money",f_smart(c.get("wallet_overlap")))
    add("liquidity",f_liq(liq,est)); add("liq_mcap",f_liq_mcap(liq,c.get("mcap"))); add("vol_liq",f_vol_liq(c.get("vol_h1"),liq))
    add("flow",f_flow(c.get("buys_m5"),c.get("sells_m5"),c.get("buys_h1"),c.get("sells_h1"))); add("momentum",f_momentum(c.get("m5"),c.get("h1")))
    add("age",f_age(c.get("age_min"))); add("migration",f_migration(c.get("dex_id"))); add("safety",f_safety(c.get("rugcheck"),c.get("bundle_pct")))
    pen=[]
    promo=set(cfg.get("promo_channels",[]))
    if n_ind<=1 and chans and chans<=promo and not c.get("wallet_overlap"): pen.append(("promo_only",P["promo_only"],"only promo-bot channel(s)"))
    xp=[a for a in c.get("x_promo_accounts") or [] if a in set(cfg.get("x_paid_promo_accounts",[]))]
    if xp: pen.append(("x_paid_promo",min(2,len(xp))*P["x_paid_promo_each"],"paid-promo X shills: "+",".join(xp[:3])))
    if c.get("ring")=="FLAG": pen.append(("ring_flag",P["ring_flag"],"wallet-ring flag (soft)"))
    fm=c.get("first_call_mcap"); mc=c.get("mcap")
    if fm and mc and fm>0:
        x=mc/fm
        if x>=10: pen.append(("chase",P["chase_10x"],f"chasing: {x:.1f}x since first call"))
        elif x>=5: pen.append(("chase",P["chase_5x"],f"chasing: {x:.1f}x since first call"))
    if c.get("copycat_of"): pen.append(("copycat",P.get("copycat",10),f"copycat ticker (earlier contract {str(c['copycat_of'])[:6]}..)"))
    pk=c.get("peak_price_seen"); px=c.get("price")
    if pk and px and px<=0.5*pk and px>(1-VETO_DUMPED_FROM_PEAK)*pk: pen.append(("off_peak_50",P["off_peak_50"],f"{(1-px/pk)*100:.0f}% off seen peak"))
    # ---- TRUE hard vetoes only ----
    vet=[]
    rc=c.get("rugcheck") or {}
    if rc.get("mint_authority"): vet.append("live mint authority")
    if rc.get("freeze_authority"): vet.append("live freeze authority")
    if c.get("sell_route")=="NO_ROUTE": vet.append("honeypot / no sell route")
    if rc.get("rugged"): vet.append("Rugcheck: rugged")
    if c.get("ring")=="REJECT": vet.append("Rug Shield REJECT (ring-traced deployer proceeds)")
    if liq is not None and liq<VETO_MIN_LIQ and not (est and liq>=VETO_MIN_LIQ): vet.append(f"liquidity ${liq:,.0f} < ${VETO_MIN_LIQ/1e3:.0f}K")
    if c.get("m5") is not None and c["m5"]<=VETO_M5_DUMP: vet.append(f"dump in progress (m5 {c['m5']:.0f}%)")
    if pk and px and px<=(1-VETO_DUMPED_FROM_PEAK)*pk: vet.append(f"already dumped {(1-px/pk)*100:.0f}% from seen peak")
    if c.get("h6") is not None and c["h6"]<=-80: vet.append(f"already dumped (h6 {c['h6']:.0f}%)")
    raw=sum(f["points"] for f in fac.values()); s=clamp(raw-sum(p[1] for p in pen),0,100)
    if vet: label="VETO"
    elif s>=T["paper_entry"]: label="PAPER_ENTRY"
    elif s>=T["ping"]: label="PING"
    elif s>=T["watch"]: label="WATCH"
    else: label="PASS"
    return {"contract":c.get("contract"),"ticker":c.get("ticker"),"score":round(s,1),"raw":round(raw,1),"label":label,"vetoes":vet,
            "n_independent":n_ind,"source_groups":{k:sorted(v) for k,v in groups.items()},"factors":fac,
            "penalties":[{"id":p[0],"points":p[1],"why":p[2]} for p in pen],"why":why_line(s,fac,pen,vet,label)}
def why_line(s,fac,pen,vet,label):
    if vet: return f"VETO: {vet[0]}"
    top=sorted(fac.items(),key=lambda kv:-kv[1]["points"])[:3]
    weak=[k for k,f in fac.items() if f["weight"]>=7 and f["value"]<0.35 and "unknown" not in f["note"]]
    s1="; ".join(f["note"] for _,f in top)
    s2=(" | weak: "+", ".join(fac[k]["note"] for k in weak[:2])) if weak else ""
    s3=(" | -"+", ".join(p[2] for p in pen[:2])) if pen else ""
    return f"{s:.0f}/100 {label}: {s1}{s2}{s3}"
# ---------------- data normalisation ----------------
def sol_usd_from_pair(p):
    try:
        if (p.get("quoteToken") or {}).get("symbol") in ("SOL","WSOL") and p.get("priceNative"): return float(p["priceUsd"])/float(p["priceNative"])
    except Exception: pass
    return None
def bonding_liq_est(mcap_usd,sol_usd):
    """pump.fun curve (1B supply, 30 virtual SOL x 1.073B virtual tokens): vSOL = sqrt(32.19 * mcap_in_SOL).
    Two-sided equivalent liquidity = 2 * vSOL * SOL price. Used only for slippage/score when DexScreener shows liq 0 on the curve."""
    if not mcap_usd or not sol_usd: return None
    return 2*math.sqrt(32.19*mcap_usd/sol_usd)*sol_usd
def normalize_pair(p,sol_usd=None,now_ts=None):
    """DexScreener pair -> flat candidate fields."""
    now_ts=now_ts or time.time(); tx=p.get("txns") or {}; pc=p.get("priceChange") or {}; v=p.get("volume") or {}
    liq=(p.get("liquidity") or {}).get("usd"); mc=p.get("marketCap") or p.get("fdv")
    d=dict(price=float(p["priceUsd"]) if p.get("priceUsd") else None,mcap=mc,liq=liq,vol_h1=v.get("h1"),vol_m5=v.get("m5"),
           m5=pc.get("m5"),h1=pc.get("h1"),h6=pc.get("h6"),buys_m5=(tx.get("m5") or {}).get("buys"),sells_m5=(tx.get("m5") or {}).get("sells"),
           buys_h1=(tx.get("h1") or {}).get("buys"),sells_h1=(tx.get("h1") or {}).get("sells"),dex_id=p.get("dexId"),pair=p.get("pairAddress"),
           age_min=(now_ts-p["pairCreatedAt"]/1000)/60 if p.get("pairCreatedAt") else None,ticker=(p.get("baseToken") or {}).get("symbol"))
    if not liq and d["dex_id"]=="pumpfun": d["liq_est"]=bonding_liq_est(mc,sol_usd or sol_usd_from_pair(p) or 180.0)
    return d
def normalize_snapshot(dx,ts,sol_usd=180.0):
    """tg_alerts 'dex' snapshot -> candidate fields (no txn counts / h1 change in the snapshot)."""
    d=dict(price=dx.get("price_usd"),mcap=dx.get("mcap_usd"),liq=dx.get("liq_usd") or None,vol_h1=dx.get("vol_h1"),m5=dx.get("chg_m5"),dex_id=dx.get("dex_id"))
    if dx.get("pair_created_et"):
        try: d["age_min"]=(ts-D.datetime.fromisoformat(dx["pair_created_et"]).timestamp())/60
        except Exception: pass
    if not d["liq"] and d.get("mcap") and (dx.get("dex_id") in (None,"pumpfun")): d["liq_est"]=bonding_liq_est(d["mcap"],sol_usd)
    return d
BUNDLE_RE=re.compile(r"Bundl\w*[^0-9\n]{0,12}(\d{1,3}(?:\.\d+)?)\s*%",re.I)
def bundle_from_text(t):
    m=BUNDLE_RE.search(t or ""); return float(m.group(1)) if m else None

# ---------------- candidate tracker (shared by backtest.py and gem_paper.py) ----------------
def _ts(s): return D.datetime.fromisoformat(s).timestamp()
def update_from_alert(state,a):
    """Fold one tg_alerts.jsonl record into state {"coins":{ca:{...}}, "tick_first":{TICKER:ca}}. Returns ca or None.
    Channel text is data: only regex-extracted numbers (bundle %) are used."""
    ca=a.get("contract")
    if a.get("chain")!="solana" or not ca: return None
    coins=state.setdefault("coins",{}); tf=state.setdefault("tick_first",{})
    t=_ts(a.get("detect_time_et") or a["ts"])
    s=coins.setdefault(ca,{"ticker":a.get("ticker"),"sources":{},"wallet":[],"first_mc":None,"peak":0.0,"bundle":None,"first_seen":t,"last_alert":t})
    s["last_alert"]=t
    if a.get("kind")=="TG_CALL":
        s["sources"][f"{a.get('channel')}|{a.get('post_id')}"]={"channel":a.get("channel"),"post_ts":a.get("post_ts"),"kind":a.get("post_kind")}
        for x in a.get("cross_channels") or []:
            try: s["sources"].setdefault(f"{x['channel']}|{x.get('link')}",{"channel":x["channel"],"post_ts":_ts(x["post_time_et"]),"kind":"call"})
            except Exception: pass
        b=bundle_from_text(a.get("text_snippet"))
        if b is not None: s["bundle"]=b
    for w in a.get("wallet_overlap") or []:
        w=w if isinstance(w,dict) else {"wallet":str(w)}
        if w not in s["wallet"]: s["wallet"].append(w)
    if a.get("kind")=="WALLET_OVERLAP_LATE":
        w={"wallet":"late:"+ca,"grade":"STRONG" if "FOMO" in " ".join(a.get("reasons") or []) else ""}
        if w not in s["wallet"]: s["wallet"].append(w)
    tk=(a.get("ticker") or "").upper()
    if tk: tf.setdefault(tk,ca)
    dx=a.get("dex") or {}
    if dx.get("price_usd"):
        if s["first_mc"] is None and dx.get("mcap_usd"): s["first_mc"]=dx["mcap_usd"]
        s["peak"]=max(s["peak"],float(dx["price_usd"]))
    return ca
def add_wallet(state,ca,w,ticker=None,t=None):
    coins=state.setdefault("coins",{}); t=t or time.time()
    s=coins.setdefault(ca,{"ticker":ticker,"sources":{},"wallet":[],"first_mc":None,"peak":0.0,"bundle":None,"first_seen":t,"last_alert":t})
    if w not in s["wallet"]: s["wallet"].append(w)
    s["last_alert"]=max(s.get("last_alert") or 0,t)
def candidate_from_state(state,ca,now_ts,market):
    """market = normalize_pair()/normalize_snapshot() dict. Returns a score() input."""
    s=state["coins"][ca]; market=dict(market); mt=market.pop("ticker",None); tk=(s.get("ticker") or mt or "").upper(); tf=state.get("tick_first",{})
    return dict(contract=ca,ticker=s.get("ticker") or mt,now_ts=now_ts,sources=list(s["sources"].values()),
                wallet_overlap=s["wallet"],first_call_mcap=s.get("first_mc"),peak_price_seen=max(s.get("peak") or 0,market.get("price") or 0) or None,
                copycat_of=(tf.get(tk) if tk and tf.get(tk) not in (None,ca) else None),bundle_pct=s.get("bundle"),**market)
# ---------------- live fetchers (read-only, cached) ----------------
CACHE=os.path.join(HERE,"data","cache"); os.makedirs(CACHE,exist_ok=True)
def _get(url,ttl,timeout=20):
    fn=os.path.join(CACHE,re.sub(r"[^A-Za-z0-9]","_",url)[-180:]+".json")
    try:
        if time.time()-os.path.getmtime(fn)<ttl: return json.load(open(fn))
    except Exception: pass
    d=json.load(urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=timeout))
    try: tmp=fn+".tmp"; json.dump(d,open(tmp,"w")); os.replace(tmp,fn)
    except Exception: pass
    return d
def fetch_pairs(mints,ttl=20):
    """{mint: deepest solana pair} via DexScreener tokens/v1 (30 per call)."""
    out={}
    for i in range(0,len(mints),30):
        try: arr=_get("https://api.dexscreener.com/tokens/v1/solana/"+",".join(mints[i:i+30]),ttl)
        except Exception: continue
        for p in arr if isinstance(arr,list) else []:
            if p.get("chainId")!="solana" or not p.get("priceUsd"): continue
            ca=(p.get("baseToken") or {}).get("address"); l=(p.get("liquidity") or {}).get("usd") or 0
            if ca in mints and (ca not in out or l>((out[ca].get("liquidity") or {}).get("usd") or 0)): out[ca]=p
    return out
def rugcheck_digest(mint,ttl=600,raw=None):
    """Rugcheck full report -> digest. rc_score_adj = normalised score minus 'Low Liquidity' risk weight (that risk is a
    liquidity reading we already score; it also appears AFTER a rug, so keeping it would leak the outcome in backtests)."""
    try: r=raw if raw is not None else _get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report",ttl,25)
    except Exception as e: return {"error":str(e)[:100]}
    ka=r.get("knownAccounts") or {}
    th=[h for h in r.get("topHolders") or [] if (ka.get(h.get("owner")) or {}).get("type")!="AMM" and (ka.get(h.get("address")) or {}).get("type")!="AMM"]
    lps=[(m.get("lp") or {}).get("lpLockedPct") for m in r.get("markets") or [] if (m.get("lp") or {}).get("lpLockedPct") is not None]
    risks=r.get("risks") or []; tot=sum(x.get("score",0) for x in risks); ll=sum(x.get("score",0) for x in risks if x.get("name")=="Low Liquidity")
    sn=r.get("score_normalised")
    adj=None if sn is None else (round(sn*(1-ll/tot)) if tot else sn)
    return {"mint_authority":r.get("mintAuthority"),"freeze_authority":r.get("freezeAuthority"),"rugged":bool(r.get("rugged")),
            "lp_locked_pct":max(lps) if lps else None,"top10_pct":round(sum(h.get("pct",0) for h in th[:10]),1) if th else None,
            "rc_score":sn,"rc_score_adj":adj,"risks":[x.get("name") for x in risks],"dev_holds":(r.get("creatorBalance") or 0)>0 if r.get("creator") else None,
            "insider_networks":len(r.get("insiderNetworks") or []),"holders":r.get("totalHolders"),"decimals":(r.get("token") or {}).get("decimals")}
def sell_route(mint,decimals=6,ui_amount=100000,ttl=120):
    """Jupiter lite quote token->SOL. OK / NO_ROUTE (honeypot-ish veto) / UNKNOWN (network/429; never a veto, never OK)."""
    amt=int(ui_amount*10**(decimals if decimals is not None else 6))
    url=f"https://lite-api.jup.ag/swap/v1/quote?inputMint={mint}&outputMint=So11111111111111111111111111111111111111112&amount={amt}&slippageBps=1000"
    try:
        q=_get(url,ttl,15)
        if q.get("outAmount") and int(q["outAmount"])>0: return "OK",float(q.get("priceImpactPct") or 0)
        return ("NO_ROUTE" if "route" in json.dumps(q).lower() else "UNKNOWN"),None
    except urllib.error.HTTPError as e:
        try: body=e.read().decode()[:300]
        except Exception: body=""
        return ("NO_ROUTE" if e.code in (400,404) and ("route" in body.lower() or "COULD_NOT_FIND" in body) else "UNKNOWN"),None
    except Exception: return "UNKNOWN",None
def ring_status(mint,creator=None):
    """REJECT if Rug Shield REJECT list names the mint/creator; FLAG if wallet_watch ring_flags.ndjson names the mint."""
    st="NONE"
    try:
        rej=json.load(open(os.path.join(HERE,"rug_shield_rejects.json")))
        if mint in rej.get("mints",[]) or (creator and creator in rej.get("deployers",[])): return "REJECT"
    except Exception: pass
    try:
        for l in open(ROOT+"/tools/wallet_watch/ring_flags.ndjson"):
            if mint in l:
                st="FLAG"
                if '"REJECT"' in l: return "REJECT"
    except Exception: pass
    return st
def main(argv):
    import sys
    cfg=load_cfg(); ps=fetch_pairs(argv)
    for m in argv:
        p=ps.get(m)
        if not p: print(m,"no DexScreener pair"); continue
        c=dict(contract=m,**normalize_pair(p)); c["rugcheck"]=rugcheck_digest(m); c["sell_route"]=sell_route(m,c["rugcheck"].get("decimals"))[0]; c["ring"]=ring_status(m)
        r=score(c,cfg); print(json.dumps({k:r[k] for k in ("ticker","score","label","vetoes","why")}))
if __name__=="__main__":
    import sys; main(sys.argv[1:])
