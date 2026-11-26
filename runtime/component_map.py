#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KOMPONENTKARTA — roll och nåbarhet per fil.

Svarar på frågan "finns filen och används den?" med två SKILDA svar. En fil som
ligger på disk, indexeras eller laddas är inte därmed integrerad.

Kartan byggs ur den faktiska importgrafen från produktens verkliga ingångar
(sfcae_cli.py, gui_*.py, mcp/server.py) — inte ur en handskriven lista.

    python scripts/component_map.py                # sammanfattning
    python scripts/component_map.py --format json  # maskinläsbar
    python scripts/component_map.py --orphans      # bara onåbar runtime-kod

Klassificering per fil:
    ACTIVE_RUNTIME   nås från en ingång via importgrafen
    ENTRYPOINT       produktens ingångar
    CONFIG           config/*.yaml|json
    MCP              mcp/
    SKILL            SKILL.md i references/
    REFERENCE        övrigt under references/
    KNOWLEDGE        references/knowledge/
    TEST             tests/
    HEALTH_TEST      systemets enda hälsotest
    PACKAGING        paketerings- och byggskript
    DOCUMENTATION    *.md i roten och docs/
    PACKAGE_MARKER   __init__.py — markerar katalog som paket, ingen modul
    REQUIRES_REVIEW  ligger i installationen men är ännu inte granskat
    NOT_REACHABLE    .py som INTE nås från någon ingång
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Set

ROOT = Path(__file__).resolve().parent.parent

# api.py är ASGI-ingången (exponerar FastAPI-appen ur mcp/http_server.py) och
# klassificerades tidigare som NOT_REACHABLE enbart för att den saknades här.
# api/index.py är Vercel-ingången (vercel.json: builds/routes → api/index.py).
ENTRYPOINTS = ["sfcae_cli.py", "gui_advanced.py", "gui_tkinter.py",
               "mcp/server.py", "mcp/http_server.py", "api.py", "api/index.py"]

# Kataloger som ligger på sys.path i drift.
MODULKATALOGER = ["runtime", "integrations", "scripts", "mcp"]


# Kataloger i installationen som ännu inte är granskade. Innehållet är varken
# godkänt eller förkastat; det ska inte räknas som onåbar runtime-kod och får
# inte raderas innan någon fastställt vad det innehåller.
#
# Tom. sfcae-plugin/ låg här tills innehållet gåtts igenom fil för fil: 21
# exakta dubbletter, 21 äldre versioner av repots filer, tre äldre
# motorgenerationer och 17 dokument som redan fanns i references/knowledge/.
# Det enda unika — counter-audit-agent.md — ligger nu i
# references/knowledge/architecture/. Resten är arkiverat utanför
# installationen. Posten ska inte bli en permanent parkering: varje rad här
# ska drivas mot BEHÅLL, FLYTTA, ARKIVERA eller TA BORT.
#
# Posterna nedan är genomgångna men saknar ett beslut som bara användaren kan
# fatta (radering är inte tillåten utan beslut). De parkeras här med skäl i
# stället för att redovisas som onåbar runtime-kod.
UNDER_GRANSKNING: Dict[str, str] = {
    "analyze_active_files.py":
        "PARKERAD: engångsanalysskript (commit 0fec8c1) som skriver "
        "analysis_output/active_files_analysis.json; ingen produktfunktion "
        "— beslut ARKIVERA/TA BORT kräver användaren",
    "show_results.py":
        "PARKERAD: läser analysis_output/active_files_analysis.json från "
        "analyze_active_files.py (commit 0fec8c1); ingen produktfunktion "
        "— beslut ARKIVERA/TA BORT kräver användaren",
    "system_health_sentinel.py":
        "PARKERAD: fristående, chr()-kodat diagnostikskript som öppnar en "
        "socket mot 127.0.0.1:20128; ingen anropare — beslut kräver användaren",
    "runtime/integration_resolver.py":
        "PARKERAD: parallell integrationsorkestrerare utan produktionsanropare. "
        "Laddar sedan steg 25 ingen arkivkod: robust_mahoor_system ersatt av "
        "aktiva runtime/mahoor_analys.py. Funktionella motsvarigheter "
        "finns i kanoniska vägen: jurisdiction_adapter via dynamic_pipeline "
        "(steg JURISDICTION), fk_entity_extract via fk_pattern_runner. "
        "Inkoppling vore en andra orkestreringsväg — beslut kräver användaren",
    "runtime/mahoor_analys.py":
        "PARKERAD (steg 25): aktiv, enda versionen av robust_mahoor_system "
        "(run_mahoor_analysis). Enda konsument är den parkerade "
        "runtime/integration_resolver.py; delarna (kodsystem_scanner RB_HOVRATT, "
        "konversation_scanner, yttrande_generator) nås redan från ingångarna. "
        "Inkoppling i produktionsvägen följer beslutet om integration_resolver "
        "- beslut kräver användaren",
}


def _modulindex() -> Dict[str, Path]:
    index: Dict[str, Path] = {}
    for katalog in MODULKATALOGER:
        d = ROOT / katalog
        if not d.is_dir():
            continue
        for f in d.rglob("*.py"):
            index.setdefault(f.stem, f)
    return index


def _importerade_namn(path: Path) -> Set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    namn: Set[str] = set()
    for nod in ast.walk(tree):
        if isinstance(nod, ast.Import):
            for a in nod.names:
                namn.add(a.name.split(".")[0])
                namn.add(a.name.split(".")[-1])
        elif isinstance(nod, ast.ImportFrom) and nod.module:
            namn.add(nod.module.split(".")[0])
            namn.add(nod.module.split(".")[-1])
        elif isinstance(nod, ast.Call):
            # importlib.import_module("modul") och spec_from_file_location
            for arg in nod.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    v = arg.value
                    if v.endswith(".py"):
                        namn.add(Path(v).stem)
                    elif v.isidentifier():
                        namn.add(v)
    return namn


def nåbara_moduler() -> Set[str]:
    """Transitiv hölje av importer från produktens ingångar."""
    index = _modulindex()
    kö: List[str] = []
    for ep in ENTRYPOINTS:
        p = ROOT / ep
        if p.is_file():
            kö.append(p.stem)
    nådda: Set[str] = set(kö)
    medan = list(kö)
    # En ingång utanför modulkatalogerna (t.ex. api/index.py) följs via sin
    # egen sökväg, inte via ett antaget ROOT/<namn>.py.
    ep_vägar = {(ROOT / ep).stem: ROOT / ep for ep in ENTRYPOINTS}
    while medan:
        namn = medan.pop()
        path = index.get(namn) or ep_vägar.get(namn) or (ROOT / f"{namn}.py")
        if not path.is_file():
            continue
        for ref in _importerade_namn(path):
            if ref in index and ref not in nådda:
                nådda.add(ref)
                medan.append(ref)
    return nådda


def klassificera() -> List[Dict]:
    nådda = nåbara_moduler()
    ep_stems = {Path(e).stem for e in ENTRYPOINTS}
    rader: List[Dict] = []

    for f in sorted(ROOT.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(ROOT).as_posix()
        # .kilo/ är, liksom .claude/, agentverktygens katalog: worktrees är
        # separata git-utcheckningar och skills/ är operatörens egna verktyg.
        # Inget där är installationens kod.
        # docs/checkpoints/ = arkiv; .pytest_temp/ = pytests basetemp (gitignored).
        if rel.startswith((".git/", ".claude/", ".kilo/", "output/", ".venv/",
                           "docs/checkpoints/", "docs/bevis/", ".pytest_temp/")) or "__pycache__" in rel:
            continue

        # __init__.py är en paketmarkör, inte en modul. Den har per
        # definition ingen importväg från en ingång och ska inte räknas som
        # onåbar runtime-kod.
        if f.name == "__init__.py":
            kat, nås = "PACKAGE_MARKER", "markerar katalogen som paket"
            rader.append({"fil": rel, "kategori": kat, "nås_via": nås})
            continue

        # Material som ligger i installationen men ännu inte är granskat.
        # Det klassificeras uttryckligen i stället för att räknas som onåbar
        # runtime-kod — annars blockerar det analysen och skapar tryck att
        # radera sådant vars innehåll ingen ännu prövat.
        if any(rel.startswith(pre) for pre in UNDER_GRANSKNING):
            kat, nås = "REQUIRES_REVIEW", UNDER_GRANSKNING[
                next(pre for pre in UNDER_GRANSKNING if rel.startswith(pre))]
            rader.append({"fil": rel, "kategori": kat, "nås_via": nås})
            continue

        if "SYSTEM_HEALTH_TEST" in f.name:
            kat, nås = "HEALTH_TEST", "sfcae_cli.py före analys"
        elif rel.startswith("tests/"):
            kat, nås = "TEST", "pytest"
        elif rel.startswith("config/") and f.suffix in (".yaml", ".yml", ".json", ".md"):
            kat, nås = "CONFIG", "config_loader (dynamisk scanning)"
        elif rel.startswith("references/knowledge/"):
            kat, nås = "KNOWLEDGE", "knowledge_loader"
        elif f.name == "SKILL.md" and rel.startswith("references/"):
            kat, nås = "SKILL", "dynamic_execution_bridge index/resolve"
        elif rel.startswith("references/"):
            kat, nås = "REFERENCE", "resource_loader / skill_reference_loader"
        elif rel.startswith("scripts/") and f.suffix == ".py" and f.stem not in nådda:
            kat, nås = "PACKAGING", "körs manuellt vid bygge"
        elif rel.startswith("mcp/"):
            kat, nås = "MCP", "mcp/server.py"
        elif f.suffix == ".py":
            if f.stem in ep_stems:
                kat, nås = "ENTRYPOINT", "startas av operatör"
            elif f.stem in nådda:
                kat, nås = "ACTIVE_RUNTIME", "importgraf från ingång"
            elif _är_utvecklingsartefakt(rel, f.name):
                kat, nås = "DEV_ARTIFACT", _utvecklingsartefakt_skäl(rel, f.name)
            else:
                kat, nås = "NOT_REACHABLE", "ingen importväg från någon ingång"
        elif f.suffix == ".md":
            kat, nås = "DOCUMENTATION", "läses av människa"
        else:
            kat, nås = "OTHER", "-"

        rader.append({"fil": rel, "kategori": kat, "nås_via": nås})
    return rader


# ── Generell klassificering av utvecklingsartefakter ────────────────────────
#
# Tidigare klassificerades varje .py som inte nås från en ingång som
# NOT_REACHABLE, vilket systemhälsokontrollen i SYSTEM_HEALTH_TEST_2026_09_22
# rapporterade som en brist ("oväntat onåbara"). Det blockrade GUI-starten
# när temporära probe-skript, verifieringsrunners och engångsskript låg i
# installationen.
#
# Detta är fel klassificering: en temporär probe eller verifieringsrunner är
# utvecklingsmaterial, inte en onåbar produktionsmodul. Den ska inte blockera
# GUI-starten eller systemhälsokontrollen.
#
# Regeln är generell — den hårdkodar inte specifika filnamn. Den känner
# av mönster i sökväg och filnamn som utmärker utvecklingsartefakter:
#   - *_probe*, *_probe_*.py  (diagnostik-prober)
#   - *_evidence*, *_evidence_*.py (bevisrunners)
#   - *_runner*.py, *_runner_*.py
#   - *_test*.py (utom i tests/-katalogen som redan klassificerats)
#   - *_verify*.py, *_verify_*.py
#   - *_tmp*.py, _tmp_*.py, *_tmp_*.py
#   - *.bak, *.ps1, *.txt, *.json (icke-kod)
#   - skript som importeras av pytest-samling (tests/) eller av
#     verify_cases_entrypoint.py
#
# En VERKTLIG onåbar produktionsmodul (t.ex. runtime/skill_orchestrator.py)
# klassificeras fortfarande som NOT_REACHABLE och blockerar kontrollen. Den
# här regeln exkluderar endast filer som verifierbart ligger utanför
# produktionsmodulernas kontrakt.
_DEV_ARTIFACT_PATTERNS = (
    "_probe_",
    "_evidence",
    "_runner",
    "_verify",
    "_tmp",
    "verify_cases_entrypoint",
    # verify_producent_konsument_kedja.py börjar med "verify_" (ingen
    # inledande underscore), och _pkk_debug_output*.py är diagnostik-prober
    # som inte matchar något av ovanstående mönster. Båda är
    # utvecklingsartefakter — verifieringsrunners som körs manuellt, inte
    # runtime-moduler som importeras från en ingång.
    "verify_",
    "_pkk_debug",
)


def _är_utvecklingsartefakt(rel: str, name: str) -> bool:
    """Returnerar True om filen är en utvecklingsartefakt (probe, verifiering,
    engångsskript) och inte en produktionsmodul."""
    lower = name.lower()
    stem = Path(name).stem.lower()
    if any(p in stem for p in _DEV_ARTIFACT_PATTERNS):
        return True
    # Skript som heter *_test*.py utanför tests/-katalogen är regressionstester
    # som körs manuellt, inte runtime-moduler.
    if "_test" in stem and not rel.startswith("tests/"):
        return True
    return False


def _utvecklingsartefakt_skäl(rel: str, name: str) -> str:
    """Kort skäl till varför filen klassificeras som utvecklingsartefakt."""
    return (
        f"utvecklingsartefakt (temporär probe/verifieringsrunner/engångsskript); "
        f"ingen produktionsanropare — ska inte räknas som onåbar runtime-kod"
    )


# Konfigurationer som medvetet INTE konsumeras av runtime, med skäl.
# Varje post är ett uttryckligt ställningstagande — inte en glömd fil.
KONFIG_EJ_RUNTIME = {
    "settings": "Editorinställningar (cSpell), inte systemkonfiguration.",
    "pipeline_fsm": "Märkt i filen: '[DEPRECATED som runtime-sanning] ... "
                    "dokumentation — parsas ej'.",
    "deep_legal_case_auditor": "Speckontrakt enligt filhuvudet, inte FSM eller "
                               "runtimekonfiguration.",
    "ai_vortex_risk_framework": "JSON-schema, inte konfiguration. "
                                "ai_risk_scanner läser ai_risk_config.yaml.",
    "puh-openapi": "OpenAPI-specifikation, referensmaterial.",
    "legal_data_hunter_se_config": "Extern nätverksleverantör. Nätanrop är "
                                   "avstängda som standard.",
    "audio_forensics": "Ljudforensik. Ingen ljudmodul finns i runtime; ljud "
                       "hanteras som EJ_TEXTBÄRANDE.",
    "hyresratt_gap_templates": "Mallar för lokalhyrestvist — domänen är inte "
                               "verifierad mot verkligt material.",
    "advocacy_config": "Advocacy-modulerna är Alt B och anropas via MCP, inte "
                       "från den kanoniska pipelinen.",
    "legal_ai_core_config": "Speckontrakt i Markdown. Implementerat i kod — "
                            "consolidated_engine (forum + rekvisit-modal-DSL) "
                            "och duel_engine §5 anger den som ursprung. "
                            "Läses inte vid körning.",
    "source_separation": "Källseparationsmanifest. Den katalog den utesluter "
                         "('external') finns inte i produkten, och ärendescopet "
                         "anvisas numera vid körning via --case/SFCAE_CASE_ROOTS.",
}

# Konfigurationer som hittas dynamiskt vid körning, inte via namn i koden.
KONFIG_DYNAMISKA = ("kodsystem_",)


def konfigurationsstatus() -> List[Dict]:
    """Roll och konsument per konfigurationsfil."""
    import re as _re

    kod = []
    for d in MODULKATALOGER:
        for f in (ROOT / d).rglob("*.py"):
            try:
                kod.append((f.relative_to(ROOT).as_posix(), f.read_text(encoding="utf-8")))
            except Exception as e:
                # En oläsbar fil utelämnades tyst ur kartan, som därmed kunde
                # beskriva systemet som mindre än det är.
                print(
                    f"[COMPONENT_MAP] KAN EJ LÄSAS: {f} — {type(e).__name__}: {e}",
                    file=sys.stderr,
                )

    rader = []
    for p in sorted((ROOT / "config").glob("*")):
        if p.suffix not in (".yaml", ".yml", ".json", ".md"):
            continue
        nyckel = p.stem
        # Endast FAKTISKA konfigurationsanrop räknas som konsumtion:
        # ladda("nyckel") eller filnamnet med ändelse. Enbart strängen
        # "settings" någonstans i koden är inte konsumtion av settings.json.
        nk = _re.escape(nyckel)
        mönster = _re.compile(
            rf'ladda\(\s*["\']{nk}["\']|'          # config_loader.ladda("x")
            rf'["\'][^"\']*{nk}\.(?:yaml|yml|json|md)["\']'  # "x.yaml"
        )
        konsumenter = [namn for namn, txt in kod if mönster.search(txt)]
        if any(nyckel.startswith(d) for d in KONFIG_DYNAMISKA):
            status, not_ = "DYNAMISKT UPPTÄCKT", \
                "kör_rättsområdesskanning() scannar config/kodsystem_*"
        elif konsumenter:
            status, not_ = "AKTIV", ", ".join(sorted(set(konsumenter))[:3])
        elif nyckel in KONFIG_EJ_RUNTIME:
            status, not_ = "EJ RUNTIME (klassificerad)", KONFIG_EJ_RUNTIME[nyckel]
        else:
            status, not_ = "OKLASSIFICERAD", "ingen konsument, inget beslut"
        rader.append({"konfig": p.name, "status": status, "not": not_})
    return rader


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Komponentkarta för SFCAE")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    ap.add_argument("--orphans", action="store_true",
                    help="Visa endast runtime-moduler utan importväg")
    ap.add_argument("--configs", action="store_true",
                    help="Visa roll och konsument per konfigurationsfil")
    a = ap.parse_args(argv)

    if a.configs:
        rader = konfigurationsstatus()
        from collections import Counter
        antal = Counter(r["status"] for r in rader)
        print("=" * 72)
        print("KONFIGURATIONER — roll och konsument")
        print("=" * 72)
        for s, n in antal.most_common():
            print(f"  {s:<28s} {n:>3d}")
        print("")
        for r in rader:
            if r["status"] != "AKTIV":
                print(f"  {r['konfig']:<42s} {r['status']}")
                print(f"      {r['not']}")
        oklass = [r for r in rader if r["status"] == "OKLASSIFICERAD"]
        print("")
        print(f"  OKLASSIFICERADE: {len(oklass)}")
        return 0 if not oklass else 1

    rader = klassificera()

    if a.format == "json":
        print(json.dumps(rader, ensure_ascii=False, indent=2))
        return 0

    if a.orphans:
        föräldralösa = [r for r in rader if r["kategori"] == "NOT_REACHABLE"]
        print(f"RUNTIME-MODULER UTAN IMPORTVÄG FRÅN NÅGON INGÅNG: {len(föräldralösa)}")
        for r in föräldralösa:
            print(f"  {r['fil']}")
        return 0

    from collections import Counter
    antal = Counter(r["kategori"] for r in rader)
    print("=" * 66)
    print("KOMPONENTKARTA — roll och nåbarhet")
    print("=" * 66)
    print(f"  Totalt filer: {len(rader)}")
    print("")
    for kat, n in antal.most_common():
        print(f"  {kat:<16s} {n:>4d}")
    print("")
    ej = [r["fil"] for r in rader if r["kategori"] == "NOT_REACHABLE"]
    if ej:
        print(f"  NOT_REACHABLE ({len(ej)}) — .py utan importväg från ingång:")
        for f in ej:
            print(f"      {f}")
    print("=" * 66)
    print("  Nåbarhet är inte detsamma som verifierad funktion.")
    print("  Kategorin säger var filen hör hemma, inte att den gör rätt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
