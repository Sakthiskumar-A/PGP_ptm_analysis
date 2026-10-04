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
| **1. Gas** | NCV (UEMS, MQTT, 15 min) | Draw (day), optical crown temp, cullet % (day); **actual boost read from DB** | **NG flow**, **air-fuel ratio** (→ secondary air) | every 15 min / per reversal cycle |
| **2. Electricity** | MB3 bottom temp (DCS) | Draw (day), cullet % (day) | **Barrier boost** | every hour |

- **Furnace:** regenerative, **2 inlets/ports**. Each carries NG + secondary air; while one fires, the other is the exhaust. They switch on a **20-min timer**. The operator sets **one NG flow for both inlets** (common header) anywhere in the **minute 15–20 window** of each cycle. So the recommendation must be ready by minute 15, using the latest NCV.
- **Units:** recommend in the **same unit as the workbook column**. The operator enters that value; no conversion.
- **No O₂ analyser.** Air can only be recommended inside its proven historical range.
- **Limits:** use **historical limits** (P1–P99) until the plant supplies official ones.
- **Melter boost** is fixed on a few levels (57.2 → 76.4 → 95.5 kWh/15 min). It's a known input, not recommended.
- **Optical crown temperature** is typed by hand (hourly). It is the primary crown signal for operators; TC MC3 (1-min DCS) is the clean hourly crown signal for analysis.

## 3. Data (all in `data/raw/`, never edit; cleaned data in `data/processed/`)

| File | Content | Frequency / period |
|---|---|---|
| `Analytical_Record_Creation_EE_60TPD_updated-2.xlsx` | Sheet `result`: main 15-min record. Sheet `Sheet1`: plant's model design | 15 min, 1 Sep 2025 – 30 Sep 2026 |
| `DCS_60_TPD_MelterCrown3.xlsx` | Crown thermocouple TC MC3 (rows newest first) | 1 min, 1 Sep 2025 – 1 Oct 2026 |
| `SFC_60_TPD_Baseline_Calculation_Sep-25_to_Jul-26_updated.xlsx` | Client baseline workbook. **Used only for comparison/verification**, never to fill data | Daily, 1 Sep 2025 – 31 Jul 2026 |

**Sep 2026 draw is missing.** The client will send it, and **Sep 2026 is the validation month** (nb04 §8 checks automatically).

### Column dictionary (15-min record → short name)

| Raw column | Short name | Meaning / unit |
|---|---|---|
| `Timestamps` | `ts` | 15-min timestamp (interval start assumed) |
| `BARRIER BOOSTER-52` | `bb_kwh` | Barrier boost, kWh per 15 min (Σ96 = SAP daily kWh) |
| `MELTER BOOSTER-51` | `mb_kwh` | Melter boost, kWh per 15 min |
| `NCV Meter` | `ncv` | Gas NCV, kcal/SCM |
| `Cullet %` | `cullet_pct` | Cullet % (16–20, changes about monthly) |
| `Melter Optical Temperature` | `opt_temp` | Pyrometer crown temp, °C; **manual hourly log** (see F11) |
| `dcs_60_SecondaryAirFlowvalue…` | `sec_air` | Secondary (combustion) air, same basis as NG (the plant calls it "secondary gas") |
| `dcs_60_MelterGasflowvalue…` | `ng_scm` | Melter NG on the **common header**, workbook unit = operator unit (Σ96 = SAP daily SCM) |
| `dcs_60_ThermocoupleMelterBottom3…` | `mb3_temp` | Bottom temp TC MB3, °C |
| `Air_Fuel_Ratio` | `afr` | = `sec_air / ng_scm` |
| `Seed Count` / `Seed Count Specs` | `seed_count` / `seed_spec` | Daily seeds; spec "30.0 each" |
| `MB51_Quantity_KG (Draw)` | `draw_kg` | SAP daily draw |
| `SFC (kcal/kg)` | `sfc_record` | Client's SFC column. Don't use (wrong while NCV = 0) |

