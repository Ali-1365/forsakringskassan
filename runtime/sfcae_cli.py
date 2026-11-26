#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SFCAE — kommandoradsgränssnitt.

Enda avsedda vägen in i systemet för en operatör. Ärendet anvisas som argument
eller via miljövariabel; ingen Python-fil behöver någonsin redigeras för att
byta ärende.

    python sfcae_cli.py --case "D:\\Cases\\CASE-001" --output "D:\\Utdata\\CASE-001"
    python sfcae_cli.py --case "C:\\SFCAE\\Cases\\CASE-001" --output "C:\\SFCAE\\output"

Flera ärenderötter kan anges:

    python sfcae_cli.py --case "D:\\A" --case "D:\\B" --output "D:\\Utdata"

Utelämnas --output skrivs resultatet till ./output/<ärendenamn>_<tidsstämpel>
under aktuell katalog — aldrig i ärendemappen.

Exitkoder:
    0  Analysen kördes igenom.
    1  Analysen stoppades av ett fel (felet skrivs ut).
    2  Felaktig användning (ogiltig sökväg, saknat argument).
    3  Analysen kördes men motorn satte HARD STOP (se HARD STOP-koder).
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODULER_DIR = ROOT.parent / "moduler_och_regler"
if str(MODULER_DIR) not in sys.path:
    sys.path.insert(0, str(MODULER_DIR))

for _p in (ROOT / "runtime", ROOT / "integrations", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _standard_output_dir(case_roots) -> str:
    """Förvald outputmapp under aktuell katalog — aldrig i ärendet."""
    namn = os.path.basename(os.path.normpath(case_roots[0])) or "ARENDE"
    stämpel = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return str(Path.cwd() / "output" / f"{namn}_{stämpel}")


def _case_roots_från_miljö():
    """SFCAE_CASE_ROOTS som reservväg när --case utelämnas."""
    from case_paths import env_case_roots
    return env_case_roots()


def bygg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sfcae",
        description="SFCAE — Svensk Forensisk Court Audit Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ärendemappen får ligga på valfri volym. Inget i utvecklings-\n"
            "miljön behöver finnas för att köra ett ärende."
        ),
    )
    p.add_argument(
        "--case", "-c", action="append", metavar="SÖKVÄG", default=None,
        help="Ärendemapp. Kan anges flera gånger. "
             "Utelämnas den används SFCAE_CASE_ROOTS.",
    )
    p.add_argument(
        "--output", "-o", metavar="SÖKVÄG", default=None,
        help="Mapp för resultatet. Får aldrig ligga i ärendemappen.",
    )
    p.add_argument("--legal-rule", default="", help="Rättsregel att pröva mot (valfritt).")
    p.add_argument("--requisite", default="", help="Rekvisit att pröva mot (valfritt).")
    p.add_argument("--max-files", type=int, default=None, metavar="ANTAL",
                   help="Högsta antal filer i ärendet innan körningen vägras "
                        "(skydd mot felvald mapp). Standard 2000.")
    p.add_argument("--quiet", "-q", action="store_true",
                   help="Skriv endast slutsammanställningen.")
    p.add_argument("--skip-health", action="store_true",
                   help="Förbigå SYSTEM_HEALTH_TEST_2026-09-22 före analys.")
    p.add_argument("--check", action="store_true",
                   help="Kontrollera systemkrav och avsluta utan att köra analys.")
    p.add_argument("--version", action="store_true", help="Visa version och avsluta.")
    p.add_argument("--moduler", default="", metavar="LISTA",
                   help="Kommaseparerade Alt B-moduler att köra (requested=True): "
                        "steg13, legal_source_chain, motor_c, kallkedja, strikt_rapport.")
    return p


# Vägarna i document_text_extractor._extract_pdf_robust, i den ordning de
# provas, och vad var och en tillför.
PDF_KEDJA = (
    ("pdftotext",   None,           "snabbast, klarar de flesta PDF:er"),
    ("pypdf",       "pypdf",        "klarar en del som poppler missar"),
    ("pdfplumber",  "pdfplumber",   "tabeller och kolumnlayout"),
    ("fitz",        "fitz",         "skadade och ovanliga filer"),
    ("OCR",         "pytesseract",  "handlingar UTAN textlager"),
)

