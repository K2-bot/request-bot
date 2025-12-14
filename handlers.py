import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
import config
from db import supabase, get_user
from utils import get_text, format_currency, calculate_cost, format_for_user

def notify_group(chat_id, text):
    try: requests.post(f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except: pass

# ... (Auth, Login, Order, MassOrder Handlers - Same as before) ...
# (Copy login_start, new_order_start, etc. from previous response)
# ...

# =========================================
# 🛠️ ADMIN COMMANDS (GROUP RESTRICTED)
# =========================================

# A. AFFILIATE GROUP
async def admin_check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.AFFILIATE_GROUP_ID: return
    try:
        u = supabase.table("users").select("balance").eq("email", context.args[0]).execute().data
        await update.message.reply_text(f"💰 Balance: ${u[0]['balance']}" if u else "❌ Not found")
    except: pass

async def admin_manual_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.AFFILIATE_GROUP_ID: return
    try:
        email = context.args[0]; amt = float(context.args[1])
        u = supabase.table("users").select("balance").eq("email", email).execute().data
        if u:
            old = float(u[0]['balance']); new = old + amt
            supabase.table("users").update({"balance": new}).eq("email", email).execute()
            notify_group(config.AFFILIATE_GROUP_ID, f"✅ **Manual Topup**\nUser: `{email}`\nAdded: `${amt}`\nBal: `${old}` ➝ `${new}`")
            await update.message.reply_text("Done.")
    except: pass

async def admin_tx_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.AFFILIATE_GROUP_ID: return
    try:
        tx_id = int(context.args[0]); tx = supabase.table("transactions").select("*").eq("id", tx_id).execute().data
        if tx and tx[0]['status'] != 'Accepted':
            u = supabase.table("users").select("balance").eq("email", tx[0]['email']).execute().data
            if u:
                old = float(u[0]['balance']); new = old + float(tx[0]['amount'])
                supabase.table("users").update({"balance": new}).eq("email", tx[0]['email']).execute()
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
    try: supabase.table("affiliate").update({"status": "Accepted"}).eq("id", int(context.args[0])).execute(); await update.message.reply_text("Accepted.")
    except: pass

# B. K2BOOST GROUP
async def admin_order_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.K2BOOST_GROUP_ID: return
    try:
        oid = context.args[0] if context.args else None
        if not oid and update.message.reply_to_message:
            txt = update.message.reply_to_message.text
            for w in txt.split():
                if w.isdigit(): oid = w; break
        if oid:
            supabase.table("WebsiteOrders").update({"status": "Completed"}).eq("id", int(oid)).execute()
            await update.message.reply_text(f"✅ Order {oid} marked as Completed.")
    except: pass

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
                user = supabase.table("users").select("balance").eq("email", o['email']).execute().data
                if user:
                    new_bal = float(user[0]['balance']) + float(o['buy_charge'])
                    supabase.table("users").update({"balance": new_bal}).eq("email", o['email']).execute()
                    supabase.table("WebsiteOrders").update({"status": "Canceled"}).eq("id", int(oid)).execute()
                    await update.message.reply_text(f"❌ Order {oid} Canceled & Refunded.")
            else: await update.message.reply_text("Already Canceled.")
    except: pass

# C. REPORT GROUP
async def admin_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.REPORT_GROUP_ID: return
    svcs = supabase.table('services').select("*").order('id', desc=False).execute().data
    cats = {}
    for s in svcs: cats.setdefault(s['category'], []).append(s)
    await update.message.reply_text(f"Posting {len(cats)} categories...")
    for c, items in cats.items():
        msg = f"📂 <b>{c}</b>\n➖➖➖➖➖\n\n"
        for s in items: msg += f"⚡ <a href='https://t.me/{(await context.bot.get_me()).username}?start=order_{s['id']}'>ID:{s['id']} - {s['service_name']}</a>\n\n"
        try: await context.bot.send_message(config.CHANNEL_ID, text=msg, parse_mode='HTML', disable_web_page_preview=True); time.sleep(3)
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
        elif update.message.reply_to_message:
            txt = update.message.reply_to_message.text
            tid = next((s for s in txt.split() if s.isdigit()), None)
            if tid:
                supabase.table("services").update({args[0].lower(): " ".join(args[1:])}).eq("id", tid).execute()
                await update.message.reply_text("✅ Updated.")
    except: pass

# D. SUPPORT GROUP
async def admin_reply_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.SUPPORT_GROUP_ID: return
    try:
        tid = context.args[0]; reply_msg = " ".join(context.args[1:])
        data = supabase.table("SupportBox").update({"reply_text": reply_msg, "status": "Replied", "UserStatus": "unread"}).eq("id", tid).execute()
        if data.data: await update.message.reply_text(f"✅ Reply Sent to #{tid}")
        else: await update.message.reply_text("❌ ID not found.")
    except: pass
