# Umbrella Developer Network: spec (Priority 3, PROPOSAL)

Status: **PROPOSED**. Nothing here is built or turned on. No workflow, gateway, quarantine branch or registry exists yet
(VERIFIED: `main` at `b1f67ea` has no `.github/workflows/` and no `quarantine/` path).
Written 2026-10-18 (ET) by Umbrella Hub (HQ) from Ray's blueprint parts 1-2 and an outside repo audit.
Draft schema: [contribution-manifest.schema.json](contribution-manifest.schema.json). Related: [AUDIT.md](../../AUDIT.md), [PRIVACY.md](../../PRIVACY.md), [README](../../README.md).

Evidence labels: VERIFIED, DERIVED, REPORTED, NOT_RUN, BLOCKED, UNKNOWN, CONFLICT.

---

## 0. Protection check

Core mission (Ray, 2026-10-18 10:10 PM ET): **Umbrella shields and protects its users and community and keeps everything safe, in everything it does.**

| Question | Answer |
| --- | --- |
| Who could be harmed? | Owners who adopt a contribution (their machines, accounts, money), contributors (their privacy and credit), HQ (supply-chain compromise), the wider community. |
| Worst failure? | Malicious or buggy contributed code runs automatically; a secret or personal data lands in the public repo; HQ gains or is handed credentials into a contributor's systems; a contribution is pushed into bots without the owner's yes. |
| What protects? | Opt-in only; manifest is data, code is never executed by HQ or CI; quarantine; CI schema + secret + dependency scans; human review + audit-request; owner-controlled, versioned, pull-only releases; **HQ holds no credentials into contributors' systems**; untrusted PRs never see privileged tokens. |
| What does this spec change? | Nothing yet. It adds docs and a draft schema only. PRIVACY.md is **not** changed (§8 shows a proposal). |
| Safe default kept | The current approval-only model (README "How updates flow out"; VERIFIED) stays the default inside the gateway (REPORTED: audit recommendation). |

---

## 1. What it is

An **opt-in** network of **independently owned** contributor bots. Each contributor bot belongs to its own owner, runs on its
own machine and accounts, and may send sanitized contributions (skills, routines, tools, role cards, docs, reports) to the hub.
HQ reviews them; good ones can be offered to owners as **opt-in, versioned releases**. Nothing flows automatically in either
direction, which matches today's README/PRIVACY rules (VERIFIED).

Pipeline (REPORTED: Ray, part 2; adapted):

```
Contributor bot (owner-approved)
  -> GitHub gateway: PR from the contributor's own fork, manifest + files only
  -> Quarantine (folder on a quarantine branch, never main)
  -> CI validation (static only: schema, secret scan, dependency scan, policy checks; NO execution)
  -> Human review by HQ + outside audit (audit-request)
  -> Registry: approved | rejected (with reason)
  -> Owner (Ray) approves a release
  -> Versioned GitHub Release; each adopting owner pulls it only on their own yes
```

| Today (VERIFIED in README/PRIVACY/AUDIT) | Proposed addition |
| --- | --- |
| Weekly reports come in as issues, scrubbed, owner-approved | Contributions come in as PRs with a manifest, scrubbed, owner-approved |
| Updates go out as Releases; bots pull; nothing pushed | Same; approved contributions ride inside a Release |
| Outside contributions are untrusted, never auto-executed (AUDIT.md) | Same, enforced by CI design and branch rules |

## 2. Roles

| Role | Who | Can | Cannot |
| --- | --- | --- | --- |
| Contributor owner | independent person | decide what their bot submits; withdraw it | merge; change registry state beyond `submitted`/`withdrawn` |
| Contributor bot | their bot | draft a manifest + files, open a PR from **their own fork with their own sign-in** after their owner's yes | push to this repo's branches; request credentials |
| HQ contribution auditor | Umbrella Hub (HQ) | read, review, label, comment, move to `validated`/`rejected`, propose `approved` | run contributed code on the HQ box or in CI; access contributor systems |
| Outside auditor | read-only (AUDIT.md) | review and reply | change anything |
| Owner (Ray) | repo owner | approve registry entries and releases; change policy | — |
| Adopting owner | any template owner | pull a release, install on their yes | — |

## 3. Sanitized contribution manifests

Every contribution includes `umbrella-contribution.json` matching the draft schema
[contribution-manifest.schema.json](contribution-manifest.schema.json) (JSON Schema 2020-12, version `0.1-draft`).

