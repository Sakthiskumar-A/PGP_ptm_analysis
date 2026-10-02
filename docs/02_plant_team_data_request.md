# Data Request and Discussion Guide: Plant Team

**Project:** SFC optimization, 60 TPD flint melter (lines S09, S10, S11, S12)
**Goal:** reduce SFC by 2% from the baseline (1,576.3 kcal/kg → 1,544.8 kcal/kg) without affecting glass quality or furnace life.

---

## How to use this document

- **Part A** lists the data files we need, with priority, frequency, period and format.
- **Part B** has the questions to ask the plant team in the meeting.
- **Part C** is a one-page checklist to tick off what has been received.

**Priority levels:**
- 🔴 **P1, critical:** the analysis cannot start properly without it.
- 🟠 **P2, important:** most of the energy savings are found here.
- 🟢 **P3, useful:** improves accuracy; send if easily available.

**Period for all data:** **1 Sep 2025 – 31 Jul 2026** (same as the baseline). Please also include **1 Aug 2026 to the latest date available**, so we can see the furnace's current condition.

**Format:** Excel or CSV. One row per timestamp. Timestamps in plant local time, with date and time in one column (e.g. `2025-09-01 06:15`). Please include tag names and units in the header.

---

## Part A: Data required

### A1. Energy data (15-min interval) 🔴 P1

Already discussed with the client; confirming the exact format.

| Column | Unit | Notes |
|---|---|---|
| Timestamp | date + time | Start or end of the 15-min interval? (please state) |
| Melter natural gas flow | SCM per 15 min (or SCM/h) | Melter burners only, no forehearth |
| NCV | kcal/SCM | Value valid for that 15-min interval |
| Melter boost | kWh per 15 min (or kW) | |
| Barrier boost | kWh per 15 min (or kW) | |

**Why we need it:** to calculate energy every 15 minutes with the NCV of that interval, and to study how the furnace reacts to NCV changes.

### A2. Furnace temperatures 🔴 P1

| Data | Frequency wanted | Notes |
|---|---|---|
| Bottom temperatures (all thermocouples) | 1 min | Please give the location of each thermocouple (sketch is fine) |
| Crown temperatures (all thermocouples) | **1 min if available in DCS** (currently 1 hour) | Hourly data is too coarse to see the furnace response to firing changes |
| Other furnace temperatures if logged | 1–15 min | Throat, glass at riser/working end, breast wall, regenerator/recuperator top and bottom, waste-gas temperature |

**Why we need it:** temperatures are the safety and quality limits. We can only reduce energy while they stay inside their limits.

### A3. Draw and production 🔴 P1

| Data | Frequency | Notes |
|---|---|---|
| Daily draw (SAP MB51) | Daily | Already received |
| Draw per line (S09, S10, S11, S12) | Per shift or per hour | Gob weight × sections × cavities × cuts per minute, or the IS machine production report |
| Line running / stopped status | Event log or per hour | Stop start time, end time, reason |
| Job change log | Event log | Line, time, old job, new job, gob weight |
| Batch charger rate | 15 min or hourly | If a batch weigher or charger counter is available |

**Why we need it:** draw is the biggest driver of SFC (correlation −0.88). Daily draw is too coarse; when a line stops, energy stays the same but draw falls, and SFC jumps. We need to see these events.

### A4. Batch and cullet 🔴 P1

| Data | Frequency | Notes |
|---|---|---|
| Cullet % in batch | Daily (or per batch change) | Split into internal (own) and external (bought) cullet if possible |
| Batch recipe / composition | When changed | Main raw materials and %; date of each change |
| Batch moisture | Daily or per shift | If measured |

**Why we need it:** cullet strongly affects melting energy (typically about 2.5% energy per 10% cullet). Without it, the model may blame operations for energy changes that are really caused by cullet.

### A5. Combustion data 🟠 P2

| Data | Frequency | Notes |
|---|---|---|
| Combustion air flow | 15 min or 1 min | |
| Flue gas O₂ % | 1 min if possible | Location of the analyzer |
| Flue gas CO (ppm) | 1 min | If available |
| Combustion air preheat temperature | 15 min | After regenerator/recuperator |
| Waste gas temperature | 15 min | At the stack or after heat recovery |
| Furnace pressure | 15 min | |
| Air/gas ratio setpoint | When changed | |
| Firing side / reversal events | Event log | Only for regenerative furnaces |

