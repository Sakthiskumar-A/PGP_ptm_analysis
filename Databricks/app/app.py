"""SFC 60 TPD - Melter Setpoint Advisor (Databricks App / Dash)

What the operator sees: the NG flow, secondary air, air-fuel ratio and barrier boost to set now,
computed by the registered SFC recommender from the live plant values.

Data sources
  DCS (1-min)  -> prod_pgp_mfg.cantier.vw_dcs60tpd_live (SQL warehouse): NG flow, secondary air, MB3, MC3
  NCV          -> Azure Blob MQTT JSON sensor feed (UEMS), latest valid value
  Operator     -> draw (t/day), cullet %, optical crown temperature; barrier / melter boost of the last
                  hour until the boost feed is connected (BOOST_QUERY). "Get recommendation" runs the model.
  Audit        -> AUDIT_TABLE (Delta, created if missing): one RECOMMENDATION row per click and one
                  OPERATOR_SET row per saved "set points applied" entry (second tab), linked by recommendation_id
  Model        -> Model Serving endpoint (SERVING_ENDPOINT) or, while there is none, the Unity Catalog
                  model loaded by alias (UC_MODEL_NAME@MODEL_ALIAS). Both run the same sfc_pyfunc.py.

The 15-min training record is the mean of the 1-min DCS values, so "NG now" / "air now" here are the
means of the last 15 one-minute values (same unit as the recommendation), and MB3 is the mean of the
last 60 minutes (the boost controller is hourly).
"""

import json
import os
import threading
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import dash
from dash import Input, Output, State, callback, dcc, html, no_update

# ------------------------------------------------------------------ #
#  Configuration (app.yaml env)                                       #
# ------------------------------------------------------------------ #
WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID", "c5b898c9dc1668ef")
DCS_VIEW = os.getenv("DCS_VIEW", "prod_pgp_mfg.cantier.vw_dcs60tpd_live")
DCS_COLUMNS = {
    "dcs_60_DateTime_IST": "ts",
    "dcs_60_MelterGasflowvalueFTMGFPVDB202DD92": "ng",
    "dcs_60_SecondaryAirFlowvalueFTSAFPVDB205DD92": "air",
    "dcs_60_ThermocoupleMelterBottom3TCMB3PVDB249DD572": "mb3",
    "dcs_60_ThermocoupleMelterCrown3TCMC3PVDB249DD202": "mc3",
}
DCS_MINUTES = 180                                   # 1-min rows read per refresh (chart window)

SERVING_ENDPOINT = os.getenv("SERVING_ENDPOINT", "").strip()
UC_MODEL_NAME = os.getenv("UC_MODEL_NAME", "prod_pgp_mfg.cantier.sfc_60tpd_recommender")
MODEL_ALIAS = os.getenv("MODEL_ALIAS", "champion")
MODEL_SOURCE = "endpoint" if SERVING_ENDPOINT else "uc"
MODEL_RELOAD_SECONDS = 1800                         # uc mode: re-read the alias every 30 min

BOOST_QUERY = os.getenv("BOOST_QUERY", "").strip()  # SQL -> one row: ts, bb_kwh_last_hour, mb_kwh_last_hour
AUDIT_TABLE = os.getenv("AUDIT_TABLE", "").strip()  # catalog.schema.table; created on first write

AZURE_CONN_STR = os.getenv("AZURE_BLOB_CONN_STR", "")
AZURE_CONTAINER = "pgldatalake"
NCV_SENSOR_ID = "19261"                             # KSB_UEM_15MIN_TAG_STREAM1_INFERIOR_CV_NCV_Meter
NCV_PARAMETER_ID = "3742"
NCV_MINUTES = 180

REFRESH_SECONDS = int(os.getenv("REFRESH_SECONDS", "60"))
NCV_RANGE, NCV_SPIKE = (8500, 10500), 400           # same validity rules as training
MAX_AGE_MIN = {"dcs": 10, "ncv": 30, "boost": 120}
OPTICAL_TC_OFFSET, OPTICAL_TC_TOL = 7.6, 5.0        # optical ~ MC3 + 7.6 degC (finding F4)
OPERATOR_RANGE = {"draw_t": (30, 80), "cullet_pct": (5, 40), "optical_temp": (1500, 1650),
                  "bb_kwh_last_hour": (0, 1000), "mb_kwh_last_hour": (0, 1000)}
MELTER_BOOST_LEVELS = "229 / 306 / 382 kWh/h"      # 57.2 / 76.4 / 95.5 kWh per 15 min

IST = timedelta(hours=5, minutes=30)


def now_ist() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None) + IST


# ------------------------------------------------------------------ #
#  Databricks access                                                  #
# ------------------------------------------------------------------ #
_ws = None


def ws():
    global _ws
    if _ws is None:
        from databricks.sdk import WorkspaceClient
        _ws = WorkspaceClient()
    return _ws


def run_sql(statement: str, parameters=None) -> pd.DataFrame:
    """SQL through the warehouse (statement execution API, native App OAuth)."""
    w = ws()
    resp = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID, statement=statement, wait_timeout="30s", parameters=parameters)
    deadline = time.time() + 60
    while resp.status and resp.status.state and resp.status.state.value in ("PENDING", "RUNNING") and time.time() < deadline:
        time.sleep(2)                               # warehouse starting up
        resp = w.statement_execution.get_statement(resp.statement_id)
    state = resp.status.state.value if resp.status and resp.status.state else "UNKNOWN"
    if state != "SUCCEEDED":
        msg = resp.status.error.message if resp.status and resp.status.error else state
        raise RuntimeError(f"SQL failed: {msg}")
    if not resp.manifest or not resp.manifest.schema or not resp.manifest.schema.columns:
        return pd.DataFrame()
    cols = [c.name for c in resp.manifest.schema.columns]
    rows = (resp.result.data_array if resp.result else None) or []
    return pd.DataFrame(rows, columns=cols)


