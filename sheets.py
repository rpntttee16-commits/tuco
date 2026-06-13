import os
import json
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

ACCOUNTS = ["BANK A", "CASH"]


def get_client():
    json_str = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if json_str:
        info = json.loads(json_str)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
    return gspread.authorize(creds)


def get_sheet(tab_name: str):
    client = get_client()
    spreadsheet_id = os.environ["SPREADSHEET_ID"]
    spreadsheet = client.open_by_key(spreadsheet_id)
    return spreadsheet.worksheet(tab_name)


def get_latest_outstanding(tab_name: str) -> float:
    """ดึง Outstanding ล่าสุดของ tab นั้น"""
    ws = get_sheet(tab_name)
    records = ws.get_all_values()
    # หา Outstanding คอลัมน์ index (F = index 5)
    for row in reversed(records[1:]):  # ข้าม header
        if len(row) > 5 and row[5].strip():
            try:
                return float(row[5].replace(",", ""))
            except ValueError:
                continue
    return 0.0


def get_all_outstanding() -> dict:
    """ดึง Outstanding ล่าสุดของทุก tab"""
    result = {}
    for account in ACCOUNTS:
        try:
            result[account] = get_latest_outstanding(account)
        except Exception as e:
            result[account] = None
    return result


def append_record(tab_name: str, amount: float, type_: str = "", sub_type: str = "", note: str = ""):
    """เพิ่มแถวใหม่ใน tab"""
    ws = get_sheet(tab_name)
    records = ws.get_all_values()

    # คำนวณ no. ถัดไป
    no = len(records)  # นับแถวทั้งหมด (รวม header)

    # ดึง Outstanding ล่าสุด
    prev_outstanding = 0.0
    for row in reversed(records[1:]):
        if len(row) > 5 and row[5].strip():
            try:
                prev_outstanding = float(row[5].replace(",", ""))
                break
            except ValueError:
                continue

    outstanding = prev_outstanding + amount
    date_str = datetime.now().strftime("%Y-%m-%d")

    new_row = [no, date_str, type_, sub_type, amount, outstanding, note]
    ws.append_row(new_row, value_input_option="USER_ENTERED")
    return outstanding
