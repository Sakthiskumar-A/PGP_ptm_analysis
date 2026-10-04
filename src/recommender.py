"""Recommendation logic for the 60 TPD melter (used by notebooks 04 and 05).

Model 1 (gas, every 15 min)  -- chosen in notebooks/training/T1, T2:
    1. Daily gas-heat target: OLS on ALL past usable days
       gas_Gcal ~ draw_t + barrier_Gcal + melter_Gcal + age_m + optical(previous day)
       plus a conformal shift = 25th percentile of the last 45 days' residuals
       (target = what the efficient quarter of recent comparable days needed).
       Optical history is gap-filled from the crown thermocouple + rolling offset.
    2. Spread evenly over the day (steady heat). No separate optical trim: the
       crown effect is inside the model.
    3. NG setpoint = heat per 15 min / latest NCV  -> exact NCV compensation.
       Units: same as the workbook column the operator enters (no conversion).
    4. Secondary air = air-per-Mcal target x heat / 1000, AFR = air / NG.
       Air-per-Mcal target = P25 of the last 45 days, floored at historical P5.

Model 2 (barrier boost, every hour):
    Integral controller on MB3: bb(t) = bb(t-1) + ki * (MB3_target - MB3_now) / gain,
    gain = steady-state MB3 response to boost estimated from history (nb05),
    clipped to the historical boost range. Gas (Model 1) reads the actual boost
    from the DB, so it automatically follows the boost changes.
"""
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

KCAL_PER_KWH = 860


# ----------------------------------------------------------------- limits
def historical_limits(q15: pd.DataFrame, h: pd.DataFrame, lo=0.01, hi=0.99) -> pd.DataFrame:
    """Plant asked to use historical limits for now: P1-P99 of normal operation."""
    rows = {
        "ng_scm (per 15 min)": q15["ng_scm"],
        "afr": q15["afr"],
        "air_per_mcal": h["air_per_mcal"],
        "bb_kwh (per hour)": h["bb_kwh"],
        "opt_temp (°C)": q15["opt_temp"],
        "mb3_temp (°C)": q15["mb3_temp"],
        "crown_tc (°C)": q15["crown_tc"],
    }
    return pd.DataFrame({k: v.quantile([lo, 0.5, hi]).to_numpy() for k, v in rows.items()},
                        index=[f"P{int(lo*100)}", "median", f"P{int(hi*100)}"]).T


# ----------------------------------------------------------------- Model 1
GAS_FORMULA_QR = "gas_g ~ draw_t + bb_g + mb_g"                       # first version (rolling QR)
GAS_FORMULA = "gas_g ~ draw_t + bb_g + mb_g + age_m + opt_f_prev"     # chosen in T1
GAS_FEATURES = ["draw_t", "bb_g", "mb_g", "age_m", "opt_f_prev"]
AGE_ORIGIN = pd.Timestamp("2025-09-01")


