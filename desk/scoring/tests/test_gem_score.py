#!/usr/bin/env python3
"""Tests for gem_score.py / gem_paper.py (PAPER ONLY). Run: python3 -m unittest discover -s desk/scoring/tests -v"""
import json,os,sys,time,glob,tempfile,unittest,datetime as D
ROOT=os.environ.get("UMBRELLA_HOME") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))   # repo root
HERE=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,HERE); sys.path.insert(0,os.path.join(ROOT,"desk","paper"))
import gem_score as G
NOW=1792290000.0
def base(**kw):
    c=dict(contract="Mint111",ticker="TEST",now_ts=NOW,price=1.0,mcap=200000,liq=40000,vol_h1=200000,m5=20,h1=50,buys_m5=300,sells_m5=200,
           buys_h1=2400,sells_h1=2000,age_min=20,dex_id="pumpswap",
           sources=[{"channel":"PromoChanA","post_ts":NOW-600,"kind":"call"},{"channel":"PromoChanD","post_ts":NOW-300,"kind":"call"},
                    {"channel":"PromoChanE","post_ts":NOW-100,"kind":"call"}],
           rugcheck={"mint_authority":None,"freeze_authority":None,"lp_locked_pct":100,"top10_pct":15,"rc_score_adj":1})
    c.update(kw); return c
CFG=G.load_cfg()
# Template fixture: the shipped weights.json has empty channel lists (each owner fills their own). Tests use placeholders.
CFG["promo_channels"]=["PromoChanA","PromoChanB","PromoChanC","PromoChanD","PromoChanE"]
CFG["owner_caller_channels"]=["callerchana","callerchanb","callerchanc","callerchand"]
class Vetoes(unittest.TestCase):
    def v(self,**kw): return G.score(base(**kw),CFG)
    def test_clean_has_no_veto(self): self.assertEqual(self.v()["vetoes"],[])
    def test_mint_authority(self): self.assertIn("live mint authority",self.v(rugcheck={"mint_authority":"X"})["vetoes"])
    def test_freeze_authority(self): self.assertIn("live freeze authority",self.v(rugcheck={"freeze_authority":"X"})["vetoes"])
    def test_honeypot(self): self.assertEqual(self.v(sell_route="NO_ROUTE")["label"],"VETO")
    def test_unknown_route_is_not_veto(self): self.assertEqual(self.v(sell_route="UNKNOWN")["vetoes"],[])
    def test_ring_reject(self): self.assertEqual(self.v(ring="REJECT")["label"],"VETO")
    def test_ring_flag_soft(self):
        r=self.v(ring="FLAG"); self.assertEqual(r["vetoes"],[]); self.assertLess(r["score"],self.v()["score"])
    def test_liq_under_5k(self): self.assertEqual(self.v(liq=4000)["label"],"VETO")
    def test_m5_dump(self): self.assertEqual(self.v(m5=-55)["label"],"VETO")
    def test_dumped_80_from_peak(self): self.assertEqual(self.v(price=0.15,peak_price_seen=1.0)["label"],"VETO")
class NoLongerGates(unittest.TestCase):
    def test_liq_15k_not_vetoed(self):
        r=G.score(base(liq=15000,mcap=90000),CFG); self.assertEqual(r["vetoes"],[]); self.assertGreater(r["score"],45)
    def test_fresh_pair_not_vetoed(self): self.assertEqual(G.score(base(age_min=2),CFG)["vetoes"],[])
    def test_vertical_partial_penalty(self):
        hi=G.score(base(m5=300),CFG)["score"]; mid=G.score(base(m5=30),CFG)["score"]
        self.assertLess(hi,mid); self.assertGreater(hi,mid-8)
    def test_vol_liq_over_15_not_veto(self): self.assertEqual(G.score(base(vol_h1=40000*25),CFG)["vetoes"],[])
