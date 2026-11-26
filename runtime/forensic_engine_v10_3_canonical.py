#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SVENSK FORENSIC COURT AUDIT ENGINE
Version: 10.3-UPDATED 

Källa: SKILL_final.md (kunskapsbas)
Arkitektur: 17-lagers pipeline, dual-mode, 13 guarded state-transitions

ABSOLUTA REGLER:
- Ingen hårdkodad juridisk slutsats, måltyp, bevisvärdering, rättsregel, praxis eller domstol
- Ingen uppdiktad fakta, bevisning, part, rättskälla eller slutsats
- Originalfiler rörs ALDRIG
- Rättskällesökning är verifiering, inte ersättning för juridisk analys
- Systemet saknar dömande mandat – PROVISIONAL JUDGMENT DRAFT ONLY
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import datetime
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple


# ============================================================
# ENUMS – STATE MACHINE
# ============================================================

class PipelineState(Enum):
    INIT = "INIT"
    INGESTING = "INGESTING"
    CLASSIFYING = "CLASSIFYING"
    CAPABILITY_MAPPING = "CAPABILITY_MAPPING"
    RELATION_BUILDING = "RELATION_BUILDING"
    GATING = "GATING"
    SUBSUMPTION = "SUBSUMPTION"
    AUDIT_A = "AUDIT_A"
    AUDIT_B = "AUDIT_B"
    AUDIT_C = "AUDIT_C"
    COUNTER_AUDIT = "COUNTER_AUDIT"
    FALSIFICATION = "FALSIFICATION"
    JUDGMENT_DRAFT = "JUDGMENT_DRAFT"
    SELF_HEALING = "SELF_HEALING"
    COMPLETE = "COMPLETE"
    HARD_STOP = "HARD_STOP"
    REJECTED = "REJECTED"
    # Steg 14: endast tekniskt undantag (infrastrukturfel). Domänspärr ger
    # alltid HARD_STOP, aldrig FAILED.
    FAILED = "FAILED"


class ProcessMode(Enum):
    JUDGMENT_AUDIT = "JUDGMENT_AUDIT"
    JUDGMENT_CONSTRUCTION = "JUDGMENT_CONSTRUCTION"
    UNDEFINED = "UNDEFINED"


class ExecutionMode(Enum):
    """Tvåspårigt exekveringsflöde (Fas 2, MODE_ROUTER state isolation).

    En körning har exakt ett MODE. Läget bestäms före analys och ändras
    aldrig mitt i en körning (RT-H / MODE_SEPARATION).
    """
    JUDGMENT_AUDIT = "JUDGMENT_AUDIT"
    JUDGMENT_CONSTRUCTION = "JUDGMENT_CONSTRUCTION"
    UNDETERMINED = "UNDETERMINED"


class CourtType(Enum):
    CIVIL_COURT = "CIVIL_COURT"
    CRIMINAL_COURT = "CRIMINAL_COURT"
    ADMINISTRATIVE_COURT = "ADMINISTRATIVE_COURT"
    UNKNOWN = "UNKNOWN"


class BaselineState(Enum):
    LOCKED_BASELINE = "LOCKED_BASELINE"
    UNSOLICITED_INPUT = "UNSOLICITED_INPUT"
    UNVERIFIED = "UNVERIFIED"


class EvidenceCategory(Enum):
    CATEGORY_A_STRONG = "CATEGORY_A_STRONG"
    CATEGORY_B_RISK = "CATEGORY_B_RISK"
    UNCLASSIFIED = "UNCLASSIFIED"


class AuditStatus(Enum):
    A = "A"  # VERIFIERAT KORREKT
    B = "B"  # VERIFIERAD AVVIKELSE
    C = "C"  # VERIFIERAD PROCESSUELL AVVIKELSE
    D = "D"  # VERIFIERAD RÄTTSLIG AVVIKELSE
    E = "E"  # VERIFIERAD FAKTISK AVVIKELSE
    F = "F"  # VERIFIERAD BEVISMÄSSIG AVVIKELSE
    G = "G"  # POTENTIELLT RÄTTSLIGT RELEVANT
    H = "H"  # KAN INTE AVGÖRAS
    I = "I"  # OTILLRÄCKLIGT UNDERLAG


class FalsificationVerdict(Enum):
    ROBUST = "ROBUST"
    VULNERABLE = "VULNERABLE"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_RUN = "NOT_RUN"


class AuditControllerVerdict(Enum):
    GODKÄND = "GODKÄND"
    UNDERKÄND = "UNDERKÄND"
    STOPPAD = "STOPPAD"
    FLAGGAD = "FLAGGAD"


# ============================================================
# PRESENTATION DATAKLASSER (Phase 6 — portat från v10-v3)
# ============================================================

@dataclass
class PartyImpactMatrix:
    """Partsimpact-matris (P18 symmetri) — speglar samma CaseState för båda parter."""
    party_label: str
    verified_strengths: List[str] = field(default_factory=list)
    verified_weaknesses: List[str] = field(default_factory=list)
    open_evidence_questions: List[str] = field(default_factory=list)
    procedural_risks: List[str] = field(default_factory=list)
    legal_risks: List[str] = field(default_factory=list)
    action_points: List[str] = field(default_factory=list)


@dataclass
class PresentationViews:
    """Tre vyer (Court / Party / Mediation) från samma CaseState.
    Mediation får ALDRIG skriva över CaseState; endast läsa."""
    court_view: Dict = field(default_factory=dict)
    party_a: Optional[PartyImpactMatrix] = None
    party_b: Optional[PartyImpactMatrix] = None
    mediation: Dict = field(default_factory=dict)
    disclaimer: str = (
        "PROVISORISKT ANALYSUNDERLAG — AI saknar dömande mandat. "
        "Vyer ändrar inte underliggande CaseState."
    )


class HardStopCode(Enum):
    HS01A = "HS01A"  # Central dom saknas (AUDIT)
    HS01B = "HS01B"  # Central processhandling saknas
    HS01C = "HS01C"  # Otillräckligt underlag (CONSTRUCTION)
    HS02 = "HS02"    # Domversion ej verifierbar
    HS03 = "HS03"    # Autenticitet ej verifierbar
    HS04 = "HS04"    # Central bevisning saknas
    HS05 = "HS05"    # Ljud ej verifierbart
    HS06 = "HS06"    # Lagversion ej fastställbar
    HS07 = "HS07"    # Prejudikatets räckvidd ej fastställbar
    HS08 = "HS08"    # Central källmotsägelse olöst
    HS09 = "HS09"    # Förbjuden inferens
    HS09B = "HS09B"  # Låg källtäckning under tröskelvärde
    HS10 = "HS10"    # Cirkulär påverkan
    HS11 = "HS11"    # Subsumtionskedja saknar rättsfaktum
    HS12 = "HS12"    # Negativ bevisstatus saknas
    HS13 = "HS13"    # Ärendenummer ej verifierbart
    HS14 = "HS14"    # Muntlig källa avviker från skriftlig
    HS15 = "HS15"    # FORUM_CONFLICT
    HS16 = "HS16"    # Källkontaminering
    HS17 = "HS17"    # Vittnesutsaga bär ensamt MUST-rekvisit
    HS18 = "HS18"    # Substantiell avvikelse med materiell betydelse
    HS19 = "HS19"    # EXPECTED_NOT_FOUND för materiellt rekvisit
    HS20 = "HS20"    # Processläge ej fastställt / MODE UNDEFINED


class ModeRouter:
    """
    Tvåspårigt exekveringsflöde med state isolation (Fas 2, v10.3).

    En körning har exakt ett MODE. MODE bestäms före analys (efter L1) och
    ändras aldrig mitt i en körning. HS01-splittring (FIX-A, RT-AX):

      - HS01A tillåts ENDAST i JUDGMENT_AUDIT.
        RT-I: en saknad tidigare dom utlöser ALDRIG HS01A i JUDGMENT_CONSTRUCTION.
      - HS01C tillåts ENDAST i JUDGMENT_CONSTRUCTION (otillräckligt underlag).
      - HS01B gäller BÅDA lägen (central processhandling saknas).
    """

    DOM_KW = ("dom", "beslut", "domslut", "tingsrätt", "underrättelse",
              "målnummer", "domstols")
    PROCESS_KW = ("stämningsansökan", "ansökan", "inlaga", "protokoll",
                  "förhandling", "överklagande", "yttrande", "genmäle",
                  "bestridande", "medgivande", "aktbilaga")

    def route(self, records, root_dirs=None):
        """Bestämmer körningsläge. Returnerar (mode, notes, hs_code)."""
        notes = []
        if self._has_prior_decision(records):
            notes.append(
                "Tidigare dom/beslut indikerad via filnamn/sökväg → JUDGMENT_AUDIT."
            )
            return ExecutionMode.JUDGMENT_AUDIT, notes, None

        has_process = self._has_process_material(records, root_dirs)
        if has_process or records:
            notes.append(
                "Ingen tidigare dom/beslut identifierad; material finns → "
                "JUDGMENT_CONSTRUCTION. Frånvaro av dom utlöser INTE HS01A [RT-I]."
            )
            if not records:
                # Processmaterial indikerat men inga records — otillräckligt underlag
                return ExecutionMode.JUDGMENT_CONSTRUCTION, notes, HardStopCode.HS01C
            return ExecutionMode.JUDGMENT_CONSTRUCTION, notes, None

        notes.append("Varken dom/beslut eller processmaterial identifierat.")
        return ExecutionMode.UNDETERMINED, notes, HardStopCode.HS01C

    # Termer under denna längd måste stå som eget ord. Se _matchar_term().
    MIN_LÄNGD_FÖR_SAMMANSÄTTNING = 5

    @classmethod
    def _matchar_term(cls, term: str, hay: str) -> bool:
        """
        Matchar en nyckelterm i filnamn/sökväg, anpassat för svenska
        sammansättningar.

        Ren delsträngsökning var fel: "dom" förekommer inuti "sjukdom", så en
        forskarrapport om psykisk sjukdom fick ModeRouter att rapportera att
        akten innehöll en DOM — vilket avgör hela körningsläget.

        Ren ordgräns är också fel: "domslut" och "beslutsunderlag" är
        sammansättningar som verkligen avser avgöranden. Korta termer kräver
        därför ordgräns, längre får matcha i sammansättning.

        Samma regel används för dokumenttypning i fup_analysis_agent.
        """
        if not term:
            return False
        if len(term) >= cls.MIN_LÄNGD_FÖR_SAMMANSÄTTNING:
            return term in hay
        icke_ord = r"[^0-9A-Za-zÅÄÖåäöÉéÜü]"
        mönster = (r"(?:^|" + icke_ord + r")" + re.escape(term)
                   + r"(?:$|" + icke_ord + r")")
        return re.search(mönster, hay) is not None

    def _has_prior_decision(self, records):
        for r in records:
            hay = self._haystack(r)
            if any(self._matchar_term(k, hay) for k in self.DOM_KW):
                return True
        return False

    def _has_process_material(self, records, root_dirs=None):
        for r in records:
            hay = self._haystack(r)
            if any(self._matchar_term(k, hay) for k in self.PROCESS_KW):
                return True
        return False

    @staticmethod
    def _haystack(r):
        return (
            (getattr(r, "relative_path", "") or "") +
            (getattr(r, "file_id", "") or "") +
            (getattr(r, "filename", "") or "")
        ).lower()


class ModeStateValidator:
    """
    Verifierar state-isolation-invarianter (Fas 2).

    ALWAYS_ACTIVE_LAYERS: lager som körs alltid oavsett HS01 (RT-AX):
      L0/L1/L6/L7/L8/L12/L13/L14. Audit A/B/C = L12/L13/L14 (RT-AÅ),
      L7 rättskällekontroll (RT-AÄ), L6 per-rättsfaktum-motor (RT-AÖ).
    """

    ALWAYS_ACTIVE_LAYERS = frozenset({
        "L0", "L1", "L6", "L7", "L8", "L12", "L13", "L14",
    })
    BLOCKED_BY_HS01A = frozenset({"L9", "L10", "L11"})

    @classmethod
    def verify_hs01_splitting(cls, mode, hs_codes):
        """Returnerar lista av HS01-splittringsbrott (FIX-A, RT-AX)."""
        violations = []
        hs = set(hs_codes)
        if HardStopCode.HS01A in hs and mode != ExecutionMode.JUDGMENT_AUDIT:
            violations.append("HS01A tillåts endast i JUDGMENT_AUDIT")
        if HardStopCode.HS01C in hs and mode != ExecutionMode.JUDGMENT_CONSTRUCTION:
            violations.append("HS01C tillåts endast i JUDGMENT_CONSTRUCTION")
        return violations

    @classmethod
    def always_active_layers_missing(cls, mode, hs_codes, executed_layers):
        """Returnerar alltid-aktiva lager som inte exekverats (RT-AX)."""
        return sorted(cls.ALWAYS_ACTIVE_LAYERS - set(executed_layers))

    @classmethod
    def hs01b_applies_to(cls, mode):
        """HS01B gäller BÅDA lägen (RT-AX)."""
        return mode in (ExecutionMode.JUDGMENT_AUDIT,
                        ExecutionMode.JUDGMENT_CONSTRUCTION)

    @classmethod
    def verify_mode_isolated(cls, declared_mode, routed_mode):
        """En körning = exakt ett MODE (RT-H / MODE_SEPARATION)."""
        if declared_mode == ExecutionMode.UNDETERMINED:
            return ["MODE ej fastställt (UNDETERMINED) — ingen körning utan "
                    "fastställt MODE"]
        if declared_mode != routed_mode:
            return [f"MODEBLANDNING: deklarerat {declared_mode.value} ≠ "
                    f"routat {routed_mode.value}"]
        return []


def generera_kompletteringsbegäran(case_state, mode, hs_codes=None):
    """
    Producerar KOMPLETTERINGSBEGÄRAN (RT-BA) med rättslig motivering och
    korrekt markering (RT-BB) vid partiell körning med HS01 aktiv (FIX-G).

    Returnerar en sträng i protokollets obligatoriska format.
    """
    hs_codes = hs_codes if hs_codes is not None else list(case_state.hard_stop_codes)
    mode_name = mode.value if hasattr(mode, "value") else str(mode)
    hs = ", ".join(h.value for h in hs_codes) if hs_codes else "INGEN"

    saknade = []
    blockerade_lager = []
    if HardStopCode.HS01A in hs_codes:
        saknade.append(
            "[CENTRAL] tidigare dom/beslut – krävs som primärkälla i "
            "JUDGMENT_AUDIT – blockerar L9/L10/L11")
        blockerade_lager += ["L9", "L10", "L11"]
    if HardStopCode.HS01C in hs_codes:
        saknade.append(
            "[CENTRAL] komplett processmaterial – krävs för domskonstruktion – "
            "blockerar Domslut-sektionen")
        blockerade_lager.append("DOMSLUT")

    rader = [
        "KOMPLETTERINGSBEGÄRAN – [DATUM]",
        f"Mode: {mode_name}",
        f"Mål: {case_state.case_id}",
        f"HS-orsak: {hs}",
        "Saknade handlingar:",
    ]
    rader += (["  " + s for s in saknade] if saknade
              else ["  [INGA – partiell körning pågår]"])
    rader.append(
        "Rättslig grund för begäran: RB 30:6, RB 35:1–3 "
        "(eller tillämpligt lagrum)")
    rader.append(
        "För att låsa upp: " + ", ".join(blockerade_lager)
        if blockerade_lager
        else "För att låsa upp: fullständig dom / komplett processmaterial")
    rader.append(
        "MARKERING: [KAN EJ VERIFIERAS – PRIMÄRKÄLLA SAKNAS | KÄLL-ID]")
    rader.append(
        "MARKERING: [BASERAT PÅ RÄTTSKÄLLOR – EJ VERIFIERAT MOT "
        "ORIGINALHANDLING]")
    return "\n".join(rader)


class OutputRegler:
    """
    FAS 3 – OUTPUTREGLER (FIX-J till FIX-M).

    Implementerar regressionstesterna RT-BE till RT-BL:

      RT-BE (FIX-J)  Obligatoriskt källformat [KÄLL-ID|FIL|SIDA|DATUM|VERSION]
                     i ALL output. Påstående utan källhänvisning → KÄLLBROTT.
      RT-BF (FIX-K)  P07-brott → HS09. Rättslig slutsats utan verifierad
                     subsumtionskedja → MÖJLIGT_[FELTYP], aldrig direkt slutsats.
      RT-BG (FIX-L)  L2 registrerar ALLA centrala påståenden – totalt antal
                     claim_id anges explicit.
      RT-BH (FIX-L)  L12/L13/L14 producerar explicit listformat – aldrig tyst
                     godkännande.
      RT-BI (FIX-L)  L8 analyserar varje rekvisit – inget utelämnas.
      RT-BJ (FIX-M)  Löptext förbjuden som primär outputform – lagerstruktur
                     obligatorisk.
      RT-BK (FIX-L)  En lucka markeras explicit och ingår i fullständig output –
                     aldrig ursäkt för reducerad output.
      RT-BL (FIX-I+M) Inget ytterligare efter Audit Controller utan ny
                     explicit begäran.
    """

    KÄLLFORMAT = "[KÄLL-ID | FIL | SIDA | DATUM | VERSION]"

    FELTYPER = {
        "MÖJLIGT_PROCESSFEL": "Processuell avvikelse identifierad",
        "MÖJLIGT_RÄTTSFEL": "Rättsregel felaktig eller felaktigt tillämpad",
        "MÖJLIGT_FAKTAFEL": "Faktapåstående avviker från primärkälla",
        "MÖJLIGT_BEVISVÄRDERINGSFEL": "Bevisvärdering avviker från faktisk "
                                      "bevisning",
        "MÖJLIGT_UTELÄMNANDE": "Central bevisning eller argument ej behandlat",
    }

    FÖRBJUDNA_FORMULERINGAR = (
        "kan utgöra stöd för argument om",
        "talar för att",
        "indikerar att domstolen",
        "sannolikt innebär",
        "troligen utgör",
        "bör tolkas som",
    )

    # ── FIX-J (RT-BE) ─────────────────────────────────────────
    @staticmethod
    def källformat(source_id, fil, sida, datum, version) -> str:
        """Renderar obligatoriskt källformat [KÄLL-ID|FIL|SIDA|DATUM|VERSION]."""
        return (f"[{source_id} | {fil} | {sida} | {datum} | {version}]")

    @classmethod
    def källformat_från_claim(cls, claim) -> str:
        """Källformat från en ClaimId-liknande post (7-fält, FIX-B)."""
        return cls.källformat(
            getattr(claim, "source_id", "SAKNAS"),
            getattr(claim, "file_name", "SAKNAS"),
            getattr(claim, "page", "SAKNAS"),
            getattr(claim, "date", "SAKNAS"),
            getattr(claim, "version", "SAKNAS"),
        )

    @staticmethod
    def saknar_källhänvisning(claim) -> bool:
        """RT-BE: ett påstående saknar källhänvisning om source_id är tom."""
        sid = getattr(claim, "source_id", "") or ""
        return sid == "" or sid == "SAKNAS"

    # ── FIX-K (RT-BF) ─────────────────────────────────────────
    @classmethod
    def p07_ersättning(cls, feltyp, claim=None) -> str:
        """Obligatorisk ersättningstext vid möjlig avvikelse (FIX-K).

        Systemet skriver ALDRIG direkt att något 'kan utgöra stöd för' eller
        'talar för' en rättslig slutsats utan fullständigt verifierad kedja.
        """
        cit = (cls.källformat_från_claim(claim)
               if claim is not None else cls.KÄLLFORMAT)
        return (f"{feltyp} identifierat – juridisk bedömning överlämnas till "
                f"behörig jurist. Källa: {cit}")

    @staticmethod
    def redigera_hs_koder(data) -> str:
        """
        Tar bort HARD STOP-koder ur text som härrör från DATA.

        AuditController sätter hard stops genom att regex-söka HS-koder i
        violation-strängarna. Interpoleras data in i en sådan sträng kan
        innehållet därmed SÄTTA en hard stop som inget villkor motsvarar.

        Bevisat: ett rekvisit vars text innehöll "[HS20]" gav
        hard_stop_codes ['HS09', 'HS20'] — HS20 enbart av textinnehåll.
        Rekvisittext kan komma från extern rättskällesökning, så texten är
        inte under systemets kontroll.

        Koder i data ersätts med [HS-KOD REDIGERAD]. Endast koder som
        producenten själv skriver i strängen får utlösa en hard stop.
        """
        return re.sub(r"\[?\bHS\d{2}[A-C]?\b\]?", "[HS-KOD REDIGERAD]", str(data))

    @classmethod
    def innehåller_förbjuden_formulering(cls, text) -> bool:
        """RT-BF: förbjudna formuleringar (otillåten inferens)."""
        t = str(text).lower()
        return any(f in t for f in cls.FÖRBJUDNA_FORMULERINGAR)

    @classmethod
    def verifiera_p07(cls, case_state) -> List[str]:
        """P07-brott → HS09 (RT-BF). MUST-rekvisit utan bevisning → MÖJLIGT_."""
        violations = []
        for req in case_state.requisite_matrix:
            if (req.modal == ModalMarker.MUST and
                    req.status == RequisiteStatus.BEVISNING_SAKNAS):
                violations.append(
                    f"P07-BROTT [HS09]: rättslig slutsats utan verifierad "
                    f"subsumtionskedja för rekvisit "
                    f"'{cls.redigera_hs_koder(req.requisite_text[:60])}'. "
                    f"Obligatorisk ersättning: "
                    f"{cls.p07_ersättning('MÖJLIGT_RÄTTSFEL')}"
                )
        return violations

    # ── FIX-L (RT-BG, RT-BH, RT-BI, RT-BK) ────────────────────
    @staticmethod
    def claim_id_totalt(case_state) -> str:
        """RT-BG: totalt antal claim_id anges explicit, aldrig tyst urval."""
        return f"[C-XXX | TOTALT: {len(case_state.claims)} claim_id]"

    @staticmethod
    def fullständighetsmarkering(lager, antal, tom_markering) -> str:
        """RT-BH: explicit listformat – aldrig tyst godkännande."""
        if antal == 0:
            return f"[{lager}] {tom_markering}"
        return f"[{lager}] TOTALT: {antal}"

    @staticmethod
    def rekvisit_totalt(case_state) -> str:
        """RT-BI: varje rekvisit analyserat – inget utelämnas."""
        return (f"[L8 | REKVISIT: {len(case_state.requisite_matrix)} analyserade "
                f"| INGET UTLÄMNAT]")

    @staticmethod
    def luckmarkering(beskrivning, claim=None) -> str:
        """RT-BK: lucka markeras explicit och ingår i fullständig output."""
        cit = (f"[{getattr(claim, 'source_id', 'SAKNAS')} | "
               f"{getattr(claim, 'page', 's.X')} | "
               f"{getattr(claim, 'date', 'ÅÅÅÅ-MM-DD')}]"
               if claim is not None else "[DOK-XXX | s.X | ÅÅÅÅ-MM-DD]")
        return (f"[LUCKA: {beskrivning} – KAN EJ VERIFIERAS | {cit}]")

    @classmethod
    def fullständighets_violations(cls, case_state) -> List[str]:
        """
        RT-BI: inget rekvisit utelämnas eller lämnas oanalyserat (FIX-L).

        Tom matris gav tidigare HS09 — förbjuden inferens. Det var fel kod för
        fel sak. En tom matris betyder att det inte FINNS något underlag att
        subsumera mot, inte att motorn dragit en otillåten slutsats. Följden
        var att varje ärende utan fastställd måltyp redovisade en
        inferensöverträdelse som aldrig inträffat, och att samma sakförhållande
        räknades som två skilda hard stops (HS09 + HS11). En kod som utlöses i
        varje körning särskiljer ingenting.

        Avsaknad av matris är HS11 — subsumtionskedja saknar rättsfaktum.
        """
        if not case_state.requisite_matrix:
            return [
                "FULLSTÄNDIGHETSBROTT [HS11]: L8 rekvisitmatris tom – "
                "inget rekvisit analyserat (FIX-L)"
            ]

        # Matrisen finns men enskilda rekvisit kan ändå vara oanalyserade.
        # Den kontrollen utlovades av regeltexten men fanns inte i koden, så
        # en matris med oanalyserade poster passerade som fullständig.
        oanalyserade = [
            r for r in case_state.requisite_matrix
            if getattr(r, "status", None) is None
        ]
        if oanalyserade:
            return [
                f"FULLSTÄNDIGHETSBROTT [HS11]: {len(oanalyserade)} av "
                f"{len(case_state.requisite_matrix)} rekvisit saknar "
                f"analysstatus (FIX-L)"
            ]
        return []

    # ── FIX-M (RT-BJ) + FIX-I (RT-BL) ─────────────────────────
    @staticmethod
    def löptext_förbud_violations(output_text) -> List[str]:
        """RT-BJ: löptext förbjuden som primär outputform (FIX-M).

        Körningsresultat ska struktureras enligt lagerformat
        ('## LAGER X – [LAGERNAMN]'), aldrig som sammanhängande prosa.
        """
        if re.search(r"^##\s+LAGER", str(output_text), re.MULTILINE):
            return []
        return [
            "[STRUKTURBROTT – EJ GILTIG KÖRNINGSOUTPUT] "
            "(FIX-M: löptext förbjuden som primär outputform – "
            "lagerstruktur obligatorisk)"
        ]

    @staticmethod
    def körningsavslut(controller_verdict) -> str:
        """RT-BL: inget ytterligare efter Audit Controller utan ny begäran."""
        if controller_verdict in (
            AuditControllerVerdict.GODKÄND,
            AuditControllerVerdict.FLAGGAD,
            AuditControllerVerdict.UNDERKÄND,
            AuditControllerVerdict.STOPPAD,
        ):
            return ("[KÖRNINGSAVSLUT | INGEN YTTERLIGARE OUTPUT UTAN NY "
                    "EXPLICIT BEGÄRAN]")
        return "[KÖRNINGSAVSLUT | EJ FASTSTÄLLD]"

    @classmethod
    def verifiera_output(cls, case_state) -> List[str]:
        """Samlad outputregel-validering (FIX-J, FIX-K, FIX-L)."""
        violations = []
        # FIX-J (RT-BE)
        for claim in case_state.claims:
            if cls.saknar_källhänvisning(claim):
                violations.append(
                    f"KÄLLBROTT [HS09]: claim {getattr(claim, 'claim_id', '?')} "
                    f"saknar källhänvisning [EJ KÄLLHÄNVISAT – OGILTIGT] (FIX-J)"
                )
        # FIX-K (RT-BF)
        violations.extend(cls.verifiera_p07(case_state))
        # FIX-L (RT-BI)
        violations.extend(cls.fullständighets_violations(case_state))
        return violations


class ProcessPositionRegler:
    """
    FAS 4 – PROCESS POSITION MODEL (RT-L CLAIM/POSITION TEST).

    Verifierar L4-positioner (producerade av process_position_agent) mot
    PROCESS POSITION CONTROL i SKILL_final.md:

      tillåtna_klasser:
        EXPLICIT_YRKANDE, EXPLICIT_GRUND, EXPLICIT_INVÄNDNING,
        EXPLICIT_MEDGIVANDE, EXPLICIT_BESTRIDANDE, SAKOMSTÄNDIGHET,
        BEVISFAKTUM, RÄTTSFAKTUM, BEVISNING

      absolut_förbud:
        - Motorn får ALDRIG konstruera ett yrkande, en grund eller en
          invändning genom inferens.
        - Om något endast kan antas → NOT_VERIFIABLE
        - Överträdelse utlöser HS09

    Positionerna läses från case_state.metadata (skrivs av
    ProcessPositionAgent.analyze under L4 i run_pipeline).
    """

    TILLÅTNA_KLASSER = [
        "EXPLICIT_YRKANDE",
        "EXPLICIT_GRUND",
        "EXPLICIT_INVÄNDNING",
        "EXPLICIT_MEDGIVANDE",
        "EXPLICIT_BESTRIDANDE",
        "SAKOMSTÄNDIGHET",
        "BEVISFAKTUM",
        "RÄTTSFAKTUM",
        "BEVISNING",
    ]

    # Nycklar i case_state.metadata där position-dicts kan finnas.
    POSITIONS_KEYS = ("l4_process_positions", "l4_positions")

    @classmethod
    def _positioner(cls, case_state) -> List[Dict[str, Any]]:
        """Samlar position-dicts från case_state.metadata."""
        positions: List[Dict[str, Any]] = []
        meta = getattr(case_state, "metadata", {}) or {}
        for key in cls.POSITIONS_KEYS:
            raw = meta.get(key)
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict):
                        positions.append(item)
        return positions

    @classmethod
    def inferens_violations(cls, case_state) -> List[str]:
        """RT-L: förbjuden inferens / icke-verifierbar position → HS09."""
        violations = []
        for pos in cls._positioner(case_state):
            confidence = str(pos.get("confidence", "")).upper()
            inferred = bool(pos.get("inferred", False))
            if confidence == "NOT_VERIFIABLE" or inferred:
                # pid/pc härrör ur positionsdata som bygger på aktens text.
                # Redigeras så att innehåll inte kan sätta en hard stop.
                pid = OutputRegler.redigera_hs_koder(pos.get("position_id", "?"))
                pc = OutputRegler.redigera_hs_koder(pos.get("position_class", "?"))
                violations.append(
                    f"PROCESS_POSITION_BROTT [HS09]: position {pid} "
                    f"({pc}) kan inte verifieras ordagrant – inferens "
                    f"förbjuden [NOT_VERIFIABLE → HS09] (RT-L)"
                )
        return violations

    @classmethod
    def klass_violations(cls, case_state) -> List[str]:
        """Otillåten/okänd position-klass → HS09 (RT-L)."""
        violations = []
        for pos in cls._positioner(case_state):
            pc = pos.get("position_class", "")
            if pc and pc not in cls.TILLÅTNA_KLASSER:
                pid = OutputRegler.redigera_hs_koder(pos.get("position_id", "?"))
                pc = OutputRegler.redigera_hs_koder(pc)
                violations.append(
                    f"PROCESS_POSITION_BROTT [HS09]: position {pid} har "
                    f"otillåten klass '{pc}' – tillåtna: "
                    f"{', '.join(cls.TILLÅTNA_KLASSER)} (RT-L)"
                )
        return violations

    @classmethod
    def verifiera_l4(cls, case_state) -> List[str]:
        """Samlad PROCESS POSITION MODEL-validering (RT-L)."""
        violations = []
        violations.extend(cls.inferens_violations(case_state))
        violations.extend(cls.klass_violations(case_state))
        return violations


class Availability(Enum):
    VERIFIED = "VERIFIED"
    PARTIALLY_AVAILABLE = "PARTIALLY_AVAILABLE"
    NOT_FOUND = "NOT_FOUND"
    CONFIRMED_ABSENT = "CONFIRMED_ABSENT"
    BEVISUNDERLAG_EJ_TILLGÄNGLIGT = "BEVISUNDERLAG_EJ_TILLGÄNGLIGT"