## 4. Cleaning rules (`src/data_prep.py`; evidence in nb01 and nb02)

1. **Duplicate timestamps** (5,472) differ only in `opt_temp`. Keep one row per timestamp, average optical, flag `opt_dup`.
2. **Zeros/out-of-range → NaN** (`*_bad` flags):
   - NCV 8,500–10,500 **plus a spike filter** (> 400 kcal/SCM from the ~2 h rolling median → NaN, `ncv_spike`; 159 readings). Not 9,000: ~7% of genuine readings (Aug–Sep 2026) are 8,500–9,000 (nb03 §1b). Use the same filter live (fall back to the last valid NCV)
   - optical 1,550–1,600
   - melter boost 1–200
   - barrier boost 1–250
   - crown TC 1,400–1,700
3. **NCV zero or missing → day left out** (user decision): `ncv_ok` = NCV coverage ≥ 90%. **No client NCV is used.**
4. **Draw doubled** on 2025-10-01 and 2026-06-01: detected as > 1.6× the surrounding-week median and halved (`draw_fixed`). The halved values equal SAP exactly (verified in nb02).
5. **Optical log:**
   - **date swap** (DD/MM ↔ MM/DD) on days 1–12 → `opt_day_ok`
   - **12-hour clock** in Jan, Mar, Apr, Jun, Aug, Sep 2026 (detected from data by `ampm_months`) → `opt_hour_ok = False`
   - Hourly optical is only used where `opt_hour_ok`.
6. Interpolate NG/boost/air gaps ≤ 1 h before daily sums. **`usable` = ncv_ok & ≥ 90% data & draw present** (316 of 395 days; 286 in the baseline period, 11 Oct 2025 – 31 Jul 2026).
7. Outputs:
   - `ar_15min_clean.parquet` (index `ts`)
   - `hourly_clean.parquet` (index `ts`)
   - `daily_clean.parquet/.csv` (index `date`; key columns `sfc`, `energy_kcal`, `gas_kcal`, `elec_kcal`, `ncv`, `usable`, `in_baseline`, `opt_day_ok`, `air_per_mcal`)

## 5. Findings (keep updated; don't re-derive)

| # | Finding | Evidence |
|---|---|---|
| F1 | **Draw drives SFC.** Energy ≈ 54 Gcal/day fixed + 0.63 Gcal/t; ~60% fixed; +1 t/day ≈ −1% SFC | nb03 §2 |
| F2 | **Furnace ageing: +0.19% energy per month** at the same draw (p ≈ 0.004). Jun–Aug 2026 is **+0.9% (SFC-based, nb03) / +1.1% (energy-based, nb04–05) above the draw-adjusted baseline**, so −2% vs baseline ≈ −3% vs today | nb03 §2 |
| F3 | **NCV compensation lags:** operators make ~17% of the needed NG change in the same hour, ~70% after 1 h, ~80% after 2 h. `NG = heat / NCV` makes it exact | nb03 §3a |
| F4 | Optical vs TC MC3 (trustworthy hours only): offset +7.4 °C (daily sd 0.9), drifting +6.8 → +8.3; hourly r ≈ 0.02, daily r ≈ 0.44. Optical is held flat (daily sd 0.5 °C) | nb01 §6 |
| F5 | 15-min NG has a sawtooth (lag-7 autocorrelation) from the **20-min reversal** sampled every 15 min | nb01 §8 |
| F6 | Air per Mcal ≈ 1.27 SCM/Mcal (tracks NCV). **Less air per Mcal → less energy** (p ≈ 0.003, within the historical range). Moving to the historical P25 (1.258) ≈ **−0.16%** | nb03 §3f |
| F7 | **Seeds:** P95 = 21, never above the spec of 30 on usable days. Best-energy days have fewer seeds; more energy and a hotter crown go with *more* seeds | nb03 §3b, §3e |
| F8 | **CORRECTED:** barrier boost replaces only ~0.56 (frontier model) to ~0.81 (month FE) Gcal of gas per Gcal. **More boost raises SFC; less boost (MB3 held) lowers it** | nb03 §3c, nb04 §2 |
| F9 | Cullet (16–20%) has no significant energy effect | nb03 §2 |
| F10 | **MB3 is controlled by barrier boost:** +100 kWh/h → +1.9 °C (steady state, 6–12 h); the same heat as gas → only +0.4 °C. Hourly data also shows operator feedback (boost cut when MB3 is high), so the response is estimated with a distributed-lag model. In Jun–Aug 2026, MB3 ran 1.5 °C above its historical median | nb03 §3d, nb05 |
| F11 | **Optical log errors proven:** DD/MM ↔ MM/DD swap (all 36 missing days have day ≤ 12; 10/10 predicted swap targets carry duplicates, p ≈ 7e-4), and a 12-hour clock in 6 months of 2026. **Only optical is hit** because it is the only hand-typed source with text dates: in all 5,472 duplicated time stamps the other 12 columns are identical, and on optical-missing days every other column is 100% filled. Month-first parsing reproduces the pattern exactly (nb02 §3) | nb02 |
| F12 | Best vs worst days (draw/age-adjusted): best days have less air/Mcal, −500 kWh/day melter boost, −0.5 °C MB3, steadier NCV, fewer seeds, the same optical | nb03 §3b |

