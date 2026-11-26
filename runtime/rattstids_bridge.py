from __future__ import annotations
# SFCAE-BINDNING: rattstids_bridge
# Roll: Alt B-modul (rattstids_bridge)
# Alt B — anropas via requested=True från pipeline eller MCP.
_BUNDEN_TILL_SFCAE = True
_ROLL = "rattstids_bridge"


# SFCAE-BINDNING: rattstids_bridge
# Brygga för rättstidskontroll.
# Anropar lagskifte_validator — INTE motor_b i _deprecated.
# Kedja: rattstids_bridge → lagskifte_validator (aktiv runtime)

"""
RATTSTIDS_BRIDGE — Definierad integrationspunkt mellan relationsgraf-/rättskällelagret
och Motor B:s RättstidskontrollAgent (FIX-T, intertemporal laganalys).

Originalkod (runtime/metadata_forensics_agent.py) anropas orändrad via motor_b_agents-
modulens loader. Bryggan adapterar ENDAST dataform: filer som dict + graph.nodes med
LEGAL_RULE-noder byggda från verifierade rättskälleregistreringar (L7) och/eller
uttryckligen tillhandahållna rättsregler. Inget historiskt material skrivs om.

Status rapporteras ärligt: KÖRD (n regler kontrollerade) / EJ AKTIVERAD (inga
LEGAL_RULE-noder) / EJ TILLGÄNGLIG (Motor B saknar agenten).
"""

_BUNDEN_TILL_SFCAE = True
_ANROPARE = "step_jurisdiction via _kör_rattstidskontroll"
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT / "integrations", _ROOT / "runtime", _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from types import SimpleNamespace
from typing import Any, Dict, List

from motor_b_agents import _load_motor_b
DEEP_SEARCH_IMPORT_ERROR: str | None = None
try:
    from deep_search_pipeline import kör_deep_search_pipeline
except ImportError as exc:
    kör_deep_search_pipeline = None
    DEEP_SEARCH_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

class _GraphAdapter:
    """Exponerar nodes-dict som Motor B-agenten itererar (csm.graph.nodes.values())."""

    def __init__(self, nodes: Dict[str, Any]) -> None:
        self.nodes = nodes

class _CsmAdapter:
    """Dataform-adapter: files-dict + graf + findings/ hårdstopp-ytor."""

    def __init__(self, files_dict: Dict[str, Any], nodes: Dict[str, Any]) -> None:
        self.files = files_dict
        self.graph = _GraphAdapter(nodes)
        self.agent_a_findings: List[Dict] = []
        self.agent_b_findings: List[Dict] = []
        self.agent_c_findings: List[Dict] = []
        self.hard_stop = False
        self.hard_stop_reason = ""

def _fil_id(r: Any, i: int) -> str:
    if isinstance(r, dict):
        return str(r.get("file_id") or r.get("claim_id") or f"REC_{i:03d}")
    return str(getattr(r, "file_id", None) or getattr(r, "claim_id", None) or f"REC_{i:03d}")


def _lagskifte(legal_rules: List[str], beslutsdatum: str) -> Dict:
    """Den verkliga intertemporala kontrollen i sfcae (lagversion per beslutsdatum)."""
    try:
        from lagskifte_validator import run_lagskifte_if_requested
        return run_lagskifte_if_requested(list(legal_rules), requested=True,
                                          beslutsdatum_str=beslutsdatum or None)
    except Exception as e:
        return {"status": "FEL", "fel": f"{type(e).__name__}: {e}"}


def run_rattstidskontroll(records: List[Any],
                          legal_rules: List[str],
                          beslutsdatum: str = "",
                          berika_via_sok: bool = True,
                          pipeline_state: Any = None) -> Dict:
    """
    Rättstidskontroll (FIX-T): lagskifte_validator (lagversion per beslutsdatum)
    + Motor B RättstidskontrollAgent (agentens findings/HS06).

    Tidigare anropades agent.check_temporal_validity(), som inte finns i sfcae:s
    agent (den har kontrollera/perform_audit) — varje körning kastade
    AttributeError, och anroparen i dynamic_pipeline svalde felet tyst.
    """
    if not legal_rules:
        return {"status": "EJ AKTIVERAD",
                "reason": "Inga lagrum (kräver verifierade rättskälleregistreringar L7 eller tillhandahållna rättsregler)"}
    lagskifte = _lagskifte(legal_rules, beslutsdatum)

    m = _load_motor_b()
    agent_cls = getattr(m, "RättstidskontrollAgent", None)
    if agent_cls is None:
        return {"status": "DELVIS", "lagskifte": lagskifte,
                "agent": {"status": "EJ TILLGÄNGLIG", "reason": "RättstidskontrollAgent saknas i Motor B"}}

    files_dict = {_fil_id(r, i): r for i, r in enumerate(records or [])}

    nodes: Dict[str, Any] = {}
    for i, rule in enumerate(legal_rules or []):
        # Berika med Deep Search om tillgängligt
        enriched_label = rule
        if kör_deep_search_pipeline and berika_via_sok:
             try:
                 search_res = kör_deep_search_pipeline(rule, search_ids=["SEARCH_01"])
                 if search_res.get("SEARCH_01") and search_res["SEARCH_01"].data:
                     enriched_label += " [VERIFIERAD VIA RIKSDAGEN]"
             except Exception as exc:
                 enriched_label += f" [RIKSDAGEN_FEL: {type(exc).__name__}]"

        nodes[f"RULE_{i:02d}"] = SimpleNamespace(
            node_type="LEGAL_RULE", label=str(enriched_label), source_id=f"RULE_{i:02d}")

    if not nodes:
        return {"status": "EJ AKTIVERAD",
                "reason": "Inga LEGAL_RULE-noder (kräver verifierade rättskälleregistreringar L7 eller tillhandahållna rättsregler)"}

    csm = _CsmAdapter(files_dict, nodes)
    agent = agent_cls()
    metod = None
    for namn in ("check_temporal_validity", "perform_audit", "kontrollera"):
        if callable(getattr(agent, namn, None)):
            metod = namn
            break
    agent_utfall: Any = None
    if metod:
        agent_utfall = getattr(agent, metod)(csm)
    status = "KÖRD" if lagskifte.get("status") == "GENOMFÖRD" else "DELVIS"
    return {
        "status": status,
        "regler_kontrollerade": len(nodes),
        "lagskifte": lagskifte,
        "agent_metod": metod or "SAKNAS",
        "agent_utfall": agent_utfall,
        "agent_b_findings": csm.agent_b_findings,
        "hard_stop": csm.hard_stop,
        "hard_stop_reason": csm.hard_stop_reason,
        "beslutsdatum": beslutsdatum or "EJ ANGIVET — lagversion bedöms mot dagens datum/konfiguration",
        # Lagversionskontroll är indata, inte juridisk slutsats: körs även
        # under spärr, men spärren redovisas (steg 8).
        "domänspärr": _domänspärr(pipeline_state),
    }


