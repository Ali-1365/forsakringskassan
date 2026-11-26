# OBS (P2): core_types.PipelineState är Enum för canonical FSM (17 states).
# dynamic_pipeline.PipelineState är separat dataclass (orkestreringsbuss).
# De är medvetet skilda — blanda inte ihop vid patchning.
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SFCAE core_types — stabil importyta för pipeline-enums.

Source of truth: runtime/forensic_engine_v10_3_canonical.py
Denna modul re-exporterar canonicals Enums så att `is`-identitet håller
mellan dynamic_pipeline och canonical (RIG/forensic gap: dubbla Enum-klasser).
"""
from __future__ import annotations

from enum import Enum

# Re-export från canonical (enda definitionen)
from forensic_engine_v10_3_canonical import (  # noqa: E402
    PipelineState,
    ProcessMode,
    HardStopCode,
    CourtType,
    EvidenceCategory,
    AuditStatus,
    FalsificationVerdict,
    ExecutionMode,
)

__all__ = [
    "PipelineState",
    "ProcessMode",
    "HardStopCode",
    "ModeRouter",
    "CourtType",
    "EvidenceCategory",
    "AuditStatus",
    "FalsificationVerdict",
    "ExecutionMode",
]


class ModeRouter(Enum):
    """SKILL dual-state → ProcessMode (canonical)."""

    ANALYS = "JUDGMENT_AUDIT"
    PRODUKTION = "JUDGMENT_CONSTRUCTION"

    def to_process_mode(self) -> ProcessMode:
        return ProcessMode(self.value)
