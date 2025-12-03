import os
import logging
import threading
import asyncio
from flask import Flask
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ConversationHandler
from supabase import create_client, Client

# 1. Configuration Setup
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID", 0))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))

# Conversation States
WAITING_EMAIL, WAITING_PASSWORD, WAITING_MASS_ORDER, WAITING_SUPPORT_ID = range(4)
ORDER_WAITING_LINK, ORDER_WAITING_QTY, ORDER_CONFIRM = range(4, 7)

# Logging Setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Supabase Setup
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- FLASK SERVER (For UptimeRobot) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive and running!", 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# --- HELPER FUNCTIONS ---

def get_user(tg_id):
    """Telegram ID ဖြင့် User ရှာခြင်း"""
    res = supabase.table('users').select("*").eq('telegram_id', tg_id).execute()
    return res.data[0] if res.data else None

def calculate_cost(quantity, service_data, user_currency='USD'):
    """ဈေးနှုန်းတွက်ချက်ခြင်း Formula"""
    per_qty = int(service_data.get('per_quantity', 1000))
    if per_qty == 0: per_qty = 1000
    
    # Currency အလိုက် ဈေးနှုန်းယူခြင်း (လက်ရှိမှာ USD default)
    # အနာဂတ်တွင် MMK column ပါလာပါက ဒီနေရာတွင် logic ထည့်နိုင်သည်
    sell_price = float(service_data.get('sell_price', 0))
    
    return (quantity / per_qty) * sell_price

# Channel တွင်ပြမည့် ပုံစံ (အတိုချုံး)
def format_for_channel(service):
    name = service.get('service_name', 'Unknown')
    min_qty = service.get('min', 0)
    max_qty = service.get('max', 0)
    display_id = service.get('id')

    return (
        f"🔥 *{name}*\n\n"
        f"🆔 *ID:* `{display_id}`\n"
        f"📉 *Min:* {min_qty} | 📈 *Max:* {max_qty}\n\n"
        f"👇 *မှာယူရန် အောက်ပါခလုတ်ကို နှိပ်ပါ*"
    )

