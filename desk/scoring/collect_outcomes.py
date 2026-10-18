#!/usr/bin/env python3
"""Collect outcome data for tg_alerts.jsonl contracts (READ-ONLY public GETs: DexScreener, GeckoTerminal, Rugcheck).
Writes data/outcomes_<date>.json: per contract: first detection snapshot, current DS pair, GT minute OHLCV-derived
peak/trough after first detection, rugcheck report digest (CURRENT, not at detection time: caveat)."""
import json,time,urllib.request,sys,os,datetime as D
ROOT=os.environ.get("UMBRELLA_HOME") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root (holds desk/ and tools/)
HERE=os.path.dirname(os.path.abspath(__file__))
ALERTS=os.environ.get("TG_ALERTS",ROOT+"/tools/tg_watch/tg_alerts.jsonl")
UA={"User-Agent":"desk-gem-score/1.0 (read-only)","Accept":"application/json"}
def get(u,t=20):
    return json.load(urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=t))
def main():
    first={}
    for l in open(ALERTS):
        try: a=json.loads(l)
        except ValueError: continue
        if a.get("chain")!="solana" or not a.get("contract"): continue
        first.setdefault(a["contract"],a)
    cas=list(first); ds={}
    for i in range(0,len(cas),30):
        for p in get("https://api.dexscreener.com/tokens/v1/solana/"+",".join(cas[i:i+30])):
            ca=p["baseToken"]["address"]; l=(p.get("liquidity") or {}).get("usd") or 0
            if ca not in ds or l>((ds[ca].get("liquidity") or {}).get("usd") or 0): ds[ca]=p
        time.sleep(0.5)
    out={}
    for ca in cas:
        a=first[ca]; p=ds.get(ca); rec={"ticker":a.get("ticker"),"first_alert_id":a.get("alert_id"),"detect_ts":a.get("post_ts") or 0,
            "detect_et":a.get("detect_time_et") or a.get("ts"),"ds_now":p}
        dts=D.datetime.fromisoformat(rec["detect_et"]).timestamp()
        if p:
            try:
                g=get(f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{p['pairAddress']}/ohlcv/minute?aggregate=1&limit=1000&currency=usd")
                c=sorted(g["data"]["attributes"]["ohlcv_list"])  # [ts,o,h,l,c,v]
                rec["ohlcv_n"]=len(c); rec["ohlcv"]=[x for x in c if x[0]>=dts-600]
            except Exception as e: rec["ohlcv_err"]=str(e)[:120]
            time.sleep(2.2)
        try: rc=get(f"https://api.rugcheck.xyz/v1/tokens/{ca}/report",25); rec["rugcheck"]={k:rc.get(k) for k in
             ("mintAuthority","freezeAuthority","score","score_normalised","rugged","totalHolders","graphInsidersDetected","creator","creatorBalance","totalMarketLiquidity","transferFee","risks","topHolders","knownAccounts","markets","token","launchpad","insiderNetworks")}
        except Exception as e: rec["rugcheck_err"]=str(e)[:120]
        time.sleep(1.0)
        out[ca]=rec; print(a.get("ticker"),ca[:6],"ohlcv",rec.get("ohlcv_n"),rec.get("ohlcv_err",""),"rc",("rugcheck" in rec),flush=True)
    fn=os.path.join(HERE,"data",f"outcomes_{D.datetime.now():%Y%m%d_%H%M}.json"); json.dump(out,open(fn,"w")); print(fn)
if __name__=="__main__": main()
