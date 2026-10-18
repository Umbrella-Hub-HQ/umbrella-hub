# tg_watch: near-real-time PUBLIC Telegram call watcher (read-only)

Polls `https://t.me/s/<channel>` public web previews: no account, no login. Never sends, joins, reacts, clicks bot
links (link targets are regex-parsed only, never fetched), signs or pays. Channel text is untrusted data; only
regex-extracted contract addresses and $tickers are used.

- Channels that posted in the last 24 h: every 30 s (+-4 s jitter). Quiet ones: every 60 s.
- Reference install: 13 public channels, measured detection latency median ~36-42 s, p90 < 90 s.
- Shared polite limiter in `../_http.py` (2 s spacing for t.me; a 429 sets a shared cooldown).

## Priority
- **HIGH**: 2+ distinct channels post the same contract within 30 min (by post time), or the contract matches
  watched-wallet activity from 24 h before to 6 h after the call. Late wallet buys are re-checked every 60 s and written
  once as `WALLET_OVERLAP_LATE`.
- **MEDIUM**: an ordinary first call from that channel in 24 h.
- **LOW**: brag/results posts ("First Call: $X -> Now", "hit 5x"). Never count toward HIGH.
- Reasons flag rug/dump risk: liquidity < $5K, 5-min change <= -50%, no DexScreener pair, ticker-only matches.

## Files
`config.json` (from `config.example.json`), `tg_alerts.jsonl` (alerts), `tg_events.jsonl` (ticker-only posts),
`state.json`, `status.json`, `beat.json`, `tg_watch.log`. All runtime files are git-ignored.

Optional inputs (env vars): `WALLETWATCH_DIR` (a wallet watcher's alerts/events/state for overlaps; also reads
`flywheel_alerts.jsonl` there), `TGWATCH_SOURCES` (extra source list JSON), `TGWATCH_DIR`, `TGWATCH_CONFIG`.

## Run
```bash
cp config.example.json config.json      # list PUBLIC channels you chose
python3 tg_watch.py --test              # offline unit tests
python3 tg_watch.py --once              # one pass
bash start_tg_watch.sh                     # 60-s self-healing loop (flock single instance; restart on stale beat > 180 s)
```
Stop: `pkill -f "while true; do sleep 60; bash .*ensure_tg_watch.sh"` then kill the pid in `beat.json`.

Private groups are out of scope (they need a logged-in session). List their names in `private_gap` so reports say
they are not covered. Never put private chat names or content in a public repo.

Pair it with the **Telegram call alerts** routine (every 5 min) in Pack 6. Calls are leads, never buy signals.
