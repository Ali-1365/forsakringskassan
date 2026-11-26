# -*- coding: utf-8 -*-
"""
Central config-laddning med bevisad yaml.safe_load för aktiva config-filer.
REQ-013 / REQ-046: load-bevis + provisional_output_only True (fail-closed).
DYNAMIC DISCOVERY: Scannaar config/-mappen för alla .yaml/.json-filer automatiskt.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import sys

try:
    import yaml
    _YAML_OK = True
except ImportError:
    _YAML_OK = False

ROOT = Path(__file__).resolve().parent.parent

# Valfria Grupp A-moduler (Alt B — laddas on-demand via MCP):
# document_text_extractor, ocr_fallback, skill_reference_loader, vault_and_audit_engine, advocacy_analysis, advocacy_drafts
_GRUPP_A_OPTIONAL: tuple = (
    "document_text_extractor",
    "ocr_fallback",
    "skill_reference_loader",
    "vault_and_audit_engine",
    "advocacy_analysis",
    "advocacy_drafts",
)
CONFIG_DIR = ROOT / "config"

_cache: Dict[str, Any] = {}


# Sätts av _discover_all_configs() när uppräkningen av config/ avbryts mitt
# i — det som redan hittats behålls, men resten föll tidigare bort utan
# spår. None betyder en fullständig, obruten uppräkning.
_UPPTÄCKT_FEL: Optional[str] = None


def _discover_all_configs() -> Dict[str, Path]:
    """Scanna config/-mappen och returnera alla .yaml och .json-filer dynamiskt."""
    global _UPPTÄCKT_FEL
    _UPPTÄCKT_FEL = None
    if not CONFIG_DIR.exists():
        return {}

    configs = {}
    try:
        for config_file in CONFIG_DIR.glob("*"):
            if config_file.is_file() and config_file.suffix in [".yaml", ".yml", ".json"]:
                config_key = config_file.stem
                configs[config_key] = config_file
    except Exception as e:
        _UPPTÄCKT_FEL = f"config/ kunde inte räknas upp fullständigt: {type(e).__name__}: {e}"
        print(f"[CONFIG_LOADER] {_UPPTÄCKT_FEL}", file=sys.stderr)

    return configs


_AKTIVA_CONFIG = _discover_all_configs()


# ── FULLSTÄNDIGT CONFIG-REGISTER ────────────────────────────────────────────
# _AKTIVA_CONFIG omfattar bara parsbara datafiler (.yaml/.yml/.json). Övriga
# filer i config/ (t.ex. .md-specifikationer och avvecklade *.deprecated)
# föll tidigare helt utanför laddaren och syntes därför inte i runtime alls.
# Registret nedan räknar upp VARJE fil i config/ och klassar den generiskt
# utifrån filnamnets form — ingen fil pekas ut med namn:
#
#   AKTIV_DATA    .yaml/.yml/.json         → laddas via ladda()
#   DOKUMENT      .md/.txt                 → läses via ladda_dokument()
#   AVVECKLAD     *.deprecated             → registreras, parsas ALDRIG
#   ÄRENDEBUNDEN  *_case_snapshot_<ref>.*  → laddas endast för explicit
#                                            case_ref via ärendebundna_config()
#
# Registreringen ändrar inte vad ladda()/ladda_alla()/validera_alla() gör
# (bakåtkompatibelt för kategori A).

_DATA_SUFFIX = (".yaml", ".yml", ".json")
_DOKUMENT_SUFFIX = (".md", ".txt")
_AVVECKLAD_SUFFIX = ".deprecated"
_ÄRENDEBUNDEN_MARKÖR = "_case_snapshot_"


def _klassa_configfil(path: Path) -> str:
    namn = path.name.lower()
    if namn.endswith(_AVVECKLAD_SUFFIX):
        return "AVVECKLAD"
    if _ÄRENDEBUNDEN_MARKÖR in path.stem.lower():
        return "ÄRENDEBUNDEN"
    if path.suffix.lower() in _DATA_SUFFIX:
        return "AKTIV_DATA"
    if path.suffix.lower() in _DOKUMENT_SUFFIX:
        return "DOKUMENT"
    return "OKÄND_TYP"


def _discover_config_register() -> Dict[str, Dict[str, Any]]:
    register: Dict[str, Dict[str, Any]] = {}
    if not CONFIG_DIR.exists():
        return register
    try:
        for path in sorted(CONFIG_DIR.iterdir()):
            if not path.is_file():
                continue
            register[path.name] = {
                "fil": path.name,
                "sökväg": path,
                "nyckel": path.stem,
                "klass": _klassa_configfil(path),
            }
    except Exception as e:
        print(f"[CONFIG_LOADER] config-registret kunde inte byggas fullständigt: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
    return register


_CONFIG_REGISTER: Dict[str, Dict[str, Any]] = _discover_config_register()
_dokument_cache: Dict[str, str] = {}


def ladda(config_key: str) -> Optional[Dict]:
    if config_key in _cache:
        return _cache[config_key]

    path = _AKTIVA_CONFIG.get(config_key)
    if not path or not path.is_file():
        return None

    try:
        with path.open(encoding="utf-8") as f:
            if path.suffix == ".json":
                data = json.load(f)
            else:
                if not _YAML_OK:
                    return None
                data = yaml.safe_load(f)
        _cache[config_key] = data
        return data
    except Exception:
        return None


def system_policy() -> Dict:
    """Säkra defaults; provisional_output_only och zero_inference alltid True (fail-closed)."""
    policy = ladda("system_policy") or {}
    if not isinstance(policy, dict):
        policy = {}
    # Nested policy keys may live under top-level
    nested = policy.get("policy") if isinstance(policy.get("policy"), dict) else {}
    return {
        "provisional_output_only": True,
        "zero_inference": True,
        "fail_closed": bool(policy.get("fail_closed", nested.get("fail_closed", True))),
        "min_source_coverage": policy.get("min_source_coverage", nested.get("min_source_coverage", 0.85)),
        "max_hard_stops_before_abort": policy.get(
            "max_hard_stops_before_abort", nested.get("max_hard_stops_before_abort", 3)
        ),
    }


def court_profiles() -> Dict:
    return ladda("court_profiles") or {}


def evidence_standards() -> Dict:
    return ladda("evidence_standards") or {}


def legal_source_hierarchy() -> Dict:
    return ladda("legal_source_hierarchy") or {}


def judgment_config(mode: str) -> Dict:
    if mode == "JUDGMENT_AUDIT":
        return ladda("judgment_audit") or {}
    if mode == "JUDGMENT_CONSTRUCTION":
        return ladda("judgment_construction") or {}
    return {}


def audit_controller() -> Dict:
    return ladda("audit_controller") or {}


def ladda_alla() -> Dict[str, Optional[Dict]]:
    return {key: ladda(key) for key in _AKTIVA_CONFIG}


def validera_alla() -> Dict[str, str]:
    resultat = {}
    for key, path in _AKTIVA_CONFIG.items():
        if not path.is_file():
            resultat[key] = "SAKNAS"
            continue
        try:
            with path.open(encoding="utf-8") as f:
                if path.suffix == ".json":
                    json.load(f)
                else:
                    if not _YAML_OK:
                        resultat[key] = "FEL: yaml saknas"
                        continue
                    yaml.safe_load(f)
            resultat[key] = "OK"
        except Exception as e:
            resultat[key] = f"FEL: {e}"
    if _UPPTÄCKT_FEL:
        resultat["_upptäckt"] = f"ofullständig konfigurationsmängd — {_UPPTÄCKT_FEL}"
    return resultat


def arende_config() -> Dict:
    """Returnerar ärendekonfiguration (processordningar, domäner, lagskiften)."""
    return ladda("arende_config") or {}


def standardrekvisit(domän: str) -> List[str]:
    """Returnerar standardrekvisit för angiven domän."""
    config = arende_config()
    return list((config.get("standardrekvisit") or {}).get(domän, []) or [])


def processordning(domän_kod: str) -> Optional[str]:
    """Returnerar processordning för angiven domänkod."""
    config = arende_config()
    for d in config.get("domäner") or []:
        if isinstance(d, dict) and d.get("kod") == domän_kod:
            return d.get("processordning")
    return None


def kodsystem_nycklar() -> List[str]:
    """Alla config-nycklar som är kodsystemtabeller (config/kodsystem_*.yaml)."""
    return sorted(key for key in _AKTIVA_CONFIG if key.startswith("kodsystem_"))


def ladda_kodsystem(nyckel: str) -> Optional[Dict]:
    """Ladda en kodsystemtabell via den gemensamma config-vägen.

    Nyckeln är filstammens namn, t.ex. 'kodsystem_fk_sfb'. Okända nycklar
    och nycklar som inte är kodsystem returnerar None — ingen tyst fallback
    till en annan tabell.
    """
    if not isinstance(nyckel, str) or not nyckel.startswith("kodsystem_"):
        return None
    data = ladda(nyckel)
    if not isinstance(data, dict):
        return None
    return data


def ladda_alla_kodsystem() -> Dict[str, Dict]:
    """Ladda varje upptäckt kodsystemtabell. Trasiga filer utelämnas, inte gissas."""
    ut: Dict[str, Dict] = {}
    for nyckel in kodsystem_nycklar():
        data = ladda_kodsystem(nyckel)
        if data is not None:
            ut[nyckel] = data
    return ut


# ── REGISTER-API ─────────────────────────────────────────────────────────────


def config_register(validera: bool = True) -> List[Dict[str, Any]]:
    """
    Returnerar en post per fil i config/ med klass och laddningsutfall.

    status:
      LADDAD        datafil parsad utan fel
      FEL: ...      datafil som inte gick att parsa (redovisas, döljs inte)
      LÄSBAR        dokument som gick att läsa som UTF-8-text
      AVVECKLAD     registrerad men aldrig laddad (kategori D)
      ÄRENDEBUNDEN  laddas bara för sitt eget ärende (ingen läcka mellan ärenden)
    """
    resultat: List[Dict[str, Any]] = []
    for namn, post in _CONFIG_REGISTER.items():
        klass = post["klass"]
        rad: Dict[str, Any] = {
            "fil": namn,
            "nyckel": post["nyckel"],
            "klass": klass,
            "sökväg": str(Path("config") / namn),
        }
        if not validera:
            rad["status"] = "REGISTRERAD"
        elif klass == "AKTIV_DATA":
            rad["status"] = "LADDAD" if ladda(post["nyckel"]) is not None else _parsfel(post["sökväg"])
        elif klass == "DOKUMENT":
            rad["status"] = "LÄSBAR" if ladda_dokument(post["nyckel"]) is not None else "FEL: kunde inte läsas"
        elif klass == "AVVECKLAD":
            rad["status"] = "AVVECKLAD"
        elif klass == "ÄRENDEBUNDEN":
            rad["status"] = "ÄRENDEBUNDEN"
        else:
            rad["status"] = "OKÄND_TYP"
        resultat.append(rad)
    return resultat


def _parsfel(path: Path) -> str:
    try:
        with path.open(encoding="utf-8") as f:
            if path.suffix == ".json":
                json.load(f)
            else:
                if not _YAML_OK:
                    return "FEL: yaml saknas"
                data = yaml.safe_load(f)
                if data is None:
                    return "FEL: tom fil"
        return "FEL: okänt laddningsfel"
    except Exception as e:
        return f"FEL: {type(e).__name__}: {e}"


def ladda_dokument(nyckel: str) -> Optional[str]:
    """Läser ett DOKUMENT ur config/ (t.ex. en .md-specifikation) som text."""
    if nyckel in _dokument_cache:
        return _dokument_cache[nyckel]
    for post in _CONFIG_REGISTER.values():
        if post["klass"] == "DOKUMENT" and post["nyckel"] == nyckel:
            try:
                text = post["sökväg"].read_text(encoding="utf-8")
            except Exception:
                return None
            _dokument_cache[nyckel] = text
            return text
    return None


def avvecklade_config() -> List[str]:
    """Filer i config/ som är avvecklade (kategori D). Parsas aldrig."""
    return [n for n, p in _CONFIG_REGISTER.items() if p["klass"] == "AVVECKLAD"]


def _normalisera_ref(ref: str) -> str:
    return "".join(ch for ch in str(ref).lower() if ch.isalnum())


def ärendebundna_config(case_ref: Optional[str]) -> Dict[str, Any]:
    """
    Laddar config-filer bundna till ett specifikt ärende
    (<namn>_case_snapshot_<ref>.yaml). Matchning sker på normaliserad
    ärendereferens (bara bokstäver/siffror), så 'T 3098-23' matchar
    '..._t3098_23'. Utan case_ref laddas ingenting — inga ärendebundna data
    får läcka till ett annat ärende.
    """
    if not case_ref:
        return {}
    mål = _normalisera_ref(case_ref)
    if not mål:
        return {}
    ut: Dict[str, Any] = {}
    for namn, post in _CONFIG_REGISTER.items():
        if post["klass"] != "ÄRENDEBUNDEN":
            continue
        stem = post["nyckel"]
        idx = stem.lower().find(_ÄRENDEBUNDEN_MARKÖR)
        if idx < 0:
            continue
        ref_del = _normalisera_ref(stem[idx + len(_ÄRENDEBUNDEN_MARKÖR):])
        if ref_del != mål:
            continue
        data = ladda(stem)
        ut[stem] = data if data is not None else {"status": _parsfel(post["sökväg"])}
    return ut


# ── KODSYSTEM-REGISTER ───────────────────────────────────────────────────────
# Kodtabellerna config/kodsystem_*.yaml var tidigare bara nåbara via en
# hårdkodad domän→fil-karta i mcp/server.py. Tabeller som saknades i kartan
# (t.ex. JB_HYRESRATT, LSB_SKYDDAT_BOENDE, KONVERSATION) kunde därför aldrig
# väljas. Registret byggs nu generiskt ur filerna själva: meta.domän i varje
# tabell är nyckeln, filnamnets stamme är en alternativ nyckel.

_KODSYSTEM_PREFIX = "kodsystem_"


def kodsystem_register() -> Dict[str, List[str]]:
    """{DOMÄN eller filstam (versaler): [config/kodsystem_*.yaml, ...]}"""
    reg: Dict[str, List[str]] = {}
    for namn, post in _CONFIG_REGISTER.items():
        if post["klass"] != "AKTIV_DATA" or not post["nyckel"].startswith(_KODSYSTEM_PREFIX):
            continue
        rel = str(Path("config") / namn)
        data = ladda(post["nyckel"])
        domän = ""
        if isinstance(data, dict) and isinstance(data.get("meta"), dict):
            domän = str(data["meta"].get("domän") or "").strip().upper()
        nycklar = {post["nyckel"][len(_KODSYSTEM_PREFIX):].upper()}
        if domän:
            nycklar.add(domän)
        if isinstance(data, dict) and isinstance(data.get("meta"), dict):
            for a in (data["meta"].get("alias") or []):
                if str(a).strip():
                    nycklar.add(str(a).strip().upper())
        for k in nycklar:
            reg.setdefault(k, [])
            if rel not in reg[k]:
                reg[k].append(rel)
    return reg


def kodsystem_sökväg(domän: str) -> Optional[str]:
    """
    Löser en domän (meta.domän) eller filstam till en kodtabell under config/.
    Returnerar relativ sökväg eller None. Flera tabeller med samma meta.domän
    löses till den vars filstam är exakt domänen, annars den första i
    sorteringsordning (deterministiskt).
    """
    if not domän:
        return None
    reg = kodsystem_register()
    nyckel = str(domän).strip().upper()
    träffar = reg.get(nyckel) or []
    if not träffar:
        return None
    exakt = [p for p in träffar if Path(p).stem.upper() == _KODSYSTEM_PREFIX.upper() + nyckel]
    return (exakt or sorted(träffar))[0]


def _domän_token(domän: str) -> List[str]:
    return [t for t in str(domän).lower().replace("-", "_").split("_") if len(t) >= 5]


def domänbundna_config(domän: str) -> Dict[str, List[str]]:
    """
    Alla AKTIV_DATA-filer vars filstam innehåller ett signifikant ord (>=5
    tecken) ur domännamnet, t.ex. JB_HYRESRATT → hyresratt_gap_templates.yaml
    och kodsystem_jb_hyresratt.yaml. Returnerar {"kodsystem": [...],
    "övriga": [...]} med relativa sökvägar. Laddar inget innehåll.
    """
    token = _domän_token(domän)
    ut: Dict[str, List[str]] = {"kodsystem": [], "övriga": []}
    if not token:
        return ut
    for namn, post in _CONFIG_REGISTER.items():
        if post["klass"] != "AKTIV_DATA":
            continue
        stem = post["nyckel"].lower()
        if not any(t in stem for t in token):
            continue
        grupp = "kodsystem" if stem.startswith(_KODSYSTEM_PREFIX) else "övriga"
        ut[grupp].append(str(Path("config") / namn))
    exakt = kodsystem_sökväg(domän)
    if exakt:
        if exakt in ut["kodsystem"]:
            ut["kodsystem"].remove(exakt)
        ut["kodsystem"].insert(0, exakt)
    return ut

