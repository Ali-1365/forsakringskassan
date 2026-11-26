#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# =============================================================================
# CHAIN_ABORT_CODES: enda koder som ger HOPPAD + skip av senare steg.
# Övriga hard_stops (t.ex. HS01B tom akt) = underlagsflagga, kedjan fortsätter,
# canonical anropas. HARD_STOP/zero_fel = outputregler, se _output_hard_stop_text.
# =============================================================================

"""
SFCAE DYNAMIC PIPELINE — automatisk modulkedja
Varje steg körs, resultatet pluggas in i nästa. Saknad/irrelevant modul
markeras EJ_TILLÄMPLIG och kedjan fortsätter. Fungerar för alla svenska
måltyper: förvaltning, brottmål, tvistemål, socialförsäkring, socialtjänst,
hälso-/sjukvård, myndighetsbeslut, patientskada m.m.

Användning:
  from dynamic_pipeline import run_dynamic_pipeline
  result = run_dynamic_pipeline(root_dirs=["/path/to/case"], mode="JUDGMENT_AUDIT")
"""
from __future__ import annotations


import importlib.util
import json
import sys
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Knowledge integration
try:
    from knowledge_loader import get_knowledge_loader, search_knowledge, get_knowledge
    _KNOWLEDGE_AVAILABLE = True
except ImportError:
    _KNOWLEDGE_AVAILABLE = False

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "runtime", ROOT / "integrations", ROOT / "scripts", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# ── core_types (mjuk fallback) ──────────────────────────────────────────────
try:
    from core_types import HardStopCode, ProcessMode, ModeRouter
    _CORE_TYPES_AVAILABLE = True
except ImportError:
    _CORE_TYPES_AVAILABLE = False
    class HardStopCode:
        # Fallback — mirrors forensic_engine_v10_3_canonical.HardStopCode
        HS01A = "HS01A"; HS01B = "HS01B"; HS01C = "HS01C"
        HS02 = "HS02";   HS03 = "HS03";   HS04 = "HS04"
        HS05 = "HS05";   HS06 = "HS06";   HS07 = "HS07"
        HS08 = "HS08";   HS09 = "HS09";   HS09B = "HS09B"; HS10 = "HS10"
        HS11 = "HS11";   HS12 = "HS12";   HS13 = "HS13"
        HS14 = "HS14";   HS15 = "HS15";   HS16 = "HS16"
        HS17 = "HS17";   HS18 = "HS18";   HS19 = "HS19"
        HS20 = "HS20"
    class ProcessMode:
        JUDGMENT_AUDIT = "JUDGMENT_AUDIT"
        JUDGMENT_CONSTRUCTION = "JUDGMENT_CONSTRUCTION"
        UNDEFINED = "UNDEFINED"


# ── config_loader — policy-bindning till runtime ─────────────────────────────
try:
    from config_loader import system_policy as _system_policy
    _POLICY = _system_policy()
except Exception:
    _POLICY = {
        "provisional_output_only": True,
        "zero_inference": True,
        "fail_closed": True,
        "min_source_coverage": 0.85,
        "max_hard_stops_before_abort": 3,
    }

if _POLICY.get("provisional_output_only") is not True:
    raise RuntimeError("POLICY: provisional_output_only måste vara True")
if _POLICY.get("zero_inference") is not True:
    raise RuntimeError("POLICY: zero_inference måste vara True")
_MAX_HARD_STOPS = int(_POLICY.get("max_hard_stops_before_abort", 3))
_MIN_SOURCE_COVERAGE = float(_POLICY.get("min_source_coverage", 0.85))

try:
    from config_loader import court_profiles as _load_court_profiles
    _COURT_PROFILES = _load_court_profiles() or {}
except Exception:
    _COURT_PROFILES = {}


CHAIN_ABORT_CODES = frozenset({
    "HS01A",
    "HS06",
    "HS09",
    "HS11",
    "HS_CANONICAL_MISSING",
    "HS_CANONICAL_ERROR",
    "HS_MAX_STOPS_EXCEEDED",
})


def _is_chain_abort(state: "OrchestrationState") -> bool:
    return any(c in CHAIN_ABORT_CODES for c in (state.hard_stops or []))


def _output_hard_stop_text(text: str, verified: bool = False) -> Dict[str, Any]:
    """Outputregel: spärra text som presenterar obestyrkt som verifierat."""
    if verified:
        return {"status": "TILLATEN", "text": text, "hard_stop_text": False}
    return {
        "status": "HARD_STOP",
        "text": None,
        "hard_stop_text": True,
        "reason": "obestyrkt får inte presenteras som verifierat",
        "blocked_preview": (text or "")[:200],
    }




def _load(name: str, rel: str):
    """
    Laddar en projektmodul deterministiskt.

    Sökordning:
    1. uttryckligen angiven relativ sökväg
    2. runtime
    3. moduler_och_regler
    4. integrations
    5. projektroten

    Importfel bevaras i _MODULE_LOAD_ERRORS och får inte tystas.
    """
    import importlib.util
    import sys
    from pathlib import Path

    global _MODULE_LOAD_ERRORS

    if "_MODULE_LOAD_ERRORS" not in globals():
        _MODULE_LOAD_ERRORS = {}

    requested = Path(rel)
    filename = requested.name

    candidates = [
        ROOT / requested,
        ROOT / "runtime" / filename,
        ROOT / "moduler_och_regler" / filename,
        ROOT / "integrations" / filename,
        ROOT / filename,
    ]

    unique_candidates = []
    observed = set()

    for candidate in candidates:
        resolved = candidate.resolve()

        if resolved in observed:
            continue

        observed.add(resolved)
        unique_candidates.append(resolved)

    existing = [
        candidate
        for candidate in unique_candidates
        if candidate.is_file()
    ]

    if not existing:
        _MODULE_LOAD_ERRORS[name] = {
            "status": "EJ_TILLÄMPLIG",
            "skäl": "Modulfil saknas.",
            "sökta_sökvägar": [
                str(candidate)
                for candidate in unique_candidates
            ],
        }
        return None

    selected = existing[0]

    try:
        spec = importlib.util.spec_from_file_location(
            name,
            selected,
        )

        if spec is None or spec.loader is None:
            raise ImportError(
                f"Kunde inte skapa importdefinition för {selected}"
            )

        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)

        _MODULE_LOAD_ERRORS.pop(name, None)
        return module

    except Exception as exc:
        _MODULE_LOAD_ERRORS[name] = {
            "status": "FEL",
            "fil": str(selected),
            "skäl": f"{type(exc).__name__}: {exc}",
        }
        return None



# ── ALT B-REGISTER (kategori C) ──────────────────────────────────────────────
# Moduler i runtime/ och integrations/ som exponerar run_*_if_requested är
# kategori C: de körs ALDRIG i standardkedjan, bara när anroparen uttryckligen
# begär dem (requested_modules). Registret byggs statiskt med ast — ingen
# modul importeras eller körs för att registreras.

_ALT_B_KATALOGER = ("runtime", "integrations")
_ALT_B_CACHE: Optional[Dict[str, Dict[str, Any]]] = None
# Filer som inte kunde tolkas när registret byggdes — redovisas i case_meta,
# så att en modul aldrig tyst faller ur registret.
_ALT_B_OPARSBARA: Dict[str, str] = {}


def alt_b_register(uppdatera: bool = False) -> Dict[str, Dict[str, Any]]:
    """{modulnamn: {"fil": rel, "funktion": run_*_if_requested, "parametrar": [...]}}"""
    global _ALT_B_CACHE
    if _ALT_B_CACHE is not None and not uppdatera:
        return _ALT_B_CACHE
    import ast
    reg: Dict[str, Dict[str, Any]] = {}
    for katalog in _ALT_B_KATALOGER:
        d = ROOT / katalog
        if not d.is_dir():
            continue
        for fil in sorted(d.glob("*.py")):
            try:
                träd = ast.parse(fil.read_text(encoding="utf-8"))
            except Exception as e:
                _ALT_B_OPARSBARA[f"{katalog}/{fil.name}"] = f"{type(e).__name__}: {e}"
                continue
            for nod in träd.body:
                if (
                    isinstance(nod, ast.FunctionDef)
                    and nod.name.startswith("run_")
                    and nod.name.endswith("_if_requested")
                ):
                    arg = nod.args
                    namn = [a.arg for a in arg.args + arg.kwonlyargs]
                    reg[fil.stem] = {
                        "fil": f"{katalog}/{fil.name}",
                        "funktion": nod.name,
                        "parametrar": namn,
                        "kategori": "C",
                        "körs_endast_med": "requested=True",
                    }
                    break
    _ALT_B_CACHE = reg
    return reg


def _alt_b_argument(state: "OrchestrationState", parametrar: List[str],
                    extra: Dict[str, Any]) -> Dict[str, Any]:
    """Bygger argument ur pipeline-state — bara namn som funktionen deklarerar."""
    pool: Dict[str, Any] = {
        "pipeline_state": state,
        "state": state,
        "claims": state.claims,
        "positions": state.positions,
        "case_meta": state.case_meta,
        "meta": state.case_meta,
        "records": state.claims,
        "files": state.files,
        "root_dirs": list(state.root_dirs),
        "domän": state.domän,
        "rekvisit": list(state.rekvisit),
        "forum": state.forum,
        "mode": state.mode,
        "segments": [
            c if isinstance(c, dict) and "text" in c else {
                "text": str((c.get("content") or c.get("text") or "") if isinstance(c, dict) else (getattr(c, "content", "") or getattr(c, "text", "") or "")),
                "datum": str((c.get("date") or "") if isinstance(c, dict) else (getattr(c, "date", "") or "")),
                "källfil": str((c.get("file_name") or "") if isinstance(c, dict) else (getattr(c, "file_name", "") or "")),
            }
            for c in (getattr(state, "claims", None) or [])
        ],
        "legal_rules": list(
            (extra or {}).get("legal_rules")
            or (state.case_meta or {}).get("legal_rules")
            or getattr(state, "legal_rules", None)
            or []
        ),
    }
    canonical_cs = state.__dict__.get("_canonical_case_state")
    pool.setdefault("case_state", canonical_cs if canonical_cs is not None else state)
    pool.setdefault("pipeline_state", state)
    pool.setdefault("state", state)
    pool.setdefault("context", state)
    pool.setdefault("case_meta", state.case_meta)
    pool.setdefault("claims", state.claims)
    pool.setdefault("positions", state.positions)
    pool.setdefault("files", state.files)
    pool.setdefault("root_dirs", state.root_dirs)
    pool.update(extra or {})
    return {k: pool[k] for k in parametrar if k in pool and k != "requested"}


def _kör_begärda_moduler(state: "OrchestrationState", begärda: List[str],
                         parametrar: Optional[Dict[str, Dict[str, Any]]]) -> Dict[str, Any]:
    """Kör uttryckligen begärda kategori C-moduler med requested=True."""
    reg = alt_b_register()
    resultat: Dict[str, Any] = {}
    for namn in begärda or []:
        post = reg.get(namn)
        if not post:
            resultat[namn] = {"status": "EJ_REGISTRERAD",
                              "skäl": "ingen run_*_if_requested i runtime/ eller integrations/"}
            continue
        mod = _load(namn, post["fil"])
        fn = getattr(mod, post["funktion"], None) if mod else None
        if fn is None:
            resultat[namn] = {"status": "EJ_KÖRBAR", "skäl": f"{post['fil']} kunde inte laddas"}
            continue
        try:
            kwargs = _alt_b_argument(state, post["parametrar"], (parametrar or {}).get(namn) or {})
            if "requested" in post["parametrar"]:
                kwargs["requested"] = True
            r = fn(**kwargs)
            resultat[namn] = r if isinstance(r, dict) else {"status": "GENOMFÖRD", "resultat": r}
        except Exception as e:
            resultat[namn] = {"status": "FEL", "skäl": f"{type(e).__name__}: {e}"}
    return resultat


def _registrera_resurser(state: "OrchestrationState") -> None:
    """
    Registrerar config-, domän- och ärendebundna resurser i case_meta via de
    generiska laddarna i config_loader. Ingen analysmodul körs här.
    """
    try:
        import config_loader as _cl
    except Exception as e:
        state.case_meta["_config_register_fel"] = f"{type(e).__name__}: {e}"
        return
    try:
        reg = _cl.config_register()
        fel = [r for r in reg if str(r.get("status", "")).startswith("FEL")]
        state.case_meta["_config_register"] = {
            "antal": len(reg),
            "per_klass": {
                k: sum(1 for r in reg if r["klass"] == k)
                for k in sorted({r["klass"] for r in reg})
            },
            "avvecklade": _cl.avvecklade_config(),
            "fel": fel,
        }
    except Exception as e:
        state.case_meta["_config_register_fel"] = f"{type(e).__name__}: {e}"

    # Domänbundna kodtabeller/mallar — endast när domänen är fastställd.
    if state.domän:
        try:
            dr = _cl.domänbundna_config(state.domän)
            # Kodtabeller: bara antal koder (skanning är kategori C, sfcae_kodscan).
            # Övriga domänbundna filer (t.ex. gap-mallar) laddas som indikativa
            # öppna frågor till akten — aldrig som slutsatser.
            kod_info = {}
            for rel in dr.get("kodsystem", []):
                d = _cl.ladda(Path(rel).stem) or {}
                kod_info[rel] = len(d.get("koder") or []) if isinstance(d, dict) else 0
            övr = {rel: _cl.ladda(Path(rel).stem) for rel in dr.get("övriga", [])}
            state.case_meta["domänresurser"] = {
                "kodsystem": kod_info,
                "övriga": övr,
                "not": "INDIKATIV_ENDAST — registrerade domänresurser, ingen skanning körd",
            }
        except Exception as e:
            state.case_meta["domänresurser"] = {"fel": f"{type(e).__name__}: {e}"}

    # Ärendebundna config — endast för explicit ärendereferens.
    ref = (
        state.case_meta.get("arende_ref")
        or state.case_meta.get("case_ref")
        or state.case_meta.get("målnummer")
    )
    if ref:
        try:
            bundna = _cl.ärendebundna_config(str(ref))
            if bundna:
                state.case_meta["ärendebundna_config"] = bundna
        except Exception as e:
            state.case_meta["ärendebundna_config"] = {"fel": f"{type(e).__name__}: {e}"}


