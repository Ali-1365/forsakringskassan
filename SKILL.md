---
name: sfcae
description: >
  Källstyrd forensisk domstolsmotor (SE). ProcessMode JUDGMENT_AUDIT eller
  JUDGMENT_CONSTRUCTION via forensic_engine_v10_3_canonical. Opartisk
  domarassistent, hard stops, L0–L16, dynamic_pipeline-orkestrering med
  policy-bindning (config_loader), valfria domain-/advokat-runners (requested=True).
  Aktiveras vid domgranskning, processhandling, aktinventering, socialtjänst,
  socialförsäkring, patientskada, tvistemål, vault, myndighetsbeslut.
metadata:
  version: "10.3-canonical"
  status: AKTIV
  primary_engine: runtime/forensic_engine_v10_3_canonical.py
  orchestrator: runtime/dynamic_pipeline.py
  core_types: runtime/core_types.py
  config_loader: runtime/config_loader.py
  # Testantalet växer löpande — kör `pytest` för det aktuella talet i
  # stället för att lita på ett tal skrivet här. Ett tidigare "45 passed"
  # blev stående oförändrat långt efter att svepet passerat 1000 tester.
  tests: "kör `pytest` för aktuellt antal — se tests/"
---

# SFCAE — Svensk Forensisk Court Audit Engine

**Version:** 10.3-canonical | **Status:** AKTIV (as-built)

## Identitet

**Domarnivå (kärna):** opartisk, forensisk, fail-closed. Skiljer påstående från bevis. Gissar inte lagversion eller kompletthet.

**Advokatlager (separat):** `run_advocacy_if_requested(..., requested=True)` läser skrivskyddad kopia av CaseState/pipeline-state. Ändrar aldrig kärnresultat. All output PROVISORISK.

## Primära entrypoints

```python
# Rekommenderad huvudväg
from dynamic_pipeline import run_dynamic_pipeline
state = run_dynamic_pipeline(root_dirs=["/ärende/"], mode="JUDGMENT_AUDIT")
# mode: JUDGMENT_AUDIT | JUDGMENT_CONSTRUCTION | ANALYS | PRODUKTION

# Canonical (anropas av finalize; kan användas direkt vid behov)
from forensic_engine_v10_3_canonical import run_pipeline
# run_pipeline(root_paths, process_mode, output_dir, references_dir) -> CaseState

# Konsoliderad väg — den CLI/GUI/MCP faktiskt använder för fullständig analys
from consolidated_engine import consolidate
# consolidate(root_dirs, output_dir, case_metadata) -> dict (Motor C + integrationer)
```

`runtime/skill_orchestrator.py` (tidigare rekommenderad "host-routing"-väg
här) är avvecklad — se `tests/test_orkestrering.py`. Den ENDA
orkestreringsvägen är `consolidated_engine.consolidate()` (CLI/GUI/MCP)
respektive `dynamic_pipeline.run_dynamic_pipeline()` (lättare MCP-delanalys).

## Körlägen

| ProcessMode | Alias | Betydelse |
|-------------|-------|-----------|
| JUDGMENT_AUDIT | ANALYS | Granska beslut/dom |
| JUDGMENT_CONSTRUCTION | PRODUKTION | Processutkast från akt |
| ogiltigt | — | HS01A → CHAIN_ABORT |

Enums: `runtime/core_types.py` re-exporterar `PipelineState` / `ProcessMode` / `HardStopCode` från canonical (**samma klassidentitet**).  
`dynamic_pipeline.PipelineState` är separat **dataclass** (orkestreringsstate).

## Kedja och hard stops

`PIPELINE_CHAIN` (16 steg, `runtime/dynamic_pipeline.py`): MODE → FORUM →
JURISDICTION → L0_INGEST → L0_CATEGORIZE → L0_HYGIENE → L2_CLAIMS →
L4_POSITIONS → L7_LEGAL → L8_REQUISITES → MOD_ECONOMY → MOD_SFB →
MOD_SOCIALTJÄNST → L10_KONTRA → L12_14_AUDIT → L16_FINALIZE → canonical.

