# -*- coding: utf-8 -*-
"""
FL/FPL process-runner (Alt B).
Anropar kodsystem_scanner mot kodsystem_fpl_forvaltning.yaml.
Ingen domslutsgenerering. requested=True krävs.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Optional
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "runtime"))


def run_fl_process_if_requested(
    text: str = "",
    requested: bool = False,
    kodtabell_path: Optional[str] = None,
    pipeline_state: Any = None,
) -> Dict[str, Any]:
    if not requested:
        return {
            "status": "EJ_BEGÄRD",
            "detail": "FL/FPL-process kräver explicit requested=True.",
        }
    import sys as _sys
    from pathlib import Path as _P
    _rt = str(_P(__file__).resolve().parents[1] / "runtime")
    if _rt not in _sys.path:
        _sys.path.insert(0, _rt)
    from hard_stop_las import spärrsvar
    _sp = spärrsvar('fl_process', pipeline_state)
    if _sp:
        return _sp
    if not text or not str(text).strip():
        return {"status": "EJ_KÖRBAR", "skäl": "Tom text."}

    path = kodtabell_path or str(ROOT / "config" / "kodsystem_fpl_forvaltning.yaml")
    try:
        from kodsystem_scanner import skanna_text
        r = skanna_text(text, kodtabell_path=path)
    except Exception as e:
        return {"status": "VARNING", "varning": True, "skäl": f"Scannerfel (icke-blockerande varning): {e}"}

    # Enforce indikativ märkning
    for t in r.get("träffar", []) or []:
        if isinstance(t, dict):
            t.setdefault("indikation", "INDIKATIV_ENDAST")
            t["not"] = "INDIKATIV_ENDAST — ingen automatisk processutgång"
    r["provisorisk"] = True
    r["not"] = "FL/FPL-träffar är indikativa. Juristen verifierar."
    return r
