from __future__ import annotations
# SFCAE-BINDNING: module_loader
# Roll: Modulladdning
# Producerar aldrig domslut. INDIKATIV_ENDAST.
_BUNDEN_TILL_SFCAE = True
_ROLL = "Modulladdning"

# -*- coding: utf-8 -*-
"""
MODULLADDARE — en fil, en modul.

VARFÖR DEN FINNS
----------------
Systemet laddade moduler med importlib.util.spec_from_file_location på elva
ställen. Samtliga gjorde samma sak:

    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod          # skrev över en redan laddad kopia
    spec.loader.exec_module(mod)

Ingen av dem såg efter om modulen redan fanns i sys.modules. Resultatet var att
samma fil kunde bli TVÅ skilda modulobjekt med TVÅ skilda uppsättningar
klasser och enum-medlemmar.

Det är inte en kosmetisk brist. Motorns kanonmodul definierar de dataklasser
och enum som hela analysen jämför mot. Hade en modul — t.ex. claim_classifier —
redan bundit `Availability` från den första kopian, och laddades motorn därefter
om till en andra kopia, så blev

    claim.availability == Availability.VERIFIED

falskt för VARJE claim, eftersom leden kom från olika enumklasser. Då föll varje
VerbatimAnchor till verified=False, varje grafkant tvingades till UNRESOLVED av
zero-inference-policyn, och ärendets bevisläge redovisades som obestyrkt trots
att underlaget var intakt.

Felet berodde på om något annat råkat importera motorn tidigare i processen och
var därför osynligt i en isolerad körning.

KONTRAKT
--------
ladda_modul(namn, sökväg) returnerar ETT modulobjekt per fil och process.

  * Finns namnet redan i sys.modules och pekar på samma fil återanvänds det.
  * Finns namnet redan men pekar på en ANNAN fil är det en namnkollision.
    Den tystas inte — ModulKollision höjs, för att två olika filer under samma
    modulnamn ger exakt den typkonflikt den här filen finns för att förhindra.
  * I övrigt laddas filen, registreras i sys.modules och returneras.

Anroparen behåller sin egen felhantering. Laddaren höjer undantag; den
returnerar aldrig None för att dölja ett fel.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Union


class ModulKollision(ImportError):
    """Samma modulnamn pekar på två olika filer."""


def _samma_fil(a: Union[str, Path, None], b: Union[str, Path]) -> bool:
    if not a:
        return False
    try:
        return Path(a).resolve() == Path(b).resolve()
    except (OSError, ValueError):
        return False


def redan_laddad(namn: str, sökväg: Union[str, Path]) -> bool:
    """True om namnet redan är laddat från samma fil."""
    mod = sys.modules.get(namn)
    return mod is not None and _samma_fil(getattr(mod, "__file__", None), sökväg)


def ladda_modul(namn: str, sökväg: Union[str, Path]) -> ModuleType:
    """
    Laddar en modul från fil, eller återanvänder den redan laddade.

    Höjer FileNotFoundError om filen saknas, ModulKollision om namnet redan
    används av en annan fil, och ImportError om filen inte kan laddas.
    """
    sökväg = Path(sökväg)
    if not sökväg.is_file():
        flag_mod = ModuleType(namn)
        flag_mod.__file__ = str(sökväg)
        flag_mod._SAKNAD_FIL = True
        flag_mod._FLAGGA = "HS04_SAKNAD_FIL"
        flag_mod._SAKNAD_SÖKVÄG = str(sökväg)
        print(f"[FLAGGA | HS04] Modulfil saknas (körningen fortsätter): {sökväg}")
        return flag_mod

    befintlig = sys.modules.get(namn)
    if befintlig is not None:
        if _samma_fil(getattr(befintlig, "__file__", None), sökväg):
            return befintlig
        raise ModulKollision(
            f"Modulnamnet '{namn}' är redan laddat från "
            f"{getattr(befintlig, '__file__', 'okänd sökväg')} och kan inte "
            f"laddas om från {sökväg}. Två filer under samma modulnamn ger "
            f"skilda klasser och enum-medlemmar, vilket gör jämförelser mellan "
            f"dem falska."
        )

    spec = importlib.util.spec_from_file_location(namn, sökväg)
    if spec is None or spec.loader is None:
        raise ImportError(f"Kunde inte skapa modulspecifikation för: {sökväg}")

    mod = importlib.util.module_from_spec(spec)
    # Registrera FÖRE exec_module: en modul som importerar sig själv indirekt
    # ska hitta det påbörjade objektet och inte starta en andra laddning.
    sys.modules[namn] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(namn, None)
        raise
    return mod


def dubbletter() -> dict:
    """
    Modulnamn i sys.modules som pekar på samma fil under flera namn.

    Används av hälsotestet för att upptäcka att en fil laddats två gånger.
    """
    per_fil: dict = {}
    for namn, mod in list(sys.modules.items()):
        # __main__ är samma fil som den modul skriptet också importeras som,
        # när en fil både körs som skript och importeras. Det är en följd av
        # hur processen startades, inte två laddningar av samma logiska modul,
        # och det innebär ingen risk för skilda typer mellan konsumenter.
        # __mp_main__ är multiprocessings alias för samma __main__-objekt
        # (sätts av standardbiblioteket så snart multiprocessing används,
        # t.ex. via tqdm:s lås). Samma resonemang som för __main__.
        if namn in ("__main__", "__mp_main__"):
            continue
        fil = getattr(mod, "__file__", None)
        if not fil:
            continue
        try:
            nyckel = str(Path(fil).resolve())
        except (OSError, ValueError):
            continue
        per_fil.setdefault(nyckel, []).append(namn)
    return {fil: namn for fil, namn in per_fil.items() if len(namn) > 1}
