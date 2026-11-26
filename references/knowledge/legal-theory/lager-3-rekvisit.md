## LAGER 3 – LJUDFORENSIK

**Aktiveras om ljudmaterial finns. Separat beviskedja – aldrig blandad med skriftlig analys.**

### Hearing audit – 6 steg + 4 specialkontroller

```yaml
hearing_audit:
  stage_1: identifiera domens påstående [DOM-ID | SIDA]
  stage_2: lokalisera motsvarande passage i ljudfilen [AUDIO-ID | TIDSKOD]
  stage_3: transkribera endast hörbar text
  stage_4: jämför domens formulering med originaluttalandet
  stage_5: identifiera eventuella utelämnade eller tillagda uppgifter
  stage_6: bedöm om en faktisk avvikelse kan verifieras

  special_controls:
    negation_control:      Kontrollera om nekanden utelämnats
    qualification_control: Kontrollera om reservationer utelämnats
    attribution_control:   Kontrollera att rätt talare tillskrivs rätt uppgift
    context_control:       Kontext lokaliserar men konstruerar aldrig ohörbart innehåll
```

### Absoluta regler

- Domens formulering får **aldrig** användas för att rekonstruera vad som sägs i ljud
- Talare identifieras endast via verifierad metadata eller förhandlingsordning
- Tonfall, paus, tystnad och skratt tolkas aldrig som bevis för avsikt
- [OHÖRBART] bevaras oförändrat genom alla lager – fylls aldrig i

`[L3 | LJUDFORENSIK | LOCKED om ljud]`

---