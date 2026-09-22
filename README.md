# jev-dingtalk

Triage a **DingTalk** mailbox and its chat with [Jev](https://docs.typesafe.ai): fetch through the `dws` CLI, sort with `jev mail` / `jev triage`, and hand back what needs a reply and what needs a person.

[中文说明](README.zh.md)

## What it does

- Fetches unread DingTalk mail and message bodies via `dws` (dingtalk-workspace-cli), converts them into the JSON `jev mail` reads.
- Sorts with Jev: `needs_reply` / `updates` / `promotional` / `sales` / `spam`, plus urgency and the flags (`needs_attention`, `low_confidence`, `injection`) that say what a person should look at.
- Triages chat records the same way: @-mentions and unread conversations through `jev triage` — one row per conversation; encrypted content is never guessed at.
- **Jev's output is the answer** — no second model pass in the loop. Flags are where a human (or a model) steps in, and nowhere else.
- Renders a plain markdown report. The scripts are Python standard library only.

Companion to [`jev-mailbox`](https://github.com/kerpopule/hermes-jev-skills): that skill sorts an export you already have; this one produces the export for DingTalk, plus the field pitfalls that come with it.

## Usage

```bash
# prerequisites: python3, Node.js (for dws), a Jev API key
npm install -g dingtalk-workspace-cli     # the dws CLI
dws auth login -y                         # scan the page it opens; ~30 days
jev setup-key                             # once

# fetch + sort
python3 scripts/dws_unread_to_jev.py --email you@example.com --size 50 --out inbox.json
jev mail --file inbox.json > triage.json

# report
python3 scripts/render_triage.py --in triage.json --md report.md

# chat records
python3 scripts/dws_chat_to_jev.py --days 7 --out chat_inbox.json
jev triage --file chat_inbox.json > chat_triage.json
python3 scripts/render_chat_triage.py --in chat_triage.json --inbox chat_inbox.json --md chat_report.md
```

To use it as an agent skill, copy this folder into your agent's skills directory (Hermes: `$HERMES_HOME/skills/`). `SKILL.md` has the full walkthrough and the DingTalk-specific pitfalls; `examples/` holds synthetic samples you can dry-run the scripts on.

## License

MIT
