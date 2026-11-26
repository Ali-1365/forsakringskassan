from __future__ import annotations
# SFCAE-BINDNING: positionsforskjutning
# Roll: Positionsförskjutning över tidsordnade skriftväxlingar
# Alt B — anropas via requested=True från pipeline eller MCP.
_BUNDEN_TILL_SFCAE = True
_ROLL = "Positionsförskjutning över tidsordnade skriftväxlingar"

# -*- coding: utf-8 -*-
"""
Positionsförskjutning: jämför en parts ställningstaganden över flera
TIDSORDNADE skriftväxlingar och flaggar när ett ämne som nämndes i en
tidigare text INTE längre nämns i en senare — en möjlig indikation på
att grunden bytts eller tonats ned. Motsvarar ai-motstrategi/SKILL.md,
metod 3 ("Dynamisk asymmetrisk attack" — den del som handlar om att
"identifiera argumentationsförskjutningar... exponera skiftet explicit
inför domstolen").

Detta är källkritik av en parts EGNA, redan inlämnade handlingar över
tid — samma princip som JOURNAL-MOTSAGELSE redan tillämpar inom ett
enda dokument, bara mellan flera dokument i tidsordning. Det är INTE:
- en förutsägelse av vad motparten KOMMER att skriva (byggs inte),
- ett förslag på hur AI-genererat innehåll kan döljas (byggs aldrig).

Ämnen identifieras via enkla, konfigurerbara nyckelordsgrupper —
fabricerar aldrig en motsägelse som inte finns i källtexterna.
"""
import re
from typing import Any, Dict, List, Optional

_NEGATION_MÖNSTER = re.compile(r'\binte\s+([a-zåäö]+(?:\s+[a-zåäö]+){0,4})', re.I)


def _möjlig_motsägelse(tidigare_text: str, nuvarande_text: str) -> List[Dict[str, Any]]:
    """Flaggar fraser som nämndes bekräftande i ett tidigare dokument och
    förekommer negerade ('inte <fras>') i ett senare — en direkt
    polaritetsomkastning på SAMMA påstående, skilt från att ett ämne
    tyst slutar nämnas (se möjliga_positionsförskjutningar)."""
    t_low = (tidigare_text or "").lower()
    n_low = (nuvarande_text or "").lower()
    träffar = []
    for m in _NEGATION_MÖNSTER.finditer(n_low):
        fras = m.group(1).strip()
        if fras and fras in t_low and f"inte {fras}" not in t_low:
            träffar.append({
                "fras": fras,
                "bekräftades_utan_negation_i_tidigare_dokument": True,
            })
    return träffar

# Generella ämnesgrupper. Ett ämne "nämns" om NÅGOT ord i gruppen
# förekommer i texten. Utökningsbar utan kodändring vore nästa steg
# (config-driven), men hålls här som en liten, transparent startlista
# tills ett verkligt användningsfall visar vilka ämnesgrupper som
# faktiskt behövs.
_STANDARDÄMNEN: Dict[str, List[str]] = {
    "proportionalitet": ["proportionalitet", "proportionerlig", "mindre ingripande åtgärd"],
    "orsakssamband": ["orsakssamband", "kausalitet", "adekvat kausalitet"],
    "handlaggningstid": ["handläggningstid", "dröjsmål", "4-månadersfristen"],
    "medicinsk_bevisning": ["läkarintyg", "specialistutlåtande", "diagnos"],
    "barnets_installning": ["barnets inställning", "barnets vilja", "barnsamtal"],
}


def _nämnda_ämnen(text: str, ämnesgrupper: Dict[str, List[str]]) -> Dict[str, List[str]]:
    tl = (text or "").lower()
    resultat: Dict[str, List[str]] = {}
    for ämne, ord in ämnesgrupper.items():
        träffar = [o for o in ord if o.lower() in tl]
        if träffar:
            resultat[ämne] = träffar
    return resultat


def analysera_positionsförskjutning(
    tidsordnade_texter: List[Dict[str, str]],
    ämnesgrupper: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """
    tidsordnade_texter: [{"datum": "YYYY-MM-DD", "text": "..."}], i
    KRONOLOGISK ordning (äldst först) — anroparen ansvarar för ordningen,
    funktionen sorterar inte om.
    """
    if not tidsordnade_texter or len(tidsordnade_texter) < 2:
        return {
            "status": "EJ_KÖRBAR",
            "skäl": "Kräver minst två tidsordnade texter för att jämföra positioner.",
        }

    grupper = ämnesgrupper or _STANDARDÄMNEN
    per_dokument = [
        {
            "datum": d.get("datum", "SAKNAS"),
            "index": i,
            "nämnda_ämnen": _nämnda_ämnen(d.get("text", ""), grupper),
        }
        for i, d in enumerate(tidsordnade_texter)
    ]

    förskjutningar = []
    motsägelser = []
    for i in range(1, len(per_dokument)):
        tidigare = per_dokument[i - 1]
        nuvarande = per_dokument[i]
        försvunna_ämnen = set(tidigare["nämnda_ämnen"]) - set(nuvarande["nämnda_ämnen"])
        for ämne in försvunna_ämnen:
            förskjutningar.append({
                "ämne": ämne,
                "nämndes_i_dokument": tidigare["index"],
                "nämndes_datum": tidigare["datum"],
                "saknas_i_dokument": nuvarande["index"],
                "saknas_datum": nuvarande["datum"],
                "matchade_ord_i_tidigare_dokument": tidigare["nämnda_ämnen"][ämne],
            })
        for fras in _möjlig_motsägelse(
            tidsordnade_texter[i - 1].get("text", ""), tidsordnade_texter[i].get("text", "")
        ):
            motsägelser.append({
                **fras,
                "bekräftades_i_dokument": tidigare["index"],
                "bekräftades_datum": tidigare["datum"],
                "negeras_i_dokument": nuvarande["index"],
                "negeras_datum": nuvarande["datum"],
            })

    return {
        "status": "GENOMFÖRD",
        "antal_dokument": len(tidsordnade_texter),
        "per_dokument": per_dokument,
        "möjliga_positionsförskjutningar": förskjutningar,
        "möjliga_motsägelser": motsägelser,
        "not": (
            "INDIKATIV_ENDAST. Ett ämne som slutar nämnas KAN betyda att "
            "grunden bytts eller tonats ned — det kan också bero på att "
            "frågan är löst, ostridig, eller irrelevant i den senare "
            "skriftväxlingen. Juristen avgör vilken förklaring som "
            "stämmer. Detta genererar aldrig en slutsats om att motparten "
            "'bytt grund'."
        ),
    }


def run_positionsforskjutning_if_requested(
    tidsordnade_texter: List[Dict[str, str]] = None, requested: bool = False
) -> Dict[str, Any]:
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "Positionsförskjutningsanalys kräver requested=True."}
    if not tidsordnade_texter:
        return {"status": "EJ_KÖRBAR", "skäl": "Inga texter angivna."}
    return analysera_positionsförskjutning(tidsordnade_texter)
