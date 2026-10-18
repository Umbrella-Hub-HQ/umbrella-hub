"""pnl_multi.py - multi-quote wallet PnL engine (read-only). Built 2026-10-17 ET.

Why: the old path (smart_money.classify, used by sol_data.realized_pnl) only counted SOL/wSOL-quoted swaps and dropped any
trade settled in USDC/USDT (sol_usd=None -> skipped). many trading apps settle in USDC (Solana) and USDG/WETH (Robinhood Chain), so
those trades vanished.

What this does
  * Every tx -> per-asset balance deltas for the wallet (Solana: lamports + SPL/Token-2022 by owner; EVM: ERC-20 Transfer logs).
  * Cash legs priced in USD at trade time: SOL/wSOL and ETH/WETH = Coinbase hourly close (keyless); stablecoins = $1.
    Cash legs: SOL, wSOL, USDC, USDT, USD1, PYUSD, USDS, USDG, FDUSD, USDe, DAI, USDbC, ETH, WETH (per chain).
  * Token legs: single token vs cash -> buy/sell at the cash value. Token-for-token -> booked at the given-up leg's USD
    value when this wallet has its own cash fill of that token within 1 h at a comparable size (<=5x); otherwise the cost
    basis carries over to the received token (realized only when it is later sold for cash). GeckoTerminal hourly OHLCV
    is used only to split cash across several tokens bought/sold in one tx, never to mint profit on illiquid blocks.
  * Several tokens vs cash -> cash split by market value at that hour; tokens with no value (rewards/dust) get $0 basis.
  * Fees: already inside the cash deltas (network fee when the wallet pays it, ATA rent, app/platform fees taken from the
    wallet's stablecoin). Reported separately: fee_network_usd (meta.fee / gasUsed*price when wallet paid) and
    fee_app_usd (stablecoin received by known app fee wallets in the same tx).
  * Average-cost ledger in USD per asset. Realized = proceeds - avg cost of qty sold. Sells with no tracked basis are kept
    apart (no_basis_*), never counted as profit. Unrealized = open qty x current price (Jupiter lite price v3 ->
    DexScreener -> GeckoTerminal) - remaining cost.
  * Closed cycles (position falls to <=1% of peak) give hit rate / hold time, same rule as smart_money.round_trips.
Never signs, sends or trades. HTTP is GET or read-only JSON-RPC. No secrets read or printed.
"""
from __future__ import annotations
import json, os, time, bisect, threading, urllib.request, urllib.error, datetime as _dt

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'data', 'pnl_multi'); os.makedirs(CACHE, exist_ok=True)
UA = 'Mozilla/5.0 (pnl_multi research read-only)'
LK = threading.Lock()

# ------------------------------------------------------------------------------------------------ assets
SOL_NATIVE = 'SOL'
WSOL = 'So11111111111111111111111111111111111111112'
SOL_STABLES = {
    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': 'USDC', 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB': 'USDT',
    'USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB': 'USD1', '2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo': 'PYUSD',
    'USDSwr9ApdHk5bvJKMjzff41FfuX8bSxdKcR81vTwcA': 'USDS', '2u1tszSeqZ3qBWF3uNGPFc8TzMk2tdiwknnRMWGWjGWH': 'USDG',
    '9zNQRsGLjNKwCUU5Gq5LR8beUCPzQMVMqKAi3SSZh54u': 'FDUSD', 'DEkqHyPN7GMRJ5cArtQFAWefqbZb33Hyf6s5iCwjEonT': 'USDe',
}
EVM_CASH = {   # chain -> {lowercase address: (symbol, kind)}   kind: 'usd' (=1) or 'eth' (ETH price)
    'robinhood': {'0x5fc5360d0400a0fd4f2af552add042d716f1d168': ('USDG', 'usd'), '0x0bd7d308f8e1639fab988df18a8011f41eacad73': ('WETH', 'eth'),
                  'native': ('ETH', 'eth')},
    'base': {'0x833589fcd6edb6e08f4c7c32d4f71b54bda02913': ('USDC', 'usd'), '0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca': ('USDbC', 'usd'),
             '0xfde4c96c8593536e31f229ea8f37b2ada2699bb2': ('USDT', 'usd'), '0x50c5725949a6f0c72e6c4a641f24049a917db0cb': ('DAI', 'usd'),
             '0x4200000000000000000000000000000000000006': ('WETH', 'eth'), 'native': ('ETH', 'eth')},
}
# app fee wallets: stablecoin received by these in a trade tx = app fee
APP_FEE_WALLETS = {}   # optional: {'<APP_FEE_WALLET_ADDRESS>': '<APP NAME>'} for app fee wallets YOU verified on-chain
EPS = 1e-12

# ------------------------------------------------------------------------------------------------ HTTP
_NEXT: dict = {}
def http_json(url, min_gap=0.6, tries=5, data=None, timeout=40):
    host = url.split('/')[2]
    for i in range(tries):
        with LK:
            w = _NEXT.get(host, 0) - time.time()
            _NEXT[host] = max(time.time(), _NEXT.get(host, 0)) + min_gap
        if w > 0: time.sleep(w)
        try:
            req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                         headers={'User-Agent': UA, 'Accept': 'application/json', 'Content-Type': 'application/json'})
            return json.load(urllib.request.urlopen(req, timeout=timeout))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504, 520, 522, 524): time.sleep(min(60, 3 * 2 ** i)); continue
            return None
        except Exception:
            time.sleep(2 * (i + 1))
    return None

