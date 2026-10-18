#!/usr/bin/env python3
"""tg_watch.py: READ-ONLY near-real-time watcher for PUBLIC Telegram call channels (Umbrella Hub generic copy, 2026-10-17).

Polls https://t.me/s/<channel> (public web preview, no account, no login) every 30 s (channels that posted in the last
24 h) or 60 s (quiet ones), through tools/_http.py's shared polite limiter (t.me group, 2 s spacing; a 429 puts every tool
on the box into the shared cooldown). Extracts Solana / EVM contract addresses (text + hrefs, never followed) and $tickers,
dedupes per channel+contract (24 h), snapshots DexScreener (price, mcap, liquidity) at detection and appends alerts to
tg_alerts.jsonl.

Priority: HIGH when 2+ distinct channels post the same contract within 30 min (post times), or the contract overlaps a
watched wallet's activity (tools/wallet_watch alerts/events/state buys + flywheel_alerts WATCHED_RECEIVE) from 24 h before
to 6 h after the call (late overlaps are re-checked every loop and emitted as WALLET_OVERLAP_LATE). MEDIUM = a normal
call; LOW = brag / results post (multiplier + brag words), which never triggers HIGH.

NEVER sends, joins, reacts, clicks bot links, signs or pays. Channel text is untrusted data: only regex fields are used.
Usage: tg_watch.py            (loop)
       tg_watch.py --once     (one pass over every channel, then exit; still writes alerts)
       tg_watch.py --test     (unit tests of extraction/priority, no network)
Files (this dir): tg_alerts.jsonl, tg_events.jsonl, state.json, status.json, beat.json, tg_watch.log
"""
from __future__ import annotations

import argparse
import html as htmlmod
import json
import os
import random
import re
import signal
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
import _http  # noqa: E402

D = os.environ.get("TGWATCH_DIR", HERE)
CFG_PATH = os.environ.get("TGWATCH_CONFIG", os.path.join(HERE, "config.json"))
WW = os.environ.get("WALLETWATCH_DIR", os.path.join(TOOLS, "wallet_watch"))   # optional: watched-wallet overlap source
SOURCES = os.environ.get("TGWATCH_SOURCES", os.path.join(TOOLS, "data", "watched_sources.json"))   # optional
ET = ZoneInfo("America/New_York")
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
              "Accept": "text/html,application/xhtml+xml"}

B58 = "1-9A-HJ-NP-Za-km-z"
SOL_RE = re.compile(rf"(?<![{B58}])[{B58}]{{32,44}}(?![{B58}])")
EVM_RE = re.compile(r"(?<![0-9a-fA-Fx])0x[0-9a-fA-F]{40}(?![0-9a-fA-F])")
TICKER_RE = re.compile(r"(?<![A-Za-z0-9_$])\$([A-Za-z][A-Za-z0-9_]{0,19})(?![A-Za-z0-9_])")
HREF_RE = re.compile(r'href="([^"]+)"')
MULT_RE = re.compile(r"(?<![\w.])(\d{1,4}(?:\.\d+)?)\s?[xX](?![\w])")
BRAG_WORDS = re.compile(r"\b(hit|hits|did|done|pumped|gain|gains|profit|from call|since call|ath|up|result|results)\b|🚀|✅|🔥|💰", re.I)
STRONG_BRAG = re.compile(r"(gain:|→\s*now|->\s*now|first call:|called at|from call|since call|lab result|premium hit|プレミアムヒット|\bhit\s+\d|\bdid\s+\d+(?:\.\d+)?\s?x|\bATH\b)", re.I)
CALL_WORDS = re.compile(r"\b(ca|contract|ape|aped|entry|buy|buying|new call|signal|alpha|gem|launch(?:ed)?|sample under analysis|match found)\b", re.I)
SKIP_TICKERS = {"SOL", "ETH", "BTC", "USDC", "USDT", "USD", "BNB"}

STOP = False


def now() -> float:
    return time.time()


def et(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, ET).isoformat(timespec="seconds") if ts else None


def jload(p, default):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return default


def jdump_atomic(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, default=str)
    os.replace(tmp, p)


def append_jsonl(p, row):
    with open(p, "a") as f:
        f.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False, default=str) + "\n")


def log(msg):
    print(f"{datetime.now(ET).strftime('%F %T')} {msg}", flush=True)


