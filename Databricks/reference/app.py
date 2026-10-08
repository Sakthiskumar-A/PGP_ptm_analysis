"""SFC 60 TPD - Live NCV & DCS Monitor (Databricks App / Dash)

Data sources
  DCS  -> prod_pgp_dcs.gold.dcs60tpd        (SQL warehouse)
  NCV  -> Azure Blob MQTT JSON sensor feed   (live blobs)
"""

import os, json, time
import dash
from dash import html, dcc, dash_table, Input, Output, callback
import pandas as pd
from datetime import datetime, timedelta
from databricks.sdk import WorkspaceClient
from azure.storage.blob import BlobServiceClient

# ------------------------------------------------------------------ #
#  Configuration                                                      #
# ------------------------------------------------------------------ #
SQL_HTTP_PATH = os.getenv(
    "DATABRICKS_SQL_WAREHOUSE_HTTP_PATH",
    "/sql/1.0/warehouses/c5b898c9dc1668ef",
)

# Azure Blob - NCV MQTT sensor data
# Connection string injected via app.yaml -> {{secrets/sfc-60-tpd/azure-blob-conn-str}}
AZURE_CONN_STR = os.getenv("AZURE_BLOB_CONN_STR", "")
AZURE_CONTAINER = "pgldatalake"
NCV_SENSOR_ID = "19261"        # KSB_UEM_15MIN_TAG_STREAM1_INFERIOR_CV_NCV_Meter
NCV_PARAMETER_ID = "3742"


# ------------------------------------------------------------------ #
#  DCS data (SDK statement execution — native App OAuth)              #
# ------------------------------------------------------------------ #
WAREHOUSE_ID = "c5b898c9dc1668ef"


def fetch_dcs(limit: int = 50) -> pd.DataFrame:
    """Latest DCS rows via SDK statement_execution (handles App auth)."""
    query = f"""
    SELECT
        dcs_60_DateTime_IST,
        dcs_60_MelterGasflowvalueFTMGFPVDB202DD92,
        dcs_60_SecondaryAirFlowvalueFTSAFPVDB205DD92,
        dcs_60_ThermocoupleMelterBottom3TCMB3PVDB249DD572,
        dcs_60_ThermocoupleMelterCrown3TCMC3PVDB249DD202
    FROM prod_pgp_mfg.cantier.vw_dcs60tpd_live
    ORDER BY dcs_60_DateTime_IST DESC
    LIMIT {limit}
    """
    try:
        w = WorkspaceClient()
        resp = w.statement_execution.execute_statement(
            warehouse_id=WAREHOUSE_ID,
            statement=query,
            wait_timeout="30s",
        )
        if resp.status and resp.status.state and resp.status.state.value == "SUCCEEDED":
            cols = [c.name for c in resp.manifest.schema.columns]
            rows = []
            for chunk in (resp.result.data_array or []):
                rows.append(chunk)
            df = pd.DataFrame(rows, columns=cols)
            df.columns = [
                "DateTime (IST)",
                "Melter Gas Flow",
                "Secondary Air Flow",
                "Melter Bottom 3",
                "Melter Crown 3",
            ]
            # Cast numeric columns
            for c in df.columns[1:]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            return df
        else:
            msg = resp.status.error.message if resp.status and resp.status.error else "Unknown"
            return pd.DataFrame({"Error": [msg]})
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return pd.DataFrame({"Error": [str(exc)]})


# ------------------------------------------------------------------ #
#  NCV data (Azure Blob - mirrors MQTT_Data_Function)                 #
# ------------------------------------------------------------------ #
def fetch_ncv(minutes: int = 10) -> pd.DataFrame:
    """Read recent NCV blobs from Azure Blob Storage."""
    try:
        low_wm = int(time.time()) - minutes * 60

        now_utc = datetime.utcnow()
        start = now_utc - timedelta(minutes=minutes)
        dates = (
            pd.date_range(
                start.strftime("%Y-%m-%d"), now_utc.strftime("%Y-%m-%d")
            )
            .strftime("%d-%m-%Y")
            .tolist()
        )

        blob_svc = BlobServiceClient.from_connection_string(AZURE_CONN_STR)
        ctr = blob_svc.get_container_client(AZURE_CONTAINER)

        records = []
        for d in dates:
            prefix = (
                f"PROD_UEMS/MQTT/MQTT_Data/load_date={d}/{NCV_SENSOR_ID}"
            )
            for blob in ctr.list_blobs(name_starts_with=prefix):
                if blob.last_modified.timestamp() <= low_wm:
                    continue
                raw = (
                    ctr.get_blob_client(blob.name)
                    .download_blob()
                    .readall()
                    .decode("utf-8")
                )
                for line in raw.strip().splitlines():
                    try:
                        obj = json.loads(line)
                        ts = obj.get("ts")
                        val = (obj.get("data") or {}).get(
                            NCV_PARAMETER_ID
                        )
                        if ts is not None and val is not None:
                            ist = datetime.utcfromtimestamp(ts) + timedelta(
                                hours=5, minutes=30
                            )
                            records.append(
                                {
                                    "Timestamp (IST)": ist.strftime(
                                        "%Y-%m-%d %H:%M:%S"
                                    ),
                                    "NCV Meter": round(float(val), 2),
                                }
                            )
                    except (json.JSONDecodeError, TypeError, ValueError):
                        pass

        if not records:
            return pd.DataFrame(columns=["Timestamp (IST)", "NCV Meter"])
        return (
            pd.DataFrame(records)
            .sort_values("Timestamp (IST)", ascending=False)
            .reset_index(drop=True)
        )
    except Exception as exc:
        return pd.DataFrame({"Error": [str(exc)]})