# User မှာယူချိန်တွင်ပြမည့် ပုံစံ (အပြည့်အစုံ - Note & Price ပါဝင်)
def format_for_user(service, user_lang='en', user_currency='USD'):
    name = service.get('service_name', 'Unknown')
    price = float(service.get('sell_price', 0))
    min_qty = service.get('min', 0)
    max_qty = service.get('max', 0)
    per_qty = service.get('per_quantity', 1000)

    # Language Logic
    if user_lang == 'mm':
        raw_note = service.get('note_mm') or ""
    else:
        raw_note = service.get('note_eng') or ""
    
    description = raw_note.replace("\\n", "\n").strip()
    currency_symbol = "$" if user_currency == 'USD' else "Ks"

    return (
        f"✅ **Selected Service**\n"
        f"🔥 *{name}*\n"
        f"🆔 *ID:* `{service.get('id')}`\n"
        f"💵 *Price:* {currency_symbol}{price} (per {per_qty})\n"
        f"📉 *Limit:* {min_qty} - {max_qty}\n\n"
        f"📝 *Description:*\n{description}"
    )
    # --- AUTHENTICATION FLOW (Login/Register) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = get_user(user.id)
    args = context.args

    # 1. Login မဝင်ရသေးလျင်
    if not db_user:
        keyboard = [
            [InlineKeyboardButton("🔐 Login (Website အကောင့်ဖြင့်)", callback_data="login_flow")],
            [InlineKeyboardButton("📝 Register (အကောင့်ဖွင့်ရန်)", url="https://k2boostweb.com/createaccount")]
        ]
        await update.message.reply_text(
            f"မင်္ဂလာပါ {user.first_name}! 👋\n"
            "K2 Boost Bot မှ ကြိုဆိုပါသည်။ ဝန်ဆောင်မှုရယူရန် Login ဝင်ပါ။",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # 2. Deep Link (Channel က Order နှိပ်လာလျင်)
    if args and args[0].startswith("order_"):
        local_id = args[0].split("_")[1]
        await update.message.reply_text(
            f"✅ Service ID: `{local_id}` ကို ရွေးချယ်ထားပါသည်။\n\n"
            f"အော်ဒါတင်ရန် နှိပ်ပါ 👉 /neworder {local_id}",
            parse_mode='Markdown'
        )
    else:
        # Normal Logged In User
        await update.message.reply_text(
            f"မင်္ဂလာပါ {db_user.get('email')}! 👋\n\n"
            "အောက်ပါ Command များကို အသုံးပြုနိုင်ပါသည်:\n"
            "👉 /services - ဝန်ဆောင်မှုများ ကြည့်ရန်\n"
            "👉 /neworder <ID> - အော်ဒါတင်ရန်\n"
            "👉 /help - အကောင့်လက်ကျန်နှင့် အကူအညီ"
        )

# Login Step 1: Ask Email
async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Update State in DB to 1 (Waiting Email)
    user_id = update.effective_user.id
    # Note: If user row doesn't exist yet, we rely on ContextHandler RAM state here first
    
    await query.edit_message_text("📧 သင့် Website Email ကို ရိုက်ထည့်ပေးပါ:")
    return WAITING_EMAIL

# Login Step 2: Receive Email & Ask Password
async def receive_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip().lower()
    context.user_data['login_email'] = email
    
    await update.message.reply_text(
        "🔑 **Password** ကို ရိုက်ထည့်ပေးပါ:\n"
        "(လုံခြုံရေးအရ သင်ရိုက်လိုက်သော Password ကို Bot မှ Auto ဖျက်ပေးပါမည်)",
        parse_mode='Markdown'
    )
    return WAITING_PASSWORD

# Login Step 3: Verify Password
async def receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    email = context.user_data.get('login_email')
    
    # Auto Delete Password Message
    try: await update.message.delete()
    except: pass
    
    msg = await update.message.reply_text("🔄 Checking...")
    
    try:
        # Supabase Auth Login
        session = supabase.auth.sign_in_with_password({"email": email, "password": password})
        if session.user:
            # Link Telegram ID to User Row & Set Defaults
            supabase.table('users').update({
                'telegram_id': update.effective_user.id,
                'bot_state': 0, 
                'temp_data': {},
                # Ensure defaults if null
                'language': 'en',
                'currency': 'USD'
            }).eq('id', session.user.id).execute()
            
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id, 
                message_id=msg.message_id, 
                text=f"✅ **Login Successful!**\nAccount: {email}\n\n/services ကိုနှိပ်၍ စတင်နိုင်ပါပြီ。",
                parse_mode='Markdown'
            )
        else:
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="❌ Login Failed.")
            
    except Exception as e:
        logger.error(f"Login Error: {e}")
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id, 
            message_id=msg.message_id, 
            text="❌ Email သို့မဟုတ် Password မှားယွင်းနေပါသည်။\n/start ကိုနှိပ်၍ ပြန်ကြိုးစားပါ။"
        )
    
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Process Canceled.")
    return ConversationHandler.END

# --- BASIC USER COMMANDS ---

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db_user = get_user(user_id)
    if not db_user: return await update.message.reply_text("Login First: /start")

    balance = db_user.get('balance', 0)
    currency = db_user.get('currency', 'USD')
    symbol = "$" if currency == 'USD' else "Ks"

    text = (
        f"👤 **Account Info**\n"
        f"📧 Email: `{db_user.get('email')}`\n"
        f"💰 Balance: **{symbol}{balance:.4f}**\n\n"
        "📋 **Available Commands:**\n"
        "1️⃣ **/services** - ဈေးနှုန်းကြည့်ရန်\n"
        "2️⃣ **/neworder <ID>** - မှာယူရန်\n"
        "3️⃣ **/massorder** - အများကြီးမှာရန်\n"
        "4️⃣ **/history** - မှတ်တမ်းကြည့်ရန်\n"
        "5️⃣ **/check <ID>** - Status စစ်ရန်\n"
        "6️⃣ **/support** - အကူအညီတောင်းရန်"
    )
    await update.message.reply_text(text, parse_mode='Markdown')

