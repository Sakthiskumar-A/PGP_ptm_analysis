"""Charts and helpers for the two client notebooks.

The calculations come from the project code in ../src (data_prep.py: cleaning; recommender.py:
the gas and barrier-boost recommenders). This file only loads the cleaned data and draws charts,
so that the notebooks stay short and readable.
"""
import os
import sys
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
warnings.filterwarnings("ignore")

import numpy as np                                    # noqa: E402
import pandas as pd                                   # noqa: E402
import matplotlib.pyplot as plt                       # noqa: E402
from matplotlib.patches import FancyBboxPatch         # noqa: E402
import statsmodels.formula.api as smf                 # noqa: E402

import data_prep as dp                                # noqa: E402
import recommender as rc                              # noqa: E402

# ----------------------------------------------------------------- style
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, MUTED, GRID, SURF = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"
LIGHT_BLUE = "#9cc3ef"
BASELINE, TARGET = 1576.3, 1544.8
BINS, LABELS = [45, 50, 55, 60, 65], ["45-50 t", "50-55 t", "55-60 t", "60-65 t"]


def setup():
    plt.rcParams.update({
        "figure.facecolor": SURF, "axes.facecolor": SURF, "axes.edgecolor": MUTED, "axes.labelcolor": INK2,
        "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
        "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 2, "font.size": 10.5,
        "axes.titlesize": 12.5, "axes.titleweight": "bold", "axes.titlecolor": INK, "axes.titlelocation": "left",
        "legend.frameon": False, "figure.dpi": 110, "axes.axisbelow": True})
    pd.set_option("display.width", 200); pd.set_option("display.max_columns", 40); pd.set_option("display.max_colwidth", 120)


def label_right(ax, y, text, color=INK2, dy=0, va="bottom"):
    ax.annotate(text, xy=(1, y), xycoords=("axes fraction", "data"), xytext=(-4, dy), textcoords="offset points",
                ha="right", va=va, color=color, fontsize=9)


# ----------------------------------------------------------------- data
class Data:
    """All cleaned tables, the fair yardsticks and the history replay."""

    def __init__(self):
        P = dp.PROCESSED
        self.q = pd.read_parquet(P / "ar_15min_clean.parquet")
        self.h = pd.read_parquet(P / "hourly_clean.parquet")
        self.d = pd.read_parquet(P / "daily_clean.parquet")
        u = rc.prepare_gas_features(self.d[self.d["usable"]])
        u["E_g"] = u["energy_kcal"] / 1e6
        self.u = u
        self.base = u[u["in_baseline"]]
        self.mA = smf.ols("E_g ~ draw_t + cullet_pct", self.base).fit()                 # draw-adjusted yardstick
        self.mB = smf.ols("E_g ~ draw_t + cullet_pct + age_m", self.base).fit()         # with ageing
        u["draw_adj"] = 100 * (u["E_g"] / self.mA.predict(u) - 1)
        u["band"] = pd.cut(u["draw_t"], BINS, labels=LABELS, include_lowest=True)
        self.band_base = self.base.groupby(pd.cut(self.base["draw_t"], BINS, labels=LABELS, include_lowest=True),
                                           observed=True)["sfc"].mean()
        f = P / "backtest_daily.parquet"
        self.bt = pd.read_parquet(f) if f.exists() else rc.walk_forward_history(self.d, self.h)
        self.processed = P


def history_replay(D, refresh=False):
    if refresh:
        D.bt = rc.walk_forward_history(D.d, D.h)
        D.bt.to_parquet(D.processed / "backtest_daily.parquet")
    return D.bt


# ----------------------------------------------------------------- notebook 1: headline
def kpi_tiles(tiles):
    """tiles: list of (big number, label, colour)."""
    fig, ax = plt.subplots(figsize=(12, 2.1))
    ax.set_axis_off(); ax.set_xlim(0, len(tiles)); ax.set_ylim(0, 1)
    for i, (num, lab, col) in enumerate(tiles):
        ax.add_patch(FancyBboxPatch((i + 0.05, 0.05), 0.9, 0.9, boxstyle="round,pad=0,rounding_size=0.06",
                                    fc="white", ec=GRID, lw=1.2))
        ax.text(i + 0.5, 0.6, num, ha="center", va="center", fontsize=22, fontweight="bold", color=col)
        ax.text(i + 0.5, 0.24, lab, ha="center", va="center", fontsize=9.5, color=INK2, wrap=True)
    plt.tight_layout(); plt.show()


def chart_coverage(D):
    d = D.d
    m = d.groupby(d.index.to_period("M")).agg(usable=("usable", "sum"), days=("usable", "size"))
    m["left out"] = m.days - m.usable
    fig, ax = plt.subplots(figsize=(11, 3.4))
    x = np.arange(len(m))
    ax.bar(x, m.usable, color=BLUE, width=0.7, label="usable days")
    ax.bar(x, m["left out"], bottom=m.usable, color=GRID, width=0.7, label="left out (NCV meter or data gaps)")
    for i, (a, b) in enumerate(zip(m.usable, m.days)):
        ax.text(i, b + 0.6, f"{a}", ha="center", color=INK2, fontsize=9)
    ax.set_xticks(x); ax.set_xticklabels([p.strftime("%b\n%Y") for p in m.index])
    ax.set_ylabel("days"); ax.set_ylim(0, 36)
    ax.set_title(f"{int(d.usable.sum())} of {len(d)} days are usable (number = usable days)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2)
    plt.tight_layout(); plt.show()


def chart_baseline(D):
    u = D.u
    fig, ax = plt.subplots(figsize=(11, 3.8))
    ax.plot(u.index, u.sfc, color=GRID, lw=1, label="daily SFC")
    roll = u.sfc.rolling(30, min_periods=10).mean()
    ax.plot(roll.index, roll, color=BLUE, lw=2.2, label="30-day average")
    ax.axhline(BASELINE, color=INK2, lw=1.2, ls="--"); ax.axhline(TARGET, color=ORANGE, lw=1.6, ls=":")
    label_right(ax, BASELINE, "baseline 1,576.3"); label_right(ax, TARGET, "target 1,544.8 (−2%)", color=ORANGE, va="top", dy=-2)
    ax.axvspan(pd.Timestamp("2025-09-01"), pd.Timestamp("2026-07-31"), color=BLUE, alpha=0.04)
    ax.text(pd.Timestamp("2025-10-15"), u.sfc.max() + 5, "baseline period (Sep 2025 – Jul 2026)", color=INK2, fontsize=9)
    ax.set_ylabel("SFC (kcal/kg)"); ax.set_title("Daily SFC recomputed from your raw 15-min data")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2); plt.tight_layout(); plt.show()


