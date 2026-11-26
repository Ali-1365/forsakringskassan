"""Obligatorisk verifieringsgrind före juridisk output (steg 20).

Bindande beslut (anti_shortcut_policy.md PART III): noll procents feltolerans.
Varje juridiskt påstående i ett utdata (lagrum, SFS-nummer, praxis) stäms av
ONLINE mot officiell källa innan utdatat får lämna systemet:
  * lag/SFS  -> data.riksdagen.se (Riksdagens öppna data, doktyp=sfs)
  * praxis   -> Legal Data Hunter /v1/resolve (nyckel via os.getenv)
Varje påstående körs också genom legal_source_chain (källkedjan) med den
hämtade exakta texten som retrieval-evidens.

Utfall (grindstatus):
  VERIFIERAD                   alla påståenden belagda -> utdata släpps
  INGET_JURIDISKT_PÅSTÅENDE    inget att verifiera -> utdata släpps
  HARD_STOP                    minst ett påstående är EJ BELAGT i officiell
                               källa (finns inte, paragrafen saknas, lagen inte
                               i kraft vid datumet, förkortning ej entydig).
                               Terminal domänspärr: utdata blockeras.
  FAILED                       verifieringen kunde inte genomföras av TEKNISKT
                               skäl (nätverk, HTTP-fel, nyckel saknas). Utdata
                               blockeras (fail closed) med exakt felorsak.
OKLAR är inget tillåtet slutläge: ett påstående är antingen VERIFIERAT,
EJ_BELAGT (HARD_STOP) eller blockerat av ett rapporterat tekniskt fel (FAILED).
FAILED har företräde framför HARD_STOP eftersom ett tekniskt fel innebär att
övriga påståenden inte kunnat prövas fullt ut.
Ingen juridisk data hittas på här: förkortningar löses ENDAST via
config/lagforkortningar_sfs.yaml och varje upplösning prövas mot riksdagen.
"""
from __future__ import annotations

import datetime
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

RIKSDAGEN_DOK = "https://data.riksdagen.se/dokument/{dok_id}.text"
RIKSDAGEN_LISTA = "https://data.riksdagen.se/dokumentlista/?sok={q}&doktyp=sfs&utformat=json&sz=10"
TIMEOUT_S = 20
FÖRSÖK = 3
CACHE_TTL_S = 3600
_PROCESS_CACHE: Dict[str, Tuple[int, str]] = {}
_PROCESS_CACHE_TID: Dict[str, float] = {}
VÄNTAN_S = 1.0

STATUS_VERIFIERAD = "VERIFIERAD"
STATUS_INGET = "INGET_JURIDISKT_PÅSTÅENDE"
STATUS_HARD_STOP = "VARNING"
STATUS_FAILED = "FAILED"
HS_KOD = "HS_VERIFIERINGSGRIND"

_ALIAS_FIL = Path(__file__).resolve().parent.parent / "config" / "lagforkortningar_sfs.yaml"


class TekniskVerifieringsfel(RuntimeError):
    pass


# ── HTTP ──────────────────────────────────────────────────────────────────
def _ssl_kontext():
    """Verifierad TLS mot OS:ets certifikatlager (truststore) eller certifi
    (valfria beroenden). Certifikatkontrollen stängs aldrig av."""
    import importlib.util
    import ssl
    if importlib.util.find_spec("truststore") is not None:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if importlib.util.find_spec("certifi") is not None:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def _urllib_get(url: str) -> Tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "SFCAE-verifieringsgrind/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S, context=_ssl_kontext()) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


# ── Förkortningar (endast ur YAML) ────────────────────────────────────────
def ladda_alias(path: Path = _ALIAS_FIL) -> Dict[str, List[Dict[str, str]]]:
    import yaml
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    ut: Dict[str, List[Dict[str, str]]] = {}
    for abbr, poster in (data.get("forkortningar") or {}).items():
        ut[str(abbr)] = [dict(p) for p in (poster or [])]
    return ut


