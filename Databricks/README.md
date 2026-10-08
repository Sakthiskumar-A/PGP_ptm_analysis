# SFC recommender on Databricks: training → MLflow (UC) → serving endpoint → operator app

```
Databricks/
├── training/
│   ├── 01_train_register_mlflow.ipynb   train, check, log + register in Unity Catalog, alias, move the endpoint
│   └── sfc_pyfunc.py                    the model code (recommendation logic) packed into the MLflow model
├── app/                                 Databricks App (Dash) for the operators
│   ├── app.py
│   ├── app.yaml
│   └── requirements.txt
└── reference/                           the original DCS / NCV monitor app (unchanged)
```

## How it fits together

```
Excel / Delta table ──► 01_train_register_mlflow (job, daily)
                              │  checks pass?
                              ▼
          UC model prod_pgp_mfg.cantier.sfc_60tpd_recommender
              version N  ◄── alias "champion"   (version N-1 ◄── "previous")
                              │  job moves the endpoint to the champion version
                              ▼
          Serving endpoint sfc-60tpd-recommender  (input: one row of live values)
                              ▲
   DCS view (1-min) ─┐        │ dataframe_records
   NCV blobs (MQTT) ─┼──► Dash app ──► NG, secondary air, AFR, barrier boost + warnings
   operator inputs  ─┘
```

The model is the same one as `models/recommender_latest.json` / `client/databricks/` (the training notebook reproduces its numbers exactly). It is logged as an MLflow **pyfunc**, so the endpoint does the whole recommendation (gas target → NG → air → AFR, MB3 controller → boost, historical limits, warnings). The app only collects inputs and shows the output.

## Notes on the approach

The plan (train in a notebook → register in MLflow → serve by alias → Dash app calls the endpoint) is sound. Four details matter:

1. **An endpoint does not follow an alias by itself.** A serving endpoint is pinned to a version number. Moving `champion` changes nothing on the endpoint. So the training notebook's last step updates the endpoint to the new champion version (zero downtime). Set the `endpoint_name` job parameter once the endpoint exists.
2. **Turn scale-to-zero off on the endpoint.** A cold start takes several minutes, and operators have a 5-minute window (minute 15–20 of the reversal cycle). The smallest CPU size is enough.
3. **The app can also run without the endpoint.** With `SERVING_ENDPOINT` empty, it loads `UC_MODEL_NAME@champion` directly (same code, same numbers).
4. **Training data should move from Excel to a Delta table.** The notebook takes either `input_path` (xlsx/csv/parquet) or `source_table`. Once the 15-min record is a table, the daily job needs no manual upload.

## Step 1: upload

| What | Where |
|---|---|
| `training/01_train_register_mlflow.ipynb` **and** `training/sfc_pyfunc.py` | the **same** workspace folder, e.g. `/Workspace/Shared/sfc_60tpd/training/` |
| the analytical record (`Analytical_Record_Creation_fixed_5.xlsx`, sheet `result`, or `client/databricks/input/analytical_record_15min.csv`) | a Volume, e.g. `/Volumes/prod_pgp_mfg/cantier/60_tpd_sfc/input/` |

You need `CREATE MODEL` and `USE SCHEMA` on `prod_pgp_mfg.cantier`, plus read access to the Volume.

## Step 2: train and register (run the notebook once)

Open the notebook on a cluster with DBR 14.3+ (or serverless) and set the widgets:

| Widget | Example |
|---|---|
| `input_path` | `/Volumes/prod_pgp_mfg/cantier/60_tpd_sfc/input/Analytical_Record_Creation_fixed_5.xlsx` |
| `excel_sheet` | `result` |
| `source_table` | leave empty (or a Delta table with the same columns; it overrides `input_path`) |
| `uc_model_name` | `prod_pgp_mfg.cantier.sfc_60tpd_recommender` |
| `experiment_path` | `/Shared/sfc_60tpd/recommender_training` |
| `endpoint_name` | leave **empty** on the first run |

Run all. Result:
- the MLflow run (parameters, metrics, `model.json`, training report, limits) in the experiment
- **version 1** of `prod_pgp_mfg.cantier.sfc_60tpd_recommender` with alias **`champion`** (if all 7 checks pass)
- section 12 reloads the registered model, checks it reproduces the notebook, and prints an example request

Expected on the current data (trained until 2026-09-29): 343 usable days, all checks PASS, walk-forward coverage 23%, MB3 gain 1.94 °C per 100 kWh/h, air target 1.2676 SCM/Mcal.

## Step 3: create the serving endpoint (once)

