# -*- coding: utf-8 -*-
"""
Aktgranskning: inventering, klassificering och luckanalys av mappstruktur.

Producerar: klassificerad fillista, lucklista, rensningsförslag, rekvisit-täckning.
Producerar INTE: bevisvärdering, domslut, automatisk radering.
Alla förslag är INDIKATIVA_ENDAST.
"""
from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "runtime", ROOT / "integrations", ROOT / "scripts", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _load(name: str, rel: str) -> Optional[Any]:
    path = ROOT / rel
    if not path.is_file():
        return None
    try:
        from module_loader import ladda_modul
        return ladda_modul(name, path)
    except Exception:
        return None


@dataclass
class FilPost:
    sökväg: str
    filnamn: str
    extension: str
    storlek_bytes: int
    sha256: str
    text: str = ""
    kategori: str = "EJ_KLASSIFICERAD"
    klassificerings_grund: str = ""
    källhygien: Dict[str, Any] = field(default_factory=dict)
    är_dubblett_av: str = ""
    rensningsförslag: bool = False
    rensnings_skäl: str = ""


@dataclass
class LuckPost:
    referens_i_text: str
    hittad_i_fil: str
    saknas_som_bilaga: bool = True
    förslag: str = "Kontrollera om dokumentet ska åberopas som bevis"


@dataclass
class AktgranskningRapport:
    tidpunkt: str = ""
    root_dirs: List[str] = field(default_factory=list)
    antal_filer_totalt: int = 0
    filer: List[FilPost] = field(default_factory=list)
    luckor: List[LuckPost] = field(default_factory=list)
    rensningsförslag: List[FilPost] = field(default_factory=list)
    rekvisit_täckning: Dict[str, List[str]] = field(default_factory=dict)
    rekvisit_luckor: List[str] = field(default_factory=list)
    varningar: List[str] = field(default_factory=list)
    not_: str = (
        "INDIKATIV_ENDAST. Alla förslag kräver juristbeslut. "
        "Ingen fil raderas eller utesluts automatiskt."
    )


