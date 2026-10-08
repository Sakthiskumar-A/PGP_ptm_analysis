"""SFC 60 TPD - Melter Setpoint Advisor, DEMO (Databricks App / Dash)

Same screens and inputs as Databricks/app, but with no integration and no secrets:
  plant values  -> replayed from the analytical record Excel (data/Analytical_Record_Creation_fixed_5.xlsx)
                   at a "demo time" picked on the page (what the DCS / NCV feed would have shown then)
  model         -> the released model file (model/sfc_recommender.json) + sfc_model.py, the same logic
                   the MLflow model / serving endpoint runs
  audit         -> kept in memory while the app runs (downloadable as CSV)

The operator still types draw, cullet, optical temperature and the last hour's boosts and clicks
"Get recommendation". "Fill from Excel" puts in the values recorded at the demo time.
"""

import io
import json
import os
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import dash
from dash import Input, Output, State, callback, dcc, html, no_update

from sfc_model import recommend_one

HERE = Path(__file__).resolve().parent
DATA_FILE = HERE / "data" / "Analytical_Record_Creation_fixed_5.xlsx"
MODEL_FILE = HERE / "model" / "sfc_recommender.json"
REPORT_FILE = HERE / "model" / "training_report.json"
DEFAULT_DEMO_TIME = pd.Timestamp(os.getenv("DEMO_TIME", "2026-08-19 10:00"))

KCAL_PER_KWH = 860
VALID_RANGE = {"ncv": (8500, 10500), "opt_temp": (1550, 1600), "mb_kwh": (1, 200), "bb_kwh": (1, 250)}
NCV_SPIKE = 400
OPERATOR_RANGE = {"draw_t": (30, 80), "cullet_pct": (5, 40), "optical_temp": (1500, 1650),
                  "bb_kwh_last_hour": (0, 1000), "mb_kwh_last_hour": (0, 1000)}
MELTER_BOOST_LEVELS = "229 / 306 / 382 kWh/h"      # 57.2 / 76.4 / 95.5 kWh per 15 min
Q15 = timedelta(minutes=15)

# ------------------------------------------------------------------ #
#  Model and data (loaded once)                                       #
# ------------------------------------------------------------------ #
MODEL = json.loads(MODEL_FILE.read_text())
REPORT = json.loads(REPORT_FILE.read_text()) if REPORT_FILE.exists() else {}

COLUMNS = {
    "Timestamps": "ts", "BARRIER BOOSTER-52": "bb_kwh", "MELTER BOOSTER-51": "mb_kwh", "NCV Meter": "ncv",
    "Cullet %": "cullet_pct", "Melter Optical Temperature": "opt_temp",
    "dcs_60_SecondaryAirFlowvalueFTSAFPVDB205DD92": "sec_air", "dcs_60_MelterGasflowvalueFTMGFPVDB202DD92": "ng_scm",
    "dcs_60_ThermocoupleMelterBottom3TCMB3PVDB249DD572": "mb3_temp", "Daily Draw": "draw_kg",
}
NUMERIC = ["bb_kwh", "mb_kwh", "ncv", "cullet_pct", "opt_temp", "sec_air", "ng_scm", "mb3_temp", "draw_kg"]


def load_record() -> tuple[pd.DataFrame, pd.DataFrame]:
    """15-min record with the training cleaning rules; NCV spike filter trailing, as live."""
    raw = pd.read_excel(DATA_FILE, sheet_name="result").rename(columns=COLUMNS)
    raw["ts"] = pd.to_datetime(raw["ts"])
    for c in NUMERIC:
        raw[c] = pd.to_numeric(raw[c], errors="coerce")
    q = raw.groupby("ts")[NUMERIC].mean().sort_index()
    for col, (lo, hi) in VALID_RANGE.items():
        q.loc[q[col].notna() & ~q[col].between(lo, hi), col] = np.nan
    v = q["ncv"].dropna()
    med = v.rolling("2h").median()
    q["ncv_ok"] = v[(v - med).abs() <= NCV_SPIKE].reindex(q.index)
    day_draw = q["draw_kg"].groupby(q.index.normalize()).first()
    week_med = day_draw.rolling(7, center=True, min_periods=3).median()
    fixed = pd.Series(np.where(day_draw > 1.6 * week_med, day_draw / 2, day_draw), index=day_draw.index)
    q["draw_kg"] = fixed.reindex(q.index.normalize()).to_numpy()

    # daily actual SFC (client formula: sum of NG x NCV per 15 min, boosts x 860, / draw)
    f = q.copy()
    for col in ["ng_scm", "bb_kwh", "mb_kwh"]:
        f[col] = f[col].interpolate(limit=4, limit_area="inside")
    g = f.groupby(f.index.normalize())
    both = f.dropna(subset=["ng_scm", "ncv"])
    d = pd.DataFrame({"ng": g["ng_scm"].sum(min_count=1), "ng_cov": g["ng_scm"].apply(lambda s: s.notna().mean()),
                      "ncv_cov": g["ncv"].apply(lambda s: s.notna().mean()),
                      "bb": g["bb_kwh"].sum(min_count=1), "mb": g["mb_kwh"].sum(min_count=1),
                      "draw_kg": g["draw_kg"].first()})
    d["ncv"] = (both["ng_scm"] * both["ncv"]).groupby(both.index.normalize()).sum() / both.groupby(both.index.normalize())["ng_scm"].sum()
    d["sfc"] = (d["ng"] * d["ncv"] + (d["bb"] + d["mb"]) * KCAL_PER_KWH) / d["draw_kg"]
    d["usable"] = (d["ncv_cov"] >= 0.9) & (d["ng_cov"] >= 0.9) & d["draw_kg"].notna()
    return q, d


Q, D = load_record()
FIRST_DAY, LAST_DAY = Q.index.min().normalize(), Q.index.max().normalize()

_audit, _audit_lock = [], threading.Lock()


def last_valid(s: pd.Series):
    s = s.dropna()
    return (float(s.iloc[-1]), s.index[-1]) if len(s) else (None, None)


