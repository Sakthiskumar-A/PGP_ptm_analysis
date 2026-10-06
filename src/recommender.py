"""Recommendation logic for the 60 TPD melter (used by notebooks 04 and 05).

Model 1 (gas, every 15 min)  -- chosen in notebooks/training/T1, T2:
    1. Daily gas-heat target: OLS on ALL past usable days
       gas_Gcal ~ draw_t + barrier_Gcal + melter_Gcal + age_m
       plus a conformal shift = 25th percentile of the last 45 days' residuals
       (target = what the efficient quarter of recent comparable days needed).
       Optical (previous day) was dropped with the corrected data: no gain in T1,
       and it mis-calibrated the Sep 2026 validation (nb04 §8). Optical stays a
       live input, checked against its historical band (guard-rail), not a model input.
    2. Spread evenly over the day (steady heat). No optical trim.
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
    }
    if "crown_tc" in q15:                     # optional: not a model input
        rows["crown_tc (°C)"] = q15["crown_tc"]
    return pd.DataFrame({k: v.quantile([lo, 0.5, hi]).to_numpy() for k, v in rows.items()},
                        index=[f"P{int(lo*100)}", "median", f"P{int(hi*100)}"]).T


# ----------------------------------------------------------------- Model 1
GAS_FORMULA_QR = "gas_g ~ draw_t + bb_g + mb_g"                       # first version (rolling QR)
GAS_FORMULA = "gas_g ~ draw_t + bb_g + mb_g + age_m"                  # chosen (T1 + Sep 2026 check)
GAS_FEATURES = ["draw_t", "bb_g", "mb_g", "age_m"]
GAS_FORMULA_OPT = GAS_FORMULA + " + opt_f_prev"                         # previous choice, kept for comparison
GAS_FEATURES_OPT = GAS_FEATURES + ["opt_f_prev"]
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
    if "crown_tc" in d:                                          # crown TC is optional (not a model input)
        off = (opt - d["crown_tc"]).rolling(30, min_periods=5).median().ffill().bfill()
        opt = opt.fillna(d["crown_tc"] + off)
    d["opt_f"] = opt
    d["opt_f_prev"] = d["opt_f"].shift(1)
    return d


def daily_gas_target(d_usable: pd.DataFrame, day, overrides: dict | None = None,
                     tau: float = 0.25, window: int = 45, method: str = "ols_conformal") -> float:
    """Gas heat target (Gcal/day) for `day`, using only days before it.

    method="ols_conformal" (chosen): OLS on all past days + conformal shift from
    the last `window` days. method="ols_conformal_opt": the same with previous-day
    optical (the earlier choice). method="qr_rolling": first version, quantile
    regression on the last `window` days. The last two are kept for comparison.
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
        formula, feats = (GAS_FORMULA_OPT, GAS_FEATURES_OPT) if method == "ols_conformal_opt" else (GAS_FORMULA, GAS_FEATURES)
        hist = hist.dropna(subset=feats + ["gas_g"])
        rec = hist[hist.index >= pd.Timestamp(day) - pd.Timedelta(days=window)]
        m = smf.ols(formula, hist).fit()
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


