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

if (strpos($text, "/add") === 0) {
    $parts = explode(" ", $text, 5);

    if (count($parts) < 5) {
        sendMessage($chat_id, "Usage: /add <ServiceID> <Type> <AverageTime> <Note>");
        exit;
    }

    $serviceId   = trim($parts[1]);
    $type        = trim($parts[2]);
    $averageTime = trim($parts[3]); // string text
    $note        = trim($parts[4]); // goes to both Note-MM & Note-ENG

    // Fetch service info from SMMGen
    $api = new Api(getenv("SMMGEN_API_KEY"));
    $services = $api->services();

    $service = null;
    foreach ($services as $s) {
        if ($s->service == $serviceId) {
            $service = $s;
            break;
        }
    }

    if (!$service) {
        sendMessage($chat_id, " Service ID not found in SMMGen API.");
        exit;
    }

    // Prepare values
    $buyPrice  = $service->rate;
    $sellPrice = $buyPrice; //  Sell = Buy

    // Insert into DB
    $stmt = $pdo->prepare("
        INSERT INTO services 
        (service_id, type, category, service_name, min, max, average_time, buy_price, sell_price, note_mm, note_eng, total_sold_qty)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ");

    $stmt->execute([
        $service->service,
        $type,
        $service->category ?? '',
        $service->name ?? '',
        $service->min ?? 0,
        $service->max ?? 0,
        $averageTime,    // text field
        $buyPrice,
        $sellPrice,
        $note, // Note-MM
        $note, // Note-ENG
        0
    ]);

    // Build message
    $msg = " <b>Service Added!</b>\n\n".
           "<b>Service ID:</b> {$service->service}\n".
           "<b>Type:</b> {$type}\n".
           "<b>Category:</b> {$service->category}\n".
           "<b>Service Name:</b> {$service->name}\n".
           "<b>Min:</b> {$service->min}\n".
           "<b>Max:</b> {$service->max}\n".
           "<b>Average Time:</b> {$averageTime}\n".
           "<b>Buy Price:</b> {$buyPrice}\n".
           "<b>Sell Price:</b> {$sellPrice}\n".
           "<b>Note:</b> {$note}";

    //  Send to Group from .env
    sendMessage(getenv("GROUP_ID"), $msg);

    // Also reply to user who added
    sendMessage($chat_id, " Service added successfully and posted to Group!");
}

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

# === Send Auto Order Message ===
def send_auto_order(order, smmgen_id):
    try:
        msg = bot.send_message(
            FAKE_BOOST_GROUP_ID,
            f"✅ Auto Order တင်ပြီးပါပြီ\n"
            f"📦 OrderID: {order.get('id','N/A')}\n"
            f"🛒 Service: {order.get('service','N/A')}\n"
            f"🔢 Quantity: {order.get('quantity',0)}"
        )

        status_text = (
            f"✅ Order တင်ပြီးပါပြီ\n\n"
            f"📦 OrderID: {order.get('id','N/A')}\n"
            f"🧾 Supplier Service ID: {order.get('service_id','N/A')}\n"
            f"🌐 Supplier Order ID: {smmgen_id}\n"
            f"👤 Email: {order.get('email','N/A')}\n"
            f"🛒 Service: {order.get('service','N/A')}\n"
            f"🔢 Quantity: {order.get('quantity',0)}\n"
            f"🔗 Link: {order.get('link','N/A')}\n"
            f"💰 Paid Amount: {order.get('amount',0)} Ks\n"
            f"💸 Charge: {order.get('charge',0)} $\n"
            f"❓ Status: {order.get('status','Pending')}\n"
            f"⚡️ Start Count: {order.get('start_count',0)}\n"
            f"⏳ Remain: {order.get('remain',0)}"
        )
        bot.send_message(FAKE_BOOST_GROUP_ID, status_text)

        try:
            bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id)
        except Exception as e:
            print(f"Cannot delete message: {e}")

    except Exception as e:
        print(f"Error in send_auto_order: {e}")

