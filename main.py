from flask import Flask, request
import requests
import json
from config import TOKEN, ADMIN_ID
import os

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

def send_message(chat_id, text):
    requests.post(f"{BOT_URL}/sendMessage", json={
        "chat_id": chat_id,
        "text": text
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if "message" in data:
        message = data["message"]
        user_id = message["from"]["id"]
        text = message.get("text", "")
        username = message["from"].get("username", "匿名用户")

        # --- 修正后的逻辑 ---

        # 首先判断是不是管理员
        if user_id == ADMIN_ID:
            # --- 这是管理员的专属逻辑区 ---
            if text.startswith("/reply"):
                parts = text.split(" ", 2)
                if len(parts) < 3:
                    send_message(ADMIN_ID, "❌ 格式错误，应为 /reply <用户ID> <内容>")
                else:
                    target_id, reply_msg = parts[1], parts[2]
                    try:
                        # 尝试发送消息，并做一些基础的错误处理
                        send_message(int(target_id), reply_msg)
                        send_message(ADMIN_ID, "✅ 回复已发送")
                    except ValueError:
                        send_message(ADMIN_ID, "❌ 用户ID无效，必须是纯数字。")
                    except Exception as e:
                        send_message(ADMIN_ID, f"❌ 发送失败: {e}")
            
            # 你可以在这里用 elif 添加其他管理员指令
            # 对于管理员发送的其他任何消息，机器人不做任何事，直接返回即可

        else:
            # --- 这是普通用户的专属逻辑区 ---
            # 保存用户信息
            users = load_users()
            users[str(user_id)] = username
            save_users(users)

            if text == "/start":
                send_message(user_id, "你好！欢迎使用本机器人，有问题请留言，我会尽快回复你。")
            elif text == "/help":
                send_message(user_id, "直接输入文字即可留言；管理员会通过该机器人回复你。")
            else:
                # 转发用户消息给管理员
                forward_text = f"👤 用户 @{username} (ID: {user_id}) 发来消息：\n\n{text}"
                send_message(ADMIN_ID, forward_text)

    return "ok", 200

@app.route("/reply", methods=["POST"])
def reply():
    data = request.get_json()
    target_id = data.get("user_id")
    text = data.get("text")
    if target_id and text:
        send_message(target_id, text)
        return "sent"
    return "missing params", 400

@app.route("/", methods=["GET"])
def index():
    return "Bot is running!", 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
