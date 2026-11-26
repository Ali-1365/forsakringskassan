#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Case Resources Consumer — konsumerar case-specifika resurser
för ett aktivt ärende under faktisk körning.
Case-katalogen löses dynamiskt från session/arende_aktivator,
inte hårdkodad per ärende.
"""

import sys
from pathlib import Path
from typing import Dict, Optional

ROOT = Path(__file__).resolve().parent.parent


def consume_case_resources(case_dir: Optional[str] = None) -> Dict[str, int]:
    """
    Konsumerar case-specifika resurser från angiven case_dir.
    case_dir: relativ eller absolut sökväg från ärendets registry-post.
    Om None: inga ärendespecifika resurser laddas — noll filer returneras.
    """
    from resource_loader import ResourceLoader

    loader = ResourceLoader(case_dir=case_dir)
    case_resources = loader.load_case_resources()

    effective_dir = str(loader.case_dir) if loader.case_dir is not None else "NO_CASE_DIR"

    consumed = {
        'total_files': len(case_resources),
        'documents': 0,
        'metadata': 0,
        'analyzed': 0,
        'case_impact': False,
        'case_dir': effective_dir,
    }

    if not case_resources:
        print(f"[CASE_RESOURCES_CONSUMER] No case resources found in {effective_dir}", file=sys.stderr)
        return consumed

    for path, content in case_resources.items():
        if not content:
            continue
        path_lower = path.lower()
        if any(ext in path_lower for ext in ['.pdf', '.docx', '.doc', '.txt', '.md']):
            consumed['documents'] += 1
            consumed['analyzed'] += 1
            consumed['case_impact'] = True
        elif any(meta in path_lower for meta in ['meta', 'info', '.json']):
            consumed['metadata'] += 1
            consumed['analyzed'] += 1

    print(
        f"[CASE_RESOURCES_CONSUMER] Consumed {consumed['total_files']} case-specific resources "
        f"from {effective_dir}",
        file=sys.stderr,
    )
    return consumed


# Bakåtkompatibelt anrop utan case_dir: behåller befintlig signatur
_consumption_stats = consume_case_resources()
