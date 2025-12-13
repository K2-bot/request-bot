import os
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

load_dotenv()

# Keys
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SMM_API_KEY = os.getenv("SMM_API_KEY")
SMM_API_URL = os.getenv("SMMGEN_URL", "https://smmgen.com/api/v2")

# =========================================
# 📢 TELEGRAM GROUPS & CHANNELS SETUP
# =========================================

# 1. Channel (For /post)
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-100xxxxxxxxxx")) 

# 2. Transaction & Affiliate Group
# (ငွေဖြည့်တာ၊ Affiliate Payout တောင်းတာတွေ ဒီကိုပို့မယ်)
AFFILIATE_GROUP_ID = int(os.getenv("AFFILIATE_GROUP_ID", "-100xxxxxxxxxx"))

# 3. Supplier Orders Group
# (SMMGen ဆီ Order ပို့လိုက်တိုင်း ဒီမှာ Log ပြမယ်)
SUPPLIER_GROUP_ID = int(os.getenv("SUPPLIER_GROUP_ID", "-100xxxxxxxxxx"))

# 4. Order Status Group
# (Order Cancel/Refund ဖြစ်ရင် ဒီမှာပြမယ်)
ORDER_LOG_GROUP_ID = int(os.getenv("ORDER_LOG_GROUP_ID", "-100xxxxxxxxxx"))

# 5. Support Group
# (Ticket ဖွင့်ရင် ဒီမှာပြမယ်)
SUPPORT_GROUP_ID = int(os.getenv("SUPPORT_GROUP_ID", "-100xxxxxxxxxx"))

# 6. Report Group
# (Profit report တွေအတွက်)
REPORT_GROUP_ID = int(os.getenv("REPORT_GROUP_ID", "-100xxxxxxxxxx"))

# Admin ID (For private commands if needed, or stick to Group Admin check)
# We use the Groups above to check permissions usually.

# Settings
MMK_RATE = 5000 
TZ = ZoneInfo("Asia/Yangon")

# Conversation States
WAITING_EMAIL, WAITING_PASSWORD, LOGIN_LANG, LOGIN_CURR = range(4)
ORDER_WAITING_LINK, ORDER_WAITING_QTY, ORDER_CONFIRM = range(4, 7)
WAITING_MASS_INPUT, WAITING_MASS_CONFIRM = range(7, 9)
WAITING_SUPPORT_ID = 9
CMD_LANG_SELECT, CMD_CURR_SELECT = range(10, 12)
