"""
app.py — Flask Webhook สำหรับ LINE Messaging API
+ Cron job ส่งสรุปทุกวัน 10:00 น. (Bangkok UTC+7)
"""

import os
import hmac
import hashlib
import base64
import requests
from flask import Flask, request, abort
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from dialogue import handle_message, start_daily_summary

app = Flask(__name__)

LINE_CHANNEL_SECRET       = os.environ["LINE_CHANNEL_SECRET"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
TARGET_GROUP_ID           = os.environ["TARGET_GROUP_ID"]

BANGKOK = pytz.timezone("Asia/Bangkok")


# ─── LINE API helpers ────────────────────────────────────────────────────────

def verify_signature(body: bytes, signature: str) -> bool:
    hash_ = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"), body, hashlib.sha256
    ).digest()
    expected = base64.b64encode(hash_).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def reply_message(reply_token: str, text: str):
    requests.post(
        "https://api.line.me/v2/bot/message/reply",
        headers={
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "replyToken": reply_token,
            "messages": [{"type": "text", "text": text}],
        },
        timeout=10,
    )


def push_message(group_id: str, text: str):
    requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "to": group_id,
            "messages": [{"type": "text", "text": text}],
        },
        timeout=10,
    )


# ─── Webhook endpoint ────────────────────────────────────────────────────────

@app.route("/webhook", methods=["POST"])
def webhook():
    body      = request.get_data()
    signature = request.headers.get("X-Line-Signature", "")

    if not verify_signature(body, signature):
        abort(400, "Invalid signature")

    data = request.get_json()

    for event in data.get("events", []):
        if event["type"] != "message":
            continue
        if event["message"]["type"] != "text":
            continue

        source   = event.get("source", {})
        group_id = source.get("groupId", "")

        if group_id != TARGET_GROUP_ID:
            continue

        text        = event["message"]["text"]
        reply_token = event["replyToken"]

        reply = handle_message(group_id, text)
        if reply:
            reply_message(reply_token, reply)

    return "OK", 200


# ─── Health check ────────────────────────────────────────────────────────────

@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200


# ─── Cron: ส่งสรุปทุกวัน 10:00 น. Bangkok ──────────────────────────────────

def send_daily_summary():
    try:
        message = start_daily_summary(TARGET_GROUP_ID)
        push_message(TARGET_GROUP_ID, message)
        print("[Cron] Daily summary sent successfully")
    except Exception as e:
        print(f"[Cron] Error sending daily summary: {e}")


scheduler = BackgroundScheduler(timezone=BANGKOK)
scheduler.add_job(
    send_daily_summary,
    CronTrigger(hour=10, minute=0, timezone=BANGKOK),
)
scheduler.start()


# ─── Run ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

