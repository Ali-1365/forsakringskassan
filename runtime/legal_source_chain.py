# SFCAE-BINDNING: legal_source_chain
# Roll: Alt B — STEG 12 källkedja: källklassificering, auktoritet, register,
#       historisk lydelse, källhash (verifiering av rättskällan som sådan).
# Producerar aldrig domslut. INDIKATIV_ENDAST.
# PORTERAD 2026-10-09 från C:\AI_Projects\sfcae_nymapp_karantan_2026-09-24\Ny mapp\legal_source_chain.py
# (24 303 B, enda kända källan). Kompletterar — ersätter inte — runtime/kallkedja.py
# (som spårar resultat bakåt till claim) och lagskifte_validator (lagversioner).
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LEGAL SOURCE CHAIN — STEG 12: DYNAMISK AUKTORITATIV RÄTTSKÄLLEMOTOR
====================================================================

Implementerar den faktiska källkedjan (STEG 12B):

    CASE
    → LEGAL QUESTION
    → REQUIRED LEGAL SOURCE TYPE
    → SEARCH
    → SOURCE IDENTIFICATION
    → AUTHORITY CLASSIFICATION
    → SOURCE RETRIEVAL
    → SOURCE HASH
    → VERSION/DATE
    → HISTORICAL VALIDITY
    → EXACT SOURCE TEXT
    → LEGAL SOURCE RECORD
    → REQUISITE EXTRACTION
    → SUBSUMPTION INPUT

ABSOLUTA REGLER (STEG 12-överordnat krav):
- Ingen juridisk slutsats får hårdkodas.
- Ingen specifik lagregel får hårdkodas som universell regel.
- Ingen specifik domstol/målkategori/praxis får hårdkodas som standardsvar.
- Ingen extern källa får behandlas som auktoritativ enbart på grund av URL,
  domännamn eller sökträff.

STEG 12C — HISTORISK LYDELSE:
    RELEVANT_DATE → SOURCE_VERSION → EFFECTIVE_FROM → EFFECTIVE_TO
    → APPLICABLE_VERSION
Om historisk lydelse inte kan verifieras: STATUS = BLOCKED, aldrig VERIFIED.

STEG 12D — EXTERN KÄLLA FÅR INTE BARA "HITTAS":
För varje rättskälla måste systemet kunna visa:
    source_id, source_type, authority_level, source_url/identifier,
    source_hash, retrieval_timestamp, effective_date/version, exact_text,
    provenance, verification_status.
En sökträff är inte en verifierad rättskälla.