_cache, _cache_lock = {}, threading.Lock()


def cached(key: str, ttl: float, fn):
    """Several operators share one app process: read each source at most once per `ttl` seconds."""
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    value = fn()
    with _cache_lock:
        _cache[key] = (time.time(), value)
    return value


def to_ist_naive(s: pd.Series) -> pd.Series:
    t = pd.to_datetime(s, errors="coerce")
    if getattr(t.dt, "tz", None) is not None:
        t = t.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    return t


# ------------------------------------------------------------------ #
#  Live data                                                          #
# ------------------------------------------------------------------ #
def fetch_dcs() -> pd.DataFrame:
    """Last DCS_MINUTES one-minute rows, oldest first, implausible values -> NaN."""
    cols = ",\n        ".join(DCS_COLUMNS)
    df = run_sql(f"""
    SELECT
        {cols}
    FROM {DCS_VIEW}
    ORDER BY dcs_60_DateTime_IST DESC
    LIMIT {DCS_MINUTES}
    """).rename(columns=DCS_COLUMNS)
    if df.empty:
        return pd.DataFrame(columns=list(DCS_COLUMNS.values()))
    df["ts"] = to_ist_naive(df["ts"])
    for c in ["ng", "air", "mb3", "mc3"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["ts"]).sort_values("ts").drop_duplicates("ts")
    df.loc[df["ng"] <= 0, "ng"] = np.nan
    df.loc[df["air"] <= 0, "air"] = np.nan
    df.loc[~df["mb3"].between(1200, 1450), "mb3"] = np.nan
    df.loc[~df["mc3"].between(1400, 1700), "mc3"] = np.nan          # crown TC validity (training rule)
    return df.reset_index(drop=True)


def fetch_ncv(minutes: int = NCV_MINUTES) -> pd.DataFrame:
    """Recent NCV readings from the UEMS MQTT blobs (as MQTT_Data_Function), oldest first."""
    from azure.storage.blob import BlobServiceClient
    low_wm = int(time.time()) - minutes * 60
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    start = now_utc - timedelta(minutes=minutes)
    dates = pd.date_range(start.strftime("%Y-%m-%d"), now_utc.strftime("%Y-%m-%d")).strftime("%d-%m-%Y").tolist()
    ctr = BlobServiceClient.from_connection_string(AZURE_CONN_STR).get_container_client(AZURE_CONTAINER)
    records = []
    for d in dates:
        for blob in ctr.list_blobs(name_starts_with=f"PROD_UEMS/MQTT/MQTT_Data/load_date={d}/{NCV_SENSOR_ID}"):
            if blob.last_modified.timestamp() <= low_wm:
                continue
            raw = ctr.get_blob_client(blob.name).download_blob().readall().decode("utf-8")
            for line in raw.strip().splitlines():
                try:
                    obj = json.loads(line)
                    ts, val = obj.get("ts"), (obj.get("data") or {}).get(NCV_PARAMETER_ID)
                    if ts is not None and val is not None:
                        records.append({"ts": datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None) + IST,
                                        "ncv": float(val)})
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
    if not records:
        return pd.DataFrame(columns=["ts", "ncv"])
    return pd.DataFrame(records).sort_values("ts").drop_duplicates("ts").reset_index(drop=True)


_last_good_ncv = {"ncv": None, "ts": None}


def latest_valid_ncv(df: pd.DataFrame):
    """Training rules, trailing: 8,500-10,500 kcal/SCM and within 400 of the ~2 h median.
    Falls back to the last valid NCV seen by this app when the window has none."""
    rejected = 0
    if len(df):
        s = df.set_index("ts")["ncv"].sort_index()
        in_range = s[s.between(*NCV_RANGE)]
        med = in_range.rolling("2h").median()
        ok = in_range[(in_range - med).abs() <= NCV_SPIKE]
        rejected = int(len(s) - len(ok))
        if len(ok):
            _last_good_ncv.update(ncv=float(ok.iloc[-1]), ts=ok.index[-1])
    return _last_good_ncv["ncv"], _last_good_ncv["ts"], rejected


def fetch_boost_last_hour():
    """Barrier / melter boost of the last hour from the DB, once BOOST_QUERY is configured.
    The query must return one row with columns ts, bb_kwh_last_hour, mb_kwh_last_hour (kWh in that hour)."""
    if not BOOST_QUERY:
        return None
    df = run_sql(BOOST_QUERY)
    if df.empty:
        return None
    r = df.iloc[0]
    return {"ts": to_ist_naive(pd.Series([r["ts"]])).iloc[0],
            "bb_kwh_last_hour": float(r["bb_kwh_last_hour"]), "mb_kwh_last_hour": float(r["mb_kwh_last_hour"])}


def live_snapshot() -> dict:
    """Everything read from the plant, each source independently (one failing source doesn't hide the others)."""
    snap = {"errors": [], "dcs": None, "ncv_df": None, "boost": None}
    try:
        snap["dcs"] = cached("dcs", 50, fetch_dcs)
    except Exception as exc:
        traceback.print_exc()
        snap["errors"].append(f"DCS: {exc}")
    try:
        snap["ncv_df"] = cached("ncv", 50, fetch_ncv)
    except Exception as exc:
        traceback.print_exc()
        snap["errors"].append(f"NCV feed: {exc}")
        snap["ncv_df"] = pd.DataFrame(columns=["ts", "ncv"])
    try:
        snap["boost"] = cached("boost", 50, fetch_boost_last_hour)
    except Exception as exc:
        traceback.print_exc()
        snap["errors"].append(f"boost query: {exc}")
    return snap


