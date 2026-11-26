# -*- coding: utf-8 -*-
"""Persistent låsstatus per körning (steg 10).

observability är medvetet in-memory; utan det här registret förlorade
MCP-verktygen körningens låsstatus vid omstart. Här sparas ENDAST
icke-känslig metadata: run_id -> pipeline_state, hard_stop_codes, case_id,
tidsstämpel. Inga texter, inga sökvägar till akten, inga hemligheter.

Lagring: ROOT/output/run_lock_status.json (gitignorerad; aldrig under en
akts rot). Kan styras med miljövariabeln SFCAE_RUN_LOCK_STORE (tester).
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
_MAX_POSTER = 500
_LÅS = threading.Lock()


def lagringsväg() -> Path:
    return Path(os.environ.get("SFCAE_RUN_LOCK_STORE") or (ROOT / "output" / "run_lock_status.json"))


def _läs(p: Path) -> Dict[str, Dict[str, Any]]:
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8") or "{}")
    return data if isinstance(data, dict) else {}


def spara(run_id: str, pipeline_state: Optional[str], hard_stop_codes: List[str],
          case_id: Optional[str]) -> Path:
    p = lagringsväg()
    with _LÅS:
        p.parent.mkdir(parents=True, exist_ok=True)
        data = _läs(p)
        data[run_id] = {
            "pipeline_state": pipeline_state,
            "hard_stop_codes": [str(k) for k in hard_stop_codes],
            "case_id": case_id,
            "tid_utc": datetime.now(timezone.utc).isoformat(),
        }
        if len(data) > _MAX_POSTER:
            for rid in sorted(data, key=lambda r: data[r].get("tid_utc", ""))[: len(data) - _MAX_POSTER]:
                del data[rid]
        # Steg 21: unikt tmp-namn per process/tråd. Ett delat ".tmp" lät två
        # processer skriva samma fil samtidigt -> "Extra data" i JSON.
        import threading
        tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, p)
    return p


def hämta(run_id: str) -> Optional[Dict[str, Any]]:
    with _LÅS:
        return _läs(lagringsväg()).get(run_id)