| Kod / signal | Effekt |
|--------------|--------|
| **CHAIN_ABORT** (`HS01A`, `HS06`, `HS_CANONICAL_*`, `HS_MAX_STOPS_EXCEEDED`) | Efterföljande steg `HOPPAD`; finalize anropar inte canonical |
| **HS01B** (tom akt) | `underlag_saknas=True`, `zero_fel=UNDERLAG_SAKNAS`, **ingen** kedje-HOPPAD; **canonical körs** |
| `max_hard_stops_before_abort` (default 3) | Från `config_loader.system_policy()`; överskridande → `HS_MAX_STOPS_EXCEEDED` |
| `EJ_TILLÄMPLIG` | Modul saknas/irrelevant — kedjan fortsätter |

### Policy-bindning (importtid)

`dynamic_pipeline` laddar `_POLICY` via `config_loader.system_policy()`:

- `provisional_output_only = True` (påtvingat fail-closed i loader)
- `zero_inference = True`
- `_MAX_HARD_STOPS`, `_MIN_SOURCE_COVERAGE`

### Zero-inference

`_check_zero_inference(state)` körs i `step_finalize` före canonical. Claims utan `source`/`källa`/`citation`/`lagrum`/`source_id` → `zero_inference_violations` + `claim_zero_fel` (stoppar **inte** kedjan).

### Ärendenivå `zero_fel`

`EJ_BEDÖMD` | `UNDERLAG_SAKNAS` | `DELVIS` | `GODKAND` — **inte** synonymt med bevisstatus.

## Analystillstånd (canonical)

`RequisiteStatus`: `BEVISNING_SAKNAS`, `OTILLRACKLIGT_STYRKT`, `BEVISNING_TALAR_EMOT`, `SAKFORHALLANDET_STYRKT`, `FRAGAN_OKLAR` (+ legacy via `map_requisite_status_to_five`).

## Valfria runners (Alt B — `requested=True`)

| Runner | Modul |
|--------|--------|
| Advokat | `integrations/advocacy_bridge.run_advocacy_if_requested` |
| Kodsystem | `kodsystem_runner` / `skanna_text` + `config/kodsystem_*.yaml` |
| Duel | `duel_runner` → `duel_engine` |
| Aktgranskning | `run_aktgranskning_if_requested` / `run_aktgranskning_per_submapp` |
| FK-rapport | `fk_rapport_runner.run_fk_rapport_if_requested` |
| Rättstid | `rattstid_runner` |

**Aldrig** i `PIPELINE_CHAIN`. Advokat: deepcopy; OUTPUT_SPÄRD vid HS09/HS11/HS15 utan override; kedje-abort → EJ_KÖRBAR.

## Katalogstruktur

| Katalog | Roll |
|---------|------|
| `runtime/` | canonical, dynamic_pipeline, core_types, config_loader, agenter, scanners, observability.py, kallkedja.py |
| `integrations/` | adapters, optional runners, advocacy, consolidated_engine.py (Motor C-orkestrering) |
| `config/` | YAML (policy, FSM, kodsystem_*, judgment_*, …) |
| `references/` | `skills_registry/` (SKILL.md per skill), `knowledge/` (konsoliderad kunskapsbas — `architecture/`, `legal-theory/`, `procedures/`, `specifications/`, `other/`), `advocacy-templates/`, `external_packs/`, `archive/` (historiskt material, bl.a. `archive/development/`), `t3098_23/` (ärendeartefakter), `_sessions/` (lokal runtime-lagring, ej committad). `_deprecated/`/`_archived_config/` som nämndes i tidigare revisioner finns inte längre — innehållet konsoliderades in i `knowledge/`/`archive/`. |
| `tests/` | pytest — kör `pytest` för aktuellt antal och täckning |
| `scripts/` | sidoverktyg (SYSTEM_HEALTH_TEST, component_map, generate_manifest, exception_census, m.fl. — ej del av analyskedjan) |
| `mcp/` | `mcp/server.py` (stdio), `mcp/http_server.py`+`mcp/observability_api.py` (FastAPI), `mcp/static/observability_dashboard.html` |
| `docs/` | arkitektur-/revisionsdokumentation (bl.a. `docs/20260925 & 26/OBSERVABILITY_ARKITEKTUR_2026-09-25.md`, `docs/20260925 & 26/SYSTEMINVENTERING_2026-09-25.md`) |
| `gui_advanced.py` | huvudsakliga arbets-GUI:t — se avsnittet nedan |