def chart_draw(D):
    b = D.base
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.2), gridspec_kw={"width_ratios": [1.4, 1]})
    ax[0].scatter(b.draw_t, b.sfc, s=16, color=MUTED, alpha=0.6, label="baseline days")
    xs = np.linspace(b.draw_t.min(), b.draw_t.max(), 50)
    E = D.mA.predict(pd.DataFrame({"draw_t": xs, "cullet_pct": b.cullet_pct.mean()}))
    ax[0].plot(xs, E * 1e3 / xs, color=BLUE, lw=2.4, label="expected SFC for that draw")
    ax[0].set_xlabel("draw (t/day)"); ax[0].set_ylabel("SFC (kcal/kg)")
    ax[0].set_title("Lower draw → higher SFC (same furnace, same firing)")
    ax[0].legend(loc="upper right")
    bb = D.band_base
    y = np.arange(len(bb))
    ax[1].barh(y, bb.values, color=BLUE, height=0.55)
    ax[1].scatter(bb.values * 0.98, y, color=ORANGE, marker="|", s=400, lw=3, zorder=3, label="−2% target")
    for i, v in enumerate(bb.values):
        ax[1].text(v + 6, i, f"{v:,.0f}  → target {v*0.98:,.0f}", va="center", fontsize=9, color=INK2)
    ax[1].set_yticks(y); ax[1].set_yticklabels(bb.index); ax[1].invert_yaxis()
    ax[1].set_xlim(1400, 1950); ax[1].set_xlabel("baseline SFC (kcal/kg)")
    ax[1].set_title("Baseline SFC per 5-t draw band"); ax[1].legend(loc="lower right")
    plt.tight_layout(); plt.show()


def chart_raw_vs_adjusted(D):
    u = D.u
    m = u.groupby(u.index.to_period("M")).agg(sfc=("sfc", "mean"), adj=("draw_adj", "mean"), draw=("draw_t", "mean"))
    m["raw"] = 100 * (m.sfc / BASELINE - 1)
    fig, ax = plt.subplots(figsize=(11, 3.8))
    x = np.arange(len(m)); w = 0.38
    ax.bar(x - w / 2, m.raw, width=w, color=GRID, label="raw SFC vs baseline (misleading)")
    ax.bar(x + w / 2, m.adj, width=w, color=BLUE, label="draw-adjusted vs baseline (fair)")
    ax.axhline(0, color=INK2, lw=0.8); ax.axhline(-2, color=ORANGE, lw=1.4, ls=":")
    label_right(ax, -2, "target −2%", color=ORANGE, va="top")
    ax.set_xticks(x); ax.set_xticklabels([f"{p.strftime('%b %y')}\n{dr:.1f} t" for p, dr in zip(m.index, m.draw)], fontsize=9)
    ax.set_ylabel("% vs baseline"); ax.set_title("Same months, two views: raw SFC swings with draw; the fair view shows real performance")
    ax.legend(loc="upper left"); plt.tight_layout(); plt.show()
    return m[["draw", "sfc", "raw", "adj"]].rename(columns={"draw": "draw (t/day)", "sfc": "SFC", "raw": "raw vs baseline %",
                                                           "adj": "draw-adjusted %"}).round(2)


def chart_ageing(D):
    u = D.u
    fig, ax = plt.subplots(figsize=(11, 3.6))
    ax.scatter(u.index, u.draw_adj, s=9, color=MUTED, alpha=0.5, label="daily, draw-adjusted")
    r = u.draw_adj.rolling(30, min_periods=10).mean()
    ax.plot(r.index, r, color=BLUE, lw=2.4, label="30-day average")
    t = (u.index - u.index.min()).days.values
    k = np.polyfit(t, u.draw_adj.values, 1)
    ax.plot(u.index, np.polyval(k, t), color=ORANGE, lw=1.6, ls="--", label=f"trend: about {k[0]*30.44:+.1f}% per month")
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_ylim(-4, 5); ax.set_ylabel("energy vs baseline at same draw (%)")
    ax.set_title("Furnace ageing: at the same draw, the furnace slowly needs more energy")
    ax.legend(loc="upper left", ncol=3); plt.tight_layout(); plt.show()


