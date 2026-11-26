# SFCAE-BINDNING: steg13_dynamic_legal_engine
# Roll: Alt B — STEG 13 dynamisk rättskälle- och juridikanalys (L06–L10)
# Producerar aldrig domslut. INDIKATIV_ENDAST.
# PORTERAD 2026-10-09 från C:\AI_Projects\sfcae_nymapp_karantan_2026-09-24\Ny mapp\steg13_dynamic_legal_engine.py
# (63 679 B, enda kända källan). Ärendespecifik hårdkodning (BrB 6:4/6:10, RB 35:1,
# FUP-SAKNAS) ersatt med materialhärledd logik; se SFCAE-PORT-kommentarer.
# Nätverk (requests) används ENDAST med enable_network=True.
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STEG 13 — DYNAMIC LEGAL SOURCE & JURIDICAL ANALYSIS ENGINE
===========================================================
SFCAE produktionsmodul för faktisk dynamisk rättskälle- och juridikanalys.

Implementerar (STEG 13 §1–§12):
  L06 APPLICABLE LAW       – dynamisk rättsområdes- och rättsfrågeidentifiering
  L07 LEGAL SUBSUMPTION    – SEARCH_01–10 + tvåstegsverifiering + subsumtion
  L08 JUDGMENT REASONING   – domskälsaudit (bidirectional)
  L09 LEGAL CONSEQUENCE    – rättslig följd
  L10 FINAL AUDIT REPORT   – slutrapport + reproduktionspost

ABS.: Noll syntetisk fabrikation. Ingen hårdkodad juridisk slutsats.
En sökträff är ALDRIG en verifierad rättskälla. PROVED kräver beviskedja.
Status OTILLRÄCKLIGT UNDERLAG – FÖRESLÅS KOMPLETTERING vid saknad verifiering.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# KÄLLOBJEKT (STEG 13 §2) – varje träff registreras som verifierbart objekt
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class RattkalleObjekt:
    """Verifierbart rättskälleobjekt (STEG 13 §2 fullformat)."""
    source_id: str
    search_id: str
    source_type: str
    authority_level: str
    kallidentitet: str
    datum: str = ""
    gallande_period_from: str = ""
    gallande_period_to: str = ""
    kalltext: str = ""
    hash: str = ""
    hamtningsstatus: str = "EJ_HÄMTAD"
    verifieringsstatus: str = "BLOCKED"
    relevans_for_arendet: str = "EJ_BEDÖMD"
    retrieval_evidence: str = ""
    blocking_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "search_id": self.search_id,
            "source_type": self.source_type,
            "authority_level": self.authority_level,
            "kallidentitet": self.kallidentitet,
            "datum": self.datum,
            "gallande_period_from": self.gallande_period_from,
            "gallande_period_to": self.gallande_period_to,
            "kalltext": self.kalltext[:2000],
            "hash": self.hash,
            "hamtningsstatus": self.hamtningsstatus,
            "verifieringsstatus": self.verifieringsstatus,
            "relevans_for_arendet": self.relevans_for_arendet,
            "retrieval_evidence": self.retrieval_evidence,
            "blocking_reason": self.blocking_reason,
        }


@dataclass
class LegalIssue:
    """Rättslig fråga – identifieras dynamiskt från ärendematerialet."""
    issue_id: str
    rattfraga: str
    rattsomrade: str
    source_hint: str = ""
    claims: List[str] = field(default_factory=list)
    relevans: str = "EJ_BEDÖMD"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "rattfraga": self.rattfraga,
            "rattsomrade": self.rattsomrade,
            "source_hint": self.source_hint,
            "claims": self.claims[:20],
            "relevans": self.relevans,
        }


# ─────────────────────────────────────────────────────────────────────────────
# RÄTTSKÄLLEKEDJA (STEG 13 §4) – maskinläsbar kedja med stabila ID
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ChainLink:
    """Ett steg i rättskällekedjan CASE → … → CONSEQUENCE."""
    chain_id: str
    step: str
    value: str = ""
    prev_id: str = ""
    next_id: str = ""
    source_ref: str = ""
    status: str = "EJ_VERIFIERAT"
    evidence: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "step": self.step,
            "value": self.value[:200],
            "prev_id": self.prev_id,
            "next_id": self.next_id,
            "source_ref": self.source_ref,
            "status": self.status,
            "evidence": self.evidence[:200],
        }


# ─────────────────────────────────────────────────────────────────────────────
# TVÅSTEGSVERIFIERING (STEG 13 §3)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class TwoStageVerification:
    """Tvåstegsverifiering: PÅSTÅENDE → ANGIVEN KÄLLA → PRIMÄRKÄLLA →
    HISTORISK LYDELSE → ÄNDRINGSFÖRFATTNING → RELEVANT PRAXIS → VERIFIERAD."""
    verification_id: str
    paestaende: str = ""
    angiven_kalla: str = ""
    primarkalla: str = ""
    historisk_lydelse_vid_datum: str = ""
    andringsforfattning: str = ""
    relevant_praxis: str = ""
    slutstatus: str = "EJ VERIFIERAD"
    blocking_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verification_id": self.verification_id,
            "paestaende": self.paestaende[:300],
            "angiven_kalla": self.angiven_kalla,
            "primarkalla": self.primarkalla,
            "historisk_lydelse_vid_datum": self.historisk_lydelse_vid_datum,
            "andringsforfattning": self.andringsforfattning,
            "relevant_praxis": self.relevant_praxis,
            "slutstatus": self.slutstatus,
            "blocking_reason": self.blocking_reason,
        }


# ─────────────────────────────────────────────────────────────────────────────
# SUBSUMTION (STEG 13 §5)
# ─────────────────────────────────────────────────────────────────────────────


class SubsumtionStatus:
    UPPFYLLT = "UPPFYLLT"
    EJ_UPPFYLLT = "EJ UPPFYLLT"
    EJ_VERIFIERAT = "EJ VERIFIERAT"
    MOTSAGS = "MOTSÄGS"
    EJ_AVGORBART = "EJ AVGÖRBART"


@dataclass
class SubsumtionEntry:
    """Subsumtionspost för ett rekvisit."""
    subsumtion_id: str
    rule_id: str
    requisite_text: str
    rattfakta_krav: str = ""
    bevisning: str = ""
    motbevisning: str = ""
    bevisstatus: str = "EJ ANGIVET"
    status: str = SubsumtionStatus.EJ_VERIFIERAT
    source_ref: str = ""
    blocking_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subsumtion_id": self.subsumtion_id,
            "rule_id": self.rule_id,
            "requisite_text": self.requisite_text,
            "rattfakta_krav": self.rattfakta_krav,
            "bevisning": self.bevisning,
            "motbevisning": self.motbevisning,
            "bevisstatus": self.bevisstatus,
            "status": self.status,
            "source_ref": self.source_ref,
            "blocking_reason": self.blocking_reason,
        }