class Factors(unittest.TestCase):
    def test_weights_sum_100(self): self.assertEqual(sum(CFG["weights"].values()),100)
    def test_spl_makai_separate_sources(self):
        c=base(sources=[{"channel":"PromoChanC","post_ts":NOW-60,"kind":"call"},{"channel":"PromoChanB","post_ts":NOW-30,"kind":"call"}])
        self.assertEqual(G.score(c,CFG)["n_independent"],2)
    def test_source_groups_feature_still_works(self):
        cfg=dict(CFG,source_groups={"PromoChanC":"G","PromoChanB":"G"})
        c=base(sources=[{"channel":"PromoChanC","post_ts":NOW-60,"kind":"call"},{"channel":"PromoChanB","post_ts":NOW-30,"kind":"call"}])
        self.assertEqual(G.score(c,cfg)["n_independent"],1)
    def test_brag_not_counted(self):
        c=base(sources=[{"channel":"PromoChanA","post_ts":NOW-60,"kind":"call"},{"channel":"callerchand","post_ts":NOW-30,"kind":"brag"}])
        self.assertEqual(G.score(c,CFG)["n_independent"],1)
    def test_old_sources_expire(self):
        c=base(sources=[{"channel":"PromoChanA","post_ts":NOW-5*3600,"kind":"call"}]); self.assertEqual(G.score(c,CFG)["n_independent"],0)
    def test_more_sources_higher(self):
        one=base(sources=[{"channel":"PromoChanA","post_ts":NOW-60,"kind":"call"}])
        self.assertGreater(G.score(base(),CFG)["score"],G.score(one,CFG)["score"]+10)
    def test_liquidity_monotonic(self):
        s=[G.score(base(liq=l,mcap=l*5,vol_h1=l*5),CFG)["score"] for l in (8000,20000,50000,100000)]; self.assertEqual(s,sorted(s))
    def test_owner_caller_and_wallet_add(self):
        b=G.score(base(),CFG)["score"]
        self.assertGreater(G.score(base(sources=base()["sources"]+[{"channel":"callerchand","post_ts":NOW-10,"kind":"call"}]),CFG)["score"],b)
        self.assertGreater(G.score(base(wallet_overlap=[{"wallet":"w1","grade":"STRONG"}]),CFG)["score"],b)
    def test_copycat_penalty(self): self.assertLess(G.score(base(copycat_of="Other111"),CFG)["score"],G.score(base(),CFG)["score"]-5)
    def test_bonding_curve_estimate(self):
        est=G.bonding_liq_est(31681,180); self.assertTrue(20000<est<35000)
        r=G.score(base(liq=None,liq_est=est,dex_id="pumpfun"),CFG); self.assertEqual(r["vetoes"],[])
    def test_unknown_data_neutral(self):
        r=G.score(base(buys_m5=None,sells_m5=None,rugcheck=None),CFG)
        self.assertEqual(r["factors"]["flow"]["value"],0.5); self.assertEqual(r["factors"]["safety"]["value"],0.5)
    def test_rugcheck_low_liq_removed(self):
        raw={"score_normalised":33,"risks":[{"name":"Low Liquidity","score":2700}],"markets":[],"topHolders":[],"knownAccounts":{}}
        self.assertEqual(G.rugcheck_digest("m",raw=raw)["rc_score_adj"],0)
    def test_why_line(self):
        r=G.score(base(),CFG); self.assertTrue(r["why"].startswith(f"{r['score']:.0f}/100"))
    def test_bundle_regex(self):
        self.assertEqual(G.bundle_from_text("Bundled: 55.65% left"),55.65); self.assertIsNone(G.bundle_from_text("no data"))
