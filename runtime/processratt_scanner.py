# -*- coding: utf-8 -*-
"""Processrättslig granskning. INDIKATIV_ENDAST. requested=True."""
from __future__ import annotations
from typing import Any, Dict, List
import sys

_KONTROLLPUNKTER = {
    "FL_KOMMUNIKATION": {
        "lagrum": "FL 25 §",
        "beskrivning": "Myndighet ska kommunicera innan beslut fattas",
        "triggers": ["utan att ge tillfälle", "inte fått yttra sig", "ej kommunicerat", "ingen remiss", "inte fått ta del av", "kommunikationsskyldighet"],
        "brist_indikation": "FL_25_KOMMUNIKATIONSBRIST",
        "allvarlighet": "HÖG",
    },
    "FL_UTREDNING": {
        "lagrum": "FL 23 §",
        "beskrivning": "Myndighet har utredningsskyldighet",
        "triggers": ["bristfällig utredning", "inte utrett", "saknar underlag", "ingen utredning", "utan att undersöka", "utredningsskyldighet"],
        "brist_indikation": "FL_23_UTREDNINGSBRIST",
        "allvarlighet": "HÖG",
    },
    "FL_MOTIVERING": {
        "lagrum": "FL 32-33 §§",
        "beskrivning": "Beslut ska motiveras",
        "triggers": ["omotiverat", "utan motivering", "saknar skäl", "inte motiverat", "ingen förklaring"],
        "brist_indikation": "FL_32_MOTIVERINGSBRIST",
        "allvarlighet": "MEDEL",
    },
    "FL_JAV": {
        "lagrum": "FL 16 §",
        "beskrivning": "Jäv hos beslutsfattaren diskvalificerar handläggningen",
        "triggers": ["jäv förelåg", "jävig", "jävsituation", "jävig handläggare", "delikatessjäv", "ombudsjäv"],
        "brist_indikation": "FL_16_JAV",
        "allvarlighet": "HÖG",
    },
    "EKMR_ART6": {
        "lagrum": "EKMR Art. 6",
        "beskrivning": "Rätt till rättvis rättegång",
        "triggers": ["inte fått möjlighet", "hindrad från", "rättvis rättegång", "art 6", "artikel 6", "access to court"],
        "brist_indikation": "EKMR_ART6_RATTVIS_RATTEGANG",
        "allvarlighet": "HÖG",
    },
    "EKMR_ART8": {
        "lagrum": "EKMR Art. 8",
        "beskrivning": "Rätt till privat- och familjeliv",
        "triggers": ["familjeliv", "privatliv", "art 8", "artikel 8", "proportionalitet", "nödvändigt i demokratiskt samhälle"],
        "brist_indikation": "EKMR_ART8_FAMILJELIV",
        "allvarlighet": "HÖG",
    },
    "PRESKRIPTION": {
        "lagrum": "PreskL 2 §",
        "beskrivning": "Preskriptionskontroll",
        "triggers": ["preskription", "preskriberad", "för sent", "tio år", "3 år", "preskriptionstid"],
        "brist_indikation": "PRESKRIPTION_KONTROLL",
        "allvarlighet": "HÖG",
    },
    "PROPORTIONALITET": {
        "lagrum": "RF 2 kap. 21 §, EKMR Art. 8",
        "beskrivning": "Proportionalitetsprincipen",
        "triggers": ["oproportionerlig", "inte proportionerlig", "alltför ingripande", "proportionalitet", "minst ingripande", "lindrigare åtgärd"],
        "brist_indikation": "PROPORTIONALITETSBRIST",
        "allvarlighet": "HÖG",
    },
    "BARNETS_RATT": {
        "lagrum": "BK Art. 12, LVU 36 §",
        "beskrivning": "Barnets rätt att höras",
        "triggers": ["barnets röst", "höra barnet", "barnets vilja", "art 12", "artikel 12", "barnsamtal", "barnet inte hörts", "barns rätt"],
        "brist_indikation": "BARNETS_RATT_HORAS",
        "allvarlighet": "HÖG",
    },
}

