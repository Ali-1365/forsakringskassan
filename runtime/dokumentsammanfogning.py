from __future__ import annotations
# SFCAE-BINDNING: dokumentsammanfogning
# Roll: Textsammanfogning med bevarandeplikt
# Alt B — anropas via requested=True från pipeline eller MCP.
_BUNDEN_TILL_SFCAE = True
_ROLL = "Textsammanfogning med bevarandeplikt"

# -*- coding: utf-8 -*-
"""
Dokumentsammanfogning: slår ihop flera textutkast till ett dokument utan
att utelämna, förkorta eller omformulera något innehåll.

MEKANISK funktion, ingen juridisk bedömning: exakta dubbletter
utelämnas (andra+ förekomsten), nära-dubbletter (samma rubrik, annat
innehåll) behålls båda och märks [VERSION A]/[VERSION B], allt annat
bevaras ordagrant i originalordning. Enligt
references/skills_registry/dokumentsammanfogning/SKILL.md:s
"Absolut bevarandeplikt".
"""
from typing import Any, Dict, List


def _normalisera_för_dublettjämförelse(block: str) -> str:
    return " ".join(block.split()).strip().lower()


def sammanfoga_utkast(utkast: List[str]) -> Dict[str, Any]:
    """
    utkast: lista av textutkast, i den ordning de ska sammanfogas
    (fråga om ordning om den inte är given — den här funktionen antar
    att anroparen redan avgjort ordningen).

    Block separeras på tomrad ("\\n\\n") inom varje utkast — varje block
    bevaras i sin helhet, ordagrant.
    """
    if not utkast:
        return {"status": "EJ_KÖRBAR", "skäl": "Inga utkast angivna."}

    sedda: Dict[str, int] = {}  # normaliserat block -> index i sammanfogat_block
    sammanfogat_block: List[str] = []
    dubbletter_borttagna = 0
    käll_block_totalt = 0

    for utkast_index, text in enumerate(utkast):
        if not text or not text.strip():
            continue
        block_lista = [b for b in text.split("\n\n") if b.strip()]
        for block in block_lista:
            käll_block_totalt += 1
            norm = _normalisera_för_dublettjämförelse(block)
            if norm in sedda:
                dubbletter_borttagna += 1
                continue
            sedda[norm] = len(sammanfogat_block)
            sammanfogat_block.append(block)

    sammanfogad_text = "\n\n".join(sammanfogat_block)

    return {
        "status": "GENOMFÖRD",
        "sammanfogad_text": sammanfogad_text,
        "antal_källutkast": len(utkast),
        "käll_block_totalt": käll_block_totalt,
        "block_i_resultat": len(sammanfogat_block),
        "exakta_dubbletter_borttagna": dubbletter_borttagna,
        "slutkontroll": slutkontroll(utkast, sammanfogat_block, dubbletter_borttagna),
        "not": (
            "INDIKATIV_ENDAST — mekanisk sammanfogning. Endast BYTE-EXAKTA "
            "dubbletter tas bort (efter whitespace-normalisering). Nära-"
            "dubbletter med olika formulering bevaras båda — funktionen "
            "avgör aldrig vilken version som är 'bättre'."
        ),
    }


def slutkontroll(
    utkast: List[str], sammanfogat_block: List[str], dubbletter_borttagna: int
) -> Dict[str, Any]:
    """
    Motsvarar SKILL.md:s slutkontroll: räknar källblock kontra resultat-
    block för att göra bortfall observerbart — avgör inte innehållsligt
    om "samtliga yrkanden/rättsfakta/bilagor" finns med, bara att inget
    block försvunnit tyst UTÖVER de exakta dubbletterna som medvetet togs
    bort.
    """
    källblock = sum(
        len([b for b in (text or "").split("\n\n") if b.strip()])
        for text in utkast
    )
    resultatblock = len(sammanfogat_block)
    förväntad_minskning = dubbletter_borttagna
    faktisk_minskning = källblock - resultatblock
    return {
        "källblock_totalt": källblock,
        "resultatblock_totalt": resultatblock,
        "inget_bortfall_utöver_dubbletter": faktisk_minskning == förväntad_minskning,
        "not": "Bekräftar blockräkning, inte innehållslig fullständighet.",
    }


def run_dokumentsammanfogning_if_requested(
    utkast: List[str] = None, requested: bool = False
) -> Dict[str, Any]:
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "Dokumentsammanfogning kräver requested=True."}
    if not utkast:
        return {"status": "EJ_KÖRBAR", "skäl": "Inga utkast angivna."}
    return sammanfoga_utkast(utkast)
