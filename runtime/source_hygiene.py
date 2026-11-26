"""
SOURCE_HYGIENE — NEW_CODE från historisk specifikation (legal_ai_core_config.md §7,
ursprung v3.0.0 "KÄLLHYGIEN med trust-nivåer och karantän").

trust_levels (high/medium/low/quarantine) tagna ORÄNDRADA från config §7.
Klassificering sker per källtypsmönster i filnamn/innehållssignal. Karantänklassade
källor flaggas för manuell granskning (config: manual_review: true) — de styr EJ
hard stops (det är ingestionens integritetskontroll som gör det).

STATUS: POST-HISTORISK NYIMPLEMENTATION (SPEC_ONLY → implementerad från config).
"""
from __future__ import annotations
import re
from typing import Any, Dict, List

TRUST_LEVELS = {
    "high": ["SFS", "HD_avgöranden", "HFD_avgöranden", "Propositioner", "SOU"],
    "medium": ["HovR_avgöranden", "KR_avgöranden", "JO_beslut", "JK_beslut",
               "Myndighetsföreskrifter"],
    "low": ["Kommentarer", "Artiklar", "Bloggposter"],
    "quarantine": ["Okänd_källa", "Manipulated", "Incomplete"],
}

# Mönster → källtyp (deterministisk mappning till configens källtypsnamn)
PATTERNS = [
    (re.compile(r"\bsfs\b|förordningssamling", re.I), "SFS"),
    (re.compile(r"\bhd\b|högsta domstolen", re.I), "HD_avgöranden"),
    (re.compile(r"\bhfd\b|högsta förvaltningsdomstolen", re.I), "HFD_avgöranden"),
    (re.compile(r"proposition", re.I), "Propositioner"),
    (re.compile(r"\bsou\b|offentliga utredningar", re.I), "SOU"),
    (re.compile(r"hovrät", re.I), "HovR_avgöranden"),
    (re.compile(r"kammarrät", re.I), "KR_avgöranden"),
    (re.compile(r"\bjo[-_ ]?beslut|justitieombudsmannen", re.I), "JO_beslut"),
    (re.compile(r"\bjk[-_ ]?beslut|justitiekanslern", re.I), "JK_beslut"),
    (re.compile(r"myndighetsföreskrift|föreskrift", re.I), "Myndighetsföreskrifter"),
    (re.compile(r"kommentar", re.I), "Kommentarer"),
    (re.compile(r"artikel|tidskrift", re.I), "Artiklar"),
    (re.compile(r"blogg", re.I), "Bloggposter"),
]


def classify_source_type(text: str) -> str:
    for pat, typ in PATTERNS:
        if pat.search(text or ""):
            return typ
    return "Okänd_källa"


def trust_of(source_type: str) -> str:
    for level, types in TRUST_LEVELS.items():
        if source_type in types:
            return level
    return "quarantine"


def assess(records: List[Any]) -> Dict:
    """Klassificerar ingesta filer enligt config §7-trustnivåer."""
    results = []
    counts = {"high": 0, "medium": 0, "low": 0, "quarantine": 0}
    for r in records:
        def value(name: str, *aliases: str) -> Any:
            if isinstance(r, dict):
                return next((r[key] for key in (name, *aliases) if r.get(key)), "")
            return next((getattr(r, key, "") for key in (name, *aliases)
                         if getattr(r, key, "")), "")

        filename = value("filename", "name", "filnamn")
        relative_path = value("relative_path", "path", "sökväg")
        blob = " ".join(str(x) for x in (filename, relative_path))
        typ = classify_source_type(blob)
        level = trust_of(typ)
        counts[level] += 1
        results.append({"file_id": value("file_id"), "filename": filename,
                        "källtyp": typ, "trust": level})
    return {
        "status": "GENOMFÖRD",
        "antal": len(results),
        "counts": counts,
        "klassificering": results,
        "manual_review_flaggade": [x for x in results if x["trust"] == "quarantine"],
        "källa": "legal_ai_core_config.md §7 (ursprung v3.0.0) — NEW_CODE från spec",
    }