def dcs_summary(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {}
    last = df["ts"].max()
    w15 = df[df["ts"] > last - timedelta(minutes=15)]
    w60 = df[df["ts"] > last - timedelta(minutes=60)]
    return {"dcs_ts": last, "ng_now": w15["ng"].mean(), "air_now": w15["air"].mean(),
            "mb3_now": w60["mb3"].mean(), "mc3_now": w60["mc3"].mean(), "mb3_n": int(w60["mb3"].count())}


# ------------------------------------------------------------------ #
#  Recommender: serving endpoint, or the UC model by alias            #
# ------------------------------------------------------------------ #
_model = {"pyfunc": None, "loaded_at": 0.0, "lock": threading.Lock()}


def _uc_model():
    with _model["lock"]:
        if _model["pyfunc"] is None or time.time() - _model["loaded_at"] > MODEL_RELOAD_SECONDS:
            import mlflow
            if "MLFLOW_TRACKING_URI" not in os.environ:
                mlflow.set_tracking_uri("databricks")
            mlflow.set_registry_uri(os.getenv("MLFLOW_REGISTRY_URI", "databricks-uc"))
            _model["pyfunc"] = mlflow.pyfunc.load_model(f"models:/{UC_MODEL_NAME}@{MODEL_ALIAS}")
            _model["loaded_at"] = time.time()
        return _model["pyfunc"]


def get_recommendation(record: dict) -> dict:
    if MODEL_SOURCE == "endpoint":
        resp = ws().serving_endpoints.query(name=SERVING_ENDPOINT, dataframe_records=[record])
        return dict(resp.predictions[0])
    out = _uc_model().predict(pd.DataFrame([record]))
    return json.loads(out.to_json(orient="records"))[0]              # plain JSON types, as from the endpoint


def model_label() -> str:
    return f"endpoint {SERVING_ENDPOINT}" if MODEL_SOURCE == "endpoint" else f"{UC_MODEL_NAME}@{MODEL_ALIAS}"


# ------------------------------------------------------------------ #
#  Audit table (append-only, created on first use)                    #
# ------------------------------------------------------------------ #
# One row per event:
#   RECOMMENDATION  - written when the operator clicks "Get recommendation" (inputs + recommendation)
#   OPERATOR_SET    - written when the operator saves what was actually set in the plant
#                     (same recommendation columns + the operator's set points), linked by recommendation_id
AUDIT_COLUMNS = [
    ("audit_id", "STRING"), ("recommendation_id", "STRING"), ("event_type", "STRING"), ("event_time", "TIMESTAMP"),
    ("app_user", "STRING"), ("operator_name", "STRING"),
    ("recommendation_for", "TIMESTAMP"), ("model_version", "STRING"), ("trained_until", "STRING"), ("model_source", "STRING"),
    # inputs used
    ("ncv", "DOUBLE"), ("draw_t", "DOUBLE"), ("cullet_pct", "DOUBLE"), ("optical_temp", "DOUBLE"),
    ("bb_kwh_last_hour", "DOUBLE"), ("mb_kwh_last_hour", "DOUBLE"), ("boost_source", "STRING"),
    ("mb3_now", "DOUBLE"), ("ng_now", "DOUBLE"), ("air_now", "DOUBLE"),
    # recommendation
    ("ng_recommended", "DOUBLE"), ("air_recommended", "DOUBLE"), ("afr_recommended", "DOUBLE"),
    ("bb_recommended_kwh_h", "DOUBLE"), ("gas_target_gcal_day", "DOUBLE"), ("sfc_expected", "DOUBLE"),
    ("draw_adjusted_pct", "DOUBLE"), ("flags", "STRING"),
    # operator set points (OPERATOR_SET rows only)
    ("ng_set", "DOUBLE"), ("air_set", "DOUBLE"), ("afr_set", "DOUBLE"), ("bb_set_kwh_h", "DOUBLE"), ("remarks", "STRING"),
]
_audit_ready = False


def ensure_audit_table() -> None:
    global _audit_ready
    if not _audit_ready:
        cols = ",\n            ".join(f"{n} {t}" for n, t in AUDIT_COLUMNS)
        run_sql(f"CREATE TABLE IF NOT EXISTS {AUDIT_TABLE} (\n            {cols}\n        )"
                " COMMENT 'SFC 60 TPD setpoint advisor: recommendations and operator set points (append-only)'")
        _audit_ready = True


def write_audit(row: dict) -> None:
    from databricks.sdk.service.sql import StatementParameterListItem as P
    ensure_audit_table()
    params = []
    for name, typ in AUDIT_COLUMNS:
        v = row.get(name)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            params.append(P(name=name, value=None, type=typ))
        elif typ == "DOUBLE":
            params.append(P(name=name, value=repr(float(v)), type=typ))
        else:
            params.append(P(name=name, value=str(v), type=typ))
    names = [n for n, _ in AUDIT_COLUMNS]
    run_sql(f"INSERT INTO {AUDIT_TABLE} ({', '.join(names)}) VALUES ({', '.join(':' + n for n in names)})", params)


def audit_row(rec: dict, event_type: str, **extra) -> dict:
    """Audit row from the stored recommendation (rec-store) plus event-specific fields."""
    inp = rec.get("inputs", {})
    return {
        "audit_id": uuid.uuid4().hex, "recommendation_id": rec["recommendation_id"], "event_type": event_type,
        "event_time": now_ist().strftime("%Y-%m-%d %H:%M:%S"), "app_user": current_user(),
        "recommendation_for": rec["recommendation_for"] + ":00", "model_version": rec.get("model_version"),
        "trained_until": rec.get("trained_until"), "model_source": rec.get("model_source"),
        **{k: inp.get(k) for k in ["ncv", "draw_t", "cullet_pct", "optical_temp", "bb_kwh_last_hour", "mb_kwh_last_hour",
                                   "mb3_now", "ng_now", "air_now"]},
        "boost_source": rec.get("boost_source"),
        "ng_recommended": rec.get("ng_setpoint"), "air_recommended": rec.get("air_setpoint"),
        "afr_recommended": rec.get("afr_setpoint"), "bb_recommended_kwh_h": rec.get("bb_setpoint_kwh_h"),
        "gas_target_gcal_day": rec.get("gas_target_gcal_day"), "sfc_expected": rec.get("sfc_expected"),
        "draw_adjusted_pct": rec.get("draw_adjusted_pct"), "flags": rec.get("all_flags", ""),
        **extra,
    }


def current_user() -> str:
    """Signed-in user (Databricks Apps forwards it in the request headers)."""
    try:
        from flask import request
        return request.headers.get("X-Forwarded-Email") or request.headers.get("X-Forwarded-Preferred-Username") or ""
    except Exception:
        return ""


# ------------------------------------------------------------------ #
#  Formatting helpers                                                 #
# ------------------------------------------------------------------ #
NAVY, BLUE, ORANGE, GREY, AMBER, GREEN, LINE = "#1B3A5C", "#2a78d6", "#eb6834", "#6b7785", "#b45309", "#1baf7a", "#dde5ec"
CARD = {"background": "white", "border": f"1px solid {LINE}", "borderRadius": "8px", "padding": "16px 18px",
        "boxSizing": "border-box"}
BUTTON = {"background": NAVY, "color": "white", "border": "none", "borderRadius": "4px", "padding": "10px 18px",
          "fontSize": "15px", "fontWeight": 600, "cursor": "pointer"}


def fmt(v, dec=1, unit=""):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "–"
    return f"{v:,.{dec}f}{(' ' + unit) if unit else ''}"


def age_min(ts) -> float:
    if ts is None or pd.isna(ts):
        return float("inf")
    return (now_ist() - pd.Timestamp(ts).to_pydatetime()).total_seconds() / 60


def chip(text, ok=True):
    return html.Span(text, style={"background": "#e8f5ee" if ok else "#fdf0e3", "color": "#155d3f" if ok else AMBER,
                                  "border": f"1px solid {'#bfe3cf' if ok else '#f3d1a8'}", "borderRadius": "12px",
                                  "padding": "3px 10px", "fontSize": "12px", "marginLeft": "6px", "whiteSpace": "nowrap"})


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


def empty_fig(msg=""):
    fig = go.Figure()
    fig.update_layout(height=260, margin=dict(l=50, r=10, t=36, b=30), plot_bgcolor="white", paper_bgcolor="white",
                      annotations=[dict(text=msg, showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper",
                                        font=dict(color=GREY))] if msg else [],
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig


def line_fig(title, ytitle):
    fig = go.Figure()
    fig.update_layout(title=dict(text=title, x=0, font=dict(size=14, color=NAVY)), height=260,
                      margin=dict(l=55, r=10, t=36, b=30), plot_bgcolor="white", paper_bgcolor="white",
                      legend=dict(orientation="h", y=-0.18, x=0, font=dict(size=11)),
                      xaxis=dict(showgrid=False, linecolor=LINE),
                      yaxis=dict(title=ytitle, gridcolor="#f0f2f5", zeroline=False))
    return fig


# ------------------------------------------------------------------ #
#  Live state shared by the callbacks                                 #
# ------------------------------------------------------------------ #
def plant_state() -> dict:
    """Live values + data-quality warnings / blockers (sources cached for 50 s)."""
    snap = live_snapshot()
    s = dcs_summary(snap["dcs"])
    ncv, ncv_ts, ncv_rejected = latest_valid_ncv(snap["ncv_df"])
    st = {"dcs": snap["dcs"], "s": s, "ncv": ncv, "ncv_ts": ncv_ts, "boost": snap["boost"],
          "dcs_age": age_min(s.get("dcs_ts")), "ncv_age": age_min(ncv_ts),
          "warnings": list(snap["errors"]), "blockers": []}
    if not s:
        st["blockers"].append("no DCS data")
    elif st["dcs_age"] > MAX_AGE_MIN["dcs"]:
        st["warnings"].append(f"DCS data is old: last reading {s['dcs_ts']:%d %b %H:%M} ({st['dcs_age']:.0f} min ago)")
    if ncv is None:
        st["blockers"].append("no valid NCV")
    elif st["ncv_age"] > MAX_AGE_MIN["ncv"]:
        st["warnings"].append(f"NCV is old: last valid value {ncv_ts:%d %b %H:%M} ({st['ncv_age']:.0f} min ago), used anyway")
    if ncv_rejected:
        st["warnings"].append(f"{ncv_rejected} NCV reading(s) in the last {NCV_MINUTES // 60} h rejected (zero, out of range or spike)")
    if s and (s.get("mb3_n", 0) < 30 or pd.isna(s.get("mb3_now"))):
        st["blockers"].append("MB3: fewer than 30 valid 1-min readings in the last hour")
    if st["boost"] and age_min(st["boost"]["ts"]) > MAX_AGE_MIN["boost"]:
        st["warnings"].append(f"boost data is old: {st['boost']['ts']:%d %b %H:%M}")
    return st


# ------------------------------------------------------------------ #
#  Layout                                                             #
# ------------------------------------------------------------------ #
def num_input(id_, label, help_text, persist=True):
    return html.Div(style={"marginBottom": "12px"}, children=[
        html.Label(label, htmlFor=id_, style={"fontWeight": 600, "fontSize": "14px", "display": "block"}),
        dcc.Input(id=id_, type="number", step="any", debounce=True, persistence=persist, persistence_type="local",
                  style={"width": "100%", "padding": "8px 10px", "fontSize": "15px", "border": "1px solid #bbb",
                         "borderRadius": "4px", "boxSizing": "border-box"}),
        html.Div(help_text, style={"fontSize": "12px", "color": GREY, "marginTop": "2px"}),
    ])


TAB_STYLE = {"padding": "10px 18px", "fontWeight": 600, "color": GREY, "borderBottom": f"1px solid {LINE}"}
TAB_SELECTED = {**TAB_STYLE, "color": NAVY, "borderTop": f"3px solid {NAVY}", "background": "white"}

recommendation_tab = html.Div(style={"paddingTop": "16px"}, children=[
    html.Div(style={"display": "flex", "gap": "16px", "flexWrap": "wrap", "alignItems": "flex-start"}, children=[
        # operator inputs
        html.Div(style={**CARD, "flex": "1 1 260px", "maxWidth": "340px", "minWidth": "0"}, children=[
            html.H3("Operator inputs", style={"margin": "0 0 12px", "color": NAVY, "fontSize": "17px"}),
            num_input("in-draw", "Draw today (t/day)", "expected SAP draw for today"),
            num_input("in-cullet", "Cullet (%)", "today's batch cullet %"),
            num_input("in-optical", "Optical crown temperature (°C)", "latest hourly pyrometer reading (check only)"),
            html.Div(id="boost-inputs", children=[
                num_input("in-bb", "Barrier boost, last hour (kWh/h)", "until the boost feed is connected"),
                num_input("in-mb", "Melter boost, last hour (kWh/h)", f"usual levels {MELTER_BOOST_LEVELS}"),
            ]),
            html.Div(id="boost-db", style={"fontSize": "13px", "color": GREY, "marginBottom": "12px"}),
            html.Button("Get recommendation", id="rec-btn", n_clicks=0, style={**BUTTON, "width": "100%"}),
        ]),
        # recommendation
        html.Div(style={"flex": "1 1 640px", "minWidth": "0"}, children=[
            dcc.Loading(type="circle", color=NAVY, children=html.Div(id="rec-area", children=[
                html.Div(style={**CARD}, children=html.Div(
                    "Enter today's values and click Get recommendation.", style={"color": GREY, "fontSize": "14px"}))])),
        ]),
    ]),
    html.H3("Live plant values", style={"color": NAVY, "margin": "22px 0 8px", "fontSize": "17px"}),
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
            num_input("set-ng", "NG flow set (per 15 min, DCS unit)", "value entered for both ports", persist=False),
            num_input("set-air", "Secondary air set (per 15 min, DCS unit)", "", persist=False),
            html.Div(id="set-afr", style={"fontSize": "13px", "color": GREY, "margin": "-4px 0 12px"}),
            num_input("set-bb", "Barrier boost set (kWh/h)", "", persist=False),
            html.Div(style={"marginBottom": "12px"}, children=[
                html.Label("Operator name / ID", htmlFor="set-operator", style={"fontWeight": 600, "fontSize": "14px", "display": "block"}),
                dcc.Input(id="set-operator", type="text", persistence=True, persistence_type="local",
                          style={"width": "100%", "padding": "8px 10px", "fontSize": "15px", "border": "1px solid #bbb",
                                 "borderRadius": "4px", "boxSizing": "border-box"})]),
            html.Div(style={"marginBottom": "14px"}, children=[
                html.Label("Remarks", htmlFor="set-remarks", style={"fontWeight": 600, "fontSize": "14px", "display": "block"}),
                dcc.Textarea(id="set-remarks", placeholder="e.g. why a value differs from the recommendation",
                             style={"width": "100%", "height": "70px", "padding": "8px 10px", "fontSize": "14px",
                                    "border": "1px solid #bbb", "borderRadius": "4px", "boxSizing": "border-box"})]),
            html.Button("Save to audit", id="save-btn", n_clicks=0, disabled=not AUDIT_TABLE,
                        style={**BUTTON, "width": "100%", "opacity": 1 if AUDIT_TABLE else 0.5,
                               "cursor": "pointer" if AUDIT_TABLE else "not-allowed"}),
            html.Div(id="save-status", style={"fontSize": "13px", "marginTop": "10px"},
                     children="" if AUDIT_TABLE else "Saving is off: AUDIT_TABLE is not set in app.yaml."),
        ]),
        html.Div(id="set-reference", style={"flex": "1 1 420px", "minWidth": "0"}),
    ]),
])

