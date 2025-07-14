from flask import Flask, request
import requests
import json
from config import TOKEN, ADMIN_ID
import os
import re
import time

app = Flask(__name__)
BOT_URL = f"https://api.telegram.org/bot{TOKEN}"
DB_FILE = "database.json"

# --- 数据管理 ---

def load_data():
    try:
        with open(DB_FILE, "r") as f:
            data = json.load(f)
            if isinstance(data, dict) and "users" not in data:
                return {"users": data, "blacklist": []}
            data.setdefault("users", {})
            data.setdefault("blacklist", [])
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {"users": {}, "blacklist": []}

def save_data(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# --- 消息发送/响应函数 ---

def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        response = requests.post(f"{BOT_URL}/sendMessage", json=payload)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"发送消息到 {chat_id} 失败: {e}")

def answer_callback_query(callback_query_id, text=None):
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    requests.post(f"{BOT_URL}/answerCallbackQuery", json=payload)

# --- Webhook 路由 ---

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    if "callback_query" in data:
        handle_callback_query(data["callback_query"])
    elif "message" in data:
        message = data["message"]
        user_id = message["from"]["id"]
        if user_id == ADMIN_ID:
            handle_admin_message(message)
        else:
            handle_user_message(message)

    return "ok", 200

# --- 用户消息处理 ---

def handle_user_message(message):
    user_id = message["from"]["id"]
    username = message["from"].get("username", "匿名用户")
    text = message.get("text", "")

    data = load_data()

    if str(user_id) in data["blacklist"]:
        print(f"已屏蔽来自黑名单用户 {user_id} 的消息。")
        return

    data["users"][str(user_id)] = {"username": username}
    save_data(data)

    if text == "/start":
        send_message(user_id, "你好！欢迎使用本机器人，有问题请留言，我会尽快回复你。")
    elif text == "/help":
        send_message(user_id, "直接输入文字即可留言；管理员会通过该机器人回复你。")
    else:
        forward_text = f"👤 用户 @{username} (ID:{user_id}) 发来消息：\n\n{text}"
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "快捷回复", "callback_data": f"reply_{user_id}"},
                    {"text": "拉黑用户", "callback_data": f"block_{user_id}"}
                ]
            ]
        }
        send_message(ADMIN_ID, forward_text, reply_markup=json.dumps(keyboard))

# --- 管理员消息处理 ---

def handle_admin_message(message):
    text = message.get("text", "")

    if "reply_to_message" in message and "请直接回复此消息" in message["reply_to_message"].get("text", ""):
        replied_text = message["reply_to_message"]["text"]
        match = re.search(r"用户 (\d+)", replied_text)
        if match:
            target_id = int(match.group(1))
            reply_msg = text
            try:
                send_message(target_id, reply_msg)
                send_message(ADMIN_ID, f"✅ 已通过「快捷回复」发送给用户 {target_id}。")
            except Exception as e:
                send_message(ADMIN_ID, f"❌ 发送失败: {e}")
        return

    if text.startswith("/"):
        parts = text.split(" ", 1)
        command = parts[0]
        args = parts[1] if len(parts) > 1 else ""

        if command == "/broadcast":
            if not args:
                send_message(ADMIN_ID, "❌ 格式错误，应为 /broadcast <要广播的内容>")
                return

            data = load_data()
            all_users = data["users"].keys()
            blacklist = data["blacklist"]

            count = 0
            for user_id in all_users:
                if user_id not in blacklist:
                    try:
                        send_message(user_id, args)
                        count += 1
                        time.sleep(0.1)
                    except Exception as e:
                        print(f"广播到 {user_id} 失败: {e}")
            send_message(ADMIN_ID, f"✅ 广播完成，消息已发送给 {count} 位用户。")

        elif command == "/block":
            if not args or not args.isdigit():
                send_message(ADMIN_ID, "❌ 格式错误，应为 /block <用户ID>")
                return

            user_id_to_block = args
            data = load_data()
            if user_id_to_block not in data["blacklist"]:
                data["blacklist"].append(user_id_to_block)
                save_data(data)
                send_message(ADMIN_ID, f"✅ 用户 {user_id_to_block} 已被加入黑名单。")
            else:
                send_message(ADMIN_ID, f"ℹ️ 用户 {user_id_to_block} 已在黑名单中。")

        elif command == "/unblock":
            if not args or not args.isdigit():
                send_message(ADMIN_ID, "❌ 格式错误，应为 /unblock <用户ID>")
                return

            user_id_to_unblock = args
            data = load_data()
            if user_id_to_unblock in data["blacklist"]:
                data["blacklist"].remove(user_id_to_unblock)
                save_data(data)
                send_message(ADMIN_ID, f"✅ 用户 {user_id_to_unblock} 已从黑名单移除。")
            else:
                send_message(ADMIN_ID, f"ℹ️ 用户 {user_id_to_unblock} 不在黑名单中。")

        elif command == "/blacklist":
            data = load_data()
            blacklist = data.get("blacklist", [])
            if not blacklist:
                send_message(ADMIN_ID, "📭 当前黑名单为空。")
            else:
                lines = []
                for uid in blacklist:
                    username = data["users"].get(uid, {}).get("username", "（无用户名）")
                    lines.append(f"- {uid} @{username}")
                send_message(ADMIN_ID, "🚫 黑名单列表：\n" + "\n".join(lines))

# --- 按钮操作处理 ---

def handle_callback_query(callback_query):
    query_id = callback_query["id"]
    from_user_id = callback_query["from"]["id"]

    if from_user_id != ADMIN_ID:
        answer_callback_query(query_id, text="❌ 你没有权限操作。")
        return

    data = callback_query["data"]
    action, target_id_str = data.split("_", 1)

    if action == "reply":
        force_reply_markup = json.dumps({"force_reply": True})
        send_message(ADMIN_ID, f"💬 请直接回复此消息来回复用户 {target_id_str}：", reply_markup=force_reply_markup)
        answer_callback_query(query_id)

    elif action == "block":
        db_data = load_data()
        if target_id_str not in db_data["blacklist"]:
            db_data["blacklist"].append(target_id_str)
            save_data(db_data)
            answer_callback_query(query_id, text=f"✅ 用户 {target_id_str} 已被拉黑")
            try:
                send_message(int(target_id_str), "🚫 你已被管理员加入黑名单，无法再继续使用本机器人。")
            except Exception as e:
                print(f"向 {target_id_str} 发送拉黑通知失败：{e}")
        else:
            answer_callback_query(query_id, text=f"ℹ️ 用户 {target_id_str} 已在黑名单中")

# --- 命令菜单设置 ---

def set_user_commands():
    commands = [
        {"command": "start", "description": "启动机器人"},
        {"command": "help", "description": "查看帮助信息"}
    ]
    requests.post(f"{BOT_URL}/setMyCommands", json={
        "commands": commands,
        "scope": {"type": "default"}
    })

def set_admin_commands():
    commands = [
        {"command": "broadcast", "description": "广播消息"},
        {"command": "block", "description": "拉黑用户"},
        {"command": "unblock", "description": "解除拉黑"},
        {"command": "help", "description": "查看帮助信息"}
    ]
    requests.post(f"{BOT_URL}/setMyCommands", json={
        "commands": commands,
        "scope": {"type": "chat", "chat_id": ADMIN_ID}
    })

# --- 健康检查 ---
@app.route("/", methods=["GET"])
def index():
    return "Bot is running!", 200

# --- 启动 ---
if __name__ == '__main__':
    # 启动后立即设置菜单
    set_user_commands()
    set_admin_commands()

    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
