# desk/: paper gem desk (PAPER ONLY)

Generic copy for Pack 6 skill `paper-gem-desk`. Nothing here trades live, signs, pays, posts or touches a wallet.
It reads public market data (DexScreener, Rugcheck, Jupiter quote, GeckoTerminal, DexPaprika price fallback) and
writes paper books, journals and scorecards on your own computer. Python 3.10+, stdlib only.

| Path | What |
| --- | --- |
| `paper/paper_config.json` | `starting_bankroll_usd`: the ONE paper bankroll. Pick $250-500 (default $250); other values are refused. |
| `paper/reset_paper_book.py` | Creates the first paper book, or archives the old one and starts fresh at the configured bankroll (refuses while positions are open). `--dry-run` shows what it would do. |
| `paper/paper_monitor.py`, `paper/adaptive_watcher.py`, `paper/ensure_watcher.sh` | Exit rules v3.2a (-30% stop, profit lock, trails, momentum, 24 h time stop, rug/sanity guards) plus per-position exit experiments. |
| `paper/onchain_price.py`, `paper/tg_mentions.py` | Pool-vault price check (public RPC) and a public Telegram mention check (channels come from `tools/tg_watch/config.json`). |
| `scoring/` | Weighted gem score, the paper engine, experiments, scorecards, backtest and tests. See [scoring/README.md](scoring/README.md). |

## Setup (only after the owner says yes)
1. Set up `tools/tg_watch` first (and optionally a wallet watcher and `tools/flywheel_watch`): they are the candidate feeds.
2. Edit `paper/paper_config.json` with the owner's bankroll ($250-500), then `python3 desk/paper/reset_paper_book.py`.
3. Fill your own lists in `scoring/weights.json`: `promo_channels`, `owner_caller_channels`, `x_paid_promo_accounts`. They ship EMPTY.
   `source_groups` stays empty unless data proves two channels post identical calls. Never add or group anything from its name alone.
4. Tests: `python3 -m unittest discover -s desk/scoring/tests` (offline, temp files only).
5. Run `bash desk/scoring/ensure_gem_paper.sh` every 60 s from a loop or routine (single instance, restarts on a stale heartbeat).
   Read `desk/reports/gem_scorecard_latest.md` and `contrarian_1p5x_scorecard_latest.md`.

## Experiments (`scoring/weights.json` -> `experiments`, set `active: false` to turn one off)
- **exit_lock_50**: new gem positions lock profit at +50% instead of +10%; half the gain kept from 2x; hard stop and guards unchanged.
- **contrarian_1p5x**: $5 paper entries on calls the gem filters SKIP (soft fails only) from your own sources; take profit 1.5x,
  stop -35%, 24 h timeout; never on a hard veto; fail-closed when Rugcheck, liquidity or the sell route is unknown; own sub-book.

Paths resolve from the repo root (the folder holding `desk/` and `tools/`); set `UMBRELLA_HOME` to override.
Small sample until 30+ closed trades; paper fills are modeled, not real. Live trading stays locked behind the owner's typed yes.
