# Plant Team Meeting: Questions to Ask

**Purpose:** understand how the 60 TPD furnace is really run, so the data makes sense and we find where the 2% can come from.
**Rule of thumb:** ask open questions first ("how do you…"), then specific ones. Write down numbers, names and dates.

⭐ = must ask, even if time is short.

---

## Numbers to have in front of you

| Month | Avg draw (t/day) | Avg SFC (kcal/kg) | Barrier boost (kWh/day) | Melter boost (kWh/day) |
|---|---|---|---|---|
| Sep-25 | 57.2 | 1,527 | ~10,800 | ~6,200 |
| Mar-26 | 57.2 | 1,593 | ~8,900 | ~7,300 |
| Jul-26 | 55.0 | 1,652 | ~6,900 | ~7,300 |

- Baseline 1,576.3 kcal/kg → target 1,544.8 kcal/kg.
- Daily NCV ranged 8,822–10,431 kcal/SCM.

---

## 1. Furnace basics (warm-up, 5 min)

**1.1 What type of furnace is it: end-port regenerative, side-port, or recuperative? How many burners? If regenerative, what is the reversal time?**
- *Why:* firing patterns, heat recovery and the right data frequency depend on furnace type. A 20-min reversal cycle won't show up properly in 15-min data.
- *Listen for:* reversal time, burner count, whether ports fire equally.

**1.2 ⭐ When did the current campaign start, and what hot repairs or maintenance were done between Sep-25 and today (regenerator cleaning, overcoating, electrode changes, burner changes)?**
- *Why:* furnace ageing and maintenance change energy use. We need these dates to explain step changes in SFC and not blame operations for them.
- *Listen for:* exact dates. Ask for a list by email afterwards.

---

## 2. How the furnace is fired today

**2.1 ⭐ What does the main firing loop control: crown temperature, a fixed gas flow (SCM/h), or a fixed heat input (kcal/h)? Is it in auto or manual most of the time?**
- *Why:* this decides how we design recommendations. If gas is held at a fixed flow, every NCV change becomes a heat change, and that is the main NCV opportunity.
- *Listen for:* "we keep flow constant" (big opportunity) vs "crown temp controls gas" (NCV effect already partly absorbed, slower).

**2.2 ⭐ When NCV changes, what do operators do? How do they know NCV has changed? Is there any automatic correction?**
- *Why:* our daily data shows gas is only partly adjusted. At the same draw, gas energy still rises about 0.45 Gcal/day for every +1,000 kcal/SCM of NCV. We want to know if this is a habit, a lag, or a missing signal.
- *Listen for:* how often they check NCV, the reaction time, whether NCV is on the DCS screen.

**2.3 Where does the NCV value come from: an online analyzer at site or the gas supplier? How often is it updated, and how is the daily NCV in the baseline calculated?**
- *Why:* if NCV comes late or is averaged, real-time compensation needs a different design. A simple daily average NCV (not flow-weighted) slightly distorts the baseline SFC.

**2.4 ⭐ How is combustion air controlled: fixed ratio to gas, or trimmed by flue O₂? What O₂ % do you aim for, and where is the O₂ analyzer?**
- *Why:* excess air is one of the biggest and cheapest energy losses (typically 1–2% potential). If air isn't adjusted with NCV, O₂ drifts.
- *Listen for:* the O₂ target, whether the analyzer works reliably, whether they fear CO or reducing conditions.

**2.5 Is the gas flow meter corrected for temperature and pressure? Is the melter gas from the supplier's billing meter or the plant's own meter?**
- *Why:* uncorrected flow gives wrong energy numbers, and our model would learn from wrong data.

---

## 3. Electric boosting

**3.1 ⭐ Barrier boost dropped from about 10,800 kWh/day in Sep-25 to about 6,900 in Jul-26, while SFC went up. Why was it reduced?**
- *Why:* in the data, each extra 1 Gcal of boost replaced about 1.6 Gcal of gas. Restoring boost could be a big lever, but only if the reason for cutting it (electrode wear, current limit, cost, quality) is solved.
- *Listen for:* electrode problems, a cost decision, transformer limits, a quality issue.

**3.2 ⭐ What are the safe limits for melter and barrier boost: maximum kW or current per electrode group and transformer capacity? How close to the limit do you run today?**
- *Why:* this is the hard upper limit for any gas-to-boost shift we recommend.

**3.3 When and why do operators change the boost? Is there a standard rule (by draw, by bottom temperature, by job)?**
- *Why:* tells us whether boost is managed deliberately or left fixed, and how it is linked to bottom temperature.

**3.4 How does the plant compare the cost of 1 Gcal from electricity vs 1 Gcal from gas? Is moving energy to boost acceptable if it costs more?**
- *Why:* the SFC formula counts electricity at 860 kcal/kWh, so more boost lowers SFC, but it may raise the energy bill. We need to know which matters more.

---

## 4. Draw and the four lines (S09–S12)

**4.1 ⭐ How is the SAP draw ("Glass given to Quality") measured: weighed, or calculated from gob weight × speed? Does it include rejects and cullet that returns to the furnace?**
- *Why:* draw is the denominator of SFC. If it's calculated, a wrong gob weight directly shifts SFC.

**4.2 ⭐ What time does the SAP production day start (06:00, 07:00, 00:00)? Is the energy-meter day the same?**
- *Why:* if the energy and draw days are cut at different times, daily SFC will be wrong and noisy. We need this to line up the 15-min energy with the daily draw.

