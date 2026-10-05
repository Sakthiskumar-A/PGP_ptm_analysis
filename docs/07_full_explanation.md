# The Whole Project Explained: What We Did, How We Trained, and How It Reduces SFC

**Who this is for:** anyone who needs to understand the project end to end and explain it to others, including the plant team, management and the client. No statistics background is assumed: every term is explained the first time it is used, and the glossary in section 12 repeats them.

**Related documents:**
- `docs/05_final_approach_and_trial_plan.md`: plant-facing plan and trial
- `docs/06_model_training_and_selection.md`: detailed training tables
- `CLAUDE.md`: project memory with all findings

---

## 1. The problem in one page

The 60 TPD flint furnace melts glass for lines S09–S12. It uses three kinds of energy in the melter:

| Energy | What it is | How it is measured |
|---|---|---|
| **Natural gas (NG)** | Burned above the glass through 2 ports. Biggest share, about 84% | SCM per 15 min × **NCV** (kcal per SCM) |
| **Barrier boost** | Electrodes low in the melter that heat the glass from below | kWh per 15 min |
| **Melter boost** | Another set of electrodes, kept on a few fixed levels | kWh per 15 min |

**SFC (specific fuel consumption)** = how much energy one kilogram of glass costs:

```
SFC (kcal/kg) = [ Σ NG × NCV  +  (barrier kWh + melter kWh) × 860 ] ÷ draw (kg)       per day
```

- **Baseline** (client, 1 Sep 2025 – 31 Jul 2026): **1,576.3 kcal/kg**. We recomputed it from raw data: 1,576.6. They agree.
- **Target:** 2% lower = **1,544.8 kcal/kg**, judged either **per 5-t draw band** or **draw-adjusted** (section 2.3).
- **What we deliver:** two **recommenders** that tell the operator what to set:
  1. **Gas recommender:** NG flow, secondary air and air-fuel ratio, every 20-minute reversal cycle.
  2. **Boost recommender:** barrier boost (kWh/h), every hour.

---

## 2. Concepts you need (explained simply)

### 2.1 NCV: the gas quality changes all the time
**NCV (net calorific value)** is how much heat one SCM of gas gives, in kcal/SCM. It moves between about 8,800 and 10,300 (1st–99th percentile) and changes every 15 minutes. If NCV rises 5%, the same gas flow brings 5% more heat. So to keep the **heat** steady, the gas **flow** must go down by 5%.

### 2.2 Draw: why SFC moves so much from day to day
**Draw** is the tonnes of glass pulled per day (about 48–62 t). A furnace loses a lot of heat through walls, crown and regenerators **whatever it melts**. In our data about **60% of the energy is fixed**. So when draw falls, the fixed losses are shared over fewer kilograms and SFC rises: **+1 t/day ≈ −1% SFC**. A low-draw day can look 10% "worse" without any change in how the furnace is fired.

### 2.3 Fair comparisons: draw bands and draw-adjusted
Because draw dominates SFC, you can't compare raw SFC between days or months. Two fair yardsticks (both accepted by the client):
- **5-t draw bands:** compare a day only with baseline days of similar draw (45–50, 50–55, 55–60, 60–65 t). Band baselines: 1,765.9 / 1,664.0 / 1,566.7 / 1,521.5 kcal/kg. Target −2% in each band.
- **Draw-adjusted (Model A):** a simple equation fitted on the baseline period says how much energy a day *should* use for its draw and cullet:
  `E_expected (Gcal/day) = 53.55 + 0.605 × draw_t + 0.123 × cullet_%`.
  Then **draw-adjusted % = actual energy ÷ E_expected − 1**. 0% = exactly baseline performance; −2% = target met.
  - Example, 29 Jul 2026: 49.7 t → expected 85.98 Gcal; actual 86.80 → +0.96%. Raw SFC (1,745) looked 10.7% worse than baseline, but almost all of that was low draw.

