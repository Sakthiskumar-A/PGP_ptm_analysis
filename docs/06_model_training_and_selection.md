# Model Training and Selection: What Was Tried and Why the Final Model Was Chosen

**Scope:** the three recommenders (gas, secondary air, barrier boost), how each was trained and tested, and why the final choice wins. Results are judged on both client yardsticks: **5-t draw bands** and **draw-adjusted**.
**Notebooks:** `notebooks/training/T1` (gas), `T2` (secondary air), `T3` (barrier boost), `T4` (final model, scorecard, live recommender).

---

## 1. Data used for training

| Item | Rule |
|---|---|
| Source | Analytical record (15-min) + DCS crown thermocouple MC3 (1-min). Client workbook values are **not** used as inputs |
| Usable day | NCV meter valid ≥ 90% of the day (NCV 8,500–10,500 kcal/SCM, spikes > 400 removed), gas/boost data ≥ 90%, draw present → **316 days** (12 Oct 2025 – 31 Aug 2026) |
| Gas target | Daily gas heat = Σ (NG × valid NCV) per 15 min |
| Optical crown temperature | Hand-typed log with proven date errors (nb02). Only the **daily** mean on trustworthy days; other days filled from the crown TC + rolling offset (optical ≈ TC + 7.4 °C) |
| Boost model | Hourly MB3, barrier boost, gas: 6,736 complete hours |
| Excluded | NCV-zero month (Sep 2025), Sep 2026 (draw not yet received → validation month), hourly optical in 12-h clock months |

## 2. How models were tested
- **Walk-forward:** every test day is predicted only from earlier days, as in live use.
- **Two test periods (folds):** Mar–May 2026 and Jun–Aug 2026. The winner must be good in both, not just one.
- **Gas metrics:**
  - **Pinball loss at τ = 0.25:** the proper accuracy score for a "25th-percentile" target. Lower is better.
  - **Coverage:** share of days that actually needed less gas than the target. It should be about 25%; much lower means the target is unrealistically low.
  - **MAE** (Gcal/day), and the savings on both client yardsticks.
- **Boost metrics:** closed-loop replay of MB3 (actual MB3 + simulated effect of our boost changes), MB3 error vs target, hours inside the historical P5–P95, boost used, hourly moves.
- **Logic checks:** coefficient signs must make physical sense (draw +, boost −, ageing +).

---

## 3. Gas recommender (T1, T4)

### 3.1 Inputs tried (quantile regression τ = 0.25, rolling 45 days, same days for each set)

| Input set | Pinball Mar–May | Pinball Jun–Aug | Verdict |
|---|---|---|---|
| draw only | 0.330 | 0.473 | unstable between folds |
| draw + barrier + melter boost | 0.404 | 0.353 | base set |
| **without barrier boost** | 0.346 | **0.507** | **barrier needed** (Jun–Aug error +44%) |
| + optical crown temperature | 0.368 | 0.355 | small gain in one fold |
| + crown thermocouple MC3 | 0.382 | 0.360 | small gain in one fold |
| + MB3 | 0.388 | 0.356 | no consistent gain |
| + cullet | 0.426 | 0.350 | no consistent gain; constant in many windows |

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

### 3.3 Crown temperature and barrier boost inside the winner type (both folds)

| Variant | Avg pinball | Coverage |
|---|---|---|
| no crown temperature | 0.344 | 0.20–0.30 |
| + optical, same day | 0.327 | 0.25–0.30 (**partly leakage**: the day's optical reflects that day's firing) |
| **+ optical, previous day (chosen)** | **0.338** | 0.24–0.26 |
| + crown thermocouple MC3 | 0.337 | 0.20–0.28 |
| without barrier boost | 0.437 | 0.31–0.36 |

### 3.4 Hourly model?
Hourly gas heat vs draw, boost, crown TC, MB3 or optical: R² ≈ 0.18–0.26, and test error isn't improved by any temperature. Hourly gas is reversal and operator noise, so **a daily target spread evenly is the right structure**.