async def services_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Channel Link
    channel_link = "https://t.me/YourChannelLink" # ပြင်ရန်
    await update.message.reply_text(
        f"🛍 **Services & Prices**\n\n"
        f"ဝန်ဆောင်မှုများကို ဤ Channel တွင် ကြည့်ရှုနိုင်ပါသည်:\n👉 {channel_link}\n\n"
        "*(Channel ထဲရှိ Post များအောက်က 'Order Now' ခလုတ်ကို နှိပ်၍ အလွယ်တကူ မှာယူနိုင်ပါသည်)*",
        disable_web_page_preview=True,
        parse_mode='Markdown'
    )

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db_user = get_user(user_id)
    if not db_user: return
    
    # Get last 5 orders
    orders = supabase.table('WebsiteOrders').select("*").eq('email', db_user['email']).order('id', desc=True).limit(5).execute().data
    
    if not orders:
        await update.message.reply_text("📝 Order မှတ်တမ်း မရှိသေးပါ။")
        return
        
    msg = "📜 **Recent Orders**\n\n"
    for o in orders:
        msg += f"🆔 `{o['id']}` | Svc: {o['service']}\n🔗 {o['link'][:20]}...\n📊 Qty: {o['quantity']} | Status: **{o['status']}**\n------------------\n"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Usage: `/check 123`", parse_mode='Markdown')
    
    ids_raw = " ".join(context.args).replace(" ", "")
    ids = ids_raw.split(',')
    msg = ""
    
    for oid in ids:
        if not oid.isdigit(): continue
        res = supabase.table('WebsiteOrders').select("status, start_count, remain").eq('id', oid).execute()
        if res.data:
            s = res.data[0]
            msg += f"🆔 `{oid}`: **{s['status']}** (Start: {s.get('start_count','-')})\n"
        else:
            msg += f"🆔 `{oid}`: ❌ Not Found\n"
            
    await update.message.reply_text(msg, parse_mode='Markdown')
    # --- NEW ORDER SYSTEM (Step-by-Step) ---

async def new_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db_user = get_user(user_id)
    if not db_user: return await update.message.reply_text("Login First.")

    # ID ပါမပါ စစ်ဆေးခြင်း
    if not context.args:
        await update.message.reply_text("⚠️ Service ID ထည့်ရန် လိုအပ်ပါသည်။\nExample: `/neworder 8`", parse_mode='Markdown')
        return ConversationHandler.END

    input_id = context.args[0] # Local ID (e.g., 8)
    
    # Database တွင် Local ID ဖြင့် ရှာဖွေခြင်း
    res = supabase.table('services').select("*").eq('id', input_id).execute()
    if not res.data:
        await update.message.reply_text("❌ Service ID မှားယွင်းနေပါသည်။")
        return ConversationHandler.END

    service = res.data[0]
    context.user_data['order_service'] = service
    
    # User ၏ Language/Currency ကို ယူမည် (Default: en, USD)
    user_lang = db_user.get('language', 'en')
    user_curr = db_user.get('currency', 'USD')
    context.user_data['user_currency'] = user_curr

    # User အတွက် အသေးစိတ် အချက်အလက် (Note & Price) ကို ဖော်ပြမည်
    full_info = format_for_user(service, user_lang, user_curr)
    
    # Type အလိုက် Link တောင်းပုံ ပြောင်းခြင်း
    prompt = "🔗 **Link** (URL) ကို ထည့်သွင်းပေးပါ:"
    if service.get('use_type') == 'Telegram username' or 'Stars' in service.get('service_name', ''):
        prompt = "🔗 **Telegram Username** ကို ထည့်သွင်းပေးပါ (Example: @username):"

    await update.message.reply_text(f"{full_info}\n\n{prompt}", parse_mode='Markdown')
    return ORDER_WAITING_LINK

