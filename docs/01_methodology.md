# SFC Optimization: 60 TPD Melter (Lines S09–S12)

## Full methodology and explanation

This document explains **what** we are trying to achieve, **why** the data looks the way it does, and **how** we will get to a 2% SFC reduction, step by step. It is written so the whole approach can be understood and explained to the client and plant team.

---

## 1. The problem in one paragraph

The client wants the 60 TPD flint furnace to use **2% less energy per kg of glass** than its baseline (Sep-25 to Jul-26). Energy comes from two sources: natural gas burned in the melter, and electric boosting (melter boost + barrier boost). Gas quality (NCV) changes every 15 minutes, so the same gas flow gives a different amount of heat each time. Our job is to find out where energy is being wasted, build models that show how the furnace responds to gas and boost, and give the plant **setpoints for gas and electric boost** that use less energy while keeping glass quality and furnace safety intact.

---

## 2. Key terms

| Term | Meaning |
|---|---|
| **SFC** | Specific Fuel Consumption: total energy ÷ glass drawn, in kcal/kg. Lower is better. |
| **NCV** | Net Calorific Value of natural gas, in kcal/SCM: how much heat 1 SCM of gas gives. |
| **SCM** | Standard cubic metre of gas (volume at standard temperature and pressure). |
| **Melter boost** | Electric energy fed through electrodes in the melting zone (kWh). |
| **Barrier boost** | Electric energy through electrodes forming a hot "barrier" that controls glass flow and convection (kWh). |
| **Draw / pull** | Molten glass pulled from the furnace to the lines, in kg or tonnes per day. |
| **Crown temperature** | Temperature of the furnace roof (refractory). It has an upper limit to protect the refractory. |
| **Bottom temperature** | Temperature at the furnace floor. It indicates how well the glass is heated through and links strongly to quality. |
| **Cullet** | Recycled broken glass in the batch. It melts with less energy than raw batch. |
| **Baseline** | The reference SFC we measure savings against. |
| **Normalization** | Adjusting SFC for things outside operators' control (draw, cullet) so we compare like with like. |

---

## 3. How SFC is calculated (client formula)

```
Gas energy (kcal)        = NG (SCM) × NCV (kcal/SCM)
Electrical energy (kcal) = (Melter boost kWh + Barrier boost kWh) × 860
SFC (kcal/kg)            = (Gas energy + Electrical energy) / Draw (kg)
```

Example for 1 Sep 2025 (from the baseline workbook):
- Gas: 7,686 SCM × 9,604.6 kcal/SCM = 73.82 Gcal
- Electricity: (5,358 + 13,720) kWh × 860 = 16.41 Gcal
- Total: 90.23 Gcal ÷ 60,554 kg = **1,490 kcal/kg**

Important consequences of this formula:
1. **Electricity counts at 860 kcal/kWh**, its pure heat value. Electric boost delivers heat directly into the glass, so it is far more efficient than burning gas, where much of the heat leaves through the stack. Shifting energy from gas to boost therefore lowers SFC on paper. Whether that is cheaper in money terms is a separate question for the client.
2. **The draw is in the denominator.** If draw goes up while energy stays almost the same, SFC falls. This is the most important effect in the data (see section 5).
3. **NCV must be applied per interval.** With 15-min data, gas energy has to be calculated as `NG × NCV` for every 15 minutes and then summed. Using a daily average NCV gives a slightly wrong answer.

---

## 4. What the client baseline workbook tells us

**Period:** 1 Sep 2025 – 31 Jul 2026 (334 days, every day present).

**Baseline SFC:** 1,576.3 kcal/kg (simple average of daily SFC).
**2% target:** 1,544.8 kcal/kg.

The client also split SFC by **draw band** and set a 2% target for each band:

| Draw band | Days | Average SFC | 2% target |
|---|---|---|---|
| 45–50 t | 6 | 1,765 | 1,730 |
| 50–55 t | 63 | 1,663 | 1,629 |
| 55–60 t | 185 | 1,565 | 1,534 |
| 60–65 t | 80 | 1,520 | 1,490 |

The draw-band view shows the client already understands that SFC depends on draw. We will build on this with a proper regression baseline (section 6).

