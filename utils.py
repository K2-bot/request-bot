import config

TEXTS = {
    'en': {
        'welcome_login': "✅ **Login Successful!**\nAccount: {email}",
        'select_lang': "Please select your **Language**:",
        'select_curr': "Please select your **Currency**:",
        'setup_done': "🎉 **Setup Complete!**\n\nType /help to start.",
        'balance_low': "⚠️ **Insufficient Balance**\n\nPlease top up on website: k2boost.org",
        'confirm_order': "❓ **Confirm Order?**\n\n💵 Cost: {cost}\n✅ Yes to proceed.",
        'order_success': "✅ **Order Queued!**\nID: {id}\nBalance: {bal}\n\n⚙️ Processing in background...",
        'cancel': "🚫 Action Canceled.",
        'help_title': "👤 **Account Info**",
        'mass_confirm': "📊 **Mass Order Summary**\n\n✅ Valid: {valid}\n❌ Invalid: {invalid}\n💵 Total Cost: {cost}\n\nProceed?",
        'help_msg': "📋 **Available Commands:**\n1️⃣ /services - View Prices\n2️⃣ /neworder - Place Order\n3️⃣ /massorder - Bulk Order\n4️⃣ /history - View History\n5️⃣ /check <ID> - Check Status\n6️⃣ /support - Ticket/Refill\n7️⃣ /settings - Language/Currency\n\n🌐 Website - k2boost.org"
    },
    'mm': {
        'welcome_login': "✅ **Login ဝင်ခြင်း အောင်မြင်ပါသည်**\nအကောင့်: {email}",
        'select_lang': "**ဘာသာစကား** ရွေးချယ်ပါ:",
        'select_curr': "**ငွေကြေး** အမျိုးအစား ရွေးချယ်ပါ:",
        'setup_done': "🎉 **ပြင်ဆင်မှု ပြီးစီးပါပြီ!**",
        'balance_low': "⚠️ **လက်ကျန်ငွေ မလုံလောက်ပါ**\n\nWebsite တွင် ငွေဖြည့်ပါ: k2boost.org",
        'confirm_order': "❓ **အော်ဒါတင်ရန် သေချာပါသလား?**\n\n💵 ကျသင့်ငွေ: {cost}\n✅ Yes ကိုနှိပ်၍ ဆက်သွားပါ။",
        'order_success': "✅ **အော်ဒါ လက်ခံရရှိပါသည်!**\nID: {id}\nလက်ကျန်: {bal}\n\n⚙️ နောက်ကွယ်တွင် ဆက်လက်ဆောင်ရွက်နေပါပြီ...",
        'cancel': "🚫 မလုပ်တော့ပါ။",
        'help_title': "👤 **အကောင့် အချက်အလက်**",
        'mass_confirm': "📊 **Mass Order အကျဉ်းချုပ်**\n\n✅ အောင်မြင်: {valid}\n❌ မှားယွင်း: {invalid}\n💵 စုစုပေါင်း: {cost}\n\nအော်ဒါတင်မှာ သေချာပါသလား?",
        'help_msg': "📋 **အသုံးပြုနိုင်သော Commands:**\n1️⃣ /services - ဈေးနှုန်းကြည့်ရန်\n2️⃣ /neworder - မှာယူရန်\n3️⃣ /massorder - အများကြီးမှာရန်\n4️⃣ /history - မှတ်တမ်းကြည့်ရန်\n5️⃣ /check <ID> - Status စစ်ရန်\n6️⃣ /support - အကူအညီတောင်းရန်\n7️⃣ /settings - ပြင်ဆင်ရန် (Lang/Curr)\n\n🌐 Website - k2boost.org"
    }
}

def get_text(lang, key, **kwargs):
    lang_code = lang if lang in ['en', 'mm'] else 'en'
    return TEXTS[lang_code].get(key, key).format(**kwargs)

def format_currency(amount, currency):
    if currency == 'MMK': return f"{amount * config.MMK_RATE:,.0f} Ks"
    return f"${amount:.4f}"

def calculate_cost(quantity, service_data):
    per_qty = int(service_data.get('per_quantity', 1000))
    if per_qty == 0: per_qty = 1000
    sell_price = float(service_data.get('sell_price', 0))
    return (quantity / per_qty) * sell_price

def format_for_user(service, lang='en', curr='USD'):
    name = service.get('service_name', 'Unknown')
    price_usd = float(service.get('sell_price', 0))
    min_q = service.get('min', 0)
    max_q = service.get('max', 0)
    per_qty = service.get('per_quantity', 1000)
    raw_note = service.get('note_mm') if lang == 'mm' else service.get('note_eng')
    desc = (raw_note or "").replace("\\n", "\n").strip()
    price_display = format_currency(price_usd, curr)
    return (f"✅ **Selected Service**\n🔥 *{name}*\n🆔 *ID:* `{service.get('id')}`\n"
            f"💵 *Price:* {price_display} (per {per_qty})\n📉 *Limit:* {min_q} - {max_q}\n\n📝 *Description:*\n{desc}")

def parse_smm_support_response(api_response, req_type, local_id):
    text = str(api_response).lower()
    if req_type == 'Refill':
        if 'refill request has been received' in text or 'queued' in text: return "✅ Refill Queued."
        elif 'canceled' in text: return "❌ Order Canceled."
        return f"⚠️ {api_response}"
    elif req_type == 'Cancel':
        if 'cancellation queue' in text: return "✅ Cancellation Queued."
        elif 'cannot be canceled' in text: return "❌ Cannot Cancel."
        return f"⚠️ {api_response}"
    return "✅ Sent."