class Engine(unittest.TestCase):
    def setUp(self):
        import paper_monitor as PM, gem_paper as GP
        self.PM,self.GP=PM,GP; self.d=tempfile.mkdtemp(); self.ob,self.ol=PM.BOOK,PM.LOCK
        PM.BOOK=os.path.join(self.d,"book.json"); PM.LOCK=os.path.join(self.d,"book.lock")
        self.oj=GP.JOURNAL; GP.JOURNAL=os.path.join(self.d,"j.jsonl")
        self.GP.RS_DISABLED=True
    def tearDown(self): self.PM.BOOK,self.PM.LOCK=self.ob,self.ol; self.GP.JOURNAL=self.oj
    def book(self,**kw):
        b={"mode":"PAPER","starting_balance":100.0,"cash":100.0,"day":"2026-10-17","day_start_equity":100.0,"positions":[],"closed_trades":[],"evaluations":[]}
        b.update(kw); json.dump(b,open(self.PM.BOOK,"w")); return b
    def pair(self): return {"priceUsd":"0.001","pairAddress":"P1","marketCap":200000,"baseToken":{"symbol":"TEST"},"liquidity":{"usd":40000}}
    def test_fill_costs(self):
        e,imp,ch=self.GP.entry_fill(1.0,40000,3.0,20); self.assertGreater(e,1.015); self.assertGreater(imp,0)
        e2,_,_=self.GP.entry_fill(1.0,8000,3.0,20); self.assertGreater(e2,e)
        e3,_,ch3=self.GP.entry_fill(1.0,40000,3.0,500); self.assertLessEqual(ch3,0.03)
    def test_size_2_to_5_pct(self):
        s,p=self.GP.size_for(62,62,100,1.0); self.assertAlmostEqual(p,0.02)
        s,p=self.GP.size_for(95,62,100,1.0); self.assertAlmostEqual(p,0.05); s,p=self.GP.size_for(95,62,100,0.5); self.assertAlmostEqual(s,2.5)
    def _enter(self,t):
        c=base(contract="MintE"); r=G.score(c,CFG); return self.GP.try_enter({}, CFG, c, r, self.pair(), t)
    def test_daily_halt_blocks(self):
        t=D.datetime(2026,10,17,23,0,tzinfo=G.ET)
        self.book(cash=85.0,day_start_equity=100.0)   # -15% today
        a,why,pos=self._enter(t); self.assertEqual(a,"SKIP_DAILY_HALT")
    def test_next_day_resets_halt(self):
        t=D.datetime(2026,10,18,0,5,tzinfo=G.ET)
        self.book(cash=85.0,day_start_equity=100.0,day="2026-10-17")
        a,why,pos=self._enter(t); self.assertEqual(a,"OPEN",why)
        b=json.load(open(self.PM.BOOK)); self.assertEqual(b["day"],"2026-10-18"); self.assertEqual(len(b["positions"]),1)
        p=b["positions"][0]; self.assertEqual(p["source"],"gem_score"); self.assertAlmostEqual(p["stop_price"],p["entry_price"]*0.70)
        self.assertLess(b["cash"],85.0); self.assertIn("factors",p["gem"]); self.assertEqual(p.get("exit_experiment"),"exit_lock_50")
    def test_no_duplicate(self):
        t=D.datetime(2026,10,17,23,0,tzinfo=G.ET); self.book()
        self.assertEqual(self._enter(t)[0],"OPEN"); self.assertEqual(self._enter(t)[0],"SKIP_DUP")
class Backtest(unittest.TestCase):
    def test_tonight_calibration(self):
        fs=sorted(glob.glob(os.path.join(HERE,"data","outcomes_20261017_*.json")))
        if not fs: self.skipTest("no outcomes file")
        import backtest as B
        o=json.load(open(fs[0])); cs=B.run(o,CFG)
        first={}
        for l in open(B.ALERTS):
            a=json.loads(l)
            if a.get("contract") and (a.get("dex") or {}).get("price_usd"): first.setdefault(a["contract"],a)
        ents=[ca for ca,c in cs.items() if c["entry"] and B.ts_of(c["entry"]["t"])<B.ts_of("2026-10-17T23:16:00-04:00")]
        labs=[B.outcome_label(ca,o,first)[0] for ca in ents]
        self.assertGreaterEqual(sum(l=="RUNNER" for l in labs),4); self.assertLessEqual(sum(l=="RUG/DUMP" for l in labs),1)
if __name__=="__main__": unittest.main(verbosity=2)