app = dash.Dash(__name__, title="SFC 60 TPD Setpoint Advisor")
server = app.server

app.layout = html.Div(
    style={"fontFamily": "Segoe UI, sans-serif", "padding": "20px 16px", "maxWidth": "1320px", "margin": "auto",
           "background": "#f5f7fa", "minHeight": "100vh", "color": "#16202a"},
    children=[
        dcc.Interval(id="tick", interval=REFRESH_SECONDS * 1000, n_intervals=0),
        dcc.Store(id="rec-store", storage_type="session"),
        html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "flex-end",
                        "flexWrap": "wrap", "gap": "8px", "marginBottom": "12px"}, children=[
            html.Div([
                html.H1("60 TPD Melter — SFC Setpoint Advisor", style={"color": NAVY, "margin": "0", "fontSize": "26px"}),
                html.Div("Recommended NG, secondary air and barrier boost from live DCS, NCV and operator values. "
                         "Advisory: the operator decides.", style={"color": GREY, "fontSize": "13px"}),
            ]),
            html.Div(id="status-chips", style={"textAlign": "right", "maxWidth": "100%", "lineHeight": "2"}),
        ]),
        dcc.Tabs(id="tabs", value="rec", children=[
            dcc.Tab(label="Recommendation", value="rec", style=TAB_STYLE, selected_style=TAB_SELECTED,
                    children=recommendation_tab),
            dcc.Tab(label="Record applied set points", value="set", style=TAB_STYLE, selected_style=TAB_SELECTED,
                    children=setpoints_tab),
        ]),
        html.Div(id="footer", style={"color": GREY, "fontSize": "12px", "marginTop": "14px"}),
    ],
)


