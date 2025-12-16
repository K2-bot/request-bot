import time
import requests
import config
import json
import html
import re
import traceback
from db import supabase
from datetime import datetime
from zoneinfo import ZoneInfo

# 🔥 SAFE LOGGING (HTML)
def send_log_retry(chat_id, text):
    if not chat_id or str(chat_id) == "0": return
    for attempt in range(3):
        try:
            url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200: return
        except: pass
        time.sleep(2)

# 🧹 HELPER: Name Cleaning
def clean_service_name(raw_name):
    name = re.sub(r"\s*~\s*Max\s*[\d\.]+[KkMmBb]?\s*", "", raw_name, flags=re.IGNORECASE)
    name = re.sub(r"\s*~\s*[\d\.]+[KkMm]?/days?\s*", "", name, flags=re.IGNORECASE)
    return name.strip()

# 💰 HELPER: Price Calculation
def calculate_sell_price(buy_price, service_name):
    if 'view' in service_name.lower():
        return round(buy_price * 3.0, 4)
    return round(buy_price * 1.4, 4)

# 🛠️ HELPER: Logic Helpers
def find_service_for_order(order):
    try:
        svc_name = order.get("service")
        if svc_name:
            r = supabase.table("services").select("*").eq("service_name", svc_name).execute()
            if r.data: return r.data[0]
            rows = supabase.table("services").select("*").ilike("service_name", f"%{svc_name}%").limit(1).execute()
            if rows.data: return rows.data[0]
    except: pass
    return None

def update_user_balance(email, amount):
    try:
        user = supabase.table("users").select("balance_usd").eq("email", email).execute().data
        if user:
            new_bal = float(user[0]['balance_usd']) + amount
            supabase.table("users").update({"balance_usd": new_bal}).eq("email", email).execute()
    except: pass

