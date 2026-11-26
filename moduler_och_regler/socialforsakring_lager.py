#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOCIALFÖRSÄKRING AUDIT-LAGER – L00–L02 (FAS 4)
SVENSK FORENSIC COURT AUDIT ENGINE v10.3-UPDATED
Datum: 2026-09-03

Implementerar socialförsäkringsspecifika audit-lager enligt
SKILL_final.md "ÄNDRINGSMATRIS 2026-08-21 – PATCH v10.3-UPDATED":

  L00_CASE_INTEGRITY     – aktens fullständighet (110:13 SFB, 27 § FL)
  L01_PRIMARY_SOURCE     – källans autenticitet + DFA-kedja (27:25 SFB,
                           HFD 2018 ref. 51)  → RT-CL DFA_KEDJA
  L02_AUDIO_FORENSICS_FK – muntlig kommunikation (27 § FL)

Lagerna aktiveras automatiskt vid socialförsäkringsmåltyp (RT-CK):
sjukpenning / SGI / rehabilitering / FK-ärenden.

DFA-kedjan (RT-CL) verifieras mot medicinska underlag i det aktuella
ärendets källmaterial – ALDRIG hårdkodad (RT-CX GENERALITET). Den
tillämpas som verifiering, ej som absolut lagkrav: en ofullständig kedja
flaggs som AVVIKELSE för granskning, inte som definitivt rättsbrott.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional


# ============================================================
# SOCIALFÖRSÄKRINGSMÅLTYP – RT-CK GATE
# ============================================================

SF_MÅLTYP_SIGNALS = [
    r"\bsjukpenning\b", r"\bsjukpenninggrundande\b", r"\bSGI\b",
    r"\bförsäkringskassan\b", r"\bFK\b", r"\brehabilitering\b",
    r"\bsjukskriven\b", r"\bsjukskrivning\b", r"\bsjukersättning\b",
    r"\baktivitetsersättning\b", r"\bsjukförsäkring\b",
    r"\bläkarintyg\b", r"\barbetsförmåga\b", r"\bsjukdom\b",
]


def is_socialforsakring_case(case_state) -> bool:
    """RT-CK: identifierar sjukpenning/SGI/rehabilitering/FK-måltyp."""
    haystacks: List[str] = []
    for claim in getattr(case_state, "claims", []) or []:
        content = getattr(claim, "content", "") or ""
        haystacks.append(str(content))
    for f in getattr(case_state, "files", []) or []:
        haystacks.append(str(getattr(f, "relative_path", "")))
        haystacks.append(str(getattr(f, "file_id", "")))
    text = " ".join(haystacks)
    return any(re.search(p, text, re.IGNORECASE) for p in SF_MÅLTYP_SIGNALS)


# ============================================================
# DATALAGER
# ============================================================

@dataclass
class SFLagerFinding:
    """Ett enskilt kontrollresultat från ett socialförsäkringslager."""
    lager: str
    kontrollpunkt: str
    status: str                    # OK | AVVIKELSE
    rättskälla: str
    beskrivning: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lager": self.lager,
            "kontrollpunkt": self.kontrollpunkt,
            "status": self.status,
            "rättskälla": self.rättskälla,
            "beskrivning": self.beskrivning,
        }


class _SFBaseLager:
    """Gemensam bas för L00–L02-lager."""
    LAGER_KOD = ""
    LAGERNAMN = ""
    RÄTTSKÄLLOR: List[str] = []

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self.log: List[str] = []
        self.findings: List[SFLagerFinding] = []

    def _add(self, kontrollpunkt: str, status: str, rättskälla: str,
             beskrivning: str) -> None:
        self.findings.append(SFLagerFinding(
            lager=self.LAGER_KOD,
            kontrollpunkt=kontrollpunkt,
            status=status,
            rättskälla=rättskälla,
            beskrivning=beskrivning,
        ))
        self.log.append(
            f"[{self.LAGER_KOD}] {kontrollpunkt}: {status} – {beskrivning}"
        )

    def _text(self, case_state) -> str:
        parts: List[str] = []
        for claim in getattr(case_state, "claims", []) or []:
            c = getattr(claim, "content", "") or ""
            if c:
                parts.append(str(c))
        return " ".join(parts)

    def generate_report(self) -> str:
        """Lagerformat-konform rapport (FIX-M: lagerstruktur obligatorisk)."""
        header = f"## LAGER {self.LAGER_KOD} – [{self.LAGERNAMN}]"
        lines = [header]
        for f in self.findings:
            lines.append(
                f"- {f.kontrollpunkt}: **{f.status}** "
                f"[{f.rättskälla}] {f.beskrivning}"
            )
        if not self.findings:
            lines.append("- Inga kontrollpunkter utvärderade.")
        return "\n".join(lines)



