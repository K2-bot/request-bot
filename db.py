from supabase import create_client, Client
import config

supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)

def get_user(tg_id):
    res = supabase.table('users').select("*").eq('telegram_id', tg_id).execute()
    return res.data[0] if res.data else None
