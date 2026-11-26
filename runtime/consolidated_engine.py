"""
CONSOLIDATED_ENGINE — Den konsoliderade arkitekturens entrypoint.

Kör:
  1. Motor C:s fullständiga pipeline (runtime/forensic_engine_v10_3_canonical.py)
     mot en ärenderot, med output till en SEPARAT mapp (aldrig i ärendet).
  2. Forumdetektor + rekvisit-modal-DSL (förverkligar legal_ai_core_config.md).
  3. Ny-mapp-unika funktioner via bridge: AgentCStressTest / AuditController /
     CounterAudit B01–B15 / HS19 närvarokontroll.
  4. Motor B-djupagenter (MetadataForensics, Röstanalys) mot Motor C-records.
  5. Sammanställer och skriver konsoliderad status + spårbarhet.

Ingen unik funktion raderas; varje integration rapporterar utfallet.
"""

from __future__ import annotations
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

_RUNTIME = Path(__file__).resolve().parent.parent / "runtime"
_ROOT = Path(__file__).resolve().parent.parent
_ENGINE = None

_SAFE_BASE = os.path.realpath(str(_ROOT))

# Skydd mot en felvald mapp (t.ex. hela hemkatalogen eller en disk av
# misstag) — se test_orkestrering.py::test_omfattningskontroll_finns_pa_den_kanoniska_vagen.
MAX_FILER_DEFAULT = 5000


def _case_paths():
    if str(_RUNTIME) not in sys.path:
        sys.path.insert(0, str(_RUNTIME))
    import case_paths
    return case_paths


def _safe_path(user_path: str, extra_roots: Optional[List[str]] = None) -> str:
    """Validerar user_path mot den centrala sökvägspolicyn (case_paths).

    Tidigare jämfördes enbart mot installationsroten, vilket gjorde det
    omöjligt att köra ett ärende utanför installationen — tvärt emot
    case_paths, där tillåten bas = installationsroten + SFCAE_CASE_ROOTS +
    de rötter operatören själv anvisat (extra_roots).
    """
    return _case_paths().safe_path(user_path, extra_roots=extra_roots)


def _kontrollera_omfattning(root_dirs: List[str], max_filer: int = MAX_FILER_DEFAULT) -> int:
    """Räknar filer under root_dirs och kastar ValueError om gränsen
    överskrids — en felvald mapp (t.ex. C:\\ eller hela hemkatalogen) ska
    stoppas innan Motor C försöker läsa den, inte upptäckas av att
    processen hänger eller kraschar."""
    antal = 0
    for root in root_dirs:
        for _dirpath, _dirnames, filnamn in os.walk(root):
            antal += len(filnamn)
            if antal > max_filer:
                raise ValueError(
                    f"Ärenderoten {root!r} innehåller fler än {max_filer} filer "
                    f"— kontrollera att rätt mapp valts innan körning."
                )
    return antal


def _kontrollera_outputkollision(output_dir: str, case_roots: List[str]) -> None:
    """Ett ärendes rapport får aldrig skrivas över av ett annat ärende.
    Läser en tidigare skriven sfcae_case_marker.json i output_dir (om den
    finns) och kastar ValueError om den pekar på andra ärenderötter."""
    marker_path = os.path.join(output_dir, "sfcae_case_marker.json")
    if not os.path.isfile(marker_path):
        return
    try:
        with open(marker_path, encoding="utf-8") as f:
            marker = json.load(f)
    except Exception as exc:
        # En markör som finns men inte går att läsa gav tidigare tyst
        # klartecken, varpå mappens innehåll skrevs över — exakt den förlust
        # kontrollen finns för att hindra. Någon körning har skrivit hit, men
        # vilket ärende det gällde går inte att avgöra: vägra.
        raise ValueError(
            "Utdatamappen innehåller en ärendemarkör som inte kan läsas.\n"
            f"  Mapp:   {output_dir}\n"
            f"  Markör: {marker_path}\n"
            f"  Fel:    {type(exc).__name__}: {exc}\n"
            "Välj en annan utdatamapp, eller ta bort markören om du vet att "
            "innehållet kan skrivas över."
        ) from exc
    tidigare = {os.path.realpath(r) for r in (marker.get("case_roots") or [])}
    nuvarande = {os.path.realpath(r) for r in case_roots}
    if tidigare and tidigare != nuvarande:
        raise ValueError(
            f"Outputmappen {output_dir!r} innehåller redan en rapport för "
            f"ett annat ärende ({sorted(tidigare)}). Välj en separat "
            f"outputmapp per ärende."
        )


def _skriv_case_marker(output_dir: str, case_roots: List[str]) -> None:
    marker_path = os.path.join(output_dir, "sfcae_case_marker.json")
    with open(marker_path, "w", encoding="utf-8") as f:
        json.dump({"case_roots": case_roots}, f, ensure_ascii=False, indent=2)


