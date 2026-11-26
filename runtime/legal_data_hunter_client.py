"""Legal Data Hunter REST-klient (steg 20).

Endpoint enligt leverantörens dokumentation (https://legaldatahunter.com/llms.txt,
refererad i config/legal_data_hunter_se_config.json): bas https://legaldatahunter.com/v1,
POST /resolve, POST /search, GET /documents/{source}/{source_id}.

Nyckeln läses ENDAST via os.getenv(LDH_ENV_VAR). Den hårdkodas aldrig, loggas
aldrig och skrivs aldrig ut — inte heller i felmeddelanden.
Saknad nyckel eller nätverksfel är ett TEKNISKT fel (LDHTekniskt); ett
svar utan träff är inte ett tekniskt fel utan ett sakutfall.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional

LDH_ENV_VAR = "LEGAL_DATA_HUNTER_API_KEY"
_STANDARD_BAS = "https://legaldatahunter.com/v1"
TIMEOUT_S = 20


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


class LDHTekniskt(RuntimeError):
    """Tekniskt fel mot Legal Data Hunter (nyckel saknas, nätverk, HTTP 5xx/401/429)."""


def _bas_url() -> str:
    """Bas-URL ur config/legal_data_hunter_se_config.json (website + /v1)."""
    cfg = Path(__file__).resolve().parent.parent / "config" / "legal_data_hunter_se_config.json"
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        site = str(data.get("website") or "").rstrip("/")
        if site.startswith("https://"):
            return site + "/v1"
    except (OSError, ValueError):
        pass
    return _STANDARD_BAS


def nyckel_finns() -> bool:
    return bool((os.getenv(LDH_ENV_VAR) or "").strip())


class LegalDataHunterClient:
    def __init__(self, transport: Optional[Callable[..., Dict[str, Any]]] = None,
                 bas_url: Optional[str] = None):
        # transport(method, url, headers, body) -> {"status": int, "json": obj}
        # injiceras i tester; standard är urllib.
        self._transport = transport or self._urllib_transport
        self._bas = (bas_url or _bas_url()).rstrip("/")

    @staticmethod
    def _urllib_transport(method: str, url: str, headers: Dict[str, str],
                          body: Optional[bytes]) -> Dict[str, Any]:
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S, context=_ssl_kontext()) as r:
                return {"status": r.status, "json": json.loads(r.read().decode("utf-8") or "null")}
        except urllib.error.HTTPError as e:
            return {"status": e.code, "json": None}

    def _anrop(self, method: str, path: str, payload: Optional[Dict] = None) -> Any:
        key = (os.getenv(LDH_ENV_VAR) or "").strip()
        if not key:
            raise LDHTekniskt(f"miljövariabeln {LDH_ENV_VAR} saknas — sätt den för att "
                              "verifiera praxis via Legal Data Hunter")
        headers = {"Authorization": "Bearer " + key, "Accept": "application/json",
                   "User-Agent": "SFCAE-verifieringsgrind/1.0"}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        try:
            svar = self._transport(method, self._bas + path, headers, body)
        except LDHTekniskt:
            raise
        except Exception as e:  # nätverk/timeout/DNS
            raise LDHTekniskt(f"nätverksfel mot Legal Data Hunter: {type(e).__name__}") from None
        st = int(svar.get("status") or 0)
        if st in (401, 403):
            raise LDHTekniskt(f"Legal Data Hunter avvisade nyckeln (HTTP {st})")
        if st == 429:
            raise LDHTekniskt("Legal Data Hunter: kvoten är slut (HTTP 429)")
        if st >= 500 or st == 0:
            raise LDHTekniskt(f"Legal Data Hunter: serverfel (HTTP {st})")
        if st == 404:
            return None
        if st >= 400:
            raise LDHTekniskt(f"Legal Data Hunter: oväntat svar (HTTP {st})")
        return svar.get("json")

    def resolve(self, reference: str, hint_country: str = "SE",
                hint_type: Optional[str] = None) -> Any:
        p: Dict[str, Any] = {"reference": reference, "hint_country": hint_country}
        if hint_type:
            p["hint_type"] = hint_type
        return self._anrop("POST", "/resolve", p)

    def get_document(self, source: str, source_id: str) -> Any:
        from urllib.parse import quote
        return self._anrop("GET", f"/documents/{quote(source, safe='')}/{quote(source_id, safe='')}")
