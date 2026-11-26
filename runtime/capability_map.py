from __future__ import annotations
# SFCAE-BINDNING: capability_map
# Roll: Förmågekarta
# Alt B — anropas via requested=True från pipeline eller MCP.
# Producerar aldrig domslut. INDIKATIV_ENDAST.
_BUNDEN_TILL_SFCAE = True
_ROLL = "Förmågekarta"

# -*- coding: utf-8 -*-
"""Dynamic capability map — vilka specialistmoduler som behövs."""
from pathlib import Path
from typing import Any, Dict, List, Optional
import sys

try:
    import yaml
    _Y = True
except ImportError:
    _Y = False

ROOT = Path(__file__).resolve().parent.parent


def aktivera_moduler(text: str = "", filnamn: Optional[List[str]] = None) -> Dict[str, Any]:
    blob = (text or "").lower()
    for n in filnamn or []:
        blob += " " + str(n).lower()
    cfg = {}
    hinder = None
    p = ROOT / "config" / "capability_map.yaml"
    if not _Y:
        hinder = "pyyaml saknas"
    elif not p.is_file():
        hinder = f"{p} saknas"
    else:
        try:
            cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception as e:
            hinder = f"{p.name} kunde inte tolkas: {type(e).__name__}: {e}"
    moduler = cfg.get("moduler") or {}
    if not hinder and not moduler:
        hinder = f"{p.name} innehåller inga moduler"
    aktiva, inaktiva = [], []
    for namn, spec in moduler.items():
        triggers = [t.lower() for t in (spec.get("triggers") or [])]
        hit = any(t in blob for t in triggers)
        entry = {
            "modul": namn,
            "aktiv": hit,
            "sfcae": spec.get("sfcae") or [],
            "not": "INDIKATIV — modul får inte själv skapa juridisk slutsats",
        }
        (aktiva if hit else inaktiva).append(entry)
    # Statusen var GENOMFÖRD även när konfigurationen inte gick att läsa och
    # noll moduler alltså hade övervägts. Ett tomt resultat på den grunden gick
    # då inte att skilja från ett ärende där ingen specialistmodul var
    # tillämplig — i båda fallen svarade funktionen att kartläggningen var
    # genomförd med noll aktiva moduler.
    return {
        "status": "GENOMFÖRD" if hinder is None else "EJ GENOMFÖRD",
        "hinder": hinder,
        "aktiva": aktiva,
        "inaktiva": inaktiva,
        "antal_aktiva": len(aktiva),
        "antal_prövade": len(moduler),
        "not": "Capability map. Specialistmodul ≠ juridisk slutbedömning.",
    }


def load_architecture_knowledge() -> Dict[str, str]:
    """Laddar och läser architecture knowledge från knowledge base."""
    from knowledge_loader import search_knowledge, get_knowledge
    arch = search_knowledge("architecture", by="category")
    if arch:
        arch_contents = {}
        for a in arch:
            content = get_knowledge(a.relative_path)
            if content:
                arch_contents[a.filename] = content

        print(f"[CAPABILITY_MAP] Read {len(arch_contents)}/{len(arch)} architecture documents", file=sys.stderr)
        return arch_contents
    return {}


def run_capability_map_if_requested(
    text: str = "",
    filnamn: Optional[List[str]] = None,
    pipeline_state: Any = None,
    requested: bool = False,
) -> Dict[str, Any]:
    if not requested:
        return {"status": "EJ_BEGÄRD"}
    if not text and pipeline_state is not None:
        text = str(getattr(pipeline_state, "zero_fel", "") or "")
        filnamn = filnamn or [
            str(getattr(f, "name", f) if not isinstance(f, dict) else f.get("name", ""))
            for f in (getattr(pipeline_state, "files", []) or [])
        ]
    return aktivera_moduler(text=text, filnamn=filnamn)