def adjust_service_qty_on_status_change(order, old_status, new_status):
    try:
        old = (old_status or "").lower()
        new = (new_status or "").lower()
        qty = int(order.get("quantity") or 0)
        remain = int(order.get("remain") or 0) if order.get("remain") is not None else 0
        sell_price = float(order.get("sell_charge") or order.get("price") or 0)
        email = order.get("email")
        service_name = order.get("service")

        svc = find_service_for_order(order)
        if not svc: return
        svc_id = svc.get("id")

        def notify_supplier(title, refund_amount=0, spend_amount=0, done_qty=0):
            msg = (
                f"📦 <b>{title}</b>\n"
                f"🧾 Order ID: {order.get('id')}\n"
                f"🧩 Service: {html.escape(service_name)}\n"
                f"👤 User: {email}\n"
                f"📊 Quantity: {qty}\n"
                f"⏳ Remain: {remain}\n"
                f"✅ Done Qty: {done_qty}\n"
                f"💰 Amount: ${sell_price:.4f}\n"
                f"💸 Refund: ${refund_amount:.4f}\n"
                f"📈 Spend Added: ${spend_amount:.4f}\n"
                f"🔄 New Status: {new.capitalize()}\n"
                f"🕒 Time: {datetime.now(ZoneInfo('Asia/Yangon')).strftime('%Y-%m-%d %H:%M:%S')}"
            )
            send_log_retry(config.SUPPLIER_GROUP_ID, msg)

        def handle_referral_and_bonus(amount, add=True):
            user_data = supabase.table("users").select("ref_owner_id", "total_spend").eq("email", email).execute().data
            if not user_data: return
            user_info = user_data[0]
            ref_owner = user_info.get("ref_owner_id")
            
            # Referral 4%
            if ref_owner:
                delta = amount * 0.04
                if not add: delta = -delta
                current_withdraw = supabase.table("users").select("withdrawable_balance").eq("id", ref_owner).execute().data[0].get("withdrawable_balance") or 0
                supabase.table("users").update({"withdrawable_balance": current_withdraw + delta}).eq("id", ref_owner).execute()
                send_log_retry(config.AFFILIATE_GROUP_ID, f"💰 Referral Owner reward {'added' if add else 'deducted'}: ${delta:.4f} for ref_owner_id {ref_owner}")
            
            # Bonus 1% if spend > 10
            total_spend = float(user_info.get("total_spend") or 0)
            if total_spend > 10:
                bonus = amount * 0.01
                if not add: bonus = -bonus
                update_user_balance(email, bonus)
                send_log_retry(config.AFFILIATE_GROUP_ID, f"🎁 User bonus {'added' if add else 'deducted'}: ${bonus:.4f} for {email}")

        # LOGIC
        if new == "completed" and old != "completed":
            cur_qty = int(svc.get("total_sold_qty") or 0)
            supabase.table("services").update({"total_sold_qty": cur_qty + qty}).eq("id", svc_id).execute()
            if email and sell_price:
                user = supabase.table("users").select("total_spend").eq("email", email).execute().data
                if user:
                    total_spend = float(user[0].get("total_spend") or 0) + sell_price
                    supabase.table("users").update({"total_spend": total_spend}).eq("email", email).execute()
            handle_referral_and_bonus(sell_price, add=True)
            notify_supplier("✅ Completed Order", refund_amount=0, spend_amount=sell_price, done_qty=qty)

        elif old == "completed" and new in ("partial", "canceled", "cancelled"):
            cur_qty = int(svc.get("total_sold_qty") or 0)
            supabase.table("services").update({"total_sold_qty": max(0, cur_qty - qty)}).eq("id", svc_id).execute()
            if email and qty and sell_price:
                refund_amount = (remain / qty) * sell_price if remain else sell_price
                user = supabase.table("users").select("total_spend").eq("email", email).execute().data
                if user:
                    total_spend = float(user[0].get("total_spend") or 0) - refund_amount
                    supabase.table("users").update({"total_spend": max(0, total_spend)}).eq("email", email).execute()
                update_user_balance(email, refund_amount)
                supabase.table("WebsiteOrders").update({"refund_amount": refund_amount, "status": "Refunded"}).eq("id", order.get("id")).execute()
                handle_referral_and_bonus(refund_amount, add=False)
                notify_supplier("♻️ Completed → Refunded", refund_amount=refund_amount, done_qty=0)
                send_log_retry(config.AFFILIATE_GROUP_ID, f"🔁 Refunded ${refund_amount:.4f} to {email} for order {order.get('id')} (remain {remain})")

        elif new in ("partial", "canceled", "cancelled") and old not in ("completed", "partial", "canceled", "cancelled"):
            done_qty = max(0, qty - remain)
            cur_qty = int(svc.get("total_sold_qty") or 0)
            supabase.table("services").update({"total_sold_qty": cur_qty + done_qty}).eq("id", svc_id).execute()
            if qty > 0 and sell_price > 0:
                refund_amount = (sell_price / qty) * remain
                spend_amount = sell_price - refund_amount
                user = supabase.table("users").select("total_spend").eq("email", email).execute().data
                if user:
                    total_spend = float(user[0].get("total_spend") or 0) + spend_amount
                    supabase.table("users").update({"total_spend": total_spend}).eq("email", email).execute()
                update_user_balance(email, refund_amount)
                supabase.table("WebsiteOrders").update({"refund_amount": refund_amount, "status": "Refunded"}).eq("id", order.get("id")).execute()
                notify_supplier("💸 Partial/Canceled Order", refund_amount=refund_amount, spend_amount=spend_amount, done_qty=done_qty)
                send_log_retry(config.AFFILIATE_GROUP_ID, f"💸 {email} refunded ${refund_amount:.4f} for {service_name} (remain {remain})")
    
    except Exception as e:
        print("adjust_service_qty_on_status_change error:", e)
        traceback.print_exc()

