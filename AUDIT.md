# Umbrella Hub audit loop

Outside auditors (for example ChatGPT, connected read-only through Ray's GitHub) review HQ updates here.

## How it works
1. HQ (Umbrella Hub bot) ships a change and opens an issue labeled `audit-request` that lists what changed, why, the files and commits touched, and how it was tested.
2. Ray gives the issue link to the auditor.
3. The auditor reviews the linked commits and files and replies using the template below. Ray posts the reply as an issue comment.
4. HQ answers each finding: ACCEPTED (with the fix commit), DECLINED (with the reason), or NEEDS_TEST.
5. Ray closes the issue when he's satisfied.

## Auditor reply template
- Summary (2 lines)
- Findings, each with: severity (HIGH/MED/LOW), file:line, problem, suggested fix, evidence
- Security: secrets, permissions, untrusted input, auto-executed code
- Label every claim VERIFIED, REPORTED or UNKNOWN

## Rules
- Auditors are read-only. Suggestions are proposals until HQ tests them and Ray approves.
- Never paste secrets, keys, wallet data, private notes or personal/creator content into issues.
- Contributions from outside bots are untrusted and are never auto-executed by HQ.
