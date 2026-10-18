"""sol_data.py - FREE-first rotating Solana data client (read-only).

Why: a keyed provider (e.g. Helius) can hit its monthly cap ('429 max usage reached'). This client spreads calls over every
working free source, with per-provider/per-method adaptive rate buckets, backoff, monthly-cap detection and disk caches.

Providers (RPC, full history unless noted):
  public_beta   https://api.mainnet-beta.solana.com   keyless, sigs ~0.3-0.5/s, getTransaction ~3-5/s, batch ok
  public_main   https://api.mainnet.solana.com        keyless, separate quota from public_beta
  publicnode    https://solana-rpc.publicnode.com     keyless, PRUNED (~1-2 days) -> only used for recent txs/getTokenLargestAccounts
  helius        HELIUS_API_KEY                         used only while not at monthly cap (auto-disabled 6h on 'max usage')
  + any keyed free endpoint listed in $SOL_DATA_ENV (default ./sol_data.env) as SOL_RPC_<NAME>=<url>   (chmod 600, never printed)
Data APIs (keyless): GeckoTerminal token info (holders count + top10/20/40 distribution), Jupiter datapi (holderCount,
  topHoldersPercentage, dev, devFundedAt), DexScreener pairs.

NOTE: transactions use maxSupportedTransactionVersion=1 (v1 txs exist; =0 returns error -32015 for them).

API:
  rpc(method, params, kind=None)            -> (result, err)
  signatures(addr, max_pages=5, until_ts=None) -> dict(sigs=[[sig,blockTime,failed],...] newest first, exhausted, pages, err)
  get_txs(sigs)                              -> ({sig: tx}, missing)
  first_funder(addr, max_pages=40)           -> dict(funder, sig, ts, amt, status)
  wallet_history(addr, days=90, max_txs=4000)-> dict(txs=[...], coverage, n_in_window, ...)
  realized_pnl(addr, days=90, ...)           -> dict(realized_usd, realized_sol (SOL-equiv), win_rate, closed, fees, ...)
                                               (2026-10-17c: pnl_multi engine, every quote currency; was SOL-only)
  token_holders(mint)                        -> dict(count, top10_pct, largest=[...], sources)
  txs_for_address(...)                       -> Helius getTransactionsForAddress-compatible shim (rows, token, err)
CLI: python3 sol_data.py status | selftest | funder <addr> | pnl <addr> | holders <mint>
"""
from __future__ import annotations
import json, os, sys, time, threading, urllib.request, urllib.error, random
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.environ.get('SOL_DATA_CACHE', os.path.join(HERE, 'data', 'sol_cache'))
ENV_FILE = os.environ.get('SOL_DATA_ENV', os.path.join(HERE, 'sol_data.env'))   # chmod 600; never commit, never print
STATS_FILE = os.path.join(HERE, 'data', 'sol_data_stats.json')
EXTRA_TX_CACHES = [p for p in os.environ.get('SOL_DATA_EXTRA_TX_CACHES', '').split(':') if p]     # optional read-only seeds
EXTRA_SIG_CACHES = [p for p in os.environ.get('SOL_DATA_EXTRA_SIG_CACHES', '').split(':') if p]
os.makedirs(CACHE + '/tx', exist_ok=True); os.makedirs(CACHE + '/sigs', exist_ok=True); os.makedirs(CACHE + '/misc', exist_ok=True)
UA = 'Mozilla/5.0 (sol_data research read-only)'
LK = threading.Lock()

def _load_env():
    env = {}
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1); env[k.strip()] = v.strip().strip('"\'')
    return env
ENV = _load_env()

class Provider:
    def __init__(self, name, url, sig_rate, tx_rate, batch=True, full_history=True, headers=None, monthly_cap=None):
        self.name, self.url, self.batch, self.full = name, url, batch, full_history
        self.headers = headers or {}
        self.b = {'sig': {'rate': sig_rate, 'next': 0.0, 'strike': 0, 'max': sig_rate},
                  'tx': {'rate': tx_rate, 'next': 0.0, 'strike': 0, 'max': tx_rate},
                  'misc': {'rate': max(tx_rate, 1.0), 'next': 0.0, 'strike': 0, 'max': max(tx_rate, 1.0)}}
        self.disabled_until = 0.0; self.disabled_why = ''
        self.cu_rate = 0.0  # >0: provider meters throughput in compute units/s (Alchemy free: 300 CU/s account-wide)
        self.gtfa = False   # supports Helius-style getTransactionsForAddress (Alchemy free does; 100 CU / up to 1000 full txs)
        self.calls = 0; self.n429 = 0; self.errs = 0
    def usable(self, kind, need_full):
        if kind == 'gtfa' and (not self.gtfa or 'gtfa' not in self.b): return False
        return time.time() >= self.disabled_until and (self.full or not need_full) and self.b[kind]['rate'] > 0

def _providers():
    P = [Provider('public_beta', 'https://api.mainnet-beta.solana.com', 0.3, 3.0),
         Provider('public_main', 'https://api.mainnet.solana.com', 0.3, 3.0),
         Provider('publicnode', 'https://solana-rpc.publicnode.com', 2.0, 5.0, full_history=False)]
    hk = os.environ.get('HELIUS_API_KEY') or ENV.get('HELIUS_API_KEY')
    if hk and os.environ.get('SOL_DATA_NO_HELIUS') != '1':
        P.append(Provider('helius', 'https://mainnet.helius-rpc.com/?api-key=' + hk, 5.0, 5.0)); P[-1].gtfa = True
    for k, v in sorted(ENV.items()):
        if k.startswith('SOL_RPC_') and v.startswith('http'):
            nm = k[8:].lower()
            rate = float(ENV.get('SOL_RATE_' + k[8:], '5'))
            srate = float(ENV.get('SOL_SIGRATE_' + k[8:], str(max(0.5, rate / 4))))
            full = ENV.get('SOL_FULL_' + k[8:], '1') == '1'
            P.append(Provider(nm, v, srate, rate, batch=ENV.get('SOL_BATCH_' + k[8:], '1') == '1', full_history=full))
            P[-1].gtfa = ENV.get('SOL_GTFA_' + k[8:], '1' if 'alchemy' in v else '0') == '1'
            P[-1].cu_rate = float(ENV.get('SOL_CUPS_' + k[8:], '270' if 'alchemy' in v else '0'))
            P[-1].b['gtfa'] = {'rate': float(ENV.get('SOL_GTFARATE_' + k[8:], '3')), 'next': 0.0, 'strike': 0, 'max': float(ENV.get('SOL_GTFARATE_' + k[8:], '3'))}
    return P
