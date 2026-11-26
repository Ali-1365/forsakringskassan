> Registry-kopia från `references/external_packs/fmjam_v6_platinum/skills/fk-monsterkatalog-crps-patientskada/SKILL.md`

---
name: fk-monsterkatalog-crps-patientskada
description: "Specialiserad mönsterkatalog och beräkningsmotor för FK-ärenden med fokus på CRPS/patientskada. Innehåller 9 namngivna juridiska mönster (SD-08, MED-04, MYND-01, PROC-02, SGI-06, CRPS-01–04, SKADE-01), beviskravskataloger per ärendetyp, och CRPS-ersättningsformler enligt Trafikskadenämndens tabeller. Komplement till fk-socialforsakring-skillen. Triggers: 'CRPS-mönster', 'SD-08', 'MED-04', 'MYND-01', 'Budapestkriterierna', 'invaliditetsersättning', 'CRPS-kalkyl', 'beviskrav FK', 'kompletteringsbegäran FK'."
---

# FK MÖNSTERKATALOG & CRPS-ERSÄTTNINGSMOTOR

## Syfte
Detta är en specialiserad utökning av `fk-socialforsakring`-skillen. Den tillhandahåller en namngiven mönsterkatalog för att klassificera brister i Försäkringskassans handläggning, en beviskravskatalog per ärendetyp (vad som MÅSTE finnas innan analys är meningsfull), och en exakt beräkningsmotor för CRPS-relaterad ersättning enligt Trafikskadenämndens tabeller.

Använd denna skill TILLSAMMANS med `fk-socialforsakring` — den ersätter inte DFA-kedjeanalysen eller anti-template-scanningen, den lägger till precisionskodning av brister och en färdig beräkningsformel.

---

## DEL A — MÖNSTERKATALOG (9 namngivna mönster)

Varje identifierad brist i FK:s handläggning ska, där tillämpligt, taggas med en av följande koder. Detta möjliggör konsekvent referens över flera dokument och ärenden.

### SD-08 — Bristfällig utredning av orsakssamband
**Allvarlighet:** KRITISK
**Triggers i materialet:** orsakssamband ej utredd, samband arbete/skada saknas, arbetsskada ej dokumenterad, kausalitet oklar, FL 23 § ej tillämpad
**Lagrum:** FL 23 §, SFB 110:13 §, SFB 39–44 kap.
**Åtgärd:** Begär kompletterande utredning. Hänvisa till FL 23 § utredningsskyldighet.

### MED-04 — Medicinsk bevisning saknas eller är bristfällig
**Allvarlighet:** HÖG
**Triggers:** läkarintyg saknas, medicinsk utredning ofullständig, specialistutlåtande saknas, journalhandlingar ej inhämtade, diagnos ej dokumenterad
**Lagrum:** FL 23 §, FPL 24 §
**Åtgärd:** Kräv inhämtande av fullständig medicinsk dokumentation.

### MYND-01 — Myndighetsmissbruk / felaktig handläggning
**Allvarlighet:** KRITISK
**Triggers:** handläggning felaktig, kommunikation ej skett, FL 25 § överträdd, motivering saknas, FL 32 § ej tillämpad, objektivitetsbrister
**Lagrum:** FL 25 §, FL 32 §, RF 1:9
**Åtgärd:** Överklaga beslut. Eventuellt skadeståndsanspråk till JK enligt SkL 3:2.

### PROC-02 — Processuella fel i handläggning
**Allvarlighet:** HÖG
**Triggers:** tidsfrister ej iakttagna, kommunikation utebliven, part ej fått yttra sig, kontradiktoriskt förfarande saknas, FL 9 § skyndsamhet
**Lagrum:** FL 9 §, FL 17 §, FPL
**Åtgärd:** Påtala processuella fel. Begär rättelse och kompensation.

