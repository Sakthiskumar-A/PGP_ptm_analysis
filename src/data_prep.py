"""Load and clean the 60 TPD melter data.

Every notebook gets its data from here (or from the files it writes to
data/processed/), so cleaning rules live in one place. Rules are documented in
CLAUDE.md under "Cleaning rules".

Primary values come only from the analytical record and the DCS crown file.
The client baseline workbook is loaded separately (`load_baseline_daily`) and is
used only for comparison and for checking our numbers, never to fill gaps.
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

AR_FILE = RAW / "Analytical_Record_Creation_EE_60TPD_updated-2.xlsx"
CROWN_FILE = RAW / "DCS_60_TPD_MelterCrown3.xlsx"
BASELINE_FILE = RAW / "SFC_60_TPD_Baseline_Calculation_Sep-25_to_Jul-26_updated.xlsx"

KCAL_PER_KWH = 860
CLIENT_BASELINE_SFC = 1576.3        # client's stated baseline (SFC Executive sheet)
CLIENT_TARGET_SFC = 1544.8          # 0.98 x baseline
BASELINE_START, BASELINE_END = "2025-09-01", "2026-07-31"

# Raw column -> short name. Flow and boost values are per 15-min interval and in
# the same unit the operator enters (plant, 2026-10-04): no conversion.
AR_COLUMNS = {
    "Timestamps": "ts",
    "BARRIER BOOSTER-52": "bb_kwh",
    "MELTER BOOSTER-51": "mb_kwh",
    "NCV Meter": "ncv",
    "Cullet %": "cullet_pct",
    "Melter Optical Temperature": "opt_temp",
    "dcs_60_SecondaryAirFlowvalueFTSAFPVDB205DD92": "sec_air",
    "dcs_60_MelterGasflowvalueFTMGFPVDB202DD92": "ng_scm",
    "dcs_60_ThermocoupleMelterBottom3TCMB3PVDB249DD572": "mb3_temp",
    "Air_Fuel_Ratio": "afr",
    "Seed Count": "seed_count",
    "Seed Count Specs": "seed_spec",
    "MB51_Quantity_KG (Draw)": "draw_kg",
    "SFC (kcal/kg)": "sfc_record",
}

# Plausible ranges; values outside are sensor faults or typing errors -> NaN.
VALID_RANGE = {
    "ncv": (7000, 11500),        # 0 = meter not working
    "opt_temp": (1550, 1600),    # manual entries like 2576, 15757, 1474
    "mb_kwh": (1, 200),          # 0 = no reading, 538 = spike
    "bb_kwh": (1, 250),
    "crown_tc": (1400, 1700),
}


def load_baseline_daily() -> pd.DataFrame:
    """Client baseline workbook, daily. For comparison only (columns prefixed base_)."""
    b = pd.read_excel(BASELINE_FILE, sheet_name="Master Data- Energy & SFC Calc",
                      header=2, usecols="C:J")
    b.columns = ["date", "ng_scm", "ncv", "mb_kwh", "bb_kwh", "energy_kcal", "draw_kg", "sfc"]
    return b.dropna(subset=["date"]).set_index("date").add_prefix("base_")


def load_crown_tc_1min() -> pd.Series:
    c = pd.read_excel(CROWN_FILE)
    c.columns = ["ts", "crown_tc"]
    c = c.sort_values("ts").set_index("ts")["crown_tc"]
    lo, hi = VALID_RANGE["crown_tc"]
    return c.where(c.between(lo, hi))


def load_ar_raw() -> pd.DataFrame:
    a = pd.read_excel(AR_FILE, sheet_name="result")
    return a.rename(columns=AR_COLUMNS)


def clean_15min(with_crown: bool = True) -> pd.DataFrame:
    """One clean row per 15-min timestamp, with *_bad / quality flags."""
    a = load_ar_raw()

    # 1. Duplicate timestamps differ only in opt_temp (date swap + 12-h clock in
    #    the manual optical log, nb02) -> average it, keep the rest, flag it.
    num = [c for c in a.columns if c not in ("ts", "seed_spec")]
    q = a.groupby("ts")[num].mean()
    q["seed_spec"] = a.groupby("ts")["seed_spec"].first()
    q["opt_n"] = a.groupby("ts")["opt_temp"].count()
    ampm = ampm_months(q)

    # 2. Out-of-range values (incl. zeros from dead sensors) -> NaN, keep a flag.
    for col, (lo, hi) in VALID_RANGE.items():
        if col in q:
            bad = q[col].notna() & ~q[col].between(lo, hi)
            q[f"{col}_bad"] = bad
            q.loc[bad, col] = np.nan

    # 3. Draw: the record doubles the SAP draw on two month-start days
    #    (2025-10-01, 2026-06-01). Detected as > 1.6x the median of the
    #    surrounding week and halved. (Halved values equal the SAP values in the
    #    client workbook exactly: checked in nb02, workbook not used here.)
    dd = q["draw_kg"].groupby(q.index.normalize()).first()
    ref = dd.rolling(7, center=True, min_periods=3).median()
    doubled = dd > 1.6 * ref
    fix = pd.Series(np.where(doubled, dd / 2, dd), index=dd.index)
    q["draw_fixed"] = doubled.reindex(q.index.normalize()).to_numpy()
    q["draw_kg"] = fix.reindex(q.index.normalize()).to_numpy()

    # 4. Optical reliability. Hour-level position is wrong in months logged on a
    #    12-h clock and on duplicated slots; see nb02.
    q["opt_dup"] = q["opt_n"] > 1
    q["opt_ampm_month"] = q.index.to_period("M").isin(ampm)
    q["opt_hour_ok"] = q["opt_temp"].notna() & ~q["opt_dup"] & ~q["opt_ampm_month"]

    # 5. Recompute AFR, energy per interval.
    q["afr"] = q["sec_air"] / q["ng_scm"]
    q["gas_kcal"] = q["ng_scm"] * q["ncv"]
    q["elec_kcal"] = (q["bb_kwh"] + q["mb_kwh"]) * KCAL_PER_KWH

    if with_crown:
        q["crown_tc"] = load_crown_tc_1min().resample("15min").mean().reindex(q.index)

    q.index.name = "ts"
    return q


def ampm_months(q: pd.DataFrame, max_pm_cov: float = 0.2) -> list:
    """Months where the optical log was stored on a 12-h clock: hours 13-23 are
    (almost) never filled while 01-12 carry duplicates (nb02 §3)."""
    pm = q[q.index.hour >= 13]
    cov = (pm["opt_n"] > 0).groupby(pm.index.to_period("M")).mean()
    am = q[(q.index.hour >= 1) & (q.index.hour <= 12)]
    dup = (am["opt_n"] > 1).groupby(am.index.to_period("M")).mean()
    return list(cov[(cov < max_pm_cov) & (dup.reindex(cov.index) > 0.05)].index)


def optical_day_ok(q: pd.DataFrame) -> pd.Series:
    """Daily optical mean is trustworthy if the day has >= 50% readings and is not
    touched by the DD/MM date swap (days 1-12 carrying duplicated readings)."""
    day = q.index.normalize()
    g = q.groupby(day)
    cov = g["opt_temp"].apply(lambda s: s.notna().mean())
    dup = g["opt_dup"].any()
    dom = pd.Series(cov.index.day, index=cov.index)
    return (cov >= 0.5) & ~((dom <= 12) & dup)


def build_daily(q: pd.DataFrame) -> pd.DataFrame:
    """Daily table, SFC recomputed from 15-min data only.

    Gas energy = sum of NG x NCV per interval (day flow-weighted NCV x day NG).
    Days with < 90% NCV coverage get ncv_ok=False and are left out of analysis.
    Short gaps in NG / boost (<= 1 h) are interpolated before summing.
    """
    f = q.copy()
    for col in ["ng_scm", "bb_kwh", "mb_kwh", "sec_air"]:
        f[col] = f[col].interpolate(limit=4, limit_area="inside")
    f["date"] = f.index.normalize()
    g = f.groupby("date")

    d = pd.DataFrame({
        "ng_scm": g["ng_scm"].sum(min_count=1),
        "sec_air": g["sec_air"].sum(min_count=1),
        "ng_cov": g["ng_scm"].apply(lambda s: s.notna().mean()),
        "ncv_cov": g["ncv"].apply(lambda s: s.notna().mean()),
        "bb_kwh": g["bb_kwh"].sum(min_count=1),
        "mb_kwh": g["mb_kwh"].sum(min_count=1),
        "boost_cov": g["bb_kwh"].apply(lambda s: s.notna().mean()),
        "draw_kg": g["draw_kg"].first(),
        "draw_fixed": g["draw_fixed"].first(),
        "cullet_pct": g["cullet_pct"].first(),
        "seed_count": g["seed_count"].first(),
        "opt_temp": g["opt_temp"].mean(),
        "mb3_temp": g["mb3_temp"].mean(),
    })
    if "crown_tc" in f:
        d["crown_tc"] = g["crown_tc"].mean()
    d["opt_day_ok"] = optical_day_ok(q).reindex(d.index)

    both = f.dropna(subset=["ng_scm", "ncv"])
    d["ncv"] = (both["ng_scm"] * both["ncv"]).groupby(both["date"]).sum() / \
        both.groupby("date")["ng_scm"].sum()
    d["gas_kcal"] = d["ng_scm"] * d["ncv"]
    d["elec_kcal"] = (d["bb_kwh"] + d["mb_kwh"]) * KCAL_PER_KWH
    d["energy_kcal"] = d["gas_kcal"] + d["elec_kcal"]
    d["sfc"] = d["energy_kcal"] / d["draw_kg"]
    d["afr"] = d["sec_air"] / d["ng_scm"]
    d["air_per_mcal"] = d["sec_air"] / (d["gas_kcal"] / 1000)
    d["draw_t"] = d["draw_kg"] / 1000
    d["elec_share"] = d["elec_kcal"] / d["energy_kcal"]

    d["ncv_ok"] = d["ncv_cov"] >= 0.9                      # user decision 2026-10-04
    d["day_complete"] = (d["ng_cov"] >= 0.9) & (d["boost_cov"] >= 0.9) & d["draw_kg"].notna()
    d["usable"] = d["ncv_ok"] & d["day_complete"]
    d["in_baseline"] = (d.index >= BASELINE_START) & (d.index <= BASELINE_END)
    d.index.name = "date"
    return d


def build_hourly(q: pd.DataFrame) -> pd.DataFrame:
    """Hourly table for modelling (1 h = 3 reversal cycles, removes 15-min aliasing)."""
    f = q.copy()
    r = f.resample("h")
    h = pd.DataFrame({
        "ng_scm": r["ng_scm"].sum(min_count=4),
        "sec_air": r["sec_air"].sum(min_count=4),
        "gas_kcal": r["gas_kcal"].sum(min_count=4),
        "ncv": r["ncv"].mean(),
        "bb_kwh": r["bb_kwh"].sum(min_count=4),
        "mb_kwh": r["mb_kwh"].sum(min_count=4),
        "mb3_temp": r["mb3_temp"].mean(),
        "opt_temp": r["opt_temp"].mean(),
        "draw_kg": r["draw_kg"].first(),
        "cullet_pct": r["cullet_pct"].first(),
        "seed_count": r["seed_count"].first(),
    })
    if "crown_tc" in f:
        h["crown_tc"] = r["crown_tc"].mean()
    h["afr"] = h["sec_air"] / h["ng_scm"]
    h["air_per_mcal"] = h["sec_air"] / (h["gas_kcal"] / 1000)
    h["draw_t"] = h["draw_kg"] / 1000
    h.index.name = "ts"
    return h


def write_processed(q: pd.DataFrame, d: pd.DataFrame, h: pd.DataFrame | None = None) -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    q.to_parquet(PROCESSED / "ar_15min_clean.parquet")
    d.to_parquet(PROCESSED / "daily_clean.parquet")
    d.to_csv(PROCESSED / "daily_clean.csv")
    if h is not None:
        h.to_parquet(PROCESSED / "hourly_clean.parquet")
