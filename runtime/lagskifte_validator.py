# -*- coding: utf-8 -*-
"""
Lagskiftesvalidering: givet beslutsdatum → korrekt lagversion.
Primär källa: config/arende_config.yaml via config_loader.
Fallback: inbyggd LAGSKIFTEN om config saknas.
Producerar aldrig domslut. Gissar aldrig.
"""
from __future__ import annotations
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from konfig_kalla import ladda_konfig

_ROOT = Path(__file__).resolve().parent.parent

# Fallback om config_loader / arende_config ej tillgänglig
_FALLBACK_LAGSKIFTEN: List[Tuple[str, str, str, date]] = [
    ("SoL", "2001:453", "2025:400", date(2025, 7, 1)),
    ("FPL", "1971:291", "2023:560", date(2024, 1, 1)),
]


# Varifrån LAGSKIFTEN kom, och varför. Sätts av _ladda_lagskiften.
#
# Tre skilda vägar landade tidigare tyst i _FALLBACK_LAGSKIFTEN: konfigurationen
# saknades, konfigurationen fanns men samtliga poster förkastades (villkoret
# `if out:` föll då igenom), eller ett undantag inträffade under laddningen.
# I samtliga fall prövades HS11 mot en inbyggd tvåpostslista i stället för de
# konfigurerade lagskiftena, utan att något i utdata sade det. En operatör som
# lagt in ett lagskifte med felstavat datum fick alltså tyst tillbaka motorns
# egna värden.
LAGSKIFTEN_KÄLLA: str = "OKÄND"
LAGSKIFTEN_SKÄL: Optional[str] = None
LAGSKIFTEN_FÖRKASTADE: List[str] = []


def _ladda_lagskiften() -> List[Tuple[str, str, str, date]]:
    """
    Läs lagskiften från arende_config; fallback till inbyggd lista.

    Källan och skälet registreras i LAGSKIFTEN_KÄLLA och LAGSKIFTEN_SKÄL,
    och förkastade poster i LAGSKIFTEN_FÖRKASTADE, så att en körning på
    inbyggda värden går att skilja från en körning på konfigurerade.
    """
    global LAGSKIFTEN_KÄLLA, LAGSKIFTEN_SKÄL, LAGSKIFTEN_FÖRKASTADE
    LAGSKIFTEN_FÖRKASTADE = []
    try:
        from config_loader import arende_config
        cfg = arende_config() or {}
        raw = cfg.get("lagskiften") or []
        out: List[Tuple[str, str, str, date]] = []
        for item in raw:
            if not isinstance(item, dict):
                LAGSKIFTEN_FÖRKASTADE.append(f"posten är inte ett objekt: {item!r}")
                continue
            lag = str(item.get("lag") or "").strip()
            gammal = str(item.get("gammal") or "").strip()
            ny = str(item.get("ny") or "").strip()
            ikraft_s = str(item.get("ikraftträdande") or item.get("ikrafttradande") or "").strip()
            if not (lag and gammal and ny and ikraft_s):
                LAGSKIFTEN_FÖRKASTADE.append(
                    f"ofullständig post (lag={lag!r}, gammal={gammal!r}, "
                    f"ny={ny!r}, ikraftträdande={ikraft_s!r})"
                )
                continue
            try:
                ikraft = date.fromisoformat(ikraft_s)
            except ValueError as e:
                LAGSKIFTEN_FÖRKASTADE.append(
                    f"{lag}: ikraftträdande {ikraft_s!r} är inget ISO-datum ({e})"
                )
                continue
            out.append((lag, gammal, ny, ikraft))
        if out:
            LAGSKIFTEN_KÄLLA = "config"
            LAGSKIFTEN_SKÄL = None
            if LAGSKIFTEN_FÖRKASTADE:
                LAGSKIFTEN_SKÄL = (
                    f"{len(LAGSKIFTEN_FÖRKASTADE)} poster i arende_config "
                    f"förkastades och ingår inte i prövningen"
                )
            return out
        LAGSKIFTEN_SKÄL = (
            "arende_config innehöll inga giltiga lagskiften"
            if raw else "arende_config innehöll inga lagskiften"
        )
    except Exception as e:
        LAGSKIFTEN_SKÄL = f"arende_config kunde inte läsas: {type(e).__name__}: {e}"

    LAGSKIFTEN_KÄLLA = "INBYGGD_FALLBACK"
    return list(_FALLBACK_LAGSKIFTEN)


# Bakåtkompatibilitet: LAGSKIFTEN speglar laddad lista vid import
LAGSKIFTEN: List[Tuple[str, str, str, date]] = _ladda_lagskiften()


class LagskiftesValideringsResultat:
    def __init__(
        self,
        lag: str,
        version: str,
        ikraftträdande: Optional[date],
        motivering: str,
        varning: Optional[str] = None,
    ):
        self.lag = lag
        self.version = version
        self.ikraftträdande = ikraftträdande
        self.motivering = motivering
        self.varning = varning

    def to_dict(self) -> Dict:
        return {
            "lag": self.lag,
            "version": self.version,
            "ikraftträdande": str(self.ikraftträdande) if self.ikraftträdande else None,
            "motivering": self.motivering,
            "varning": self.varning,
        }


