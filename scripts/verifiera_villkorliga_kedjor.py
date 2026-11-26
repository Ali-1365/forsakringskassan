import sys
import inspect
import importlib
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "runtime"))
sys.path.insert(0, str(root / "integrations"))

found = []
for d in [root / "runtime", root / "integrations"]:
    if not d.exists():
        continue
    for py in d.glob("*.py"):
        try:
            mod = importlib.import_module(py.stem)
            for name, func in inspect.getmembers(mod, inspect.isfunction):
                if name.startswith("run_") and name.endswith("_if_requested"):
                    found.append((d.name, py.stem, name, func))
        except Exception as exc:
            verifiera_villkorliga_import_error = f"{type(exc).__name__}: {exc}"

lines = ["="*80, f"SFCAE ALT B BATCHVERIFIERING (Totalt hittade: {len(found)})", "="*80]

for mapp, modul, fn, func in found:
    sig = inspect.signature(func)
    kwargs = {}
    for p in sig.parameters:
        if p == "requested":
            kwargs[p] = False
        elif p in ("verdict", "result", "state", "pipeline_state"):
            kwargs[p] = {"case_id": "TEST"}
        elif p in ("output_path", "out_path", "path"):
            kwargs[p] = "test.tmp"
        else:
            kwargs[p] = None

    try:
        res = func(**kwargs)
        lines.append(f"[{mapp:<12}] {modul:<30} | {fn:<35} RESULTAT: OK ({res})")
    except Exception as e:
        lines.append(f"[{mapp:<12}] {modul:<30} | {fn:<35} RESULTAT: FEL ({e})")

out = "\n".join(lines)
print(out)
(root / "verifiering_alt_b_resultat.txt").write_text(out, encoding="utf-8")
