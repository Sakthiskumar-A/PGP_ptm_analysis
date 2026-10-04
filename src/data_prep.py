"""Load and clean the 60 TPD melter data.

Every notebook should get its data from here (or from the files it writes to
data/processed/), so cleaning rules live in one place. Rules are documented in
CLAUDE.md under "Cleaning rules".
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

# Raw column -> short name. Units are per 15-min interval (see CLAUDE.md).
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
    """Client baseline workbook, daily (1 Sep 2025 - 31 Jul 2026)."""
    b = pd.read_excel(BASELINE_FILE, sheet_name="Master Data- Energy & SFC Calc",
                      header=2, usecols="C:J")
    b.columns = ["date", "ng_scm", "ncv", "mb_kwh", "bb_kwh", "energy_kcal", "draw_kg", "sfc"]
    return b.dropna(subset=["date"]).set_index("date").add_prefix("base_")


def load_crown_tc_15min() -> pd.Series:
    """1-min crown thermocouple (TC MC3) averaged to 15-min, labelled by interval start."""
    c = pd.read_excel(CROWN_FILE)
    c.columns = ["ts", "crown_tc"]
    c = c.sort_values("ts").set_index("ts")["crown_tc"]
    lo, hi = VALID_RANGE["crown_tc"]
    c = c.where(c.between(lo, hi))
    return c.resample("15min").mean()


def load_ar_raw() -> pd.DataFrame:
    a = pd.read_excel(AR_FILE, sheet_name="result")
    return a.rename(columns=AR_COLUMNS)


def clean_15min(with_crown: bool = True) -> pd.DataFrame:
    """One clean row per 15-min timestamp. Adds *_bad flags for values set to NaN."""
    a = load_ar_raw()

    # 1. Duplicate timestamps differ only in opt_temp -> average it, keep the rest.
    num = [c for c in a.columns if c not in ("ts", "seed_spec")]
    q = a.groupby("ts")[num].mean()
    q["seed_spec"] = a.groupby("ts")["seed_spec"].first()

    # 2. Out-of-range values (incl. zeros from dead sensors) -> NaN, keep a flag.
    for col, (lo, hi) in VALID_RANGE.items():
        if col in q:
            bad = q[col].notna() & ~q[col].between(lo, hi)
            q[f"{col}_bad"] = bad
            q.loc[bad, col] = np.nan

    # 3. Draw: the record doubles the draw on two month-start days; take the
    #    baseline workbook value wherever it exists.
    base = load_baseline_daily()
    day = q.index.normalize()
    base_draw = base["base_draw_kg"].reindex(day).to_numpy()
    q["draw_kg"] = np.where(~np.isnan(base_draw), base_draw, q["draw_kg"])

    # 4. Recompute AFR from cleaned flows.
    q["afr"] = q["sec_air"] / q["ng_scm"]

    # 5. Energy per interval.
    q["gas_kcal"] = q["ng_scm"] * q["ncv"]
    q["elec_kcal"] = (q["bb_kwh"] + q["mb_kwh"]) * KCAL_PER_KWH

    if with_crown:
        q["crown_tc"] = load_crown_tc_15min().reindex(q.index)
        q["opt_minus_tc"] = q["opt_temp"] - q["crown_tc"]

    q.index.name = "ts"
    return q


def build_daily(q: pd.DataFrame) -> pd.DataFrame:
    """Daily table with SFC recomputed from 15-min data.

    Gas energy: sum of NG x NCV per interval. Where the NCV meter covers < 90%
    of the day, the baseline workbook's daily NCV is used (ncv_source='baseline').
    Short gaps in NG / boost (<= 1 h) are interpolated before summing.
    """
    base = load_baseline_daily()
    f = q.copy()
    for col in ["ng_scm", "bb_kwh", "mb_kwh"]:
        f[col] = f[col].interpolate(limit=4, limit_area="inside")
    f["date"] = f.index.normalize()
    g = f.groupby("date")

    d = pd.DataFrame({
        "n_rows": g.size(),
        "ng_scm": g["ng_scm"].sum(min_count=1),
        "ng_cov": g["ng_scm"].apply(lambda s: s.notna().mean()),
        "ncv_cov": g["ncv"].apply(lambda s: s.notna().mean()),
        "bb_kwh": g["bb_kwh"].sum(min_count=1),
        "mb_kwh": g["mb_kwh"].sum(min_count=1),
        "boost_cov": g["bb_kwh"].apply(lambda s: s.notna().mean()),
        "draw_kg": g["draw_kg"].first(),
        "cullet_pct": g["cullet_pct"].first(),
        "seed_count": g["seed_count"].first(),
        "opt_temp": g["opt_temp"].mean(),
        "mb3_temp": g["mb3_temp"].mean(),
        "afr": g["afr"].mean(),
    })
    if "crown_tc" in f:
        d["crown_tc"] = g["crown_tc"].mean()

    # Flow-weighted NCV on intervals where both exist.
    both = f.dropna(subset=["ng_scm", "ncv"])
    d["ncv_meter"] = (both["ng_scm"] * both["ncv"]).groupby(both["date"]).sum() / \
        both.groupby("date")["ng_scm"].sum()

    d = d.join(base)
    use_base = (d["ncv_cov"] < 0.9) & d["base_ncv"].notna()
    d["ncv_used"] = np.where(use_base, d["base_ncv"], d["ncv_meter"])
    d["ncv_source"] = np.where(use_base, "baseline", "meter")
    d["gas_kcal"] = d["ng_scm"] * d["ncv_used"]
    d["elec_kcal"] = (d["bb_kwh"] + d["mb_kwh"]) * KCAL_PER_KWH
    d["energy_kcal"] = d["gas_kcal"] + d["elec_kcal"]
    d["sfc"] = d["energy_kcal"] / d["draw_kg"]
    d["day_complete"] = (d["ng_cov"] >= 0.9) & (d["boost_cov"] >= 0.9) & d["draw_kg"].notna()
    d.index.name = "date"
    return d


def write_processed(q: pd.DataFrame, d: pd.DataFrame) -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    q.to_parquet(PROCESSED / "ar_15min_clean.parquet")
    d.to_parquet(PROCESSED / "daily_clean.parquet")
    d.to_csv(PROCESSED / "daily_clean.csv")
