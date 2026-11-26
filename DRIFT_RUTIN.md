# Drift- och miljörutin — SFCAE / Försäkringskassan

## 1. Python Virtual Environments (`venv`)
- Huvudmiljö (`venv_stable`): `C:\AI_Projects\monster_ai_clean\venv_stable\Scripts\Activate.ps1`
- Kodgrafmiljö (`venv_cgc`): `C:\AI_Projects\monster_ai_clean\venv_cgc\Scripts\Activate.ps1`
- Avaktivera aktiv miljö: `deactivate`
- Regler:
  1. Kör aldrig `pip install` i global Python (`C:\Program Files\Python 3.12\python.exe`).
  2. Kör aldrig `pip install --upgrade` i `venv_stable` eller `venv_cgc`.
  3. Installera fristående CLI-/MCP-verktyg endast med `uv tool install <paket>` eller `npm install -g <paket>`.

## 2. Daglig start & kontroll av MCP-hubb (port 3050)
- Starta MCP-hubben:
  & "C:\Users\Min\.mcp\start-mcp-hub.ps1"
- Snabbkontroll (utan anrop):
  pwsh -NoProfile -ExecutionPolicy Bypass -File "C:\Users\Min\.mcp\test-mcp-hub.ps1" -NoCalls