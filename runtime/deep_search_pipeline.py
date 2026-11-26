from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


_PNR_RE = re.compile(r"\b(?:19|20)?\d{6}[-+]?\d{4}\b")


@dataclass(frozen=True)
class SearchQuerySpec:
    query_id: str
    title: str
    query: str
    category: str = "rättskälla"
    required: bool = True


@dataclass(frozen=True)
class LegalSourceRecord:
    query_id: str
    source_id: str
    title: str
    url: str = ""
    doc_id: str = ""
    snippet: str = ""
    source_type: str = "okänd"
    verified: bool = False


@dataclass
class SubAgentResult:
    query_id: str
    query: str
    records: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_legal_source_records(self) -> list[LegalSourceRecord]:
        """Konverterar råa sökträffar till verifierade rättskälleposter."""
        out: list[LegalSourceRecord] = []
        for idx, raw in enumerate(self.records, start=1):
            if not isinstance(raw, dict):
                continue
            url = str(raw.get("url") or "").strip()
            title = str(raw.get("title") or "").strip()
            doc_id = str(raw.get("doc_id") or "").strip()
            snippet = str(raw.get("snippet") or "").strip()
            source_type = str(raw.get("source_type") or "okänd").strip()
            allowed, _ = SourceClassifier.classify_and_check(url=url, title=title, source_type=source_type)
            if not allowed:
                continue
            source_id = str(raw.get("source_id") or f"{self.query_id}_{idx:02d}").strip()
            out.append(
                LegalSourceRecord(
                    query_id=self.query_id,
                    source_id=source_id,
                    title=title or source_id,
                    url=url,
                    doc_id=doc_id,
                    snippet=snippet,
                    source_type=source_type,
                    verified=bool(url or doc_id),
                )
            )
        return out


class SourceClassifier:
    """Klassificerar och spärrar källor som inte utgör auktoritativa rättskällor."""

    BLOCKED_DOMAINS = (
        "reddit.com",
        "flashback.org",
        "familjeliv.se",
        "tiktok.com",
        "instagram.com",
        "facebook.com",
        "youtube.com",
        "wikipedia.org",
    )

    ALLOWED_MARKERS = (
        "riksdagen.se",
        "regeringen.se",
        "domstol.se",
        "hogstaforvaltningsdomstolen.se",
        "forsakringskassan.se",
        "jo.se",
        "jk.se",
        "lagrummet.se",
        "sfs",
        "prop.",
        "hfd",
        "rkf",
        "vled",
    )

    @classmethod
    def classify_and_check(
        cls,
        *,
        url: str = "",
        title: str = "",
        source_type: str = "",
    ) -> tuple[bool, str]:
        haystack = f"{url} {title} {source_type}".lower()
        for blocked in cls.BLOCKED_DOMAINS:
            if blocked in haystack:
                return False, f"BLOCKERAD_KÄLLA:{blocked}"
        if any(marker in haystack for marker in cls.ALLOWED_MARKERS):
            return True, "GODKÄND_RÄTTSKÄLLA"
        return False, "EJ_VERIFIERAD_RÄTTSKÄLLA"


def validera_sokterm(term: str) -> tuple[bool, str]:
    """Blockerar personnummer och direkt identifierande personuppgifter i externa söktermer."""
    cleaned = (term or "").strip()
    if not cleaned:
        return False, "TOM_SÖKTERM"
    if _PNR_RE.search(cleaned):
        return False, "PERSONNUMMER_BLOCKERAT"
    return True, "OK"


def blockera_ej_rättskälla(url: str = "", title: str = "", source_type: str = "") -> tuple[bool, str]:
    allowed, reason = SourceClassifier.classify_and_check(
        url=url,
        title=title,
        source_type=source_type,
    )
    return (not allowed), reason


SEARCH_SPECS: list[SearchQuerySpec] = [
    SearchQuerySpec("SEARCH_01", "Tillämplig lagtext och SFS", "socialförsäkringsbalken SFB tillämplig lagtext"),
    SearchQuerySpec("SEARCH_02", "Förarbeten och propositioner", "proposition socialförsäkring förarbeten"),
    SearchQuerySpec("SEARCH_03", "Högsta förvaltningsdomstolens praxis", "HFD avgörande socialförsäkring praxis"),
    SearchQuerySpec("SEARCH_04", "Kammarrättspraxis", "kammarrätten dom socialförsäkring"),
    SearchQuerySpec("SEARCH_05", "Förvaltningsrättslig praxis", "förvaltningsrätten dom socialförsäkring"),
    SearchQuerySpec("SEARCH_06", "Försäkringskassans vägledningar", "Försäkringskassan vägledning rättsligt ställningstagande"),
    SearchQuerySpec("SEARCH_07", "JO och JK beslut", "JO beslut Försäkringskassan förvaltningslagen"),
    SearchQuerySpec("SEARCH_08", "Förvaltningslagen och processregler", "förvaltningslagen förvaltningsprocesslagen utredningsskyldighet"),
    SearchQuerySpec("SEARCH_09", "Bevisbörda och beviskrav", "beviskrav sannolikt göras antagligt socialförsäkring"),
    SearchQuerySpec("SEARCH_10", "EU-rätt och internationella åtaganden", "EU rätt social trygghet samordning"),
]


def build_search_plan(extra_terms: list[str] | None = None) -> list[SearchQuerySpec]:
    plan = list(SEARCH_SPECS)
    for idx, term in enumerate(extra_terms or [], start=1):
        ok, _ = validera_sokterm(term)
        if ok:
            plan.append(
                SearchQuerySpec(
                    query_id=f"SEARCH_CUSTOM_{idx:02d}",
                    title=f"Anpassad sökfråga {idx}",
                    query=term.strip(),
                    category="anpassad",
                    required=False,
                )
            )
    return plan