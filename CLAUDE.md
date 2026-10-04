# CLAUDE.md — 60 TPD Melter SFC Optimization (gas + barrier-boost recommender)

Read this first. It records what we are building, what the data means, what has already been analysed (so it is **not** repeated), and what is still open. **Update the "Notebook registry" and "Findings" sections whenever a notebook is added or changes a conclusion.**

---

## 1. Objective

Reduce **SFC of the 60 TPD flint melter by 2%** versus the client baseline, by giving operators recommended setpoints. Glass quality (seeds) and furnace limits must hold.

- Furnace feeds lines **S09, S10, S11, S12**. Scope is **melter only** (melter NG, melter boost, barrier boost); forehearths are excluded.
- **SFC formula (client, do not change):**
  ```
  SFC (kcal/kg) = [ Σ NG_scm × NCV_kcal/scm  +  (Σ Barrier_kWh + Σ Melter_kWh) × 860 ] / Draw_kg      (per day)
  ```
  Compute `NG × NCV` per interval, then sum. Never multiply daily NG by an average NCV.
- **Baseline (client workbook):** 1 Sep 2025 – 31 Jul 2026, average daily SFC **1,576.3 kcal/kg** → target **1,544.8 kcal/kg**. The client also sets 2% targets per draw band: 45–50 t: 1,730 · 50–55 t: 1,629 · 55–60 t: 1,534 · 60–65 t: 1,490.

## 2. What the plant wants (from `Sheet1` of the analytical record + plant meeting)

Two recommendation models. Operators change NG roughly every 15 min, when NCV updates.

| Model | Automated input | Operator input | Recommends |
|---|---|---|---|
| **1. Gas** | NCV (UEMS, MQTT, every 15 min) | Draw (day), optical crown temp, cullet % (day) | **NG flow** and **air-fuel ratio** (→ secondary air) |
| **2. Electricity** | MB3 bottom temp (DCS autoloader) | Draw (day), cullet % (day) | **Barrier boost (kWh)** |

- Plant also has **threshold limits for gas, boosting and temperatures**. We still need the values (open question Q4).
- **Melter boost** sits on a few fixed levels (57.2 → 76.4 → 95.5 kWh per 15 min) because it runs under the burners. Use it as a known input; don't recommend it.
- **Crown temperature:** two sensors, the pyrometer (**optical, primary**) and thermocouple **TC MC3**. Plant guidance: use both if the offset is constant and useful, otherwise optical only. Decision is in Findings F4.

## 3. Data (all in `data/raw/`, never edit; cleaned data in `data/processed/`)

| File | Content | Frequency / period |
|---|---|---|
| `Analytical_Record_Creation_EE_60TPD_updated-2.xlsx` | Sheet `result`: main 15-min record. Sheet `Sheet1`: plant's model design | 15 min, 1 Sep 2025 – 30 Sep 2026 |
| `DCS_60_TPD_MelterCrown3.xlsx` | Crown thermocouple TC MC3 (`dcs_60_DateTime`, rows newest first) | 1 min, 1 Sep 2025 – 1 Oct 2026 |
| `SFC_60_TPD_Baseline_Calculation_Sep-25_to_Jul-26_updated.xlsx` | Client baseline: daily NG, NCV, boosts, SAP draw, SFC, draw-band targets | Daily, 1 Sep 2025 – 31 Jul 2026 |

### Column dictionary (15-min record → short name used in code)

| Raw column | Short name | Meaning / unit (inferred, see Q1) |
|---|---|---|
| `Timestamps` | `ts` | 15-min timestamp (interval start assumed) |
| `BARRIER BOOSTER-52` | `bb_kwh` | Barrier boost energy, **kWh per 15 min** (Σ96 = baseline daily kWh, ratio 1.002) |
| `MELTER BOOSTER-51` | `mb_kwh` | Melter boost energy, **kWh per 15 min** (ratio 1.000) |
| `NCV Meter` | `ncv` | Gas NCV, kcal/SCM |
| `Cullet %` | `cullet_pct` | Cullet % of the day (only 16–20, changes about monthly) |
| `Melter Optical Temperature` | `opt_temp` | Pyrometer crown temp, °C. **Manual hourly reading**, integers, carried forward |
| `dcs_60_SecondaryAirFlowvalueFTSAFPVDB205DD92` | `sec_air` | **Secondary (combustion) air** flow, same per-15-min basis as NG. The plant calls it "secondary gas", but it is air (Q2) |
| `dcs_60_MelterGasflowvalueFTMGFPVDB202DD92` | `ng_scm` | Melter natural gas, **SCM per 15 min** (Σ96 = baseline daily SCM, ratio 1.005) |
| `dcs_60_ThermocoupleMelterBottom3TCMB3PVDB249DD572` | `mb3_temp` | Melter bottom temp TC MB3, °C (~1,320 ± 2) |
| `Air_Fuel_Ratio` | `afr` | Exactly `sec_air / ng_scm` (volume ratio, median 12.2) |
| `Seed Count` / `Seed Count Specs` | `seed_count` / `seed_spec` | Daily seed count; spec "30.0 each" (mean 14.8; 1 day of 395 above 30) |
| `MB51_Quantity_KG (Draw)` | `draw_kg` | SAP daily draw, repeated on every row of the day |
| `SFC (kcal/kg)` | `sfc_record` | Client's daily SFC. **Don't use:** wrong while NCV = 0. Recompute instead |

