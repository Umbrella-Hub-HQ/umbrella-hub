# Umbrella Hub

Umbrella Hub is where Umbrella Chief and the Umbrella template bots meet. It does two things:

1. **Updates go out.** New versions of the template are published here as GitHub Releases, plus pack files and tools your bot downloads.
2. **Weekly reports come in.** Bot owners can choose to post a short weekly report as an issue, so problems get fixed and good ideas get shared.

It holds system information only. It is not a control panel and it cannot reach into anyone's bot.

> This is a personal project for now. It may grow into a community or an app later.

**What the template can do:** see **[docs/CAPABILITIES.md](docs/CAPABILITIES.md)** for the full, bot-by-bot list (features, safety rails, routines, tools, setup, what stays locked). Latest changes: [CHANGELOG.md](CHANGELOG.md) (2026-10-17 update).

---

## What's new (2026-10-17)

- **Pack 6: Live Watchers & Brain** (add-on, 8 skills, 7 routines): free-first Solana data, a near-real-time public Telegram call watcher, multi-chain wallet watch with the insider-ring rule, a launchpad launch/migration watcher, wallet deep-dive methods with multi-currency PnL, Perps Lab (learn + paper only), the Brain second-brain bot, and the daily-stop/delegation addendum.
- **Generic tools** in [`tools/`](tools/): `sol_data` (+ `pnl_multi`), `tg_watch`, `flywheel_watch`, `ring_filter`. Example configs only: no keys, wallets or channel lists.
- **Full capabilities doc:** [docs/CAPABILITIES.md](docs/CAPABILITIES.md).

## Install the template

The v9 template is 5 linked packs, plus the optional pack 6 add-on. Install them in order; see **[packs/HOW-TO-INSTALL.md](packs/HOW-TO-INSTALL.md)** for plain step-by-step instructions.

**Pack 1: Umbrella Chief bot template (v9).** Core OS and safety: safety rules, getting-started setup, delegation, rooms, routine guards, quality gates, all core memories, and the hub `weekly-report` and `update-check` routines. Works on its own. *Template link will be added here when it is published.*

**Packs 2-6: downloads.** Give your Umbrella Chief bot the raw file link and ask it to install the pack. It adds the skills and routines only with your yes, and keeps everything paused and in paper mode.

