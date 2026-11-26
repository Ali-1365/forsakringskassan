# RÄTTSTIDSKONTROLL — 8-stegskedja (FIX-T)
## Aktiveras vid: lagändring, övergångsbestämmelse, intertemporal, lex mitior

1. Identifiera SFS-nr + paragraf  
2. Händelsedatum (materiell rätt)  
3. Rättegångsdatum (processuell rätt)  
4. Lydelse vid händelsedatum  
5. Lydelse vid rättegångsdatum  
6. Ändringsförfattningar  
7. Övergångsbestämmelser  
8. Bedöm temporal påverkan → PÅVERKAR / PÅVERKAR EJ / KAN EJ AVGÖRAS  

HS06 om lydelse inte kan fastställas.

---

## FULLSTÄNDIGT PROTOKOLL

Källa: SKILL\arkitektur\SKILL_Olika.zip → KONSOLIDERAD_ARKITEKTUR/references/rättstidskontroll-protokoll.md (2026-09-05). Porterat oförändrat nedan; sammanfattningen ovan är sfcae:s tidigare innehåll och behålls.

> Notera (sfcae 2026-10-09): i sfcae utförs kontrollen av integrations/rattstids_bridge.py → lagskifte_validator; Motor B:s RättstidskontrollAgent är ersatt (se POST_HISTORICAL_VERIFICATION_ADDENDUM §3 rad 6).

## 0l. RÄTTSTIDSKONTROLL-PROTOKOLL (NY v10.3-UPDATED)

### Syfte
Säkerställa att rätt lagversion tillämpas vid rätt tidpunkt.
Systemet frågar ALDRIG bara "Vilken lag gäller?" utan alltid:
- "Vilken lydelse gällde när den rättsligt relevanta händelsen inträffade?"
- "Vilken lydelse gäller vid rättegångsdatum?"

### 8-STEGSKEDJA PER LAGRUM

```yaml
RÄTTSTIDSKONTROLL_8_STEG:

  steg_1:
    uppgift: Identifiera SFS-nummer och exakt paragraf
    output: "[SFS-nummer § X stycke Y]"
    källa: Riksdagen.se / SFS-register

  steg_2:
    uppgift: Fastställ händelsedatum (materiell rätt)
    output: "[ÅÅÅÅ-MM-DD] – datum för den rättsligt relevanta händelsen"
    regel: Materiell rätt = lagversion vid händelsedatum

  steg_3:
    uppgift: Fastställ rättegångsdatum (processuell rätt)
    output: "[ÅÅÅÅ-MM-DD] – datum för förhandling eller beslut"
    regel: Processuell rätt = lagversion vid rättegångsdatum

  steg_4:
    uppgift: Hämta lydelse vid händelsedatum (SEARCH_02)
    output: "[exakt lagtextlydelse] | Datum: [ÅÅÅÅ-MM-DD] | Källa: Riksdagen.se"
    verktyg: SEARCH_02 – historiska versioner

  steg_5:
    uppgift: Hämta lydelse vid rättegångsdatum (SEARCH_02)
    output: "[exakt lagtextlydelse] | Datum: [ÅÅÅÅ-MM-DD] | Källa: Riksdagen.se"
    verktyg: SEARCH_02 – aktuell version

  steg_6:
    uppgift: Kontrollera ändringsförfattningar mellan datumen
    output: "[lista SFS-nummer för ändringar mellan händelsedatum och rättegångsdatum]"
    källa: Riksdagen.se ändringsförteckning

  steg_7:
    uppgift: Kontrollera övergångsbestämmelser
    output: "[finns / saknas / SAKNAS_EJ_VERIFIERBART]"
    regel: Övergångsbestämmelser kan föreskriva annan tillämpning

  steg_8:
    uppgift: Identifiera om lagändring påverkar bedömningen
    output: "[PÅVERKAR / PÅVERKAR EJ / KAN EJ AVGÖRAS]"
    vid_påverkan: Flaggas som MÖJLIGT_RÄTTSFEL om fel version tillämpats
```

### OUTPUTFORMAT

```yaml
RÄTTSTIDSKONTROLL:
  lagrum:                  "[SFS-nummer § X]"
  händelsedatum:           "[ÅÅÅÅ-MM-DD]"
  lydelse_vid_händelse:    "[exakt text] | Datum: [ÅÅÅÅ-MM-DD] | Källa: Riksdagen.se"
  rättegångsdatum:         "[ÅÅÅÅ-MM-DD]"
  lydelse_vid_rättegång:   "[exakt text] | Datum: [ÅÅÅÅ-MM-DD] | Källa: Riksdagen.se"
  ändringsförfattningar:   "[lista SFS-nummer | INGA]"
  övergångsbestämmelser:   "[finns | saknas | SAKNAS_EJ_VERIFIERBART]"
  temporal_påverkan:       "[PÅVERKAR | PÅVERKAR EJ | KAN EJ AVGÖRAS]"
```

### TEMPORALREGLER

```yaml
TEMPORALREGLER:

  materiell_rätt:
    regel: Lagversion vid händelsedatum

  processuell_rätt:
    regel: Lagversion vid rättegångsdatum

  undantag:
    övergångsbestämmelser: Kan föreskriva annan tillämpning
    lex_mitior:
      regel: Förmånligare lag tillämpas (BrB 5 §)
      tillämpning: Brottmål – om ny lag är förmånligare för den tilltalade
      kontroll: Alltid vid brottmål där lagändring skett under processen

  vid_osäkerhet:
    output: "[KAN EJ VERIFIERAS – TEMPORAL KONTROLL KRÄVS]"
    hs_kod: HS06 (lagversion kan inte fastställas)
```

### ABSOLUTA REGLER

```
❌ ALDRIG: Anta att aktuell lagversion gällde vid händelsedatum
❌ ALDRIG: Hoppa över kontroll av ändringsförfattningar
❌ ALDRIG: Ignorera övergångsbestämmelser
✅ ALLTID: Dubbel verifiering – händelsedatum OCH rättegångsdatum
✅ ALLTID: Lex mitior kontrolleras vid brottmål med lagändring
✅ ALLTID: KAN EJ VERIFIERAS om lydelse inte kan fastställas
```

`[RÄTTSTIDSKONTROLL-PROTOKOLL | v10.3-UPDATED | LOCKED]`

---