# ── Extraktion av påståenden ──────────────────────────────────────────────
_ABBR = r"([A-ZÅÄÖ][A-Za-zÅÄÖåäö]{1,9})"
_PAR = r"(\d+\s*[a-z]?)\s*§"
_KAP = r"(\d+)\s*kap\.?\s*"
_RX_ABBR_KAP = re.compile(r"\b" + _ABBR + r"\s+" + _KAP + _PAR)          # SoL 3 kap. 1 §
_RX_KAP_ABBR = re.compile(_KAP + _PAR + r"\s+" + _ABBR + r"\b")           # 3 kap. 1 § SoL
_RX_ABBR_KOLON = re.compile(r"\b" + _ABBR + r"\s+(\d+):(\d+\s?[a-z]?)\b")  # RB 35:1
_RX_ABBR_PAR = re.compile(r"\b" + _ABBR + r"\s+" + _PAR)                 # LVU 3 §
_RX_PAR_ABBR = re.compile(r"(?<!kap\. )(?<!kap )\b" + _PAR + r"\s+" + _ABBR + r"\b")  # 3 § LVU
_RX_SFS = re.compile(r"(?:SFS\s*|Lag\s*\(|Förordning\s*\(|\()((?:1[6-9]|20)\d{2}):(\d{1,4})\b")
_RX_PRAXIS = re.compile(
    r"\b(NJA\s+\d{4}\s+s\.\s*\d+|NJA\s+\d{4}:\d+|HFD\s+\d{4}\s+ref\.\s*\d+|HFD\s+\d{4}:\d+"
    r"|RÅ\s+\d{4}\s+ref\.\s*\d+|(?:mål\s+(?:nr\s+)?)?[TÖB]\s+\d{1,5}-\d{2})\b")


_EJ_LAGFÖRKORTNING = {"SFS", "NJA", "HFD", "RÅ", "AD", "MÖD", "MMD"}


def _är_förkortning(s: str) -> bool:
    if s in _EJ_LAGFÖRKORTNING:
        return False
    # En lagförkortning har minst två versaler (LVU, SoL, BrB, RB). Ord som
    # "Enligt" eller "Vård" är inga förkortningar.
    return sum(1 for c in s if c.isupper()) >= 2


def _norm_par(p: str) -> str:
    return re.sub(r"\s+", " ", p.strip())


def extrahera_påståenden(text: str) -> List[Dict[str, Any]]:
    ut: List[Dict[str, Any]] = []
    sett = set()

    def lägg(d: Dict[str, Any]) -> None:
        nyckel = json.dumps(d, sort_keys=True, ensure_ascii=False)
        if nyckel not in sett:
            sett.add(nyckel)
            ut.append(d)

    upptagna: List[Tuple[int, int]] = []
    for rx, ordning in ((_RX_ABBR_KAP, "akp"), (_RX_KAP_ABBR, "kpa"), (_RX_ABBR_KOLON, "akp")):
        for m in rx.finditer(text or ""):
            if ordning == "akp":
                a, k, p = m.group(1), m.group(2), m.group(3)
            else:
                k, p, a = m.group(1), m.group(2), m.group(3)
            if not _är_förkortning(a):
                continue
            upptagna.append(m.span())
            lägg({"typ": "LAGRUM", "förkortning": a, "kapitel": str(int(k)),
                  "paragraf": _norm_par(p), "citat": m.group(0).strip()})
    for rx, ordning in ((_RX_ABBR_PAR, "ap"), (_RX_PAR_ABBR, "pa")):
        for m in rx.finditer(text or ""):
            if any(s <= m.start() < e for s, e in upptagna):
                continue
            a, p = (m.group(1), m.group(2)) if ordning == "ap" else (m.group(2), m.group(1))
            if not _är_förkortning(a):
                continue
            lägg({"typ": "LAGRUM", "förkortning": a, "kapitel": "",
                  "paragraf": _norm_par(p), "citat": m.group(0).strip()})
    for m in _RX_SFS.finditer(text or ""):
        lägg({"typ": "SFS", "sfs": f"{m.group(1)}:{m.group(2)}", "citat": m.group(0).strip()})
    for m in _RX_PRAXIS.finditer(text or ""):
        lägg({"typ": "PRAXIS", "referens": re.sub(r"^mål\s+(?:nr\s+)?", "", re.sub(r"\s+", " ", m.group(1)).strip()),
              "citat": m.group(0).strip()})
    return ut


