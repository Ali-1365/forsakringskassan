from __future__ import annotations
# SFCAE-BINDNING: layer_map
# Roll: Lagerkarta
# Alt B — anropas via requested=True från pipeline eller MCP.
# Producerar aldrig domslut. INDIKATIV_ENDAST.
_BUNDEN_TILL_SFCAE = True
_ROLL = "Lagerkarta"

# -*- coding: utf-8 -*-
"""
Architecture_SKILL-lager → SFCAE dynamic/canonical.
Endast mappning och metadata — ingen ny tillståndsmaskin.
"""
from typing import Any, Dict, List, Optional
import sys

def _load_map() -> Dict[str, Any]:
    try:
        from config_loader import ladda
        return ladda("layer_map") or {}
    except Exception:
        return {}


def architecture_layers() -> Dict[str, Any]:
    return (_load_map().get("architecture_to_sfcae") or {})


def map_architecture_layer(layer_id: str) -> Dict[str, Any]:
    layers = architecture_layers()
    key = layer_id if layer_id in layers else layer_id.upper()
    entry = layers.get(key) or layers.get(layer_id) or {}
    return {
        "layer_id": layer_id,
        "dynamic_steps": list(entry.get("dynamic_steps") or []),
        "canonical_states": list(entry.get("canonical_states") or []),
        "optional_modules": list(entry.get("optional_modules") or []),
        "beskrivning": entry.get("beskrivning") or "",
        "hittad": bool(entry),
    }


def bidirectional_audit_policy() -> Dict[str, Any]:
    m = _load_map()
    pol = m.get("bidirectional_audit") or {}
    return {
        "rule": pol.get("rule") or "CONTROL_ONLY",
        "never_dataflow": bool(pol.get("never_dataflow", True)),
        "modules": list(pol.get("modules") or []),
    }


def get_layer_knowledge(layer_number: int) -> Optional[str]:
    """Laddar juridisk teori för en specifik lagernivå (0-12)."""
    from knowledge_loader import get_knowledge

    if not 0 <= layer_number <= 12:
        return None

    file_path = f"references/knowledge/legal-theory/lager-{layer_number}-integritet.md"
    if layer_number == 13:
        file_path = "references/knowledge/legal-theory/lager-mappning.md"

    content = get_knowledge(file_path)
    if content:
        print(f"[LAYER_MAP] Loaded legal-theory for layer {layer_number}", file=sys.stderr)
    return content


def attach_layer_map_to_meta(case_meta: Optional[Dict] = None) -> Dict:
    """Lägg layer_map-referens i case_meta (icke-invasivt)."""
    meta = dict(case_meta or {})
    meta["layer_map_version"] = (_load_map().get("version") or "1.0")
    meta["bidirectional_audit"] = bidirectional_audit_policy()

    # Load legal-theory knowledge for all layers
    from knowledge_loader import search_knowledge, get_knowledge
    legal_theory = search_knowledge("legal-theory", by="category")
    if legal_theory:
        layer_contents = {}
        for layer_file in legal_theory:
            content = get_knowledge(layer_file.relative_path)
            if content:
                layer_contents[layer_file.filename] = content

        meta["_layer_knowledge_available"] = len(legal_theory)
        meta["_layer_knowledge_read"] = len(layer_contents)
        print(f"[LAYER_MAP] Read {len(layer_contents)}/{len(legal_theory)} legal-theory files", file=sys.stderr)

    return meta