@dataclass
class StepResult:
    step_id: str
    module: str
    # OK             steget gjorde det det utger sig för att göra
    # DELVIS         steget kördes men täckte inte allt material
    # EJ_TILLÄMPLIG  steget var inte aktuellt för ärendet
    # UNDERLAG_SAKNAS steget kunde inte köras på det underlag som fanns
    # HARD_STOP      hard stop registrerad (CHAIN_ABORT-koder)
    # FEL            undantag i steget
    # HOPPAD         överhoppat p.g.a. kedjeavbrott
    # Endast OK lägger modulen i state.active_modules (se _step). En modul
    # som inte slutförde sitt uppdrag ska inte redovisas som aktiverad.
    status: str
    detail: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class OrchestrationState:
    # HARD GUARD: Detta är ORKESTRERINGS-state. canonical använder core_types.PipelineState (Enum).
    """Orkestrerings-state (dataclass). Skild från core_types.PipelineState Enum (P2)."""
    # P2: EJ samma typ som core_types.PipelineState Enum — GUARD: blanda aldrig ihop
    mode: str = "JUDGMENT_AUDIT"
    root_dirs: List[str] = field(default_factory=list)
    case_meta: Dict[str, Any] = field(default_factory=dict)
    forum: str = "EJ_FASTSTÄLLT"
    court_type: str = "EJ_FASTSTÄLLT"
    files: List[Dict] = field(default_factory=list)
    claims: List[Dict] = field(default_factory=list)
    positions: Dict = field(default_factory=dict)
    legal_sources: List[Dict] = field(default_factory=list)
    requisites: List[Dict] = field(default_factory=list)
    audit_a: List[Dict] = field(default_factory=list)
    audit_b: List[Dict] = field(default_factory=list)
    audit_c: List[Dict] = field(default_factory=list)
    economic: Dict = field(default_factory=dict)
    hard_stops: List[str] = field(default_factory=list)
    underlag_saknas: bool = False
    claim_zero_fel: List[Dict[str, Any]] = field(default_factory=list)
    zero_inference_violations: List[str] = field(default_factory=list)
    domän: str = ""
    rekvisit: List[str] = field(default_factory=list)
    bilageförteckning: List[str] = field(default_factory=list)
    text_hard_stops: List[Dict[str, Any]] = field(default_factory=list)
    steps: List[StepResult] = field(default_factory=list)
    active_modules: List[str] = field(default_factory=list)
    output: Dict[str, Any] = field(default_factory=dict)
    zero_fel: str = "EJ_BEDÖMD"  # ärendenivå: EJ_BEDÖMD | UNDERLAG_SAKNAS | DELVIS | GODKAND
    observability_run_id: Optional[str] = None



def _step(state: OrchestrationState, step_id: str, module: str, fn: Callable) -> StepResult:
    try:
        # HOPPAD endast vid CHAIN_ABORT — inte vid bevisluckor/HS01B.
        if _is_chain_abort(state) and step_id != "L16_FINALIZE":
            abort = next(c for c in state.hard_stops if c in CHAIN_ABORT_CODES)
            sr = StepResult(
                step_id=step_id,
                module=module,
                status="HOPPAD",
                detail=f"Kedjeavbrott: {abort}",
            )
            state.steps.append(sr)
            return sr

        # Policy: max_hard_stops_before_abort — för många icke-kritiska HS
        if (
            step_id != "L16_FINALIZE"
            and len(state.hard_stops) >= _MAX_HARD_STOPS
            and not _is_chain_abort(state)
        ):
            abort_code = "HS_MAX_STOPS_EXCEEDED"
            if abort_code not in state.hard_stops:
                state.hard_stops.append(abort_code)
            sr = StepResult(
                step_id=step_id,
                module=module,
                status="HARD_STOP",
                detail=f"Max antal hard stops ({_MAX_HARD_STOPS}) överskridna: {state.hard_stops}",
            )
            state.steps.append(sr)
            return sr

        result = fn(state) or {}
        status = result.get("status") or result.get("_status") or "OK"
        detail = result.get("detail") or result.get("_detail") or ""
        if status == "HARD_STOP":
            code = result.get("hard_stop_code", "HS_OKAND")
            if hasattr(code, "value"):
                code = code.value
            code = str(code)
            if code not in state.hard_stops:
                state.hard_stops.append(code)
            # HS01B m.fl. icke-abort: stegstatus = UNDERLAG_SAKNAS (fortsätt kedjan)
            if code not in CHAIN_ABORT_CODES:
                status = "UNDERLAG_SAKNAS"
        if status == "OK":
            state.active_modules.append(module)
        data = {k: v for k, v in result.items()
                if k not in ("status", "_status", "detail", "_detail", "hard_stop_code")}
        sr = StepResult(
            step_id=step_id, module=module, status=status,
            detail=detail, data=data, error="",
        )
    except Exception as e:
        sr = StepResult(
            step_id=step_id, module=module, status="FEL",
            detail="", error=f"{type(e).__name__}: {e}",
        )
    state.steps.append(sr)
    return sr


# ── STEGFUNKTIONER (pluggar in i varandra via state) ─────────────────────────


def step_mode(state: OrchestrationState) -> Dict:
    """Validera och normalisera körläge dynamiskt mot core_types.ModeRouter / ProcessMode."""
    raw_mode = (state.mode or "").strip().upper()
    router_map = {}
    if ModeRouter is not None:
        for member in ModeRouter:
            router_map[str(member.name).upper()] = str(member.value).upper()
            router_map[str(member.value).upper()] = str(member.value).upper()
    resolved = router_map.get(raw_mode)
    if resolved is None:
        code = getattr(HardStopCode, "HS01A", "HS01A")
        code_val = getattr(code, "value", code)
        state.hard_stops.append(code_val)
        allowed = sorted(router_map.keys()) if router_map else ["JUDGMENT_AUDIT", "JUDGMENT_CONSTRUCTION"]
        return {
            "_status": "HARD_STOP",
            "hard_stop_code": code_val,
            "_detail": (
                f"Okänt körläge '{state.mode}'. "
                f"Tillåtna: {', '.join(allowed)}."
            ),
        }
    state.mode = resolved
    return {"_status": "OK", "mode": resolved}
def step_forum(state: OrchestrationState) -> Dict:
    mod = _load("sfcae_forum", "integrations/forum_detector.py")
    if not mod or not hasattr(mod, "detect_forum"):
        return {"_status": "EJ_TILLÄMPLIG", "_detail": "forum_detector saknas"}
    # Bygg textsignal från case_meta + filnamn
    blob = " ".join([
        str(state.case_meta.get("domstol", "")),
        str(state.case_meta.get("myndighet", "")),
        str(state.case_meta.get("måltyp", "")),
        " ".join(Path(d).name for d in state.root_dirs),
    ])
    try:
        result = mod.detect_forum(blob) if callable(mod.detect_forum) else None
    except TypeError:
        # vissa versioner tar dict
        try:
            result = mod.detect_forum({"text": blob, **state.case_meta})
        except Exception:
            result = None
    if isinstance(result, dict):
        state.forum = result.get("forum") or result.get("detected_forum") or "EJ_FASTSTÄLLT"
        if result.get("conflict") or state.forum == "FORUM_CONFLICT":
            state.hard_stops.append("HS15")
    elif isinstance(result, str):
        state.forum = result
    else:
        state.forum = state.case_meta.get("forum") or "EJ_FASTSTÄLLT"
    domstol_validering = _validera_domstol(state.forum, state.court_type)
    state.case_meta["domstol_validering"] = domstol_validering
    if not domstol_validering.get("validerad"):
        state.case_meta["instansordning_varning"] = domstol_validering.get("skäl")
    return {
        "_status": "OK",
        "forum": state.forum,
        "domstol_validering": domstol_validering,
    }


def step_jurisdiction(state: OrchestrationState) -> Dict:
    _kör_rattstidskontroll(state)
    mod = _load("sfcae_jur", "integrations/jurisdiction_adapter.py")
    if not mod:
        # Fallback mapping
        mapping = {
            "FPL": "ADMINISTRATIVE_COURT", "SFB": "ADMINISTRATIVE_COURT",
            "RB": "CIVIL_COURT", "KL": "CIVIL_COURT",
            "BrB": "CRIMINAL_COURT",
        }
        state.court_type = mapping.get(state.forum, "ADMINISTRATIVE_COURT")
        return {"_status": "OK", "court_type": state.court_type, "_detail": "fallback mapping"}
    try:
        if hasattr(mod, "run_jurisdiction"):
            blob = " ".join([state.forum, str(state.case_meta.get("domstol","")), str(state.case_meta.get("måltyp",""))])
            forum_result = {"forum": state.forum, "status": "KLASSIFICERAD"}
            r = mod.run_jurisdiction(blob, forum_result, meta=state.case_meta)
            if isinstance(r, dict):
                state.court_type = r.get("court_type") or r.get("profile") or state.court_type
        # fallback mapping
        if state.court_type in ("EJ_FASTSTÄLLT", "", None):
            mapping = {"FPL": "ADMINISTRATIVE_COURT", "SFB": "ADMINISTRATIVE_COURT",
                       "RB": "CIVIL_COURT", "KL": "CIVIL_COURT", "BrB": "CRIMINAL_COURT"}
            state.court_type = mapping.get(state.forum, "ADMINISTRATIVE_COURT")
        return {"_status": "OK", "court_type": state.court_type}
    except Exception as e:
        mapping = {"FPL": "ADMINISTRATIVE_COURT", "SFB": "ADMINISTRATIVE_COURT",
                   "RB": "CIVIL_COURT", "KL": "CIVIL_COURT", "BrB": "CRIMINAL_COURT"}
        state.court_type = mapping.get(state.forum, "ADMINISTRATIVE_COURT")
        return {"_status": "OK", "court_type": state.court_type, "_detail": f"fallback after {e}"}


def step_ingest(state: OrchestrationState) -> Dict:
    """L0: lista filer (rör aldrig original — bara metadata).
    Alt B-moduler: document_text_extractor, ocr_fallback
    """
    # Grupp A: document_text_extractor
    files = []
    for rd in state.root_dirs:
        root = Path(rd)
        if not root.exists():
            continue
        for f in root.rglob("*"):
            if f.is_file() and f.suffix.lower() in {
                ".pdf", ".doc", ".docx", ".txt", ".rtf", ".jpg", ".png",
                ".wav", ".mp3", ".m4a", ".json", ".xml", ".html", ".eml",
            }:
                files.append({
                    "path": str(f),
                    "name": f.name,
                    "suffix": f.suffix.lower(),
                    "size": f.stat().st_size,
                })
    state.files = files
    if not files:
        state.hard_stops.append("HS01B")
        state.underlag_saknas = True
        if state.zero_fel == "EJ_BEDÖMD":
            state.zero_fel = "UNDERLAG_SAKNAS"
        return {
            "_status": "UNDERLAG_SAKNAS",
            "hard_stop_code": "HS01B",
            "_detail": "Inga handlingar funna — underlag saknas, ingen sakfrågebedömning",
            "count": 0,
        }
    # P00 materialregistrering (schema ur config/blueprint_p00_material.yaml)
    # och intagsklassning - körs alltid, inte bara via blueprint requested=True.
    l0: Dict[str, Any] = {}
    mr = _load("material_registry", "runtime/material_registry.py")
    if mr and hasattr(mr, "registrera_material"):
        reg = mr.registrera_material(filer=files)
        state.case_meta["p00_material"] = reg
        l0["p00_material"] = reg.get("status")
    else:
        l0["p00_material"] = "EJ_KÖRBAR: material_registry kunde inte laddas"
    ic = _load("intake_classifier", "runtime/intake_classifier.py")
    if ic and hasattr(ic, "klassificera_intake"):
        intag = ic.klassificera_intake(
            filer=files, requested_names=state.case_meta.get("requested_file_names"))
        state.case_meta["intake"] = intag
        l0["intake"] = intag.get("status")
    else:
        l0["intake"] = "EJ_KÖRBAR: intake_classifier kunde inte laddas"
    # L1 måltyp/ärendetyp ur aktens faktiska text (config/case_routing.yaml)
    cr = _load("case_router", "integrations/case_router.py")
    if cr and hasattr(cr, "klassificera_text"):
        text = _akt_text(state)
        if text.strip():
            routing = cr.klassificera_text(text)
            state.case_meta["case_routing"] = routing
            l0["case_routing"] = routing.get("status") or "GENOMFÖRD"
        else:
            state.case_meta["case_routing"] = {"status": "EJ_KÖRBAR", "skäl": "ingen extraherad text"}
            l0["case_routing"] = "EJ_KÖRBAR: ingen extraherad text"
    else:
        l0["case_routing"] = "EJ_KÖRBAR: case_router kunde inte laddas"
    cm = _load("capability_map", "runtime/capability_map.py")
    if cm and hasattr(cm, "aktivera_moduler"):
        kap = cm.aktivera_moduler(text=_akt_text(state), filnamn=[f["name"] for f in files])
        state.case_meta["capability_map"] = kap
        state.active_modules.extend(
            m["modul"] for m in kap.get("aktiva", []) if m["modul"] not in state.active_modules)
        l0["capability_map"] = f'{kap.get("status")} ({kap.get("antal_aktiva", 0)} aktiva)'
    else:
        l0["capability_map"] = "EJ_KÖRBAR: capability_map kunde inte laddas"
    return {"_status": "OK", "count": len(files), "_detail": str(l0)}