# ------------------------------------------------------------------ channels
def source_group(ch: str, cfg) -> str:
    """Channels listed together in cfg['source_groups'] (channel -> group id, case-insensitive) count as ONE source
    for the multi-channel HIGH rule. Empty by default: every channel counts separately. Group channels only when data
    shows they post identical calls (mirrors); never group from a channel's name alone."""
    g = {k.lower(): v for k, v in (cfg.get("source_groups") or {}).items()}
    return g.get((ch or "").lower(), (ch or "").lower())


def independent_groups(prior_channels, own_ch: str, cfg) -> list[str]:
    """Distinct source groups among prior callers, excluding the poster's own group."""
    own = source_group(own_ch, cfg)
    return sorted({source_group(c, cfg) for c in prior_channels} - {own})


def load_channels(cfg) -> list[dict]:
    out, seen = [], set()

    def add(ch, label, source):
        if not ch or ch.lower() in seen or ch in cfg.get("disabled_channels", []):
            return
        seen.add(ch.lower())
        out.append({"channel": ch, "label": label, "source": source})
    ww = jload(os.path.join(WW, "config.json"), {})
    for name, feed in (ww.get("caller_feeds") or {}).items():
        add((feed or {}).get("tg"), name, "wallet_watch/config.json caller_feeds")
    for s in jload(SOURCES, {}).get("sources", []):
        if s.get("type") == "telegram" and s.get("enabled", True):
            add(s.get("channel"), s.get("id"), "tools/data/watched_sources.json")
    for e in cfg.get("extra_channels", []):
        add(e.get("channel"), e.get("label"), e.get("source", "tg_watch/config.json extra_channels"))
    return out


# ------------------------------------------------------------------ parsing
def html_to_text(fragment: str) -> str:
    t = re.sub(r"<br\s*/?>", "\n", fragment)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"[ \t]+", " ", htmlmod.unescape(t)).strip()


