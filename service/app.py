"""Reference API for the SFC recommenders (FastAPI). A starting point for the backend team.

Run from the repo root:
    pip install -r requirements.txt -r service/requirements.txt
    MODEL_PATH=models/recommender_latest.json uvicorn service.app:app --port 8000
Docs: http://localhost:8000/docs
"""
import os
import sys
from datetime import date as Date, datetime
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import data_prep as dp          # noqa: E402
import recommender as rc        # noqa: E402

MODEL_PATH = Path(os.environ.get("MODEL_PATH", ROOT / "models" / "recommender_latest.json"))
app = FastAPI(title="60 TPD melter SFC recommender", version="1.0")
STATE = {"model": rc.FinalRecommender.load(MODEL_PATH), "path": str(MODEL_PATH)}


# ----------------------------------------------------------------- request / response schemas
class RecommendInput(BaseModel):
    date: Date = Field(description="today's date (furnace age is computed from it)")
    ncv: float = Field(ge=8500, le=10500, description="latest VALID NCV, kcal/SCM (send the last valid value if the meter glitches)")
    draw_t: float = Field(gt=0, description="expected draw today, t/day")
    cullet_pct: float = Field(ge=0, le=100)
    optical_prev24h: float = Field(description="average optical crown temperature of the last 24 h, °C (guard-rail only)")
    bb_kwh_last_hour: float = Field(ge=0, description="barrier boost of the last hour, kWh")
    mb_kwh_last_hour: float = Field(ge=0, description="melter boost of the last hour, kWh")
    mb3_now: float = Field(description="MB3 bottom temperature now, °C")


class Setpoint(BaseModel):
    value: float
    model_value: float
    unit: str
    limit_low: float
    limit_high: float
    held_at_limit: bool


class RecommendOutput(BaseModel):
    model_trained_until: str
    gas_heat_target_gcal_day: Setpoint
    ng_setpoint: Setpoint
    secondary_air: Setpoint
    afr: Setpoint
    barrier_boost_kwh_h: Setpoint
    barrier_boost_kwh_15min: Setpoint
    flags: List[str]


class Row15(BaseModel):
    ts: datetime
    ncv: Optional[float] = None
    ng_scm: Optional[float] = None
    sec_air: Optional[float] = None
    bb_kwh: Optional[float] = None          # kWh per 15 min
    mb_kwh: Optional[float] = None          # kWh per 15 min
    mb3_temp: Optional[float] = None


class CompareInput(BaseModel):
    date: Date
    draw_t: float
    cullet_pct: float
    rows: List[Row15]


# ----------------------------------------------------------------- helpers
KEYS = ["gas_heat_target_gcal_day", "ng_setpoint", "secondary_air", "afr", "barrier_boost_kwh_h", "barrier_boost_kwh_15min"]


def clean_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Same rules as data_prep for live rows: out-of-range -> NaN, NCV spike filter, recompute AFR."""
    df = df.set_index("ts").sort_index()
    for col, (lo, hi) in dp.VALID_RANGE.items():
        if col in df:
            df.loc[~df[col].between(lo, hi), col] = np.nan
    med = df["ncv"].rolling(9, center=True, min_periods=3).median()
    df.loc[(df["ncv"] - med).abs() > dp.NCV_SPIKE, "ncv"] = np.nan
    df["afr"] = df["sec_air"] / df["ng_scm"]
    return df


def nan_to_none(records):
    return [{k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in r.items()} for r in records]


# ----------------------------------------------------------------- endpoints
@app.get("/health")
def health():
    return {"status": "ok", "model_file": STATE["path"], "trained_until": str(STATE["model"].trained_until.date())}


@app.get("/model")
def model_info():
    return STATE["model"].to_dict()


@app.post("/recommend", response_model=RecommendOutput)
def recommend(inp: RecommendInput):
    fr = STATE["model"]
    rec = fr.recommend(inp.model_dump())
    out = {}
    for key, (_, r) in zip(KEYS, rec.iterrows()):
        lo, hi = (float(x) for x in r["historical P1-P99"].split(" - "))
        out[key] = Setpoint(value=round(float(r["recommended (within limits)"]), 3), model_value=round(float(r["model value"]), 3),
                            unit=r["unit"], limit_low=lo, limit_high=hi, held_at_limit=bool(r["clipped?"]))
    return RecommendOutput(model_trained_until=str(fr.trained_until.date()), flags=rec.attrs["flags"], **out)


@app.post("/compare-day")
def compare_day(inp: CompareInput):
    if not inp.rows:
        raise HTTPException(422, "rows is empty")
    df = clean_rows(pd.DataFrame([r.model_dump() for r in inp.rows]))
    if df["ncv"].notna().sum() == 0:
        raise HTTPException(422, "no valid NCV in rows")
    res = rc.compare_day(STATE["model"], df, inp.draw_t, inp.cullet_pct, date=pd.Timestamp(inp.date))
    iv = res["intervals"].reset_index().round(4); iv["ts"] = iv["ts"].astype(str)
    hr = res["hours"].reset_index().round(3); hr["ts"] = hr["ts"].astype(str)
    return {"summary": res["summary"], "intervals": nan_to_none(iv.to_dict("records")), "hours": nan_to_none(hr.to_dict("records"))}


@app.post("/admin/reload")
def reload_model():
    STATE["model"] = rc.FinalRecommender.load(MODEL_PATH)
    return health()
