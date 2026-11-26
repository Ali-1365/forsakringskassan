from __future__ import annotations
# PASSIV MOTIVERING: Domskalmatris — ingår i canonical L13. Separat modul bibehålls.
# Bibehålls per arkitekturbeslutet.
_PASSIV_MOTIVERING = True

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DOMSKÄLSMATRIS AGENT – L9 (MODEBEROENDE)
SVENSK FORENSIC COURT AUDIT ENGINE v10.3-UPDATED
Datum: 2026-08-23

JUDGMENT_AUDIT:  Granskar domstolens befintliga resonemang mot primärkällor.
JUDGMENT_CONSTRUCTION: Konstruerar domskälsmatris från processmaterial.

ABSOLUTA REGLER:
- CIRCULAR_REASONING_BLOCKER: Domens faktabeskrivning får ALDRIG användas
  som primärkälla för de fakta domen sedan bedömer (FIX-Q)
- Conclusion-first är FÖRBJUDET: FAKTA → BEVIS → RÄTTSFAKTA → RÄTTSREGEL
  → REKVISIT → SUBSUMTION → SLUTSATS (aldrig omvänt)
- Procentuell bevisvärdering är FÖRBJUDEN (P10 FREE_EVIDENCE_RESPECT)
- Varje länk i kedjan måste verifieras mot primärkälla
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from forensic_engine_v10_3_canonical import (
    ClaimId,
    Availability,
    CaseState,
    CourtType,
    ProcessMode,
    AuditStatus,
    HardStopCode,
    LegalSourceRecord,
    RequisiteEntry,
    RequisiteStatus,
    ModalMarker,
    AuditFinding,
)


# ============================================================
# ENUMS
# ============================================================

class DiskrepansStatus(Enum):
    JA = "JA"                        # Verifierad diskrepans
    NEJ = "NEJ"                      # Ingen diskrepans
    KAN_EJ_AVGÖRAS = "KAN EJ AVGÖRAS"  # Otillräckligt underlag


class RättsligBetydelse(Enum):
    KAN_INTE_AVGÖRAS = "KAN INTE AVGÖRAS"
    KAN_PRÖVAS = "KAN PRÖVAS"
    VERIFIERAD = "VERIFIERAD"


class BevisfrågeStatus(Enum):
    VERIFIERAT_KORREKT = "VERIFIERAT_KORREKT"
    VERIFIERAD_AVVIKELSE = "VERIFIERAD_AVVIKELSE"
    KAN_EJ_VERIFIERAS = "KAN_EJ_VERIFIERAS"
    MOTSTRIDIGT = "MOTSTRIDIGT"


class SubsumtionsStatus(Enum):
    UPPFYLLT = "UPPFYLLT"
    EJ_UPPFYLLT = "EJ_UPPFYLLT"
    UNRESOLVED = "UNRESOLVED"


# ============================================================
# DATAKLASSER – JUDGMENT_AUDIT
# ============================================================

@dataclass
class DomskälsFynd:
    """
    Ett fynd från domskälsmatrisen (JUDGMENT_AUDIT).
    Format per bevisfråga enligt FIX-S.
    """
    fynd_id: str                          # DS-001, DS-002, ...
    domstolens_bevispremiss: str          # Exakt domtext | DOM-ID | SIDA
    domstolens_källa: str                 # Angiven källa
    primärkälla_ref: str                  # KÄLL-ID | FIL | SIDA | DATUM | VERSION
    källan_visar: str                     # Vad primärkällan faktiskt innehåller
    motbevisning: str                     # Motbevis | KÄLL-ID eller SAKNAS
    domstolens_bemötande: str             # Hur domstolen hanterat motbevisning
    verifierad_diskrepans: DiskrepansStatus
    rättslig_betydelse: RättsligBetydelse
    bevisfråge_status: BevisfrågeStatus
    audit_status: AuditStatus             # B–F vid verifierad avvikelse, A om korrekt
    source_claim_id: str = ""             # Koppling till L2 claim_id
    circular_reasoning_detected: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fynd_id": self.fynd_id,
            "domstolens_bevispremiss": self.domstolens_bevispremiss[:200],
            "primärkälla_ref": self.primärkälla_ref,
            "källan_visar": self.källan_visar[:200],
            "verifierad_diskrepans": self.verifierad_diskrepans.value,
            "rättslig_betydelse": self.rättslig_betydelse.value,
            "bevisfråge_status": self.bevisfråge_status.value,
            "audit_status": self.audit_status.value,
            "circular_reasoning_detected": self.circular_reasoning_detected,
        }

    def to_formatted_string(self) -> str:
        lines = [
            f"[{self.fynd_id}]",
            f"DOMSTOLENS_BEVISPREMISS:    {self.domstolens_bevispremiss[:150]}",
            f"DOMSTOLENS_KÄLLA:           {self.domstolens_källa}",
            f"PRIMÄRKÄLLA:                {self.primärkälla_ref}",
            f"KÄLLAN_VISAR:               {self.källan_visar[:150]}",
            f"MOTBEVISNING:               {self.motbevisning}",
            f"DOMSTOLENS_BEMÖTANDE:       {self.domstolens_bemötande[:100]}",
            f"VERIFIERAD_DISKREPANS:      {self.verifierad_diskrepans.value}",
            f"RÄTTSLIG_BETYDELSE:         {self.rättslig_betydelse.value}",
            f"STATUS:                     {self.bevisfråge_status.value} → {self.audit_status.value}",
        ]
        if self.circular_reasoning_detected:
            lines.append("⚠️ CIRCULAR_REASONING_BLOCKER: Möjligt cirkelresonemang detekterat [HS10]")
        return "\n".join(lines)


