# RÖSTANALYS-PROTOKOLL (ENFSI FSA-BPM-002 FIXED-2026)
## Aktiveras vid: .wav/.mp3/.m4a, transkription, förhandlingsljud

### Zero-inference
- [OHÖRBART] får aldrig fyllas i
- Domen får inte användas för att rekonstruera ljud
- Riktning: LJUD → TRANSKRIPTION → KÄLLKONTROLL → DOM

### Segmentformat
`[AUDIO-ID | TALARE | HH:MM:SS.mmm–HH:MM:SS.mmm | EXAKT_CITAT | KÄLLSTATUS]`

### Kontroller M1–M5 (regelbaserade)
M1 Integritet/hash · M2 Tidskodskontinuitet · M3 Överlappande tal · M4 Bakgrundsljud bevaras · M5 Diskrepans ljud↔skriftlig utsaga

---

## FULLSTÄNDIGT PROTOKOLL

Källa: SKILL\arkitektur\SKILL_Olika.zip → KONSOLIDERAD_ARKITEKTUR/references/röstanalys-protokoll.md (2026-09-05). Porterat oförändrat nedan; sammanfattningen ovan är sfcae:s tidigare innehåll och behålls.

> Notera (sfcae 2026-10-09): transkription sker i sfcae via runtime/asr_adapter.py. Utan installerad ASR-motor redovisas ljudgranskningen som EJ_GENOMFÖRD (simulerad=True); utan ljudfil som EJ_TILLÄMPLIG. Formuleringen nedan om SIMULERAD transkription i motor_b_source.py avser den historiska Motor B och gäller inte sfcae.

# RÖSTANALYS-PROTOKOLL
## Terminologireferens: ENFSI FSA-BPM-002 (EJ certifierad implementation)
## SVENSK FORENSIC COURT AUDIT ENGINE v10.3
---

## SYFTE

Kontrollpunkter för granskning av domstolens hantering av röst- och
ljudmaterial, med terminologi inspirerad av ENFSI FSA-BPM-002
(FIXED-version januari 2026).
**OBS:** Ingen certifierad audioforensisk metodik — verktyget utför
regelbaserade textkontroller, och aktuell agent använder en SIMULERAD
transkription (se motor_b_source.py). Se LIMITATIONS.md.
Protokollet aktiveras när L2b (Audio Forensics)
och L3 (Ljudforensik) körs.

---

## ABSOLUTA REGLER (ZERO INFERENCE POLICY)

```
❌ ALDRIG: Domen får användas som facit för vad ljudet säger
❌ ALDRIG: [OHÖRBART] fylls i med antaganden
❌ ALDRIG: [ÖVERLAPPANDE TAL] ignoreras
❌ ALDRIG: Talaridentifiering utan verifierad metadata
❌ ALDRIG: Inferens om vad som "troligen" sades
✅ ALLTID: [OHÖRBART] bevaras oförändrat
✅ ALLTID: Tidsangivelse per segment [HH:MM:SS.mmm]
✅ ALLTID: Källstatus per segment (VERIFIERAD / KAN EJ VERIFIERAS)
✅ ALLTID: Muntlig källa markeras [MUNTLIG_KÄLLA – EJ PRIMÄRKÄLLA]
```

---

## 5 ANALYSMODULER

### M1: Teknisk kvalitetskontroll

```yaml
M1_TEKNISK_KVALITET:
  syfte: Bedöm om ljudkvaliteten tillåter forensisk analys
  kontrollpunkter:
    SNR:       Signal-to-noise ratio – acceptabelt för analys?
    klippning: Finns tecken på klippning eller redigering?
    kodek:     Identifiera codec och komprimeringsartefakter
    metadata:  Extrahera teknisk metadata (samplerate, bitrate, kanaler)
  output:
    kvalitetsbedömning: "[TILLRÄCKLIG | OTILLRÄCKLIG | GRÄNSFALL]"
    analysbarhet:       "[KAN ANALYSERAS | KAN EJ ANALYSERAS | DELVIS]"
    teknisk_metadata:   "[samplerate | bitrate | kanaler | längd]"
```

### M2: Autenticitetsanalys

```yaml
M2_AUTENTICITET:
  syfte: Verifiera att ljudfilen inte manipulerats
  standard: ISO/IEC 27037:2012 + ENFSI FSA-BPM-002 (endast terminologireferens — ej certifierad implementation)
  kontrollpunkter:
    hash:           SHA-256 + MD5 – matchar original?
    metadata:       Skapad/ändrad-datum konsistent?
    redigeringstecken: Finns diskontinuiteter, klick eller artefakter?
    kodek_konsistens: Är kodek konsistent genom hela filen?
  output:
    integritet: "[VERIFIERAD | MODIFIERAD | KAN EJ VERIFIERAS]"
    hash_sha256: "[värde eller KAN EJ VERIFIERAS]"
    avvikelser: "[lista avvikelser eller INGA AVVIKELSER]"
```

