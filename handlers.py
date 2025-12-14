import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
import config
from db import supabase, get_user
from utils import get_text, format_currency, calculate_cost, format_for_user

def notify_group(chat_id, text):
    try: requests.post(f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except: pass

# ... (Auth & Login Handlers - Same as before) ...
# (Start, Login, etc. Copy from previous response)

# --- HELPERS (Update Balance Display) ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id; db_user = get_user(user_id)
    if not db_user: return await start(update, context)
    # 🔥 FIXED: balance_usd
    bal = format_currency(float(db_user.get('balance_usd', 0)), db_user.get('currency', 'USD'))
    msg = f"{get_text(db_user.get('language', 'en'), 'help_title')}\n📧 {db_user.get('email')}\n💰 {bal}\n\n{get_text(db_user.get('language', 'en'), 'help_msg')}"
    if update.callback_query: await update.callback_query.message.reply_text(msg, parse_mode='Markdown')
    else: await update.message.reply_text(msg, parse_mode='Markdown')

# ... (Check, History, Services, Settings Handlers - Same as before) ...

# --- ORDERS (Update Balance Deduction) ---
# (new_order_start, link, qty - Same)

async def new_order_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == 'no': await query.edit_message_text("🚫 Canceled."); return ConversationHandler.END
    user = get_user(update.effective_user.id); cost = context.user_data['cost_usd']
    # 🔥 FIXED: balance_usd
    if float(user['balance_usd']) < cost: await query.edit_message_text("⚠️ Insufficient Balance."); return ConversationHandler.END
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

# --- MASS ORDER (Update Balance Deduction) ---
# (mass_start, mass_process - Same)

async def mass_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == 'mass_no': await query.edit_message_text("🚫 Canceled."); return ConversationHandler.END
    user = get_user(update.effective_user.id); total = context.user_data['mass_total']
    # 🔥 FIXED: balance_usd
    if float(user['balance_usd']) < total: await query.edit_message_text("⚠️ Insufficient Balance."); return ConversationHandler.END
    try:
        new_bal = float(user['balance_usd']) - total
        supabase.table('users').update({'balance_usd': new_bal}).eq('telegram_id', user.id).execute()
        for o in context.user_data['mass_queue']:
            supabase.table('WebsiteOrders').insert({"email": user['email'], "service": o['svc']['service_id'], "link": o['link'], "quantity": o['qty'], "buy_charge": o['cost'], "status": "Pending", "UsedType": "MassOrder", "supplier_service_id": o['svc']['service_id'], "supplier_name": "smmgen"}).execute()
        await query.edit_message_text("✅ Mass Order Queued!")
    except: await query.edit_message_text("❌ Error.")
    await help_command(update, context); return ConversationHandler.END

# --- ADMIN (Update Balance Checks) ---
async def admin_check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.AFFILIATE_GROUP_ID: return
    try:
        # 🔥 FIXED: balance_usd
        u = supabase.table("users").select("balance_usd").eq("email", context.args[0]).execute().data
        await update.message.reply_text(f"💰 Balance: ${u[0]['balance_usd']}" if u else "❌ Not found")
    except: pass

async def admin_manual_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.AFFILIATE_GROUP_ID: return
    try:
        email = context.args[0]; amt = float(context.args[1])
        u = supabase.table("users").select("balance_usd").eq("email", email).execute().data
        if u:
            # 🔥 FIXED: balance_usd
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
            # 🔥 FIXED: balance_usd
            u = supabase.table("users").select("balance_usd").eq("email", tx[0]['email']).execute().data
            if u:
                old = float(u[0]['balance_usd']); new = old + float(tx[0]['amount'])
                supabase.table("users").update({"balance_usd": new}).eq("email", tx[0]['email']).execute()
                supabase.table("transactions").update({"status": "Accepted"}).eq("id", tx_id).execute()
                notify_group(config.AFFILIATE_GROUP_ID, f"✅ **Approved**\nUser: `{tx[0]['email']}`\nBal: `${old}` ➝ `${new}`")
                await update.message.reply_text("Approved.")
    except: pass

# ... (Other Admin Commands Same) ...

async def admin_order_error(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.K2BOOST_GROUP_ID: return
    try:
        oid = context.args[0] if context.args else None
        if not oid and update.message.reply_to_message:
            txt = update.message.reply_to_message.text
            for w in txt.split():
                if w.isdigit(): oid = w; break
        if oid:
            order = supabase.table("WebsiteOrders").select("*").eq("id", int(oid)).execute().data
            if order and order[0]['status'] != 'Canceled':
                o = order[0]
                # 🔥 FIXED: balance_usd
                user = supabase.table("users").select("balance_usd").eq("email", o['email']).execute().data
                if user:
                    new_bal = float(user[0]['balance_usd']) + float(o['buy_charge'])
                    supabase.table("users").update({"balance_usd": new_bal}).eq("email", o['email']).execute()
                    supabase.table("WebsiteOrders").update({"status": "Canceled"}).eq("id", int(oid)).execute()
                    await update.message.reply_text(f"❌ Order {oid} Canceled & Refunded.")
            else: await update.message.reply_text("Already Canceled.")
    except: pass