### SGI-06 — Felaktig SGI-beräkning
**Allvarlighet:** KRITISK
**Triggers:** SGI felaktig, sjukpenninggrundande inkomst fel, SFB 25 kap. ej tillämpad, inkomst nedsatt utan grund, återställande av SGI nekat
**Lagrum:** SFB 25 kap., SFB 27:46 §
**Åtgärd:** Överklaga SGI-beslut. Kräv återställande enligt SFB 25 kap.

### CRPS-01 — Bristfällig CRPS-diagnos
**Allvarlighet:** KRITISK
**Triggers:** CRPS ej diagnostiserad, Budapestkriterierna ej tillämpade, komplex regional smärta förbisedd, reflexdystrofi ej bekräftad, smärtdiagnos saknas
**Lagrum:** Patientskadelagen 6 § 1 p, Budapestkriterierna (IASP), HFD 2018 ref. 3
**Åtgärd:** Begär specialistutlåtande. Tillämpa Budapestkriterierna. Överklaga till LÖF.

### CRPS-02 — Fördröjd CRPS-diagnos
**Allvarlighet:** HÖG
**Triggers:** CRPS-diagnos fördröjd, sent upptäckt CRPS, symtom ignorerade, tidig behandling utebliven, diagnos efter månader/år
**Lagrum:** Patientskadelagen 6 § 1 p, HFD 2018 ref. 3
**Åtgärd:** Dokumentera fördröjningen tidsmässigt. Hänvisa till HFD 2018 ref. 3. Kräv ersättning för fördröjningens konsekvenser.

### CRPS-03 — Bristande orsakssamband CRPS
**Allvarlighet:** HÖG
**Triggers:** orsakssamband CRPS ej styrkt, samband vård/CRPS saknas, kausalitet CRPS oklar
**Lagrum:** Patientskadelagen (1996:799), HFD 2015 ref. 55
**Åtgärd:** Begär specialistutlåtande om orsakssamband. Dokumentera tidsmässigt samband mellan vårdåtgärd och symtomdebut.

### CRPS-04 — Felaktig invaliditetsgradsbedömning
**Allvarlighet:** HÖG
**Triggers:** invaliditetsgrad för låg, funktionsnedsättning underskattas, CRPS-påverkan ej beaktad, arbetsförmåga felbedömd
**Lagrum:** Trafikskadenämndens tabeller, HFD 2015 ref. 55
**Åtgärd:** Begär ny funktionsbedömning. Jämför med Trafikskadenämndens praxis.

### SKADE-01 — Grund för skadeståndsanspråk mot staten
**Allvarlighet:** KRITISK
**Triggers:** skadestånd JK, Justitiekanslern, myndighetsmissbruk, SkL 3:2, staten ska betala, ersättning myndighetens fel
**Lagrum:** SkL 3:2, RF 1:9
**Åtgärd:** Framställ skadeståndsanspråk till JK. Dokumentera myndighetens fel och den ekonomiska skadan systematiskt.

---

## DEL B — BEVISKRAVSKATALOG PER ÄRENDETYP

**KRITISK PRINCIP:** Innan en fullständig analys eller processhandling produceras, kontrollera att nedanstående bevis finns. Om kategorier saknas — generera en kompletteringsbegäran enligt FL 23 § istället för att fortsätta analysen på bristfälligt underlag.

### FK_SJUKPENNING_SGI
| Kategori | Krävs |
|---|---|
| Medicinsk | Läkarintyg för sjukpenning (aktuellt), journalhandlingar, ev. specialistutlåtande |
| Inkomst | Lönebesked/lönelistor, SGI-beslut från FK, inkomstdeklaration |
| Omständighet | Sjukanmälan till arbetsgivare, ansökan om sjukpenning, FK:s beslut |
| Processuell | Korrespondens med FK, eventuella tidigare beslut |