def validera_lagversion(
    lag: str,
    beslutsdatum: Optional[date] = None,
    beslutsdatum_str: Optional[str] = None,
) -> LagskiftesValideringsResultat:
    if beslutsdatum is None and beslutsdatum_str:
        try:
            beslutsdatum = date.fromisoformat(beslutsdatum_str.strip())
        except ValueError:
            return LagskiftesValideringsResultat(
                lag=lag,
                version="VERSION_OKLAR",
                ikraftträdande=None,
                motivering=f"Datum '{beslutsdatum_str}' kunde inte tolkas — ange YYYY-MM-DD.",
                varning="HS11: Lagversion kan inte fastställas utan giltigt datum.",
            )

    if beslutsdatum is None:
        return LagskiftesValideringsResultat(
            lag=lag,
            version="VERSION_OKLAR",
            ikraftträdande=None,
            motivering="Beslutsdatum saknas — lagversion kan inte fastställas.",
            varning="HS11: Lagversion oklar utan datum.",
        )

    register = _ladda_lagskiften()
    for (reg_lag, gammal, ny, ikraft) in register:
        if reg_lag.upper() != lag.upper():
            continue
        if beslutsdatum >= ikraft:
            return LagskiftesValideringsResultat(
                lag=lag,
                version=ny,
                ikraftträdande=ikraft,
                motivering=(
                    f"Beslutsdatum {beslutsdatum} ≥ ikraftträdandedatum {ikraft}. "
                    f"Gällande version: {lag} ({ny})."
                ),
            )
        return LagskiftesValideringsResultat(
            lag=lag,
            version=gammal,
            ikraftträdande=ikraft,
            motivering=(
                f"Beslutsdatum {beslutsdatum} < ikraftträdandedatum {ikraft}. "
                f"Gällande version: {lag} ({gammal})."
            ),
            varning=f"OBS: Ny version {lag} ({ny}) trädde i kraft {ikraft}.",
        )

    return LagskiftesValideringsResultat(
        lag=lag,
        version="VERSION_OKLAR",
        ikraftträdande=None,
        motivering=f"Lag '{lag}' finns inte i lagskiftesregistret (arende_config/fallback).",
        varning=f"Lägg till '{lag}' i arende_config.yaml lagskiften om lagskifte är känt.",
    )


def validera_alla_lagrum(
    lagrum_lista: List[str],
    beslutsdatum: Optional[date] = None,
    beslutsdatum_str: Optional[str] = None,
) -> List[Dict]:
    import re
    resultat = []
    for lagrum in lagrum_lista:
        match = re.match(r"^([A-Za-zÅÄÖåäö]{2,6})", lagrum.strip())
        if not match:
            resultat.append({
                "lagrum": lagrum,
                "version": "VERSION_OKLAR",
                "varning": "Lagnamn kunde inte extraheras.",
            })
            continue
        lag = match.group(1)
        val = validera_lagversion(lag, beslutsdatum, beslutsdatum_str)
        r = val.to_dict()
        r["lagrum"] = lagrum
        resultat.append(r)
    return resultat


def run_lagskifte_if_requested(
    lagrum_lista: Optional[List[str]] = None,
    requested: bool = False,
    beslutsdatum_str: Optional[str] = None,
) -> Dict:
    if not requested:
        return {
            "status": "EJ_BEGÄRD",
            "detail": "Lagskiftesvalidering kräver explicit requested=True.",
        }
    if not lagrum_lista:
        return {
            "status": "EJ_KÖRBAR",
            "skäl": "Ingen lagrum-lista angiven.",
        }
    resultat = validera_alla_lagrum(
        lagrum_lista,
        beslutsdatum_str=beslutsdatum_str,
    )
    varningar = [r for r in resultat if r.get("varning")]
    hs11 = [r for r in resultat if "HS11" in str(r.get("varning", ""))]
    return {
        "status": "GENOMFÖRD",
        "antal_lagrum": len(resultat),
        "resultat": resultat,
        "varningar": varningar,
        "hs11_koder": hs11,
        "källa": "arende_config eller fallback",
        "not": "INDIKATIV_ENDAST — juristen verifierar lagversion.",
    }


