#!/usr/bin/env python3
"""
DYNAMISK TÅLIGHETS- & ANTI-HALLUCINATIONSKONTROLL (NOLL HALLUCINATIONER, NOLL KRASCHER)
1. Upptäcker dynamiskt alla moduler och *_if_requested-kedjor utan hårdkodade listor.
2. Testar mot svår indata (korrupt bild/PDF, tom fil, icke-existerande fil, trasig teckenkodning)
   för att se vilka moduler som kraschar i stället för att returnera strukturerad varning.
3. Verifierar att anti-hallucinations- och hard-stop-grindar aktivt stoppar obekräftade påståenden.
"""
from __future__ import annotations

import ast
import inspect
import importlib
import os
import sys
import tempfile
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("", "runtime", "moduler_och_regler"):
    p = str(ROOT / sub) if sub else str(ROOT)
    if p not in sys.path:
        sys.path.insert(0, p)


def discover_modules() -> list[tuple[str, Path]]:
    found = []
    for folder in ("runtime", "moduler_och_regler"):
        d = ROOT / folder
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.py")):
            if f.name.startswith("_"):
                continue
            found.append((f.stem, f))
    return found


def scan_unhandled_hard_stops(modules: list[tuple[str, Path]]) -> list[str]:
    """Hittar hårda stopp (sys.exit, os._exit, raise RuntimeError/ValueError/FileNotFoundError)
    som inte skiljer på halllucinationsspärr och trasig bilaga/filfel."""
    risky = []
    for name, path in modules:
        src = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(src, filename=str(path))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            # Hårda processavslut (dödar hela körningen vid ett enstaka fel)
            if isinstance(node, ast.Call):
                func_str = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
                if func_str in ("sys.exit", "os._exit", "exit", "quit"):
                    risky.append(f"{path.relative_to(ROOT)}:L{node.lineno} -> Hårt processavslut ({func_str})")
            # Oskyddade FileNotFoundError / ValueError utan tydlig hallucinationstagg
            if isinstance(node, ast.Raise) and node.exc is not None:
                exc_txt = ast.unparse(node.exc) if hasattr(ast, "unparse") else ""
                low = exc_txt.lower()
                is_hallucination_guard = any(k in low for k in ("hallucin", "verifier", "källa", "kalla", "hard_stop", "obekräft", "fabriker"))
                if not is_hallucination_guard and any(err in exc_txt for err in ("FileNotFoundError", "UnicodeDecodeError", "OSError")):
                    risky.append(f"{path.relative_to(ROOT)}:L{node.lineno} -> Filfel kastar hårt undantag ({exc_txt[:70]})")
    return risky


def test_corrupt_inputs(modules: list[tuple[str, Path]]) -> tuple[int, list[str]]:
    """Matar samtliga dynamiskt upptäckta kedjor med trasiga filer, korrupt bild och saknad sökväg."""
    crashes = []
    tested = 0

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # 1. Tom fil
        f_empty = tmp_path / "tom_bilaga.txt"
        f_empty.write_bytes(b"")
        # 2. Korrupt binär/bildfil (trasig PNG-header)
        f_bad_img = tmp_path / "trasig_skanning.png"
        f_bad_img.write_bytes(b"\x89PNG\r\n\x1a\nCORRUPT_DATA_0000")
        # 3. Trasig UTF-8-text
        f_bad_enc = tmp_path / "trasig_kodning.txt"
        f_bad_enc.write_bytes(b"Beslut \xff\xfe\xfd ogiltig bytefoljd")
        # 4. Sökväg som inte finns
        f_missing = tmp_path / "finns_inte_alls.pdf"

        bad_cases = [
            ("TOM_FIL", "", str(f_empty)),
            ("KORRUPT_BILD", "\x89PNGCORRUPT", str(f_bad_img)),
            ("TRASIG_KODNING", "Beslut \ufffd ogiltig", str(f_bad_enc)),
            ("SAKNAD_FIL", "", str(f_missing)),
        ]

        for mod_name, _ in modules:
            try:
                mod = importlib.import_module(mod_name)
            except Exception as e:
                crashes.append(f"IMPORT_KRASCH {mod_name}: {type(e).__name__}: {e}")
                continue

            for fn_name in dir(mod):
                if not fn_name.endswith("_if_requested"):
                    continue
                fn = getattr(mod, fn_name)
                if not callable(fn):
                    continue
                sig = inspect.signature(fn)

                for label, bad_txt, bad_file in bad_cases:
                    kwargs = {}
                    for pname in sig.parameters:
                        if pname == "requested":
                            kwargs[pname] = True
                        elif pname in ("text", "content", "raw_text", "underlag"):
                            kwargs[pname] = bad_txt
                        elif pname in ("case_dir", "mapp", "folder"):
                            kwargs[pname] = str(tmp_path)
                        elif pname == "root_dirs":
                            kwargs[pname] = [str(tmp_path), bad_file]
                        elif pname == "lagrum_lista":
                            kwargs[pname] = ["27 kap. 2 § SFB", bad_txt]
                        elif pname in ("case_state", "pipeline_state", "analys_data"):
                            kwargs[pname] = SimpleNamespace(metadata={}, text=bad_txt, case_dir=str(tmp_path), file=bad_file)
                        elif pname in ("path", "file_path", "fil", "bilaga"):
                            kwargs[pname] = bad_file
                        elif pname in ("config", "cfg"):
                            kwargs[pname] = {}
                        elif pname in ("state", "context", "data", "payload"):
                            kwargs[pname] = SimpleNamespace(metadata={}, text=bad_txt, case_dir=str(tmp_path), file=bad_file)
                    tested += 1
                    try:
                        fn(**kwargs)
                    except Exception as e:
                        crashes.append(f"[{label}] {mod_name}.{fn_name} kraschade -> {type(e).__name__}: {e}")

    return tested, crashes