PROVIDERS = _providers()
for _p in PROVIDERS:
    if _p.gtfa and 'gtfa' not in _p.b: _p.b['gtfa'] = {'rate': 2.0, 'next': 0.0, 'strike': 0, 'max': 2.0}
def gtfa_available(): return any(p.usable('gtfa', True) for p in PROVIDERS)
STATS = {'calls': 0, '429': 0, 'cache_tx_hits': 0, 'retried_ok': 0}

# Cross-process cooldowns: every process on the box (watcher, deep-dive, Rug Shield) shares one IP, so a 429 seen by one
# process is written here and respected by all for a short time. Format {provider|kind: until_ts}. Helius cap marker too.
COOL_FILE = os.path.join(HERE, 'data', 'sol_data_cooldowns.json')
HELIUS_CAP_FILE = os.path.join(HERE, 'data', 'helius_capped.json')
_COOL = {'t': 0.0, 'd': {}}
def _shared_cool():
    if time.time() - _COOL['t'] > 1.0:
        try: _COOL['d'] = json.load(open(COOL_FILE))
        except Exception: _COOL['d'] = {}
        _COOL['t'] = time.time()
    return _COOL['d']
def _set_shared_cool(name, kind, until):
    try:
        d = _shared_cool(); now = time.time()
        d = {k: v for k, v in d.items() if v > now}
        d[f'{name}|{kind}'] = max(until, d.get(f'{name}|{kind}', 0))
        tmp = COOL_FILE + f'.{os.getpid()}'; json.dump(d, open(tmp, 'w')); os.replace(tmp, COOL_FILE); _COOL['d'] = d
    except Exception: pass
def helius_capped_until():
    try: return float(json.load(open(HELIUS_CAP_FILE)).get('until', 0))
    except Exception: return 0.0
def mark_helius_capped(why='max usage reached', hours=6):
    try: json.dump({'until': time.time() + hours * 3600, 'why': why[:100], 'set_et': time.strftime('%Y-%m-%d %H:%M:%S')}, open(HELIUS_CAP_FILE, 'w'))
    except Exception: pass
for _p in PROVIDERS:
    if _p.name == 'helius' and helius_capped_until() > time.time():
        _p.disabled_until = helius_capped_until(); _p.disabled_why = 'helius monthly cap (shared marker)'

# Box-wide pacing: all processes reserve request slots from one shared schedule (fcntl-locked file), so the watcher,
# deep-dive scripts and Rug Shield together stay under each provider's per-IP / per-key rate instead of each process
# pacing alone and colliding (that collision is what produced ~8 of every 32 requests as 429).
import fcntl
SLOT_FILE = os.path.join(HERE, 'data', 'sol_data_slots.json')
def _reserve_shared(name, kind, rate, units, earliest):
    """Reserve `units` at `rate`/s on the box-wide schedule. Returns the start time of our slot (may be in the future)."""
    try:
        fd = os.open(SLOT_FILE, os.O_RDWR | os.O_CREAT, 0o644)
        with os.fdopen(fd, 'r+') as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try: d = json.loads(fh.read() or '{}')
            except ValueError: d = {}
            k = f'{name}|{kind}'; now = time.time()
            start = max(now, earliest, d.get(k, 0))
            d[k] = start + units / max(rate, 0.01)
            fh.seek(0); fh.truncate(); fh.write(json.dumps({kk: v for kk, v in d.items() if v > now - 60}))
            fcntl.flock(fh, fcntl.LOCK_UN)
            return start
    except Exception:
        return max(time.time(), earliest)

CU_COST = {'sig': 40, 'tx': 40, 'gtfa': 100, 'misc': 40}   # Alchemy Solana CU table (getBlock 40, getSlot 20, largest 20)
def _acquire(kind, units=1, need_full=True, exclude=()):
    p = _acquire_local(kind, units, need_full, exclude)
    if p is None: return None
    b = p.b[kind]
    start = _reserve_shared(p.name, kind, b['rate'], units, time.time())
    if p.cu_rate > 0:   # one box-wide CU budget for every method on this provider
        start = max(start, _reserve_shared(p.name, 'cu', p.cu_rate, CU_COST.get(kind, 40) * units, time.time()))
    w = start - time.time()
    if w > 0: time.sleep(min(w, 30))
    return p

def _acquire_local(kind, units=1, need_full=True, exclude=()):
    chosen = None
    while True:
        with LK:
            now = time.time()
            sc = _shared_cool()
            cands = [p for p in PROVIDERS if p.usable(kind, need_full) and p.name not in exclude and sc.get(f'{p.name}|{kind}', 0) <= now]
            if not cands and kind == 'gtfa' and not any(p.usable('gtfa', True) for p in PROVIDERS): return None
            if not cands:
                if exclude: exclude = (); continue
                rel = [p for p in PROVIDERS if (p.full or not need_full) and (kind != 'gtfa' or p.gtfa)]
                soon = min([max(p.disabled_until, sc.get(f'{p.name}|{kind}', 0), p.b.get(kind, {}).get('next', 0)) for p in rel] or [now + 60])
                w = max(1.0, min(60.0, soon - now))
            else:
                ready = [x for x in cands if x.b[kind]['next'] <= now]
                p = max(ready, key=lambda x: (x.b[kind]['rate'], -x.b[kind]['strike'])) if ready else min(cands, key=lambda x: x.b[kind]['next'])
                b = p.b[kind]
                if b['next'] <= now:
                    b['next'] = max(b['next'], now) + units / b['rate']
                    chosen = p; break
                w = b['next'] - now
        time.sleep(min(w, 2.0))
    return chosen