## Definition of Done (DoD)

1. `python -m py_compile` på ändrade filer OK  
2. Tom akt: `zero_fel=UNDERLAG_SAKNAS`, 0× HOPPAD, finalize OK, canonical körd  
3. Ogiltigt läge: HS01A + HOPPAD  
4. `pytest tests/` grön  
5. Policy: `_POLICY` bunden i dynamic_pipeline  
6. Advokat/optional kräver `requested=True`  
7. Inga aktiva imports till `_deprecated/`  

## Infrastruktur

| Fil | Innehåll |
|-----|----------|
| `requirements.txt` | pyyaml, PDF-extraktionskedjan (pypdf/pdfplumber/PyMuPDF/Pillow/pytesseract/pdf2image), fastapi/uvicorn/pydantic (HTTP-server + testsvit) |
| `pyproject.toml` | version 10.3.0 |
| `runtime/config_loader.py` | bevisad `yaml.safe_load` av aktiva config-nycklar |
| `tests/` | kör `pytest` för aktuellt antal (växer löpande — inte hårdkodat här) |

## Policy

- `references/knowledge/other/policy-ej-implementera.md` — medvetet exkluderade filer (poäng→domslut, court-ready utan granskning, hårdkodad klientdata).
- Integrations utan path i `PIPELINE_CHAIN` är **direktanrop/Alt B**, inte dead code per automatik (se lista i historik om behövs).

## Systemet gör aldrig

- Blandar JUDGMENT_AUDIT och JUDGMENT_CONSTRUCTION i samma körning  
- Presenterar overifierat som verifierat (`zero_inference`)  
- Låter advokatlagret skriva över CaseState  
- Kör optional runners utan `requested=True`  
- Returnerar `zero_fel=GODKAND` vid tom akt / kedje-abort utan markering  

## Avslutningsstatus (verifierat)

| Kontroll | Status |
|----------|--------|
| dynamic → canonical | OK |
| Policy-bindning | OK |
| HS01B / CHAIN_ABORT | OK |
| zero_inference-flagga | OK |
| Advokat Alt B | OK |
| pytest | kör `pytest` — se tests/ |
| Kärn-enums identitet | OK |

**Host bör använda `consolidated_engine.consolidate()` (fullständig analys) eller `run_dynamic_pipeline` (delanalys) — inte en parallell canonical-väg som kringgår policy.**

## Nya runtime-komponenter (korrigeringspaket)

| Modul | Funktion |
|-------|----------|
| `runtime/lagskifte_validator.py` | SoL 2001:453 vs 2025:400 m.fl. via `beslutsdatum` |
| `step_jurisdiction` | anropar lagskifte om `case_meta.beslutsdatum` |
| `step_forum` | `_validera_domstol` mot `court_profiles` |
| `aktgranskning` | `bilageförteckning=` korsreferens |
| `advocacy_bridge` | `TOM_REKVISIT_LISTA` i gap_list |
| `tests/test_e2e_minimal_akt.py` | e2e mot `/tmp/test_akt` |
| `tests/test_lagskifte_validator.py` | 10 lagskiftetester |

**Tester:** `tests/test_e2e_minimal_akt.py`, `tests/test_lagskifte_validator.py` gröna (kör `pytest` för fullständig svit).

## Ohårdkodad ärendeparameter-hantering