def chart_ncv_day(D, day="2026-06-29"):
    x = D.q.loc[day, ["ncv", "ng_scm"]].dropna().copy()
    x["heat"] = x.ng_scm * x.ncv * 4 / 1e6                     # Gcal/h
    steady_heat = x.heat.mean()
    x["ng_needed"] = steady_heat * 1e6 / 4 / x.ncv
    fig, ax = plt.subplots(3, 1, figsize=(11, 7.2), sharex=True)
    ax[0].plot(x.index, x.ncv, color=INK2, lw=1.6); ax[0].set_ylabel("NCV\n(kcal/SCM)")
    ax[0].set_title(f"One day ({pd.Timestamp(day):%d %b %Y}): gas quality changes, gas flow doesn't follow it fully")
    ax[1].plot(x.index, x.ng_scm, color=MUTED, lw=1.6, label="actual NG flow")
    ax[1].plot(x.index, x.ng_needed, color=BLUE, lw=2.2, label="NG = heat ÷ NCV (recommender)")
    ax[1].set_ylabel("NG\n(per 15 min)"); ax[1].legend(loc="upper left", ncol=2)
    ax[2].plot(x.index, x.heat, color=MUTED, lw=1.6, label="actual gas heat")
    ax[2].axhline(steady_heat, color=BLUE, lw=2.2, label="steady heat (recommender)")
    ax[2].set_ylabel("gas heat\n(Gcal/h)"); ax[2].legend(loc="upper left", ncol=2)
    import matplotlib.dates as mdates
    ax[2].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M")); ax[2].set_xlabel("time of day")
    plt.tight_layout(); plt.show()


def ncv_correction(D):
    hh = D.h[D.h.ncv.notna()].copy(); hh["dn"] = hh.ncv.diff()
    ideal = hh.ng_scm.mean() / hh.ncv.mean() * 100
    out = []
    for k in range(5):
        hh["dg"] = hh.ng_scm.shift(-k) - hh.ng_scm.shift(1)
        out.append(-smf.ols("dg ~ dn", hh).fit().params.dn * 100 / ideal * 100)
    return pd.Series(out, index=range(5))


def chart_ncv_lag(D):
    s = ncv_correction(D)
    fig, ax = plt.subplots(figsize=(9, 3.4))
    ax.bar(s.index, s.values, color=BLUE, width=0.6, label="operators today")
    ax.axhline(100, color=ORANGE, lw=1.6, ls=":"); label_right(ax, 100, "recommender: 100% in the same cycle", color=ORANGE)
    for i, v in s.items():
        ax.text(i, v + 3, f"{v:.0f}%", ha="center", color=INK2)
    ax.set_xticks(s.index); ax.set_xticklabels(["same hour", "+1 h", "+2 h", "+3 h", "+4 h"])
    ax.set_ylim(0, 118); ax.set_ylabel("% of needed NG change made")
    ax.set_title("When NCV changes, how much of the needed gas correction is made, and when")
    plt.tight_layout(); plt.show()


def mb3_responses(D, lags=12):
    x = D.h[["mb3_temp", "bb_kwh", "gas_kcal"]].dropna().asfreq("h")
    df = pd.DataFrame({"y": x.mb3_temp.diff()})
    for k in range(lags + 1):
        df[f"b{k}"] = x.bb_kwh.diff().shift(k); df[f"g{k}"] = (x.gas_kcal / 1e6).diff().shift(k)
    m = smf.ols("y ~ " + " + ".join([f"b{k}" for k in range(lags + 1)] + [f"g{k}" for k in range(lags + 1)]), df.dropna()).fit()
    b = (pd.Series([m.params[f"b{k}"] for k in range(lags + 1)]).cumsum() * 100).clip(lower=0).cummax()
    g = (pd.Series([m.params[f"g{k}"] for k in range(lags + 1)]).cumsum() * 0.086).clip(lower=0).cummax()
    return b, g


def chart_boost_mb3(D):
    b, g = mb3_responses(D)
    fig, ax = plt.subplots(figsize=(9, 3.6))
    ax.plot(b.index, b, color=BLUE, marker="o", ms=5, label="+100 kWh/h barrier boost")
    ax.plot(g.index, g, color=ORANGE, marker="s", ms=5, label="the same heat as gas (86 Mcal/h)")
    ax.text(12.2, b.iloc[-1], f"+{b.iloc[-1]:.1f} °C", va="center", color=INK2)
    ax.text(12.2, g.iloc[-1], f"+{g.iloc[-1]:.1f} °C", va="center", color=INK2)
    ax.set_xlim(-0.3, 13.5); ax.set_xlabel("hours after the change"); ax.set_ylabel("MB3 bottom temperature change (°C)")
    ax.set_title("Barrier boost is the handle for the bottom temperature"); ax.legend(loc="upper left")
    plt.tight_layout(); plt.show()


def chart_boost_energy(D):
    fe = smf.ols("gas_g ~ draw_t + bb_g + mb_g + C(mon)", D.u.assign(mon=D.u.index.to_period("M").astype(str))).fit()
    gm = smf.ols(rc.GAS_FORMULA, D.u).fit()
    rep = (-gm.params.bb_g + -fe.params.bb_g) / 2
    fig, ax = plt.subplots(figsize=(9, 3.2))
    vals = [1.0, -rep, 1 - rep]
    labs = ["electricity added\n(1 Gcal boost)", "gas saved", "net change\nin energy"]
    cols = [ORANGE, BLUE, INK2]
    ax.bar(range(3), vals, color=cols, width=0.55)
    for i, v in enumerate(vals):
        ax.text(i, v + (0.04 if v >= 0 else -0.04), f"{v:+.2f} Gcal", ha="center", va="bottom" if v >= 0 else "top", color=INK, fontweight="bold")
    ax.axhline(0, color=INK2, lw=0.8); ax.set_xticks(range(3)); ax.set_xticklabels(labs)
    ax.set_ylim(-1.05, 1.25); ax.set_ylabel("Gcal")
    ax.set_title("1 Gcal more barrier boost saves only ~%.2f Gcal of gas → total energy goes UP" % rep)
    plt.tight_layout(); plt.show()