# ─────────────────────────────────────────────────────────────────────────────
# DOMSKÄLSAUDIT (STEG 13 §6) – bidirectional
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class DomskalsAuditEntry:
    audit_id: str
    paestaende: str = ""
    kalla: str = ""
    primarkalla: str = ""
    rattsregel: str = ""
    rekvisit: str = ""
    rattsfakt: str = ""
    bevisning: str = ""
    domstolens_premiss: str = ""
    slutsats: str = ""
    reverse_kalla_anvandning: str = ""   # KÄLLA → DOMSTOLENS ANVÄNDNING
    status: str = "EJ AVGÖRBART"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "paestaende": self.paestaende[:300],
            "kalla": self.kalla,
            "primarkalla": self.primarkalla,
            "rattsregel": self.rattsregel,
            "rekvisit": self.rekvisit,
            "rattsfakt": self.rattfakt[:200],
            "bevisning": self.bevisning[:200],
            "domstolens_premiss": self.domstolens_premiss[:200],
            "slutsats": self.slutsats[:200],
            "reverse_kalla_anvandning": self.reverse_kalla_anvandning[:200],
            "status": self.status,
        }


# ─────────────────────────────────────────────────────────────────────────────
# KONTRADIKTORISK KONTROLL (STEG 13 §7)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ContraCheck:
    check_id: str
    typ: str
    beskrivning: str = ""
    status: str = "EJ_BEDÖMT"
    source_ref: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "typ": self.typ,
            "beskrivning": self.beskrivning[:200],
            "status": self.status,
            "source_ref": self.source_ref,
        }


# ─────────────────────────────────────────────────────────────────────────────
# HARD STOP (STEG 13 §8)
# ─────────────────────────────────────────────────────────────────────────────


class HardStopStatus:
    OTILLRACKLIGT = "OTILLRÄCKLIGT UNDERLAG – FÖRESLÅS KOMPLETTERING"


@dataclass
class HardStopEntry:
    stop_id: str
    betreffande: str = ""
    reason: str = ""
    status: str = HardStopStatus.OTILLRACKLIGT

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stop_id": self.stop_id,
            "betreffande": self.betreffande[:200],
            "reason": self.reason[:300],
            "status": self.status,
        }


# ─────────────────────────────────────────────────────────────────────────────
# SEARCH 01–10 (STEG 13 §2) – separata, klassificerade verifieringssteg
# ─────────────────────────────────────────────────────────────────────────────

SEARCH_SPEC = {
    "SEARCH_01": {"syfte": "Exakt lagrum", "source_type": "LAG", "authority_level": "BINDANDE"},
    "SEARCH_02": {"syfte": "Aktuell och historisk lydelse vid relevant datum", "source_type": "FÖRORDNING", "authority_level": "BINDANDE"},
    "SEARCH_03": {"syfte": "Förarbeten", "source_type": "FÖRARBETE", "authority_level": "INFORMERANDE"},
    "SEARCH_04": {"syfte": "HD-prejudikat", "source_type": "PREJUDIKAT", "authority_level": "PREJUDIKATIV"},
    "SEARCH_05": {"syfte": "HFD-prejudikat", "source_type": "PREJUDIKAT", "authority_level": "PREJUDIKATIV"},
    "SEARCH_06": {"syfte": "Relevant överrättspraxis", "source_type": "ÖVERRÄTT", "authority_level": "VÄGLEDANDE"},
    "SEARCH_07": {"syfte": "EU-domstolen", "source_type": "EU", "authority_level": "VÄGLEDANDE"},
    "SEARCH_08": {"syfte": "Europadomstolen (EKMR)", "source_type": "EKMR", "authority_level": "VÄGLEDANDE"},
    "SEARCH_09": {"syfte": "Speciallagstiftning och myndighetsföreskrifter", "source_type": "MYNDIGHET", "authority_level": "VÄGLEDANDE"},
    "SEARCH_10": {"syfte": "Senare praxis som förändrat eller preciserat rättsläget", "source_type": "ÖVERRÄTT", "authority_level": "VÄGLEDANDE"},
}


# ─────────────────────────────────────────────────────────────────────────────
# DYNAMISK PROFILERING (STEG 13 §1) – signalord, ej juridisk mall
# ─────────────────────────────────────────────────────────────────────────────

RATTSOMRADE_SIGNALS = {
    "straffrätt": ["brott", "åklagare", "misstanke", "förundersökning", "polisförhör",
                   "brb", "brottsbalk", "straff", "tingsrätt_brott", "sexualbrott",
                   "sexuellt", "våldtäkt", "ofredande", "särskild företrädare"],
    "förvaltningsrätt": ["förvaltningsrätt", "kammarrätt", "hfd", "försäkringskassan",
                         "sfb", "sjukpenning", "sol", "lvu", "lvm", "socialnämnd"],
    "tvistemål": ["tvistemål", "hyresrätt", "skadestånd", "edition", "stämningsansökan",
                  "avtal", "fordran", "betalningsföreläggande"],
    "skatterätt": ["skatt", "skatteverket", "taxering", "mervärdesskatt", "lag (2001:1227)"],
}

PROCESSFORM_SIGNALS = {
    "BROTTMÅL": ["åklagare", "misstänkt", "förundersökning", "fup", "delgivning av misstanke",
                 "särskild företrädare", "strafflindring"],
    "TVISTEMÅL": ["kärande", "svarande", "stämningsansökan", "tvist", "fordran"],
    "FÖRVALTNINGSMÅL": ["förvaltningsrätt", "överklagande", "besvär", "part"],
}

MALTYP_SIGNALS = {
    "BROTTMÅL_SEXUALBROTT": ["våldtäkt", "sexuellt ofredande", "sexuellt övergrepp", "sexualbrott"],
    "BROTTMÅL_VALDSBROTT": ["misshandel", "vållande", "olaga hot"],
    "BROTTMÅL_FORMOGENHETSBROTT": ["stöld", "häleri", "bedrägeri", "förskingring", "skadegörelse"],
    "TVISTEMÅL_FORMOGEN": ["fordran", "avtal", "skadestånd", "faktura"],
    "FÖRVALTNINGSMÅL_SOCIAL": ["socialnämnd", "lvu", "sol", "försörjningsstöd"],
    "FÖRVALTNINGSMÅL_FÖRSÄKRING": ["sjukpenning", "sfb", "arbetsförmåga", "rehabilitering"],
}

LAGRUM_RE = re.compile(
    r"(\d{1,2}\s*kap(?:\.|:)?\s*\d{1,3}\s*§|\d{1,2}:\d{1,3}|"      # 6 kap. 4 § / 6:4
    r"\d{1,3}\s*§\s*(?:brottsbalken|brb|rättegångsbalken|rb)|"
    r"(?:brb|rb|osl|sekretesslagen|fuk)\s*\d{1,3}\s*§)")


def _count_signals(text_lower: str, signals: List[str]) -> int:
    return sum(1 for sig in signals if sig in text_lower)


# ─────────────────────────────────────────────────────────────────────────────
# STEG 13 PRODUKTIONSMOTOR – HUVUDKLASSEN
# ─────────────────────────────────────────────────────────────────────────────


