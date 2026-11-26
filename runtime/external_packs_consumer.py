#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
External Packs Consumer – konsumerar commands, references, plugin.json, .mcp.json
från references/external_packs under faktisk runtime.
"""

import sys
import json
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parent.parent


def consume_external_packs() -> Dict[str, int]:
    """
    Konsumerar externa paket resurser under runtime.
    Verifiera faktisk användning av commands, references, konfigurationer.
    """
    from resource_loader import load_all_resources

    resources = load_all_resources()
    external = resources.get('external_packs', {})

    consumed = {
        'total_files': len(external),
        'commands': 0,
        'references': 0,
        'configs': 0,
        'analyzed': 0,
        'ogiltiga': 0,
        'ogiltiga_filer': [],
    }

    if not external:
        return consumed

    # Konsumera och analysera innehål
    for path, content in external.items():
        if not content:
            continue

        # Kategorisera och konsumera
        path_lower = path.lower()

        if 'command' in path_lower:
            consumed['commands'] += 1
            consumed['analyzed'] += 1
            # Verifiera kommando-struktur
            if path.endswith('.json'):
                # Ett naket `except:` fångade även KeyboardInterrupt och
                # SystemExit. Dessutom räknades en ogiltig JSON varken som
                # analyserad eller som ogiltig, varför siffrorna såg ut som
                # om filen bara saknat innehåll.
                try:
                    cmd_data = json.loads(content)
                    if cmd_data:
                        consumed['analyzed'] += 1
                except (ValueError, TypeError) as e:
                    consumed['ogiltiga'] += 1
                    consumed['ogiltiga_filer'].append(
                        f"{path}: {type(e).__name__}: {e}")

        elif 'reference' in path_lower or 'ref' in path_lower:
            consumed['references'] += 1
            consumed['analyzed'] += 1

        elif path.endswith('.json') or path.endswith('.yaml') or path.endswith('.yml'):
            consumed['configs'] += 1
            # Verifiera konfiguration
            if path.endswith('.json'):
                try:
                    config = json.loads(content)
                    if config:
                        consumed['analyzed'] += 1
                except (ValueError, TypeError) as e:
                    consumed['ogiltiga'] += 1
                    consumed['ogiltiga_filer'].append(
                        f"{path}: {type(e).__name__}: {e}")

    print(f"[EXTERNAL_PACKS_CONSUMER] Consumed {consumed['total_files']} external pack files", file=sys.stderr)
    print(f"[EXTERNAL_PACKS_CONSUMER] Commands: {consumed['commands']}, References: {consumed['references']}, Configs: {consumed['configs']}", file=sys.stderr)
    print(f"[EXTERNAL_PACKS_CONSUMER] Analyzed {consumed['analyzed']} items for content", file=sys.stderr)
    if consumed['ogiltiga']:
        print(
            f"[EXTERNAL_PACKS_CONSUMER] {consumed['ogiltiga']} filer kunde "
            f"inte tolkas: {consumed['ogiltiga_filer'][:5]}",
            file=sys.stderr,
        )

    return consumed


# Initiera konsumtion vid modul-laddning
_consumption_stats = consume_external_packs()