def chart_air(D):
    u = D.u.copy()
    u["resid"] = 100 * (u.E_g / D.mB.predict(u) - 1)
    u["grp"] = pd.qcut(u.air_per_mcal, 5)
    g = u.groupby("grp", observed=True).agg(apm=("air_per_mcal", "mean"), r=("resid", "mean"), se=("resid", "sem"), n=("resid", "size"))
    fig, ax = plt.subplots(figsize=(9, 3.6))
    ax.errorbar(g.apm, g.r, yerr=1.96 * g.se, fmt="o-", color=BLUE, ms=8, capsize=4, lw=2)
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_xlabel("secondary air per Mcal of gas heat (SCM/Mcal), 5 groups of days")
    ax.set_ylabel("energy vs expected (%)")
    ax.set_title("Days with less excess air used less energy (same draw and furnace age)")
    plt.tight_layout(); plt.show()


def chart_seeds(D):
    u = D.u.copy()
    u["eff"] = pd.qcut(u.draw_adj, 4, labels=["most efficient 25%", "2nd", "3rd", "least efficient 25%"])
    fig, ax = plt.subplots(1, 2, figsize=(12, 3.6))
    ax[0].hist(u.seed_count.dropna(), bins=range(0, 34), color=BLUE, rwidth=0.85)
    ax[0].axvline(30, color=ORANGE, lw=2, ls=":"); ax[0].text(29.6, ax[0].get_ylim()[1] * 0.9, "spec 30", color=ORANGE, ha="right")
    p95 = u.seed_count.quantile(0.95)
    ax[0].axvline(p95, color=INK2, lw=1.2, ls="--"); ax[0].text(p95 + 0.4, ax[0].get_ylim()[1] * 0.75, f"95% of days\n≤ {p95:.0f}", color=INK2, fontsize=9)
    ax[0].set_xlabel("seed count per day"); ax[0].set_ylabel("days"); ax[0].set_title("Seeds stay far below the spec")
    s = u.groupby("eff", observed=True).seed_count.mean()
    ax[1].bar(range(4), s.values, color=[BLUE, LIGHT_BLUE, LIGHT_BLUE, MUTED], width=0.6)
    for i, v in enumerate(s.values):
        ax[1].text(i, v + 0.3, f"{v:.1f}", ha="center", color=INK2)
    ax[1].set_xticks(range(4)); ax[1].set_xticklabels(s.index, fontsize=9); ax[1].set_ylabel("average seeds")
    ax[1].set_title("The most energy-efficient days have FEWER seeds"); ax[1].set_ylim(0, s.max() * 1.25)
    plt.tight_layout(); plt.show()


def best_vs_worst(D):
    u = D.u.copy()
    u["eff"] = pd.qcut(u.draw_adj, 4, labels=["most efficient 25%", "2nd", "3rd", "least efficient 25%"])
    t = u.groupby("eff", observed=True).agg(**{
        "energy vs baseline at same draw (%)": ("draw_adj", "mean"), "draw (t/day)": ("draw_t", "mean"),
        "air per Mcal": ("air_per_mcal", "mean"), "barrier boost (kWh/day)": ("bb_kwh", "mean"),
        "MB3 bottom temp (°C)": ("mb3_temp", "mean"),
        "optical crown temp (°C)": ("opt_temp", "mean"), "seeds": ("seed_count", "mean")}).T
    return t.iloc[:, [0, 3]].round(2)


def chart_efficient_spread(D):
    u = D.u
    fig, ax = plt.subplots(figsize=(10, 3.4))
    q25 = u.draw_adj.quantile(0.25)
    n, bins, patches = ax.hist(u.draw_adj, bins=40, color=MUTED, rwidth=0.9)
    for p, left in zip(patches, bins[:-1]):
        if left < q25:
            p.set_facecolor(BLUE)
    ax.axvline(0, color=INK2, lw=1); ax.axvline(-2, color=ORANGE, lw=1.6, ls=":")
    ax.text(-2.1, ax.get_ylim()[1] * 0.92, "−2% target", color=ORANGE, ha="right")
    ax.text(q25 - 0.1, ax.get_ylim()[1] * 0.75, "most efficient\nquarter of days", color=BLUE, ha="right", fontsize=9)
    ax.set_xlabel("daily energy vs baseline at the same draw (%)"); ax.set_ylabel("days")
    ax.set_title("The furnace already runs efficiently on many days: the goal is to make that the normal day")
    plt.tight_layout(); plt.show()


# ----------------------------------------------------------------- results
def chart_monthly_replay(D):
    bt = D.bt
    m = bt.groupby(bt.index.to_period("M")).agg(actual=("sfc_actual", "mean"), rec=("sfc_rec", "mean"), days=("sfc_actual", "size"))
    m["saving"] = 100 * (1 - m.rec / m.actual)
    fig, ax = plt.subplots(figsize=(11, 3.9))
    x = np.arange(len(m))
    ax.vlines(x, m.rec, m.actual, color=GRID, lw=3)
    ax.scatter(x, m.actual, color=MUTED, s=70, zorder=3, label="actual operation")
    ax.scatter(x, m.rec, color=BLUE, s=70, zorder=3, label="with the recommendations")
    for i, (a, r, s) in enumerate(zip(m.actual, m.rec, m.saving)):
        ax.text(i, a + 6, f"−{s:.1f}%", ha="center", color=INK2, fontsize=9)
    ax.set_xticks(x); ax.set_xticklabels([p.strftime("%b\n%Y") for p in m.index])
    ax.set_ylabel("average SFC (kcal/kg)"); ax.set_ylim(m.rec.min() - 25, m.actual.max() + 25)
    ax.set_title("Replaying history: the recommendations would have lowered SFC in every month")
    ax.legend(loc="upper left", ncol=2); plt.tight_layout(); plt.show()
    return m.round(2)


