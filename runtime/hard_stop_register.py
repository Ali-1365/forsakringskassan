from __future__ import annotations
# SFCAE-BINDNING: hard_stop_register
# Roll: Hard-stop-register
# Producerar aldrig domslut. INDIKATIV_ENDAST.
_BUNDEN_TILL_SFCAE = True
_ROLL = "Hard-stop-register"

# -*- coding: utf-8 -*-
"""
HARD-STOP-REGISTER — verifierat 2026-09-22

Varje HARD STOP i systemet, dess exakta utlösningsvillkor och dess räckvidd.

Registret finns för att hard-stop-arkitekturen ska gå att granska utan att läsa
hela motorn, och för att fel i den ska gå att upptäcka maskinellt.

RÄCKVIDD
--------
    HELA_ÄRENDET  Körningen avbryts. Ingen vidare analys sker.
    KEDJAN        Endast den berörda analyskedjan spärras. Övriga lager körs
                  vidare och resultatet redovisas som partiellt.

PRINCIP
-------
En oläsbar eller ej analyserad handling påverkar ENDAST den handlingen och
analysens täckningsstatus. Ett fel i en enskild modul får inte stoppa hela
SFCAE utan verifierat skäl. Endast verkligt blockerande systemfel får avbryta
körningen.
"""

from typing import Dict, List, Optional

SIGNATUR = "2026-09-22"

HELA_ÄRENDET = "HELA_ÄRENDET"
KEDJAN = "KEDJAN"


class HardStopPost:
    """En post i registret."""

    def __init__(
        self,
        kod: str,
        beskrivning: str,
        villkor: str,
        räckvidd: str,
        sätts_i: str,
        anmärkning: str = "",
    ) -> None:
        self.kod = kod
        self.beskrivning = beskrivning
        self.villkor = villkor
        self.räckvidd = räckvidd
        self.sätts_i = sätts_i
        self.anmärkning = anmärkning

    def to_dict(self) -> Dict[str, str]:
        return {
            "kod": self.kod,
            "beskrivning": self.beskrivning,
            "villkor": self.villkor,
            "räckvidd": self.räckvidd,
            "sätts_i": self.sätts_i,
            "anmärkning": self.anmärkning,
        }


# ── Koder som sätts DIREKT av ett villkor i koden ───────────────────────────

REGISTER: List[HardStopPost] = [
    HardStopPost(
        "HS01A", "Central dom saknas (AUDIT)",
        "Tillåts endast i JUDGMENT_AUDIT. Frånvaro av dom utlöser ALDRIG "
        "HS01A i JUDGMENT_CONSTRUCTION (RT-I).",
        KEDJAN, "ModeRouter.route",
        "Sätts inte i nuvarande kodväg; ModeRouter returnerar None eller HS01C.",
    ),
    HardStopPost(
        "HS01C", "Otillräckligt underlag",
        "Akten saknar filer helt (inga poster efter ingestion), eller — när "
        "anroparen lämnat processläget UNDEFINED — varken dom/beslut eller "
        "processmaterial kan identifieras.",
        HELA_ÄRENDET, "IngestionAgent.ingest (L0) samt ModeRouter.route",
        "Sätter hard_stop_active och slutstatus I, och avbryter pipelinen. "
        "Villkoret låg tidigare ENBART i ModeRouter.route, som bara körs när "
        "process_mode är UNDEFINED. CLI och consolidated_engine anger alltid "
        "ett läge, varför koden aldrig kunde sättas i drift: en tom "
        "ärendemapp kördes igenom hela pipelinen och avslutades med "
        "slutstatus G. Villkoret ligger nu i ingestionen, oberoende av vem "
        "som valt körningsläge. Nyckeltermer i ModeRouter matchas "
        "sammansättningsmedvetet så att 'dom' inte träffar i 'sjukdom'. "
        "Utlöses inte när en ENSKILD handling är oläsbar.",
    ),
    HardStopPost(
        "HS03", "Autenticitet ej verifierbar",
        "Fler än 60 % av aktens filer saknar SHA-256.",
        HELA_ÄRENDET, "RecursiveVaultIngestion.ingest",
        "Enda kod som avbryter körningen direkt (return False). Integritets"
        "brist i majoriteten av materialet gör vidare analys meningslös.",
    ),
    HardStopPost(
        "HS04", "Central bevisning saknas",
        "Akten innehåller filer men SAMTLIGA gav noll extraherad text.",
        KEDJAN, "run_pipeline (L2)",
        "Kräver att INGEN handling gav text. En enskild oläsbar handling "
        "utlöser inte HS04 — den redovisas i extraktionstäckningen.",
    ),
    HardStopPost(
        "HS07", "Prejudikatets räckvidd ej fastställbar",
        "Prejudikat utan holding-verifiering H1/H2/H3 (RT-BP/P12).",
        KEDJAN, "LegalSourceSearchIntegration (L7)",
        "Koden väljs på systemgenererad blocking_reason — ingen ärendedata "
        "ingår, alltså inte injicerbar.",
    ),
    HardStopPost(
        "HS09", "Förbjuden inferens",
        "Rättslig slutsats utan verifierad subsumtionskedja (P07), claim utan "
        "källhänvisning, eller icke verifierbar processposition (RT-L).",
        KEDJAN, "OutputRegler / ProcessPositionRegler via AuditController",
        "Data som interpoleras i violation-texten redigeras så att "
        "textinnehåll inte kan sätta koden. En TOM rekvisitmatris utlöser "
        "INTE längre HS09: avsaknad av underlag är inte en otillåten "
        "slutsats. Tidigare gav varje ärende utan fastställd måltyp både "
        "HS09 och HS11 för samma sakförhållande, och en kod som brinner i "
        "varje körning särskiljer ingenting. Tom matris är HS11.",
    ),
    HardStopPost(
        "HS09B", "Låg källtäckning under tröskelvärde",
        "source_coverage (andel claims med källa/lagrum/source_id, eller "
        "max mot antal legal_sources/claims) < min_source_coverage. Tröskeln "
        "läses ur config/system_policy.yaml (nyckel min_source_coverage, "
        "direkt eller nästlad) via config_loader.system_policy(); default "
        "0.85 när nyckeln saknas (config_loader.py och "
        "dynamic_pipeline._MIN_SOURCE_COVERAGE).",
        KEDJAN, "dynamic_pipeline._kolla_min_source_coverage",
        "Underlagsflagga, inte kedjeavbrott: underlag_saknas=True och "
        "zero_fel nedgraderas till DELVIS. Skild från HS09 (förbjuden "
        "inferens), som tidigare felaktigt användes för detta villkor.",
    ),
    HardStopPost(
        "HS10", "Cirkulär påverkan",
        "Cirkulära kanter i relationsgrafen, eller rättskälla klassad som "
        "EJ_RÄTTSKÄLLA.",
        KEDJAN, "CircularReasoningBlocker.block / L7",
    ),
    HardStopPost(
        "HS11", "Subsumtionskedja saknar rättsfaktum",
        "Ett obligatoriskt (MUST) funktionellt krav saknar verifierad "
        "bevisning (status BEVISNING_SAKNAS). Vilket krav som saknas anges ur "
        "rekvisitmatrisen; kan det inte anges redovisas SAKNAS.",
        KEDJAN, "SubsumptionGatekeeper / RequisiteClaimMapper / DomskälsmatrisAgent",
        "Grinden släpps aldrig utan prövat funktionellt krav.",
    ),
    HardStopPost(
        "HS15", "FORUM_CONFLICT",
        "Två domstolsslag är lika starkt representerade i akten efter att "
        "processuell vokabulär prövats som särskiljare.",
        KEDJAN, "kör_processklassificering (L1)",
        "Utlöses INTE när ingen domstol nämns — då sätts court_type UNKNOWN "
        "utan hard stop, eftersom analysen kan fortsätta.",
    ),
]