STEG 12F — REGISTERS:
Identifierar exakt vilka register som krävs. Om nödvändigt register inte är
tillgängligt → REGISTER_SAKNAS och systemet behåller BLOCKED/PARTIAL.
Ingen syntetisk registerdata skapas.
"""
from __future__ import annotations

import datetime
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
# ─────────────────────────────────────────────────────────────────────────────
# OBLIGATORISK KLASSIFICERING (STEG 12B)
# ─────────────────────────────────────────────────────────────────────────────

SOURCE_TYPES = [
    "LAG", "FÖRORDNING", "PREJUDIKAT", "FÖRARBETE", "EU",
    "EKMR", "ÖVERRÄTT", "MYNDIGHET", "DOKTRIN", "ÖVRIG",
]

AUTHORITY_LEVELS = [
    "BINDANDE", "PREJUDIKATIV", "VÄGLEDANDE", "INFORMERANDE",
    "EJ_RÄTTSKÄLLA",
]

# Källtyper som aldrig får bära rekvisit (EJ_RÄTTSKÄLLA)
_EJ_RÄTTSKÄLLA_SOURCE_TYPES = {"DOKTRIN", "ARTIKEL", "AI_GENERERAT", "MYNDIGHET"}

# Mappning source_type → tillåten authority (deterministisk, ej hårdkodad slutsats)
_ALLOWED_AUTHORITY = {
    "LAG": {"BINDANDE"},
    "FÖRORDNING": {"BINDANDE"},
    "PREJUDIKAT": {"PREJUDIKATIV"},
    "FÖRARBETE": {"INFORMERANDE"},
    "EU": {"BINDANDE", "VÄGLEDANDE"},
    "EKMR": {"VÄGLEDANDE", "BINDANDE"},
    "ÖVERRÄTT": {"VÄGLEDANDE"},
    "MYNDIGHET": {"INFORMERANDE", "EJ_RÄTTSKÄLLA"},
    "DOKTRIN": {"INFORMERANDE", "EJ_RÄTTSKÄLLA"},
    "ÖVRIG": {"INFORMERANDE", "EJ_RÄTTSKÄLLA"},
}


def is_valid_source_type(source_type: str) -> bool:
    return (source_type or "").strip().upper() in SOURCE_TYPES


def is_valid_authority_level(authority_level: str) -> bool:
    return (authority_level or "").strip().upper() in AUTHORITY_LEVELS


def classify_source(source_type: str, authority_level: str) -> Dict[str, Any]:
    """Obligatorisk klassificering (FIX-N / STEG 12B).

    Returnerar klassificering + blockering. En källa blockeras från att bära
    rekvisit om den är EJ_RÄTTSKÄLLA eller har ogiltig kombination.
    """
    source_type = (source_type or "").strip().upper()
    authority_level = (authority_level or "").strip().upper()

    if not source_type:
        source_type = "OKÄND"
    if not authority_level:
        authority_level = "EJ_RÄTTSKÄLLA"

    blocked = False
    reasons: List[str] = []

    if authority_level == "EJ_RÄTTSKÄLLA":
        blocked = True
        reasons.append("AUTHORITY_LEVEL=EJ_RÄTTSKÄLLA → blockerad")
    if source_type in _EJ_RÄTTSKÄLLA_SOURCE_TYPES:
        blocked = True
        reasons.append(f"SOURCE_TYPE={source_type} → ej rättskälla")
    if source_type in _ALLOWED_AUTHORITY and authority_level not in _ALLOWED_AUTHORITY[source_type]:
        blocked = True
        reasons.append(
            f"ogiltig kombination {source_type}/{authority_level} → blockerad"
        )

    return {
        "source_type": source_type,
        "authority_level": authority_level,
        "blocked_from_requisites": blocked,
        "blocking_reason": "; ".join(reasons),
        "klassificering": "EJ_RÄTTSKÄLLA" if blocked else "RÄTTSKÄLLA",
    }


# ─────────────────────────────────────────────────────────────────────────────
# DATUMMODELL (STEG 12C)
# ─────────────────────────────────────────────────────────────────────────────

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date(value: Optional[str]) -> Optional[datetime.date]:
    """Parsar en datumsträng (ÅÅÅÅ-MM-DD). None om ogiltig."""
    if not value:
        return None
    m = _DATE_RE.match(str(value).strip())
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def historical_validity(
    relevant_date: Optional[str],
    effective_from: Optional[str],
    effective_to: Optional[str],
) -> Dict[str, Any]:
    """STEG 12C: Verifierar att en källversion gällde vid RELEVANT_DATE.

    Kedja: RELEVANT_DATE → EFFECTIVE_FROM → EFFECTIVE_TO → APPLICABLE_VERSION.

    Returnerar:
        verification_status: VERIFIED | BLOCKED
        applicable: bool
        blocking_reason: str (tom om VERIFIED)
    """
    rd = parse_date(relevant_date)
    ef = parse_date(effective_from)
    et = parse_date(effective_to)

    # Kan historisk lydelse inte verifieras → BLOCKED, aldrig VERIFIED
    if rd is None:
        return {
            "verification_status": "BLOCKED",
            "applicable": False,
            "blocking_reason": "RELEVANT_DATE saknas eller ogiltig → historisk lydelse ej verifierbar",
        }
    if ef is None:
        return {
            "verification_status": "BLOCKED",
            "applicable": False,
            "blocking_reason": "EFFECTIVE_FROM saknas eller ogiltig → historisk lydelse ej verifierbar",
        }
    if rd < ef:
        return {
            "verification_status": "BLOCKED",
            "applicable": False,
            "blocking_reason": (
                f"RELEVANT_DATE {relevant_date} före EFFECTIVE_FROM "
                f"{effective_from} → versionen gällde ej då"
            ),
        }
    if et is not None and rd > et:
        return {
            "verification_status": "BLOCKED",
            "applicable": False,
            "blocking_reason": (
                f"RELEVANT_DATE {relevant_date} efter EFFECTIVE_TO "
                f"{effective_to} → versionen upphävd/ersatt"
            ),
        }
    return {
        "verification_status": "VERIFIED",
        "applicable": True,
        "blocking_reason": "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# KÄLLHASH OCH PROVENANCE (STEG 12D)
# ─────────────────────────────────────────────────────────────────────────────

def compute_text_hash(text: str) -> str:
    """SHA-256 av exakt källtext (deterministisk provenance)."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def utc_timestamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z"


