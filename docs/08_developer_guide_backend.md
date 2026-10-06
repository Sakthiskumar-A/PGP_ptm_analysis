# Developer Guide: Serving the SFC Recommender (Backend, Frontend, Retraining)

**For:** the backend and frontend developers who build the live application around the model.
**You need no glass or statistics background.** Part A is all you need to call the model. Parts B–D explain how to compare the model with live data, how retraining works, and the project context.

| Part | What it covers |
|---|---|
| **A. Using the model** | the model file, inputs, outputs, when to call, the exact math, test vectors, the reference API |
| **B. Model vs actual** | what to store, how to compare recommendations with what operators actually set, history back-test |
| **C. Retraining pipeline** | daily flow, what changes and what is frozen, checks, rollback, **ageing question answered** |
| **D. Context** | what the model is for and why it looks like this |

---

# Part A — Using the model

## A1. What you are serving, in one paragraph
Two small recommenders packed in **one model file**:
1. **Gas recommender:** every 20-min reversal cycle → **NG flow setpoint**, **secondary air** and **air-fuel ratio (AFR)**.
2. **Barrier-boost recommender:** every hour → **barrier boost (kWh/h)**.

Both are plain arithmetic on a handful of numbers stored in a JSON file. **No ML runtime, no GPU, no statsmodels needed at serving time.** A call takes well under a millisecond.

## A2. What to hand over / use

| File | Purpose |
|---|---|
| `models/recommender_latest.json` | **The model.** Coefficients, targets, limits. Replaced by the daily retraining (Part C) |
| `src/recommender.py` | `FinalRecommender.load(path).recommend(inputs)` (Python reference implementation) and `compare_day(...)` (Part B) |
| `src/data_prep.py` | Cleaning rules (needed for retraining and for cleaning live rows) |
| `src/train_model.py` | The retraining pipeline (Part C) |
| `service/app.py` | **Reference REST API (FastAPI)**, tested. A starting point for the backend |
| `service/requirements.txt` | `fastapi`, `uvicorn`, `pydantic` |

## A3. Quick start (Python)

```python
import sys; sys.path.insert(0, "src")
import recommender as rc

model = rc.FinalRecommender.load("models/recommender_latest.json")

inputs = dict(
    date="2026-10-05",        # today (furnace age is computed from it)
    ncv=9300,                 # latest VALID NCV, kcal/SCM
    draw_t=58.0,              # expected draw today, t/day
    cullet_pct=18,            # cullet % today
    optical_prev24h=1574.5,   # average optical crown temp of the last 24 h, °C (safety check only)
    bb_kwh_last_hour=350,     # barrier boost in the last hour, kWh
    mb_kwh_last_hour=300,     # melter boost in the last hour, kWh
    mb3_now=1321.5,           # MB3 bottom temperature now, °C
)
rec = model.recommend(inputs)        # pandas DataFrame, 6 rows (see A5)
print(rec)
print(rec.attrs["flags"])            # list of warning strings ([] = all fine)
```

**Run the reference API:**
```bash
pip install -r requirements.txt -r service/requirements.txt
MODEL_PATH=models/recommender_latest.json uvicorn service.app:app --port 8000
# interactive docs: http://localhost:8000/docs
```

## A4. Inputs

| Field | Unit | Source | Frequency | Validation / rule |
|---|---|---|---|---|
| `date` | date | server clock (plant local date) | each call | Drives the furnace-age term; must be the real current date |
| `ncv` | kcal/SCM | UEMS gas analyser (MQTT) | every 15 min | Accept only **8,500–10,500** and within **±400** of the median of the last ~2 h (9 readings). Otherwise **send the last valid NCV**. The API rejects values outside 8,500–10,500 (HTTP 422) |
| `draw_t` | t/day | operator / production plan | daily | Planned draw for today (SAP confirms it the next day). History range 49–62 t |
| `cullet_pct` | % | operator | daily (changes ~monthly) | 16–20 typical. Not used in the setpoints, kept for reporting |
| `optical_prev24h` | °C | operator log (hourly, typed) | hourly | Mean of the last 24 h. **Guard-rail only:** flagged outside 1,568–1,578 °C; does not change the setpoints |
| `bb_kwh_last_hour` | kWh (per hour) | energy meter / DB (BARRIER BOOSTER-52) | hourly | Sum of the last 4 × 15-min values. Used by both recommenders |
| `mb_kwh_last_hour` | kWh (per hour) | energy meter / DB (MELTER BOOSTER-51) | hourly | Sum of the last 4 × 15-min values |
| `mb3_now` | °C | DCS (TC MB3) | hourly (any recent value) | Bottom thermocouple 3 |

