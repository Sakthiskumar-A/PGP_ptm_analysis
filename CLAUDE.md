# CLAUDE.md — 60 TPD Melter SFC Optimization (gas + barrier-boost recommender)

Read this first. It records what we are building, what the data means, what has already been analysed (so it is **not** repeated), and what is still open. **Update the "Notebook registry" and "Findings" sections whenever a notebook is added or changes a conclusion.**

---

## 1. Objective

Reduce **SFC of the 60 TPD flint melter by 2%** versus the client baseline, by giving operators recommended setpoints. Glass quality (seeds) and furnace limits must hold.

- Furnace feeds lines **S09, S10, S11, S12**. Scope is **melter only** (melter NG, melter boost, barrier boost); forehearths are excluded.
- **SFC formula (client, do not change):**
  ```
  SFC (kcal/kg) = [ Σ NG × NCV  +  (Σ Barrier_kWh + Σ Melter_kWh) × 860 ] / Draw_kg      (per day)
  ```
  Compute `NG × NCV` per interval, then sum. Never multiply daily NG by an average NCV.
- **Client baseline:** 1 Sep 2025 – 31 Jul 2026, average daily SFC **1,576.3 kcal/kg** → target **1,544.8**. **We reproduced it from raw data: 1,576.6** (nb03).
- **Success criterion (user, 2026-10-04):** per draw band (5-t bands, −2% each) **or** draw-adjusted (−2% vs baseline model at the same draw and cullet). Both are computed in nb03–nb05.

## 2. What the plant wants and how the furnace works

| Model | Automated input | Operator input | Recommends | Frequency |
|---|---|---|---|---|
| **1. Gas** | NCV (UEMS, MQTT, 15 min) | Draw (day), optical crown temp (**guard-rail only**, see F14), cullet % (day); **actual boost read from DB** | **NG flow**, **air-fuel ratio** (→ secondary air) | every 15 min / per reversal cycle |
| **2. Electricity** | MB3 bottom temp (DCS) | Draw (day), cullet % (day): not needed by the chosen controller; melter boost not needed either (F13) | **Barrier boost** | every hour |

- **Furnace:** regenerative, **2 inlets/ports**. Each carries NG + secondary air; while one fires, the other is the exhaust. They switch on a **20-min timer**. The operator sets **one NG flow for both inlets** (common header) anywhere in the **minute 15–20 window** of each cycle. So the recommendation must be ready by minute 15, using the latest NCV.
- **Units:** recommend in the **same unit as the workbook column**. The operator enters that value; no conversion.
- **No O₂ analyser.** Air can only be recommended inside its proven historical range.
- **Limits:** use **historical limits** (P1–P99) until the plant supplies official ones.
- **Melter boost** is fixed on a few levels (57.2 → 76.4 → 95.5 kWh/15 min). It's a known input, not recommended.
- **Optical crown temperature** is typed by hand (hourly). It is the primary crown signal for operators; TC MC3 (1-min DCS) is a clean crown check.

## 3. Data (all in `data/raw/`, never edit; cleaned data in `data/processed/`)

| File | Content | Frequency / period |
|---|---|---|
| `Analytical_Record_Creation_fixed_5.xlsx` | **Corrected 15-min record (2026-10-05), used for ALL calculations** (`dp.AR_FILE`). Sheet `result` only. Optical log fixed (no swap, 24-h clock, no duplicates, no typos); draw column `Daily Draw` incl. **Sep 2026** | 15 min, 1 Sep 2025 – 30 Sep 2026 |
| `Analytical_Record_Creation_EE_60TPD_updated-2.xlsx` | First record: **evidence only** (nb02, `dp.AR_FILE_OLD`, `load_ar_raw(old=True)`). Sheet `Sheet1`: plant's model design | 15 min, 1 Sep 2025 – 30 Sep 2026 |
| `DCS_60_TPD_MelterCrown3.xlsx` | Crown thermocouple TC MC3 (rows newest first) | 1 min, 1 Sep 2025 – 1 Oct 2026 |
| `SFC_60_TPD_Baseline_Calculation_Sep-25_to_Jul-26_updated.xlsx` | Client baseline workbook. **Used only for comparison/verification**, never to fill data | Daily, 1 Sep 2025 – 31 Jul 2026 |

**Sep 2026 is the validation month** (draw arrived with the corrected file): nb04 §8, nb05 §6b, T4 §2c. It was used once to decide that optical stays out of the gas model (F14), so **Oct 2026 is the next clean check**.

