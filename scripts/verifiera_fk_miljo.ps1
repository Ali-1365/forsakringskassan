param(
    [string]$Proj     = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$SrcRoot  = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [switch]$SkipPip,
    [switch]$SkipCopy,
    [switch]$KeepIsolated
)
$ErrorActionPreference = 'Continue'
$logFile = Join-Path $Proj ("verifiering_" + (Get-Date -Format 'yyyyMMdd_HHmmss') + ".log")

function Log { param([string]$Msg, [string]$Color='Gray')
    Write-Host $Msg -ForegroundColor $Color
    Add-Content -Path $logFile -Value $Msg -Encoding UTF8 }
function Section { param([string]$T)
    Log ""; Log ("=" * 72) 'DarkCyan'; Log "  $T" 'Cyan'; Log ("=" * 72) 'DarkCyan' }

Set-Location $Proj
$isoCache = Join-Path $Proj '.isolated_pycache'
$isoTmp   = Join-Path $Proj '.isolated_tmp'
$isoPip   = Join-Path $Proj '.isolated_pip_cache'
New-Item -ItemType Directory -Force -Path $isoCache, $isoTmp, $isoPip | Out-Null
$env:PYTHONPATH          = "$Proj;$Proj\runtime;$Proj\moduler_och_regler"
$env:PYTHONPYCACHEPREFIX = $isoCache
$env:TEMP                = $isoTmp
$env:TMP                 = $isoTmp
$env:PIP_CACHE_DIR       = $isoPip

Section "0. Miljö"
Log "Projekt:   $Proj"
Log "Källa:     $SrcRoot"
Log "Logg:      $logFile"
Log "Python:    $(python --version 2>&1)"
Log "Exe:       $((Get-Command python).Source)"
Log "PYTHONPATH = $env:PYTHONPATH"

function Write-TempPy { param([string]$Name, [string]$Code)
    $f = Join-Path $isoTmp $Name
    [System.IO.File]::WriteAllText($f, $Code, [System.Text.UTF8Encoding]::new($false))
    return $f }

Section "1. Kopiera saknade moduler"
if (-not $SkipCopy) {
    $wanted = @{
        runtime = @(
            'claim_classifier','evidence_categorizer','config_loader','core_types',
            'bristrapport','capability_map','case_paths','case_resources_consumer',
            'deep_search_pipeline','document_text_extractor','domskals_matris_agent',
            'external_packs_consumer','fup_analysis_agent','hard_stop_las',
            'hard_stop_register','knowledge_loader','kodsystem_scanner',
            'kvalitetskontroll','lagskifte_validator','layer_map','material_registry',
            'metadata_forensics_agent','module_loader','observability','ocr_fallback',
            'pattern_scanner','process_position_agent','processratt_scanner',
            'resource_loader','session_context','skill_references_consumer',
            'verifieringsgrind','kallkedja','konfig_kalla','legal_data_hunter_client',
            'legal_source_chain','run_lock_store','skill_reference_loader',
            'steg13_dynamic_legal_engine','strict_legal_report_generator',
            'technical_fixtures'
        )
        integrations = @('consolidated_engine','motor_b_agents','ny_runtime_bridge','rattstids_bridge')
        scripts      = @('component_map','exception_census','SYSTEM_HEALTH_TEST_2026_09_22')
    }
    $copied=$skipped=$missing=0
    foreach ($k in $wanted.Keys) { foreach ($m in $wanted[$k]) {
        $s = Join-Path $SrcRoot "$k\$m.py"; $d = Join-Path $Proj "runtime\$m.py"
        if (-not (Test-Path $s)) { Log "  ! KÄLLA SAKNAS: $s" 'DarkYellow'; $missing++; continue }
        if (Test-Path $d) { $skipped++; continue }
        Copy-Item $s $d -Force; Log "  + runtime\$m.py (från $k\)" 'Green'; $copied++
    }}
    Log "  Kopierade: $copied | Redan fanns: $skipped | Källa saknas: $missing"
}

Section "2. Pip-beroenden"
if (-not $SkipPip) {
    $pkgs = @('python-docx','pypdf','PyYAML','Pillow','beautifulsoup4','certifi',
              'feedparser','PyMuPDF','pdf2image','pdfplumber','pytesseract',
              'requests','truststore')
    $out = & python -m python -m pip install --quiet --disable-pip-version-check @pkgs 2>&1
    if ($LASTEXITCODE -ne 0) { Log "  pip returnerade $LASTEXITCODE" 'Red'; $out | % { Log "    $_" 'DarkRed' } }
    else { Log "  pip OK" 'Green' }
}