def snapshot(t: pd.Timestamp) -> dict:
    """What the live feeds would show at demo time t (rows are interval starts; latest complete = t - 15 min)."""
    past = Q.loc[:t - Q15]
    hour = Q.loc[t - 4 * Q15:t - Q15]
    ncv, ncv_ts = last_valid(past["ncv_ok"].iloc[-24:])               # last 6 h
    opt, opt_ts = last_valid(past["opt_temp"].iloc[-12:])             # last 3 h
    full = len(hour) == 4
    day = t.normalize()
    return {
        "t": t, "ncv": ncv, "ncv_ts": ncv_ts,
        "ng_now": float(past["ng_scm"].iloc[-1]) if len(past) else None,
        "air_now": float(past["sec_air"].iloc[-1]) if len(past) else None,
        "mb3_now": float(hour["mb3_temp"].mean()) if full and hour["mb3_temp"].notna().sum() >= 2 else None,
        "excel": {
            "draw_t": float(Q.loc[day:day + timedelta(hours=23, minutes=45), "draw_kg"].dropna().iloc[0]) / 1000
            if Q.loc[day:day + timedelta(hours=23, minutes=45), "draw_kg"].notna().any() else None,
            "cullet_pct": last_valid(past["cullet_pct"].iloc[-96:])[0],
            "optical_temp": opt,
            "bb_kwh_last_hour": float(hour["bb_kwh"].sum()) if full and hour["bb_kwh"].notna().all() else None,
            "mb_kwh_last_hour": float(hour["mb_kwh"].sum()) if full and hour["mb_kwh"].notna().all() else None,
        },
    }


def after(t: pd.Timestamp) -> dict:
    """What the plant actually did after t (from the Excel), to compare with the recommendation."""
    nxt = Q.loc[t:t + 3 * Q15]
    day = D.loc[t.normalize()] if t.normalize() in D.index else None
    return {"ng_next_hour": nxt["ng_scm"].mean(), "air_next_hour": nxt["sec_air"].mean(),
            "bb_next_hour": nxt["bb_kwh"].sum(min_count=4),
            "sfc_day": float(day["sfc"]) if day is not None and bool(day["usable"]) else None}


# ------------------------------------------------------------------ #
#  Formatting helpers (same look as the production app)               #
# ------------------------------------------------------------------ #
NAVY, BLUE, ORANGE, GREY, AMBER, LINE = "#1B3A5C", "#2a78d6", "#eb6834", "#6b7785", "#b45309", "#dde5ec"
CARD = {"background": "white", "border": f"1px solid {LINE}", "borderRadius": "8px", "padding": "16px 18px",
        "boxSizing": "border-box"}
BUTTON = {"background": NAVY, "color": "white", "border": "none", "borderRadius": "4px", "padding": "10px 18px",
          "fontSize": "15px", "fontWeight": 600, "cursor": "pointer"}
BUTTON2 = {**BUTTON, "background": "white", "color": NAVY, "border": f"1px solid {NAVY}"}


def fmt(v, dec=1, unit=""):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "–"
    return f"{v:,.{dec}f}{(' ' + unit) if unit else ''}"


def change_span(value, now, dec):
    if now is None or (isinstance(now, float) and np.isnan(now)) or value is None:
        return ""
    move = value - now
    if abs(move) < 0.5 * 10 ** (-dec):
        return html.Span("no change", style={"color": GREY})
    return html.Span(f"{'▲' if move > 0 else '▼'} {abs(move):,.{dec}f}", style={"color": NAVY, "fontWeight": 600})


def setpoint_tile(title, unit, value, dec, now, lo, hi, at_limit, note=None):
    return html.Div(style={**CARD, "flex": "1 1 200px", "minWidth": "0"}, children=[
        html.Div(title, style={"fontSize": "13px", "color": GREY, "fontWeight": 600, "textTransform": "uppercase",
                               "letterSpacing": ".03em"}),
        html.Div([html.Span(fmt(value, dec), style={"fontSize": "34px", "fontWeight": 700, "color": NAVY}),
                  html.Span(f" {unit}", style={"fontSize": "13px", "color": GREY})], style={"margin": "6px 0 4px"}),
        html.Div(["now ", html.B(fmt(now, dec)), "  ", change_span(value, now, dec)], style={"fontSize": "13px", "color": "#333"}),
        html.Div(f"historical range {fmt(lo, dec)} – {fmt(hi, dec)}", style={"fontSize": "12px", "color": GREY, "marginTop": "4px"}),
        html.Div("held at historical limit", style={"fontSize": "12px", "color": AMBER, "fontWeight": 600, "marginTop": "4px"})
        if at_limit else None,
        html.Div(note, style={"fontSize": "12px", "color": GREY, "marginTop": "4px"}) if note else None,
    ])


def warn_box(items, title="Please check before applying"):
    if not items:
        return ""
    return html.Div(style={**CARD, "borderColor": "#f3d1a8", "background": "#fffaf3"}, children=[
        html.Div(title, style={"fontWeight": 700, "color": AMBER, "marginBottom": "4px"}),
        html.Ul([html.Li(w) for w in items], style={"margin": "0", "paddingLeft": "20px", "color": AMBER, "fontSize": "13px"})])


def line_fig(title, ytitle):
    fig = go.Figure()
    fig.update_layout(title=dict(text=title, x=0, font=dict(size=14, color=NAVY)), height=260,
                      margin=dict(l=55, r=10, t=36, b=30), plot_bgcolor="white", paper_bgcolor="white",
                      legend=dict(orientation="h", y=-0.18, x=0, font=dict(size=11)),
                      xaxis=dict(showgrid=False, linecolor=LINE),
                      yaxis=dict(title=ytitle, gridcolor="#f0f2f5", zeroline=False))
    return fig


def table(headers, rows, aligns=None):
    th = {"textAlign": "left", "padding": "7px 8px", "fontSize": "12px", "color": "white", "background": NAVY}
    td = {"padding": "7px 8px", "borderBottom": f"1px solid {LINE}", "fontSize": "13px"}
    aligns = aligns or ["left"] * len(headers)
    return html.Div(style={"overflowX": "auto"}, children=html.Table(
        style={"width": "100%", "borderCollapse": "collapse"},
        children=[html.Thead(html.Tr([html.Th(h, style={**th, "textAlign": a}) for h, a in zip(headers, aligns)])),
                  html.Tbody([html.Tr([html.Td(c, style={**td, "textAlign": a}) for c, a in zip(r, aligns)]) for r in rows])]))