def slå_upp_sol_paragraf(
    gammal_paragraf: Optional[str] = None,
    ämne: Optional[str] = None,
    kategori: Optional[str] = None,
) -> Dict[str, Any]:
    """Slår upp SoL 2001:453 → 2025:400-mappningen i
    config/sol_paragrafmappning.yaml (sol-paragrafmappning.md,
    juridisk-processmotor-UNIFIED). Redovisar bara mappningen — avgör
    aldrig vilken lagversion som faktiskt gäller i ett ärende (det
    kräver ett beslutsdatum, se validera_lagversion())."""
    konfig = ladda_konfig(_ROOT / "config" / "sol_paragrafmappning.yaml")
    mappningar = (konfig.data or {}).get("mappningar") or []

    def _matchar(post: Dict[str, Any]) -> bool:
        if gammal_paragraf is not None:
            return post.get("gammal_paragraf") == gammal_paragraf
        if ämne is not None:
            return post.get("ämne") == ämne
        if kategori is not None:
            return post.get("kategori") == kategori
        return False

    träffar = [
        {
            "ämne": post.get("ämne"),
            "kategori": post.get("kategori"),
            "gammal_paragraf_2001_453": post.get("gammal_paragraf"),
            "ny_paragraf_2025_400": post.get("ny_paragraf"),
            "kommentar": post.get("kommentar", ""),
        }
        for post in mappningar if _matchar(post)
    ]

    if not träffar:
        return {
            "status": "INGEN_TRÄFF",
            "träffar": [],
            "antal_träffar": 0,
            **konfig.som_fält(),
        }

    return {
        "status": "GENOMFÖRD",
        "träffar": träffar,
        "antal_träffar": len(träffar),
        **konfig.som_fält(),
        "not": "INDIKATIV_ENDAST. Redovisar bara paragrafmappningen, avgör aldrig vilken lagversion som gäller i ärendet.",
    }


# ── Steg 27: onlineverifierad lagversion (samma källa som verifieringsgrinden) ──
# validera_alla_lagrum() ovan bygger på lagskiftesregistret och kan ge
# VERSION_OKLAR. Det får inte vara ett slutläge för juridisk output. Den här
# vägen löser förkortningen via config/lagforkortningar_sfs.yaml, väljer den
# författning som gällde på beslutsdatum och prövar paragrafen mot
# data.riksdagen.se. Utfallet är alltid VERIFIERAD, eller blockerat med skäl
# (EJ_BELAGT i källan, ogiltig inmatning, eller tekniskt källfel).
def run_lagskifte_verifierad(
    lagrum_lista: List[str],
    beslutsdatum_str: Optional[str] = None,
    grind: Any = None,
) -> Dict[str, Any]:
    import datetime as _dt
    from verifieringsgrind import (
        HS_KOD, TekniskVerifieringsfel, Verifieringsgrind, extrahera_påståenden,
    )
    if not lagrum_lista:
        return {"status": "VARNING", "kod": HS_KOD, "output_blockerad": False, "varning": True,
                "skäl": "Ingen lagrum-lista angiven - inget att verifiera (varning)." }
    try:
        datum = _dt.date.fromisoformat(str(beslutsdatum_str or "").strip())
    except ValueError:
        return {"status": "VARNING", "kod": HS_KOD, "output_blockerad": False, "varning": True,
                "skäl": f"Beslutsdatum {beslutsdatum_str!r} saknas eller är inte YYYY-MM-DD; "
                        "lagversion ej verifierad (varning)."}
    grind = grind or Verifieringsgrind()
    resultat: List[Dict[str, Any]] = []
    tekniska: List[str] = []
    for lagrum in lagrum_lista:
        p = [x for x in extrahera_påståenden(str(lagrum)) if x.get("typ") == "LAGRUM"]
        if len(p) != 1:
            resultat.append({"lagrum": lagrum, "utfall": "EJ_BELAGT",
                             "skäl": "Lagrummet måste anges som paragraf + förkortning "
                                     "(t.ex. '2 § LVU' eller 'SoL 4 kap. 1 §'); "
                                     f"hittade {len(p)} prövbara lagrum."})
            continue
        try:
            v = grind._verifiera_lagrum(p[0], datum)
        except TekniskVerifieringsfel as e:
            tekniska.append(f"{lagrum}: {e}")
            resultat.append({"lagrum": lagrum, "utfall": "TEKNISKT_FEL", "skäl": str(e)})
            continue
        v = {k: val for k, val in v.items() if k != "exakt_text"}
        v["lagrum"] = lagrum
        v["förkortning"] = p[0]["förkortning"]
        if v.get("utfall") == "VERIFIERAT":
            v["version"] = v.get("sfs")
        resultat.append(v)
    bas = {"antal_lagrum": len(resultat), "beslutsdatum": datum.isoformat(),
           "resultat": resultat, "källa": "data.riksdagen.se via config/lagforkortningar_sfs.yaml",
           "prövningsdatum": _dt.date.today().isoformat()}
    if tekniska:
        return {"status": "FAILED", "kod": "FAILED_VERIFIERING", "output_blockerad": True,
                "fel": "; ".join(tekniska), **bas}
    ej = [r for r in resultat if r.get("utfall") != "VERIFIERAT"]
    if ej:
        return {"status": "VARNING", "kod": HS_KOD, "output_blockerad": False, "varning": True,
                "skäl": "; ".join(f"{r['lagrum']}: {r.get('skäl', '')}" for r in ej), **bas}
    return {"status": "VERIFIERAD", "output_blockerad": False, **bas}