def step_categorize(state: OrchestrationState) -> Dict:
    mod = _load("sfcae_evcat", "runtime/evidence_categorizer.py")
    if not mod or not state.files:
        return {"_status": "EJ_TILLÄMPLIG", "_detail": "categorizer eller filer saknas"}
    if not hasattr(mod, "kategorisera_fil"):
        return {"_status": "EJ_TILLÄMPLIG", "_detail": "kategorisera_fil saknas"}
    cats = []
    errors = []
    for f in state.files[:50]:
        name = f.get("name") or Path(str(f.get("path", ""))).name
        path = f.get("path") or name
        try:
            cats.append(mod.kategorisera_fil(name, path))
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {e}")
    if errors and not cats:
        return {
            "_status": "FEL",
            "_detail": "; ".join(errors[:5]),
            "kategorier": 0,
            "fel": len(errors),
        }

    # Kategoriseringen beräknades och kastades bort. Modulens deklarerade
    # output (bevis_kategorisering.json/.md) producerades aldrig i en
    # pipelinekörning — bara om någon körde modulens egen CLI för hand.
    # Statistiken går också in i state så senare steg och rapporten kan se
    # vad L0 faktiskt kategoriserade.
    export = {}
    statistik: Dict[str, int] = {}
    if hasattr(mod, "bygg_rapport") and hasattr(mod, "exportera_kategorisering"):
        try:
            rapport = mod.bygg_rapport(cats, state.case_meta.get("case_id") or "")
            statistik = dict(rapport.kategori_statistik)
            out_dir = _utdatakatalog(state)
            export = mod.exportera_kategorisering(rapport, out_dir)
            state.case_meta["bevis_kategorisering"] = {
                "statistik": statistik,
                "export": export,
                "output_dir": out_dir,
                "antal_poster": rapport.totalt_filer,
            }
        except Exception as e:
            # Export som inte gick igenom redovisas; en utebliven
            # bevisförteckning är en lucka i akten, inte ett icke-utfall.
            export = {"fel": f"{type(e).__name__}: {e}"}
            state.case_meta["bevis_kategorisering"] = {"export": export}

    ej_exporterad = [k for k, v in export.items() if str(v) != "EXPORTED"]
    return {
        "_status": "OK" if not ej_exporterad else "DELVIS",
        "kategorier": len(cats),
        "fel": len(errors),
        "statistik": statistik,
        "export": export,
        "_detail": (
            "; ".join(errors[:3]) if errors
            else (
                "kategorisering genomförd + exporterad"
                if not ej_exporterad
                else f"kategorisering genomförd, export ej fullständig: {ej_exporterad}"
            )
        ),
    }


def step_source_hygiene(state: OrchestrationState) -> Dict:
    mod = _load("sfcae_hygiene", "integrations/source_hygiene.py")
    if not mod:
        return {"_status": "EJ_TILLÄMPLIG"}
    try:
        files = state.files[:30]
        if hasattr(mod, "assess"):
            # Identiteten sätts av anroparen (adaptern läser bara posterna).
            # Utan file_id kan klassificeringen inte knytas tillbaka till filen.
            poster = [
                {
                    "file_id": str(f.get("path") or f.get("name") or i),
                    "name": str(f.get("name") or ""),
                    "path": str(f.get("path") or ""),
                }
                for i, f in enumerate(files, 1)
            ]
            result = mod.assess(poster)
            # Urvalet redovisas: 30 filer bedöms, inte hela aktens filer.
            result["urval"] = {
                "bedömda_filer": len(files),
                "total_filer": len(state.files),
                "max_filer": 30,
                "fullständigt": len(files) >= len(state.files),
            }
            state.case_meta["source_hygiene"] = result
            return {
                "_status": "OK",
                "bedömda": result.get("antal", 0),
                "karantän": len(result.get("manual_review_flaggade") or []),
                "urval": result["urval"],
            }
        if hasattr(mod, "classify_source_type"):
            klassificering = [
                {"fil": f.get("name", ""), "typ": mod.classify_source_type(f.get("name", ""))}
                for f in files
            ]
            state.case_meta["source_hygiene"] = {
                "status": "GENOMFÖRD", "antal": len(klassificering),
                "klassificering": klassificering,
            }
            return {"_status": "OK", "bedömda": len(klassificering)}
        return {"_status": "EJ_TILLÄMPLIG", "_detail": "source_hygiene saknar assess/classify_source_type"}
    except Exception as e:
        return {"_status": "FEL", "_detail": str(e)}


def step_claims(state: OrchestrationState) -> Dict:
    case_state, extraction = _bygg_l4_underlag(state)
    if case_state is None:
        return {"_status": "UNDERLAG_SAKNAS", "_detail": str(extraction)}
    if not case_state.claims:
        state.claims = []
        return {
            "_status": "UNDERLAG_SAKNAS",
            "_detail": "Ingen claim skapades från extraherad källtext; filnamn används inte som påståenden",
        }

    # Urvalet redovisas: extraktionen tar max 50 filer (befintlig gräns).
    state.case_meta["claim_urval"] = {
        "extraherade_filer": len(case_state.files),
        "total_filer": len(state.files),
        "max_filer": 50,
        "fullständigt": len(case_state.files) >= len(state.files),
    }

    # Semantisk klassning: befintlig ClaimClassifier, samma case_state
    # (ingen andra extraktionskörning). Utan den är claim_type "CLAIM" och
    # FIX-C-kontrollen i claim_id_adapter blir vacill. Klassifieringen är
    # densamma som canonical L2 gör på sin egen CaseState — ingen ny motor.
    klassifiering_status = "EJ_KÖRBAR"
    cc = _load("sfcae_cc", "runtime/claim_classifier.py")
    if cc and hasattr(cc, "ClaimClassifier"):
        try:
            classifier = cc.ClaimClassifier()
            classifier.classify_all(case_state)
            stats = case_state.metadata.get("claim_classification_stats") or {}
            state.case_meta["claim_classification"] = {
                "status": "GENOMFÖRD",
                "fördelning": stats,
                "källa": "runtime/claim_classifier.py (befintlig implementation)",
            }
            klassifiering_status = "GENOMFÖRD"
        except Exception as e:
            state.case_meta["claim_classification"] = {
                "status": "FEL", "skäl": f"{type(e).__name__}: {e}",
            }
            klassifiering_status = f"FEL: {type(e).__name__}"
    else:
        state.case_meta["claim_classification"] = {
            "status": "EJ_KÖRBAR",
            "skäl": "claim_classifier saknas; semantisk klassning lämnas till canonical",
        }

    adapter = _load("sfcae_cid", "integrations/claim_id_adapter.py")
    if adapter and hasattr(adapter, "run_claim_id_validation"):
        state.case_meta["claim_id_validation"] = adapter.run_claim_id_validation(case_state.claims)

    cit_mod = _load("sfcae_cit", "integrations/citation_adapter.py")
    if cit_mod and hasattr(cit_mod, "run_citation_analysis"):
        state.case_meta["citation_analysis"] = cit_mod.run_citation_analysis(case_state.claims)
    state.claims = [
        {
            "claim_id": claim.claim_id,
            "content": claim.content,
            "text": claim.content,
            "source_id": claim.source_id,
            "file_name": claim.file_name,
            "page": claim.page,
            "date": claim.date,
            "version": claim.version,
            "claim_type": claim.claim_type,
            "availability": getattr(claim.availability, "value", claim.availability),
        }
        for claim in case_state.claims
    ]
    return {
        "_status": "OK",
        "claims": len(state.claims),
        "klassning": klassifiering_status,
    }


def _bygg_l4_underlag(state: OrchestrationState, max_filer: int = 50):
    """Extraherar verklig text ur aktens filer till en canonical CaseState.

    L4 kan inte mäta parternas positioner på filnamn. ProcessPositionAgent
    kräver case_state.claims med ordagrann text (dess egen docstring:
    "Kräver att L2 (DocumentTextExtractor) har körts"). Returnerar
    (case_state, extraction_results) eller (None, skäl-sträng).
    """
    _cache = state.__dict__.get("_l4_underlag_cache")
    if _cache is not None and _cache[0] == max_filer:
        return _cache[1], _cache[2]
    canonical = _load(
        "forensic_engine_v10_3_canonical",
        "runtime/forensic_engine_v10_3_canonical.py",
    )
    dte = _load("sfcae_dte", "runtime/document_text_extractor.py")
    if canonical is None or dte is None:
        return None, "canonical eller document_text_extractor kunde inte laddas"

    case_state = canonical.CaseState(
        case_id=str(state.case_meta.get("case_id") or "DYNAMIC-L4"),
    )
    for f in state.files[:max_filer]:
        sökväg = str(f.get("path") or "")
        if not sökväg:
            continue
        case_state.files.append(canonical.FileRecord(
            file_id=canonical.generate_file_id(sökväg),
            file_path=sökväg,
            relative_path=str(f.get("name") or Path(sökväg).name),
            filtyp_magic=canonical.detect_filetype_magic(sökväg),
            file_size_bytes=int(f.get("size") or 0),
        ))
    if not case_state.files:
        return None, "inga filer att extrahera text ur"

    extractor = dte.DocumentTextExtractor()
    extraction_results = extractor.extract_all(case_state)
    PM = getattr(canonical, "ProcessMode", None)
    if PM is not None and state.mode in PM.__members__:
        case_state.process_mode = PM[state.mode]
    state.__dict__["_l4_underlag_cache"] = (max_filer, case_state, extraction_results)
    return case_state, extraction_results


def _akt_text(state: OrchestrationState) -> str:
    """Aktens extraherade text (claims.content). Tom sträng om inget extraherats."""
    case_state, _ = _bygg_l4_underlag(state)
    if case_state is None:
        return ""
    return "\n".join(str(getattr(c, "content", "") or "") for c in case_state.claims)


def step_positions(state: OrchestrationState) -> Dict:
    """L4: parternas positioner — faktiskt analyserade, inte "registered".

    Steget instansierade tidigare ProcessPositionAgent, satte
    state.positions = {"status": "registered"} och returnerade OK utan att
    någonsin anropa .analyze() (kommentaren löd "agent API varies — best
    effort"). Ett L4 som redovisades som genomfört hade då registrerat noll
    positioner, och varken kontradiktorisk matris, partsvyn eller rapporten
    hade något partsmaterial att arbeta på. Ett steg som inte mätt något får
    inte se ut som ett steg som mätt och funnit det i sin ordning.
    """
    mod = _load("sfcae_pos", "runtime/process_position_agent.py")
    if not mod or not hasattr(mod, "ProcessPositionAgent"):
        return {"_status": "EJ_TILLÄMPLIG", "_detail": "process_position_agent saknas"}
    if not state.files:
        return {"_status": "EJ_TILLÄMPLIG", "_detail": "inga filer i akten"}

    try:
        case_state, underlag = _bygg_l4_underlag(state)
        if case_state is None:
            return {"_status": "UNDERLAG_SAKNAS", "_detail": str(underlag)}

        if not case_state.claims:
            # Filer finns men ingen text kunde läsas ur dem. Underlaget är
            # oläst, inte tomt — samma skillnad som canonical HS04 gör.
            state.positions = {
                "status": "UNDERLAG_SAKNAS",
                "skäl": "ingen text kunde extraheras ur aktens filer",
                "källa": "process_position_agent.analyze (ej körd)",
            }
            return {
                "_status": "UNDERLAG_SAKNAS",
                "_detail": (
                    f"{len(case_state.files)} filer lästes in men noll claims "
                    f"extraherades — positioner kan inte mätas på filnamn"
                ),
                "filer": len(case_state.files),
                "claims": 0,
            }

        agent = mod.ProcessPositionAgent()
        result = agent.analyze(case_state, underlag)

        per_part: Dict[str, int] = {}
        for pos in result.positions:
            per_part[pos.party] = per_part.get(pos.party, 0) + 1

        state.positions = {
            "status": "ANALYSERAD",
            "källa": "process_position_agent.analyze",
            "parter": list(result.parties_identified),
            "per_part": per_part,
            "antal_positioner": len(result.positions),
            "yrkanden": result.yrkanden_count,
            "grunder": result.grunder_count,
            "invändningar": result.invändningar_count,
            "not_verifiable": result.not_verifiable_count,
            "varningar": list(result.warnings),
            "positioner": [p.to_dict() for p in result.positions],
        }
        # Samma nycklar som canonical skriver, så nedströms konsumenter
        # (P18-symmetrikontrollen, partsvyn) läser ett och samma format.
        state.case_meta["l4_process_positions"] = \
            case_state.metadata.get("l4_process_positions", [])
        state.case_meta["l4_parties"] = case_state.metadata.get("l4_parties", [])
        state.case_meta["l4_result"] = result.to_dict()
        state.__dict__["_förberett_l4"] = {
            "result": result,
            "metadata": {k: case_state.metadata[k] for k in (
                "l4_process_positions", "l4_parties", "l4_has_forbidden_inference")
                if k in case_state.metadata},
        }

        # GAP-4: party_impact_adapter — partsbild ur Motor C/L4
        try:
            pia = _load("sfcae_pia", "integrations/party_impact_adapter.py")
            if pia and hasattr(pia, "run_party_impact"):
                state.case_meta["party_impact"] = pia.run_party_impact(
                    csm=None,
                    canonical_metadata=state.case_meta,
                )
        except Exception:
            pass

        return {
            "_status": "OK",
            "_detail": (
                f"{len(result.positions)} positioner ur {len(case_state.claims)} "
                f"claims; parter: {', '.join(result.parties_identified) or 'INGA'}"
            ),
            "claims": len(case_state.claims),
            "antal_positioner": len(result.positions),
            "parter": list(result.parties_identified),
            "per_part": per_part,
            "not_verifiable": result.not_verifiable_count,
            "varningar": list(result.warnings),
        }
    except Exception as e:
        return {"_status": "FEL", "_detail": f"{type(e).__name__}: {e}"}


