# -*- coding: utf-8 -*-
"""Valfri FK-mönster+entitetsscan. requested=True. Ingen domslutsgenerering."""
from __future__ import annotations
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent


def _ladda_modul():
    """Gemensam laddare — en fil ger ett modulobjekt. Se runtime/module_loader.py."""
    if str(ROOT / "runtime") not in sys.path:
        sys.path.insert(0, str(ROOT / "runtime"))
    from module_loader import ladda_modul
    return ladda_modul


def _load(name: str, rel: str):
    path = ROOT / rel
    if not path.is_file():
        return None
    return _ladda_modul()(name, path)


def _ladda_yaml_eller_json(path: Path) -> Dict[str, Any]:
    """Läser YAML eller JSON utan ärendespecifik logik; tydlig status vid saknad/fel."""
    if not path.is_file():
        return {"_status": "UNAVAILABLE", "_reason": f"Fil saknas: {path.name}"}
    raw = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(raw)
        return data if isinstance(data, dict) else {"_status": "UNAVAILABLE", "_reason": "Ogiltigt format"}
    except ImportError:
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {"_status": "UNAVAILABLE", "_reason": "PyYAML saknas"}
        except Exception as e:
            return {"_status": "UNAVAILABLE", "_reason": f"PyYAML saknas: {e}"}
    except Exception as e:
        return {"_status": "UNAVAILABLE", "_reason": f"Kunde inte läsa {path.name}: {e}"}


def _skanna_kodkatalog(text: str, katalog: Dict[str, Any]) -> Dict[str, Any]:
    """Generell mönstermatchning över 'koder:' i en kodtabell."""
    if katalog.get("_status") == "UNAVAILABLE":
        return {"status": "UNAVAILABLE", "reason": katalog.get("_reason", "Saknas"), "träffar": []}
    lower_text = text.lower()
    träffar: List[Dict[str, Any]] = []
    for post in katalog.get("koder") or []:
        if not isinstance(post, dict):
            continue
        neg = [str(n).lower() for n in (post.get("negativa_filter") or []) if n]
        if any(n in lower_text for n in neg):
            continue
        mönster = [str(m) for m in (post.get("mönster") or []) if m]
        matchade = [m for m in mönster if re.search(re.escape(m), text, flags=re.IGNORECASE)]
        if matchade:
            träffar.append({
                "kod": post.get("kod"),
                "lagrum": post.get("lagrum"),
                "beskrivning": post.get("beskrivning"),
                "föreslaget_block": post.get("föreslaget_block"),
                "indikation": post.get("indikation"),
                "matchade_mönster": matchade,
            })
    return {
        "status": "AVAILABLE",
        "domän": (katalog.get("meta") or {}).get("domän"),
        "antal_träffar": len(träffar),
        "träffar": träffar,
    }


def _detektera_dokumenttyper(text: str, beviskrav: Dict[str, Any]) -> Dict[str, Any]:
    """Matchar dokumentigenkänningsmönster i fk_beviskrav.yaml generellt mot text."""
    if beviskrav.get("_status") == "UNAVAILABLE":
        return {"status": "UNAVAILABLE", "reason": beviskrav.get("_reason", "Saknas"), "träffar": {}}
    mönster_karta = beviskrav.get("dokumentigenkänningsmönster") or {}
    if not isinstance(mönster_karta, dict):
        return {"status": "AVAILABLE", "träffar": {}}
    träffar: Dict[str, List[str]] = {}
    for dok_typ, nyckelord in mönster_karta.items():
        matchade = [str(ord_str) for ord_str in (nyckelord or []) if ord_str and re.search(re.escape(str(ord_str)), text, flags=re.IGNORECASE)]
        if matchade:
            träffar[str(dok_typ)] = matchade
    return {"status": "AVAILABLE", "träffar": träffar}


