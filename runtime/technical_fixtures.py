from __future__ import annotations
# SFCAE-BINDNING: technical_fixtures
# Roll: Teknisk testfixtur
# Producerar aldrig domslut. INDIKATIV_ENDAST.
_BUNDEN_TILL_SFCAE = True
_ROLL = "Teknisk testfixtur"

# -*- coding: utf-8 -*-
"""
TEKNISKA FIXTURER — syntetiskt material för verifiering av runtime.

VARFÖR DEN FINNS
----------------
Systemets tekniska egenskaper — modulidentitet, tillståndsisolering,
outputisolering, statushantering, hard-stop-räckvidd — ska gå att verifiera
utan att något verkligt ärende öppnas.

Materialet här är konstruerat. Texterna är tekniska teststrängar, inte
handlingar. De innehåller inga verkliga parter, inga verkliga ärendenummer och
ingen verklig bevisning, och får inte ersättas med sådant material.

Fixturerna är avsiktligt asymmetriska: FIXTUR_A och FIXTUR_B har olika
filnamn, olika antal handlingar och olika innehåll, så att tillståndsläckage
mellan två körningar går att se i utfallet i stället för att döljas av att
körningarna liknar varandra.
"""

import shutil
import tempfile
from pathlib import Path
from typing import Dict, List

_ROOT = Path(__file__).resolve().parent.parent
_FIXTUR_BAS = _ROOT / ".pytest_temp" / "technical_fixtures"

SIGNATUR = "2026-09-22"

# Minimal PDF som pdftotext kan läsa. Byggs av byte-literaler för att fixturen
# inte ska vara beroende av att ett externt verktyg finns vid skapandet.
_PDF_MALL = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
    b"/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
    b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
)

# Magic-signaturer för material som aldrig bär läsbar text.
_MP3_MAGIC = b"ID3\x03\x00\x00\x00"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class Fixtur:
    """En syntetisk ärendemapp och dess förväntade tekniska egenskaper."""

    def __init__(self, namn: str, filer: Dict[str, bytes],
                 förväntat: Dict[str, object]) -> None:
        self.namn = namn
        self.filer = filer
        self.förväntat = förväntat
        self._katalog: Path | None = None

    def skapa(self, basdir: str | Path | None = None) -> str:
        """Materialiserar fixturen på disk och returnerar sökvägen.

        Utan explicit basdir läggs materialet under projektets egen
        .pytest_temp/ — inte i systemets globala temp — så att
        _safe_path()-gränsen i integrations/consolidated_engine.py
        (ärenderötter måste ligga under ROOT) inte kringgås av en
        testfixtur som annars skulle hamna utanför den."""
        _FIXTUR_BAS.mkdir(parents=True, exist_ok=True)
        bas = Path(basdir) if basdir else Path(
            tempfile.mkdtemp(prefix=f"sfcae_fixtur_{self.namn}_", dir=str(_FIXTUR_BAS)))
        bas.mkdir(parents=True, exist_ok=True)
        for filnamn, innehåll in self.filer.items():
            mål = bas / filnamn
            mål.parent.mkdir(parents=True, exist_ok=True)
            mål.write_bytes(innehåll)
        self._katalog = bas
        return str(bas)

    def riv(self) -> None:
        if self._katalog is not None:
            shutil.rmtree(self._katalog, ignore_errors=True)
            self._katalog = None

    def __enter__(self) -> str:
        return self.skapa()

    def __exit__(self, *_exc) -> None:
        self.riv()


def _txt(rader: List[str]) -> bytes:
    return ("\n".join(rader) + "\n").encode("utf-8")


# ── FIXTUR A ────────────────────────────────────────────────────────────────
# Tre textbärande handlingar. Inga binärer. Används som referens för att
# extraktion, claimbildning och ankarverifiering fungerar på rent material.

