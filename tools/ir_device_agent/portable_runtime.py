from __future__ import annotations

import ctypes
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from tools.ir_device_agent.model import EvidenceRecord


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LIBRARY = ROOT / "build/srlinux-adapter/libir-srlinux-c-api.so"
ERROR_SIZE = 256

DECISION_STATUS = {
    0: "unknown",
    1: "selected",
    2: "fallback",
    3: "no_candidate",
}
ACTION_STATUS = {
    0: "no_action",
    1: "admitted",
    2: "suppressed_duplicate",
    3: "suppressed_qualification_or_dwell",
    4: "suppressed_budget",
}


class _Candidate(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_uint64),
        ("stable_cost", ctypes.c_double),
        ("eligible", ctypes.c_int),
        ("next_hop_group", ctypes.c_char_p),
    ]


class _Evidence(ctypes.Structure):
    _fields_ = [
        ("candidate_id", ctypes.c_uint64),
        ("kind", ctypes.c_char_p),
        ("value", ctypes.c_double),
        ("confidence", ctypes.c_double),
        ("timestamp_seconds", ctypes.c_double),
        ("expires_after_seconds", ctypes.c_double),
        ("source", ctypes.c_char_p),
    ]


class _UpdateConfig(ctypes.Structure):
    _fields_ = [
        ("suppress_duplicates", ctypes.c_int),
        ("dwell_seconds", ctypes.c_double),
        ("token_rate_per_second", ctypes.c_double),
        ("token_burst", ctypes.c_double),
        ("min_consecutive_selections", ctypes.c_uint32),
    ]


class _Result(ctypes.Structure):
    _fields_ = [
        ("decision_status", ctypes.c_int),
        ("has_selection", ctypes.c_int),
        ("candidate_id", ctypes.c_uint64),
        ("score", ctypes.c_double),
        ("action_status", ctypes.c_int),
        ("action_generation", ctypes.c_uint64),
        ("backend_attempted", ctypes.c_int),
        ("backend_applied", ctypes.c_int),
        ("policy", ctypes.c_char * 64),
        ("decision_reason", ctypes.c_char * 256),
        ("action_reason", ctypes.c_char * 256),
        ("backend_detail", ctypes.c_char * 256),
        ("next_hop_group", ctypes.c_char * 64),
    ]


_ApplyCallback = ctypes.CFUNCTYPE(
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_uint32,
    ctypes.c_uint64,
    ctypes.c_char_p,
)


def _decode(value: bytes | None) -> str:
    return value.decode("utf-8", errors="replace") if value else ""


def _load_library(path: str | Path | None) -> ctypes.CDLL:
    selected = Path(path or os.environ.get("IR_SRLINUX_ADAPTER_LIBRARY", DEFAULT_LIBRARY))
    if not selected.is_file():
        raise FileNotFoundError(
            f"portable SR Linux runtime library not found at {selected}; "
            "run `make srlinux-adapter` or pass --ir-adapter-library"
        )
    library = ctypes.CDLL(str(selected))
    library.ir_srlinux_adapter_create.argtypes = [
        ctypes.c_char_p,
        ctypes.POINTER(_UpdateConfig),
        _ApplyCallback,
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_size_t,
    ]
    library.ir_srlinux_adapter_create.restype = ctypes.c_void_p
    library.ir_srlinux_adapter_destroy.argtypes = [ctypes.c_void_p]
    library.ir_srlinux_adapter_destroy.restype = None
    library.ir_srlinux_adapter_seed_active.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_uint64,
        ctypes.POINTER(_Candidate),
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_uint64,
        ctypes.c_double,
        ctypes.c_char_p,
        ctypes.c_size_t,
    ]
    library.ir_srlinux_adapter_seed_active.restype = ctypes.c_int
    library.ir_srlinux_adapter_execute.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.c_double,
        ctypes.c_char_p,
        ctypes.c_uint64,
        ctypes.POINTER(_Candidate),
        ctypes.c_size_t,
        ctypes.c_char_p,
        ctypes.c_uint64,
        ctypes.POINTER(_Candidate),
        ctypes.c_size_t,
        ctypes.POINTER(_Evidence),
        ctypes.c_size_t,
        ctypes.c_int,
        ctypes.POINTER(_Result),
        ctypes.c_char_p,
        ctypes.c_size_t,
    ]
    library.ir_srlinux_adapter_execute.restype = ctypes.c_int
    library.ir_srlinux_adapter_reset.argtypes = [ctypes.c_void_p]
    library.ir_srlinux_adapter_reset.restype = None
    return library


@dataclass(frozen=True)
class PortableRuntimeResult:
    decision_status: str
    has_selection: bool
    candidate_id: int
    next_hop_group: str
    score: float
    action_status: str
    action_generation: int
    backend_attempted: bool
    backend_applied: bool
    policy: str
    decision_reason: str
    action_reason: str
    backend_detail: str
    action_duration_s: float
    callback_error: str