def step_legal_search(state: OrchestrationState) -> Dict:
    mod = _load("sfcae_dsp", "runtime/deep_search_pipeline.py")
    term = state.case_meta.get("legal_rule") or state.case_meta.get("måltyp") or state.forum
    if not mod or not term or term in ("EJ_FASTSTÄLLT", ""):
        return {"_status": "EJ_TILLÄMPLIG", "_detail": "ingen sökterm eller modul"}
    if not hasattr(mod, "kör_deep_search_pipeline"):
        return {"_status": "EJ_KÖRBAR", "_detail": "deep_search_pipeline saknar sökfunktion"}
    state.case_meta["legal_search_need"] = {
        "sokterm": term,
        "status": "REQUIRES_SEARCH_VERIFICATION",
    }
    return {
        "_status": "UNDERLAG_SAKNAS",
        "sokterm": term,
        "_detail": "rättskällebehov registrerat; ingen sökning kördes och inga verifierade källor producerades",
    }


def step_requisites(state: OrchestrationState) -> Dict:
    """Tom matris här — subsumtion/rekvisit utförs i canonical (L8/L8.5)."""
    mod = _load("sfcae_req", "runtime/requisite_claim_mapper.py")
    state.requisites = []
    if mod:
        return {
            "_status": "OK",
            "rekvisit": 0,
            "_detail": "requisites lämnas till canonical subsumtion",
        }
    return {"_status": "EJ_TILLÄMPLIG", "rekvisit": 0, "_detail": "requisite_claim_mapper saknas"}


def step_economy(state: OrchestrationState) -> Dict:
    # Aktiveras om filnamn antyder ekonomi/skuld/faktura
    triggers = ("faktura", "inkasso", "skuld", "krav", "saldo", "betalning", "kfm")
    hit = any(any(t in f["name"].lower() for t in triggers) for f in state.files)
    if not hit and not state.case_meta.get("economic"):
        return {"_status": "EJ_TILLÄMPLIG", "_detail": "inga ekonomiska signaler"}
    mod = _load("sfcae_econ", "integrations/economy_bridge.py")
    if not mod:
        return {"_status": "EJ_TILLÄMPLIG", "_detail": "economy_bridge saknas"}
    try:
        r = mod.run_economic_reconstruction(state.case_meta)
        state.economic = r if isinstance(r, dict) else {}
        economic_status = state.economic.get("status")
        step_status = "OK" if economic_status in ("PRELIMINAR EKONOMISK REKONSTRUKTION", "GENOMFÖRD") else "UNDERLAG_SAKNAS"
        return {"_status": step_status, "economic_status": economic_status,
                "_detail": "ekonomisk rekonstruktion körd" if step_status == "OK"
                else f"ekonomisk rekonstruktion ej komplett: {economic_status or 'okänd status'}"}
    except Exception as e:
        return {"_status": "FEL", "_detail": str(e)}


def step_socialforsakring(state: OrchestrationState) -> Dict:
    triggers = ("sjukpenning", "sgi", "fk", "försäkringskassan", "sfb", "aktivitetsersättning")
    blob = (state.forum + " " + str(state.case_meta) + " " + " ".join(f["name"] for f in state.files)).lower()
    if not any(t in blob for t in triggers):
        return {"_status": "EJ_TILLÄMPLIG"}
    mod = _load("sfcae_sf", "moduler_och_regler/socialforsakring_lager.py") or _load("sfcae_sf", "runtime/socialforsakring_lager.py")
    if not mod:
        return {"_status": "EJ_TILLÄMPLIG", "_detail": "socialforsakring_lager saknas"}
    try:
        case_state, underlag = _bygg_l4_underlag(state)
        if case_state is None:
            return {"_status": "UNDERLAG_SAKNAS", "_detail": str(underlag)}
        if hasattr(mod, "is_socialforsakring_case") and not mod.is_socialforsakring_case(case_state):
            return {"_status": "EJ_TILLÄMPLIG", "_detail": "socialförsäkringsmåltyp ej identifierad i extraherat underlag"}
        if not hasattr(mod, "kör_socialforsakring_lager"):
            return {"_status": "EJ_KÖRBAR", "_detail": "socialforsakring_lager saknar körfunktion"}
        result = mod.kör_socialforsakring_lager(case_state)
        state.case_meta["sf_l00_l02"] = result.get("lager", {})
        state.case_meta["sf_l00_l02_status"] = "GENOMFÖRD" if result.get("aktiverad") else "EJ_TILLÄMPLIG"
        return {"_status": "OK" if result.get("aktiverad") else "EJ_TILLÄMPLIG",
                "lager": sorted((result.get("lager") or {}).keys()),
                "_detail": "L00–L02 kördes på canonical extraherat case state" if result.get("aktiverad")
                else "L00–L02 ej aktiverade för extraherat underlag"}
    except Exception as e:
        return {"_status": "FEL", "_detail": str(e)}



def step_socialtjanst(state: OrchestrationState) -> Dict:
    """L1-signal: ladda domain-referens socialtjänst (ingen parallell motor)."""
    triggers = (
        "socialnämnd", "socialtjänst", "ifo", "sol", "lss", "lvu", "lvm",
        "bistånd", "omhändertagande", "personlig assistans", "bbic",
    )
    blob = (
        state.forum + " " + str(state.case_meta) + " "
        + " ".join(f.get("name", "") for f in state.files)
    ).lower()
    if not any(x in blob for x in triggers):
        return {"_status": "EJ_TILLÄMPLIG", "_detail": "ingen socialtjänst-signal"}
    # progressive disclosure paths only
    refs = [
        "runtime/knowledge/socialtjanst-kunskapsbas.md",
        "runtime/knowledge/socialtjanst-overklagande.md",
    ]
    state.case_meta.setdefault("domain_modules", []).extend(refs)
    # Referenserna läses via knowledge_loader (runtime-domain). Tidigare
    # registrerades bara sökvägarna och filerna lästes aldrig.
    lästa: Dict[str, int] = {}
    ej_lästa: List[str] = []
    if _KNOWLEDGE_AVAILABLE:
        for ref in refs:
            try:
                innehåll = get_knowledge(ref)
            except Exception as e:
                ej_lästa.append(f"{ref} ({type(e).__name__}: {e})")
                continue
            if innehåll:
                lästa[ref] = len(innehåll)
            else:
                ej_lästa.append(ref)
    else:
        ej_lästa = list(refs)
    state.case_meta["domain_knowledge_read"] = lästa
    # Kodtabell för domänen (config/kodsystem_*.yaml via kodsystem_sökväg) och
    # mönsterbiblioteket (config/pattern_rules_v2.yaml) körs mot aktens text.
    # Kodtabellernas egen meta.domän är nyckeln (kodsystem_register):
    # socialtjänsttabellen deklarerar SOL_SOCIALTJANST, inte SOL_LVU.
    # Steg 16: saknad domän redovisas som standarddomän (källmärkt); en angiven
    # men olöst domän ger EJ_KÖRBAR - aldrig tyst en annan domäns tabell.
    domän = state.domän or "SOL_SOCIALTJANST"
    state.case_meta["domän_kodsystem_källa"] = (
        "INDATA" if state.domän else "STANDARDDOMÄN_DOMÄN_SAKNAS_I_INDATA")
    text = _akt_text(state)
    try:
        import config_loader as _cl
        kodtabell = _cl.kodsystem_sökväg(domän)
    except Exception as e:
        kodtabell = None
        state.case_meta["domän_kodsystem_fel"] = f"{type(e).__name__}: {e}"
    ks = _load("kodsystem_scanner", "runtime/kodsystem_scanner.py")
    if ks and kodtabell and text.strip():
        state.case_meta["domän_kodsystem"] = ks.skanna_text(
            text, kodtabell_path=str(ROOT / kodtabell), domän=domän)
    else:
        state.case_meta["domän_kodsystem"] = {
            "status": "EJ_KÖRBAR",
            "skäl": ("ingen kodtabell för domän " + domän) if not kodtabell
                    else ("ingen extraherad text" if not text.strip() else "kodsystem_scanner saknas"),
        }
    ps = _load("pattern_scanner", "runtime/pattern_scanner.py")
    if ps and text.strip():
        state.case_meta["domän_mönster"] = ps.skanna_monster(text)
    if ej_lästa:
        state.case_meta["domain_knowledge_ej_läst"] = ej_lästa
    return {
        "_status": "OK" if not ej_lästa else "DELVIS",
        "_detail": (
            "domain socialtjänst markerad, referenser lästa"
            if not ej_lästa else f"domain socialtjänst markerad, ej lästa: {ej_lästa}"
        ),
        "domain_refs": refs,
        "domain_refs_lästa": len(lästa),
        "forum_guard": "kommunal_socialtjanst_only",
    }

def step_kontradiktorisk(state: OrchestrationState) -> Dict:
    """
    Motparts-/kontradiktionsanalys — automatiskt aktiverad efter positionsidentifiering.
    Byggs från claims + positions i state; aldrig ett domslut.
    Ingår i DOMAR→MOTPART→BEVIS→RÄTTSLIG→PARTS→OUTPUT-kedjan som den neutrala
    kontradiktoriska kontrollen (req SFCAE architecture rule 4).
    """
    mod = _load("sfcae_kontra", "integrations/kontradiktorisk_matris.py")
    if not mod or not hasattr(mod, "run_matris_if_requested"):
        return {"_status": "EJ_TILLÄMPLIG", "_detail": "kontradiktorisk_matris saknas"}
    try:
        result = mod.run_matris_if_requested(
            claims=state.claims or [],
            positions=state.positions or {},
            pipeline_state=state,
            requested=True,
        )
        # Store matris data in state for downstream consumers (finalize, optional post-pipeline runners)
        state.case_meta["kontradiktorisk_matris"] = result.get("matris") or {}
        return {
            "_status": "OK" if result.get("status") == "GENOMFÖRD" else "EJ_TILLÄMPLIG",
            "rader": (result.get("matris") or {}).get("antal_rader", 0),
            "_detail": result.get("not", ""),
        }
    except Exception as e:
        return {"_status": "FEL", "_detail": str(e)}


def _fynd_dict(f: Any) -> Dict[str, Any]:
    if isinstance(f, dict):
        return f
    ut = {}
    for k, v in getattr(f, "__dict__", {}).items():
        ut[k] = getattr(v, "value", v) if not isinstance(v, (list, dict)) else v
    return ut or {"fynd": str(f)}


