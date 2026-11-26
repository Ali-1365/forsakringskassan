# -*- coding: utf-8 -*-
"""
Sessionskontext: ohårdkodad ärendeparameter-hantering.
Inga personuppgifter i kod. Sessionsdata i references/_sessions/.
"""
from __future__ import annotations

import json
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
SESSION_DIR = ROOT / "references" / "_sessions"
SESSION_DIR.mkdir(parents=True, exist_ok=True)

# database_manager: SQLite-fallback för audit-logging av sparade verdicts
# Skälet sparas i _DB_FEL: utan det gick det inte att skilja "ingen databas
# är installerad" från "databasen gick inte att öppna".
_DB_FEL: Optional[str] = None
try:
    import importlib.util as _ilu
    _dm_path = ROOT / "integrations" / "database_manager.py"
    if _dm_path.is_file():
        _spec = _ilu.spec_from_file_location("database_manager", _dm_path)
        _dm_mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_dm_mod)
        _DB_MANAGER = _dm_mod.DatabaseManager(str(ROOT / "references" / "_sessions" / "sfcae_audit.db"))
    else:
        _DB_MANAGER = None
        _DB_FEL = f"database_manager.py saknas på {_dm_path}"
except Exception as _e:
    _DB_MANAGER = None
    _DB_FEL = f"{type(_e).__name__}: {_e}"


def _session_id(arende_ref: str) -> str:
    return hashlib.sha256(arende_ref.encode()).hexdigest()[:16]


