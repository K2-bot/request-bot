import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
import config
from db import supabase, get_user
from utils import get_text, format_currency, calculate_cost, format_for_user

# Helper to send notifications to specific groups
def notify_group(chat_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage", 
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, 
            timeout=10
        )
    except: pass

# =========================================
# 🔐 AUTH & START HANDLERS
# =========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = get_user(user.id)
    args = context.args
    
    # Group Chat Logic
    if update.effective_chat.type != 'private':
        if not db_user:
            bot_username = (await context.bot.get_me()).username
            kb = [[InlineKeyboardButton("🔐 Login in Private", url=f"https://t.me/{bot_username}?start=login")]]
            return await update.message.reply_text("⚠️ Login first in Private Chat.", reply_markup=InlineKeyboardMarkup(kb))
        if not args: return await update.message.reply_text(f"👋 {user.first_name}! Ready.")
    
    # Deep Link Logic (e.g. /start order_123)
    if args and args[0].startswith("order_"):
        local_id = args[0].split("_")[1]
        if not db_user:
            context.user_data['pending_order_id'] = local_id
            kb = [[InlineKeyboardButton("🔐 Login", callback_data="login_flow")]]
            return await update.message.reply_text(f"⚠️ Login required for ID: {local_id}", reply_markup=InlineKeyboardMarkup(kb))
        context.user_data['deep_link_id'] = local_id
        await new_order_start(update, context); return

    # Welcome / Login Prompt
    if not db_user:
        kb = [[InlineKeyboardButton("🔐 Login", callback_data="login_flow")], [InlineKeyboardButton("📝 Register", url="https://k2boost.org/createaccount")]]
        return await update.message.reply_text(f"Welcome {user.first_name}!\nPlease Login.", reply_markup=InlineKeyboardMarkup(kb))
    
    await help_command(update, context)

# =========================================
# 🔑 LOGIN FLOW (The missing part)
# =========================================

async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("📧 Enter Email:")
    return config.WAITING_EMAIL

async def receive_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['login_email'] = update.message.text.strip().lower()
    await update.message.reply_text("🔑 Enter Password:")
    return config.WAITING_PASSWORD

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
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="✅ Success! Language:", reply_markup=InlineKeyboardMarkup(kb))
            return config.LOGIN_LANG
        else:
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="❌ Failed.")
            await start(update, context); return ConversationHandler.END
    except:
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="❌ Error.")
        await start(update, context); return ConversationHandler.END

async def login_set_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data['temp_lang'] = query.data.split("_")[1]
    kb = [[InlineKeyboardButton("USD", callback_data="curr_USD"), InlineKeyboardButton("MMK", callback_data="curr_MMK")]]
    await query.edit_message_text("Select Currency:", reply_markup=InlineKeyboardMarkup(kb))
    return config.LOGIN_CURR

async def login_set_curr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    supabase.table('users').update({'language': context.user_data.get('temp_lang'), 'currency': query.data.split("_")[1]}).eq('telegram_id', update.effective_user.id).execute()
    await query.edit_message_text("✅ Setup Done!")
    await help_command(update, context); return ConversationHandler.END

# =========================================
# ℹ️ HELPER COMMANDS
# =========================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db_user = get_user(user_id)
    if not db_user: return await start(update, context)
    
    lang = db_user.get('language', 'en'); curr = db_user.get('currency', 'USD')
    bal = format_currency(float(db_user.get('balance', 0)), curr)
    
    msg = f"{get_text(lang, 'help_title')}\n📧 {db_user.get('email')}\n💰 {bal}\n\n{get_text(lang, 'help_msg')}"
    
    if update.callback_query: await update.callback_query.message.reply_text(msg, parse_mode='Markdown')
    else: await update.message.reply_text(msg, parse_mode='Markdown')

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Usage: `/check 1234`", parse_mode='Markdown')
    ids = context.args[0].split(','); msg = ""; user = get_user(update.effective_user.id)
    for oid in ids:
        if not oid.strip().isdigit(): continue
        try:
            o_res = supabase.table('WebsiteOrders').select("*").eq('id', oid.strip()).eq('email', user['email']).execute()
            if o_res.data:
                o = o_res.data[0]; s_name = "Unknown"
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
    user_id = update.effective_user.id; db_user = get_user(user_id)
    try:
        orders = supabase.table('WebsiteOrders').select("*").eq('email', db_user['email']).order('id', desc=True).limit(5).execute().data
        if not orders: return await update.message.reply_text("No history.")
        msg = "📜 **History**\n\n"
        for o in orders: msg += f"🆔 `{o['id']}` | 🔢 {o['quantity']} | ✅ {o['status']}\n🔗 {o['link']}\n----------------\n"
        await update.message.reply_text(msg, parse_mode='Markdown', disable_web_page_preview=True)
    except: await update.message.reply_text("Error fetching history.")

