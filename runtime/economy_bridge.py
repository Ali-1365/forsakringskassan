from __future__ import annotations
# SFCAE-BINDNING: economy_bridge
# Roll: Alt B-modul (economy_bridge)
# Alt B — anropas via requested=True från pipeline eller MCP.
_BUNDEN_TILL_SFCAE = True
_ROLL = "economy_bridge"

"""GAP-E: ECONOMY_BRIDGE — brygga till fas5 ekonomisk rekonstruktion.

Aterstaeller den historiska integrationskedjan:
  unified_engine -> economy_bridge -> function_sources/fas5_economic_reconstruction
                                     (reconstruct_economic_chain)

Registrsoekvagor kan ges explicit via meta ("fas3_register"/"fas4_register").
Saknas register returneras aerlig status REGISTER_SAKNAS (aldrig fabicerade
belopp). Utdata skrivs av unified_engine in i case_state.metadata
(economic_reconstruction) och verdict["layers"]["economic_reconstruction"].
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
_RUNTIME = _ROOT / "runtime"
for _p in (_SCRIPTS, _RUNTIME, _ROOT / "integrations"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

ECONOMY_IMPORT_ERROR: str | None = None
try:
    from fas5_economic_reconstruction import reconstruct_economic_chain  # noqa: E402
except ImportError as exc:
    reconstruct_economic_chain = None  # graceful — REGISTER_SAKNAS path still works
    ECONOMY_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


def _load(path: str):
    fp = Path(path)
    if not fp.is_file():
        return None
    with fp.open(encoding="utf-8") as handle:
        return json.load(handle)


def run_economic_reconstruction(meta: Optional[Dict[str, Any]] = None,
                                fas3: Optional[Dict] = None,
                                fas4: Optional[Dict] = None) -> Dict:
    """Kor FAS5-ekonomisk rekonstruktion via den rekonstruerade kaelian."""
    meta = meta or {}
    if reconstruct_economic_chain is None:
        return {
            "fas": "FAS 5 - Ekonomisk rekonstruktion och kontroll",
            "status": "MODUL_SAKNAS",
            "flaggor": ["fas5_economic_reconstruction kunde inte importeras"],
            "rekonstruktioner": [],
            "antal_rekonstruktioner": 0,
        }
    # 

    # 1) Explicita register fraan case_metadata (om angivna och existerande)
    if fas3 is None and meta.get("fas3_register"):
        fas3 = _load(str(meta["fas3_register"]))
    if fas4 is None and meta.get("fas4_register"):
        fas4 = _load(str(meta["fas4_register"]))

    # 2) Rekonstruktion ( REGISTER_SAKNAS om inga register finns )
    result = reconstruct_economic_chain(fas3=fas3, fas4=fas4)
    result["adapter"] = "economy_bridge (GAP-E)"
    result["integrationspunkt"] = (
        "unified_engine -> economy_bridge -> fas5_economic_reconstruction"
        ".reconstruct_economic_chain"
    )
    return result

def run_economy_bridge_if_requested(requested: bool = False, **kwargs):
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "economy_bridge kräver requested=True."}
    try:
        res = run_economic_reconstruction(**kwargs)
        if isinstance(res, dict):
            res.setdefault("status", "GENOMFÖRD")
            return res
        return {"status": "GENOMFÖRD", "resultat": res}
    except TypeError as e:
        return {"status": "EJ_KÖRBAR", "skäl": f"Saknade eller ogiltiga parametrar: {e}"}
    except Exception as e:
        return {"status": "FEL", "fel": f"{type(e).__name__}: {e}"}
