#!/usr/bin/env python3
"""gem_scorecard.py - daily scorecard for the gem-score PAPER trades + score calibration feedback. Read-only (local files;
--shadow adds GeckoTerminal candle GETs). Feeds the 9:17 AM ET morning desk report.
Writes desk/reports/gem_scorecard_<ET date>.md (+ .json) and gem_scorecard_latest.md. See SCORECARD_README.md.
Usage: python3 gem_scorecard.py [--hours 24] [--shadow] [--quiet]"""
import json,os,sys,time,datetime as D
ROOT=os.environ.get("UMBRELLA_HOME") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root (holds desk/ and tools/)
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE)
import gem_score as G
import contrarian as CX   # paper250 2026-10-18: separate contrarian_1p5x section + its own report files
ET=G.ET; BOOK=ROOT+"/desk/paper/paper_book.json"; STATE=os.path.join(HERE,"gem_state.json"); REPORTS=ROOT+"/desk/reports"
EXIT_COST=0.015
def jl(p,d):
    try: return json.load(open(p))
    except Exception: return d
def trade_rows(b,since_ts=None):
    rows=[]
    for p in b.get("positions",[]):
        if not str(p.get("source","")).startswith("gem_score"): continue
        et=D.datetime.fromisoformat(p["entry_time"]).timestamp()
        ct=[x for x in b.get("closed_trades",[]) if x["id"]==p["id"]]
        realized=sum(x["pnl_usd"] for x in ct)
        unreal=p["qty_open"]*(p["last_price"]*(1-EXIT_COST)-p["entry_price"]) if p["qty_open"]>1e-12 else 0.0
        last_exit=max([D.datetime.fromisoformat(x["exit_time"]).timestamp() for x in ct],default=None)
        if since_ts and et<since_ts and (p["qty_open"]>1e-12 or (last_exit or 0)<since_ts) and p["qty_open"]<=1e-12: continue
        rows.append(dict(id=p["id"],symbol=p["symbol"],mint=p["mint"],score=(p.get("gem") or {}).get("score"),size=p["size_usd"],entry_time=p["entry_time"],
                         open=p["qty_open"]>1e-12,realized=round(realized,4),unrealized=round(unreal,4),pnl=round(realized+unreal,4),
                         pnl_pct=round((realized+unreal)/p["size_usd"]*100,1),peak_x=round(p["peak_price"]/p["entry_price"],2),
                         exits=[x["reason"] for x in ct],exit_rules=p.get("exit_experiment") or "v3.2a",why=(p.get("gem") or {}).get("why")))
    return rows
def bucket(s):
    return "80+" if s>=80 else ("70-79" if s>=70 else ("62-69" if s>=62 else ("55-61" if s>=55 else "45-54")))
def calib_rows(st,since_ts):
    out=[]
    for ca,s in (st.get("coins") or {}).items():
        if not s.get("first_watch_ts") or s["first_watch_ts"]<since_ts or not s.get("first_watch_price"): continue
        p0=s["first_watch_price"]; pk=s.get("peak_live") or p0; last=s.get("last_price") or p0
        out.append(dict(ticker=s.get("ticker"),mint=ca,max_score=s.get("max_score") or 0,first_score=s.get("first_watch_score"),peak_x=round(pk/p0,2),now_x=round(last/p0,2)))
    return out