# ----------------------------------------------------------------- final recommender (live use)
class FinalRecommender:
    """Both recommenders trained on all usable history, with historical limits.

    fit(d, q, h)  -> trains the gas target model, air target, MB3 gain and limits.
    recommend(inputs) -> NG, secondary air, AFR (per 15 min) and barrier boost (next hour),
                         every value checked against the historical P1-P99 limits.
    save(path) / FinalRecommender.load(path) -> portable JSON model file (only numbers; no
                         statsmodels object is needed to serve recommendations).
    """
    MODEL_SCHEMA = 1
    ki = 0.1

    def fit(self, d: pd.DataFrame, q: pd.DataFrame, h: pd.DataFrame, window: int = 45, tau: float = 0.25):
        u = prepare_gas_features(d[d["usable"]]).dropna(subset=GAS_FEATURES + ["gas_g"])
        self.trained_until = u.index.max()
        self.gas_model = smf.ols(GAS_FORMULA, u).fit()
        self.gas_params = {k: float(v) for k, v in self.gas_model.params.items()}
        self.n_days = int(self.gas_model.nobs)
        rec = u[u.index > self.trained_until - pd.Timedelta(days=window)]
        self.conformal_shift = float(np.quantile(rec["gas_g"] - self.gas_model.predict(rec), tau))
        apm = d.loc[d["usable"], "air_per_mcal"].dropna()
        self.air_per_mcal = float(max(apm[apm.index > self.trained_until - pd.Timedelta(days=window)].quantile(0.25),
                                      apm.quantile(0.05)))
        self.mb3_gain = float(boost_step_response(h, 12).iloc[-1])          # °C per kWh/h
        self.mb3_target = float(h["mb3_temp"].median())
        lim = historical_limits(q, h)
        self.limits = {
            "ng_scm": tuple(lim.loc["ng_scm (per 15 min)", ["P1", "P99"]]),
            "afr": tuple(lim.loc["afr", ["P1", "P99"]]),
            "bb_kwh_h": tuple(lim.loc["bb_kwh (per hour)", ["P1", "P99"]]),
            "mb3_temp": tuple(h["mb3_temp"].quantile([0.01, 0.99])),
            "opt_temp": tuple(lim.loc["opt_temp (°C)", ["P1", "P99"]]),
            "ncv": (8500.0, 10500.0),
            "draw_t": tuple(u["draw_t"].quantile([0.01, 0.99])),
            "sec_air": tuple(q["sec_air"].quantile([0.01, 0.99])),
            "gas_day_gcal": tuple(u["gas_g"].quantile([0.01, 0.99])),
        }
        # M&V yardsticks: fitted on the fixed baseline period only, so they do not move on retraining
        base = u[u["in_baseline"]].assign(E_g=lambda x: x["energy_kcal"] / 1e6)
        self.mv_model_a = {k: float(v) for k, v in smf.ols("E_g ~ draw_t + cullet_pct", base).fit().params.items()}
        bands = pd.cut(base["draw_t"], [45, 50, 55, 60, 65], labels=["45-50", "50-55", "55-60", "60-65"], include_lowest=True)
        self.band_baseline = {str(k): float(v) for k, v in base.groupby(bands, observed=True)["sfc"].mean().items()}
        return self

    # ---- portable model file
    def to_dict(self) -> dict:
        return {
            "schema": self.MODEL_SCHEMA,
            "created_at": pd.Timestamp.now().isoformat(timespec="seconds"),
            "trained_until": str(pd.Timestamp(self.trained_until).date()),
            "n_training_days": self.n_days,
            "gas": {"formula": GAS_FORMULA, "coefficients": self.gas_params, "conformal_shift": self.conformal_shift,
                    "age_origin": str(AGE_ORIGIN.date()), "days_per_month": 30.44, "intervals_per_day": 96,
                    "kcal_per_kwh": KCAL_PER_KWH},
            "air": {"air_per_mcal": self.air_per_mcal},
            "boost": {"mb3_target": self.mb3_target, "mb3_gain_degC_per_kwh_h": self.mb3_gain, "ki": self.ki},
            "limits": {k: [float(v[0]), float(v[1])] for k, v in self.limits.items()},
            "mv": {"model_a": self.mv_model_a, "band_baseline_sfc": self.band_baseline,
                   "client_baseline_sfc": 1576.3, "client_target_sfc": 1544.8},
        }

    @classmethod
    def from_dict(cls, m: dict) -> "FinalRecommender":
        fr = cls()
        fr.trained_until = pd.Timestamp(m["trained_until"])
        fr.n_days = m["n_training_days"]
        fr.gas_model = None
        fr.gas_params = dict(m["gas"]["coefficients"])
        fr.conformal_shift = float(m["gas"]["conformal_shift"])
        fr.air_per_mcal = float(m["air"]["air_per_mcal"])
        fr.mb3_target = float(m["boost"]["mb3_target"])
        fr.mb3_gain = float(m["boost"]["mb3_gain_degC_per_kwh_h"])
        fr.ki = float(m["boost"].get("ki", 0.1))
        fr.limits = {k: tuple(v) for k, v in m["limits"].items()}
        fr.mv_model_a = dict(m["mv"]["model_a"])
        fr.band_baseline = dict(m["mv"]["band_baseline_sfc"])
        return fr

    def save(self, path) -> None:
        import json
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path) -> "FinalRecommender":
        import json
        with open(path) as f:
            return cls.from_dict(json.load(f))

    def gas_target(self, date, draw_t, bb_kwh_day, mb_kwh_day) -> float:
        """Daily gas-heat target (Gcal/day). Furnace age is computed from the date, so it advances by itself."""
        x = {"Intercept": 1.0, "draw_t": draw_t, "bb_g": bb_kwh_day * KCAL_PER_KWH / 1e6,
             "mb_g": mb_kwh_day * KCAL_PER_KWH / 1e6, "age_m": (pd.Timestamp(date) - AGE_ORIGIN).days / 30.44}
        return float(sum(self.gas_params[k] * x[k] for k in self.gas_params)) + self.conformal_shift

    def recommend(self, inputs: dict, mb3_target: float | None = None, ki: float | None = None) -> pd.DataFrame:
        """inputs: date, ncv, draw_t, cullet_pct, optical_prev24h, bb_kwh_last_hour,
        mb_kwh_last_hour, mb3_now. Boost/melter last hour are kWh per hour (read from DB).
        optical_prev24h is a guard-rail: flagged when outside its historical band, not a model input."""
        L = self.limits
        flags = []
        for key, lim_key in [("ncv", "ncv"), ("draw_t", "draw_t"), ("optical_prev24h", "opt_temp"), ("mb3_now", "mb3_temp")]:
            lo, hi = L[lim_key]
            if not (lo <= inputs[key] <= hi):
                flags.append(f"input {key}={inputs[key]} outside history [{lo:.0f}, {hi:.0f}]")
        target = self.gas_target(inputs["date"], inputs["draw_t"], inputs["bb_kwh_last_hour"] * 24,
                                 inputs["mb_kwh_last_hour"] * 24)
        # Daily gas heat is an outcome, not a setpoint: not clipped, only flagged.
        target_c = target
        if not (L["gas_day_gcal"][0] <= target <= L["gas_day_gcal"][1]):
            flags.append(f"daily gas target {target:.1f} Gcal outside the historical daily range "
                         f"[{L['gas_day_gcal'][0]:.1f}, {L['gas_day_gcal'][1]:.1f}] (setpoints below are still inside limits)")
        heat = target_c * 1e6 / 96
        ng_raw = heat / inputs["ncv"]
        ng = float(np.clip(ng_raw, *L["ng_scm"]))
        air_raw = self.air_per_mcal * ng * inputs["ncv"] / 1000
        afr = float(np.clip(air_raw / ng, *L["afr"]))
        air = float(np.clip(afr * ng, *L["sec_air"]))      # secondary air also within its own history
        afr = air / ng
        tgt = self.mb3_target if mb3_target is None else mb3_target
        ki = self.ki if ki is None else ki
        bb_raw = inputs["bb_kwh_last_hour"] + ki * (tgt - inputs["mb3_now"]) / self.mb3_gain
        bb = float(np.clip(bb_raw, *L["bb_kwh_h"]))
        if ng_raw > L["ng_scm"][1] and bb < inputs["bb_kwh_last_hour"]:
            # gas is already at its historical maximum: don't take heat away from the bottom too
            bb = float(inputs["bb_kwh_last_hour"])
            flags.append("NG at historical maximum -> barrier boost not reduced this hour")
        rows = [
            ("Daily gas heat target (not a setpoint; flagged only)", target, target_c, "Gcal/day", L["gas_day_gcal"]),
            ("NG setpoint (per 15 min, workbook unit)", ng_raw, ng, "SCM/15 min", L["ng_scm"]),
            ("Secondary air (per 15 min, workbook unit)", air_raw, air, "SCM/15 min", L["sec_air"]),
            ("Air-fuel ratio", air_raw / ng, afr, "-", L["afr"]),
            ("Barrier boost, next hour", bb_raw, bb, "kWh/h", L["bb_kwh_h"]),
            ("Barrier boost, next hour (per 15 min)", bb_raw / 4, bb / 4, "kWh/15 min", tuple(v / 4 for v in L["bb_kwh_h"])),
        ]
        rows = [(i, mv, rv, un, f"{lim[0]:.2f} - {lim[1]:.2f}") for i, mv, rv, un, lim in rows]
        out = pd.DataFrame(rows, columns=["item", "model value", "recommended (within limits)", "unit", "historical P1-P99"])
        out["clipped?"] = ~np.isclose(out["model value"], out["recommended (within limits)"])
        out.attrs["flags"] = flags
        return out


