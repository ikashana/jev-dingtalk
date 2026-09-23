#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jev-dingtalk: render a `jev triage` output JSON for chat records as a plain markdown report.

Mechanical on purpose: it sorts and formats rows, it decides nothing. Standard library only. MIT.

    python3 render_chat_triage.py --in chat_triage.json [--inbox chat_inbox.json] [--md report.md] [--top 30]

With `--inbox` (the converter's output) every row also quotes the message it triaged - taken
locally from the inbox file, no model call, nothing extra sent anywhere.
"""
import argparse
import json

QUOTE_TABLE = 64  # characters of the quoted message in the Now / Today tables
QUOTE_LIST = 44   # characters in the Queue list


def clip(value, limit=48):
    s = str(value if value is not None else "")
    s = s.replace("|", "\\|").replace("\n", " ")
    return s[:limit] + ("..." if len(s) > limit else "")


def when(value):
    s = str(value or "")
    return s[5:16] if len(s) >= 16 else s


def source_of(row):
    return "at" if str(row.get("id") or "").startswith("at:") else "conv"


def quote_of(row, content_by_id):
    """The line worth searching back for: a mention quotes itself, a conversation its
    newest readable message. "" when the inbox cannot supply it."""
    content = content_by_id.get(str(row.get("id") or ""))
    if not content:
        return ""
    lines = [ln.strip() for ln in str(content).split("\n")
             if ln.strip()
             and not ln.startswith("[earlier messages trimmed]")
             and "message(s) in this conversation could not be read]" not in ln]
    if not lines:
        return ""
    line = lines[0] if source_of(row) == "at" else lines[-1]
    line = " ".join(line.split())
    sender = str(row.get("sender") or "").strip()
    if sender and line.startswith(sender + ": "):
        line = line[len(sender) + 2:]
    return line


def table_row(row, content_by_id=None):
    line = (f"| {source_of(row)} | {clip(row.get('subject'))} | {clip(row.get('sender'), 30)} "
            f"| {row.get('urgency', '')} | {clip(row.get('kind'), 12)} | {when(row.get('received'))} ")
    if content_by_id is not None:
        line += f"| {clip(quote_of(row, content_by_id), QUOTE_TABLE)} "
    return line + "|"


def main():
    ap = argparse.ArgumentParser(description="render jev triage output for chat as markdown")
    ap.add_argument("--in", dest="src", required=True, help="jev triage output JSON")
    ap.add_argument("--inbox", dest="inbox",
                    help="the converter's chat_inbox.json - supplies the quote column and the unreadable list")
    ap.add_argument("--md", dest="md", help="write markdown here (default: stdout)")
    ap.add_argument("--top", type=int, default=30, help="cap the queue list (default 30)")
    args = ap.parse_args()

    with open(args.src, encoding="utf-8") as fh:
        doc = json.load(fh)
    summary = doc.get("summary") or {}
    rows = doc.get("messages") or []

    unreadable, content_by_id = [], None
    if args.inbox:
        with open(args.inbox, encoding="utf-8") as fh:
            inbox = json.load(fh)
        unreadable = inbox.get("unreadable") or []
        content_by_id = {str(m.get("id")): m.get("content") for m in (inbox.get("messages") or [])}

    now_rows = sorted([m for m in rows if m.get("route") == "now"],
                      key=lambda m: -(m.get("urgency") or 0))
    today_rows = sorted([m for m in rows if m.get("route") == "today"],
                        key=lambda m: -(m.get("urgency") or 0))
    queue_rows = sorted([m for m in rows if m.get("route") == "queue"],
                        key=lambda m: -(m.get("urgency") or 0))
    ignore_rows = [m for m in rows if m.get("route") == "ignore"]

    routes = summary.get("routes") or {}
    header = [f"{summary.get('messages', len(rows))} items"]
    for name in ("now", "today", "queue", "ignore"):
        if name in routes:
            header.append(f"{name}: {routes[name]}")
    latency = (summary.get("latency_ms") or {}).get("p50")
    if latency:
        header.append(f"p50 {latency}ms")
    cost = summary.get("cost_estimate_usd")
    if cost is not None:
        header.append(f"cost ${cost}")

    lines = ["# DingTalk chat triage", "", " · ".join(header), ""]

    def section(title, items, body):
        lines.append(f"## {title} ({len(items)})")
        lines.append("")
        body(items)
        lines.append("")

    def table(items):
        if not items:
            lines.append("- none")
            return
        if content_by_id is not None:
            lines.append("| src | conversation | from | u | kind | when | quote |")
            lines.append("|---|---|---|---|---|---|---|")
        else:
            lines.append("| src | conversation | from | u | kind | when |")
            lines.append("|---|---|---|---|---|---|")
        for m in items:
            lines.append(table_row(m, content_by_id))

    def queue(items):
        for m in items[:args.top]:
            line = (f"- [{source_of(m)}] {clip(m.get('subject'))} · {clip(m.get('sender'), 24)} "
                    f"· {clip(m.get('kind'), 12)} · u{m.get('urgency')} · {when(m.get('received'))}")
            if content_by_id is not None:
                line += f" · {clip(quote_of(m, content_by_id), QUOTE_LIST)}"
            lines.append(line)
        if len(items) > args.top:
            lines.append(f"- ...and {len(items) - args.top} more")

    section("Now", now_rows, table)
    section("Today", today_rows, table)
    section("Queue", queue_rows, queue)

    lines.append(f"## Ignore ({len(ignore_rows)})")
    lines.append("")
    lines.append("- counted only, nothing to read" if ignore_rows else "- none")
    lines.append("")

    if unreadable:
        lines.append(f"## Could not read - check manually ({len(unreadable)})")
        lines.append("")
        for u in unreadable:
            lines.append(f"- {clip(u.get('conversation'))} — {clip(u.get('reason'), 90)}")
        lines.append("")

    review = summary.get("needs_review") or []
    if review:
        lines.append(f"## Low confidence ({len(review)})")
        lines.append("")
        for r in review:
            lines.append(f"- {clip(r.get('subject'))} ({r.get('route', '')}, confidence {r.get('confidence', '')})")
        lines.append("")

    lines.append("_Quotes are copied locally from the inbox file - a conversation's newest "
                 "readable line, the mention itself for @-mentions - search them back in DingTalk. "
                 "Rendered mechanically from `jev triage` output; routes are code, readings are Jev's._")
    lines.append("")

    text = "\n".join(lines)
    if args.md:
        with open(args.md, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"report -> {args.md}")
    else:
        print(text)


if __name__ == "__main__":
    main()