Inga personnamn, personnummer eller klientdata i kod/config.
Klient- och ärendedata anges som **parametrar** eller via **session**.

### Sessionsminne

```python
from session_context import spara_session
from dynamic_pipeline import run_dynamic_pipeline
from arende_loader import ladda_ärende, kör_ärende, lista_ärenden

# Värdena nedan är PLATSHÅLLARE - ersätt med uppgifter ur det faktiska
# ärendet/operatörens indata. Inga exempelvärden får användas som underlag.
spara_session(
    arende_ref="<ÄRENDEREFERENS>",
    processordning="<PROCESSORDNING>",
    domän="<DOMÄN>",
    forum="<FORUM>",
    beslutsdatum="<ÅÅÅÅ-MM-DD>",
    rekvisit=["<rekvisit ur aktmaterialet>"],
    bilageförteckning=["<bilaga ur aktmaterialet>"],
)
state = run_dynamic_pipeline(root_dirs=["<ärendets aktmapp>"], session_id=sid)
# eller
kör_ärende("<ÄRENDEREFERENS>", root_dirs=["<ärendets aktmapp>"])
```

**Dataursprung (steg 15):** analys, rekvisitmatris, bevisobjekt och
falsifiering grundas ENDAST på aktmaterialet, operatörens indata eller
uttryckligen konfigurerade källor (`config/`). Saknas underlag redovisas vad
som saknas och varför (t.ex. `UNDERLAG_SAKNAS`, `BEVISNING_SAKNAS`, HS-kod) -
inga inbyggda exempel, inga förifyllda resultat och ingen förutbestämd
slutsats. Ej körd falsifiering redovisas `NOT_RUN`.

| Fil | Roll |
|-----|------|
| `config/arende_config.yaml` | Domäner, processordningar, standardrekvisit, lagskiften |
| `runtime/session_context.py` | spara/ladda/radera session |
| `runtime/arende_loader.py` | uppslag via målnummer |
| `references/_sessions/` | JSON-sessioner (ej i git-logik; lokal lagring) |
| `references/session_index.yaml` | index över sparade sessioner |
| `references/knowledge/other/memory_import.md` | systemminne (målnummer, arkitektur) |

Ny domän = ny rad i YAML. Sessioner raderas **endast** explicit.

## Session-fält och policy-kopplingar (verifierat)

- **Lagskifte:** `lagskifte_validator` läser `arende_config.lagskiften` via `config_loader` (fallback inbyggd lista).
- **Session-fält:** `state.rekvisit` / `state.bilageförteckning` aktiveras i `run_dynamic_pipeline` → `case_meta`; rekvisit utan laghänvisning flaggas (HS09-meta, ej kedje-abort).
- **min_source_coverage:** kontrolleras i `step_finalize`; under tröskel → `underlag_saknas` + transparent status, ej CHAIN_ABORT.

## Architecture_SKILL-utbyggnad (verifierad)

Bygger vidare på befintlig motor — ingen parallell FSM.

| Komponent | Anrop | Roll |
|-----------|-------|------|
| `config/layer_map.yaml` + `runtime/layer_map.py` | `map_architecture_layer("L00_INTEGRITET")` | Architecture ↔ dynamic/canonical |
| `runtime/source_class_bridge.py` | `klassificera_kalla(...)`, `annotate_records(...)` | SOURCE_TYPE / AUTHORITY_LEVEL |
| `config/legal_source_hierarchy.yaml` | via `config_loader` | SEARCH-protokoll + hierarki |
| `integrations/kontradiktorisk_matris.py` | `run_matris_if_requested(..., requested=True)` | Påstående↔motpåstående |
| `integrations/expert_observation_runner.py` | `run_expert_observations_if_requested(..., requested=True)` | Sakobservation, **ingen** juridisk slutsats |

**Regler:** Bidirectional audit = `CONTROL_ONLY` (aldrig dataflöde). Deep search förblir verifiering under analysen. Optional runners kräver `requested=True`.