# ------------------------------------------------------------------ #
#  Dash UI                                                            #
# ------------------------------------------------------------------ #
HDR = {
    "backgroundColor": "#1B3A5C",
    "color": "white",
    "fontWeight": "bold",
    "textAlign": "center",
}
CELL = {"textAlign": "center", "padding": "8px", "fontSize": "13px"}
ODD = [{"if": {"row_index": "odd"}, "backgroundColor": "#f5f7fa"}]

app = dash.Dash(__name__, title="SFC 60 TPD Live Monitor")

app.layout = html.Div(
    style={
        "fontFamily": "Segoe UI, sans-serif",
        "padding": "24px 32px",
        "maxWidth": "1320px",
        "margin": "auto",
    },
    children=[
        # Title
        html.H1(
            "SFC 60 TPD \u2014 Live NCV & DCS Monitor",
            style={
                "textAlign": "center",
                "color": "#1B3A5C",
                "marginBottom": "4px",
            },
        ),
        html.P(
            "Auto-refreshes every 30 s",
            style={
                "textAlign": "center",
                "color": "#999",
                "marginBottom": "24px",
            },
        ),
        dcc.Interval(id="tick", interval=30_000, n_intervals=0),
        # Draw-in-tonnes input
        html.Div(
            style={
                "display": "flex",
                "alignItems": "center",
                "gap": "12px",
                "marginBottom": "28px",
                "padding": "14px 18px",
                "backgroundColor": "#eef3f8",
                "borderRadius": "6px",
            },
            children=[
                html.Label(
                    "Draw in Tonnes:",
                    style={"fontWeight": "600", "fontSize": "15px"},
                ),
                dcc.Input(
                    id="draw-tonnes",
                    type="number",
                    placeholder="Enter value \u2026",
                    style={
                        "width": "180px",
                        "padding": "8px 10px",
                        "fontSize": "14px",
                        "border": "1px solid #bbb",
                        "borderRadius": "4px",
                    },
                ),
                html.Span(
                    id="draw-echo",
                    style={"color": "#555", "fontSize": "14px"},
                ),
            ],
        ),
        # DCS section
        html.H2(
            "DCS Live Values",
            style={
                "borderBottom": "2px solid #1B3A5C",
                "paddingBottom": "6px",
            },
        ),
        html.Div(
            id="dcs-ts",
            style={"color": "#999", "fontSize": "12px", "marginBottom": "6px"},
        ),
        dash_table.DataTable(
            id="dcs-tbl",
            page_size=20,
            style_table={"overflowX": "auto"},
            style_header=HDR,
            style_cell=CELL,
            style_data_conditional=ODD,
        ),
        html.Br(),
        # NCV section
        html.H2(
            "NCV Live Values (UEMS MQTT)",
            style={
                "borderBottom": "2px solid #1B3A5C",
                "paddingBottom": "6px",
            },
        ),
        html.Div(
            id="ncv-ts",
            style={"color": "#999", "fontSize": "12px", "marginBottom": "6px"},
        ),
        dash_table.DataTable(
            id="ncv-tbl",
            page_size=20,
            style_table={"overflowX": "auto"},
            style_header=HDR,
            style_cell=CELL,
            style_data_conditional=ODD,
        ),
    ],
)


@callback(
    Output("dcs-tbl", "data"),
    Output("dcs-tbl", "columns"),
    Output("dcs-ts", "children"),
    Output("ncv-tbl", "data"),
    Output("ncv-tbl", "columns"),
    Output("ncv-ts", "children"),
    Input("tick", "n_intervals"),
)
def refresh(n):
    now_ist = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime(
        "%Y-%m-%d %H:%M:%S IST"
    )

    dcs = fetch_dcs()
    ncv = fetch_ncv(minutes=10)

    return (
        dcs.to_dict("records"),
        [{"name": c, "id": c} for c in dcs.columns],
        f"Last refreshed: {now_ist}",
        ncv.to_dict("records"),
        [{"name": c, "id": c} for c in ncv.columns],
        f"Last refreshed: {now_ist}",
    )


@callback(Output("draw-echo", "children"), Input("draw-tonnes", "value"))
def echo_draw(val):
    return f"Current draw: {val} tonnes" if val is not None else ""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8050, debug=False)
