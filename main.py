from flask import Flask, request
import requests
import json
from config import TOKEN, ADMIN_ID
import os
import re
import time
import random
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
BOT_URL = f"https://api.telegram.org/bot{TOKEN}"
DB_FILE = "database.json"
KEYWORD_FILE = "keywords.json"
WELCOME_MSG = """👋 欢迎使用智能客服机器人！

我是您的在线助手，有问题请随时留言。
- 输入 /help 查看使用说明
- 输入 /about 了解更多关于我们的信息
- 试试触发隐藏彩蛋吧！"""


# --- 数据管理 ---

def load_data():
    try:
        with open(DB_FILE, "r") as f:
            data = json.load(f)
            data.setdefault("users", {})
            data.setdefault("blacklist", {})
            data.setdefault("stats", {
                "messages_received": 0,
                "users_count": 0,
                "blacklist_count": 0,
                "replies_sent": 0,
                "egg_hits": 0
            })
            data.setdefault("pending_actions", {})
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "users": {},
            "blacklist": {},
            "stats": {
                "messages_received": 0,
                "users_count": 0,
                "blacklist_count": 0,
                "replies_sent": 0,
                "egg_hits": 0
            },
            "pending_actions": {}
        }


def save_data(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# --- 词库管理 ---

def load_keywords():
    try:
        with open(KEYWORD_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "eggs": [
                {"keywords": ["彩蛋", "惊喜", "秘密"],
                 "reply": "🎉 恭喜你发现隐藏彩蛋！🎁\n你获得了一次虚拟抽奖机会：\n\n🎲 正在抽奖...\n\n✨ 恭喜获得：{prize}"},
                {"keywords": ["测试", "功能"], "reply": "这是一个测试回复，用于验证关键词匹配功能。"},
                {"keywords": ["你好", "hi", "hello"], "reply": "👋 你好！有什么我可以帮助你的吗？"}
            ],
            "prizes": ["100积分", "优惠券", "虚拟鲜花", "神秘礼品", "再次抽奖机会"]
        }


def save_keywords(data):
    with open(KEYWORD_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# --- 消息发送/响应函数 ---

def send_message(chat_id, text, reply_markup=None, retries=5, delay=2):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }

    if reply_markup:
        payload["reply_markup"] = reply_markup

    logging.info(f"尝试发送消息到用户 {chat_id}: {text[:50]}...")
    for attempt in range(retries):
        try:
            response = requests.post(
                f"{BOT_URL}/sendMessage",
                json=payload,
                timeout=15
            )
            response.raise_for_status()
            logging.info(f"消息成功发送到用户 {chat_id}")
            return {"status": "success", "result": response.json()}
        except requests.exceptions.RequestException as e:
            error_msg = f"发送消息到 {chat_id} 失败 (尝试 {attempt + 1}/{retries}): {str(e)}"
            logging.error(error_msg)
            try:
                if hasattr(e, 'response') and e.response:
                    error_details = e.response.json()
                    error_description = error_details.get('description', '未知 Telegram API 错误')
                    logging.error(f"Telegram API 错误: {error_description}")
                    if "bot was blocked" in error_description.lower():
                        return {"status": "error", "error": "user_blocked", "description": error_description}
                    elif "chat not found" in error_description.lower():
                        return {"status": "error", "error": "chat_not_found", "description": error_description}
                    elif "too many requests" in error_description.lower():
                        time.sleep(delay * (2 ** attempt))
                        continue
                    return {"status": "error", "error": "api_error", "description": error_description}
                else:
                    error_description = f"无响应内容: {str(e)}"
                    return {"status": "error", "error": "no_response", "description": error_description}
            except Exception as parse_error:
                error_description = f"无法解析 Telegram API 响应: {str(parse_error)}"
                logging.error(error_description)
                return {"status": "error", "error": "parse_error", "description": error_description}
        time.sleep(delay * (2 ** attempt))
    error_description = f"发送消息到 {chat_id} 失败：达到最大重试次数"
    logging.error(error_description)
    return {"status": "error", "error": "max_retries_exceeded", "description": error_description}


def answer_callback_query(callback_query_id, text=None, show_alert=False):
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    if show_alert:
        payload["show_alert"] = True
    requests.post(f"{BOT_URL}/answerCallbackQuery", json=payload)


# --- 统计功能 ---

def update_stats(message_type="user_message", increment=1):
    data = load_data()
    stats = data["stats"]

    if message_type == "user_message":
        stats["messages_received"] += increment
    elif message_type == "admin_reply":
        stats["replies_sent"] += increment
    elif message_type == "new_user":
        stats["users_count"] = len(data["users"])
    elif message_type == "blacklist":
        stats["blacklist_count"] = len(data["blacklist"])
    elif message_type == "egg_hit":
        stats["egg_hits"] += increment

    save_data(data)


# --- 彩蛋系统 ---

def process_egg_keywords(text):
    keywords_data = load_keywords()
    eggs = keywords_data.get("eggs", [])

    for egg in eggs:
        for keyword in egg["keywords"]:
            if keyword.lower() in text.lower():
                reply = egg["reply"]

                # 处理动态内容
                if "{prize}" in reply and "prizes" in keywords_data:
                    prizes = keywords_data["prizes"]
                    prize = random.choice(prizes)
                    reply = reply.format(prize=prize)

                elif "{time}" in reply:
                    current_time = datetime.now().strftime("%H:%M:%S")
                    reply = reply.replace("{time}", current_time)

                elif "{date}" in reply:
                    current_date = datetime.now().strftime("%Y年%m月%d日")
                    reply = reply.replace("{date}", current_date)

                # 更新统计
                update_stats("egg_hit")

                return reply

    return None


# --- Webhook 路由 ---

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    if "callback_query" in data:
        handle_callback_query(data["callback_query"])
    elif "message" in data:
        message = data["message"]
        user_id = message["from"]["id"]

        # 更新统计信息
        update_stats()

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

    # 检查用户是否在黑名单中
    if str(user_id) in data["blacklist"]:
        reason = data["blacklist"][str(user_id)]
        print(f"已屏蔽来自黑名单用户 {user_id} 的消息。原因: {reason}")
        send_message(user_id, f"🚫 你已被管理员加入黑名单，无法继续使用本机器人。\n原因: {reason}")
        return

    # 记录用户信息
    if str(user_id) not in data["users"]:
        data["users"][str(user_id)] = {
            "username": username,
            "first_seen": int(time.time()),
            "messages_count": 0
        }
        update_stats("new_user")
    else:
        data["users"][str(user_id)]["messages_count"] += 1

    save_data(data)

    # 处理命令和关键词
    if text == "/start":
        send_message(user_id, WELCOME_MSG)
    elif text == "/help":
        help_text = """📖 使用帮助：

1. 直接输入文字即可留言
2. 管理员会通过本机器人回复你
3. 输入 /start 重新显示欢迎信息
4. 输入 /help 显示此帮助信息
5. 输入 /about 了解更多关于我们的信息

尝试输入一些关键词触发隐藏功能哦！"""
        send_message(user_id, help_text)
    elif text == "/about":
        about_text = """🤖 关于本机器人：

这是一个智能客服机器人，由管理员团队维护。
我们致力于提供优质的服务，如有任何问题或建议，请随时留言。

版本: v2.0.0
更新日期: 2025年7月
"""
        send_message(user_id, about_text)
    else:
        # 检查彩蛋关键词
        egg_reply = process_egg_keywords(text)
        if egg_reply:
            send_message(user_id, egg_reply)
            return

        # 转发消息给管理员
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
    text = message.get("text", "").strip()
    message_id = str(message["message_id"])
    user_id = message["from"]["id"]

    data = load_data()
    reply_to_message = message.get("reply_to_message")

    # 情况 1：回复的是 Bot 发出的 "请直接回复此消息来回复用户 ..." 提示
    if reply_to_message and "💬 请直接回复此消息来回复用户" in reply_to_message.get("text", ""):
        match = re.search(r"用户 (\d+)", reply_to_message["text"])
        if not match:
            send_message(ADMIN_ID, "❌ 无法解析目标用户ID，请检查消息格式！")
            return

        target_id = match.group(1)
        if not text:
            send_message(ADMIN_ID, "❌ 回复内容不能为空！")
            return

        # 发送管理员回复给目标用户
        reply_text = f"📨 管理员回复：\n\n{text}"
        result = send_message(int(target_id), reply_text)

        if result["status"] == "success":
            send_message(ADMIN_ID, f"✅ 回复已成功发送给用户 {target_id}。")
            update_stats("admin_reply")
        else:
            error_msg = {
                "user_blocked": f"❌ 用户 {target_id} 已拉黑机器人，无法发送消息。",
                "chat_not_found": f"❌ 用户 {target_id} 不存在或未启动机器人。",
                "api_error": f"❌ 发送失败：{result['description']}",
                "unknown": f"❌ 未知错误：{result['description']}"
            }.get(result.get("error", "unknown"), f"❌ 错误：{result['description']}")
            send_message(ADMIN_ID, error_msg)
        return

    # 情况 2：回复的是之前 bot 发出的 ForceReply 消息，判断是否在待处理操作中
    if reply_to_message:
        reply_to_msg_id = str(reply_to_message["message_id"])
        pending_actions = data.get("pending_actions", {})
        if reply_to_msg_id in pending_actions:
            action = pending_actions.pop(reply_to_msg_id)
            save_data(data)

            target_id = action["target_id"]

            if action["type"] == "block":
                reason = text
                if not reason:
                    send_message(ADMIN_ID, "❌ 拉黑原因不能为空！")
                    # 重新放回 pending_actions
                    data["pending_actions"][reply_to_msg_id] = action
                    save_data(data)
                    return

                if target_id not in data["blacklist"]:
                    data["blacklist"][target_id] = reason
                    save_data(data)
                    update_stats("blacklist")
                    send_message(ADMIN_ID, f"✅ 用户 {target_id} 已被拉黑。\n原因: {reason}")
                    try:
                        send_message(int(target_id),
                                     f"🚫 你已被管理员加入黑名单，无法再继续使用本机器人。\n原因: {reason}")
                    except Exception as e:
                        logging.warning(f"通知用户 {target_id} 拉黑失败：{e}")
                else:
                    current_reason = data["blacklist"][target_id]
                    send_message(ADMIN_ID, f"ℹ️ 用户 {target_id} 已在黑名单中。\n原因: {current_reason}")

                # 更新原始按钮消息为“已处理”
                try:
                    requests.post(f"{BOT_URL}/editMessageText", json={
                        "chat_id": action["original_chat_id"],
                        "message_id": action["original_message_id"],
                        "text": f"[已处理] 用户 {target_id} 已被拉黑",
                        "reply_markup": json.dumps({"inline_keyboard": []})
                    })
                except Exception as e:
                    logging.warning(f"更新原始拉黑按钮消息失败：{e}")

            elif action["type"] == "reply":
                reply_text = text
                if not reply_text:
                    send_message(ADMIN_ID, "❌ 回复内容不能为空！")
                    return

                send_message(int(target_id), f"📨 管理员回复：\n\n{reply_text}")
                send_message(ADMIN_ID, f"✅ 已成功回复用户 {target_id}")
                update_stats("admin_reply")
            return

    # 情况 3：最后兜底，直接 message_id 命中 pending_actions 的情况（极少出现）
    if message_id in data.get("pending_actions", {}):
        action = data["pending_actions"].pop(message_id)
        save_data(data)

        if action["type"] == "block":
            target_id = action["target_id"]
            reason = text

            if not reason:
                send_message(ADMIN_ID, "❌ 拉黑原因不能为空！")
                return

            if target_id not in data["blacklist"]:
                data["blacklist"][target_id] = reason
                save_data(data)
                update_stats("blacklist")
                send_message(ADMIN_ID, f"✅ 用户 {target_id} 已被拉黑。\n原因: {reason}")
                try:
                    send_message(int(target_id),
                                 f"🚫 你已被管理员加入黑名单，无法再继续使用本机器人。\n原因: {reason}")
                except Exception as e:
                    logging.warning(f"向 {target_id} 发送拉黑通知失败：{e}")
            else:
                current_reason = data["blacklist"][target_id]
                send_message(ADMIN_ID, f"ℹ️ 用户 {target_id} 已在黑名单中。\n当前原因: {current_reason}")

            # 更新原始消息内容
            try:
                requests.post(f"{BOT_URL}/editMessageText", json={
                    "chat_id": action["original_chat_id"],
                    "message_id": action["original_message_id"],
                    "text": f"[已处理] 用户 {target_id} 已被拉黑",
                    "reply_markup": json.dumps({"inline_keyboard": []})
                })
            except Exception as e:
                logging.warning(f"更新原始按钮消息失败：{e}")
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
            failed = 0
            for user_id_str in all_users:
                if user_id_str not in blacklist:
                    try:
                        if send_message(int(user_id_str), args):
                            count += 1
                        else:
                            failed += 1
                        time.sleep(0.1)  # 避免触发API限制
                    except Exception as e:
                        print(f"广播到 {user_id_str} 失败: {e}")
                        failed += 1
            send_message(ADMIN_ID, f"✅ 广播完成，消息已成功发送给 {count} 位用户，{failed} 位用户发送失败。")

        elif command == "/block":
            if not args or len(args.split()) < 2:
                send_message(ADMIN_ID, "❌ 格式错误，应为 /block <用户ID> <原因>")
                return

            user_id_to_block, reason = args.split(" ", 1)

            if not user_id_to_block.isdigit():
                send_message(ADMIN_ID, "❌ 用户ID必须为数字！")
                return

            data = load_data()
            if user_id_to_block not in data["blacklist"]:
                data["blacklist"][user_id_to_block] = reason
                save_data(data)
                update_stats("blacklist")
                send_message(ADMIN_ID, f"✅ 用户 {user_id_to_block} 已被加入黑名单。\n原因: {reason}")

                # 通知被拉黑用户
                try:
                    send_message(int(user_id_to_block),
                                 f"🚫 你已被管理员加入黑名单，无法再继续使用本机器人。\n原因: {reason}")
                except Exception as e:
                    print(f"向 {user_id_to_block} 发送拉黑通知失败：{e}")
            else:
                current_reason = data["blacklist"][user_id_to_block]
                send_message(ADMIN_ID, f"ℹ️ 用户 {user_id_to_block} 已在黑名单中。\n当前原因: {current_reason}")

        elif command == "/unblock":
            if not args or not args.isdigit():
                send_message(ADMIN_ID, "❌ 格式错误，应为 /unblock <用户ID>")
                return

            user_id_to_unblock = args
            data = load_data()
            if user_id_to_unblock in data["blacklist"]:
                del data["blacklist"][user_id_to_unblock]
                save_data(data)
                update_stats("blacklist")
                send_message(ADMIN_ID, f"✅ 用户 {user_id_to_unblock} 已从黑名单移除。")
            else:
                send_message(ADMIN_ID, f"ℹ️ 用户 {user_id_to_unblock} 不在黑名单中。")

        elif command == "/blacklist":
            data = load_data()
            blacklist = data.get("blacklist", {})
            if not blacklist:
                send_message(ADMIN_ID, "📭 当前黑名单为空。")
            else:
                lines = []
                for uid, reason in blacklist.items():
                    user_info = data["users"].get(uid, {})
                    username = user_info.get("username", "（无用户名）")
                    first_seen = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(user_info.get("first_seen", 0)))
                    lines.append(f"- {uid} @{username}\n  拉黑原因: {reason}\n  首次加入: {first_seen}")
                send_message(ADMIN_ID, "🚫 黑名单列表：\n" + "\n\n".join(lines))

        elif command == "/stats":
            data = load_data()
            stats = data["stats"]
            active_users = len(data["users"]) - len(data["blacklist"])

            message = "📊 机器人统计信息:\n\n"
            message += f"👥 总用户数: {stats['users_count']}\n"
            message += f"👤 活跃用户: {active_users}\n"
            message += f"🚫 黑名单用户: {stats['blacklist_count']}\n"
            message += f"💬 收到消息总数: {stats['messages_received']}\n"
            message += f"↩️ 发送回复总数: {stats['replies_sent']}\n"
            message += f"🥚 彩蛋触发次数: {stats['egg_hits']}\n"

            # 计算回复率
            if stats['messages_received'] > 0:
                reply_rate = (stats['replies_sent'] / stats['messages_received']) * 100
                message += f"📊 回复率: {reply_rate:.2f}%\n"

            message += f"\n📅 数据更新时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            send_message(ADMIN_ID, message)

        elif command == "/egg":
            # 显示菜单
            keyboard = {
                "inline_keyboard": [
                    [{"text": "添加彩蛋", "callback_data": "egg_add"}],
                    [{"text": "查看彩蛋列表", "callback_data": "egg_list"}],
                    [{"text": "删除彩蛋", "callback_data": "egg_delete"}],
                    [{"text": "管理奖品", "callback_data": "egg_prize"}],
                    [{"text": "返回", "callback_data": "back"}]
                ]
            }
            send_message(ADMIN_ID, "🥚 彩蛋管理菜单:", reply_markup=json.dumps(keyboard))

        elif command == "/help":
            help_text = """👨‍💻 管理员帮助菜单:

/broadcast <消息> - 广播消息给所有用户
/block <用户ID> <原因> - 拉黑用户
/unblock <用户ID> - 解除拉黑
/blacklist - 查看黑名单列表
/stats - 查看机器人统计信息
/egg - 彩蛋关键词管理
/help - 显示此帮助信息"""
            send_message(ADMIN_ID, help_text)


