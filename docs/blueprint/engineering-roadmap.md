# Umbrella engineering roadmap (Priority 4, PROPOSAL)

Status: **PROPOSED**. No website, app, portal, simulator or launchpad described here is built or deployed.
Written 2026-10-18 (ET) by Umbrella Hub (HQ) from Ray's blueprint parts 1-3 and an outside repo audit.
Related: [media-entertainment.md](media-entertainment.md), [developer-network.md](developer-network.md), [desk/](../../desk/README.md), [CAPABILITIES](../CAPABILITIES.md).

Evidence labels: VERIFIED, DERIVED, REPORTED, NOT_RUN, BLOCKED, UNKNOWN, CONFLICT.

---

## 0. Protection check

Core mission (Ray, 2026-10-18 10:10 PM ET): **Umbrella shields and protects its users and community and keeps everything
safe, in everything it does. It is free to grow into new trades, skills and hobbies.**

| Question | Answer |
| --- | --- |
| Who could be harmed? | Site visitors and members (data, money), owners using the template, token buyers on any launchpad, contributors, HQ. |
| Worst failures? | Real money at risk without consent (launchpad, trading); leaked personal data from a site database; a dashboard that can *do* things instead of only showing them; legal exposure from launching tokens. |
| What protects? | Read-only first everywhere; paper/simulation before anything real; testnet before mainnet; audits + legal before any launch; **no real-money launch without Ray's yes**; row-level security and no personal data in the first site phases; every phase ends in an audit-request PR. |
| What does this file change? | Nothing. It is a plan. |
| Locked (VERIFIED in CAPABILITIES §9) | live trading, fund moves, signing, wallet connect, spending, installing tools, creating bots, posts as the owner, credentials, safety-limit changes. |

---

## 1. Principles

1. **Read-only before read-write.** Every surface ships first as a viewer.
2. **Paper before real.** Trading and launchpad work stays in paper/simulation/testnet until Ray types yes.
3. **One change, one PR, one audit-request.** Each phase below ends with a PR to `main` labelled `audit-request`; nothing merges without review.
4. **No secrets in the repo.** Env vars live on the host; examples use placeholders (VERIFIED pattern in `tools/`).
5. **Never call a proposed feature deployed.** Status labels only.

## 2. Website (Next.js / TypeScript / Tailwind / Supabase)

Stack (REPORTED: Ray, part 2): Next.js (App Router) + TypeScript + Tailwind; Postgres via Supabase; Expo for mobile later.
Sections (REPORTED): HQ, tools directory, bot marketplace, developer portal, academy, trading lab, studio, launchpad, dashboard.

| Phase | Scope | Data | Write paths | Exit gate |
| --- | --- | --- | --- | --- |
| W0 | Repo scaffold, lint, type-check, CI build; static pages rendering README/CAPABILITIES/blueprint docs | repo markdown | none | builds clean; audit-request |
| W1 | **Read-only dashboard**: release list, pack contents, routine catalogue, open audit-requests, (mock) contribution queue counts | GitHub public API or a static JSON export | none | no auth needed; no personal data; audit-request |
| W2 | Supabase read-only mirror of public repo metadata; RLS on every table; anon key read-only | public metadata only | server-side sync job only | RLS reviewed; secrets only in host env |
| W3 | Owner sign-in (owner only) for private views: counts and statuses, never content | aggregates | none from UI | auth reviewed; audit-request |
| W4 | Tools directory + bot marketplace listing (approved registry entries only) | public registry | none | Rights/licence review |
| W5+ | Any write action (e.g. submitting a contribution via the site) | — | proposed separately | owner yes + security review |

Never on the site: keys, wallet lists, private channels, creator/adult content, subscriber data, consent records, live trading controls.

## 3. Media Studio

Follows [media-entertainment.md §8](media-entertainment.md) (M0 spec page -> M1 read-only portfolio of owner-approved all-ages
work -> M2 private production board with counts only -> M3 tool directory -> M4 Academy link-out). Restricted brands never
appear on the public site. Tool installs and spend need the owner's yes.

## 4. Academy

| Phase | Scope |
| --- | --- |
| A0 | Public catalogue of lesson topics from Pack 5 (12 teaching skills, VERIFIED in CAPABILITIES §2.10) |
| A1 | Static lessons (markdown -> pages) with source provenance (`source-provenance-and-license`) |
| A2 | Interactive quizzes with no account (local storage only) |
| A3 | Optional accounts; minimal data; age-appropriate, all-ages content only |

## 5. Developer portal

Follows [developer-network.md](developer-network.md): P0 contributor guide + schema docs -> P1 manifest validator page (runs the
JSON Schema in the browser; uploads nothing) -> P2 public registry view (approved entries, provenance) -> P3 PR-based submission
helper that only prepares a PR in the contributor's own fork. HQ never holds contributor credentials.