def chart_bands(D):
    pct = pd.read_csv(D.processed / "T4_band_pct.csv", index_col=0)
    pct = pct[["(1) actual", "(5) = (4) + air target"]]
    days = D.u.loc["2026-06-01":"2026-08-31"].band.value_counts().reindex(LABELS)
    fig, ax = plt.subplots(figsize=(10, 3.8))
    x = np.arange(len(pct)); w = 0.36
    ax.bar(x - w / 2, pct.iloc[:, 0], width=w, color=MUTED, label="actual (Jun–Aug 2026)")
    ax.bar(x + w / 2, pct.iloc[:, 1], width=w, color=BLUE, label="with the recommendations")
    for i, (a, r) in enumerate(pct.values):
        ax.text(i - w / 2, a + (0.06 if a >= 0 else -0.2), f"{a:+.2f}", ha="center", fontsize=9, color=INK2)
        ax.text(i + w / 2, r + (0.06 if r >= 0 else -0.2), f"{r:+.2f}", ha="center", fontsize=9, color=INK2)
    ax.axhline(0, color=INK2, lw=0.8); ax.axhline(-2, color=ORANGE, lw=1.6, ls=":")
    label_right(ax, -2, "band target −2%", color=ORANGE, va="bottom", dy=2)
    ax.set_xticks(x); ax.set_xticklabels([f"{b}\n({n} days)" for b, n in zip(pct.index, days.values)])
    ax.set_ylim(-2.5, 2.2); ax.set_ylabel("% vs band baseline SFC")
    ax.set_title("Per 5-t draw band: the common bands move from above to below their baseline")
    ax.legend(loc="upper left", ncol=2); plt.tight_layout(); plt.show()


def chart_path_to_2pct():
    steps = [("Today\n(Jun–Aug 26)", 1.14, "start"), ("Gas\nrecommender", -0.72, "proven"), ("Barrier-boost\ncontroller", -0.41, "proven"),
             ("Air\ntarget", -0.18, "proven"), ("Proven\nresult", None, "sub"),
             ("Trial: MB3\ntarget −1 °C", -0.30, "trial"), ("Trial: air\nto hist. P25", -0.25, "trial"),
             ("With trial\nlevers", None, "sub2"), ("Trial: crown\n−1 to −2 °C", None, "unknown"), ("Target", -2.0, "target")]
    fig, ax = plt.subplots(figsize=(12.5, 4.6))
    cum = 0.0
    for i, (lab, v, kind) in enumerate(steps):
        if kind == "start":
            ax.bar(i, v, color=MUTED, width=0.62); cum = v; txt, y = f"{v:+.2f}%", v + 0.08
        elif kind in ("proven", "trial"):
            col = BLUE if kind == "proven" else "white"
            ax.bar(i, v, bottom=cum, color=col, width=0.62, edgecolor=BLUE, hatch=None if kind == "proven" else "///", lw=1.4)
            cum += v; txt, y = f"{v:+.2f}", cum - 0.14
        elif kind in ("sub", "sub2"):
            ax.bar(i, cum, color=BLUE if kind == "sub" else LIGHT_BLUE, width=0.62, edgecolor=BLUE, lw=1.4)
            txt, y = f"{cum:+.2f}%", cum - 0.14 if cum < 0 else cum + 0.08
        elif kind == "unknown":
            ax.bar(i, -0.8, bottom=cum, color="white", width=0.62, edgecolor=MUTED, ls="--", lw=1.4)
            txt, y = "to be\nmeasured", cum - 0.45
        else:
            ax.bar(i, v, color=ORANGE, width=0.62); txt, y = f"{v:+.2f}%", v - 0.14
        ax.text(i, y, txt, ha="center", va="center", fontsize=9.5, color=INK, fontweight="bold" if kind in ("sub", "sub2", "target") else None)
    ax.axhline(0, color=INK2, lw=0.9)
    ax.set_xticks(range(len(steps))); ax.set_xticklabels([s[0] for s in steps], fontsize=9)
    ax.set_ylim(-2.4, 1.45); ax.set_ylabel("energy vs baseline at the same draw (%)")
    ax.set_title("Path to −2%: solid = proven on history; hatched / dashed = to be confirmed in the trial")
    plt.tight_layout(); plt.show()


def chart_mv_ci(sd=1.29, rho=0.44):
    n = np.arange(7, 61)
    ci = 1.96 * sd * np.sqrt((1 + rho) / (1 - rho) / n)
    fig, ax = plt.subplots(figsize=(9, 3.3))
    ax.plot(n, ci, color=BLUE, lw=2.4)
    for k in (14, 30, 45):
        c = 1.96 * sd * np.sqrt((1 + rho) / (1 - rho) / k)
        ax.scatter(k, c, color=BLUE, s=50, zorder=3); ax.text(k + 0.8, c + 0.05, f"{k} days: ±{c:.2f}%", color=INK2, fontsize=9)
    ax.set_xlabel("trial days at the final settings"); ax.set_ylabel("± uncertainty of the\naverage saving (%)")
    ax.set_title("How long a trial must run to measure the saving reliably"); ax.set_ylim(0, 1.8)
    plt.tight_layout(); plt.show()


# ----------------------------------------------------------------- notebook 2: training
def chart_walk_forward():
    fig, ax = plt.subplots(figsize=(11, 2.8))
    days = pd.date_range("2025-10-11", "2026-09-29")
    examples = [pd.Timestamp("2026-03-01"), pd.Timestamp("2026-06-01"), pd.Timestamp("2026-08-31")]
    for i, t in enumerate(examples):
        ax.barh(i, (t - days[0]).days, left=0, color=LIGHT_BLUE, height=0.45)
        ax.barh(i, 1.5, left=(t - days[0]).days, color=ORANGE, height=0.45)
        ax.text((t - days[0]).days + 4, i, f"predict {t:%d %b %Y}", va="center", fontsize=9, color=INK2)
    ax.set_yticks(range(3)); ax.set_yticklabels(["example 1", "example 2", "example 3"])
    ticks = pd.date_range("2025-11-01", "2026-09-01", freq="2MS")
    ax.set_xticks([(t - days[0]).days for t in ticks]); ax.set_xticklabels([f"{t:%b %y}" for t in ticks])
    ax.set_xlim(0, (days[-1] - days[0]).days + 80); ax.invert_yaxis(); ax.grid(axis="y", visible=False)
    ax.set_title("Walk-forward: each day is predicted only from the days before it (blue = training data)")
    plt.tight_layout(); plt.show()