def step_audit_abc(state: OrchestrationState) -> Dict:
    """L12-L14: canonical AuditAgentA/B/C + AuditController (config/audit_controller.yaml)
    körs på aktens extraherade CaseState. Tidigare en stub som returnerade
    a=b=c=0 och "delegerade" till finalize, som hoppade över canonical."""
    canonical = _load(
        "forensic_engine_v10_3_canonical",
        "runtime/forensic_engine_v10_3_canonical.py",
    )
    if canonical is None:
        return {"_status": "EJ_KÖRBAR", "_detail": "canonical kunde inte laddas"}
    if not state.files:
        return {"_status": "UNDERLAG_SAKNAS", "_detail": "inga filer i akten"}
    # Audit A/B/C och AuditController körs EN gång, i canonical, efter
    # relationsgraf, gating och subsumtion (L5-L8.5) som de granskar. Steget
    # startar den körningen (med L4/L9 från denna kedja återanvända) och läser
    # ut resultatet; L16_FINALIZE återanvänder samma körning.
    try:
        case_state = _kör_canonical(state, canonical, _process_mode(state, canonical),
                                    _utdatakatalog(state))
    except Exception as e:
        state.hard_stops.append("HS_CANONICAL_ERROR")
        return {"_status": "HARD_STOP", "hard_stop_code": "HS_CANONICAL_ERROR",
                "_detail": f"canonical: {type(e).__name__}: {e}"}
    a = list(getattr(case_state, "audit_a_findings", []) or [])
    b = list(getattr(case_state, "audit_b_findings", []) or [])
    c = list(getattr(case_state, "audit_c_findings", []) or [])
    state.audit_a = [_fynd_dict(x) for x in a]
    state.audit_b = [_fynd_dict(x) for x in b]
    state.audit_c = [_fynd_dict(x) for x in c]
    verdict = getattr(case_state, "audit_controller_verdict", None)
    violations = list(case_state.metadata.get("audit_controller_violations") or [])
    state.case_meta["audit_controller"] = {
        "verdict": getattr(verdict, "value", str(verdict)),
        "violations": violations,
        "p18_tröskel_källa": case_state.metadata.get("audit_controller_p18_källa"),
    }
    return {
        "_status": "OK",
        "a": len(a),
        "b": len(b),
        "c": len(c),
        "_detail": f"AuditController={getattr(verdict, 'value', verdict)}; "
                   f"{len(violations)} violations",
    }


def step_hyresratt(state: OrchestrationState) -> Dict:
    """Domänsteg JB 12 kap. (lokal-/bostadshyra): kodtabell
    config/kodsystem_jb_hyresratt.yaml + luckmallar
    config/hyresratt_gap_templates.yaml. Luckorna registreras som öppna frågor
    som ska besvaras ur akten - ingen fråga besvaras automatiskt."""
    triggers = ("hyresrätt", "hyresratt", "lokalhyra", "hyresvärd", "hyresgäst",
                "hyresavtal", "jb 12", "12 kap. jordabalken", "jordabalken 12",
                "hyresnämnd", "besittningsskydd")
    text = _akt_text(state)
    blob = (state.domän + " " + " ".join(f.get("name", "") for f in state.files)
            + " " + text).lower()
    if state.domän.upper() != "JB_HYRESRATT" and not any(t in blob for t in triggers):
        return {"_status": "EJ_TILLÄMPLIG", "_detail": "ingen hyresrättssignal"}
    try:
        import config_loader as _cl
        kodtabell = _cl.kodsystem_sökväg("JB_HYRESRATT")
        gap = _cl.ladda("hyresratt_gap_templates") or {}
    except Exception as e:
        return {"_status": "EJ_KÖRBAR", "_detail": f"config_loader: {type(e).__name__}: {e}"}
    ks = _load("kodsystem_scanner", "runtime/kodsystem_scanner.py")
    res: Dict[str, Any] = {}
    if ks and kodtabell and text.strip():
        res["kodsystem"] = ks.skanna_text(text, kodtabell_path=str(ROOT / kodtabell),
                                          domän="JB_HYRESRATT")
    else:
        res["kodsystem"] = {"status": "EJ_KÖRBAR", "skäl": "kodtabell, scanner eller text saknas"}
    res["luckor"] = [{
        "id": g.get("id"), "kategori": g.get("kategori"),
        "lagrum_indikativa": g.get("lagrum_indikativa") or [],
        "fråga": g.get("fråga"), "status": "OBESVARAD - besvaras ur akten",
    } for g in (gap.get("gap_typer") or [])]
    state.case_meta["domän_hyresratt"] = res
    state.case_meta.setdefault("domain_modules", []).append("JB_HYRESRATT")
    if not res["luckor"]:
        return {"_status": "DELVIS", "_detail": "hyresratt_gap_templates innehåller inga gap_typer"}
    return {"_status": "OK", "_detail": f'{len(res["luckor"])} öppna luckfrågor; kodsystem={res["kodsystem"].get("status", "körd")}'}


def _utdatakatalog(state: OrchestrationState) -> str:
    """Anvisad utdatamapp, annars ROOT/output/<case_id> - produktens
    utdataplats (SYSTEM_HEALTH_TEST UTDATAKATALOGER). Tidigare den relativa
    "output_v10", som hamnade i processens arbetskatalog (produktmappen) och
    kringgick canonical.run_pipelines krav på explicit output_dir."""
    od = state.case_meta.get("output_dir")
    if od:
        return str(od)
    return str(ROOT / "output" / str(state.case_meta.get("case_id") or "dynamic_pipeline"))


def _process_mode(state: OrchestrationState, canonical: Any) -> Any:
    PM = getattr(canonical, "ProcessMode", None)
    if PM is None:
        return state.mode
    try:
        return PM[state.mode] if state.mode in PM.__members__ else PM.JUDGMENT_AUDIT
    except Exception:
        return getattr(PM, "JUDGMENT_AUDIT", state.mode)


def _kör_canonical(state: OrchestrationState, canonical: Any, pm: Any, out_dir: str) -> Any:
    """En canonical-körning per kedja. L4 och eventuell redan körd L9-audit
    skickas in för återanvändning; konstruktion körs först efter canonical-gaten."""
    cs = state.__dict__.get("_canonical_case_state")
    if cs is not None:
        return cs
    förberett = {}
    if state.__dict__.get("_förberett_l4") is not None:
        förberett["l4"] = state.__dict__["_förberett_l4"]
    if state.__dict__.get("_förberett_l9") is not None:
        förberett["l9"] = state.__dict__["_förberett_l9"]
    if state.case_meta.get("legal_merge_output") is not None:
        förberett["legal_merge"] = {
            "legal_merge_output": state.case_meta["legal_merge_output"],
            "legal_merge_anchors": state.case_meta.get("legal_merge_anchors"),
            "legal_merge_status": state.case_meta.get("legal_merge_status"),
        }
    cs = canonical.run_pipeline(
        root_paths=list(state.root_dirs),
        process_mode=pm,
        output_dir=out_dir,
        references_dir=str(ROOT / "references"),
        förberett=förberett or None,
    )
    state.__dict__["_canonical_case_state"] = cs
    state.case_meta["canonical_återanvänt"] = sorted(förberett.keys())
    return cs


def step_domskal(state: OrchestrationState) -> Dict:
    """L11: domskälsaudit/-konstruktion. Läser config/judgment_audit.yaml resp.
    judgment_construction.yaml via config_loader.judgment_config(mode) och kör
    DomskälsmatrisAgent. Lager som modekonfigen blockerar vid HS01A respekteras."""
    try:
        import config_loader as _cl
        jcfg = _cl.judgment_config(state.mode) or {}
    except Exception as e:
        return {"_status": "EJ_KÖRBAR", "_detail": f"judgment_config: {type(e).__name__}: {e}"}
    if not jcfg:
        return {"_status": "EJ_KÖRBAR", "_detail": f"ingen judgment-konfig för mode {state.mode}"}
    blockerade = ((jcfg.get("active_layers") or {}).get("blocked_by_HS01A") or [])
    state.case_meta["judgment_config"] = {
        "mode_kod": jcfg.get("mode_kod"), "hs01_variant": jcfg.get("hs01_variant"),
        "blocked_by_HS01A": blockerade,
    }
    if "HS01A" in state.hard_stops and any(l in blockerade for l in ("L9", "L11")):
        return {"_status": "HARD_STOP", "hard_stop_code": "HS01A",
                "_detail": "domskälsmatris kräver fullständig dom (judgment_config.blocked_by_HS01A)"}
    case_state, underlag = _bygg_l4_underlag(state)
    if case_state is None:
        return {"_status": "UNDERLAG_SAKNAS", "_detail": str(underlag)}
    # Samma grenval som canonical L9: utan dom i akten (JUDGMENT_AUDIT) gäller
    # FUP-analysgrenen, inte domskälsmatrisen.
    if state.mode == "JUDGMENT_CONSTRUCTION":
        state.case_meta["domskal"] = {
            "status": "UPPSKJUTEN_TILL_CANONICAL_GATE",
            "skäl": "L11 körs före canonical subsumtionsgate; juridisk konstruktion får inte föregå gate-beslutet",
        }
        return {
            "_status": "UPPSKJUTEN",
            "_detail": "subsumtionskonstruktion skjuten upp till canonical efter gate-beslut",
        }
    if state.mode == "JUDGMENT_AUDIT":
        fup = _load("fup_analysis_agent", "runtime/fup_analysis_agent.py")
        if fup is None or not hasattr(fup, "akten_innehåller_dom"):
            return {"_status": "EJ_KÖRBAR", "_detail": "domsdetektion (fup_analysis_agent) kunde inte laddas"}
        if not fup.akten_innehåller_dom(case_state):
            state.case_meta["domskal"] = {"status": "EJ_TILLÄMPLIG",
                                          "skäl": "dom saknas i akten - FUP-analysgren körs i canonical L9"}
            return {"_status": "EJ_TILLÄMPLIG",
                    "_detail": "dom saknas i akten - FUP-analysgren körs i canonical L9"}
    dm = _load("domskals_matris_agent", "runtime/domskals_matris_agent.py")
    if dm is None or not hasattr(dm, "DomskälsmatrisAgent"):
        return {"_status": "EJ_KÖRBAR", "_detail": "domskals_matris_agent kunde inte laddas"}
    agent = dm.DomskälsmatrisAgent()
    fynd, kedjor = agent.run(case_state)
    state.__dict__["_förberett_l9"] = {"fynd": fynd, "kedjor": kedjor}
    state.case_meta["domskal"] = {
        "fynd": [_fynd_dict(f) for f in fynd],
        "kedjor": [_fynd_dict(k) for k in kedjor],
    }
    return {"_status": "OK", "fynd": len(fynd), "kedjor": len(kedjor),
            "_detail": f"{len(fynd)} domskälsfynd, {len(kedjor)} kedjor"}


def step_bevisstyrka(state: OrchestrationState) -> Dict:
    """L6: bevisstyrka per rekvisit (bevisstyrka_kalkylator). Kräver rekvisit -
    utan rekvisit körs inget (rekvisitdefinitioner saknas: HS11)."""
    bk = _load("bevisstyrka_kalkylator", "runtime/bevisstyrka_kalkylator.py")
    if bk is None:
        return {"_status": "EJ_KÖRBAR", "_detail": "bevisstyrka_kalkylator kunde inte laddas"}
    if not state.rekvisit:
        state.case_meta["bevisstyrka"] = {"status": "EJ_KÖRBAR",
                                          "skäl": "inga rekvisit fastställda (HS11)"}
        return {"_status": "EJ_TILLÄMPLIG", "_detail": "inga rekvisit fastställda (HS11)"}
    bevis = [{"kategori": f.get("kategori", "C_BAKGRUND"), "beskrivning": f.get("name", ""),
              "källa": f.get("path", "")} for f in state.files]
    domän = state.domän or "SOL_LVU"
    res = [bk.beräkna_bevisstyrka(r, bevis, domän) for r in state.rekvisit]
    state.case_meta["bevisstyrka"] = {"status": "GENOMFÖRD", "domän": domän, "resultat": res}
    return {"_status": "OK", "_detail": f"{len(res)} rekvisit bedömda (INDIKATIV)"}



def _slutstatus_l14(state: OrchestrationState) -> None:
    """L14: bug_classifier -> severity_engine -> final_audit_state, alltid."""
    bug_res: Dict[str, Any] = {}
    bc = _load("bug_classifier", "runtime/bug_classifier.py")
    if bc and hasattr(bc, "klassificera_buggar"):
        bug_res = bc.klassificera_buggar(
            hard_stops=list(state.hard_stops),
            flaggor=list(state.case_meta.get("flaggor") or []),
        ) or {}
        state.case_meta["buggar"] = bug_res
    se = _load("severity_engine", "runtime/severity_engine.py")
    if se and hasattr(se, "klassificera_severity"):
        state.case_meta["severity"] = se.klassificera_severity(
            buggar=bug_res.get("buggar") or [])
    fa = _load("final_audit_state", "runtime/final_audit_state.py")
    if fa and hasattr(fa, "bygg_final_audit_state"):
        state.case_meta["final_audit_state"] = fa.bygg_final_audit_state(
            pipeline_state=state, bug_result=bug_res,
            zero_fel=state.zero_fel, hard_stops=list(state.hard_stops))