def sgn(v, dec=3) -> str:
    """'+ 0.495' / '− 0.771' for formulas."""
    return f"{'+' if v >= 0 else '−'} {abs(v):.{dec}f}"


def section(title, *children, sub=None):
    return html.Div(style={**CARD, "marginBottom": "12px"}, children=[
        html.H3(title, style={"margin": "0 0 4px", "color": NAVY, "fontSize": "17px"}),
        html.Div(sub, style={"fontSize": "13px", "color": GREY, "marginBottom": "10px"}) if sub else None, *children])


def demo_time(date, hhmm) -> pd.Timestamp:
    t = pd.Timestamp(f"{str(date)[:10]} {hhmm}")
    return min(max(t, FIRST_DAY + timedelta(hours=6)), Q.index.max())


# ------------------------------------------------------------------ #
#  Layout                                                             #
# ------------------------------------------------------------------ #
def num_input(id_, label, help_id=None, help_text=""):
    return html.Div(style={"marginBottom": "12px"}, children=[
        html.Label(label, htmlFor=id_, style={"fontWeight": 600, "fontSize": "14px", "display": "block"}),
        dcc.Input(id=id_, type="number", step="any", debounce=True,
                  style={"width": "100%", "padding": "8px 10px", "fontSize": "15px", "border": "1px solid #bbb",
                         "borderRadius": "4px", "boxSizing": "border-box"}),
        html.Div(help_text, id=help_id, style={"fontSize": "12px", "color": GREY, "marginTop": "2px"}) if help_id else
        html.Div(help_text, style={"fontSize": "12px", "color": GREY, "marginTop": "2px"}),
    ])


TAB_STYLE = {"padding": "10px 18px", "fontWeight": 600, "color": GREY, "borderBottom": f"1px solid {LINE}"}
TAB_SELECTED = {**TAB_STYLE, "color": NAVY, "borderTop": f"3px solid {NAVY}", "background": "white"}
TIMES = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 15, 30, 45)]

demo_bar = html.Div(style={**CARD, "display": "flex", "gap": "14px", "alignItems": "center", "flexWrap": "wrap",
                           "background": "#eef3f8", "marginBottom": "12px"}, children=[
    html.Div([html.B("DEMO", style={"background": ORANGE, "color": "white", "padding": "2px 8px", "borderRadius": "4px",
                                    "fontSize": "12px", "marginRight": "8px"}),
              html.Span("Plant values are replayed from the Excel record at the demo time below.",
                        style={"fontSize": "13px", "color": "#333"})], style={"flex": "1 1 280px"}),
    html.Div([html.Label("Demo date", style={"fontSize": "12px", "color": GREY, "display": "block"}),
              dcc.DatePickerSingle(id="demo-date", date=DEFAULT_DEMO_TIME.date(), min_date_allowed=FIRST_DAY.date(),
                                   max_date_allowed=LAST_DAY.date(), display_format="DD MMM YYYY")]),
    html.Div([html.Label("Demo time", style={"fontSize": "12px", "color": GREY, "display": "block"}),
              dcc.Dropdown(id="demo-time", options=TIMES, value=DEFAULT_DEMO_TIME.strftime("%H:%M"), clearable=False,
                           style={"width": "110px"})]),
])

recommendation_tab = html.Div(style={"paddingTop": "16px"}, children=[
    html.Div(style={"display": "flex", "gap": "16px", "flexWrap": "wrap", "alignItems": "flex-start"}, children=[
        html.Div(style={**CARD, "flex": "1 1 260px", "maxWidth": "340px", "minWidth": "0"}, children=[
            html.H3("Operator inputs", style={"margin": "0 0 12px", "color": NAVY, "fontSize": "17px"}),
            num_input("in-draw", "Draw today (t/day)", "hint-draw_t"),
            num_input("in-cullet", "Cullet (%)", "hint-cullet_pct"),
            num_input("in-optical", "Optical crown temperature (°C)", "hint-optical_temp"),
            num_input("in-bb", "Barrier boost, last hour (kWh/h)", "hint-bb_kwh_last_hour"),
            num_input("in-mb", "Melter boost, last hour (kWh/h)", "hint-mb_kwh_last_hour"),
            html.Button("Fill from Excel", id="fill-btn", n_clicks=0, style={**BUTTON2, "width": "100%", "marginBottom": "8px"}),
            html.Button("Get recommendation", id="rec-btn", n_clicks=0, style={**BUTTON, "width": "100%"}),
        ]),
        html.Div(style={"flex": "1 1 640px", "minWidth": "0"}, children=[
            dcc.Loading(type="circle", color=NAVY, children=html.Div(id="rec-area", children=[
                html.Div(style={**CARD}, children=html.Div(
                    "Enter the operator values (or click Fill from Excel) and click Get recommendation.",
                    style={"color": GREY, "fontSize": "14px"}))])),
        ]),
    ]),
    html.H3("Plant values at the demo time (from the Excel)", style={"color": NAVY, "margin": "22px 0 8px", "fontSize": "17px"}),
    html.Div(id="live-values", style={"display": "flex", "gap": "12px", "flexWrap": "wrap"}),
    html.Div(style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "marginTop": "12px"}, children=[
        html.Div(dcc.Graph(id=g, config={"displayModeBar": False}, responsive=True, style={"height": "260px"}),
                 style={**CARD, "flex": "1 1 360px", "minWidth": "0", "padding": "8px"})
        for g in ("ng-chart", "mb3-chart")]),
])

