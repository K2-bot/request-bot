import time
import requests
import config
import json
import html # For escaping HTML
from db import supabase
from utils import parse_smm_support_response
from datetime import datetime

# 🔥 IMPROVED: Error Logging & HTML Mode (Prevents Markdown Errors)
def send_log(chat_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage", 
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"} # Changed to HTML
        )
    except Exception as e:
        print(f"⚠️ Send Log Error: {e}")

# 1. ORDER PROCESSOR (Fixed Logic for '0' ID)
def process_pending_orders_loop():
    while True:
        try:
            # Fetch Pending Orders
            orders = supabase.table("WebsiteOrders").select("*").eq("status", "Pending").execute().data or []
            
            for o in orders:
                # 🛑 CRITICAL FIX: Only skip if ID exists AND is NOT '0'
                # အရင်က '0' ဖြစ်နေရင် ကျော်သွားလို့ အခု ပြန်ပြင်ထားပါတယ်
                sup_oid = str(o.get("supplier_order_id") or "")
                
                # ID ရှိပြီး "0" မဟုတ်မှသာ ကျော်မယ် (ဆိုလိုတာက "0" ဆိုရင် ဆက်လုပ်မယ်)
                if sup_oid and sup_oid != "0": 
                    continue
                
                supplier = (o.get("supplier_name") or "").lower()
                
                # --- A. SMMGEN ORDER ---
                if supplier == "smmgen":
                    payload = {
                        'key': config.SMM_API_KEY, 
                        'action': 'add', 
                        'service': o['supplier_service_id'], 
                        'link': o['link'], 
                        'quantity': o['quantity']
                    }
                    try:
                        res = requests.post(config.SMM_API_URL, data=payload, timeout=30).json()
                        
                        # ✅ Success Case
                        if 'order' in res:
                            sup_id = str(res['order'])
                            supabase.table("WebsiteOrders").update({
                                "status": "Processing", 
                                "supplier_order_id": sup_id
                            }).eq("id", o["id"]).execute()
                            
                            # Log to Supplier Group
                            msg = (f"🚀 <b>Order Sent to SMMGEN</b>\n"
                                   f"🆔 Local: <code>{o['id']}</code>\n"
                                   f"🔢 SupID: <code>{sup_id}</code>\n"
                                   f"🔗 Service: {html.escape(o.get('service', ''))}")
                            send_log(config.SUPPLIER_GROUP_ID, msg)
                        
                        # ❌ Error Case (Refund)
                        elif 'error' in res:
                            # User Balance Refund (balance_usd)
                            user = supabase.table('users').select("balance_usd").eq("email", o['email']).execute().data
                            if user:
                                refund = float(o['sell_charge'])
                                new_bal = float(user[0]['balance_usd']) + refund
                                supabase.table('users').update({'balance_usd': new_bal}).eq("email", o['email']).execute()
                            
                            supabase.table("WebsiteOrders").update({"status": "Canceled"}).eq("id", o["id"]).execute()
                            
                            msg = (f"❌ <b>Order Failed & Refunded</b>\n"
                                   f"🆔 ID: <code>{o['id']}</code>\n"
                                   f"⚠️ Error: {res['error']}")
                            send_log(config.K2BOOST_GROUP_ID, msg)
                    except Exception as e:
                        print(f"SMM API Error: {e}")

                # --- B. K2BOOST MANUAL ORDER ---
                elif supplier == "k2boost":
                    # Update to Processing
                    supabase.table("WebsiteOrders").update({"status": "Processing"}).eq("id", o["id"]).execute()
                    
                    # Notify Admin
                    msg = (
                        f"⚡️ <b>New Manual Order</b>\n"
                        f"🆔 ID: <code>{o['id']}</code>\n"
                        f"📧 User: {o.get('email')}\n"
                        f"📦 Service: {html.escape(o.get('service', ''))}\n"
                        f"🔗 Link: <code>{html.escape(o.get('link', ''))}</code>\n"
                        f"🔢 Qty: {o.get('quantity')}\n\n"
                        f"👇 <b>Admin Actions:</b>\n"
                        f"/Done {o['id']} (Complete)\n"
                        f"/Error {o['id']} (Refund)"
                    )
                    send_log(config.K2BOOST_GROUP_ID, msg)

        except Exception as e:
            print(f"Order Loop Error: {e}")
        
        time.sleep(5)

