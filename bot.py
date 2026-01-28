import os
import logging
import asyncio
import datetime
import dns.resolver
import pytz 
from telebot.async_telebot import AsyncTeleBot
from telebot import types
from motor.motor_asyncio import AsyncIOMotorClient
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from aiohttp import web  # REQUIRED FOR KOYEB

# --- 1. CONFIGURATION ---

# Fix Google DNS
try:
    dns.resolver.default_resolver = dns.resolver.Resolver(configure=False)
    dns.resolver.default_resolver.nameservers = ['8.8.8.8']
except Exception:
    pass

load_dotenv()

def get_bool(key, default="False"):
    return os.getenv(key, default).lower() in ["true", "1", "yes", "on"]

# Load Env Variables
try:
    BOT_TOKENS = os.getenv("BOT_TOKEN", "").split(",")
    MONGO_URL = os.getenv("MONGO_URL", "")
    LOG_CHANNEL = int(os.getenv("LOG_CHANNEL_ID", "0"))
    
    PIN_START = get_bool("PIN_START_RAW", "False")
    PIN_ADS   = get_bool("PIN_ADS_RAW", "False")
    PIN_ALERT = get_bool("PIN_ALERT_RAW", "False")
    PIN_BL    = get_bool("PIN_BL_RAW", "False")
    ADS_RAW_PIN = get_bool("ADS_RAW_PIN", "False")

    _admin_ids = os.getenv("ADMIN_IDS", "")
    ADMIN_IDS = [int(x) for x in _admin_ids.split(",") if x]

except (ValueError, TypeError):
    print("⚠️ WARNING: Check your Environment Variables.")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
IST = pytz.timezone('Asia/Kolkata')

# --- 2. DATABASE ---

