from __future__ import annotations
# SFCAE-BINDNING: material_registry
# Roll: Materialregister
# Alt B — anropas via requested=True från pipeline eller MCP.
# Producerar aldrig domslut. INDIKATIV_ENDAST.
_BUNDEN_TILL_SFCAE = True
_ROLL = "Materialregister"

# -*- coding: utf-8 -*-
"""P00 Materialregistrering — registrerar objekt utan juridisk kvalificering."""
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
    _Y = True
except ImportError:
    _Y = False

ROOT = Path(__file__).resolve().parent.parent


# Orsaken till att blueprinten inte kunde läsas, när det berodde på ett fel.
# Utan den blev en TRASIG blueprint oskiljbar från en som saknas: båda gav
# minimifältlistan nedan, och att registret krympt syntes ingenstans.
_FÄLT_LADDNINGSFEL: Optional[str] = None

# Minimifält som alltid registreras när blueprinten inte kan läsas.
_MINIMIFÄLT = ["SOURCE_ID", "SOURCE_TYPE", "REQUESTED_OR_UNSOLICITED"]


def fält_laddningsfel() -> Optional[str]:
    """Felet som hindrade blueprinten från att läsas, eller None."""
    return _FÄLT_LADDNINGSFEL


def _fält() -> List[str]:
    global _FÄLT_LADDNINGSFEL
    _FÄLT_LADDNINGSFEL = None
    p = ROOT / "config" / "blueprint_p00_material.yaml"
    if _Y and p.is_file():
        try:
            d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            return list(d.get("fält") or [])
        except Exception as exc:
            _FÄLT_LADDNINGSFEL = f"{type(exc).__name__}: {exc}"
    elif not _Y:
        _FÄLT_LADDNINGSFEL = "pyyaml saknas"
    elif not p.is_file():
        _FÄLT_LADDNINGSFEL = f"blueprint saknas: {p.name}"
    return list(_MINIMIFÄLT)


def registrera_material(
    filer: Optional[List[Any]] = None,
    requested_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    filer = filer or []
    req = {n.lower() for n in (requested_names or [])}
    poster = []
    for i, f in enumerate(filer):
        if isinstance(f, dict):
            name = str(f.get("name") or f.get("filnamn") or f.get("path") or f"OBJ-{i}")
            path = str(f.get("path") or "")
            stype = str(f.get("type") or f.get("source_type") or "DOCUMENT")
        else:
            name = str(f)
            path = ""
            stype = "DOCUMENT"
        kind = "REQUESTED" if any(r in name.lower() or name.lower() == r for r in req) else "UNSOLICITED"
        # Tre skilda utfall som tidigare alla blev None: ingen sökväg angiven,
        # sökväg som inte pekar på en fil, och en fil vars hash inte kunde
        # beräknas. Det sista är en integritetsbrist och får inte se likadant
        # ut som att posten aldrig hade någon fil att hasha.
        if not path:
            h = "INGEN SÖKVÄG"
        elif not Path(path).is_file():
            h = "FILEN SAKNAS"
        else:
            try:
                h = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
            except Exception as exc:
                h = f"KAN EJ BERÄKNAS: {type(exc).__name__}"
        poster.append({
            "SOURCE_ID": f"SRC-{i+1:04d}",
            "SOURCE_TYPE": stype,
            "SOURCE_ORIGIN": path or name,
            "RECEIVED_TIMESTAMP": datetime.now(timezone.utc).isoformat(),
            "HASH": h,
            "RELATION_TO_CASE": "REGISTERED",
            "REQUESTED_OR_UNSOLICITED": kind,
            "PREVIOUSLY_KNOWN_OR_NEW": "NEW",
            "SOURCE_AUTHORITY": "UNKNOWN",
            "PROCESSUAL_STATUS": "PENDING_QUALIFICATION",
            "filnamn": name,
            "not": "INDIKATIV — ej bevis",
        })
    return {
        "status": "GENOMFÖRD" if poster else "EJ_KÖRBAR",
        "antal": len(poster),
        "poster": poster,
        "schema_fält": _fält(),
        "not": "P00: Allt är data tills integrity/relevans passerats. Inte automatiskt bevis.",
    }


def run_material_registry_if_requested(
    filer: Optional[List] = None,
    requested_names: Optional[List[str]] = None,
    pipeline_state: Any = None,
    requested: bool = False,
) -> Dict[str, Any]:
    if not requested:
        return {"status": "EJ_BEGÄRD"}
    if filer is None and pipeline_state is not None:
        filer = list(getattr(pipeline_state, "files", []) or [])
    return registrera_material(filer=filer, requested_names=requested_names)
