# sol_data: free-first Solana data client (read-only)

Spreads Solana RPC calls over every working free source with per-provider rate buckets, backoff, monthly-cap detection
and disk caches, so research and watchers keep working when a paid provider runs out of credits.

## Providers
| Provider | Key | Notes |
| --- | --- | --- |
| api.mainnet-beta.solana.com | none | full history; getSignaturesForAddress is strict (~0.3-0.5/s) |
| api.mainnet.solana.com | none | full history; separate quota |
| solana-rpc.publicnode.com | none | pruned (~1-2 days); recent txs and getTokenLargestAccounts only |
| Alchemy Solana free tier (optional) | `SOL_RPC_ALCHEMY` | full archive, JSON batch, Helius-style getTransactionsForAddress; budget ~200 CU/s box-wide |
| Helius (optional) | `HELIUS_API_KEY` | used only while under its monthly cap; auto-disabled 6 h on "max usage reached" |
| any other free RPC | `SOL_RPC_<NAME>` | `SOL_FULL_<NAME>=0` marks a pruned node |

Keyless data APIs used for holders/market data: GeckoTerminal, Jupiter datapi, DexScreener.

## Setup
```bash
cp sol_data.env.example sol_data.env && chmod 600 sol_data.env   # optional; edit YOUR_ALCHEMY_KEY
python3 sol_data.py status
python3 test_sol_data.py <ANY_PUBLIC_WALLET> <ANY_TOKEN_MINT>
```
`SOL_DATA_ENV` can point at the env file elsewhere. Never print, paste or commit it.

## API
`rpc(method, params)`, `raw(body)`, `get_txs(sigs)`, `signatures(addr)`, `first_funder(addr)`, `wallet_history(addr)`,
`realized_pnl(addr)` (multi-currency via `pnl_multi.py`), `token_holders(mint)`, `txs_for_address(...)`.
CLI: `sol_data.py status | funder <addr> | pnl <addr> | holders <mint> | selftest <wallet> <mint>`.

Gotcha: request `maxSupportedTransactionVersion: 1`; v1 transactions exist and `0` returns -32015. `raw()` fixes it.

## pnl_multi.py
Multi-currency wallet PnL: every cash leg (SOL, wSOL, USDC, USDT, USD1, PYUSD, USDS, USDG, FDUSD, USDe, DAI, USDbC,
ETH, WETH) priced in USD at trade time; token-for-token swaps handled conservatively; fees counted; sells with no
tracked basis kept apart, never counted as profit. Solana and EVM (Robinhood Chain, Ethereum, Base).

## Rules
Never pay or upgrade a plan; never open a second free account to get around a cap; label every number with its source;
write UNKNOWN when no free source can reach a value.