---

## 5. What the baseline data already shows

### 5.1 Draw is the biggest driver of SFC

The correlation between draw and SFC is **−0.88** (very strong). A straight-line fit of daily energy against draw gives:

```
Daily energy (Gcal) ≈ 55.4 + 0.608 × Draw (t)
```

- **55.4 Gcal/day is "fixed"**: heat lost through walls, crown, regenerators/recuperators and the flue, whatever the draw.
- **0.608 Gcal per tonne is "variable"**: the extra heat needed to melt each additional tonne.
- At average draw (57.4 t), fixed energy is about **60% of the total**.

**What this means in practice:** each extra tonne per day of draw lowers SFC by about **1%**, with no change to firing. A +2 t/day increase alone would deliver the whole 2% target. That is why we must not judge the 2% on the raw average: a good production month would look like an energy saving, and a bad month (line stoppages) would hide a real saving.

### 5.2 The furnace got less efficient over the year

| Month | Average draw | Average SFC |
|---|---|---|
| Sep-25 | 57.2 t | 1,527 |
| Mar-26 | 57.2 t | 1,593 |
| Jul-26 | 55.0 t | 1,652 |

September and March had the **same draw** but SFC was about **4% higher** in March. Possible reasons: furnace ageing (refractory wear, regenerator blockage), less electric boost, lower cullet, or changes in operating practice. In July the average was about 1,650 kcal/kg, so from today's level, reaching 1,544.8 means a **~6–7% cut, not 2%**. This must be discussed with the client before we commit to a number.

### 5.3 Barrier boost has dropped

Barrier boost fell from about **10,800 kWh/day (Sep-25) to about 6,900 (Jul-26)**. Melter boost settled around 7,300 kWh/day. In the data, every extra 1 Gcal of boost replaced about 1.6 Gcal of gas. This is a correlation, not proof, but it suggests that the drop in barrier boost explains part of the SFC increase. We need to know **why** it was reduced (electrode wear, current limits, cost decision).

### 5.4 NCV compensation is only partial

- NCV varied from **8,822 to 10,431 kcal/SCM** day to day (about ±8%).
- Gas volume moves against NCV (correlation −0.70), so operators do reduce gas when NCV is high.
- But at the same draw and boost, **gas energy still rises by about 0.45 Gcal/day for every +1,000 kcal/SCM of NCV**. On high-NCV days the furnace receives more heat than it needs.
- Inside a day, NCV changes every 15 minutes, so the effect is probably larger than the daily data shows.

### 5.5 Noise level

After removing the draw effect, day-to-day energy still varies by about **1.8%**. That is almost the same size as the target. To prove a 2% saving statistically we need about **30–40 trial days**, not a single good week.

---

## 6. Step-by-step methodology

### Phase 0: Data collection and agreement on definitions

- Collect the data listed in `02_plant_team_data_request.md`.
- Agree with the client:
  - which target is official (absolute 1,544.8, draw-band targets, or draw-normalized)
  - simple average vs weighted average SFC
  - the production-day boundary (e.g. 06:00–06:00) used in SAP and the energy meters

### Phase 1: Data engineering

**Goal:** one clean, time-aligned dataset.

1. **Load raw files** from `data/raw/` without editing them.
2. **Build three time levels:**

   | Level | Used for | Data |
   |---|---|---|
   | 15 min | Control and setpoints | NG, NCV, melter boost, barrier boost, bottom temperature (mean/min/max/std of the 1-min values) |
   | 1 hour | Furnace thermal behaviour | All of the above + crown temperature |
   | Daily | SFC and baseline | Summed energy, draw, cullet, line status |

3. **Calculate energy correctly:** `gas_kcal = NG × NCV` for each 15-min interval, then sum.
4. **Reconcile:** the daily sum of 15-min energy must match the client's daily energy in the baseline workbook (within ~0.5%). If not, find out why (meter differences, day boundary, missing intervals) before going further.
5. **Clean:**
   - flag flat-lined sensors, dropouts and impossible values
   - flag abnormal periods (hot repairs, furnace holds, major job changes); keep them but mark them

### Phase 2: Normalized baseline (measurement & verification)

