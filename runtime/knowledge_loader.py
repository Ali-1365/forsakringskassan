#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KNOWLEDGE BASE LOADER

Gör alla knowledge-base filer åtkomliga för Runtime, MCP, Plugins och Skills.

Kunskapsrötter (upptäcks generiskt, ingen fil pekas ut med namn):
- references/knowledge/<kategori>/**.md   kategori = underkatalogens namn
- runtime/knowledge/**.md                 kategori = "runtime-domain"
  (domänreferenser som dynamic_pipeline läser via progressive disclosure;
  tidigare indexerades de inte alls, så get_knowledge() gav NOT_FOUND)

Byte-identiska filer under olika rötter indexeras var för sig men markeras
med duplicate_of (sha256), så en dubblett aldrig räknas som ny kunskap.

Integrationspunkter:
- Runtime: Dynamisk pipelining kan fråga relevant kunskap
- MCP: Knowledge-tools kan exponera kunskap för plugins
- Skills: Varje skill kan få sin kontextkunskap
- Juridisk Motor: Kan förhöra kunskapen om juridiska lager
"""

from __future__ import annotations

import os
import json
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent

@dataclass
class KnowledgeFile:
    """Representation av en kunskapsfil."""
    filename: str
    path: str
    category: str  # legal-theory, procedures, architecture, specifications, other
    relative_path: str
    size_bytes: int
    content_preview: str  # First 500 chars
    tags: List[str]
    sha256: str = ""
    duplicate_of: str = ""

    def __post_init__(self):
        """Validate and set content."""
        if os.path.exists(self.path):
            try:
                with open(self.path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    self.content_preview = content[:500]
            except Exception:
                self.content_preview = "[ERROR: Cannot read file]"


class KnowledgeBaseLoader:
    """Laddar och indexerar alla knowledge-base filer."""

    def __init__(self):
        self.knowledge_dir = ROOT / "references" / "knowledge"
        # Platta kunskapsrötter: (katalog, kategori). Alla .md under katalogen
        # hör till samma kategori.
        self.flat_roots: List[tuple] = [
            (ROOT / "runtime" / "knowledge", "runtime-domain"),
        ]
        self._hash_index: Dict[str, str] = {}  # sha256 -> första relative_path
        self.files: Dict[str, KnowledgeFile] = {}
        self.index: Dict[str, List[str]] = {}  # category -> filenames
        self.tags_index: Dict[str, List[str]] = {}  # tag -> filenames

    def load_all_knowledge(self) -> Dict[str, Any]:
        """Laddar alla knowledge-base filer från references/knowledge/."""
        result = {
            "status": "LOADING",
            "total_files": 0,
            "categories": {},
            "files_by_category": {},
            "files": {},
            "errors": []
        }

        if not self.knowledge_dir.exists():
            result["status"] = "FAILED"
            result["errors"].append(f"Knowledge directory not found: {self.knowledge_dir}")
            return result

        # Scan subdirectories
        categories: Dict[str, List[str]] = {}
        for category_dir in sorted(self.knowledge_dir.iterdir()):
            if not category_dir.is_dir():
                continue
            self._scan_category(category_dir, category_dir.name, categories, result)

        # Platta rötter (t.ex. runtime/knowledge)
        for root_dir, category in self.flat_roots:
            if root_dir.is_dir():
                self._scan_category(root_dir, category, categories, result)

        result["categories"] = categories
        result["status"] = "LOADED"
        result["total_files"] = len(self.files)

        return result

    def _scan_category(self, category_dir: Path, category: str,
                       categories: Dict[str, List[str]], result: Dict[str, Any]) -> None:
        categories.setdefault(category, [])
        result["files_by_category"].setdefault(category, [])
        for file_path in sorted(category_dir.rglob("*.md")):
            try:
                relative = file_path.relative_to(ROOT)
                relative_posix = relative.as_posix()
                try:
                    digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
                except Exception as e:
                    digest = ""
                    result.setdefault("hash_fel", []).append(
                        f"{relative_posix}: {type(e).__name__}: {e}")
                duplicate_of = ""
                if digest:
                    first = self._hash_index.get(digest)
                    if first and first != relative_posix:
                        duplicate_of = first
                    else:
                        self._hash_index[digest] = relative_posix
                knowledge_file = KnowledgeFile(
                    filename=file_path.name,
                    path=str(file_path),
                    category=category,
                    relative_path=relative_posix,
                    size_bytes=file_path.stat().st_size,
                    content_preview="",  # Set by __post_init__
                    tags=self._extract_tags(file_path.name, file_path),
                    sha256=digest,
                    duplicate_of=duplicate_of,
                )

                self.files[relative_posix] = knowledge_file
                categories[category].append(file_path.name)
                self.index.setdefault(category, []).append(relative_posix)
                result["files_by_category"][category].append({
                    "name": file_path.name,
                    "size": file_path.stat().st_size,
                    "path": str(relative),
                    "duplicate_of": duplicate_of,
                })

                for tag in knowledge_file.tags:
                    self.tags_index.setdefault(tag, []).append(str(relative))

            except Exception as e:
                result["errors"].append(f"Error loading {file_path}: {e}")

    def categories(self) -> Dict[str, int]:
        """Antal indexerade filer per kategori."""
        return {k: len(v) for k, v in self.index.items()}

    def duplicates(self) -> Dict[str, str]:
        """{relative_path: duplicate_of} för byte-identiska kopior."""
        return {p: f.duplicate_of for p, f in self.files.items() if f.duplicate_of}

    def _extract_tags(self, filename: str, filepath: Path) -> List[str]:
        """Extraherar relevanta tags från filnamn och kategori."""
        tags = []

        # Category-based tags
        category = filepath.parent.name
        tags.append(category)

        # Filename-based tags
        name_lower = filename.lower()
        if "lager" in name_lower:
            tags.append("legal-layer")
        if "protokoll" in name_lower:
            tags.append("protocol")
        if "arkitektur" in name_lower:
            tags.append("architecture")
        if "bevis" in name_lower:
            tags.append("evidence")
        if "juridisk" in name_lower:
            tags.append("legal")
        if "process" in name_lower:
            tags.append("process")
        if "falsifiering" in name_lower or "falsifikation" in name_lower:
            tags.append("falsification")
        if "audit" in name_lower:
            tags.append("audit")

        return list(set(tags))

    def search_by_category(self, category: str) -> List[KnowledgeFile]:
        """Söker filer i en specifik kategori."""
        return [
            f for f in self.files.values()
            if f.category == category
        ]

    def search_by_tag(self, tag: str) -> List[str]:
        """Söker filer med en specifik tag."""
        return self.tags_index.get(tag, [])

    def search_by_pattern(self, pattern: str) -> List[KnowledgeFile]:
        """Söker filer vars filnamn matchar pattern."""
        pattern_lower = pattern.lower()
        return [
            f for f in self.files.values()
            if pattern_lower in f.filename.lower()
        ]

    def get_file(self, relative_path: str) -> Optional[KnowledgeFile]:
        """Hämtar en specifik kunskapsfil."""
        return self.files.get(str(relative_path).replace("\\", "/"))

    def read_content(self, relative_path: str) -> Optional[str]:
        """Läser innehållet av en kunskapsfil."""
        file_info = self.get_file(relative_path)
        if not file_info:
            return None

        try:
            with open(file_info.path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            return None

    def export_index(self, output_file: Optional[str] = None) -> Dict:
        """Exporterar knowledge-index som JSON."""
        index_data = {
            "timestamp": datetime.now().isoformat(),
            "total_files": len(self.files),
            "categories": {},
            "files": {}
        }

        for rel_path, file_obj in self.files.items():
            index_data["files"][rel_path] = {
                "filename": file_obj.filename,
                "category": file_obj.category,
                "size": file_obj.size_bytes,
                "tags": file_obj.tags,
                "sha256": file_obj.sha256,
                "duplicate_of": file_obj.duplicate_of,
                "preview": file_obj.content_preview[:200]
            }

        categories_map: Dict[str, List[str]] = {}
        for file_obj in self.files.values():
            categories_map.setdefault(file_obj.category, []).append(file_obj.filename)
        for category, fnames in categories_map.items():
            index_data["categories"][category] = fnames

        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)

        return index_data


# Global loader instance
_knowledge_loader: Optional[KnowledgeBaseLoader] = None


def get_knowledge_loader() -> KnowledgeBaseLoader:
    """Hämtar global knowledge loader (singleton)."""
    global _knowledge_loader
    if _knowledge_loader is None:
        _knowledge_loader = KnowledgeBaseLoader()
        result = _knowledge_loader.load_all_knowledge()
        import sys
        print(f"[KNOWLEDGE_LOADER] Initialized: {result['total_files']} files loaded", file=sys.stderr)
        for cat, files in result['categories'].items():
            print(f"[KNOWLEDGE_LOADER]   {cat}: {len(files)} files", file=sys.stderr)
    return _knowledge_loader


def search_knowledge(query: str, by: str = "pattern") -> List[KnowledgeFile]:
    """
    Söker i knowledge base.

    Args:
        query: Sökterm
        by: "pattern" (filnamn), "category", "tag"
    """
    loader = get_knowledge_loader()
    import sys

    if by == "pattern":
        results = loader.search_by_pattern(query)
        print(f"[KNOWLEDGE_SEARCH] pattern='{query}' → {len(results)} files", file=sys.stderr)
        return results
    elif by == "tag":
        files = loader.search_by_tag(query)
        results = [loader.get_file(f) for f in files if loader.get_file(f)]
        print(f"[KNOWLEDGE_SEARCH] tag='{query}' → {len(results)} files", file=sys.stderr)
        return results
    elif by == "category":
        results = loader.search_by_category(query)
        print(f"[KNOWLEDGE_SEARCH] category='{query}' → {len(results)} files", file=sys.stderr)
        return results
    else:
        return []


def get_knowledge(relative_path: str) -> Optional[str]:
    """Hämtar innehålet av en specifik kunskapsfil."""
    loader = get_knowledge_loader()
    content = loader.read_content(relative_path)
    import sys
    status = "OK" if content else "NOT_FOUND"
    print(f"[KNOWLEDGE_GET] {relative_path} → {status}", file=sys.stderr)
    return content


def ladda_kodsystem_index() -> Dict[str, Any]:
    """Indexera config/kodsystem_*.yaml via config_loader.

    Kunskapsbasen och kodsystemtabellerna är olika artefakter. Den här
    ingången gör varje tabell adresserbar utan att hårdkoda filnamn, och
    utan att blanda in knowledge-markdown i samma index.
    """
    import sys
    sys.path.insert(0, str(ROOT / "runtime"))
    from config_loader import kodsystem_nycklar, ladda_kodsystem

    poster: List[Dict[str, Any]] = []
    fel: List[str] = []
    for nyckel in kodsystem_nycklar():
        data = ladda_kodsystem(nyckel)
        if data is None:
            fel.append(nyckel)
            continue
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        koder = data.get("koder") if isinstance(data.get("koder"), list) else []
        poster.append({
            "nyckel": nyckel,
            "domän": meta.get("domän", nyckel[len("kodsystem_"):]),
            "antal_koder": len(koder),
        })
    print(
        f"[KNOWLEDGE_LOADER] kodsystem indexerade: {len(poster)}, fel: {len(fel)}",
        file=sys.stderr,
    )
    return {"antal": len(poster), "kodsystem": poster, "fel": fel}


if __name__ == "__main__":
    # Test knowledge loader
    loader = KnowledgeBaseLoader()
    result = loader.load_all_knowledge()

    print("=" * 70)
    print("KNOWLEDGE BASE LOADER TEST")
    print("=" * 70)
    print(f"Status: {result['status']}")
    print(f"Total files loaded: {result['total_files']}")
    print(f"Categories: {list(result['categories'].keys())}")
    print()
    print("Files by category:")
    for cat, count in [(cat, len(files)) for cat, files in result['categories'].items()]:
        print(f"  {cat}: {count} files")
    print()

    if result['errors']:
        print("Errors:")
        for error in result['errors']:
            print(f"  - {error}")
