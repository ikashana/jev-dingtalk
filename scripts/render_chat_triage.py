#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jev-dingtalk: render a `jev triage` output JSON for chat records as a plain markdown report.

Mechanical on purpose: it sorts and formats rows, it decides nothing. Standard library only. MIT.

    python3 render_chat_triage.py --in chat_triage.json [--inbox chat_inbox.json] [--md report.md] [--top 30]
"""
import argparse
import json


def clip(value, limit=48):
    s = str(value if value is not None else "")
    s = s.replace("|", "\\|").replace("\n", " ")
    return s[:limit] + ("..." if len(s) > limit else "")


def when(value):
    s = str(value or "")
    return s[5:16] if len(s) >= 16 else s


def source_of(row):
    return "at" if str(row.get("id") or "").startswith("at:") else "conv"


def table_row(row):
    return (f"| {source_of(row)} | {clip(row.get('subject'))} | {clip(row.get('sender'), 30)} "
            f"| {row.get('urgency', '')} | {clip(row.get('kind'), 12)} | {when(row.get('received'))} |")


def main():
    ap = argparse.ArgumentParser(description="render jev triage output for chat as markdown")
    ap.add_argument("--in", dest="src", required=True, help="jev triage output JSON")
    ap.add_argument("--inbox", dest="inbox", help="the converter's chat_inbox.json (for the unreadable list)")
    ap.add_argument("--md", dest="md", help="write markdown here (default: stdout)")
    ap.add_argument("--top", type=int, default=30, help="cap the queue list (default 30)")
    args = ap.parse_args()

    with open(args.src, encoding="utf-8") as fh:
        doc = json.load(fh)
    summary = doc.get("summary") or {}
    rows = doc.get("messages") or []

    unreadable = []
    if args.inbox:
        with open(args.inbox, encoding="utf-8") as fh:
            unreadable = (json.load(fh).get("unreadable")) or []

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
        lines.append("| src | conversation | from | u | kind | when |")
        lines.append("|---|---|---|---|---|---|")
        for m in items:
            lines.append(table_row(m))

    section("Now", now_rows, table)
    section("Today", today_rows, table)
    section("Queue", queue_rows, lambda items: (
        [lines.append(f"- [{source_of(m)}] {clip(m.get('subject'))} · {clip(m.get('sender'), 24)} "
                      f"· {clip(m.get('kind'), 12)} · u{m.get('urgency')} · {when(m.get('received'))}")
         for m in items[:args.top]]
        + ([lines.append(f"- ...and {len(items) - args.top} more")] if len(items) > args.top else [])))

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

    lines.append("_Rendered mechanically from `jev triage` output; routes are code, readings are Jev's._")
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
