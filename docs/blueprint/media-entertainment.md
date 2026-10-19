# Umbrella Media & Entertainment Division: spec (Priority 2, PROPOSAL)

Status: **PROPOSED**. Nothing in this file is built, deployed, installed or turned on. It is a design for owner review.
Written 2026-10-18 (ET) by Umbrella Hub (HQ) from Ray's blueprint parts 1-3 and an outside repo audit.
Related: [developer-network.md](developer-network.md), [engineering-roadmap.md](engineering-roadmap.md), [Pack 4](../../packs/umbrella-template-v9-pack4.stage-payload.json), [CAPABILITIES §2.9](../CAPABILITIES.md).

Evidence labels used here: VERIFIED (checked in this repo or on the HQ box today), DERIVED (worked out from verified facts),
REPORTED (said by Ray, an auditor or a vendor, not checked), NOT_RUN, BLOCKED, UNKNOWN, CONFLICT.

---

## 0. Protection check

Umbrella's core mission (Ray, 2026-10-18 10:10 PM ET): **Umbrella shields and protects its users and community and keeps
everything safe, in everything it does.** For this division that means:

| Question | Answer for this spec |
| --- | --- |
| Who could be harmed? | The owner (reputation, accounts, income), creators and performers, subscribers and fans, people shown or voiced in media, minors who might see content, and the community that installs the template. |
| What is the worst failure? | Adult content, a subscriber list or a consent record leaking into a public repo or an unapproved AI service; a post going out without the owner's yes; a real person's face or voice used without permission; one brand's content showing up on another brand's account. |
| What protects against it? | Draft-only production; **owner approval before any publish, spend or contract**; brand isolation (§5); restricted storage for adult/subscriber/consent material (§6); a Rights & Consent Auditor gate on every release (§3, §4); tool terms checked before use (§7). |
| What does this spec NOT do? | It adds no bot, routine, account connection, tool install, credential or storage. It changes no pack. It does not publish anything. |
| What stays locked? | Everything in [CAPABILITIES §9](../CAPABILITIES.md) (VERIFIED in that doc): posts/messages as the owner, spending, installing tools, creating bots, credentials. This division adds no exceptions. |
| Where does private data live? | Never in this repo. Only generic structure, role cards and checklists go here. |

---

## 1. Purpose and placement

Media & Entertainment becomes a major pillar built alongside Trading, Company & Academy, the Developer Network and
Platform & Launchpad (REPORTED: Ray, blueprint part 3). It sits under the owner and HQ:

```
Owner (Ray)  ->  HQ (Umbrella Chief / Umbrella Hub)  ->  Media Coordinator  ->  8 departments
```

