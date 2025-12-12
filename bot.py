import os
import logging
import threading
import asyncio
import requests
import time
from flask import Flask
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ConversationHandler
from supabase import create_client, Client
from zoneinfo import ZoneInfo
from datetime import datetime
import json
import traceback

# 1. Configuration Setup
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SMM_API_KEY = os.getenv("SMM_API_KEY")
SMM_API_URL = os.getenv("SMMGEN_URL", "https://smmgen.com/api/v2")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID", "0"))
CHANNEL_ID = int(os.getenv("NEWS_GROUP_ID", "0"))
SUPPLIER_GROUP_ID = int(os.getenv("SUPPLIER_GROUP_ID", "0"))
MMK_RATE = 5000 
TZ = ZoneInfo("Asia/Yangon")

# Conversation States
WAITING_EMAIL, WAITING_PASSWORD, LOGIN_LANG, LOGIN_CURR = range(4)
ORDER_WAITING_LINK, ORDER_WAITING_QTY, ORDER_CONFIRM = range(4, 7)
WAITING_MASS_INPUT, WAITING_MASS_CONFIRM = range(7, 9)
WAITING_SUPPORT_ID = 9
CMD_LANG_SELECT, CMD_CURR_SELECT = range(10, 12)

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
app = Flask(__name__)

@app.route('/')
def home(): return "Bot is running!", 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# --- LOCALIZATION (Updated Domain: k2boost.org) ---
TEXTS = {
    'en': {
        'welcome_login': "✅ **Login Successful!**\nAccount: {email}",
        'select_lang': "Please select your **Language**:",
        'select_curr': "Please select your **Currency**:",
        'setup_done': "🎉 **Setup Complete!**\n\nType /help to start.",
        'balance_low': "⚠️ **Insufficient Balance**\n\nPlease top up on website: k2boost.org",
        'confirm_order': "❓ **Confirm Order?**\n\n💵 Cost: {cost}\n✅ Yes to proceed.",
        'order_success': "✅ **Order Queued!**\nID: {id}\nBalance: {bal}\n\n⚙️ Processing in background...",
        'cancel': "🚫 Action Canceled.",
        'help_title': "👤 **Account Info**",
        'mass_confirm': "📊 **Mass Order Summary**\n\n✅ Valid: {valid}\n❌ Invalid: {invalid}\n💵 Total Cost: {cost}\n\nProceed?",
        'help_msg': "📋 **Available Commands:**\n1️⃣ /services - View Prices\n2️⃣ /neworder - Place Order\n3️⃣ /massorder - Bulk Order\n4️⃣ /history - View History\n5️⃣ /check <ID> - Check Status\n6️⃣ /support - Ticket/Refill\n7️⃣ /settings - Language/Currency\n\n🌐 Website - k2boost.org"
    },
    'mm': {
        'welcome_login': "✅ **Login ဝင်ခြင်း အောင်မြင်ပါသည်**\nအကောင့်: {email}",
        'select_lang': "**ဘာသာစကား** ရွေးချယ်ပါ:",
        'select_curr': "**ငွေကြေး** အမျိုးအစား ရွေးချယ်ပါ:",
        'setup_done': "🎉 **ပြင်ဆင်မှု ပြီးစီးပါပြီ!**",
        'balance_low': "⚠️ **လက်ကျန်ငွေ မလုံလောက်ပါ**\n\nWebsite တွင် ငွေဖြည့်ပါ: k2boost.org",
        'confirm_order': "❓ **အော်ဒါတင်ရန် သေချာပါသလား?**\n\n💵 ကျသင့်ငွေ: {cost}\n✅ Yes ကိုနှိပ်၍ ဆက်သွားပါ။",
        'order_success': "✅ **အော်ဒါ လက်ခံရရှိပါသည်!**\nID: {id}\nလက်ကျန်: {bal}\n\n⚙️ နောက်ကွယ်တွင် ဆက်လက်ဆောင်ရွက်နေပါပြီ...",
        'cancel': "🚫 မလုပ်တော့ပါ။",
        'help_title': "👤 **အကောင့် အချက်အလက်**",
        'mass_confirm': "📊 **Mass Order အကျဉ်းချုပ်**\n\n✅ အောင်မြင်: {valid}\n❌ မှားယွင်း: {invalid}\n💵 စုစုပေါင်း: {cost}\n\nအော်ဒါတင်မှာ သေချာပါသလား?",
        'help_msg': "📋 **အသုံးပြုနိုင်သော Commands:**\n1️⃣ /services - ဈေးနှုန်းကြည့်ရန်\n2️⃣ /neworder - မှာယူရန်\n3️⃣ /massorder - အများကြီးမှာရန်\n4️⃣ /history - မှတ်တမ်းကြည့်ရန်\n5️⃣ /check <ID> - Status စစ်ရန်\n6️⃣ /support - အကူအညီတောင်းရန်\n7️⃣ /settings - ပြင်ဆင်ရန် (Lang/Curr)\n\n🌐 Website - k2boost.org"
    }
}

