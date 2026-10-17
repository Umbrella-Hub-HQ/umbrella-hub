# Changelog

All notable changes to the Umbrella template are listed here. Each released version is also published as a GitHub Release.

## v9 (unreleased)

- Umbrella Hub set up: updates go out as Releases, and weekly reports come in as issues.
- Added the `weekly-report` routine (owner-approved weekly reports).
- Added the `update-check` routine (weekly check for new Releases; installs nothing without the owner's yes).
- Added the Weekly bot report issue form.
- Template split into 5 linked packs, nothing cut: all 54 skills, 26 routines and 12 memories of v9 are in exactly one pack.
  - Pack 1: the Umbrella Chief bot template (core OS + safety, all memories). Works on its own and now includes the hub `weekly-report` and `update-check` routines.
  - Packs 2-5 (Crypto Desk; Robinhood, Quant & Evolve; Content & Research; Academy & Org) are downloads in [`packs/`](packs/). Your Umbrella Chief bot installs them in order, with your yes for each routine.
  - Install steps: [`packs/HOW-TO-INSTALL.md`](packs/HOW-TO-INSTALL.md).