_ÅTGÄRD = {
    "FL_KOMMUNIKATION": ["Kontrollera om kommunikation faktiskt skett", "Granska om undantag från kommunikationsplikten åberopats", "Åberopa FL 25 § som grund i överklagandet"],
    "FL_UTREDNING": ["Identifiera vilka uppgifter som saknades", "Visa att myndigheten borde ha inhämtat uppgifterna", "Åberopa FL 23 § och officialprincipen"],
    "FL_MOTIVERING": ["Kontrollera om beslutet innehåller skäl", "Åberopa FL 32-33 §§ om motivering saknas"],
    "FL_JAV": ["Utred jävsgrunden (delikatess-, ombuds- eller släktskapsjäv)", "Åberopa FL 16 § och begär ny handläggning"],
    "EKMR_ART6": ["Granska om rättegången uppfyller art. 6-kraven", "Kontrollera domstolstillgång och opartiskhet"],
    "EKMR_ART8": ["Tillämpa trestegsprövningen: lagstöd → syfte → proportionalitet", "Visa att ingreppet inte är nödvändigt i demokratiskt samhälle"],
    "PRESKRIPTION": ["Fastställ preskriptionstidpunkten", "Kontrollera om preskriptionsavbrott skett"],
    "PROPORTIONALITET": ["Visa att lindrigare åtgärd hade räckt", "Tillämpa proportionalitetsprincipen systematiskt"],
    "BARNETS_RATT": ["Kontrollera om barnsamtal genomförts", "Åberopa BK art. 12 och LVU 36 §", "Granska om barnets åsikt beaktats i beslutet"],
}


def skanna_processratt(text: str) -> Dict:
    if not text or not text.strip():
        return {"status": "EJ_KÖRBAR", "skäl": "Tom text."}
    text_norm = text.lower()
    brister = []
    for kod, punkt in _KONTROLLPUNKTER.items():
        matchade = [t for t in punkt["triggers"] if t.lower() in text_norm]
        if not matchade:
            continue
        brister.append({
            "kod": kod,
            "lagrum": punkt["lagrum"],
            "beskrivning": punkt["beskrivning"],
            "brist_indikation": punkt["brist_indikation"],
            "allvarlighet": punkt["allvarlighet"],
            "matchade_triggers": matchade,
            "åtgärdsförslag": _ÅTGÄRD.get(kod, ["Juristen bedömer lämplig åtgärd"]),
            "not": "INDIKATIV_ENDAST — juristen verifierar",
        })
    brister.sort(key=lambda x: 0 if x["allvarlighet"] == "HÖG" else 1)
    if not brister:
        return {"status": "INGEN_TRÄFF", "brister": [], "not": "Inga processrättsliga brister identifierade."}
    return {
        "status": "GENOMFÖRD",
        "antal_brister": len(brister),
        "höga_brister": sum(1 for b in brister if b["allvarlighet"] == "HÖG"),
        "brister": brister,
        "not": "INDIKATIV_ENDAST — juristen bedömer relevans och styrka.",
    }


def load_procedure_protocols() -> Dict[str, str]:
    """Laddar och läser procedure-protokoll från knowledge base."""
    from knowledge_loader import search_knowledge, get_knowledge
    procedures = search_knowledge("procedures", by="category")
    if procedures:
        protocol_contents = {}
        for proc in procedures:
            content = get_knowledge(proc.relative_path)
            if content:
                protocol_contents[proc.filename] = content

        print(f"[PROCESSRATT_SCANNER] Read {len(protocol_contents)}/{len(procedures)} procedure protocols", file=sys.stderr)
        return protocol_contents
    return {}


def run_processratt_if_requested(text: str = "", pipeline_state: Any = None, requested: bool = False) -> Dict:
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "Processrättsskanner kräver explicit requested=True."}
    if not text and pipeline_state:
        claims = getattr(pipeline_state, "claims", []) or []
        delar = []
        for c in claims:
            if isinstance(c, dict):
                delar.append(str(c.get("content") or c.get("text") or ""))
            elif isinstance(c, str):
                delar.append(c)
            else:
                delar.append(str(getattr(c, "content", "") or getattr(c, "text", "") or ""))
        text = " ".join(filter(None, delar))
    if not text:
        return {"status": "EJ_KÖRBAR", "skäl": "Ingen text att skanna."}
    return skanna_processratt(text)