setpoints_tab = html.Div(style={"paddingTop": "16px"}, children=[
    html.Div(style={"display": "flex", "gap": "16px", "flexWrap": "wrap", "alignItems": "flex-start"}, children=[
        html.Div(style={**CARD, "flex": "1 1 300px", "maxWidth": "420px", "minWidth": "0"}, children=[
            html.H3("Set points applied in the plant", style={"margin": "0 0 4px", "color": NAVY, "fontSize": "17px"}),
            html.Div("Enter the values actually set on the DCS for the recommendation shown on the right.",
                     style={"fontSize": "13px", "color": GREY, "marginBottom": "12px"}),
            num_input("set-ng", "NG flow set (per 15 min, DCS unit)", help_text="value entered for both ports"),
            num_input("set-air", "Secondary air set (per 15 min, DCS unit)"),
            html.Div(id="set-afr", style={"fontSize": "13px", "color": GREY, "margin": "-4px 0 12px"}),
            num_input("set-bb", "Barrier boost set (kWh/h)"),
            html.Div(style={"marginBottom": "12px"}, children=[
                html.Label("Operator name / ID", htmlFor="set-operator", style={"fontWeight": 600, "fontSize": "14px", "display": "block"}),
                dcc.Input(id="set-operator", type="text", style={"width": "100%", "padding": "8px 10px", "fontSize": "15px",
                                                                 "border": "1px solid #bbb", "borderRadius": "4px", "boxSizing": "border-box"})]),
            html.Div(style={"marginBottom": "14px"}, children=[
                html.Label("Remarks", htmlFor="set-remarks", style={"fontWeight": 600, "fontSize": "14px", "display": "block"}),
                dcc.Textarea(id="set-remarks", placeholder="e.g. why a value differs from the recommendation",
                             style={"width": "100%", "height": "70px", "padding": "8px 10px", "fontSize": "14px",
                                    "border": "1px solid #bbb", "borderRadius": "4px", "boxSizing": "border-box"})]),
            html.Button("Save to audit", id="save-btn", n_clicks=0, style={**BUTTON, "width": "100%"}),
            html.Div(id="save-status", style={"fontSize": "13px", "marginTop": "10px"}),
        ]),
        html.Div(id="set-reference", style={"flex": "1 1 420px", "minWidth": "0"}),
    ]),
    html.Div(style={**CARD, "marginTop": "16px"}, children=[
        html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "flexWrap": "wrap",
                        "gap": "8px", "marginBottom": "8px"}, children=[
            html.H3("Audit table (demo: kept in memory)", style={"margin": "0", "color": NAVY, "fontSize": "17px"}),
            html.Button("Download CSV", id="dl-btn", n_clicks=0, style={**BUTTON2, "padding": "6px 12px", "fontSize": "13px"})]),
        html.Div(id="audit-table"),
        dcc.Download(id="audit-download"),
    ]),
])

app = dash.Dash(__name__, title="SFC 60 TPD Setpoint Advisor (demo)")
server = app.server

app.layout = html.Div(
    style={"fontFamily": "Segoe UI, sans-serif", "padding": "20px 16px", "maxWidth": "1320px", "margin": "auto",
           "background": "#f5f7fa", "minHeight": "100vh", "color": "#16202a", "overflowX": "hidden"},
    children=[
        dcc.Store(id="rec-store"),
        dcc.Store(id="audit-version", data=0),
        html.Div(style={"marginBottom": "12px"}, children=[
            html.H1("60 TPD Melter — SFC Setpoint Advisor", style={"color": NAVY, "margin": "0", "fontSize": "26px"}),
            html.Div("Recommended NG, secondary air and barrier boost from plant and operator values. "
                     "Advisory: the operator decides.", style={"color": GREY, "fontSize": "13px"}),
        ]),
        demo_bar,
        dcc.Tabs(id="tabs", value="rec", children=[
            dcc.Tab(label="Recommendation", value="rec", style=TAB_STYLE, selected_style=TAB_SELECTED, children=recommendation_tab),
            dcc.Tab(label="Record applied set points", value="set", style=TAB_STYLE, selected_style=TAB_SELECTED, children=setpoints_tab),
            dcc.Tab(label="Model details", value="model", style=TAB_STYLE, selected_style=TAB_SELECTED,
                    children=html.Div(id="model-tab", style={"paddingTop": "16px"})),
        ]),
        html.Div(f"Demo · model {MODEL.get('model_version', MODEL['trained_until'])} (trained until {MODEL['trained_until']}) · "
                 f"data: {DATA_FILE.name}, {Q.index.min():%d %b %Y} – {Q.index.max():%d %b %Y}",
                 style={"color": GREY, "fontSize": "12px", "marginTop": "14px"}),
    ],
)


# ------------------------------------------------------------------ #
#  Callbacks: recommendation tab                                      #
# ------------------------------------------------------------------ #
HINT_KEYS = ["draw_t", "cullet_pct", "optical_temp", "bb_kwh_last_hour", "mb_kwh_last_hour"]
HINT_DEC = {"draw_t": 1, "cullet_pct": 0, "optical_temp": 0, "bb_kwh_last_hour": 0, "mb_kwh_last_hour": 0}


@callback(
    Output("live-values", "children"), Output("ng-chart", "figure"), Output("mb3-chart", "figure"),
    *[Output(f"hint-{k}", "children") for k in HINT_KEYS],
    Input("demo-date", "date"), Input("demo-time", "value"), Input("rec-store", "data"),
)
def show_plant(date, hhmm, rec):
    t = demo_time(date, hhmm)
    sn = snapshot(t)

    def live(label, value, sub):
        return html.Div(style={**CARD, "flex": "1 1 150px", "padding": "10px 14px", "minWidth": "0"}, children=[
            html.Div(label, style={"fontSize": "12px", "color": GREY}),
            html.Div(value, style={"fontSize": "20px", "fontWeight": 600, "color": "#16202a"}),
            html.Div(sub, style={"fontSize": "11px", "color": GREY})])

    afr_now = sn["air_now"] / sn["ng_now"] if sn["ng_now"] and sn["air_now"] else None
    live_values = [
        live("NCV (kcal/SCM)", fmt(sn["ncv"], 0), f"latest valid {sn['ncv_ts']:%H:%M}" if sn["ncv_ts"] is not None else "no valid reading"),
        live("NG flow now", fmt(sn["ng_now"], 1), f"15-min value {t - Q15:%H:%M}"),
        live("Secondary air now", fmt(sn["air_now"], 0), f"15-min value {t - Q15:%H:%M}"),
        live("AFR now", fmt(afr_now, 2), "air ÷ NG"),
        live("MB3 bottom (°C)", fmt(sn["mb3_now"], 1), "mean of last hour"),
    ]

    win = Q.loc[t - timedelta(hours=6):t + timedelta(hours=3)]
    before, later = win.loc[:t - Q15], win.loc[t - Q15:]
    ng = line_fig(f"NG flow around {t:%d %b %H:%M}", "per 15 min (DCS unit)")
    ng.add_trace(go.Scatter(x=before.index, y=before["ng_scm"], mode="lines+markers", name="before demo time",
                            line=dict(color=BLUE, width=2.5), marker=dict(size=4)))
    ng.add_trace(go.Scatter(x=later.index, y=later["ng_scm"], mode="lines", name="what the plant did after (Excel)",
                            line=dict(color="#9aa5b1", width=2, dash="dot")))
    mb3 = line_fig(f"MB3 bottom temperature around {t:%d %b %H:%M}", "°C")
    mb3.add_trace(go.Scatter(x=before.index, y=before["mb3_temp"], mode="lines", name="before demo time",
                             line=dict(color=BLUE, width=2.5)))
    mb3.add_trace(go.Scatter(x=later.index, y=later["mb3_temp"], mode="lines", name="after (Excel)",
                             line=dict(color="#9aa5b1", width=2, dash="dot")))
    for fig in (ng, mb3):
        fig.add_vline(x=t, line=dict(color=GREY, width=1))
    if rec and rec.get("demo_time") == str(t):
        ng.add_hline(y=rec["ng_setpoint"], line=dict(color=ORANGE, dash="dash", width=2),
                     annotation_text=f"recommended {rec['ng_setpoint']:.1f}", annotation_position="top left")
        mb3.add_hline(y=rec["mb3_target"], line=dict(color=ORANGE, dash="dash", width=2),
                      annotation_text=f"target {rec['mb3_target']:.1f}", annotation_position="top left")
    hints = [f"Excel at demo time: {fmt(sn['excel'][k], HINT_DEC[k])}" for k in HINT_KEYS]
    return live_values, ng, mb3, *hints


