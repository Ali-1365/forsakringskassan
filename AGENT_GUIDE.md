# AGENT_GUIDE: ATERANVANDNING AV forsakringskassan-MOTORN

Denna mapp (<PROJEKTROT>) ar en isolerad, verifierad och skrivskyddad (READ-ONLY) korningsmiljo for **Svensk Forensic Court Audit Engine (SFCAE v10.3-canonical)** med fullt stod for socialforsakringsmal (Forsakringskassan).

## 1. STRIKTA REGLER FOR EXTERNA AGENTER (CODEX M.FL.)
1. **READ-ONLY-BASLINJE:** Andra, radera eller skriv ALDRIG nya filer inuti <PROJEKTROT>. Kopiera inte over karnkod till ditt andra projekt -- importera direkt harifran.
2. **ISOLERAD SOKVAG (LACKAGESKYDD):** Lagg ENDAST till foljande tre sokvagar i sys.path / PYTHONPATH:
   - <PROJEKTROT>
   - <PROJEKTROT>\runtime
   - <PROJEKTROT>\moduler_och_regler
   Lagg **ALDRIG** till modermappen C:\AI_Projects\sfcae i sokvagen.
3. **SEPARAT UTDATAMAPP:** 
un_pipeline() kraver ett explicit output_dir utanfor bade denna mapp och kallmappen. Originalhandlingar lases alltid skrivskyddat (LOCKED_BASELINE).
4. **INGEN BYTECODE-NEDSKRAPNING:** Kor Python med -B eller PYTHONDONTWRITEBYTECODE=1.

## 2. PUBLIKT GRANSSNITT (ENTRYPOINT)
Huvudingang: 
untime/forensic_engine_v10_3_canonical.py -> funktionen 
un_pipeline:

    import sys
    from pathlib import Path

    FK_ROOT = Path(r'<PROJEKTROT>')
    for p in (FK_ROOT, FK_ROOT / 'runtime', FK_ROOT / 'moduler_och_regler'):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))

    from runtime import forensic_engine_v10_3_canonical as canon

    case_state = canon.run_pipeline(
        root_paths=[r'SOKVAG_TILL_ARENDEMAPP'],
        process_mode=canon.ProcessMode.JUDGMENT_AUDIT,
        output_dir=r'SOKVAG_TILL_SEPARAT_UTDATAMAPP',
    )

### Utdata som genereras i output_dir
- udit_report_v10.md -- Fullstandig forensisk granskningsrapport (provisoriskt beslutsstod).
- case_state_v10.json -- Komplett maskinlasbart tillstand (claims, rekvisit, flaggor, SHA-256).
- presentation_views_v10.json -- Domstols-, Part A- och Part B-vyer.
- 
ekvisitmatris.csv -- Strukturerad rekvisit- och bevistabell.

## 3. FELHANTERING & STOPPKODER
- **Saknade modulfiler (HS04_SAKNAD_FIL):** 
untime/module_loader.py och 
untime/ny_runtime_bridge.py kastar inte FileNotFoundError vid saknad valfri modul utan returnerar en flaggad platshallare (_SAKNAD_FIL = True).
- **Saknat materiellt underlag (HS11):** Om rekvisit i ett FK-arende saknar verifierat rattsfaktum flaggas HardStopCode.HS11 och slutstatus blir AuditStatus.H (*Otillrackligt underlag*).
- **Tom indatamapp (HS01C):** Om 
oot_paths saknar filer avbryts korningen kontrollerat med HardStopCode.HS01C.
- **Offline-rattskallor (REQUIRES_SEARCH_01_VERIFICATION):** Lagrum och praxis markerade [REQUIRES_SEARCH_01_VERIFICATION] maste kontrolleras mot primarkalla fore skarp anvandning.

## 4. MAPPSTRUKTUR
- 
untime/ -- Kanonmotor (orensic_engine_v10_3_canonical.py), modulladdare (module_loader.py), agenter och pipeline.
- moduler_och_regler/ -- FK-specifika regler (socialforsakring_lager.py, k_entity_extract.py, k_pattern_runner.py, k_rapport_runner.py, 
attstid_runner.py + *.yaml).
- config/ -- Regel- och kodsystemstabeller (YAML/JSON).
- 
eferences/ -- Kunskaps- och granskningsprotokoll (Markdown).
- scripts/ -- Interna passiva verifieringsverktyg (ska ej anropas i skarp drift).