# ── Riksdagen ─────────────────────────────────────────────────────────────
class RiksdagenKälla:
    def __init__(self, http_get: Optional[Callable[[str], Tuple[int, str]]] = None):
        self._get = http_get or _urllib_get
        # Riktiga anrop delar en processvid cache (TTL) så att officiell källa
        # inte belastas med samma dokument om och om igen; injicerad http_get
        # (tester) får egen cache.
        self._cache: Dict[str, Tuple[int, str]] = _PROCESS_CACHE if http_get is None else {}

    def _hämta(self, url: str) -> Tuple[int, str]:
        import time as _t
        if self._cache is _PROCESS_CACHE:
            tid = _PROCESS_CACHE_TID.get(url)
            if tid is not None and _t.monotonic() - tid > CACHE_TTL_S:
                _PROCESS_CACHE.pop(url, None)
        if url not in self._cache:
            import time
            fel = ""
            for försök in range(FÖRSÖK):
                try:
                    st, txt = self._get(url)
                except Exception as e:
                    fel = f"nätverksfel mot data.riksdagen.se: {type(e).__name__}: {e}"
                else:
                    if st >= 500 or st == 0 or st == 429:
                        fel = f"data.riksdagen.se svarade HTTP {st} ({url})"
                    else:
                        fel = ""
                        break
                if försök + 1 < FÖRSÖK:
                    time.sleep(VÄNTAN_S * (försök + 1))
            if fel:
                raise TekniskVerifieringsfel(f"{fel} (efter {FÖRSÖK} försök)")
            if st not in (200, 404):
                raise TekniskVerifieringsfel(f"data.riksdagen.se oväntat svar HTTP {st} ({url})")
            self._cache[url] = (st, txt)
            if self._cache is _PROCESS_CACHE:
                _PROCESS_CACHE_TID[url] = _t.monotonic()
        return self._cache[url]

    def författning(self, sfs: str) -> Optional[Dict[str, Any]]:
        år, nr = sfs.split(":")
        url = RIKSDAGEN_DOK.format(dok_id=f"sfs-{år}-{nr}")
        st, txt = self._hämta(url)
        if st == 404 or not txt.strip():
            return None
        if not re.search(r"SFS nr:\s*" + re.escape(sfs) + r"\b", txt[:2000]):
            return None
        m = re.search(r"Upphävd:\s*(\d{4}-\d{2}-\d{2})", txt[:2000])
        u = re.search(r"Utfärdad:\s*(\d{4}-\d{2}-\d{2})", txt[:2000])
        return {"url": url, "text": txt, "titel": txt.splitlines()[0].strip(),
                "upphävd": m.group(1) if m else "", "utfärdad": u.group(1) if u else ""}

    def ändrings_sfs_finns(self, sfs: str) -> Optional[Dict[str, Any]]:
        """Ändrings-SFS saknar ofta eget dokument: belagd om en grundförfattning
        hos riksdagen innehåller "(år:nr)" i sin text."""
        url = RIKSDAGEN_LISTA.format(q=urllib.parse.quote(sfs))
        st, txt = self._hämta(url)
        if st == 404 or not txt.strip():
            return None
        try:
            dok = (json.loads(txt).get("dokumentlista") or {}).get("dokument") or []
        except ValueError:
            raise TekniskVerifieringsfel("data.riksdagen.se dokumentlista: ogiltig JSON") from None
        if isinstance(dok, dict):
            dok = [dok]
        for d in dok[:10]:
            did = str(d.get("id") or "")
            if not did.startswith("sfs-"):
                continue
            st2, t2 = self._hämta(RIKSDAGEN_DOK.format(dok_id=did))
            if st2 == 200 and f"({sfs})" in t2:
                u = re.search(r"Utfärdad:\s*(\d{4}-\d{2}-\d{2})", t2[:2000])
                return {"url": RIKSDAGEN_DOK.format(dok_id=did), "utfärdad": u.group(1) if u else "",
                        "titel": t2.splitlines()[0].strip() if t2 else did, "text": t2}
        return None


def _paragraf_finns(text: str, kapitel: str, paragraf: str) -> Optional[str]:
    """Returnerar paragrafens första rad om den finns, annars None."""
    par = re.escape(paragraf).replace(r"\ ", r"\s*")
    rx_par = re.compile(r"(?m)^\s*" + par + r"\s*§\s+[A-ZÅÄÖ\"”].*$")
    if kapitel:
        m = re.search(r"(?m)^\s*" + kapitel + r"\s*kap\.\s+[A-ZÅÄÖ]", text)
        if not m:
            return None
        nästa = re.search(r"(?m)^\s*" + str(int(kapitel) + 1) + r"\s*kap\.\s+[A-ZÅÄÖ]",
                          text[m.end():])
        del_text = text[m.end(): m.end() + nästa.start()] if nästa else text[m.end():]
    else:
        del_text = text
    m2 = rx_par.search(del_text)
    return m2.group(0).strip() if m2 else None


