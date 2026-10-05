# Model Training and Selection: What Was Tried and Why the Final Model Was Chosen

**Scope:** the three recommenders (gas, secondary air, barrier boost), how each was trained and tested, and why the final choice wins. Results are judged on both client yardsticks: **5-t draw bands** and **draw-adjusted**.
**Notebooks:** `notebooks/training/T1` (gas), `T2` (secondary air), `T3` (barrier boost), `T4` (final model, scorecard, Sep 2026 validation, live recommender).
**Data:** the corrected analytical record `Analytical_Record_Creation_fixed_5.xlsx` (2026-10-05). All results below were re-run on it.

---

## 1. Data used for training

| Item | Rule |
|---|---|
| Source | Corrected analytical record (15-min) + DCS crown thermocouple MC3 (1-min). Client workbook values are **not** used as inputs |
| Usable day | NCV meter valid ≥ 90% of the day (NCV 8,500–10,500 kcal/SCM, spikes > 400 removed), gas/boost data ≥ 90%, draw present → **343 days** (11 Oct 2025 – 29 Sep 2026); 286 in the baseline period |
| Gas target | Daily gas heat = Σ (NG × valid NCV) per 15 min |
| Optical crown temperature | Corrected log: one reading per hour, trustworthy on 393 of 395 days. Tested as an input; **not used** in the final model (section 3.3) |
| Boost model | Hourly MB3, barrier boost, gas: 6,736 complete hours |
| Excluded | NCV-zero month (Sep 2025) |
| Test periods | Model selection: Mar–May and Jun–Aug 2026. **Validation: Sep 2026** (its draw arrived with the corrected file) |

## 2. How models were tested
- **Walk-forward:** every test day is predicted only from earlier days, as in live use.
- **Two test periods (folds):** Mar–May 2026 and Jun–Aug 2026. The winner must be good in both, not just one.
- **Validation month:** Sep 2026, scored after the choice.
- **Gas metrics:**
  - **Pinball loss at τ = 0.25:** the proper accuracy score for a "25th-percentile" target. Lower is better.
  - **Coverage:** share of days that actually needed less gas than the target. It should be about 25%; much lower means the target is unrealistically low, much higher means it is too easy.
  - **MAE** (Gcal/day), and the savings on both client yardsticks.
- **Boost metrics:** closed-loop replay of MB3 (actual MB3 + simulated effect of our boost changes), MB3 error vs target, hours inside the historical P5–P95, boost used, hourly moves.
- **Logic checks:** coefficient signs must make physical sense (draw +, boost −, ageing +).

---

## 3. Gas recommender (T1, T4)

### 3.1 Inputs tried (quantile regression τ = 0.25, rolling 45 days, same days for each set)

| Input set | Pinball Mar–May | Pinball Jun–Aug | Verdict |
|---|---|---|---|
| draw only | 0.314 | 0.558 | unstable between folds |
| draw + barrier + melter boost | 0.348 | 0.424 | base set |
| **without barrier boost** | 0.329 | **0.571** | **barrier needed** (Jun–Aug error +35%) |
| + optical crown temperature | 0.348 | 0.424 | no gain (corrected log) |
| + crown thermocouple MC3 | 0.337 | 0.428 | small gain in one fold |
| + MB3 | 0.370 | 0.426 | no gain |
| + cullet | 0.430 | 0.424 | worse; constant in many windows |

### 3.2 Model types tried (inputs: draw + barrier + melter boost; both folds)

| Model | Avg pinball | Coverage (min–max) | MAE | Verdict |
|---|---|---|---|---|
| QR expanding + ageing | **0.331** | 0.15–0.28 | 0.98 | most accurate, but **targets too low** in Jun–Aug (15%) |
| **OLS expanding + ageing + conformal** | 0.344 | 0.20–0.30 | 0.94 | best with realistic coverage → **winner type** |
| OLS rolling 45 d + conformal | 0.362 | 0.22–0.28 | 1.03 | good, less accurate |
| LightGBM expanding + ageing | 0.362 | 0.17–0.26 | 1.09 | too few rows for trees |
| QR rolling 60 d | 0.367 | 0.11–0.21 | 1.17 | targets too low |
| QR rolling 45 d (first version) | 0.386 | 0.25–0.28 | 1.13 | realistic, but noisy |
| QR rolling 30 d | 0.394 | 0.22–0.28 | 1.13 | noisy |
| LightGBM expanding | 0.442 | 0.04–0.16 | 1.59 | worst |