# ─────────────────────────────────────────────────────────────────────────────
# REGISTER (STEG 12F)
# ─────────────────────────────────────────────────────────────────────────────

# Register som krävs för att juridiska slutsatser ska kunna verifieras.
# varje register har: källa, format, datum/version, provenance, schema.
# Om åtkomst inte kan verifieras → REGISTER_SAKNAS. Ingen syntetisk data.
REQUIRED_REGISTERS = {
    "SFS": {
        "källa": "Riksdagens öppna data (data.riksdagen.se, doktyp=sfs)",
        "format": "JSON/XML",
        "syfte": "Lagtext med ikraftträdande/ändringar (historisk lydelse)",
        "krävs_för": "Historisk lydelse av LAG/FÖRORDNING",
    },
    "PROP_BET_SOU": {
        "källa": "Riksdagens öppna data (data.riksdagen.se, doktyp=prop/bet/sou/ds)",
        "format": "JSON/XML",
        "syfte": "Förarbeten (propositioner, betänkanden, SOU/Ds)",
        "krävs_för": "FÖRARBETE-verifiering",
    },
    "RÄTTSPRAXIS": {
        "källa": "Sveriges Domstolar (rattspraxis.etjanst.domstol.se)",
        "format": "JSON",
        "syfte": "Prejudikat och överrättsavgöranden",
        "krävs_för": "PREJUDIKAT/ÖVERRÄTT-verifiering",
    },
    "EUR_LEX": {
        "källa": "publications.europa.eu / EUR-Lex",
        "format": "SPARQL/JSON",
        "syfte": "EU-förordningar/direktiv och CJEU-avgöranden",
        "krävs_för": "EU-verifiering",
    },
    "HUDOC": {
        "källa": "hudoc.echr.coe.int",
        "format": "JSON/XML",
        "syfte": "Europadomstolens avgöranden (EKMR)",
        "krävs_för": "EKMR-verifiering",
    },
}

class RegisterRegistry:
    """STEG 12F: Identifierar registerstatus utan att fabricera data."""

    def __init__(self, register_availability: Optional[Dict[str, bool]] = None):
        # register_availability: {register: accessible_bool}. Om ej angiven
        # testas faktisk åtkomst. Som default: ej verifierad → REGISTER_SAKNAS.
        self._availability = dict(register_availability or {})

    def register_status(self, register: str) -> Dict[str, Any]:
        spec = REQUIRED_REGISTERS.get(register)
        if spec is None:
            return {
                "register": register,
                "status": "REGISTER_SAKNAS",
                "reason": "okänt register",
            }
        accessible = self._availability.get(register)
        if accessible is None:
            return {
                "register": register,
                "status": "REGISTER_SAKNAS",
                "reason": "åtkomst ej verifierad — ingen syntetisk registerdata skapas",
                "källa": spec["källa"],
                "format": spec["format"],
                "syfte": spec["syfte"],
                "krävs_för": spec["krävs_för"],
            }
        if not accessible:
            return {
                "register": register,
                "status": "REGISTER_SAKNAS",
                "reason": "register ej åtkomligt i körningsmiljön",
                "källa": spec["källa"],
                "format": spec["format"],
                "syfte": spec["syfte"],
                "krävs_för": spec["krävs_för"],
            }
        return {
            "register": register,
            "status": "TILLGÄNGLIGT",
            "källa": spec["källa"],
            "format": spec["format"],
            "syfte": spec["syfte"],
            "krävs_för": spec["krävs_för"],
        }

    def all_register_status(self) -> Dict[str, Any]:
        return {
            register: self.register_status(register)
            for register in REQUIRED_REGISTERS
        }

    def required_registers_for_source_type(self, source_type: str) -> List[str]:
        """Exakt vilka register som krävs för en källtyp."""
        mapping = {
            "LAG": ["SFS"],
            "FÖRORDNING": ["SFS"],
            "PREJUDIKAT": ["RÄTTSPRAXIS"],
            "ÖVERRÄTT": ["RÄTTSPRAXIS"],
            "FÖRARBETE": ["PROP_BET_SOU"],
            "EU": ["EUR_LEX"],
            "EKMR": ["HUDOC"],
        }
        return mapping.get((source_type or "").upper(), [])


