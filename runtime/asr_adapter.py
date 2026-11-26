"""ASR adapter interface for SFCAE Motor B integration.

Provides a neutral interface for Automatic Speech Recognition that can be
switched between implementations (Whisper, simulated, etc.) without
hard-coupling the rest of Motor B to a specific ASR engine.

Usage:
    adapter = get_asr_adapter(config)
    resultat = adapter.transcribe_detailed(audio_path)

ABSOLUTA REGLER (config/audio_forensics.yaml, zero_inference_policy):
- En adapter som inte transkriberat får ALDRIG returnera text som ser ut
  som en transkription. `simulerad` skiljer verklig ASR från utebliven ASR.
- Ingen parafras, ingen meningskomplettering, ingen ifyllnad av ohörbart.
- Filnärvaro är inte transkribering.
"""

from __future__ import annotations

import abc
import importlib.util
import os
from typing import Any, Dict, Optional

# Motorer vi kan använda, i prioritetsordning.
WHISPER_PAKET = ("faster_whisper", "whisper")


def whisper_tillganglig() -> Optional[str]:
    """Namnet på det Whisper-paket som faktiskt är installerat, annars None."""
    for namn in WHISPER_PAKET:
        if importlib.util.find_spec(namn) is not None:
            return namn
    return None


class ASRAdapter(abc.ABC):
    """Abstract base class for ASR adapters."""

    #: True när adaptern inte utför verklig taligenkänning.
    simulerad: bool = True
    namn: str = "okänd"

    @abc.abstractmethod
    def transcribe_detailed(self, audio_path: str) -> Dict[str, Any]:
        """Transkribera en ljudfil och redovisa utfallet.

        Returnerar alltid en dict med nycklarna:
          text      — ordagrann transkription, eller None
          simulerad — False ENDAST när verklig ASR producerat texten
          motor     — vilken motor som kördes
          status    — GENOMFÖRD | FIL_SAKNAS | MOTOR_SAKNAS | FEL | TOM
          fel       — verklig felorsak när status != GENOMFÖRD
        """
        raise NotImplementedError

    def transcribe(self, audio_path: str) -> str:
        """Bakåtkompatibelt textgränssnitt.

        Returnerar tom sträng när ingen verklig transkription skett — aldrig
        en platshållare som kan förväxlas med ett citat ur ljudet.
        """
        return self.transcribe_detailed(audio_path).get("text") or ""


class SimulatedASR(ASRAdapter):
    """Fallback som ALDRIG transkriberar.

    Används när ingen verklig ASR-motor är installerad eller konfigurerad.
    Den redovisar sin egen oförmåga i stället för att producera text.
    """

    simulerad = True
    namn = "simulated"

    def transcribe_detailed(self, audio_path: str) -> Dict[str, Any]:
        finns = bool(audio_path) and os.path.isfile(audio_path)
        return {
            "text": None,
            "simulerad": True,
            "motor": "simulated",
            "status": "MOTOR_SAKNAS",
            "fil_finns": finns,
            "fel": ("Ingen ASR-motor är installerad. Filnärvaro är inte "
                    "transkribering."),
        }


class WhisperASR(ASRAdapter):
    """Whisper-baserad ASR. Kräver 'faster-whisper' eller 'openai-whisper'.

    Modellen laddas lat vid första anropet — en import av modulen får inte
    dra in hundratals MB modellvikter i processer som aldrig transkriberar.
    """

    simulerad = False
    namn = "whisper"

    def __init__(self, model_size: str = "base", language: str = "sv"):
        self.model_size = model_size
        self.language = language
        self._model = None
        self._paket = whisper_tillganglig()

    def _ladda_modell(self):
        if self._model is not None:
            return self._model
        if self._paket == "faster_whisper":
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_size, device="cpu",
                                       compute_type="int8")
        elif self._paket == "whisper":
            import whisper
            self._model = whisper.load_model(self.model_size)
        return self._model

    def transcribe_detailed(self, audio_path: str) -> Dict[str, Any]:
        bas = {"motor": f"whisper:{self._paket or 'saknas'}", "text": None}

        if self._paket is None:
            return {**bas, "simulerad": True, "status": "MOTOR_SAKNAS",
                    "fel": ("Varken faster-whisper eller openai-whisper är "
                            "installerat.")}

        if not audio_path or not os.path.isfile(audio_path):
            return {**bas, "simulerad": True, "status": "FIL_SAKNAS",
                    "fel": f"Ljudfil saknas: {audio_path}"}

        try:
            modell = self._ladda_modell()
            if self._paket == "faster_whisper":
                segments, _info = modell.transcribe(audio_path,
                                                    language=self.language)
                text = " ".join(s.text.strip() for s in segments).strip()
            else:
                res = modell.transcribe(audio_path, language=self.language)
                text = (res.get("text") or "").strip()
        except Exception as e:
            # En motor som inte kunde läsa filen har inte transkriberat.
            # Felet redovisas; det ersätts aldrig med text.
            return {**bas, "simulerad": True, "status": "FEL",
                    "fel": f"{type(e).__name__}: {e}"}

        if not text:
            return {**bas, "simulerad": True, "status": "TOM",
                    "fel": "Whisper producerade ingen text ur ljudfilen"}

        return {"text": text, "simulerad": False, "motor": bas["motor"],
                "status": "GENOMFÖRD", "fel": None,
                "model_size": self.model_size, "language": self.language}


def get_asr_adapter(config: Optional[dict] = None) -> ASRAdapter:
    """Factory function that returns the appropriate ASR adapter.

    Args:
        config: Optional configuration dictionary. Expected keys:
            - 'engine': 'whisper' | 'auto' | 'simulated' (default 'auto')
            - 'model_size': str (for Whisper, e.g. 'base', 'large')
            - 'language': str language code (e.g. 'sv', 'en')

    'auto' väljer Whisper när ett Whisper-paket verkligen är installerat,
    annars SimulatedASR. Att be om 'whisper' utan installerat paket ger
    också SimulatedASR — en adapter får aldrig utge sig för att kunna
    transkribera när motorn saknas.
    """
    cfg = config or {}
    engine = cfg.get("engine", "auto")
    model_size = cfg.get("model_size", "base")
    language = cfg.get("language", "sv")

    if engine in ("whisper", "auto"):
        if whisper_tillganglig():
            return WhisperASR(model_size=model_size, language=language)
        return SimulatedASR()
    return SimulatedASR()
