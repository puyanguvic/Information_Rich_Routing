#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.ir_device_agent.model import EvidenceRecord
from tools.ir_device_agent.portable_runtime import PortableIrDegGovernor


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def evidence(index: int, *, jitter: bool, timestamp_s: float) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=f"ev-{index:03d}",
        scope="branch:s1",
        kind="app_jitter" if jitter else "app_healthy",
        value=2.0 if jitter else 0.1,
        threshold=1.0,
        confidence=0.9,
        timestamp_s=timestamp_s,
        expires_s=5.0,
        source=f"task:{index}",
    )


def main() -> int:
    actions: list[tuple[int, str]] = []

    def apply(candidate_id: int, next_hop_group: str) -> bool:
        actions.append((candidate_id, next_hop_group))
        return True

    with PortableIrDegGovernor(apply) as governor:
        healthy = governor.observe(evidence(0, jitter=False, timestamp_s=0.1))
        check(healthy.candidate_id == 1, "healthy evidence should select stable ECMP")
        check(healthy.action_status == "suppressed_duplicate", "seed should suppress ECMP")

        first = governor.observe(evidence(1, jitter=True, timestamp_s=0.2))
        check(first.candidate_id == 2, "jitter should select suppression")
        check(
            first.action_status == "suppressed_qualification_or_dwell",
            "first jitter sample should wait for qualification",
        )
        second = governor.observe(evidence(2, jitter=True, timestamp_s=0.3))
        check(second.backend_applied, "second jitter sample should apply suppression")
        check(actions == [(2, "suppress_s1")], "binding should invoke one suppression action")

        duplicate = governor.observe(evidence(3, jitter=True, timestamp_s=0.4))
        check(duplicate.action_status == "suppressed_duplicate", "repeat should be duplicate")

        restore_first = governor.observe(evidence(4, jitter=False, timestamp_s=0.5))
        check(
            restore_first.action_status == "suppressed_qualification_or_dwell",
            "first healthy sample should qualify restoration",
        )
        restore_second = governor.observe(evidence(5, jitter=False, timestamp_s=0.6))
        check(
            restore_second.action_status == "suppressed_budget",
            "qualified restoration should respect the action budget",
        )
        check(len(actions) == 1, "suppressed actions must not reach Python actuation")

    print("PASS: Python binding uses portable SR Linux runtime")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
