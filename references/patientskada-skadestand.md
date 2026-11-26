# PATIENTSKADA & SKADESTÅND — Forensisk modul
## Aktiveras vid: patientskada, Patientskadelagen, SkL 3:2, medicinsk felbehandling

### Tillämplig rätt (dynamisk — verifiera lydelse per händelsedatum)
- Patientskadelagen (SFS 1996:799)
- Skadeståndslagen 3 kap. 2 § (myndighet/arbetsgivare)
- Patientsäkerhetslagen (SFS 2010:659) — anmälan, utredning
- Hälso- och sjukvårdslagen (SFS 2017:30) — vårdplikt
- Patientdatalagen (SFS 2008:355) — journal

### Rekvisitkedja Patientskadelagen (MUST-status krävs)
1. Patient i svensk hälso-/sjukvård
2. Personskada
3. Skadan orsakad av undersökning/vård/behandling (eller underlåtenhet)
4. Skadan hade kunnat undvikas / ej förväntad komplikation enligt etablerad vetenskap
5. Orsakssamband skada ↔ vårdåtgärd

### Bevisbörda / beviskrav
- Patient: göra antagligt att skada uppkommit i vården
- Ersättning via LÖF/landsting — ej obligatoriskt domstol först
- Vid SkL 3:2: culpa + orsakssamband; beviskrav enligt HD-praxis

### Forensisk kontrollista
- [ ] Journal komplett / luckor markerade
- [ ] Vårdgivare / enhet identifierad
- [ ] Tidpunkt för åtgärd vs skadesymtom (tidslinje)
- [ ] Medicinskt sakkunnigutlåtande åberopat?
- [ ] Anmälan till IVO / LÖF gjord?
- [ ] Rekvisit MUST status i LEGAL_REQUISITE_GATE
- [ ] CIRCULAR_REASONING: journal får inte ensam bevisa egen riktighet utan stöd

### Output
Rekvisitmatris + tidslinje + lucklista + (vid MODE B) provisoriskt beslutsunderlag.
