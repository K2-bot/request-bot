import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
import config
from db import supabase, get_user
from utils import get_text, format_currency, calculate_cost, format_for_user

def notify_group(chat_id, text):
    try: requests.post(f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except: pass

# --- AUTH & ORDERS (Standard) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; db_user = get_user(user.id); args = context.args
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

# ... (Include Login, NewOrder, MassOrder, Support from previous response) ...
# (Login/Order Handlers are generic and don't change based on groups)

# =========================================
# 🛠️ ADMIN COMMANDS (Using Correct Groups)
# =========================================

# 1. /balance -> Admin Only
async def admin_check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in [config.AFFILIATE_GROUP_ID, config.SUPPLIER_GROUP_ID]: return
    try:
        email = context.args[0]
        user = supabase.table("users").select("balance").eq("email", email).execute().data
        if user: await update.message.reply_text(f"💰 Balance: ${user[0]['balance']}")
        else: await update.message.reply_text("❌ Not found.")
    except: await update.message.reply_text("Usage: /balance email")

# 2. /Topup -> Affiliate Group
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

# 3. /Yes -> Affiliate Group
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

# 4. /No -> Affiliate Group
async def admin_tx_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.AFFILIATE_GROUP_ID: return
    try:
        tx_id = int(context.args[0])
        supabase.table("transactions").update({"status": "Rejected"}).eq("id", tx_id).execute()
        await update.message.reply_text("❌ Rejected.")
    except: pass

# 5. /Accept -> Affiliate Group
async def admin_aff_accept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.AFFILIATE_GROUP_ID: return
    try:
        rid = int(context.args[0])
        supabase.table("affiliate").update({"status": "Accepted"}).eq("id", rid).execute()
        await update.message.reply_text("✅ Accepted.")
    except: pass

# 6. /post -> Channel
async def admin_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.ADMIN_GROUP_ID: return
    # ... (Same post logic) ...
    await update.message.reply_text("Posting...")
    # ...

# 7. /ban -> Any Admin Group
async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in [config.SUPPLIER_GROUP_ID, config.AFFILIATE_GROUP_ID]: return
    if context.args:
        supabase.table('users').update({'is_banned': True}).eq('email', context.args[0]).execute()
        await update.message.reply_text(f"🚫 Banned {context.args[0]}")

# 8. /Change -> Supplier Group (Range Change)
async def admin_change_attr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.SUPPLIER_GROUP_ID: return
    # ... (Insert the Bulk Change Logic here from previous response) ...