# ─────────────────────────────────────────────────────────────────────────────
# VERIFIERAD RÄTTSKÄLLA (STEG 12D-fullformat)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class VerifiedLegalSource:
    """Fullständig verifierad rättskälla (STEG 12D)."""
    source_id: str
    source_type: str
    authority_level: str
    source_url: str = ""
    source_identifier: str = ""          # SFS-nummer / målnummer / DOI
    source_hash: str = ""                 # SHA-256 av exact_text
    retrieval_timestamp: str = ""         # när källan hämtades
    effective_from: str = ""              # STEG 12C
    effective_to: str = ""                # STEG 12C
    source_version: str = ""              # version av lagtext/avgörande
    applicable_version: str = ""          # version som gällde vid relevant datum
    exact_text: str = ""                  # exakt källtext (STEG 12D)
    provenance: str = ""                  # hur källan erhölls
    verification_status: str = "BLOCKED"  # VERIFIED | PARTIAL | BLOCKED
    relevant_date: str = ""
    blocked_from_requisites: bool = False
    blocking_reason: str = ""
    required_registers: List[str] = field(default_factory=list)
    chain: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "authority_level": self.authority_level,
            "source_url": self.source_url,
            "source_identifier": self.source_identifier,
            "source_hash": self.source_hash,
            "retrieval_timestamp": self.retrieval_timestamp,
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "source_version": self.source_version,
            "applicable_version": self.applicable_version,
            "exact_text": self.exact_text,
            "provenance": self.provenance,
            "verification_status": self.verification_status,
            "relevant_date": self.relevant_date,
            "blocked_from_requisites": self.blocked_from_requisites,
            "blocking_reason": self.blocking_reason,
            "required_registers": self.required_registers,
            "chain": self.chain,
        }
# ─────────────────────────────────────────────────────────────────────────────
# DEN FAKTISKA KÄLLKEDJAN (STEG 12B)
# ─────────────────────────────────────────────────────────────────────────────