async def services_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛍 **Services:**\nCheck @k2boost for prices.", parse_mode='Markdown')

# =========================================
# ⚙️ SETTINGS
# =========================================

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("Language", callback_data="set_lang_start"), InlineKeyboardButton("Currency", callback_data="set_curr_start")]]
    await update.message.reply_text("⚙️ Settings:", reply_markup=InlineKeyboardMarkup(kb))

async def change_lang_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("English", callback_data="set_en"), InlineKeyboardButton("Myanmar", callback_data="set_mm")]]
    await update.callback_query.message.edit_text("Select Language:", reply_markup=InlineKeyboardMarkup(kb))
    return config.CMD_LANG_SELECT

async def change_curr_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("USD", callback_data="set_USD"), InlineKeyboardButton("MMK", callback_data="set_MMK")]]
    await update.callback_query.message.edit_text("Select Currency:", reply_markup=InlineKeyboardMarkup(kb))
    return config.CMD_CURR_SELECT

async def setting_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data = query.data; user_id = update.effective_user.id
    if "set_en" in data or "set_mm" in data:
        lang = "en" if "en" in data else "mm"
        supabase.table('users').update({'language': lang}).eq('telegram_id', user_id).execute()
        await query.message.edit_text("✅ Language Updated!")
    elif "set_USD" in data or "set_MMK" in data:
        curr = "USD" if "USD" in data else "MMK"
        supabase.table('users').update({'currency': curr}).eq('telegram_id', user_id).execute()
        await query.message.edit_text("✅ Currency Updated!")
    await help_command(update, context); return ConversationHandler.END

