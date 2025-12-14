import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
import config
from db import supabase, get_user
from utils import get_text, format_currency, calculate_cost, format_for_user

def notify_group(chat_id, text):
    try: requests.post(f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except: pass

# =========================================
# 🔐 AUTH & START HANDLERS
# =========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = get_user(user.id)
    args = context.args
    
    # 1. Group Chat Redirect
    if update.effective_chat.type != 'private':
        if not db_user:
            bot_username = (await context.bot.get_me()).username
            kb = [[InlineKeyboardButton("🔐 Login in Private", url=f"https://t.me/{bot_username}?start=login")]]
            return await update.message.reply_text("⚠️ Login first in Private Chat.", reply_markup=InlineKeyboardMarkup(kb))
        if not args: return await update.message.reply_text(f"👋 {user.first_name}! Ready.")
    
    # 2. Deep Link (order_123)
    if args and args[0].startswith("order_"):
        local_id = args[0].split("_")[1]
        if not db_user:
            context.user_data['pending_order_id'] = local_id
            kb = [[InlineKeyboardButton("🔐 Login", callback_data="login_flow")]]
            return await update.message.reply_text(f"⚠️ Login required for ID: {local_id}", reply_markup=InlineKeyboardMarkup(kb))
        context.user_data['deep_link_id'] = local_id
        await new_order_start(update, context); return

    # 3. Login Prompt
    if not db_user:
        kb = [[InlineKeyboardButton("🔐 Login", callback_data="login_flow")], [InlineKeyboardButton("📝 Register", url="https://k2boost.org/createaccount")]]
        return await update.message.reply_text(f"Welcome {user.first_name}!\nPlease Login.", reply_markup=InlineKeyboardMarkup(kb))
    
    await help_command(update, context)

# --- LOGIN FLOW ---
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
            
            pending_id = context.user_data.pop('pending_order_id', None)
            if pending_id:
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="✅ Login Success! Resuming...")
                context.user_data['deep_link_id'] = pending_id
                await new_order_start(update, context)
                return ConversationHandler.END
            
            kb = [[InlineKeyboardButton("English", callback_data="lang_en"), InlineKeyboardButton("Myanmar", callback_data="lang_mm")]]
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="✅ Success! Language:", reply_markup=InlineKeyboardMarkup(kb))
            return config.LOGIN_LANG
        else:
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="❌ Login Failed.")
            await start(update, context); return ConversationHandler.END
    except:
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text="❌ Error / Wrong Password.")
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