def step_finalize(state: OrchestrationState) -> Dict:
    """Anropa canonical om inte CHAIN_ABORT. HARD_STOP/zero_fel = output, inte gate.

    Alt B-moduler (Grupp A): skill_reference_loader, vault_and_audit_engine.
    """
    _check_zero_inference(state)
    _kolla_min_source_coverage(state)
    _slutstatus_l14(state)
    if _is_chain_abort(state):
        abort = [c for c in state.hard_stops if c in CHAIN_ABORT_CODES]
        if state.zero_fel == "EJ_BEDÖMD":
            state.zero_fel = "UNDERLAG_SAKNAS"
        state.output = {
            "mode": state.mode,
            "hard_stops": state.hard_stops,
            "chain_abort": abort,
            "underlag_saknas": state.underlag_saknas,
            "claim_zero_fel": state.claim_zero_fel,
            "text_hard_stops": state.text_hard_stops,
            "status": "CHAIN_ABORT",
        }
        return {
            "_status": "HOPPAD",
            "hard_stops": state.hard_stops,
            "_detail": f"Kedjeavbrott {abort} — canonical ej anropad",
        }

    canonical = _load(
        "forensic_engine_v10_3_canonical",
        "runtime/forensic_engine_v10_3_canonical.py",
    )
    if canonical is None:
        state.hard_stops.append("HS_CANONICAL_MISSING")
        state.output = {
            "mode": state.mode,
            "hard_stops": state.hard_stops,
            "underlag_saknas": state.underlag_saknas,
            "status": "CHAIN_ABORT",
        }
        return {
            "_status": "HARD_STOP",
            "hard_stop_code": "HS_CANONICAL_MISSING",
            "_detail": "forensic_engine_v10_3_canonical.py kunde inte laddas.",
        }

    try:
        pm = state.mode
        PM = getattr(canonical, "ProcessMode", None)
        if PM is not None:
            try:
                pm = PM[state.mode] if state.mode in PM.__members__ else PM.JUDGMENT_AUDIT
            except Exception:
                pm = getattr(PM, "JUDGMENT_AUDIT", state.mode)

        out_dir = _utdatakatalog(state)
        # P1: tom akt — ingen full COMPLETE-export utan underlag
        if (getattr(state, "underlag_saknas", False) and not getattr(state, "files", None)) or (
            hasattr(state, "hard_stops") and any(
                str(h) in ("HS01B",) or "HS01B" in str(h)
                for h in (state.hard_stops or [])
            ) and not getattr(state, "files", None)
        ):
            state.output = state.output or {}
            state.output["canonical_skipped"] = True
            state.output["skäl"] = "UNDERLAG_SAKNAS — canonical ej körd för tom akt (P1)"
            state.output["status"] = "UNDERLAG_SAKNAS"
            return {"status": "UNDERLAG_SAKNAS", "canonical_skipped": True}
        # else: normal path
        case_state = _kör_canonical(state, canonical, pm, out_dir)
        hs = [getattr(x, "value", str(x)) for x in (getattr(case_state, "hard_stop_codes", None) or [])]
        ac = getattr(case_state, "audit_controller_verdict", None)
        ac_s = str(getattr(ac, "value", ac) or "")
        # Påståendenivå: markera overifierade claims (om canonical exponerar claims)
        claims = getattr(case_state, "claims", None) or []
        for c in claims:
            sid = getattr(c, "source_id", None) or (c.get("source_id") if isinstance(c, dict) else None)
            cid = getattr(c, "claim_id", None) or (c.get("claim_id") if isinstance(c, dict) else None)
            if not sid or sid == "SAKNAS":
                state.claim_zero_fel.append({
                    "claim_id": str(cid),
                    "zero_fel": "UNDERKAND",
                    "reason": "saknar källa / SAKNAS",
                })
        summary = {
            "case_id": getattr(case_state, "case_id", None),
            "pipeline_state": str(getattr(case_state, "pipeline_state", "")),
            "hard_stop_codes": hs,
            "hard_stop_active": bool(getattr(case_state, "hard_stop_active", False)),
            "hard_stop_triggered": bool(getattr(case_state, "hard_stop_triggered", False)),
            "hard_stop_chain_abort": bool(getattr(case_state, "hard_stop_chain_abort", False)),
            "requisite_gate_status": (
                "PASSERAD" if case_state.metadata.get("requisite_gate_passed") is True
                else "SPÄRRAD" if case_state.metadata.get("requisite_gate_passed") is False
                else "EJ FASTSTÄLLD"
            ),
            "l9_status": case_state.metadata.get("l9_status", "EJ FASTSTÄLLD"),
            "requisite_matrix": [
                canonical._jsonbar(r) for r in (getattr(case_state, "requisite_matrix", None) or [])
            ],
            "rekvisitmatris_status": str(getattr(case_state, "rekvisitmatris_status", "EJ_FASTSTÄLLD")),
            "process_mode": str(getattr(case_state, "process_mode", pm)),
            "audit_controller_verdict": ac_s,
            "underlag_saknas": state.underlag_saknas,
            "claim_zero_fel": list(state.claim_zero_fel),
            "text_hard_stops": list(state.text_hard_stops),
            "falsification_verdict": str(getattr(getattr(case_state, "falsification_verdict", None), "value", getattr(case_state, "falsification_verdict", ""))),
        }
        state.output = summary
        # Ärendenivå: inte UNDERKAND enbart för saknat underlag / enskilda claim-luckor
        if state.underlag_saknas and not claims:
            state.zero_fel = "UNDERLAG_SAKNAS"
        elif state.claim_zero_fel and not hs:
            state.zero_fel = "DELVIS"
        elif hs or ac_s in ("FLAGGAD", "UNDERKÄND", "STOPPAD", "UNDERKAND"):
            state.zero_fel = "DELVIS"
        else:
            state.zero_fel = "GODKAND"
        return {
            "_status": "OK",
            "_detail": "L16-pipeline körd via canonical.run_pipeline",
            "l16_summary": summary,
        }
    except Exception as e:
        state.hard_stops.append("HS_CANONICAL_ERROR")
        state.output = {
            "mode": state.mode,
            "hard_stops": state.hard_stops,
            "status": "CHAIN_ABORT",
            "error": f"{type(e).__name__}: {e}",
        }
        return {
            "_status": "HARD_STOP",
            "hard_stop_code": "HS_CANONICAL_ERROR",
            "_detail": f"Fel vid canonical: {type(e).__name__}: {e}",
        }


# ── KEDJA: varje modul pluggar automatiskt i nästa ───────────────────────────


def _check_zero_inference(state: "OrchestrationState") -> None:
    """Flagga claims utan källa om zero_inference aktiv. Stoppar inte kedjan."""
    if not _POLICY.get("zero_inference", True):
        return
    for claim in getattr(state, "claims", []) or []:
        if not isinstance(claim, dict):
            continue
        has_source = (
            claim.get("source")
            or claim.get("källa")
            or claim.get("citation")
            or claim.get("lagrum")
            or claim.get("source_id")
        )
        if has_source and str(has_source) not in ("", "SAKNAS", "None"):
            continue
        violation = str(claim.get("claim_id") or claim.get("text", "OKÄND")[:40])
        if violation not in state.zero_inference_violations:
            state.zero_inference_violations.append(violation)
            state.claim_zero_fel.append({
                "claim_id": violation,
                "zero_fel": "UNDERKAND",
                "skäl": "Påstående utan källhänvisning (zero_inference aktiv)",
            })



def _validera_domstol(forum: str, court_type: str) -> Dict:
    """Kontrollera forum/domstol mot court_profiles (indikativ)."""
    if not _COURT_PROFILES:
        return {"validerad": False, "skäl": "court_profiles ej laddad", "instansordning": []}
    profiles = _COURT_PROFILES
    # YAML-struktur: process_profiles / administrative_courts etc.
    pp = profiles.get("process_profiles") or {}
    profil = pp.get(forum) or pp.get(court_type) or {}
    if not profil and isinstance(profiles.get(forum), dict):
        profil = profiles[forum]
    if not profil:
        # fallback: sök under administrative_courts list
        for key in ("administrative_courts", "general_courts", "special_courts"):
            block = profiles.get(key)
            if isinstance(block, dict) and (forum in block or court_type in block):
                profil = block.get(forum) or block.get(court_type) or {}
                break
            if isinstance(block, list):
                for item in block:
                    if isinstance(item, dict) and (
                        item.get("forum") == forum or item.get("type") == court_type
                    ):
                        profil = item
                        break
    if not profil:
        return {
            "validerad": False,
            "skäl": f"Ingen profil för forum={forum}, court_type={court_type}",
            "instansordning": [],
        }
    return {
        "validerad": True,
        "instansordning": profil.get("instansordning") or profil.get("appeal_chain") or [],
        "praxispool": profil.get("praxispool") or [],
        "processordning": profil.get("processordning") or forum,
    }



def _kör_rattstidskontroll(state: "OrchestrationState") -> None:
    """Lagskifte om beslutsdatum i case_meta. Stoppar inte kedjan."""
    beslutsdatum = (
        state.case_meta.get("beslutsdatum")
        or state.case_meta.get("decision_date")
        or state.case_meta.get("datum")
    )
    if not beslutsdatum:
        state.case_meta["lagversion_status"] = "EJ_KONTROLLERAD - beslutsdatum saknas"
        flaggor = state.case_meta.setdefault("flaggor", [])
        if "RATTSTID_EJ_KONTROLLERAD_BESLUTSDATUM_SAKNAS" not in flaggor:
            flaggor.append("RATTSTID_EJ_KONTROLLERAD_BESLUTSDATUM_SAKNAS")
        state.text_hard_stops.append({
            "kod": "RATTSTID_EJ_KONTROLLERAD",
            "skäl": "beslutsdatum saknas i case_meta - intertemporal rättstillämpning ej prövad",
            "blockerande": False,
        })
        return
    # Steg 28: lagversion verifieras online (run_lagskifte_verifierad) i stället
    # för mot lagskiftesregistret. Utfallet är alltid VERIFIERAD, HARD_STOP
    # (HS_VERIFIERINGSGRIND, ej belagt i källan) eller FAILED (tekniskt källfel).
    # VERSION_OKLAR kan inte längre uppstå här. HS11 sätts inte längre av detta
    # steg: enligt hard_stop_register betyder HS11 "Subsumtionskedja saknar
    # rättsfaktum", inte oklar lagversion. Den tidigare hårdkodade listan
    # ["SoL", "FPL", "SFB"] (lagnamn utan paragraf, oberoende av ärendet) är
    # borttagen: utan lagrum i materialet finns inget att pröva
    # (INGET_JURIDISKT_PÅSTÅENDE, samma begrepp som verifieringsgrinden).
    # case_meta["lagversion_kontroll"]["status"] anger att steget kördes
    # (GENOMFÖRD); det rättsliga utfallet står i ["utfall"].
    try:
        from lagskifte_validator import run_lagskifte_verifierad
        from verifieringsgrind import HS_KOD, STATUS_INGET
        lagrum = []
        for claim in (state.claims or []):
            if isinstance(claim, dict):
                lag = claim.get("lagrum") or claim.get("lag")
                if isinstance(lag, str):
                    lagrum.append(lag)
                elif isinstance(lag, list):
                    lagrum.extend(x for x in lag if isinstance(x, str))
        if not lagrum:
            state.case_meta["lagversion_kontroll"] = {
                "status": "GENOMFÖRD", "utfall": STATUS_INGET,
                "beslutsdatum": str(beslutsdatum),
                "skäl": "inga lagrum i materialets påståenden - ingen lagversion att pröva",
            }
        else:
            resultat = run_lagskifte_verifierad(
                lagrum_lista=lagrum, beslutsdatum_str=str(beslutsdatum),
            )
            utfall = resultat.get("status")
            state.case_meta["lagversion_kontroll"] = {
                **resultat, "status": "GENOMFÖRD", "utfall": utfall,
            }
            if utfall == "HARD_STOP":
                if HS_KOD not in state.hard_stops:
                    state.hard_stops.append(HS_KOD)
                state.text_hard_stops.append({
                    "kod": HS_KOD, "skäl": f"lagversion ej belagd: {resultat.get('skäl', '')}",
                    "blockerande": True,
                })
            elif utfall == "FAILED":
                state.case_meta["lagversion_status"] = f"FAILED: {resultat.get('fel', '')}"
                state.text_hard_stops.append({
                    "kod": resultat.get("kod", "FAILED_VERIFIERING"),
                    "skäl": f"tekniskt källfel vid lagversionsprövning: {resultat.get('fel', '')}",
                    "blockerande": True,
                })
    except Exception as e:
        state.case_meta["lagversion_status"] = f"FAILED: {type(e).__name__}: {e}"
    # rattstids_bridge: intertemporär rättsanalys via Motor B RättstidskontrollAgent
    try:
        rb_mod = _load("sfcae_rattstid_bridge", "integrations/rattstids_bridge.py")
        if rb_mod and hasattr(rb_mod, "run_rattstidskontroll"):
            legal_rules = []
            for claim in (state.claims or []):
                if isinstance(claim, dict):
                    lag = claim.get("lagrum") or claim.get("lag")
                    if isinstance(lag, str):
                        legal_rules.append(lag)
                    elif isinstance(lag, list):
                        legal_rules.extend(lag)
            # Ingen hårdkodad standardlista (tidigare SoL/FPL/SFB oavsett
            # ärende) — utan lagrum ur materialet: EJ AKTIVERAD.
            rb_result = rb_mod.run_rattstidskontroll(
                records=state.claims or [],
                legal_rules=legal_rules,
                beslutsdatum=str(state.case_meta.get("beslutsdatum") or ""),
            )
            state.case_meta["rattstidskontroll_bridge"] = rb_result
    except Exception as e:
        # Tidigare `pass` — felet doldes helt.
        state.case_meta["rattstidskontroll_bridge"] = {
            "status": "FEL", "fel": f"{type(e).__name__}: {e}"}