# ----------------------------------------------------------------- back-test: history replay + one set of inputs
def walk_forward_history(d: pd.DataFrame, h: pd.DataFrame, start: str = "2025-12-01", ki: float = 0.1) -> pd.DataFrame:
    """Replay the full recommender on every usable day from `start`, walk-forward.

    Each day: gas target from earlier days only (with that day's recommended boost), barrier boost from
    the MB3 controller replayed hour by hour from `start` (target = historical median MB3, limits P1-P99),
    actual melter boost, and the air trim (energy effect of moving air/Mcal to its rolling P25 target).
    Returns one row per day with actual and recommended energy, SFC and draw-adjusted % (Model A).
    Takes a minute or two; T4 caches the result in data/processed/backtest_daily.parquet.
    """
    u = prepare_gas_features(d[d["usable"]])
    u["E_g"] = u["energy_kcal"] / 1e6
    days = u.index[u.index >= start]
    step = boost_step_response(h, 12)
    bb_lim = tuple(h["bb_kwh"].quantile([0.01, 0.99]))
    sim = simulate_boost_controller(h.loc[start:], step, float(h["mb3_temp"].median()), ki=ki, bb_limits=bb_lim)
    bb_day = sim["bb_rec"].groupby(sim.index.normalize()).mean() * 24                      # kWh/day
    base = u[u["in_baseline"]]
    mA = smf.ols("E_g ~ draw_t + cullet_pct", base).fit()
    mB = smf.ols("E_g ~ draw_t + cullet_pct + age_m", base).fit()
    ma = smf.ols("r ~ air_per_mcal", u.assign(r=u["E_g"] - mB.predict(u))).fit()
    rows = []
    for day in days:
        x = u.loc[day]
        bb = bb_day.get(day, np.nan)
        if np.isnan(bb):
            continue
        gas_rec = daily_gas_target(u, day, {"bb_g": bb * KCAL_PER_KWH / 1e6})
        air_gain = ma.params["air_per_mcal"] * max(x["air_per_mcal"] - air_target(u, day), 0.0)
        e_rec = gas_rec + bb * KCAL_PER_KWH / 1e6 + x["mb_g"] - air_gain
        e_exp = float(mA.predict(u.loc[[day]]).iloc[0])
        rows.append(dict(date=day, draw_t=x["draw_t"], ncv=x["ncv"], cullet_pct=x["cullet_pct"],
                         sfc_actual=x["sfc"], sfc_rec=e_rec * 1e6 / x["draw_kg"],
                         E_actual=x["E_g"], E_rec=e_rec, E_expected_A=e_exp,
                         draw_adj_actual=100 * (x["E_g"] / e_exp - 1), draw_adj_rec=100 * (e_rec / e_exp - 1),
                         gas_actual=x["gas_g"], gas_rec=gas_rec, bb_actual_kwh_h=x["bb_kwh"] / 24, bb_rec_kwh_h=bb / 24,
                         mb3=x["mb3_temp"], air_per_mcal=x["air_per_mcal"], seeds=x["seed_count"]))
    return pd.DataFrame(rows).set_index("date")


