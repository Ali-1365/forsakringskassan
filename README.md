# Försäkringskassan (SFB) — Gransknings- och exekveringsmiljö

Komplett dokumentation för gransknings- och exekveringsmiljön i `C:\AI_Projects\sfcae\forsakringskassan` för arbete med svensk socialförsäkringsgranskning (`runtime\fk_cli.py`), lokal modellrouting via OmniRoute (`http://localhost:20128`), OCR-stöd samt kryptografisk filintegritetsverifiering via `sha256_manifest.json` och `sfcae_forsakringskassan_1to1.zip`.

---

## 1. Vad som har använts och vad som har gjorts

### Använda komponenter och tjänster
* **Projektkatalog:** `C:\AI_Projects\sfcae\forsakringskassan`
* **Python-miljö:** `venv_stable` (körs i PowerShell utan `-B`)
* **CLI-ingång:** `runtime\fk_cli.py`
* **Underliggande moduler i `runtime/`:**
  * `dynamic_pipeline.py` (`OrchestrationState`, `step_mode`)
  * `hard_stop_las.py` (`kedjeavbrott`, `las_hard_stop_koder`, `spärrsvar`)
  * `legal_text_merge_agent.py` (`merge_from_iterable`, `merge_legal_drafts`)
  * `strict_legal_report_generator.py` (`generate_strict_legal_report`)
  * Samt övriga projektmoduler (`config_loader.py`, `core_types.py`, `forensic_engine_v10_3_canonical.py`, `knowledge_loader.py` m.fl.)
* **Lokal modellrouter:** OmniRoute på `http://localhost:20128` (`http://localhost:20128/v1/chat/completions` och `/v1/models`)
* **Combo-konfiguration:** `combos\combo_models.json`
* **OCR-verktyg:** Tesseract OCR (`tesseract.exe` och `tessdata`) samt `ocrmypdf.exe`
* **Integritetsfiler:** `sha256_manifest.json` och 1:1-arkivet `sfcae_forsakringskassan_1to1.zip`

### Vad som har gjorts hittills
1. **Modellinventering och gruppering:** Hämtade och analyserade modellistan från OmniRoute (`localhost:20128/v1/models`), grupperade efter prefix/leverantör och kombo-/auto-alias samt filtrerade fram text-/resonemangsmodeller.
2. **Identifiering och verifiering av egna combo-modeller:** Bekräftade de tre anpassade combo-modellerna i OmniRoute:
   * `min-gratis-kodkedja`
   * `min-kod-kedja`
   * `static-best-reasoning`
3. **Lagring av combo-konfiguration:** Skapade `combos\combo_models.json` med dessa tre combo-modeller.
4. **Införande i `runtime\fk_cli.py`:** Lade till stöd för `load_combo_models()`, flaggan `--list-combos`, standardmodell `static-best-reasoning` samt inkludering av tillgängliga combos i OmniRoute-utdata.
5. **Upprensning av cache och engångstestfil:** Tog bort `runtime\__pycache__` och `scripts\fk_avancerad_praxis_test.py`.
6. **Synkronisering och integritetsverifiering:** Uppdaterade och verifierade `sha256_manifest.json` och `sfcae_forsakringskassan_1to1.zip` mot **196** verifierade projektfiler (`0` hashavvikelser, `zf.testzip() == None`).

---

## 2. Regler, standardvärden och beteende i systemet

### Arbets- och säkerhetsregler för drift och ändringar
* **Ingen automatisk manipulation:** Ändringar i kod, konfiguration, manifest eller ZIP-arkiv sker endast när du uttryckligen kör kommandot för det.
* **Strikt kontroll mot manifest och ZIP:** Varje filändring, tillägg eller borttagning i projektkatalogen förändrar filernas SHA-256-summor och kräver omsynkronisering av `sha256_manifest.json` och `sfcae_forsakringskassan_1to1.zip` om 1:1-integriteten ska bevaras.
* **Hårdkodade standardvärden i `runtime\fk_cli.py`:**
  * `DEFAULT_OMNI_URL = "http://localhost:20128/v1/chat/completions"`
  * `DEFAULT_OMNI_MODEL = "static-best-reasoning"`
  * `DEFAULT_COMBOS_FILE = Path(__file__).resolve().parent.parent / "combos" / "combo_models.json"`
  * `DEFAULT_TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"`
  * `DEFAULT_TESSDATA_DIR = r"C:\Program Files\Tesseract-OCR\tessdata"`
  * `DEFAULT_VENV_OCRMYPDF = r"C:\AI_Projects\monster_ai_clean\venv_stable\Scripts\ocrmypdf.exe"`