def _validera_session_falt(state: "OrchestrationState") -> None:
    """
    Aktiverar session-fält: rekvisit och bilageförteckning.
    - Kopierar till case_meta för nedströms/optional runners
    - Flaggar rekvisit utan spårbar källhänvisning (lagrum/§) transparent
    Stoppar aldrig kedjan.
    """
    rek = list(getattr(state, "rekvisit", None) or [])
    bil = list(getattr(state, "bilageförteckning", None) or [])
    state.case_meta["session_rekvisit"] = rek
    state.case_meta["session_bilageförteckning"] = bil
    if state.domän:
        state.case_meta.setdefault("domän", state.domän)

    # Auto-fyll rekvisit från arende_config om tomma och domän känd
    if not rek and state.domän:
        try:
            from config_loader import standardrekvisit
            rek = list(standardrekvisit(state.domän) or [])
            state.rekvisit = rek
            state.case_meta["session_rekvisit"] = rek
            state.case_meta["rekvisit_källa"] = "arende_config.standardrekvisit"
        except Exception:
            pass

    saknar_spar = []
    for r in rek:
        s = str(r)
        has_ref = (
            "§" in s
            or any(x in s for x in ("SoL", "SFB", "FPL", "RB", "FL", "LVU", "LSS", "KL", "kap."))
        )
        if not has_ref:
            saknar_spar.append(s[:80])
            state.claim_zero_fel.append({
                "claim_id": f"REKVISIT:{s[:40]}",
                "zero_fel": "UNDERKAND",
                "skäl": "Session-rekvisit saknar spårbar laghänvisning",
            })
    if saknar_spar:
        state.case_meta["session_rekvisit_utan_källa"] = saknar_spar
        if "HS09" not in state.hard_stops:
            # transparent flag — not chain abort
            state.case_meta["session_rekvisit_varning"] = (
                f"{len(saknar_spar)} rekvisit utan laghänvisning"
            )


def _kolla_min_source_coverage(state: "OrchestrationState") -> None:
    """
    Policy: min_source_coverage. Icke-blockerande flagga om täckning < tröskel.
    underlag_saknas sätts True; hard_stop HS09B (låg källtäckning under
    tröskelvärde) läggs till utan CHAIN_ABORT. HS09 (förbjuden inferens) är
    en annan sak och sätts inte här (användarbeslut t66u).
    """
    try:
        thr = float(_MIN_SOURCE_COVERAGE)
    except Exception:
        thr = 0.85
    claims = list(getattr(state, "claims", None) or [])
    sources = list(getattr(state, "legal_sources", None) or [])
    # Om inga claims: täckning ej mätbar — lämna (HS01B/underlag hanteras separat)
    if not claims:
        state.case_meta["source_coverage"] = None
        state.case_meta["source_coverage_status"] = "EJ_MÄTBAR"
        return
    with_src = 0
    for c in claims:
        if not isinstance(c, dict):
            continue
        if c.get("source") or c.get("källa") or c.get("citation") or c.get("lagrum") or c.get("source_id"):
            with_src += 1
    coverage = with_src / max(len(claims), 1)
    # Endast verifierade rättskälleposter kan bidra till täckning.
    verified_sources = [
        source for source in sources
        if isinstance(source, dict)
        and source.get("official_source") == "VERIFIED"
        and source.get("current_status") != "REQUIRES_SEARCH_VERIFICATION"
    ]
    if verified_sources and claims:
        coverage = max(coverage, min(1.0, len(verified_sources) / max(len(claims), 1)))
    state.case_meta["source_coverage"] = round(coverage, 4)
    state.case_meta["source_coverage_threshold"] = thr
    if coverage < thr:
        state.underlag_saknas = True
        state.case_meta["source_coverage_status"] = "UNDER_TRÖSKEL"
        state.case_meta["source_coverage_varning"] = (
            f"source_coverage={coverage:.2f} < min_source_coverage={thr}"
        )
        if "HS09B" not in state.hard_stops:
            state.hard_stops.append("HS09B")
        if state.zero_fel == "GODKAND":
            state.zero_fel = "DELVIS"
        elif state.zero_fel == "EJ_BEDÖMD":
            state.zero_fel = "DELVIS"
    else:
        state.case_meta["source_coverage_status"] = "OK"


# ── PIPELINE CHAIN ────────────────────────────────────────────────────────────
# Ordning följer SFCAE-designprincipen:
#   DOMAR-ANALYS (neutral) → BEVIS/REKVISIT → MOTPARTS/KONTRADIKTORISK
#   → PARTS-MODELL → OUTPUT   (post-pipeline runners hanterar parts-output)
# Varje steg aktiveras om relevant, annars EJ_TILLÄMPLIG (kedjan avbryts ej).

def step_legal_merge(state: OrchestrationState) -> Dict:
    """Deterministisk sammanfogning av textutkast (LegalTextMergeAgent).

    Utkast: state.case_meta["utkast"] (lista med texter) eller aktfiler med
    "utkast" i namnet (.txt/.md). Färre än två -> EJ_TILLÄMPLIG; inga
    syntetiska indata. En konflikt ändrar aldrig pipeline_state - den
    redovisas i MERGE_STATUS och i presentationsvyn."""
    texter = [u for u in (state.case_meta.get("utkast") or []) if isinstance(u, str) and u.strip()]
    källa = "case_meta.utkast"
    if not texter:
        källa = "aktfiler *utkast*"
        for f in state.files:
            n = str(f.get("name", "")).lower()
            if "utkast" in n and n.endswith((".txt", ".md")):
                try:
                    texter.append(Path(f["path"]).read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError) as e:
                    state.case_meta.setdefault("legal_merge_ej_lästa", []).append(
                        f'{f.get("name")}: {type(e).__name__}')
    if len(texter) < 2:
        return {"_status": "EJ_TILLÄMPLIG", "_detail": f"{len(texter)} utkast ({källa}) - kräver minst två"}
    lm = _load("legal_text_merge_agent", "runtime/legal_text_merge_agent.py")
    if lm is None:
        return {"_status": "EJ_KÖRBAR", "_detail": "legal_text_merge_agent kunde inte laddas"}
    res = lm.LegalTextMergeAgent(
        show_source_tags=bool(state.case_meta.get("SHOW_SOURCE_TAGS"))).merge(texter)
    state.case_meta["legal_merge_output"] = res["output"]
    state.case_meta["legal_merge_anchors"] = res["anchors"]
    state.case_meta["legal_merge_status"] = res["MERGE_STATUS"]
    return {"_status": "OK", "_detail": f'{res["MERGE_STATUS"]}; {len(texter)} utkast ({källa}); '
                                        f'{len(res.get("konflikter") or [])} konflikter'}



def step_active_18(state: OrchestrationState) -> Dict[str, Any]:
    """Kör samtliga 18 tidigare fristående komponenter i huvudkedjan."""
    begärda = [
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
    ]

    resultat = _kör_begärda_moduler(state, begärda, None)

    resurser = {}
    for namn in (
        "component_map",
        "exception_census",
        "sfcae_cli",
        "technical_fixtures",
        "vittnesverifikation",
    ):
        modul = _load(namn, f"runtime/{namn}.py")
        resurser[namn] = {
            "status": "AKTIV" if modul is not None else "FEL"
        }

    state.case_meta["active_18_resultat"] = {
        "kedjemoduler": resultat,
        "resurser": resurser,
    }

    fel = [
        namn for namn, värde in resultat.items()
        if (värde or {}).get("status") in {"FEL", "EJ_REGISTRERAD", "EJ_BEGÄRD"}
    ]
    fel.extend(
        namn for namn, värde in resurser.items()
        if värde["status"] != "AKTIV"
    )

    return {
        "_status": "OK" if not fel else "FEL",
        "_detail": f"18 komponenter anropade; fel={len(fel)}",
        "resultat": state.case_meta["active_18_resultat"],
        "fel": fel,
    }


PIPELINE_CHAIN = [
    ("MODE",             "mode_router",           step_mode),
    ("FORUM",            "forum_detector",         step_forum),
    ("JURISDICTION",     "jurisdiction_adapter",   step_jurisdiction),
    ("L0_INGEST",        "ingest",                 step_ingest),
    ("L0_CATEGORIZE",    "evidence_categorizer",   step_categorize),
    ("L0_HYGIENE",       "source_hygiene",         step_source_hygiene),
    ("L2_CLAIMS",        "claim_classifier",       step_claims),
    ("L4_POSITIONS",     "process_position_agent", step_positions),
    ("L6_BEVISSTYRKA",   "bevisstyrka_kalkylator", step_bevisstyrka),
    ("L7_LEGAL",         "deep_search_pipeline",   step_legal_search),
    ("L8_REQUISITES",    "requisite_claim_mapper", step_requisites),
    ("MOD_ECONOMY",      "economy_bridge",         step_economy),
    ("MOD_SFB",          "socialforsakring_lager", step_socialforsakring),
    ("MOD_SOCIALTJÄNST", "socialtjanst_domain",    step_socialtjanst),
    ("MOD_HYRESRATT",    "hyresratt_domain",       step_hyresratt),
    ("MOD_LEGAL_MERGE",  "legal_text_merge_agent", step_legal_merge),
    # Kontradiktorisk kontroll — motparts-/kontradiktionsanalys (SFCAE architecture rule 4)
    # Aktiveras efter positioner är etablerade, före audit och finalize
    ("L10_KONTRA",       "kontradiktorisk_matris", step_kontradiktorisk),
    ("L11_DOMSKAL",      "domskals_matris_agent",  step_domskal),
    ("L12_14_AUDIT",     "audit_abc",              step_audit_abc),
    ("ACTIVE_18",        "active_18",              step_active_18),
    ("L16_FINALIZE",     "finalize",               step_finalize),
]


