# -*- coding: utf-8 -*-
"""
Ersättningsscanner: identifierar ersättningstyp och lagrum ur text.
Returnerar ALDRIG belopp eller domslut.
Returnerar: ersättningstyp, lagrum, beräkningsgrunder (platshållare).
Juristen fyller i alla belopp.
Kräver requested=True.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional

from konfig_kalla import ladda_konfig, Konfig

ROOT = Path(__file__).resolve().parent.parent


# Senaste utfallet av konfigurationsläsningen.
_KONFIG: Konfig = Konfig()


def _ladda_config() -> List[Dict]:
    """
    Ersättningstyper ur config. Tre skilda utfall gav tidigare samma tomma
    lista utan förklaring: pyyaml saknades, filen saknades, eller den gick
    inte att tolka. Skannern svarade då som om inga ersättningstyper fanns
    definierade.
    """
    global _KONFIG
    _KONFIG = ladda_konfig(ROOT / "config" / "ersattning_config.yaml")
    return list(_KONFIG.data.get("ersättningstyper") or [])


_MÖNSTER = {
    "LIVRÄNTA": [
        "livränta", "inkomstbortfall", "arbetsskada",
        "arbetsolycka", "förvärvsoförmåga",
    ],
    "PATIENTSKADA_LOF": [
        "patientskada", "löf", "lof", "vårdskada",
        "medicinsk felbehandling", "crps",
    ],
    "SKADESTAND_SKL": [
        "skadestånd", "skl 3", "ren förmögenhetsskada",
        "myndighetsutövning", "kränkningsersättning",
    ],
    "CRPS_INVALIDITET": [
        "crps", "budapest", "komplex regionalt smärtsyndrom",
        "nervskada", "invaliditetsgrad",
    ],
    "JK_ANSPRAK": [
        "jk", "justitiekanslern", "statens ansvar",
        "felaktig myndighetsutövning", "anspråk mot staten",
    ],
}


def skanna_ersättningstyp(text: str) -> Dict:
    """Identifierar ersättningstyp ur text. Returnerar aldrig belopp."""
    if not text or not text.strip():
        return {
            "status": "EJ_KÖRBAR",
            "skäl": "Tom text.",
        }

    config = _ladda_config()
    text_norm = text.lower()
    träffar = []

    for erstyp, mönsterlista in _MÖNSTER.items():
        matchade = [m for m in mönsterlista if m in text_norm]
        if not matchade:
            continue

        cfg_post = next(
            (c for c in config if c.get("kod") == erstyp), {}
        )
        träffar.append({
            "kod": erstyp,
            "lagrum": cfg_post.get("lagrum", ""),
            "beräkningsgrunder": cfg_post.get("beräkningsgrunder", []),
            "matchade_mönster": matchade,
            "not": "INDIKATIV_ENDAST — juristen anger alla belopp",
        })

    if not träffar:
        return {
            "status": "INGEN_TRÄFF",
            "träffar": [],
            "not": "Ingen ersättningstyp identifierad i texten.",
        }

    return {
        "status": "GENOMFÖRD",
        "träffar": träffar,
        "antal": len(träffar),
        "varning": (
            "Belopp och procentsatser är ALDRIG automatiska. "
            "Juristen anger och verifierar alla siffror."
        ),
        "not": "INDIKATIV_ENDAST",
    }


def run_ersattning_if_requested(
    text: str,
    requested: bool = False,
) -> Dict:
    """Valfri ersättningsscanner. Kräver requested=True."""
    if not requested:
        return {
            "status": "EJ_BEGÄRD",
            "detail": "Ersättningsscanner kräver explicit requested=True.",
        }
    return skanna_ersättningstyp(text)
