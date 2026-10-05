# 60 TPD Melter: Final Approach and Trial Plan for the 2% SFC Reduction

**Audience:** plant team (process head, shift engineers, operators).
**Purpose:** explain what we recommend, why it works, what it can deliver, and how the trial proves it.
**Supporting work:** notebooks `01`–`05` and `training/T1`–`T4`; training details in `docs/06_model_training_and_selection.md`.
**Data:** the corrected analytical record `Analytical_Record_Creation_fixed_5.xlsx` (received 2026-10-05; optical log fixed, Sep 2026 draw added).

---

## 1. The message in one page

1. **The data confirms the client baseline.** Recomputed from raw data, SFC was **1,576.6 kcal/kg**, against the client's 1,576.3. The 2% target is **1,544.8 kcal/kg**, or −2% within each 5-t draw band.
2. **Three things decide SFC:**
   - **draw:** +1 t/day ≈ −1% SFC
   - **furnace ageing:** +0.19% energy per month at the same draw
   - **how gas, air and barrier boost are set:** this is the part we control
3. **Today the furnace is about 1.1% above the baseline** at the same draw (Jun–Aug 2026). Most of that is ageing, not operations.
4. **The two recommenders** (gas + air every reversal cycle, barrier boost every hour) save about **1.3% SFC compared with today's operation**. This was measured walk-forward on Jun–Aug 2026, with every setpoint kept inside the historical limits.
   - **Checked on an unseen month (Sep 2026): 0.55%.** The gas model held its calibration, but the bottom ran cold that month, so the boost controller *added* boost to hold MB3. The saving depends on how far the furnace is from its efficient operation; summer 2026 had more to remove.
5. **Three trial levers** add about **0.55% or more**: a lower MB3 target, air per Mcal at its historical P25, and a 1–2 °C lower crown setpoint. That brings the total to about **2% compared with today's operation at the same draw** (summer conditions).
6. **Against the fixed historical baseline**, the furnace must also make up the ageing drift (~1.1%). Setpoints alone can't do that; it needs higher draw (+1 t/day ≈ −1%), furnace maintenance, or an agreed ageing-adjusted baseline (section 6).
7. **The trial runs in 4 phases over about 14 weeks**, with daily guard-rails on seeds, MB3 and crown temperature, and daily M&V against the agreed baseline. **30 trial days measure the saving to ±0.74%** (95% confidence).

---

## 2. What we recommend to the operator

| | Gas recommender | Barrier-boost recommender |
|---|---|---|
| **When** | Every 20-min reversal cycle, ready by minute 15 (set in the minute 15–20 window) | Every hour |
| **Inputs** | Latest NCV (UEMS); draw and cullet (day); barrier + melter boost of the last hour (DB); optical crown temperature (average of the last 24 h) as a **guard-rail only** | MB3 bottom temperature now (DCS); boost of the last hour. Melter boost is not needed (T3 §4) |
| **Outputs** | **NG flow** (same unit as the workbook column; one value for both inlets), **secondary air**, **air-fuel ratio** | **Barrier boost (kWh/h)** for the next hour |
| **Limits** | NG, secondary air and AFR held inside their historical P1–P99 | Boost held inside its historical P1–P99 (114–610 kWh/h) |

Notebook `training/T4_final_model_and_recommender.ipynb` §5 has the input cell: type the plant values and get the recommendation.

---

## 3. Why this approach works (the furnace logic behind each part)

### 3.1 Gas: deliver the right heat, exactly
- **The daily heat target** comes from the furnace's **own recent best practice**: the gas that the most efficient quarter of comparable recent days needed (same draw, barrier and melter boost, furnace age).
  - It doesn't ask for anything the furnace hasn't already done.
  - On history, 20% of days in Jun–Aug and 26% in the unseen Sep 2026 actually used less gas than the target (25% intended). Those days had **the same crown temperature, a lower MB3 and fewer seeds**.
- **Exact NCV compensation:** NG = heat ÷ latest NCV.
  - Today operators make only about 17% of the needed correction in the same hour and about 73% after one hour, so the furnace swings between too much and too little heat.
  - Exact compensation delivers the target heat every cycle.
- **Steady heat** is spread evenly over the day. Hour-to-hour gas swings are mostly the 20-min reversal and operator moves (T1: they explain nothing about the heat actually needed).
- **Crown temperature is a guard-rail, not an input.** With the corrected optical log, the previous day's optical added no accuracy (T1). In September it ran about 1.3 °C low and pushed the target up, so only the version without it stayed calibrated (nb04 §8). A crown input with that sign would also fight a lower crown setpoint (trial lever C). The recommender flags an optical reading outside its historical band (1,568–1,578 °C).

