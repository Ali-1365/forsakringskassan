from __future__ import annotations
# SFCAE-BINDNING: case_paths
# Roll: Sökvägspolicy (sandlåda för ärendedata)
# Producerar aldrig domslut. INDIKATIV_ENDAST.
_BUNDEN_TILL_SFCAE = True
_ROLL = "Sökvägspolicy"

# -*- coding: utf-8 -*-
"""
CASE PATHS — central sökvägspolicy för SFCAE.

Bakgrund
--------
Sökvägssaneringen (S8707) låste tidigare ALL filåtkomst till installationsroten.
Det gjorde installationsmappen till en dold runtime-förutsättning: ett ärende
utanför installationen kunde inte läsas alls. Ärenden ligger aldrig i
installationen — de ligger på domstolens eller handläggarens egna volymer.

Policy
------
Skyddet behålls, men basen är inte längre hårdkodad till installationsroten.
Tillåten bas = installationsroten UNION de ärenderötter som operatören själv
har anvisat. En ärenderot anvisas på exakt ett av två sätt:

  1. Explicit på kommandoraden (operatörens direkta anvisning), eller
  2. Miljövariabeln SFCAE_CASE_ROOTS (os.pathsep-separerad lista).

Allt som härleds därefter — filnamn ur dokument, sökvägar ur MCP-anrop,
sökvägar ur konfiguration — valideras mot den tillåtna basmängden. Det är där
traversal-skyddet hör hemma: på härledda, icke betrodda sökvägar, inte på
operatörens egen anvisning.

Ingen sökväg till en utvecklingsmiljö får vara nödvändig. INDIKATIV_ENDAST.
"""

import os
from typing import Iterable, List, Optional

# Installationsroten (paketets egen rot) — alltid tillåten bas.
INSTALL_ROOT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# Miljövariabel för operatörsanvisade ärenderötter.
ENV_CASE_ROOTS = "SFCAE_CASE_ROOTS"


def _canonical(path: str) -> str:
    """Kanonisk absolut sökväg. Ingen validering — bara normalisering."""
    return os.path.realpath(os.path.abspath(os.path.expanduser(str(path))))


def env_case_roots() -> List[str]:
    """Ärenderötter anvisade via SFCAE_CASE_ROOTS. Tom lista om ej satt."""
    raw = os.environ.get(ENV_CASE_ROOTS, "")
    if not raw.strip():
        return []
    roots: List[str] = []
    for part in raw.split(os.pathsep):
        part = part.strip()
        if part:
            roots.append(_canonical(part))
    return roots


def allowed_bases(extra_roots: Optional[Iterable[str]] = None) -> List[str]:
    """
    Den tillåtna basmängden: installationsroten + SFCAE_CASE_ROOTS + extra_roots.

    extra_roots är ärenderötter som operatören anvisat i det aktuella anropet
    (t.ex. CLI-argument). De är betrodda i egenskap av att vara operatörens
    egen anvisning — men de kanoniseras ändå.
    """
    bases = [INSTALL_ROOT]
    bases.extend(env_case_roots())
    for r in (extra_roots or []):
        bases.append(_canonical(r))
    # Deduplicera med bevarad ordning.
    seen = set()
    unique: List[str] = []
    for b in bases:
        if b not in seen:
            seen.add(b)
            unique.append(b)
    return unique


def is_within(path: str, bases: Iterable[str]) -> bool:
    """True om path ligger i eller under någon av bases."""
    resolved_path = _canonical(path)
    for base in bases:
        base_dir = _canonical(base)
        if resolved_path == base_dir or resolved_path.startswith(base_dir + os.sep):
            return True
    return False


def safe_path(user_path: str, extra_roots: Optional[Iterable[str]] = None) -> str:
    """
    Validerar att user_path ligger inom den tillåtna basmängden.

    Används på HÄRLEDDA / icke betrodda sökvägar (MCP-parametrar, sökvägar ur
    dokumentinnehåll, konfigurationsvärden). Returnerar kanonisk sökväg eller
    kastar ValueError.
    """
    bases = allowed_bases(extra_roots)
    resolved_path = _canonical(user_path)
    for base in bases:
        if resolved_path == base or resolved_path.startswith(base + os.sep):
            return resolved_path
    raise ValueError(
        f"Sökväg utanför tillåtet område: {user_path!r}. "
        f"Anvisa ärenderoten via kommandoraden eller {ENV_CASE_ROOTS}."
    )


def resolve_case_root(user_path: str) -> str:
    """
    Kanoniserar en ärenderot som operatören anvisat explicit.

    Anvisningen i sig är behörigheten — därför sker ingen containment-kontroll
    mot installationsroten här. Däremot måste roten faktiskt finnas och vara en
    katalog; annars är ärendet inte körbart och det ska synas direkt.
    """
    resolved_path = _canonical(user_path)
    if not os.path.isdir(resolved_path):
        raise ValueError(f"Ärenderot saknas eller är ingen katalog: {user_path!r}")
    return resolved_path


def assert_output_outside_cases(output_dir: str, case_roots: Iterable[str]) -> str:
    """
    Output får aldrig hamna i eller under en ärenderot — ärendematerialet ska
    förbli orört. Returnerar kanonisk outputsökväg.
    """
    out = _canonical(output_dir)
    for root in case_roots:
        base = _canonical(root)
        if out == base or out.startswith(base + os.sep):
            raise ValueError("Outputmapp får inte vara/ligga under ärenderot.")
    return out
