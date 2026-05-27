#!/usr/bin/env python3
"""Inject a generated table fragment between START/END markers in §5.

Usage:
  python3 tools/inject_table_block.py \\
      --tex content/5_evaluation.tex \\
      --start "% TAB-2C-INJECT-START" \\
      --end   "% TAB-2C-INJECT-END" \\
      --fragment tables/generated/tab2c_trace.tex

Reads the fragment, replaces whatever is currently between the
two marker lines (inclusive of the line breaks) with the fragment
content, leaves marker lines in place.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tex", type=Path, required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--fragment", type=Path, required=True)
    args = ap.parse_args()

    text = args.tex.read_text()
    fragment = args.fragment.read_text().rstrip() + "\n"

    if args.start not in text or args.end not in text:
        raise SystemExit(f"markers not found in {args.tex}: "
                         f"{args.start!r} / {args.end!r}")

    pre, rest = text.split(args.start, 1)
    _, post = rest.split(args.end, 1)
    new = f"{pre}{args.start}\n{fragment}{args.end}{post}"
    args.tex.write_text(new)
    print(f"[inject] {args.tex} ← {args.fragment} "
          f"(between {args.start!r} / {args.end!r})")


if __name__ == "__main__":
    main()