def chart_gas_candidates(D):
    t = pd.read_csv(D.processed / "training_gas_models.csv").set_index("model")
    names = {"QR expanding + ageing": "Quantile regression, all history + ageing",
             "OLS expanding + ageing + conformal": "CHOSEN: regression, all history + ageing + 25% shift",
             "OLS rolling 45d + conformal": "Regression, last 45 days + 25% shift",
             "LightGBM expanding + ageing": "LightGBM (machine learning) + ageing",
             "QR rolling 60d": "Quantile regression, last 60 days",
             "QR rolling 45d": "Quantile regression, last 45 days",
             "QR rolling 30d": "Quantile regression, last 30 days",
             "LightGBM expanding": "LightGBM (machine learning)"}
    t.index = [names.get(i, i) for i in t.index]
    t = t.sort_values("pinball")
    ok = (t.coverage_min >= 0.18) & (t.coverage_max <= 0.32)
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.2), sharey=True)
    y = np.arange(len(t))
    cols = [BLUE if "CHOSEN" in n else (LIGHT_BLUE if k else GRID) for n, k in zip(t.index, ok)]
    ax[0].barh(y, t.pinball, color=cols, height=0.6)
    for i, v in enumerate(t.pinball):
        ax[0].text(v + 0.003, i, f"{v:.3f}", va="center", fontsize=9, color=INK2)
    ax[0].set_yticks(y); ax[0].set_yticklabels(t.index, fontsize=9); ax[0].invert_yaxis()
    ax[0].set_xlim(0.3, 0.47); ax[0].set_xlabel("error score (pinball loss) — lower is better")
    ax[0].set_title("Accuracy")
    ax[1].axvspan(18, 32, color=AQUA, alpha=0.12); ax[1].axvline(25, color=AQUA, lw=1.4, ls=":")
    ax[1].hlines(y, t.coverage_min * 100, t.coverage_max * 100, color=cols, lw=6)
    ax[1].text(25, len(t) - 0.4, "25% = right level", color=INK2, ha="center", fontsize=9)
    ax[1].set_xlim(0, 40); ax[1].set_xlabel("% of days that beat the target (range over both test periods)")
    ax[1].set_title("Realism (grey = target too hard)")
    plt.tight_layout(); plt.show()


def chart_gas_inputs(D):
    t = pd.read_csv(D.processed / "training_gas_final_variants.csv").set_index("variant")
    names = {"winner (no crown temp)": "CHOSEN: draw + barrier + melter boost + age",
             "+ optical (same day, filled)": "+ optical, same day (partly 'sees' the answer)",
             "+ crown thermocouple MC3": "+ crown thermocouple, same day",
             "+ optical (yesterday, filled)": "+ optical, previous day",
             "final inputs without melter boost": "without melter boost",
             "without barrier boost": "without barrier boost"}
    t.index = [names[i] for i in t.index]
    t = t.loc[list(names.values())]
    fig, ax = plt.subplots(figsize=(10, 3.4))
    y = np.arange(len(t))
    cols = [BLUE if "CHOSEN" in n else (ORANGE if "barrier" in n else LIGHT_BLUE) for n in t.index]
    ax.barh(y, t.pinball, color=cols, height=0.6)
    for i, v in enumerate(t.pinball):
        ax.text(v + 0.002, i, f"{v:.3f}", va="center", fontsize=9, color=INK2)
    ax.set_yticks(y); ax.set_yticklabels(t.index, fontsize=9.5); ax.invert_yaxis(); ax.set_xlim(0.3, 0.46)
    ax.set_xlabel("error score — lower is better (average of both test periods)")
    ax.set_title("Which inputs matter: barrier boost is essential; crown temperatures add little")
    plt.tight_layout(); plt.show()


def gas_targets(D, start, end):
    days = D.u.loc[start:end].index
    return rc.walk_forward_gas_targets(D.u, days)


