#!/usr/bin/env python3
"""READ-ONLY flywheel.cash launch + migration watcher (Umbrella Hub generic copy, 2026-10-17). NO trades, signing,
payments, sends or posts. Free sources only: public Robinhood Chain RPC (eth_blockNumber / eth_getLogs / eth_call /
eth_getBlockByNumber), DexScreener + CoinGecko via tools/_http.py, flywheel.cash public indexer API as a fallback.

Every poll_s (default 60 s; fast launches can 10x in 15 min, so a 180-s wallet poll is too slow):
  1. New launches: factory 0xf05a26e9... event TokenCreated(token, creator, quote) [topic 0x8f9d1d4b...], plus the
     site's /api/indexer/v2/tokens list as a fallback when the RPC log call fails.
  2. Every launch younger than track_h is followed with ONE eth_getLogs (Transfer, address = all tracked tokens) and one
     for its quote tokens in/out of the Uniswap V4 PoolManager, so we get swaps, prices and on-chain market cap
     (price = quote into pool / tokens out of pool, x quote USD, x totalSupply).
Alert kinds (flywheel_alerts.jsonl, append-only, one JSON per line, dedupe per token+kind[+wallet]):
  WATCHED_RECEIVE   a watched wallet (wallet_watch config.json robinhood wallets, factory owner, flywheel deployers,
                    extra_watched) receives the coin (buy OR airdrop/transfer). HIGH if >= 0.05% of supply or >= $500.
  CREATOR_LAUNCH_BUY creator took >= 5% of supply in the launch tx (insider concentration). MEDIUM.
  LAUNCH_BY_WATCHED creator is the factory owner (HIGH) or a listed deployer / watched wallet (MEDIUM).
  MIGRATION         one non-pool address sends the coin to >= 50 distinct wallets within 15 min (airdrop/migration).
                    HIGH if the sender was funded by the creator or a watched wallet is a recipient. Lists older
                    same-symbol Robinhood tokens (DexScreener) as migration-source candidates.
  FAST_MC           mcap >= max(fast_min_usd, fast_mult x first post-launch mcap) within fast_window_min, or
                    >= big_mc_usd within big_window_h. HIGH if the coin already has an insider flag above, else MEDIUM.
Files ($FLYWHEEL_DIR or this dir): flywheel_alerts.jsonl, flywheel_state.json, flywheel_status.json, flywheel_beat.json,
flywheel.log; lead IDs shared with wallet_watch (leads.json, protocol.md 6a).
Usage: flywheel_watch.py [--once] | --replay FROM_BLOCK TO_BLOCK [--step-s 60] [--token 0x..]
"""
import json, os, sys, time, signal, fcntl, re, sqlite3, traceback, urllib.request, collections, datetime as D

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.abspath(os.environ.get("FLYWHEEL_DIR") or HERE)
sys.path.insert(0, os.environ.get("UMBRELLA_TOOLS_DIR") or os.path.dirname(HERE))   # dir that holds _http.py
import _http  # noqa: E402

FCFG = json.load(open(os.environ.get("FLYWHEEL_CONFIG") or os.path.join(HERE, "flywheel_config.json")))
WCFG_PATH = os.environ.get("WALLETWATCH_CONFIG") or os.path.join(HERE, "wallets.json")   # optional watched-wallet list (chain=robinhood)
P = {k: os.path.join(DIR, v) for k, v in dict(alerts="flywheel_alerts.jsonl", state="flywheel_state.json", status="flywheel_status.json",
     beat="flywheel_beat.json", log="flywheel.log", leads="leads.json").items()}
DESK_DB = os.environ.get("DESK_DB") or ""   # optional read-only SQLite with [L-YYYYMMDD-NNN] lead IDs; empty = off
TR = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
CREATED = FCFG["created_topic"]
FAC = FCFG["factory"].lower()
PM = FCFG["pool_manager"].lower()
NONUSER = {FAC, PM, FCFG["hook"].lower(), FCFG["fee_router"].lower(), "0x" + "0" * 40} | {a.lower() for a in FCFG.get("routers", [])}
STABLE = {a.lower() for a in FCFG.get("usd_stables", [])}
WETH = FCFG["weth"].lower()
REPLAY = {"on": False, "now": None}


