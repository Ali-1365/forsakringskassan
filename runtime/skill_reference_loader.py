#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SKILL REFERENCE LOADER

Gör skill-specifika references åtkomliga för varje skill.
Varje skill har en references/ subdirectory med dokumentation.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent


class SkillReferenceLoader:
    """Laddar references för en specifik skill."""

    def __init__(self):
        self.skills_dir = ROOT / "references" / "skills_registry"
        self.skill_references: Dict[str, Dict[str, str]] = {}  # skill_name -> {ref_name: content}

    def load_skill_references(self, skill_name: str) -> Dict[str, str]:
        """Laddar references för en specifik skill."""
        if skill_name in self.skill_references:
            return self.skill_references[skill_name]

        skill_dir = self.skills_dir / skill_name
        if not skill_dir.exists():
            return {}

        references_dir = skill_dir / "references"
        if not references_dir.exists():
            return {}

        refs = {}
        for ref_file in references_dir.rglob("*.md"):
            try:
                with open(ref_file, 'r', encoding='utf-8') as f:
                    refs[ref_file.name] = f.read()
            except Exception as e:
                # Referensen föll tidigare bort utan spår. En skill som
                # saknar en av sina referenser går då inte att skilja från
                # en skill som aldrig haft den.
                refs[ref_file.name] = (
                    f"[KAN EJ LÄSAS: {type(e).__name__}: {e}]"
                )
                print(
                    f"[SKILL_REFERENCE_LOADER] KAN EJ LÄSAS: {ref_file} "
                    f"— {type(e).__name__}: {e}",
                    file=sys.stderr,
                )

        self.skill_references[skill_name] = refs
        return refs

    def get_skill_reference(self, skill_name: str, ref_name: str) -> Optional[str]:
        """Hämtar en specifik reference för en skill."""
        refs = self.load_skill_references(skill_name)
        return refs.get(ref_name)

    def list_skill_references(self, skill_name: str) -> List[str]:
        """Listar alla references för en skill."""
        refs = self.load_skill_references(skill_name)
        return list(refs.keys())


# Global loader instance
_skill_reference_loader: Optional[SkillReferenceLoader] = None


def get_skill_reference_loader() -> SkillReferenceLoader:
    """Hämtar global skill reference loader (singleton)."""
    global _skill_reference_loader
    if _skill_reference_loader is None:
        _skill_reference_loader = SkillReferenceLoader()
        import sys
        print(f"[SKILL_REFERENCE_LOADER] Initialized", file=sys.stderr)
    return _skill_reference_loader


def load_skill_references(skill_name: str) -> Dict[str, str]:
    """Laddar references för en skill."""
    loader = get_skill_reference_loader()
    refs = loader.load_skill_references(skill_name)
    import sys
    print(f"[SKILL_REFERENCE_LOAD] {skill_name} → {len(refs)} files", file=sys.stderr)
    return refs


def get_skill_reference(skill_name: str, ref_name: str) -> Optional[str]:
    """Hämtar en skill-specifik reference."""
    loader = get_skill_reference_loader()
    content = loader.get_skill_reference(skill_name, ref_name)
    import sys
    status = "OK" if content else "NOT_FOUND"
    print(f"[SKILL_REFERENCE_GET] {skill_name}/{ref_name} → {status}", file=sys.stderr)
    return content


if __name__ == "__main__":
    # Test skill reference loader
    loader = SkillReferenceLoader()

    print("=" * 70)
    print("SKILL REFERENCE LOADER TEST")
    print("=" * 70)
    print()

    # Find first skill with references
    skills_dir = ROOT / "references" / "skills_registry"
    for skill_folder in skills_dir.iterdir():
        if not skill_folder.is_dir():
            continue

        skill_name = skill_folder.name
        refs = loader.load_skill_references(skill_name)

        if refs:
            print(f"Skill: {skill_name}")
            print(f"  References: {len(refs)} files")
            for ref_name in list(refs.keys())[:3]:
                content_len = len(refs[ref_name])
                print(f"    - {ref_name} ({content_len} bytes)")
            print()
            break

    print("=" * 70)
    print("SKILL REFERENCES ARE LOADABLE")
    print("=" * 70)