class EdgeType(Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    DERIVES_FROM = "DERIVES_FROM"
    REQUIRES = "REQUIRES"
    DEPENDS_ON = "DEPENDS_ON"
    REFERS_TO = "REFERS_TO"
    QUALIFIES = "QUALIFIES"
    INVALIDATES = "INVALIDATES"
    OMITS = "OMITS"
    UNRESOLVED = "UNRESOLVED"


class RequisiteStatus(Enum):
    """Analystillstånd — separat från outputregler (HARD_STOP-text / claim_zero_fel).

    Fem bedömningstillstånd (primära):
      BEVISNING_SAKNAS, OTILLRACKLIGT_STYRKT, BEVISNING_TALAR_EMOT,
      SAKFORHALLANDET_STYRKT, FRAGAN_OKLAR

    Legacy-mappning (behålls för bakåtkompatibilitet):
      REKVISIT_UPPFYLLT → SAKFORHALLANDET_STYRKT
      OBESTRITT         → SAKFORHALLANDET_STYRKT (processuellt obestritt)
      TVISTIGT          → FRAGAN_OKLAR
      BEVISNING_SAKNAS  → BEVISNING_SAKNAS
    """
    # --- fem analystillstånd ---
    BEVISNING_SAKNAS = "BEVISNING_SAKNAS"
    OTILLRACKLIGT_STYRKT = "OTILLRACKLIGT_STYRKT"
    BEVISNING_TALAR_EMOT = "BEVISNING_TALAR_EMOT"
    SAKFORHALLANDET_STYRKT = "SAKFORHALLANDET_STYRKT"
    FRAGAN_OKLAR = "FRAGAN_OKLAR"
    # --- legacy alias (samma värdesträng där det överlappar) ---
    REKVISIT_UPPFYLLT = "REKVISIT_UPPFYLLT"
    OBESTRITT = "OBESTRITT"
    TVISTIGT = "TVISTIGT"


def map_requisite_status_to_five(status: "RequisiteStatus") -> str:
    """Mappa legacy/enum till ett av de fem analystillstånden (strängkod)."""
    v = getattr(status, "value", str(status))
    m = {
        "REKVISIT_UPPFYLLT": "SAKFORHALLANDET_STYRKT",
        "OBESTRITT": "SAKFORHALLANDET_STYRKT",
        "TVISTIGT": "FRAGAN_OKLAR",
        "BEVISNING_SAKNAS": "BEVISNING_SAKNAS",
        "OTILLRACKLIGT_STYRKT": "OTILLRACKLIGT_STYRKT",
        "BEVISNING_TALAR_EMOT": "BEVISNING_TALAR_EMOT",
        "SAKFORHALLANDET_STYRKT": "SAKFORHALLANDET_STYRKT",
        "FRAGAN_OKLAR": "FRAGAN_OKLAR",
    }
    return m.get(v, "FRAGAN_OKLAR")


class ModalMarker(Enum):
    MUST = "MUST"
    ALT = "ALT"
    EXC = "EXC"
    IF = "IF"
    WHEN = "WHEN"


# ============================================================
# DATAKLASSER
# ============================================================

@dataclass
class FileRecord:
    """Representerar en fil i vault-ingestion (FAS 1)."""
    file_id: str
    file_path: str
    relative_path: str
    hash_sha256: str = "KAN EJ VERIFIERAS"
    hash_md5: str = "KAN EJ VERIFIERAS"
    filtyp_magic: str = "OKÄND"
    file_size_bytes: int = 0
    baseline_state: BaselineState = BaselineState.UNVERIFIED
    procedural_status: str = "UNKNOWN"
    quarantine_flag: bool = False
    evidence_category: EvidenceCategory = EvidenceCategory.UNCLASSIFIED
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_id": self.file_id,
            "file_path": self.file_path,
            "hash_sha256": self.hash_sha256,
            "hash_md5": self.hash_md5,
            "filtyp_magic": self.filtyp_magic,
            "file_size_bytes": self.file_size_bytes,
            "baseline_state": self.baseline_state.value,
            "procedural_status": self.procedural_status,
            "quarantine_flag": self.quarantine_flag,
            "evidence_category": self.evidence_category.value,
        }


CLAIM_MAXLÄNGD = 500  # tecken i ClaimId.content (B-011: kapning flaggas)


@dataclass
class ClaimId:
    """Obligatoriskt 7-fältsformat för claim_id (FIX-B)."""
    claim_id: str          # [C-XXX]
    content: str           # Exakt text från källan
    source_id: str         # KÄLL-ID: [DOK-XXX]
    file_name: str         # FIL: [filnamn]
    page: str              # SIDA: [s.X eller SAKNAS]
    date: str              # DATUM: [ÅÅÅÅ-MM-DD eller SAKNAS]
    version: str           # VERSION: [v1.0 eller SAKNAS]
    claim_type: str        # Påståendetyp
    availability: Availability = Availability.VERIFIED
    avsnitt: str = "SAKNAS"   # AVSNITT: rubrik/stycke, SAKNAS om ej fastställt
    tidskod: str = "SAKNAS"   # TIDSKOD: hh:mm:ss för ljud/video, annars SAKNAS
    # Steg 13: content är kapat till CLAIM_MAXLÄNGD tecken - flaggas, aldrig tyst.
    text_trunkerad: bool = False
    # Proveniens för date/version. FIL_MTIME och STANDARDVÄRDE räknas INTE som
    # verifierad datum-/versionsmetadata (ingen dummy, ingen mtime).
    datum_källa: str = "SAKNAS"
    version_källa: str = "SAKNAS"

    def metadata_verifierad(self) -> bool:
        """True endast om både datum och version kommer ur dokumentet självt."""
        ogiltig = {"SAKNAS", "FIL_MTIME", "STANDARDVÄRDE", ""}
        return (self.date not in ("SAKNAS", "") and self.version not in ("SAKNAS", "")
                and self.datum_källa not in ogiltig and self.version_källa not in ogiltig)

    def sju_fält(self) -> str:
        """[KÄLL-ID|FIL|SIDA|AVSNITT|TIDSKOD|DATUM|VERSION]"""
        return (f"[{self.source_id}|{self.file_name}|{self.page}|{self.avsnitt}|"
                f"{self.tidskod}|{self.date}|{self.version}]")

    def validate(self) -> List[str]:
        """Kontrollerar att alla 7 fält är angivna (FIX-B)."""
        errors = []
        for field_name, value in [
            ("content", self.content),
            ("source_id", self.source_id),
            ("file_name", self.file_name),
            ("page", self.page),
            ("date", self.date),
            ("version", self.version),
            ("avsnitt", self.avsnitt),
            ("tidskod", self.tidskod),
            ("claim_type", self.claim_type),
        ]:
            if not value or value.strip() == "":
                errors.append(f"Fält '{field_name}' saknas – skriv SAKNAS")
        # FIX-C: EVIDENCED_FACT förbjudet på PARTIALLY_AVAILABLE
        if (self.claim_type == "EVIDENCED_FACT" and
                self.availability == Availability.PARTIALLY_AVAILABLE):
            errors.append(
                "FIX-C-BROTT: EVIDENCED_FACT förbjudet på PARTIALLY_AVAILABLE källa. "
                "Nedgradera till CLAIM. [HS09]"
            )
        return errors

    def to_formatted_string(self) -> str:
        return (
            f"[{self.claim_id}] | \"{self.content}\"\n"
            f"         | KÄLL-ID: {self.source_id}\n"
            f"         | FIL: {self.file_name}\n"
            f"         | SIDA: {self.page}\n"
            f"         | AVSNITT: {self.avsnitt}\n"
            f"         | TIDSKOD: {self.tidskod}\n"
            f"         | DATUM: {self.date}\n"
            f"         | VERSION: {self.version}\n"
            f"         | Påståendetyp: {self.claim_type}\n"
            f"         | Tillgänglighet: {self.availability.value}"
        )


@dataclass
class VerbatimAnchor:
    """Obligatorisk koppling per grafkant (FAS 3)."""
    source_id: str
    source_path: str
    source_hash: str
    page_or_time: str
    verbatim_quote: str
    verified: bool = False

    def is_valid(self) -> bool:
        """Kontrollerar att ankaret är giltigt."""
        if not self.verbatim_quote or self.verbatim_quote == "[SAKNAR CITAT]":
            return False
        if not self.verified:
            return False
        return True


@dataclass
class GraphEdge:
    """En kant i relationsgrafen (FAS 3)."""
    edge_id: str
    source_node: str
    target_node: str
    edge_type: EdgeType
    anchor: Optional[VerbatimAnchor] = None

    def __post_init__(self):
        """Tvinga UNRESOLVED om ankaret är ogiltigt (zero inference policy)."""
        if self.anchor is None or not self.anchor.is_valid():
            self.edge_type = EdgeType.UNRESOLVED


@dataclass
class LegalSourceRecord:
    """Fullständigt format per prejudikat (FIX-P)."""
    source_id: str
    source_type: str
    authority_level: str
    court: str
    case_number: str
    reference: str
    date: str
    legal_issue: str
    holding: str
    cited_law: str
    official_source: str = "NOT_VERIFIED"
    current_status: str = "NOT AUTOMATICALLY ASSUMED"
    later_case_check: str = "REQUIRED"
    applicability_to_current_case: str = "NOT YET ASSESSED"
    # FAS 1 – Rättskälleintegritet
    holding_verification: str = "HOLDING_EJ_VERIFIERBAR"  # RT-BP (H1/H2/H3)
    blocked_from_requisites: bool = False                 # RT-BO (EJ_RÄTTSKÄLLA)
    blocking_reason: str = ""                             # HS07/HS10-detalj
    search_domain: str = "LEGAL_SEARCH"                   # RT-BS (FIX-R)
    search_id: str = ""                                   # RT-BQ (SEARCH_10)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "authority_level": self.authority_level,
            "court": self.court,
            "case_number": self.case_number,
            "reference": self.reference,
            "date": self.date,
            "legal_issue": self.legal_issue,
            "holding": self.holding,
            "holding_verification": self.holding_verification,
            "cited_law": self.cited_law,
            "official_source": self.official_source,
            "current_status": self.current_status,
            "later_case_check": self.later_case_check,
            "applicability_to_current_case": self.applicability_to_current_case,
            "blocked_from_requisites": self.blocked_from_requisites,
            "blocking_reason": self.blocking_reason,
            "search_domain": self.search_domain,
            "search_id": self.search_id,
        }


@dataclass
class RequisiteEntry:
    """En rad i rekvisitmatrisen (L8)."""
    requisite_text: str
    modal: ModalMarker
    claim_id: str  # claim_id eller NOT_VERIFIABLE
    source_ref: str  # [KÄLL-ID|SIDA]
    status: RequisiteStatus = RequisiteStatus.BEVISNING_SAKNAS
    # Steg 17: claims som matchade men uteslöts p.g.a. trunkerad text utan
    # verifierad datum-/versionsmetadata (B-011) - redovisas i luckan.
    uteslutna_trunkerade: List[str] = field(default_factory=list)


@dataclass
class AuditFinding:
    """Ett fynd från audit-agent A, B eller C."""
    finding_id: str
    agent: str  # A, B, C
    description: str
    source_ref: str
    severity: str = "MEDEL"  # LÅG | MEDEL | HÖG | KRITISK


@dataclass
class SelfHealingPatch:
    """En patch från SelfHealingEngine."""
    patch_id: str
    trigger: str
    gap: str
    rule: str
    severity: str
    applied: bool = False


@dataclass
class ReproducibilityRecord:
    """Reproducerbarhetsdata (FAS 8)."""
    record_id: str
    engine_version: str = "10.3-UPDATED"
    scan_timestamp: str = ""
    root_hash: str = ""
    activated_modules: List[str] = field(default_factory=list)
    state_transitions: List[Dict[str, str]] = field(default_factory=list)
    file_hashes: Dict[str, str] = field(default_factory=dict)
    patches: List[SelfHealingPatch] = field(default_factory=list)
    final_state: str = "INIT"

    def __post_init__(self):
        if not self.scan_timestamp:
            self.scan_timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "engine_version": self.engine_version,
            "scan_timestamp": self.scan_timestamp,
            "root_hash": self.root_hash,
            "activated_modules": self.activated_modules,
            "state_transitions": self.state_transitions,
            "file_hashes": self.file_hashes,
            "patches": [
                {"patch_id": p.patch_id, "trigger": p.trigger,
                 "severity": p.severity, "applied": p.applied}
                for p in self.patches
            ],
            "final_state": self.final_state,
        }


@dataclass
class CaseState:
    """Fullständigt case state – maskinläsbart output."""
    case_id: str
    engine_version: str = "10.3-UPDATED"
    process_mode: ProcessMode = ProcessMode.UNDEFINED
    execution_mode: ExecutionMode = ExecutionMode.UNDETERMINED
    mode_routing_notes: List[str] = field(default_factory=list)
    court_type: CourtType = CourtType.UNKNOWN
    pipeline_state: PipelineState = PipelineState.INIT
    hard_stop_active: bool = False
    hard_stop_codes: List[HardStopCode] = field(default_factory=list)
    # Tillståndsseparation: kedjeavbrott (körningen avbröts före sista lagret
    # p.g.a. domänspärr). pipeline_state är då HARD_STOP (användarbeslut steg 8).
    hard_stop_chain_abort: bool = False
    files: List[FileRecord] = field(default_factory=list)
    claims: List[ClaimId] = field(default_factory=list)
    graph_edges: List[GraphEdge] = field(default_factory=list)
    requisite_matrix: List[RequisiteEntry] = field(default_factory=list)
    legal_sources: List[LegalSourceRecord] = field(default_factory=list)
    audit_a_findings: List[AuditFinding] = field(default_factory=list)
    audit_b_findings: List[AuditFinding] = field(default_factory=list)
    audit_c_findings: List[AuditFinding] = field(default_factory=list)
    counter_audit_results: Dict[str, str] = field(default_factory=dict)
    sårbarhet_risk: str = "EJ ANALYSERAD"
    falsification_verdict: FalsificationVerdict = FalsificationVerdict.NOT_RUN
    overall_status: AuditStatus = AuditStatus.H
    audit_controller_verdict: AuditControllerVerdict = AuditControllerVerdict.UNDERKÄND
    activated_modules: List[str] = field(default_factory=list)
    reproducibility: Optional[ReproducibilityRecord] = None
    patches: List[SelfHealingPatch] = field(default_factory=list)
    presentation: Optional[PresentationViews] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def hard_stop_triggered(self) -> bool:
        """Härleds ur koderna - aldrig false när hard_stop_codes har innehåll."""
        return bool(self.hard_stop_active or self.hard_stop_codes)

    @property
    def rekvisitmatris_status(self) -> str:
        """Steg 14: matrisens giltighet följer pipeline_state.
        FAILED (tekniskt fel) -> OGILTIG; domänspärr -> BEVARAD (matrisen
        bevaras intakt, slutsatsen spärras); COMPLETE -> GILTIG."""
        if self.pipeline_state == PipelineState.FAILED:
            return "OGILTIG"
        if self.pipeline_state == PipelineState.HARD_STOP or self.hard_stop_triggered:
            return "BEVARAD"
        if self.pipeline_state == PipelineState.COMPLETE:
            return "GILTIG"
        return "EJ_FASTSTÄLLD"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "engine_version": self.engine_version,
            "process_mode": self.process_mode.value,
            "court_type": self.court_type.value,
            "pipeline_state": self.pipeline_state.value,
            "hard_stop_active": self.hard_stop_active,
            "hard_stop_triggered": self.hard_stop_triggered,
            "hard_stop_chain_abort": self.hard_stop_chain_abort,
            "hard_stop_codes": [hs.value for hs in self.hard_stop_codes],
            "rekvisitmatris_status": self.rekvisitmatris_status,
            "requisite_gate_status": (
                "PASSERAD" if self.metadata.get("requisite_gate_passed") is True
                else "SPÄRRAD" if self.metadata.get("requisite_gate_passed") is False
                else "EJ FASTSTÄLLD"
            ),
            "l9_status": self.metadata.get("l9_status", "EJ FASTSTÄLLD"),
            "kritiska_pipelinefel": list(self.metadata.get("kritiska_pipelinefel") or []),
            "tekniskt_fel": self.metadata.get("tekniskt_fel"),
            # Rekvisitmatrisen bevaras intakt även under spärr.
            "requisite_matrix": [_jsonbar(r) for r in self.requisite_matrix],
            "files_count": len(self.files),
            "claims_count": len(self.claims),
            "graph_edges_count": len(self.graph_edges),
            "audit_a_findings_count": len(self.audit_a_findings),
            "audit_b_findings_count": len(self.audit_b_findings),
            "audit_c_findings_count": len(self.audit_c_findings),
            "falsification_verdict": self.falsification_verdict.value,
            "overall_status": self.overall_status.value,
            "audit_controller_verdict": self.audit_controller_verdict.value,
            "activated_modules": self.activated_modules,
            "counter_audit_results": self.counter_audit_results,
            "sårbarhet_risk": self.sårbarhet_risk,
        }


# ============================================================
# HJÄLPFUNKTIONER
# ============================================================

def compute_sha256(file_path: str) -> str:
    """Beräknar SHA-256 för en fil (chain of custody)."""
    try:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except (IOError, OSError):
        return "KAN EJ VERIFIERAS"


def compute_md5(file_path: str) -> str:
    """Beräknar MD5 för en fil (bakåtkompatibilitet)."""
    try:
        h = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except (IOError, OSError):
        return "KAN EJ VERIFIERAS"


def detect_filetype_magic(file_path: str) -> str:
    """
    Identifierar filtyp via magic bytes – ALDRIG via filnamnstillägg.
    Implementerar K2 från METADATA_FORENSIK_PROTOKOLL.
    """
    magic_signatures = {
        b"%PDF": "PDF",
        b"PK\x03\x04": "ZIP/DOCX/XLSX",
        b"\xff\xd8\xff": "JPEG",
        b"\x89PNG": "PNG",
        b"RIFF": "WAV/AVI",
        b"ID3": "MP3",
        b"fLaC": "FLAC",
        b"\x1a\x45\xdf\xa3": "MKV/WEBM",
        b"OggS": "OGG",
        b"\x00\x00\x00\x18ftypmp4": "MP4",
        b"{\n": "JSON",
        b"<?xml": "XML",
        b"---\n": "YAML/MARKDOWN",
    }
    try:
        with open(file_path, "rb") as f:
            header = f.read(16)
        for magic, filetype in magic_signatures.items():
            if header.startswith(magic):
                return filetype
        # Kontrollera om det är text
        try:
            with open(file_path, "r", encoding="utf-8", errors="strict") as f:
                f.read(512)
            return "TEXT/MARKDOWN/CODE"
        except UnicodeDecodeError:
            return "BINÄR/OKÄND"
    except (IOError, OSError):
        return "KAN EJ VERIFIERAS"


def _jsonbar(obj: Any) -> Any:
    """Dataklass/enum -> JSON-bart värde (rekvisitmatris i case_state_v10.json)."""
    import dataclasses as _dc
    if isinstance(obj, Enum):
        return obj.value
    if _dc.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _jsonbar(getattr(obj, f.name)) for f in _dc.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): _jsonbar(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonbar(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def generate_file_id(file_path: str) -> str:
    """Genererar ett unikt fil-ID baserat på sökväg."""
    safe_path = re.sub(r"[^a-zA-Z0-9_]", "_", file_path)[:40]
    short_hash = hashlib.sha256(file_path.encode()).hexdigest()[:8].upper()
    return f"FILE_{safe_path}_{short_hash}"


def generate_case_id() -> str:
    """
    Genererar ett unikt ID för körningen.

    Tidsstämpeln hade sekundupplösning, så två körningar som startade inom
    samma sekund fick SAMMA id. Det id:t används som record_id i
    ReproducibilityRecord — alltså blev två skilda analyser omöjliga att skilja
    åt genom just den post som finns för att göra en körning identifierbar.

    Suffixet gör id:t unikt utan att ta bort tidsordningen.
    """
    import secrets
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"CASE_{ts}_{secrets.token_hex(3).upper()}"


# ============================================================
# INGESTION AGENT (FAS 1)
# ============================================================

class IngestionAgent:
    """
    FAS 1: RECURSIVE_VAULT_INGESTION
    Tillstånd: INIT → INGESTING
    
    Regler:
    - Skanna rotmapp(ar) rekursivt
    - Beräkna SHA-256 + MD5 per fil
    - Klassificera LOCKED_BASELINE / UNSOLICITED_INPUT
    - Original-filer rörs ALDRIG
    - HARD STOP om >60% filer saknar SHA-256
    """

    AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}
    VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
    DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".rtf", ".odt"}

    def __init__(self, case_state: CaseState):
        self.case_state = case_state
        self.log: List[str] = []

    def ingest(self, root_paths: List[str]) -> bool:
        """
        Kör ingestion på en eller flera rotmappar.
        Returnerar True om ingestion lyckades, False vid HARD STOP.
        """
        self.log.append(f"[L0] Ingestion startar – {len(root_paths)} rotmapp(ar)")
        all_files: List[FileRecord] = []

        for root_path in root_paths:
            if not os.path.exists(root_path):
                self.log.append(f"[L0] VARNING: Sökväg finns inte: {root_path}")
                continue
            if os.path.isfile(root_path):
                record = self._process_file(root_path, root_path)
                all_files.append(record)
            else:
                for dirpath, _, filenames in os.walk(root_path):
                    for filename in filenames:
                        full_path = os.path.join(dirpath, filename)
                        rel_path = os.path.relpath(full_path, root_path)
                        record = self._process_file(full_path, rel_path)
                        all_files.append(record)

        # A2: file_id byggs av relativ sökväg; två rötter med samma relativa
        # namn (t.ex. yttrande.txt) gav samma id och den ena handlingen
        # skuggade den andra i registret. Kolliderande id görs unika via full
        # sökväg (deterministiskt för samma akt).
        _sedda: Dict[str, int] = {}
        for rec in all_files:
            _sedda[rec.file_id] = _sedda.get(rec.file_id, 0) + 1
        for rec in all_files:
            if _sedda[rec.file_id] > 1:
                rec.file_id = generate_file_id(os.path.abspath(rec.file_path))

        if not all_files:
            # En akt utan filer är inte en partiell körning — det finns inget
            # material alls. Tidigare returnerades True här, varpå pipelinen
            # kördes igenom på noll handlingar och avslutades med en positiv
            # slutstatus. En tom mapp fick alltså ett omdöme som såg ut som ett
            # analysresultat.
            #
            # HS01C var dessutom onåbar i drift: enda producenten var
            # ModeRouter.route(), som endast körs när anroparen lämnar
            # process_mode UNDEFINED. CLI och consolidated_engine anger alltid
            # ett läge, så koden kunde aldrig sättas trots att registret
            # beskriver den som helstopp. Villkoret hör hemma här, där det är
            # oberoende av vem som valt körningsläge.
            self.log.append(
                "[L0] HARD STOP HS01C: akten innehåller inga filer. "
                "Det finns inget underlag att analysera."
            )
            self.case_state.hard_stop_active = True
            if HardStopCode.HS01C not in self.case_state.hard_stop_codes:
                self.case_state.hard_stop_codes.append(HardStopCode.HS01C)
            # Anpassningsbart läge: flagga saknat underlag (HS01C) utan att krascha/avbryta kedjan.
            self.case_state.hard_stop_chain_abort = False
            self.case_state.pipeline_state = PipelineState.COMPLETE
            self.case_state.metadata["akten_tom"] = True
            self.case_state.overall_status = AuditStatus.I

        # L00 integritetskontroll: >60% saknar SHA-256 → HARD STOP
        unverified = sum(
            1 for f in all_files
            if f.hash_sha256 == "KAN EJ VERIFIERAS"
        )
        pct_unverified = (unverified / len(all_files) * 100) if all_files else 0.0
        if pct_unverified > 60:
            self.log.append(
                f"[L0] HARD STOP: {pct_unverified:.1f}% av filer saknar SHA-256 "
                f"(gräns: 60%). Analys avbruten."
            )
            self.case_state.hard_stop_active = True
            self.case_state.hard_stop_codes.append(HardStopCode.HS03)
            # Anpassningsbart läge: flagga integritetsavvikelse (HS03) utan hårt avbrott.
            self.case_state.hard_stop_chain_abort = False
            self.case_state.pipeline_state = PipelineState.COMPLETE

        self.case_state.files = all_files
        self.log.append(
            f"[L0] Ingestion klar: {len(all_files)} filer, "
            f"{unverified} utan SHA-256 ({pct_unverified:.1f}%)"
        )

        # Registrera filhashar i reproducibility record
        if self.case_state.reproducibility:
            for f in all_files:
                self.case_state.reproducibility.file_hashes[f.file_id] = f.hash_sha256

        return True

    def _process_file(self, full_path: str, rel_path: str) -> FileRecord:
        """Processar en enskild fil."""
        file_id = generate_file_id(rel_path)
        sha256 = compute_sha256(full_path)
        md5 = compute_md5(full_path)
        magic = detect_filetype_magic(full_path)
        size = 0
        try:
            size = os.path.getsize(full_path)
        except OSError:
            pass

        # Klassificera baseline-state baserat på filnamn/sökväg
        baseline = self._classify_baseline(rel_path)
        quarantine = (baseline == BaselineState.UNSOLICITED_INPUT)

        record = FileRecord(
            file_id=file_id,
            file_path=full_path,
            relative_path=rel_path,
            hash_sha256=sha256,
            hash_md5=md5,
            filtyp_magic=magic,
            file_size_bytes=size,
            baseline_state=baseline,
            procedural_status="OFFICIALLY_SUBMITTED" if baseline == BaselineState.LOCKED_BASELINE else "UNKNOWN",
            quarantine_flag=quarantine,
        )
        self.log.append(
            f"[L0] {file_id} | {rel_path} | {magic} | "
            f"{baseline.value} | SHA256: {sha256[:16]}..."
        )
        return record

    def _classify_baseline(self, rel_path: str) -> BaselineState:
        """
        Klassificerar fil som LOCKED_BASELINE eller UNSOLICITED_INPUT
        baserat på sökväg och filnamn.
        """
        path_lower = rel_path.lower()
        # Aktbilagor, polisprotokoll, FUP → LOCKED_BASELINE
        locked_indicators = [
            "aktbilaga", "aktbilagor", "dom", "beslut", "protokoll",
            "inlaga", "stämningsansökan", "överklagande", "yttrande",
            "läkarintyg", "journal", "fup", "förundersökning",
        ]
        for indicator in locked_indicators:
            if indicator in path_lower:
                return BaselineState.LOCKED_BASELINE
        # Oombett/nyupptäckt material → UNSOLICITED_INPUT
        unsolicited_indicators = ["ny_", "new_", "oombett", "karantän", "quarantine"]
        for indicator in unsolicited_indicators:
            if indicator in path_lower:
                return BaselineState.UNSOLICITED_INPUT
        # Standard: LOCKED_BASELINE för allt åberopat material
        return BaselineState.LOCKED_BASELINE


# ============================================================
# EVIDENCE CLASSIFIER AGENT (FAS 2)
# ============================================================

class EvidenceClassifierAgent:
    """
    FAS 2: CLASSIFICATION_AND_CAPABILITY_MAPPING
    Klassificerar filer som Kategori A (stark) eller B (risk).
    """

    def __init__(self, case_state: CaseState):
        self.case_state = case_state
        self.log: List[str] = []

    def classify(self) -> None:
        """Klassificerar alla filer i case_state.files."""
        for file_record in self.case_state.files:
            category = self._classify_file(file_record)
            file_record.evidence_category = category
            self.log.append(
                f"[L2] {file_record.file_id} → {category.value}"
            )

    def _classify_file(self, record: FileRecord) -> EvidenceCategory:
        """
        Kategori A: Direkt bevisning med bekräftad integritet.
        Villkor: ej karantän + LOCKED_BASELINE + integritet VERIFIED
        
        Kategori B: Brus, svagheter eller oombett material.
        Villkor: quarantine_flag=true ELLER integritet=KAN EJ VERIFIERAS
        """
        if record.quarantine_flag:
            return EvidenceCategory.CATEGORY_B_RISK
        if record.hash_sha256 == "KAN EJ VERIFIERAS":
            return EvidenceCategory.CATEGORY_B_RISK
        if record.baseline_state != BaselineState.LOCKED_BASELINE:
            return EvidenceCategory.CATEGORY_B_RISK
        return EvidenceCategory.CATEGORY_A_STRONG


# ============================================================
# CAPABILITY MAP ENGINE (FAS 2)
# ============================================================

class CapabilityMapEngine:
    """
    FAS 2: Dynamisk modulaktivering baserat på filtyper och nyckelord.
    En modul aktiveras ALDRIG utan stöd i materialet.
    """

    AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}
    VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
    FINANCIAL_KEYWORDS = {"bank", "transaktion", "transfer", "faktura", "bokföring"}
    MEDICAL_KEYWORDS = {"läkar", "journal", "rättsintyg", "diagnos", "patient"}
    JUDGMENT_KEYWORDS = {"dom", "beslut", "tingsrätt", "hovrätt", "förvaltningsrätt"}
    FK_KEYWORDS = {"försäkringskassan", "sjukpenning", "sgi", "rehabilitering", "sfb"}
    SOL_KEYWORDS = {"socialtjänst", "sol", "lvu", "lvm", "lss", "socialnämnd"}
    TVISTEMÅL_KEYWORDS = {"hyresrätt", "lokalhyra", "edition", "tvistemål", "skadestånd"}
    PATIENTSKADA_KEYWORDS = {"patientskada", "felbehandling", "löf", "patientskadelagen"}

    def __init__(self, case_state: CaseState):
        self.case_state = case_state
        self.log: List[str] = []

    def map_capabilities(self) -> List[str]:
        """Identifierar och aktiverar relevanta moduler."""
        activated = set()

        # Alltid aktiva moduler
        activated.add("DOCUMENT_FORENSICS")
        activated.add("METADATA_FORENSICS")
        activated.add("PROCEDURAL")
        activated.add("LEGAL_SOURCE")

        for file_record in self.case_state.files:
            path_lower = file_record.relative_path.lower()
            ext = Path(file_record.relative_path).suffix.lower()

            # Audio Forensics
            if ext in self.AUDIO_EXTENSIONS or "audio" in file_record.filtyp_magic.lower():
                activated.add("AUDIO_FORENSICS")

            # Video Forensics
            if ext in self.VIDEO_EXTENSIONS:
                activated.add("VIDEO_FORENSICS")

            # Finansiell analys
            if any(kw in path_lower for kw in self.FINANCIAL_KEYWORDS):
                activated.add("FINANCIAL_ANALYSIS")

            # Medicinsk analys
            if any(kw in path_lower for kw in self.MEDICAL_KEYWORDS):
                activated.add("MEDICAL_ANALYSIS")

            # Judgment Audit
            if any(kw in path_lower for kw in self.JUDGMENT_KEYWORDS):
                activated.add("JUDGMENT_AUDIT")

            # Socialförsäkring
            if any(kw in path_lower for kw in self.FK_KEYWORDS):
                activated.add("SOCIALFÖRSÄKRING_FORENSISK_MODUL")

            # Socialtjänst
            if any(kw in path_lower for kw in self.SOL_KEYWORDS):
                activated.add("SOCIALTJÄNST_KUNSKAPSBAS")

            # Tvistemål
            if any(kw in path_lower for kw in self.TVISTEMÅL_KEYWORDS):
                activated.add("TVISTEMÅL_FORENSISK_MODUL")

            # Patientskada
            if any(kw in path_lower for kw in self.PATIENTSKADA_KEYWORDS):
                activated.add("PATIENTSKADA_SKADESTÅND_MODUL")

        modules = sorted(activated)
        self.case_state.activated_modules = modules
        if self.case_state.reproducibility:
            self.case_state.reproducibility.activated_modules = modules

        for mod in modules:
            self.log.append(f"[CAPABILITY] Aktiverad modul: {mod}")

        return modules


# ============================================================
# RELATION GRAPH BUILDER (FAS 3)
# ============================================================