class Steg13DynamicEngine:
    """STEG 13 produktionsmotor – faktisk dynamisk rättskälle- och juridikanalys."""

    def __init__(self, case_id: str, run_id: str = "", enable_network: bool = False,
                 relevant_date: str = "") -> None:
        self.case_id = case_id
        self.run_id = run_id
        self.enable_network = enable_network
        self.relevant_date = relevant_date or datetime.date.today().isoformat()
        self.log: List[str] = []
        self.legal_issues: List[LegalIssue] = []
        self.sources: List[RattkalleObjekt] = []
        self.verifications: List[TwoStageVerification] = []
        self.subsumptions: List[SubsumtionEntry] = []
        self.domskals_audit: List[DomskalsAuditEntry] = []
        self.contra_checks: List[ContraCheck] = []
        self.hard_stops: List[HardStopEntry] = []
        self.chain: List[ChainLink] = []
        self.rattsomrade = "EJ IDENTIFIERAT"
        self.processform = "EJ IDENTIFIERAD"
        self.maltyp = "EJ IDENTIFIERAD"
        self._issues_created = 0
        self._sources_created = 0
        self._verifications_created = 0
        self._subsumptions_created = 0
        self._audit_created = 0
        self._contra_created = 0
        self._stops_created = 0
        self._chain_created = 0

    def _log(self, msg: str) -> None:
        entry = f"[STEG13:{self.run_id}] {msg}"
        self.log.append(entry)
        print(entry)

    def _utc(self) -> str:
        return datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z"

    @staticmethod
    def _sha256(text: str) -> str:
        return hashlib.sha256((text or "").encode("utf-8")).hexdigest()

    # ── L06: DYNAMISK PROFILERING ───────────────────────────────
    def profile_case_dynamically(self, claims: List[Any]) -> None:
        """Identifierar rättsområde, processform och måltyp DYNAMISKT från
        ärendematerialets claims – ingen hårdkodad juridisk mall."""
        def _get(c, key, default=""):
            """Säker attribut/dict-access för både dataclass och dict."""
            v = getattr(c, key, None)
            if v is not None:
                return v
            if isinstance(c, dict):
                return c.get(key, default)
            return default
        text_lower = " ".join(str(_get(c, "content", "")).lower() for c in claims)
        best = None
        best_count = 0
        for area, signals in RATTSOMRADE_SIGNALS.items():
            cnt = _count_signals(text_lower, signals)
            if cnt > best_count:
                best_count = cnt
                best = area
        self.rattsomrade = best if best else "EJ IDENTIFIERAT"

        best = None
        best_count = 0
        for form, signals in PROCESSFORM_SIGNALS.items():
            cnt = _count_signals(text_lower, signals)
            if cnt > best_count:
                best_count = cnt
                best = form
        self.processform = best if best else "EJ IDENTIFIERAD"

        best = None
        best_count = 0
        for mt, signals in MALTYP_SIGNALS.items():
            cnt = _count_signals(text_lower, signals)
            if cnt > best_count:
                best_count = cnt
                best = mt
        self.maltyp = best if best else "EJ IDENTIFIERAD"

        self._log(
            f"L06 Dynamisk profilering: rättsområde={self.rattsomrade} "
            f"processform={self.processform} måltyp={self.maltyp} "
            f"(signalträffar: {best_count} i {len(claims)} claims)"
        )

    # ── L06: RÄTTSFRÅGEIDENTIFIERING ────────────────────────────
    def extract_legal_issues(self, claims: List[Any]) -> List[LegalIssue]:
        """Extraherar rättsfrågor dynamiskt från claims: lagrumssignaler och
        brottsrubricering/text i ärendet. Inte en förutbestämd mall."""
        def _get(c, key, default=""):
            v = getattr(c, key, None)
            if v is not None:
                return v
            if isinstance(c, dict):
                return c.get(key, default)
            return default
        issues: List[LegalIssue] = []
        hints: Dict[str, List[str]] = {}

        for c in claims:
            txt = str(_get(c, "content", ""))
            claim_id = str(_get(c, "claim_id", "?"))
            for m in LAGRUM_RE.finditer(txt):
                hint = m.group(0).strip()
                hints.setdefault(hint, []).append(claim_id)

        text_lower = " ".join(str(_get(c, "content", "")).lower() for c in claims)
        # SFCAE-PORT: källan hårdkodade rättsfrågor för ett specifikt ärende
        # (BrB 6:4 / 6:10 / RB 35:1 utlösta av ord i texten). Det strider mot
        # STEG 12/13:s egen regel "ingen hårdkodad juridisk slutsats".
        # Rättsfrågor härleds nu ENDAST ur lagrumshänvisningar som faktiskt
        # förekommer i materialet; rättsområdet tas från den dynamiska
        # profileringen.
        _ = text_lower
        rattfraga_candidates = [
            (f"rättsfråga kopplad till lagrum {hint}",
             self.rattsomrade if self.rattsomrade != "EJ IDENTIFIERAT" else "obestämt")
            for hint in hints
        ]

        for i, (fraga, omrade) in enumerate(rattfraga_candidates[:12], 1):
            self._issues_created += 1
            issue_id = f"LI-{self._issues_created:03d}"
            claim_ids = []
            for hint, cids in hints.items():
                if hint in fraga:
                    claim_ids.extend(cids)
            clues = [k for k in hints if k]
            issues.append(LegalIssue(
                issue_id=issue_id, rattfraga=fraga, rattsomrade=omrade,
                source_hint=clues[0] if clues else "",
                claims=claim_ids[:30], relevans="RÄTTSLIGT RELEVANT",
            ))
        self.legal_issues.extend(issues)
        return issues

    # ── L07: SEARCH 01–10 – faktiska verifieringssteg ──────────
    def run_searches(self, rättsbegrepp: List[str]) -> Dict[str, Dict[str, Any]]:
        """Kör SEARCH_01–10 som SEPARATA verifieringssteg. Varje träff
        registreras som verifierbart rättskälleobjekt. Nätverksanrop aktiveras
        endast med enable_network=True. Utan nätverk: status REGISTER_SAKNAS
        – aldrig gissad eller fejklad."""
        results: Dict[str, Dict[str, Any]] = {}

        for search_id, spec in SEARCH_SPEC.items():
            hits: List[Dict[str, Any]] = []
            status = "REGISTER_SAKNAS"
            error = ""
            if self.enable_network:
                try:
                    import requests
                    for term in rättsbegrepp:
                        if not re.search(r"\d{6,8}-?\d{4}", term):
                            hits, status, error = self._live_search(search_id, term, spec)
                            if hits:
                                break
                except Exception as e:  # pragma: no cover
                    status = "VARNING"
                    error = str(e)[:200]

            registrations = 0
            for h in hits[:5]:
                self._sources_created += 1
                src = RattkalleObjekt(
                    source_id=f"LS13-{search_id}-{self._sources_created:04d}",
                    search_id=search_id,
                    source_type=spec["source_type"],
                    authority_level=spec["authority_level"],
                    kallidentitet=h.get("identitet", ""),
                    datum=h.get("datum", ""),
                    gallande_period_from=h.get("from", ""),
                    gallande_period_to=h.get("to", ""),
                    kalltext=h.get("text", ""),
                    hash=h.get("hash", "") or self._sha256(h.get("text", "")),
                    hamtningsstatus="HÄMTAD" if h.get("text") else "EJ_HÄMTAD",
                    verifieringsstatus="VERIFIED" if (h.get("text") and h.get("verifierad")) else (
                        "PARTIAL" if h.get("text") else "BLOCKED"),
                    relevans_for_arendet="RÄTTSLIGT RELEVANT" if h.get("relevant") else "EJ BEDÖMD",
                    retrieval_evidence=h.get("url", ""),
                    blocking_reason=h.get("reason", ""),
                )
                self.sources.append(src)
                registrations += 1
            results[search_id] = {
                "search_id": search_id,
                "syfte": spec["syfte"],
                "source_type": spec["source_type"],
                "authority_level": spec["authority_level"],
                "status": status if status else ("HITTAD" if hits else "INGA_TRÄFFAR"),
                "error": error,
                "hits_count": len(hits),
                "registrerade_objekt": registrations,
                "network": self.enable_network,
            }
            self._log(
                f"L07 {search_id} ({spec['syfte']}) → status={results[search_id]['status']} "
                f"träffar={len(hits)} registrerade={registrations}"
            )
        return results

    # ── L07: LIVE-HÄMTNING mot faktiska register ───────────────
    def _live_search(self, search_id: str, term: str,
                     spec: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str, str]:
        """Faktisk hämtning via officiella API:er. Vid frånvaro av register:
        REGISTER_SAKNAS. En sökträff är ALDRIG en verifierad rättskälla."""
        import requests
        hits: List[Dict[str, Any]] = []
        try:
            if search_id in ("SEARCH_01", "SEARCH_02", "SEARCH_03", "SEARCH_09"):
                url = "https://data.riksdagen.se/dokumentlista/"
                doktyp = "sfs" if search_id in ("SEARCH_01", "SEARCH_02", "SEARCH_09") else "prop"
                params = {"doktyp": doktyp, "utformat": "json", "sz": "5", "sok": term}
                r = requests.get(url, params=params, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    docs = data.get("dokumentlista", {}).get("dokument", [])
                    if isinstance(docs, dict):
                        docs = [docs]
                    for d in docs[:5]:
                        ident = d.get("beteckning", "")
                        hits.append({
                            "identitet": ident,
                            "datum": d.get("datum", ""),
                            "text": d.get("titel", "") or "",
                            "url": f"https://data.riksdagen.se/dokument/{d.get('id', '')}",
                            "verifierad": False,
                            "relevant": bool(term.lower() in str(d.get("titel", "")).lower()
                                             or term.lower() in ident.lower()),
                            "reason": "sökträff – kräver primärkälleverifiering",
                        })
                return hits, "HITTAD", ""
            elif search_id == "SEARCH_10":
                url = "https://api.crossref.org/works"
                r = requests.get(url, params={"rows": "3", "query": term,
                                              "select": "DOI,title,published,type"}, timeout=15)
                if r.status_code == 200:
                    works = r.json().get("message", {}).get("items", [])
                    for w in works[:3]:
                        title = (w.get("title") or [""])[0]
                        date = str(w.get("published", {}).get("date-parts", [[""]])[0][0])
                        hits.append({
                            "identitet": w.get("DOI", ""),
                            "datum": date,
                            "text": title or "",
                            "url": f"https://doi.org/{w.get('DOI', '')}",
                            "verifierad": False,
                            "relevant": bool(term.lower() in (title or "").lower()),
                            "reason": "sökträff (doktrin/meta) – förhandsgranskning krävs",
                        })
                return hits, "HITTAD", ""
            elif search_id in ("SEARCH_04", "SEARCH_05", "SEARCH_06",
                               "SEARCH_07", "SEARCH_08"):
                return [], "REGISTER_SAKNAS", (
                    "officiellt rättspraxisregister ej monterat i denna miljö (ärlig status)")
            return [], "REGISTER_SAKNAS", f"ej stödd sökning {search_id}"
        except Exception as e:
            return [], "VARNING", str(e)[:200]

    # ── L07: KONVERTERA BEFINTLIGA LEGAL_SOURCES TILL RATTKALLEOBJEKT
    def identifiera_fran_existerande(self, legal_sources: List[Any]) -> None:
        """Konverterar redan identifierade LegalSourceRecord-objekt (från L7
        i kanonisk pipeline) till RattkalleObjekt för STEG 13.
        Ingen dubblering om objektet redan finns (kontrolleras på source_id)."""
        for src in legal_sources:
            sid = getattr(src, "source_id", "")
            if any(s.source_id == sid for s in self.sources):
                continue
            self._sources_created += 1
            self.sources.append(RattkalleObjekt(
                source_id=sid or f"LS13-EXIST-{self._sources_created:04d}",
                search_id=getattr(src, "search_id", "") or "EXIST_L7",
                source_type=getattr(src, "source_type", ""),
                authority_level=getattr(src, "authority_level", ""),
                kallidentitet=(
                    f"{getattr(src, 'reference', '')} "
                    f"({getattr(src, 'source_type', '')})"
                ).strip(),
                datum=getattr(src, "date", ""),
                gallande_period_from="",
                gallande_period_to="",
                kalltext=getattr(src, "holding", "") or getattr(
                    src, "legal_issue", ""),
                hash=self._sha256(
                    getattr(src, "holding", "") + getattr(src, "reference", "")
                ),
                hamtningsstatus=(
                    "VERIFIED" if getattr(src, "official_source", "") == "VERIFIED"
                    else "EJ_HÄMTAD"
                ),
                verifieringsstatus=(
                    "VERIFIED" if getattr(src, "official_source", "") == "VERIFIED"
                    else "BLOCKED"
                ),
                relevans_for_arendet=(
                    "BEDÖMD" if getattr(src, "legal_issue", "") else "EJ_BEDÖMD"
                ),
                retrieval_evidence=getattr(src, "search_domain", ""),
                blocking_reason=getattr(src, "blocking_reason", ""),
            ))

    # ── L08: TVÅSTEGSVERIFIERING (STEG 13 §3) ──────────────────
    def two_stage_verify(self, sources: List[Any], requisite_entries: List[Any],
                         case_claims: List[Any]) -> List[TwoStageVerification]:
        """För varje angiven rättskälla: länka primärkälla, historisk lydelse
        (vid relevant datum), ändringsförfattning, relevant praxis. PROVED
        sätts ALDRIG här – det sker först i finalize_proved när hela kedjan
        är komplett."""
        out: List[TwoStageVerification] = []
        by_id: Dict[str, Any] = {getattr(s, "source_id", ""): s for s in sources}
        for src in sources:
            self._verifications_created += 1
            v = TwoStageVerification(
                verification_id=f"V13-{self._verifications_created:04d}",
                paestaende=(
                    getattr(src, "legal_issue", "")
                    or getattr(src, "holding", "")
                    or "Påstående ej specificerat"
                ),
                angiven_kalla=(
                    f"{getattr(src, 'reference', '')} "
                    f"({getattr(src, 'source_type', '')})"
                ).strip(),
                primarkalla=(
                    f"{getattr(src, 'court', '')} "
                    f"{getattr(src, 'case_number', '')}"
                ).strip(),
                historisk_lydelse_vid_datum=(
                    f"datum={getattr(src, 'date', '')}; "
                    f"period={getattr(src, 'gallande_period_from', '')}→"
                    f"{getattr(src, 'gallande_period_to', '')}"
                ),
                andringsforfattning="EJ SÖKT" if not getattr(src, "search_id", "") else (
                    "SÖKT via " + src.search_id),
                relevant_praxis=(
                    f"holding_verification={getattr(src, 'holding_verification', '')}"
                ),
                slutstatus="EJ VERIFIERAD",  # sätts aldrig till PROVED här
            )
            # Bättre primärkälla för SFS/prop-träffar
            if (getattr(src, "source_type", "") in ("LAG", "FÖRORDNING", "FÖRARBETE")
                    and getattr(src, "official_source", "") == "VERIFIED"):
                v.primarkalla = (
                    f"https://data.riksdagen.se – "
                    f"{getattr(src, 'reference', '')}"
                )
            # Förstärk historisk lydelse från STEG 12-data
            if getattr(src, "current_status", "") == "REQUIRES_SEARCH_01_VERIFICATION":
                v.historisk_lydelse_vid_datum = (
                    "EJ BEKRÄFTAD – kräver SEARCH_01 mot primärkälla"
                )
            # Blockering om källan är blockerad
            if getattr(src, "blocked_from_requisites", False):
                v.slutstatus = "BLOCKED"
                v.blocking_reason = getattr(src, "blocking_reason", "RT-BO")
            out.append(v)
        self.verifications.extend(out)
        return out

    # ── L08: SUBSUMTION (STEG 13 §5) ────────────────────────────
    def subsumera_requisites(self, requisite_entries: List[Any],
                             legal_sources: List[Any],
                             case_claims: List[Any]) -> List[SubsumtionEntry]:
        """För varje rekvisit: länka RULE_ID, REQUISITE_ID, rättsfakta, bevisning,
        motbevisning, bevisstatus, källa. PROVED sätts inte här."""
        out: List[SubsumtionEntry] = []
        # Mappa claims efter ID för att hitta motbevisning
        def _get(c, key, default=""):
            v = getattr(c, key, None)
            if v is not None:
                return v
            if isinstance(c, dict):
                return c.get(key, default)
            return default
        claims_by_id: Dict[str, Any] = {}
        for c in case_claims:
            cid = _get(c, "claim_id", "")
            if cid:
                claims_by_id[cid] = c

        # Mappa legal source per ID
        src_by_id: Dict[str, Any] = {
            getattr(s, "source_id", ""): s for s in legal_sources}

        for req in requisite_entries:
            self._subsumptions_created += 1
            claim_id = getattr(req, "claim_id", "NOT_VERIFIABLE")
            source_ref = getattr(req, "source_ref", "")
            claim = claims_by_id.get(claim_id)
            evidence_text = (
                getattr(claim, "content", "") if claim is not None else ""
            )
            contra_text = ""
            # Sök i claims efter motpåståenden (CONTRADICTS-kanter)
            for c in case_claims:
                if getattr(c, "claim_id", "") == claim_id:
                    continue
                # Heuristik: claim som innehåller ordet "inte" eller "förnekar"
                # i samma fil kan vara motbevisning.
                ct = (getattr(c, "content", "") or "").lower()
                if ct and any(
                    w in ct for w in ("inte", "förnekar", "bestrider", "motsäger",
                                      "tillbakavisar")
                ):
                    contra_text = (contra_text + " | " + ct[:150]).strip(" |")
            # Välj källa för subsumtionen
            matched_source = src_by_id.get(source_ref.split("|")[0].strip(), None)
            source_for_sub = source_ref
            if matched_source is not None:
                source_for_sub = (
                    f"{getattr(matched_source, 'reference', '')} | "
                    f"{getattr(matched_source, 'source_type', '')} | "
                    f"{getattr(matched_source, 'date', '')}"
                )

            entry = SubsumtionEntry(
                subsumtion_id=f"SUBS13-{self._subsumptions_created:04d}",
                rule_id=(
                    f"BRB-6-{getattr(req, 'requisite_text', '')[:20]}"
                    if "brott" in (getattr(req, "requisite_text", "") or "").lower()
                    else f"RULE-{self._subsumptions_created:03d}"
                ),
                requisite_text=getattr(req, "requisite_text", ""),
                rattfakta_krav=getattr(req, "requisite_text", ""),
                bevisning=evidence_text[:300],
                motbevisning=contra_text[:300],
                bevisstatus=(
                    "STYRK" if getattr(req, "status", None) is not None
                    and str(getattr(req, "status", "")).endswith("UPPFYLLT")
                    else "EJ STYRK"
                ),
                status=SubsumtionStatus.EJ_VERIFIERAT,  # PROVED sätts ej här
                source_ref=source_for_sub,
                blocking_reason=(
                    "BEVISNING_SAKNAS"
                    if getattr(req, "status", None) is not None
                    and str(getattr(req, "status", "")).endswith("SAKNAS")
                    else ""
                ),
            )
            # Mappa status från v10-requisitstatus om tillgänglig
            st = getattr(req, "status", None)
            if st is not None:
                stv = str(st)
                if "UPPFYLLT" in stv or stv == "OBESTRITT":
                    entry.status = SubsumtionStatus.UPPFYLLT
                elif "TVISTIGT" in stv:
                    entry.status = SubsumtionStatus.EJ_AVGORBART
                elif "SAKNAS" in stv:
                    entry.status = SubsumtionStatus.EJ_VERIFIERAT
                    entry.blocking_reason = "BEVISNING_SAKNAS (RT-BF)"
            out.append(entry)
        self.subsumptions.extend(out)
        return out

    # ── L08: DOMSKÄLSAUDIT (STEG 13 §6) – bidirectional ───────
    def audit_domskal(self, subsumptions: List[SubsumtionEntry],
                      case_claims: List[Any]) -> List[DomskalsAuditEntry]:
        """Bidirectional: påstående ↔ källa ↔ primärkälla ↔ rättsregel ↔
        rekvisit ↔ rättsfakt ↔ bevisning ↔ domstolens premiss ↔ slutsats."""
        out: List[DomskalsAuditEntry] = []
        claims_by_id: Dict[str, Any] = {
            getattr(c, "claim_id", ""): c for c in case_claims}
        for sub in subsumptions:
            self._audit_created += 1
            claim_id = ""
            for cid, c in claims_by_id.items():
                if cid and cid in sub.bevisning:
                    claim_id = cid
                    break
            entry = DomskalsAuditEntry(
                audit_id=f"AUD13-{self._audit_created:04d}",
                paestaende=(sub.requisite_text or "")[:200],
                kalla=sub.source_ref,
                primarkalla=(
                    sub.source_ref.split("|")[0].strip()
                    if "|" in sub.source_ref else sub.source_ref
                ),
                rattsregel=sub.rule_id,
                rekvisit=sub.requisite_text,
                rattsfakt=sub.rattfakta_krav,
                bevisning=sub.bevisning,
                domstolens_premiss="DOM SAKNAS – endast förundersökningsprotokoll",
                slutsats="KAN EJ AVGÖRAS (HS01A) – dom krävs för fullständig audit",
                reverse_kalla_anvandning=(
                    f"källa={sub.source_ref[:120]} → "
                    f"rekvisit={sub.requisite_text[:60]}"
                ),
                status="EJ AVGÖRBART",
            )
            out.append(entry)
        self.domskals_audit.extend(out)
        return out

    # ── L08: KONTRADIKTORISK KONTROLL (STEG 13 §7) ─────────────
    def contradictorisk_kontroll(self, case_claims: List[Any],
                                 subsumptions: List[SubsumtionEntry]
                                 ) -> List[ContraCheck]:
        """För varje subsumtion: registrera motpåståenden, alternativa
        kvalifikationer, saknade motargument."""
        out: List[ContraCheck] = []
        for sub in subsumptions:
            self._contra_created += 1
            motsager = bool(sub.motbevisning)
            out.append(ContraCheck(
                check_id=f"CC13-{self._contra_created:04d}",
                typ="MOTPÅSTÅENDE",
                beskrivning=(
                    sub.motbevisning[:200] if motsager
                    else "Inga explicita motpåståenden registrerade i claims"
                ),
                status="MOTSÄGS" if motsager else "EJ_MOTSAGT",
                source_ref=sub.source_ref,
            ))
        # SFCAE-PORT: källan registrerade ovillkorligen "BrB 6:4 vs 6:10
        # PRÖVAD" och "FUP-SAKNAS" — påståenden om ett visst ärende som inte
        # vilade på materialet. Nu: alternativ kvalifikation redovisas bara när
        # minst två olika lagrum faktiskt förekommer, och då som EJ_PRÖVAD.
        _lagrum = sorted({i.source_hint for i in self.legal_issues if i.source_hint})
        if len(_lagrum) >= 2:
            self._contra_created += 1
            out.append(ContraCheck(
                check_id=f"CC13-{self._contra_created:04d}",
                typ="ALTERNATIV_KVALIFIKATION",
                beskrivning=("Flera lagrum förekommer i materialet: "
                             + ", ".join(_lagrum[:6])
                             + " — alternativ kvalifikation kräver manuell prövning"),
                status="EJ_PRÖVAD",
                source_ref="REKV-MATRIS",
            ))
        if not any(c.status == "MOTSÄGS" for c in out):
            self._contra_created += 1
            out.append(ContraCheck(
                check_id=f"CC13-{self._contra_created:04d}",
                typ="SAKNAT_MOTARGUMENT",
                beskrivning=("Inga motpåståenden har kunnat registreras ur "
                             "materialet — frånvaro av motargument är inte "
                             "verifierad frånvaro"),
                status="EJ_VERIFIERAT",
                source_ref="MATERIAL",
            ))
        self.contra_checks.extend(out)
        return out

    # ── HARD STOP MASKINELL KONTROLL (STEG 13 §8) ──────────────
    def apply_hard_stops(self, subsumptions: List[SubsumtionEntry],
                         verifications: List[TwoStageVerification],
                         sources: List[Any]) -> List[HardStopEntry]:
        """Maskinell HARD-STOP-kontroll: får endast utlösas om något av
        legal_source_missing, historical_version_required/missing,
        requisite_source_missing, evidence_link_missing,
        subsumption_basis_missing, provenance_chain_incomplete."""
        out: List[HardStopEntry] = []
        for v in verifications:
            if v.slutstatus == "BLOCKED":
                self._stops_created += 1
                out.append(HardStopEntry(
                    stop_id=f"HS13-{self._stops_created:03d}",
                    betreffande=f"verifiering {v.verification_id}",
                    reason=(
                        "legal_source_missing: "
                        f"{v.angiven_kalla} blockerad ({v.blocking_reason})"
                    ),
                ))

        for s in sources:
            if (getattr(s, "current_status", "") ==
                    "REQUIRES_SEARCH_01_VERIFICATION"):
                self._stops_created += 1
                out.append(HardStopEntry(
                    stop_id=f"HS13-{self._stops_created:03d}",
                    betreffande=f"källa {getattr(s, 'source_id', '')}",
                    reason=(
                        "historical_version_required_and_missing: "
                        f"referens={getattr(s, 'reference', '')}"
                    ),
                ))

        for sub in subsumptions:
            if sub.status == SubsumtionStatus.EJ_VERIFIERAT and not sub.source_ref:
                self._stops_created += 1
                out.append(HardStopEntry(
                    stop_id=f"HS13-{self._stops_created:03d}",
                    betreffande=f"subsumtion {sub.subsumtion_id}",
                    reason=(
                        "requisite_source_missing: "
                        "rekvisit saknar källhänvisning"
                    ),
                ))
            if sub.status == SubsumtionStatus.EJ_VERIFIERAT and not sub.bevisning:
                self._stops_created += 1
                out.append(HardStopEntry(
                    stop_id=f"HS13-{self._stops_created:03d}",
                    betreffande=f"subsumtion {sub.subsumtion_id}",
                    reason=(
                        "evidence_link_missing: "
                        "subsumtion saknar bevisning"
                    ),
                ))
            if sub.status == SubsumtionStatus.EJ_VERIFIERAT and not sub.rattfakta_krav:
                self._stops_created += 1
                out.append(HardStopEntry(
                    stop_id=f"HS13-{self._stops_created:03d}",
                    betreffande=f"subsumtion {sub.subsumtion_id}",
                    reason=(
                        "subsumption_basis_missing: "
                        "subsumtion saknar rättsfaktakrav"
                    ),
                ))

        if not out:
            self._stops_created += 1
            out.append(HardStopEntry(
                stop_id=f"HS13-{self._stops_created:03d}",
                betreffande="provenance",
                reason=(
                    "provenance_chain_incomplete: fullständig CASE→…→"
                    "CONSEQUENCE-kedja krävs för PROVED"
                ),
            ))
        self.hard_stops.extend(out)
        return out

    # ── PROVENANCE-KEDJA STEG 1/2 (CASE → … → LEGAL_FACT) ────
    def _bygg_kedja_del1(self, case_id: str,
                         legal_issues: List[LegalIssue],
                         sources: List[Any],
                         verifications: List[TwoStageVerification],
                         subsumptions: List[SubsumtionEntry]
                         ) -> List[ChainLink]:
        chain: List[ChainLink] = []
        chain.append(ChainLink(
            chain_id="CASE-0",
            step="CASE",
            value=case_id,
            next_id="LI-001" if legal_issues else "",
            status="OK",
            evidence=f"case_id={case_id}; run_id={self.run_id}",
        ))
        for i, li in enumerate(legal_issues[:3], 1):
            chain.append(ChainLink(
                chain_id=f"LI-{i:03d}",
                step="LEGAL_ISSUE",
                value=li.rattfraga,
                prev_id="CASE-0" if i == 1 else f"LI-{i-1:03d}",
                next_id=f"LS-{i:03d}",
                source_ref=li.source_hint,
                status="OK",
                evidence=f"issue_id={li.issue_id}",
            ))
        for i, s in enumerate(sources[:3], 1):
            chain.append(ChainLink(
                chain_id=f"LS-{i:03d}",
                step="LEGAL_SOURCE",
                value=getattr(s, "reference", "") or getattr(s, "source_id", ""),
                prev_id=f"LI-{i:03d}" if legal_issues else "CASE-0",
                next_id=f"V13-{i:04d}",
                source_ref=getattr(s, "source_id", ""),
                status=("OK" if getattr(s, "official_source", "") == "VERIFIED"
                        else "PARTIAL"),
                evidence=(
                    f"type={getattr(s, 'source_type', '')}; "
                    f"auth={getattr(s, 'authority_level', '')}"
                ),
            ))
        for i, v in enumerate(verifications[:3], 1):
            chain.append(ChainLink(
                chain_id=f"V13-{i:04d}",
                step="VERSION",
                value=v.historisk_lydelse_vid_datum,
                prev_id=f"LS-{i:03d}" if i <= len(sources[:3]) else "CASE-0",
                next_id=f"RULE-{i:03d}",
                source_ref=v.angiven_kalla,
                status="OK" if v.slutstatus != "BLOCKED" else "BLOCKED",
                evidence=f"verification_id={v.verification_id}",
            ))
        for i, sub in enumerate(subsumptions[:3], 1):
            chain.append(ChainLink(
                chain_id=f"RULE-{i:03d}",
                step="RULE",
                value=sub.rule_id,
                prev_id=f"V13-{i:04d}" if i <= len(verifications[:3]) else "CASE-0",
                next_id=f"REQ-{i:03d}",
                source_ref=sub.source_ref,
                status="OK",
                evidence=f"subsumtion_id={sub.subsumtion_id}",
            ))
        for i, sub in enumerate(subsumptions[:3], 1):
            chain.append(ChainLink(
                chain_id=f"REQ-{i:03d}",
                step="REQUISITE",
                value=sub.requisite_text,
                prev_id=f"RULE-{i:03d}",
                next_id=f"LF-{i:03d}",
                source_ref=sub.source_ref,
                status="OK" if sub.rattfakta_krav else "PARTIAL",
                evidence=f"requisite={sub.requisite_text[:60]}",
            ))
        for i, sub in enumerate(subsumptions[:3], 1):
            chain.append(ChainLink(
                chain_id=f"LF-{i:03d}",
                step="LEGAL_FACT",
                value=sub.rattfakta_krav,
                prev_id=f"REQ-{i:03d}",
                next_id=f"EV-{i:03d}",
                source_ref=sub.source_ref,
                status="OK",
                evidence=f"bevisstatus={sub.bevisstatus}",
            ))
        return chain

    # ── PROVENANCE-KEDJA STEG 2/2 (EVIDENCE → … → CONSEQUENCE) ─
    def _bygg_kedja_del2(self, subsumptions: List[SubsumtionEntry],
                         hard_stops: List[HardStopEntry]
                         ) -> List[ChainLink]:
        chain: List[ChainLink] = []
        for i, sub in enumerate(subsumptions[:3], 1):
            chain.append(ChainLink(
                chain_id=f"EV-{i:03d}",
                step="EVIDENCE",
                value=sub.bevisning,
                prev_id=f"LF-{i:03d}",
                next_id=f"SUB-{i:03d}",
                source_ref=sub.source_ref,
                status="OK" if sub.bevisning else "PARTIAL",
                evidence=f"motbevis={'JA' if sub.motbevisning else 'NEJ'}",
            ))
        for i, sub in enumerate(subsumptions[:3], 1):
            chain.append(ChainLink(
                chain_id=f"SUB-{i:03d}",
                step="SUBSUMPTION",
                value=sub.status,
                prev_id=f"EV-{i:03d}",
                next_id=f"CON-{i:03d}",
                source_ref=sub.source_ref,
                status=("PROVED" if (sub.status == SubsumtionStatus.UPPFYLLT
                                     and sub.bevisning
                                     and sub.rattfakta_krav
                                     and not hard_stops)
                        else "EJ VERIFIERAT"),
                evidence=(
                    f"bevisstatus={sub.bevisstatus}; "
                    f"blocking={sub.blocking_reason or '—'}"
                ),
            ))
        for i, sub in enumerate(subsumptions[:3], 1):
            chain.append(ChainLink(
                chain_id=f"CON-{i:03d}",
                step="CONSEQUENCE",
                value=(
                    "RÄTTSLIG FÖLJD: bevistemat viktat enligt subsumtion"
                    if sub.status == SubsumtionStatus.UPPFYLLT
                    else "RÄTTSLIG FÖLJD: kan ej dras (HS01A/HS11)"
                ),
                prev_id=f"SUB-{i:03d}",
                source_ref=sub.source_ref,
                status=("OK" if (sub.status == SubsumtionStatus.UPPFYLLT
                                 and sub.bevisning
                                 and sub.rattfakta_krav
                                 and not hard_stops)
                        else "BLOCKED"),
                evidence=f"consequence_from={sub.subsumtion_id}",
            ))
        return chain

    def bygg_provenance_kedja(self, case_id: str,
                              legal_issues: List[LegalIssue],
                              sources: List[Any],
                              verifications: List[TwoStageVerification],
                              subsumptions: List[SubsumtionEntry],
                              hard_stops: List[HardStopEntry]
                              ) -> List[ChainLink]:
        chain = self._bygg_kedja_del1(
            case_id, legal_issues, sources, verifications, subsumptions
        )
        chain.extend(self._bygg_kedja_del2(subsumptions, hard_stops))
        for link in chain[1:]:
            if not link.prev_id:
                link.status = "PARTIAL"
        self.chain.extend(chain)
        return chain

    # ── FINAL KLASSIFICERING (PROVED kräver komplett kedja) ────
    def finalize_proved(self) -> Dict[str, int]:
        """PROVED sätts ENDAST för subsumtionssteg där HELA kedjan
        (CASE→…→CONSEQUENCE) är komplett OCH inga HARD_STOP blockerar."""
        ids_by_step: Dict[str, ChainLink] = {}
        for link in self.chain:
            ids_by_step[link.step + ":" + link.chain_id] = link

        proved = 0
        ej_verifierat = 0
        motsags = 0
        ej_avgor = 0
        for sub in self.subsumptions:
            sub_status = sub.status
            sub_id_short = sub.subsumtion_id.split("-")[-1]
            sub_link = ids_by_step.get(
                f"SUBSUMPTION:SUB-{int(sub_id_short):03d}")
            cons_link = ids_by_step.get(
                f"CONSEQUENCE:CON-{int(sub_id_short):03d}") if sub_link else None
            if (sub_status == SubsumtionStatus.UPPFYLLT
                    and sub.bevisning
                    and sub.rattfakta_krav
                    and cons_link is not None
                    and cons_link.status == "OK"
                    and not any(
                        sub.subsumtion_id in (h.betreffande or "")
                        for h in self.hard_stops)):
                if sub_link is not None:
                    sub_link.status = "PROVED"
                proved += 1
            elif sub_status == SubsumtionStatus.MOTSAGS:
                motsags += 1
            elif sub_status in (SubsumtionStatus.EJ_AVGORBART,):
                ej_avgor += 1
            else:
                ej_verifierat += 1

        for link in self.chain:
            if link.step == "CONSEQUENCE" and link.status == "OK":
                i = int(link.chain_id.split("-")[-1])
                sub_link = ids_by_step.get(f"SUBSUMPTION:SUB-{i:03d}")
                if sub_link is not None and sub_link.status == "PROVED":
                    link.status = "PROVED"
                    link.evidence = "fullständig kedja CASE→…→CONSEQUENCE verifierad"
        return {
            "PROVED": proved,
            "EJ_VERIFIERAT": ej_verifierat,
            "MOTSAGS": motsags,
            "EJ_AVGORBART": ej_avgor,
        }

    # ── SLUTGILTIG RAPPORTDATA ─────────────────────────────────
    def to_report(self) -> Dict[str, Any]:
        """Sammanställer maskinläsbar slutrapport med alla räknare."""
        ids = {
            "LEGAL_ISSUE": len(self.legal_issues),
            "LEGAL_SOURCE": len(self.sources),
            "VERIFIERAD_PRIMARKALLA": sum(
                1 for v in self.verifications
                if v.primarkalla and v.slutstatus == "EJ VERIFIERAD"
            ),
            "HISTORISKA_VERSIONER": sum(
                1 for v in self.verifications
                if v.historisk_lydelse_vid_datum
                and "EJ BEKRÄFTAD" not in v.historisk_lydelse_vid_datum),
            "RULE": len(set(s.rule_id for s in self.subsumptions)),
            "REQUISITE": len(self.subsumptions),
            "LEGAL_FACT": len(self.subsumptions),
            "EVIDENCE": sum(1 for s in self.subsumptions if s.bevisning),
            "SUBSUMPTION": len(self.subsumptions),
            "MOTPROVNINGAR": len(self.contra_checks),
            "HARD_STOP": len(self.hard_stops),
        }
        complete = 0
        for link in self.chain:
            if link.step == "SUBSUMPTION" and link.status == "PROVED":
                complete += 1
        ids["KOMPLETT_PROVENANCE"] = complete
        final = self.finalize_proved()
        return {
            "run_id": self.run_id,
            "case_id": self.case_id,
            "rattsomrade": self.rattsomrade,
            "processform": self.processform,
            "maltyp": self.maltyp,
            "enable_network": self.enable_network,
            "relevant_date": self.relevant_date,
            "log": self.log[-30:],
            "counters": ids,
            "final_status": final,
            "verifications": [v.to_dict() for v in self.verifications],
            "subsumptions": [s.to_dict() for s in self.subsumptions],
            "domskals_audit": [a.to_dict() for a in self.domskals_audit],
            "contra_checks": [c.to_dict() for c in self.contra_checks],
            "hard_stops": [h.to_dict() for h in self.hard_stops],
            "chain": [c.to_dict() for c in self.chain],
        }


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRATION MED PRODUKTIONSPIPELINE (STEG 13 §10)
# ─────────────────────────────────────────────────────────────────────────────


def run_steg13_on_case_state(case_state: Any, run_id: str = "",
                             enable_network: bool = False,
                             relevant_date: str = "") -> Dict[str, Any]:
    """Kör hela STEG 13-flödet mot en kanonisk CaseState från v10.3-pipelinen.
    Returnerar rapportdict + skriver resultatet till case_state.metadata.
    """
    engine = Steg13DynamicEngine(
        case_id=getattr(case_state, "case_id", "UNKNOWN"),
        run_id=run_id or f"STEG13-{datetime.datetime.now().strftime('%H%M%S')}",
        enable_network=enable_network,
        relevant_date=relevant_date,
    )
    engine._log("STEG 13 startar mot kanonisk CaseState")

    # 1. Profilering dynamiskt
    claims_list = list(getattr(case_state, "claims", []) or [])
    legal_sources = list(getattr(case_state, "legal_sources", []) or [])
    requisite_list = list(
        getattr(case_state, "requisite_matrix", []) or [])

    engine.profile_case_dynamically(claims_list)
    engine._log(
        f"Profilering klar: rättsområde={engine.rattsomrade}, "
        f"processform={engine.processform}, måltyp={engine.maltyp}"
    )

    # 2. Identifiering av rättsfrågor
    issues = engine.extract_legal_issues(claims_list)
    engine._log(f"Rättsfrågor identifierade: {len(issues)}")

    # 3. Rättskällekontroll mot primary sources (SFS / prop)
    # Bygg rättsbegreppslista dynamiskt från extraherade lagrumshints
    rättsbegrepp = []
    for li in issues:
        if li.source_hint:
            rättsbegrepp.append(li.source_hint)
        rättsbegrepp.append(li.rattfraga)
    # SFCAE-PORT: inga hårdkodade standardbegrepp (källan föll tillbaka på
    # BrB 6:4/6:10). Tom lista → ingen sökning, redovisas ärligt.
    if not rättsbegrepp:
        engine._log("Inga rättsbegrepp ur materialet — ingen registersökning")
    if enable_network:
        search_results = engine.run_searches(rättsbegrepp)
        engine._log(
            f"SEARCH_01–10 resultat: {len(search_results)} söksteg, "
            f"{len(engine.sources)} RattkalleObjekt"
        )
    else:
        engine._log("enable_network=False → register ej anropat (ärlig status)")

    # 3b. Skapa RattkalleObjekt även för redan kända legal_sources från
    # canonical-pipelinen (L7-utfall). Då slipper vi gå miste om redan
    # identifierade rättskällor.
    if legal_sources and not engine.sources:
        engine.identifiera_fran_existerande(legal_sources)
    engine._log(f"Rättskälleobjekt totalt: {len(engine.sources)}")

    # 4. TwoStageVerification
    verifications = engine.two_stage_verify(
        engine.sources, list(getattr(case_state, "requisite_matrix", []) or []),
        list(getattr(case_state, "claims", []) or []))
    engine._log(f"Tvåstegsverifieringar: {len(verifications)}")

    # 5. Subsumtion
    subsumptions = engine.subsumera_requisites(
        list(getattr(case_state, "requisite_matrix", []) or []),
        engine.sources, list(getattr(case_state, "claims", []) or []))
    engine._log(f"Subsumtionsposter: {len(subsumptions)}")

    # 6. Domskälsaudit (bidirectional)
    audit_entries = engine.audit_domskal(
        subsumptions, list(getattr(case_state, "claims", []) or []))
    engine._log(f"Domskälsaudit-poster: {len(audit_entries)}")

    # 7. Kontradiktorisk kontroll
    contra = engine.contradictorisk_kontroll(
        list(getattr(case_state, "claims", []) or []), subsumptions)
    engine._log(f"Kontradiktoriska kontroller: {len(contra)}")

    # 8. Hard-stop-kontroll
    hard_stops = engine.apply_hard_stops(
        subsumptions, verifications, engine.sources)
    engine._log(f"Hard-stop-flaggor: {len(hard_stops)}")

    # 9. Provenance-kedja
    chain = engine.bygg_provenance_kedja(
        case_id=getattr(case_state, "case_id", "UNKNOWN"),
        legal_issues=engine.legal_issues,
        sources=engine.sources,
        verifications=verifications,
        subsumptions=subsumptions,
        hard_stops=hard_stops,
    )
    engine._log(f"Provenance-kedjelänkar: {len(chain)}")
    # 10. Slutrapport
    report = engine.to_report()
    engine._log(
        f"STEG 13 slutrapport klar – "
        f"final={report['final_status']}, "
        f"proved={report['counters'].get('KOMPLETT_PROVENANCE', 0)}"
    )

    # Skriv tillbaka i case_state.metadata
    md = getattr(case_state, "metadata", None)
    if isinstance(md, dict):
        md["steg13_report"] = report
        md["steg13_proved"] = report["final_status"]["PROVED"]
        md["steg13_ej_verifierat"] = report["final_status"]["EJ_VERIFIERAT"]
        md["steg13_hard_stops"] = [
            h.to_dict() for h in engine.hard_stops]
        md["steg13_chain_length"] = len(chain)
    return report


def run_steg13_if_requested(case_state=None, pipeline_state=None,
                            requested: bool = False, enable_network: bool = False,
                            relevant_date: str = "", run_id: str = "") -> Dict[str, Any]:
    """Alt B-ingång. case_state = kanonisk CaseState (consolidated_engine);
    pipeline_state = dynamic_pipeline OrchestrationState (claims som dict)."""
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "STEG 13 kräver requested=True."}
    if case_state is None and pipeline_state is not None:
        from types import SimpleNamespace
        case_state = SimpleNamespace(
            case_id=(getattr(pipeline_state, "case_meta", {}) or {}).get("case_id", "PIPELINE"),
            claims=list(getattr(pipeline_state, "claims", []) or []),
            legal_sources=[], requisite_matrix=[], metadata={},
        )
    if case_state is None:
        return {"status": "PARAMS_SAKNAS", "krävs": ["case_state eller pipeline_state"]}
    # Steg 14: domänspärr i kanonisk CaseState eller OrchestrationState
    # blockerar den dynamiska juridiska analysen (ingen alternativ väg).
    from hard_stop_las import spärrsvar as _spärrsvar
    _sv = _spärrsvar("steg13", case_state, pipeline_state)
    if _sv:
        return _sv
    rapport = run_steg13_on_case_state(case_state, run_id=run_id,
                                       enable_network=enable_network,
                                       relevant_date=relevant_date)
    return {"status": "GENOMFÖRD", "nätverk": enable_network, "rapport": rapport}
