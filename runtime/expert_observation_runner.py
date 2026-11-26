# -*- coding: utf-8 -*-
"""
Ämnesexpert-observationer: sakfrågor endast.
Får inte generera juridisk slutsats eller rekvisit-subsumtion.
requested=True krävs.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional


def run_expert_observations_if_requested(
    domain: str = "TEKNISK",
    observations: Optional[List[Dict]] = None,
    requested: bool = False,
    pipeline_state: Any = None,
) -> Dict[str, Any]:
    if not requested:
        return {
            "status": "EJ_BEGÄRD",
            "detail": "Expert-observationer kräver requested=True.",
        }
    import sys as _sys
    from pathlib import Path as _P
    _rt = str(_P(__file__).resolve().parents[1] / "runtime")
    if _rt not in _sys.path:
        _sys.path.insert(0, _rt)
    from hard_stop_las import spärrsvar
    _sp = spärrsvar('expert_observation', pipeline_state)
    if _sp:
        return _sp
    domain = (domain or "TEKNISK").upper()
    obs = []
    for o in observations or []:
        if not isinstance(o, dict):
            continue
        obs.append({
            "domain": domain,
            "observation": str(o.get("observation") or o.get("text") or "")[:500],
            "source_id": o.get("source_id") or o.get("källa") or "SAKNAS",
            "confidence_note": "INDIKATIV_ENDAST",
            "legal_conclusion": None,  # explicit forbidden
        })
    return {
        "status": "GENOMFÖRD",
        "domain": domain,
        "antal": len(obs),
        "observations": obs,
        "rule": "Expertpanel får endast etablera sakobservationer — ingen juridisk slutsats.",
    }