def parse_page(page: str, channel: str) -> list[dict]:
    msgs = []
    for part in re.split(r'(?=<div class="tgme_widget_message_wrap)', page)[1:]:
        pid = re.search(rf'data-post="{re.escape(channel)}/(\d+)"', part, re.I)
        if not pid:
            continue
        tm = re.search(r'<time datetime="([^"]+)"', part)
        body = re.search(r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>', part, re.S)
        ts = None
        if tm:
            try:
                ts = datetime.fromisoformat(tm.group(1)).timestamp()
            except ValueError:
                pass
        raw = body.group(1) if body else ""
        hrefs = [htmlmod.unescape(h) for h in HREF_RE.findall(raw)]
        # inline keyboard / link preview hrefs also carry CAs (pump.fun/<mint>, dexscreener, bot ?start=<ca>): parse only
        for blk in re.findall(r'<a class="tgme_widget_message_(?:link_preview|inline_button)[^"]*"[^>]*href="([^"]+)"', part):
            hrefs.append(htmlmod.unescape(blk))
        msgs.append({"msg_id": int(pid.group(1)), "ts": ts, "text": html_to_text(raw), "hrefs": hrefs})
    return msgs


def extract(msg: dict, ignore: set[str], max_addrs: int) -> dict:
    txt = msg.get("text") or ""
    blob = txt + "\n" + "\n".join(msg.get("hrefs") or [])
    addrs: list[str] = []
    for a in EVM_RE.findall(blob):
        if a.lower() not in {x.lower() for x in addrs} and a.lower() not in ignore:
            addrs.append(a)
    for a in SOL_RE.findall(blob):
        if re.fullmatch(r"[1-9]+", a) or a in ignore or a in addrs:
            continue
        if not (re.search(r"[a-z]", a) and re.search(r"[A-Z]", a) and re.search(r"[1-9]", a)):
            continue  # real base58 mints mix cases and digits; skips words/hashes-in-urls
        addrs.append(a)
    tickers = []
    for t in TICKER_RE.findall(txt):
        if t.upper() not in SKIP_TICKERS and t.upper() not in [x.upper() for x in tickers]:
            tickers.append(t)
    mults = MULT_RE.findall(txt)
    is_brag = bool(STRONG_BRAG.search(txt)) or (bool(mults) and bool(BRAG_WORDS.search(txt)) and not CALL_WORDS.search(txt[:120]))
    return {"addrs": addrs[:max_addrs], "n_addrs": len(addrs), "tickers": tickers[:5], "brag": is_brag}


def chain_of(a: str) -> str:
    return "evm" if a.startswith("0x") else "solana"


# ------------------------------------------------------------------ dexscreener
def ds_snapshot(addrs: list[str]) -> dict[str, dict | None]:
    out = {a: None for a in addrs}
    for i in range(0, len(addrs), 30):
        chunk = addrs[i:i + 30]
        r = _http.get_json("https://api.dexscreener.com/latest/dex/tokens/" + ",".join(chunk), cache_ttl=0, timeout=10, retries=1)
        if not r.ok or not isinstance(r.data, dict):
            for a in chunk:
                out[a] = {"error": f"{r.status} {(r.error or '')[:80]}"}
            continue
        for a in chunk:
            best = None
            for p in r.data.get("pairs") or []:
                bt = (p.get("baseToken") or {}).get("address") or ""
                if bt.lower() != a.lower():
                    continue
                if best is None or ((p.get("liquidity") or {}).get("usd") or 0) > ((best.get("liquidity") or {}).get("usd") or 0):
                    best = p
            if best:
                bt = best.get("baseToken") or {}
                out[a] = {"price_usd": float(best["priceUsd"]) if best.get("priceUsd") else None,
                          "mcap_usd": best.get("marketCap") or best.get("fdv"), "fdv_usd": best.get("fdv"),
                          "liq_usd": (best.get("liquidity") or {}).get("usd"), "symbol": bt.get("symbol"),
                          "name": bt.get("name"), "dex_chain": best.get("chainId"), "dex_id": best.get("dexId"),
                          "pair_url": best.get("url"),
                          "pair_created_et": et(best["pairCreatedAt"] / 1000) if best.get("pairCreatedAt") else None,
                          "vol_h1": (best.get("volume") or {}).get("h1"), "chg_m5": (best.get("priceChange") or {}).get("m5"),
                          "snapshot_et": et(now())}
    return out


# ------------------------------------------------------------------ watched wallets
def wallet_activity() -> tuple[dict[str, list[dict]], dict[str, dict]]:
    """contract(lower) -> [activity]; plus watched wallet addr(lower) -> meta."""
    act: dict[str, list[dict]] = {}
    cfg = jload(os.path.join(WW, "config.json"), {})
    wallets = {w["address"].lower(): w for w in cfg.get("wallets", []) if w.get("address")}

    def add(contract, row):
        if contract:
            act.setdefault(contract.lower(), []).append(row)

    def tail(p, n=3000):
        rows = []
        try:
            with open(p) as f:
                lines = f.readlines()[-n:]
            for ln in lines:
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    pass
        except OSError:
            pass
        return rows
    for r in tail(os.path.join(WW, "alerts.jsonl")):
        if r.get("contract") and r.get("kind") not in (None,) and "DUST" not in str(r.get("kind")):
            add(r["contract"], {"src": "wallet_watch/alerts", "kind": r.get("kind"), "wallet": r.get("wallet"),
                                "caller": r.get("caller"), "ts": r.get("buy_ts") or _ts(r.get("ts")), "size_usd": r.get("size_usd")})
    for r in tail(os.path.join(WW, "events.jsonl")):
        if r.get("contract") and r.get("wallet") and "DUST" not in str(r.get("kind")):
            w = wallets.get(str(r["wallet"]).lower(), {})
            add(r["contract"], {"src": "wallet_watch/events", "kind": r.get("kind"), "wallet": r.get("wallet"),
                                "caller": w.get("caller"), "ts": _ts(r.get("time_et")) or _ts(r.get("ts")), "size_usd": r.get("size_usd")})
    st = jload(os.path.join(WW, "state.json"), {})
    for b in st.get("buys", []):
        add(b.get("contract"), {"src": "wallet_watch/state.buys", "kind": "BUY", "wallet": b.get("wallet"),
                                "caller": b.get("caller"), "ts": b.get("ts")})
    for r in tail(os.path.join(WW, "flywheel_alerts.jsonl")):
        if r.get("kind") in ("WATCHED_RECEIVE", "LAUNCH_BY_WATCHED") and (r.get("contract") or r.get("token")):
            add(r.get("contract") or r.get("token"), {"src": "flywheel_alerts", "kind": r.get("kind"), "wallet": r.get("wallet"),
                                                      "caller": r.get("wallet_label") or r.get("wallet_kind"),
                                                      "ts": _ts(r.get("event_time_et")) or _ts(r.get("ts"))})
    return act, wallets


def _ts(s):
    if not s:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    try:
        return datetime.fromisoformat(str(s)).timestamp()
    except ValueError:
        return None


def overlaps(contract: str, call_ts: float, act: dict, cfg) -> list[dict]:
    lo = call_ts - cfg["overlap_wallet_lookback_h"] * 3600
    hi = call_ts + cfg["overlap_wallet_after_h"] * 3600
    out = []
    for a in act.get(contract.lower(), []):
        t = a.get("ts")
        if t is None or lo <= t <= hi:
            out.append({**a, "time_et": et(t) if t else None})
    return out


# ------------------------------------------------------------------ watcher
class Watcher:
    def __init__(self, cfg):
        self.cfg = cfg
        self.state = jload(os.path.join(D, "state.json"), {})
        for k, v in (("channels", {}), ("calls", []), ("dedupe", {}), ("overlap_flagged", {}), ("alert_seq", 0),
                     ("latency", []), ("tickers", [])):
            self.state.setdefault(k, v)
        self.ignore = {a.lower() for a in cfg.get("ignore_addresses", [])} | {a for a in cfg.get("ignore_addresses", [])}
        self.errors: list[str] = []
        self.stats = {"polls": 0, "poll_errors": 0, "posts_seen": 0, "alerts": 0, "started": now()}
        self.act, self.wallets, self.act_ts = {}, {}, 0.0
        self.ww_wallet_set: set[str] = set()

    # --- persistence
    def save(self):
        cut = now() - 48 * 3600
        self.state["calls"] = [c for c in self.state["calls"] if c["ts"] >= cut][-5000:]
        self.state["tickers"] = [c for c in self.state["tickers"] if c["ts"] >= cut][-3000:]
        dcut = now() - self.cfg["dedupe_h"] * 3600
        self.state["dedupe"] = {k: v for k, v in self.state["dedupe"].items() if v >= dcut}
        self.state["overlap_flagged"] = {k: v for k, v in self.state["overlap_flagged"].items() if v >= cut}
        self.state["latency"] = self.state["latency"][-500:]
        jdump_atomic(os.path.join(D, "state.json"), self.state)

    def refresh_wallets(self, force=False):
        if force or now() - self.act_ts > 55:
            try:
                self.act, self.wallets = wallet_activity()
            except Exception as e:  # never die on a sibling file
                self.errors.append(f"wallet_activity: {e}")
            self.act_ts = now()

    # --- fetch
    def fetch(self, ch: str) -> tuple[list[dict] | None, float]:
        url = f"https://t.me/s/{ch}"
        r = _http.get_text(url, headers=BROWSER_UA, cache_ttl=0, timeout=12, retries=1)
        t = now()
        self.stats["polls"] += 1
        if not r.ok:
            self.stats["poll_errors"] += 1
            self.errors.append(f"{et(t)} tg {ch}: {r.status} {(r.error or '')[:80]}")
            return None, t
        page = r.data if isinstance(r.data, str) else r.text
        msgs = parse_page(page, ch)
        cs = self.state["channels"].get(ch, {})
        last = cs.get("last_id", 0)
        if last and msgs and min(m["msg_id"] for m in msgs) > last + 1:  # >20 posts since last poll: one older page
            r2 = _http.get_text(f"{url}?before={min(m['msg_id'] for m in msgs)}", headers=BROWSER_UA, cache_ttl=0, timeout=12, retries=1)
            if r2.ok:
                msgs = parse_page(r2.data if isinstance(r2.data, str) else r2.text, ch) + msgs
        return msgs, t

    # --- process one channel
    def poll_channel(self, chinfo: dict) -> list[dict]:
        ch = chinfo["channel"]
        msgs, fetch_ts = self.fetch(ch)
        cs = self.state["channels"].setdefault(ch, {"last_id": 0, "last_post_ts": None, "first_poll_et": et(now())})
        prev_poll = cs.get("last_poll_ts")
        cs["last_poll_et"], cs["last_poll_ts"] = et(fetch_ts), fetch_ts
        if msgs is None:
            cs["last_error_et"] = et(fetch_ts)
            return []
        cs["ok_polls"] = cs.get("ok_polls", 0) + 1
        first = cs["last_id"] == 0
        new = sorted((m for m in msgs if m["msg_id"] > cs["last_id"]), key=lambda m: m["msg_id"])
        if msgs:
            cs["last_post_ts"] = max([m["ts"] for m in msgs if m["ts"]] + [cs.get("last_post_ts") or 0]) or None
            cs["last_post_et"] = et(cs["last_post_ts"])
        out = []
        for m in new:
            cs["last_id"] = max(cs["last_id"], m["msg_id"])
            self.stats["posts_seen"] += 1
            age = fetch_ts - (m["ts"] or fetch_ts)
            catchup = first or age > self.cfg["startup_alert_max_age_s"] * (1 if first else 10)
            seed_only = first and age > self.cfg["startup_alert_max_age_s"]
            ex = extract(m, self.ignore, self.cfg["max_addrs_per_post"])
            link = f"https://t.me/{ch}/{m['msg_id']}"
            if not first and m["ts"]:
                self.state["latency"].append({"ch": ch, "id": m["msg_id"], "post_ts": m["ts"], "detect_ts": fetch_ts,
                                              "latency_s": round(fetch_ts - m["ts"], 1), "has_ca": bool(ex["addrs"]),
                                              "prev_poll_ts": prev_poll,
                                              "preview_lag_min_s": round(prev_poll - m["ts"], 1) if prev_poll and prev_poll > m["ts"] else 0})
            if not ex["addrs"]:
                if ex["tickers"]:
                    self.state["tickers"].append({"ts": m["ts"] or fetch_ts, "channel": ch, "tickers": ex["tickers"], "link": link})
                    append_jsonl(os.path.join(D, "tg_events.jsonl"), {"kind": "TICKER_ONLY", "channel": ch, "link": link,
                                 "post_time_et": et(m["ts"]), "tickers": ex["tickers"], "detect_et": et(fetch_ts), "seed": seed_only})
                continue
            if seed_only:  # backlog seen at first start: remember for cross-channel matching, no alert
                for a in ex["addrs"]:
                    self.state["calls"].append({"contract": a, "channel": ch, "ts": m["ts"] or fetch_ts, "msg_id": m["msg_id"],
                                                "brag": ex["brag"], "seed": True})
                    self.state["dedupe"][f"{ch}:{a.lower()}"] = m["ts"] or fetch_ts
                continue
            out.append({"ch": ch, "label": chinfo.get("label"), "msg": m, "ex": ex, "fetch_ts": fetch_ts, "link": link,
                        "catchup": catchup})
        return out

    def emit(self, cands: list[dict]):
        if not cands:
            return
        self.refresh_wallets()
        todo = []
        for c in cands:
            for a in c["ex"]["addrs"]:
                k = f"{c['ch']}:{a.lower()}"
                if k in self.state["dedupe"]:
                    continue
                todo.append((c, a))
        if not todo:
            return
        snaps = ds_snapshot(sorted({a for _, a in todo}))
        for c, a in todo:
            m, ex = c["msg"], c["ex"]
            post_ts = m["ts"] or c["fetch_ts"]
            k = f"{c['ch']}:{a.lower()}"
            self.state["dedupe"][k] = post_ts
            snap = snaps.get(a)
            win = self.cfg["cross_window_s"]
            prior = [p for p in self.state["calls"] if p["contract"].lower() == a.lower() and p["channel"] != c["ch"]
                     and abs(p["ts"] - post_ts) <= win and not p.get("brag")]
            sym = (snap or {}).get("symbol") if isinstance(snap, dict) else None
            tick_match = []
            if sym:
                for t in self.state["tickers"]:
                    if t["channel"] != c["ch"] and abs(t["ts"] - post_ts) <= win and sym.upper() in [x.upper() for x in t["tickers"]]:
                        tick_match.append({"channel": t["channel"], "post_time_et": et(t["ts"]), "link": t["link"], "match": "ticker"})
            self.state["calls"].append({"contract": a, "channel": c["ch"], "ts": post_ts, "msg_id": m["msg_id"], "brag": ex["brag"]})
            ov = overlaps(a, post_ts, self.act, self.cfg)
            is_wallet = a.lower() in self.wallets
            reasons = []
            prio = "LOW" if ex["brag"] else "MEDIUM"
            chans = sorted({p["channel"] for p in prior})
            indep = independent_groups(chans, c["ch"], self.cfg)
            if indep and not ex["brag"]:
                prio = "HIGH"
                reasons.append(f"{len(indep) + 1} independent sources ({len(chans) + 1} channels) called this contract within {win // 60} min: {', '.join(chans + [c['ch']])}")
            elif prior and not ex["brag"]:
                reasons.append(f"also called by same-source group channel(s) {', '.join(chans)} (counted as one source, not HIGH)")
            if ov:
                prio = "HIGH"
                reasons.append("watched wallet overlap: " + "; ".join(
                    f"{o.get('caller') or '?'} {str(o.get('wallet'))[:6]}.. {o.get('kind')} {o.get('time_et') or ''}" for o in ov[:3]))
                self.state["overlap_flagged"][a.lower()] = now()
            if is_wallet:
                reasons.append(f"posted address is a WATCHED WALLET ({self.wallets[a.lower()].get('caller')}), not a token")
            if tick_match and not prior:
                reasons.append("same ticker posted (no CA) by: " + ", ".join(sorted({t['channel'] for t in tick_match})))
            if isinstance(snap, dict) and snap.get("error"):
                reasons.append(f"DexScreener error: {snap['error']}")
            elif snap is None:
                reasons.append("no DexScreener pair at detection (unlisted, wallet, or not a token)")
            if isinstance(snap, dict) and not snap.get("error"):
                if snap.get("dex_id") == "pumpfun":
                    reasons.append("still on pump.fun bonding curve (DS shows no pool liquidity)")
                elif (snap.get("liq_usd") or 0) < 5000:
                    reasons.append(f"DS liquidity only ${snap.get('liq_usd') or 0:,.0f}")
                if snap.get("chg_m5") is not None and snap["chg_m5"] <= -50:
                    reasons.append(f"DS m5 {snap['chg_m5']}% (dumping / likely rugged)")
            if c["catchup"] and prio != "HIGH":
                reasons.append("catch-up (post older than live window)")
            ticker = (ex["tickers"][0] if ex["tickers"] else None) or sym
            self.state["alert_seq"] += 1
            row = {"ts": et(now()), "alert_id": self.state["alert_seq"], "kind": "TG_CALL", "priority": prio,
                   "notify": prio == "HIGH", "reasons": reasons, "channel": c["ch"], "channel_label": c.get("label"),
                   "post_id": m["msg_id"], "post_link": c["link"], "post_time_et": et(m["ts"]), "post_ts": m["ts"],
                   "detect_time_et": et(c["fetch_ts"]), "latency_s": round(c["fetch_ts"] - m["ts"], 1) if m["ts"] else None,
                   "catchup": c["catchup"], "contract": a, "chain": (snap or {}).get("dex_chain") if isinstance(snap, dict) and snap.get("dex_chain") else chain_of(a),
                   "ticker": ticker, "tickers_in_post": ex["tickers"], "post_kind": "brag" if ex["brag"] else "call",
                   "n_addrs_in_post": ex["n_addrs"], "dex": snap,
                   "cross_channels": [{"channel": p["channel"], "post_time_et": et(p["ts"]),
                                       "link": f"https://t.me/{p['channel']}/{p['msg_id']}"} for p in prior] + tick_match,
                   "wallet_overlap": ov, "text_snippet": (m.get("text") or "")[:240],
                   "dedupe_key": f"TG_CALL:{k}"}
            append_jsonl(os.path.join(D, "tg_alerts.jsonl"), row)
            self.stats["alerts"] += 1
            log(f"ALERT #{row['alert_id']} {prio} {c['ch']} {a} ${ticker} lat={row['latency_s']}s mc={(snap or {}).get('mcap_usd') if isinstance(snap, dict) else None} {'; '.join(reasons)[:160]}")

    def late_overlaps(self):
        """A watched wallet buys a contract AFTER a TG channel already called it -> one HIGH WALLET_OVERLAP_LATE."""
        self.refresh_wallets()
        cut = now() - self.cfg["overlap_wallet_after_h"] * 3600
        for p in [c for c in self.state["calls"] if c["ts"] >= cut and not c.get("brag")]:
            key = p["contract"].lower()
            if key in self.state["overlap_flagged"]:
                continue
            ov = overlaps(p["contract"], p["ts"], self.act, self.cfg)
            if not ov:
                continue
            self.state["overlap_flagged"][key] = now()
            calls = [c for c in self.state["calls"] if c["contract"].lower() == key]
            snap = ds_snapshot([p["contract"]]).get(p["contract"])
            self.state["alert_seq"] += 1
            row = {"ts": et(now()), "alert_id": self.state["alert_seq"], "kind": "WALLET_OVERLAP_LATE", "priority": "HIGH",
                   "notify": True, "reasons": ["watched wallet activity on a contract a TG channel called: " + "; ".join(
                       f"{o.get('caller') or '?'} {str(o.get('wallet'))[:6]}.. {o.get('kind')} {o.get('time_et') or ''}" for o in ov[:3])],
                   "channel": p["channel"], "post_link": f"https://t.me/{p['channel']}/{p['msg_id']}", "post_time_et": et(p["ts"]),
                   "contract": p["contract"], "chain": (snap or {}).get("dex_chain") if isinstance(snap, dict) else chain_of(p["contract"]),
                   "ticker": (snap or {}).get("symbol") if isinstance(snap, dict) else None, "dex": snap,
                   "cross_channels": [{"channel": c["channel"], "post_time_et": et(c["ts"]),
                                       "link": f"https://t.me/{c['channel']}/{c['msg_id']}"} for c in calls],
                   "wallet_overlap": ov, "dedupe_key": f"WALLET_OVERLAP_LATE:{key}"}
            append_jsonl(os.path.join(D, "tg_alerts.jsonl"), row)
            self.stats["alerts"] += 1
            log(f"ALERT #{row['alert_id']} HIGH WALLET_OVERLAP_LATE {p['contract']} {row['reasons'][0][:160]}")

    def status(self, chans, sched):
        def summ(rows, note):
            r = [x["latency_s"] for x in rows if x.get("latency_s") is not None][-50:]
            srt = sorted(r)
            return {"n": len(r), "median_s": srt[len(srt) // 2] if srt else None, "p90_s": srt[int(len(srt) * 0.9)] if srt else None,
                    "max_s": max(r) if r else None, "note": note}
        t = now()
        st = {"heartbeat": et(t), "pid": os.getpid(), "uptime_s": int(t - self.stats["started"]),
              "channels": len(chans), "polls": self.stats["polls"], "poll_errors": self.stats["poll_errors"],
              "posts_seen": self.stats["posts_seen"], "alerts_this_run": self.stats["alerts"],
              "alerts_total": self.state["alert_seq"],
              "latency_live_ca_posts": summ([x for x in self.state["latency"] if x.get("has_ca")],
                                            "detect time minus Telegram post time; posts with a CA first seen after the channel's first poll (last 50)"),
              "latency_live_all_posts": summ(self.state["latency"], "same, every new post (last 50)"),
              "per_channel": {c["channel"]: {"label": c.get("label"), "interval_s": sched.get(c["channel"], {}).get("interval"),
                                             "last_poll_et": self.state["channels"].get(c["channel"], {}).get("last_poll_et"),
                                             "last_post_et": self.state["channels"].get(c["channel"], {}).get("last_post_et"),
                                             "last_id": self.state["channels"].get(c["channel"], {}).get("last_id"),
                                             "ok_polls": self.state["channels"].get(c["channel"], {}).get("ok_polls", 0)}
                              for c in chans},
              "private_gap_not_covered": self.cfg.get("private_gap", []),
              "telegram_cooldown_s": round(_http.cooldown_remaining("https://t.me/s/x"), 1),
              "errors": self.errors[-10:]}
        jdump_atomic(os.path.join(D, "status.json"), st)
        jdump_atomic(os.path.join(D, "beat.json"), {"pid": os.getpid(), "wall": t, "et": et(t)})


def interval_for(cfg, cs: dict) -> float:
    lp = (cs or {}).get("last_post_ts")
    hot = lp and now() - lp < cfg["hot_if_posted_within_h"] * 3600
    return cfg["hot_interval_s"] if hot else cfg["cold_interval_s"]


def run(once=False):
    cfg = jload(CFG_PATH, {})
    w = Watcher(cfg)
    chans = load_channels(cfg)
    log(f"tg_watch start pid {os.getpid()} channels={[c['channel'] for c in chans]}")
    sched = {}
    t0 = now()
    for i, c in enumerate(chans):  # stagger first polls
        sched[c["channel"]] = {"due": t0 + i * 2.2, "interval": interval_for(cfg, w.state["channels"].get(c["channel"]))}
    last_status = last_late = last_cfg = 0.0
    done_once = set()
    while not STOP:
        ch = min(sched, key=lambda k: sched[k]["due"])
        wait = sched[ch]["due"] - now()
        if wait > 0:
            if now() - last_status > 10:
                w.status(chans, sched)
                last_status = now()
            time.sleep(min(wait, 5))
            continue
        info = next(c for c in chans if c["channel"] == ch)
        try:
            cands = w.poll_channel(info)
            w.emit(cands)
        except Exception as e:
            w.errors.append(f"{et(now())} {ch}: {type(e).__name__}: {e}")
            log(f"error {ch}: {e!r}")
        iv = interval_for(cfg, w.state["channels"].get(ch))
        sched[ch] = {"due": now() + iv + random.uniform(-cfg["jitter_s"], cfg["jitter_s"]), "interval": iv}
        done_once.add(ch)
        if now() - last_late > 60:
            try:
                w.late_overlaps()
            except Exception as e:
                w.errors.append(f"late_overlaps: {e}")
            last_late = now()
        w.save()
        if now() - last_cfg > 300:  # pick up channel list changes without a restart
            cfg = jload(CFG_PATH, cfg)
            w.cfg = cfg
            nc = load_channels(cfg)
            for c in nc:
                if c["channel"] not in sched:
                    sched[c["channel"]] = {"due": now() + 1, "interval": cfg["cold_interval_s"]}
                    log(f"channel added {c['channel']}")
            for k in [k for k in sched if k not in {c['channel'] for c in nc}]:
                sched.pop(k)
                log(f"channel removed {k}")
            chans = nc
            last_cfg = now()
        if once and done_once >= set(sched):
            break
    w.status(chans, sched)
    w.save()
    log("tg_watch stop")


# ------------------------------------------------------------------ tests
def selftest():
    ign = {"So11111111111111111111111111111111111111112".lower(), "So11111111111111111111111111111111111111112"}
    m = {"text": "━━ EXAMPLE LAB ━━ sample under analysis > ca : MASi45ub7Qe4ZE36UT5G6cU4ud8Fhhe4deS4F3cwpump > token : $TRENCHER mc 40k $SOL",
         "hrefs": ["https://pump.fun/coin/MASi45ub7Qe4ZE36UT5G6cU4ud8Fhhe4deS4F3cwpump", "https://t.me/somebot?start=0xaaaaaa0000000000000000000000000000abcdef"]}
    ex = extract(m, ign, 5)
    assert ex["addrs"] == ["0xaaaaaa0000000000000000000000000000abcdef", "MASi45ub7Qe4ZE36UT5G6cU4ud8Fhhe4deS4F3cwpump"], ex
    assert ex["tickers"] == ["TRENCHER"], ex
    assert not ex["brag"]
    b = extract({"text": "$INK hit 5x from call 🚀 9KTAb8dLcukC7edhDQ7cn5d4gEYkbUrMWeWQLGsCpump", "hrefs": []}, ign, 5)
    assert b["brag"], b
    g = extract({"text": "#GTA6 mrG6dLaYyNoVKf58ZTBqNAYT3j5qcdsyuMNmPfYepump Zone First Call: $132k → Now: $1.1M (8x) ├ Entry: $131,944", "hrefs": []}, ign, 5)
    assert g["brag"], g
    assert extract({"text": "wrapped So11111111111111111111111111111111111111112", "hrefs": []}, ign, 5)["addrs"] == []
    assert extract({"text": "https://x.com/abc/status/1234567890123456789", "hrefs": []}, ign, 5)["addrs"] == []
    page = ('<div class="tgme_widget_message_wrap js-widget_message_wrap"><div class="tgme_widget_message" data-post="chan/42">'
            '<div class="tgme_widget_message_text js-message_text" dir="auto">CA <code>MASi45ub7Qe4ZE36UT5G6cU4ud8Fhhe4deS4F3cwpump</code> &#036;TR</div>'
            '<time datetime="2026-10-18T01:06:47+00:00" class="time">01:06</time></div></div>')
    ps = parse_page(page, "chan")
    assert ps[0]["msg_id"] == 42 and "MASi45" in ps[0]["text"] and "$TR" in ps[0]["text"] and ps[0]["ts"] == 1792285607.0, ps
    print("selftest ok")


def _stop(*_):
    global STOP
    STOP = True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    if a.test:
        selftest()
    else:
        run(once=a.once)