**Units:** NG and secondary air are in the **same unit as the DCS/workbook columns** (per 15 min). Operators enter the value as shown; there is no conversion.

## A5. Outputs

| # | Item | Unit | Who uses it | Notes |
|---|---|---|---|---|
| 0 | Daily gas-heat target | Gcal/day | display / reporting | Not a setpoint. **Flagged** (not clipped) if outside its history |
| 1 | **NG setpoint** | SCM per 15 min (workbook unit) | operator, every reversal cycle | One value for both ports (common header) |
| 2 | **Secondary air** | SCM per 15 min | operator, every reversal cycle | |
| 3 | **Air-fuel ratio** | – | operator | = secondary air ÷ NG |
| 4 | **Barrier boost, next hour** | kWh/h | operator, every hour | |
| 5 | Barrier boost, next hour | kWh per 15 min | display | = row 4 ÷ 4 (workbook unit) |

Each row carries: `model value` (before limits), `recommended (within limits)` (**what to show the operator**), `historical P1-P99` (allowed range), `clipped?` (true = held at a limit). `rec.attrs["flags"]` holds warnings, e.g.:
- `input optical_prev24h=1566 outside history [1568, 1578]`
- `daily gas target 83.6 Gcal outside the historical daily range [72.5, 80.9] (...)`
- `NG at historical maximum -> barrier boost not reduced this hour`

**REST output** (`POST /recommend`), one object per setpoint:
```json
{
  "model_trained_until": "2026-09-29",
  "gas_heat_target_gcal_day": {"value": 78.906, "model_value": 78.906, "unit": "Gcal/day", "limit_low": 72.54, "limit_high": 80.9, "held_at_limit": false},
  "ng_setpoint":             {"value": 88.38,  "model_value": 88.38,  "unit": "SCM/15 min", "limit_low": 73.86, "limit_high": 96.34, "held_at_limit": false},
  "secondary_air":           {"value": 1041.915, "...": "..."},
  "afr":                     {"value": 11.789, "...": "..."},
  "barrier_boost_kwh_h":     {"value": 343.53, "...": "..."},
  "barrier_boost_kwh_15min": {"value": 85.883, "...": "..."},
  "flags": []
}
```

## A6. When to call
- **Gas (NG, air, AFR):** once per 20-min reversal cycle, **at about minute 14**, with the **latest valid NCV**. The operator sets it anywhere in the minute 15–20 window. If you prefer a fixed schedule, calling every 5 minutes and showing the latest result is fine: the result only changes when NCV, draw or the hourly boost inputs change.
- **Barrier boost:** **once per hour**, just after the hour, with the boost of the hour that just ended and the current MB3. Show it until the next hour. Gas calls in between reuse the latest hourly boost inputs.
- **One call returns both.** The frontend shows gas values every cycle and the boost value hourly.

## A7. The exact math (to re-implement in any language)
Everything comes from `models/recommender_latest.json`. Values below are from the model trained up to 2026-09-29.