### Column dictionary (15-min record → short name)

| Raw column | Short name | Meaning / unit |
|---|---|---|
| `Timestamps` | `ts` | 15-min timestamp (interval start assumed) |
| `BARRIER BOOSTER-52` | `bb_kwh` | Barrier boost, kWh per 15 min (Σ96 = SAP daily kWh) |
| `MELTER BOOSTER-51` | `mb_kwh` | Melter boost, kWh per 15 min |
| `NCV Meter` | `ncv` | Gas NCV, kcal/SCM |
| `Cullet %` | `cullet_pct` | Cullet % (16–20, changes about monthly) |
| `Melter Optical Temperature` | `opt_temp` | Pyrometer crown temp, °C; **manual hourly log** (errors in the first file, F11; fixed in the corrected file) |
| `dcs_60_SecondaryAirFlowvalue…` | `sec_air` | Secondary (combustion) air, same basis as NG (the plant calls it "secondary gas") |
| `dcs_60_MelterGasflowvalue…` | `ng_scm` | Melter NG on the **common header**, workbook unit = operator unit (Σ96 = SAP daily SCM) |
| `dcs_60_ThermocoupleMelterBottom3…` | `mb3_temp` | Bottom temp TC MB3, °C |
| `Air_Fuel_Ratio` | `afr` | = `sec_air / ng_scm` |
| `Seed Count` / `Seed Count Specs` | `seed_count` / `seed_spec` | Daily seeds; spec "30.0 each" |
| `Daily Draw` (corrected file) / `MB51_Quantity_KG (Draw)` (first file) | `draw_kg` | SAP daily draw |
| `SFC (kcal/kg)` | `sfc_record` | Client's SFC column. Don't use (wrong while NCV = 0) |

## 4. Cleaning rules (`src/data_prep.py`; evidence in nb01 and nb02)

1. **Duplicate timestamps** (first file: 5,472) differ only in `opt_temp`. Keep one row per timestamp, average optical, flag `opt_dup`. **The corrected file has none**; the rule stays as a guard.
2. **Zeros/out-of-range → NaN** (`*_bad` flags):
   - NCV 8,500–10,500 **plus a spike filter** (> 400 kcal/SCM from the ~2 h rolling median → NaN, `ncv_spike`; 159 readings). Not 9,000: ~7% of genuine readings (Aug–Sep 2026) are 8,500–9,000 (nb03 §1b). Use the same filter live (fall back to the last valid NCV)
   - optical 1,550–1,600
   - melter boost 1–200
   - barrier boost 1–250
   - crown TC 1,400–1,700
3. **NCV zero or missing → day left out** (user decision): `ncv_ok` = NCV coverage ≥ 90%. **No client NCV is used.**
4. **Draw doubled** on 2025-10-01, 2026-06-01 and 2026-09-01 (**still in the corrected file**): detected as > 1.6× the surrounding-week median and halved (`draw_fixed`). The first two halved values equal SAP exactly (nb02 §7).
5. **Optical log** (first file only; the corrected file triggers none of these, they stay as guards):
   - **date swap** (DD/MM ↔ MM/DD) on days 1–12 → `opt_day_ok`
   - **12-hour clock** in Jan, Mar, Apr, Jun, Aug, Sep 2026 (detected from data by `ampm_months`) → `opt_hour_ok = False`
   - Corrected file: trustworthy daily optical on 393 of 395 days; optical gaps only 1 Sep 2025 00:00–05:45 and 28–30 Sep 2026.
6. Interpolate NG/boost/air gaps ≤ 1 h before daily sums. **`usable` = ncv_ok & ≥ 90% data & draw present** (343 of 395 days: 286 in the baseline period, 11 Oct 2025 – 31 Jul 2026; 27 in Sep 2026).
7. Outputs:
   - `ar_15min_clean.parquet` (index `ts`)
   - `hourly_clean.parquet` (index `ts`)
   - `daily_clean.parquet/.csv` (index `date`; key columns `sfc`, `energy_kcal`, `gas_kcal`, `elec_kcal`, `ncv`, `usable`, `in_baseline`, `opt_day_ok`, `air_per_mcal`)

## 5. Findings (keep updated; don't re-derive)