class Database:
    def __init__(self, uri):
        self.client = AsyncIOMotorClient(uri)
        self.db = self.client['TelegramBotDB']
        self.users = self.db['users']
        self.ban_list = self.db['global_bans']

    async def add_user(self, user_id, name, username, source="organic"):
        user = await self.users.find_one({"_id": user_id})
        if not user:
            await self.users.insert_one({
                "_id": user_id,
                "name": name,
                "username": username,
                "joined_date": datetime.datetime.now(IST),
                "status": "active",
                "source": source
            })
            return True 
        else:
            await self.users.update_one({"_id": user_id}, {"$set": {"status": "active"}})
            return False

    async def update_block_status(self, user_id, status="blocked"):
        await self.users.update_one({"_id": user_id}, {"$set": {"status": status}})

    async def is_banned(self, user_id):
        user = await self.ban_list.find_one({"_id": user_id})
        return user is not None
    
    async def ban_user(self, user_id, reason="Spam"):
        await self.ban_list.update_one(
            {"_id": user_id}, 
            {"$set": {"reason": reason, "banned_at": datetime.datetime.now(IST)}}, 
            upsert=True
        )

    async def unban_user(self, user_id):
        await self.ban_list.delete_one({"_id": user_id})

    async def get_full_stats(self):
        total = await self.users.count_documents({})
        blocked = await self.users.count_documents({"status": "blocked"})
        active = total - blocked
        now = datetime.datetime.now(IST)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_joins = await self.users.count_documents({"joined_date": {"$gte": start_of_day}})
        return total, active, blocked, today_joins

    async def get_source_stats(self):
        pipeline = [
            {"$group": {"_id": "$source", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10}
        ]
        cursor = self.users.aggregate(pipeline)
        stats = {}
        async for doc in cursor:
            stats[doc['_id']] = doc['count']
        return stats

db = None
if MONGO_URL:
    try:
        db = Database(MONGO_URL)
        print("✅ MongoDB Connected")
    except Exception as e:
        print(f"❌ MongoDB Error: {e}")

# --- 3. BOT INIT ---

bots = []
if BOT_TOKENS:
    for token in BOT_TOKENS:
        if not token.strip(): continue
        bot = AsyncTeleBot(token.strip(), parse_mode='HTML')
        bots.append(bot)

# --- 4. HTML TEMPLATES ---

PREVIEW_IMAGE = "https://telegra.ph/file/p5a5a5a5a5a5a.jpg" 

START_HTML = """
<a href="{img}">&#8203;</a><tg-emoji emoji-id="6321173922398084063">⭐</tg-emoji> Hey {name} Welcome to <tg-emoji emoji-id="6323306309236038626">🍿</tg-emoji> Bot <tg-emoji emoji-id="6321320290588565035">🤖</tg-emoji>

<tg-emoji emoji-id="6321325964240362008">❗️</tg-emoji> <b>ᴘᴏᴡᴇʀғᴜʟ ᴀᴜᴛᴏ-ғɪʟᴛᴇʀ ʙᴏᴛ</b> <tg-emoji emoji-id="6321119462212770863">🗣️</tg-emoji>

<tg-emoji emoji-id="6321325964240362008">❗️</tg-emoji> <b>ɪ ᴄᴀɴ ᴘʀᴏᴠɪᴅᴇ ᴀʟʟ ᴍᴏᴠɪᴇs ᴀɴᴅ ᴡᴇʙ sᴇʀɪᴇs</b><tg-emoji emoji-id="5375464961822695044">🎬</tg-emoji>

<tg-emoji emoji-id="5258396243666681152">🔎</tg-emoji> <b>ᴊᴜsᴛ sᴇɴᴅ ᴛʜᴇ ɢᴏᴏɢʟᴇ sᴘᴇʟʟɪɴɢ!</b><tg-emoji emoji-id="5454370584861384827">🔍</tg-emoji>

<tg-emoji emoji-id="6321228227964574392">ℹ️</tg-emoji> <b>ᴊᴏ ʙʜɪ ᴍᴏᴠɪᴇ/ᴡᴇʙsᴇʀɪᴇs ᴅᴇᴋʜɴᴀ ʜᴏ ᴇɴɢʟɪsʜ ᴍᴇɴ ᴜsᴋᴀ ɴᴀᴀᴍ ʙʜᴇᴊᴇ.</b><tg-emoji emoji-id="6323223570986048376">✍️</tg-emoji><tg-emoji emoji-id="6323224799346695416">🍿</tg-emoji>

<tg-emoji emoji-id="6323322084650916948">🟩</tg-emoji><tg-emoji emoji-id="6323498813965213364">🟩</tg-emoji><tg-emoji emoji-id="6320925046223150523">🟩</tg-emoji><tg-emoji emoji-id="6320951799574436533">🟩</tg-emoji><tg-emoji emoji-id="6323445633680154253">🟩</tg-emoji><tg-emoji emoji-id="6321303986892708556">🟩</tg-emoji><tg-emoji emoji-id="6323535943957487433">🟩</tg-emoji><tg-emoji emoji-id="6323113439434644381">🟩</tg-emoji>
"""

ADS_HTML = """
<tg-emoji emoji-id="6320901479737597120">☄️</tg-emoji> <b>Bot नाम के नीचे अगर विज्ञापन (ads) दिखे तो उस पर 3- 4 बार क्लिक कर दे,</b> <tg-emoji emoji-id="6320837317221162843">⚠️</tg-emoji>

<tg-emoji emoji-id="6320901479737597120">☄️</tg-emoji><b>Click 4-5 times on (Ads) below bot name to cancel it</b> <tg-emoji emoji-id="6320837317221162843">⚠️</tg-emoji>
"""

REQST_HTML = """
<tg-emoji emoji-id="6321056944668810750">🙂</tg-emoji> <b>This Bot doesn't have permission to complete your request</b><tg-emoji emoji-id="6321186412162981920">🙌</tg-emoji><tg-emoji emoji-id="6321289040406519344">🙏</tg-emoji>

<tg-emoji emoji-id="6321295551576939276">🟢</tg-emoji><tg-emoji emoji-id="6323250174013479634">❄️</tg-emoji><b>Kindly use the Bot/group below</b>

<tg-emoji emoji-id="6323514039624277371">😊</tg-emoji><b>Click on buttons</b><tg-emoji emoji-id="6321119462212770863">🗣️</tg-emoji>
"""

ALERT_HTML = """
<tg-emoji emoji-id="5854688062566567731">🔮</tg-emoji><b>Above Message Will Be Deleted In 4 Min</b><tg-emoji emoji-id="5947290074319162163">⏱</tg-emoji>
"""

DELETE_HTML = """
<tg-emoji emoji-id="6321096110475583514">♨️</tg-emoji><b>Send another message To Get Link Again</b> <tg-emoji emoji-id="6321119462212770863">🗣️</tg-emoji>
"""

BL_HTML = """
<tg-emoji emoji-id="6320837317221162843">⚠️</tg-emoji><tg-emoji emoji-id="6323541003428964949">❗️</tg-emoji><tg-emoji emoji-id="6320974773354503135">❗️</tg-emoji><tg-emoji emoji-id="6323497568424696886">❗️</tg-emoji><tg-emoji emoji-id="6323504637940866342">❗️</tg-emoji><tg-emoji emoji-id="6320868013352426245">❗️</tg-emoji><tg-emoji emoji-id="6320812887447182178">❗️</tg-emoji><tg-emoji emoji-id="6323444675902447251">❗️</tg-emoji><tg-emoji emoji-id="6323404960339860176">❗️</tg-emoji><tg-emoji emoji-id="6321227244417064040">❗️</tg-emoji><tg-emoji emoji-id="6321119462212770863">🗣️</tg-emoji> ㅤ 
"""

# --- 5. BACKGROUND LOGIC ---

async def handle_sequence(bot, chat_id, reqst_msg_id):
    await asyncio.sleep(180)
    try:
        await bot.delete_message(chat_id, reqst_msg_id)
    except:
        pass

    bot_me = await bot.get_me()
    button = types.InlineKeyboardMarkup()
    button.add(types.InlineKeyboardButton("👀Start Now🌻", url=f"https://t.me/{bot_me.username}?start=return"))
    
    try:
        del_msg = await bot.send_message(
            chat_id, 
            DELETE_HTML, 
            reply_markup=button
        )
        try:
            await bot.pin_chat_message(chat_id, del_msg.message_id, disable_notification=False)
        except Exception as e:
            logger.error(f"Pin Error: {e}")
            
    except Exception as e:
        logger.error(f"Error sending Delete Text: {e}")

    try:
        bl_msg = await bot.send_message(chat_id, BL_HTML)
        if PIN_BL:
            try: await bot.pin_chat_message(chat_id, bl_msg.message_id, disable_notification=False)
            except: pass
    except:
        pass

# --- 6. HANDLERS ---

def register_handlers(bot: AsyncTeleBot):
    
    # --- START HANDLER ---
    @bot.message_handler(commands=['start'])
    async def start_command(message):
        user_id = message.from_user.id
        
        if db and await db.is_banned(user_id): return 

        args = message.text.split()
        source = "organic"
        if len(args) > 1:
            source = args[1]

        custom_mention = f'<a href="tg://user?id={user_id}">{message.from_user.first_name}</a>'

        is_new = False
        if db:
            is_new = await db.add_user(user_id, message.from_user.first_name, message.from_user.username, source)

        if is_new and source != "return":
            log_text = (
                f"#New_User\n"
                f"User: {custom_mention}\n"
                f"ID: <code>{user_id}</code>\n"
                f"Source: {source}"
            )
            try:
                await bot.send_message(LOG_CHANNEL, log_text)
            except:
                pass

        try:
            start_msg = await bot.reply_to(
                message, 
                START_HTML.format(name=custom_mention, img=PREVIEW_IMAGE)
            )
            if PIN_START:
                try: await bot.pin_chat_message(message.chat.id, start_msg.message_id, disable_notification=False)
                except: pass

            ads_msg = await bot.reply_to(message, ADS_HTML)
            if PIN_ADS or ADS_RAW_PIN:
                try: await bot.pin_chat_message(message.chat.id, ads_msg.message_id, disable_notification=False)
                except: pass

        except Exception as e:
            logger.error(f"Start Error: {e}")

    # --- ADMIN STATS ---
    @bot.message_handler(commands=['stats'])
    async def stats_command(message):
        if message.from_user.id not in ADMIN_IDS: return
        if not db: return
        total, active, blocked, today = await db.get_full_stats()
        sources = await db.get_source_stats()
        
        sources_text = ""
        for src, count in sources.items(): 
            sources_text += f"• {src}: {count}\n"

        text = (
            f"<tg-emoji emoji-id='6321052714126025714'>📊</tg-emoji> <b>BOT STATISTICS</b>\n\n"
            f"<tg-emoji emoji-id='6321128013492657577'>👥</tg-emoji> <b>Total Users:</b> {total}\n"
            f"<tg-emoji emoji-id='6320924492172369146'>✅</tg-emoji> <b>Active:</b> {active}\n"
            f"<tg-emoji emoji-id='5413879192267805083'>🗓</tg-emoji> <b>Joined Today:</b> {today}\n\n"
            f"<tg-emoji emoji-id='5260730055880876557'>⛓</tg-emoji> <b>Top Sources:</b>\n"
            f"{sources_text}"
        )
        await bot.reply_to(message, text)

    # --- BROADCAST ---
    @bot.message_handler(commands=['broadcast'])
    async def broadcast_command(message):
        if message.from_user.id not in ADMIN_IDS: return
        if not message.reply_to_message:
            await bot.reply_to(message, "Reply to a message to broadcast.")
            return

        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("Yes, Pin it 📌", callback_data="bc_pin_yes"),
            types.InlineKeyboardButton("No, Just Send 📨", callback_data="bc_pin_no")
        )
        await bot.reply_to(message, "Pin message?", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("bc_pin_"))
    async def broadcast_callback(call):
        should_pin = "yes" in call.data
        original_msg = call.message.reply_to_message
        await bot.edit_message_text("🚀 Broadcast started...", call.message.chat.id, call.message.message_id)
        
        users_cursor = db.users.find({}, {"_id": 1})
        sent, blocked, failed = 0, 0, 0
        
        async for user in users_cursor:
            user_id = user['_id']
            try:
                msg = await bot.copy_message(chat_id=user_id, from_chat_id=original_msg.chat.id, message_id=original_msg.message_id)
                if should_pin:
                    try: await bot.pin_chat_message(user_id, msg.message_id)
                    except: pass
                sent += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                if "blocked" in str(e).lower() or "user is deactivated" in str(e).lower():
                    await db.update_block_status(user_id, "blocked")
                    blocked += 1
                else:
                    failed += 1
        
        await bot.send_message(call.message.chat.id, f"✅ <b>Broadcast Completed</b>\nSent: {sent}\nBlocked: {blocked}\nFailed: {failed}")

    # --- BAN ---
    @bot.message_handler(commands=['ban'])
    async def ban_command(message):
        if message.from_user.id not in ADMIN_IDS: return
        try:
            target_id = int(message.text.split()[1])
            await db.ban_user(target_id, "Spam")
            await bot.reply_to(message, f"🚫 User <code>{target_id}</code> banned.")
        except:
            await bot.reply_to(message, "Usage: /ban user_id")

    # --- MAIN REPLY FLOW ---
    @bot.message_handler(func=lambda m: True)
    async def echo_all(message):
        if message.chat.type != 'private': return
        if db and await db.is_banned(message.from_user.id): return

        try:
            req_markup = types.InlineKeyboardMarkup()
            req_markup.add(
                types.InlineKeyboardButton(" Use this Bot 🟢", url="https://t.me/ThemovieQ1bot"),
                types.InlineKeyboardButton(" Join and search in group 🟢", url="https://t.me/iPopkornMovies_Group")
            )

            req_msg = await bot.reply_to(
                message,
                REQST_HTML, 
                reply_markup=req_markup
            )

            alert_msg = await bot.reply_to(
                message,
                ALERT_HTML
            )
            
            if PIN_ALERT:
                try: await bot.pin_chat_message(message.chat.id, alert_msg.message_id, disable_notification=False)
                except: pass

            asyncio.create_task(handle_sequence(bot, message.chat.id, req_msg.message_id))

        except Exception as e:
            logger.error(f"Reply Flow Error: {e}")

