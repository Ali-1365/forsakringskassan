# -*- coding: utf-8 -*-
"""
Metadata-forensik och rättstidskontroll.
Migrerad från _deprecated/motor_b.py — aktiv runtime, inget beroende till motor_b.
"""
from __future__ import annotations
import re
import sys
from typing import Any, Dict, List


def load_miscellaneous_knowledge() -> Dict[str, str]:
    """Laddar och läser diverse knowledge från 'other' kategori."""
    from knowledge_loader import search_knowledge, get_knowledge
    other = search_knowledge("other", by="category")
    if other:
        other_contents = {}
        for o in other:
            content = get_knowledge(o.relative_path)
            if content:
                other_contents[o.filename] = content

        print(f"[METADATA_FORENSICS] Read {len(other_contents)}/{len(other)} miscellaneous knowledge files", file=sys.stderr)
        return other_contents
    return {}


class MetadataForensicsAgent:
    """Regelbaserad format-/integritets-/tidsstämpelkontroll. Ingen inference."""

    def perform_audit(self, csm: Any) -> None:
        files = getattr(csm, "files", None)
        if files is None and hasattr(csm, "records"):
            files = {getattr(r, "file_id", i): r for i, r in enumerate(csm.records)}
        if not files:
            return
        findings = getattr(csm, "agent_a_findings", None)
        if findings is None:
            return

        for fid, record in files.items():
            meta = getattr(record, "metadata", None)
            if meta is None:
                findings.append({
                    "id": f"FINDING_A_META_{len(findings)+1}",
                    "typ": "METADATA_SAKNAS",
                    "beskrivning": f"Fil {getattr(record,'filename',fid)} saknar metadata",
                    "allvarlighet": "MEDEL",
                    "käll_id": fid,
                })
                continue

            ext = (getattr(record, "extension", "") or "").lower().replace(".", "")
            magic = getattr(meta, "filtyp_magic", None) or ""
            details = None
            if ext == "pdf" and magic not in ("PDF", "KAN EJ VERIFIERAS", ""):
                details = f".pdf men magic={magic}"
            elif ext in ("png", "jpg", "jpeg") and magic not in ("PNG", "JPEG", "KAN EJ VERIFIERAS", ""):
                details = f".{ext} men magic={magic}"
            elif ext in ("docx", "xlsx", "pptx") and magic not in ("ZIP/DOCX/XLSX/PPTX", "KAN EJ VERIFIERAS", ""):
                details = f".{ext} men magic={magic}"

            if details:
                # Misslyckas märkningen nedan är avvikelsen konstaterad men
                # filen inte märkt som modifierad, respektive inte höjd till
                # riskkategori. Det tystades tidigare, varpå en konstaterad
                # källkontaminering kunde bli liggande som en fil utan
                # anmärkning. Bortfallet skrivs nu in i avvikelselistan, som
                # följer med fyndet.
                märkningsfel = []
                try:
                    meta.integritet = "MODIFIERAD"
                    meta.modifieringstyp = "FORMAT_MISMATCH"
                    if hasattr(meta, "avvikelser") and isinstance(meta.avvikelser, list):
                        meta.avvikelser.append(details)
                except Exception as e:
                    märkningsfel.append(
                        f"integritetsmärkningen kunde inte sättas: "
                        f"{type(e).__name__}: {e}"
                    )
                try:
                    record.evidence_category = "B_RISK"
                except Exception as e:
                    märkningsfel.append(
                        f"beviskategorin kunde inte höjas till B_RISK: "
                        f"{type(e).__name__}: {e}"
                    )
                if hasattr(record, "avvikelser") and isinstance(record.avvikelser, list):
                    record.avvikelser.append(f"METADATA DISCREPANCY: {details}")
                    for m in märkningsfel:
                        record.avvikelser.append(f"MÄRKNING EJ GENOMFÖRD: {m}")
                findings.append({
                    "id": f"FINDING_A_META_{len(findings)+1}",
                    "typ": "KALLKONTAMINERING_FORMAT",
                    "beskrivning": f"Fil {getattr(record,'filename',fid)}: {details}",
                    "allvarlighet": "HOG",
                    "käll_id": fid,
                })

            if getattr(record, "quarantine_flag", False):
                findings.append({
                    "id": f"FINDING_A_META_{len(findings)+1}",
                    "typ": "KARANTAN",
                    "beskrivning": f"Fil {getattr(record,'filename',fid)} karantänflaggad",
                    "allvarlighet": "HOG",
                    "käll_id": fid,
                })


class RättstidskontrollAgent:
    """Intertemporal kontroll — kräver csm.graph. Bevarad funktionskälla."""

    def kontrollera(self, csm: Any) -> Dict:
        graph = getattr(csm, "graph", None)
        if graph is None:
            return {
                "status": "EJ_KORBAR",
                "skäl": "RelationsGraph saknas",
            }
        nodes = getattr(graph, "nodes", {}) or {}
        return {
            "status": "BEVARAD_FUNKTIONSKALLA",
            "noder": len(nodes) if hasattr(nodes, "__len__") else 0,
        }

    def perform_audit(self, csm: Any) -> None:
        """Kompatibilitet om anropare förväntar perform_audit."""
        result = self.kontrollera(csm)
        findings = getattr(csm, "agent_b_findings", None)
        if findings is not None and result.get("status") == "BEVARAD_FUNKTIONSKALLA":
            findings.append({
                "id": f"FINDING_B_TEMP_{len(findings)+1}",
                "typ": "TIDSMASSIG_NARVARO",
                "beskrivning": f"Rättstidskontroll: {result}",
                "käll_id": "SYSTEM",
            })