| # | Finding | Evidence |
|---|---|---|
| F1 | **Draw drives SFC.** Energy ≈ 54 Gcal/day fixed + 0.63 Gcal/t; ~60% fixed; +1 t/day ≈ −1% SFC | nb03 §3 |
| F2 | **Furnace ageing: +0.19% energy per month** at the same draw (p ≈ 0.003). Jun–Aug 2026 is **+1.1% above the draw-adjusted baseline**, Sep 2026 +1.7%, so −2% vs baseline ≈ −3% vs today | nb03 §4, T4 |
| F3 | **NCV compensation lags:** operators make ~17% of the needed NG change in the same hour, ~73% after 1 h, ~89% after 2 h, then ~80%. `NG = heat / NCV` makes it exact | nb03 §5 |
| F4 | Optical vs TC MC3 (corrected file, 9,372 hours): offset +7.6 °C (daily sd 0.8), drifting +6.8 → +8.4; hourly r ≈ 0.08, daily r ≈ 0.63. Optical is held flat (daily sd 0.8 °C) | nb01 §6 |
| F5 | 15-min NG has a sawtooth (lag-7 autocorrelation) from the **20-min reversal** sampled every 15 min | nb01 §8 |
| F6 | Air per Mcal ≈ 1.27 SCM/Mcal (tracks NCV). **Less air per Mcal → less energy** (+0.01 SCM/Mcal ≈ +0.13–0.16 Gcal/day, p ≤ 0.01, within the historical range). Air at the rolling P25 ≈ **−0.17%** | nb03 §7, T2 |
| F7 | **Seeds:** P95 = 21, max 28, never above the spec of 30 on usable days. Best-energy days have fewer seeds | nb03 §8 |
| F8 | **Barrier boost replaces only ~0.77 (chosen gas model) to ~0.83 (month FE) Gcal of gas per Gcal.** More boost raises SFC; less boost (MB3 held) lowers it | nb03 §6, T3 §1 |
| F9 | Cullet (16–20%) has no significant energy effect | nb03 §4 |
| F10 | **MB3 is controlled by barrier boost:** +100 kWh/h → +1.9 °C (steady state, 6–12 h); the same heat as gas → only +0.4 °C. Hourly data also shows operator feedback (boost cut when MB3 is high), so the response is estimated with a distributed-lag model. MB3 ran 1.56 °C above its historical median in Jun–Aug 2026 but **0.6 °C below it in Sep 2026** | nb03 §6, nb05 |
| F11 | **Optical log errors in the first file proven:** DD/MM ↔ MM/DD swap (all 36 missing days have day ≤ 12; 10/10 predicted swap targets carry duplicates, p ≈ 7e-4) and a 12-hour clock in 6 months of 2026. Only optical is hit (the only hand-typed source). **Confirmed by the corrected file:** no duplicates, the 36 days and afternoon hours filled, and 84% of the first file's extra readings sit exactly at the swapped date (512) or 12 h later (3,840) | nb02 §1–§9 |
| F12 | Best vs worst days (draw/age-adjusted): best days have less air/Mcal, ~−480 kWh/day melter boost, −0.5 °C MB3, higher NCV, fewer seeds, the same optical | nb03 §8 |
| F13 | **Melter boost is not needed in the barrier-boost controller.** It changes in ~1% of hours; its MB3 effect is real but temporary (peak +1.8 °C per +100 kWh/h at 4 h, fading to +0.6 °C at 12 h); no out-of-sample MB3 forecast gain (0.540 → 0.537, 0.531 → 0.532); barrier gain unchanged (1.96 vs 1.91); a feedforward doesn't improve closed-loop MB3 error (< 0.01 °C). It stays an input of the gas model (coefficient ≈ −0.1, n.s.) | T3 §4, T1 §D |
| F14 | **Optical is not a useful gas-model input with the corrected data.** Previous-day optical: T1 pinball 0.344 vs 0.344 without; coefficient −0.15 Gcal/day per °C (p 0.21, operator feedback). On Sep 2026 (optical ~1.3 °C low) the optical version mis-calibrated (41% of days below target, saving 0.15%) while the chosen model held (26%, 0.54%). → **removed from the model; optical is a guard-rail** | T1 §D, nb04 §2, §8 |
| F15 | **The recommenders' saving varies by month:** 1.27% in Jun–Aug 2026 (MB3 hot → boost cut), 0.55% in Sep 2026 (MB3 cold → controller adds boost). The gas part is steadier (0.70% / 0.56%) | T4 §2, §2c; nb05 §6b |