# Deklarerade beroenden i pyproject.toml, med modulnamn, pypi-namn och den
# kod som faktiskt importerar dem.
DEKLARERADE_PAKET = (
    ("yaml",        "pyyaml",      "config_loader"),
    ("pypdf",       "pypdf",       "document_text_extractor._pdf_pypdf"),
    ("pdfplumber",  "pdfplumber",  "document_text_extractor._pdf_pdfplumber"),
    ("fitz",        "PyMuPDF",     "_pdf_fitz och rastrering infor OCR"),
    ("PIL",         "Pillow",      "bildhantering i OCR-vagen"),
    ("pytesseract", "pytesseract", "OCR"),
    ("pdf2image",   "pdf2image",   "runtime/ocr_fallback.py"),
    ("faster_whisper", "faster-whisper",
     "runtime/asr_adapter.py:WhisperASR — utan den transkriberas inget ljud"),
    ("fastapi",     "fastapi",     "mcp/http_server.py, mcp/observability_api.py"),
    ("uvicorn",     "uvicorn",     "mcp/http_server.py (ASGI-server)"),
    ("pydantic",    "pydantic",    "mcp/http_server.py (request-modeller)"),
    ("httpx2",      "httpx2",      "mcp/http_server.py (krävs av starlette.testclient.TestClient)"),
)


def kontrollera_pdfkedjan():
    """
    Vilka av PDF-extraktionens fem vägar som faktiskt är tillgängliga.

    Kedjan degraderar tyst: varje väg rapporterar själv att dess bibliotek
    saknas, men bara i loggen för den enskilda handlingen. Saknas OCR läses
    inga skannade handlingar alls, och det märktes tidigare först när en sådan
    handling dök upp i en akt. Här syns det innan analysen börjar.
    """
    import importlib.util
    import shutil

    tillgängliga, saknade = [], []
    for namn, modul, _ in PDF_KEDJA:
        if modul is None:
            finns = shutil.which("pdftotext") is not None
        else:
            finns = importlib.util.find_spec(modul) is not None
        (tillgängliga if finns else saknade).append(namn)
    return tillgängliga, saknade


def kontrollera_systemkrav(skriv: bool = True):
    """
    Kontrollerar de krav som inte är Python-paket.

    pdftotext (poppler) är en extern binär som PDF-extraktionen anropar.
    Saknas den läses noll tecken ur varje PDF, och analysen får inget underlag
    att arbeta med. Det ska sägas innan körningen, inte upptäckas efteråt.
    """
    brister = []

    import shutil
    import subprocess

    pdftotext = shutil.which("pdftotext")
    pdftotext_körbar = False
    if pdftotext:
        # Att binären ligger på PATH räcker inte. En ofullständigt kopierad
        # poppler startar inte alls (saknade DLL:er ger 0xC0000135), och då
        # läses noll tecken ur varje PDF trots att kontrollen såg grön ut.
        # Därför provkörs den.
        #
        # Exitkoden duger INTE som kriterium: xpdf:s pdftotext avslutar med 99
        # efter "-v" trots att den fungerar, medan popplers avslutar med 0.
        # Det som skiljer en fungerande binär från en som inte startar är att
        # den faktiskt skriver ut sin version. En binär som inte kan laddas
        # ger ingen utskrift alls och en returkod i NTSTATUS-intervallet.
        try:
            r = subprocess.run([pdftotext, "-v"], capture_output=True,
                               timeout=15)
            utskrift = (r.stdout or b"") + (r.stderr or b"")
            startade = b"pdftotext" in utskrift.lower() or b"version" in utskrift.lower()
            kraschade = r.returncode >= 0xC0000000
            pdftotext_körbar = (startade or r.returncode == 0) and not kraschade
        except Exception:
            pdftotext_körbar = False

    if not pdftotext:
        brister.append(
            "pdftotext (poppler) saknas på PATH.\n"
            "       PDF-filer kan då inte läsas och analysen får inget underlag.\n"
            "       Windows: installera poppler och lägg dess bin-mapp i PATH,\n"
            "       t.ex. https://github.com/oschwartz10612/poppler-windows"
        )
    elif not pdftotext_körbar:
        brister.append(
            f"pdftotext hittades ({pdftotext}) men kunde inte köras.\n"
            "       Vanligaste orsaken är en ofullständig poppler-installation\n"
            "       där DLL-filerna saknas. Installera hela poppler-paketet,\n"
            "       inte bara pdftotext.exe."
        )

    # Varje deklarerat beroende provas. Tidigare kontrollerades endast
    # pyyaml, trots att PDF-kedjans fem vagar hanger pa ytterligare sex
    # paket. En installation utan dem laser inga skannade handlingar, och
    # det markes forst nar en sadan handling dyker upp i en akt.
    import importlib.util

    saknade_paket = [
        (pypi, konsument)
        for modul, pypi, konsument in DEKLARERADE_PAKET
        if importlib.util.find_spec(modul) is None
    ]
    if saknade_paket:
        rader = [
            f"       {pypi} - behovs av {konsument}"
            for pypi, konsument in saknade_paket
        ]
        brister.append(
            f"{len(saknade_paket)} deklarerade beroenden saknas:"
            + chr(10) + chr(10).join(rader) + chr(10)
            + "       Installera: python -m pip install -r requirements.txt"
        )

    # tesseract-binaren kan pip inte installera. Utan den lases inga
    # handlingar som saknar textlager.
    if shutil.which("tesseract") is None:
        brister.append(
            "tesseract saknas pa PATH."
            + chr(10) + "       Handlingar UTAN textlager kan da inte lasas."
            + chr(10) + "       https://github.com/UB-Mannheim/tesseract/wiki"
            + chr(10) + "       Installera aven sprakpaketet swe."
        )

    if skriv:
        if not pdftotext:
            pdf_status = "SAKNAS"
        elif pdftotext_körbar:
            pdf_status = pdftotext
        else:
            pdf_status = f"{pdftotext} (GÅR EJ ATT KÖRA)"
        print("[SFCAE] Systemkontroll:")
        print(f"  pdftotext (poppler) ....... {pdf_status}")
        try:
            import yaml
            print(f"  pyyaml .................... {yaml.__version__}")
        except ImportError:
            print("  pyyaml .................... SAKNAS")
        print(f"  Python .................... {sys.version.split()[0]}")

        tillgängliga, saknade = kontrollera_pdfkedjan()
        print(f"  PDF-extraktion ............ {len(tillgängliga)} av "
              f"{len(PDF_KEDJA)} vägar: {', '.join(tillgängliga) or 'ingen'}")
        if saknade:
            for namn, modul, syfte in PDF_KEDJA:
                if namn in saknade:
                    print(f"      saknas: {namn:<11s} ({modul}) — {syfte}")
            if "OCR" in saknade:
                print("      Handlingar UTAN textlager kan inte läsas.")
            print("      Installera med: pip install -r requirements.txt")
        print("")

    return brister