class LegalSourceChainEngine:
    """
    Utför hela källkedjan för ett rättsligt frågebehov.

    Flödet är mekaniskt och deterministiskt. Varje steg loggas. Om något steg
    inte kan verifieras (extern källa, historisk lydelse, register) → BLOCKED,
    aldrig VERIFIED. Ingen syntetisk data skapas.
    """

    def __init__(
        self,
        register_availability: Optional[Dict[str, bool]] = None,
        external_retrieval_available: bool = False,
    ):
        # external_retrieval_available: om falskt kan vi inte hämta externa
        # källor → varje extern källa förblir BLOCKED (ärligt).
        self._register_registry = RegisterRegistry(register_availability)
        self._external_available = external_retrieval_available
        self.log: List[str] = []

    def _step(self, name: str, status: str, detail: str) -> Dict[str, Any]:
        entry = {
            "step": name,
            "status": status,
            "detail": detail,
            "timestamp": utc_timestamp(),
        }
        self.log.append(f"[KÄLLKEDJA] {name}: {status} — {detail}")
        return entry

    def process_legal_question(
        self,
        legal_question: str,
        source_type: str,
        relevant_date: Optional[str] = None,
        source_url: str = "",
        source_identifier: str = "",
        exact_text: str = "",
        effective_from: str = "",
        effective_to: str = "",
        source_version: str = "",
        retrieval_evidence: str = "",
        candidate: Optional[Dict[str, Any]] = None,
    ) -> VerifiedLegalSource:
        """
        Kör den fullständiga källkedjan för en rättslig fråga.

        candidate: om en sökträff finns (från deep_search / externt), annars
                   None (källan hittades inte → BLOCKED).
        """
        chain: List[Dict[str, Any]] = []
        # SFCAE-PORT: hash() är slumpad per process (PYTHONHASHSEED) — id:t
        # blev olika mellan körningar. sha256 ger reproducerbart id.
        source_id = source_identifier if source_identifier else (
            "LS-" + hashlib.sha256((legal_question or "").encode("utf-8")).hexdigest()[:10])

        # ── Steg 1–2: Källklassificering (obligatorisk) ──────────────
        source_type_u = (source_type or "").strip().upper()
        authority_level_u = (candidate or {}).get("authority_level", "")
        classification = classify_source(source_type_u, authority_level_u)
        chain.append(self._step(
            "SOURCE_TYPE_CLASSIFICATION",
            "VERIFIED" if is_valid_source_type(source_type_u) else "BLOCKED",
            f"source_type={source_type_u}",
        ))
        chain.append(self._step(
            "AUTHORITY_CLASSIFICATION",
            "VERIFIED" if is_valid_authority_level(classification["authority_level"]) else "BLOCKED",
            f"authority_level={classification['authority_level']}",
        ))

        # ── Steg 3: Registers (STEG 12F) ─────────────────────────────
        required_registers = self._register_registry.required_registers_for_source_type(
            source_type_u
        )
        register_statuses = {
            r: self._register_registry.register_status(r) for r in required_registers
        }
        missing_registers = [
            r for r, st in register_statuses.items()
            if st["status"] != "TILLGÄNGLIGT"
        ]
        chain.append(self._step(
            "REGISTER_CHECK",
            "BLOCKED" if missing_registers else "VERIFIED",
            f"register={required_registers} saknas={missing_registers}",
        ))
# ── Steg 4: SOURCE RETRIEVAL ────────────────────────────────
        # En sökträff är inte en verifierad rättskälla (STEG 12D).
        # Extern hämtning kräver att retrieval faktiskt skedde.
        retrieval_status = "VERIFIED" if (self._external_available and retrieval_evidence) else "BLOCKED"
        chain.append(self._step(
            "SOURCE_RETRIEVAL",
            retrieval_status,
            f"url={source_url} evidence={'finns' if retrieval_evidence else 'saknas'}",
        ))

        # ── Steg 5: SOURCE HASH (provenance) ─────────────────────────
        source_hash = compute_text_hash(exact_text) if exact_text else ""
        chain.append(self._step(
            "SOURCE_HASH",
            "VERIFIED" if source_hash else "BLOCKED",
            f"hash={'finns' if source_hash else 'saknas (ingen exakt text)'}",
        ))

        # ── Steg 6: HISTORISK VALIDITET (STEG 12C) ───────────────────
        hist = historical_validity(relevant_date, effective_from, effective_to)
        applicable_version = source_version if hist["applicable"] else ""
        chain.append(self._step(
            "HISTORICAL_VALIDITY",
            hist["verification_status"],
            hist["blocking_reason"] or f"version {source_version} gällde vid {relevant_date}",
        ))

        # ── Steg 7: EXACT SOURCE TEXT ────────────────────────────────
        chain.append(self._step(
            "EXACT_SOURCE_TEXT",
            "VERIFIED" if exact_text else "BLOCKED",
            f"exact_text={'finns' if exact_text else 'saknas'}",
        ))

        # ── Steg 8: SLUTKLASSIFICERING ───────────────────────────────
        blocked = (
            classification["blocked_from_requisites"]
            or retrieval_status == "BLOCKED"
            or not source_hash
            or hist["verification_status"] == "BLOCKED"
            or not exact_text
            or bool(missing_registers)
        )
        blocking_reasons = []
        if classification["blocked_from_requisites"]:
            blocking_reasons.append(classification["blocking_reason"])
        if retrieval_status == "BLOCKED":
            blocking_reasons.append("extern källa ej hämtad/verifierad")
        if not source_hash:
            blocking_reasons.append("ingen exakt källtext → ingen källhash")
        if hist["verification_status"] == "BLOCKED":
            blocking_reasons.append(hist["blocking_reason"])
        if not exact_text:
            blocking_reasons.append("exact_text saknas")
        if missing_registers:
            blocking_reasons.append(f"nödvändiga register saknas: {missing_registers}")

        verification_status = "BLOCKED" if blocked else "VERIFIED"
        chain.append(self._step(
            "FINAL_CLASSIFICATION",
            verification_status,
            "; ".join(blocking_reasons) or "verifierad rättskälla",
        ))

        record = VerifiedLegalSource(
            source_id=source_id,
            source_type=source_type_u,
            authority_level=classification["authority_level"],
            source_url=source_url,
            source_identifier=source_identifier,
            source_hash=source_hash,
            retrieval_timestamp=utc_timestamp(),
            effective_from=effective_from,
            effective_to=effective_to,
            source_version=source_version,
            applicable_version=applicable_version,
            exact_text=exact_text,
            provenance=(
                f"retrieval={'externt' if retrieval_evidence else 'ej skett'}; "
                f"register={required_registers}"
            ),
            verification_status=verification_status,
            relevant_date=relevant_date or "",
            blocked_from_requisites=blocked,
            blocking_reason="; ".join(blocking_reasons),
            required_registers=required_registers,
            chain=chain,
        )
        return record


