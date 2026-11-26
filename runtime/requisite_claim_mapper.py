#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
REQUISITE CLAIM MAPPER – AUTOMATISK KOPPLING CLAIMS → REKVISIT
SVENSK FORENSIC COURT AUDIT ENGINE v10.3-UPDATED
Datum: 2026-08-23

Kopplar automatiskt klassificerade claims till rekvisit i rekvisitmatrisen.
Aktiverar LEGAL_REQUISITE_GATE på riktigt ärendematerial.

ABSOLUTA REGLER:
- Koppling baseras på semantisk relevans – aldrig automatisk slutsats
- BEVISNING_SAKNAS sätts när ingen claim kan kopplas till ett MUST-rekvisit
- Ingen rättslig slutsats dras automatiskt
- Alla kopplingar är spårbara till claim_id och källa
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Set, Any

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from forensic_engine_v10_3_canonical import (
    ClaimId, CaseState, CourtType, ProcessMode,
    RequisiteEntry, RequisiteStatus, ModalMarker,
    HardStopCode, LegalSourceRecord,
)
from claim_classifier import JuridiskKlass, KlassificeratSegment


# ============================================================
# REKVISITDEFINITIONER PER BROTTSTYP / MÅLTYP
#
# Enda källan är config/rekvisit_definitioner.yaml (se filens egen
# docstring: "en ny måltyp krävde ändring i källkod — otillåtet på en
# domstolsdator"). Listorna nedan är FALLBACK om config saknas eller
# inte går att läsa. Steg 15: listorna används INTE längre operativt - de
# innehåller exempelinnehåll (bl.a. "leasingavtalets punkt 11") som inte
# kommer ur ärendet eller en uttryckligen konfigurerad källa. Saknas eller
# brister config byggs inga rekvisit och orsaken redovisas
# (profil_laddningsfel); matrisen fylls aldrig med inbyggda exempel.
# Listorna står kvar orörda i väntan på användarens beslut om borttagning.
# ============================================================

# Rekvisit för olovligt förfogande (BrB 10:4)
_FALLBACK_REKVISIT_OLOVLIGT_FÖRFOGANDE = [
    {
        "text": "Egendom tillhör annan (äganderätt förbehållen)",
        "modal": ModalMarker.MUST,
        "lagrum": "BrB 10 kap. 4 § (SFS 1962:700)",
        "nyckelord": ["äganderätt", "förbehållen", "leasing", "leasingavtal",
                      "tillhör", "äger", "ägare", "hyra", "hyresavtal"],
    },
    {
        "text": "Giltig uppsägning kommunicerad till gäldenären",
        "modal": ModalMarker.MUST,
        "lagrum": "BrB 10 kap. 4 § + leasingavtalets punkt 11",
        "nyckelord": ["uppsägning", "uppsagt", "sagt upp", "rekommenderat",
                      "brev", "avsänt", "mottagit", "delgivning", "delgiven"],
    },
    {
        "text": "Underlåtenhet att återlämna efter fristens utgång",
        "modal": ModalMarker.MUST,
        "lagrum": "BrB 10 kap. 4 §",
        "nyckelord": ["återlämna", "återlämnande", "inte lämnat", "behållit",
                      "frist", "fristen", "löpt ut", "förfallen"],
    },
    {
        "text": "Uppsåt att olovligen förfoga",
        "modal": ModalMarker.MUST,
        "lagrum": "BrB 10 kap. 4 § + BrB 1:2",
        "nyckelord": ["uppsåt", "avsiktligt", "medvetet", "visste", "kände till",
                      "insåg", "förstod", "hade kännedom"],
    },
]

