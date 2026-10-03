# CLAUDE.md — 60 TPD Furnace SFC Optimization

Context for anyone (human or Claude) working in this repo. Read this first.

## Objective

Reduce the **Specific Fuel/Energy Consumption (SFC)** of the **60 TPD flint glass melter** by **2% versus the client baseline**, without hurting glass quality or furnace life.

- Furnace: 60 TPD melter, flint glass ("MOLTEN GLASS 60 TPD FLINT-III" in SAP)
- Production lines fed by this furnace: **S09, S10, S11, S12**
- Scope: **melter only** (melter NG + melter boost + barrier boost). Forehearth energy is **not** in the SFC.

## SFC definition (client formula — do not change without agreement)

```
SFC (kcal/kg) = [ NG (SCM) × NCV (kcal/SCM) + (Melter boost kWh + Barrier boost kWh) × 860 ] / Draw (kg)
```

- Calculated per day. Draw = SAP MB51, movement type 101, "Glass given to Quality" (pulled molten glass, not packed ware).
- Electricity is counted at 860 kcal/kWh, so shifting heat from gas to electric boost lowers SFC by definition (cost is a separate question).
- When aggregating from 15-min data: compute `NG × NCV` **per interval** and then sum. Never multiply daily NG by an average NCV.

## Client baseline (from `SFC_60_TPD_Baseline_Calculation_Sep-25_to_Jul-26_updated.xlsx`)

| Item | Value |
|---|---|
| Baseline period | 1 Sep 2025 – 31 Jul 2026 (334 days, no gaps) |
| Baseline SFC | **1,576.3 kcal/kg** (simple average of daily SFC) |
| Overall 2% target | **1,544.8 kcal/kg** |
| Weighted SFC (Σenergy / Σdraw) | 1,573.2 kcal/kg |
| Average draw | 57.4 t/day (range 47.8–62.4) |

Draw-band targets (client "SFC Executive" sheet):

| Draw band (t) | Days | Avg SFC | 2% target |
|---|---|---|---|
| 45–50 | 6 | 1,765 | 1,730 |
| 50–55 | 63 | 1,663 | 1,629 |
| 55–60 | 185 | 1,565 | 1,534 |
| 60–65 | 80 | 1,520 | 1,490 |

Workbook sheets: Cover, Master Data – Energy & SFC Calc, SFC Executive, Draw Data, Draw Bucket Analysis, Daily Variation Analysis, Energy Data & SFC Calc (2) (hidden; used by the analysis sheets).

## Early findings from the baseline (daily data only — to be confirmed)

1. **Draw dominates SFC** (r = −0.88). Fit: `Energy (Gcal/day) ≈ 55.4 + 0.608 × Draw (t)` → ~60% of energy is fixed. +1 t/day draw ≈ −1% SFC. So SFC must be judged **draw-normalized**, not on the raw average.
2. **Draw-adjusted SFC drifted up through the year**: Sep-25 1,527 → Mar-26 1,593 at the same 57.2 t draw; Jul-26 ≈ 1,652. From today's level, absolute 1,544.8 is a ~6–7% cut, not 2%.
3. **Barrier boost fell** from ~10,800 kWh/day (Sep-25) to ~6,900 (Jul-26). In the data, 1 Gcal more boost displaced ~1.6 Gcal gas (correlation, not proven cause).
4. **NCV compensation is partial**: NG volume moves against NCV (r = −0.70), but at the same draw and boost, gas energy still rises ~0.45 Gcal/day per +1,000 kcal/SCM NCV, i.e. over-firing on high-NCV days. Daily NCV ranged 8,822–10,431 kcal/SCM.
5. Residual day-to-day noise after the draw effect is ~1.8% of energy, about the size of the target. Any trial needs ~30–40 days to prove 2%.

## Data inventory

| Data | Frequency | Status |
|---|---|---|
| NG flow, NCV, melter boost, barrier boost | 15 min | Promised by client, not yet received |
| Bottom temperature | 1 min | Promised, not yet received |
| Crown temperature | 1 hour (asking for 1 min) | Promised, not yet received |
| Draw (SAP) | Daily | Received (in baseline workbook) |
| Daily energy & SFC | Daily | Received (baseline workbook) |
| Cullet %, line status S09–S12, O₂/combustion air, limits, quality | — | **Requested**: see `docs/02_plant_team_data_request.md` |

## Repo layout

```
CLAUDE.md                              this file
docs/01_methodology.md                 full approach (baseline → diagnostics → ML → optimization → trial)
docs/02_plant_team_data_request.md     questionnaire / data request for the plant team
docs/03_plant_meeting_questions.md     meeting guide: questions with "why" and "listen for"
data/raw/                              client files exactly as received (never edit in place)
data/raw/README.md                     expected files, naming, column formats
```

Planned later: `data/processed/` (cleaned, aligned data), `notebooks/` (EDA), `src/` (pipeline, models).

## Working rules

- **Never modify files in `data/raw/`.** Write cleaned outputs to `data/processed/`.
- Keep timestamps in plant local time (IST) and record the SAP production-day boundary once known.
- Reconcile first: summed 15-min energy must reproduce the client's daily SFC before any modelling.
- Use **time-based** train/test splits (no random shuffle). Prefer interpretable models first (regression, GBM + SHAP).
- Report savings as **draw-normalized SFC versus the baseline model** (IPMVP-style M&V), alongside the client's draw-band view.
- Quality (seeds/blisters) and refractory limits (crown max, bottom temp band, electrode limits) are hard constraints. Never recommend energy cuts that break them.
- Use units consistently: NG in SCM, NCV in kcal/SCM, electricity in kWh, energy in kcal (or Gcal), draw in kg or t (say which), SFC in kcal/kg.

## Open questions for the client

Tracked in detail in `docs/02_plant_team_data_request.md`. The most important:
1. Which target is official: absolute 1,544.8, the draw-band targets, or a draw-normalized target?
2. Daily cullet % for the baseline period.
3. Why barrier boost was reduced, and what the electrode/kW limits are.
4. Line running status for S09–S12 and the job-change log.
5. How the daily NCV is calculated, the SAP day boundary, and whether draw is measured or calculated.
