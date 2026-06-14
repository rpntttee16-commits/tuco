"""
sheets.py — อ่านและเขียนข้อมูลลง Google Sheets
แต่ละ tab = 1 บัญชี (TTB, CS, CC)
"""

import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone, timedelta
import os

# Bangkok timezone (UTC+7)
BKK = timezone(timedelta(hours=7))

# ชื่อ tab ทั้งหมดในระบบ — ต้องตรงกับชื่อ tab ใน Google Sheets
ACCOUNT_TABS = ["TTB", "CS", "CC"]

# คอลัมน์: A=no, B=date, C=type, D=sub-type, E=amount, F=Outstanding, G=note
COL_NO          = 0
COL_DATE        = 1
COL_TYPE        = 2
COL_SUBTYPE     = 3
COL_AMOUNT      = 4
COL_OUTSTANDING = 5
COL_NOTE        = 6


def get_client():
    """สร้าง gspread client ด้วย Service Account"""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(
        os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"], scopes=scopes
    )
    return gspread.authorize(creds)


def get_sheet(tab_name: str):
    """ดึง worksheet ตามชื่อ tab"""
    client = get_client()
    spreadsheet = client.open_by_key(os.environ["SPREADSHEET_ID"])
    return spreadsheet.worksheet(tab_name)


def get_latest_balance(tab_name: str) -> dict:
    """
    ดึงยอด Outstanding ล่าสุดของ tab นั้น
    คืนค่า: { outstanding, last_row_index, last_no }
    """
    sheet = get_sheet(tab_name)
    all_rows = sheet.get_all_values()

    last_outstanding = 0.0
    last_row_index = 1
    last_no = 0

    for i, row in enumerate(all_rows):
        if i == 0:
            continue
        outstanding_str = row[COL_OUTSTANDING].replace(",", "").strip()
        if outstanding_str:
            try:
                last_outstanding = float(outstanding_str)
                last_row_index = i + 1
                no_str = row[COL_NO].strip()
                last_no = int(no_str) if no_str.isdigit() else last_no
            except ValueError:
                pass

    return {
        "outstanding": last_outstanding,
        "last_row_index": last_row_index,
        "last_no": last_no,
    }


def get_all_balances() -> dict:
    """ดึงยอดล่าสุดของทุก tab คืนเป็น dict { tab_name: outstanding }"""
    return {tab: get_latest_balance(tab)["outstanding"] for tab in ACCOUNT_TABS}


def append_transaction(
    tab_name: str,
    date: str,
    type_: str,
    sub_type: str,
    amount: float,
    note: str,
) -> float:
    """
    เพิ่มแถวรายการใหม่ลง Sheets
    คืนค่า Outstanding ใหม่หลังจากบวก/ลบ amount
    """
    info = get_latest_balance(tab_name)
    new_outstanding = round(info["outstanding"] + amount, 2)
    new_no = info["last_no"] + 1

    sheet = get_sheet(tab_name)
    amount_str = f"{amount:,.2f}" if amount != 0 else ""

    new_row = [
        new_no,
        date,
        type_,
        sub_type,
        amount_str,
        f"{new_outstanding:,.2f}",
        note,
    ]
    sheet.append_row(new_row, value_input_option="USER_ENTERED")
    return new_outstanding


def append_confirmed_balances(confirmed: dict, today_str: str):
    """
    บันทึกยอดที่ทีมยืนยันแล้ว
    confirmed = { "TTB": 135000.0, "CS": 10000.0, "CC": 500.0 }
    """
    for tab_name, new_balance in confirmed.items():
        info = get_latest_balance(tab_name)
        diff = round(new_balance - info["outstanding"], 2)

        sheet = get_sheet(tab_name)
        new_no = info["last_no"] + 1

        new_row = [
            new_no,
            today_str,
            "ยืนยันยอด",
            "",
            f"{diff:,.2f}" if diff != 0 else "",
            f"{new_balance:,.2f}",
            "ยืนยันโดยทีม",
        ]
        sheet.append_row(new_row, value_input_option="USER_ENTERED")


def today_bkk() -> str:
    """วันที่วันนี้ในรูปแบบ D/M/YYYY (Bangkok time)"""
    now = datetime.now(BKK)
    return f"{now.day}/{now.month}/{now.year}"