# ============================================================
# DATAKLASSER – JUDGMENT_CONSTRUCTION
# ============================================================

@dataclass
class DomskälsKedja:
    """
    En domskälskedja för JUDGMENT_CONSTRUCTION.
    Ordning: RÄTTSFRÅGA → RÄTTSREGEL → REKVISIT → RÄTTSFAKTA →
             BEVISNING → BEVISKRAV → BEVISBEDÖMNING → SUBSUMTION → SLUTSATS
    Conclusion-first är FÖRBJUDET.
    """
    kedja_id: str
    rättsfråga: str
    rättsregel: str                    # SFS-nummer § X
    rättsregel_källa: str              # KÄLL-ID
    rekvisit: List[RequisiteEntry] = field(default_factory=list)
    rättsfakta: List[str] = field(default_factory=list)
    bevisning: List[str] = field(default_factory=list)
    beviskrav: str = ""
    beviskrav_källa: str = ""
    bevisbedömning: str = ""           # Aldrig procentuell
    subsumtion: SubsumtionsStatus = SubsumtionsStatus.UNRESOLVED
    slutsats: str = ""                 # Produceras SIST – aldrig först
    slutsats_blockerad: bool = False   # True om HS11 aktiv
    blockerings_orsak: str = ""

    def to_formatted_string(self) -> str:
        lines = [
            f"[{self.kedja_id}] DOMSKÄLSKEDJA",
            f"RÄTTSFRÅGA:    {self.rättsfråga}",
            f"RÄTTSREGEL:    {self.rättsregel} | Källa: {self.rättsregel_källa}",
            f"REKVISIT:      {len(self.rekvisit)} st",
            f"RÄTTSFAKTA:    {len(self.rättsfakta)} st",
            f"BEVISNING:     {len(self.bevisning)} st",
            f"BEVISKRAV:     {self.beviskrav} | Källa: {self.beviskrav_källa}",
            f"BEVISBEDÖMNING: {self.bevisbedömning[:100]}",
            f"SUBSUMTION:    {self.subsumtion.value}",
        ]
        if self.slutsats_blockerad:
            lines.append(
                f"SLUTSATS:      [BLOCKERAD – {self.blockerings_orsak}]"
            )
        else:
            lines.append(f"SLUTSATS:      {self.slutsats[:150]}")
        return "\n".join(lines)


# ============================================================
# DOMSKÄLSMATRIS AGENT
# ============================================================