**4.3 ⭐ What happens to energy when a line stops or changes job? Do operators reduce gas or boost, or keep the furnace as it is?**
- *Why:* draw is the biggest driver of SFC (+1 t/day ≈ −1% SFC). A line stop cuts draw while energy stays almost the same, so SFC jumps. If there's no standard practice for this, it's an opportunity.

**4.4 Can we get line-wise draw per shift and a log of line stops and job changes (start time, end time, reason)?**
- *Why:* daily draw alone can't show these events. With the log, we can separate "bad days because of the lines" from "bad days because of the furnace".

**4.5 What draw do you expect in the next 3–6 months? Any planned line or job changes?**
- *Why:* the target must fit the future draw. At lower draw, SFC naturally rises.

---

## 5. Batch and cullet

**5.1 ⭐ What is the cullet % in the batch, and how much did it change between Sep-25 and Jul-26? Is it internal or bought cullet?**
- *Why:* cullet typically saves about 2.5% energy per +10% cullet. If cullet fell during the year, that alone could explain part of the SFC rise. We need it so the model doesn't blame operations.

**5.2 Were there any batch recipe changes in the period? Is batch moisture measured?**
- *Why:* recipe and moisture changes affect melting energy and explain jumps in SFC.

**5.3 Is there a limit on cullet % (quality, availability, colour)? Any plan to increase it?**
- *Why:* more cullet is a strong lever, but it's a business decision. We need to know if it's on the table.

---

## 6. Temperatures and quality

**6.1 ⭐ What are the limits: maximum crown temperature, normal bottom temperature band, and normal setpoints?**
- *Why:* these are the hard constraints for any energy reduction. Our optimizer must stay inside them.

**6.2 ⭐ At what bottom temperature do quality problems (seeds, blisters, cords) start? Has anyone seen defects go up after reducing energy?**
- *Why:* tells us how much safety margin there is. If the furnace runs well above the minimum needed, that margin is wasted energy.
- *Listen for:* past experiences, e.g. "we tried lowering the crown temperature and got seeds".

**6.3 Crown temperature is logged hourly. Is 1-minute data available in the DCS or historian?**
- *Why:* hourly data is too slow to see how the furnace reacts to firing changes.

**6.4 Where are the bottom and crown thermocouples located? Are any known to be faulty or drifting?**
- *Why:* a faulty thermocouple can mislead both operators and our model.

**6.5 How is glass quality recorded: per line, per shift? Can we get defect data for the same period?**
- *Why:* quality is our guard-rail. We must prove savings don't increase rejects.

---

## 7. Why SFC got worse over the year

**7.1 ⭐ (Show the table at the top.) In Sep-25 and Mar-26 the draw was the same, but SFC was about 4% higher in March, and by Jul-26 it was about 1,650. What changed: furnace condition, boost, cullet, NCV, operating practice?**
- *Why:* this is the most important question. The cause of the drift is probably the biggest single lever. It also affects the target: from today's level, 1,544.8 is about a 6–7% cut, not 2%.

**7.2 Were the best SFC days (around 1,456–1,500 kcal/kg) different in any way: lines running, job mix, boost, cullet, operators?**
- *Why:* if the furnace has already run at that level, we can learn from those days and repeat them. That's usually the easiest saving to justify.

---

## 8. Target and baseline

**8.1 ⭐ How will success be judged: the absolute 1,544.8, the 2% target per draw band (as in your SFC Executive sheet), or SFC adjusted for draw and cullet?**
- *Why:* draw alone can move SFC by more than 2%. Without agreeing this, a good production month could look like success and a bad month could hide real savings.

**8.2 Is the baseline the simple average of daily SFC (1,576.3) or total energy ÷ total draw (1,573.2)?**
- *Why:* small difference, but we must use the same number as the client.

---

## 9. Systems and data access

**9.1 Which DCS/PLC and historian do you use (e.g. PI, Wonderware, Siemens, ABB)? Can we export tags at 1-min or 15-min intervals for Sep-25 to today?**
- *Why:* tells us what data is realistically available and in what format.

**9.2 Who is the contact person for data exports, and how long will it take?**
- *Why:* keeps the project moving. Agree a date before you leave the meeting.

---

## 10. Trial and changes

**10.1 Which settings could we change in a trial: gas setpoint, air/gas ratio, boost kW, temperature setpoints? Who approves changes?**
- *Why:* there's no point recommending something the plant can't or won't change.

**10.2 Could an NCV-based gas setpoint (gas SCM/h = required heat ÷ NCV) be added in the DCS, or should it start as an advisory sheet for operators?**
- *Why:* decides how we deliver the solution.

**10.3 Is any maintenance planned in the next 3 months (regenerator cleaning, electrode change, hot repair)?**
- *Why:* a trial must avoid these periods, or the results will be mixed up with the maintenance effect.

---

## 11. Ask their opinion (end of meeting)

**11.1 ⭐ In your experience, where is energy being wasted in this furnace? If you had to save 2% tomorrow, what would you change first?**
- *Why:* operators and shift engineers often already know the answer. It also gives the team ownership of the solution, which matters when the trial starts.

**11.2 Are there differences between shifts in how the furnace is run?**
- *Why:* shift-to-shift variation is a common hidden loss, and a standard operating practice can fix it at no cost.

---

## Before leaving the meeting, confirm

- [ ] Contact person for data exports
- [ ] Date when 15-min energy and 1-min temperature data will be shared
- [ ] Cullet % data: who will send it, and when
- [ ] Line stop / job change log: who will send it, and when
- [ ] Furnace limits sheet (crown max, bottom band, electrode limits)
- [ ] Maintenance history list with dates
- [ ] Next meeting date

Full data list with formats: `docs/02_plant_team_data_request.md`.
