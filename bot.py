import os
import time
import threading
from keep_alive import keep_alive
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from telebot import TeleBot, types
from supabase import create_client
from dateutil import parser
import requests
import traceback
load_dotenv()

TOKEN = os.getenv("TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SMMGEN_API_KEY = os.getenv("SMMGEN_API_KEY")
REAL_BOOST_GROUP_ID = os.getenv("REAL_BOOST_GROUP_ID")  # /Done, /Error
FAKE_BOOST_GROUP_ID = os.getenv("FAKE_BOOST_GROUP_ID")  # /Buy

# Bot နှင့် Supabase Client ကို Initialize လုပ်ခြင်း
bot = TeleBot(TOKEN)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# အသုံးပြုသူ state များ
user_states = {}
user_chatids_by_username = {}
latest_order_id = 0
banned_user_ids = set()


# အခြား handlers များ (start, refill, request, error, admin commands...) အားလုံး ဒီလို indent မှန်အောင် ပြင်ပေးထားပါတယ်

# Poll New Orders with fixed indentation

# Error Prompt Text
ERROR_PROMPTS = [
    "1. Order Error လား တစ်ခြား Error လား❓\n\nမည်သည့် Error ဖြစ်ကြောင်း ရေးပါ ✅",
    "2. မည်သို့ဖြစ်သည်ကိုရေးပါ☑️\n\nဥပမာ ငွေမရောက်သေးတာ စသည်ဖြင့်",
    "3. @email & Order ID ရေးပါ 💬\nEg. example@gmail.com , Order ID 👀",
    "4. Error ဖြစ်မဖြစ်သေချာ စစ်ဆေးပါ💣\n\nသေချာပါက 'Error Report ✅' ကိုနှိပ်ပါ။"
]

def reset_state(user_id):
    user_states.pop(user_id, None)
    # /start Command
@bot.message_handler(commands=['start'])
def cmd_start(message):
    if message.chat.type != "private":
        return
    chat_id = message.chat.id
    username = message.from_user.username or message.from_user.first_name
    if username:
        user_chatids_by_username[username.lower()] = chat_id
    if chat_id in banned_user_ids:
        bot.send_message(chat_id, "🚫 သင်သည် Bot ကိုအသုံးပြုခွင့်ပိတ်ထားပါသည်။")
        return
    text = (
        "🎉 Hello! K2 Bot မှကြိုဆိုပါတယ်။\n\n"
        "ကျနော်တို့ရဲ့ K2Boost ဆိုတဲ့ Telegram Channel လေးကို Join ပေးကြပါအုံး။✅\n\n"
        "[ https://t.me/K2_Boost ]"
    )
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("Request တောင်းဆိုခြင်း 🙏", callback_data="request"),
        types.InlineKeyboardButton("Error ဖြစ်ခြင်းကိုဖြေရှင်းရန် ‼️", callback_data="error"),
        types.InlineKeyboardButton("Refill ဖြည့်ရန်♻️ ", callback_data="refill"),
        types.InlineKeyboardButton("အသုံးပြုနည်းလမ်းညွန် ✅", url="https://t.me/K2_Boost")
    )
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")

# Refill Flow with 2 Steps
@bot.callback_query_handler(func=lambda c: c.data == "refill")
def cb_refill_start(call):
    user_id = call.from_user.id
    user_states[user_id] = {"mode": "refill", "step": 1, "data": {}}
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Refill Cancel ❌", callback_data="refill_cancel"))
    msg = (
        "📧 Refill ပြုလုပ်ရန်အတွက် Email ကို ရိုက်ထည့်ပါ။\n\n"
        "Website ထဲက Email ကို Copy ယူပြီး Paste လုပ်ပါ။✅\n\n"
        "ဥပမာ 👇\nexample@gmail.com\nexample@Gmail.com"
    )
    bot.send_message(user_id, msg, reply_markup=markup, parse_mode="Markdown")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == "refill_cancel")