def _välj_sfs(poster: List[Dict[str, str]], datum: datetime.date) -> Optional[str]:
    for p in poster:
        fr = p.get("giltig_fran") or ""
        ti = p.get("giltig_till") or ""
        if fr and datum < datetime.date.fromisoformat(fr):
            continue
        if ti and datum >= datetime.date.fromisoformat(ti):
            continue
        return p.get("sfs")
    return None


# ── Grinden ───────────────────────────────────────────────────────────────
class Verifieringsgrind:
    def __init__(self, http_get: Optional[Callable[[str], Tuple[int, str]]] = None,
                 ldh_client: Any = None, alias: Optional[Dict[str, List[Dict[str, str]]]] = None,
                 tillåt_nätverk: bool = True):
        self.riksdagen = RiksdagenKälla(http_get)
        self._ldh = ldh_client
        self._alias = alias
        self.tillåt_nätverk = tillåt_nätverk

    def _ldh_klient(self):
        if self._ldh is None:
            from legal_data_hunter_client import LegalDataHunterClient
            self._ldh = LegalDataHunterClient()
        return self._ldh

    def _verifiera_lagrum(self, p: Dict[str, Any], datum: datetime.date) -> Dict[str, Any]:
        if self._alias is None:
            self._alias = ladda_alias()
        poster = self._alias.get(p["förkortning"])
        if not poster:
            return {"utfall": "EJ_BELAGT",
                    "skäl": f"förkortningen {p['förkortning']} saknas i "
                            "config/lagforkortningar_sfs.yaml (ej entydigt upplösbar)"}
        sfs = _välj_sfs(poster, datum)
        if not sfs:
            return {"utfall": "EJ_BELAGT",
                    "skäl": f"{p['förkortning']}: ingen författning gällde {datum.isoformat()}"}
        f = self.riksdagen.författning(sfs)
        if f is None:
            return {"utfall": "EJ_BELAGT", "sfs": sfs,
                    "skäl": f"SFS {sfs} finns inte hos data.riksdagen.se"}
        if f["upphävd"] and datum >= datetime.date.fromisoformat(f["upphävd"]):
            return {"utfall": "EJ_BELAGT", "sfs": sfs, "källa": f["url"],
                    "skäl": f"{f['titel']} upphävd {f['upphävd']} (prövningsdatum {datum})"}
        rad = _paragraf_finns(f["text"], p.get("kapitel", ""), p["paragraf"])
        if not rad:
            kap = f"{p['kapitel']} kap. " if p.get("kapitel") else ""
            return {"utfall": "EJ_BELAGT", "sfs": sfs, "källa": f["url"],
                    "skäl": f"{kap}{p['paragraf']} § finns inte i {f['titel']}"}
        return {"utfall": "VERIFIERAT", "sfs": sfs, "källa": f["url"], "titel": f["titel"],
                "lydelse_början": rad[:200], "exakt_text": f["text"],
                "giltig_från": f["utfärdad"], "giltig_till": f["upphävd"]}

    def _verifiera_sfs(self, p: Dict[str, Any]) -> Dict[str, Any]:
        f = self.riksdagen.författning(p["sfs"])
        if f is not None:
            return {"utfall": "VERIFIERAT", "källa": f["url"], "titel": f["titel"],
                    "exakt_text": f["text"], "giltig_från": f["utfärdad"],
                    "giltig_till": f["upphävd"]}
        a = self.riksdagen.ändrings_sfs_finns(p["sfs"])
        if a is not None:
            return {"utfall": "VERIFIERAT", "källa": a["url"],
                    "titel": f"ändrings-SFS ({p['sfs']}) i {a['titel']}", "exakt_text": a["text"],
                    "giltig_från": a["utfärdad"], "giltig_till": ""}
        return {"utfall": "EJ_BELAGT", "skäl": f"SFS {p['sfs']} hittas inte hos data.riksdagen.se"}

    def _verifiera_praxis(self, p: Dict[str, Any]) -> Dict[str, Any]:
        from legal_data_hunter_client import LDHTekniskt
        try:
            svar = self._ldh_klient().resolve(p["referens"], hint_country="SE", hint_type="case_law")
        except LDHTekniskt as e:
            raise TekniskVerifieringsfel(str(e)) from None
        träffar: List[Dict[str, Any]] = []
        if isinstance(svar, list):
            träffar = [t for t in svar if isinstance(t, dict)]
        elif isinstance(svar, dict):
            for k in ("results", "matches", "documents", "data"):
                if isinstance(svar.get(k), list):
                    träffar = [t for t in svar[k] if isinstance(t, dict)]
                    break
            if not träffar and svar.get("source_id"):
                träffar = [svar]
            mt = svar.get("match_type")
            if mt and träffar:
                for t in träffar:
                    t.setdefault("match_type", mt)
        exakta = [t for t in träffar if str(t.get("match_type", "")).lower() == "exact"]
        siffror = re.findall(r"\d+", p["referens"])
        for t in exakta:
            blob = json.dumps(t, ensure_ascii=False)
            if all(s in blob for s in siffror):
                return {"utfall": "VERIFIERAT", "källa": t.get("url") or
                        f"legaldatahunter:{t.get('source')}/{t.get('source_id')}",
                        "titel": t.get("title") or "", "exakt_text": t.get("text") or blob,
                        "giltig_från": str(t.get("date") or t.get("decision_date") or "")[:10],
                        "giltig_till": ""}
        return {"utfall": "EJ_BELAGT",
                "skäl": f"{p['referens']}: ingen exakt träff i Legal Data Hunter "
                        f"({len(träffar)} träffar, {len(exakta)} exakta)"}

    def verifiera_text(self, text: str, relevant_date: str = "") -> Dict[str, Any]:
        return self.verifiera_påståenden(extrahera_påståenden(text), relevant_date)

    def verifiera_påståenden(self, påståenden: List[Dict[str, Any]],
                             relevant_date: str = "") -> Dict[str, Any]:
        try:
            datum = (datetime.date.fromisoformat(relevant_date[:10]) if relevant_date
                     else datetime.date.today())
        except ValueError:
            # Ogiltigt prövningsdatum ersätts aldrig tyst: utdata blockeras.
            return {"grindstatus": STATUS_FAILED, "output_släppt": False,
                    "antal": len(påståenden), "verifierade": 0, "ej_belagda": 0,
                    "tekniska_fel": [f"ogiltigt relevant_date {relevant_date!r} (ÅÅÅÅ-MM-DD krävs)"],
                    "påståenden": påståenden, "prövningsdatum": ""}
        if not påståenden:
            return {"grindstatus": STATUS_INGET, "output_släppt": True, "antal": 0,
                    "påståenden": [], "prövningsdatum": datum.isoformat()}
        if not self.tillåt_nätverk:
            return self._blockera_tekniskt(påståenden, datum,
                                           "nätverksverifiering avstängd (tillåt_nätverk=False) — "
                                           "juridisk output kan inte verifieras och blockeras")
        resultat: List[Dict[str, Any]] = []
        tekniska: List[str] = []
        for p in påståenden:
            try:
                if p["typ"] == "LAGRUM":
                    r = self._verifiera_lagrum(p, datum)
                elif p["typ"] == "SFS":
                    r = self._verifiera_sfs(p)
                else:
                    r = self._verifiera_praxis(p)
            except TekniskVerifieringsfel as e:
                r = {"utfall": "TEKNISKT_FEL", "fel": str(e)}
                tekniska.append(f"{p.get('citat')}: {e}")
            resultat.append({**p, **r})
        kedja = _kör_källkedja(resultat, datum)
        for r in resultat:
            r.pop("exakt_text", None)
            if r["utfall"] == "VERIFIERAT" and r.get("källkedja_status") != "VERIFIED":
                # Källkedjan (legal_source_chain) är bindande: ett påstående
                # som inte klarar kedjan är inte belagt.
                r["utfall"] = "EJ_BELAGT"
                r["skäl"] = "källkedjan blockerade: " + str(r.get("källkedja_skäl") or "")
        ej = [r for r in resultat if r["utfall"] == "EJ_BELAGT"]
        if tekniska:
            status = STATUS_FAILED
        elif ej:
            status = STATUS_HARD_STOP
        else:
            status = STATUS_VERIFIERAD
        ut = {"grindstatus": status, "output_släppt": status == STATUS_VERIFIERAD,
              "antal": len(resultat),
              "verifierade": sum(1 for r in resultat if r["utfall"] == "VERIFIERAT"),
              "ej_belagda": len(ej), "tekniska_fel": tekniska,
              "påståenden": resultat, "källkedja": kedja,
              "prövningsdatum": datum.isoformat()}
        if status == STATUS_HARD_STOP:
            ut["hard_stop_kod"] = HS_KOD
        return ut

    def _blockera_tekniskt(self, påståenden, datum, fel: str) -> Dict[str, Any]:
        return {"grindstatus": STATUS_FAILED, "output_släppt": False, "antal": len(påståenden),
                "verifierade": 0, "ej_belagda": 0, "tekniska_fel": [fel],
                "påståenden": [{**p, "utfall": "TEKNISKT_FEL", "fel": fel} for p in påståenden],
                "prövningsdatum": datum.isoformat()}


