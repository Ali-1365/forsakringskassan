# -*- coding: utf-8 -*-
"""
Konversationsscanner — analyserar taltranskriberingar för taktiska mönster.
Migrerad från archive/robust_mahoor_system.py (analysera_konversation_robust).
INDIKATIV_ENDAST. Ingen bevisvärdering, inget domslut.
"""
from __future__ import annotations
import re
from typing import Any, Dict, List, Optional


def _hel_ord(fras: str) -> "re.Pattern[str]":
    """Helordsmatchning som i arkivoriginalet (\\b...\\b): "eh" ska inte
    träffa inuti "behöver", "det" inte inuti "detalj" (steg 25)."""
    return re.compile(r"(?<!\w)" + re.escape(fras) + r"(?!\w)")


def _hitta(lower: str, fras: str) -> Optional[int]:
    m = _hel_ord(fras).search(lower)
    return m.start() if m else None


def _load_konversation_rules() -> List[Dict[str, Any]]:
    try:
        from config_loader import ladda
        cfg = ladda("kodsystem_konversation") or {}
        return cfg.get("koder") or []
    except Exception:
        return []


def _default_rules() -> List[Dict[str, Any]]:
    return [
        {
            "kod": "TVEKAN",
            "mönster": ["eh", "hm", "jag vet inte", "kanske", "möjligen", "typ", "liksom"],
            "validering": ["jag", "vi", "man", "det", "den"],
            "negativa_filter": [],
            "beskrivning": "Uttryck för osäkerhet",
            "indikation": "TROVÄRDIGHET_SVAG",
        },
        {
            "kod": "BEKRÄFTELSE",
            "mönster": ["jag medger", "det stämmer", "absolut", "precis", "exakt", "håller med"],
            "validering": ["det", "jag", "vi", "påstående"],
            "negativa_filter": [],
            "beskrivning": "Positiv bekräftelse",
            "indikation": "ERKÄNNANDE_INDIKATION",
        },
        {
            "kod": "AGGRESSIV_TON",
            "mönster": ["du ljuger", "det är lögn", "hur vågar du", "fullständigt orimligt"],
            "validering": ["du", "motpart", "tvist", "konflikt"],
            "negativa_filter": ["inte ljuger", "talar sanning"],
            "beskrivning": "Konfrontativ ton",
            "indikation": "TON_KONTROLL",
        },
    ]


def skanna_konversation(text: str) -> Dict[str, Any]:
    if not (text or "").strip():
        return {"status": "EJ_KÖRBAR", "skäl": "Tom text", "träffar": []}

    regler = _load_konversation_rules() or _default_rules()
    lower = text.lower()
    träffar: List[Dict[str, Any]] = []

    for regel in regler:
        mönster = [str(m).lower() for m in (regel.get("mönster") or [])]
        validering = [str(v).lower() for v in (regel.get("validering") or [])]
        negativa = [str(n).lower() for n in (regel.get("negativa_filter") or [])]

        matchade = []
        for m in mönster:
            idx = _hitta(lower, m)
            if idx is None:
                continue
            # Kontextfönster 200 tecken
            kontext_start = max(0, idx - 100)
            kontext_slut = min(len(text), idx + len(m) + 100)
            kontext = lower[kontext_start:kontext_slut]

            # Dubbel-validering: valideringsord måste finnas i kontext
            if validering and not any(_hel_ord(v).search(kontext) for v in validering):
                continue
            # Negativt filter: om negativt ord finns → skip
            if any(_hel_ord(n).search(kontext) for n in negativa):
                continue
            matchade.append(m)

        if matchade:
            träffar.append({
                "kod": regel.get("kod", "OKÄND"),
                "matchade_mönster": matchade,
                "beskrivning": regel.get("beskrivning", ""),
                "indikation": regel.get("indikation", ""),
                "status": "INDIKATIV_ENDAST",
                "not": "Konversationsanalys är indikativ — kräver källkedja i AUDIT.",
            })

    return {
        "status": "GENOMFÖRD",
        "antal_träffar": len(träffar),
        "träffar": träffar,
        "not": "Träff är indikativ — ingen bevisvärdering eller juridisk slutsats.",
    }


def run_konversation_scan_if_requested(text: str = "", requested: bool = False) -> Dict[str, Any]:
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "Konversationsskanning kräver requested=True."}
    return skanna_konversation(text)
