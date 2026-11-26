# -*- coding: utf-8 -*-
"""Gemensam läsning av domänspärrar (hard stops) - en enda källa.

Användarbeslut steg 8: en domänspärr ger terminalt pipeline_state HARD_STOP.
Spärrar redovisas i hard_stop_codes / hard_stops / hard_stop_active /
pipeline_state och läses här.

Tidigare läste varje runner på sitt eget sätt: kodsystem_runner och
skuldkedja_runner läste bara .hard_stops (missade CaseState.hard_stop_codes
och platta dict), lojalitet_bridge jämförde HardStopCode-enum mot strängar
(träffade aldrig) - spärrar kunde alltså missas.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, List

# Koder som avbryter hela analyskedjan (samma mängd som runners använde).
CHAIN_ABORT = frozenset({"HS01A", "HS06", "HS09", "HS11", "HS_CANONICAL_MISSING", "HS_CANONICAL_ERROR"})

SPÄRRTEXT = (
    "Juridisk slutsats spärrad på grund av otillräckligt verifierat underlag. "
    "Systemet har identifierat ett obligatoriskt rekvisit där tillräcklig bevisning "
    "inte har kunnat verifieras. Den beroende juridiska slutsatsen har därför blockerats. "
    "Granska den angivna bevisluckan och bedöm om ytterligare relevant underlag behöver "
    "tillföras. Systemets status innebär inte i sig att domstolen kommer att avslå "
    "yrkandet. En ny bedömning ska göras när underlaget har kompletterats och verifierats."
)


def _koder_ur(obj: Any) -> Iterable[Any]:
    if obj is None:
        return []
    ut: List[Any] = []
    if isinstance(obj, dict):
        for k in ("hard_stop_codes", "hard_stops"):
            v = obj.get(k)
            if isinstance(v, (list, tuple)):
                ut.extend(v)
        for k in ("output", "case_state"):
            if isinstance(obj.get(k), dict):
                ut.extend(_koder_ur(obj[k]))
        return ut
    for k in ("hard_stop_codes", "hard_stops"):
        v = getattr(obj, k, None)
        if isinstance(v, (list, tuple)):
            ut.extend(v)
    for k in ("output", "case_state"):
        v = getattr(obj, k, None)
        if v is not None and v is not obj:
            ut.extend(_koder_ur(v))
    return ut


def las_hard_stop_koder(*objekt: Any) -> List[str]:
    """Alla spärrkoder ur CaseState, OrchestrationState, dict eller nästlad
    output, som strängar, i ordning och utan dubbletter."""
    sett, ut = set(), []
    for o in objekt:
        for c in _koder_ur(o):
            s = str(getattr(c, "value", c))
            if s and s not in sett:
                sett.add(s)
                ut.append(s)
    return ut


def spärr_aktiv(*objekt: Any) -> bool:
    if any(bool(getattr(o, "hard_stop_active", False)) or
           (isinstance(o, dict) and bool(o.get("hard_stop_active"))) or
           str(getattr(getattr(o, "pipeline_state", None), "value",
                       getattr(o, "pipeline_state", None) if not isinstance(o, dict)
                       else o.get("pipeline_state"))) == "HARD_STOP" for o in objekt):
        return True
    return bool(las_hard_stop_koder(*objekt))


def kedjeavbrott(*objekt: Any) -> List[str]:
    return [k for k in las_hard_stop_koder(*objekt) if k in CHAIN_ABORT]


def _v(x: Any) -> str:
    return str(getattr(x, "value", x)) if x not in (None, "") else "SAKNAS"


def spärrdetalj(case_state: Any) -> dict:
    """Datahärledd detalj till spärrtexten - inget påhittat, okänt = SAKNAS.

    * luckor: MUST-rekvisit med status BEVISNING_SAKNAS ur rekvisitmatrisen
    * kedjebrott: var och varför kedjan bröts (hard_stop_register)
    * kontrollerade_källor: endast handlingar som faktiskt kontrollerats
      (SHA-256 verifierad, ej karantän) före spärren
    * rekvisitmatris: bevarad oförändrad (slutsatskedjan stoppas, inte data)
    """
    matris = list(getattr(case_state, "requisite_matrix", None) or [])
    luckor = []
    for n, r in enumerate(matris, 1):
        if _v(getattr(r, "modal", None)) == "MUST" and _v(getattr(r, "status", None)) == "BEVISNING_SAKNAS":
            luckor.append({
                "rad": n,
                "rekvisit": getattr(r, "requisite_text", None) or "SAKNAS",
                "källa_lagrum": getattr(r, "source_ref", None) or "SAKNAS",
                "saknad_bevisning": (f"ingen verifierad bevisning kopplad (claim_id={getattr(r, 'claim_id', None) or 'SAKNAS'})"),
            })
            trunk = list(getattr(r, "uteslutna_trunkerade", None) or [])
            if trunk:
                # Steg 17: luckan anger att matchande bevisning var trunkerad.
                luckor[-1]["bevisning_trunkerad"] = trunk
                luckor[-1]["saknad_bevisning"] += (
                    f"; matchande claims {trunk} uteslutna: texten trunkerad och "
                    "datum-/versionsmetadata ej verifierad (B-011)")
    kedjebrott = []
    import hard_stop_register as _hsr
    for kod in las_hard_stop_koder(case_state):
        post = _hsr.hämta(kod)
        kedjebrott.append({
            "kod": kod,
            "beskrivning": getattr(post, "beskrivning", None) or "SAKNAS",
            "bruten_vid": getattr(post, "sätts_i", None) or "SAKNAS",
            "villkor": getattr(post, "villkor", None) or "SAKNAS",
            "räckvidd": getattr(post, "räckvidd", None) or "SAKNAS",
        })
    if not luckor and "HS11" in las_hard_stop_koder(case_state):
        # Steg 14b: HS11 beskrivs enbart av det saknade funktionella kravet.
        # Kan det inte härledas ur matrisen redovisas SAKNAS - aldrig en
        # förklaring om tom matris (den är ett separat kritiskt pipelinefel).
        luckor.append({"rad": "SAKNAS", "rekvisit": "SAKNAS", "källa_lagrum": "SAKNAS",
                       "saknad_bevisning": "SAKNAS"})
    filer = list(getattr(case_state, "files", None) or [])
    kontrollerade = [{
        "file_id": getattr(f, "file_id", "SAKNAS"),
        "fil": Path(str(getattr(f, "relative_path", "") or "")).name or "SAKNAS",
        "sha256": getattr(f, "hash_sha256", "SAKNAS"),
    } for f in filer if getattr(f, "hash_sha256", "KAN EJ VERIFIERAS") != "KAN EJ VERIFIERAS"
        and not getattr(f, "quarantine_flag", False)]
    return {
        "luckor": luckor,
        "kedjebrott": kedjebrott,
        "kontrollerade_källor": kontrollerade,
        "karantän_antal": sum(1 for f in filer if getattr(f, "quarantine_flag", False)),
        "ej_verifierbara_antal": sum(1 for f in filer if getattr(f, "hash_sha256", "") == "KAN EJ VERIFIERAS"),
        "rekvisitmatris_bevarad": len(matris),
        "nästa_steg": ("Tillför och verifiera bevisning för de angivna luckorna. "
                       "Kör därefter om analysen."),
    }


def spärrpayload(*objekt: Any) -> dict:
    """Presentationsblock vid aktiv spärr (tom dict annars)."""
    koder = las_hard_stop_koder(*objekt)
    if not spärr_aktiv(*objekt):
        return {}
    ut = {"juridisk_spärr": True, "spärrkoder": koder, "spärrtext": SPÄRRTEXT}
    cs = next((o for o in objekt if o is not None and hasattr(o, "requisite_matrix")
               and not isinstance(o, dict)), None)
    if cs is not None:
        ut["spärrdetalj"] = spärrdetalj(cs)
    return ut


def spärrsvar(modul: str, *objekt: Any) -> dict:
    """Gemensamt svar för runners vid aktiv domänspärr (tom dict annars).

    Runnern producerar då ingen ny analys; spärrkoder, spärrtext och
    datahärledd detalj redovisas i stället (steg 8)."""
    if not (las_hard_stop_koder(*objekt) or spärr_aktiv(*objekt)):
        return {}
    ut = {"status": "OUTPUT_SPÄRRAD", "modul": modul,
          "skäl": "Domänspärr aktiv - ingen ny analys producerad"}
    ut.update(spärrpayload(*objekt) or {"juridisk_spärr": True,
              "spärrkoder": las_hard_stop_koder(*objekt), "spärrtext": SPÄRRTEXT})
    return ut