def _kör_källkedja(resultat: List[Dict[str, Any]], datum: datetime.date) -> Dict[str, Any]:
    """Varje påstående genom legal_source_chain med verklig retrieval-evidens."""
    try:
        from legal_source_chain import LegalSourceChainEngine
    except Exception as e:
        return {"status": "FEL", "fel": f"{type(e).__name__}: {e}"}
    motor = LegalSourceChainEngine(
        register_availability={"SFS": True, "RÄTTSPRAXIS": True},
        external_retrieval_available=True)
    poster = []
    for r in resultat:
        if r["utfall"] != "VERIFIERAT":
            continue
        rec = motor.process_legal_question(
            legal_question=r.get("citat", ""),
            source_type="PREJUDIKAT" if r["typ"] == "PRAXIS" else "LAG",
            relevant_date=datum.isoformat(),
            effective_from=r.get("giltig_från", ""),
            effective_to=r.get("giltig_till", ""),
            source_url=r.get("källa", ""),
            source_identifier=r.get("sfs") or r.get("referens") or "",
            exact_text=r.get("exakt_text", ""),
            retrieval_evidence=r.get("källa", ""),
            candidate={"authority_level": "PREJUDIKATIV" if r["typ"] == "PRAXIS" else "BINDANDE"},
        ).to_dict()
        rec.pop("exact_text", None)
        r["källkedja_status"] = rec.get("verification_status")
        r["källkedja_skäl"] = rec.get("blocking_reason")
        poster.append({"source_identifier": rec.get("source_identifier"),
                       "verification_status": rec.get("verification_status"),
                       "source_hash": rec.get("source_hash"),
                       "blocking_reason": rec.get("blocking_reason")})
    return {"status": "GENOMFÖRD", "poster": poster}


