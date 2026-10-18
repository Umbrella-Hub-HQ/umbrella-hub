#!/usr/bin/env python3
"""onchain_price.py - PAPER/READ-ONLY helpers (2026-10-17 readiness job). Stdlib only. No keys, no Helius, no signing.
Uses the PUBLIC Solana RPC (api.mainnet-beta.solana.com, keyless) so it never touches the Helius 12K/day cap.
  reserve_price(pool, mint, quote_usd=None) -> dict: price implied by the pool's own token vaults (getTokenAccountsByOwner(pool)).
      Works where the pool account owns its vaults (PumpSwap, pump.fun curve WSOL-less excluded, Meteora). Raydium AMM v4/CPMM
      vaults are owned by a shared authority -> returns status UNAVAILABLE (never a guess).
  metaplex_metadata(mint) -> dict: legacy-SPL Metaplex metadata (update authority + is_mutable), PDA derived locally.
Origin: research/deeper-2026-10-17.md (VEILTRUMP/HUMPH: DexScreener AND DexPaprika both stale, 2x-5x above vault price)."""
import json,hashlib,urllib.request,time
RPC="https://api.mainnet-beta.solana.com"
WSOL="So11111111111111111111111111111111111111112"
USD_STABLE={"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v":"USDC","Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB":"USDT"}
TOKEN="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"; TOKEN22="TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
METAPLEX="metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"
_last=[0.0]
def rpc(method,params,timeout=12):
    w=0.25-(time.time()-_last[0])          # be polite to the public endpoint (<= ~4 req/s)
    if w>0: time.sleep(w)
    _last[0]=time.time()
    req=urllib.request.Request(RPC,data=json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params}).encode(),
                               headers={"Content-Type":"application/json","User-Agent":"desk-paper-onchain/1.0 (read-only)"})
    d=json.load(urllib.request.urlopen(req,timeout=timeout))
    if "error" in d: raise RuntimeError(f"rpc {method}: {str(d['error'])[:120]}")
    return d["result"]
# ---- base58 / PDA (pure python) ----
B58="123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
def b58d(s):
    n=0
    for c in s: n=n*58+B58.index(c)
    b=n.to_bytes((n.bit_length()+7)//8,"big") if n else b""
    return b"\0"*(len(s)-len(s.lstrip("1")))+b
def b58e(b):
    n=int.from_bytes(b,"big"); s=""
    while n: n,r=divmod(n,58); s=B58[r]+s
    return "1"*(len(b)-len(b.lstrip(b"\0")))+s
_P=2**255-19; _D=(-121665*pow(121666,_P-2,_P))%_P
def on_curve(b32):
    """True if the 32 bytes decode to a valid ed25519 point (PDAs must be OFF the curve)."""
    y=int.from_bytes(b32,"little")&((1<<255)-1); sign=b32[31]>>7
    if y>=_P: return False
    u=(y*y-1)%_P; v=(_D*y*y+1)%_P
    x2=u*pow(v,_P-2,_P)%_P
    if x2==0: return sign==0
    x=pow(x2,(_P+3)//8,_P)
    if (x*x-x2)%_P!=0: x=x*pow(2,(_P-1)//4,_P)%_P
    return (x*x-x2)%_P==0
def find_pda(seeds,program):
    pid=b58d(program)
    for bump in range(255,-1,-1):
        h=hashlib.sha256(b"".join(seeds)+bytes([bump])+pid+b"ProgramDerivedAddress").digest()
        if not on_curve(h): return b58e(h),bump
    raise ValueError("no PDA")
def metadata_pda(mint): return find_pda([b"metadata",b58d(METAPLEX),b58d(mint)],METAPLEX)[0]
def parse_metadata(raw):
    """Metaplex Metadata v1 borsh: key u8, update_authority[32], mint[32], name, symbol, uri (u32 len+bytes), fee u16,
    creators Option<Vec<34B>>, primary_sale bool, is_mutable bool."""
    o=1; ua=b58e(raw[o:o+32]); o+=32; mint=b58e(raw[o:o+32]); o+=32; out={}
    for k in ("name","symbol","uri"):
        n=int.from_bytes(raw[o:o+4],"little"); o+=4; out[k]=raw[o:o+n].decode("utf8","replace").rstrip("\0"); o+=n
    o+=2
    if raw[o]==1: o+=1; n=int.from_bytes(raw[o:o+4],"little"); o+=4+34*n
    else: o+=1
    o+=1; mut=bool(raw[o])
    return dict(update_authority=ua,mint=mint,is_mutable=mut,**out)
def metaplex_metadata(mint,rpc_fn=None):
    import base64; rpc_fn=rpc_fn or rpc
    pda=metadata_pda(mint); v=rpc_fn("getAccountInfo",[pda,{"encoding":"base64"}]).get("value")
    if not v: return {"status":"NOT_FOUND","pda":pda}
    if v.get("owner")!=METAPLEX: return {"status":"UNKNOWN","pda":pda,"detail":f"owner {v.get('owner')}"}
    md=parse_metadata(base64.b64decode(v["data"][0]))
    if md["mint"]!=mint: return {"status":"UNKNOWN","pda":pda,"detail":"metadata mint mismatch"}
    return {"status":"VERIFIED","pda":pda,**md}
def pool_balances(pool,rpc_fn=None):
    """{mint: ui_amount} summed over token accounts OWNED BY the pool account (both token programs)."""
    rpc_fn=rpc_fn or rpc; bal={}
    for prog in (TOKEN,TOKEN22):
        for a in rpc_fn("getTokenAccountsByOwner",[pool,{"programId":prog},{"encoding":"jsonParsed","commitment":"confirmed"}]).get("value") or []:
            i=a["account"]["data"]["parsed"]["info"]; bal[i["mint"]]=bal.get(i["mint"],0)+float(i["tokenAmount"].get("uiAmount") or 0)
    return bal
def reserve_price(pool,mint,sol_usd=None,rpc_fn=None):
    """Vault-implied USD price of `mint` in `pool`. status VERIFIED | UNAVAILABLE (no owned vaults / unknown quote) | ERROR."""
    try: bal=pool_balances(pool,rpc_fn)
    except Exception as e: return {"status":"ERROR","detail":f"{type(e).__name__}: {e}"[:160]}
    tok=bal.get(mint) or 0
    if tok<=0: return {"status":"UNAVAILABLE","detail":"pool does not own a vault of this mint (e.g. Raydium shared authority)","balances_n":len(bal)}
    for q,name in USD_STABLE.items():
        if bal.get(q): return {"status":"VERIFIED","price_usd":bal[q]/tok,"quote":name,"quote_reserve":bal[q],"token_reserve":tok}
    if bal.get(WSOL):
        if not sol_usd: return {"status":"UNAVAILABLE","detail":"SOL/USD unknown","price_sol":bal[WSOL]/tok}
        return {"status":"VERIFIED","price_usd":bal[WSOL]/tok*sol_usd,"price_sol":bal[WSOL]/tok,"quote":"SOL","quote_reserve":bal[WSOL],"token_reserve":tok}
    return {"status":"UNAVAILABLE","detail":"no SOL/USDC/USDT vault owned by pool","balances_n":len(bal)}
def sol_usd_from_pair(pair):
    try:
        if (pair.get("quoteToken") or {}).get("address")==WSOL and float(pair.get("priceNative") or 0)>0:
            return float(pair["priceUsd"])/float(pair["priceNative"])
    except Exception: pass
    return None
