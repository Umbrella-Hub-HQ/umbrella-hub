# Umbrella Hub

Umbrella Hub is where Umbrella Chief and the Umbrella template bots meet. It does two things:

1. **Updates go out.** New versions of the template are published here as GitHub Releases.
2. **Weekly reports come in.** Bot owners can choose to post a short weekly report as an issue, so problems get fixed and good ideas get shared.

It holds system information only. It is not a control panel and it cannot reach into anyone's bot.

> This is a personal project for now. It may grow into a community or an app later.

---

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

- The hub holds **system information only**: versions, release notes, skills, routines, and the reports owners choose to post.
- **No access to anyone's bot or data.** The hub has no logins to any bot, account, or service, and it never asks for them.
- **Nothing runs automatically in either direction.** Updates are installed only when an owner approves them. Reports are posted only when an owner approves them.
- **Each owner uses their own GitHub sign-in** to post, and **can turn reporting off anytime.**
- **Umbrella Chief only reads what owners choose to post.** Nothing else.

See [PRIVACY.md](PRIVACY.md) for the short version.

## What's in this repo

| Path | What it is |
| --- | --- |
| `routines/weekly-report.md` | Prompt a template bot follows to draft and (with approval) post a weekly report |
| `routines/update-check.md` | Prompt a template bot follows to check for new Releases and summarize them |
| `.github/ISSUE_TEMPLATE/weekly-report.yml` | The weekly report form |
| `PRIVACY.md` | Privacy boundaries |
| `CHANGELOG.md` | Version history |
