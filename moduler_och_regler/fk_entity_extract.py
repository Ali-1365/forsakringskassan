from __future__ import annotations
# -*- coding: utf-8 -*-
# PASSIV MOTIVERING: FK-entitetsextraktion — anropas av fk_rapport_runner.py.
# Bibehålls per arkitekturbeslutet.
_PASSIV_MOTIVERING = True

"""
FK entity extract — datum, diarienummer, lagrum, belopp, enkla personmönster.
Indikativt. Ingen bevisvärdering. Ingen domslut.
"""
import re
import sys
from typing import Dict, List, Tuple


def extrahera_datum(text: str) -> List[str]:
    return sorted(set(re.findall(r"\d{4}-\d{2}-\d{2}", text or "")))


def extrahera_diarienummer(text: str) -> List[str]:
    pats = [
        r"\d{12}[_-]\d{4}[_-]\d{10}",
        r"\b\d{4}-\d{6,}\b",
    ]
    out = []
    for p in pats:
        out.extend(re.findall(p, text or ""))
    return sorted(set(out))


def extrahera_lagrum(text: str) -> List[str]:
    pats = [
        r"FL\s*\d+\s*§",
        r"SFB\s*\d+\s*kap\.?\s*\d+\s*§?",
        r"SkL\s*\d+\s*kap\.?\s*\d+\s*§?",
        r"HFD\s*\d{4}\s*ref\.?\s*\d+",
        r"FPL\s*\d+\s*§",
    ]
    out = []
    for p in pats:
        out.extend(re.findall(p, text or "", flags=re.I))
    return sorted(set(out))


def extrahera_belopp(text: str) -> List[Tuple[float, str]]:
    matches = re.findall(
        r"(\d{1,3}(?:[\s\u00a0]\d{3})*(?:[.,]\d{2})?)\s*(?:SEK|kr|kronor)",
        text or "",
        flags=re.I,
    )
    out = []
    for m in matches:
        s = m.replace(" ", "").replace("\u00a0", "").replace(",", ".")
        try:
            v = float(s)
        except ValueError:
            # Beloppet hoppades över tyst. Eftersom träffarna används som
            # underlag för belopp i akten kunde ett belopp som matchade
            # mönstret men inte gick att tolka försvinna helt, utan spår.
            print(
                f"[FK_ENTITY] belopp kunde inte tolkas och utelämnas: {m!r}",
                file=sys.stderr,
            )
            continue
        out.append((v, f"{v:,.2f} SEK"))
    return out


def extrahera_personhint(text: str) -> List[str]:
    """Svaga namnhintar — ej identitetsverifiering."""
    pats = [
        r"[Dd]r\.?\s+([A-ZÅÄÖ][a-zåäö]+(?:\s+[A-ZÅÄÖ][a-zåäö]+){0,2})",
        r"handläggare\s+([A-ZÅÄÖ][a-zåäö]+(?:\s+[A-ZÅÄÖ][a-zåäö]+)?)",
    ]
    out = []
    for p in pats:
        out.extend(re.findall(p, text or ""))
    return sorted(set(out))


def extrahera_allt(text: str) -> Dict:
    belopp = extrahera_belopp(text)
    return {
        "datum": extrahera_datum(text),
        "diarienummer": extrahera_diarienummer(text),
        "lagrum": extrahera_lagrum(text),
        "belopp": [{"värde": b[0], "text": b[1]} for b in belopp],
        "person_hint": extrahera_personhint(text),
        "not": "INDIKATIV_ENDAST — kräver källverifiering",
    }
