from __future__ import annotations
# SFCAE-BINDNING: kvalitetskontroll
# Roll: Slutkontroll före leverans
# Körs automatiskt sist i run_pipeline(), efter bristrapport.
# Producerar aldrig domslut. INDIKATIV_ENDAST — juristen fattar leveransbeslutet.
_BUNDEN_TILL_SFCAE = True
_ROLL = "Slutkontroll före leverans"

# -*- coding: utf-8 -*-
"""
Kvalitetskontroll: obligatorisk slutkontroll innan leverans av
processkrift. Prövar redan beräknade fält mot ett fast antal interna
konsistenskrav — skapar ingen ny juridisk bedömning, avgör inte om
innehållet är korrekt, bara om pipelinens EGNA resultat är internt
konsekventa och fullständiga.
"""
from typing import Any, Dict, List


def _kontroll_hard_stop_konsistens(case_state) -> Dict[str, Any]:
    aktiv = bool(getattr(case_state, "hard_stop_active", False))
    koder = getattr(case_state, "hard_stop_codes", None) or []
    ok = aktiv == bool(koder)
    return {
        "kontrollpunkt": "HARD_STOP_KONSISTENS",
        "godkänd": ok,
        "detalj": (
            "hard_stop_active och hard_stop_codes överensstämmer" if ok else
            f"hard_stop_active={aktiv} men hard_stop_codes={[c.value if hasattr(c,'value') else c for c in koder]}"
        ),
    }


def _kontroll_kritiska_brister(case_state) -> Dict[str, Any]:
    meta = getattr(case_state, "metadata", None)
    if not isinstance(meta, dict):
        meta = getattr(case_state, "case_meta", None) or {}
    rapport = (meta or {}).get("bristrapport") or {}
    kritiska = [
        b for b in rapport.get("brister", [])
        if b.get("risknivå") == "KRITISK"
    ]
    return {
        "kontrollpunkt": "INGA_OLÖSTA_KRITISKA_BRISTER",
        "godkänd": not kritiska,
        "detalj": (
            "Inga KRITISK-brister i bristrapporten" if not kritiska else
            f"{len(kritiska)} KRITISK-brister kvarstår: "
            f"{[b['kod'] for b in kritiska]}"
        ),
    }


def _kontroll_verdict_konsistens(case_state) -> Dict[str, Any]:
    from forensic_engine_v10_3_canonical import AuditStatus, AuditControllerVerdict

    overall = getattr(case_state, "overall_status", None)
    verdict = getattr(case_state, "audit_controller_verdict", None)
    inkonsekvent = (
        verdict == AuditControllerVerdict.GODKÄND
        and overall == AuditStatus.H
    )
    return {
        "kontrollpunkt": "VERDICT_KONSISTENS",
        "godkänd": not inkonsekvent,
        "detalj": (
            "overall_status och audit_controller_verdict är konsekventa"
            if not inkonsekvent else
            "audit_controller_verdict=GODKÄND men overall_status=H "
            "(KAN INTE AVGÖRAS) — motsägelsefullt utfall"
        ),
    }


def _kontroll_falsifiering_genomförd(case_state) -> Dict[str, Any]:
    from forensic_engine_v10_3_canonical import FalsificationVerdict, PipelineState

    genomförd = getattr(case_state, "pipeline_state", None) == PipelineState.COMPLETE
    ej_körd = getattr(case_state, "falsification_verdict", None) == FalsificationVerdict.NOT_RUN
    # COMPLETE + NOT_RUN under domänspärr är ett korrekt, samstämt tillstånd
    # (tillståndsseparation) - ingen inflationsvarning.
    spärr = bool(getattr(case_state, "hard_stop_codes", None)) or bool(
        getattr(case_state, "hard_stop_active", False))
    # Steg 8: spärr ger pipeline_state HARD_STOP; COMPLETE + NOT_RUN är alltid fel.
    problem = genomförd and ej_körd
    return {
        "kontrollpunkt": "FALSIFIERING_FÖRSÖKT",
        "godkänd": not problem,
        "detalj": (
            ("NOT_RUN under domänspärr - korrekt, ingen slutsats fabricerad"
             if (spärr and ej_körd and not genomförd) else "Falsifieringsförsök genomfört") if not problem else
            "Pipeline markerad COMPLETE men falsification_verdict=NOT_RUN"
        ),
    }


def _kontroll_fullständiga_steg(case_state) -> Dict[str, Any]:
    from forensic_engine_v10_3_canonical import ej_genomförda_steg

    luckor = ej_genomförda_steg(case_state)
    return {
        "kontrollpunkt": "INGA_OFÖRKLARADE_LUCKOR",
        "godkänd": True,  # EJ_KÖRBAR-steg är ett korrekt, redovisat utfall — blockerar inte
        "detalj": (
            "Inga ofullständiga steg" if not luckor else
            f"{len(luckor)} steg redovisade som ej genomförda (se bristrapport): "
            f"{[s.get('steg') for s in luckor]}"
        ),
    }


def kör_kvalitetskontroll(case_state) -> Dict[str, Any]:
    """
    Kör samtliga slutkontroller. Returnerar GODKÄND endast om alla
    blockerande kontrollpunkter (hard-stop-konsistens, kritiska brister,
    verdict-konsistens, falsifiering) är godkända. INGA_OFÖRKLARADE_LUCKOR
    är alltid rapporterande, aldrig blockerande — ett redovisat
    EJ_KÖRBAR-steg är ett korrekt utfall, inte ett leveranshinder i sig.
    """
    kontroller: List[Dict[str, Any]] = [
        _kontroll_hard_stop_konsistens(case_state),
        _kontroll_kritiska_brister(case_state),
        _kontroll_verdict_konsistens(case_state),
        _kontroll_falsifiering_genomförd(case_state),
        _kontroll_fullständiga_steg(case_state),
    ]
    blockerande = [k for k in kontroller if not k["godkänd"] and k["kontrollpunkt"] != "INGA_OFÖRKLARADE_LUCKOR"]

    return {
        "status": "GODKÄND" if not blockerande else "EJ_GODKÄND",
        "case_id": getattr(case_state, "case_id", ""),
        "kontroller": kontroller,
        "blockerande_kontrollpunkter": [k["kontrollpunkt"] for k in blockerande],
        "not": (
            "INDIKATIV_ENDAST — prövar pipelinens EGNA interna konsistens och "
            "fullständighet, inte innehållets juridiska korrekthet. "
            "Leveransbeslutet fattas av juristen."
        ),
    }


def run_kvalitetskontroll_if_requested(case_state=None, requested: bool = False) -> Dict[str, Any]:
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "Kvalitetskontroll kräver requested=True."}
    if case_state is None:
        return {"status": "EJ_KÖRBAR", "skäl": "Inget case_state angivet."}
    return kör_kvalitetskontroll(case_state)