### M3: Talaridentifiering

```yaml
M3_TALARIDENTIFIERING:
  syfte: Identifiera talare i ljudmaterialet
  krav: Verifierad referensupptagning krävs för jämförelse
  metod:
    auditiv_analys:    Lyssningsanalys av tränad analytiker
    akustisk_analys:   Spektrogram och formantanalys
    lingvistisk_analys: Dialekt, ordval, prosodi
  output_format: >
    Talare: [VERIFIERAD: namn | EJ SÄKERT: möjlig talare | OKÄND]
    Grund: [verifierad metadata | referensupptagning | KAN EJ VERIFIERAS]
  absolut_regel: >
    Talaridentifiering utan verifierad referensupptagning
    markeras alltid: [TALARIDENTIFIERING EJ VERIFIERBAR]
```

### M4: Transkription

```yaml
M4_TRANSKRIPTION:
  syfte: Ordagrann, tidsstämplad transkription av hörbart tal
  outputformat: >
    [AUDIO-ID] | [HH:MM:SS.mmm]–[HH:MM:SS.mmm]
    HÖRBART: "[exakt text]" | Talare: [verifierad/EJ SÄKERT]
    [OHÖRBART] | Källstatus: KAN EJ VERIFIERAS
    [ÖVERLAPPANDE TAL: talare A + talare B]
  regler:
    - Ordagrann återgivning – aldrig parafras
    - [OHÖRBART] bevaras oförändrat – aldrig gissning
    - [ÖVERLAPPANDE TAL] markeras explicit
    - Osäkra ord markeras: [OSÄKERT ORD: X]
    - Rekonstruerad text: [REKONSTRUERAD – EJ ORIGINAL]
  fallback_citation:
    nivå_4: "[AUDIO-ID | Talare | HH:MM:SS | exakt citat]"
```

### M5: Diskrepansanalys

```yaml
M5_DISKREPANSANALYS:
  syfte: Jämför domstolens återgivning av ljud mot originalljudet
  circular_reasoning_blocker: >
    Domen får ALDRIG användas som facit för vad ljudet säger.
    Riktning: ORIGINALLJUD → TRANSKRIPTION → DOMSTOLENS PÅSTÅENDE
    Förbjuden riktning: DOM → LJUD (cirkel)
  outputformat:
    DOMSTOLENS_PÅSTÅENDE:  "[exakt domtext | DOM-ID | SIDA]"
    ORIGINALLJUD_VISAR:    "[exakt transkription | AUDIO-ID | tidskod]"
    DISKREPANS:            "[JA | NEJ | KAN EJ AVGÖRAS]"
    DISKREPANSTYP:         "[UTELÄMNAT | TILLAGT | FÖRÄNDRAT | OHÖRBART]"
    RÄTTSLIG_BETYDELSE:    "[KAN PRÖVAS | KAN INTE AVGÖRAS | VERIFIERAD]"
```

---

## BEVISKEDJA FÖR LJUDBEVISNING

```yaml
BEVISKEDJA:
  steg_1: Originalljud (primärkälla) – hash-verifierad
  steg_2: Teknisk kvalitetskontroll (M1)
  steg_3: Autenticitetsanalys (M2)
  steg_4: Transkription (M4) – ordagrann
  steg_5: Talaridentifiering (M3) – om relevant
  steg_6: Diskrepansanalys (M5) – mot domstolens påstående
  steg_7: Slutstatus per segment (A–I)

KEDJAN_KAN_INTE_VERIFIERAS_OM:
  - Originalljud saknas eller ej hash-verifierat
  - Teknisk kvalitet otillräcklig (M1 = KAN EJ ANALYSERAS)
  - Autenticitet ej verifierbar (M2 = KAN EJ VERIFIERAS)
```

---

## INTEGRATION MED v10.3
```yaml
LAGERMAPPNING:
  L2b_audio_forensics:  M1 + M2 (teknisk + autenticitet)
  L3_ljudforensik:      M3 + M4 + M5 (talare + transkription + diskrepans)
  L0_källregistrering:  Hash-registrering vid ingestion
  FALLBACK_CITATION:    Nivå 4 för muntliga källor

STANDARD:
  namn: ENFSI FSA-BPM-002 FIXED-2026
  url:  enfsi.eu/wp-content/uploads/2026/01/FSA-BPM-002_Digital-Audio-Authenticity-Analysis-FIXED.pdf
  tillämpning: M1–M5 alla moduler
```

`[RÖSTANALYS-PROTOKOLL | ENFSI FSA-BPM-002 FIXED-2026 | v10.3 | LOCKED]`