### Hur `build_verdict` och hårdstoppsregler fungerar i `runtime\fk_cli.py`
* Initierar `OrchestrationState(mode=mode, forum=forum)` med `jurisdiction` och `text`, och kör `step_mode(state)`.
* Om inga rekvisit anges (`--rekvisit` är tom) läggs flaggan `"HS11"` till.
* Hämtar hårdkodade stoppkoder via `las_hard_stop_koder(flags)` och kedjeavbrott via `kedjeavbrott(flags)`.
* Sätter `overall_status` till:
  * `"HARD_STOP"` (och returnerar exit-kod `2`) om `chain_abort` är sann,
  * `"READY_WITH_WARNINGS"` om hårdkodade koder finns utan kedjeavbrott,
  * `"READY"` annars.
* Kan generera rapport via `--strict-report` (`generate_strict_legal_report(verdict)`) och sammanfoga utkastfiler via `--merge-drafts` (`merge_from_iterable` / `merge_legal_drafts`).

---

## 3. Vad som behöver installeras och finnas på plats

1. **Python 3.12+** med en aktiv virtuell miljö (`venv_stable` rekommenderas).
2. **Python-paket i miljön:**
   * `pytesseract` och `Pillow` (`PIL`) om bild-OCR ska köras via Python utöver Tesseract CLI.
   * Övriga beroenden som krävs av modulerna i `runtime/` (`ocrmypdf` installerat i den miljö som `DEFAULT_VENV_OCRMYPDF` pekar på om `--ocr-pdf` används).
3. **Tesseract OCR och svenskt språkpaket (`swe.traineddata`):**
   * Standardvägar i `runtime\fk_cli.py` pekar på `C:\Program Files\Tesseract-OCR\tesseract.exe` och `C:\Program Files\Tesseract-OCR\tessdata`, men kan åsidosättas vid körning med `--tesseract-cmd` och `--tessdata-dir`.
4. **Lokal OmniRoute-instans:**
   * Körande på `http://localhost:20128` (eller angiven URL via `--omni-url`) med de tre combo-modellerna (`min-gratis-kodkedja`, `min-kod-kedja`, `static-best-reasoning`) konfigurerade i OmniRoute, samt eventuell API-nyckel i miljövariabeln `OMNIROUTE_API_KEY` eller `OPENAI_API_KEY` (eller i `.env` / `~/.omniroute/.env`).

---

## 4. Hur du använder systemet (`runtime\fk_cli.py`)

Kör alltid kommandona i PowerShell med din aktiva miljö (`venv_stable`):

### Lista combo-modeller och aktiv standardmodell
```powershell
Set-Location -Path "C:\AI_Projects\sfcae\forsakringskassan"
python runtime\fk_cli.py --list-combos
```

### Granska ärendetext via OmniRoute med standardmodellen (`static-best-reasoning`)
```powershell
Set-Location -Path "C:\AI_Projects\sfcae\forsakringskassan"
python runtime\fk_cli.py `
  --omniroute `
  --text "Granska ärendet sakligt utifrån svenska socialförsäkringsregler (SFB)." `
  --rekvisit "R1" `
  --strict-report `
  --json
```

### Växla combo-modell vid körning (`min-gratis-kodkedja` eller `min-kod-kedja`)
```powershell
Set-Location -Path "C:\AI_Projects\sfcae\forsakringskassan"
python runtime\fk_cli.py `
  --omniroute `
  --omni-model "min-gratis-kodkedja" `
  --text "Granska ärendet utifrån relevanta SFB-bestämmelser." `
  --rekvisit "R1" `
  --json
```