def now():
    return REPLAY["now"] if REPLAY["on"] else time.time()


def et(ts):
    return D.datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds") if ts else None


def load(p, default):
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return default


def save(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, p)


def log(msg):
    with open(P["log"], "a") as f:
        f.write(f"{D.datetime.now().astimezone().strftime('%F %T')} {msg}\n")


def beat(phase):
    save(P["beat"], dict(wall=time.time(), wall_et=et(time.time()), pid=os.getpid(), phase=phase))


def pad(a):
    return "0x" + "0" * 24 + a.lower()[2:]


def a40(t):
    return "0x" + t[-40:].lower()


# ------------------------------------------------------------------ RPC (public, backoff)
def rpc(method, params, tries=5):
    urls, last = FCFG["rh_rpcs"], None
    for k in range(tries):
        u = urls[k % len(urls)]
        try:
            req = urllib.request.Request(u, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                                         headers={"content-type": "application/json", "user-agent": "flywheel-watch/1 (read-only)"})
            d = json.load(urllib.request.urlopen(req, timeout=25))
            if "result" in d:
                return d["result"]
            last = d.get("error")
        except Exception as e:
            last = str(e)[:120]
        time.sleep(min(15, 0.8 * 2 ** k))
    raise RuntimeError(f"rh {method}: {last}")


def get_logs(flt, frm, to):
    """eth_getLogs over [frm, to] with automatic range splitting."""
    out, b, step = [], frm, max(1, to - frm + 1)
    while b <= to:
        e = min(to, b + step - 1)
        try:
            out += rpc("eth_getLogs", [dict(flt, fromBlock=hex(b), toBlock=hex(e))], tries=3)
            b = e + 1
        except RuntimeError:
            if step <= 500:
                raise
            step //= 4
    return out


def call_str(addr, sel):
    try:
        r = rpc("eth_call", [{"to": addr, "data": sel}, "latest"], tries=2)
        b = bytes.fromhex(r[2:])
        return (b[64:64 + int.from_bytes(b[32:64], "big")] if len(b) >= 96 else b.rstrip(b"\0")).decode("utf8", "replace").strip("\0 ")
    except Exception:
        return None


def call_int(addr, sel):
    try:
        return int(rpc("eth_call", [{"to": addr, "data": sel}, "latest"], tries=2), 16)
    except Exception:
        return None


# ------------------------------------------------------------------ prices (free, cached)
_PX = {}


def quote_usd(q):
    q = q.lower()
    if q in STABLE:
        return 1.0
    hit = _PX.get(q)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    v = None
    if q == WETH:
        r = _http.get_json("https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd", cache_ttl=600)
        if r.ok and isinstance(r.data, dict):
            v = (r.data.get("ethereum") or {}).get("usd")
    if v is None:
        r = _http.get_json(f"https://api.dexscreener.com/tokens/v1/robinhood/{q}", cache_ttl=300)
        if r.ok and isinstance(r.data, list) and r.data:
            for p in sorted(r.data, key=lambda x: -((x.get("liquidity") or {}).get("usd") or 0)):
                try:
                    if (p.get("baseToken") or {}).get("address", "").lower() == q:
                        v = float(p["priceUsd"])
                    elif (p.get("quoteToken") or {}).get("address", "").lower() == q and float(p.get("priceNative") or 0) > 0:
                        v = float(p["priceUsd"]) / float(p["priceNative"])
                except (KeyError, TypeError, ValueError):
                    v = None
                if v:
                    break
    if v is None and hit:
        v = hit[1]
    _PX[q] = (time.time(), v)
    return v


def migration_candidates(symbol, token, launch_ts, launches):
    """Older same-symbol Robinhood tokens on DexScreener that are not flywheel launches (possible migration source)."""
    if not symbol:
        return []
    r = _http.get_json(f"https://api.dexscreener.com/latest/dex/search?q={urllib.request.quote(symbol)}", cache_ttl=600)
    if not r.ok or not isinstance(r.data, dict):
        return []
    seen, out = set(), []
    for p in r.data.get("pairs") or []:
        bt = p.get("baseToken") or {}
        a = (bt.get("address") or "").lower()
        if p.get("chainId") != "robinhood" or a == token or a in launches or a in seen:
            continue
        if (bt.get("symbol") or "").upper() != symbol.upper():
            continue
        if (p.get("pairCreatedAt") or 0) / 1000 >= launch_ts:
            continue
        seen.add(a)
        out.append(dict(contract=a, name=bt.get("name"), mcap=p.get("marketCap") or p.get("fdv"), h24=(p.get("priceChange") or {}).get("h24"),
                        pair_created_et=et((p.get("pairCreatedAt") or 0) / 1000), socials=[s.get("url") for s in (p.get("info") or {}).get("socials") or []]))
    return out[:5]