Sanitization rules (contributor side, before submitting):
- No keys, tokens, passwords, seed phrases, cookies, `.env` files; placeholders only (`YOUR_API_KEY`), as in `tools/` today (VERIFIED).
- No personal data: names, emails, phone numbers, addresses, chat/channel lists, wallet addresses or wallet lists.
- No creator, adult or subscriber content and no consent records (see media-entertainment.md §6).
- No binaries, archives, notebooks with outputs, or minified code. Text source only, under 1 MiB per file.
- Contributor identity is a public GitHub login and bot name only.

Example (illustrative only, no real contributor):

```json
{
  "manifest_version": "0.1-draft",
  "contribution_id": "C-20261018-example-skill",
  "kind": "skill",
  "title": "Example: caption length checker",
  "summary": "Checks draft captions against per-platform length limits. Draft-only.",
  "source": { "type": "original", "url": "https://github.com/example-contributor/example-bot" },
  "license": "MIT",
  "version": "0.1.0",
  "compatible_with": ["v9-pack4"],
  "contributor": { "github_login": "example-contributor", "bot_name": "Example Bot", "owner_consent": true },
  "capabilities": { "requested": ["none"], "network": [], "writes": [], "executes_code": false, "needs_credentials": false },
  "files": [{ "path": "skills/caption-length-check.md", "sha256": "0000000000000000000000000000000000000000000000000000000000000000", "bytes": 900 }],
  "review": { "state": "unreviewed" },
  "tests": { "status": "NOT_RUN" },
  "status": "submitted",
  "attestations": { "no_secrets": true, "no_personal_data": true, "no_creator_or_adult_content": true, "no_wallet_data": true, "no_auto_execution": true }
}
```

## 4. Quarantine (folder + branch)

- Contributions land under `quarantine/<contribution_id>/` on a long-lived branch `quarantine` (PROPOSED), **never on `main`**.
- `main` is protected (PROPOSED): no direct pushes, PR review required, CODEOWNERS = owner/HQ, required CI checks.
  (UNKNOWN whether branch protection is on now; `list_branches` reports `main` as `protected: false` on 2026-10-18, VERIFIED.)
- Moving from `quarantine/` into `packs/`, `tools/` or `docs/` is a separate HQ PR, after review, with an audit-request, and merged only with the owner's yes.
- Rejected contributions are closed with a reason; the folder is removed from the quarantine branch, the PR history stays.
- Nothing in `quarantine/` is ever referenced by a Release, a raw download link, or a routine.

## 5. CI validation (static only, no auto-execution)

PROPOSED workflow `.github/workflows/contribution-validate.yml` (not created in this PR; NOT_RUN):

| Check | What | Fails when |
| --- | --- | --- |
| Schema | validate `umbrella-contribution.json` against the schema | invalid, unknown fields, missing attestations |
| File policy | only listed files present; sha256 match; size and type limits; paths inside `quarantine/<id>/` | extra/binary/oversize files, path traversal |
| Secret scan | a pinned secret scanner (e.g. gitleaks or trufflehog, choice UNKNOWN) on the PR diff | any finding (no allow-list by contributors) |
| Personal/creator data scan | regex + wordlists for emails, phones, wallet address formats, seed-phrase word runs, restricted-content markers | any hit -> human review, default reject |
| Dependency scan | pinned versions only; OSV/GitHub advisory lookup; licence allow-list | ranges, known vulns, disallowed licence |
| Capability policy | `capabilities.requested` within the allowed vocabulary; no live trading/signing/sending | anything outside the vocabulary |
| No-execution guard | CI never installs dependencies or runs contributed code, tests or scripts | (by design) |

Workflow safety rules (PROPOSED):
- Trigger on `pull_request` (not `pull_request_target`) so fork PRs get **no secrets and a read-only token**.
- `permissions: contents: read` only. No deploy keys, no environment secrets, no self-hosted runners for fork PRs.
- Third-party actions pinned by full commit SHA.
- Contributed tests are run, if ever, **only by a human reviewer in a throwaway sandbox**, never on the HQ box with real data.

## 6. Provenance fields (required)

| Field | Meaning | Set by |
| --- | --- | --- |
| `source` | original/fork/adapted/third-party, public URL, commit, upstream list with licences | contributor |
| `license` | SPDX id; UNKNOWN rejected | contributor |
| `version` | semver | contributor |
| `contributor` | GitHub login + bot name + owner consent | contributor |
| `capabilities` | requested capability vocabulary, network hosts, writes, executes_code, needs_credentials | contributor, verified by review |
| `review` | state, reviewers, audit-request link, notes | HQ |
| `tests` | VERIFIED / NOT_RUN / BLOCKED / FAILED + command + evidence | contributor proposes, HQ confirms |
| `status` | submitted -> quarantined -> validated -> approved -> released (or rejected/withdrawn) | HQ; `released` needs the owner's yes |