# ------------------------------------------------------------------ #
#  Callbacks                                                          #
# ------------------------------------------------------------------ #
@callback(
    Output("status-chips", "children"), Output("live-values", "children"), Output("ng-chart", "figure"),
    Output("mb3-chart", "figure"), Output("boost-inputs", "style"), Output("boost-db", "children"), Output("footer", "children"),
    Input("tick", "n_intervals"), Input("rec-store", "data"),
)
def refresh_live(_n, rec):
    """Every REFRESH_SECONDS: live values, charts and data status. Does not recommend."""
    st = plant_state()
    s, dcs, ncv, ncv_ts = st["s"], st["dcs"], st["ncv"], st["ncv_ts"]
    chips = [chip(f"DCS {s['dcs_ts']:%H:%M}" if s else "DCS –", ok=bool(s) and st["dcs_age"] <= MAX_AGE_MIN["dcs"]),
             chip(f"NCV {ncv_ts:%H:%M}" if ncv_ts is not None else "NCV –",
                  ok=ncv is not None and st["ncv_age"] <= MAX_AGE_MIN["ncv"]),
             chip(f"model {rec['trained_until']}" if rec else "model –", ok=rec is not None),
             html.Div(f"live data refreshed {now_ist():%d %b %Y %H:%M:%S} IST", style={"fontSize": "12px", "color": GREY})]

    def live(label, value, sub):
        return html.Div(style={**CARD, "flex": "1 1 150px", "padding": "10px 14px", "minWidth": "0"}, children=[
            html.Div(label, style={"fontSize": "12px", "color": GREY}),
            html.Div(value, style={"fontSize": "20px", "fontWeight": 600, "color": "#16202a"}),
            html.Div(sub, style={"fontSize": "11px", "color": GREY})])

    afr_now = (s["air_now"] / s["ng_now"]) if s.get("ng_now") else None
    live_values = [
        live("NCV (kcal/SCM)", fmt(ncv, 0), f"latest valid {ncv_ts:%H:%M}" if ncv_ts is not None else "no valid reading"),
        live("NG flow now", fmt(s.get("ng_now"), 1), "mean of last 15 min"),
        live("Secondary air now", fmt(s.get("air_now"), 0), "mean of last 15 min"),
        live("AFR now", fmt(afr_now, 2), "air ÷ NG"),
        live("MB3 bottom (°C)", fmt(s.get("mb3_now"), 1), "mean of last 60 min"),
        live("MC3 crown TC (°C)", fmt(s.get("mc3_now"), 1), "mean of last 60 min"),
    ]

    if dcs is not None and not dcs.empty:
        ng = line_fig("NG flow, last 3 h", "per 15 min (DCS unit)")
        ng.add_trace(go.Scatter(x=dcs["ts"], y=dcs["ng"], mode="lines", name="1-min", line=dict(color="#c9cfd6", width=1)))
        ng15 = dcs.set_index("ts")["ng"].resample("15min").mean()
        ng.add_trace(go.Scatter(x=ng15.index, y=ng15.values, mode="lines+markers", name="15-min mean",
                                line=dict(color=BLUE, width=2.5), line_shape="hv"))
        mb3 = line_fig("MB3 bottom temperature, last 3 h", "°C")
        mb3.add_trace(go.Scatter(x=dcs["ts"], y=dcs["mb3"], mode="lines", name="MB3 (1-min)", line=dict(color=BLUE, width=2)))
        if rec:
            ng.add_hline(y=rec["ng_setpoint"], line=dict(color=ORANGE, dash="dash", width=2),
                         annotation_text=f"recommended {rec['ng_setpoint']:.1f}", annotation_position="top left")
            mb3.add_hline(y=rec["mb3_target"], line=dict(color=ORANGE, dash="dash", width=2),
                          annotation_text=f"target {rec['mb3_target']:.1f}", annotation_position="top left")
    else:
        ng, mb3 = empty_fig("no DCS data"), empty_fig("no DCS data")

    boost = st["boost"]
    if boost:
        boost_style = {"display": "none"}
        boost_db = [html.Div("Boosts, last hour (from DB)", style={"fontWeight": 600, "color": "#16202a"}),
                    html.Div(f"barrier {fmt(boost['bb_kwh_last_hour'], 0, 'kWh/h')} · "
                             f"melter {fmt(boost['mb_kwh_last_hour'], 0, 'kWh/h')}"),
                    html.Div(f"hour ending {boost['ts']:%H:%M}")]
    else:
        boost_style, boost_db = {}, ""

    footer = (f"Model: {model_label()}" + (f" · version {rec['model_version']} (trained until {rec['trained_until']})" if rec else "")
              + f" · DCS: {DCS_VIEW} · audit: {AUDIT_TABLE or 'off'} · live data every {REFRESH_SECONDS} s")
    return chips, live_values, ng, mb3, boost_style, boost_db, footer


