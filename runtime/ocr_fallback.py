#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR FALLBACK – SKANNADE PDF:ER
SVENSK FORENSIC COURT AUDIT ENGINE v10.3-UPDATED
Datum: 2026-08-23

Fallback-extraktion för skannade PDF:er när pdftotext ger tom output.
Använder pytesseract (Tesseract OCR) med svenska språkmodeller.

ABSOLUTA REGLER:
- Original-filer rörs ALDRIG
- OCR-text markeras alltid [OCR-EXTRAHERAD] – aldrig som VERIFIED
- Låg OCR-kvalitet → PARTIALLY_AVAILABLE (aldrig VERIFIED)
- Ingen tolkning av OCR-text – ordagrann återgivning
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from forensic_engine_v10_3_canonical import FileRecord, Availability
from document_text_extractor import TextSegment, ExtractionResult


# ============================================================
# OCR KVALITETSBEDÖMNING
# ============================================================

@dataclass
class OCRKvalitet:
    """Bedömning av OCR-extraktionens kvalitet."""
    confidence_score: float    # 0.0–1.0
    language_detected: str     # "swe", "eng", "unknown"
    char_count: int
    word_count: int
    quality_level: str         # HÖG | MEDEL | LÅG | OTILLRÄCKLIG

    @classmethod
    def from_text(cls, text: str) -> "OCRKvalitet":
        """Beräknar kvalitet från extraherad text."""
        if not text or len(text.strip()) < 20:
            return cls(0.0, "unknown", 0, 0, "OTILLRÄCKLIG")

        char_count = len(text)
        words = text.split()
        word_count = len(words)

        # Enkel kvalitetsbedömning baserat på läsbarhet
        # Räkna andel "normala" ord (bokstäver + siffror)
        normal_words = sum(
            1 for w in words
            if re.match(r'^[a-zA-ZåäöÅÄÖ0-9\-\.,:;!?]+$', w)
        )
        ratio = normal_words / max(word_count, 1)

        if ratio > 0.8:
            quality = "HÖG"
            score = 0.9
        elif ratio > 0.6:
            quality = "MEDEL"
            score = 0.6
        elif ratio > 0.4:
            quality = "LÅG"
            score = 0.3
        else:
            quality = "OTILLRÄCKLIG"
            score = 0.1

        # Detektera språk (enkel heuristik)
        swedish_words = sum(
            1 for w in words
            if any(c in w.lower() for c in ['å', 'ä', 'ö'])
        )
        lang = "swe" if swedish_words > 2 else "eng"

        return cls(score, lang, char_count, word_count, quality)


# ============================================================
# OCR FALLBACK
# ============================================================

