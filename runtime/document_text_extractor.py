#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DOCUMENT TEXT EXTRACTOR – L2 AKTENS RÅDATA
SVENSK FORENSIC COURT AUDIT ENGINE v10.3-ROBUST
Datum: 2026-09-21

Robust textextraktion från PDF/DOCX/TXT/MD med:
- Absolut sökvägsresolverare för ärenderoten (case_paths.py)
- getattr-skydd mot AttributeError
- 4-stegs PDF-motor (pypdf → pdfplumber → fitz → ocr_fallback)

ABSOLUTA REGLER:
- Original-filer rörs ALDRIG – läses enbart
- Ingen tolkning, parafras eller inferens
- [KAN EJ EXTRAHERAS] bevaras oförändrat
- Varje textsegment kopplas till KÄLL-ID | FIL | SIDA | DATUM | VERSION
"""

from __future__ import annotations

import os
import re
import subprocess
import datetime
import tempfile
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

# Importera motorn
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from forensic_engine_v10_3_canonical import (
    ClaimId,
    Availability,
    FileRecord,
    CaseState,
    HardStopCode,
)

# Logger
logger = logging.getLogger(__name__)


# ============================================================
# ABSOLUT SÖKVÄGSRESOLVERARE
# ============================================================

def resolve_absolute_path(base_path: str) -> str:
    """
    Löser absolut sökväg för en ärenderot.

    Ärenderoten anvisas alltid av operatören — aldrig hårdkodad i koden
    (case_paths.py). Fallback-kedje:
    1. Använd base_path direkt om det finns.
    2. Försök varje operatörsanvisad ärenderot (SFCAE_CASE_ROOTS).
    """
    from case_paths import env_case_roots

    candidates = [base_path, *env_case_roots()]

    for candidate in candidates:
        if candidate and os.path.isdir(candidate):
            resolved = os.path.abspath(candidate)
            logger.info(f"[RESOLVE] Hittade ärenderot: {resolved}")
            return resolved

    logger.error(f"[RESOLVE] Kunde inte hitta någon giltig ärenderot. Försökte: {candidates}")
    return os.path.abspath(base_path)


def _gav_text(result: "ExtractionResult") -> bool:
    """True om en extraktionsväg faktiskt gav text — inte bara att
    statusen råkar heta SUCCESS/PARTIAL. pdftotext svarar PARTIAL med
    noll tecken på en skannad (bildbaserad) PDF; en sådan väg har inte
    gett text och kedjan ska gå vidare till nästa metod."""
    return result.status in ("SUCCESS", "PARTIAL") and (result.char_count or 0) > 0


# ============================================================
# KÄLLIDENTITET
# ============================================================

def _källidentitet(file_record) -> str:
    """
    Handlingens file_id, eller en SPÅRBAR felmarkering som är unik per fil.

    Återställd ur 76d29b1^. Fallbacken 'UNKNOWN' gav varje handling utan
    file_id samma identitet, så att påståenden ur skilda dokument redovisades
    som hämtade ur en och samma källa. Saknas file_id är det ett fel
    uppströms; markeringen säger vad som hänt och skiljer ändå handlingarna
    åt via sökvägens hash.
    """
    fid = getattr(file_record, "file_id", None)
    if fid:
        return str(fid)
    sökväg = (
        getattr(file_record, "file_path", None)
        or getattr(file_record, "path", None)
        or ""
    )
    if sökväg:
        import hashlib as _h
        stam = _h.sha256(str(sökväg).encode("utf-8", "replace")).hexdigest()[:12]
        return f"KÄLLA_EJ_IDENTIFIERAD_{stam}"
    return f"KÄLLA_EJ_IDENTIFIERAD_{id(file_record):x}"


# ============================================================
# DATAKLASSER
# ============================================================

@dataclass
class TextSegment:
    """
    Ett textsegment extraherat från en fil.
    Ordagrann text – aldrig parafras eller tolkning.
    """
    file_id: str
    file_path: str
    page_or_position: str    # "s.1", "rad 42", "avsnitt: Bedömning"
    text: str                # Ordagrann text
    char_offset: int = 0     # Position i dokumentet
    extraction_method: str = "UNKNOWN"  # pdftotext | pypdf | pdfplumber | fitz | ocr | python-docx | plaintext
    confidence: str = "VERIFIED"  # VERIFIED | PARTIALLY_AVAILABLE | KAN EJ EXTRAHERAS
    # Steg 14: kapning vid extraktion (MAX_SEGMENT_LENGTH) flaggas här - text
    # ovan är redan kapad, så längden på self.text kan inte visa det.
    text_trunkerad: bool = False

    def to_claim_id(
        self,
        claim_counter: int,
        source_id: str,
        date: str = "SAKNAS",
        version: str = "SAKNAS",
        datum_källa: str = "SAKNAS",
        version_källa: str = "SAKNAS",
    ) -> ClaimId:
        """
        Konverterar textsegment till ClaimId (7-fältsformat FIX-B).
        Påståendetyp bestäms av confidence.
        """
        # FIX-C: EVIDENCED_FACT förbjudet på PARTIALLY_AVAILABLE
        if self.confidence == "VERIFIED":
            claim_type = "CLAIM"
            availability = Availability.VERIFIED
        elif self.confidence == "PARTIALLY_AVAILABLE":
            claim_type = "CLAIM"
            availability = Availability.PARTIALLY_AVAILABLE
        else:
            claim_type = "CLAIM"
            availability = Availability.NOT_FOUND

        return ClaimId(
            claim_id=f"C-{claim_counter:03d}",
            content=self.text[:500],
            text_trunkerad=self.text_trunkerad or len(self.text) > 500,
            datum_källa=datum_källa,
            version_källa=version_källa,
            source_id=source_id,
            file_name=os.path.basename(self.file_path),
            page=self.page_or_position,
            date=date,
            version=version,
            claim_type=claim_type,
            availability=availability,
            # TIDSKOD endast när positionen faktiskt är en tidsangivelse
            # (ljud/video); AVSNITT fastställs inte här och redovisas SAKNAS.
            tidskod=(self.page_or_position
                     if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?(\.\d+)?", str(self.page_or_position or "").strip())
                     else "SAKNAS"),
        )


@dataclass
class ExtractionResult:
    """Resultat från textextraktion av en fil."""
    file_id: str
    file_path: str
    file_name: str
    extraction_method: str
    status: str              # SUCCESS | PARTIAL | FAILED | UNSUPPORTED | EJ_TEXTBÄRANDE
    segments: List[TextSegment] = field(default_factory=list)
    page_count: int = 0
    char_count: int = 0
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_id": self.file_id,
            "file_name": self.file_name,
            "extraction_method": self.extraction_method,
            "status": self.status,
            "page_count": self.page_count,
            "char_count": self.char_count,
            "segments_count": len(self.segments),
            "error": self.error,
            "warnings": self.warnings,
        }


# ============================================================
# DOCUMENT TEXT EXTRACTOR – ROBUST VERSION
# ============================================================

def _ser_binär_ut(path: str, prov: int = 8192) -> bool:
    """True om filens början är binär: NUL-byte eller mer än 30 % styrtecken
    (utom tabb/radbrytningar). Gäller bara format som inte känts igen."""
    try:
        with open(path, "rb") as f:
            data = f.read(prov)
    except OSError:
        return False  # läsfelet redovisas av den ordinarie extraktionen
    if not data:
        return False
    if b"\x00" in data:
        return True
    styr = sum(1 for b in data if b < 32 and b not in (9, 10, 12, 13))
    return styr / len(data) > 0.30


class DocumentTextExtractor:
    """
    L2: Extraherar text från filer för claim_id-registrering.

    4-stegs PDF-motor:
    1. pdftotext (poppler-utils) – snabbast
    2. pypdf – Python fallback
    3. pdfplumber – bättre layout
    4. fitz (PyMuPDF) – robust
    5. ocr_fallback – skannade bilder

    Stödda format:
    - PDF: 4-stegs motor
    - DOCX/DOC: python-docx
    - TXT/MD/CSV: direkt läsning
    """

    MIN_SEGMENT_LENGTH = 20
    MAX_SEGMENT_LENGTH = 500

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.log: List[str] = []

    # Magic-typer som aldrig bär läsbar text (återställt ur 76d29b1^).
    # Motsvarar vokabulären i forensic_engine_v10_3_canonical.detect_filetype_magic().
    ICKE_TEXTBÄRANDE_MAGIC = (
        "MP3", "WAV", "AVI", "FLAC", "OGG", "MP4", "MKV", "WEBM", "M4A",
        "JPEG", "JPG", "PNG", "GIF", "TIFF", "BMP", "HEIC",
    )

    # Filändelser som stöd när magic inte räcker.
    ICKE_TEXTBÄRANDE_ÄNDELSER = (
        ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma",
        ".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv",
        ".jpg", ".jpeg", ".png", ".gif", ".tiff", ".tif", ".bmp", ".heic",
    )

    def _är_icke_textbärande(self, file_record: FileRecord) -> bool:
        """True för ljud, video och bild — format som kräver annan förmåga."""
        magic = (getattr(file_record, "filtyp_magic", "") or "").upper()
        for m in self.ICKE_TEXTBÄRANDE_MAGIC:
            if m in magic:
                return True
        namn = (getattr(file_record, "file_path", "") or "").lower()
        return namn.endswith(self.ICKE_TEXTBÄRANDE_ÄNDELSER)

    def extract_file(self, file_record: FileRecord) -> ExtractionResult:
        """
        Extraherar text från en fil baserat på magic bytes-typ.
        Väljer extraktionsmetod dynamiskt.
        """
        # getattr-skydd för file_record-attribut
        try:
            magic = getattr(file_record, 'filtyp_magic', 'UNKNOWN').upper()
            path = getattr(file_record, 'file_path', '')
            file_id = _källidentitet(file_record)
        except AttributeError as e:
            logger.error(f"[L2] AttributeError vid läsning av FileRecord: {e}")
            return ExtractionResult(
                file_id="UNKNOWN",
                file_path="UNKNOWN",
                file_name="UNKNOWN",
                extraction_method="NONE",
                status="FAILED",
                error=f"FileRecord-fel: {str(e)}",
            )

        if not os.path.exists(path):
            return ExtractionResult(
                file_id=file_id,
                file_path=path,
                file_name=os.path.basename(path),
                extraction_method="NONE",
                status="FAILED",
                error=f"Fil finns inte: {path}",
            )

        self.log.append(f"[L2] Extraherar {file_id} ({magic}): {os.path.basename(path)}")

        # Kontrollen ligger FÖRE typvalet: ett ljud- eller bildformat vars
        # magic råkar matcha en textgren får inte nå _extract_plaintext.
        if self._är_icke_textbärande(file_record):
            return ExtractionResult(
                file_id=file_id,
                file_path=path,
                file_name=os.path.basename(path),
                extraction_method="NONE",
                status="EJ_TEXTBÄRANDE",
                error=(
                    f"Formatet {magic} bär inte text. Kräver transkribering "
                    f"eller bildtolkning — inte textextraktion."
                ),
            )

        if "PDF" in magic:
            return self._extract_pdf_robust(file_record)
        elif "ZIP/DOCX" in magic or "WORD" in magic:
            return self._extract_docx(file_record)
        elif "TEXT" in magic or "MARKDOWN" in magic or "YAML" in magic:
            return self._extract_plaintext(file_record)
        elif "JSON" in magic or "XML" in magic:
            return self._extract_plaintext(file_record)
        else:
            # Okänt format: läs som text bara om innehållet faktiskt är text.
            # latin-1 avkodar alla bytes, så utan den här kontrollen blev
            # binärt material (ljud, bild) "VERIFIED"-claims av rena
            # bytevärden — och HS04 (material finns men ingen text kunde
            # läsas) kunde aldrig utlösas.
            if _ser_binär_ut(path):
                return ExtractionResult(
                    file_id=file_id,
                    file_path=path,
                    file_name=os.path.basename(path),
                    extraction_method="NONE",
                    status="EJ_TEXTBÄRANDE",
                    error=f"Binärt innehåll utan läsbar text: {magic}",
                )
            result = self._extract_plaintext(file_record)
            if result.status == "SUCCESS" and result.char_count > 0:
                return result
            return ExtractionResult(
                file_id=file_id,
                file_path=path,
                file_name=os.path.basename(path),
                extraction_method="UNSUPPORTED",
                status="UNSUPPORTED",
                error=f"Format ej stödt: {magic}",
            )

    def _extract_pdf_robust(self, file_record: FileRecord) -> ExtractionResult:
        """
        4-stegs PDF-motor med fallback-kedje.
        1. pdftotext (poppler-utils)
        2. pypdf
        3. pdfplumber
        4. fitz (PyMuPDF)
        5. ocr_fallback (tesseract)
        """
        path = getattr(file_record, 'file_path', '')
        file_id = _källidentitet(file_record)
        file_name = os.path.basename(path)

        # Försök 1: pdftotext
        logger.info(f"[PDF] Försöker pdftotext på {file_name}")
        result = self._pdf_pdftotext(file_record)
        if _gav_text(result):
            return result

        # Försök 2: pypdf
        logger.info(f"[PDF] Försöker pypdf på {file_name}")
        result = self._pdf_pypdf(file_record)
        if _gav_text(result):
            return result

        # Försök 3: pdfplumber
        logger.info(f"[PDF] Försöker pdfplumber på {file_name}")
        result = self._pdf_pdfplumber(file_record)
        if _gav_text(result):
            return result

        # Försök 4: fitz (PyMuPDF)
        logger.info(f"[PDF] Försöker fitz (PyMuPDF) på {file_name}")
        result = self._pdf_fitz(file_record)
        if _gav_text(result):
            return result

        # Försök 5: ocr_fallback
        logger.info(f"[PDF] Försöker OCR-fallback på {file_name}")
        result = self._pdf_ocr_fallback(file_record)
        if _gav_text(result):
            return result

        # Alla försök misslyckades
        return ExtractionResult(
            file_id=file_id,
            file_path=path,
            file_name=file_name,
            extraction_method="all_failed",
            status="FAILED",
            error="Alla PDF-extraktionsmetoder misslyckades",
        )

    def _pdf_pdftotext(self, file_record: FileRecord) -> ExtractionResult:
        """Steg 1: pdftotext (poppler-utils)"""
        path = getattr(file_record, 'file_path', '')
        file_id = _källidentitet(file_record)
        file_name = os.path.basename(path)
        segments: List[TextSegment] = []
        warnings: List[str] = []

        try:
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
                tmp_path = tmp.name

            result = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", path, tmp_path],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                result2 = subprocess.run(
                    ["pdftotext", "-enc", "UTF-8", path, tmp_path],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result2.returncode != 0:
                    return ExtractionResult(
                        file_id=file_id,
                        file_path=path,
                        file_name=file_name,
                        extraction_method="pdftotext",
                        status="FAILED",
                        error=f"pdftotext: {result.stderr[:200]}",
                    )

            with open(tmp_path, "r", encoding="utf-8", errors="replace") as f:
                full_text = f.read()

            os.unlink(tmp_path)

            if not full_text.strip():
                warnings.append("PDF verkar vara skannad – inga textlager funna")
                return ExtractionResult(
                    file_id=file_id,
                    file_path=path,
                    file_name=file_name,
                    extraction_method="pdftotext",
                    status="PARTIAL",
                    segments=[],
                    warnings=warnings,
                )

            # Dela upp per sida
            pages = full_text.split("\x0c")
            total_chars = 0

            for page_num, page_text in enumerate(pages, 1):
                page_text = page_text.strip()
                if not page_text:
                    continue

                paragraphs = self._split_into_paragraphs(page_text)
                for para in paragraphs:
                    if len(para) < self.MIN_SEGMENT_LENGTH:
                        continue
                    seg = TextSegment(
                        file_id=file_id,
                        file_path=path,
                        page_or_position=f"s.{page_num}",
                        text=para[:self.MAX_SEGMENT_LENGTH],
                        text_trunkerad=len(para) > self.MAX_SEGMENT_LENGTH,
                        char_offset=total_chars,
                        extraction_method="pdftotext",
                        confidence="VERIFIED",
                    )
                    segments.append(seg)
                    total_chars += len(para)

            return ExtractionResult(
                file_id=file_id,
                file_path=path,
                file_name=file_name,
                extraction_method="pdftotext",
                status="SUCCESS" if segments else "PARTIAL",
                segments=segments,
                page_count=len([p for p in pages if p.strip()]),
                char_count=total_chars,
                warnings=warnings,
            )

        except subprocess.TimeoutExpired:
            return ExtractionResult(
                file_id=file_id,
                file_path=path,
                file_name=file_name,
                extraction_method="pdftotext",
                status="FAILED",
                error="pdftotext timeout",
            )
        except Exception as e:
            return ExtractionResult(
                file_id=file_id,
                file_path=path,
                file_name=file_name,
                extraction_method="pdftotext",
                status="FAILED",
                error=str(e),
            )

    def _pdf_pypdf(self, file_record: FileRecord) -> ExtractionResult:
        """Steg 2: pypdf"""
        path = getattr(file_record, 'file_path', '')
        file_id = _källidentitet(file_record)
        file_name = os.path.basename(path)
        segments: List[TextSegment] = []

        try:
            from pypdf import PdfReader
            reader = PdfReader(path)
            total_chars = 0

            for page_num, page in enumerate(reader.pages, 1):
                text = page.extract_text()
                if not text:
                    continue

                paragraphs = self._split_into_paragraphs(text)
                for para in paragraphs:
                    if len(para) < self.MIN_SEGMENT_LENGTH:
                        continue
                    seg = TextSegment(
                        file_id=file_id,
                        file_path=path,
                        page_or_position=f"s.{page_num}",
                        text=para[:self.MAX_SEGMENT_LENGTH],
                        text_trunkerad=len(para) > self.MAX_SEGMENT_LENGTH,
                        char_offset=total_chars,
                        extraction_method="pypdf",
                        confidence="VERIFIED",
                    )
                    segments.append(seg)
                    total_chars += len(para)

            return ExtractionResult(
                file_id=file_id,
                file_path=path,
                file_name=file_name,
                extraction_method="pypdf",
                status="SUCCESS" if segments else "PARTIAL",
                segments=segments,
                page_count=len(reader.pages),
                char_count=total_chars,
            )

        except ImportError:
            return ExtractionResult(
                file_id=file_id,
                file_path=path,
                file_name=file_name,
                extraction_method="pypdf",
                status="FAILED",
                error="pypdf ej installerat",
            )
        except Exception as e:
            return ExtractionResult(
                file_id=file_id,
                file_path=path,
                file_name=file_name,
                extraction_method="pypdf",
                status="FAILED",
                error=str(e),
            )

    def _pdf_pdfplumber(self, file_record: FileRecord) -> ExtractionResult:
        """Steg 3: pdfplumber"""
        path = getattr(file_record, 'file_path', '')
        file_id = _källidentitet(file_record)
        file_name = os.path.basename(path)
        segments: List[TextSegment] = []

        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                total_chars = 0

                for page_num, page in enumerate(pdf.pages, 1):
                    text = page.extract_text()
                    if not text:
                        continue

                    paragraphs = self._split_into_paragraphs(text)
                    for para in paragraphs:
                        if len(para) < self.MIN_SEGMENT_LENGTH:
                            continue
                        seg = TextSegment(
                            file_id=file_id,
                            file_path=path,
                            page_or_position=f"s.{page_num}",
                            text=para[:self.MAX_SEGMENT_LENGTH],
                            text_trunkerad=len(para) > self.MAX_SEGMENT_LENGTH,
                            char_offset=total_chars,
                            extraction_method="pdfplumber",
                            confidence="VERIFIED",
                        )
                        segments.append(seg)
                        total_chars += len(para)

            return ExtractionResult(
                file_id=file_id,
                file_path=path,
                file_name=file_name,
                extraction_method="pdfplumber",
                status="SUCCESS" if segments else "PARTIAL",
                segments=segments,
                page_count=len(pdf.pages),
                char_count=total_chars,
            )

        except ImportError:
            return ExtractionResult(
                file_id=file_id,
                file_path=path,
                file_name=file_name,
                extraction_method="pdfplumber",
                status="FAILED",
                error="pdfplumber ej installerat",
            )
        except Exception as e:
            return ExtractionResult(
                file_id=file_id,
                file_path=path,
                file_name=file_name,
                extraction_method="pdfplumber",
                status="FAILED",
                error=str(e),
            )

    def _pdf_fitz(self, file_record: FileRecord) -> ExtractionResult:
        """Steg 4: fitz (PyMuPDF)"""
        path = getattr(file_record, 'file_path', '')
        file_id = _källidentitet(file_record)
        file_name = os.path.basename(path)
        segments: List[TextSegment] = []

        try:
            import fitz
            doc = fitz.open(path)
            total_chars = 0

            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text()
                if not text:
                    continue

                paragraphs = self._split_into_paragraphs(text)
                for para in paragraphs:
                    if len(para) < self.MIN_SEGMENT_LENGTH:
                        continue
                    seg = TextSegment(
                        file_id=file_id,
                        file_path=path,
                        page_or_position=f"s.{page_num + 1}",
                        text=para[:self.MAX_SEGMENT_LENGTH],
                        text_trunkerad=len(para) > self.MAX_SEGMENT_LENGTH,
                        char_offset=total_chars,
                        extraction_method="fitz",
                        confidence="VERIFIED",
                    )
                    segments.append(seg)
                    total_chars += len(para)

            page_count = len(doc)
            doc.close()

            return ExtractionResult(
                file_id=file_id,
                file_path=path,
                file_name=file_name,
                extraction_method="fitz",
                status="SUCCESS" if segments else "PARTIAL",
                segments=segments,
                page_count=page_count,
                char_count=total_chars,
            )

        except ImportError:
            return ExtractionResult(
                file_id=file_id,
                file_path=path,
                file_name=file_name,
                extraction_method="fitz",
                status="FAILED",
                error="fitz ej installerat",
            )
        except Exception as e:
            return ExtractionResult(
                file_id=file_id,
                file_path=path,
                file_name=file_name,
                extraction_method="fitz",
                status="FAILED",
                error=str(e),
            )

    def _pdf_ocr_fallback(self, file_record: FileRecord) -> ExtractionResult:
        """Steg 5: OCR-fallback för skannade PDFs"""
        path = getattr(file_record, 'file_path', '')
        file_id = _källidentitet(file_record)
        file_name = os.path.basename(path)

        try:
            import pytesseract
            from PIL import Image
            import fitz

            doc = fitz.open(path)
            segments: List[TextSegment] = []
            total_chars = 0

            for page_num in range(len(doc)):
                page = doc[page_num]
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                # pix.samples är den råa pixelbufferten. pix.tobytes() ger
                # istället PNG-kodade bytes — Image.frombytes kräver rådata,
                # inte ett kodat bildformat, och kraschade tidigare med
                # "not enough image data" på varje anrop.
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                text = pytesseract.image_to_string(img, lang='swe+eng')

                if not text.strip():
                    continue

                paragraphs = self._split_into_paragraphs(text)
                for para in paragraphs:
                    if len(para) < self.MIN_SEGMENT_LENGTH:
                        continue
                    seg = TextSegment(
                        file_id=file_id,
                        file_path=path,
                        page_or_position=f"s.{page_num + 1}",
                        text=para[:self.MAX_SEGMENT_LENGTH],
                        text_trunkerad=len(para) > self.MAX_SEGMENT_LENGTH,
                        char_offset=total_chars,
                        extraction_method="ocr_fallback",
                        confidence="PARTIALLY_AVAILABLE",
                    )
                    segments.append(seg)
                    total_chars += len(para)

            page_count = len(doc)
            doc.close()

            return ExtractionResult(
                file_id=file_id,
                file_path=path,
                file_name=file_name,
                extraction_method="ocr_fallback",
                status="SUCCESS" if segments else "PARTIAL",
                segments=segments,
                page_count=page_count,
                char_count=total_chars,
                warnings=["Denna PDF användes OCR (låg precision möjlig)"],
            )

        except ImportError:
            return ExtractionResult(
                file_id=file_id,
                file_path=path,
                file_name=file_name,
                extraction_method="ocr_fallback",
                status="FAILED",
                error="pytesseract eller PIL ej installerat",
            )
        except Exception as e:
            return ExtractionResult(
                file_id=file_id,
                file_path=path,
                file_name=file_name,
                extraction_method="ocr_fallback",
                status="FAILED",
                error=str(e),
            )

    def _extract_docx(self, file_record: FileRecord) -> ExtractionResult:
        """Extraherar text från DOCX via python-docx."""
        path = getattr(file_record, 'file_path', '')
        file_id = _källidentitet(file_record)
        file_name = os.path.basename(path)
        segments: List[TextSegment] = []

        try:
            import docx as python_docx
            doc = python_docx.Document(path)
            total_chars = 0
            para_num = 0

            for para in doc.paragraphs:
                text = para.text.strip()
                if len(text) < self.MIN_SEGMENT_LENGTH:
                    continue
                para_num += 1
                seg = TextSegment(
                    file_id=file_id,
                    file_path=path,
                    page_or_position=f"stycke {para_num}",
                    text=text[:self.MAX_SEGMENT_LENGTH],
                    text_trunkerad=len(text) > self.MAX_SEGMENT_LENGTH,
                    char_offset=total_chars,
                    extraction_method="python-docx",
                    confidence="VERIFIED",
                )
                segments.append(seg)
                total_chars += len(text)

            for table_num, table in enumerate(doc.tables, 1):
                for row in table.rows:
                    row_text = " | ".join(
                        cell.text.strip() for cell in row.cells
                        if cell.text.strip()
                    )
                    if len(row_text) < self.MIN_SEGMENT_LENGTH:
                        continue
                    seg = TextSegment(
                        file_id=file_id,
                        file_path=path,
                        page_or_position=f"tabell {table_num}",
                        text=row_text[:self.MAX_SEGMENT_LENGTH],
                        text_trunkerad=len(row_text) > self.MAX_SEGMENT_LENGTH,
                        char_offset=total_chars,
                        extraction_method="python-docx",
                        confidence="VERIFIED",
                    )
                    segments.append(seg)
                    total_chars += len(row_text)

            return ExtractionResult(
                file_id=file_id,
                file_path=path,
                file_name=file_name,
                extraction_method="python-docx",
                status="SUCCESS" if segments else "PARTIAL",
                segments=segments,
                page_count=0,
                char_count=total_chars,
            )

        except ImportError:
            return ExtractionResult(
                file_id=file_id,
                file_path=path,
                file_name=file_name,
                extraction_method="python-docx",
                status="FAILED",
                error="python-docx ej installerat",
            )
        except Exception as e:
            return ExtractionResult(
                file_id=file_id,
                file_path=path,
                file_name=file_name,
                extraction_method="python-docx",
                status="FAILED",
                error=str(e),
            )

    def _extract_plaintext(self, file_record: FileRecord) -> ExtractionResult:
        """Extraherar text från TXT/MD/CSV/JSON/XML via direkt läsning."""
        path = getattr(file_record, 'file_path', '')
        file_id = _källidentitet(file_record)
        file_name = os.path.basename(path)
        segments: List[TextSegment] = []

        for encoding in ["utf-8", "utf-8-sig", "latin-1", "cp1252"]:
            try:
                with open(path, "r", encoding=encoding, errors="strict") as f:
                    full_text = f.read()
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            return ExtractionResult(
                file_id=file_id,
                file_path=path,
                file_name=file_name,
                extraction_method="plaintext",
                status="FAILED",
                error="Kunde inte avkoda fil",
            )

        lines = full_text.splitlines()
        total_chars = 0
        line_num = 0
        current_para: List[str] = []
        current_start_line = 1

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped:
                current_para.append(stripped)
            else:
                if current_para:
                    para_text = " ".join(current_para)
                    if len(para_text) >= self.MIN_SEGMENT_LENGTH:
                        line_num += 1
                        seg = TextSegment(
                            file_id=file_id,
                            file_path=path,
                            page_or_position=f"rad {current_start_line}",
                            text=para_text[:self.MAX_SEGMENT_LENGTH],
                            text_trunkerad=len(para_text) > self.MAX_SEGMENT_LENGTH,
                            char_offset=total_chars,
                            extraction_method="plaintext",
                            confidence="VERIFIED",
                        )
                        segments.append(seg)
                        total_chars += len(para_text)
                    current_para = []
                    current_start_line = i + 1

        if current_para:
            para_text = " ".join(current_para)
            if len(para_text) >= self.MIN_SEGMENT_LENGTH:
                seg = TextSegment(
                    file_id=file_id,
                    file_path=path,
                    page_or_position=f"rad {current_start_line}",
                    text=para_text[:self.MAX_SEGMENT_LENGTH],
                    text_trunkerad=len(para_text) > self.MAX_SEGMENT_LENGTH,
                    char_offset=total_chars,
                    extraction_method="plaintext",
                    confidence="VERIFIED",
                )
                segments.append(seg)
                total_chars += len(para_text)

        return ExtractionResult(
            file_id=file_id,
            file_path=path,
            file_name=file_name,
            extraction_method="plaintext",
            status="SUCCESS" if segments else "PARTIAL",
            segments=segments,
            page_count=0,
            char_count=total_chars,
        )

    def _split_into_paragraphs(self, text: str) -> List[str]:
        """Delar upp text i meningsfulla stycken."""
        paragraphs = re.split(r"\n{2,}", text)
        result = []
        for para in paragraphs:
            cleaned = re.sub(r"\s+", " ", para).strip()
            if cleaned:
                result.append(cleaned)
        return result

    def extract_all(
        self,
        case_state: CaseState,
        max_files: Optional[int] = None,
    ) -> Dict[str, ExtractionResult]:
        """
        Extraherar text från alla filer i case_state.
        Fyller case_state.claims med ClaimId-objekt.
        """
        results: Dict[str, ExtractionResult] = {}
        claim_counter = len(case_state.claims) + 1

        files_to_process = case_state.files
        if max_files:
            files_to_process = files_to_process[:max_files]

        self.log.append(
            f"[L2] Startar textextraktion: {len(files_to_process)} filer"
        )

        for file_record in files_to_process:
            # getattr-skydd för quarantine_flag
            quarantine = getattr(file_record, 'quarantine_flag', False)
            if quarantine:
                file_id = _källidentitet(file_record)
                self.log.append(f"[L2] Hoppar över karantänfil: {file_id}")
                continue

            result = self.extract_file(file_record)
            file_id = _källidentitet(file_record)
            results[file_id] = result

            if result.status in ("SUCCESS", "PARTIAL"):
                file_path = getattr(file_record, 'file_path', '')
                file_date = "SAKNAS"
                try:
                    mtime = os.path.getmtime(file_path)
                    file_date = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
                except (OSError, ValueError):
                    pass

                for segment in result.segments:
                    try:
                        claim = segment.to_claim_id(
                            claim_counter=claim_counter,
                            source_id=file_id,
                            date=file_date,
                            version="v1.0",
                            # Proveniens redovisas: mtime/standardversion är inte
                            # dokumentmetadata (steg 13).
                            datum_källa="FIL_MTIME" if file_date != "SAKNAS" else "SAKNAS",
                            version_källa="STANDARDVÄRDE",
                        )
                        errors = claim.validate()
                        if not errors:
                            case_state.claims.append(claim)
                            claim_counter += 1
                        else:
                            self.log.append(
                                f"[L2] ClaimId-valideringsfel för {file_id}: {errors}"
                            )
                    except Exception as e:
                        self.log.append(f"[L2] Fel vid claim-konvertering: {str(e)}")

        total_claims = len(case_state.claims)
        successful = sum(1 for r in results.values() if r.status == "SUCCESS")
        failed = sum(1 for r in results.values() if r.status == "FAILED")
        unsupported = sum(1 for r in results.values() if r.status == "UNSUPPORTED")
        ej_textbärande = sum(1 for r in results.values() if r.status == "EJ_TEXTBÄRANDE")

        self.log.append(
            f"[L2] Extraktion klar: {successful} lyckade, {failed} misslyckade, "
            f"{unsupported} ej stödda, {ej_textbärande} ej textbärande. "
            f"Totalt {total_claims} claims registrerade."
        )

        return results

    def generate_l2_report(
        self,
        results: Dict[str, ExtractionResult],
        case_state: CaseState,
    ) -> str:
        """Genererar L2-rapport i lagerformat."""
        lines = [
            "## LAGER 2 – AKTENS RÅDATA (ROBUST)",
            "",
            f"Totalt claims registrerade: {len(case_state.claims)} "
            f"[C-001–C-{len(case_state.claims):03d} | TOTALT: {len(case_state.claims)} claim_id]",
            "",
            "### Extraktionsresultat per fil",
        ]

        for file_id, result in results.items():
            status_symbol = "✓" if result.status == "SUCCESS" else "⚠" if result.status == "PARTIAL" else "✗"
            lines.append(
                f"{status_symbol} {file_id} | {result.file_name} | "
                f"{result.extraction_method} | {result.status} | "
                f"{result.char_count} tecken | {len(result.segments)} segment"
            )
            if result.error:
                lines.append(f"  → FEL: {result.error}")
            for w in result.warnings:
                lines.append(f"  → VARNING: {w}")

        lines.extend([
            "",
            "### Claim_id-register (urval, max 10)",
        ])

        for claim in case_state.claims[:10]:
            lines.append(claim.to_formatted_string())
            lines.append("")

        if len(case_state.claims) > 10:
            lines.append(
                f"[... {len(case_state.claims) - 10} ytterligare claims ej visade ...]"
            )

        lines.append("")
        lines.append("[L2 | AKTENS RÅDATA | ROBUST | LOCKED]")
        return "\n".join(lines)