### 3.5 All candidates on the client yardsticks (gas only, Jun–Aug 2026, walk-forward)

| Candidate | Days below target | MAE | Saving vs actual | **Draw-adjusted** vs baseline | 45–50 t | 50–55 t | 55–60 t | 60–65 t |
|---|---|---|---|---|---|---|---|---|
| Actual operation | – | – | – | +1.14% | +0.23% | +1.36% | +1.36% | +1.60% |
| QR rolling 45 d (first) | 25% | 1.20 | 0.76% | +0.37% | −0.24% | +1.00% | +0.45% | +0.68% |
| QR rolling 60 d | 11% | 1.36 | 1.19% | −0.06% | −0.30% | −0.21% | +0.29% | +0.36% |
| QR expanding + ageing | 15% | 1.07 | 0.82% | +0.31% | −1.13% | +0.92% | +0.57% | +0.58% |
| LightGBM expanding + ageing | 16% | 1.17 | 0.85% | +0.26% | +0.15% | +1.05% | +0.63% | +0.07% |
| OLS + ageing + conformal (no optical) | 20% | 1.04 | 0.70% | +0.42% | −0.67% | +1.31% | +0.53% | +0.63% |
| **CHOSEN: OLS + ageing + optical + conformal** | **24%** | **1.00** | 0.64% | +0.48% | −0.41% | +1.30% | +0.57% | +0.73% |

*Band columns = % vs the band's baseline SFC (band target −2%). Days per band: 5 / 18 / 33 / 29.*

### 3.6 Why the chosen gas model, even though others show bigger "savings"
1. **The others' savings come from targets the furnace rarely met.**
   - QR 60 d, QR expanding and LightGBM set targets that only **11–16%** of days achieved (25% intended).
   - In a trial, operators would face targets that cool the furnace, override them, and lose trust. Those savings would not materialise.
2. **The first version (QR 45 d)** is realistic, but its daily targets are **20% less accurate** (MAE 1.20 vs 1.00), and across both folds its pinball is worse (0.386 vs 0.338). Bigger daily swings mean more days where the target is wrong in either direction.
3. **The chosen model is the most accurate realistic target.** Its signs are physical: draw +0.47 Gcal/t, barrier boost −0.70 Gcal/Gcal, ageing +0.34 Gcal/day per month, crown −0.49 Gcal/day per °C. It follows ageing automatically and contains the crown trim.
4. **The gas-only saving is the honest floor.** The full saving comes from combining gas with the boost controller and air (section 6): 1.32% vs actual, −0.23% draw-adjusted.

---

## 4. Secondary air (T2)

| Question / approach | Result |
|---|---|
| What does air follow? | Gas **heat** R² 0.66 vs gas **volume** R² 0.44 → oxygen demand follows heat |
| A1 constant AFR × NG | error 3.32% of air (worst) |
| **A2 air per Mcal × heat** | **1.50%** (chosen: physical, no intercept) |
| A3 regression heat + NCV | 1.42% |
| A4 regression heat | 1.45% |
| Energy effect | −0.01 SCM/Mcal ≈ −0.14 Gcal/day (p 0.008) |
| Target | **P25 of the last 45 days, floor at historical P5** (no O₂ analyser). AFR = air ÷ NG |

---

## 5. Barrier boost (T3)

### 5.1 Does barrier boost help?

| Question | Answer |
|---|---|
| Does it move MB3? | **Yes:** +1.94 °C per +100 kWh/h (steady state, 12 h); gas moves MB3 only about a fifth as much |
| Does the gas model need it? | **Yes:** without it the error rises about 27% (pinball 0.344 → 0.437) |
| Does more boost lower SFC? | **No:** 1 Gcal boost replaces 0.70 (gas model) to 0.81 (month FE) Gcal gas, so less boost (with MB3 held) saves energy |

### 5.2 MB3 response model (3-hour-ahead, out-of-sample R²)

| Inputs | Mar–May | Jun–Aug | Steady gain (°C per 100 kWh/h) |
|---|---|---|---|
| boost history | 0.532 | 0.474 | – |
| **boost + gas history** | 0.540 | 0.534 | **1.94** |
| + crown TC history | 0.556 | 0.547 | 1.92 |
| + MB3 level (+ draw) | 0.537–0.539 | 0.539 | – |

