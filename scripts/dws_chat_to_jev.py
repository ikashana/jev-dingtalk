#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jev-dingtalk: fetch DingTalk chat records via the dws CLI (mentions + unread
conversations) and convert them to the JSON `jev triage` reads.

Standard library only. MIT.

    python3 dws_chat_to_jev.py --out chat_inbox.json [--days 7] [--max-convos 20] [--per-convo 20]

Writes {"messages": [...], "unreadable": [...], "marks": {...}, "meta": {...}}:
- messages: one row per @-mention, plus one row per readable unread conversation
  (its latest --per-convo messages as a transcript).
- unreadable: conversations whose content came back as ciphertext, or that could not be
  fetched - listed for a person, never guessed at.
- marks: LOCAL "have I dealt with this already?" flags - computed from a state file and
  the unread-conversation list, with no model call anywhere. Per row id:
    seen      - how many earlier reports already carried this row
    updated   - the conversation has new activity since the last report
    read      - the conversation has nothing unread left (you already opened it)
    self_last - your own message is the newest one in the conversation
  `jev triage` reads the "messages" key and ignores the rest.

The ledger: pass --state PATH to keep it between runs (default: chat_state.json next to
--out); --no-state turns the marks layer off. It is local scratch - keep it out of git.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

BODY_CHARS = 2500        # the same per-item budget `jev triage` applies
PER_MESSAGE_CHARS = 400  # per chat message inside a transcript
STATE_TTL_DAYS = 30      # ledger entries older than this are pruned


class DwsError(RuntimeError):
    pass


def find_dws():
    candidates = ["dws.cmd", "dws"] if os.name == "nt" else ["dws"]
    for name in candidates:
        if shutil.which(name):
            return name
    sys.exit("error: dws CLI not found on PATH - npm install -g dingtalk-workspace-cli")


def run_dws(binary, args):
    cmd = [binary] + args + ["-y", "-f", "json"]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", shell=(os.name == "nt"))
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        detail = (proc.stderr or out or "no output").strip()[:300]
        raise DwsError(f"{' '.join(cmd)} failed (rc={proc.returncode}): {detail}")
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        raise DwsError(f"dws returned non-JSON for {' '.join(cmd)}: {out[:200]}")
    if isinstance(data, dict):
        if data.get("error"):
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise DwsError(f"dws refused {' '.join(args)}: {msg}")
        if data.get("errorCode") not in (None, 0, "0"):
            raise DwsError(f"dws refused {' '.join(args)}: {data.get('errorMsg') or data.get('errorCode')}")
        if str(data.get("success")).lower() == "false":
            raise DwsError(f"dws reported failure for {' '.join(args)}: {data.get('message') or 'unknown'}")
    return data


def clean_text(text):
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\\n", "\n").replace("\\t", "    ")
    # Media IDs are long base64 runs with no reading value - shorten them so they do not
    # crowd out the message around them (or the truncation window).
    text = re.sub(r"(mediaId=[$@]?)([A-Za-z0-9+/=_-]{24,})",
                  lambda m: m.group(1) + m.group(2)[:12] + "...", text)
    return text.strip()


def one_line(text):
    text = re.sub(r"\s+", " ", clean_text(text)).strip()
    return text[:PER_MESSAGE_CHARS] + ("..." if len(text) > PER_MESSAGE_CHARS else "")


def looks_encrypted(text):
    """Base64-ish blobs a chat API cannot decrypt.

    Blobs carry no CJK and no sentence punctuation, and their content is one or more
    whitespace-free runs of 40+ characters drawn from the base64 alphabet. Human text
    of any language fails at least one of those checks: words are short, URLs and code
    carry punctuation, and the "||n||n||n" metadata suffix is not a 40-char run.
    """
    t = (text or "").strip()
    if len(t) < 60:
        return False
    if re.search(r"[\u4e00-\u9fff]", t):
        return False
    if "." in t or ":" in t:
        return False
    core = re.sub(r"[\s|]", "", t)
    if len(core) < 50:
        return False
    ratio = len(re.findall(r"[A-Za-z0-9+/=]", core)) / len(core)
    if ratio < 0.9:
        return False
    runs = [r for r in re.split(r"[\s|]+", t) if re.fullmatch(r"[A-Za-z0-9+/=]+", r)]
    return max((len(r) for r in runs), default=0) >= 40


def is_self(sender, self_name):
    """Lenient match: some feeds decorate the name as 'Name(...)'."""
    s = str(sender or "").strip()
    if not self_name or not s:
        return False
    return s == self_name or f"({self_name})" in s or s.startswith(self_name + "(")