class RelationGraphBuilder:
    """
    FAS 3: VERBATIM_GATING_AND_RELATION_GRAPH
    Bygger relationsgraf med VerbatimAnchor-gate.
    Ingen kant skapas utan exakt, ordagrant citat från SHA-256-verifierad primärkälla.
    """

    def __init__(self, case_state: CaseState):
        self.case_state = case_state
        self.log: List[str] = []
        self._edge_counter = 0

    def add_edge(
        self,
        source_node: str,
        target_node: str,
        edge_type: EdgeType,
        anchor: Optional[VerbatimAnchor] = None,
    ) -> GraphEdge:
        """
        Lägger till en kant i grafen.
        Om ankaret är ogiltigt tvingas kanten till UNRESOLVED (zero inference policy).
        """
        self._edge_counter += 1
        edge_id = f"EDGE-{self._edge_counter:04d}"
        edge = GraphEdge(
            edge_id=edge_id,
            source_node=source_node,
            target_node=target_node,
            edge_type=edge_type,
            anchor=anchor,
        )
        # GraphEdge.__post_init__ hanterar UNRESOLVED-tvång
        if edge.edge_type == EdgeType.UNRESOLVED:
            self.log.append(
                f"[GRAPH] {edge_id}: {source_node} → {target_node} "
                f"TVINGAS UNRESOLVED (ogiltigt ankare)"
            )
        else:
            self.log.append(
                f"[GRAPH] {edge_id}: {source_node} → {target_node} "
                f"[{edge.edge_type.value}]"
            )
        self.case_state.graph_edges.append(edge)
        return edge

    # ── Ankarkonstruktion ────────────────────────────────────────────────
    def _file_by_id(self, file_id: str) -> Optional[FileRecord]:
        for f in self.case_state.files:
            if f.file_id == file_id:
                return f
        return None

    def build_anchor(self, claim: ClaimId) -> Optional[VerbatimAnchor]:
        """
        Bygger ett VerbatimAnchor för ett claim mot dess källdokument.

        verified sätts ENDAST när hela kedjan håller: källdokumentet är
        återfunnet, SHA-256-verifierat, låst baseline, ej i karantän, och
        claimets text är ordagrant hämtad ur det dokumentet. Håller inte
        kedjan lämnas verified=False, varpå GraphEdge.__post_init__ tvingar
        kanten till UNRESOLVED (zero inference policy).
        """
        källa = self._file_by_id(claim.source_id)
        if källa is None:
            return None
        if not claim.content or not claim.content.strip():
            return None

        kedjan_håller = (
            källa.hash_sha256 != "KAN EJ VERIFIERAS"
            and källa.baseline_state == BaselineState.LOCKED_BASELINE
            and not källa.quarantine_flag
            and claim.availability == Availability.VERIFIED
        )

        return VerbatimAnchor(
            source_id=claim.source_id,
            source_path=källa.relative_path,
            source_hash=källa.hash_sha256,
            page_or_time=claim.page or "SAKNAS",
            verbatim_quote=claim.content,
            verified=kedjan_håller,
        )

    def build_provenance_edges(self) -> int:
        """
        FAS 3a: härkomstkanter claim → källdokument (DERIVES_FROM).

        Detta är dokumenterad härkomst, inte bevisvärdering: kanten säger att
        claimet är hämtat ur dokumentet, aldrig att det styrker något.
        Innehållsmässig bevisrelation (SUPPORTS) byggs separat och först när
        rekvisitmatrisen finns.
        """
        skapade = 0
        for claim in self.case_state.claims:
            anchor = self.build_anchor(claim)
            if anchor is None:
                continue
            self.add_edge(
                source_node=claim.claim_id,
                target_node=claim.source_id,
                edge_type=EdgeType.DERIVES_FROM,
                anchor=anchor,
            )
            skapade += 1
        return skapade

    def build_requisite_edges(self, mappningar: List[Any]) -> int:
        """
        FAS 3b: kanter claim → rekvisit (SUPPORTS) ur rekvisitmappningen.

        En kant skapas bara för claims som mappern faktiskt kopplat till
        rekvisitet, och bara med verifierat ordagrant ankare. Saknas ankare
        blir kanten UNRESOLVED och fångas av Audit-agent A.
        """
        claim_index = {c.claim_id: c for c in self.case_state.claims}
        skapade = 0
        for m in mappningar or []:
            rekvisit_text = getattr(m, "rekvisit_text", "")
            if not rekvisit_text:
                continue
            mål_nod = f"REKVISIT:{rekvisit_text[:60]}"
            for claim_id in (getattr(m, "kopplade_claims", None) or []):
                claim = claim_index.get(claim_id)
                if claim is None:
                    continue
                self.add_edge(
                    source_node=claim.claim_id,
                    target_node=mål_nod,
                    edge_type=EdgeType.SUPPORTS,
                    anchor=self.build_anchor(claim),
                )
                skapade += 1
        return skapade

    def get_unresolved_edges(self) -> List[GraphEdge]:
        return [e for e in self.case_state.graph_edges if e.edge_type == EdgeType.UNRESOLVED]

    def get_stats(self) -> Dict[str, int]:
        total = len(self.case_state.graph_edges)
        unresolved = len(self.get_unresolved_edges())
        return {
            "total_edges": total,
            "verified_edges": total - unresolved,
            "unresolved_edges": unresolved,
        }


# ============================================================
# ANKARVERIFIERING MOT KÄLLA (FAS 3b)
# ============================================================
#
# build_anchor ovan sätter verified utifrån vad som registrerades när filen
# togs in: att en hash beräknats, att baslinjen är låst, att filen inte är i
# karantän och att claimet är primärextraherat. Det är förhållanden vid
# INTAGET.
#
# Ingenting prövade därefter att förhållandena fortfarande gäller när grafen
# byggs, och ingenting prövade att citatet faktiskt står i källan. Ett ankare
# som heter VerbatimAnchor kontrollerade alltså aldrig ordagrannheten.
#
# I den nuvarande kedjan är claim.content en prefix av ett extraherat segment
# (TextSegment.to_claim_id), så ordagrannheten är sann genom konstruktion.
# Det gör kontrollen nedan till ett skydd mot att kedjan går sönder MELLAN
# extraktion och grafbygge: en källfil som bytts ut eller tagits bort under
# körningen, eller ett claim vars sida inte finns i extraktionen.
#
# Zero inference: kan förhållandet inte visas maskinellt sätts verified=False
# och kanten tvingas UNRESOLVED. Ingen kontroll hoppas över tyst — varje
# nedgradering får ett skäl som redovisas i case_state.metadata.


def _parse_sidnummer(page_or_time: str) -> Optional[int]:
    """Tolkar 's.12' eller '12' till 12. None när fältet inte är ett sidnummer."""
    if not page_or_time:
        return None
    m = re.match(r"^(?:s\.)?(\d+)$", str(page_or_time).strip())
    return int(m.group(1)) if m else None


def _normalisera_blanksteg(text: str) -> str:
    """Radbrytning och dubbla mellanslag skiljer sig mellan extraktionsvägarna."""
    return re.sub(r"\s+", " ", (text or "")).strip()


def _sidtexter_per_fil(extraction_results: Dict[str, Any]) -> Dict[str, Dict[str, List[str]]]:
    """file_id -> sidbeteckning -> [segmenttexter]. Ingen omextraktion."""
    ut: Dict[str, Dict[str, List[str]]] = {}
    for file_id, res in (extraction_results or {}).items():
        sidor: Dict[str, List[str]] = {}
        for seg in (getattr(res, "segments", None) or []):
            sidor.setdefault(str(getattr(seg, "page_or_position", "")), []).append(
                getattr(seg, "text", "") or ""
            )
        ut[file_id] = sidor
    return ut


def verifiera_ankare_mot_kalla(
    case_state: CaseState,
    extraction_results: Dict[str, Any],
) -> Dict[str, Any]:
    """
    FAS 3b: prövar varje redan verifierat ankare mot källan som den ser ut nu.

    Tre kontroller som saknades, alla mekaniska:
      1. källfilen finns kvar på disk
      2. SHA-256 på disk är oförändrad mot FileRecord.hash_sha256
      3. citatet står ordagrant (normaliserade blanksteg) på den sida
         claimet anger

    Faller någon av dem sätts anchor.verified=False och kanten tvingas
    UNRESOLVED. Returnerar en rapport som skrivs till case_state.metadata.
    """
    filer = {f.file_id: f for f in case_state.files}
    claims = {c.claim_id: c for c in case_state.claims}
    sidtexter = _sidtexter_per_fil(extraction_results)

    hash_cache: Dict[str, Optional[bool]] = {}

    def _hash_ok(fr: FileRecord) -> Optional[bool]:
        """True/False, eller None när filen inte finns kvar."""
        if fr.file_id in hash_cache:
            return hash_cache[fr.file_id]
        if not fr.file_path or not os.path.exists(fr.file_path):
            svar: Optional[bool] = None
        elif fr.hash_sha256 in ("", "KAN EJ VERIFIERAS"):
            svar = False
        else:
            svar = compute_sha256(fr.file_path).lower() == fr.hash_sha256.lower()
        hash_cache[fr.file_id] = svar
        return svar

    nedgraderade: List[Dict[str, str]] = []
    prövade = 0

    for edge in case_state.graph_edges:
        ankare = edge.anchor
        if ankare is None or not ankare.verified:
            continue
        prövade += 1

        fr = filer.get(ankare.source_id)
        skäl = None

        if fr is None:
            skäl = "KÄLLPOST_SAKNAS"
        else:
            h = _hash_ok(fr)
            if h is None:
                skäl = "KÄLLFIL_BORTA"
            elif h is False:
                skäl = "HASH_AVVIKER"

        if skäl is None:
            claim = claims.get(edge.source_node)
            sidor = sidtexter.get(ankare.source_id)
            if sidor is None:
                skäl = "EXTRAKTION_SAKNAS"
            else:
                sida = ankare.page_or_time
                kandidater = sidor.get(str(sida))
                if kandidater is None and _parse_sidnummer(sida) is not None:
                    # 's.3' och '3' är samma sida, skrivna olika av olika vägar.
                    n = _parse_sidnummer(sida)
                    for nyckel, texter in sidor.items():
                        if _parse_sidnummer(nyckel) == n:
                            kandidater = texter
                            break
                if kandidater is None:
                    skäl = "SIDA_SAKNAS_I_EXTRAKTION"
                else:
                    citat = _normalisera_blanksteg(
                        ankare.verbatim_quote or (claim.content if claim else "")
                    )
                    if not citat:
                        skäl = "CITAT_TOMT"
                    elif not any(
                        citat in _normalisera_blanksteg(t) for t in kandidater
                    ):
                        skäl = "CITAT_EJ_ORDAGRANT_PA_SIDAN"

        if skäl is not None:
            ankare.verified = False
            edge.edge_type = EdgeType.UNRESOLVED
            nedgraderade.append({
                "edge_id": edge.edge_id,
                "claim_id": edge.source_node,
                "source_id": ankare.source_id,
                "sida": ankare.page_or_time,
                "skäl": skäl,
            })

    rapport = {
        "prövade_ankare": prövade,
        "nedgraderade": len(nedgraderade),
        "detaljer": nedgraderade,
    }
    case_state.metadata["ankarverifiering"] = rapport
    return rapport


# ============================================================
# SUBSUMPTION GATEKEEPER (FAS 4)
# ============================================================

class SubsumptionGatekeeper:
    """
    FAS 4: SUBSUMPTION_GATEKEEPER
    Hård grind – subsumtion passeras inte om bevis- eller rättskällkedjan är bruten.
    """

    def __init__(self, case_state: CaseState):
        self.case_state = case_state
        self.log: List[str] = []

    def check_file(self, file_record: FileRecord) -> bool:
        """
        Kontrollerar om en fil kan passera till subsumtion.
        Villkor: quarantine_flag=false + LOCKED_BASELINE + integritet VERIFIED
        """
        if file_record.quarantine_flag:
            self.log.append(
                f"[GATE] {file_record.file_id} BLOCKERAD: quarantine_flag=true"
            )
            return False
        if file_record.baseline_state != BaselineState.LOCKED_BASELINE:
            self.log.append(
                f"[GATE] {file_record.file_id} BLOCKERAD: baseline_state="
                f"{file_record.baseline_state.value}"
            )
            return False
        if file_record.hash_sha256 == "KAN EJ VERIFIERAS":
            self.log.append(
                f"[GATE] {file_record.file_id} BLOCKERAD: integritet=KAN EJ VERIFIERAS"
            )
            return False
        self.log.append(f"[GATE] {file_record.file_id} GODKÄND")
        return True

    def check_requisite_matrix(self) -> Tuple[bool, List[str]]:
        """
        Kontrollerar LEGAL_REQUISITE_GATE.
        Returnerar (gate_passed, list_of_blocking_requisites).
        """
        # En TOM rekvisitmatris är inte ett godkännande. Den betyder att
        # måltypen inte kunnat fastställas eller att rekvisitdefinitioner
        # saknas — i båda fallen finns inget att subsumera mot, och grinden
        # måste vara stängd. Tidigare returnerade tom matris (True, []), vilket
        # gav ett tyst PASSERAD på obefintligt underlag.
        if not self.case_state.requisite_matrix:
            skäl = self.case_state.metadata.get(
                "requisite_matrix_blocked_reason",
                "Rekvisitmatrisen är tom – måltyp eller rekvisitdefinitioner saknas.",
            )
            # Steg 14b: tom matris är ett kritiskt pipelinefel, inte HS11:s förklaring.
            self.log.append(f"[GATE] KRITISKT PIPELINEFEL: {skäl}")
            self.log.append("[GATE] LEGAL_REQUISITE_GATE SPÄRRAD → HS11 "
                            "(saknat funktionellt krav: SAKNAS)")
            # Samma mönster som HS01C/HS03: kod och flagga sätts tillsammans
            # (kvalitetskontrollens HARD_STOP_KONSISTENS, steg 10).
            self.case_state.hard_stop_active = True
            if HardStopCode.HS11 not in self.case_state.hard_stop_codes:
                self.case_state.hard_stop_codes.append(HardStopCode.HS11)
            return False, ["REKVISITMATRIS_TOM"]

        blocking = []
        for req in self.case_state.requisite_matrix:
            if (req.modal == ModalMarker.MUST and
                    req.status == RequisiteStatus.BEVISNING_SAKNAS):
                blocking.append(req.requisite_text)
                self.log.append(
                    f"[GATE] LEGAL_REQUISITE_GATE SPÄRRAD: "
                    f"MUST-rekvisit '{req.requisite_text[:50]}' = BEVISNING_SAKNAS → HS11"
                )

        if blocking:
            self.case_state.hard_stop_active = True
            if HardStopCode.HS11 not in self.case_state.hard_stop_codes:
                self.case_state.hard_stop_codes.append(HardStopCode.HS11)
            return False, blocking
        return True, []

    def get_blocked_files(self) -> List[FileRecord]:
        return [f for f in self.case_state.files if not self.check_file(f)]

    def get_passed_files(self) -> List[FileRecord]:
        return [f for f in self.case_state.files if self.check_file(f)]


# ============================================================
# BIDIRECTIONAL AUDIT ENGINE + AUDIT AGENTS A/B/C (FAS 5)
# ============================================================

class AuditAgentA:
    """
    L12: Audit-agent A – Falsifiering
    Söker aktivt efter avvikelser. ALLTID AKTIV oavsett HS-status.
    """

    def __init__(self, case_state: CaseState):
        self.case_state = case_state
        self.log: List[str] = []
        self._finding_counter = 0

    def run(self) -> List[AuditFinding]:
        """Kör falsifiering mot primärkällor och rättskällor."""
        findings: List[AuditFinding] = []

        # Kontroll 1: UNRESOLVED-kanter i grafen
        unresolved = [
            e for e in self.case_state.graph_edges
            if e.edge_type == EdgeType.UNRESOLVED
        ]
        if unresolved:
            for edge in unresolved:
                self._finding_counter += 1
                finding = AuditFinding(
                    finding_id=f"AUDIT-A-{self._finding_counter:03d}",
                    agent="A",
                    description=(
                        f"UNRESOLVED grafkant: {edge.edge_id} "
                        f"({edge.source_node} → {edge.target_node}) – "
                        f"VerbatimAnchor saknas eller ej verifierad"
                    ),
                    source_ref=edge.edge_id,
                    severity="HÖG",
                )
                findings.append(finding)
                self.log.append(f"[L12] {finding.finding_id}: {finding.description}")

        # Kontroll 2: EVIDENCED_FACT på PARTIALLY_AVAILABLE (FIX-C)
        for claim in self.case_state.claims:
            errors = claim.validate()
            for error in errors:
                if "FIX-C-BROTT" in error:
                    self._finding_counter += 1
                    finding = AuditFinding(
                        finding_id=f"AUDIT-A-{self._finding_counter:03d}",
                        agent="A",
                        description=f"FIX-C-BROTT: {claim.claim_id} – {error}",
                        source_ref=claim.claim_id,
                        severity="KRITISK",
                    )
                    findings.append(finding)
                    self.log.append(f"[L12] {finding.finding_id}: {finding.description}")

        # Kontroll 3: Kategori B-filer som passerat gatekeeper
        for file_record in self.case_state.files:
            if (file_record.evidence_category == EvidenceCategory.CATEGORY_B_RISK and
                    not file_record.quarantine_flag):
                self._finding_counter += 1
                finding = AuditFinding(
                    finding_id=f"AUDIT-A-{self._finding_counter:03d}",
                    agent="A",
                    description=(
                        f"Kategori B-fil utan karantänflagga: {file_record.file_id} "
                        f"({file_record.relative_path})"
                    ),
                    source_ref=file_record.file_id,
                    severity="MEDEL",
                )
                findings.append(finding)
                self.log.append(f"[L12] {finding.finding_id}: {finding.description}")

        if not findings:
            self.log.append("[L12] [INGA AVVIKELSER IDENTIFIERADE – AUDIT-AGENT A]")

        # Fynd från andra producenter får inte kastas. L9 (FUP-agenten) skriver
        # sina fynd till samma lista tidigare i pipelinen; en ren tilldelning
        # här raderade dem. Effekten var att 50 identifierade diskrepanser
        # försvann och rapporten skrev "INGA AVVIKELSER IDENTIFIERADE".
        befintliga = {f.finding_id for f in self.case_state.audit_a_findings}
        self.case_state.audit_a_findings.extend(
            f for f in findings if f.finding_id not in befintliga
        )
        return findings


class AuditAgentB:
    """
    L13: Audit-agent B – Verifiering
    Bekräftar giltiga stöd. ALLTID AKTIV oavsett HS-status.
    """

    def __init__(self, case_state: CaseState):
        self.case_state = case_state
        self.log: List[str] = []
        self._finding_counter = 0

    def run(self) -> List[AuditFinding]:
        """Kör verifiering mot primärkällor."""
        findings: List[AuditFinding] = []

        # Kontroll 1: Kategori A-filer med verifierad integritet
        verified_a = [
            f for f in self.case_state.files
            if (f.evidence_category == EvidenceCategory.CATEGORY_A_STRONG and
                f.hash_sha256 != "KAN EJ VERIFIERAS")
        ]
        if verified_a:
            self._finding_counter += 1
            finding = AuditFinding(
                finding_id=f"AUDIT-B-{self._finding_counter:03d}",
                agent="B",
                description=(
                    f"Verifierade Kategori A-filer: {len(verified_a)} st med "
                    f"bekräftad SHA-256-integritet"
                ),
                source_ref="L0_KÄLLREGISTER",
                severity="LÅG",
            )
            findings.append(finding)
            self.log.append(f"[L13] {finding.finding_id}: {finding.description}")

        # Kontroll 2: SUPPORTS-kanter med giltig ankare
        valid_supports = [
            e for e in self.case_state.graph_edges
            if (e.edge_type == EdgeType.SUPPORTS and
                e.anchor is not None and e.anchor.is_valid())
        ]
        if valid_supports:
            self._finding_counter += 1
            finding = AuditFinding(
                finding_id=f"AUDIT-B-{self._finding_counter:03d}",
                agent="B",
                description=(
                    f"Verifierade SUPPORTS-kanter: {len(valid_supports)} st "
                    f"med giltig VerbatimAnchor"
                ),
                source_ref="RELATIONSGRAF",
                severity="LÅG",
            )
            findings.append(finding)
            self.log.append(f"[L13] {finding.finding_id}: {finding.description}")

        # Kontroll 3: Rättskällor med LEGAL_SOURCE_RECORD
        if self.case_state.legal_sources:
            self._finding_counter += 1
            finding = AuditFinding(
                finding_id=f"AUDIT-B-{self._finding_counter:03d}",
                agent="B",
                description=(
                    f"Rättskällor i LEGAL_SOURCE_RECORD-format: "
                    f"{len(self.case_state.legal_sources)} st"
                ),
                source_ref="L7_RÄTTSKÄLLEKONTROLL",
                severity="LÅG",
            )
            findings.append(finding)
            self.log.append(f"[L13] {finding.finding_id}: {finding.description}")

        if not findings:
            self.log.append("[L13] [INGA STÖD IDENTIFIERADE – AUDIT-AGENT B]")

        # Fynd från andra producenter får inte kastas. L9 (FUP-agenten) skriver
        # sina fynd till samma lista tidigare i pipelinen; en ren tilldelning
        # här raderade dem. Effekten var att 50 identifierade diskrepanser
        # försvann och rapporten skrev "INGA AVVIKELSER IDENTIFIERADE".
        befintliga = {f.finding_id for f in self.case_state.audit_b_findings}
        self.case_state.audit_b_findings.extend(
            f for f in findings if f.finding_id not in befintliga
        )
        return findings


class CircularReasoningBlocker:
    """
    CIRCULAR_REASONING_BLOCKER (FIX-Q, HS10).
    Domen får ALDRIG användas som primärkälla för sina egna fakta.
    Identifierar SUPPORTS-kanter som utgår från en DOM-källa och
    registrerar HS10 vid förekomst.
    """

    def __init__(self, case_state: CaseState):
        self.case_state = case_state

    def find_circular_edges(self) -> List[GraphEdge]:
        """Returnerar kanter som utgör möjligt cirkelresonemang (DOM → SUPPORTS)."""
        dom_ids = {
            f.file_id for f in self.case_state.files
            if "dom" in f.relative_path.lower() or "DOM-" in f.file_id
        }
        return [
            e for e in self.case_state.graph_edges
            if (e.anchor and e.anchor.source_id in dom_ids and
                e.edge_type == EdgeType.SUPPORTS)
        ]

    def block(self) -> List[GraphEdge]:
        """Markerar cirkulära kanter och registrerar HS10. Returnerar blockerade kanter."""
        circular = self.find_circular_edges()
        if circular and HardStopCode.HS10 not in self.case_state.hard_stop_codes:
            self.case_state.hard_stop_codes.append(HardStopCode.HS10)
        return circular


class AuditAgentC:
    """
    L14: Audit-agent C – Second-order audit
    Kontrollerar A och B oberoende. ALLTID AKTIV oavsett HS-status.
    """

    def __init__(self, case_state: CaseState):
        self.case_state = case_state
        self.log: List[str] = []
        self._finding_counter = 0

    def run(self) -> List[AuditFinding]:
        """Kör second-order audit av A och B."""
        findings: List[AuditFinding] = []

        # Kontroll 1: P18 Symmetrikontroll
        # (Kontrollerar att båda parters argument behandlas lika)
        # I denna implementation: kontrollera att inga claims saknar källhänvisning
        claims_without_source = [
            c for c in self.case_state.claims
            if c.source_id == "SAKNAS" or not c.source_id
        ]
        if claims_without_source:
            self._finding_counter += 1
            finding = AuditFinding(
                finding_id=f"AUDIT-C-{self._finding_counter:03d}",
                agent="C",
                description=(
                    f"P18 SYMMETRY-kontroll: {len(claims_without_source)} claims "
                    f"saknar källhänvisning (FIX-J-brott)"
                ),
                source_ref="L2_CLAIM_REGISTER",
                severity="HÖG",
            )
            findings.append(finding)
            self.log.append(f"[L14] {finding.finding_id}: {finding.description}")

        # Kontroll 2: CIRCULAR_REASONING_BLOCKER
        # Kontrollera att inga DOM-källor används som primärkälla för egna fakta
        circular_edges = CircularReasoningBlocker(self.case_state).block()
        if circular_edges:
            self._finding_counter += 1
            finding = AuditFinding(
                finding_id=f"AUDIT-C-{self._finding_counter:03d}",
                agent="C",
                description=(
                    f"CIRCULAR_REASONING_BLOCKER: {len(circular_edges)} SUPPORTS-kanter "
                    f"använder DOM-källa som primärkälla – möjligt cirkelresonemang [HS10]"
                ),
                source_ref="RELATIONSGRAF",
                severity="KRITISK",
            )
            findings.append(finding)
            self.log.append(f"[L14] {finding.finding_id}: {finding.description}")

        # Kontroll 3: Asymmetrivarning (A hittar avvikelser, B hittar inget stöd)
        if (self.case_state.audit_a_findings and
                not self.case_state.audit_b_findings):
            self._finding_counter += 1
            finding = AuditFinding(
                finding_id=f"AUDIT-C-{self._finding_counter:03d}",
                agent="C",
                description=(
                    "ASYMMETRIVARNING: Audit-A identifierade avvikelser men "
                    "Audit-B hittade inga stöd – asymmetrisk analys"
                ),
                source_ref="L12_L13",
                severity="MEDEL",
            )
            findings.append(finding)
            self.log.append(f"[L14] {finding.finding_id}: {finding.description}")

        if not findings:
            self.log.append("[L14] [SECOND-ORDER AUDIT GODKÄND – AUDIT-AGENT C]")

        # Fynd från andra producenter får inte kastas. L9 (FUP-agenten) skriver
        # sina fynd till samma lista tidigare i pipelinen; en ren tilldelning
        # här raderade dem. Effekten var att 50 identifierade diskrepanser
        # försvann och rapporten skrev "INGA AVVIKELSER IDENTIFIERADE".
        befintliga = {f.finding_id for f in self.case_state.audit_c_findings}
        self.case_state.audit_c_findings.extend(
            f for f in findings if f.finding_id not in befintliga
        )
        return findings


# ============================================================
# AGENT_C_STRESS_TEST (Adversarial Pass)
# ============================================================

class AgentCStressTest:
    """
    AGENT_C_STRESS_TEST – Adversarial Pass
    Körs ALLTID efter L14 och innan L15. Kan INTE hoppas över.
    """

    def __init__(self, case_state: CaseState):
        self.case_state = case_state
        self.log: List[str] = []
        self.svagaste_lankar: List[Dict[str, str]] = []
        self.alternativa_tolkningar: List[Dict[str, str]] = []
        self.processuella_invandningar: List[Dict[str, str]] = []

    def run(self) -> Dict[str, Any]:
        """Kör alla tre obligatoriska kontroller."""
        self.log.append("[STRESS_TEST] AGENT_C_STRESS_TEST startar")

        self._kontroll_1_svagaste_lank()
        self._kontroll_2_alternativa_tolkningar()
        self._kontroll_3_processuella_invandningar()

        samlad_risk = self._berakna_samlad_risk()

        result = {
            "svagaste_lankar": self.svagaste_lankar,
            "alternativa_tolkningar": self.alternativa_tolkningar,
            "processuella_invandningar": self.processuella_invandningar,
            "samlad_riskbedömning": samlad_risk,
        }

        self.log.append(
            f"[STRESS_TEST] Klar. Samlad risk: {samlad_risk}. "
            f"Svagaste länkar: {len(self.svagaste_lankar)}, "
            f"Alternativa tolkningar: {len(self.alternativa_tolkningar)}, "
            f"Processuella invändningar: {len(self.processuella_invandningar)}"
        )
        return result

    def _kontroll_1_svagaste_lank(self) -> None:
        """Identifierar svagaste länken i argumentationskedjan."""
        counter = 1

        # Kontrollera UNRESOLVED-kanter
        unresolved = [
            e for e in self.case_state.graph_edges
            if e.edge_type == EdgeType.UNRESOLVED
        ]
        if unresolved:
            self.svagaste_lankar.append({
                "id": f"SVAGASTE_LÄNK-{counter:03d}",
                "sårbarhet": (
                    f"{len(unresolved)} UNRESOLVED grafkanter utan VerbatimAnchor – "
                    f"öppnar för motpartens angrepp"
                ),
                "rättslig_påverkan": "HÖG",
                "källa": "RELATIONSGRAF",
            })
            counter += 1

        # Kontrollera TVISTIGA rekvisit
        tvistiga = [
            r for r in self.case_state.requisite_matrix
            if r.status == RequisiteStatus.TVISTIGT
        ]
        for req in tvistiga:
            self.svagaste_lankar.append({
                "id": f"SVAGASTE_LÄNK-{counter:03d}",
                "sårbarhet": (
                    f"TVISTIGT rekvisit: '{req.requisite_text[:60]}' – "
                    f"motparten kan angripa detta"
                ),
                "rättslig_påverkan": "MEDEL",
                "källa": "L8_REKVISITMATRIS",
            })
            counter += 1

        # Kontrollera Kategori B-filer
        cat_b = [
            f for f in self.case_state.files
            if f.evidence_category == EvidenceCategory.CATEGORY_B_RISK
        ]
        if cat_b:
            self.svagaste_lankar.append({
                "id": f"SVAGASTE_LÄNK-{counter:03d}",
                "sårbarhet": (
                    f"{len(cat_b)} Kategori B-filer med osäker integritet – "
                    f"bevisvärdet kan ifrågasättas"
                ),
                "rättslig_påverkan": "MEDEL",
                "källa": "L0_KÄLLREGISTER",
            })

    def _kontroll_2_alternativa_tolkningar(self) -> None:
        """Identifierar alternativa tolkningar av åberopad bevisning."""
        counter = 1

        # Kontrollera CONTRADICTS-kanter
        contradicts = [
            e for e in self.case_state.graph_edges
            if e.edge_type == EdgeType.CONTRADICTS
        ]
        for edge in contradicts:
            self.alternativa_tolkningar.append({
                "id": f"ALT_TOLKNING-{counter:03d}",
                "bevisning": edge.edge_id,
                "alternativ_tolkning": (
                    f"CONTRADICTS-kant {edge.edge_id}: "
                    f"{edge.source_node} → {edge.target_node} – "
                    f"motparten kan använda denna motstridighet"
                ),
                "motpartens_möjliga_argument": "Bevisningen är motstridig och bör inte tillmätas bevisvärde",
            })
            counter += 1

    def _kontroll_3_processuella_invandningar(self) -> None:
        """Identifierar processuella invändningar som motparten kan resa."""
        counter = 1

        # Kontrollera om HS-koder är aktiva
        for hs_code in self.case_state.hard_stop_codes:
            risk = "HÖG" if hs_code in [HardStopCode.HS09, HardStopCode.HS10, HardStopCode.HS11] else "MEDEL"
            self.processuella_invandningar.append({
                "id": f"PROC_INVÄNDNING-{counter:03d}",
                "typ": hs_code.value,
                "risk": risk,
                "rättslig_grund": f"Hard Stop {hs_code.value} aktiverad",
                "motåtgärd": "Komplettera underlag och åtgärda hard stop innan fortsatt körning",
            })
            counter += 1

        # Kontrollera om UNRESOLVED-kanter finns (preklusion-risk)
        unresolved_count = sum(
            1 for e in self.case_state.graph_edges
            if e.edge_type == EdgeType.UNRESOLVED
        )
        if unresolved_count > 0:
            self.processuella_invandningar.append({
                "id": f"PROC_INVÄNDNING-{counter:03d}",
                "typ": "PREKLUSION",
                "risk": "MEDEL",
                "rättslig_grund": "RB 43:10 – bevisning åberopad utan verifierat ankare",
                "motåtgärd": f"Verifiera VerbatimAnchor för {unresolved_count} UNRESOLVED-kanter",
            })

    def _berakna_samlad_risk(self) -> str:
        """Beräknar samlad riskbedömning."""
        hög_risk = sum(
            1 for item in (
                self.svagaste_lankar + self.alternativa_tolkningar + self.processuella_invandningar
            )
            if item.get("rättslig_påverkan") == "HÖG" or item.get("risk") == "HÖG"
        )
        if hög_risk > 0 or self.case_state.hard_stop_active:
            return "HÖG"
        if (self.svagaste_lankar or self.alternativa_tolkningar or
                self.processuella_invandningar):
            return "MEDEL"
        return "LÅG"


# ============================================================
# COUNTER AUDIT AGENT B01–B15 (sektion 0n)
# ============================================================