The crown TC adds a little prediction power but doesn't change the controller gain, so it isn't used.

### 5.3 Policies (closed-loop replay, MB3 target 1,320.25 °C)

| Policy | MB3 error (°C) Mar–May / Jun–Aug | Boost used (kWh/h) Jun–Aug (actual 347) | Hourly move | Verdict |
|---|---|---|---|---|
| P1 copy operators (OLS: MB3, draw, cullet; plant design) | 1.09 / 1.42 | 321 | 1.6 / 11.1 | **unstable** (MB3 coefficient −0.6 vs −22 between windows) |
| P4 copy operators (LightGBM) | 1.08 / 1.39 | 324 | 12.8 / 13.6 | jumpy |
| **P2 integral controller** | **1.05 / 1.09** | **268** | 5.3 / 5.4 | **chosen**: best tracking, calm, stable |
| P3 hybrid (feedforward + integral) | 1.10 / 1.12 | 266 | 6.6 / 6.2 | no better, more complex |

---

## 6. Final model: combined result on both yardsticks (T4, Jun–Aug 2026)

| Approach | Saving vs actual | **Draw-adjusted** (Model A) | Ageing-adjusted (Model B) | 45–50 t | 50–55 t | 55–60 t | 60–65 t |
|---|---|---|---|---|---|---|---|
| Actual | – | +1.14% | +0.56% | +0.23% | +1.36% | +1.36% | +1.60% |
| Gas recommender | 0.64% | +0.48% | −0.09% | −0.41% | +1.30% | +0.57% | +0.73% |
| Gas + boost controller | 1.14% | −0.04% | −0.61% | +0.03% | +1.41% | −0.20% | −0.07% |
| **Gas + boost + air (final)** | **1.32%** | **−0.23%** | **−0.79%** | −0.28% | +1.23% | **−0.40%** | **−0.23%** |

**All recommended setpoints stay inside the historical P1–P99:**
- NG 75.9–96.2 (limit 73.9–96.3)
- secondary air 981–1,091 (limit 921–1,104)
- AFR 11.15–13.11 (limit 10.99–13.44)
- boost 115–454 kWh/h (limit 114–610)

### How "draw-adjusted" is calculated
- Model A is fitted once on the 286 usable baseline days (Sep 2025 – Jul 2026): `E_expected = 53.55 + 0.605 × draw_t + 0.123 × cullet_%` (Gcal/day).
- For each day: **draw-adjusted % = energy ÷ E_expected − 1**. The period value is the average of the daily %. The target is −2%.
- Example, 29 Jul 2026: 49.7 t → E_expected 85.98 Gcal; actual 86.80 → +0.96%. The raw SFC looked 10.7% above 1,576.3, but almost all of that was low draw.
- **Model B** adds furnace age (+0.34 Gcal/day per month), so ageing isn't counted against operations.

### How the 5-t band view is calculated
Band baselines are recomputed from our own data on the baseline period (45–50: 1,765.9; 50–55: 1,664.0; 55–60: 1,566.7; 60–65: 1,521.5 kcal/kg). Each test day is compared with its band's baseline, and the target is −2% per band.

## 7. Conclusion
- **Gas:** OLS on all history + ageing + previous-day optical, with a conformal 25th-percentile target. It is the most accurate *and* realistic target, with physical signs, and it follows ageing.
- **Air:** air per Mcal × heat, target at the rolling P25. It matches how the furnace really uses air, and stays inside proven operation.
- **Barrier boost:** integral controller on MB3. It holds the bottom temperature with the least boost; copying operators was unstable.
- **Together:** −1.32% vs today's operation, draw-adjusted −0.23% vs the baseline. The 55–65 t bands drop below their baselines. All setpoints are inside history.
- **The remaining path to −2%** (trial levers, draw, ageing) is in `docs/05_final_approach_and_trial_plan.md`.