# Rekvisit för sjukpenning (27 kap. SFB)
_FALLBACK_REKVISIT_SJUKPENNING = [
    {
        "text": "Nedsatt arbetsförmåga på grund av sjukdom",
        "modal": ModalMarker.MUST,
        "lagrum": "27 kap. 2 § SFB (SFS 2010:110)",
        "nyckelord": ["arbetsförmåga", "nedsatt", "sjukdom", "diagnos",
                      "funktionsnedsättning", "aktivitetsbegränsning"],
    },
    {
        "text": "Arbetsförmågan nedsatt med minst 25 procent",
        "modal": ModalMarker.MUST,
        "lagrum": "27 kap. 2 § SFB",
        "nyckelord": ["25 procent", "50 procent", "75 procent", "100 procent",
                      "hel", "halv", "tre fjärdedelar", "en fjärdedel"],
    },
    {
        "text": "Läkarintyg styrker nedsättningen",
        "modal": ModalMarker.MUST,
        "lagrum": "27 kap. 25 § SFB",
        "nyckelord": ["läkarintyg", "intyg", "läkare", "specialist",
                      "behandlande", "utfärdat"],
    },
]

# Rekvisit för LVU (tvångsvård barn)
_FALLBACK_REKVISIT_LVU = [
    {
        "text": "Risk för skada på barnets hälsa eller utveckling",
        "modal": ModalMarker.MUST,
        "lagrum": "LVU 2 § (SFS 1990:52)",
        "nyckelord": ["risk", "skada", "hälsa", "utveckling", "barn",
                      "fara", "utsatt", "misshandel", "försummelse"],
    },
    {
        "text": "Brister i hemförhållandena eller barnets eget beteende",
        "modal": ModalMarker.MUST,
        "lagrum": "LVU 2-3 §§",
        "nyckelord": ["hemförhållanden", "beteende", "missbruk", "kriminalitet",
                      "brister", "föräldrar", "vårdnadshavare"],
    },
    {
        "text": "Barnets bästa avgörande",
        "modal": ModalMarker.MUST,
        "lagrum": "LVU 1 § + SoL 1 kap. 2 §",
        "nyckelord": ["barnets bästa", "barnets behov", "barnets vilja",
                      "barnets åsikt"],
    },
]

# Rekvisit för olovligt förfogande av fordon (generell)
_FALLBACK_REKVISIT_FORDON = [
    {
        "text": "Fordonet identifierat och beslagtaget",
        "modal": ModalMarker.MUST,
        "lagrum": "RB 27:1",
        "nyckelord": ["fordon", "bil", "beslag", "beslagtaget", "omhändertaget",
                      "registreringsnummer", "regnr"],
    },
]

# Fallback-mappning — används bara om config/rekvisit_definitioner.yaml
# saknas eller inte kan läsas.
_FALLBACK_REKVISIT_PER_MÅLTYP = {
    "olovligt_förfogande": _FALLBACK_REKVISIT_OLOVLIGT_FÖRFOGANDE,
    "sjukpenning": _FALLBACK_REKVISIT_SJUKPENNING,
    "lvu": _FALLBACK_REKVISIT_LVU,
    "fordon": _FALLBACK_REKVISIT_FORDON,
}
_FALLBACK_RUBRICERINGSFRASER: Dict[str, List[str]] = {
    "olovligt_förfogande": ["olovligt förfogande", "brb 10 kap. 4", "brb 10:4"],
    "sjukpenning": ["sjukpenning"],
    "lvu": ["lvu", "tvångsvård"],
    "sexuellt_ofredande": ["sexuellt ofredande"],
    "våldtäkt_mot_barn": ["våldtäkt mot barn"],
}
_FALLBACK_LAGRUM_MÖNSTER: Dict[str, List[str]] = {}
_FALLBACK_MÅLTYP_STÖDORD: Dict[str, List[str]] = {
    "olovligt_förfogande": ["leasingavtal", "leasing", "återlämna", "uppsägning", "uppsagt"],
    "sjukpenning": ["arbetsförmåga", "sfb", "försäkringskassan", "rehabilitering", "sgi", "sjukskrivning", "läkarintyg"],
    "lvu": ["omhändertagande", "socialnämnd", "barnets bästa", "placering"],
    "fordon": ["fordonsbrott", "registreringsnummer"],
}


# Skälet till att config/rekvisit_definitioner.yaml inte kunde läsas, eller
# None. Utan det gick ett trasigt config inte att skilja från ett som lästs:
# analysen föll tyst tillbaka till de inbyggda listorna.
_PROFIL_LADDNINGSFEL: Optional[str] = None


