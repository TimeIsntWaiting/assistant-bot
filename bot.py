import os
import sys
import logging
import asyncio
import datetime
import dns.resolver

# --- 1. AUTO-UPDATE & DEPENDENCIES ---
try:
    import pyrogram
    import pytz 
    from aiohttp import web # REQUIRED FOR KOYEB FREE TIER
    from pyrogram import Client, filters, enums, idle
    from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
    from pyrogram.errors import FloodWait, InputUserDeactivated, UserIsBlocked, PeerIdInvalid
    from motor.motor_asyncio import AsyncIOMotorClient
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from dotenv import load_dotenv
except ImportError:
    print("📦 Installing requirements...")
    os.system("pip install -U pyrogram tgcrypto motor dnspython python-dotenv pytz apscheduler aiohttp")
    print("✅ Done! Restarting...")
    os.execv(sys.executable, [sys.executable] + sys.argv)

# --- 2. CONFIGURATION ---

# Fix Google DNS
dns.resolver.default_resolver = dns.resolver.Resolver(configure=False)
dns.resolver.default_resolver.nameservers = ['8.8.8.8']

# FORCE LOAD .env
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, ".env")
load_dotenv(env_path)

# Helper to load boolean env vars
def get_bool(key, default="False"):
    return os.getenv(key, default).lower() in ["true", "1", "yes", "on"]

# Load Variables
try:
    API_ID = int(os.getenv("API_ID", "0")) # Default to 0 to prevent crash before validation
    API_HASH = os.getenv("API_HASH", "")
    BOT_TOKENS = os.getenv("BOT_TOKEN", "").split(",")
    MONGO_URL = os.getenv("MONGO_URL", "")
    LOG_CHANNEL = int(os.getenv("LOG_CHANNEL_ID", "0"))
    
    # Validation
    if API_ID == 0 or not API_HASH or not BOT_TOKENS or not MONGO_URL:
        # If running on cloud, variables might not be loaded yet, skip exit
        if not os.getenv("KOYEB_APP_NAME"): 
            print("❌ ERROR: Missing Env Variables!")
            # exit() # Commented out to allow web server to start if needed for debugging

    # ADMIN IDS
    _admin_ids = os.getenv("ADMIN_IDS", "")
    ADMIN_IDS = [int(x) for x in _admin_ids.split(",") if x]
    
    # PIN CONFIGURATIONS
    PIN_START = get_bool("PIN_START_RAW", "False")
    PIN_ADS   = get_bool("PIN_ADS_RAW", "False")
    PIN_ALERT = get_bool("PIN_ALERT_RAW", "False")
    PIN_BL    = get_bool("PIN_BL_RAW", "False")
    ADS_RAW_PIN = get_bool("ADS_RAW_PIN", "False")

except (TypeError, AttributeError, ValueError) as e:
    print(f"\n❌ Configuration Error: {e}")

# Setup Logging
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)
IST = pytz.timezone('Asia/Kolkata')

# --- 3. DATABASE ---

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

try:
    if MONGO_URL:
        db = Database(MONGO_URL)
    else:
        db = None
except Exception as e:
    print(f"❌ MongoDB Error: {e}")
    exit()

# --- 4. CLIENT INIT ---

apps = []
if BOT_TOKENS:
    for i, token in enumerate(BOT_TOKENS):
        if not token.strip(): continue
        app = Client(name=f"bot_{i}", api_id=API_ID, api_hash=API_HASH, bot_token=token.strip())
        apps.append(app)

# --- 5. TEXT TEMPLATES ---

def make_bold(text, **kwargs):
    formatted = text.format(**kwargs)
    return f"**{formatted}**"

