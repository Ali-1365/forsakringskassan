"""FAS 5 -- Ekonomisk rekonstruktion och kontroll.

Funktionell rekonstruktion av den historiska källan
fas5_economic_reconstruction.py (+507 rader, refererad i
"Multi-Agent Juridisk Analysmotor (17 sektioner).md") som aldrig
aterfanns som fristaende fil i projekttradet.

Substans (bevarad fraan den historiska specifikationen):
  - Formatmedveten en-gangs-normalisering av belopp (Decimal bevaras
    under beraekning; belopp summeras ALDRIG mellan dokument).
  - Deterministisk insamling av ekonomiska poster (FAS3-register).
  - Kaelsporad datumvaeljare per dokumenttyp; odaterade dokument anvaends
    inte som kronologiska aendpunkter utan flaggas.
  - Skuldkedje-rekonstruktion fraan FAS4 + FAS3 -> FAS5-register.

Publik integrationspunkt: reconstruct_economic_chain() (GAP-E).
"""

from __future__ import annotations

import collections
import datetime
import decimal
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent
FAS3 = ROOT / "FAS3_v4_20260803_korrigerat_extraktionsregister.json"
FAS4 = ROOT / "FAS4_skuldkedjeregister.json"

ECONOMIC_FIELDS = {
    "belopp",
    "kapitalbelopp",
    "ursprungligt_belopp",
    "kravbelopp",
    "saldo",
    "kvarvarande_belopp",
    "ranta",
    "avgift",
    "paminneiseavgift",
    "inkassokostnad",
    "ansokningsavgift",
    "administrationsavgift",
    "aviavgift",
    "betalning",
}
ENDPOINT_FIELDS = (
    "kravbelopp",
    "saldo",
    "kvarvarande_belopp",
    "kapitalbelopp",
    "ursprungligt_belopp",
)
DEFAULT_DATE_PRIORITY = (
    "beslutsdatum",
    "inkassodatum",
    "fakturadatum",
    "betalningsdatum",
    "forfallodatum",
    "datum",
)
DATE_PRIORITY_BY_DOCUMENT_TYPE = {
    "faktura": (
        "fakturadatum", "forfallodatum", "datum", "inkassodatum",
        "beslutsdatum", "betalningsdatum",
    ),
    "paminneise": (
        "fakturadatum", "forfallodatum", "datum", "inkassodatum",
        "beslutsdatum", "betalningsdatum",
    ),
    "inkassokrav": (
        "inkassodatum", "forfallodatum", "datum", "fakturadatum",
        "beslutsdatum", "betalningsdatum",
    ),
    "kfm_beslut": (
        "beslutsdatum", "datum", "inkassodatum", "forfallodatum",
        "fakturadatum", "betalningsdatum",
    ),
    "betalningsplan": (
        "betalningsdatum", "forfallodatum", "datum", "fakturadatum",
        "inkassodatum", "beslutsdatum",
    ),
    "avtal": (
        "datum", "fakturadatum", "betalningsdatum", "forfallodatum",
        "inkassodatum", "beslutsdatum",
    ),
}
def _norm(value: object) -> str:
    """Normaliserar registertext (gemener + diakritiska tecken bort)."""
    s = str(value).strip().lower()
    s = s.replace("\u00e4", "a").replace("\u00e5", "a").replace("\u00f6", "o")
    s = s.replace("\u00e9", "e")
    return s


