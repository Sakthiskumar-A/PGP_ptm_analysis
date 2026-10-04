"""Recommendation logic for the 60 TPD melter (used by notebooks 04 and 05).

Model 1 (gas, every 15 min):
    1. Daily gas-heat target from a walk-forward quantile regression on the last
       `window` usable days: gas_Gcal ~ draw_t + barrier_Gcal + melter_Gcal,
       at quantile `tau` (the "efficient frontier" of recent operation).
    2. Spread evenly over the day (steady heat), plus a small optical trim.
    3. NG setpoint = heat per 15 min / latest NCV  -> exact NCV compensation.
       Units: same as the workbook column the operator enters (no conversion).
    4. AFR = target air-per-Mcal x NCV / 1000.

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
GAS_FORMULA = "gas_g ~ draw_t + bb_g + mb_g"


def add_gcal_columns(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["gas_g"] = d["gas_kcal"] / 1e6
    d["bb_g"] = d["bb_kwh"] * KCAL_PER_KWH / 1e6
    d["mb_g"] = d["mb_kwh"] * KCAL_PER_KWH / 1e6
    return d


def daily_gas_target(d_usable: pd.DataFrame, day, inputs: dict, tau=0.25, window=45) -> float:
    """Gas heat target (Gcal/day) for `day`, fitted only on the `window` days before it."""
    d = add_gcal_columns(d_usable)
    tr = d[(d.index < day) & (d.index >= pd.Timestamp(day) - pd.Timedelta(days=window))]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")          # IterationLimitWarning: solution is still usable
        m = smf.quantreg(GAS_FORMULA, tr).fit(q=tau, max_iter=5000)
    x = pd.DataFrame([inputs])
    return float(m.predict(x).iloc[0])


def walk_forward_gas_targets(d_usable: pd.DataFrame, days, tau=0.25, window=45) -> pd.Series:
    d = add_gcal_columns(d_usable)
    out = {}
    for day in days:
        row = d.loc[day]
        out[day] = daily_gas_target(d_usable, day, {"draw_t": row.draw_t, "bb_g": row.bb_g,
                                                    "mb_g": row.mb_g}, tau, window)
    return pd.Series(out, name=f"gas_target_tau{tau}")


@dataclass
class GasRecommendation:
    ng_setpoint: float      # workbook / operator units, per 15 min
    afr: float
    sec_air: float          # same basis as ng_setpoint
    heat_kcal: float        # gas heat this 15-min interval


def recommend_gas(day_target_gcal: float, ncv_now: float, opt_now: float | None = None,
                  opt_target: float = 1574.5, trim_per_degC: float = 0.0,
                  air_per_mcal: float = 1.26, limits: dict | None = None) -> GasRecommendation:
    """One 15-min gas recommendation (to be shown by minute 15 of the reversal cycle)."""
    heat = day_target_gcal * 1e6 / 96
    if opt_now is not None and not np.isnan(opt_now) and trim_per_degC:
        heat *= 1 + trim_per_degC * (opt_target - opt_now)
    ng = heat / ncv_now
    afr = air_per_mcal * ncv_now / 1000
    if limits:
        ng = float(np.clip(ng, *limits.get("ng_scm", (-np.inf, np.inf))))
        afr = float(np.clip(afr, *limits.get("afr", (-np.inf, np.inf))))
    return GasRecommendation(ng, afr, ng * afr, ng * ncv_now)


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