**Why we need it:** too much excess air is one of the largest and cheapest sources of energy loss. Each extra % of O₂ heats air that goes out of the stack.

### A6. Electric boosting details 🟠 P2

| Data | Frequency | Notes |
|---|---|---|
| Boost power per electrode group | 15 min | kW, voltage, current |
| Electrode limits | One-time | Maximum current / kW per group, recommended operating range |
| Boost transformer capacity | One-time | Total kW available for melter and barrier boost |
| Boost setpoint changes | Event log | When and why |

**Why we need it:** barrier boost dropped from about 10,800 kWh/day (Sep-25) to about 6,900 (Jul-26) while SFC went up. We need to know how much boost can safely be used.

### A7. Glass quality 🟠 P2

| Data | Frequency | Notes |
|---|---|---|
| Seeds / blisters count or rate per line | Per shift or daily | |
| Stones, cords and other melting defects | Daily | |
| Pack-to-melt % or reject % per line | Daily | |
| Quality complaints / holds | Event log | |

**Why we need it:** quality is our guard-rail. We must prove the energy reduction does not increase defects.

### A8. Operating limits and setpoints 🟠 P2 (one-time information)

| Item | Value needed |
|---|---|
| Maximum crown temperature (alarm / trip) | °C |
| Bottom temperature normal operating band | min °C – max °C |
| Normal crown temperature setpoint | °C |
| Minimum and maximum gas flow | SCM/h |
| Normal O₂ target in flue gas | % |
| Current temperature control mode | Manual or automatic? What controls gas: crown temp, a fixed flow, or energy? |

### A9. Furnace and equipment information 🟠 P2 (one-time)

| Item | Detail needed |
|---|---|
| Furnace type | End-port regenerative / side-port / recuperative / other |
| Reversal cycle | Minutes (if regenerative) |
| Burner type and number | |
| Furnace start date (current campaign) | Date of last cold repair |
| Hot repairs / maintenance in the period | Dates and what was done (e.g. regenerator cleaning, overcoating, electrode change) |
| Furnace drawing / layout | Including thermocouple and electrode positions |
| DCS / PLC system | Make and model, historian (e.g. PI, Wonderware), whether tag export is possible |

### A10. Other useful data 🟢 P3

| Data | Frequency | Notes |
|---|---|---|
| Ambient temperature and humidity | Hourly | Weather station or DCS |
| Gas composition / Wobbe index / specific gravity | 15 min | From the gas supplier or online analyzer |
| Gas pressure and temperature at the meter | 15 min | To check flow compensation |
| Gas cost (per SCM or per Gcal) and electricity cost (per kWh) | Monthly | For cost comparison of gas vs boost |
| CO₂ emission factors used by the plant | One-time | If they report CO₂ |
| Forehearth gas and electricity | Daily | Only to confirm it is excluded from SFC |
| Operator shift logbook | Per shift | Manual setpoint changes and remarks |

---

## Part B: Questions for the plant team

### B1. Target and baseline (to agree with management)

1. Which target will be used to judge success?
   - (a) the absolute value 1,544.8 kcal/kg,
   - (b) the 2% target for each draw band (as in the SFC Executive sheet), or
   - (c) a draw-normalized SFC (adjusted for draw and cullet)?
2. SFC drifted up during the year: about 1,527 in Sep-25, 1,593 in Mar-26 at the same draw, and about 1,652 in Jul-26. What is the reason (ageing, regenerator condition, lower boost, cullet, other)? Is the 2% measured from the yearly average or from the current level?
3. Is the official baseline the **simple average of daily SFC (1,576.3)** or the **total energy ÷ total draw (1,573.2)**?
4. Is a saving achieved by shifting energy from gas to electric boost acceptable, given electricity is counted at 860 kcal/kWh? Or does the plant also care about cost?

### B2. Data definitions