# 1. ORDER PROCESSOR
def process_pending_orders_loop():
    while True:
        try:
            orders = supabase.table("WebsiteOrders").select("*").eq("status", "Pending").execute().data or []
            for o in orders:
                try:
                    sup_oid = str(o.get("supplier_order_id") or "")
                    if sup_oid and sup_oid != "0": continue
                    supplier = (o.get("supplier_name") or "").lower().strip()
                    try:
                        sell_usd = float(o.get('sell_charge', 0))
                        mmk_price = sell_usd * config.USD_TO_MMK
                    except: sell_usd = 0.0; mmk_price = 0.0

                    if supplier == "smmgen":
                        payload = {'key': config.SMM_API_KEY, 'action': 'add', 'service': o['supplier_service_id'], 'link': o['link'], 'quantity': o['quantity']}
                        if o.get('comments'): payload['comments'] = "\n".join(o['comments'])
                        res = requests.post(config.SMM_API_URL, data=payload, timeout=30).json()
                        if 'order' in res:
                            sup_id = str(res['order'])
                            supabase.table("WebsiteOrders").update({"status": "Processing", "supplier_order_id": sup_id}).eq("id", o["id"]).execute()
                            msg = f"🚀 <b>New Order Sent to SMMGEN</b>\n\n🆔 <b>{o['id']}</b>\n📦 Service: {html.escape(o.get('service',''))}\n🔢 Quantity: {o['quantity']}\n🔗 Link: {html.escape(o.get('link',''))}\n💰 Sell Charge (USD): {sell_usd}\n💵 Sell Charge (MMK): {mmk_price:,.0f}\n📧 Email: {o['email']}\n🧾 Supplier Order ID: {sup_id}\n✅ Status: Processing"
                            send_log_retry(config.SUPPLIER_GROUP_ID, msg)
                        elif 'error' in res:
                            update_user_balance(o['email'], sell_usd)
                            supabase.table("WebsiteOrders").update({"status": "Canceled"}).eq("id", o["id"]).execute()
                            send_log_retry(config.K2BOOST_GROUP_ID, f"❌ <b>Order {o['id']} Failed & Refunded</b>\nReason: {res['error']}")

                    elif supplier == "k2boost":
                        supabase.table("WebsiteOrders").update({"status": "Processing"}).eq("id", o["id"]).execute()
                        msg = f"⚡️ <b>New Order to K2BOOST</b>\n\n🆔 <b>{o['id']}</b>\n📧 Email: {o['email']}\n📦 Service: {html.escape(o.get('service',''))}\n🔢 Quantity: {o['quantity']}\n🔗 Link: {html.escape(o.get('link',''))}\n📆 Day: {o.get('day', 1)}\n⏳ Remain: {o.get('quantity')}\n💰 Sell Charge (USD): {sell_usd}\n💵 Sell Charge (MMK): {mmk_price:,.0f}\n🏷 Supplier: k2boost\n🕒 Created: {o.get('created_at', 'Now')}\n💬 Used Type: {html.escape(str(o.get('UsedType', 'Default')))}"
                        send_log_retry(config.K2BOOST_GROUP_ID, msg)
                except Exception as inner_e: print(f"⚠️ Error on Order {o.get('id')}: {inner_e}")
        except Exception as e: print(f"🔥 Critical Order Loop Error: {e}")
        time.sleep(5)

# 2. STATUS CHECKER (Uses New Logic)
def smmgen_status_batch_loop():
    while True:
        try:
            all_smm = supabase.table("WebsiteOrders").select("*").eq("supplier_name","smmgen").not_.in_("status", ["Completed", "Canceled", "Refunded", "Partial", "cancelled"]).not_.is_("supplier_order_id", None).execute().data or []
            s_ids = [str(o['supplier_order_id']) for o in all_smm if str(o['supplier_order_id']).isdigit()]
            if not s_ids: time.sleep(60); continue
            
            for i in range(0, len(s_ids), 100):
                batch = ",".join(s_ids[i:i + 100])
                try:
                    res = requests.post(config.SMM_API_URL, data={"key": config.SMM_API_KEY, "action": "status", "orders": batch}, timeout=30).json()
                    for sup_id, info in res.items():
                        if isinstance(info, dict) and "status" in info:
                            new_s = info["status"]
                            local_order = next((x for x in all_smm if str(x['supplier_order_id']) == str(sup_id)), None)
                            
                            if local_order and local_order['status'].lower() != new_s.lower():
                                remains = int(info.get('remains', 0))
                                # Update remain first so logic can use it
                                supabase.table("WebsiteOrders").update({"remain": remains}).eq("supplier_order_id", sup_id).execute()
                                
                                # 🔥 CALL THE LOGIC FUNCTION
                                local_order['remain'] = remains # Update local obj for function
                                adjust_service_qty_on_status_change(local_order, local_order['status'], new_s)
                                
                                # Final Status Update in DB
                                supabase.table("WebsiteOrders").update({"status": new_s}).eq("supplier_order_id", sup_id).execute()
                except: pass
                time.sleep(2)
        except: pass
        time.sleep(60)

