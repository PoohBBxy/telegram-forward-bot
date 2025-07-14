from flask import Flask, request
import requests
import json
from config import TOKEN, ADMIN_ID
import os
import re # 导入正则表达式模块

app = Flask(__name__)
BOT_URL = f"https://api.telegram.org/bot{TOKEN}"
DB_FILE = "database.json"

def load_users():
    """从JSON文件加载用户数据"""
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_users(users):
    """将用户数据保存到JSON文件"""
    with open(DB_FILE, "w") as f:
        json.dump(users, f, indent=4)

def send_message(chat_id, text, **kwargs):
    """发送消息到指定的聊天ID"""
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    # 允许传入其他参数，如 reply_markup
    payload.update(kwargs)
    try:
        response = requests.post(f"{BOT_URL}/sendMessage", json=payload)
        response.raise_for_status() # 如果请求失败 (如 4xx or 5xx), 抛出异常
    except requests.exceptions.RequestException as e:
        print(f"发送消息到 {chat_id} 失败: {e}")


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if "message" not in data:
        return "ok", 200

    message = data["message"]
    user_id = message["from"]["id"]
    text = message.get("text", "")
    username = message["from"].get("username", "匿名用户")

    # --- 逻辑判断 ---

    # 1. 判断消息是否来自管理员
    if user_id == ADMIN_ID:
        # --- 管理员专属逻辑区 ---

        # 1.1 优先处理【快捷回复】功能
        # 检查消息是否是对另一条消息的回复
        if "reply_to_message" in message:
            replied_text = message["reply_to_message"].get("text", "")
            # 使用正则表达式从被回复的消息文本中提取原始用户ID
            # 匹配格式: "(ID:12345678)"
            match = re.search(r"\(ID:(\d+)\)", replied_text)
            
            if match:
                target_id = int(match.group(1))
                reply_msg = text  # 管理员的回复内容就是当前消息的文本
                try:
                    send_message(target_id, reply_msg)
                    send_message(ADMIN_ID, f"✅ 已通过「快捷回复」发送给用户 {target_id}。")
                except Exception as e:
                    send_message(ADMIN_ID, f"❌ 发送失败: {e}")
                return "ok", 200 # 处理完毕，直接返回
            else:
                # 如果管理员回复的不是机器人转发的用户消息，可以给个提示
                send_message(ADMIN_ID, "🤔 无法识别回复对象。请直接回复由机器人转发的用户消息才能使用快捷回复。")

        # 1.2 处理传统的【/reply 命令】(作为备用方案)
        elif text.startswith("/reply"):
            parts = text.split(" ", 2)
            if len(parts) < 3:
                send_message(ADMIN_ID, "❌ 格式错误，应为 /reply <用户ID> <内容>")
            else:
                target_id, reply_msg = parts[1], parts[2]
                try:
                    send_message(int(target_id), reply_msg)
                    send_message(ADMIN_ID, "✅ 已通过「指令」发送回复。")
                except ValueError:
                    send_message(ADMIN_ID, "❌ 用户ID无效，必须是纯数字。")
                except Exception as e:
                    send_message(ADMIN_ID, f"❌ 发送失败: {e}")
        
        # 1.3 管理员发送的其他消息，机器人可以不作回应
        # (或者你可以在这里添加其他管理员指令)

    # 2. 如果消息来自普通用户
    else:
        # --- 普通用户专属逻辑区 ---
        # 保存或更新用户信息
        users = load_users()
        users[str(user_id)] = username
        save_users(users)

        if text == "/start":
            send_message(user_id, "你好！欢迎使用本机器人，有问题请留言，我会尽快回复你。")
        elif text == "/help":
            send_message(user_id, "直接输入文字即可留言；管理员会通过该机器人回复你。")
        else:
            # 转发用户消息给管理员，并附上用户信息以便快捷回复
            forward_text = f"👤 用户 @{username} (ID:{user_id}) 发来消息：\n\n{text}"
            send_message(ADMIN_ID, forward_text)

    return "ok", 200


# 这个 /reply 路由现在是可选的，因为主要逻辑都在 webhook 中
# 但可以保留它用于其他可能的外部应用调用
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