async def new_order_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    context.user_data['order_link'] = link
    
    svc = context.user_data['order_service']
    await update.message.reply_text(f"📊 **Quantity** ထည့်ပါ (Min: {svc['min']} - Max: {svc['max']}):")
    return ORDER_WAITING_QTY

async def new_order_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qty_text = update.message.text.strip()
    if not qty_text.isdigit():
        await update.message.reply_text("❌ ဂဏန်းသာ ရိုက်ထည့်ပါ။")
        return ORDER_WAITING_QTY
    
    qty = int(qty_text)
    svc = context.user_data['order_service']
    
    if qty < svc['min'] or qty > svc['max']:
        await update.message.reply_text(f"❌ Quantity မမှန်ပါ။ {svc['min']} မှ {svc['max']} ကြား ရိုက်ပါ။")
        return ORDER_WAITING_QTY

    context.user_data['order_qty'] = qty
    
    # Calculate Cost based on currency
    user_curr = context.user_data.get('user_currency', 'USD')
    cost = calculate_cost(qty, svc, user_curr)
    context.user_data['order_cost'] = cost
    
    symbol = "$" if user_curr == 'USD' else "Ks"
    
    # Confirm Button
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data="confirm_yes"), InlineKeyboardButton("❌ Cancel", callback_data="confirm_no")]
    ])
    await update.message.reply_text(
        f"🧾 **Order Summary**\n"
        f"🔗 Link: {context.user_data['order_link']}\n"
        f"📊 Qty: {qty}\n"
        f"💵 Cost: **{symbol}{cost:.4f}**\n\n"
        f"မှာယူရန် သေချာပါသလား?",
        reply_markup=markup, parse_mode='Markdown'
    )
    return ORDER_CONFIRM

async def new_order_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "confirm_no":
        await query.edit_message_text("❌ Order Canceled.")
        return ConversationHandler.END
    
    user_id = update.effective_user.id
    db_user = get_user(user_id) # Refresh Balance
    cost = context.user_data['order_cost']
    
    if db_user['balance'] < cost:
        symbol = "$" if db_user.get('currency') == 'USD' else "Ks"
        await query.edit_message_text(f"❌ Balance မလောက်ပါ။ Need: {symbol}{cost:.4f}")
        return ConversationHandler.END
        
    # Process Order
    new_bal = float(db_user['balance']) - cost
    supabase.table('users').update({'balance': new_bal}).eq('telegram_id', user_id).execute()
    
    order_data = {
        "email": db_user['email'],
        "service": context.user_data['order_service']['service_id'], # Supplier ID for record
        "link": context.user_data['order_link'],
        "quantity": context.user_data['order_qty'],
        "buy_charge": cost,
        "status": "Pending",
        "UsedType": "NewOrder"
    }
    supabase.table('WebsiteOrders').insert(order_data).execute()
    await query.edit_message_text(f"✅ **Success!**\nBalance: {new_bal:.4f}", parse_mode='Markdown')
    return ConversationHandler.END

# --- MASS ORDER SYSTEM ---

async def mass_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not get_user(update.effective_user.id): return await update.message.reply_text("Login First.")
    
    await update.message.reply_text(
        "🚀 **Mass Order**\nFormat: `ID | Link | Quantity`\n\nExample:\n`8 | https://link1 | 1000`\n`9 | @username | 50`\n\n(စာရင်းကို ပို့ပေးပါ):",
        parse_mode='Markdown'
    )
    return WAITING_MASS_ORDER