# --- HELPER FUNCTIONS ---
def get_user(tg_id):
    res = supabase.table('users').select("*").eq('telegram_id', tg_id).execute()
    return res.data[0] if res.data else None

def get_text(lang, key, **kwargs):
    lang_code = lang if lang in ['en', 'mm'] else 'en'
    return TEXTS[lang_code].get(key, key).format(**kwargs)

def format_currency(amount, currency):
    if currency == 'MMK': return f"{amount * MMK_RATE:,.0f} Ks"
    return f"${amount:.4f}"

def calculate_cost(quantity, service_data):
    per_qty = int(service_data.get('per_quantity', 1000))
    if per_qty == 0: per_qty = 1000
    sell_price = float(service_data.get('sell_price', 0))
    return (quantity / per_qty) * sell_price

def format_for_user(service, lang='en', curr='USD'):
    name = service.get('service_name', 'Unknown')
    price_usd = float(service.get('sell_price', 0))
    min_q = service.get('min', 0)
    max_q = service.get('max', 0)
    per_qty = service.get('per_quantity', 1000)
    raw_note = service.get('note_mm') if lang == 'mm' else service.get('note_eng')
    desc = (raw_note or "").replace("\\n", "\n").strip()
    price_display = format_currency(price_usd, curr)
    return (f"✅ **Selected Service**\n🔥 *{name}*\n🆔 *ID:* `{service.get('id')}`\n"
            f"💵 *Price:* {price_display} (per {per_qty})\n📉 *Limit:* {min_q} - {max_q}\n\n📝 *Description:*\n{desc}")

def parse_smm_support_response(api_response, req_type, local_id):
    text = str(api_response).lower()
    if req_type == 'Refill':
        if 'refill request has been received' in text or 'queued' in text: return "✅ Refill Queued."
        elif 'canceled' in text: return "❌ Order Canceled."
        return f"⚠️ {api_response}"
    elif req_type == 'Cancel':
        if 'cancellation queue' in text: return "✅ Cancellation Queued."
        elif 'cannot be canceled' in text: return "❌ Cannot Cancel."
        return f"⚠️ {api_response}"
    return "✅ Sent."

# --- AUTH & DASHBOARD ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = get_user(user.id)
    chat_type = update.effective_chat.type
    args = context.args

    if chat_type != 'private':
        if not db_user:
            bot_username = (await context.bot.get_me()).username
            deep_link = f"https://t.me/{bot_username}?start=login"
            kb = [[InlineKeyboardButton("🔐 Login in Private", url=deep_link)]]
            await update.message.reply_text("⚠️ Login first in Private Chat.", reply_markup=InlineKeyboardMarkup(kb))
            return
        if not args:
            await update.message.reply_text(f"👋 {user.first_name}! Ready to serve.")
            return
    
    if args and args[0].startswith("order_"):
        local_id = args[0].split("_")[1]
        if not db_user:
            context.user_data['pending_order_id'] = local_id
            kb = [[InlineKeyboardButton("🔐 Login", callback_data="login_flow")]]
            await update.message.reply_text(f"⚠️ Login required for ID: {local_id}", reply_markup=InlineKeyboardMarkup(kb))
            return
        context.user_data['deep_link_id'] = local_id
        await new_order_start(update, context)
        return

    if not db_user:
        kb = [[InlineKeyboardButton("🔐 Login", callback_data="login_flow")], [InlineKeyboardButton("📝 Register", url="https://k2boost.org/createaccount")]]
        await update.message.reply_text(f"Welcome {user.first_name}!\nPlease Login.", reply_markup=InlineKeyboardMarkup(kb))
        return

    await help_command(update, context)