# ============================================================
# L00 – CASE INTEGRITY CONTROL
# ============================================================

class L00_CASE_INTEGRITY(_SFBaseLager):
    """
    Granskar aktens fullständighet: bortfall av handlingar, osignerade
    journalanteckningar och brister i diarieföringen.
    Rättskällor: 110:13 SFB, 27 § FL.  Rättssäkerhetspåverkan: MYCKET HÖG.
    """
    LAGER_KOD = "L00"
    LAGERNAMN = "CASE INTEGRITY"
    RÄTTSKÄLLOR = ["110 kap. 13 § SFB", "27 § FL"]

    # Signalord som indikerar dokumentationsbrister (osignerad/journal)
    OREGELBUNDENHET_SIGNALS = [
        r"\bosignerad\b", r"\bsaknar\s+signatur\b", r"\bej\s+signerad\b",
        r"\bsaknas\b", r"\bbortfall\b", r"\bej\s+diarieförd\b",
        r"\bofullständig\s+akt\b", r"\bregistrering\s+saknas\b",
    ]

    def run(self, case_state) -> List[SFLagerFinding]:
        text = self._text(case_state)

        # Kontrollpunkt 1: Är akten komplett?
        saknas = [s for s in self.OREGELBUNDENHET_SIGNALS
                  if re.search(s, text, re.IGNORECASE)]
        if saknas:
            self._add("Aktens fullständighet", "AVVIKELSE",
                      "110 kap. 13 § SFB",
                      "Indikation på bortfall/osignerad handling: "
                      + ", ".join(saknas))
        else:
            self._add("Aktens fullständighet", "OK",
                      "110 kap. 13 § SFB",
                      "Inga brister i aktens fullständighet identifierade.")

        # Kontrollpunkt 2: Är journalanteckningar signerade?
        if re.search(r"\bosignerad\b|\bsaknar\s+signatur\b",
                     text, re.IGNORECASE):
            self._add("Journalanteckningar signerade", "AVVIKELSE",
                      "110 kap. 13 § SFB",
                      "Osignerad journalanteckning identifierad.")
        else:
            self._add("Journalanteckningar signerade", "OK",
                      "110 kap. 13 § SFB",
                      "Inga osignerade journalanteckningar identifierade.")

        # Kontrollpunkt 3: Är diarieföringen korrekt och fullständig?
        if re.search(r"\bej\s+diarieförd\b|\bregistrering\s+saknas\b",
                     text, re.IGNORECASE):
            self._add("Diarieföring", "AVVIKELSE", "27 § FL",
                      "Brist i diarieföring/registrering identifierad.")
        else:
            self._add("Diarieföring", "OK", "27 § FL",
                      "Inga brister i diarieföringen identifierade.")

        # Kontrollpunkt 4: Finns alla inkomna handlingar registrerade?
        if re.search(r"\bbortfall\b|\bsaknas\b", text, re.IGNORECASE):
            self._add("Inkomna handlingar registrerade", "AVVIKELSE",
                      "27 § FL",
                      "Möjligt bortfall av inkommen handling.")
        return self.findings

# ============================================================
# L01 – PRIMARY SOURCE CONTROL (inkl. DFA-KEDJA, RT-CL)
# ============================================================

