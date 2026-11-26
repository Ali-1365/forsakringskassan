#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLAIM CLASSIFIER – SEMANTISK JURIDISK KLASSIFICERING
SVENSK FORENSIC COURT AUDIT ENGINE v10.3-UPDATED
Datum: 2026-08-23

Klassificerar extraherade textsegment juridiskt utan tolkning.
Skiljer mellan: DOM_PREMISS, YRKANDE, GRUND, INVÄNDNING,
SAKOMSTÄNDIGHET, BEVISNING, RÄTTSFAKTUM, LAGRUM, ÖVRIGT.

ABSOLUTA REGLER:
- Klassificering baseras på textens faktiska innehåll – aldrig inferens
- Osäker klassificering → ÖVRIGT (aldrig gissning)
- Ingen juridisk slutsats dras från klassificeringen
- Original-text bevaras oförändrad
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any
from enum import Enum

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from forensic_engine_v10_3_canonical import ClaimId, Availability, CaseState
from document_text_extractor import TextSegment


# ============================================================
# JURIDISKA KLASSER
# ============================================================

class JuridiskKlass(Enum):
    """Juridisk klassificering av ett textsegment."""
    DOM_PREMISS        = "DOM_PREMISS"         # Domstolens egna slutsatser/fynd
    YRKANDE            = "YRKANDE"             # Explicit yrkande från part
    GRUND              = "GRUND"               # Grund för yrkande
    INVÄNDNING         = "INVÄNDNING"          # Invändning/bestridande
    MEDGIVANDE         = "MEDGIVANDE"          # Medgivande
    SAKOMSTÄNDIGHET    = "SAKOMSTÄNDIGHET"     # Faktisk omständighet
    BEVISNING          = "BEVISNING"           # Åberopad bevisning
    RÄTTSFAKTUM        = "RÄTTSFAKTUM"         # Juridiskt relevant faktum
    LAGRUM             = "LAGRUM"              # Lagrum/paragraf
    PREJUDIKAT         = "PREJUDIKAT"          # Rättspraxis
    VITTNESUTSAGA      = "VITTNESUTSAGA"       # Vittnes uppgifter
    FÖRHÖRSUTSAGA      = "FÖRHÖRSUTSAGA"       # Misstänkts/parts uppgifter i förhör
    MYNDIGHETSBESLUT   = "MYNDIGHETSBESLUT"    # Myndighetsbeslut
    KORRESPONDENS      = "KORRESPONDENS"       # E-post/brev/kommunikation
    TEKNISKT_FAKTUM    = "TEKNISKT_FAKTUM"     # Tekniska/medicinska fakta
    TIDSFRIST          = "TIDSFRIST"           # Processuell tidsfrist
    ÖVRIGT             = "ÖVRIGT"              # Oklassificerat


@dataclass
class KlassificeratSegment:
    """Ett textsegment med juridisk klassificering."""
    segment: TextSegment
    juridisk_klass: JuridiskKlass
    confidence: str          # HÖG | MEDEL | LÅG
    matchade_signaler: List[str] = field(default_factory=list)
    part: str = "OKÄND"      # Klaganden | Motparten | Domstolen | OKÄND
    
    def to_claim_id(self, counter: int) -> ClaimId:
        """Konverterar till ClaimId med juridisk klass som påståendetyp."""
        return ClaimId(
            claim_id=f"C-{counter:03d}",
            content=self.segment.text[:500],
            text_trunkerad=len(self.segment.text) > 500,
            source_id=self.segment.file_id,
            file_name=os.path.basename(self.segment.file_path),
            page=self.segment.page_or_position,
            date="SAKNAS",
            version="SAKNAS",
            claim_type=self.juridisk_klass.value,
            availability=Availability.VERIFIED
            if self.confidence == "HÖG"
            else Availability.PARTIALLY_AVAILABLE,
        )


# ============================================================
# CLAIM CLASSIFIER
# ============================================================