def shadow_wide(r):
    """RESEARCH ONLY: what the 'wide' exit variant (lock at +50%) would have done on GT 1-min candles for this trade."""
    try:
        import backtest as B, urllib.request
        os.environ["EXIT_VARIANT"]="wide"; B.VARIANT="wide"
        b=jl(BOOK,{}); p=next(x for x in b["positions"] if x["id"]==r["id"])
        g=G._get(f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{p['pair']}/ohlcv/minute?aggregate=1&limit=1000&currency=usd",300)
        c=sorted(g["data"]["attributes"]["ohlcv_list"]); t0=D.datetime.fromisoformat(p["entry_time"]).timestamp()
        s=B.sim_exit(c,t0,p["mkt_price_at_entry"],p.get("entry_liq")); return None if not s else round(s[0],1)
    except Exception: return None
def main():
    hours=float(sys.argv[sys.argv.index("--hours")+1]) if "--hours" in sys.argv else 24.0
    now=D.datetime.now(ET); since=now.timestamp()-hours*3600; b=jl(BOOK,{}); st=jl(STATE,{}); cfg=G.load_cfg()
    allr=trade_rows(b); win=[r for r in allr if D.datetime.fromisoformat(r["entry_time"]).timestamp()>=since or r["open"]]
    closed=[r for r in allr if not r["open"]]; closed_w=[r for r in win if not r["open"]]
    def stats(rs):
        if not rs: return {"n":0}
        w=[r for r in rs if r["pnl"]>0]
        return {"n":len(rs),"winners":len(w),"hit_rate_pct":round(len(w)/len(rs)*100,1),"pnl_usd":round(sum(r["pnl"] for r in rs),2),
                "staked_usd":round(sum(r["size"] for r in rs),2),"return_on_staked_pct":round(sum(r["pnl"] for r in rs)/max(1e-9,sum(r["size"] for r in rs))*100,1),
                "best":max(rs,key=lambda r:r["pnl_pct"]),"worst":min(rs,key=lambda r:r["pnl_pct"])}
    by_b={}
    for r in allr: by_b.setdefault(bucket(r["score"] or 0),[]).append(r)
    by_x={}
    for r in allr: by_x.setdefault(r["exit_rules"],[]).append(r)
    cal=calib_rows(st,since); cb={}
    for r in cal: cb.setdefault(bucket(r["max_score"]),[]).append(r)
    calib={k:{"n":len(v),"reached_2x_pct":round(sum(1 for r in v if r["peak_x"]>=2)/len(v)*100),"dumped_70pct":round(sum(1 for r in v if r["now_x"]<=0.3)/len(v)*100),
              "median_peak_x":sorted(r["peak_x"] for r in v)[len(v)//2]} for k,v in sorted(cb.items())}
    if "--shadow" in sys.argv:
        for r in closed_w: r["shadow_wide_pnl_pct"]=shadow_wide(r)
    out={"generated_et":now.isoformat(timespec="seconds"),"window_h":hours,"thresholds":cfg["thresholds"],
         "book":{k:b.get(k) for k in ("equity","cash","starting_balance","day","day_pnl_pct","daily_halt_new_entries")}|{"loss_ladder":(b.get("loss_ladder") or {}).get("state")},
         "window":stats(win),"window_closed":stats(closed_w),"since_inception":stats(allr),"inception_closed":stats(closed),
         "by_score_bucket":{k:stats(v) for k,v in sorted(by_b.items())},"by_exit_rules":{k:stats(v) for k,v in sorted(by_x.items())},
         "by_exit_rules_closed":{k:stats([r for r in v if not r["open"]]) for k,v in sorted(by_x.items())},"score_calibration_window":calib,"trades_window":win,"calib_coins":sorted(cal,key=lambda r:-r["max_score"])[:25]}
    os.makedirs(REPORTS,exist_ok=True)
    def fmt(s):
        if not s.get("n"): return "none"
        return (f"n {s['n']}, hit {s['winners']}/{s['n']} ({s['hit_rate_pct']}%), P&L ${s['pnl_usd']:+.2f} on ${s['staked_usd']:.2f} staked ({s['return_on_staked_pct']:+.1f}%), "
                f"best {s['best']['symbol']} {s['best']['pnl_pct']:+.1f}%, worst {s['worst']['symbol']} {s['worst']['pnl_pct']:+.1f}%")
    bk=out["book"]
    md=[f"# Gem-score PAPER scorecard: {now:%Y-%m-%d %H:%M} ET (last {hours:.0f} h)",
        f"PAPER ONLY. Thresholds: paper entry >= {cfg['thresholds']['paper_entry']}, ping >= {cfg['thresholds']['ping']}. Exits: protocols/exit-rules.md v3.2a. Small sample: treat every % as anecdotal until n >= 30.",
        f"- Book: equity ${bk.get('equity')} (start ${bk.get('starting_balance')}), day {bk.get('day')} {bk.get('day_pnl_pct')}%, -12% halt {'ON' if bk.get('daily_halt_new_entries') else 'off'}, ladder {bk.get('loss_ladder')}",
        f"- Gem trades, last {hours:.0f} h (incl. open, marked net of 1.5% exit cost): {fmt(out['window'])}",
        f"- Closed only, last {hours:.0f} h: {fmt(out['window_closed'])}",
        f"- Since inception: {fmt(out['since_inception'])}",
        "- By exit rules (A/B: v3.2a = lock at +10%, exit_lock_50 = lock at +50%; closed trades only): "+("; ".join(f"{k}: {fmt(v)}" for k,v in out["by_exit_rules_closed"].items()) or "none"),
        "- By entry score: "+("; ".join(f"{k}: {fmt(v)}" for k,v in out["by_score_bucket"].items()) or "none"),
        "", "## Trades"]
    for r in win:
        md.append(f"- {r['symbol']} {r['mint'][:6]}.. score {r['score']} ${r['size']:.2f} {r['entry_time'][5:16]} [{r['exit_rules']}] {'OPEN' if r['open'] else 'closed '+'/'.join(r['exits'])}: "
                  f"P&L ${r['pnl']:+.2f} ({r['pnl_pct']:+.1f}%), peak {r['peak_x']}x"+(f", shadow wide-exit {r.get('shadow_wide_pnl_pct')}%" if 'shadow_wide_pnl_pct' in r else ""))
    if not win: md.append("- none")
    md+=["","## Did higher scores run? (every coin that reached WATCH in the window; x vs price when it first reached WATCH)"]
    md+=[f"- max score {k}: n {v['n']}, reached 2x {v['reached_2x_pct']}%, now <=0.3x {v['dumped_70pct']}%, median peak {v['median_peak_x']}x" for k,v in calib.items()] or ["- none"]
    md+=["- top: "+", ".join(f"{r['ticker']} {r['max_score']:.0f} (pk {r['peak_x']}x, now {r['now_x']}x)" for r in out["calib_coins"][:10])]
    ctr=CX.scorecard(); out["contrarian_1p5x"]=ctr
    cmd=CX.scorecard_md(ctr,now)
    md+=["",*cmd]
    ctxt="\n".join([f"# contrarian_1p5x PAPER scorecard: {now:%Y-%m-%d %H:%M} ET (since experiment start; separate sub-book)",*cmd[1:]])+"\n"
    for fn in (f"contrarian_1p5x_scorecard_{now:%Y-%m-%d}.md","contrarian_1p5x_scorecard_latest.md"): open(os.path.join(REPORTS,fn),"w").write(ctxt)
    json.dump(ctr,open(os.path.join(REPORTS,"contrarian_1p5x_scorecard_latest.json"),"w"),indent=1,default=str)
    txt="\n".join(md)+"\n"
    for fn in (f"gem_scorecard_{now:%Y-%m-%d}.md","gem_scorecard_latest.md"): open(os.path.join(REPORTS,fn),"w").write(txt)
    json.dump(out,open(os.path.join(REPORTS,f"gem_scorecard_{now:%Y-%m-%d}.json"),"w"),indent=1,default=str)
    if "--quiet" not in sys.argv: print(txt)
if __name__=="__main__": main()