### 2.4 Ageing: the furnace slowly gets less efficient
At the same draw, energy rises about **0.19% per month** (refractory and regenerator wear). In Jun–Aug 2026 the furnace was **+1.1% above the baseline** at the same draw. So reaching −2% vs the baseline means about **−3% vs today**. **Model B** (ageing-adjusted) adds furnace age to Model A, so ageing isn't counted against operators. It is shown for discussion; the client's yardstick is Model A or the bands.

### 2.5 Barrier boost and MB3 (bottom temperature)
- **MB3** is a thermocouple in the melter bottom.
- Barrier boost heats the glass from below, so it moves MB3 directly: **+100 kWh/h → about +1.9 °C after 6–12 hours**. The same heat as gas moves MB3 only +0.4 °C.
- **But boost is not an energy saver.** 1 Gcal of boost replaces only about **0.77–0.83 Gcal of gas**. So more boost means *more* total energy.
- **Conclusion:** use the **minimum boost that holds MB3 at its target**.

### 2.6 Melter boost
Fixed on a few levels (mostly 76.4 kWh per 15 min) and rarely changed. It warms the bottom only for a few hours after a change. It is an input (read from the database), never a recommendation.

### 2.7 Secondary air, AFR and "air per Mcal"
- **Secondary air** is the combustion air sent with the gas. **AFR** (air-fuel ratio) = air ÷ NG.
- Oxygen demand depends on the **heat** burned, not the gas **volume**. When NCV rises, each SCM needs more air. So the right control quantity is **air per Mcal of gas heat** (≈ 1.27 SCM/Mcal in history), not a fixed AFR.
- **Too much air wastes energy:** the extra air is heated up and leaves through the flue. In history, −0.01 SCM/Mcal ≈ −0.13 Gcal/day.
- **There is no O₂ analyser**, so we never recommend less air than the furnace has already run at safely.

### 2.8 Optical crown temperature
A pyrometer reading of the crown, typed by hand every hour.
- The first data file had date errors (day/month swap, a 12-hour clock). We proved this in nb02, and the plant's corrected file confirmed it.
- Operators hold it almost flat (~1,574.5 °C, daily sd 0.8 °C), so history can't tell what a lower crown would save.
- With the corrected data, it **adds nothing** to the gas model, and in September it made the model wrong. So it is a **guard-rail** only: the recommender flags it if it is outside its normal band (1,568–1,578 °C).

### 2.9 Historical limits (P1–P99)
For every setpoint we take the range that covers 98% of history: from the 1st percentile (P1) to the 99th (P99). **No recommendation may go outside it.** That way we never ask the furnace to do something it hasn't already done. Official plant limits will replace these when supplied.

### 2.10 Walk-forward testing: why the results are honest
A model is only useful if it works on days it has **not** seen. Every result in this project is **walk-forward**: to recommend for day D, the model is trained only on days **before D**, exactly as it would run live. No future information leaks in. We tested on Mar–May and Jun–Aug 2026 (to choose models) and kept **Sep 2026** as an extra check.

---

## 3. The data journey

| Step | What happened |
|---|---|
| **Raw files** | 15-min analytical record (corrected file `..._fixed_5.xlsx`), 1-min crown thermocouple, client baseline workbook (used only to verify our numbers) |
| **Cleaning** (`src/data_prep.py`) | NCV kept only between 8,500 and 10,500 and without spikes (> 400 from the 2-h median). Zeros → missing. Short gaps (≤ 1 h) filled. Draw doubled on 3 month-start days → halved |
| **Usable day** | NCV valid ≥ 90% of the day **and** gas/boost data ≥ 90% **and** draw present. **343 of 395 days** |
| **Left out** | Sep 2025 (the NCV meter read 0 all month), a few days with NCV or gas gaps |
| **Tables** | 15-min, hourly and daily tables in `data/processed/` |

**Rule:** no client values are used as inputs. The client workbook is only used to check that we reproduce their numbers (we do, within ±1.5%).

---

