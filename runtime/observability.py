from __future__ import annotations
# SFCAE-BINDNING: observability
# Roll: körnings-/eventregister för dashboardet (#8/#9-uppföljning)
# Alt B — anropas från call_tool()/dynamic_pipeline/consolidated_engine.
_BUNDEN_TILL_SFCAE = True
_ROLL = "Observability — körnings- och eventregister"

# -*- coding: utf-8 -*-
"""
OBSERVABILITY — in-memory register över RIKTIGA körningar och RIKTIGA events.

Detta är INTE en egen motor och innehåller ingen juridisk logik. Det är ett
passivt register som andra, redan verkliga körvägar (mcp/server.py::call_tool,
runtime/dynamic_pipeline.py::run_dynamic_pipeline,
integrations/consolidated_engine.py::consolidate) skriver in RIKTIGA events i
när de faktiskt exekverar. Ingenting här hittar på ett event, ett värde eller
en status som inte redan producerats av den riktiga koden.

Ett Run har ett run_id (korrelations-id). Ett Run kan ha ett parent_run_id —
satt automatiskt via en contextvar när en MCP-verktygskörning (call_tool)
internt startar en fullständig pipelinekörning (t.ex. sfcae_run_pipeline →
run_dynamic_pipeline), så att dashboardet kan visa den verkliga nästlingen
i stället för två orelaterade rader.

In-memory, processlokalt: en omstart av FastAPI-processen tömmer
registret (runs/events). Undantag (steg 10): vid end_run för en
pipelinekörning (case_state_obj eller hard_stop_codes angivet) skrivs
körningens låsstatus - run_id, pipeline_state, hard_stop_codes, case_id,
tidsstämpel; inga texter eller sökvägar - till ROOT/output/run_lock_status.json
via run_lock_store (styrbart med SFCAE_RUN_LOCK_STORE), så att låsstatusen
överlever omstart.
"""

import contextvars
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_LOCK = threading.RLock()
_MAX_RUNS = 200  # äldsta körningen kastas vid överskridande — en ärlig, redovisad gräns

_ACTIVE_RUN: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "sfcae_observability_active_run", default=None
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Event:
    event_id: str
    run_id: str
    seq: int
    ts_utc: str
    type: str  # RUN_START | STEP_START | STEP_END | TOOL_CALL | RUN_END | ERROR
    step_id: Optional[str] = None
    module: Optional[str] = None
    tool: Optional[str] = None
    status: Optional[str] = None
    duration_ms: Optional[float] = None
    detail: str = ""
    error: str = ""
    källa: Any = "NOT_AVAILABLE"
    case_eller_dokument_id: Any = "NOT_AVAILABLE"
    fallback_anvant: Any = "NOT_AVAILABLE"
    verifieringsstatus: str = "EJ_TILLÄMPLIGT"
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id, "run_id": self.run_id, "seq": self.seq,
            "ts_utc": self.ts_utc, "type": self.type, "step_id": self.step_id,
            "module": self.module, "tool": self.tool, "status": self.status,
            "duration_ms": self.duration_ms, "detail": self.detail, "error": self.error,
            "källa": self.källa, "case_eller_dokument_id": self.case_eller_dokument_id,
            "fallback_anvant": self.fallback_anvant,
            "verifieringsstatus": self.verifieringsstatus, "data": self.data,
        }


@dataclass
class Run:
    run_id: str
    kind: str  # "dynamic_pipeline" | "consolidated_engine" | "mcp_tool"
    started_at_utc: str
    parent_run_id: Optional[str] = None
    ended_at_utc: Optional[str] = None
    status: str = "PÅGÅR"
    case_id: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)
    events: List[Event] = field(default_factory=list)
    # Aldrig serialiserat till API — endast för in-process källkedjespårning.
    case_state_obj: Any = field(default=None, repr=False)

    def to_dict(self, include_events: bool = False) -> Dict[str, Any]:
        d = {
            "run_id": self.run_id, "kind": self.kind,
            "parent_run_id": self.parent_run_id,
            "started_at_utc": self.started_at_utc, "ended_at_utc": self.ended_at_utc,
            "status": self.status, "case_id": self.case_id or "NOT_AVAILABLE",
            "meta": self.meta, "event_count": len(self.events),
            "case_state_tillgänglig_för_sparning": self.case_state_obj is not None,
        }
        if include_events:
            d["events"] = [e.to_dict() for e in self.events]
        return d