# --- LOGIN ---
async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("📧 Enter Email:")
    return WAITING_EMAIL

async def receive_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['login_email'] = update.message.text.strip().lower()
    await update.message.reply_text("🔑 Enter Password:")
    return WAITING_PASSWORD

async def receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = context.user_data.get('login_email')
    password = update.message.text.strip()
    try: await update.message.delete()
    except: pass
    msg = await update.message.reply_text("🔄 Verifying...")
    try:
        session = supabase.auth.sign_in_with_password({"email": email, "password": password})
        if session.user:
            supabase.table('users').update({'telegram_id': update.effective_user.id}).eq('id', session.user.id).execute()
            pending_id = context.user_data.get('pending_order_id')
            if pending_id:
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="✅ Login Success! Resuming...")
                context.user_data['deep_link_id'] = pending_id
                await new_order_start(update, context)
                return ConversationHandler.END
            kb = [[InlineKeyboardButton("English", callback_data="lang_en"), InlineKeyboardButton("Myanmar", callback_data="lang_mm")]]
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="✅ Login Success! Select Language:", reply_markup=InlineKeyboardMarkup(kb))
            return LOGIN_LANG
        else:
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="❌ Failed.")
            await start(update, context)
            return ConversationHandler.END
    except:
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="❌ Error.")
        await start(update, context)
        return ConversationHandler.END

async def login_set_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['temp_lang'] = query.data.split("_")[1]
    kb = [[InlineKeyboardButton("USD", callback_data="curr_USD"), InlineKeyboardButton("MMK", callback_data="curr_MMK")]]
    await query.edit_message_text("Select Currency:", reply_markup=InlineKeyboardMarkup(kb))
    return LOGIN_CURR

async def login_set_curr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    supabase.table('users').update({'language': context.user_data.get('temp_lang'), 'currency': query.data.split("_")[1]}).eq('telegram_id', update.effective_user.id).execute()
    await query.edit_message_text("✅ Setup Done!")
    await help_command(update, context)
    return ConversationHandler.END

# --- HELPERS ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db_user = get_user(user_id)
    if not db_user: return await start(update, context)
    lang = db_user.get('language', 'en')
    curr = db_user.get('currency', 'USD')
    bal = format_currency(float(db_user.get('balance', 0)), curr)
    msg = f"{get_text(lang, 'help_title')}\n📧 {db_user.get('email')}\n💰 {bal}\n\n{get_text(lang, 'help_msg')}"
    if update.callback_query: await update.callback_query.message.reply_text(msg, parse_mode='Markdown')
    else: await update.message.reply_text(msg, parse_mode='Markdown')

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Usage: `/check 1234`", parse_mode='Markdown')
    ids = context.args[0].split(',')
    msg = ""
    user = get_user(update.effective_user.id)
    for oid in ids:
        if not oid.strip().isdigit(): continue
        try:
            o_res = supabase.table('WebsiteOrders').select("*").eq('id', oid.strip()).eq('email', user['email']).execute()
            if o_res.data:
                o = o_res.data[0]
                s_name = "Unknown"
                try:
                    s_res = supabase.table('services').select('service_name').eq('service_id', o['service']).execute()
                    if not s_res.data: s_res = supabase.table('services').select('service_name').eq('id', o['service']).execute()
                    if s_res.data: s_name = s_res.data[0]['service_name']
                except: pass
                msg += f"🆔 `{o['id']}` | 📦 {s_name} | 🔢 {o['quantity']} | ✅ {o['status']}\n\n"
            else: msg += f"❌ Order {oid}: Not found.\n"
        except: pass
    await update.message.reply_text(msg)

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db_user = get_user(user_id)
    try:
        orders = supabase.table('WebsiteOrders').select("*").eq('email', db_user['email']).order('id', desc=True).limit(5).execute().data
        if not orders: return await update.message.reply_text("No history.")
        msg = "📜 **History**\n\n"
        for o in orders:
            msg += f"🆔 `{o['id']}` | 🔢 {o['quantity']} | ✅ {o['status']}\n🔗 {o['link']}\n----------------\n"
        await update.message.reply_text(msg, parse_mode='Markdown', disable_web_page_preview=True)
    except: await update.message.reply_text("Error fetching history.")

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("Language", callback_data="set_lang_start"), InlineKeyboardButton("Currency", callback_data="set_curr_start")]]
    await update.message.reply_text("⚙️ Settings:", reply_markup=InlineKeyboardMarkup(kb))