START_RAW = """
![⭐](tg://emoji?id=6321173922398084063) Hey {name} Welcome to ![🍿](tg://emoji?id=6323306309236038626) Bot ![🤖](tg://emoji?id=6321320290588565035)

![❗️](tg://emoji?id=6321325964240362008) ᴘᴏᴡᴇʀғᴜʟ ᴀᴜᴛᴏ-ғɪʟᴛᴇʀ ʙᴏᴛ ![🗣️](tg://emoji?id=6321119462212770863)

![❗️](tg://emoji?id=6321325964240362008) ɪ ᴄᴀɴ ᴘʀᴏᴠɪᴅᴇ ᴀʟʟ ᴍᴏᴠɪᴇs ᴀɴᴅ ᴡᴇʙ sᴇʀɪᴇs![🎬](tg://emoji?id=5375464961822695044)

![🔎](tg://emoji?id=5258396243666681152) ᴊᴜsᴛ sᴇɴᴅ ᴛʜᴇ ɢᴏᴏɢʟᴇ sᴘᴇʟʟɪɴɢ![🔍](tg://emoji?id=5454370584861384827)

![ℹ️](tg://emoji?id=6321228227964574392) ᴊᴏ ʙʜɪ ᴍᴏᴠɪᴇ/ᴡᴇʙsᴇʀɪᴇs ᴅᴇᴋʜɴᴀ ʜᴏ ᴇɴɢʟɪsʜ ᴍᴇɴ ᴜsᴋᴀ ɴᴀᴀᴍ ʙʜᴇᴊᴇ.![✍️](tg://emoji?id=6323223570986048376)![🍿](tg://emoji?id=6323224799346695416)

![🟩](tg://emoji?id=6323322084650916948)![🟩](tg://emoji?id=6323498813965213364)![🟩](tg://emoji?id=6320925046223150523)![🟩](tg://emoji?id=6320951799574436533)![🟩](tg://emoji?id=6323445633680154253)![🟩](tg://emoji?id=6321303986892708556)![🟩](tg://emoji?id=6323535943957487433)![🟩](tg://emoji?id=6323113439434644381)
"""

ADS_RAW = """
![☄️](tg://emoji?id=6320901479737597120) Bot नाम के नीचे अगर विज्ञापन (ads) दिखे तो उस पर 3- 4 बार क्लिक कर दे, ![⚠️](tg://emoji?id=6320837317221162843)

![☄️](tg://emoji?id=6320901479737597120)Click 4-5 times on (Ads) below bot name to cancel it ![⚠️](tg://emoji?id=6320837317221162843)
"""

REQST_RAW = """
![🙂](tg://emoji?id=6321056944668810750) This Bot doesn't have permission to complete your request![🙌](tg://emoji?id=6321186412162981920)![🙏](tg://emoji?id=6321289040406519344)

![🟢](tg://emoji?id=6321295551576939276)![❄️](tg://emoji?id=6323250174013479634)Kindly use the Bot/group below

![😊](tg://emoji?id=6323514039624277371)Click on buttons![🗣️](tg://emoji?id=6321119462212770863)
"""

ALERT_RAW = """
![🔮](tg://emoji?id=5854688062566567731)Above Message Will Be Deleted In 4 Min![⏱](tg://emoji?id=5947290074319162163)
"""

DELETE_RAW = """
![♨️](tg://emoji?id=6321096110475583514)Send another message To Get Link Again ![🗣️](tg://emoji?id=6321119462212770863)
"""

BL_RAW = """
![⚠️](tg://emoji?id=6320837317221162843)![❗️](tg://emoji?id=6323541003428964949)![❗️](tg://emoji?id=6320974773354503135)![❗️](tg://emoji?id=6323497568424696886)![❗️](tg://emoji?id=6323504637940866342)![❗️](tg://emoji?id=6320868013352426245)![❗️](tg://emoji?id=6320812887447182178)![❗️](tg://emoji?id=6323444675902447251)![❗️](tg://emoji?id=6323404960339860176)![❗️](tg://emoji?id=6321227244417064040)![🗣️](tg://emoji?id=6321119462212770863)
"""

# --- 6. BACKGROUND LOGIC ---