async def cancel_op(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 Canceled.")
    await help_command(update, context); return ConversationHandler.END

# =========================================
# 🛒 ORDER HANDLERS
# =========================================

async def new_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; db_user = get_user(user.id)
    if not db_user: return await start(update, context)
    target_id = None
    if context.args: target_id = context.args[0]
    elif context.user_data.get('deep_link_id'): target_id = context.user_data.pop('deep_link_id')
    if not target_id:
        await update.message.reply_text("Usage: `/neworder <ID>`", parse_mode='Markdown'); return ConversationHandler.END
    if "order_" in target_id: target_id = target_id.split("_")[1]
    
    res = supabase.table('services').select("*").eq('id', target_id).execute()
    if not res.data: return await update.message.reply_text("❌ ID Not Found.");
    
    svc = res.data[0]; context.user_data['order_svc'] = svc
    lang = db_user.get('language', 'en'); curr = db_user.get('currency', 'USD')
    
    prompt = "🔗 **Link:**"
    if svc.get('use_type') == 'Telegram username': prompt = "🔗 **Username (@...):**"
    await update.message.reply_text(f"{format_for_user(svc, lang, curr)}\n\n{prompt}", parse_mode='Markdown')
    return config.ORDER_WAITING_LINK

async def new_order_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['order_link'] = update.message.text.strip()
    svc = context.user_data['order_svc']
    await update.message.reply_text(f"📊 **Quantity**\nMin: {svc['min']} - Max: {svc['max']}")
    return config.ORDER_WAITING_QTY

async def new_order_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: qty = int(update.message.text.strip())
    except: return await update.message.reply_text("❌ Numbers only.")
    svc = context.user_data['order_svc']
    if qty < svc['min'] or qty > svc['max']: return await update.message.reply_text(f"❌ Invalid Qty.")
    context.user_data['order_qty'] = qty
    cost_usd = calculate_cost(qty, svc)
    context.user_data['cost_usd'] = cost_usd
    user = get_user(update.effective_user.id)
    lang = user.get('language', 'en'); curr = user.get('currency', 'USD')
    cost_display = format_currency(cost_usd, curr)
    text = get_text(lang, 'confirm_order', cost=cost_display)
    kb = [[InlineKeyboardButton("✅ Yes", callback_data="yes"), InlineKeyboardButton("❌ No", callback_data="no")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return config.ORDER_CONFIRM

async def new_order_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == 'no':
        await query.edit_message_text("🚫 Canceled."); return ConversationHandler.END
    user = get_user(update.effective_user.id); cost_usd = context.user_data['cost_usd']
    if float(user['balance']) < cost_usd:
        await query.edit_message_text("⚠️ Insufficient Balance."); return ConversationHandler.END
    try:
        new_bal = float(user['balance']) - cost_usd
        supabase.table('users').update({'balance': new_bal}).eq('telegram_id', user.id).execute()
        o_data = {
            "email": user['email'], "service": context.user_data['order_svc']['service_id'],
            "link": context.user_data['order_link'], "quantity": context.user_data['order_qty'],
            "buy_charge": cost_usd, "status": "Pending", "UsedType": "NewOrder", 
            "supplier_service_id": context.user_data['order_svc']['service_id'], "supplier_name": "smmgen"
        }
        inserted = supabase.table('WebsiteOrders').insert(o_data).execute()
        local_id = inserted.data[0]['id'] if inserted.data else "N/A"
        await query.edit_message_text(f"✅ **Order Queued!**\nID: {local_id}", parse_mode='Markdown')
    except: await query.edit_message_text("❌ Error.")
    await help_command(update, context); return ConversationHandler.END

# --- MASS ORDER ---
async def mass_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 **Mass Order**\n`ID | Link | Qty`\n\nSend list:", parse_mode='Markdown')
    return config.WAITING_MASS_INPUT

async def mass_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = update.message.text.strip().split('\n'); valid_orders = []; total_cost = 0.0
    for line in lines:
        try:
            parts = [p.strip() for p in line.split('|')]
            if len(parts) != 3: continue
            sid, link, qty = parts[0], parts[1], int(parts[2])
            res = supabase.table('services').select("*").eq('id', sid).execute()
            if not res.data: continue
            svc = res.data[0]; cost = calculate_cost(qty, svc)
            total_cost += cost
            valid_orders.append({'svc': svc, 'link': link, 'qty': qty, 'cost': cost})
        except: continue
    context.user_data['mass_queue'] = valid_orders; context.user_data['mass_total'] = total_cost
    user = get_user(update.effective_user.id); curr = user.get('currency', 'USD')
    summary = f"📊 **Mass Order**\nValid: {len(valid_orders)}\nTotal: {format_currency(total_cost, curr)}"
    kb = [[InlineKeyboardButton("✅ Yes", callback_data="mass_yes"), InlineKeyboardButton("❌ No", callback_data="mass_no")]]
    await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return config.WAITING_MASS_CONFIRM

async def mass_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == 'mass_no':
        await query.edit_message_text("🚫 Canceled."); return ConversationHandler.END
    user = get_user(update.effective_user.id); total = context.user_data['mass_total']
    if float(user['balance']) < total:
        await query.edit_message_text("⚠️ Insufficient Balance."); return ConversationHandler.END
    try:
        new_bal = float(user['balance']) - total
        supabase.table('users').update({'balance': new_bal}).eq('telegram_id', user.id).execute()
        for o in context.user_data['mass_queue']:
            supabase.table('WebsiteOrders').insert({
                "email": user['email'], "service": o['svc']['service_id'], "link": o['link'], 
                "quantity": o['qty'], "buy_charge": o['cost'], "status": "Pending", 
                "UsedType": "MassOrder", "supplier_service_id": o['svc']['service_id'], "supplier_name": "smmgen"
            }).execute()
        await query.edit_message_text("✅ Mass Order Queued!")
    except: await query.edit_message_text("❌ Error.")
    await help_command(update, context); return ConversationHandler.END

# --- SUPPORT ---
async def sup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("Refill", callback_data="s_Refill"), InlineKeyboardButton("Cancel", callback_data="s_Cancel")]]
    await update.message.reply_text("Select Issue:", reply_markup=InlineKeyboardMarkup(kb))

async def sup_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data['stype'] = query.data.split("_")[1]
    await query.edit_message_text("Send Order IDs (e.g. 1234):")
    return config.WAITING_SUPPORT_ID

async def sup_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = get_user(update.effective_user.id); ids = update.message.text.split(',')
        stype = context.user_data.get('stype', 'Other')
        for lid in ids:
            if not lid.strip().isdigit(): continue
            supabase.table('SupportBox').insert({"email": user['email'], "subject": stype, "order_id": lid.strip(), "status": "Pending", "UserStatus": "unread"}).execute()
        await update.message.reply_text("✅ Ticket Created.")
        await help_command(update, context); return ConversationHandler.END
    except: return ConversationHandler.END

# =========================================
# 🛠️ ADMIN COMMANDS
# =========================================

async def admin_check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in [config.AFFILIATE_GROUP_ID, config.SUPPLIER_GROUP_ID]: return
    try:
        email = context.args[0]
        user = supabase.table("users").select("balance").eq("email", email).execute().data
        if user: await update.message.reply_text(f"💰 Balance: ${user[0]['balance']}")
        else: await update.message.reply_text("❌ Not found.")
    except: await update.message.reply_text("Usage: /balance email")

async def admin_manual_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.AFFILIATE_GROUP_ID: return
    try:
        email = context.args[0]; amount = float(context.args[1])
        user = supabase.table("users").select("balance").eq("email", email).execute().data
        if user:
            old = float(user[0]['balance']); new = old + amount
            supabase.table("users").update({"balance": new}).eq("email", email).execute()
            await update.message.reply_text("✅ Done.")
            notify_group(config.AFFILIATE_GROUP_ID, f"✅ **Manual Topup**\nUser: `{email}`\nAdded: `${amount}`\nBalance: `${old}` ➝ `${new}`")
        else: await update.message.reply_text("❌ Not found.")
    except: await update.message.reply_text("Usage: /Topup email amount")

async def admin_tx_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.AFFILIATE_GROUP_ID: return
    try:
        tx_id = int(context.args[0])
        tx = supabase.table("transactions").select("*").eq("id", tx_id).execute().data
        if tx and tx[0]['status'] != 'Accepted':
            user = supabase.table("users").select("balance").eq("email", tx[0]['email']).execute().data
            if user:
                old = float(user[0]['balance']); amt = float(tx[0]['amount']); new = old + amt
                supabase.table("users").update({"balance": new}).eq("email", tx[0]['email']).execute()
                supabase.table("transactions").update({"status": "Accepted"}).eq("id", tx_id).execute()
                await update.message.reply_text("✅ Approved.")
                notify_group(config.AFFILIATE_GROUP_ID, f"✅ **Transaction Approved**\nUser: `{tx[0]['email']}`\nBalance: `${old}` ➝ `${new}`")
    except: pass

async def admin_tx_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.AFFILIATE_GROUP_ID: return
    try:
        tx_id = int(context.args[0])
        supabase.table("transactions").update({"status": "Rejected"}).eq("id", tx_id).execute()
        await update.message.reply_text("❌ Rejected.")
    except: pass

async def admin_aff_accept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.AFFILIATE_GROUP_ID: return
    try:
        rid = int(context.args[0])
        supabase.table("affiliate").update({"status": "Accepted"}).eq("id", rid).execute()
        await update.message.reply_text("✅ Accepted.")
    except: pass

async def admin_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only allow in generic admin or supplier group
    if update.effective_chat.id not in [config.SUPPLIER_GROUP_ID]: return
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
        try:
            await context.bot.send_message(config.CHANNEL_ID, text=msg, parse_mode='HTML', disable_web_page_preview=True)
            time.sleep(3)
        except: pass
    await update.message.reply_text("Done.")

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in [config.SUPPLIER_GROUP_ID, config.AFFILIATE_GROUP_ID]: return
    if context.args:
        supabase.table('users').update({'is_banned': True}).eq('email', context.args[0]).execute()
        await update.message.reply_text(f"🚫 Banned {context.args[0]}")

async def admin_swap_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.SUPPLIER_GROUP_ID: return
    try:
        local_id = context.args[0]; new_sup_id = context.args[1]
        payload = {'key': config.SMM_API_KEY, 'action': 'services'}
        res = requests.post(config.SMM_API_URL, data=payload).json()
        target = next((s for s in res if str(s['service']) == str(new_sup_id)), None)
        if target:
            supabase.table("services").update({"service_id": new_sup_id, "buy_price": float(target['rate'])}).eq("id", local_id).execute()
            await update.message.reply_text(f"✅ Swapped Local ID {local_id} to Supplier {new_sup_id}")
        else: await update.message.reply_text("❌ Supplier ID not found.")
    except: await update.message.reply_text("Usage: /swap LocalID SupplierID")

async def admin_change_attr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.SUPPLIER_GROUP_ID: return
    try:
        args = context.args
        if len(args) >= 4 and args[0].isdigit() and args[1].isdigit(): # Range
            start, end, field, val = int(args[0]), int(args[1]), args[2], " ".join(args[3:])
            supabase.table("services").update({field.lower(): val}).gte("id", start).lte("id", end).execute()
            await update.message.reply_text(f"✅ Bulk Updated ID {start}-{end}")
        elif len(args) >= 3 and args[0].isdigit(): # Single
            tid, field, val = int(args[0]), args[1], " ".join(args[2:])
            supabase.table("services").update({field.lower(): val}).eq("id", tid).execute()
            await update.message.reply_text(f"✅ Updated ID {tid}")
        elif update.message.reply_to_message: # Reply
            field, val = args[0], " ".join(args[1:])
            txt = update.message.reply_to_message.text
            tid = next((s for s in txt.split() if s.isdigit()), None)
            if tid:
                supabase.table("services").update({field.lower(): val}).eq("id", tid).execute()
                await update.message.reply_text(f"✅ Updated ID {tid}")
    except: await update.message.reply_text("Error.")