# --- 按钮操作处理 ---

def handle_callback_query(callback_query):
    query_id = callback_query["id"]
    from_user_id = callback_query["from"]["id"]
    message_id = callback_query["message"]["message_id"]
    chat_id = callback_query["message"]["chat"]["id"]
    data = callback_query["data"]

    if from_user_id != ADMIN_ID:
        answer_callback_query(query_id, text="❌ 你没有权限操作。")
        return

    if data == "back":
        # 返回主菜单
        keyboard = {
            "inline_keyboard": [
                [{"text": "添加彩蛋", "callback_data": "egg_add"}],
                [{"text": "查看彩蛋列表", "callback_data": "egg_list"}],
                [{"text": "删除彩蛋", "callback_data": "egg_delete"}],
                [{"text": "管理奖品", "callback_data": "egg_prize"}],
                [{"text": "返回", "callback_data": "back_main"}]
            ]
        }
        requests.post(f"{BOT_URL}/editMessageText", json={
            "chat_id": chat_id,
            "message_id": message_id,
            "text": "🥚 彩蛋管理菜单:",
            "reply_markup": json.dumps(keyboard)
        })
        answer_callback_query(query_id)
        return

    elif data == "back_main":
        # 返回管理员主菜单
        help_text = """👨‍💻 管理员帮助菜单:

/broadcast <消息> - 广播消息给所有用户
/block <用户ID> <原因> - 拉黑用户
/unblock <用户ID> - 解除拉黑
/blacklist - 查看黑名单列表
/stats - 查看机器人统计信息
/egg - 彩蛋关键词管理
/help - 显示此帮助信息"""
        requests.post(f"{BOT_URL}/editMessageText", json={
            "chat_id": chat_id,
            "message_id": message_id,
            "text": help_text,
            "reply_markup": json.dumps({"inline_keyboard": []})
        })
        answer_callback_query(query_id)
        return

    elif data.startswith("egg_"):
        subcommand = data.split("_")[1]
        keywords_data = load_keywords()

        if subcommand == "add":
            force_reply_markup = json.dumps({
                "force_reply": True,
                "input_field_placeholder": "格式: 关键词1,关键词2|回复内容"
            })
            msg = send_message(ADMIN_ID, "请输入彩蛋信息 (格式: 关键词1,关键词2|回复内容):",
                               reply_markup=force_reply_markup)
            if not msg or "message_id" not in msg:
                answer_callback_query(query_id, text="❌ 操作失败，请重试", show_alert=True)
                return
            answer_callback_query(query_id)

        elif subcommand == "list":
            eggs = keywords_data.get("eggs", [])

            if not eggs:
                send_message(ADMIN_ID, "📭 当前没有设置任何彩蛋关键词。")
                answer_callback_query(query_id)
                return

            lines = []
            for i, egg in enumerate(eggs, 1):
                keywords = ", ".join(egg["keywords"])
                reply = egg["reply"][:50] + ("..." if len(egg["reply"]) > 50 else "")
                lines.append(f"{i}. 关键词: {keywords}\n   回复: {reply}")

            text = "🥚 彩蛋关键词列表:\n\n" + "\n\n".join(lines)
            keyboard = {
                "inline_keyboard": [
                    [{"text": "返回", "callback_data": "back"}]
                ]
            }
            requests.post(f"{BOT_URL}/editMessageText", json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "reply_markup": json.dumps(keyboard)
            })
            answer_callback_query(query_id)

        elif subcommand == "delete":
            eggs = keywords_data.get("eggs", [])

            if not eggs:
                send_message(ADMIN_ID, "📭 当前没有设置任何彩蛋关键词。")
                answer_callback_query(query_id)
                return

            lines = []
            for i, egg in enumerate(eggs, 1):
                keywords = ", ".join(egg["keywords"])
                lines.append(f"{i}. {keywords}")

            text = "请选择要删除的彩蛋:\n\n" + "\n".join(lines)
            force_reply_markup = json.dumps({
                "force_reply": True,
                "input_field_placeholder": "输入序号删除"
            })
            msg = send_message(ADMIN_ID, text, reply_markup=force_reply_markup)
            if not msg or "message_id" not in msg:
                answer_callback_query(query_id, text="❌ 操作失败，请重试", show_alert=True)
                return

            # 存储待处理的删除操作
            data = load_data()
            data.setdefault("pending_actions", {})
            data["pending_actions"][str(msg["message_id"])] = {
                "type": "egg_delete",
                "original_message_id": message_id,
                "original_chat_id": chat_id
            }
            save_data(data)

            answer_callback_query(query_id)

        elif subcommand == "prize":
            # 奖品管理子菜单
            keyboard = {
                "inline_keyboard": [
                    [{"text": "添加奖品", "callback_data": "egg_prize_add"}],
                    [{"text": "查看奖品列表", "callback_data": "egg_prize_list"}],
                    [{"text": "删除奖品", "callback_data": "egg_prize_delete"}],
                    [{"text": "返回", "callback_data": "back"}]
                ]
            }
            requests.post(f"{BOT_URL}/editMessageText", json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": "🎁 奖品管理菜单:",
                "reply_markup": json.dumps(keyboard)
            })
            answer_callback_query(query_id)

        elif subcommand == "prize_add":
            force_reply_markup = json.dumps({
                "force_reply": True,
                "input_field_placeholder": "输入奖品名称"
            })
            msg = send_message(ADMIN_ID, "请输入要添加的奖品名称:", reply_markup=force_reply_markup)
            if not msg or "message_id" not in msg:
                answer_callback_query(query_id, text="❌ 操作失败，请重试", show_alert=True)
                return
            answer_callback_query(query_id)

        elif subcommand == "prize_list":
            prizes = keywords_data.get("prizes", [])

            if not prizes:
                send_message(ADMIN_ID, "📭 当前没有设置任何奖品。")
                answer_callback_query(query_id)
                return

            lines = [f"{i}. {prize}" for i, prize in enumerate(prizes, 1)]
            text = "🎁 奖品列表:\n\n" + "\n".join(lines)
            keyboard = {
                "inline_keyboard": [
                    [{"text": "返回", "callback_data": "egg_prize"}]
                ]
            }
            requests.post(f"{BOT_URL}/editMessageText", json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "reply_markup": json.dumps(keyboard)
            })
            answer_callback_query(query_id)

        elif subcommand == "prize_delete":
            prizes = keywords_data.get("prizes", [])

            if not prizes:
                send_message(ADMIN_ID, "📭 当前没有设置任何奖品。")
                answer_callback_query(query_id)
                return

            lines = [f"{i}. {prize}" for i, prize in enumerate(prizes, 1)]
            text = "请选择要删除的奖品:\n\n" + "\n".join(lines)
            force_reply_markup = json.dumps({
                "force_reply": True,
                "input_field_placeholder": "输入序号删除"
            })
            msg = send_message(ADMIN_ID, text, reply_markup=force_reply_markup)
            if not msg or "message_id" not in msg:
                answer_callback_query(query_id, text="❌ 操作失败，请重试", show_alert=True)
                return

            # 存储待处理的删除操作
            data = load_data()
            data.setdefault("pending_actions", {})
            data["pending_actions"][str(msg["message_id"])] = {
                "type": "prize_delete",
                "original_message_id": message_id,
                "original_chat_id": chat_id
            }
            save_data(data)

            answer_callback_query(query_id)

    elif data.startswith("reply_"):
        target_id_str = data.split("_", 1)[1]
        force_reply_markup = json.dumps({"force_reply": True})
        prompt_message = f"💬 请直接回复此消息来回复用户 {target_id_str}：\n\n用户ID: {target_id_str}"

        result = send_message(ADMIN_ID, prompt_message, reply_markup=force_reply_markup)
        if result["status"] == "success":
            result_data = result.get("result", {}).get("result", {})
            message_id_sent = result_data.get("message_id")
            if message_id_sent:
                data = load_data()
                data.setdefault("pending_actions", {})
                data["pending_actions"][str(message_id_sent)] = {
                    "type": "reply",
                    "target_id": target_id_str,
                    "original_message_id": message_id,
                    "original_chat_id": chat_id
                }
                save_data(data)
                logging.info(f"✅ 存储待处理回复操作：message_id={message_id_sent}, target_id={target_id_str}")
                answer_callback_query(query_id)
                return
        else:
            error_description = result.get('description', '未知错误')
            error_msg = f"❌ 发送回复提示失败：{error_description}"
            logging.error(
                f"发送回复提示失败：chat_id={ADMIN_ID}, error={result.get('error')}, description={error_description}")
            send_message(ADMIN_ID, error_msg)
            answer_callback_query(query_id, text=error_msg, show_alert=True)

    elif data.startswith("block_"):
        target_id_str = data.split("_", 1)[1]
        force_reply_markup = json.dumps({
            "force_reply": True,
            "input_field_placeholder": "请输入拉黑原因..."
        })

        result = send_message(ADMIN_ID,
                               f"🚫 请输入拉黑用户 {target_id_str} 的原因：",
                               reply_markup=force_reply_markup)
         # 如果失败直接提示
         if result.get("status") != "success":
             answer_callback_query(query_id, text="❌ 发送请求失败，请稍后再试", show_alert=True)
             return
         # 深层提取到真正的 Telegram message_id
         sent = result["result"].get("result", {})
         prompt_msg_id = sent.get("message_id")
         if not prompt_msg_id:
             answer_callback_query(query_id, text="❌ 未能获取提示消息 ID，请重试", show_alert=True)
             return
 
         # 存储待处理的拉黑操作
         data = load_data()
         data.setdefault("pending_actions", {})
         data["pending_actions"][str(prompt_msg_id)] = {
             "type": "block",
             "target_id": target_id_str,
             "original_message_id": message_id,
             "original_chat_id": chat_id
         }
         save_data(data)
         answer_callback_query(query_id)


# --- 命令菜单设置 ---

def set_user_commands():
    commands = [
        {"command": "start", "description": "启动机器人"},
        {"command": "help", "description": "查看帮助信息"},
        {"command": "about", "description": "了解更多关于我们的信息"}
    ]
    requests.post(f"{BOT_URL}/setMyCommands", json={
        "commands": commands,
        "scope": {"type": "default"}
    })


def set_admin_commands():
    commands = [
        {"command": "broadcast", "description": "广播消息给所有用户"},
        {"command": "block", "description": "拉黑用户 - /block <用户ID> <原因>"},
        {"command": "unblock", "description": "解除拉黑 - /unblock <用户ID>"},
        {"command": "blacklist", "description": "查看黑名单列表"},
        {"command": "stats", "description": "查看机器人统计信息"},
        {"command": "egg", "description": "管理彩蛋关键词"},
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

    # 确保数据文件存在
    if not os.path.exists(DB_FILE):
        save_data(load_data())
    if not os.path.exists(KEYWORD_FILE):
        save_keywords(load_keywords())

    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