async def handle_sequence(client, chat_id, reqst_msg_id):
    await asyncio.sleep(180)
    try:
        await client.delete_messages(chat_id, reqst_msg_id)
    except:
        pass

    me = await client.get_me()
    button = InlineKeyboardMarkup([[
        InlineKeyboardButton("👀Start Now🌻", url=f"https://t.me/{me.username}?start=return")
    ]])
    
    try:
        # SEND DELETE TEXT
        del_msg = await client.send_message(
            chat_id, 
            make_bold(DELETE_RAW), 
            reply_markup=button, 
            parse_mode=enums.ParseMode.MARKDOWN
        )
        # Always pin DELETE_RAW
        try:
            await del_msg.pin(disable_notification=False, both_sides=True)
        except Exception as e:
            print(f"⚠️ Failed to pin DELETE_TEXT: {e}")
            
    except Exception as e:
        logger.error(f"Error sending Delete Text: {e}")

    try:
        # SEND BL TEXT
        bl_msg = await client.send_message(chat_id, make_bold(BL_RAW), parse_mode=enums.ParseMode.MARKDOWN)
        if PIN_BL:
            try: await bl_msg.pin(disable_notification=False, both_sides=True)
            except Exception as e: print(f"⚠️ Failed to pin BL_RAW: {e}")
    except:
        pass

# --- 7. HANDLERS ---

def register_handlers(app: Client):
    
    # --- START HANDLER ---
    @app.on_message(filters.command("start") & filters.private)
    async def start_handler(client: Client, message: Message):
        user_id = message.from_user.id
        
        if db and await db.is_banned(user_id): return 

        source = "organic"
        if len(message.command) > 1:
            source = message.command[1]

        fname = message.from_user.first_name
        lname = message.from_user.last_name if message.from_user.last_name else ""
        full_name = f"{fname} {lname}".strip()
        custom_mention = f"[{full_name}](tg://user?id={user_id})"

        is_new = False
        if db:
            is_new = await db.add_user(user_id, message.from_user.first_name, message.from_user.username, source)

        if is_new and source != "return":
            log_text = (
                f"#New_User\n"
                f"User: {message.from_user.mention}\n"
                f"ID: `{user_id}`\n"
                f"Source: {source}"
            )
            try:
                await client.send_message(LOG_CHANNEL, log_text)
            except:
                pass

        try:
            # SEND START RAW
            start_msg = await message.reply_text(make_bold(START_RAW, name=custom_mention), parse_mode=enums.ParseMode.MARKDOWN)
            if PIN_START:
                try: await start_msg.pin(disable_notification=False, both_sides=True)
                except Exception as e: print(f"⚠️ Failed to pin START_RAW: {e}")

            # SEND ADS RAW
            ads_msg = await message.reply_text(make_bold(ADS_RAW), parse_mode=enums.ParseMode.MARKDOWN)
            if PIN_ADS or ADS_RAW_PIN:
                try: await ads_msg.pin(disable_notification=False, both_sides=True)
                except Exception as e: print(f"⚠️ Failed to pin ADS_RAW: {e}")

        except Exception as e:
            logger.error(f"Start Error: {e}")

    # --- ADMIN: STATS ---
    @app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
    async def stats_handler(client: Client, message: Message):
        if not db: return
        total, active, blocked, today = await db.get_full_stats()
        sources = await db.get_source_stats()
        
        text = (
            f"📊 **BOT STATISTICS**\n\n"
            f"👥 **Total Users:** {total}\n"
            f"✅ **Active:** {active}\n"
            f"🚫 **Blocked:** {blocked}\n"
            f"📅 **Joined Today:** {today}\n\n"
            f"🔗 **Top Sources:**\n"
        )
        for src, count in sources.items():
            text += f"• {src}: {count}\n"
        await message.reply_text(text)

    # --- ADMIN: BROADCAST ---
    @app.on_message(filters.command("broadcast") & filters.user(ADMIN_IDS) & filters.reply)
    async def broadcast_request(client: Client, message: Message):
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("Yes, Pin it 📌", callback_data="bc_pin_yes")],
            [InlineKeyboardButton("No, Just Send 📨", callback_data="bc_pin_no")]
        ])
        await message.reply_text("Do you want to Pin this message?", reply_to_message_id=message.reply_to_message.id, reply_markup=buttons)

    @app.on_callback_query(filters.regex("bc_pin_"))
    async def broadcast_execute(client: Client, callback: CallbackQuery):
        should_pin = "yes" in callback.data
        original_msg = callback.message.reply_to_message
        await callback.message.edit_text("🚀 Broadcast started... This will take time.")
        
        users_cursor = db.users.find({}, {"_id": 1})
        sent = 0
        blocked = 0
        failed = 0
        
        async for user in users_cursor:
            user_id = user['_id']
            try:
                msg = await original_msg.copy(chat_id=user_id)
                if should_pin:
                    try: await msg.pin(disable_notification=False, both_sides=True)
                    except: pass
                sent += 1
                await asyncio.sleep(0.05)
            except FloodWait as e:
                await asyncio.sleep(e.value)
                try: await original_msg.copy(chat_id=user_id)
                except: failed += 1
            except (InputUserDeactivated, UserIsBlocked, PeerIdInvalid):
                await db.update_block_status(user_id, "blocked")
                blocked += 1
            except Exception:
                failed += 1
        
        await callback.message.reply_text(
            f"✅ **Broadcast Completed**\n\n"
            f"📨 Sent: {sent}\n"
            f"🚫 Blocked: {blocked}\n"
            f"❌ Failed: {failed}"
        )

    # --- ADMIN: GLOBAL BAN ---
    @app.on_message(filters.command("ban") & filters.user(ADMIN_IDS))
    async def global_ban(client: Client, message: Message):
        try:
            target_id = int(message.command[1])
            await db.ban_user(target_id, "Spam")
            await message.reply_text(f"🚫 User `{target_id}` banned.")
        except:
            await message.reply_text("Usage: /ban user_id")

    # --- MAIN REPLY FLOW ---
    @app.on_message(filters.private & ~filters.command(["start", "broadcast", "stats", "ban", "unban"]))
    async def reply_flow(client: Client, message: Message):
        if db and await db.is_banned(message.from_user.id): return

        try:
            req_buttons = InlineKeyboardMarkup([
                [InlineKeyboardButton(" Use this Bot 🟢", url="https://t.me/botsexpertbot")],
                [InlineKeyboardButton(" Join and search in group 🟢", url="https://t.me/groupusername")]
            ])

            req_msg = await message.reply_text(
                make_bold(REQST_RAW), 
                reply_markup=req_buttons,
                parse_mode=enums.ParseMode.MARKDOWN
            )

            alert_msg = await message.reply_text(
                make_bold(ALERT_RAW),
                parse_mode=enums.ParseMode.MARKDOWN
            )
            # PIN ALERT IF ENABLED
            if PIN_ALERT:
                try: await alert_msg.pin(disable_notification=False, both_sides=True)
                except Exception as e: print(f"⚠️ Failed to pin ALERT_RAW: {e}")

            asyncio.create_task(handle_sequence(client, message.chat.id, req_msg.id))

        except Exception as e:
            logger.error(f"Reply Flow Error: {e}")