**Step 1: daily gas-heat target (Gcal/day)**
```
age_m    = (date − gas.age_origin) in days ÷ gas.days_per_month          # 2025-09-01, 30.44
bb_g     = bb_kwh_last_hour × 24 × 860 ÷ 1e6                             # barrier boost, Gcal/day
mb_g     = mb_kwh_last_hour × 24 × 860 ÷ 1e6                             # melter boost, Gcal/day
target   = c.Intercept + c.draw_t × draw_t + c.bb_g × bb_g + c.mb_g × mb_g + c.age_m × age_m
           + gas.conformal_shift
           # c = gas.coefficients: Intercept 52.195, draw_t 0.4953, bb_g −0.7715, mb_g −0.0993,
           #     age_m 0.3498; conformal_shift −0.412
```
**Step 2: NG** (steady heat, exact NCV compensation)
```
heat_15  = target × 1e6 ÷ 96                         # kcal per 15 min
ng_raw   = heat_15 ÷ ncv
ng       = clip(ng_raw, limits.ng_scm)               # [73.86, 96.34]
```
**Step 3: air and AFR**
```
afr      = clip(air.air_per_mcal × ncv ÷ 1000, limits.afr)        # air_per_mcal 1.268; afr limits [10.99, 13.44]
air      = clip(afr × ng, limits.sec_air)                         # [920.5, 1104.2]
afr      = air ÷ ng
```
**Step 4: barrier boost (next hour)**
```
bb_raw   = bb_kwh_last_hour + boost.ki × (boost.mb3_target − mb3_now) ÷ boost.mb3_gain_degC_per_kwh_h
           # ki 0.1, mb3_target 1320.25, gain 0.01936
bb       = clip(bb_raw, limits.bb_kwh_h)             # [114.3, 609.8]
if ng_raw > limits.ng_scm.high and bb < bb_kwh_last_hour:  bb = bb_kwh_last_hour   # never cut boost when gas is maxed
```
**Step 5: flags**
- input outside its limit: `ncv`, `draw_t`, `optical_prev24h → limits.opt_temp`, `mb3_now → limits.mb3_temp`
- `target` outside `limits.gas_day_gcal`
- any setpoint clipped

## A8. Test vectors (model file trained until 2026-09-29; `date` = 2026-10-05, cullet 18)
Use these as unit tests for your implementation (tolerance ±0.01).

| ncv | draw | bb last h | mb last h | MB3 | optical | → target | NG | air | AFR | boost kWh/h | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 9300 | 58 | 350 | 300 | 1321.5 | 1574.5 | 78.91 | 88.38 | 1041.92 | 11.79 | 343.53 | normal |
| 9600 | 58 | 350 | 300 | 1321.5 | 1574.5 | 78.91 | 85.62 | 1041.92 | 12.17 | 343.53 | same heat, higher NCV → less NG |
| 10200 | 52 | 300 | 305 | 1319.0 | 1575 | 76.72 | 78.35 | 1013.05 | 12.93 | 306.44 | MB3 cold → more boost |
| 8600 | 61 | 150 | 305 | 1324.0 | 1566 | 83.57 | **96.34** (limit) | 1058.67 | **10.99** (limit) | **150.00** (kept) | NG at max → boost not cut; 3 flags |

## A9. Edge cases the backend must handle

| Situation | What to do |
|---|---|
| NCV reading 0, missing, outside 8,500–10,500, or a spike | Use the last valid NCV. If none in the last 2 h, show "NCV unavailable: hold current NG" and don't call |
| Boost meter missing for the last hour | Use the most recent complete hour; flag it |
| Draw not entered yet today | Use yesterday's draw or the production plan; show which one was used |
| `held_at_limit = true` | Show the value with a "limit" badge; the shift engineer checks the plant |
| Any flag | Show the flags next to the setpoints; log them |
| Model file missing or corrupt | Keep serving the previous model; alarm (see C5) |