class CounterAuditAgent:
    """
    COUNTER_AUDIT_AGENT B01–B15
    Körs efter L14 och FÖRE FALSIFICATION. Kan INTE hoppas över.

    Var och en av de femton standardiserade buggkoderna (B01–B15) har en
    dedikerad, exekverbar kontrollmetod (_check_b01 .. _check_b15). Den
    slutliga sårbarhetsrisken (case_state.sårbarhet_risk) beräknas
    hierarkiskt – den mest allvarliga upptäckta signalen vinner:
    KRITISK > HÖG > MEDEL > LÅG. Ingen signal skrivs över tyst:
    varje identifierad bugg registreras som ett unikt resultat i
    case_state.counter_audit_results.
    """

    # Allvarlighetskarta – används av sårbarhetskalkylatorn.
    BUG_SEVERITY = {
        # KRITISK – blockerar FALSIFICATION / styr VULNERABLE
        "B07": "KRITISK",   # Utelämnande
        "B09": "KRITISK",   # Rättskällefel (FIX-T)
        "B10": "KRITISK",   # Rekvisitfel (MUST utan bevisning)
        "B11": "KRITISK",   # Subsumtionsfel
        "B14": "KRITISK",   # Intern motsägelse
        "B15": "KRITISK",   # Oupplöst fråga
        # HÖG
        "B01": "HÖG",       # Dataintegritet
        "B02": "HÖG",       # Källfel
        "B05": "HÖG",       # Faktaavvikelse
        "B06": "HÖG",       # Bevisavvikelse
        "B08": "HÖG",       # Processfel
        "B12": "HÖG",       # Domskälsfel
        "B13": "HÖG",       # Beviskravsfel
        # MEDEL
        "B03": "MEDEL",     # Tidsfel
        "B04": "MEDEL",     # Identitetsfel
    }
    SEVERITY_ORDER = ("KRITISK", "HÖG", "MEDEL", "LÅG")

    def __init__(self, case_state: CaseState):
        self.case_state = case_state
        self.log: List[str] = []
        self.results: Dict[str, str] = {}
        self.identified: List[str] = []
        self.risk_level: str = "LÅG"

    def run(self) -> Dict[str, str]:
        """Kör alla 15 buggkontroller och beräknar sårbarhetsrisken."""
        self.log.append("[COUNTER_AUDIT] B01–B15 startar")

        self.results = {
            "B01": self._check_b01(),
            "B02": self._check_b02(),
            "B03": self._check_b03(),
            "B04": self._check_b04(),
            "B05": self._check_b05(),
            "B06": self._check_b06(),
            "B07": self._check_b07(),
            "B08": self._check_b08(),
            "B09": self._check_b09(),
            "B10": self._check_b10(),
            "B11": self._check_b11(),
            "B12": self._check_b12(),
            "B13": self._check_b13(),
            "B14": self._check_b14(),
            "B15": self._check_b15(),
        }

        # Ingen signal skrivs över tyst – hela resultatet finns i tillståndet.
        self.case_state.counter_audit_results = dict(self.results)

        self.identified = [k for k, v in self.results.items() if v == "IDENTIFIERAD"]
        self.risk_level = self._compute_risk_level(self.identified)
        self.case_state.sårbarhet_risk = self.risk_level

        critical = [b for b in self.identified if self.BUG_SEVERITY.get(b) == "KRITISK"]

        self.log.append(
            f"[COUNTER_AUDIT] Klar. Identifierade buggar: {len(self.identified)}, "
            f"Kritiska: {len(critical)} | Sårbarhet: {self.risk_level}"
        )

        if critical:
            self.log.append(
                f"[COUNTER_AUDIT] VARNING: kritiska buggar {critical} "
                f"identifierade – kör i icke-blockerande varningsläge"
            )

        return self.results

    def _compute_risk_level(self, identified: List[str]) -> str:
        """Hierarkisk kalkylator – den mest allvarliga signalen vinner."""
        for level in self.SEVERITY_ORDER:
            if any(self.BUG_SEVERITY.get(b) == level for b in identified):
                return level
        return "LÅG"

    def blocks_falsification(self) -> bool:
        """True om kritiska buggar blockerar FALSIFICATION (KRITISK-signal)."""
        critical = [b for b, sev in self.BUG_SEVERITY.items() if sev == "KRITISK"]
        return any(self.results.get(b) == "IDENTIFIERAD" for b in critical)

    def _file_by_id(self, file_id: str) -> Optional[Any]:
        for f in self.case_state.files:
            if f.file_id == file_id:
                return f
        return None

    @staticmethod
    def _parse_date(value) -> Optional[datetime.datetime]:
        """Tolerant datumtolkning (ISO-8601 eller ÅÅÅÅ-MM-DD)."""
        if not value:
            return None
        try:
            return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            try:
                return datetime.datetime.strptime(str(value), "%Y-%m-%d")
            except (ValueError, TypeError):
                return None
# ── B01: DATAINTEGRITET ─────────────────────────────────
    def _check_b01(self) -> str:
        """B01: SHA-256/MD5 saknas, magic bytes avviker eller filstorleken är noll."""
        # (legacy) hårdkodad juridisk slutsats utan verifierad kedja
        for claim in self.case_state.claims:
            if (claim.claim_type == "EVIDENCED_FACT" and
                    claim.availability != Availability.VERIFIED):
                return "IDENTIFIERAD"
        # (spec) filintegritet
        for f in self.case_state.files:
            if f.hash_sha256 in ("", "KAN EJ VERIFIERAS") or \
                    f.hash_md5 in ("", "KAN EJ VERIFIERAS"):
                return "IDENTIFIERAD"
            if f.file_size_bytes == 0:
                return "IDENTIFIERAD"
            if (f.metadata or {}).get("magic_bytes_ok") is False:
                return "IDENTIFIERAD"
        return "EJ IDENTIFIERAD"

    # ── B02: KÄLLFEL ────────────────────────────────────────
    def _check_b02(self) -> str:
        """B02: påstående/slutsats saknar motsvarande källnod eller giltigt citatankare."""
        # (legacy) court UNKNOWN med aktmaterial
        if (self.case_state.court_type == CourtType.UNKNOWN and
                len(self.case_state.files) > 0):
            return "IDENTIFIERAD"
        # (spec) claims utan källnod/ankare i relationsgrafen
        if self.case_state.claims and self.case_state.graph_edges:
            node_ids = set()
            for e in self.case_state.graph_edges:
                node_ids.add(e.source_node)
                node_ids.add(e.target_node)
                if e.anchor:
                    node_ids.add(e.anchor.source_id)
                    node_ids.add(e.anchor.source_path)
            for c in self.case_state.claims:
                if c.source_id and c.source_id != "SAKNAS" and \
                        c.source_id not in node_ids and c.claim_id not in node_ids:
                    return "IDENTIFIERAD"
        return "EJ IDENTIFIERAD"

    # ── B03: TIDSFEL ────────────────────────────────────────
    def _check_b03(self) -> str:
        """B03: kausalitetsavvikelser, ogiltiga datum, ändrat före skapat."""
        # (legacy) procentuell bevisvärdering
        for claim in self.case_state.claims:
            if re.search(r"\d+\s*%", claim.content):
                return "IDENTIFIERAD"
        # (spec) tidsfel i fil/metadata
        for f in self.case_state.files:
            meta = f.metadata or {}
            created = self._parse_date(meta.get("created_at") or meta.get("date_created"))
            modified = self._parse_date(meta.get("modified_at") or meta.get("date_modified"))
            if meta.get("created_at") and created is None:
                return "IDENTIFIERAD"        # ogiltigt datum
            if meta.get("modified_at") and modified is None:
                return "IDENTIFIERAD"
            if created and created.year < 1970:
                return "IDENTIFIERAD"        # kausalitetsavvikelse
            if created and modified and modified < created:
                return "IDENTIFIERAD"        # ändringsdatum före skapandedatum
        return "EJ IDENTIFIERAD"

    # ── B04: IDENTITETSFEL ──────────────────────────────────
    def _check_b04(self) -> str:
        """B04: tvetydiga roller, domstolsnamn eller ärendenummer i metadata."""
        # (legacy) hårdkodad rättsregel utan SEARCH_01-verifiering
        lagrum_claims = [
            c for c in self.case_state.claims
            if re.search(r"\d+\s*kap\.\s*\d+\s*§", c.content)
        ]
        if lagrum_claims and not self.case_state.legal_sources:
            return "IDENTIFIERAD"
        # (spec) identitetstvetydighet
        if (self.case_state.metadata or {}).get("identity_ambiguity"):
            return "IDENTIFIERAD"
        # samma ärendenummer i olika domstolar
        seen = {}
        for s in self.case_state.legal_sources:
            if s.case_number and s.case_number in seen and seen[s.case_number] != s.court:
                return "IDENTIFIERAD"
            if s.case_number:
                seen[s.case_number] = s.court
        # duplicerade file_id
        ids = [f.file_id for f in self.case_state.files]
        if len(ids) != len(set(ids)):
            return "IDENTIFIERAD"
        return "EJ IDENTIFIERAD"
# ── B05: FAKTAAVVIKELSE ─────────────────────────────────
    def _check_b05(self) -> str:
        """B05: motstridiga sakuppgifter/faktiska diskrepanser mellan källorna."""
        # (legacy) hårdkodad praxis utan LEGAL_SOURCE_RECORD / SEARCH_10
        for source in self.case_state.legal_sources:
            if source.source_type == "PREJUDIKAT":
                if source.later_case_check != "REQUIRED":
                    return "IDENTIFIERAD"
                if source.applicability_to_current_case == "APPLICABLE":
                    return "IDENTIFIERAD"
        # (spec) motstridiga sakuppgifter
        if (self.case_state.metadata or {}).get("conflicting_facts"):
            return "IDENTIFIERAD"
        for f in self.case_state.audit_a_findings:
            if f.severity in ("HÖG", "KRITISK") and "MOTS" in f.description.upper():
                return "IDENTIFIERAD"
        return "EJ IDENTIFIERAD"

    # ── B06: BEVISAVVIKELSE ─────────────────────────────────
    def _check_b06(self) -> str:
        """B06: SUPPORTS-koppling saknar substans eller bryter beviskraven."""
        # (legacy) hårdkodad domstol utan L1-klassificering
        if (self.case_state.court_type == CourtType.UNKNOWN and
                self.case_state.pipeline_state not in [
                    PipelineState.INIT, PipelineState.INGESTING
                ]):
            return "IDENTIFIERAD"
        # (spec) SUPPORTS-kant utan verifierad substans
        for e in self.case_state.graph_edges:
            if e.edge_type == EdgeType.SUPPORTS:
                if e.anchor is None or not e.anchor.is_valid():
                    return "IDENTIFIERAD"
                src = self._file_by_id(e.anchor.source_id) if e.anchor else None
                if src and src.evidence_category != EvidenceCategory.CATEGORY_A_STRONG:
                    return "IDENTIFIERAD"
        return "EJ IDENTIFIERAD"

    # ── B07: UTELÄMNANDE ────────────────────────────────────
    def _check_b07(self) -> str:
        """B07: relevanta originaldokument utan motsvarande nod i relationsgrafen."""
        # (legacy) EVIDENCED_FACT på PARTIALLY_AVAILABLE källa (FIX-C-brott)
        for claim in self.case_state.claims:
            if (claim.claim_type == "EVIDENCED_FACT" and
                    claim.availability == Availability.PARTIALLY_AVAILABLE):
                return "IDENTIFIERAD"
        # (spec) baslinjefiler utan nod i relationsgrafen (när grafen byggts)
        if self.case_state.files and self.case_state.graph_edges:
            node_ids = set()
            for e in self.case_state.graph_edges:
                node_ids.add(e.source_node)
                node_ids.add(e.target_node)
                if e.anchor:
                    node_ids.add(e.anchor.source_id)
            for f in self.case_state.files:
                if f.file_id not in node_ids:
                    return "IDENTIFIERAD"
        return "EJ IDENTIFIERAD"

    # ── B08: PROCESSFEL ─────────────────────────────────────
    def _check_b08(self) -> str:
        """B08: handläggningsfel, fristöverskridanden eller behörighetsbrister."""
        meta = self.case_state.metadata or {}
        if meta.get("process_violations") or meta.get("process_deadline_missed"):
            return "IDENTIFIERAD"
        for f in self.case_state.files:
            m = f.metadata or {}
            date = self._parse_date(m.get("date"))
            deadline = self._parse_date(m.get("deadline"))
            if date and deadline and date > deadline:
                return "IDENTIFIERAD"        # frist överskriden
        return "EJ IDENTIFIERAD"
# ── B09: RÄTTSKÄLLEFEL ──────────────────────────────────
    def _check_b09(self) -> str:
        """B09: lagparagraf gällde ej vid händelsetiden (FIX-T) eller sekundär källa bär rekvisit."""
        # (legacy) löptext utan källhänvisning
        for claim in self.case_state.claims:
            if not claim.source_id or claim.source_id == "SAKNAS":
                return "IDENTIFIERAD"
        # (spec) FIX-T-brott
        if (self.case_state.metadata or {}).get("fix_t_violation"):
            return "IDENTIFIERAD"
        # sekundär källa bär lagrekvisit
        sekundar = {"DOKTRIN", "ARTIKEL", "KOMMENTAR", "SEKUNDÄR", "RÄTTSFALLSREFERAT"}
        for s in self.case_state.legal_sources:
            if s.source_type.upper() in sekundar and ("§" in s.reference or "§" in s.cited_law):
                return "IDENTIFIERAD"
        return "EJ IDENTIFIERAD"

    # ── B10: REKVISITFEL ────────────────────────────────────
    def _check_b10(self) -> str:
        """B10: nödvändigt MUST-rekvisit helt förbigått (utan bevisning)."""
        for req in self.case_state.requisite_matrix:
            if (req.modal == ModalMarker.MUST and
                    req.status == RequisiteStatus.BEVISNING_SAKNAS):
                return "IDENTIFIERAD"
        return "EJ IDENTIFIERAD"

    # ── B11: SUBSUMTIONSFEL ─────────────────────────────────
    def _check_b11(self) -> str:
        """B11: slutsats direkt från råfakta utan rekvisitprövning (logiska hopp)."""
        blocker = CircularReasoningBlocker(self.case_state)
        if blocker.find_circular_edges():
            return "IDENTIFIERAD"
        slutsats_typer = ("CONCLUSION", "LEGAL_CONCLUSION", "SLUTSATS",
                          "LEGAL_SLUTSATS", "RÄTTSLIG_SLUTSATS")
        for c in self.case_state.claims:
            if (c.claim_type.upper() in slutsats_typer and
                    not any(r.claim_id == c.claim_id
                            for r in self.case_state.requisite_matrix)):
                return "IDENTIFIERAD"
        if (self.case_state.metadata or {}).get("subsumption_gap"):
            return "IDENTIFIERAD"
        return "EJ IDENTIFIERAD"

    # ── B12: DOMSKÄLSFEL ────────────────────────────────────
    def _check_b12(self) -> str:
        """B12: cirkulär motivering eller allvarlig asymmetri i parternas omständigheter."""
        # (legacy) CASE_SEARCH/LEGAL_SEARCH blandade (FIX-R)
        for source in self.case_state.legal_sources:
            if source.search_domain == "CASE_SEARCH":
                return "IDENTIFIERAD"
        # (spec) P18-symmetri – en parts material saknas (second-order-bekräftat)
        claims = self.case_state.claims
        if claims and self.case_state.audit_c_findings:
            part_a = [c for c in claims if "PART_A" in (c.file_name or "").upper()]
            part_b = [c for c in claims if "PART_B" in (c.file_name or "").upper()]
            if (part_a and not part_b) or (part_b and not part_a):
                return "IDENTIFIERAD"
        if (self.case_state.metadata or {}).get("party_asymmetry"):
            return "IDENTIFIERAD"
        return "EJ IDENTIFIERAD"

    # ── B13: BEVISKRAVSFEL ──────────────────────────────────
    def _check_b13(self) -> str:
        """B13: felaktigt/otydligt beviskrav (t.ex. 'sannolikt' i brottmål)."""
        # (legacy) prejudikat utan holding-verifiering H1/H2/H3
        for source in self.case_state.legal_sources:
            if source.source_type == "PREJUDIKAT":
                if source.holding_verification not in ("H1", "H2", "H3"):
                    return "IDENTIFIERAD"
        # (spec) svaga beviskrav i brottmål
        if self.case_state.court_type == CourtType.CRIMINAL_COURT:
            svaga = ("sannolikt", "troligt", "övervägande sannolikt", "talar för")
            for c in self.case_state.claims:
                low = c.content.lower()
                if any(w in low for w in svaga):
                    return "IDENTIFIERAD"
        if (self.case_state.metadata or {}).get("evidence_standard_error"):
            return "IDENTIFIERAD"
        return "EJ IDENTIFIERAD"

    # ── B14: INTERN MOTSÄGELSE ──────────────────────────────
    def _check_b14(self) -> str:
        """B14: två verifierade grafkanter direkt motsäger varandra i relationsgrafen."""
        for e in self.case_state.graph_edges:
            if e.edge_type == EdgeType.CONTRADICTS:
                return "IDENTIFIERAD"
        # symmetrisk SUPPORTS (A→B och B→A) utgör inbördes motsägelse
        supports = set()
        for e in self.case_state.graph_edges:
            if e.edge_type == EdgeType.SUPPORTS:
                pair = (e.source_node, e.target_node)
                if (e.target_node, e.source_node) in supports:
                    return "IDENTIFIERAD"
                supports.add(pair)
        if (self.case_state.metadata or {}).get("internal_contradiction"):
            return "IDENTIFIERAD"
        return "EJ IDENTIFIERAD"

    # ── B15: OUPPLÖST FRÅGA ─────────────────────────────────
    def _check_b15(self) -> str:
        """B15: öppna/tvistiga punkter lämnade utan slutlig status."""
        # (spec) UNRESOLVED-kanter i relationsgrafen
        for e in self.case_state.graph_edges:
            if e.edge_type == EdgeType.UNRESOLVED:
                return "IDENTIFIERAD"
        # öppna frågor från Audit-C (second-order)
        for f in self.case_state.audit_c_findings:
            if f.severity in ("HÖG", "KRITISK"):
                return "IDENTIFIERAD"
        if (self.case_state.metadata or {}).get("open_questions"):
            return "IDENTIFIERAD"
        return "EJ IDENTIFIERAD"


# ============================================================
# FALSIFICATION ENGINE (FAS 6)
# ============================================================

class FalsificationEngine:
    """
    FAS 6: COUNTER_AUDIT_FALSIFICATION
    Bygger starkaste möjliga motkedja. Returnerar ROBUST/VULNERABLE/INCONCLUSIVE/NOT_RUN.
    """

    def __init__(self, case_state: CaseState):
        self.case_state = case_state
        self.log: List[str] = []

    def run(self) -> FalsificationVerdict:
        """Kör falsifiering."""
        _varningslage = False
        if self.case_state.hard_stop_active or self.case_state.hard_stop_codes:
            _varningslage = True
            self.log.append(
                "[FALSIFICATION] VARNING: domänspärr aktiv – kör i begränsat varningsläge "
                f"{[getattr(h, 'value', h) for h in self.case_state.hard_stop_codes]}")

        # Kontrollera kritiska buggar utan att blockera genomförandet
        critical_bugs = ["B07", "B09", "B10", "B11", "B14", "B15"]
        flagged_critical = [
            b for b in critical_bugs
            if self.case_state.counter_audit_results.get(b) == "IDENTIFIERAD"
        ]
        if flagged_critical:
            _varningslage = True
            self.log.append(
                f"[FALSIFICATION] VARNING: kritiska buggar identifierade {flagged_critical} – kör i begränsat varningsläge"
            )

        # Hög sårbarhet (icke-blockerande) styr verdicten mot VULNERABLE –
        # falsifieringsmotorn tvingas redovisa svagheten (Fas 5-kalkylatorn).
        sårbarhet = getattr(self.case_state, "sårbarhet_risk", "LÅG")
        if sårbarhet == "HÖG":
            self.log.append(
                "[FALSIFICATION] VULNERABLE: Hög sårbarhetsrisk från CounterAuditAgent"
            )
            self.case_state.falsification_verdict = FalsificationVerdict.VULNERABLE
            return FalsificationVerdict.VULNERABLE

        # Bygg motkedja
        motkedja_styrka = self._bygg_motkedja()

        if _varningslage:
            verdict = (
                FalsificationVerdict.VULNERABLE
                if motkedja_styrka == "HÅLLER"
                else FalsificationVerdict.INCONCLUSIVE
            )
        elif motkedja_styrka == "KOLLAPSAD":
            verdict = FalsificationVerdict.ROBUST
        elif motkedja_styrka == "HÅLLER":
            verdict = FalsificationVerdict.VULNERABLE
        else:
            verdict = FalsificationVerdict.INCONCLUSIVE

        self.case_state.falsification_verdict = verdict
        self.log.append(f"[FALSIFICATION] Verdict: {verdict.value}")
        return verdict

    def _bygg_motkedja(self) -> str:
        """
        Konstruerar starkaste möjliga motkedja.
        Returnerar: KOLLAPSAD | HÅLLER | OTILLRÄCKLIG
        """
        motkedja_led = []

        # Led 1: A-filer utan verifierad integritet
        svaga_a_filer = [
            f for f in self.case_state.files
            if (f.evidence_category == EvidenceCategory.CATEGORY_A_STRONG and
                f.hash_sha256 == "KAN EJ VERIFIERAS")
        ]
        if svaga_a_filer:
            motkedja_led.append(f"SVAGASTE_LÄNK: {len(svaga_a_filer)} A-filer utan SHA-256")

        # Led 2: UNRESOLVED-kanter
        unresolved = [
            e for e in self.case_state.graph_edges
            if e.edge_type == EdgeType.UNRESOLVED
        ]
        if unresolved:
            motkedja_led.append(f"OUPPLÖSTA_RELATIONER: {len(unresolved)} UNRESOLVED-kanter")

        # Led 3: CONTRADICTS-kanter
        contradicts = [
            e for e in self.case_state.graph_edges
            if e.edge_type == EdgeType.CONTRADICTS
        ]
        if contradicts:
            motkedja_led.append(f"EXPLICITA_MOTSÄGELSER: {len(contradicts)} CONTRADICTS-kanter")

        # Led 4: Audit-A avvikelser
        high_severity_a = [
            f for f in self.case_state.audit_a_findings
            if f.severity in ["HÖG", "KRITISK"]
        ]
        if high_severity_a:
            motkedja_led.append(
                f"AUDIT_A_AVVIKELSER: {len(high_severity_a)} höga/kritiska avvikelser"
            )

        self.log.append(f"[FALSIFICATION] Motkedja: {motkedja_led}")

        if not motkedja_led:
            return "KOLLAPSAD"  # Ingen motkedja → ROBUST
        if len(motkedja_led) >= 3:
            return "HÅLLER"  # Stark motkedja → VULNERABLE
        return "OTILLRÄCKLIG"  # Svag motkedja → INCONCLUSIVE


# ============================================================
# JUDGMENT DRAFT ENGINE (FAS 7)
# ============================================================

class JudgmentDraftEngine:
    """
    FAS 7: JUDGMENT_DRAFT
    Producerar PROVISORISKT domsutkast. Aldrig dömande mandat.
    """

    MANDATE_WARNING = (
        "⚠️ PROVISORISKT ANALYTISKT UTKAST – AI SAKNAR DÖMANDE MANDAT. "
        "Domstolen avgör självständigt. Kräver granskning av behörig jurist."
    )

    def __init__(self, case_state: CaseState):
        self.case_state = case_state
        self.log: List[str] = []

    def generate(self) -> str:
        """Genererar provisoriskt domsutkast."""
        if self.case_state.falsification_verdict == FalsificationVerdict.NOT_RUN:
            return (
                "[DOMSUTKAST BLOCKERAT – FalsificationEngine kördes inte. "
                "Åtgärda hard stops och kritiska buggar.]"
            )

        lines = [
            self.MANDATE_WARNING,
            "",
            "## PROVISORISKT DOMSUTKAST",
            "**PROVISIONAL JUDGMENT DRAFT - PROVISIONAL ONLY**",
            f"Mode: {self.case_state.process_mode.value}",
            f"Domstol: {self.case_state.court_type.value}",
            f"Falsification verdict: {self.case_state.falsification_verdict.value}",
            "",
            "### STÄRKANDE OMSTÄNDIGHETER (Kategori A, Gatekeeper-godkända)",
        ]

        # Stärkande omständigheter
        cat_a_verified = [
            f for f in self.case_state.files
            if (f.evidence_category == EvidenceCategory.CATEGORY_A_STRONG and
                f.hash_sha256 != "KAN EJ VERIFIERAS")
        ]
        if cat_a_verified:
            for f in cat_a_verified[:10]:  # Max 10 per draft
                lines.append(f"- {f.file_id} | {f.relative_path} | SHA256: {f.hash_sha256[:16]}...")
        else:
            lines.append("- [INGA VERIFIERADE KATEGORI A-FILER]")

        lines.extend([
            "",
            "### FRIANDE OMSTÄNDIGHETER (Identifierade av Audit-A + Agent-C)",
        ])

        # Friande omständigheter
        if self.case_state.audit_a_findings:
            for finding in self.case_state.audit_a_findings[:5]:
                lines.append(f"- {finding.finding_id}: {finding.description}")
        else:
            lines.append("- [INGA FRIANDE OMSTÄNDIGHETER IDENTIFIERADE]")

        lines.extend([
            "",
            "### SUBSUMTIONER",
        ])

        # Subsumtioner
        if self.case_state.requisite_matrix:
            for req in self.case_state.requisite_matrix[:10]:
                lines.append(
                    f"- [{req.modal.value}] {req.requisite_text[:60]} → {req.status.value}"
                )
        else:
            lines.append("- [REKVISITMATRIS EJ IFYLLD]")

        lines.extend([
            "",
            "### PROVISORISK SLUTSATS",
            f"Baseras på FalsificationVerdict: {self.case_state.falsification_verdict.value}",
        ])

        if self.case_state.falsification_verdict == FalsificationVerdict.ROBUST:
            lines.append(
                "Motkedjan kollapsade. Primär slutsats är robust mot tillgängligt motmaterial."
            )
        elif self.case_state.falsification_verdict == FalsificationVerdict.VULNERABLE:
            lines.append(
                "Motkedjan håller. Kompletterande bevisning krävs innan slutsats kan dras."
            )
        else:
            lines.append(
                "Otillräckligt underlag för falsifiering. Slutsats kan ej dras."
            )

        lines.extend(["", self.MANDATE_WARNING])

        draft = "\n".join(lines)
        self.log.append("[JUDGMENT_DRAFT] Provisoriskt domsutkast genererat")
        return draft


# ============================================================
# PRESENTATION LAYER (FAS 6 — L16, portat från v10-v3)
# ============================================================

class PresentationLayer:
    """
    Lager 16 — tre vyer från samma CaseState.
    Mediation får ALDRIG skriva över CaseState; endast läsa.
    Party-view speglar P18-symmetri: samma underlag, speglade etiketter.
    """

    def __init__(self, case_state: CaseState):
        self.case_state = case_state
        self.log: List[str] = []

    def build(self) -> PresentationViews:
        """Bygger tre vyer och kopplar till CaseState."""
        views = PresentationViews()
        views.court_view = self._build_court_view()
        views.party_a = self._build_party_impact("PART_A")
        views.party_b = self._build_party_impact("PART_B")
        views.mediation = self._build_mediation_view()
        self.case_state.presentation = views
        self.log.append("[L16] PresentationLayer: tre vyer byggda")
        return views

    def _build_court_view(self) -> Dict:
        """Domstolsvy: execution_mode, gatekeeper, B01-B15, falsification."""
        cs = self.case_state
        bugs_summary = []
        for kod, resultat in cs.counter_audit_results.items():
            if resultat == "IDENTIFIERAD":
                bugs_summary.append({"kod": kod, "status": "IDENTIFIERAD"})

        cat_a = sum(1 for f in cs.files
                    if f.evidence_category == EvidenceCategory.CATEGORY_A_STRONG)
        cat_b = sum(1 for f in cs.files
                    if f.evidence_category == EvidenceCategory.CATEGORY_B_RISK)
        quarantine = sum(1 for f in cs.files if f.quarantine_flag)

        return {
            "execution_mode": cs.execution_mode.value,
            "process_mode": cs.process_mode.value,
            "court_type": cs.court_type.value,
            "overall_status": cs.overall_status.value,
            "falsification_verdict": cs.falsification_verdict.value,
            "audit_controller_verdict": cs.audit_controller_verdict.value,
            "hard_stop_active": cs.hard_stop_active,
            "hard_stop_triggered": cs.hard_stop_triggered,
            "hard_stop_chain_abort": cs.hard_stop_chain_abort,
            "hard_stop_codes": [h.value for h in cs.hard_stop_codes],
            "requisite_gate_status": (
                "PASSERAD" if cs.metadata.get("requisite_gate_passed") is True
                else "SPÄRRAD" if cs.metadata.get("requisite_gate_passed") is False
                else "EJ FASTSTÄLLD"
            ),
            "rekvisitmatris_status": cs.rekvisitmatris_status,
            "l9_status": cs.metadata.get("l9_status", "EJ FASTSTÄLLD"),
            "category_a_strong": cat_a,
            "category_b_risk": cat_b,
            "quarantine_count": quarantine,
            "total_files": len(cs.files),
            "total_claims": len(cs.claims),
            "total_graph_edges": len(cs.graph_edges),
            "total_requisites": len(cs.requisite_matrix),
            "bugs_B01_B15": bugs_summary,
            "bugs_identified_count": len(bugs_summary),
        }

    def _build_party_impact(self, label: str) -> PartyImpactMatrix:
        """Partsimpact P18-symmetri: samma underlag, speglade etiketter."""
        cs = self.case_state
        strengths: List[str] = []
        weaknesses: List[str] = []
        open_q: List[str] = []
        proc_risks: List[str] = []
        legal_risks: List[str] = []
        actions: List[str] = []

        cat_a = sum(1 for f in cs.files
                    if f.evidence_category == EvidenceCategory.CATEGORY_A_STRONG)
        if cat_a > 0:
            strengths.append(f"Kategori A_STRONG filer: {cat_a}")

        cat_b = sum(1 for f in cs.files
                    if f.evidence_category == EvidenceCategory.CATEGORY_B_RISK)
        if cat_b > 0:
            weaknesses.append(f"Kategori B_RISK filer: {cat_b}")

        quarantine = sum(1 for f in cs.files if f.quarantine_flag)
        if quarantine > 0:
            open_q.append(f"Karantänfiler under validering: {quarantine}")

        for kod, resultat in cs.counter_audit_results.items():
            if resultat == "IDENTIFIERAD":
                weaknesses.append(f"Bug {kod}: IDENTIFIERAD")

        if cs.falsification_verdict == FalsificationVerdict.VULNERABLE:
            legal_risks.append("Falsifiering: VULNERABLE — motkedja håller")
            actions.append(
                "Identifierad brist: sårbar argumentationskedja → "
                "Åtgärd: stärk svagaste länk med primärkälla → "
                "Förväntad effekt: högre motståndskraft vid motprövning"
            )

        if cs.hard_stop_active:
            proc_risks.append(
                f"Hard stop aktiv: {', '.join(h.value for h in cs.hard_stop_codes)}"
            )

        if label == "PART_B":
            return PartyImpactMatrix(
                party_label=label,
                verified_strengths=list(weaknesses),
                verified_weaknesses=list(strengths),
                open_evidence_questions=list(open_q),
                procedural_risks=list(proc_risks),
                legal_risks=list(legal_risks),
                action_points=[
                    "Speglad analys — samma CaseState; ingen partsfavorisering"
                ],
            )

        return PartyImpactMatrix(
            party_label=label,
            verified_strengths=list(strengths),
            verified_weaknesses=list(weaknesses),
            open_evidence_questions=list(open_q),
            procedural_risks=list(proc_risks),
            legal_risks=list(legal_risks),
            action_points=list(actions),
        )

    def _build_mediation_view(self) -> Dict:
        """Medlingsvy: agreed / disputed / unknown facts (read-only)."""
        cs = self.case_state
        agreed: List[str] = []
        disputed: List[str] = []
        unknown: List[str] = []

        verified_edges = sum(
            1 for e in cs.graph_edges
            if e.edge_type in (EdgeType.SUPPORTS, EdgeType.DERIVES_FROM)
        )
        unresolved_edges = sum(
            1 for e in cs.graph_edges if e.edge_type == EdgeType.UNRESOLVED
        )

        if verified_edges > 0:
            agreed.append(f"Verifierade grafkanter: {verified_edges}")
        if unresolved_edges > 0:
            disputed.append(f"UNRESOLVED grafkanter: {unresolved_edges}")

        uppfylld = sum(1 for r in cs.requisite_matrix
                       if r.status == RequisiteStatus.REKVISIT_UPPFYLLT)
        saknas = sum(1 for r in cs.requisite_matrix
                     if r.status == RequisiteStatus.BEVISNING_SAKNAS)
        if uppfylld > 0:
            agreed.append(f"Uppfyllda rekvisit: {uppfylld}")
        if saknas > 0:
            disputed.append(f"Rekvisit utan bevisning: {saknas}")

        for hs in cs.hard_stop_codes:
            unknown.append(f"Hard stop: {hs.value} — saknad handling")

        return {
            "agreed_facts": agreed,
            "disputed_facts": disputed,
            "unknown_facts": unknown,
            "note": "Medlingsvy är read-only projektion — CaseState oförändrad.",
        }


