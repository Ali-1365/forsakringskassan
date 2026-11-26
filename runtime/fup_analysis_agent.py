from __future__ import annotations
# PASSIV MOTIVERING: FUP-analys — anropas av motor_b_agents.py.
# Bibehålls per arkitekturbeslutet.
_PASSIV_MOTIVERING = True

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FUP ANALYSIS AGENT – L9 FÖRUNDERSÖKNINGSMATERIAL
SVENSK FORENSIC COURT AUDIT ENGINE v10.3-UPDATED
Datum: 2026-08-23

Separat L9-analysgren för förundersökningsmaterial (ingen dom att granska).
Analyserar beviskedjor, diskrepanser och processuella brister direkt
mot primärkällor i FUP-materialet.

ABSOLUTA REGLER:
- CIRCULAR_REASONING_BLOCKER: FUP-text får ALDRIG användas som primärkälla
  för de fakta FUP sedan bedömer
- Ingen rättslig slutsats utan verifierad kedja (P07)
- Procentuell bevisvärdering förbjuden (P10)
- Varje diskrepans kräver källhänvisning på båda sidor
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any
from enum import Enum

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from forensic_engine_v10_3_canonical import (
    ClaimId, CaseState, CourtType, ProcessMode,
    AuditStatus, AuditFinding, HardStopCode,
)
from claim_classifier import JuridiskKlass, KlassificeratSegment


# ============================================================
# DOKUMENTTYPER OCH DISKREPANSPOLICY (config-styrt)
# ============================================================

_DOKTYP_CACHE: Optional[Dict[str, Any]] = None

# Orsaken till att dokumenttypskonfigurationen inte kunde läsas, eller None.
_DOKTYP_LADDNINGSFEL: Optional[str] = None


def dokumenttypskonfig_laddningsfel() -> Optional[str]:
    """Felet som hindrade config/dokumenttyper.yaml från att läsas, eller None."""
    return _DOKTYP_LADDNINGSFEL


def _dokumenttypskonfig() -> Dict[str, Any]:
    """Läser config/dokumenttyper.yaml. Tom dict om den saknas."""
    global _DOKTYP_CACHE
    if _DOKTYP_CACHE is not None:
        return _DOKTYP_CACHE
    global _DOKTYP_LADDNINGSFEL
    data = None
    _DOKTYP_LADDNINGSFEL = None
    try:
        import config_loader
        data = config_loader.ladda("dokumenttyper")
    except Exception as exc:
        # En trasig dokumenttyper.yaml gav tidigare tom konfiguration, varpå
        # varje handling blev otypad — utan att något angav att orsaken var
        # ett konfigurationsfel och inte materialet.
        data = None
        _DOKTYP_LADDNINGSFEL = f"{type(exc).__name__}: {exc}"
    _DOKTYP_CACHE = data if isinstance(data, dict) else {}
    return _DOKTYP_CACHE


def _diskrepanspolicy() -> Dict[str, Any]:
    """Jämförelsepolicyn för diskrepansanalysen."""
    p = _dokumenttypskonfig().get("diskrepansanalys")
    return p if isinstance(p, dict) else {}


# Termer kortare än så här måste stå som eget ord i filnamnet. Längre termer
# får matcha som del av en sammansättning.
_MIN_LÄNGD_FÖR_SAMMANSÄTTNING = 5


def _ord_i_filnamn(term: str, filnamn: str) -> bool:
    """
    Matchning av handlingstyp i filnamn, anpassad för svenska sammansättningar.

    Ren delsträngsökning är fel: "dom" förekommer inuti "sjukdom", så en
    forskarrapport om psykisk sjukdom klassades som DOM — med följden att
    motorn trodde att akten innehöll en dom och stängde av FUP-grenen.

    Ren ordgränsmatchning är också fel: "Polisförhör" ÄR ett förhör, och
    "Huvudanmälan" ÄR en anmälan. Svenska handlingstyper skrivs normalt som
    sammansättningar.

    Skillnaden är termens längd. Korta termer (< 5 tecken) råkar ofta ingå i
    andra ord och kräver därför ordgräns. Längre termer är tillräckligt
    särskiljande för att få matcha inuti en sammansättning.
    """
    if not term:
        return False
    if len(term) >= _MIN_LÄNGD_FÖR_SAMMANSÄTTNING:
        return term in filnamn
    icke_ord = r"[^0-9A-Za-zÅÄÖåäöÉéÜü]"
    mönster = r"(?:^|" + icke_ord + r")" + re.escape(term) + r"(?:$|" + icke_ord + r")"
    return re.search(mönster, filnamn) is not None