## A10. Reference API (`service/app.py`)

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/health` | – | status, model file, `trained_until` |
| GET | `/model` | – | the whole model JSON (coefficients, limits, M&V constants) |
| POST | `/recommend` | inputs (A4) | setpoints (A5) |
| POST | `/compare-day` | `date`, `draw_t`, `cullet_pct`, `rows` (15-min actuals) | actual vs recommended for that day (Part B) |
| POST | `/admin/reload` | – | reloads `MODEL_PATH` after a retrain (C4) |

Production additions the reference doesn't include: authentication, request logging to a database (B1), rate limiting, HTTPS, a model registry instead of a file path.

---

# Part B — Model vs actual: comparing with live data

## B1. What to store (so that comparisons and M&V are possible)

| Table | One row per | Columns |
|---|---|---|
| `actuals_15min` | 15-min timestamp | ncv, ng_scm, sec_air, afr, bb_kwh, mb_kwh, mb3_temp (raw and cleaned) |
| `recommendations` | each call | timestamp, model `trained_until`, all inputs, all outputs (value, model value, held_at_limit), flags |
| `operator_actions` | each setpoint change | timestamp, NG set, air set, boost set, override reason (if any) |
| `daily_kpi` | day | draw (SAP), cullet, seeds, actual gas/elec/SFC, SFC if followed, draw-adjusted %, band %, adherence |
| `model_registry` | model version | file, trained_until, checks report, promoted_at |

**Always log the recommendation that was shown at the time**, with the model version. Recomputing later with a newer model gives different numbers.

## B2. The live comparison: `compare_day` / `POST /compare-day`
For a day (or the day so far), it compares what the operators did with what the model recommended:

| Output | Meaning |
|---|---|
| `intervals` (each 15 min) | NCV, **actual NG vs recommended NG** (and % deviation), actual vs recommended secondary air and AFR, actual vs recommended gas heat |
| `hours` (each hour) | MB3, **actual vs recommended barrier boost**. Open loop: each hour starts from the actual boost of the previous hour and the actual MB3, i.e. what the operator would have been told at that moment |
| `summary` | gas actual vs target; **actual SFC vs SFC if the advice had been followed**; draw-adjusted % for both; band baseline; **adherence** = share of intervals with NG within ±2% of the advice |

**Example (20 Aug 2026, draw 61.6 t, 19% cullet):**
```
gas_actual_gcal 81.74   gas_target_gcal 78.66   (+3.9% more gas than the target)
sfc_actual 1578.4       sfc_if_followed 1527.0  (−3.25%)
draw_adjusted_actual +4.33%   draw_adjusted_if_followed +0.94%    band 60-65 baseline 1521.5
ng_within_2pct_of_advice 20%  ng_mean_abs_dev 6.2%
```

A partial day (live, before midnight) is scaled to 96 intervals for the totals. The SAP draw arrives the next day, so recompute the final daily KPI then.

## B3. Why model and actual differ (what the frontend should explain)

| Difference | Cause | How it shows |
|---|---|---|
| Actual NG zig-zags, advice is smooth | The 20-min port reversal sampled every 15 min, plus manual moves | NG deviation swings ± a few % every interval |
| Actual NG lags NCV changes | Operators correct only ~17% of an NCV change in the same hour, ~73% after 1 h | Heat (NG × NCV) overshoots when NCV rises, undershoots when it falls; the advice keeps heat flat |
| Actual gas above target | The target is the level the most efficient quarter of comparable days reached | `gas_vs_target_pct` > 0 on ~75% of days; that gap is the saving |
| Actual boost above advice | Operators keep MB3 above its normal level (summer 2026) | `bb_actual > bb_rec`, MB3 above 1,320.25 |
| Actual boost below advice | MB3 running cold (Sep 2026) | The controller asks for **more** boost; correct, it protects the bottom |
| Advice held at a limit | Unusual conditions (very lean gas at high draw) | `held_at_limit` badge |

"SFC if followed" is a **model estimate**, not a measurement. It is right on average over many days (see B4), but any single day can differ. Trial results are judged on ≥ 30 days of **measured** SFC (draw-adjusted), not on this estimate.

## B4. History back-test: "what does history say for these values?"
Two functions (in `src/recommender.py`, shown in `client/02_model_training_and_recommender.ipynb` §10):

- `walk_forward_history(d, h)` replays the full recommender on every usable day since 1 Dec 2025. Each day only uses earlier days, as in live use. Result: 292 days, SFC 1,583.4 → 1,569.8 kcal/kg (−0.86%), lower in every month (0.3–1.9%). Cached in `data/processed/backtest_daily.parquet`.
- `history_backtest(model, d, q, inputs, bt)` finds days similar to the current inputs (draw ±1.5 t, NCV ±150, cullet ±1%; widened automatically if fewer than 10) and returns:
  - the **actual average SFC** on those days, and the **recommender's SFC on the same days**
  - draw-adjusted % and band % for both
  - **today's expected SFC** if the current advice is followed all day
  - setpoints used on those days vs recommended now
  - Example (NCV 9300, 58 t, 18%): 13 days, actual 1,579.8 → recommender 1,560.8 (−1.2%).

**Suggested optional endpoint** (needs the processed history tables loaded at start-up):
```python
@app.post("/backtest")
def backtest(inp: RecommendInput):
    r = rc.history_backtest(STATE["model"], D, Q, inp.model_dump(), BT)   # D, Q, BT loaded from data/processed
    return {"rule": r["rule"], "summary": r["summary"].astype(str).to_dict(),
            "setpoints": r["setpoints"].round(2).to_dict()}
