"""60 TPD melter - SFC recommender as an MLflow pyfunc model ("models from code").

Logged by 01_train_register_mlflow.ipynb:
    mlflow.pyfunc.log_model(python_model="sfc_pyfunc.py", artifacts={"model_json": ...}, ...)

The model itself is a small JSON of numbers (coefficients, targets, historical limits) written by the
training notebook. This file is the recommendation logic that turns live plant values into setpoints.
It is the same calculation as src/recommender.py (FinalRecommender.recommend) and the client inference
notebook, so the serving endpoint, the app and the notebooks give identical numbers.

Input (one row per request; dataframe_records on the serving endpoint):
    timestamp          str    "YYYY-MM-DD HH:MM" (IST) - the furnace-age term comes from the date
    ncv                float  latest valid NCV, kcal/SCM
    draw_t             float  today's draw, t/day (operator)
    cullet_pct         float  today's cullet %, (operator; only for the draw-adjusted yardstick)
    bb_kwh_last_hour   float  barrier boost in the last hour, kWh (= kWh/h)
    mb_kwh_last_hour   float  melter boost in the last hour, kWh (= kWh/h)
    mb3_now            float  MB3 bottom temperature, mean of the last hour, degC
    optical_temp       float  optional - optical crown temperature, degC (guard-rail only, not a model input)
    ng_now, air_now    float  optional - current NG / secondary air (workbook unit), shown as "change"

Output: one row per input row with the setpoints, the raw model values, the historical limits,
"at limit" markers, the expected SFC and a " | "-joined list of warnings.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import mlflow
from mlflow.pyfunc import PythonModel

REQUIRED = ["timestamp", "ncv", "draw_t", "cullet_pct", "bb_kwh_last_hour", "mb_kwh_last_hour", "mb3_now"]
OPTIONAL = ["optical_temp", "ng_now", "air_now"]
BANDS = [(45, 50), (50, 55), (55, 60), (60, 65)]


def _num(v) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return math.nan
    return v


def _held(raw: float, val: float) -> bool:
    return bool(not np.isclose(raw, val))


def recommend_one(m: dict, inp: dict) -> dict:
    """Setpoints for one set of plant values. `m` is the model JSON (FinalRecommender.to_dict schema)."""
    gas, air, boost, L = m["gas"], m["air"], m["boost"], {k: tuple(v) for k, v in m["limits"].items()}
    c = gas["coefficients"]
    x = {k: _num(inp.get(k)) for k in REQUIRED[1:] + OPTIONAL}
    ts = pd.Timestamp(inp["timestamp"])
    flags: list[str] = []

    missing = [k for k in REQUIRED[1:] if math.isnan(x[k])]
    if missing:
        raise ValueError(f"missing input values: {', '.join(missing)}")

    # input guard-rails (historical P1-P99); optical is a guard-rail only (finding F14)
    for key, lim_key, label in [("ncv", "ncv", "NCV"), ("draw_t", "draw_t", "draw"),
                                ("optical_temp", "opt_temp", "optical crown"), ("mb3_now", "mb3_temp", "MB3")]:
        if math.isnan(x[key]):
            continue
        lo, hi = L[lim_key]
        if not lo <= x[key] <= hi:
            flags.append(f"input {label} = {x[key]:.1f} is outside its historical range {lo:.1f}-{hi:.1f}")

    # 1. daily gas-heat target: OLS (draw, barrier boost, melter boost, age) + efficient-quarter shift
    kcal_kwh = gas["kcal_per_kwh"]
    age_m = (ts.normalize() - pd.Timestamp(gas["age_origin"])).days / gas["days_per_month"]
    bb_g = x["bb_kwh_last_hour"] * 24 * kcal_kwh / 1e6
    mb_g = x["mb_kwh_last_hour"] * 24 * kcal_kwh / 1e6
    target = (c["Intercept"] + c["draw_t"] * x["draw_t"] + c["bb_g"] * bb_g + c["mb_g"] * mb_g
              + c["age_m"] * age_m + gas["conformal_shift"])
    if not L["gas_day_gcal"][0] <= target <= L["gas_day_gcal"][1]:
        flags.append(f"daily gas target {target:.1f} Gcal is outside its historical range "
                     f"{L['gas_day_gcal'][0]:.1f}-{L['gas_day_gcal'][1]:.1f} (setpoints are still held inside limits)")

    # 2. NG = steady heat / latest NCV; 3. secondary air from heat; AFR = air / NG
    heat = target * 1e6 / gas["intervals_per_day"]
    ng_raw = heat / x["ncv"]
    ng = float(np.clip(ng_raw, *L["ng_scm"]))
    air_raw = air["air_per_mcal"] * ng * x["ncv"] / 1000
    afr_raw = air_raw / ng
    afr = float(np.clip(afr_raw, *L["afr"]))
    air_sp = float(np.clip(afr * ng, *L["sec_air"]))
    afr = air_sp / ng

    # 4. barrier boost: integral controller on MB3
    bb_raw = x["bb_kwh_last_hour"] + boost["ki"] * (boost["mb3_target"] - x["mb3_now"]) / boost["mb3_gain_degC_per_kwh_h"]
    bb = float(np.clip(bb_raw, *L["bb_kwh_h"]))
    if ng_raw > L["ng_scm"][1] and bb < x["bb_kwh_last_hour"]:
        bb = float(x["bb_kwh_last_hour"])
        flags.append("NG at its historical maximum: barrier boost not reduced this hour")

    # expected SFC if the day follows the gas target (boosts at the last-hour level, as in the target)
    energy_g = target + (x["bb_kwh_last_hour"] + x["mb_kwh_last_hour"]) * 24 * kcal_kwh / 1e6
    sfc_expected = energy_g * 1e6 / (x["draw_t"] * 1000)
    mv = m["mv"]
    a = mv["model_a"]
    sfc_base = math.nan
    if not math.isnan(x["cullet_pct"]):
        e_base = a["Intercept"] + a["draw_t"] * x["draw_t"] + a["cullet_pct"] * x["cullet_pct"]
        sfc_base = e_base * 1e6 / (x["draw_t"] * 1000)
    band = next((f"{lo}-{hi}" for lo, hi in BANDS if lo < x["draw_t"] <= hi or x["draw_t"] == lo == 45), "")  # as pd.cut
    band_base = mv["band_baseline_sfc"].get(band, math.nan)

    return {
        "model_version": m.get("model_version", m["trained_until"]),
        "trained_until": m["trained_until"],
        "timestamp": str(ts),
        "gas_target_gcal_day": target,
        "ng_setpoint": ng, "ng_raw": ng_raw, "ng_lo": L["ng_scm"][0], "ng_hi": L["ng_scm"][1], "ng_at_limit": _held(ng_raw, ng),
        "air_setpoint": air_sp, "air_raw": air_raw, "air_lo": L["sec_air"][0], "air_hi": L["sec_air"][1],
        "air_at_limit": _held(air_raw, air_sp),
        "afr_setpoint": afr, "afr_raw": afr_raw, "afr_lo": L["afr"][0], "afr_hi": L["afr"][1], "afr_at_limit": _held(afr_raw, afr),
        "bb_setpoint_kwh_h": bb, "bb_raw_kwh_h": bb_raw, "bb_lo": L["bb_kwh_h"][0], "bb_hi": L["bb_kwh_h"][1],
        "bb_at_limit": _held(bb_raw, bb), "bb_setpoint_kwh_15min": bb / 4,
        "mb3_target": boost["mb3_target"],
        "air_per_mcal_target": air["air_per_mcal"],
        "sfc_expected": sfc_expected,
        "sfc_baseline_at_draw": sfc_base,
        "draw_adjusted_pct": (sfc_expected / sfc_base - 1) * 100 if not math.isnan(sfc_base) else math.nan,
        "draw_band": band,
        "band_baseline_sfc": band_base,
        "band_target_sfc": band_base * 0.98,
        "client_target_sfc": mv["client_target_sfc"],
        "flags": " | ".join(flags),
        "n_flags": len(flags),
    }


class SFCRecommender(PythonModel):
    def load_context(self, context):
        self.m = json.loads(Path(context.artifacts["model_json"]).read_text())

    def predict(self, context, model_input: pd.DataFrame, params=None) -> pd.DataFrame:
        if isinstance(model_input, dict):
            model_input = pd.DataFrame([model_input])
        rows = model_input.to_dict("records")
        return pd.DataFrame([recommend_one(self.m, r) for r in rows])


mlflow.models.set_model(SFCRecommender())
