#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jev-dingtalk: render a `jev mail` output JSON into a plain markdown report.

Mechanical on purpose: it sorts and formats rows, it decides nothing. Standard library only. MIT.

    python3 render_triage.py --in triage.json --md report.md [--top 20]
"""
import argparse
import json


def fmt_row(m):
    return (f"| {m.get('subject', '')} | {m.get('sender', '')} | {m.get('lane', '')} "
            f"| {m.get('urgency', '')} | {m.get('reason', '')} |")


def main():
    ap = argparse.ArgumentParser(description="render jev mail output as markdown")
    ap.add_argument("--in", dest="src", required=True, help="jev mail output JSON")
    ap.add_argument("--md", dest="md", help="write markdown here (default: stdout)")
    ap.add_argument("--top", type=int, default=0, help="cap the 'needs a person' list (0 = no cap)")
    args = ap.parse_args()

    with open(args.src, encoding="utf-8") as fh:
        doc = json.load(fh)
    summary = doc.get("summary") or {}
    rows = doc.get("messages") or []

    flags = [m for m in rows
             if m.get("injection") or m.get("sent_to_jev") is False or m.get("low_confidence")]
    attention = [m for m in rows
                 if (m.get("needs_attention") or m.get("lane") == "needs_reply") and m not in flags]
    attention.sort(key=lambda m: -(m.get("urgency") or 0))
    filed = [m for m in rows if m not in flags and m not in attention]
    if args.top:
        attention = attention[:args.top]

    lanes = summary.get("lanes") or {}
    header = [f"{summary.get('messages', len(rows))} messages"]
    for name, count in lanes.items():
        header.append(f"{name}: {count}")
    if summary.get("needs_attention") is not None:
        header.append(f"needs attention: {summary['needs_attention']}")
    cost = (summary.get("cost") or {}).get("usd")
    if cost is not None:
        header.append(f"cost: ${cost}")

    lines = ["# DingTalk mail triage", "", " · ".join(header), ""]

    def section(title, items):
        lines.append(f"## {title} ({len(items)})")
        lines.append("")
        if not items:
            lines.append("- none")
        else:
            lines.append("| subject | sender | lane | urgency | reason |")
            lines.append("|---|---|---|---|---|")
            for m in items:
                lines.append(fmt_row(m))
        lines.append("")

    section("Flags", flags)
    section("Needs a person", attention)
    lines.append(f"## Filed ({len(filed)})")
    lines.append("")
    for m in filed:
        lines.append(f"- [{m.get('lane', '')}] {m.get('subject', '')} — {m.get('sender', '')}")
    lines.append("")
    lines.append("_Rendered mechanically from `jev mail` output; the flags are Jev's._")
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