### Kontrollera OCR-miljö, köra OCR på bild/PDF eller sammanfoga utkast
```powershell
Set-Location -Path "C:\AI_Projects\sfcae\forsakringskassan"
python runtime\fk_cli.py --ocr-check --json
python runtime\fk_cli.py --ocr-image "underlag.png" --ocr-lang "swe" --rekvisit "R1" --json
python runtime\fk_cli.py --ocr-pdf "in.pdf" "ut_sokbar.pdf" --ocr-lang "swe" --json
python runtime\fk_cli.py --merge-drafts "utkast1.md" "utkast2.md" --json
```

---

## 5. Hur du installerar och kör på ett eget eller annat system / annan disk

När du flyttar paketet till ett annat system, en annan enhet/disk (till exempel `D:\AI_Projects\forsakringskassan`) eller delar det vidare via arkiv/repositorium:

### Steg 1: Packa upp eller klona projektet på måldisken
Packa upp `sfcae_forsakringskassan_1to1.zip` (eller kopiera projektmappen) till önskad katalog, till exempel `D:\AI_Projects\forsakringskassan`:

```powershell
New-Item -ItemType Directory -Path "D:\AI_Projects\forsakringskassan" -Force | Out-Null
Expand-Archive -Path "sfcae_forsakringskassan_1to1.zip" -DestinationPath "D:\AI_Projects\forsakringskassan" -Force
Set-Location -Path "D:\AI_Projects\forsakringskassan"
```

### Steg 2: Skapa och aktivera Python-miljö på målsystemet
```powershell
python -m venv venv_stable
.\venv_stable\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install pytesseract pillow ocrmypdf
```

### Steg 3: Anpassa sökvägar och URL om målsystemet skiljer sig
Eftersom `runtime\fk_cli.py` har hårdkodade standardvärden för Windows-sökvägar och lokal OmniRoute bör du på ett nytt system antingen:
1. Skicka sökvägar/URL/modell explicit som CLI-argument vid körning (`--omni-url`, `--omni-model`, `--tesseract-cmd`, `--tessdata-dir`), **eller**
2. Uppdatera `DEFAULT_OMNI_URL`, `DEFAULT_OMNI_MODEL`, `DEFAULT_TESSERACT_CMD`, `DEFAULT_TESSDATA_DIR` och `DEFAULT_VENV_OCRMYPDF` i `runtime\fk_cli.py` så att de matchar målsystemets faktiska installationer.

### Steg 4: Konfigurera OmniRoute och `combos\combo_models.json`
* Se till att OmniRoute körs på målsystemet (standard `http://localhost:20128`) och att de tre combo-modellerna (`min-gratis-kodkedja`, `min-kod-kedja`, `static-best-reasoning`) finns uppsatta där.
* Kontrollera att `combos\combo_models.json` finns på plats i projektroten och kör:

```powershell
python runtime\fk_cli.py --list-combos
```

### Steg 5: Verifiera filintegritet på målsystemet
Kör en skrivskyddad kontroll mot `sha256_manifest.json` för att säkerställa att alla filer kommit över intakta utan korruption:

```powershell
python -c '
import ast, hashlib, json, pathlib

root = pathlib.Path(".")
cli_path = root / "runtime" / "fk_cli.py"
manifest_path = root / "sha256_manifest.json"

ast.parse(cli_path.read_text(encoding="utf-8"), filename=str(cli_path))
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

disk_files = {
    p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in sorted(root.rglob("*"))
    if p.is_file() and p.name not in {"sfcae_forsakringskassan_1to1.zip", manifest_path.name} and "__pycache__" not in p.parts
}

mismatches = [k for k, v in disk_files.items() if manifest.get(k) != v["sha256"]]
missing = [k for k in manifest if k not in disk_files]
print("AST: OK | Filer:", len(disk_files), "| Avvikelser:", len(mismatches), "| Saknas:", len(missing))
'
```