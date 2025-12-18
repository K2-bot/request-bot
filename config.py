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

# Groups
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0")) 
REPORT_GROUP_ID = int(os.getenv("REPORT_GROUP_ID", "0"))
AFFILIATE_GROUP_ID = int(os.getenv("AFFILIATE_GROUP_ID", "0"))
K2BOOST_GROUP_ID = int(os.getenv("K2BOOST_GROUP_ID", "0"))
SUPPLIER_GROUP_ID = int(os.getenv("SUPPLIER_GROUP_ID", "0"))
SUPPORT_GROUP_ID = int(os.getenv("SUPPORT_GROUP_ID", "0"))

# Settings
USD_TO_MMK = 4500
TZ = ZoneInfo("Asia/Yangon")

# Conversation States
WAITING_EMAIL, WAITING_PASSWORD, LOGIN_LANG, LOGIN_CURR = range(4)
ORDER_WAITING_LINK, ORDER_WAITING_QTY, ORDER_CONFIRM, ORDER_WAITING_COMMENTS = range(4, 8) # 🔥 Added ORDER_WAITING_COMMENTS (Index 7)
WAITING_MASS_INPUT, WAITING_MASS_CONFIRM = range(8, 10)
WAITING_SUPPORT_ID = 10
CMD_LANG_SELECT, CMD_CURR_SELECT = range(11, 13)