def profil_laddningsfel() -> Optional[str]:
    """Felet som hindrade måltypsprofilerna från att läsas, eller None."""
    return _PROFIL_LADDNINGSFEL


def _sätt_laddningsfel(skäl: str) -> None:
    global _PROFIL_LADDNINGSFEL
    _PROFIL_LADDNINGSFEL = skäl


def _ladda_måltypsprofiler() -> Tuple[Dict, Dict[str, List[str]], Dict[str, List[str]], Dict[str, List[str]]]:
    """Läser config/rekvisit_definitioner.yaml — enda källan för
    måltypsidentifiering och rekvisit (se filens egen docstring). Faller
    tillbaka till de inbyggda listorna ovan om config saknas, inte kan
    tolkas, eller inte innehåller någon 'måltyper'-nyckel."""
    try:
        import config_loader
        data = config_loader.ladda("rekvisit_definitioner") or {}
        måltyper = data.get("måltyper") if isinstance(data, dict) else None
    except Exception as e:
        global _PROFIL_LADDNINGSFEL
        _PROFIL_LADDNINGSFEL = f"{type(e).__name__}: {e}"
        print(f"[REQUISITE_CLAIM_MAPPER] rekvisit_definitioner kunde inte läsas — "
              f"inga rekvisit byggs (fail-closed): {_PROFIL_LADDNINGSFEL}", file=sys.stderr)
        måltyper = None

    if not isinstance(måltyper, dict) or not måltyper:
        # Steg 15: fail-closed - inga inbyggda exempelrekvisit.
        if _PROFIL_LADDNINGSFEL is None:
            _sätt_laddningsfel("config/rekvisit_definitioner.yaml saknar "
                               "'måltyper' eller är tom")
        print(f"[REQUISITE_CLAIM_MAPPER] inga måltypsprofiler laddade - inga "
              f"rekvisit byggs: {_PROFIL_LADDNINGSFEL}", file=sys.stderr)
        return {}, {}, {}, {}

    rekvisit_per_måltyp: Dict[str, List[Dict]] = {}
    rubriceringsfraser: Dict[str, List[str]] = {}
    lagrum_mönster: Dict[str, List[str]] = {}
    stödord: Dict[str, List[str]] = {}

    for namn, profil in måltyper.items():
        if not isinstance(profil, dict):
            continue
        rubriceringsfraser[namn] = [str(x) for x in (profil.get("rubricering_mönster") or [])]
        lagrum_mönster[namn] = [str(x) for x in (profil.get("lagrum_mönster") or [])]
        stödord[namn] = [str(x) for x in (profil.get("nyckelord") or [])]
        rekvisit_lista = []
        for r in (profil.get("rekvisit") or []):
            if not isinstance(r, dict) or not r.get("text"):
                continue
            modal_ogiltig = None
            try:
                modal = ModalMarker[str(r.get("modal", "MUST")).upper()]
            except KeyError:
                # Okänd modal tolkas strängast (MUST) — men att configens
                # värde inte gick att tolka ska synas, inte försvinna.
                modal_ogiltig = str(r.get("modal"))
                modal = ModalMarker.MUST
            rekvisit_lista.append({
                "text": r["text"],
                "modal": modal,
                "modal_ogiltig": modal_ogiltig,
                "lagrum": r.get("lagrum", ""),
                "nyckelord": [str(x) for x in (r.get("nyckelord") or [])],
            })
        if rekvisit_lista:
            rekvisit_per_måltyp[namn] = rekvisit_lista

    return rekvisit_per_måltyp, rubriceringsfraser, lagrum_mönster, stödord


(
    REKVISIT_PER_MÅLTYP, _RUBRICERINGSFRASER, _LAGRUM_MÖNSTER, _MÅLTYP_STÖDORD,
) = _ladda_måltypsprofiler()


# ============================================================
# MÅLTYPSKLASSIFICERING — ordgränsmatchning, inget enstaka svagt
# blankettord får klassa hela ärendet (se test_requisite_classification_and_graph.py)
# ============================================================

