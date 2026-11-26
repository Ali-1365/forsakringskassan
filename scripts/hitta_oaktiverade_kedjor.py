"""
Statisk AST-genomsökning av runtime/ och integrations/.
Identifierar filer utan känd statisk import- eller dynamisk registreringskoppling
till kärnan (dynamic_pipeline.py, consolidated_engine.py, mcp/server.py,
mcp/http_server.py, aktgranskning.py).

Ingen pipeline körs. Ingen kod exekveras.
Skriver resultatet till oaktiverade_kedjor_rapport.txt i projektets rot.
"""
from __future__ import annotations
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIRS = [ROOT / "runtime", ROOT / "integrations"]

# ── 1. Samla alla .py-filer (exkl. __pycache__) ──────────────────────────────
py_files: list[Path] = []
for d in DIRS:
    py_files += [p for p in d.rglob("*.py") if "__pycache__" not in str(p)]

# ── 2. Alla modul-namn importerade av dessa filer själva (peer-imports) ───────
imported_names: set[str] = set()
for p in py_files:
    try:
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_names.add(node.module.split(".")[0])
    except Exception as exc:
        hitta_oaktiverade_import_error = f"{type(exc).__name__}: {exc}"

# ── 3. Dynamiska loader-anrop (_load("sfcae_X", "runtime/foo.py")) ───────────
ENTRYPOINTS = [
    ROOT / "runtime"       / "dynamic_pipeline.py",
    ROOT / "integrations"  / "consolidated_engine.py",
    ROOT / "mcp"           / "server.py",
    ROOT / "mcp"           / "http_server.py",
    ROOT / "runtime"       / "aktgranskning.py",
]

dynamic_refs: set[str] = set()
for ef in ENTRYPOINTS:
    if not ef.exists():
        continue
    txt = ef.read_text(encoding="utf-8", errors="replace")
    # _load("sfcae_XX", "runtime/modul.py")  →  "modul"
    for m in re.findall(
        r'''_load\s*\(\s*["'][^"']+["']\s*,\s*["'](?:runtime|integrations)/([^"'/]+)\.py["']''',
        txt,
    ):
        dynamic_refs.add(m)
    # from modul import …  /  import modul
    dynamic_refs.update(re.findall(r"from\s+([\w_]+)\s+import", txt))
    dynamic_refs.update(re.findall(r"^import\s+([\w_]+)", txt, re.MULTILINE))
    # try: from X import  (lazy imports inuti funktioner)
    dynamic_refs.update(re.findall(r"from\s+([\w_]+)\s+import", txt))

all_refs = imported_names | dynamic_refs

# ── 4. Klassificera ───────────────────────────────────────────────────────────
aktiva:      list[str] = []
oaktiverade: list[str] = []

for p in sorted(py_files):
    stem = p.stem
    rel  = str(p.relative_to(ROOT)).replace("\\", "/")
    if stem.startswith("__"):
        aktiva.append(rel)
        continue
    if stem in all_refs:
        aktiva.append(rel)
    else:
        oaktiverade.append(rel)

# ── 5. Rapport ────────────────────────────────────────────────────────────────
lines: list[str] = []
lines.append("=== AKTIVA (statisk import ELLER dynamisk ref funnen) ===")
for f in aktiva:
    lines.append(f"  OK  {f}")

lines.append("")
lines.append("=== OAKTIVERADE (ingen statisk import eller dynamisk registreringskoppling) ===")
for f in oaktiverade:
    lines.append(f"  ??  {f}")

lines.append("")
lines.append(
    f"Totalt: {len(py_files)} filer | "
    f"Aktiva: {len(aktiva)} | "
    f"Oaktiverade: {len(oaktiverade)}"
)

rapport = ROOT / "oaktiverade_kedjor_rapport.txt"
rapport.write_text("\n".join(lines), encoding="utf-8")

print("\n".join(lines))
print()
print(f"Rapport sparad: {rapport}")
