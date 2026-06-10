import re
from typing import Optional

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

from . import user_config as cfg

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def extract_spreadsheet_id(value: str) -> str:
    value = str(value or "").strip()
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", value)
    if match:
        return match.group(1)
    return value


def _service_account_info_available() -> bool:
    try:
        return "gcp_service_account" in st.secrets
    except Exception:
        return False


@st.cache_resource(show_spinner=False)
def _client_from_secrets():
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=SCOPES,
    )
    return gspread.authorize(creds)


@st.cache_resource(show_spinner=False)
def _client_from_file(path: str):
    creds = Credentials.from_service_account_file(path, scopes=SCOPES)
    return gspread.authorize(creds)


def get_client(service_account_file: Optional[str] = None):
    if _service_account_info_available():
        return _client_from_secrets()
    path = service_account_file or cfg.GOOGLE_SERVICE_ACCOUNT_FILE
    if not path:
        raise RuntimeError(
            "Google credentials not found. Add Streamlit secrets [gcp_service_account] for deployment, "
            "or enter a local JSON key path while testing."
        )
    return _client_from_file(path)


def read_google_sheet(spreadsheet_id_or_url: str, worksheet_name: str, service_account_file: Optional[str] = None) -> pd.DataFrame:
    client = get_client(service_account_file)
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id_or_url)
    ws = client.open_by_key(spreadsheet_id).worksheet(worksheet_name)
    data = ws.get_all_values()
    if not data:
        return pd.DataFrame()
    return pd.DataFrame(data)


def write_google_sheet(
    df: pd.DataFrame,
    spreadsheet_id_or_url: str,
    worksheet_name: str,
    service_account_file: Optional[str] = None,
    clear_sheet: bool = True,
):
    client = get_client(service_account_file)
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id_or_url)
    sh = client.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        rows = max(1000, len(df) + 10)
        cols = max(20, len(df.columns) + 5)
        ws = sh.add_worksheet(title=worksheet_name[:100], rows=str(rows), cols=str(cols))

    if clear_sheet:
        ws.clear()

    safe_df = df.copy().fillna("").astype(str)
    values = [safe_df.columns.tolist()] + safe_df.values.tolist()
    ws.update("A1", values)