# 2. STATUS BATCH
def smmgen_status_batch_loop():
    while True:
        try:
            all_smm = supabase.table("WebsiteOrders").select("supplier_order_id").eq("supplier_name","smmgen").not_.in_("status", ["Completed", "Canceled", "Refunded"]).not_.is_("supplier_order_id", None).execute().data or []
            s_ids = [str(o['supplier_order_id']) for o in all_smm if str(o['supplier_order_id']).isdigit()]
            if not s_ids: time.sleep(60); continue
            for i in range(0, len(s_ids), 100):
                batch = ",".join(s_ids[i:i + 100])
                try:
                    res = requests.post(config.SMM_API_URL, data={"key": config.SMM_API_KEY, "action": "status", "orders": batch}, timeout=30).json()
                    for sup_id, info in res.items():
                        if isinstance(info, dict) and "status" in info:
                            new_s = info["status"]
                            current = supabase.table("WebsiteOrders").select("status").eq("supplier_order_id", sup_id).execute().data
                            if current and current[0]['status'] != new_s:
                                supabase.table("WebsiteOrders").update({"status": new_s}).eq("supplier_order_id", sup_id).execute()
                                if new_s == "Canceled": send_log(config.K2BOOST_GROUP_ID, f"❌ **Order {sup_id} Canceled by Supplier**\n\nManual Check:\n/Done | /Error")
                    time.sleep(2)
                except: pass
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
                if match:
                    user = supabase.table("users").select("balance_usd").eq("email", tx['email']).execute().data
                    if user:
                        old = float(user[0]['balance_usd']); new = old + float(tx["amount"])
                        supabase.table("VerifyPayment").update({"status": "used"}).eq("transaction_id", tx['transaction_id']).execute()
                        supabase.table("users").update({"balance_usd": new}).eq("email", tx['email']).execute()
                        supabase.table("transactions").update({"status": "Accepted"}).eq("id", tx_id).execute()
                        send_log(config.AFFILIATE_GROUP_ID, f"✅ **Auto Top-up Success!**\n👤 `{tx['email']}`\n💵 `${tx['amount']}`\n💰 `${old}` ➝ `${new}`")
                else:
                    supabase.table("transactions").update({"status": "Processing"}).eq("id", tx_id).execute()
                    send_log(config.AFFILIATE_GROUP_ID, f"🆕 **Unverified Tx**\nID: `{tx_id}`\nUser: `{tx['email']}`\nAmt: `${tx['amount']}`\n/Yes {tx_id} | /No {tx_id}")
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
                send_log(config.AFFILIATE_GROUP_ID, f"💸 **Affiliate Payout**\nUser: `{req['email']}`\nAmount: `${req['amount']}`\n/Accept {rid}")
                processed_aff.add(rid)
        except: pass
        time.sleep(10)

# 5. RATE CHECKER
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
                        send_log(config.REPORT_GROUP_ID, f"📉📈 **Price Changed**\n🆔 `{ls['id']}`\n📦 {ls['service_name']}\n💰 `${old_rate}` ➝ `${api_rate}`")
        except: pass
        time.sleep(3600)

# 6. SUPPORT POLLER
def poll_supportbox_worker():
    while True:
        try:
            tickets = supabase.table("SupportBox").select("*").eq("status", "Pending").execute().data or []
            for t in tickets:
                lid = t.get("order_id"); subject = t.get("subject")
                order_res = supabase.table("WebsiteOrders").select("supplier_order_id, status").eq("id", lid).execute().data
                sup_id = None; order_status = "Unknown"
                if order_res:
                    sup_id = order_res[0].get("supplier_order_id"); order_status = order_res[0].get("status")

                is_auto = False; reply_text = ""
                if order_status in ["Canceled", "Refunded", "Fail"]:
                    reply_text = f"❌ Request Rejected. Order is already {order_status}."; is_auto = True
                elif subject in ["Refill", "Cancel"] and sup_id:
                    action = 'refill' if subject == 'Refill' else 'cancel'
                    try:
                        res = requests.post(config.SMM_API_URL, data={'key': config.SMM_API_KEY, 'action': action, 'order': sup_id}, timeout=10).json()
                        if 'error' in res: reply_text = f"⚠️ API Error: {res['error']}"; is_auto = False
                        else: reply_text = parse_smm_support_response(res, subject, lid); is_auto = True
                    except: reply_text = "⚠️ Connection Error"; is_auto = False
                else: reply_text = "Waiting for Admin..."; is_auto = False

                if is_auto:
                    send_log(config.SUPPORT_GROUP_ID, f"✅ **Auto Completed Report**\nTicket: `{t['id']}`\nOrder: `{lid}`\nAction: {subject}\nResult: {reply_text}")
                    supabase.table("SupportBox").update({"reply_text": reply_text, "status": "Replied", "updated_at": datetime.now().isoformat()}).eq("id", t['id']).execute()
                else:
                    send_log(config.SUPPORT_GROUP_ID, f"📩 **New Ticket**\nTicket: `{t['id']}`\nOrder: `{lid}`\nSub: `{subject}`\nStat: `{order_status}`\n\n⚠️ **Manual Action Needed:**\n`/Reply {t['id']} YourMessage`")
                    supabase.table("SupportBox").update({"status": "Processing"}).eq("id", t['id']).execute()
        except: pass
        time.sleep(10)

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
                        send_log(config.REPORT_GROUP_ID, f"🆕 **Imported**\nID: `{s['id']}`\nName: {s['service_name']}\nType: Demo")
        except: pass
        time.sleep(21600)
