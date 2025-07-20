
import os
import time
import threading
from keep_alive import keep_alive
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from telebot import TeleBot, types
from supabase import create_client
from dateutil import parser

# ✅ Environment Variable တွေ load ပြုလုပ်ခြင်း
load_dotenv()
TOKEN = os.getenv("TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# ✅ Bot နှင့် Supabase Client Initialize
bot = TeleBot(TOKEN)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ✅ အသုံးပြုသူတွေရဲ့ state များ စောင့်သိမ်းဖို့ Dictionary များ
user_states = {}  # user_id -> state
user_chatids_by_username = {}  # username.lower() -> chat_id
latest_order_id = 0
banned_user_ids = set()

# ✅ Error Prompt Text တွေ
ERROR_PROMPTS = [
    "1. Order Error လား တစ်ခြား Error လား❓\n\nမည်သည့် Error ဖြစ်ကြောင်း ရေးပါ ✅",
    "2. မည်သို့ဖြစ်သည်ကိုရေးပါ☑️\n\nဥပမာ ငွေမရောက်သေးတာ စသည်ဖြင့်\n\nအကြောင်းအရာအချက်အလက်ကိုရေးပါ။",
    "3. အချက်အလက် @email & Order Error ဖြစ်ပါက Order ID ရေးပေးပါ 💬။\n\nWebsite ထဲက Email ကို Copy ယူပေးပါ 👁‍🗨\n\nEg. example@gmail.com , Order ID 👀",
    "4. Error ဖြစ်မဖြစ်သေချာ စစ်ဆေးပါ💣\n\nဥပမာ Order Error က ကြာချိန်ဆိုရင် ပြောပြထားတဲ့အချိန်ထက်ကျော်မှ Complain တင်ပါ 📊\n\nError က Password မေ့တဲ့ပြဿနာတွေဆိုရင် မဖြေရှင်းပေးပါ❌\n\nOrder Cancel ခံရတယ်ဆိုရင် ဘာကြောင့် Cancel ခံရလဲဆိုတာကို ကျနော်တို့ Reason ရေးပေးထားပါတယ်။✅\n\nကိုယ်ဘက်က အမှားမရှိဘူးဆိုမှ သေချာစစ်ဆေးပြီး ရေးသားဖို့အတွက် မေတ္တာရပ်ခံပါတယ်ရှင့်🤗"
]

def reset_state(user_id):
    if user_id in user_states:
        del user_states[user_id]

# ✅ /start
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
        "🎉 Hello! Welcome to K2 Bot.\n\n"
        "ကျနော်တို့ရဲ့ K2Boost ဆိုတဲ့ Telegram Channel လေးကို Join ပေးကြပါအုံး။✅\n\n"
        "[ https://t.me/K2_Boost ]"
    )
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("Request တောင်းဆိုခြင်း 🙏", callback_data="request"),
        types.InlineKeyboardButton("Error ဖြစ်ခြင်းကိုဖြေရှင်းရန် ‼️", callback_data="error"),
        types.InlineKeyboardButton("အသုံးပြုနည်းလမ်းညွန် ✅", url="https://t.me/K2_Boost")
    )
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")

