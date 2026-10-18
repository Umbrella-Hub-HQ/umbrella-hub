#!/usr/bin/env python3
"""Tests for the 2026-10-18 paper250 job (PAPER ONLY): $250 configurable paper bankroll + book reset/archive, and the
contrarian_1p5x experiment. Offline: no network (G fetchers stubbed), temp files only; never touches the real books.
Run (from the repo root): python3 -m unittest discover -s desk/scoring/tests -v"""
import json,os,sys,copy,tempfile,unittest,datetime as D
ROOT=os.environ.get("UMBRELLA_HOME") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # repo root
HERE=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,HERE); sys.path.insert(0,os.path.join(ROOT,"desk","paper"))
import gem_score as G, contrarian as CX, paper_monitor as PM
CFG=G.load_cfg(); ET=G.ET
# Template fixture: the shipped configs have no channels (each owner picks their own). Point the experiment at placeholder
# configs in a temp dir: tg_watch extra_channels + one caller feed. Same files tg_watch.load_channels() merges.
_FX=tempfile.mkdtemp(); os.makedirs(os.path.join(_FX,"ww"),exist_ok=True)
json.dump({"extra_channels":[{"channel":"PromoChanA"},{"channel":"ExampleChanB"}],"disabled_channels":[]},open(os.path.join(_FX,"tg.json"),"w"))
json.dump({"caller_feeds":{"CallerA":{"tg":"callerchana"}}},open(os.path.join(_FX,"ww","config.json"),"w"))
CX.TG_CFG=os.path.join(_FX,"tg.json"); CX.WW_CFG=os.path.join(_FX,"ww","config.json"); CX.WSRC=os.path.join(_FX,"none.json")
os.environ["WALLETWATCH_DIR"]=os.path.join(_FX,"ww"); os.environ["TGWATCH_SOURCES"]=os.path.join(_FX,"none.json")
CFG["promo_channels"]=["PromoChanA","PromoChanB","PromoChanC","PromoChanD","PromoChanE"]
CFG["owner_caller_channels"]=["callerchana","callerchanb","callerchanc","callerchand"]
T0=D.datetime(2026,10,18,2,0,tzinfo=ET); NOW=T0.timestamp()
XC=CX.config(CFG)
def cand(**kw):
    c=dict(contract="MintC",ticker="CTR",now_ts=NOW,price=1.0,mcap=200000,liq=30000,vol_h1=60000,m5=-4,h1=10,buys_m5=100,sells_m5=120,
           buys_h1=1200,sells_h1=1100,age_min=90,dex_id="pumpswap",sell_route="OK",ring="NONE",
           sources=[{"channel":"PromoChanA","post_ts":NOW-120,"kind":"call"}],
           rugcheck={"mint_authority":None,"freeze_authority":None,"rugged":False,"lp_locked_pct":100,"top10_pct":20,"rc_score_adj":5})
    c.update(kw); return c
SRC=["tg:PromoChanA"]
def elig(c,src=SRC,last=NOW-60):
    r=G.score(c,CFG); return CX.eligible(c,r,CFG,XC,src,last,NOW),r