### 3.2 Air: oxygen follows heat, not gas volume
- Secondary air follows gas **heat** (R² 0.66), not gas volume (R² 0.44). Richer gas (higher NCV) needs more oxygen per SCM.
- So we recommend **air per Mcal × heat**, and AFR = air ÷ NG.
- Less air per Mcal means less energy: extra air is heated up and leaves through the regenerators. The data shows this within the historical range (−0.01 SCM/Mcal ≈ −0.13 Gcal/day).
- **There is no O₂ analyser.** So the target is the P25 of the last 45 days, never below the historical P5.

### 3.3 Barrier boost: a temperature handle, not an energy saver
- Barrier boost heats the glass from below. **+100 kWh/h raises MB3 by about 1.9 °C** within 6–12 h, while gas barely moves MB3.
- But 1 Gcal of boost replaces only about **0.77–0.83 Gcal of gas**, so **more boost raises SFC**.
- **Melter boost** also warms the bottom, but only for a few hours (peak about +1.8 °C per +100 kWh/h after 4 h, then fading). It rarely changes, it doesn't improve the MB3 forecast, and a feedforward on it didn't hold MB3 any better. The hourly feedback on MB3 absorbs it, so the boost controller doesn't use it (T3 §4).
- The right use is the **minimum boost that holds MB3 at its target**. In Jun–Aug 2026, MB3 ran 1.5 °C above its historical median, so boost was higher than needed.
- The **integral controller** moves boost a little each hour toward what holds MB3 at target. In the closed-loop replay it tracked MB3 best, with calm moves.
  - The "copy the operators" regression was unstable (T3).
  - If NG is already at its historical maximum, boost isn't lowered further.

### 3.4 Why the plant can trust it
- **Walk-forward proof:** every number in this document comes from predicting each day only from earlier days, on Jun–Aug 2026 (and Mar–May 2026 for model selection), and is checked on the unseen month Sep 2026.
- **Inside history:** every setpoint stays inside the historical P1–P99. Fewer than 2% of 15-min recommendations touched a limit (mostly boost at its lower limit while MB3 was high).
- **Transparent:** the gas model is a simple equation with physically sensible signs: draw +0.50 Gcal/day per t, barrier boost −0.77 per Gcal, furnace age +0.35 Gcal/day per month. No black box.
- **Robust:** LightGBM, longer windows and other model types were tried. They promised bigger savings with unrealistic targets and were rejected (T1, T4 §2b).

---

## 4. What it delivers on history (walk-forward, every setpoint inside history)

### 4.1 Jun–Aug 2026 (85 usable days)

| Approach | SFC (kcal/kg) | Saving vs actual | Draw-adjusted vs baseline (Model A) | Ageing-adjusted vs baseline (Model B) |
|---|---|---|---|---|
| (1) Actual operation | 1,605.3 | – | **+1.14%** | +0.56% |
| (3) Gas recommender | 1,594.0 | 0.70% | +0.42% | −0.15% |
| (4) Gas + barrier-boost controller | 1,587.8 | 1.09% | +0.01% | −0.56% |
| **(5) = (4) + air target** | **1,585.0** | **1.27%** | **−0.17%** | **−0.73%** |

*(The 15-min back-test in nb04, which includes exact NCV handling interval by interval, gives 0.81% for gas alone.)*

### 4.2 Per 5-t draw band, Jun–Aug 2026 (% vs the band's baseline SFC; target −2%)

| Band | Days | Actual | Gas | Gas + boost | Gas + boost + air |
|---|---|---|---|---|---|
| 45–50 t | 5 | +0.23% | −0.67% | −0.33% | −0.62% |
| 50–55 t | 18 | +1.36% | +1.31% | +1.40% | +1.23% |
| 55–60 t | 33 | +1.36% | +0.53% | −0.08% | **−0.26%** |
| 60–65 t | 29 | +1.60% | +0.63% | 0.00% | **−0.15%** |

**Reading:**
- In the two most common bands (55–65 t, 62 of 85 days), the recommenders move SFC from about +1.5% *above* the band baseline to just *below* it.
- The 50–55 t band stays above its baseline. Low-draw days carry the fixed heat losses on fewer tonnes, and the furnace has aged since the baseline.
- **Keeping draw at or above 55 t/day** is itself one of the strongest levers.

### 4.3 Validation on an unseen month: Sep 2026 (27 usable days)

| Approach | Saving vs actual | Draw-adjusted (Model A) | Ageing-adjusted (Model B) |
|---|---|---|---|
| (1) Actual operation | – | +1.68% | +0.52% |
| (3) Gas recommender | 0.56% | +1.13% | −0.03% |
| (4) Gas + barrier-boost controller | 0.39% | +1.29% | +0.13% |
| **(5) = (4) + air target** | **0.55%** | **+1.13%** | **−0.03%** |