```

**Reading "today's expected SFC":** it includes today's furnace age (+0.35 Gcal/day per month), so it is usually a little higher than older similar days. The like-for-like saving is "actual vs recommender on the same days".

## B5. Suggested frontend screens

| Screen | Content |
|---|---|
| **Operator panel** | Current NG, secondary air, AFR (big numbers) with countdown to minute 15 of the cycle; barrier boost for this hour; limit badges; flags; last NCV and its age |
| **Live trend (today)** | NCV; actual vs recommended NG; actual vs recommended gas heat (Gcal/h); MB3 with target line; actual vs recommended boost |
| **Daily KPI** | SFC actual vs if followed; draw-adjusted % vs the −2% target; band % vs band target; adherence %; seeds |
| **History** | `backtest_inputs` result for the current inputs; the monthly replay chart |
| **Model** | model version / trained_until, checks report, rolling 30-day coverage (C5) |

---

# Part C — Retraining pipeline

## C1. Flow

```
 06:00  SAP posts yesterday's draw
   │
   ▼
 [1] Load  ── last 13+ months of 15-min data (NCV, NG, air, boosts, MB3, optical, cullet, seeds, draw)
   │          from the plant DB → DataFrame with the workbook column names (or the short names)
   ▼
 [2] Clean ── data_prep.clean_15min(raw=df, with_crown=False)        same rules as the analysis:
   │          NCV 8,500–10,500 + spike filter, zeros → missing, draw-doubling fix, gaps ≤ 1 h filled
   ▼
 [3] Build ── data_prep.build_daily(q), build_hourly(q)              usable days = NCV ≥ 90%, data complete, draw present
   ▼
 [4] Fit   ── FinalRecommender().fit(d, q, h)                        a few seconds
   ▼
 [5] Check ── train_model.checks(...)  signs, ranges, recent coverage (C3)
   │     fail ──► keep yesterday's model, alarm
   ▼ pass
 [6] Save  ── models/recommender_<trained_until>.json + report_<...>.json
   ▼
 [7] Promote ─ copy to models/recommender_latest.json → POST /admin/reload
