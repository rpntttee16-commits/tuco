"""
dialogue.py — จัดการ state การสนทนาใน LINE Group
และเรียก Claude API เพื่อสร้างข้อความ
"""

import os
from sheets import ACCOUNT_TABS, get_all_balances, today_bkk, append_transaction

# State ของแต่ละ group (group_id → state dict)
group_states: dict = {}


def get_state(group_id: str) -> dict:
    if group_id not in group_states:
        group_states[group_id] = {
            "step": "idle",
            "balances": {},
            "pending_corrections": [],
            "corrected": {},
            "date": "",
        }
    return group_states[group_id]


def reset_state(group_id: str):
    group_states[group_id] = {
        "step": "idle",
        "balances": {},
        "pending_corrections": [],
        "corrected": {},
        "date": "",
    }


# ─── สร้างข้อความต่าง ๆ ──────────────────────────────────────────────────────

def build_summary_message(balances: dict, date_str: str) -> str:
    lines = [f"📊 สรุปยอดคงเหลือ วันที่ {date_str}\n"]
    for tab, amount in balances.items():
        lines.append(f"  {tab:<6}: {amount:>15,.2f}")
    lines.append("\nยืนยันถูกต้องไหมครับ?")
    lines.append("✅ ใช่  /  ❌ ไม่ใช่")
    return "\n".join(lines)


def build_account_list_message(tabs: list) -> str:
    lines = ["บัญชีไหนที่ไม่ถูกครับ? (ตอบเลข)\n"]
    for i, tab in enumerate(tabs, 1):
        lines.append(f"  {i}. {tab}")
    return "\n".join(lines)


def build_ask_correct_amount(tab_name: str, current: float) -> str:
    return (
        f"💳 {tab_name}\n"
        f"ยอดที่ระบบคิด: {current:,.2f}\n\n"
        f"ยอดที่ถูกต้องควรเป็นเท่าไหร่ครับ? (ตอบตัวเลขเท่านั้น)"
    )


def build_reconfirm_message(balances: dict, date_str: str) -> str:
    lines = [f"📊 ยอดที่อัปเดตแล้ว วันที่ {date_str}\n"]
    for tab, amount in balances.items():
        lines.append(f"  {tab:<6}: {amount:>15,.2f}")
    lines.append("\nยืนยันถูกต้องไหมครับ?")
    lines.append("✅ ใช่  /  ❌ ไม่ใช่")
    return "\n".join(lines)


# ─── Claude helpers ───────────────────────────────────────────────────────────

def parse_amount(text: str) -> float | None:
    """
    แปลงข้อความตัวเลขเป็น float
    รองรับ: 3000 / 3,000 / 3.5k / 3.5K
    """
    text = text.strip().replace(",", "")
    if text.lower().endswith("k"):
        try:
            return round(float(text[:-1]) * 1000, 2)
        except ValueError:
            return None
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def classify_reply(text: str) -> str:
    t = text.strip().lower()
    if any(w in t for w in ["ใช่", "yes", "ถูก", "ok", "โอเค", "✅", "confirmed", "ยืนยัน"]):
        return "yes"
    if any(w in t for w in ["ไม่ใช่", "no", "ผิด", "ไม่", "❌", "แก้"]):
        return "no"
    return "unknown"


def parse_account_number(text: str, max_index: int) -> int | None:
    text = text.strip()
    if text.isdigit():
        n = int(text)
        if 1 <= n <= max_index:
            return n
    return None


# ─── Parser คำสั่ง บัญชี +/-จำนวน ──────────────────────────────────────────

def parse_transaction_command(text: str) -> dict | None:
    """
    รูปแบบ: "[บัญชี] [+/-][จำนวน] [หมายเหตุ]"
    เช่น:   "ttb +3000 ลูกค้า A"
            "CS -500 ค่ารถ"
            "CC +4000 ลูกค้า M"
    - ชื่อบัญชีพิมพ์ใหญ่เล็กยังไงก็ได้
    - +/- ต้องติดหน้าตัวเลข (ไม่มีเว้นวรรค)
    """
    parts = text.strip().split(None, 2)   # [บัญชี, ±จำนวน, note?]
    if len(parts) < 2:
        return None

    account = parts[0].upper()
    if account not in ACCOUNT_TABS:
        return None

    amount_str = parts[1]
    if amount_str[0] == "+":
        direction = "รับ"
    elif amount_str[0] == "-":
        direction = "จ่าย"
    else:
        return None  # ไม่มี +/- → ไม่ใช่คำสั่ง

    return {
        "direction":   direction,
        "account":     account,
        "amount_text": amount_str[1:],          # ตัด +/- ออก
        "note":        parts[2] if len(parts) > 2 else "",
    }