def _domänspärr(pipeline_state: Any) -> Dict:
    import sys as _sys
    from pathlib import Path as _P
    _rt = str(_P(__file__).resolve().parents[1] / "runtime")
    if _rt not in _sys.path:
        _sys.path.insert(0, _rt)
    from hard_stop_las import las_hard_stop_koder, spärr_aktiv
    if pipeline_state is None:
        return {"aktiv": False, "koder": [], "källa": "EJ ANGIVEN"}
    koder = las_hard_stop_koder(pipeline_state)
    return {"aktiv": bool(koder) or spärr_aktiv(pipeline_state), "koder": koder}



def _run_rattstids_wrapper(requested: bool = False, **kwargs):
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "rattstids_bridge kräver requested=True."}
    st = kwargs.get("pipeline_state") or kwargs.get("state") or kwargs.get("case_state")
    meta = kwargs.get("case_meta") or kwargs.get("meta") or (getattr(st, "case_meta", None) if st is not None else {}) or {}
    records = kwargs.get("records")
    if not records and st is not None:
        records = getattr(st, "claims", None) if not isinstance(st, dict) else st.get("claims")
    legal_rules = kwargs.get("legal_rules") or (meta.get("legal_rules") if isinstance(meta, dict) else None)
    if not records:
        return {"status": "EJ_KÖRBAR", "skäl": "Saknar records för rättstidskontroll."}
    if not legal_rules:
        return {"status": "EJ_KÖRBAR", "skäl": "Saknar legal_rules för rättstidskontroll."}
    call_kwargs = dict(kwargs)
    call_kwargs["records"] = records
    call_kwargs["legal_rules"] = list(legal_rules)
    try:
        res = run_rattstidskontroll(**call_kwargs)
        if isinstance(res, dict):
            res.setdefault("status", "GENOMFÖRD")
            return res
        return {"status": "GENOMFÖRD", "resultat": res}
    except TypeError as e:
        return {"status": "EJ_KÖRBAR", "skäl": f"Saknade eller ogiltiga parametrar: {e}"}
    except Exception as e:
        return {"status": "FEL", "fel": f"{type(e).__name__}: {e}"}


def run_rattstidskontroll_if_requested(
    records: List[Any] = None,
    legal_rules: List[str] = None,
    beslutsdatum: str = "",
    berika_via_sok: bool = False,
    pipeline_state: Any = None,
    requested: bool = False,
    csm: Any = None,
    state: Any = None,
    case_state: Any = None,
    claims: Any = None,
    meta: Any = None,
    case_meta: Any = None,
) -> Dict[str, Any]:
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "rattstids_bridge kräver requested=True."}
    eff_records = list(records or [])
    if not eff_records:
        for src_obj in (claims, csm, case_state, state, pipeline_state):
            if isinstance(src_obj, list) and src_obj:
                eff_records = list(src_obj)
                break
            if src_obj is not None and getattr(src_obj, "claims", None):
                eff_records = list(getattr(src_obj, "claims") or [])
                break
    eff_rules = list(legal_rules or [])
    if not eff_rules:
        for m_obj in (meta, case_meta):
            if isinstance(m_obj, dict) and m_obj.get("legal_rules"):
                eff_rules = list(m_obj.get("legal_rules") or [])
                break
    if not eff_rules:
        for s_obj in (csm, case_state, state, pipeline_state):
            if s_obj is not None:
                s_meta = getattr(s_obj, "metadata", None) or getattr(s_obj, "case_meta", None) or {}
                if isinstance(s_meta, dict) and s_meta.get("legal_rules"):
                    eff_rules = list(s_meta.get("legal_rules") or [])
                    break
    if not eff_records:
        return {"status": "EJ_KÖRBAR", "skäl": "Saknar records för rättstidskontroll."}
    if not eff_rules:
        return {"status": "EJ_KÖRBAR", "skäl": "Saknar legal_rules för rättstidskontroll."}
    eff_ps = pipeline_state or csm or case_state or state
    return run_rattstidskontroll(
        records=eff_records,
        legal_rules=eff_rules,
        beslutsdatum=beslutsdatum,
        berika_via_sok=berika_via_sok,
        pipeline_state=eff_ps,
    )