def history_backtest(fr: "FinalRecommender", d: pd.DataFrame, q: pd.DataFrame, inputs: dict, bt: pd.DataFrame,
                     draw_tol: float = 1.5, ncv_tol: float = 150.0, cullet_tol: float = 1.0,
                     min_days: int = 10) -> dict:
    """Back-test one set of live inputs against history.

    1. Similar days = replayed days (`bt`, from walk_forward_history) with draw within +-draw_tol t, daily
       NCV within +-ncv_tol kcal/SCM and cullet within +-cullet_tol %. With fewer than `min_days`, the window
       is widened (x1.5, x2, x3) and that is reported.
    2. On those days: average ACTUAL SFC vs average SFC had the recommender been followed (walk-forward:
       each day only used earlier days), plus the draw-adjusted % and the draw band's baseline and target.
    3. Today's recommendation: expected SFC if followed all day (it includes today's furnace age, so it is
       not directly comparable with older days; the like-for-like comparison is point 2).
    4. Setpoints on the similar days (all, and the best 25% by SFC) next to the recommended values.
    """
    rec = fr.recommend(inputs)
    bb_rec = float(rec.iloc[4, 2])                         # kWh/h, next hour (assumed held for the day)
    mb_day = inputs["mb_kwh_last_hour"] * 24
    e_now = fr.gas_target(inputs["date"], inputs["draw_t"], bb_rec * 24, mb_day) + (bb_rec * 24 + mb_day) * KCAL_PER_KWH / 1e6
    sfc_now = e_now * 1e6 / (inputs["draw_t"] * 1000)

    for mult in (1.0, 1.5, 2.0, 3.0):
        m = ((bt["draw_t"] - inputs["draw_t"]).abs() <= draw_tol * mult) \
            & ((bt["ncv"] - inputs["ncv"]).abs() <= ncv_tol * mult) \
            & ((bt["cullet_pct"] - inputs["cullet_pct"]).abs() <= cullet_tol * mult)
        if m.sum() >= min_days:
            break
    sim = bt[m].copy()
    rule = (f"draw {inputs['draw_t'] - draw_tol * mult:.1f}-{inputs['draw_t'] + draw_tol * mult:.1f} t, "
            f"NCV {inputs['ncv'] - ncv_tol * mult:.0f}-{inputs['ncv'] + ncv_tol * mult:.0f} kcal/SCM, "
            f"cullet {inputs['cullet_pct'] - cullet_tol * mult:.1f}-{inputs['cullet_pct'] + cullet_tol * mult:.1f}%"
            + ("" if mult == 1.0 else f"  (window widened x{mult:g}: too few days)"))

    u = d[d["usable"]]
    base = u[u["in_baseline"]]
    bins, labels = [45, 50, 55, 60, 65], ["45-50", "50-55", "55-60", "60-65"]
    band_base = base.groupby(pd.cut(base["draw_t"], bins, labels=labels, include_lowest=True), observed=True)["sfc"].mean()
    band = pd.cut([inputs["draw_t"]], bins, labels=labels, include_lowest=True)[0]
    bb_ = band_base.get(band, np.nan)
    e_exp_now = 53.55 + 0.605 * inputs["draw_t"] + 0.123 * inputs["cullet_pct"]       # Model A (CLAUDE.md §6)

    n = len(sim)
    summary = pd.Series({
        "similar historical days": n,
        "period covered": f"{sim.index.min().date()} to {sim.index.max().date()}" if n else "-",
        "average draw (t/day) | NCV": f"{sim['draw_t'].mean():.1f} | {sim['ncv'].mean():.0f}" if n else "-",
        "1. ACTUAL average SFC on those days (kcal/kg)": sim["sfc_actual"].mean(),
        "2. RECOMMENDER on the same days, walk-forward (kcal/kg)": sim["sfc_rec"].mean(),
        "   saving vs actual (%)": 100 * (1 - sim["sfc_rec"].mean() / sim["sfc_actual"].mean()) if n else np.nan,
        "   days where the recommender was better (%)": 100 * (sim["sfc_rec"] < sim["sfc_actual"]).mean() if n else np.nan,
        "3. draw-adjusted vs baseline: actual (%)": sim["draw_adj_actual"].mean(),
        "   draw-adjusted vs baseline: recommender (%)": sim["draw_adj_rec"].mean(),
        f"4. band {band} t: baseline SFC | -2% target": f"{bb_:.1f} | {bb_ * 0.98:.1f}",
        "   actual vs band baseline (%)": 100 * (sim["sfc_actual"].mean() / bb_ - 1) if n else np.nan,
        "   recommender vs band baseline (%)": 100 * (sim["sfc_rec"].mean() / bb_ - 1) if n else np.nan,
        "5. TODAY: expected SFC if today's recommendation is followed all day": sfc_now,
        "   today, draw-adjusted vs baseline (%)": 100 * (e_now / e_exp_now - 1),
    })

    qq = q[q.index.normalize().isin(sim.index)]
    near = qq[(qq["ncv"] - inputs["ncv"]).abs() <= ncv_tol * mult]
    best_days = sim.index[sim["sfc_actual"] <= sim["sfc_actual"].quantile(0.25)]
    qb, nb_ = qq[qq.index.normalize().isin(best_days)], near[near.index.normalize().isin(best_days)]

    def col(xq, xall):
        return [xq["ng_scm"].mean(), xq["sec_air"].mean(), xq["afr"].mean(), (xall["bb_kwh"] * 4).mean(), xall["mb3_temp"].mean()]

    setp = pd.DataFrame({"history: similar days (actual)": col(near, qq),
                         "history: best 25% of similar days": col(nb_, qb),
                         "recommended now": [rec.iloc[1, 2], rec.iloc[2, 2], rec.iloc[3, 2], bb_rec, fr.mb3_target]},
                        index=["NG (per 15 min, at a similar NCV)", "secondary air (per 15 min)", "air-fuel ratio",
                               "barrier boost (kWh/h)", "MB3 (°C; recommended = target)"])
    return {"summary": summary, "setpoints": setp, "similar_days": sim, "rule": rule,
            "band_baseline": bb_, "recommendation": rec}


