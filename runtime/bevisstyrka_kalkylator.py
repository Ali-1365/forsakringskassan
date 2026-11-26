# -*- coding: utf-8 -*-
"""Bevisstyrkekalkylator. INDIKATIV_ENDAST. requested=True. Aldrig domslut."""
from __future__ import annotations
from typing import Any, Dict, List, Optional

BEVISVÄRDE = {
    "A_STARK": 1.0, "B_STÖD": 0.6, "C_BAKGRUND": 0.3,
    "D_DUBBLETT": 0.0, "E_IRRELEVANT": 0.0, "F_OTILLÅTEN": 0.0,
}
BEVISKRAV = {"STYRKT": 0.75, "SANNOLIKT": 0.50, "ANTAGLIGT": 0.25, "PÅSTÅTT": 0.10}
DOMÄN_BEVISKRAV = {
    "FK_SFB": "SANNOLIKT", "SOL_LVU": "SANNOLIKT",
    "RB_TVIST": "STYRKT", "KL_KONKURS": "STYRKT", "LVU_TVÅNG": "STYRKT",
}


# Domän -> sektion i config/evidence_standards.yaml (evidence_standards).
_STANDARD_SEKTION = {
    "SOL_LVU": ("förvaltning_FPL", "LVU"), "SOL_SOCIALTJANST": ("förvaltning_FPL", None),
    "LVU_TVÅNG": ("förvaltning_FPL", "LVU"), "FK_SFB": ("förvaltning_FPL", "socialförsäkring"),
    "FPL_FORVALTNING": ("förvaltning_FPL", None), "RB_TVIST": ("tvistemål_dispositivt_RB", None),
    "KL_KONKURS": ("tvistemål_dispositivt_RB", None), "JB_HYRESRATT": ("tvistemål_dispositivt_RB", None),
}


def rättslig_standard(domän: str) -> Dict[str, Any]:
    """Läser beviskrav och principer ur config/evidence_standards.yaml.
    Filen förbjuder numerisk/procentuell poängsättning (P10) och hårdkodad
    bevisbörda (FIX-U); det redovisas i varje resultat."""
    try:
        import config_loader as _cl
        cfg = _cl.evidence_standards() or {}
    except Exception as e:
        return {"status": "EJ_LÄST", "skäl": f"{type(e).__name__}: {e}"}
    if not cfg:
        return {"status": "EJ_LÄST", "skäl": "evidence_standards.yaml tom eller saknas"}
    principer = cfg.get("core_principles") or {}
    sek, mål = _STANDARD_SEKTION.get(str(domän).upper(), (None, None))
    std = (cfg.get("evidence_standards") or {}).get(sek or "", {}) if sek else {}
    standard = std.get("standard")
    if mål and isinstance(std.get("per_måltyp"), dict):
        standard = std["per_måltyp"].get(mål) or standard
    return {
        "status": "LÄST" if sek else "DOMÄN_SAKNAR_MAPPNING",
        "sektion": sek, "standard": standard, "källa": std.get("källa"),
        "numerisk_poäng_förbjuden": bool(principer.get("numeric_scoring_forbidden")),
        "fri_bevisprövning": principer.get("free_evidence_assessment"),
    }


def beräkna_bevisstyrka(rekvisit: str, bevis: List[Dict], domän: str = "SOL_LVU") -> Dict:
    res = _beräkna_bevisstyrka_tal(rekvisit, bevis, domän)
    std = rättslig_standard(domän)
    res["rättslig_standard"] = std
    if std.get("numerisk_poäng_förbjuden"):
        # Talvärdena är hjälpvärden. Uppfylldhet avgörs av juristen mot den
        # rättsliga standarden - inte av en tröskel (evidence_standards P10).
        res["beviskrav_uppfyllt_bindande"] = False
        res["not"] = ("INDIKATIV_ENDAST. evidence_standards.yaml förbjuder numerisk "
                      "poängsättning: talvärden och beviskrav_uppfyllt är hjälpvärden. "
                      f"Rättslig standard: {std.get('standard')} ({std.get('källa')}).")
    return res


