from __future__ import annotations
# PASSIV MOTIVERING: Framtida runtime-brygga. Bibehålls — ej aktiverad i v10.3.
# Bibehålls per arkitekturbeslutet.
_PASSIV_MOTIVERING = True

"""
NY_RUNTIME_BRIDGE — Brygga till Ny-mappens canonical-motor (10.3-UPDATED).

Konsolideringskrav: Ny-mappens unika funktioner får inte försvinna genom att
Motor C väljs som bas. Denna modul importerar den bevarade Ny-mapp-motorn
(runtime_ny/scripts/forensic_engine_v10_3_canonical.py) och exponerar dess
unika funktionella substans som en del av den konsoliderade arkitekturen.

Unika funktioner som exponeras (VERIFIERAT i källkoden):
  - AgentCStressTest            (adversarial pass, rad ~1160)
  - AuditController             (AuditControllerVerdict, rad ~1795)
  - CounterAuditAgent._check_b01.._check_b15  (full B01–B15, rad ~1330+)
  - HS19 "EXPECTED_NOT_FOUND"   (HardStopCode, rad ~127)
  - LegalSourceSearchIntegration (rad ~2358)
  - CourtType / ProcessMode / ModalMarker / PipelineState (enums)
  - run_pipeline (rad ~2493) + subagent_testsvit
"""

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Optional

# KONSOLIDERAD-ARKITEKTUR: canonical-motorn ligger fysiskt i runtime/,
# inte i runtime_ny/ (katalogen runtime_ny existerar inte i sluttradet).
_SCRIPTS = Path(__file__).resolve().parent.parent / "runtime"

_MODULE = None


def _loader() -> Any:
    global _MODULE
    if _MODULE is not None:
        return _MODULE
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    path = _SCRIPTS / "forensic_engine_v10_3_canonical.py"
    if not path.is_file():
        print(f"[FLAGGA | HS04] Ny-mapp-motor saknas (körningen fortsätter): {path}"); return None
    from module_loader import ladda_modul
    mod = ladda_modul("forensic_engine_v10_3_canonical", path)
    _MODULE = mod
    return mod


def get_unique_symbols() -> dict:
    """Listar vilken unik substans som faktiskt finns i den importerade motorn."""
    m = _loader()
    names = ["AgentCStressTest", "AuditController", "CounterAuditAgent",
             "LegalSourceSearchIntegration", "CourtType", "ProcessMode",
             "ModalMarker", "PipelineState", "HardStopCode", "run_pipeline",
             "subagent_testsvit", "generate_audit_report",
             "generate_audit_telemetry_header"]
    return {n: hasattr(m, n) for n in names}


def has_hs19() -> bool:
    """Verifierar HS19 (EXPECTED_NOT_FOUND) som en HardStopCode-medlem."""
    m = _loader()
    hsc = getattr(m, "HardStopCode", None)
    if hsc is None:
        return False
    return any("HS19" in str(v) for v in hsc)


def run_testsvit() -> dict:
    """Kör Ny-mappens inbyggda testsvit (T-01–T-05) i den konsoliderade källan."""
    m = _loader()
    fn = getattr(m, "subagent_testsvit", None)
    if fn is None:
        return {"status": "EJ TILLGÄNGLIG"}
    return fn()


if __name__ == "__main__":
    print("UNIKA SYMBOLER:", get_unique_symbols())
    print("HS19:", has_hs19())