| Pack | Name | What's in it | Download (raw) |
| --- | --- | --- | --- |
| 2 | Crypto Desk | Crypto intelligence OS, Rug Shield (security + risk veto) and Trading Scout role cards, crypto move cards, team-trading clear verdict: discovery, caller watch/pipeline, fast-lane, market brief, paper/position monitors, filter test routines (5 skills, 9 routines) | [umbrella-template-v9-pack2.stage-payload.json](https://raw.githubusercontent.com/Umbrella-Hub-HQ/umbrella-hub/main/packs/umbrella-template-v9-pack2.stage-payload.json) |
| 3 | Robinhood, Quant & Evolve | Robinhood trading rules, role card and four-routine set, trading protocols, Quant Lab and desk playbooks library, capped-wallet engine, evolve/deeper triggers, self-update, shadow voting (10 skills, 7 routines) | [umbrella-template-v9-pack3.stage-payload.json](https://raw.githubusercontent.com/Umbrella-Hub-HQ/umbrella-hub/main/packs/umbrella-template-v9-pack3.stage-payload.json) |
| 4 | Content & Research | Draft-only AI content studio, Shorts/voiceover, AI video and image, social research methods, last30days, writing-clarity check, source provenance, knowledge bases and indexes; Content Studio, X/TikTok desk, Venture Studio and utility-bot role cards (13 skills, 2 routines) | [umbrella-template-v9-pack4.stage-payload.json](https://raw.githubusercontent.com/Umbrella-Hub-HQ/umbrella-hub/main/packs/umbrella-template-v9-pack4.stage-payload.json) |
| 5 | Academy & Org | Academy role card and 12 teaching skills, contrarian third view, Org Architect, org governance, bot design checklist, Memory Transfer and Umbrella Brain role cards; governance-audit routine (18 skills, 1 routine) | [umbrella-template-v9-pack5.stage-payload.json](https://raw.githubusercontent.com/Umbrella-Hub-HQ/umbrella-hub/main/packs/umbrella-template-v9-pack5.stage-payload.json) |
| 6 | Live Watchers & Brain *(new, optional; needs packs 1-2)* | Free-first data providers, Telegram call watcher, multi-chain wallet watch + ring rule, launchpad watcher, wallet deep-dive methods, Perps Lab (learn + paper), Brain second brain, daily-stop/delegation addendum; Telegram call alerts (5 min), wallet watch check (15 min), caller + community watch (30 min), 4 Brain routines (8 skills, 7 routines). Tools in [`tools/`](tools/) | [umbrella-template-v9-pack6.stage-payload.json](https://raw.githubusercontent.com/Umbrella-Hub-HQ/umbrella-hub/main/packs/umbrella-template-v9-pack6.stage-payload.json) |

## How updates flow out (Releases)

Every update is a [GitHub Release](../../releases). Each Release has:

- **A version number** (for example `v9`).
- **Plain-language notes** saying what changed and why, written for bot owners rather than developers.
- **The updated skills and routines** that are part of that version.

How a bot gets an update:

1. The bot's weekly update check (see [`routines/update-check.md`](routines/update-check.md)) reads the latest Release.
2. It compares that with the version it has installed and tells its owner what changed.
3. **The owner decides.** Nothing gets installed unless the owner says yes.

Bots **pull** updates. Nothing is ever **pushed** into a bot from this hub.

## How weekly reports come in (Issues)

Owners who want to help improve the template can post a weekly report:

1. The bot's weekly report routine (see [`routines/weekly-report.md`](routines/weekly-report.md)) collects errors, problems, and any improvements the owner made.
2. It removes private details (names, wallets, keys, emails, personal details).
3. It shows the draft to the owner.
4. Only after the owner says yes, it posts the report as an issue using the **Weekly bot report** form, from the owner's own GitHub account.

Reports are labeled `weekly-report`. Umbrella Chief reads them to plan the next Release.

## Privacy boundaries

- The hub holds **system information only**: versions, release notes, skills, routines, generic tools, and the reports owners choose to post.
- **No access to anyone's bot or data.** The hub has no logins to any bot, account, or service, and it never asks for them.
- **Nothing runs automatically in either direction.** Updates are installed only when an owner approves them. Reports are posted only when an owner approves them.
- **Each owner uses their own GitHub sign-in** to post, and **can turn reporting off anytime.**
- **Umbrella Chief only reads what owners choose to post.** Nothing else.
- **Tools ship without secrets.** Example configs use placeholders such as `YOUR_ALCHEMY_KEY`; real keys, wallet lists and private chat names stay on your own machine (see [.gitignore](.gitignore)).

See [PRIVACY.md](PRIVACY.md) for the short version.

## What's in this repo

| Path | What it is |
| --- | --- |
| `docs/CAPABILITIES.md` | Full capabilities: every bot, feature, safety rail, routine and tool; setup for a friend; what stays locked |
| `routines/weekly-report.md` | Prompt a template bot follows to draft and (with approval) post a weekly report |
| `routines/update-check.md` | Prompt a template bot follows to check for new Releases and summarize them |
| `.github/ISSUE_TEMPLATE/weekly-report.yml` | The weekly report form |
| `packs/HOW-TO-INSTALL.md` | Step-by-step install for the v9 packs and the pack 6 add-on |
| `packs/umbrella-template-v9-pack2..5.stage-payload.json` | Packs 2-5 (Crypto Desk; Robinhood, Quant & Evolve; Content & Research; Academy & Org) for your Umbrella Chief bot to install with your yes |
| `packs/umbrella-template-v9-pack6.stage-payload.json` | Pack 6 add-on: Live Watchers & Brain |
| `tools/` | Generic read-only tools: `sol_data` (+ `pnl_multi`), `tg_watch`, `flywheel_watch`, `ring_filter`, example configs |
| `PRIVACY.md` | Privacy boundaries |
| `CHANGELOG.md` | Version history |
