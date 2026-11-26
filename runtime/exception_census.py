#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EXCEPTION-INVENTERING — varje svalt undantag, dess plats och dess verkan.

VARFÖR DEN FINNS
----------------
Ett `except: pass` är inte ett fel i sig. Det är ett fel när det döljer något
som borde ha gått att observera. Skillnaden går inte att se på mönstret — bara
på var det sitter och vad som händer när det slår till.

Verktyget listar varje ställe där ett undantag sväljs utan att lämna spår, med
fil, rad, omgivande funktion, fångad feltyp och vilken kedja funktionen tillhör.
Klassificeringen görs av människa eller av `KLASSIFICERING` nedan — den härleds
inte maskinellt, eftersom avsikten inte går att läsa ur koden.

    python scripts/exception_census.py            # sammanfattning
    python scripts/exception_census.py --alla     # varje förekomst
    python scripts/exception_census.py --oklassade
    python scripts/exception_census.py --analysvag # bara analyskedjan

KLASSER
-------
    SAFE                    Undantaget kan inte dölja något av teknisk vikt.
                            Typiskt ett valfritt värde med uttrycklig default.
    HANDLED                 Felet hanteras — alternativ väg tas, värdet ersätts
                            med en uttrycklig markör.
    REGISTERED_FAILURE      Felet registreras och blir observerbart i utfallet.
    INTENTIONAL_SUPPRESSION Medvetet undertryckt, med angivet skäl.
    OPTIONAL_DEPENDENCY     Modulen eller binären är valfri. Frånvaron ger ett
                            uttryckligt tillstånd, inte ett tyst bortfall.
    BUG                     Döljer något som borde observeras. Ska rättas.
    UNKNOWN                 Inte granskad.

Exitkod 1 om någon förekomst på analysvägen är oklassad eller klassad BUG.
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
SIGNATUR = "2026-09-22"

KATALOGER = ("runtime", "integrations", "scripts", "mcp")

# Ingångar som producerar ett resultat åt en användare.
#
#   consolidated_engine            CLI, GUI och MCP sfcae_consolidated_run
#   forensic_engine_v10_3_canonical  motorn
#   dynamic_pipeline               MCP sfcae_run_pipeline — grundare analys,
#                                  men dess utfall presenteras som ett resultat
#   server                         mcp/server.py: samtliga 51 verktyg
#   http_server                    mcp/http_server.py: HTTP-ytan
#
# Mängden omfattade tidigare bara de tre första. MCP-serverns verktygsyta
# saknades, trots att den är produktens huvudsakliga gränssnitt och trots att
# varje verktygssvar är utdata en anropare handlar på. Sju moduler — bland dem
# policy_monitor, bug_classifier, pretrial_objectives, ai_risk_scanner,
# ersattning_scanner, fmjam_adapter och rattstid_runner — räknades därför som
# "utanför analysvägen" fast de nås av ett verktygsanrop. Att en modul ligger
# utanför den beräknade mängden är inget bevis för att dess exception-handlers
# är riktiga; nåbarheten måste följa av anropsgrafen, och anropsgrafen måste
# utgå från samtliga ingångar.
ANALYS_INGÅNGAR = (
    "consolidated_engine",
    "forensic_engine_v10_3_canonical",
    "dynamic_pipeline",
    "server",
    "http_server",
)


def _modulindex() -> Dict[str, Path]:
    index: Dict[str, Path] = {}
    for katalog in KATALOGER:
        d = ROOT / katalog
        if d.is_dir():
            for f in d.rglob("*.py"):
                index.setdefault(f.stem, f)
    return index


def _importerade_namn(p: Path) -> set:
    try:
        träd = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return set()
    namn = set()
    for nod in ast.walk(träd):
        if isinstance(nod, ast.Import):
            for a in nod.names:
                namn.add(a.name.split(".")[-1])
        elif isinstance(nod, ast.ImportFrom) and nod.module:
            namn.add(nod.module.split(".")[-1])
        elif isinstance(nod, ast.Call):
            # importlib.import_module("modul") och spec_from_file_location
            for a in nod.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    v = a.value
                    if v.endswith(".py"):
                        namn.add(Path(v).stem)
                    elif v.isidentifier():
                        namn.add(v)
    return namn


def analysvägen() -> set:
    """
    Filer som kan påverka ett analysresultat, härlett ur importgrafen.

    Mängden var tidigare en handskriven lista. Den missade fem moduler som
    faktiskt nås från analyskedjan — deep_search_pipeline, config_loader,
    metadata_forensics_agent, knowledge_loader och kodsystem_scanner — och
    därmed 22 handlers som slapp undan kravet på klassificering.

    Att en fil ligger "utanför analysvägen" är ingen egenskap hos filen. Det
    är ett påstående om vad som kan nå den, och det ska härledas ur koden.
    """
    index = _modulindex()
    nådda = set(ANALYS_INGÅNGAR)
    kö = list(ANALYS_INGÅNGAR)
    while kö:
        p = index.get(kö.pop())
        if p is None:
            continue
        for ref in _importerade_namn(p):
            if ref in index and ref not in nådda:
                nådda.add(ref)
                kö.append(ref)
    return {
        index[m].relative_to(ROOT).as_posix()
        for m in nådda if m in index
    }


ANALYSVÄG = analysvägen()


class Förekomst:
    def __init__(self, fil: str, rad: int, funktion: str, feltyp: str,
                 kropp: str) -> None:
        self.fil = fil
        self.rad = rad
        self.funktion = funktion
        self.feltyp = feltyp
        self.kropp = kropp
        # Löpnummer när samma funktion har flera identiska handlers.
        # Sätts av inventera().
        self.ordning = 0

    @property
    def nyckel(self) -> str:
        """
        Stabil identitet för en förekomst.

        Radnummer dög inte: varje redigering ovanför en handler försköt
        nyckeln, varpå hela registret blev ogiltigt och förekomsterna föll
        tillbaka till UNKNOWN. Nyckeln bärs i stället av det som faktiskt
        beskriver handlern — fil, omslutande funktion, fångad typ och kroppens
        form — plus ett löpnummer när samma funktion har flera identiska.
        """
        return f"{self.fil}::{self.funktion}::{self.feltyp}::{self.kropp}#{self.ordning}"

    @property
    def på_analysvägen(self) -> bool:
        return self.fil in ANALYSVÄG


def _feltyp(handler: ast.ExceptHandler) -> str:
    if handler.type is None:
        return "BART except"
    try:
        return ast.unparse(handler.type)
    except Exception:
        return "?"


