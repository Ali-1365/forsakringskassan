from __future__ import annotations
# SFCAE-BINDNING: kallkedja
# Roll: Källkedje-/spårbarhetskontroll (dokument → faktum → rekvisit → lagrum → resultat)
# Alt B — anropas via requested=True från MCP.
_BUNDEN_TILL_SFCAE = True
_ROLL = "Källkedje-/spårbarhetskontroll"

# -*- coding: utf-8 -*-
"""
KÄLLKEDJA — spårar ett resultat bakåt till sin faktiska källa:

    RESULTAT (AuditFinding)
      ↓ source_ref
    REKVISIT (RequisiteEntry, byggd av requisite_claim_mapper vid L8)
      ↓ claim_id                      ↓ source_ref (lagrum, fritext)
    CLAIM (ClaimId — exakt citat,     LEGAL_SOURCE_RECORD (om en
      dokument, sida, datum)          matchande, verifierad rättskälla
                                       finns i ärendet)

Läser ENDAST redan byggda, canonical CaseState-fält
(claims/requisite_matrix/legal_sources/audit_*_findings/graph_edges/
files) — bygger ingen egen parallell spårningsdatabas och lägger inget
nytt i pipelinen. Varje länk som inte kan verifieras mot ett faktiskt
fält markeras EJ_VERIFIERAT eller EJ_HITTAT — fylls aldrig i med ett
antagande eller en påhittad källa.
"""
from typing import Any, Dict, List, Optional


def _claim_till_dict(claim: Any) -> Dict[str, Any]:
    return {
        "claim_id": claim.claim_id,
        "exakt_citat": claim.content,
        "källa_id": claim.source_id,
        "filnamn": claim.file_name,
        "sida": claim.page,
        "datum": claim.date,
        "version": claim.version,
        "påståendetyp": claim.claim_type,
        "tillgänglighet": getattr(claim.availability, "value", str(claim.availability)),
    }


def spåra_claim(case_state: Any, claim_id: Optional[str]) -> Dict[str, Any]:
    """
    Löser upp ett claim_id till dess fullständiga dokumentprovenens
    (exakt citat, källfil, sida, datum) — det obligatoriska 7-fälts-
    formatet (FIX-B) som redan krävs av canonical för varje claim.
    """
    if not claim_id or claim_id == "NOT_VERIFIABLE":
        return {
            "status": "EJ_VERIFIERAT",
            "skäl": "Inget claim_id angivet, eller markerat NOT_VERIFIABLE av rekvisitmappningen.",
        }
    for claim in getattr(case_state, "claims", None) or []:
        if claim.claim_id == claim_id:
            return {"status": "VERIFIERAT", "claim": _claim_till_dict(claim)}
    return {
        "status": "EJ_VERIFIERAT",
        "skäl": f"claim_id '{claim_id}' finns inte bland case_state.claims.",
    }


def _lagrum_till_rättskälla(case_state: Any, lagrum: Optional[str]) -> Dict[str, Any]:
    """
    Försöker matcha ett rekvisits fritextlagrum mot en verifierad
    LegalSourceRecord i ärendet (case_state.legal_sources). Ingen
    träff ger EJ_VERIFIERAT — lagrummet redovisas ändå (det ANGAVS),
    men ingen rättskälla hittas på för att kedjan ska se fullständig ut.
    """
    if not lagrum:
        return {"status": "EJ_VERIFIERAT", "skäl": "Inget lagrum angivet på rekvisitet."}
    lagrum_norm = lagrum.strip().lower()
    for källa in getattr(case_state, "legal_sources", None) or []:
        cited = getattr(källa, "cited_law", "") or ""
        if cited.strip().lower() == lagrum_norm:
            blockerad = bool(getattr(källa, "blocked_from_requisites", False))
            return {
                "status": "BLOCKERAD" if blockerad else "VERIFIERAT",
                "rättskälla": källa.to_dict(),
            }
    return {
        "status": "EJ_VERIFIERAT",
        "skäl": (
            f"Lagrummet '{lagrum}' har ingen matchande, verifierad "
            f"LegalSourceRecord i case_state.legal_sources — angivet i "
            f"rekvisitmatrisen men inte styrkt mot en rättskälla i det "
            f"aktuella ärendet."
        ),
    }