**UI:** *Serving* → *Create serving endpoint*
1. Name: `sfc-60tpd-recommender`
2. Served entity: *Unity Catalog model* `prod_pgp_mfg.cantier.sfc_60tpd_recommender`, version = the one with alias `champion` (Catalog Explorer shows the aliases)
3. Compute: CPU, size **Small**, **Scale to zero: off**
4. Create, then wait for *Ready* (about 5–10 min the first time; it builds the environment from the model's `pandas`/`numpy`/`mlflow` pins)

**Or in a notebook:**
```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import EndpointCoreConfigInput, ServedEntityInput

w = WorkspaceClient()
model = "prod_pgp_mfg.cantier.sfc_60tpd_recommender"
version = w.model_versions.get_by_alias(model, "champion").version
w.serving_endpoints.create(
    name="sfc-60tpd-recommender",
    config=EndpointCoreConfigInput(served_entities=[ServedEntityInput(
        entity_name=model, entity_version=str(version), workload_size="Small", scale_to_zero_enabled=False)]),
)
```

**Permissions** (endpoint → *Permissions*): the app's service principal **Can Query**; the job's identity (the user or service principal that runs the training job) **Can Manage**.

**Test it** (*Serving* → endpoint → *Use* → *Query*, or):
```bash
curl -X POST "https://<workspace-host>/serving-endpoints/sfc-60tpd-recommender/invocations" -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{"dataframe_records":[{"timestamp":"2026-10-08 10:15","ncv":9300,"draw_t":58,"cullet_pct":18,"bb_kwh_last_hour":350,"mb_kwh_last_hour":305.6,"mb3_now":1321.5,"optical_temp":1574}]}'
```
Expected (model trained until 2026-09-29): `ng_setpoint` 88.41, `air_setpoint` 1042.2, `afr_setpoint` 11.79, `bb_setpoint_kwh_h` 343.5, `gas_target_gcal_day` 78.93, `flags` empty.

## Step 4: make training a job (retraining)

*Workflows* → *Create job* → task type *Notebook* → `01_train_register_mlflow`, with the same parameters as the widgets plus **`endpoint_name = sfc-60tpd-recommender`**. Schedule daily, after the previous day's SAP draw is in the data (e.g. 06:30 IST).

Each run registers a new version. If the checks pass: `previous` ← old champion, `champion` ← new version, endpoint → new version. If a check fails, the version is registered with tag `checks_passed=false`, and `champion` and the endpoint stay where they were.

Before a retrain, update the Excel file in the Volume (same path) or point `source_table` at the table.

**Rollback:** Catalog Explorer → model → set alias `champion` on the `previous` version, then on the endpoint *Edit* → choose that version (or rerun the job's last cell).

## Step 5: deploy the operator app

1. *Compute* → *Apps* → *Create app* (custom), upload `app/` (`app.py`, `app.yaml`, `requirements.txt`).
2. App **resources** (the keys must match `app.yaml`):
   - SQL warehouse `c5b898c9dc1668ef`: *Can use*
   - secret with the Azure Blob connection string, key **`azure-blob-secret`** (as in the reference app)
   - serving endpoint `sfc-60tpd-recommender`: *Can query*, key **`serving-endpoint`**
3. Grants for the app's service principal:
   - `SELECT` on `prod_pgp_mfg.cantier.vw_dcs60tpd_live`
   - `USE CATALOG` on `prod_pgp_mfg`, `USE SCHEMA` + `CREATE TABLE` on `prod_pgp_mfg.cantier` (the app creates the audit table on first use), then `MODIFY` + `SELECT` on the audit table if it is created by someone else
4. Set `AUDIT_TABLE` in `app.yaml` (default `prod_pgp_mfg.cantier.sfc_60tpd_setpoint_audit`) and deploy.

**Without the endpoint** (fallback): set `SERVING_ENDPOINT` to `value: ""`. The app then loads `UC_MODEL_NAME@champion` itself and needs `EXECUTE` on the model.

### How operators use it

| Tab | What happens |
|---|---|
| **Recommendation** | Enter draw, cullet, optical temperature and the last hour's barrier and melter boost (kWh/h), then click **Get recommendation**. The app reads the live DCS and NCV values at that moment, calls the endpoint, shows NG, secondary air, AFR and barrier boost (kWh/h) with the historical range and warnings, and writes a `RECOMMENDATION` row to the audit table. Live values and charts refresh every 60 s; the recommendation changes only on a click. |
| **Record applied set points** | Shows the latest recommendation. The operator enters what was actually set on the DCS (NG, secondary air, barrier boost), name/ID and remarks. The difference to the recommendation is shown while typing. **Save to audit** writes an `OPERATOR_SET` row. |

### Audit table

Append-only, one row per event, created automatically (`CREATE TABLE IF NOT EXISTS`) on the first write. The two rows of one cycle share `recommendation_id`:

| Columns | Content |
|---|---|
| `audit_id`, `recommendation_id`, `event_type`, `event_time`, `app_user`, `operator_name` | `RECOMMENDATION` or `OPERATOR_SET`; `app_user` = signed-in Databricks user |
| `recommendation_for`, `model_version`, `trained_until`, `model_source` | which model gave the recommendation |
| `ncv`, `draw_t`, `cullet_pct`, `optical_temp`, `bb_kwh_last_hour`, `mb_kwh_last_hour`, `boost_source`, `mb3_now`, `ng_now`, `air_now` | the inputs used |
| `ng_recommended`, `air_recommended`, `afr_recommended`, `bb_recommended_kwh_h`, `gas_target_gcal_day`, `sfc_expected`, `draw_adjusted_pct`, `flags` | the recommendation and its warnings |
| `ng_set`, `air_set`, `afr_set`, `bb_set_kwh_h`, `remarks` | what the operator set (`OPERATOR_SET` rows only) |

Recommended vs applied for the trial:
```sql
SELECT recommendation_for, operator_name, ng_recommended, ng_set, air_recommended, air_set,
       bb_recommended_kwh_h, bb_set_kwh_h, remarks
FROM prod_pgp_mfg.cantier.sfc_60tpd_setpoint_audit
WHERE event_type = 'OPERATOR_SET'
ORDER BY event_time DESC
```

### What the app does with the live data

| Model input | From | How |
|---|---|---|
| `ncv` | MQTT blobs | latest reading inside 8,500–10,500 and within 400 of the trailing 2 h median (training rules); falls back to the last valid value, flagged when older than 30 min |
| `mb3_now` | DCS view, 1-min | mean of the last 60 min (the boost controller is hourly); needs ≥ 30 valid minutes |
| `ng_now`, `air_now` | DCS view, 1-min | mean of the last 15 min. The training record's 15-min values are the means of this same tag, so the units match |
| `draw_t`, `cullet_pct`, `optical_temp` | operator | typed on the page, remembered in that browser; typos outside plausible ranges block the recommendation (optical only warns) |
| `bb_kwh_last_hour`, `mb_kwh_last_hour` | operator **for now** (kWh/h) | set `BOOST_QUERY` (SQL returning one row: `ts, bb_kwh_last_hour, mb_kwh_last_hour`) and the app reads them from the DB and hides the two fields |
| MC3 crown TC | DCS view | not a model input; used to check the optical reading (optical ≈ MC3 + 7.6 °C, warns if more than 5 °C off) |

## Endpoint contract

**Request** (`dataframe_records`, one row):

| Field | Type | Required | Meaning |
|---|---|---|---|
| `timestamp` | string | yes | `YYYY-MM-DD HH:MM` IST (the furnace-age term uses the date) |
| `ncv` | double | yes | kcal/SCM |
| `draw_t` | double | yes | t/day |
| `cullet_pct` | double | yes | % (only for the draw-adjusted yardstick) |
| `bb_kwh_last_hour`, `mb_kwh_last_hour` | double | yes | kWh in the last hour |
| `mb3_now` | double | yes | °C |
| `optical_temp` | double | no | °C, guard-rail only |
| `ng_now`, `air_now` | double | no | current values, DCS unit |

**Response** (`predictions[0]`): `ng_setpoint`, `air_setpoint`, `afr_setpoint`, `bb_setpoint_kwh_h`, `bb_setpoint_kwh_15min`, the raw model values (`*_raw`), the historical limits (`*_lo`, `*_hi`), `*_at_limit`, `gas_target_gcal_day`, `mb3_target`, `sfc_expected`, `sfc_baseline_at_draw`, `draw_adjusted_pct`, `draw_band`, `band_baseline_sfc`, `band_target_sfc`, `flags` (`" | "`-joined warnings), `model_version`, `trained_until`.

## Still to confirm with the plant

- **NG and air units at the controller.** The recommendation is in the training record's unit, which is the 15-min mean of the 1-min DCS tag. That mean includes the short flow dips at each reversal. Compare the 1-min tag while firing with its 15-min mean in the live view. If they differ by more than a percent or so, the operator's controller setpoint needs a fixed factor (applied in the app).
- **Boost feed.** Send the table/query for the last hour's barrier and melter boost, then set `BOOST_QUERY`.
- **Operator inputs are stored per browser.** If several screens must share one draw/cullet entry, those values should go to a small Delta table instead.
