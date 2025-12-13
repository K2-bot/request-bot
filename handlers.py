import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
import config
from db import supabase, get_user
from utils import get_text, format_currency, calculate_cost, format_for_user

def notify_admin_group(text):
    try: requests.post(f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage", json={"chat_id": config.ADMIN_GROUP_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except: pass

# --- AUTH & DASHBOARD ---
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
    try: await update.
