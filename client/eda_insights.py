"""Charts and tables for client notebook 03 (EDA, features and insights).

Builds on report.py (style, cleaned data, fair yardsticks). Calculations come from the project code in
../src; this file only summarises the cleaned data and draws charts, so the notebook stays readable.
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import FancyBboxPatch, Rectangle, FancyArrowPatch, Arc
import statsmodels.formula.api as smf

import report as R
import recommender as rc

BLUE, ORANGE, AQUA, INK, INK2, MUTED, GRID = R.BLUE, R.ORANGE, R.AQUA, R.INK, R.INK2, R.MUTED, R.GRID
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _mlab(p):
    return f"{MONTHS[p.month - 1]}\n{str(p.year)[2:]}"


# ================================================================ orientation
def furnace_schematic():
    """A simple sketch of the melter: where each signal comes from."""
    fig, ax = plt.subplots(figsize=(12, 5.4))
    ax.set_xlim(0, 12); ax.set_ylim(-0.1, 6.1); ax.set_axis_off()
    # glass bath, combustion space and crown
    ax.add_patch(Rectangle((2.5, 1.0), 7, 1.6, fc="#f6d9b8", ec=INK2, lw=1.5))
    ax.text(4.0, 2.15, "molten glass", ha="center", va="center", color=INK2, fontsize=10)
    ax.add_patch(Rectangle((2.5, 2.6), 7, 1.3, fc="white", ec=INK2, lw=1.5))
    ax.add_patch(Arc((6, 3.9), 7, 1.6, theta1=0, theta2=180, ec=INK2, lw=1.5))
    ax.text(6, 4.3, "crown (roof)", ha="center", color=INK2, fontsize=9.5)
    # flame from port 1
    ax.add_patch(FancyArrowPatch((2.6, 3.2), (7.4, 3.2), arrowstyle="simple,head_width=10,head_length=12", color=ORANGE, alpha=0.85))
    ax.text(5.0, 3.42, "flame: NG + secondary air", ha="center", color=ORANGE, fontsize=9.5, fontweight="bold")
    # ports (text inside the boxes)
    for x, lab, col in [(0.45, "Port 1 (firing now)\nNG + secondary\nair in", ORANGE),
                        (9.65, "Port 2 (exhaust)\nhot gas → regenerator\n(stores the heat)", INK2)]:
        ax.add_patch(FancyBboxPatch((x, 2.65), 1.9, 1.15, boxstyle="round,pad=0.02,rounding_size=0.08", fc="white", ec=col, lw=1.8))
        ax.text(x + 0.95, 3.22, lab, ha="center", va="center", fontsize=8.8, color=col)
    ax.annotate("", xy=(10.6, 5.2), xytext=(1.4, 5.2), arrowprops=dict(arrowstyle="<->", color=INK2, lw=1.2))
    ax.text(6, 5.4, "the two ports swap roles every 20 minutes (reversal); the operator sets one NG flow for both",
            ha="center", fontsize=9.5, color=INK2)
    # electrodes
    for x in np.linspace(2.9, 4.2, 4):
        ax.add_patch(Rectangle((x, 0.55), 0.08, 0.75, fc=BLUE, ec="none"))
    for x in np.linspace(7.9, 9.2, 4):
        ax.add_patch(Rectangle((x, 0.55), 0.08, 0.75, fc="#7fa9df", ec="none"))
    ax.text(3.55, 0.25, "barrier boost electrodes", ha="center", color=BLUE, fontsize=9.5, fontweight="bold")
    ax.text(8.55, 0.25, "melter boost electrodes", ha="center", color="#4f7fbf", fontsize=9.5)
    # sensors
    sensors = [(6.6, 4.0, "optical crown pyrometer\n(read by hand, hourly)", (10.6, 4.4)),
               (5.0, 3.95, "crown thermocouple MC3\n(DCS, every minute)", (1.4, 4.4)),
               (6.0, 1.1, "MB3 bottom thermocouple (DCS)", (6.0, 0.25))]
    for x, y, lab, (tx, ty) in sensors:
        ax.scatter([x], [y], s=60, color=INK, zorder=5)
        ax.annotate(lab, xy=(x, y), xytext=(tx, ty), ha="center", va="center", fontsize=8.8, color=INK,
                    arrowprops=dict(arrowstyle="-", color=MUTED, lw=1))
    ax.annotate("batch in", xy=(2.5, 1.9), xytext=(0.7, 1.75), fontsize=9.5, color=INK2, va="center",
                arrowprops=dict(arrowstyle="->", color=INK2))
    ax.annotate("", xy=(10.4, 1.4), xytext=(9.5, 1.4), arrowprops=dict(arrowstyle="->", color=INK2))
    ax.text(10.5, 1.4, "glass out\n(lines S09–S12)", fontsize=9.5, color=INK2, ha="left", va="center")
    ax.set_title("How the melter works, and where each measurement comes from")
    plt.tight_layout(); plt.show()


# ================================================================ EDA
def data_sources_table(D):
    return pd.DataFrame([
        ["Analytical_Record_Creation_fixed_5.xlsx", "result", "every 15 min", "1 Sep 2025 – 30 Sep 2026",
         f"{len(D.q):,} rows", "the main record: gas, NCV, air, boosts, MB3, optical, draw, cullet, seeds"],
        ["DCS_60_TPD_MelterCrown3.xlsx", "first sheet", "every 1 min", "1 Sep 2025 – 1 Oct 2026", "≈ 570,000 rows",
         "crown thermocouple MC3, used to check the optical reading"],
        ["SFC_60_TPD_Baseline_Calculation_Sep-25_to_Jul-26_updated.xlsx", "Master Data- Energy & SFC Calc", "daily",
         "1 Sep 2025 – 31 Jul 2026", "334 days", "your baseline: used only to check our numbers, never as an input"],
    ], columns=["file", "sheet", "frequency", "period", "size", "what we used it for"]).set_index("file")


def data_levels_table(D):
    return pd.DataFrame([
        ["15-minute", f"{len(D.q):,}", "gas heat (NG × NCV per interval), the 15-min gas back-test"],
        ["hourly", f"{len(D.h):,}", "barrier boost vs bottom temperature (MB3)"],
        ["daily", f"{len(D.d):,}", "energy, SFC, draw, seeds"],
        ["usable days", f"{int(D.d.usable.sum()):,}", "all daily analysis (NCV meter working, data complete, draw present)"],
    ], columns=["level", "records", "used for"]).set_index("level")


def cleaning_table(D):
    q, d = D.q, D.d
    return pd.DataFrame([
        ["NCV outside 8,500–10,500 kcal/SCM (meter zero or glitch)", f"{int(q.ncv_bad.sum()):,} readings", "removed; live: last valid NCV is used"],
        ["NCV spike > 400 kcal/SCM away from its 2-hour median", f"{int(q.ncv_spike.sum()):,} readings", "removed"],
        ["day with less than 90% valid NCV", f"{int((~d.ncv_ok).sum())} days", "left out (no NCV is invented)"],
        ["SAP draw doubled on a month-start day", f"{int(d.draw_fixed.sum())} days", "halved (matches SAP exactly)"],
        ["short gaps in gas, air or boost", "≤ 1 hour", "filled by interpolation"],
    ], columns=["check", "found", "action"]).set_index("check")


def summary_table(D):
    u = D.u
    rows = [
        ("draw", "glass pulled per day", "t/day", u.draw_t),
        ("SFC", "energy per kg of glass", "kcal/kg", u.sfc),
        ("total energy", "gas heat + boost electricity", "Gcal/day", u.E_g),
        ("gas heat", "Σ NG × NCV", "Gcal/day", u.gas_g),
        ("electricity share", "boost share of total energy", "%", 100 * u.elec_share),
        ("NCV", "heat in one SCM of gas", "kcal/SCM", u.ncv),
        ("NG flow", "melter gas, common header", "SCM/15 min", u.ng_scm / 96),
        ("secondary air", "combustion air", "SCM/15 min", u.sec_air / 96),
        ("air per Mcal", "air per unit of gas heat", "SCM/Mcal", u.air_per_mcal),
        ("air-fuel ratio", "air ÷ NG", "–", u.afr),
        ("barrier boost", "bottom electrodes", "kWh/h", u.bb_kwh / 24),
        ("melter boost", "second electrode set", "kWh/h", u.mb_kwh / 24),
        ("MB3", "bottom temperature", "°C", u.mb3_temp),
        ("optical crown", "crown temperature (hand log)", "°C", u.opt_temp),
        ("crown TC MC3", "crown thermocouple", "°C", u.crown_tc),
        ("cullet", "recycled glass in the batch", "%", u.cullet_pct),
        ("seeds", "bubbles per sample (spec 30)", "count", u.seed_count),
    ]
    t = pd.DataFrame([(n, m, un, s.quantile(0.05), s.median(), s.quantile(0.95)) for n, m, un, s in rows],
                     columns=["variable", "meaning", "unit", "low day (P5)", "typical (median)", "high day (P95)"]).set_index("variable")
    for c in ["low day (P5)", "typical (median)", "high day (P95)"]:
        t[c] = [f"{v:,.3f}" if abs(v) < 2 else (f"{v:,.1f}" if abs(v) < 2000 else f"{v:,.0f}") for v in t[c]]
    return t


def chart_monthly_grid(D):
    u = D.u
    panels = [("draw_t", "Draw (t/day)", 1), ("sfc", "SFC (kcal/kg)", 1), ("ncv", "NCV (kcal/SCM)", 1),
              ("gas_g", "Gas heat (Gcal/day)", 1), ("bb_kwh", "Barrier boost (kWh/h)", 1 / 24), ("mb3_temp", "MB3 bottom (°C)", 1),
              ("air_per_mcal", "Air per Mcal (SCM/Mcal)", 1), ("opt_temp", "Optical crown (°C)", 1), ("seed_count", "Seeds (count)", 1)]
    g = u.groupby(u.index.to_period("M"))
    fig, axs = plt.subplots(3, 3, figsize=(13, 8.4), sharex=True)
    x = np.arange(len(g))
    for ax, (col, title, k) in zip(axs.ravel(), panels):
        med = g[col].median() * k
        lo, hi = g[col].quantile(0.1) * k, g[col].quantile(0.9) * k
        ax.fill_between(x, lo, hi, color=BLUE, alpha=0.12, lw=0)
        ax.plot(x, med, color=BLUE, marker="o", ms=4)
        ax.set_title(title, fontsize=11)
        ax.set_xticks(x[::2]); ax.set_xticklabels([_mlab(p) for p in med.index[::2]], fontsize=8.5)
    fig.suptitle("13 months at a glance: monthly median (line) and the range of typical days (band = P10–P90)",
                 x=0.01, ha="left", fontweight="bold", fontsize=12.5)
    plt.tight_layout(); plt.show()


def chart_distributions(D):
    u, h, q = D.u, D.h, D.q
    panels = [(u.sfc, "SFC (kcal/kg), daily", None), (u.draw_t, "Draw (t/day)", None),
              (q.ncv.dropna(), "NCV (kcal/SCM), every 15 min", None), (u.draw_adj, "Energy vs baseline at the same draw (%)", 0),
              (u.air_per_mcal, "Air per Mcal (SCM/Mcal), daily", None), (h.mb3_temp.dropna(), "MB3 bottom (°C), hourly", None)]
    def f(v):
        return f"{v:,.3f}" if abs(v) < 2 else (f"{v:,.1f}" if abs(v) < 100 else f"{v:,.0f}")

    fig, axs = plt.subplots(2, 3, figsize=(13, 6.6))
    for ax, (s, title, ref) in zip(axs.ravel(), panels):
        s = s[s.between(s.quantile(0.002), s.quantile(0.998))]
        ax.hist(s, bins=40, color=BLUE, alpha=0.85, rwidth=0.9)
        ax.axvline(s.median(), color=INK2, lw=1.3, ls="--")
        if ref is not None:
            ax.axvline(ref, color=ORANGE, lw=1.4, ls=":")
        ax.set_title(f"{title}\nmedian {f(s.median())}  ·  P5–P95: {f(s.quantile(.05))} to {f(s.quantile(.95))}", fontsize=10.5)
        ax.set_yticks([])
    fig.suptitle("How the key variables are spread (dashed line = median)", x=0.01, ha="left", fontweight="bold", fontsize=12.5)
    plt.tight_layout(); plt.show()


def chart_one_day(D, day="2026-05-14"):
    x = D.q.loc[day]
    fig, axs = plt.subplots(4, 1, figsize=(12, 8), sharex=True)
    axs[0].plot(x.index, x.ng_scm, color=BLUE, marker="o", ms=3, lw=1.4); axs[0].set_ylabel("NG\n(SCM/15 min)")
    axs[1].plot(x.index, x.ncv, color=INK2, lw=1.6); axs[1].set_ylabel("NCV\n(kcal/SCM)")
    axs[2].step(x.index, x.bb_kwh * 4, where="post", color=ORANGE, lw=1.8); axs[2].set_ylabel("barrier boost\n(kWh/h)")
    axs[3].plot(x.index, x.mb3_temp, color=AQUA, lw=1.8); axs[3].set_ylabel("MB3 bottom\n(°C)")
    axs[0].set_title(f"Inside one ordinary day ({pd.Timestamp(day):%d %b %Y}), every 15 minutes")
    axs[3].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M")); axs[3].set_xlabel("time of day")
    plt.tight_layout(); plt.show()


HEAT_COLS = {"draw_t": "Draw", "sfc": "SFC", "E_g": "Total energy", "gas_g": "Gas heat", "elec_g": "Electric heat",
             "bb_kwh": "Barrier boost", "mb_kwh": "Melter boost", "ncv": "NCV", "ng_scm": "NG flow (volume)",
             "sec_air": "Secondary air", "air_per_mcal": "Air per Mcal", "afr": "Air-fuel ratio", "mb3_temp": "MB3 bottom",
             "opt_temp": "Optical crown", "crown_tc": "Crown TC", "cullet_pct": "Cullet %", "seed_count": "Seeds",
             "age_m": "Furnace age"}


def correlations(D):
    u = D.u.assign(elec_g=D.u.elec_kcal / 1e6)
    c = u[list(HEAT_COLS)].corr()
    c.index = c.columns = list(HEAT_COLS.values())
    return c


def chart_heatmap(D):
    c = correlations(D)
    n = len(c)
    cmap = LinearSegmentedColormap.from_list("bo", [BLUE, "#ffffff", ORANGE])
    m = c.values.copy()
    m[np.triu_indices(n, 0)] = np.nan
    m = m[1:, :-1]                                   # drop the empty first row and last column
    fig, ax = plt.subplots(figsize=(12.5, 10))
    im = ax.imshow(m, cmap=cmap, vmin=-1, vmax=1)
    for i in range(n - 1):
        for j in range(i + 1):
            v = m[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8.3, color="white" if abs(v) > 0.6 else INK)
    ax.set_xticks(range(n - 1)); ax.set_xticklabels(c.columns[:-1], rotation=60, ha="right", fontsize=9.5)
    ax.set_yticks(range(n - 1)); ax.set_yticklabels(c.index[1:], fontsize=9.5)
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(im, ax=ax, shrink=0.6, pad=0.02)
    cb.set_label("correlation (−1 = move opposite, 0 = unrelated, +1 = move together)")
    ax.set_title(f"Correlation heat map of daily values ({len(D.u)} usable days)")
    plt.tight_layout(); plt.show()


def top_pairs(D, k=12):
    c = correlations(D)
    s = c.where(np.tril(np.ones(c.shape, bool), -1)).stack()
    s = s.reindex(s.abs().sort_values(ascending=False).index)[:k]
    return s.rename("correlation").round(2).to_frame()


def draw_adjusted_drivers(D):
    u = D.u
    cols = {"age_m": "Furnace age", "air_per_mcal": "Air per Mcal", "mb_kwh": "Melter boost", "bb_kwh": "Barrier boost",
            "mb3_temp": "MB3 bottom", "ncv": "NCV", "opt_temp": "Optical crown", "crown_tc": "Crown TC",
            "cullet_pct": "Cullet %", "seed_count": "Seeds"}
    return u[list(cols)].corrwith(u.draw_adj).rename(index=cols).sort_values()


def chart_draw_adjusted_drivers(D):
    s = draw_adjusted_drivers(D)
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.barh(range(len(s)), s.values, color=[ORANGE if v > 0 else BLUE for v in s.values], height=0.6)
    for i, v in enumerate(s.values):
        ax.text(v + (0.01 if v >= 0 else -0.01), i, f"{v:+.2f}", va="center", ha="left" if v >= 0 else "right", fontsize=9, color=INK2)
    ax.set_yticks(range(len(s))); ax.set_yticklabels(s.index); ax.axvline(0, color=INK2, lw=0.8)
    ax.set_xlim(-0.6, 0.6); ax.set_xlabel("correlation with daily energy vs baseline at the same draw")
    ax.set_title("Once draw is taken out: what moves together with extra energy?")
    plt.tight_layout(); plt.show()


def chart_key_relationships(D):
    u = D.u
    fig, axs = plt.subplots(2, 2, figsize=(12.5, 8.2))

    def sc(ax, x, y, xl, yl, title):
        ax.scatter(x, y, s=12, color=BLUE, alpha=0.5)
        k = np.polyfit(x, y, 1); xs = np.linspace(x.min(), x.max(), 20)
        ax.plot(xs, np.polyval(k, xs), color=ORANGE, lw=2)
        r2 = np.corrcoef(x, y)[0, 1] ** 2
        ax.set_xlabel(xl); ax.set_ylabel(yl); ax.set_title(f"{title}  (R² = {r2:.2f})", fontsize=11)
        return k, r2

    k, _ = sc(axs[0, 0], u.draw_t, u.E_g, "draw (t/day)", "total energy (Gcal/day)", "Energy grows slowly with draw")
    axs[0, 0].text(0.03, 0.92, f"≈ {k[1]:.0f} Gcal/day fixed + {k[0]:.2f} Gcal per tonne", transform=axs[0, 0].transAxes, color=INK2, fontsize=9.5)
    sc(axs[0, 1], u.draw_t, u.bb_kwh / 24, "draw (t/day)", "barrier boost (kWh/h)", "Barrier boost is raised with draw")
    sc(axs[1, 0], u.gas_g * 1000 / 96, u.sec_air / 96, "gas heat (Mcal per 15 min)", "secondary air (SCM/15 min)", "Air follows the heat burned")
    sc(axs[1, 1], u.ng_scm / 96, u.sec_air / 96, "NG flow (SCM/15 min)", "secondary air (SCM/15 min)", "Air follows gas volume less well")
    plt.tight_layout(); plt.show()


# ================================================================ features
def feature_table():
    return pd.DataFrame([
        ["Gas heat", "Σ (NG × NCV) per 15 min, summed over the day", "NG flow, NCV Meter", "15 min → day", "what the gas model predicts (Gcal/day)"],
        ["Draw", "SAP daily draw in tonnes; month-start doubling halved", "Daily Draw", "day", "gas model input; fair yardstick"],
        ["Barrier boost heat", "Σ kWh × 860 ÷ 10⁶", "BARRIER BOOSTER-52", "15 min → day", "gas model input (boost replaces part of the gas)"],
        ["Melter boost heat", "Σ kWh × 860 ÷ 10⁶", "MELTER BOOSTER-51", "15 min → day", "gas model input"],
        ["Furnace age", "months since 1 Sep 2025", "date", "day", "gas model input (ageing)"],
        ["Latest valid NCV", "range check + spike filter; last valid value if missing", "NCV Meter", "15 min", "turns heat into NG flow: NG = heat ÷ NCV"],
        ["Air per Mcal", "secondary air ÷ gas heat", "Secondary air, NG, NCV", "day", "air target (efficient level of recent days)"],
        ["Air-fuel ratio", "secondary air ÷ NG", "Secondary air, NG", "15 min", "operator setpoint, follows from the air target"],
        ["MB3 bottom temperature", "hourly average", "Thermocouple Melter Bottom 3", "hour", "barrier-boost controller input"],
        ["Energy and SFC", "gas heat + (barrier + melter kWh) × 860; ÷ draw for SFC", "all of the above", "day", "the result we measure"],
        ["Draw-adjusted %", "energy ÷ expected energy at the same draw and cullet − 1", "draw, cullet", "day", "fair yardstick for every comparison"],
        ["Optical crown (24-h average)", "average of the hourly hand log", "Melter Optical Temperature", "hour", "safety check (guard-rail), not a model input"],
    ], columns=["feature", "how we build it", "from column", "level", "used for"]).set_index("feature")


def features_left_out():
    return pd.DataFrame([
        ["Optical crown temperature (previous day)", "No gain in accuracy (0.344 vs 0.344); in Sep 2026 it read low and pushed the gas target the wrong way", "kept as a safety check"],
        ["Crown thermocouple MC3", "Small gain only with same-day values, which are not known when the recommendation is made", "used to check the optical reading"],
        ["Cullet %", "16–20% in this period; no significant effect on energy once ageing is allowed for", "kept in the fair yardstick only"],
        ["MB3 in the gas model", "No reliable gain; MB3 is steered by barrier boost, not by gas", "used by the boost controller"],
        ["Melter boost in the boost controller", "Changes in about 1% of hours; did not improve the MB3 forecast (0.540 → 0.537)", "the hourly MB3 feedback absorbs it"],
    ], columns=["candidate feature", "what the test showed", "decision"]).set_index("candidate feature")


def gas_model(D):
    return smf.ols(rc.GAS_FORMULA, D.u).fit()


def chart_feature_effects(D):
    m = gas_model(D); u = D.u
    names = {"draw_t": "Draw", "bb_g": "Barrier boost heat", "mb_g": "Melter boost heat", "age_m": "Furnace age"}
    rows = []
    for k, lab in names.items():
        lo, hi = u[k].quantile(0.1), u[k].quantile(0.9)
        rows.append((lab, m.params[k] * (hi - lo), lo, hi))
    t = pd.DataFrame(rows, columns=["feature", "effect", "lo", "hi"]).set_index("feature")
    t["pct"] = 100 * t.effect / u.gas_g.mean()
    t = t.reindex(t.effect.abs().sort_values().index)
    fig, ax = plt.subplots(figsize=(10, 3.6))
    ax.barh(range(len(t)), t.effect, color=[ORANGE if v > 0 else BLUE for v in t.effect], height=0.55)
    for i, (v, p) in enumerate(zip(t.effect, t.pct)):
        ax.text(v + (0.15 if v >= 0 else -0.15), i, f"{v:+.1f} Gcal/day ({p:+.1f}%)", va="center",
                ha="left" if v >= 0 else "right", fontsize=9.5, color=INK2)
    ax.set_yticks(range(len(t))); ax.set_yticklabels(t.index); ax.axvline(0, color=INK2, lw=0.8)
    ax.set_xlim(-12, 12); ax.set_xlabel("change in daily gas heat needed when the feature moves from a low day (P10) to a high day (P90)")
    ax.set_title("How much each feature moves the gas the furnace needs")
    plt.tight_layout(); plt.show()
    lab = {"Draw": "t/day", "Barrier boost heat": "Gcal/day", "Melter boost heat": "Gcal/day", "Furnace age": "months"}
    out = t.assign(unit=[lab[i] for i in t.index]).rename(columns={"effect": "effect (Gcal/day)", "pct": "effect (% of gas)",
                                                                  "lo": "low day (P10)", "hi": "high day (P90)"})
    return out[["low day (P10)", "high day (P90)", "unit", "effect (Gcal/day)", "effect (% of gas)"]].iloc[::-1].round(2)


def chart_feature_tests(D):
    v = pd.read_csv(D.processed / "training_gas_final_variants.csv").set_index("variant")
    lab = {"without barrier boost": ("without barrier boost", MUTED),
           "final inputs without melter boost": ("without melter boost", MUTED),
           "+ optical (yesterday, filled)": ("+ optical crown, previous day", MUTED),
           "winner (no crown temp)": ("FINAL model", AQUA),
           "+ crown thermocouple MC3": ("+ crown TC, same day*", LIGHT),
           "+ optical (same day, filled)": ("+ optical crown, same day*", LIGHT)}
    v = v.loc[list(lab)]
    base = v.loc["winner (no crown temp)", "pinball"]
    rel = 100 * (v.pinball / base - 1)
    fig, ax = plt.subplots(figsize=(10, 3.6))
    ax.barh(range(len(v)), rel.values, color=[lab[i][1] for i in v.index], height=0.55)
    for i, r in enumerate(rel.values):
        ax.text(r + (0.4 if r >= 0 else -0.4), i, f"{r:+.1f}%", va="center", ha="left" if r >= 0 else "right", fontsize=9.5, color=INK2)
    ax.set_yticks(range(len(v))); ax.set_yticklabels([lab[i][0] for i in v.index]); ax.axvline(0, color=INK2, lw=0.8)
    ax.set_xlim(-8, 32); ax.invert_yaxis()
    ax.set_xlabel("prediction error vs the final model (%)   (lower = more accurate)")
    ax.set_title("Adding or removing a feature: change in prediction error")
    plt.tight_layout(); plt.show()


LIGHT = R.LIGHT_BLUE


# ================================================================ insights
def lowest_highest(D, n=5):
    u = D.u
    cols = {"draw_t": "draw (t/day)", "sfc": "SFC (kcal/kg)", "draw_adj": "vs baseline at same draw (%)", "gas_g": "gas heat (Gcal/day)",
            "bb_kwh": "barrier boost (kWh/day)", "mb3_temp": "MB3 (°C)", "air_per_mcal": "air per Mcal", "seed_count": "seeds"}
    lo = u.nsmallest(n, "sfc")[list(cols)].rename(columns=cols)
    hi = u.nlargest(n, "sfc")[list(cols)].rename(columns=cols)
    lo.index = lo.index.strftime("%d %b %Y"); hi.index = hi.index.strftime("%d %b %Y")
    return lo.round(2), hi.round(2)


def same_draw_extremes(D, n=4):
    u = D.u
    cols = {"draw_t": "draw (t/day)", "sfc": "SFC (kcal/kg)", "draw_adj": "vs baseline at same draw (%)", "gas_g": "gas heat (Gcal/day)",
            "bb_kwh": "barrier boost (kWh/day)", "mb3_temp": "MB3 (°C)", "seed_count": "seeds"}
    best = u.nsmallest(n, "draw_adj")[list(cols)].rename(columns=cols)
    worst = u.nlargest(n, "draw_adj")[list(cols)].rename(columns=cols)
    best.index = best.index.strftime("%d %b %Y"); worst.index = worst.index.strftime("%d %b %Y")
    return best.round(2), worst.round(2)


def chart_crown(D):
    d = D.d
    m = d.groupby(d.index.to_period("M")).agg(opt=("opt_temp", "mean"), tc=("crown_tc", "mean"))
    fig, ax = plt.subplots(figsize=(11, 3.6))
    x = np.arange(len(m))
    ax.plot(x, m.opt, color=ORANGE, marker="o", label="optical crown (hand log, hourly)")
    ax.plot(x, m.tc, color=BLUE, marker="o", label="crown thermocouple MC3 (DCS, every minute)")
    ax.set_xticks(x); ax.set_xticklabels([_mlab(p) for p in m.index], fontsize=9)
    ax.set_ylabel("°C (monthly average)"); ax.set_ylim(1562, 1578)
    off = (m.opt - m.tc).mean()
    ax.set_title(f"The crown is held almost flat; the optical reads about {off:.1f} °C above the thermocouple")
    ax.legend(loc="lower left", ncol=2); plt.tight_layout(); plt.show()


# ================================================================ how it reduces SFC
def recommendation_example(D, ts="2026-08-19 10:00"):
    """Recommendation at one moment, with what was actually run in that hour and the historical range."""
    FR = rc.FinalRecommender.load(D.processed.parent.parent / "models" / "recommender_latest.json")
    t = pd.Timestamp(ts); day = str(t.date()); prev = t - pd.Timedelta("1h")
    qh = D.q.loc[t: t + pd.Timedelta("45min")]
    inputs = dict(date=day, ncv=float(qh.ncv.dropna().iloc[0]), draw_t=float(D.d.loc[day, "draw_t"]),
                  cullet_pct=float(D.d.loc[day, "cullet_pct"]),
                  optical_prev24h=float(D.h.loc[t - pd.Timedelta("24h"): prev, "opt_temp"].mean()),
                  bb_kwh_last_hour=float(D.h.loc[prev, "bb_kwh"]), mb_kwh_last_hour=float(D.h.loc[prev, "mb_kwh"]),
                  mb3_now=float(D.h.loc[t, "mb3_temp"]))
    rec = FR.recommend(inputs)
    L = FR.limits
    med = dict(ng=D.q.ng_scm.median(), air=D.q.sec_air.median(), afr=D.q.afr.median(), bb=D.h.bb_kwh.median())
    rows = [("NG flow", "SCM/15 min", L["ng_scm"], med["ng"], qh.ng_scm.mean(), rec.iloc[1, 2]),
            ("Secondary air", "SCM/15 min", L["sec_air"], med["air"], qh.sec_air.mean(), rec.iloc[2, 2]),
            ("Air-fuel ratio", "–", L["afr"], med["afr"], qh.sec_air.mean() / qh.ng_scm.mean(), rec.iloc[3, 2]),
            ("Barrier boost", "kWh/h", L["bb_kwh_h"], med["bb"], float(D.h.loc[t, "bb_kwh"]), rec.iloc[4, 2])]
    return inputs, rows, rec.attrs["flags"]


def chart_recommendation_example(D, ts="2026-08-19 10:00"):
    inputs, rows, flags = recommendation_example(D, ts)
    fig, axs = plt.subplots(len(rows), 1, figsize=(11, 5.6))
    for ax, (name, unit, (lo, hi), med, act, recv) in zip(axs, rows):
        a, b = min(lo, act, recv), max(hi, act, recv)
        pad = (b - a) * 0.1
        ax.set_xlim(a - pad, b + pad); ax.set_ylim(-1, 1); ax.set_yticks([]); ax.grid(False)
        for s in ("left", "top", "right"):
            ax.spines[s].set_visible(False)
        ax.plot([lo, hi], [0, 0], color=GRID, lw=12, solid_capstyle="round")
        ax.plot([med, med], [-0.45, 0.45], color=INK2, lw=2)
        ax.scatter([act], [0], s=150, color=ORANGE, zorder=3, label="actual in that hour")
        ax.scatter([recv], [0], s=170, color=AQUA, marker="D", zorder=4, label="recommended")
        d = 2 if name == "Air-fuel ratio" else 1
        ax.set_title(f"{name} ({unit}):  actual {act:,.{d}f}   →   recommended {recv:,.{d}f}     "
                     f"history P1–P99: {lo:,.{d}f} – {hi:,.{d}f}", fontsize=10.5, loc="left")
    axs[0].legend(loc="upper right", bbox_to_anchor=(1, 2.1), ncol=2)
    fig.suptitle(f"Recommendation for {pd.Timestamp(ts):%d %b %Y, %H:%M} against the furnace's own history "
                 "(grey = P1–P99, line = median)", x=0.01, ha="left", fontweight="bold", fontsize=12)
    plt.tight_layout(); plt.show()
    return pd.Series(inputs).rename("input").to_frame()


def chart_path_today():
    steps = [("Gas recommender", 0.72, BLUE, "proven"), ("Barrier-boost controller", 0.41, BLUE, "proven"),
             ("Air target", 0.18, BLUE, "proven"), ("Lever A: MB3 target 1,319.2 °C", 0.30, ORANGE, "trial"),
             ("Lever B: air per Mcal 1.252", 0.25, ORANGE, "trial"), ("Lever C: crown −1 to −2 °C", 0.14, ORANGE, "trial")]
    fig, ax = plt.subplots(figsize=(11.5, 4.4))
    cum = 0
    for i, (lab, v, col, kind) in enumerate(steps):
        ax.barh(i, v, left=cum, color=col, height=0.55, hatch=None if kind == "proven" else "//", edgecolor="white")
        cum += v
        ax.text(cum + 0.03, i, "−0.15% or more" if i == 5 else f"−{v:.2f}%", va="center", fontsize=9.5, color=INK2)
    ax.barh(len(steps), 2.0, color=AQUA, height=0.6)
    ax.text(2.03, len(steps), "−2.0%", va="center", fontsize=11, fontweight="bold", color=INK)
    ax.set_yticks(range(len(steps) + 1)); ax.set_yticklabels([s[0] for s in steps] + ["Total"])
    ax.invert_yaxis(); ax.set_xlim(0, 2.5)
    ax.set_xlabel("SFC reduction vs today's operation at the same draw (%)")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=BLUE, label="proven on history (walk-forward)"),
                       Patch(facecolor=ORANGE, hatch="//", edgecolor="white", label="trial levers, inside the historical range")],
              loc="upper right")
    ax.set_title("Path to 2% lower SFC")
    plt.tight_layout(); plt.show()