# ─── Main handler ─────────────────────────────────────────────────────────────

def handle_message(group_id: str, text: str) -> str | None:
    state = get_state(group_id)
    step  = state["step"]

    # ── idle: รับคำสั่งบันทึกรายการ ──
    if step == "idle":
        # คำสั่งสรุปยอด
        if text.strip().lower() in ["สรุป", "summary", "ยอด"]:
            return start_daily_summary(group_id)

        parsed = parse_transaction_command(text)
        if parsed is None:
            return None

        amount = parse_amount(parsed["amount_text"])
        if amount is None:
            return (
                "ไม่เข้าใจจำนวนเงินครับ\n"
                "ตัวอย่าง: ttb +3000 ลูกค้า A"
            )

        signed = amount if parsed["direction"] == "รับ" else -amount
        new_bal = append_transaction(
            tab_name=parsed["account"],
            date=today_bkk(),
            type_=parsed["direction"],
            sub_type="",
            amount=signed,
            note=parsed["note"],
        )

        icon = "💰" if parsed["direction"] == "รับ" else "💸"
        lines = [f"{icon} {parsed['account']} {parsed['direction']} {amount:,.2f}"]
        if parsed["note"]:
            lines.append(f"   {parsed['note']}")
        return "\n".join(lines)

    # ── รอยืนยันครั้งแรก ──
    if step == "waiting_confirm":
        reply_type = classify_reply(text)

        if reply_type == "yes":
            from sheets import append_confirmed_balances
            append_confirmed_balances(state["balances"], state["date"])
            reset_state(group_id)
            return "✅ บันทึกยอดเรียบร้อยแล้วครับ ขอบคุณครับ"

        elif reply_type == "no":
            state["step"] = "correcting"
            state["pending_corrections"] = list(ACCOUNT_TABS)
            state["corrected"] = dict(state["balances"])
            return build_account_list_message(ACCOUNT_TABS)

        else:
            return "กรุณาตอบ ใช่ หรือ ไม่ใช่ ครับ"

    # ── เลือกบัญชีที่ผิด ──
    elif step == "correcting":
        n = parse_account_number(text, len(ACCOUNT_TABS))
        if n is None:
            return build_account_list_message(ACCOUNT_TABS)
        tab = ACCOUNT_TABS[n - 1]
        state["step"] = f"correcting:{tab}"
        return build_ask_correct_amount(tab, state["corrected"].get(tab, 0))

    # ── รับยอดที่ถูกต้อง ──
    elif step.startswith("correcting:"):
        tab = step.split(":", 1)[1]
        amount = parse_amount(text)
        if amount is None:
            return "ไม่เข้าใจตัวเลขครับ เช่น 135000"

        state["corrected"][tab] = amount
        state["step"] = "ask_more_corrections"
        remaining = [t for t in ACCOUNT_TABS if t != tab]
        lines = [f"✏️ {tab} = {amount:,.2f}\n", "มีบัญชีอื่นที่ไม่ถูกอีกไหมครับ?"]
        for i, t in enumerate(remaining, 1):
            lines.append(f"  {i}. {t}")
        lines.append(f"  {len(remaining)+1}. ไม่มีแล้ว")
        state["_remaining_tabs"] = remaining
        return "\n".join(lines)

    # ── ถามว่ามีบัญชีอื่นผิดอีกไหม ──
    elif step == "ask_more_corrections":
        remaining = state.get("_remaining_tabs", [])
        if text.strip() in [str(len(remaining)+1), "ไม่มี", "ไม่มีแล้ว", "no", "เสร็จ"]:
            state["balances"] = dict(state["corrected"])
            state["step"] = "waiting_confirm"
            return build_reconfirm_message(state["balances"], state["date"])

        n = parse_account_number(text, len(remaining))
        if n is None:
            return "กรุณาตอบเลขครับ"
        tab = remaining[n - 1]
        state["step"] = f"correcting:{tab}"
        return build_ask_correct_amount(tab, state["corrected"].get(tab, 0))

    return None


# ─── Daily summary ────────────────────────────────────────────────────────────

def start_daily_summary(group_id: str) -> str:
    balances = get_all_balances()
    date_str = today_bkk()
    state = get_state(group_id)
    state["step"]     = "waiting_confirm"
    state["balances"] = balances
    state["date"]     = date_str
    return build_summary_message(balances, date_str)