class Bankroll(unittest.TestCase):
    def setUp(self):
        import reset_paper_book as R; self.R=R; self.d=tempfile.mkdtemp(); self.ob,self.ol=PM.BOOK,PM.LOCK; self.oa=R.ARCH
        PM.BOOK=os.path.join(self.d,"paper_book.json"); PM.LOCK=os.path.join(self.d,"l"); R.ARCH=os.path.join(self.d,"archive")
        self.cfgp=os.path.join(self.d,"paper_config.json")
    def tearDown(self): PM.BOOK,PM.LOCK=self.ob,self.ol; self.R.ARCH=self.oa
    def old(self,open_=False):
        p=lambda i,src,et,q: {"id":i,"symbol":i,"mint":"M"+i,"source":src,"entry_time":et,"qty":1.0,"qty_open":q,"size_usd":5.0,"entry_price":1.0,"peak_price":1.0,"last_price":1.0}
        b={"mode":"PAPER","starting_balance":100.0,"cash":96.03,"equity":96.03,"assumptions":{"x":1},"rules":{"y":2},"evaluations":[],
           "positions":[p("G1","gem_score","2026-10-18T01:30:00-04:00",0.0),p("G0","gem_score","2026-10-16T01:30:00-04:00",0.0),p("L1",None,"2026-10-18T01:00:00-04:00",1.0 if open_ else 0.0)],
           "closed_trades":[{"id":"G1","pnl_usd":-1.0,"exit_time":"2026-10-18T01:40:00-04:00","reason":"STOP_-30"}]}
        json.dump(b,open(PM.BOOK,"w")); return b
    def test_config_is_250_and_in_range(self):
        c=json.load(open(ROOT+"/desk/paper/paper_config.json")); self.assertEqual(c["starting_bankroll_usd"],250); self.assertEqual(c["allowed_range_usd"],[250,500])
        self.assertEqual(self.R.bankroll(),250.0)
    def test_first_book_created_when_missing(self):
        self.assertFalse(os.path.exists(PM.BOOK)); self.assertEqual(self.R.main([]),0)
        b=json.load(open(PM.BOOK)); self.assertEqual((b["starting_balance"],b["cash"],b["positions"],b["archived_books"]),(250.0,250.0,[],[]))
        self.assertTrue(os.path.exists(os.path.join(self.d,"paper_log.md")))
    def test_out_of_range_refused(self):
        for v in (100,600):
            json.dump({"starting_bankroll_usd":v,"allowed_range_usd":[250,500]},open(self.cfgp,"w"))
            with self.assertRaises(SystemExit): self.R.load_cfg(self.cfgp)
    def test_reset_archives_and_starts_250(self):
        old=self.old(); self.assertEqual(self.R.main([]),0)
        nb=json.load(open(PM.BOOK)); self.assertEqual((nb["starting_balance"],nb["cash"],nb["equity"]),(250.0,250.0,250.0))
        self.assertEqual(nb["positions"],[]); self.assertEqual(nb["closed_trades"],[]); self.assertEqual(nb["loss_ladder"]["state"],"OK")
        ap=nb["archived_books"][-1]; a=json.load(open(ap)); self.assertTrue(os.path.basename(ap).startswith("paper_book_") and "start100" in ap)
        self.assertEqual(a["positions"],old["positions"]); self.assertEqual(a["closed_trades"],old["closed_trades"]); self.assertEqual(a["starting_balance"],100.0)
        self.assertEqual([x["mint"] for x in nb["reentry_block"]],["MG1"])   # only gem entries < 24 h old carry over
        self.assertEqual(nb["assumptions"],{"x":1})
    def test_reset_never_overwrites_archive(self):
        self.old(); self.R.main([]); self.old(); self.R.main([])
        self.assertEqual(len(os.listdir(self.R.ARCH)),2)
    def test_reset_refuses_open_positions(self):
        self.old(open_=True)
        with self.assertRaises(SystemExit): self.R.main([])
        self.assertEqual(json.load(open(PM.BOOK))["starting_balance"],100.0)
    def test_loss_ladder_scales_with_250(self):
        b={"starting_balance":250.0,"closed_trades":[{"pnl_usd":-10.0,"exit_time":T0.isoformat()}]}
        self.assertEqual(PM.loss_ladder(b,T0)["realized_loss_pct"]["day"],4.0)
        b["starting_balance"]=100.0; self.assertEqual(PM.loss_ladder(b,T0)["realized_loss_pct"]["day"],10.0)
    def test_gem_reentry_block_respected(self):
        import gem_paper as GP; GP.RS_DISABLED=True; oj=GP.JOURNAL; GP.JOURNAL=os.path.join(self.d,"j")
        try:
            b={"mode":"PAPER","starting_balance":250.0,"cash":250.0,"day":"2026-10-18","day_start_equity":250.0,"positions":[],"closed_trades":[],
               "reentry_block":[{"mint":"MintE","entry_time":"2026-10-18T01:30:00-04:00","id":"X"}]}
            json.dump(b,open(PM.BOOK,"w"))
            c=cand(contract="MintE"); r=G.score(c,CFG); pair={"priceUsd":"0.001","pairAddress":"P1","marketCap":200000,"baseToken":{"symbol":"T"},"liquidity":{"usd":40000}}
            self.assertEqual(GP.try_enter({},CFG,c,r,pair,T0)[0],"SKIP_REENTRY")
            b["reentry_block"]=[]; json.dump(b,open(PM.BOOK,"w")); a,why,pos=GP.try_enter({},CFG,c,r,pair,T0)
            self.assertEqual(a,"OPEN"); self.assertTrue(4.99<=pos["size_usd"]<=12.5)   # 2-5% of $250
        finally: GP.JOURNAL=oj
    def test_readiness_dd_uses_book_start(self):
        try: import readiness_report as RR
        except ImportError: self.skipTest('readiness_report.py is install-specific; not shipped in the template')
        ts=[{"pnl_usd":-25.0}]; self.assertEqual(RR.max_dd(ts,250.0),10.0); self.assertEqual(RR.max_dd(ts,100.0),25.0)