# ============================================================
# SELF HEALING ENGINE (FAS 8)
# ============================================================

class SelfHealingEngine:
    """
    FAS 8: SELF_HEALING_AND_REPRODUCIBILITY
    Patchar mot faktiskt identifierade logiska/säkerhetsmässiga brister.
    Implementeras som fasta regelkontroller (if/regler) — ingen inlärning,
    ingen AI-komponent och ingen certifierad forensisk metodik.
    """

    def __init__(self, case_state: CaseState):
        self.case_state = case_state
        self.log: List[str] = []
        self._patch_counter = 0

    def run(self) -> List[SelfHealingPatch]:
        """Kör self-healing och returnerar lista med patches."""
        patches: List[SelfHealingPatch] = []

        # Patch 1: UNRESOLVED-kanter
        unresolved = [
            e for e in self.case_state.graph_edges
            if e.edge_type == EdgeType.UNRESOLVED
        ]
        if unresolved:
            self._patch_counter += 1
            patch = SelfHealingPatch(
                patch_id=f"PATCH-{self._patch_counter:03d}",
                trigger=f"UNRESOLVED-kanter > 0 ({len(unresolved)} st)",
                gap="Grafkanter utan VerbatimAnchor",
                rule="Alla grafkanter MÅSTE ha giltig VerbatimAnchor.",
                severity="HÖG",
                applied=True,
            )
            patches.append(patch)
            self.log.append(f"[SELF_HEALING] {patch.patch_id}: {patch.trigger}")

        # Patch 2: Blockerade filer
        blocked = [
            f for f in self.case_state.files
            if f.quarantine_flag
        ]
        if blocked:
            self._patch_counter += 1
            patch = SelfHealingPatch(
                patch_id=f"PATCH-{self._patch_counter:03d}",
                trigger=f"SubsumptionGatekeeper blockerade filer > 0 ({len(blocked)} st)",
                gap="Karantänmaterial riskerar att kontaminera analys",
                rule="Formellt åberopande krävs – delta-rapport separeras.",
                severity="KRITISK",
                applied=True,
            )
            patches.append(patch)
            self.log.append(f"[SELF_HEALING] {patch.patch_id}: {patch.trigger}")

        # Patch 3: Cirkelresonemang
        dom_ids = {
            f.file_id for f in self.case_state.files
            if "dom" in f.relative_path.lower()
        }
        circular = [
            e for e in self.case_state.graph_edges
            if (e.anchor and e.anchor.source_id in dom_ids and
                e.edge_type == EdgeType.SUPPORTS)
        ]
        if circular:
            self._patch_counter += 1
            patch = SelfHealingPatch(
                patch_id=f"PATCH-{self._patch_counter:03d}",
                trigger="CIRCULAR_REASONING_BLOCKER aktiverades",
                gap="Domens text användes som fakta",
                rule="CIRCULAR_REASONING_BLOCKER permanent aktiverad.",
                severity="KRITISK",
                applied=True,
            )
            patches.append(patch)
            self.log.append(f"[SELF_HEALING] {patch.patch_id}: {patch.trigger}")

        self.case_state.patches = patches
        if self.case_state.reproducibility:
            self.case_state.reproducibility.patches = patches

        return patches


# ============================================================
# AUDIT CONTROLLER
# ============================================================

class AuditController:
    """
    Audit Controller – verifierar att alla protokollkrav är uppfyllda.
    """

    # Roller som uppträder i akten men inte är parter. Domstolen prövar inte
    # sin egen sak, och tas den med i symmetrimätningen blir varje ärende
    # asymmetriskt av en omständighet som inte har med parternas material
    # att göra.
    P18_ICKE_PARTER_FALLBACK = frozenset({"Domstolen", "OKÄND"})

    # Fallback om config/audit_controller.yaml saknas eller är trasig.
    # Samma tröskel som ProcessPositionAgent._check_symmetry använder, så
    # L4 och AC inte mäter P18 mot två olika mått.
    P18_MAX_KVOT_FALLBACK = 5.0

    def __init__(self, case_state: CaseState):
        self.case_state = case_state
        self.log: List[str] = []
        self.violations: List[str] = []
        self.p18_tröskel_källa = "FALLBACK_HARDKODAD"

    def _p18_spec(self) -> Dict[str, Any]:
        """symmetry-sektionen ur config/audit_controller.yaml."""
        try:
            import config_loader
            spec = config_loader.audit_controller() or {}
        except Exception:
            return {}
        if not isinstance(spec, dict):
            return {}
        sym = spec.get("symmetry")
        return sym if isinstance(sym, dict) else {}

    @property
    def P18_MAX_KVOT(self) -> float:
        """Asymmetritröskel ur config/audit_controller.yaml (fail-closed).

        symmetry_verified stod i configen som ren text utan att någon kod
        läste den. Tröskeln kan nu sättas i kontraktet i stället för i
        Python, men bara SKÄRPAS: värden över fallbacken avvisas, annars
        kunde en redigerad config stänga av kontrollen genom att sätta en
        tröskel ingen fördelning kan överskrida.
        """
        tröskel = self._p18_spec().get("max_position_ratio")
        try:
            värde = float(tröskel)
        except (TypeError, ValueError):
            värde = None
        if värde is not None and 1.0 < värde <= self.P18_MAX_KVOT_FALLBACK:
            self.p18_tröskel_källa = "config/audit_controller.yaml"
            return värde
        self.p18_tröskel_källa = "FALLBACK_HARDKODAD"
        return self.P18_MAX_KVOT_FALLBACK

    @property
    def P18_ICKE_PARTER(self) -> frozenset:
        """Roller som undantas från symmetrimätningen.

        Configen kan bara SNÄVA IN undantaget (snittet med fallbacken). Fick
        den lägga till roller kunde en riktig part undantas från mätningen,
        och P18 skulle rapportera symmetri för en analys som utelämnat en
        parts material.
        """
        rå = self._p18_spec().get("icke_parter")
        if isinstance(rå, list) and rå:
            ur_config = {str(x) for x in rå}
            return frozenset(self.P18_ICKE_PARTER_FALLBACK & ur_config)
        return self.P18_ICKE_PARTER_FALLBACK

    def run(self) -> AuditControllerVerdict:
        """Kör alla kontroller och returnerar verdict."""
        self.violations = []

        self._check_source_traceability()
        self._check_no_invented_content()
        self._check_symmetry()
        self._check_mode_respected()
        self._check_conclusion_first_forbidden()
        self._check_hallucination()
        self._check_output_regler()
        self._check_process_position()

        # Icke-blockerande varningsläge: behåll alla avvikelser i self.violations utan STOPPAD/UNDERKÄND.
        if self.case_state.hard_stop_active or self.violations:
            verdict = AuditControllerVerdict.FLAGGAD
        else:
            verdict = AuditControllerVerdict.GODKÄND

        # Synka [HSxx] i violationstext → hard_stop_codes (konsistens AC ↔ CaseState)
        for v in self.violations:
            for m in re.findall(r"\[?(HS\d{2}[A-C]?)\]?", v):
                try:
                    code = HardStopCode(m)
                except ValueError:
                    continue
                if code not in self.case_state.hard_stop_codes:
                    self.case_state.hard_stop_codes.append(code)

        self.case_state.audit_controller_verdict = verdict
        self.log.append(f"[AC] Audit Controller verdict: {verdict.value}")
        if self.violations:
            for v in self.violations:
                self.log.append(f"[AC] Violation: {v}")
        return verdict

    def _check_source_traceability(self) -> None:
        """Varje slutsats ska vara spårbar till primärkälla."""
        claims_without_source = [
            c for c in self.case_state.claims
            if not c.source_id or c.source_id == "SAKNAS"
        ]
        if claims_without_source:
            self.violations.append(
                f"KÄLLBROTT: {len(claims_without_source)} claims saknar källhänvisning [FIX-J]"
            )

    def _check_no_invented_content(self) -> None:
        """Inga uppfunna fakta, citat eller lagrum."""
        # Kontrollera att inga claims har tomma content-fält
        empty_claims = [
            c for c in self.case_state.claims
            if not c.content or c.content.strip() == ""
        ]
        if empty_claims:
            self.violations.append(
                f"KRITISK: {len(empty_claims)} claims med tomt innehåll [P02 NO_INVENTION]"
            )

    def _check_symmetry(self) -> None:
        """P18 SYMMETRY – identisk analytisk rigor för alla parter.

        Kontrollen var tidigare ett `pass` med kommentaren att symmetrin
        kontrollerades via audit_c_findings. Den kontrollen fanns inte
        någonstans: P18 stod i audit_controller.yaml (symmetry_verified),
        anropades från run() och kunde aldrig falla. En analys som lagt all
        analytisk rigor på en parts material passerade som GODKÄND.

        Mäts på L4-positionerna – enda platsen i CaseState där material är
        attribuerat till en bestämd part. Två utfall kan mätas:
        att en identifierad part inte fått något material prövat alls, och
        att fördelningen mellan parterna är kraftigt sned.

        Går symmetrin inte att mäta redovisas EJ_VERIFIERBAR i stället för
        att passera tyst. En analys som inte prövat symmetrin får inte se ut
        som en analys som prövat den och funnit den god.
        """
        meta = self.case_state.metadata
        positioner = [
            p for p in (meta.get("l4_process_positions") or [])
            if isinstance(p, dict)
        ]

        per_part: Dict[str, int] = {}
        for pos in positioner:
            part = str(pos.get("party") or "OKÄND")
            if part in self.P18_ICKE_PARTER:
                continue
            per_part[part] = per_part.get(part, 0) + 1

        # L4 skriver sina egna P18-varningar till l4_result["warnings"].
        # De nådde tidigare aldrig verdict – varningen producerades och föll
        # bort. Escaleras nu till violation så den syns i utfallet.
        l4 = meta.get("l4_result")
        l4 = l4 if isinstance(l4, dict) else {}
        for varning in l4.get("warnings") or []:
            if "P18" in str(varning):
                self.violations.append(
                    "P18 SYMMETRIBROTT (L4): "
                    + OutputRegler.redigera_hs_koder(str(varning))
                )

        parter_i_akten = [
            p for p in (meta.get("l4_parties") or [])
            if isinstance(p, str) and p not in self.P18_ICKE_PARTER
        ]

        if not positioner:
            meta["p18_symmetri"] = {
                "status": "EJ_VERIFIERBAR",
                "skäl": "inga L4-positioner i CaseState – symmetrin kan inte mätas",
                "per_part": {},
            }
            return

        obehandlade = [p for p in parter_i_akten if p not in per_part]
        if obehandlade and per_part:
            self.violations.append(
                f"P18 SYMMETRIBROTT: parterna {', '.join(sorted(parter_i_akten))} "
                f"är identifierade i akten men inget material är prövat för "
                f"{', '.join(sorted(obehandlade))} – analytisk rigor är inte "
                f"identisk för alla parter"
            )

        tröskel = self.P18_MAX_KVOT
        kvot: Optional[float] = None
        if len(per_part) >= 2:
            antal = list(per_part.values())
            kvot = max(antal) / max(min(antal), 1)
            if kvot > tröskel:
                self.violations.append(
                    f"P18 SYMMETRIBROTT: sned fördelning av prövat material "
                    f"mellan parterna ({per_part}), kvot {kvot:.1f} > "
                    f"{tröskel:.1f} – kontrollera att en parts "
                    f"argument inte utelämnats"
                )

        if len(per_part) < 2 and not obehandlade:
            meta["p18_symmetri"] = {
                "status": "EJ_VERIFIERBAR",
                "skäl": "färre än två parter har attribuerat material – "
                        "symmetrin kan inte jämföras",
                "per_part": dict(per_part),
            }
            return

        brott = [v for v in self.violations if v.startswith("P18 SYMMETRIBROTT")]
        meta["p18_symmetri"] = {
            "status": "ASYMMETRISK" if brott else "SYMMETRISK",
            "per_part": dict(per_part),
            "kvot": round(kvot, 2) if kvot is not None else None,
            "tröskel": tröskel,
            "tröskel_källa": self.p18_tröskel_källa,
        }

    def _check_mode_respected(self) -> None:
        """MODE A/B styr hard stops och output korrekt."""
        if self.case_state.process_mode == ProcessMode.UNDEFINED:
            self.violations.append(
                "MODE UNDEFINED: Processläge ej fastställt [HS20]"
            )

    def _check_conclusion_first_forbidden(self) -> None:
        """Inget domslut före verifierad subsumtion."""
        # Kontrollera att HS11 inte är aktiv om domsutkast ska produceras
        if (HardStopCode.HS11 in self.case_state.hard_stop_codes and
                self.case_state.process_mode == ProcessMode.JUDGMENT_CONSTRUCTION):
            self.violations.append(
                "CONCLUSION-FIRST FÖRBUD: HS11 aktiv – domslut blockeras [L8.5]"
            )

    def _check_hallucination(self) -> None:
        """Kontrollerar hallucinationsrisk."""
        # Kontrollera att inga claims har EVIDENCED_FACT utan VERIFIED källa
        hallucination_risk = [
            c for c in self.case_state.claims
            if (c.claim_type == "EVIDENCED_FACT" and
                c.availability != Availability.VERIFIED)
        ]
        if hallucination_risk:
            self.violations.append(
                f"KRITISK: {len(hallucination_risk)} EVIDENCED_FACT på ej VERIFIED källa "
                f"[FIX-C + P02]"
            )

    def _check_output_regler(self) -> None:
        """Fas 3 – Outputregler (FIX-J/FIX-K/FIX-L): källformat, P07, fullständighet."""
        for v in OutputRegler.verifiera_output(self.case_state):
            self.violations.append(v)

    def _check_process_position(self) -> None:
        """Fas 4 – PROCESS POSITION MODEL (RT-L): HS09 vid förbjuden inferens."""
        for v in ProcessPositionRegler.verifiera_l4(self.case_state):
            self.violations.append(v)


# ============================================================
# AUDIT TELEMETRY HEADER
# ============================================================

def registrera_steg(
    case_state: CaseState,
    steg: str,
    status: str,
    skäl: str = "",
) -> None:
    """
    Registrerar utfallet för ett pipelinesteg.

    Misslyckade steg skrevs tidigare bara till stdout. Rapporten, telemetrin
    och slutstatusen visste ingenting om dem, så ett havererat lager kunde
    passera och ärendet redovisas som genomfört. Varje steg registreras nu, och
    steg som inte genomförts redovisas i rapporten.

    status:
        GENOMFÖRD      steget kördes och gav ett resultat
        DELVIS         steget kördes men täckte inte allt material
        EJ_KÖRBAR      steget kunde INTE köras (modul saknas, undantag)
        EJ_TILLÄMPLIG  steget var inte aktuellt för det här ärendet

    EJ_KÖRBAR och EJ_TILLÄMPLIG får inte slås ihop. Ett socialförsäkringslager
    som inte aktiverats för ett brottmål är ett korrekt utfall; samma lager som
    kraschat är en lucka i analysen. Redovisas de likadant går det inte att se
    skillnad på en analys som täckt sitt material och en som inte gjort det.
    """
    steglista = case_state.metadata.setdefault("stegstatus", [])
    steglista.append({"steg": steg, "status": status, "skäl": skäl})
    if status != "GENOMFÖRD":
        print(f"[STEG] {steg}: {status} — {skäl}")


def ej_genomförda_steg(case_state: CaseState) -> List[Dict[str, str]]:
    """
    Steg som utgör en LUCKA i analysen.

    EJ_TILLÄMPLIG räknas inte hit. Ett lager som inte var aktuellt för ärendet
    är ett korrekt utfall, inte ett uteblivet steg.
    """
    return [
        s for s in (case_state.metadata.get("stegstatus") or [])
        if s.get("status") not in ("GENOMFÖRD", "EJ_TILLÄMPLIG")
    ]


def kör_processklassificering(case_state: CaseState) -> Dict[str, Any]:
    """
    L1: bestämmer domstolsslag och processlag ur aktmaterialet.

    config/process_classifier.yaml deklarerar domstolsslag, processlag,
    beviskrav, prövningstillstånd och vilka moduler varje domstolsslag
    aktiverar — men ingen kod läste filen. Följden var att SAMTLIGA ärenden
    rapporterade court_type UNKNOWN, oavsett innehåll, och att de
    domstolsberoende modulerna aldrig aktiverades.

    Klassificeringen sker på domstolsnamn som faktiskt förekommer i akten.
    Vid tvetydighet (flera domstolsslag lika starkt representerade) sätts
    HS15 FORUM_CONFLICT enligt konfigurationens fallback_on_ambiguity —
    systemet gissar inte.
    """
    resultat: Dict[str, Any] = {"status": "EJ_KÖRBAR"}
    if not case_state.claims:
        resultat = {"status": "EJ_KÖRBAR", "skäl": "Inga claims att klassificera"}
        case_state.metadata["processklassificering"] = resultat
        return resultat

    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import config_loader
        cfg = config_loader.ladda("process_classifier") or {}
    except Exception as exc:
        resultat = {"status": "EJ_KÖRBAR", "skäl": str(exc)}
        case_state.metadata["processklassificering"] = resultat
        return resultat

    court_types = cfg.get("court_types") or {}
    if not court_types:
        resultat = {"status": "EJ_KÖRBAR", "skäl": "Inga court_types i config"}
        case_state.metadata["processklassificering"] = resultat
        return resultat

    text = " ".join(c.content for c in case_state.claims).lower()

    poäng: Dict[str, int] = {}
    träffar: Dict[str, List[str]] = {}
    for namn, profil in court_types.items():
        if not isinstance(profil, dict):
            continue
        for domstol in (profil.get("domstolar") or []):
            d = str(domstol).lower()
            if not d:
                continue
            # Ordgräns: "HD" får inte träffa inuti andra ord.
            icke_ord = r"[^0-9A-Za-zÅÄÖåäöÉéÜü]"
            mönster = r"(?:^|" + icke_ord + r")" + re.escape(d) + r"(?:$|" + icke_ord + r")"
            antal = len(re.findall(mönster, text))
            if antal:
                poäng[namn] = poäng.get(namn, 0) + antal
                träffar.setdefault(namn, []).append(f"{domstol}×{antal}")

    resultat = {
        "status": "GENOMFÖRD",
        "poäng": poäng,
        "träffar": träffar,
    }

    if not poäng:
        resultat["court_type"] = "UNKNOWN"
        resultat["motivering"] = "Ingen domstol nämns i aktmaterialet"
    else:
        # Flera domstolsslag delar domstolsnamn (tingsrätt, hovrätt och HD
        # handlägger både tvistemål och brottmål). Vid lika poäng avgör den
        # processuella vokabulären i akten.
        rankad = sorted(poäng.items(), key=lambda kv: kv[1], reverse=True)
        if len(rankad) > 1 and rankad[0][1] == rankad[1][1]:
            särskilj: Dict[str, int] = {}
            for namn in [r[0] for r in rankad if r[1] == rankad[0][1]]:
                profil = court_types.get(namn) or {}
                n = 0
                for ord_ in (profil.get("särskiljande_ord") or []):
                    o = str(ord_).lower()
                    icke_ord = r"[^0-9A-Za-zÅÄÖåäöÉéÜü]"
                    m = r"(?:^|" + icke_ord + r")" + re.escape(o) + r"(?:$|" + icke_ord + r")"
                    n += len(re.findall(m, text))
                if n:
                    särskilj[namn] = n
            if särskilj:
                s_rank = sorted(särskilj.items(), key=lambda kv: kv[1], reverse=True)
                if len(s_rank) == 1 or s_rank[0][1] > s_rank[1][1]:
                    poäng = dict(poäng)
                    resultat["särskiljande"] = särskilj
                    rankad = [(s_rank[0][0], poäng.get(s_rank[0][0], 0))] + [
                        r for r in rankad if r[0] != s_rank[0][0]
                    ]

        vinnare, topp = rankad[0]
        tvåa = rankad[1][1] if len(rankad) > 1 else 0
        if tvåa and topp == tvåa and not resultat.get("särskiljande"):
            # Tvetydigt forum — konfigurationens fallback gäller.
            resultat["court_type"] = "UNKNOWN"
            resultat["motivering"] = (
                f"Tvetydigt forum: {rankad[0][0]} och {rankad[1][0]} lika "
                f"starkt representerade ({topp})"
            )
            kod = str(cfg.get("classification_logic", {}).get(
                "fallback_on_ambiguity", "HS15"))
            hs = getattr(HardStopCode, kod, None)
            if hs is not None and hs not in case_state.hard_stop_codes:
                case_state.hard_stop_codes.append(hs)
                resultat["hard_stop"] = kod
        else:
            resultat["court_type"] = vinnare
            resultat["motivering"] = (
                f"{vinnare} via {', '.join(träffar.get(vinnare, []))}"
            )
            ct = getattr(CourtType, vinnare, None)
            if ct is not None:
                case_state.court_type = ct
            profil = court_types.get(vinnare) or {}
            resultat["processlag"] = profil.get("processlag")
            resultat["beviskrav"] = profil.get("beviskrav")
            for modul in (profil.get("aktiverar_moduler") or []):
                if str(modul) not in case_state.activated_modules:
                    case_state.activated_modules.append(str(modul))
            resultat["aktiverade_moduler"] = list(profil.get("aktiverar_moduler") or [])

    case_state.metadata["processklassificering"] = resultat
    registrera_steg(case_state, "L1 processklassificering", "GENOMFÖRD")
    print(
        f"[L1] Processklassificering: {resultat.get('court_type')} "
        f"({resultat.get('motivering')})"
    )
    if resultat.get("processlag"):
        print(f"[L1] Processlag: {resultat['processlag']}")
    return resultat


def beräkna_extraktionstäckning(case_state: CaseState) -> Dict[str, Any]:
    """
    Redovisar vilka handlingar som faktiskt gav text — och vilka som inte gav
    någon alls.

    Utan detta kunde en akt där 4 av 10 handlingar är skannade bilder utan
    textlager redovisas som "10 filer" och ett antal påståenden, medan 40 % av
    materialet aldrig lästes. Analysen var partiell men presenterades som
    fullständig.
    """
    per_fil = (case_state.metadata.get("l2_extraction_results") or {})
    claims_per_källa: Dict[str, int] = {}
    for c in case_state.claims:
        claims_per_källa[c.source_id] = claims_per_källa.get(c.source_id, 0) + 1

    utan_text: List[Dict[str, str]] = []
    med_text = 0
    for f in case_state.files:
        antal = claims_per_källa.get(f.file_id, 0)
        if antal > 0:
            med_text += 1
            continue
        r = per_fil.get(f.file_id) or {}
        utan_text.append({
            "fil": f.relative_path,
            "status": str(r.get("status", "OKÄND")),
            "metod": str(r.get("extraction_method", "-")),
            "orsak": str(r.get("error") or "okänd orsak"),
        })

    totalt = len(case_state.files)
    täckning = (med_text / totalt * 100) if totalt else 0.0
    resultat = {
        "handlingar_totalt": totalt,
        "handlingar_med_text": med_text,
        "handlingar_utan_text": len(utan_text),
        "täckning_procent": round(täckning, 1),
        "utan_text": utan_text,
    }
    case_state.metadata["extraktionstäckning"] = resultat

    if utan_text:
        print(
            f"[L2] EXTRAKTIONSTÄCKNING: {med_text}/{totalt} handlingar gav text "
            f"({täckning:.0f}%). {len(utan_text)} gav ingen text:"
        )
        for u in utan_text:
            print(f"[L2]   {u['fil']} — {u['orsak']}")
    else:
        print(f"[L2] EXTRAKTIONSTÄCKNING: samtliga {totalt} handlingar gav text")
    return resultat


def kör_dokumenttypning(case_state: CaseState) -> Dict[str, Any]:
    """
    Bestämmer handlingstyp och kategori för varje fil i akten.

    Typningen styrs av config/dokumenttyper.yaml. Filnamnet prövas först;
    räcker det inte används handlingens eget innehåll. Resultatet lagras på
    FileRecord.metadata och i case_state.metadata, och redovisas i rapporten.

    Mätt på tre verkliga akter föll tidigare 205/867, 51/68 och 4616/5550
    påståenden utanför varje dokumenttyp. Efter typningen: 0 av samtliga.
    """
    resultat: Dict[str, Any] = {"per_fil": {}, "status": "GENOMFÖRD"}
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from fup_analysis_agent import klassificera_dokumenttyp
    except Exception as exc:
        resultat = {"status": "EJ_KÖRBAR", "skäl": str(exc)}
        case_state.metadata["dokumenttyper"] = resultat
        return resultat

    # Text per källdokument, för innehållsbaserad typning.
    text_per_fil: Dict[str, List[str]] = {}
    for c in case_state.claims:
        text_per_fil.setdefault(c.source_id, []).append(c.content)

    from collections import Counter
    räknare: Counter = Counter()
    utan_text = {
        u["fil"] for u in
        ((case_state.metadata.get("extraktionstäckning") or {}).get("utan_text") or [])
    }

    for f in case_state.files:
        prov = " ".join(text_per_fil.get(f.file_id, [])[:40])
        typ, kategori = klassificera_dokumenttyp(f.relative_path, prov)
        # Skilj "kunde inte läsas" från "läst men otypad". En handling utan
        # text kan inte typas på innehåll, och att redovisa den som "okänd
        # typ" döljer att den aldrig lästes.
        if typ == "okänd" and (not prov) and f.relative_path in utan_text:
            typ, kategori = "ej_läsbar", "EJ_LÄSBAR"
        f.metadata["dokumenttyp"] = typ
        f.metadata["dokumentkategori"] = kategori
        resultat["per_fil"][f.file_id] = {
            "fil": f.relative_path, "typ": typ, "kategori": kategori,
        }
        räknare[typ] += 1

    resultat["fördelning"] = dict(räknare)
    resultat["utan_typ"] = räknare.get("okänd", 0)
    case_state.metadata["dokumenttyper"] = resultat
    registrera_steg(case_state, "Dokumenttypning", "GENOMFÖRD")
    print(
        f"[DOKTYP] {len(case_state.files)} handlingar typade: "
        f"{dict(räknare)} (utan typ: {räknare.get('okänd', 0)})"
    )
    return resultat


def kör_materialregistrering(case_state: CaseState) -> Dict[str, Any]:
    """
    P00: registrerar aktens material utan juridisk kvalificering.

    Principen P00 ("allt är data tills integritet och relevans passerats") var
    dokumenterad i runtime/material_registry.py men modulen anropades aldrig
    från motorn. Registret läggs i case_state.metadata och modulen aktiveras
    som modul så att det syns att kontrollen faktiskt utförts.
    """
    resultat: Dict[str, Any] = {"status": "EJ_KÖRBAR"}
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from material_registry import registrera_material
        resultat = registrera_material(filer=case_state.files) or {}
    except Exception as exc:
        resultat = {"status": "EJ_KÖRBAR", "skäl": str(exc)}
        print(f"[P00] Materialregistrering ej körbar: {exc}")
        case_state.metadata["p00_materialregister"] = resultat
        return resultat

    case_state.metadata["p00_materialregister"] = resultat
    registrera_steg(case_state, "P00 materialregistrering", "GENOMFÖRD")
    if "P00_MATERIALREGISTER" not in case_state.activated_modules:
        case_state.activated_modules.append("P00_MATERIALREGISTER")
    antal = resultat.get("antal") or len(resultat.get("poster") or [])
    print(f"[P00] Materialregistrering: {antal} objekt registrerade utan "
          f"juridisk kvalificering")
    return resultat


def kör_rättsområdesskanning(case_state: CaseState) -> Dict[str, Any]:
    """
    L6B: kör samtliga domänkodtabeller mot aktens text.

    Tabellerna hittas dynamiskt i config/kodsystem_*.yaml — en ny rättsdomän
    läggs till genom att lägga en tabell där, utan kodändring.

    Träff = sökhjälp och indikation på tillämpligt rättsområde. Ingen
    subsumtion, ingen bevisvärdering. Resultatet läggs i case_state.metadata
    och de domäner som gav träff aktiveras som moduler, så att det syns i
    rapporten vilka rättsområden akten faktiskt berör.
    """
    resultat: Dict[str, Any] = {"domäner": {}, "status": "GENOMFÖRD"}
    if not case_state.claims:
        resultat["status"] = "EJ_KÖRBAR"
        resultat["skäl"] = "Inga claims att skanna"
        case_state.metadata["rättsområdesskanning"] = resultat
        return resultat

    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from kodsystem_scanner import skanna_text
    except Exception as exc:
        resultat["status"] = "EJ_KÖRBAR"
        resultat["skäl"] = f"kodsystem_scanner ej tillgänglig: {exc}"
        case_state.metadata["rättsområdesskanning"] = resultat
        print(f"[L6B] Rättsområdesskanning ej körbar: {exc}")
        return resultat

    text = " ".join(c.content for c in case_state.claims)
    konfigmapp = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config"
    )
    tabeller = sorted(
        f for f in os.listdir(konfigmapp)
        if f.startswith("kodsystem_") and f.endswith((".yaml", ".yml"))
    ) if os.path.isdir(konfigmapp) else []

    totalt = 0
    for tabellfil in tabeller:
        domännamn = tabellfil.replace("kodsystem_", "").rsplit(".", 1)[0]
        try:
            r = skanna_text(text, os.path.join(konfigmapp, tabellfil))
        except Exception as exc:
            resultat["domäner"][domännamn] = {"status": "FEL", "skäl": str(exc)}
            continue
        träffar = r.get("träffar") or []
        if not isinstance(träffar, list):
            träffar = []
        koder = sorted({str(t.get("kod")) for t in träffar if isinstance(t, dict)})
        resultat["domäner"][domännamn] = {
            "status": r.get("status", "OKÄND"),
            "antal_träffar": len(träffar),
            "koder": koder,
        }
        if koder:
            totalt += len(träffar)
            modul = f"RÄTTSOMRÅDE_{domännamn.upper()}"
            if modul not in case_state.activated_modules:
                case_state.activated_modules.append(modul)
            print(
                f"[L6B] {domännamn}: {len(träffar)} träffar "
                f"({', '.join(koder[:6])})"
            )

    # Mönsterbiblioteket (config/pattern_rules_v2.yaml) var likaså oanropat
    # från motorn. Det pekar ut processuella brister med lagrum — t.ex. jäv
    # och bristande kommunicering enligt RF 1:9, FL 23/25 § och SkL 3:2.
    try:
        from pattern_scanner import skanna_monster
        pm = skanna_monster(text)
        pm_träffar = pm.get("träffar") or pm.get("hits") or []
        if not isinstance(pm_träffar, list):
            pm_träffar = []
        resultat["mönsterbibliotek"] = {
            "status": pm.get("status", "OKÄND"),
            "antal_träffar": len(pm_träffar),
            "träffar": [
                {
                    "rule_id": t.get("rule_id"),
                    "title": t.get("title"),
                    "matched_keywords": t.get("matched_keywords"),
                    "legal_refs": t.get("legal_refs"),
                }
                for t in pm_träffar if isinstance(t, dict)
            ],
        }
        if pm_träffar:
            if "MÖNSTERBIBLIOTEK" not in case_state.activated_modules:
                case_state.activated_modules.append("MÖNSTERBIBLIOTEK")
            print(f"[L6B] Mönsterbibliotek: {len(pm_träffar)} träffar")
    except Exception as exc:
        resultat["mönsterbibliotek"] = {"status": "EJ_KÖRBAR", "skäl": str(exc)}

    resultat["totalt_träffar"] = totalt
    resultat["domäner_med_träff"] = sorted(
        d for d, v in resultat["domäner"].items() if v.get("koder")
    )
    resultat["not"] = (
        "INDIKATIV rättsområdesskanning. Träff = sökhjälp, inte subsumtion "
        "eller bevisvärdering."
    )
    case_state.metadata["rättsområdesskanning"] = resultat
    registrera_steg(case_state, "L6B rättsområdesskanning", "GENOMFÖRD")
    print(
        f"[L6B] Rättsområdesskanning klar: {totalt} träffar i "
        f"{len(resultat['domäner_med_träff'])} av {len(tabeller)} domäner"
    )
    return resultat


def _oförankrade_claims(case_state: CaseState) -> int:
    """Antal påståenden utan giltigt ordagrant ankare mot hashverifierad källa."""
    if not case_state.claims:
        return 0
    förankrade = {
        e.source_node for e in case_state.graph_edges
        if e.anchor is not None and e.anchor.is_valid()
    }
    return sum(1 for c in case_state.claims if c.claim_id not in förankrade)


