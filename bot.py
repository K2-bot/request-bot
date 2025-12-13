import threading
from telegram.ext import ApplicationBuilder, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
import config
from flask import Flask
import handlers
import jobs

app = Flask(__name__)
@app.route('/')
def home(): return "Bot is running!", 200
def run_flask(): app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Start Backend Workers
    threading.Thread(target=jobs.poll_transactions, daemon=True).start()
    threading.Thread(target=jobs.poll_affiliate, daemon=True).start()
    threading.Thread(target=jobs.check_smmgen_rates_loop, daemon=True).start()
    threading.Thread(target=jobs.process_pending_orders_loop, daemon=True).start()
    threading.Thread(target=jobs.smmgen_status_batch_loop, daemon=True).start()
    threading.Thread(target=jobs.poll_supportbox_worker, daemon=True).start()
    threading.Thread(target=jobs.auto_import_services_loop, daemon=True).start()

    # Build Bot
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()
    
    # Handlers Registration
    # ... (Login, NewOrder, MassOrder, Support Handlers - same as before) ...
    # ... (Admin Handlers - same as before) ...
    
    print("Bot Running...")
    app.run_polling()