_STÖDDA_TEXTFORMAT = {".txt", ".md", ".csv", ".json", ".xml", ".html", ".htm"}
_STÖDDA_DOKUMENTFORMAT = {".pdf", ".docx", ".doc", ".odt", ".rtf"}
_STÖDDA_BILDFORMAT = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"}
_ADMINISTRATIVA_MÖNSTER = [
    "kvitto", "faktura", "porto", "frakt", "betalning",
    "orderbekräftelse", "newsletter", "reklam",
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return "FEL_VID_HASH"


def _är_administrativ(text: str) -> Tuple[bool, str]:
    text_norm = text.lower()
    for mönster in _ADMINISTRATIVA_MÖNSTER:
        if mönster in text_norm:
            return True, f"Administrativt mönster: '{mönster}'"
    return False, ""


def _extrahera_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in _STÖDDA_TEXTFORMAT:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""
    # Best-effort: try read as text for small files; OCR/extractor optional later
    if path.stat().st_size < 500_000 and ext in {".pdf", ".docx"}:
        try:
            raw = path.read_bytes()
            # very weak extract of printable sequences
            text = "".join(chr(b) if 32 <= b < 127 else " " for b in raw[:50000])
            return " ".join(text.split())
        except Exception:
            return ""
    return ""


def _inventera_mappar(root_dirs: List[str]) -> List[Path]:
    alla = []
    för_kända = _STÖDDA_TEXTFORMAT | _STÖDDA_DOKUMENTFORMAT | _STÖDDA_BILDFORMAT
    for rd in root_dirs:
        p = Path(rd)
        if not p.exists():
            continue
        for f in p.rglob("*"):
            if f.is_file() and f.suffix.lower() in för_kända:
                alla.append(f)
    return alla


def _hitta_luckor(filer: List[FilPost]) -> List[LuckPost]:
    luckor = []
    alla_filnamn = {Path(f.sökväg).stem.lower() for f in filer}
    referensmönster = [
        r"bilaga\s+\w+",
        r"avtal\s+(?:av|från|daterat)\s+[\d\-]+",
        r"mejl\s+(?:av|från)\s+[\d\-]+",
        r"protokoll\s+(?:av|från)\s+[\d\-]+",
        r"intyg\s+(?:av|från|daterat)\s+[\w\-]+",
        r"beslut\s+(?:av|från|daterat|dnr)\s+[\w\-]+",
        r"yttrande\s+(?:av|från)\s+[\w\-]+",
    ]
    seen = set()
    for fil in filer:
        if not fil.text:
            continue
        for mönster in referensmönster:
            for träff in re.finditer(mönster, fil.text, re.IGNORECASE):
                ref = träff.group(0).strip()
                key = ref.lower()
                if key in seen:
                    continue
                ref_norm = ref.lower().replace(" ", "_")
                finns = any(ref_norm in fn or fn in ref_norm for fn in alla_filnamn)
                if not finns:
                    seen.add(key)
                    luckor.append(LuckPost(
                        referens_i_text=ref,
                        hittad_i_fil=fil.filnamn,
                        saknas_som_bilaga=True,
                    ))
    return luckor


def _enkel_rekvisit_täckning(all_text: str, rekvisit: List[str]) -> Tuple[Dict[str, List[str]], List[str]]:
    """Enkel substring-täckning — indikativ, inte subsumtion."""
    text_norm = all_text.lower()
    täckta: Dict[str, List[str]] = {}
    otäckta: List[str] = []
    for r in rekvisit:
        if r.lower() in text_norm:
            täckta[r] = ["TEXT_TRÄFF"]
        else:
            otäckta.append(r)
    return täckta, otäckta


def _relativ_sökväg(path: Path, root_dirs: List[str]) -> str:
    """Sökväg relativt den root_dir som innehåller filen (steg 28)."""
    for r in root_dirs:
        try:
            return str(Path(path).resolve().relative_to(Path(r).resolve()))
        except ValueError:
            continue
    return Path(path).name


def run_aktgranskning(
    root_dirs: List[str],
    case_context: Optional[Dict] = None,
    rekvisit: Optional[List[str]] = None,
    bilageförteckning: Optional[List[str]] = None,
) -> AktgranskningRapport:
    rapport = AktgranskningRapport(
        tidpunkt=datetime.now(timezone.utc).isoformat() + "Z",
        root_dirs=list(root_dirs or []),
    )

    categorizer_mod = _load("evidence_categorizer", "runtime/evidence_categorizer.py")
    hygiene_mod = _load("source_hygiene", "integrations/source_hygiene.py")

    alla_filer = _inventera_mappar(root_dirs or [])
    rapport.antal_filer_totalt = len(alla_filer)

    if not alla_filer:
        rapport.varningar.append("Inga filer hittades i angivna mappar.")
        if bilageförteckning:
            for bilaga in bilageförteckning:
                b = (bilaga or "").strip()
                if b:
                    rapport.luckor.append(LuckPost(
                        referens_i_text=b,
                        hittad_i_fil="BILAGEFÖRTECKNING",
                        saknas_som_bilaga=True,
                        förslag="Åberopad bilaga saknas som fil i root_dirs",
                    ))
        return rapport

    hash_register: Dict[str, str] = {}

    for path in alla_filer:
        sha = _sha256(path)
        text = _extrahera_text(path)
        post = FilPost(
            sökväg=str(path),
            filnamn=path.name,
            extension=path.suffix.lower(),
            storlek_bytes=path.stat().st_size,
            sha256=sha,
            text=text,
        )

        if sha != "FEL_VID_HASH" and sha in hash_register:
            post.kategori = "D_DUBBLETT"
            post.är_dubblett_av = hash_register[sha]
            post.rensningsförslag = True
            post.rensnings_skäl = f"Identisk fil: {hash_register[sha]}"
        else:
            if sha != "FEL_VID_HASH":
                hash_register[sha] = str(path)

            if categorizer_mod:
                fn = getattr(categorizer_mod, "kategorisera_fil", None)
                if fn:
                    try:
                        # Steg 28: kategorisera_fil kräver relativ_sökväg.
                        kat_result = fn(path.name, _relativ_sökväg(path, root_dirs or []),
                                        storlek_bytes=post.storlek_bytes, hash_sha256=sha)
                        if not isinstance(kat_result, (dict, str)) and hasattr(kat_result, "kategori"):
                            kat_result = {"kategori": kat_result.kategori,
                                          "grund": ", ".join(getattr(kat_result, "matchade_nyckelord", []) or [])}
                        if isinstance(kat_result, dict):
                            post.kategori = str(
                                kat_result.get("kategori")
                                or kat_result.get("category")
                                or post.kategori
                            )
                            post.klassificerings_grund = str(
                                kat_result.get("grund") or kat_result.get("reason") or ""
                            )
                        elif isinstance(kat_result, str):
                            post.kategori = kat_result
                    except Exception as e:
                        rapport.varningar.append(f"Klassificeringsfel för {path.name}: {type(e).__name__}")

            if post.kategori not in ("D_DUBBLETT",) and text:
                admin, skäl = _är_administrativ(text)
                if admin:
                    post.rensningsförslag = True
                    post.rensnings_skäl = skäl
                    if post.kategori == "EJ_KLASSIFICERAD":
                        post.kategori = "E_IRRELEVANT"

        rapport.filer.append(post)

    if hygiene_mod and hasattr(hygiene_mod, "assess"):
        try:
            hygiene = hygiene_mod.assess([
                {"file_id": str(i), "path": f.sökväg, "name": f.filnamn}
                for i, f in enumerate(rapport.filer, 1)
            ])
            trust_by_file = {
                post["filename"]: post
                for post in hygiene.get("klassificering", [])
            }
            for fil in rapport.filer:
                source = trust_by_file.get(fil.filnamn)
                if source:
                    fil.källhygien = source
            rapport.varningar.extend(
                f"Källhygien: manuell granskning krävs för {post['filename']}"
                for post in hygiene.get("manual_review_flaggade", [])
            )
        except Exception as e:
            rapport.varningar.append(f"Källhygien-fel: {type(e).__name__}")

    rapport.luckor = _hitta_luckor(rapport.filer)

    if rekvisit:
        all_text = " ".join(f.text for f in rapport.filer if f.text)
        all_text += " " + " ".join(f.filnamn for f in rapport.filer)
        täckta, otäckta = _enkel_rekvisit_täckning(all_text, rekvisit)
        rapport.rekvisit_täckning = täckta
        rapport.rekvisit_luckor = otäckta


    # Explicit bilageförteckning → saknade bilagor
    if bilageförteckning:
        filnamn_l = {f.filnamn.lower() for f in rapport.filer}
        stem_l = {Path(f.sökväg).stem.lower() for f in rapport.filer if len(Path(f.sökväg).stem) >= 3}
        for bilaga in bilageförteckning:
            b = (bilaga or "").strip()
            if not b:
                continue
            bn = b.lower()
            # Kräv meningsfull match: hela nyckelord (min 4 tecken) ur bilaganamnet
            tokens = [tok for tok in re.split(r"[^\wåäöÅÄÖ]+", bn) if len(tok) >= 4]
            tokens = [tok for tok in tokens if tok not in ("bilaga", "appendix", "aktbilaga")]
            finns = False
            for fn in filnamn_l:
                if any(tok in fn for tok in tokens) or (len(bn) >= 8 and (bn in fn or fn in bn)):
                    finns = True
                    break
            if not finns:
                for st in stem_l:
                    if any(tok in st for tok in tokens) or (len(bn) >= 8 and (bn in st or st in bn)):
                        finns = True
                        break
            if not tokens:
                # ingen meningsfull token — behandla som saknad om exact filnamn saknas
                finns = any(bn == fn or bn == st for fn, st in zip(filnamn_l, stem_l))
            if not finns:
                rapport.luckor.append(LuckPost(
                    referens_i_text=b,
                    hittad_i_fil="BILAGEFÖRTECKNING",
                    saknas_som_bilaga=True,
                    förslag="Åberopad bilaga saknas som fil i root_dirs",
                ))

    rapport.rensningsförslag = [f for f in rapport.filer if f.rensningsförslag]
    return rapport


def run_aktgranskning_if_requested(
    root_dirs: List[str],
    requested: bool = False,
    case_context: Optional[Dict] = None,
    rekvisit: Optional[List[str]] = None,
    bilageförteckning: Optional[List[str]] = None,
) -> Dict:
    if not requested:
        return {
            "status": "EJ_BEGÄRD",
            "detail": "Aktgranskning kräver explicit requested=True.",
        }
    if not root_dirs:
        return {
            "status": "EJ_KÖRBAR",
            "skäl": "Inga mappar angivna.",
        }
    try:
        rapport = run_aktgranskning(root_dirs, case_context, rekvisit, bilageförteckning)
        return {
            "status": "GENOMFÖRD",
            "rapport": asdict(rapport),
            "sammanfattning": {
                "totalt": rapport.antal_filer_totalt,
                "dubbletter": sum(1 for f in rapport.filer if f.kategori == "D_DUBBLETT"),
                "rensningsförslag": len(rapport.rensningsförslag),
                "luckor": len(rapport.luckor),
                "rekvisit_otäckta": len(rapport.rekvisit_luckor),
                "varningar": len(rapport.varningar),
            },
        }
    except Exception as e:
        return {
            "status": "HARD_STOP",
            "kod": "HS_AKTGRANSKNING_ERROR",
            "detail": f"{type(e).__name__}: {e}",
        }


if __name__ == "__main__":
    import tempfile
    td = Path(tempfile.mkdtemp())
    (td / "beslut.txt").write_text("Socialnämndens beslut. Se bilaga A och intyg från 2024-01-15.")
    (td / "kopia_beslut.txt").write_text("Socialnämndens beslut. Se bilaga A och intyg från 2024-01-15.")
    (td / "faktura_porto.txt").write_text("Faktura porto frakt betalning orderbekräftelse")
    r = run_aktgranskning_if_requested(
        [str(td)],
        requested=True,
        rekvisit=["påtaglig risk", "utredningsskyldighet", "Socialnämndens beslut"],
    )
    print(r["status"], r.get("sammanfattning"))

def run_aktgranskning_per_submapp(
    bas_mapp: str,
    requested: bool = False,
    rekvisit: Optional[List[str]] = None,
) -> Dict:
    """
    Kör aktgranskning per undermapp (1 nivå).
    Migrerad logik från fk_auto_analyze_all_folders.
    Kräver explicit requested=True. Producerar aldrig domslut.
    """
    if not requested:
        return {
            "status": "EJ_BEGÄRD",
            "detail": "Undermappsanalys kräver explicit requested=True.",
        }
    from pathlib import Path as P
    bas = P(bas_mapp)
    if not bas.exists():
        return {"status": "EJ_KÖRBAR", "skäl": f"Mapp saknas: {bas_mapp}"}
    undermappar = sorted([
        d for d in bas.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    ])
    if not undermappar:
        return {"status": "EJ_KÖRBAR", "skäl": "Inga undermappar hittades."}
    per_mapp = {}
    for mapp in undermappar:
        filer = [f for f in mapp.rglob("*") if f.is_file()]
        if not filer:
            per_mapp[mapp.name] = {"status": "TOM_MAPP", "antal_filer": 0}
            continue
        rapport = run_aktgranskning_if_requested(
            root_dirs=[str(mapp)],
            requested=True,
            rekvisit=rekvisit,
        )
        per_mapp[mapp.name] = {
            "status": rapport.get("status"),
            "sammanfattning": rapport.get("sammanfattning", {}),
        }
    return {
        "status": "GENOMFÖRD",
        "bas_mapp": bas_mapp,
        "antal_mappar": len(undermappar),
        "per_mapp": per_mapp,
        "not": "INDIKATIV_ENDAST — juristen bedömer varje mapps relevans",
    }