for bot in bots:
    register_handlers(bot)

# --- 7. SCHEDULED TASKS ---

async def send_daily_report():
    if not bots: return
    try:
        total, active, blocked, today = await db.get_full_stats()
        sources = await db.get_source_stats()
        report = f"🌅 <b>DAILY REPORT (05:30 IST)</b>\n\n📅 <b>Users Joined Today:</b> {today}\n👥 <b>Total Active:</b> {active}\n🚫 <b>Blocked:</b> {blocked}\n\n🔗 <b>Top Sources:</b>\n"
        for src, count in sources.items(): report += f"• {src}: {count}\n"
        await bots[0].send_message(LOG_CHANNEL, report)
    except Exception as e:
        logger.error(f"Daily Report Failed: {e}")

scheduler = AsyncIOScheduler()
scheduler.add_job(send_daily_report, 'cron', hour=5, minute=30, timezone=IST)

# --- 8. KOYEB HEALTH CHECK SERVER ---

async def health_check(request):
    return web.Response(text="Bot Running")

async def start_web_server():
    # Koyeb sets the PORT environment variable.
    port = int(os.environ.get("PORT", 8080))
    app = web.Application()
    app.add_routes([web.get('/', health_check)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌍 Web Server running on port {port}")

# --- 9. RUN ---

async def main():
    print(f"🚀 Starting {len(bots)} Bots (Telebot)...")
    
    # 1. Start Web Server (CRITICAL for Koyeb)
    await start_web_server()

    # 2. Send Startup Log
    active_bot_usernames = []
    for bot in bots:
        try:
            me = await bot.get_me()
            active_bot_usernames.append(f"@{me.username}")
        except Exception:
            pass
    
    if active_bot_usernames and LOG_CHANNEL:
        try:
            log_text = f"🚀 <b>Bot Restarted!</b>\n\n✅ <b>Active Bots ({len(active_bot_usernames)}):</b>\n" + "\n".join(active_bot_usernames)
            await bots[0].send_message(LOG_CHANNEL, log_text)
        except Exception as e:
            logger.error(f"Startup Log Error: {e}")

    # 3. Start Polling
    scheduler.start()
    await asyncio.gather(*(bot.polling(non_stop=True) for bot in bots))

if __name__ == "__main__":
    asyncio.run(main())