def skriv_sammanstallning(res: dict) -> None:
    """Redovisar det faktiska utfallet — aldrig ett påhittat godkännande."""
    def rad(etikett, värde):
        print(f"  {etikett:.<34} {värde}")

    print("")
    print("=" * 64)
    print("  SFCAE — RESULTAT")
    print("=" * 64)
    STATUSTEXT = {
        "A": "VERIFIERAT KORREKT", "B": "VERIFIERAD AVVIKELSE",
        "C": "VERIFIERAD PROCESSUELL AVVIKELSE", "D": "VERIFIERAD RÄTTSLIG AVVIKELSE",
        "E": "VERIFIERAD FAKTISK AVVIKELSE", "F": "VERIFIERAD BEVISMÄSSIG AVVIKELSE",
        "G": "POTENTIELLT RÄTTSLIGT RELEVANT", "H": "KAN INTE AVGÖRAS",
        "I": "OTILLRÄCKLIGT UNDERLAG",
    }
    status = res.get("overall_status") or "?"

    rad("Ärende-ID", res.get("case_id") or "—")
    rad("Motorversion", res.get("base_engine_version") or "—")
    rad("Sluttillstånd", res.get("final_state") or "—")
    rad("Slutstatus", f"{status} — {STATUSTEXT.get(status, 'OKÄND')}")
    print("")
    rad("Filer i akten", res.get("files_count", 0))
    rad("Påståenden (claims)", res.get("claims_count", 0))
    rad("Grafkanter", res.get("graph_edges_count", 0))
    if res.get("extraction_failed"):
        print("")
        print("  TEXTEXTRAKTION MISSLYCKADES")
        print(f"      {res.get('extraction_failed_reason')}")
        print("      Analysen saknar underlag. Åtgärda och kör om.")
    print("")
    rad("Identifierad måltyp", res.get("måltyp") or "okänd")
    rad("Tillförlitlighet", res.get("måltyp_confidence") or "INGEN")
    if res.get("måltyp_motivering"):
        print(f"      {res['måltyp_motivering']}")
    print("")
    rad("Rekvisitmatris", res.get("requisite_matrix_status") or "OKÄND")
    rad("Antal rekvisit", res.get("requisite_matrix_count", 0))

    koder = res.get("hard_stop_codes") or []
    rad("HARD STOP aktiv", "JA" if res.get("hard_stop") else "nej")
    if koder:
        rad("HARD STOP-koder", ", ".join(koder))

    forum = res.get("forum_detection") or {}
    rad("Forum", forum.get("forum") or forum.get("status") or "—")
    print("")
    rad("Analysnivå", res.get("analysnivå") or "—")
    for d in res.get("delfel") or []:
        print(f"      DELFEL {d.get('komponent')}: {d.get('status')}"
              + (f" — {d.get('skäl')}" if d.get("skäl") else ""))
    for namn, d in (res.get("alt_b") or {}).items():
        rad(f"Alt B {namn}", (d or {}).get("status", "—") if isinstance(d, dict) else "—")
    rad("Resultatmapp", res.get("output_dir") or "—")
    print("=" * 64)

    if res.get("requisite_matrix_status") in ("MÅLTYP_EJ_FASTSTÄLLD",
                                              "REKVISITDEFINITIONER_SAKNAS"):
        print("")
        print("  OBS: Ingen rekvisitmatris kunde byggas. Subsumtion är spärrad.")
        print("  Rekvisit för måltypen måste finnas i")
        print("  config/rekvisit_definitioner.yaml och författas av behörig jurist.")
    print("")
    print("  Resultatet är underlag. Juridisk bedömning görs av jurist.")
    print("")


