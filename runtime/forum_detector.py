"""
FORUM_DETECTOR + REKVISIT-MODAL-DSL — Konsoliderad implementation.

Realiserar den funktionella substansen i `legal_ai_core_config.md`
(fristående specifikation → exekverbar kod) som en del av den
konsoliderade arkitekturen. Faktisk bas hämtad från config:
  - forum_detector: SIGNALER (FPL/RB/KL/SFB), tröskel 0.55,
    on_conflict=FORUM_CONFLICT, fallback=null.
  - requisites: modal_markers → DSL (MUST/ALT/EXC/IF/WHEN),
    utvärderingsregler (must_all_true, alt_groups_any, exception_overrides,
    condition_gates, temporal_sequence).
  - quality_thresholds + case_law-ranks är enbart policy (ej maskin-tvingat här)
    men exponeras som datastrukturer för nedströms motorer.

VERIFIERAT: forum_signaler och modal_markers kopierade från config.
EJ VERIFIERBART: extern praxis-ranking mot live-källproduktion (kräver nätverk).
"""

from __future__ import annotations
import re
import unicodedata
from typing import Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# FORUM-SIGNALER — kopierade från legal_ai_core_config.md (avsnitt 2)
# ─────────────────────────────────────────────────────────────────────────────
FORUM_SIGNALS: Dict[str, Dict] = {
    "FPL": {
        "entities": [
            "Försäkringskassan", "Förvaltningsrätten", "Kammarrätten",
            "Högsta förvaltningsdomstolen", "HFD", "Skatteverket",
            "Migrationsverket",
        ],
        "terms": [
            "omprövning", "SFB", "FPL", "förvaltningsbeslut", "överklagande",
            "sociala avgifter",
        ],
        "weight": 0.6,
    },
    "RB": {
        "entities": [
            "Tingsrätten", "Hovrätten", "Högsta domstolen", "HD", "kronofogden",
        ],
        "terms": [
            "RB 42 kap", "stämningsansökan", "rättegångskostnader 18 kap",
            "talan", "civilrättslig", "skadestånd",
        ],
        "weight": 0.6,
    },
    "KL": {
        "entities": [
            "konkursförvaltare", "tillsynsmyndigheten", "gäldenär", "borgenär",
        ],
        "terms": [
            "bouppteckning", "förvaltarberättelse", "avskrivning", "konkurs",
            "ackordsförslag",
        ],
        "weight": 0.6,
    },
    "SFB": {
        "entities": ["Försäkringskassan", "FK"],
        "terms": [
            "sjukpenning", "aktivitetsersättning", "sjukersättning", "SFB",
            "socialförsäkring",
        ],
        "weight": 0.6,
    },
}

THRESHOLD: float = 0.55
ON_CONFLICT: str = "FORUM_CONFLICT"
FALLBACK: Optional[str] = None  # "Ingen fallback - fel är fel"


def _har_signal(signal: str, low: str) -> bool:
    """Helordsträff: "HD"/"FK"/"talan" får inte träffa inuti andra ord
    (samma delsträngsfelklass som "dom" i "sjukdom")."""
    s = unicodedata.normalize("NFC", signal).lower()
    return re.search(r"(?<!\w)" + re.escape(s) + r"(?!\w)", low) is not None


def forum_match_score(forum: str, entities: List[str], terms: List[str],
                      weight: float, text: str) -> float:
    low = unicodedata.normalize("NFC", text).lower()
    score = 0.0
    for ent in entities:
        if _har_signal(ent, low):
            score += weight
    for term in terms:
        if _har_signal(term, low):
            score += weight
    return score


