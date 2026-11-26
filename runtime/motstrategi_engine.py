# -*- coding: utf-8 -*-
"""Motstrategisk analysmotor. INDIKATIV_ENDAST. requested=True."""
from __future__ import annotations
import copy
from typing import Any, Dict, List, Optional

# Steg 18: mönstren (motargument, lagrum, bemötande, bevisbörda) ligger i
# config/motstrategi_templates.yaml och laddas via config_loader. Saknas
# eller är filen ogiltig blir motstrategin EJ_KÖRBAR - ingen inbyggd fallback.
_MALLFIL = "motstrategi_templates"
_FÄLT = ("motpartens_argument", "lagrum", "bemötande_struktur", "bevisbörda")


def _ladda_mönster():
    """(mönster per domän, None) eller (None, skäl)."""
    try:
        import config_loader
        data = config_loader.ladda("motstrategi_templates")
    except ImportError as exc:
        return None, f"config_loader ej tillgänglig: {exc}"
    if not isinstance(data, dict):
        return None, f"config/{_MALLFIL}.yaml saknas eller kunde inte läsas"
    mönster = data.get("mönster")
    if not isinstance(mönster, dict) or not mönster:
        return None, f"config/{_MALLFIL}.yaml saknar 'mönster' eller är tom"
    for domän, lista in mönster.items():
        if not isinstance(lista, list) or not all(
                isinstance(m, dict) and all(k in m for k in _FÄLT) for m in lista):
            return None, f"config/{_MALLFIL}.yaml: ogiltig post för domän {domän}"
    return mönster, None


def analysera_motstrategi(domän: str, ej_styrkt_rekvisit: List[str], hard_stops: List[str], extra_kontext: Optional[str] = None) -> Dict:
    alla, fel = _ladda_mönster()
    if fel:
        return {"status": "EJ_KÖRBAR", "skäl": fel, "domän": domän}
    mönster = alla.get(domän, [])
    if not mönster:
        return {"status": "INGEN_MALL", "skäl": f"Inga motstrategiska mönster för domän '{domän}'", "domän": domän}
    matchade = []
    for m in mönster:
        relevans = any(
            rekv.lower() in m["motpartens_argument"].lower() or m["motpartens_argument"].lower() in rekv.lower()
            for rekv in (ej_styrkt_rekvisit or [])
        )
        matchade.append({
            "argument": m["motpartens_argument"],
            "lagrum": m["lagrum"],
            "bemötande": m["bemötande_struktur"],
            "bevisbörda": m["bevisbörda"],
            "relevans_för_ärendet": "HÖG" if relevans else "MEDEL",
            "not": "INDIKATIV_ENDAST — juristen bedömer relevans",
        })
    matchade.sort(key=lambda x: 0 if x["relevans_för_ärendet"] == "HÖG" else 1)
    komplettering = []
    if "HS09" in (hard_stops or []):
        komplettering.append("Källtäckning låg — inhämta ytterligare rättskällor")
    if "HS11" in (hard_stops or []):
        komplettering.append("Lagversion oklar — verifiera beslutsdatum mot lagskiftesregister")
    if "HS15" in (hard_stops or []):
        komplettering.append("Falsifikation VULNERABLE — bemöt identifierade svaga punkter")
    for rekv in (ej_styrkt_rekvisit or []):
        komplettering.append(f"Inhämta underlag för: {rekv}")
    return {
        "status": "GENOMFÖRD",
        "domän": domän,
        "antal_motargument": len(matchade),
        "motpartens_argumentation": matchade,
        "kompletteringsbehov": komplettering,
        "varning": "Motstrategisk analys är INDIKATIV. Juristen bedömer vilka argument som faktiskt åberopas av motparten.",
        "not": "SFCAE-kärnan orörd. Ingen bevisvärdering.",
    }


def run_motstrategi_if_requested(pipeline_state: Any = None, case_state: Any = None, requested: bool = False, domän: Optional[str] = None, extra_kontext: Optional[str] = None) -> Dict:
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "Motstrategi kräver explicit requested=True."}
    aktiv_domän = domän
    if not aktiv_domän and pipeline_state:
        aktiv_domän = getattr(pipeline_state, "domän", "") or ""
    if not aktiv_domän and case_state:
        aktiv_domän = getattr(case_state, "domän", "") or ""
    if not aktiv_domän:
        return {"status": "EJ_KÖRBAR", "skäl": "Domän saknas — ange domän explicit."}
    cs = copy.deepcopy(case_state) if case_state else None
    ej_styrkt = []
    if cs:
        for r in (getattr(cs, "requisites", []) or []):
            status = r.get("status", "") if isinstance(r, dict) else str(getattr(r, "status", ""))
            namn = r.get("name", "") if isinstance(r, dict) else str(getattr(r, "name", r))
            if "OTILL" in status or "EJ" in status or "OKLAR" in status:
                ej_styrkt.append(namn)
    # Steg 17: koderna läses som strängar (enum och sträng) via hard_stop_las;
    # kedjeavbrott ger EJ_KÖRBAR, VARJE annan aktiv HS spärrar output.
    from hard_stop_las import las_hard_stop_koder, kedjeavbrott, spärrsvar
    hard_stops = las_hard_stop_koder(pipeline_state, case_state)
    aktiva = kedjeavbrott(pipeline_state, case_state)
    if aktiva:
        return {"status": "EJ_KÖRBAR", "skäl": f"Kedje-abort aktiv: {aktiva}"}
    spärr = spärrsvar("motstrategi", pipeline_state, case_state)
    if spärr:
        return spärr
    return analysera_motstrategi(domän=aktiv_domän, ej_styrkt_rekvisit=ej_styrkt, hard_stops=hard_stops, extra_kontext=extra_kontext)