@callback(
    Output("rec-area", "children"), Output("rec-store", "data"),
    Input("rec-btn", "n_clicks"),
    State("in-draw", "value"), State("in-cullet", "value"), State("in-optical", "value"),
    State("in-bb", "value"), State("in-mb", "value"),
    prevent_initial_call=True,
)
def make_recommendation(_n, draw, cullet, optical, bb_manual, mb_manual):
    """On "Get recommendation": validate, call the model, show the setpoints, write a RECOMMENDATION audit row."""
    now = now_ist()
    st = plant_state()
    s, ncv = st["s"], st["ncv"]
    warnings, blockers = list(st["warnings"]), list(st["blockers"])

    boost = st["boost"]
    if boost:
        bb, mb, boost_src = boost["bb_kwh_last_hour"], boost["mb_kwh_last_hour"], "DB"
    else:
        bb, mb, boost_src = bb_manual, mb_manual, "operator"

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
    if optical is not None and s and not pd.isna(s.get("mc3_now")):
        gap = optical - (s["mc3_now"] + OPTICAL_TC_OFFSET)
        if abs(gap) > OPTICAL_TC_TOL:
            warnings.append(f"optical {optical:.0f} °C differs from crown TC MC3 + {OPTICAL_TC_OFFSET} "
                            f"({s['mc3_now'] + OPTICAL_TC_OFFSET:.0f} °C) by {gap:+.0f} °C: check the reading")

    if blockers:
        return [html.Div(style={**CARD}, children=[
            html.Div("No recommendation", style={"fontWeight": 700, "color": AMBER, "fontSize": "17px", "marginBottom": "6px"}),
            html.Ul([html.Li(b) for b in blockers], style={"margin": "0", "paddingLeft": "20px", "color": AMBER})]),
            html.Div(warn_box(warnings), style={"marginTop": "12px"})], None

    record = {"timestamp": now.strftime("%Y-%m-%d %H:%M"), "ncv": float(ncv), "draw_t": float(draw),
              "cullet_pct": float(cullet), "bb_kwh_last_hour": float(bb), "mb_kwh_last_hour": float(mb),
              "mb3_now": round(float(s["mb3_now"]), 3)}
    for k, v in {"optical_temp": optical, "ng_now": s.get("ng_now"), "air_now": s.get("air_now")}.items():
        if v is not None and not pd.isna(v):
            record[k] = round(float(v), 3)
    try:
        rec = get_recommendation(record)
    except Exception as exc:
        traceback.print_exc()
        return html.Div(style={**CARD}, children=html.Div(f"Recommender ({model_label()}) failed: {exc}",
                                                          style={"color": AMBER})), None

    warnings += [f for f in (rec.get("flags") or "").split(" | ") if f]
    store = {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in rec.items()}
    store.update(recommendation_id=uuid.uuid4().hex, recommendation_for=now.strftime("%Y-%m-%d %H:%M"),
                 inputs=record, boost_source=boost_src, model_source=model_label(), all_flags=" | ".join(warnings))

    audit_note = ""
    if AUDIT_TABLE:
        try:
            write_audit(audit_row(store, "RECOMMENDATION"))
        except Exception as exc:
            traceback.print_exc()
            warnings.append(f"recommendation not written to the audit table: {exc}")
            audit_note = " (audit write failed)"

    da = rec.get("draw_adjusted_pct")
    area = [
        html.Div(style={"marginBottom": "8px"}, children=[
            html.Span(f"Recommendation for {now:%d %b %Y %H:%M}{audit_note}",
                      style={"fontWeight": 700, "color": NAVY, "fontSize": "17px"}),
            html.Span("  ·  NG and air: set in minute 15–20 of the next reversal cycle (one NG value for both ports). "
                      "Barrier boost: for the next hour. Then record what you set in the second tab.",
                      style={"color": GREY, "fontSize": "13px"})]),
        html.Div(style={"display": "flex", "gap": "12px", "flexWrap": "wrap"}, children=[
            setpoint_tile("NG flow", "per 15 min (DCS unit)", rec["ng_setpoint"], 1, s.get("ng_now"),
                          rec["ng_lo"], rec["ng_hi"], rec["ng_at_limit"]),
            setpoint_tile("Secondary air", "per 15 min (DCS unit)", rec["air_setpoint"], 0, s.get("air_now"),
                          rec["air_lo"], rec["air_hi"], rec["air_at_limit"]),
            setpoint_tile("Air-fuel ratio", "", rec["afr_setpoint"], 2,
                          (s["air_now"] / s["ng_now"]) if s.get("ng_now") else None,
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
                         f"target {fmt(rec['band_target_sfc'], 0)}" if rec.get("draw_band") else ""),
                      style={"color": GREY}),
            html.Div(f"Daily gas-heat target {rec['gas_target_gcal_day']:.2f} Gcal/day · NCV {ncv:,.0f} kcal/SCM · "
                     f"MB3 {s['mb3_now']:.1f} °C · boosts from {boost_src}",
                     style={"color": GREY, "fontSize": "12px", "marginTop": "4px"}),
        ]),
        html.Div(warn_box(warnings), style={"marginTop": "12px"}),
    ]
    return area, store


