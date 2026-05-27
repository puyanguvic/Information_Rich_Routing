#!/usr/bin/env python3
"""Merge multiple WAN sweep directories into one analysis-ready view."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

from run_wan_sweep import write_group_summary, write_markdown_summary, write_summary_csv


SKIP_DIRS = {"analysis"}


def read_summary(path: Path) -> list[dict[str, str]]:
    summary = path / "summary.csv"
    if not summary.exists():
        print(f"[skip] no summary.csv in {path}", file=sys.stderr)
        return []
    with summary.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def link_run_dirs(input_dir: Path, output_dir: Path) -> list[str]:
    linked: list[str] = []
    for scenario_dir in sorted(input_dir.iterdir()):
        if not scenario_dir.is_dir():
            continue
        if scenario_dir.name in SKIP_DIRS or scenario_dir.name.endswith("-analysis"):
            continue
        for protocol_dir in sorted(scenario_dir.iterdir()):
            if not protocol_dir.is_dir():
                continue
            for seed_dir in sorted(protocol_dir.iterdir()):
                if not seed_dir.is_dir() or not seed_dir.name.startswith("seed-"):
                    continue
                target = output_dir / scenario_dir.name / protocol_dir.name / seed_dir.name
                if target.exists() or target.is_symlink():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(seed_dir.resolve(), target_is_directory=True)
                linked.append(f"{scenario_dir.name}/{protocol_dir.name}/{seed_dir.name}")
    return linked


def merge(inputs: list[Path], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    manifest: list[str] = []

    for input_dir in inputs:
        input_dir = input_dir.resolve()
        input_rows = read_summary(input_dir)
        added = 0
        for row in input_rows:
            key = (row.get("scenario", ""), row.get("protocol", ""), row.get("seed", ""))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
            added += 1
        linked = link_run_dirs(input_dir, output_dir)
        manifest.append(
            f"{input_dir}\n  rows_added={added}\n  run_dirs_linked={len(linked)}"
        )

    if not rows:
        raise SystemExit("no rows merged")

    write_summary_csv(output_dir / "summary.csv", rows)
    write_group_summary(output_dir / "summary_by_protocol.csv", rows)
    write_markdown_summary(output_dir / "summary.md", rows, output_dir)
    (output_dir / "merge_manifest.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    print(f"[done] merged {len(rows)} rows into {output_dir}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="merged output directory")
    parser.add_argument("inputs", nargs="+", type=Path, help="input sweep directories")
    args = parser.parse_args()
    merge(args.inputs, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
