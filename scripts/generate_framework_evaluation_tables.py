#!/usr/bin/env python3
"""Generate paper tables from the canonical program/conformance trace."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRACE = (
    ROOT / "ns3" / "contrib" / "information-routing" / "core" / "test" / "conformance-trace.csv"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "paper" / "generated")
    parser.add_argument("--check-only", action="store_true")
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(f"[FAIL] framework evaluation tables: {message}")


def group_epochs(rows: list[dict[str, str]]) -> dict[int, list[dict[str, str]]]:
    grouped: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["epoch"])].append(row)
    if not grouped:
        fail("empty conformance trace")
    for epoch, candidates in grouped.items():
        for field in (
            "program",
            "traffic_class",
            "expected_status",
            "expected_candidate",
            "expected_policy",
            "expected_action_status",
            "expected_attempted",
            "expected_applied",
            "expected_backend_detail",
        ):
            values = {row[field] for row in candidates}
            if len(values) != 1:
                fail(f"epoch {epoch} disagrees across candidate rows for {field}: {values}")
    return dict(sorted(grouped.items()))


def field(epoch_rows: list[dict[str, str]], name: str) -> str:
    return epoch_rows[0][name]


def selected_row(epoch_rows: list[dict[str, str]]) -> dict[str, str]:
    candidate = field(epoch_rows, "expected_candidate")
    matches = [row for row in epoch_rows if row["candidate_id"] == candidate]
    if len(matches) != 1:
        fail(f"expected candidate {candidate!r} does not identify one trace row")
    return matches[0]


def epoch_list(values: list[int]) -> str:
    values = sorted(set(values))
    ranges: list[str] = []
    start = previous = values[0]
    for value in values[1:]:
        if value == previous + 1:
            previous = value
            continue
        ranges.append(str(start) if start == previous else f"{start}--{previous}")
        start = previous = value
    ranges.append(str(start) if start == previous else f"{start}--{previous}")
    return ", ".join(ranges)


def matching_epochs(
    epochs: dict[int, list[dict[str, str]]],
    predicate,
    case_name: str,
) -> list[int]:
    matches = [epoch for epoch, rows in epochs.items() if predicate(rows)]
    if not matches:
        fail(f"canonical trace no longer covers {case_name}")
    return matches


def recovery_after(
    epochs: dict[int, list[dict[str, str]]],
    failed_epochs: list[int],
    case_name: str,
) -> int:
    failed_epoch = max(failed_epochs)
    failed = epochs[failed_epoch]
    identity = tuple(field(failed, name) for name in ("scope", "generation", "program"))
    for epoch, rows in epochs.items():
        if epoch <= failed_epoch:
            continue
        candidate_identity = tuple(field(rows, name) for name in ("scope", "generation", "program"))
        if (
            candidate_identity == identity
            and field(rows, "expected_action_status") == "admitted"
            and field(rows, "expected_applied") == "1"
        ):
            return epoch
    fail(f"canonical trace has no successful same-generation retry after {case_name}")


def validate_program_distinctions(epochs: dict[int, list[dict[str, str]]]) -> dict[str, list[int]]:
    by_program: dict[str, list[int]] = defaultdict(list)
    for epoch, rows in epochs.items():
        by_program[field(rows, "program")].append(epoch)
    expected = {"ir-deg", "ir-load", "ir-class"}
    if set(by_program) != expected:
        fail(f"expected named programs {sorted(expected)}, got {sorted(by_program)}")

    load_epochs = by_program["ir-load"]
    load_rows = epochs[load_epochs[0]]
    load_selected = selected_row(load_rows)
    eligible = [row for row in load_rows if row["eligible"] == "1"]
    if float(load_selected["load"]) != min(float(row["load"]) for row in eligible):
        fail("IR-Load trace does not select the minimum-load candidate")
    if float(load_selected["stable_cost"]) <= min(float(row["stable_cost"]) for row in eligible):
        fail("IR-Load trace does not distinguish load selection from stable cost")

    class_epochs = by_program["ir-class"]
    bulk = next((epochs[e] for e in class_epochs if field(epochs[e], "traffic_class") == "0"), None)
    priority = next(
        (epochs[e] for e in class_epochs if field(epochs[e], "traffic_class") == "184"), None
    )
    if bulk is None or priority is None:
        fail("IR-Class trace must contain bulk and priority traffic classes")
    if field(bulk, "expected_candidate") == field(priority, "expected_candidate"):
        fail("IR-Class trace does not distinguish bulk and priority decisions")
    snapshot_fields = ("candidate_id", "stable_cost", "eligible", "delay", "queue", "load")
    bulk_snapshot = [tuple(row[name] for name in snapshot_fields) for row in bulk]
    priority_snapshot = [tuple(row[name] for name in snapshot_fields) for row in priority]
    if bulk_snapshot != priority_snapshot:
        fail("IR-Class bulk/priority decisions do not hold the candidate/evidence snapshot fixed")

    return dict(by_program)


def render_table(
    epochs: dict[int, list[dict[str, str]]],
    by_program: dict[str, list[int]],
) -> str:
    normal = matching_epochs(
        epochs,
        lambda rows: field(rows, "expected_status") == "selected"
        and field(rows, "expected_action_status") == "admitted"
        and field(rows, "expected_applied") == "1",
        "valid selection/application",
    )
    dwell = matching_epochs(
        epochs,
        lambda rows: field(rows, "expected_action_status") == "suppressed-dwell",
        "dwell suppression",
    )
    duplicate = matching_epochs(
        epochs,
        lambda rows: field(rows, "expected_action_status") == "suppressed-duplicate",
        "duplicate suppression",
    )
    fallback = matching_epochs(
        epochs,
        lambda rows: field(rows, "expected_status") == "fallback"
        and field(rows, "expected_policy") == "static-cost",
        "unusable-evidence fallback",
    )
    empty = matching_epochs(
        epochs,
        lambda rows: field(rows, "expected_status") == "no-candidate"
        and field(rows, "expected_action_status") == "no-action",
        "empty eligible candidate set",
    )
    stale = matching_epochs(
        epochs,
        lambda rows: field(rows, "expected_backend_detail") == "stale candidate generation"
        and field(rows, "expected_applied") == "0",
        "stale backend generation",
    )
    rejected = matching_epochs(
        epochs,
        lambda rows: field(rows, "expected_backend_detail") == "backend rejected action"
        and field(rows, "expected_applied") == "0",
        "backend rejection",
    )
    stale_recovery = recovery_after(epochs, stale, "stale generation")
    rejection_recovery = recovery_after(epochs, rejected, "backend rejection")
    class_isolation = by_program["ir-class"]

    program_rows = [
        (
            "IR-Deg",
            "Weights, evidence qualification, dwell/rate limit",
            f"{len(by_program['ir-deg'])} epochs: selection and lifecycle failures",
            "Full study",
        ),
        (
            "IR-Load",
            "Load-only objective; duplicate admission",
            f"{len(by_program['ir-load'])} epoch: lower load beats stable cost",
            "F4 ($N{=}20$)",
        ),
        (
            "IR-Class",
            "Traffic-class weights; duplicate admission",
            f"{len(by_program['ir-class'])} epochs: one snapshot, class-specific choices",
            "F4 ($N{=}20$)",
        ),
    ]
    correctness_rows = [
        ("Valid output", "Admit and apply the selected in-set candidate", normal),
        (
            "Dwell / duplicate",
            "Suppress before the backend; retain the active view",
            dwell + duplicate,
        ),
        ("Unusable evidence", "Fall back to minimum stable cost and record the reason", fallback),
        ("No eligible candidate", "Return no-candidate and emit no action", empty),
        (
            "Stale generation",
            "Attempt is rejected; current-generation retry applies",
            stale + [stale_recovery],
        ),
        (
            "Backend rejection",
            "Do not record application; a later retry remains admissible",
            rejected + [rejection_recovery],
        ),
        (
            "Traffic-class isolation",
            "Same snapshot may select class-specific candidates",
            class_isolation,
        ),
    ]

    lines = [
        "% Generated by scripts/generate_framework_evaluation_tables.py; do not edit.",
        "\\begin{table*}[!t]",
        "\\centering",
        "\\caption[Program composition and action-lifecycle correctness]{Program composition and shared-runtime correctness. The standalone core, production ns-3 adapter, and thin SR Linux adapter emit byte-identical canonical rows for all 14 epochs; the function-native F4 study separately measures IR-Load and IR-Class service.}",
        "\\label{tab:framework-composition-correctness}",
        "\\scriptsize",
        "\\setlength{\\tabcolsep}{3pt}",
        "\\renewcommand{\\arraystretch}{1.02}",
        "\\begin{minipage}[t]{0.57\\textwidth}",
        "\\centering",
        "\\textbf{(a) Named program composition.}\\vspace{0.3ex}",
        "\\begin{tabularx}{\\linewidth}{@{}l L{0.27\\linewidth} X l@{}}",
        "\\toprule",
        "Program & Function-specific replacement & Canonical distinction & Service \\\\",
        "\\midrule",
    ]
    for row in program_rows:
        lines.append(" & ".join(row) + r" \\")
    lines.extend(
        [
            "\\bottomrule",
            "\\end{tabularx}",
            "\\end{minipage}%",
            "\\hfill",
            "\\begin{minipage}[t]{0.40\\textwidth}",
            "\\centering",
            "\\textbf{(b) Canonical safety cases.}\\vspace{0.3ex}",
            "\\begin{tabularx}{\\linewidth}{@{}X r@{}}",
            "\\toprule",
            "Case (core / ns-3 / SRL: \\cmark~/~\\cmark~/~\\cmark) & Epoch(s) \\\\",
            "\\midrule",
        ]
    )
    for case, _outcome, case_epochs in correctness_rows:
        lines.append(f"{case} & {epoch_list(case_epochs)} \\\\")
    lines.extend(
        [
            "\\bottomrule",
            "\\end{tabularx}",
            "\\end{minipage}",
            "\\end{table*}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    with args.trace.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    epochs = group_epochs(rows)
    if len(epochs) != 14:
        fail(f"expected 14 canonical epochs, got {len(epochs)}")
    by_program = validate_program_distinctions(epochs)
    counts = ", ".join(f"{name}={len(values)}" for name, values in sorted(by_program.items()))
    if args.check_only:
        print(f"[PASS] framework table inputs: 14 epochs ({counts})")
        return
    output = args.output_dir / "framework_composition_correctness.tex"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_table(epochs, by_program), encoding="utf-8")
    print(f"[PASS] framework tables: 14 epochs ({counts}) -> {output}")


if __name__ == "__main__":
    main()
