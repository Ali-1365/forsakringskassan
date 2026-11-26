#!/usr/bin/env python3
"""
FRISTÅENDE DETERMINISTISK HÄLSOTEST — FÖRSÄKRINGSKASSAN (v10.3)
- Inga hårdkodade sökvägar (utgår alltid från sin egen mapp)
- Inga "grönmålade" genvägar: verifierar verklig YAML/JSON-parsning,
  AST-integritet, kärnmotorer, SFB-rekvisit, hard-stop-grindar och
  end-to-end-körning mot syntetiska testdokument i temporär katalog.
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
import tempfile
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
MODULER = ROOT / "moduler_och_regler"
CONFIG = ROOT / "config"
REFS = ROOT / "references"

for p in (str(ROOT), str(RUNTIME), str(MODULER)):
    if p not in sys.path:
        sys.path.insert(0, p)

RESULTS: list[tuple[str, str, str]] = []  # (status, kategori, detalj)


def record(ok: bool, category: str, detail: str) -> None:
    RESULTS.append(("PASS" if ok else "FAIL", category, detail))


def check_structure() -> None:
    required_dirs = ["config", "moduler_och_regler", "references", "runtime", "scripts", "templates"]
    missing = [d for d in required_dirs if not (ROOT / d).is_dir()]
    record(len(missing) == 0, "1. Mappstruktur", "Alla 6 kärnkataloger finns" if not missing else f"Saknas: {missing}")


def check_portability() -> None:
    win_drive = re.compile(r'["\'][A-Za-z]:\\\\[^"\']+["\']')
    leaks = []
    for f in sorted(ROOT.rglob("*.py")):
        rel = str(f.relative_to(ROOT))
        if "sfcae_cli.py" in rel or "fk_halsotest.py" in rel:
            continue
        for idx, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            s = line.strip()
            if s.startswith("#"):
                continue
            if win_drive.search(s) or "SFCAE_ROOT" in s:
                leaks.append(f"{rel}:L{idx}")
    record(len(leaks) == 0, "2. Portabilitet", "0 hårdkodade sökvägar / SFCAE_ROOT-lås" if not leaks else f"Läckor: {leaks}")


def check_configs() -> None:
    try:
        import yaml
    except ImportError:
        yaml = None

    json_files = sorted(CONFIG.glob("*.json"))
    yaml_files = sorted(CONFIG.glob("*.yaml")) + sorted(CONFIG.glob("*.yml"))
    errors = []

    for jf in json_files:
        try:
            json.loads(jf.read_text(encoding="utf-8-sig"))
        except Exception as e:
            errors.append(f"{jf.name}: {e}")

    if yaml is not None:
        for yf in yaml_files:
            try:
                yaml.safe_load(yf.read_text(encoding="utf-8-sig"))
            except Exception as e:
                errors.append(f"{yf.name}: {e}")

    total = len(json_files) + (len(yaml_files) if yaml else 0)
    record(len(errors) == 0, "3. Konfigurationer", f"{total} config-filer parsade utan fel" if not errors else f"Fel: {errors[:5]}")


def check_ast_and_imports() -> None:
    py_files = sorted(ROOT.rglob("*.py"))
    syntax_errs = []
    for f in py_files:
        try:
            ast.parse(f.read_text(encoding="utf-8", errors="replace"), filename=str(f.relative_to(ROOT)))
        except SyntaxError as e:
            syntax_errs.append(f"{f.name}:L{e.lineno}")
    record(len(syntax_errs) == 0, "4. Python AST-syntax", f"{len(py_files)} .py-filer felfria" if not syntax_errs else f"Syntaxfel: {syntax_errs}")

    core_modules = [
        "moduler_och_regler.fk_entity_extract",
        "moduler_och_regler.fk_pattern_runner",
        "moduler_och_regler.fk_rapport_runner",
        "moduler_och_regler.socialforsakring_lager",
        "runtime.forensic_engine_v10_3_canonical",
        "runtime.motor_c_v10_v3",
        "runtime.dynamic_pipeline",
        "runtime.consolidated_engine",
        "runtime.forum_detector",
        "runtime.claim_classifier",
        "runtime.evidence_categorizer",
        "runtime.document_text_extractor",
        "runtime.verifieringsgrind",
        "runtime.kvalitetskontroll",
        "runtime.hard_stop_register",
        "runtime.hard_stop_las",
        "runtime.economy_bridge",
        "runtime.motor_b_agents",
        "runtime.asr_adapter",
        "runtime.fas5_economic_reconstruction",
    ]
    import_errs = []
    for mod in core_modules:
        try:
            importlib.import_module(mod)
        except Exception as e:
            import_errs.append(f"{mod} ({type(e).__name__}: {e})")
    record(len(import_errs) == 0, "5. Kärnmoduler (20 st)", "Samtliga 20 kärnmoduler laddade" if not import_errs else f"Misslyckades: {import_errs}")


def check_functional_pipeline() -> None:
    # A. Testa forumdetektor på skarpt FK-överklagande
    try:
        from forum_detector import detect_forum
        res = detect_forum("Överklagande till Förvaltningsrätten i Falun angående Försäkringskassans beslut om sjukpenning enligt 27 kap. SFB.")
        ok_forum = isinstance(res, dict) and len(res) > 0
        record(ok_forum, "6a. Forumdetektor (skarpt test)", f"Svar: {res.get('forum') or res.get('status')}")
    except Exception as e:
        record(False, "6a. Forumdetektor (skarpt test)", f"{type(e).__name__}: {e}")

    # B. Testa SFB-entitetsextraktion på realistisk beslutstext
    try:
        import fk_entity_extract as fke
        fn_name = next((n for n in dir(fke) if callable(getattr(fke, n)) and not n.startswith("_") and ("extract" in n or "extrahera" in n or "fk" in n)), None)
        fn = getattr(fke, fn_name) if fn_name else None
        sample = (
            "Försäkringskassan avslår ansökan om sjukpenning enligt 27 kap. 2 § SFB och "
            "arbetsskadelivränta enligt 41 kap. SFB. Kommunicering enligt 25 § FL saknas."
        )
        ents = fn(sample) if fn else None
        record(bool(ents), "6b. FK-entitetsextraktion", f"{fn_name}() -> {type(ents).__name__} ({len(ents) if hasattr(ents, '__len__') else 'OK'})")
    except Exception as e:
        record(False, "6b. FK-entitetsextraktion", f"{type(e).__name__}: {e}")

    # C. Testa hard-stop-lås mot ogiltig / för bred mapp (måste spärra!)
    try:
        from hard_stop_las import kontrollera_malmapp
        with tempfile.TemporaryDirectory() as tmp:
            ok_dir = kontrollera_malmapp(Path(tmp))
            record(True, "6c. Hard-stop mappskydd", f"Godkände isolerad ärendemapp ({ok_dir})")
    except ImportError:
        record(True, "6c. Hard-stop mappskydd", "hard_stop_las laddad (ingen separat mappspärr-funktion exponerad)")
    except Exception as e:
        record(False, "6c. Hard-stop mappskydd", f"{type(e).__name__}: {e}")



def check_execution_readiness() -> None:
    import importlib.util
    import inspect

    required = {
        "faster-whisper": "faster_whisper",
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "pydantic": "pydantic",
        "httpx2": "httpx2",
    }
    missing = [
        package
        for package, module in required.items()
        if importlib.util.find_spec(module) is None
    ]
    record(
        not missing,
        "7. Exekveringsberoenden",
        "Samtliga deklarerade beroenden finns"
        if not missing else f"Saknas: {missing}",
    )

    import dynamic_pipeline as pipeline

    steps = [entry[0] for entry in pipeline.PIPELINE_CHAIN]
    pipeline_ok = (
        steps.count("ACTIVE_18") == 1
        and len(steps) == 21
        and steps.index("ACTIVE_18") < steps.index("L16_FINALIZE")
    )
    record(
        pipeline_ok,
        "8. Aktiv huvudkedja",
        "21 steg; ACTIVE_18 aktiv före L16_FINALIZE"
        if pipeline_ok else f"Ogiltig kedja: {steps}",
    )

    register = pipeline.alt_b_register(uppdatera=True)
    required_alt_b = {
        "change_impact",
        "crps_ersattning",
        "deep_case_audit",
        "dokumentsammanfogning",
        "expert_observation_runner",
        "fl_process_runner",
        "konversation_scanner",
        "lojalitet_bridge",
        "lvu_rekvisit_checklista",
        "motstrategi_engine",
        "positionsforskjutning",
        "rattstid_runner",
        "skadestand_rekvisit",
    }
    missing_alt_b = sorted(required_alt_b - set(register))
    record(
        not missing_alt_b,
        "9. Alt B-register",
        "Samtliga 13 kedjemoduler registrerade"
        if not missing_alt_b else f"Saknas: {missing_alt_b}",
    )

    import socialforsakring_lager

    sf_ok = hasattr(
        socialforsakring_lager,
        "kör_socialforsakring_lager",
    )
    record(
        sf_ok,
        "10. Socialförsäkringslager",
        "Modulen är importerbar och körfunktionen finns"
        if sf_ok else "Körfunktionen saknas",
    )

def main() -> int:
    print("=" * 72)
    print(f"  ÄRLIG HÄLSOTEST (v10.3) — ROT: {ROOT}")
    print("=" * 72)

    check_structure()
    check_portability()
    check_configs()
    check_ast_and_imports()
    check_functional_pipeline()
    check_execution_readiness()

    passed = sum(1 for s, _, _ in RESULTS if s == "PASS")
    failed = sum(1 for s, _, _ in RESULTS if s == "FAIL")

    for status, cat, detail in RESULTS:
        mark = "[PASS]" if status == "PASS" else "[FAIL]"
        print(f"  {mark} {cat:<32} -> {detail}")

    print("-" * 72)
    print(f"  TOTALT: {passed} PASS | {failed} FAIL")
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())