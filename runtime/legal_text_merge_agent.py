from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Iterable, List, Sequence

WORDING_CHANGE_POLICY = "FORBIDDEN"
INFERENCE_POLICY = "ZERO_INFERENCE"
STATUS_CONSOLIDATED = "CONSOLIDATED_WITHOUT_SUBSTANTIVE_INTERPRETATION"
STATUS_CONFLICT = "CONFLICT_REQUIRES_HUMAN_DECISION"
FLAG_MANUAL_CHOICE = "[KONFLIKT — MANUELLT VAL KRÄVS]"
FLAG_CLAIM = "[KONFLIKT — YRKANDE]"

CLAIM_PATTERN = re.compile(
    r"\b(yrkar|yrkande|medger|bestrider|avslår|bifaller|fordrar|kräver)\b",
    re.IGNORECASE,
)

CONFLICT_SIGNAL_PATTERN = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d+\s*(?:kr|kronor|sek|eur|%|dagar|månader|år)|\d+\s*kap\.|\d+\s*§|SFS\s*\d{4}:\d+)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DraftBlock:
    source: str
    heading: str
    text: str

    @property
    def exact_digest(self) -> str:
        payload = f"{self.heading}\n{self.text}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass
class MergeResult:
    merged_text: str
    merge_status: str
    show_source_tags: bool
    preserved_unique_count: int
    deduplicated_count: int
    conflict_count: int
    blocks_by_heading: dict[str, List[str]] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "wording_change": WORDING_CHANGE_POLICY,
                "inference_policy": INFERENCE_POLICY,
                "merge_status": self.merge_status,
                "show_source_tags": self.show_source_tags,
                "preserved_unique_count": self.preserved_unique_count,
                "deduplicated_count": self.deduplicated_count,
                "conflict_count": self.conflict_count,
                "merged_text": self.merged_text,
            },
            ensure_ascii=False,
            indent=2,
        )


def parse_markdown_blocks(source_name: str, raw_text: str) -> List[DraftBlock]:
    if not raw_text:
        return []

    lines = raw_text.splitlines(keepends=True)
    current_heading = "EJ ANGIVEN"
    current_lines: List[str] = []
    blocks: List[DraftBlock] = []

    def flush_paragraph() -> None:
        chunk = "".join(current_lines).strip("\r\n")
        current_lines.clear()
        if chunk.strip():
            blocks.append(DraftBlock(source=source_name, heading=current_heading, text=chunk))

    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("#"):
            flush_paragraph()
            current_heading = stripped.lstrip("#").strip() or "EJ ANGIVEN"
        elif line.strip() == "":
            flush_paragraph()
        else:
            current_lines.append(line)

    flush_paragraph()
    return blocks


def _conflict_flag_for(left: DraftBlock, right: DraftBlock) -> str:
    combined = f"{left.text} {right.text}"
    if CLAIM_PATTERN.search(combined):
        return FLAG_CLAIM
    return FLAG_MANUAL_CHOICE


def _shares_conflict_anchor(left: DraftBlock, right: DraftBlock) -> bool:
    if left.text == right.text:
        return False
    left_anchors = set(m.group(0).lower() for m in CONFLICT_SIGNAL_PATTERN.finditer(left.text))
    right_anchors = set(m.group(0).lower() for m in CONFLICT_SIGNAL_PATTERN.finditer(right.text))
    if left_anchors and right_anchors and left_anchors != right_anchors:
        return True
    if CLAIM_PATTERN.search(left.text) and CLAIM_PATTERN.search(right.text):
        return True
    return False


def _format_source_tag(sources: Sequence[str], show_source_tags: bool) -> str:
    if not show_source_tags or not sources:
        return ""
    unique_sources = list(dict.fromkeys(sources))
    return f"[{'+'.join(unique_sources)}] "


def merge_legal_drafts(
    drafts: Sequence[tuple[str, str]],
    show_source_tags: bool = False,
) -> MergeResult:
    seen_exact_digests: set[str] = set()
    heading_order: List[str] = []
    grouped_blocks: dict[str, List[DraftBlock]] = {}
    sources_by_digest: dict[str, List[str]] = {}

    deduplicated_count = 0
    preserved_unique_count = 0

    for source_name, raw_text in drafts:
        for block in parse_markdown_blocks(source_name, raw_text):
            digest = block.exact_digest
            sources_by_digest.setdefault(digest, []).append(block.source)
            if digest in seen_exact_digests:
                deduplicated_count += 1
                continue
            seen_exact_digests.add(digest)
            preserved_unique_count += 1
            if block.heading not in grouped_blocks:
                heading_order.append(block.heading)
                grouped_blocks[block.heading] = []
            grouped_blocks[block.heading].append(block)

    conflict_count = 0
    rendered_sections: List[str] = []
    blocks_by_heading: dict[str, List[str]] = {}

    for heading in heading_order:
        blocks = grouped_blocks[heading]
        emitted_indices: set[int] = set()
        section_parts: List[str] = [f"## {heading}"]
        heading_items: List[str] = []

        for i, current in enumerate(blocks):
            if i in emitted_indices:
                continue

            conflict_partner_idx: int | None = None
            for j in range(i + 1, len(blocks)):
                if j not in emitted_indices and _shares_conflict_anchor(current, blocks[j]):
                    conflict_partner_idx = j
                    break

            if conflict_partner_idx is not None:
                partner = blocks[conflict_partner_idx]
                emitted_indices.add(i)
                emitted_indices.add(conflict_partner_idx)
                conflict_count += 1
                flag = _conflict_flag_for(current, partner)
                left_tag = _format_source_tag([current.source], show_source_tags)
                right_tag = _format_source_tag([partner.source], show_source_tags)
                rendered = (
                    f"{flag}\n"
                    f"{left_tag}{current.text}\n"
                    f"{right_tag}{partner.text}\n"
                    f"{flag}"
                )
                section_parts.append(rendered)
                heading_items.append(rendered)
            else:
                emitted_indices.add(i)
                tag = _format_source_tag(sources_by_digest.get(current.exact_digest, [current.source]), show_source_tags)
                rendered = f"{tag}{current.text}"
                section_parts.append(rendered)
                heading_items.append(rendered)

        blocks_by_heading[heading] = heading_items
        rendered_sections.append("\n\n".join(section_parts))

    merge_status = STATUS_CONFLICT if conflict_count > 0 else STATUS_CONSOLIDATED

    return MergeResult(
        merged_text="\n\n".join(rendered_sections),
        merge_status=merge_status,
        show_source_tags=show_source_tags,
        preserved_unique_count=preserved_unique_count,
        deduplicated_count=deduplicated_count,
        conflict_count=conflict_count,
        blocks_by_heading=blocks_by_heading,
    )


def merge_from_iterable(
    drafts: Iterable[tuple[str, str]],
    show_source_tags: bool = False,
) -> MergeResult:
    return merge_legal_drafts(list(drafts), show_source_tags=show_source_tags)
