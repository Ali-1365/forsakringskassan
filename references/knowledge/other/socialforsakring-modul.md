# SOCIALFÖRSÄKRING (FK/SFB) — Forensisk modul
## Aktiveras vid: sjukpenning, SGI, rehabilitering, FK, SFB, aktivitetsersättning

### Kärnlagrum (verifiera version per datum)
- SFB 27 kap. sjukpenning; 26 kap. SGI; 27 kap. 46–49 §§ rehabiliteringskedja
- FL 23 § utredningsskyldighet; 32 § motivering; 5 § proportionalitet
- FPL 8 § officialprincip; 28 § inhibition; 34 a § PT

### Kontroller
- [ ] DFA-kedja (Diagnos–Funktion–Aktivitet) mot medicinskt underlag — ej absolut lagkrav
- [ ] Rehabiliteringskedja dag 1/90/180 + undantag
- [ ] FMR vs specialistläkare (kontrast, inte automatisk rangordning)
- [ ] Kvasinormer (“objektiva fynd”) flaggas EJ_RÄTTSKÄLLA om saknar lagstöd
- [ ] HFD 2018 ref. 51, 2021 ref. 63, 2021 ref. 71 i LEGAL_SOURCE_RECORD
- [ ] Tidsfrister: sjukanmälan, läkarintyg dag 8, SGI, vidarebefordran

### Runtime
`runtime/socialforsakring_lager.py` — L00–L0x FK-lager.

## FK-kodsystem
Se `config/kodsystem_fk_sfb.yaml` och `references/fk-sfb-arbetsskada.md`.