def _penalize(p, kind, msg=''):
    with LK:
        b = p.b[kind]; b['strike'] += 1; p.n429 += 1; STATS['429'] += 1
        b['rate'] = max(b['max'] * 0.15, b['rate'] * 0.7)
        b['next'] = max(b['next'], time.time() + min(60, 2 * 2 ** min(b['strike'], 5)) * (0.5 + random.random()))
        m = msg.lower()
        if 'max usage' in m or 'monthly' in m or 'quota' in m or 'credits' in m or 'capacity limit' in m:
            p.disabled_until = time.time() + 6 * 3600; p.disabled_why = msg[:100]
            if p.name == 'helius': mark_helius_capped(msg)
    _set_shared_cool(p.name, kind, time.time() + min(30, 1.5 * 2 ** min(b['strike'], 4)))

def _reward(p, kind):
    with LK:
        b = p.b[kind]; b['strike'] = 0; b['rate'] = min(b['max'], b['rate'] * 1.03 + 0.01)

def _post(p, body, timeout=40):
    h = {'content-type': 'application/json', 'user-agent': UA}; h.update(p.headers)
    r = urllib.request.urlopen(urllib.request.Request(p.url, json.dumps(body).encode(), h), timeout=timeout).read()
    p.calls += 1; STATS['calls'] += 1
    return json.loads(r)

def _kind(method):
    return 'sig' if method == 'getSignaturesForAddress' else ('tx' if method == 'getTransaction' else 'misc')

def _gsfa_via_gtfa(params):
    """getSignaturesForAddress(addr, {limit, until}) via gTFA signatures mode (same item format). On Alchemy free the
    native getSignaturesForAddress 429s even at ~1 req/s while gTFA does not (measured 2026-10-17 ~8:20 PM ET)."""
    addr = params[0]; o = params[1] if len(params) > 1 and isinstance(params[1], dict) else {}
    if o.get('before') or not gtfa_available(): return None
    limit = int(o.get('limit') or 1000); until = o.get('until')
    r, err = gtfa(addr, {'transactionDetails': 'signatures', 'sortOrder': 'desc', 'limit': min(limit, 1000)}, tries=4)
    if r is None: return None
    out = []
    for x in r.get('data') or []:
        if until and x.get('signature') == until: break
        out.append(x)
    return out