*Conformal* = shift the regression prediction to the 25th percentile of its errors over the last 45 days. It keeps the target realistic as the furnace changes.

### 3.3 Crown temperature, barrier and melter boost inside the winner type (both folds)

| Variant | Avg pinball | Coverage |
|---|---|---|
| **no crown temperature (chosen)** | **0.344** | 0.20–0.30 |
| + optical, same day | 0.334 | 0.25–0.33 (**partly leakage**: the day's optical reflects that day's firing) |
| + optical, previous day (the earlier choice) | 0.344 | 0.20–0.29 |
| + crown thermocouple MC3 (same day) | 0.337 | 0.20–0.28 |
| without melter boost | 0.345 | 0.21–0.29 |
| without barrier boost | 0.437 | 0.31–0.36 |

**Why optical was taken out.** With the first file, previous-day optical gave a small gain (0.338), probably from the many days gap-filled from the thermocouple. With the corrected log it gives none, and its coefficient (−0.15 Gcal/day per °C, p 0.21) is operator feedback, not physics. On the validation month it failed:

| Sep 2026 (unseen) | Pinball | Days below target | Implied saving |
|---|---|---|---|
| **Chosen (no optical)** | **0.326** | **26%** | 0.54% |
| + previous-day optical | 0.386 | 41% | 0.15% |
| QR rolling 45 d (first version) | 0.476 | 33% | 0.60% |

September's optical ran about 1.3 °C below the summer, so the optical term raised the target. In live use the same term would raise gas whenever the crown runs cooler, which fights a lower crown setpoint (trial lever C). Optical therefore stays an operator input only as a **guard-rail** (flagged outside its historical band). Because this decision used September, the next clean check is October 2026 or the trial's shadow phase.

**Melter boost:** removing it changes nothing (0.345 vs 0.344), and its coefficient is near zero. It is kept because it is part of the furnace's energy and is read from the DB.

### 3.4 Hourly model?
Hourly gas heat vs draw and boost: R² ≈ 0.18. The crown TC and MB3 don't improve the test error. Previous-hour optical (now trustworthy) improves it a little (R² 0.23, test error 0.088 → 0.082 Gcal/h), but that mostly reflects operators reacting to the reading. Hourly gas is reversal and operator noise, so **a daily target spread evenly is the right structure**.

### 3.5 All candidates on the client yardsticks (gas only, Jun–Aug 2026, walk-forward)

| Candidate | Days below target | MAE | Saving vs actual | **Draw-adjusted** vs baseline | 45–50 t | 50–55 t | 55–60 t | 60–65 t |
|---|---|---|---|---|---|---|---|---|
| Actual operation | – | – | – | +1.14% | +0.23% | +1.36% | +1.36% | +1.60% |
| QR rolling 45 d (first) | 25% | 1.20 | 0.76% | +0.37% | −0.24% | +1.00% | +0.45% | +0.68% |
| QR rolling 60 d | 11% | 1.36 | 1.19% | −0.06% | −0.30% | −0.21% | +0.29% | +0.36% |
| QR expanding + ageing | 15% | 1.07 | 0.82% | +0.31% | −1.13% | +0.92% | +0.57% | +0.58% |
| LightGBM expanding + ageing | 16% | 1.17 | 0.85% | +0.26% | +0.15% | +1.05% | +0.63% | +0.07% |
| OLS + ageing + optical + conformal (earlier) | 20% | 1.01 | 0.68% | +0.45% | −0.54% | +1.27% | +0.53% | +0.70% |
| **CHOSEN: OLS + ageing + conformal** | **20%** | **1.04** | 0.70% | +0.42% | −0.67% | +1.31% | +0.53% | +0.63% |

*Band columns = % vs the band's baseline SFC (band target −2%). Days per band: 5 / 18 / 33 / 29.*

### 3.6 Why the chosen gas model, even though others show bigger "savings"
1. **The others' savings come from targets the furnace rarely met.**
   - QR 60 d, QR expanding and LightGBM set targets that only **11–16%** of days achieved (25% intended).
   - In a trial, operators would face targets that cool the furnace, override them, and lose trust. Those savings would not materialise.
