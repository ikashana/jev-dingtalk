---
name: jev-dingtalk
description: "Use when triaging DingTalk mail or chat with Jev — fetch through the dws CLI, sort it with jev mail or jev triage, and surface what needs a person. Companion to jev-mailbox."
version: 0.2.0
license: MIT
metadata:
  hermes:
    tags: [dingtalk, dws, jev, typesafe, mailbox, triage]
    related_skills: [jev-mailbox, jev-setup]
---

# DingTalk triage with Jev

`jev mail` sorts a mailbox; `jev triage` sorts everything else. DingTalk hands you neither a mailbox export nor a chat export — this skill produces both, drives them through the right Jev command, and hands back rows.

Two pipelines, and no model sits inside either:

    mail:  dws (fetch) → scripts/dws_unread_to_jev.py (convert) → jev mail   (classify) → scripts/render_triage.py (present)
    chat:  dws (fetch) → scripts/dws_chat_to_jev.py   (convert) → jev triage (classify) → scripts/render_chat_triage.py (present)

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

## Chat records

Same discipline, second source — `dws chat`, which offers two read-only views:

```bash
python3 scripts/dws_chat_to_jev.py --days 7 --out chat_inbox.json
jev triage --file chat_inbox.json > chat_triage.json
python3 scripts/render_chat_triage.py --in chat_triage.json --inbox chat_inbox.json --md chat_report.md
```

- `--days N` of **@-mentions** (`dws chat +at-me`) — a message that names you is one someone expects you to read.
- The newest `--per-convo` readable messages of every **unread conversation** (`+messages-list-unread-conversations`), one triage row per conversation — the transcript, not a single message, is the unit that carries "is there an ask here".

`jev triage` is not `jev mail`: mail's five lanes are mailbox semantics. Triage answers `route` (now / today / queue / ignore), `urgency`, `kind`, and the readings `needs_human`, `blocked`, `deadline`, `actionable`. **Read the pile as `route now` + `route today`**; queue is context; ignore is nothing.

Chat notes:

- Timestamps arrive already local (`createTime`) — no UTC conversion, unlike mail.
- `chat message list` answers nest under `result.messages`; mentions arrive pre-projected as `{conversation, sender, text, time}`.
- **Encrypted messages are real.** Some chat content comes back as ciphertext the API cannot read (private messages in particular). Per-message ciphertext is dropped from transcripts with a count at the end of the row; a conversation with nothing readable lands in the `unreadable` list and is printed as "check manually" — never guessed at, never sent to Jev as noise.
- One item can surface twice (an @-mention inside an unread conversation) — that is honest, not duplication to chase.

## DingTalk-specific pitfalls

- **The unread list carries no dates** — `date` is null; real timestamps come from `batch-get` (`receivedDateTime`, UTC).
- **`batch-get` answers are two levels deep** — `messages[].result.message`; the body is `markdownBody` (it may hold literal `\n` sequences), the sender is `from{name,email}`.
- **20 ids per `batch-get` call, max** — the script chunks automatically.
- **Automated mail gets over-flagged** — status digests, system notifications and CC'd threads occasionally come back `needs_reply`; check `urgency` and `reason` before nagging a person about a robot.
- **"Did I already reply?"** — `dws mail message search --email <addr> --query 'subject:"<subject>" AND folderId:1' -y` (folder ids: 1 sent, 2 inbox, 3 junk, 5 drafts, 6 deleted). No rows = no reply from this account.
- **Exports change shape** — when `dws` updates, run `dws <service> --help`; the `+alias` commands (`+unread-mail`, `+recent-mail`, …) are the stable surface.

## What leaves the machine

The scripts talk only to DingTalk; what leaves the machine is what `jev mail` and `jev triage` send, exactly as those skills describe. For mail: the subject, up to 2,500 characters of redacted body, the sender's domain (never the mailbox), a locally computed sender class. For chat: the mention text and the conversation transcripts (up to 2,500 characters per row), sender display names included. A message that looks like it holds a credential is not sent; ciphertext never leaves. Say this to the person before the first run — a DingTalk inbox carries customer names as a matter of course.

## When it fails

- `jev mail` fails open: every failure is a row with `needs_attention: true` and a `reason`, and a batch keeps its other rows.
- `dws` failures exit the fetch script non-zero and write nothing half-done. Fix the login and re-run — unread mail stays unread, so the fetch is idempotent.
- No Jev key yet? Mail rows return `needs_attention: true, reason: no_key`; triage rows default to `today` with a reason — a working answer either way.

## Roadmap

`chat message list-all` (a full time-window sweep, present on tenants with the message-search entitlement) is not wired in yet.
