# desk/scoring: gem score + paper gem trades (PAPER ONLY)
Umbrella Hub generic copy (2026-10-18). Never trades live, signs, posts or touches wallets. Paths resolve from the repo root (`UMBRELLA_HOME` overrides).

| file | what |
|---|---|
| gem_score.py | weighted 0-100 score (`score(cand)`), live fetchers (DexScreener, Rugcheck, Jupiter lite quote), shared candidate tracker. CLI: `python3 gem_score.py <mint>...` |
| weights.json | factor weights (sum 100), penalties, thresholds (watch 45 / ping 55 / paper_entry 62), source groups (empty: every channel counts separately), promo channels, owner caller channels and paid-promo X accounts (all EMPTY in the template: fill with your own picks, verified, never from names alone) |
| backtest.py | scores every tg_alerts.jsonl alert at its detection time, enters at first score >= thr, simulates exit rules v3 on GeckoTerminal 1-min candles; threshold sweep. `EXIT_VARIANT=wide` = research-only alternative exit |
| collect_outcomes.py | pulls DexScreener/GeckoTerminal/Rugcheck outcome data for the backtest -> data/outcomes_*.json |
| gem_paper.py | the engine (loop 45 s): ingest tg_watch + wallet_watch + flywheel alerts -> live re-score -> journal / pings / paper entries |
| ensure_gem_paper.sh | single-instance supervisor (pid + 180 s heartbeat); run it every 60 s from your own loop or routine (see desk/README.md) |
| gem_scorecard.py | scorecard -> desk/reports/gem_scorecard_<date>.md/.json + gem_scorecard_latest.md (engine refreshes every ~15 min) |
| tests/test_gem_score.py | vetoes, removed gates, factor behaviour, sizing/fill costs, -12% halt + next-day reset, no duplicates, exit_lock_50 (calibration test skips without an outcomes file) |
| gem_state.json / gem_status.json / gem_alerts.jsonl / gem_paper.log | engine state, heartbeat, ping lines for routines, log |
| ../paper/gem_journal.jsonl | learning journal: SCORE (label changes), ENTER / ENTRY_SKIP with full factor breakdown + cost model, CLOSE with P&L and exit reasons |

## Hard vetoes (the only "no"s)
live mint authority; live freeze authority; honeypot / Jupiter says no sell route (UNKNOWN is not a veto); Rugcheck `rugged`;
Rug Shield REJECT (ring-traced deployer proceeds: `rug_shield_rejects.json` or a REJECT line in wallet_watch/ring_flags.ndjson);
liquidity < $5K (bonding-curve coins use an estimated curve liquidity); m5 <= -50%; already dumped > 80% from the highest price seen (or h6 <= -80%).
Everything else ($25K floor, fresh < 1 h, vertical, v/l > 15, cheap screen) is now a weighted factor.

## Paper entries
score >= paper_entry, no veto, a new call/wallet input in the last 45 min, book not under the -12% daily halt (equity-based, counts
unrealized; resets at the first run of each ET day) and loss ladder allows entries, max 6 open gem positions, <= 25% of equity in gem
positions, no re-entry on the same mint within 24 h. Size 2% of paper equity at the threshold rising linearly to 5% at threshold+20
(x ladder size_mult). Fill = DexScreener price x (1 + 1.5% fee) x (1 + constant-product impact size/(liq/2+size)) x (1 + chase
0.5% + 0.02% per +1% m5, max 3%). Exits: desk/paper/adaptive_watcher.py applies protocols/exit-rules.md v3.2a (stop -30%, lock at
+10%, trails, BREAKING/FADING, 24 h time stop, RUG/SANITY guards) to gem positions like any book position; the engine kicks
ensure_watcher.sh right after an entry.

## How to read the scorecard (desk/reports/gem_scorecard_latest.md)
- Book line: paper equity vs the book's start (desk/paper/paper_config.json starting_bankroll_usd: configurable $250-500, default $250; the reference install started at $100), today's % (ET day), whether the -12% halt is on, loss-ladder state.
- "Gem trades, last 24 h": every gem entry in the window, open ones marked at last price net of the 1.5% exit cost. hit = trades
  with P&L > 0. "return on staked" = P&L / dollars put in. best/worst by %.
- "Closed only": realized results; this is the honest number. "Since inception": all gem trades ever.
- "By entry score": does a higher entry score earn more? If 62-69 loses and 70+ wins, raise thresholds.paper_entry.
- "Did higher scores run?": every coin that reached WATCH (45+) in the window, bucketed by its max score: share that reached 2x
  from the price when it first hit WATCH, share now <= 0.3x (dumped), median peak. Healthy calibration = 2x-rate rises and
  dump-rate falls as the bucket rises. If a low bucket runs as often as a high one, the weights are not helping; re-tune.
- `--shadow` adds a RESEARCH-ONLY "wide exit" P&L per closed trade (lock at +50% instead of +10%) to test the exit rules.
- Everything is small-sample until n >= 30 closed trades. Paper fills are modeled, not real.

## Re-tune
1. `python3 collect_outcomes.py` (after a session) 2. edit weights.json 3. `python3 backtest.py` (check the sweep) 4. `python3 -m unittest discover -s tests`.

## Experiment contrarian_1p5x (PAPER ONLY) - desk/scoring/contrarian.py
- Question: do the calls our filters SKIP still pay with a quick +50% exit? Hooked from gem_paper.cycle; config weights.json
  experiments.contrarian_1p5x (reloaded every 5 min; active=false turns it off).
- Entry: candidate from the owner's sources (tg_watch channels = the same merge tg_watch.load_channels() does; caller watch = wallet_watch
  caller_feeds tg; wallet watch / flywheel watched wallets), fresh call (<= fresh_min 20 min), score >= min_score 30, that the gem engine
  would NOT enter (score < paper_entry, or a SOFT veto 'already dumped from peak'), and not a mint the gem engine took in the last 24 h.
  Never a hard veto: live mint/freeze authority, honeypot/no sell route, Rugcheck rugged, Rug Shield REJECT, liq < $5K, m5 <= -50%.
  Fail-closed: no Rugcheck report, unknown liquidity or sell route not OK -> no entry.
- Tags: skip_reasons (dumped_from_peak, momentum, vertical, fake_volume (h1 vol/liq > 15), already_ran (>= 5x since first call),
  liquidity_cap (liq < $25K or liq/mcap < 6%), fresh_lt_1h, promo_only, ring_flag, copycat, x_paid_promo, low_score) + primary_skip;
  sources + primary_source (latest call).
- Size $5 fixed (size_usd) from its own sub-book desk/paper/contrarian_1p5x_book.json (start = paper_config.json bankroll unless
  start_usd is set). Exits: TP 1.5x entry fill, stop -35%, 24 h timeout, RUG if liq < $100; fills = same cost model as gem entries.
  Every entry is tracked 24 h from entry (also after the exit): peak_x, min_x, reached 1.5x/2x/3x times, post_exit_peak_x.
- Journal desk/paper/contrarian_1p5x_journal.jsonl (CTR_ENTER / CTR_EXIT / CTR_SKIP / CTR_TRACK_DONE). Scorecard:
  desk/reports/contrarian_1p5x_scorecard_latest.md (+ dated .md, latest .json) and a separate section at the end of
  gem_scorecard_latest.md: TP hit rate, avg result, reached 1.5x/2x/3x, median max, end equity, by skip reason and by source.
- Untouched: main paper book, gem thresholds, exit rules v3.2a + exit_lock_50, protocols/exit-rules.md, live desk rules.
- Tests: tests/test_contrarian_paper250.py (bankroll reset + experiment, incl. mutant checks).