@callback(Output("set-reference", "children"), Output("set-afr", "children"),
          Input("rec-store", "data"), Input("set-ng", "value"), Input("set-air", "value"), Input("set-bb", "value"),
          Input("tick", "n_intervals"))
def show_reference(rec, ng_set, air_set, bb_set, _n):
    """Second tab: the recommendation the set points belong to, with the difference as the operator types."""
    afr_txt = f"Air-fuel ratio set: {air_set / ng_set:.2f}" if ng_set and air_set else ""
    if not rec:
        return html.Div(style={**CARD}, children=html.Div(
            "No recommendation yet. Get one in the Recommendation tab first.", style={"color": GREY})), afr_txt
    age = age_min(pd.Timestamp(rec["recommendation_for"]))
    afr_set = air_set / ng_set if ng_set and air_set else None
    rows = [("NG flow (per 15 min)", rec["ng_setpoint"], ng_set, 1),
            ("Secondary air (per 15 min)", rec["air_setpoint"], air_set, 0),
            ("Air-fuel ratio", rec["afr_setpoint"], afr_set, 2),
            ("Barrier boost (kWh/h)", rec["bb_setpoint_kwh_h"], bb_set, 0)]
    th = {"textAlign": "left", "padding": "8px", "fontSize": "12px", "color": "white", "background": NAVY}
    td = {"padding": "8px", "borderBottom": f"1px solid {LINE}", "fontSize": "14px"}
    table = html.Table(style={"width": "100%", "borderCollapse": "collapse"}, children=[
        html.Thead(html.Tr([html.Th(h, style=th) for h in ["Set point", "Recommended", "Set by operator", "Difference"]])),
        html.Tbody([html.Tr([html.Td(name, style=td), html.Td(fmt(r, dec), style={**td, "fontWeight": 600}),
                             html.Td(fmt(v, dec), style=td),
                             html.Td(change_span(v, r, dec) if v is not None else "–", style=td)])
                    for name, r, v, dec in rows])])
    old = html.Div(f"This recommendation is {age:.0f} min old. For a new cycle, get a new recommendation first.",
                   style={"color": AMBER, "fontSize": "13px", "marginTop": "8px"}) if age > 30 else None
    return html.Div(style={**CARD}, children=[
        html.Div(f"Recommendation of {pd.Timestamp(rec['recommendation_for']):%d %b %Y %H:%M}",
                 style={"fontWeight": 700, "color": NAVY, "fontSize": "16px"}),
        html.Div(f"id {rec['recommendation_id'][:8]} · model {rec['model_version']}",
                 style={"color": GREY, "fontSize": "12px", "marginBottom": "10px"}),
        table, old]), afr_txt


