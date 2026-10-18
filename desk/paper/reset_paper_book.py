#!/usr/bin/env python3
"""reset_paper_book.py - PAPER ONLY. Archive the main paper book and start a fresh one at paper_config.json starting_bankroll_usd.
Paper bankroll is configurable $250-500 (default $250). History is kept: the old book is copied to
archive/paper_book_<ET date>_start<old start>.json (never overwritten) and listed in the new book's archived_books, which
a readiness report can read so evidence is not lost. Gem re-entry blocks (< 24 h) carry over as reentry_block.
Refuses while any position is open (close or wait first). With no book yet it creates the first one. Runs under paper_monitor's book lock. No network, no wallets.
Usage: python3 reset_paper_book.py [--bankroll USD] [--dry-run]"""
import json,os,sys,shutil,datetime as D
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE)
CFG=os.path.join(HERE,"paper_config.json"); ARCH=os.path.join(HERE,"archive")
ET=D.timezone(D.timedelta(hours=-4)); REENTRY_H=24
def load_cfg(path=CFG):
    c=json.load(open(path)); v=float(c["starting_bankroll_usd"]); lo,hi=c.get("allowed_range_usd",[250,500])
    if not (lo<=v<=hi): raise SystemExit(f"starting_bankroll_usd {v} outside allowed range {lo}-{hi}")
    return c
def bankroll(path=CFG): return float(load_cfg(path)["starting_bankroll_usd"])
def new_book(old,start,now,arch_path):
    t=now.isoformat(timespec="seconds")
    blk=[{"mint":p["mint"],"entry_time":p["entry_time"],"id":p["id"]} for p in old.get("positions",[])
         if str(p.get("source","")).startswith("gem_score") and (now-D.datetime.fromisoformat(p["entry_time"])).total_seconds()<REENTRY_H*3600]
    return {"mode":"PAPER","starting_balance":float(start),"cash":float(start),"equity":float(start),"day":now.date().isoformat(),"day_start_equity":float(start),
            "started_et":t,"bankroll_source":"paper_config.json starting_bankroll_usd",
            "assumptions":old.get("assumptions"),"rules":old.get("rules"),"positions":[],"closed_trades":[],"evaluations":[],
            "day_pnl_pct":0.0,"daily_halt_new_entries":False,"loss_ladder":{"state":"OK","new_entries_allowed":True,"size_mult":1.0,"realized_loss_pct":{"1h":0.0,"day":0.0,"week":0.0}},
            "archived_books":list(old.get("archived_books",[]))+[arch_path],
            "reentry_block":blk,"last_run":t,
            "history_note":f"Reset {t} (paper bankroll $250-500, default $250). Previous book (start ${old.get('starting_balance')}, equity ${old.get('equity')}) archived at {arch_path}."}
def main(argv):
    import paper_monitor as PM
    start=float(argv[argv.index("--bankroll")+1]) if "--bankroll" in argv else bankroll()
    lo,hi=load_cfg().get("allowed_range_usd",[250,500])
    if not (lo<=start<=hi): raise SystemExit(f"bankroll {start} outside {lo}-{hi}")
    now=D.datetime.now(ET); lk=PM.book_lock()
    try:
        if not os.path.exists(PM.BOOK):   # first install: no book yet -> create the first one, nothing to archive
            nb=new_book({},start,now,None); nb["archived_books"]=[]; nb["history_note"]=f"First paper book {now.isoformat(timespec='seconds')} at ${start:g} (paper_config.json)."
            if "--dry-run" in argv: print(json.dumps({"archive":None,"new":{k:nb[k] for k in ("starting_balance","cash","day","reentry_block")}},indent=1)); return 0
            lg=os.path.join(os.path.dirname(PM.BOOK),"paper_log.md")
            if not os.path.exists(lg): open(lg,"w").write("# Paper log (PAPER ONLY)\n")
            tmp=PM.BOOK+".tmp"; json.dump(nb,open(tmp,"w"),indent=1); os.replace(tmp,PM.BOOK)
            print(f"created first paper book ${start:g}"); return 0
        old=json.load(open(PM.BOOK))
        op=[p["id"] for p in old["positions"] if p["qty_open"]>1e-12]
        if op: raise SystemExit(f"refusing: open positions {op}")
        os.makedirs(ARCH,exist_ok=True)
        ap=os.path.join(ARCH,f"paper_book_{now:%Y-%m-%d}_start{old.get('starting_balance',0):g}.json"); i=1
        while os.path.exists(ap): ap=os.path.join(ARCH,f"paper_book_{now:%Y-%m-%d}_start{old.get('starting_balance',0):g}_{i}.json"); i+=1
        old_arch=dict(old,archived_et=now.isoformat(timespec="seconds"),archived_reason="paper bankroll reset to $%g"%start)
        nb=new_book(old,start,now,ap)
        if "--dry-run" in argv: print(json.dumps({"archive":ap,"new":{k:nb[k] for k in ("starting_balance","cash","day","reentry_block")}},indent=1)); return 0
        json.dump(old_arch,open(ap,"x"),indent=1)
        tmp=PM.BOOK+".tmp"; json.dump(nb,open(tmp,"w"),indent=1); os.replace(tmp,PM.BOOK)
        PM.record(nb,[dict(ts=now.isoformat(timespec="seconds"),type="BOOK_RESET",symbol="-",id="-",price=0.0,
                           reason=f"paper book reset to ${start:g} (paper_config.json); old book (start ${old.get('starting_balance')}, equity ${old.get('equity')}, {len(old.get('closed_trades',[]))} closes) archived at {ap}")],[],now)
        print(f"reset: new book ${start:g}; archived {ap}")
        return 0
    finally: lk.close()
if __name__=="__main__": sys.exit(main(sys.argv[1:]))
