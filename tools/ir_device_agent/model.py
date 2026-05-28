from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    scope: str
    kind: str
    value: float
    threshold: float
    confidence: float
    timestamp_s: float
    expires_s: float
    source: str

    @property
    def fresh_until_s(self) -> float:
        return self.timestamp_s + self.expires_s


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    action: str
    candidate: str
    evidence_id: str
    confidence: float
    timestamp_s: float
    reason: str


@dataclass(frozen=True)
class Admission:
    proposal_id: str
    admitted: bool
    reason: str
    action: str
    candidate: str
    timestamp_s: float


@dataclass(frozen=True)
class IOTaskResult:
    task_id: int
    start_s: float
    end_s: float
    duration_s: float
    ok: bool
    jitter: bool
    hang: bool
    throughput_mbps: float | None
    retransmits: int | None
    raw_file: str


@dataclass(frozen=True)
class RouteAudit:
    before_signature: str
    after_signature: str
    route_signature_changed: bool
    slow_route_edits: int
    next_hop_group_edits: int

