from flask import Flask, request
import requests
import json
from config import TOKEN, ADMIN_ID
import os
import re
import time
import random

app = Flask(__name__)
BOT_URL = f"https://api.telegram.org/bot{TOKEN}"
DB_FILE = "database.json"
KEYWORD_FILE = "keywords.json"  # 词库文件
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
        # 返回默认词库
        return {
            "eggs": [
                {"keywords": ["彩蛋", "惊喜", "秘密"], "reply": "🎉 恭喜你发现隐藏彩蛋！🎁\n你获得了一次虚拟抽奖机会：\n\n🎲 正在抽奖...\n\n✨ 恭喜获得：{prize}"},
                {"keywords": ["测试", "功能"], "reply": "这是一个测试回复，用于验证关键词匹配功能。"},
                {"keywords": ["你好", "hi", "hello"], "reply": "👋 你好！有什么我可以帮助你的吗？"}
            ],
            "prizes": ["100积分", "优惠券", "虚拟鲜花", "神秘礼品", "再次抽奖机会"]
        }

def save_keywords(data):
    with open(KEYWORD_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# --- 消息发送/响应函数 ---

def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        response = requests.post(f"{BOT_URL}/sendMessage", json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"发送消息到 {chat_id} 失败: {e}")
        return None

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
            # 简单的关键词匹配，可以根据需要调整为正则匹配
            if keyword.lower() in text.lower():
                reply = egg["reply"]
                
                # 处理动态内容
                if "{prize}" in reply and "prizes" in keywords_data:
                    prizes = keywords_data["prizes"]
                    prize = random.choice(prizes)
                    reply = reply.format(prize=prize)
                
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
    text = message.get("text", "")
    message_id = message["message_id"]
    user_id = message["from"]["id"]

    data = load_data()
    
    # 检查是否是待处理的操作
    if str(message_id) in data.get("pending_actions", {}):
        action = data["pending_actions"].pop(str(message_id))
        save_data(data)
        
        if action["type"] == "block":
            target_id = action["target_id"]
            reason = text
            
            if not reason.strip():
                send_message(ADMIN_ID, "❌ 拉黑原因不能为空！")
                return
                
            # 执行拉黑操作
            if target_id not in data["blacklist"]:
                data["blacklist"][target_id] = reason
                save_data(data)
                update_stats("blacklist")
                send_message(ADMIN_ID, f"✅ 用户 {target_id} 已被加入黑名单。\n原因: {reason}")
                
                # 通知被拉黑用户
                try:
                    send_message(int(target_id), f"🚫 你已被管理员加入黑名单，无法再继续使用本机器人。\n原因: {reason}")
                except Exception as e:
                    print(f"向 {target_id} 发送拉黑通知失败：{e}")
            else:
                current_reason = data["blacklist"][target_id]
                send_message(ADMIN_ID, f"ℹ️ 用户 {target_id} 已在黑名单中。\n当前原因: {current_reason}")
            
            # 更新原始消息
            try:
                original_chat_id = action["original_chat_id"]
                original_message_id = action["original_message_id"]
                
                # 获取原始消息
                msg = requests.get(f"{BOT_URL}/getMessage?chat_id={original_chat_id}&message_id={original_message_id}").json()
                if msg.get("ok"):
                    original_text = msg["result"]["text"]
                    new_text = f"[已处理] {original_text}"
                    
                    # 移除键盘
                    requests.post(f"{BOT_URL}/editMessageText", json={
                        "chat_id": original_chat_id,
                        "message_id": original_message_id,
                        "text": new_text
                    })
            except Exception as e:
                print(f"更新原始消息失败: {e}")
                
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
                    send_message(int(user_id_to_block), f"🚫 你已被管理员加入黑名单，无法再继续使用本机器人。\n原因: {reason}")
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
            subcommand = args.split()[0] if args else ""
            
            if subcommand == "add":
                # 添加新彩蛋
                try:
                    parts = args.split(" ", 2)
                    keywords_str = parts[1]
                    reply = parts[2]
                    
                    keywords = [k.strip() for k in keywords_str.split(",")]
                    
                    if not keywords or not reply:
                        send_message(ADMIN_ID, "❌ 格式错误，应为 /egg add <关键词1,关键词2> <回复内容>")
                        return
                        
                    keywords_data = load_keywords()
                    eggs = keywords_data.get("eggs", [])
                    
                    eggs.append({
                        "keywords": keywords,
                        "reply": reply
                    })
                    
                    save_keywords(keywords_data)
                    send_message(ADMIN_ID, f"✅ 新彩蛋已添加！\n关键词: {', '.join(keywords)}\n回复: {reply}")
                    
                except Exception as e:
                    send_message(ADMIN_ID, f"❌ 添加彩蛋失败: {str(e)}\n格式应为 /egg add <关键词1,关键词2> <回复内容>")
                    
            elif subcommand == "list":
                # 列出所有彩蛋
                keywords_data = load_keywords()
                eggs = keywords_data.get("eggs", [])
                
                if not eggs:
                    send_message(ADMIN_ID, "📭 当前没有设置任何彩蛋关键词。")
                    return
                    
                lines = []
                for i, egg in enumerate(eggs, 1):
                    keywords = ", ".join(egg["keywords"])
                    reply = egg["reply"][:50] + ("..." if len(egg["reply"]) > 50 else "")
                    lines.append(f"{i}. 关键词: {keywords}\n   回复: {reply}")
                    
                send_message(ADMIN_ID, "🥚 彩蛋关键词列表:\n\n" + "\n\n".join(lines))
                
            elif subcommand == "delete":
                # 删除彩蛋
                try:
                    index = int(args.split()[1]) - 1
                    
                    keywords_data = load_keywords()
                    eggs = keywords_data.get("eggs", [])
                    
                    if 0 <= index < len(eggs):
                        deleted = eggs.pop(index)
                        save_keywords(keywords_data)
                        send_message(ADMIN_ID, f"✅ 已删除彩蛋: {', '.join(deleted['keywords'])}")
                    else:
                        send_message(ADMIN_ID, "❌ 索引不存在，请使用 /egg list 查看可用索引。")
                        
                except (ValueError, IndexError):
                    send_message(ADMIN_ID, "❌ 格式错误，应为 /egg delete <序号>")
                    
            elif subcommand == "prize":
                # 管理奖品
                prize_subcmd = args.split()[1] if len(args.split()) > 1 else ""
                
                if prize_subcmd == "add":
                    prize = args.split(" ", 2)[2]
                    
                    if not prize:
                        send_message(ADMIN_ID, "❌ 格式错误，应为 /egg prize add <奖品名称>")
                        return
                        
                    keywords_data = load_keywords()
                    prizes = keywords_data.setdefault("prizes", [])
                    
                    if prize not in prizes:
                        prizes.append(prize)
                        save_keywords(keywords_data)
                        send_message(ADMIN_ID, f"✅ 新奖品已添加: {prize}")
                    else:
                        send_message(ADMIN_ID, f"❌ 奖品已存在: {prize}")
                        
                elif prize_subcmd == "list":
                    keywords_data = load_keywords()
                    prizes = keywords_data.get("prizes", [])
                    
                    if not prizes:
                        send_message(ADMIN_ID, "📭 当前没有设置任何奖品。")
                        return
                        
                    lines = [f"{i}. {prize}" for i, prize in enumerate(prizes, 1)]
                    send_message(ADMIN_ID, "🎁 奖品列表:\n\n" + "\n".join(lines))
                    
                elif prize_subcmd == "delete":
                    try:
                        index = int(args.split()[2]) - 1
                        
                        keywords_data = load_keywords()
                        prizes = keywords_data.get("prizes", [])
                        
                        if 0 <= index < len(prizes):
                            deleted = prizes.pop(index)
                            save_keywords(keywords_data)
                            send_message(ADMIN_ID, f"✅ 已删除奖品: {deleted}")
                        else:
                            send_message(ADMIN_ID, "❌ 索引不存在，请使用 /egg prize list 查看可用索引。")
                            
                    except (ValueError, IndexError):
                        send_message(ADMIN_ID, "❌ 格式错误，应为 /egg prize delete <序号>")
                        
                else:
                    send_message(ADMIN_ID, "❌ 未知子命令。可用子命令: add, list, delete")
                    
            else:
                help_text = """🥚 彩蛋管理命令:

/egg add <关键词1,关键词2> <回复内容> - 添加新彩蛋
/egg list - 列出所有彩蛋
/egg delete <序号> - 删除指定彩蛋
/egg prize add <奖品名称> - 添加抽奖奖品
/egg prize list - 列出所有奖品
/egg prize delete <序号> - 删除指定奖品"""
                send_message(ADMIN_ID, help_text)

# --- 按钮操作处理 ---

def handle_callback_query(callback_query):
    query_id = callback_query["id"]
    from_user_id = callback_query["from"]["id"]
    message_id = callback_query["message"]["message_id"]
    chat_id = callback_query["message"]["chat"]["id"]

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
        # 先确认拉黑原因
        force_reply_markup = json.dumps({
            "force_reply": True,
            "input_field_placeholder": "请输入拉黑原因..."
        })
        msg = send_message(ADMIN_ID, 
                          f"🚫 请输入拉黑用户 {target_id_str} 的原因：", 
                          reply_markup=force_reply_markup)
        
        # 存储待处理的拉黑操作
        data = load_data()
        data.setdefault("pending_actions", {})
        data["pending_actions"][str(msg["message_id"])] = {
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