@callback(
    *[Output(i, "value") for i in ["in-draw", "in-cullet", "in-optical", "in-bb", "in-mb"]],
    Input("fill-btn", "n_clicks"), State("demo-date", "date"), State("demo-time", "value"),
    prevent_initial_call=True,
)
def fill_from_excel(_n, date, hhmm):
    ex = snapshot(demo_time(date, hhmm))["excel"]
    return tuple(None if ex[k] is None else round(ex[k], HINT_DEC[k] if k != "draw_t" else 2) for k in HINT_KEYS)


@callback(
    Output("rec-area", "children"), Output("rec-store", "data"), Output("audit-version", "data", allow_duplicate=True),
    Input("rec-btn", "n_clicks"),
    State("demo-date", "date"), State("demo-time", "value"),
    State("in-draw", "value"), State("in-cullet", "value"), State("in-optical", "value"),
    State("in-bb", "value"), State("in-mb", "value"), State("audit-version", "data"),
    prevent_initial_call=True,
)
def make_recommendation(_n, date, hhmm, draw, cullet, optical, bb, mb, audit_v):
    t = demo_time(date, hhmm)
    sn = snapshot(t)
    warnings, blockers = [], []
    if sn["ncv"] is None:
        blockers.append("no valid NCV in the last 6 h of the record")
    elif sn["ncv_ts"] < t - timedelta(minutes=45):
        warnings.append(f"NCV is old: last valid value {sn['ncv_ts']:%d %b %H:%M}, used anyway")
    if sn["mb3_now"] is None:
        blockers.append("no MB3 data in the last hour of the record")

    op = {"draw_t": draw, "cullet_pct": cullet, "optical_temp": optical, "bb_kwh_last_hour": bb, "mb_kwh_last_hour": mb}
    labels = {"draw_t": "draw", "cullet_pct": "cullet %", "optical_temp": "optical crown temperature",
              "bb_kwh_last_hour": "barrier boost last hour", "mb_kwh_last_hour": "melter boost last hour"}
    for k, v in op.items():
        if v is None:
            if k != "optical_temp":
                blockers.append(f"enter {labels[k]}")
            continue
        lo, hi = OPERATOR_RANGE[k]
        if not lo <= v <= hi:
            (warnings if k == "optical_temp" else blockers).append(f"{labels[k]} = {v} looks wrong (expected {lo}–{hi})")
    if blockers:
        return [html.Div(style={**CARD}, children=[
            html.Div("No recommendation", style={"fontWeight": 700, "color": AMBER, "fontSize": "17px", "marginBottom": "6px"}),
            html.Ul([html.Li(b) for b in blockers], style={"margin": "0", "paddingLeft": "20px", "color": AMBER})]),
            html.Div(warn_box(warnings), style={"marginTop": "12px"})], None, no_update

    record = {"timestamp": t.strftime("%Y-%m-%d %H:%M"), "ncv": sn["ncv"], "draw_t": float(draw), "cullet_pct": float(cullet),
              "bb_kwh_last_hour": float(bb), "mb_kwh_last_hour": float(mb), "mb3_now": round(sn["mb3_now"], 3)}
    for k, v in {"optical_temp": optical, "ng_now": sn["ng_now"], "air_now": sn["air_now"]}.items():
        if v is not None and not pd.isna(v):
            record[k] = round(float(v), 3)
    rec = recommend_one(MODEL, record)                      # same call the serving endpoint makes
    warnings += [f for f in rec["flags"].split(" | ") if f]
    store = {k: (None if isinstance(v, float) and np.isnan(v) else (bool(v) if isinstance(v, np.bool_) else v))
             for k, v in rec.items()}
    store.update(recommendation_id=uuid.uuid4().hex, recommendation_for=t.strftime("%Y-%m-%d %H:%M"), demo_time=str(t),
                 inputs=record, all_flags=" | ".join(warnings))
    add_audit(store, "RECOMMENDATION")

    a = after(t)
    da = rec["draw_adjusted_pct"]
    area = [
        html.Div(style={"marginBottom": "8px"}, children=[
            html.Span(f"Recommendation for {t:%d %b %Y %H:%M}", style={"fontWeight": 700, "color": NAVY, "fontSize": "17px"}),
            html.Span("  ·  NG and air: set in minute 15–20 of the next reversal cycle (one NG value for both ports). "
                      "Barrier boost: for the next hour. Then record what you set in the second tab.",
                      style={"color": GREY, "fontSize": "13px"})]),
        html.Div(style={"display": "flex", "gap": "12px", "flexWrap": "wrap"}, children=[
            setpoint_tile("NG flow", "per 15 min (DCS unit)", rec["ng_setpoint"], 1, sn["ng_now"],
                          rec["ng_lo"], rec["ng_hi"], rec["ng_at_limit"]),
            setpoint_tile("Secondary air", "per 15 min (DCS unit)", rec["air_setpoint"], 0, sn["air_now"],
                          rec["air_lo"], rec["air_hi"], rec["air_at_limit"]),
            setpoint_tile("Air-fuel ratio", "", rec["afr_setpoint"], 2,
                          sn["air_now"] / sn["ng_now"] if sn["ng_now"] and sn["air_now"] else None,
                          rec["afr_lo"], rec["afr_hi"], rec["afr_at_limit"]),
            setpoint_tile("Barrier boost, next hour", "kWh/h", rec["bb_setpoint_kwh_h"], 0, bb,
                          rec["bb_lo"], rec["bb_hi"], rec["bb_at_limit"], note=f"MB3 target {rec['mb3_target']:,.1f} °C"),
        ]),
        html.Div(style={**CARD, "marginTop": "12px", "fontSize": "14px"}, children=[
            html.Span("Expected SFC today at the gas target: ", style={"color": GREY}),
            html.B(fmt(rec["sfc_expected"], 0, "kcal/kg"), style={"color": NAVY, "fontSize": "16px"}),
            html.Span(f"   ·   baseline at this draw and cullet {fmt(rec['sfc_baseline_at_draw'], 0)}"
                      + (f" ({da:+.1f}%)" if da is not None and not pd.isna(da) else "")
                      + (f"   ·   band {rec['draw_band']} t: baseline {fmt(rec['band_baseline_sfc'], 0)}, "
                         f"target {fmt(rec['band_target_sfc'], 0)}" if rec["draw_band"] else ""),
                      style={"color": GREY}),
            html.Div(f"Daily gas-heat target {rec['gas_target_gcal_day']:.2f} Gcal/day · NCV {sn['ncv']:,.0f} kcal/SCM · "
                     f"MB3 {sn['mb3_now']:.1f} °C", style={"color": GREY, "fontSize": "12px", "marginTop": "4px"}),
        ]),
        html.Div(style={**CARD, "marginTop": "12px", "background": "#f8fafc"}, children=[
            html.Div("Demo comparison: what the plant actually did after this time (from the Excel)",
                     style={"fontWeight": 700, "color": NAVY, "marginBottom": "6px", "fontSize": "14px"}),
            table(["", "Recommended", "Actual (Excel)"], [
                ["NG flow, next hour mean (per 15 min)", fmt(rec["ng_setpoint"], 1), fmt(a["ng_next_hour"], 1)],
                ["Secondary air, next hour mean (per 15 min)", fmt(rec["air_setpoint"], 0), fmt(a["air_next_hour"], 0)],
                ["Barrier boost, next hour (kWh/h)", fmt(rec["bb_setpoint_kwh_h"], 0), fmt(a["bb_next_hour"], 0)],
                ["SFC of the day (kcal/kg)", fmt(rec["sfc_expected"], 0) + " expected", fmt(a["sfc_day"], 0) + " actual"],
            ], ["left", "right", "right"]),
        ]),
        html.Div(warn_box(warnings), style={"marginTop": "12px"}),
    ]
    return area, store, (audit_v or 0) + 1


