#!/usr/bin/env python3
"""Repository-level checks for the information-rich routing artifact."""

from __future__ import annotations

import ast
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PATHS = [
    "LICENSE",
    "README.md",
    "CONTRIBUTING.md",
    "docs/ARTIFACT_EVALUATION.md",
    "docs/NS3_SETUP.md",
    "docs/RESULTS_AND_DATA.md",
    "ns3/NS3_VERSION",
    "ns3/contrib/information-routing/CMakeLists.txt",
    "ns3/contrib/information-routing/model/information-routing.cc",
    "ns3/contrib/information-routing/model/information-routing.h",
    "ns3/contrib/information-routing/examples/information-routing-wan-experiment.cc",
    "ns3/contrib/information-routing/utils/run_wan_sweep.py",
    "containerlab/srlinux-clos2x2/clos2x2_srlinux.clab.yaml",
    "containerlab/srlinux-clos2x2/exp3_nokia_srlinux.yaml",
    "tools/run_containerlab_recovery_cdf.py",
    "tools/run_containerlab_governor_stress.py",
    "tools/run_containerlab_app_recovery.py",
    "experiments/containerlab/app_recovery.yaml",
    "traces/fb_hadoop_synth_load1x.csv",
]

SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "cmake-build-debug",
    "cmake-build-release",
    "figs/generated",
    "results",
    "tables/generated",
    "tables/generated_v5",
}

TEXT_SUFFIXES = {
    ".cc",
    ".cfg",
    ".cff",
    ".csv",
    ".h",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".rst",
    ".sh",
    ".tex",
    ".tmpl",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

TEXT_FILENAMES = {
    ".editorconfig",
    ".gitignore",
    "Makefile",
}

FORBIDDEN_PATTERNS = [
    (re.compile(r"/home/[A-Za-z0-9_.-]+/"), "developer home directory"),
    (re.compile("Projects/" + "romam"), "old romam checkout path"),
    (re.compile("NSDI2027-" + "Toward"), "paper-worktree absolute path"),
    (re.compile("Projects/" + "ns-3-" + "dev-git"), "developer ns-3 checkout path"),
    (re.compile("Co-Authored" + "-By:"), "commit metadata in source files"),
    (re.compile("Clau" + "de"), "assistant metadata in source files"),
]

TRACE_HEADER = ["t_start_s", "src", "dst", "bytes", "tos"]
NS3_COMMIT = "80ffa6e66e9c59d7e80c324576daaf574ba3481b"


@dataclass
class CheckResult:
    name: str
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def should_skip(path: Path) -> bool:
    parts = path.relative_to(ROOT).parts
    if any(part.startswith("clab-") for part in parts):
        return True
    for item in SKIP_DIRS:
        skip_parts = tuple(item.split("/"))
        if parts[: len(skip_parts)] == skip_parts:
            return True
    return False


def iter_repo_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*"):
        if path.is_dir() or should_skip(path):
            continue
        out.append(path)
    return sorted(out)


def is_text_file(path: Path) -> bool:
    return path.name in TEXT_FILENAMES or path.suffix in TEXT_SUFFIXES


def check_required_paths() -> CheckResult:
    errors = []
    for item in REQUIRED_PATHS:
        if not (ROOT / item).exists():
            errors.append(f"missing required path: {item}")
    license_path = ROOT / "LICENSE"
    license_text = license_path.read_text(encoding="utf-8") if license_path.exists() else ""
    if (
        "GNU GENERAL PUBLIC LICENSE" not in license_text
        or "Version 2, June 1991" not in license_text
    ):
        errors.append("LICENSE is not GPL version 2 text")
    return CheckResult("required paths", errors)


def check_json_files(files: list[Path]) -> CheckResult:
    errors = []
    for path in files:
        if path.suffix != ".json":
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - report all parse failures.
            errors.append(f"{rel(path)}: {exc}")
    return CheckResult("json syntax", errors)


def check_python_syntax(files: list[Path]) -> CheckResult:
    errors = []
    for path in files:
        if path.suffix != ".py":
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            errors.append(f"{rel(path)}:{exc.lineno}: {exc.msg}")
    return CheckResult("python syntax", errors)


def check_forbidden_paths(files: list[Path]) -> CheckResult:
    errors = []
    for path in files:
        if not is_text_file(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern, label in FORBIDDEN_PATTERNS:
            if pattern.search(text):
                errors.append(f"{rel(path)}: contains {label}")
                break
    return CheckResult("portable paths", errors)


def check_containerlab_topology() -> CheckResult:
    errors = []
    topology = ROOT / "containerlab/srlinux-clos2x2/clos2x2_srlinux.clab.yaml"
    text = topology.read_text(encoding="utf-8")
    for match in re.finditer(r"startup-config:\s*([^\s]+)", text):
        cfg = topology.parent / match.group(1)
        if not cfg.exists():
            errors.append(f"{rel(topology)} references missing startup config: {match.group(1)}")
    return CheckResult("containerlab references", errors)


def check_trace_headers() -> CheckResult:
    errors = []
    for path in sorted((ROOT / "traces").glob("*.csv")):
        with path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
        if header != TRACE_HEADER:
            errors.append(f"{rel(path)}: expected header {TRACE_HEADER}, got {header}")
    return CheckResult("trace csv headers", errors)


def check_ns3_version_pin() -> CheckResult:
    errors = []
    version_path = ROOT / "ns3/NS3_VERSION"
    docs_path = ROOT / "docs/NS3_SETUP.md"
    version_text = version_path.read_text(encoding="utf-8") if version_path.exists() else ""
    docs_text = docs_path.read_text(encoding="utf-8") if docs_path.exists() else ""
    if "NS3_VERSION=3-dev" not in version_text:
        errors.append("ns3/NS3_VERSION does not record NS3_VERSION=3-dev")
    if f"NS3_COMMIT={NS3_COMMIT}" not in version_text:
        errors.append("ns3/NS3_VERSION does not record the validated ns-3 commit")
    if NS3_COMMIT not in docs_text:
        errors.append("docs/NS3_SETUP.md does not mention the validated ns-3 commit")
    return CheckResult("ns-3 version pin", errors)


def run_checks() -> list[CheckResult]:
    files = iter_repo_files()
    return [
        check_required_paths(),
        check_json_files(files),
        check_python_syntax(files),
        check_forbidden_paths(files),
        check_containerlab_topology(),
        check_trace_headers(),
        check_ns3_version_pin(),
    ]


def main() -> int:
    results = run_checks()
    failed = False
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        print(f"[{status}] {result.name}")
        for error in result.errors:
            print(f"  - {error}")
        failed = failed or not result.ok
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