def _jload(p, d):
    try: return json.load(open(p))
    except Exception: return d
def _jsave(p, o):
    tmp = p + '.%d' % os.getpid(); json.dump(o, open(tmp, 'w')); os.replace(tmp, p)

# ------------------------------------------------------------------------------------------------ USD prices at trade time
class Hourly:
    """Coinbase hourly close (keyless). product e.g. SOL-USD / ETH-USD. Cached on disk, extended on demand."""
    def __init__(self, product):
        self.product = product; self.path = f'{CACHE}/cb_{product}.json'
        self.d = {int(k): v for k, v in _jload(self.path, {}).items()}; self.keys = sorted(self.d)
    def _fetch(self, t0, t1):
        t = t0 - t0 % 3600
        while t < t1:
            e = min(t + 299 * 3600, t1 + 3600)
            f = lambda x: _dt.datetime.fromtimestamp(x, _dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            r = http_json(f'https://api.exchange.coinbase.com/products/{self.product}/candles?granularity=3600&start={f(t)}&end={f(e)}', min_gap=0.4)
            for c in r or []: self.d[int(c[0])] = float(c[4])
            t = e
        self.keys = sorted(self.d)
        with LK: _jsave(self.path, {str(k): v for k, v in self.d.items()})
    def ensure(self, t0, t1):
        t1 = min(t1, time.time())
        if not self.keys or self.keys[0] > t0 - 3600 or self.keys[-1] < t1 - 7200:
            lo = t0 if not self.keys or self.keys[0] > t0 - 3600 else self.keys[-1]
            self._fetch(int(lo) - 3600, int(t1))
    def at(self, ts):
        if not self.keys or ts > self.keys[-1] + 7200 or ts < self.keys[0] - 3600: self.ensure(ts - 86400, ts + 3600)
        if not self.keys: return None
        h = int(ts) - int(ts) % 3600; i = bisect.bisect_right(self.keys, h) - 1
        return self.d[self.keys[max(i, 0)]]

SOLPX = Hourly('SOL-USD'); ETHPX = Hourly('ETH-USD')

# GeckoTerminal historical token price (hourly close), used only for token-for-token legs
GT_NET = {'solana': 'solana', 'robinhood': 'robinhood', 'base': 'base'}
_GTP = _jload(f'{CACHE}/gt_pool.json', {}); _GTO = _jload(f'{CACHE}/gt_ohlcv.json', {})
def gt_price_at(chain, token, ts):
    key = f'{chain}:{token}:{int(ts) // 3600}'
    if key in _GTO: return _GTO[key]
    pk = f'{chain}:{token}'
    if pk not in _GTP:
        r = http_json(f'https://api.geckoterminal.com/api/v2/networks/{GT_NET.get(chain, chain)}/tokens/{token}/pools?page=1', min_gap=2.2)
        pools = [(p.get('attributes') or {}).get('address') for p in (r or {}).get('data') or []]
        _GTP[pk] = pools[0] if pools else None
        with LK: _jsave(f'{CACHE}/gt_pool.json', _GTP)
    pool = _GTP.get(pk); px = None
    if pool:
        r = http_json(f'https://api.geckoterminal.com/api/v2/networks/{GT_NET.get(chain, chain)}/pools/{pool}/ohlcv/hour?aggregate=1'
                      f'&before_timestamp={int(ts) + 3600}&limit=3&currency=usd&token={token}', min_gap=2.2)
        rows = (((r or {}).get('data') or {}).get('attributes') or {}).get('ohlcv_list') or []
        if rows:
            best = min(rows, key=lambda c: abs(c[0] - ts)); px = float(best[4]) if abs(best[0] - ts) < 3 * 3600 else None
    _GTO[key] = px
    with LK: _jsave(f'{CACHE}/gt_ohlcv.json', _GTO)
    return px

# current prices (for unrealized)
def current_prices(chain, tokens):
    out = {}; toks = [t for t in dict.fromkeys(tokens) if t]
    if chain == 'solana':
        for i in range(0, len(toks), 50):
            r = http_json('https://lite-api.jup.ag/price/v3?ids=' + ','.join(toks[i:i + 50]), min_gap=1.1) or {}
            for k, v in r.items():
                if isinstance(v, dict) and v.get('usdPrice') is not None: out[k] = (float(v['usdPrice']), 'jupiter_price_v3', v.get('liquidity'))
    rest = [t for t in toks if t not in out]
    for i in range(0, len(rest), 30):
        r = http_json(f'https://api.dexscreener.com/tokens/v1/{chain}/' + ','.join(rest[i:i + 30]), min_gap=1.0) or []
        best = {}
        for p in r if isinstance(r, list) else []:
            a = (p.get('baseToken') or {}).get('address'); liq = (p.get('liquidity') or {}).get('usd') or 0
            if a and p.get('priceUsd') and liq >= best.get(a.lower() if chain != 'solana' else a, (0, 0))[1]:
                best[a.lower() if chain != 'solana' else a] = (float(p['priceUsd']), liq)
        for t in rest[i:i + 30]:
            b = best.get(t.lower() if chain != 'solana' else t)
            if b: out[t] = (b[0], 'dexscreener', b[1])
    for t in [t for t in toks if t not in out][:40]:
        r = http_json(f'https://api.geckoterminal.com/api/v2/simple/networks/{GT_NET.get(chain, chain)}/token_price/{t}', min_gap=2.2) or {}
        v = (((r.get('data') or {}).get('attributes') or {}).get('token_prices') or {})
        v = v.get(t) or v.get(t.lower())
        if v: out[t] = (float(v), 'geckoterminal', None)
    return out

# ------------------------------------------------------------------------------------------------ events
# event = {'id','ts','chain','legs':{asset:qty}, 'fee_net_usd', 'fee_app_usd', 'signer':bool}
def _keys(tx):
    msg = (tx.get('transaction') or {}).get('message') or {}
    ks = [k if isinstance(k, str) else k.get('pubkey') for k in msg.get('accountKeys') or []]
    la = (tx.get('meta') or {}).get('loadedAddresses') or {}
    return ks + list(la.get('writable') or []) + list(la.get('readonly') or [])
def _ui(b):
    ta = b.get('uiTokenAmount') or {}
    try: return float(ta.get('uiAmountString') if ta.get('uiAmountString') is not None else (ta.get('uiAmount') or 0))
    except (TypeError, ValueError): return 0.0
def _owner_deltas(meta, owner=None):
    out = {}
    for sign, arr in ((-1, meta.get('preTokenBalances') or []), (1, meta.get('postTokenBalances') or [])):
        for b in arr:
            o = b.get('owner'); m = b.get('mint')
            if not m or (owner and o != owner): continue
            k = m if owner else (o, m); out[k] = out.get(k, 0.0) + sign * _ui(b)
    return out

def sol_event(tx, wallet):
    """Solana tx (json encoding) -> event or None (failed tx / wallet absent)."""
    meta = tx.get('meta') or {}
    if meta.get('err') is not None: return None
    ks = _keys(tx)
    if wallet not in ks: return None
    idx = ks.index(wallet)
    hdr = ((tx.get('transaction') or {}).get('message') or {}).get('header') or {}
    signer = idx < int(hdr.get('numRequiredSignatures') or 1)
    pre, post = meta.get('preBalances') or [], meta.get('postBalances') or []
    lam = (post[idx] - pre[idx]) / 1e9 if idx < len(pre) and idx < len(post) else 0.0
    legs = {k: v for k, v in _owner_deltas(meta, wallet).items() if abs(v) > EPS}
    sol = lam + legs.pop(WSOL, 0.0)
    if abs(sol) > 1e-9: legs[SOL_NATIVE] = sol
    ts = tx.get('blockTime') or 0
    fee_net = (meta.get('fee') or 0) / 1e9 if idx == 0 else 0.0
    app = 0.0
    if any(m in SOL_STABLES for m in legs):
        allo = _owner_deltas(meta)
        app = sum(v for (o, m), v in allo.items() if o in APP_FEE_WALLETS and m in SOL_STABLES and v > 0)
    sig = ((tx.get('transaction') or {}).get('signatures') or [''])[0]
    return {'id': sig, 'ts': ts, 'slot': tx.get('slot') or 0, 'chain': 'solana', 'legs': legs, 'signer': signer,
            'fee_net_native': fee_net, 'fee_app_usd': app}

def evm_events(chain, wallet, logs, decimals, tx_meta=None):
    """ERC-20 Transfer logs touching wallet -> events grouped by tx hash. decimals {token: int}; tx_meta {hash: {ts, from,
    gas_native, value_native}} (gas_native = gasUsed*effectiveGasPrice/1e18 when wallet sent the tx)."""
    w = wallet.lower(); by = {}
    for lg in logs:
        t = lg['address'].lower(); tp = lg['topics']
        if len(tp) < 3: continue
        fr = '0x' + tp[1][-40:]; to = '0x' + tp[2][-40:]
        v = int(lg['data'], 16) if lg.get('data') not in (None, '0x') else 0
        q = v / 10 ** decimals.get(t, 18)
        e = by.setdefault(lg['transactionHash'], {'legs': {}, 'block': int(lg['blockNumber'], 16), 'li': int(lg.get('logIndex', '0x0'), 16)})
        if to == w: e['legs'][t] = e['legs'].get(t, 0) + q
        if fr == w: e['legs'][t] = e['legs'].get(t, 0) - q
    out = []
    for h, e in by.items():
        m = (tx_meta or {}).get(h, {})
        legs = {k: v for k, v in e['legs'].items() if abs(v) > EPS}
        if m.get('value_native'): legs['native'] = legs.get('native', 0) + m['value_native']
        out.append({'id': h, 'ts': m.get('ts', 0), 'slot': e['block'], 'chain': chain, 'legs': legs,
                    # EVM: relayers / EIP-7702 / permits mean tx.from is often not the wallet. Wallet sent tokens -> its own action.
                    'signer': (m.get('from') or '').lower() == w or any(v < 0 for v in legs.values()), 'fee_net_native': m.get('gas_native', 0.0), 'fee_app_usd': 0.0})
    return out

# ------------------------------------------------------------------------------------------------ pricing of legs
def cash_px(chain, asset, ts):
    """USD price of a cash asset at ts, or None if asset is not cash."""
    if chain == 'solana':
        if asset in (SOL_NATIVE, WSOL): return SOLPX.at(ts)
        if asset in SOL_STABLES: return 1.0
        return None
    c = EVM_CASH.get(chain, {}).get(asset.lower() if asset != 'native' else 'native')
    if not c: return None
    return 1.0 if c[1] == 'usd' else ETHPX.at(ts)
def native_px(chain, ts): return SOLPX.at(ts) if chain == 'solana' else ETHPX.at(ts)
def asset_sym(chain, a):
    if chain == 'solana': return 'SOL' if a in (SOL_NATIVE, WSOL) else SOL_STABLES.get(a)
    c = EVM_CASH.get(chain, {}).get(a.lower() if a != 'native' else 'native'); return c[0] if c else None

# ------------------------------------------------------------------------------------------------ ledger
class Ledger:
    def __init__(self, chain, gt_budget=60):
        self.chain = chain; self.pos = {}; self.trades = []; self.cycles = []; self.flags = {}; self.gt_budget = gt_budget
        self.fee_net_usd = 0.0; self.fee_app_usd = 0.0; self.cash_flows = []; self.last_px = {}  # mint -> [(ts, px)]
    def flag(self, k, n=1): self.flags[k] = self.flags.get(k, 0) + n
    def _p(self, m):
        return self.pos.setdefault(m, {'qty': 0.0, 'cost': 0.0, 'peak': 0.0, 't0': None, 'cyc_real': 0.0, 'cyc_cost': 0.0,
                                       'cyc_n': 0, 'realized': 0.0, 'bought_usd': 0.0, 'sold_usd': 0.0, 'nb_qty': 0.0, 'nb_usd': 0.0, 'free_qty': 0.0})
    def _implied(self, m, ts, qty=None):
        """Price from this wallet's own cash fill of m within 1 h. With qty: only if qty <= 5x that fill's size (a spot fill
        does not price a much larger block, e.g. a deployer's supply going into an LP)."""
        arr = [x for x in (self.last_px.get(m) or []) if abs(x[0] - ts) <= 3600]
        if qty is not None: arr = [x for x in arr if qty <= 5 * x[2]]
        best = min(arr, key=lambda x: abs(x[0] - ts), default=None)
        return best[1] if best else None
    def price_token(self, m, ts, qty=None, allow_gt=True):
        px = self._implied(m, ts, qty)
        if px is not None: return px, 'implied_own_trade'
        if allow_gt and self.gt_budget > 0:
            self.gt_budget -= 1; px = gt_price_at(self.chain, m, ts)
            if px is not None: return px, 'geckoterminal_ohlcv'
        return None, None
    def buy(self, m, q, usd, ts, sig, how, period=True):
        p = self._p(m)
        if p['qty'] <= 1e-9 * max(p['peak'], 1e-30): p['t0'] = ts; p['peak'] = 0.0; p['cyc_real'] = 0.0; p['cyc_cost'] = 0.0; p['cyc_n'] = 0
        p['qty'] += q; p['cost'] += usd; p['peak'] = max(p['peak'], p['qty']); p['cyc_cost'] += usd; p['cyc_n'] += 1
        if usd == 0: p['free_qty'] += q
        p['bought_usd'] += usd if period else 0
        if usd > 0 and q > 0 and 'token_swap' not in how: self.last_px.setdefault(m, []).append((ts, usd / q, q))
        self.trades.append({'ts': ts, 'sig': sig, 'mint': m, 'side': 'buy' if (usd > 0 or 'zero_cost' not in how) else 'inflow', 'qty': q, 'usd': usd,
                            'how': how, 'realized': 0.0, 'period': period})
    def sell(self, m, q, usd, ts, sig, how, period=True):
        p = self._p(m)
        if q > 0 and usd > 0 and 'token_swap' not in how: self.last_px.setdefault(m, []).append((ts, usd / q, q))
        have = max(p['qty'], 0.0); matched = min(q, have); frac = matched / q if q else 0
        basis = p['cost'] * (matched / have) if have > 0 else 0.0
        proceeds = usd * frac; real = proceeds - basis
        p['qty'] -= matched; p['cost'] -= basis
        if p['free_qty']: p['free_qty'] = max(0.0, p['free_qty'] - matched)
        if period: p['realized'] += real; p['sold_usd'] += proceeds
        p['cyc_real'] += real; p['cyc_n'] += 1
        if q - matched > 1e-9 * q:
            p['nb_qty'] += q - matched
            if period: p['nb_usd'] += usd * (1 - frac)
            self.flag('sell_without_tracked_basis')
        self.trades.append({'ts': ts, 'sig': sig, 'mint': m, 'side': 'sell', 'qty': q, 'usd': usd, 'how': how, 'realized': real,
                            'no_basis_usd': usd * (1 - frac), 'period': period})
        if matched > 0 and p['peak'] > 0 and p['qty'] <= 0.01 * p['peak']:
            if p['cyc_cost'] > 0:
                self.cycles.append({'mint': m, 'cost': p['cyc_cost'], 'pnl': p['cyc_real'], 't0': p['t0'], 't1': ts,
                                    'hold_s': max(0, ts - (p['t0'] or ts)), 'legs': p['cyc_n'], 'period': period})
            p['qty'] = 0.0; p['cost'] = 0.0; p['peak'] = 0.0; p['free_qty'] = 0.0
    def transfer_out(self, m, q, ts, sig):
        p = self._p(m); have = max(p['qty'], 0.0); matched = min(q, have)
        if have > 0: p['cost'] -= p['cost'] * matched / have
        p['qty'] -= matched; self.flag('token_transfer_out')
        self.trades.append({'ts': ts, 'sig': sig, 'mint': m, 'side': 'transfer_out', 'qty': q, 'usd': 0.0, 'how': 'no cash leg', 'realized': 0.0})

    def apply(self, ev, period=True):
        ch = self.chain; ts = ev['ts']; legs = ev['legs']
        cash_usd = 0.0; toks = {}; ctypes = set()
        for a, q in legs.items():
            px = cash_px(ch, a, ts)
            if px is None: toks[a] = q
            else:
                cash_usd += q * px
                if abs(q * px) >= 0.01: ctypes.add('stable' if px == 1.0 else ('sol' if ch == 'solana' else 'eth'))
        qt = '[' + '+'.join(sorted(ctypes)) + ']' if ctypes else ''
        npx = native_px(ch, ts) or 0
        fee_net = ev.get('fee_net_native', 0.0) * npx
        if period: self.fee_net_usd += fee_net; self.fee_app_usd += ev.get('fee_app_usd', 0.0)
        sig = ev['id']
        if not toks:
            if abs(cash_usd) > 0.01: self.cash_flows.append((ts, sig, cash_usd))
            return 'cash_only'
        if not ev.get('signer', True):
            # wallet did not sign: airdrop / someone else's transfer -> zero-cost inflow, never a trade
            # Kept OUT of the tracked position (cost unknown: could be the wallet's own funds moved from another wallet);
            # if later sold, those sells land in no_basis_* and never count as profit. Same rule as the old SOL-only path.
            for m, q in toks.items():
                if q > 0:
                    self._p(m)['untracked_in_qty'] = self._p(m).get('untracked_in_qty', 0.0) + q
                    self.trades.append({'ts': ts, 'sig': sig, 'mint': m, 'side': 'untracked_inflow', 'qty': q, 'usd': 0.0, 'how': 'unsigned inflow', 'realized': 0.0, 'period': period})
                else: self.transfer_out(m, -q, ts, sig)
            self.flag('unsigned_token_inflow'); return 'unsigned'
        ins = {m: q for m, q in toks.items() if q > 0}; outs = {m: -q for m, q in toks.items() if q < 0}
        if abs(cash_usd) < 0.01 and len(ins) + len(outs) == 1:
            for m, q in ins.items(): self.buy(m, q, 0.0, ts, sig, 'inflow_no_cash_zero_cost', period); self.flag('token_inflow_no_cash')
            for m, q in outs.items(): self.transfer_out(m, q, ts, sig)
            return 'transfer'
        if cash_usd < 0 and ins and not outs:                   # buy(s) paid in cash
            self._alloc_buys(ins, -cash_usd, ts, sig, ('cash_buy' if len(ins) == 1 else 'cash_buy_multi') + qt, period); return 'buy'
        if cash_usd > 0 and outs and not ins:                   # sell(s) for cash
            if len(outs) == 1:
                m, q = next(iter(outs.items())); self.sell(m, q, cash_usd, ts, sig, 'cash_sell' + qt, period)
            else:
                vals = {m: (self.price_token(m, ts)[0] or 0) * q for m, q in outs.items()}; tot = sum(vals.values())
                for m, q in outs.items():
                    share = vals[m] / tot if tot > 0 else 1 / len(outs); self.sell(m, q, cash_usd * share, ts, sig, 'cash_sell_multi' + qt, period)
                self.flag('multi_token_sell')
            return 'sell'
        if ins and outs:                                         # token-for-token (cash residual = fees/rent/LP cash side)
            # Book realized at the swap only when every given-up leg is priced by this wallet's own cash fill within 1 h at a
            # comparable size. Otherwise carry the basis over to the received legs (no realized PnL until cash comes out);
            # a GeckoTerminal spot price x a large illiquid block (deployer supply, LP adds) would invent profit.
            V = 0.0; ok = True; ov = {}
            for m, q in outs.items():
                px, src = self.price_token(m, ts, q, allow_gt=False)
                if px is None: ok = False; break
                ov[m] = px * q; V += px * q
            if ok and V > 0:
                self.flag('token_for_token_swap')
                for m, q in outs.items(): self.sell(m, q, ov[m], ts, sig, 'token_swap:implied_own_trade', period)
                self._alloc_buys(ins, max(V - cash_usd, 0.0), ts, sig, 'token_swap:implied_own_trade', period)
                return 'swap'
            self.flag('token_swap_basis_carryover')
            basis = 0.0
            for m, q in outs.items():
                p = self._p(m); have = max(p['qty'], 0.0); mt = min(q, have)
                b = p['cost'] * mt / have if have > 0 else 0.0
                basis += b; p['cost'] -= b; p['qty'] -= mt
                if q - mt > 1e-9 * q: self.flag('swap_out_without_tracked_basis')
                if p['peak'] > 0 and p['qty'] <= 0.01 * p['peak']: p['qty'] = 0.0; p['cost'] = 0.0; p['peak'] = 0.0
                self.trades.append({'ts': ts, 'sig': sig, 'mint': m, 'side': 'swap_out', 'qty': q, 'usd': b, 'how': 'token_swap:basis_carryover', 'realized': 0.0, 'period': period})
            nb = basis - cash_usd                                # cash paid adds to basis, cash received reduces it
            if nb < 0:                                           # received more cash than the carried basis -> realized gain
                if period:
                    self.trades.append({'ts': ts, 'sig': sig, 'mint': next(iter(outs)), 'side': 'sell', 'qty': 0.0, 'usd': -nb, 'how': 'token_swap:cash_above_basis', 'realized': -nb, 'period': period})
                    self._p(next(iter(outs)))['realized'] += -nb
                nb = 0.0
            tq = sum(ins.values())
            for m, q in ins.items():
                p = self._p(m)
                if p['qty'] <= 1e-9 * max(p['peak'], 1e-30): p['t0'] = ts; p['peak'] = 0.0; p['cyc_real'] = 0.0; p['cyc_cost'] = 0.0; p['cyc_n'] = 0
                share = nb * (q / tq if len(ins) > 1 else 1.0)
                p['qty'] += q; p['cost'] += share; p['peak'] = max(p['peak'], p['qty']); p['cyc_cost'] += share
                self.trades.append({'ts': ts, 'sig': sig, 'mint': m, 'side': 'swap_in', 'qty': q, 'usd': share, 'how': 'token_swap:basis_carryover', 'realized': 0.0, 'period': period})
            return 'swap_carryover'
        # odd shapes: token in + cash in, token out + cash out -> transfer + cash flow
        for m, q in ins.items():   # cost unknown -> untracked (later sells of it go to no_basis_*)
            self._p(m)['untracked_in_qty'] = self._p(m).get('untracked_in_qty', 0.0) + q
            self.trades.append({'ts': ts, 'sig': sig, 'mint': m, 'side': 'untracked_inflow', 'qty': q, 'usd': 0.0, 'how': 'odd shape: token in + cash in', 'realized': 0.0, 'period': period})
        for m, q in outs.items(): self.transfer_out(m, q, ts, sig)
        self.cash_flows.append((ts, sig, cash_usd)); self.flag('odd_shape'); return 'odd'
    def _alloc_buys(self, ins, usd, ts, sig, how, period):
        if len(ins) == 1:
            m, q = next(iter(ins.items())); self.buy(m, q, usd, ts, sig, how, period); return
        vals = {}
        for m, q in ins.items():
            px, _ = self.price_token(m, ts); vals[m] = (px or 0) * q
        tot = sum(vals.values())
        if tot <= 0:   # nothing priceable: give it to the largest-qty-change leg not seen as free before
            paid = [m for m in ins if not self.pos.get(m, {}).get('free_qty')] or list(ins)
            tgt = max(paid, key=lambda m: ins[m]); vals = {m: (1.0 if m == tgt else 0.0) for m in ins}; tot = 1.0
            self.flag('multi_buy_alloc_heuristic')
        for m, q in ins.items(): self.buy(m, q, usd * vals[m] / tot, ts, sig, how, period)

    def summary(self, prices=None, sol_px_now=None):
        prices = prices or {}; rows = []
        for m, p in self.pos.items():
            if not (p['bought_usd'] or p['sold_usd'] or p['realized'] or p['nb_usd'] or p['qty'] > 1e-12 or p.get('untracked_in_qty')): continue
            px = prices.get(m); val = p['qty'] * px[0] if px and p['qty'] > 0 else None
            unr = (val - p['cost']) if val is not None and p['cost'] > 0 else None
            rows.append({'mint': m, 'bought_usd': p['bought_usd'], 'sold_usd': p['sold_usd'], 'realized_usd': p['realized'],
                         'open_qty': max(p['qty'], 0), 'open_cost_usd': max(p['cost'], 0), 'free_qty': p['free_qty'],
                         'px_now': px[0] if px else None, 'px_src': px[1] if px else None, 'value_now_usd': val,
                         'unrealized_usd': unr, 'no_basis_qty': p['nb_qty'], 'no_basis_proceeds_usd': p['nb_usd'], 'untracked_in_qty': p.get('untracked_in_qty', 0.0)})
        return rows

def reconcile(L, opening):
    """At period start, cap each seeded position to the real opening balance (on-chain now minus in-period deltas).
    Qty the seed ledger still shows but the wallet no longer held left before the period at an unknown price: its cost is
    dropped (not counted as an in-period loss). Opening qty above the seed ledger stays untracked -> later sells of it go
    to no_basis_* (never counted as profit)."""
    L.reconciled = {}
    for m, p in L.pos.items():
        q = max(opening.get(m, 0.0), 0.0)
        if p['qty'] > q * 1.0001 + 1e-9:
            dropped = p['cost'] * (1 - q / p['qty']) if p['qty'] > 0 else 0.0
            L.reconciled[m] = {'ledger_qty': p['qty'], 'opening_qty': q, 'cost_dropped_usd': dropped}
            p['cost'] -= dropped; p['qty'] = q
            if q <= 0: p['peak'] = 0.0; p['cost'] = 0.0
            L.flag('seed_position_capped_to_opening_balance')

def run(chain, events, period_start=0, period_end=None, gt_budget=60, opening=None):
    """Seed with events before period_start (basis only), count realized/fees inside [period_start, period_end].
    opening: optional {asset: qty held at period_start}; seeded positions are capped to it (see reconcile)."""
    period_end = period_end or time.time() + 86400
    L = Ledger(chain, gt_budget); kinds = {}; crossed = False
    for ev in sorted(events, key=lambda e: (e['ts'], e.get('slot', 0))):
        if ev['ts'] > period_end: continue
        if opening is not None and not crossed and ev['ts'] >= period_start:
            crossed = True; reconcile(L, opening)
        k = L.apply(ev, period=ev['ts'] >= period_start); kinds[k] = kinds.get(k, 0) + (1 if ev['ts'] >= period_start else 0)
    L.kinds = kinds
    return L

def stats(L, period_start=0):
    """Compact metrics compatible with the old wallet_pnl_90d columns."""
    cyc = [c for c in L.cycles if c['period']]; pl = [c['pnl'] for c in cyc]; gp = sum(x for x in pl if x > 0)
    tr = [t for t in L.trades if t.get('period') and t['side'] in ('buy', 'sell')]
    real_usd = sum(t['realized'] for t in tr if t['side'] == 'sell')
    real_sol = sum(t['realized'] / (SOLPX.at(t['ts']) or 1) for t in tr if t['side'] == 'sell')
    quotes = {}
    return {'swaps': len(tr), 'closed': len(cyc), 'realized_usd': round(real_usd, 2), 'realized_sol_equiv': round(real_sol, 3),
            'win_rate': round(sum(x > 0 for x in pl) / len(pl), 3) if pl else None, 'best_share': round(max(pl) / gp, 3) if gp > 0 else None,
            'n_coins': len({t['mint'] for t in tr}), 'open': sum(1 for p in L.pos.values() if p['qty'] > 1e-9 and p['cost'] > 0),
            'median_hold_s': sorted(c['hold_s'] for c in cyc)[len(cyc) // 2] if cyc else None,
            'fee_network_usd': round(L.fee_net_usd, 2), 'fee_app_usd': round(L.fee_app_usd, 2),
            'no_basis_proceeds_usd': round(sum(t.get('no_basis_usd', 0) for t in tr if t['side'] == 'sell'), 2),
            'token_swaps': L.flags.get('token_for_token_swap', 0) + L.flags.get('token_swap_basis_carryover', 0),
            'token_swaps_carryover': L.flags.get('token_swap_basis_carryover', 0), 'unpriced_swaps': L.flags.get('token_swap_unpriced', 0),
            'flags': dict(L.flags), 'kinds': dict(getattr(L, 'kinds', {}))}

def realized_from_txs(txs, wallet, period_start=0, gt_budget=30):
    """Solana convenience: raw txs -> (Ledger, stats)."""
    evs = [e for e in (sol_event(t, wallet) for t in txs) if e]
    if evs:
        SOLPX.ensure(min(e['ts'] for e in evs), max(e['ts'] for e in evs))
    L = run('solana', evs, period_start, gt_budget=gt_budget)
    return L, stats(L, period_start)

# ------------------------------------------------------------------------------------------------ EVM read-only fetch
EVM_RPC = {'robinhood': ['https://rpc.mainnet.chain.robinhood.com'],
           'base': ['https://base.gateway.tenderly.co', 'https://mainnet.base.org']}
EVM_SPAN = {'robinhood': 30000, 'base': 1000}
TRANSFER = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
_READ = {'eth_blockNumber', 'eth_getBlockByNumber', 'eth_getLogs', 'eth_call', 'eth_getTransactionByHash', 'eth_getTransactionReceipt', 'eth_getBalance'}
def evm_rpc(chain, method, params):
    assert method in _READ, 'read-only RPC only'
    for i in range(8):
        for u in EVM_RPC[chain]:
            r = http_json(u, min_gap=0.35, tries=2, data={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}, timeout=60)
            if r and 'result' in r: return r['result'], ''
            err = str((r or {}).get('error'))[:160]
            if r and 'error' in r and ('range' in err or 'spans' in err or 'too large' in err): return None, err
        time.sleep(2 * (i + 1))
    return None, 'rpc failed'
def evm_block_at(chain, ts):
    head, _ = evm_rpc(chain, 'eth_blockNumber', []); hi = int(head, 16); lo = 1
    def t(b): return int(evm_rpc(chain, 'eth_getBlockByNumber', [hex(b), False])[0]['timestamp'], 16)
    if t(hi) <= ts: return hi
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if t(mid) <= ts: lo = mid
        else: hi = mid
    return hi
def evm_transfer_logs(chain, wallet, b0, b1, log=print):
    """All ERC-20 Transfer logs with wallet as from or to, blocks [b0,b1]. Cached per chunk."""
    p = f'{CACHE}/evm_{chain}_{wallet.lower()}.json'; C = _jload(p, {'chunks': {}, 'logs': {}})
    pad = '0x' + '0' * 24 + wallet.lower()[2:]; span = EVM_SPAN[chain]; n = 0
    for b in range(b0, b1 + 1, span):
        e = min(b + span - 1, b1); key = f'{b}-{e}'
        if key in C['chunks']: continue
        ok = True
        for topics in ([TRANSFER, pad], [TRANSFER, None, pad]):
            r, err = evm_rpc(chain, 'eth_getLogs', [{'fromBlock': hex(b), 'toBlock': hex(e), 'topics': topics}])
            if r is None: ok = False; log('getLogs fail', chain, key, err); break
            for lg in r: C['logs'][f"{lg['transactionHash']}:{lg['logIndex']}"] = lg
        if ok and e < b1 - 50: C['chunks'][key] = 1   # do not cache the moving head chunk
        n += 1
        if n % 50 == 0: _jsave(p, C); log('evm scan', chain, b, '/', b1, 'logs', len(C['logs']))
    _jsave(p, C); return list(C['logs'].values())
def evm_decimals(chain, tokens):
    p = f'{CACHE}/evm_decimals_{chain}.json'; D = _jload(p, {})
    for t in tokens:
        if t in D: continue
        r, _ = evm_rpc(chain, 'eth_call', [{'to': t, 'data': '0x313ce567'}, 'latest'])
        D[t] = int(r, 16) if r and r != '0x' else 18
    _jsave(p, D); return D
def evm_tx_meta(chain, hashes, wallet):
    p = f'{CACHE}/evm_txmeta_{chain}.json'; M = _jload(p, {}); bt = {}
    for h in hashes:
        if h in M: continue
        tx, _ = evm_rpc(chain, 'eth_getTransactionByHash', [h])
        if not tx: continue
        b = int(tx['blockNumber'], 16)
        if b not in bt: bt[b] = int(evm_rpc(chain, 'eth_getBlockByNumber', [hex(b), False])[0]['timestamp'], 16)
        m = {'ts': bt[b], 'from': tx['from'], 'to': tx.get('to'), 'value_native': 0.0, 'gas_native': 0.0}
        if tx['from'].lower() == wallet.lower():
            rc, _ = evm_rpc(chain, 'eth_getTransactionReceipt', [h])
            if rc: m['gas_native'] = int(rc['gasUsed'], 16) * int(rc.get('effectiveGasPrice') or tx.get('gasPrice') or '0x0', 16) / 1e18
            m['value_native'] = -int(tx.get('value') or '0x0', 16) / 1e18
        M[h] = m
    _jsave(p, M); return M
def evm_wallet_events(chain, wallet, ts0, ts1=None, log=print):
    b0 = evm_block_at(chain, ts0); b1 = evm_block_at(chain, ts1) if ts1 else int(evm_rpc(chain, 'eth_blockNumber', [])[0], 16)
    logs = evm_transfer_logs(chain, wallet, b0, b1, log)
    dec = evm_decimals(chain, sorted({l['address'].lower() for l in logs}))
    meta = evm_tx_meta(chain, sorted({l['transactionHash'] for l in logs}), wallet)
    evs = evm_events(chain, wallet, logs, dec, meta)
    if evs: ETHPX.ensure(min(e['ts'] for e in evs), max(e['ts'] for e in evs))
    return evs, {'b0': b0, 'b1': b1, 'n_logs': len(logs)}

def evm_settle_relayed(chain, wallet, events, log=print):
    """Relayer-settled EVM trades (e.g. app relayers on Robinhood Chain: tokens move wallet<->relay, the USDG/WETH side moves between the
    relay and the app's settlement account, never touching the wallet). For each event that has token legs but no cash leg,
    read the receipt; R = the wallet's token counterparty; routers = R's counterparties for those tokens; the user's cash
    leg = cash-asset transfers between R and anyone except routers/the wallet (into R = user paid, out of R = user got).
    Adds the cash leg to ev['legs'] and sets ev['settled_via']. Cached receipts. Read-only."""
    w = wallet.lower(); cash = {a for a in EVM_CASH.get(chain, {}) if a != 'native'}
    p = f'{CACHE}/evm_receipts_{chain}.json'; RC = _jload(p, {}); n = 0
    for ev in events:
        legs = ev['legs']; toks = [a for a in legs if a.lower() not in cash and a != 'native']
        if not toks or any(a.lower() in cash for a in legs): continue
        h = ev['id']
        if h not in RC:
            r, _ = evm_rpc(chain, 'eth_getTransactionReceipt', [h]); RC[h] = [{'a': l['address'].lower(), 't': l['topics'], 'd': l['data']} for l in (r or {}).get('logs', [])]; n += 1
        tr = []
        for l in RC[h]:
            if len(l['t']) == 3 and l['t'][0] == TRANSFER:
                tr.append((l['a'], '0x' + l['t'][1][-40:], '0x' + l['t'][2][-40:], int(l['d'], 16) if l['d'] not in ('0x', None) else 0))
        tl = {t.lower() for t in toks}
        R = {fr if to == w else to for a, fr, to, v in tr if a in tl and w in (fr, to)}
        R.discard(w)
        if len(R) != 1: continue
        R = R.pop()
        routers = {to if fr == R else fr for a, fr, to, v in tr if a in tl and R in (fr, to)} - {w, R}
        dec = evm_decimals(chain, sorted(cash))
        side = 'buy' if all(legs[t] > 0 for t in toks) else 'sell' if all(legs[t] < 0 for t in toks) else 'mixed'
        cl = {}
        if side == 'buy':     # user paid: cash into R from its funding source(s), minus refunds back to those sources
            src = {fr for a, fr, to, v in tr if a in cash and to == R and fr not in routers and fr != w}
            for a, fr, to, v in tr:
                if a not in cash: continue
                if to == R and fr in src: cl[a] = cl.get(a, 0) - v / 10 ** dec.get(a, 18)
                if fr == R and to in src: cl[a] = cl.get(a, 0) + v / 10 ** dec.get(a, 18)
        elif side == 'sell':  # user received: cash out of R to its payout account(s), minus anything those sent back
            dst = {to for a, fr, to, v in tr if a in cash and fr == R and to not in routers and to != w}
            for a, fr, to, v in tr:
                if a not in cash: continue
                if fr == R and to in dst: cl[a] = cl.get(a, 0) + v / 10 ** dec.get(a, 18)
                if to == R and fr in dst: cl[a] = cl.get(a, 0) - v / 10 ** dec.get(a, 18)
        cl = {a: q for a, q in cl.items() if abs(q) > EPS}
        if cl:
            legs.update(cl); ev['settled_via'] = R; ev['signer'] = True
    _jsave(p, RC); log('relay receipts fetched', n)
    return events