def _verifierad_holding(rec: Any) -> bool:
    hv = str(getattr(rec, "holding_verification", "") or "").upper()
    return hv.startswith("HOLDING_VERIFIERAD") or hv in {"H1", "VERIFIED", "VERIFIERAD"}


def run_legal_source_chain_if_requested(case_state: Any = None,
                                        legal_questions: Optional[List[Dict[str, Any]]] = None,
                                        relevant_date: str = "",
                                        register_availability: Optional[Dict[str, bool]] = None,
                                        requested: bool = False) -> Dict[str, Any]:
    """Alt B-ingång. Kör källkedjan för varje rättskälla i en kanonisk
    CaseState (legal_sources) och/eller för uttryckliga legal_questions.
    Ingen extern hämtning sker här → varje extern källa förblir BLOCKED
    (ärligt), aldrig VERIFIED."""
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "Källkedjan kräver requested=True."}
    motor = LegalSourceChainEngine(register_availability=register_availability,
                                   external_retrieval_available=False)
    poster: List[Dict[str, Any]] = []
    for rec in list(getattr(case_state, "legal_sources", []) or []):
        r = motor.process_legal_question(
            legal_question=str(getattr(rec, "legal_issue", "") or getattr(rec, "reference", "")),
            source_type=str(getattr(rec, "source_type", "") or ""),
            relevant_date=relevant_date or None,
            source_url=str(getattr(rec, "official_source", "") or ""),
            source_identifier=str(getattr(rec, "source_id", "") or ""),
            exact_text=str(getattr(rec, "holding", "") or "") if _verifierad_holding(rec) else "",
            candidate={"authority_level": str(getattr(rec, "authority_level", "") or "")},
        )
        poster.append(r.to_dict())
    for q in legal_questions or []:
        poster.append(motor.process_legal_question(**q).to_dict())
    verifierade = sum(1 for p in poster if p.get("verification_status") == "VERIFIED")
    blockerade = len(poster) - verifierade
    if not poster:
        status = "INGET_UNDERLAG"
    elif blockerade:
        # Blockerade källor får inte redovisas som genomförd källkedja.
        status = "DELVIS"
    else:
        status = "GENOMFÖRD"
    return {
        "status": status,
        "skäl": (f"{blockerade} av {len(poster)} källor BLOCKED — "
                 "extern hämtning ej kopplad") if blockerade else None,
        "antal": len(poster),
        "verifierade": verifierade,
        "blockerade": len(poster) - verifierade,
        "poster": poster,
        "logg": motor.log[-200:],
        "not": "Extern hämtning ej kopplad → externa källor förblir BLOCKED.",
    }