Section "3. Syntaxkontroll (py_compile)"
$pyFiles = Get-ChildItem -Path $Proj -Recurse -Filter '*.py' |
    Where-Object { $_.FullName -notlike '*\_backup_*' -and $_.FullName -notlike '*\.isolated_*' }
$syntaxErrors = 0
foreach ($f in $pyFiles) {
    $out = & python -m py_compile $f.FullName 2>&1
    if ($LASTEXITCODE -ne 0) {
        Log "[SYNTAXFEL] $($f.FullName.Replace($Proj + '\', ''))" 'Red'
        $out | % { Log "    $_" 'DarkRed' }; $syntaxErrors++
    }
}
Log "Kontrollerade $($pyFiles.Count) filer | Fel: $syntaxErrors" $(if ($syntaxErrors) {'Red'} else {'Green'})

Section "4. Beroendeskanner"
$scannerCode = @"
import ast, pathlib, sys, importlib.util
root     = pathlib.Path(r'$Proj')
src_root = pathlib.Path(r'$SrcRoot')
py_files = [p for p in root.rglob('*.py')
            if '_backup_' not in str(p) and '.isolated_' not in str(p)]
local_mods = {p.stem for p in py_files}
for d in root.rglob('*'):
    if d.is_dir() and (d/'__init__.py').exists(): local_mods.add(d.name)