async def cancel_op(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 Canceled.")
    await help_command(update, context); return ConversationHandler.END

# =========================================
# ℹ️ HELPERS
# =========================================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id; db_user = get_user(user_id)
    if not db_user: return await start(update, context)
    
    bal = format_currency(float(db_user.get('balance_usd', 0)), db_user.get('currency', 'USD'))
    msg = f"{get_text(db_user.get('language', 'en'), 'help_title')}\n📧 {db_user.get('email')}\n💰 {bal}\n\n{get_text(db_user.get('language', 'en'), 'help_msg')}"
    
    if update.callback_query: await update.callback_query.message.reply_text(msg, parse_mode='Markdown')
    else: await update.message.reply_text(msg, parse_mode='Markdown')

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Usage: `/check 1234`", parse_mode='Markdown')
    ids = context.args[0].split(','); msg = ""; user = get_user(update.effective_user.id)
    for oid in ids:
        if not oid.strip().isdigit(): continue
        try:
            o = supabase.table('WebsiteOrders').select("*").eq('id', oid.strip()).eq('email', user['email']).execute().data
            if o: msg += f"🆔 `{o[0]['id']}` | 🔢 {o[0]['quantity']} | ✅ {o[0]['status']}\n\n"
            else: msg += f"❌ Order {oid}: Not found.\n"
        except: pass
    await update.message.reply_text(msg)

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        orders = supabase.table('WebsiteOrders').select("*").eq('email', get_user(update.effective_user.id)['email']).order('id', desc=True).limit(5).execute().data
        if not orders: return await update.message.reply_text("No history.")
        msg = "📜 **History**\n\n"
        for o in orders: msg += f"🆔 `{o['id']}` | 🔢 {o['quantity']} | ✅ {o['status']}\n🔗 {o['link']}\n----------------\n"
        await update.message.reply_text(msg, parse_mode='Markdown', disable_web_page_preview=True)
    except: await update.message.reply_text("Error.")

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
        supabase.table('users').update({'language': "en" if "en" in data else "mm"}).eq('telegram_id', user_id).execute()
        await query.message.edit_text("✅ Language Updated!")
    elif "set_USD" in data or "set_MMK" in data:
        supabase.table('users').update({'currency': "USD" if "USD" in data else "MMK"}).eq('telegram_id', user_id).execute()
        await query.message.edit_text("✅ Currency Updated!")
    await help_command(update, context); return ConversationHandler.END

# =========================================
# 🛒 ORDERS & MASS ORDERS (🔥 Fixed Errors Here)
# =========================================

async def new_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; db_user = get_user(user.id)
    if not db_user: return await start(update, context)
    
    # Get ID from args or deep link
    target_id = None
    if context.args: target_id = context.args[0]
    elif context.user_data.get('deep_link_id'): target_id = context.user_data.pop('deep_link_id')
    
    # 🛑 FIX: Split Return Statements
    if not target_id:
        await update.message.reply_text("Usage: `/neworder <ID>`", parse_mode='Markdown')
        return ConversationHandler.END
        
    if "order_" in target_id: target_id = target_id.split("_")[1]
    
    res = supabase.table('services').select("*").eq('id', target_id).execute()
    if not res.data:
        await update.message.reply_text("❌ ID Not Found.")
        return ConversationHandler.END
        
    svc = res.data[0]; context.user_data['order_svc'] = svc
    prompt = "🔗 **Username:**" if svc.get('use_type') == 'Telegram username' else "🔗 **Link:**"
    
    await update.message.reply_text(f"{format_for_user(svc, db_user.get('language','en'), db_user.get('currency','USD'))}\n\n{prompt}", parse_mode='Markdown')
    return config.ORDER_WAITING_LINK

async def new_order_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['order_link'] = update.message.text.strip()
    svc = context.user_data['order_svc']
    await update.message.reply_text(f"📊 **Quantity**\nMin: {svc['min']} - Max: {svc['max']}")
    return config.ORDER_WAITING_QTY

async def new_order_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: qty = int(update.message.text.strip())
    except: 
        await update.message.reply_text("❌ Numbers only.")
        return config.ORDER_WAITING_QTY
        
    svc = context.user_data['order_svc']
    if qty < svc['min'] or qty > svc['max']:
        await update.message.reply_text(f"❌ Invalid Qty. ({svc['min']}-{svc['max']})")
        return config.ORDER_WAITING_QTY
        
    context.user_data['order_qty'] = qty
    cost = calculate_cost(qty, svc)
    context.user_data['cost_usd'] = cost
    
    user = get_user(update.effective_user.id)
    cost_display = format_currency(cost, user.get('currency', 'USD'))
    text = get_text(user.get('language','en'), 'confirm_order', cost=cost_display)
    
    kb = [[InlineKeyboardButton("✅ Yes", callback_data="yes"), InlineKeyboardButton("❌ No", callback_data="no")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    return config.ORDER_CONFIRM

async def new_order_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == 'no':
        await query.edit_message_text("🚫 Canceled.")
        return ConversationHandler.END
        
    user = get_user(update.effective_user.id); cost = context.user_data['cost_usd']
    
    if float(user['balance_usd']) < cost:
        await query.edit_message_text("⚠️ Insufficient Balance.")
        return ConversationHandler.END
        
    try:
        new_bal = float(user['balance_usd']) - cost
        supabase.table('users').update({'balance_usd': new_bal}).eq('telegram_id', user.id).execute()
        o_data = {"email": user['email'], "service": context.user_data['order_svc']['service_id'], "link": context.user_data['order_link'], 
                  "quantity": context.user_data['order_qty'], "buy_charge": cost, "status": "Pending", "UsedType": "NewOrder", 
                  "supplier_service_id": context.user_data['order_svc']['service_id'], "supplier_name": "smmgen"}
        inserted = supabase.table('WebsiteOrders').insert(o_data).execute()
        await query.edit_message_text(f"✅ **Order Queued!**\nID: {inserted.data[0]['id']}", parse_mode='Markdown')
    except: await query.edit_message_text("❌ Error.")
    
    await help_command(update, context); return ConversationHandler.END

# --- MASS ORDER ---
async def mass_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 **Mass Order**\nFormat: `ID | Link | Qty`\n(One per line)", parse_mode='Markdown')
    return config.WAITING_MASS_INPUT

async def mass_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = update.message.text.strip().split('\n'); valid = []; total = 0.0
    for line in lines:
        try:
            p = [x.strip() for x in line.split('|')]
            if len(p)!=3: continue
            res = supabase.table('services').select("*").eq('id', p[0]).execute()
            if res.data:
                cost = calculate_cost(int(p[2]), res.data[0]); total += cost
                valid.append({'svc': res.data[0], 'link': p[1], 'qty': int(p[2]), 'cost': cost})
        except: continue
    context.user_data['mass_queue'] = valid; context.user_data['mass_total'] = total
    curr = get_user(update.effective_user.id).get('currency', 'USD')
    await update.message.reply_text(f"📊 Valid: {len(valid)}\nTotal: {format_currency(total, curr)}\nConfirm?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅", callback_data="mass_yes"), InlineKeyboardButton("❌", callback_data="mass_no")]]))
    return config.WAITING_MASS_CONFIRM

