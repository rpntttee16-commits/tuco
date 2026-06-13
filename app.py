import os
import json
import hashlib
import hmac
import base64
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from sheets import get_all_outstanding, append_record, ACCOUNTS

app = Flask(__name__)

line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])

# State machine per group
# state: idle | waiting_confirm | waiting_fix_{account}
group_states = {}
# เก็บ outstanding ที่ bot ส่งไป รอยืนยัน
pending_data = {}


def send_message(group_id: str, text: str):
    line_bot_api.push_message(group_id, TextSendMessage(text=text))


def format_summary(data: dict) -> str:
    lines = ["📊 สรุปยอดคงเหลือประจำวัน"]
    for account, balance in data.items():
        if balance is None:
            lines.append(f"• {account}: ❌ ดึงข้อมูลไม่ได้")
        else:
            lines.append(f"• {account}: {balance:,.2f} บาท")
    lines.append("\nยอดถูกต้องไหมครับ? (ใช่ / ไม่ใช่)")
    return "\n".join(lines)


def send_daily_summary(group_id: str):
    data = get_all_outstanding()
    pending_data[group_id] = data
    group_states[group_id] = {"state": "waiting_confirm", "fix_queue": []}
    send_message(group_id, format_summary(data))


def handle_text(group_id: str, text: str, user_id: str):
    text = text.strip()
    state_obj = group_states.get(group_id, {"state": "idle", "fix_queue": []})
    state = state_obj.get("state", "idle")

    # --- waiting_confirm ---
    if state == "waiting_confirm":
        if text in ["ใช่", "ถูกต้อง", "ok", "OK", "โอเค", "✅"]:
            group_states[group_id] = {"state": "idle", "fix_queue": []}
            pending_data.pop(group_id, None)
            send_message(group_id, "✅ รับทราบครับ บันทึกยืนยันแล้ว")

        elif text in ["ไม่ใช่", "ไม่", "ผิด", "❌"]:
            # ถามทีละบัญชี
            fix_queue = list(ACCOUNTS)
            group_states[group_id] = {"state": f"waiting_fix_{fix_queue[0]}", "fix_queue": fix_queue}
            current = pending_data.get(group_id, {}).get(fix_queue[0], 0)
            send_message(
                group_id,
                f"กรุณาระบุยอดที่ถูกต้องของ {fix_queue[0]} ครับ\n(ยอดปัจจุบัน: {current:,.2f} บาท)\nพิมพ์ตัวเลขได้เลย หรือพิมพ์ 'ข้าม' ถ้าถูกต้อง"
            )
        return

    # --- waiting_fix_{account} ---
    for account in ACCOUNTS:
        if state == f"waiting_fix_{account}":
            fix_queue = state_obj.get("fix_queue", [])

            if text in ["ข้าม", "skip"]:
                # ข้ามบัญชีนี้
                new_queue = fix_queue[1:]
            else:
                try:
                    new_amount = float(text.replace(",", ""))
                    # บันทึกลง sheet
                    append_record(account, new_amount, type_="แก้ไข", note="แก้จาก LINE Bot")
                    send_message(group_id, f"✅ บันทึก {account}: {new_amount:,.2f} บาท แล้วครับ")
                    new_queue = fix_queue[1:]
                except ValueError:
                    send_message(group_id, "กรุณาพิมพ์ตัวเลขเท่านั้นครับ (เช่น 15000 หรือ 15,000)")
                    return

            if new_queue:
                next_account = new_queue[0]
                group_states[group_id] = {"state": f"waiting_fix_{next_account}", "fix_queue": new_queue}
                current = pending_data.get(group_id, {}).get(next_account, 0)
                send_message(
                    group_id,
                    f"กรุณาระบุยอดที่ถูกต้องของ {next_account} ครับ\n(ยอดปัจจุบัน: {current:,.2f} บาท)\nพิมพ์ตัวเลข หรือ 'ข้าม' ถ้าถูกต้อง"
                )
            else:
                group_states[group_id] = {"state": "idle", "fix_queue": []}
                pending_data.pop(group_id, None)
                send_message(group_id, "✅ บันทึกครบทุกบัญชีแล้วครับ ขอบคุณ!")
            return

    # --- idle: รับคำสั่ง manual ---
    if text.lower() in ["/summary", "สรุป"]:
        send_daily_summary(group_id)


@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    if event.source.type != "group":
        return
    group_id = event.source.group_id
    user_id = event.source.user_id
    text = event.message.text
    handle_text(group_id, text, user_id)


# Endpoint สำหรับ external cron ปลุก server และ trigger summary
@app.route("/trigger-summary", methods=["POST"])
def trigger_summary():
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {os.environ.get('CRON_SECRET', '')}":
        abort(401)
    group_id = os.environ["LINE_GROUP_ID"]
    send_daily_summary(group_id)
    return "OK"


@app.route("/", methods=["GET"])
def health():
    return "LINE Bot is running"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