## 7. Owner-controlled adoption and opt-in versioned releases

1. Approved contributions are bundled into a normal versioned Release (e.g. `v9.1`) with plain-language notes and a
   provenance table (contribution id, contributor login, licence, version, review link).
2. Releasing needs Ray's yes. HQ proposes; it does not publish on its own.
3. Each adopting owner's update-check routine reads the Release and asks them (VERIFIED: `routines/update-check.md` behaviour per README). Nothing installs without their yes.
4. Every contribution is individually optional: an owner can take the Release but skip any contribution.
5. Rollback: previous Release stays available; an owner can uninstall a contribution; HQ can mark a contribution `withdrawn` and publish a fix Release.

### HQ has no credentials into contributors' systems
- HQ never asks for, accepts, stores or uses a contributor's tokens, keys, logins, SSH access, webhooks or API access.
- HQ reads only what contributors post publicly to this repo.
- Contributor bots never get credentials into HQ or this repo beyond their own normal GitHub account (fork + PR).
- If a contributor offers access, HQ declines and tells the owner. If a credential is pasted, HQ tells the contributor to rotate it and removes it from the PR.

## 8. Proposed PRIVACY.md migration (for owner review, NOT applied)

PRIVACY.md is **unchanged by this PR** (VERIFIED: not in the changed files). The diff below is a proposal only.

```diff
 # Privacy

 Umbrella Hub's boundaries:

 - **System info only.** The hub holds versions, release notes, skills, routines, and reports owners choose to post. No personal data.
+- **Contributions are opt-in.** Owners may let their own bot submit a sanitized contribution (manifest + text files) as a pull
+  request from their own GitHub account. Contributions hold no keys, personal data, wallet data, creator content, subscriber
+  data or consent records. See docs/blueprint/developer-network.md.
 - **No access.** The hub has no logins to, and no access to, anyone's bot, accounts, or data.
+- **No credentials either way.** HQ never asks for or accepts credentials into a contributor's systems, and contributor bots
+  get no credentials into the hub.
 - **Nothing automatic.** Nothing runs automatically in either direction. Updates install only with the owner's yes, and reports post only with the owner's yes.
+- **Untrusted until reviewed.** Contributions land in quarantine, are checked by static CI (no code is run) and human review,
+  and reach a Release only with the hub owner's yes. Each owner still installs only what they choose.
 - **Your own sign-in.** Each owner posts with their own GitHub account.
-- **Opt out anytime.** Owners can turn weekly reporting off whenever they want.
+- **Opt out anytime.** Owners can turn weekly reporting and contributions off whenever they want, and withdraw a contribution.
 - **Read-only for Umbrella Chief.** Umbrella Chief only reads what owners choose to post.
-- **Scrub before posting.** Reports must not include names, wallets, keys, emails, or personal details.
+- **Scrub before posting.** Reports and contributions must not include names, wallets, keys, emails, personal details,
+  creator/adult content, subscriber data or consent records.
```

To apply: owner says yes -> separate PR touching only PRIVACY.md (and the README privacy section to match) -> audit-request.

## 9. Rollout (PROPOSED)

| Step | What | Status |
| --- | --- | --- |
| D1 | This spec + draft schema | PROPOSED (this PR) |
| D2 | Owner decision on PRIVACY.md migration | PROPOSED |
| D3 | `quarantine` branch, CODEOWNERS, branch protection on `main` | PROPOSED |
| D4 | CI workflow (static checks only) + tests of the workflow with synthetic manifests | PROPOSED, NOT_RUN |
| D5 | Contribution issue/PR template, contributor guide | PROPOSED |
| D6 | Pilot with one contributor (owner-invited), docs-only contribution | PROPOSED |
| D7 | First opt-in Release containing a contribution | PROPOSED; needs Ray's yes |

## 10. Open questions

1. Secret scanner choice (gitleaks vs trufflehog) and dependency scanner (OSV vs Dependabot). (UNKNOWN)
2. Licence allow-list (MIT, Apache-2.0, BSD, CC-BY?). (UNKNOWN)
3. Do contributors need a code of conduct and a CLA/DCO sign-off? (UNKNOWN)
4. Should code contributions be allowed at all in the pilot, or docs/skills only? (HQ suggests docs/skills only first; DERIVED from risk.)