# Hur många tecken av dokumentets början som läses vid innehållsklassificering.
# Handlingstypen anges normalt i sidhuvud eller ingress.
_INNEHÅLL_PROV = 2000


def klassificera_dokumenttyp(
    filnamn: str,
    text: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Bestämmer (dokumenttyp, kategori) för en handling.

    Filnamnet prövas först. Ger det ingen typ används handlingens eget
    innehåll — ett filnamn som bara är ett myndighetsnamn
    ("Arbetsförmedlingen.txt") säger inget om handlingstypen, medan texten
    inleds med "om ditt ärende ... Beslut ... Bifall".

    Att lägga in myndighetsnamn bland nyckelorden vore fel väg: det gör ett
    enskilt ärendes aktörer till generell klassificeringslogik.

    Returnerar ("okänd", "ÖVRIGT") när varken filnamn eller innehåll räcker.
    """
    typer = _dokumenttypskonfig().get("dokumenttyper") or {}

    def _bäst(prov: str, matchare) -> Tuple[str, str, int]:
        bästa = ("okänd", "ÖVRIGT", 0)
        for typnamn, profil in typer.items():
            if not isinstance(profil, dict):
                continue
            for kw in (profil.get("filnamn_nyckelord") or []):
                k = str(kw).lower()
                # Längsta matchande nyckelord vinner, så att "huvudanmälan"
                # inte råkar klassas av ett kortare, mindre specifikt ord.
                if k and len(k) > bästa[2] and matchare(k, prov):
                    bästa = (str(typnamn),
                             str(profil.get("kategori", "ÖVRIGT")), len(k))
        return bästa

    träff = _bäst((filnamn or "").lower(), _ord_i_filnamn)
    if träff[0] != "okänd":
        return träff[0], träff[1]

    if text:
        prov = str(text)[:_INNEHÅLL_PROV].lower()
        träff = _bäst(prov, _ord_i_filnamn)
        if träff[0] != "okänd":
            return träff[0], träff[1]

    return "okänd", "ÖVRIGT"


def akten_innehåller_dom(case_state) -> bool:
    """
    True om akten innehåller en dom eller ett rättens protokoll.

    Avgör om L9 ska köra domskälsanalys eller FUP-analysgrenen. Kontrollen
    gjordes tidigare med `"dom" in filnamn`, vilket träffade inuti "sjukdom":
    en forskarrapport om psykisk sjukdom fick motorn att tro att en dom fanns,
    varpå FUP-grenen — och därmed hela diskrepansanalysen — stängdes av.
    """
    for f in getattr(case_state, "files", []) or []:
        for namn in (getattr(f, "relative_path", ""), getattr(f, "file_id", "")):
            typ, _ = klassificera_dokumenttyp(str(namn).lower())
            if typ == "dom":
                return True
    return False


# ============================================================
# DATAKLASSER
# ============================================================

class DiskrepansTyp(Enum):
    UTELÄMNAT       = "UTELÄMNAT"        # Källa A utelämnar vad källa B visar
    TILLAGT         = "TILLAGT"          # Källa A lägger till vad källa B inte visar
    FÖRÄNDRAT       = "FÖRÄNDRAT"        # Källa A ändrar vad källa B visar
    MOTSTRIDIGT     = "MOTSTRIDIGT"      # Källorna pekar åt olika håll
    KAN_EJ_AVGÖRAS  = "KAN_EJ_AVGÖRAS"  # Otillräckligt underlag


@dataclass
class FUPDiskrepans:
    """En identifierad diskrepans i FUP-materialet."""
    diskrepans_id: str
    typ: DiskrepansTyp
    källa_a_id: str
    källa_a_text: str
    källa_a_ref: str       # KÄLL-ID | FIL | SIDA | DATUM
    källa_b_id: str
    källa_b_text: str
    källa_b_ref: str
    beskrivning: str
    rättslig_relevans: str  # HÖG | MEDEL | LÅG
    audit_status: AuditStatus

    def to_formatted_string(self) -> str:
        return (
            f"[{self.diskrepans_id}] {self.typ.value}\n"
            f"  KÄLLA A: {self.källa_a_text[:120]}\n"
            f"           [{self.källa_a_ref}]\n"
            f"  KÄLLA B: {self.källa_b_text[:120]}\n"
            f"           [{self.källa_b_ref}]\n"
            f"  DISKREPANS: {self.beskrivning}\n"
            f"  RÄTTSLIG RELEVANS: {self.rättslig_relevans} | "
            f"STATUS: {self.audit_status.value}"
        )


@dataclass
class BeviskedjeLed:
    """Ett led i en beviskedja."""
    led_nummer: int
    led_namn: str
    beskrivning: str
    status: str              # STYRKT | OBESTYRKT | TVISTIGT | KAN_EJ_AVGÖRAS
    primärkälla_id: str      # claim_id eller NOT_VERIFIABLE
    primärkälla_ref: str
    primärkälla_text: str
    motbevisning: str = "SAKNAS"
    anmärkning: str = ""


@dataclass
class FUPAnalysResult:
    """Resultat från FUP-analysen."""
    beviskedjor: Dict[str, List[BeviskedjeLed]] = field(default_factory=dict)
    diskrepanser: List[FUPDiskrepans] = field(default_factory=list)
    obestyrkta_led: List[str] = field(default_factory=list)
    audit_findings: List[AuditFinding] = field(default_factory=list)
    overall_status: AuditStatus = AuditStatus.H
    warnings: List[str] = field(default_factory=list)


# ============================================================
# FUP ANALYSIS AGENT
# ============================================================

class FUPAnalysAgent:
    """
    L9 FUP-analysgren: Analyserar förundersökningsmaterial.

    Till skillnad från DomskälsmatrisAgent (som granskar en dom)
    analyserar denna agent:
    1. Beviskedjor i FUP-materialet
    2. Diskrepanser mellan olika källors uppgifter
    3. Processuella brister i utredningen
    4. Obestyrkta påståenden i FUP

    Aktiveras när:
    - Ingen dom finns (HS01A aktiv)
    - Materialet innehåller FUP, förhör, vittnesförhör, reskontra
    - ProcessMode = JUDGMENT_AUDIT med FUP-material
    """

    # Signalord för FUP-specifika dokumenttyper
    FUP_DOK_SIGNALS = [
        "förundersökning", "fup", "förhör", "vittnesförhör",
        "polisanmälan", "beslagsprotokoll", "pm ", "transkription",
        "reskontra", "faktura", "epost", "mail", "brev",
    ]

    # Beviskedjemönster per brottstyp
    BEVISKEDJOR = {
        "olovligt_förfogande": [
            BeviskedjeLed(1, "Upprättande", "Dokumentet upprättat och daterat",
                         "OBESTYRKT", "NOT_VERIFIABLE", "", ""),
            BeviskedjeLed(2, "Avsändande", "Dokumentet faktiskt avsänt",
                         "OBESTYRKT", "NOT_VERIFIABLE", "", ""),
            BeviskedjeLed(3, "Försändelsesätt", "Avsänt på föreskrivet sätt (rekommenderat)",
                         "OBESTYRKT", "NOT_VERIFIABLE", "", ""),
            BeviskedjeLed(4, "Adress", "Korrekt adress använd",
                         "OBESTYRKT", "NOT_VERIFIABLE", "", ""),
            BeviskedjeLed(5, "Faktisk ankomst", "Dokumentet kom fram till adressen",
                         "OBESTYRKT", "NOT_VERIFIABLE", "", ""),
            BeviskedjeLed(6, "Mottagande", "Mottagaren tog emot dokumentet",
                         "OBESTYRKT", "NOT_VERIFIABLE", "", ""),
            BeviskedjeLed(7, "Fristens startpunkt", "Fristen började löpa",
                         "OBESTYRKT", "NOT_VERIFIABLE", "", ""),
        ],
        "sjukpenning": [
            BeviskedjeLed(1, "Diagnos", "Medicinsk diagnos styrkt av läkare",
                         "OBESTYRKT", "NOT_VERIFIABLE", "", ""),
            BeviskedjeLed(2, "Funktionsnedsättning", "Diagnosen påverkar funktioner",
                         "OBESTYRKT", "NOT_VERIFIABLE", "", ""),
            BeviskedjeLed(3, "Aktivitetsbegränsning", "Funktionsnedsättning begränsar arbetsförmåga",
                         "OBESTYRKT", "NOT_VERIFIABLE", "", ""),
            BeviskedjeLed(4, "Graden av nedsättning", "Nedsättning minst 25%",
                         "OBESTYRKT", "NOT_VERIFIABLE", "", ""),
        ],
    }

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.log: List[str] = []
        self._diskrepans_counter = 0
        self._finding_counter = 0

    def run(
        self,
        case_state: CaseState,
        klassificerade: Optional[List[KlassificeratSegment]] = None,
        måltyp: str = "okänd",
    ) -> FUPAnalysResult:
        """
        Kör FUP-analys mot tillgängligt material.

        Args:
            case_state: CaseState med claims
            klassificerade: Klassificerade segment
            måltyp: Typ av mål (olovligt_förfogande, sjukpenning, etc.)
        """
        self.log.append(
            f"[FUP] FUP-analys startar. Måltyp: {måltyp}. "
            f"Claims: {len(case_state.claims)}"
        )

        result = FUPAnalysResult()

        if not case_state.claims:
            self.log.append("[FUP] VARNING: Inga claims – kör L2 + ClaimClassifier först")
            result.warnings.append("Inga claims att analysera")
            return result

        # 1. Analysera beviskedjor
        beviskedja = self._analyze_beviskedja(
            case_state, klassificerade, måltyp
        )
        result.beviskedjor[måltyp] = beviskedja

        # 2. Identifiera obestyrkta led
        result.obestyrkta_led = [
            f"Led {led.led_nummer}: {led.led_namn}"
            for led in beviskedja
            if led.status == "OBESTYRKT"
        ]

        # 3. Identifiera diskrepanser
        result.diskrepanser = self._identify_diskrepanser(
            case_state, klassificerade
        )

        # 4. Generera audit-findings
        result.audit_findings = self._generate_findings(
            beviskedja, result.diskrepanser, case_state
        )

        # 5. Bestäm overall_status
        result.overall_status = self._determine_status(
            beviskedja, result.diskrepanser
        )

        # 6. Uppdatera case_state
        case_state.metadata["fup_analysis"] = {
            "måltyp": måltyp,
            "obestyrkta_led": result.obestyrkta_led,
            "diskrepanser_count": len(result.diskrepanser),
            "overall_status": result.overall_status.value,
        }

        # Lägg till findings i case_state
        case_state.audit_a_findings.extend(result.audit_findings)

        self.log.append(
            f"[FUP] Klar. Obestyrkta led: {len(result.obestyrkta_led)}, "
            f"Diskrepanser: {len(result.diskrepanser)}, "
            f"Status: {result.overall_status.value}"
        )

        return result

    def _analyze_beviskedja(
        self,
        case_state: CaseState,
        klassificerade: Optional[List[KlassificeratSegment]],
        måltyp: str,
    ) -> List[BeviskedjeLed]:
        """
        Analyserar beviskedjan för måltypen mot tillgängliga claims.
        Varje led analyseras självständigt – inget led används som
        bevis för nästa utan extern primärkälla.
        """
        import copy
        mall = self.BEVISKEDJOR.get(måltyp, [])
        if not mall:
            self.log.append(f"[FUP] Ingen beviskedjemall för måltyp: {måltyp}")
            return []

        # Kopiera mallen för att inte modifiera originalet
        kedjor = copy.deepcopy(mall)

        for led in kedjor:
            # Hitta relevanta claims för detta led
            relevanta = self._find_claims_for_led(
                led, case_state.claims, klassificerade
            )

            if relevanta:
                bästa = relevanta[0]
                led.primärkälla_id = bästa.claim_id
                led.primärkälla_ref = (
                    f"{bästa.source_id} | {bästa.file_name} | "
                    f"{bästa.page} | {bästa.date}"
                )
                led.primärkälla_text = bästa.content[:150]

                # Bestäm status baserat på claim-typ och innehåll
                led.status = self._determine_led_status(led, bästa)

                # Sök motbevisning
                led.motbevisning = self._find_motbevisning(
                    led, case_state.claims, bästa
                )
            else:
                led.status = "OBESTYRKT"
                led.primärkälla_id = "NOT_VERIFIABLE"
                led.primärkälla_ref = "KAN EJ VERIFIERAS – primärkälla saknas"
                led.primärkälla_text = ""

            self.log.append(
                f"[FUP] Led {led.led_nummer} ({led.led_namn}): {led.status}"
            )

        return kedjor

    def _find_claims_for_led(
        self,
        led: BeviskedjeLed,
        claims: List[ClaimId],
        klassificerade: Optional[List[KlassificeratSegment]],
    ) -> List[ClaimId]:
        """Hittar relevanta claims för ett beviskedjeled."""
        # Nyckelord per led
        led_nyckelord = {
            # Ett konkret datum ur ett tidigare ärende ("2025-12-10",
            # "december 2025") är borttaget: en enskild akts datum är inte en
            # generell indikator på att ett dokument upprättats.
            "Upprättande": ["daterat", "upprättat", "utfärdat", "skrivet",
                           "brev", "dokument"],
            "Avsändande": ["avsänt", "skickat", "postat", "avsändning",
                          "inlämnat", "postnord", "spårning"],
            "Försändelsesätt": ["rekommenderat", "rekommendation", "kvitto",
                               "spårningsnummer", "postnord"],
            # Gatunamnet ur ett tidigare ärende är borttaget: en specifik
            # adress säger ingenting om adressledet i ett annat ärende.
            "Adress": ["adress", "folkbokföring", "lgh",
                      "bostad", "hemadress"],
            "Faktisk ankomst": ["ankommit", "levererat", "framme", "brevlåda",
                               "besök", "lämnat"],
            "Mottagande": ["mottagit", "tagit emot", "fått", "erhållit",
                          "delgiven", "delgivning"],
            "Fristens startpunkt": ["frist", "börjar löpa", "startpunkt",
                                   "räknas från", "fyra veckor"],
            # Sjukpenning
            "Diagnos": ["diagnos", "sjukdom", "tillstånd", "icd",
                       "läkare", "specialist"],
            "Funktionsnedsättning": ["funktionsnedsättning", "funktion",
                                    "nedsatt", "begränsad"],
            "Aktivitetsbegränsning": ["aktivitetsbegränsning", "arbetsförmåga",
                                     "kan inte", "förmår inte"],
            "Graden av nedsättning": ["procent", "grad", "hel", "halv",
                                     "25", "50", "75", "100"],
        }

        nyckelord = led_nyckelord.get(led.led_namn, [])
        if not nyckelord:
            return []

        scored: List[Tuple[int, ClaimId]] = []
        for claim in claims:
            text_lower = claim.content.lower()
            score = sum(1 for kw in nyckelord if kw.lower() in text_lower)
            if score > 0:
                scored.append((score, claim))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:3]]

    def _determine_led_status(
        self,
        led: BeviskedjeLed,
        claim: ClaimId,
    ) -> str:
        """Bestämmer status för ett led baserat på claim-innehåll."""
        text_lower = claim.content.lower()

        # Negationer → OBESTYRKT
        negation_patterns = [
            r"\binte\b.*\b(skickat|avsänt|mottagit|fått)\b",
            r"\bnej\b", r"\bnekar\b", r"\bförnekar\b",
            r"\bkan\s+ej\s+verifieras\b",
            r"\bsaknas\b", r"\bfinns\s+inte\b",
            r"\bald(rig|rig)\b.*\b(fått|mottagit)\b",
        ]
        for pattern in negation_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return "TVISTIGT"

        # Bekräftelser → TVISTIGT (kräver mänsklig verifiering för STYRKT)
        bekräftelse_patterns = [
            r"\bhar\s+(skickat|avsänt|mottagit|fått)\b",
            r"\bbekräftar\b", r"\bverifierar\b",
            r"\bstyrkt\b", r"\bbevisat\b",
        ]
        for pattern in bekräftelse_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return "TVISTIGT"

        return "OBESTYRKT"

    def _find_motbevisning(
        self,
        led: BeviskedjeLed,
        claims: List[ClaimId],
        primärkälla: ClaimId,
    ) -> str:
        """Söker motbevisning för ett led."""
        negation_signals = [
            r"\binte\b", r"\bej\b", r"\bnej\b", r"\bnekar\b",
            r"\bbestrider\b", r"\bifrågasätter\b", r"\bförnekar\b",
        ]

        led_words = set(re.findall(r"\b\w{4,}\b", led.led_namn.lower()))

        for claim in claims:
            if claim.claim_id == primärkälla.claim_id:
                continue
            text_lower = claim.content.lower()
            claim_words = set(re.findall(r"\b\w{4,}\b", text_lower))
            overlap = len(led_words & claim_words)

            has_negation = any(
                re.search(p, text_lower) for p in negation_signals
            )

            if overlap >= 1 and has_negation:
                return (
                    f"{claim.content[:100]} "
                    f"[{claim.source_id} | {claim.file_name} | {claim.page}]"
                )

        return "SAKNAS"

    def _identify_diskrepanser(
        self,
        case_state: CaseState,
        klassificerade: Optional[List[KlassificeratSegment]],
    ) -> List[FUPDiskrepans]:
        """
        Identifierar diskrepanser mellan olika källors uppgifter.
        CIRCULAR_REASONING_BLOCKER: Ingen källa används som primärkälla
        för de fakta den sedan bedömer.
        """
        diskrepanser: List[FUPDiskrepans] = []
        if not case_state.claims:
            return diskrepanser

        policy = _diskrepanspolicy()
        min_ord = int(policy.get("min_gemensamma_ord", 3))
        max_df = float(policy.get("max_dokumentfrekvens", 0.10))
        max_par = int(policy.get("max_kandidatpar", 200000))
        max_disk = int(policy.get("max_diskrepanser", 50))
        kräv_olika = bool(policy.get("kräv_olika_källdokument", True))

        claims = case_state.claims
        # Förbered ordmängder en gång per claim — samma ordregel som
        # _compare_claims_for_diskrepans använder.
        stoppord = {str(w).lower() for w in (policy.get("stoppord") or [])}
        ordmängder = [
            set(re.findall(r"\b\w{5,}\b", c.content.lower())) - stoppord
            for c in claims
        ]

        # Inverterat index: ord → vilka claims som innehåller ordet.
        index: Dict[str, List[int]] = {}
        for i, ord_ in enumerate(ordmängder):
            for w in ord_:
                index.setdefault(w, []).append(i)

        # Blankettord (sidhuvuden, myndighetsnamn, formulärtext) förekommer i
        # nästan varje påstående och pekar inte ut ett gemensamt ämne. De
        # utesluts som kandidatnyckel — annars blir varje par kandidat.
        tak = max(2, int(len(claims) * max_df))
        särskiljande = {w: ids for w, ids in index.items() if 2 <= len(ids) <= tak}

        # Kandidatpar byggs ur indexet i stället för som kartesisk produkt.
        # Tidigare jämfördes endast förhör×myndighet och teknisk×myndighet,
        # båda dessutom avkortade till fem påståenden per grupp. På verkligt
        # material gav det noll jämförelser: förhör jämfördes aldrig mot
        # förhör, vilket är själva kärnan i ett utsagemål.
        par_räknare: Dict[Tuple[int, int], int] = {}
        for ids in särskiljande.values():
            for a_idx in range(len(ids)):
                for b_idx in range(a_idx + 1, len(ids)):
                    i, j = ids[a_idx], ids[b_idx]
                    if kräv_olika and claims[i].source_id == claims[j].source_id:
                        continue
                    par_räknare[(i, j)] = par_räknare.get((i, j), 0) + 1

        kandidater = [p for p, n in par_räknare.items() if n >= min_ord]
        # Starkast relaterade par först, så att en eventuell avkortning tar
        # bort de svagaste kandidaterna och inte godtyckliga.
        kandidater.sort(key=lambda p: par_räknare[p], reverse=True)
        prövade = kandidater[:max_par]

        for i, j in prövade:
            d = self._compare_claims_for_diskrepans(claims[i], claims[j])
            if d:
                diskrepanser.append(d)
                if len(diskrepanser) >= max_disk:
                    break

        # Omfattningen redovisas så att noll diskrepanser går att skilja från
        # noll utförda jämförelser.
        par_avkortade = len(kandidater) > max_par
        lista_avkortad = len(diskrepanser) >= max_disk
        case_state.metadata["diskrepansanalys"] = {
            "claims": len(claims),
            "särskiljande_ord": len(särskiljande),
            "kandidatpar": len(kandidater),
            "prövade_par": len(prövade),
            "uteslutna_par": max(0, len(kandidater) - len(prövade)),
            "diskrepanser": len(diskrepanser),
            # Två skilda avkortningar. Flaggan speglade tidigare bara
            # kandidatparen, så en kapad diskrepanslista redovisades som
            # fullständig.
            "avkortad": par_avkortade or lista_avkortad,
            "kandidatpar_avkortade": par_avkortade,
            "diskrepanslista_avkortad": lista_avkortad,
            "urvalsregel": (
                f"Högst {max_par} kandidatpar prövas och högst {max_disk} "
                f"diskrepanser redovisas. Kandidatpar bildas ur inverterat "
                f"index på särskiljande ord; par ur samma källdokument "
                f"utesluts."
            ),
        }
        self.log.append(
            f"[FUP] Diskrepansanalys: {len(kandidater)} kandidatpar, "
            f"{len(prövade)} prövade, {len(diskrepanser)} diskrepanser"
        )

        return diskrepanser

    def _compare_claims_for_diskrepans(
        self,
        claim_a: ClaimId,
        claim_b: ClaimId,
    ) -> Optional[FUPDiskrepans]:
        """
        Jämför två claims för diskrepans.
        Returnerar FUPDiskrepans om diskrepans identifieras.
        """
        text_a = claim_a.content.lower()
        text_b = claim_b.content.lower()

        # Hitta gemensamma nyckelord. Funktionsord räknas inte som ämne.
        stoppord = {str(w).lower() for w in (_diskrepanspolicy().get("stoppord") or [])}
        words_a = set(re.findall(r"\b\w{5,}\b", text_a)) - stoppord
        words_b = set(re.findall(r"\b\w{5,}\b", text_b)) - stoppord
        overlap = words_a & words_b

        min_ord = int(_diskrepanspolicy().get("min_gemensamma_ord", 3))
        if len(overlap) < min_ord:
            return None  # Inte tillräckligt relaterade

        # Kontrollera om de säger motsatta saker
        negation_a = bool(re.search(
            r"\b(inte|ej|nej|nekar|förnekar|bestrider)\b", text_a
        ))
        negation_b = bool(re.search(
            r"\b(inte|ej|nej|nekar|förnekar|bestrider)\b", text_b
        ))

        if negation_a == negation_b:
            return None  # Ingen tydlig diskrepans

        self._diskrepans_counter += 1
        diskrepans_id = f"D-{self._diskrepans_counter:03d}"

        # TYPNING — VAD TESTET FAKTISKT KAN VISA.
        #
        # Testet är: två handlingar berör samma ämnesord och exakt en av dem
        # innehåller ett nekande ord. Det är en INDIKATION på att källorna bör
        # jämföras — det är inte ett bevis för att de motsäger varandra.
        # Prövat mot verkligt förundersökningsmaterial gav märkningen
        # MOTSTRIDIGT övervägande falska utpekanden: två vittnen som beskriver
        # olika resor, eller ett förhör och en anmälan som beskriver SAMMA sak,
        # redovisades som motstridiga källor.
        #
        # Att påstå motstridighet mellan vittnen som inte motsäger varandra är
        # en allvarligare brist än att inte hitta något alls. Fyndet redovisas
        # därför som KAN_EJ_AVGÖRAS: samma ämne, olika källor, nekande på ena
        # sidan — jämförelsen ska göras av en människa.
        ämnen = ", ".join(sorted(overlap)[:5])
        typ = DiskrepansTyp.KAN_EJ_AVGÖRAS
        beskrivning = (
            f"Två skilda källor berör samma ämne ({ämnen}) och en av dem "
            f"innehåller ett nekande. INDIKATION för mänsklig jämförelse — "
            f"motstridighet är inte fastställd av systemet."
        )

        return FUPDiskrepans(
            diskrepans_id=diskrepans_id,
            typ=typ,
            källa_a_id=claim_a.claim_id,
            källa_a_text=claim_a.content[:150],
            källa_a_ref=(
                f"{claim_a.source_id} | {claim_a.file_name} | "
                f"{claim_a.page} | {claim_a.date}"
            ),
            källa_b_id=claim_b.claim_id,
            källa_b_text=claim_b.content[:150],
            källa_b_ref=(
                f"{claim_b.source_id} | {claim_b.file_name} | "
                f"{claim_b.page} | {claim_b.date}"
            ),
            beskrivning=beskrivning,
            # Relevansen får inte påstås av systemet. Fyndet är ett underlag
            # för granskning, inte en bedömd rättslig omständighet.
            rättslig_relevans="KRÄVER_MÄNSKLIG_BEDÖMNING",
            audit_status=AuditStatus.H,  # KAN INTE AVGÖRAS
        )

    def _generate_findings(
        self,
        beviskedja: List[BeviskedjeLed],
        diskrepanser: List[FUPDiskrepans],
        case_state: CaseState,
    ) -> List[AuditFinding]:
        """Genererar AuditFinding-objekt från FUP-analysen."""
        findings: List[AuditFinding] = []

        # Findings för obestyrkta led
        obestyrkta = [led for led in beviskedja if led.status == "OBESTYRKT"]
        if obestyrkta:
            self._finding_counter += 1
            findings.append(AuditFinding(
                finding_id=f"FUP-A-{self._finding_counter:03d}",
                agent="FUP",
                description=(
                    f"{len(obestyrkta)} obestyrkta led i beviskedjan: "
                    + ", ".join(f"Led {l.led_nummer} ({l.led_namn})"
                               for l in obestyrkta)
                ),
                source_ref="L9_FUP_BEVISKEDJA",
                severity="KRITISK",
            ))

        # Findings för diskrepanser
        for d in diskrepanser:
            self._finding_counter += 1
            findings.append(AuditFinding(
                finding_id=f"FUP-A-{self._finding_counter:03d}",
                agent="FUP",
                description=(
                    f"[{d.diskrepans_id}] {d.typ.value}: {d.beskrivning}"
                ),
                source_ref=f"{d.källa_a_ref} vs {d.källa_b_ref}",
                # Allvarlighetsgraden ska spegla vad fyndet faktiskt visar.
                # Ett fynd märkt KAN_EJ_AVGÖRAS är en indikation för mänsklig
                # jämförelse och får inte redovisas som HÖG allvarlighet.
                severity=(
                    "MEDEL" if d.typ == DiskrepansTyp.KAN_EJ_AVGÖRAS else "HÖG"
                ),
            ))

        return findings

    def _determine_status(
        self,
        beviskedja: List[BeviskedjeLed],
        diskrepanser: List[FUPDiskrepans],
    ) -> AuditStatus:
        """Bestämmer overall_status från FUP-analysen."""
        obestyrkta = sum(1 for led in beviskedja if led.status == "OBESTYRKT")
        tvistiga = sum(1 for led in beviskedja if led.status == "TVISTIGT")

        if obestyrkta > 3:
            return AuditStatus.G  # Potentiellt rättsligt relevant
        elif diskrepanser:
            return AuditStatus.G
        elif tvistiga > 0:
            return AuditStatus.H  # Kan inte avgöras
        else:
            return AuditStatus.H

    def generate_fup_report(self, result: FUPAnalysResult) -> str:
        """Genererar FUP-analysrapport i lagerformat."""
        lines = [
            "## LAGER 9 – FUP-ANALYSGREN (JUDGMENT_AUDIT utan dom)",
            "",
        ]

        for måltyp, kedja in result.beviskedjor.items():
            lines.append(f"### Beviskedja: {måltyp}")
            lines.append("")

            styrkt = sum(1 for l in kedja if l.status == "STYRKT")
            tvistigt = sum(1 for l in kedja if l.status == "TVISTIGT")
            obestyrkt = sum(1 for l in kedja if l.status == "OBESTYRKT")

            lines.append(
                f"Styrkt: {styrkt} | Tvistigt: {tvistigt} | "
                f"Obestyrkt: {obestyrkt} av {len(kedja)} led"
            )
            lines.append("")

            for led in kedja:
                symbol = {
                    "STYRKT": "✓", "TVISTIGT": "~",
                    "OBESTYRKT": "✗", "KAN_EJ_AVGÖRAS": "?"
                }.get(led.status, "?")

                lines.append(
                    f"{symbol} Led {led.led_nummer}: {led.led_namn} "
                    f"[{led.status}]"
                )
                if led.primärkälla_text:
                    lines.append(
                        f"   Primärkälla: \"{led.primärkälla_text[:100]}...\""
                    )
                    lines.append(f"   Ref: [{led.primärkälla_ref}]")
                else:
                    lines.append(
                        "   Primärkälla: KAN EJ VERIFIERAS – saknas i materialet"
                    )
                if led.motbevisning != "SAKNAS":
                    lines.append(f"   Motbevisning: {led.motbevisning[:80]}")
                lines.append("")

        if result.diskrepanser:
            lines.append("### Identifierade diskrepanser")
            lines.append("")
            for d in result.diskrepanser:
                lines.append(d.to_formatted_string())
                lines.append("")

        if result.obestyrkta_led:
            lines.append("### Obestyrkta led (kräver komplettering)")
            for led in result.obestyrkta_led:
                lines.append(f"  ✗ {led}")
            lines.append("")

        lines.extend([
            f"OVERALL_STATUS: {result.overall_status.value}",
            "",
            "[L9 | FUP-ANALYSGREN | LOCKED]",
        ])
        return "\n".join(lines)