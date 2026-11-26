# METADATA-FORENSIK (ISO/IEC 27037:2012-inspirerad terminologi)
## Aktiveras vid: metadata, EXIF, hash, magic bytes, SHA-256

### K1–K5
K1 Modifieringstyp (skapad/ändrad/åtkommen)  
K2 Filstorlek + magic bytes vs tillägg  
K3 EXIF/systemmetadata  
K4 Programvarukonsistens  
K5 Integritet SHA-256  

### Regel
Teknisk avvikelse ≠ automatiskt bevisförvanskning. Rapportera fakta; juridisk betydelse i L9/L11.

---

## FULLSTÄNDIGT PROTOKOLL

Källa: SKILL\arkitektur\SKILL_Olika.zip → KONSOLIDERAD_ARKITEKTUR/references/metadata-forensik-protokoll.md (2026-09-05). Porterat oförändrat nedan; sammanfattningen ovan är sfcae:s tidigare innehåll och behålls.

> Notera (sfcae 2026-10-09): i sfcae utförs kontrollen av runtime/metadata_forensics_agent.py och integrations/motor_b_agents.run_metadata_forensics.

## 0k. METADATA-FORENSIK-PROTOKOLL (NY v10.3-UPDATED)

### Syfte
Kontrollpunkter för granskning av metadata i digital bevisning, med terminologi
inspirerad av ISO/IEC 27037:2012 (Digital Evidence) och ISO/IEC 27042 (Analysis).
**OBS:** Verktyget är **EJ certifierat** enligt dessa standarder — implementationen
består av regelbaserade kontroller (regex/nyckelordsmatchning). Se LIMITATIONS.md.
Aktiveras vid L0 (källregistrering) och L2 (aktens rådata).

### 5 KONTROLLPUNKTER

```yaml
METADATA_FORENSIK_KONTROLLPUNKTER:

  K1_MODIFIERINGSTYP:
    syfte: Identifiera typ av modifiering i filen
    kontrollpunkter:
      skapad:   Ursprungligt skapandedatum (creation timestamp)
      ändrad:   Senaste ändringsdatum (modification timestamp)
      åtkommen: Senaste åtkomstdatum (access timestamp)
      raderad:  Finns tecken på raderade filer eller data?
    output:
      modifieringstyp: "[SKAPAD | ÄNDRAD | RADERAD | OFÖRÄNDRAD | KAN EJ VERIFIERAS]"
      tidsstämplar:
        skapad:   "[ÅÅÅÅ-MM-DD HH:MM:SS | KAN EJ VERIFIERAS]"
        ändrad:   "[ÅÅÅÅ-MM-DD HH:MM:SS | KAN EJ VERIFIERAS]"
        åtkommen: "[ÅÅÅÅ-MM-DD HH:MM:SS | KAN EJ VERIFIERAS]"
    absolut_regel: >
      Tidsstämplar verifieras mot externa källor när möjligt.
      Aldrig anta att tidsstämpel är korrekt utan verifiering.

  K2_FILSTORLEK_FORMAT:
    syfte: Verifiera filstorlek och format mot förväntad standard
    kontrollpunkter:
      magic_bytes:    Identifiera filtyp via magic bytes (ej filnamnstillägg)
      filstorlek:     Matchar filstorleken förväntad storlek?
      format_version: Identifiera formatversion (t.ex. PDF 1.4, DOCX OOXML)
    output:
      filtyp_verifierad: "[MATCHAR | MATCHAR EJ | KAN EJ VERIFIERAS]"
      magic_bytes:       "[identifierad filtyp via magic bytes]"
      filstorlek_bytes:  "[antal bytes]"
      format_version:    "[identifierad version]"
    avvikelse: >
      Om filnamnstillägg inte matchar magic bytes →
      MÖJLIGT_FAKTAFEL: "Filtyp avviker från filnamnstillägg"

  K3_EXIF_SYSTEMMETADATA:
    syfte: Extrahera all tillgänglig EXIF-data och systemmetadata
    tillämpning: Bilder (JPEG, PNG, TIFF), PDF, Office-dokument
    exif_fält:
      kamera:        Kameramodell och tillverkare
      gps:           GPS-koordinater (om tillgängliga)
      datum_tagen:   Datum och tid för upptagning
      bildstorlek:   Upplösning och dimensioner
      programvara:   Programvara som skapade filen
    output_format: >
      EXIF_RECORD:
        kamera:      "[modell | KAN EJ VERIFIERAS]"
        gps:         "[koordinater | EJ TILLGÄNGLIGT]"
        datum_tagen: "[ÅÅÅÅ-MM-DD HH:MM:SS | KAN EJ VERIFIERAS]"
        programvara: "[identifierad programvara | KAN EJ VERIFIERAS]"

  K4_PROGRAMVARA:
    syfte: Identifiera programvara som genererat eller modifierat filen
    kontrollpunkter:
      skapande_program:     Vilket program skapade filen?
      modifierande_program: Vilket program senast modifierade filen?
      version:              Programvaruversion
    output:
      skapande_program:   "[programnamn version | KAN EJ VERIFIERAS]"
      konsistens:         "[KONSISTENT | INKONSISTENT | KAN EJ AVGÖRAS]"
    avvikelse: >
      Om skapande program och modifierande program är inkonsistenta →
      MÖJLIGT_FAKTAFEL: "Programvaruinkonsistens detekterad"

  K5_INTEGRITETSKONTROLL:
    syfte: Verifiera filens integritet via kryptografisk hash
    standard: ISO/IEC 27037:2012 § 8.3
    hashalgoritmer:
      sha256: Primär – kryptografiskt stark
      md5:    Sekundär – för bakåtkompatibilitet
    output:
      hash_sha256:  "[värde | KAN EJ VERIFIERAS]"
      hash_md5:     "[värde | KAN EJ VERIFIERAS]"
      integritet:   "[VERIFIERAD | MODIFIERAD | KAN EJ VERIFIERAS]"
    chain_of_custody: >
      Varje fil registreras med hash vid ingestion (L0).
      Hash verifieras vid varje analystillfälle.
      Avvikelse → MÖJLIGT_FAKTAFEL: "Filintegritet kan ej verifieras"
```