### FK_ARBETSSKADA
| Kategori | Krävs |
|---|---|
| Medicinsk | Läkarintyg med diagnos, journalhandlingar från akutbesök, specialistutlåtande, dokumentation av skadans omfattning |
| Inkomst | Lönebesked före skadan, SGI-underlag, dokumentation av inkomstförlust |
| Omständighet | Arbetsskadeanmälan (SKV 5011), arbetsgivarens utredning, vittnesmål, dokumentation av hur skadan inträffade, bevis på orsakssamband |
| Processuell | FK:s beslut om arbetsskada, korrespondens med FK, eventuella tidigare omprövningar |

### FK_LIVRANTA
| Kategori | Krävs |
|---|---|
| Medicinsk | Läkarintyg som dokumenterar varaktig nedsättning (>1 år), specialistutlåtande om prognos, funktionsbedömning, dokumentation av invaliditetsgrad |
| Inkomst | Lönebesked före skadan, aktuell inkomst, beräkning av inkomstförlust >1/15, dokumentation av framtida förvärvskapacitet |
| Omständighet | Arbetsskadeanmälan, FK:s beslut om arbetsskada, dokumentation av skadans varaktighet |
| Processuell | FK:s beslut om livränta (om fattat), korrespondens med FK |

### CRPS_PATIENTSKADA
| Kategori | Krävs |
|---|---|
| Medicinsk | Läkarintyg med CRPS-diagnos enligt Budapestkriterierna, specialistutlåtande från smärtspecialist/neurolog, journalhandlingar från ursprunglig behandling, dokumentation av diagnostisk fördröjning, funktionsbedömning och invaliditetsgradsbedömning, prognos och behandlingshistorik |
| Omständighet | Tidslinje för behandling och symtomutveckling, dokumentation av vårdkontakter före/efter diagnos, ev. patientklagomål, bevis på orsakssamband mellan vård/behandling och CRPS |
| Ekonomisk | Lönebesked före CRPS-utveckling, dokumentation av arbetsoförmåga och inkomstförlust, prognoser för framtida förvärvskapacitet, beräkning av livränta, dokumentation av merkostnader |
| Processuell | LÖF:s beslut (om fattat), korrespondens med LÖF, eventuell patientanmälan till IVO |

### SKADESTAND_JK
| Kategori | Krävs |
|---|---|
| Grund för fel | Dokumentation av felaktig handläggning, FK-beslut som är felaktiga, bevis på brott mot FL 23/25/32 §§, dokumentation av processuella fel |
| Ekonomisk skada | Beräkning av ekonomisk förlust, lönebesked/inkomstunderlag, kontoutdrag som visar påverkan, fakturor för merkostnader, dokumentation av framtida ekonomisk skada |
| Orsakssamband | Tydlig koppling mellan myndighetens fel och skadan, tidslinje som visar kausalitet, dokumentation att skadan inte skulle uppstått utan felet |
| Processuell | Samtliga FK-beslut, all korrespondens med FK, eventuella domstolsbeslut |

**Dokumentigenkänningsmönster** (för att klassificera ett okänt dokument):
- Läkarintyg: innehåller "läkarintyg", "sjukpenning", "läkare", "diagnos"
- Journalhandling: "journal", "anteckning", "besök"
- Specialistutlåtande: "specialist", "ortoped", "neurolog", "smärtläkare", "anestesi"
- SGI-beslut: "SGI", "sjukpenninggrundande"
- Arbetsskadeanmälan: "arbetsskada", "skadeanmälan", "SKV 5011"

---

## DEL C — CRPS-ERSÄTTNINGSBERÄKNING

Exakt beräkningsformel enligt Trafikskadenämndens tabeller (2025), för användning i skadeståndsberäkning vid CRPS/patientskada.

### Grundbelopp efter ålder vid skadetillfället
| Åldersgrupp | Grundbelopp |
|---|---|
| 0–29 år | 1 200 000 kr |
| 30–49 år | 1 000 000 kr |
| 50–64 år | 800 000 kr |
| 65+ år | 600 000 kr |

### Beräkningssteg

**1. Invaliditetsersättning**
```
Invaliditetsersättning = Grundbelopp (efter ålder) × (invaliditetsgrad % / 100)
```