class HardVetoesNeverEntered(unittest.TestCase):
    def no(self,**kw):
        (ok,why,_),r=elig(cand(**kw)); self.assertFalse(ok,(kw,why)); return why
    def test_mint_authority(self): self.no(rugcheck={"mint_authority":"X","freeze_authority":None})
    def test_freeze_authority(self): self.no(rugcheck={"mint_authority":None,"freeze_authority":"X"})
    def test_honeypot(self): self.no(sell_route="NO_ROUTE")
    def test_rugged(self): self.no(rugcheck={"mint_authority":None,"freeze_authority":None,"rugged":True})
    def test_rug_shield_reject(self): self.no(ring="REJECT")
    def test_liq_under_5k(self): self.no(liq=4500,mcap=40000,vol_h1=9000)
    def test_m5_dump_50(self): self.no(m5=-55)
    def test_fail_closed_no_rugcheck(self): self.assertIn("UNVERIFIED",self.no(rugcheck=None))
    def test_fail_closed_unknown_route(self): self.assertIn("UNVERIFIED",self.no(sell_route="UNKNOWN"))
    def test_fail_closed_unknown_liq(self): self.no(liq=None,liq_est=None)
    def test_mutant_hard_prefix_killed(self):
        old=CX.HARD_PREFIX
        try:
            CX.HARD_PREFIX=tuple(x for x in old if x!="live mint authority")
            (ok,why,_),r=elig(cand(rugcheck={"mint_authority":"X","freeze_authority":None}))
            self.assertTrue(ok)   # mutant would enter a live-mint-authority coin -> test_mint_authority catches it
        finally: CX.HARD_PREFIX=old
class SoftSkipsEntered(unittest.TestCase):
    def yes(self,**kw):
        (ok,why,rs),r=elig(cand(**kw)); self.assertTrue(ok,(why,r["score"],r["vetoes"])); return rs,r
    def test_low_score_tagged(self):
        rs,r=self.yes(); self.assertLess(r["score"],CFG["thresholds"]["paper_entry"]); self.assertIn("low_score",rs); self.assertIn("momentum",rs)
    def test_fake_volume(self): rs,_=self.yes(vol_h1=30000*20); self.assertIn("fake_volume",rs)
    def test_already_ran(self): rs,_=self.yes(first_call_mcap=30000); self.assertIn("already_ran",rs)
    def test_liquidity_cap(self): rs,_=self.yes(liq=12000,mcap=100000,vol_h1=24000); self.assertIn("liquidity_cap",rs)
    def test_soft_veto_dumped_from_peak_allowed(self):
        rs,r=self.yes(price=0.15,peak_price_seen=1.0); self.assertEqual(r["label"],"VETO"); self.assertEqual(CX.primary_reason(rs),"dumped_from_peak")
    def test_min_score_floor(self):
        (ok,why,_),r=elig(cand(),last=NOW-60); xc=dict(XC,min_score=99)
        self.assertFalse(CX.eligible(cand(),r,CFG,xc,SRC,NOW-60,NOW)[0])
    def test_not_owner_source(self): (ok,why,_),r=elig(cand(),src=[]); self.assertFalse(ok)
    def test_stale_call(self): (ok,why,_),r=elig(cand(),last=NOW-3600); self.assertFalse(ok)
    def test_main_entry_not_duplicated(self):
        r={"label":"PAPER_ENTRY","vetoes":[],"score":70,"factors":{},"penalties":[]}
        self.assertFalse(CX.eligible(cand(),r,CFG,XC,SRC,NOW-60,NOW)[0])
