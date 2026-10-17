# How to install the Umbrella template (v9)

The v9 template comes in 5 packs. Pack 1 is the **Umbrella Chief** bot template. Packs 2-5 are JSON files in this folder that your Umbrella Chief bot reads and installs for you, one at a time, with your yes.

Install them **in order**. Pack 1 works on its own; packs 2-5 need pack 1.

## Step 1: Install the Umbrella Chief template (pack 1)

Install the **Umbrella Chief** bot template, version 9. (The template link will be added to the [README](../README.md) when it is published.)

Pack 1 holds the core: safety rules, the getting-started setup, delegation, rooms, routine guards, quality gates, all the core memories, and the hub's `weekly-report` and `update-check` routines. Finish its getting-started setup before adding more packs.

## Step 2: Add packs 2-5, one at a time, in order

For each pack, copy its raw file link from the table below and send it to your Umbrella Chief bot with a message like this:

> Install Umbrella pack 2 from this file: https://raw.githubusercontent.com/Umbrella-Hub-HQ/umbrella-hub/main/packs/umbrella-template-v9-pack2.stage-payload.json
> Add its skills and routines. Ask me yes before each routine. Keep everything paused and in paper mode.

Change the number and link for packs 3, 4 and 5. Wait until one pack is done before sending the next.

| Pack | Name | Raw file link |
| --- | --- | --- |
| 2 | Crypto Desk | https://raw.githubusercontent.com/Umbrella-Hub-HQ/umbrella-hub/main/packs/umbrella-template-v9-pack2.stage-payload.json |
| 3 | Robinhood, Quant & Evolve | https://raw.githubusercontent.com/Umbrella-Hub-HQ/umbrella-hub/main/packs/umbrella-template-v9-pack3.stage-payload.json |
| 4 | Content & Research | https://raw.githubusercontent.com/Umbrella-Hub-HQ/umbrella-hub/main/packs/umbrella-template-v9-pack4.stage-payload.json |
| 5 | Academy & Org | https://raw.githubusercontent.com/Umbrella-Hub-HQ/umbrella-hub/main/packs/umbrella-template-v9-pack5.stage-payload.json |

What your bot does with each file:

1. Reads the JSON file (it lists skills, routines and a short description).
2. Tells you what is in the pack.
3. Saves the skills, and creates each routine **only after you say yes to that routine**. New routines start **paused**.
4. Keeps trading in **paper mode** until you type an explicit yes for live, inside the safety rules.
5. Confirms what it added.

If your bot already has a skill or routine with the same name, it should ask you before replacing it.

## Hub rules

- **No access to anyone's bots or data.** The hub, other owners and their bots can't reach your bot, and your bot never reads or touches a friend's bot or data.
- **Nothing auto-runs.** Packs, routines, updates and reports happen only when you say yes.
- **Your yes on everything.** Each routine, each update and each weekly report needs your approval.
- **Reports are scrubbed.** The weekly report removes names, wallets, keys, emails and other private details, and is posted only after you approve it, from your own GitHub account.
- **Updates are pulled, never pushed.** The update check reads this repo's Releases and installs nothing without your yes.

See [PRIVACY.md](../PRIVACY.md).