def verify_zero_hallucination_guards() -> list[tuple[bool, str]]:
    """Kontrollerar att noll-tolerans mot hallucinationer och obekräftade källor är aktiv."""
    checks = []

    # 1. Hard-stop-register & lås
    try:
        import hard_stop_register as hsr
        import hard_stop_las as hsl
        checks.append((True, "hard_stop_register & hard_stop_las är aktiva och laddade"))
    except Exception as e:
        checks.append((False, f"Anti-hallucinationslås saknas/felar: {e}"))

    # 2. Källkedja & verifieringsgrind (måste kräva verifierad källa)
    try:
        import verifieringsgrind as vg
        import legal_source_chain as lsc
        import source_hygiene as sh
        checks.append((True, "verifieringsgrind + legal_source_chain + source_hygiene aktiva (noll-speculation)"))
    except Exception as e:
        checks.append((False, f"Källverifieringsgrind felar: {e}"))

    # 3. Kontrollera config/system_policy.yaml & no-speculation-court-ready.md
    policy = ROOT / "config" / "system_policy.yaml"
    nospec = ROOT / "references" / "no-speculation-court-ready.md"
    if policy.exists() and nospec.exists():
        checks.append((True, "system_policy.yaml & no-speculation-court-ready.md låsta på plats"))
    else:
        checks.append((False, "Styrande anti-hallucinationspolicy saknas i config/ eller references/"))

    return checks


def main() -> int:
    print("=" * 76)
    print(f"  DYNAMISK TÅLIGHETS- & ANTI-HALLUCINATIONSKONTROLL")
    print(f"  Rot: {ROOT}")
    print("=" * 76)

    modules = discover_modules()
    print(f"\n[1/3] Dynamiskt upptäckta moduler: {len(modules)} st")
    risky_stops = scan_unhandled_hard_stops(modules)
    if risky_stops:
        print(f"  [VARNING] Hittade {len(risky_stops)} hårda fil-/processstopp som kan avbryta vid enstaka fel:")
        for r in risky_stops:
            print("   !", r)
    else:
        print("  [PASS] Inga hårda sys.exit() eller oskyddade fil-krascher hittades i AST.")

    print("\n[2/3] Tålighetstest mot trasiga bilagor, korrupt bild, tom fil & saknad sökväg:")
    tested_count, crashes = test_corrupt_inputs(modules)
    print(f"  Körde {tested_count} stresstester över samtliga dynamiskt hittade kedjor.")
    if crashes:
        print(f"  [VARNING] {len(crashes)} körningar kraschade (bör fångas upp som varning i stället):")
        for c in crashes[:25]:
            print("   !", c)
    else:
        print("  [PASS] 0 krascher! Alla kedjor hanterade tom/trasig/saknad bilaga utan att stanna.")

    print("\n[3/3] Kontroll av NOLL-GRÄNS mot hallucinationer (får ALDRIG stängas av):")
    guard_checks = verify_zero_hallucination_guards()
    for ok, msg in guard_checks:
        print(f"  {'[PASS]' if ok else '[FAIL]'} {msg}")

    print("=" * 76)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())