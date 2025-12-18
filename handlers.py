import requests
import re
import html
import time
import unicodedata 
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
import config
from db import supabase, get_user
from utils import get_text, format_currency, calculate_cost, format_for_user, clean_service_name, calculate_sell_price, get_link_prompt

def notify_group(chat_id, text):
    try: requests.post(f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=10)
    except: pass

# =========================================
# 🔐 AUTH & START HANDLERS
# =========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = get_user(user.id)
    args = context.args
    
    if update.effective_chat.type != 'private':
        if not db_user:
            bot_username = (await context.bot.get_me()).username
            kb = [[InlineKeyboardButton("🔐 Login in Private", url=f"https://t.me/{bot_username}?start=login")]]
            return await update.message.reply_text("⚠️ Login first in Private Chat.", reply_markup=InlineKeyboardMarkup(kb))
        if not args: return await update.message.reply_text(f"👋 {user.first_name}! Ready.")
    
    if args and args[0].startswith("order_"):
        local_id = args[0].split("_")[1]
        if not db_user:
            context.user_data['pending_order_id'] = local_id
            kb = [[InlineKeyboardButton("🔐 Login", callback_data="login_flow")]]
            return await update.message.reply_text(f"⚠️ Login required for ID: {local_id}", reply_markup=InlineKeyboardMarkup(kb))
        context.user_data['deep_link_id'] = local_id
        await new_order_start(update, context); return

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
    
    if update.callback_query: await update.callback_query.message.reply_text(msg, parse_mode='HTML', disable_web_page_preview=True)
    else: await update.message.reply_text(msg, parse_mode='HTML', disable_web_page_preview=True)

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Usage: <code>/check ID</code>", parse_mode='HTML')
    
    input_ids = context.args[0].split(',')
    msg = ""
    user = get_user(update.effective_user.id)
    
    for oid in input_ids:
        oid = oid.strip()
        if not oid: continue
        
        try:
            data = supabase.table('WebsiteOrders').select("*").eq('email', user['email']).or_(f"id.eq.{oid},supplier_order_id.eq.{oid}").execute().data
            
            if data:
                o = data[0]
                display_id = o['supplier_order_id'] if o['supplier_name'] != 'k2boost' and o['supplier_order_id'] != '0' else o['id']
                svc_name = html.escape(o.get('service', 'Service'))
                msg += (f"🆔 <code>{display_id}</code> | 🔢 {o['quantity']} | ✅ {o['status']}\n"
                        f"📦 {svc_name}\n\n")
            else:
                msg += f"❌ Order {oid}: Not found.\n"
        except: pass
        
    await update.message.reply_text(msg if msg else "❌ Not found.", parse_mode='HTML')

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        orders = supabase.table('WebsiteOrders').select("*").eq('email', get_user(update.effective_user.id)['email']).order('id', desc=True).limit(5).execute().data
        if not orders: return await update.message.reply_text("No history.")
        
        msg = "📜 <b>History (Last 5)</b>\n\n"
        for o in orders:
            if o.get('supplier_name') != 'k2boost' and o.get('supplier_order_id') and o.get('supplier_order_id') != '0':
                show_id = f"<code>{o['supplier_order_id']}</code>"
            else:
                show_id = f"<code>{o['id']}</code>"
            
            svc_name = html.escape(o.get('service', 'Service'))
            msg += (
                f"🆔 {show_id} | 🔢 {o['quantity']} | ✅ {o['status']}\n"
                f"📦 {svc_name}\n"
                f"🔗 {html.escape(o['link'])}\n"
                f"----------------\n"
            )
            
        await update.message.reply_text(msg, parse_mode='HTML', disable_web_page_preview=True)
    except: await update.message.reply_text("Error fetching history.")

async def services_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛍 <b>Services:</b>\nCheck @k2boost for prices.", parse_mode='HTML')

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
# 🛒 ORDERS & MASS ORDERS (Smart Logic)
# =========================================