class OCRFallback:
    """
    OCR-fallback för skannade PDF:er.

    Prioritetsordning:
    1. pytesseract (Python-binding för Tesseract)
    2. tesseract CLI direkt
    3. pdftotext med -raw flagga (sista utväg)

    OCR-text markeras alltid [OCR-EXTRAHERAD] och får
    Availability.PARTIALLY_AVAILABLE – aldrig VERIFIED.
    """

    # Minsta antal tecken för att OCR ska anses lyckad
    MIN_CHARS = 50

    def __init__(self, language: str = "swe+eng", verbose: bool = False):
        self.language = language
        self.verbose = verbose
        self.log: List[str] = []
        self._pytesseract_available = self._check_pytesseract()
        self._tesseract_cli_available = self._check_tesseract_cli()

    def _check_pytesseract(self) -> bool:
        """Kontrollerar om pytesseract är tillgängligt."""
        try:
            import pytesseract
            return True
        except ImportError:
            return False

    def _check_tesseract_cli(self) -> bool:
        """Kontrollerar om tesseract CLI är tillgängligt."""
        try:
            result = subprocess.run(
                ["tesseract", "--version"],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def extract(self, file_record: FileRecord) -> ExtractionResult:
        """
        Kör OCR på en fil.
        Väljer metod baserat på tillgänglighet.
        """
        path = file_record.file_path

        if not os.path.exists(path):
            return ExtractionResult(
                file_id=file_record.file_id,
                file_path=path,
                file_name=os.path.basename(path),
                extraction_method="OCR_FAILED",
                status="FAILED",
                error="Fil finns inte",
            )

        self.log.append(
            f"[OCR] Startar OCR på {file_record.file_id}: "
            f"{os.path.basename(path)}"
        )

        # Försök 1: pytesseract
        if self._pytesseract_available:
            result = self._extract_pytesseract(file_record)
            if result.status == "SUCCESS" and result.char_count >= self.MIN_CHARS:
                return result

        # Försök 2: tesseract CLI
        if self._tesseract_cli_available:
            result = self._extract_tesseract_cli(file_record)
            if result.status == "SUCCESS" and result.char_count >= self.MIN_CHARS:
                return result

        # Försök 3: pdftotext -raw (sista utväg)
        result = self._extract_pdftotext_raw(file_record)
        if result.status == "SUCCESS" and result.char_count >= self.MIN_CHARS:
            return result

        return ExtractionResult(
            file_id=file_record.file_id,
            file_path=path,
            file_name=os.path.basename(path),
            extraction_method="OCR_ALL_FAILED",
            status="FAILED",
            error=(
                "Alla OCR-metoder misslyckades. "
                f"pytesseract: {self._pytesseract_available}, "
                f"tesseract CLI: {self._tesseract_cli_available}"
            ),
        )

    def _extract_pytesseract(self, file_record: FileRecord) -> ExtractionResult:
        """OCR via pytesseract."""
        try:
            import pytesseract
            from PIL import Image
            import pdf2image

            path = file_record.file_path
            segments: List[TextSegment] = []
            total_chars = 0

            # Konvertera PDF-sidor till bilder
            try:
                pages = pdf2image.convert_from_path(path, dpi=300)
            except Exception as e:
                return ExtractionResult(
                    file_id=file_record.file_id,
                    file_path=path,
                    file_name=os.path.basename(path),
                    extraction_method="pytesseract",
                    status="FAILED",
                    error=f"pdf2image fel: {e}",
                )

            for page_num, page_img in enumerate(pages, 1):
                # Kör OCR
                ocr_text = pytesseract.image_to_string(
                    page_img,
                    lang=self.language,
                    config="--psm 6",  # Antag enhetligt textblock
                )

                if not ocr_text.strip():
                    continue

                # Bedöm kvalitet
                kvalitet = OCRKvalitet.from_text(ocr_text)

                # Dela upp i stycken
                paragraphs = re.split(r"\n{2,}", ocr_text)
                for para in paragraphs:
                    para = para.strip()
                    if len(para) < 20:
                        continue

                    # Markera som OCR-extraherad
                    marked_text = f"[OCR-EXTRAHERAD] {para}"

                    seg = TextSegment(
                        file_id=file_record.file_id,
                        file_path=path,
                        page_or_position=f"s.{page_num} (OCR)",
                        text=marked_text[:500],
                        char_offset=total_chars,
                        extraction_method="pytesseract",
                        # OCR är alltid PARTIALLY_AVAILABLE – aldrig VERIFIED
                        confidence="PARTIALLY_AVAILABLE",
                    )
                    segments.append(seg)
                    total_chars += len(para)

            self.log.append(
                f"[OCR] pytesseract: {len(pages)} sidor, "
                f"{len(segments)} segment, {total_chars} tecken"
            )

            return ExtractionResult(
                file_id=file_record.file_id,
                file_path=path,
                file_name=os.path.basename(path),
                extraction_method="pytesseract",
                status="SUCCESS" if segments else "PARTIAL",
                segments=segments,
                page_count=len(pages),
                char_count=total_chars,
                warnings=["[OCR-EXTRAHERAD] – Availability: PARTIALLY_AVAILABLE"],
            )

        except ImportError as e:
            return ExtractionResult(
                file_id=file_record.file_id,
                file_path=file_record.file_path,
                file_name=os.path.basename(file_record.file_path),
                extraction_method="pytesseract",
                status="FAILED",
                error=f"Import fel: {e}. Installera: pip install pytesseract pdf2image Pillow",
            )
        except Exception as e:
            return ExtractionResult(
                file_id=file_record.file_id,
                file_path=file_record.file_path,
                file_name=os.path.basename(file_record.file_path),
                extraction_method="pytesseract",
                status="FAILED",
                error=str(e),
            )

    def _extract_tesseract_cli(self, file_record: FileRecord) -> ExtractionResult:
        """OCR via tesseract CLI."""
        path = file_record.file_path
        segments: List[TextSegment] = []

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Konvertera PDF till bilder med pdftoppm
                img_prefix = os.path.join(tmpdir, "page")
                result = subprocess.run(
                    ["pdftoppm", "-r", "300", "-png", path, img_prefix],
                    capture_output=True, text=True, timeout=60
                )

                if result.returncode != 0:
                    return ExtractionResult(
                        file_id=file_record.file_id,
                        file_path=path,
                        file_name=os.path.basename(path),
                        extraction_method="tesseract_cli",
                        status="FAILED",
                        error=f"pdftoppm fel: {result.stderr[:100]}",
                    )

                # Hitta genererade bilder
                img_files = sorted([
                    f for f in os.listdir(tmpdir)
                    if f.endswith(".png")
                ])

                total_chars = 0
                for page_num, img_file in enumerate(img_files, 1):
                    img_path = os.path.join(tmpdir, img_file)
                    txt_path = os.path.join(tmpdir, f"page_{page_num}")

                    # Kör tesseract
                    ocr_result = subprocess.run(
                        ["tesseract", img_path, txt_path,
                         "-l", self.language, "--psm", "6"],
                        capture_output=True, text=True, timeout=30
                    )

                    txt_file = txt_path + ".txt"
                    if not os.path.exists(txt_file):
                        continue

                    with open(txt_file, "r", encoding="utf-8",
                              errors="replace") as f:
                        ocr_text = f.read()

                    if not ocr_text.strip():
                        continue

                    paragraphs = re.split(r"\n{2,}", ocr_text)
                    for para in paragraphs:
                        para = para.strip()
                        if len(para) < 20:
                            continue

                        seg = TextSegment(
                            file_id=file_record.file_id,
                            file_path=path,
                            page_or_position=f"s.{page_num} (OCR-CLI)",
                            text=f"[OCR-EXTRAHERAD] {para[:500]}",
                            char_offset=total_chars,
                            extraction_method="tesseract_cli",
                            confidence="PARTIALLY_AVAILABLE",
                        )
                        segments.append(seg)
                        total_chars += len(para)

            self.log.append(
                f"[OCR] tesseract CLI: {len(img_files)} sidor, "
                f"{len(segments)} segment, {total_chars} tecken"
            )

            return ExtractionResult(
                file_id=file_record.file_id,
                file_path=path,
                file_name=os.path.basename(path),
                extraction_method="tesseract_cli",
                status="SUCCESS" if segments else "PARTIAL",
                segments=segments,
                page_count=len(img_files),
                char_count=total_chars,
                warnings=["[OCR-EXTRAHERAD] – Availability: PARTIALLY_AVAILABLE"],
            )

        except FileNotFoundError:
            return ExtractionResult(
                file_id=file_record.file_id,
                file_path=path,
                file_name=os.path.basename(path),
                extraction_method="tesseract_cli",
                status="FAILED",
                error="tesseract eller pdftoppm ej installerat",
            )
        except Exception as e:
            return ExtractionResult(
                file_id=file_record.file_id,
                file_path=path,
                file_name=os.path.basename(path),
                extraction_method="tesseract_cli",
                status="FAILED",
                error=str(e),
            )

    def _extract_pdftotext_raw(self, file_record: FileRecord) -> ExtractionResult:
        """
        Sista utväg: pdftotext med -raw flagga.
        Kan ge bättre resultat för vissa skannade PDF:er med inbäddad text.
        """
        path = file_record.file_path
        segments: List[TextSegment] = []

        try:
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
                tmp_path = tmp.name

            result = subprocess.run(
                ["pdftotext", "-raw", "-enc", "UTF-8", path, tmp_path],
                capture_output=True, text=True, timeout=30
            )

            if result.returncode != 0:
                os.unlink(tmp_path)
                return ExtractionResult(
                    file_id=file_record.file_id,
                    file_path=path,
                    file_name=os.path.basename(path),
                    extraction_method="pdftotext_raw",
                    status="FAILED",
                    error=f"pdftotext -raw fel: {result.stderr[:100]}",
                )

            with open(tmp_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            os.unlink(tmp_path)

            if not text.strip():
                return ExtractionResult(
                    file_id=file_record.file_id,
                    file_path=path,
                    file_name=os.path.basename(path),
                    extraction_method="pdftotext_raw",
                    status="PARTIAL",
                    error="Ingen text extraherad – troligen skannad bild utan OCR-lager",
                )

            total_chars = 0
            pages = text.split("\x0c")
            for page_num, page_text in enumerate(pages, 1):
                page_text = page_text.strip()
                if not page_text:
                    continue
                paragraphs = re.split(r"\n{2,}", page_text)
                for para in paragraphs:
                    para = para.strip()
                    if len(para) < 20:
                        continue
                    seg = TextSegment(
                        file_id=file_record.file_id,
                        file_path=path,
                        page_or_position=f"s.{page_num} (raw)",
                        text=f"[OCR-EXTRAHERAD] {para[:500]}",
                        char_offset=total_chars,
                        extraction_method="pdftotext_raw",
                        confidence="PARTIALLY_AVAILABLE",
                    )
                    segments.append(seg)
                    total_chars += len(para)

            return ExtractionResult(
                file_id=file_record.file_id,
                file_path=path,
                file_name=os.path.basename(path),
                extraction_method="pdftotext_raw",
                status="SUCCESS" if segments else "PARTIAL",
                segments=segments,
                page_count=len([p for p in pages if p.strip()]),
                char_count=total_chars,
                warnings=["[OCR-EXTRAHERAD] – Availability: PARTIALLY_AVAILABLE"],
            )

        except Exception as e:
            return ExtractionResult(
                file_id=file_record.file_id,
                file_path=path,
                file_name=os.path.basename(path),
                extraction_method="pdftotext_raw",
                status="FAILED",
                error=str(e),
            )

    def install_instructions(self) -> str:
        """Returnerar installationsinstruktioner."""
        return """
OCR-INSTALLATION:
  Ubuntu/Debian:
    sudo apt-get install tesseract-ocr tesseract-ocr-swe poppler-utils
    pip install pytesseract pdf2image Pillow

  macOS:
    brew install tesseract tesseract-lang poppler
    pip install pytesseract pdf2image Pillow

  Windows:
    Ladda ner Tesseract: https://github.com/UB-Mannheim/tesseract/wiki
    pip install pytesseract pdf2image Pillow

  Verifiera:
    tesseract --version
    tesseract --list-langs  # ska visa 'swe'
"""