def cb_refill_cancel(call):
    user_id = call.from_user.id
    if user_states.get(user_id, {}).get("mode") == "refill":
        reset_state(user_id)
        bot.send_message(user_id, "✅ Refill Cancel ပြီးပါပြီ။")
    else:
        bot.send_message(user_id, "⚠️ Refill Cancel မရနိုင်ပါ။")
    bot.send_message(user_id, "⚡️အစသို့ပြန်သွားရန် /start ကိုနှိပ်ပါ။")
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get("mode") == "refill")
def handle_refill_steps(message):
    user_id = message.from_user.id
    text = message.text.strip()
    state = user_states.get(user_id)
    if not state:
        return

    step = state.get("step")
    if step == 1:
        # Email Validation
        if "@" not in text or "." not in text:
            bot.send_message(user_id, "❌ Email မမှန်ပါ။ ပြန်စစ်ပေးပါ။")
            return
        state["data"]["email"] = text
        state["step"] = 2
        bot.send_message(
            user_id,
            "🔁 Refill ပြုလုပ်ချင်သည့် Order ID နှင့် ဖြစ်သည့်အကြောင်းအရင်းကိုရေးပေးပါ။\n\n"
            "ဥပမာ 👉 OrderID- 1234 , TikTok Like ကျသွားပါတယ် ♻️",
            parse_mode="Markdown"
        )
    elif step == 2:
        state["data"]["info"] = text
        email = state["data"]["email"]
        info = state["data"]["info"]
        username = message.from_user.username or message.from_user.first_name
        reset_state(user_id)

        refill_msg = (
            f"🔁 Refill Request\n\n"
            f"👤 @{username} (ID: {user_id})\n"
            f"📧 Email: {email}\n"
            f"📝 Info: {info}\n\n"
        )
        bot.send_message(ADMIN_GROUP_ID, refill_msg)
        bot.send_message(user_id, "✅ Refill Request တောင်းဆိုပြီးပါပြီ။\n  ")
        bot.send_message(user_id, "⚡️အစသို့ပြန်သွားရန် /start ကိုနှိပ်ပါ။")
        # Request Flow
@bot.callback_query_handler(func=lambda c: c.data == "request")
def cb_request(call):
    user_id = call.from_user.id
    user_states[user_id] = {"mode": "request"}
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Request Cancel ✅", callback_data="request_cancel"))
    bot.send_message(
        user_id,
        "K2 ဆီကိုတောင်းဆိုချင်သည့် စာ ၊ အကြံပြုချက်\nရေးထားပေးနိုင်ပါတယ် 🙏",
        reply_markup=markup
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == "request_cancel")
def cb_request_cancel(call):
    user_id = call.from_user.id
    if user_states.get(user_id, {}).get("mode") == "request":
        reset_state(user_id)
        bot.send_message(user_id, "✅ Request Cancel ပြီးပါပြီ။")
    else:
        bot.send_message(user_id, "⚠️ Request Cancel မရနိုင်ပါ။")
    bot.answer_callback_query(call.id)
    bot.send_message(user_id, "⚡️အစသို့ပြန်သွားရန် /start ကိုနှိပ်ပါ။")

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get("mode") == "request")
def handle_request_message(message):
    user_id = message.from_user.id
    text = message.text.strip()
    username = message.from_user.username or message.from_user.first_name
    forward = f"Title Request🙏 \n\n @{username} (ID: {user_id}):\n\n{text}"
    bot.send_message(ADMIN_GROUP_ID, forward)
    bot.send_message(user_id, "Request တောင်းဆိုခြင်း လက်ခံရရှိပါပြီ ✅")
    reset_state(user_id)
    bot.send_message(user_id, "⚡️အစသို့ပြန်သွားရန် /start ကိုနှိပ်ပါ။")

# Error Flow
@bot.callback_query_handler(func=lambda c: c.data == "error")
def cb_error_start(call):
    user_id = call.from_user.id
    user_states[user_id] = {"mode": "error", "step": 1, "data": {}}
    bot.send_message(user_id, ERROR_PROMPTS[0])
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get("mode") == "error")
def handle_error_steps(message):
    user_id = message.from_user.id
    state = user_states.get(user_id)
    if not state:
        return
    step = state["step"]
    text = message.text.strip()
    if step in [1, 2]:
        state["data"][f"step_{step}"] = text
        state["step"] += 1
        bot.send_message(user_id, ERROR_PROMPTS[step])
    elif step == 3:
        if "@" not in text:
            bot.send_message(user_id, "❌ Email ပါအောင်ရိုက်ထည့်ပါ။")
            return
        state["data"]["email_order"] = text
        state["step"] = 4
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("Error Report ✅", callback_data="error_report"),
            types.InlineKeyboardButton("Error Cancel ❌", callback_data="error_cancel")
        )
        bot.send_message(user_id, ERROR_PROMPTS[3], reply_markup=markup)
    else:
        bot.send_message(user_id, "Button ကိုရွေးချယ်ပါ 🔘")

