# HS15 — Falsification VULNERABLE

## Vad det betyder
`falsification_verdict: VULNERABLE` innebär att L12-fasen
(Falsifikation / Counter-Audit) identifierade minst ett argument
som kan motverka den primära analysen utan att vara tillräckligt bemött.

## Konsekvens
- `_output_hard_stop_text = True` (spärrar textproduktion)
- Pipeline FORTSÄTTER (ej chain-abort)
- Advokatlagret varnar juristen explicit

## Åtgärd för juristen
1. Granska `gap_list` för identifierade svagheter
2. Inhämta kompletterande underlag
3. Bemöt motargumenten explicit i inlagan

## Koppling
- `HS15` registreras i `state.hard_stops`
- `_output_hard_stop_text(state)` returnerar True
- `advocacy_bridge` returnerar `OUTPUT_SPÄRD` utan override