def chart_gas_target_vs_actual(D, tgt):
    a = D.u.loc[tgt.index, "gas_g"]
    below = a <= tgt
    fig, ax = plt.subplots(figsize=(11, 3.8))
    line = tgt.asfreq("D")                                   # gaps (non-usable days) break the line
    ax.plot(line.index, line, color=BLUE, lw=2.2, label="gas target (computed each day from earlier days only)")
    ax.scatter(a.index[~below], a[~below], color=MUTED, s=22, label="actual day used MORE gas than the target")
    ax.scatter(a.index[below], a[below], color=AQUA, s=30, marker="D", label="actual day already beat the target")
    ax.set_ylabel("gas heat (Gcal/day)")
    ax.set_title(f"Gas target vs actual: {100*below.mean():.0f}% of days already beat the target (25% intended)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2, fontsize=9); plt.tight_layout(); plt.show()


def chart_air_follows_heat(D):
    h = D.h.dropna(subset=["sec_air", "ng_scm", "gas_kcal"]).copy()
    h["heat"] = h.gas_kcal / 1e3
    s = h.sample(3000, random_state=1)
    r_vol = smf.ols("sec_air ~ ng_scm", h).fit().rsquared; r_heat = smf.ols("sec_air ~ heat", h).fit().rsquared
    fig, ax = plt.subplots(1, 2, figsize=(12, 3.8), sharey=True)
    ax[0].scatter(s.ng_scm, s.sec_air, s=5, color=MUTED, alpha=0.5)
    ax[0].set_xlabel("gas volume (NG per hour)"); ax[0].set_ylabel("secondary air (per hour)")
    ax[0].set_title(f"Air vs gas VOLUME: weak link (R² {r_vol:.2f})")
    ax[1].scatter(s.heat, s.sec_air, s=5, color=BLUE, alpha=0.5)
    ax[1].set_xlabel("gas HEAT (Mcal per hour)"); ax[1].set_title(f"Air vs gas HEAT: strong link (R² {r_heat:.2f})")
    plt.tight_layout(); plt.show()


def chart_boost_policies(D):
    p = pd.read_csv(D.processed / "training_boost_policies.csv")
    names = {"P1 copy operators (OLS: MB3, draw, cullet)": "Copy operators (regression)",
             "P4 copy operators (LightGBM)": "Copy operators (LightGBM)",
             "P2 integral controller on MB3": "CHOSEN: controller on MB3",
             "P3 hybrid (feedforward + integral)": "Hybrid"}
    p["policy"] = p.policy.map(names)
    fig, ax = plt.subplots(1, 2, figsize=(12, 3.6), sharey=True)
    order = list(names.values()); y = np.arange(len(order))
    for k, (col, ttl, xl) in enumerate([("mb3_abs_error", "Holding MB3 at target", "average MB3 error (°C) — lower is better"),
                                        ("hourly_move", "Calm operation", "average boost change per hour (kWh/h) — lower is calmer")]):
        for j, (fold, c) in enumerate([("Mar-May 2026", LIGHT_BLUE), ("Jun-Aug 2026", BLUE)]):
            v = p[p.fold == fold].set_index("policy").reindex(order)[col]
            ax[k].barh(y + (j - 0.5) * 0.36, v, height=0.34, color=c, label=fold.replace("-", "–"))
        ax[k].set_title(ttl); ax[k].set_xlabel(xl)
    ax[0].set_yticks(y); ax[0].set_yticklabels(order); ax[0].invert_yaxis()
    ax[0].legend(loc="upper center", bbox_to_anchor=(1.0, -0.2), ncol=2)
    plt.tight_layout(); plt.show()


def chart_boost_replay(D, start="2026-08-01", end="2026-08-21"):
    step = rc.boost_step_response(D.h, 12)
    lim = tuple(D.h.bb_kwh.quantile([0.01, 0.99]))
    tgt = float(D.h.mb3_temp.median())
    r = rc.simulate_boost_controller(D.h.loc["2026-06-01":end + " 23:00"], step, tgt, ki=0.1, bb_limits=lim).loc[start:end + " 23:00"]
    fig, ax = plt.subplots(2, 1, figsize=(11, 5.8), sharex=True)
    ax[0].plot(r.index, r.bb_kwh, color=MUTED, lw=1.2, label="actual boost")
    ax[0].plot(r.index, r.bb_rec, color=BLUE, lw=2.2, label="recommended boost")
    ax[0].set_ylabel("barrier boost (kWh/h)"); ax[0].legend(loc="upper left", ncol=2)
    ax[0].set_title("Three weeks of Aug 2026 replayed: less boost, bottom temperature held at its normal level")
    ax[1].plot(r.index, r.mb3_temp, color=MUTED, lw=1.2, label="actual MB3")
    ax[1].plot(r.index, r.mb3_sim, color=BLUE, lw=2.2, label="MB3 with recommended boost (simulated)")
    ax[1].axhline(tgt, color=ORANGE, lw=1.6, ls=":", label=f"target {tgt:.2f} °C (historical median)")
    ax[1].set_ylabel("MB3 (°C)"); ax[1].legend(loc="upper left", ncol=3)
    plt.tight_layout(); plt.show()


def chart_scorecard(D):
    a = pd.read_csv(D.processed / "T4_scorecard.csv", index_col=0)
    s = pd.read_csv(D.processed / "T4_scorecard_sep.csv", index_col=0)
    rows = ["(1) actual", "(3) chosen gas model", "(4) chosen gas + boost controller", "(5) = (4) + air target"]
    labs = ["actual", "+ gas", "+ boost", "+ air\n(final)"]
    col = "draw-adjusted vs baseline % (Model A)"
    fig, ax = plt.subplots(1, 2, figsize=(12, 3.8), sharey=True)
    for k, (t, ttl) in enumerate([(a, "Jun–Aug 2026 (85 days, main test)"), (s, "Sep 2026 (27 days, unseen month)")]):
        v = t.loc[rows, col].values
        ax[k].bar(range(4), v, color=[MUTED, LIGHT_BLUE, LIGHT_BLUE, BLUE], width=0.6)
        for i, x in enumerate(v):
            ax[k].text(i, x + (0.06 if x >= 0 else -0.16), f"{x:+.2f}%", ha="center", fontsize=9.5, color=INK)
        ax[k].axhline(0, color=INK2, lw=0.8); ax[k].axhline(-2, color=ORANGE, lw=1.4, ls=":")
        ax[k].set_xticks(range(4)); ax[k].set_xticklabels(labs); ax[k].set_title(ttl)
    label_right(ax[1], -2, "target −2%", color=ORANGE, va="top")
    ax[0].set_ylabel("energy vs baseline at same draw (%)"); ax[0].set_ylim(-2.3, 2.0)
    plt.tight_layout(); plt.show()
    out = pd.DataFrame({"Jun–Aug: SFC": a.loc[rows, "SFC (kcal/kg)"].values, "Jun–Aug: saving %": a.loc[rows, "saving vs actual %"].values,
                        "Jun–Aug: draw-adjusted %": a.loc[rows, col].values, "Sep: SFC": s.loc[rows, "SFC (kcal/kg)"].values,
                        "Sep: saving %": s.loc[rows, "saving vs actual %"].values, "Sep: draw-adjusted %": s.loc[rows, col].values},
                       index=["actual operation", "+ gas recommender", "+ barrier-boost controller", "+ air target (final)"])
    return out.round(2)


def chart_limits(D, FR, start="2026-06-01", end="2026-08-31"):
    bt = D.bt.loc[start:end]
    qq = D.q.loc[start:end + " 23:45", ["ncv"]].dropna()
    qq = qq[qq.index.normalize().isin(bt.index)]
    gas = bt.gas_rec.reindex(qq.index.normalize()).values
    air_t = pd.Series({day: rc.air_target(D.u, day) for day in bt.index})
    heat = gas * 1e6 / 96
    ng = np.clip(heat / qq.ncv.values, *FR.limits["ng_scm"])
    afr = np.clip(air_t.reindex(qq.index.normalize()).values * qq.ncv.values / 1000, *FR.limits["afr"])
    sim = rc.simulate_boost_controller(D.h.loc[start:end + " 23:00"], rc.boost_step_response(D.h, 12), FR.mb3_target,
                                      ki=0.1, bb_limits=FR.limits["bb_kwh_h"])
    rec = {"ng": ng, "afr": afr, "bb": sim.bb_rec.dropna().values}
    hist = {"ng": D.q.ng_scm, "afr": D.q.afr, "bb": D.h.bb_kwh}
    lims = {"ng": FR.limits["ng_scm"], "afr": FR.limits["afr"], "bb": FR.limits["bb_kwh_h"]}
    fig, ax = plt.subplots(1, 3, figsize=(13, 3.4))
    for a_, k, ttl in [(ax[0], "ng", "NG setpoint (per 15 min)"), (ax[1], "afr", "Air-fuel ratio"), (ax[2], "bb", "Barrier boost (kWh/h)")]:
        rng = (hist[k].quantile(0.002), hist[k].quantile(0.998))
        a_.hist(hist[k].dropna(), bins=50, range=rng, density=True, color=GRID, label="history")
        a_.hist(rec[k], bins=50, range=rng, density=True, color=BLUE, alpha=0.75, label="recommended")
        for v in lims[k]:
            a_.axvline(v, color=ORANGE, lw=1.4, ls="--")
        a_.set_title(ttl); a_.set_yticks([])
    ax[0].legend(loc="upper left"); fig.suptitle("Every recommendation stays inside the historical limits (orange = P1 and P99)",
                                                 x=0.01, ha="left", fontweight="bold", fontsize=12.5)
    plt.tight_layout(); plt.show()


def ng_lookup(FR, ncvs=range(8600, 10500, 200), draws=(52, 55, 58, 61), boost=350, melter=300):
    tab, afr = {}, {}
    for dr in draws:
        v, a = [], []
        for n in ncvs:
            r = FR.recommend(dict(date=pd.Timestamp.today().normalize(), ncv=n, draw_t=dr, cullet_pct=18, optical_prev24h=1574.5,
                                  bb_kwh_last_hour=boost, mb_kwh_last_hour=melter, mb3_now=FR.mb3_target))
            v.append(r.iloc[1, 2]); a.append(r.iloc[3, 2])
        tab[f"draw {dr} t"] = v; afr[f"draw {dr} t"] = a
    idx = [f"NCV {n:,}" for n in ncvs]
    return pd.DataFrame(tab, index=idx).round(1), pd.DataFrame(afr, index=idx).round(2)


def show_recommendation(rec):
    out = rec[["item", "recommended (within limits)", "unit", "historical P1-P99", "clipped?"]].copy()
    out.columns = ["setpoint", "recommended", "unit", "allowed range (history)", "held at limit?"]
    out["recommended"] = out["recommended"].round(2)
    out["held at limit?"] = out["held at limit?"].map({True: "yes", False: "no"})
    return out.set_index("setpoint")


def backtest_inputs(D, FR, inputs, draw_tol=1.5, ncv_tol=150, cullet_tol=1.0):
    r = rc.history_backtest(FR, D.d, D.q, inputs, D.bt, draw_tol=draw_tol, ncv_tol=ncv_tol, cullet_tol=cullet_tol)
    print("Similar days searched:", r["rule"])
    fmt = r["summary"].apply(lambda v: f"{v:,.2f}" if isinstance(v, (float, np.floating)) else v)
    from IPython.display import display
    display(fmt.to_frame("result"))
    print("Setpoints: what operators used on similar days vs what is recommended now")
    display(r["setpoints"].round(2))
    sim = r["similar_days"]
    if len(sim):
        fig, ax = plt.subplots(figsize=(11, 3.8))
        ax.vlines(sim.index, sim.sfc_rec, sim.sfc_actual, color=GRID, lw=1.6)
        ax.plot(sim.index, sim.sfc_actual, "o", color=MUTED, ms=7, label="actual SFC")
        ax.plot(sim.index, sim.sfc_rec, "o", color=BLUE, ms=7, label="with the recommendations")
        bb = r["band_baseline"]
        ax.axhline(bb, color=INK2, lw=1, ls="--"); ax.axhline(bb * 0.98, color=ORANGE, lw=1.4, ls=":")
        label_right(ax, bb, "band baseline"); label_right(ax, bb * 0.98, "target −2%", color=ORANGE)
        lo = min(bb * 0.98, sim.sfc_rec.min(), sim.sfc_actual.min()); hi = max(sim.sfc_rec.max(), sim.sfc_actual.max(), bb)
        ax.set_ylim(lo - 0.15 * (hi - lo), hi + 0.25 * (hi - lo))
        ax.set_ylabel("SFC (kcal/kg)"); ax.set_title(f"{len(sim)} similar days in history: actual vs with the recommendations")
        ax.legend(loc="upper left", ncol=2); plt.tight_layout(); plt.show()
    return r
