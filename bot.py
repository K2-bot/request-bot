import os
import logging
import threading
import asyncio
import requests
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
SMM_API_KEY = os.getenv("SMM_API_KEY")
SMM_API_URL = "https://smmgen.com/api/v2"
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID", 0))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))
MMK_RATE = 5000 

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

# --- LOCALIZATION (ဘာသာပြန် စာသားများ) ---
TEXTS = {
    'en': {
        'welcome_login': "✅ **Login Successful!**\nAccount: {email}",
        'select_lang': "Please select your **Language**:",
        'select_curr': "Please select your **Currency**:",
        'setup_done': "🎉 **Setup Complete!**\n\nType /help to start.",
        'balance_low': "⚠️ **Insufficient Balance**\n\nPlease top up your account on our website.\n👉 Link: k2boostweb.com",
        'confirm_order': "❓ **Confirm Order?**\n\n💵 Cost: {cost}\n✅ Yes to proceed.",
        'order_success': "✅ **Order Placed!**\nID: {id}\nBalance: {bal}",
        'cancel': "🚫 Action Canceled.",
        'help_title': "👤 **Account Info**",
        'mass_confirm': "📊 **Mass Order Summary**\n\n✅ Valid: {valid}\n❌ Invalid: {invalid}\n💵 Total Cost: {cost}\n\nProceed?",
        'help_msg': (
            "📋 **Available Commands:**\n"
            "1️⃣ /services - View Prices\n2️⃣ /neworder - Place Order\n"
            "3️⃣ /massorder - Bulk Order\n4️⃣ /history - View History\n"
            "5️⃣ /check <ID> - Check Status\n6️⃣ /support - Ticket/Refill\n"
            "7️⃣ /settings - Language/Currency\n\n"
            "🌐 Website - k2boostweb.com\n📢 Channel - @k2boost\n👮 Admin - @K2boostservice\n\n"
            "💡 *Please top up via Website if balance is low.*"
        )
    },
    'mm': {
        'welcome_login': "✅ **Login ဝင်ခြင်း အောင်မြင်ပါသည်**\nအကောင့်: {email}",
        'select_lang': "**ဘာသာစကား** ရွေးချယ်ပါ:",
        'select_curr': "**ငွေကြေး** အမျိုးအစား ရွေးချယ်ပါ:",
        'setup_done': "🎉 **ပြင်ဆင်မှု ပြီးစီးပါပြီ!**\n\nစတင်ရန် /help ကို နှိပ်ပါ။",
        'balance_low': "⚠️ **လက်ကျန်ငွေ မလုံလောက်ပါ**\n\nWebsite တွင် ငွေသွားရောက်ဖြည့်သွင်းပေးပါ။\n👉 Link: k2boostweb.com",
        'confirm_order': "❓ **အော်ဒါတင်ရန် သေချာပါသလား?**\n\n💵 ကျသင့်ငွေ: {cost}\n✅ Yes ကိုနှိပ်၍ ဆက်သွားပါ။",
        'order_success': "✅ **အော်ဒါတင်ပြီးပါပြီ!**\nID: {id}\nလက်ကျန်: {bal}",
        'cancel': "🚫 မလုပ်တော့ပါ။ (/help သို့ ပြန်သွားပါ)",
        'help_title': "👤 **အကောင့် အချက်အလက်**",
        'mass_confirm': "📊 **Mass Order အကျဉ်းချုပ်**\n\n✅ အောင်မြင်: {valid}\n❌ မှားယွင်း: {invalid}\n💵 စုစုပေါင်း: {cost}\n\nအော်ဒါတင်မှာ သေချာပါသလား?",
        'help_msg': (
            "📋 **အသုံးပြုနိုင်သော Commands:**\n"
            "1️⃣ /services - ဈေးနှုန်းကြည့်ရန်\n2️⃣ /neworder - မှာယူရန်\n"
            "3️⃣ /massorder - အများကြီးမှာရန်\n4️⃣ /history - မှတ်တမ်းကြည့်ရန်\n"
            "5️⃣ /check <ID> - Status စစ်ရန်\n6️⃣ /support - အကူအညီတောင်းရန်\n"
            "7️⃣ /settings - ပြင်ဆင်ရန် (Lang/Curr)\n\n"
            "🌐 Website - k2boostweb.com\n📢 Channel - @k2boost\n👮 Admin - @K2boostservice\n\n"
            "💡 *ငွေဖြည့်လိုပါက Website တွင် ဝင်ရောက်ဖြည့်သွင်းပါ။*"
        )
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
    if currency == 'MMK':
        return f"{amount * MMK_RATE:,.0f} Ks"
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
    # --- AUTH & GENERAL ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = get_user(user.id)
    args = context.args

    if not db_user:
        kb = [[InlineKeyboardButton("🔐 Login", callback_data="login_flow")],
              [InlineKeyboardButton("📝 Register", url="https://k2boostweb.com/createaccount")]]
        await update.message.reply_text(f"Welcome {user.first_name}!\nPlease Login or Register.", reply_markup=InlineKeyboardMarkup(kb))
        return

    # Deep Link Handler (Handled by regex in Main)
    pass 
    await help_command(update, context)

# --- LOGIN FLOW ---
async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("📧 Enter your Website Email:")
    return WAITING_EMAIL

async def receive_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['login_email'] = update.message.text.strip().lower()
    await update.message.reply_text("🔑 Enter Password (Auto-delete enabled):")
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
            kb = [[InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"), InlineKeyboardButton("🇲🇲 Myanmar", callback_data="lang_mm")]]
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id, message_id=msg.message_id,
                text=TEXTS['en']['welcome_login'].format(email=email) + "\n\n" + TEXTS['en']['select_lang'],
                reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown'
            )
            return LOGIN_LANG
        else:
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="❌ Login Failed.")
            return ConversationHandler.END
    except:
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="❌ Error.")
        return ConversationHandler.END

async def login_set_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = query.data.split("_")[1]
    context.user_data['temp_lang'] = lang
    text = get_text(lang, 'select_curr')
    kb = [[InlineKeyboardButton("💵 USD ($)", callback_data="curr_USD"), InlineKeyboardButton("💵 MMK (Ks)", callback_data="curr_MMK")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return LOGIN_CURR

async def login_set_curr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    curr = query.data.split("_")[1]
    lang = context.user_data.get('temp_lang', 'en')
    user_id = update.effective_user.id
    supabase.table('users').update({'language': lang, 'currency': curr}).eq('telegram_id', user_id).execute()
    await query.edit_message_text(get_text(lang, 'setup_done'), parse_mode='Markdown')
    await help_command(update, context) 
    return ConversationHandler.END

# --- DASHBOARD & UTILS ---

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db_user = get_user(user_id)
    if not db_user: return await start(update, context)

    lang = db_user.get('language', 'en')
    curr = db_user.get('currency', 'USD')
    bal_display = format_currency(float(db_user.get('balance', 0)), curr)
    
    title = get_text(lang, 'help_title')
    body = get_text(lang, 'help_msg')
    msg = f"{title}\n📧 Email: `{db_user.get('email')}`\n💰 Balance: **{bal_display}**\n\n{body}"
    
    if update.callback_query: await update.callback_query.message.reply_text(msg, parse_mode='Markdown')
    else: await update.message.reply_text(msg, parse_mode='Markdown')

async def services_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛍 **Services:**\nCheck @k2boost for prices.", parse_mode='Markdown')

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Usage: `/check 1234`", parse_mode='Markdown')
    ids = context.args[0].split(',')
    msg = ""
    user = get_user(update.effective_user.id)
    for oid in ids:
        oid = oid.strip()
        if not oid.isdigit(): continue
        o_res = supabase.table('WebsiteOrders').select("*").eq('id', oid).eq('email', user['email']).execute()
        if o_res.data:
            o = o_res.data[0]
            s_res = supabase.table('services').select('service_name').eq('service_id', o['service']).execute()
            if not s_res.data: s_res = supabase.table('services').select('service_name').eq('id', o['service']).execute()
            s_name = s_res.data[0]['service_name'] if s_res.data else "Unknown"
            msg += (f"🆔 `{oid}` ၊ 📦 Service: {s_name} ၊ 🔢 Quantity: {o['quantity']} ၊ 🔗 Link: {o['link']} ၊ ✅ Status: {o['status']}\n\n")
        else:
            msg += f"❌ Unable to Process:\nOrder {oid} - Not found or does not belong to your account\n\n"
    await update.message.reply_text(msg, disable_web_page_preview=True)

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db_user = get_user(user_id)
    orders = supabase.table('WebsiteOrders').select("*").eq('email', db_user['email']).order('id', desc=True).limit(5).execute().data
    if not orders: return await update.message.reply_text("No history.")
    msg = "📜 **Order History**\n\n"
    for o in orders:
        s_res = supabase.table('services').select('service_name').eq('service_id', o['service']).execute()
        if not s_res.data: s_res = supabase.table('services').select('service_name').eq('id', o['service']).execute()
        s_name = s_res.data[0]['service_name'] if s_res.data else "Service"
        msg += (f"🆔 `{o['id']}` ၊ 📦 {s_name}\n🔢 Qty: {o['quantity']} ၊ ✅ {o['status']}\n🔗 {o['link']}\n-------------------\n")
    await update.message.reply_text(msg, disable_web_page_preview=True)

async def cancel_op(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 Canceled.")
    await help_command(update, context)
    return ConversationHandler.END

# --- SETTINGS (/settings) ---
async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("🗣 Language", callback_data="set_lang_start"), 
           InlineKeyboardButton("💰 Currency", callback_data="set_curr_start")]]
    await update.message.reply_text("⚙️ **Settings**\nChoose option:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def change_lang_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("🇬🇧 English", callback_data="set_en"), InlineKeyboardButton("🇲🇲 Myanmar", callback_data="set_mm")]]
    if update.callback_query: await update.callback_query.message.edit_text("Select Language:", reply_markup=InlineKeyboardMarkup(kb))
    else: await update.message.reply_text("Select Language:", reply_markup=InlineKeyboardMarkup(kb))
    return CMD_LANG_SELECT

async def change_curr_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("USD ($)", callback_data="set_USD"), InlineKeyboardButton("MMK (Ks)", callback_data="set_MMK")]]
    if update.callback_query: await update.callback_query.message.edit_text("Select Currency:", reply_markup=InlineKeyboardMarkup(kb))
    else: await update.message.reply_text("Select Currency:", reply_markup=InlineKeyboardMarkup(kb))
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

# --- ORDER SYSTEMS ---

async def new_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.id
    db_user = get_user(user.id)
    if not db_user: return await start(update, context)

    # Resolve ID: 1. Deep Link Context, 2. Regex Args, 3. Command Args
    target_id = None
    if context.user_data.get('deep_link_id'):
        target_id = context.user_data.pop('deep_link_id')
    elif context.args:
        target_id = context.args[0]
    
    if not target_id:
        await update.message.reply_text("⚠️ Usage: `/neworder <ID>`", parse_mode='Markdown')
        return ConversationHandler.END
        
    if "order_" in target_id: target_id = target_id.split("_")[1]
    
    res = supabase.table('services').select("*").eq('id', target_id).execute()
    if not res.data: 
        await update.message.reply_text("❌ Service ID Not Found.")
        return ConversationHandler.END
    
    svc = res.data[0]
    context.user_data['order_svc'] = svc
    lang = db_user.get('language', 'en')
    curr = db_user.get('currency', 'USD')
    
    prompt = "🔗 **Enter Link (URL):**"
    if svc.get('use_type') == 'Telegram username' or 'Stars' in svc.get('service_name', ''):
        prompt = "🔗 **Enter Telegram Username (@...):**"
    
    await update.message.reply_text(f"{format_for_user(svc, lang, curr)}\n\n{prompt}", parse_mode='Markdown')
    return ORDER_WAITING_LINK

async def new_order_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['order_link'] = update.message.text.strip()
    svc = context.user_data['order_svc']
    await update.message.reply_text(f"📊 **Enter Quantity**\nMin: {svc['min']} - Max: {svc['max']}")
    return ORDER_WAITING_QTY

async def new_order_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: qty = int(update.message.text.strip())
    except: return await update.message.reply_text("❌ Numbers only.")
    
    svc = context.user_data['order_svc']
    if qty < svc['min'] or qty > svc['max']:
        return await update.message.reply_text(f"❌ Invalid Qty (Min: {svc['min']} - Max: {svc['max']})")

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
        await help_command(update, context)
        return ConversationHandler.END
        
    user = get_user(update.effective_user.id)
    lang = user.get('language', 'en')
    cost_usd = context.user_data['cost_usd']
    
    if float(user['balance']) < cost_usd:
        await query.edit_message_text(get_text(lang, 'balance_low'))
        return ConversationHandler.END
        
    new_bal = float(user['balance']) - cost_usd
    supabase.table('users').update({'balance': new_bal}).eq('telegram_id', user.id).execute()
    
    o_data = {
        "email": user['email'], "service": context.user_data['order_svc']['service_id'],
        "link": context.user_data['order_link'], "quantity": context.user_data['order_qty'],
        "buy_charge": cost_usd, "status": "Pending", "UsedType": "NewOrder", "supplier_service_id": context.user_data['order_svc']['service_id']
    }
    supabase.table('WebsiteOrders').insert(o_data).execute()
    
    curr = user.get('currency', 'USD')
    bal_display = format_currency(new_bal, curr)
    await query.edit_message_text(get_text(lang, 'order_success', id=context.user_data['order_svc']['id'], bal=bal_display), parse_mode='Markdown')
    await help_command(update, context)
    return ConversationHandler.END

async def mass_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 **Mass Order**\n`ID | Link | Qty`\n\nSend list:", parse_mode='Markdown')
    return WAITING_MASS_INPUT

async def mass_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = update.message.text.strip().split('\n')
    valid_orders = []
    error_log = ""
    total_cost_usd = 0.0
    
    for i, line in enumerate(lines, 1):
        try:
            parts = [p.strip() for p in line.split('|')]
            if len(parts) != 3: 
                error_log += f"❌ Line {i}: Invalid Format\n"
                continue
            sid, link, qty_str = parts
            if not qty_str.isdigit():
                error_log += f"❌ Line {i}: Qty must be number\n"
                continue
            qty = int(qty_str)

            res = supabase.table('services').select("*").eq('id', sid).execute()
            if not res.data:
                error_log += f"❌ Line {i}: ID {sid} Not Found\n"
                continue
            svc = res.data[0]
            if qty < svc['min'] or qty > svc['max']:
                error_log += f"❌ Line {i}: Qty Limit\n"
                continue
            cost = calculate_cost(qty, svc)
            total_cost_usd += cost
            valid_orders.append({'svc': svc, 'link': link, 'qty': qty, 'cost': cost})
        except: 
            error_log += f"❌ Line {i}: Syntax Error\n"
            continue
    
    context.user_data['mass_queue'] = valid_orders
    context.user_data['mass_total'] = total_cost_usd
    
    user = get_user(update.effective_user.id)
    lang = user.get('language', 'en')
    curr = user.get('currency', 'USD')
    cost_display = format_currency(total_cost_usd, curr)
    
    summary = get_text(lang, 'mass_confirm', valid=len(valid_orders), invalid=len(lines)-len(valid_orders), cost=cost_display)
    if error_log: summary += f"\n\n⚠️ **Errors:**\n{error_log}"
    
    if valid_orders:
        kb = [[InlineKeyboardButton("✅ Yes", callback_data="mass_yes"), InlineKeyboardButton("❌ No", callback_data="mass_no")]]
        await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        return WAITING_MASS_CONFIRM
    else:
        await update.message.reply_text(summary + "\n❌ No valid orders.", parse_mode='Markdown')
        await help_command(update, context)
        return ConversationHandler.END

async def mass_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'mass_no':
        await query.edit_message_text("🚫 Canceled.")
        await help_command(update, context)
        return ConversationHandler.END
        
    user = get_user(update.effective_user.id)
    total_usd = context.user_data['mass_total']
    if float(user['balance']) < total_usd:
        await query.edit_message_text("⚠️ Insufficient Balance.")
        return ConversationHandler.END
        
    new_bal = float(user['balance']) - total_usd
    supabase.table('users').update({'balance': new_bal}).eq('telegram_id', user.id).execute()
    
    for o in context.user_data['mass_queue']:
        supabase.table('WebsiteOrders').insert({
            "email": user['email'], "service": o['svc']['service_id'], "link": o['link'], 
            "quantity": o['qty'], "buy_charge": o['cost'], "status": "Pending", "UsedType": "MassOrder",
            "supplier_service_id": o['svc']['service_id']
        }).execute()
        
    await query.edit_message_text("✅ Mass Order Placed!")
    await help_command(update, context)
    return ConversationHandler.END

# --- SUPPORT ---

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
        msg_out = ""

        for lid in ids:
            lid = lid.strip()
            if not lid.isdigit(): continue
            order_res = supabase.table('WebsiteOrders').select("*").eq('id', lid).eq('email', user['email']).execute()
            if order_res.data:
                order = order_res.data[0]
                sup_id = order.get('supplier_order_id')
                if stype == 'Refill':
                    if not sup_id:
                        msg_out += f"❌ Order {lid}: No Supplier ID\n"
                        continue
                    try:
                        payload = {'key': SMM_API_KEY, 'action': 'refill', 'order': sup_id}
                        res = requests.post(SMM_API_URL, data=payload, timeout=10).json()
                        if 'refill' in res:
                            supabase.table('SupportBox').insert({"email": user['email'], "subject": "Refill", "order_id": lid, "supplier_order_id": sup_id, "supplier_refill_id": res['refill'], "refill_status": "In Progress", "status": "In Progress"}).execute()
                            msg_out += f"✅ Order {lid}: Refill processing.\n"
                        elif 'error' in res:
                            msg_out += f"❌ Order {lid}: {res['error']}\n"
                    except Exception as e: msg_out += f"❌ Error: {e}\n"
                else:
                    supabase.table('SupportBox').insert({"email": user['email'], "subject": stype, "order_id": lid, "status": "Pending"}).execute()
                    msg_out += f"✅ Ticket {lid}: Created\n"
            else:
                msg_out += f"❌ Unable to Process:\nOrder {lid} - Not found or does not belong to your account\n\n"
        
        await update.message.reply_text(f"{msg_out}Thank you!")
        await help_command(update, context)
        return ConversationHandler.END
    except Exception as e:
        logger.error(e)
        await update.message.reply_text("❌ System Error.")
        await help_command(update, context)
        return ConversationHandler.END

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
    await update.message.reply_text(f"Posting {len(grouped)} Categories (HTML)...")
    for cat, items in grouped.items():
        try:
            safe_cat = cat.replace("<", "&lt;").replace(">", "&gt;")
            msg = f"📂 <b>{safe_cat}</b>\n➖➖➖➖➖➖➖➖➖➖\n\n"
            for s in items:
                lid = s['id']
                safe_name = s.get('service_name', 'Unknown').replace("<", "&lt;").replace(">", "&gt;")
                ft = (s.get('service_name') + (s.get('note_eng') or "")).lower()
                icon = "🚫" if 'no refill' in ft else ("♻️" if 'refill' in ft else "⚡")
                link = f"https://t.me/{bot_username}?start=order_{lid}"
                msg += f"{icon} <a href='{link}'>ID:{lid} - {safe_name}</a>\n\n"
            msg += "➖➖➖➖➖➖➖➖➖➖\n👇 <b>Click blue text to Order</b>"
            sent = await context.bot.send_message(CHANNEL_ID, text=msg, parse_mode='HTML', disable_web_page_preview=True)
            for s in items: supabase.table('services').update({'channel_msg_id': sent.message_id}).eq('id', s['id']).execute()
            await asyncio.sleep(3)
        except Exception as e: logger.error(e)
    await update.message.reply_text("Done.")

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_GROUP_ID: return
    if context.args:
        supabase.table('users').update({'is_banned': True}).eq('email', context.args[0]).execute()
        await update.message.reply_text(f"Banned {context.args[0]}")

# --- MAIN ---
if __name__ == '__main__':
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    login_h = ConversationHandler(
        entry_points=[CallbackQueryHandler(login_start, pattern='^login_flow$')],
        states={WAITING_EMAIL: [MessageHandler(filters.TEXT, receive_email)],
                WAITING_PASSWORD: [MessageHandler(filters.TEXT, receive_password)],
                LOGIN_LANG: [CallbackQueryHandler(login_set_lang)],
                LOGIN_CURR: [CallbackQueryHandler(login_set_curr)]},
        fallbacks=[CommandHandler('cancel', cancel_op)])

    new_h = ConversationHandler(
        entry_points=[
            CommandHandler('neworder', new_order_start),
            CommandHandler('start', new_order_start, filters.Regex('order_'))
        ],
        states={ORDER_WAITING_LINK: [MessageHandler(filters.TEXT, new_order_link)],
                ORDER_WAITING_QTY: [MessageHandler(filters.TEXT, new_order_qty)],
                ORDER_CONFIRM: [CallbackQueryHandler(new_order_confirm)]},
        fallbacks=[CommandHandler('cancel', cancel_op)])
    
    mass_h = ConversationHandler(
        entry_points=[CommandHandler('massorder', mass_start)],
        states={WAITING_MASS_INPUT: [MessageHandler(filters.TEXT, mass_process)],
                WAITING_MASS_CONFIRM: [CallbackQueryHandler(mass_confirm)]},
        fallbacks=[CommandHandler('cancel', cancel_op)])

    sup_h = ConversationHandler(
        entry_points=[CommandHandler('support', sup_start), CallbackQueryHandler(sup_process, pattern='^s_')],
        states={WAITING_SUPPORT_ID: [MessageHandler(filters.TEXT, sup_save)]},
        fallbacks=[CommandHandler('cancel', cancel_op)])
    
    sett_h = ConversationHandler(
        entry_points=[CommandHandler('settings', settings_command), 
                      CallbackQueryHandler(change_lang_start, pattern='^set_lang_start'),
                      CallbackQueryHandler(change_curr_start, pattern='^set_curr_start')],
        states={CMD_LANG_SELECT: [CallbackQueryHandler(setting_process)],
                CMD_CURR_SELECT: [CallbackQueryHandler(setting_process)]},
        fallbacks=[CommandHandler('cancel', cancel_op)])

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

    print("Bot Running...")
    app.run_polling()

