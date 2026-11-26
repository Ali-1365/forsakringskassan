# SFCAE-BINDNING: motor_c_v10_v3
# Roll: Alt B — Motor C (v10.3 Relation-Driven Case State Machine), parallell valideringsmotor
# Producerar aldrig domslut. INDIKATIV_ENDAST.
# PORTERAD 2026-10-09 från C:\AI_Projects\sfcae_nymapp_karantan_2026-09-24\Ny mapp\forensic_engine_v10-v3.py
# (178 866 B, nyaste kända versionen; äldre: SKILL_Olika.zip KONSOLIDERAD_ARKITEKTUR 174 985 B).
# Bevarar unik funktionalitet som saknades i sfcae: CaseStateMachine (21 tillstånd),
# HoldingChainValidator, LegalRequisiteGate, UnsolicitedValidationAgent,
# BidirectionalAuditEngine, PreTrialObjectives. ERSÄTTER INTE canonical — körs
# endast med requested=True via run_motor_c_if_requested().
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  FORENSIC COURT AUDIT ENGINE v10.3                                          ║
║  Relation-Driven Case State Machine + Self-Healing Audit Loop               ║
║                                                                              ║
║  Arkitektur: A-Blueprint_DOMSTOL_Arkitekt-Dynamit.md (v10)                  ║
║  Metod:      Regelbaserad textklassificering för svenska juridiska          ║
║              dokument (regex/nyckelordsmatchning). Ingen standard-          ║
║              certifiering och ingen maskininlärning — se LIMITATIONS.md.    ║
║                                                                              ║
║  v10 NYA KOMPONENTER (uppgradering från v9.9.0):                            ║
║    MachineState          → Guarded state-transitions (ej linjär pipeline)   ║
║    VerbatimAnchor        → Obligatorisk exakt citatkoppling per graf-kant    ║
║    RelationGraph         → Typad grafstruktur med 10 kanttyper               ║
║    SubsumptionGatekeeper → Hård grind — karantänfiler BLOCKERAS              ║
║    CapabilityMapEngine   → Dynamisk modulaktivering per materialklass        ║
║    BidirectionalAudit    → DOM→KÄLLA + KÄLLA→DOM + KÄLLA↔KÄLLA              ║
║    AuditAgent A/B/C      → Falsifiering / Verifiering / Second-order        ║
║    FalsificationEngine   → Bygger starkaste motkedja — HARD STOP krävs      ║
║    JudgmentDraftEngine   → PROVISIONAL ONLY — aldrig dömande mandat         ║
║    SelfHealingEngine     → Logiska glapp → inverterade säkerhetsregler       ║
║    ReproducibilityRecord → Komplett spårlogg med käll-hashes                ║
║                                                                              ║
║  ABSOLUTA SPÄRRAR (invariant kärna):                                        ║
║    INGEN HÅRDKODAD MÅLTYP / JURIDISK SLUTSATS                               ║
║    INGEN GRAFKANT UTAN VERBATIM-ANKARE                                      ║
║    INGEN SUBSUMTION UTAN GATEKEEPER-GODKÄNNANDE                             ║
║    INGEN SLUTSATS ROBUST UTAN KOLLAPSAD MOTKEDJA                            ║
║    ALDRIG DÖMANDE MANDAT — PROVISIONAL JUDGMENT DRAFT ENDAST               ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import re
import time
import uuid
import logging
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# LOGGNING
# ─────────────────────────────────────────────────────────────────────────────
# SFCAE-PORT: logging.basicConfig() togs bort — en importerad modul får inte
# skriva om värdprocessens globala loggkonfiguration (CLI/MCP/stdio).
log = logging.getLogger("FORENSIC_v10_v3")

