from __future__ import annotations
# SFCAE-BINDNING: bristrapport
# Roll: Bristförteckning
# Alt B — anropas via requested=True från pipeline eller MCP.
# Producerar aldrig domslut. INDIKATIV_ENDAST.
_BUNDEN_TILL_SFCAE = True
_ROLL = "Bristförteckning"

# -*- coding: utf-8 -*-
"""
Bristrapport: aggregerar REDAN BERÄKNADE fynd (hard stops, audit-fynd,
ofullständiga steg, olösta grafkanter) till en sorterad bristförteckning.

Skapar inga nya bedömningar. Varje rad i förteckningen härleds direkt ur
ett fält som redan finns i CaseState och redan är verifierat av annan
kod (AuditController, registrera_steg, RelationGraphBuilder). Detta är
en omformatterare, inte en ny analysmotor.
"""
from typing import Any, Dict, List

_RISKORDNING = {"KRITISK": 0, "HÖG": 1, "MEDEL": 2, "LÅG": 3}


def _hard_stop_brister(case_state) -> List[Dict[str, Any]]:
    from hard_stop_register import hämta

    brister = []
    for kod in getattr(case_state, "hard_stop_codes", None) or []:
        kod_str = kod.value if hasattr(kod, "value") else str(kod)
        post = hämta(kod_str)
        brister.append({
            "typ": "HARD_STOP",
            "kod": kod_str,
            "beskrivning": post.beskrivning if post else "Okänd hard stop-kod",
            "risknivå": "KRITISK",
            "källa": "case_state.hard_stop_codes",
        })
    return brister


def _audit_brister(case_state) -> List[Dict[str, Any]]:
    brister = []
    for agent_fält in ("audit_a_findings", "audit_b_findings", "audit_c_findings"):
        for f in getattr(case_state, agent_fält, None) or []:
            brister.append({
                "typ": "AUDIT_FYND",
                "kod": f.finding_id,
                "beskrivning": f.description,
                "risknivå": f.severity,
                "källa": f"case_state.{agent_fält}",
                "agent": f.agent,
                "referens": f.source_ref,
            })
    return brister


def _steg_brister(case_state) -> List[Dict[str, Any]]:
    from forensic_engine_v10_3_canonical import ej_genomförda_steg

    brister = []
    for s in ej_genomförda_steg(case_state):
        brister.append({
            "typ": "OFULLSTÄNDIGT_STEG",
            "kod": s.get("steg", "OKÄNT_STEG"),
            "beskrivning": s.get("skäl", "") or f"Status: {s.get('status')}",
            "risknivå": "HÖG" if s.get("status") == "EJ_KÖRBAR" else "MEDEL",
            "källa": "case_state.metadata['stegstatus']",
        })
    return brister


def _grafkant_brister(case_state) -> List[Dict[str, Any]]:
    brister = []
    for edge in getattr(case_state, "graph_edges", None) or []:
        edge_typ = edge.edge_type.value if hasattr(edge.edge_type, "value") else str(edge.edge_type)
        if edge_typ == "UNRESOLVED":
            brister.append({
                "typ": "OLÖST_BEVISKEDJA",
                "kod": edge.edge_id,
                "beskrivning": (
                    f"{edge.source_node} → {edge.target_node}: ankaret klarade "
                    "inte verifiering (VerbatimAnchor ogiltigt)."
                ),
                "risknivå": "MEDEL",
                "källa": "case_state.graph_edges",
            })
    return brister


def _kumulationseffekter(brister: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Identifierar systematiska fel: samma källreferens (t.ex. samma dokument
    eller samma steg) som återkommer i flera brister. Räknar bara det som
    redan finns i listan — lägger inte till nya bedömningar.
    """
    räkning: Dict[str, int] = {}
    for b in brister:
        ref = b.get("referens") or b.get("källa")
        if ref:
            räkning[ref] = räkning.get(ref, 0) + 1
    return [
        {"referens": ref, "antal_brister": n}
        for ref, n in sorted(räkning.items(), key=lambda kv: -kv[1])
        if n > 1
    ]


def generera_bristrapport(case_state) -> Dict[str, Any]:
    """Genererar bristförteckning från redan genomförd analys."""
    brister: List[Dict[str, Any]] = []
    brister.extend(_hard_stop_brister(case_state))
    brister.extend(_audit_brister(case_state))
    brister.extend(_steg_brister(case_state))
    brister.extend(_grafkant_brister(case_state))

    brister.sort(key=lambda b: _RISKORDNING.get(b["risknivå"], 9))

    statistik: Dict[str, int] = {}
    for b in brister:
        statistik[b["risknivå"]] = statistik.get(b["risknivå"], 0) + 1

    return {
        "status": "GENOMFÖRD" if brister else "INGA_BRISTER_FUNNA",
        "case_id": getattr(case_state, "case_id", ""),
        "totalt_antal": len(brister),
        "per_risknivå": statistik,
        "brister": brister,
        "kumulationseffekter": _kumulationseffekter(brister),
        "not": (
            "INDIKATIV_ENDAST — sammanställning av redan beräknade fynd "
            "(hard stops, audit A/B/C, ofullständiga steg, olösta "
            "beviskedjor). Skapar inga nya bedömningar."
        ),
    }


def run_bristrapport_if_requested(case_state=None, requested: bool = False) -> Dict[str, Any]:
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "Bristrapport kräver requested=True."}
    if case_state is None:
        return {"status": "EJ_KÖRBAR", "skäl": "Inget case_state angivet."}
    return generera_bristrapport(case_state)