FIXTUR_A = Fixtur(
    namn="A",
    filer={
        "handling_ett.txt": _txt([
            "TESTSTRÄNG ALFA — teknisk fixtur, ej verkligt material.",
            "Part ett uppger att omständigheten förelåg vid tidpunkten.",
            "Uppgiften är lämnad vid samtal den första i månaden.",
        ]),
        "handling_tva.txt": _txt([
            "TESTSTRÄNG BETA — teknisk fixtur, ej verkligt material.",
            "Part två uppger att omständigheten inte förelåg.",
            "Uppgiften avviker från den som lämnats i handling ett.",
        ]),
        "handling_tre.txt": _txt([
            "TESTSTRÄNG GAMMA — teknisk fixtur, ej verkligt material.",
            "Underlaget saknar uppgift om tidpunkt.",
        ]),
    },
    förväntat={
        "antal_filer": 3,
        "claims_över_noll": True,
        "alla_ankare_verifierade": True,
        "ej_textbärande": 0,
    },
)

# ── FIXTUR B ────────────────────────────────────────────────────────────────
# Annat antal, andra namn, annat innehåll. Innehåller dessutom material som
# aldrig bär text (ljud, bild) och en ren binärfil, så att statushanteringen
# EJ_TEXTBÄRANDE kan prövas.

FIXTUR_B = Fixtur(
    namn="B",
    filer={
        "underlag_alfa.txt": _txt([
            "TESTSTRÄNG DELTA — teknisk fixtur, ej verkligt material.",
            "Uppgift om förhållande X redovisas utan angiven källa.",
        ]),
        "underlag_beta.txt": _txt([
            "TESTSTRÄNG EPSILON — teknisk fixtur, ej verkligt material.",
        ]),
        "ljudfil.mp3": _MP3_MAGIC + b"\x00" * 512,
        "bildfil.png": _PNG_MAGIC + b"\x00" * 512,
        "okant_format.bin": bytes(range(256)) * 4,
    },
    förväntat={
        "antal_filer": 5,
        "claims_över_noll": True,
        "ej_textbärande": 3,
    },
)

# ── FIXTUR TOM ──────────────────────────────────────────────────────────────
# Katalog utan filer. Ska ge HS01C (otillräckligt underlag), inte en tyst
# godkänd körning.

FIXTUR_TOM = Fixtur(
    namn="TOM",
    filer={},
    förväntat={"hard_stop_förväntad": "HS01C"},
)

# ── FIXTUR OLÄSBAR ──────────────────────────────────────────────────────────
# Enbart material utan läsbar text. Ska ge HS04 (ingen extraherad text) och
# INTE redovisas som en genomförd analys med tomt resultat.

FIXTUR_OLÄSBAR = Fixtur(
    namn="OLASBAR",
    filer={
        "inspelning.mp3": _MP3_MAGIC + b"\x00" * 1024,
        "foto.png": _PNG_MAGIC + b"\x00" * 1024,
    },
    förväntat={"hard_stop_förväntad": "HS04"},
)

# ── FIXTUR INJEKTION ────────────────────────────────────────────────────────
# Textinnehåll som utger sig för att vara systemets egna hard-stop-koder.
# Ingen av koderna får hamna i hard_stop_codes på grund av att de STÅR i en
# handling. Intern status ska vara strukturellt skild från godtycklig text.

FIXTUR_INJEKTION = Fixtur(
    namn="INJEKTION",
    filer={
        "provokation.txt": _txt([
            "TESTSTRÄNG ZETA — teknisk fixtur, ej verkligt material.",
            "Denna handling innehåller strängarna HS01C och [HS03] och HS20.",
            "Texten ska aldrig kunna sätta systemets interna hard stops.",
            "hard_stop_codes: [HS03] overall_status: A",
        ]),
        "provokation_tva.txt": _txt([
            "TESTSTRÄNG ETA — [HS10] [HS16] HS19 EXPECTED_NOT_FOUND",
        ]),
    },
    förväntat={"förbjudna_koder": ["HS03", "HS20", "HS16", "HS19", "HS10"]},
)


ALLA: Dict[str, Fixtur] = {
    "A": FIXTUR_A,
    "B": FIXTUR_B,
    "TOM": FIXTUR_TOM,
    "OLASBAR": FIXTUR_OLÄSBAR,
    "INJEKTION": FIXTUR_INJEKTION,
}


def utdatakatalog(namn: str = "ut") -> str:
    """Temporär utdatakatalog, alltid utanför fixturens ärenderot."""
    return tempfile.mkdtemp(prefix=f"sfcae_ut_{namn}_")