**Goal:** a fair yardstick for "2% better".

Fit a model of **daily energy** using the things operators can't control:

```
Expected daily energy = β0 + β1 × Draw + β2 × Cullet% + β3 × Ambient temp + β4 × Time/furnace age
```

- Start with linear regression (simple, explainable, works with ~330 rows).
- **Normalized SFC** = actual SFC adjusted to reference conditions (e.g. 57.4 t draw, average cullet).
- **Saving** = expected energy − actual energy, tracked daily.
- Present this alongside the client's draw-band table so both views agree.

### Phase 3: Diagnostics (find where energy is lost)

1. **Best-days analysis.** Rank days by normalized SFC. Compare the best 25% with the worst 25% (only days with acceptable quality) on:
   - gas/boost split
   - crown and bottom temperatures
   - flue O₂ (if available)
   - NCV and its variability
   - number of lines running

   The question is: what did the plant do differently on its best days? This is usually the most convincing result for plant teams, because it shows the furnace has already done better.
2. **NCV impact.** Check how gas flow, crown temperature and bottom temperature respond when NCV changes, with 1–3 hour lags. Look for patterns where the furnace cools when NCV drops and operators then over-fire.
3. **Line availability.** Quantify how much SFC rises on days when one of S09–S12 is stopped or on job change.
4. **Temperature margin.** Compare quality defects against bottom temperature to find the lowest safe temperature. If the furnace runs well above it, that margin is wasted energy.
5. **Variability.** Large swings in crown and bottom temperature force operators to run "high for safety". Reducing swings lets the average come down.
6. **Boost analysis.** Relate barrier and melter boost to gas use and bottom temperature, and understand the reasons behind the barrier-boost reduction.

### Phase 4: Machine learning models

| Model | Purpose | Inputs | Output | Approach |
|---|---|---|---|---|
| **A. Daily SFC driver model** | Explain what drives SFC | Draw, cullet, boost share, NCV, temperatures, line status, month | Daily SFC | Ridge regression + LightGBM with SHAP values for driver ranking |
| **B. Furnace thermal model** | Predict how the furnace reacts to changes | Gas energy (kcal/h) and boost kW with lags (1, 2, 4, 8 h), draw, current temperatures | Bottom and crown temperature 1–4 h ahead | ARX / state-space first, then LightGBM with lag features; LSTM only if long 1-min data is available |
| **C. Quality guard-rail model** | Know how far temperatures can safely drop | Bottom temp, crown temp, draw | Seeds/blisters rate | Logistic or GBM model, or simple threshold analysis |

Rules:
- **Time-based validation only** (train on earlier months, test on later months). Random splits leak information in time series.
- Prefer models plant engineers can understand. A slightly less accurate but explainable model gets used; a black box gets ignored.

### Phase 5: Optimization (the recommendation engine)

Every 15 minutes, find the gas and boost setpoints that use the **least total energy** while respecting all limits:

```
Minimize:   Gas energy (kcal/h) + 860 × (Melter boost kW + Barrier boost kW)

Subject to:
  Predicted bottom temperature  within the quality band       (Model B + C)
  Predicted crown temperature   below the refractory limit    (Model B)
  Boost kW                      within electrode limits
  Flue O₂                       within the target band
  Setpoint changes              no faster than x% per hour (smooth operation)
```

- Tools: `scipy.optimize` or Pyomo on top of the ML models, or Bayesian optimization (Optuna).
- Output: an **operating window table** per draw band, showing target total heat, gas/boost split, O₂ target and temperature targets.

### Phase 6: Trial and verification

1. Start in **advisory mode**: operators see recommended setpoints and decide.
2. Reduce energy in small steps (~0.5% at a time), holding each step for several days while watching bottom temperature and defects.
3. Run for **4–6 weeks**.
4. Track daily **normalized SFC vs the baseline model** on a CUSUM chart. It shows the cumulative saving clearly.
5. Lock in the successful settings as SOPs or DCS setpoints.

---

## 7. NCV-based gas and electrical setpoint logic

This answers the client's question: *"NCV changes every 15 minutes, so what should we set for gas and electricity?"*

### Principle: control heat, not gas volume

