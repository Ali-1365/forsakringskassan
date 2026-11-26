# -*- coding: utf-8 -*-
"""
Kodsystem-scanner: mönster mot config-tabell.
Träff = sökhjälp. Inga slutsatser. Inga poäng som bevisvärde.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

try:
    import yaml
    _YAML_OK = True
except ImportError:
    _YAML_OK = False

ROOT = Path(__file__).resolve().parent.parent


def _ladda_kodtabell(yaml_path: Path) -> Optional[Dict]:
    if not _YAML_OK or not yaml_path.is_file():
        return None
    try:
        with yaml_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def _normalisera(text: str) -> str:
    return text.lower().strip()


def _matchar_mönster(text_norm: str, mönster: List[str]) -> List[str]:
    träffar = []
    for m in mönster:
        if _normalisera(m) in text_norm:
            träffar.append(m)
    return träffar


def _matchar_negativt(text_norm: str, negativa: List[str]) -> bool:
    for n in negativa or []:
        if _normalisera(n) in text_norm:
            return True
    return False


def _extrahera_kontext(text: str, mönster: str, fönster: int = 80) -> str:
    pos = text.lower().find(mönster.lower())
    if pos == -1:
        return ""
    start = max(0, pos - fönster)
    slut = min(len(text), pos + len(mönster) + fönster)
    utdrag = text[start:slut].strip()
    return f"…{utdrag}…" if start > 0 or slut < len(text) else utdrag


def skanna_text(
    text: str,
    kodtabell_path: Optional[str] = None,
    domän: str = "RB_TVIST",
) -> Dict:
    if not text or not str(text).strip():
        return {"status": "EJ_KÖRBAR", "skäl": "Tom text — inget att skanna."}

    if kodtabell_path:
        path = Path(kodtabell_path)
    else:
        # Steg 16: tabellen löses ur domänen via config-registret (meta.domän /
        # filstam) - aldrig tyst en annan domäns tabell.
        try:
            from config_loader import kodsystem_sökväg
            rel = kodsystem_sökväg(domän)
        except ImportError as exc:
            return {"status": "EJ_KÖRBAR", "domän": domän,
                    "skäl": f"config_loader ej tillgänglig: {exc}"}
        if not rel:
            return {"status": "EJ_KÖRBAR", "domän": domän,
                    "skäl": f"Ingen kodtabell i config/ för domän {domän}"}
        path = ROOT / rel
    tabell = _ladda_kodtabell(path)
    if tabell is None:
        return {
            "status": "EJ_KÖRBAR",
            "skäl": f"Kodtabell kunde inte laddas: {path}",
        }

    koder = tabell.get("koder", []) if isinstance(tabell, dict) else []
    if not koder:
        return {
            "status": "EJ_KÖRBAR",
            "domän": domän,
            "skäl": f"Kodtabellen saknar koder: {path}",
        }
    meta = tabell.get("meta", {})
    text_norm = _normalisera(text)
    träffar = []

    for post in koder:
        positiva = _matchar_mönster(text_norm, post.get("mönster", []))
        if not positiva:
            continue
        if _matchar_negativt(text_norm, post.get("negativa_filter", [])):
            continue
        kontext = _extrahera_kontext(text, positiva[0])
        träffar.append({
            "kod": post.get("kod", "OKÄND"),
            "lagrum": post.get("lagrum", ""),
            "beskrivning": post.get("beskrivning", ""),
            "indikation": post.get("indikation", ""),
            "föreslaget_block": post.get("föreslaget_block", ""),
            "matchade_mönster": positiva,
            "kontext": kontext,
            "not": "INDIKATIV_ENDAST — kräver källkedja i AUDIT",
        })

    if not träffar:
        return {
            "status": "INGEN_TRÄFF",
            "domän": meta.get("domän", domän),
            "träffar": [],
            "antal_träffar": 0,
            "not": meta.get("not", ""),
        }

    return {
        "status": "GENOMFÖRD",
        "domän": meta.get("domän", domän),
        "träffar": träffar,
        "antal_träffar": len(träffar),
        "not": meta.get("not", ""),
    }