@bot.callback_query_handler(func=lambda c: c.data in ["error_report", "error_cancel"])
def cb_error_report_cancel(call):
    user_id = call.from_user.id
    if user_id not in user_states:
        bot.answer_callback_query(call.id, "⚠️ Error Report မရှိပါ။")
        return
    if call.data == "error_cancel":
        reset_state(user_id)
        bot.send_message(user_id, "⭕️ Error Report မလုပ်တော့ပါဘူး")
        bot.send_message(user_id, "⚡️အစသို့ပြန်သွားရန် /start ကိုနှိပ်ပါ။")
    else:
        data = user_states[user_id]["data"]
        reset_state(user_id)
        username = call.from_user.username or call.from_user.first_name
        error_text = (
            f"🚨 New Error Report \n\n @{username} (ID: {user_id}):\n\n"
            f"Step 1: {data.get('step_1','')}\n"
            f"Step 2: {data.get('step_2','')}\n"
            f"Step 3: {data.get('email_order','')}\n"
        )
        bot.send_message(ADMIN_GROUP_ID, error_text)
        bot.send_message(user_id, "🛠 Error Report တင်ပြီးပါပြီ 💯")
        # Admin Commands

@bot.message_handler(commands=['Done'])
def handle_done(message):
    print(f"[DEBUG] message.text: {repr(message.text)}")
    print(f"[DEBUG] chat.id: {message.chat.id}, REAL_BOOST_GROUP_ID: {REAL_BOOST_GROUP_ID}")

    if str(message.chat.id) != str(REAL_BOOST_GROUP_ID):
        bot.reply_to(message, "⚠️ ဒီ command ကို သတ်မှတ်ထားတဲ့ Group ထဲမှာပဲ သုံးလို့ရပါတယ်။")
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        bot.reply_to(message, "🔧 သုံးပုံ မှားနေပါတယ်။\n\nမှန်ကန်သော Format:\n/Done <order_id> [optional_reason]\nဥပမာ: /Done 123 မှန်ပြီ")
        return

    order_id = parts[1].strip()
    reason = parts[2].strip() if len(parts) > 2 else "Completed"

    result = supabase.table("orders").update({
        "status": "Done",
        "reason": reason
    }).eq("id", order_id).execute()

    print(f"[DEBUG] Supabase update result: {result}")

    if result.data:
        bot.reply_to(message, f"✅ Order {order_id} ကို Done အဖြစ် သတ်မှတ်ပြီးပါပြီ။")
    else:
        bot.reply_to(message, f"❌ Order ID {order_id} မတွေ့ပါ။")

@bot.message_handler(commands=['Error'])
def handle_error(message):
    print(f"[DEBUG] message.text: {repr(message.text)}")
    print(f"[DEBUG] chat.id: {message.chat.id}, REAL_BOOST_GROUP_ID: {REAL_BOOST_GROUP_ID}")

    if str(message.chat.id) != str(REAL_BOOST_GROUP_ID):
        bot.reply_to(message, "⚠️ ဒီ command ကို သတ်မှတ်ထားတဲ့ Group ထဲမှာပဲ သုံးလို့ရပါတယ်။")
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(message, "🔧 သုံးပုံ မှားနေပါတယ်။\n\nမှန်ကန်သော Format:\n/Error <order_id> <အကြောင်းအရင်း>\nဥပမာ: /Error 123 လိပ်စာ မှားနေပါတယ်")
        return

    try:
        order_id = int(parts[1].strip())
    except ValueError:
        bot.reply_to(message, "❌ Order ID မှားနေပါတယ်။ Number ဖြစ်ရပါမယ်။")
        return

    reason = parts[2].strip()

    result = supabase.table("orders").update({
        "status": "Error",
        "reason": reason
    }).eq("id", order_id).execute()

    print(f"[DEBUG] Supabase update result: {result}")

    if result.data:
        bot.reply_to(message, f"❌ Order {order_id} ကို Error အဖြစ် သတ်မှတ်ပြီးပါပြီ။")
    else:
        bot.reply_to(message, f"⚠️ Order ID {order_id} မတွေ့ပါ။")

