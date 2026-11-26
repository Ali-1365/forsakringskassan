# -*- coding: utf-8 -*-
"""
Enkel rättstidskontroll mot config — utan RelationsGraph.
requested=True. Indikativ. Ingen lagversion-slutsats utan datum.
"""
from __future__ import annotations
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from konfig_kalla import ladda_konfig, Konfig

ROOT = Path(__file__).resolve().parent.parent


# Senaste utfallet av konfigurationsläsningen.
_KONFIG: Konfig = Konfig()


def _load_config() -> Dict:
    path = ROOT / "config" / "rattstid_config.yaml"
    global _KONFIG
    _KONFIG = ladda_konfig(path)
    return _KONFIG.data


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def bedöm_sol_version(beslutsdatum: Optional[str]) -> Dict:
    d = _parse_date(beslutsdatum)
    cfg = _load_config()
    regel = next((r for r in cfg.get("regler", []) if r.get("id") == "SOL_SKIFTE_2025"), None)
    if not regel:
        return {"status": "EJ_KONFIG", "label": "EJ_VERIFIERAT"}
    if d is None:
        return {
            "status": "SAKNAR_DATUM",
            "label": "EJ_VERIFIERAT",
            "regel": regel.get("regel"),
            "not": "Beslutsdatum krävs för SoL-version",
        }
    cut = _parse_date(regel.get("ikraftträdande"))
    if cut and d >= cut:
        version = regel.get("ny")
    else:
        version = regel.get("gammal")
    return {
        "status": "INDIKATIV",
        "beslutsdatum": d.isoformat(),
        "föreslagen_sol_version": version,
        "ikraftträdande": regel.get("ikraftträdande"),
        "label": "EJ_VERIFIERAT",
        "not": "Juristen verifierar övergångsbestämmelser",
    }


def bedöm_version(lag: str, beslutsdatum: Optional[str]) -> Dict:
    """Generisk lagversionsbedömning ur config/rattstid_config.yaml (regler
    per lag). Okänd lag ger EJ_KONFIG - ingen påhittad version."""
    cfg = _load_config()
    regel = next((r for r in cfg.get("regler", [])
                  if str(r.get("lag", "")).upper() == str(lag).upper()), None)
    if not regel:
        return {"status": "EJ_KONFIG", "label": "EJ_VERIFIERAT", "lag": lag,
                "kända_lagar": [r.get("lag") for r in cfg.get("regler", [])]}
    d = _parse_date(beslutsdatum)
    if d is None:
        return {"status": "SAKNAR_DATUM", "label": "EJ_VERIFIERAT", "lag": lag,
                "regel": regel.get("regel")}
    cut = _parse_date(regel.get("ikraftträdande"))
    if cut and d >= cut:
        version = regel.get("ny")
    else:
        version = regel.get("gammal") or f"före {regel.get('ny')} (äldre lydelse ej konfigurerad)"
    return {"status": "INDIKATIV", "lag": lag, "regel_id": regel.get("id"),
            "beslutsdatum": d.isoformat(), "föreslagen_version": version,
            "ikraftträdande": regel.get("ikraftträdande"), "label": "EJ_VERIFIERAT",
            "not": "Juristen verifierar övergångsbestämmelser"}


def run_rattstid_if_requested(
    requested: bool = False,
    beslutsdatum: Optional[str] = None,
    lag: str = "SoL",
) -> Dict:
    if not requested:
        return {"status": "EJ_BEGÄRD"}
    if lag.upper() in ("SOL", "SOL_SOCIALTJANST", "SOCIALTJANST"):
        return {"status": "GENOMFÖRD", "resultat": bedöm_sol_version(beslutsdatum)}
    res = bedöm_version(lag, beslutsdatum)
    return {"status": "GENOMFÖRD" if res["status"] != "EJ_KONFIG" else "EJ_KÖRBAR",
            "resultat": res}