class ClaimClassifier:
    """
    Semantisk juridisk klassificering av textsegment.
    
    Klassificerar baserat på:
    1. Signalord och fraser (primär metod)
    2. Dokumentkontext (filnamn, dokumenttyp)
    3. Strukturella mönster (datum, lagrum, citat)
    
    Osäker klassificering → ÖVRIGT (aldrig gissning).
    """

    # ── DOM-PREMISSER ──────────────────────────────────────────
    DOM_PREMISS_SIGNALS = [
        r"\bdomstolen\s+finner\b", r"\bdomstolen\s+konstaterar\b",
        r"\bdomstolen\s+bedömer\b", r"\bdomstolen\s+anser\b",
        r"\brätten\s+finner\b", r"\brätten\s+konstaterar\b",
        r"\brätten\s+bedömer\b", r"\brätten\s+anser\b",
        r"\bdet\s+är\s+utrett\b", r"\bdet\s+är\s+styrkt\b",
        r"\bdet\s+är\s+klarlagt\b", r"\bdet\s+är\s+ostridigt\b",
        r"\bav\s+utredningen\s+framgår\b",
        r"\bdet\s+har\s+framkommit\s+att\b",
        r"\bförvaltningsrätten\s+gör\s+följande\b",
        r"\bkammarrätten\s+gör\s+följande\b",
        r"\btingsrätten\s+gör\s+följande\b",
        r"\brätten\s+gör\s+följande\s+bedömning\b",
        r"\bdomskäl\b", r"\bdomslut\b",
        r"\bmed\s+hänsyn\s+till\s+det\s+anförda\b",
        r"\bpå\s+grund\s+av\s+det\s+anförda\b",
    ]

    # ── YRKANDEN ───────────────────────────────────────────────
    YRKANDE_SIGNALS = [
        r"\byrkar\b", r"\byrkar\s+att\b", r"\byrkar\s+på\b",
        r"\byrkar\s+ersättning\b", r"\byrkar\s+skadestånd\b",
        r"\bklaganden\s+yrkar\b", r"\bsökanden\s+yrkar\b",
        r"\bkäranden\s+yrkar\b", r"\bbolaget\s+yrkar\b",
        r"\bparten\s+yrkar\b", r"\bvi\s+yrkar\b",
        r"\byrkande\b", r"\byrkanden\b",
        r"\bansöker\s+om\b", r"\bbegär\b.*\bdom\b",
        r"\bvill\s+ha\b.*\bdom\b",
        r"\bönskar\b.*\bi\s+första\s+hand\b",
        r"\bi\s+första\s+hand\b.*\byrkar\b",
        r"\bi\s+andra\s+hand\b.*\byrkar\b",
        r"\bprimärt\s+yrkar\b", r"\bsubsidiärt\s+yrkar\b",
    ]

    # ── GRUNDER ────────────────────────────────────────────────
    GRUND_SIGNALS = [
        r"\btill\s+stöd\s+för\b", r"\bgrunden\s+är\b",
        r"\bsom\s+grund\s+åberopas\b", r"\bgrunder\b.*\bföljande\b",
        r"\bmed\s+anledning\s+av\b", r"\bpå\s+grund\s+av\b",
        r"\bmed\s+stöd\s+av\b", r"\bhävdar\b",
        r"\bmenar\b.*\batt\b", r"\banser\b.*\batt\b",
        r"\bgrundas\s+på\b", r"\bbaseras\s+på\b",
        r"\bpåstår\b.*\batt\b",
        r"\bsom\s+skäl\s+för\b",
        r"\bav\s+följande\s+skäl\b",
    ]

    # ── INVÄNDNINGAR ───────────────────────────────────────────
    INVÄNDNING_SIGNALS = [
        r"\bbestrider\b", r"\bbestrids\b", r"\bbestrida\b",
        r"\binvänder\b", r"\binvändning\b",
        r"\bmotsätter\s+sig\b", r"\bnekar\b.*\btill\b",
        r"\bförnekar\b", r"\bifrågasätter\b",
        r"\bsvaranden\s+bestrider\b", r"\bmotparten\s+bestrider\b",
        r"\bFK\s+bestrider\b",
        r"\bförsäkringskassan\s+bestrider\b",
        r"\bbestrider\s+bifall\b",
        r"\bbestrider\s+ersättning\b",
    ]

    # ── MEDGIVANDEN ────────────────────────────────────────────
    MEDGIVANDE_SIGNALS = [
        r"\bmedger\b", r"\bmedges\b", r"\bmedgivande\b",
        r"\bvitsordas\b", r"\bvitsorda\b",
        r"\bvitsordas\s+som\s+skäligt\b",
        r"\bhar\s+inget\s+att\s+invända\b",
        r"\baccept\w*\b.*\byrkande\b",
        r"\bmedger\s+att\b",
    ]

    # ── BEVISNING ──────────────────────────────────────────────
    BEVISNING_SIGNALS = [
        r"\bsom\s+bevisning\s+åberopas\b",
        r"\bbevisuppgift\b", r"\bbevisning\b",
        r"\bbifogar\b", r"\bbilaga\b", r"\baktbilaga\b",
        r"\bläkarintyg\b", r"\bintyg\b", r"\butlåtande\b",
        r"\bvittne\b", r"\bvittnesförhör\b",
        r"\bskriftlig\s+bevisning\b", r"\bmuntlig\s+bevisning\b",
        r"\bbevisas\s+av\b", r"\bstyrks\s+av\b",
        r"\bbevisar\b", r"\bstyrker\b",
        r"\bsom\s+bevis\s+åberopas\b",
        r"\binspelning\b", r"\btranskription\b",
        r"\bljudfil\b", r"\bljudinspelning\b",
        r"\bskärmbild\b", r"\bskärmavbild\b",
        r"\breskontra\b", r"\bfaktura\b.*\bbevis\b",
    ]

    # ── RÄTTSFAKTA ─────────────────────────────────────────────
    RÄTTSFAKTUM_SIGNALS = [
        r"\bdet\s+är\s+ostridigt\s+att\b",
        r"\bdet\s+är\s+klarlagt\s+att\b",
        r"\bhar\s+konstaterats\s+att\b",
        r"\bhar\s+fastställts\s+att\b",
        r"\bär\s+bevisat\s+att\b",
        r"\bär\s+styrkt\s+att\b",
        r"\bframgår\s+av\s+utredningen\b",
        r"\bframgår\s+av\s+materialet\b",
        r"\bdet\s+är\s+utrett\s+att\b",
        r"\bdet\s+framgår\s+att\b",
    ]

    # ── LAGRUM ─────────────────────────────────────────────────
    LAGRUM_SIGNALS = [
        r"\b\d+\s*kap\.\s*\d+\s*§\b",
        r"\b§\s*\d+\b",
        r"\bsfs\s*\d{4}:\d+\b",
        r"\blagen\s*\(\s*\d{4}:\d+\s*\)\b",
        r"\bförordningen\s*\(\s*\d{4}:\d+\s*\)\b",
        r"\brättegångsbalken\b", r"\bbrottsbalken\b",
        r"\bförvaltningslagen\b", r"\bförvaltningsprocesslagen\b",
        r"\bsocialförsäkringsbalken\b", r"\bsfb\b",
        r"\bsocialtjänstlagen\b", r"\bsol\b",
        r"\blvu\b", r"\blvm\b",
        r"\bpatientskadelagen\b",
        r"\bjordabalken\b",
    ]

    # ── PREJUDIKAT ─────────────────────────────────────────────
    PREJUDIKAT_SIGNALS = [
        r"\bnja\s+\d{4}\b", r"\bhfd\s+\d{4}\b",
        r"\brd\s+\d{4}\b", r"\brå\s+\d{4}\b",
        r"\bprejudikat\b", r"\bvägledande\s+avgörande\b",
        r"\bhögsta\s+domstolen\s+har\s+uttalat\b",
        r"\bhögsta\s+förvaltningsdomstolen\s+har\b",
        r"\bpraxis\b.*\bvisar\b",
        r"\bav\s+praxis\s+framgår\b",
    ]

    # ── VITTNESUTSAGOR ─────────────────────────────────────────
    VITTNE_SIGNALS = [
        r"\bvittnet\s+uppger\b", r"\bvittnet\s+berättar\b",
        r"\bvittnet\s+har\s+uppgett\b",
        r"\bvittnesförhör\b",
        r"\bvittnet\b.*\buppger\b",
        r"\bhar\s+hörts\s+som\s+vittne\b",
        r"\bvittnar\b",
    ]

    # ── FÖRHÖRSUTSAGOR ─────────────────────────────────────────
    FÖRHÖR_SIGNALS = [
        r"\bmisstänkt\s+uppger\b", r"\bmisstänkt\s+berättar\b",
        r"\bmisstänkt\s+har\s+uppgett\b",
        r"\bden\s+misstänkte\s+uppger\b",
        r"\bklaganden\s+uppger\b", r"\bklaganden\s+berättar\b",
        r"\bparten\s+uppger\b",
        r"\bförhör\s+med\b",
        r"\bhar\s+hörts\s+i\s+förhör\b",
        r"\bpolisförhör\b",
        r"\buppger\s+i\s+förhör\b",
        r"\bberättar\s+i\s+förhör\b",
    ]

    # ── MYNDIGHETSBESLUT ───────────────────────────────────────
    MYNDIGHET_SIGNALS = [
        r"\bbeslutade\b.*\batt\b",
        r"\bbeslut\s+om\b",
        r"\bförsäkringskassan\s+beslutade\b",
        r"\bförsäkringskassan\s+har\s+beslutat\b",
        r"\bsocialnämnden\s+beslutade\b",
        r"\bkommunen\s+beslutade\b",
        r"\bmyndigheten\s+beslutade\b",
        r"\bbeslutet\s+innebär\b",
        r"\bbeslutet\s+avser\b",
        r"\böverklagat\s+beslut\b",
    ]

    # ── KORRESPONDENS ──────────────────────────────────────────
    KORRESPONDENS_SIGNALS = [
        r"\be-post\b", r"\bemail\b", r"\bmail\b",
        r"\bbrev\b.*\bdaterat\b", r"\bskrivelse\b",
        r"\bmeddelande\b.*\bskickat\b",
        r"\bkommunikation\b.*\bmellan\b",
        r"\bkorrespondens\b",
        r"\bsms\b",
        r"@\w+\.\w+",  # E-postadress
        r"\bskickade\b.*\bmail\b",
        r"\bskickade\b.*\bbrev\b",
    ]

    # ── TEKNISKA FAKTA ─────────────────────────────────────────
    TEKNISKT_SIGNALS = [
        r"\bsha-256\b", r"\bhash\b", r"\bmd5\b",
        r"\bmetadata\b", r"\bexif\b",
        r"\bdiagnos\b", r"\bdiagnostiserad\b",
        r"\bläkarens\s+bedömning\b",
        r"\bmedicinsk\s+bedömning\b",
        r"\bteknisk\s+analys\b",
        r"\bforensisk\s+analys\b",
        r"\bautogiro\b", r"\bfaktura\b.*\bförfallodag\b",
        r"\breskontra\b",
        r"\bkontonummer\b", r"\bbankgiro\b",
    ]

    # ── TIDSFRISTER ────────────────────────────────────────────
    TIDSFRIST_SIGNALS = [
        r"\bsenast\b.*\d{4}-\d{2}-\d{2}\b",
        r"\bfrist\b.*\blöper\b",
        r"\böverklagandefrist\b",
        r"\bpreskription\b",
        r"\binom\s+\d+\s+dagar\b",
        r"\binom\s+\d+\s+veckor\b",
        r"\binom\s+\d+\s+månader\b",
        r"\bsenast\s+den\b",
        r"\bfrist\b.*\d{4}-\d{2}-\d{2}\b",
        r"\bex\s+lege\b",
        r"\bautomatiskt\b.*\bhävas\b",
    ]

    # ── PARTSIDENTIFIERING ─────────────────────────────────────
    PART_SIGNALS = {
        "Klaganden": [
            r"\bklaganden\b", r"\bsökanden\b", r"\bkäranden\b",
            r"\bden\s+försäkrade\b",
        ],
        "Den tilltalade": [
            r"\bden\s+tilltalade\b", r"\btilltalade\b", r"\btilltalad\b",
            r"\bden\s+misstänkte\b", r"\bmisstänkte\b", r"\bmisstänkt\b",
        ],
        "Motparten": [
            r"\bmotparten\b", r"\bsvaranden\b",
            r"\bförsäkringskassan\b", r"\bfk\b",
            r"\bkommunen\b", r"\bnämnden\b",
            r"\bsocialnämnden\b", r"\blandstinget\b",
        ],
        "Domstolen": [
            r"\bdomstolen\b", r"\brätten\b",
            r"\btingsrätten\b", r"\bhovrätten\b",
            r"\bförvaltningsrätten\b", r"\bkammarrätten\b",
            r"\bhfd\b", r"\bhd\b",
        ],
        "Åklagaren": [
            r"\båklagaren\b", r"\bstaten\b.*\bbrott\b",
            r"\bpolis\b", r"\butredaren\b",
        ],
    }

    # ── DOKUMENTTYP-KONTEXT ────────────────────────────────────
    DOKUMENTTYP_KONTEXT = {
        "dom": JuridiskKlass.DOM_PREMISS,
        "beslut": JuridiskKlass.MYNDIGHETSBESLUT,
        "förhör": JuridiskKlass.FÖRHÖRSUTSAGA,
        "vittne": JuridiskKlass.VITTNESUTSAGA,
        "transkription": JuridiskKlass.FÖRHÖRSUTSAGA,
        "inlaga": JuridiskKlass.YRKANDE,
        "stämning": JuridiskKlass.YRKANDE,
        "överklagande": JuridiskKlass.YRKANDE,
        "yttrande": JuridiskKlass.GRUND,
        "läkarintyg": JuridiskKlass.BEVISNING,
        "intyg": JuridiskKlass.BEVISNING,
        "reskontra": JuridiskKlass.TEKNISKT_FAKTUM,
        "faktura": JuridiskKlass.TEKNISKT_FAKTUM,
        "protokoll": JuridiskKlass.SAKOMSTÄNDIGHET,
        "pm": JuridiskKlass.SAKOMSTÄNDIGHET,
        "epost": JuridiskKlass.KORRESPONDENS,
        "mail": JuridiskKlass.KORRESPONDENS,
        "brev": JuridiskKlass.KORRESPONDENS,
    }

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.log: List[str] = []

    def classify_segment(
        self,
        segment: TextSegment,
        document_context: str = "",
    ) -> KlassificeratSegment:
        """
        Klassificerar ett textsegment juridiskt.
        
        Args:
            segment: Textsegment att klassificera
            document_context: Filnamn/dokumenttyp för kontextuell hjälp
        
        Returns:
            KlassificeratSegment med juridisk klass och confidence
        """
        text = segment.text
        text_lower = text.lower()
        doc_lower = (document_context or segment.file_path).lower()

        # Identifiera part
        part = self._identify_part(text_lower)

        # Klassificera med prioritetsordning
        klass, confidence, signaler = self._classify_text(text_lower, doc_lower)

        result = KlassificeratSegment(
            segment=segment,
            juridisk_klass=klass,
            confidence=confidence,
            matchade_signaler=signaler,
            part=part,
        )

        if self.verbose:
            self.log.append(
                f"[CLASSIFIER] {segment.file_id} | {segment.page_or_position} | "
                f"{klass.value} ({confidence}) | Part: {part}"
            )

        return result

    def classify_all(
        self,
        case_state: CaseState,
        segments_by_file: Optional[Dict[str, List[TextSegment]]] = None,
    ) -> List[KlassificeratSegment]:
        """
        Klassificerar alla claims i case_state och uppdaterar claim_type.
        
        Kan ta emot segments_by_file för bättre dokumentkontext.
        """
        klassificerade: List[KlassificeratSegment] = []
        claim_counter = 1

        self.log.append(
            f"[CLASSIFIER] Klassificerar {len(case_state.claims)} claims"
        )

        for claim in case_state.claims:
            # Skapa ett temporärt TextSegment från claim
            seg = TextSegment(
                file_id=claim.source_id,
                file_path=claim.file_name,
                page_or_position=claim.page,
                text=claim.content,
                extraction_method="from_claim",
            )

            klass_seg = self.classify_segment(seg, claim.file_name)
            klassificerade.append(klass_seg)

            # Uppdatera claim_type i det befintliga claim-objektet
            claim.claim_type = klass_seg.juridisk_klass.value

        # Statistik
        stats: Dict[str, int] = {}
        for ks in klassificerade:
            k = ks.juridisk_klass.value
            stats[k] = stats.get(k, 0) + 1

        self.log.append(
            f"[CLASSIFIER] Klar. Fördelning: "
            + ", ".join(f"{k}: {v}" for k, v in sorted(stats.items()))
        )

        # Spara i metadata
        case_state.metadata["claim_classification_stats"] = stats

        return klassificerade

    def _classify_text(
        self,
        text_lower: str,
        doc_lower: str,
    ) -> Tuple[JuridiskKlass, str, List[str]]:
        """
        Klassificerar text med prioritetsordning.
        Returnerar (klass, confidence, matchade_signaler).
        """
        # Prioritetsordning: specifika klasser före generella
        checks = [
            (JuridiskKlass.DOM_PREMISS,     self.DOM_PREMISS_SIGNALS,    "HÖG"),
            (JuridiskKlass.TIDSFRIST,        self.TIDSFRIST_SIGNALS,      "HÖG"),
            (JuridiskKlass.LAGRUM,           self.LAGRUM_SIGNALS,         "HÖG"),
            (JuridiskKlass.PREJUDIKAT,       self.PREJUDIKAT_SIGNALS,     "HÖG"),
            (JuridiskKlass.YRKANDE,          self.YRKANDE_SIGNALS,        "HÖG"),
            (JuridiskKlass.MEDGIVANDE,       self.MEDGIVANDE_SIGNALS,     "HÖG"),
            (JuridiskKlass.INVÄNDNING,       self.INVÄNDNING_SIGNALS,     "HÖG"),
            (JuridiskKlass.VITTNESUTSAGA,    self.VITTNE_SIGNALS,         "HÖG"),
            (JuridiskKlass.FÖRHÖRSUTSAGA,    self.FÖRHÖR_SIGNALS,         "HÖG"),
            (JuridiskKlass.MYNDIGHETSBESLUT, self.MYNDIGHET_SIGNALS,      "MEDEL"),
            (JuridiskKlass.KORRESPONDENS,    self.KORRESPONDENS_SIGNALS,  "MEDEL"),
            (JuridiskKlass.BEVISNING,        self.BEVISNING_SIGNALS,      "MEDEL"),
            (JuridiskKlass.RÄTTSFAKTUM,      self.RÄTTSFAKTUM_SIGNALS,    "MEDEL"),
            (JuridiskKlass.TEKNISKT_FAKTUM,  self.TEKNISKT_SIGNALS,       "MEDEL"),
            (JuridiskKlass.GRUND,            self.GRUND_SIGNALS,          "MEDEL"),
            (JuridiskKlass.SAKOMSTÄNDIGHET,  [],                          "LÅG"),
        ]

        for klass, signals, base_confidence in checks:
            if not signals:
                continue
            matched = self._match_signals(text_lower, signals)
            if matched:
                # Dokumentkontext kan höja confidence
                doc_boost = self._doc_context_boost(doc_lower, klass)
                final_confidence = "HÖG" if doc_boost else base_confidence
                return klass, final_confidence, matched

        # Dokumentkontext som fallback
        for keyword, doc_klass in self.DOKUMENTTYP_KONTEXT.items():
            if keyword in doc_lower:
                return doc_klass, "LÅG", [f"doc_context:{keyword}"]

        # Sakomständighet om text innehåller datum eller siffror
        if re.search(r"\b\d{4}-\d{2}-\d{2}\b", text_lower):
            return JuridiskKlass.SAKOMSTÄNDIGHET, "LÅG", ["datum_mönster"]

        return JuridiskKlass.ÖVRIGT, "LÅG", []

    def _match_signals(
        self,
        text: str,
        signals: List[str],
    ) -> List[str]:
        """Returnerar lista av matchade signaler."""
        matched = []
        for signal in signals:
            if re.search(signal, text, re.IGNORECASE):
                matched.append(signal[:40])
                if len(matched) >= 3:
                    break
        return matched

    def _identify_part(self, text_lower: str) -> str:
        """Identifierar vilken part texten tillhör.

        Räknar TRÄFFAR per part i stället för att returnera den första
        kategorin som matchar — annars avgör ordningen i PART_SIGNALS,
        inte texten, när flera parter nämns lika starkt."""
        poäng: Dict[str, int] = {}
        for part_name, signals in self.PART_SIGNALS.items():
            träffar = sum(
                1 for signal in signals
                if re.search(signal, text_lower, re.IGNORECASE)
            )
            if träffar:
                poäng[part_name] = träffar
        if not poäng:
            return "OKÄND"
        rankade = sorted(poäng.items(), key=lambda kv: -kv[1])
        bäst_part, bäst_poäng = rankade[0]
        tvåa_poäng = rankade[1][1] if len(rankade) > 1 else 0
        if bäst_poäng == tvåa_poäng:
            return "OKÄND"
        return bäst_part

    def _doc_context_boost(
        self,
        doc_lower: str,
        klass: JuridiskKlass,
    ) -> bool:
        """Kontrollerar om dokumentkontext stärker klassificeringen."""
        context_map = {
            JuridiskKlass.DOM_PREMISS: ["dom", "beslut", "domskäl"],
            JuridiskKlass.FÖRHÖRSUTSAGA: ["förhör", "transkription"],
            JuridiskKlass.VITTNESUTSAGA: ["vittne", "vittnesförhör"],
            JuridiskKlass.BEVISNING: ["intyg", "läkarintyg", "utlåtande"],
            JuridiskKlass.TEKNISKT_FAKTUM: ["reskontra", "faktura", "kontoutdrag"],
            JuridiskKlass.KORRESPONDENS: ["epost", "mail", "brev", "skrivelse"],
        }
        keywords = context_map.get(klass, [])
        return any(kw in doc_lower for kw in keywords)

    def generate_classification_report(
        self,
        klassificerade: List[KlassificeratSegment],
    ) -> str:
        """Genererar klassificeringsrapport."""
        stats: Dict[str, int] = {}
        for ks in klassificerade:
            k = ks.juridisk_klass.value
            stats[k] = stats.get(k, 0) + 1

        lines = [
            "## CLAIM CLASSIFIER – KLASSIFICERINGSRAPPORT",
            "",
            f"Totalt klassificerade: {len(klassificerade)}",
            "",
            "### Fördelning per juridisk klass",
        ]
        for klass, antal in sorted(stats.items(), key=lambda x: -x[1]):
            lines.append(f"  {klass}: {antal}")

        lines.extend(["", "### Urval (max 10)"])
        for ks in klassificerade[:10]:
            lines.append(
                f"  [{ks.juridisk_klass.value}] ({ks.confidence}) "
                f"Part: {ks.part} | "
                f"{ks.segment.text[:80]}..."
            )

        return "\n".join(lines)