class L01_PRIMARY_SOURCE(_SFBaseLager):
    """
    Kontrollerar källans autenticitet och medicinska underlag samt
    DFA-kedjan (Diagnos-Funktion-Aktivitet).
    Rättskällor: 27:25 SFB, HFD 2018 ref. 51.  Rättssäkerhetspåverkan: KRITISK.
    """
    LAGER_KOD = "L01"
    LAGERNAMN = "PRIMARY SOURCE"
    RÄTTSKÄLLOR = ["27 kap. 25 § SFB", "HFD 2018 ref. 51"]

    # Signalord per DFA-led (RT-CL)
    DIAGNOS_SIGNALS = [
        r"\bdiagnos\b", r"\bdiagnosticerad\b", r"\bsjukdom\b",
        r"\båkomma\b", r"\bbesvär\b", r"\bdiagnos\s+enligt\b",
    ]
    FUNKTION_SIGNALS = [
        r"\bfunktionsnedsättning\b", r"\bfunktion\b",
        r"\bnedsatt\s+funktion\b", r"\brörlighet\b", r"\bstyrka\b",
        r"\bkänsel\b", r"\bkoordination\b",
    ]
    AKTIVITET_SIGNALS = [
        r"\baktivitetsbegränsning\b", r"\barbetsförmåga\b",
        r"\bkan\s+inte\s+arbeta\b", r"\boförmåga\s+att\b",
        r"\bbegränsar\b", r"\barbetsuppgifter\b",
    ]

    FORMKRÄVS_AVVIKELSE_SIGNALS = [
        r"\bsaknar\s+formkrav\b", r"\bintyget\s+uppfyller\s+inte\b",
        r"\bogiltigt\s+läkarintyg\b", r"\bsaknar\s+stöd\s+i\s+lag\b",
        r"\botillåten\s+begränsning\b", r"\bintern\s+rådgivare\b",
    ]

    @classmethod
    def analysera_dfa(cls, text: str) -> Dict[str, str]:
        """RT-CL: bedömer närvaro av varje DFA-led mot medicinska underlag."""
        d = "DIAGNOS" if re.search("|".join(cls.DIAGNOS_SIGNALS),
                                   text, re.IGNORECASE) else "SAKNAS"
        f = "FUNKTION" if re.search("|".join(cls.FUNKTION_SIGNALS),
                                    text, re.IGNORECASE) else "SAKNAS"
        a = "AKTIVITET" if re.search("|".join(cls.AKTIVITET_SIGNALS),
                                     text, re.IGNORECASE) else "SAKNAS"
        return {"Diagnos": d, "Funktionsnedsättning": f,
                "Aktivitetsbegränsning": a}

    def run(self, case_state) -> List[SFLagerFinding]:
        text = self._text(case_state)

        # Kontrollpunkt 1: Uppfyller läkarintyget formkraven?
        if re.search("|".join(self.FORMKRÄVS_AVVIKELSE_SIGNALS),
                     text, re.IGNORECASE):
            self._add("Läkarintygets formkrav", "AVVIKELSE",
                      "27 kap. 25 § SFB",
                      "Möjlig brist i läkarintygets formkrav identifierad.")
        else:
            self._add("Läkarintygets formkrav", "OK",
                      "27 kap. 25 § SFB",
                      "Inga tecken på formkravsbrist.")

        # Kontrollpunkt 2: Otillåtna begränsningar i fri bevisföring?
        if re.search(r"\botillåten\s+begränsning\b|\bsaknar\s+stöd\s+i\s+lag\b",
                     text, re.IGNORECASE):
            self._add("Begränsningar i fri bevisföring", "AVVIKELSE",
                      "27 kap. 25 § SFB",
                      "Indikation på otillåten begränsning av bevisföring.")
        else:
            self._add("Begränsningar i fri bevisföring", "OK",
                      "27 kap. 25 § SFB",
                      "Inga otillåtna begränsningar identifierade.")

        # Kontrollpunkt 3: Behandlande läkare vs intern rådgivare?
        if re.search(r"\bintern\s+rådgivare\b", text, re.IGNORECASE):
            self._add("Behandlande läkare vs intern rådgivare", "AVVIKELSE",
                      "HFD 2018 ref. 51",
                      "Intern rådgivare förekommer – kontrast mot "
                      "behandlande läkare kräver granskning.")
        else:
            self._add("Behandlande läkare vs intern rådgivare", "OK",
                      "HFD 2018 ref. 51",
                      "Ingen intern rådgivarkontrast identifierad.")

        # Kontrollpunkt 4: DFA-kedja (RT-CL)
        dfa = self.analysera_dfa(text)
        saknade = [k for k, v in dfa.items() if v == "SAKNAS"]
        if saknade:
            self._add("DFA-kedja (Diagnos-Funktion-Aktivitet)", "AVVIKELSE",
                      "HFD 2018 ref. 51",
                      "DFA-kedjan ofullständig – saknar: "
                      + ", ".join(saknade)
                      + ". Verifieras mot medicinska underlag; ej absolut "
                      "lagkrav – granskning krävs (RT-CL).")
        else:
            self._add("DFA-kedja (Diagnos-Funktion-Aktivitet)", "OK",
                      "HFD 2018 ref. 51",
                      "DFA-kedjan fullständig: "
                      + ", ".join(f"{k}={v}" for k, v in dfa.items()) + ".")
        return self.findings