@bot.message_handler(commands=['S'])
def admin_send_user(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(message, "Usage: /S @username message")
        return
    username = parts[1].lstrip('@').lower()
    send_text = parts[2]
    user_id = user_chatids_by_username.get(username)
    if not user_id:
        bot.reply_to(message, f"❌ User @{username} ကို မတွေ့ပါ။")
        return
    bot.send_message(user_id, f"K2 မှ Message♻️:\n\n{send_text}")
    bot.reply_to(message, f"Message ကို @{username} ဆီသို့ ပို့ပြီးပါပြီ။✅")



@bot.message_handler(commands=['Clean'])
def clean_old_orders(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    parts = message.text.split()
    if len(parts) != 2 or parts[1] != "3Day":
        bot.reply_to(message, "Usage: /Clean 3Day")
        return
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        old_orders = supabase.table("orders") \
            .select("id, created_at") \
            .lt("created_at", cutoff.isoformat()) \
            .execute()
        deleted_ids = []
        for order in old_orders.data:
            supabase.table("orders").delete().eq("id", order["id"]).execute()
            deleted_ids.append(str(order["id"]))
        if deleted_ids:
            bot.reply_to(message, f"🗑 Deleted Orders: {', '.join(deleted_ids)}")
        else:
            bot.reply_to(message, "ℹ️ မရှိပါ။")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['Ban'])
def handle_ban_user(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /Ban @username")
        return
    username = parts[1].lstrip('@').lower()
    user_id = user_chatids_by_username.get(username)
    if user_id:
        banned_user_ids.add(user_id)
        bot.reply_to(message, f"🚫 @{username} ကို Ban လုပ်ပြီးပါပြီ။")
    else:
        bot.reply_to(message, f"❌ User @{username} မတွေ့ပါ။")
@bot.message_handler(commands=['Unban'])
def handle_unban_user(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /Unban @username")
        return
    username = parts[1].lstrip('@').lower()
    user_id = user_chatids_by_username.get(username)
    if user_id and user_id in banned_user_ids:
        banned_user_ids.remove(user_id)
        bot.reply_to(message, f"✅ @{username} ကို Unban ပြန်လုပ်ပြီးပါပြီ။")
    else:
        bot.reply_to(message, f"ℹ️ @{username} ကို Ban မထားပါ။")

        # Refill Command
@bot.message_handler(commands=['Refill'])
def handle_refill(message):
    if message.chat.id != ADMIN_GROUP_ID:  # Admin Group ID မှာသာ အသုံးပြုနိုင်သည်
        bot.reply_to(message, "🚫 သင်သည် Refill Command ကို အသုံးပြုရန်ခွင့်မပြုပါ။")
        return

    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Usage: /Refill <smm_order_id>")
        return
    smm_order_id = parts[1]

    # SMMGEN API ကို Refill လုပ်ရန် Call
    refill_response = send_refill_to_smmgen(smm_order_id)
    if refill_response:
        bot.reply_to(message, f"✅ Refill request for SMM Order ID {smm_order_id} has been submitted.")
    else:
        bot.reply_to(message, f"❌ Failed to submit refill request for SMM Order ID {smm_order_id}.")

def send_refill_to_smmgen(smm_order_id):
    url = "https://smmgen.com/api/v2"
    data = {
        "key": SMMGEN_API_KEY,
        "action": "refill",
        "order": smm_order_id
    }
    try:
        res = requests.post(url, data=data)
        result = res.json()
        return result.get("success", False)
    except Exception as e:
        print(f"[❌ Refill Error] {e}")
        return False

# Buy Command
@bot.message_handler(commands=['Buy'])
def handle_buy(message):
    if message.chat.id != ADMIN_GROUP_ID:  # Admin Group ID မှာသာ အသုံးပြုနိုင်သည်
        bot.reply_to(message, "🚫 သင်သည် Buy Command ကို အသုံးပြုရန်ခွင့်မပြုပါ။")
        return

    parts = message.text.split()
    if len(parts) != 4:
        bot.reply_to(message, "Usage: /Buy <SMMGEN-ServiceID> <Quantity> <Link>")
        return
    
    service_id = parts[1]
    quantity = parts[2]
    link = parts[3]

    # SMMGEN API ကို Order တင်ရန် Call
    order_response = send_order_to_smmgen(service_id, quantity, link)
    if order_response:
        bot.reply_to(message, f"✅ Order for Service ID {service_id} has been submitted successfully.")
    else:
        bot.reply_to(message, f"❌ Failed to submit order for Service ID {service_id}.")

def send_order_to_smmgen(service_id, quantity, link):
    url = "https://smmgen.com/api/v2"
    data = {
        "key": SMMGEN_API_KEY,
        "action": "add",
        "service": service_id,
        "link": link,
        "quantity": quantity
    }
    try:
        res = requests.post(url, data=data)
        result = res.json()
        return "order" in result
    except Exception as e:
        print(f"[❌ Order Error] {e}")
        return False
    # ✅ Banned users ကို Block လုပ်ခြင်း
# ✅ Banned users ကို Block လုပ်ခြင်း
@bot.message_handler(func=lambda m: not m.text.startswith("/"), content_types=['text'])
def block_banned_users(message):
    ...
    if message.chat.type == "private" and message.from_user.id in banned_user_ids:
        bot.send_message(message.chat.id, "🚫 သင်အား Bot အသုံးပြုခွင့်ပိတ်ထားပါသည်။")
        return  # ❗ Block ဖြစ်တဲ့အခါ နောက်ထပ် logic မသွားအောင် return ပြန်ပေးပါ

# == Send Order to SMMGEN ==
def send_to_smmgen(order):
    url = "https://smmgen.com/api/v2"
    main_service = order["service_id"]
    main_quantity = order["quantity"]

    data = {
        "key": SMMGEN_API_KEY,
        "action": "add",
        "service": main_service,
        "link": order["link"],
        "quantity": main_quantity
    }

    if order.get("comments"):
        if isinstance(order["comments"], list):
            data["comments"] = "\n".join(order["comments"])
        else:
            data["comments"] = order["comments"]

    try:
        # Main Order
        res = requests.post(url, data=data, timeout=15)
        result = res.json()

        if "order" in result:
            smmgen_id = result["order"]
            charge_amount = result.get("charge", "N/A")
            currency = result.get("currency", "USD")

            supabase.table("orders").update({
                "status": "Processing",
                "smmgen_order_id": str(smmgen_id)
            }).eq("id", order["id"]).execute()

            mm_time = parser.parse(order['created_at']) + timedelta(hours=6, minutes=30)

            # 📌 Main Order message
            bot.send_message(
                FAKE_BOOST_GROUP_ID,
                f"✅ Main Order တင်ပြီးပါပြီ\n\n"
                f"📦 OrderID: {order['id']}\n"
                f"🧾 Service ID: {order['service_id']}\n"
                f"😂 SMMGEN Order ID: {smmgen_id}\n"
                f"🔢 Quantity: {order['quantity']}\n"
                f"💰 Amount: {order['amount']} Ks\n"
                f"💸 Cost: {charge_amount} {currency}\n"
                f"🕐 Time: {mm_time.strftime('%Y-%m-%d %H:%M')} (MMT)\n"
                f"📍 Status: Processing"
            )

            # ✅ Auto Extra Order Logic
            if main_service == 14962:  # View → Like (10%)
                extra_service = 9343
                extra_quantity = max(1, int(main_quantity * 0.1))
            elif main_service == 9343:  # Like → View (×10)
                extra_service = 14391
                extra_quantity = main_quantity * 10
            else:
                extra_service = None

            if extra_service:
                extra_res = requests.post(url, data={
                    "key": SMMGEN_API_KEY,
                    "action": "add",
                    "service": extra_service,
                    "link": order["link"],
                    "quantity": extra_quantity
                }, timeout=15)
                extra_result = extra_res.json()

                if "order" in extra_result:
                    # 📌 Extra Order message
                    bot.send_message(
                        FAKE_BOOST_GROUP_ID,
                        f"📎 Extra Order တင်ပြီးပါပြီ\n\n"
                        f"➡ Main OrderID: {order['id']}\n"
                        f"🧾 Service ID: {extra_service}\n"
                        f"😂 Extra SMMGEN Order ID: {extra_result['order']}\n"
                        f"🔢 Quantity: {extra_quantity}\n"
                        f"📌 For: {order['service']} ({main_quantity})"
                    )

        else:
            bot.send_message(
                FAKE_BOOST_GROUP_ID,
                f"❌ Order {order['id']} Failed:\n{result.get('error', 'Unknown Error')}"
            )

    except Exception:
        bot.send_message(
            FAKE_BOOST_GROUP_ID,
            f"❌ Order {order['id']} Exception:\n{traceback.format_exc()}"
        )
        
        
# == Poll New Orders ==
def poll_new_orders():
    global latest_order_id
    while True:
        try:
            orders = supabase.table("orders") \
                .select("*") \
                .eq("status", "Pending") \
                .gt("id", latest_order_id) \
                .order("id", desc=False) \
                .limit(10) \
                .execute()

            for order in orders.data or []:
                if order['id'] > latest_order_id:
                    latest_order_id = order['id']

                    # ✅ SMMGEN auto order
                    if isinstance(order.get("service_id"), int) and not order.get("smmgen_order_id"):
                        send_to_smmgen(order)
                    else:
                        mm_time = parser.parse(order['created_at']) + timedelta(hours=6, minutes=30)
                        msg = (
                            f"📦 OrderID: {order['id']}\n"
                            f"👤 Email: {order['email']}\n"
                            f"🛒 Service: {order['service']}\n"
                            f"🔴 Quantity: {order['quantity']}\n"
                            f"📆 Duration: {order.get('duration', 'N/A')} ရက်\n"
                            f"💰 Amount: {order['amount']} Ks\n"
                            f"🔗 Link: {order['link']}\n"
                            f"🕧 Time: {mm_time.strftime('%Y-%m-%d %H:%M')} (MMT)"
                        )

                        # ✅ Comments ပါလာရင် ထည့်
                        if order.get("comments"):
                            if isinstance(order["comments"], list):
                                comments_text = "\n".join(order["comments"])
                            else:
                                comments_text = str(order["comments"])
                            msg += f"\n💬 Comments: {comments_text}"

                        bot.send_message(REAL_BOOST_GROUP_ID, msg)

            time.sleep(5)

        except Exception as e:
            print("Polling Error:", e)
            time.sleep(10)


# == Check SMMGEN Status (Retry + Debug) ==
def check_smmgen_status(order_id, retries=3, delay=2):
    url = "https://smmgen.com/api/v2"
    data = {
        "key": SMMGEN_API_KEY,
        "action": "status",
        "order": order_id
    }
    for attempt in range(retries):
        try:
            res = requests.post(url, data=data, timeout=15)
            print(f"[DEBUG] SMMGEN Status response text for order {order_id}:", repr(res.text))
            res.raise_for_status()

            if not res.text.strip():
                print(f"[❌ Empty response] Order {order_id}")
                continue

            result = res.json()
            status = result.get("status", "Unknown")

            if status and status.lower() != "unknown":
                return status

        except requests.exceptions.RequestException as req_err:
            print(f"[⚠️ Retry {attempt+1}/{retries}] Request error for {order_id}: {req_err}")
        except ValueError:
            print(f"[⚠️ Retry {attempt+1}/{retries}] JSON decode error for {order_id}: {repr(res.text)}")
        except Exception:
            print(f"[⚠️ Retry {attempt+1}/{retries}] Unexpected error: {traceback.format_exc()}")

        time.sleep(delay)

    return "Unknown"


# == Update Status in Supabase ==
def update_order_status_in_supabase(order_id, new_status):
    try:
        result = supabase.table("orders").update({
            "status": new_status
        }).eq("id", order_id).execute()
        print(f"[✅ Status Updated] Order ID {order_id} -> {new_status}")
        return result
    except Exception:
        print(f"[❌ Supabase Update Error] {traceback.format_exc()}")
        return None


# == Polling SMMGEN for Status Changes ==
def poll_smmgen_orders_status():
    while True:
        try:
            response = supabase.table("orders") \
                .select("*") \
                .in_("status", ["Unknown", "Processing", "Pending", "In progress"]) \
                .execute()

            orders = response.data or []

            for order in orders:
                smmgen_order_id = order.get("smmgen_order_id")
                if smmgen_order_id:
                    current_status = check_smmgen_status(smmgen_order_id)

                    # Unknown ကို skip
                    if current_status != "Unknown" and current_status != order["status"]:
                        update_order_status_in_supabase(order["id"], current_status)
                        bot.send_message(
                            FAKE_BOOST_GROUP_ID,
                            f"🟢 Order ID {order['id']} status updated to {current_status} "
                            f"(SMMGEN ID: {smmgen_order_id})"
                        )

            time.sleep(60)

        except Exception:
            print(f"[Polling SMMGEN Error] {traceback.format_exc()}")
            time.sleep(60)


# == Bot Run ==
if __name__ == "__main__":
    keep_alive()
    threading.Thread(target=poll_new_orders, daemon=True).start()
    threading.Thread(target=poll_smmgen_orders_status, daemon=True).start()
    print("🤖 K2 Bot is running...")
    bot.infinity_polling()