async def mass_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == 'mass_no':
        await query.edit_message_text("🚫 Canceled.")
        return ConversationHandler.END
        
    user = get_user(update.effective_user.id); total = context.user_data['mass_total']
    if float(user['balance_usd']) < total:
        await query.edit_message_text("⚠️ Insufficient Balance.")
        return ConversationHandler.END
        
    try:
        new_bal = float(user['balance_usd']) - total
        supabase.table('users').update({'balance_usd': new_bal}).eq('telegram_id', user.id).execute()
        for o in context.user_data['mass_queue']:
            supabase.table('WebsiteOrders').insert({"email": user['email'], "service": o['svc']['service_id'], "link": o['link'], "quantity": o['qty'], "buy_charge": o['cost'], "status": "Pending", "UsedType": "MassOrder", "supplier_service_id": o['svc']['service_id'], "supplier_name": "smmgen"}).execute()
        await query.edit_message_text("✅ Mass Order Queued!")
    except: await query.edit_message_text("❌ Error.")
    
    await help_command(update, context); return ConversationHandler.END

# =========================================
# 💬 SUPPORT
# =========================================
async def sup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("Refill", callback_data="s_Refill"), InlineKeyboardButton("Cancel", callback_data="s_Cancel")]]
    await update.message.reply_text("Select Issue:", reply_markup=InlineKeyboardMarkup(kb))

async def sup_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data['stype'] = query.data.split("_")[1]
    await query.edit_message_text("Send Order IDs (comma separated):")
    return config.WAITING_SUPPORT_ID

async def sup_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = get_user(update.effective_user.id)
        for lid in update.message.text.split(','):
            if lid.strip().isdigit(): supabase.table('SupportBox').insert({"email": user['email'], "subject": context.user_data['stype'], "order_id": lid.strip(), "status": "Pending", "UserStatus": "unread"}).execute()
        await update.message.reply_text("✅ Ticket Created.")
        await help_command(update, context); return ConversationHandler.END
    except: return ConversationHandler.END

# =========================================
# 🛠️ ADMIN COMMANDS (All Included)
# =========================================

# --- A. AFFILIATE & FINANCE (Group: Affiliate) ---
async def admin_check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.AFFILIATE_GROUP_ID: return
    try:
        u = supabase.table("users").select("balance_usd").eq("email", context.args[0]).execute().data
        await update.message.reply_text(f"💰 Balance: ${u[0]['balance_usd']}" if u else "❌ Not found")
    except: pass

async def admin_manual_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.AFFILIATE_GROUP_ID: return
    try:
        email = context.args[0]; amt = float(context.args[1])
        u = supabase.table("users").select("balance_usd").eq("email", email).execute().data
        if u:
            old = float(u[0]['balance_usd']); new = old + amt
            supabase.table("users").update({"balance_usd": new}).eq("email", email).execute()
            notify_group(config.AFFILIATE_GROUP_ID, f"✅ **Manual Topup**\nUser: `{email}`\nAdded: `${amt}`\nBal: `${old}` ➝ `${new}`")
            await update.message.reply_text("Done.")
    except: pass

async def admin_tx_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.AFFILIATE_GROUP_ID: return
    try:
        tx_id = int(context.args[0]); tx = supabase.table("transactions").select("*").eq("id", tx_id).execute().data
        if tx and tx[0]['status'] != 'Accepted':
            u = supabase.table("users").select("balance_usd").eq("email", tx[0]['email']).execute().data
            if u:
                old = float(u[0]['balance_usd']); new = old + float(tx[0]['amount'])
                supabase.table("users").update({"balance_usd": new}).eq("email", tx[0]['email']).execute()
                supabase.table("transactions").update({"status": "Accepted"}).eq("id", tx_id).execute()
                notify_group(config.AFFILIATE_GROUP_ID, f"✅ **Approved**\nUser: `{tx[0]['email']}`\nBal: `${old}` ➝ `${new}`")
                await update.message.reply_text("Approved.")
    except: pass

async def admin_tx_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.AFFILIATE_GROUP_ID: return
    try: supabase.table("transactions").update({"status": "Rejected"}).eq("id", int(context.args[0])).execute(); await update.message.reply_text("Rejected.")
    except: pass

async def admin_aff_accept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.AFFILIATE_GROUP_ID: return
    try:
        aff_id = int(context.args[0])
        res = supabase.table("affiliate").select("*").eq("id", aff_id).execute().data
        if res:
            row = res[0]; email = row["email"]; amount = float(row["amount"])
            u = supabase.table("users").select("balance_usd").eq("email", email).execute().data
            if u:
                new_bal = float(u[0]["balance_usd"]) + amount
                supabase.table("users").update({"balance_usd": new_bal}).eq("email", email).execute()
                supabase.table("affiliate").update({"status": "Accepted"}).eq("id", aff_id).execute()
                await update.message.reply_text(f"✅ Affiliate {aff_id} Accepted.")
    except: pass