async def change_lang_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("English", callback_data="set_en"), InlineKeyboardButton("Myanmar", callback_data="set_mm")]]
    await update.callback_query.message.edit_text("Select Language:", reply_markup=InlineKeyboardMarkup(kb))
    return CMD_LANG_SELECT

async def change_curr_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("USD", callback_data="set_USD"), InlineKeyboardButton("MMK", callback_data="set_MMK")]]
    await update.callback_query.message.edit_text("Select Currency:", reply_markup=InlineKeyboardMarkup(kb))
    return CMD_CURR_SELECT

async def setting_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    if "set_en" in data or "set_mm" in data:
        lang = "en" if "en" in data else "mm"
        supabase.table('users').update({'language': lang}).eq('telegram_id', user_id).execute()
        await query.message.edit_text("✅ Language Updated!")
    elif "set_USD" in data or "set_MMK" in data:
        curr = "USD" if "USD" in data else "MMK"
        supabase.table('users').update({'currency': curr}).eq('telegram_id', user_id).execute()
        await query.message.edit_text("✅ Currency Updated!")
    await help_command(update, context)
    return ConversationHandler.END

async def cancel_op(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 Canceled.")
    await help_command(update, context)
    return ConversationHandler.END

# --- ORDER ---
async def new_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = get_user(user.id)
    if not db_user: return await start(update, context)
    target_id = None
    if context.args: target_id = context.args[0]
    elif context.user_data.get('deep_link_id'): target_id = context.user_data.pop('deep_link_id')
    if not target_id:
        await update.message.reply_text("Usage: `/neworder <ID>`", parse_mode='Markdown')
        return ConversationHandler.END
    if "order_" in target_id: target_id = target_id.split("_")[1]
    res = supabase.table('services').select("*").eq('id', target_id).execute()
    if not res.data: return await update.message.reply_text("❌ ID Not Found.")
    svc = res.data[0]
    context.user_data['order_svc'] = svc
    lang = db_user.get('language', 'en')
    curr = db_user.get('currency', 'USD')
    prompt = "🔗 **Link:**"
    if svc.get('use_type') == 'Telegram username': prompt = "🔗 **Username (@...):**"
    await update.message.reply_text(f"{format_for_user(svc, lang, curr)}\n\n{prompt}", parse_mode='Markdown')
    return ORDER_WAITING_LINK

async def new_order_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['order_link'] = update.message.text.strip()
    svc = context.user_data['order_svc']
    await update.message.reply_text(f"📊 **Quantity**\nMin: {svc['min']} - Max: {svc['max']}")
    return ORDER_WAITING_QTY

async def new_order_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: qty = int(update.message.text.strip())
    except: return await update.message.reply_text("❌ Numbers only.")
    svc = context.user_data['order_svc']
    if qty < svc['min'] or qty > svc['max']: return await update.message.reply_text(f"❌ Invalid Qty.")
    context.user_data['order_qty'] = qty
    cost_usd = calculate_cost(qty, svc)
    context.user_data['cost_usd'] = cost_usd
    user = get_user(update.effective_user.id)
    lang = user.get('language', 'en')
    curr = user.get('currency', 'USD')
    cost_display = format_currency(cost_usd, curr)
    text = get_text(lang, 'confirm_order', cost=cost_display)
    kb = [[InlineKeyboardButton("✅ Yes", callback_data="yes"), InlineKeyboardButton("❌ No", callback_data="no")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return ORDER_CONFIRM

async def new_order_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'no':
        await query.edit_message_text("🚫 Canceled.")
        return ConversationHandler.END
    user = get_user(update.effective_user.id)
    lang = user.get('language', 'en')
    cost_usd = context.user_data['cost_usd']
    if float(user['balance']) < cost_usd:
        await query.edit_message_text(get_text(lang, 'balance_low'))
        return ConversationHandler.END
    try:
        new_bal = float(user['balance']) - cost_usd
        supabase.table('users').update({'balance': new_bal}).eq('telegram_id', user.id).execute()
        o_data = {
            "email": user['email'], "service": context.user_data['order_svc']['service_id'],
            "link": context.user_data['order_link'], "quantity": context.user_data['order_qty'],
            "buy_charge": cost_usd, "status": "Pending", 
            "UsedType": "NewOrder", "supplier_service_id": context.user_data['order_svc']['service_id'], "supplier_name": "smmgen"
        }
        inserted = supabase.table('WebsiteOrders').insert(o_data).execute()
        local_id = inserted.data[0]['id'] if inserted.data else "N/A"
        curr = user.get('currency', 'USD')
        bal_display = format_currency(new_bal, curr)
        await query.edit_message_text(get_text(lang, 'order_success', id=local_id, bal=bal_display), parse_mode='Markdown')
    except Exception as e:
        await query.edit_message_text("❌ System Error.")
    await help_command(update, context)
    return ConversationHandler.END

async def mass_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 **Mass Order**\n`ID | Link | Qty`\n\nSend list:", parse_mode='Markdown')
    return WAITING_MASS_INPUT

async def mass_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = update.message.text.strip().split('\n')
    valid_orders = []
    total_cost = 0.0
    for line in lines:
        try:
            parts = [p.strip() for p in line.split('|')]
            if len(parts) != 3: continue
            sid, link, qty = parts[0], parts[1], int(parts[2])
            res = supabase.table('services').select("*").eq('id', sid).execute()
            if not res.data: continue
            svc = res.data[0]
            cost = calculate_cost(qty, svc)
            total_cost += cost
            valid_orders.append({'svc': svc, 'link': link, 'qty': qty, 'cost': cost})
        except: continue
    context.user_data['mass_queue'] = valid_orders
    context.user_data['mass_total'] = total_cost
    user = get_user(update.effective_user.id)
    lang = user.get('language', 'en')
    curr = user.get('currency', 'USD')
    cost_display = format_currency(total_cost, curr)
    summary = get_text(lang, 'mass_confirm', valid=len(valid_orders), invalid=len(lines)-len(valid_orders), cost=cost_display)
    kb = [[InlineKeyboardButton("✅ Yes", callback_data="mass_yes"), InlineKeyboardButton("❌ No", callback_data="mass_no")]]
    await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return WAITING_MASS_CONFIRM

async def mass_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'mass_no':
        await query.edit_message_text("🚫 Canceled.")
        return ConversationHandler.END
    user = get_user(update.effective_user.id)
    total = context.user_data['mass_total']
    if float(user['balance']) < total:
        await query.edit_message_text("⚠️ Insufficient Balance.")
        return ConversationHandler.END
    try:
        new_bal = float(user['balance']) - total
        supabase.table('users').update({'balance': new_bal}).eq('telegram_id', user.id).execute()
        for o in context.user_data['mass_queue']:
            supabase.table('WebsiteOrders').insert({
                "email": user['email'], "service": o['svc']['service_id'], "link": o['link'], 
                "quantity": o['qty'], "buy_charge": o['cost'], "status": "Pending", 
                "UsedType": "MassOrder", "supplier_service_id": o['svc']['service_id'], "supplier_name": "smmgen"
            }).execute()
        await query.edit_message_text("✅ Mass Order Placed! Processing in background.")
    except Exception as e:
        await query.edit_message_text(f"❌ Error: {e}")
    await help_command(update, context)
    return ConversationHandler.END

# --- SUPPORT BOT HANDLERS ---
async def sup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("Refill", callback_data="s_Refill"), InlineKeyboardButton("Cancel", callback_data="s_Cancel")]]
    await update.message.reply_text("Select Issue:", reply_markup=InlineKeyboardMarkup(kb))

async def sup_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['stype'] = query.data.split("_")[1]
    await query.edit_message_text("Send Order IDs (e.g. 1234):")
    return WAITING_SUPPORT_ID

async def sup_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = get_user(update.effective_user.id)
        ids = update.message.text.split(',')
        stype = context.user_data.get('stype', 'Other')
        for lid in ids:
            lid = lid.strip()
            if not lid.isdigit(): continue
            supabase.table('SupportBox').insert({
                "email": user['email'], "subject": stype, "order_id": lid, 
                "status": "Pending", "UserStatus": "unread"
            }).execute()
        await update.message.reply_text("✅ Ticket Created.")
        await help_command(update, context)
        return ConversationHandler.END
    except: return ConversationHandler.END

# =========================================
# 🔥 BACKEND POLLING WORKERS
# =========================================

def poll_transactions():
    """Checks for new transactions and auto-verifies them."""
    processed_tx = set()
    while True:
        try:
            txs = supabase.table("transactions").select("*").eq("status", "Pending").execute().data or []
            for tx in txs:
                tx_id = tx['id']
                if tx_id in processed_tx: continue
                
                verify = supabase.table("VerifyPayment").select("*").eq("transaction_id", tx['transaction_id']).eq("status", "unused").execute().data
                match = None
                if verify:
                    for v in verify:
                        if abs(float(v["amount_usd"]) - float(tx["amount"])) < 0.01:
                            match = v
                            break
                
                if match:
                    supabase.table("VerifyPayment").update({"status": "used"}).eq("transaction_id", tx['transaction_id']).execute()
                    user = supabase.table("users").select("balance").eq("email", tx['email']).execute().data
                    if user:
                        new_bal = float(user[0]['balance']) + float(tx["amount"])
                        supabase.table("users").update({"balance": new_bal}).eq("email", tx['email']).execute()
                        supabase.table("transactions").update({"status": "Accepted"}).eq("id", tx_id).execute()
                        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": ADMIN_GROUP_ID, "text": f"✅ Auto Top-up: {tx['email']} (${tx['amount']})"})
                else:
                    supabase.table("transactions").update({"status": "Processing"}).eq("id", tx_id).execute()
                    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": ADMIN_GROUP_ID, "text": f"⚠️ Manual Check: {tx_id} ({tx['amount']})"})
                
                processed_tx.add(tx_id)
        except: pass
        time.sleep(10)

def poll_affiliate():
    processed_aff = set()
    while True:
        try:
            reqs = supabase.table("affiliate").select("*").eq("status", "Pending").execute().data or []
            for req in reqs:
                rid = req['id']
                if rid in processed_aff: continue
                supabase.table("affiliate").update({"status": "Processing"}).eq("id", rid).execute()
                requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": ADMIN_GROUP_ID, "text": f"💸 Affiliate Request: {rid} (${req['amount']})"})
                processed_aff.add(rid)
        except: pass
        time.sleep(10)

def check_smmgen_rates_loop():
    while True:
        try:
            payload = {'key': SMM_API_KEY, 'action': 'services'}
            res = requests.post(SMM_API_URL, data=payload, timeout=30).json()
            local = supabase.table("services").select("id, service_id, buy_price").execute().data or []
            for ls in local:
                api_svc = next((s for s in res if str(s['service']) == str(ls['service_id'])), None)
                if api_svc:
                    api_rate = float(api_svc['rate'])
                    if abs(float(ls['buy_price']) - api_rate) > 0.0001:
                        supabase.table("services").update({"buy_price": api_rate}).eq("id", ls['id']).execute()
        except: pass
        time.sleep(3600)

def process_pending_orders_loop():
    while True:
        try:
            orders = supabase.table("WebsiteOrders").select("*").eq("status", "Pending").eq("supplier_name", "smmgen").execute().data or []
            for o in orders:
                if o.get("supplier_order_id"): continue
                payload = {'key': SMM_API_KEY, 'action': 'add', 'service': o['supplier_service_id'], 'link': o['link'], 'quantity': o['quantity']}
                try:
                    res = requests.post(SMM_API_URL, data=payload, timeout=20).json()
                    if 'order' in res:
                        supabase.table("WebsiteOrders").update({"status": "Processing", "supplier_order_id": str(res['order'])}).eq("id", o["id"]).execute()
                    elif 'error' in res:
                        user = supabase.table('users').select("balance").eq("email", o['email']).execute().data[0]
                        new_bal = float(user['balance']) + float(o['buy_charge'])
                        supabase.table('users').update({'balance': new_bal}).eq("email", o['email']).execute()
                        supabase.table("WebsiteOrders").update({"status": "Canceled"}).eq("id", o["id"]).execute()
                except: pass
        except: pass
        time.sleep(5)

def smmgen_status_batch_loop():
    while True:
        try:
            all_smm = supabase.table("WebsiteOrders").select("supplier_order_id").eq("supplier_name","smmgen").not_.in_("status", ["Completed", "Canceled", "Refunded"]).not_.is_("supplier_order_id", None).execute().data or []
            s_ids = [str(o['supplier_order_id']) for o in all_smm if str(o['supplier_order_id']).isdigit()]
            if not s_ids: 
                time.sleep(60)
                continue
            for i in range(0, len(s_ids), 100):
                batch = ",".join(s_ids[i:i + 100])
                try:
                    res = requests.post(SMM_API_URL, data={"key": SMM_API_KEY, "action": "status", "orders": batch}, timeout=30).json()
                    for sup_id, info in res.items():
                        if isinstance(info, dict) and "status" in info:
                            upd = {"status": info["status"]}
                            if "remains" in info: upd["remain"] = int(float(info["remains"]))
                            if "start_count" in info: upd["start_count"] = int(float(info["start_count"]))
                            supabase.table("WebsiteOrders").update(upd).eq("supplier_order_id", sup_id).execute()
                    time.sleep(2)
                except: pass
        except: pass
        time.sleep(60)

def poll_supportbox_worker():
    while True:
        try:
            tickets = supabase.table("SupportBox").select("*").eq("status", "Pending").execute().data or []
            for t in tickets:
                lid = t.get("order_id")
                subject = t.get("subject")
                order = supabase.table("WebsiteOrders").select("supplier_order_id").eq("id", lid).execute().data
                sup_id = order[0].get("supplier_order_id") if order else None
                reply_text = ""
                if subject in ["Refill", "Cancel"] and sup_id:
                    action = 'refill' if subject == 'Refill' else 'cancel'
                    try:
                        res = requests.post(SMM_API_URL, data={'key': SMM_API_KEY, 'action': action, 'order': sup_id}, timeout=10).json()
                        reply_text = parse_smm_support_response(res, subject, lid)
                    except: reply_text = "❌ Error."
                else: reply_text = "⚠️ Manual Check."
                supabase.table("SupportBox").update({"reply_text": reply_text, "status": "Replied"}).eq("id", t["id"]).execute()
        except: pass
        time.sleep(10)

# --- ADMIN COMMANDS ---
async def admin_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_GROUP_ID: return
    services = supabase.table('services').select("*").order('id', desc=False).execute().data
    if not services: return await update.message.reply_text("No Services.")
    grouped = {}
    for s in services:
        cat = s.get('category', 'Uncategorized')
        if cat not in grouped: grouped[cat] = []
        grouped[cat].append(s)
    bot_username = (await context.bot.get_me()).username
    await update.message.reply_text(f"Posting {len(grouped)} Categories...")
    for cat, items in grouped.items():
        msg = f"📂 <b>{cat}</b>\n➖➖➖➖➖➖➖➖➖➖\n\n"
        for s in items:
            lid = s['id']
            link = f"https://t.me/{bot_username}?start=order_{lid}"
            msg += f"⚡ <a href='{link}'>ID:{lid} - {s['service_name']}</a>\n\n"
        await context.bot.send_message(CHANNEL_ID, text=msg, parse_mode='HTML', disable_web_page_preview=True)
        time.sleep(3)
    await update.message.reply_text("Done.")

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_GROUP_ID: return
    if context.args:
        supabase.table('users').update({'is_banned': True}).eq('email', context.args[0]).execute()
        await update.message.reply_text(f"Banned {context.args[0]}")

async def admin_tx_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_GROUP_ID: return
    try:
        tx_id = int(context.args[0])
        tx = supabase.table("transactions").select("*").eq("id", tx_id).execute().data
        if not tx: return await update.message.reply_text("Not Found.")
        if tx[0]['status'] == 'Accepted': return await update.message.reply_text("Already Accepted.")
        user = supabase.table("users").select("balance").eq("email", tx[0]['email']).execute().data
        if user:
            new_bal = float(user[0]['balance']) + float(tx[0]['amount'])
            supabase.table("users").update({"balance": new_bal}).eq("email", tx[0]['email']).execute()
            supabase.table("transactions").update({"status": "Accepted"}).eq("id", tx_id).execute()
            await update.message.reply_text(f"✅ Approved.")
    except: pass

async def admin_tx_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_GROUP_ID: return
    try:
        tx_id = int(context.args[0])
        supabase.table("transactions").update({"status": "Rejected"}).eq("id", tx_id).execute()
        await update.message.reply_text(f"❌ Rejected.")
    except: pass

async def admin_aff_accept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_GROUP_ID: return
    try:
        rid = int(context.args[0])
        supabase.table("affiliate").update({"status": "Accepted"}).eq("id", rid).execute()
        await update.message.reply_text(f"✅ Accepted.")
    except: pass

async def services_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛍 **Services:**\nCheck @k2boost for prices.", parse_mode='Markdown')

# --- MAIN ---
if __name__ == '__main__':
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    
    # 🔥 Start All Polling Workers
    threading.Thread(target=process_pending_orders_loop, daemon=True).start()
    threading.Thread(target=smmgen_status_batch_loop, daemon=True).start()
    threading.Thread(target=poll_supportbox_worker, daemon=True).start()
    threading.Thread(target=poll_transactions, daemon=True).start()
    threading.Thread(target=poll_affiliate, daemon=True).start()
    threading.Thread(target=check_smmgen_rates_loop, daemon=True).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    login_h = ConversationHandler(entry_points=[CallbackQueryHandler(login_start, pattern='^login_flow$')], states={WAITING_EMAIL: [MessageHandler(filters.TEXT, receive_email)], WAITING_PASSWORD: [MessageHandler(filters.TEXT, receive_password)], LOGIN_LANG: [CallbackQueryHandler(login_set_lang)], LOGIN_CURR: [CallbackQueryHandler(login_set_curr)]}, fallbacks=[CommandHandler('cancel', cancel_op)])
    new_h = ConversationHandler(entry_points=[CommandHandler('neworder', new_order_start), CommandHandler('start', new_order_start, filters.Regex('order_'))], states={ORDER_WAITING_LINK: [MessageHandler(filters.TEXT, new_order_link)], ORDER_WAITING_QTY: [MessageHandler(filters.TEXT, new_order_qty)], ORDER_CONFIRM: [CallbackQueryHandler(new_order_confirm)]}, fallbacks=[CommandHandler('cancel', cancel_op)])
    mass_h = ConversationHandler(entry_points=[CommandHandler('massorder', mass_start)], states={WAITING_MASS_INPUT: [MessageHandler(filters.TEXT, mass_process)], WAITING_MASS_CONFIRM: [CallbackQueryHandler(mass_confirm)]}, fallbacks=[CommandHandler('cancel', cancel_op)])
    sup_h = ConversationHandler(entry_points=[CommandHandler('support', sup_start), CallbackQueryHandler(sup_process, pattern='^s_')], states={WAITING_SUPPORT_ID: [MessageHandler(filters.TEXT, sup_save)]}, fallbacks=[CommandHandler('cancel', cancel_op)])
    sett_h = ConversationHandler(entry_points=[CommandHandler('settings', settings_command), CallbackQueryHandler(change_lang_start, pattern='^set_lang_start'), CallbackQueryHandler(change_curr_start, pattern='^set_curr_start')], states={CMD_LANG_SELECT: [CallbackQueryHandler(setting_process)], CMD_CURR_SELECT: [CallbackQueryHandler(setting_process)]}, fallbacks=[CommandHandler('cancel', cancel_op)])

    app.add_handler(login_h)
    app.add_handler(new_h)
    app.add_handler(mass_h)
    app.add_handler(sup_h)
    app.add_handler(sett_h)
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('check', check_command))
    app.add_handler(CommandHandler('services', services_command))
    app.add_handler(CommandHandler('history', history_command))
    app.add_handler(CommandHandler('post', admin_post))
    app.add_handler(CommandHandler('ban', admin_ban))
    app.add_handler(CommandHandler('Yes', admin_tx_approve))
    app.add_handler(CommandHandler('No', admin_tx_reject))
    app.add_handler(CommandHandler('Accept', admin_aff_accept))

    print("Bot Running...")
    app.run_polling()