def main(argv=None) -> int:
    args = bygg_parser().parse_args(argv)

    if args.version:
        print("SFCAE 10.3.0")
        return 0

    if args.check:
        brister = kontrollera_systemkrav(skriv=True)
        if brister:
            print("SYSTEMKRAV EJ UPPFYLLDA:", file=sys.stderr)
            for b in brister:
                print(f"  - {b}", file=sys.stderr)
            return 1
        print("  Alla systemkrav uppfyllda.")
        return 0

    case_roots = args.case or _case_roots_från_miljö()
    if not case_roots:
        print(
            "FEL: ingen ärendemapp angiven.\n"
            "     Ange --case \"<sökväg>\" eller sätt SFCAE_CASE_ROOTS.",
            file=sys.stderr,
        )
        return 2

    output_dir = args.output or _standard_output_dir(case_roots)

    # SYSTEM_HEALTH_TEST_2026-09-22 körs EN gång innan analys startar.
    # Systemet ska inte analysera ett ärende när hälsotestet fallerar.
    if not args.skip_health:
        import subprocess
        health_script = ROOT.parent / "scripts" / "fk_halsotest.py"
        if not health_script.is_file():
            print(f"FEL: hälsotestet saknas: {health_script}", file=sys.stderr)
            return 2
        health_run = subprocess.run(
            [sys.executable, "-B", str(health_script)],
            cwd=str(ROOT.parent),
            check=False,
        )
        if health_run.returncode != 0:
            print(
                f"FEL: hälsotestet fallerade med exitkod {health_run.returncode}",
                file=sys.stderr,
            )
            return health_run.returncode


    # Systemkrav kontrolleras före körning. Brister varnar men stoppar inte:
    # operatören kan ha skäl att köra ändå, och motorn sätter HS04 +
    # status I om inget underlag kunde läsas.
    for brist in kontrollera_systemkrav(skriv=not args.quiet):
        print(f"VARNING: {brist}", file=sys.stderr)

    if not args.quiet:
        print(f"[SFCAE] Ärende:  {', '.join(case_roots)}")
        print(f"[SFCAE] Utdata:  {output_dir}")
        print("")

    try:
        from consolidated_engine import consolidate
    except Exception as exc:
        print(f"FEL: kunde inte ladda motorn: {exc}", file=sys.stderr)
        return 1

    meta = None
    if args.legal_rule or args.requisite:
        meta = {"legal_rule": args.legal_rule, "requisite": args.requisite}
    moduler = [m.strip() for m in (args.moduler or "").split(",") if m.strip()]
    if moduler:
        meta = dict(meta or {})
        meta["begärda_moduler"] = moduler

    try:
        from consolidated_engine import MAX_FILER_DEFAULT
        # --case/--output är operatörens explicita anvisning = behörigheten
        # enligt case_paths (ärenden ligger aldrig i installationen).
        res = consolidate(list(case_roots), output_dir, meta,
                          max_filer=args.max_files or MAX_FILER_DEFAULT,
                          anvisade_rotter=list(case_roots) + [output_dir])
    except ValueError as exc:
        # Ogiltig sökväg, output i ärendemappen, saknad ärendemapp.
        print(f"FEL: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"FEL: analysen avbröts: {exc}", file=sys.stderr)
        return 1

    skriv_sammanstallning(res)
    # Ett hard stop är inte ett lyckat utfall — exitkoden får inte säga 0.
    if res.get("hard_stop"):
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