def run_dynamic_pipeline(
    root_dirs: Optional[List[str]] = None,
    mode: str = "JUDGMENT_AUDIT",
    case_meta: Optional[Dict] = None,
    output_dir: Optional[str] = None,
    session_id: Optional[str] = None,
    domän: Optional[str] = None,
    rekvisit: Optional[List[str]] = None,
    bilageförteckning: Optional[List[str]] = None,
    _run_id: Optional[str] = None,
    requested_modules: Optional[List[str]] = None,
    requested_params: Optional[Dict[str, Dict[str, Any]]] = None,
) -> OrchestrationState:
    """
    Kör hela kedjan dynamiskt. Varje steg får state från föregående.
    Irrelevanta moduler → EJ_TILLÄMPLIG (kedjan bryts inte).
    session_id laddar parametrar från session_context (ohårdkodat).

    _run_id: ett redan startat observability-run-id (t.ex. från
    mcp/server.py::call_tool() eller http_server.py::/pipeline). Om
    angivet äger anroparen run:et — den här funktionen avslutar det
    aldrig själv, bara skriver STEP_END-events i det. Annars startar
    och avslutar funktionen sitt eget run.

    requested_modules: kategori C-moduler (run_*_if_requested) som anroparen
    uttryckligen begär. De körs EFTER kedjan med requested=True och
    redovisas i case_meta["alt_b_resultat"]. Utan listan körs ingen av dem;
    de registreras bara i case_meta["_alt_b_register"].
    requested_params: valfria extra argument per begärd modul.
    """
    import time as _time
    import observability as _obs
    _äger_run = _run_id is None
    run_id = _run_id or _obs.start_run("dynamic_pipeline", meta={"mode": mode})
    _session_params: Dict[str, Any] = {}
    if session_id:
        try:
            from session_context import session_till_pipeline_params
            _session_params = session_till_pipeline_params(session_id) or {}
        except Exception as e:
            # Analysen kördes tidigare tyst som om ingen session angetts.
            # Utfallet följer nu med i case_meta (session_status).
            _session_params = {"case_meta": {"session_status": f"KAN EJ LÄSAS: {type(e).__name__}: {e}"}}

    _merged_meta = {**(_session_params.get("case_meta") or {}), **(case_meta or {})}
    _domän = domän or _session_params.get("domän") or _merged_meta.get("domän") or ""
    _rek = list(rekvisit or _session_params.get("rekvisit") or [])
    _bil = list(bilageförteckning or _session_params.get("bilageförteckning") or [])
    _mode = mode or _session_params.get("mode") or "JUDGMENT_AUDIT"
    _session_roots = _session_params.get("root_dirs") or ([_session_params.get("case_dir")] if _session_params.get("case_dir") else [])
    _roots = list(root_dirs or _session_roots)

    state = OrchestrationState(
        mode=_mode,
        root_dirs=_roots,
        case_meta=_merged_meta,
        domän=_domän,
        rekvisit=_rek,
        bilageförteckning=_bil,
    )
    _validera_session_falt(state)

    # Initialize knowledge base for pipeline access
    if _KNOWLEDGE_AVAILABLE:
        try:
            knowledge_loader = get_knowledge_loader()
            state.case_meta["_knowledge_available"] = True
            # Tidigare lästes .index via search_by_category.__self__, men
            # indexet fylldes aldrig och gav alltid en tom lista.
            _kat = getattr(knowledge_loader, "index", {}) or {}
            state.case_meta["_knowledge_categories"] = sorted(_kat.keys())
            state.case_meta["_knowledge_per_category"] = {k: len(v) for k, v in _kat.items()}
            if hasattr(knowledge_loader, "duplicates"):
                state.case_meta["_knowledge_duplicates"] = len(knowledge_loader.duplicates())
        except Exception:
            state.case_meta["_knowledge_available"] = False

    _registrera_resurser(state)
    try:
        state.case_meta["_alt_b_register"] = sorted(alt_b_register().keys())
        if _ALT_B_OPARSBARA:
            state.case_meta["_alt_b_oparsbara"] = dict(_ALT_B_OPARSBARA)
    except Exception as e:
        state.case_meta["_alt_b_register_fel"] = f"{type(e).__name__}: {e}"

    try:
        from layer_map import attach_layer_map_to_meta
        state.case_meta = attach_layer_map_to_meta(state.case_meta)
    except Exception:
        pass

    # Initialize all knowledge-consuming engines
    try:
        from processratt_scanner import load_procedure_protocols
        state.case_meta["_procedures_available"] = len(load_procedure_protocols())
    except Exception:
        pass

    try:
        from capability_map import load_architecture_knowledge
        state.case_meta["_architecture_available"] = len(load_architecture_knowledge())
    except Exception:
        pass

    try:
        from metadata_forensics_agent import load_miscellaneous_knowledge
        state.case_meta["_miscellaneous_available"] = len(load_miscellaneous_knowledge())
    except Exception:
        pass

    # Load all runtime-active resources
    try:
        from resource_loader import load_all_resources
        resources = load_all_resources()
        state.case_meta["_archive_available"] = len(resources.get('archive', {}))
        state.case_meta["_external_packs_available"] = len(resources.get('external_packs', {}))
        state.case_meta["_case_resources_available"] = len(resources.get('case_resources', {}))
        state.case_meta["_skill_definitions_available"] = len(resources.get('skill_definitions', {}))
        state.case_meta["_skill_references_available"] = len(resources.get('skill_references', {}))
    except Exception:
        pass

    # Consume external packs resources
    try:
        from external_packs_consumer import consume_external_packs
        ext_stats = consume_external_packs()
        state.case_meta["_external_packs_consumed"] = ext_stats.get('total_files', 0)
        state.case_meta["_external_packs_commands"] = ext_stats.get('commands', 0)
    except Exception:
        pass

    # Consume skill references
    try:
        from skill_references_consumer import consume_skill_references
        skill_ref_stats = consume_skill_references()
        state.case_meta["_skill_references_consumed"] = skill_ref_stats.get('total_references', 0)
        state.case_meta["_skills_with_references"] = skill_ref_stats.get('skills_loaded', 0)
    except Exception:
        pass

    # Consume case-specific resources — case_dir hämtas från aktivt ärende i sessionen.
    # Saknas case_dir laddas noll ärendespecifika resurser.
    try:
        from case_resources_consumer import consume_case_resources
        _active_case_dir = _session_params.get("case_dir") if isinstance(_session_params, dict) else None
        if not _active_case_dir:
            _active_case_dir = _merged_meta.get("case_dir")
        case_stats = consume_case_resources(case_dir=_active_case_dir)
        state.case_meta["_case_resources_consumed"] = case_stats.get('total_files', 0)
        state.case_meta["_case_impact"] = case_stats.get('case_impact', False)
        state.case_meta["_active_case_dir"] = case_stats.get('case_dir', '')
    except Exception:
        pass
    for step_id, module, fn in PIPELINE_CHAIN:
        _t0 = _time.perf_counter()
        _step(state, step_id, module, fn)
        _duration_ms = (_time.perf_counter() - _t0) * 1000
        _sr = state.steps[-1] if state.steps else None
        _obs.emit(
            run_id, "STEP_END", step_id=step_id, module=module,
            status=_sr.status if _sr else "OKÄND", duration_ms=_duration_ms,
            detail=(_sr.detail or _sr.error) if _sr else "",
        )
        # Efter HARD_STOP: övriga steg blir HOPPAD via _step (state.hard_stops)
        # Avbryt tidigt endast vid kritiskt FEL i MODE/INGEST utan hard_stop-registrering
        last = state.steps[-1] if state.steps else None
        if last and step_id in ("MODE", "L0_INGEST") and last.status == "FEL" and not state.hard_stops:
            break
    # Kategori C: alla registrerade moduler som standard om requested_modules är None.
    _eff_requested = sorted(alt_b_register().keys()) if requested_modules is None else list(requested_modules)
    if _eff_requested:
        alt_b = _kör_begärda_moduler(state, _eff_requested, requested_params)
        state.case_meta["alt_b_resultat"] = alt_b
        for _namn, _r in alt_b.items():
            _obs.emit(
                run_id, "STEP_END", step_id=f"ALT_B:{_namn}", module=_namn,
                status=str((_r or {}).get("status", "OKÄND")), duration_ms=0.0,
                detail=str((_r or {}).get("skäl", "")),
            )

    # Om avbruten före FINALIZE men hard_stops finns — sätt status
    if _is_chain_abort(state) and not state.output:
        state.output = {
            "mode": state.mode,
            "hard_stops": state.hard_stops,
            "status": "CHAIN_ABORT",
            "underlag_saknas": state.underlag_saknas,
        }
        if state.zero_fel == "EJ_BEDÖMD":
            state.zero_fel = "UNDERLAG_SAKNAS"
    elif state.underlag_saknas and not state.output:
        # finalize should have run; if not, minimal mark
        if state.zero_fel == "EJ_BEDÖMD":
            state.zero_fel = "UNDERLAG_SAKNAS"

    if output_dir:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        report = {
            "pipeline": "SFCAE_DYNAMIC_v10.3",
            "output": state.output,
            "steps": [asdict(s) for s in state.steps],
            "hard_stops": state.hard_stops,
            "active_modules": state.active_modules,
            "zero_fel": state.zero_fel,
            "integrations": {
                key: state.case_meta[key]
                for key in (
                    "source_hygiene", "claim_classification",
                    "claim_id_validation", "citation_analysis",
                )
                if key in state.case_meta
            },
            "alt_b_resultat": {
                k: (v.get("status") if isinstance(v, dict) else str(v))
                for k, v in (state.case_meta.get("alt_b_resultat") or {}).items()
            },
        }
        (out / "dynamic_pipeline_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # Kort markdown
        lines = [
            "# SFCAE Dynamic Pipeline Report",
            f"Mode: {state.mode}",
            f"Forum: {state.forum} | Court: {state.court_type}",
            f"Files: {len(state.files)} | Claims: {len(state.claims)}",
            f"Hard stops: {state.hard_stops or 'INGA'}",
            f"ZERO-FEL: {state.zero_fel}",
            "",
            "## Steg",
        ]
        for s in state.steps:
            lines.append(f"- [{s.status}] {s.step_id} ({s.module}) {s.detail or s.error}")
        (out / "dynamic_pipeline_report.md").write_text("\n".join(lines), encoding="utf-8")

    state.observability_run_id = run_id
    if _äger_run:
        # Exekveringsstatus är teknisk; spärrkoderna följer med separat.
        _obs.end_run(run_id, "HARD_STOP" if state.hard_stops else (state.zero_fel or "KLAR"), hard_stop_codes=list(state.hard_stops))

    return state

if __name__ == "__main__":
    import argparse
    import json
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="SFCAE Dynamic Pipeline"
    )
    parser.add_argument(
        "--root_dirs",
        nargs="+",
        required=True,
    )
    parser.add_argument(
        "--mode",
        default="JUDGMENT_AUDIT",
    )
    parser.add_argument(
        "--output",
        required=True,
    )
    parser.add_argument(
        "--domstol",
        default="",
    )
    parser.add_argument(
        "--maltyp",
        default="",
    )

    args = parser.parse_args()

    output_directory = Path(args.output).resolve()
    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    state = run_dynamic_pipeline(
        root_dirs=args.root_dirs,
        mode=args.mode,
        case_meta={
            "domstol": args.domstol,
            "måltyp": args.maltyp,
            "output_dir": str(output_directory),
        },
        output_dir=str(output_directory),
        domän="socialförsäkring",
    )

    active_step = next(
        (
            step
            for step in state.steps
            if step.step_id == "ACTIVE_18"
        ),
        None,
    )

    active_data = (
        active_step.data
        if active_step is not None
        else {}
    )

    active_result = (
        active_data.get("resultat")
        or {}
    )

    chain_results = (
        active_result.get("kedjemoduler")
        or {}
    )

    resource_results = (
        active_result.get("resurser")
        or {}
    )

    real_errors = []

    for module_name, module_result in chain_results.items():
        status = (
            module_result.get("status")
            if isinstance(module_result, dict)
            else "FEL"
        )

        if status in {
            "FEL",
            "EJ_REGISTRERAD",
            "EJ_BEGÄRD",
        }:
            real_errors.append(
                {
                    "modul": module_name,
                    "status": status,
                    "skäl": (
                        module_result.get("skäl", "")
                        if isinstance(module_result, dict)
                        else str(module_result)
                    ),
                }
            )

    for module_name, module_result in resource_results.items():
        status = (
            module_result.get("status")
            if isinstance(module_result, dict)
            else "FEL"
        )

        if status == "FEL":
            real_errors.append(
                {
                    "modul": module_name,
                    "status": status,
                    "skäl": (
                        module_result.get("skäl", "")
                        if isinstance(module_result, dict)
                        else str(module_result)
                    ),
                }
            )

    readable_status = {
        "OK": "Genomförd",
        "GENOMFÖRD": "Genomförd",
        "AKTIV": "Tillgänglig",
        "EJ_TILLÄMPLIG": "Inte relevant för materialet",
        "EJ_KÖRBAR": "Tillräckligt underlag saknas",
        "UNDERLAG_SAKNAS": "Tillräckligt underlag saknas",
        "FEL": "Tekniskt fel",
        "EJ_REGISTRERAD": "Inte ansluten",
        "EJ_BEGÄRD": "Anropades inte korrekt",
    }

    report_lines = [
        "# Samlad analysrapport",
        "",
        "## Analyserat material",
        "",
        f"Antal registrerade källfiler: {len(state.files)}",
        "",
    ]

    for file_record in state.files:
        report_lines.append(
            "- "
            + str(
                file_record.get("path")
                or file_record.get("name")
                or "Okänd fil"
            )
        )

    report_lines.extend(
        [
            "",
            "## Huvudanalys",
            "",
            f"Ärende-ID: {state.output.get('case_id', 'Saknas')}",
            (
                "Bearbetningstillstånd: "
                + str(
                    state.output.get(
                        "pipeline_state",
                        "Saknas",
                    )
                )
            ),
            (
                "Rekvisitkontroll: "
                + str(
                    state.output.get(
                        "requisite_gate_status",
                        "Saknas",
                    )
                )
            ),
            (
                "Auditresultat: "
                + str(
                    state.output.get(
                        "audit_controller_verdict",
                        "Saknas",
                    )
                )
            ),
            "",
            "## Komponentresultat",
            "",
        ]
    )

    for module_name, module_result in chain_results.items():
        if isinstance(module_result, dict):
            raw_status = module_result.get(
                "status",
                "Saknas",
            )
            reason = (
                module_result.get("skäl")
                or module_result.get("detail")
                or ""
            )
        else:
            raw_status = "FEL"
            reason = str(module_result)

        status_text = readable_status.get(
            raw_status,
            str(raw_status),
        )

        line = f"- {module_name}: {status_text}"

        if reason:
            line += f". {reason}"

        report_lines.append(line)

    for module_name, module_result in resource_results.items():
        raw_status = (
            module_result.get("status", "Saknas")
            if isinstance(module_result, dict)
            else "FEL"
        )

        report_lines.append(
            f"- {module_name}: "
            + readable_status.get(
                raw_status,
                str(raw_status),
            )
        )

    report_lines.extend(
        [
            "",
            "## Fel som måste åtgärdas",
            "",
        ]
    )

    if real_errors:
        for error in real_errors:
            report_lines.append(
                f"- {error['modul']}: "
                f"{error['skäl'] or error['status']}"
            )
    else:
        report_lines.append(
            "Inga tekniska komponentfel registrerades."
        )

    report_lines.extend(
        [
            "",
            "## Samlad status",
            "",
            (
                "Körningen är tekniskt genomförd."
                if not real_errors
                else
                "Körningen är inte tekniskt slutförd."
            ),
        ]
    )

    readable_report = (
        output_directory
        / "samlad_lasbar_rapport.md"
    )

    readable_report.write_text(
        "\n".join(report_lines),
        encoding="utf-8",
    )

    machine_report = (
        output_directory
        / "samlad_maskinrapport.json"
    )

    machine_report.write_text(
        json.dumps(
            {
                "canonical": state.output,
                "active_18": active_result,
                "source_files": state.files,
                "errors": real_errors,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    print(f"LÄSBAR_RAPPORT: {readable_report}")
    print(f"MASKINRAPPORT: {machine_report}")
    print(
        "ACTIVE_18_STATUS: "
        + (
            active_step.status
            if active_step is not None
            else "SAKNAS"
        )
    )
    print(f"VERKLIGA_FEL: {len(real_errors)}")

    if real_errors:
        print("STATUS: EJ SLUTFÖRD")
        raise SystemExit(1)

    print("STATUS: SLUTFÖRD")
    raise SystemExit(0)

def _ensure_moduler_och_regler_path():
    from pathlib import Path as _P
    import sys as _S
    _here = _P(__file__).resolve().parent
    for _cand in (_here.parent / 'moduler_och_regler', _P.cwd() / 'moduler_och_regler'):
        if _cand.is_dir() and str(_cand) not in _S.path:
            _S.path.insert(0, str(_cand))

