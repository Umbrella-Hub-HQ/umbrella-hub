#!/usr/bin/env python3
"""tg_mentions.py - READ-ONLY Telegram call check (stdlib). Never posts.
Sources: desk.db caller_performance (source LIKE 'tg:%') + public previews https://t.me/s/<channel>
(preview shows only the ~20 most recent posts, so absence != never called).
Usage: python3 tg_mentions.py <mint> [<mint>...]   -> JSON per mint."""
import json,re,sqlite3,sys,urllib.request,html,os
ROOT=os.environ.get("UMBRELLA_HOME") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
def _channels():
    """PUBLIC channels from tools/tg_watch/config.json (extra_channels minus disabled_channels). Empty if not set up."""
    try: c=json.load(open(os.environ.get("TGWATCH_CONFIG",os.path.join(ROOT,"tools","tg_watch","config.json"))))
    except Exception: return []
    dis={d.lower() for d in c.get("disabled_channels") or []}
    return [e["channel"] for e in c.get("extra_channels") or [] if e.get("channel") and e["channel"].lower() not in dis and not e["channel"].startswith("EXAMPLE_")]
CHANNELS=_channels()
DB=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","desk.db")
def fetch(ch):
    try:
        r=urllib.request.urlopen(urllib.request.Request(f"https://t.me/s/{ch}",headers={"User-Agent":"Mozilla/5.0"}),timeout=20)
        return r.read().decode("utf-8","replace"),None
    except Exception as e: return None,str(e)
def preview_hits(page,mint):
    hits=[];window=None
    for blk in page.split('class="tgme_widget_message_wrap')[1:]:
        if mint in blk or mint in html.unescape(blk):
            m=re.search(r'<time[^>]*datetime="([^"]+)"',blk); hits.append(m.group(1) if m else "UNKNOWN")
    ts=re.findall(r'<time[^>]*datetime="([^"]+)"',page)
    return hits,(min(ts),max(ts)) if ts else None
def check(mints,pages=None):
    pages=pages or {ch:fetch(ch) for ch in CHANNELS}
    out={}
    try: con=sqlite3.connect(f"file:{DB}?mode=ro",uri=True)
    except Exception: con=None
    for m in mints:
        calls=[]
        if con:
            for src,ts in con.execute("SELECT source,call_ts FROM caller_performance WHERE source LIKE 'tg:%' AND contract=?",(m,)):
                calls.append({"channel":src,"ts":ts or "UNKNOWN","via":"desk.db"})
        errors={}
        for ch,(page,err) in pages.items():
            if page is None: errors[ch]=err; continue
            hits,_=preview_hits(page,m)
            for t in hits: calls.append({"channel":ch,"ts":t,"via":"t.me/s preview"})
        chans=sorted({c["channel"].split(":",1)[-1].lower() for c in calls})
        dated=sorted([c for c in calls if c["ts"]!="UNKNOWN"],key=lambda c:c["ts"])
        first=dated[0] if dated else (calls[0] if calls else None)
        out[m]={"n_channels":len(chans),"channels":chans,"first":first,"calls":calls,"fetch_errors":errors,
                "confidence_factor":"RAISE" if len(chans)>=2 else "NEUTRAL"}
    return out
if __name__=="__main__":
    print(json.dumps(check(sys.argv[1:]),indent=1))