It **extends Pack 4 (Content & Research)**; it does not replace it or add a parallel copy (§2). The existing X & TikTok Desk
is the base seat (REPORTED: Ray, part 3; the desk's role card is VERIFIED in Pack 4 as `specialist-x-tiktok-desk`).

### Departments

| # | Department | Scope | Draws on (existing) |
| --- | --- | --- | --- |
| 1 | Film & Video | short films, series, explainers, Shorts, edits | `ai-video-generation`, `shorts-voiceover-pipeline` |
| 2 | AI Artists & Music | music projects (e.g. Ray.nn), cover art, voice work | `ai-image-generation`, `shorts-voiceover-pipeline` (TTS rules) |
| 3 | Stories & IP | original stories, story universes, AI characters, series bibles | `ai-video-generation` (story/style bible), `ai-image-generation` (identity lock) |
| 4 | Social Media | TikTok, X, Instagram, YouTube: plans, clips, captions, inbox | `specialist-x-tiktok-desk`, `ai-content-studio` |
| 5 | Creator Platforms | subscription platforms (e.g. OnlyFans): planning, scheduling drafts, analytics summaries | new; RESTRICTED (see §6) |
| 6 | AI Production Lab | tool evaluation, workflows (ComfyUI/Wan etc.), prompt logs, QA | `ai-video-generation` step 2 (tool study), `knowledge-bases-and-indexes` |
| 7 | Marketing & Growth | trends, hooks, launches, channel plans, metrics | `ai-content-studio` (Marketing & Growth), `last30days`, `social-research-methods`, Venture & Growth Studio |
| 8 | Media Business | rights, licensing, deals, revenue tracking, contracts (drafts only) | `source-provenance-and-license`, Money Desk (Pack 6, read-only) |

---

## 2. Capability map: Pack 4 -> Media & Entertainment (consolidate, don't duplicate)

All Pack 4 items below are VERIFIED present in `packs/umbrella-template-v9-pack4.stage-payload.json` (13 skills, 2 routines) on `main` at `b1f67ea`.
The rule: **each capability has one home.** New departments reference the existing skill instead of copying it.
A Pack 4 item that serves several departments is listed once, with "shared".

| Pack 4 item (type) | Today | Home in new structure | Action (PROPOSED) |
| --- | --- | --- | --- |
| `ai-content-studio` (skill) | Creator/Brand, AI Media Studio, Marketing & Growth divisions; approval queue; voice profile; viral scripts; creator watch | Marketing & Growth (owner); shared with Social Media | Keep. Rename its "AI Media Studio" sub-division to point at Film & Video + AI Production Lab. Add a brand tag to each queue item (§5). |
| `shorts-voiceover-pipeline` (skill) | local yt-dlp/whisper/ffmpeg/TTS Shorts, draft-only | Film & Video; TTS rules shared with AI Artists & Music | Keep as is. Repurposing Agent uses it. |
| `ai-video-generation` (skill) | brief -> tool study -> story -> style bible -> generate -> QA -> edit -> draft | Film & Video (generation), AI Production Lab (tool study) | Keep. Tool-study step feeds the §7 candidate list. |
| `ai-image-generation` (skill) | style lock, identity lock, panels, avatars | Stories & IP (characters), AI Artists & Music (cover art) | Keep. Character Designer uses identity lock. |
| `source-provenance-and-license` (skill) | origin, date, label, reuse rights; unknown rights => link only | Media Business; gate used by Rights & Consent Auditor | Keep; extend (PROPOSED) with consent-record *reference IDs* (never the records). |
| `hq-humanizer-clarity` (skill) | plain writing, honest voice, no detector evasion | shared (all departments) | Keep. |
| `last30days` (skill) | 30-day cited trend brief | Marketing & Growth; Trend Researcher | Keep. |
| `social-research-methods` (skill) | X/Reddit/YouTube methods, partial-read honesty | Marketing & Growth; Trend Researcher | Keep. |
| `knowledge-bases-and-indexes` (skill) | platform guides index, links log, landscape | AI Production Lab (tool index) | Keep. |
| `specialist-content-studio` (role card) | AI media seat; drafts into approval queue | **Becomes the Media Coordinator** (or the Video Production Manager) | Consolidate: no second "media coordinator" card. |
| `specialist-x-tiktok-desk` (role card) | private, read + drafts for owner's X and TikTok | Social Media (base seat) | Keep private. Extend scope to IG/YT clips only on the owner's yes. |
| `specialist-venture-studio` (role card) | weekly product loop, GO/HOLD/KILL | Marketing & Growth + Media Business (strategy) | Keep; media bets go through its loop. |
| `specialist-utility-bots` (role card) | small single-purpose bots | optional helpers (e.g. Copy Humanizer, Game/Art Director) | Keep. |
| `content-draft-batch` (routine) | drafts into queue, never posts | Marketing & Growth / Social Media | Keep; add brand tag. |
| `knowledge-index-update` (routine) | weekly guides/links check | AI Production Lab | Keep. |

Gaps (no home today, DERIVED): subscription-platform planning (Creator Platforms), music production workflow,
story-universe continuity, audience analytics, monetization analysis, consent auditing. These are filled by the registry in §3,
each as a role card that **reuses** the skills above. No new skill duplicates an existing one.

---

## 3. Specialist-agent registry

"Covered today" means a seat that exists and can do most of the job now. Status labels describe the seat in the template
(VERIFIED in pack files) or as reported by Ray/HQ.

| Role | Department | Job (one line) | Covered today by | Coverage | Gap / PROPOSED change |
| --- | --- | --- | --- | --- | --- |
| Scriptwriter | Film & Video, Stories & IP | loglines, beat sheets, scripts, hooks | Content Studio (`ai-content-studio` viral scripts) | PARTIAL (VERIFIED card exists) | add long-form/series scripts; reuse skill |
| Story Universe Manager | Stories & IP | series bible, canon, timelines, character continuity | none | NONE | new role card; uses `ai-video-generation` style bible + `ai-image-generation` identity lock |
| Music Producer | AI Artists & Music | song briefs, lyrics drafts, stems, release packages | none | NONE | new role card; tool terms (§7) checked first |
| Character Designer | Stories & IP | character sheets, identity locks, AI characters | Content Studio (`ai-image-generation`) | PARTIAL | new card or Utility "Game/Art Director"; no real-person likeness without permission |
| Video Production Manager | Film & Video | shot lists, generation runs, QA, edit, export | Content Studio (`ai-video-generation`) | PARTIAL | may be the same seat as Media Coordinator |
| Trend Researcher | Marketing & Growth | trends, hooks, competitor creators | Venture & Growth Studio + `last30days` | COVERED (VERIFIED skills) | none; route media questions to it |
| Repurposing Agent | Social Media | long-form -> clips, captions, per-platform cuts | **X & TikTok Desk** (social + clips; absorbed Clip Bot, REPORTED) with `shorts-voiceover-pipeline` | COVERED (REPORTED) | confirm clip scope on the desk's card (UNKNOWN whether the installed card says so) |
| Audience Analytics | Marketing & Growth | performance of approved, published posts | Content Studio job 4 (track performance) | PARTIAL | read-only analytics; aggregate numbers only; no subscriber-level data |
| Monetization Analyst | Media Business | revenue mix, pricing, sponsorship terms (drafts) | Venture & Growth Studio; Money Desk (Pack 6, read-only) | PARTIAL | new card; never moves money or signs |
| Rights & Consent Auditor | Media Business (gate for all) | checks licenses, likeness/voice permission, consent-record *references*, platform terms before any release | `source-provenance-and-license` (partial) | PARTIAL | new card; holds a **veto** like Rug Shield: missing consent = BLOCKED |
| *(Lessons)* | Academy media | teaching videos, visual lessons | **Academy** (Pack 5, 12 teaching skills, VERIFIED) | COVERED | Academy covers lessons; Media only helps produce |

Rules for every new card (PROPOSED): created only on the owner's typed yes, starts at autonomy L1, draft-only, uses the
standard Pack 4 safety locks block, at most one routine until it proves useful.

---

## 4. Production workflow (owner approval before any publish)

```
Owner brief
  -> Media Coordinator (plan, brand tag, budget = 0 unless owner says otherwise)
  -> Research / Writing / Character studio (Trend Researcher, Scriptwriter, Story Universe Manager, Character Designer)
  -> Production (Video Production Manager, Music Producer, AI Production Lab)
  -> Edit + QA (continuity, artifacts, captions, AI labels where platforms require them)
  -> Rights & Consent gate (licenses, likeness/voice permission, consent reference present, tool terms OK)  [veto]
  -> Approval package to the OWNER (draft, brand, platform, sources, licenses, risks)
  -> OWNER APPROVES THIS EXACT ITEM            <-- nothing goes out without it
  -> Publish (owner's action, or a bot action only after that exact approval)
  -> Analytics (aggregate, read-only) -> lessons -> next brief
```

| Gate | Who | Pass condition | Fail result |
| --- | --- | --- | --- |
| G1 Brief | Coordinator | brand, platform, goal, must-avoid list set | back to owner |
| G2 QA | Video Production Manager | QA checklist from `ai-video-generation` step 6 passes | regenerate (capped retries) |
| G3 Rights & Consent | Rights & Consent Auditor | every asset has license/permission; consent reference exists for any person shown; tool terms allow the use | BLOCKED; cannot be overruled by HQ |
| G4 Owner approval | **Owner only** | owner approves the exact item | stays a draft |
| G5 Post-publish | Audience Analytics | aggregate metrics logged | n/a |

HQ delegation ("HQ approves for the owner", CAPABILITIES §6) does **not** cover G4: posts sent as the owner, spending and
contracts are on the owner-only locked list (VERIFIED in CAPABILITIES §6 and §9).

---

## 5. Brand-isolation rules

Brands and channels in scope (REPORTED: Ray, part 3): HD Productions Network, Ray.nn (music), original stories, AI characters,
TikTok, X, Instagram, YouTube, OnlyFans, Academy media.

1. **One brand tag per item.** Every draft, asset folder, prompt log and queue row carries exactly one brand tag. No tag = not publishable.
2. **Separate workspaces.** Each brand has its own private folder, voice card, style bible and approval queue on the owner's machine. Nothing brand-specific is in this repo.
3. **No cross-posting by default.** Moving an asset from one brand to another needs the owner's yes for that asset.
4. **Adult isolation (hard rule).** Creator-platform (OnlyFans) material never enters a general/all-ages brand's folder, queue, prompt log, analytics or model context, and general-brand bots never read the restricted area. Separate seat, separate storage, separate accounts.
5. **Academy media stays all-ages and educational.** Academy owns lesson content; nothing from Creator Platforms is ever reused there.
6. **Account separation.** Each platform account is connected only by the owner, only to the seat that needs it, read + drafts by default. No bot gets a credential for a brand it does not serve. HQ holds no social credentials in the repo.
7. **AI characters are their own IP.** Each has a character sheet and an "is AI" disclosure where platforms require it. An AI character is never presented as a real person, and never based on a real person without written permission.
8. **Analytics per brand only.** Aggregates are not mixed across brands in a way that could identify a subscriber.
9. **Private desk stays private.** The X & TikTok Desk remains outside company rooms and exports (VERIFIED in its Pack 4 card).

---

## 6. Rights-and-consent safeguards

Hard rules (PROPOSED for the division; consistent with AUDIT.md "never paste ... personal/creator content", VERIFIED):

| Data class | Allowed where | Never allowed |
| --- | --- | --- |
| Adult content (images, video, audio, text) | owner-controlled restricted storage only | this repo, any public repo, issues/PRs, weekly reports, template packs, any AI service not approved for adult use by the owner, general-brand folders |
| Subscriber / fan data (names, handles, messages, payments, lists) | the platform itself; owner-controlled restricted storage | this repo, reports, prompts to unapproved AI services, analytics exports below aggregate level |
| Consent records (model releases, IDs, age verification, signed permissions) | owner-controlled restricted storage, encrypted | this repo, any AI service, chat logs, prompt logs; bots reference them only by an opaque ID |
| Real-person likeness or voice | only with written permission on file (referenced by ID) | voice cloning or face use without it; deceptive deepfakes |
| Third-party media | per its license (`source-provenance-and-license`) | unknown rights => link only |

Process rules:
- The Rights & Consent Auditor sees only **whether** a consent reference exists and is current, never the document.
- Every performer and every person shown must be an adult with verified consent recorded outside the repo; missing = BLOCKED.
- "Approved AI service" means the owner has approved it for that data class **and** its terms allow the use (§7). Default for adult and subscriber data: **no AI service approved** (UNKNOWN for every tool until checked).
- If any restricted item is found in the repo or a report: stop, tell the owner, remove it from the working tree, and treat history rewriting/rotation as an owner decision.
- CI (developer-network.md §5) adds a scan for restricted-content paths and keywords before anything merges (PROPOSED, NOT_RUN).

---

## 7. Tool candidate list (all NOT_TESTED)

Nothing here is installed, purchased or connected. Pricing and terms change; every row must be checked against the vendor's
current terms page, with a date, before use. Columns "Commercial use" and "Adult use" are **UNKNOWN until checked**; the
check is an AI Production Lab + Rights & Consent task.

| Tool | Category | Local / cloud | Test status | Commercial use allowed? | Adult use allowed? | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Runway | AI video | cloud | NOT_TESTED | UNKNOWN (check terms) | UNKNOWN (check terms) | |
| Kling | AI video | cloud | NOT_TESTED | UNKNOWN | UNKNOWN | |
| ComfyUI | image/video workflows | local | NOT_TESTED | UNKNOWN (tool licence + each model's licence) | UNKNOWN (per model) | blueprint studio core (REPORTED) |
| Wan 2.2 | open video model | local | NOT_TESTED | UNKNOWN (check model licence) | UNKNOWN | runs inside ComfyUI (REPORTED) |
| Suno | AI music | cloud | NOT_TESTED | UNKNOWN (plan-dependent, check) | UNKNOWN | |
| Udio | AI music | cloud | NOT_TESTED | UNKNOWN | UNKNOWN | |
| BandLab | DAW / music | cloud + app | NOT_TESTED | UNKNOWN | UNKNOWN | |
| DaVinci Resolve | edit / color | local | NOT_TESTED | UNKNOWN | UNKNOWN | |
| CapCut | edit | app/cloud | NOT_TESTED | UNKNOWN (check template/asset terms) | UNKNOWN | |
| Descript | edit / transcription | cloud | NOT_TESTED | UNKNOWN | UNKNOWN | |
| ElevenLabs | voice / TTS | cloud | NOT_TESTED | UNKNOWN | UNKNOWN | never clone a voice without written permission |
| Coqui (TTS) | voice / TTS | local | NOT_TESTED | UNKNOWN (check model licence) | UNKNOWN | |
| WriterDuet | screenwriting | cloud | NOT_TESTED | UNKNOWN | UNKNOWN | |
| Celtx | screenwriting / pre-production | cloud | NOT_TESTED | UNKNOWN | UNKNOWN | |
| Notion | planning / docs | cloud | NOT_TESTED | UNKNOWN | UNKNOWN | never for adult/subscriber/consent data unless owner approves |
| Airtable | tracking / database | cloud | NOT_TESTED | UNKNOWN | UNKNOWN | same restriction as Notion |

Also mentioned in the blueprint (REPORTED, not in scope of this table): Blender, Canva, Ollama, Hugging Face.

Evaluation template per tool (PROPOSED): terms URL + fetch date; commercial use (Y/N/plan); adult use (Y/N); data retention and
training-on-inputs policy; cost per minute/track with source + date; local vs cloud; one sample run on **non-personal test
input**; verdict ADOPT / TRIAL / HOLD / REJECT. Installing or paying for any tool needs the owner's yes (locked list).

---

## 8. Media Studio website roadmap (PROPOSED)

Lives under the main site plan in [engineering-roadmap.md §2](engineering-roadmap.md). Public pages show only approved,
published, all-ages work. Restricted brands never appear on the public site.

| Phase | What | Data | Gate to next phase |
| --- | --- | --- | --- |
| M0 | Static spec page: departments, workflow, safety rules (this doc, rendered) | none | owner yes |
| M1 | Read-only portfolio: owner-approved, already-published all-ages items (links/embeds) | public links only | owner approves each item listed |
| M2 | Private production board (signed-in owner only): queue status counts per brand, no media files | counts only | auth + RLS reviewed; audit-request PR |
| M3 | Tool-evaluation directory (from §7) | public vendor info | Rights & Consent review of wording |
| M4 | Academy media hub link-out | Academy lessons | Academy owner sign-off |
| Never | Hosting adult content, subscriber data or consent records on the Umbrella site | n/a | n/a |

---

## 9. Open questions for the owner

1. Is the Content Studio card the Media Coordinator, or should Video Production Manager be a separate seat? (UNKNOWN)
2. Which brands are active now vs later? (UNKNOWN)
3. Where is restricted storage for Creator Platforms, and who besides the owner may read it? (UNKNOWN; must be outside this repo)
4. Confirm the X & TikTok Desk's installed card covers clips (absorbed Clip Bot). (REPORTED, not verified in the repo)
5. Which tools from §7 should the Production Lab evaluate first? (UNKNOWN)