async def process_mass_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lines = update.message.text.strip().split('\n')
    msg = await update.message.reply_text(f"🔄 Processing {len(lines)} orders...")
    
    report = "📊 **Result**\n"
    success, fail = 0, 0
    
    for i, line in enumerate(lines, 1):
        try:
            # Separator check
            parts = [p.strip() for p in line.split('|')] if '|' in line else [p.strip() for p in line.split(',')]
            if len(parts) != 3: raise Exception("Format Error")
            
            sid, link, qty = parts[0], parts[1], int(parts[2])
            
            # Fetch Service by Local ID
            res = supabase.table('services').select("*").eq('id', sid).execute()
            if not res.data: raise Exception("ID Not Found")
            svc = res.data[0]
            
            # Validation
            allowed = ['Default', 'Promote', 'Telegram username']
            if svc.get('use_type') not in allowed and 'Stars' not in svc.get('service_name',''):
                 raise Exception("Type Not Supported")
                 
            if qty < svc['min'] or qty > svc['max']: raise Exception("Qty Limit")
            
            # Smart Input Check
            is_username_type = (svc.get('use_type') == 'Telegram username' or 'Stars' in svc.get('service_name',''))
            if is_username_type and ('@' not in link and 't.me' not in link):
                raise Exception("Need @username")
            elif not is_username_type and 'http' not in link:
                raise Exception("Need URL")
                
            cost = calculate_cost(qty, svc) # Uses USD Default for mass order for simplicity
            u = get_user(user_id)
            if u['balance'] < cost: raise Exception("No Balance")
            
            # Execute
            new_bal = float(u['balance']) - cost
            supabase.table('users').update({'balance': new_bal}).eq('telegram_id', user_id).execute()
            supabase.table('WebsiteOrders').insert({
                "email": u['email'], "service": svc['service_id'], "link": link, "quantity": qty,
                "buy_charge": cost, "status": "Pending", "UsedType": "MassOrder"
            }).execute()
            
            report += f"✅ L{i}: Success (${cost:.4f})\n"
            success += 1
            
        except Exception as e:
            report += f"❌ L{i}: {e}\n"
            fail += 1
            
    if len(report) > 4000: report = report[:4000]
    await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text=report)
    return ConversationHandler.END

# --- SUPPORT SYSTEM ---

async def support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("Refill", callback_data="sup_Refill"), InlineKeyboardButton("Cancel", callback_data="sup_Cancel")],
          [InlineKeyboardButton("SpeedUp", callback_data="sup_SpeedUp"), InlineKeyboardButton("Other", callback_data="sup_Other")]]
    await update.message.reply_text("🛠 **Support Center**\nSelect Issue:", reply_markup=InlineKeyboardMarkup(kb))

async def support_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['sup_type'] = query.data.split("_")[1]
    await query.edit_message_text(f"✅ Selected: {context.user_data['sup_type']}\n\nSend Order IDs (e.g. `123, 456`):", parse_mode='Markdown')
    return WAITING_SUPPORT_ID

async def process_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    ids = update.message.text
    supabase.table('SupportBox').insert({
        "email": user['email'], "subject": context.user_data['sup_type'],
        "order_id": ids, "message": "User Request via Bot", "status": "Pending", "UserStatus": "unread"
    }).execute()
    await update.message.reply_text("✅ Ticket Created! Admin will check shortly.")
    return ConversationHandler.END
    # --- ADMIN COMMANDS ---

async def admin_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Admin Group ဟုတ်မဟုတ် စစ်ဆေးခြင်း
    if update.effective_chat.id != ADMIN_GROUP_ID: return

    # ID ငယ်ရာမှ ကြီးရာသို့ Service အားလုံးကို ယူမည်
    services = supabase.table('services').select("*").order('id', desc=False).execute().data
    
    if not services:
        await update.message.reply_text("❌ No services found in Database.")
        return

    bot_username = (await context.bot.get_me()).username
    total = len(services)
    await update.message.reply_text(f"🔄 Posting {total} services to channel... (3s delay each)")

    for index, s in enumerate(services, 1):
        try:
            local_id = s['id']
            # Channel အတွက် သီးသန့် Format (အတို) ကို သုံးမည်
            text = format_for_channel(s)
            
            deep_link = f"https://t.me/{bot_username}?start=order_{local_id}"
            keyboard = [[InlineKeyboardButton("🚀 Order Now", url=deep_link)]]
            
            # Channel သို့ ပို့ခြင်း
            sent = await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=text,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            # Message ID ကို Database တွင် ပြန်သိမ်းခြင်း (Sync လုပ်ရန်အတွက်)
            supabase.table('services').update({'channel_msg_id': sent.message_id}).eq('id', local_id).execute()
            
            # Flood Limit မထိအောင် ၃ စက္ကန့် နားမည်
            await asyncio.sleep(3)

        except Exception as e:
            logger.error(f"Post Error ID {local_id}: {e}")

    await update.message.reply_text("✅ All posts completed.")

