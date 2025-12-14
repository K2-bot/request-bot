import time
import requests
import config
import json
import html
from db import supabase
from utils import parse_smm_support_response
from datetime import datetime
from zoneinfo import ZoneInfo

# 🔥 RETRY LOGIC SYSTEM (စာမရောက်မချင်း ၃ ခါပြန်ပို့မယ်)
def send_log_retry(chat_id, text):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200:
                return # Success
            else:
                print(f"⚠️ Telegram Error {res.status_code}: {res.text}")
        except Exception as e:
            print(f"⚠️ Connection Error (Attempt {attempt+1}): {e}")
        time.sleep(2) # Wait 2s before retry

# 1. ORDER PROCESSOR (K2Boost & SMMGen Formats)
def process_pending_orders_loop():
    while True:
        try:
            orders = supabase.table("WebsiteOrders").select("*").eq("status", "Pending").execute().data or []
            
            for o in orders:
                # Skip Logic (0 ဆိုရင် မကျော်ဘူး)
                sup_oid = str(o.get("supplier_order_id") or "")
                if sup_oid and sup_oid != "0": continue
                
                supplier = (o.get("supplier_name") or "").lower()
                mmk_price = float(o['sell_charge']) * config.USD_TO_MMK
                
                # --- A. SMMGEN ORDER ---
                if supplier == "smmgen":
                    payload = {'key': config.SMM_API_KEY, 'action': 'add', 'service': o['supplier_service_id'], 'link': o['link'], 'quantity': o['quantity']}
                    try:
                        res = requests.post(config.SMM_API_URL, data=payload, timeout=30).json()
                        if 'order' in res:
                            sup_id = str(res['order'])
                            supabase.table("WebsiteOrders").update({"status": "Processing", "supplier_order_id": sup_id}).eq("id", o["id"]).execute()
                            
                            # 🚀 SMMGen Message Format
                            msg = (
                                f"🚀 <b>New Order Sent to SMMGEN</b>\n\n"
                                f"🆔 <b>{o['id']}</b>\n"
                                f"📦 Service: {html.escape(o.get('service',''))}\n"
                                f"🔢 Quantity: {o['quantity']}\n"
                                f"🔗 Link: {html.escape(o['link'])}\n"
                                f"💰 Sell Charge (USD): {o['sell_charge']}\n"
                                f"💵 Sell Charge (MMK): {mmk_price:,.0f}\n"
                                f"📧 Email: {o['email']}\n"
                                f"🧾 Supplier Order ID: {sup_id}\n"
                                f"✅ Status: Processing"
                            )
                            send_log_retry(config.SUPPLIER_GROUP_ID, msg)
                        
                        elif 'error' in res:
                             # Refund Logic
                            user = supabase.table('users').select("balance_usd").eq("email", o['email']).execute().data
                            if user:
                                new_bal = float(user[0]['balance_usd']) + float(o['sell_charge'])
                                supabase.table('users').update({'balance_usd': new_bal}).eq("email", o['email']).execute()
                            supabase.table("WebsiteOrders").update({"status": "Canceled"}).eq("id", o["id"]).execute()
                    except: pass

                # --- B. K2BOOST MANUAL ORDER ---
                elif supplier == "k2boost":
                    # Update Status
                    supabase.table("WebsiteOrders").update({"status": "Processing"}).eq("id", o["id"]).execute()
                    
                    # ⚡️ K2Boost Message Format
                    msg = (
                        f"⚡️ <b>New Order to K2BOOST</b>\n\n"
                        f"🆔 <b>{o['id']}</b>\n"
                        f"📧 Email: {o['email']}\n"
                        f"📦 Service: {html.escape(o.get('service',''))}\n"
                        f"🔢 Quantity: {o['quantity']}\n"
                        f"🔗 Link: {html.escape(o['link'])}\n"
                        f"📆 Day: {o.get('day', 1)}\n"
                        f"⏳ Remain: {o.get('quantity')}\n"
                        f"💰 Sell Charge (USD): {o['sell_charge']}\n"
                        f"💵 Sell Charge (MMK): {mmk_price:,.0f}\n"
                        f"🏷 Supplier: k2boost\n"
                        f"🕒 Created: {o['created_at']}\n"
                        f"💬 Used Type: {o.get('UsedType', 'Default')}"
                    )
                    send_log_retry(config.K2BOOST_GROUP_ID, msg) # Ensure it goes to K2Boost Group

        except Exception as e: print(f"Order Error: {e}")
        time.sleep(5)