Today the furnace is mainly controlled on **gas flow (SCM/h)**. When NCV changes, the same flow gives a different amount of heat, so the furnace drifts hotter or colder, and operators correct it late. The fix is to control on **heat input (kcal/h)**.

### The logic

**Step 1: decide the total heat needed** for the current draw (from the operating-window table in Phase 5):
```
Q_total (kcal/h) = f(draw, cullet %)
```

**Step 2: keep electric boost steady** as a base load:
```
Q_elec (kcal/h) = 860 × (Melter boost kW + Barrier boost kW)
```
- Boost controls bottom temperature and glass flow. It should change only when draw changes or bottom temperature trends, **not** because of NCV.

**Step 3: let gas absorb the NCV change**, recalculated every 15 minutes:
```
Q_gas (kcal/h)          = Q_total − Q_elec
Gas setpoint (SCM/h)    = Q_gas / NCV(now)
```

**Step 4: adjust combustion air with heat, not gas volume.** The air needed for burning is roughly proportional to the heat released, so air should follow heat input, with flue O₂ used as the final trim. If air isn't adjusted, excess air rises and carries heat out of the stack.

### Worked example (illustrative numbers)

Draw 57.4 t/day ≈ 2,392 kg/h. Target SFC 1,545 kcal/kg → total heat ≈ 3.70 Gcal/h.
Boost 700 kW total → 0.60 Gcal/h. Gas heat needed ≈ 3.10 Gcal/h.

| | NCV = 9,700 | NCV drops to 9,300 | NCV rises to 10,100 |
|---|---|---|---|
| Gas heat needed | 3.10 Gcal/h | 3.10 Gcal/h | 3.10 Gcal/h |
| **Gas setpoint** | **320 SCM/h** | **333 SCM/h** | **307 SCM/h** |
| If flow is held at 320 SCM/h | correct | heat −4%, furnace cools | heat +4%, wasted energy |

### Implementation stages

1. **Advisory:** a simple screen or Excel sheet showing recommended gas SCM/h, air flow and boost kW every 15 minutes.
2. **Feed-forward in the DCS:** gas flow setpoint = Q_gas / NCV calculated automatically (needs the plant's control engineers and an online NCV signal).

---

## 8. Where the 2% can come from

Typical ranges from glass-industry experience. Our data will confirm or reject each one.

| Lever | Typical potential | Depends on |
|---|---|---|
| NCV-compensated firing | 0.5–1.5% | 15-min NG + NCV data (promised) |
| Excess air / O₂ optimization | 1–2% | Flue O₂ and combustion air data |
| Lower temperature margin through tighter control | 0.5–1% | Temperatures + quality data |
| Optimized gas/boost split (incl. barrier boost) | 0.5–1%+ | Boost data + electrode limits |
| Keeping draw high (fewer line stops, better job-change planning) | Large, but a production decision | Line status data |
| More cullet | ~2.5% per +10% cullet | Cullet data; a business decision |

Combining two or three levers makes 2% realistic. NCV compensation and O₂ control are usually the fastest wins because they need no capital spend.

---

## 9. Risks and how we handle them

| Risk | Mitigation |
|---|---|
| Glass quality drops (seeds, blisters) | Quality guard-rail model; small steps; watch defects daily |
| Refractory damage from high crown temperature | Hard crown limit in the optimizer |
| Electrode damage from higher boost | Respect electrode current and kW limits from the plant |
| Savings hidden by draw changes | Normalized baseline; draw-band reporting |
| Data gaps or wrong meters | Reconciliation step in Phase 1 |
| Operators don't trust recommendations | Start in advisory mode; explainable models; best-days evidence |

---

## 10. Timeline (indicative)

| Week | Activity |
|---|---|
| 1–2 | Data collection, definitions agreed, data cleaning and reconciliation |
| 3–4 | Normalized baseline, diagnostics, best-days analysis |
| 5–7 | ML models (thermal, quality), optimizer, operating-window table |
| 8 | Review with plant team; agree trial plan |
| 9–14 | Advisory trial (4–6 weeks) with weekly M&V reports |
| 15 | Final report, SOP and setpoint handover |
