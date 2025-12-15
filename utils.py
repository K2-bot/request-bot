import config
import html

TEXTS = {
    'en': {
        'welcome_login': "✅ <b>Login Successful!</b>\nAccount: {email}",
        'select_lang': "Please select your <b>Language</b>:",
        'select_curr': "Please select your <b>Currency</b>:",
        'setup_done': "🎉 <b>Setup Complete!</b>\n\nType /help to start.",
        'balance_low': "⚠️ <b>Insufficient Balance</b>\n\nPlease top up on website: k2boost.org",
        'confirm_order': "❓ <b>Confirm Order?</b>\n\n💵 Cost: {cost}\n✅ Yes to proceed.",
        'order_success': "✅ <b>Order Queued!</b>\nID: {id}\nBalance: {bal}\n\n⚙️ Processing in background...",
        'cancel': "🚫 Action Canceled.",
        'help_title': "👤 <b>Account Info</b>",
        'mass_confirm': "📊 <b>Mass Order Summary</b>\n\n✅ Valid: {valid}\n❌ Invalid: {invalid}\n💵 Total Cost: {cost}\n\nProceed?",
        'help_msg': "📋 <b>Available Commands:</b>\n1️⃣ /services - View Prices\n2️⃣ /neworder - Place Order\n3️⃣ /massorder - Bulk Order\n4️⃣ /history - View History\n5️⃣ /check ID - Check Status\n6️⃣ /support - Ticket/Refill\n7️⃣ /settings - Language/Currency\n\n🌐 Website - k2boost.org"
    },
    'mm': {
        'welcome_login': "✅ <b>Login ဝင်ခြင်း အောင်မြင်ပါသည်</b>\nအကောင့်: {email}",
        'select_lang': "<b>ဘာသာစကား</b> ရွေးချယ်ပါ:",
        'select_curr': "<b>ငွေကြေး</b> အမျိုးအစား ရွေးချယ်ပါ:",
        'setup_done': "🎉 <b>ပြင်ဆင်မှု ပြီးစီးပါပြီ!</b>",
        'balance_low': "⚠️ <b>လက်ကျန်ငွေ မလုံလောက်ပါ</b>\n\nWebsite တွင် ငွေဖြည့်ပါ: k2boost.org",
        'confirm_order': "❓ <b>အော်ဒါတင်ရန် သေချာပါသလား?</b>\n\n💵 ကျသင့်ငွေ: {cost}\n✅ Yes ကိုနှိပ်၍ ဆက်သွားပါ။",
        'order_success': "✅ <b>အော်ဒါ လက်ခံရရှိပါသည်!</b>\nID: {id}\nလက်ကျန်: {bal}\n\n⚙️ နောက်ကွယ်တွင် ဆက်လက်ဆောင်ရွက်နေပါပြီ...",
        'cancel': "🚫 မလုပ်တော့ပါ။",
        'help_title': "👤 <b>အကောင့် အချက်အလက်</b>",
        'mass_confirm': "📊 <b>Mass Order အကျဉ်းချုပ်</b>\n\n✅ အောင်မြင်: {valid}\n❌ မှားယွင်း: {invalid}\n💵 စုစုပေါင်း: {cost}\n\nအော်ဒါတင်မှာ သေချာပါသလား?",
        'help_msg': (
            "📋 <b>အသုံးပြုနိုင်သော Commands:</b>\n"
            "1️⃣ /services - ဈေးနှုန်းကြည့်ရန်\n"
            "2️⃣ /neworder - မှာယူရန်\n"
            "3️⃣ /massorder - အများကြီးမှာရန်\n"
            "4️⃣ /history - မှတ်တမ်းကြည့်ရန်\n"
            "5️⃣ /check ID - Status စစ်ရန်\n"
            "6️⃣ /support - အကူအညီတောင်းရန်\n"
            "7️⃣ /settings - ပြင်ဆင်ရန် (Lang/Curr)\n\n"
            "🌐 Website - k2boost.org\n"
            "@k2boostservice\n"
            "https://t.me/k2_boost"
        )
    }
}

def get_text(lang, key, **kwargs):
    lang_code = lang if lang in ['en', 'mm'] else 'en'
    return TEXTS[lang_code].get(key, key).format(**kwargs)

def format_currency(amount, currency):
    if currency == 'MMK': return f"{amount * config.USD_TO_MMK:,.0f} Ks"
    return f"${amount:.4f}"

def calculate_cost(quantity, service_data):
    per_qty = int(service_data.get('per_quantity', 1000))
    if per_qty == 0: per_qty = 1000
    sell_price = float(service_data.get('sell_price', 0))
    return (quantity / per_qty) * sell_price

def format_for_user(service, lang='en', curr='USD'):
    name = html.escape(service.get('service_name', 'Unknown'))
    price_usd = float(service.get('sell_price', 0))
    min_q = service.get('min', 0)
    max_q = service.get('max', 0)
    per_qty = service.get('per_quantity', 1000)
    raw_note = service.get('note_mm') if lang == 'mm' else service.get('note_eng')
    desc = html.escape((raw_note or "").replace("\\n", "\n").strip())
    price_display = format_currency(price_usd, curr)
    
    return (f"✅ <b>Selected Service</b>\n🔥 {name}\n🆔 <b>ID:</b> <code>{service.get('id')}</code>\n"
            f"💵 <b>Price:</b> {price_display} (per {per_qty})\n📉 <b>Limit:</b> {min_q} - {max_q}\n\n📝 <b>Description:</b>\n{desc}")

def parse_smm_support_response(api_response, req_type, local_id):
    text = str(api_response).lower()
    if req_type == 'Refill':
        if 'refill request has been received' in text or 'queued' in text: return "✅ Refill Queued."
        elif 'canceled' in text or 'refunded' in text: return "❌ Order Canceled/Refunded."
        return f"⚠️ {api_response}"
    elif req_type == 'Cancel':
        if 'cancellation queue' in text: return "✅ Cancellation Queued."
        elif 'cannot be canceled' in text: return "❌ Cannot Cancel."
        return f"⚠️ {api_response}"
    return "✅ Sent."