def _ordgräns_finns(ord: str, text: str) -> bool:
    """True om `ord` förekommer i `text` som ett HELT ord — inte som
    substräng i ett längre ord ('bil' i 'bilden'/'bilen'/'mobil')."""
    return re.search(r"\b" + re.escape(ord) + r"\b", text, re.IGNORECASE) is not None


def _fras_finns(fras: str, text: str) -> bool:
    """Flerordsfraser matchas ordgränsat i sin helhet (bygger på samma
    princip som _ordgräns_finns, bara med mellanslag i mönstret)."""
    mönster = r"\b" + re.escape(fras).replace(r"\ ", r"\s+") + r"\b"
    return re.search(mönster, text, re.IGNORECASE) is not None


@dataclass
class MåltypBedömning:
    """Resultatet av identify_måltyp_detailed() — måltyp plus VARFÖR,
    så en tyst feltolkning (ett enstaka blankettord, en jämn kandidatstrid)
    går att skilja från en verkligt underbyggd klassificering."""
    måltyp: str
    signal: str
    confidence: str
    motivering: str


# ============================================================
# DATAKLASSER
# ============================================================

@dataclass
class RequisiteMapping:
    """Koppling mellan ett rekvisit och relevanta claims."""
    rekvisit_text: str
    modal: ModalMarker
    lagrum: str
    status: RequisiteStatus
    kopplade_claims: List[str] = field(default_factory=list)  # claim_id-lista
    starkaste_claim: Optional[str] = None
    starkaste_claim_text: Optional[str] = None
    confidence: str = "LÅG"
    motivering: str = ""
    uteslutna_trunkerade: List[str] = field(default_factory=list)

    def to_requisite_entry(self) -> RequisiteEntry:
        """Konverterar till RequisiteEntry för case_state."""
        return RequisiteEntry(
            requisite_text=self.rekvisit_text,
            modal=self.modal,
            claim_id=self.starkaste_claim or "NOT_VERIFIABLE",
            source_ref=self.lagrum,
            status=self.status,
            uteslutna_trunkerade=list(self.uteslutna_trunkerade),
        )


# ============================================================
# REQUISITE CLAIM MAPPER
# ============================================================