Crown file: `dcs_60_ThermocoupleMelterCrown3TCMC3PVDB249DD202` → `crown_tc` (°C, ~1,567).

## 4. Cleaning rules (implemented in `src/data_prep.py`, evidence in notebook 01)

1. **Duplicate timestamps:** 5,472 timestamps appear twice, and the copies differ **only in `opt_temp`**. Keep one row per timestamp and average `opt_temp`.
2. **Zeros = sensor not working → NaN** (flag columns `*_bad`). Valid ranges:
   - NCV 7,000–11,500
   - optical 1,550–1,600 (typos like 2576, 15757, 15722, 1674, 1474)
   - melter boost 1–200 (one spike of 538)
   - barrier boost 1–250
   - crown TC 1,400–1,700
3. **NCV = 0 from 1 Sep to 6 Oct 2025** (856 h), plus missing 6–8 Oct 2025 and 13–16 Jul 2026. For daily SFC, days with < 90% NCV coverage use the **baseline workbook's daily NCV** (`ncv_source='baseline'`, 44 days). Exclude these days when training the gas model.
4. **Draw:** the record doubles the draw on 2025-10-01 and 2026-06-01, so the baseline workbook draw is used wherever it exists. **Draw for Sep 2026 is missing** (Q5).
5. NG, air and MB3 share 21 DCS gaps (≤ 11 h). Interpolate gaps ≤ 1 h for energy totals; leave longer gaps as NaN. `day_complete` = NG and boost coverage ≥ 90% and draw present.
6. AFR is recomputed from the cleaned flows. Crown TC is averaged from 1 min to 15 min (interval start).
7. **Reconciliation check passed:** recomputed daily SFC vs the client's daily SFC on 329 complete days: median ratio **0.999** (p05 0.985, p95 1.013). The few days off by > 3% are where the DCS gas total differs from the SAP gas total.

## 5. Findings so far (keep updated; don't re-derive)

| # | Finding | Evidence | Implication |
|---|---|---|---|
| F1 | **Draw drives SFC** (r ≈ −0.88): `Energy/day ≈ 55.4 Gcal + 0.608 Gcal × draw_t`, so ~60% of energy is fixed; +1 t/day ≈ −1% SFC | Baseline workbook | Judge the 2% **draw-normalized** (and by client draw bands), never on the raw average |
| F2 | Draw-adjusted SFC rose through the year: Sep-25 ~1,527 → Mar-26 ~1,593 at the same 57.2 t → Jul-26 ~1,650. **Aug-26 recovered to 1,563 at 59.7 t** | nb01 §7 monthly table | The baseline average includes a deterioration. Check what changed in Aug-26 (boost back up, AFR down) |
| F3 | **NCV compensation is partial and lagged.** Hourly NG tracks NCV level (r −0.80), but within a day NG moves only **~73%** of what exact heat compensation needs, with ~1 h lag | nb01 §8 | Recommending `NG = Q_required / NCV` removes the drift. **Lever 1** |
| F4 | **Optical vs TC MC3:** offset +7.6 °C (daily sd 1.0), drifting +6.9 → +8.8 °C over the year; hourly correlation ≈ 0.03. Optical is held flat at ~1,574.5 (daily sd 0.5) | nb01 §6 | **Optical = primary.** TC = gap-filler (`opt ≈ TC + monthly offset`) and a 1-min feature for furnace response. History can't show what a lower crown setpoint does, so that needs a step trial |
| F5 | **15-min NG has a sawtooth** (autocorrelation peak at lag 7 ≈ 105 min), likely the regenerator reversal (~20–21 min) aliased by 15-min sampling | nb01 §8 | 15-min NG is noisy. **Model gas at 1-h resolution**, and apply the NCV correction every 15 min (Q3) |
| F6 | **AFR median 12.2** (11.2–13.3) and it **tracks NCV** (hourly r 0.88), so air per unit of gas heat is held nearly constant at **1.27 ± 0.03 SCM air per Mcal**. Natural-gas stoichiometric air is roughly 1.1 SCM/Mcal (to confirm with gas composition), which puts excess air at about **15%** | nb01 §8 | Air already scales with heat. Recommend AFR = target air-per-Mcal × NCV/1000 and test lowering the target (e.g. 1.27 → 1.22). **Lever 2**; confirm with flue O₂ |
| F7 | **Seeds have headroom:** mean 14.8 against a spec of 30 (1 day above) | nb01 §8 | Room for a small optical setpoint reduction trial. **Lever 3** |
| F8 | **Barrier boost** fell from ~10,900 kWh/day (Sep-25) to ~6,900 (Jul-26), then rose to ~10,400 (Aug-26). In the baseline regression, 1 Gcal boost displaced ~1.6 Gcal gas | nb01 §7, baseline | Boost is a substitute for gas, and the SFC formula favours it. **Lever 4**, within electrode limits |
| F9 | Cullet only changes about monthly (16–20%); MB3 varies ±2 °C; seeds are only weakly correlated with anything (all |r| < 0.16) | nb01 | Cullet is a slow covariate. Weak seed correlations mean the quality guard-rail is best handled as a limit, not a model |

