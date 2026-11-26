from __future__ import annotations
# SFCAE-BINDNING: skadestand_rekvisit
# Roll: SkL 3:2-rekvisitnedbrytning
# Alt B — anropas via requested=True från pipeline eller MCP.
_BUNDEN_TILL_SFCAE = True
_ROLL = "SkL 3:2-rekvisitnedbrytning"

# -*- coding: utf-8 -*-
"""
Skadeståndsrekvisit (SkL 3 kap. 2 §) — bryter ner de fyra rekvisiten för
kommuns/statens skadeståndsansvar vid myndighetsutövning i sina
delrekvisit, enligt
references/skills_registry/skadestand-process/SKILL.md STEG 1.

Samma princip som lvu_rekvisit_checklista.py: STRUKTURERAD
SÖNDERDELNING, ingen automatisk bedömning av om rekvisiten är uppfyllda.

Den ekonomiska beräkningen (STEG 2 i källan) byggs INTE här med de
praxisintervall källan anger (t.ex. "20 000-100 000 kr" för kränkning)
— dessa är ospecificerade praxisintervall utan verifierbar källa i
detta system, och att hårdkoda dem som SFCAE-"sanning" vore att
fabricera auktoritet de inte har. Endast den rena ekonomiska formeln
(period × norm - inkomst, med dröjsmålsränta som separat, ej
sammanslagen post) tillhandahålls, byggd på samma sätt som
riksnorm_berakning.py.
"""
from typing import Any, Dict, List

SKL_DELREKVISIT = [
    {
        "id": "SKL-A",
        "text": "Myndighetsutövning föreligger (beslut, faktisk handläggning, eller underlåtenhet att agera)",
        "mönster": ["myndighetsutövning", "beslut om bistånd", "LVU-beslut", "underlåtenhet att agera"],
    },
    {
        "id": "SKL-B",
        "text": "Fel eller försummelse (formellt fel, materiellt fel, underlåtenhet, "
                "proportionalitetsfel, eller diskriminering)",
        "mönster": ["formellt fel", "materiellt fel", "dröjsmål", "oproportionerlig åtgärd",
                     "diskriminering", "vårdslöshet", "försumlighet"],
    },
    {
        "id": "SKL-C",
        "text": "Skada föreligger (ekonomisk och/eller ideell)",
        "mönster": ["ekonomisk skada", "ideell skada", "sakskada", "personskada",
                     "kränkning", "lidande"],
    },
    {
        "id": "SKL-D",
        "text": "Orsakssamband (adekvat kausalitet) mellan felet och skadan",
        "mönster": ["orsakssamband", "adekvat kausalitet", "utan felet hade",
                     "medvållande"],
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
            "not": "Träff = mönstret nämns i texten. Avgör INTE om delrekvisitet är styrkt.",
        })
    return resultat


def bryt_ner_skadestand_rekvisit(text: str) -> Dict[str, Any]:
    if not text or not str(text).strip():
        return {"status": "EJ_KÖRBAR", "skäl": "Tom text."}
    delrekvisit = _pröva_delrekvisit(text, SKL_DELREKVISIT)
    ej_prövade = [r for r in delrekvisit if r["status"] == "EJ_PRÖVAT"]
    return {
        "status": "GENOMFÖRD",
        "lagrum": "SkL 3 kap. 2 §",
        "delrekvisit": delrekvisit,
        "antal_ej_prövade": len(ej_prövade),
        "ej_prövade_delrekvisit": [r["id"] for r in ej_prövade],
        "not": (
            "INDIKATIV_ENDAST — samtliga fyra rekvisit krävs enligt SkL 3:2. "
            "'PRÖVAT' betyder att materialet berör delrekvisitet, inte att "
            "det är styrkt. Skadeberäkning (belopp) görs inte här — se "
            "separat, källkontrollerad beräkning vid behov."
        ),
    }


def beräkna_ekonomisk_skada(
    period_månader: int,
    norm_per_månad: float,
    faktiska_inkomster: float = 0.0,
) -> Dict[str, Any]:
    """
    Ren ekonomisk-skadeformel enligt SKILL.md STEG 2A:
    totalt behov (norm × månader) - inkomster = ekonomisk skada.
    Dröjsmålsränta beräknas INTE här (kräver referensränta vid
    respektive förfallodag, en tidsberoende extern faktor) — redovisas
    som separat post att komplettera.
    """
    if period_månader < 0 or norm_per_månad < 0:
        return {"status": "EJ_KÖRBAR", "skäl": "Negativa värden är inte giltiga."}
    totalt_behov = norm_per_månad * period_månader
    ekonomisk_skada = totalt_behov - faktiska_inkomster
    return {
        "status": "GENOMFÖRD",
        "totalt_behov": round(totalt_behov, 2),
        "faktiska_inkomster": round(faktiska_inkomster, 2),
        "ekonomisk_skada": round(ekonomisk_skada, 2),
        "dröjsmålsränta": "EJ_BERÄKNAD — kräver referensränta per förfallodag (räntelagen 6 §)",
        "not": "INDIKATIV_ENDAST — ideell skada och dröjsmålsränta ingår inte i detta belopp.",
    }


def run_skadestand_rekvisit_if_requested(text: str = "", requested: bool = False) -> Dict[str, Any]:
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "Skadeståndsrekvisit kräver requested=True."}
    return bryt_ner_skadestand_rekvisit(text)
