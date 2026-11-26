from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

from dynamic_pipeline import OrchestrationState, step_mode
from hard_stop_las import kedjeavbrott, las_hard_stop_koder, spärrsvar
from legal_text_merge_agent import merge_from_iterable, merge_legal_drafts
from strict_legal_report_generator import generate_strict_legal_report

DEFAULT_OMNI_URL = (os.environ.get("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128").rstrip("/") + ("" if os.environ.get("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128").rstrip("/").endswith("/v1") else "/v1") + "/chat/completions")
DEFAULT_OMNI_MODEL = os.environ.get("OMNIROUTE_MODEL", "auto/best-coding").strip() or "auto/best-coding"
DEFAULT_COMBOS_FILE = Path(__file__).resolve().parent.parent / "combos" / "combo_models.json"
DEFAULT_TESSERACT_CMD = os.environ.get("TESSERACT_CMD", "tesseract").strip() or "tesseract"
DEFAULT_TESSDATA_DIR = os.environ.get("TESSDATA_DIR", "").strip()
DEFAULT_VENV_OCRMYPDF = os.environ.get("OCRMYPDF_EXE", "ocrmypdf").strip() or "ocrmypdf"


def _normalize_codes(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, (list, tuple, set)):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, dict):
        return [str(k).strip() for k, v in raw.items() if v and str(k).strip()]
    return [str(raw).strip()]


def load_combo_models(combos_file: Path = DEFAULT_COMBOS_FILE) -> list[str]:
    fallback = ["min-gratis-kodkedja", "min-kod-kedja", "static-best-reasoning"]
    if not combos_file.is_file():
        return fallback
    data = json.loads(combos_file.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("combos"), list):
        items = [str(x).strip() for x in data["combos"] if str(x).strip()]
        return items or fallback
    if isinstance(data, list):
        items = [str(x).strip() for x in data if str(x).strip()]
        return items or fallback
    return fallback


def configure_ocr_environment(
    *,
    tesseract_cmd: str = DEFAULT_TESSERACT_CMD,
    tessdata_dir: str = DEFAULT_TESSDATA_DIR,
) -> dict[str, Any]:
    tess_path = Path(tesseract_cmd)
    tessdata_path = Path(tessdata_dir)
    resolved_tesseract = str(tess_path) if tess_path.is_file() else (shutil.which("tesseract") or str(tess_path))

    if tessdata_path.is_dir():
        os.environ["TESSDATA_PREFIX"] = str(tessdata_path)

    pytesseract_configured = False
    try:
        import pytesseract  # type: ignore

        pytesseract.pytesseract.tesseract_cmd = resolved_tesseract
        pytesseract_configured = True
    except ImportError:
        pytesseract_configured = False

    venv_ocrmypdf = Path(DEFAULT_VENV_OCRMYPDF)
    resolved_ocrmypdf = (
        str(venv_ocrmypdf)
        if venv_ocrmypdf.is_file()
        else (shutil.which("ocrmypdf") or str(venv_ocrmypdf))
    )

    return {
        "tesseract_cmd": resolved_tesseract,
        "tesseract_exists": Path(resolved_tesseract).is_file(),
        "tessdata_dir": str(tessdata_path),
        "tessdata_exists": tessdata_path.is_dir(),
        "pytesseract_configured": pytesseract_configured,
        "ocrmypdf_cmd": resolved_ocrmypdf,
        "ocrmypdf_exists": Path(resolved_ocrmypdf).is_file(),
    }


