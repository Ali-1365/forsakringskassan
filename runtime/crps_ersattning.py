from __future__ import annotations
# SFCAE-BINDNING: crps_ersattning
# Roll: CRPS-ersättningsberäkning
# Alt B — anropas via requested=True från pipeline eller MCP.
_BUNDEN_TILL_SFCAE = True
_ROLL = "CRPS-ersättningsberäkning"

# -*- coding: utf-8 -*-
"""
CRPS-ersättningsberäkning enligt
references/skills_registry/fk-monsterkatalog-crps-patientskada/SKILL.md
DEL C. Formeln (invaliditetsersättning = grundbelopp × invaliditetsgrad,
retroaktiv förlust = månadsdifferens × månader, livränta = årlig
förlust × år) är objektiv aritmetik. Grundbeloppen per åldersgrupp läses
från config/trafikskadenamnden_grundbelopp.yaml, som är transkriberat ur
källan men INTE oberoende verifierat — se den filens egen källhänvisning.
Sveda-och-värk är alltid 0 här: den är enligt SKILL.md själv "ej
formelbaserad, bedöms från fall till fall enligt praxis" — motorn
fabricerar inget sådant belopp.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

from konfig_kalla import ladda_konfig, Konfig

ROOT = Path(__file__).resolve().parent.parent
_YAML = ROOT / "config" / "trafikskadenamnden_grundbelopp.yaml"
_BEVISKRAV_YAML = ROOT / "config" / "fk_beviskrav.yaml"

_KONFIG: Konfig = Konfig()
_BEVISKRAV_KONFIG: Konfig = Konfig()


def _load() -> Dict:
    global _KONFIG
    _KONFIG = ladda_konfig(_YAML)
    return _KONFIG.data or {}


def _grundbelopp_för_ålder(ålder: int, tabell: list) -> Optional[float]:
    for rad in tabell:
        min_å = rad.get("min_ålder", 0)
        max_å = rad.get("max_ålder")
        if ålder >= min_å and (max_å is None or ålder <= max_å):
            return rad.get("belopp")
    return None


def beräkna_crps_ersättning(
    invaliditetsgrad_procent: float,
    ålder_vid_skada: int,
    hypotetisk_månadsinkomst: float = 0.0,
    faktisk_månadsinkomst: float = 0.0,
    antal_månader_retroaktiv: int = 0,
    antal_år_livränta: int = 0,
) -> Dict[str, Any]:
    cfg = _load()
    tabell = cfg.get("grundbelopp_efter_ålder") or []
    if not tabell:
        return {
            "status": "EJ_KÖRBAR",
            "skäl": "config/trafikskadenamnden_grundbelopp.yaml kunde inte läsas eller är tom.",
            "källa": _KONFIG.källa,
        }

    grundbelopp = _grundbelopp_för_ålder(ålder_vid_skada, tabell)
    if grundbelopp is None:
        return {
            "status": "EJ_KÖRBAR",
            "skäl": f"Ingen åldersgrupp i tabellen täcker ålder {ålder_vid_skada}.",
        }

    invaliditetsersättning = grundbelopp * (invaliditetsgrad_procent / 100.0)
    månadsdifferens = hypotetisk_månadsinkomst - faktisk_månadsinkomst
    retroaktiv_förlust = månadsdifferens * antal_månader_retroaktiv
    årlig_förlust = månadsdifferens * 12
    livränta = årlig_förlust * antal_år_livränta
    sveda_och_värk = 0.0  # ej formelbaserad enligt källan — inte fabricerad här

    total = invaliditetsersättning + sveda_och_värk + retroaktiv_förlust + livränta

    return {
        "status": "GENOMFÖRD",
        "grundbelopp_efter_ålder": grundbelopp,
        "invaliditetsersättning": round(invaliditetsersättning, 2),
        "sveda_och_värk": sveda_och_värk,
        "retroaktiv_inkomstförlust": round(retroaktiv_förlust, 2),
        "livränta": round(livränta, 2),
        "total_ersättning": round(total, 2),
        "källa_grundbelopp": _KONFIG.data.get("källhänvisning") if _KONFIG.data else None,
        "not": (
            "INDIKATIV_ENDAST. Sveda och värk är INTE beräknad — SKILL.md "
            "anger uttryckligen att den bedöms från fall till fall enligt "
            "praxis, inte formelbaserat. Grundbeloppen är transkriberade "
            "ur en extern referenspack, inte oberoende verifierade mot "
            "Trafikskadenämndens aktuella tabell — verifiera innan "
            "beloppet används."
        ),
    }


def run_crps_ersattning_if_requested(requested: bool = False, **kwargs) -> Dict[str, Any]:
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "CRPS-ersättningsberäkning kräver requested=True."}
    if kwargs.get("invaliditetsgrad_procent") is None or kwargs.get("ålder_vid_skada") is None:
        return {"status": "EJ_KÖRBAR", "skäl": "invaliditetsgrad_procent och ålder_vid_skada krävs."}
    return beräkna_crps_ersättning(**kwargs)


# ============================================================
# DEL B — BEVISKRAVSKATALOG PER ÄRENDETYP
# ============================================================
#
# "Innan en fullständig analys eller processhandling produceras,
# kontrollera att nedanstående bevis finns. Om kategorier saknas —
# generera en kompletteringsbegäran enligt FL 23 § istället för att
# fortsätta analysen på bristfälligt underlag." (SKILL.md, DEL B)
#
# Skild från config/case_routing.yaml (avgör VILKEN ärendetyp ett
# ärende är, via nyckelord) — den här katalogen avgör, GIVET
# ärendetypen, om den obligatoriska bevisningen faktiskt finns.
# Kompletterande, inte en dubblett.

def _ladda_beviskrav() -> Dict:
    global _BEVISKRAV_KONFIG
    _BEVISKRAV_KONFIG = ladda_konfig(_BEVISKRAV_YAML)
    return _BEVISKRAV_KONFIG.data or {}


def klassificera_dokument(text: str) -> Optional[str]:
    """
    Klassificerar ett dokument utifrån SKILL.md:s egna
    dokumentigenkänningsmönster. Returnerar dokumenttypens namn, eller
    None om inget mönster matchar — gissar aldrig en typ.
    """
    cfg = _ladda_beviskrav()
    mönster = cfg.get("dokumentigenkänningsmönster") or {}
    text_norm = (text or "").lower()
    for typ, nyckelord in mönster.items():
        if any(str(n).lower() in text_norm for n in nyckelord):
            return typ
    return None


def pröva_beviskrav(ärendetyp: str, kategorier_med_bevis: List[str]) -> Dict[str, Any]:
    """
    Kontrollerar om samtliga obligatoriska bevis-KATEGORIER för given
    ärendetyp har minst ett stödjande dokument, enligt DEL B:s egen
    princip (kategorinivå, inte enskilda dokument). Avgör aldrig
    bevisvärdet — bara närvaron av en kategori.

    kategorier_med_bevis: kategorinamnen (t.ex. "Medicinsk", "Inkomst")
    som anroparen bekräftat har minst ett dokument för — t.ex. via
    klassificera_dokument() på varje tillgängligt dokument.
    """
    cfg = _ladda_beviskrav()
    ärendetyper = cfg.get("ärendetyper") or {}
    if ärendetyp not in ärendetyper:
        return {
            "status": "EJ_KÖRBAR",
            "skäl": f"Okänd ärendetyp '{ärendetyp}'. Giltiga: {sorted(ärendetyper.keys())}",
        }

    obligatoriska = ärendetyper[ärendetyp].get("kategorier") or {}
    funna = set(kategorier_med_bevis or [])
    saknade = [k for k in obligatoriska if k not in funna]

    if saknade:
        return {
            "status": "OTILLRÄCKLIGT_UNDERLAG",
            "ärendetyp": ärendetyp,
            "beslut": "Generera en kompletteringsbegäran enligt FL 23 §.",
            "saknade_kategorier": saknade,
            "exempel_per_saknad_kategori": {k: obligatoriska[k] for k in saknade},
            "not": (
                "INDIKATIV_ENDAST — kontrollerar bara närvaro av kategori, "
                "inte bevisvärde."
            ),
        }

    return {
        "status": "GODKÄND",
        "ärendetyp": ärendetyp,
        "beslut": "Samtliga obligatoriska bevis-kategorier har minst ett dokument.",
        "saknade_kategorier": [],
        "not": (
            "INDIKATIV_ENDAST — kontrollerar bara närvaro av kategori, "
            "inte bevisvärde eller om beviset räcker för bifall."
        ),
    }


def run_beviskrav_if_requested(
    ärendetyp: str = "",
    kategorier_med_bevis: Optional[List[str]] = None,
    requested: bool = False,
) -> Dict[str, Any]:
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "Beviskravskontroll kräver requested=True."}
    if not ärendetyp:
        return {"status": "EJ_KÖRBAR", "skäl": "ärendetyp krävs."}
    return pröva_beviskrav(ärendetyp, kategorier_med_bevis or [])