## 6. Recommenders (implemented in `src/recommender.py`, chosen in `notebooks/training/`)

**Model 1, gas (nb04; selection T1, T2; Sep check nb04 §8):**
1. Daily gas-heat target = **OLS on all past usable days** `gas_Gcal ~ draw_t + barrier_Gcal + melter_Gcal + age_m` (`rc.GAS_FORMULA`) **+ conformal shift** (P25 of the last 45 days' residuals). Coverage 20% on Jun–Aug, 26% on Sep (25% expected). The earlier version with previous-day optical is kept as `method="ols_conformal_opt"` for comparison only.
2. Spread evenly over the day. **No optical input or trim**; optical is a guard-rail (flagged outside its historical P1–P99, 1,568–1,578 °C).
3. `NG = heat per 15 min / latest NCV`.
4. **Secondary air first:** `air = air_per_Mcal_target × heat / 1000`, target = P25 of the last 45 days (floor: historical P5). `AFR = air / NG`.
5. Clip to historical P1–P99.

**Live use:** `rc.FinalRecommender().fit(d, q, h).recommend(inputs)` (T4 §5). Setpoints (NG, secondary air, AFR, boost) are clipped to historical P1–P99. The daily gas total is an outcome: it is flagged, not clipped. If NG is at its upper limit, boost is not lowered. `optical_prev24h` is still an input, used only for the guard-rail flag.

**Back-test of live inputs (T4 §6):** `rc.walk_forward_history(d, h)` replays the full recommender walk-forward on every usable day from 1 Dec 2025 (cached in `data/processed/backtest_daily.parquet`; 292 days: SFC 1,583.4 → 1,569.8, −0.86%; draw-adjusted +0.47% → −0.40%; better than actual in every month, 0.3–1.9%). `rc.history_backtest(FR, d, q, INPUTS, BT)` (wrapped as `backtest_inputs(INPUTS)` in T4) finds similar days (draw ±1.5 t, NCV ±150, cullet ±1%, widened if < 10 days) and reports actual vs recommender SFC, draw-adjusted, band, today's expected SFC (includes today's ageing) and setpoints.

**Serving and retraining (developers):** `docs/08_developer_guide_backend.md`. Model file `models/recommender_latest.json` (`FinalRecommender.save/load`, numbers only); reference API `service/app.py` (FastAPI: `/recommend`, `/compare-day`, `/model`, `/admin/reload`); live comparison `rc.compare_day(model, q_day, draw_t, cullet_pct)`; daily retraining `python src/train_model.py --out models` (checks: signs, ranges, 30-day coverage 10–45%; promotes only on pass). `data_prep.clean_15min(raw=df, with_crown=False)` accepts live data; crown TC is optional everywhere. Ageing: `age_m` comes from the date; daily retrain re-fits the slope and the 45-day shift; step changes (maintenance) need an event flag or restricted window.

**Model 2, boost (nb05; selection T3):** hourly integral controller on MB3: `bb(t) = bb(t-1) + 0.1 × (MB3_target − MB3) / 0.0194 °C per kWh/h`, clipped to [114, 610] kWh/h. Target = historical median MB3 (1,320.25 °C). No draw, cullet or melter-boost terms (T3 §3, §4).

**Back-test results (walk-forward, daily scorecard T4; 15-min gas back-test nb04):**

| Step | Jun–Aug 2026 (85 days): SFC saving | Jun–Aug draw-adjusted (target −2%) | Sep 2026 (27 days, unseen): SFC saving | Sep draw-adjusted |
|---|---|---|---|---|
| Actual operation | – | +1.14% | – | +1.68% |
| Gas model | 0.70% (15-min nb04: 0.81%) | +0.42% | 0.56% (15-min: 0.55%) | +1.13% |
| + boost, MB3 at historical median | 1.09% (pessimistic 0.99%) | +0.01% | 0.39% (MB3 cold → more boost) | +1.29% |
| + air at rolling P25 | **1.27%** | **−0.17%** | **0.55%** | **+1.13%** |
| MB3 at historical P25 (still inside history) | 1.37% gas + boost (pess. 1.19%) | needs trial | – | – |
| Scenario B (MB3 below history) | 2.0–2.2% on paper | **not recommended** | – | – |