_RUNS: "Dict[str, Run]" = {}
_RUN_ORDER: List[str] = []  # insättningsordning, för evikering av äldst


def _evict_if_needed() -> None:
    # Körningar med domänspärr behåller sin spårning: äldsta körning UTAN
    # spärr kastas först. Bara om alla har spärr kastas den äldsta (gränsen
    # är fortfarande ärlig och begränsad).
    while len(_RUN_ORDER) > _MAX_RUNS:
        offer = next((rid for rid in _RUN_ORDER
                      if not (_RUNS.get(rid) and _RUNS[rid].meta.get("hard_stop_codes"))),
                     _RUN_ORDER[0])
        _RUN_ORDER.remove(offer)
        _RUNS.pop(offer, None)


def start_run(kind: str, meta: Optional[Dict[str, Any]] = None,
              case_id: Optional[str] = None,
              parent_run_id: Optional[str] = None) -> str:
    run_id = uuid.uuid4().hex[:12]
    parent = parent_run_id if parent_run_id is not None else _ACTIVE_RUN.get()
    with _LOCK:
        r = Run(run_id=run_id, kind=kind, started_at_utc=_now(),
                parent_run_id=parent, case_id=case_id, meta=meta or {})
        _RUNS[run_id] = r
        _RUN_ORDER.append(run_id)
        _evict_if_needed()
    emit(run_id, "RUN_START", status="PÅGÅR", detail=f"Run startad ({kind})")
    return run_id


def emit(run_id: str, type: str, **kwargs) -> Optional[Event]:
    with _LOCK:
        r = _RUNS.get(run_id)
        if r is None:
            return None
        seq = len(r.events)
        ev = Event(event_id=f"{run_id}-{seq}", run_id=run_id, seq=seq, ts_utc=_now(),
                   type=type, **kwargs)
        r.events.append(ev)
        return ev


def end_run(run_id: str, status: str, case_id: Optional[str] = None,
            case_state_obj: Any = None, hard_stop_codes: Optional[List[str]] = None) -> None:
    with _LOCK:
        r = _RUNS.get(run_id)
        if r is None:
            return
        r.ended_at_utc = _now()
        r.status = status
        if hard_stop_codes:
            r.meta["hard_stop_codes"] = list(hard_stop_codes)
        if case_id:
            r.case_id = case_id
        if case_state_obj is not None:
            r.case_state_obj = case_state_obj
        sparas = case_state_obj is not None or hard_stop_codes is not None
        cid = r.case_id
    if sparas:
        # Steg 10: låsstatus persisteras (överlever omstart). Endast metadata.
        import run_lock_store
        ps = getattr(getattr(case_state_obj, "pipeline_state", None), "value",
                     getattr(case_state_obj, "pipeline_state", None)) or status
        koder = [str(getattr(k, "value", k)) for k in
                 (hard_stop_codes or getattr(case_state_obj, "hard_stop_codes", None) or [])]
        run_lock_store.spara(run_id, str(ps), koder, cid or getattr(case_state_obj, "case_id", None))
    emit(run_id, "RUN_END", status=status, detail=f"Run avslutad: {status}")


class active_run:
    """Context manager: markerar run_id som 'aktiv' för nästlade start_run()-
    anrop under blockets exekvering (t.ex. call_tool() runt en handler som
    internt kör run_dynamic_pipeline/consolidate)."""

    def __init__(self, run_id: Optional[str]):
        self.run_id = run_id
        self._token = None

    def __enter__(self):
        self._token = _ACTIVE_RUN.set(self.run_id)
        return self

    def __exit__(self, *exc):
        if self._token is not None:
            _ACTIVE_RUN.reset(self._token)
        return False


def get_run(run_id: str) -> Optional[Run]:
    with _LOCK:
        return _RUNS.get(run_id)


def list_runs() -> List[Run]:
    with _LOCK:
        return sorted(_RUNS.values(), key=lambda r: r.started_at_utc, reverse=True)


def get_case_state(run_id: str) -> Any:
    with _LOCK:
        r = _RUNS.get(run_id)
        return r.case_state_obj if r else None


def clear_all() -> None:
    """Endast för tester — tömmer registret mellan testfall."""
    with _LOCK:
        _RUNS.clear()
        _RUN_ORDER.clear()