# ✅ Request Flow
@bot.callback_query_handler(func=lambda c: c.data == "request")
def cb_request(call):
    user_id = call.from_user.id
    user_states[user_id] = {"mode": "request"}
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Request Cancel ✅", callback_data="request_cancel"))
    bot.send_message(
        user_id,
        "K2 ဆီကိုတောင်းဆိုချင်သည့် စာ ၊ အကြံပြုချက်\nရေးထားပေးနိုင်ပါတယ် ။🙏\n\nမရေးသားလိုပါက Request Cancel ကိုနှိပ်ပါ ✅\n\nရေးသားလိုပါက ရေးသားပြီးတော့ Send နှိပ်လိုက်ပါ ✍️",
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
    bot.send_message(user_id, "Request တောင်းဆိုခြင်း လက်ခံရရှိပါပြီ ✅ ကျေးဇူးတင်ပါတယ် 🙏")
    reset_state(user_id)
    bot.send_message(user_id, "⚡️အစသို့ပြန်သွားရန် /start ကိုနှိပ်ပါ။")

# ✅ Error Report Flow
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
        state["step"] = step + 1
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
        bot.send_message(user_id, "Choose the Button 🔘")

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
        bot.send_message(user_id, "🛠 Error ပြဿနာဖြေရှင်းရန် စာတင်ပြီးပါပြီ 💯\n\n‌ဖြေရှင်းပြီးပါက Reason နှင့်တကွ ပြန်လည်အသိပေးပါမည်⚠️")
        bot.send_message(user_id, "⚡️အစသို့ပြန်သွားရန် /start ကိုနှိပ်ပါ။")
        username = call.from_user.username or call.from_user.first_name
        error_text = (
            f"🚨 New Error Report \n\n @{username} (ID: {user_id}):\n\n"
            f"Step 1: {data.get('step_1','')}\n"
            f"Step 2: {data.get('step_2','')}\n"
            f"Step 3: {data.get('email_order','')}\n"
        )
        bot.send_message(ADMIN_GROUP_ID, error_text)
        
# ✅ Admin Commands (S, Done, Error, Refund, Clean, Ban, Unban) — Already Correct — Continue Below# ✅ Admin Commands
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

@bot.message_handler(commands=['Done'])
def handle_done(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /Done <order_id> [reason]")
        return
    order_id = parts[1]
    reason = parts[2] if len(parts) > 2 else "Completed"
    result = supabase.table("orders").update({"status": "Done", "reason": reason}).eq("id", order_id).execute()
    if result.data:
        bot.reply_to(message, f"✅ Order {order_id} marked as Done.")
    else:
        bot.reply_to(message, f"❌ Order ID {order_id} မတွေ့ပါ။")

@bot.message_handler(commands=['Error'])
def handle_error(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(message, "Usage: /Error <order_id> <reason>")
        return
    order_id = parts[1]
    reason = parts[2]
    order = supabase.table("orders").select("email, amount").eq("id", order_id).execute()
    if not order.data:
        bot.reply_to(message, f"❌ Order ID {order_id} မတွေ့ပါ။")
        return
    email = order.data[0]['email']
    amount = order.data[0]['amount']
    supabase.table("orders").update({"status": "Error", "reason": reason}).eq("id", order_id).execute()
    bot.reply_to(message, f"🔁 Order {order_id} marked as Error.\n\n )


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
            .in_("status", ["Done", "Error"]) \
            .lt("created_at", cutoff.isoformat()) \
            .execute()
        deleted_ids = []
        if old_orders.data:
            for order in old_orders.data:
                supabase.table("orders").delete().eq("id", order["id"]).execute()
                deleted_ids.append(str(order["id"]))
        if deleted_ids:
            bot.reply_to(message, f"🗑 Deleted Orders: {', '.join(deleted_ids)}")
        else:
            bot.reply_to(message, "ℹ️ မဖျက်ရသေးတဲ့ 3 ရက်ထပ်ကျော်သော Done/Error orders မရှိပါ။")
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

# ✅ Block banned user messages
@bot.message_handler(func=lambda m: True, content_types=['text'])
def block_banned_users(message):
    if message.chat.type == "private" and message.from_user.id in banned_user_ids:
        bot.send_message(message.chat.id, "🚫 သင်အား Bot အသုံးပြုခွင့်ပိတ်ထားပါသည်။")
        return
                     
# ✅ Poll new orders
def poll_new_orders():
    global latest_order_id
    while True:
        try:
            orders = supabase.table("orders").select("*").eq("status", "Pending").order("id", desc=True).limit(10).execute()
            if orders.data:
                for order in orders.data:
                    if order['id'] > latest_order_id:
                        latest_order_id = order['id']
                        utc_time = parser.parse(order['created_at'])
                        mm_time = utc_time + timedelta(hours=6, minutes=30)
                        formatted_time = mm_time.strftime("%Y-%m-%d %H:%M")
                        duration = order.get('duration', 'N/A')
                        msg = (
                            f"📦 OrderID: {order['id']}\n\n"
                            f"👤 Email: {order['email']}\n\n"
                            f"🛒 Service: {order['service']}\n"
                            f"🔴 Quantity: {order['quantity']}\n\n"
                            f"📆 Duration: {duration} ရက်\n\n"
                            f"💰 Amount: {order['amount']} Ks\n"
                            f"🔗 Link: {order['link']}\n\n"
                            f"🕧 Order Time - {formatted_time} (MMT)"
                        )
                        bot.send_message(ADMIN_GROUP_ID, msg)
        except Exception as e:
            print("Polling Error:", e)
        time.sleep(5)

# ✅ Main Entry Point
if __name__ == '__main__':
    keep_alive()
    threading.Thread(target=poll_new_orders, daemon=True).start()
    print("🤖 K2 Bot is running...")
    bot.infinity_polling()