# ============================================================
# L02 – AUDIO / VIDEO FORENSICS (myndighetsspecifik)
# ============================================================

class L02_AUDIO_FORENSICS_FK(_SFBaseLager):
    """
    Analyserar transkriptioner av muntlig kommunikation mellan myndighet
    och enskild. Identifierar bemötandefel, maktspråk eller muntliga beslut
    som ej dokumenterats korrekt.
    Rättskälla: 27 § FL.  Rättssäkerhetspåverkan: MEDEL.
    """
    LAGER_KOD = "L02"
    LAGERNAMN = "AUDIO FORENSICS FK"
    RÄTTSKÄLLOR = ["27 § FL"]

    MAKTSPRÅK_SIGNALS = [
        r"\bmaktspråk\b", r"\botillbörlig\s+påverkan\b",
        r"\bhot\b", r"\butpressning\b", r"\bpressa\b",
    ]
    MUNTLIGT_BESLUT_SIGNALS = [
        r"\bmuntligt\s+beslut\b", r"\bavslog\s+muntligt\b",
        r"\bmuntligen\b.*\bavslag\b",
    ]
    TRANSCRIPTION_AVVIKELSE_SIGNALS = [
        r"\btranskriptionen\s+stämmer\s+inte\b",
        r"\bavvikelse\s+i\s+transkription\b",
        r"\bfelaktig\s+transkription\b",
    ]

    def run(self, case_state) -> List[SFLagerFinding]:
        text = self._text(case_state)

        # Kontrollpunkt 1: Muntliga uppgifter dokumenterade (27 § FL)?
        if re.search("|".join(self.MUNTLIGT_BESLUT_SIGNALS),
                     text, re.IGNORECASE):
            self._add("Muntliga uppgifter dokumenterade", "AVVIKELSE",
                      "27 § FL",
                      "Muntligt beslut/uppgift kan sakna skriftlig "
                      "dokumentation.")
        else:
            self._add("Muntliga uppgifter dokumenterade", "OK", "27 § FL",
                      "Inga muntliga beslut utan dokumentation identifierade.")

        # Kontrollpunkt 2: Maktspråk eller otillbörlig påverkan?
        if re.search("|".join(self.MAKTSPRÅK_SIGNALS), text, re.IGNORECASE):
            self._add("Maktspråk / otillbörlig påverkan", "AVVIKELSE",
                      "27 § FL",
                      "Möjligt maktspråk eller otillbörlig påverkan "
                      "identifierad.")
        else:
            self._add("Maktspråk / otillbörlig påverkan", "OK", "27 § FL",
                      "Inget maktspråk identifierat.")

        # Kontrollpunkt 3: Muntliga beslut utan skriftlig dokumentation?
        if re.search(r"\bmuntligt\s+beslut\b", text, re.IGNORECASE):
            self._add("Muntliga beslut skriftligt dokumenterade", "AVVIKELSE",
                      "27 § FL",
                      "Muntligt beslut identifierat – skriftlig "
                      "dokumentation krävs.")
        else:
            self._add("Muntliga beslut skriftligt dokumenterade", "OK",
                      "27 § FL",
                      "Inga odokumenterade muntliga beslut identifierade.")

        # Kontrollpunkt 4: Stämmer transkriptionen med samtalet?
        if re.search("|".join(self.TRANSCRIPTION_AVVIKELSE_SIGNALS),
                     text, re.IGNORECASE):
            self._add("Transkriptionskorrekthet", "AVVIKELSE", "27 § FL",
                      "Avvikelse i transkription identifierad.")
        else:
            self._add("Transkriptionskorrekthet", "OK", "27 § FL",
                      "Inga transkriptionsavvikelser identifierade.")

        return self.findings


# ============================================================
# SAMLAD KÖRNING
# ============================================================