# ------------------------------------------------------------------ #
#  Callbacks: record applied set points + audit                       #
# ------------------------------------------------------------------ #
AUDIT_FIELDS = ["event_time", "event_type", "recommendation_id", "operator_name", "recommendation_for",
                "ncv", "draw_t", "cullet_pct", "optical_temp", "bb_kwh_last_hour", "mb_kwh_last_hour", "mb3_now",
                "ng_now", "air_now", "ng_recommended", "air_recommended", "afr_recommended", "bb_recommended_kwh_h",
                "gas_target_gcal_day", "sfc_expected", "flags", "ng_set", "air_set", "afr_set", "bb_set_kwh_h", "remarks",
                "model_version"]


def add_audit(rec: dict, event_type: str, **extra) -> None:
    inp = rec.get("inputs", {})
    row = {"event_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "event_type": event_type,
           "recommendation_id": rec["recommendation_id"], "recommendation_for": rec["recommendation_for"],
           **{k: inp.get(k) for k in ["ncv", "draw_t", "cullet_pct", "optical_temp", "bb_kwh_last_hour", "mb_kwh_last_hour",
                                      "mb3_now", "ng_now", "air_now"]},
           "ng_recommended": rec["ng_setpoint"], "air_recommended": rec["air_setpoint"], "afr_recommended": rec["afr_setpoint"],
           "bb_recommended_kwh_h": rec["bb_setpoint_kwh_h"], "gas_target_gcal_day": rec["gas_target_gcal_day"],
           "sfc_expected": rec["sfc_expected"], "flags": rec.get("all_flags", ""), "model_version": rec["model_version"], **extra}
    with _audit_lock:
        _audit.append(row)


@callback(Output("set-reference", "children"), Output("set-afr", "children"),
          Input("rec-store", "data"), Input("set-ng", "value"), Input("set-air", "value"), Input("set-bb", "value"))
def show_reference(rec, ng_set, air_set, bb_set):
    afr_set = air_set / ng_set if ng_set and air_set else None
    afr_txt = f"Air-fuel ratio set: {afr_set:.2f}" if afr_set else ""
    if not rec:
        return html.Div(style={**CARD}, children=html.Div(
            "No recommendation yet. Get one in the Recommendation tab first.", style={"color": GREY})), afr_txt
    rows = [("NG flow (per 15 min)", rec["ng_setpoint"], ng_set, 1), ("Secondary air (per 15 min)", rec["air_setpoint"], air_set, 0),
            ("Air-fuel ratio", rec["afr_setpoint"], afr_set, 2), ("Barrier boost (kWh/h)", rec["bb_setpoint_kwh_h"], bb_set, 0)]
    return html.Div(style={**CARD}, children=[
        html.Div(f"Recommendation of {pd.Timestamp(rec['recommendation_for']):%d %b %Y %H:%M}",
                 style={"fontWeight": 700, "color": NAVY, "fontSize": "16px"}),
        html.Div(f"id {rec['recommendation_id'][:8]} · model {rec['model_version']}",
                 style={"color": GREY, "fontSize": "12px", "marginBottom": "10px"}),
        table(["Set point", "Recommended", "Set by operator", "Difference"],
              [[n, html.B(fmt(r, d)), fmt(v, d), change_span(v, r, d) if v is not None else "–"] for n, r, v, d in rows])]), afr_txt