def _kontrollera_beviskrav_kategorier(text: str, beviskrav: Dict[str, Any]) -> Dict[str, Any]:
    """Generell kategorikontroll över 'ärendetyper:' i fk_beviskrav.yaml."""
    if beviskrav.get("_status") == "UNAVAILABLE":
        return {"status": "UNAVAILABLE", "reason": beviskrav.get("_reason", "Saknas"), "ärendetyper": {}}
    lower_text = text.lower()
    ärendetyper = beviskrav.get("ärendetyper") or {}
    utfall: Dict[str, Any] = {}
    for ärendetyp, spec in ärendetyper.items():
        if not isinstance(spec, dict):
            continue
        kategorier = spec.get("kategorier") or {}
        saknade_kategorier: List[str] = []
        uppfyllda_kategorier: List[str] = []
        for kat_namn, krav_lista in kategorier.items():
            krav_strängar = [str(x).lower() for x in (krav_lista or []) if x]
            # Generell nyckelordsprövning utan ärendespecifika regler
            har_träff = any(
                any(token in lower_text for token in re.findall(r"[a-zåäö0-9]{4,}", krav))
                for krav in krav_strängar
            )
            if har_träff:
                uppfyllda_kategorier.append(str(kat_namn))
            else:
                saknade_kategorier.append(str(kat_namn))
        utfall[str(ärendetyp)] = {
            "uppfyllda_kategorier": uppfyllda_kategorier,
            "saknade_kategorier": saknade_kategorier,
        }
    return {
        "status": "AVAILABLE",
        "ärendetyper": utfall,
    }


def run_fk_pattern_if_requested(
    text: str = "",
    requested: bool = False,
    pipeline_state: Any = None,
) -> Dict:
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "requested=True krävs"}
    import sys as _sys
    from pathlib import Path as _P
    _rt = str(_P(__file__).resolve().parents[1] / "runtime")
    if _rt not in _sys.path:
        _sys.path.insert(0, _rt)
    from hard_stop_las import spärrsvar
    _sp = spärrsvar('fk_pattern', pipeline_state)
    if _sp:
        return _sp
    if pipeline_state is not None and not text:
        out = getattr(pipeline_state, "output", None) or {}
        if isinstance(out, dict):
            text = out.get("raw_text") or ""
        if not text:
            claims = getattr(pipeline_state, "claims", None) or []
            text = " ".join(
                (c.get("text") if isinstance(c, dict) else str(c)) for c in claims
            )
    if not (text or "").strip():
        return {"status": "EJ_KÖRBAR", "skäl": "Ingen text"}

    scanner = _load("kodsystem_scanner", "runtime/kodsystem_scanner.py")
    entities = _load("fk_entity_extract", "runtime/fk_entity_extract.py")
    if scanner is None:
        return {"status": "VARNING", "kod": "VARNING_SCANNER_MISSING", "skäl": "Scanner saknas – kör i begränsat varningsläge"}

    mod_dir = ROOT / "moduler_och_regler"
    path = str(mod_dir / "kodsystem_fk_sfb.yaml")
    scan = scanner.skanna_text(text, kodtabell_path=path, domän="FK_SFB")
    ent = entities.extrahera_allt(text) if entities else {}

    antitemplate_data = _ladda_yaml_eller_json(mod_dir / "kodsystem_fk_antitemplate.yaml")
    monsterkatalog_data = _ladda_yaml_eller_json(mod_dir / "kodsystem_fk_monsterkatalog.yaml")
    beviskrav_data = _ladda_yaml_eller_json(mod_dir / "fk_beviskrav.yaml")

    return {
        "status": "GENOMFÖRD",
        "kodscan": scan,
        "entities": ent,
        "antitemplate_scan": _skanna_kodkatalog(text, antitemplate_data),
        "monsterkatalog_scan": _skanna_kodkatalog(text, monsterkatalog_data),
        "beviskrav_kategorier": _kontrollera_beviskrav_kategorier(text, beviskrav_data),
        "dokumentigenkanning": _detektera_dokumenttyper(text, beviskrav_data),
        "not": "INDIKATIV — jurist verifierar före processhandling",
    }