def fingerprint(kind, *parts):
    key = "|".join(str(p or "") for p in parts)
    return f"{kind}:" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def load_state(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    items = data.get("items")
    return items if isinstance(items, dict) else {}


def parse_time(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def save_state(path, items, now_dt):
    cutoff = now_dt - timedelta(days=STATE_TTL_DAYS)
    kept = {}
    for key, rec in items.items():
        seen_at = parse_time(rec.get("last_seen"))
        if seen_at is None or seen_at >= cutoff:
            kept[key] = rec
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"updated": now_dt.strftime("%Y-%m-%d %H:%M:%S"), "items": kept},
                  fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return len(kept)


def touch(rec, now, reports):
    rec["first_seen"] = rec.get("first_seen") or now
    rec["last_seen"] = now
    rec["reports"] = reports
    return rec


def main():
    ap = argparse.ArgumentParser(description="fetch DingTalk chat records and convert them to jev triage input")
    ap.add_argument("--out", required=True, help="output JSON path")
    ap.add_argument("--days", type=int, default=7, help="how many days of @-mentions to pull (default 7)")
    ap.add_argument("--max-mentions", type=int, default=100, help="cap on mention rows (default 100)")
    ap.add_argument("--max-convos", type=int, default=20, help="cap on unread conversations fetched (default 20)")
    ap.add_argument("--per-convo", type=int, default=20, help="messages per conversation transcript (default 20)")
    ap.add_argument("--keep-raw", metavar="DIR", help="also save the raw dws responses under DIR")
    ap.add_argument("--state", metavar="PATH",
                    help="ledger file for the marks layer (default: chat_state.json next to --out)")
    ap.add_argument("--no-state", action="store_true", help="turn the marks layer off entirely")
    ap.add_argument("--self", dest="self_name", metavar="NAME",
                    help="your display name for the self_last mark (default: read from `dws auth status`)")
    args = ap.parse_args()

    dws = find_dws()
    now_dt = datetime.now()
    now = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    keep = None
    if args.keep_raw:
        os.makedirs(args.keep_raw, exist_ok=True)
        keep = args.keep_raw

    ledger = not args.no_state
    state_path, state, marks, self_name = None, {}, {}, ""
    if ledger:
        state_path = args.state or os.path.join(
            os.path.dirname(os.path.abspath(args.out)), "chat_state.json")
        state = load_state(state_path)
        self_name = (args.self_name or "").strip()
        if not self_name:
            try:
                status = run_dws(dws, ["auth", "status"])
                self_name = str(status.get("user_name") or "").strip()
            except DwsError:
                self_name = ""
    touched = set()

    # --- 1) listings ----------------------------------------------------------
    try:
        mentions_listing = run_dws(dws, ["chat", "+at-me", "--days", str(args.days)])
    except DwsError as error:
        sys.exit(f"error: {error}")
    if keep:
        with open(os.path.join(keep, "at-me.json"), "w", encoding="utf-8") as fh:
            json.dump(mentions_listing, fh, ensure_ascii=False, indent=1)

    # The unread list doubles as the read-state source: a conversation that is NOT in it
    # has nothing unread left, so any @-mention inside it is already read. Ask for a high
    # count (100) so the map stays faithful even for a heavy inbox.
    try:
        unread_listing = run_dws(dws, ["chat", "+messages-list-unread-conversations",
                                       "--count", "100"])
    except DwsError as error:
        sys.exit(f"error: {error}")
    if keep:
        with open(os.path.join(keep, "unread-conversations.json"), "w", encoding="utf-8") as fh:
            json.dump(unread_listing, fh, ensure_ascii=False, indent=1)
    convs = unread_listing.get("conversations") or []
    unread_titles = {str(c.get("title") or "").strip() for c in convs}

    # --- 2) @-mentions --------------------------------------------------------
    mention_items, encrypted_mentions = [], 0
    for i, m in enumerate((mentions_listing.get("messages") or [])[:args.max_mentions]):
        text = clean_text(m.get("text"))
        if not text:
            continue
        if looks_encrypted(text):
            encrypted_mentions += 1
            continue
        item = {
            "id": f"at:{i}",
            "subject": str(m.get("conversation") or "")[:120],
            "content": text[:BODY_CHARS],
            "sender": str(m.get("sender") or "")[:120],
            "received": str(m.get("time") or ""),
        }
        if ledger:
            fp = fingerprint("m", m.get("conversation"), m.get("sender"), m.get("time"),
                             str(m.get("text") or "")[:300])
            rec = state.get(fp) or {}
            prior = int(rec.get("reports") or 0)
            mark = {}
            if prior:
                mark["seen"] = prior
            title = str(m.get("conversation") or "").strip()
            if title and title not in unread_titles:
                mark["read"] = True
            if mark:
                marks[item["id"]] = mark
            if fp not in touched:
                touched.add(fp)
                state[fp] = touch(rec, now, prior + 1)
        mention_items.append(item)
    print(f"mentions: {len(mention_items)} usable"
          + (f" ({encrypted_mentions} encrypted, skipped)" if encrypted_mentions else ""))

    # --- 3) unread conversations ---------------------------------------------
    conv_items, unreadable = [], []
    fetch_convs = convs[:args.max_convos] if args.max_convos > 0 else []
    for i, conv in enumerate(fetch_convs):
        cid = conv.get("conversationId") or ""
        title = str(conv.get("title") or "")
        try:
            batch = run_dws(dws, ["chat", "message", "list", "--group", cid,
                                  "--time", now, "--direction", "older",
                                  "--limit", str(args.per_convo * 2)])
        except DwsError as error:
            unreadable.append({"conversation": title, "reason": f"fetch failed: {error}"[:200]})
            continue
        if keep:
            with open(os.path.join(keep, f"conv-{i + 1}.json"), "w", encoding="utf-8") as fh:
                json.dump(batch, fh, ensure_ascii=False, indent=1)
        messages = ((batch.get("result") or {}).get("messages")) or []
        readable, skipped = [], 0
        for m in messages:
            text = clean_text(m.get("content") or "")
            if not text:
                continue
            if looks_encrypted(text):
                skipped += 1
                continue
            readable.append({"sender": str(m.get("sender") or ""),
                             "text": one_line(text), "time": str(m.get("createTime") or "")})
        readable.sort(key=lambda m: m["time"])
        readable = readable[-args.per_convo:]
        if not readable:
            unreadable.append({
                "conversation": title,
                "reason": "content is encrypted (ciphertext); the API cannot read it"
                if messages else "no readable messages",
            })
            continue
        transcript = "\n".join(f"{m['sender']}: {m['text']}" for m in readable)
        if len(transcript) > BODY_CHARS:
            transcript = "[earlier messages trimmed]\n" + transcript[-BODY_CHARS:]
        if skipped:
            transcript += f"\n[{skipped} message(s) in this conversation could not be read]"
        item_id = f"conv:{i}"
        conv_items.append({
            "id": item_id,
            "subject": title[:120],
            "content": transcript,
            "sender": readable[-1]["sender"][:120],
            "received": readable[-1]["time"],
        })
        if ledger:
            fp = fingerprint("c", cid)
            rec = state.get(fp) or {}
            prior = int(rec.get("reports") or 0)
            activity = max((str(mm.get("createTime") or "") for mm in messages), default="")
            previous = str(rec.get("watermark") or "")
            updated = bool(previous and activity and activity > previous)
            newest = max(messages, key=lambda mm: str(mm.get("createTime") or "")) if messages else None
            self_last = bool(newest and is_self(newest.get("sender"), self_name))
            mark = {}
            if updated:
                mark["updated"] = True
            elif prior:
                mark["seen"] = prior
            if self_last:
                mark["self_last"] = True
            if mark:
                marks[item_id] = mark
            if activity:
                rec["watermark"] = max(activity, previous)
            if fp not in touched:
                touched.add(fp)
                state[fp] = touch(rec, now, prior + 1)
    print(f"conversations: {len(conv_items)} readable, {len(unreadable)} unreadable")

    if ledger:
        n_seen = sum(1 for v in marks.values() if v.get("seen"))
        n_read = sum(1 for v in marks.values() if v.get("read"))
        n_upd = sum(1 for v in marks.values() if v.get("updated"))
        n_self = sum(1 for v in marks.values() if v.get("self_last"))
        print(f"marks: {n_seen} repeat, {n_read} read, {n_upd} updated, {n_self} yours-newest")

    # --- 4) write -------------------------------------------------------------
    doc = {
        "messages": mention_items + conv_items,
        "unreadable": unreadable,
        "marks": marks,
        "meta": {
            "generated": now,
            "days": args.days,
            "mentions": len(mention_items),
            "conversations": len(conv_items),
            "unreadable": len(unreadable),
            "marked": len(marks),
        },
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print(f"wrote {len(doc['messages'])} items -> {args.out}")
    if ledger and state_path:
        try:
            kept = save_state(state_path, state, now_dt)
            print(f"state: {kept} tracked items -> {state_path}")
        except OSError as error:
            print(f"warning: could not save state to {state_path}: {error}")


if __name__ == "__main__":
    main()