def run_ocr_check(
    *,
    tesseract_cmd: str = DEFAULT_TESSERACT_CMD,
    tessdata_dir: str = DEFAULT_TESSDATA_DIR,
) -> dict[str, Any]:
    info = configure_ocr_environment(tesseract_cmd=tesseract_cmd, tessdata_dir=tessdata_dir)
    version_out = ""
    langs_out: list[str] = []
    if info["tesseract_exists"]:
        v_cp = subprocess.run(
            [info["tesseract_cmd"], "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        version_out = (v_cp.stdout or v_cp.stderr or "").strip().splitlines()[0] if (v_cp.stdout or v_cp.stderr) else ""

        l_cp = subprocess.run(
            [info["tesseract_cmd"], "--list-langs"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        raw_langs = (l_cp.stdout or "").splitlines()
        langs_out = [line.strip() for line in raw_langs[1:] if line.strip()] if len(raw_langs) > 1 else [
            line.strip() for line in raw_langs if line.strip()
        ]

    info["version"] = version_out
    info["languages"] = langs_out
    return info


def run_ocr_image(
    image_path: str,
    *,
    lang: str = "swe",
    tesseract_cmd: str = DEFAULT_TESSERACT_CMD,
    tessdata_dir: str = DEFAULT_TESSDATA_DIR,
) -> dict[str, Any]:
    src = Path(image_path)
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"Bildfil saknas: {src}")

    info = configure_ocr_environment(tesseract_cmd=tesseract_cmd, tessdata_dir=tessdata_dir)
    text = ""
    engine_used = "tesseract_cli"

    if info["pytesseract_configured"]:
        try:
            from PIL import Image  # type: ignore
            import pytesseract  # type: ignore

            with Image.open(src) as img:
                text = pytesseract.image_to_string(img, lang=lang)
            engine_used = "pytesseract"
        except Exception:
            engine_used = "tesseract_cli"

    if engine_used == "tesseract_cli":
        if not info["tesseract_exists"]:
            raise FileNotFoundError(f"Tesseract hittades inte: {info['tesseract_cmd']}")
        cp = subprocess.run(
            [info["tesseract_cmd"], str(src), "stdout", "-l", lang],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        text = cp.stdout

    cleaned = text.strip()
    return {
        "image_path": str(src),
        "lang": lang,
        "engine": engine_used,
        "text": cleaned,
        "char_count": len(cleaned),
    }


def run_ocr_pdf(
    input_pdf: str,
    output_pdf: str,
    *,
    lang: str = "swe",
    tesseract_cmd: str = DEFAULT_TESSERACT_CMD,
    tessdata_dir: str = DEFAULT_TESSDATA_DIR,
) -> dict[str, Any]:
    src = Path(input_pdf)
    dst = Path(output_pdf)
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"Indata-PDF saknas: {src}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    info = configure_ocr_environment(tesseract_cmd=tesseract_cmd, tessdata_dir=tessdata_dir)
    if not info["ocrmypdf_exists"]:
        raise FileNotFoundError(f"ocrmypdf hittades inte: {info['ocrmypdf_cmd']}")

    cp = subprocess.run(
        [info["ocrmypdf_cmd"], "-l", lang, str(src), str(dst)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return {
        "input_pdf": str(src),
        "output_pdf": str(dst),
        "lang": lang,
        "ocrmypdf_cmd": info["ocrmypdf_cmd"],
        "output_exists": dst.is_file(),
        "output_size": dst.stat().st_size if dst.is_file() else 0,
        "stdout": (cp.stdout or "").strip(),
    }


def _resolve_omni_api_key() -> str:
    env_key = (
        os.environ.get("OMNIROUTE_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()
    if env_key:
        return env_key

    candidates = [
        Path.home() / ".omniroute" / ".env",
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    for candidate in candidates:
        if candidate.is_file():
            for line in candidate.read_text(encoding="utf-8", errors="ignore").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, val = stripped.split("=", 1)
                if key.strip() in {"OMNIROUTE_API_KEY", "OPENAI_API_KEY", "API_KEY"}:
                    return val.strip().strip("'").strip('"')
    return ""


def query_omniroute(
    prompt_text: str,
    *,
    omni_url: str = DEFAULT_OMNI_URL,
    model: str = DEFAULT_OMNI_MODEL,
    timeout: int = 60,
) -> dict[str, Any]:
    api_key = _resolve_omni_api_key()
    resolved_url = (omni_url or DEFAULT_OMNI_URL).strip()
    resolved_model = (model or os.environ.get("OMNIROUTE_MODEL") or DEFAULT_OMNI_MODEL or "auto/best-coding").strip()

    headers = {"Content-Type": "application/json; charset=utf-8"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": resolved_model,
        "temperature": 0,
        "messages": [
            {"role": "user", "content": prompt_text},
        ],
    }

    req = urllib.request.Request(
        resolved_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OmniRoute HTTP {exc.code} mot {resolved_url}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"OmniRoute anrop mot {resolved_url} misslyckades: {exc}") from exc

    content = data["choices"][0]["message"]["content"]
    return {
        "url": resolved_url,
        "model": resolved_model,
        "content": content,
        "raw": data,
    }





def build_verdict(
    text: str,
    *,
    rekvisit: list[str] | None = None,
    mode: str = "JUDGMENT_AUDIT",
    forum: str = "förvaltningsdomstol",
    jurisdiction: str = "Sverige",
) -> dict[str, Any]:
    state = OrchestrationState(
        mode=mode,
        forum=forum,
    )
    state.jurisdiction = jurisdiction
    state.text = text
    step_mode(state)

    existing_flags = getattr(state, "flags", None)
    if existing_flags is None:
        existing_flags = getattr(state, "hard_stops", None)
    flags: list[str] = [str(f).strip() for f in (existing_flags or []) if str(f).strip()]

    req_list = [r.strip() for r in (rekvisit or []) if r and r.strip()]
    if not req_list:
        flags.append("HS11")

    raw_codes = las_hard_stop_koder(flags)
    codes = _normalize_codes(raw_codes) or list(flags)

    raw_abort = kedjeavbrott(flags)
    abort_from_fn = _normalize_codes(raw_abort) if isinstance(raw_abort, (list, tuple, set, dict)) else []
    chain_abort = bool(
        (flags and "CHAIN_ABORT" in flags)
        or bool(raw_abort)
        or any(bool(kedjeavbrott([c])) for c in codes)
    )
    abort_codes = abort_from_fn or [c for c in codes if bool(kedjeavbrott([c]))]

    if chain_abort:
        overall_status = "HARD_STOP"
    elif codes:
        overall_status = "READY_WITH_WARNINGS"
    else:
        overall_status = "READY"

    return {
        "overall_status": overall_status,
        "chain_abort": chain_abort,
        "chain_abort_codes": abort_codes,
        "hard_stop_codes": codes,
        "rekvisit": req_list,
        "flags": flags,
        "sparr": spärrsvar(flags) if codes else None,
        "state": {
            "mode": state.mode,
            "forum": state.forum,
            "jurisdiction": state.jurisdiction,
        },
    }


def _serialize_conflicts(raw_conflicts: Any) -> list[Any]:
    if not raw_conflicts:
        return []
    out: list[Any] = []
    for item in raw_conflicts:
        if isinstance(item, (str, int, float, bool)) or item is None:
            out.append(item)
        elif isinstance(item, dict):
            out.append(item)
        elif hasattr(item, "to_dict") and callable(item.to_dict):
            out.append(item.to_dict())
        elif hasattr(item, "__dict__"):
            out.append(vars(item))
        else:
            out.append(str(item))
    return out


def _run_merge_drafts(merge_paths: list[str]) -> dict[str, Any]:
    if not merge_paths:
        raise ValueError("Inga utkastfiler angavs till --merge-drafts.")

    drafts: list[tuple[str, str]] = []
    for raw_path in merge_paths:
        p = Path(raw_path)
        if not p.exists() or not p.is_file():
            raise FileNotFoundError(f"Utkastfil saknas: {p}")
        drafts.append((p.name, p.read_text(encoding="utf-8")))

    if len(drafts) == 1:
        res = merge_from_iterable(drafts)
    else:
        res = merge_legal_drafts(drafts)

    merged_text = getattr(res, "merged_text", None)
    if merged_text is None:
        merged_text = getattr(res, "text", "")

    return {
        "merged_text": merged_text,
        "unique_blocks": getattr(res, "unique_blocks", None),
        "duplicate_blocks_removed": getattr(res, "duplicate_blocks_removed", None),
        "conflicts": _serialize_conflicts(getattr(res, "conflicts", [])),
        "source_count": len(drafts),
        "result_fields": sorted(k for k in vars(res).keys() if not k.startswith("_")) if hasattr(res, "__dict__") else [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Försäkringskassan CLI")
    parser.add_argument("--text", default="", help="Ärendetext eller underlag")
    parser.add_argument("--rekvisit", nargs="*", default=[], help="Lista med prövade rekvisit")
    parser.add_argument("--mode", default="JUDGMENT_AUDIT", help="Körläge")
    parser.add_argument("--forum", default="förvaltningsdomstol", help="Forum")
    parser.add_argument("--jurisdiction", default="Sverige", help="Rättsordning")
    parser.add_argument("--strict-report", action="store_true", help="Generera strikt gransknings-PM")
    parser.add_argument("--omniroute", action="store_true", help="Hämta och inkludera svar via lokal OmniRoute")
    parser.add_argument("--omni-url", default=DEFAULT_OMNI_URL, help="OmniRoute chat completions-URL")
    parser.add_argument("--omni-model", default=DEFAULT_OMNI_MODEL, help="Modellnamn i OmniRoute")
    parser.add_argument("--list-combos", action="store_true", help="Lista registrerade combo-modeller från combos/combo_models.json")
    parser.add_argument("--ocr-check", action="store_true", help="Kontrollera Tesseract, tessdata och ocrmypdf")
    parser.add_argument("--ocr-image", default=None, metavar="BILD", help="Kör OCR på en bildfil via Tesseract")
    parser.add_argument(
        "--ocr-pdf",
        nargs=2,
        default=None,
        metavar=("IN_PDF", "UT_PDF"),
        help="Gör en inskannad PDF sökbar via ocrmypdf",
    )
    parser.add_argument("--ocr-lang", default="swe", help="Språk för OCR (standard: swe)")
    parser.add_argument("--tesseract-cmd", default=DEFAULT_TESSERACT_CMD, help="Sökväg till tesseract.exe")
    parser.add_argument("--tessdata-dir", default=DEFAULT_TESSDATA_DIR, help="Sökväg till tessdata-katalog")
    parser.add_argument(
        "--merge-drafts",
        nargs="+",
        default=None,
        metavar="FIL",
        help="Sammanfoga en eller flera utkastfiler deterministiskt via legal_text_merge_agent",
    )
    parser.add_argument("--json", action="store_true", help="Skriv utfall som JSON")

    args = parser.parse_args(argv)
    combos = load_combo_models()

    if args.list_combos:
        if args.json:
            print(json.dumps({"combos": combos, "default_model": args.omni_model}, ensure_ascii=False, indent=2))
        else:
            print(f"default_model: {args.omni_model}")
            for c in combos:
                print(f"  * {c}")
        return 0

    ocr_info = configure_ocr_environment(
        tesseract_cmd=args.tesseract_cmd,
        tessdata_dir=args.tessdata_dir,
    )

    text_parts: list[str] = []
    if args.text.strip():
        text_parts.append(args.text.strip())

    ocr_result: dict[str, Any] = {"environment": ocr_info}
    if args.ocr_check:
        ocr_result["check"] = run_ocr_check(
            tesseract_cmd=args.tesseract_cmd,
            tessdata_dir=args.tessdata_dir,
        )
    if args.ocr_image:
        img_res = run_ocr_image(
            args.ocr_image,
            lang=args.ocr_lang,
            tesseract_cmd=args.tesseract_cmd,
            tessdata_dir=args.tessdata_dir,
        )
        ocr_result["image"] = img_res
        if img_res["text"]:
            text_parts.append(img_res["text"])
    if args.ocr_pdf:
        pdf_res = run_ocr_pdf(
            args.ocr_pdf[0],
            args.ocr_pdf[1],
            lang=args.ocr_lang,
            tesseract_cmd=args.tesseract_cmd,
            tessdata_dir=args.tessdata_dir,
        )
        ocr_result["pdf"] = pdf_res

    base_text = "\n\n".join(text_parts)
    omni_result: dict[str, Any] | None = None

    if args.omniroute:
        prompt_input = base_text or (
            "Granska ärendet kort och sakligt utifrån svenska socialförsäkringsregler (SFB) "
            "och ange relevanta rekvisit."
        )
        omni_result = query_omniroute(
            prompt_input,
            omni_url=args.omni_url,
            model=args.omni_model,
        )
        omni_result["available_combos"] = combos
        if omni_result["content"].strip():
            text_parts.append(omni_result["content"].strip())

    effective_text = "\n\n".join(text_parts)
    verdict = build_verdict(
        effective_text,
        rekvisit=args.rekvisit,
        mode=args.mode,
        forum=args.forum,
        jurisdiction=args.jurisdiction,
    )

    if args.ocr_check or args.ocr_image or args.ocr_pdf:
        verdict["ocr"] = ocr_result
    if omni_result is not None:
        verdict["omniroute"] = omni_result

    if args.strict_report:
        verdict["strict_report_md"] = generate_strict_legal_report(verdict)

    if args.merge_drafts is not None:
        verdict["merge_result"] = _run_merge_drafts(args.merge_drafts)

    if args.json:
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
    else:
        print(f"overall_status: {verdict['overall_status']}")
        print(f"chain_abort: {verdict['chain_abort']}")
        print(f"hard_stop_codes: {', '.join(verdict['hard_stop_codes']) or 'NONE'}")
        if "ocr" in verdict and "check" in verdict["ocr"]:
            chk = verdict["ocr"]["check"]
            print(f"ocr_version: {chk.get('version', '')}")
            print(f"ocr_langs: {', '.join(chk.get('languages', []))}")
        if "omniroute" in verdict:
            print("\n--- OMNIROUTE ---\n")
            print(verdict["omniroute"]["content"])
        if "strict_report_md" in verdict:
            print("\n--- STRICT REPORT ---\n")
            print(verdict["strict_report_md"])
        if "merge_result" in verdict:
            print("\n--- MERGED DRAFTS ---\n")
            print(verdict["merge_result"]["merged_text"])

    return 2 if verdict["overall_status"] == "HARD_STOP" else 0


if __name__ == "__main__":
    sys.exit(main())