2. **The first version (QR 45 d)** is realistic, but its daily targets are about **15% less accurate** (MAE 1.20 vs 1.04), its pinball is worse across both folds (0.386 vs 0.344), and in September it was the least accurate (0.476).
3. **The chosen model is an accurate, realistic target in every period, including the unseen month.** Its signs are physical: draw +0.50 Gcal/day per t, barrier boost −0.77 Gcal per Gcal, ageing +0.35 Gcal/day per month (melter boost −0.10, not significant). It follows ageing automatically.
4. **The gas-only saving is the honest floor.** The full saving comes from combining gas with the boost controller and air (section 6): 1.27% vs actual in Jun–Aug, −0.17% draw-adjusted.

---

## 4. Secondary air (T2)

| Question / approach | Result |
|---|---|
| What does air follow? | Gas **heat** R² 0.66 vs gas **volume** R² 0.44 → oxygen demand follows heat |
| A1 constant AFR × NG | error 3.32% of air (worst) |
| **A2 air per Mcal × heat** | **1.50%** (chosen: physical, no intercept) |
| A3 regression heat + NCV | 1.42% |
| A4 regression heat | 1.45% |
| Energy effect | −0.01 SCM/Mcal ≈ −0.13 Gcal/day (p 0.011) |
| Target | **P25 of the last 45 days, floor at historical P5 (1.226)** (no O₂ analyser). Historical P25 = 1.252. AFR = air ÷ NG |

---

## 5. Barrier boost (T3)

### 5.1 Does barrier boost help?

| Question | Answer |
|---|---|
| Does it move MB3? | **Yes:** +1.94 °C per +100 kWh/h (steady state, 12 h); gas moves MB3 only about a fifth as much |
| Does the gas model need it? | **Yes:** without it the error rises about 27% (pinball 0.344 → 0.437) |
| Does more boost lower SFC? | **No:** 1 Gcal boost replaces 0.77 (gas model) to 0.83 (month FE) Gcal gas, so less boost (with MB3 held) saves energy |

### 5.2 MB3 response model (3-hour-ahead, out-of-sample R²)

| Inputs | Mar–May | Jun–Aug | Steady gain (°C per 100 kWh/h) |
|---|---|---|---|
| boost history | 0.530 | 0.478 | – |
| **boost + gas history** | 0.538 | 0.536 | **1.91** |
| + crown TC history | 0.553 | 0.548 | 1.88 |
| + optical history (corrected log) | 0.538 | 0.532 | – |
| + MB3 level (+ draw) | 0.535–0.537 | 0.540 | – |

The crown TC adds a little prediction power but doesn't change the controller gain; optical adds nothing. Neither is used.

### 5.3 Policies (closed-loop replay, MB3 target 1,320.25 °C)

| Policy | MB3 error (°C) Mar–May / Jun–Aug | Boost used (kWh/h) Jun–Aug (actual 347) | Hourly move | Verdict |
|---|---|---|---|---|
| P1 copy operators (OLS: MB3, draw, cullet; plant design) | 1.09 / 1.42 | 321 | 1.6 / 11.1 | **unstable** (MB3 coefficient −0.6 vs −22 between windows) |
| P4 copy operators (LightGBM) | 1.08 / 1.39 | 324 | 12.8 / 13.6 | jumpy |
| **P2 integral controller** | **1.05 / 1.09** | **268** | 5.3 / 5.4 | **chosen**: best tracking, calm, stable |
| P3 hybrid (feedforward + integral) | 1.10 / 1.12 | 266 | 6.6 / 6.2 | no better, more complex |

### 5.4 Should melter boost be considered in the boost recommender? **No.**

| Check | Result |
|---|---|
| How often does it change? | Fixed levels (mostly 76.4 kWh per 15 min); a change > 20 kWh/h in 104 of 9,429 hours (about 1%) |
| Effect on MB3 (+100 kWh/h step) | **Temporary:** +0.7, +1.1, +1.5, +1.8, **+1.8 (4 h)**, +1.7, +1.6, +1.4, +1.2, +0.9, +0.7, +0.6, +0.6 °C over 0–12 h. Barrier boost builds up to +1.9 °C and stays. F-test: the effect is real (p ≈ 3e-28) |
| Better MB3 forecast? | No: 3-h-ahead R² 0.540 → 0.537 (Mar–May), 0.531 → 0.532 (Jun–Aug) |
| Barrier gain changed? | Hardly: 1.96 without vs 1.91 °C per 100 kWh/h with melter boost in the model |
| Closed loop with a feedforward (cut barrier by 33% or 100% of a melter change) | MB3 error 0.912 / 0.909 / 0.915 °C (Oct 2025–Jan 2026) and 1.086 / 1.084 / 1.081 °C (Jun–Aug 2026): no real gain, busier boost moves |

