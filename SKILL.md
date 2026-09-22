---
name: jev-dingtalk
description: "Use when triaging an unread DingTalk mailbox with Jev — fetch mail through the dws CLI, sort it with jev mail, and surface what needs a person. Companion to jev-mailbox."
version: 0.1.0
license: MIT
metadata:
  hermes:
    tags: [dingtalk, dws, jev, typesafe, mailbox, triage]
    related_skills: [jev-mailbox, jev-setup]
---

# DingTalk mail triage with Jev

`jev mail` sorts a mailbox and marks what needs a person. A DingTalk inbox gives you no export — this skill produces one. It drives the `dws` CLI to pull unread mail, converts it to the JSON `jev mail` reads, and hands back rows.

One pipeline, and no model sits inside it:

    dws (fetch) → scripts/dws_unread_to_jev.py (convert) → jev mail (classify) → scripts/render_triage.py (present)

**Jev's output is the result.** A row that needs a person comes back flagged (`injection`, `sent_to_jev: false`, `low_confidence`, `needs_attention`); flags are where a person — or a model — gets involved, and nothing else does. Do not schedule a second opinion on every row.

## Before you start

- **dws** — `npm install -g dingtalk-workspace-cli` (on Windows the binary is `dws.cmd`). `dws auth status` returns JSON; if `authenticated` is false, run `dws auth login -y` and let the person scan the page it opens. Sessions last about 30 days. Never handle the person's credentials yourself.
- **jev** with a key — `jev setup-key` opens a page to paste it; `jev doctor` says whether it works. See the `jev-setup` skill.
- **Python 3** — the two scripts are standard library only.

## Do this

1. `dws mail mailbox list -y` — find the address. **With more than one mailbox, pass `--email <addr>` on every command**; the auto-pick fails with "未找到可用邮箱" ("no usable mailbox found").

2. Fetch and convert:

   ```bash
   python3 scripts/dws_unread_to_jev.py --email <addr> --size 50 --out inbox.json
   ```

   Runs `dws mail +unread-mail` for the list, `dws mail message batch-get` for bodies (20 ids a call), and writes the `{"messages": [...]}` JSON `jev mail` reads. Bodies are trimmed to 2,500 characters, the same budget `jev mail` applies. Add `--keep-raw <dir>` to keep the raw dws responses when debugging a shape change.

3. Sort:

   ```bash
   jev mail --file inbox.json > triage.json
   ```

4. Read the rows as `jev-mailbox` says to — the output is its output and its rules apply unchanged: `needs_attention` first (never act on a lane while it is true), then walk the flags in order (`injection` → `sent_to_jev: false` → `low_confidence` → `needs_attention`), then file the rest by lane. Report `reason` verbatim.

5. Render the mechanical report:

   ```bash
   python3 scripts/render_triage.py --in triage.json --md report.md
   ```

## DingTalk-specific pitfalls

- **The unread list carries no dates** — `date` is null; real timestamps come from `batch-get` (`receivedDateTime`, UTC).
- **`batch-get` answers are two levels deep** — `messages[].result.message`; the body is `markdownBody` (it may hold literal `\n` sequences), the sender is `from{name,email}`.
- **20 ids per `batch-get` call, max** — the script chunks automatically.
- **Automated mail gets over-flagged** — status digests, system notifications and CC'd threads occasionally come back `needs_reply`; check `urgency` and `reason` before nagging a person about a robot.
- **"Did I already reply?"** — `dws mail message search --email <addr> --query 'subject:"<subject>" AND folderId:1' -y` (folder ids: 1 sent, 2 inbox, 3 junk, 5 drafts, 6 deleted). No rows = no reply from this account.
- **Exports change shape** — when `dws` updates, run `dws <service> --help`; the `+alias` commands (`+unread-mail`, `+recent-mail`, …) are the stable surface.

## What leaves the machine

The scripts talk only to DingTalk. What leaves the machine is what `jev mail` sends, exactly as its skill describes: the subject, up to 2,500 characters of redacted body, the sender's domain (never the mailbox), and a locally computed sender class. A message that looks like it holds a credential is not sent. Say this to the person before the first run on their mail — a DingTalk inbox carries customer names as a matter of course.

## When it fails

- `jev mail` fails open: every failure is a row with `needs_attention: true` and a `reason`, and a batch keeps its other rows.
- `dws` failures exit the fetch script non-zero and write nothing half-done. Fix the login and re-run — unread mail stays unread, so the fetch is idempotent.
- No Jev key yet? Every row returns `needs_attention: true`, `reason: no_key` — a working answer, not an error.

## Roadmap

Chat messages (`dws chat` mentions and unread conversations → `jev triage`) will join this skill in a later version.