# === Send to SMMGEN ===
def send_to_smmgen(order):
    try:
        main_service = order["service_id"]
        main_quantity = int(order["quantity"])
        data = {
            "key": SMMGEN_API_KEY,
            "action": "add",
            "service": main_service,
            "link": order["link"],
            "quantity": main_quantity
        }

        if order.get("comments"):
            data["comments"] = "\n".join(order["comments"]) if isinstance(order["comments"], list) else order["comments"]

        res = requests.post("https://smmgen.com/api/v2", data=data, timeout=15)
        result = res.json()

        if "order" in result:
            smmgen_id = result["order"]

            supabase.table("orders").update({
                "status": "Processing",
                "smmgen_order_id": str(smmgen_id)
            }).eq("id", order["id"]).execute()

            send_auto_order(order, smmgen_id)

            # === Extra Order Logic ===
            extra_service, extra_quantity = None, 0
            if main_service == 14962:  # View → Like
                extra_service, extra_quantity = 9343, max(1, int(main_quantity * 0.1))
            elif main_service == 9343:  # Like → View
                extra_service, extra_quantity = 14961, main_quantity * 10
                if extra_service:extra_res = requests.post(
                    "https://smmgen.com/api/v2",
                    data={
                        "key": SMMGEN_API_KEY,
                        "action": "add",
                        "service": extra_service,
                        "link": order["link"],
                        "quantity": extra_quantity
                    },
                    timeout=15
                ).json()

                if "order" in extra_res:
                    bot.send_message(
                        FAKE_BOOST_GROUP_ID,
                        f"📎 Extra Order တင်ပြီးပါပြီ\n"
                        f"➡️ Main OrderID: {order['id']}\n"
                        f"🧾 Service ID: {extra_service}\n"
                        f"🌐 Extra Supplier Order ID: {extra_res['order']}\n"
                        f"🔢 Quantity: {extra_quantity}\n"
                        f"🔗 Link: {order['link']}\n"
                        f"📌 For: {order.get('service','N/A')} ({main_quantity})"
                    )
                else:
                    bot.send_message(FAKE_BOOST_GROUP_ID, f"❌ Extra Order for {order['id']} Failed:\n{extra_res.get('error','Unknown Error')}")
        else:
            bot.send_message(FAKE_BOOST_GROUP_ID, f"❌ Order {order['id']} Failed:\n{result.get('error','Unknown Error')}")

    except Exception:
        bot.send_message(FAKE_BOOST_GROUP_ID, f"❌ Order {order['id']} Exception:\n{traceback.format_exc()}")

# === Admin Buy Command ===
@bot.message_handler(commands=['Buy'])
def handle_buy(message):
    if message.chat.id != ADMIN_GROUP_ID:
        bot.reply_to(message, "🚫 သင်သည် Buy Command ကို အသုံးပြုရန်ခွင့်မပြုပါ။")
        return

    parts = message.text.split(maxsplit=3)
    if len(parts) != 4:
        bot.reply_to(message, "Usage: /Buy <SMMGEN-ServiceID> <Quantity> <Link>")
        return

    try:
        service_id, quantity, link = int(parts[1]), int(parts[2]), parts[3]
        new_order = {
            "service_id": service_id,
            "quantity": quantity,
            "link": link,
            "status": "Pending",
            "source": "Manual-Buy"
        }
        result = supabase.table("orders").insert(new_order).execute()
        order = result.data[0]

        bot.reply_to(message, f"📦 OrderID {order['id']} created. Submitting to SMMGEN...")
        send_to_smmgen(order)
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# === Block Banned Users ===
@bot.message_handler(func=lambda m: True, content_types=['text'])
def block_banned_users(message):
    if message.chat.type == "private" and message.from_user.id in banned_user_ids:
        bot.send_message(message.chat.id, "🚫 သင်အား Bot အသုံးပြုခွင့်ပိတ်ထားပါသည်။")
        return