**Reading:**
- **The gas model holds:** 26% of days below target (25% intended) and a saving close to the summer's (0.56% vs 0.70%).
- **The boost lever reverses:** MB3 ran *below* target (1,319.7 vs 1,320.25 °C), so the controller adds about 9% boost to warm the bottom. That is the intended behaviour (it holds MB3), but it costs energy.
- **So the recommenders' saving is not a fixed number.** It is the inefficiency there is to remove: about 1.3% in a summer month with a hot bottom, about 0.5% in a month with a cold one. The −2% needs the trial levers on top.
- September was used once to decide that optical stays out of the gas model, so the next clean check is October 2026 or the shadow phase.

---

## 5. Path to 2%

All values are draw-adjusted vs the client baseline (Model A); "vs today" is the same quantity measured from Jun–Aug 2026 operation.

| Step | Change | Cumulative vs baseline | Cumulative vs today | Evidence |
|---|---|---|---|---|
| Today (Jun–Aug 2026) | – | +1.14% | 0 | measured |
| Gas recommender (NG = heat ÷ NCV, efficient target) | −0.72% | +0.42% | −0.72% | walk-forward (T4) |
| + Barrier-boost controller, MB3 at historical median | −0.41% | +0.01% | −1.13% | walk-forward replay (T4, nb05) |
| + Air per Mcal at rolling P25 | −0.18% | **−0.17%** | **−1.31%** | T2/nb04 relationship |
| **Trial lever A:** MB3 target → historical P25 (1,319.2 °C) | about −0.3% | about −0.45% | about −1.6% | nb05 replay (still inside history) |
| **Trial lever B:** air per Mcal → historical P25 (1.252) | about −0.25% | about −0.7% | about −1.85% | T2 relationship; needs an O₂/CO spot check |
| **Trial lever C:** crown (optical) setpoint −1 to −2 °C | to be measured | – | beyond −2% | needs the trial (crown has been held flat, so history can't tell) |
| **Draw:** +1 t/day sustained | about −1% | about −1.7% | – | baseline model |
| **Ageing recovery** (regenerator / checker maintenance) | up to about −1% | about −2% or better | – | plant decision |

**How to present this to the client:**
- **About 2% vs today's operation, at the same draw, is achievable with setpoints:** recommenders plus trial levers A–C (summer conditions; in a month like Sep 2026, with a cold bottom, the recommenders give less and the levers carry more).
- **−2% vs the fixed 1,576.3 baseline** also needs the ~1.1% ageing drift since the baseline made up, through draw (≥ 58–59 t/day average) or maintenance. Alternatively, agree an **ageing-adjusted M&V baseline** (Model B), under which the recommenders plus trial levers reach about −1.3% to −2%. Under IPMVP, ageing is a recognised non-routine adjustment because it is not caused by operation.

---

## 6. How success is measured (M&V)

### 6.1 Daily calculation
For each trial day:
1. **SFC** = (Σ NG × NCV + (barrier + melter kWh) × 860) / draw, using the client formula with only valid NCV.
2. **Expected energy (Model A, frozen):** `E_expected = 53.55 + 0.605 × draw_t + 0.123 × cullet_%` Gcal/day.
3. **Draw-adjusted %** = actual energy ÷ E_expected − 1.
   - Example, 29 Jul 2026: 49.7 t, 19% cullet → E_expected 85.98 Gcal; actual 86.80 → **+0.96%**. The raw SFC of 1,745 looked 10.7% worse, but almost all of that was low draw.
4. **Band view:** the day's SFC vs its 5-t band baseline (45–50: 1,765.9; 50–55: 1,664.0; 55–60: 1,566.7; 60–65: 1,521.5).
5. Optional **Model B** (with furnace age), for the ageing-adjusted view.

### 6.2 Statistics: how long must the trial run?
- Day-to-day noise of the draw-adjusted % is about **1.3%**, and days are correlated (lag-1 autocorrelation 0.44).
- The 95% uncertainty of the average over the trial:

| Trial days | ±95% band of the average |
|---|---|
| 14 | ±1.08% |
| 21 | ±0.88% |
| **30** | **±0.74%** |
| 45 | ±0.60% |

- **Each phase needs at least 30 days** to prove a ~1% change. The final claim should cover at least 30 days at the final settings.

### 6.3 Success criteria
1. **Average draw-adjusted % ≤ −2.0%** over ≥ 30 days at the final settings, with the 95% band entirely below 0.
2. **Per 5-t band:** every band with ≥ 5 trial days at or below its −2% target (or within its 95% band).
3. **Quality:** seeds within spec (≤ 30) every day; no rise in the weekly seed average above the historical P95 (21).
4. **Limits:** no setpoint outside the historical P1–P99; every clip and override is logged.

### 6.4 Monitoring
- **Daily M&V sheet:** draw, cullet, energy, SFC, draw-adjusted %, band %, seeds, MB3, optical.
- **CUSUM chart** of the daily draw-adjusted %. Its slope shows the saving rate.
- **Weekly review** with the process head.

---

## 7. Trial plan

| Phase | Weeks | What changes | Expected (draw-adjusted, vs today) | Go / no-go to the next phase |
|---|---|---|---|---|
| **0. Shadow mode** | 1–2 | Recommendations computed live and logged, **not applied**. Check the data feeds: NCV filter, optical typed with date and 24-h time, boost from DB, draw | 0 | Feeds complete for ≥ 95% of cycles; operators agree the recommendations are sensible; shadow results agree with the Sep 2026 validation |
| **1. Gas + air** | 3–6 | Operators set **NG and secondary air/AFR** from the recommender each reversal cycle. Boost as usual | about −0.9% | No guard-rail breach; draw-adjusted average below the Phase 0 level |
| **2. + Barrier boost** | 7–10 | Barrier boost from the controller, MB3 target **1,320.25 °C** (historical median) | about −1.3% cumulative | MB3 inside 1,317.6–1,323.9 °C ≥ 95% of hours; seeds normal |
| **3. Trial levers** | 11–14+ | One lever at a time, each held ≥ 7 days: **(A)** MB3 target −0.5 °C per week to 1,319.2; **(B)** air per Mcal toward 1.252 (with a portable O₂/CO check); **(C)** optical setpoint −1 °C, then −2 °C | about −1.9 to −2.2% cumulative | Guard-rails hold; keep each lever that shows a saving |
| **4. Lock-in** | after | Final settings become SOP; ≥ 30 days of M&V at the final settings | ≥ −2% vs today | Success criteria in section 6.3 |

### Guard-rails (checked daily; any breach → go back one step)
- **Seeds** > 21 on 2 consecutive days, or any day > 25.
- **MB3** outside **1,317.6–1,323.9 °C** for more than 3 consecutive hours.
- **Optical crown** below **1,570 °C** (historical P1) or more than 2 °C below the current setpoint step.
- **Crown thermocouple MC3** falls more than 3 °C below its previous-week average.
- **Any operator override** for safety or quality is logged with its reason. Repeated overrides on the same step mean go back one step.
- **NG at its historical limit** (flag in the recommender) for more than 2 h → check NCV and draw inputs.

### Roles
- **Operators:** apply the recommendations within the minute 15–20 window; log overrides.
- **Shift engineer:** checks guard-rails each shift.
- **Process head:** approves each phase change.
- **Data scientist:** daily M&V, weekly report, model refresh (the gas model refits daily on new data automatically).

### What we need from the plant before the trial
1. **October 2026 data** in the corrected format: the next clean validation month (Sep 2026 was used once to settle the optical decision).
2. Keep the **optical log** in the corrected format (day-first date, 24-hour clock), and fix the **draw doubling on month-start days** in the SAP extract (still present on 1 Oct 2025, 1 Jun 2026 and 1 Sep 2026; halved automatically for now).
3. **Official limits** for MB3, the optical band and electrode current, to replace the historical P1–P99 if they are tighter.
4. A **portable O₂/CO analyser** for lever B.
5. Agreement on the **success yardstick**: draw-adjusted Model A, band targets, and whether an ageing adjustment (Model B) is accepted.

---

## 8. Risks and how they are handled

| Risk | Mitigation |
|---|---|
| Glass quality drops (seeds) | Daily seed guard-rail; levers one at a time; history shows efficient days have *fewer* seeds |
| Crown or bottom too cold | MB3 controller built in (it adds boost when MB3 falls, as in Sep 2026); optical flagged outside its band; guard-rails on MB3, optical and crown TC |
| NCV meter glitch → wrong NG | NCV accepted only in 8,500–10,500 and within 400 of the ~2 h median; otherwise the last valid NCV is used |
| Incomplete combustion with less air | Air never below the historical P5; lever B only with an O₂/CO check |
| Savings hidden by draw changes | Draw-adjusted M&V and band view, never raw monthly averages |
| Furnace keeps ageing during the trial | Report Model A and Model B; ageing (+0.19%/month) is quantified and visible |
| Saving varies by month (1.3% in Jun–Aug, 0.55% in Sep 2026) | Judge on ≥ 30 days of M&V; the trial levers (MB3 target, air, crown) don't depend on how hot the bottom happens to run |
| Operators don't follow | Shadow phase first; simple look-up tables (T4 §4); override log |