def spara_session(
    arende_ref: str,
    processordning: str,
    domän: str,
    forum: str,
    beslutsdatum: Optional[str] = None,
    instans: Optional[str] = None,
    rekvisit: Optional[List[str]] = None,
    bilageförteckning: Optional[List[str]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict:
    sid = _session_id(arende_ref)
    session = {
        "session_id": sid,
        "arende_ref": arende_ref,
        "skapad": datetime.now(timezone.utc).isoformat() + "Z",
        "processordning": processordning,
        "domän": domän,
        "forum": forum,
        "beslutsdatum": beslutsdatum,
        "instans": instans,
        "rekvisit": rekvisit or [],
        "bilageförteckning": bilageförteckning or [],
        "extra": extra or {},
        "not": "Sessionsdata innehåller inga personuppgifter.",
    }
    path = SESSION_DIR / f"{sid}.json"
    path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
    # SQLite-fallback: spara verdict-audit i database_manager. Utfallet
    # redovisas explicit — SPARAD betydde tidigare "allt sparades", även när
    # den här skrivningen hade fallerat tyst.
    if _DB_MANAGER is None:
        revisionslogg = f"EJ TILLGÄNGLIG: {_DB_FEL}" if _DB_FEL else "EJ KONFIGURERAD"
    else:
        try:
            _DB_MANAGER.save_verdict(sid, session)
            revisionslogg = "SKRIVEN"
        except Exception as e:
            revisionslogg = f"EJ SKRIVEN: {type(e).__name__}: {e}"
    return {"status": "SPARAD", "session_id": sid, "path": str(path), "revisionslogg": revisionslogg}


def ladda_session(session_id: str) -> Optional[Dict]:
    path = SESSION_DIR / f"{session_id}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _ladda_från_case_registry(arende_ref: str) -> Optional[Dict]:
    """
    Fallback: läser kanonisk ärenderegistrering från references/case_registry.yaml
    när ingen runtime-JSON finns. Returnerar ett minimalt sessions-dict som är
    kompatibelt med arende_aktivator och arende_loader.
    """
    registry_path = ROOT / "references" / "case_registry.yaml"
    if not registry_path.is_file():
        return None
    try:
        import yaml
        data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None

    ärenden = data.get("ärenden") or []
    arende_ref_norm = arende_ref.strip()

    for ä in ärenden:
        canonical = ä.get("canonical_id", "")
        original = ä.get("original_id", "")
        aliases = ä.get("aliases") or []
        all_ids = [canonical, original] + aliases
        if any(a.strip() == arende_ref_norm for a in all_ids if a):
            return {
                "session_id": _session_id(canonical),
                "arende_ref": canonical,
                "domän": ä.get("domän", ""),
                "forum": ä.get("forum", ""),
                "instans": ä.get("instans", ""),
                "processordning": ä.get("processordning", ""),
                "status": ä.get("status", "EJ_VERIFIERAT"),
                "verification_status": ä.get("verification_status", "EJ_VERIFIERAT"),
                "resource_policy": ä.get("resource_policy", "DOMAIN_RESOURCES_ONLY"),
                "case_dir": ä.get("case_dir"),
                "source_availability": ä.get("source_availability", "UNKNOWN"),
                "rekvisit": [],
                "bilageförteckning": [],
                "extra": {"case_resources": [], "from_registry": True},
                "not": "Laddad från case_registry.yaml — ingen runtime-JSON.",
            }
    return None


def ladda_session_via_ref(arende_ref: str) -> Optional[Dict]:
    session = ladda_session(_session_id(arende_ref))
    if session is not None:
        return session
    return _ladda_från_case_registry(arende_ref)


def lista_sessioner() -> List[Dict]:
    result = []
    seen_session_ids: set = set()

    for f in sorted(SESSION_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            sid = data.get("session_id")
            result.append({
                "session_id": sid,
                "arende_ref": data.get("arende_ref"),
                "domän": data.get("domän"),
                "forum": data.get("forum"),
                "skapad": data.get("skapad"),
                "källa": "runtime",
            })
            if sid:
                seen_session_ids.add(sid)
        except Exception as e:
            # En trasig sessionsfil hoppades tidigare över tyst — ärendet
            # försvann då ur listningen utan spår, omöjligt att skilja från
            # ett ärende som aldrig funnits.
            fel = f"{type(e).__name__}: {e}"
            result.append({
                "session_id": f.stem,
                "arende_ref": None,
                "domän": None,
                "forum": None,
                "skapad": None,
                "källa": "runtime",
                "status": "KAN EJ LÄSAS",
                "fel": fel,
            })
            print(f"[SESSION_CONTEXT] KAN EJ LÄSAS: {f.name}: {fel}", file=sys.stderr)
            continue

    # Fallback: registrerade ärenden utan runtime-JSON
    registry_path = ROOT / "references" / "case_registry.yaml"
    if registry_path.is_file():
        try:
            import yaml
            data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
            for ä in (data.get("ärenden") or []):
                canonical = ä.get("canonical_id", "")
                if not canonical:
                    continue
                sid = _session_id(canonical)
                if sid in seen_session_ids:
                    continue
                result.append({
                    "session_id": sid,
                    "arende_ref": canonical,
                    "domän": ä.get("domän", ""),
                    "forum": ä.get("forum", ""),
                    "skapad": None,
                    "källa": "registry",
                    "status": ä.get("status", ""),
                })
                seen_session_ids.add(sid)
        except Exception as e:
            # Ett trasigt case_registry.yaml tog tidigare bort samtliga
            # registrerade ärenden ur listningen på en gång, utan besked.
            fel = f"{type(e).__name__}: {e}"
            print(f"[SESSION_CONTEXT] case_registry.yaml kunde inte läsas: {fel}",
                  file=sys.stderr)
            result.append({
                "session_id": None,
                "arende_ref": None,
                "domän": None,
                "forum": None,
                "skapad": None,
                "källa": "registry",
                "status": "REGISTRET KAN EJ LÄSAS",
                "fel": fel,
            })

    return result


def radera_session(session_id: str) -> Dict:
    path = SESSION_DIR / f"{session_id}.json"
    if path.is_file():
        path.unlink()
        return {"status": "RADERAD", "session_id": session_id}
    return {"status": "HITTADES_INTE", "session_id": session_id}


def radera_alla_sessioner() -> Dict:
    raderade = 0
    for f in SESSION_DIR.glob("*.json"):
        f.unlink()
        raderade += 1
    return {"status": "RADERADE", "antal": raderade}


def session_till_pipeline_params(session_id: str) -> Optional[Dict]:
    session = ladda_session(session_id)
    if not session:
        return None
    extra = session.get("extra") or {}
    case_dir = session.get("case_dir") or extra.get("case_dir")
    root_dirs = extra.get("root_dirs") or ([case_dir] if case_dir else [])
    return {
        "mode": session.get("mode", "JUDGMENT_AUDIT"),
        "case_meta": {
            "arende_ref": session.get("arende_ref"),
            "beslutsdatum": session.get("beslutsdatum"),
            "forum": session.get("forum"),
            "instans": session.get("instans"),
            "domän": session.get("domän"),
            "case_dir": case_dir,
        },
        "rekvisit": session.get("rekvisit", []),
        "bilageförteckning": session.get("bilageförteckning", []),
        "domän": session.get("domän", ""),
        "case_dir": case_dir,
        "root_dirs": root_dirs,
    }