def rpc(method, params, tries=12, need_full=True, kind=None):
    if method == 'getSignaturesForAddress' and os.environ.get('SOL_DATA_NO_GTFA_SIGS') != '1':
        res = _gsfa_via_gtfa(params)
        if res is not None: return res, ''
    kind = kind or _kind(method); last = ''
    for _ in range(tries):
        p = _acquire(kind, 1, need_full)
        try:
            d = _post(p, {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
        except urllib.error.HTTPError as e:
            body = ''
            try: body = e.read()[:300].decode('utf8', 'replace')
            except Exception: pass
            last = f'{p.name} HTTP {e.code} {body[:80]}'
            if e.code in (429, 503, 403, 402, 401): _penalize(p, kind, body)
            if e.code in (401, 403, 402): p.disabled_until = time.time() + 3600; p.disabled_why = last
            continue
        except Exception as e:
            last = f'{p.name} {str(e)[:80]}'; p.errs += 1; _penalize(p, kind); continue
        if 'result' in d:
            _reward(p, kind); return d['result'], ''
        err = str(d.get('error'))
        if '429' in err or 'Too many' in err or 'rate' in err.lower() or 'max usage' in err:
            _penalize(p, kind, err); last = p.name + ' ' + err[:80]; continue
        if 'cleaned' in err or 'not available' in err or 'pruned' in err.lower():
            last = p.name + ' ' + err[:80]; continue           # pruned node: try another provider
        return None, f'{p.name} {err[:160]}'
    return None, last or 'exhausted retries'

# ---------------------------------------------------------------- signatures (paged, resumable)
def _sig_path(a): return f'{CACHE}/sigs/{a}.json'
def _load_sigs(a):
    for p in [_sig_path(a)] + [f'{d}/{a}.json' for d in EXTRA_SIG_CACHES]:
        if os.path.exists(p):
            try:
                c = json.load(open(p))
                if c.get('sigs') is not None:
                    c.setdefault('before', c['sigs'][-1][0] if c['sigs'] and not c.get('exhausted') else None); return c
            except Exception: pass
    return None

def signatures(addr, max_pages=5, until_ts=None, refresh=False):
    """Newest-first signature list; pages of 1000; resumes from cache. until_ts: stop once a page reaches older than it."""
    c = None if refresh else _load_sigs(addr)
    if c is None: c = {'addr': addr, 'sigs': [], 'exhausted': False, 'pages': 0, 'err': '', 'before': None, 'fetched': time.time()}
    def done():
        if c['exhausted'] or c['pages'] >= max_pages: return True
        if until_ts and c['sigs'] and (c['sigs'][-1][1] or 9e18) < until_ts: return True
        return False
    changed = False
    while not done() and gtfa_available() and (not c.get('before') or c.get('gtoken')) and os.environ.get('SOL_DATA_NO_GTFA_SIGS') != '1':
        cfg = {'transactionDetails': 'signatures', 'sortOrder': 'desc', 'limit': 1000}
        if c.get('gtoken'): cfg['paginationToken'] = c['gtoken']
        r, err = gtfa(addr, cfg)
        if r is None: c['err'] = err; break
        data = r.get('data') or []
        c['err'] = ''; c['pages'] += 1; changed = True
        c['sigs'] += [[x['signature'], x.get('blockTime'), bool(x.get('err'))] for x in data]
        c['gtoken'] = r.get('paginationToken')
        if not c['gtoken'] or not data: c['exhausted'] = True; c['before'] = None; break
        c['before'] = data[-1]['signature']
        if c['pages'] % 10 == 0: json.dump(c, open(_sig_path(addr), 'w'))
    while not done():
        prm = {'limit': 1000}
        if c.get('before'): prm['before'] = c['before']
        r, err = rpc('getSignaturesForAddress', [addr, prm])
        if r is None: c['err'] = err; break
        c['err'] = ''; c['pages'] += 1; changed = True
        c['sigs'] += [[x['signature'], x.get('blockTime'), bool(x.get('err'))] for x in r]
        if len(r) < 1000: c['exhausted'] = True; c['before'] = None; break
        c['before'] = r[-1]['signature']
        if c['pages'] % 10 == 0: json.dump(c, open(_sig_path(addr), 'w'))
    if changed or not os.path.exists(_sig_path(addr)): json.dump(c, open(_sig_path(addr), 'w'))
    return c

# ---------------------------------------------------------------- transactions (batched, cached)
def _tx_cached(s):
    for d in [CACHE + '/tx'] + EXTRA_TX_CACHES:
        p = f'{d}/{s}.json'
        if os.path.exists(p):
            try: return json.load(open(p))
            except Exception: return None
    return None

def get_txs(sigs, rounds=12, batch=10):
    out, todo = {}, []
    for s in sigs:
        t = _tx_cached(s)
        if t: out[s] = t; STATS['cache_tx_hits'] += 1
        else: todo.append(s)
    from concurrent.futures import ThreadPoolExecutor
    def do_chunk(ch):
        p = _acquire('tx', len(ch), True)
        cfg = {'encoding': 'json', 'maxSupportedTransactionVersion': 1, 'commitment': 'confirmed'}
        try:
            if p.batch and len(ch) > 1:
                d = _post(p, [{'jsonrpc': '2.0', 'id': i, 'method': 'getTransaction', 'params': [s, cfg]} for i, s in enumerate(ch)])
            else:
                d = [dict(_post(p, {'jsonrpc': '2.0', 'id': 0, 'method': 'getTransaction', 'params': [ch[0], cfg]}), id=0)]
        except urllib.error.HTTPError as e:
            body = ''
            try: body = e.read()[:200].decode('utf8', 'replace')
            except Exception: pass
            _penalize(p, 'tx', body)
            if e.code in (401, 403, 402): p.disabled_until = time.time() + 3600; p.disabled_why = f'HTTP {e.code} {body[:60]}'
            return ch
        except Exception:
            p.errs += 1; _penalize(p, 'tx'); return ch
        if not isinstance(d, list): _penalize(p, 'tx', str(d)[:200]); return ch
        got = {x.get('id'): x for x in d}; miss = []; bad = 0
        for i, s in enumerate(ch):
            x = got.get(i) or {}
            if x.get('result'):
                out[s] = x['result']; json.dump(x['result'], open(f'{CACHE}/tx/{s}.json', 'w'))
            else:
                miss.append(s); bad += 1 if 'error' in x else 0
        if bad: _penalize(p, 'tx', str([got.get(i, {}).get('error') for i in range(len(ch))][:1]))
        else: _reward(p, 'tx')
        return miss
    nw = max(1, sum(1 for p in PROVIDERS if p.full and time.time() >= p.disabled_until))
    for rnd in range(rounds):
        if not todo: break
        chunks = [todo[k:k + batch] for k in range(0, len(todo), batch)]
        with ThreadPoolExecutor(min(nw * 2, 8)) as ex: res = list(ex.map(do_chunk, chunks))
        todo = [s for m in res for s in m]
        if todo: time.sleep(min(20, 1.5 * 2 ** rnd))
    return out, todo

def _keys(tx):
    msg = (tx.get('transaction') or {}).get('message') or {}
    keys = [k if isinstance(k, str) else k.get('pubkey') for k in msg.get('accountKeys') or []]
    la = (tx.get('meta') or {}).get('loadedAddresses') or {}
    return keys + list(la.get('writable') or []) + list(la.get('readonly') or [])

def funder_from(a, txs_sorted):
    """First tx (oldest first) where `a` gains lamports and another account loses them: funder = largest SOL sender."""
    for tx in txs_sorted:
        k = _keys(tx); m = tx.get('meta') or {}
        if m.get('err') is not None or a not in k: continue
        pre, post = m.get('preBalances') or [], m.get('postBalances') or []
        i = k.index(a)
        if i < len(post) and post[i] - pre[i] > 0:
            dl = [(post[j] - pre[j], k[j]) for j in range(min(len(k), len(post))) if k[j] != a]
            neg = min(dl) if dl else (0, None)
            if neg[0] < 0:
                return {'funder': neg[1], 'sig': ((tx.get('transaction') or {}).get('signatures') or [None])[0],
                        'ts': tx.get('blockTime'), 'amt': (post[i] - pre[i]) / 1e9}
    return None

# ---------------------------------------------------------------- getTransactionsForAddress (Helius-style; Alchemy free supports it)
def gtfa(addr, cfg, tries=10):
    """-> (result dict {'data':[...], 'paginationToken':...} or None, err). err 'no gtfa provider' when none usable."""
    last = ''
    cfg = dict(cfg)
    if cfg.get('transactionDetails') == 'full': cfg['maxSupportedTransactionVersion'] = 1
    for _ in range(tries):
        p = _acquire('gtfa', 1, True)
        if p is None: return None, 'no gtfa provider'
        try:
            d = _post(p, {'jsonrpc': '2.0', 'id': 1, 'method': 'getTransactionsForAddress', 'params': [addr, cfg]}, timeout=90)
        except urllib.error.HTTPError as e:
            bd = ''
            try: bd = e.read()[:300].decode('utf8', 'replace')
            except Exception: pass
            last = f'{p.name} HTTP {e.code} {bd[:80]}'; _penalize(p, 'gtfa', bd)
            if e.code in (401, 402, 403): p.disabled_until = time.time() + 3600; p.disabled_why = last
            continue
        except Exception as e:
            last = f'{p.name} {str(e)[:80]}'; p.errs += 1; _penalize(p, 'gtfa'); continue
        if 'result' in d: _reward(p, 'gtfa'); return d['result'] or {}, ''
        err = str(d.get('error'))
        if '429' in err or 'Too many' in err or 'rate' in err.lower() or 'max usage' in err or 'capacity' in err:
            _penalize(p, 'gtfa', err); last = p.name + ' ' + err[:80]; continue
        if 'not found' in err.lower() or 'not supported' in err.lower() or '-32601' in err:
            p.gtfa = False; last = p.name + ' ' + err[:80]; continue
        return None, p.name + ' ' + err[:160]
    return None, last or 'gtfa retries exhausted'

def gtfa_pages(addr, *, sort='desc', since=None, max_pages=5, limit=1000, token_filter=None, full=True):
    """All succeeded txs (full) via gTFA pages. -> (txs, complete, err)"""
    cfg = {'transactionDetails': 'full' if full else 'signatures', 'sortOrder': sort, 'limit': limit, 'filters': {'status': 'succeeded'}}
    if full: cfg.update(encoding='json', maxSupportedTransactionVersion=1)
    if since: cfg['filters']['blockTime'] = {'gte': int(since)}
    if token_filter: cfg['filters']['tokenAccounts'] = token_filter
    rows, tok = [], None
    for _ in range(max_pages):
        if tok: cfg['paginationToken'] = tok
        r, err = gtfa(addr, dict(cfg))
        if r is None: return rows, False, err
        rows += r.get('data') or []; tok = r.get('paginationToken')
        if not tok or not r.get('data'): return rows, True, ''
    return rows, False, ''

# ---------------------------------------------------------------- oldest-signature seek (no full pagination)
# getSignaturesForAddress accepts ANY signature as `before` (it is resolved to its slot), so we binary-search slots
# using one signature from a block at that slot. ~20-30 cheap probes instead of hundreds of 1000-sig pages for bot wallets.
_BLK = {}
def _sig_at_slot(slot):
    for k in range(0, 40, 4):
        s = slot + k
        if s in _BLK: return _BLK[s]
        r, e = rpc('getBlock', [s, {'maxSupportedTransactionVersion': 1, 'transactionDetails': 'signatures', 'rewards': False, 'commitment': 'finalized'}], tries=6, kind='misc')
        if r and r.get('signatures'):
            _BLK[s] = (r['signatures'][0], r.get('blockTime')); return _BLK[s]
    return None, None

def oldest_signatures(addr, max_probes=40):
    """-> dict(sigs=[[sig,blockTime,failed],...] newest-first (the oldest <1000 sigs of the address), exhausted=True, probes, err)"""
    p = f'{CACHE}/misc/oldest_{addr}.json'
    if os.path.exists(p): return json.load(open(p))
    cur, e = rpc('getSlot', [{'commitment': 'finalized'}], kind='misc')
    if not cur: return {'sigs': [], 'exhausted': False, 'err': 'getSlot failed ' + e}
    lo, hi = 1, int(cur)          # invariant: no sigs before lo-slot block (n==0) ; >=1000 sigs before hi
    c = _load_sigs(addr)
    if c and c['sigs'] and not c['exhausted']: pass
    for i in range(max_probes):
        mid = (lo + hi) // 2
        sig, bt = _sig_at_slot(mid)
        if not sig: lo = mid + 1; continue
        r, err = rpc('getSignaturesForAddress', [addr, {'limit': 1000, 'before': sig}])
        if r is None: return {'sigs': [], 'exhausted': False, 'err': err, 'probes': i + 1}
        if 0 < len(r) < 1000:
            out = {'sigs': [[x['signature'], x.get('blockTime'), bool(x.get('err'))] for x in r], 'exhausted': True, 'probes': i + 1, 'err': '', 'method': 'slot-seek'}
            json.dump(out, open(p, 'w')); return out
        if len(r) == 0: lo = mid + 1
        else: hi = mid
        if hi - lo < 50: break
    return {'sigs': [], 'exhausted': False, 'err': 'seek did not converge (%d probes)' % max_probes}

def first_funder(addr, max_pages=40, n_oldest=8, n_more=30, seek_after_pages=3):
    if gtfa_available():
        rows, complete, err = gtfa_pages(addr, sort='asc', max_pages=1, limit=40)
        if not err:
            if not rows: return {'funder': None, 'status': 'UNKNOWN: no successful txs', 'n_sigs': 0}
            f = funder_from(addr, rows)
            if f: return f | {'status': 'FACT: resolved (gTFA asc)', 'first_ts': rows[0].get('blockTime'), 'n_sigs': '>=%d' % len(rows)}
            if complete: return {'funder': None, 'status': 'UNKNOWN: all %d txs show no inbound SOL from another account' % len(rows), 'first_ts': rows[0].get('blockTime')}
            rows2, _, err2 = gtfa_pages(addr, sort='asc', max_pages=1, limit=300)
            f = funder_from(addr, rows2) if rows2 else None
            if f: return f | {'status': 'FACT: resolved (gTFA asc)', 'first_ts': rows2[0].get('blockTime'), 'n_sigs': '>=%d' % len(rows2)}
            return {'funder': None, 'status': 'UNKNOWN: oldest %d txs show no inbound SOL from another account' % len(rows2 or rows), 'first_ts': rows[0].get('blockTime')}
    c = signatures(addr, max_pages=min(max_pages, seek_after_pages))
    if not c['exhausted']:
        o = oldest_signatures(addr)
        if o.get('exhausted'): c = {'sigs': o['sigs'], 'exhausted': True, 'pages': c['pages'], 'err': '', 'seek': True}
    if not c['exhausted'] and max_pages > seek_after_pages:
        c = signatures(addr, max_pages=max_pages)
    if not c['exhausted']:
        why = c['err'][:100] if c['err'] else f'>{len(c["sigs"])} sigs ({c["pages"]} pages); oldest tx not reached within page budget'
        return {'funder': None, 'status': 'UNKNOWN: ' + why, 'n_sigs': len(c['sigs'])}
    ok = [s for s in c['sigs'] if not s[2]]
    if not ok: return {'funder': None, 'status': 'UNKNOWN: no successful txs', 'n_sigs': len(c['sigs'])}
    old = sorted(ok, key=lambda s: (s[1] or 0))[:n_oldest]
    txs, miss = get_txs([s[0] for s in old])
    f = funder_from(addr, sorted(txs.values(), key=lambda t: (t.get('blockTime') or 0, t.get('slot') or 0)))
    if not f and not miss and len(ok) > n_oldest:
        more = sorted(ok, key=lambda s: (s[1] or 0))[n_oldest:n_oldest + n_more]
        t2, miss = get_txs([s[0] for s in more]); txs.update(t2)
        f = funder_from(addr, sorted(txs.values(), key=lambda t: (t.get('blockTime') or 0, t.get('slot') or 0)))
    if f: return f | {'status': 'FACT: resolved' + (' (slot-seek)' if c.get('seek') else ''), 'first_ts': old[0][1], 'n_sigs': len(c['sigs']) if not c.get('seek') else '>%d' % (c['pages'] * 1000)}
    if miss: return {'funder': None, 'status': f'UNKNOWN: {len(miss)} oldest txs not fetchable (rate limits)', 'n_sigs': len(c['sigs'])}
    return {'funder': None, 'status': f'UNKNOWN: oldest {len(old)} txs show no inbound SOL from another account', 'n_sigs': len(c['sigs']), 'first_ts': old[0][1]}

def wallet_history(addr, days=90, max_txs=4000, sample=150, max_pages=None):
    now = time.time(); since = now - days * 86400
    if gtfa_available():
        pages = max(1, -(-max_txs // 1000))
        rows, complete, err = gtfa_pages(addr, sort='desc', since=since, max_pages=pages, token_filter='balanceChanged')
        if not err:
            ws = since if complete else min([t.get('blockTime') for t in rows if t.get('blockTime')], default=None)
            cov = 'FULL_%dD' % days if complete else 'LATEST_%d_TXS (window has more; truncated at %s)' % (len(rows), time.strftime('%Y-%m-%d %H:%M', time.localtime(ws)) if ws else '?')
            return {'addr': addr, 'txs': rows, 'missing': [], 'coverage': cov, 'n_in_window': len(rows) if complete else '>%d' % len(rows),
                    'window_start': ws, 'sig_err': '', 'source': 'gTFA (token-balance-changing txs)'}
    c = signatures(addr, max_pages=max_pages or max(5, max_txs // 1000 + 1), until_ts=since)
    ok = [s for s in c['sigs'] if not s[2]]
    in_w = [s for s in ok if (s[1] or 0) >= since]
    reached = c['exhausted'] or any((s[1] or now) < since for s in c['sigs'])
    if reached and len(in_w) <= max_txs: use, cov = in_w, 'FULL_%dD' % days
    else: use, cov = in_w[:sample], 'SAMPLE_LATEST_%d_TXS (window has >%d txs)' % (min(sample, len(in_w)), len(in_w))
    txs, miss = get_txs([s[0] for s in use])
    ws = since if cov.startswith('FULL') else (min([s[1] for s in use if s[1]], default=None))
    return {'addr': addr, 'txs': list(txs.values()), 'missing': miss, 'coverage': cov, 'n_in_window': len(in_w) if reached else '>%d' % len(in_w),
            'window_start': ws, 'sig_err': c['err']}

def realized_pnl(addr, days=90, max_txs=4000, sample=150, study_mints=(), gt_budget=8):
    sys.path.insert(0, HERE)
    try: import smart_money as sm          # optional (deploy-tx counter); not shipped in the hub copy
    except ImportError: sm = None
    h = wallet_history(addr, days, max_txs, sample)
    use_n = len(h['txs']) + len(h['missing'])
    if use_n and len(h['missing']) > 0.05 * use_n:
        return {'status': 'UNKNOWN: %d/%d txs not fetchable (rate limits)' % (len(h['missing']), use_n), 'coverage': h['coverage']}
    if not use_n:
        if h['sig_err']: return {'status': 'UNKNOWN: ' + h['sig_err'][:100], 'coverage': h['coverage']}
        return {'status': 'FACT: no successful txs in window', 'coverage': h['coverage'], 'win_start': h['window_start'], 'n_in_window': 0, 'parsed': 0,
                'closed': 0, 'realized_sol': 0, 'win_rate': None, 'best_share': None, 'n_coins': 0, 'open': 0, 'deploys': 0, 'median_hold_s': None, 'study_sol': 0, 'skill': False}
    # 2026-10-17c: multi-quote engine (pnl_multi). Old path (sm.classify with sol_usd=None) dropped every USDC/USDT-settled
    # trade; now SOL/wSOL/USDC/USDT/other stables and token-for-token swaps all count, priced in USD at trade time
    # (Coinbase hourly SOL, stables $1, GeckoTerminal OHLCV for token-for-token), fees included. Backup: sol_data.py.bak-2026-10-17c
    import pnl_multi as PM
    dep = sum(1 for tx in h['txs'] if sm.is_deploy_tx(tx, addr)) if sm else None
    L, st = PM.realized_from_txs(h['txs'], addr, period_start=0, gt_budget=gt_budget)
    cyc = [c for c in L.cycles if c['period']]
    full = h['coverage'].startswith('FULL')
    study = set(study_mints)
    open_pos = {m: {'qty': p['qty'], 'cost_usd': p['cost']} for m, p in L.pos.items() if p['qty'] > 1e-9 and p['cost'] > 0}
    return {'status': 'DERIVED: computed (multi-quote USD)' + (' (%d txs missing)' % len(h['missing']) if h['missing'] else ''), 'coverage': h['coverage'],
            'win_start': h['window_start'], 'n_in_window': h['n_in_window'], 'parsed': len(h['txs']), 'swaps': st['swaps'], 'closed': st['closed'],
            'realized_sol': st['realized_sol_equiv'], 'realized_usd': st['realized_usd'], 'win_rate': st['win_rate'], 'best_share': st['best_share'],
            'n_coins': st['n_coins'], 'open': st['open'], 'deploys': dep, 'median_hold_s': st['median_hold_s'],
            'study_sol': round(sum(t['realized'] / (PM.SOLPX.at(t['ts']) or 1) for t in L.trades if t['side'] == 'sell' and t['mint'] in study), 3),
            'fee_network_usd': st['fee_network_usd'], 'fee_app_usd': st['fee_app_usd'], 'no_basis_proceeds_usd': st['no_basis_proceeds_usd'],
            'token_swaps': st['token_swaps'], 'unpriced_swaps': st['unpriced_swaps'], 'flags': st['flags'], 'open_positions': open_pos,
            'quote_mix': quote_mix(L), 'method': 'pnl_multi avg-cost USD; all quotes; fees inside cash legs',
            'skill': bool(full and len(cyc) >= 15 and (st['win_rate'] or 0) >= 0.5 and st['realized_usd'] > 0 and (st['best_share'] or 1) <= 0.6)}

def quote_mix(L):
    """Count of trades by how they were priced (cash_buy/cash_sell = SOL or stable legs; token_swap = token-for-token)."""
    c = {}
    for t in L.trades:
        if t['side'] in ('buy', 'sell'): k = t['how'].split(':')[0]; c[k] = c.get(k, 0) + 1
    return c

# ---------------------------------------------------------------- holders + market data (keyless HTTP APIs)
_HTTP_NEXT = {}
def http_json(url, min_gap=1.0, tries=4, headers=None):
    host = url.split('/')[2]
    for i in range(tries):
        with LK:
            w = _HTTP_NEXT.get(host, 0) - time.time(); _HTTP_NEXT[host] = max(time.time(), _HTTP_NEXT.get(host, 0)) + min_gap
        if w > 0: time.sleep(w)
        try:
            h = {'user-agent': UA, 'accept': 'application/json'}; h.update(headers or {})
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=25).read()), ''
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(5 * 2 ** i); continue
            return None, f'HTTP {e.code}'
        except Exception as e:
            time.sleep(2); last = str(e)[:80]
    return None, 'retries exhausted'

def token_holders(mint, largest=True):
    p = f'{CACHE}/misc/holders_{mint}.json'
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < 6 * 3600: return json.load(open(p))
    out = {'mint': mint, 'count': None, 'sources': []}
    d, e = http_json(f'https://api.geckoterminal.com/api/v2/networks/solana/tokens/{mint}/info', 2.1)
    if d:
        hh = ((d.get('data') or {}).get('attributes') or {}).get('holders') or {}
        if hh.get('count'): out['count'] = hh['count']; out['gt_distribution_pct'] = hh.get('distribution_percentage'); out['sources'].append('geckoterminal')
    d, e = http_json(f'https://datapi.jup.ag/v1/assets/search?query={mint}', 0.5)
    if d and isinstance(d, list):
        t = next((x for x in d if x.get('id') == mint), None)
        if t:
            out['jup_holder_count'] = t.get('holderCount'); out['dev'] = t.get('dev'); a = t.get('audit') or {}
            out['top_holders_pct'] = a.get('topHoldersPercentage'); out['dev_funded_at'] = a.get('devFundedAt'); out['sources'].append('jupiter_datapi')
            out['count'] = out['count'] or t.get('holderCount')
    if largest:
        r, err = rpc('getTokenLargestAccounts', [mint], need_full=False)
        if r: out['largest_token_accounts'] = [{'account': x['address'], 'ui': x.get('uiAmount')} for x in (r.get('value') or [])]; out['sources'].append('rpc getTokenLargestAccounts')
    out['fetched'] = time.time(); json.dump(out, open(p, 'w')); return out

def dexscreener_pairs(mint):
    d, e = http_json(f'https://api.dexscreener.com/tokens/v1/solana/{mint}', 0.25); return d or []

# ---------------------------------------------------------------- Helius gTFA-compatible shim
def txs_for_address(addr, *, full=True, sort='desc', limit=1000, filters=None, token=None, max_cooldown_wait=0.0, max_pages=40):
    """Emulates Helius getTransactionsForAddress (succeeded txs only). token = offset index as str."""
    if gtfa_available():
        cfg = {'transactionDetails': 'full' if full else 'signatures', 'sortOrder': sort, 'limit': limit, 'filters': dict(filters or {})}
        cfg['filters'].setdefault('status', 'succeeded')
        if full: cfg.update(encoding='json', maxSupportedTransactionVersion=1)
        if token: cfg['paginationToken'] = token
        r, err = gtfa(addr, cfg)
        if r is not None: return r.get('data') or [], r.get('paginationToken'), ''
        if err != 'no gtfa provider': return [], None, err
    since = ((filters or {}).get('blockTime') or {}).get('gte')
    if sort == 'asc':
        c = signatures(addr, max_pages=max_pages)
        if not c['exhausted']: return [], None, c['err'] or f'oldest not reachable (> {len(c["sigs"])} sigs)'
        ok = [s for s in reversed(c['sigs']) if not s[2]]
    else:
        c = signatures(addr, max_pages=max_pages, until_ts=since)
        ok = [s for s in c['sigs'] if not s[2]]
    if since: ok = [s for s in ok if (s[1] or 0) >= since]
    off = int(token or 0); page = ok[off:off + limit]
    nxt = str(off + limit) if off + limit < len(ok) else None
    if not full: return [{'signature': s[0], 'blockTime': s[1]} for s in page], nxt, ''
    txs, miss = get_txs([s[0] for s in page])
    if miss: return [txs[s[0]] for s in page if s[0] in txs], None, f'{len(miss)} txs not fetchable (rate limits)'
    return [txs[s[0]] for s in page], nxt, ''

def status():
    return {'providers': [{'name': p.name, 'full_history': p.full, 'batch': p.batch, 'calls': p.calls, '429': p.n429, 'errs': p.errs,
                           'sig_rate': round(p.b['sig']['rate'], 3), 'tx_rate': round(p.b['tx']['rate'], 3),
                           'disabled_for_s': max(0, int(p.disabled_until - time.time())), 'why': p.disabled_why[:80]} for p in PROVIDERS],
            'stats': STATS, 'env_file': ENV_FILE if os.path.exists(ENV_FILE) else None}

def save_stats():
    try: json.dump(status() | {'ts': time.time()}, open(STATS_FILE, 'w'), indent=1)
    except Exception: pass

if __name__ == '__main__':
    a = sys.argv[1:] or ['status']
    if a[0] == 'status': print(json.dumps(status(), indent=1))
    elif a[0] == 'funder': print(json.dumps(first_funder(a[1]), indent=1))
    elif a[0] == 'pnl': print(json.dumps(realized_pnl(a[1]), indent=1))
    elif a[0] == 'holders': print(json.dumps(token_holders(a[1]), indent=1))
    elif a[0] == 'selftest':
        # usage: sol_data.py selftest <ANY_PUBLIC_WALLET> <ANY_TOKEN_MINT>
        if len(a) < 3: sys.exit('usage: sol_data.py selftest <ANY_PUBLIC_WALLET> <ANY_TOKEN_MINT>')
        t0 = time.time(); w = a[1]
        print('funder', first_funder(w, max_pages=3)); print('holders', {k: v for k, v in token_holders(a[2]).items() if k != 'largest_token_accounts'})
        print(json.dumps(status(), indent=1)); print('elapsed', round(time.time() - t0, 1))
    save_stats()

# ---------------------------------------------------------------- raw JSON-RPC passthrough (drop-in for scripts' own post())
def _fix_version(b):
    if isinstance(b, dict) and b.get('method') == 'getTransaction' and len(b.get('params') or []) > 1 and isinstance(b['params'][1], dict):
        b['params'][1]['maxSupportedTransactionVersion'] = 1
    return b

def raw(body, tries=12):
    """Send a JSON-RPC body (dict or batch list) through the rotation. Returns the parsed response
    (dict or list); on failure returns {'error': '...'} like the old per-script post() helpers."""
    batch = isinstance(body, list)
    body = [_fix_version(dict(b)) for b in body] if batch else _fix_version(dict(body))
    method = (body[0] if batch else body).get('method', '')
    kind = _kind(method); units = len(body) if batch else 1; last = ''
    for _ in range(tries):
        p = _acquire(kind, units, method not in ('getTokenLargestAccounts', 'getSlot', 'getAccountInfo', 'getBalance', 'getTokenSupply'))
        if batch and not p.batch: 
            out = []
            for b in body:
                r = raw(b, tries); out.append(r if 'id' in r else dict(r, id=b.get('id')))
            return out
        try:
            d = _post(p, body)
        except urllib.error.HTTPError as e:
            bd = ''
            try: bd = e.read()[:300].decode('utf8', 'replace')
            except Exception: pass
            last = f'{p.name} HTTP {e.code}'; _penalize(p, kind, bd)
            if e.code in (401, 402, 403): p.disabled_until = time.time() + 3600; p.disabled_why = last + ' ' + bd[:60]
            continue
        except Exception as e:
            last = f'{p.name} {str(e)[:80]}'; p.errs += 1; _penalize(p, kind); continue
        if batch:
            if not isinstance(d, list): _penalize(p, kind, str(d)[:200]); last = str(d)[:100]; continue
            errs = [x for x in d if 'error' in x]
            if errs and any(('429' in str(x['error']) or 'Too many' in str(x['error'])) for x in errs): _penalize(p, kind, str(errs[0])[:200])
            else: _reward(p, kind)
            return d
        err = str(d.get('error', ''))
        if 'error' in d and ('429' in err or 'Too many' in err or 'rate' in err.lower() or 'max usage' in err):
            _penalize(p, kind, err); last = p.name + ' ' + err[:80]; continue
        if 'error' in d and ('cleaned' in err or 'pruned' in err.lower()): last = err[:80]; continue
        _reward(p, kind); return d
    return {'error': last or 'retries exhausted'}


# ---------------------------------------------------------------- optional: make a smart_money.py module use this client
def install_smart_money_transport(sm=None):
    """Point smart_money's Helius transport (sm.RPC) at sol_data: gTFA -> Alchemy/Helius rotation, everything else -> RPC rotation."""
    if sm is None:
        sys.path.insert(0, HERE); import smart_money as sm
    sys.path.insert(0, HERE); from _http import Resp
    def _rpc(method, params, timeout=30.0):
        if method == 'getTransactionsForAddress':
            r, err = gtfa(params[0], dict(params[1]) if len(params) > 1 else {})
            if r is None and err == 'no gtfa provider':
                cfg = params[1] if len(params) > 1 else {}
                rows, tok, err = txs_for_address(params[0], full=cfg.get('transactionDetails') == 'full', sort=cfg.get('sortOrder', 'desc'),
                                                 limit=cfg.get('limit', 1000), filters=cfg.get('filters'), token=cfg.get('paginationToken'))
                r = None if err else {'data': rows, 'paginationToken': tok}
            return Resp(r is not None, 200 if r is not None else 429, data={'result': r} if r is not None else None, error=err or '')
        res, err = rpc(method, params)
        return Resp(res is not None or not err, 200 if not err else 429, data={'result': res}, error=err or '')
    sm.RPC = _rpc
    return sm
