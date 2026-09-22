#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jev-dingtalk: fetch unread DingTalk mail via the dws CLI and convert it to the JSON `jev mail` reads.

Standard library only. MIT.

    python3 dws_unread_to_jev.py --email you@example.com --size 50 --out inbox.json

Writes {"messages": [{"id", "subject", "content", "sender", "received"}, ...]}.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime

MAX_BODY = 2500   # the same per-message budget `jev mail` applies
CHUNK = 20        # `dws mail message batch-get` accepts at most 20 ids per call


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
        detail = (proc.stderr or out or "no output").strip()[:400]
        sys.exit(f"error: {' '.join(cmd)} failed (rc={proc.returncode}): {detail}")
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        sys.exit(f"error: dws returned non-JSON for {' '.join(cmd)}: {out[:200]}")
    if isinstance(data, dict) and data.get("error"):
        err = data["error"]
        msg = err.get("message") if isinstance(err, dict) else str(err)
        sys.exit(f"error: dws refused {' '.join(args)}: {msg}")
    if isinstance(data, dict) and str(data.get("success")).lower() == "false":
        sys.exit(f"error: dws reported failure for {' '.join(args)}: {data.get('message') or 'unknown'}")
    return data


def clean_body(text):
    """markdownBody may carry literal \\n escape sequences; normalize them."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\\n", "\n").replace("\\t", "    ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def local_stamp(iso):
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(iso)


def main():
    ap = argparse.ArgumentParser(description="fetch unread DingTalk mail and convert it to jev mail input")
    ap.add_argument("--email", required=True, help="mailbox address (see: dws mail mailbox list -y)")
    ap.add_argument("--size", type=int, default=50, help="how many unread messages to pull (default 50)")
    ap.add_argument("--out", required=True, help="output JSON path")
    ap.add_argument("--keep-raw", metavar="DIR", help="also save the raw dws responses under DIR")
    args = ap.parse_args()

    dws = find_dws()

    listing = run_dws(dws, ["mail", "+unread-mail", "--email", args.email, "--size", str(args.size)])
    entries = listing.get("messages") or listing.get("items") or []
    print(f"unread messages: {len(entries)}")
    if args.keep_raw:
        os.makedirs(args.keep_raw, exist_ok=True)
        with open(os.path.join(args.keep_raw, "unread.json"), "w", encoding="utf-8") as fh:
            json.dump(listing, fh, ensure_ascii=False, indent=1)

    if not entries:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"messages": []}, fh, ensure_ascii=False, indent=1)
        print(f"nothing unread -> {args.out}")
        return

    ids = [e.get("messageId") for e in entries if e.get("messageId")]
    details = {}
    for start in range(0, len(ids), CHUNK):
        chunk = ids[start:start + CHUNK]
        batch = run_dws(dws, ["mail", "message", "batch-get", "--email", args.email,
                              "--ids", ",".join(chunk)])
        if args.keep_raw:
            with open(os.path.join(args.keep_raw, f"batch-{start // CHUNK + 1}.json"),
                      "w", encoding="utf-8") as fh:
                json.dump(batch, fh, ensure_ascii=False, indent=1)
        for item in batch.get("messages") or []:
            res = item.get("result") or {}
            if str(res.get("success")).lower() != "true":
                continue
            msg = res.get("message") or {}
            mid = msg.get("id") or item.get("id")
            if mid:
                details[mid] = msg

    out, missing = [], 0
    for entry in entries:
        mid = entry.get("messageId")
        msg = details.get(mid)
        if not msg:
            missing += 1
            out.append({
                "id": mid,
                "subject": entry.get("subject") or "",
                "content": "",
                "sender": entry.get("from") or "",
                "received": local_stamp(entry.get("date")),
            })
            continue
        frm = msg.get("from") or {}
        sender = f"{frm.get('name', '')} <{frm.get('email', '')}>".strip() \
            if isinstance(frm, dict) else str(frm)
        body = clean_body(msg.get("markdownBody") or "")
        content = body[:MAX_BODY] + ("\n[body truncated]" if len(body) > MAX_BODY else "")
        out.append({
            "id": mid,
            "subject": (msg.get("subject") or entry.get("subject") or "").strip(),
            "content": content,
            "sender": sender,
            "received": local_stamp(msg.get("receivedDateTime")),
        })

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"messages": out}, fh, ensure_ascii=False, indent=1)
    note = f" ({missing} without bodies)" if missing else ""
    print(f"wrote {len(out)} messages -> {args.out}{note}")


if __name__ == "__main__":
    main()