def spåra_rekvisit(case_state: Any, rekvisit_text: str) -> Dict[str, Any]:
    """
    REKVISIT → LAGRUM(+RÄTTSKÄLLA) → CLAIM → DOKUMENT/EXAKT TEXT.

    rekvisit_text matchas exakt mot RequisiteEntry.requisite_text i
    case_state.requisite_matrix. Flera rekvisit med identisk text
    (ovanligt, men inte uteslutet) redovisas alla, inte bara den första.
    """
    if not rekvisit_text:
        return {"status": "EJ_KÖRBAR", "skäl": "Inget rekvisit_text angivet."}

    matris = getattr(case_state, "requisite_matrix", None) or []
    träffar = [r for r in matris if r.requisite_text == rekvisit_text]
    if not träffar:
        return {
            "status": "EJ_HITTAT",
            "skäl": (
                f"Inget rekvisit med exakt den texten finns i "
                f"case_state.requisite_matrix ({len(matris)} rekvisit "
                f"totalt i ärendet)."
            ),
        }

    kedjor = []
    for entry in träffar:
        claim_spårning = spåra_claim(case_state, entry.claim_id)
        lagrum_spårning = _lagrum_till_rättskälla(case_state, entry.source_ref)
        kedjor.append({
            "rekvisit": entry.requisite_text,
            "modal": getattr(entry.modal, "value", str(entry.modal)),
            "rekvisitstatus": getattr(entry.status, "value", str(entry.status)),
            "lagrum": entry.source_ref,
            "lagrum_spårning": lagrum_spårning,
            "claim_spårning": claim_spårning,
            "fullständigt_spårbar": (
                claim_spårning["status"] == "VERIFIERAT"
                and lagrum_spårning["status"] == "VERIFIERAT"
            ),
        })

    return {
        "status": "GENOMFÖRD",
        "antal_träffar": len(kedjor),
        "kedjor": kedjor,
        "not": (
            "INDIKATIV_ENDAST. Visar bara VAD som styrker rekvisitet och "
            "VARIFRÅN (claim + lagrum/rättskälla) — bedömer aldrig om "
            "rekvisitet faktiskt är uppfyllt. 'fullständigt_spårbar' "
            "är False så fort någon länk i kedjan inte kunde verifieras."
        ),
    }


def spåra_finding(case_state: Any, finding_id: str) -> Dict[str, Any]:
    """
    RESULTAT (AuditFinding) → dess source_ref, tolkat i den ordning det
    faktiskt kan peka: claim_id, grafkant (edge_id), fil (file_id) —
    eller en fasetikett (t.ex. "L7_RÄTTSKÄLLEKONTROLL") som inte pekar
    på en specifik post alls. Det senare redovisas explicit som
    FASETIKETT, aldrig maskerat som en trasig claim-spårning.
    """
    if not finding_id:
        return {"status": "EJ_KÖRBAR", "skäl": "Inget finding_id angivet."}

    alla_findings = (
        list(getattr(case_state, "audit_a_findings", None) or [])
        + list(getattr(case_state, "audit_b_findings", None) or [])
        + list(getattr(case_state, "audit_c_findings", None) or [])
    )
    träff = next((f for f in alla_findings if f.finding_id == finding_id), None)
    if träff is None:
        return {
            "status": "EJ_HITTAT",
            "skäl": (
                f"Inget fynd med finding_id '{finding_id}' hittades bland "
                f"{len(alla_findings)} granskade fynd (audit A/B/C)."
            ),
        }

    källref = träff.source_ref
    claim_spårning = spåra_claim(case_state, källref)
    if claim_spårning["status"] == "VERIFIERAT":
        källtyp = "CLAIM"
    else:
        edge = next(
            (e for e in getattr(case_state, "graph_edges", None) or [] if e.edge_id == källref),
            None,
        )
        fil = next(
            (f for f in getattr(case_state, "files", None) or [] if f.file_id == källref),
            None,
        )
        if edge is not None:
            källtyp = "GRAFKANT"
        elif fil is not None:
            källtyp = "FIL"
        else:
            källtyp = "FASETIKETT"

    return {
        "status": "GENOMFÖRD",
        "finding_id": träff.finding_id,
        "agent": träff.agent,
        "beskrivning": träff.description,
        "allvarlighet": träff.severity,
        "source_ref": källref,
        "källtyp": källtyp,
        "claim_spårning": claim_spårning if källtyp == "CLAIM" else None,
        "not": (
            "INDIKATIV_ENDAST. källtyp=FASETIKETT betyder att fyndet är "
            "kopplat till en analysfas (t.ex. L7_RÄTTSKÄLLEKONTROLL), "
            "inte ett specifikt, spårbart dokumentcitat — redovisas som "
            "sådant, fylls aldrig i med en påhittad claim-koppling."
        ),
    }


def run_kallkedja_if_requested(
    case_state: Any = None,
    rekvisit_text: Optional[str] = None,
    finding_id: Optional[str] = None,
    claim_id: Optional[str] = None,
    requested: bool = False,
) -> Dict[str, Any]:
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "Källkedjespårning kräver requested=True."}
    if case_state is None:
        return {"status": "EJ_KÖRBAR", "skäl": "Inget case_state angivet."}
    if rekvisit_text:
        return spåra_rekvisit(case_state, rekvisit_text)
    if finding_id:
        return spåra_finding(case_state, finding_id)
    if claim_id:
        return spåra_claim(case_state, claim_id)
    return {
        "status": "EJ_KÖRBAR",
        "skäl": "Ange exakt ett av rekvisit_text, finding_id eller claim_id.",
    }