5. **Draw:** is the SAP draw ("Glass given to Quality") measured (weighing) or calculated (gob weight × speed)? Does it include rejected glass and cullet returned to the furnace?
6. **Day boundary:** what time does the SAP production day start (e.g. 06:00 or 00:00)? Is the energy-meter day the same?
7. **NCV:** where does the 15-min NCV come from (online gas chromatograph at site, or the gas supplier)? How is the daily NCV in the baseline calculated: simple average, or weighted by gas flow?
8. **Gas meter:** is the gas flow already corrected to standard conditions (temperature and pressure compensated)? Which meter is used: the supplier billing meter or the plant's own melter meter?
9. **Boost:** are the boost values from energy meters (kWh) or from transformer readings?

### B3. How the furnace is run today

10. How do operators adjust the gas when NCV changes? Is there any automatic correction?
11. What does the main firing control loop use as its setpoint: crown temperature, a fixed gas flow, or a fixed heat input?
12. How is combustion air controlled: fixed ratio to gas flow, or trimmed by O₂? What is the O₂ target?
13. When a line (S09–S12) stops or changes job, what do operators do with gas and boost? Is there a standard practice?
14. When and why do operators change the boost (melter and barrier)?
15. Why was barrier boost reduced from about 10,800 to about 6,900 kWh/day between Sep-25 and Jul-26?
16. What are the known quality problems linked to furnace temperature (seeds, blisters, cords)? At what bottom temperature do they start?
17. Are there shift-to-shift differences in how the furnace is run?

### B4. Constraints and opportunities

18. Which parameters can we change during a trial: gas setpoint, air/gas ratio, boost kW, temperature setpoints?
19. Who approves changes, and is there a management-of-change procedure?
20. Is it possible to connect a recommendation (e.g. gas setpoint from NCV) into the DCS, or must it be advisory only?
21. Is there a plan to increase cullet, or a limit on how much cullet can be used?
22. Are any maintenance activities planned in the next 3 months (regenerator cleaning, electrode replacement, hot repairs) that could affect a trial?
23. What is the expected draw for the coming months? Any planned line changes?

---

## Part C: Checklist

| # | Item | Priority | Received | Remarks |
|---|---|---|---|---|
| 1 | 15-min NG, NCV, melter boost, barrier boost | 🔴 | ☐ | |
| 2 | 1-min bottom temperatures + thermocouple locations | 🔴 | ☐ | |
| 3 | Crown temperatures (1-min if possible) | 🔴 | ☐ | |
| 4 | Draw per line per shift / hour | 🔴 | ☐ | |
| 5 | Line stop and job-change log (S09–S12) | 🔴 | ☐ | |
| 6 | Daily cullet % (internal / external) | 🔴 | ☐ | |
| 7 | Batch recipe changes | 🔴 | ☐ | |
| 8 | Combustion air flow, flue O₂, CO | 🟠 | ☐ | |
| 9 | Air preheat, waste gas temp, furnace pressure | 🟠 | ☐ | |
| 10 | Boost per electrode group + electrode limits | 🟠 | ☐ | |
| 11 | Quality defects per line per day | 🟠 | ☐ | |
| 12 | Operating limits and control setpoints (A8) | 🟠 | ☐ | |
| 13 | Furnace type, campaign, maintenance history (A9) | 🟠 | ☐ | |
| 14 | Ambient temperature / humidity | 🟢 | ☐ | |
| 15 | Gas composition / Wobbe, gas P & T | 🟢 | ☐ | |
| 16 | Gas and electricity cost | 🟢 | ☐ | |
| 17 | Answers to Part B questions | 🔴 | ☐ | |
| 18 | Data from Aug-26 to latest date | 🟠 | ☐ | |

---

## What we will give back

Once the P1 data is received, we will share:
1. A **reconciliation check**: our 15-min energy totals matched against the client's daily SFC.
2. A **draw-normalized baseline**, showing what SFC the furnace "should" have each day for its draw and cullet.
3. A **diagnostics report**: best-days analysis, NCV impact, line-stop impact, boost impact.
4. A **first set of recommendations**, including NCV-compensated gas setpoints and a gas/boost operating table per draw band.
