#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemensam YAML-laddning som redovisar varifrån konfigurationen kom.

Åtta skannermoduler bar samma konstruktion:

    try:
        import yaml
        _Y = True
    except ImportError:
        _Y = False

    def _load_cfg() -> Dict:
        p = ROOT / "config" / "x.yaml"
        if _Y and p.is_file():
            try:
                return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except Exception:
                pass
        return {}          # eller en inbyggd standardlista

Tre skilda utfall landade i samma tysta returvärde: pyyaml saknades, filen
saknades, eller filen gick inte att tolka. Skannern kördes då vidare på
inbyggda värden eller på tom konfiguration och svarade som vanligt. En
operatör som ändrat en tröskel eller ett mönster i config/ kunde alltså få
tillbaka motorns egna värden utan att något sade det — samma felklass som
lagskifte_validator bar för HS11.

Laddaren nedan returnerar därför alltid källan och skälet vid sidan av
data, så att anroparen kan redovisa vilken konfiguration som faktiskt
användes.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import yaml
    YAML_TILLGÄNGLIG = True
except ImportError:
    # pyyaml är ett deklarerat beroende som sfcae_cli --check prövar.
    # Saknas det ändå blir varje laddning nedan EJ_LÄST med det som skäl,
    # i stället för en tom konfiguration som ser normal ut.
    YAML_TILLGÄNGLIG = False


@dataclass
class Konfig:
    """Resultatet av en konfigurationsladdning."""

    data: Dict[str, Any] = field(default_factory=dict)
    källa: str = "EJ_LÄST"          # "config" | "EJ_LÄST"
    skäl: Optional[str] = None
    sökväg: str = ""

    @property
    def från_config(self) -> bool:
        return self.källa == "config"

    def som_fält(self) -> Dict[str, Any]:
        """Redovisningsfält att lägga i ett skannerresultat."""
        return {
            "konfigkälla": self.källa,
            "konfigfil": self.sökväg,
            "konfigskäl": self.skäl,
        }


def ladda_konfig(sökväg: Path, tyst: bool = False) -> Konfig:
    """
    Läser en YAML-konfiguration och redovisar utfallet.

    Kastar aldrig. Misslyckad läsning ger källa EJ_LÄST med skäl, inte en
    tom konfiguration utan förklaring.
    """
    s = str(sökväg)
    if not YAML_TILLGÄNGLIG:
        return Konfig(källa="EJ_LÄST", skäl="pyyaml saknas", sökväg=s)
    if not sökväg.is_file():
        return Konfig(källa="EJ_LÄST", skäl=f"{sökväg.name} saknas", sökväg=s)
    try:
        data = yaml.safe_load(sökväg.read_text(encoding="utf-8")) or {}
    except Exception as e:
        skäl = f"{sökväg.name} kunde inte tolkas: {type(e).__name__}: {e}"
        if not tyst:
            print(f"[KONFIG] {skäl}", file=sys.stderr)
        return Konfig(källa="EJ_LÄST", skäl=skäl, sökväg=s)
    if not isinstance(data, dict):
        skäl = f"{sökväg.name} innehåller {type(data).__name__}, inte ett objekt"
        if not tyst:
            print(f"[KONFIG] {skäl}", file=sys.stderr)
        return Konfig(källa="EJ_LÄST", skäl=skäl, sökväg=s)
    return Konfig(data=data, källa="config", skäl=None, sökväg=s)