class Sources(unittest.TestCase):
    def test_tags(self):
        chans={"promochana":"PromoChanA","callerchana":"callerchana"}; callers={"callerchana"}
        coin={"sources":{"a":{"channel":"PromoChanA","post_ts":1,"kind":"call"},"b":{"channel":"callerchana","post_ts":2,"kind":"call"},
                         "c":{"channel":"RandomChan","post_ts":3,"kind":"call"},"d":{"channel":"PromoChanA","post_ts":4,"kind":"brag"}},
              "wallet":[{"wallet":"w","caller":"CallerA","src":"wallet_watch"},{"wallet":"f","src":"flywheel"},{"wallet":"x"}]}
        self.assertEqual(CX.owner_sources(coin,chans,callers),["tg:PromoChanA","caller_watch:callerchana","wallet_watch:CallerA","flywheel"])
        self.assertEqual(CX.owner_sources({"sources":{"c":{"channel":"RandomChan","kind":"call"}},"wallet":[]},chans,callers),[])
    def test_live_channel_list_matches_tg_watch(self):
        sys.path.insert(0,ROOT+"/tools/tg_watch")
        try: import tg_watch as TW
        except Exception as e: self.skipTest(f"tg_watch import {e}")
        tw={c["channel"].lower() for c in TW.load_channels(json.load(open(CX.TG_CFG)))}
        self.assertEqual(set(CX.owner_channels()[0]),tw)
def mkpos(**kw):
    b={"cash":245.0,"positions":[],"closed_trades":[]}
    c=cand(); r=G.score(c,CFG); pair={"priceUsd":"1.0","pairAddress":"P","marketCap":200000,"baseToken":{"symbol":"CTR"}}
    fill=lambda px,liq,size,m5:(px*1.02,0.0,0.005)
    p,_=CX.open_position(b,XC,c,r,pair,SRC,["low_score"],T0,fill); p.update(kw); return b,p
class ExitsAndTracking(unittest.TestCase):
    def at(self,h): return T0+D.timedelta(hours=h)
    def test_fixed_size_and_levels(self):
        b,p=mkpos(); self.assertEqual(p["size_usd"],5.0); self.assertAlmostEqual(p["tp_price"],1.02*1.5); self.assertAlmostEqual(p["stop_price"],1.02*0.65)
        self.assertEqual(p["primary_skip"],"low_score"); self.assertEqual(p["sources"],SRC); self.assertAlmostEqual(b["cash"],240.0)
    def test_tp_then_track_after_exit(self):
        b,p=mkpos(); e=p["entry_price"]
        self.assertIsNone(CX.step_position(b,p,XC,e*1.3,30000,self.at(1)))
        ex=CX.step_position(b,p,XC,e*1.55,30000,self.at(2)); self.assertEqual(ex["reason"],"TP_1.5X"); self.assertGreater(ex["pnl_pct"],45)
        self.assertEqual(p["qty_open"],0.0); self.assertIn("1.5x",p["track"]["reached"])
        CX.step_position(b,p,XC,e*2.5,30000,self.at(5)); CX.step_position(b,p,XC,e*3.2,30000,self.at(10))
        self.assertEqual(p["track"]["peak_x"],3.2); self.assertIn("3x",p["track"]["reached"]); self.assertEqual(p["track"]["post_exit_peak_x"],3.2)
        self.assertEqual(p["exit"]["reason"],"TP_1.5X")   # exit is not rewritten by later prices
        CX.step_position(b,p,XC,e*5,30000,self.at(25)); self.assertTrue(p["track"]["done"]); self.assertEqual(p["track"]["peak_x"],3.2)   # after 24 h: not counted
    def test_stop_35(self):
        b,p=mkpos(); e=p["entry_price"]
        self.assertIsNone(CX.step_position(b,p,XC,e*0.70,30000,self.at(1)))   # -30% is NOT the stop here
        ex=CX.step_position(b,p,XC,e*0.64,30000,self.at(2)); self.assertEqual(ex["reason"],"STOP_-35"); self.assertLess(ex["pnl_pct"],-35)
    def test_timeout_24h(self):
        b,p=mkpos(); e=p["entry_price"]; CX.step_position(b,p,XC,e*1.1,30000,self.at(3))
        ex=CX.step_position(b,p,XC,e*1.2,30000,self.at(24.01)); self.assertEqual(ex["reason"],"TIMEOUT_24H"); self.assertTrue(p["track"]["done"])
    def test_rug(self):
        b,p=mkpos(); ex=CX.step_position(b,p,XC,p["entry_price"]*0.5,50,self.at(1)); self.assertEqual(ex["reason"],"RUG")
    def test_jump_needs_confirmation(self):
        b,p=mkpos(); e=p["entry_price"]
        self.assertIsNone(CX.step_position(b,p,XC,e*20,30000,self.at(1))); self.assertEqual(p["qty_open"],p["qty"]); self.assertLess(p["track"]["peak_x"],2)
        ex=CX.step_position(b,p,XC,e*21,30000,self.at(1.02)); self.assertEqual(ex["reason"],"TP_1.5X")
    def test_mutant_tp_killed(self):
        xc=dict(XC,tp_x=2.0); b,p=mkpos(); p["tp_price"]=p["entry_price"]*xc["tp_x"]
        self.assertIsNone(CX.step_position(b,p,xc,p["entry_price"]*1.55,30000,self.at(1)))   # a 2x mutant would not exit -> test_tp catches it