def detect_forum(text: str) -> Dict:
    """Tvingad, regelstyrd forumklassning med hårt stopp. (config avsnitt 2)"""
    scores = {
        forum: forum_match_score(forum, s["entities"], s["terms"], s["weight"], text)
        for forum, s in FORUM_SIGNALS.items()
    }
    best = max(scores, key=scores.get)
    best_score = scores[best]
    over = sorted((f for f, s in scores.items() if s >= THRESHOLD), key=lambda f: -scores[f])

    if not over:
        return {
            "forum": None,
            "status": "EJ KLASSIFICERAD",
            "scores": scores,
            "on_conflict_rule": ON_CONFLICT,
        }
    if len(over) > 1:
        return {
            "forum": None,
            "status": ON_CONFLICT,  # Hårt stopp vid tvetydighet
            "scores": scores,
            "leading": over,
        }
    return {
        "forum": over[0],
        "status": "KLASSIFICERAD",
        "score": best_score,
        "scores": scores,
    }
# __PART_BOUNDARY__
# ─────────────────────────────────────────────────────────────────────────────
# REKVISIT-MODAL-DSL — kopierad från legal_ai_core_config.md (avsnitt 3)
# ─────────────────────────────────────────────────────────────────────────────
MODAL_MARKERS: Dict[str, List[str]] = {
    "must": ["ska", "måste", "får inte", "förbjudet", "krävs"],
    "alt": ["eller", "alternativt", "antingen", "å ena sidan"],
    "exception": ["undantag", "dock", "trots att", "om inte", "såvida inte"],
    "condition": ["endast om", "förutsatt att", "under förutsättning"],
    "temporal": ["förrän", "inte utan att", "först när", "sedan"],
}
DSL_MAPPING = {"must": "MUST", "alt": "ALT", "exception": "EXC",
               "condition": "IF", "temporal": "WHEN"}


def classify_modal(requisite_text: str) -> str:
    low = requisite_text.lower()
    for cat, markers in MODAL_MARKERS.items():
        for m in markers:
            if m in low:
                return DSL_MAPPING[cat]
    return "MUST"  # default hårdaste bindande tolkning i konfig-läge


class RequisiteEvaluator:
    """
    Symbolisk evaluering per config-avsnitt 3 'evaluation':
      must_all_true, alt_groups_any, exception_overrides,
      condition_gates, temporal_sequence.
    """

    def __init__(self) -> None:
        self.must_all_true = True
        self.alt_groups_any = True
        self.exception_overrides = True
        self.condition_gates = True
        self.temporal_sequence = True

    def evaluate(self, nodes: List[Dict]) -> Dict:
        """nodes: [{id, modal: MUST/ALT/EXC/IF/WHEN, satisfied: bool}]"""
        overrides = [n for n in nodes if n["modal"] == "EXC" and n["satisfied"]]
        if self.exception_overrides and overrides:
            return {"verdict": "EXCEPTION_OVERRIDES", "reason": [n["id"] for n in overrides]}

        conditional = [n for n in nodes if n["modal"] == "IF"]
        if self.condition_gates and any(not n["satisfied"] for n in conditional):
            return {"verdict": "CONDITION_GATE_BLOCKED", "reason": "IF-villkor ej uppfyllt"}

        must = [n for n in nodes if n["modal"] == "MUST"]
        if self.must_all_true and must and not all(n["satisfied"] for n in must):
            return {"verdict": "MUST_NOT_ALL_TRUE",
                    "reason": [n["id"] for n in must if not n["satisfied"]]}

        alt_groups = [n for n in nodes if n["modal"] == "ALT"]
        if self.alt_groups_any and alt_groups and any(n["satisfied"] for n in alt_groups):
            return {"verdict": "ALT_SATISFIED", "reason": [n["id"] for n in alt_groups if n["satisfied"]]}

        return {"verdict": "OPEN", "reason": []}


if __name__ == "__main__":
    # Snabb självtest
    r = detect_forum("Försäkringskassan har beslutat om sjukpenning och omprövning begärs")
    print("FORUM:", r["status"], r.get("forum"), {k: round(v, 2) for k, v in r["scores"].items()})
    print("MODAL:", classify_modal("Bidrag lämnas endast om inkomst understiger gränsen"))