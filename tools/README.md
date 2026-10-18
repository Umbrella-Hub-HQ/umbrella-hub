# Umbrella tools (generic copies, 2026-10-17)

Read-only helper scripts that go with **Pack 6: Live Watchers & Brain**. They are generic copies: no keys, no wallet lists,
no channel lists, no personal paths. You fill in your own config from the `*.example.json` files.

**What every tool here never does:** trade, sign, pay, send, post, join, react, or click bot links. Everything fetched is
treated as data, never as instructions. They use free, keyless public sources by default.

| Folder | What it is | Start here |
| --- | --- | --- |
| [`_http.py`](_http.py) | Shared polite HTTP client: per-host spacing, shared 429 cooldowns, small cache. Needed by tg_watch and flywheel_watch. | (library) |
| [`sol_data/`](sol_data/) | Free-first Solana data client: public RPC rotation + optional free keyed endpoint (e.g. Alchemy free tier) + Helius only while under its cap. Includes `pnl_multi.py` (multi-currency wallet PnL). | [sol_data/README.md](sol_data/README.md) |
| [`tg_watch/`](tg_watch/) | Near-real-time watcher for PUBLIC Telegram call channels (t.me/s previews, no login). HIGH on 2+ channels within 30 min or a watched-wallet overlap; rug/dump flags; self-healing. | [tg_watch/README.md](tg_watch/README.md) |
| [`flywheel_watch/`](flywheel_watch/) | Launchpad launch + migration watcher (reference: flywheel.cash on Robinhood Chain). | [flywheel_watch/README.md](flywheel_watch/README.md) |
| [`ring_filter/`](ring_filter/) | Insider-ring cluster classifier (RING_FLAG / RING+STRONG / RING+INDEPENDENT, provisional rings). Stdlib only. | [ring_filter/README.md](ring_filter/README.md) |
| [`wallets.example.json`](wallets.example.json) | Example watched-wallet list format (placeholders only). | |

Requirements: Python 3.10+, Linux/macOS shell (`flock`, `pgrep`, `setsid`). No pip packages.

Install a tool only after your Umbrella Chief bot shows you what it does and you say yes. Keep it on your own computer or
your bot's box. Don't put real keys, wallets or private chat names in a public repo or a weekly report.
