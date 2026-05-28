from __future__ import annotations

import hashlib
import re

from tools.ir_device_agent.model import RouteAudit


ROUTE_LINE = re.compile(r"(?:10\.30\.[12]\.0/24|preference|metric)", re.IGNORECASE)
ACTIVE_VIEW_TOKEN = re.compile(r"next-hop-group\s+\S+", re.IGNORECASE)


def route_signature(snapshot: str) -> str:
    """Hash stable route-state lines while ignoring CLI headers and timestamps."""
    lines = []
    for line in snapshot.splitlines():
        stripped = " ".join(line.strip().split())
        if stripped and ROUTE_LINE.search(stripped):
            stripped = ACTIVE_VIEW_TOKEN.sub("next-hop-group <active-view>", stripped)
            lines.append(stripped)
    digest = hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()
    return digest[:16]


def compare_route_state(before: str, after: str, *, next_hop_group_edits: int) -> RouteAudit:
    before_sig = route_signature(before)
    after_sig = route_signature(after)
    changed = before_sig != after_sig
    return RouteAudit(
        before_signature=before_sig,
        after_signature=after_sig,
        route_signature_changed=changed,
        slow_route_edits=1 if changed else 0,
        next_hop_group_edits=next_hop_group_edits,
    )