## 4. What the data taught us (the reasons behind the recommenders)

| # | Finding | What it means for SFC |
|---|---|---|
| 1 | Draw explains most SFC swings (+1 t/day ≈ −1%) | Judge results per band or draw-adjusted |
| 2 | Ageing +0.19%/month | Today starts +1.1% above baseline |
| 3 | **NCV is corrected late:** operators make 17% of the needed gas change in the same hour, 73% after 1 h | Gas heat drifts with NCV → wasted heat. **Lever 1** |
| 4 | Efficient days used less gas for the same conditions, with the same crown temperature and *fewer* seeds | There is room to fire to the efficient level safely. **Lever 1** |
| 5 | Barrier boost is a temperature handle, not an energy saver; MB3 ran 1.5 °C above its median in Jun–Aug | Too much boost was used. **Lever 2** |
| 6 | Less air per Mcal → less energy, within history | **Lever 3** |
| 7 | Seeds: P95 = 21, never above the spec of 30 | Quality headroom for trial levers |
| 8 | Cullet (16–20%) has no measurable effect | Not used |

---

## 5. How the two recommenders work (with a worked example)

**Example inputs:** 5 Oct 2026, NCV 9,300, draw 58 t, cullet 18%, barrier boost last hour 350 kWh, melter boost last hour 300 kWh, MB3 now 1,321.5 °C, optical 1,574.5 °C.

### 5.1 Gas recommender (every reversal cycle)

**Step 1: daily gas-heat target.** A simple equation, trained on all past usable days:

```
gas heat (Gcal/day) = 52.20
                    + 0.495 × draw (t)                 more glass → more gas
                    − 0.771 × barrier boost (Gcal)     boost replaces some gas
                    − 0.099 × melter boost (Gcal)
                    + 0.350 × furnace age (months)     ageing
                    + conformal shift (−0.41)          moves the target to the efficient quarter
```

- **What the conformal shift does.** The equation alone predicts an *average* day. We want the gas of an *efficient* day, so we look at the last 45 days and take the error that only 25% of days beat (the 25th percentile). That number is added to the prediction.
  - So the target = "what the most efficient quarter of comparable recent days needed".
  - It updates every day, so it follows the furnace as it changes.
- **Example:** 52.20 + 0.495 × 58 − 0.771 × 7.22 − 0.099 × 6.19 + 0.350 × 13.1 − 0.41 = **78.9 Gcal/day**.

**Step 2: spread evenly.** Heat per 15 min = 78.9 Gcal ÷ 96 = 0.822 Gcal = 822,000 kcal. Steady heat, no swings.

**Step 3: exact NCV compensation.** **NG = heat ÷ latest NCV** = 822,000 ÷ 9,300 = **88.4** (workbook unit per 15 min). If NCV goes to 9,600, NG becomes 85.6, and the heat stays exactly the same. This is the correction operators today make only partly and late.

**Step 4: secondary air.** Air = air-per-Mcal target × heat. The target is the 25th percentile of the last 45 days (the efficient end of recent operation), never below the historical P5. Example: 1.268 × 822 Mcal = **1,042**; **AFR** = 1,042 ÷ 88.4 = **11.79**.

**Step 5: limits.** NG, air and AFR are held inside their historical P1–P99. The daily gas total is only flagged if it is unusual, not clipped.

### 5.2 Boost recommender (every hour)

An **integral controller**, the same logic as a thermostat that adjusts gently:

```
boost next hour = boost last hour + 0.1 × (MB3 target − MB3 now) ÷ 0.0194
```

- **MB3 target** = 1,320.25 °C (the historical median).
- **0.0194 °C per kWh/h** is the measured effect of boost on MB3 (1.94 °C per 100 kWh/h).
- **0.1** means each hour it corrects only 10% of the gap. The furnace responds slowly (6–12 h), so big moves would make MB3 overshoot.
- **Example:** 350 + 0.1 × (1,320.25 − 1,321.5) ÷ 0.0194 = **343.5 kWh/h**. MB3 is a little hot, so boost goes down a little.
- Clipped to the historical range 114–610 kWh/h. If NG is already at its maximum, boost is not reduced.

