from __future__ import annotations
import json
import re
from typing import Any

import pandas as pd
import streamlit as st

try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:  # pragma: no cover
    gspread = None
    Credentials = None

SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

def extract_sheet_id(url_or_id: str) -> str:
    s = str(url_or_id or "").strip()
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", s)
    return m.group(1) if m else s

@st.cache_resource(show_spinner=False)
def get_client_from_secrets():
    if gspread is None or Credentials is None:
        raise RuntimeError("gspread/google-auth are not installed.")
    info = dict(st.secrets.get("gcp_service_account", {}))
    if not info:
        raise RuntimeError("No [gcp_service_account] found in Streamlit secrets.")
    if "private_key" in info:
        info["private_key"] = info["private_key"].replace("\\n", "\n")
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)

def get_client_from_json_path(path: str):
    if gspread is None or Credentials is None:
        raise RuntimeError("gspread/google-auth are not installed.")
    creds = Credentials.from_service_account_file(path, scopes=SCOPES)
    return gspread.authorize(creds)

def read_worksheet(url_or_id: str, worksheet_name: str, local_json_path: str = "") -> pd.DataFrame:
    client = get_client_from_json_path(local_json_path) if local_json_path else get_client_from_secrets()
    sh = client.open_by_key(extract_sheet_id(url_or_id))
    ws = sh.worksheet(worksheet_name)
    values = ws.get_all_values()
    return pd.DataFrame(values)

def read_worksheet_as_records(url_or_id: str, worksheet_name: str, local_json_path: str = "") -> pd.DataFrame:
    client = get_client_from_json_path(local_json_path) if local_json_path else get_client_from_secrets()
    sh = client.open_by_key(extract_sheet_id(url_or_id))
    ws = sh.worksheet(worksheet_name)
    return pd.DataFrame(ws.get_all_records())

def write_dataframe_new_worksheet(url_or_id: str, worksheet_name: str, df: pd.DataFrame, local_json_path: str = "") -> str:
    client = get_client_from_json_path(local_json_path) if local_json_path else get_client_from_secrets()
    sh = client.open_by_key(extract_sheet_id(url_or_id))
    try:
        ws = sh.worksheet(worksheet_name)
        ws.clear()
    except Exception:
        ws = sh.add_worksheet(title=worksheet_name, rows=max(len(df) + 5, 100), cols=max(len(df.columns) + 5, 20))
    values = [list(map(str, df.columns))] + df.fillna("").astype(str).values.tolist()
    ws.update(values, value_input_option="USER_ENTERED")
    return worksheet_name

def update_cells_by_a1(url_or_id: str, worksheet_name: str, updates: dict[str, Any], local_json_path: str = "") -> int:
    client = get_client_from_json_path(local_json_path) if local_json_path else get_client_from_secrets()
    sh = client.open_by_key(extract_sheet_id(url_or_id))
    ws = sh.worksheet(worksheet_name)
    cells = []
    for a1, value in updates.items():
        cell = ws.acell(a1)
        cell.value = value
        cells.append(cell)
    if cells:
        ws.update_cells(cells, value_input_option="USER_ENTERED")
    return len(cells)