def _omslutande_funktioner(träd: ast.AST) -> Dict[int, str]:
    """Radnummer → närmaste omslutande funktions namn."""
    karta: Dict[int, str] = {}

    class Besökare(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: List[str] = []

        def _registrera(self, nod) -> None:
            self.stack.append(nod.name)
            # Skriv över, inte setdefault: klassen besöks före sina metoder, så
            # setdefault gav klassnamnet i stället för den innersta funktionen
            # — vilket är just den uppgift posten ska bära.
            for barn in ast.walk(nod):
                if hasattr(barn, "lineno"):
                    karta[barn.lineno] = ".".join(self.stack)
            self.generic_visit(nod)
            self.stack.pop()

        visit_FunctionDef = _registrera
        visit_AsyncFunctionDef = _registrera
        visit_ClassDef = _registrera

    Besökare().visit(träd)
    return karta


def _sväljer_tyst(handler: ast.ExceptHandler) -> Optional[str]:
    """
    Returnerar kroppens form om handlern sväljer undantaget utan spår.

    Enbart `pass`, `continue` eller `break` — eller en tilldelning av ett
    reservvärde — räknas. En handler som loggar, registrerar, höjer vidare
    eller returnerar ett strukturerat fel räknas inte.
    """
    kropp = handler.body
    if len(kropp) != 1:
        return None
    sats = kropp[0]
    if isinstance(sats, ast.Pass):
        return "pass"
    if isinstance(sats, ast.Continue):
        return "continue"
    if isinstance(sats, ast.Break):
        return "break"
    if isinstance(sats, (ast.Assign, ast.AnnAssign)):
        try:
            return f"tilldelning: {ast.unparse(sats)}"
        except Exception:
            return "tilldelning"
    return None


def inventera() -> List[Förekomst]:
    ut: List[Förekomst] = []
    for katalog in KATALOGER:
        d = ROOT / katalog
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.py")):
            if "__pycache__" in f.parts:
                continue
            rel = f.relative_to(ROOT).as_posix()
            try:
                träd = ast.parse(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            funktioner = _omslutande_funktioner(träd)
            for nod in ast.walk(träd):
                if not isinstance(nod, ast.ExceptHandler):
                    continue
                form = _sväljer_tyst(nod)
                if form is None:
                    continue
                ut.append(Förekomst(
                    fil=rel,
                    rad=nod.lineno,
                    funktion=funktioner.get(nod.lineno, "<modulnivå>"),
                    feltyp=_feltyp(nod),
                    kropp=form,
                ))

    # Löpnummer per identisk grupp, i radordning, så att nyckeln blir unik
    # även när en funktion har flera likadana handlers.
    ut.sort(key=lambda f: (f.fil, f.rad))
    räknare: Dict[str, int] = {}
    for f in ut:
        grupp = f"{f.fil}::{f.funktion}::{f.feltyp}::{f.kropp}"
        f.ordning = räknare.get(grupp, 0)
        räknare[grupp] = f.ordning + 1
    return ut


# ── Klassificering ──────────────────────────────────────────────────────────
# Nyckeln är Förekomst.nyckel: fil, omslutande funktion, fångad typ, kroppens
# form och ett löpnummer. Ändras någon av dessa är posten inte längre en
# beskrivning av samma handler, och förekomsten redovisas som oklassad.
#
# Formatet är nyckel -> (klass, skäl).

def _n(fil: str, funktion: str, feltyp: str, kropp: str, i: int = 0) -> str:
    return f"{fil}::{funktion}::{feltyp}::{kropp}#{i}"


_FE = "runtime/forensic_engine_v10_3_canonical.py"
_DTE = "runtime/document_text_extractor.py"
_DP = "runtime/dynamic_pipeline.py"
_DSP = "runtime/deep_search_pipeline.py"
_CL = "runtime/config_loader.py"
_CM = "runtime/capability_map.py"
_KL = "runtime/knowledge_loader.py"
_KS = "runtime/kodsystem_scanner.py"
_LV = "runtime/lagskifte_validator.py"
_EB = "integrations/economy_bridge.py"
_RB = "integrations/rattstids_bridge.py"
_AB = "integrations/advocacy_bridge.py"
_DEB = "integrations/dynamic_execution_bridge.py"
_MBR = "integrations/motor_b_runner.py"
_MS = "mcp/server.py"
_HS = "mcp/http_server.py"
_FA = "runtime/fmjam_adapter.py"
_KK = "runtime/konfig_kalla.py"
_LSB = "runtime/lsb_skyddat_scanner.py"
_RR = "runtime/rattstid_runner.py"
_HT = "scripts/SYSTEM_HEALTH_TEST_2026_09_22.py"
_EXC = "scripts/exception_census.py"
_VCI = "scripts/verify_case_isolation.py"
_EC = "runtime/evidence_categorizer.py"
_SC = "runtime/session_context.py"
_MR = "runtime/material_registry.py"
_CE = "integrations/consolidated_engine.py"
_MC = "runtime/motor_c_v10_v3.py"

KLASSIFICERING: Dict[str, Tuple[str, str]] = {

    # ── integrations/consolidated_engine.py ─────────────────────────────
    _n(_CE, "consolidate", "Exception", "tilldelning: ny_svensvit = {'status': 'FEL', 'reason': str(e)}"): ("REGISTERED_FAILURE", "Felet skrivs in i resultatet som status FEL med orsak och följer med ut i rapporten."),
    'runtime/sfcae_cli.py::kontrollera_systemkrav::Exception::tilldelning: pdftotext_körbar = False#0': ("HANDLED", "Fel vid kontroll av pdftotext sätter pdftotext_körbar = False utan att krascha CLI-kontrollen."),
    'scripts/fk_avancerad_praxis_test.py::SuiteRunner.test_2_concurrent_execution::Exception::continue#0': ("HANDLED", "Enskilt scenariofel i parallelltestet hoppas över med continue så övriga scenarier utvärderas."),
    'scripts/fk_avancerad_praxis_test.py::SuiteRunner.test_5_atomic_manifest_and_config_integrity::ImportError::tilldelning: yaml = None#0': ("OPTIONAL_DEPENDENCY", "Valfritt PyYAML-beroende i testsviten faller tillbaka till None när modulen saknas."),
    'scripts/fk_avancerad_praxis_test.py::SuiteRunner.test_5_atomic_manifest_and_config_integrity::ValueError::tilldelning: relative = str(path)#0': ("HANDLED", "Om sökvägen ligger utanför projektroten används str(path) som relativ etikett i stället för att krascha."),
    'scripts/fk_halsotest.py::check_configs::ImportError::tilldelning: yaml = None#0': ("OPTIONAL_DEPENDENCY", "Valfritt PyYAML-beroende i hälsotestet faller tillbaka till None när modulen saknas."),
    'scripts/fk_talighets_och_hallucinationskontroll.py::scan_unhandled_hard_stops::SyntaxError::continue#0': ("HANDLED", "Fil med SyntaxError hoppas över med continue under statisk skanning av hard stops."),

    # ── runtime/document_text_extractor.py ──────────────────────────────
    _n(_DTE, "DocumentTextExtractor._extract_plaintext",
       "(UnicodeDecodeError, LookupError)", "continue"):
        ("HANDLED",
         "Teckenkodningsslinga. continue prövar nästa kodning; for/else "
         "hanterar att samtliga misslyckas. Att en kodning inte passar är "
         "slingans normalfall, inte ett dolt fel."),
    _n(_DTE, "DocumentTextExtractor.extract_all", "(OSError, ValueError)",
       "pass"):
        ("HANDLED",
         "Filens ändringstid kunde inte läsas. Datumet står redan på "
         "'SAKNAS' och behåller det värdet — bristen är uttryckligt märkt i "
         "claimet, inte dold."),

    # ── runtime/forensic_engine_v10_3_canonical.py ──────────────────────
    _n(_FE, "IngestionAgent._process_file", "OSError", "pass"):
        ("SAFE",
         "Filstorlek för redovisning. Storleken påverkar varken extraktion, "
         "claimbildning eller integritetskontroll — SHA-256 beräknas "
         "separat och dess utfall redovisas för sig."),
    _n(_FE, "AuditController.run", "ValueError", "continue"):
        ("INTENTIONAL_SUPPRESSION",
         "HardStopCode(m) kastar ValueError när en sträng SER UT som en "
         "HS-kod men inte är någon. Att förkasta den är själva "
         "injektionsförsvaret: handlingstext får inte kunna sätta interna "
         "hard stops. Kontrolleras av hälsotestet, kontroll 5 och 10."),
    _n(_FE, "kör_rättsområdesskanning", "Exception",
       "tilldelning: resultat['mönsterbibliotek'] = {'status': 'EJ_KÖRBAR', "
       "'skäl': str(exc)}"):
        ("REGISTERED_FAILURE",
         "Mönsterbiblioteket registreras som EJ_KÖRBAR med orsak. "
         "Kodtabellsskanningen är oberoende och körs vidare."),
    _n(_FE, "minnesbank_las", "(IOError, OSError)",
       "tilldelning: content[filename] = f'[KAN EJ LÄSAS: {e}]'"):
        ("HANDLED",
         "Filens innehåll ersätts med en uttrycklig markör som bär orsaken. "
         "En oläsbar minnesbanksfil blir därmed synlig i innehållet i "
         "stället för att tyst utebli."),

    # Exportfelen: sedan rättningen registreras varje misslyckad export som
    # EJ_KÖRBAR via registrera_steg(), och run_pipeline namnger inte längre
    # artefakter som inte skrevs.
    **{
        _n(_FE, "exportera_l16_output", "Exception",
           f"tilldelning: results['{nyckel}'] = f'KAN EJ EXPORTERAS: {{e}}'"):
            ("REGISTERED_FAILURE",
             f"Misslyckad export av {nyckel} registreras som EJ_KÖRBAR i "
             f"stegstatus och redovisas i rapportens avsnitt STEG SOM INTE "
             f"GENOMFÖRTS. Tidigare namngavs filen ändå som skriven.")
        for nyckel in ("json", "csv", "markdown", "presentation_views")
    },

    # Testsvitens egna handlers: utfallet ÄR testresultatet.
    **{
        _n(_FE, "subagent_testsvit", feltyp,
           f"tilldelning: results['{test}'] = f'{etikett}: {{e}}'"):
            ("REGISTERED_FAILURE",
             f"{etikett} för {test} är testsvitens redovisade utfall och "
             f"kontrolleras av hälsotestets kontroll 13.")
        for test, feltyp, etikett in (
            ("T-01", "AssertionError", "FEL"), ("T-01", "Exception", "BUGG"),
            ("T-02", "AssertionError", "FEL"), ("T-02", "Exception", "BUGG"),
            ("T-03", "AssertionError", "FEL"), ("T-03", "Exception", "BUGG"),
            ("T-04", "Exception", "BUGG"), ("T-05", "Exception", "BUGG"),
        )
    },

    _n(_DTE, "DocumentTextExtractor._pdf_ocr_fallback",
       "pytesseract.TesseractError",
       "tilldelning: text = pytesseract.image_to_string(img, lang='eng')"):
        ("HANDLED",
         "Språkpaketet swe saknas i en del tesseract-installationer. Andra "
         "försöket kör engelska, vilket är sämre på svenska diakriter men "
         "bättre än ingen läsning alls. Misslyckas även det höjs felet till "
         "den yttre handlern, som redovisar OCR-vägen som FAILED med orsak — "
         "ingen text hittas på."),


    # ── runtime/dynamic_pipeline.py ─────────────────────────────────────
    #
    # Modulen når MCP-verktyget sfcae_run_pipeline. Vad som faktiskt når
    # anroparen är avgörande för bedömningen: _handle_run_pipeline returnerar
    # engine, zero_fel, hard_stops, underlag_saknas, domän, rekvisit och steg.
    # case_meta returneras INTE och läses inte av någon annan kod — verifierat
    # med sökning över runtime/, integrations/ och mcp/.

    _n(_DP, "<modulnivå>", "ImportError",
       "tilldelning: _KNOWLEDGE_AVAILABLE = False"):
        ("OPTIONAL_DEPENDENCY",
         "knowledge_loader är valfri. Flaggan styr att kunskapsstegen hoppas "
         "över, och frånvaron är ett uttryckligt tillstånd i stället för ett "
         "bortfall mitt i körningen."),

    _n(_DP, "<modulnivå>", "Exception",
       "tilldelning: _POLICY = {'provisional_output_only': True, "
       "'zero_inference': True, 'fail_closed': True, "
       "'min_source_coverage': 0.85, 'max_hard_stops_before_abort': 3}"):
        ("HANDLED",
         "Reservpolicyn är den strängaste: provisorisk output, ingen inferens, "
         "fail_closed. Raderna omedelbart efter höjer RuntimeError om någon av "
         "invarianterna inte håller — tidigare assert, som Python tar bort "
         "under -O."),

    _n(_DP, "<modulnivå>", "Exception", "tilldelning: _COURT_PROFILES = {}"):
        ("HANDLED",
         "Tom profilmängd prövas uttryckligen av anroparen (`if not "
         "_COURT_PROFILES`) innan den används. Frånvaron leder inte till en "
         "tyst felklassificering."),

    _n(_DP, "_step", "Exception",
       "tilldelning: sr = StepResult(step_id=step_id, module=module, "
       "status='FEL', detail='', error=f'{type(e).__name__}: {e}')"):
        ("REGISTERED_FAILURE",
         "Steget registreras som FEL med feltexten i state.steps, som är just "
         "den del av resultatet MCP returnerar som `steg`."),

    _n(_DP, "step_forum", "Exception", "tilldelning: result = None"):
        ("HANDLED",
         "Andra anropsformen för detect_forum. Misslyckas båda faller forum "
         "tillbaka på case_meta eller EJ_FASTSTÄLLT — en uttrycklig markör, "
         "inte ett gissat forum."),

    _n(_DP, "step_finalize", "Exception",
       "tilldelning: pm = getattr(PM, 'JUDGMENT_AUDIT', state.mode)"):
        ("HANDLED",
         "Reservläget är detsamma som funktionens dokumenterade standardläge, "
         "och raden ovanför väljer redan JUDGMENT_AUDIT för okända lägen."),

    _n(_DP, "_kör_rattstidskontroll", "Exception",
       "tilldelning: state.case_meta['lagversion_status'] = f'FAILED: {type(e).__name__}: {e}'"):
        ("REGISTERED_FAILURE",
         "Steg 28: utfallet skrivs som FAILED med undantagstyp och orsak i "
         "case_meta['lagversion_status'], inte som frånvaro av varning."),

    _n(_DP, "_validera_session_falt", "Exception", "pass"):
        ("HANDLED",
         "Autoifyllnad av rekvisit ur arende_config. Misslyckas den förblir "
         "rekvisitlistan tom, och `rekvisit` är ett fält MCP returnerar — "
         "anroparen ser att ingen ifyllnad skett. rekvisit_källa sätts bara "
         "vid lyckad ifyllnad."),

    _n(_DP, "_kolla_min_source_coverage", "Exception", "tilldelning: thr = 0.85"):
        ("SAFE",
         "Tröskeln faller tillbaka på samma värde som policyns eget "
         "standardvärde. Ingen skillnad i beteende."),
    _n(_DP, "step_claims", "Exception", "pass", 0):
        ("SAFE",
         "Valfri berikning: claim_id-validering via adapter. Resultatet skrivs enbart till case_meta, "
         "som varken returneras av MCP eller läses av någon annan kod — "
         "verifierat med sökning över runtime/, integrations/ och mcp/. "
         "Misslyckandet kan därför inte nå bevisning, claims, graf, rekvisit, "
         "hard stops eller utdata."),
    _n(_DP, "step_claims", "Exception", "pass", 1):
        ("SAFE",
         "Valfri berikning: citationsanalys. Resultatet skrivs enbart till case_meta, "
         "som varken returneras av MCP eller läses av någon annan kod — "
         "verifierat med sökning över runtime/, integrations/ och mcp/. "
         "Misslyckandet kan därför inte nå bevisning, claims, graf, rekvisit, "
         "hard stops eller utdata."),
    _n(_DP, "step_positions", "Exception", "pass", 0):
        ("SAFE",
         "Valfri berikning: partspåverkansanalys. Resultatet skrivs enbart till case_meta, "
         "som varken returneras av MCP eller läses av någon annan kod — "
         "verifierat med sökning över runtime/, integrations/ och mcp/. "
         "Misslyckandet kan därför inte nå bevisning, claims, graf, rekvisit, "
         "hard stops eller utdata."),
    _n(_DP, "step_legal_search", "Exception", "pass", 0):
        ("SAFE",
         "Valfri berikning: källklassificering av rättskällor. Resultatet skrivs enbart till case_meta, "
         "som varken returneras av MCP eller läses av någon annan kod — "
         "verifierat med sökning över runtime/, integrations/ och mcp/. "
         "Misslyckandet kan därför inte nå bevisning, claims, graf, rekvisit, "
         "hard stops eller utdata."),
    _n(_DP, "_kör_rattstidskontroll", "Exception", "pass", 0):
        ("SAFE",
         "Valfri berikning: rättstidsbryggan. Resultatet skrivs enbart till case_meta, "
         "som varken returneras av MCP eller läses av någon annan kod — "
         "verifierat med sökning över runtime/, integrations/ och mcp/. "
         "Misslyckandet kan därför inte nå bevisning, claims, graf, rekvisit, "
         "hard stops eller utdata."),
    _n(_DP, "run_dynamic_pipeline", "Exception", "pass", 0):
        ("SAFE",
         "Valfri berikning: lagerkarta. Resultatet skrivs enbart till case_meta, "
         "som varken returneras av MCP eller läses av någon annan kod — "
         "verifierat med sökning över runtime/, integrations/ och mcp/. "
         "Misslyckandet kan därför inte nå bevisning, claims, graf, rekvisit, "
         "hard stops eller utdata."),
    _n(_DP, "run_dynamic_pipeline", "Exception", "pass", 1):
        ("SAFE",
         "Valfri berikning: procedurprotokoll. Resultatet skrivs enbart till case_meta, "
         "som varken returneras av MCP eller läses av någon annan kod — "
         "verifierat med sökning över runtime/, integrations/ och mcp/. "
         "Misslyckandet kan därför inte nå bevisning, claims, graf, rekvisit, "
         "hard stops eller utdata."),
    _n(_DP, "run_dynamic_pipeline", "Exception", "pass", 2):
        ("SAFE",
         "Valfri berikning: arkitekturkunskap. Resultatet skrivs enbart till case_meta, "
         "som varken returneras av MCP eller läses av någon annan kod — "
         "verifierat med sökning över runtime/, integrations/ och mcp/. "
         "Misslyckandet kan därför inte nå bevisning, claims, graf, rekvisit, "
         "hard stops eller utdata."),
    _n(_DP, "run_dynamic_pipeline", "Exception", "pass", 3):
        ("SAFE",
         "Valfri berikning: övrig kunskap. Resultatet skrivs enbart till case_meta, "
         "som varken returneras av MCP eller läses av någon annan kod — "
         "verifierat med sökning över runtime/, integrations/ och mcp/. "
         "Misslyckandet kan därför inte nå bevisning, claims, graf, rekvisit, "
         "hard stops eller utdata."),
    _n(_DP, "run_dynamic_pipeline", "Exception", "pass", 4):
        ("SAFE",
         "Valfri berikning: skill-definitioner. Resultatet skrivs enbart till case_meta, "
         "som varken returneras av MCP eller läses av någon annan kod — "
         "verifierat med sökning över runtime/, integrations/ och mcp/. "
         "Misslyckandet kan därför inte nå bevisning, claims, graf, rekvisit, "
         "hard stops eller utdata."),
    _n(_DP, "run_dynamic_pipeline", "Exception", "pass", 5):
        ("SAFE",
         "Valfri berikning: externa paket. Resultatet skrivs enbart till case_meta, "
         "som varken returneras av MCP eller läses av någon annan kod — "
         "verifierat med sökning över runtime/, integrations/ och mcp/. "
         "Misslyckandet kan därför inte nå bevisning, claims, graf, rekvisit, "
         "hard stops eller utdata."),
    _n(_DP, "run_dynamic_pipeline", "Exception", "pass", 6):
        ("SAFE",
         "Valfri berikning: skill-referenser. Resultatet skrivs enbart till case_meta, "
         "som varken returneras av MCP eller läses av någon annan kod — "
         "verifierat med sökning över runtime/, integrations/ och mcp/. "
         "Misslyckandet kan därför inte nå bevisning, claims, graf, rekvisit, "
         "hard stops eller utdata."),
    _n(_DP, "run_dynamic_pipeline", "Exception", "pass", 7):
        ("SAFE",
         "Valfri berikning: ärenderesurser. Resultatet skrivs enbart till case_meta, "
         "som varken returneras av MCP eller läses av någon annan kod — "
         "verifierat med sökning över runtime/, integrations/ och mcp/. "
         "Misslyckandet kan därför inte nå bevisning, claims, graf, rekvisit, "
         "hard stops eller utdata."),
    _n(_DP, "run_dynamic_pipeline", "Exception",
       "tilldelning: state.case_meta['_knowledge_available'] = False"):
        ("SAFE",
         "Samma sak: diagnostikfält i case_meta, utan konsument och utan väg "
         "till utdata."),

    # ── Verifieringsverktygen ───────────────────────────────────────────
    #
    # Dessa ligger utanför produktens körväg, men just här är en tyst gren
    # allvarligast: en kontroll som hoppar över ett fall och ändå rapporterar
    # OK är en kontroll som inte kan falla. Var och en är därför prövad mot
    # frågan om den kan dölja ett underkännande.

    _n(_HT, "kontroll_hard_stops", "ValueError", "pass"):
        ("SAFE",
         "HardStopCode(m) på varje regexträff. ValueError betyder att "
         "strängen inte är en hard stop-kod, och `pass` är själva "
         "medlemskapsprövningen — inte ett bortfall. Enbart verkliga koder "
         "hamnar i mängden funna."),

    _n(_HT, "kontroll_hard_stops", "Exception",
       "tilldelning: register_ok, register_detalj = (False, "
       "f'registret kunde inte läsas: {exc}')"):
        ("REGISTERED_FAILURE",
         "Ett oläsbart hard stop-register sätter register_ok till False, "
         "vilket gör att kontrollen underkänns med orsaken i detaljtexten. "
         "Handlern kan alltså bara leda till ett strängare utfall."),

    _n(_HT, "kontroll_mcp_routing", "Exception", "continue"):
        ("INTENTIONAL_SUPPRESSION",
         "Kontrollen letar efter verktyg som svarar lyckat trots saknade "
         "obligatoriska parametrar. Ett undantag är inte ett falskt lyckat "
         "svar — dispatchen exponerar det som isError, vilket är rätt "
         "felkontrakt. Räknaren prövade har redan ökats, så verktyget "
         "försvinner inte ur redovisningen."),

    _n(_HT, "kontroll_mcp_verktygskontrakt",
       "(ValueError, FileNotFoundError, PermissionError, OSError)", "continue"):
        ("INTENTIONAL_SUPPRESSION",
         "Strukturerad invändning mot syntetiska sökvägar. Dispatchern gör "
         "den till isError, vilket är det avsedda felkontraktet. Grenen för "
         "oväntade undantagstyper rapporterar däremot numera verktyget som "
         "oprövat i stället för att hoppa över det tyst."),

    _n(_EXC, "inventera", "Exception", "continue"):
        ("SAFE",
         "ast.parse på en fil som inte går att tolka. Filen kan inte "
         "innehålla några analyserbara handlers, och en fil som inte är "
         "giltig Python fångas av hälsotestets kontroll 1, som importerar "
         "hela arkitekturen."),

    _n(_VCI, "kör", "OSError", "pass"):
        ("SAFE",
         "os.unlink på en temporär arbetsfil i ett finally-block. "
         "Misslyckad städning påverkar inget resultat, och filen ligger i "
         "systemets temp-katalog, utanför de kodkataloger hälsotestets "
         "artefaktkontroll bevakar."),

    # ── integrations/advocacy_bridge.py ─────────────────────────────────

    _n(_AB, "_extrahera_rekvisit", "ImportError", "tilldelning: RS = None"):
        ("HANDLED",
         "Motorns RequisiteStatus och map_requisite_status_to_five. Saknas de "
         "prövas `if mapper and RS is not None` och rekvisiten sorteras på sin "
         "råa statussträng. Utfallet redovisas i fältet statusmappning, som "
         "då anger RÅ_STRÄNG i stället för KANONISK."),

    _n(_AB, "run_advocacy_if_requested", "Exception",
       "tilldelning: motpartsanalys = {'fel': str(e)}"):
        ("REGISTERED_FAILURE",
         "Felet läggs i delresultatet, och svarets status blir DELVIS "
         "GENOMFÖRD i stället för GENOMFÖRD. Tidigare rapporterades ett "
         "fullständigt genomförande även när båda delarna bara innehöll "
         "ett fel-fält."),

    _n(_AB, "run_advocacy_if_requested", "Exception",
       "tilldelning: utkast = {'fel': str(e)}"):
        ("REGISTERED_FAILURE", "Som motpartsanalysen ovan."),

    # ── integrations/dynamic_execution_bridge.py ────────────────────────

    _n(_DEB, "_action_resolve", "Exception",
       "tilldelning: preview = f'[KAN EJ LÄSAS: {type(e).__name__}: {e}]'", 0):
        ("REGISTERED_FAILURE",
         "Förhandsvisningen får en uttrycklig markör. Tidigare blev den en "
         "tom sträng, vilket inte gick att skilja från en fil vars åtta "
         "första rader är tomma — trots att statusen är HITTAD."),

    _n(_DEB, "_action_resolve", "Exception",
       "tilldelning: preview = f'[KAN EJ LÄSAS: {type(e).__name__}: {e}]'", 1):
        ("REGISTERED_FAILURE", "Som ovan, pack-indexets gren."),

    _n(_DEB, "_action_resolve", "Exception",
       "tilldelning: preview = f'[KAN EJ LÄSAS: {type(e).__name__}: {e}]'", 2):
        ("REGISTERED_FAILURE", "Som ovan, registry-indexets gren."),

    # ── integrations/motor_b_runner.py ──────────────────────────────────

    _n(_MBR, "run_motor_b_if_requested", "Exception",
       "tilldelning: out['agenter']['metadata'] = {'status': 'SAKNAS', "
       "'fel': str(e)[:120]}"):
        ("REGISTERED_FAILURE",
         "Agenten redovisas som SAKNAS med feltexten i svaret."),

    _n(_MBR, "run_motor_b_if_requested", "Exception",
       "tilldelning: out['agenter']['rostanalys'] = {'status': 'EJ_KOPPLAD', "
       "'fel': str(e)[:160], 'not': 'valfri'}"):
        ("OPTIONAL_DEPENDENCY",
         "Röstanalysen är uttryckligen valfri och redovisas som EJ_KOPPLAD, "
         "nu med feltexten i svaret."),

    _n(_MBR, "run_motor_b_if_requested", "Exception",
       "tilldelning: out['agenter']['rattstidskontroll'] = {'status': 'SAKNAS', "
       "'fel': str(e)[:120]}"):
        ("REGISTERED_FAILURE",
         "Agenten redovisas som SAKNAS med feltexten i svaret — samma "
         "konstruktion som metadata-agenten ovan."),

    _n(_MBR, "_samla_ljudfiler", "Exception",
       "tilldelning: format_ = ('.wav', '.mp3', '.m4a', '.flac', '.ogg', '.aac')"):
        ("HANDLED",
         "Går motor_b_agents.ljudformat inte att importera används de "
         "vanliga ljudändelserna. Funktionen samlar bara kandidatfiler; "
         "går motor_b_agents inte att importera redovisas själva "
         "röstanalysen som EJ_KOPPLAD med fel (se run_motor_b_if_requested)."),

    # ── mcp/server.py och mcp/http_server.py ────────────────────────────

    _n(_MS, "_ensure_utf8_stdio", "Exception", "pass"):
        ("SAFE",
         "Omkonfigurering av stdio till UTF-8. Misslyckas den behåller "
         "strömmarna sin befintliga kodning; MCP-ramverket skickar ändå "
         "Content-Length-räknad JSON. Inget analysresultat berörs."),

    _n(_MS, "_handle_lista_arenden", "TypeError",
       "tilldelning: ärenden = lista_ärenden()"):
        ("HANDLED",
         "Andra anropsformen för lista_ärenden, för versioner utan "
         "parametern. Misslyckas även den propagerar undantaget."),

    _n(_HS, "lista_arenden", "TypeError",
       "tilldelning: ärenden = lista_ärenden()"):
        ("HANDLED", "Samma konstruktion som i mcp/server.py."),

    # ── runtime/fmjam_adapter.py ────────────────────────────────────────

    _n(_FA, "_read_file_texts", "Exception",
       "tilldelning: läsfel = f'{type(e).__name__}: {e}'"):
        ("REGISTERED_FAILURE",
         "En handling som inte gick att läsa blev tidigare en tom sträng och "
         "behandlades i varje efterföljande lager som en handling utan "
         "innehåll. Skillnaden mellan 'dokumentet saknar text' och 'vi kunde "
         "inte läsa dokumentet' försvann därmed ur underlaget — avgörande för "
         "om ett rekvisit får anses obestyrkt eller oprövat. Orsaken följer "
         "nu med posten i fältet läsfel."),

    _n(_FA, "_state_to_dict", "Exception",
       "tilldelning: out[attr] = str(val)[:500]"):
        ("HANDLED",
         "Reservserialisering när ett attribut inte är JSON-dugligt. Värdet "
         "bevaras som text i stället för att utelämnas, så inget fält "
         "försvinner ur tillståndsbilden."),

    # ── runtime/konfig_kalla.py ─────────────────────────────────────────

    _n(_KK, "<modulnivå>", "ImportError",
       "tilldelning: YAML_TILLGÄNGLIG = False"):
        ("OPTIONAL_DEPENDENCY",
         "Laddarens egen importvakt. Saknas pyyaml blir varje ladda_konfig "
         "EJ_LÄST med 'pyyaml saknas' som skäl — aldrig en tom konfiguration "
         "som ser normal ut. Det är hela modulens syfte."),

    # ── runtime/lsb_skyddat_scanner.py ──────────────────────────────────

    _n(_LSB, "skanna_lsb_skyddat", "Exception", "pass"):
        ("HANDLED",
         "Försök att återanvända kodsystem_scanner.skanna_text. Misslyckas "
         "det faller funktionen igenom till modulens egen skanning nedan, "
         "som är fullständig och redovisar sin konfigkälla. Ingen gren "
         "lämnar funktionen utan resultat."),

    # ── runtime/rattstid_runner.py ──────────────────────────────────────

    _n(_RR, "_parse_date", "ValueError", "continue"):
        ("SAFE",
         "Prövar tre datumformat i tur och ordning; `continue` går vidare "
         "till nästa format. Håller inget av dem returneras None, vilket "
         "anroparen prövar. Konstruktionen är själva formatprövningen, inte "
         "ett bortfall."),

    # ── integrations/economy_bridge.py ──────────────────────────────────

    _n(_EB, "<modulnivå>", "ImportError",
       "tilldelning: reconstruct_economic_chain = None"):
        ("HANDLED",
         "run_economic_reconstruction prövar None på rad 45 och svarar då "
         "status MODUL_SAKNAS med flaggan 'fas5_economic_reconstruction "
         "kunde inte importeras'. Frånvaron är ett uttryckligt tillstånd i "
         "svaret, inte en rekonstruktion med noll poster."),

    # ── integrations/rattstids_bridge.py ────────────────────────────────

    _n(_RB, "<modulnivå>", "ImportError",
       "tilldelning: kör_deep_search_pipeline = None"):
        ("OPTIONAL_DEPENDENCY",
         "Deep Search används enbart för att berika en rättsregels etikett "
         "med markeringen [VERIFIERAD VIA RIKSDAGEN]. Saknas modulen prövas "
         "villkoret `if kör_deep_search_pipeline:` och berikningen uteblir. "
         "Bortfallet kan bara ta bort ett verifieringspåstående, aldrig "
         "skapa ett."),

    _n(_RB, "run_rattstidskontroll", "Exception", "pass"):
        ("SAFE",
         "Misslyckas sökningen behåller etiketten sitt ursprungliga värde och "
         "markeringen [VERIFIERAD VIA RIKSDAGEN] sätts inte. Felet kan alltså "
         "bara leda till att en regel förblir omarkerad — aldrig till att en "
         "overifierad regel märks som verifierad. Riktningen är fail-closed."),

    # ── runtime/capability_map.py ───────────────────────────────────────

    _n(_CM, "<modulnivå>", "ImportError", "tilldelning: _Y = False"):
        ("HANDLED",
         "pyyaml är ett deklarerat beroende som sfcae_cli --check prövar. "
         "Saknas det sätts hindret 'pyyaml saknas' och aktivera_moduler "
         "svarar status EJ GENOMFÖRD. Statusen var tidigare GENOMFÖRD även "
         "när noll moduler hade övervägts, vilket inte gick att skilja från "
         "ett ärende där ingen specialistmodul var tillämplig."),

    _n(_CM, "aktivera_moduler", "Exception",
       "tilldelning: hinder = f'{p.name} kunde inte tolkas: "
       "{type(e).__name__}: {e}'"):
        ("REGISTERED_FAILURE",
         "Ett otolkbart capability_map.yaml ger status EJ GENOMFÖRD med "
         "orsaken i fältet hinder, i stället för en tom men till synes "
         "genomförd kartläggning."),

    # ── runtime/knowledge_loader.py ─────────────────────────────────────

    _n(_KL, "KnowledgeFile.__post_init__", "Exception",
       "tilldelning: self.content_preview = '[ERROR: Cannot read file]'"):
        ("REGISTERED_FAILURE",
         "Förhandsvisningen får den uttryckliga markören [ERROR: Cannot read "
         "file]. En oläsbar kunskapsfil kan därmed inte förväxlas med en fil "
         "vars innehåll är tomt."),

    # ── runtime/kodsystem_scanner.py ────────────────────────────────────

    _n(_KS, "<modulnivå>", "ImportError", "tilldelning: _YAML_OK = False"):
        ("HANDLED",
         "_ladda_kodtabell prövar flaggan först av allt och returnerar None. "
         "Anroparen får alltså ingen kodtabell alls i stället för en tom, och "
         "skillnaden mellan 'inga koder matchade' och 'ingen kodtabell fanns' "
         "bevaras. pyyaml är dessutom ett deklarerat beroende som "
         "sfcae_cli --check prövar."),

    # ── runtime/lagskifte_validator.py ──────────────────────────────────

    _n(_LV, "_ladda_lagskiften", "Exception",
       "tilldelning: LAGSKIFTEN_SKÄL = f'arende_config kunde inte läsas: "
       "{type(e).__name__}: {e}'"):
        ("REGISTERED_FAILURE",
         "Skälet sparas och LAGSKIFTEN_KÄLLA sätts till INBYGGD_FALLBACK. "
         "dynamic_pipeline registrerar då steget lagskiften_källa som FEL, "
         "vilket är den del av resultatet MCP returnerar. Tidigare föll tre "
         "skilda vägar tyst tillbaka på modulens inbyggda tvåpostslista, "
         "varpå HS11 prövades mot motorns egna värden i stället för de "
         "konfigurerade."),

    # ── runtime/config_loader.py ────────────────────────────────────────

    _n(_CL, "<modulnivå>", "ImportError", "tilldelning: _YAML_OK = False"):
        ("HANDLED",
         "pyyaml är ett deklarerat beroende och prövas av sfcae_cli --check, "
         "som gör dess frånvaro till en brist. Saknas det ändå faller inte "
         "modulen: validera_alla svarar uttryckligen 'FEL: yaml saknas' per "
         "konfiguration i stället för att tyst redovisa dem som giltiga."),

    _n(_CL, "validera_alla", "Exception", "tilldelning: resultat[key] = f'FEL: {e}'"):
        ("REGISTERED_FAILURE",
         "Varje konfiguration som inte går att tolka får FEL med orsak i "
         "resultatet. En ogiltig fil kan därmed inte förväxlas med en giltig."),

    # ── runtime/evidence_categorizer.py ─────────────────────────────────

    _n(_EC, "exportera_kategorisering", "Exception",
       "tilldelning: results['json'] = f'KAN EJ EXPORTERAS: {e}'"):
        ("REGISTERED_FAILURE",
         "Exportutfallet per format returneras med orsaken bifogad."),

    _n(_EC, "exportera_kategorisering", "Exception",
       "tilldelning: results['markdown'] = f'KAN EJ EXPORTERAS: {e}'"):
        ("REGISTERED_FAILURE",
         "Som json-grenen ovan."),

    # ── runtime/session_context.py ──────────────────────────────────────

    _n(_SC, "spara_session", "Exception",
       "tilldelning: revisionslogg = f'EJ SKRIVEN: {type(e).__name__}: {e}'"):
        ("REGISTERED_FAILURE",
         "Skrivningen till SQLite-revisionsloggen (audit_logs). JSON-filen är "
         "den primära lagringen och har redan skrivits när detta sker. "
         "Funktionen svarade tidigare SPARAD även när revisionsloggen hade "
         "fallerat, alltså ett besked om en fullständig sparning som inte ägt "
         "rum. Utfallet redovisas nu i fältet revisionslogg."),

    # ── runtime/deep_search_pipeline.py ─────────────────────────────────
    #
    # Nåbarhet, fastställd med sökning över hela trädet: utifrån importeras
    # enbart kör_deep_search_pipeline (motorn rad 4427, rattstids_bridge
    # rad 34) och SourceClassifier (source_class_bridge rad 41). Modulens
    # exportera_l16_output och subagent_testsvit nås alltså INTE av motorn.
    # De anropas bara av modulens egen main() under if __name__ == "__main__",
    # det vill säga en parallell CLI-ingång.
    #
    # DUBBLERAD IMPLEMENTATION: exportera_l16_output (63 rader här, 82 i
    # motorn) och subagent_testsvit (60 här, 81 i motorn) finns i båda
    # filerna och är INTE identiska. De prövar och exporterar olika saker.
    # Motorns versioner är de rättade. Se docs/TEKNISK_REKONSTRUKTION.md.

    _n(_DSP, "<modulnivå>", "ImportError", "tilldelning: REQUESTS_AVAILABLE = False"):
        ("OPTIONAL_DEPENDENCY",
         "requests är valfritt och används bara för externa rättskällor. "
         "Saknas det returnerar _run_standard_search status DISABLED med "
         "installationsanvisning (rad 363). Frånvaron blir ett uttryckligt "
         "tillstånd i resultatet, inte en tom träfflista."),

    _n(_DSP, "<modulnivå>", "ImportError", "tilldelning: FEEDPARSER_AVAILABLE = False"):
        ("OPTIONAL_DEPENDENCY",
         "feedparser läser JO:s RSS-flöde. Saknas det läggs noten "
         "'feedparser saknas – JO RSS ej tillgänglig' i resultatlistan, så "
         "att en utebliven källa inte kan förväxlas med en genomsökt källa "
         "utan träff."),

    _n(_DSP, "<modulnivå>", "ImportError", "tilldelning: BS4_AVAILABLE = False"):
        ("OPTIONAL_DEPENDENCY",
         "beautifulsoup4 läser JK:s HTML. Saknas det läggs en motsvarande "
         "not i resultatlistan. Grenen prövade tidigare bara BS4_AVAILABLE, "
         "varför fallet 'requests saknas men bs4 finns' föll mellan grenarna "
         "och tog bort JK-källan utan spår. Rättat: noten räknar nu upp "
         "samtliga saknade paket."),

    _n(_DSP, "SubAgent._run_search_06", "Exception",
       "tilldelning: orsak = f'{type(e).__name__}: {e}'"):
        ("REGISTERED_FAILURE",
         "EUR-Lex SPARQL. Utfallet registreras som SubAgentResult med status "
         "FAILED. Felorsaken kastades tidigare bort och ersattes av en fast "
         "textsträng, vilket gjorde ett kodfel oskiljbart från en nedstängd "
         "tjänst. Orsaken följer nu med i error-fältet."),

    _n(_DSP, "SubAgent._run_search_07", "Exception",
       "tilldelning: orsak = f'{type(e).__name__}: {e}'"):
        ("REGISTERED_FAILURE",
         "HUDOC. Samma konstruktion och samma rättning som _run_search_06."),

    _n(_DSP, "kör_deep_search_pipeline", "Exception",
       "tilldelning: results[sid] = SubAgentResult(search_id=sid, "
       "syfte=SEARCH_CONFIG.get(sid, {}).get('syfte', ''), "
       "källa=SEARCH_CONFIG.get(sid, {}).get('källa', ''), sokterm=sokterm, "
       "status='FAILED', error=str(e), "
       "source_type=SEARCH_CONFIG.get(sid, {}).get('source_type', ''), "
       "authority_level=SEARCH_CONFIG.get(sid, {}).get('authority_level', ''))"):
        ("REGISTERED_FAILURE",
         "Registrering av en sökagent som fallerat. Resultatet får status "
         "FAILED med feltexten, och posten finns kvar i results — den söknings-"
         "id som inte gick att köra försvinner alltså inte ur underlaget."),

    _n(_DSP, "minnesbank_subagent", "(IOError, OSError)",
       "tilldelning: results[filename] = '[KAN EJ LÄSAS]'"):
        ("REGISTERED_FAILURE",
         "Filen skrivs in i resultatet med den uttryckliga markören "
         "[KAN EJ LÄSAS]. En oläsbar fil kan därmed inte förväxlas med en "
         "fil som lästs utan träff."),

    _n(_DSP, "exportera_l16_output", "Exception",
       "tilldelning: results['json'] = f'KAN EJ EXPORTERAS: {e}'"):
        ("REGISTERED_FAILURE",
         "Exportutfallet per format returneras till anroparen med orsaken "
         "bifogad. Utanför analysvägen: funktionen nås bara av modulens egen "
         "CLI, inte av motorn."),

    _n(_DSP, "exportera_l16_output", "Exception",
       "tilldelning: results['csv'] = f'KAN EJ EXPORTERAS: {e}'"):
        ("REGISTERED_FAILURE",
         "Som json-grenen ovan."),

    _n(_DSP, "exportera_l16_output", "Exception",
       "tilldelning: results['markdown'] = f'KAN EJ EXPORTERAS: {e}'"):
        ("REGISTERED_FAILURE",
         "Som json-grenen ovan."),

    # Testsvitens fem handlers registrerar varje brutet kontrakt som BUGG med
    # feltyp och meddelande. Kontrollerna byggde tidigare på assert, som -O
    # tar bort: sviten rapporterade då GODKÄND utan att ha prövat något.
    # Verifierat med felinjektion. Kontrollerna sker nu med uttrycklig raise.
    _n(_DSP, "subagent_testsvit", "Exception",
       "tilldelning: results['T-01'] = f'BUGG: {type(e).__name__}: {e}'"):
        ("REGISTERED_FAILURE",
         "T-01 registrerar utfallet som BUGG med orsak i returvärdet."),

    _n(_DSP, "subagent_testsvit", "Exception",
       "tilldelning: results['T-02'] = f'BUGG: {type(e).__name__}: {e}'"):
        ("REGISTERED_FAILURE", "T-02, som T-01."),

    _n(_DSP, "subagent_testsvit", "Exception",
       "tilldelning: results['T-03'] = f'BUGG: {type(e).__name__}: {e}'"):
        ("REGISTERED_FAILURE", "T-03, som T-01."),

    _n(_DSP, "subagent_testsvit", "Exception",
       "tilldelning: results['T-04'] = f'BUGG: {type(e).__name__}: {e}'"):
        ("REGISTERED_FAILURE", "T-04, som T-01."),

    _n(_DSP, "subagent_testsvit", "Exception",
       "tilldelning: results['T-05'] = f'BUGG: {type(e).__name__}: {e}'"):
        ("REGISTERED_FAILURE", "T-05, som T-01."),

    # ── runtime/material_registry.py ────────────────────────────────────
    _n(_MR, "<modulnivå>", "ImportError", "tilldelning: _Y = False"):
        ("HANDLED",
         "pyyaml är valfritt här. Flaggan styr att blueprinten hoppas över, "
         "och _fält() registrerar då 'pyyaml saknas' som laddningsfel."),
    _n(_MR, "_fält", "Exception",
       "tilldelning: _FÄLT_LADDNINGSFEL = f'{type(exc).__name__}: {exc}'"):
        ("REGISTERED_FAILURE",
         "Orsaken bevaras i _FÄLT_LADDNINGSFEL och kan läsas med "
         "fält_laddningsfel(). Utan den var en trasig blueprint oskiljbar "
         "från en som saknas — båda gav minimifältlistan."),
    _n(_MR, "registrera_material", "Exception",
       "tilldelning: h = f'KAN EJ BERÄKNAS: {type(exc).__name__}'"):
        ("REGISTERED_FAILURE",
         "Hashfel skrivs in i posten som 'KAN EJ BERÄKNAS'. Tidigare blev "
         "det None, samma värde som 'ingen sökväg' och 'filen saknas' — tre "
         "skilda utfall som såg likadana ut."),

    # ── runtime/module_loader.py ────────────────────────────────────────
    _n("runtime/module_loader.py", "dubbletter", "(OSError, ValueError)",
       "continue"):
        ("SAFE",
         "Path.resolve() på en modul vars __file__ inte går att kanonisera. "
         "Funktionen letar efter filer laddade under flera modulnamn; en "
         "sökväg som inte kan lösas kan per definition inte utgöra en sådan "
         "dubblett."),

    # ── Tillägg fix/runtime-integration: nya handlers på analysvägen ──
    _n(_MC, '_finalize', 'Exception',
       "tilldelning: utfall = {'json': f'KAN EJ EXPORTERAS: {type(e).__name__}: {e}', 'markdown': 'EJ FÖRSÖKT'}"):
        ('REGISTERED_FAILURE',
         'Misslyckad export av bevis_kategorisering registreras i csm._kat_export och redovisas som bevis_kategorisering_export i Motor C-sammanfattningen; loggen säger då Export ofullständig i stället för Exporterade.'),
    _n(_CE, '_vidarebefordra_legal_merge', '(OSError, ValueError)',
       "tilldelning: views = {}"):
        ('HANDLED',
         'Saknas eller är presentation_views_v10.json oläsbar skrivs filen ny med enbart legal_merge-blocket; sammanfogningen går inte förlorad och kanoniska vyer som inte fanns hittas inte på.'),
    _n(_CE, '_cli_falt', 'Exception',
       "tilldelning: f['ej_genomförda_steg'] = [s for s in md.get('stegstatus') or [] if s.get('status') not in ('GENOMFÖRD', 'EJ_TILLÄMPLIG')]"):
        ('HANDLED',
         "Om motorns ej_genomförda_steg() inte kan anropas läses samma uppgift direkt ur metadata['stegstatus']. Ej genomförda steg redovisas alltså ändå och blir delfel i resultatet."),
    # ── Steg 14: tekniskt undantag -> FAILED ──
    _n(_FE, '_tekniskt_fel_ger_failed.run_pipeline', 'Exception',
       "tilldelning: cs.metadata['tekniskt_fel']['export'] = f'{type(exp_exc).__name__}: {exp_exc}'"):
        ('REGISTERED_FAILURE',
         'Misslyckad export av FAILED-tillståndet skrivs in i case_state.metadata["tekniskt_fel"]["export"] med feltyp och orsak; CaseState returneras med pipeline_state FAILED, matrisen OGILTIG och falsifiering NOT_RUN.'),
    _n(_CE, '_kör_alt_b', 'Exception',
       "tilldelning: res[namn] = {'status': 'FEL', 'fel': f'{type(e).__name__}: {e}'}"):
        ('REGISTERED_FAILURE',
         'Ett fel i en begärd kategori C-modul skrivs in som status FEL med orsak på modulens nivå, samlas av _delfel() och ger analysnivå DELVIS. Övriga moduler körs vidare.'),
    _n(_CE, 'consolidate', 'Exception',
       "tilldelning: result.setdefault('alt_b', {})['strikt_rapport'] = {'status': 'FEL', 'fel': f'{type(e).__name__}: {e}'}"):
        ('REGISTERED_FAILURE',
         'Fel i den begärda strikta rapporten skrivs in som alt_b.strikt_rapport status FEL med orsak och följer med i consolidated_engine_report.json.'),
    _n(_MS, '_kodscan_domäner', 'Exception',
       'pass'):
        ('OPTIONAL_DEPENDENCY',
         'Utan config_loader begränsas enum-listan till de bakåtkompatibla aliasen. Inget analysresultat påverkas, och verktyget anropas fortfarande med ett giltigt alias.'),
    _n(_MS, '_kodscan_sökväg', 'Exception',
       'tilldelning: rel = None'):
        ('HANDLED',
         'Okänd domän som inte heller kan lösas via config_loader ger None; _handle_kodscan svarar EJ_KÖRBAR med giltiga domäner (ingen tyst FK_SFB-tabell).'),
    _n(_MS, '_sätt_reflektionsscheman', 'Exception',
       "tilldelning: t['inputSchema'] = {'type': 'object', 'properties': {}, 'description': f'backend kunde inte inspekteras: {type(e).__name__}: {e}'}"):
        ('HANDLED',
         'Backend som inte kan importeras vid start får tomt schema med orsaken i description; anrop till verktyget redovisar samma importfel som EJ_KÖRBAR via reflektionshandlern.'),
    _n(_DP, '_kör_begärda_moduler', 'Exception',
       "tilldelning: resultat[namn] = {'status': 'FEL', 'skäl': f'{type(e).__name__}: {e}'}"):
        ('REGISTERED_FAILURE',
         'Ett fel i en begärd modul skrivs in med status FEL och orsak i modulens resultat. Övriga begärda moduler körs vidare.'),
    _n(_DP, '_registrera_resurser', 'Exception',
       "tilldelning: state.case_meta['_config_register_fel'] = f'{type(e).__name__}: {e}'"):
        ('REGISTERED_FAILURE',
         "Felet registreras i case_meta['_config_register_fel'] och följer med i pipelinens metadata."),
    _n(_DP, '_registrera_resurser', 'Exception',
       "tilldelning: state.case_meta['domänresurser'] = {'fel': f'{type(e).__name__}: {e}'}"):
        ('REGISTERED_FAILURE',
         "Felet registreras i case_meta['domänresurser']['fel'] och följer med i pipelinens metadata."),
    _n(_DP, '_registrera_resurser', 'Exception',
       "tilldelning: state.case_meta['ärendebundna_config'] = {'fel': f'{type(e).__name__}: {e}'}"):
        ('REGISTERED_FAILURE',
         "Felet registreras i case_meta['ärendebundna_config']['fel'] och följer med i pipelinens metadata."),
    _n(_DP, '_kör_rattstidskontroll', 'Exception',
       "tilldelning: state.case_meta['rattstidskontroll_bridge'] = {'status': 'FEL', 'fel': f'{type(e).__name__}: {e}'}"):
        ('REGISTERED_FAILURE',
         "Ersätter ett tidigare except: pass. Fel i rättstidskontrollen registreras med status FEL och orsak i case_meta['rattstidskontroll_bridge']."),
    _n(_DP, 'run_dynamic_pipeline', 'Exception',
       "tilldelning: state.case_meta['_alt_b_register_fel'] = f'{type(e).__name__}: {e}'"):
        ('REGISTERED_FAILURE',
         "Felet registreras i case_meta['_alt_b_register_fel']. Kategori C körs aldrig i standardkedjan, så standardanalysen påverkas inte."),
    _n(_MC, '_redan_laddad', '(OSError, ValueError)',
       'continue'):
        ('SAFE',
         'Jämförelse av en redan laddad moduls __file__. En sökväg som inte kan lösas upp kan inte vara samma fil. Faller annars tillbaka på vanlig import.'),
    _n(_MC, '_kategorisera_fil', 'ValueError',
       'tilldelning: _rel = _abs.name'):
        ('HANDLED',
         'En fil utanför roten får sitt filnamn som relativ sökväg. Kategoriseringen körs ändå.'),
    _n(_MC, 'CounterAuditAgent._parse_date', 'ValueError',
       'continue'):
        ('HANDLED',
         'Datumformatslinga: nästa format prövas, och om inget passar returneras None, vilket anroparen redovisar som ej verifierbart datum.'),
    _n(_MC, '_enrich_with_name_categorizer', 'ValueError',
       'continue'):
        ('SAFE',
         'Filtrerar bort filer som inte ligger under den aktuella roten. De hör till en annan rot och kategoriseras där.'),
    _n(_MC, '_motor_c_sammanfattning._d', 'Exception',
       'pass'):
        ('HANDLED',
         'Om to_dict() misslyckas serialiseras objektet via nästa väg (dataklass/attribut). Värdet redovisas alltså ändå.'),
    _n(_MS, 'call_tool', 'Exception',
       "tilldelning: resultat = {'status': 'HARD_STOP', 'kod': 'HS_MCP_ERROR', 'verktyg': name, 'fel': f'{type(e).__name__}: {e}'}"):
        ('REGISTERED_FAILURE',
         'Dispatcherns yttersta skydd. Ett undantag ur en handler blir ett HARD_STOP-svar med koden HS_MCP_ERROR, verktygsnamnet och felet, som returneras till klienten och loggas med spårbarhetsfälten nedanför.'),
    _n(_DP, '_load', '(OSError, ValueError)', 'pass'):
        ('SAFE',
         'Sökningen efter samma fil under ett annat modulnamn. Kan en sökväg inte lösas upp hoppas återanvändningen över och filen laddas via module_loader som tidigare; en eventuell dubbelladdning fångas av hälsotestets kontroll En fil, en modul.'),
    _n(_DP, 'run_dynamic_pipeline', 'Exception',
       "tilldelning: _session_params = {'case_meta': {'session_status': f'KAN EJ LÄSAS: {type(e).__name__}: {e}'}}"):
        ('REGISTERED_FAILURE',
         "En session som inte kan läsas registreras i case_meta['session_status'] med orsak. Tidigare blev den {} och analysen kördes tyst som om ingen session angetts."),
    _n(_FE, 'AuditController.P18_MAX_KVOT', '(TypeError, ValueError)',
       'tilldelning: värde = None'):
        ('REGISTERED_FAILURE',
         'Ett otolkbart tröskelvärde i config/audit_controller.yaml ger den hårdkodade tröskeln, och källan registreras i p18_tröskel_källa = FALLBACK_HARDKODAD. Ett värde utanför (1.0, fallback] avvisas på samma sätt, så configen kan inte stänga av P18-kontrollen.'),
    _n('runtime/ocr_pipeline.py', 'ocr_segments', 'ImportError',
       'tilldelning: TextSegment = None'):
        ('HANDLED',
         'Saknas document_text_extractor.TextSegment byggs segmenten som dict med samma fält (else-grenen nedan). Inget segment går förlorat.'),
    "runtime/consolidated_engine.py::_kör_alt_b::Exception::tilldelning: res[namn] = {'status': 'FEL', 'fel_typ': type(e).__name__, 'fel': f'{type(e).__name__}: {e}'}#0": ('REGISTERED_FAILURE', 'Ett fel i en begärd kategori C-modul skrivs in som status FEL med fel_typ och orsak på modulens nivå, samlas av _delfel() och ger analysnivå DELVIS. Övriga moduler körs vidare.'),
    'runtime/consolidated_engine.py::_vidarebefordra_legal_merge::FileNotFoundError::tilldelning: views = {}#0': ('HANDLED', 'Saknas presentation_views_v10.json initieras views till {} innan legal_merge-blocket skrivs.'),
    "runtime/consolidated_engine.py::consolidate::Exception::tilldelning: ny_svensvit = {'status': 'FEL', 'error_type': type(e).__name__, 'reason': str(e)}#0": ('REGISTERED_FAILURE', 'Felet skrivs in i resultatet som status FEL med error_type och orsak och följer med ut i rapporten.'),
    "runtime/consolidated_engine.py::consolidate::Exception::tilldelning: result.setdefault('alt_b', {})['strikt_rapport'] = {'status': 'FEL', 'fel_typ': type(e).__name__, 'fel': f'{type(e).__name__}: {e}'}#0": ('REGISTERED_FAILURE', 'Fel i den begärda strikta rapporten skrivs in som alt_b.strikt_rapport status FEL med fel_typ och orsak.'),
    'runtime/exception_census.py::inventera::Exception::continue#0': ('HANDLED', 'Oparsebar fil i inventeringen hoppas över med continue så övriga filer fortsätter inventeras.'),
}



# ── Steg 20: verifieringsgrind före juridisk output ──
KLASSIFICERING.update({
    "mcp/http_server.py::_verifieringsgrind_mw::Exception::tilldelning: ut = {'status': 'FAILED', 'kod': 'FAILED_VERIFIERING', 'output_blockerad': True, 'fel': f'verifieringsgrinden kunde inte köras: {type(e).__name__}: {e}'}#0":
        ('REGISTERED_FAILURE',
         'Steg 20: undantag i verifieringsgrinden ersätter HTTP-svaret med status FAILED, kod FAILED_VERIFIERING, output_blockerad=True och feltyp/orsak. Fail closed – ogrindat juridiskt utdata släpps aldrig.'),
    "mcp/server.py::call_tool::Exception::tilldelning: resultat = {'status': 'FAILED', 'kod': 'FAILED_VERIFIERING', 'verktyg': name, 'output_blockerad': True, 'fel': f'verifieringsgrinden kunde inte köras: {type(e).__name__}: {e}'}#0":
        ('REGISTERED_FAILURE',
         'Steg 20: undantag i verifieringsgrinden ersätter verktygssvaret med status FAILED, kod FAILED_VERIFIERING, output_blockerad=True och feltyp/orsak. Fail closed – ogrindat juridiskt utdata släpps aldrig.'),
    'runtime/legal_data_hunter_client.py::_bas_url::(OSError, ValueError)::pass#0':
        ('HANDLED',
         'Steg 20: oläsbar config/legal_data_hunter_se_config.json ger leverantörens dokumenterade bas-URL https://legaldatahunter.com/v1 (llms.txt). Påverkar bara adressen; varje anrop och fel redovisas ändå.'),
    "runtime/verifieringsgrind.py::RiksdagenKälla._hämta::Exception::tilldelning: fel = f'nätverksfel mot data.riksdagen.se: {type(e).__name__}: {e}'#0":
        ('REGISTERED_FAILURE',
         'Steg 20: nätverksfel mot data.riksdagen.se sparas i fel och prövas om (FÖRSÖK gånger); kvarstår felet höjs TekniskVerifieringsfel med exakt orsak och grinden ger FAILED (output blockeras).'),
})


KLASSIFICERING.update({
    "runtime/aktgranskning.py::_relativ_sökväg::ValueError::continue#0":
        ("HANDLED",
         "Steg 28: ValueError från Path.relative_to betyder att filen inte ligger under just den "
         "root_dir; nästa root_dir prövas och utan träff används filnamnet. Ingen fil går förlorad."),
})


# ── Steg 41: klassificering av handlers från steg36/38/40 ──
KLASSIFICERING.update({
    'integrations/n8n/riksdagen_sfs.py::_hamta::Exception::tilldelning: senaste = e#0':
        ('REGISTERED_FAILURE',
         'Steg38: nätverksfel mot data.riksdagen.se sparas och prövas om med backoff; kvarstår felet höjs RiksdagenFel med feltyp, orsak, URL och antal försök, och hänvisningen blir EJ_VERIFIERAD_KÄLLFEL i resultatet.'),
    'integrations/n8n/sfcae_mappanalys.py::_read_text_file::UnicodeDecodeError::continue#0':
        ('HANDLED',
         'Steg36: nästa teckenkodning prövas; efter sista försöket avkodas med latin-1/replace. Ingen fil blir tyst tom.'),
    'integrations/n8n/sfcae_mappanalys.py::_rtf::ImportError::pass#0':
        ('HANDLED',
         'Steg36: striprtf saknas -> inbyggd RTF-avkodning (nedan) används; metoden redovisas i resultatet.'),
    "integrations/n8n/sfcae_mappanalys.py::extrahera::Exception::tilldelning: r = {'text': '', 'metod': 'FEL', 'fel': f'{type(e).__name__}: {e}'}#0":
        ('REGISTERED_FAILURE',
         'Steg36: fel vid extraktion skrivs in per fil (metod FEL, feltyp och orsak) och filen listas som OLÄSBAR i rapporten.'),
    "integrations/n8n/sfcae_mappanalys.py::kor_pipeline::Exception::tilldelning: f = {'status': 'FEL', 'fel': f'{type(e).__name__}: {e}'}#0":
        ('REGISTERED_FAILURE',
         'Steg36: fel i SFCAE-pipelinen redovisas som status FEL med feltyp och orsak i resultat.json och sammanställningen.'),
    'integrations/n8n/sfcae_mappanalys.py::<modulnivå>::Exception::pass#0':
        ('HANDLED',
         'Steg36: CLI-läge; om stdout inte kan konfigureras om (ej TextIOWrapper) skrivs utdata ändå med standardkodningen.'),
    'mcp/server.py::_handle_pipeline_kedja::(OSError, TypeError)::tilldelning: rad = None#0':
        ('HANDLED',
         'Steg40: inspect hittar ingen källrad (inbyggd/C-funktion) -> rad redovisas uttryckligen som null; steget listas ändå.'),
    'mcp/server.py::_handle_verktygskarta::(OSError, TypeError)::tilldelning: fil, rad = (None, None)#0':
        ('HANDLED',
         'Steg40: inspect hittar ingen källfil -> fil/rad redovisas uttryckligen som null; verktyget listas ändå.'),
})


def klassificera(förekomster: List[Förekomst]) -> List[Tuple[Förekomst, str, str]]:
    """Parar ihop förekomster med sin klassificering."""
    ut = []
    for f in förekomster:
        post = KLASSIFICERING.get(f.nyckel)
        if post is None:
            ut.append((f, "UNKNOWN", "ingen post i registret"))
            continue
        klass, skäl = post
        ut.append((f, klass, skäl))
    return ut


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Exception-inventering för SFCAE")
    ap.add_argument("--alla", action="store_true", help="Visa varje förekomst")
    ap.add_argument("--oklassade", action="store_true",
                    help="Visa endast förekomster utan giltig klassificering")
    ap.add_argument("--analysvag", action="store_true",
                    help="Visa endast förekomster på analysvägen")
    a = ap.parse_args(argv)

    förekomster = inventera()
    parade = klassificera(förekomster)
    if a.analysvag:
        parade = [(f, k, s) for f, k, s in parade if f.på_analysvägen]
    if a.oklassade:
        parade = [(f, k, s) for f, k, s in parade if k == "UNKNOWN"]

    from collections import Counter
    antal = Counter(k for _, k, _ in parade)

    print("=" * 74)
    print(f"EXCEPTION-INVENTERING — {SIGNATUR}")
    print("=" * 74)
    print(f"  Förekomster totalt : {len(förekomster)}")
    print(f"  På analysvägen     : {sum(1 for f in förekomster if f.på_analysvägen)}")
    print("")
    for klass, n in antal.most_common():
        print(f"  {klass:<24s} {n:>3d}")
    print("")

    if a.alla or a.oklassade or a.analysvag:
        for f, klass, skäl in parade:
            märke = "!" if f.på_analysvägen else " "
            print(f" {märke}[{klass:<22s}] {f.fil}:{f.rad}")
            print(f"    funktion: {f.funktion}  |  fångar: {f.feltyp}  |  {f.kropp}")
            print(f"    {skäl}")
        print("")

    # Blockerande: oklassad eller BUG på analysvägen.
    blockerande = [(f, k) for f, k, _ in klassificera(förekomster)
                   if f.på_analysvägen and k in ("UNKNOWN", "BUG")]
    if blockerande:
        print(f"  BLOCKERANDE: {len(blockerande)} förekomster på analysvägen är "
              f"oklassade eller klassade BUG.")
        for f, k in blockerande:
            print(f"      [{k}] {f.fil}:{f.rad} ({f.funktion})")
        return 1
    print("  Analysvägens förekomster är samtliga klassificerade och inga BUG.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