# Koder som endast kan sättas genom att AuditController läser dem ur en
# violation-sträng som producenten själv skrivit. Ingen av dem har i dag en
# egen producent, men mekanismen finns och koderna är därför inte döda.
ÖVRIGA_VIA_VIOLATION: Dict[str, str] = {
    "HS01B": "Central processhandling saknas",
    "HS02": "Domversion ej verifierbar",
    "HS05": "Ljud ej verifierbart",
    "HS06": "Lagversion ej fastställbar",
    "HS08": "Central källmotsägelse olöst",
    "HS12": "Negativ bevisstatus saknas",
    "HS13": "Ärendenummer ej verifierbart",
    "HS14": "Muntlig källa avviker från skriftlig",
    "HS16": "Källkontaminering",
    "HS17": "Vittnesutsaga bär ensamt MUST-rekvisit",
    "HS18": "Substantiell avvikelse med materiell betydelse",
    "HS19": "EXPECTED_NOT_FOUND för materiellt rekvisit",
    "HS20": "Processläge ej fastställt / MODE UNDEFINED",
}


def hämta(kod: str) -> Optional[HardStopPost]:
    """Registerposten för en kod, eller None."""
    for post in REGISTER:
        if post.kod == kod:
            return post
    return None


def helstopp_koder() -> List[str]:
    """Koder som avbryter hela körningen."""
    return [p.kod for p in REGISTER if p.räckvidd == HELA_ÄRENDET]


def registrerade_koder() -> List[str]:
    """Samtliga koder registret känner till."""
    return [p.kod for p in REGISTER] + list(ÖVRIGA_VIA_VIOLATION)


def kontrollera_mot_enum(hard_stop_enum) -> Dict[str, List[str]]:
    """
    Jämför registret mot HardStopCode-enumet.

    Returnerar avvikelser i båda riktningarna, så att en ny kod i koden utan
    registerpost — eller en registerpost utan kod — går att upptäcka.
    """
    i_enum = {m.value for m in hard_stop_enum}
    i_register = set(registrerade_koder())
    return {
        "saknas_i_register": sorted(i_enum - i_register),
        "saknas_i_enum": sorted(i_register - i_enum),
    }


def rapport() -> str:
    """Läsbar redovisning av hela hard-stop-arkitekturen."""
    rader = [
        f"HARD-STOP-REGISTER — verifierat {SIGNATUR}",
        "=" * 72,
        "",
        f"Koder med eget villkor i koden: {len(REGISTER)}",
        f"Koder via violation-mekanismen: {len(ÖVRIGA_VIA_VIOLATION)}",
        f"Avbryter hela körningen: {', '.join(helstopp_koder())}",
        "",
    ]
    for p in REGISTER:
        rader.append(f"[{p.kod}] {p.beskrivning}")
        rader.append(f"    Räckvidd : {p.räckvidd}")
        rader.append(f"    Villkor  : {p.villkor}")
        rader.append(f"    Sätts i  : {p.sätts_i}")
        if p.anmärkning:
            rader.append(f"    Anm.     : {p.anmärkning}")
        rader.append("")
    rader.append("Koder utan egen producent (kan sättas via violation-text):")
    for kod, beskr in sorted(ÖVRIGA_VIA_VIOLATION.items()):
        rader.append(f"    {kod}: {beskr}")
    return "\n".join(rader)


if __name__ == "__main__":
    print(rapport())
