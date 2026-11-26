---
module_id: fk-sfb-arbetsskada
version: "1.0"
status: DOMAIN_REFERENCE
forum: FK | förvaltningsrätt | SFB | arbetsskada | livränta
does_not_replace: canonical | socialforsakring_lager
kodtabell: config/kodsystem_fk_sfb.yaml
---

# FK / SFB / arbetsskada — domain

## Kodsystem

Skanna text med:

```python
from kodsystem_scanner import skanna_text
from kodsystem_runner import run_kodscan_if_requested

r = skanna_text(text, kodtabell_path="config/kodsystem_fk_sfb.yaml", domän="FK_SFB")
# eller
run_kodscan_if_requested(state, requested=True, kodtabell_path="…/kodsystem_fk_sfb.yaml", domän="FK_SFB")
```

Koder: FK-00…FK-11 (ärendesteg), BD-01…BD-05 (bedömning), DOK-*, ERR-01…ERR-06 (felindikation), KOM-*.

## Regler i SFCAE

- ERR-* är **indikation** för granskning, inte automatisk ogiltigförklaring.
- AI-stöd (semantik/klassning) får inte ersätta FL 32 §-motivering utan mänsklig kontroll (jfr ERR-05).
- Arbetsskada/livränta: rekvisit och kausalitet via akt + rättskälla — ingen hårdkodad “100 % skada”.
- Patientskada (LÖF) och JK-skadestånd är **andra forum** — aktivera inte FK-modulen som enda sanning där (HS06/forumvakt).

## Relaterade filer

- `runtime/socialforsakring_lager.py`
- `references/socialforsakring-modul.md`
- `references/diagnostikblock-medicinsk.md`
- `references/patientskada-skadestand.md`


## V2-mönster & entiteter

```python
from fk_pattern_runner import run_fk_pattern_if_requested
r = run_fk_pattern_if_requested(text="...", requested=True)
# kodscan + datum/diarie/lagrum/belopp/person_hint
```

Se även `references/no-speculation-court-ready.md`.
Överklagande-/JK-generatorer med hårdkodad klientdata ingår **inte** i SFCAE-kärnan.