def amount_to_decimal(value: object) -> decimal.Decimal:
    """Formatmedveten beloppsnormalisering (en gaang, till Decimal)."""
    if isinstance(value, decimal.Decimal):
        number = value
    elif isinstance(value, int):
        number = decimal.Decimal(value)
    else:
        raw = str(value).strip()
        raw = re.sub(r"(?i)\b(?:SEK|KR)\b|:-", "", raw)
        raw = (
            raw.replace("\u00a0", "")
            .replace("\u202f", "")
            .replace(" ", "")
            .replace("'", "")
        )
        if not raw:
            raise decimal.InvalidOperation("Tom beloppsstring")
        sign = ""
        if raw[0] in "+-":
            sign, raw = raw[0], raw[1:]
        if not raw or not re.fullmatch(r"[\d.,]+", raw):
            raise decimal.InvalidOperation(f"Ogiltigt beloppsformat: {value!r}")
        comma = raw.rfind(",")
        point = raw.rfind(".")
        if comma >= 0 and point >= 0:
            dec = "," if comma > point else "."
            grp = "." if dec == "," else ","
            raw = raw.replace(grp, "").replace(dec, ".")
        elif comma >= 0:
            parts = raw.split(",")
            if len(parts) == 2 and len(parts[1]) in {1, 2}:
                raw = f"{parts[0]}.{parts[1]}"
            else:
                raw = "".join(parts)
        elif point >= 0:
            parts = raw.split(".")
            if len(parts) == 2 and len(parts[1]) in {1, 2}:
                raw = f"{parts[0]}.{parts[1]}"
            else:
                raw = "".join(parts)
        number = decimal.Decimal(f"{sign}{raw}")
    if not number.is_finite():
        raise decimal.InvalidOperation("Beloppet aer inte aendligt")
    return number


def decimal_text(value: decimal.Decimal) -> str:
    """Konsistent redovisning med 2 decimaler."""
    return f"{value.quantize(decimal.Decimal('0.01'))} SEK"


def parse_documented_date(value: object) -> datetime.date:
    """Tolkar dokumenterat datum (YYYY-MM-DD eller DD-MM-YYYY och varianter)."""
    parts = re.split(r"[-/.]", str(value))
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"Ogiltigt datumformat: {value!r}")
    if len(parts[0]) == 4:
        year, month, day = map(int, parts)
    else:
        day, month, year = map(int, parts)
    return datetime.date(year, month, day)


