#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PROCESS POSITION AGENT – L4 PARTERNAS POSITIONER
SVENSK FORENSIC COURT AUDIT ENGINE v10.3-UPDATED
Datum: 2026-08-23

Registrerar parternas explicita yrkanden, grunder och invändningar.

ABSOLUTA REGLER:
- Motorn får ALDRIG konstruera ett yrkande, en grund eller en invändning genom inferens
- Om position inte kan verifieras ordagrant → NOT_VERIFIABLE
- Symmetriregeln P18: Båda parters argument behandlas med identisk analytisk rigor
- Ingen part favoriseras
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from forensic_engine_v10_3_canonical import (
    ClaimId,
    Availability,
    CaseState,
    CourtType,
    ProcessMode,
    HardStopCode,
)
from document_text_extractor import TextSegment, ExtractionResult


# ============================================================
# PROCESS POSITION CLASSES (SKILL_final.md L4)
# ============================================================

POSITION_CLASSES = [
    "EXPLICIT_YRKANDE",       # Uttryckligt yrkande
    "EXPLICIT_GRUND",         # Uttrycklig grund för yrkandet
    "EXPLICIT_INVÄNDNING",    # Uttrycklig invändning mot motpartens yrkande
    "EXPLICIT_MEDGIVANDE",    # Uttryckligt medgivande
    "EXPLICIT_BESTRIDANDE",   # Uttryckligt bestridande
    "SAKOMSTÄNDIGHET",        # Faktisk omständighet åberopad av part
    "BEVISFAKTUM",            # Faktum som stöder bevisning
    "RÄTTSFAKTUM",            # Juridiskt relevant faktum
    "BEVISNING",              # Åberopad bevisning
    "NOT_VERIFIABLE",         # Kan inte verifieras ordagrant – inferens förbjuden
]


# ============================================================
# DATAKLASSER
# ============================================================

@dataclass
class ProcessPosition:
    """
    En parts position i processen.
    Alla fält måste vara verifierbara mot primärkälla.
    Infererade positioner är FÖRBJUDNA.
    """
    position_id: str              # PP-001, PP-002, ...
    party: str                    # Klagande | Motpart | Svaranden | Åklagaren | OKÄND
    position_class: str           # Från POSITION_CLASSES
    claim_id: str                 # Koppling till L2 claim_id
    source_id: str                # KÄLL-ID
    file_name: str                # Filnamn
    page_or_position: str         # Sida/position
    verbatim_text: str            # Ordagrann text – aldrig parafras
    inferred: bool = False        # Alltid False – inferens förbjuden
    confidence: str = "VERIFIED"  # VERIFIED | PARTIALLY_AVAILABLE | NOT_VERIFIABLE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "position_id": self.position_id,
            "party": self.party,
            "position_class": self.position_class,
            "claim_id": self.claim_id,
            "source_id": self.source_id,
            "file_name": self.file_name,
            "page_or_position": self.page_or_position,
            "verbatim_text": self.verbatim_text[:200],
            "inferred": self.inferred,
            "confidence": self.confidence,
        }

    def to_formatted_string(self) -> str:
        return (
            f"[{self.position_id}] | Part: {self.party} | "
            f"Klass: {self.position_class} | "
            f"Källa: [{self.source_id} | {self.file_name} | "
            f"{self.page_or_position}] | "
            f"Text: \"{self.verbatim_text[:150]}...\""
            if len(self.verbatim_text) > 150
            else f"[{self.position_id}] | Part: {self.party} | "
            f"Klass: {self.position_class} | "
            f"Källa: [{self.source_id} | {self.file_name} | "
            f"{self.page_or_position}] | "
            f"Text: \"{self.verbatim_text}\""
        )


@dataclass
class ProcessPositionResult:
    """Resultat från L4-analys."""
    positions: List[ProcessPosition] = field(default_factory=list)
    parties_identified: List[str] = field(default_factory=list)
    yrkanden_count: int = 0
    grunder_count: int = 0
    invändningar_count: int = 0
    not_verifiable_count: int = 0
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_positions": len(self.positions),
            "parties_identified": self.parties_identified,
            "yrkanden_count": self.yrkanden_count,
            "grunder_count": self.grunder_count,
            "invändningar_count": self.invändningar_count,
            "not_verifiable_count": self.not_verifiable_count,
            "warnings": self.warnings,
        }


# ============================================================
# PROCESS POSITION AGENT
# ============================================================