## Domänrouting och mönsterbibliotek (verifierat)

Härlett från externa systeminstruktioner (FK/arbetsskada/router/mönster) men **neutraliserat**:
- ingen strikt lojalitet i kärnan
- ingen maximal-ersättning-policy i domarnivå
- ingen person-/ärendedata

| Komponent | Anrop | Roll |
|-----------|-------|------|
| `config/case_routing.yaml` | `case_router.run_case_router_if_requested(text, requested=True)` | Domän/forum-indikation |
| `config/pattern_rules_v2.yaml` | `pattern_scanner.skanna_monster(text)` / `run_pattern_scan_if_requested` | MYND-01, SFB-03, MED-04, AS-04 m.fl. |
| `arende_config` domäner | standardrekvisit FK_ARBETSSKADA, FK_LIVRANTA, PATIENTSKADA_CRPS | Session/rekvisit |
| `references/knowledge/specifications/phal-workflow-indikativ.md` | dokumentation | Arbetsflödesstöd |
| `references/advocacy-templates/fem-sektions-struktur.md` | mall | Advokatlagret |

**HS06-princip:** Routing föreslår — blandar inte FK/Löf/JK i samma automatiska körning utan explicit val.

## Ersättning och lojalitetsbrygga (advokatlager)

Utelämnat från kärnan; implanterat som **Alt B**:

| Komponent | Anrop |
|-----------|--------|
| `config/ersattning_config.yaml` | 5 typer, endast `[JURIST: …]`-platshållare |
| `runtime/ersattning_scanner.py` | `run_ersattning_if_requested(text, requested=True)` |
| `integrations/lojalitet_bridge.py` | `run_lojalitet_if_requested(case_state, pipeline_state, requested=True, …)` |
| `references/advocacy-templates/ersattning-struktur.md` | Mall med GAP_LIST |

**Garantier:** inga automatiska belopp; deepcopy CaseState; kedje-abort blockerar; provisorisk märkning.

## FL/FPL process-adapter (utelämnat material)

Från SYSTEM_INSTRUKTION / pasted-text — **inte** i canonical:

| Del | Anrop |
|-----|--------|
| `config/kodsystem_fpl_forvaltning.yaml` | FL 5–32, FPL 7–44 (indikativ) |
| `integrations/fl_process_runner.py` | `run_fl_process_if_requested(text, requested=True)` |
| `references/knowledge/procedures/fl-process-protokoll.md` | Kontrollpunkter |
| `references/knowledge/specifications/policy-matris-indikativ.md` | Mönster utan poäng→domslut |
| `references/archive/development/adapter_log.md` | Gap-logg per bilaga |

`grep` personnamn i runtime/integrations/config ska vara tomt.

## Smarta verktyg för att bemöta motparten

### Motstrategisk analysmotor
`runtime/motstrategi_engine.py` — `run_motstrategi_if_requested(..., requested=True)`  
Domäner: FK_SFB, SOL_LVU, RB_TVIST, KL_KONKURS. INDIKATIV_ENDAST.

### Processrättslig granskningsmodul
`runtime/processratt_scanner.py` — `run_processratt_if_requested(..., requested=True)`  
FL 23/25/32, EKMR art. 6/8, BK art. 12, proportionalitet, preskription.

### Bevisstyrkekalkylator
`runtime/bevisstyrka_kalkylator.py` — `run_bevisstyrka_if_requested(..., requested=True)`  
Skala A_STARK→F_OTILLÅTEN. Aldrig domslut. Juristen beslutar.

## MCP / Claude-plugin
- `mcp/server.py` — JSON-RPC 2.0 stdio. Antal verktyg växer löpande — läs
  `len(TOOLS)` i `mcp/server.py` eller `manifest.json`/
  `plugin/.claude-plugin/plugin.json` för det aktuella, exakta talet
  (69 vid denna revision) i stället för ett hårdkodat tal här.