class RequisiteClaimMapper:
    """
    Kopplar automatiskt klassificerade claims till rekvisit.
    
    Flöde:
    1. Identifiera måltyp från claims och court_type
    2. Ladda relevanta rekvisit för måltypen
    3. För varje rekvisit: hitta relevanta claims via nyckelordsmatchning
    4. Sätt RequisiteStatus baserat på matchkvalitet
    5. Trigga HS11 om MUST-rekvisit saknar claims
    
    ABSOLUT REGEL: Ingen rättslig slutsats dras automatiskt.
    Mappningen är ett underlag för mänsklig juridisk bedömning.
    """

    # Trösklar för matchkvalitet
    STRONG_MATCH_THRESHOLD = 3   # ≥3 nyckelord → TVISTIGT eller REKVISIT_UPPFYLLT
    WEAK_MATCH_THRESHOLD = 1     # ≥1 nyckelord → TVISTIGT
    NO_MATCH = 0                 # 0 nyckelord → BEVISNING_SAKNAS

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.log: List[str] = []

    def map(
        self,
        case_state: CaseState,
        klassificerade: Optional[List[KlassificeratSegment]] = None,
    ) -> List[RequisiteMapping]:
        """
        Huvudmetod: identifierar måltyp, laddar rekvisit, kopplar claims.
        
        Args:
            case_state: CaseState med claims
            klassificerade: Klassificerade segment (valfritt, förbättrar mappning)
        
        Returns:
            Lista av RequisiteMapping med status per rekvisit
        """
        if not case_state.claims:
            self.log.append(
                "[MAPPER] VARNING: Inga claims – kör L2 + ClaimClassifier först"
            )
            return []

        # Identifiera måltyp
        bedömning = self.identify_måltyp_detailed(case_state)
        måltyp = bedömning.måltyp
        self.log.append(
            f"[MAPPER] Identifierad måltyp: {måltyp} "
            f"(signal={bedömning.signal}, confidence={bedömning.confidence})"
        )

        # Ladda rekvisit
        rekvisit_defs = self._load_rekvisit(måltyp, case_state)
        if not rekvisit_defs:
            self.log.append(
                f"[MAPPER] Inga rekvisitdefinitioner för måltyp: {måltyp}"
            )
            return []

        self.log.append(
            f"[MAPPER] Laddar {len(rekvisit_defs)} rekvisit för {måltyp}"
        )

        # Koppla claims till rekvisit
        mappningar: List[RequisiteMapping] = []
        for rek_def in rekvisit_defs:
            mapping = self._map_rekvisit_to_claims(
                rek_def, case_state.claims, klassificerade
            )
            mappningar.append(mapping)

        # Uppdatera case_state.requisite_matrix
        case_state.requisite_matrix = [m.to_requisite_entry() for m in mappningar]

        # Kontrollera HS11
        self._check_hs11(mappningar, case_state)

        # Statistik
        uppfyllda = sum(
            1 for m in mappningar
            if m.status in (
                RequisiteStatus.REKVISIT_UPPFYLLT,
                RequisiteStatus.OBESTRITT
            )
        )
        saknas = sum(
            1 for m in mappningar
            if m.status == RequisiteStatus.BEVISNING_SAKNAS
        )
        tvistiga = sum(
            1 for m in mappningar
            if m.status == RequisiteStatus.TVISTIGT
        )

        self.log.append(
            f"[MAPPER] Klar: {len(mappningar)} rekvisit. "
            f"Uppfyllda: {uppfyllda}, Tvistiga: {tvistiga}, "
            f"Bevisning saknas: {saknas}"
        )

        # Spara i metadata
        case_state.metadata["requisite_mappings"] = [
            {
                "rekvisit": m.rekvisit_text,
                "modal": m.modal.value,
                "status": m.status.value,
                "kopplade_claims": m.kopplade_claims,
                "confidence": m.confidence,
            }
            for m in mappningar
        ]

        return mappningar

    def identify_måltyp_detailed(self, case_state: CaseState) -> MåltypBedömning:
        """
        Identifierar måltyp med en spårbar motivering — inte bara ett
        namn. Ett enstaka svagt blankettord ('beslag' på ett försättsblad)
        får aldrig ensamt avgöra måltypen, och två jämnstarka kandidater
        ska ge "okänd" hellre än en tyst gissning.
        """
        claims_text = [c.content.lower() for c in case_state.claims]
        if not claims_text:
            return MåltypBedömning(
                "okänd", signal="INGET_UNDERLAG", confidence="LÅG",
                motivering="Inga claims att klassificera.",
            )

        poäng: Dict[str, int] = {}
        rubricering_träffar: Dict[str, int] = {}

        for text in claims_text:
            for kandidat, fraser in _RUBRICERINGSFRASER.items():
                if any(_fras_finns(f, text) for f in fraser):
                    rubricering_träffar[kandidat] = rubricering_träffar.get(kandidat, 0) + 1
                    poäng[kandidat] = poäng.get(kandidat, 0) + 3
            for kandidat, mönster in _LAGRUM_MÖNSTER.items():
                if any(_fras_finns(m, text) for m in mönster):
                    poäng[kandidat] = poäng.get(kandidat, 0) + 2
            for kandidat, ord in _MÅLTYP_STÖDORD.items():
                for w in ord:
                    if _fras_finns(w, text):
                        poäng[kandidat] = poäng.get(kandidat, 0) + 1

        if not poäng:
            return MåltypBedömning(
                "okänd", signal="INGEN_TRÄFF", confidence="LÅG",
                motivering="Inget rubricerings- eller nyckelord matchade underlaget.",
            )

        rankade = sorted(poäng.items(), key=lambda kv: -kv[1])
        bäst_måltyp, bäst_poäng = rankade[0]
        tvåa_poäng = rankade[1][1] if len(rankade) > 1 else 0

        # Rubricering som återkommer i flera claims är den starkaste signalen.
        if rubricering_träffar.get(bäst_måltyp, 0) >= 2 and (bäst_poäng - tvåa_poäng) >= 3:
            return MåltypBedömning(
                bäst_måltyp, signal="RUBRICERING", confidence="HÖG",
                motivering=(
                    f"Rubriceringsfras för '{bäst_måltyp}' återkommer i "
                    f"{rubricering_träffar[bäst_måltyp]} claims."
                ),
            )

        # Jämnstarka kandidater — ingen tyst tilldelning till den ena.
        if tvåa_poäng > 0 and (bäst_poäng - tvåa_poäng) <= 1:
            return MåltypBedömning(
                "okänd", signal="TVETYDIGT", confidence="LÅG",
                motivering=(
                    f"Liten marginal mellan de starkaste kandidaterna "
                    f"({bäst_poäng} mot {tvåa_poäng} poäng) — klassificeras inte."
                ),
            )

        # Ett enda svagt stödord räcker aldrig ensamt.
        if bäst_poäng < 2:
            return MåltypBedömning(
                "okänd", signal="FÖR_SVAGT", confidence="LÅG",
                motivering="Endast ett enstaka, svagt signalord — räcker inte för klassificering.",
            )

        return MåltypBedömning(
            bäst_måltyp, signal="NYCKELORD",
            confidence="HÖG" if bäst_poäng >= 5 else "MEDEL",
            motivering=f"{bäst_poäng} poäng nyckelords-/rubriceringsmatchning för '{bäst_måltyp}'.",
        )

    def _load_rekvisit(
        self,
        måltyp: str,
        case_state: CaseState,
    ) -> List[Dict]:
        """Laddar rekvisitdefinitioner för måltypen."""
        # Kombinera relevanta rekvisit
        rekvisit = list(REKVISIT_PER_MÅLTYP.get(måltyp, []))

        # Lägg till fordon-rekvisit för brottmål med fordon
        if måltyp == "olovligt_förfogande":
            rekvisit.extend(REKVISIT_PER_MÅLTYP.get("fordon", []))

        # Lägg till rekvisit från legal_sources om tillgängliga
        for source in case_state.legal_sources:
            if source.cited_law and source.holding:
                # Skapa ett dynamiskt rekvisit från rättskällan
                rekvisit.append({
                    "text": f"Rekvisit enligt {source.cited_law}: {source.holding[:100]}",
                    "modal": ModalMarker.MUST,
                    "lagrum": source.cited_law,
                    "nyckelord": source.cited_law.lower().split()[:5],
                })

        return rekvisit

    def _map_rekvisit_to_claims(
        self,
        rek_def: Dict,
        claims: List[ClaimId],
        klassificerade: Optional[List[KlassificeratSegment]],
    ) -> RequisiteMapping:
        """
        Kopplar ett rekvisit till relevanta claims.
        
        Matchningslogik:
        1. Nyckelordsmatchning mot claim-text
        2. Juridisk klass-matchning (om klassificerade finns)
        3. Beräkna RequisiteStatus baserat på matchkvalitet
        """
        nyckelord = rek_def.get("nyckelord", [])
        modal = rek_def.get("modal", ModalMarker.MUST)
        lagrum = rek_def.get("lagrum", "")
        rekvisit_text = rek_def.get("text", "")

        kopplade: List[Tuple[int, str, str]] = []  # (score, claim_id, text)

        # Steg 13 (B-011): ett trunkerat claim UTAN verifierad datum-/
        # versionsmetadata kan inte bära rekvisitet - bevisningen redovisas
        # som saknad, inte som tyst kapad text. mtime/standardversion räknas
        # inte som metadata (ClaimId.metadata_verifierad).
        uteslutna_trunkerade: List[str] = []
        for claim in claims:
            score = self._score_claim_for_rekvisit(
                claim, nyckelord, rek_def, klassificerade
            )
            if score > 0:
                if getattr(claim, "text_trunkerad", False) and not (
                        callable(getattr(claim, "metadata_verifierad", None))
                        and claim.metadata_verifierad()):
                    uteslutna_trunkerade.append(claim.claim_id)
                    continue
                kopplade.append((score, claim.claim_id, claim.content))

        # Sortera efter score
        kopplade.sort(key=lambda x: x[0], reverse=True)

        # Bestäm status
        if not kopplade and uteslutna_trunkerade:
            status = RequisiteStatus.BEVISNING_SAKNAS
            confidence = "HÖG"
            motivering = (
                f"Bevisning saknas: matchande claims {uteslutna_trunkerade} är "
                f"trunkerade och saknar verifierad datum-/versionsmetadata (B-011)"
            )
            starkaste = None
            starkaste_text = None
        elif not kopplade:
            status = RequisiteStatus.BEVISNING_SAKNAS
            confidence = "HÖG"  # Säkert att bevisning saknas
            motivering = "Inga claims matchar rekvisitets nyckelord"
            starkaste = None
            starkaste_text = None
        elif kopplade[0][0] >= self.STRONG_MATCH_THRESHOLD:
            # Stark matchning – men vi kan inte automatiskt sätta UPPFYLLT
            # Det kräver mänsklig juridisk bedömning
            # Vi sätter TVISTIGT som säkert mellanläge
            status = RequisiteStatus.TVISTIGT
            confidence = "MEDEL"
            motivering = (
                f"Stark matchning ({kopplade[0][0]} nyckelord) – "
                f"juridisk bedömning krävs för REKVISIT_UPPFYLLT"
            )
            starkaste = kopplade[0][1]
            starkaste_text = kopplade[0][2][:150]
        else:
            # Svag matchning
            status = RequisiteStatus.TVISTIGT
            confidence = "LÅG"
            motivering = (
                f"Svag matchning ({kopplade[0][0]} nyckelord) – "
                f"otillräckligt underlag"
            )
            starkaste = kopplade[0][1]
            starkaste_text = kopplade[0][2][:150]

        mapping = RequisiteMapping(
            rekvisit_text=rekvisit_text,
            modal=modal,
            lagrum=lagrum,
            status=status,
            kopplade_claims=[c[1] for c in kopplade[:5]],
            starkaste_claim=starkaste,
            starkaste_claim_text=starkaste_text,
            confidence=confidence,
            motivering=motivering,
        )
        if uteslutna_trunkerade:
            mapping.uteslutna_trunkerade = list(uteslutna_trunkerade)
            mapping.motivering = (motivering if not kopplade else
                                  f"{motivering}; uteslutna trunkerade claims utan "
                                  f"verifierad metadata: {uteslutna_trunkerade}")

        if self.verbose:
            self.log.append(
                f"[MAPPER] Rekvisit: {rekvisit_text[:50]} → "
                f"{status.value} ({len(kopplade)} claims matchade)"
            )

        return mapping

    def _score_claim_for_rekvisit(
        self,
        claim: ClaimId,
        nyckelord: List[str],
        rek_def: Dict,
        klassificerade: Optional[List[KlassificeratSegment]],
    ) -> int:
        """
        Beräknar relevanspoäng för ett claim mot ett rekvisit.
        
        Poängsystem:
        - 1 poäng per matchat nyckelord
        - +2 bonus om juridisk klass matchar rekvisittypen
        - +1 bonus om claim är EVIDENCED_FACT eller VERIFIED
        """
        text_lower = claim.content.lower()
        score = 0

        # Nyckelordsmatchning
        for kw in nyckelord:
            if kw.lower() in text_lower:
                score += 1

        # Juridisk klass-bonus
        if klassificerade:
            for ks in klassificerade:
                if ks.segment.file_id == claim.source_id:
                    klass_bonus = self._klass_bonus(
                        ks.juridisk_klass, rek_def
                    )
                    score += klass_bonus
                    break

        # Availability-bonus
        if claim.availability == "VERIFIED":
            score += 1

        return score

    def _klass_bonus(
        self,
        klass: JuridiskKlass,
        rek_def: Dict,
    ) -> int:
        """Bonus baserat på juridisk klass vs rekvisittyp."""
        rekvisit_text = rek_def.get("text", "").lower()

        # Bevisning-rekvisit → bevisning-klass ger bonus
        if any(kw in rekvisit_text for kw in ["styrkt", "bevisat", "intyg"]):
            if klass in (JuridiskKlass.BEVISNING, JuridiskKlass.TEKNISKT_FAKTUM):
                return 2

        # Uppsåt-rekvisit → förhörsutsaga ger bonus
        if "uppsåt" in rekvisit_text:
            if klass in (JuridiskKlass.FÖRHÖRSUTSAGA, JuridiskKlass.VITTNESUTSAGA):
                return 2

        # Faktum-rekvisit → rättsfaktum ger bonus
        if any(kw in rekvisit_text for kw in ["faktum", "omständighet", "händelse"]):
            if klass in (JuridiskKlass.RÄTTSFAKTUM, JuridiskKlass.SAKOMSTÄNDIGHET):
                return 1

        return 0

    def _check_hs11(
        self,
        mappningar: List[RequisiteMapping],
        case_state: CaseState,
    ) -> None:
        """
        Kontrollerar om HS11 ska triggas.
        HS11: MUST-rekvisit med BEVISNING_SAKNAS → subsumtionskedja spärras.
        """
        must_saknas = [
            m for m in mappningar
            if m.modal == ModalMarker.MUST
            and m.status == RequisiteStatus.BEVISNING_SAKNAS
        ]

        if must_saknas:
            if HardStopCode.HS11 not in case_state.hard_stop_codes:
                case_state.hard_stop_codes.append(HardStopCode.HS11)
            self.log.append(
                f"[MAPPER] HS11 TRIGGAS: {len(must_saknas)} MUST-rekvisit "
                f"saknar bevisning: "
                + ", ".join(m.rekvisit_text[:40] for m in must_saknas)
            )
            for m in must_saknas:
                self.log.append(
                    f"[MAPPER] MATERIELLT UNDERLAG SAKNAS FÖR REKVISIT: "
                    f"{m.rekvisit_text} – RÄTTSLIG SLUTSATS KAN EJ DRAS"
                )

    def generate_requisite_report(
        self,
        mappningar: List[RequisiteMapping],
    ) -> str:
        """Genererar rekvisitrapport i lagerformat (FIX-M)."""
        lines = [
            "## LAGER 8 – REKVISITMATRIS + LEGAL_REQUISITE_GATE",
            "",
        ]

        for m in mappningar:
            status_symbol = {
                RequisiteStatus.REKVISIT_UPPFYLLT: "✓",
                RequisiteStatus.OBESTRITT: "○",
                RequisiteStatus.TVISTIGT: "~",
                RequisiteStatus.BEVISNING_SAKNAS: "✗",
            }.get(m.status, "?")

            lines.append(
                f"{status_symbol} [{m.modal.value}] {m.rekvisit_text}"
            )
            lines.append(f"   Lagrum: {m.lagrum}")
            lines.append(f"   Status: {m.status.value} ({m.confidence})")
            lines.append(f"   Motivering: {m.motivering}")
            if m.kopplade_claims:
                lines.append(
                    f"   Kopplade claims: {', '.join(m.kopplade_claims[:3])}"
                )
            if m.starkaste_claim_text:
                lines.append(
                    f"   Starkaste match: \"{m.starkaste_claim_text[:100]}...\""
                )
            lines.append("")

        # Gate-resultat
        must_saknas = [
            m for m in mappningar
            if m.modal == ModalMarker.MUST
            and m.status == RequisiteStatus.BEVISNING_SAKNAS
        ]

        if must_saknas:
            lines.append(
                f"GATE_RESULTAT: SPÄRRAD – "
                f"{len(must_saknas)} MUST-rekvisit saknar bevisning"
            )
            lines.append("HS11: TRIGGAS")
            for m in must_saknas:
                lines.append(
                    f"  MATERIELLT UNDERLAG SAKNAS FÖR REKVISIT: "
                    f"{m.rekvisit_text} – RÄTTSLIG SLUTSATS KAN EJ DRAS"
                )
        else:
            lines.append("GATE_RESULTAT: PASSERAD (preliminärt)")
            lines.append(
                "OBS: PASSERAD kräver mänsklig juridisk verifiering – "
                "automatisk mappning är inte tillräcklig för REKVISIT_UPPFYLLT"
            )

        lines.append("")
        lines.append("[L8 | REKVISITMATRIS | LOCKED]")
        return "\n".join(lines)