async def admin_aff_failed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.AFFILIATE_GROUP_ID: return
    try: supabase.table("affiliate").update({"status": "Failed"}).eq("id", int(context.args[0])).execute(); await update.message.reply_text("❌ Marked Failed.")
    except: pass

async def admin_verify_use(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.AFFILIATE_GROUP_ID: return
    try: supabase.table("VerifyPayment").update({"status": "used"}).eq("transaction_id", context.args[0]).execute(); await update.message.reply_text("✅ Marked Used.")
    except: pass

# --- B. K2BOOST / ORDERS ---
async def admin_order_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.K2BOOST_GROUP_ID: return
    try:
        oid = context.args[0]
        supabase.table("WebsiteOrders").update({"status": "Completed"}).eq("id", int(oid)).execute()
        await update.message.reply_text(f"✅ Order {oid} Completed.")
    except: pass

async def admin_order_error(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.K2BOOST_GROUP_ID: return
    try:
        oid = context.args[0]
        order = supabase.table("WebsiteOrders").select("*").eq("id", int(oid)).execute().data
        if order and order[0]['status'] != 'Canceled':
            o = order[0]
            u = supabase.table("users").select("balance_usd").eq("email", o['email']).execute().data
            if u:
                new_bal = float(u[0]['balance_usd']) + float(o['sell_charge'])
                supabase.table("users").update({"balance_usd": new_bal}).eq("email", o['email']).execute()
                supabase.table("WebsiteOrders").update({"status": "Canceled"}).eq("id", int(oid)).execute()
                await update.message.reply_text(f"❌ Order {oid} Canceled & Refunded.")
    except: pass

# --- C. SUPPORT ---
async def admin_reply_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.SUPPORT_GROUP_ID: return
    try:
        tid = context.args[0]; reply_msg = " ".join(context.args[1:])
        supabase.table("SupportBox").update({"reply_text": reply_msg, "status": "Replied", "UserStatus": "unread"}).eq("id", tid).execute()
        await update.message.reply_text(f"✅ Replied to #{tid}")
    except: pass

async def admin_ticket_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.SUPPORT_GROUP_ID: return
    try: supabase.table("SupportBox").update({"status": "Closed"}).eq("id", context.args[0]).execute(); await update.message.reply_text("🔒 Closed.")
    except: pass

# --- D. SYSTEM ADMIN ---
async def admin_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.REPORT_GROUP_ID: return
    svcs = supabase.table('services').select("*").order('id', desc=False).execute().data
    cats = {}
    for s in svcs: cats.setdefault(s['category'], []).append(s)
    await update.message.reply_text("Posting...")
    for c, items in cats.items():
        msg = f"📂 <b>{c}</b>\n➖➖➖➖➖\n\n"
        for s in items: msg += f"⚡ <a href='https://t.me/{(await context.bot.get_me()).username}?start=order_{s['id']}'>ID:{s['id']} - {s['service_name']}</a>\n\n"
        try: await context.bot.send_message(config.CHANNEL_ID, text=msg, parse_mode='HTML', disable_web_page_preview=True); 
        except: pass
    await update.message.reply_text("Done.")

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.REPORT_GROUP_ID: return
    if context.args: supabase.table('users').update({'is_banned': True}).eq('email', context.args[0]).execute(); await update.message.reply_text("Banned.")

async def admin_swap_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.REPORT_GROUP_ID: return
    try:
        lid = context.args[0]; nid = context.args[1]
        res = requests.post(config.SMM_API_URL, data={'key': config.SMM_API_KEY, 'action': 'services'}).json()
        target = next((s for s in res if str(s['service']) == str(nid)), None)
        if target:
            supabase.table("services").update({"service_id": nid, "buy_price": float(target['rate'])}).eq("id", lid).execute()
            await update.message.reply_text(f"✅ Swapped {lid} to {nid}")
    except: pass

async def admin_change_attr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.REPORT_GROUP_ID: return
    try:
        args = context.args
        if len(args) >= 4 and args[0].isdigit(): 
            supabase.table("services").update({args[2].lower(): " ".join(args[3:])}).gte("id", int(args[0])).lte("id", int(args[1])).execute()
            await update.message.reply_text("✅ Bulk Updated.")
        elif len(args) >= 3 and args[0].isdigit(): 
            supabase.table("services").update({args[1].lower(): " ".join(args[2:])}).eq("id", int(args[0])).execute()
            await update.message.reply_text("✅ Updated.")
    except: pass
