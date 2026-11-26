from __future__ import annotations
# SFCAE-BINDNING: change_impact
# Roll: Ändringsimpakt
# Alt B — anropas via requested=True från pipeline eller MCP.
# Producerar aldrig domslut. INDIKATIV_ENDAST.
_BUNDEN_TILL_SFCAE = True
_ROLL = "Ändringsimpakt"

# -*- coding: utf-8 -*-
"""Change Impact Engine — vilka lager nytt material kan påverka (indikativ)."""
from typing import Any, Dict, List, Optional


def analysera_impact(
    new_material_summary: str = "",
    affected_hints: Optional[List[str]] = None,
) -> Dict[str, Any]:
    hints = [h.lower() for h in (affected_hints or [])]
    blob = (new_material_summary or "").lower()
    layers = []
    mapping = [
        ("FACT", ["faktum", "datum", "händelse"]),
        ("EVIDENCE", ["bevis", "bilaga", "vittne"]),
        ("LEGAL", ["lagrum", "rekvisit", "praxis"]),
        ("PROCEDURAL", ["frist", "kommunikation", "process"]),
        ("CONSEQUENCE", ["påverkan", "utgång", "följd"]),
    ]
    for layer, keys in mapping:
        if any(k in blob for k in keys) or any(k in hints for k in keys):
            layers.append(layer)
    if not layers and (blob or hints):
        impact = "LOCAL_IMPACT"
        layers = ["UNKNOWN_PENDING_REVIEW"]
    elif not layers:
        impact = "NO_IMPACT"
    elif len(layers) >= 3:
        impact = "MULTI_LAYER_IMPACT"
    elif len(layers) == 1:
        impact = "LOCAL_IMPACT"
    else:
        impact = "MULTI_LAYER_IMPACT"
    return {
        "status": "GENOMFÖRD",
        "impact": impact,
        "affected_layers": layers,
        "not": "INDIKATIV. Endast verifierad påverkan får ändra Case State.",
    }


def run_change_impact_if_requested(
    new_material_summary: str = "",
    requested: bool = False,
) -> Dict[str, Any]:
    if not requested:
        return {"status": "EJ_BEGÄRD"}
    return analysera_impact(new_material_summary=new_material_summary)
