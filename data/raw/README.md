# data/raw

Client files **exactly as received**. Never edit them, rename their columns or overwrite them; cleaned data goes to `data/processed/` (written by `notebooks/01_data_audit.ipynb` through `src/data_prep.py`).

| File | Content | Frequency / period | Received |
|---|---|---|---|
| `Analytical_Record_Creation_EE_60TPD_updated-2.xlsx` | Sheet `result`: barrier and melter boost (kWh/15 min), NCV, cullet %, optical crown temp, secondary air, melter NG, MB3 bottom temp, AFR, seed count, SAP draw, SFC. Sheet `Sheet1`: plant's 2-model design | 15 min, 2025-09-01 → 2026-09-30 | 2026-10-04 |
| `DCS_60_TPD_MelterCrown3.xlsx` | Crown thermocouple TC MC3 (rows newest first) | 1 min, 2025-09-01 → 2026-10-01 | 2026-10-04 |
| `SFC_60_TPD_Baseline_Calculation_Sep-25_to_Jul-26_updated.xlsx` | Client baseline: daily NG, NCV, boosts, SAP draw (MB51), SFC; draw-band targets | Daily, 2025-09-01 → 2026-07-31 | 2026-10-02 |

Column meanings, units and known data problems are in `CLAUDE.md` (sections 3 and 4).

When new files arrive: add a row here, keep the client's file name, and note the period and units.
