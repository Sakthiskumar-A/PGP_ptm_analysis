# SFC Setpoint Advisor: demo app

The operator app (`../app`) with **no integration and no secrets**, for showing the client.

| In production (`../app`) | In this demo |
|---|---|
| DCS 1-min view + NCV MQTT blobs | the analytical record Excel (`data/Analytical_Record_Creation_fixed_5.xlsx`), replayed at a **demo time** picked on the page |
| serving endpoint / UC model | `model/sfc_recommender.json` (the released model, trained until 2026-09-29) + `sfc_model.py`, the same logic the endpoint runs |
| audit Delta table | kept in memory while the app runs, shown in the second tab, downloadable as CSV |

Same screens and inputs: the operator types draw, cullet, optical temperature and the last hour's barrier and melter boost (kWh/h) and clicks **Get recommendation**. Extras for the demo:
- **Fill from Excel** puts the values recorded at the demo time into the inputs (each input also shows the Excel value as a hint).
- After a recommendation, a **demo comparison** shows what the plant actually did in the next hour and that day's actual SFC.
- **Model details** tab: what the model is, the formulas with this model's coefficients, a step-by-step worked example of the last recommendation, historical limits, release checks and the savings yardsticks.

Note for the demo: the model was trained on data up to 29 Sep 2026, so a demo time inside that period is a replay, not an out-of-sample test. The out-of-sample results are in the walk-forward back-tests (T4).

## Run on Databricks
*Compute* → *Apps* → *Create app* (custom) → upload this whole folder (`app.py`, `sfc_model.py`, `app.yaml`, `requirements.txt`, `data/`, `model/`) → Deploy. No resources or permissions needed.

## Run locally
```bash
pip install -r requirements.txt
python app.py
```
Open http://localhost:8050.
