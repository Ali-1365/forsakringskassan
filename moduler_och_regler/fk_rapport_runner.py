# -*- coding: utf-8 -*-
"""
FK rapport-filter: kritiska problem, mönster, diarienummer, top-10.
Migrerad från fk_smart_filter.py — konfigurerbar, ingen hårdkodad klientdata.
Valfri runner: requested=True krävs. Producerar aldrig domslut.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
import json
from pathlib import Path


def ladda_analys(filepath: str) -> dict:
    """Ladda JSON-analysfil om den finns."""
    p = Path(filepath)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _samla_kandidatposter(data: Any) -> List[Any]:
    """Samlar poster generellt från befintliga fält och nya scan-/beviskravssektioner."""
    poster: List[Any] = []
    if not isinstance(data, dict):
        return poster

    for key in ("kritiska", "problems", "problem", "resultat", "dokument", "filer"):
        items = data.get(key)
        if isinstance(items, list):
            poster.extend(items)
        elif isinstance(items, dict):
            poster.extend(items.values())

    for sec_key in ("antitemplate_scan", "monsterkatalog_scan", "kodscan"):
        sec = data.get(sec_key)
        if isinstance(sec, dict):
            träffar = sec.get("träffar")
            if isinstance(träffar, list):
                for t in träffar:
                    if isinstance(t, dict):
                        poster.append({"_källa_sektion": sec_key, **t})
                    else:
                        poster.append(t)

    beviskrav = data.get("beviskrav_kategorier")
    if isinstance(beviskrav, dict) and isinstance(beviskrav.get("ärendetyper"), dict):
        for ärendetyp, spec in beviskrav["ärendetyper"].items():
            if not isinstance(spec, dict):
                continue
            saknade = spec.get("saknade_kategorier") or []
            if saknade:
                poster.append({
                    "_källa_sektion": "beviskrav_kategorier",
                    "ärendetyp": ärendetyp,
                    "saknade_kategorier": list(saknade),
                    "uppfyllda_kategorier": list(spec.get("uppfyllda_kategorier") or []),
                })

    return poster


def filtrera_kritiska_problem(data: dict) -> list:
    """Returnera poster märkta kritiska/allvarliga eller med saknade beviskravskategorier."""
    out = []
    if not isinstance(data, dict):
        return out

    for it in _samla_kandidatposter(data):
        if isinstance(it, dict):
            sev = str(
                it.get("allvarlighet")
                or it.get("severity")
                or it.get("föreslaget_block")
                or it.get("indikation")
                or ""
            ).upper()
            if (
                any(tag in sev for tag in ("KRITISK", "HÖG", "CRITICAL", "HIGH", "ALLVARLIG"))
                or bool(it.get("kritisk"))
                or bool(it.get("saknade_kategorier"))
            ):
                out.append(it)
        else:
            out.append(it)

    if not out and "monster" in data and isinstance(data["monster"], dict):
        for kod, v in data["monster"].items():
            if isinstance(v, dict) and any(
                tag in str(v.get("allvarlighet", "")).upper() for tag in ("KRITISK", "HÖG", "ALLVARLIG")
            ):
                out.append({"kod": kod, **v})
    return out


def filtrera_monster(data: dict, monster_kod: str) -> list:
    out = []
    if not isinstance(data, dict):
        return out
    target = str(monster_kod).upper()

    for it in _samla_kandidatposter(data):
        if isinstance(it, dict):
            kod_val = str(it.get("kod") or it.get("indikation") or it.get("ärendetyp") or "").upper()
            if target in kod_val or target in str(it).upper():
                out.append(it)
        elif target in str(it).upper():
            out.append(it)

    blob = data.get("monster") or data.get("mönster") or data.get("resultat") or data
    if isinstance(blob, dict):
        if monster_kod in blob:
            v = blob[monster_kod]
            return v if isinstance(v, list) else [v]
        for k, v in blob.items():
            if target in str(k).upper():
                out.append({"kod": k, "data": v})
    elif isinstance(blob, list):
        for it in blob:
            if isinstance(it, dict) and target in str(it).upper():
                out.append(it)
    return out


def filtrera_diarienummer(data: dict, diarie: str) -> list:
    out = []
    if not isinstance(data, dict):
        return out
    items = _samla_kandidatposter(data)
    if not items:
        raw_items = data.get("dokument") or data.get("resultat") or data.get("filer") or []
        items = list(raw_items.values()) if isinstance(raw_items, dict) else list(raw_items)
    for it in items:
        if diarie in str(it):
            out.append(it)
    return out


def hitta_top_dokument(data: dict, antal: int = 10) -> list:
    items = []
    if isinstance(data, dict):
        for key in ("top", "dokument", "resultat", "ranked"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
        if not items and isinstance(data.get("scores"), list):
            items = data["scores"]
        if not items:
            items = _samla_kandidatposter(data)
    if not items and isinstance(data, list):
        items = data
    return list(items)[: max(1, int(antal))]


def run_fk_rapport_if_requested(
    analys_data: Dict,
    requested: bool = False,
    filter_typ: str = "KRITISKA",
    monster_kod: Optional[str] = None,
    diarienummer: Optional[str] = None,
    antal: int = 10,
    pipeline_state: Any = None,
) -> Dict:
    """Valfri FK-rapportfilter. Kräver requested=True. Aldrig domslut.
    Vid aktiv domänspärr (pipeline_state eller analys_data) -> OUTPUT_SPÄRRAD."""
    if not requested:
        return {
            "status": "EJ_BEGÄRD",
            "detail": "Rapportfilter kräver explicit requested=True.",
        }
    import sys as _sys
    from pathlib import Path as _P
    _rt = str(_P(__file__).resolve().parents[1] / "runtime")
    if _rt not in _sys.path:
        _sys.path.insert(0, _rt)
    from hard_stop_las import spärrsvar
    _sp = spärrsvar('fk_rapport', pipeline_state, analys_data if isinstance(analys_data, dict) else None)
    if _sp:
        return _sp
    if not analys_data:
        return {
            "status": "EJ_KÖRBAR",
            "skäl": "Ingen analysdata angiven.",
        }
    try:
        if filter_typ == "KRITISKA":
            resultat = filtrera_kritiska_problem(analys_data)
        elif filter_typ == "TOP10":
            resultat = hitta_top_dokument(analys_data, antal)
        elif filter_typ == "MONSTER" and monster_kod:
            resultat = filtrera_monster(analys_data, monster_kod)
        elif filter_typ == "DIARIE" and diarienummer:
            resultat = filtrera_diarienummer(analys_data, diarienummer)
        else:
            return {
                "status": "EJ_KÖRBAR",
                "skäl": f"Okänt filter_typ: {filter_typ}",
            }
        return {
            "status": "GENOMFÖRD",
            "filter_typ": filter_typ,
            "antal_resultat": len(resultat) if isinstance(resultat, list) else 0,
            "resultat": resultat,
            "not": "INDIKATIV_ENDAST — juristen bedömer relevans",
        }
    except Exception as e:
        return {
            "status": "VARNING",
            "kod": "VARNING_RAPPORT_ERROR",
            "varning": True,
            "detail": f"{type(e).__name__}: {e}",
        }