class DomskälsmatrisAgent:
    """
    L9: Domskälsmatris – modeberoende.

    JUDGMENT_AUDIT:
        Granskar domstolens befintliga resonemang.
        Jämför domstolens bevispremisser mot primärkällor.
        Identifierar diskrepanser och producerar statusar A–F.

    JUDGMENT_CONSTRUCTION:
        Konstruerar domskälsmatris från processmaterial.
        Ordning: FAKTA → BEVIS → RÄTTSFAKTA → RÄTTSREGEL → REKVISIT
                 → SUBSUMTION → SLUTSATS
        Conclusion-first är FÖRBJUDET.
    """

    # Signalord för domstolens bevispremisser (JUDGMENT_AUDIT)
    DOM_PREMISS_SIGNALS = [
        r"\bdomstolen\s+finner\b", r"\bdomstolen\s+konstaterar\b",
        r"\bdomstolen\s+bedömer\b", r"\bdomstolen\s+anser\b",
        r"\brätten\s+finner\b", r"\brätten\s+konstaterar\b",
        r"\bdet\s+är\s+utrett\b", r"\bdet\s+är\s+styrkt\b",
        r"\bdet\s+framgår\b", r"\bdet\s+har\s+framkommit\b",
        r"\bav\s+utredningen\s+framgår\b",
        r"\bdomskäl\b", r"\bdomslut\b",
        r"\brätten\s+gör\s+följande\s+bedömning\b",
        r"\bförvaltningsrätten\s+gör\b", r"\bkammarrätten\s+gör\b",
    ]

    # Signalord för rättsfrågor
    RÄTTSFRÅGA_SIGNALS = [
        r"\bfrågan\s+är\b", r"\bfrågan\s+i\s+målet\b",
        r"\btvisten\s+gäller\b", r"\btvistigt\s+är\b",
        r"\bprövningsfrågan\b", r"\bprövningsramen\b",
        r"\bom\s+klaganden\s+har\s+rätt\s+till\b",
        r"\bom\s+sökanden\s+uppfyller\b",
        r"\bhuvudfrågan\b",
    ]

    # Signalord för lagrum
    LAGRUM_SIGNALS = [
        r"\b\d+\s*kap\.\s*\d+\s*§\b",
        r"\b§\s*\d+\b",
        r"\bsfs\s*\d{4}:\d+\b",
        r"\bsfb\b", r"\bfl\b", r"\bfpl\b", r"\brb\b",
        r"\bsol\b", r"\blvu\b", r"\blvm\b",
    ]

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.log: List[str] = []
        self._fynd_counter = 0
        self._kedja_counter = 0

    def run(self, case_state: CaseState) -> Tuple[
        List[DomskälsFynd], List[DomskälsKedja]
    ]:
        """
        Kör L9 baserat på processmode.
        Returnerar (audit_fynd, construction_kedjor).
        """
        if case_state.process_mode == ProcessMode.JUDGMENT_AUDIT:
            fynd = self.run_audit(case_state)
            return fynd, []
        elif case_state.process_mode == ProcessMode.JUDGMENT_CONSTRUCTION:
            kedjor = self.run_construction(case_state)
            return [], kedjor
        else:
            self.log.append("[L9] VARNING: ProcessMode UNDEFINED – kör AUDIT som standard")
            fynd = self.run_audit(case_state)
            return fynd, []

    # ──────────────────────────────────────────────────────────
    # JUDGMENT_AUDIT
    # ──────────────────────────────────────────────────────────

    def run_audit(self, case_state: CaseState) -> List[DomskälsFynd]:
        """
        JUDGMENT_AUDIT: Granskar domstolens befintliga resonemang.

        För varje domspåstående:
        1. Identifiera domstolens bevispremiss [DOM-ID | SIDA]
        2. Identifiera angiven källa
        3. Hämta primärkälla från case_state.claims
        4. Jämför domens formulering med primärkällan
        5. Identifiera diskrepans
        6. Bedöm rättslig betydelse
        """
        self.log.append("[L9] JUDGMENT_AUDIT: Domskälsmatris startar")

        if not case_state.claims:
            self.log.append(
                "[L9] VARNING: Inga claims – kör L2 textextraktion först. "
                "Domskälsmatris kan inte köras utan primärkällor."
            )
            return []

        fynd: List[DomskälsFynd] = []

        # Identifiera dom-claims (från DOM-filer)
        dom_claims = [
            c for c in case_state.claims
            if "dom" in c.source_id.lower() or
               "dom" in c.file_name.lower() or
               "beslut" in c.file_name.lower()
        ]

        # Identifiera primärkälla-claims (ej från dom)
        primärkälla_claims = [
            c for c in case_state.claims
            if c not in dom_claims
        ]

        self.log.append(
            f"[L9] Dom-claims: {len(dom_claims)}, "
            f"Primärkälla-claims: {len(primärkälla_claims)}"
        )

        if not dom_claims:
            self.log.append(
                "[L9] Inga dom-claims identifierade. "
                "Kontrollera att dom-dokument är uppladdade."
            )
            # Kör ändå mot tillgängligt material
            return self._analyze_available_material(case_state, primärkälla_claims)

        # Analysera varje dom-claim mot primärkällor
        for dom_claim in dom_claims:
            if not self._is_dom_premiss(dom_claim.content):
                continue

            fynd_list = self._analyze_dom_claim(
                dom_claim, primärkälla_claims, case_state
            )
            fynd.extend(fynd_list)

        # Uppdatera audit_status baserat på fynd
        self._update_case_status_from_fynd(fynd, case_state)

        # Spara i case_state.metadata
        case_state.metadata["l9_audit_fynd"] = [f.to_dict() for f in fynd]

        self.log.append(
            f"[L9] JUDGMENT_AUDIT klar: {len(fynd)} fynd. "
            f"Verifierade avvikelser: "
            f"{sum(1 for f in fynd if f.verifierad_diskrepans == DiskrepansStatus.JA)}"
        )

        return fynd

    def _is_dom_premiss(self, text: str) -> bool:
        """Kontrollerar om text innehåller en domstolsbevispremiss."""
        text_lower = text.lower()
        for signal in self.DOM_PREMISS_SIGNALS:
            if re.search(signal, text_lower, re.IGNORECASE):
                return True
        return False

    def _analyze_dom_claim(
        self,
        dom_claim: ClaimId,
        primärkälla_claims: List[ClaimId],
        case_state: CaseState,
    ) -> List[DomskälsFynd]:
        """
        Analyserar ett dom-claim mot primärkällor.
        CIRCULAR_REASONING_BLOCKER: Dom används ALDRIG som primärkälla för egna fakta.
        """
        fynd: List[DomskälsFynd] = []

        # CIRCULAR_REASONING_BLOCKER (FIX-Q)
        # Kontrollera att dom-claim inte refererar till sig själv
        circular = self._detect_circular_reasoning(dom_claim, primärkälla_claims)

        # Hitta relevanta primärkällor via nyckelordsmatchning
        relevant_primärkällor = self._find_relevant_primärkällor(
            dom_claim.content, primärkälla_claims
        )

        self._fynd_counter += 1
        fynd_id = f"DS-{self._fynd_counter:03d}"

        if not relevant_primärkällor:
            # Ingen primärkälla hittad
            fynd.append(DomskälsFynd(
                fynd_id=fynd_id,
                domstolens_bevispremiss=(
                    f"{dom_claim.content[:200]} "
                    f"[{dom_claim.source_id} | {dom_claim.file_name} | "
                    f"{dom_claim.page}]"
                ),
                domstolens_källa=dom_claim.source_id,
                primärkälla_ref="KAN EJ VERIFIERAS – primärkälla saknas",
                källan_visar="KAN EJ VERIFIERAS",
                motbevisning="SAKNAS",
                domstolens_bemötande="KAN EJ VERIFIERAS",
                verifierad_diskrepans=DiskrepansStatus.KAN_EJ_AVGÖRAS,
                rättslig_betydelse=RättsligBetydelse.KAN_INTE_AVGÖRAS,
                bevisfråge_status=BevisfrågeStatus.KAN_EJ_VERIFIERAS,
                audit_status=AuditStatus.H,
                source_claim_id=dom_claim.claim_id,
                circular_reasoning_detected=circular,
            ))
        else:
            # Jämför dom-claim mot primärkälla
            for pk_claim in relevant_primärkällor[:2]:  # Max 2 primärkällor per dom-claim
                diskrepans, källan_visar = self._compare_claims(
                    dom_claim, pk_claim
                )

                bevisfråge_status, audit_status = self._determine_status(
                    diskrepans, circular
                )

                fynd.append(DomskälsFynd(
                    fynd_id=fynd_id,
                    domstolens_bevispremiss=(
                        f"{dom_claim.content[:200]} "
                        f"[{dom_claim.source_id} | {dom_claim.file_name} | "
                        f"{dom_claim.page}]"
                    ),
                    domstolens_källa=dom_claim.source_id,
                    primärkälla_ref=(
                        f"{pk_claim.source_id} | {pk_claim.file_name} | "
                        f"{pk_claim.page} | {pk_claim.date} | {pk_claim.version}"
                    ),
                    källan_visar=källan_visar,
                    motbevisning=self._find_motbevisning(
                        dom_claim, primärkälla_claims
                    ),
                    domstolens_bemötande=self._find_domstolens_bemötande(
                        dom_claim, case_state
                    ),
                    verifierad_diskrepans=diskrepans,
                    rättslig_betydelse=self._determine_rättslig_betydelse(
                        diskrepans, audit_status
                    ),
                    bevisfråge_status=bevisfråge_status,
                    audit_status=audit_status,
                    source_claim_id=dom_claim.claim_id,
                    circular_reasoning_detected=circular,
                ))

        return fynd

    def _analyze_available_material(
        self,
        case_state: CaseState,
        claims: List[ClaimId],
    ) -> List[DomskälsFynd]:
        """
        Analyserar tillgängligt material utan dom.
        Producerar status G (potentiellt) eller H (kan ej avgöras).
        """
        fynd: List[DomskälsFynd] = []

        for claim in claims[:5]:  # Max 5 fynd utan dom
            self._fynd_counter += 1
            fynd.append(DomskälsFynd(
                fynd_id=f"DS-{self._fynd_counter:03d}",
                domstolens_bevispremiss="[DOM SAKNAS – partiell körning]",
                domstolens_källa="KAN EJ VERIFIERAS",
                primärkälla_ref=(
                    f"{claim.source_id} | {claim.file_name} | "
                    f"{claim.page} | {claim.date} | {claim.version}"
                ),
                källan_visar=claim.content[:200],
                motbevisning="SAKNAS",
                domstolens_bemötande="KAN EJ VERIFIERAS – dom saknas",
                verifierad_diskrepans=DiskrepansStatus.KAN_EJ_AVGÖRAS,
                rättslig_betydelse=RättsligBetydelse.KAN_INTE_AVGÖRAS,
                bevisfråge_status=BevisfrågeStatus.KAN_EJ_VERIFIERAS,
                audit_status=AuditStatus.H,
                source_claim_id=claim.claim_id,
            ))

        return fynd

    def _detect_circular_reasoning(
        self,
        dom_claim: ClaimId,
        primärkälla_claims: List[ClaimId],
    ) -> bool:
        """
        CIRCULAR_REASONING_BLOCKER (FIX-Q):
        Detekterar om dom-claim refererar till sig själv som primärkälla.
        """
        dom_text = dom_claim.content.lower()

        # Kontrollera om dom-texten innehåller fraser som tyder på
        # att domen används som primärkälla för egna fakta
        circular_patterns = [
            r"\bsom\s+framgår\s+av\s+domen\b",
            r"\bsom\s+domstolen\s+konstaterat\b",
            r"\bsom\s+anges\s+i\s+domen\b",
            r"\bsom\s+framgår\s+ovan\b.*\bdomstolen\b",
            r"\bav\s+domens\s+skäl\s+framgår\b",
        ]

        for pattern in circular_patterns:
            if re.search(pattern, dom_text, re.IGNORECASE):
                self.log.append(
                    f"[L9] CIRCULAR_REASONING_BLOCKER: Möjligt cirkelresonemang "
                    f"i {dom_claim.claim_id} [HS10]"
                )
                return True

        return False

    def _find_relevant_primärkällor(
        self,
        dom_text: str,
        primärkälla_claims: List[ClaimId],
    ) -> List[ClaimId]:
        """
        Hittar primärkällor relevanta för ett dom-påstående
        via nyckelordsmatchning.
        """
        dom_words = set(re.findall(r"\b\w{4,}\b", dom_text.lower()))
        scored: List[Tuple[int, ClaimId]] = []

        for pk in primärkälla_claims:
            pk_words = set(re.findall(r"\b\w{4,}\b", pk.content.lower()))
            overlap = len(dom_words & pk_words)
            if overlap > 3:  # Minst 4 gemensamma ord
                scored.append((overlap, pk))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [pk for _, pk in scored[:3]]

    def _compare_claims(
        self,
        dom_claim: ClaimId,
        pk_claim: ClaimId,
    ) -> Tuple[DiskrepansStatus, str]:
        """
        Jämför dom-claim mot primärkälla.
        Returnerar (diskrepans_status, källan_visar).
        """
        dom_text = dom_claim.content.lower()
        pk_text = pk_claim.content.lower()

        # Beräkna textlikhet (enkel ordöverlapp)
        dom_words = set(re.findall(r"\b\w{4,}\b", dom_text))
        pk_words = set(re.findall(r"\b\w{4,}\b", pk_text))

        if not dom_words or not pk_words:
            return DiskrepansStatus.KAN_EJ_AVGÖRAS, pk_claim.content[:200]

        overlap = len(dom_words & pk_words)
        total = len(dom_words | pk_words)
        similarity = overlap / total if total > 0 else 0

        källan_visar = pk_claim.content[:200]

        # Hög likhet → troligen korrekt återgivning
        if similarity > 0.4:
            return DiskrepansStatus.NEJ, källan_visar
        # Låg likhet → möjlig diskrepans
        elif similarity < 0.15:
            return DiskrepansStatus.JA, källan_visar
        else:
            return DiskrepansStatus.KAN_EJ_AVGÖRAS, källan_visar

    def _find_motbevisning(
        self,
        dom_claim: ClaimId,
        primärkälla_claims: List[ClaimId],
    ) -> str:
        """Söker efter motbevisning i primärkällorna."""
        dom_text = dom_claim.content.lower()

        # Sök efter claims som innehåller negationer av dom-påståendet
        negation_patterns = [
            r"\binte\b", r"\bej\b", r"\bnej\b", r"\bnekar\b",
            r"\bbestrider\b", r"\bifrågasätter\b",
        ]

        for pk in primärkälla_claims:
            pk_text = pk.content.lower()
            # Kontrollera om primärkällan innehåller negationer
            # och delar nyckelord med dom-påståendet
            dom_words = set(re.findall(r"\b\w{5,}\b", dom_text))
            pk_words = set(re.findall(r"\b\w{5,}\b", pk_text))
            overlap = len(dom_words & pk_words)

            has_negation = any(
                re.search(p, pk_text) for p in negation_patterns
            )

            if overlap > 2 and has_negation:
                return (
                    f"{pk.content[:150]} "
                    f"[{pk.source_id} | {pk.file_name} | {pk.page}]"
                )

        return "SAKNAS"

    def _find_domstolens_bemötande(
        self,
        dom_claim: ClaimId,
        case_state: CaseState,
    ) -> str:
        """Söker efter domstolens bemötande av motbevisning."""
        bemötande_patterns = [
            r"\bdomstolen\s+noterar\b", r"\bdomstolen\s+beaktar\b",
            r"\brätten\s+noterar\b", r"\brätten\s+beaktar\b",
            r"\bvad\s+gäller\b.*\binvändning\b",
            r"\btill\s+detta\s+kan\s+sägas\b",
        ]

        for claim in case_state.claims:
            if claim.claim_id == dom_claim.claim_id:
                continue
            text_lower = claim.content.lower()
            for pattern in bemötande_patterns:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    return (
                        f"{claim.content[:150]} "
                        f"[{claim.source_id} | {claim.file_name} | {claim.page}]"
                    )

        return "KAN EJ VERIFIERAS"

    def _determine_status(
        self,
        diskrepans: DiskrepansStatus,
        circular: bool,
    ) -> Tuple[BevisfrågeStatus, AuditStatus]:
        """Bestämmer bevisfråge- och auditstatus."""
        if circular:
            return BevisfrågeStatus.MOTSTRIDIGT, AuditStatus.G

        if diskrepans == DiskrepansStatus.JA:
            return BevisfrågeStatus.VERIFIERAD_AVVIKELSE, AuditStatus.E
        elif diskrepans == DiskrepansStatus.NEJ:
            return BevisfrågeStatus.VERIFIERAT_KORREKT, AuditStatus.A
        else:
            return BevisfrågeStatus.KAN_EJ_VERIFIERAS, AuditStatus.H

    def _determine_rättslig_betydelse(
        self,
        diskrepans: DiskrepansStatus,
        audit_status: AuditStatus,
    ) -> RättsligBetydelse:
        """Bestämmer rättslig betydelse av diskrepansen."""
        if audit_status in (AuditStatus.B, AuditStatus.C, AuditStatus.D,
                            AuditStatus.E, AuditStatus.F):
            return RättsligBetydelse.VERIFIERAD
        elif audit_status == AuditStatus.G:
            return RättsligBetydelse.KAN_PRÖVAS
        else:
            return RättsligBetydelse.KAN_INTE_AVGÖRAS

    def _update_case_status_from_fynd(
        self,
        fynd: List[DomskälsFynd],
        case_state: CaseState,
    ) -> None:
        """Uppdaterar case_state.overall_status baserat på L9-fynd."""
        if not fynd:
            return

        # Hitta allvarligaste status
        status_priority = {
            AuditStatus.B: 8, AuditStatus.C: 7, AuditStatus.D: 6,
            AuditStatus.E: 5, AuditStatus.F: 4, AuditStatus.G: 3,
            AuditStatus.H: 2, AuditStatus.A: 1, AuditStatus.I: 0,
        }

        worst_status = max(
            fynd,
            key=lambda f: status_priority.get(f.audit_status, 0)
        ).audit_status

        # Uppdatera bara om ny status är allvarligare
        current_priority = status_priority.get(case_state.overall_status, 0)
        new_priority = status_priority.get(worst_status, 0)

        if new_priority > current_priority:
            case_state.overall_status = worst_status
            self.log.append(
                f"[L9] overall_status uppdaterad till {worst_status.value} "
                f"baserat på domskälsanalys"
            )

    # ──────────────────────────────────────────────────────────
    # JUDGMENT_CONSTRUCTION
    # ──────────────────────────────────────────────────────────

    def run_construction(self, case_state: CaseState) -> List[DomskälsKedja]:
        """
        JUDGMENT_CONSTRUCTION: Konstruerar domskälsmatris.

        Ordning (conclusion-first FÖRBJUDET):
        RÄTTSFRÅGA → RÄTTSREGEL → REKVISIT → RÄTTSFAKTA →
        BEVISNING → BEVISKRAV → BEVISBEDÖMNING → SUBSUMTION → SLUTSATS
        """
        self.log.append("[L9] JUDGMENT_CONSTRUCTION: Domskälsmatris startar")

        if not case_state.claims:
            self.log.append(
                "[L9] VARNING: Inga claims – kör L2 textextraktion först."
            )
            return []

        kedjor: List[DomskälsKedja] = []

        # Identifiera rättsfrågor från claims
        rättsfrågor = self._identify_rättsfrågor(case_state.claims)
        self.log.append(f"[L9] Identifierade rättsfrågor: {len(rättsfrågor)}")

        for rättsfråga in rättsfrågor[:5]:  # Max 5 kedjor per körning
            kedja = self._build_domskälskedja(rättsfråga, case_state)
            kedjor.append(kedja)

        # Spara i case_state.metadata
        case_state.metadata["l9_construction_kedjor"] = [
            {"kedja_id": k.kedja_id, "rättsfråga": k.rättsfråga,
             "subsumtion": k.subsumtion.value, "slutsats_blockerad": k.slutsats_blockerad}
            for k in kedjor
        ]

        self.log.append(
            f"[L9] JUDGMENT_CONSTRUCTION klar: {len(kedjor)} kedjor. "
            f"Blockerade: {sum(1 for k in kedjor if k.slutsats_blockerad)}"
        )

        return kedjor

    def _identify_rättsfrågor(self, claims: List[ClaimId]) -> List[str]:
        """Identifierar rättsfrågor från claims."""
        rättsfrågor = []

        for claim in claims:
            text_lower = claim.content.lower()
            for signal in self.RÄTTSFRÅGA_SIGNALS:
                if re.search(signal, text_lower, re.IGNORECASE):
                    # Extrahera meningen som innehåller signalen
                    sentences = re.split(r"[.!?]", claim.content)
                    for sent in sentences:
                        if re.search(signal, sent.lower(), re.IGNORECASE):
                            rättsfråga = sent.strip()
                            if len(rättsfråga) > 20 and rättsfråga not in rättsfrågor:
                                rättsfrågor.append(rättsfråga)
                    break

        # Om inga rättsfrågor hittades, skapa en generisk
        if not rättsfrågor:
            rättsfrågor.append(
                "Rättsfråga ej explicit identifierad i materialet – "
                "KAN EJ VERIFIERAS"
            )

        return rättsfrågor

    def _build_domskälskedja(
        self,
        rättsfråga: str,
        case_state: CaseState,
    ) -> DomskälsKedja:
        """
        Bygger en domskälskedja för en rättsfråga.
        Conclusion-first är FÖRBJUDET – slutsatsen produceras sist.
        """
        self._kedja_counter += 1
        kedja_id = f"DK-{self._kedja_counter:03d}"

        # Steg 1: Identifiera rättsregel från legal_sources
        rättsregel, rättsregel_källa = self._find_rättsregel(
            rättsfråga, case_state
        )

        # Steg 2: Hämta rekvisit från requisite_matrix
        rekvisit = case_state.requisite_matrix.copy()

        # Steg 3: Identifiera rättsfakta från claims
        rättsfakta = self._extract_rättsfakta(rättsfråga, case_state.claims)

        # Steg 4: Identifiera bevisning
        bevisning = self._extract_bevisning(case_state.claims)

        # Steg 5: Beviskrav från court_type
        beviskrav, beviskrav_källa = self._get_beviskrav(case_state.court_type)

        # Steg 6: Bevisbedömning (aldrig procentuell – P10)
        bevisbedömning = self._make_bevisbedömning(
            rättsfakta, bevisning, rekvisit
        )

        # Steg 7: Subsumtion
        subsumtion = self._determine_subsumtion(rekvisit)

        # Steg 8: Slutsats (SIST – conclusion-first förbjudet)
        slutsats_blockerad = False
        blockerings_orsak = ""
        slutsats = ""

        if subsumtion == SubsumtionsStatus.UNRESOLVED:
            slutsats_blockerad = True
            blockerings_orsak = "HS11 – subsumtionskedja saknar verifierat rättsfaktum"
            slutsats = "[BLOCKERAD – HS11]"
            # HS11 är ETT tillstånd i ärendet, inte en räknare. Varje blockerad
            # kedja lade tidigare till koden på nytt, vilket gjorde att samma
            # hard stop redovisades som flera separata stopp i rapporten och
            # blåste upp hard_stop_code_count. Samma vakt som i
            # SubsumptionGatekeeper och RequisiteClaimMapper.
            if HardStopCode.HS11 not in case_state.hard_stop_codes:
                case_state.hard_stop_codes.append(HardStopCode.HS11)
        elif subsumtion == SubsumtionsStatus.EJ_UPPFYLLT:
            slutsats = (
                "Rekvisiten är inte uppfyllda baserat på tillgängligt material. "
                "Juridisk bedömning överlämnas till behörig jurist. "
                f"[PROVISORISKT UTKAST – AI SAKNAR DÖMANDE MANDAT]"
            )
        else:
            slutsats = (
                "Rekvisiten bedöms vara uppfyllda baserat på tillgängligt material. "
                "Juridisk bedömning överlämnas till behörig jurist. "
                f"[PROVISORISKT UTKAST – AI SAKNAR DÖMANDE MANDAT]"
            )

        return DomskälsKedja(
            kedja_id=kedja_id,
            rättsfråga=rättsfråga,
            rättsregel=rättsregel,
            rättsregel_källa=rättsregel_källa,
            rekvisit=rekvisit,
            rättsfakta=rättsfakta,
            bevisning=bevisning,
            beviskrav=beviskrav,
            beviskrav_källa=beviskrav_källa,
            bevisbedömning=bevisbedömning,
            subsumtion=subsumtion,
            slutsats=slutsats,
            slutsats_blockerad=slutsats_blockerad,
            blockerings_orsak=blockerings_orsak,
        )

    def _find_rättsregel(
        self,
        rättsfråga: str,
        case_state: CaseState,
    ) -> Tuple[str, str]:
        """Hittar tillämplig rättsregel från legal_sources."""
        if case_state.legal_sources:
            for source in case_state.legal_sources:
                if source.cited_law and source.cited_law != rättsfråga:
                    return source.cited_law, source.source_id

        # Sök i claims efter lagrum
        for claim in case_state.claims:
            for signal in self.LAGRUM_SIGNALS:
                match = re.search(signal, claim.content, re.IGNORECASE)
                if match:
                    return match.group(0), claim.source_id

        return "KAN EJ VERIFIERAS – SEARCH_01 krävs", "REQUIRES_SEARCH_01"

    def _extract_rättsfakta(
        self,
        rättsfråga: str,
        claims: List[ClaimId],
    ) -> List[str]:
        """Extraherar rättsfakta relevanta för rättsfrågan."""
        rättsfakta = []
        rättsfråga_words = set(re.findall(r"\b\w{4,}\b", rättsfråga.lower()))

        for claim in claims:
            claim_words = set(re.findall(r"\b\w{4,}\b", claim.content.lower()))
            overlap = len(rättsfråga_words & claim_words)
            if overlap > 2:
                rättsfakta.append(
                    f"{claim.content[:150]} "
                    f"[{claim.source_id} | {claim.file_name} | {claim.page}]"
                )

        return rättsfakta[:5]  # Max 5 rättsfakta

    def _extract_bevisning(self, claims: List[ClaimId]) -> List[str]:
        """Extraherar åberopad bevisning från claims."""
        bevisning_signals = [
            r"\bintyg\b", r"\butlåtande\b", r"\bläkarintyg\b",
            r"\bprotokoll\b", r"\bbilaga\b", r"\baktbilaga\b",
            r"\bvittne\b", r"\bskriftlig\s+bevisning\b",
        ]
        bevisning = []

        for claim in claims:
            text_lower = claim.content.lower()
            for signal in bevisning_signals:
                if re.search(signal, text_lower, re.IGNORECASE):
                    bevisning.append(
                        f"{claim.content[:100]} "
                        f"[{claim.source_id} | {claim.file_name} | {claim.page}]"
                    )
                    break

        return bevisning[:5]

    def _get_beviskrav(self, court_type: CourtType) -> Tuple[str, str]:
        """Hämtar beviskrav baserat på domstolstyp (dynamiskt, ej hårdkodat)."""
        beviskrav_map = {
            CourtType.CRIMINAL_COURT: (
                "Ställt utom rimligt tvivel",
                "RB 35:1 + HD-praxis"
            ),
            CourtType.CIVIL_COURT: (
                "Styrkt / Sannolikhetsövervikt",
                "RB 35:1 + HD-praxis"
            ),
            CourtType.ADMINISTRATIVE_COURT: (
                "Varierar med sakens beskaffenhet",
                "HFD-praxis per måltyp"
            ),
            CourtType.UNKNOWN: (
                "KAN EJ FASTSTÄLLAS – domstolstyp okänd",
                "REQUIRES_L1_CLASSIFICATION"
            ),
        }
        return beviskrav_map.get(
            court_type,
            ("KAN EJ FASTSTÄLLAS", "REQUIRES_L1_CLASSIFICATION")
        )

    def _make_bevisbedömning(
        self,
        rättsfakta: List[str],
        bevisning: List[str],
        rekvisit: List[RequisiteEntry],
    ) -> str:
        """
        Gör bevisbedömning.
        FÖRBJUDET: Procentuell bevisvärdering (P10 FREE_EVIDENCE_RESPECT).
        Systemet kontrollerar kedjan – det värderar inte bevis.
        """
        if not rättsfakta and not bevisning:
            return (
                "KEDJAN KAN INTE VERIFIERAS – "
                "rättsfakta och bevisning saknas i materialet"
            )

        lines = []
        if rättsfakta:
            lines.append(f"Rättsfakta identifierade: {len(rättsfakta)} st")
        if bevisning:
            lines.append(f"Bevisning åberopad: {len(bevisning)} st")

        # Kontrollera rekvisit
        uppfyllda = sum(
            1 for r in rekvisit
            if r.status in (
                RequisiteStatus.REKVISIT_UPPFYLLT,
                RequisiteStatus.OBESTRITT
            )
        )
        saknas = sum(
            1 for r in rekvisit
            if r.status == RequisiteStatus.BEVISNING_SAKNAS
        )

        if rekvisit:
            lines.append(
                f"Rekvisit: {uppfyllda}/{len(rekvisit)} uppfyllda, "
                f"{saknas} saknar bevisning"
            )

        if not lines:
            return "KAN EJ AVGÖRAS – otillräckligt underlag"

        return " | ".join(lines)

    def _determine_subsumtion(
        self,
        rekvisit: List[RequisiteEntry],
    ) -> SubsumtionsStatus:
        """Bestämmer subsumtionsstatus baserat på rekvisitmatris."""
        if not rekvisit:
            return SubsumtionsStatus.UNRESOLVED

        # MUST-rekvisit med BEVISNING_SAKNAS → UNRESOLVED (HS11)
        must_saknas = any(
            r.modal == ModalMarker.MUST and
            r.status == RequisiteStatus.BEVISNING_SAKNAS
            for r in rekvisit
        )
        if must_saknas:
            return SubsumtionsStatus.UNRESOLVED

        # Alla MUST-rekvisit uppfyllda → UPPFYLLT
        all_must_ok = all(
            r.status in (
                RequisiteStatus.REKVISIT_UPPFYLLT,
                RequisiteStatus.OBESTRITT
            )
            for r in rekvisit
            if r.modal == ModalMarker.MUST
        )
        if all_must_ok and rekvisit:
            return SubsumtionsStatus.UPPFYLLT

        return SubsumtionsStatus.EJ_UPPFYLLT

    # ──────────────────────────────────────────────────────────
    # RAPPORT
    # ──────────────────────────────────────────────────────────

    def generate_l9_report(
        self,
        fynd: List[DomskälsFynd],
        kedjor: List[DomskälsKedja],
        process_mode: ProcessMode,
    ) -> str:
        """Genererar L9-rapport i lagerformat (FIX-M)."""
        lines = ["## LAGER 9 – DOMSKÄLSMATRIS", ""]

        if process_mode == ProcessMode.JUDGMENT_AUDIT:
            lines.append(f"Mode: JUDGMENT_AUDIT | Fynd: {len(fynd)}")
            lines.append("")

            if not fynd:
                lines.append(
                    "[DOMSKÄLSMATRIS EJ KÖRBAR – dom-dokument saknas eller "
                    "L2 textextraktion ej genomförd]"
                )
            else:
                # Sammanfattning
                verifierade = sum(
                    1 for f in fynd
                    if f.verifierad_diskrepans == DiskrepansStatus.JA
                )
                korrekta = sum(
                    1 for f in fynd
                    if f.verifierad_diskrepans == DiskrepansStatus.NEJ
                )
                ej_avgöras = sum(
                    1 for f in fynd
                    if f.verifierad_diskrepans == DiskrepansStatus.KAN_EJ_AVGÖRAS
                )
                circular = sum(1 for f in fynd if f.circular_reasoning_detected)

                lines.extend([
                    f"Verifierade avvikelser: {verifierade}",
                    f"Verifierat korrekta: {korrekta}",
                    f"Kan ej avgöras: {ej_avgöras}",
                    f"Cirkelresonemang detekterade: {circular}",
                    "",
                    "### Fynd",
                ])

                for f in fynd:
                    lines.append(f.to_formatted_string())
                    lines.append("")

        elif process_mode == ProcessMode.JUDGMENT_CONSTRUCTION:
            lines.append(f"Mode: JUDGMENT_CONSTRUCTION | Kedjor: {len(kedjor)}")
            lines.append("")

            if not kedjor:
                lines.append(
                    "[DOMSKÄLSMATRIS EJ KÖRBAR – L2 textextraktion ej genomförd]"
                )
            else:
                blockerade = sum(1 for k in kedjor if k.slutsats_blockerad)
                lines.extend([
                    f"Blockerade kedjor (HS11): {blockerade}",
                    "",
                    "### Domskälskedjor",
                ])
                for k in kedjor:
                    lines.append(k.to_formatted_string())
                    lines.append("")

        lines.extend([
            "",
            "[L9 | DOMSKÄLSMATRIS | LOCKED]"
        ])
        return "\n".join(lines)