# ------------------------------------------------------------------ lead IDs (same registry/format as watch.py)
def lead_for(contract):
    key = f"robinhood:{contract.lower()}"
    with open(P["leads"] + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        L = load(P["leads"], {"by_contract": {}, "counters": {}})
        if key in L["by_contract"]:
            return L["by_contract"][key]
        found, mx = desk_db_lead(contract)
        if found:
            L["by_contract"][key] = found
            save(P["leads"], L)
            return found
        day = D.datetime.fromtimestamp(now()).astimezone().strftime("%Y%m%d")
        n = max(L["counters"].get(day, 0), mx.get(day, 0)) + 1
        L["counters"][day] = n
        lid = f"L-{day}-{n:03d}"
        L["by_contract"][key] = lid
        save(P["leads"], L)
        return lid


def desk_db_lead(contract):
    found, mx = None, {}
    if os.environ.get("WALLETWATCH_NO_DESKDB") == "1" or not DESK_DB or not os.path.exists(DESK_DB):
        return None, mx
    try:
        c = sqlite3.connect(f"file:{DESK_DB}?mode=ro", uri=True, timeout=5)
        for (t,) in c.execute("select name from sqlite_master where type='table'").fetchall():
            cols = [r[1] for r in c.execute(f"pragma table_info('{t}')")]
            row = " || ' ' || ".join(f"coalesce(cast(\"{x}\" as text),'')" for x in cols)
            for (v,) in c.execute(f"select {row} from \"{t}\" where ({row}) like '%[L-2%'"):
                for d_, n_ in re.findall(r"\[L-(\d{8})-(\d{3})\]", v or ""):
                    mx[d_] = max(mx.get(d_, 0), int(n_))
                if not found and contract.lower() in (v or "").lower():
                    m = re.search(r"\[(L-\d{8}-\d{3})\]", v or "")
                    found = m.group(1) if m else None
        c.close()
    except Exception:
        pass
    return found, mx


# ------------------------------------------------------------------ watcher
class Flywheel:
    def __init__(self):
        self.s = load(P["state"], {})
        for k, v in (("last_block", None), ("launches", {}), ("dedupe", {}), ("alert_seq", 0), ("blockts", {}), ("auto_deployers", {})):
            self.s.setdefault(k, v)
        self.errors = []

    # ---- watch lists
    def watched(self):
        w = {}
        try:
            for x in (json.load(open(WCFG_PATH)).get("wallets", []) if os.path.exists(WCFG_PATH) else []):
                if x.get("chain") == "robinhood":
                    w[x["address"].lower()] = dict(label=f"{x.get('caller')} ({x.get('role')})", grade=x.get("grade"), kind="watched wallet")
        except Exception as e:
            self.errors.append(f"wallet config: {str(e)[:80]}")
        for x in FCFG.get("extra_watched", []):
            w.setdefault(x["address"].lower(), dict(label=x["label"], grade=x.get("grade"), kind="watched wallet"))
        w[FCFG["factory_owner"].lower()] = dict(label="flywheel factory owner/controller", grade="FACT (factory.owner())", kind="factory owner")
        for x in FCFG.get("deployers", []):
            w.setdefault(x["address"].lower(), dict(label=x["label"], grade=x.get("grade", "deployer"), kind="flywheel deployer"))
        for a, lab in self.s["auto_deployers"].items():
            w.setdefault(a, dict(label=lab, grade="auto (creator of a HIGH-alert coin)", kind="flywheel deployer"))
        for a in FCFG.get("ignore", []):
            w.pop(a.lower(), None)
        return w

    # ---- helpers
    def bts(self, blk):
        k = str(blk)
        if k not in self.s["blockts"]:
            self.s["blockts"][k] = int(rpc("eth_getBlockByNumber", [hex(blk), False])["timestamp"], 16)
        return self.s["blockts"][k]

    def alert(self, kind, prio, tok, key_extra="", **kw):
        L = self.s["launches"][tok]
        dk = f"{kind}:{tok}:{key_extra}"
        if dk in self.s["dedupe"]:
            return None
        if not L.get("lead_id"):
            L["lead_id"] = lead_for(tok)
        self.s["alert_seq"] += 1
        rec = dict(ts=et(now()), alert_id=self.s["alert_seq"], kind=kind, priority=prio, notify=prio == "HIGH", dedupe_key=dk,
                   lead_id=L["lead_id"], chain="robinhood", contract=tok, symbol=L.get("symbol"), token_name=L.get("name"),
                   creator=L.get("creator"), quote=L.get("quote_symbol"), launch_time_et=et(L.get("launch_ts")),
                   mcap_usd=round(L["mc"]) if L.get("mc") else None, base_mcap_usd=round(L["base_mc"]) if L.get("base_mc") else None,
                   flags=sorted(L.get("flags", [])), dex_url=f"https://dexscreener.com/robinhood/{tok}", **kw)
        if REPLAY["on"]:
            rec["replay_chain_time_et"] = et(now())
        with open(P["alerts"], "a") as f:
            f.write(json.dumps(rec) + "\n")
        self.s["dedupe"][dk] = rec["ts"]
        L.setdefault("flags", [])
        if kind not in L["flags"]:
            L["flags"].append(kind)
        log(f"ALERT {prio} {kind} {L['lead_id']} {L.get('symbol')} {tok} {kw.get('wallet', '')}")
        if prio == "HIGH" and L.get("creator") and L["creator"] not in self.s["auto_deployers"]:
            self.s["auto_deployers"][L["creator"]] = f"creator of {L.get('symbol')} ({tok[:10]}, HIGH {kind})"
        return rec

    def add_launch(self, tok, creator, quote, blk, tx, ts, meta=None):
        tok = tok.lower()
        if tok in self.s["launches"]:
            return
        meta = meta or {}
        sup = meta.get("supply") or call_int(tok, "0x18160ddd")
        dec = 18
        L = dict(token=tok, creator=creator.lower(), quote=quote.lower(), launch_block=blk, launch_tx=tx, launch_ts=ts,
                 name=meta.get("name") or call_str(tok, "0x06fdde03"), symbol=meta.get("symbol") or call_str(tok, "0x95d89b41"),
                 quote_symbol=meta.get("quote_symbol") or call_str(quote, "0x95d89b41"), supply=(sup or 0) / 10 ** dec,
                 creator_launch_pct=None, base_mc=None, mc=None, peak_mc=None, prices=[], recv={}, senders={}, flags=[], fund={})
        self.s["launches"][tok] = L
        w = self.watched()
        if L["creator"] in w:
            k = w[L["creator"]]
            self.alert("LAUNCH_BY_WATCHED", "HIGH" if k["kind"] == "factory owner" else "MEDIUM", tok,
                       wallet=L["creator"], wallet_label=k["label"], wallet_kind=k["kind"], rule="creator is a watched wallet / factory owner / deployer")

    # ---- core: process one block range
    def process(self, frm, to):
        w = self.watched()
        # 1) launches
        try:
            for l in get_logs({"address": FAC, "topics": [CREATED]}, frm, to):
                blk = int(l["blockNumber"], 16)
                self.add_launch(a40(l["topics"][1]), a40(l["topics"][2]), a40(l["topics"][3]), blk, l["transactionHash"], self.bts(blk))
        except RuntimeError as e:
            self.errors.append(f"factory logs: {str(e)[:100]}")
            if not REPLAY["on"]:
                self.api_fallback()
        # 2) follow tracked launches
        cut = now() - FCFG["track_h"] * 3600
        tracked = [t for t, L in self.s["launches"].items() if (L.get("launch_ts") or 0) >= cut and L["launch_block"] <= to]
        if not tracked:
            return
        tlogs = []
        for i in range(0, len(tracked), 40):
            try:
                tlogs += get_logs({"address": tracked[i:i + 40], "topics": [TR]}, frm, to)
            except RuntimeError as e:
                self.errors.append(f"token logs: {str(e)[:100]}")
        if not tlogs:
            return
        quotes = sorted({self.s["launches"][t]["quote"] for t in tracked})
        txset = {l["transactionHash"] for l in tlogs}
        qlogs = []
        try:
            for side in ([TR, pad(PM)], [TR, None, pad(PM)]):
                qlogs += [l for l in get_logs({"address": quotes, "topics": side}, frm, to) if l["transactionHash"] in txset]
        except RuntimeError as e:
            self.errors.append(f"quote logs: {str(e)[:100]}")
        qby = collections.defaultdict(list)
        for l in qlogs:
            qby[l["transactionHash"]].append(l)
        byt = collections.defaultdict(lambda: collections.defaultdict(list))
        for l in tlogs:
            byt[l["address"].lower()][l["transactionHash"]].append(l)
        for tok, txs in byt.items():
            L = self.s["launches"][tok]
            for txh, ls in sorted(txs.items(), key=lambda kv: (int(kv[1][0]["blockNumber"], 16), int(kv[1][0]["logIndex"], 16))):
                self.handle_tx(L, txh, ls, qby.get(txh, []), w)
            self.check_mc(L)
            self.check_migration(L, w)

    def handle_tx(self, L, txh, ls, ql, w):
        tok, sup = L["token"], L["supply"] or 1
        blk = int(ls[0]["blockNumber"], 16)
        ts = self.bts(blk)
        pm_out = pm_in = 0.0
        moves = []
        for l in ls:
            f, t, v = a40(l["topics"][1]), a40(l["topics"][2]), int(l["data"], 16) / 1e18
            moves.append((f, t, v))
            if f == PM:
                pm_out += v
            if t == PM:
                pm_in += v
        q_in = sum(int(l["data"], 16) / 1e18 for l in ql if l["address"].lower() == L["quote"] and a40(l["topics"][2]) == PM) - \
            sum(int(l["data"], 16) / 1e18 for l in ql if l["address"].lower() == L["quote"] and a40(l["topics"][1]) == PM)
        net = pm_out - pm_in
        is_launch = txh == L["launch_tx"]
        price_mc = None
        if net and q_in and net * q_in > 0:
            qu = quote_usd(L["quote"])
            if qu:
                price_mc = abs(q_in / net) * qu * sup
        if is_launch:
            got = sum(v for f, t, v in moves if f == FAC and t == L["creator"])
            L["creator_launch_pct"] = round(got / sup * 100, 3)
            if got / sup >= FCFG["creator_buy_pct"] / 100:
                L["flags"].append("CREATOR_BIG_BUY")
                self.alert("CREATOR_LAUNCH_BUY", "MEDIUM", tok, pct_supply=L["creator_launch_pct"],
                           rule=f"creator took >= {FCFG['creator_buy_pct']}% of supply in the launch tx",
                           note="insider concentration; >= 20% is a migration/airdrop setup or rug risk" if got / sup >= 0.2 else None,
                           event_time_et=et(ts), tx=txh)
        elif price_mc:
            L["prices"].append([ts, price_mc])
            L["prices"] = L["prices"][-60:]
            if L["base_mc"] is None:
                L["base_mc"], L["base_ts"] = price_mc, ts
            L["mc"], L["mc_ts"] = price_mc, ts
            L["peak_mc"] = max(L.get("peak_mc") or 0, price_mc)
        # recipients / senders (migration + watched)
        swap_tx = pm_out > 0          # pool paid tokens out = a swap; router fan-out inside swaps is not a distribution
        for f, t, v in moves:
            if t not in NONUSER and t != L["creator"] and not swap_tx:
                if f not in NONUSER:
                    s = L["senders"].setdefault(f, {"first_ts": ts, "recips": {}, "amt": 0.0})
                    s["recips"][t] = ts
                    s["amt"] += v
            if f == L["creator"] and t not in NONUSER:
                L["fund"][t] = L["fund"].get(t, 0) + v          # creator -> distributor link
            if t in w and t != L["creator"]:
                k = w[t]
                kind = "buy" if (net > 0 and pm_out > 0) else ("airdrop/transfer" if f not in NONUSER else "receive")
                L["recv"].setdefault(t, 0.0)
                L["recv"][t] += v
                usd = (v / sup) * (L.get("mc") or price_mc or 0) if (L.get("mc") or price_mc) else None
                pct = v / sup * 100
                mc_now = L.get("mc") or price_mc or 0
                prio = "HIGH" if ((usd or 0) >= FCFG["watched_high_usd"] or
                                  (pct >= FCFG["watched_high_pct"] and mc_now >= FCFG.get("watched_high_min_mc", 0))) else "MEDIUM"
                self.alert("WATCHED_RECEIVE", prio, tok, key_extra=t, wallet=t, wallet_label=k["label"], wallet_kind=k["kind"], grade=k.get("grade"),
                           how=kind, from_addr=f, tokens=round(v, 2), pct_supply=round(pct, 4), size_usd_est=round(usd, 2) if usd else None,
                           event_time_et=et(ts), minutes_after_launch=round((ts - L["launch_ts"]) / 60, 1), tx=txh,
                           rule="watched wallet / factory owner / deployer received the coin (buy or airdrop)")

    def insider(self, L):
        return bool({"CREATOR_LAUNCH_BUY", "CREATOR_BIG_BUY", "WATCHED_RECEIVE", "LAUNCH_BY_WATCHED", "MIGRATION"} & set(L.get("flags", [])))

    def check_mc(self, L):
        if not L.get("mc") or not L.get("base_mc"):
            return
        age_min = (L["mc_ts"] - L["launch_ts"]) / 60
        fast = age_min <= FCFG["fast_window_min"] and L["mc"] >= max(FCFG["fast_min_usd"], FCFG["fast_mult"] * L["base_mc"])
        big = age_min <= FCFG["big_window_h"] * 60 and L["mc"] >= FCFG["big_mc_usd"]
        if fast:
            self.alert("FAST_MC", "HIGH" if self.insider(L) else "MEDIUM", L["token"], key_extra="fast",
                       rule=f"mcap {L['mc'] / L['base_mc']:.1f}x first post-launch mcap (>= ${FCFG['fast_min_usd']:,.0f}) within {age_min:.0f} min",
                       growth_x=round(L["mc"] / L["base_mc"], 2), minutes_after_launch=round(age_min, 1), event_time_et=et(L["mc_ts"]),
                       creator_launch_pct=L.get("creator_launch_pct"), note="mcap is on-chain (pool swaps x quote USD x supply); approximate")
        if big:
            self.alert("FAST_MC", "HIGH" if self.insider(L) else "MEDIUM", L["token"], key_extra="big",
                       rule=f"mcap >= ${FCFG['big_mc_usd']:,.0f} within {age_min:.0f} min of launch", growth_x=round(L["mc"] / L["base_mc"], 2),
                       minutes_after_launch=round(age_min, 1), event_time_et=et(L["mc_ts"]), creator_launch_pct=L.get("creator_launch_pct"))

    def check_migration(self, L, w):
        for snd, s in L["senders"].items():
            recent = [t for t, ts in s["recips"].items() if ts - s["first_ts"] <= FCFG["mig_window_min"] * 60]
            if len(recent) < FCFG["mig_min_recipients"]:
                continue
            from_creator = snd == L["creator"] or L["fund"].get(snd, 0) > 0
            watched_r = [t for t in s["recips"] if t in w]
            cands = [] if REPLAY.get("no_http") else migration_candidates(L.get("symbol"), L["token"], L["launch_ts"], self.s["launches"])
            self.alert("MIGRATION", "HIGH" if (from_creator or watched_r) else "MEDIUM", L["token"], key_extra=snd,
                       distributor=snd, funded_by_creator=from_creator, recipients=len(s["recips"]), tokens_sent=round(s["amt"]),
                       pct_supply=round(s["amt"] / (L["supply"] or 1) * 100, 2), event_time_et=et(s["first_ts"]),
                       minutes_after_launch=round((s["first_ts"] - L["launch_ts"]) / 60, 1),
                       watched_recipients=[dict(wallet=t, label=w[t]["label"]) for t in watched_r][:10],
                       migration_source_candidates=cands,
                       rule=f">= {FCFG['mig_min_recipients']} distinct recipients from one address within {FCFG['mig_window_min']} min")

    def api_fallback(self):
        r = _http.get_json(FCFG["api_tokens"], cache_ttl=30)
        if not r.ok or not isinstance(r.data, list):
            self.errors.append(f"flywheel api: {r.status}")
            return
        for t in r.data:
            if (t.get("factory") or "").lower() != FAC:
                continue
            self.add_launch(t["address"], t.get("creator") or "0x" + "0" * 40, t.get("quoteAsset") or WETH, int(t.get("launchBlock") or 0), None,
                            int(t.get("launchTimestamp") or now()), dict(name=t.get("name"), symbol=t.get("symbol"), quote_symbol=t.get("quoteSymbol"),
                                                                         supply=int(t.get("totalSupplyRaw") or 0) or None))

    def prune(self):
        cut = now() - max(FCFG["track_h"], 24) * 3600
        self.s["launches"] = {k: v for k, v in self.s["launches"].items() if (v.get("launch_ts") or 0) >= cut}
        if len(self.s["blockts"]) > 400:
            self.s["blockts"] = dict(list(self.s["blockts"].items())[-150:])

    def poll(self):
        self.errors = []
        t0 = time.time()
        head = int(rpc("eth_blockNumber", []), 16)
        last = self.s["last_block"]
        if last is None:
            last = head - FCFG["first_backfill_blocks"]      # first run: short back-fill so a launch minutes ago is not missed
        frm = last + 1
        while frm <= head:
            to = min(head, frm + FCFG["max_blocks_per_poll"] - 1)
            self.process(frm, to)
            self.s["last_block"] = to
            frm = to + 1
            beat("poll")
        self.prune()
        save(P["state"], self.s)
        tracked = [L for L in self.s["launches"].values() if (L.get("launch_ts") or 0) >= now() - FCFG["track_h"] * 3600]
        st = dict(heartbeat=et(time.time()), pid=os.getpid(), poll_s=FCFG["poll_s"], poll_secs=round(time.time() - t0, 1), last_block=self.s["last_block"],
                  tracked=len(tracked), watched=len(self.watched()), alerts_total=self.s["alert_seq"], errors=self.errors[-10:],
                  top_mc=sorted([dict(symbol=L.get("symbol"), contract=L["token"], mc=round(L["mc"]) if L.get("mc") else None) for L in tracked if L.get("mc")],
                                key=lambda x: -(x["mc"] or 0))[:5])
        save(P["status"], st)
        return st


def replay(frm, to, step_s, only=None):
    REPLAY["on"] = True
    F = Flywheel()
    F.s["last_block"] = frm - 1
    t_from, t_to = F.bts(frm), F.bts(to)
    bps = (to - frm) / max(1, (t_to - t_from))
    step = max(1, int(bps * step_s))
    b = frm
    while b <= to:
        e = min(to, b + step - 1)
        REPLAY["now"] = F.bts(e)
        F.process(b, e)
        F.s["last_block"] = e
        b = e + 1
    save(P["state"], F.s)
    rows = [json.loads(x) for x in open(P["alerts"])] if os.path.exists(P["alerts"]) else []
    if only:
        rows = [r for r in rows if r["contract"] == only.lower()]
    return rows


def main():
    if "--replay" in sys.argv:
        i = sys.argv.index("--replay")
        step = int(sys.argv[sys.argv.index("--step-s") + 1]) if "--step-s" in sys.argv else FCFG["poll_s"]
        only = sys.argv[sys.argv.index("--token") + 1] if "--token" in sys.argv else None
        for r in replay(int(sys.argv[i + 1]), int(sys.argv[i + 2]), step, only):
            print(json.dumps({k: r.get(k) for k in ("replay_chain_time_et", "event_time_et", "priority", "kind", "symbol", "contract", "wallet_label",
                                                     "how", "pct_supply", "mcap_usd", "growth_x", "recipients", "rule")}))
        return
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    F = Flywheel()
    log(f"start pid {os.getpid()} dir {DIR}")
    while True:
        beat("poll")
        try:
            F.poll()
        except Exception:
            log("ERR poll " + traceback.format_exc()[-800:])
            save(P["state"], F.s)
        if "--once" in sys.argv:
            return
        end = time.time() + FCFG["poll_s"]
        while time.time() < end:
            beat("sleep")
            time.sleep(5)


if __name__ == "__main__":
    main()
