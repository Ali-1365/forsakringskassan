#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EVIDENCE CATEGORIZER – SVENSK FORENSIC COURT AUDIT ENGINE v10.3-UPDATED
Datum: 2026-08-23

Namnbaserad kategorisering av bevisning (SKILL_architecture_v10.3_v3.md sektion 6).
Läser ALDRIG filinnehåll – kategoriserar enbart baserat på filnamn och sökväg.

Output: bevis_kategorisering.json + bevis_kategorisering.md
"""

from __future__ import annotations

import json
import os
import sys
import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any, Optional


# ============================================================
# KATEGORIER
# ============================================================

KATEGORI_REGLER = {
    "RÄTTSLIG": {
        "nyckelord": [
            "dom", "beslut", "tingsrätt", "hovrätt", "hfd", "hd",
            "förvaltningsrätt", "kammarrätt", "stämning", "överklagande",
            "inlaga", "yttrande", "protokoll", "aktbilaga", "diarienummer",
            "mål", "ärende", "rättegång", "förhandling",
        ],
        "prioritet": 1,
        "processuell_relevans": "DIREKT",
    },
    "MEDICINSK": {
        "nyckelord": [
            "läkarintyg", "journal", "rättsintyg", "diagnos", "patient",
            "medicinsk", "sjukpenning", "arbetsförmåga", "rehabilitering",
            "specialist", "psykiater", "ortoped", "neurolog", "mrt", "emg",
            "neurografi", "röntgen", "bilddiagnostik", "utlåtande",
        ],
        "prioritet": 2,
        "processuell_relevans": "DIREKT",
    },
    "EKONOMISK": {
        "nyckelord": [
            "bank", "transaktion", "transfer", "faktura", "bokföring",
            "räkenskaper", "balansräkning", "resultaträkning", "skatt",
            "inkomst", "lön", "ersättning", "sgi", "sjukpenning_belopp",
            "återkrav", "skuld", "betalning",
        ],
        "prioritet": 3,
        "processuell_relevans": "STÖDJANDE",
    },
    "SYSTEM": {
        "nyckelord": [
            "logg", "log", "metadata", "exif", "hash", "sha256",
            "digital", "e-post", "email", "sms", "chatt", "fil",
            "databas", "system", "server", "ip", "timestamp",
        ],
        "prioritet": 4,
        "processuell_relevans": "STÖDJANDE",
    },
    "LJUD_VIDEO": {
        "nyckelord": [
            ".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac",
            ".mp4", ".mov", ".mkv", ".avi", ".webm",
            "ljud", "audio", "video", "inspelning", "transkription",
            "förhandling_ljud",
        ],
        "prioritet": 2,
        "processuell_relevans": "DIREKT",
    },
    "KORRESPONDENS": {
        "nyckelord": [
            "brev", "e-post", "email", "meddelande", "kommunikation",
            "korrespondens", "skrivelse", "remiss", "svar",
        ],
        "prioritet": 3,
        "processuell_relevans": "STÖDJANDE",
    },
    "ÖVRIGT": {
        "nyckelord": [],
        "prioritet": 9,
        "processuell_relevans": "OKÄND",
    },
}


# ============================================================
# DATAKLASSER
# ============================================================

@dataclass
class BevisPost:
    """En kategoriserad bevispost."""
    fil_id: str
    filnamn: str
    relativ_sökväg: str
    kategori: str
    prioritet: int
    processuell_relevans: str
    matchade_nyckelord: List[str] = field(default_factory=list)
    filtyp: str = ""
    storlek_bytes: int = 0
    hash_sha256: str = "KAN EJ VERIFIERAS"
    # Additional fields for enrichment (default values, as we do not read file content)
    status: str = ""
    beviskedje_funktion: str = ""
    atgard_prioritet: int = 3
    matchade_termer: List[str] = field(default_factory=list)
    extraherat_datum: Optional[str] = None
    sokvag: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fil_id": self.fil_id,
            "filnamn": self.filnamn,
            "relativ_sökväg": self.relativ_sökväg,
            "kategori": self.kategori,
            "prioritet": self.prioritet,
            "processuell_relevans": self.processuell_relevans,
            "matchade_nyckelord": self.matchade_nyckelord,
            "filtyp": self.filtyp,
            "storlek_bytes": self.storlek_bytes,
            "hash_sha256": self.hash_sha256,
            "status": self.status,
            "beviskedje_funktion": self.beviskedje_funktion,
            "atgard_prioritet": self.atgard_prioritet,
            "matchade_termer": self.matchade_termer,
            "extraherat_datum": self.extraherat_datum,
            "sokvag": self.sokvag,
        }


@dataclass
class KategoriseringsRapport:
    """Fullständig kategoriseringsrapport."""
    case_id: str
    timestamp: str = ""
    totalt_filer: int = 0
    poster: List[BevisPost] = field(default_factory=list)
    kategori_statistik: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "timestamp": self.timestamp,
            "totalt_filer": self.totalt_filer,
            "kategori_statistik": self.kategori_statistik,
            "poster": [p.to_dict() for p in self.poster],
        }

    def to_markdown(self) -> str:
        lines = [
            "# BEVIS KATEGORISERING",
            f"## Case ID: {self.case_id}",
            f"## Datum: {self.timestamp}",
            f"## Totalt filer: {self.totalt_filer}",
            "",
            "## Statistik per kategori",
        ]
        for kategori, antal in sorted(self.kategori_statistik.items()):
            lines.append(f"- {kategori}: {antal} filer")
        lines.append("")
        lines.append("## Detaljerad lista")
        lines.append("")

        # Sortera efter prioritet
        sorted_poster = sorted(self.poster, key=lambda p: (p.prioritet, p.filnamn))
        for post in sorted_poster:
            lines.append(
                f"### {post.fil_id}"
            )
            lines.append(f"- Fil: {post.filnamn}")
            lines.append(f"- Sökväg: {post.relativ_sökväg}")
            lines.append(f"- Kategori: {post.kategori}")
            lines.append(f"- Processuell relevans: {post.processuell_relevans}")
            lines.append(f"- Prioritet: {post.prioritet}")
            if post.matchade_nyckelord:
                lines.append(f"- Matchade nyckelord: {', '.join(post.matchade_nyckelord[:5])}")
            lines.append("")

        return "\n".join(lines)


# ============================================================
# KATEGORISERING
# ============================================================

def kategorisera_fil(
    filnamn: str,
    relativ_sökväg: str,
    fil_id: str = "",
    storlek_bytes: int = 0,
    hash_sha256: str = "KAN EJ VERIFIERAS",
) -> BevisPost:
    """
    Kategoriserar en fil baserat på filnamn och sökväg.
    Läser ALDRIG filinnehåll.
    """
    if isinstance(filnamn, Path):
        filnamn = str(filnamn)
    if isinstance(relativ_sökväg, Path):
        relativ_sökväg = str(relativ_sökväg)
    path_lower = (filnamn + " " + relativ_sökväg).lower()
    ext = Path(filnamn).suffix.lower()

    bästa_kategori = "ÖVRIGT"
    bästa_prioritet = 9
    matchade_nyckelord: List[str] = []

    for kategori, regler in KATEGORI_REGLER.items():
        if kategori == "ÖVRIGT":
            continue
        träffar = [kw for kw in regler["nyckelord"] if kw in path_lower]
        if träffar and regler["prioritet"] < bästa_prioritet:
            bästa_kategori = kategori
            bästa_prioritet = regler["prioritet"]
            matchade_nyckelord = träffar

    # Filtyp baserat på extension
    filtyp_map = {
        ".pdf": "PDF",
        ".docx": "WORD",
        ".doc": "WORD",
        ".xlsx": "EXCEL",
        ".xls": "EXCEL",
        ".txt": "TEXT",
        ".md": "MARKDOWN",
        ".wav": "LJUD",
        ".mp3": "LJUD",
        ".m4a": "LJUD",
        ".flac": "LJUD",
        ".ogg": "LJUD",
        ".aac": "LJUD",
        ".mp4": "VIDEO",
        ".mov": "VIDEO",
        ".mkv": "VIDEO",
        ".avi": "VIDEO",
        ".jpg": "BILD",
        ".jpeg": "BILD",
        ".png": "BILD",
        ".json": "JSON",
        ".xml": "XML",
        ".csv": "CSV",
    }
    filtyp = filtyp_map.get(ext, "OKÄND")

    processuell_relevans = KATEGORI_REGLER[bästa_kategori]["processuell_relevans"]

    return BevisPost(
        fil_id=fil_id or f"BEV-{hash(filnamn) % 10000:04d}",
        filnamn=filnamn,
        relativ_sökväg=relativ_sökväg,
        kategori=bästa_kategori,
        prioritet=bästa_prioritet,
        processuell_relevans=processuell_relevans,
        matchade_nyckelord=matchade_nyckelord,
        filtyp=filtyp,
        storlek_bytes=storlek_bytes,
        hash_sha256=hash_sha256,
    )
def kategorisera_mappar(
    root_paths: List[str],
    case_id: str = "",
) -> KategoriseringsRapport:
    """
    Kategoriserar alla filer i angivna mappar.
    Läser ALDRIG filinnehåll.
    """
    poster: List[BevisPost] = []

    for root_path in root_paths:
        if not os.path.exists(root_path):
            continue
        if os.path.isfile(root_path):
            filnamn = os.path.basename(root_path)
            storlek = os.path.getsize(root_path)
            post = kategorisera_fil(
                filnamn=filnamn,
                relativ_sökväg=filnamn,
                fil_id=f"BEV-{len(poster)+1:04d}",
                storlek_bytes=storlek,
            )
            poster.append(post)
        else:
            for dirpath, _, filenames in os.walk(root_path):
                for filename in filenames:
                    full_path = os.path.join(dirpath, filename)
                    rel_path = os.path.relpath(full_path, root_path)
                    try:
                        storlek = os.path.getsize(full_path)
                    except OSError as e:
                        # Reservvärdet är dataklassens standard och styr ingen
                        # gren, men en oläsbar fil går annars inte att skilja
                        # från en tom fil. Felet skrivs därför ut.
                        storlek = 0
                        print(
                            f"[EVIDENCE_CATEGORIZER] storlek kunde inte läsas: "
                            f"{full_path} — {type(e).__name__}: {e}",
                            file=sys.stderr,
                        )
                    post = kategorisera_fil(
                        filnamn=filename,
                        relativ_sökväg=rel_path,
                        fil_id=f"BEV-{len(poster)+1:04d}",
                        storlek_bytes=storlek,
                    )
                    poster.append(post)

    return bygg_rapport(poster, case_id)


def exportera_json(
    rapport: KategoriseringsRapport,
    output_dir: Optional[str] = None,
) -> str:
    """Skriver bevis_kategorisering.json och returnerar utfallet.

    Var tidigare `return None` med docstringen "Stub function for
    compatibility". Ingen kod anropade den. Den riktiga skrivningen låg inne
    i exportera_kategorisering, som nu delegerar hit — en stub vid sidan av
    en fungerande implementation ser ut som ett alternativ och inbjuder till
    att anropas.

    Returnerar "EXPORTED" eller "KAN EJ EXPORTERAS: <skäl>". Skälet ska
    följa med ut, inte sväljas: en kategorisering som inte kunde skrivas är
    en lucka i akten, inte ett tyst icke-utfall.
    """
    try:
        os.makedirs(output_dir, exist_ok=True)
        json_path = os.path.join(output_dir, "bevis_kategorisering.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(rapport.to_dict(), f, ensure_ascii=False, indent=2)
        return "EXPORTED"
    except Exception as e:
        return f"KAN EJ EXPORTERAS: {e}"


def exportera_markdown(
    rapport: KategoriseringsRapport,
    output_dir: Optional[str] = None,
) -> str:
    """Skriver bevis_kategorisering.md och returnerar utfallet."""
    try:
        os.makedirs(output_dir, exist_ok=True)
        md_path = os.path.join(output_dir, "bevis_kategorisering.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(rapport.to_markdown())
        return "EXPORTED"
    except Exception as e:
        return f"KAN EJ EXPORTERAS: {e}"


def exportera_kategorisering(
    rapport: KategoriseringsRapport,
    output_dir: Optional[str] = None,
) -> Dict[str, str]:
    """Exporterar kategoriseringsrapport som JSON och Markdown."""
    return {
        "json": exportera_json(rapport, output_dir),
        "markdown": exportera_markdown(rapport, output_dir),
    }


def bygg_rapport(
    poster: List[BevisPost],
    case_id: str = "",
) -> KategoriseringsRapport:
    """Bygger en KategoriseringsRapport ur redan kategoriserade poster.

    kategorisera_mappar vandrar själv filträdet. Anropare som redan har
    kategoriserat sina filer (pipeline-steget L0_CATEGORIZE) hade ingen väg
    till en rapport och därmed ingen väg till exporten — modulens
    deklarerade output producerades aldrig i en pipelinekörning.
    """
    if not case_id:
        case_id = f"CASE_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    rapport = KategoriseringsRapport(case_id=case_id)
    rapport.poster = list(poster)
    rapport.totalt_filer = len(rapport.poster)

    statistik: Dict[str, int] = {}
    for post in rapport.poster:
        statistik[post.kategori] = statistik.get(post.kategori, 0) + 1
    rapport.kategori_statistik = statistik

    return rapport


# ============================================================
# ENTRYPOINT
# ============================================================

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Evidence Categorizer – SVENSK FORENSIC COURT AUDIT ENGINE v10.3-UPDATED"
    )
    parser.add_argument("paths", nargs="+", help="Sökvägar till ärendemappar")
    parser.add_argument("--output", default=str(Path(__file__).resolve().parent.parent / "output"), help="Outputmapp")
    parser.add_argument("--case-id", default="", help="Case ID")

    args = parser.parse_args()

    rapport = kategorisera_mappar(args.paths, args.case_id)
    results = exportera_kategorisering(rapport, args.output)

    print(f"Kategorisering klar: {rapport.totalt_filer} filer")
    for kategori, antal in sorted(rapport.kategori_statistik.items()):
        print(f"  {kategori}: {antal}")
    print(f"Export: {results}")


def skanna_ärendemapp(
    root_path: str,
    case_id: str = "",
) -> KategoriseringsRapport:
    """Kategoriserar en enskild ärendemapp.

    Var `return None` med docstringen "Stub function for compatibility".
    Ingen kod anropade den, och ett namn som lovar en ärendeskanning men
    returnerar None är farligare än ett saknat namn: en anropare som tror
    sig ha skannat akten får ett tomt utfall som inte skiljer sig från en
    tom akt.

    Delegerar till kategorisera_mappar. Funktionen är enkelmappsformen av
    samma operation, inte en andra implementation av den.
    """
    return kategorisera_mappar([root_path], case_id)


if __name__ == "__main__":
    main()