stdlib = getattr(sys, 'stdlib_module_names', set())
missing = {}
for p in py_files:
    try: tree = ast.parse(p.read_text(encoding='utf-8', errors='replace'))
    except Exception: continue
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import): names = [a.name.split('.')[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module.split('.')[0]]
        for n in names:
            if n in stdlib or n in local_mods or n == '__future__': continue
            missing.setdefault(n, set()).add(str(p.relative_to(root)))
really = {}
for n, users in missing.items():
    try:
        if importlib.util.find_spec(n) is None: really[n] = users
    except (ImportError, ValueError): really[n] = users
print(f'=== {len(really)} saknade moduler ===')
for n, users in sorted(really.items()):
    src = [s for s in src_root.rglob(n + '.py') if 'forsakringskassan' not in str(s).lower()]
    print(f'[{n}]')
    print(f'  används av: {sorted(users)}')
    print(f'  källa:      {src if src else "SAKNAS i sfcae"}')
"@
$scannerFile = Write-TempPy 'scanner.py' $scannerCode
$scanOut = & python $scannerFile 2>&1
$scanOut | % { Log $_ }
$missingCount = 0
if ($scanOut -match '=== (\d+) saknade') { $missingCount = [int]$Matches[1] }

Section "5. Importkontroll"
$importCode = @"
import importlib, traceback
mods = [
    'bygg_forsakringskassan_miljo','diagnostik_fk_moduler','kor_fk_egna_tester',
    'moduler_och_regler.fk_entity_extract','moduler_och_regler.fk_pattern_runner',
    'moduler_och_regler.fk_rapport_runner','moduler_och_regler.socialforsakring_lager',
    'runtime.dynamic_pipeline','runtime.forensic_engine_v10_3_canonical',
    'runtime.forum_detector','runtime.motor_c_v10_v3',
    'runtime.requisite_claim_mapper','runtime.sfcae_cli','runtime.source_hygiene',
    'claim_classifier','evidence_categorizer','document_text_extractor',
    'config_loader','bristrapport','deep_search_pipeline','domskals_matris_agent',
    'fup_analysis_agent','hard_stop_las','hard_stop_register','kodsystem_scanner',
    'kvalitetskontroll','material_registry','ocr_fallback','pattern_scanner',
    'process_position_agent','consolidated_engine','kallkedja','konfig_kalla',
    'legal_data_hunter_client','legal_source_chain','motor_b_agents',
    'ny_runtime_bridge','rattstids_bridge','run_lock_store',
    'skill_reference_loader','steg13_dynamic_legal_engine',
    'strict_legal_report_generator','technical_fixtures',
]
ok = fel = 0
for m in mods:
    try:
        importlib.import_module(m); print(f'[OK]   {m}'); ok += 1
    except Exception as e:
        print(f'[FEL]  {m} -> {type(e).__name__}: {e}'); fel += 1
        for line in traceback.format_exc().splitlines()[-4:]:
            print('       ' + line)
print(f'=== {ok} OK | {fel} FEL ===')
"@
$importFile = Write-TempPy 'imports.py' $importCode
$impOut = & python $importFile 2>&1
$impOut | % { Log $_ $(if ($_ -match '^\[FEL\]') {'Red'} elseif ($_ -match '^\[OK\]') {'Green'} else {'Gray'}) }
$importOk = 0; $importFel = 0
if ($impOut -match '=== (\d+) OK \| (\d+) FEL') { $importOk = [int]$Matches[1]; $importFel = [int]$Matches[2] }

Section "6. Rök-tester"
function Run-Smoke { param([string]$Name, [string]$Code)
    Log "`n--- $Name ---" 'Yellow'
    $file = Write-TempPy ("smoke_" + ($Name -replace '[^\w]','_') + ".py") $Code
    $out = & python $file 2>&1
    $rc = $LASTEXITCODE
    $out | % { Log "  $_" $(if ($_ -match 'Error|Traceback|FEL') {'Red'} else {'Gray'}) }
    Log "  exit=$rc" $(if ($rc -eq 0) {'Green'} else {'Red'})
    return $rc }

$forumCode = @"
from forum_detector import detect_forum
cases = [
    'Yrkande om ogiltigförklaring av hyresavtal enligt 12 kap. jordabalken',
    'Överklagande av förvaltningsrättens dom i mål om sjukpenning',
    'Tvistemål om skadestånd enligt 2 kap. skadeståndslagen',
]
for t in cases:
    r = detect_forum(t)
    print(f\"  {r.get('status')!s:18s} {t[:60]}\")
"@
$diagCode = @"
from diagnostik_fk_moduler import diagnostisera
try: diagnostisera()
except SystemExit as e: print(f'(SystemExit {e.code})')
"@
$testerCode = @"
from kor_fk_egna_tester import kor_fk_analys
try: kor_fk_analys()
except SystemExit as e: print(f'(SystemExit {e.code})')
"@
$smoke = @{}
$smoke.forum  = Run-Smoke 'forum_detector'      $forumCode
$smoke.diag   = Run-Smoke 'diagnostisera'       $diagCode
$smoke.tester = Run-Smoke 'kor_fk_analys'       $testerCode

Section "7. Resultat"
Log "`negna_tester_input:" 'Cyan'
Get-ChildItem (Join-Path $Proj 'egna_tester_input') -Recurse -ErrorAction SilentlyContinue |
    Select-Object @{n='Fil';e={$_.FullName.Replace($Proj+'\','')}}, Length |
    Format-Table -AutoSize | Out-String | % { Log $_ }
Log "`negna_tester_resultat (efter):" 'Cyan'
Get-ChildItem (Join-Path $Proj 'egna_tester_resultat') -Recurse -ErrorAction SilentlyContinue |
    Select-Object @{n='Fil';e={$_.FullName.Replace($Proj+'\','')}}, Length, LastWriteTime |
    Format-Table -AutoSize | Out-String | % { Log $_ }

Section "8. Sammanfattning"
$allGreen = ($syntaxErrors -eq 0) -and ($importFel -eq 0) -and
            (($smoke.Values | Where-Object { $_ -ne 0 }).Count -eq 0)
Log "Syntaxfel:            $syntaxErrors"
Log "Saknade moduler:      $missingCount"
Log "Import OK/FEL:        $importOk / $importFel"
Log "Rök forum_detector:   exit=$($smoke.forum)"
Log "Rök diagnostisera:    exit=$($smoke.diag)"
Log "Rök kor_fk_analys:    exit=$($smoke.tester)"
Log ""
if ($allGreen) { Log ">>> MILJON AR VERIFIERAD <<<" 'Green' }
else           { Log ">>> ATGARDA FEL OVAN <<<"   'Red'   }

Section "9. Städning"
if (-not $KeepIsolated) {
    Remove-Item -Recurse -Force $isoCache, $isoTmp, $isoPip -ErrorAction SilentlyContinue
    Log "Borttaget: .isolated_pycache, .isolated_tmp, .isolated_pip_cache"
} else { Log "Behallet (KeepIsolated): $isoCache, $isoTmp" }
Log "`nLogg sparad: $logFile" 'Cyan'