async def admin_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_GROUP_ID: return
    if not context.args: return await update.message.reply_text("Usage: `/sync <Local_ID>`")

    local_id = context.args[0]
    res = supabase.table('services').select("*").eq('id', local_id).execute()
    
    if res.data and res.data[0].get('channel_msg_id'):
        s = res.data[0]
        # Channel Format အတိုင်း ပြန်ပြင်မည်
        text = format_for_channel(s)
        
        bot_username = (await context.bot.get_me()).username
        deep_link = f"https://t.me/{bot_username}?start=order_{local_id}"
        keyboard = [[InlineKeyboardButton("🚀 Order Now", url=deep_link)]]
        
        try:
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=s['channel_msg_id'],
                text=text,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            await update.message.reply_text(f"✅ Service {local_id} Updated in Channel!")
        except Exception as e:
            await update.message.reply_text(f"❌ Update Failed: {e}")
    else:
        await update.message.reply_text("❌ Service or Message ID not found.")

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_GROUP_ID: return
    if not context.args: return await update.message.reply_text("Usage: `/ban user@email.com`")
    
    email = context.args[0]
    # Supabase Users Table တွင် is_banned = True လုပ်မည်
    supabase.table('users').update({'is_banned': True}).eq('email', email).execute()
    await update.message.reply_text(f"🚫 User {email} has been BANNED.")

# --- MAIN EXECUTION ---

if __name__ == '__main__':
    # 1. Flask Server ကို Thread ခွဲပြီး Run မယ် (Render/UptimeRobot အတွက်)
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

    # 2. Bot Application တည်ဆောက်မယ်
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # --- HANDLERS SETUP ---
    
    # Login Conversation
    login_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(login_start, pattern='^login_flow$')],
        states={
            WAITING_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_email)],
            WAITING_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_password)],
        },
        fallbacks=[CommandHandler('cancel', cancel_login)]
    )

    # New Order Conversation
    new_order_handler = ConversationHandler(
        entry_points=[CommandHandler('neworder', new_order_start)],
        states={
            ORDER_WAITING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_order_link)],
            ORDER_WAITING_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_order_qty)],
            ORDER_CONFIRM: [CallbackQueryHandler(new_order_confirm)]
        },
        fallbacks=[CommandHandler('cancel', cancel_login)]
    )

    # Mass Order Conversation
    mass_order_handler = ConversationHandler(
        entry_points=[CommandHandler('massorder', mass_order_start)],
        states={
            WAITING_MASS_ORDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_mass_order)],
        },
        fallbacks=[CommandHandler('cancel', cancel_login)]
    )

    # Support Conversation
    support_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(support_btn, pattern='^sup_')],
        states={
            WAITING_SUPPORT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_support)]
        },
        fallbacks=[CommandHandler('cancel', cancel_login)]
    )

    # Adding All Handlers
    app.add_handler(login_handler)
    app.add_handler(new_order_handler)
    app.add_handler(mass_order_handler)
    app.add_handler(support_handler)
    
    # Basic Commands
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('services', services_command))
    app.add_handler(CommandHandler('history', history_command))
    app.add_handler(CommandHandler('check', check_command))
    app.add_handler(CommandHandler('support', support_start))

    # Admin Commands
    app.add_handler(CommandHandler('post', admin_post))
    app.add_handler(CommandHandler('sync', admin_sync))
    app.add_handler(CommandHandler('ban', admin_ban))

    print("🤖 K2 Boost Bot is Running...")
    app.run_polling()
