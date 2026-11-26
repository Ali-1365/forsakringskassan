from __future__ import annotations
# SFCAE-BINDNING: lvu_rekvisit_checklista
# Roll: LVU-rekvisitnedbrytning
# Alt B — anropas via requested=True från pipeline eller MCP.
# Producerar aldrig domslut. INDIKATIV_ENDAST.
_BUNDEN_TILL_SFCAE = True
_ROLL = "LVU-rekvisitnedbrytning"

# -*- coding: utf-8 -*-
"""
LVU-rekvisitchecklista — bryter ner LVU 2 §/3 § i deras faktiska
delrekvisit enligt lagtexten, samt proportionalitetsprövningens delmoment.

Detta är INTE en automatisk bedömning av om rekvisiten är uppfyllda.
Det är en STRUKTURERAD SÖNDERDELNING av vad lagtexten kräver ska visas —
motsvarande hur bevisstyrka_kalkylator.py bryter ner bevisvärdering utan
att själv avgöra om beviskravet är nått. Varje delrekvisit får status
PRÖVAT/EJ_PRÖVAT baserat på om motsvarande mönster hittats i
kör_rättsområdesskanning()s träffar — juristen avgör om det som hittats
faktiskt STYRKER delrekvisitet.

Källa: lagtexten i LVU (1990:52) 2 §, 3 § och 1 § femte stycket
(proportionalitet/frivillighetsprincipen). Ingen konstruerad tolkning.
"""
from typing import Any, Dict, List

# Delrekvisit direkt ur lagtexten — inte en juridisk tolkning av dem.
LVU_2_DELREKVISIT = [
    {
        "id": "LVU2-A",
        "text": "Brister i omsorgen om den unge, eller något annat förhållande i hemmet",
        "mönster": ["brister i omsorgen", "förhållande i hemmet", "hemmiljö"],
    },
    {
        "id": "LVU2-B",
        "text": "Föreligger påtaglig risk för att den unges hälsa eller utveckling skadas",
        "mönster": ["påtaglig risk", "skada på hälsa", "skada på utveckling"],
    },
]

LVU_3_DELREKVISIT = [
    {
        "id": "LVU3-A",
        "text": "Missbruk av beroendeframkallande medel, brottslig verksamhet eller "
                "annat socialt nedbrytande beteende — av den unge själv",
        "mönster": ["missbruk", "brottslig verksamhet", "socialt nedbrytande beteende"],
    },
    {
        "id": "LVU3-B",
        "text": "Föreligger påtaglig risk för att den unges hälsa eller utveckling skadas",
        "mönster": ["påtaglig risk", "skada på hälsa", "skada på utveckling"],
    },
]

PROPORTIONALITET_DELMOMENT = [
    {
        "id": "PROP-A",
        "text": "Frivilliga insatser enligt SoL har prövats eller bedömts otillräckliga "
                "(LVU 1 § femte stycket)",
        "mönster": ["frivillig insats", "samtycke till vård saknas",
                     "otillräcklig frivillig åtgärd", "vägrar samtycka"],
    },
    {
        "id": "PROP-B",
        "text": "Åtgärden är proportionerlig i förhållande till syftet "
                "(art. 8 EKMR, se även config/kodsystem_art8.yaml)",
        "mönster": ["mindre ingripande åtgärd", "proportionalitet", "proportionerlig"],
    },
    {
        "id": "PROP-C",
        "text": "Barnets egen inställning har inhämtats och redovisats "
                "(BK art. 12, LVU 1 § sjätte stycket)",
        "mönster": ["barnets inställning", "barnets vilja", "barnet hörts", "barnsamtal"],
    },
]


def _pröva_delrekvisit(text: str, delrekvisit: List[Dict]) -> List[Dict[str, Any]]:
    tl = (text or "").lower()
    resultat = []
    for d in delrekvisit:
        träffade = [m for m in d["mönster"] if m.lower() in tl]
        resultat.append({
            "id": d["id"],
            "delrekvisit": d["text"],
            "status": "PRÖVAT" if träffade else "EJ_PRÖVAT",
            "matchade_mönster": träffade,
            "not": (
                "Träff = mönstret nämns i texten. Avgör INTE om delrekvisitet "
                "är STYRKT — det kräver jurists bevisvärdering."
            ),
        })
    return resultat


def bryt_ner_lvu_rekvisit(text: str, paragraf: str = "2") -> Dict[str, Any]:
    """
    paragraf: '2' (miljöfall) eller '3' (beteendefall).
    """
    if not text or not str(text).strip():
        return {"status": "EJ_KÖRBAR", "skäl": "Tom text."}
    if paragraf not in ("2", "3"):
        return {"status": "EJ_KÖRBAR", "skäl": f"Okänd LVU-paragraf: '{paragraf}' (stöder '2' eller '3')"}

    huvudrekvisit = LVU_2_DELREKVISIT if paragraf == "2" else LVU_3_DELREKVISIT
    delrekvisit_resultat = _pröva_delrekvisit(text, huvudrekvisit)
    proportionalitet_resultat = _pröva_delrekvisit(text, PROPORTIONALITET_DELMOMENT)

    alla = delrekvisit_resultat + proportionalitet_resultat
    ej_prövade = [r for r in alla if r["status"] == "EJ_PRÖVAT"]

    return {
        "status": "GENOMFÖRD",
        "lagrum": f"LVU {paragraf} §",
        "delrekvisit": delrekvisit_resultat,
        "proportionalitet": proportionalitet_resultat,
        "antal_ej_prövade": len(ej_prövade),
        "ej_prövade_delrekvisit": [r["id"] for r in ej_prövade],
        "not": (
            "INDIKATIV_ENDAST — strukturerad nedbrytning av lagtextens "
            "delrekvisit, inte en automatisk bedömning. 'PRÖVAT' betyder "
            "att materialet BERÖR delrekvisitet, inte att det är styrkt. "
            "Proportionalitetsbedömningen kräver alltid juristens egen "
            "avvägning — den generas inte här."
        ),
    }


def run_lvu_rekvisit_if_requested(
    text: str = "", paragraf: str = "2", requested: bool = False
) -> Dict[str, Any]:
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "LVU-rekvisitchecklista kräver requested=True."}
    return bryt_ner_lvu_rekvisit(text, paragraf)