def kör_socialforsakring_lager(case_state, verbose: bool = False
                               ) -> Dict[str, Any]:
    """
    Kör L00–L02 om måltypen är socialförsäkring (RT-CK).
    Returnerar {'aktiverad': bool, 'lager': {kod: [finding, ...]}}.
    """
    result: Dict[str, Any] = {"aktiverad": False, "lager": {}}
    if not is_socialforsakring_case(case_state):
        return result
    result["aktiverad"] = True
    for klass in (L00_CASE_INTEGRITY, L01_PRIMARY_SOURCE,
                  L02_AUDIO_FORENSICS_FK):
        layer = klass(verbose=verbose)
        layer.run(case_state)
        result["lager"][layer.LAGER_KOD] = [f.to_dict() for f in layer.findings]
    return result





def _addera_månader(d, n: int):
    """Adderar n kalendermånader till d, klämmer dagen till sista giltiga
    dag i månlmånaden (t.ex. 31 dec + 2 mån → 28/29 feb, inte ett fel)."""
    import calendar
    from datetime import date as _date
    m = d.month - 1 + n
    år = d.year + m // 12
    månad = m % 12 + 1
    sista_dag = calendar.monthrange(år, månad)[1]
    return _date(år, månad, min(d.day, sista_dag))


def bestäm_processväg(
    har_omprövningsbeslut: bool = False,
    relevant_beslutsdatum=None,
    dagens_datum=None,
    har_dom_i_förvaltningsrätten: bool = False,
) -> Dict[str, Any]:
    """PROCESSVÄGAR (fk-socialforsakring/SKILL.md) — regelbaserad frist-/
    instansbedömning (SFB 113 kap., FPL). Avgör aldrig om talan bör
    föras eller dess utsikter, bara VILKEN väg/frist som gäller."""
    from datetime import date as _date

    if relevant_beslutsdatum is None:
        return {"status": "EJ_KÖRBAR", "skäl": "Inget relevant beslutsdatum angivet."}

    idag = dagens_datum or _date.today()
    frist_datum = _addera_månader(relevant_beslutsdatum, 2)
    frist_utgången = idag > frist_datum

    if har_dom_i_förvaltningsrätten:
        väg = "KAMMARRÄTTEN"
        motivering = (
            "Dom har meddelats i förvaltningsrätten — överklagande till "
            "kammarrätten kräver prövningstillstånd (FPL)."
        )
    elif har_omprövningsbeslut:
        väg = "ÖVERKLAGANDE_FÖRVALTNINGSRÄTTEN"
        motivering = (
            "Omprövningsbeslut föreligger — överklagande sker till "
            "förvaltningsrätten (SFB 113 kap.)."
        )
    else:
        väg = "OMPRÖVNING"
        motivering = (
            "Inget omprövningsbeslut föreligger ännu — begäran om "
            "omprövning ska ges in i första hand (SFB 113 kap.)."
        )

    return {
        "status": "GENOMFÖRD",
        "rekommenderad_väg": väg,
        "frist": frist_datum.isoformat(),
        "frist_utgången": frist_utgången,
        "motivering": motivering,
        "not": "INDIKATIV_ENDAST. Avgör aldrig om talan bör föras eller dess utsikter.",
    }


def run_processväg_if_requested(
    requested: bool = False,
    har_omprövningsbeslut: bool = False,
    relevant_beslutsdatum_str: Optional[str] = None,
    dagens_datum_str: Optional[str] = None,
    har_dom_i_förvaltningsrätten: bool = False,
) -> Dict[str, Any]:
    if not requested:
        return {"status": "EJ_BEGÄRD", "detail": "Processvägsbedömning kräver requested=True."}
    from datetime import date as _date

    def _parse(s):
        return _date.fromisoformat(s) if s else None

    try:
        beslutsdatum = _parse(relevant_beslutsdatum_str)
        dagens_datum = _parse(dagens_datum_str)
    except ValueError as e:
        return {"status": "EJ_KÖRBAR", "skäl": f"Ogiltigt datumformat: {e}"}

    return bestäm_processväg(
        har_omprövningsbeslut=har_omprövningsbeslut,
        relevant_beslutsdatum=beslutsdatum,
        dagens_datum=dagens_datum,
        har_dom_i_förvaltningsrätten=har_dom_i_förvaltningsrätten,
    )

