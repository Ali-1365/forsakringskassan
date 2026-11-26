# -*- coding: utf-8 -*-
"""
Lojalitetsbrygga: strukturerar advokatens partsperspektiv.
ERSÄTTER INTE domarnivån. LÄSER från CaseState (deepcopy).
Producerar aldrig automatisk "maximal ersättning".
Kräver requested=True + explicit juristbeslut per sektion.
"""
from __future__ import annotations
import copy
from typing import Any, Dict, List, Optional
import sys as _sys_hs
from pathlib import Path as _Path_hs
if str(_Path_hs(__file__).resolve().parent.parent / "runtime") not in _sys_hs.path:
    _sys_hs.path.insert(0, str(_Path_hs(__file__).resolve().parent.parent / "runtime"))
from hard_stop_las import las_hard_stop_koder, kedjeavbrott  # noqa: E402


def run_lojalitet_if_requested(
    case_state: Any,
    pipeline_state: Any,
    requested: bool = False,
    klient_mål: Optional[List[str]] = None,
    ersättningstyper: Optional[List[str]] = None,
    perspektiv: str = "KLAGANDE",
) -> Dict:
    """
    Analyserar ärendet ur klientens perspektiv.
    Producerar aldrig automatiska ersättningsbelopp eller domslut.
    """
    if not requested:
        return {
            "status": "EJ_BEGÄRD",
            "detail": "Lojalitetsbrygga kräver explicit requested=True.",
        }

    cs = copy.deepcopy(case_state) if case_state else None

    # Tidigare jämfördes HardStopCode-enum mot strängar - träffade aldrig.
    hs = las_hard_stop_koder(cs)
    aktiva = kedjeavbrott(cs)
    if aktiva:
        return {
            "status": "EJ_KÖRBAR",
            "skäl": f"Kedje-abort aktiv: {aktiva}",
        }

    rekvisit = getattr(cs, "requisites", []) or [] if cs else []
    styrkt = []
    ej_styrkt = []
    for r in rekvisit:
        status = (
            r.get("status", "") if isinstance(r, dict)
            else str(getattr(r, "status", ""))
        )
        namn = (
            r.get("name", "") if isinstance(r, dict)
            else str(getattr(r, "name", r))
        )
        if "STYRKT" in status.upper() and "EJ" not in status.upper() and "OTILL" not in status.upper():
            styrkt.append(namn)
        elif "COVERED" in status.upper() or "UPPFYLLT" in status.upper():
            styrkt.append(namn)
        else:
            ej_styrkt.append(namn)

    luckor = list(getattr(cs, "gap_list", []) or []) if cs else []

    styrkor = []
    for s in styrkt:
        styrkor.append({
            "rekvisit": s,
            "rekommendation": f"Åberopa aktivt: '{s}' är styrkt per SFCAE-analys.",
            "prioritet": "HÖG",
        })

    svagheter = []
    for e in ej_styrkt:
        svagheter.append({
            "rekvisit": e,
            "rekommendation": f"Inhämta underlag för '{e}' eller justera yrkandet.",
            "prioritet": "HÖG",
        })

    ersättningsanalys = []
    if ersättningstyper:
        for et in ersättningstyper:
            ersättningsanalys.append({
                "typ": et,
                "status": "KRÄVER_JURISTBEDÖMNING",
                "not": (
                    "Belopp anges av juristen. "
                    "Systemet anger aldrig ersättningssiffror."
                ),
            })

    målanalys = []
    if klient_mål:
        for mål in klient_mål:
            uppnåeligt = any(mål.lower() in str(s).lower() for s in styrkt)
            målanalys.append({
                "mål": mål,
                "bedömning": (
                    "MÖJLIGT — styrkt underlag finns"
                    if uppnåeligt else
                    "OSÄKERT — komplettering behövs"
                ),
                "not": "INDIKATIV_ENDAST — juristen fattar beslut",
            })

    return {
        "status": "GENOMFÖRD",
        "provisorisk": True,
        "perspektiv": perspektiv,
        "märkning": "PROVISORISK — LOJALITETSANALYS | Juristen godkänner",
        "styrkor": styrkor,
        "svagheter": svagheter,
        "kompletteringsbehov": [
            {"lucka": str(lucka), "åtgärd": "Inhämta och åberopa"}
            for lucka in luckor
        ],
        "ersättningsanalys": ersättningsanalys,
        "målanalys": målanalys,
        "varning": (
            "Lojalitetsbryggan ersätter inte SFCAE-domarnivån. "
            "Domarnivåns bedömning är oförändrad. "
            "Juristen ansvarar för alla beslut."
        ),
        "not": "SFCAE-kärnan orörd. CaseState ändras aldrig.",
    }
