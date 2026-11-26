#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RESOURCE LOADER

Laddar arkiverade, externa och case-specifika resurser från references/.
Dessa är stödmaterial som kan refereras men inte är kritiska för pipeline.
"""

from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Optional
import sys

ROOT = Path(__file__).resolve().parent.parent


class ResourceLoader:
    """Laddar arkiverade och externa resurser."""

    def __init__(self, case_dir: Optional[str] = None):
        self.archive_dir = ROOT / "references" / "archive"
        self.external_dir = ROOT / "references" / "external_packs"
        # case_dir måste sättas explicit från det aktiva ärendets registry-post.
        # None innebär att inga ärendespecifika resurser laddas — aldrig en annan
        # ärendekatalog som implicit fallback.
        if case_dir:
            self.case_dir: Optional[Path] = (
                Path(case_dir) if Path(case_dir).is_absolute() else ROOT / case_dir
            )
        else:
            self.case_dir = None
        self.advocacy_dir = ROOT / "references" / "advocacy-templates"
        self.resources: Dict[str, Dict[str, str]] = {}
        # En resursfil som inte går att läsa föll tidigare ur ordboken utan
        # spår — bara en lägre räknare i loggraden, omöjlig att skilja från
        # att katalogen innehöll färre filer. Varje bortfall redovisas nu
        # explicit här.
        self.ej_lästa: List[Dict[str, str]] = []

    def _läs_katalog(self, katalog: Path, kategori: str) -> Dict[str, str]:
        resources: Dict[str, str] = {}
        for file in katalog.rglob("*"):
            if not file.is_file():
                continue
            relative = file.relative_to(katalog)
            try:
                with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                resources[str(relative)] = content
            except Exception as e:
                fel = f"{type(e).__name__}: {e}"
                self.ej_lästa.append({"kategori": kategori, "fil": str(relative), "fel": fel})
                print(f"[RESOURCE_LOADER] KAN EJ LÄSAS ({kategori}) {relative}: {fel}", file=sys.stderr)
        return resources

    def load_archive(self) -> Dict[str, str]:
        """Laddar arkiverade resurser."""
        if not self.archive_dir.exists():
            return {}
        resources = self._läs_katalog(self.archive_dir, "archive")
        if resources:
            print(f"[RESOURCE_LOADER] Loaded {len(resources)} archive resources", file=sys.stderr)
        return resources

    def load_external_packs(self) -> Dict[str, str]:
        """Laddar externa paket."""
        if not self.external_dir.exists():
            return {}
        resources = self._läs_katalog(self.external_dir, "external_packs")
        if resources:
            print(f"[RESOURCE_LOADER] Loaded {len(resources)} external pack resources", file=sys.stderr)
        return resources

    def load_case_resources(self) -> Dict[str, str]:
        """Laddar case-specifika resurser. Returnerar {} om case_dir ej är explicit satt."""
        if self.case_dir is None or not self.case_dir.exists():
            return {}
        resources = self._läs_katalog(self.case_dir, "case_resources")
        if resources:
            print(f"[RESOURCE_LOADER] Loaded {len(resources)} case-specific resources", file=sys.stderr)
        return resources

    def load_advocacy_templates(self) -> Dict[str, str]:
        """Laddar advocacy-templates resurser."""
        if not self.advocacy_dir.exists():
            return {}
        resources = self._läs_katalog(self.advocacy_dir, "advocacy_templates")
        if resources:
            print(f"[RESOURCE_LOADER] Loaded {len(resources)} advocacy templates", file=sys.stderr)
        return resources


_resource_loader: Optional[ResourceLoader] = None


def get_resource_loader() -> ResourceLoader:
    """Hämtar global resource loader (singleton)."""
    global _resource_loader
    if _resource_loader is None:
        _resource_loader = ResourceLoader()
    return _resource_loader


def load_all_resources() -> Dict[str, Dict[str, str]]:
    """Laddar alla arkiv-, externa och case-resurser."""
    loader = get_resource_loader()

    # Load skill SKILL.md definitions and references (RUNTIME-ACTIVE ONLY)
    # NOTE: skill_registry_meta (README.md, SKILLKEDJA_INDEX.md) and skill_commands
    # are documentation/index files that are not consumed by runtime motors.
    # They have been removed from active loading to eliminate memory overhead.
    skill_definitions = {}
    skill_references = {}
    skills_dir = ROOT / "references" / "skills_registry"
    if skills_dir.exists():
        for skill_dir in skills_dir.iterdir():
            if skill_dir.is_dir():
                # Load SKILL.md file
                skill_md = skill_dir / "SKILL.md"
                if skill_md.exists():
                    try:
                        with open(skill_md, 'r', encoding='utf-8') as f:
                            content = f.read()
                        relative = skill_md.relative_to(skills_dir)
                        skill_definitions[str(relative)] = content
                    except Exception as e:
                        # Läsningen saknar errors='ignore': ett avkodningsfel
                        # tog tidigare bort hela skill-definitionen utan spår.
                        loader.ej_lästa.append({
                            "kategori": "skill_definitions",
                            "fil": str(skill_md),
                            "fel": f"{type(e).__name__}: {e}",
                        })
                        print(
                            f"[RESOURCE_LOADER] KAN EJ LÄSAS (skill_definitions): "
                            f"{skill_md} — {type(e).__name__}: {e}",
                            file=sys.stderr,
                        )

                # Load skill references
                refs_dir = skill_dir / "references"
                if refs_dir.exists():
                    for file in refs_dir.rglob("*"):
                        if file.is_file():
                            try:
                                with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                                    content = f.read()
                                relative = file.relative_to(skills_dir)
                                skill_references[str(relative)] = content
                            except Exception as e:
                                loader.ej_lästa.append({
                                    "kategori": "skill_references",
                                    "fil": str(file),
                                    "fel": f"{type(e).__name__}: {e}",
                                })
                                print(
                                    f"[RESOURCE_LOADER] KAN EJ LÄSAS "
                                    f"(skill_references): {file} "
                                    f"— {type(e).__name__}: {e}",
                                    file=sys.stderr,
                                )

    if skill_definitions:
        print(f"[RESOURCE_LOADER] Loaded {len(skill_definitions)} SKILL.md definitions", file=sys.stderr)
    if skill_references:
        print(f"[RESOURCE_LOADER] Loaded {len(skill_references)} skill references", file=sys.stderr)

    return {
        'archive': loader.load_archive(),
        'external_packs': loader.load_external_packs(),
        'case_resources': loader.load_case_resources(),
        'advocacy_templates': loader.load_advocacy_templates(),
        'skill_definitions': skill_definitions,
        'skill_references': skill_references,
        'ej_lästa': loader.ej_lästa,
    }