# ----------------------------------------------------------------- live check: what was recommended vs what was done
def compare_day(fr: "FinalRecommender", q_day: pd.DataFrame, draw_t: float, cullet_pct: float, date=None) -> dict:
    """Compare one day's actual operation with the recommendations (for the live 'model vs actual' view).

    q_day: the day's cleaned 15-min rows (index = timestamp) with ncv, ng_scm, sec_air, bb_kwh, mb_kwh
    (kWh per 15 min) and mb3_temp; e.g. dp.clean_15min(raw=...).loc['2026-08-20'].
    Returns
      intervals: per 15 min, NCV, actual vs recommended NG / secondary air / AFR / gas heat
      hours:     per hour, actual vs recommended barrier boost (open loop: each hour starts from the actual
                 boost of the previous hour and the actual MB3, as the operator would have seen it)
      summary:   day totals: actual vs target gas, actual SFC vs expected SFC if the recommendations had been
                 followed, draw-adjusted % (Model A) and band baseline, and how closely NG followed the advice.
    A partial day (live, before midnight) is scaled to 96 intervals for the daily totals.
    """
    q = q_day.dropna(subset=["ncv"]).copy()
    date = pd.Timestamp(date if date is not None else q.index[0]).normalize()
    L = fr.limits
    scale = 96 / max(q_day["bb_kwh"].notna().sum(), 1)
    bb_day, mb_day = q_day["bb_kwh"].sum() * scale, q_day["mb_kwh"].sum() * scale        # kWh/day, actual
    target = fr.gas_target(date, draw_t, bb_day, mb_day)                                 # gas reads the actual boost
    heat = target * 1e6 / 96
    q["ng_rec"] = np.clip(heat / q["ncv"], *L["ng_scm"])
    q["afr_rec"] = np.clip(fr.air_per_mcal * q["ncv"] / 1000, *L["afr"])
    q["air_rec"] = np.clip(q["afr_rec"] * q["ng_rec"], *L["sec_air"])
    q["afr_rec"] = q["air_rec"] / q["ng_rec"]
    q["heat_actual_gcal"] = q["ng_scm"] * q["ncv"] / 1e6
    q["heat_rec_gcal"] = q["ng_rec"] * q["ncv"] / 1e6
    q["ng_dev_pct"] = 100 * (q["ng_scm"] / q["ng_rec"] - 1)
    intervals = q[["ncv", "ng_scm", "ng_rec", "ng_dev_pct", "sec_air", "air_rec", "afr", "afr_rec",
                   "heat_actual_gcal", "heat_rec_gcal"]].rename(columns={"ng_scm": "ng_actual", "sec_air": "air_actual",
                                                                        "afr": "afr_actual"})
    hr = q_day[["bb_kwh", "mb3_temp"]].resample("h").agg({"bb_kwh": "sum", "mb3_temp": "first"})
    hr["bb_actual_kwh_h"] = hr["bb_kwh"]
    hr["bb_rec_kwh_h"] = np.clip(hr["bb_kwh"].shift(1) + fr.ki * (fr.mb3_target - hr["mb3_temp"]) / fr.mb3_gain,
                                 *L["bb_kwh_h"])
    hours = hr[["mb3_temp", "bb_actual_kwh_h", "bb_rec_kwh_h"]]
    bb_rec_day = hours["bb_rec_kwh_h"].fillna(hours["bb_actual_kwh_h"]).mean() * 24
    gas_actual = (q_day["ng_scm"] * q_day["ncv"]).sum() / 1e6 * 96 / max(q_day["ng_scm"].mul(q_day["ncv"]).notna().sum(), 1)
    e_actual = gas_actual + (bb_day + mb_day) * KCAL_PER_KWH / 1e6
    e_rec = fr.gas_target(date, draw_t, bb_rec_day, mb_day) + (bb_rec_day + mb_day) * KCAL_PER_KWH / 1e6
    a = fr.mv_model_a
    e_exp = a["Intercept"] + a["draw_t"] * draw_t + a["cullet_pct"] * cullet_pct
    band = pd.cut([draw_t], [45, 50, 55, 60, 65], labels=["45-50", "50-55", "55-60", "60-65"], include_lowest=True)[0]
    bb_ = fr.band_baseline.get(str(band), np.nan)
    summary = {
        "date": str(date.date()), "intervals_with_ncv": int(len(q)), "draw_t": draw_t, "cullet_pct": cullet_pct,
        "gas_actual_gcal": gas_actual, "gas_target_gcal": target, "gas_vs_target_pct": 100 * (gas_actual / target - 1),
        "barrier_actual_kwh_day": bb_day, "barrier_rec_kwh_day": bb_rec_day,
        "sfc_actual": e_actual * 1e6 / (draw_t * 1000), "sfc_if_followed": e_rec * 1e6 / (draw_t * 1000),
        "saving_if_followed_pct": 100 * (1 - e_rec / e_actual),
        "draw_adjusted_actual_pct": 100 * (e_actual / e_exp - 1), "draw_adjusted_if_followed_pct": 100 * (e_rec / e_exp - 1),
        "band": None if pd.isna(band) else str(band), "band_baseline_sfc": bb_,
        "ng_within_2pct_of_advice_share": float((q["ng_dev_pct"].abs() <= 2).mean()),
        "ng_mean_abs_dev_pct": float(q["ng_dev_pct"].abs().mean()),
    }
    summary = {k: (int(v) if isinstance(v, (int, np.integer)) else float(v) if isinstance(v, (float, np.floating)) else v)
               for k, v in summary.items()}
    return {"summary": summary, "intervals": intervals, "hours": hours}
