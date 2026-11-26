from __future__ import annotations
# SFCAE-BINDNING: strict_legal_report_generator
# Roll: Alt B — strikt granskningspromemoria ur ett färdigt körresultat
# Producerar aldrig domslut. INDIKATIV_ENDAST.
# PORTERAD 2026-10-09 från C:\AI_Projects\sfcae_nymapp_karantan_2026-09-24\Ny mapp\strict_legal_report_generator.py
# (4 745 B, enda kända källan). Struktur (avsnitt 1–6) och signatur bevarade.
# Ändrat: källan fyllde i positiva standardvärden när data saknades
# ("GODKÄND FÖR PROCESSUELL PRÖVNING", "Alla 15 kontroller genomförda utan
# avvikelser", Claim-ID "VERIFIED", "100 % deterministiskt"). Saknad data
# redovisas nu som EJ ANGIVEN / EJ KÖRD — aldrig som ett positivt utfall.
# Läser både KONS unified_verdict ("layers") och sfcae consolidate()-resultat.
"""
STRICT_LEGAL_REPORT_GENERATOR — strikt, spårbar granskningspromemoria.
"""
import json
from pathlib import Path
from typing import Any, Dict, List

_EJ = "EJ ANGIVEN"


def _normalisera(verdict: Dict[str, Any]) -> Dict[str, Any]:
    """Gemensam vy över unified_verdict (KONS) och consolidate() (sfcae)."""
    layers = verdict.get("layers") or {}
    if layers:
        motor_c = layers.get("motor_c", {}) or {}
        return {
            "case_id": verdict.get("case_id") or _EJ,
            "hard_stop": verdict.get("hard_stop"),
            "hard_stop_codes": list(verdict.get("hard_stop_codes") or []),
            "court_type": (layers.get("jurisdiction", {}) or {}).get("court_type"),
            "forum_status": (layers.get("jurisdiction", {}) or {}).get("status"),
            "files": motor_c.get("files_ingested"),
            "graph_nodes": (motor_c.get("graph", {}) or {}).get("nodes"),
            "falsification": motor_c.get("falsification"),
            "counter_audit": motor_c.get("counter_audit"),
            "claims": len((layers.get("citations", {}) or {}).get("claims", []) or []) or None,
            "claim_validation": (layers.get("claim_id_validation", {}) or {}).get("status"),
            "overall_status": verdict.get("overall_status"),
            "delresultat": {},
        }
    forum = verdict.get("forum_detection") or {}
    counter_audit = verdict.get("counter_audit_results")
    if isinstance(counter_audit, dict):
        cac = counter_audit
    else:
        cac = verdict.get("counter_audit")
    return {
        "case_id": verdict.get("case_id") or _EJ,
        "hard_stop": verdict.get("hard_stop"),
        "hard_stop_codes": list(verdict.get("hard_stop_codes") or []),
        "court_type": forum.get("forum") if isinstance(forum, dict) else None,
        "forum_status": forum.get("status") if isinstance(forum, dict) else None,
        "files": verdict.get("files_count"),
        "graph_nodes": verdict.get("graph_edges_count"),
        "falsification": verdict.get("falsification_verdict"),
        "counter_audit": cac,
        "claims": verdict.get("claims_count"),
        "claim_validation": verdict.get("claim_id_validation"),
        "overall_status": verdict.get("overall_status"),
        "delresultat": verdict.get("motor_b") or {},
    }


def _v(x: Any) -> str:
    return _EJ if x is None or x == "" else str(x)


