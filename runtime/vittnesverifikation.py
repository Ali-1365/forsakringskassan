from __future__ import annotations
# SFCAE-BINDNING: vittnesverifikation
# Roll: Alt B-modul (vittnesverifikation)
# Alt B — anropas via requested=True från pipeline eller MCP.
_BUNDEN_TILL_SFCAE = True
_ROLL = "vittnesverifikation"

"""
VITTNESVERIFIKATION — NEW_CODE från historisk specifikation (v6.0.0 FIX-07,
STEG 03b / L01b / Agent 2b "Vittnesverifieringsprotokoll").

Implementerar protokollets VITTNESVERIFIERINGSMATRIS deterministiskt: för varje
vittnessegment populeras matrisfält som kan härledas från text (Förhörsform,
ID-styrkt) med EJ ANGIVET där underlag saknas, plus fullständighetskontroll.
Ingen tillförlitlighetsbedömning uppfinns — protokollet kräver att tomma fält
flaggas, inte gissas. Ljudberoende verifiering (järn i protokollet: muntliga
förhör) förblir kopplad till GAP-C (verklig ASR saknas i hela historien).

STATUS: POST-HISTORISK NYIMPLEMENTATION (SPEC_ONLY → implementerad från v6.0).
"""
import re
from typing import Any, Dict, List

WITNESS_PATTERNS = [
    re.compile(r"\bvittnesförhör\b", re.I),
    re.compile(r"\bvittnesmål\b", re.I),
    # Även böjda former (vittnet/vittnen/vittnes) är vittnessignaler. Med en
    # strikt \bvittne\b tystnade normala utsagor som "Vittnet ändrade ...".
    re.compile(r"\bvittne(?:t|n|ns)?\b", re.I),
    re.compile(r"\bförhör\s+med\b", re.I),
]
FORM_PATTERNS = [
    (re.compile(r"videolänk|videoförhör", re.I), "videolänk"),
    (re.compile(r"telefon", re.I), "telefon"),
    (re.compile(r"skriftlig", re.I), "skriftligt"),
    (re.compile(r"personligt|muntlig", re.I), "personligt"),
]
ID_PATTERNS = [
    (re.compile(r"id[- ]?styrkt\s*[:\-]?\s*ja|identitet\s+fastställd", re.I), "JA"),
    (re.compile(r"id[- ]?styrkt\s*[:\-]?\s*nej|identitet\s+ej\s+fastställd", re.I), "NEJ"),
]

REQUIRED_FIELDS = ["VITTNE-ID", "Namn", "Roll", "Förhörsdatum", "Förhörsform",
                   "ID-styrkt", "Förhörsledare"]


def build_matris(segment: Dict[str, Any], index: int) -> Dict:
    """Populerar v6.0-matrisen för ett vittnessegment (textbaserat, deterministiskt)."""
    text = str(segment.get("text") or "")
    form = next((f for pat, f in FORM_PATTERNS if pat.search(text)), "EJ ANGIVET")
    id_styrkt = next((v for pat, v in ID_PATTERNS if pat.search(text)), "EJ ANGIVET")
    matris = {
        "VITTNE-ID": f"VIT-{index:03d}",
        "Namn": str(segment.get("namn") or "EJ ANGIVET"),
        "Roll": str(segment.get("roll") or "EJ ANGIVET"),
        "Förhörsdatum": str(segment.get("datum") or "EJ ANGIVET"),
        "Förhörsform": form,
        "ID-styrkt": id_styrkt,
        "Förhörsledare": str(segment.get("förhörsledare") or "EJ ANGIVET"),
        "källfil": str(segment.get("källfil") or ""),
        "ljudberoende_verifiering": "GAP-C — verklig ASR saknas (ljud kan ej verifieras)",
    }
    matris["fullständighet"] = (
        "COMPLETE" if all(matris[f] not in ("EJ ANGIVET", "") for f in REQUIRED_FIELDS)
        else "OFULLSTÄNDIG (flaggad för manuell granskning enligt protokoll)")
    return matris


def run(segments: List[Dict[str, Any]]) -> Dict:
    """Kör protokollet över alla vittnessegment. segments: [{text, namn?, roll?, datum?,
    förhörsledare?, källfil?}] — segment utan vittnesignal hoppas över."""
    matriser = []
    idx = 0
    for seg in segments or []:
        text = str(seg.get("text") or "")
        if any(p.search(text) for p in WITNESS_PATTERNS):
            idx += 1
            matriser.append(build_matris(seg, idx))
    return {
        "status": "GENOMFÖRD" if matriser else "INGA VITTNESEGMENT",
        "antal_matriser": len(matriser),
        "ofullständiga": sum(1 for m in matriser if m["fullständighet"].startswith("OFULLSTÄNDIG")),
        "matriser": matriser,
        "källa": "v6.0.0 FIX-07 STEG 03b (Agent 2b) — NEW_CODE från spec",
    }



def run_vittnesverifikation_if_requested(
    segments: List[Dict[str, Any]] = None,
    requested: bool = False,
    csm: Any = None,
    state: Any = None,
    case_state: Any = None,
    claims: Any = None,
    meta: Any = None,
    case_meta: Any = None,
) -> Dict[str, Any]:
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "Vittnesverifikation kräver requested=True."}
    eff_segments = list(segments or [])
    if not eff_segments:
        for src_obj in (claims, csm, case_state, state):
            if isinstance(src_obj, list):
                for c in src_obj:
                    if isinstance(c, dict):
                        eff_segments.append({"text": str(c.get("text") or c.get("content") or ""), "datum": str(c.get("datum") or c.get("date") or ""), "källfil": str(c.get("källfil") or c.get("file_name") or "")})
                    else:
                        eff_segments.append({"text": str(getattr(c, "text", "") or getattr(c, "content", "") or ""), "datum": str(getattr(c, "datum", "") or getattr(c, "date", "") or ""), "källfil": str(getattr(c, "källfil", "") or getattr(c, "file_name", "") or "")})
            elif src_obj is not None and getattr(src_obj, "claims", None):
                for c in getattr(src_obj, "claims") or []:
                    if isinstance(c, dict):
                        eff_segments.append({"text": str(c.get("text") or c.get("content") or ""), "datum": str(c.get("datum") or c.get("date") or ""), "källfil": str(c.get("källfil") or c.get("file_name") or "")})
                    else:
                        eff_segments.append({"text": str(getattr(c, "text", "") or getattr(c, "content", "") or ""), "datum": str(getattr(c, "datum", "") or getattr(c, "date", "") or ""), "källfil": str(getattr(c, "källfil", "") or getattr(c, "file_name", "") or "")})
            if eff_segments:
                break
    if not eff_segments:
        return {"status": "EJ_KÖRBAR", "skäl": "Saknar segments."}
    return run(eff_segments)