def _load_motor_c():
    """Motor C = canonical (STEG 2D).

    Återanvänder en redan importerad forensic_engine_v10_3_canonical under
    sys.modules i stället för att köra källfilen igen och skriva över
    cachen — annars uppstår en andra, icke-identisk kopia av dess klasser
    (AuditStatus, AuditControllerVerdict m.fl.), vilket gör att == och
    `is`-jämförelser mot instanser från den ursprungliga modulen tyst
    blir falska på tvärs genom hela pipelinen."""
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    if "forensic_engine_v10_3_canonical" in sys.modules:
        _ENGINE = sys.modules["forensic_engine_v10_3_canonical"]
        return _ENGINE
    path = _RUNTIME / "forensic_engine_v10_3_canonical.py"
    if not path.is_file():
        raise FileNotFoundError(f"Canonical motor saknas: {path}")
    if str(_RUNTIME) not in sys.path:
        sys.path.insert(0, str(_RUNTIME))
    spec = importlib.util.spec_from_file_location("forensic_engine_v10_3_canonical", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    _ENGINE = mod
    return mod



def _integrations():
    from forum_detector import detect_forum, classify_modal, RequisiteEvaluator
    from motor_b_agents import (run_metadata_forensics, run_rostanalys,
                                rattstidskontroll_available)
    from ny_runtime_bridge import get_unique_symbols, has_hs19, run_testsvit
    return locals()


def _hard_stop_flagga(csm, csm_dict: dict) -> bool:
    """Hard stop-flaggan ur motorns CaseState.

    CaseState bär fältet ``hard_stop_active`` (det är det L0/L00 och ModeRouter
    sätter). Tidigare lästes ``csm.hard_stop``, som inte finns, så flaggan blev
    alltid False även när HS01C stod i hard_stop_codes. En kod i
    hard_stop_codes utan aktiv flagga redovisas inte som "inget stopp":
    koderna räknas som stopp om motorn inte uttryckligen säger annat.
    """
    # En kod som hard_stop_register klassar som helstopp får aldrig redovisas
    # som hard_stop:false, oavsett vad flaggan säger (aldrig dolt blockerande fel).
    koder = [getattr(c, "value", c) for c in (getattr(csm, "hard_stop_codes", None)
                                              or csm_dict.get("hard_stop_codes") or [])]
    if _RUNTIME and str(_RUNTIME) not in sys.path:
        sys.path.insert(0, str(_RUNTIME))
    try:
        from hard_stop_register import helstopp_koder
        helstopp = set(helstopp_koder())
    except ImportError:
        # Registret kunde inte laddas: räckvidden går inte att avgöra, så
        # varje kod räknas som stopp (fail-closed — aldrig dolt stopp).
        return bool(koder) or bool(getattr(csm, "hard_stop_active", False)
                                   or csm_dict.get("hard_stop_active"))
    # Steg 8 (användarbeslut): varje HS-kod ger hard_stop=True oavsett räckvidd;
    # räckvidden redovisas separat i _hard_stop_räckvidd.
    if koder or set(map(str, koder)) & helstopp:
        return True
    if str(getattr(getattr(csm, "pipeline_state", None), "value", "")) == "HARD_STOP":
        return True
    if hasattr(csm, "hard_stop_active"):
        return bool(getattr(csm, "hard_stop_active"))
    if "hard_stop_active" in csm_dict:
        return bool(csm_dict["hard_stop_active"])
    if hasattr(csm, "hard_stop"):
        return bool(getattr(csm, "hard_stop"))
    return bool(csm_dict.get("hard_stop_codes") or getattr(csm, "hard_stop_codes", None))


_OK_STATUS = {"OK", "GENOMFÖRD", "EJ_TILLÄMPLIG", "EJ_BEGÄRD", "TILLGÄNGLIG",
              "BEVARAD_FUNKTIONSKALLA", "INGET_UNDERLAG", "HARD_STOP", "TOM",
              "KÖRD", "EJ AKTIVERAD"}


def _hard_stop_räckvidd(csm, csm_dict: dict) -> Dict:
    """Skiljer helstopp (avbryter ärendet) från flaggor med begränsad räckvidd
    (t.ex. HS11: subsumtion spärrad men övrig analys fortsätter)."""
    koder = [str(getattr(c, "value", c)) for c in (getattr(csm, "hard_stop_codes", None)
                                                   or csm_dict.get("hard_stop_codes") or [])]
    try:
        from hard_stop_register import helstopp_koder
        hel = set(helstopp_koder())
    except Exception:
        return {"helstopp": [], "begränsad": koder, "register": "EJ_LADDAT"}
    return {"helstopp": [k for k in koder if k in hel],
            "begränsad": [k for k in koder if k not in hel]}


def _cli_falt(csm, records, out: str, eng) -> Dict:
    md = getattr(csm, "metadata", {}) or {}
    f: Dict = {
        "files_count": len(records),
        "output_dir": out,
        "extraction_failed": bool(md.get("l2_extraction_failed")),
        "extraction_failed_reason": md.get("l2_extraction_failed_reason", ""),
        "requisite_matrix_count": len(getattr(csm, "requisite_matrix", []) or []),
    }
    try:
        from requisite_claim_mapper import RequisiteClaimMapper
        mb = RequisiteClaimMapper().identify_måltyp_detailed(csm)
        f.update({"måltyp": mb.måltyp, "måltyp_confidence": mb.confidence,
                  "måltyp_motivering": mb.motivering})
    except Exception as e:
        f.update({"måltyp": None, "måltyp_confidence": "FEL",
                  "måltyp_motivering": f"{type(e).__name__}: {e}"})
    if f["requisite_matrix_count"]:
        f["requisite_matrix_status"] = "BYGGD"
    elif not f.get("måltyp") or f.get("måltyp") == "okänd":
        f["requisite_matrix_status"] = "MÅLTYP_EJ_FASTSTÄLLD"
    else:
        f["requisite_matrix_status"] = "REKVISITDEFINITIONER_SAKNAS"
    try:
        f["ej_genomförda_steg"] = list(eng.ej_genomförda_steg(csm))
    except Exception as exc:
        f["ej_genomförda_steg"] = [s for s in (md.get("stegstatus") or [])
                                   if s.get("status") not in ("GENOMFÖRD", "EJ_TILLÄMPLIG")]
        f["ej_genomförda_steg_fallback_fel"] = f"{type(exc).__name__}: {exc}"
    return f


import re as _re

# "RB 35:1", "SoL 4 kap. 1 §", "FL 23 §" — förkortning först (lagskiftes form).
_LAGRUM_FÖRST = _re.compile(
    r"\b([A-ZÅÄÖ][A-Za-zÅÄÖåäö]{1,9})\s+(\d+\s*kap\.?\s*\d+\s*[a-z]?\s*§|\d+:\d+[a-z]?\b|\d+\s*[a-z]?\s*§)")
# "6 kap. 10 § BrB" — förkortning sist; vänds till förkortning först.
_LAGRUM_SIST = _re.compile(
    r"(\d+\s*kap\.?\s*\d+\s*[a-z]?\s*§)\s+([A-ZÅÄÖ][A-Za-zÅÄÖåäö]{1,9})\b")


def _lagrum_ur(text: str) -> List[str]:
    """Lagrumsreferenser i en regelsträng. Begrepp utan lagrum (t.ex.
    "beviskrav bortom rimligt tvivel") ger tom lista — de är inte lagrum och
    kan inte versionsprövas."""
    ut: List[str] = []
    for m in _LAGRUM_FÖRST.finditer(text):
        ut.append(f"{m.group(1)} {m.group(2).strip()}")
    for m in _LAGRUM_SIST.finditer(text):
        kand = f"{m.group(2)} {m.group(1).strip()}"
        if kand not in ut:
            ut.append(kand)
    return ut


def _kör_rattstid(csm, records, meta: Dict, fd: Dict) -> Dict:
    """Rättstidskontroll (FIX-T) körs — inte bara närvarokontrolleras.
    Regler = lagrum som canonical faktiskt registrerat (legal_sources.cited_law)
    + operatörens legal_rule. Utan regler: EJ AKTIVERAD (ärligt)."""
    regler: List[str] = []
    for ls in list(getattr(csm, "legal_sources", []) or []):
        cl = str(getattr(ls, "cited_law", "") or "").strip()
        if cl and cl not in regler and not cl.upper().startswith("EJ "):
            regler.append(cl)
    lr = str(meta.get("legal_rule") or "").strip()
    if lr and not lr.startswith("EJ ") and lr not in regler:
        regler.append(lr)
    # Endast lagrum versionsprövas. Rättsfrågor/begrepp utan lagrum redovisas
    # separat i stället för att ge skräpträffar ("in", "bevisk").
    lagrum: List[str] = []
    ej_lagrum: List[str] = []
    for r_ in regler:
        hittade = _lagrum_ur(r_)
        if hittade:
            lagrum.extend(h for h in hittade if h not in lagrum)
        else:
            ej_lagrum.append(r_)
    try:
        from rattstids_bridge import run_rattstidskontroll
        r = run_rattstidskontroll(
            records, lagrum,
            beslutsdatum=str(meta.get("beslutsdatum") or meta.get("relevant_date") or ""),
            berika_via_sok=bool(meta.get("tillåt_nätverk", True)),
            pipeline_state=csm)
        r["regler"] = regler
        r["lagrum_prövade"] = lagrum
        r["ej_lagrum"] = ej_lagrum
        return r
    except Exception as e:
        tillg = fd["rattstidskontroll_available"]()
        return {"status": "FEL", "fel": f"{type(e).__name__}: {e}", "tillgänglighet": tillg}


def _tar_parameter(fn, namn: str) -> bool:
    """True om fn deklarerar parametern namn. Osignerbara anrop (inbyggda)
    redovisas som False — då skickas parametern inte."""
    import inspect
    try:
        return namn in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _delfel(result: Dict) -> List[Dict]:
    """Samlar delkomponenter vars status inte är ett fullständigt utfall."""
    ut: List[Dict] = []
    for grupp in ("motor_b", "alt_b"):
        for namn, d in (result.get(grupp) or {}).items():
            st = d.get("status") if isinstance(d, dict) else None
            if st and str(st).upper() not in _OK_STATUS:
                ut.append({"komponent": f"{grupp}.{namn}", "status": st})
    ny = result.get("ny_testsvit")
    if isinstance(ny, dict) and str(ny.get("status", "")).upper() == "FEL":
        ut.append({"komponent": "ny_testsvit", "status": "FEL"})
    for s in result.get("ej_genomförda_steg") or []:
        ut.append({"komponent": f"canonical.{s.get('steg')}", "status": s.get("status"),
                   "skäl": s.get("skäl", "")})
    if result.get("extraction_failed"):
        ut.append({"komponent": "canonical.L2_extraktion", "status": "MISSLYCKAD",
                   "skäl": result.get("extraction_failed_reason", "")})
    return ut


def _kör_alt_b(begärda: List[str], csm, roots: List[str], out: str,
               meta: Dict, result: Dict) -> Dict:
    """Kör begärda kategori C-moduler mot samma CaseState (requested=True).
    Ett fel i en modul rapporteras på modulens nivå och stoppar inte analysen."""
    res: Dict[str, Dict] = {}
    from hard_stop_las import spärrsvar as _spärrsvar
    _låst = bool(_spärrsvar("alt_b", csm))
    for namn in begärda:
        try:
            if _låst and namn in ("steg13", "motor_c"):
                # Steg 14: den spärrade analysen får inte köras via Alt B.
                res[namn] = _spärrsvar(namn, csm)
                continue
            if namn == "steg13":
                from steg13_dynamic_legal_engine import run_steg13_if_requested
                res[namn] = run_steg13_if_requested(
                    case_state=csm, requested=True,
                    enable_network=bool(meta.get("tillåt_nätverk", True)),
                    relevant_date=str(meta.get("relevant_date") or ""))
            elif namn == "legal_source_chain":
                from legal_source_chain import run_legal_source_chain_if_requested
                res[namn] = run_legal_source_chain_if_requested(
                    case_state=csm, requested=True,
                    relevant_date=str(meta.get("relevant_date") or ""))
            elif namn == "motor_c":
                from motor_c_v10_v3 import run_motor_c_if_requested
                res[namn] = run_motor_c_if_requested(
                    root_dirs=roots, output_dir=out, case_meta=meta, requested=True)
            elif namn == "kallkedja":
                from kallkedja import run_kallkedja_if_requested
                mål = dict(meta.get("kallkedja") or {})
                if mål:
                    res[namn] = run_kallkedja_if_requested(case_state=csm, requested=True, **mål)
                else:
                    # Inget uttryckligt mål: spåra varje registrerat fynd (A/B/C)
                    # bakåt till sin källa — så att varje slutsats kan följas.
                    fynd = []
                    for attr in ("audit_a_findings", "audit_b_findings", "audit_c_findings"):
                        fynd.extend(getattr(csm, attr, []) or [])
                    spår = [run_kallkedja_if_requested(
                                case_state=csm, requested=True,
                                finding_id=getattr(f, "finding_id", None))
                            for f in fynd[:200] if getattr(f, "finding_id", None)]
                    res[namn] = {"status": "GENOMFÖRD" if spår else "INGET_UNDERLAG",
                                 "spårade_fynd": len(spår), "spår": spår}
            elif namn == "strikt_rapport":
                continue  # körs efter att resultatet är komplett
            else:
                from dynamic_pipeline import alt_b_register as _alt_b_reg, _load as _alt_b_load
                _reg = _alt_b_reg()
                _post = _reg.get(namn)
                if not _post:
                    res[namn] = {"status": "EJ_REGISTRERAD", "giltiga": sorted(_reg.keys())}
                else:
                    _mod = _alt_b_load(namn, _post["fil"])
                    _fn = getattr(_mod, _post["funktion"], None) if _mod else None
                    if _fn is None:
                        res[namn] = {"status": "EJ_KÖRBAR", "skäl": f"{_post['fil']} kunde inte laddas"}
                    else:
                        _claim_texter = [str(getattr(c, "content", "") if not isinstance(c, dict) else c.get("content", "")) for c in (getattr(csm, "claims", None) or [])]
                        _claim_texter = [t for t in _claim_texter if t and t.strip()]
                        _eff_text = str(meta.get("text") or "").strip() or "\n".join(_claim_texter)
                        _eff_roots = list(roots or [])
                        if not _eff_roots and out:
                            _in_dir = Path(out) / "_alt_b_input"
                            _in_dir.mkdir(parents=True, exist_ok=True)
                            _eff_roots = [str(_in_dir)]
                        _eff_out = str(Path(out) / "_alt_b_out") if out else ""
                        if _eff_out and any(Path(_eff_out).resolve() == Path(r).resolve() or Path(_eff_out).resolve().is_relative_to(Path(r).resolve()) for r in _eff_roots if r):
                            _eff_out = str(Path(out).parent / (Path(out).name + "_alt_b_out")) if out else ""
                        if _eff_out:
                            Path(_eff_out).mkdir(parents=True, exist_ok=True)
                        _eff_domän = meta.get("domän") or result.get("domän") or getattr(csm, "domän", None) or ""
                        _eff_rekv = list(meta.get("rekvisit") or []) or [(r.get("name") if isinstance(r, dict) else str(getattr(r, "name", r))) for r in (getattr(csm, "requisites", None) or [])]
                        _eff_rekv_lista = list(meta.get("rekvisit_lista") or []) or [{"rekvisit": r, "bevis": []} for r in _eff_rekv if r]
                        _eff_verdict = meta.get("verdict") or result.get("verdict") or result.get("slutbedömning")
                        _eff_utkast = list(meta.get("utkast") or []) or ([_eff_text] if _eff_text else [])
                        _eff_filer = list(meta.get("filer") or []) or list(getattr(csm, "files", None) or [])
                        _pool = {
                            "csm": csm, "claims": list(getattr(csm, "claims", None) or []), "records": list(getattr(csm, "claims", None) or []), "case_state": csm, "pipeline_state": csm, "state": csm, "context": csm,
                            "case_id": getattr(csm, "case_id", None) or meta.get("case_id") or "CASE",
                            "case_context": meta, "root_dirs": _eff_roots, "output_dir": _eff_out or out,
                            "case_meta": meta, "meta": meta, "domän": _eff_domän, "text": _eff_text,
                            "tidsordnade_texter": [item if isinstance(item, dict) else {"datum": "SAKNAS", "text": str(item)} for item in (list(meta.get("tidsordnade_texter") or []) or _claim_texter) if (isinstance(item, dict) and str(item.get("text") or "").strip()) or (not isinstance(item, dict) and str(item).strip())],
                            "beslutsdatum": meta.get("beslutsdatum") or meta.get("relevant_date") or "",
                            "beslutsdatum_str": str(meta.get("beslutsdatum") or meta.get("relevant_date") or ""),
                            "relevant_date": meta.get("relevant_date") or meta.get("beslutsdatum") or "",
                            "lag": meta.get("lag") or "SoL", "rekvisit": _eff_rekv,
                            "rekvisit_lista": _eff_rekv_lista, "lagrum_lista": list(meta.get("lagrum_lista") or []),
                            "bilageförteckning": list(meta.get("bilageförteckning") or []),
                            "utkast": _eff_utkast, "filer": _eff_filer, "verdict": _eff_verdict,
                            "output_path": meta.get("output_path") or (str(Path(out) / "strict_legal_report.md") if out else ""),
                            "requested": True,
                        }
                        _extra = (meta.get("requested_params") or {}).get(namn)
                        if isinstance(_extra, dict):
                            _pool.update(_extra)
                        _pool.setdefault("legal_rules", list(
                            ((_extra or {}).get("legal_rules") if isinstance(_extra, dict) else [])
                            or (meta or {}).get("legal_rules") or []
                        ))
                        _kwargs = {k: _pool[k] for k in _post["parametrar"] if k in _pool}
                        _ut = _fn(**_kwargs)
                        res[namn] = _ut if isinstance(_ut, dict) else {"status": "GENOMFÖRD", "resultat": _ut}
        except Exception as e:
            res[namn] = {"status": "FEL", "fel_typ": type(e).__name__, "fel": f"{type(e).__name__}: {e}"}
    return res


def _kör_verifieringsgrind(result: Dict, meta: Dict) -> Dict:
    """Steg 20: samlar systemets egna juridiska påståenden och kör
    verifieringsgrinden (nätverk på som standard). Ett undantag i grinden
    är ett tekniskt fel och blockerar (fail closed)."""
    try:
        from verifieringsgrind import Verifieringsgrind
        rt = (result.get("motor_b") or {}).get("rattstidskontroll") or {}
        delar = [str(x) for x in (rt.get("regler") or [])]
        lr = str(meta.get("legal_rule") or "")
        if lr and not lr.startswith("EJ "):
            delar.append(lr)
        if result.get("alt_b"):
            delar.append(json.dumps(result["alt_b"], ensure_ascii=False, default=str))
        g = Verifieringsgrind(tillåt_nätverk=bool(meta.get("tillåt_nätverk", True)))
        return g.verifiera_text("\n".join(delar), str(meta.get("relevant_date")
                                                     or meta.get("beslutsdatum") or ""))
    except Exception as e:
        return {"grindstatus": "FAILED", "output_släppt": False,
                "tekniska_fel": [f"verifieringsgrinden kunde inte köras: {type(e).__name__}: {e}"]}


def _vidarebefordra_legal_merge(meta: dict, out: str) -> dict:
    """legal_merge_output/anchors ur case_metadata -> presentation_views_v10.json."""
    if meta.get("legal_merge_output") is None:
        return {"status": "EJ_TILLÄMPLIG"}
    path = os.path.join(out, "presentation_views_v10.json")
    views_read_error = None
    try:
        with open(path, encoding="utf-8") as f:
            views = json.load(f)
    except FileNotFoundError:
        views = {}
    except (OSError, ValueError) as exc:
        views = {}
        views_read_error = f"{type(exc).__name__}: {exc}"
    views["legal_merge"] = {"output": meta.get("legal_merge_output"),
                            "anchors": meta.get("legal_merge_anchors"),
                            "status": meta.get("legal_merge_status")}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(views, f, ensure_ascii=False, indent=2)
    return {"status": "VIDAREBEFORDRAD", "fil": "presentation_views_v10.json"}


def consolidate(
    root_dirs: List[str],
    output_dir: str,
    case_metadata: Optional[Dict] = None,
    _expose_case_state: bool = False,
    max_filer: int = MAX_FILER_DEFAULT,
    anvisade_rotter: Optional[List[str]] = None,
) -> Dict:
    """anvisade_rotter: sökvägar som operatören själv anvisat explicit (CLI
    --case/--output). De utgör behörigheten enligt case_paths. Utelämnas de
    (t.ex. MCP-parametrar, som är härledda) gäller installationsroten +
    SFCAE_CASE_ROOTS."""
    import time
    # Vissa entrypoints kör med reducerad sys.path. Säkerställ att
    # runtime-paketet är synligt så att "observability" resolvas till
    # runtime/observability.py.
    _ROOT = Path(__file__).resolve().parent.parent
    _RUNTIME = _ROOT / "runtime"
    if str(_RUNTIME) not in sys.path:
        sys.path.insert(0, str(_RUNTIME))
    import observability as obs

    cp = _case_paths()
    safe_roots = [cp.resolve_case_root(_safe_path(r, anvisade_rotter)) for r in root_dirs]
    # Output är inte ärendedata: utöver de tillåtna baserna får den ligga i
    # systemets temp (CLI-standard och tekniska fixturer). Att den aldrig
    # ligger i/under en ärenderot kontrolleras nedan.
    import tempfile
    # Tom sökväg kanoniseras annars till processens aktuella katalog — i
    # praktiken produktmappen — och None blir strängen "None". Båda måste
    # stoppas innan sökvägen tolkas.
    if output_dir is None or not str(output_dir).strip():
        raise ValueError(
            "output_dir måste anges. Tom sökväg skulle skriva resultatet i "
            "den katalog processen råkar stå i, typiskt produktmappen."
        )
    out = _safe_path(output_dir, list(anvisade_rotter or []) + [tempfile.gettempdir()])
    run_id = obs.start_run("consolidated_engine")

    for r in safe_roots:
        if out == r or out.startswith(r + os.sep):
            raise ValueError("Outputmapp får inte vara/ligga under ärenderot.")

    _kontrollera_outputkollision(out, safe_roots)
    _kontrollera_omfattning(safe_roots, max_filer)

    os.makedirs(out, exist_ok=True)

    # 1) Motor C full pipeline
    eng = _load_motor_c()
    run = getattr(eng, "run_pipeline", None)
    if run is None:
        run = getattr(eng, "run_pipeline_v10")
    _t0 = time.perf_counter()
    import inspect as _inspect
    _kw = {}
    if _tar_parameter(run, "references_dir"):
        # Relativ "references" löstes mot aktuell katalog → minnesbanken
        # föll bort när CLI startades utanför installationen.
        _kw["references_dir"] = str(_ROOT / "references")
    csm = run(root_paths=safe_roots, output_dir=out, **_kw)
    _duration_ms = (time.perf_counter() - _t0) * 1000
    obs.emit(
        run_id, "STEP_END", step_id="MOTOR_C_PIPELINE",
        module="forensic_engine_v10_3_canonical", status="OK", duration_ms=_duration_ms,
    )
    records = list(getattr(csm, "files", []))

    # 2)–4) integrationer
    fd = _integrations()
    # Forum härleds ur aktmaterialets text (claims), inte ur filnamn:
    # FileRecord saknar attributet "filename", så detektorn fick tidigare
    # bara blanksteg och gav alltid EJ KLASSIFICERAD.
    combined = "\n".join(
        str(getattr(c, "content", "") or "") for c in (getattr(csm, "claims", []) or [])
    ).strip()
    forum = fd["detect_forum"](combined) if combined else {"status": "TOM", "forum": None}

    req_sample = []
    meta = case_metadata or {}
    # Nycklar i case_metadata som någon kodväg i consolidate faktiskt läser.
    # Övriga redovisas i case_metadata_ej_konsumerad: GUI:t skickar forum,
    # domstol och targettyp, som medvetet inte styr analysen (forum härleds
    # ur aktmaterialet; en operatörs uppgift om domstolsslag är ett
    # påstående, inte bevis) — men att de inte används ska framgå.
    KONSUMERADE_NYCKLAR = (
        "legal_rule", "requisite", "yrkande", "beslutsdatum", "relevant_date",
        "tillåt_nätverk", "kallkedja", "begärda_moduler", "requested_modules",
        # Sammanfogade utkast: vidarebefordras till presentationsvyn nedan.
        "legal_merge_output", "legal_merge_anchors", "legal_merge_status",
    )
    for key in ("legal_rule", "requisite", "yrkande"):
        if meta.get(key) and not str(meta.get(key)).startswith("EJ "):
            req_sample.append({"source": "metadata:" + key,
                               "text": str(meta[key]),
                               "modal": fd["classify_modal"](str(meta[key]))})

    ny_symbols = fd["get_unique_symbols"]()
    hs19 = fd["has_hs19"]()
    # AgentCStressTest / AuditController behöver en Ny-mapp CaseState; vi verifierar
    # att de är importerbara + att Ny-mappens egen testsvit körs senare i testet.
    try:
        ny_svensvit = fd["run_testsvit"]()
    except Exception as e:  # nätverksberoende delar kan saknas — aldrig tyst
        ny_svensvit = {"status": "FEL", "error_type": type(e).__name__, "reason": str(e)}

    motor_b = {
        "metadata_forensics": fd["run_metadata_forensics"](records),
        "rostanalys": fd["run_rostanalys"](records),
        "rattstidskontroll": _kör_rattstid(csm, records, meta, fd),
    }

    csm_dict = csm.to_dict() if hasattr(csm, "to_dict") else {}
    _legal_merge = _vidarebefordra_legal_merge(meta, out)

    result = {
        "consolidated_engine": "KONSOLIDERAD_ARKITEKTUR v1",
        "engine": "forensic_engine_v10_3_canonical",
        "base_engine_version": (getattr(eng, "MOTOR_VERSION", None)
                                or getattr(csm, "engine_version", None)
                                or csm_dict.get("engine_version") or "?"),
        "case_id": getattr(csm, "case_id", ""),
        "final_state": str(getattr(getattr(csm, "current_state", None)
                                   or getattr(csm, "pipeline_state", None), "value",
                                   getattr(csm, "current_state", None)
                                   or getattr(csm, "pipeline_state", None) or "")),
        "hard_stop": _hard_stop_flagga(csm, csm_dict),
        "hard_stop_räckvidd": _hard_stop_räckvidd(csm, csm_dict),
        "claims_count": csm_dict.get("claims_count", len(getattr(csm, "claims", []) or [])),
        "graph_edges_count": csm_dict.get("graph_edges_count", len(getattr(csm, "graph_edges", []) or [])),
        "hard_stop_codes": csm_dict.get(
            "hard_stop_codes",
            [getattr(c, "value", c) for c in (getattr(csm, "hard_stop_codes", []) or [])],
        ),
        "overall_status": csm_dict.get(
            "overall_status", getattr(getattr(csm, "overall_status", None), "value", None)
        ),
        # Steg 14: samma spärr-/giltighetsfält som case_state_v10.json, så att
        # artefakterna på disk kan jämföras fält för fält.
        "hard_stop_active": csm_dict.get("hard_stop_active"),
        "hard_stop_triggered": csm_dict.get("hard_stop_triggered"),
        "hard_stop_chain_abort": csm_dict.get("hard_stop_chain_abort"),
        "falsification_verdict": csm_dict.get("falsification_verdict"),
        "rekvisitmatris_status": csm_dict.get("rekvisitmatris_status"),
        "rekvisit_status": [r.get("status") for r in (csm_dict.get("requisite_matrix") or [])
                            if isinstance(r, dict)],
        "kritiska_pipelinefel": csm_dict.get("kritiska_pipelinefel") or [],
        "tekniskt_fel": csm_dict.get("tekniskt_fel"),
        "forum_detection": forum,
        "requisite_modal": req_sample,
        "ny_unique_symbols_present": ny_symbols,
        "hs19_present": hs19,
        "ny_testsvit": ny_svensvit,
        "motor_b": motor_b,
        "legal_merge": _legal_merge,
        "_observability_run_id": run_id,
    }
    ej_konsumerad = sorted(
        k for k, v in meta.items()
        if k not in KONSUMERADE_NYCKLAR and v not in (None, "", [])
    )
    _raw_begärda = meta.get("begärda_moduler") if "begärda_moduler" in meta else meta.get("requested_modules")
    if _raw_begärda is None:
        try:
            from dynamic_pipeline import alt_b_register as _alt_b_reg
            _begärda = sorted(_alt_b_reg().keys())
        except Exception:
            _begärda = []
    else:
        _begärda = list(_raw_begärda)
    if "motor_c" in [str(x) for x in _begärda]:
        # Hela case_metadata lämnas vidare till motor_c (Alt B); vad den
        # modulen läser redovisas där, inte här.
        result["case_metadata_vidarebefordrad_till"] = ["motor_c"]
    result["case_metadata_ej_konsumerad"] = ej_konsumerad
    # Fält som CLI-sammanställningen läser men som aldrig fylldes i — CLI
    # visade därför "Filer i akten 0" och "måltyp okänd" oavsett utfall.
    result.update(_cli_falt(csm, records, out, eng))

    # Alt B — uttryckligen begärda moduler (requested=True), samma ärende.
    begärda = [str(x) for x in (meta.get("begärda_moduler") or meta.get("requested_modules") or [])]
    if begärda:
        result["alt_b"] = _kör_alt_b(begärda, csm, safe_roots, out, meta, result)

    # Delresultatens nivå: ett delfel får aldrig se ut som en hel analys,
    # och ett hard stop får aldrig rapporteras som GENOMFÖRD.
    delfel = _delfel(result)
    for kod in (result.get("hard_stop_räckvidd") or {}).get("begränsad") or []:
        delfel.append({"komponent": "hard_stop", "status": kod,
                       "skäl": "flagga med begränsad räckvidd — berörd del spärrad, övrig analys körd"})
    result["delfel"] = delfel
    if result["final_state"] == "FAILED":
        # Tekniskt undantag - aldrig redovisat som domänspärr.
        result["analysnivå"] = "FAILED"
    elif result["hard_stop"]:
        result["analysnivå"] = "DELVIS"
    elif result["kritiska_pipelinefel"]:
        result["analysnivå"] = "KRITISKT_PIPELINEFEL"
    elif delfel:
        result["analysnivå"] = "DELVIS"
    else:
        result["analysnivå"] = "FULLSTÄNDIG"

    # Steg 20: obligatorisk verifieringsgrind före juridisk output.
    # De juridiska påståenden systemet självt för fram (registrerade lagrum,
    # operatörens legal_rule, Alt B-modulernas utdata) stäms av online mot
    # officiell källa. Ej belagt -> HARD_STOP (terminal domänspärr); tekniskt
    # fel -> FAILED (fail closed). Rapporten skrivs ändå för spårbarhet, men
    # juridiskt innehåll (Alt B, strikt rapport) släpps inte.
    result["verifieringsgrind"] = _kör_verifieringsgrind(result, meta)
    if not result["verifieringsgrind"].get("output_släppt"):
        gs = result["verifieringsgrind"].get("grindstatus")
        result["output_blockerad"] = True
        if result.get("alt_b"):
            result["alt_b"] = {"status": "BLOCKERAD_AV_VERIFIERINGSGRIND", "grindstatus": gs}
        if result["analysnivå"] != "FAILED":
            result["analysnivå"] = "DELVIS" 

    obs.end_run(
        run_id, {"HARD_STOP": "HARD_STOP", "DELVIS": "DELVIS", "FAILED": "FAILED",
                 "KRITISKT_PIPELINEFEL": "KRITISKT_PIPELINEFEL"}.get(result["analysnivå"], "GENOMFÖRD"),
        case_id=getattr(csm, "case_id", None), case_state_obj=csm,
        hard_stop_codes=[str(getattr(h, "value", h)) for h in (getattr(csm, "hard_stop_codes", None) or [])] or None,
    )

    if "strikt_rapport" in begärda and result.get("output_blockerad"):
        result.setdefault("alt_b", {})["strikt_rapport"] = {
            "status": "BLOCKERAD_AV_VERIFIERINGSGRIND",
            "grindstatus": result["verifieringsgrind"].get("grindstatus")}
    elif "strikt_rapport" in begärda:
        try:
            from strict_legal_report_generator import run_strict_report_if_requested
            result.setdefault("alt_b", {})["strikt_rapport"] = run_strict_report_if_requested(
                verdict={k: v for k, v in result.items() if not k.startswith("_")},
                output_path=os.path.join(out, "strikt_granskningspromemoria.md"),
                requested=True)
        except Exception as e:
            result.setdefault("alt_b", {})["strikt_rapport"] = {
                "status": "FEL", "fel_typ": type(e).__name__, "fel": f"{type(e).__name__}: {e}"}

    # Konsoliderad spårbarhetsrapport — skrivs till output, inte till ärendet.
    with open(os.path.join(out, "consolidated_engine_report.json"), "w",
              encoding="utf-8") as f:
        json.dump({k: v for k, v in result.items() if not k.startswith("_")},
                   f, ensure_ascii=False, indent=2, default=str)
    _skriv_case_marker(out, safe_roots)

    if _expose_case_state:
        # Endast för interna anropare (t.ex. sfcae_kallkedja) som behöver
        # det riktiga CaseState-objektet vidare — poppas alltid ut innan
        # svaret når en extern klient, läcker aldrig i den skrivna rapporten.
        result["_case_state_obj"] = csm
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Konsoliderad forensisk motor")
    ap.add_argument("case_roots", nargs="+")
    ap.add_argument("--output", required=True)
    ap.add_argument("--legal-rule", default="")
    ap.add_argument("--requisite", default="")
    a = ap.parse_args()
    meta = {"legal_rule": a.legal_rule, "requisite": a.requisite} if (a.legal_rule or a.requisite) else None
    r = consolidate(a.case_roots, a.output, meta)
    print("FINAL_STATE:", r["final_state"], "| HARD_STOP:", r["hard_stop"])
    print("FORUM:", r["forum_detection"].get("forum") or r["forum_detection"].get("status"))
    print("HS19:", r["hs19_present"])