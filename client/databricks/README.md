# Databricks jobs — SFC recommender (60 TPD melter)

```
databricks/
├── 01_training_sfc_model.ipynb              training / retraining job
├── 02_inference_recommendation_email.ipynb  recommendation + historical-limit check + e-mail
├── input/
│   └── analytical_record_15min.csv          15-min analytical record (CSV or Parquet)
└── output/                                  written by the training job
    ├── sfc_recommender_latest.json          the released model (read by notebook 02)
    ├── sfc_recommender_<date>.json          versioned copy of every model
    ├── training_report_<date>.json          checks of that model
    ├── historical_limits.csv                P1–P99 limits
    └── recommendation_log.csv               appended by notebook 02 (one row per recommendation)
```

## Set-up in Databricks
1. Upload both notebooks and the `input/` folder to the same workspace folder, or put the data in a Volume and set `INPUT_DIR` / `OUTPUT_DIR` in the settings cell of each notebook (e.g. `/Volumes/prod_pgp_mfg/cantier/60_tpd_sfc/input`).
2. Run **01_training_sfc_model**. It writes the model to `output/`, and releases `sfc_recommender_latest.json` only if all checks pass.
3. Run **02_inference_recommendation_email**. It loads the model, takes the latest plant values (or the `MANUAL_INPUTS`), shows the setpoints with the historical-limit check, and previews the e-mail.
4. To send the e-mail, set `SEND_MAIL = True` in the settings cell of notebook 02. It is `False` by default, so a test run never e-mails anyone.

Both notebooks are self-contained (pandas, numpy, matplotlib, requests) and need no project code.

## Input data
The analytical record with its original column names (`Timestamps`, `NCV Meter`, `dcs_60_MelterGasflowvalue…`, `BARRIER BOOSTER-52`, `MELTER BOOSTER-51`, `dcs_60_ThermocoupleMelterBottom3…`, `dcs_60_SecondaryAirFlowvalue…`, `Melter Optical Temperature`, `Cullet %`, `Seed Count`, `Daily Draw`). If the live table uses other names, change only the `COLUMNS` map in each notebook. To read a table instead of a file, replace `read_table(...)` with `spark.table("...").toPandas()`.

## Scheduling
| Job | When | Why |
|---|---|---|
| 01 training | daily, after the previous day's SAP draw is available (e.g. 06:30) | the model follows the furnace (ageing, recent efficient level) |
| 02 inference | hourly (barrier boost), or every 20 min for the gas setpoints | operators set NG/air in the minute 15–20 window of each reversal cycle |

## Before production
- Move `MAIL_URL` into a secret scope (`dbutils.secrets.get(scope, key)`). It is a signed Logic App URL.
- Replace the historical P1–P99 limits with the plant's official limits when available.
- Write the recommendation log to a Delta table (the line is in the last cell).