class PortableIrDegGovernor:
    """Thin Python binding to the shared C++ IR-Deg policy and admission runtime."""

    STABLE_CANDIDATE = 1
    SUPPRESS_CANDIDATE = 2

    def __init__(
        self,
        action_callback: Callable[[int, str], bool | None],
        *,
        library_path: str | Path | None = None,
        scope: str = "10.30.2.0/24",
        traffic_class: int = 0,
        generation: int = 1,
        dwell_events: int = 2,
        action_budget: int = 1,
        budget_window_s: float = 30.0,
    ) -> None:
        if dwell_events < 1:
            raise ValueError("dwell_events must be at least one")
        if action_budget < 1 or budget_window_s <= 0.0:
            raise ValueError("action_budget and budget_window_s must be positive")

        self._library = _load_library(library_path)
        self._scope = scope.encode("utf-8")
        self._destination = self._scope
        self._traffic_class = traffic_class
        self._generation = generation
        self._action_callback = action_callback
        self._callback_error = ""
        self._callback_duration_s = 0.0
        self._callback = _ApplyCallback(self._apply)
        self._candidate_names = (b"ecmp", b"suppress_s1")
        self._candidates = (_Candidate * 2)(
            _Candidate(self.STABLE_CANDIDATE, 0.0, 1, self._candidate_names[0]),
            _Candidate(self.SUPPRESS_CANDIDATE, 0.0, 1, self._candidate_names[1]),
        )

        config = _UpdateConfig(
            1,
            0.0,
            float(action_budget) / budget_window_s,
            float(action_budget),
            dwell_events,
        )
        error = ctypes.create_string_buffer(ERROR_SIZE)
        self._handle = self._library.ir_srlinux_adapter_create(
            b"ir-deg",
            ctypes.byref(config),
            self._callback,
            None,
            error,
            len(error),
        )
        if not self._handle:
            raise RuntimeError(f"failed to create portable runtime: {_decode(error.value)}")

        seeded = self._library.ir_srlinux_adapter_seed_active(
            self._handle,
            self._scope,
            self._generation,
            self._candidates,
            len(self._candidates),
            self._traffic_class,
            self.STABLE_CANDIDATE,
            0.0,
            error,
            len(error),
        )
        if seeded != 1:
            self.close()
            raise RuntimeError(f"failed to seed native active view: {_decode(error.value)}")

    def _apply(
        self,
        _user_data: int,
        _destination: bytes,
        _traffic_class: int,
        candidate_id: int,
        next_hop_group: bytes,
    ) -> int:
        self._callback_error = ""
        started = time.monotonic()
        try:
            applied = self._action_callback(candidate_id, _decode(next_hop_group))
            return 1 if applied is None or applied else 0
        except Exception as exception:  # never propagate through a C callback
            self._callback_error = f"{type(exception).__name__}: {exception}"
            return -1
        finally:
            self._callback_duration_s = time.monotonic() - started

    def observe(self, evidence: EvidenceRecord) -> PortableRuntimeResult:
        if not self._handle:
            raise RuntimeError("portable runtime is closed")

        self._callback_error = ""
        self._callback_duration_s = 0.0
        normalized = max(evidence.value / max(evidence.threshold, 1e-12), 1.0)
        if evidence.kind == "app_jitter":
            queue_values = (normalized, 0.0)
        elif evidence.kind == "app_healthy":
            queue_values = (0.0, 1.0)
        else:
            raise ValueError(f"unsupported evidence kind: {evidence.kind}")

        kind = b"queue"
        source = evidence.source.encode("utf-8")
        records = (_Evidence * 2)(
            _Evidence(
                self.STABLE_CANDIDATE,
                kind,
                queue_values[0],
                evidence.confidence,
                evidence.timestamp_s,
                evidence.expires_s,
                source,
            ),
            _Evidence(
                self.SUPPRESS_CANDIDATE,
                kind,
                queue_values[1],
                evidence.confidence,
                evidence.timestamp_s,
                evidence.expires_s,
                source,
            ),
        )
        result = _Result()
        error = ctypes.create_string_buffer(ERROR_SIZE)
        ok = self._library.ir_srlinux_adapter_execute(
            self._handle,
            self._destination,
            self._traffic_class,
            evidence.timestamp_s,
            self._scope,
            self._generation,
            self._candidates,
            len(self._candidates),
            self._scope,
            self._generation,
            self._candidates,
            len(self._candidates),
            records,
            len(records),
            1,
            ctypes.byref(result),
            error,
            len(error),
        )
        if ok != 1:
            raise RuntimeError(f"portable runtime execution failed: {_decode(error.value)}")
        return PortableRuntimeResult(
            decision_status=DECISION_STATUS.get(result.decision_status, "unknown"),
            has_selection=bool(result.has_selection),
            candidate_id=result.candidate_id,
            next_hop_group=_decode(result.next_hop_group),
            score=result.score,
            action_status=ACTION_STATUS.get(result.action_status, "unknown"),
            action_generation=result.action_generation,
            backend_attempted=bool(result.backend_attempted),
            backend_applied=bool(result.backend_applied),
            policy=_decode(result.policy),
            decision_reason=_decode(result.decision_reason),
            action_reason=_decode(result.action_reason),
            backend_detail=_decode(result.backend_detail),
            action_duration_s=self._callback_duration_s,
            callback_error=self._callback_error,
        )

    def close(self) -> None:
        handle = getattr(self, "_handle", None)
        if handle:
            self._library.ir_srlinux_adapter_destroy(handle)
            self._handle = None

    def __enter__(self) -> PortableIrDegGovernor:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
