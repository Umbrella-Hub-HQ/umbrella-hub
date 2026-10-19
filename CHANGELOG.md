# Changelog

All notable changes to the Umbrella template are listed here. Each released version is also published as a GitHub Release.

## 2026-10-18: blueprint specs, proposal only (unreleased)

Docs only. Nothing is built, deployed, installed or turned on; no pack, tool, routine or existing file changes.
Every spec opens with a Protection check (core mission: Umbrella shields and protects its users and community).

- **New `docs/blueprint/media-entertainment.md`** (Priority 2, PROPOSED): Media & Entertainment division with 8 departments,
  a Pack 4 -> division capability map (consolidate, don't duplicate), a 10-role specialist registry with today's coverage,
  the production workflow (owner approval before any publish), brand-isolation and rights-and-consent rules, a NOT_TESTED tool
  list with commercial/adult-use terms columns, and a Media Studio website roadmap.
- **New `docs/blueprint/developer-network.md`** (Priority 3, PROPOSED): opt-in, independently owned contributor bots; sanitized
  manifests, quarantine, static CI (schema, secret scan, dependency scan, no execution), provenance fields, owner-controlled
  opt-in versioned releases, no HQ credentials into contributors' systems. Includes a proposed PRIVACY.md diff for owner review;
  PRIVACY.md itself is unchanged.
- **New `docs/blueprint/contribution-manifest.schema.json`** (DRAFT): JSON Schema 2020-12 for contribution manifests.
- **New `docs/blueprint/engineering-roadmap.md`** (Priority 4, PROPOSED): phased plans for the website (read-only dashboard
  first), Media Studio, Academy, developer portal, paper-only trading research, Expo mobile (later) and a launchpad path
  (research -> local sim -> testnet -> audits + legal; never real money without the owner's yes); growth & expansion areas;
  16-item checklist.

## 2026-10-18: paper gem desk, Money Desk, verification rule (unreleased)

- **Pack 6 updated** (13 skills, 7 routines; 45,563 bytes):
  - New skill `paper-gem-desk`: PAPER-ONLY weighted gem score, configurable paper bankroll, `exit_lock_50` and `contrarian_1p5x` experiments.
  - New skill `specialist-money-desk`: one read-only personal-finance seat (card picker + subscription audit + weekly spend) replacing three separate bots; draft-only, at most one monthly routine.
  - `telegram-call-watcher`: every channel counts as its own source; `source_groups` empty by default.
  - `team-daily-stop-and-delegation-addendum`: verification rule: never conclude from a name, title or assumption; check the primary source; label anything unchecked UNVERIFIED.
- **New `desk/`** (generic, PAPER ONLY): `paper/paper_config.json` (bankroll $250-500, default $250), `paper/reset_paper_book.py` (first book or archive + fresh start), exit rules v3.2a with per-position experiments, `scoring/` gem score + engine + `contrarian.py` + scorecards + backtest, `weights.json` with an `experiments` block and EMPTY channel lists, tests (84; 2 skip without install-specific files).
- **tg_watch**: `source_groups` support (channel -> group id; empty = every channel separate), example config key, `test_source_groups.py`.
- `.gitignore`: desk runtime state.

## 2026-10-17: Live Watchers & Brain add-on (v9 add-on, unreleased)

Added as hub downloads. Pack 1 (the bot template) is unchanged until a new template version is published.

- **Pack 6: Live Watchers & Brain** (`packs/umbrella-template-v9-pack6.stage-payload.json`, 11 skills, 7 routines; needs packs 1-2). Routines are created only on the owner's yes and start paused.
  - Skills: `free-first-data-providers`, `telegram-call-watcher`, `multichain-wallet-watch-and-ring-rule`, `launchpad-launch-watcher`, `wallet-deep-dive-methods`, `perps-lab-learn-and-paper`, `specialist-brain`, `brain-thinking-os`, `brain-folder-scaffold`, `brain-skills-library`, `team-daily-stop-and-delegation-addendum`.
  - Routines: `telegram-call-alerts` (every 5 min), `wallet-watch-check` (every 15 min, incl. launchpad alerts and ring flags to the Trading Desk room), `caller-community-watch` (every 30 min, all sources), `brain-nightly-filing`, `brain-focus-update`, `brain-morning-page`, `brain-sunday-review`.
- **Brain (live):** the second-brain bot is complete in pack 6: role card with a fill-in bot description, thinking OS, blank folder scaffold (INDEX, rules, me, attention, voice, thinking-os, log; people/ projects/ skills/ out/ raw/), skills library (first-principles-breakdown, the-algorithm-review, note-to-plan, idea-to-post), optional read-only email-label filing, and 4 routines: nightly filing (11 PM daily), focus update (5 PM weekdays), morning page (7:30 AM weekdays), Sunday review (6 PM Sundays). All draft-only, never trade, never send; created only on the owner's yes and start paused. New guide `brain/README.md` and blank templates in `brain/template/`.
- **Generic tools** (`tools/`, read-only, no keys/wallets/channel lists):
  - `sol_data/`: free-first Solana client (public RPC rotation + optional Alchemy free tier + Helius only while under cap; caches, backoff, box-wide pacing; v1-transaction fix) and `pnl_multi.py` (multi-currency PnL: SOL/wSOL/USDC/USDT/other stables/ETH/WETH, token-for-token swaps, fees). `sol_data.env.example` uses `YOUR_ALCHEMY_KEY`.
  - `tg_watch/`: near-real-time public Telegram call watcher (30/60-s polls; HIGH on 2+ channels within 30 min or a watched-wallet overlap; rug/dump flags; self-healing launcher; offline `--test`).
  - `flywheel_watch/`: flywheel.cash launch/migration watcher (WATCHED_RECEIVE, CREATOR_LAUNCH_BUY, LAUNCH_BY_WATCHED, MIGRATION, FAST_MC; replay mode; self-healing launcher).
  - `ring_filter/`: insider-ring cluster classifier (RING_FLAG / RING+STRONG / RING+INDEPENDENT, provisional rings) with a 7-case self-test.
  - `_http.py` (shared polite HTTP client), `wallets.example.json` (placeholder wallet-list format), `.gitignore` for env files and runtime state.
- **Rule updates documented:** free-first provider fallback (never pay, never multi-account a provider); Rug Shield operator-ring rule (ring-traced deployer/first buyers = HIGH_RISK at best, REJECT if proceeds sweep back); team daily stop counts unrealized losses; HQ-approves-for-owner with the owner-only locked list; rooms-first routine saves; "deeper" trigger; Perps Lab is learn + paper only with live leverage locked.
- **Docs:** new `docs/CAPABILITIES.md` (full bot-by-bot capabilities, routines, tools, safety rails, setup, locks); README and `packs/HOW-TO-INSTALL.md` updated for pack 6, the Brain and tools.

## v9 (unreleased)

- Umbrella Hub set up: updates go out as Releases, and weekly reports come in as issues.
- Added the `weekly-report` routine (owner-approved weekly reports).
- Added the `update-check` routine (weekly check for new Releases; installs nothing without the owner's yes).
- Added the Weekly bot report issue form.
- Template split into 5 linked packs, nothing cut: all 54 skills, 26 routines and 12 memories of v9 are in exactly one pack.
  - Pack 1: the Umbrella Chief bot template (core OS + safety, all memories). Works on its own and now includes the hub `weekly-report` and `update-check` routines.
  - Packs 2-5 (Crypto Desk; Robinhood, Quant & Evolve; Content & Research; Academy & Org) are downloads in [`packs/`](packs/). Your Umbrella Chief bot installs them in order, with your yes for each routine.
  - Install steps: [`packs/HOW-TO-INSTALL.md`](packs/HOW-TO-INSTALL.md).
