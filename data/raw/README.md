# data/raw

Client files **exactly as received**. Do not edit, rename columns or overwrite files here; cleaned data goes to `data/processed/`.

## Expected files

| Suggested file name | Content | Frequency | Status |
|---|---|---|---|
| `SFC_60_TPD_Baseline_Calculation_Sep-25_to_Jul-26_updated.xlsx` | Client baseline: daily NG, NCV, boost, draw, SFC | Daily | Received (not yet added to repo) |
| `energy_15min_<from>_<to>.xlsx` | Melter NG, NCV, melter boost, barrier boost | 15 min | Pending |
| `bottom_temp_1min_<from>_<to>.csv` | All bottom thermocouples | 1 min | Pending |
| `crown_temp_<freq>_<from>_<to>.csv` | All crown thermocouples | 1 min / 1 h | Pending |
| `draw_per_line_<from>_<to>.xlsx` | Draw per line S09–S12 | Shift / hour | Pending |
| `line_events_<from>_<to>.xlsx` | Line stops and job changes | Event log | Pending |
| `cullet_batch_<from>_<to>.xlsx` | Cullet %, batch recipe changes | Daily | Pending |
| `combustion_<from>_<to>.csv` | Air flow, O₂, CO, preheat, waste gas, pressure | 1–15 min | Pending |
| `quality_<from>_<to>.xlsx` | Defects per line | Shift / day | Pending |
| `furnace_info.xlsx` or `.pdf` | Limits, furnace type, maintenance history | One-time | Pending |

Use dates as `YYYYMMDD`, e.g. `energy_15min_20250901_20260731.xlsx`. If the client's original file name is different, keep it as is and add a row to the table above.

## Format notes

- One row per timestamp; date and time in a single column in plant local time.
- Keep the original tag names and units in the header. Note any unit doubts in the table above.
- Full request with priorities: `docs/02_plant_team_data_request.md`.