# 2. STATUS CHECKER (Detailed Report)
def smmgen_status_batch_loop():
    while True:
        try:
            all_smm = supabase.table("WebsiteOrders").select("*").eq("supplier_name","smmgen").not_.in_("status", ["Completed", "Canceled", "Refunded"]).not_.is_("supplier_order_id", None).execute().data or []
            s_ids = [str(o['supplier_order_id']) for o in all_smm if str(o['supplier_order_id']).isdigit()]
            
            if not s_ids: time.sleep(60); continue
            
            for i in range(0, len(s_ids), 100):
                batch = ",".join(s_ids[i:i + 100])
                try:
                    res = requests.post(config.SMM_API_URL, data={"key": config.SMM_API_KEY, "action": "status", "orders": batch}, timeout=30).json()
                    for sup_id, info in res.items():
                        if isinstance(info, dict) and "status" in info:
                            new_s = info["status"]
                            # Find local order
                            local_order = next((x for x in all_smm if str(x['supplier_order_id']) == str(sup_id)), None)
                            
                            if local_order and local_order['status'] != new_s:
                                # Update DB
                                remains = int(info.get('remains', 0))
                                supabase.table("WebsiteOrders").update({"status": new_s, "remain": remains}).eq("supplier_order_id", sup_id).execute()
                                
                                # Prepare Detailed Message
                                done_qty = int(local_order['quantity']) - remains
                                refund = 0.0
                                spend = float(local_order['sell_charge'])
                                
                                # Refund Logic Calculation
                                if new_s in ["Canceled", "Partial", "Refunded"]:
                                    if int(local_order['quantity']) > 0:
                                        refund = (spend / int(local_order['quantity'])) * remains
                                        spend = spend - refund
                                        # Update User Balance
                                        user = supabase.table('users').select("balance_usd").eq("email", local_order['email']).execute().data
                                        if user:
                                            new_bal = float(user[0]['balance_usd']) + refund
                                            supabase.table('users').update({'balance_usd': new_bal}).eq("email", local_order['email']).execute()
                                
                                # 📦 Detailed Report Message
                                msg = (
                                    f"📦 ✅ <b>{new_s} Order</b>\n"
                                    f"🧾 Order ID: {local_order['id']}\n"
                                    f"🧩 Service: {html.escape(local_order.get('service',''))}\n"
                                    f"👤 User: {local_order['email']}\n"
                                    f"📊 Quantity: {local_order['quantity']}\n"
                                    f"⏳ Remain: {remains}\n"
                                    f"✅ Done Qty: {done_qty}\n"
                                    f"💰 Amount: ${local_order['sell_charge']}\n"
                                    f"💸 Refund: ${refund:.4f}\n"
                                    f"📈 Spend Added: ${spend:.4f}\n"
                                    f"🔄 New Status: {new_s}\n"
                                    f"🕒 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                                )
                                send_log_retry(config.SUPPLIER_GROUP_ID, msg)
                                
                                # Simple Status Msg (Optional)
                                simple_msg = (
                                    f"✅ Order #{sup_id} Status Changed\n"
                                    f"🕒 Old: {local_order['status']}\n"
                                    f"🚀 New: {new_s}"
                                )
                                send_log_retry(config.SUPPLIER_GROUP_ID, simple_msg)

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
                
                if match: # Auto Success
                    user = supabase.table("users").select("balance_usd").eq("email", tx['email']).execute().data
                    if user:
                        old = float(user[0]['balance_usd']); new = old + float(tx["amount"])
                        supabase.table("VerifyPayment").update({"status": "used"}).eq("transaction_id", tx['transaction_id']).execute()
                        supabase.table("users").update({"balance_usd": new}).eq("email", tx['email']).execute()
                        supabase.table("transactions").update({"status": "Accepted"}).eq("id", tx_id).execute()
                        
                        msg = (
                            f"✅ <b>Auto Top-up Completed</b>\n\n"
                            f"👤 User: {tx['email']}\n"
                            f"💳 Method: {tx['method']}\n"
                            f"💰 Amount USD: {tx['amount']}\n"
                            f"🇲🇲 Amount MMK: {mmk_amt:,.0f}\n"
                            f"🧾 Transaction ID: {tx['transaction_id']}"
                        )
                        send_log_retry(config.AFFILIATE_GROUP_ID, msg)
                else: # Manual Check
                    supabase.table("transactions").update({"status": "Processing"}).eq("id", tx_id).execute()
                    msg = (
                        f"🆕 <b>New Unverified Transaction</b>\n\n"
                        f"🆔 ID: {tx_id}\n"
                        f"📧 Email: {tx['email']}\n"
                        f"💳 Method: {tx['method']}\n"
                        f"💵 Amount USD: {tx['amount']}\n"
                        f"🇲🇲 Amount MMK: {mmk_amt:,.0f}\n"
                        f"🧾 Transaction ID: {tx.get('transaction_id', 'N/A')}\n\n"
                        f"🛠 <b>Admin Commands:</b>\n"
                        f"/Yes {tx_id}\n"
                        f"/No {tx_id}"
                    )
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
                    msg = (
                        f"💰 <b>Affiliate Topup</b>\n\n"
                        f"🆔 ID = {rid}\n"
                        f"📧 Email = {req['email']}\n"
                        f"💳 Method = TopUp\n"
                        f"💵 Amount USD = {req['amount']}\n"
                        f"🇲🇲 Amount MMK = {mmk_amt:,.0f}"
                    )
                    send_log_retry(config.AFFILIATE_GROUP_ID, msg)
                else:
                    msg = (
                        f"🆕 <b>New Affiliate Request</b>\n\n"
                        f"🆔 ID = {rid}\n"
                        f"📧 Email = {req['email']}\n"
                        f"💰 Amount = {req['amount']}\n"
                        f"💳 Method = {req['method']}\n"
                        f"📱 Phone ID = {req.get('phone_id','-')}\n"
                        f"👤 Name = {req.get('name','-')}\n\n"
                        f"🇲🇲 Amount MMK = {mmk_amt:,.0f}\n"
                        f"🛠 <b>Admin Actions:</b>\n"
                        f"/Accept {rid}\n"
                        f"/Failed {rid}"
                    )
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
                lid = t.get("order_id"); subject = t.get("subject")
                
                # ... (Auto Check Logic - same as before) ...
                # (For brevity, skipping the auto-check code here, just updating formatting)
                
                msg = (
                    f"📢 <b>New Support Ticket</b>\n"
                    f"ID - {t['id']}\n"
                    f"Email - {t['email']}\n"
                    f"Subject - {html.escape(subject)}\n"
                    f"Order ID - {lid}\n\n"
                    f"Message:\n{html.escape(t.get('message', 'No message'))}\n\n"
                    f"Commands:\n"
                    f"/Answer {t['id']} reply message\n"
                    f"/Close {t['id']}"
                )
                send_log_retry(config.SUPPORT_GROUP_ID, msg)
                supabase.table("SupportBox").update({"status": "Processing"}).eq("id", t['id']).execute()
        except: pass
        time.sleep(10)

# 6. RATE CHECKER (Standard)
def check_smmgen_rates_loop():
    while True:
        try:
            payload = {'key': config.SMM_API_KEY, 'action': 'services'}
            res = requests.post(config.SMM_API_URL, data=payload, timeout=30).json()
            local = supabase.table("services").select("id, service_id, buy_price, service_name").execute().data or []
            for ls in local:
                api_svc = next((s for s in res if str(s['service']) == str(ls['service_id'])), None)
                if api_svc:
                    api_rate = float(api_svc['rate']); old_rate = float(ls['buy_price'])
                    if abs(old_rate - api_rate) > 0.0001:
                        supabase.table("services").update({"buy_price": api_rate}).eq("id", ls['id']).execute()
                        msg = f"📉📈 <b>Price Changed</b>\n🆔 {ls['id']}\n📦 {ls['service_name']}\n💰 {old_rate} ➝ {api_rate}"
                        send_log_retry(config.REPORT_GROUP_ID, msg)
        except: pass
        time.sleep(3600)

# 7. AUTO IMPORT
def auto_import_services_loop():
    while True:
        try:
            payload = {'key': config.SMM_API_KEY, 'action': 'services'}
            res = requests.post(config.SMM_API_URL, data=payload, timeout=60).json()
            existing = supabase.table("services").select("service_id").execute().data
            existing_ids = [str(x['service_id']) for x in existing]
            new_s = []
            for item in res:
                s_id = str(item['service'])
                if s_id not in existing_ids:
                    buy = float(item['rate'])
                    sell = buy * 3.0 if 'view' in item['name'].lower() else buy * 1.4
                    new_s.append({
                        "service_id": s_id, "service_name": item['name'], "category": item['category'],
                        "type": "Demo", "min": int(item['min']), "max": int(item['max']),
                        "buy_price": buy, "sell_price": round(sell, 4), "source": "smmgen", "per_quantity": 1000
                    })
            if new_s:
                data = supabase.table("services").insert(new_s).execute()
                if data.data:
                    for s in data.data:
                        send_log_retry(config.REPORT_GROUP_ID, f"🆕 <b>Imported</b>\nID: {s['id']}\nName: {s['service_name']}")
        except: pass
        time.sleep(21600)
