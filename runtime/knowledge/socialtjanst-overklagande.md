---
module_id: sfcae-socialtjanst-overklagande-v1
version: "1.0"
status: DOMAIN_REFERENCE
role: progressive_disclosure
binds_to: L1 signal SoL|LSS|LVU|LVM|socialnämnd|IFO
does_not_replace: FalsificationEngine|Audit A/B/C|canonical FSM
hard_stop_mapping: core_types.HardStopCode
---

# SOCIALTJÄNST — ÖVERKLAGANDE / GRANSKNING (domain)

Källstyrd kunskapsmodul för **kommunal** socialtjänst. Laddas endast vid L1-match.
Ersätter **inte** canonical, FalsificationEngine eller Audit A/B/C — tillför rekvisit,
attackmallar och utdataformat under befintliga faser.

## Forum (HS06 vid korsning)

**Tillåtet:** FPL + SoL / LSS / LVU / LVM (kommun / socialnämnd / IFO).  
**Blockerat:** FK, Migrationsverket, CSN, LÖF, JK som primär forum — `HS15`/`HS06` enligt core_types.

### L1-signaler
ENTITETER: socialnämnd, socialtjänst, IFO, socialsekreterare, kommunen, SoL, LSS, LVU, LVM  
TERMER: bistånd, ekonomiskt bistånd, insats, omhändertagande, riksnorm, personlig assistans, daglig verksamhet  
DIARIE: SN-ÅÅÅÅ-NNNN | IFO-ÅÅÅÅ-NNNN

## Hard-stop-mappning (ena semantik = core_types)

| Modultext | core_types.HardStopCode | Betydelse här |
|-----------|-------------------------|---------------|
| Forumkonflikt / fel myndighet | HS15 (ev. HS06 i äldre text) | Fel processordning |
| Källunderskott MUST | HS01B / HS09 | Saknat central handling / inferens |
| Lagversion ej fastställbar | HS06 | Intertemporal |
| Otillräckligt underlag CONSTRUCTION | HS01C | Domslut/yrkande blockerat |
| Motstridig falsifiering | lämna till FalsificationVerdict + jurist | Ej ny HS-kod parallellt |

## MUST / ALT (rekvisit — gap, inte egen motor)

**MUST (saknas → gap + relevant HS):**  
1. Överklagat beslut (dnr, datum, undertecknare)  
2. Tjänsteutlåtande/utredning före beslut  
3. Klagandes identitet mot beslut  
4. Överklagandetid (FPL 23 §, 3 veckor från delgivning) — passerad → HS01C i CONSTRUCTION  

**ALT (lucka, ej automatiskt stopp):** läkarintyg, ekonomiunderlag, journal/BBIC, barnsamtal, tidigare beslut.

## Lagversionslås SoL

- SoL (2025:400) fr.o.m. 2025-07-01  
- SoL (2001:453) t.o.m. 2025-06-30  
- Okänt händelsedatum → HS06 (lagversion), inte fri gissning  

## Attackmallar (under Falsification / Audit — opartisk i AUDIT)

I **JUDGMENT_AUDIT:** formulera som *avvikelse / styrkt / påstående / gap*.  
I **JUDGMENT_CONSTRUCTION:** samma kedja får bli yrkandepunkter (processhandling).

| Kod | Trigger | Laganknytning (verifiera version) |
|-----|---------|-----------------------------------|
| SOL-01 | Utredningslucka | FL 23 §, SoL utredningsskyldighet |
| SOL-02 | Motiveringsbrist | FL 32 § |
| SOL-03 | Rättstillämpningsfel | speciallag + FL |
| SOL-04 | Utelämnat bevis i akten | FL 23 § |
| LSS-01 / LVU-03 | Proportionalitet | FL 5–6 §§, LVU |
| LVU-02 | Barnets bästa / åsikt | SoL, LVU, barnkonventionen art. 12 |
| LSS personkrets | Ofullständig 1 § LSS-bedömning | LSS + praxis via LEGAL_SOURCE_RECORD |
| SOL-05 | Riksnorm/beräkning | SoL ekonomiskt bistånd |

Efter attacksekvens: **COUNTER_AUDIT** (befintlig fas) — kan myndigheten försvaras på annan grund?

## Citatkrav

`"[ordagrant]"` (Källa: fil, sida, datum, tjänsteman). Saknas ankare → GAP, ingen parafras som fakta.

## Utdata (renderer-mall, FULL_JURIST)

CONSTRUCTION: yrkanden → faktabakgrund/kronologi → identifierade fel (mall ovan) → bevisförteckning → GAP_LIST → sammanfattning.  
AUDIT: totalvärdering LAGLIGT | FORMELLT_FEL | MATERIELLT_FEL | EJ_VERIFIERBART | OTILLRÄCKLIGT_UNDERLAG — neutral ton.

## Körregler

- Aktiveras endast vid L1 socialtjänst-signal  
- Aldrig ersätta canonical entrypoint  
- AUDIT opartisk; CONSTRUCTION får skarp processhandling  
- COUNTER_AUDIT obligatorisk i adversarial grind  
- Ingen spekulation; luckor i GAP_LIST  