- Varje verktygsanrop via `call_tool()` (main()s tools/call-väg) bär ett
  `mcp_sparbarhet`-fält: verktyg, riktig runtime-modul, tidsstämpel,
  varaktighet, samt passthrough av handlerns egna käll-/fallback-/
  verifieringsfält — `NOT_AVAILABLE` där verktyget inte har konceptet,
  aldrig ett fabricerat värde.
- `mcp/http_server.py` — FastAPI, `api.py` som ASGI-ingång (localhost:8080
  lokalt; kräver fastapi/uvicorn/pydantic, numera kärnberoenden i
  `requirements.txt`/`pyproject.toml`). Exponerar merparten av
  MCP-verktygen som REST-routes samt `/dashboard` — ett read-only
  observability-lager (`mcp/observability_api.py`,
  `runtime/observability.py`) som visar riktiga körningar/events, ALDRIG
  simulerade — se `docs/20260925 & 26/OBSERVABILITY_ARKITEKTUR_2026-09-25.md`.
- `mcp/claude_desktop_config.json`, `mcp/plugin_manifest.json`, `mcp/INSTALL.md`

## Skuldkedja / ekonomisk dokumentforensik (Alt B)
- `config/skuldkedja_config.yaml`
- `runtime/skuldkedja_scanner.py` — `skanna_skuldkedja`
- `integrations/skuldkedja_runner.py` — `run_skuldkedja_if_requested(..., requested=True)`
- Referens: `references/knowledge/procedures/forensisk-ekonomisk-skuldkedja-protokoll.md`
- **Aldrig:** skuldgiltighet, preskription, avgiftslaglighet, partsansvar.

## AI-riskheuristik (Alt B)
- `config/ai_risk_config.yaml`
- `runtime/ai_risk_scanner.py` — kanonisk (den tidigare `integrations/ai_risk_runner.py` är avvecklad)
- Flaggar misstänkta citat/fall-mönster — **ingen** lagdatabasverifiering.

## Processmotor / 28-skill-orchestrator
Endast `references/*-indikativ.md`. Inte inbakat i `dynamic_pipeline`/`canonical`.

## LSB skyddat boende (Alt B)
- `config/kodsystem_lsb_skyddat_boende.yaml`
- `runtime/lsb_skyddat_scanner.py` / `integrations/lsb_skyddat_runner.py`
- Protokoll: `references/knowledge/procedures/lsb-skyddat-boende-analysprotokoll.md`
- Ordning: rättslig ram → händelsetabell → angreppspunkter A–D → handling via advocacy
- **Aldrig** automatisk processkrift utan `requested=True` och faktamaterial.

MCP-verktyg utökade med: `sfcae_skuldkedja`, `sfcae_ai_risk`, `sfcae_lsb_skyddat`, `sfcae_ersattning` (historisk notering — det totala antalet har vuxit betydligt sedan dess, se `len(TOOLS)` i `mcp/server.py`).

## Blueprint-lager (utan kärnkonflikt)
- Mappning: `references/knowledge/architecture/blueprint-court-architecture-mapping.md`
- B01–B15: `config/bug_classification.yaml` + `runtime/bug_classifier.py::klassificera_buggar`
- Pre-trial PT01–PT07: `runtime/pretrial_objectives.py::run_pretrial_if_requested(svar=..., requested=True)` (utan `svar`: tom mall; med `svar` utan `källa`: flaggas `SAKNAR_KÄLLA`/B02, fylls aldrig i tyst)
- Party/mediation: endast advocacy/party_impact (deepcopy), inte canonical

## Blueprint pack (post-pipeline)
```python
from integrations.blueprint_pack_runner import run_blueprint_pack_if_requested
pack = run_blueprint_pack_if_requested(pipeline_state=state, requested=True)
# bugs, pretrial, relation_graph, mediation
```

## Blueprint full pack
Se `references/knowledge/architecture/blueprint-full-implementation-map.md`.
```python
from integrations.blueprint_pack_runner import run_blueprint_pack_if_requested
pack = run_blueprint_pack_if_requested(pipeline_state=state, requested=True, include_change_impact=True)
# p00, bugs, severity, pretrial×17, graph, mediation, capability, final_audit, reproducibility
```