@callback(Output("save-status", "children"), Output("set-ng", "value"), Output("set-air", "value"),
          Output("set-bb", "value"), Output("set-remarks", "value"), Output("audit-version", "data", allow_duplicate=True),
          Input("save-btn", "n_clicks"),
          State("rec-store", "data"), State("set-ng", "value"), State("set-air", "value"), State("set-bb", "value"),
          State("set-operator", "value"), State("set-remarks", "value"), State("audit-version", "data"),
          prevent_initial_call=True)
def save_setpoints(_n, rec, ng_set, air_set, bb_set, operator, remarks, audit_v):
    keep = (no_update,) * 5
    err = {"color": AMBER}
    if not rec:
        return html.Span("Get a recommendation first (Recommendation tab).", style=err), *keep
    if ng_set is None and air_set is None and bb_set is None:
        return html.Span("Enter at least one set point.", style=err), *keep
    if not (operator or "").strip():
        return html.Span("Enter the operator name / ID.", style=err), *keep
    for name, v, lo, hi in [("NG", ng_set, rec["ng_lo"], rec["ng_hi"]), ("secondary air", air_set, rec["air_lo"], rec["air_hi"]),
                            ("barrier boost", bb_set, 0, 1000)]:
        if v is not None and not (0.5 * lo <= v <= 1.5 * hi):
            return html.Span(f"{name} = {v} looks like a typing error; please check.", style=err), *keep
    add_audit(rec, "OPERATOR_SET", operator_name=operator.strip(), remarks=(remarks or "").strip(), ng_set=ng_set,
              air_set=air_set, bb_set_kwh_h=bb_set, afr_set=(air_set / ng_set) if ng_set and air_set else None)
    msg = (f"Saved for the recommendation of {pd.Timestamp(rec['recommendation_for']):%d %b %H:%M}: "
           f"NG {fmt(ng_set, 1)}, air {fmt(air_set, 0)}, boost {fmt(bb_set, 0)} kWh/h")
    return html.Span(msg, style={"color": "#155d3f"}), None, None, None, "", (audit_v or 0) + 1


def audit_frame() -> pd.DataFrame:
    with _audit_lock:
        return pd.DataFrame(list(_audit), columns=AUDIT_FIELDS)


@callback(Output("audit-table", "children"), Input("audit-version", "data"), Input("tabs", "value"))
def show_audit(_v, _tab):
    a = audit_frame()
    if a.empty:
        return html.Div("No rows yet. Each Get recommendation and each Save adds a row.", style={"color": GREY, "fontSize": "13px"})
    a = a.iloc[::-1].head(20)
    cols = [("event_time", "time", None), ("event_type", "event", None), ("recommendation_for", "for", None),
            ("operator_name", "operator", None), ("ng_recommended", "NG rec", 1), ("ng_set", "NG set", 1),
            ("air_recommended", "air rec", 0), ("air_set", "air set", 0), ("bb_recommended_kwh_h", "boost rec", 0),
            ("bb_set_kwh_h", "boost set", 0), ("remarks", "remarks", None)]
    rows = [[fmt(r[c], d) if d is not None else ("" if pd.isna(r[c]) else str(r[c])) for c, _, d in cols] for _, r in a.iterrows()]
    return table([h for _, h, _ in cols], rows)


@callback(Output("audit-download", "data"), Input("dl-btn", "n_clicks"), prevent_initial_call=True)
def download_audit(_n):
    buf = io.StringIO()
    audit_frame().to_csv(buf, index=False)
    return dict(content=buf.getvalue(), filename=f"sfc_setpoint_audit_demo_{datetime.now():%Y%m%d_%H%M}.csv")