# === Poll New Orders ===
def poll_new_orders():
    global latest_order_id
    while True:
        try:
            response = supabase.table("orders") \
                .select("*") \
                .eq("status", "Pending") \
                .gt("id", latest_order_id) \
                .order("id") \
                .limit(20) \
                .execute()
            new_orders = response.data or []
            max_id = latest_order_id

            for order in new_orders:
                order_id = order['id']
                if order_id > max_id:
                    max_id = order_id

                if isinstance(order.get("service_id"), int) and not order.get("smmgen_order_id"):
                    send_to_smmgen(order)
                else:
                    mm_time = parser.parse(order['created_at']) + timedelta(hours=6, minutes=30)
                    msg = (
                        f"📦 OrderID: {order['id']}\n"
                        f"👤 Email: {order['email']}\n"
                        f"🛒 Service: {order['service']}\n"f"🔴 Quantity: {order['quantity']}\n"
                        f"📆 Duration: {order.get('duration', 'N/A')} ရက်\n"
                        f"💰 Amount: {order['amount']} Ks\n"
                        f"🔗 Link: {order['link']}\n"
                        f"🕧 Time: {mm_time.strftime('%Y-%m-%d %H:%M')} (MMT)"
                    )
                    if order.get("comments"):
                        comments_text = "\n".join(order["comments"]) if isinstance(order["comments"], list) else str(order["comments"])
                        msg += f"\n💬 Comments: {comments_text}"
                    bot.send_message(REAL_BOOST_GROUP_ID, msg)

            if max_id > latest_order_id:
                latest_order_id = max_id

            time.sleep(5)
        except Exception as e:
            print("Polling Error:", e)
            traceback.print_exc()
            time.sleep(10)

# === Check SMMGEN Status with Update Only on Change ===
def check_smmgen_status(order):
    try:
        smmgen_id = order.get("smmgen_order_id")
        if not smmgen_id:
            print(f"[WARN] No SMMGEN ID for order {order['id']}, skipping.")
            return

        res = requests.post(
            "https://smmgen.com/api/v2",
            data={"key": SMMGEN_API_KEY, "action": "status", "order": smmgen_id},
            timeout=15
        )
        result = res.json()
        current_status = order.get("status", "Pending")
        smm_status = result.get("status", current_status)

        # ✅ Only update & send message if status changed
        if smm_status != current_status:
    supabase.table("orders").update({
        "start_count": int(result.get("start_count") or 0),
        "remain": int(result.get("remains") or 0),
        "charge": float(result.get("charge") or 0),
        "status": smm_status
    }).eq("id", order["id"]).execute()if            msg = (
                f"📦 OrderID: {order['id']}\n"
                f"🧾 Supplier Service ID: {order.get('service_id','N/A')}\n"
                f"🌐 Supplier Order ID: {smmgen_id}\n"
                f"💰 Paid Amount: {order.get('amount',0)} Ks\n"
                f"💸 Charge: {result.get('charge','0')} $\n"
                f"❓ Status: {smm_status}\n"
                f"⚡️ Start Count: {result.get('start_count','-')}\n"
                f"⏳ Remain: {result.get('remains','-')}"
            )
            bot.send_message(FAKE_BOOST_GROUP_ID, msg)

    except Exception as e:
        print(f"[❌ check_smmgen_status Error] {e}")
        traceback.print_exc()
        bot.send_message(FAKE_BOOST_GROUP_ID, f"❌ Error checking SMMGEN status for Order {order.get('id')}\n{e}")

# === Poll SMMGEN Orders Status ===
def poll_smmgen_orders_status():
    while True:
        try:
            orders = supabase.table("orders").select("*").in_("status", ["Unknown","Processing","Pending","In progress"]).execute().data or []
            for order in orders:
                smmgen_order_id = order.get("smmgen_order_id")
                if smmgen_order_id:
                    check_smmgen_status(order)
            time.sleep(60)
        except Exception:
            print(f"[Polling SMMGEN Error] {traceback.format_exc()}")
            time.sleep(60)

# === Bot Run ===
if __name__ == "__main__":
    from keep_alive import keep_alive
    keep_alive()
    threading.Thread(target=poll_new_orders, daemon=True).start()
    threading.Thread(target=poll_smmgen_orders_status, daemon=True).start()
    print("🤖 K2 Bot is running...")
    bot.infinity_polling()