## 6. Approach to the 2%

**Core idea:** a model trained to copy what operators did reproduces the baseline. To save energy, the recommender must (a) apply physics exactly where operators are imperfect (NCV, air), and (b) aim at the **efficient** historical operation for the same conditions, within limits.

1. **Baseline & M&V** (nb02). Draw-normalized expected daily energy = f(draw, cullet, month/age). The saving is expected minus actual; report it alongside the client's draw-band table. Add Aug–Sep 2026 as the "current state" check.
2. **Hourly modelling table** (nb03). Hourly means/sums of the 15-min data, plus crown TC, lags (1–8 h) of gas heat, boosts and temperatures, and day-level draw/cullet. Drivers, best-days (lowest normalized SFC with seeds within spec), AFR vs NCV, and NCV-compensation simulation.
3. **Gas model (Model 1)** (nb04). Predict the **required gas heat** `Q_gas (kcal/h) = f(draw, cullet, optical target, MB3, barrier+melter boost, lags)`.
   - Fit it to the efficient frontier (quantile regression at ~P30–P40 and/or best-days training), not the mean.
   - Recommendation: `NG_scm per 15 min = Q_gas / 4 / NCV_now`, recomputed whenever NCV updates. That gives exact NCV compensation by construction.
   - **AFR** = target air-per-Mcal × NCV / 1000 (today ~1.27 SCM/Mcal; target from efficient periods and O₂ when available). Secondary air = AFR × NG.
   - Boost must be an input to the gas model, because boost replaces gas heat (Q6).
4. **Electricity model (Model 2)** (nb05). Barrier boost kWh needed to hold MB3 in its band, given draw and cullet, again fitted to efficient operation. Then decide the gas/boost split: more boost lowers SFC (860 kcal/kWh), limited by electrode/transformer limits and cost (Q4, Q7).
5. **Joint recommendation + back-test** (nb06). Order: boost first (Model 2), then gas given that boost (Model 1).
   - Back-test on a time-based hold-out (e.g. Jun–Sep 2026): simulated SFC = Σ(recommended NG × actual NCV + (recommended BB + actual MB) × 860) / actual draw.
   - Success = ≥ 2% below actual (draw-normalized), with predicted optical/MB3 inside their bands and the thresholds respected.
   - Use the TC MC3 / MB3 response models as soft sensors for temperature.
6. **Trial** (advisory). 4–6 weeks of operators following the recommendations, with small steps (e.g. optical −1 °C, AFR −0.2 at a time), daily seed checks, and a daily M&V/CUSUM report. History alone can't prove 2% (daily noise ~1.8%), so ~30–40 trial days are needed.

**Expected levers** (hypotheses, each to be quantified in its notebook): exact NCV compensation (F3), excess-air reduction (F6), barrier-boost/gas split (F8), small optical setpoint reduction using seed headroom (F7), and running at the efficient-frontier heat for each draw band (F1/F2).

## 7. Notebook registry (update when you add or change a notebook)