def add_gcal_columns(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["gas_g"] = d["gas_kcal"] / 1e6
    d["bb_g"] = d["bb_kwh"] * KCAL_PER_KWH / 1e6
    d["mb_g"] = d["mb_kwh"] * KCAL_PER_KWH / 1e6
    return d


def prepare_gas_features(d: pd.DataFrame) -> pd.DataFrame:
    """Gcal columns, furnace age, and optical gap-filled from the thermocouple.

    opt_f = optical daily mean on trustworthy days (nb02); other days = crown TC +
    rolling 30-day median offset (optical - TC, F4). opt_f_prev = previous day
    (live: mean of the last 24 h of typed optical readings).
    """
    d = add_gcal_columns(d)
    d["age_m"] = (d.index - AGE_ORIGIN).days / 30.44
    opt = d["opt_temp"].where(d["opt_day_ok"].astype(bool))
    off = (opt - d["crown_tc"]).rolling(30, min_periods=5).median().ffill().bfill()
    d["opt_f"] = opt.fillna(d["crown_tc"] + off)
    d["opt_f_prev"] = d["opt_f"].shift(1)
    return d


def daily_gas_target(d_usable: pd.DataFrame, day, overrides: dict | None = None,
                     tau: float = 0.25, window: int = 45, method: str = "ols_conformal") -> float:
    """Gas heat target (Gcal/day) for `day`, using only days before it.

    method="ols_conformal" (chosen): OLS on all past days + conformal shift from
    the last `window` days. method="qr_rolling": first version, quantile
    regression on the last `window` days (kept for comparison).
    `overrides` replaces inputs of the day (e.g. {"bb_g": recommended boost}).
    """
    d = prepare_gas_features(d_usable)
    x = d.loc[[day]].copy()
    for k, v in (overrides or {}).items():
        x[k] = v
    hist = d[d.index < day]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")          # IterationLimitWarning: solution is still usable
        if method == "qr_rolling":
            tr = hist[hist.index >= pd.Timestamp(day) - pd.Timedelta(days=window)]
            m = smf.quantreg(GAS_FORMULA_QR, tr).fit(q=tau, max_iter=5000)
            return float(m.predict(x).iloc[0])
        hist = hist.dropna(subset=GAS_FEATURES + ["gas_g"])
        rec = hist[hist.index >= pd.Timestamp(day) - pd.Timedelta(days=window)]
        m = smf.ols(GAS_FORMULA, hist).fit()
        shift = float(np.quantile(rec["gas_g"] - m.predict(rec), tau))
        return float(m.predict(x).iloc[0]) + shift


def walk_forward_gas_targets(d_usable: pd.DataFrame, days, tau=0.25, window=45,
                             method: str = "ols_conformal") -> pd.Series:
    return pd.Series({day: daily_gas_target(d_usable, day, None, tau, window, method) for day in days},
                     name=f"gas_target_{method}")


def air_target(d_usable: pd.DataFrame, day, window: int = 45, q: float = 0.25, floor_q: float = 0.05) -> float:
    """Air per Mcal target (T2): P25 of the last `window` days, floored at the
    historical P5 of all earlier days (never below proven operation; no O2 analyser)."""
    hist = d_usable.loc[d_usable.index < day, "air_per_mcal"].dropna()
    recent = hist[hist.index >= pd.Timestamp(day) - pd.Timedelta(days=window)]
    return float(max(recent.quantile(q), hist.quantile(floor_q)))


@dataclass
class GasRecommendation:
    ng_setpoint: float      # workbook / operator units, per 15 min
    afr: float
    sec_air: float          # same basis as ng_setpoint
    heat_kcal: float        # gas heat this 15-min interval


def recommend_gas(day_target_gcal: float, ncv_now: float, air_per_mcal: float,
                  limits: dict | None = None, opt_now: float | None = None,
                  opt_target: float = 1574.5, trim_per_degC: float = 0.0) -> GasRecommendation:
    """One 15-min gas recommendation (to be shown by minute 15 of the reversal cycle).

    Secondary air is recommended first (air_per_mcal x heat), then AFR = air / NG.
    The optical trim is off by default: the chosen gas model already contains
    the optical crown temperature (T1).
    """
    heat = day_target_gcal * 1e6 / 96
    if opt_now is not None and not np.isnan(opt_now) and trim_per_degC:
        heat *= 1 + trim_per_degC * (opt_target - opt_now)
    ng = heat / ncv_now
    if limits:
        ng = float(np.clip(ng, *limits.get("ng_scm", (-np.inf, np.inf))))
    sec_air = air_per_mcal * ng * ncv_now / 1000
    afr = sec_air / ng
    if limits and "afr" in limits:
        afr = float(np.clip(afr, *limits["afr"]))
        sec_air = afr * ng
    return GasRecommendation(ng, afr, sec_air, ng * ncv_now)


# ----------------------------------------------------------------- Model 2
def mb3_impulse_response(h: pd.DataFrame, lags=8) -> pd.Series:
    """Distributed-lag fit: dMB3(t) ~ sum_k c_k * dBB(t-k) + gas terms.
    Returns cumulative MB3 response (°C) to a sustained +1 kWh/h barrier boost step."""
    x = h[["mb3_temp", "bb_kwh", "gas_kcal"]].dropna().copy()
    x = x.asfreq("h")
    df = pd.DataFrame({"dmb3": x["mb3_temp"].diff()})
    cols = []
    for k in range(lags + 1):
        df[f"dbb{k}"] = x["bb_kwh"].diff().shift(k)
        df[f"dgas{k}"] = (x["gas_kcal"] / 1e6).diff().shift(k)
        cols += [f"dbb{k}", f"dgas{k}"]
    m = smf.ols("dmb3 ~ " + " + ".join(cols), df.dropna()).fit()
    c = pd.Series([m.params[f"dbb{k}"] for k in range(lags + 1)], name="step_response")
    return c.cumsum()


def recommend_boost(bb_ref_kwh_h: float, mb3_now: float, mb3_target: float,
                    gain_degC_per_kwh_h: float, damping: float = 0.5,
                    bb_limits: tuple = (-np.inf, np.inf)) -> float:
    """Hourly barrier boost (kWh per hour). Moves part (`damping`) of the way to the
    boost that would bring MB3 to target, using the steady-state gain."""
    corr = (mb3_target - mb3_now) / gain_degC_per_kwh_h * damping
    return float(np.clip(bb_ref_kwh_h + corr, *bb_limits))


def boost_step_response(h: pd.DataFrame, lags=12) -> pd.Series:
    """Physical part of the MB3 step response: early negative values come from
    operator feedback (boost raised when MB3 already falls), so clip at 0 and
    force it to be non-decreasing."""
    return mb3_impulse_response(h, lags).clip(lower=0).cummax()


def simulate_boost_controller(hh: pd.DataFrame, step: pd.Series, mb3_target: float,
                              ki: float = 0.1, bb_limits=(0, np.inf)) -> pd.DataFrame:
    """Closed-loop replay, hour by hour.

    Each hour: MB3_sim = MB3_actual + effect of all past (recommended - actual)
    boost differences (linear superposition with the step response); then
    bb_rec(t) = bb_rec(t-1) + ki * (target - MB3_sim) / steady_gain  (integral
    controller), clipped to limits. Returns hh with bb_rec and mb3_sim.
    """
    g = step.diff().fillna(step.iloc[0]).to_numpy()
    gain = float(step.iloc[-1])
    out_b, out_m, dev_hist = [], [], []
    prev = None
    for bb_act, m_act in zip(hh["bb_kwh"].to_numpy(), hh["mb3_temp"].to_numpy()):
        if np.isnan(bb_act) or np.isnan(m_act):
            out_b.append(np.nan); out_m.append(np.nan); dev_hist.append(0.0)
            continue
        n = min(len(g), len(dev_hist))
        m_sim = m_act + sum(g[k] * dev_hist[-1 - k] for k in range(n))
        prev = bb_act if prev is None else prev
        b = float(np.clip(prev + ki * (mb3_target - m_sim) / gain, *bb_limits))
        prev = b
        out_b.append(b); out_m.append(m_sim); dev_hist.append(b - bb_act)
    res = hh.copy()
    res["bb_rec"] = out_b
    res["mb3_sim"] = out_m
    return res


def simulate_policy(hh: pd.DataFrame, step: pd.Series, policy) -> pd.DataFrame:
    """Closed-loop replay for any boost policy.

    policy(prev_bb, mb3_sim, row) -> recommended boost for this hour (kWh/h).
    MB3_sim = actual MB3 + superposed effect of all past (recommended - actual) boost.
    """
    g = step.diff().fillna(step.iloc[0]).to_numpy()
    out_b, out_m, dev_hist = [], [], []
    prev = None
    for ts, row in hh.iterrows():
        bb_act, m_act = row["bb_kwh"], row["mb3_temp"]
        if np.isnan(bb_act) or np.isnan(m_act):
            out_b.append(np.nan); out_m.append(np.nan); dev_hist.append(0.0)
            continue
        n = min(len(g), len(dev_hist))
        m_sim = m_act + sum(g[k] * dev_hist[-1 - k] for k in range(n))
        prev = bb_act if prev is None else prev
        b = float(policy(prev, m_sim, row))
        prev = b
        out_b.append(b); out_m.append(m_sim); dev_hist.append(b - bb_act)
    res = hh.copy()
    res["bb_rec"] = out_b
    res["mb3_sim"] = out_m
    return res