**The two talk to each other:** the gas recommender reads the actual boost from the database, so when boost goes down, the gas target goes up a little (by 0.77 Gcal per Gcal of boost removed). Total energy still falls.

---

## 6. How we trained and chose the models

### 6.1 The training principle
We didn't pick one model and hope. For each recommender we **tried several alternatives, scored them walk-forward on two separate test periods** (Mar–May and Jun–Aug 2026), and chose by fixed rules: accurate, realistic, physically sensible, stable.

### 6.2 How a gas target is scored
- **Pinball loss (τ = 0.25):** the standard accuracy score for a "25th-percentile" target. It punishes a target that is too high more lightly than one that is too low, in the right proportion. Lower is better.
- **Coverage:** the share of days that actually used *less* gas than the target. It should be about **25%**.
  - Much lower (e.g. 11%) means the target is unrealistically low: operators would override it and lose trust.
  - Much higher means it is too easy and saves nothing.

### 6.3 What we tried (notebooks T1–T3)

| Question | Alternatives tried | Winner and why |
|---|---|---|
| **Gas: which inputs?** (T1) | draw; ± barrier boost; ± melter boost; + optical (same day / previous day); + crown thermocouple; + MB3; + cullet | **draw + barrier + melter boost + furnace age.** Barrier boost is essential (without it the error rises 27%). Optical, thermocouple, MB3 and cullet add nothing reliable |
| **Gas: which model type?** (T1) | Quantile regression on 30/45/60-day windows; quantile regression with ageing; OLS + ageing + conformal; OLS on 45 days + conformal; LightGBM (machine learning) ± ageing | **OLS on all past days + ageing + conformal shift**: the best accuracy *with* realistic coverage in both periods. LightGBM was worst (too few days for trees); some others looked "better" only because their targets were too low (11–16% coverage) |
| **Gas: daily or hourly?** (T1) | Hourly models with crown temperature, MB3, optical | **Daily target, spread evenly.** Hourly gas is mostly the reversal and operator moves (R² ≈ 0.2) |
| **Air: what to follow?** (T2) | Constant AFR; constant air per Mcal; regressions on heat ± NCV | **Air per Mcal × heat**: half the error of a fixed AFR, physically meaningful |
| **Air: which level?** (T2) | Historical P1…P75 vs a rolling level | **Rolling P25 of the last 45 days, floor at historical P5**: efficient but always proven (no O₂ analyser) |
| **Boost: does it help?** (T3) | Effect on MB3, on the gas model, on total energy | It is the MB3 handle, but **not** an energy saver |
| **Boost: which policy?** (T3) | Copy operators (regression, as in the plant's design), copy with LightGBM, integral controller, hybrid | **Integral controller**: best MB3 tracking, calm moves. Copying operators was unstable (its key coefficient changed from −0.6 to −22 between periods) |
| **Boost: include melter boost?** (T3 §4) | Response, forecast test, gain test, a feedforward controller | **No.** Its effect is temporary, it doesn't improve the forecast, and the controller already absorbs it |

### 6.4 Why not a "black-box" machine-learning model?
We tried LightGBM. With about 300 daily rows it can't learn more than a straight-line model, and it extrapolates badly. The chosen equation has **five numbers with physical meaning** that an engineer can check (more draw → more gas, more boost → less gas, older furnace → more gas). That transparency is what lets the plant trust it in a trial.

### 6.5 The final training (T4)
The chosen models are trained on **all 343 usable days** (`FinalRecommender`) for live use. The history results in section 8 always use walk-forward versions, so they are not flattered by training on the test days.

---

## 7. How it reduces SFC: the three mechanisms

```
                      TODAY                                  WITH THE RECOMMENDERS
Gas         heat drifts with NCV (late, partial)   →   exact heat every 15 min, at the efficient-quarter level
Boost       more than needed (MB3 1.5 °C above)    →   minimum boost that holds MB3 at its median
Air         ~1.28 SCM per Mcal                     →   rolling P25 (~1.27), never below proven operation
```

1. **Gas, about 0.7–0.8%.** The target asks for what the efficient quarter of comparable days needed. Exact NCV compensation makes sure that heat is actually delivered, without the over-firing that happens when NCV rises and gas isn't cut in time.
2. **Barrier boost, about 0.4%** (when MB3 runs hot). Less boost saves electricity. Gas makes up only ~77% of it, so total energy falls. **When MB3 runs cold (as in Sep 2026), the controller adds boost** to protect the bottom, and this lever turns into a small cost.
3. **Air, about 0.17%.** Less excess air to heat and throw out of the flue.

**Jun–Aug 2026, draw-adjusted vs baseline (walk-forward):**

| Step | Draw-adjusted vs baseline |
|---|---|
| Actual operation | +1.14% |
| + gas recommender | +0.42% |
| + boost controller | +0.01% |
| + air target | **−0.17%** |
| Target | −2.00% |
| **Remaining gap** | **about 1.8 points**: needs trial levers |

---

## 8. Results on history (all walk-forward, all setpoints inside historical limits)

| Period | Days | Actual SFC | With recommenders | Saving | Draw-adjusted: actual → recommended |
|---|---|---|---|---|---|
| **Jun–Aug 2026** (main test) | 85 | 1,605.3 | 1,585.0 | **1.27%** | +1.14% → **−0.17%** |
| **Sep 2026** (unseen month) | 27 | 1,610.4 | 1,601.6 | **0.55%** | +1.68% → **+1.13%** |
| **Whole replay, Dec 2025 – Sep 2026** (T4 §6) | 292 | 1,583.4 | 1,569.8 | **0.86%** | +0.47% → **−0.40%** |

- **The recommender beats actual operation in every month**, by 0.3% to 1.9% (T4 §6 table).
- **The saving varies by month.** It is the inefficiency there is to remove: bigger in Feb, Jun and Aug 2026 (1.3–1.9%), smaller in Dec 2025, Mar–Apr and Sep 2026 (0.3–0.6%). In Sep the reason is known: the bottom ran cold, so the boost controller added boost.
- **Per band, Jun–Aug:** the two most common bands (55–60 and 60–65 t) move from about +1.5% above their baselines to just below them (−0.26% and −0.15%).

---

## 9. Path to 2% and the trial

**The recommenders (proven on history) give about 1.3% vs today.** The rest needs **trial levers**: they are outside what history can prove, so they are tested carefully with daily seed checks.

| Lever | Expected | Why it needs a trial |
|---|---|---|
| A. MB3 target from the median (1,320.25) to the historical P25 (1,319.2 °C) | about −0.3% | Still inside history, but a lower bottom temperature must be checked against quality |
| B. Air per Mcal to the historical P25 (1.252) | about −0.25% | Needs a portable O₂/CO check (no analyser) |
| C. Crown (optical) setpoint −1 to −2 °C | to be measured | The crown was always held flat, so history can't say. Seeds have headroom (P95 = 21 vs spec 30) |
| D. Higher draw (+1 t/day) | about −1% | Production decision |
| E. Ageing recovery (maintenance) | up to about −1% | Plant decision |

With A–C, the total is about **2% vs today's operation at the same draw**. Reaching −2% vs the **fixed** 2025–26 baseline also needs the ageing since then (~1.1%) made up by draw or maintenance, or an agreed ageing-adjusted yardstick (Model B).

**Trial in phases** (details in `docs/05`):
1. Shadow mode (2 weeks, recommendations logged, not applied)
2. Gas + air
3. + boost controller
4. Trial levers one at a time
5. Lock-in with ≥ 30 days of measurement

30 trial days measure the saving to **±0.74%**.

---

## 10. The notebooks: what each one does, and do they use the same method?

### 10.1 Map

| Notebook | Role | In one sentence |
|---|---|---|
| `01_data_audit` | Data | Loads the corrected file, checks units, gaps and zeros, reproduces the client's SFC |
| `02_optical_log_evidence` | Data | Proves the optical-log errors of the first file and confirms them with the corrected file |
| `03_insights` | Understanding | One chart per finding: draw, ageing, NCV lag, boost ↔ MB3, air, seeds, waterfall to 2% |
| `training/T1_gas_model_experiments` | **Choosing** | Tries many gas inputs and model types on two test periods; picks the winner |
| `training/T2_secondary_air_experiments` | **Choosing** | Tries four air formulas and several air levels; picks the winner |
| `training/T3_boost_model_experiments` | **Choosing** | Tests whether boost helps, how MB3 responds, four boost policies, and melter boost; picks the winner |
| `training/T4_final_model_and_recommender` | **Final + live** | Trains the winners on all data, scores them on both yardsticks (Jun–Aug and Sep), checks the limits, look-up tables, **input cell (§5)** and **back-test cell (§6)** |
| `04_gas_recommendation` | **Deep dive, gas** | The chosen gas model at 15-min detail: every reversal-cycle setpoint replayed, NCV handling, air/AFR, with/without limits, Sep validation |
| `05_boost_recommendation` | **Deep dive, boost** | The chosen boost controller: MB3 step response, speed tuning, scenarios inside/outside history, combined with gas, path to 2%, Sep validation |

### 10.2 Do the training notebooks and nb04/nb05 use the same method and the same terms? **Yes.**

- **The same method.** All the chosen logic lives in one file, `src/recommender.py`, and every notebook calls it:

| Logic | Function in `src/recommender.py` | Used by |
|---|---|---|
| Gas target (OLS + ageing + conformal) | `daily_gas_target`, `walk_forward_gas_targets` | nb04, nb05, T4 |
| NG / air / AFR from the target | `recommend_gas` | nb04 |
| Air target (rolling P25, floor P5) | `air_target` | nb04, T4 |
| MB3 step response, boost controller | `boost_step_response`, `simulate_boost_controller` | nb05, T4 |
| Final trained recommender (live) | `FinalRecommender` | T4 |
| Whole-history replay, input back-test | `walk_forward_history`, `history_backtest` | T4 §6 |

- **The difference is the job, not the method:**
  - **T1–T3** compare the winner against the *losing* alternatives (this is where the rejected models live).
  - **T4** is the final product: trained on everything, scored on both client yardsticks, with the live input cell.
  - **nb04 / nb05** take the *same* winners and look inside them in detail: nb04 at 15-minute resolution (each reversal cycle with its own NCV), nb05 hour by hour for MB3 and boost scenarios.
- **The same terms everywhere:** gas (heat) target, conformal shift, coverage, pinball loss, air per Mcal, AFR, MB3 target, step response, integral controller, walk-forward, draw-adjusted (Model A), ageing-adjusted (Model B), 5-t band baseline, P1–P99 limits. They are defined in section 12.
- **Why the numbers differ slightly between notebooks** (they measure the same thing at different detail):

| Number | Where | Why it differs |
|---|---|---|
| Gas saving 0.81% vs 0.70% | nb04 (15-min) vs T4/nb05 (daily) | nb04 divides each 15-min heat by *that* interval's NCV. The daily version uses the day total |
| Final 1.26% vs 1.27%; draw-adjusted −0.16% vs −0.17% | nb05 vs T4 | nb05 applies the air saving as an average %, T4 applies it day by day |
| Whole replay vs Jun–Aug | T4 §6 vs T4 §2 | §6 runs the boost controller continuously from Dec 2025; §2 starts it fresh on 1 Jun |

---

## 11. Using the final notebook (T4) yourself

1. Open `notebooks/training/T4_final_model_and_recommender.ipynb` and run all cells once (a few minutes).
2. **§5, input cell:** edit `INPUTS` (date, NCV, draw, cullet, optical of the last 24 h, barrier and melter boost of the last hour, MB3 now) and run it. You get:
   - NG setpoint, secondary air, AFR (for the next reversal cycle)
   - barrier boost for the next hour
   - each value next to its historical P1–P99 limit, plus any warnings (flags)
3. **§6, back-test cell:** run `backtest_inputs(INPUTS)`. For days in history with similar draw, NCV and cullet, it shows:
   - the **actual average SFC** on those days
   - the **SFC the recommender would have given on the same days** (walk-forward), and the saving
   - both values **draw-adjusted** and against the **band baseline**
   - the **setpoints** used on those days (all, and the best 25%) next to today's recommendation
   - a chart, day by day, of actual vs recommender
   - Example (NCV 9,300, 58 t, 18% cullet): 13 similar days, actual **1,579.8** → recommender **1,560.8** kcal/kg (**−1.2%**), draw-adjusted +1.20% → −0.02%.
   - "Today's expected SFC" is usually higher than older similar days because it includes today's furnace age. Compare actual vs recommender for the saving.

---

## 12. Glossary

| Term | Meaning |
|---|---|
| **SFC** | Energy per kg of glass (kcal/kg). Lower is better |
| **NCV** | Heat per SCM of gas (kcal/SCM); changes every 15 min |
| **Draw** | Glass pulled per day (t). The biggest driver of SFC |
| **Usable day** | A day with ≥ 90% valid NCV and gas/boost data, and a draw value |
| **Baseline / target** | 1,576.3 / 1,544.8 kcal/kg (client, Sep 2025 – Jul 2026) |
| **5-t band baseline** | Average baseline SFC of days with similar draw (45–50, 50–55, 55–60, 60–65 t) |
| **Model A (draw-adjusted)** | `E = 53.55 + 0.605·draw + 0.123·cullet`; % = actual ÷ expected − 1 |
| **Model B (ageing-adjusted)** | Model A + furnace age; used for discussion |
| **Ageing** | Slow efficiency loss: +0.19% energy per month |
| **Gas (heat) target** | Daily gas heat the efficient quarter of comparable days needed |
| **OLS** | Ordinary least squares: fitting a straight-line equation to data |
| **Conformal shift** | Correction that moves the equation's prediction to the 25th percentile of its recent errors |
| **Coverage** | Share of days that beat the target; should be ~25% |
| **Pinball loss** | Accuracy score for a percentile target; lower is better |
| **Walk-forward** | Testing each day with a model trained only on earlier days |
| **Validation month** | A month used only to check, not to choose (Sep 2026; next: Oct 2026) |
| **Air per Mcal** | Secondary air per Mcal of gas heat; the air control quantity |
| **AFR** | Air-fuel ratio = secondary air ÷ NG |
| **MB3** | Bottom thermocouple; controlled by barrier boost |
| **Step response** | How much MB3 rises over the hours after a lasting +1 kWh/h boost step |
| **Integral controller** | Each hour, adds a small correction proportional to the MB3 error |
| **Closed-loop replay** | Re-simulating history with our boost: MB3 = actual MB3 + effect of our boost changes |
| **P1–P99 limits** | Range covering 98% of history; recommendations never leave it |
| **Guard-rail** | A check that flags or stops (e.g. seeds > 21 two days running, optical out of band) |
| **Scenario B / extrapolation** | Anything outside the historical range; not recommended without a trial |

---

## 13. Honest limits

- **The saving changes from month to month** (Sep 2026: 0.55%). Judge the trial on at least 30 days.
- **Sep 2026 was used once** to decide that optical stays out of the gas model, so October 2026 is the next clean check.
- **No O₂ analyser:** air stays inside history.
- **Historical limits** stand in for official plant limits until the plant supplies them.
- **Trial levers** (lower MB3 target, less air, lower crown) can't be proven from history. That is why they are trial steps with guard-rails, not recommendations yet.