## Gap-åtgärder (P1–P6)
- **P1:** Tom akt → `canonical_skipped`, finalize-status `UNDERLAG_SAKNAS` (ingen full COMPLETE-export).
- **P2:** `core_types.PipelineState` (Enum) ≠ `dynamic_pipeline.PipelineState` (dataclass) — dokumenterat.
- **P3:** Party-vyer märkta `PROVISORISK_PARTY_VIEW`.
- **P4:** MCP +`sfcae_duel`, `sfcae_rattstid`, `sfcae_fk_rapport`.
- **P5:** e2e-testakt `/tmp/test_akt` — tidigare skip nu körbara.
- **P6:** bug_classifier tar in canonical counter_audit-signaler när de finns i state.output.

## Konfliktfix 2026-09-16
- `dynamic_pipeline.OrchestrationState` (ej PipelineState-dataclass)
- `bug_classifier` synkar `counter_audit_results` först
- `config/policy_monitor_live_snapshots.yaml` (SoL/LSB/Budapest-struktur)
- `runtime/sfs_api_resolver.py` + MCP `sfcae_live_sfs_verifier` (fail-closed)
- `runtime/phal_hardware_adapter.py` + MCP `sfcae_phal_validate` (strukturell logg)

## Domän JB_HYRA (lokalhyra)
- `config/kodsystem_jb_hyresratt.yaml` (JB 12:58/57/42, RB 13:3, 36:6)
- Gap-mallar: `config/hyresratt_gap_templates.yaml`
- Exempelsession T 3098-23 (illustrativt namnmönster, `_sessions/` är lokal
  runtime-lagring, ej committad — se `references/t3098_23/` för de
  committade ärendeartefakterna) + case snapshot (PROVISORISK)
- `integrations/motor_b_runner.py` (isolerad, requested=True)
- **Ingen** automatisk ogiltigförklaring av uppsägning i kärnan.

## FMJAM-GOLD (v1.0) — Chain of Custody
- `config/fmjam_gold_schema.yaml` — 7 ID-kedjor (SHA-256), 4 lager, Justice Guard (EJ_AVGJORT)
- `runtime/fmjam_adapter.py` — `run_fmjam_gold_if_requested(requested=True)`
- MCP: `sfcae_fmjam_gold_audit`
- **Ingen** materiell dom/subsumtion; risknivå är strukturell flagga

## FMJAM Controller + Justice Guard-symbios
- `runtime/fmjam_controller.py` — cross-case KPI (0–1), fragment-återkomst, `feedback_to_justice_guard`
- Justice Guard i `fmjam_adapter` skannar `files` → `indikativa_källor` + SHA-256; status **EJ_AVGJORT**
- MCP: `sfcae_fmjam_controller_scan`
- Loop: `apply_controller_feedback_to_guard(...)` → priorities in i Guard

## Ärendeartefakter T 3098-23
- `references/t3098_23/` — projekt_config, fall_konfiguration, process_data, fall_malminne, fall_systemarkitektur, source_separation (PROVISORISK)
- `config/source_separation.yaml` — `excluded_roots: external` (loader/cross-case)
- Session: illustrativt namnmönster i `references/_sessions/` (lokal runtime-lagring, ej committad)

## Källkedjespårning (dokument → faktum → rekvisit → lagrum → resultat)
- `runtime/kallkedja.py` — spårar en claim/ett rekvisit/ett granskningsfynd
  bakåt till exakt dokument, sida och citat, mot ett redan byggt
  `CaseState` (`consolidated_engine.consolidate(..., _expose_case_state=True)`).
  Läser ENDAST redan byggda canonical-fält (`claims`/`requisite_matrix`/
  `legal_sources`/`audit_*_findings`) — bygger ingen egen parallell
  spårningsdatabas. Varje länk som inte kan verifieras markeras
  `EJ_VERIFIERAT`/`EJ_HITTAT`, fylls aldrig i med ett antagande.