| Notebook | Purpose | Status | Key outputs |
|---|---|---|---|
| `notebooks/01_data_audit.ipynb` | Raw-data audit, cleaning rules, units, optical vs TC, SFC reconciliation, first lever signals | ✅ Done | `data/processed/ar_15min_clean.parquet` (37,920 rows), `daily_clean.parquet/.csv` (395 days); findings F2–F9 |
| `notebooks/02_baseline_mv.ipynb` | Draw-normalized baseline, targets per draw band, Aug–Sep 2026 check | ⏳ Next | — |
| `notebooks/03_hourly_eda.ipynb` | Hourly feature table, drivers, best days, AFR vs NCV, NCV-compensation saving | ⏳ | — |
| `notebooks/04_gas_model.ipynb` | Model 1: required gas heat → NG = Q/NCV, AFR | ⏳ | — |
| `notebooks/05_boost_model.ipynb` | Model 2: barrier boost from MB3, draw, cullet | ⏳ | — |
| `notebooks/06_backtest_recommender.ipynb` | Joint recommender, guardrails, simulated SFC saving | ⏳ | — |

**How to use processed data:** `pd.read_parquet('data/processed/ar_15min_clean.parquet')` (index `ts`) and `daily_clean.parquet` (index `date`). To rebuild them, run notebook 01 or `import data_prep as dp; q = dp.clean_15min(); d = dp.build_daily(q); dp.write_processed(q, d)`. Key daily columns: `sfc`, `energy_kcal`, `gas_kcal`, `elec_kcal`, `ncv_used`, `ncv_source`, `day_complete`, `base_*` (client values).

## 8. Open questions (ask the user / plant; record answers here)

| # | Question | Why it matters | Answer |
|---|---|---|---|
| Q1 | NG and secondary-air tags: are values **SCM per 15 min** (Σ96 matches daily SCM) or a rate? Instantaneous snapshot or 15-min average? | Units for recommendations; aliasing in F5 | |
| Q2 | "Secondary gas" column is `SecondaryAirFlow`, and AFR = air/gas. Is it combustion air? Any other air (primary/atomising)? Is flue **O₂** measured? | AFR recommendation and excess-air lever | |
| Q3 | Furnace type and **reversal time** (F5 suggests ~20–21 min) | Choose the model resolution, avoid aliasing | |
| Q4 | **Threshold limits** (Sheet1): NG min/max, barrier boost min/max, optical band, MB3 band, electrode/transformer limits | Hard constraints in the recommender | |
| Q5 | **Sep 2026 draw** (missing) | SFC for Sep 2026 | |
| Q6 | OK to include boost (and melter boost) as an input to the gas model? | Boost replaces gas heat; without it, gas recommendations are biased | |
| Q7 | Is shifting heat from gas to boost acceptable (cost)? Gas vs electricity price per Gcal | Gas/boost split | |
| Q8 | Optical log: who records it and when? Missing days fall on days 1–12 of months (possible DD/MM swap) and there are duplicates. Can we get the raw log? | Optical is a model input | |
| Q9 | Seed count definition (per what sample?) and whether 30 is the max spec | Quality guard-rail | |
| Q10 | Target confirmation: absolute 1,544.8 vs draw-band targets vs draw-normalized; training period to include Aug–Sep 2026? | Success criterion | |

## 9. Working rules

- Never modify `data/raw/`. All cleaning goes in `src/data_prep.py`; notebooks import it (`sys.path.insert(0, '../src')`).
- Timestamps are plant local time. Daily = calendar day 00:00–24:00, matching the SAP draw date (confirm the SAP day boundary).
- **Time-based** train/test splits only. Prefer interpretable models (linear/quantile regression, GBM + SHAP).
- Quality and limits are hard constraints. Never recommend a setpoint outside the plant thresholds.
- Units: NG in SCM per 15 min, NCV in kcal/SCM, boosts in kWh per 15 min, energy in kcal/Gcal, draw in kg, SFC in kcal/kg.
- Charts: reference palette (blue `#2a78d6`, orange `#eb6834`), one y-axis per chart, recessive grid.
- Environment: `pip install -r requirements.txt`.

## 10. Repo layout

```
CLAUDE.md                      this file (project memory)
requirements.txt
src/data_prep.py               loading + cleaning + daily SFC (single source of truth)
notebooks/01_data_audit.ipynb  executed, with outputs
data/raw/                      client files as received (+ README.md)
data/processed/                cleaned outputs written by notebook 01
docs/01_methodology.md         earlier generic methodology (before the plant's 2-model design; sections on NCV logic still valid)
docs/02_plant_team_data_request.md  earlier data request list
```