@callback(Output("save-status", "children"), Output("set-ng", "value"), Output("set-air", "value"),
          Output("set-bb", "value"), Output("set-remarks", "value"),
          Input("save-btn", "n_clicks"),
          State("rec-store", "data"), State("set-ng", "value"), State("set-air", "value"), State("set-bb", "value"),
          State("set-operator", "value"), State("set-remarks", "value"),
          prevent_initial_call=True)
def save_setpoints(_n, rec, ng_set, air_set, bb_set, operator, remarks):
    """Write an OPERATOR_SET row: the recommendation and what was actually set."""
    keep = (no_update,) * 4
    err = {"color": AMBER}
    if not AUDIT_TABLE:
        return html.Span("Saving is off: AUDIT_TABLE is not set in app.yaml.", style=err), *keep
    if not rec:
        return html.Span("Get a recommendation first (Recommendation tab).", style=err), *keep
    if ng_set is None and air_set is None and bb_set is None:
        return html.Span("Enter at least one set point.", style=err), *keep
    if not (operator or "").strip():
        return html.Span("Enter the operator name / ID.", style=err), *keep
    checks = [("NG", ng_set, rec["ng_lo"], rec["ng_hi"]), ("secondary air", air_set, rec["air_lo"], rec["air_hi"]),
              ("barrier boost", bb_set, 0, 1000)]
    for name, v, lo, hi in checks:
        if v is not None and not (0.5 * lo <= v <= 1.5 * hi):
            return html.Span(f"{name} = {v} looks like a typing error; please check.", style=err), *keep
    try:
        write_audit(audit_row(rec, "OPERATOR_SET", operator_name=operator.strip(), remarks=(remarks or "").strip(),
                              ng_set=ng_set, air_set=air_set, bb_set_kwh_h=bb_set,
                              afr_set=(air_set / ng_set) if ng_set and air_set else None))
    except Exception as exc:
        traceback.print_exc()
        return html.Span(f"Could not save: {exc}", style=err), *keep
    parts = [f"NG {fmt(ng_set, 1)}", f"air {fmt(air_set, 0)}", f"boost {fmt(bb_set, 0)} kWh/h"]
    return (html.Span(f"Saved at {now_ist():%H:%M:%S} for the recommendation of "
                      f"{pd.Timestamp(rec['recommendation_for']):%H:%M}: " + ", ".join(parts), style={"color": "#155d3f"}),
            None, None, None, "")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("DATABRICKS_APP_PORT", "8050")), debug=False)