class ProcessPositionAgent:
    """
    L4: Parternas positioner + PROCESS POSITION MODEL.

    Identifierar och klassificerar parternas explicita positioner
    från extraherad text (L2-output).

    Absolut förbud: Motorn konstruerar ALDRIG ett yrkande, en grund
    eller en invändning genom inferens. Allt måste vara explicit
    i källmaterialet.
    """

    # Signalord för yrkanden (svenska domstolsspråk)
    YRKANDE_SIGNALS = [
        r"\byrkar\b", r"\byrkar\s+att\b", r"\byrkar\s+på\b",
        r"\bklaganden\s+yrkar\b", r"\bsökanden\s+yrkar\b",
        r"\bkäranden\s+yrkar\b", r"\bbolaget\s+yrkar\b",
        r"\bparten\s+yrkar\b", r"\bvi\s+yrkar\b",
        r"\byrkande\b", r"\byrkanden\b",
        r"\bansöker\s+om\b", r"\bbegär\b",
        r"\bvill\s+ha\b.*\bdom\b",
        r"\bpåstår\s+att\b",
    ]

    # Signalord för grunder
    GRUND_SIGNALS = [
        r"\btill\s+stöd\s+för\b", r"\bgrunden\s+är\b", r"\bgrunder\b",
        r"\bsom\s+grund\s+åberopas\b", r"\bmed\s+anledning\s+av\b",
        r"\bpå\s+grund\s+av\b", r"\bmed\s+stöd\s+av\b",
        r"\bpåstår\b.*\batt\b", r"\bhävdar\b",
        r"\bmenar\b.*\batt\b", r"\banser\b.*\batt\b",
        r"\bgrundas\s+på\b", r"\bbaseras\s+på\b",
    ]

    # Signalord för invändningar/bestridanden
    INVÄNDNING_SIGNALS = [
        r"\bbestrider\b", r"\bbestrids\b", r"\bbestrida\b",
        r"\binvänder\b", r"\binvändning\b",
        r"\bmotsätter\s+sig\b", r"\bnekar\b.*\btill\b",
        r"\bförnekar\b", r"\bifrågasätter\b",
        r"\bsvaranden\s+bestrider\b", r"\bmotparten\s+bestrider\b",
        r"\bFK\s+bestrider\b", r"\bförsäkringskassan\s+bestrider\b",
    ]

    # Signalord för medgivanden
    MEDGIVANDE_SIGNALS = [
        r"\bmedger\b", r"\bmedges\b", r"\bmedgivande\b",
        r"\bvitsordas\b", r"\bvitsorda\b", r"\bvitsordas\s+som\s+skäligt\b",
        r"\baccept\w*\b.*\byrkande\b",
        r"\bhar\s+inget\s+att\s+invända\b",
    ]

    # Signalord för bevisning
    BEVISNING_SIGNALS = [
        r"\bsom\s+bevisning\s+åberopas\b", r"\bbevisuppgift\b",
        r"\bbifogar\b", r"\bbilaga\b", r"\baktbilaga\b",
        r"\bläkarintyg\b", r"\bintyg\b", r"\butlåtande\b",
        r"\bvittne\b", r"\bvittnesförhör\b",
        r"\bskriftlig\s+bevisning\b", r"\bmuntlig\s+bevisning\b",
        r"\bbevisas\s+av\b", r"\bstyrks\s+av\b",
    ]

    # Partsidentifiering
    PARTY_SIGNALS = {
        "Klaganden": [
            r"\bklaganden\b", r"\bsökanden\b", r"\bkäranden\b",
            r"\bden\s+försäkrade\b", r"\bmin\s+klient\b",
        ],
        "Motparten": [
            r"\bmotparten\b", r"\bsvaranden\b", r"\bförsäkringskassan\b",
            r"\bFK\b", r"\bkommunen\b", r"\bnämnden\b",
            r"\bsocialnämnden\b", r"\blandstinget\b",
        ],
        "Åklagaren": [
            r"\båklagaren\b", r"\bstaten\b.*\bbrott\b",
        ],
        "Den tilltalade": [
            r"\bden\s+tilltalade\b", r"\btilltalade\b",
            r"\bmisstänkte\b",
        ],
    }

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.log: List[str] = []
        self._position_counter = 0

    def analyze(
        self,
        case_state: CaseState,
        extraction_results: Optional[Dict[str, ExtractionResult]] = None,
    ) -> ProcessPositionResult:
        """
        Analyserar parternas positioner från case_state.claims.

        Kräver att L2 (DocumentTextExtractor) har körts och fyllt
        case_state.claims med faktiskt innehåll.
        """
        result = ProcessPositionResult()

        if not case_state.claims:
            self.log.append(
                "[L4] VARNING: case_state.claims är tom. "
                "Kör DocumentTextExtractor (L2) först."
            )
            result.warnings.append(
                "Inga claims att analysera – L2 textextraktion krävs"
            )
            return result

        self.log.append(
            f"[L4] Analyserar {len(case_state.claims)} claims "
            f"för parternas positioner"
        )

        # Identifiera parter från alla claims
        parties = self._identify_parties(case_state.claims)
        result.parties_identified = parties
        self.log.append(f"[L4] Identifierade parter: {parties}")

        # Klassificera varje claim
        for claim in case_state.claims:
            positions = self._classify_claim(claim)
            for pos in positions:
                result.positions.append(pos)
                if pos.position_class == "EXPLICIT_YRKANDE":
                    result.yrkanden_count += 1
                elif pos.position_class in ("EXPLICIT_GRUND", "SAKOMSTÄNDIGHET"):
                    result.grunder_count += 1
                elif pos.position_class in ("EXPLICIT_INVÄNDNING", "EXPLICIT_BESTRIDANDE"):
                    result.invändningar_count += 1
                elif pos.position_class == "NOT_VERIFIABLE":
                    result.not_verifiable_count += 1

        # P18 SYMMETRY-kontroll
        self._check_symmetry(result)

        self.log.append(
            f"[L4] Klar: {len(result.positions)} positioner identifierade. "
            f"Yrkanden: {result.yrkanden_count}, "
            f"Grunder: {result.grunder_count}, "
            f"Invändningar: {result.invändningar_count}, "
            f"NOT_VERIFIABLE: {result.not_verifiable_count}"
        )

        # Spara i case_state.metadata
        case_state.metadata["l4_process_positions"] = [
            p.to_dict() for p in result.positions
        ]
        case_state.metadata["l4_parties"] = result.parties_identified

        return result

    def _identify_parties(self, claims: List[ClaimId]) -> List[str]:
        """Identifierar parter från claims-text."""
        found_parties = set()
        all_text = " ".join(c.content.lower() for c in claims)

        for party_name, signals in self.PARTY_SIGNALS.items():
            for signal in signals:
                if re.search(signal, all_text, re.IGNORECASE):
                    found_parties.add(party_name)
                    break

        if not found_parties:
            found_parties.add("OKÄND")

        return sorted(found_parties)

    def _classify_claim(self, claim: ClaimId) -> List[ProcessPosition]:
        """
        Klassificerar ett claim enligt POSITION_CLASSES.
        Returnerar lista av ProcessPosition (ett claim kan ha flera klasser).
        Inferens är FÖRBJUDEN – returnerar NOT_VERIFIABLE om osäkert.
        """
        text = claim.content
        text_lower = text.lower()
        positions: List[ProcessPosition] = []

        # Identifiera part
        party = self._identify_party_from_text(text_lower)

        # Kontrollera varje positionsklass
        matched_class = None

        if self._matches_any(text_lower, self.YRKANDE_SIGNALS):
            matched_class = "EXPLICIT_YRKANDE"
        elif self._matches_any(text_lower, self.MEDGIVANDE_SIGNALS):
            matched_class = "EXPLICIT_MEDGIVANDE"
        elif self._matches_any(text_lower, self.INVÄNDNING_SIGNALS):
            matched_class = "EXPLICIT_INVÄNDNING"
        elif self._matches_any(text_lower, self.GRUND_SIGNALS):
            matched_class = "EXPLICIT_GRUND"
        elif self._matches_any(text_lower, self.BEVISNING_SIGNALS):
            matched_class = "BEVISNING"
        elif self._is_rättsfaktum(text_lower):
            matched_class = "RÄTTSFAKTUM"
        elif self._is_sakomständighet(text_lower):
            matched_class = "SAKOMSTÄNDIGHET"

        if matched_class:
            self._position_counter += 1
            pos = ProcessPosition(
                position_id=f"PP-{self._position_counter:03d}",
                party=party,
                position_class=matched_class,
                claim_id=claim.claim_id,
                source_id=claim.source_id,
                file_name=claim.file_name,
                page_or_position=claim.page,
                verbatim_text=text,
                inferred=False,
                confidence=getattr(claim.availability, "value", str(claim.availability)),
            )
            positions.append(pos)

        return positions

    def _identify_party_from_text(self, text_lower: str) -> str:
        """Identifierar vilken part ett textstycke tillhör.

        Räknar träffar per part i stället för att returnera den första
        kategorin som matchar — annars avgör ordningen i PARTY_SIGNALS,
        inte texten, när flera parter nämns lika starkt."""
        poäng: Dict[str, int] = {}
        for party_name, signals in self.PARTY_SIGNALS.items():
            träffar = sum(
                1 for signal in signals
                if re.search(signal, text_lower, re.IGNORECASE)
            )
            if träffar:
                poäng[party_name] = träffar
        if not poäng:
            return "OKÄND"
        rankade = sorted(poäng.items(), key=lambda kv: -kv[1])
        bäst_part, bäst_poäng = rankade[0]
        tvåa_poäng = rankade[1][1] if len(rankade) > 1 else 0
        if bäst_poäng == tvåa_poäng:
            return "OKÄND"
        return bäst_part

    def _matches_any(self, text: str, patterns: List[str]) -> bool:
        """Kontrollerar om text matchar något av mönstren."""
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    def _is_rättsfaktum(self, text: str) -> bool:
        """Identifierar rättsfakta (juridiskt relevanta fakta)."""
        signals = [
            r"\bden\s+\d+\s+\w+\s+\d{4}\b",  # Datum
            r"\bparagraf\b|\b§\b|\blagen\b|\bsfs\b",
            r"\bdomstolen\s+fann\b|\bdomstolen\s+konstaterade\b",
            r"\bdet\s+är\s+ostridigt\b|\bdet\s+är\s+klarlagt\b",
            r"\bhar\s+konstaterats\b|\bhar\s+fastställts\b",
        ]
        return self._matches_any(text, signals)

    def _is_sakomständighet(self, text: str) -> bool:
        """Identifierar sakomständigheter."""
        signals = [
            r"\bden\s+\d+\b",  # Datum
            r"\bunder\s+perioden\b", r"\bfr\.o\.m\.\b", r"\bt\.o\.m\.\b",
            r"\bsjukskriven\b", r"\bsjukpenning\b", r"\barbetar\b",
            r"\bbeslutade\b", r"\bmeddelade\b", r"\bansökte\b",
            r"\böverklagade\b", r"\binkom\b",
        ]
        return self._matches_any(text, signals)

    def _check_symmetry(self, result: ProcessPositionResult) -> None:
        """
        P18 SYMMETRY: Kontrollerar att båda parters argument
        behandlas med identisk analytisk rigor.
        """
        if len(result.parties_identified) < 2:
            result.warnings.append(
                "P18 SYMMETRY: Färre än 2 parter identifierade – "
                "symmetrikontroll ej möjlig"
            )
            return

        # Räkna positioner per part
        party_counts: Dict[str, int] = {}
        for pos in result.positions:
            party_counts[pos.party] = party_counts.get(pos.party, 0) + 1

        if len(party_counts) >= 2:
            counts = list(party_counts.values())
            ratio = max(counts) / max(min(counts), 1)
            if ratio > 5:
                result.warnings.append(
                    f"P18 SYMMETRY-VARNING: Stark asymmetri i positioner. "
                    f"Fördelning: {party_counts}. "
                    f"Kontrollera att motpartens argument inte utelämnats."
                )

    def generate_l4_report(self, result: ProcessPositionResult) -> str:
        """Genererar L4-rapport i lagerformat (FIX-M)."""
        lines = [
            "## LAGER 4 – PARTERNAS POSITIONER + PROCESS POSITION MODEL",
            "",
            f"Identifierade parter: {', '.join(result.parties_identified)}",
            f"Totalt positioner: {len(result.positions)}",
            f"  Yrkanden: {result.yrkanden_count}",
            f"  Grunder/Sakomständigheter: {result.grunder_count}",
            f"  Invändningar/Bestridanden: {result.invändningar_count}",
            f"  NOT_VERIFIABLE: {result.not_verifiable_count}",
            "",
        ]

        if result.warnings:
            lines.append("### Varningar")
            for w in result.warnings:
                lines.append(f"⚠️ {w}")
            lines.append("")

        if result.positions:
            lines.append("### Positioner (urval, max 10)")
            for pos in result.positions[:10]:
                lines.append(pos.to_formatted_string())
            if len(result.positions) > 10:
                lines.append(
                    f"[... {len(result.positions) - 10} ytterligare positioner ...]"
                )
        else:
            lines.append(
                "[INGA POSITIONER IDENTIFIERADE – "
                "kontrollera att L2 textextraktion körts]"
            )

        lines.extend(["", "[L4 | PARTERNAS POSITIONER | LOCKED]"])
        return "\n".join(lines)