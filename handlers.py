# ... (Imports) ...

# 1. /Topup (Manual) -> Send to Affiliate Group
async def admin_manual_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.AFFILIATE_GROUP_ID: return # Restrict to Affiliate Group
    try:
        # ... (Same logic) ...
        # Notify
        msg = f"✅ **Manual Topup**\nUser: `{email}`\nAdded: `${amount}`"
        requests.post(f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage", 
                      json={"chat_id": config.AFFILIATE_GROUP_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

# 2. /Yes (Approve) -> Send to Affiliate Group
async def admin_tx_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != config.AFFILIATE_GROUP_ID: return
    try:
        # ... (Same logic) ...
        msg = f"✅ **Transaction Approved**\nUser: `{tx[0]['email']}`"
        requests.post(f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage", 
                      json={"chat_id": config.AFFILIATE_GROUP_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

# 3. /post -> Send to Channel
# (Already using config.CHANNEL_ID correctly in previous code)

# 4. /Change /swap -> Restrict to Supplier or Report Group if needed
# (Assuming Admin can do this from any admin group, usually Supplier Group)