## 6. Recommenders (implemented in `src/recommender.py`)

**Model 1, gas (nb04):**
1. Daily gas-heat target = walk-forward **quantile regression (τ = 0.25, last 45 usable days)**: `gas_Gcal ~ draw_t + barrier_Gcal + melter_Gcal`. Out-of-sample calibration: 24.7% of test days below the target (25% expected).
2. Spread evenly over the day, with an optical trim of 0.29% heat per °C below target (operators' own historical response).
3. `NG = heat per 15 min / latest NCV`.
4. `AFR = 1.258 × NCV / 1000`.
5. Clip to historical P1–P99.

**Model 2, boost (nb05):** hourly integral controller on MB3: `bb(t) = bb(t-1) + 0.1 × (MB3_target − MB3) / 0.019 °C per kWh/h`, clipped to the historical boost range [114, 610] kWh/h. Default target = historical median MB3 (1,320.25 °C).

**Back-test results, Jun–Aug 2026 (walk-forward, 85 usable days):**

| Step | SFC saving vs actual | Draw-adjusted vs baseline (target −2%) |
|---|---|---|
| Actual operation | – | +1.14% |
| Gas model (nb04, 15-min) | 0.87% | +0.25% |
| + boost, MB3 at historical median (nb05) | 1.38% (pessimistic 1.07%) | −0.29% |
| + air to historical P25 (estimate) | ~1.5% | **−0.45%** |
| MB3 at historical P25 (still inside history) | 1.88% (pess. 1.29%) | needs trial |
| Scenario B (MB3 below history) | 2.9–3.4% on paper | **not recommended**: MB3 outside history 60–80% of the time |

**Remaining gap to −2% draw-adjusted: ~1.55 points.** This needs trial levers: an optical setpoint step of −1 to −2 °C (seed headroom), MB3 toward the historical P25, and higher draw / fewer line stops.

## 6b. What data trains the models (and what doesn't)

| Model | Trained on | Rows | Not used for training |
|---|---|---|---|
| Gas target (nb04) | **Daily** rows of usable days: target = gas heat (Σ NG × valid NCV), inputs = draw, barrier boost, melter boost. Refitted every day on the **last 45 usable days** (walk-forward) | 38–45 days per fit (median 42); for the Jun–Aug 2026 test, 129 distinct days (17 Apr – 30 Aug 2026). Usable days in total: 316 | NCV-zero/missing days, spikes; **optical** (hand-typed, flat); **crown TC MC3**; cullet (no effect; captured by the window); client workbook |
| Optical trim gain (nb04) | Hourly optical vs gas heat, **only hours with a trustworthy optical time stamp** (`opt_hour_ok`; months with the 12-h clock and duplicate slots excluded) | 3,302 hours | – |
| Air target (nb04) | Historical P25 of daily air per Mcal (usable days) | 316 days | – |
| Boost controller (nb05) | Hourly MB3, barrier boost and gas (distributed lag, 0–12 h) for the MB3 step response | 6,736 hours (complete 13-hour lag windows) | crown TC, optical |
| Back-tests | 15-min data, Jun–Aug 2026 (8,092 recommendations) | 85 test days | Sep 2026 (waiting for draw) |

**Crown thermocouple TC MC3 is not used to train any model.** It is used only for checks: the optical comparison (nb01), frontier-day temperatures (nb04 §3) and the historical limits table.

## 7. Notebook registry (update when you add or change a notebook)

| Notebook | Purpose | Status | Key outputs |
|---|---|---|---|
| `01_data_audit.ipynb` | Raw-data audit, units, zero runs, optical vs TC, SFC reconciliation | ✅ | `data/processed/*` (via `data_prep`); our SFC = client SFC (median ratio 0.998) |
| `02_optical_log_evidence.ipynb` | Why only optical is wrong (source/join tests A–B), raw Excel rows, parsing demo, proof of date swap and 12-h clock, typos, draw doubling | ✅ | F11, rules `opt_day_ok`, `opt_hour_ok`, `ampm_months` |
| `03_insights.ipynb` | Detailed, chart per insight: data coverage, NCV filter, own baseline, draw, ageing, NCV lag, **barrier boost ↔ MB3 (physics, step response, daily, substitution)**, air, seeds, best days, optical, savings waterfall, conclusions | ✅ | F1–F3, F6–F10, F12; M&V Model A (`E ~ draw + cullet`, baseline period) |
| `04_gas_recommendation.ipynb` | Model 1: frontier tuning (τ, window), safety check, 15-min back-test, scenarios with/without limits, per band, draw-adjusted, Sep validation hook | ✅ | gas saving 0.87% SFC |
| `05_boost_recommendation.ipynb` | Model 2: MB3 step response, controller tuning, scenarios A (inside history) / B (outside), combined gas + boost back-test, path to 2% | ✅ | combined 1.38% (+air ~1.5%); draw-adjusted −0.45%; writes `data/processed/path_to_2pct.csv` (read by nb03) |

Notebooks are executed with outputs saved. Rebuild the processed data with `q = dp.clean_15min(); d = dp.build_daily(q); h = dp.build_hourly(q); dp.write_processed(q, d, h)`.

## 8. Open questions / answers

| # | Question | Answer |
|---|---|---|
| Q1 | NG/air units | **Answered:** use the workbook values as they are; operator enters the same unit |
| Q2 | Secondary air & O₂ | **Answered:** secondary air goes through the same 2 inlets; **no O₂ analyser** |
| Q3 | Reversal | **Answered:** 2 ports, 20-min timer, one NG flow for both (common header), set in the minute 15–20 window |
| Q4 | Threshold limits | **Answered for now:** use historical P1–P99 (nb04 §1). Replace when the plant gives official limits |
| Q5 | Sep 2026 draw | Client will send it → validation month |
| Q6 | Boost as gas-model input | **Answered:** gas recommendation uses the actual boost from the DB (boost is hourly, gas is 15-min) |
| Q7 | Optical log | **Answered:** typed by hand. Errors proven in nb02. Still useful: the raw log with ISO dates and a 24-h clock would let us repair the history |
| Q8 | Electricity vs gas cost | Analysed inside and outside the historical range (nb05); more boost raises SFC anyway |
| Q9 | Target | **Answered:** per draw band or draw-adjusted |
| Q10 | Official limits for MB3/optical bands and electrode limits; seed sample definition | Open |
| Q11 | Trial approval: optical −1 °C steps, MB3 target toward P25 | Open (next step) |

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
data/raw/                      client files as received (+ README.md)
data/processed/                cleaned outputs
docs/                          earlier methodology and data-request notes (pre-DCS-data)
```