**2. Sveda och värk**
Ideell ersättning, anges separat utifrån läkningsförlopp och lidande — ej formelbaserad, bedöms från fall till fall enligt praxis.

**3. Retroaktiv inkomstförlust**
```
Månadsdifferens = Hypotetisk månadsinkomst − Faktisk månadsinkomst
Retroaktiv inkomstförlust = Månadsdifferens × antal månader med förlust
```

**4. Livränta (framtida inkomstförlust)**
```
Årlig förlust = Månadsdifferens × 12
Livränta = Årlig förlust × antal år livränta beräknas för
```

**5. Total ersättning**
```
Total = Invaliditetsersättning + Sveda och värk + Retroaktiv inkomstförlust + Livränta
```

### Rättslig grund för beräkningen
- Patientskadelagen (1996:799), särskilt 6 § 1 p
- Trafikskadenämndens tabeller (åldersjustering av grundbelopp)
- HFD 2018 ref. 3 (fördröjd CRPS-diagnos)
- HFD 2015 ref. 55 (specialistläkares företräde vid bedömning)

### Exempel på fullständig rapport (format att återanvända)
```
CRPS-ERSÄTTNINGSBERÄKNING
================================================================

INPUTPARAMETRAR:
├─ Invaliditetsgrad: [X]%
├─ Ålder vid skada: [X] år
├─ Grundbelopp (åldersjusterat): [X] kr
├─ Hypotetisk månadsinkomst: [X] kr
├─ Faktisk månadsinkomst: [X] kr
├─ Månadsdifferens: [X] kr
├─ Antal månader (retroaktiv förlust): [X]
└─ Livränta beräknad för: [X] år

BERÄKNAD ERSÄTTNING:
1. INVALIDITETSERSÄTTNING = [grundbelopp] × [grad]% = [X] kr
2. SVEDA OCH VÄRK = [X] kr
3. RETROAKTIV INKOMSTFÖRLUST = [X] kr/mån × [X] mån = [X] kr
4. LIVRÄNTA = [X] kr/mån × 12 × [X] år = [X] kr

TOTAL ERSÄTTNING: [SUMMA] kr

RÄTTSLIG GRUND: Patientskadelagen 6 § 1 p, Trafikskadenämndens tabeller,
HFD 2018 ref. 3, HFD 2015 ref. 55
```

---

## DEL D — ÖVERKLAGANDESTRUKTUR (referensmall)

Genererat överklagande ska följa denna struktur (identisk med `processhandling`-skillens I–V, men med FK-specifika fält):

1. **Rubrik** — domstol, diarienummer, parter
2. **Inledning och yrkanden** — numrerad lista, t.ex.:
   - Upphäver Försäkringskassans beslut av den [datum]
   - Fastställer rätt till sjukpenning baserat på korrekt SGI
   - Återställer SGI till nivån före nedsättning
   - Tillerkänner ersättning för ekonomisk förlust
   - Tillerkänner ersättning för rättegångskostnader
3. **Bakgrund** — tidslinje med datum + händelse, medicinska förhållanden, yrkesmässiga förhållanden
4. **Bevisning** — indelad i medicinsk / omständighet / ekonomisk, med exakt dokumentreferens
5. **Rättslig analys** — varje identifierat mönster (Del A ovan) med kod, lagrum, beskrivning och konkret tillämpning på det aktuella ärendet
6. **Slutsats** — sammanfattning av yrkanden

---

## ANVÄNDNING TILLSAMMANS MED ÖVRIGA SKILLS

Denna skill ska alltid kombineras med:
- **fk-socialforsakring** för DFA-kedjeanalys och anti-template-scanning
- **bristklassning** för att omsätta mönsterkoderna ovan (SD-08 etc.) till det generella fyrgradiga systemet (KRITISK/ALLVARLIG/MÅTTLIG/LÅG)
- **skadestand-process** när SKADE-01 aktiveras, för fullständig SkL 3:2-prövning
- **processhandling** eller **juridisk-processmotor** för slutgiltig formatering av överklagandet