def generate_strict_legal_report(verdict: Dict[str, Any], output_path: str) -> str:
    n = _normalisera(verdict or {})
    lines: List[str] = []
    lines.append("# STRIKT FORENSISK GRANSKNINGSPROMEMORIA")
    lines.append(f"**Ärende-ID:** `{n['case_id']}`")
    lines.append("**Processläge:** STRIKT KONTRADIKTORISK FORENSISK GRANSKNING")
    lines.append("**Integritetspolicy:** Noll-inferens | Ordagrann källhänvisning | Saknad data redovisas som saknad")
    lines.append("\n---\n")

    lines.append("## 1. SAMMANFATTANDE BEDÖMNING")
    if n["hard_stop"] is True:
        lines.append("> **PROCESSUELLT STOPP (HARD STOP — HELSTOPP)**")
        lines.append(f"> **Hårdstoppskoder:** `{', '.join(map(str, n['hard_stop_codes'])) or _EJ}`")
        lines.append("> Här kommer domstolen att avslå din begäran. Du måste lägga till bevis för detta krav för att komma vidare.")
    elif n["hard_stop_codes"]:
        lines.append("> **PROCESSUELLT STOPP (HARD STOP — BEVISBRIST / SPÄRRAD KEDJA)**")
        lines.append(f"> **Hårdstoppskoder:** `{', '.join(map(str, n['hard_stop_codes']))}`")
        lines.append("> Här kommer domstolen att avslå din begäran. Du måste lägga till bevis för detta krav för att komma vidare.")
    elif n["hard_stop"] is False:
        lines.append("> Inga hårdstopp registrerade av motorn. Detta är INTE ett godkännande i sak.")
    else:
        lines.append(f"> Hard stop-status: {_EJ} — kan inte bedömas.")
    lines.append(f"> **Slutstatus (motor):** `{_v(n['overall_status'])}`")
    lines.append("\n")

    lines.append("## 2. PROCESSUELL BEHÖRIGHET & JURISDIKTION")
    lines.append(f"- **Domstolstyp/forum:** `{_v(n['court_type'])}`")
    lines.append(f"- **Forumstatus:** `{_v(n['forum_status'])}`")
    lines.append("\n")

    lines.append("## 3. INGESTION & BEVISINTEGRITET")
    lines.append(f"- **Inlästa filer:** `{_v(n['files'])}`")
    lines.append(f"- **Grafkanter/noder:** `{_v(n['graph_nodes'])}`")
    lines.append(f"- **Falsifieringsstatus:** `{_v(n['falsification'])}`")
    lines.append("\n")

    lines.append("## 4. KONTRADIKTORISK MOTGRANSKNING (B01–B15)")
    ca = n["counter_audit"]
    if isinstance(ca, dict) and ca:
        for k, v in ca.items():
            lines.append(f"- **{k}:** `{v}`")
    else:
        lines.append(f"- Motgranskningsresultat: {_EJ} (EJ KÖRD eller ej överfört) — inga slutsatser dras.")
    lines.append("\n")

    lines.append("## 5. BEVISKEDJA OCH KÄLLANKARE")
    lines.append(f"- **Claims:** `{_v(n['claims'])}`")
    lines.append(f"- **Claim-ID-validering:** `{_v(n['claim_validation'])}`")
    for namn, d in (n["delresultat"] or {}).items():
        if isinstance(d, dict):
            lines.append(f"- **{namn}:** `{_v(d.get('status'))}`")
    lines.append("\n")

    lines.append("## 6. SLUTSATS")
    lines.append("Promemorian återger motorns registrerade utfall. Den innehåller ingen "
                 "egen bedömning och inget domslut. Uppgifter markerade "
                 f"'{_EJ}' har inte kunnat fastställas. Granskas av behörig jurist.")
    lines.append("\n---")
    lines.append("*Genererad av SFCAE strict_legal_report_generator (INDIKATIV_ENDAST).*")

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("\n".join(lines), encoding="utf-8")
    return str(out_file)


def run_strict_report_if_requested(verdict: Dict[str, Any] = None, output_path: str = "",
                                   requested: bool = False) -> Dict[str, Any]:
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "Strikt rapport kräver requested=True."}
    if not verdict or not output_path:
        return {"status": "PARAMS_SAKNAS", "krävs": ["verdict", "output_path"]}
    return {"status": "GENOMFÖRD", "fil": generate_strict_legal_report(verdict, output_path)}