for app in apps:
    register_handlers(app)

# --- 8. DAILY REPORT SCHEDULER (5:30 AM IST) ---

async def send_daily_report():
    if not apps or not db: return
    try:
        total, active, blocked, today = await db.get_full_stats()
        sources = await db.get_source_stats()
        
        report = (
            f"🌅 **DAILY REPORT (05:30 IST)**\n\n"
            f"📅 **Users Joined Last 24h:** {today}\n"
            f"👥 **Total Active Users:** {active}\n"
            f"🚫 **Blocked Users:** {blocked}\n\n"
            f"🔗 **Top Sources:**\n"
        )
        for src, count in sources.items():
            report += f"• {src}: {count}\n"
        await apps[0].send_message(LOG_CHANNEL, report)
    except Exception as e:
        logger.error(f"Daily Report Failed: {e}")

scheduler = AsyncIOScheduler()
scheduler.add_job(send_daily_report, 'cron', hour=5, minute=30, timezone=IST)

# --- 9. DUMMY WEB SERVER FOR KOYEB FREE TIER ---

async def web_handler(request):
    return web.Response(text="Bot is Running")

async def start_web_server():
    port = int(os.environ.get("PORT", 8000))
    app = web.Application()
    app.add_routes([web.get('/', web_handler)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌍 Web Server running on port {port}")

# --- 10. RUN ---

async def main():
    print(f"🚀 Starting {len(apps)} Bots...")
    
    # Start Web Server First (Important for Health Checks)
    await start_web_server()
    
    scheduler.start()
    await asyncio.gather(*[app.start() for app in apps])
    print("✅ Bots are Online!")
    await idle()
    await asyncio.gather(*[app.stop() for app in apps])

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