```

**Command (reference, reading the Excel files):** `python src/train_model.py --out models`. Runtime about 20 s. In production, replace step 1 with a DB loader and keep steps 2–7.

**Schedule:** **daily**, after yesterday's SAP draw is available (e.g. 06:30). Yesterday's day enters training once it is complete and usable.

## C2. What a retrain updates, and what stays fixed

| Item | On retrain | Why |
|---|---|---|
| Gas coefficients (draw, barrier, melter, **ageing slope**, constant) | **re-estimated** on all usable history | follows the furnace as data accumulates |
| 25% shift (`conformal_shift`) | **recomputed** from the last 45 usable days | keeps the target at the "efficient quarter" of *recent* operation |
| Air per Mcal target | **recomputed**: P25 of the last 45 days, floor P5 | follows recent combustion |
| MB3 gain (°C per kWh/h) | re-estimated (stable, ~0.019) | |
| MB3 target (historical median, 1,320.25) | recomputed | **recommend freezing** in config once the plant agrees a target (trial lever A changes it deliberately) |
| Limits (P1–P99) | recomputed from all history | **recommend freezing** to plant-approved official limits when available, so limits don't drift |
| **M&V yardsticks** (Model A, band baselines) | **frozen**: always fitted on the fixed baseline period (Sep 2025 – Jul 2026) | they are the contract yardstick and must never move |

## C3. Automatic checks before a model is served (`src/train_model.py`)

| Check | Pass range |
|---|---|
| usable training days | ≥ 200 |
| draw coefficient | > 0 |
| barrier-boost coefficient | −1.2 to −0.3 |
| ageing coefficient | ≥ 0 |
| MB3 gain | 0.010–0.030 °C per kWh/h |
| air per Mcal target | 1.15–1.40 |
| walk-forward coverage on the last 30 days | 10–45% (25% intended) |

If any check fails, `recommender_latest.json` is **not** updated (exit code 1) and the API keeps serving the previous model.

## C4. Deployment and rollback
- The API reads the file named by `MODEL_PATH`. After promotion, call `POST /admin/reload`, or restart the service.
- Every model file is versioned by `trained_until`, so **rollback** = copy an older file to `recommender_latest.json` and reload.
- Log the model version with every recommendation (B1).

## C5. Monitoring (daily)

| Metric | Healthy | Action if not |
|---|---|---|
| Rolling 30-day coverage (share of days with gas ≤ target) | 15–35% | < 10%: targets too hard (check data, maintenance event); > 45%: too easy |
| Share of calls with flags | low single-digit % | inspect inputs / sensors |
| Share of setpoints held at a limit | < 2% | check limits and inputs |
| NCV availability | ≥ 95% of 15-min slots valid | fix the meter feed |
| Daily draw-adjusted % (actual) | trending down during the trial | review adherence |

## C6. Does retraining handle ageing automatically? **Yes, with one caveat**
- **Age is not an input you send.** The model computes `age_m` from the date (months since 1 Sep 2025). So the target already rises by itself, about +0.35 Gcal/day per month, even between retrains.
- **Daily retraining re-estimates the ageing slope** together with the other coefficients, using all history including the newest days. If ageing speeds up or slows down, the slope follows.
- **The 25% shift is recomputed from the last 45 days.** If the furnace drifts away from the straight-line ageing trend, recent residuals change and the shift corrects the target within days to a few weeks. That covers gradual changes in either direction, including drift that isn't linear.
- **The caveat: a sudden step change.** Examples: regenerator/checker cleaning, a hot repair, a burner change, a new NCV source. The furnace jumps to a different efficiency in one go, but the straight-line age term assumes continuous wear. Until enough new days accumulate, the target is temporarily off: too easy after a maintenance that improves efficiency, too hard after a degradation.
  - The 45-day shift absorbs most of it in 2–6 weeks. To be faster:
    - **log maintenance events**, and after one, retrain with a restricted window (e.g. only days after the event plus a minimum of 60 days), or add an event indicator to the model;
    - **watch the 30-day coverage** (C5): a drop below 10% or a rise above 45% is the signal.
- **The boost controller has no age term.** It is feedback on MB3, so ageing doesn't affect it.
- **The M&V baseline does not age** (it is frozen on purpose). Ageing is why the client's fixed baseline gets harder to beat over time; see Part D.

So: **keep the daily retrain running, keep the date correct, log maintenance events, and watch coverage.** Then ageing is handled automatically.

---

# Part D — Context (short)

**Goal:** reduce the SFC of the 60 TPD flint melter by 2% vs the client baseline (1,576.3 → 1,544.8 kcal/kg), judged per 5-t draw band or draw-adjusted.
`SFC = [Σ(NG × NCV) + (barrier kWh + melter kWh) × 860] ÷ draw kg`

**Why the model looks like this**
- Draw drives SFC (~60% of energy is fixed). That is why draw is in the gas target and why results are judged draw-adjusted.
- The furnace ages (+0.19% energy per month), hence the age term.
- Operators correct gas only partly and late after NCV changes. `NG = heat ÷ NCV` fixes that.
- Barrier boost controls the bottom temperature (MB3) but replaces only ~0.77 Gcal of gas per Gcal. So the boost recommender gives the **minimum** boost that holds MB3.
- Excess air wastes heat; there is no O₂ analyser, so air stays within proven operation.
- Optical crown temperature adds nothing reliable to the model; it is a guard-rail.

**What it delivers (walk-forward on history, all setpoints within limits)**
- Jun–Aug 2026: −1.27% SFC; draw-adjusted +1.14% → −0.17%.
- Sep 2026: −0.55%.
- Dec 2025 – Sep 2026: −0.86%, lower in every month.
- The remaining gap to −2% needs trial levers (MB3 target, air with an O₂ check, crown setpoint) and draw.

**Read more**

| Document | What it covers |
|---|---|
| `docs/07_full_explanation.md` | plain-language explanation of everything |
| `docs/06_model_training_and_selection.md` | the model choices |
| `docs/05_final_approach_and_trial_plan.md` | the trial and its guard-rails |
| `client/01`, `client/02` notebooks | the client presentation and the recommendation function |
