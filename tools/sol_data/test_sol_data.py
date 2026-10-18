"""Live, read-only checks for sol_data.py. Usage: python3 test_sol_data.py <ANY_PUBLIC_WALLET> <ANY_TOKEN_MINT>
Uses whatever providers sol_data.env lists (public RPC only if none). Never signs or sends."""
import os, sys, time, json
os.environ.setdefault('SOL_DATA_NO_HELIUS', '1'); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sol_data as SD
if len(sys.argv) < 3: sys.exit(__doc__)
W, MINT = sys.argv[1], sys.argv[2]
R = []
def check(name, fn):
    t = time.time()
    try: ok, info = fn()
    except Exception as e: ok, info = False, repr(e)[:120]
    R.append((name, ok)); print(('PASS' if ok else 'FAIL'), name, f'{time.time()-t:.1f}s', str(info)[:140], flush=True)
check('getSignaturesForAddress (5)', lambda: (lambda r: (r[0] is not None and len(r[0]) > 0, len(r[0] or [])))(SD.rpc('getSignaturesForAddress', [W, {'limit': 5}])))
check('getTransaction v1', lambda: (lambda s: (bool(SD.get_txs([s])[0]), s[:10]))(SD.rpc('getSignaturesForAddress', [W, {'limit': 1}])[0][0]['signature']))
check('first_funder', lambda: (lambda f: (bool(f.get('status')), f.get('status')))(SD.first_funder(W, max_pages=3)))
check('token_holders', lambda: (lambda h: (bool(h.get('count')), h.get('sources')))(SD.token_holders(MINT)))
def no_keyed():
    for p in SD.PROVIDERS:
        if not p.name.startswith('public'): p.disabled_until = time.time() + 600
    r, e = SD.rpc('getSignaturesForAddress', [W, {'limit': 5}]); return (r is not None, e or 'public RPC fallback ok')
check('fallback to public RPC when keyed providers are out', no_keyed)
print(json.dumps({'pass': sum(o for _, o in R), 'total': len(R), 'providers': [(p['name'], p['calls'], p['429']) for p in SD.status()['providers']]}))