async def new_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; db_user = get_user(user.id)
    if not db_user: return await start(update, context)
    
    target_id = None
    if context.args: target_id = context.args[0]
    elif context.user_data.get('deep_link_id'): target_id = context.user_data.pop('deep_link_id')
    
    if not target_id:
        await update.message.reply_text("Usage: <code>/neworder ID</code>", parse_mode='HTML')
        return ConversationHandler.END
        
    if "order_" in target_id: target_id = target_id.split("_")[1]
    
    res = supabase.table('services').select("*").eq('id', target_id).execute()
    if not res.data:
        await update.message.reply_text("❌ ID Not Found.")
        return ConversationHandler.END
        
    svc = res.data[0]; context.user_data['order_svc'] = svc
    
    link_type = get_link_prompt(svc['service_name'])
    prompt = f"🔗 <b>Enter {link_type} for:</b>\n<i>{html.escape(svc['service_name'])}</i>"
    
    if svc.get('use_type') == 'Telegram username':
        prompt += "\n\n(Example: @username or https://t.me/...)"
    
    kb = [[InlineKeyboardButton("🚫 Cancel", callback_data="no")]]
    
    await update.message.reply_text(
        f"{format_for_user(svc, db_user.get('language','en'), db_user.get('currency','USD'))}\n\n{prompt}", 
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return config.ORDER_WAITING_LINK

async def new_order_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "/cancel":
        await update.message.reply_text("🚫 Canceled.")
        return ConversationHandler.END

    context.user_data['order_link'] = update.message.text.strip()
    svc = context.user_data['order_svc']
    
    # 🔥 CHECK TYPE: If Custom Comments, ask for comments instead of Quantity
    if svc.get('use_type') == 'Custom Comments':
        kb = [[InlineKeyboardButton("🚫 Cancel", callback_data="no")]]
        await update.message.reply_text(
            "💬 <b>Enter Custom Comments:</b>\n(One comment per line)\n\nExample:\nGood Post!\nNice video\nAmazing", 
            parse_mode='HTML', 
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return config.ORDER_WAITING_COMMENTS

    # Default Flow (Ask Quantity)
    kb = [[InlineKeyboardButton("🚫 Cancel", callback_data="no")]]
    await update.message.reply_text(f"📊 <b>Quantity</b>\nMin: {svc['min']} - Max: {svc['max']}", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(kb))
    return config.ORDER_WAITING_QTY

async def new_order_comments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = update.message.text.strip()
    comments_list = [line.strip() for line in raw_text.split('\n') if line.strip()]
    
    if not comments_list:
        await update.message.reply_text("❌ Empty comments. Please try again.")
        return config.ORDER_WAITING_COMMENTS
        
    qty = len(comments_list)
    svc = context.user_data['order_svc']
    
    if qty < svc['min'] or qty > svc['max']:
        await update.message.reply_text(f"❌ Invalid Quantity ({qty}).\nMin: {svc['min']} - Max: {svc['max']}\nPlease add/remove lines.")
        return config.ORDER_WAITING_COMMENTS

    context.user_data['order_qty'] = qty
    context.user_data['custom_comments'] = comments_list
    
    cost = calculate_cost(qty, svc)
    context.user_data['cost_usd'] = cost
    
    user = get_user(update.effective_user.id)
    cost_display = format_currency(cost, user.get('currency', 'USD'))
    text = get_text(user.get('language','en'), 'confirm_order', cost=cost_display)
    text += f"\n📝 Comments: {qty} lines"
    
    kb = [[InlineKeyboardButton("✅ Yes", callback_data="yes"), InlineKeyboardButton("❌ No", callback_data="no")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
    return config.ORDER_CONFIRM

async def new_order_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: qty = int(update.message.text.strip())
    except: 
        kb = [[InlineKeyboardButton("🚫 Cancel", callback_data="no")]]
        await update.message.reply_text("❌ Numbers only. Try again:", reply_markup=InlineKeyboardMarkup(kb))
        return config.ORDER_WAITING_QTY
        
    svc = context.user_data['order_svc']
    if qty < svc['min'] or qty > svc['max']:
        kb = [[InlineKeyboardButton("🚫 Cancel", callback_data="no")]]
        await update.message.reply_text(f"❌ Invalid Qty. ({svc['min']}-{svc['max']})", reply_markup=InlineKeyboardMarkup(kb))
        return config.ORDER_WAITING_QTY
        
    context.user_data['order_qty'] = qty
    context.user_data.pop('custom_comments', None)
    
    cost = calculate_cost(qty, svc)
    context.user_data['cost_usd'] = cost
    
    user = get_user(update.effective_user.id)
    cost_display = format_currency(cost, user.get('currency', 'USD'))
    text = get_text(user.get('language','en'), 'confirm_order', cost=cost_display)
    
    kb = [[InlineKeyboardButton("✅ Yes", callback_data="yes"), InlineKeyboardButton("❌ No", callback_data="no")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
    return config.ORDER_CONFIRM

async def new_order_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == 'no':
        await query.edit_message_text("🚫 Canceled.")
        return ConversationHandler.END
        
    user = get_user(update.effective_user.id)
    cost = context.user_data['cost_usd']
    svc = context.user_data['order_svc']
    qty = context.user_data['order_qty']
    link = context.user_data['order_link']
    comments = context.user_data.get('custom_comments', None)
    
    if float(user['balance_usd']) < cost:
        await query.edit_message_text(f"⚠️ <b>Insufficient Balance</b>\n\n💵 Cost: ${cost:.4f}\n💰 Your Balance: ${user['balance_usd']:.4f}\n\nPlease top up.", parse_mode='HTML')
        return ConversationHandler.END
        
    try:
        new_bal = float(user['balance_usd']) - cost
        supabase.table('users').update({'balance_usd': new_bal}).eq('telegram_id', update.effective_user.id).execute()
        
        per_qty = int(svc.get('per_quantity', 1000))
        if per_qty < 1: per_qty = 1000
        buy_price = float(svc.get('buy_price', 0))
        buy_charge = (buy_price / per_qty) * qty
        
        o_data = {
            "email": user['email'],
            "service": svc['service_name'],
            "quantity": qty,
            "link": link,
            "day": 1,
            "remain": qty,
            "start_count": 0,
            "buy_charge": round(buy_charge, 6),
            "sell_charge": round(cost, 6),
            "supplier_service_id": svc['service_id'],
            "supplier_name": svc['source'],
            "status": "Pending",
            "UsedType": svc['use_type'],
            "supplier_order_id": 0
        }
        
        if comments:
            o_data['comments'] = comments
        
        inserted = supabase.table('WebsiteOrders').insert(o_data).execute()
        await query.edit_message_text(f"✅ <b>Order Queued!</b>\nID: {inserted.data[0]['id']}", parse_mode='HTML')
        
    except Exception as e:
        await query.edit_message_text(f"❌ <b>Error Occurred:</b>\n{str(e)}", parse_mode='HTML')
    
    await help_command(update, context); return ConversationHandler.END

async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🚫 Canceled.")
    return ConversationHandler.END

# --- MASS ORDER (STRICT FILTER) ---
async def mass_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 <b>Mass Order</b>\nFormat: <code>ID Link Qty</code>\n(Space separated, One per line)", parse_mode='HTML')
    return config.WAITING_MASS_INPUT

async def mass_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = update.message.text.strip().split('\n'); valid = []; total = 0.0
    details_msg = "📝 <b>Order Details:</b>\n\n"
    
    for line in lines:
        try:
            line = line.replace('|', ' ') 
            p = line.split()
            if len(p) != 3: continue
            res = supabase.table('services').select("*").eq('id', p[0]).execute()
            if res.data:
                svc = res.data[0]
                if svc.get('use_type') in ['Custom Comments', 'Poll', 'Comment Likes']:
                    continue
                    
                cost = calculate_cost(int(p[2]), svc); total += cost
                valid.append({'svc': svc, 'link': p[1], 'qty': int(p[2]), 'cost': cost})
                
                details_msg += (
                    f"📦 <b>{html.escape(svc['service_name'])}</b>\n"
                    f"🔗 {html.escape(p[1])}\n"
                    f"🔢 Qty: {p[2]} | 💰 ${cost:.4f}\n"
                    f"--------------------\n"
                )
        except: continue
        
    context.user_data['mass_queue'] = valid; context.user_data['mass_total'] = total
    curr = get_user(update.effective_user.id).get('currency', 'USD')
    
    if not valid:
         await update.message.reply_text("❌ No valid orders found.\nNote: 'Custom Comments' services are not supported in Mass Order.", parse_mode='HTML')
         return config.WAITING_MASS_INPUT

    confirm_msg = (
        f"{details_msg}"
        f"📊 <b>Summary:</b>\n"
        f"✅ Valid Orders: {len(valid)}\n"
        f"💵 Total Cost: {format_currency(total, curr)}\n\n"
        f"❓ <b>Confirm Order?</b>"
    )
    
    await update.message.reply_text(confirm_msg, parse_mode='HTML', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes", callback_data="mass_yes"), InlineKeyboardButton("❌ No", callback_data="mass_no")]]))
    return config.WAITING_MASS_CONFIRM

async def mass_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == 'mass_no':
        await query.edit_message_text("🚫 Canceled.")
        await help_command(update, context)
        return ConversationHandler.END
        
    user = get_user(update.effective_user.id); total = context.user_data['mass_total']
    
    if float(user['balance_usd']) < total:
        await query.edit_message_text(f"⚠️ <b>Insufficient Balance</b>\nNeeded: ${total}\nHas: ${user['balance_usd']}", parse_mode='HTML')
        await help_command(update, context)
        return ConversationHandler.END
        
    try:
        new_bal = float(user['balance_usd']) - total
        supabase.table('users').update({'balance_usd': new_bal}).eq('telegram_id', update.effective_user.id).execute()
        
        for o in context.user_data['mass_queue']:
            svc = o['svc']
            qty = o['qty']
            
            per_qty = int(svc.get('per_quantity', 1000))
            if per_qty < 1: per_qty = 1000
            
            buy_price = float(svc.get('buy_price', 0))
            buy_charge = (buy_price / per_qty) * qty
            
            o_data = {
                "email": user['email'],
                "service": svc['service_name'],
                "quantity": qty,
                "link": o['link'],
                "day": 1,
                "remain": qty,
                "start_count": 0,
                "buy_charge": round(buy_charge, 6),
                "sell_charge": round(o['cost'], 6),
                "supplier_service_id": svc['service_id'],
                "supplier_name": svc['source'],
                "status": "Pending",
                "UsedType": svc['use_type'],
                "supplier_order_id": 0
            }
            
            supabase.table('WebsiteOrders').insert(o_data).execute()
            
        await query.edit_message_text("✅ <b>Mass Order Queued!</b>", parse_mode='HTML')
        
    except Exception as e: 
        await query.edit_message_text(f"❌ Error: {e}")
    
    await help_command(update, context); return ConversationHandler.END

# =========================================
# 💬 SUPPORT
# =========================================
async def sup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("Refill", callback_data="s_Refill"), InlineKeyboardButton("Cancel", callback_data="s_Cancel")], [InlineKeyboardButton("Speed up", callback_data="s_Speed up")]]
    await update.message.reply_text("Select Issue:", reply_markup=InlineKeyboardMarkup(kb))

async def sup_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data['stype'] = query.data.split("_")[1]
    await query.edit_message_text(f"Selected: {context.user_data['stype']}\n\nSend Order IDs (comma separated):")
    return config.WAITING_SUPPORT_ID

async def sup_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = get_user(update.effective_user.id)
        raw_text = update.message.text
        subject = context.user_data.get('stype', 'Support')

        if not raw_text:
            await update.message.reply_text("❌ Invalid Input.")
            return ConversationHandler.END

        input_ids = [x.strip() for x in raw_text.split(',') if x.strip().isdigit()]
        if not input_ids:
            await update.message.reply_text("❌ No valid numbers found.")
            return ConversationHandler.END

        valid_orders = supabase.table('WebsiteOrders').select("id, supplier_order_id").or_(f"id.in.({','.join(input_ids)}),supplier_order_id.in.({','.join(input_ids)})").eq("email", user['email']).execute().data
        
        confirmed_ids = []
        for iid in input_ids:
            is_valid = False
            for o in valid_orders:
                if str(o['id']) == iid or str(o['supplier_order_id']) == iid:
                    is_valid = True
                    break
            if is_valid: confirmed_ids.append(iid)

        invalid_ids = list(set(input_ids) - set(confirmed_ids))
        
        if invalid_ids:
            error_msg = f"❌ <b>Unable to Process:</b>\nOrder {', '.join(invalid_ids)} - Not found or does not belong to your account.\n\nThank you for using our service!"
            await update.message.reply_text(error_msg, parse_mode='HTML')
            return ConversationHandler.END

        if confirmed_ids:
            joined_ids = ", ".join(confirmed_ids)
            custom_msg = f"{joined_ids} {subject}"
            supabase.table('SupportBox').insert({"email": user['email'], "subject": subject, "order_id": joined_ids, "message": custom_msg, "status": "Pending", "UserStatus": "unread"}).execute()
            await update.message.reply_text(f"✅ Ticket Created for {len(confirmed_ids)} orders.")
            
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {str(e)}")
        
    await help_command(update, context); return ConversationHandler.END

# =========================================
# 🛠️ ADMIN COMMANDS
# =========================================

async def admin_answer_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.SUPPORT_GROUP_ID: return
    try:
        if len(context.args) < 2: return await update.message.reply_text("⚠️ Usage: /Answer <ID> <Message>")
        tid = context.args[0]; reply_msg = " ".join(context.args[1:])
        data = supabase.table("SupportBox").update({"reply_text": reply_msg, "status": "Replied", "UserStatus": "unread"}).eq("id", tid).execute()
        if data.data: await update.message.reply_text(f"✅ Replied to Ticket #{tid}")
        else: await update.message.reply_text("❌ Ticket ID not found.")
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

async def admin_ticket_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.SUPPORT_GROUP_ID: return
    try:
        if not context.args: return await update.message.reply_text("⚠️ Usage: /Close <ID>")
        tid = context.args[0]
        supabase.table("SupportBox").update({"status": "Closed"}).eq("id", tid).execute()
        await update.message.reply_text(f"🔒 Ticket #{tid} Closed.")
    except Exception as e: await update.message.reply_text(f"❌ Error: {e}")

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
            notify_group(config.AFFILIATE_GROUP_ID, f"✅ <b>Manual Topup</b>\nUser: <code>{email}</code>\nAdded: ${amt}\nBal: ${old} ➝ ${new}")
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
                notify_group(config.AFFILIATE_GROUP_ID, f"✅ <b>Approved</b>\nUser: <code>{tx[0]['email']}</code>\nBal: ${old} ➝ ${new}")
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

# 🔥 ADMIN BULK ADD
async def admin_add_bulk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.REPORT_GROUP_ID: return
    
    if len(context.args) < 3:
        await update.message.reply_text(
            "⚠️ Usage: `/add <Start> <End> <Type> | <GoodsName>`\n"
            "Ex: `/add 16310 16319 Telegram Premium | Tele_Prem_Goods`", 
            parse_mode='Markdown'
        )
        return

    try:
        start_id = int(context.args[0])
        end_id = int(context.args[1])
        raw_rest = " ".join(context.args[2:])
        if "|" in raw_rest:
            custom_type, goods_name = raw_rest.split("|", 1)
            custom_type = custom_type.strip(); goods_name = goods_name.strip()
        else:
            custom_type = raw_rest.strip(); goods_name = custom_type
            
        await update.message.reply_text(f"🔄 Fetching from SMMGen API...\nType: {custom_type}\nGoods: {goods_name}")
        
        res = requests.post(config.SMM_API_URL, data={'key': config.SMM_API_KEY, 'action': 'services'}).json()
        targets = [s for s in res if start_id <= int(s['service']) <= end_id]
        
        if not targets:
            await update.message.reply_text("❌ No services found.")
            return

        added_count = 0
        for item in targets:
            s_id = str(item['service'])
            exists = supabase.table("services").select("id").eq("service_id", s_id).execute().data
            if exists: continue 
            
            final_name = clean_service_name(item['name']) 
            buy_price = float(item['rate'])
            sell_price = calculate_sell_price(buy_price, final_name)
            api_type = item.get('type', 'Default') 
            
            supabase.table("services").insert({
                "service_id": s_id, 
                "service_name": final_name, 
                "category": item['category'], 
                "type": custom_type, 
                "min": int(item['min']), 
                "max": int(item['max']), 
                "buy_price": buy_price, 
                "sell_price": sell_price, 
                "use_type": api_type, 
                "source": "smmgen", 
                "per_quantity": 1000, 
                "GoodsName": goods_name
            }).execute()
            added_count += 1
            
        await update.message.reply_text(f"✅ **Success!**\nAdded {added_count} services.\nType: `{custom_type}`", parse_mode='Markdown')
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


# 🔥 ADMIN POST (Final Logic: Grouped Type/Goods + Unicode Icons)
async def admin_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.REPORT_GROUP_ID: return
    
    try:
        bot_info = await context.bot.get_me()
        bot_username = bot_info.username
    except Exception as e:
        print(f"❌ Error getting bot info: {e}")
        return

    svcs = supabase.table('services').select("*").neq('type', 'Demo').range(0, 2000).order('id', desc=False).execute().data
    if not svcs:
        await update.message.reply_text("❌ No services found.")
        return

    cats = {}
    for s in svcs: cats.setdefault(s['category'], []).append(s)
    
    await update.message.reply_text(f"📢 Processing {len(svcs)} services...\n⏳ Delay: 3s per message")
    
    for c, items in cats.items():
        chunks = []
        current_chunk = []
        current_len = 0
        limit = 3800
        
        first = items[0]
        sType = first.get('type', '')
        sGoods = first.get('GoodsName', '')
        
        sub_header = ""
        if sType and sType != 'Default':
            sub_header += f"Type = {html.escape(sType)}"
        
        if sGoods:
            if sub_header: sub_header += f" | {html.escape(sGoods)}"
            else: sub_header += f"Goods = {html.escape(sGoods)}"
            
        header = f"📂 <b>{html.escape(c)}</b>\n"
        if sub_header:
            header += f"{sub_header}\n"
        header += "➖➖➖➖➖➖➖➖➖➖\n\n"
        
        footer = "➖➖➖➖➖➖➖➖➖➖\n👇 Click blue text to Order"
        
        for s in items:
            raw_name = s['service_name']
            clean_name = raw_name.replace('\xa0', ' ').replace('\u200b', '')
            normalized_name = unicodedata.normalize('NFKD', clean_name).encode('ascii', 'ignore').decode('utf-8').lower()
            
            if "no refill" in normalized_name: 
                icon = "🚫"
            elif any(x in normalized_name for x in ["refill", "lifetime", "guaranteed", "auto"]): 
                icon = "♻️"
            else: 
                icon = "⚡"
            
            line = f"{icon} <a href='https://t.me/{bot_username}?start=order_{s['id']}'>ID:{s['id']} - {html.escape(s['service_name'])}</a>\n\n"
            
            if current_len + len(line) > limit:
                chunks.append(current_chunk)
                current_chunk = []
                current_len = 0
            
            current_chunk.append(s)
            current_len += len(line)
            
        if current_chunk: chunks.append(current_chunk)
        
        for batch in chunks:
            msg_text = header
            for s in batch:
                raw_name = s['service_name']
                clean_name = raw_name.replace('\xa0', ' ').replace('\u200b', '')
                normalized_name = unicodedata.normalize('NFKD', clean_name).encode('ascii', 'ignore').decode('utf-8').lower()
                
                if "no refill" in normalized_name: icon = "🚫"
                elif any(x in normalized_name for x in ["refill", "lifetime", "guaranteed", "auto"]): icon = "♻️"
                else: icon = "⚡"
                
                msg_text += f"{icon} <a href='https://t.me/{bot_username}?start=order_{s['id']}'>ID:{s['id']} - {html.escape(s['service_name'])}</a>\n\n"
            
            msg_text += footer
            
            first_svc_batch = batch[0]
            msg_id = first_svc_batch.get('channel_msg_id')
            
            try:
                sent_msg = None
                if msg_id and msg_id != 0:
                    try:
                        await context.bot.edit_message_text(chat_id=config.CHANNEL_ID, message_id=msg_id, text=msg_text, parse_mode='HTML', disable_web_page_preview=True)
                        print(f"✅ Edited Msg ID {msg_id}...")
                    except:
                        sent_msg = await context.bot.send_message(chat_id=config.CHANNEL_ID, text=msg_text, parse_mode='HTML', disable_web_page_preview=True)
                else:
                    sent_msg = await context.bot.send_message(chat_id=config.CHANNEL_ID, text=msg_text, parse_mode='HTML', disable_web_page_preview=True)
                    print(f"✅ Sent New Msg...")

                if sent_msg:
                    for s in batch:
                        supabase.table('services').update({'channel_msg_id': sent_msg.message_id}).eq('id', s['id']).execute()
            
            except Exception as e:
                print(f"❌ CRITICAL POST ERROR: {e}")
            
            time.sleep(3) 
                
    await update.message.reply_text("✅ All Done.")