def _beräkna_bevisstyrka_tal(rekvisit: str, bevis: List[Dict], domän: str = "SOL_LVU") -> Dict:
    if not bevis:
        return {
            "rekvisit": rekvisit, "total_styrka": 0.0,
            "beviskrav": DOMÄN_BEVISKRAV.get(domän, "SANNOLIKT"),
            "beviskrav_tröskelvärde": BEVISKRAV.get(DOMÄN_BEVISKRAV.get(domän, "SANNOLIKT"), 0.5),
            "beviskrav_uppfyllt": False, "bevis_antal": 0, "bevis_per_kategori": {},
            "gap_lista": [f"Inga bevis åberopade för '{rekvisit}'"],
            "not": "INDIKATIV_ENDAST — juristen bedömer",
        }
    per_kat = {}
    poäng_lista = []
    for b in bevis:
        kat = b.get("kategori", "E_IRRELEVANT")
        per_kat[kat] = per_kat.get(kat, 0) + 1
        poäng_lista.append(BEVISVÄRDE.get(kat, 0.0))
    raw = sum(poäng_lista) / len(poäng_lista)
    a_stark_antal = per_kat.get("A_STARK", 0)
    bonus = min(0.15, a_stark_antal * 0.05)
    total = min(1.0, raw + bonus)
    krav_kod = DOMÄN_BEVISKRAV.get(domän, "SANNOLIKT")
    krav_tröskel = BEVISKRAV.get(krav_kod, 0.5)
    uppfyllt = total >= krav_tröskel
    gap = []
    if not uppfyllt:
        saknat = krav_tröskel - total
        gap.append(f"Bevisstyrka {total:.2f} < krav {krav_tröskel:.2f} ({krav_kod}). Komplettera med {saknat:.2f} enheter starkare bevisning.")
    if per_kat.get("F_OTILLÅTEN", 0) > 0:
        gap.append("Otillåten bevisning identifierad — ta bort eller ersätt")
    if per_kat.get("D_DUBBLETT", 0) > 0:
        gap.append(f"{per_kat['D_DUBBLETT']} dubbletter — rensa")
    return {
        "rekvisit": rekvisit, "total_styrka": round(total, 3),
        "beviskrav": krav_kod, "beviskrav_tröskelvärde": krav_tröskel,
        "beviskrav_uppfyllt": uppfyllt, "bevis_antal": len(bevis),
        "bevis_per_kategori": per_kat, "gap_lista": gap,
        "not": "INDIKATIV_ENDAST. Bevisstyrkevärden är matematiska hjälpmedel. Juristen bedömer alltid om bevisningen är tillräcklig.",
    }


def run_bevisstyrka_if_requested(rekvisit_lista: Optional[List[Dict]] = None, pipeline_state: Any = None, requested: bool = False, domän: str = "SOL_LVU") -> Dict:
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "Bevisstyrkekalkylator kräver explicit requested=True."}
    if not rekvisit_lista and pipeline_state:
        rekv = getattr(pipeline_state, "rekvisit", []) or []
        filer = getattr(pipeline_state, "files", []) or []
        rekvisit_lista = [{
            "rekvisit": r,
            "bevis": [{"kategori": getattr(f, "kategori", "C_BAKGRUND"), "beskrivning": getattr(f, "filnamn", ""), "källa": getattr(f, "sökväg", "")} for f in filer],
        } for r in rekv]
    if not rekvisit_lista:
        return {"status": "EJ_KÖRBAR", "skäl": "Ingen rekvisit-lista angiven."}
    resultat = [beräkna_bevisstyrka(post.get("rekvisit", "OKÄNT"), post.get("bevis", []), domän) for post in rekvisit_lista]
    uppfyllda = sum(1 for r in resultat if r["beviskrav_uppfyllt"])
    totalt = len(resultat)
    return {
        "status": "GENOMFÖRD", "domän": domän, "rekvisit_totalt": totalt,
        "rekvisit_uppfyllda": uppfyllda, "rekvisit_ej_uppfyllda": totalt - uppfyllda,
        "täckningsgrad": round(uppfyllda / totalt, 3) if totalt else 0.0,
        "resultat": resultat,
        "not": "INDIKATIV_ENDAST — juristen beslutar om tillräcklig bevisning.",
    }
