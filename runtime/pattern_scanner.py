# -*- coding: utf-8 -*-
"""
Mönsterbibliotek v2 — skannar text mot pattern_rules_v2.yaml.
INDIKATIV_ENDAST. Ingen bevisvärdering, inget domslut.
"""
from __future__ import annotations
from typing import Any, Dict, List
import re


def _load_rules() -> Dict[str, Any]:
    try:
        from config_loader import ladda
        return ladda("pattern_rules_v2") or {}
    except Exception:
        return {}


def skanna_monster(text: str) -> Dict[str, Any]:
    if not (text or "").strip():
        return {"status": "EJ_KÖRBAR", "skäl": "Tom text", "träffar": []}
    cfg = _load_rules()
    rules = cfg.get("rules") or []
    neg = [str(x).lower() for x in (cfg.get("negation_words") or [])]
    lower = text.lower()
    hits: List[Dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rid = rule.get("rule_id") or ""
        kws = rule.get("keywords") or []
        matched = []
        for kw in kws:
            k = str(kw).lower()
            if k not in lower:
                continue
            # enkel negation: "inte X" inom 40 tecken före
            idx = lower.find(k)
            window = lower[max(0, idx - 40) : idx]
            if any(n in window for n in neg):
                continue
            matched.append(kw)
        if matched:
            hits.append({
                "rule_id": rid,
                "title": rule.get("title"),
                "matched_keywords": matched,
                "legal_refs": rule.get("legal_refs") or [],
                "responsibility": rule.get("responsibility") or [],
                "status": "INDIKATIV_ENDAST",
                "potential": bool(rule.get("potential_default", True)),
            })
    return {
        "status": "GENOMFÖRD",
        "antal_träffar": len(hits),
        "träffar": hits,
        "not": "Träff är indikativ — ingen bevisvärdering eller juridisk slutsats.",
    }


def run_pattern_scan_if_requested(text: str = "", requested: bool = False) -> Dict[str, Any]:
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "Pattern scan kräver requested=True."}
    return skanna_monster(text)
