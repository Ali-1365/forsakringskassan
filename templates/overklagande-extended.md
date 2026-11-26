# Överklagande — Extended Mall (PROVISORISK)
*Juristen verifierar och godkänner varje sektion*

*Alla personuppgifter ersatta med platshållare*

---

## Sektion 1

AUTOMATISK ÖVERKLAGANDEGENERATOR
Genererar färdiga överklaganden baserat på ärendedata och identifierade mönster

SYFTE:
Skapar domstolsrediga överklaganden med:
- Korrekt juridisk struktur (5 avsnitt enligt MASTERPROMPT)
- Automatisk tillämpning av identifierade mönster
- Fullständiga lagrumshänvisningar
- Beräkningar (SGI, CRPS-ersättning etc.)

ANVÄNDNING:
python overklagande_generator.py --arende arende_data.json --output overklagande.docx

---

## Sektion 2

Initialiserar generatorn med ärendedata.
        
        Args:
            arende_data: Dictionary med ärendespecifik information

---

## Sektion 3

# ÖVERKLAGANDE
## {arende_typ} - {namn} mot Försäkringskassan

**Diarienummer FK:** {self.data.get('diarienummer_fk', '[Diarienummer]')}
**Beslutsdatum:** {self.data.get('beslutsdatum', '[Datum]')}
**Datum för överklagande:** {datetime.now().strftime('%Y-%m-%d')}

---

---

## Sektion 4

1. Upphäver Försäkringskassans beslut av den [datum].

2. Återförvisar ärendet till Försäkringskassan för förnyad handläggning enligt FL 23 § och SFB 110:13 §.

3. Tillerkänner [klienten] ersättning för rättegångskostnader.

---

## Sektion 5

## 1. INLEDNING & YRKANDEN

### Ärendeskärna
{klient} (personnummer: {personnummer}) överklagar härmed Försäkringskassans beslut av den {beslutsdatum} (diarienummer: {diarienummer}).

{self.data.get('arende_beskrivning', 'Ärendet rör Försäkringskassans felaktiga handläggning och bristande utredning.')}

### Yrkanden
{klient} yrkar att Förvaltningsrätten:

{yrkanden_text}

---

---

## Sektion 6

## 2. BAKGRUND & RELEVANTA FAKTA

### Kronologisk händelseutveckling

{tidslinje_text}

### Medicinska förhållanden
{self.data.get('medicinska_forhallanden', '[Beskriv medicinska förhållanden]')}

### Yrkesmässiga förhållanden
{self.data.get('yrkesmassi ga_forhallanden', '[Beskriv yrkesmässiga förhållanden]')}

---

---

## Sektion 7

## 3. BEVISNING

### Medicinsk bevisning
{medicinska_text}

### Omständighetsbevisning
{omstandighets_text}

### Ekonomisk bevisning
{ekonomiska_text}

**Samtliga bevis är bifogade detta överklagande och åberopas till fullo.**

---

---

## Sektion 8

## 4. RÄTTSLIG ANALYS

[RÄTTSLIG ANALYS SAKNAS - Komplettera baserat på ärendespecifika omständigheter]

---

---

## Sektion 9

### {kod}: {namn}

**Rättslig grund:** {lagrum_text}

{beskrivning}

**Tillämpning på detta ärende:**
{m.get('tillampning', '[Beskriv hur mönstret tillämpas på detta specifika ärende]')}

---

## Sektion 10

1. Upphäver Försäkringskassans beslut.
2. Återförvisar ärendet för förnyad handläggning.
3. Tillerkänner ersättning för rättegångskostnader.

---

## Sektion 11

## 5. SLUTSATS & SAMMANFATTNING

### Sammanfattande bedömning
Försäkringskassan har genom sitt beslut brutit mot grundläggande förvaltningsrättsliga principer. De fel som redovisats i den rättsliga analysen utgör var och en för sig, och särskilt sammantagna, grund för att upphäva beslutet.

{klient} har dokumenterat:
- Bristande utredning enligt FL 23 § och SFB 110:13 §
- Felaktig rättstillämpning
- Processuella fel i handläggningen
- Ekonomisk skada till följd av felaktigt beslut

### Sammanfattning av yrkanden
Med stöd av ovanstående yrkar {klient} att Förvaltningsrätten:

{yrkanden_text}

---

**Datum:** {datetime.now().strftime('%Y-%m-%d')}

**{klient}**

**Ombud:** {self.data.get('ombud_namn', '[Ombuds namn]')}

---

**Bilagor:**
{self._generera_bilagor_lista()}

---

---

## Sektion 12

- Bilaga 1: Överklagat beslut från Försäkringskassan
- Bilaga 2: Läkarintyg
- Bilaga 3: Övriga handlingar

---