class EngineCycle(unittest.TestCase):
    def setUp(self):
        self.d=tempfile.mkdtemp(); self.saved=(CX.BOOK,CX.JOURNAL,CX.LOCK,CX.PAPER_CFG,PM.BOOK)
        CX.BOOK=os.path.join(self.d,"ctr.json"); CX.JOURNAL=os.path.join(self.d,"ctr.jsonl"); CX.LOCK=os.path.join(self.d,"l"); CX.PAPER_CFG=os.path.join(self.d,"pc.json")
        json.dump({"starting_bankroll_usd":250},open(CX.PAPER_CFG,"w"))
        PM.BOOK=os.path.join(self.d,"main.json"); json.dump({"untouched":True},open(PM.BOOK,"w"))
    def tearDown(self): CX.BOOK,CX.JOURNAL,CX.LOCK,CX.PAPER_CFG,PM.BOOK=self.saved
    class FakeG:
        calls=[]
        def fetch_pairs(self,m,ttl=15): self.calls.append(("fetch",tuple(m))); return {}
        def rugcheck_digest(self,ca): self.calls.append(("rc",ca)); return {"mint_authority":None,"freeze_authority":"F" if ca=="Bad" else None,"rugged":False,"decimals":6}
        def sell_route(self,ca,dec): self.calls.append(("route",ca)); return "OK",0.01
        def score(self,c,cfg): return G.score(c,cfg)
    def test_cycle_enters_soft_skip_only(self):
        fg=self.FakeG(); fg.calls=[]
        coin=lambda ch:{"last_alert":NOW-60,"sources":{"x":{"channel":ch,"post_ts":NOW-60,"kind":"call"}},"wallet":[]}
        ch=sorted(CX.owner_channels()[0].values())[0]
        pair=lambda s:{"priceUsd":"1.0","pairAddress":"P"+s,"marketCap":200000,"baseToken":{"symbol":s},"liquidity":{"usd":30000}}
        good=cand(contract="Good",rugcheck=None,sell_route=None,sources=[{"channel":ch,"post_ts":NOW-60,"kind":"call"}]); bad=dict(good,contract="Bad")
        ext=cand(contract="Ext",sources=[{"channel":"NotOwnersChannelXYZ","post_ts":NOW-60,"kind":"call"}])
        cands=[("Good",coin(ch),good,G.score(good,CFG),pair("GOOD")),("Bad",coin(ch),bad,G.score(bad,CFG),pair("BAD")),
               ("Ext",coin("NotOwnersChannelXYZ"),ext,G.score(ext,CFG),pair("EXT"))]
        st={}; cfg=copy.deepcopy(CFG); cfg["experiments"]["contrarian_1p5x"]["active"]=True
        out=CX.run_cycle(st,cfg,cands,T0,fg,lambda px,liq,size,m5:(px*1.02,0.0,0.005))
        b=json.load(open(CX.BOOK)); self.assertEqual([p["mint"] for p in b["positions"]],["Good"]); self.assertEqual(b["starting_balance"],250.0)
        p=b["positions"][0]; self.assertEqual(p["size_usd"],5.0); self.assertTrue(p["primary_skip"]); self.assertEqual(p["sources"],["caller_watch:"+ch] if ch.lower() in CX.owner_channels()[1] else ["tg:"+ch])
        self.assertAlmostEqual(b["cash"],245.0)
        self.assertEqual(json.load(open(PM.BOOK)),{"untouched":True})   # main book never touched
        js=[json.loads(l) for l in open(CX.JOURNAL)]; self.assertEqual([j["type"] for j in js if j["type"]=="CTR_ENTER"],["CTR_ENTER"])
        self.assertTrue(any(j["type"]=="CTR_SKIP" and j["mint"]=="Bad" and "HARD" in j["why"] for j in js))
        CX.run_cycle(st,cfg,cands,T0+D.timedelta(seconds=45),fg,lambda px,liq,size,m5:(px*1.02,0.0,0.005))
        self.assertEqual(len(json.load(open(CX.BOOK))["positions"]),1)   # no re-entry
        sc=CX.scorecard(CX.BOOK); self.assertEqual(sc["overall"]["n"],1); self.assertIn(p["primary_skip"],sc["by_primary_skip"]); self.assertIn(p["primary_source"],sc["by_primary_source"])
        self.assertTrue(any("contrarian_1p5x" in l for l in CX.scorecard_md(sc,T0)))
    def test_inactive_does_nothing(self):
        cfg=copy.deepcopy(CFG); cfg["experiments"]["contrarian_1p5x"]["active"]=False
        self.assertEqual(CX.run_cycle({},cfg,[],T0,self.FakeG(),None),{"active":False}); self.assertFalse(os.path.exists(CX.BOOK))
