from __future__ import annotations
# PASSIV MOTIVERING: Motor B historisk agent. Bibehålls — anropas av fup_analysis_agent.
# Bibehålls per arkitekturbeslutet.
_PASSIV_MOTIVERING = True

"""
MOTOR_B_AGENTS — Integrerar Motor B:s djupagenter i den konsoliderade arkitekturen.

Motor B (runtime/metadata_forensics_agent.py, MOTOR_VERSION="10.0-v2") innehåller
regelbaserade kontrollagenter som Motor C inte inbäddar:
  - MetadataForensicsAgent   (regelbaserad format- & tidsstempelvalidering med
                              ISO 27037-inspirerad terminologi)
  - RättstidskontrollAgent   (regelbaserad intertemporal SFS-analys) — kräver relationsgraf
  - RöstanalysAgent          (regelbaserad granskning med zero-inference-policy;
                              transkription ENDAST via verklig ASR-motor; utan motor redovisas EJ_GENOMFÖRD och ingen text)

Denna modul adapternar Motor C:s `FileRecord`-lista (files: List, ej dict) till
den form Motor B-agenterna förväntar sig (files.items()), och anropar de ORIGINAL
Motor B-klasserna via import — funktionell trohet bevaras, ingen omimplementering.

VERIFIERAT: MetadataForum & Röstanalys körs mot adapterad csm. Rättstidskontroll
kräver en relationsgraf (csm.graph med noder); här verifieras närvaro och
grafbehov, och guarden rapporteras ärligt.
"""

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
_MOTOR_B = None

# runtime/ har inget __init__.py — dess moduler (asr_adapter m.fl.) importeras
# med bart stamnamn. Sökvägen läggs till här så att ASR-adaptern går att nå
# även när bara integrations/ finns på sys.path.
if str(_ROOT / "runtime") not in sys.path:
    sys.path.insert(0, str(_ROOT / "runtime"))

def _load_motor_b() -> Any:
    """Laddar metadata_forensics_agent (aktiv runtime). Inget beroende till _deprecated/motor_b."""
    global _MOTOR_B
    if _MOTOR_B is not None:
        return _MOTOR_B
    path = _ROOT / "runtime" / "metadata_forensics_agent.py"
    if not path.is_file():
        return None
    if str(_ROOT / "runtime") not in sys.path:
        sys.path.insert(0, str(_ROOT / "runtime"))
    from module_loader import ladda_modul
    mod = ladda_modul("metadata_forensics_agent", path)
    _MOTOR_B = mod
    return mod

class _CsmAdapter:
    """Anpassar Motor C CaseStateMachine/records till Motor B-agenternas kontrakt."""

    def __init__(self, records: List[Any]) -> None:
        self.files: Dict[str, Any] = {r.file_id: r for r in records}
        self.agent_a_findings: List[Dict] = []
        self.agent_b_findings: List[Dict] = []
        self.agent_c_findings: List[Dict] = []
        self.active_modules: List[str] = []

def run_metadata_forensics(records: List[Any]) -> Dict:
    """Kör Motor B MetadataForensicsAgent mot ett givet filregister."""
    m = _load_motor_b()
    agent_cls = getattr(m, "MetadataForensicsAgent", None)
    if agent_cls is None:
        return {"status": "EJ TILLGÄNGLIG", "reason": "MetadataForensicsAgent saknas"}
    csm = _CsmAdapter(records)
    agent_cls().perform_audit(csm)
    return {
        "status": "GENOMFÖRD",
        "agent_a_findings": csm.agent_a_findings,
        "records_flagged": len(csm.agent_a_findings),
    }

#: Ljudformat som aktiverar ljudforensiken (config/audio_forensics.yaml,
#: activating_formats). Läses ur konfigurationen när den går att läsa, så
#: nyckeln inte blir en död deklaration som ingen kod konsulterar.
_LJUDFORMAT_FALLBACK = (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac",
                        ".mp4", ".mov")