## 6. Trading research and paper simulation (PAPER ONLY)

What exists today:
- **Paper gem desk** in [`desk/`](../../desk/README.md): weighted gem score, paper bankroll $250-500 (default $250), exit rules v3.2a, `exit_lock_50` and `contrarian_1p5x` paper experiments, scorecards, offline tests (VERIFIED in repo; test count "84" is REPORTED in CHANGELOG, NOT_RUN in this PR).
- **$1,000/day risk paper book** (Ray's rule, 2026-10-18 9:32 PM ET): a fresh $1,000 **paper** allowance each ET day, deliberately high-risk entries from the watcher feeds, midnight ET reset with history kept, winners-only pings. VERIFIED running on the HQ box (heartbeat 2026-10-18 10:15 PM ET); it is **not in this repo** (VERIFIED: no `desk/paper/risk/` on `main`). PAPER ONLY: no wallets, signing or transfers.

Roadmap (PROPOSED):

| Phase | Scope | Guard |
| --- | --- | --- |
| T0 | Publish a generic, sanitized copy of the risk paper book (no channel lists, wallets or tokens) to `desk/paper/risk/` | separate PR + audit-request; owner yes |
| T1 | Deterministic risk engine as a library: loss ladder, daily stop incl. unrealized, size caps; same code for paper and any future live mode | limits can tighten automatically, never loosen (VERIFIED rule) |
| T2 | Add Rugcheck + GoPlus checks to the paper pipeline (REPORTED: Ray part 2), fail-closed for any *live* use; the risk book keeps its documented paper-only exception (unavailable check -> entered with safety=UNVERIFIED) | label every check result |
| T3 | Read-only "trading lab" page: paper scorecards, win rate, sample size warnings (n < 30) | paper data only; no live controls |
| T4 | Live trading | **stays locked** behind the owner's typed yes inside `trading-safety-rules`; not on this roadmap |

Protection note: the risk paper book is designed to lose paper money while learning. Its loose entry rules must never be
reused for live trading; any live path uses T1's engine and Rug Shield's veto.

## 7. Mobile (Expo, later)

| Phase | Scope |
| --- | --- |
| X0 | Not started. Begins only after W3 is stable. |
| X1 | Read-only Expo app mirroring the dashboard (releases, audit-requests, paper scorecards). |
| X2 | Push notifications for owner-approved alert types only. No trading, posting or fund actions from the phone app. |

## 8. Launchpad (research -> local sim -> testnet -> audits + legal)

Scope (REPORTED: Ray parts 1-2): **one EVM chain**, approved-pair registry (Pons V2 approved pairs referenced; Flywheel-style
buyback/burn referenced), bonding curve, graduation, fee controller. The existing `tools/flywheel_watch/` is a read-only
*watcher* of another launchpad (VERIFIED); it is not a launchpad.

| Stage | What | Money | Exit gate |
| --- | --- | --- | --- |
| L0 Research | mechanics, competitor launchpads, failure/rug patterns, regulatory questions, chain choice (one EVM chain, UNKNOWN which) | none | written research with sources |
| L1 Local simulation | contracts + tests on a local devnet (e.g. Foundry/Hardhat, choice UNKNOWN); bonding-curve, graduation and fee maths; adversarial tests (snipers, sandwich, rug paths) | none | test suite VERIFIED, invariants documented |
| L2 Testnet | deploy to that chain's public testnet; approved-pair registry populated with testnet pairs only; read-only UI | test tokens only | 30+ days without critical bugs; audit-request |
| L3 Audits + legal | at least one independent smart-contract audit; legal review of token launch, fees and marketing in relevant jurisdictions | audit/legal spend needs Ray's yes | findings fixed; legal sign-off |
| L4 Limited launch | caps on size and users | real money | **never without Ray's explicit yes**, after L3 |

Approved-pair registry (PROPOSED): a reviewed list of quote assets/pairs the launchpad may use; additions via PR +
audit-request; anything not on the list is rejected by the contracts.

## 9. Growth & expansion: new trades, skills and hobbies

Umbrella may grow into new areas. Each one enters the same way: research -> paper/simulation or draft-only -> owner yes ->
small pilot. Each is tied to a protection rule. All PROPOSED.

| Area | Type | What Umbrella could do | Protection tie |
| --- | --- | --- | --- |
| Personal finance coaching | skill | budgeting lessons built on the read-only Money Desk | read-only; never moves money; no account credentials stored |
| Scam & fraud awareness | skill / community | teach the scam flags the X & TikTok Desk already uses (advance fee, fake sponsors, wallet-connect) | directly protects users; examples scrubbed of real people |
| Cybersecurity hygiene | skill | password managers, 2FA, key rotation, phishing drills for owners | never handles a real secret |
| Photography & visual art | hobby | lessons + AI-assisted editing via the Media Studio | likeness and licence rules (media spec §6) |
| Music production | hobby / trade | beat-making and mixing lessons alongside AI Artists & Music | tool terms checked; no voice cloning without permission |
| Writing & storytelling | hobby / trade | story craft lessons from Stories & IP | original work only; provenance tracked |
| Game design & modding | hobby | design docs, level ideas, art direction | no copied assets; licence checks |
| Fitness & wellbeing | hobby | habit tracking and routines | not medical advice; no health data stored in the repo |
| Cooking & nutrition | hobby | recipe planning, shopping lists | not medical advice; allergy warnings |
| Language learning | skill | Academy lessons with spaced repetition | all-ages; no personal recordings stored |
| Small-business ops | trade | invoicing templates, client CRM drafts | draft-only; no sending; client data stays local |
| Freelance web building | trade | site builds using the website stack | client credentials never in repo; owner approves each deliverable |
| Data analysis | skill | spreadsheets/SQL lessons using public datasets | public or synthetic data only |
| Home & DIY | hobby | project plans and safety checklists | safety warnings first; licensed trades for electrical/gas |
| Travel planning | hobby | itineraries and checklists | no booking or payment without owner yes |
| Community moderation | skill | moderation playbooks for owner communities | protects members; no doxxing; escalation rules |

## 10. 16-item checklist (4 phases)

Phase 1 is "audit bots, skills, repo and routines" (REPORTED: Ray, part 2). Status is VERIFIED (exists and checked today) or
PROPOSED (not done).

| # | Phase | Item | Status | Evidence |
| --- | --- | --- | --- | --- |
| 1 | 1 Audit | Audit loop: AUDIT.md + audit-request issue template + `audit-request` label | VERIFIED | files and label on `main` @ `b1f67ea` |
| 2 | 1 Audit | Full capabilities inventory of bots, skills, routines, tools | VERIFIED | `docs/CAPABILITIES.md` (updated 2026-10-17) |
| 3 | 1 Audit | README updated to the current template version + Pack 1 template link | PROPOSED | README still says "Template link will be added" (VERIFIED) |
| 4 | 1 Audit | Routine budget check against the 50 routines/bot limit, per bot | PROPOSED | limit REPORTED in blueprint part 1 |
| 5 | 2 Contribution architecture | Blueprint specs (media, developer network, roadmap) | PROPOSED | this PR, open, not merged |
| 6 | 2 Contribution architecture | Contribution manifest JSON Schema (draft) | PROPOSED | draft in this PR; example validated locally (see PR) |
| 7 | 2 Contribution architecture | Quarantine branch, CODEOWNERS, branch protection on `main` | PROPOSED | `main` reports `protected: false` (VERIFIED) |
| 8 | 2 Contribution architecture | Static CI: schema, secret scan, dependency scan, no execution | PROPOSED | no `.github/workflows/` (VERIFIED) |
| 9 | 2 Contribution architecture | PRIVACY.md migration for contributions | PROPOSED | diff in developer-network.md §8, not applied |
| 10 | 3 Website & studio | Website spec + W0 scaffold | PROPOSED | §2 |
| 11 | 3 Website & studio | W1 read-only dashboard + mock contribution dashboard | PROPOSED | §2 |
| 12 | 3 Website & studio | Media Studio M0-M1 and Media division role cards | PROPOSED | media-entertainment.md |
| 13 | 3 Website & studio | Academy A0 + developer portal P0 | PROPOSED | §4, §5 |
| 14 | 4 Trading & platform | Paper research base: paper gem desk (repo) + $1,000/day risk paper book (HQ box), paper only | VERIFIED | `desk/` on `main`; risk book heartbeat 2026-10-18 10:15 PM ET on HQ box |
| 15 | 4 Trading & platform | Launchpad L0-L2 (research, local sim, testnet only) | PROPOSED | §8 |
| 16 | 4 Trading & platform | Commercial model (pricing, marketplace terms, revenue share for contributors) | PROPOSED | blueprint order item 6 (REPORTED) |

Mobile (Expo) is deliberately after item 11 and not counted in the 16.

## 11. Open questions

1. Which EVM chain for the launchpad? (UNKNOWN)
2. Host for the website (Vercel or other) and domain? (UNKNOWN)
3. Should the risk paper book be published to the repo (item T0) or stay HQ-only? (UNKNOWN)
4. Who signs off legal for L3? (UNKNOWN)