class ScorecardStats(unittest.TestCase):
    def test_stats(self):
        b,p1=mkpos(); _,p2=mkpos(); b["positions"]=[p1,p2]; e=p1["entry_price"]
        p2["primary_skip"]="fake_volume"; p2["skip_reasons"]=["fake_volume","low_score"]; p2["primary_source"]=p2["sources"][0]="wallet_watch"
        CX.step_position(b,p1,XC,e*1.6,30000,T0+D.timedelta(hours=1)); CX.step_position(b,p2,XC,e*0.6,30000,T0+D.timedelta(hours=1))
        d=tempfile.mkdtemp(); fp=os.path.join(d,"b.json"); json.dump(b,open(fp,"w"))
        sc=CX.scorecard(fp); o=sc["overall"]
        self.assertEqual((o["n"],o["closed"],o["tp_hits"],o["tp_hit_rate_pct"]),(2,2,1,50.0)); self.assertEqual(o["reached_1.5x_pct"],50.0)
        self.assertEqual(sc["by_primary_skip"]["fake_volume"]["tp_hits"],0); self.assertEqual(sc["by_any_skip_reason"]["low_score"]["n"],2)
        self.assertIn("wallet_watch",sc["by_source_kind"]); self.assertIn("tg",sc["by_source_kind"])
        self.assertAlmostEqual(sc["equity"],round(b["cash"],2),2)
    def test_live_config_values(self):
        x=CFG["experiments"]["contrarian_1p5x"]
        self.assertTrue(x["active"]); self.assertEqual((x["tp_x"],x["stop_pct"],x["timeout_h"],x["track_h"]),(1.5,-35.0,24,24)); self.assertTrue(5<=x["size_usd"]<=10)
        self.assertEqual(CFG["exit_experiment"],"exit_lock_50"); self.assertEqual(CFG["thresholds"]["paper_entry"],62)   # main engine unchanged
if __name__=="__main__": unittest.main(verbosity=2)
class ExcludeMainEntries(unittest.TestCase):
    def test_main_engine_mints_excluded(self):
        d=tempfile.mkdtemp(); saved=(CX.BOOK,CX.JOURNAL,CX.LOCK)
        CX.BOOK=os.path.join(d,"b.json"); CX.JOURNAL=os.path.join(d,"j"); CX.LOCK=os.path.join(d,"l")
        try:
            ch=sorted(CX.owner_channels()[0].values())[0]
            c=cand(contract="Taken",sources=[{"channel":ch,"post_ts":NOW-60,"kind":"call"}])
            coin={"last_alert":NOW-60,"sources":{"x":{"channel":ch,"post_ts":NOW-60,"kind":"call"}},"wallet":[]}
            pair={"priceUsd":"1.0","pairAddress":"P","marketCap":200000,"baseToken":{"symbol":"T"},"liquidity":{"usd":30000}}
            cfg=copy.deepcopy(CFG); cfg["experiments"]["contrarian_1p5x"]["active"]=True
            CX.run_cycle({},cfg,[("Taken",coin,c,G.score(c,CFG),pair)],T0,EngineCycle.FakeG(),lambda px,l,s,m:(px*1.02,0,0),exclude={"Taken"})
            self.assertEqual(json.load(open(CX.BOOK))["positions"],[])
            CX.run_cycle({},cfg,[("Taken",coin,c,G.score(c,CFG),pair)],T0,EngineCycle.FakeG(),lambda px,l,s,m:(px*1.02,0,0))
            self.assertEqual(len(json.load(open(CX.BOOK))["positions"]),1)
        finally: CX.BOOK,CX.JOURNAL,CX.LOCK=saved
