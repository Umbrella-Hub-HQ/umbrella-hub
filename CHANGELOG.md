# Changelog

All notable changes to the Umbrella template are listed here. Each released version is also published as a GitHub Release.

## 2026-10-17: Live Watchers & Brain add-on (v9 add-on, unreleased)

Added as hub downloads. Pack 1 (the bot template) is unchanged until a new template version is published.

- **Pack 6: Live Watchers & Brain** (`packs/umbrella-template-v9-pack6.stage-payload.json`, 8 skills, 7 routines; needs packs 1-2). Routines are created only on the owner's yes and start paused.
  - Skills: `free-first-data-providers`, `telegram-call-watcher`, `multichain-wallet-watch-and-ring-rule`, `launchpad-launch-watcher`, `wallet-deep-dive-methods`, `perps-lab-learn-and-paper`, `brain-second-brain`, `team-daily-stop-and-delegation-addendum`.
  - Routines: `telegram-call-alerts` (every 5 min), `wallet-watch-check` (every 15 min, incl. launchpad alerts and ring flags to the Trading Desk room), `caller-community-watch` (every 30 min, all sources), `brain-nightly-filing`, `brain-attention-update`, `brain-morning-page`, `brain-sunday-review`.
- **Generic tools** (`tools/`, read-only, no keys/wallets/channel lists):
  - `sol_data/`: free-first Solana client (public RPC rotation + optional Alchemy free tier + Helius only while under cap; caches, backoff, box-wide pacing; v1-transaction fix) and `pnl_multi.py` (multi-currency PnL: SOL/wSOL/USDC/USDT/other stables/ETH/WETH, token-for-token swaps, fees). `sol_data.env.example` uses `YOUR_ALCHEMY_KEY`.
  - `tg_watch/`: near-real-time public Telegram call watcher (30/60-s polls; HIGH on 2+ channels within 30 min or a watched-wallet overlap; rug/dump flags; self-healing launcher; offline `--test`).
  - `flywheel_watch/`: flywheel.cash launch/migration watcher (WATCHED_RECEIVE, CREATOR_LAUNCH_BUY, LAUNCH_BY_WATCHED, MIGRATION, FAST_MC; replay mode; self-healing launcher).
  - `ring_filter/`: insider-ring cluster classifier (RING_FLAG / RING+STRONG / RING+INDEPENDENT, provisional rings) with a 7-case self-test.
  - `_http.py` (shared polite HTTP client), `wallets.example.json` (placeholder wallet-list format), `.gitignore` for env files and runtime state.
- **Rule updates documented:** free-first provider fallback (never pay, never multi-account a provider); Rug Shield operator-ring rule (ring-traced deployer/first buyers = HIGH_RISK at best, REJECT if proceeds sweep back); team daily stop counts unrealized losses; HQ-approves-for-owner with the owner-only locked list; rooms-first routine saves; "deeper" trigger; Perps Lab is learn + paper only with live leverage locked.
- **Docs:** new `docs/CAPABILITIES.md` (full bot-by-bot capabilities, routines, tools, safety rails, setup, locks); README and `packs/HOW-TO-INSTALL.md` updated for pack 6 and tools.

## v9 (unreleased)

- Umbrella Hub set up: updates go out as Releases, and weekly reports come in as issues.
- Added the `weekly-report` routine (owner-approved weekly reports).
- Added the `update-check` routine (weekly check for new Releases; installs nothing without the owner's yes).
- Added the Weekly bot report issue form.
- Template split into 5 linked packs, nothing cut: all 54 skills, 26 routines and 12 memories of v9 are in exactly one pack.
  - Pack 1: the Umbrella Chief bot template (core OS + safety, all memories). Works on its own and now includes the hub `weekly-report` and `update-check` routines.
  - Packs 2-5 (Crypto Desk; Robinhood, Quant & Evolve; Content & Research; Academy & Org) are downloads in [`packs/`](packs/). Your Umbrella Chief bot installs them in order, with your yes for each routine.
  - Install steps: [`packs/HOW-TO-INSTALL.md`](packs/HOW-TO-INSTALL.md).