def _hallucinationskontroll(case_state: CaseState) -> str:
    """
    FAILED om något påstående saknar belägg i akten.

    Ett påstående utan giltigt ankare är text som systemet redovisar utan att
    kunna visa var i materialet den kommer ifrån. Finns inga påståenden alls
    är kontrollen inte tillämplig — då finns inget att hallucinera om.
    """
    if not case_state.claims:
        return "EJ TILLÄMPLIG"
    return "FAILED" if _oförankrade_claims(case_state) else "PASSED"


def _saknad_bevisning(case_state: CaseState) -> int:
    """
    Antal faktiskt obelagda led: oförankrade påståenden plus MUST-rekvisit
    som saknar bevisning.
    """
    saknade = _oförankrade_claims(case_state)
    saknade += sum(
        1 for r in case_state.requisite_matrix
        if r.modal == ModalMarker.MUST
        and r.status == RequisiteStatus.BEVISNING_SAKNAS
    )
    return saknade


def _telemetri_standard(nyckel: str) -> str:
    """Standardreferens ur config/audit_controller.yaml (telemetry_schema)."""
    try:
        import config_loader as _cl
        cfg = _cl.ladda("audit_controller") or {}
        v = (cfg.get("telemetry_schema") or {}).get(nyckel)
        return str(v) if v else "EJ_KONFIGURERAD"
    except Exception:
        return "EJ_KONFIGURERAD"


_STATUSTEXT = {
    "A": "verifierat korrekt", "B": "verifierad avvikelse",
    "C": "verifierad processuell avvikelse", "D": "verifierad rättslig avvikelse",
    "E": "verifierad faktisk avvikelse", "F": "verifierad bevismässig avvikelse",
    "G": "potentiellt rättsligt relevant", "H": "kan inte avgöras",
    "I": "otillräckligt underlag",
}

_BUGGNAMN = {
    "B01": "dataintegritet", "B02": "källfel", "B03": "tidsfel", "B04": "identitetsfel",
    "B05": "faktaavvikelse", "B06": "bevisavvikelse", "B07": "utelämnande",
    "B08": "processfel", "B09": "rättskällefel", "B10": "rekvisitfel",
    "B11": "subsumtionsfel", "B12": "domskälsfel", "B13": "beviskravsfel",
    "B14": "intern motsägelse", "B15": "olöst fråga",
}


def _svensk_prosa(text: str) -> str:
    """C5: rapportens löptext ska vara läsbar svenska. Interna koder
    (B01-B15, HS01-HS19) översätts till svensk benämning; den maskinläsbara
    telemetrin ovanför rapporten behåller koderna."""
    text = re.sub(r"\bB01\s*[–-]\s*B15\b", "femton kontrollpunkter", text)

    def _b(m):
        return _BUGGNAMN.get(m.group(0), m.group(0)).capitalize()

    def _hs(m):
        import hard_stop_register as _hsr
        post = _hsr.hämta(m.group(0))
        return f"spärr: {post.beskrivning.lower()}" if post else "spärr"

    text = re.sub(r"\bB(0[1-9]|1[0-5])\b", _b, text)
    text = re.sub(r"\bHS\d\d[A-C]?\b", _hs, text)
    return text