The controller reads MB3 every hour, so it absorbs the melter-boost transient on its own. Melter boost stays an input to the **gas** model (it is part of the energy) and is read from the DB.

---

## 6. Final model: combined result on both yardsticks (T4)

### 6.1 Jun–Aug 2026 (85 days)

| Approach | Saving vs actual | **Draw-adjusted** (Model A) | Ageing-adjusted (Model B) | 45–50 t | 50–55 t | 55–60 t | 60–65 t |
|---|---|---|---|---|---|---|---|
| Actual | – | +1.14% | +0.56% | +0.23% | +1.36% | +1.36% | +1.60% |
| Gas recommender | 0.70% | +0.42% | −0.15% | −0.67% | +1.31% | +0.53% | +0.63% |
| Gas + boost controller | 1.09% | +0.01% | −0.56% | −0.33% | +1.40% | −0.08% | 0.00% |
| **Gas + boost + air (final)** | **1.27%** | **−0.17%** | **−0.73%** | −0.62% | +1.23% | **−0.26%** | **−0.15%** |

### 6.2 Sep 2026, unseen month (27 days; bands 1 / 7 / 12 / 7 days)

| Approach | Saving vs actual | **Draw-adjusted** (Model A) | Ageing-adjusted (Model B) | 45–50 t | 50–55 t | 55–60 t | 60–65 t |
|---|---|---|---|---|---|---|---|
| Actual | – | +1.68% | +0.52% | −1.24% | +2.17% | +1.49% | +0.98% |
| Gas recommender | 0.56% | +1.13% | −0.03% | −1.55% | +0.96% | +0.91% | +1.08% |
| Gas + boost controller | 0.39% | +1.29% | +0.13% | −0.72% | +1.56% | +0.84% | +1.10% |
| **Gas + boost + air (final)** | **0.55%** | **+1.13%** | **−0.03%** | −1.12% | +1.42% | +0.72% | +0.91% |

In September MB3 ran below target (1,319.7 °C), so the controller added boost (+9%) to hold it. The gas model kept its calibration (26% of days below target).

**All recommended setpoints stay inside the historical P1–P99** (Jun–Aug replay, 8,059 recommendations; under 2% touched a limit):
- NG 76.0–96.2 (limit 73.9–96.3)
- secondary air 981–1,088 (limit 921–1,104)
- AFR 11.14–13.10 (limit 10.99–13.44)
- boost 115–454 kWh/h (limit 114–610)

### How "draw-adjusted" is calculated
- Model A is fitted once on the 286 usable baseline days (Sep 2025 – Jul 2026): `E_expected = 53.55 + 0.605 × draw_t + 0.123 × cullet_%` (Gcal/day).
- For each day: **draw-adjusted % = energy ÷ E_expected − 1**. The period value is the average of the daily %. The target is −2%.
- Example, 29 Jul 2026: 49.7 t → E_expected 85.98 Gcal; actual 86.80 → +0.96%. The raw SFC looked 10.7% above 1,576.3, but almost all of that was low draw.
- **Model B** adds furnace age (+0.18 Gcal/day per month on the baseline period), so ageing isn't counted against operations.

### How the 5-t band view is calculated
Band baselines are recomputed from our own data on the baseline period (45–50: 1,765.9; 50–55: 1,664.0; 55–60: 1,566.7; 60–65: 1,521.5 kcal/kg). Each test day is compared with its band's baseline, and the target is −2% per band.

## 7. Conclusion
- **Gas:** OLS on all history + ageing, with a conformal 25th-percentile target (draw, barrier and melter boost, age). It is an accurate *and* realistic target, with physical signs, it follows ageing, and it held its calibration on the unseen September. Optical is a guard-rail, not an input.
- **Air:** air per Mcal × heat, target at the rolling P25. It matches how the furnace really uses air, and stays inside proven operation.
- **Barrier boost:** integral controller on MB3. It holds the bottom temperature with the least boost; copying operators was unstable; melter boost isn't needed as an input.
- **Together:** −1.27% vs today's operation in Jun–Aug (draw-adjusted −0.17% vs the baseline; the 55–65 t bands drop just below their baselines). In September, with a cold bottom, −0.55%. All setpoints are inside history.
- **The remaining path to −2%** (trial levers, draw, ageing) is in `docs/05_final_approach_and_trial_plan.md`.
