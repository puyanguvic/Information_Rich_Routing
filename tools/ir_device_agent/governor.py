"""Legacy standalone governor model; live app recovery uses portable_runtime."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from tools.ir_device_agent.model import Admission, EvidenceRecord, Proposal


@dataclass
class GovernorConfig:
    min_confidence: float = 0.7
    dwell_events: int = 2
    action_budget: int = 1
    budget_window_s: float = 30.0
    suppress_candidate: str = "s1_branch"


@dataclass
class IRGovernor:
    config: GovernorConfig = field(default_factory=GovernorConfig)
    _recent_evidence: deque[str] = field(default_factory=deque)
    _action_times: deque[float] = field(default_factory=deque)
    _active_action: str = "ecmp"

    def propose(self, evidence: EvidenceRecord, *, proposal_id: str) -> Proposal:
        if evidence.kind == "app_jitter":
            return Proposal(
                proposal_id=proposal_id,
                action="suppress",
                candidate=self.config.suppress_candidate,
                evidence_id=evidence.evidence_id,
                confidence=evidence.confidence,
                timestamp_s=evidence.timestamp_s,
                reason="service-visible jitter above threshold",
            )
        if evidence.kind == "app_healthy" and self._active_action != "ecmp":
            return Proposal(
                proposal_id=proposal_id,
                action="fallback",
                candidate="stable_default",
                evidence_id=evidence.evidence_id,
                confidence=evidence.confidence,
                timestamp_s=evidence.timestamp_s,
                reason="healthy evidence after suppression",
            )
        return Proposal(
            proposal_id=proposal_id,
            action="shadow",
            candidate=self.config.suppress_candidate,
            evidence_id=evidence.evidence_id,
            confidence=evidence.confidence,
            timestamp_s=evidence.timestamp_s,
            reason="evidence below action threshold",
        )

    def admit(self, proposal: Proposal) -> Admission:
        now = proposal.timestamp_s
        while self._action_times and now - self._action_times[0] > self.config.budget_window_s:
            self._action_times.popleft()

        if proposal.action == "shadow":
            return self._reject(proposal, "shadow-only proposal")
        if proposal.confidence < self.config.min_confidence:
            return self._reject(proposal, "low-confidence evidence")

        self._recent_evidence.append(proposal.evidence_id)
        while len(self._recent_evidence) > self.config.dwell_events:
            self._recent_evidence.popleft()
        if proposal.action == "suppress" and len(self._recent_evidence) < self.config.dwell_events:
            return self._reject(proposal, "dwell not satisfied")

        if len(self._action_times) >= self.config.action_budget:
            return self._reject(proposal, "action budget exhausted")
        if proposal.action == self._active_action:
            return self._reject(proposal, "duplicate active action")

        self._action_times.append(now)
        self._active_action = proposal.action
        return Admission(
            proposal_id=proposal.proposal_id,
            admitted=True,
            reason="admitted",
            action=proposal.action,
            candidate=proposal.candidate,
            timestamp_s=now,
        )

    @staticmethod
    def _reject(proposal: Proposal, reason: str) -> Admission:
        return Admission(
            proposal_id=proposal.proposal_id,
            admitted=False,
            reason=reason,
            action=proposal.action,
            candidate=proposal.candidate,
            timestamp_s=proposal.timestamp_s,
        )
