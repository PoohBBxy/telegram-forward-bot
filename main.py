# main.py
from flask import Flask, request
import requests
import json
from config import TOKEN, ADMIN_ID

app = Flask(__name__)
BOT_URL = f"https://api.telegram.org/bot{TOKEN}"

DB_FILE = "database.json"

def load_users():
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_users(users):
    with open(DB_FILE, "w") as f:
        json.dump(users, f)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if "message" in data:
        message = data["message"]
        user_id = message["from"]["id"]
        text = message.get("text", "")
        username = message["from"].get("username", "匿名用户")

        users = load_users()
        users[str(user_id)] = username
        save_users(users)

        forward_text = f"👤 用户 @{username}（ID:{user_id}）发来消息：\n{text}"
        requests.post(f"{BOT_URL}/sendMessage", json={
            "chat_id": ADMIN_ID,
            "text": forward_text
        })

    return "ok"

@app.route("/reply", methods=["POST"])
def reply():
    data = request.get_json()
    target_id = data.get("user_id")
    text = data.get("text")
    if target_id and text:
        requests.post(f"{BOT_URL}/sendMessage", json={
            "chat_id": target_id,
            "text": text
        })
        return "sent"
    return "missing params", 400

@app.route("/", methods=["GET"])
def index():
    return "Bot is running!", 200

if __name__ == "__main__":
    app.run()