def select_event_date(document: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Kaelsporad datumvaeljare enligt dokumenttypens prioritet."""
    parsed_rows = []
    ej_tolkade = []
    for row in document.get("datum", []):
        try:
            parsed_date = parse_documented_date(row.get("vaerde"))
        except (TypeError, ValueError) as e:
            # Raden hoppades tidigare over tyst. Eftersom valet nedan tar
            # tidigaste respektive senaste datum bland kandidaterna kan ett
            # bortfall flytta det valda haendelsedatumet, utan att det syns
            # i den kaelsporning funktionen returnerar.
            ej_tolkade.append({
                "vaerde": row.get("vaerde"),
                "typ": row.get("typ"),
                "sida": row.get("sida"),
                "fel": f"{type(e).__name__}: {e}",
            })
            continue
        parsed_rows.append((parsed_date, row))

    priorities = DATE_PRIORITY_BY_DOCUMENT_TYPE.get(
        _norm(document.get("dokumenttyp")),
        DEFAULT_DATE_PRIORITY,
    )
    for date_type in priorities:
        candidates = [
            (parsed_date, row)
            for parsed_date, row in parsed_rows
            if _norm(row.get("typ")) == date_type
        ]
        if not candidates:
            continue
        selected_date, selected_row = (
            max(candidates, key=lambda item: item[0])
            if date_type == "datum"
            else min(candidates, key=lambda item: item[0])
        )
        return {
            "vaerde": selected_date.isoformat(),
            "datumtyp": date_type,
            "sida": selected_row.get("sida"),
            "textutdrag": selected_row.get("textutdrag"),
            "metod": selected_row.get("metod"),
            "ej_tolkade_datumrader": ej_tolkade,
            "urvalsregel": (
                "Senaste dokumenterade generiska datum som fallback."
                if date_type == "datum"
                else "Tidigaste dokumenterade datum av prioriterad handelsetyp."
            ),
        }
    return None


def event_sort_key(summary: Dict[str, Any]) -> tuple:
    event = summary.get("handelsedatum")
    if event:
        return (0, datetime.date.fromisoformat(event["vaerde"]), summary["dok_id"])
    return (1, datetime.date.max, summary["dok_id"])


def collect_economic_rows(
    fas3: Dict[str, Any],
    chain_by_doc: Dict[str, str],
) -> collections.defaultdict:
    """Samlar ekonomiska poster fraan FAS3 och grupperar per kedja/dokument."""
    rows_by_chain_doc = collections.defaultdict(lambda: collections.defaultdict(list))
    for document in fas3.get("dokument", []):
        dok_id = document.get("dok_id")
        chain_id = chain_by_doc.get(dok_id)
        if not chain_id:
            continue
        for group in ("datum", "referenser", "belopp"):
            for index, post in enumerate(document.get(group, []), 1):
                field = post.get("typ", group)
                if _norm(field) not in ECONOMIC_FIELDS:
                    continue
                row = {
                    **post,
                    "dok_id": dok_id,
                    "filnamn": document.get("filnamn"),
                    "faltnamn": _norm(field),
                    "extraktion_id": (
                        post.get("extraktion_id")
                        or post.get("id")
                        or f"FAS3-{dok_id}-{group}-{index:05d}"
                    ),
                }
                rows_by_chain_doc[chain_id][dok_id].append(row)
    return rows_by_chain_doc


def _summarize_document_fields(grouped: Dict[str, List[Dict]]) -> Dict[str, Any]:
    """Hoegsta klassificerade vaerde per faelttyp; summeras inte mellan poster."""
    fields = {}
    for field, values in grouped.items():
        parsed = []
        ej_tolkade = []
        for row in values:
            try:
                parsed.append((amount_to_decimal(row.get("vaerde")), row))
            except decimal.InvalidOperation as e:
                # Posten hoppades tidigare over tyst. Samtidigt rapporterades
                # antal_poster som len(values), det vill saga samtliga rader,
                # medan hogsta_varde var maximum over enbart de tolkbara. En
                # faeltsammanstaellning kunde daermed saega "5 poster, hogsta
                # vaerde X" naer tva av de fem aldrig oevervaegts, och det
                # hogsta vaerdet kan ha legat i en av dem.
                ej_tolkade.append({
                    "vaerde": row.get("vaerde"),
                    "sida": row.get("sida"),
                    "fel": f"{type(e).__name__}: {e}",
                })
                continue
        if not parsed:
            continue
        intern = max(parsed, key=lambda item: item[0])
        fields[field] = {
            "antal_poster": len(values),
            "antal_tolkade": len(parsed),
            "ej_tolkade": ej_tolkade,
            "hogsta_varde": decimal_text(intern[0]),
            "normaliserat_decimalvarde": str(intern[0]),
            "kalla": intern[1],
        }
    return fields


def build_reconstructions(
    fas3: Dict[str, Any],
    fas4: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Bygger fullstaendig skuldkedje-rekonstruktion (FAS3 + FAS4)."""
    fas3_by_doc = {
        document["dok_id"]: document
        for document in fas3.get("dokument", [])
        if document.get("dok_id")
    }
    chain_by_doc = {}
    for chain in fas4.get("skuldkedjor", []):
        for document in chain.get("dokument", []):
            chain_by_doc[document["dok_id"]] = chain["kedja_id"]

    rows_by_chain_doc = collect_economic_rows(fas3, chain_by_doc)
    reconstructions = []
    for chain in fas4.get("skuldkedjor", []):
        chain_id = chain["kedja_id"]
        document_summaries = []
        for chain_document in chain.get("dokument", []):
            doc_id = chain_document["dok_id"]
            source_document = fas3_by_doc.get(doc_id, {})
            grouped = collections.defaultdict(list)
            for row in rows_by_chain_doc[chain_id].get(doc_id, []):
                grouped[row["faltnamn"]].append(row)

            document_summaries.append(
                {
                    "dok_id": doc_id,
                    "relativ_sokvag": chain_document.get("relativ_sokvag"),
                    "dokumenttyp": source_document.get("dokumenttyp"),
                    "handelsedatum": select_event_date(source_document),
                    "ekonomiska_falt": _summarize_document_fields(grouped),
                }
            )

        document_summaries.sort(key=event_sort_key)
        candidates = []
        for summary in document_summaries:
            event = summary.get("handelsedatum")
            if not event:
                continue
            for priority, field in enumerate(ENDPOINT_FIELDS):
                economic_field = summary["ekonomiska_falt"].get(field)
                if economic_field:
                    candidates.append(
                        {
                            "dok_id": summary["dok_id"],
                            "prioritet": priority,
                            "falttyp": field,
                            "varde": decimal.Decimal(
                                economic_field["normaliserat_decimalvarde"]
                            ),
                            "sammanfattning": summary,
                            "handelsedatum": event,
                        }
                    )
                    break

        candidates.sort(
            key=lambda item: (
                datetime.date.fromisoformat(item["handelsedatum"]["vaerde"]),
                item["prioritet"],
                item["dok_id"],
            )
        )
        original = candidates[0] if candidates else None
        current = candidates[-1] if candidates else None
        difference = (
            current["varde"] - original["varde"]
            if original and current
            else None
        )
        payment_candidates = [
            {
                "dok_id": summary["dok_id"],
                "handelsedatum": summary["handelsedatum"],
                **summary["ekonomiska_falt"]["betalning"],
            }
            for summary in document_summaries
            if "betalning" in summary["ekonomiska_falt"]
        ]

        flags = []
        if not candidates:
            flags.append(
                "INGA DATERADE KLASSIFICERADE KAPITAL-, KRAV- ELLER SALDOBELOPP"
            )
        if payment_candidates:
            flags.append("BETALNINGSKANDIDATER EJ AUTOMATISKT AVRANKNADE")
        undated_documents = [
            summary["dok_id"]
            for summary in document_summaries
            if not summary["handelsedatum"]
        ]
        if undated_documents:
            flags.append(
                "HANDELSEDATUM SAKNAS; ODATERADE DOKUMENT HAR INTE ANVANTS "
                "SOM KRONOLOGISKA ANDPUNKTER: " + ", ".join(undated_documents)
            )
        generic_date_documents = [
            summary["dok_id"]
            for summary in document_summaries
            if summary.get("handelsedatum", {}).get("datumtyp") == "datum"
        ]
        if generic_date_documents:
            flags.append(
                "GENERISKT DOKUMENTERAT DATUM HAR ANVANTS SOM FALLBACK: "
                + ", ".join(generic_date_documents)
            )

        reconstructions.append(
            {
                "kedja_id": chain_id,
                "status": "PRELIMINAR EKONOMISK REKONSTRUKTION MED FLAGGOR",
                "ordningsprincip": (
                    "Dokument sorteras efter valt dokumenterat handelsedatum. "
                    "DOK-ID anvands endast som stabil tie-breaker."
                ),
                "ursprunglig_beloppspunkt": (
                    {
                        "dok_id": original["dok_id"],
                        "handelsedatum": original["handelsedatum"],
                        "falttyp": original["falttyp"],
                        "belopp": decimal_text(original["varde"]),
                        "kalla": original["sammanfattning"]["ekonomiska_falt"][
                            original["falttyp"]
                        ],
                    }
                    if original
                    else None
                ),
                "senaste_beloppspunkt": (
                    {
                        "dok_id": current["dok_id"],
                        "handelsedatum": current["handelsedatum"],
                        "falttyp": current["falttyp"],
                        "belopp": decimal_text(current["varde"]),
                        "kalla": current["sammanfattning"]["ekonomiska_falt"][
                            current["falttyp"]
                        ],
                    }
                    if current
                    else None
                ),
                "beraknad_differens": (
                    {
                        "varde": decimal_text(difference),
                        "formel": (
                            "senaste kronologiska dokumenterade beloppspunkt "
                            "- ursprunglig kronologiska dokumenterade "
                            "beloppspunkt"
                        ),
                    }
                    if difference is not None
                    else None
                ),
                "betalningskandidater": payment_candidates,
                "dokumentvisa_kontrollpunkter": document_summaries,
                "flaggor": flags,
            }
        )
    return reconstructions


def _load_register(path: Path):
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def reconstruct_economic_chain(fas3=None, fas4=None) -> dict:
    """GAP-E: publik integrationspunkt foer ekonomisk rekonstruktion.

    Utfoerer skuldkedje-rekonstruktion fraan FAS3/FAS4-register. Om
    registren saknas returneras en aerlig status (REGISTER_SAKNAS) —
    inga belopp fabriceras eller summeras.
    """
    if fas3 is None:
        fas3 = _load_register(FAS3)
    if fas4 is None:
        fas4 = _load_register(FAS4)
    created = datetime.datetime.now().isoformat(sep=" ", timespec="seconds")

    if fas3 is None or fas4 is None:
        missing = []
        if fas3 is None:
            missing.append(str(FAS3))
        if fas4 is None:
            missing.append(str(FAS4))
        return {
            "fas": "FAS 5 - Ekonomisk rekonstruktion och kontroll",
            "status": "REGISTER_SAKNAS",
            "skapad": created,
            "kallor_som_saknas": missing,
            "antal_rekonstruktioner": 0,
            "rekonstruktioner": [],
            "flaggor": [
                "FAS3/FAS4-extraktionsregister saknas fysiskt - inga "
                "belopp har summerats eller fabricerats."
            ],
        }

    reconstructions = build_reconstructions(fas3, fas4)
    return {
        "fas": "FAS 5 - Ekonomisk rekonstruktion och kontroll",
        "status": "PRELIMINAR EKONOMISK REKONSTRUKTION",
        "analysrot": str(ROOT),
        "skapad": created,
        "kallor": [str(FAS3), str(FAS4)],
        "berakningsprincip": (
            "Belopp normaliseras en gang och bevaras som Decimal under "
            "berakningen. Klassificerade belopp summeras inte mellan "
            "dokument. Hoegsta klassificerade vaerde per falttyp valjs. "
            "Handelseordningen bygger pa dokumenterade datum; DOK-ID anvands "
            "endast som tie-breaker. Odaterade dokument anvaands inte som "
            "kronologiska andpunkter. Betalningskandidater raknas inte av "
            "utan separat verifierad betalningskoppling."
        ),
        "antal_rekonstruktioner": len(reconstructions),
        "rekonstruktioner": reconstructions,
    }


def main() -> None:
    payload = reconstruct_economic_chain()
    out_json = ROOT / "FAS5_ekonomiskt_rekonstruktionsregister.json"
    out_md = ROOT / "FAS5_ekonomisk_rekonstruktionsrapport.md"
    out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with out_md.open("w", encoding="utf-8") as handle:
        handle.write("# FAS 5 - Ekonomisk rekonstruktion och kontroll\n\n")
        handle.write(f"Skapad: {payload['skapad']}\n\n")
        handle.write(f"- Rekonstruktioner: {payload['antal_rekonstruktioner']}\n\n")
        if payload.get("status") == "REGISTER_SAKNAS":
            handle.write("Register saknas - ingen rekonstruktion utfoerd.\n")
        for row in payload["rekonstruktioner"]:
            handle.write(f"## {row['kedja_id']}\n")
            handle.write(f"- Status: {row['status']}\n")
            handle.write(f"- Ursprunglig: {row['ursprunglig_beloppspunkt']}\n")
            handle.write(f"- Senaste: {row['senaste_beloppspunkt']}\n")
            handle.write(f"- Differens: {row['beraknad_differens']}\n")


if __name__ == "__main__":
    main()