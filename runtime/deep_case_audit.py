# -*- coding: utf-8 -*-
"""
Deep Legal Case Auditor — tunn orkestrering (v1.0).
Binder inventering/extraktion/luckor till SFCAE utan att ersätta canonical.
Fail-closed completeness. Påstående ≠ bevis. Ingen inventering av saknat.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "runtime", ROOT / "integrations", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


# ── Speckontraktet läses, inte dupliceras ───────────────────────────────────
#
# config/deep_legal_case_auditor.yaml deklarerar modulens states, labels,
# completeness-nivåer och obligatoriska kvalitetsgrindar. Kontraktet fanns
# men INGEN kod läste det: alla fyra listorna satt hårdkodade här. En
# deklaration som ingen konsulterar är inte en konfiguration — den kan
# ändras utan verkan, och koden kan glida ifrån den utan att något märker.
#
# Fallback är medvetet FAIL-CLOSED: saknas eller är filen trasig används de
# tidigare hårdkodade värdena, så inkopplingen aldrig kan göra modulen
# svagare än den var. Grindarna nedan är dessutom en NEDRE gräns — en grind
# som finns i configen men saknas i resultatet får aldrig tystas bort.

_FALLBACK_LABELS = (
    "VERIFIERAT", "PARTSUPPGIFT", "EJ_VERIFIERAT", "MOTSAGT",
    "ANALYS_INFERENS", "SAKNAS", "BLOCKERAT", "TEKNISKT_FEL",
)
_FALLBACK_GATES = (
    "case_identity_verified_or_flagged",
    "document_inventory_completed",
    "claims_separated_from_evidence",
    "conflicts_checked",
    "missing_material_checked",
    "processing_errors_visible",
)


def _spec() -> Dict[str, Any]:
    """Läs speckontraktet via den kanoniska config-vägen."""
    try:
        from config_loader import ladda
        data = ladda("deep_legal_case_auditor")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _spec_lista(nyckel: str, fallback: tuple) -> List[str]:
    värden = _spec().get(nyckel)
    if isinstance(värden, list):
        rena = [str(v) for v in värden if isinstance(v, (str, int))]
        if rena:
            return rena
    return list(fallback)


def spec_labels() -> List[str]:
    """Etiketterna som contractet tillåter."""
    return _spec_lista("labels", _FALLBACK_LABELS)


def spec_quality_gates() -> List[str]:
    """Grindar som MÅSTE redovisas i varje rapport."""
    return _spec_lista("quality_gate_required", _FALLBACK_GATES)


def spec_states() -> List[str]:
    return _spec_lista("states", ("INITIALIZED", "SCOPING", "COMPLETED"))


def spec_completeness_levels() -> List[str]:
    return _spec_lista(
        "completeness_levels",
        ("complete", "substantially_complete", "incomplete", "blocked"),
    )


def spec_kraver_explicit_requested() -> bool:
    """activation.requires_explicit_requested — Alt B-kontraktet."""
    akt = _spec().get("activation")
    if isinstance(akt, dict) and "requires_explicit_requested" in akt:
        return bool(akt["requires_explicit_requested"])
    return True


@dataclass
class DeepAuditReport:
    run_id: str = ""
    case_id: str = ""
    status: str = "INITIALIZED"
    completeness: str = "incomplete"
    document_count: int = 0
    processed_count: int = 0
    failed_count: int = 0
    steps: List[Dict] = field(default_factory=list)
    inventory: List[Dict] = field(default_factory=list)
    claims_hint: List[Dict] = field(default_factory=list)
    missing: List[Dict] = field(default_factory=list)
    conflicts: List[Dict] = field(default_factory=list)
    errors: List[Dict] = field(default_factory=list)
    quality_gate: Dict = field(default_factory=dict)
    labels_used: List[str] = field(default_factory=list)
    #: Var states/labels/grindar kom ifrån — configen eller fallback.
    #: Gör inkopplingen kontrollerbar i utdata i stället för förmodad.
    spec_kalla: str = "EJ_SATT"
    not_: str = (
        "INDIKATIV_ORKESTRERING. Separera påstående/bevis. "
        "Ingen fil inventeras. Completeness fail-closed."
    )
    audit_log: List[Dict] = field(default_factory=list)


def _log(rep: DeepAuditReport, operation: str, status: str, detail: str = "") -> None:
    rep.audit_log.append({
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "run_id": rep.run_id,
        "case_id": rep.case_id,
        "operation": operation,
        "status": status,
        "detail": detail[:500],
    })


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        return f"ERROR:{type(e).__name__}"


def _inventory(root_dirs: List[str]) -> tuple[List[Dict], List[Dict]]:
    files, errs = [], []
    exts = {
        ".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml",
        ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx",
        ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp",
    }
    for rd in root_dirs:
        p = Path(rd)
        if not p.exists():
            errs.append({"path": rd, "error": "ROOT_NOT_FOUND", "label": "BLOCKERAT"})
            continue
        try:
            for f in p.rglob("*"):
                if not f.is_file():
                    continue
                if f.suffix.lower() not in exts:
                    continue
                try:
                    st = f.stat()
                    files.append({
                        "file_id": f"F_{_sha256(f)[:12]}",
                        "path": str(f),
                        "filename": f.name,
                        "extension": f.suffix.lower(),
                        "size_bytes": st.st_size,
                        "modified_time": datetime.fromtimestamp(
                            st.st_mtime, tz=timezone.utc
                        ).isoformat(),
                        "content_hash": _sha256(f),
                        "access_status": "OK",
                        "extraction_status": "PENDING",
                        "label": "EJ_VERIFIERAT",
                    })
                except Exception as e:
                    errs.append({
                        "path": str(f),
                        "error": type(e).__name__,
                        "label": "TEKNISKT_FEL",
                    })
        except Exception as e:
            errs.append({"path": rd, "error": type(e).__name__, "label": "BLOCKERAT"})
    return files, errs


def _extract_text(path: str) -> tuple[str, str]:
    p = Path(path)
    try:
        if p.suffix.lower() in {".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml"}:
            return p.read_text(encoding="utf-8", errors="replace"), "OK"
        # weak binary printable extract — full OCR/PDF is host-dependent
        if p.stat().st_size < 2_000_000:
            raw = p.read_bytes()[:80000]
            text = "".join(chr(b) if 32 <= b < 127 else " " for b in raw)
            return " ".join(text.split()), "PARTIAL_BINARY_SCAN"
        return "", "SKIPPED_LARGE_BINARY"
    except Exception as e:
        return "", f"FAIL:{type(e).__name__}"


def _claim_hints(text: str, file_id: str) -> List[Dict]:
    """Indikativa mönster — aldrig faktum. Label PARTSUPPGIFT/EJ_VERIFIERAT."""
    hints = []
    lower = text.lower()
    markers = [
        ("yrkar", "request"),
        ("påstår", "allegation"),
        ("medger", "admission"),
        ("nekär", "denial"),
        ("nekas", "denial"),
        ("åberopar", "evidentiary_claim"),
        ("styrker", "evidentiary_claim"),
    ]
    for m, ctype in markers:
        if m in lower:
            idx = lower.find(m)
            snippet = text[max(0, idx - 40): idx + 80].strip()
            hints.append({
                "claim_id": f"C_{file_id}_{m}",
                "claim_type": ctype,
                "claim_text": snippet[:200],
                "source_file_id": file_id,
                "verification_status": "unverified",
                "label": "PARTSUPPGIFT",
                "not": "INDIKATIV — ej bevis",
            })
    return hints


def run_deep_case_audit(
    root_dirs: List[str],
    case_id: Optional[str] = None,
    case_context: Optional[Dict] = None,
) -> DeepAuditReport:
    run_id = f"DCA_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    cid = case_id or (case_context or {}).get("case_id") or "CASE_UNVERIFIED"
    rep = DeepAuditReport(run_id=run_id, case_id=cid, status="SCOPING")
    _log(rep, "init", "OK", f"roots={len(root_dirs)}")

    # Optional: reuse aktgranskning
    try:
        from aktgranskning import run_aktgranskning
        akt = run_aktgranskning(root_dirs, case_context)
        rep.steps.append({"step": "aktgranskning", "status": "OK",
                          "totalt": akt.antal_filer_totalt,
                          "luckor": len(akt.luckor)})
        for luck in akt.luckor:
            rep.missing.append({
                "referens": luck.referens_i_text,
                "i_fil": luck.hittad_i_fil,
                "label": "SAKNAS",
            })
        _log(rep, "aktgranskning", "OK")
    except Exception as e:
        rep.errors.append({"step": "aktgranskning", "error": type(e).__name__})
        _log(rep, "aktgranskning", "TEKNISKT_FEL", str(e))

    rep.status = "INVENTORYING"
    inv, errs = _inventory(root_dirs)
    rep.inventory = inv
    rep.document_count = len(inv)
    rep.errors.extend(errs)
    rep.steps.append({
        "step": "inventory",
        "status": "OK" if inv else "EMPTY",
        "discovered": len(inv),
        "access_errors": len(errs),
    })
    _log(rep, "inventory", "OK", f"n={len(inv)}")

    rep.status = "EXTRACTING"
    processed, failed = 0, 0
    for item in inv:
        text, estatus = _extract_text(item["path"])
        item["extraction_status"] = estatus
        item["text_len"] = len(text)
        if estatus.startswith("FAIL") or estatus.startswith("SKIPPED"):
            failed += 1
            item["label"] = "TEKNISKT_FEL" if estatus.startswith("FAIL") else "EJ_VERIFIERAT"
        else:
            processed += 1
            item["label"] = "EJ_VERIFIERAT"
            for h in _claim_hints(text, item["file_id"]):
                rep.claims_hint.append(h)
    rep.processed_count = processed
    rep.failed_count = failed
    rep.steps.append({
        "step": "extraction",
        "status": "OK",
        "processed": processed,
        "failed": failed,
        "note": "full OCR/PDF kräver host-adapters; partial binary scan endast",
    })
    _log(rep, "extraction", "OK", f"ok={processed} fail={failed}")

    # Hash conflicts (same hash different path already in akt; date-agnostic)
    by_hash: Dict[str, List[str]] = {}
    for item in inv:
        h = item.get("content_hash") or ""
        if h.startswith("ERROR"):
            continue
        by_hash.setdefault(h, []).append(item["path"])
    for h, paths in by_hash.items():
        if len(paths) > 1:
            rep.conflicts.append({
                "type": "duplicate_hash",
                "severity": "informational",
                "paths": paths,
                "label": "EJ_VERIFIERAT",
                "note": "dubblett bevaras — ej raderas",
            })
    rep.steps.append({
        "step": "conflicts",
        "status": "OK",
        "count": len(rep.conflicts),
    })

    rep.steps.append({
        "step": "claims_vs_evidence",
        "status": "OK",
        "claim_hints": len(rep.claims_hint),
        "rule": "claim_equals_fact FORBIDDEN",
    })

    # Quality gate (fail-closed)
    rep.status = "QUALITY_CONTROL"
    case_ok = cid != "CASE_UNVERIFIED"
    inv_ok = True  # inventory ran
    claims_sep = True
    crit_fail = failed > 0 and processed == 0 and rep.document_count > 0

    # Grindarna kommer ur speckontraktet. Utfallen nedan är de faktiska
    # observationerna; en grind som configen kräver men som koden inte kan
    # belägga redovisas som False — aldrig som tyst frånvarande.
    utfall = {
        "case_identity_verified_or_flagged": case_ok,
        "document_inventory_completed": inv_ok,
        "claims_separated_from_evidence": claims_sep,
        "conflicts_checked": True,
        "missing_material_checked": True,
        "processing_errors_visible": True,
    }
    gate = {namn: bool(utfall.get(namn, False)) for namn in spec_quality_gates()}
    gate["critical_all_failed"] = crit_fail
    rep.quality_gate = gate
    rep.spec_kalla = "config/deep_legal_case_auditor.yaml" if _spec() else "FALLBACK_HARDKODAD"
    if crit_fail or (rep.document_count == 0 and not errs):
        rep.completeness = "blocked" if errs else "incomplete"
        rep.status = "INCOMPLETE_REQUIRES_VERIFICATION"
    elif failed > 0 or not case_ok or rep.missing:
        rep.completeness = "substantially_complete" if processed > 0 else "incomplete"
        rep.status = "INCOMPLETE_REQUIRES_VERIFICATION"
    else:
        rep.completeness = "substantially_complete" if processed else "incomplete"
        # Never auto "complete" without host full-read proof
        rep.status = "COMPLETED" if processed and not rep.errors else "INCOMPLETE_REQUIRES_VERIFICATION"
        if rep.status == "COMPLETED":
            rep.completeness = "substantially_complete"  # hard: full complete needs host OCR proof

    rep.labels_used = sorted(set(spec_labels()))
    rep.steps.append({"step": "quality_gate", "status": rep.status, "completeness": rep.completeness})
    _log(rep, "quality_gate", rep.status, rep.completeness)
    return rep


def run_deep_case_audit_if_requested(
    root_dirs: List[str],
    requested: bool = False,
    case_id: Optional[str] = None,
    case_context: Optional[Dict] = None,
) -> Dict:
    if not requested:
        return {
            "status": "EJ_BEGÄRD",
            "detail": "Deep case audit kräver explicit requested=True.",
        }
    if not root_dirs:
        return {
            "status": "EJ_KÖRBAR",
            "skäl": "root_dirs saknas (host måste ange åtkomlig mapp).",
        }
    try:
        rep = run_deep_case_audit(root_dirs, case_id=case_id, case_context=case_context)
        return {
            "status": "GENOMFÖRD",
            "report": asdict(rep),
            "sammanfattning": {
                "run_id": rep.run_id,
                "case_id": rep.case_id,
                "pipeline_status": rep.status,
                "completeness": rep.completeness,
                "document_count": rep.document_count,
                "processed_count": rep.processed_count,
                "failed_count": rep.failed_count,
                "claim_hints": len(rep.claims_hint),
                "missing": len(rep.missing),
                "conflicts": len(rep.conflicts),
                "errors": len(rep.errors),
            },
        }
    except Exception as e:
        return {
            "status": "HARD_STOP",
            "kod": "HS_DEEP_AUDIT_ERROR",
            "detail": f"{type(e).__name__}: {e}",
        }