Bands, Jun–Aug final: −0.62 / +1.23 / −0.26 / −0.15% (45–50 / 50–55 / 55–60 / 60–65 t). Model B (ageing-adjusted): Jun–Aug +0.56 → −0.73%; Sep +0.52 → −0.03%.

**Remaining gap to −2% draw-adjusted: ~1.8 points (Jun–Aug).** This needs trial levers: an optical setpoint step of −1 to −2 °C, MB3 toward the historical P25 (~−0.3%), air toward the historical P25 (1.252, ~−0.25%) with an O₂ check, and higher draw.

### Training experiments (`notebooks/training/`, 2 folds: Mar–May and Jun–Aug 2026, walk-forward; corrected data)

| Notebook | Tried | Result → choice |
|---|---|---|
| **T1 gas** | Inputs: draw, ± barrier, ± melter, + optical (same/prev day), + crown TC, + MB3, + cullet. Models: QR rolling 30/45/60 d, QR expanding + age, OLS expanding + age + conformal, OLS rolling + conformal, LightGBM (± age). Hourly model with TC/MB3/optical | **Barrier boost needed** (without it pinball 0.437 vs 0.344). Previous-day optical: no gain with the corrected log (0.344 vs 0.344) and failed on Sep (F14); same-day optical 0.334 is partly leakage; TC 0.337 (same day). Melter boost: no effect on accuracy (0.345), kept. LightGBM worst; QR expanding + age too ambitious (coverage 15%). Hourly R² 0.18 (0.23 with optical = operator reaction) → **OLS expanding + age + conformal, no crown input** |
| **T2 secondary air** | Air vs NG volume vs heat; constant AFR, constant air/Mcal, OLS heat (+NCV); efficiency vs P-levels | Air follows **heat** (R² 0.66 vs 0.44 for volume). Constant AFR error 3.3% vs air/Mcal 1.5% → **air = air/Mcal × heat**, target **rolling P25**, floor hist P5 (1.226); −0.01 SCM/Mcal ≈ −0.13 Gcal/day |
| **T3 boost** | Does boost help (MB3, gas model, SFC)? MB3 response with/without gas, crown TC, optical, MB3 level, draw. Policies: copy operators (OLS, LightGBM), integral, hybrid; closed-loop replay. **§4: melter boost** (response, F-test, forecast, gain, feedforward) | Boost = MB3 handle (+1.9 °C/100 kWh/h; TC doesn't change the gain: 1.91 vs 1.88; optical adds nothing) but **not an energy saver** (replaces 0.77–0.83 Gcal gas). The operator-copy regression is unstable (MB3 coef −0.6 vs −22 between windows) → **integral controller**. **Melter boost not needed** (F13) |
| **T4 final** | Final models on all data; scorecard Jun–Aug and **Sep 2026 validation (§2c)**; all T1 candidates on both yardsticks | Chosen gas model realistic in every period (20% / 26% coverage); final 1.27% (Jun–Aug), 0.55% (Sep) |

### How "draw-adjusted" is calculated
- **Model A** (M&V baseline), fitted once on the 286 usable baseline days: `E_expected (Gcal/day) = 53.55 + 0.605 × draw_t + 0.123 × cullet_%`.
- For any day: **draw-adjusted % = actual (or simulated) energy ÷ E_expected − 1**. The period value is the mean of the daily %. The target is −2%.
- Example, 29 Jul 2026 (49.7 t, 19% cullet): E_expected = 85.98 Gcal; actual 86.80 → **+0.96%**. Raw SFC 1,745 looks 10.7% worse than 1,576.3, but almost all of that is low draw.
- The SFC form (nb03 chart) scales each day to the reference conditions (57.5 t, 17.5% cullet): `SFC_adj = SFC × (E_ref/ref_draw) / (E_expected/draw)`.
- Model A has no ageing term, so it gives no credit for fighting ageing (conservative).

## 6b. What data trains the models (and what doesn't)

| Model | Trained on | Rows | Not used |
|---|---|---|---|
| Gas target (nb04) | Daily usable days. Target = Σ NG × valid NCV; inputs = draw, barrier, melter boost, age. OLS on all past days + 45-day conformal shift | Jun–Aug 2026 fits: 231–315 past days; Sep fits: 316–342; final (T4): 343 | NCV zero/missing/spikes, optical (guard-rail only), crown TC, cullet, MB3, client workbook |
| Air target (nb04) | Daily air per Mcal, last 45 days (P25), floor = historical P5 | 45 days | – |
| Boost controller (nb05) | Hourly MB3, boost, gas (distributed lag 0–12 h) | 6,736 hours | crown TC, optical, melter boost (F13) |
| Back-tests | 15-min data Jun–Aug 2026 and Sep 2026 | 85 + 27 days, 8,092 + 2,556 recommendations | – |

**Neither crown signal (optical, TC MC3) is a model input.** Optical is a live guard-rail; the TC is used for checks.

## 7. Notebook registry (update when you add or change a notebook)

| Notebook | Purpose | Status | Key outputs |
|---|---|---|---|
| `01_data_audit.ipynb` | Raw-data audit (corrected file), units, zero runs, optical vs TC, SFC reconciliation | ✅ | `data/processed/*` (via `data_prep`); our SFC = client SFC (median ratio 0.998); 343 usable days |
| `02_optical_log_evidence.ipynb` | On the **first** file: why only optical is wrong (tests A–B), raw Excel rows, parsing demo, proof of date swap and 12-h clock, typos, draw doubling (corrected file). **§9: verification with the corrected file** | ✅ | F11, rules `opt_day_ok`, `opt_hour_ok`, `ampm_months` (guards now) |
| `03_insights.ipynb` | Detailed, chart per insight: data coverage, NCV filter, own baseline, draw, ageing, NCV lag, **barrier boost ↔ MB3 (physics, step response, daily, substitution)**, air, seeds, best days, optical, savings waterfall, conclusions | ✅ | F1–F3, F6–F10, F12; M&V Model A (`E ~ draw + cullet`, baseline period) |
| `04_gas_recommendation.ipynb` | Model 1 (chosen in T1/T2): chosen vs earlier optical version vs first version, safety check, 15-min back-test, secondary air → AFR, with/without limits, per band, draw-adjusted, **§8 Sep 2026 validation** | ✅ | gas 0.81% SFC + air 0.17% (Jun–Aug); Sep 0.55% + 0.15%; writes `nb04_air_saving.csv` (Jun–Aug and Sep) |
| `05_boost_recommendation.ipynb` | Model 2: MB3 step response, controller tuning, scenarios A (inside history) / B (outside), combined gas + boost back-test, path to 2%, **§6b Sep 2026 validation** | ✅ | combined 1.09% (+air ~1.26%); draw-adjusted −0.16%; Sep 0.55%; writes `data/processed/path_to_2pct.csv` (read by nb03) |
| `training/T1_gas_model_experiments.ipynb` | Gas inputs (barrier, melter, optical, crown TC, MB3, cullet) × model types × 2 folds; hourly test | ✅ | `training_gas_*.csv`; choice in §6 (optical dropped, F14) |
| `training/T2_secondary_air_experiments.ipynb` | Secondary air: volume vs heat, 4 formulas, efficient target | ✅ | `training_air_targets.csv` |
| `training/T3_boost_model_experiments.ipynb` | Does boost help; MB3 response variants (incl. optical); 4 policies, closed loop × 2 folds; **§4 melter boost** | ✅ | `training_boost_policies.csv`; F13 |
| `training/T4_final_model_and_recommender.ipynb` | **Final**: trains `FinalRecommender` on all usable data; walk-forward scorecard (overall, 5-t bands, draw-adjusted A, ageing-adjusted B); all T1 candidates on both yardsticks; **§2c Sep 2026 validation**; setpoints vs historical limits; look-up tables; **live input cell (§5)**; **back-test of the inputs against history (§6)** | ✅ | `T4_scorecard.csv`, `T4_scorecard_sep.csv`, `T4_band_pct.csv`, `T4_candidates_scorecard.csv`, `backtest_daily.parquet` |

| `client/01_insights_path_to_target.ipynb` | **Client deliverable:** glossary, insights with charts (baseline, draw, draw-adjusted, ageing, NCV lag, boost ↔ MB3, air, seeds, efficient days), history replay, bands, path to −2%, trial plan and M&V | ✅ | charts via `client/report.py` |
| `client/02_model_training_and_recommender.ipynb` | **Client deliverable:** data rules, walk-forward testing, gas candidates and inputs, final equation with worked example, target vs actual, air, boost model and policies, melter-boost check, scorecards, limits, **recommendation function + look-up tables + `backtest_inputs`** | ✅ | uses `FinalRecommender`, `history_backtest` |

| `client/03_eda_features_insights.ipynb` | **Client demo notebook** for readers new to the terms: glossary + melter sketch; Part 1 EDA (sources, cleaning, summary, distributions, monthly grid, one day, correlation heat map, draw-adjusted correlations, key scatters); Part 2 features (table, draw-adjusted yardstick, P10→P90 effects, add/remove tests, left-out features); Part 3 twelve insights; Part 4 finding → action, worked recommendation (19 Aug 2026 10:00), replay, path to 2% vs today's operation, trial | ✅ | charts in `client/eda_insights.py` (on top of `report.py`); no new findings beyond F1–F15 |
| `client/SFC_Optimisation_Client_Presentation.pptx` | **Client deck (40 slides, speaker notes):** challenge, acceptance criteria, formula, 10 EDA slides, heat map, golden batch, best/worst days, input data, split, models compared, final model, evaluation, Databricks, operator setpoints + historical range (19 Aug 2026 example), path to −2% (vs today's operation), trial plan | ✅ | numbers from `data/processed/*` and `models/recommender_latest.json` |
| `client/databricks/01_training_sfc_model.ipynb` | **Databricks training job**, self-contained (pandas/numpy only): reads `input/analytical_record_15min.csv` (or parquet), cleans, builds daily/hourly, trains gas + boost + limits + M&V constants, checks, writes `output/sfc_recommender_latest.json` (same schema as `FinalRecommender.to_dict`; reproduces `models/recommender_latest.json` to 1e-13) | ✅ | `client/databricks/output/*` |
| `client/databricks/02_inference_recommendation_email.ipynb` | **Databricks inference job**: loads the model, latest plant values (or manual), setpoints + historical-limit check + data-freshness flags, HTML e-mail via the plant Logic App (`SEND_MAIL=False` by default), appends `output/recommendation_log.csv` | ✅ | e-mail preview |
| `Databricks/training/01_train_register_mlflow.ipynb` | **MLflow/serving path:** same training as `client/databricks/01` (Excel/CSV/Parquet in a Volume or a Delta table via widgets), logs a **pyfunc** (`sfc_pyfunc.py` = recommendation logic, `model.json` = numbers) to UC `prod_pgp_mfg.cantier.sfc_60tpd_recommender`; alias `champion` only if checks pass (`previous` = rollback); moves the serving endpoint to the champion version (endpoints don't follow aliases) | ✅ (tested locally, 2026-10-08) | reproduces `models/recommender_latest.json`; setup steps in `Databricks/README.md` |
| `Databricks/app/` | **Operator Dash app (Databricks App):** 1-min DCS view (NG, air = 15-min mean; MB3, MC3 = 60-min mean), NCV from MQTT blobs (training validity rules, trailing), operator draw/cullet/optical + boosts (until `BOOST_QUERY`); recommendation only on **Get recommendation** (calls `SERVING_ENDPOINT`, fallback `UC_MODEL_NAME@champion`); barrier boost in kWh/h only; 2nd tab: operator enters the set points actually applied; both go to `AUDIT_TABLE` (append-only, created if missing; `RECOMMENDATION` / `OPERATOR_SET` rows linked by `recommendation_id`) | ✅ (tested locally with simulated feeds + SQLite audit) | open: controller setpoint vs 15-min mean (reversal dips), boost feed |
| `Databricks/demo/` | **Client demo app, no integration/secrets:** same screens and inputs as `Databricks/app`; plant values replayed from the bundled Excel at a demo date/time (default 19 Aug 2026 10:00); model = bundled `model/sfc_recommender.json` + `sfc_model.py` (same logic as `sfc_pyfunc.py`); "Fill from Excel", comparison with what the plant actually did, **Model details** tab (formulas, worked example, limits, checks, yardsticks); audit kept in memory + CSV download | ✅ (tested locally) | demo times inside the training period are replays, not out-of-sample |

Notebooks are executed with outputs saved. Client notebooks are rebuilt after T4 (they read `backtest_daily.parquet` and the training CSVs). Run order after a data change: 01 → 02 → training T1–T3 → 04 → 05 → T4 → 03 (T3 reads T1's csv; nb05 reads nb04's air csv; nb03 reads nb05's waterfall file). Rebuild the processed data with `q = dp.clean_15min(); d = dp.build_daily(q); h = dp.build_hourly(q); dp.write_processed(q, d, h)`.

## 8. Open questions / answers

| # | Question | Answer |
|---|---|---|
| Q1 | NG/air units | **Answered:** use the workbook values as they are; operator enters the same unit |
| Q2 | Secondary air & O₂ | **Answered:** secondary air goes through the same 2 inlets; **no O₂ analyser** |
| Q3 | Reversal | **Answered:** 2 ports, 20-min timer, one NG flow for both (common header), set in the minute 15–20 window |
| Q4 | Threshold limits | **Answered for now:** use historical P1–P99 (nb04 §1). Replace when the plant gives official limits |
| Q5 | Sep 2026 draw | **Answered:** in the corrected file (2026-10-05). Validation done (nb04 §8, nb05 §6b, T4 §2c). Next clean check: Oct 2026 |
| Q6 | Boost as gas-model input | **Answered:** gas recommendation uses the actual boost from the DB (boost is hourly, gas is 15-min) |
| Q7 | Optical log | **Answered:** typed by hand. Errors proven in nb02; the plant sent a corrected file that confirms the diagnosis (nb02 §9). Still open: the SAP draw doubling on month-start days |
| Q8 | Electricity vs gas cost | Analysed inside and outside the historical range (nb05); more boost raises SFC anyway |
| Q9 | Target | **Answered:** per draw band or draw-adjusted |
| Q10 | Official limits for MB3/optical bands and electrode limits; seed sample definition | Open |
| Q11 | Trial approval: phases 0–4, guard-rails and M&V in `docs/05` (30 days → ±0.74% CI) | Open (next step) |
| Q12 | Success yardstick: Model A (draw-adjusted), band targets, and whether an ageing adjustment (Model B) is accepted. Setpoints give ~2% vs today (summer conditions); −2% vs the fixed baseline also needs ageing recovery (~1.1%) or draw | Open (client) |
| Q13 | Should melter boost be an input to the barrier-boost model? | **Answered (user question, 2026-10-05): no** (F13). It stays an input to the gas model |

## 9. Working rules

- Never modify `data/raw/`. All cleaning goes in `src/data_prep.py`, recommendation logic in `src/recommender.py`; notebooks import both (`sys.path.insert(0, '../src')`).
- Don't use client workbook values as inputs. If one is used (for verification or as the target to beat), say so explicitly in the notebook.
- **Time-based / walk-forward** evaluation only. Check calibration of any quantile model out of sample.
- Control for **ageing** (month fixed effects or a time trend) before claiming any lever. F8 was wrong without it.
- Limits are hard constraints. Anything outside the historical range is labelled "scenario B / extrapolation".
- Charts: reference palette (blue `#2a78d6`, orange `#eb6834`), one y-axis per chart, recessive grid.
- Environment: `pip install -r requirements.txt`.

## 10. Repo layout

```
CLAUDE.md                      this file (project memory)
requirements.txt
src/data_prep.py               loading + cleaning + daily/hourly tables (single source of truth)
src/recommender.py             Model 1 (gas) + Model 2 (boost) logic, limits, simulators
notebooks/01..05_*.ipynb       executed, with outputs
notebooks/training/T1..T3      model-selection experiments (gas, secondary air, boost)
notebooks/training/T4          final model, scorecards, live input cell + history back-test
data/raw/                      client files as received (+ README.md); fixed_5 = corrected record used everywhere
data/processed/                cleaned outputs
docs/05_final_approach_and_trial_plan.md   plant-facing: approach, evidence, path to 2%, M&V, trial phases, guard-rails
docs/06_model_training_and_selection.md    what was trained, why the final model, both yardsticks
docs/07_full_explanation.md                plain-language explanation of everything: concepts, data, training, how SFC drops, notebook map, glossary
models/                        versioned model files (recommender_<date>.json, report_<date>.json, recommender_latest.json)
service/                       reference FastAPI backend (app.py, requirements.txt)
src/train_model.py             retraining pipeline
docs/08_developer_guide_backend.md         developers: model I/O, math, test vectors, API, live comparison, retraining, ageing
client/                        client deliverables: 01 insights → target, 02 training + recommender (report.py = chart helpers)
client/databricks/              Databricks jobs: 01 training (input/ → output/), 02 inference + e-mail
Databricks/                     MLflow path: training/ (train + register UC model + move endpoint, sfc_pyfunc.py), app/ (operator Dash app), demo/ (self-contained client demo from the Excel), reference/ (plant's original monitor app), README.md (setup steps)
docs/01-02                     earlier methodology and data-request notes (pre-DCS-data)
```