def ljudformat() -> tuple:
    """Filändelser som aktiverar ljudforensiken.

    Hämtas ur config/audio_forensics.yaml:activating_formats. Kan filen
    eller PyYAML inte läsas används _LJUDFORMAT_FALLBACK — konfigurationen
    styr, men dess frånvaro får inte tysta ned hela ljudvägen.
    """
    sökväg = _ROOT / "config" / "audio_forensics.yaml"
    try:
        import yaml
        with open(sökväg, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        format_ = [str(x).lower() for x in (cfg.get("activating_formats") or [])
                   if str(x).startswith(".")]
        if format_:
            return tuple(format_)
    except Exception as e:
        print(f"[MOTOR_B] audio_forensics.yaml kunde inte läsas — inbyggda "
              f"ljudformat används: {type(e).__name__}: {e}", file=sys.stderr)
    return _LJUDFORMAT_FALLBACK


def _extrahera_ljudvag(audio_file_path: Any) -> Optional[str]:
    """Plockar ut en ljudfilssökväg ur en sträng, en lista eller FileRecords.

    consolidated_engine skickar in HELA filregistret, inte en ljudfil. En
    ljudfil måste alltså väljas ur listan på sin faktiska ändelse — annars
    hittas den aldrig och ljudvägen körs aldrig.
    """
    if isinstance(audio_file_path, str):
        return audio_file_path
    if not isinstance(audio_file_path, (list, tuple)):
        return None

    format_ = ljudformat()
    första: Optional[str] = None
    for item in audio_file_path:
        if isinstance(item, str):
            kandidat = item
        else:
            kandidat = (getattr(item, "file_path", None)
                        or getattr(item, "relative_path", None))
        if not kandidat:
            continue
        if första is None:
            första = kandidat
        if str(kandidat).lower().endswith(format_):
            return kandidat
    # Ingen ljudfil i registret → None. Tidigare returnerades första filen
    # oavsett typ, så t.ex. dom.pdf/dom.txt behandlades som ljud och
    # ljudgranskningen redovisades som påbörjad på ett ärende helt utan ljud.
    _ = första
    return None


def run_rostanalys(audio_file_path: Any = None,
                   adapter: Optional[object] = None,
                   asr_config: Optional[dict] = None) -> dict:
    """Ljudgranskning L3/M4 — transkriberar när en ASR-motor finns.

    Kopplad till den verkliga ASR-adaptern (runtime/asr_adapter.py). Finns
    en installerad motor körs den och `simulerad` blir False. Saknas motorn
    rapporteras det ärligt: `simulerad` förblir True och transkriptionen
    ersätts ALDRIG med konstruerad text.

    ABSOLUT REGEL (config/audio_forensics.yaml): filnärvaro är inte
    transkribering. Endast text som en motor faktiskt producerat får
    presenteras som transkription.
    """
    audio_file_path = _extrahera_ljudvag(audio_file_path)

    _asr_not = (
        "INDIKATIV_ENDAST — ingen verklig taligenkänning är kopplad till "
        "detta system. Filnärvaro är inte transkribering."
    )

    # Status får ALDRIG vara GENOMFÖRD när ingen ljudgranskning skett.
    # Tidigare rapporterades "GENOMFÖRD" (simulerad) även utan ljudfil, vilket
    # i rapporten läses som utförd granskning.
    if not isinstance(audio_file_path, str) or not audio_file_path:
        return {
            "status": "EJ_TILLÄMPLIG",
            "utförd": False,
            "simulerad": True,
            "transkription": "[Ingen ljudfil hittad — ingen transkription]",
            "asr_motor": "ingen",
            "not": _asr_not,
        }

    if not os.path.exists(audio_file_path):
        return {
            "status": "LJUDFIL_SAKNAS",
            "utförd": False,
            "simulerad": True,
            "transkription": "[Ingen ljudfil hittad på angiven sökväg — ingen transkription]",
            "asr_motor": "ingen",
            "ljudfil": audio_file_path,
            "not": _asr_not,
        }

    if adapter is None:
        adapter = _valj_asr_adapter(asr_config)

    res = _asr_pipeline(audio_file_path, adapter=adapter)

    # simulerad=False får sättas ENDAST när en motor verkligen producerat text.
    verklig = bool(res.get("text")) and res.get("simulerad") is False
    if verklig:
        return {
            "status": "GENOMFÖRD",
            "utförd": True,
            "simulerad": False,
            "transkription": res["text"],
            "asr_motor": res.get("motor"),
            "ljudfil": audio_file_path,
            "not": ("ORDAGRANN TRANSKRIPTION via verklig ASR. Ingen "
                    "talaridentifiering utan referensupptagning (M3); "
                    "ohörbara partier fylls aldrig i."),
        }

    return {
        "status": "EJ_GENOMFÖRD",
        "utförd": False,
        "simulerad": True,
        "transkription": "[Ej transkriberad — ingen ASR-motor kopplad]",
        "asr_motor": res.get("motor", "ingen"),
        "asr_status": res.get("status"),
        "asr_fel": res.get("fel"),
        "ljudfil": audio_file_path,
        "not": _asr_not,
    }


def _asr_pipeline(file_path: str, adapter: Optional[object] = None) -> dict:
    """Transkriberar en ljudfil med vald ASR-adapter.

    Returnerar adapterns detaljerade utfall ({"text","simulerad","motor",
    "status","fel"}) — aldrig en naken sträng, eftersom anroparen måste
    kunna skilja "transkriberad" från "motor saknas".
    """
    from asr_adapter import SimulatedASR

    if adapter is None:
        adapter = _valj_asr_adapter()

    fn = getattr(adapter, "transcribe_detailed", None)
    if fn is None:
        # En adapter med bara transcribe() (t.ex. en testdubbel) — dess text
        # kan inte styrkas som verklig ASR, så simulerad förblir True.
        legacy = getattr(adapter, "transcribe", None)
        if legacy is None:
            adapter = SimulatedASR()
            return adapter.transcribe_detailed(file_path)
        text = legacy(file_path)
        return {"text": text or None,
                "simulerad": getattr(adapter, "simulerad", True),
                "motor": getattr(adapter, "namn", type(adapter).__name__),
                "status": "GENOMFÖRD" if text else "TOM",
                "fel": None if text else "adaptern gav ingen text"}

    return fn(file_path)


def set_asr_adapter_for_testing(adapter: Optional[object]) -> None:
    """Injicera en specifik adapterinstans (tester, eller en operatörsvald motor).

    Anropas av _valj_asr_adapter() och därmed av run_rostanalys på den
    verkliga körvägen. Sätt None för att återgå till automatiskt val.
    """
    global _test_asr_adapter
    _test_asr_adapter = adapter


_test_asr_adapter: Optional[object] = None


def _valj_asr_adapter(asr_config: Optional[dict] = None) -> object:
    """Väljer ASR-adapter: injicerad instans först, annars motorval på vad
    som faktiskt är installerat (runtime/asr_adapter.get_asr_adapter)."""
    if _test_asr_adapter is not None:
        return _test_asr_adapter
    from asr_adapter import get_asr_adapter
    return get_asr_adapter(asr_config)


#: Bakåtkompatibelt namn — samma funktion som _valj_asr_adapter.
_get_testable_asr_adapter = _valj_asr_adapter

def rattstidskontroll_available() -> Dict:
    """Närvarokontroll. Kräver relationsgraf med noder för full körning."""
    m = _load_motor_b()
    if m is None or not hasattr(m, "RättstidskontrollAgent"):
        return {"status": "EJ TILLGÄNGLIG"}
    return {
        "status": "BEVARAD_FUNKTIONSKALLA",
        "krav": "csm.graph med noder för materiell/processuell intertemporal kontroll",
        "källa": "runtime/metadata_forensics_agent.py",
    }

if __name__ == "__main__":
    # Demonstration med tomt register: bör vara genomförd utan fynd.
    class _R:
        file_id = "DEMO-1"
        relative_path = "demo.txt"
        filename = "demo.txt"
        extension = ".txt"
        quarantine_flag = False
        metadata = type("M", (), {"filtyp_magic": "KAN EJ VERIFIERAS",
                                   "integritet": "KAN EJ VERIFIERAS",
                                   "modifieringstyp": "OFÖRÄNDRAD",
                                   "avvikelser": []})()
        evidence_category = "UNCLASSIFIED"
        avvikelser = []

    print(run_metadata_forensics([_R()]))
    print(rattstidskontroll_available())