def generate_audit_telemetry_header(
    case_state: CaseState,
    stress_test_result: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Genererar AUDIT_TELEMETRY_HEADER – alltid första blocket i L16-rapporten.
    """
    # CITATIONSTÄCKNING.
    # Måttet räknade tidigare andelen claims med ifyllt source_id. Varje claim
    # konstrueras med source_id = filen det kom ur, så måttet var 100 % per
    # konstruktion och kunde aldrig visa något annat. Det som faktiskt går att
    # verifiera är om påståendet är förankrat i en grafkant med giltigt,
    # ordagrant ankare mot en hashverifierad källa.
    if case_state.claims:
        förankrade = {
            e.source_node for e in case_state.graph_edges
            if e.anchor is not None and e.anchor.is_valid()
        }
        täckta = sum(1 for c in case_state.claims if c.claim_id in förankrade)
        pct = (täckta / len(case_state.claims) * 100) if case_state.claims else 0.0
        citation_coverage = f"{pct:.0f}%"
    else:
        citation_coverage = "0%"

    adversarial_pass = "GENOMFÖRD" if stress_test_result else "EJ GENOMFÖRD"
    risk_level = "EJ BEDÖMD"
    if stress_test_result:
        risk_level = stress_test_result.get("samlad_riskbedömning", "EJ BEDÖMD")

    telemetry = {
        "engine_version": case_state.engine_version,
        "target_jurisdiction": "SE",
        "analysis_date": datetime.date.today().isoformat(),
        "process_mode": case_state.process_mode.value,
        "court_type": case_state.court_type.value,
        "active_modules": case_state.activated_modules,
        # HALLUCINATIONSKONTROLL.
        # Fältet läste attributet _ac_violations, som aldrig sätts någonstans i
        # koden. Det kunde därför bara rapportera "PASSED", i varje ärende och
        # oavsett innehåll — en kontroll som per konstruktion alltid godkände.
        # Det som går att kontrollera är om något påstående saknar giltigt
        # ordagrant ankare mot en hashverifierad källa, dvs. text som inte kan
        # beläggas i akten.
        "hallucination_check": _hallucinationskontroll(case_state),
        # Härleds ur koderna (tidigare hard_stop_active: false trots HS11).
        "hard_stop_active": case_state.hard_stop_active,
        "hard_stop_triggered": case_state.hard_stop_triggered,
        "hard_stop_chain_abort": case_state.hard_stop_chain_abort,
        "pipeline_state": case_state.pipeline_state.value,
        "hard_stop_codes": [hs.value for hs in case_state.hard_stop_codes],
        "rekvisitmatris_status": case_state.rekvisitmatris_status,
        # SAKNAD BEVISNING.
        # Fältet rapporterade antalet HARD STOP-koder som antal saknade
        # bevislänkar. Två helt olika storheter: en akt med koderna HS11+HS09
        # redovisades som "2 väsentliga bevislänkar saknas", vilket den inte
        # betyder. Här räknas faktiskt obelagda led: påståenden utan giltigt
        # ankare, plus MUST-rekvisit utan bevisning.
        "missing_evidence_flagged": (
            _saknad_bevisning(case_state) > 0
            or len(case_state.files) == 0
            or "HS01C" in (case_state.hard_stop_codes or [])
        ),
        "missing_evidence_count": _saknad_bevisning(case_state),
        "hard_stop_code_count": len(case_state.hard_stop_codes),
        # Steg som inte genomförts. Ett ärende med icke genomförda steg eller
        # saknat aktunderlag är inte fullständigt analyserat.
        "steg_ej_genomforda": len(ej_genomförda_steg(case_state)),
        "analys_fullstandig": (
            len(ej_genomförda_steg(case_state)) == 0
            and (len(case_state.files) > 0 or len(case_state.claims) > 0)
            and not any(c in (case_state.hard_stop_codes or []) for c in ("HS01C", "HS11"))
        ),
        "citation_coverage": citation_coverage,
        "requisite_gate_status": (
            "PASSERAD" if case_state.metadata.get("requisite_gate_passed") is True
            else "SPÄRRAD" if case_state.metadata.get("requisite_gate_passed") is False
            else "EJ FASTSTÄLLD"
        ),
        "l9_status": case_state.metadata.get("l9_status", "EJ FASTSTÄLLD"),
        "adversarial_pass_status": adversarial_pass,
        "risk_level": risk_level,
        "audit_agent_a_findings": len(case_state.audit_a_findings),
        "audit_agent_b_findings": len(case_state.audit_b_findings),
        "audit_agent_c_findings": len(case_state.audit_c_findings),
        "overall_status": case_state.overall_status.value,
        "audit_controller_verdict": case_state.audit_controller_verdict.value,
        "scan_timestamp": (
            case_state.reproducibility.scan_timestamp
            if case_state.reproducibility else
            datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z"
        ),
        "falsification_verdict": case_state.falsification_verdict.value,
        "verbatim_gate": "VERBATIM_ANCHOR_GATE_ACTIVE",
        "subsumption_gate": "SUBSUMPTION_GATEKEEPER_ACTIVE",
        # Fält ur config/audit_controller.yaml telemetry_schema som saknades.
        "case_id": case_state.case_id,
        "audit_status": case_state.audit_controller_verdict.value,
        "standard_iso": _telemetri_standard("standard_iso"),
        "standard_enfsi": _telemetri_standard("standard_enfsi"),
        "locked_baseline": sum(1 for f in case_state.files
                               if f.baseline_state == BaselineState.LOCKED_BASELINE),
        "quarantine": sum(1 for f in case_state.files if f.quarantine_flag),
        "category_a": sum(1 for f in case_state.files
                          if f.evidence_category == EvidenceCategory.CATEGORY_A_STRONG),
        "category_b": sum(1 for f in case_state.files
                          if f.evidence_category == EvidenceCategory.CATEGORY_B_RISK),
    }

    lines = ["---", "AUDIT_TELEMETRY:"]
    for key, value in telemetry.items():
        if isinstance(value, list):
            lines.append(f"  {key}: {json.dumps(value, ensure_ascii=False)}")
        elif isinstance(value, bool):
            lines.append(f"  {key}: {str(value).lower()}")
        else:
            lines.append(f"  {key}: \"{value}\"")
    lines.append("---")
    return "\n".join(lines)


# ============================================================
# DETERMINE OVERALL STATUS
# ============================================================

def pdf_verktyg_tillgängligt() -> bool:
    """True om pdftotext (poppler) finns på PATH.

    PDF-extraktionen anropar pdftotext som extern binär. Saknas den läses noll
    tecken ur varje PDF. Detta är ett systemkrav, inte ett Python-paket, och
    måste därför kontrolleras separat.
    """
    import shutil
    return shutil.which("pdftotext") is not None


def _pdf_verktyg_saknas(case_state: CaseState) -> bool:
    """True om akten innehåller PDF men pdftotext saknas."""
    har_pdf = any(
        "PDF" in (f.filtyp_magic or "").upper()
        or f.relative_path.lower().endswith(".pdf")
        for f in case_state.files
    )
    return har_pdf and not pdf_verktyg_tillgängligt()


def determine_overall_status(case_state: CaseState) -> AuditStatus:
    """
    Bestämmer slutstatus A–I baserat på analysresultat.
    Status I sätts ALDRIG enbart pga HS01.
    """
    if case_state.hard_stop_active and not case_state.files:
        return AuditStatus.I  # Inga filer alls

    # Filer finns men ingenting kunde läsas ur dem. Då saknas underlag för
    # varje annan status: ett tomt underlag kan aldrig bära ett starkare
    # omdöme än ett fullständigt. Tidigare gav detta läge status G
    # (POTENTIELLT RÄTTSLIGT RELEVANT) på noll extraherat innehåll.
    if case_state.files and not case_state.claims:
        return AuditStatus.I  # OTILLRÄCKLIGT UNDERLAG

    if case_state.hard_stop_active:
        # HS01 är partiellt stopp – aktiva lager körs → status G eller H
        if case_state.audit_a_findings:
            return AuditStatus.G  # Potentiella avvikelser identifierade
        return AuditStatus.H  # Kan inte avgöras

    if case_state.falsification_verdict == FalsificationVerdict.NOT_RUN:
        return AuditStatus.H

    # HS11 = subsumtionskedjan saknar rättsfaktum (tom rekvisitmatris). Då har
    # ingenting prövats mot rekvisit, och A/B ("verifierat korrekt"/"verifierad
    # avvikelse") saknar bärighet. Tidigare kunde ett ROBUST-utfall utan
    # A-fynd ge A trots att subsumtionen var spärrad.
    if HardStopCode.HS11 in case_state.hard_stop_codes:
        if case_state.audit_a_findings:
            return AuditStatus.G
        return AuditStatus.H

    # Kontrollera om kritiska buggar finns
    critical_bugs = ["B07", "B09", "B10", "B11", "B14", "B15"]
    if any(
        case_state.counter_audit_results.get(b) == "IDENTIFIERAD"
        for b in critical_bugs
    ):
        return AuditStatus.G

    # Basera på falsification verdict
    if case_state.falsification_verdict == FalsificationVerdict.ROBUST:
        if not case_state.audit_a_findings:
            return AuditStatus.A
        return AuditStatus.B
    elif case_state.falsification_verdict == FalsificationVerdict.VULNERABLE:
        return AuditStatus.G
    else:
        return AuditStatus.H


# ============================================================
# RAPPORT-GENERATOR
# ============================================================

def generate_audit_report(
    case_state: CaseState,
    stress_test_result: Optional[Dict[str, Any]],
    judgment_draft: Optional[str],
    patches: List[SelfHealingPatch],
) -> str:
    """
    Genererar fullständig L16-rapport (Avsnitt A/B/C).
    AUDIT_TELEMETRY_HEADER är alltid första blocket.
    """
    lines = []

    # AUDIT_TELEMETRY_HEADER – alltid först
    lines.append(generate_audit_telemetry_header(case_state, stress_test_result))
    lines.append("")

    lines.append("# FORENSISK GRANSKNINGSRAPPORT")
    lines.append(f"## Mål: {case_state.case_id}")
    lines.append(f"## Datum: {datetime.date.today().isoformat()}")
    lines.append(f"## Mode: {case_state.process_mode.value}")
    lines.append(f"## Domstol: {case_state.court_type.value}")
    lines.append(f"## Slutstatus: {case_state.overall_status.value} "
                 f"({_STATUSTEXT.get(case_state.overall_status.value, '')})")
    lines.append("")
    lines.append("**PROVISIONAL ONLY** - analytiskt underlag, inte ett avgörande. "
                 "Systemet saknar dömande mandat.")
    lines.append("")

    # Varningsvy vid domänspärr: var kedjan bröts och varför. Slutsatskedjan
    # stoppas; rekvisitmatris och kontrollerade handlingar bevaras.
    from hard_stop_las import spärrpayload as _spärrp
    _sp = _spärrp(case_state)
    if _sp:
        _d = _sp.get("spärrdetalj") or {}
        lines.append("## VARNING: JURIDISK SLUTSATS SPÄRRAD")
        lines.append("")
        lines.append(_sp["spärrtext"])
        lines.append("")
        lines.append("### Var kedjan bröts")
        for k in _d.get("kedjebrott", []):
            lines.append(f"- {k['beskrivning']} (bruten vid: {k['bruten_vid']}; räckvidd: {k['räckvidd']}). "
                         f"Villkor: {k['villkor']}")
        lines.append("")
        lines.append("### Rekvisit utan verifierad bevisning")
        for l in _d.get("luckor", []):
            lines.append(f"- Rad {l['rad']}: {l['rekvisit']} | källa/lagrum: {l['källa_lagrum']} | "
                         f"{l['saknad_bevisning']}")
        lines.append("")
        lines.append(f"Bevarat: rekvisitmatris med {_d.get('rekvisitmatris_bevarad', 0)} rader; "
                     f"{len(_d.get('kontrollerade_källor', []))} kontrollerade handlingar "
                     f"(karantän {_d.get('karantän_antal', 0)}, ej verifierbara {_d.get('ej_verifierbara_antal', 0)}).")
        lines.append(f"Nästa steg: {_d.get('nästa_steg', 'SAKNAS')}")
        lines.append("")

    # AVSNITT A: LÅST BEVISBALANS
    lines.append("## AVSNITT A: LÅST BEVISBALANS (LOCKED_BASELINE)")
    lines.append("")
    lines.append("### Statistik")
    total_files = len(case_state.files)
    cat_a = sum(1 for f in case_state.files if f.evidence_category == EvidenceCategory.CATEGORY_A_STRONG)
    cat_b = sum(1 for f in case_state.files if f.evidence_category == EvidenceCategory.CATEGORY_B_RISK)
    quarantine = sum(1 for f in case_state.files if f.quarantine_flag)
    unresolved_edges = sum(1 for e in case_state.graph_edges if e.edge_type == EdgeType.UNRESOLVED)

    lines.append(f"- Totalt filer: {total_files}")
    lines.append(f"- Kategori A (stark): {cat_a}")
    lines.append(f"- Kategori B (risk): {cat_b}")
    lines.append(f"- Karantän: {quarantine}")
    lines.append(f"- Grafkanter totalt: {len(case_state.graph_edges)}")
    lines.append(f"- UNRESOLVED kanter: {unresolved_edges}")
    lines.append(f"- Claims registrerade: {len(case_state.claims)}")
    lines.append("")

    # Rubriken löd tidigare "Styrkta omständigheter". Avsnittet listar
    # HANDLINGAR med verifierad integritet — inte omständigheter. En jurist
    # som läser "styrkta omständigheter" förväntar sig fastställda sakför-
    # hållanden och fick en filförteckning med hashsummor. Att en fil är
    # integritetsverifierad säger ingenting om vad den bevisar.
    lines.append(
        "### Handlingar med verifierad integritet "
        "(Kategori A, Gatekeeper-godkända)"
    )
    lines.append(
        "_Integritetsverifiering avser filens oförändrade skick, "
        "inte innehållets bevisvärde._"
    )
    cat_a_files = [f for f in case_state.files if f.evidence_category == EvidenceCategory.CATEGORY_A_STRONG]
    if cat_a_files:
        for f in cat_a_files:
            lines.append(
                f"- {f.file_id} | {f.relative_path} | "
                f"{f.filtyp_magic} | SHA256: {f.hash_sha256[:16]}..."
            )
    else:
        lines.append("- [INGA KATEGORI A-FILER IDENTIFIERADE]")
    lines.append("")

    # AVSNITT B: KARANTÄNSRAPPORT
    lines.append("## AVSNITT B: KARANTÄNSRAPPORT (DELTA-ANALYS)")
    lines.append("")
    quarantine_files = [f for f in case_state.files if f.quarantine_flag]
    if quarantine_files:
        for f in quarantine_files:
            lines.append(
                f"- {f.file_id} | {f.relative_path} | "
                f"Status: NOT_YET_PLEADED | Kräver formellt åberopande"
            )
    else:
        lines.append("- [INGA KARANTÄNFILER]")
    lines.append("")

    # ── RÄTTSOMRÅDEN (L6B) ────────────────────────────────────────────
    # Domänkodtabellerna kördes tidigare aldrig från den kanoniska motorn.
    # Rapporten saknade därför varje uppgift om vilket rättsområde akten rör.
    skan = case_state.metadata.get("rättsområdesskanning") or {}
    # ── HARD STOPS MED VILLKOR ────────────────────────────────────────
    # Varje aktiverad kod redovisas med sitt exakta utlösningsvillkor och sin
    # räckvidd, så att läsaren kan se om ärendet stoppats eller endast en kedja.
    if case_state.hard_stop_codes:
        try:
            import hard_stop_register as _hsr
            lines.append("## HARD STOPS — VILLKOR OCH RÄCKVIDD")
            lines.append("")
            for hs in case_state.hard_stop_codes:
                post = _hsr.hämta(hs.value)
                if post:
                    lines.append(f"- **{post.kod}** {post.beskrivning}")
                    lines.append(f"  - Räckvidd: {post.räckvidd}")
                    lines.append(f"  - Villkor: {post.villkor}")
                else:
                    lines.append(
                        f"- **{hs.value}** (satt via violation-mekanismen)"
                    )
            lines.append("")
            lines.append(
                "_KEDJAN = endast den berörda analyskedjan spärrad; övriga "
                "lager har körts. HELA_ÄRENDET = körningen avbruten._"
            )
            lines.append("")
        except Exception as exc:
            # Avsnittet fick tidigare falla bort tyst. Läsaren såg då en
            # rapport helt utan hard stop-redovisning, utan att något angav
            # att koderna fanns men inte kunnat redovisas — vilket är det
            # motsatta budskapet mot det sanna.
            lines.append("## HARD STOPS — VILLKOR OCH RÄCKVIDD")
            lines.append("")
            lines.append(
                f"**Villkoren kunde inte redovisas: {type(exc).__name__}: {exc}**"
            )
            lines.append("")
            lines.append("Aktiverade koder i ärendet:")
            for hs in case_state.hard_stop_codes:
                lines.append(f"- {getattr(hs, 'value', hs)}")
            lines.append("")

    # ── DISKREPANSANALYSENS OMFATTNING ────────────────────────────────
    # En avkortad operation får inte redovisas som fullständig. Omfattningen
    # låg tidigare endast i metadata och nådde aldrig rapporten, så läsaren
    # kunde inte skilja "inga diskrepanser" från "jämförelsen kapades".
    disk = case_state.metadata.get("diskrepansanalys") or {}
    if disk:
        lines.append("## DISKREPANSANALYSENS OMFATTNING")
        lines.append("")
        lines.append(f"- Påståenden i underlaget: **{disk.get('claims')}**")
        lines.append(f"- Kandidatpar bildade: **{disk.get('kandidatpar')}**")
        lines.append(f"- Par faktiskt prövade: **{disk.get('prövade_par')}**")
        lines.append(f"- Par uteslutna: **{disk.get('uteslutna_par')}**")
        lines.append(f"- Diskrepanser redovisade: **{disk.get('diskrepanser')}**")
        if disk.get("avkortad"):
            vad = []
            if disk.get("kandidatpar_avkortade"):
                vad.append("kandidatparen")
            if disk.get("diskrepanslista_avkortad"):
                vad.append("diskrepanslistan")
            lines.append("")
            lines.append(
                f"**AVKORTAD ANALYS — {' och '.join(vad)} nådde sin gräns. "
                f"Jämförelsen är inte uttömmande.**"
            )
        lines.append("")
        lines.append(f"_Urvalsregel: {disk.get('urvalsregel', 'ej angiven')}_")
        lines.append("")

    # ── ANALYSTÄCKNING: STEG SOM INTE GENOMFÖRTS ──────────────────────
    # Ett havererat lager skrevs tidigare bara till stdout. Rapporten visste
    # ingenting om det och ärendet kunde redovisas som genomfört.
    ej_klara = ej_genomförda_steg(case_state)
    if ej_klara:
        lines.append("## STEG SOM INTE GENOMFÖRTS")
        lines.append("")
        lines.append(
            f"**{len(ej_klara)} av analysens steg kunde inte genomföras. "
            f"Analysen är partiell i motsvarande mån.**"
        )
        lines.append("")
        for s_ in ej_klara:
            lines.append(f"- {s_['steg']} | {s_['status']} | {s_.get('skäl','')}")
        lines.append("")

    # ── EXTRAKTIONSTÄCKNING ───────────────────────────────────────────
    täck = case_state.metadata.get("extraktionstäckning") or {}
    if täck:
        lines.append("## EXTRAKTIONSTÄCKNING")
        lines.append("")
        lines.append(
            f"- Handlingar som gav text: **{täck.get('handlingar_med_text')} av "
            f"{täck.get('handlingar_totalt')}** "
            f"({täck.get('täckning_procent')} %)"
        )
        utan = täck.get("utan_text") or []
        if utan:
            lines.append("")
            lines.append(
                f"**{len(utan)} handlingar gav ingen text och ingår därmed inte "
                f"i analysen:**"
            )
            for u in utan:
                lines.append(
                    f"- {u['fil']} | status: {u['status']} | {u['orsak']}"
                )
            lines.append("")
            lines.append(
                "_Analysen är partiell i motsvarande mån. Skannade handlingar "
                "kräver OCR för att kunna läsas._"
            )
        lines.append("")

    # ── HANDLINGSTYPER ────────────────────────────────────────────────
    dt = case_state.metadata.get("dokumenttyper") or {}
    if dt.get("per_fil"):
        lines.append("## HANDLINGSTYPER I AKTEN")
        lines.append("")
        _förd = ", ".join(f"{k.replace('_', ' ')} {v}"
                          for k, v in (dt.get('fördelning') or {}).items())
        lines.append(f"Fördelning: {_förd or 'ingen'}; "
                     f"utan fastställd typ: {dt.get('utan_typ', 0)}")
        lines.append("")
        for fid, v in dt["per_fil"].items():
            lines.append(f"- {v['fil']} | typ: **{v['typ']}** | "
                         f"kategori: {v['kategori']}")
        lines.append("")

    lines.append("## RÄTTSOMRÅDEN IDENTIFIERADE I AKTMATERIALET (L6B)")
    lines.append("")
    domäner = skan.get("domäner") or {}
    med_träff = skan.get("domäner_med_träff") or []
    if med_träff:
        lines.append(
            f"Skannade {len(domäner)} domänkodtabeller. "
            f"Träff i {len(med_träff)}."
        )
        lines.append("")
        for d in med_träff:
            v = domäner.get(d) or {}
            lines.append(
                f"- **{d}** | {v.get('antal_träffar', 0)} träffar | "
                f"koder: {', '.join(v.get('koder') or [])}"
            )
        lines.append("")
        lines.append(
            "_Träff är sökhjälp och indikation på tillämpligt rättsområde — "
            "inte subsumtion och inte bevisvärdering._"
        )
    mönster = (skan.get("mönsterbibliotek") or {}).get("träffar") or []
    if mönster:
        lines.append("")
        lines.append("### Processuella mönster (mönsterbibliotek v2)")
        for t in mönster:
            lines.append(
                f"- **{t.get('rule_id')}** {t.get('title')} | "
                f"nyckelord: {t.get('matched_keywords')} | "
                f"lagrum: {t.get('legal_refs')}"
            )
    elif skan.get("status") == "GENOMFÖRD":
        lines.append(
            f"- [INGEN DOMÄNTRÄFF I {len(domäner)} SKANNADE KODTABELLER]"
        )
    else:
        lines.append(
            f"- [SKANNING EJ KÖRBAR: {skan.get('skäl', 'okänd orsak')}]"
        )
    lines.append("")

    # AUDIT-AGENTER
    lines.append("## AUDIT-AGENT A – FALSIFIERING")
    if case_state.audit_a_findings:
        for finding in case_state.audit_a_findings:
            lines.append(
                f"[{finding.finding_id}] | Avvikelse: {finding.description} | "
                f"Källa: {finding.source_ref} | Allvarlighet: {finding.severity}"
            )
    else:
        lines.append("[INGA AVVIKELSER IDENTIFIERADE – AUDIT-AGENT A]")
    lines.append("")

    lines.append("## AUDIT-AGENT B – VERIFIERING")
    if case_state.audit_b_findings:
        for finding in case_state.audit_b_findings:
            lines.append(
                f"[{finding.finding_id}] | Stöd: {finding.description} | "
                f"Källa: {finding.source_ref}"
            )
    else:
        lines.append("[INGA STÖD IDENTIFIERADE – AUDIT-AGENT B]")
    lines.append("")

    lines.append("## AUDIT-AGENT C – SECOND-ORDER AUDIT")
    if case_state.audit_c_findings:
        for finding in case_state.audit_c_findings:
            lines.append(
                f"[{finding.finding_id}] | Kontroll: {finding.description} | "
                f"Källa: {finding.source_ref}"
            )
    else:
        lines.append("[SECOND-ORDER AUDIT GODKÄND – AUDIT-AGENT C]")
    lines.append("")

    # COUNTER AUDIT
    lines.append("## COUNTER_AUDIT_AGENT – BUGGREGISTER B01–B15")
    if case_state.counter_audit_results:
        identified = [k for k, v in case_state.counter_audit_results.items() if v == "IDENTIFIERAD"]
        for bug_id, status in sorted(case_state.counter_audit_results.items()):
            lines.append(f"[{bug_id}] | Status: {status}")
        lines.append(f"TOTALT IDENTIFIERADE BUGGAR: {len(identified)}")
        # Samma källa som FalsificationEngine (BUG_SEVERITY). Listan här
        # saknade B14, så rapporten kunde säga NEJ när falsifieringen
        # faktiskt blockerades.
        critical = [b for b in identified
                    if CounterAuditAgent.BUG_SEVERITY.get(b) == "KRITISK"]
        lines.append(f"KRITISKA: {len(critical)}")
        lines.append(f"BLOCKERAR_FALSIFICATION: {'JA' if critical else 'NEJ'}")
    lines.append("")

    # RISKANALYS (AGENT_C_STRESS_TEST)
    lines.append("## RISKANALYS OCH SVAGASTE LÄNK I TALAN")
    if stress_test_result:
        lines.append(f"SAMLAD_RISKBEDÖMNING: {stress_test_result.get('samlad_riskbedömning', 'EJ BEDÖMD')}")
        lines.append("")
        lines.append("### Svagaste länkar")
        for item in stress_test_result.get("svagaste_lankar", []):
            lines.append(
                f"[{item['id']}] | Sårbarhet: {item['sårbarhet']} | "
                f"Rättslig påverkan: {item['rättslig_påverkan']}"
            )
        lines.append("")
        lines.append("### Alternativa tolkningar")
        for item in stress_test_result.get("alternativa_tolkningar", []):
            lines.append(f"[{item['id']}] | {item['alternativ_tolkning']}")
        lines.append("")
        lines.append("### Processuella invändningar")
        for item in stress_test_result.get("processuella_invandningar", []):
            lines.append(
                f"[{item['id']}] | Typ: {item['typ']} | Risk: {item['risk']} | "
                f"Grund: {item['rättslig_grund']}"
            )
    else:
        lines.append("[AGENT_C_STRESS_TEST EJ GENOMFÖRD]")
    lines.append("")

    # AVSNITT C: PROCESSUELL ÅTGÄRDSLISTA
    lines.append("## AVSNITT C: PROCESSUELL ÅTGÄRDSLISTA (Self-Healing Patches)")
    if patches:
        for patch in patches:
            lines.append(
                f"[{patch.patch_id}] | Trigger: {patch.trigger} | "
                f"Allvarlighet: {patch.severity} | Tillämpad: {patch.applied}"
            )
    else:
        lines.append("[INGA PATCHES KRÄVDES]")
    lines.append("")

    # DOMSUTKAST (om MODE B)
    if (case_state.process_mode == ProcessMode.JUDGMENT_CONSTRUCTION and
            judgment_draft):
        lines.append("## PROVISORISKT DOMSUTKAST - PROVISIONAL JUDGMENT DRAFT")
        lines.append("**PROVISIONAL JUDGMENT DRAFT - PROVISIONAL ONLY**")
        lines.append(judgment_draft)
        lines.append("")

    # JURIDISK ANSVARSFRISKRIVNING
    lines.append(
        "⚠️ Alla AI-genererade juridiska handlingar måste granskas av behörig jurist "
        "innan de används i faktiska rättsliga sammanhang. "
        "Detta system saknar dömande mandat."
    )

    return lines[0] + "\n" + _svensk_prosa("\n".join(lines[1:]))  # telemetri (lines[0]) behåller koderna


# ============================================================
# MINNESBANK
# ============================================================

def _resolve_knowledge_path(filename: str, base_references_dir: str = "references") -> Optional[str]:
    """Löser filsökvägen för en kunskapsfil baserat på ny kunskapsstruktur."""
    protocol_map = {
        "rattstidskontroll-protokoll.md": "references/knowledge/procedures/rattstidskontroll-protokoll.md",
        "rättstidskontroll-protokoll.md": "references/knowledge/procedures/rattstidskontroll-protokoll.md",
        "rostanalys-protokoll.md": "references/knowledge/procedures/rostanalys-protokoll.md",
        "röstanalys-protokoll.md": "references/knowledge/procedures/rostanalys-protokoll.md",
        "metadata-forensik-protokoll.md": "runtime/knowledge/metadata-forensik-protokoll.md",  # kanonisk plats (byte-identisk kopia i references/knowledge/other borttagen)
    }
    if filename in protocol_map:
        path = protocol_map[filename]
    else:
        path = os.path.join(base_references_dir, filename)

    if os.path.exists(path):
        return path
    # Relativa sökvägar löstes tidigare mot aktuell katalog, så minnesbanken
    # blev DISABLED så fort CLI/MCP startades utanför installationsroten.
    # Fallback: samma relativa sökväg mot paketets egen rot.
    if not os.path.isabs(path):
        _rot = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        alt = os.path.join(_rot, path)
        if os.path.exists(alt):
            return alt
    return None


def minnesbank_kontroll(references_dir: str = "references") -> Dict[str, Any]:
    """
    Kontrollerar att minnesbank-filer finns (använder ny kunskapsstruktur).
    Returnerar DISABLED om filer saknas (ÄNDRING-004).
    """
    required_files = [
        "rättstidskontroll-protokoll.md",
        "röstanalys-protokoll.md",
        "metadata-forensik-protokoll.md",
    ]
    missing = []
    for filename in required_files:
        path = _resolve_knowledge_path(filename, references_dir)
        if path is None:
            missing.append(filename)

    if missing:
        return {
            "status": "DISABLED",
            "missing_files": missing,
            "message": f"Minnesbank inaktiverad – saknade filer: {missing}. Körning fortsätter utan minnesbank.",
        }
    return {
        "status": "ACTIVE",
        "missing_files": [],
        "message": "Minnesbank aktiv – alla referensfiler tillgängliga från ny kunskapsstruktur.",
    }


def minnesbank_las(references_dir: str = "references") -> Dict[str, Any]:
    """
    Läser minnesbank-filer från ny kunskapsstruktur. Returnerar DISABLED eller ACTIVE utan exception.
    """
    try:
        result = minnesbank_kontroll(references_dir)
        if result["status"] == "DISABLED":
            return result
        content = {}
        for filename in [
            "rättstidskontroll-protokoll.md",
            "röstanalys-protokoll.md",
            "metadata-forensik-protokoll.md",
        ]:
            path = _resolve_knowledge_path(filename, references_dir)
            if path is None:
                content[filename] = "[SAKNAD]"
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content[filename] = f.read()
            except (IOError, OSError) as e:
                content[filename] = f"[KAN EJ LÄSAS: {e}]"
        return {"status": "ACTIVE", "content": content, "paths": {k: _resolve_knowledge_path(k, references_dir) for k in content.keys()}}
    except Exception as e:
        return {"status": "DISABLED", "missing_files": [], "message": f"Okänt fel: {e}"}


# ============================================================
# DATAEXPORT (ÄNDRING-006)
# ============================================================

_EXPORTFILER = ("case_state_v10.json", "rekvisitmatris.csv",
                "audit_report_v10.md", "presentation_views_v10.json")


def kontrollera_tom_export(case_state: CaseState, output_dir: Optional[str] = None,
                           export_results: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Steg 14: tom presentationsvy, tom rekvisitmatris eller tom/saknad
    exportfil under en aktiv körning är ett KRITISKT PIPELINEFEL - aldrig en
    säkerhetsspärr. Fynden läggs i metadata["kritiska_pipelinefel"] (även när
    en spärr råkar vara aktiv, så att tomheten inte förklaras med spärren).
    Utan output_dir prövas bara minnesobjekten (före export)."""
    fel: List[Dict[str, Any]] = []

    def _f(artefakt: str, orsak: str) -> None:
        fel.append({"artefakt": artefakt, "orsak": orsak,
                    "klassning": "KRITISKT_PIPELINEFEL", "säkerhetsspärr": False})

    if not case_state.requisite_matrix:
        _orsak = "Rekvisitmatrisen är tom under aktiv körning."
        try:  # Steg 15: konfigurationsfel redovisas som orsak, aldrig exempeldata.
            from requisite_claim_mapper import profil_laddningsfel as _plf
            if _plf():
                _orsak += f" Måltypsprofiler kunde inte laddas: {_plf()}"
        except ImportError as _ie:
            _orsak += f" (requisite_claim_mapper ej importerbar: {_ie})"
        _f("rekvisitmatris", _orsak)
    pres = case_state.presentation
    if pres is None or not (pres.court_view or pres.party_a or pres.party_b or pres.mediation):
        _f("presentation_views", "Presentationsvyn är tom under aktiv körning.")
    if output_dir:
        for namn in _EXPORTFILER:
            sökväg = os.path.join(output_dir, namn)
            if not os.path.isfile(sökväg):
                if not any(f["artefakt"] == namn.split("_v10")[0].split(".")[0] for f in fel):
                    _f(namn, "Exportfilen skrevs inte.")
            elif os.path.getsize(sökväg) == 0:
                _f(namn, "Exportfilen är tom (0 byte).")
    case_state.metadata["kritiska_pipelinefel"] = fel
    return fel


def exportera_l16_output(
    case_state: CaseState,
    report_text: str,
    output_dir: Optional[str] = None,
) -> Dict[str, str]:
    """
    Exporterar L16-output i tre format: JSON, CSV, Markdown.
    """
    if not output_dir:
        output_dir = str(Path(__file__).resolve().parent.parent / "output")
    os.makedirs(output_dir, exist_ok=True)
    results = {}

    # JSON-export (JSON-LD)
    try:
        json_data = {
            "@context": "https://schema.org/",
            "@type": "forensic:GranskningsRapport",
            "case_id": case_state.case_id,
            "engine_version": case_state.engine_version,
            "analysis_date": datetime.date.today().isoformat(),
            "process_mode": case_state.process_mode.value,
            "court_type": case_state.court_type.value,
            "overall_status": case_state.overall_status.value,
            "falsification_verdict": case_state.falsification_verdict.value,
            "audit_controller_verdict": case_state.audit_controller_verdict.value,
            "case_state": case_state.to_dict(),
        }
        json_path = os.path.join(output_dir, "case_state_v10.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        results["json"] = "EXPORTED"
    except Exception as e:
        results["json"] = f"KAN EJ EXPORTERAS: {e}"

    # CSV-export (rekvisitmatris)
    try:
        # Steg 14: spärrkolumner så att matrisen kan synkas mot case_state.
        csv_lines = ["rekvisit,modal,faktum_id,källa,status,"
                     "pipeline_state,hard_stop_active,hard_stop_triggered,"
                     "hard_stop_chain_abort,hard_stop_koder,rekvisitmatris_status,"
                     "requisite_gate_status,l9_status"]
        _ps = case_state.pipeline_state.value
        _ha = str(case_state.hard_stop_active).lower()
        _ht = str(case_state.hard_stop_triggered).lower()
        _hca = str(case_state.hard_stop_chain_abort).lower()
        _hs = ";".join(hs.value for hs in case_state.hard_stop_codes)
        _ms = case_state.rekvisitmatris_status
        _gs = (
            "PASSERAD" if case_state.metadata.get("requisite_gate_passed") is True
            else "SPÄRRAD" if case_state.metadata.get("requisite_gate_passed") is False
            else "EJ FASTSTÄLLD"
        )
        _l9 = case_state.metadata.get("l9_status", "EJ FASTSTÄLLD")

        def _csv_q(v) -> str:
            # Steg 17: RFC 4180 - citattecken i fältet dubbleras (förvanskas inte).
            return str(v if v is not None else "").replace('"', '""')
        for req in case_state.requisite_matrix:
            row = (
                f'"{_csv_q(req.requisite_text[:80])}",'
                f"{req.modal.value},"
                f"{req.claim_id},"
                f'"{_csv_q(req.source_ref)}",'
                f"{req.status.value},"
                f"{_ps},{_ha},{_ht},{_hca},{_hs},{_ms},{_gs},"
                f'"{_csv_q(_l9)}"'
            )
            csv_lines.append(row)
        csv_path = os.path.join(output_dir, "rekvisitmatris.csv")
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("\n".join(csv_lines))
        results["csv"] = "EXPORTED"
    except Exception as e:
        results["csv"] = f"KAN EJ EXPORTERAS: {e}"

    # Markdown-export
    try:
        md_path = os.path.join(output_dir, "audit_report_v10.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(report_text)
        results["markdown"] = "EXPORTED"
    except Exception as e:
        results["markdown"] = f"KAN EJ EXPORTERAS: {e}"

    # Presentation views JSON-export (L16). Steg 14b: även vid spärr utan
    # byggda vyer (L0-stopp) skrivs spärrblocket, så att spärren syns på disk.
    from hard_stop_las import spärr_aktiv as _låst
    if case_state.presentation or _låst(case_state):
        try:
            from dataclasses import asdict as _asdict
            _pr = case_state.presentation
            views_data = {
                "court_view": _pr.court_view if _pr else None,
                "party_a": _asdict(_pr.party_a) if _pr and _pr.party_a else None,
                "party_b": _asdict(_pr.party_b) if _pr and _pr.party_b else None,
                "mediation": _pr.mediation if _pr else None,
                "disclaimer": _pr.disclaimer if _pr else None,
                "pipeline_state": case_state.pipeline_state.value,
                "hard_stop_active": case_state.hard_stop_active,
                "hard_stop_triggered": case_state.hard_stop_triggered,
                "hard_stop_chain_abort": case_state.hard_stop_chain_abort,
                "hard_stop_codes": [hs.value for hs in case_state.hard_stop_codes],
                "requisite_gate_status": (
                    "PASSERAD" if case_state.metadata.get("requisite_gate_passed") is True
                    else "SPÄRRAD" if case_state.metadata.get("requisite_gate_passed") is False
                    else "EJ FASTSTÄLLD"
                ),
                "l9_status": case_state.metadata.get("l9_status", "EJ FASTSTÄLLD"),
                "rekvisitmatris_status": case_state.rekvisitmatris_status,
                "falsification_verdict": case_state.falsification_verdict.value,
                "kritiska_pipelinefel": list(case_state.metadata.get("kritiska_pipelinefel") or []),
            }
            from hard_stop_las import spärrpayload as _spärr
            views_data.update(_spärr(case_state))
            if case_state.metadata.get("legal_merge_output") is not None:
                views_data["legal_merge"] = {
                    "output": case_state.metadata.get("legal_merge_output"),
                    "anchors": case_state.metadata.get("legal_merge_anchors"),
                }
            views_path = os.path.join(output_dir, "presentation_views_v10.json")
            with open(views_path, "w", encoding="utf-8") as f:
                json.dump(views_data, f, ensure_ascii=False, indent=2)
            results["presentation_views"] = "EXPORTED"
        except Exception as e:
            results["presentation_views"] = f"KAN EJ EXPORTERAS: {e}"

    return results


# ============================================================
# L1: PROCESSKLASSIFICERING – HJÄLPFUNKTION
# ============================================================

def _classify_court_from_files(files: List["FileRecord"]) -> "CourtType":
    """
    Identifierar domstolsslag dynamiskt från filnamn och sökvägar (L1).
    Ingen måltyp hårdkodas – identifieras från aktmaterialet.
    """
    all_paths = " ".join(
        (f.relative_path + " " + f.file_id).lower()
        for f in files
    )
    # Förvaltningsdomstol
    admin_signals = [
        "förvaltningsrätt", "kammarrätt", "hfd", "försäkringskassan",
        "sfb", "sjukpenning", "sgi", "sol", "lvu", "lvm", "lss",
        "socialtjänst", "socialnämnd", "fpl", "fl_", "_fl_",
        "beslut_fk", "fk_", "_fk_", "fk.", "beslut_fk",
        "försäkring", "rehabilitering", "arbetsförmåga",
    ]
    if any(s in all_paths for s in admin_signals):
        return CourtType.ADMINISTRATIVE_COURT

    # Brottmål
    criminal_signals = [
        "brottmål", "åklagare", "brb", "tingsrätt_brott", "fup",
        "förundersökning", "polisprotokoll", "stämningsansökan_brott",
    ]
    if any(s in all_paths for s in criminal_signals):
        return CourtType.CRIMINAL_COURT

    # Tvistemål
    civil_signals = [
        "tvistemål", "tingsrätt", "hovrätt", "hd_", "_hd_",
        "hyresrätt", "lokalhyra", "skadestånd", "edition",
        "stämningsansökan", "rb_", "_rb_",
    ]
    if any(s in all_paths for s in civil_signals):
        return CourtType.CIVIL_COURT

    return CourtType.UNKNOWN


# ============================================================
# L7: RÄTTSKÄLLEKONTROLL – INTEGRERAD MED DEEP SEARCH
# ============================================================

class LegalSourceSearchIntegration:
    """
    L7: Rättskällekontroll integrerad med Deep Search (FIX-N).

    Flöde:
    ÄRENDE → PROCESSIDENTIFIERING → RÄTTSFRÅGA → RÄTTSKÄLLEBEHOV
    → SEARCH → KÄLLKLASSIFICERING → VERIFIERING → RÄTTSKÄLLEPOST → ANALYS

    Webb/API-sökning är verifieringsfunktion – ligger UNDER analysen.
    Aktiveras med enable_network=True för faktiska API-anrop.
    """

    # Rättsfrågor per domstolstyp – identifieras dynamiskt, ej hårdkodade slutsatser
    RÄTTSFRÅGOR_PER_DOMSTOL = {
        CourtType.ADMINISTRATIVE_COURT: [
            "officialprincipen FPL 8 §",
            "utredningsskyldighet FL 23 §",
            "motiveringsplikt FL 32 §",
        ],
        CourtType.CRIMINAL_COURT: [
            "in dubio pro reo RB 35:1",
            "beviskrav bortom rimligt tvivel",
        ],
        CourtType.CIVIL_COURT: [
            "dispositionsprincipen RB 17:3",
            "fri bevisprövning RB 35:1",
        ],
        CourtType.UNKNOWN: [],
    }

    def __init__(self, case_state: "CaseState"):
        self.case_state = case_state
        self.log: List[str] = []

    def run(self, enable_network: bool = False) -> List["LegalSourceRecord"]:
        """
        Kör L7 rättskällekontroll.
        enable_network=True aktiverar faktiska SEARCH_01–10 API-anrop.
        enable_network=False registrerar rättskällebehov utan nätverksanrop.
        """
        court = self.case_state.court_type
        rättsfrågor = self.RÄTTSFRÅGOR_PER_DOMSTOL.get(court, [])

        self.log.append(
            f"[L7] Rättskällekontroll startar. Domstol: {court.value}. "
            f"Identifierade rättsfrågor: {len(rättsfrågor)}"
        )

        records: List[LegalSourceRecord] = []

        for rättsfråga in rättsfrågor:
            self.log.append(f"[L7] Rättsfråga: {rättsfråga}")

            if enable_network:
                # Aktivera Deep Search för faktisk verifiering
                records.extend(self._search_legal_source(rättsfråga))
            else:
                # Registrera rättskällebehov utan nätverksanrop
                record = LegalSourceRecord(
                    source_id=f"LS-NEED-{len(records)+1:04d}",
                    source_type="LAG",
                    authority_level="BINDANDE",
                    court=court.value,
                    case_number="",
                    reference=rättsfråga,
                    date="",
                    legal_issue=rättsfråga,
                    holding="",
                    cited_law=rättsfråga,
                    official_source="NOT_VERIFIED",
                    current_status="REQUIRES_SEARCH_01_VERIFICATION",
                    later_case_check="REQUIRED",
                    applicability_to_current_case="NOT YET ASSESSED",
                )
                records.append(record)
                self.log.append(
                    f"[L7] Rättskällebehov registrerat: {rättsfråga} "
                    f"[REQUIRES_SEARCH_01_VERIFICATION]"
                )

        # FAS 1: Strikt rättskälleintegritet (RT-BO, RT-BP, HS07/HS10/P12).
        # EJ_RÄTTSKÄLLA-poster och prejudikat utan holding-kedja blockeras
        # från rekvisitkedjan och registrerar hårdstopp.
        records, blockerade = self._verifiera_rättskälleintegritet(records)
        for rec in blockerade:
            code = (HardStopCode.HS10 if "HS10" in rec.blocking_reason
                    else HardStopCode.HS07)
            if code not in self.case_state.hard_stop_codes:
                self.case_state.hard_stop_codes.append(code)
            self.log.append(
                f"[L7] Blockerad rättskälla {rec.source_id}: {rec.blocking_reason}"
            )

        self.case_state.legal_sources.extend(records)
        self.log.append(
            f"[L7] Rättskällekontroll klar. "
            f"{len(records)} poster registrerade, {len(blockerade)} blockerade "
            f"({'med' if enable_network else 'utan'} nätverksanrop)."
        )
        return records

    def _verifiera_rättskälleintegritet(
        self, records: List[LegalSourceRecord]
    ) -> tuple:
        """
        FAS 1: Strikt runtime-validering av rättskälleintegritet.
        - RT-BO (FIX-N): EJ_RÄTTSKÄLLA-poster blockeras (HS10).
        - RT-BP (FIX-P/P12): Prejudikat utan holding-verifiering H1/H2/H3
          blockeras (HS07).
        Returnerar (kvarvarande poster, blockerade poster).
        """
        kvar: List[LegalSourceRecord] = []
        blockerade: List[LegalSourceRecord] = []
        for rec in records:
            if rec.blocked_from_requisites:
                if not rec.blocking_reason:
                    rec.blocking_reason = "EJ_RÄTTSKÄLLA – HS10"
                blockerade.append(rec)
                continue
            if (rec.source_type == "PREJUDIKAT" and
                    rec.holding_verification in ("HOLDING_EJ_VERIFIERBAR", "")):
                rec.blocked_from_requisites = True
                rec.blocking_reason = (
                    "PREJUDIKAT UTAN HOLDING-VERIFIERING H1/H2/H3 – HS07/P12"
                )
                blockerade.append(rec)
                continue
            kvar.append(rec)
        return kvar, blockerade

    def _search_legal_source(self, rättsfråga: str) -> List[LegalSourceRecord]:
        """
        Anropar Deep Search pipeline för faktisk rättskälleverifiering.
        Importerar deep_search_pipeline valfritt (try/except).
        """
        try:
            from deep_search_pipeline import kör_deep_search_pipeline
            # RT-BQ (FIX-Q): SEARCH_10 körs ALLTID för prejudikat – senare
            # praxis som ändrat/preciserat rättsläget får aldrig utelämnas.
            results = kör_deep_search_pipeline(
                sokterm=rättsfråga,
                search_ids=["SEARCH_01", "SEARCH_02", "SEARCH_10"],
                parallel=False,
                timeout=8,
            )
            records = []
            for sid, result in results.items():
                if result.status == "SUCCESS":
                    for item in result.data[:2]:
                        # RT-BO: EJ_RÄTTSKÄLLA blockeras (FIX-N).
                        blocked = (
                            result.authority_level == "EJ_RÄTTSKÄLLA"
                            or result.source_type in {
                                "MYNDIGHET", "DOKTRIN", "ARTIKEL", "AI_GENERERAT"
                            }
                        )
                        # RT-BP: Prejudikat kräver holding-verifiering H1/H2/H3.
                        holding_verification = "N/A"
                        if result.source_type == "PREJUDIKAT":
                            holding_verification = (
                                "H1" if item.get("holding")
                                else "HOLDING_EJ_VERIFIERBAR"
                            )
                        record = LegalSourceRecord(
                            source_id=f"LS-{sid}-{len(records)+1:04d}",
                            source_type=result.source_type,
                            authority_level=result.authority_level,
                            court=item.get("court", ""),
                            case_number=item.get("case_number", ""),
                            reference=item.get("reference", ""),
                            date=item.get("date", ""),
                            legal_issue=rättsfråga,
                            holding=item.get("legal_issue", ""),
                            cited_law=rättsfråga,
                            official_source="VERIFIED",
                            current_status="NOT AUTOMATICALLY ASSUMED",
                            later_case_check="REQUIRED – SEARCH_10",  # RT-BQ
                            applicability_to_current_case="NOT YET ASSESSED",
                            holding_verification=holding_verification,  # RT-BP
                            blocked_from_requisites=blocked,             # RT-BO
                            search_domain="LEGAL_SEARCH",                # RT-BS
                            search_id=sid,                               # RT-BQ
                        )
                        records.append(record)
            return records
        except ImportError:
            self.log.append("[L7] deep_search_pipeline ej tillgänglig – nätverksanrop hoppas över")
            return []
        except Exception as e:
            self.log.append(f"[L7] Deep Search fel: {e}")
            return []


# ============================================================
# HUVUD-PIPELINE
# ============================================================

def _tekniskt_fel_ger_failed(kärna):
    """Steg 14: tekniskt undantag efter att CaseState skapats ger terminalt
    FAILED (aldrig HARD_STOP): matrisen markeras OGILTIG och falsifieringen
    NOT_RUN. Fel före CaseState (t.ex. ogiltig output_dir) kastas som förut.
    Domänspärr berörs inte - den ger HARD_STOP i pipelinen själv."""
    import functools

    @functools.wraps(kärna)
    def run_pipeline(*args, **kwargs) -> "CaseState":
        hållare: List[CaseState] = []
        kwargs["_hållare"] = hållare
        output_dir = kwargs.get("output_dir", args[2] if len(args) > 2 else None)
        try:
            return kärna(*args, **kwargs)
        except Exception as exc:
            if not hållare:
                raise
            cs = hållare[0]
            föregående = cs.pipeline_state.value
            cs.pipeline_state = PipelineState.FAILED
            cs.falsification_verdict = FalsificationVerdict.NOT_RUN
            cs.metadata["tekniskt_fel"] = {
                "typ": type(exc).__name__, "meddelande": str(exc),
                "tillstånd_vid_fel": föregående,
            }
            if cs.reproducibility:
                cs.reproducibility.final_state = PipelineState.FAILED.value
            print(f"[FAILED] Tekniskt fel i {föregående}: {type(exc).__name__}: {exc}")
            try:
                exportera_l16_output(
                    cs, f"# TEKNISKT FEL\n\nKörningen avbröts i {föregående}: "
                        f"{type(exc).__name__}: {exc}\n\nRekvisitmatrisen är OGILTIG; "
                        f"falsifiering NOT_RUN.\n", output_dir)
            except Exception as exp_exc:  # aldrig tyst
                cs.metadata["tekniskt_fel"]["export"] = f"{type(exp_exc).__name__}: {exp_exc}"
            return cs
    return run_pipeline


@_tekniskt_fel_ger_failed
def run_pipeline(
    root_paths: List[str],
    process_mode: ProcessMode = ProcessMode.JUDGMENT_AUDIT,
    output_dir: Optional[str] = None,
    references_dir: str = "references",
    förberett: Optional[Dict[str, Any]] = None,
    _hållare: Optional[List["CaseState"]] = None,
) -> CaseState:
    """
    Kör den fullständiga 17-lagers pipeline.
    
    Tillståndsövergångar:
    INIT → INGESTING → CLASSIFYING → CAPABILITY_MAPPING →
    RELATION_BUILDING → GATING → SUBSUMPTION →
    AUDIT_A → AUDIT_B → AUDIT_C → COUNTER_AUDIT →
    FALSIFICATION → JUDGMENT_DRAFT → SELF_HEALING → COMPLETE
    """
    # Utdatamappen måste anvisas. Defaulten var tidigare den relativa
    # sökvägen "output_v10", som landar i den katalog processen råkar stå i —
    # i praktiken produktmappen. Ett direktanrop skrev då ärendeartefakter mitt
    # i installationen, där nästa körnings hälsotest hittade dem som rester.
    # Samtliga anropare i systemet anger utdata explicit; den tysta defaulten
    # tjänade ingen och dolde var resultatet hamnade.
    if not output_dir:
        raise ValueError(
            "run_pipeline kräver output_dir. Utdata får inte skrivas till en "
            "relativ standardsökväg, eftersom den hamnar där processen råkar "
            "stå — typiskt i produktmappen."
        )

    # A1 källisolering: utdata i eller under en aktrot skulle skriva in i
    # bevismaterialet (aktens träd ändras, och nästa körning läser in
    # rapporten som en handling). consolidated_engine hade spärren; den
    # kanoniska ingången saknade den.
    _ut = os.path.realpath(os.path.abspath(output_dir))
    for _rot in root_paths or []:
        _r = os.path.realpath(os.path.abspath(_rot))
        if os.path.isfile(_r):
            continue
        if _ut == _r or _ut.startswith(_r.rstrip(os.sep) + os.sep):
            raise ValueError(
                f"Utdatamappen får inte vara eller ligga under en aktrot: {output_dir}")

    case_id = generate_case_id()
    print(f"\n{'='*60}")
    print(f"SVENSK FORENSIC COURT AUDIT ENGINE v10.3-UPDATED")
    print(f"Case ID: {case_id}")
    print(f"Mode: {process_mode.value}")
    print(f"{'='*60}\n")

    # Initiera case state
    case_state = CaseState(
        case_id=case_id,
        process_mode=process_mode,
        reproducibility=ReproducibilityRecord(record_id=case_id),
    )
    if _hållare is not None:
        _hållare.append(case_state)

    def log_transition(from_state: PipelineState, to_state: PipelineState) -> None:
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z"
        print(f"[{ts}] {from_state.value} → {to_state.value}")
        if case_state.reproducibility:
            case_state.reproducibility.state_transitions.append({
                "from": from_state.value,
                "to": to_state.value,
                "timestamp": ts,
            })

    # Kontrollera minnesbank
    mb_result = minnesbank_las(references_dir)
    print(f"[MINNESBANK] Status: {mb_result['status']}")

    # ── FAS 1: INGESTION ──────────────────────────────────────
    log_transition(PipelineState.INIT, PipelineState.INGESTING)
    case_state.pipeline_state = PipelineState.INGESTING

    ingestion_agent = IngestionAgent(case_state)
    success = ingestion_agent.ingest(root_paths)
    for line in ingestion_agent.log:
        print(line)

    if not success:
        print(f"\n[HARD STOP] Pipeline avbruten: {case_state.hard_stop_codes}")
        # Steg 14b: L0-stopp (HS01C/HS03) - terminalt HARD_STOP med samtliga
        # spärrflaggor, falsifiering NOT_RUN, och synkade artefakter på disk.
        case_state.pipeline_state = PipelineState.HARD_STOP
        case_state.hard_stop_active = True
        case_state.hard_stop_chain_abort = True
        case_state.falsification_verdict = FalsificationVerdict.NOT_RUN
        if case_state.reproducibility:
            case_state.reproducibility.final_state = case_state.pipeline_state.value
        try:
            _l0_rapport = generate_audit_report(case_state, None, "", [])
        except Exception as _rap_exc:  # aldrig tyst: orsaken skrivs i rapporten
            from hard_stop_las import SPÄRRTEXT as _st
            _l0_rapport = (f"# HARD STOP (L0)\n\n{_st}\n\nSpärrkoder: "
                           f"{[h.value for h in case_state.hard_stop_codes]}\n\n"
                           f"Full rapport kunde inte genereras: {type(_rap_exc).__name__}: {_rap_exc}\n")
        case_state.metadata["kritiska_pipelinefel"] = []
        _l0_export = exportera_l16_output(case_state, _l0_rapport, output_dir)
        case_state.metadata["export_misslyckade"] = sorted(
            k for k, v in _l0_export.items() if isinstance(v, str) and v.startswith("KAN EJ EXPORTERAS"))
        return case_state

    # ── FAS 2: CLASSIFYING ────────────────────────────────────
    log_transition(PipelineState.INGESTING, PipelineState.CLASSIFYING)
    case_state.pipeline_state = PipelineState.CLASSIFYING

    classifier = EvidenceClassifierAgent(case_state)
    classifier.classify()
    for line in classifier.log:
        print(line)

    # ── FAS 2b: CAPABILITY MAPPING ────────────────────────────
    log_transition(PipelineState.CLASSIFYING, PipelineState.CAPABILITY_MAPPING)
    case_state.pipeline_state = PipelineState.CAPABILITY_MAPPING

    capability_engine = CapabilityMapEngine(case_state)
    modules = capability_engine.map_capabilities()
    for line in capability_engine.log:
        print(line)

    # ── L1: PROCESSKLASSIFICERING ─────────────────────────────
    # Identifierar domstolsslag, instans, processlag dynamiskt från materialet
    court_type = _classify_court_from_files(case_state.files)
    case_state.court_type = court_type
    print(f"[L1] Processklassificering: {court_type.value}")
    print(f"[L1] MODE: {case_state.process_mode.value}")

    # ── MODE_ROUTER: STATE ISOLATION (Fas 2) ──────────────────
    # En körning = exakt ett MODE. Läget ändras aldrig mitt i körningen.
    if process_mode == ProcessMode.UNDEFINED:
        routed_mode, mode_notes, mode_hs = ModeRouter().route(
            case_state.files, root_paths)
        case_state.execution_mode = routed_mode
        case_state.mode_routing_notes = list(mode_notes)
        for note in mode_notes:
            print(f"[MR] {note}")
        if mode_hs is not None:
            case_state.hard_stop_codes.append(mode_hs)
            case_state.hard_stop_active = True
            print(f"[MR] {mode_hs.value} aktiverad (partiell körning)")
    else:
        # Fastställt MODE från anroparen/CLI — state isolation
        case_state.execution_mode = ExecutionMode(process_mode.value)
        print(f"[MR] MODE fastställt: {process_mode.value} (state isolation)")

    # KOMPLETTERINGSBEGÄRAN vid HS01 aktiv (RT-BA/RT-BB, FIX-G)
    if case_state.hard_stop_active:
        begaran = generera_kompletteringsbegäran(
            case_state, case_state.execution_mode)
        case_state.metadata["kompletteringsbegäran"] = begaran
        print(f"[MR] KOMPLETTERINGSBEGÄRAN genererad (RT-BA/RT-BB)")

    # ── L2: AKTENS RÅDATA – TEXTEXTRAKTION + OCR-FALLBACK ────
    extraction_results = {}
    klassificerade = []
    try:
        from document_text_extractor import DocumentTextExtractor
        from ocr_fallback import OCRFallback

        text_extractor = DocumentTextExtractor()
        ocr = OCRFallback()

        # Kör primär extraktion
        extraction_results = text_extractor.extract_all(case_state)

        # OCR-fallback för filer som gav tom output
        for file_record in case_state.files:
            result = extraction_results.get(file_record.file_id)
            if result and result.status in ("FAILED", "PARTIAL") and \
               result.char_count == 0 and "PDF" in file_record.filtyp_magic.upper():
                print(f"[L2] OCR-fallback för {file_record.file_id}")
                ocr_result = ocr.extract(file_record)
                if ocr_result.status == "SUCCESS" and ocr_result.segments:
                    extraction_results[file_record.file_id] = ocr_result
                    # Lägg till OCR-claims med PARTIALLY_AVAILABLE
                    claim_counter = len(case_state.claims) + 1
                    import datetime as _dt
                    for seg in ocr_result.segments:
                        from forensic_engine_v10_3_canonical import ClaimId, Availability
                        claim = ClaimId(
                            claim_id=f"C-{claim_counter:03d}",
                            content=seg.text[:CLAIM_MAXLÄNGD],
                            text_trunkerad=len(seg.text) > CLAIM_MAXLÄNGD,
                            source_id=file_record.file_id,
                            file_name=os.path.basename(file_record.file_path),
                            page=seg.page_or_position,
                            date="SAKNAS",
                            version="SAKNAS",
                            claim_type="CLAIM",
                            availability=Availability.PARTIALLY_AVAILABLE,
                        )
                        case_state.claims.append(claim)
                        claim_counter += 1
                    for line in ocr.log:
                        print(line)

        for line in text_extractor.log:
            print(line)
        print(
            f"[L2] Claims registrerade: {len(case_state.claims)} "
            f"[C-001–C-{len(case_state.claims):03d} | TOTALT: {len(case_state.claims)} claim_id]"
        )
        case_state.metadata["l2_extraction_results"] = {
            fid: r.to_dict() for fid, r in extraction_results.items()
        }

        # EXTRAKTIONSINTEGRITET.
        # Finns filer men inget innehåll kunde läsas ur dem är bevisunderlaget
        # inte tomt — det är OLÄST. Vanligaste orsaken är att pdftotext
        # (poppler) saknas på maskinen, varvid varje PDF ger noll tecken.
        # Utan den här kontrollen fortsatte pipelinen till COMPLETE och kunde
        # sätta en starkare slutstatus på noll underlag än på fullständigt.
        if case_state.files and not case_state.claims:
            case_state.metadata["l2_extraction_failed"] = True
            if HardStopCode.HS04 not in case_state.hard_stop_codes:
                case_state.hard_stop_codes.append(HardStopCode.HS04)
            saknar_verktyg = _pdf_verktyg_saknas(case_state)
            case_state.metadata["l2_extraction_failed_reason"] = (
                "pdftotext (poppler) saknas på maskinen – PDF-text kan ej läsas"
                if saknar_verktyg else
                "Ingen text kunde extraheras ur aktens filer"
            )
            print(
                f"[L2] HS04: {len(case_state.files)} filer inlästa men NOLL "
                f"claims extraherade – bevisunderlaget är oläst, inte tomt."
            )
            print(f"[L2] Orsak: {case_state.metadata['l2_extraction_failed_reason']}")
        registrera_steg(case_state, "L2 textextraktion", "GENOMFÖRD")
    except ImportError as e:
        print("[L2] document_text_extractor ej tillgänglig – claims förblir tomma")
        registrera_steg(case_state, "L2 textextraktion", "EJ_KÖRBAR",
                        f"modul saknas: {e}")
    except Exception as e:
        print(f"[L2] Textextraktion fel: {e}")
        registrera_steg(case_state, "L2 textextraktion", "EJ_KÖRBAR", str(e))

    # ── L2 CLAIM CLASSIFIER – semantisk juridisk klassificering ─
    try:
        from claim_classifier import ClaimClassifier
        classifier = ClaimClassifier()
        klassificerade = classifier.classify_all(case_state)
        for line in classifier.log:
            print(line)
        case_state.metadata["l2_classification"] = \
            case_state.metadata.get("claim_classification_stats", {})
        registrera_steg(case_state, "L2 claimklassificering", "GENOMFÖRD")
    except ImportError as e:
        print("[L2] claim_classifier ej tillgänglig")
        registrera_steg(case_state, "L2 claimklassificering", "EJ_KÖRBAR",
                        f"modul saknas: {e}")
    except Exception as e:
        print(f"[L2] Klassificering fel: {e}")
        registrera_steg(case_state, "L2 claimklassificering", "EJ_KÖRBAR", str(e))

    # ── L4: PARTERNAS POSITIONER ──────────────────────────────
    try:
        # förberett["l4"]: dynamic_pipeline.step_positions har redan kört
        # ProcessPositionAgent.analyze på samma akt - återanvänd i stället för
        # att analysera en andra gång (en körning, ett resultat).
        # Sammanfogade utkast (dynamic_pipeline MOD_LEGAL_MERGE) -> metadata,
        # så att presentation_views_v10.json får dem.
        if (förberett or {}).get("legal_merge"):
            case_state.metadata.update(förberett["legal_merge"])
        _f_l4 = (förberett or {}).get("l4")
        if _f_l4 is not None:
            position_result = _f_l4["result"]
            case_state.metadata.update(_f_l4.get("metadata") or {})
            print("[L4] Partspositioner återanvända från dynamic_pipeline (ingen omkörning)")
        else:
            from process_position_agent import ProcessPositionAgent
            position_agent = ProcessPositionAgent()
            position_result = position_agent.analyze(case_state, extraction_results)
            for line in position_agent.log:
                print(line)
        case_state.metadata["l4_result"] = position_result.to_dict()
        if position_result.not_verifiable_count > 0:
            # GAP 2-fix: förbjuden inferens ytliggörs explicit (RT-L → HS09)
            case_state.metadata["l4_has_forbidden_inference"] = True
            print(
                f"[L4] HS09: {position_result.not_verifiable_count} positioner "
                f"NOT_VERIFIABLE – inferens förbjuden (RT-L)"
            )
        registrera_steg(case_state, "L4 partspositioner", "GENOMFÖRD")
    except ImportError as e:
        print("[L4] process_position_agent ej tillgänglig")
        registrera_steg(case_state, "L4 partspositioner", "EJ_KÖRBAR",
                        f"modul saknas: {e}")
    except Exception as e:
        # GAP 2-fix: fel ytliggörs som violation, ej tyst sväljning
        case_state.metadata["l4_has_forbidden_inference"] = True
        print(f"[L4] HS09: Positionsanalys misslyckades – {e} (RT-L)")
        registrera_steg(case_state, "L4 partspositioner", "EJ_KÖRBAR", str(e))

    # ── L00–L02: SOCIALFÖRSÄKRINGSSPECIFIKA AUDIT-LAGER (Fas 4) ──
    # RT-CK: aktiveras automatiskt vid sjukpenning/SGI/rehabilitering/FK-måltyp.
    # RT-CL: DFA-kedjan verifieras i L01_PRIMARY_SOURCE.
    try:
        _sf_mod_dir = str(Path(__file__).resolve().parent.parent / 'moduler_och_regler')
        if Path(_sf_mod_dir).is_dir() and _sf_mod_dir not in sys.path:
            sys.path.insert(0, _sf_mod_dir)
        from socialforsakring_lager import kör_socialforsakring_lager
        sf_result = kör_socialforsakring_lager(case_state)
        if sf_result["aktiverad"]:
            print("[SF] L00–L02 aktiverade (socialförsäkringsmåltyp, RT-CK)")
            for kod, findings in sf_result["lager"].items():
                for f in findings:
                    print(f"[SF|{kod}] {f['kontrollpunkt']}: {f['status']}")
            case_state.metadata["sf_l00_l02"] = sf_result["lager"]
        else:
            print("[SF] Socialförsäkringsmåltyp ej identifierad – L00-L02 ej aktiverade")
        registrera_steg(
            case_state, "L00–L02 socialförsäkringslager",
            "GENOMFÖRD" if sf_result["aktiverad"] else "EJ_TILLÄMPLIG",
            "" if sf_result["aktiverad"]
            else "måltypen är inte en socialförsäkringsmåltyp",
        )
    except ImportError as e:
        print("[SF] socialforsakring_lager ej tillgänglig")
        registrera_steg(case_state, "L00–L02 socialförsäkringslager", "EJ_KÖRBAR",
                        f"modul saknas: {e}")
    except Exception as e:
        print(f"[SF] Socialförsäkringslager fel: {e}")
        registrera_steg(case_state, "L00–L02 socialförsäkringslager", "EJ_KÖRBAR",
                        str(e))

    # ── L1: PROCESSKLASSIFICERING ─────────────────────────────
    # Domstolsslag och processlag ur config/process_classifier.yaml. Filen
    # lästes tidigare inte av någon kod, varför samtliga ärenden rapporterade
    # court_type UNKNOWN oavsett innehåll.
    kör_processklassificering(case_state)

    # ── EXTRAKTIONSTÄCKNING ───────────────────────────────────
    # Vilka handlingar gav faktiskt text? En akt där flera handlingar är
    # skannade bilder utan textlager analyserades tidigare partiellt utan att
    # rapporten sa det.
    beräkna_extraktionstäckning(case_state)

    # ── DOKUMENTTYPNING ───────────────────────────────────────
    # Varje handling klassificeras efter typ och kategori (UTSAGA/MYNDIGHET/
    # TEKNISK). Filnamn först, annars handlingens eget innehåll — ett filnamn
    # som bara är ett myndighetsnamn säger inget om handlingstypen.
    kör_dokumenttypning(case_state)

    # ── P00: MATERIALREGISTRERING ─────────────────────────────
    # runtime/material_registry.py registrerar aktens objekt UTAN juridisk
    # kvalificering ("allt är data tills integritet och relevans passerats").
    # Modulen fanns men anropades aldrig från motorn — P00 var därmed en
    # dokumenterad princip utan exekvering. Fälten styrs av
    # config/blueprint_p00_material.yaml.
    kör_materialregistrering(case_state)

    # ── L6B: RÄTTSOMRÅDESSKANNING MOT KODTABELLER ─────────────
    # Systemet har tolv domänkodtabeller i config/kodsystem_*.yaml med lagrum
    # och mönster per rättsområde (SoL/LVU, SFB, FPL, RB tvist, hyresrätt,
    # konkurs, patientskada m.fl.). Ingen av dem anropades från den kanoniska
    # motorn — de var nåbara enbart som separata MCP-verktyg. Mätt på verkligt
    # material hittar de rätt författning (LVU-2, LVU-3, SOL-INSATS i ett
    # BBIC-ärende; RB 35:1 och 36:1 i en förundersökning) medan analysen inte
    # såg något av det. Det var en integrationsbrist, inte ett designval.
    kör_rättsområdesskanning(case_state)

    # ── L7: RÄTTSKÄLLEKONTROLL (integrerad med Deep Search) ───
    # Deep Search är verifieringsfunktion – ligger UNDER analysen
    legal_search = LegalSourceSearchIntegration(case_state)
    legal_search.run(enable_network=False)  # Nätverksanrop kräver explicit aktivering
    for line in legal_search.log:
        print(line)

    # ── FAS 3: RELATION BUILDING ──────────────────────────────
    log_transition(PipelineState.CAPABILITY_MAPPING, PipelineState.RELATION_BUILDING)
    case_state.pipeline_state = PipelineState.RELATION_BUILDING

    graph_builder = RelationGraphBuilder(case_state)
    # Strukturell filrelation ≠ innehållsmässig bevisrelation.
    # Härkomst (DERIVES_FROM) byggs här; SUPPORTS först när rekvisitmatrisen
    # finns. Ingen kant skapas utan VerbatimAnchor med ordagrant citat.
    antal_härkomst = graph_builder.build_provenance_edges()
    print(
        f"[GRAPH] Härkomstkanter byggda: {antal_härkomst} "
        f"(claim → källdokument, DERIVES_FROM)"
    )

    # FAS 3b: build_anchor prövade förhållandena vid intaget. Här prövas de mot
    # källan som den ser ut nu — filen kvar, hash oförändrad, citatet ordagrant
    # på angiven sida. Faller någon kontroll tvingas kanten UNRESOLVED.
    ankarrapport = verifiera_ankare_mot_kalla(case_state, extraction_results)
    print(
        f"[GRAPH] Ankarverifiering mot källa: {ankarrapport['prövade_ankare']} prövade, "
        f"{ankarrapport['nedgraderade']} nedgraderade"
    )
    for post in ankarrapport["detaljer"][:20]:
        print(
            f"[GRAPH]   {post['edge_id']} {post['claim_id']} → "
            f"{post['source_id']} s.{post['sida']}: {post['skäl']}"
        )

    # ── L8: REKVISITMATRIS – automatisk claim-koppling ────────
    # Måste ligga FÖRE grinden: grinden prövar matrisen, så en matris som ännu
    # inte byggts gav tidigare ett tyst PASSERAD på obefintligt underlag.
    requisite_mappings = []
    try:
        from requisite_claim_mapper import RequisiteClaimMapper
        mapper = RequisiteClaimMapper()
        requisite_mappings = mapper.map(case_state, klassificerade)
        for line in mapper.log:
            print(line)
    except ImportError:
        registrera_steg(case_state, "L8 rekvisitmappning", "EJ_KÖRBAR", "modul saknas")
        print("[L8] requisite_claim_mapper ej tillgänglig")
    except Exception as e:
        registrera_steg(case_state, "L8 rekvisitmappning", "EJ_KÖRBAR", str(e))
        print(f"[L8] Rekvisitmappning fel: {e}")

    # ── FAS 3b: SUPPORTS-kanter claim → rekvisit ──────────────
    antal_rekvisitkanter = graph_builder.build_requisite_edges(requisite_mappings)
    print(f"[GRAPH] Rekvisitkanter byggda: {antal_rekvisitkanter} (claim → rekvisit)")
    graf_stats = graph_builder.get_stats()
    print(
        f"[GRAPH] Relationsgraf klar. Totalt: {graf_stats['total_edges']} kanter "
        f"({graf_stats['verified_edges']} verifierade, "
        f"{graf_stats['unresolved_edges']} UNRESOLVED)"
    )

    # ── FAS 4: GATING ─────────────────────────────────────────
    log_transition(PipelineState.RELATION_BUILDING, PipelineState.GATING)
    case_state.pipeline_state = PipelineState.GATING

    gatekeeper = SubsumptionGatekeeper(case_state)
    gate_passed, blocking_requisites = gatekeeper.check_requisite_matrix()
    case_state.metadata["requisite_gate_passed"] = gate_passed
    for line in gatekeeper.log:
        print(line)

    if not gate_passed:
        print(f"[GATE] LEGAL_REQUISITE_GATE SPÄRRAD: {blocking_requisites}")
        # Partiellt stopp – fortsätt med aktiva lager

    # ── FAS 5: SUBSUMTION ─────────────────────────────────────
    log_transition(PipelineState.GATING, PipelineState.SUBSUMPTION)
    case_state.pipeline_state = PipelineState.SUBSUMPTION
    print("[L8.5] Subsumtion – SubsumptionGatekeeper aktiv")

    # ── L9: DOMSKÄLSMATRIS + FUP-ANALYSGREN ───────────────────
    # JUDGMENT_AUDIT med dom:  DomskälsmatrisAgent
    # JUDGMENT_AUDIT utan dom: FUPAnalysAgent (FUP-analysgren)
    # JUDGMENT_CONSTRUCTION:   DomskälsmatrisAgent (construction-gren)
    l9_fynd = []
    l9_kedjor = []

    # Kontrollera om dom finns i materialet.
    # Delsträngsökningen `"dom" in filnamn` träffade inuti "sjukdom", så en
    # forskarrapport om psykisk sjukdom fick motorn att tro att akten innehöll
    # en dom — varpå FUP-grenen och hela diskrepansanalysen stängdes av.
    try:
        from fup_analysis_agent import akten_innehåller_dom
        dom_finns = akten_innehåller_dom(case_state)
    except Exception as e:
        # Att domsdetektionen inte kunde köras är INTE detsamma som att akten
        # saknar dom. Utan den registreringen valdes L9-gren på ett antagande
        # som ingenting i akten stödde, och inget i rapporten visade det.
        dom_finns = False
        registrera_steg(case_state, "L9 domsdetektion", "EJ_KÖRBAR",
                        f"{e} — grenval gjordes på antagandet att dom saknas")

    if process_mode == ProcessMode.JUDGMENT_AUDIT and not dom_finns:
        # FUP-analysgren: ingen dom → analysera beviskedjor direkt
        print("[L9] FUP-ANALYSGREN aktiverad (dom saknas i materialet)")
        try:
            from fup_analysis_agent import FUPAnalysAgent
            from requisite_claim_mapper import RequisiteClaimMapper as _RCM
            # Identifiera måltyp för FUP-analysen
            _mapper_tmp = _RCM()
            _måltyp = _mapper_tmp.identify_måltyp_detailed(case_state).måltyp
            fup_agent = FUPAnalysAgent()
            fup_result = fup_agent.run(case_state, klassificerade, _måltyp)
            for line in fup_agent.log:
                print(line)
            case_state.metadata["l9_fup_result"] = {
                "måltyp": _måltyp,
                "obestyrkta_led": fup_result.obestyrkta_led,
                "diskrepanser": len(fup_result.diskrepanser),
                "status": fup_result.overall_status.value,
            }
            case_state.metadata["l9_status"] = "FUP_ANALYS_GENOMFÖRD"
            registrera_steg(case_state, "L9 FUP-analysgren", "GENOMFÖRD")
        except ImportError as e:
            case_state.metadata["l9_status"] = "EJ_KÖRBAR"
            print("[L9] fup_analysis_agent ej tillgänglig")
            registrera_steg(case_state, "L9 FUP-analysgren", "EJ_KÖRBAR",
                            f"modul saknas: {e}")
        except Exception as e:
            case_state.metadata["l9_status"] = "EJ_KÖRBAR"
            print(f"[L9] FUP-analys fel: {e}")
            registrera_steg(case_state, "L9 FUP-analysgren", "EJ_KÖRBAR", str(e))
    elif not (HardStopCode.HS01A in case_state.hard_stop_codes and
              process_mode == ProcessMode.JUDGMENT_AUDIT):
        if process_mode == ProcessMode.JUDGMENT_CONSTRUCTION and not gate_passed:
            case_state.metadata["l9_status"] = "SPÄRRAD_AV_REKVISITGATE"
            print("[L9] [BLOCKERAD – rekvisitgate stängd; konstruktion ej körd]")
            registrera_steg(case_state, "L9 domskälsmatris", "EJ_KÖRBAR",
                            "Subsumtionskonstruktion spärrad eftersom rekvisitgrinden inte passerades")
        else:
            case_state.metadata["l9_status"] = "GENOMFÖRD"
            # Standard domskälsmatris
            try:
                _f_l9 = (förberett or {}).get("l9")
                if _f_l9 is not None:
                    l9_fynd, l9_kedjor = list(_f_l9["fynd"]), list(_f_l9["kedjor"])
                    print("[L9] Domskälsmatris återanvänd från dynamic_pipeline L11 (ingen omkörning)")
                else:
                    from domskals_matris_agent import DomskälsmatrisAgent
                    l9_agent = DomskälsmatrisAgent()
                    l9_fynd, l9_kedjor = l9_agent.run(case_state)
                    for line in l9_agent.log:
                        print(line)
                registrera_steg(case_state, "L9 domskälsmatris", "GENOMFÖRD")
            except ImportError as e:
                case_state.metadata["l9_status"] = "EJ_KÖRBAR"
                print("[L9] domskals_matris_agent ej tillgänglig")
                registrera_steg(case_state, "L9 domskälsmatris", "EJ_KÖRBAR",
                                f"modul saknas: {e}")
            except Exception as e:
                case_state.metadata["l9_status"] = "EJ_KÖRBAR"
                print(f"[L9] Domskälsmatris fel: {e}")
                registrera_steg(case_state, "L9 domskälsmatris", "EJ_KÖRBAR", str(e))
    else:
        print("[L9] [BLOCKERAD – HS01A | Domskälsmatris kräver fullständig dom]")
        registrera_steg(case_state, "L9 domskälsmatris", "EJ_KÖRBAR",
                        "HS01A — domskälsmatris kräver fullständig dom")

    # ── AUDIT A ───────────────────────────────────────────────
    log_transition(PipelineState.SUBSUMPTION, PipelineState.AUDIT_A)
    case_state.pipeline_state = PipelineState.AUDIT_A

    audit_a = AuditAgentA(case_state)
    audit_a.run()
    for line in audit_a.log:
        print(line)

    # ── AUDIT B ───────────────────────────────────────────────
    log_transition(PipelineState.AUDIT_A, PipelineState.AUDIT_B)
    case_state.pipeline_state = PipelineState.AUDIT_B

    audit_b = AuditAgentB(case_state)
    audit_b.run()
    for line in audit_b.log:
        print(line)

    # ── AUDIT C ───────────────────────────────────────────────
    log_transition(PipelineState.AUDIT_B, PipelineState.AUDIT_C)
    case_state.pipeline_state = PipelineState.AUDIT_C

    audit_c = AuditAgentC(case_state)
    audit_c.run()
    for line in audit_c.log:
        print(line)

    # ── AGENT_C_STRESS_TEST (Adversarial Pass) ────────────────
    print("[STRESS_TEST] AGENT_C_STRESS_TEST startar (obligatorisk)")
    stress_test = AgentCStressTest(case_state)
    stress_test_result = stress_test.run()
    for line in stress_test.log:
        print(line)

    # ── COUNTER AUDIT ─────────────────────────────────────────
    log_transition(PipelineState.AUDIT_C, PipelineState.COUNTER_AUDIT)
    case_state.pipeline_state = PipelineState.COUNTER_AUDIT

    counter_audit = CounterAuditAgent(case_state)
    counter_audit.run()
    for line in counter_audit.log:
        print(line)

    # ── FALSIFICATION ─────────────────────────────────────────
    log_transition(PipelineState.COUNTER_AUDIT, PipelineState.FALSIFICATION)
    case_state.pipeline_state = PipelineState.FALSIFICATION

    falsification = FalsificationEngine(case_state)
    verdict = falsification.run()
    for line in falsification.log:
        print(line)
    print(f"[FALSIFICATION] Verdict: {verdict.value}")

    # ── JUDGMENT DRAFT ────────────────────────────────────────
    log_transition(PipelineState.FALSIFICATION, PipelineState.JUDGMENT_DRAFT)
    case_state.pipeline_state = PipelineState.JUDGMENT_DRAFT

    judgment_draft_text = None
    if process_mode == ProcessMode.JUDGMENT_CONSTRUCTION:
        draft_engine = JudgmentDraftEngine(case_state)
        judgment_draft_text = draft_engine.generate()
        for line in draft_engine.log:
            print(line)

    # ── OVERALL STATUS ────────────────────────────────────────
    case_state.overall_status = determine_overall_status(case_state)
    print(f"[L15] Slutstatus: {case_state.overall_status.value}")

    # ── AUDIT CONTROLLER ──────────────────────────────────────
    ac = AuditController(case_state)
    ac_verdict = ac.run()
    case_state.metadata["audit_controller_violations"] = list(ac.violations)
    case_state.metadata["audit_controller_p18_källa"] = ac.p18_tröskel_källa
    for line in ac.log:
        print(line)
    print(f"[AC] Audit Controller: {ac_verdict.value}")

    # ── PRESENTATION (L16) ────────────────────────────────────
    presentation_layer = PresentationLayer(case_state)
    presentation_layer.build()
    for line in presentation_layer.log:
        print(line)
    if case_state.presentation:
        cv = case_state.presentation.court_view
        print(f"[L16] Court view: {cv.get('bugs_identified_count', 0)} buggar")
        if case_state.presentation.party_a:
            print(
                f"[L16] Party A: "
                f"{len(case_state.presentation.party_a.verified_strengths)} styrkor, "
                f"{len(case_state.presentation.party_a.verified_weaknesses)} svagheter"
            )
        if case_state.presentation.party_b:
            print(
                f"[L16] Party B: "
                f"{len(case_state.presentation.party_b.verified_strengths)} styrkor, "
                f"{len(case_state.presentation.party_b.verified_weaknesses)} svagheter"
            )

    # ── SELF HEALING ──────────────────────────────────────────
    log_transition(PipelineState.JUDGMENT_DRAFT, PipelineState.SELF_HEALING)
    case_state.pipeline_state = PipelineState.SELF_HEALING

    self_healing = SelfHealingEngine(case_state)
    patches = self_healing.run()
    for line in self_healing.log:
        print(line)

    # ── COMPLETE ──────────────────────────────────────────────
    # Icke-blockerande avslut: behåll flaggor och avvikelser utan att stoppa övergången till COMPLETE.
    if case_state.hard_stop_codes or case_state.hard_stop_active:
        _koder = [getattr(h, "value", h) for h in case_state.hard_stop_codes]
        case_state.hard_stop_active = True
        _slut = PipelineState.HARD_STOP
        log_transition(PipelineState.SELF_HEALING, _slut)
        case_state.pipeline_state = _slut
        print(f"[HARD_STOP] Analys avbruten vid aktiva spärrflaggor: {_koder}")
    else:
        _slut = PipelineState.COMPLETE
        log_transition(PipelineState.SELF_HEALING, _slut)
        case_state.pipeline_state = _slut

    if case_state.reproducibility:
        case_state.reproducibility.final_state = _slut.value

    # ── RAPPORT OCH EXPORT ────────────────────────────────────
    report_text = generate_audit_report(
        case_state, stress_test_result, judgment_draft_text, patches
    )
    _tomma = kontrollera_tom_export(case_state)
    export_results = exportera_l16_output(case_state, report_text, output_dir)
    if kontrollera_tom_export(case_state, output_dir, export_results) != _tomma:
        # Fil-nivåns fynd ska finnas i de skrivna artefakterna.
        export_results = exportera_l16_output(case_state, report_text, output_dir)

    # En artefakt som inte kunde skrivas registrerades tidigare ingenstans.
    # Raderna nedan namngav ändå rapport- och case state-filen som om de fanns,
    # och CaseState bar inget spår av att exporten fallerat. Operatören fick
    # alltså en sökväg till en fil som inte existerade.
    misslyckade_exporter = {
        namn: värde for namn, värde in (export_results or {}).items()
        if isinstance(värde, str) and värde.startswith("KAN EJ EXPORTERAS")
    }
    for namn, värde in misslyckade_exporter.items():
        registrera_steg(case_state, f"L16 export: {namn}", "EJ_KÖRBAR", värde)
    case_state.metadata["export_misslyckade"] = sorted(misslyckade_exporter)

    print(f"\n[OUTPUT] Export: {export_results}")
    print(f"[COMPLETE] Pipeline klar. Status: {case_state.overall_status.value}")
    if misslyckade_exporter:
        print(
            f"[COMPLETE] VARNING: {len(misslyckade_exporter)} artefakt(er) "
            f"kunde inte skrivas: {', '.join(sorted(misslyckade_exporter))}"
        )
    for artefakt, nyckel in (("audit_report_v10.md", "markdown"),
                             ("case_state_v10.json", "json")):
        if nyckel in misslyckade_exporter:
            print(f"[COMPLETE] {artefakt}: SKREVS INTE")
        else:
            print(f"[COMPLETE] {os.path.join(output_dir, artefakt)}")

    # Bristrapport (runtime/bristrapport.py) — aggregerar redan beräknade
    # fynd (hard stops, audit-fynd, ofullständiga steg, olösta bevisked-
    # jor) till en samlad förteckning. Körs före kvalitetskontroll, som
    # läser case_state.metadata["bristrapport"] för sin kritiska-brister-kontroll.
    try:
        from bristrapport import generera_bristrapport
        bristrapport_resultat = generera_bristrapport(case_state)
        case_state.metadata["bristrapport"] = bristrapport_resultat
        print(f"[COMPLETE] Bristrapport: {bristrapport_resultat['status']}")
    except Exception as e:
        print(f"[COMPLETE] Bristrapport kunde inte genereras: {type(e).__name__}: {e}")

    # Obligatorisk slutkontroll (runtime/kvalitetskontroll.py) — prövar
    # pipelinens EGEN interna konsistens (hard-stop/verdict-motsägelser,
    # olösta kritiska brister, uteblven falsifiering), inte innehållets
    # juridiska korrekthet.
    try:
        from kvalitetskontroll import kör_kvalitetskontroll
        kvalitetskontroll_resultat = kör_kvalitetskontroll(case_state)
        case_state.metadata["kvalitetskontroll"] = kvalitetskontroll_resultat
        print(f"[COMPLETE] Kvalitetskontroll: {kvalitetskontroll_resultat['status']}")
    except Exception as e:
        print(f"[COMPLETE] Kvalitetskontroll kunde inte köras: {type(e).__name__}: {e}")

    return case_state


# ============================================================
# TESTSVIT
# ============================================================

def _kräv(villkor: bool, beskrivning: str) -> None:
    """
    Prövar ett kontrakt i testsviten nedan.

    Kontrollerna var assert-satser. Python tar bort varje assert-sats när
    tolken körs med -O, och då kunde testfallens try-kroppar inte längre
    falla: samtliga fem rapporterade GODKÄND utan att ha prövat någonting.
    Hälsotestets kontroll 13 kör just denna svit och hade därmed varit grön
    på tom grund i optimerat läge.

    AssertionError behålls som feltyp, eftersom testfallen skiljer ett brutet
    kontrakt (FEL) från ett oväntat undantag (BUGG) på just den typen.
    """
    if not villkor:
        raise AssertionError(beskrivning)


def subagent_testsvit() -> Dict[str, str]:
    """
    Kör testsvit T-01–T-05 (ÄNDRING-005).
    Returnerar resultat per testfall.

    Kontrollerna sker med _kräv, inte assert, så att sviten inte kan bli
    innehållslös under -O. Se _kräv.
    """
    results = {}

    # T-01: tom ärendelista ger HS01C — inte en tyst genomförd körning.
    # Testet kontrollerade tidigare endast att inget undantag kastades och
    # var därför alltid grönt, även när ingestionen släppte igenom en tom akt.
    try:
        cs = CaseState(case_id="TEST-001")
        agent = IngestionAgent(cs)
        ok = agent.ingest([])  # Tom lista – inga filer
        _kräv(ok is False,
              'tom akt får inte rapporteras som lyckad ingestion')
        _kräv(HardStopCode.HS01C in cs.hard_stop_codes,
              'HS01C sattes inte')
        _kräv(cs.hard_stop_active is True,
              'hard_stop_active sattes inte')
        _kräv(cs.overall_status == AuditStatus.I,
              'slutstatus ska vara I')
        results["T-01"] = "GODKÄND"
    except AssertionError as e:
        results["T-01"] = f"FEL: {e}"
    except Exception as e:
        results["T-01"] = f"BUGG: {e}"

    # T-02: obefintlig sökväg får inte krascha, men inte heller passera tyst.
    try:
        cs = CaseState(case_id="TEST-002")
        agent = IngestionAgent(cs)
        ok = agent.ingest(["/sökväg/som/inte/finns"])
        _kräv(ok is False,
              'obefintlig rot får inte ge lyckad ingestion')
        _kräv(HardStopCode.HS01C in cs.hard_stop_codes,
              'HS01C sattes inte')
        _kräv(any(('finns inte' in rad for rad in agent.log)),
              'den obefintliga sökvägen redovisas inte i loggen')
        results["T-02"] = "GODKÄND"
    except AssertionError as e:
        results["T-02"] = f"FEL: {e}"
    except Exception as e:
        results["T-02"] = f"BUGG: {e}"

    # T-03: A, B och C ska ACKUMULERA fynd, inte skriva över varandra.
    # Agenterna tilldelade tidigare listorna med =, varpå ett senare lagers
    # resultat raderade ett tidigare lagers fynd utan spår.
    try:
        cs = CaseState(case_id="TEST-003")
        markör = AuditFinding(
            finding_id="T03-MARKÖR", agent="A",
            description="Fixturfynd som ska överleva efterföljande lager.",
            source_ref="TEKNISK_FIXTUR", severity="LÅG",
        )
        cs.audit_a_findings.append(markör)
        AuditAgentA(cs).run()
        AuditAgentB(cs).run()
        AuditAgentC(cs).run()
        _kräv(markör in cs.audit_a_findings,
              'tidigare fynd skrevs över av ett senare auditlager')
        results["T-03"] = "GODKÄND"
    except AssertionError as e:
        results["T-03"] = f"FEL: {e}"
    except Exception as e:
        results["T-03"] = f"BUGG: {e}"

    # T-04: Minnesbank-subagent returnerar DISABLED eller ACTIVE
    try:
        result = minnesbank_kontroll("/sökväg/som/inte/finns")
        _kräv(result['status'] in ['DISABLED', 'ACTIVE'],
              "kontraktet höll inte: result['status'] in ['DISABLED', 'ACTIVE']")
        results["T-04"] = "GODKÄND"
    except Exception as e:
        results["T-04"] = f"BUGG: {e}"

    # T-05: Tom Audit-agent A ger [INGA AVVIKELSER]-rapport
    try:
        cs = CaseState(case_id="TEST-005")
        agent = AuditAgentA(cs)
        findings = agent.run()
        _kräv(len(findings) == 0,
              'kontraktet höll inte: len(findings) == 0')
        _kräv(any(('INGA AVVIKELSER' in line for line in agent.log)),
              "kontraktet höll inte: any(('INGA AVVIKELSER' in line for line in agent.log))")
        results["T-05"] = "GODKÄND"
    except Exception as e:
        results["T-05"] = f"BUGG: {e}"

    return results


# ============================================================
# ENTRYPOINT
# ============================================================

def main() -> None:
    """CLI-entrypoint för forensic_engine_v10.3-canonical.py."""
    import argparse

    parser = argparse.ArgumentParser(
        description="SVENSK FORENSIC COURT AUDIT ENGINE v10.3-UPDATED"
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Sökvägar till ärendemappar eller filer",
    )
    parser.add_argument(
        "--mode",
        choices=["JUDGMENT_AUDIT", "JUDGMENT_CONSTRUCTION"],
        default="JUDGMENT_AUDIT",
        help="Exekveringsläge (default: JUDGMENT_AUDIT)",
    )
    _default_out = str(Path(__file__).resolve().parent.parent / "output")
    parser.add_argument(
        "--output",
        default=_default_out,
        help=f"Outputmapp (default: {_default_out})",
    )
    parser.add_argument(
        "--references",
        default="references",
        help="Minnesbank-mapp (default: references)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Kör testsvit T-01–T-05",
    )

    args = parser.parse_args()

    if args.test:
        print("Kör testsvit T-01–T-05...")
        results = subagent_testsvit()
        godkanda = sum(1 for v in results.values() if v == "GODKÄND")
        buggar = sum(1 for v in results.values() if v != "GODKÄND")
        for test_id, result in sorted(results.items()):
            print(f"  {test_id}: {result}")
        print(f"\nTOTAL GODKÄNDA: {godkanda} | BUGGAR: {buggar}")
        return

    if not args.paths:
        print("Användning: python forensic_engine_v10_3_canonical.py <sökväg> [--mode MODE]")
        print("           python forensic_engine_v10_3_canonical.py --test")
        sys.exit(1)

    mode = ProcessMode[args.mode]
    run_pipeline(
        root_paths=args.paths,
        process_mode=mode,
        output_dir=args.output,
        references_dir=args.references,
    )


if __name__ == "__main__":
    main()
