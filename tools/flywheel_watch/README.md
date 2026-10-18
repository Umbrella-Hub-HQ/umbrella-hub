# flywheel_watch: launchpad launch + migration watcher (read-only)

Reference target: flywheel.cash on Robinhood Chain. Polls every 60 s (fast launches can 10x within 15 min).
No trades, signing, payments, sends or posts. Free sources: public Robinhood Chain RPCs, DexScreener, CoinGecko,
and the launchpad's public indexer API as a fallback.

## How it works
1. New launches from the factory `TokenCreated(token, creator, quote)` logs.
2. Every launch younger than `track_h` (6 h) is followed with ONE Transfer `eth_getLogs` for all tracked tokens plus
   quote legs through the pool manager -> swaps, price and on-chain market cap.

## Alerts (`flywheel_alerts.jsonl`)
| Kind | Rule |
| --- | --- |
| WATCHED_RECEIVE | a watched wallet / factory owner / listed deployer receives the coin (buy or airdrop). HIGH if >= $500, or >= 0.05% of supply at mcap >= $50K |
| CREATOR_LAUNCH_BUY | creator took >= 5% of supply in the launch tx (MEDIUM) |
| LAUNCH_BY_WATCHED | creator is the factory owner (HIGH) or a listed deployer / watched wallet (MEDIUM) |
| MIGRATION | one address sends the coin to >= 50 wallets within 15 min; lists older same-symbol tokens |
| FAST_MC | >= 3x and >= $150K within 60 min, or >= $500K within 3 h (HIGH with an insider flag) |

## Run
```bash
cp flywheel_config.example.json flywheel_config.json   # re-verify the public protocol constants on an explorer
cp ../wallets.example.json wallets.json                # optional; chain=robinhood wallets are watched
python3 flywheel_watch.py --once
python3 flywheel_watch.py --replay FROM_BLOCK TO_BLOCK [--step-s 60] [--token 0x..]
bash start_flywheel_watch.sh                              # 60-s self-healing loop
```
Env: `FLYWHEEL_DIR`, `FLYWHEEL_CONFIG`, `WALLETWATCH_CONFIG`, `UMBRELLA_TOOLS_DIR` (folder with `_http.py`),
`DESK_DB` (optional read-only SQLite holding `[L-YYYYMMDD-NNN]` lead IDs). Change thresholds only with the owner's OK.