MOTOR_VERSION   = "10.3"
SCAN_TIMESTAMP  = datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# VALFRI INTEGRATION: DEEP_SEARCH_PIPELINE (rättskällesökning, v9.8.1)
# Motorn får ALDRIG krascha bara för att sökmodulen saknas eller är
# nätverkslös. Om importen misslyckas inaktiveras LEGAL_SOURCE-verifiering
# och detta registreras i reproducerbarhetsdatan, INTE tystas ner.
# ─────────────────────────────────────────────────────────────────────────────
# Säkerställ att scripts/-katalogen finns på sys.path (sibling-import)
_scripts_dir = str(Path(__file__).resolve().parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

def _redan_laddad(filnamn: str, standardnamn: str):
    """En fil, en modul: återanvänd modulen om filen redan laddats under
    ett annat namn (t.ex. dynamic_pipeline:s sfcae_dsp/sfcae_evcat) i stället
    för att ladda samma fil en gång till under ett nytt namn."""
    import importlib
    mål = (Path(__file__).resolve().parent / filnamn).resolve()
    for _m in list(sys.modules.values()):
        _f = getattr(_m, "__file__", None)
        if _f:
            try:
                if Path(_f).resolve() == mål:
                    return _m
            except (OSError, ValueError):
                continue
    return importlib.import_module(standardnamn)


try:
    _kör_deep_search = _redan_laddad("deep_search_pipeline.py",
                                     "deep_search_pipeline").kör_deep_search_pipeline
    DEEP_SEARCH_AVAILABLE = True
except Exception as _e:  # ImportError, saknade beroenden (requests m.fl.)
    _kör_deep_search = None
    DEEP_SEARCH_AVAILABLE = False
    log.warning(f"[DEEP_SEARCH] Ej tillgänglig — LEGAL_SOURCE inaktiverad ({_e})")

# ─────────────────────────────────────────────────────────────────────────────
# VALFRI INTEGRATION: EVIDENCE_CATEGORIZER (filnamn/sökvägsbaserad strukturering)
# Körs under CLASSIFYING. Om importen misslyckas fortsätter pipelinen utan
# namnbaserad kategorisering — aldrig krasch.
# ─────────────────────────────────────────────────────────────────────────────
try:
    # SFCAE-PORT: sfcae:s evidence_categorizer har kategorisera_fil(filnamn,
    # relativ_sökväg) och saknar _analysera_kausalsamband (som även i källan
    # var en stub som returnerade None). Ett saknat valfritt namn får inte
    # stänga av hela kategoriseringen.
    _ec_mod = _redan_laddad("evidence_categorizer.py", "evidence_categorizer")

    def _kategorisera_fil(abs_p, root):
        _abs = Path(abs_p)
        try:
            _rel = str(_abs.resolve().relative_to(Path(root).resolve()))
        except ValueError:
            _rel = _abs.name
        post = _ec_mod.kategorisera_fil(_abs.name, _rel)
        _pr = getattr(post, "processuell_relevans", None)
        if isinstance(_pr, str):
            post.processuell_relevans = [_pr] if _pr else []
        if not getattr(post, "sokvag", ""):
            post.sokvag = _rel
        return post

    _skanna_ärendemapp = getattr(_ec_mod, "skanna_ärendemapp", None)
    _kat_exportera_json = getattr(_ec_mod, "exportera_json", None)
    _kat_exportera_markdown = getattr(_ec_mod, "exportera_markdown", None)
    _kat_kausal = getattr(_ec_mod, "_analysera_kausalsamband", None)
    EVIDENCE_CATEGORIZER_AVAILABLE = True
except Exception as _e:
    _kategorisera_fil = None
    _skanna_ärendemapp = None
    _kat_exportera_json = None
    _kat_exportera_markdown = None
    _kat_kausal = None
    EVIDENCE_CATEGORIZER_AVAILABLE = False
    log.warning(f"[EVIDENCE_CATEGORIZER] Ej tillgänglig ({_e})")


# ─────────────────────────────────────────────────────────────────────────────
# MASKIN-TILLSTÅND  (v10 State Machine — ej linjär pipeline)
# ─────────────────────────────────────────────────────────────────────────────
class MachineState(str, Enum):
    """
    Guarded state-transitions. En övergång sker ALDRIG
    utan att föregående grind godkänts.
    """
    INIT               = "INIT"
    INGESTING          = "INGESTING"
    CLASSIFYING        = "CLASSIFYING"
    MODE_ROUTING       = "MODE_ROUTING"            # v10-v3 ModeRouter
    UNSOLICITED_VALIDATION = "UNSOLICITED_VALIDATION"  # v10-v3 sexstegs karantän
    PRE_TRIAL_OBJECTIVES = "PRE_TRIAL_OBJECTIVES"
    CAPABILITY_MAPPING = "CAPABILITY_MAPPING"
    RELATION_BUILDING  = "RELATION_BUILDING"
    GATING             = "GATING"
    SUBSUMPTION        = "SUBSUMPTION"
    LEGAL_REQUISITE_GATE = "LEGAL_REQUISITE_GATE"  # v10-v3 HS11
    AUDIT_A            = "AUDIT_A"
    AUDIT_B            = "AUDIT_B"
    AUDIT_C            = "AUDIT_C"
    FALSIFICATION      = "FALSIFICATION"
    JUDGMENT_DRAFT     = "JUDGMENT_DRAFT"
    PRESENTATION       = "PRESENTATION"            # v10-v3 Court/Party/Mediation
    SELF_HEALING       = "SELF_HEALING"
    COMPLETE           = "COMPLETE"
    HARD_STOP          = "HARD_STOP"


# ─────────────────────────────────────────────────────────────────────────────
# STATUS-ENUMERATIONER
# ─────────────────────────────────────────────────────────────────────────────
class BaselineState(str, Enum):
    LOCKED_BASELINE   = "LOCKED_BASELINE"
    UNSOLICITED_INPUT = "UNSOLICITED_INPUT"
    UNVERIFIED        = "UNVERIFIED"


class ProceduralStatus(str, Enum):
    OFFICIALLY_SUBMITTED = "OFFICIALLY_SUBMITTED"
    NOT_YET_PLEADED      = "NOT_YET_PLEADED"
    DISPUTED             = "DISPUTED"
    UNKNOWN              = "UNKNOWN"


class EvidenceCategory(str, Enum):
    A_STRONG     = "A_STRONG"
    B_RISK       = "B_RISK"
    UNCLASSIFIED = "UNCLASSIFIED"


class IntegrityStatus(str, Enum):
    VERIFIED          = "VERIFIED"
    MODIFIERAD        = "MODIFIERAD"
    KAN_EJ_VERIFIERAS = "KAN EJ VERIFIERAS"


class EdgeType(str, Enum):
    """
    Alla kanttyper i relationsgrafen (avsnitt 15 i blueprinten).
    Varje kant KRÄVER VerbatimAnchor — ingen undantag.
    """
    SUPPORTS     = "SUPPORTS"
    CONTRADICTS  = "CONTRADICTS"
    DERIVES_FROM = "DERIVES_FROM"
    REQUIRES     = "REQUIRES"
    DEPENDS_ON   = "DEPENDS_ON"
    REFERS_TO    = "REFERS_TO"
    QUALIFIES    = "QUALIFIES"
    INVALIDATES  = "INVALIDATES"
    OMITS        = "OMITS"
    UNRESOLVED   = "UNRESOLVED"


class NodeType(str, Enum):
    FILE_RECORD   = "FILE_RECORD"
    LEGAL_FACT    = "LEGAL_FACT"
    EVIDENCE_ITEM = "EVIDENCE_ITEM"
    LEGAL_RULE    = "LEGAL_RULE"
    REQUISITE     = "REQUISITE"
    CLAIM         = "CLAIM"
    JUDGMENT_PART = "JUDGMENT_PART"
    SUBSUMPTION   = "SUBSUMPTION"


class SlutStatus(str, Enum):
    A = "A: VERIFIERAD"
    B = "B: DELVIS_VERIFIERAD"
    C = "C: TVISTIGT"
    D = "D: OBESTRITT_EJ_VERIFIERAT"
    E = "E: KAN_EJ_AVGÖRAS"
    F = "F: MÖJLIGT_FAKTAFEL"
    G = "G: MÖJLIGT_RÄTTSFEL"
    H = "H: BEVISNING_SAKNAS"
    I = "I: HARD_STOP"


class FalsificationVerdict(str, Enum):
    ROBUST           = "ROBUST"           # Motkedja kollapsade i HARD_STOP
    VULNERABLE       = "VULNERABLE"       # Motkedja håller — slutsatsen ej robust
    INCONCLUSIVE     = "INCONCLUSIVE"     # Otillräckligt underlag för falsifiering
    NOT_RUN          = "NOT_RUN"



class ExecutionMode(str, Enum):
    """Tvåspårigt exekveringsflöde (v10-v3)."""
    JUDGMENT_AUDIT        = "JUDGMENT_AUDIT"
    JUDGMENT_CONSTRUCTION = "JUDGMENT_CONSTRUCTION"
    UNDETERMINED          = "UNDETERMINED"


class HardStopCode(str, Enum):
    """Kodade hårdstopp (v10-v3)."""
    HS01A = "HS01A: JUDGMENT_AUDIT saknar identifierbar tidigare dom/beslut"
    HS01C = "HS01C: Otillräckligt underlag för JUDGMENT_CONSTRUCTION"
    HS11  = "HS11: Subsumtionskedja saknar verifierat rättsfaktum (MUST-rekvisit)"


class RequisiteStatus(str, Enum):
    REKVISIT_UPPFYLLT = "REKVISIT_UPPFYLLT"
    OBESTRITT         = "OBESTRITT"
    TVISTIGT          = "TVISTIGT"
    NOT_VERIFIABLE    = "NOT_VERIFIABLE"
    BEVISNING_SAKNAS  = "BEVISNING_SAKNAS"


class HoldingLevel(str, Enum):
    H1_DIREKT      = "H1_DIREKT"
    H2_STRUKTURELL = "H2_STRUKTURELL"
    H3_ALTERNATIV  = "H3_ALTERNATIV"
    EJ_VERIFIERAD  = "EJ_VERIFIERAD"


class BugCode(str, Enum):
    """Porterat från recursive_evidence_vault_manager.py v9.9.0 (CounterAuditAgent)."""
    B01 = "B01: DATAINTEGRITET"
    B02 = "B02: KÄLLFEL"
    B03 = "B03: TIDSFEL"
    B04 = "B04: IDENTITETSFEL"
    B05 = "B05: FAKTAAVVIKELSE"
    B06 = "B06: BEVISAVVIKELSE"
    B07 = "B07: UTELÄMNANDE"
    B08 = "B08: PROCESSFEL"
    B09 = "B09: RÄTTSKÄLLEFEL"
    B10 = "B10: REKVISITFEL"
    B11 = "B11: SUBSUMTIONSFEL"
    B12 = "B12: DOMSKÄLSFEL"
    B13 = "B13: BEVISBÖRDEFEL"
    B14 = "B14: INTERN MOTSÄGELSE"
    B15 = "B15: OUPPLÖST FRÅGA"


class CapabilityModule(str, Enum):
    DOCUMENT_FORENSICS   = "DOCUMENT_FORENSICS"
    AUDIO_FORENSICS      = "AUDIO_FORENSICS"
    VIDEO_FORENSICS      = "VIDEO_FORENSICS"
    METADATA_FORENSICS   = "METADATA_FORENSICS"
    TECHNICAL_ANALYSIS   = "TECHNICAL_ANALYSIS"
    FINANCIAL_ANALYSIS   = "FINANCIAL_ANALYSIS"
    MEDICAL_ANALYSIS     = "MEDICAL_ANALYSIS"
    ADMINISTRATIVE       = "ADMINISTRATIVE"
    LEGAL_SOURCE         = "LEGAL_SOURCE"
    PROCEDURAL           = "PROCEDURAL"
    JUDGMENT_AUDIT       = "JUDGMENT_AUDIT"


# ─────────────────────────────────────────────────────────────────────────────
# VERBATIM ANCHOR — Kärnan i anti-hallucinations-arkitekturen
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class VerbatimAnchor:
    """
    OBLIGATORISK koppling per grafkant.
    Ingen kant i RelationGraph skapas utan ett exakt, ordagrant citat
    från en verifierbar primärkälla.

    Saknas citat → edge_type TVINGAS till UNRESOLVED.
    Denna regel är INTE förhandlingsbar.
    """
    source_id:      str   # Fil-ID eller DOK-ID
    source_path:    str   # Relativ sökväg
    source_hash:    str   # SHA-256 (chain of custody)
    page_or_time:   str   # Sida, rad eller [HH:MM:SS.mmm]
    verbatim_quote: str   # Ordagrann text — ALDRIG parafras
    verified:       bool  # True endast om hash är bekräftad

    def is_valid(self) -> bool:
        """En ankare är giltig om den har citat + verifierad hash."""
        return (
            bool(self.verbatim_quote.strip())
            and self.verbatim_quote != "[SAKNAR CITAT]"
            and self.verified
            and self.source_hash not in ("KAN EJ VERIFIERAS", "")
        )

    @classmethod
    def missing(cls, source_id: str, source_path: str) -> "VerbatimAnchor":
        """Skapar en ogiltig ankare — tvingar kanten till UNRESOLVED."""
        return cls(
            source_id=source_id,
            source_path=source_path,
            source_hash="KAN EJ VERIFIERAS",
            page_or_time="OKÄND",
            verbatim_quote="[SAKNAR CITAT]",
            verified=False,
        )


# ─────────────────────────────────────────────────────────────────────────────
# RELATION GRAPH — Noder och kanter
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class GraphNode:
    node_id:   str
    node_type: str          # NodeType
    label:     str
    source_id: str
    metadata:  Dict = field(default_factory=dict)


@dataclass
class GraphEdge:
    """
    En kant i relationsgrafen.
    edge_type sätts AUTOMATISKT till UNRESOLVED om ankaren är ogiltig.
    """
    edge_id:    str
    from_node:  str
    to_node:    str
    edge_type:  str         # EdgeType — kan åsidosättas till UNRESOLVED
    anchor:     VerbatimAnchor
    confidence: str = "KAN EJ VERIFIERAS"
    notes:      str = ""

    def __post_init__(self):
        """Tvinga UNRESOLVED vid ogiltig ankare."""
        if not self.anchor.is_valid():
            self.edge_type = EdgeType.UNRESOLVED
            self.confidence = "KAN EJ VERIFIERAS"
            self.notes += " [TVINGAD TILL UNRESOLVED — VERBATIM-ANKARE SAKNAS]"


@dataclass
class RelationGraph:
    """Relationsgrafen — systemets centrala datastruktur i v10."""
    nodes: Dict[str, GraphNode] = field(default_factory=dict)
    edges: List[GraphEdge]      = field(default_factory=list)
    unresolved_count: int       = 0
    verified_count:   int       = 0

    def add_node(self, node: GraphNode):
        self.nodes[node.node_id] = node

    def add_edge(self, edge: GraphEdge):
        """Lägger till kanten och uppdaterar statistik."""
        self.edges.append(edge)
        if edge.edge_type == EdgeType.UNRESOLVED:
            self.unresolved_count += 1
        else:
            self.verified_count += 1

    def get_edges_from(self, node_id: str) -> List[GraphEdge]:
        return [e for e in self.edges if e.from_node == node_id]

    def get_edges_to(self, node_id: str) -> List[GraphEdge]:
        return [e for e in self.edges if e.to_node == node_id]

    def contradiction_pairs(self) -> List[Tuple[GraphEdge, GraphEdge]]:
        """Returnerar alla par av motstridiga kanter."""
        pairs = []
        for e in self.edges:
            if e.edge_type == EdgeType.CONTRADICTS:
                # Sök efter SUPPORTS-kant i motsatt riktning
                for e2 in self.edges:
                    if (e2.from_node == e.to_node
                            and e2.to_node == e.from_node
                            and e2.edge_type == EdgeType.SUPPORTS):
                        pairs.append((e, e2))
        return pairs

    def summary(self) -> Dict:
        return {
            "total_nodes":     len(self.nodes),
            "total_edges":     len(self.edges),
            "verified_edges":  self.verified_count,
            "unresolved_edges": self.unresolved_count,
            "pct_verified":    (
                f"{self.verified_count / max(len(self.edges), 1):.0%}"
            ),
            "contradictions":  len(self.contradiction_pairs()),
        }


# ─────────────────────────────────────────────────────────────────────────────
# METADATA RECORD (fältnamn med ISO 27037-inspirerad terminologi; ej en certifierad implementation)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class MetadataRecord:
    fil:             str = ""
    käll_id:         str = ""
    skapad:          str = "KAN EJ VERIFIERAS"
    ändrad:          str = "KAN EJ VERIFIERAS"
    storlek_bytes:   int = 0
    filtyp_magic:    str = "KAN EJ VERIFIERAS"
    hash_sha256:     str = "KAN EJ VERIFIERAS"
    hash_md5:        str = "KAN EJ VERIFIERAS"
    integritet:      str = IntegrityStatus.KAN_EJ_VERIFIERAS
    modifieringstyp: str = "OFÖRÄNDRAD"
    avvikelser:      List[str] = field(default_factory=list)


@dataclass
class FileRecord:
    file_id:           str = ""
    relative_path:     str = ""
    absolute_path:     str = ""
    filename:          str = ""
    extension:         str = ""
    folder_depth:      int = 0
    context_tags:      List[str] = field(default_factory=list)
    baseline_state:    str = BaselineState.UNVERIFIED
    procedural_status: str = ProceduralStatus.UNKNOWN
    quarantine_flag:   bool = False
    evidence_category: str = EvidenceCategory.UNCLASSIFIED
    metadata:          MetadataRecord = field(default_factory=MetadataRecord)
    gatekeeper_passed: bool = False   # v10: SubsumptionGatekeeper
    slutstatus:        str = SlutStatus.E
    avvikelser:        List[str] = field(default_factory=list)
    # Namnbaserad kategorisering (evidence_categorizer) — endast filnamn/sökväg
    name_kategori:         str = "Ej identifierad"
    name_status:           str = "Ej verifierad"
    processuell_relevans:  List[str] = field(default_factory=list)
    beviskedje_funktion:   str = ""
    atgard_prioritet:      int = 3
    matchade_termer:       List[str] = field(default_factory=list)
    extraherat_datum:      Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# SUBSUMTION & DOMSUTKAST
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class SubsumptionRecord:
    """
    Explicit subsumtionskedja: Rättsregel→Rekvisit→Rättsfaktum→Bevis→Status.
    Systemet får INTE hoppa direkt från fakta till slutsats.
    """
    sub_id:        str = ""
    legal_rule:    str = "EJ IDENTIFIERAD"
    requisite:     str = "EJ IDENTIFIERAD"
    legal_fact:    str = "EJ IDENTIFIERAD"
    evidence_id:   str = ""
    anchor:        Optional[VerbatimAnchor] = None
    status:        str = "UNRESOLVED"  # UPPFYLLT | EJ_UPPFYLLT | UNRESOLVED
    legal_consequence: str = "KAN EJ AVGÖRAS"
    notes:         str = ""


@dataclass
class JudgmentDraftSection:
    """
    P18 Symmetriregeln: Domskälen MÅSTE redovisa BÅDE stärkande
    och friande/motsägande omständigheter med identisk analytisk rigor.
    """
    section_id:            str = ""
    yrkande:               str = ""
    grunder:               List[str] = field(default_factory=list)
    stärkande_omständigheter: List[str] = field(default_factory=list)
    friande_omständigheter:   List[str] = field(default_factory=list)
    subsumtioner:          List[SubsumptionRecord] = field(default_factory=list)
    provisional_conclusion: str = "UNRESOLVED — OTILLRÄCKLIGT UNDERLAG"
    symmetry_verified:     bool = False
    mandate_warning:       str = (
        "ABSOLUT FÖRBUD: Detta är ett PROVISORISKT UTKAST. "
        "AI:n saknar dömande mandat. Domstolen avgör självständigt."
    )


# ─────────────────────────────────────────────────────────────────────────────
# SELF-HEALING PATCH
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class SelfHealingPatch:
    """
    Identifierat logiskt glapp → inverterad säkerhetsregel.
    Patcharna skapar REPRODUCIBILITY_RECORD som del av spårloggen.
    """
    patch_id:    str = ""
    trigger:     str = ""       # Vad utlöste patchern
    gap_found:   str = ""       # Identifierat glapp
    rule_added:  str = ""       # Inverterad säkerhetsregel
    severity:    str = "MEDEL"  # LÅG | MEDEL | HÖG | KRITISK
    timestamp:   str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class BugReport:
    """
    Identifierad avvikelse från CounterAuditAgent (porterat från v9.9.0).
    Kompletterar Agent A/B/C med konkreta, kodade fynd (B01–B15).
    """
    bug_id:         str = ""
    bug_kod:        str = ""
    beskrivning:    str = ""
    fil:            str = ""
    allvarlighet:   str = "MEDEL"  # LÅG | MEDEL | HÖG | KRITISK
    rekommendation: str = ""


@dataclass
class ReproducibilityRecord:
    """
    Komplett spårlogg. Alla körningsteg registreras.
    Möjliggör reproducerbar verifiering av hela analysen.
    """
    record_id:         str = ""
    engine_version:    str = MOTOR_VERSION
    scan_timestamp:    str = SCAN_TIMESTAMP
    root_hash:         str = "KAN EJ VERIFIERAS"    # SHA-256 av root-mappens innehåll
    activated_modules: List[str] = field(default_factory=list)
    state_transitions: List[Dict] = field(default_factory=list)
    file_hashes:       Dict[str, str] = field(default_factory=dict)
    patches:           List[SelfHealingPatch] = field(default_factory=list)
    final_state:       str = MachineState.INIT
    iso_standard:      str = "ISO/IEC 27037:2012"   # endast en etikett i rapportutdata — systemet är EJ certifierat enligt standarden
    enfsi_standard:    str = "ENFSI FSA-BPM-002 FIXED-2026"  # endast en etikett i rapportutdata — ej certifierad metodik


# ─────────────────────────────────────────────────────────────────────────────
# CASE STATE MACHINE (v10 — ersätter v9.9.0 CaseState)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PreTrialObjectives:
    """
    Prövningsmodell före juridisk slutanalys.
    Byggs ENDAST från faktiskt material + angiven metadata.
    Ingen hårdkodad juridisk slutsats. Luckor förblir luckor.
    """
    vad_skall_avgoras: List[str] = field(default_factory=list)
    ostridigt: List[str] = field(default_factory=list)
    tvistigt: List[str] = field(default_factory=list)
    required_legal_facts: List[str] = field(default_factory=list)
    required_evidence: List[str] = field(default_factory=list)
    required_legal_sources: List[str] = field(default_factory=list)
    gaps: List[str] = field(default_factory=list)
    material_summary: Dict[str, int] = field(default_factory=dict)
    readiness: str = "OTILLRÄCKLIGT UNDERLAG"  # REDO | DELVIS | OTILLRÄCKLIGT UNDERLAG
    notes: List[str] = field(default_factory=list)



@dataclass
class UnsolicitedStepResult:
    step: str
    passed: bool
    detail: str = ""


@dataclass
class UnsolicitedValidationRecord:
    file_id: str
    relative_path: str
    steps: List[UnsolicitedStepResult] = field(default_factory=list)
    fully_cleared: bool = False
    blocked_reason: str = ""


@dataclass
class RequisiteGateItem:
    legal_rule: str
    requisite_text: str
    modal: str = "MUST"  # MUST | ALT | EXC
    status: str = RequisiteStatus.BEVISNING_SAKNAS
    fact_ref: str = "NOT_VERIFIABLE"
    anchor_ok: bool = False
    notes: str = ""


@dataclass
class LegalRequisiteGateResult:
    items: List[RequisiteGateItem] = field(default_factory=list)
    gate_passed: bool = False
    hard_stop_hs11: bool = False
    summary: str = ""


@dataclass
class HoldingChainResult:
    source_ref: str
    h1: str = HoldingLevel.EJ_VERIFIERAD
    h2: str = HoldingLevel.EJ_VERIFIERAD
    h3: str = HoldingLevel.EJ_VERIFIERAD
    usable_for_requisite: bool = False
    notes: str = ""


@dataclass
class PartyImpactMatrix:
    party_label: str
    verified_strengths: List[str] = field(default_factory=list)
    verified_weaknesses: List[str] = field(default_factory=list)
    open_evidence_questions: List[str] = field(default_factory=list)
    procedural_risks: List[str] = field(default_factory=list)
    legal_risks: List[str] = field(default_factory=list)
    action_points: List[str] = field(default_factory=list)


@dataclass
class PresentationViews:
    court_view: Dict = field(default_factory=dict)
    party_a: Optional[PartyImpactMatrix] = None
    party_b: Optional[PartyImpactMatrix] = None
    mediation: Dict = field(default_factory=dict)
    disclaimer: str = (
        "PROVISORISKT ANALYSUNDERLAG — AI saknar dömande mandat. "
        "Vyer ändrar inte underliggande CaseState."
    )


@dataclass
class CaseStateMachine:
    """
    Systemets centrala arbetsrepresentation i v10.
    Tillståndet är en graf — inte en lista.
    Övergångar sker ALDRIG utan godkänd grind.
    """
    # Identitet
    case_id:        str = ""
    motor_version:  str = MOTOR_VERSION
    root_directory: str = ""

    # Tillstånd (state machine)
    current_state:  str = MachineState.INIT
    state_history:  List[Dict] = field(default_factory=list)

    # Jurisdiktion (DYNAMISK — bestäms från materialet)
    domstol:      str = "EJ IDENTIFIERAD"
    jurisdiktion: str = "EJ IDENTIFIERAD"
    processform:  str = "EJ IDENTIFIERAD"
    måltyp:       str = "EJ IDENTIFIERAD"

    # Material
    files:           List[FileRecord] = field(default_factory=list)
    total_files:     int = 0
    locked_count:    int = 0
    quarantine_count: int = 0
    category_a:      int = 0
    category_b:      int = 0
    # Sammanfattning från evidence_categorizer (filnamn/sökväg)
    name_categorization_summary: Dict[str, int] = field(default_factory=dict)
    name_categorization_ran: bool = False

    # Pre-trial objectives (prövningsmål före analys)
    pre_trial: Optional[PreTrialObjectives] = None

    # v10-v3 ModeRouter
    execution_mode: str = ExecutionMode.UNDETERMINED
    mode_routing_notes: List[str] = field(default_factory=list)
    hard_stop_code: str = ""

    # v10-v3 Unsolicited validation
    unsolicited_validations: List[UnsolicitedValidationRecord] = field(default_factory=list)

    # v10-v3 Legal Requisite Gate
    requisite_gate: Optional[LegalRequisiteGateResult] = None
    holding_chains: List[HoldingChainResult] = field(default_factory=list)

    # v10-v3 Presentation layer
    presentation: Optional[PresentationViews] = None

    # Graf (central datastruktur v10)
    graph: RelationGraph = field(default_factory=RelationGraph)

    # Kapabiliteter (dynamisk modulaktivering)
    active_modules: List[str] = field(default_factory=list)

    # Gatekeeper
    gatekeeper_passed:  int = 0
    gatekeeper_blocked: int = 0

    # Subsumtion
    subsumtioner: List[SubsumptionRecord] = field(default_factory=list)

    # Revision
    agent_a_findings: List[Dict] = field(default_factory=list)   # Falsifiering
    agent_b_findings: List[Dict] = field(default_factory=list)   # Verifiering
    agent_c_findings: List[Dict] = field(default_factory=list)   # Second-order

    # Rättskällesökning (från deep_search_pipeline.py, v9.8.1) — verifiering,
    # ersätter aldrig juridisk analys.
    legal_source_verifications: List[Dict] = field(default_factory=list)

    # Motrevision / buggregister (porterat från recursive_evidence_vault_manager.py v9.9.0)
    bugs: List["BugReport"] = field(default_factory=list)
    processuell_åtgärdslista: List[str] = field(default_factory=list)

    # Falsifiering
    falsification_verdict: str = FalsificationVerdict.NOT_RUN
    counter_chain_strength: str = "EJ ANALYSERAD"

    # Domsutkast (PROVISIONAL ONLY)
    judgment_draft: Optional[JudgmentDraftSection] = None

    # Self-healing
    patches: List[SelfHealingPatch] = field(default_factory=list)
    reproducibility: Optional[ReproducibilityRecord] = None

    # Slutstatus
    hard_stop:        bool  = False
    hard_stop_reason: str   = ""
    audit_status:     str   = SlutStatus.E
    sårbarhet_risk:   str   = "EJ ANALYSERAD"

    def transition(self, new_state: MachineState, reason: str = ""):
        """Registrerar tillståndsövergång med tidsstämpel."""
        entry = {
            "from": self.current_state,
            "to":   new_state,
            "ts":   datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        }
        self.state_history.append(entry)
        self.current_state = new_state
        log.info(f"[STATE] {entry['from']} → {new_state} | {reason}")
        if self.reproducibility:
            self.reproducibility.state_transitions.append(entry)

    def trigger_hard_stop(self, reason: str):
        self.hard_stop = True
        self.hard_stop_reason = reason
        self.audit_status = SlutStatus.I
        self.transition(MachineState.HARD_STOP, reason)
        log.error(f"[HARD_STOP] {reason}")


# ─────────────────────────────────────────────────────────────────────────────
# HJÄLPFUNKTIONER
# ─────────────────────────────────────────────────────────────────────────────
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except (PermissionError, OSError):
        return "KAN EJ VERIFIERAS"


def _md5(path: Path) -> str:
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except (PermissionError, OSError):
        return "KAN EJ VERIFIERAS"


def _magic_bytes(path: Path) -> str:
    MAGIC = {
        b"%PDF":         "PDF",
        b"PK\x03\x04":  "ZIP/DOCX/XLSX/PPTX",
        b"\xff\xd8\xff": "JPEG",
        b"\x89PNG":      "PNG",
        b"RIFF":         "WAV/AVI",
        b"ID3":          "MP3",
        b"fLaC":         "FLAC",
        b"\x1a\x45\xdf\xa3": "MKV/WEBM",
        b"OggS":         "OGG",
        b"{\n":          "JSON",
        b"<?xml":        "XML",
        b"<!DO":         "HTML",
    }
    try:
        with open(path, "rb") as f:
            header = f.read(16)
        for magic, ft in MAGIC.items():
            if header.startswith(magic):
                return ft
        return "OKÄND/TEXT"
    except (PermissionError, OSError):
        return "KAN EJ VERIFIERAS"


def _timestamps(path: Path) -> Tuple[str, str]:
    try:
        s   = path.stat()
        fmt = "%Y-%m-%d %H:%M:%S UTC"
        c   = datetime.fromtimestamp(
            getattr(s, "st_birthtime", s.st_ctime), tz=timezone.utc
        ).strftime(fmt)
        m = datetime.fromtimestamp(s.st_mtime, tz=timezone.utc).strftime(fmt)
        return c, m
    except OSError:
        return "KAN EJ VERIFIERAS", "KAN EJ VERIFIERAS"


def _file_id(path: Path, root: Path) -> str:
    rel   = str(path.relative_to(root)).upper().replace(os.sep, "_")
    short = re.sub(r"[^A-Z0-9_]", "", rel)[:36]
    return f"FILE_{short}_{str(uuid.uuid4())[:8].upper()}"


def _to_json(obj) -> object:
    """Rekursiv JSON-serialisering."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    if isinstance(obj, list):
        return [_to_json(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _to_json(v) for k, v in obj.items()}
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _to_json(v) for k, v in asdict(obj).items()}
    return str(obj)


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 1: INGESTION AGENT (v10 — multi-folder, fryst baslinje)
# ─────────────────────────────────────────────────────────────────────────────
class IngestionAgent:
    """
    Rekursiv filinläsning med multi-folder-stöd.

    v10-förbättringar:
    - Multi-folder: accept list of root dirs
    - Strukturell länkning per undermapp (STRUCTURAL_LINKED_BY_PATH)
    - Karantän-triggers konfigurerbara per ärende
    - Root-hash beräknas för hela vault
    """

    QUARANTINE_KW = {
        "nya_inkomna_filer", "oombett", "new_files", "incoming",
        "quarantine", "karantän", "ej_åberopad", "new_discoveries",
        "nya_upptäckter", "unsolicited",
    }
    LOCKED_KW = {
        "aktbilagor", "polisprotokoll", "förundersökning", "fup",
        "domstolsakt", "åberopat", "inkommit_material",
        "official", "submitted", "inkommen_akt",
    }

    def __init__(
        self,
        root_dirs: List[str],
        exhibit_list: Optional[List[str]] = None,
        extra_quarantine_kw: Optional[Set[str]] = None,
        extra_locked_kw: Optional[Set[str]] = None,
    ):
        self.roots         = [Path(d).resolve() for d in root_dirs]
        self.exhibit_list  = exhibit_list or []
        self.quarantine_kw = self.QUARANTINE_KW | (extra_quarantine_kw or set())
        self.locked_kw     = self.LOCKED_KW | (extra_locked_kw or set())
        log.info(f"[INGESTION v10] Roots: {[str(r) for r in self.roots]}")

    def _classify(self, path: Path) -> Tuple[str, str, bool]:
        parts = " ".join(p.lower().replace(" ", "_") for p in path.parts)
        if self.exhibit_list and any(
            e.lower() in str(path).lower() for e in self.exhibit_list
        ):
            return BaselineState.LOCKED_BASELINE, ProceduralStatus.OFFICIALLY_SUBMITTED, False
        if any(kw in parts for kw in self.quarantine_kw):
            return BaselineState.UNSOLICITED_INPUT, ProceduralStatus.NOT_YET_PLEADED, True
        if any(kw in parts for kw in self.locked_kw):
            return BaselineState.LOCKED_BASELINE, ProceduralStatus.OFFICIALLY_SUBMITTED, False
        return BaselineState.UNVERIFIED, ProceduralStatus.UNKNOWN, False

    def scan(self) -> Tuple[List[FileRecord], Dict[str, str]]:
        """
        Returnerar (records, file_hashes).
        file_hashes: {fil_id: sha256} för ReproducibilityRecord.
        """
        all_records: List[FileRecord] = []
        file_hashes: Dict[str, str]   = {}

        for root in self.roots:
            if not root.exists():
                log.warning(f"[INGESTION] Root saknas: {root}")
                continue

            files = [f for f in root.rglob("*") if f.is_file()]
            log.info(f"[INGESTION] {root}: {len(files)} filer")

            # Bygg folder→files-index för strukturell länkning
            folder_idx: Dict[str, List[str]] = defaultdict(list)
            for f in files:
                folder_idx[str(f.parent)].append(str(f))

            for fpath in files:
                rel    = fpath.relative_to(root)
                parts  = list(rel.parts)
                sha    = _sha256(fpath)
                md5    = _md5(fpath)
                magic  = _magic_bytes(fpath)
                c, m   = _timestamps(fpath)
                fid    = _file_id(fpath, root)

                avvik: List[str] = []
                ext = fpath.suffix.lower().lstrip(".")
                ext_map = {
                    "pdf": "PDF", "jpg": "JPEG", "jpeg": "JPEG",
                    "png": "PNG", "mp3": "MP3", "wav": "WAV/AVI",
                    "docx": "ZIP/DOCX/XLSX/PPTX", "xlsx": "ZIP/DOCX/XLSX/PPTX",
                }
                expected = ext_map.get(ext, "")
                if expected and magic not in ("KAN EJ VERIFIERAS", "OKÄND/TEXT"):
                    if expected not in magic:
                        avvik.append(
                            f"MÖJLIGT_FAKTAFEL: Magic ({magic}) ≠ tillägg (.{ext})"
                        )

                meta = MetadataRecord(
                    fil=str(rel),
                    käll_id=fid,
                    skapad=c,
                    ändrad=m,
                    storlek_bytes=fpath.stat().st_size if fpath.exists() else 0,
                    filtyp_magic=magic,
                    hash_sha256=sha,
                    hash_md5=md5,
                    integritet=(
                        IntegrityStatus.VERIFIED
                        if sha != "KAN EJ VERIFIERAS"
                        else IntegrityStatus.KAN_EJ_VERIFIERAS
                    ),
                    modifieringstyp="SKAPAD" if c == m else "ÄNDRAD",
                    avvikelser=avvik,
                )

                baseline, proc, quarantine = self._classify(fpath)

                rec = FileRecord(
                    file_id=fid,
                    relative_path=str(rel),
                    absolute_path=str(fpath),
                    filename=fpath.name,
                    extension=fpath.suffix.lower(),
                    folder_depth=len(parts) - 1,
                    context_tags=list(parts[:-1]),
                    baseline_state=baseline,
                    procedural_status=proc,
                    quarantine_flag=quarantine,
                    evidence_category=EvidenceCategory.UNCLASSIFIED,
                    metadata=meta,
                    gatekeeper_passed=False,
                    slutstatus=SlutStatus.E,
                    avvikelser=avvik,
                )
                all_records.append(rec)
                file_hashes[fid] = sha

        log.info(
            f"[INGESTION] Totalt {len(all_records)} filer | "
            f"Locked: {sum(1 for r in all_records if r.baseline_state == BaselineState.LOCKED_BASELINE)} | "
            f"Karantän: {sum(1 for r in all_records if r.quarantine_flag)}"
        )
        return all_records, file_hashes


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 2: EVIDENCE CLASSIFIER (v10)
# ─────────────────────────────────────────────────────────────────────────────
class EvidenceClassifierAgent:
    """Klassificerar Kategori A (stark) / B (brus/risk). Oförändrad logik, hårdare gräns."""

    A_KW = {
        "dna", "forensik", "forensic", "polisprotokoll", "fup",
        "banktransaktion", "transfer", "avtal", "kontrakt", "signerat",
        "myndighetsbeslut", "domstolsakt", "aktbilaga", "tekniskrapport",
        "rattsintyg", "läkarintyg", "it-forensik", "it_forensik",
        "it-rapport", "logg", "log", "sms_konversationer",
        "övervakningskamera", "surveillance", "evidence", "banköverföring",
    }
    B_KW = {
        "hörensägen", "hearsay", "spekulation", "speculation", "chatt",
        "kommentar", "privat", "private", "oombett", "unsolicited",
        "okänd", "unknown", "brus", "noise", "irrelevant", "odaterad",
        "undated", "konversation_privat",
    }
    STRONG_EXT = {".pdf", ".docx", ".xlsx", ".wav", ".mp3", ".m4a",
                  ".mp4", ".mov", ".jpg", ".jpeg", ".png"}

    def classify(self, records: List[FileRecord]) -> List[FileRecord]:
        for r in records:
            r.evidence_category = self._one(r)
        a = sum(1 for r in records if r.evidence_category == EvidenceCategory.A_STRONG)
        b = sum(1 for r in records if r.evidence_category == EvidenceCategory.B_RISK)
        log.info(f"[CLASSIFIER] A={a} | B={b} | UNCL={len(records)-a-b}")
        return records

    def _one(self, r: FileRecord) -> str:
        if r.quarantine_flag:
            return EvidenceCategory.B_RISK
        if r.metadata.integritet == IntegrityStatus.KAN_EJ_VERIFIERAS:
            r.avvikelser.append("MÖJLIGT_FAKTAFEL: Integritet ej verifierbar → B_RISK")
            return EvidenceCategory.B_RISK
        path = (r.relative_path + " " + " ".join(r.context_tags)).lower()
        sa = sum(1 for kw in self.A_KW if kw in path or kw in r.filename.lower())
        sb = sum(1 for kw in self.B_KW if kw in path or kw in r.filename.lower())
        if r.extension in self.STRONG_EXT:
            sa += 1
        if sa > sb and sa >= 1:
            return EvidenceCategory.A_STRONG
        if sb > sa:
            return EvidenceCategory.B_RISK
        if r.baseline_state == BaselineState.LOCKED_BASELINE:
            return EvidenceCategory.A_STRONG
        return EvidenceCategory.UNCLASSIFIED


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 3: CAPABILITY MAP ENGINE (v10 — ny)
# ─────────────────────────────────────────────────────────────────────────────
class CapabilityMapEngine:
    """
    Aktiverar ENDAST relevanta specialistmoduler baserat på inläst material.
    En modul aktiveras ej utan stöd i materialet.
    """

    AUDIO_EXT  = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}
    VIDEO_EXT  = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
    DOC_EXT    = {".pdf", ".docx", ".doc", ".txt", ".rtf"}
    FINANCE_KW = {"bank", "transaktion", "transfer", "faktura", "räkn", "betalning", "konto"}
    MEDICAL_KW = {"läkar", "journal", "diagnos", "medicinsk", "vård", "sjukhus", "rättsintyg"}
    ADMIN_KW   = {"myndighet", "beslut", "förvaltning", "tillstånd", "ansökan"}

    def map(self, records: List[FileRecord]) -> List[str]:
        modules: Set[str] = set()
        if records:
            modules.add(CapabilityModule.DOCUMENT_FORENSICS)
            modules.add(CapabilityModule.METADATA_FORENSICS)
            modules.add(CapabilityModule.PROCEDURAL)
            modules.add(CapabilityModule.LEGAL_SOURCE)

        for r in records:
            ext  = r.extension.lower()
            path = (r.relative_path + " " + r.filename).lower()

            if ext in self.AUDIO_EXT:
                modules.add(CapabilityModule.AUDIO_FORENSICS)
            if ext in self.VIDEO_EXT:
                modules.add(CapabilityModule.VIDEO_FORENSICS)
            if any(kw in path for kw in self.FINANCE_KW):
                modules.add(CapabilityModule.FINANCIAL_ANALYSIS)
            if any(kw in path for kw in self.MEDICAL_KW):
                modules.add(CapabilityModule.MEDICAL_ANALYSIS)
            if any(kw in path for kw in self.ADMIN_KW):
                modules.add(CapabilityModule.ADMINISTRATIVE)
            if "dom" in path or "beslut" in path or "tingsrätt" in path:
                modules.add(CapabilityModule.JUDGMENT_AUDIT)
            if ext in {".pdf", ".docx"}:
                modules.add(CapabilityModule.TECHNICAL_ANALYSIS)

        result = sorted(modules)
        log.info(f"[CAPABILITY_MAP] Aktiverade moduler ({len(result)}): {result}")
        return result


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 4: RELATION GRAPH BUILDER (v10 — ny, ersätter v9.9.0 RelationGraphAgent)
# ─────────────────────────────────────────────────────────────────────────────
class RelationGraphBuilder:
    """
    Bygger relationsgrafen från FileRecords.

    ZERO INFERENCE POLICY:
    - Varje kant TVINGAS till UNRESOLVED om VerbatimAnchor saknas/ogiltig
    - CIRCULAR_REASONING_BLOCKER: Domen används ALDRIG som facit
    - Muntlig källa → [MUNTLIG_KÄLLA — EJ PRIMÄRKÄLLA]
    """

    def build(self, records: List[FileRecord]) -> RelationGraph:
        g = RelationGraph()

        # Skapa en nod per fil
        for r in records:
            node = GraphNode(
                node_id=r.file_id,
                node_type=(
                    NodeType.EVIDENCE_ITEM
                    if r.evidence_category == EvidenceCategory.A_STRONG
                    else NodeType.CLAIM
                ),
                label=r.relative_path,
                source_id=r.file_id,
                metadata={
                    "baseline_state":    r.baseline_state,
                    "quarantine_flag":   r.quarantine_flag,
                    "evidence_category": r.evidence_category,
                    "sha256":            r.metadata.hash_sha256,
                    "integrity":         r.metadata.integritet,
                },
            )
            g.add_node(node)

        # Skapa kanter: strukturella länkar och bevisrelationer
        folder_groups: Dict[str, List[FileRecord]] = defaultdict(list)
        for r in records:
            folder_groups[str(Path(r.relative_path).parent)].append(r)

        edge_counter = 0
        for folder, group in folder_groups.items():
            for i, r_a in enumerate(group):
                for r_b in group[i + 1:]:
                    edge_counter += 1
                    # Strukturell länk inom samma mapp
                    anchor = self._make_anchor(r_a)
                    raw_type = (
                        EdgeType.SUPPORTS
                        if (r_a.evidence_category == EvidenceCategory.A_STRONG
                            and r_b.evidence_category == EvidenceCategory.A_STRONG
                            and not r_a.quarantine_flag
                            and not r_b.quarantine_flag)
                        else EdgeType.UNRESOLVED
                    )
                    edge = GraphEdge(
                        edge_id=f"E{edge_counter:04d}",
                        from_node=r_a.file_id,
                        to_node=r_b.file_id,
                        edge_type=raw_type,
                        anchor=anchor,
                        notes="STRUCTURAL_LINKED_BY_PATH — L02/L03 krävs för juridisk slutsats",
                    )
                    g.add_edge(edge)

        log.info(
            f"[RELATION_GRAPH] Noder: {len(g.nodes)} | Kanter: {len(g.edges)} | "
            f"Verifierade: {g.verified_count} | UNRESOLVED: {g.unresolved_count}"
        )
        return g

    def _make_anchor(self, r: FileRecord) -> VerbatimAnchor:
        """
        Skapar ankare från FileRecord metadata.
        Om SHA-256 saknas → ogiltig ankare → UNRESOLVED.
        """
        verified = r.metadata.hash_sha256 not in ("KAN EJ VERIFIERAS", "")
        return VerbatimAnchor(
            source_id=r.file_id,
            source_path=r.relative_path,
            source_hash=r.metadata.hash_sha256,
            page_or_time="FILNIVÅ",
            verbatim_quote=(
                f"[FILREFERENS: {r.relative_path} | "
                f"SHA-256: {r.metadata.hash_sha256[:16]}...]"
                if verified
                else "[SAKNAR CITAT]"
            ),
            verified=verified,
        )


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 5: SUBSUMPTION GATEKEEPER (v10 — ny hård grind)
# ─────────────────────────────────────────────────────────────────────────────
class SubsumptionGatekeeper:
    """
    Hård processbarriär — kontrollerar att INGET karantänmaterial
    tillåts in i den juridiska subsumtionen utan formellt åberopande.

    Detta är en ABSOLUT SPÄRR, inte en mjuk rekommendation.
    Material som blockeras loggas och åtgärdslista uppdateras.
    """

    def gate(
        self, records: List[FileRecord]
    ) -> Tuple[List[FileRecord], List[FileRecord], List[str]]:
        """
        Returnerar (passed, blocked, action_items).
        passed:  Filer som får ingå i subsumtionen
        blocked: Filer som är blockerade (karantän / ej åberopade)
        action_items: Processuell åtgärdslista
        """
        passed:   List[FileRecord] = []
        blocked:  List[FileRecord] = []
        actions:  List[str]        = []

        for r in records:
            if self._allowed(r):
                r.gatekeeper_passed = True
                passed.append(r)
            else:
                r.gatekeeper_passed = False
                blocked.append(r)
                actions.append(
                    f"[GATEKEEPER BLOCK] {r.relative_path} | "
                    f"Status: {r.procedural_status} | "
                    f"Baseline: {r.baseline_state} | "
                    f"Kräver formellt åberopande för subsumtion."
                )

        log.info(
            f"[GATEKEEPER] Godkänd: {len(passed)} | "
            f"Blockerad: {len(blocked)}"
        )
        return passed, blocked, actions

    def _allowed(self, r: FileRecord) -> bool:
        """
        Tillåt i subsumtion om:
        1. Ej i karantän, OCH
        2. LOCKED_BASELINE eller OFFICIALLY_SUBMITTED, OCH
        3. Integritet VERIFIED
        """
        return (
            not r.quarantine_flag
            and r.baseline_state == BaselineState.LOCKED_BASELINE
            and r.metadata.integritet == IntegrityStatus.VERIFIED
        )


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 6: BIDIRECTIONAL AUDIT ENGINE (v10 — ny)
# ─────────────────────────────────────────────────────────────────────────────
class BidirectionalAuditEngine:
    """
    Tredubbel granskning (avsnitt 23 i blueprinten):
    Riktning 1: DOM → KÄLLA → BEVIS → RÄTTSFAKTUM
    Riktning 2: AKT → RÄTTSFAKTUM → BEVIS → HAR DET BEAKTATS?
    Riktning 3: KÄLLA ↔ KÄLLA — intern motsägelse?

    Resultat matas in i Audit-agent A (Falsifiering) och B (Verifiering).
    """

    def run(
        self, graph: RelationGraph, passed_records: List[FileRecord]
    ) -> Dict[str, List[Dict]]:
        results = {
            "direction_1_dom_to_source":   self._dir1(graph, passed_records),
            "direction_2_source_to_dom":   self._dir2(graph, passed_records),
            "direction_3_internal_conflict": self._dir3(graph),
        }
        total_issues = sum(len(v) for v in results.values())
        log.info(f"[BIDIRECTIONAL_AUDIT] Totala avvikelser: {total_issues}")
        return results

    def _dir1(
        self, graph: RelationGraph, records: List[FileRecord]
    ) -> List[Dict]:
        """DOM → KÄLLA: Kontrollera att varje grafkant har giltig ankare."""
        issues = []
        for edge in graph.edges:
            if not edge.anchor.is_valid():
                issues.append({
                    "riktning":    "DOM→KÄLLA",
                    "edge_id":     edge.edge_id,
                    "from":        edge.from_node,
                    "to":          edge.to_node,
                    "problem":     "Kant saknar giltig VerbatimAnchor",
                    "typ":         "KÄLLBRIST",
                    "allvarlighet": "HÖG",
                })
        return issues

    def _dir2(
        self, graph: RelationGraph, records: List[FileRecord]
    ) -> List[Dict]:
        """KÄLLA → DOM: Finns bevis i akten som inte har någon grafkant?"""
        issues = []
        node_ids = set(graph.nodes.keys())
        for r in records:
            if r.file_id not in node_ids:
                issues.append({
                    "riktning":    "KÄLLA→DOM",
                    "fil":         r.relative_path,
                    "problem":     "Fil finns i akt men saknar nod i relationsgrafen",
                    "typ":         "UTELÄMNANDE",
                    "allvarlighet": "MEDEL",
                })
            elif not graph.get_edges_from(r.file_id) and not graph.get_edges_to(r.file_id):
                issues.append({
                    "riktning":    "KÄLLA→DOM",
                    "fil":         r.relative_path,
                    "problem":     "Nod i graf men utan kanter — isolerad bevispunkt",
                    "typ":         "ISOLERAD_BEVISPUNKT",
                    "allvarlighet": "LÅG",
                })
        return issues

    def _dir3(self, graph: RelationGraph) -> List[Dict]:
        """KÄLLA ↔ KÄLLA: Interna motsägelser i relationsgrafen."""
        issues = []
        for pair in graph.contradiction_pairs():
            e1, e2 = pair
            issues.append({
                "riktning":    "KÄLLA↔KÄLLA",
                "edge_1":      e1.edge_id,
                "edge_2":      e2.edge_id,
                "from_node":   e1.from_node,
                "to_node":     e1.to_node,
                "problem":     "Intern motsägelse: CONTRADICTS + SUPPORTS i båda riktningar",
                "typ":         "INTERN_MOTSÄGELSE",
                "allvarlighet": "HÖG",
            })
        return issues


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT-AGENT A — Falsifiering (L12)
# ─────────────────────────────────────────────────────────────────────────────
class AuditAgentA:
    """
    Söker aktivt avvikelser mellan primärkällor och grafrelationer.
    Input: bidirectional_audit-resultat + graph.
    Output: Lista med identifierade avvikelser.
    """

    def run(
        self, bidir: Dict[str, List[Dict]], graph: RelationGraph
    ) -> List[Dict]:
        findings: List[Dict] = []

        # Samlat från bidirektional audit
        for direction, issues in bidir.items():
            for issue in issues:
                findings.append({
                    "agent":       "AUDIT-A",
                    "typ":         "AVVIKELSE",
                    "subtyp":      issue.get("typ", "OKÄND"),
                    "beskrivning": issue.get("problem", ""),
                    "allvarlighet": issue.get("allvarlighet", "MEDEL"),
                    "direction":   direction,
                    "detalj":      issue,
                })

        # UNRESOLVED-kanter som borde vara verifierade
        unres = [e for e in graph.edges if e.edge_type == EdgeType.UNRESOLVED]
        if unres:
            findings.append({
                "agent":       "AUDIT-A",
                "typ":         "AVVIKELSE",
                "subtyp":      "OUPPLÖSTA_KANTER",
                "beskrivning": (
                    f"{len(unres)} grafkanter är UNRESOLVED — "
                    f"verbatim-ankare saknas"
                ),
                "allvarlighet": "HÖG" if len(unres) > 3 else "MEDEL",
                "detalj":      {"antal": len(unres)},
            })

        # CONTRADICTS-kanter utan motbevis
        contradicts = [e for e in graph.edges if e.edge_type == EdgeType.CONTRADICTS]
        for e in contradicts:
            finding = {
                "agent":       "AUDIT-A",
                "typ":         "AVVIKELSE",
                "subtyp":      "CONTRADICTS_KANT",
                "beskrivning": (
                    f"Kant {e.edge_id} är CONTRADICTS — "
                    f"kontrapåstående identifierat"
                ),
                "allvarlighet": "HÖG",
                "edge_id":     e.edge_id,
                "anchor":      e.anchor.verbatim_quote,
                "anchor_förhandsvisning": e.anchor.verbatim_quote[:80],
            }
            findings.append(finding)

        log.info(f"[AUDIT-A] Falsifiering: {len(findings)} avvikelser")
        return findings


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT-AGENT B — Verifiering (L13)
# ─────────────────────────────────────────────────────────────────────────────
class AuditAgentB:
    """
    Söker stöd för påståenden i primärkällor.
    Verifierar att SUPPORTS-kanter har giltiga ankare.
    """

    def run(
        self, graph: RelationGraph, passed_records: List[FileRecord]
    ) -> List[Dict]:
        findings: List[Dict] = []

        # Verifierade SUPPORTS-kanter
        verified_supports = [
            e for e in graph.edges
            if e.edge_type == EdgeType.SUPPORTS and e.anchor.is_valid()
        ]
        for e in verified_supports:
            findings.append({
                "agent":       "AUDIT-B",
                "typ":         "VERIFIERAT_STÖD",
                "edge_id":     e.edge_id,
                "from":        e.from_node,
                "to":          e.to_node,
                # Fullständigt ankare: [:80] kapade bort SHA-256-referensen
                # (20/21 i verklig körning). Förhandsvisningen hålls separat.
                "ankare":      e.anchor.verbatim_quote,
                "ankare_förhandsvisning": e.anchor.verbatim_quote[:80],
                "beskrivning": "SUPPORTS-kant med giltig VerbatimAnchor",
            })

        # Filer med verifierad integritet i subsumtion
        verified_a = [
            r for r in passed_records
            if r.evidence_category == EvidenceCategory.A_STRONG
            and r.metadata.integritet == IntegrityStatus.VERIFIED
        ]
        for r in verified_a:
            findings.append({
                "agent":       "AUDIT-B",
                "typ":         "EVIDENCED_FACT_VERIFIED",
                "fil":         r.relative_path,
                "sha256":      r.metadata.hash_sha256[:16] + "...",
                "beskrivning": "Kategori-A-fil med verifierad integritet",
            })

        log.info(f"[AUDIT-B] Verifiering: {len(findings)} verifierade stöd")
        return findings


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT-AGENT C — Second-order audit (L14)
# ─────────────────────────────────────────────────────────────────────────────
class AuditAgentC:
    """
    Granskar Agent A och B oberoende.
    Kontrollerar:
    1. Symmetri (P18): Båda parters argument behandlade?
    2. Cirkelresonemang: Används domens text som fakta?
    3. Asymmetri-varning: A hittar avvikelser men B hittar inget stöd?
    4. Hallucination-kontroll: Påståenden utan ankare?
    """

    def run(
        self, a_findings: List[Dict], b_findings: List[Dict]
    ) -> List[Dict]:
        obs: List[Dict] = []

        # 1. Symmetri-kontroll (P18)
        a_typer = {f.get("subtyp") for f in a_findings}
        b_typer = {f.get("typ")    for f in b_findings}

        if not a_findings and not b_findings:
            obs.append({
                "agent":       "AUDIT-C",
                "kontroll":    "SYMMETRI_P18",
                "resultat":    "Varken avvikelser (A) eller stöd (B) identifierade",
                "bedömning":   "OTILLRÄCKLIGT_UNDERLAG",
                "allvarlighet": "MEDEL",
            })
        elif a_findings and not b_findings:
            obs.append({
                "agent":       "AUDIT-C",
                "kontroll":    "SYMMETRI_P18",
                "resultat":    "Agent A hittade avvikelser men Agent B hittade inget stöd",
                "bedömning":   "ASYMMETRI_VARNING",
                "allvarlighet": "HÖG",
            })
        else:
            obs.append({
                "agent":       "AUDIT-C",
                "kontroll":    "SYMMETRI_P18",
                "resultat":    (
                    f"A={len(a_findings)} avvikelser, B={len(b_findings)} stöd"
                ),
                "bedömning":   "SYMMETRI_GODKÄND",
                "allvarlighet": "LÅG",
            })

        # 2. Cirkelresonemang-kontroll
        for f in a_findings + b_findings:
            desc = f.get("beskrivning", "") + f.get("ankare", "")
            if "domen" in desc.lower() and "primärkälla" not in desc.lower():
                obs.append({
                    "agent":       "AUDIT-C",
                    "kontroll":    "CIRCULAR_REASONING_BLOCKER",
                    "resultat":    f"MÖJLIGT CIRKELRESONEMANG: {desc[:80]}",
                    "bedömning":   "CIRCULAR_REASONING_VARNING",
                    "allvarlighet": "KRITISK",
                })

        # 3. Hallucination-kontroll: UNRESOLVED hos Agent A utan ankare
        unres_findings = [
            f for f in a_findings
            if f.get("subtyp") in ("OUPPLÖSTA_KANTER", "KÄLLBRIST")
        ]
        if len(unres_findings) >= 3:
            obs.append({
                "agent":       "AUDIT-C",
                "kontroll":    "HALLUCINATION_RISK",
                "resultat":    (
                    f"{len(unres_findings)} fynd utan primärkälla — "
                    f"hallucinationsrisk förhöjd"
                ),
                "bedömning":   "HALLUCINATION_RISK_HÖG",
                "allvarlighet": "KRITISK",
            })

        log.info(f"[AUDIT-C] Second-order: {len(obs)} observationer")
        return obs


# ─────────────────────────────────────────────────────────────────────────────
# COUNTER AUDIT AGENT (porterat från recursive_evidence_vault_manager.py v9.9.0)
#
# Kompletterar Agent A/B/C med ett konkret, kodat buggregister (B01–B15).
# Körs efter AUDIT_C, före FALSIFICATION. Adapterad till v10:s CaseStateMachine
# och RelationGraph — "claims" (v9.9.0-koncept) ersätts här av graf-kanter.
# ─────────────────────────────────────────────────────────────────────────────
class CounterAuditAgent:
    """
    FALSIFIERINGSLÄGE — Motbevisar systemets egna slutsatser.

    FAS 5: Var och en av de femton standardiserade buggkoderna (B01–B15) har
    en dedikerad, exekverbar kontrollmetod (_check_b01 .. _check_b15). Varje
    identifierat fynd registreras som ett unikt BugReport i csm.bugs med
    korrekt bug_kod (ingen signal skrivs över tyst). Den slutliga
    sårbarhetsrisken (csm.sårbarhet_risk) beräknas hierarkiskt — den mest
    allvarliga signalen vinner: KRITISK > HÖG > MEDEL > LÅG.

    Kritiska koder (B07/B09/B10/B11/B14/B15) sätter även
    csm.blocks_falsification = True, så att falsifieringsmotorn kan
    spärras/kronas i nästa steg.
    """

    # Allvarlighetskarta per buggkod – används av kalkylatorn.
    BUG_SEVERITY = {
        "B01": "HÖG",    # Dataintegritet
        "B02": "HÖG",    # Källfel
        "B03": "MEDEL",  # Tidsfel
        "B04": "MEDEL",  # Identitetsfel
        "B05": "HÖG",    # Faktaavvikelse
        "B06": "HÖG",    # Bevisavvikelse
        "B07": "KRITISK",  # Utelämnande
        "B08": "HÖG",    # Processfel
        "B09": "KRITISK",  # Rättskällefel (FIX-T)
        "B10": "KRITISK",  # Rekvisitfel (MUST utan bevisning)
        "B11": "KRITISK",  # Subsumtionsfel
        "B12": "HÖG",    # Domskälsfel
        "B13": "HÖG",    # Beviskravsfel
        "B14": "KRITISK",  # Intern motsägelse
        "B15": "KRITISK",  # Oupplöst fråga
    }
    SEVERITY_ORDER = ("KRITISK", "HÖG", "MEDEL", "LÅG")
    CRITICAL_CODES = ("B07", "B09", "B10", "B11", "B14", "B15")

    def run(self, csm: CaseStateMachine) -> CaseStateMachine:
        log.info("[COUNTER_AUDIT] Kör inverterad motrevision (B01–B15)...")
        bugs: List[BugReport] = list(csm.bugs)

        bugs += self._check_b01(csm)
        bugs += self._check_b02(csm)
        bugs += self._check_b03(csm)
        bugs += self._check_b04(csm)
        bugs += self._check_b05(csm)
        bugs += self._check_b06(csm)
        bugs += self._check_b07(csm)
        bugs += self._check_b08(csm)
        bugs += self._check_b09(csm)
        bugs += self._check_b10(csm)
        bugs += self._check_b11(csm)
        bugs += self._check_b12(csm)
        bugs += self._check_b13(csm)
        bugs += self._check_b14(csm)
        bugs += self._check_b15(csm)

        csm.bugs = bugs
        csm.sårbarhet_risk = self._compute_risk_level(bugs)
        csm.processuell_åtgärdslista = self._build_action_list(csm, bugs)
        csm.blocks_falsification = any(
            self._kod(b) in self.CRITICAL_CODES for b in bugs
        )

        critical = [b for b in bugs if b.allvarlighet == "KRITISK"]
        if critical and not csm.hard_stop:
            log.warning(f"[COUNTER_AUDIT] {len(critical)} kritiska buggar identifierade")

        log.info(
            f"[COUNTER_AUDIT] Klar | Buggar: {len(bugs)} | "
            f"Risk: {csm.sårbarhet_risk} | Åtgärder: {len(csm.processuell_åtgärdslista)}"
        )
        return csm

    @staticmethod
    def _kod(bug: BugReport) -> str:
        """Returnerar kort buggkod ('B07') oavsett enum/sträng på bug_kod."""
        k = getattr(bug, "bug_kod", "")
        return getattr(k, "name", str(k))
    @staticmethod
    def _parse_date(value) -> Optional[datetime]:
        """Tolerant datumtolkning (ISO-8601 eller ÅÅÅÅ-MM-DD)."""
        if not value or str(value).strip() in ("KAN EJ VERIFIERAS", ""):
            return None
        s = str(value).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None

    def _compute_risk_level(self, bugs: List[BugReport]) -> str:
        """Hierarkisk kalkylator – den mest allvarliga signalen vinner."""
        if any(b.allvarlighet == "KRITISK" for b in bugs):
            return "KRITISK"
        if any(b.allvarlighet == "HÖG" for b in bugs):
            return "HÖG"
        if any(b.allvarlighet == "MEDEL" for b in bugs):
            return "MEDEL"
        return "LÅG"

    def _build_action_list(self, csm: CaseStateMachine, bugs: List[BugReport]) -> List[str]:
        actions = []
        for b in bugs:
            if b.allvarlighet in ("KRITISK", "HÖG"):
                actions.append(f"[{self._kod(b)}] {b.rekommendation}")
        if csm.quarantine_count > 0:
            actions.append(
                f"[KARANTÄN] {csm.quarantine_count} filer kräver formellt åberopande "
                f"för att ingå i primäranalys"
            )
        if csm.hard_stop:
            actions.append(f"[HARD_STOP] {csm.hard_stop_reason}")
        return actions

    # ── B01: DATAINTEGRITET ─────────────────────────────────
    def _check_b01(self, csm: CaseStateMachine) -> List[BugReport]:
        """B01: SHA-256/MD5 saknas, magic bytes avviker eller filstorleken är noll."""
        bugs = []
        for r in csm.files:
            if r.metadata.hash_sha256 in ("", "KAN EJ VERIFIERAS") or \
                    r.metadata.hash_md5 in ("", "KAN EJ VERIFIERAS"):
                bugs.append(BugReport(
                    bug_id=f"BUG_{BugCode.B01.name}_{r.file_id[:8]}",
                    bug_kod=BugCode.B01,
                    beskrivning=f"Fil saknar SHA-256/MD5-hash: {r.relative_path}",
                    fil=r.relative_path,
                    allvarlighet=self.BUG_SEVERITY["B01"],
                    rekommendation="Verifiera filintegritet manuellt. Kontrollera chain of custody.",
                ))
            if r.metadata.storlek_bytes == 0:
                bugs.append(BugReport(
                    bug_id=f"BUG_{BugCode.B01.name}_{r.file_id[:8]}_ZERO",
                    bug_kod=BugCode.B01,
                    beskrivning=f"Filstorleken är noll: {r.relative_path}",
                    fil=r.relative_path,
                    allvarlighet=self.BUG_SEVERITY["B01"],
                    rekommendation="Kontrollera att filen inte är korrupt eller tom.",
                ))
            if r.metadata.filtyp_magic in ("", "KAN EJ VERIFIERAS"):
                bugs.append(BugReport(
                    bug_id=f"BUG_{BugCode.B01.name}_{r.file_id[:8]}_MAGIC",
                    bug_kod=BugCode.B01,
                    beskrivning=f"Filens dolda magic bytes kan inte verifieras: {r.relative_path}",
                    fil=r.relative_path,
                    allvarlighet=self.BUG_SEVERITY["B01"],
                    rekommendation="Identifiera filtyp via magic bytes – aldrig via filnamnstillägg.",
                ))
        return bugs

    # ── B02: KÄLLFEL ────────────────────────────────────────
    def _check_b02(self, csm: CaseStateMachine) -> List[BugReport]:
        """B02: påståenden/slutsatser saknar källnod eller giltigt citatankare."""
        bugs = []
        if len(csm.files) > 0 and csm.graph.verified_count == 0 and csm.graph.unresolved_count == 0:
            bugs.append(BugReport(
                bug_id=f"BUG_{BugCode.B02.name}_NO_SOURCE_ANCHOR",
                bug_kod=BugCode.B02,
                beskrivning=(
                    "Påståenden/slutsatser saknar motsvarande källnod eller giltigt "
                    "citatankare i relationsgrafen (0 verifierade kanter)."
                ),
                fil=csm.root_directory,
                allvarlighet=self.BUG_SEVERITY["B02"],
                rekommendation="Bygg relationsgrafen med verifierade VerbatimAnchor per påstående.",
            ))
        return bugs
    # ── B03: TIDSFEL ────────────────────────────────────────
    def _check_b03(self, csm: CaseStateMachine) -> List[BugReport]:
        """B03: kausalitetsavvikelser, ogiltiga datum, ändrat före skapat."""
        bugs = []
        for r in csm.files:
            skapad = self._parse_date(r.metadata.skapad)
            andrad = self._parse_date(r.metadata.ändrad)
            if r.metadata.skapad not in ("", "KAN EJ VERIFIERAS") and skapad is None:
                bugs.append(BugReport(
                    bug_id=f"BUG_{BugCode.B03.name}_{r.file_id[:8]}_DATUM",
                    bug_kod=BugCode.B03,
                    beskrivning=f"Ogiltigt skapandedatum: {r.metadata.skapad} ({r.relative_path})",
                    fil=r.relative_path,
                    allvarlighet=self.BUG_SEVERITY["B03"],
                    rekommendation="Korrigera metadata så att datum följer ÅÅÅÅ-MM-DD.",
                ))
            if r.metadata.ändrad not in ("", "KAN EJ VERIFIERAS") and andrad is None:
                bugs.append(BugReport(
                    bug_id=f"BUG_{BugCode.B03.name}_{r.file_id[:8]}_AND_DATUM",
                    bug_kod=BugCode.B03,
                    beskrivning=f"Ogiltigt ändringsdatum: {r.metadata.ändrad} ({r.relative_path})",
                    fil=r.relative_path,
                    allvarlighet=self.BUG_SEVERITY["B03"],
                    rekommendation="Korrigera metadata så att datum följer ÅÅÅÅ-MM-DD.",
                ))
            if skapad and andrad and andrad < skapad:
                bugs.append(BugReport(
                    bug_id=f"BUG_{BugCode.B03.name}_{r.file_id[:8]}_KAUSALITET",
                    bug_kod=BugCode.B03,
                    beskrivning=(
                        f"Ändringsdatum ligger före skapandedatum "
                        f"({r.metadata.ändrad} < {r.metadata.skapad}) — kausalitetsavvikelse."
                    ),
                    fil=r.relative_path,
                    allvarlighet=self.BUG_SEVERITY["B03"],
                    rekommendation="Utred ändringshistoriken (chain of custody).",
                ))
        return bugs

    # ── B04: IDENTITETSFEL ──────────────────────────────────
    def _check_b04(self, csm: CaseStateMachine) -> List[BugReport]:
        """B04: tvetydiga roller, domstolsnamn eller ärendenummer i metadata."""
        bugs = []
        ids = [r.file_id for r in csm.files]
        if len(ids) != len(set(ids)):
            bugs.append(BugReport(
                bug_id=f"BUG_{BugCode.B04.name}_DUP_ID",
                bug_kod=BugCode.B04,
                beskrivning="Duplicerade file_id i materialet — identitetstvetydighet.",
                fil="ROOT",
                allvarlighet=self.BUG_SEVERITY["B04"],
                rekommendation="Tilldela unika ärende- och filidentiteter.",
            ))
        if csm.files and csm.domstol in ("", "EJ IDENTIFIERAD"):
            bugs.append(BugReport(
                bug_id=f"BUG_{BugCode.B04.name}_COURT",
                bug_kod=BugCode.B04,
                beskrivning=(
                    "Domstolsnamn eller centralt ärendenummer saknas i metadata "
                    "trots aktmaterial — tvetydig identitet."
                ),
                fil=csm.root_directory,
                allvarlighet=self.BUG_SEVERITY["B04"],
                rekommendation="Verifiera ärendeidentitet (domstol + målnummer) mot primärkälla.",
            ))
        return bugs

    # ── B05: FAKTAAVVIKELSE ─────────────────────────────────
    def _check_b05(self, csm: CaseStateMachine) -> List[BugReport]:
        """B05: motstridiga sakuppgifter/faktiska diskrepanser mellan källorna."""
        bugs = []
        for f in (csm.agent_a_findings + csm.agent_b_findings + csm.agent_c_findings):
            if f.get("allvarlighet") not in ("HÖG", "KRITISK"):
                continue
            text = f"{f.get('beskrivning', '')} {f.get('typ', '')}".upper()
            if any(t in text for t in ("MOTSÄGELSE", "MOTSAGELSE", "DISKREPAN", "AVVIKER")):
                bugs.append(BugReport(
                    bug_id=f"BUG_{BugCode.B05.name}_AGENT_{f.get('agent', '?')}",
                    bug_kod=BugCode.B05,
                    beskrivning=f"Motstridiga sakuppgifter i källorna: {f.get('beskrivning', '')}",
                    fil=csm.root_directory,
                    allvarlighet=self.BUG_SEVERITY["B05"],
                    rekommendation="Stäm av primärkällorna och redovisa diskrepansen explicit.",
                ))
        return bugs

    # ── B06: BEVISAVVIKELSE ─────────────────────────────────
    def _check_b06(self, csm: CaseStateMachine) -> List[BugReport]:
        """B06: SUPPORTS-koppling saknar substans eller bryter beviskraven."""
        bugs = []
        by_id = {r.file_id: r for r in csm.files}
        for e in csm.graph.edges:
            if e.edge_type != EdgeType.SUPPORTS:
                continue
            src = by_id.get(e.anchor.source_id) if e.anchor else None
            if src is not None and src.evidence_category != EvidenceCategory.A_STRONG:
                bugs.append(BugReport(
                    bug_id=f"BUG_{BugCode.B06.name}_{e.edge_id}",
                    bug_kod=BugCode.B06,
                    beskrivning=(
                        f"SUPPORTS-kant {e.edge_id} bygger på {e.anchor.source_id} "
                        f"som inte är Kategori A (beviskrav ej uppfyllt)."
                    ),
                    fil=e.edge_id,
                    allvarlighet=self.BUG_SEVERITY["B06"],
                    rekommendation="Kärnslutsatser får endast stödjas av Kategori A-material.",
                ))
        return bugs
    # ── B07: UTELÄMNANDE ────────────────────────────────────
    def _check_b07(self, csm: CaseStateMachine) -> List[BugReport]:
        """B07: relevanta originaldokument utan motsvarande nod i relationsgrafen."""
        bugs = []
        if csm.total_files == 0:
            bugs.append(BugReport(
                bug_id=f"BUG_{BugCode.B07.name}_NO_FILES",
                bug_kod=BugCode.B07,
                beskrivning="Inga filer hittades i angiven root-mapp — utelämnande.",
                fil=csm.root_directory,
                allvarlighet=self.BUG_SEVERITY["B07"],
                rekommendation="Kontrollera sökväg och behörigheter. Kör om ingestion.",
            ))
            return bugs
        if csm.graph.nodes:
            nod_ids = set(csm.graph.nodes)
            saknade = [r.file_id for r in csm.files if r.file_id not in nod_ids]
            if saknade:
                bugs.append(BugReport(
                    bug_id=f"BUG_{BugCode.B07.name}_UTELÄMNADE_NODER",
                    bug_kod=BugCode.B07,
                    beskrivning=(
                        f"{len(saknade)} originaldokument saknar motsvarande nod i "
                        f"relationsgrafen (t.ex. {saknade[0]})."
                    ),
                    fil=csm.root_directory,
                    allvarlighet=self.BUG_SEVERITY["B07"],
                    rekommendation="Säkerställ att varje baslinjedokument finns som nod.",
                ))
        return bugs

    # ── B08: PROCESSFEL ─────────────────────────────────────
    def _check_b08(self, csm: CaseStateMachine) -> List[BugReport]:
        """B08: handläggningsfel, fristöverskridanden eller behörighetsbrister."""
        bugs = []
        contaminated = [
            r for r in csm.files
            if r.quarantine_flag and r.evidence_category == EvidenceCategory.A_STRONG
        ]
        if contaminated:
            bugs.append(BugReport(
                bug_id=f"BUG_{BugCode.B08.name}_CATEGORY_MIX",
                bug_kod=BugCode.B08,
                beskrivning=(
                    f"KATEGORIBLANDNING: {len(contaminated)} karantän-filer "
                    f"felaktigt klassificerade som A_STRONG"
                ),
                fil=contaminated[0].relative_path,
                allvarlighet="KRITISK",
                rekommendation=(
                    "A och B får ALDRIG blandas i argumentation. "
                    "Klassificera om och isolera karantänmaterialet."
                ),
            ))
        return bugs

    # ── B09: RÄTTSKÄLLEFEL ──────────────────────────────────
    def _check_b09(self, csm: CaseStateMachine) -> List[BugReport]:
        """B09: rättskälleverifiering misslyckad (FIX-T-risk, sekundärkälla osäker)."""
        bugs = []
        for sok in csm.legal_source_verifications:
            status = sok.get("status", "")
            klar = sok.get("klar", 0)
            agenter = sok.get("agenter", 0)
            if status in ("FEL", "TIMEOUT") or (agenter > 0 and klar < agenter):
                bugs.append(BugReport(
                    bug_id=f"BUG_{BugCode.B09.name}_{sok.get('sokterm', '?')[:16]}",
                    bug_kod=BugCode.B09,
                    beskrivning=(
                        f"Rättskälleverifiering misslyckades för '{sok.get('sokterm', '')}' "
                        f"(status: {status}, {klar}/{agenter} agenter klara)."
                    ),
                    fil=sok.get("sokterm", ""),
                    allvarlighet=self.BUG_SEVERITY["B09"],
                    rekommendation=(
                        "Verifiera lagversions giltighet vid händelsetidpunkten "
                        "(FIX-T). Slutsatsen får inte bygga på overifierad rättskälla."
                    ),
                ))
        return bugs

    # ── B10: REKVISITFEL ────────────────────────────────────
    def _check_b10(self, csm: CaseStateMachine) -> List[BugReport]:
        """B10: nödvändigt MUST-rekvisit utan bevisning (ej uppfyllt/olöst)."""
        bugs = []
        for s in csm.subsumtioner:
            if s.status in ("EJ_UPPFYLLT", "UNRESOLVED"):
                bugs.append(BugReport(
                    bug_id=f"BUG_{BugCode.B10.name}_{s.sub_id}",
                    bug_kod=BugCode.B10,
                    beskrivning=(
                        f"MUST-rekvisit '{s.requisite}' har status {s.status} "
                        f"utan uppfylld bevisning."
                    ),
                    fil=s.evidence_id or "SUMSUMPTION",
                    allvarlighet=self.BUG_SEVERITY["B10"],
                    rekommendation=(
                        "Ett nödvändigt rekvisit får aldrig förbigås — "
                        "markera BEVISNING_SAKNAS och avstå från slutsats."
                    ),
                ))
        return bugs
    # ── B11: SUBSUMTIONSFEL ─────────────────────────────────
    def _check_b11(self, csm: CaseStateMachine) -> List[BugReport]:
        """B11: slutsats direkt från råfakta utan rekvisitprövning (logiska hopp)."""
        bugs = []
        if csm.judgment_draft is not None and not csm.subsumtioner:
            bugs.append(BugReport(
                bug_id=f"BUG_{BugCode.B11.name}_HOPP",
                bug_kod=BugCode.B11,
                beskrivning=(
                    "Domsutkast producerat utan att någon subsumtionskedja "
                    "har passerat rekvisitprövningen — logiskt hopp."
                ),
                fil="JUDGMENT_DRAFT",
                allvarlighet=self.BUG_SEVERITY["B11"],
                rekommendation=(
                    "Slutsats får aldrig dras direkt från råfakta — "
                    "kräv explicit rekvisitprövning per MUST-rekvisit."
                ),
            ))
        for s in csm.subsumtioner:
            if s.status == "UNRESOLVED" and s.anchor is None:
                bugs.append(BugReport(
                    bug_id=f"BUG_{BugCode.B11.name}_{s.sub_id}_ANCHOR",
                    bug_kod=BugCode.B11,
                    beskrivning=(
                        f"Subsumtion {s.sub_id} saknar verifierat källankare "
                        f"(rekvisit '{s.requisite}') — kedjan kan inte verifieras."
                    ),
                    fil=s.evidence_id or "SUBSUMTION",
                    allvarlighet=self.BUG_SEVERITY["B11"],
                    rekommendation="Kräv VerbatimAnchor per kedjeled.",
                ))
        return bugs

    # ── B12: DOMSKÄLSFEL ────────────────────────────────────
    def _check_b12(self, csm: CaseStateMachine) -> List[BugReport]:
        """B12: cirkulär motivering eller allvarlig asymmetri i parternas omständigheter."""
        bugs = []
        draft = csm.judgment_draft
        if draft is not None:
            stark = draft.stärkande_omständigheter or []
            friande = draft.friande_omständigheter or []
            if (stark and not friande) or (friande and not stark):
                bugs.append(BugReport(
                    bug_id=f"BUG_{BugCode.B12.name}_ASYMMETRI",
                    bug_kod=BugCode.B12,
                    beskrivning=(
                        f"Domsskälsasymmetri (P18): {len(stark)} stärkande men "
                        f"{len(friande)} friande omständigheter — parterna behandlas olika."
                    ),
                    fil="JUDGMENT_DRAFT",
                    allvarlighet=self.BUG_SEVERITY["B12"],
                    rekommendation="Redovisa båda parters omständigheter med identisk rigor.",
                ))
            if draft.provisional_conclusion != "UNRESOLVED — OTILLRÄCKLIGT UNDERLAG" \
                    and not draft.symmetry_verified:
                bugs.append(BugReport(
                    bug_id=f"BUG_{BugCode.B12.name}_CIRKULÄR",
                    bug_kod=BugCode.B12,
                    beskrivning=(
                        "Provisorisk slutsats formulerad utan verifierad "
                        "partsymmetri — risk för cirkulär motivering."
                    ),
                    fil="JUDGMENT_DRAFT",
                    allvarlighet=self.BUG_SEVERITY["B12"],
                    rekommendation="Kör P18-symmetrikontroll före slutsats.",
                ))
        return bugs
    # ── B13: BEVISKRAVSFEL ──────────────────────────────────
    def _check_b13(self, csm: CaseStateMachine) -> List[BugReport]:
        """B13: felaktigt/otydligt beviskrav (t.ex. 'sannolikt' i brottmål)."""
        bugs = []
        for f in (csm.agent_a_findings + csm.agent_b_findings + csm.agent_c_findings):
            text = f"{f.get('beskrivning', '')} {f.get('typ', '')}".lower()
            if any(t in text for t in ("sannolikt", "procent", "beviskrav", "övervikt")):
                bugs.append(BugReport(
                    bug_id=f"BUG_{BugCode.B13.name}_AGENT_{f.get('agent', '?')}",
                    bug_kod=BugCode.B13,
                    beskrivning=(
                        f"Otydligt/felaktigt beviskrav antytt i analys: {f.get('beskrivning', '')}"
                    ),
                    fil=csm.root_directory,
                    allvarlighet=self.BUG_SEVERITY["B13"],
                    rekommendation=(
                        "Precisera beviskrav enligt processordning "
                        "(ställt utom rimligt tvivel / sannolikhetsövervikt)."
                    ),
                ))
        return bugs

    # ── B14: INTERN MOTSÄGELSE ──────────────────────────────
    def _check_b14(self, csm: CaseStateMachine) -> List[BugReport]:
        """B14: två verifierade grafkanter direkt motsäger varandra i relationsgrafen."""
        bugs = []
        quarantined_ids = {r.file_id for r in csm.files if r.quarantine_flag}
        for e in csm.graph.edges:
            if (e.edge_type == EdgeType.SUPPORTS
                    and (e.from_node in quarantined_ids or e.to_node in quarantined_ids)):
                bugs.append(BugReport(
                    bug_id=f"BUG_{BugCode.B14.name}_{e.edge_id}",
                    bug_kod=BugCode.B14,
                    beskrivning=(
                        f"Karantän-material ingår i SUPPORTS-kant utan formellt "
                        f"åberopande: {e.edge_id} ({e.from_node} → {e.to_node})"
                    ),
                    fil=e.edge_id,
                    allvarlighet="KRITISK",
                    rekommendation=(
                        "Material måste formellt åberopas av part innan det "
                        "kan ingå i primäranalys (GATING/SUBSUMPTION)."
                    ),
                ))
        for e in csm.graph.edges:
            if e.edge_type == EdgeType.CONTRADICTS:
                bugs.append(BugReport(
                    bug_id=f"BUG_{BugCode.B14.name}_{e.edge_id}",
                    bug_kod=BugCode.B14,
                    beskrivning=(
                        f"Explicit CONTRADICTS-kant i relationsgrafen: "
                        f"{e.from_node} → {e.to_node}"
                    ),
                    fil=e.edge_id,
                    allvarlighet=self.BUG_SEVERITY["B14"],
                    rekommendation="Lös källmotsägelsen mot primärkällorna före slutsats.",
                ))
        return bugs
    # ── B15: OUPPLÖST FRÅGA ─────────────────────────────────
    def _check_b15(self, csm: CaseStateMachine) -> List[BugReport]:
        """B15: öppna/tvistiga punkter lämnade utan slutlig status (UNRESOLVED)."""
        bugs = []
        total = len(csm.graph.edges)
        unresolved = csm.graph.unresolved_count
        if total > 0 and unresolved > 0:
            pct = unresolved / total
            bugs.append(BugReport(
                bug_id=f"BUG_{BugCode.B15.name}_UNRESOLVED",
                bug_kod=BugCode.B15,
                beskrivning=(
                    f"OUPPLÖSTA KANTER: {unresolved}/{total} "
                    f"({pct:.0%}) saknar verifierat verbatim-ankare"
                ),
                fil="RELATIONSGRAFEN",
                allvarlighet=self.BUG_SEVERITY["B15"],
                rekommendation=(
                    "Varje öppen/tvistig punkt kräver slutlig status "
                    "(upplöst, nedprioriterad eller uttryckligen oavgjord)."
                ),
            ))
        return bugs

# AGENT 7: FALSIFICATION ENGINE (v10 — ny, avgörande)
# ─────────────────────────────────────────────────────────────────────────────
class FalsificationEngine:
    """
    Tvingar systemet att bevisa MOTSATSEN till sin primära slutsats.

    Algoritm:
    1. Antag att den primära slutsatsen är FALSK.
    2. Konstruera den starkaste möjliga motkedjan från tillgängligt material.
    3. Testa motkedjan: kollapsar den i HARD_STOP → slutsatsen är ROBUST.
    4. Håller motkedjan → slutsatsen är VULNERABLE.

    Ingen preliminär slutsats produceras utan att detta steg körts.
    """

    def run(
        self,
        graph: RelationGraph,
        passed_records: List[FileRecord],
        a_findings: List[Dict],
    ) -> Tuple[str, str, List[Dict]]:
        """
        Returnerar (verdict, chain_strength, counter_chain).
        verdict: FalsificationVerdict
        """
        log.info("[FALSIFICATION] Konstruerar motkedja...")

        # Bygg motkedja från B_RISK-material och UNRESOLVED-kanter
        b_risk = [r for r in passed_records if r.evidence_category == EvidenceCategory.B_RISK]
        unres_edges = [e for e in graph.edges if e.edge_type == EdgeType.UNRESOLVED]
        contradicts = [e for e in graph.edges if e.edge_type == EdgeType.CONTRADICTS]

        counter_chain: List[Dict] = []

        # Steg 1: Svaga länk — alla A-filer med ej-verifierad integritet
        weak_a = [
            r for r in passed_records
            if r.evidence_category == EvidenceCategory.A_STRONG
            and r.metadata.integritet != IntegrityStatus.VERIFIED
        ]
        if weak_a:
            counter_chain.append({
                "led":       "SVAGASTE_LÄNK",
                "argument":  (
                    f"{len(weak_a)} kärnbevis (Kategori A) saknar verifierad integritet — "
                    f"kan utmanas: {weak_a[0].relative_path}"
                ),
                "styrka":    "HÖG",
            })

        # Steg 2: Oupplösta ankare ger öppning för motpart
        if unres_edges:
            counter_chain.append({
                "led":      "OUPPLÖSTA_RELATIONER",
                "argument": (
                    f"{len(unres_edges)} grafkanter saknar verbatim-ankare — "
                    f"motpart kan ifrågasätta varje sådan kant"
                ),
                "styrka":   "MEDEL" if len(unres_edges) < 5 else "HÖG",
            })

        # Steg 3: Explicita motsägelser
        if contradicts:
            counter_chain.append({
                "led":      "EXPLICITA_MOTSÄGELSER",
                "argument": (
                    f"{len(contradicts)} CONTRADICTS-kanter i grafen — "
                    f"motpart har direkta motbevis"
                ),
                "styrka":   "HÖG",
            })

        # Steg 4: Agent A-avvikelser
        critical_a = [f for f in a_findings if f.get("allvarlighet") in ("HÖG", "KRITISK")]
        if critical_a:
            counter_chain.append({
                "led":      "AUDIT_A_AVVIKELSER",
                "argument": (
                    f"{len(critical_a)} höga/kritiska avvikelser från Audit-A — "
                    f"beviskedjan har identifierade svagheter"
                ),
                "styrka":   "HÖG",
            })

        # Utvärdera om motkedjan kollapsar
        high_strength = sum(1 for c in counter_chain if c.get("styrka") == "HÖG")
        total_leads   = len(counter_chain)

        if total_leads == 0:
            verdict        = FalsificationVerdict.INCONCLUSIVE
            chain_strength = "OTILLRÄCKLIGT UNDERLAG FÖR FALSIFIERING"
        elif high_strength == 0:
            # Motkedjan har bara svaga argument → kollapsar → ROBUST
            verdict        = FalsificationVerdict.ROBUST
            chain_strength = "MOTKEDJAN KOLLAPSADE — SLUTSATS ROBUST"
        elif high_strength >= 2:
            # Motkedjan håller → slutsatsen är VULNERABLE
            verdict        = FalsificationVerdict.VULNERABLE
            chain_strength = (
                f"MOTKEDJAN HÅLLER ({high_strength} starka led) — "
                f"SLUTSATS EJ ROBUST — KRÄVER YTTERLIGARE BEVISNING"
            )
        else:
            verdict        = FalsificationVerdict.VULNERABLE
            chain_strength = (
                f"MOTKEDJAN DELVIS STARK ({high_strength} starkt led) — "
                f"SLUTSATS VILLKORLIGT ROBUST"
            )

        log.info(f"[FALSIFICATION] Verdict: {verdict} | {chain_strength}")
        return verdict, chain_strength, counter_chain


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 8: JUDGMENT DRAFT ENGINE (v10 — PROVISIONAL ONLY)
# ─────────────────────────────────────────────────────────────────────────────
class JudgmentDraftEngine:
    """
    Producerar PROVISORISKT DOMSUTKAST — aldrig ett dömande mandat.

    P18 Symmetriregeln: Stärkande OCH friande omständigheter redovisas
    med identisk analytisk rigor.

    AI:n saknar dömande mandat. Domstolen avgör självständigt.
    """

    def draft(
        self,
        passed_records: List[FileRecord],
        a_findings:     List[Dict],
        b_findings:     List[Dict],
        falsification_verdict: str,
        graph:          RelationGraph,
        case_meta:      Dict,
    ) -> JudgmentDraftSection:
        section_id = f"JD-{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        # Stärkande omständigheter (Kategori A, verifierade)
        stärkande = [
            f"[VERIFIERAT] {r.relative_path} | "
            f"SHA-256: {r.metadata.hash_sha256[:16]}... | "
            f"Kategori: A_STRONG"
            for r in passed_records
            if r.evidence_category == EvidenceCategory.A_STRONG
            and r.metadata.integritet == IntegrityStatus.VERIFIED
        ]

        # Friande/motsägande omständigheter (P18 kräver symmetri)
        friande = [
            f"[OUPPLÖST] {f.get('beskrivning', '')[:80]}"
            for f in a_findings
            if f.get("allvarlighet") in ("HÖG", "KRITISK")
        ]

        # Preliminär slutsats baseras på falsifieringsresultatet
        if falsification_verdict == FalsificationVerdict.ROBUST:
            conclusion = (
                "PROVISORISK BEDÖMNING: Primär beviskedja verifierad och robust "
                "— motkedja kollapsade. Domstolen bör pröva rekvisituppfyllelse."
            )
        elif falsification_verdict == FalsificationVerdict.VULNERABLE:
            conclusion = (
                "PROVISORISK BEDÖMNING: Beviskedja SÅRBAR — motkedja håller. "
                "Kompletterande bevisning rekommenderas innan rekvisitprövning."
            )
        else:
            conclusion = (
                "PROVISORISK BEDÖMNING: OTILLRÄCKLIGT UNDERLAG — "
                "Falsifiering ej möjlig. Status: UNRESOLVED."
            )

        # Bygg subsumtioner per kärnbevis
        subs: List[SubsumptionRecord] = []
        for i, r in enumerate(passed_records[:5], 1):  # max 5 i draft
            anchor = VerbatimAnchor(
                source_id=r.file_id,
                source_path=r.relative_path,
                source_hash=r.metadata.hash_sha256,
                page_or_time="FILNIVÅ",
                verbatim_quote=(
                    f"[FILREFERENS: {r.relative_path} | "
                    f"SHA-256: {r.metadata.hash_sha256[:16]}...]"
                    if r.metadata.hash_sha256 != "KAN EJ VERIFIERAS"
                    else "[SAKNAR CITAT]"
                ),
                verified=(r.metadata.hash_sha256 != "KAN EJ VERIFIERAS"),
            )
            subs.append(SubsumptionRecord(
                sub_id=f"SUB-{i:03d}",
                legal_rule=case_meta.get("legal_rule", "EJ IDENTIFIERAD"),
                requisite=case_meta.get("requisite", "EJ IDENTIFIERAD"),
                legal_fact=r.relative_path,
                evidence_id=r.file_id,
                anchor=anchor,
                status=(
                    "UPPFYLLT"
                    if r.evidence_category == EvidenceCategory.A_STRONG
                    and r.metadata.integritet == IntegrityStatus.VERIFIED
                    else "UNRESOLVED"
                ),
                legal_consequence="KAN EJ AVGÖRAS UTAN FULLSTÄNDIG RÄTTSANALYS",
            ))

        symmetry_ok = len(stärkande) > 0 and len(friande) > 0

        draft = JudgmentDraftSection(
            section_id=section_id,
            yrkande=case_meta.get("yrkande", "EJ ANGIVET"),
            grunder=case_meta.get("grunder", ["EJ ANGIVNA"]),
            stärkande_omständigheter=stärkande,
            friande_omständigheter=friande if friande else ["[INGA FRIANDE OMSTÄNDIGHETER IDENTIFIERADE]"],
            subsumtioner=subs,
            provisional_conclusion=conclusion,
            symmetry_verified=symmetry_ok,
        )

        log.info(
            f"[JUDGMENT_DRAFT] {section_id} | "
            f"Stärkande: {len(stärkande)} | Friande: {len(friande)} | "
            f"Symmetri: {symmetry_ok}"
        )
        return draft


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 9: SELF-HEALING ENGINE (v10 — ny)
# ─────────────────────────────────────────────────────────────────────────────
class SelfHealingEngine:
    """
    Identifierade logiska glapp → inverterade säkerhetsregler (patcher).
    Patcharna lagras i ReproducibilityRecord och kan återanvändas
    i framtida körningar för att förhindra upprepning.

    OBS: "Self-healing" här betyder endast regelbaserade korrigeringar
    (fasta if/regler) — ingen adaptiv eller inlärande komponent.
    """

    def heal(
        self,
        a_findings: List[Dict],
        c_findings: List[Dict],
        blocked:    List[FileRecord],
        graph:      RelationGraph,
        reproducibility: ReproducibilityRecord,
    ) -> Tuple[List[SelfHealingPatch], ReproducibilityRecord]:
        patches: List[SelfHealingPatch] = []

        # Patch 1: UNRESOLVED-kanter → regel om obligatorisk ankare
        unres = graph.unresolved_count
        if unres > 0:
            patches.append(SelfHealingPatch(
                patch_id=f"PATCH-{len(patches)+1:03d}",
                trigger=f"{unres} UNRESOLVED-kanter detekterade",
                gap_found="Grafkanter utan VerbatimAnchor skapar bevisningsluckor",
                rule_added=(
                    "SÄKERHETSREGEL: Alla grafkanter MÅSTE ha giltig VerbatimAnchor "
                    "med SHA-256-verifierad primärkälla. "
                    "Saknas ankare → kanten är UNRESOLVED och får ej ingå i subsumtion."
                ),
                severity="HÖG",
            ))

        # Patch 2: Blockerade filer → regel om explicit åberopande
        if blocked:
            patches.append(SelfHealingPatch(
                patch_id=f"PATCH-{len(patches)+1:03d}",
                trigger=f"{len(blocked)} filer blockerade av SubsumptionGatekeeper",
                gap_found="Oombett/ej-åberopat material riskerar att kontaminera analys",
                rule_added=(
                    "SÄKERHETSREGEL: Karantänmaterial tilldelas UNSOLICITED_INPUT + "
                    "NOT_YET_PLEADED vid ingestion. "
                    "Formellt åberopande krävs innan SubsumptionGatekeeper godkänner. "
                    "Delta-rapport genereras separat."
                ),
                severity="KRITISK",
            ))

        # Patch 3: Cirkelresonemang-varning → regel
        circular = [f for f in c_findings if f.get("kontroll") == "CIRCULAR_REASONING_BLOCKER"]
        if circular:
            patches.append(SelfHealingPatch(
                patch_id=f"PATCH-{len(patches)+1:03d}",
                trigger=f"{len(circular)} circular-reasoning-varningar",
                gap_found="Möjligt att domens text används som fakta (cirkelresonemang)",
                rule_added=(
                    "SÄKERHETSREGEL: CIRCULAR_REASONING_BLOCKER aktiverad. "
                    "Domen används ALDRIG som facit för vad primärkällan innehåller. "
                    "Riktning: PRIMÄRKÄLLA → TRANSKRIPTION → DOMENS PÅSTÅENDE. "
                    "Förbjuden riktning: DOM → PRIMÄRKÄLLA."
                ),
                severity="KRITISK",
            ))

        # Patch 4: Hallucination-risk
        halluc = [f for f in c_findings if f.get("kontroll") == "HALLUCINATION_RISK"]
        if halluc:
            patches.append(SelfHealingPatch(
                patch_id=f"PATCH-{len(patches)+1:03d}",
                trigger="Hallucination-risk identifierad av Audit-C",
                gap_found="För många påståenden utan primärkälla",
                rule_added=(
                    "SÄKERHETSREGEL: ZERO_INFERENCE_POLICY skärpt. "
                    "Inga påståenden utan verifierat primärkällecitat. "
                    "Status: KAN EJ VERIFIERAS om citat saknas."
                ),
                severity="KRITISK",
            ))

        # Registrera patcher i ReproducibilityRecord
        reproducibility.patches.extend(patches)

        log.info(f"[SELF_HEALING] {len(patches)} patcher genererade")
        return patches, reproducibility


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT
# ─────────────────────────────────────────────────────────────────────────────
def export_json(csm: CaseStateMachine, output_path: str) -> str:
    """Exporterar komplett CaseStateMachine som JSON."""
    data = {
        "AUDIT_TELEMETRY_V10": {
            "engine_version":        MOTOR_VERSION,
            "scan_timestamp":        SCAN_TIMESTAMP,
            "case_id":               csm.case_id,
            "final_state":           csm.current_state,
            "total_files":           csm.total_files,
            "locked_baseline":       csm.locked_count,
            "quarantine":            csm.quarantine_count,
            "category_a":            csm.category_a,
            "category_b":            csm.category_b,
            "gatekeeper_passed":     csm.gatekeeper_passed,
            "gatekeeper_blocked":    csm.gatekeeper_blocked,
            "graph_nodes":           len(csm.graph.nodes),
            "graph_edges":           len(csm.graph.edges),
            "graph_verified_edges":  csm.graph.verified_count,
            "graph_unresolved":      csm.graph.unresolved_count,
            "subsumtioner":          len(csm.subsumtioner),
            "agent_a_findings":      len(csm.agent_a_findings),
            "agent_b_findings":      len(csm.agent_b_findings),
            "agent_c_findings":      len(csm.agent_c_findings),
            "falsification_verdict": _to_json(csm.falsification_verdict),
            "counter_chain_strength": csm.counter_chain_strength,
            "patches":               len(csm.patches),
            "hard_stop":             csm.hard_stop,
            "hard_stop_reason":      csm.hard_stop_reason,
            "audit_status":          _to_json(csm.audit_status),
            "sårbarhet_risk":        csm.sårbarhet_risk,
            "active_modules":        csm.active_modules,
            "hallucination_check":   "ZERO_INFERENCE_POLICY_ACTIVE",
            "circular_reasoning":    "CIRCULAR_REASONING_BLOCKER_ACTIVE",
            "verbatim_gate":         "VERBATIM_ANCHOR_GATE_ACTIVE",
            "subsumption_gate":      "SUBSUMPTION_GATEKEEPER_ACTIVE",
            "standard_iso":          "ISO/IEC 27037:2012",   # etikett i rapportutdata — ej certifieringsclaim
            "standard_enfsi":        "ENFSI FSA-BPM-002 FIXED-2026",  # etikett i rapportutdata — ej certifieringsclaim
        },
        "CASE_STATE_MACHINE": _to_json(csm),
    }
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info(f"[EXPORT] JSON: {out}")
    return str(out)


def export_markdown(csm: CaseStateMachine, output_path: str) -> str:
    """Exporterar strukturerad Markdown-rapport (Avsnitt A/B/C + teknisk audit)."""
    g   = csm.graph.summary()
    jd  = csm.judgment_draft

    lines = [
        f"# FORENSIC COURT AUDIT RAPPORT",
        f"## SVENSK FORENSIC COURT AUDIT ENGINE v{MOTOR_VERSION}",
        f"",
        f"> **ABSOLUT FÖRBUD:** Detta är ett PROVISORISKT ANALYSUNDERLAG.",
        f"> AI:n saknar dömande mandat. Domstolen avgör självständigt.",
        f"",
        f"| Fält | Värde |",
        f"|------|-------|",
        f"| Case ID | `{csm.case_id}` |",
        f"| Tidsstämpel | `{SCAN_TIMESTAMP}` |",
        f"| Motorversion | `v{MOTOR_VERSION}` |",
        f"| Slutstatus | `{_to_json(csm.current_state)}` |",
        f"| Domstol | {csm.domstol} |",
        f"| Processform | {csm.processform} |",
        f"| Audit-status | `{_to_json(csm.audit_status)}` |",
        f"| Falsifiering | **{_to_json(csm.falsification_verdict)}** |",
        f"",
        f"---",
        f"",
        f"## AVSNITT A: LÅST BEVISBALANS (LOCKED_BASELINE)",
        f"",
        f"| Nyckeltal | Värde |",
        f"|-----------|-------|",
        f"| Totalt antal filer | {csm.total_files} |",
        f"| Locked Baseline | {csm.locked_count} |",
        f"| Karantän | {csm.quarantine_count} |",
        f"| Kategori A (Stark) | {csm.category_a} |",
        f"| Kategori B (Risk) | {csm.category_b} |",
        f"| Gatekeeper godkänd | {csm.gatekeeper_passed} |",
        f"| Gatekeeper blockerad | {csm.gatekeeper_blocked} |",
        f"| Namnbaserad kategorisering | {'JA' if csm.name_categorization_ran else 'NEJ'} |",
        f"",
        f"### Namnbaserad kategorisering (filnamn/sökväg)",
        f"",
        f"_Läser aldrig filinnehåll. Endast struktureringshjälp — ingen juridisk slutsats._",
        f"",
        f"| Namnkategori | Antal |",
        f"|--------------|-------|",
    ]
    if csm.name_categorization_summary:
        for k, v in sorted(csm.name_categorization_summary.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"| {k} | {v} |")
    else:
        lines.append("| — | 0 |")
    # Pre-trial objectives
    lines += [
        f"",
        f"## PRE-TRIAL OBJECTIVES (prövningsmål)",
        f"",
        f"_Konstrueras före juridisk slutanalys. Ingen bedömning av utgång. "
        f"Luckor förblir luckor._",
        f"",
    ]
    pt = csm.pre_trial
    if pt:
        lines += [
            f"| Fält | Värde |",
            f"|------|-------|",
            f"| Readiness | **{pt.readiness}** |",
            f"",
            f"### Vad skall avgöras?",
            f"",
        ]
        if pt.vad_skall_avgoras:
            for x in pt.vad_skall_avgoras:
                lines.append(f"- {x}")
        else:
            lines.append("- _Ej angivet — motorn gissar inte._")
        lines += [f"", f"### Ostridigt (materialstatus)", f""]
        if pt.ostridigt:
            for x in pt.ostridigt:
                lines.append(f"- {x}")
        else:
            lines.append("- _Inget strukturellt ostridigt registrerat._")
        lines += [f"", f"### Tvistigt / oklart (materialstatus)", f""]
        if pt.tvistigt:
            for x in pt.tvistigt:
                lines.append(f"- {x}")
        else:
            lines.append("- _Inga materialstatus-oklarheter flaggade._")
        lines += [f"", f"### Krävt underlag (utifrån angiven metadata)", f""]
        for title, lst in (
            ("Rättsfakta", pt.required_legal_facts),
            ("Bevisning", pt.required_evidence),
            ("Rättskällor", pt.required_legal_sources),
        ):
            lines.append(f"**{title}:**")
            if lst:
                for x in lst:
                    lines.append(f"- {x}")
            else:
                lines.append("- _Ej specificerbart utan ytterligare metadata/material._")
            lines.append("")
        lines += [f"### Luckor", f""]
        if pt.gaps:
            for x in pt.gaps:
                lines.append(f"- {x}")
        else:
            lines.append("- _Inga automatiskt identifierade luckor._")
        if pt.notes:
            lines += [f"", f"### Noter", f""]
            for x in pt.notes:
                lines.append(f"- {x}")
    else:
        lines.append("_Pre-trial objectives kördes inte._")

    lines += [
        f"",
        f"### Relationsgrafen",
        f"",
        f"| Graf-nyckeltal | Värde |",
        f"|----------------|-------|",
        f"| Noder | {g['total_nodes']} |",
        f"| Kanter totalt | {g['total_edges']} |",
        f"| Verifierade kanter | {g['verified_edges']} |",
        f"| UNRESOLVED kanter | {g['unresolved_edges']} |",
        f"| Verifieringsgrad | {g['pct_verified']} |",
        f"| Motsägelser | {g['contradictions']} |",
        f"",
    ]

    # Kärnbevis (Kategori A, verifierade)
    a_files = [
        r for r in csm.files
        if r.evidence_category == EvidenceCategory.A_STRONG
        and r.metadata.integritet == IntegrityStatus.VERIFIED
        and r.gatekeeper_passed
    ][:10]
    if a_files:
        lines += [
            f"### Styrkta omständigheter och kärnbevis (Kategori A, Gatekeeper-godkänd)",
            f"",
        ]
        for r in a_files:
            lines.append(
                f"- `{r.relative_path}` | SHA-256: `{r.metadata.hash_sha256[:16]}...` | "
                f"Modul: `{r.baseline_state}`"
            )
        lines.append("")

    lines += [
        f"---",
        f"",
        f"## AVSNITT B: KARANTÄNSRAPPORT (DELTA-ANALYS)",
        f"",
        f"Oombett/nytt material — kräver formellt åberopande för primäranalys.",
        f"",
    ]
    b_files = [r for r in csm.files if r.quarantine_flag][:10]
    if b_files:
        for r in b_files:
            lines.append(
                f"- `{r.relative_path}` | Status: `{r.procedural_status}` | "
                f"Kategori: `{r.evidence_category}`"
            )
    else:
        lines.append("_Inga karantänfiler identifierade._")

    lines += [
        f"",
        f"---",
        f"",
        f"## AVSNITT C: PROCESSUELL ÅTGÄRDSLISTA",
        f"",
    ]
    if csm.processuell_åtgärdslista:
        for a in csm.processuell_åtgärdslista:
            lines.append(f"- {a}")
        lines.append("")
    if csm.patches:
        for p in csm.patches:
            lines.append(f"**[{p.patch_id}]** `{p.severity}` — {p.rule_added}")
            lines.append("")
    if not csm.processuell_åtgärdslista and not csm.patches:
        lines.append("_Inga patcher eller åtgärder genererade._")

    # CounterAuditAgent — buggregister (B01–B15, porterat från v9.9.0)
    lines += [
        f"",
        f"---",
        f"",
        f"## MOTREVISION — BUGGREGISTER (COUNTERAUDITAGENT)",
        f"",
        f"**Sårbarhetsrisk:** {csm.sårbarhet_risk}",
        f"",
    ]
    if csm.bugs:
        lines += [
            f"| Kod | Allvarlighet | Beskrivning | Fil |",
            f"|-----|-------------|-------------|-----|",
        ]
        for b in csm.bugs:
            lines.append(
                f"| `{b.bug_kod}` | **{b.allvarlighet}** | "
                f"{b.beskrivning[:80]} | `{b.fil}` |"
            )
    else:
        lines.append("_Inga avvikelser identifierade av motrevisionen._")

    # Rättskällesökning (deep_search_pipeline.py, v9.8.1) — verifiering,
    # ersätter aldrig juridisk analys.
    lines += [
        f"",
        f"---",
        f"",
        f"## RÄTTSKÄLLESÖKNING (VERIFIERING — EJ JURIDISK ANALYS)",
        f"",
    ]
    if csm.legal_source_verifications:
        for sok in csm.legal_source_verifications:
            if sok.get("status") == "FEL":
                lines.append(f"- Sökning misslyckades: `{sok.get('fel', 'okänt fel')}`")
                continue
            lines.append(
                f"- Sökterm `{sok.get('sokterm', '')}`: "
                f"{sok.get('klar', 0)}/{sok.get('agenter', 0)} källagenter klara, "
                f"{sok.get('fel', 0)} fel"
            )
    else:
        lines.append(
            "_Ingen rättskällesökning kördes (LEGAL_SOURCE ej aktiv, "
            "ingen sökterm angiven, eller deep_search_pipeline saknas)._"
        )

    # Falsifiering
    lines += [
        f"---",
        f"",
        f"## FALSIFIERING & MOTREVISION",
        f"",
        f"**Verdict:** `{_to_json(csm.falsification_verdict)}`",
        f"",
        f"**Motkedjestyrka:** {csm.counter_chain_strength}",
        f"",
    ]

    # Domsutkast (PROVISIONAL)
    if jd:
        lines += [
            f"---",
            f"",
            f"## PROVISORISKT DOMSUTKAST (ALDRIG DÖMANDE MANDAT)",
            f"",
            f"> {jd.mandate_warning}",
            f"",
            f"**Yrkande:** {jd.yrkande}",
            f"",
            f"**Symmetri (P18):** {'✅ GODKÄND' if jd.symmetry_verified else '⚠️ EJ UPPFYLLD'}",
            f"",
            f"**Stärkande omständigheter:**",
        ]
        for s in jd.stärkande_omständigheter[:5]:
            lines.append(f"- {s}")
        lines += [
            f"",
            f"**Friande/motsägande omständigheter (P18):**",
        ]
        for f_ in jd.friande_omständigheter[:5]:
            lines.append(f"- {f_}")
        lines += [
            f"",
            f"**Preliminär slutsats:**",
            f"",
            f"> {jd.provisional_conclusion}",
            f"",
        ]

    # Audit-agenter
    lines += [
        f"---",
        f"",
        f"## REVISION (Agent A / B / C)",
        f"",
        f"| Agent | Fynd |",
        f"|-------|------|",
        f"| A — Falsifiering | {len(csm.agent_a_findings)} avvikelser |",
        f"| B — Verifiering | {len(csm.agent_b_findings)} verifierade stöd |",
        f"| C — Second-order | {len(csm.agent_c_findings)} observationer |",
        f"",
    ]

    # Self-healing patcher
    if csm.patches:
        lines += [
            f"### Self-Healing Patcher",
            f"",
            f"| Patch | Allvarlighet | Gap | Regel |",
            f"|-------|-------------|-----|-------|",
        ]
        for p in csm.patches:
            lines.append(
                f"| `{p.patch_id}` | **{p.severity}** | "
                f"{p.gap_found[:50]} | {p.rule_added[:60]} |"
            )

    if csm.hard_stop:
        lines += [
            f"",
            f"---",
            f"",
            f"## ⛔ HARD STOP",
            f"",
            f"> {csm.hard_stop_reason}",
        ]

    lines += [
        f"",
        f"---",
        f"",
        f"_Genererad av FORENSIC COURT AUDIT ENGINE v{MOTOR_VERSION}_",
        f"_ISO/IEC 27037:2012 | ENFSI FSA-BPM-002 FIXED-2026 | LOCKED_",
    ]

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"[EXPORT] Markdown: {out}")
    return str(out)


# ─────────────────────────────────────────────────────────────────────────────
# HUVUD-ORKESTRATOR: run_pipeline_v10
# ─────────────────────────────────────────────────────────────────────────────

def _enrich_with_name_categorizer(
    records: List[FileRecord],
    root_dirs: List[str],
) -> tuple:
    """
    Berikar FileRecord med filnamn-/sökvägsbaserad kategorisering.
    Läser ALDRIG filinnehåll. Returnerar (records, poster, summary).
    """
    if not EVIDENCE_CATEGORIZER_AVAILABLE or _kategorisera_fil is None:
        return records, [], {}

    by_rel = {r.relative_path: r for r in records}
    all_posts = []
    summary: Dict[str, int] = {}

    for root_s in root_dirs:
        root = Path(root_s)
        if not root.is_dir():
            continue
        try:
            # Matcha mot redan ingererade filer via relativ sökväg
            for r in records:
                abs_p = Path(r.absolute_path)
                if not abs_p.exists():
                    continue
                # Endast filer under denna root
                try:
                    abs_p.resolve().relative_to(root.resolve())
                except ValueError:
                    continue
                post = _kategorisera_fil(abs_p, root)
                all_posts.append(post)
                r.name_kategori = post.kategori
                r.name_status = post.status
                r.processuell_relevans = list(post.processuell_relevans or [])
                r.beviskedje_funktion = post.beviskedje_funktion or ""
                r.atgard_prioritet = int(post.atgard_prioritet or 3)
                r.matchade_termer = list(post.matchade_termer or [])
                r.extraherat_datum = post.extraherat_datum
                # Context tags för nedströms agenter (ofarlig berikning)
                if post.kategori and post.kategori != "Ej identifierad":
                    tag = f"name_kat:{post.kategori}"
                    if tag not in r.context_tags:
                        r.context_tags.append(tag)
                for rel in (post.processuell_relevans or []):
                    tag = f"proc:{rel}"
                    if tag not in r.context_tags:
                        r.context_tags.append(tag)
                summary[post.kategori] = summary.get(post.kategori, 0) + 1
        except Exception as e:
            log.warning(f"[EVIDENCE_CATEGORIZER] Fel vid berikning av {root}: {e}")

    if all_posts and _kat_kausal is not None:
        try:
            _kat_kausal(all_posts)
            # synka kausal tillbaka till FileRecord om möjligt
            post_by_path = {p.sokvag: p for p in all_posts}
            for r in records:
                p = post_by_path.get(r.relative_path)
                if p and getattr(p, "kausalsamband", None):
                    # lagra i beviskedje_funktion-noten om relevant
                    if p.kausalsamband and p.kausalsamband != "Ej verifierad":
                        r.beviskedje_funktion = (
                            (r.beviskedje_funktion + " | Kausal: " + p.kausalsamband)
                            if r.beviskedje_funktion else f"Kausal: {p.kausalsamband}"
                        )
        except Exception as e:
            log.warning(f"[EVIDENCE_CATEGORIZER] Kausalanalys misslyckades: {e}")

    log.info(
        f"[EVIDENCE_CATEGORIZER] Berikade {len(all_posts)} filer | "
        f"kategorier: {summary}"
    )
    return records, all_posts, summary



def _build_pre_trial_objectives(
    records: List[FileRecord],
    meta: Dict,
    kat_summary: Dict[str, int],
) -> PreTrialObjectives:
    """
    Konstruerar prövningsmodell från material + metadata.
    Uppfinner aldrig rättsfakta, parter eller slutsatser.
    """
    pto = PreTrialObjectives()
    pto.material_summary = dict(kat_summary or {})
    pto.material_summary["totalt_filer"] = len(records)
    pto.material_summary["karantan"] = sum(1 for r in records if r.quarantine_flag)
    pto.material_summary["a_strong"] = sum(
        1 for r in records if r.evidence_category == EvidenceCategory.A_STRONG
    )
    pto.material_summary["b_risk"] = sum(
        1 for r in records if r.evidence_category == EvidenceCategory.B_RISK
    )
    pto.material_summary["ej_verifierad_hash"] = sum(
        1 for r in records
        if r.metadata.integritet == IntegrityStatus.KAN_EJ_VERIFIERAS
    )

    # Vad skall avgöras — endast om metadata faktiskt anger det
    for key, label in (
        ("måltyp", "Måltyp"),
        ("yrkande", "Yrkande"),
        ("processform", "Processform"),
        ("legal_rule", "Rättsregel"),
        ("requisite", "Rekvisit"),
    ):
        v = (meta.get(key) or "").strip()
        if v and not v.startswith("EJ "):
            pto.vad_skall_avgoras.append(f"{label}: {v}")

    if not pto.vad_skall_avgoras:
        pto.gaps.append(
            "Ingen måltyp/yrkande/processform/rättsregel angiven i metadata "
            "och ingen kan härledas utan antagande."
        )
        pto.notes.append(
            "Prövningsfråga ej satt — motorn gissar inte vad som skall avgöras."
        )

    # Ostridigt: sådant som är strukturellt observerbart utan värdering
    if records:
        pto.ostridigt.append(f"Antal registrerade filer i ärenderot: {len(records)}")
    if kat_summary:
        for k, n in sorted(kat_summary.items(), key=lambda x: (-x[1], x[0])):
            if k != "Ej identifierad":
                pto.ostridigt.append(
                    f"Filnamnsbaserad kategoritäckning — {k}: {n} fil(er) "
                    f"(ej innehållsverifierat)"
                )

    # Tvistigt / oklart utifrån materialstatus (inte juridisk tvist)
    uncl = sum(1 for r in records if r.evidence_category == EvidenceCategory.UNCLASSIFIED)
    if uncl:
        pto.tvistigt.append(
            f"{uncl} fil(er) saknar A/B-klassificering (UNCLASSIFIED) — "
            f"bevisvärde ej fastställt."
        )
    if pto.material_summary.get("karantan", 0):
        pto.tvistigt.append(
            f"{pto.material_summary['karantan']} fil(er) i karantän/oombett — "
            f"ingår inte automatiskt i primäranalys."
        )
    if pto.material_summary.get("ej_verifierad_hash", 0):
        pto.tvistigt.append(
            f"{pto.material_summary['ej_verifierad_hash']} fil(er) saknar "
            f"verifierad SHA-256."
        )
    ej_id = kat_summary.get("Ej identifierad", 0) if kat_summary else 0
    if ej_id:
        pto.tvistigt.append(
            f"{ej_id} fil(er) utan matchande namnkategori — "
            f"processuell roll oklar utifrån filnamn."
        )

    # Krävt underlag — härlett från angiven metadata, inte påhittat
    if meta.get("legal_rule") and not str(meta.get("legal_rule", "")).startswith("EJ "):
        pto.required_legal_sources.append(
            f"Primärkälla för angiven rättsregel: {meta['legal_rule']}"
        )
        pto.required_legal_facts.append(
            "Rättsfakta som knyter sakomständigheter till angiven rättsregel "
            "(kräver manuellt/juridiskt urval — ej automatiskt ifyllt)."
        )
    if meta.get("requisite") and not str(meta.get("requisite", "")).startswith("EJ "):
        pto.required_legal_facts.append(
            f"Rekvisit att pröva (angivet): {meta['requisite']}"
        )
    if meta.get("måltyp") and not str(meta.get("måltyp", "")).startswith("EJ "):
        pto.required_evidence.append(
            f"Bevisning relevant för måltyp '{meta['måltyp']}' "
            f"(konkret urval kräver aktgenomgång)."
        )

    # Bevisbehov utifrån saknade kategorier när måltyp/rättsregel finns
    if pto.vad_skall_avgoras:
        for need_kat, need_txt in (
            ("Rättslig", "Rättsligt underlag (beslut/dom/yttrande) i aktmaterialet"),
            ("Medicinsk", "Medicinskt underlag om hälsotillstånd åberopas"),
            ("Ekonomisk", "Ekonomiskt underlag om ersättning/inkomst åberopas"),
        ):
            n = (kat_summary or {}).get(need_kat, 0)
            if n == 0:
                pto.gaps.append(f"Saknas filnamnsindikation på: {need_txt}")
            else:
                pto.required_evidence.append(
                    f"Finns filnamnsindikation ({need_kat}: {n}) — "
                    f"innehåll och relevans ej verifierad av motorn."
                )

    if not records:
        pto.gaps.append("Inget material i ärenderot.")
    if not pto.required_legal_sources and not (
        meta.get("legal_rule") and not str(meta.get("legal_rule", "")).startswith("EJ ")
    ):
        pto.gaps.append("Ingen rättskälla angiven — rättskällesökning kan inte riktas.")

    # Readiness
    critical_gaps = [g for g in pto.gaps if "Inget material" in g or "Prövningsfråga" in g
                     or "Ingen måltyp" in g or "Ingen rättskälla" in g]
    if not records:
        pto.readiness = "OTILLRÄCKLIGT UNDERLAG"
    elif pto.vad_skall_avgoras and len(pto.gaps) <= 2:
        pto.readiness = "DELVIS" if pto.gaps else "REDO"
    elif pto.vad_skall_avgoras:
        pto.readiness = "DELVIS"
    else:
        pto.readiness = "OTILLRÄCKLIGT UNDERLAG"

    pto.notes.append(
        "Pre-trial objectives är en prövningsmodell, inte en bedömning av utgång. "
        "Ostridigt/tvistigt avser materialstatus, inte partsståndpunkter."
    )
    log.info(
        f"[PRE_TRIAL] readiness={pto.readiness} | "
        f"avgöras={len(pto.vad_skall_avgoras)} | gaps={len(pto.gaps)}"
    )
    return pto



# ─────────────────────────────────────────────────────────────────────────────
# v10-v3: MODE ROUTER
# ─────────────────────────────────────────────────────────────────────────────
class ModeRouter:
    """
    Tvåspårigt exekveringsflöde efter CLASSIFYING.
    JUDGMENT_AUDIT: kräver identifierbar tidigare dom/beslut — annars HS01A.
    JUDGMENT_CONSTRUCTION: frånvaro av dom utlöser INTE HS01A; saknas underlag → HS01C.
    """

    DOM_KW = (
        "dom", "beslut", "domstol", "förvaltningsrätt", "forvaltningsratt",
        "kammarrätt", "kammarratt", "hfd", "hovrätt", "hovratt", "tingsrätt",
        "myndighetsbeslut", "avslag", "bifall", "omprövning",
    )
    INCOMING_MARKERS = (
        "incoming_material", "incoming", "åberopat", "aberopat",
        "inkommit_material", "processhandling", "stämningsansökan",
        "stamningsansokan", "överklagande", "overklagande",
    )

    def route(self, records: List[FileRecord], root_dirs: List[str]) -> Tuple[str, List[str], Optional[str]]:
        notes: List[str] = []
        paths = " ".join((r.relative_path + " " + r.filename).lower() for r in records)
        has_prior_decision = any(kw in paths for kw in self.DOM_KW)
        has_incoming = any(
            any(m in (r.relative_path + "/" + r.filename).lower() for m in self.INCOMING_MARKERS)
            for r in records
        )
        # Mappstruktur
        for root in root_dirs:
            rp = Path(root)
            if (rp / "INCOMING_MATERIAL").is_dir() or (rp / "incoming_material").is_dir():
                has_incoming = True
                notes.append("Mapp INCOMING_MATERIAL/incoming_material detekterad.")

        if has_prior_decision:
            notes.append("Tidigare dom/beslut indikerad via filnamn/sökväg → JUDGMENT_AUDIT.")
            return ExecutionMode.JUDGMENT_AUDIT, notes, None

        if has_incoming or records:
            notes.append(
                "Ingen tidigare dom/beslut identifierad; material finns → JUDGMENT_CONSTRUCTION. "
                "Frånvaro av dom utlöser inte HS01A."
            )
            if not records:
                return ExecutionMode.JUDGMENT_CONSTRUCTION, notes, HardStopCode.HS01C
            return ExecutionMode.JUDGMENT_CONSTRUCTION, notes, None

        notes.append("Varken dom/beslut eller processmaterial identifierat.")
        return ExecutionMode.UNDETERMINED, notes, HardStopCode.HS01C


# ─────────────────────────────────────────────────────────────────────────────
# v10-v3: SEXSTEGS KARANTÄNSVALIDERING (oombett material)
# ─────────────────────────────────────────────────────────────────────────────
class UnsolicitedValidationAgent:
    """
    Oombett material under NEW_DISCOVERIES/karantän injiceras aldrig direkt
    i subsumtion. Sex steg måste klaras innan uppgradering kan övervägas.
    """

    NEW_MARKERS = (
        "new_discoveries", "nya_upptäckter", "nya_upptackter", "oombett",
        "quarantine", "karantän", "karantan", "new_files", "incoming_new",
    )

    def run(self, records: List[FileRecord]) -> List[UnsolicitedValidationRecord]:
        out: List[UnsolicitedValidationRecord] = []
        for r in records:
            path_l = (r.relative_path + " " + r.filename).lower()
            is_unsol = r.quarantine_flag or r.baseline_state == BaselineState.UNSOLICITED_INPUT
            is_unsol = is_unsol or any(m in path_l for m in self.NEW_MARKERS)
            if not is_unsol:
                continue

            rec = UnsolicitedValidationRecord(
                file_id=r.file_id,
                relative_path=r.relative_path,
            )
            # 1 Source Verification — strukturell (ej innehållsgissning)
            s1 = bool(r.metadata.hash_sha256 and r.metadata.hash_sha256 != "KAN EJ VERIFIERAS")
            rec.steps.append(UnsolicitedStepResult(
                "1_SOURCE_VERIFICATION", s1,
                "SHA-256 verifierad" if s1 else "Källintegritet ej verifierbar",
            ))
            # 2 Relevance — endast om namnkategori/processuell relevans finns
            s2 = bool(
                (r.name_kategori and r.name_kategori != "Ej identifierad")
                or r.processuell_relevans
            )
            rec.steps.append(UnsolicitedStepResult(
                "2_RELEVANCE_TEST", s2,
                f"Namnkategori={r.name_kategori}" if s2 else "Ingen filnamnsbaserad relevansindikation",
            ))
            # 3 Duplication — samma hash som annan fil
            dup = any(
                o.file_id != r.file_id
                and o.metadata.hash_sha256 == r.metadata.hash_sha256
                and r.metadata.hash_sha256 not in ("", "KAN EJ VERIFIERAS")
                for o in records
            )
            s3 = not dup
            rec.steps.append(UnsolicitedStepResult(
                "3_DUPLICATION_TEST", s3,
                "Ingen dubbletthash" if s3 else "Samma SHA-256 som annan registrerad fil",
            ))
            # 4 Temporal Placement
            s4 = bool(r.extraherat_datum or (
                r.metadata.skapad and r.metadata.skapad != "KAN EJ VERIFIERAS"
            ))
            rec.steps.append(UnsolicitedStepResult(
                "4_TEMPORAL_PLACEMENT", s4,
                f"Tid={r.extraherat_datum or r.metadata.skapad}" if s4 else "Ingen verifierbar tidpunkt",
            ))
            # 5 Procedural Status — formellt åberopat?
            s5 = r.procedural_status == ProceduralStatus.OFFICIALLY_SUBMITTED
            rec.steps.append(UnsolicitedStepResult(
                "5_PROCEDURAL_STATUS", s5,
                f"Status={r.procedural_status}",
            ))
            # 6 Evidence Qualification — integritet + ej karantänflagga kvar
            s6 = (
                r.metadata.integritet == IntegrityStatus.VERIFIED
                and not r.quarantine_flag
            )
            rec.steps.append(UnsolicitedStepResult(
                "6_EVIDENCE_QUALIFICATION", s6,
                f"Integritet={r.metadata.integritet}, karantän={r.quarantine_flag}",
            ))

            rec.fully_cleared = all(st.passed for st in rec.steps)
            if not rec.fully_cleared:
                failed = [st.step for st in rec.steps if not st.passed]
                rec.blocked_reason = "Ej klarade steg: " + ", ".join(failed)
                # Kvarstår isolerat
                r.quarantine_flag = True
            out.append(rec)

        log.info(f"[UNSOLICITED] Validerade {len(out)} oombett/karantänfiler")
        return out


# ─────────────────────────────────────────────────────────────────────────────
# v10-v3: LEGAL REQUISITE GATE (HS11)
# ─────────────────────────────────────────────────────────────────────────────
class LegalRequisiteGate:
    """
    Bryter angiven rättsregel i MUST-rekvisit. Saknas verifierat rättsfaktum
    eller VerbatimAnchor i grafen → NOT_VERIFIABLE → HS11 HARD_STOP.
    Ingen procentuell bevisvärdering — binär kedjeintegritet.
    """

    def run(
        self,
        meta: Dict,
        graph: RelationGraph,
        subsumtioner: List[SubsumptionRecord],
    ) -> LegalRequisiteGateResult:
        result = LegalRequisiteGateResult()
        rule = (meta.get("legal_rule") or "").strip()
        req = (meta.get("requisite") or "").strip()

        if not rule or rule.startswith("EJ "):
            result.summary = (
                "Ingen rättsregel angiven i metadata — "
                "Legal Requisite Gate kan inte binda MUST-rekvisit. "
                "Ingen HS11 (saknar regel att pröva)."
            )
            result.gate_passed = True  # ingen falsk spärr utan regel
            return result

        # Bygg rekvisitlista från metadata (uppfinner inte lagtext)
        requisite_texts: List[str] = []
        if req and not req.startswith("EJ "):
            requisite_texts.append(req)
        else:
            requisite_texts.append(
                f"[MUST-rekvisit för '{rule}' ej specificerat i metadata — "
                f"status NOT_VERIFIABLE tills rekvisit anges]"
            )

        verified_edges = [
            e for e in graph.edges
            if e.edge_type != EdgeType.UNRESOLVED
            and getattr(e, "anchor", None) is not None
        ]
        has_any_anchor = len(verified_edges) > 0

        for rt in requisite_texts:
            item = RequisiteGateItem(
                legal_rule=rule,
                requisite_text=rt,
                modal="MUST",
            )
            # Matcha subsumtion
            matched_sub = next(
                (s for s in subsumtioner if s.legal_rule == rule or rule in (s.legal_rule or "")),
                None,
            )
            if matched_sub and matched_sub.anchor and matched_sub.status == "UPPFYLLT":
                item.status = RequisiteStatus.REKVISIT_UPPFYLLT
                item.fact_ref = matched_sub.evidence_id or matched_sub.legal_fact
                item.anchor_ok = True
            elif has_any_anchor and matched_sub:
                item.status = RequisiteStatus.TVISTIGT
                item.fact_ref = matched_sub.evidence_id or "DELVIS"
                item.anchor_ok = bool(matched_sub.anchor)
                item.notes = "Subsumtionspost finns men ej status UPPFYLLT"
            else:
                item.status = RequisiteStatus.NOT_VERIFIABLE
                item.fact_ref = "NOT_VERIFIABLE"
                item.anchor_ok = False
                item.notes = "Saknar verifierat rättsfaktum med VerbatimAnchor i grafen"
            result.items.append(item)

        must_fail = [
            i for i in result.items
            if i.modal == "MUST"
            and i.status in (RequisiteStatus.NOT_VERIFIABLE, RequisiteStatus.BEVISNING_SAKNAS)
        ]
        if must_fail:
            result.gate_passed = False
            result.hard_stop_hs11 = True
            result.summary = (
                f"HS11: {len(must_fail)} MUST-rekvisit saknar verifierat rättsfaktum/ankare. "
                f"Provisoriskt domsutkast blockeras."
            )
        else:
            result.gate_passed = True
            result.hard_stop_hs11 = False
            result.summary = "Legal Requisite Gate passerad — alla MUST-rekvisit har kedjestöd."

        log.info(f"[LEGAL_REQUISITE_GATE] {result.summary}")
        return result


# ─────────────────────────────────────────────────────────────────────────────
# v10-v3: HOLDING-KEDJA FÖR PREJUDIKAT (H1–H3)
# ─────────────────────────────────────────────────────────────────────────────
class HoldingChainValidator:
    """
    Prejudikat får inte bära rekvisit utan H1/H2/H3-verifiering.
    Binär användbarhet — ingen procent.
    """

    def validate_all(self, legal_source_verifications: List[Dict]) -> List[HoldingChainResult]:
        results: List[HoldingChainResult] = []
        for ver in legal_source_verifications or []:
            ref = str(ver.get("sokterm") or ver.get("source") or ver.get("sokterm", "OKÄND"))
            status = str(ver.get("status", ""))
            klar = int(ver.get("klar") or 0)
            # H1: explicit träff i sökresultat
            h1 = HoldingLevel.H1_DIREKT if klar > 0 and status not in ("FEL", "TIMEOUT") else HoldingLevel.EJ_VERIFIERAD
            # H2: strukturell — kräver lagtextkoppling (finns sällan automatiskt)
            h2 = HoldingLevel.EJ_VERIFIERAD
            # H3: alternativ källa — flera agenter klara
            h3 = HoldingLevel.H3_ALTERNATIV if klar >= 2 else HoldingLevel.EJ_VERIFIERAD

            usable = (h1 == HoldingLevel.H1_DIREKT) and (
                h2 == HoldingLevel.H2_STRUKTURELL or h3 == HoldingLevel.H3_ALTERNATIV
            )
            # Strikt: utan H2 krävs H3; H1 ensamt räcker inte för att bära rekvisit
            if h1 == HoldingLevel.H1_DIREKT and h3 == HoldingLevel.H3_ALTERNATIV:
                usable = True
            else:
                usable = False

            results.append(HoldingChainResult(
                source_ref=ref,
                h1=h1,
                h2=h2,
                h3=h3,
                usable_for_requisite=usable,
                notes=(
                    "Prejudikat/träff får användas för rekvisitstöd"
                    if usable else
                    "Holding-kedja ofullständig — får inte ensamt bära rekvisit"
                ),
            ))
        log.info(f"[HOLDING_CHAIN] {len(results)} källor bedömda")
        return results


# ─────────────────────────────────────────────────────────────────────────────
# v10-v3: PRESENTATIONSLAGER (Court / Party / Mediation)
# ─────────────────────────────────────────────────────────────────────────────
class PresentationLayer:
    """
    Lager 16 — tre vyer från samma CaseState. Mediation får ALDRIG
    skriva över CaseState; endast läsa.
    """

    def build(self, csm: "CaseStateMachine") -> PresentationViews:
        views = PresentationViews()

        # Court View
        views.court_view = {
            "execution_mode": csm.execution_mode,
            "pre_trial_readiness": (
                csm.pre_trial.readiness if csm.pre_trial else "EJ KÖRD"
            ),
            "vad_skall_avgoras": (
                list(csm.pre_trial.vad_skall_avgoras) if csm.pre_trial else []
            ),
            "gatekeeper_passed": csm.gatekeeper_passed,
            "gatekeeper_blocked": csm.gatekeeper_blocked,
            "requisite_gate_summary": (
                csm.requisite_gate.summary if csm.requisite_gate else "EJ KÖRD"
            ),
            "requisite_items": [
                {
                    "rule": i.legal_rule,
                    "requisite": i.requisite_text,
                    "status": i.status,
                    "anchor_ok": i.anchor_ok,
                }
                for i in (csm.requisite_gate.items if csm.requisite_gate else [])
            ],
            "bugs_B01_B15": [
                {
                    "kod": getattr(b, "bug_kod", None) or str(b),
                    "allvarlighet": getattr(b, "allvarlighet", ""),
                }
                for b in (csm.bugs or [])
            ],
            "falsification": csm.falsification_verdict,
            "hard_stop": csm.hard_stop,
            "hard_stop_code": csm.hard_stop_code,
            "sårbarhet_risk": csm.sårbarhet_risk,
        }

        # Party View (P18 symmetri) — härlett från materialstatus, inte partsnamn
        strengths = []
        weaknesses = []
        open_q = []
        proc_risks = []
        legal_risks = []
        actions = []

        if csm.category_a:
            strengths.append(f"Kategori A_STRONG filer: {csm.category_a}")
        if csm.gatekeeper_passed:
            strengths.append(f"Gatekeeper godkända filer: {csm.gatekeeper_passed}")
        if csm.category_b:
            weaknesses.append(f"Kategori B_RISK filer: {csm.category_b}")
        if csm.gatekeeper_blocked:
            weaknesses.append(f"Gatekeeper blockerade: {csm.gatekeeper_blocked}")
            proc_risks.append("Blockerat material kräver formellt åberopande innan subsumtion")
        if csm.quarantine_count:
            open_q.append(f"Karantänfiler under validering: {csm.quarantine_count}")
        if csm.requisite_gate and not csm.requisite_gate.gate_passed:
            legal_risks.append("MUST-rekvisit ej verifierbara (HS11-risk/utlöst)")
            actions.append(
                "Identifierad brist: saknad rekvisitkedja → "
                "Åtgärd: tillför verifierat rättsfaktum med ankare → "
                "Förväntad effekt: Legal Requisite Gate kan passeras"
            )
        if csm.falsification_verdict == FalsificationVerdict.VULNERABLE:
            legal_risks.append("Falsifiering: VULNERABLE — motkedja håller")
            actions.append(
                "Identifierad brist: sårbar argumentationskedja → "
                "Åtgärd: stärk svagaste länk med primärkälla → "
                "Förväntad effekt: högre motståndskraft vid motprövning"
            )
        for u in csm.unsolicited_validations:
            if not u.fully_cleared:
                open_q.append(f"Oombett ej klarat: {u.relative_path} ({u.blocked_reason})")
                actions.append(
                    f"Identifierad brist: oombett material ej kvalificerat ({u.relative_path}) → "
                    f"Åtgärd: genomgå steg 1–6 / formellt åberopande → "
                    f"Förväntad effekt: möjlig uppgradering ur karantän"
                )

        # Symmetrisk spegling Part A / Part B — samma underlag, speglade etiketter
        views.party_a = PartyImpactMatrix(
            party_label="PART_A",
            verified_strengths=list(strengths),
            verified_weaknesses=list(weaknesses),
            open_evidence_questions=list(open_q),
            procedural_risks=list(proc_risks),
            legal_risks=list(legal_risks),
            action_points=list(actions),
        )
        views.party_b = PartyImpactMatrix(
            party_label="PART_B",
            verified_strengths=list(weaknesses),  # spegel: motpartens styrka ≈ egen svaghet
            verified_weaknesses=list(strengths),
            open_evidence_questions=list(open_q),
            procedural_risks=list(proc_risks),
            legal_risks=list(legal_risks),
            action_points=[
                "Speglad analys — samma CaseState; ingen partsfavorisering i kärnan"
            ],
        )

        # Mediation View — tre hinkar från pre_trial + graf
        agreed, disputed, unknown = [], [], []
        if csm.pre_trial:
            agreed.extend(csm.pre_trial.ostridigt)
            disputed.extend(csm.pre_trial.tvistigt)
            unknown.extend(csm.pre_trial.gaps)
        if csm.graph:
            if csm.graph.unresolved_count:
                disputed.append(
                    f"UNRESOLVED grafkanter: {csm.graph.unresolved_count}"
                )
            if csm.graph.verified_count:
                agreed.append(
                    f"Verifierade grafkanter: {csm.graph.verified_count}"
                )
        views.mediation = {
            "agreed_facts": agreed,
            "disputed_facts": disputed,
            "unknown_facts": unknown,
            "note": "Medlingsvy är read-only projektion — CaseState oförändrad.",
        }
        return views



def run_pipeline_v10_v3(

    root_dirs:          List[str],
    output_dir:         Optional[str] = None,
    exhibit_list:       Optional[List[str]] = None,
    case_metadata:      Optional[Dict] = None,
    extra_quarantine_kw: Optional[Set[str]] = None,
    extra_locked_kw:    Optional[Set[str]] = None,
) -> CaseStateMachine:
    """
    v10 PIPELINE — Relation-Driven Case State Machine.

    Guarded state-transitions:
    INIT → INGESTING → CLASSIFYING → PRE_TRIAL_OBJECTIVES → CAPABILITY_MAPPING
         → RELATION_BUILDING → GATING → SUBSUMPTION
         → AUDIT_A → AUDIT_B → AUDIT_C
         → FALSIFICATION → JUDGMENT_DRAFT
         → SELF_HEALING → COMPLETE

    REGEL: Original-filer rörs ALDRIG. Systemet kopierar — aldrig flyttar.
    """
    if not output_dir:
        output_dir = str(Path(__file__).resolve().parent.parent / "output")
    t0   = time.time()
    meta = case_metadata or {}

    log.info("=" * 72)
    log.info(f"FORENSIC COURT AUDIT ENGINE v{MOTOR_VERSION} — PIPELINE START")
    log.info(f"Roots: {root_dirs}")
    log.info("=" * 72)

    # ── Initiera CaseStateMachine ──────────────────────────────────────────
    csm = CaseStateMachine(
        case_id=f"CASE_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        root_directory=";".join(root_dirs),
        domstol=meta.get("domstol", "EJ IDENTIFIERAD"),
        jurisdiktion=meta.get("jurisdiktion", "EJ IDENTIFIERAD"),
        processform=meta.get("processform", "EJ IDENTIFIERAD"),
        måltyp=meta.get("måltyp", "EJ IDENTIFIERAD"),
    )

    # Initiera reproducibility record
    repro = ReproducibilityRecord(
        record_id=csm.case_id,
        engine_version=MOTOR_VERSION,
        scan_timestamp=SCAN_TIMESTAMP,
    )
    csm.reproducibility = repro

    # ── TILLSTÅND: INIT → INGESTING ────────────────────────────────────────
    csm.transition(MachineState.INGESTING, "Pipeline startad")

    agent1           = IngestionAgent(
        root_dirs=root_dirs,
        exhibit_list=exhibit_list,
        extra_quarantine_kw=extra_quarantine_kw,
        extra_locked_kw=extra_locked_kw,
    )
    records, hashes  = agent1.scan()
    csm.files        = records
    csm.total_files  = len(records)
    csm.locked_count = sum(
        1 for r in records if r.baseline_state == BaselineState.LOCKED_BASELINE
    )
    csm.quarantine_count = sum(1 for r in records if r.quarantine_flag)
    repro.file_hashes.update(hashes)

    # L00: Integritetskontroll — HARD STOP om > 60% filer ej verifierbara
    unverified_pct = sum(
        1 for r in records
        if r.metadata.integritet == IntegrityStatus.KAN_EJ_VERIFIERAS
    ) / max(len(records), 1)

    if unverified_pct > 0.60:
        csm.trigger_hard_stop(
            f"L00 INTEGRITETSKONTROLL: {unverified_pct:.0%} av filer "
            f"saknar verifierad SHA-256 — HARD STOP"
        )
        _finalize(csm, output_dir, t0)
        return csm

    # ── TILLSTÅND: CLASSIFYING ─────────────────────────────────────────────
    csm.transition(MachineState.CLASSIFYING, "Bevisklassificering")
    # 1) A/B-klassificering (befintlig logik)
    records      = EvidenceClassifierAgent().classify(records)
    # 2) Namnbaserad kategorisering (evidence_categorizer) — berikar FileRecord
    records, kat_posts, kat_summary = _enrich_with_name_categorizer(records, root_dirs)
    csm.files = records
    csm.category_a = sum(
        1 for r in records if r.evidence_category == EvidenceCategory.A_STRONG
    )
    csm.category_b = sum(
        1 for r in records if r.evidence_category == EvidenceCategory.B_RISK
    )
    csm.name_categorization_summary = kat_summary
    csm.name_categorization_ran = bool(kat_posts)
    # Spara poster på csm för export i _finalize (transient attribut)
    csm._kat_posts = kat_posts  # type: ignore[attr-defined]

    # ── TILLSTÅND: MODE_ROUTING (v10-v3) ──────────────────────────────────
    csm.transition(MachineState.MODE_ROUTING, "ModeRouter JUDGMENT_AUDIT|CONSTRUCTION")
    mode, mode_notes, mode_hs = ModeRouter().route(records, root_dirs)
    csm.execution_mode = mode
    csm.mode_routing_notes = mode_notes
    if mode == ExecutionMode.JUDGMENT_AUDIT:
        # Säkerhet: saknas indikation på dom/beslut — ModeRouter returnerar inte AUDIT utan beslut
        pass
    if mode_hs == HardStopCode.HS01A or (
        mode == ExecutionMode.JUDGMENT_AUDIT
        and not any(
            any(k in (r.relative_path + r.filename).lower() for k in ModeRouter.DOM_KW)
            for r in records
        )
    ):
        # Extra skydd: AUDIT utan dom → HS01A
        if mode == ExecutionMode.JUDGMENT_AUDIT and not any(
            any(k in (r.relative_path + r.filename).lower() for k in ModeRouter.DOM_KW)
            for r in records
        ):
            csm.hard_stop_code = HardStopCode.HS01A
            csm.trigger_hard_stop(HardStopCode.HS01A)
            _finalize(csm, output_dir, t0)
            return csm
    if mode_hs == HardStopCode.HS01C:
        csm.hard_stop_code = HardStopCode.HS01C
        csm.trigger_hard_stop(HardStopCode.HS01C)
        _finalize(csm, output_dir, t0)
        return csm

    # ── TILLSTÅND: UNSOLICITED_VALIDATION (v10-v3) ───────────────────────
    csm.transition(MachineState.UNSOLICITED_VALIDATION, "Sexstegs karantänsvalidering")
    csm.unsolicited_validations = UnsolicitedValidationAgent().run(records)

    # ── TILLSTÅND: PRE_TRIAL_OBJECTIVES ───────────────────────────────────
    csm.transition(MachineState.PRE_TRIAL_OBJECTIVES, "Prövningsmål före analys")
    csm.pre_trial = _build_pre_trial_objectives(records, meta, kat_summary)

    # ── TILLSTÅND: CAPABILITY_MAPPING ─────────────────────────────────────
    csm.transition(MachineState.CAPABILITY_MAPPING, "Aktiverar moduler")
    _mods = CapabilityMapEngine().map(records)
    # Lagra som strängar — undvik Enum-serialiseringsproblem
    csm.active_modules = [m.value if hasattr(m, "value") else str(m) for m in _mods]
    repro.activated_modules = list(csm.active_modules)

    # ── RÄTTSKÄLLESÖKNING (deep_search_pipeline.py, v9.8.1) ────────────────
    # Endast en verifieringsfunktion — ersätter aldrig juridisk analys (§7).
    # Körs bara om LEGAL_SOURCE-modulen är aktiverad OCH en faktisk sökterm
    # finns (rättsregel/rekvisit/måltyp). Ingen sökterm uppfinns.
    if (CapabilityModule.LEGAL_SOURCE in csm.active_modules
            or CapabilityModule.LEGAL_SOURCE.value in csm.active_modules) and DEEP_SEARCH_AVAILABLE:
        sokterm = next(
            (
                v for v in (meta.get("legal_rule"), meta.get("requisite"), meta.get("måltyp"))
                if v and not v.startswith("EJ ")
            ),
            None,
        )
        if sokterm:
            try:
                from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
                with ThreadPoolExecutor(max_workers=1) as _ex:
                    _fut = _ex.submit(_kör_deep_search, sokterm)
                    try:
                        sok_resultat = _fut.result(timeout=25)
                    except FuturesTimeout:
                        sok_resultat = {
                            "sokterm": sokterm,
                            "status": "TIMEOUT",
                            "agenter": 0,
                            "klar": 0,
                            "fel": 1,
                            "resultat": {},
                            "note": "Rättskällesökning avbröts efter 25s — ingen krasch",
                        }
                        log.warning(f"[LEGAL_SOURCE] Timeout 25s för '{sokterm}'")
                csm.legal_source_verifications.append(sok_resultat)
                log.info(
                    f"[LEGAL_SOURCE] '{sokterm}': {sok_resultat.get('klar', 0)}/"
                    f"{sok_resultat.get('agenter', 0)} källagenter klara"
                )
            except Exception as e:
                log.warning(f"[LEGAL_SOURCE] Sökning misslyckades: {e}")
                csm.legal_source_verifications.append({
                    "sokterm": sokterm, "status": "FEL", "fel": str(e),
                })
        else:
            log.info(
                "[LEGAL_SOURCE] Ingen rättsregel/rekvisit/måltyp angiven — "
                "sökning hoppas över (ingen sökterm uppfinns)."
            )
    elif (CapabilityModule.LEGAL_SOURCE in csm.active_modules
              or CapabilityModule.LEGAL_SOURCE.value in csm.active_modules) and not DEEP_SEARCH_AVAILABLE:
        log.warning("[LEGAL_SOURCE] Modul aktiverad men deep_search_pipeline saknas.")

    # Holding-kedja för ev. rättskälleträffar (v10-v3)
    csm.holding_chains = HoldingChainValidator().validate_all(
        csm.legal_source_verifications
    )

    # ── TILLSTÅND: RELATION_BUILDING ──────────────────────────────────────
    csm.transition(MachineState.RELATION_BUILDING, "Bygger relationsgrafen")
    csm.graph = RelationGraphBuilder().build(records)

    # ── TILLSTÅND: GATING (SubsumptionGatekeeper) ─────────────────────────
    csm.transition(MachineState.GATING, "SubsumptionGatekeeper")
    passed, blocked, gate_actions = SubsumptionGatekeeper().gate(records)
    csm.gatekeeper_passed  = len(passed)
    csm.gatekeeper_blocked = len(blocked)

    # ── TILLSTÅND: SUBSUMPTION ────────────────────────────────────────────
    csm.transition(MachineState.SUBSUMPTION, "Subsumtionskedja")
    # Subsumtioner byggs per godkänd kärnbevisnod
    for i, r in enumerate(passed[:10], 1):
        if r.evidence_category == EvidenceCategory.A_STRONG:
            anchor = VerbatimAnchor(
                source_id=r.file_id,
                source_path=r.relative_path,
                source_hash=r.metadata.hash_sha256,
                page_or_time="FILNIVÅ",
                verbatim_quote=(
                    f"[FILREFERENS: {r.relative_path} | "
                    f"SHA-256: {r.metadata.hash_sha256[:16]}...]"
                    if r.metadata.hash_sha256 != "KAN EJ VERIFIERAS"
                    else "[SAKNAR CITAT]"
                ),
                verified=r.metadata.hash_sha256 != "KAN EJ VERIFIERAS",
            )
            csm.subsumtioner.append(SubsumptionRecord(
                sub_id=f"SUB-{i:03d}",
                legal_rule=meta.get("legal_rule", "EJ IDENTIFIERAD"),
                requisite=meta.get("requisite", "EJ IDENTIFIERAD"),
                legal_fact=r.relative_path,
                evidence_id=r.file_id,
                anchor=anchor,
                status=(
                    "UPPFYLLT"
                    if anchor.is_valid()
                    else "UNRESOLVED"
                ),
            ))

    # ── BIDIRECTIONAL AUDIT ───────────────────────────────────────────────
    bidir = BidirectionalAuditEngine().run(csm.graph, passed)

    # ── TILLSTÅND: AUDIT_A (Falsifiering) ─────────────────────────────────
    
    # ── TILLSTÅND: LEGAL_REQUISITE_GATE (v10-v3 / HS11) ───────────────────
    csm.transition(MachineState.LEGAL_REQUISITE_GATE, "Legal Requisite Gate")
    csm.requisite_gate = LegalRequisiteGate().run(meta, csm.graph, csm.subsumtioner)
    if csm.requisite_gate.hard_stop_hs11:
        csm.hard_stop_code = HardStopCode.HS11
        csm.trigger_hard_stop(HardStopCode.HS11)
        _finalize(csm, output_dir, t0)
        return csm

    csm.transition(MachineState.AUDIT_A, "Audit-Agent A: Falsifiering")
    csm.agent_a_findings = AuditAgentA().run(bidir, csm.graph)

    # ── TILLSTÅND: AUDIT_B (Verifiering) ──────────────────────────────────
    csm.transition(MachineState.AUDIT_B, "Audit-Agent B: Verifiering")
    csm.agent_b_findings = AuditAgentB().run(csm.graph, passed)
    for sok in csm.legal_source_verifications:
        if sok.get("status") == "FEL":
            continue
        csm.agent_b_findings.append({
            "agent":       "AUDIT-B",
            "typ":         "RÄTTSKÄLLA_VERIFIERAD",
            "sokterm":     sok.get("sokterm", ""),
            "beskrivning": (
                f"Rättskällesökning: {sok.get('klar', 0)}/{sok.get('agenter', 0)} "
                f"källagenter klara (verifiering, ej rättslig slutsats)"
            ),
        })

    # ── TILLSTÅND: AUDIT_C (Second-order) ─────────────────────────────────
    csm.transition(MachineState.AUDIT_C, "Audit-Agent C: Second-order")
    csm.agent_c_findings = AuditAgentC().run(
        csm.agent_a_findings, csm.agent_b_findings
    )

    # ── COUNTER AUDIT (porterat från v9.9.0) ────────────────────────────────
    # Körs efter AUDIT_C, före FALSIFICATION — bidrar med kodat buggregister
    # (B01–B15) som falsifieringsmotorn och åtgärdslistan kan använda.
    csm = CounterAuditAgent().run(csm)

    # ── TILLSTÅND: FALSIFICATION ──────────────────────────────────────────
    csm.transition(MachineState.FALSIFICATION, "FalsificationEngine")
    # ── Fas 5-koppling: kritiska/höga buggar från CounterAudit styr utfallet ──
    critical_codes = {"B07", "B09", "B10", "B11", "B14", "B15"}
    ca_critical = any(
        getattr(getattr(b, "bug_kod", ""), "name", str(getattr(b, "bug_kod", "")))
        in critical_codes for b in csm.bugs
    )
    ca_high = any(getattr(b, "allvarlighet", "") == "HÖG" for b in csm.bugs)
    if ca_critical:
        verdict = FalsificationVerdict.NOT_RUN
        chain_str = "BLOCKERAD_AV_COUNTERAUDIT"
        counter_chain = [{
            "led": "COUNTER_AUDIT_BLOCK",
            "argument": "Kritiska buggar (B07/B09/B10/B11/B14/B15) blockerar falsifiering",
            "styrka": "KRITISK",
        }]
        log.warning("[FALSIFICATION] NOT_RUN: kritiska buggar från CounterAuditAgent blockerar")
    else:
        verdict, chain_str, counter_chain = FalsificationEngine().run(
            csm.graph, passed, csm.agent_a_findings
        )
        if ca_high:
            verdict = FalsificationVerdict.VULNERABLE
            chain_str = "VULNERABLE_HÖG_RISK_COUNTERAUDIT"
            log.warning("[FALSIFICATION] VULNERABLE: hög sårbarhetsrisk från CounterAuditAgent")
    csm.falsification_verdict  = verdict
    csm.counter_chain_strength = chain_str

    # ── TILLSTÅND: JUDGMENT_DRAFT ─────────────────────────────────────────
    csm.transition(MachineState.JUDGMENT_DRAFT, "Provisoriskt domsutkast")
    csm.judgment_draft = JudgmentDraftEngine().draft(
        passed_records=passed,
        a_findings=csm.agent_a_findings,
        b_findings=csm.agent_b_findings,
        falsification_verdict=verdict,
        graph=csm.graph,
        case_meta=meta,
    )

    # ── TILLSTÅND: PRESENTATION (v10-v3) ──────────────────────────────────
    csm.transition(MachineState.PRESENTATION, "Court / Party / Mediation views")
    csm.presentation = PresentationLayer().build(csm)

    csm.transition(MachineState.SELF_HEALING, "Self-Healing loop")
    patches, repro = SelfHealingEngine().heal(
        a_findings=csm.agent_a_findings,
        c_findings=csm.agent_c_findings,
        blocked=blocked,
        graph=csm.graph,
        reproducibility=repro,
    )
    csm.patches         = patches
    csm.reproducibility = repro

    # ── Beräkna slutstatus och sårbarhet ──────────────────────────────────
    csm.audit_status  = _compute_audit_status(csm, verdict)
    csm.sårbarhet_risk = _compute_risk(csm)

    # ── TILLSTÅND: COMPLETE ────────────────────────────────────────────────
    # Steg 17: slutstatus respekterar en aktiv spärr - aldrig COMPLETE under HARD_STOP.
    repro.final_state = (MachineState.HARD_STOP
                         if (csm.hard_stop or csm.current_state == MachineState.HARD_STOP)
                         else MachineState.COMPLETE)
    _finalize(csm, output_dir, t0)
    return csm


def _compute_audit_status(csm: CaseStateMachine, verdict: str) -> str:
    if verdict == FalsificationVerdict.ROBUST and csm.gatekeeper_passed > 0:
        return SlutStatus.A
    if verdict == FalsificationVerdict.VULNERABLE:
        return SlutStatus.C
    if csm.gatekeeper_passed == 0:
        return SlutStatus.H
    return SlutStatus.E


def _compute_risk(csm: CaseStateMachine) -> str:
    """
    Slutlig riskbedömning. Kombinerar Agent A/C-fynd med CounterAuditAgent
    (csm.bugs, porterat från v9.9.0) — den mest allvarliga vinner, ingen
    signal skrivs över tyst.
    """
    critical = [
        f for f in csm.agent_c_findings
        if f.get("allvarlighet") == "KRITISK"
    ]
    high_a = [
        f for f in csm.agent_a_findings
        if f.get("allvarlighet") in ("HÖG", "KRITISK")
    ]
    critical_bugs = [b for b in csm.bugs if b.allvarlighet == "KRITISK"]
    high_bugs     = [b for b in csm.bugs if b.allvarlighet == "HÖG"]

    if critical or critical_bugs:
        n = len(critical) + len(critical_bugs)
        return f"KRITISK RISK — {n} kritiska avvikelser (Agent C + CounterAudit B01–B15)"
    if high_a or high_bugs:
        n = len(high_a) + len(high_bugs)
        return f"HÖG RISK — {n} höga avvikelser (Agent A + CounterAudit)"
    if csm.graph.unresolved_count > 3:
        return f"MEDEL RISK — {csm.graph.unresolved_count} UNRESOLVED grafkanter"
    return "LÅG RISK — Inga kritiska avvikelser identifierade"


def _finalize(csm: CaseStateMachine, output_dir: str, t0: float):
    if not csm.hard_stop:
        csm.transition(MachineState.COMPLETE, "Pipeline klar")

    json_path = export_json(csm, os.path.join(output_dir, "case_state_v10.json"))
    md_path   = export_markdown(csm, os.path.join(output_dir, "audit_report_v10.md"))

    # v10-v3 presentation export
    try:
        pres_path = os.path.join(output_dir, "presentation_views_v10.json")
        pres_obj = csm.presentation
        if pres_obj is not None:
            with open(pres_path, "w", encoding="utf-8") as pf:
                json.dump(_to_json(pres_obj), pf, ensure_ascii=False, indent=2)
            log.info(f"[PRESENTATION] {pres_path}")
    except Exception as e:
        log.warning(f"[PRESENTATION] Export misslyckades: {e}")

    # Exportera namnbaserad kategorisering om den kördes
    kat_posts = getattr(csm, "_kat_posts", None)
    if (
        kat_posts
        and EVIDENCE_CATEGORIZER_AVAILABLE
        and _kat_exportera_json is not None
        and _kat_exportera_markdown is not None
    ):
        # SFCAE-PORT: sfcae:s exportera_json/markdown tar en
        # KategoriseringsRapport och returnerar "EXPORTED" eller
        # "KAN EJ EXPORTERAS: <skäl>". Källan skickade postlistan direkt och
        # ignorerade returvärdet → tom fil och falskt "Exporterade".
        try:
            from collections import Counter as _Counter
            _rapport = _ec_mod.KategoriseringsRapport(
                case_id=str(csm.case_id),
                totalt_filer=len(kat_posts),
                poster=list(kat_posts),
                kategori_statistik=dict(_Counter(
                    str(getattr(p_, "kategori", "")) for p_ in kat_posts)),
            )
            utfall = {
                "json": _kat_exportera_json(_rapport, str(output_dir)),
                "markdown": _kat_exportera_markdown(_rapport, str(output_dir)),
            }
        except Exception as e:
            utfall = {"json": f"KAN EJ EXPORTERAS: {type(e).__name__}: {e}",
                      "markdown": "EJ FÖRSÖKT"}
        csm._kat_export = utfall  # type: ignore[attr-defined]
        if all(v == "EXPORTED" for v in utfall.values()):
            log.info("[EVIDENCE_CATEGORIZER] Exporterade bevis_kategorisering.json/.md")
        else:
            log.warning(f"[EVIDENCE_CATEGORIZER] Export ofullständig: {utfall}")

    elapsed = time.time() - t0
    log.info("=" * 72)
    log.info(f"v{MOTOR_VERSION} PIPELINE KLAR på {elapsed:.2f}s")
    log.info(f"  Filer:           {csm.total_files}")
    log.info(f"  Locked/Karantän: {csm.locked_count}/{csm.quarantine_count}")
    log.info(f"  Graf:            {len(csm.graph.nodes)} noder, {len(csm.graph.edges)} kanter")
    log.info(f"  Gatekeeper:      {csm.gatekeeper_passed} godkänd / {csm.gatekeeper_blocked} blockerad")
    log.info(f"  Agent A/B/C:     {len(csm.agent_a_findings)}/{len(csm.agent_b_findings)}/{len(csm.agent_c_findings)}")
    log.info(f"  Falsifiering:    {_to_json(csm.falsification_verdict)}")
    log.info(f"  Audit-status:    {_to_json(csm.audit_status)}")
    log.info(f"  Sårbarhet:       {csm.sårbarhet_risk}")
    log.info(f"  Patcher:         {len(csm.patches)}")
    log.info(f"  Hard Stop:       {csm.hard_stop}")
    log.info(f"  JSON:            {json_path}")
    log.info(f"  Rapport:         {md_path}")
    log.info("=" * 72)


# ─────────────────────────────────────────────────────────────────────────────
# ENTRYPOINT
# ─────────────────────────────────────────────────────────────────────────────
# Bakåtkompatibel alias
def run_pipeline_v10(*args, **kwargs):
    return run_pipeline_v10_v3(*args, **kwargs)


if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser(
        description=f"FORENSIC COURT AUDIT ENGINE v{MOTOR_VERSION}"
    )
    parser.add_argument(
        "root_dirs", nargs="+",
        help="En eller flera rot-mappar att skanna",
    )
    parser.add_argument("--output",      default=str(Path(__file__).resolve().parent.parent / "output"))
    parser.add_argument("--domstol",     default="EJ ANGIVEN")
    parser.add_argument("--processform", default="EJ ANGIVEN")
    parser.add_argument("--yrkande",     default="EJ ANGIVET")
    parser.add_argument("--legal-rule",  default="EJ IDENTIFIERAD")
    parser.add_argument("--requisite",   default="EJ IDENTIFIERAD")
    args = parser.parse_args()

    csm = run_pipeline_v10(
        root_dirs=args.root_dirs,
        output_dir=args.output,
        case_metadata={
            "domstol":    args.domstol,
            "processform": args.processform,
            "yrkande":    args.yrkande,
            "legal_rule": args.legal_rule,
            "requisite":  args.requisite,
        },
    )

    print("\n" + "═" * 70)
    print(f"FORENSIC COURT AUDIT ENGINE v{MOTOR_VERSION} — SAMMANFATTNING")
    print("═" * 70)
    print(f"Case ID:            {csm.case_id}")
    print(f"Slutstatus:         {csm.current_state}")
    print(f"Filer:              {csm.total_files}")
    print(f"Graf:               {len(csm.graph.nodes)} noder / {len(csm.graph.edges)} kanter")
    print(f"Gatekeeper:         {csm.gatekeeper_passed} ✓ / {csm.gatekeeper_blocked} ✗")
    print(f"Falsifiering:       {_to_json(csm.falsification_verdict)}")
    print(f"Motkedjestyrka:     {csm.counter_chain_strength}")
    print(f"Audit-status:       {_to_json(csm.audit_status)}")
    print(f"Sårbarhet:          {csm.sårbarhet_risk}")
    print(f"Self-healing patch: {len(csm.patches)}")
    print(f"Hard Stop:          {csm.hard_stop}")
    if csm.judgment_draft:
        print(f"\nPROVISORISKT DOMSUTKAST:")
        print(f"  Symmetri (P18):   {'✅ GODKÄND' if csm.judgment_draft.symmetry_verified else '⚠️ EJ UPPFYLLD'}")
        print(f"  Slutsats:         {csm.judgment_draft.provisional_conclusion[:80]}...")
    if csm.patches:
        print(f"\nSelf-Healing Patcher:")
        for p in csm.patches:
            print(f"  [{p.patch_id}] {p.severity}: {p.rule_added[:60]}...")
    print("═" * 70)


# ─────────────────────────────────────────────────────────────────────────────
# SFCAE-INTEGRATION (Alt B, requested=True)
# ─────────────────────────────────────────────────────────────────────────────
def _gate_status(gate) -> str:
    if gate is None:
        return "EJ_KÖRD"
    if not (getattr(gate, "items", None) or []):
        return "EJ_PRÖVAD (ingen rättsregel att binda rekvisit till)"
    return "GODKÄND" if getattr(gate, "gate_passed", False) else "SPÄRRAD"


def _motor_c_sammanfattning(csm) -> Dict:
    def _d(o):
        if o is None:
            return None
        if hasattr(o, "to_dict"):
            try:
                return o.to_dict()
            except Exception:
                pass
        try:
            return asdict(o)
        except Exception:
            return str(o)
    return {
        "motor": "Motor C v" + MOTOR_VERSION,
        "case_id": getattr(csm, "case_id", ""),
        "slutläge": str(getattr(csm, "current_state", "")),
        "tillståndshistorik": list(getattr(csm, "state_history", []) or []),
        "hard_stop": bool(getattr(csm, "hard_stop", False)),
        "hard_stop_reason": getattr(csm, "hard_stop_reason", ""),
        "audit_status": str(getattr(csm, "audit_status", "")),
        "filer": getattr(csm, "total_files", 0),
        "holding_chains": [_d(h) for h in (getattr(csm, "holding_chains", []) or [])],
        "requisite_gate": _d(getattr(csm, "requisite_gate", None)),
        # gate_passed=True utan prövade rekvisit betyder "inget att pröva",
        # inte "rekvisit uppfyllda" — redovisas därför som EJ_PRÖVAD.
        "requisite_gate_status": _gate_status(getattr(csm, "requisite_gate", None)),
        "bevis_kategorisering_export": getattr(csm, "_kat_export", None),
        "unsolicited_validations": [_d(u) for u in (getattr(csm, "unsolicited_validations", []) or [])],
        "pre_trial": _d(getattr(csm, "pre_trial", None)),
        "agent_a_findings": list(getattr(csm, "agent_a_findings", []) or []),
        "agent_b_findings": list(getattr(csm, "agent_b_findings", []) or []),
        "agent_c_findings": list(getattr(csm, "agent_c_findings", []) or []),
        "falsification_verdict": str(getattr(csm, "falsification_verdict", "")),
        "not": "INDIKATIV_ENDAST. Parallell valideringsmotor; ersätter inte canonical.",
    }


def run_motor_c_if_requested(root_dirs: Optional[List[str]] = None,
                             output_dir: str = "",
                             case_meta: Optional[Dict] = None,
                             requested: bool = False) -> Dict:
    """Kör Motor C (HoldingChain, LegalRequisiteGate, Unsolicited, Bidirectional
    audit, 21-tillståndsmaskinen) på samma ärende. Endast med requested=True."""
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "Motor C kräver requested=True."}
    if not root_dirs:
        return {"status": "PARAMS_SAKNAS", "krävs": ["root_dirs"]}
    if not output_dir:
        return {"status": "PARAMS_SAKNAS", "krävs": ["output_dir"],
                "detail": "Motor C skriver rapportfiler; ange en outputmapp utanför ärendet."}
    ut = os.path.join(output_dir, "motor_c")
    for r in root_dirs:
        rr = os.path.realpath(r)
        ur = os.path.realpath(ut)
        if ur == rr or ur.startswith(rr + os.sep):
            return {"status": "FEL", "detail": "Outputmapp får inte ligga i ärendemappen."}
    os.makedirs(ut, exist_ok=True)
    csm = run_pipeline_v10_v3(root_dirs=list(root_dirs), output_dir=ut,
                              case_metadata=dict(case_meta or {}))
    res = _motor_c_sammanfattning(csm)
    res["status"] = "HARD_STOP" if res["hard_stop"] else "GENOMFÖRD"
    res["output_dir"] = ut
    return res