### METADATA_RECORD – FULLSTÄNDIGT FORMAT

```yaml
METADATA_RECORD:
  fil:              "[filnamn]"
  käll_id:          "[DOK-XXX]"
  skapad:           "[ÅÅÅÅ-MM-DD HH:MM:SS | KAN EJ VERIFIERAS]"
  ändrad:           "[ÅÅÅÅ-MM-DD HH:MM:SS | KAN EJ VERIFIERAS]"
  storlek_bytes:    "[antal]"
  filtyp_magic:     "[identifierad via magic bytes]"
  format_version:   "[version]"
  hash_sha256:      "[värde | KAN EJ VERIFIERAS]"
  hash_md5:         "[värde | KAN EJ VERIFIERAS]"
  programvara:      "[identifierad programvara | KAN EJ VERIFIERAS]"
  exif_datum:       "[ÅÅÅÅ-MM-DD HH:MM:SS | EJ TILLGÄNGLIGT]"
  gps:              "[koordinater | EJ TILLGÄNGLIGT]"
  integritet:       "[VERIFIERAD | MODIFIERAD | KAN EJ VERIFIERAS]"
  modifieringstyp:  "[SKAPAD | ÄNDRAD | RADERAD | OFÖRÄNDRAD]"
  avvikelser:       "[lista avvikelser | INGA AVVIKELSER]"
```

### ANALYSFLÖDE – 5 STEG

```
Steg 1: Ingestion → Hash-registrering (K5) → KÄLL-ID tilldelat
Steg 2: Filtypsverifiering (K2) → Magic bytes kontroll
Steg 3: Metadataextraktion (K1 + K3 + K4) → EXIF + systemmetadata
Steg 4: Integritetskontroll (K5) → Hash-verifiering
Steg 5: METADATA_RECORD → Registreras i L0 källregister
```

### INTEGRATION MED v10.3

```yaml
METADATA_FORENSIK_LAGERMAPPNING:
  L0_källregistrering:  K5 (hash vid ingestion) + METADATA_RECORD
  L2_aktens_rådata:     K1 + K2 + K3 + K4 (fullständig analys)
  FALLBACK_CITATION:    Metadata används för Nivå 1–2 källhänvisning
  LEGAL_REQUISITE_GATE: Integritetsstatus påverkar rekvisit-status

STANDARDER:
  ISO_IEC_27037_2012: Digital Evidence – identifiering, insamling, förvaring
  ISO_IEC_27042:      Digital Evidence – analys och tolkning
```

`[METADATA-FORENSIK-PROTOKOLL | ISO/IEC 27037:2012 | v10.3-UPDATED | LOCKED]`

---