# 3. TRANSACTION POLLER
def poll_transactions():
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
                        if abs(float(v["amount_usd"]) - float(tx["amount"])) < 0.01: match = v; break
                mmk_amt = float(tx["amount"]) * config.USD_TO_MMK
                if match:
                    update_user_balance(tx['email'], float(tx["amount"]))
                    supabase.table("VerifyPayment").update({"status": "used"}).eq("transaction_id", tx['transaction_id']).execute()
                    supabase.table("transactions").update({"status": "Accepted"}).eq("id", tx_id).execute()
                    msg = f"✅ <b>Auto Top-up Completed</b>\n\n👤 User: {tx['email']}\n💳 Method: {tx['method']}\n💰 Amount USD: {tx['amount']}\n🇲🇲 Amount MMK: {mmk_amt:,.0f}\n🧾 Transaction ID: {tx['transaction_id']}"
                    send_log_retry(config.AFFILIATE_GROUP_ID, msg)
                else:
                    supabase.table("transactions").update({"status": "Processing"}).eq("id", tx_id).execute()
                    msg = f"🆕 <b>New Unverified Transaction</b>\n\n🆔 ID: {tx_id}\n📧 Email: {tx['email']}\n💳 Method: {tx['method']}\n💵 Amount USD: {tx['amount']}\n🇲🇲 Amount MMK: {mmk_amt:,.0f}\n🧾 Transaction ID: {tx.get('transaction_id', 'N/A')}\n\n🛠 <b>Admin Commands:</b>\n/Yes {tx_id}\n/No {tx_id}"
                    send_log_retry(config.AFFILIATE_GROUP_ID, msg)
                processed_tx.add(tx_id)
        except: pass
        time.sleep(10)

# 4. AFFILIATE POLLER
def poll_affiliate():
    processed_aff = set()
    while True:
        try:
            reqs = supabase.table("affiliate").select("*").eq("status", "Pending").execute().data or []
            for req in reqs:
                rid = req['id']
                if rid in processed_aff: continue
                supabase.table("affiliate").update({"status": "Processing"}).eq("id", rid).execute()
                mmk_amt = float(req['amount']) * config.USD_TO_MMK
                if str(req.get('method')).lower() == 'topup':
                    msg = f"💰 <b>Affiliate Topup</b>\n\n🆔 ID = {rid}\n📧 Email = {req['email']}\n💳 Method = TopUp\n💵 Amount USD = {req['amount']}\n🇲🇲 Amount MMK = {mmk_amt:,.0f}"
                else:
                    msg = f"🆕 <b>New Affiliate Request</b>\n\n🆔 ID = {rid}\n📧 Email = {req['email']}\n💰 Amount = {req['amount']}\n💳 Method = {req['method']}\n📱 Phone ID = {req.get('phone_id','-')}\n👤 Name = {req.get('name','-')}\n\n🇲🇲 Amount MMK = {mmk_amt:,.0f}\n🛠 <b>Admin Actions:</b>\n/Accept {rid}\n/Failed {rid}"
                send_log_retry(config.AFFILIATE_GROUP_ID, msg)
                processed_aff.add(rid)
        except: pass
        time.sleep(10)

# 5. SUPPORT POLLER
def poll_supportbox_worker():
    while True:
        try:
            tickets = supabase.table("SupportBox").select("*").eq("status", "Pending").execute().data or []
            for t in tickets:
                lid = str(t.get("order_id", ""))
                subject = str(t.get("subject", "No Subject"))
                email = str(t.get("email", "No Email"))
                msg_content = str(t.get("message", "-"))
                msg = f"📢 <b>New Support Ticket</b>\nID - {t['id']}\nEmail - {email}\nSubject - {html.escape(subject)}\nOrder ID - {lid}\n\nMessage:\n{html.escape(msg_content)}\n\nCommands:\n/Answer {t['id']} reply message\n/Close {t['id']}"
                send_log_retry(config.SUPPORT_GROUP_ID, msg)
                supabase.table("SupportBox").update({"status": "Processing"}).eq("id", t['id']).execute()
        except: pass
        time.sleep(10)

# 7. RATE CHECKER
def check_smmgen_rates_loop():
    print("📈 Rate Checker Worker Started...")
    while True:
        try:
            payload = {'key': config.SMM_API_KEY, 'action': 'services'}
            res = requests.post(config.SMM_API_URL, data=payload, timeout=30).json()
            local = supabase.table("services").select("id, service_id, buy_price, service_name").execute().data or []
            for ls in local:
                api_svc = next((s for s in res if str(s['service']) == str(ls['service_id'])), None)
                if api_svc:
                    api_rate = float(api_svc['rate'])
                    old_rate = float(ls['buy_price'])
                    if abs(old_rate - api_rate) > 0.0001:
                        new_sell = calculate_sell_price(api_rate, ls['service_name'])
                        supabase.table("services").update({"buy_price": api_rate, "sell_price": new_sell}).eq("id", ls['id']).execute()
                        msg = f"📉📈 <b>Price Updated</b>\n🆔 {ls['service_id']}\n📦 {ls['service_name']}\n💵 Buy: {old_rate} ➝ {api_rate}\n💰 Sell Updated: {new_sell}"
                        send_log_retry(config.REPORT_GROUP_ID, msg)
        except Exception as e: print(f"❌ Rate Check Error: {e}")
        time.sleep(3600)