- MCP: `sfcae_kallkedja` (kör hela pipelinen mot verkligt aktmaterial och
  spårar sedan resultatet i den faktiska CaseState).
- HTTP: `GET /api/observability/trace` (samma modul, mot en körning som
  bevarat sitt CaseState).
- GUI: fliken "Källkedja / Spårbarhet" i `gui_advanced.py`.

## Observability — read-only lager ovanpå den befintliga HTTP-servern
- `runtime/observability.py` — in-memory register över RIKTIGA
  körningar/events. Instrumenterat i `call_tool()` (varje MCP-
  verktygsanrop), `dynamic_pipeline.run_dynamic_pipeline()` (de 16 riktiga
  pipeline-stegen, med verklig timing) och `consolidated_engine.consolidate()`
  (Motor C — grovkornigt, då motorn saknar interna fasstakar).
- `mcp/observability_api.py` — `/api/observability/{tools,modules,pipeline,
  runs,runs/{id},events/{id},events/{id}/stream,trace,status}`, monterat i
  `mcp/http_server.py`. Introspekterar levande register — inget hårdkodat.
- `mcp/static/observability_dashboard.html` — serveras på `GET /dashboard`.
  Visar verktyg/moduler/pipeline/körningar live; `NOT_AVAILABLE` där
  systemet faktiskt inte exponerar ett värde (cpu/ram/kö/AI/RAG-status),
  aldrig ett påhittat tal. Stöder sekretessmaskering (`?maskera=true`) av
  innehållsfält — maskerar aldrig strukturfält, ersätter aldrig med
  fejkdata.

## gui_advanced.py — det kompletta arbets-GUI:t
Huvudsaklig arbetsyta för att öppna, köra och följa upp ärenden. Bygger
INGEN egen analyslogik — varje flik anropar en redan existerande, redan
testad funktion.

| Flik | Roll | Anropar |
|------|------|---------|
| Analysera ärendet | Öppna ärendemapp, kör full analys | `consolidated_engine.consolidate()` |
| Mina ärenden | Lista/ladda sparade ärenden | `session_context.lista_sessioner`/`ladda_session` |
| Källkedja / Spårbarhet | Spåra en claim/rekvisit/finding | `runtime/kallkedja.py` |
| Motstrategi | Motpartsargument utifrån ej styrkta rekvisit | `runtime/motstrategi_engine.py` |
| **Alla verktyg** | Generisk, schemadriven vy över SAMTLIGA registrerade MCP-verktyg, grupperade i 16 arbetsytor (`VERKTYGSGRUPPER`) | `mcp/server.py::call_tool()` — formulär byggda live ur varje verktygs riktiga `inputSchema` |
| Systemstatus | Live-räknade tal (config/kunskap/resurser/MCP-verktyg/hälsotest) | `knowledge_loader`/`resource_loader`/`mcp/server.py`/`SYSTEM_HEALTH_TEST` |
| Inställningar | Lokal preferens — läses INTE av något annat i systemet (ärligt disclaimad) | — |

"Alla verktyg"-fliken garanterar att ett nytt MCP-verktyg alltid är nåbart
från GUI:t (direkt eller under "Övrigt") utan att någon flik behöver
skrivas om — se `tests/test_gui_advanced.py::test_verktygsgrupper_tacker_exakt_alla_registrerade_verktyg`.

**`runtime/vault_and_audit_engine.py::VaultAuditEngine`** (fil-kopierande
SHA-256/riskklassificering) är MEDVETET INTE kopplad till MCP-verktyget
`sfcae_vault_audit` — det verktyget rapporterar bara ärligt
`MODUL_TILLGÄNGLIG`. Att koppla in den riktiga motorn skulle innebära
faktiska filkopieringssidoeffekter via en MCP-/GUI-väg och kräver
explicit, separat godkännande.