# ------------------------------------------------------------------ #
#  Model details tab                                                  #
# ------------------------------------------------------------------ #
@callback(Output("model-tab", "children"), Input("rec-store", "data"))
def model_details(rec):
    m, gas, air, boost, L = MODEL, MODEL["gas"], MODEL["air"], MODEL["boost"], MODEL["limits"]
    c = gas["coefficients"]
    data = m.get("data", {})

    overview = section("The model", html.Div(style={"display": "flex", "gap": "12px", "flexWrap": "wrap"}, children=[
        html.Div(style={"flex": "1 1 160px", "minWidth": "0"}, children=[
            html.Div(k, style={"fontSize": "12px", "color": GREY}), html.Div(v, style={"fontSize": "17px", "fontWeight": 600})])
        for k, v in [("model version", m.get("model_version", "–")), ("trained until", m["trained_until"]),
                     ("usable training days", str(m["n_training_days"])),
                     ("data", f"{str(data.get('from', ''))[:10]} – {str(data.get('to', ''))[:10]}"),
                     ("release checks", "all PASS" if REPORT.get("passed") else "–")]]),
        html.P("Two recommenders work together. The gas recommender sets NG and secondary air so the furnace gets the "
               "heat an efficient day at this draw needs, whatever the NCV. The barrier-boost recommender keeps the "
               "bottom temperature MB3 at its usual level. Every setpoint stays inside the furnace's own historical range.",
               style={"fontSize": "14px", "margin": "12px 0 0"}))

    steps = section("How a recommendation is calculated", table(["Step", "Formula", "Numbers in this model"], [
        ["1. Daily gas-heat target (Gcal/day)",
         "a + b·draw + c·barrier boost + d·melter boost + e·furnace age + shift",
         f"{c['Intercept']:.2f} {sgn(c['draw_t'])}·draw {sgn(c['bb_g'])}·barrier boost (Gcal/day) "
         f"{sgn(c['mb_g'])}·melter boost (Gcal/day) {sgn(c['age_m'])}·age (months) {sgn(gas['conformal_shift'])}"],
        ["2. NG setpoint (per 15 min)", "target ÷ 96 intervals ÷ latest NCV", "exact NCV compensation every cycle"],
        ["3. Secondary air (per 15 min)", "air-per-Mcal target × gas heat", f"{air['air_per_mcal']:.4f} SCM per Mcal"],
        ["4. Air-fuel ratio", "secondary air ÷ NG", ""],
        ["5. Barrier boost, next hour (kWh/h)", "last hour + Ki × (MB3 target − MB3 now) ÷ gain",
         f"Ki {boost['ki']}, MB3 target {boost['mb3_target']:.2f} °C, gain {boost['mb3_gain_degC_per_kwh_h'] * 100:.2f} °C per +100 kWh/h"],
        ["6. Limits", "each setpoint held inside its historical P1–P99", "see table below"],
    ]), sub="Furnace age is counted in months from 1 Sep 2025. The shift sets the target at the level the most efficient "
            "quarter of the last 45 days reached.")

    worked = section("Worked example: your last recommendation",
                     html.Div("Click Get recommendation in the first tab to see the calculation step by step.",
                              style={"color": GREY, "fontSize": "13px"}))
    if rec:
        i = rec["inputs"]
        age = (pd.Timestamp(i["timestamp"]).normalize() - pd.Timestamp(gas["age_origin"])).days / gas["days_per_month"]
        bb_g = i["bb_kwh_last_hour"] * 24 * KCAL_PER_KWH / 1e6
        mb_g = i["mb_kwh_last_hour"] * 24 * KCAL_PER_KWH / 1e6
        heat = rec["gas_target_gcal_day"] * 1e6 / 96
        worked = section(f"Worked example: recommendation for {pd.Timestamp(rec['recommendation_for']):%d %b %Y %H:%M}", table(
            ["Quantity", "Calculation", "Value"], [
                ["Barrier boost as daily heat", f"{i['bb_kwh_last_hour']:.0f} kWh/h × 24 × 860 ÷ 10⁶", f"{bb_g:.3f} Gcal/day"],
                ["Melter boost as daily heat", f"{i['mb_kwh_last_hour']:.0f} kWh/h × 24 × 860 ÷ 10⁶", f"{mb_g:.3f} Gcal/day"],
                ["Furnace age", f"days since {gas['age_origin']} ÷ 30.44", f"{age:.2f} months"],
                ["Gas-heat target", f"{c['Intercept']:.2f} {sgn(c['draw_t'])}×{i['draw_t']:.2f} {sgn(c['bb_g'])}×{bb_g:.3f} "
                                    f"{sgn(c['mb_g'])}×{mb_g:.3f} {sgn(c['age_m'])}×{age:.2f} {sgn(gas['conformal_shift'])}",
                 f"{rec['gas_target_gcal_day']:.3f} Gcal/day"],
                ["Heat per 15 min", "target × 10⁶ ÷ 96", f"{heat:,.0f} kcal"],
                ["NG setpoint", f"{heat:,.0f} ÷ NCV {i['ncv']:,.0f}", f"{rec['ng_raw']:.2f}" + (" → held at limit " + f"{rec['ng_setpoint']:.2f}" if rec["ng_at_limit"] else "")],
                ["Secondary air", f"{air['air_per_mcal']:.4f} × {rec['ng_setpoint']:.2f} × {i['ncv']:,.0f} ÷ 1000",
                 f"{rec['air_raw']:.1f}" + (f" → held at limit {rec['air_setpoint']:.1f}" if rec["air_at_limit"] else "")],
                ["Air-fuel ratio", "air ÷ NG", f"{rec['afr_setpoint']:.3f}"],
                ["Barrier boost", f"{i['bb_kwh_last_hour']:.0f} + {boost['ki']} × ({boost['mb3_target']:.2f} − {i['mb3_now']:.2f}) "
                                  f"÷ {boost['mb3_gain_degC_per_kwh_h']:.4f}",
                 f"{rec['bb_raw_kwh_h']:.1f} kWh/h" + (f" → held at limit {rec['bb_setpoint_kwh_h']:.1f}" if rec["bb_at_limit"] else "")],
                ["Expected SFC", "(gas target + boosts × 24 × 860 ÷ 10⁶) ÷ draw", f"{rec['sfc_expected']:,.1f} kcal/kg"],
            ], ["left", "left", "right"]))

    labels = {"ng_scm": "NG setpoint (per 15 min)", "sec_air": "Secondary air (per 15 min)", "afr": "Air-fuel ratio",
              "bb_kwh_h": "Barrier boost (kWh/h)", "mb3_temp": "MB3 bottom temperature (°C)",
              "opt_temp": "Optical crown temperature (°C)", "ncv": "NCV accepted (kcal/SCM)", "draw_t": "Draw (t/day)",
              "gas_day_gcal": "Daily gas heat (Gcal/day, warning only)"}
    limits = section("Historical limits (P1–P99 of the furnace's own history)",
                     table(["Item", "Low (P1)", "High (P99)"],
                           [[labels.get(k, k), fmt(v[0], 2), fmt(v[1], 2)] for k, v in L.items()], ["left", "right", "right"]),
                     sub="Setpoints are held inside these limits. Inputs outside them give a warning.")

    checks = section("Release checks (run by the training job before a model is used)",
                     table(["Check", "Value", "Result"],
                           [[r["check"], fmt(float(r["value"]), 4), r["result"]] for r in REPORT.get("checks", [])],
                           ["left", "right", "center"]))

    a = m["mv"]["model_a"]
    mv = section("How savings are measured", table(["Yardstick", "Definition"], [
        ["Client baseline", f"{m['mv']['client_baseline_sfc']:,.1f} kcal/kg (1 Sep 2025 – 31 Jul 2026); target "
                            f"{m['mv']['client_target_sfc']:,.1f} (−2%)"],
        ["Draw-adjusted", f"expected energy = {a['Intercept']:.2f} + {a['draw_t']:.3f}·draw + {a['cullet_pct']:.3f}·cullet "
                          "(Gcal/day, fitted on the baseline period); saving = actual ÷ expected − 1"],
        ["Per draw band", ", ".join(f"{k} t: {v:,.0f}" for k, v in m["mv"]["band_baseline_sfc"].items())
         + " kcal/kg baseline; target −2% each"],
    ]))
    return [overview, steps, worked, limits, checks, mv]


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("DATABRICKS_APP_PORT", "8050")), debug=False)