def spärrat_svar(grind: Dict[str, Any], komponent: str) -> Dict[str, Any]:
    """Det enda som får lämna systemet när grinden blockerar."""
    st = grind["grindstatus"]
    return {
        "status": st,
        "kod": grind.get("hard_stop_kod") if st == STATUS_HARD_STOP else "FAILED_VERIFIERING",
        "komponent": komponent,
        "output_blockerad": True,
        "skäl": ("juridiskt påstående ej belagt i officiell källa" if st == STATUS_HARD_STOP
                 else "verifiering mot officiell källa kunde inte genomföras (tekniskt fel)"),
        "verifieringsgrind": grind,
    }


def grinda_utdata(resultat: Any, komponent: str, relevant_date: str = "",
                  grind: Optional[Verifieringsgrind] = None) -> Any:
    """Kör grinden över hela utdatats text. Släpper utdatat (med grindrapport)
    eller returnerar ett spärrat svar."""
    g = grind or Verifieringsgrind()
    text = json.dumps(resultat, ensure_ascii=False, default=str)
    rapport = g.verifiera_text(text, relevant_date)
    if rapport["output_släppt"]:
        if isinstance(resultat, dict):
            return {**resultat, "verifieringsgrind": rapport}
        return {"resultat": resultat, "verifieringsgrind": rapport}
    return spärrat_svar(rapport, komponent)