class ExitLock50(unittest.TestCase):
    """exit_lock_50 experiment (reference install 2026-10-17, PAPER ONLY): lock at +50% for opted-in positions; default v3.2a untouched."""
    def setUp(self):
        import paper_monitor as PM; self.PM=PM; self.old_shadow=PM.SHADOW_LOG
        PM.SHADOW_LOG=os.path.join(tempfile.mkdtemp(),"shadow.ndjson")   # never write test rows into the real shadow log
    def tearDown(self): self.PM.SHADOW_LOG=self.old_shadow
    def pos(self,exp=None,peak=1.2):
        p={"id":"T","symbol":"T","mint":"M","pair":"P","entry_price":1.0,"mkt_price_at_entry":1.0,"qty":10.0,"qty_open":10.0,"size_usd":10.0,
           "stop_price":0.70,"peak_price":peak,"last_price":peak,"realized_usd":0.0,"entry_time":"2026-10-17T23:00:00-04:00",
           "time_stop_at":"2026-10-18T23:00:00-04:00","last_liq":50000,"entry_liq":50000}
        if exp: p["exit_experiment"]=exp
        return p
    def book(self): return {"cash":0.0,"closed_trades":[],"positions":[]}
    def now(self): return D.datetime(2026,10,17,23,30,tzinfo=G.ET)
    def test_default_unchanged(self):
        self.assertEqual(self.PM.exit_params(self.pos())["lock_start"],1.10)
        st,t=self.PM.runner_trail(self.pos(peak=1.2),"NEUTRAL"); self.assertAlmostEqual(st,max(1/(1-0.015),1.2*0.75))
    def test_no_lock_below_50(self):
        st,t=self.PM.runner_trail(self.pos("exit_lock_50",peak=1.45),"STRONG"); self.assertEqual(st,0.0)
        b=self.book(); p=self.pos("exit_lock_50",peak=1.0); self.PM.apply_rules(b,p,1.3,self.now())
        self.assertFalse(p.get("lock_active")); self.assertGreater(p["qty_open"],0)
        b=self.book(); q=self.pos(peak=1.0); self.PM.apply_rules(b,q,1.3,self.now()); self.assertTrue(q.get("lock_active"))   # v3.2a locks at +10%
    def test_lock_at_50_breakeven(self):
        b=self.book(); p=self.pos("exit_lock_50",peak=1.0); self.PM.apply_rules(b,p,1.55,self.now())
        self.assertTrue(p.get("lock_active")); self.assertAlmostEqual(p["runner_stop"],1/(1-0.015),6)   # 35% trail from 1.55 < BE
    def test_trails_and_keep_half_from_2x(self):
        st,t=self.PM.runner_trail(self.pos("exit_lock_50",peak=2.5),"NEUTRAL"); self.assertEqual(t,0.35); self.assertAlmostEqual(st,max(1.75,2.5*0.65))
        st,t=self.PM.runner_trail(self.pos("exit_lock_50",peak=4.0),"STRONG"); self.assertEqual(t,0.30)
        st,t=self.PM.runner_trail(self.pos("exit_lock_50",peak=1.8),"NEUTRAL"); self.assertAlmostEqual(st,max(1/(1-0.015),1.8*0.65))   # no keep-half below 2x
    def test_hard_stop_still_applies_prelock(self):
        b=self.book(); p=self.pos("exit_lock_50",peak=1.3); self.PM.apply_rules(b,p,0.69,self.now())
        self.assertLessEqual(p["qty_open"],1e-12); self.assertEqual(b["closed_trades"][-1]["reason"],"STOP_-30")
    def test_engine_tags_new_positions(self):
        import gem_paper as GP
        self.assertEqual(GP.active_exit_experiment(CFG),"exit_lock_50")
        self.assertIsNone(GP.active_exit_experiment(dict(CFG,experiments={"exit_lock_50":{"active":False}})))
        self.assertIsNone(GP.active_exit_experiment(dict(CFG,exit_experiment="nope")))
    def test_mutant_lock_start_killed(self):
        old=self.PM.EXIT_EXPERIMENTS["exit_lock_50"]["lock_start"]
        try:
            self.PM.EXIT_EXPERIMENTS["exit_lock_50"]["lock_start"]=1.10
            b=self.book(); p=self.pos("exit_lock_50",peak=1.0); self.PM.apply_rules(b,p,1.3,self.now())
            self.assertTrue(p.get("lock_active"))   # the mutant locks early -> test_no_lock_below_50 would fail on it
        finally: self.PM.EXIT_EXPERIMENTS["exit_lock_50"]["lock_start"]=old
