import os
import threading
import requests
import time
from telegram.ext import ApplicationBuilder, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
import config
from flask import Flask
import handlers
import jobs

app = Flask(__name__)
@app.route('/')
def home(): return "Bot is running!", 200
def run_flask(): app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

def send_startup_alert():
    time.sleep(2)
    msg = (
        "🚀 **Bot Online!**\n\n"
        "👑 **Admin Commands:**\n\n"
        "📂 **Daily Report Group:**\n"
        "• `/post`, `/ban`, `/swap`, `/Change`\n\n"
        "💰 **Affiliate & Transactions:**\n"
        "• `/Topup`, `/balance`, `/Yes`, `/No`\n\n"
        "📦 **K2Boost Group:**\n"
        "• `/Done`, `/Error`\n\n"
        "🔧 **Support Group:**\n"
        "• `/Reply <ID> <Msg>`"
    )
    try: requests.post(f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage", json={"chat_id": config.REPORT_GROUP_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=jobs.poll_transactions, daemon=True).start()
    threading.Thread(target=jobs.poll_affiliate, daemon=True).start()
    threading.Thread(target=jobs.check_smmgen_rates_loop, daemon=True).start()
    threading.Thread(target=jobs.process_pending_orders_loop, daemon=True).start()
    threading.Thread(target=jobs.smmgen_status_batch_loop, daemon=True).start()
    threading.Thread(target=jobs.poll_supportbox_worker, daemon=True).start()
    threading.Thread(target=jobs.auto_import_services_loop, daemon=True).start()
    threading.Thread(target=send_startup_alert, daemon=True).start()

    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # Handlers (Must import login functions correctly in handlers.py)
    # Ensure handlers.py has all authentication functions defined
    login_h = ConversationHandler(entry_points=[CallbackQueryHandler(handlers.login_start, pattern='^login_flow$')], states={config.WAITING_EMAIL: [MessageHandler(filters.TEXT, handlers.receive_email)], config.WAITING_PASSWORD: [MessageHandler(filters.TEXT, handlers.receive_password)], config.LOGIN_LANG: [CallbackQueryHandler(handlers.login_set_lang)], config.LOGIN_CURR: [CallbackQueryHandler(handlers.login_set_curr)]}, fallbacks=[CommandHandler('cancel', handlers.cancel_op)])
    new_h = ConversationHandler(entry_points=[CommandHandler('neworder', handlers.new_order_start), CommandHandler('start', handlers.new_order_start, filters.Regex('order_'))], states={config.ORDER_WAITING_LINK: [MessageHandler(filters.TEXT, handlers.new_order_link)], config.ORDER_WAITING_QTY: [MessageHandler(filters.TEXT, handlers.new_order_qty)], config.ORDER_CONFIRM: [CallbackQueryHandler(handlers.new_order_confirm)]}, fallbacks=[CommandHandler('cancel', handlers.cancel_op)])
    mass_h = ConversationHandler(entry_points=[CommandHandler('massorder', handlers.mass_start)], states={config.WAITING_MASS_INPUT: [MessageHandler(filters.TEXT, handlers.mass_process)], config.WAITING_MASS_CONFIRM: [CallbackQueryHandler(handlers.mass_confirm)]}, fallbacks=[CommandHandler('cancel', handlers.cancel_op)])
    sup_h = ConversationHandler(entry_points=[CommandHandler('support', handlers.sup_start), CallbackQueryHandler(handlers.sup_process, pattern='^s_')], states={config.WAITING_SUPPORT_ID: [MessageHandler(filters.TEXT, handlers.sup_save)]}, fallbacks=[CommandHandler('cancel', handlers.cancel_op)])
    sett_h = ConversationHandler(entry_points=[CommandHandler('settings', handlers.settings_command), CallbackQueryHandler(handlers.change_lang_start, pattern='^set_lang_start'), CallbackQueryHandler(handlers.change_curr_start, pattern='^set_curr_start')], states={config.CMD_LANG_SELECT: [CallbackQueryHandler(handlers.setting_process)], config.CMD_CURR_SELECT: [CallbackQueryHandler(handlers.setting_process)]}, fallbacks=[CommandHandler('cancel', handlers.cancel_op)])

    app.add_handler(login_h)
    app.add_handler(new_h)
    app.add_handler(mass_h)
    app.add_handler(sup_h)
    app.add_handler(sett_h)
    app.add_handler(CommandHandler('start', handlers.start))
    app.add_handler(CommandHandler('help', handlers.help_command))
    app.add_handler(CommandHandler('check', handlers.check_command))
    app.add_handler(CommandHandler('services', handlers.services_command))
    app.add_handler(CommandHandler('history', handlers.history_command))
    
    app.add_handler(CommandHandler('post', handlers.admin_post))
    app.add_handler(CommandHandler('ban', handlers.admin_ban))
    app.add_handler(CommandHandler('swap', handlers.admin_swap_id))
    app.add_handler(CommandHandler('Change', handlers.admin_change_attr))
    app.add_handler(CommandHandler('Yes', handlers.admin_tx_approve))
    app.add_handler(CommandHandler('No', handlers.admin_tx_reject))
    app.add_handler(CommandHandler('Accept', handlers.admin_aff_accept))
    app.add_handler(CommandHandler('balance', handlers.admin_check_balance))
    app.add_handler(CommandHandler('Topup', handlers.admin_manual_topup))
    app.add_handler(CommandHandler('Done', handlers.admin_order_done))
    app.add_handler(CommandHandler('Error', handlers.admin_order_error))
    app.add_handler(CommandHandler('Answer', handlers.admin_answer_ticket)) # New Name
    app.add_handler(CommandHandler('Close', handlers.admin_ticket_close))   # New Name

    print("Bot Running...")
    app.run_polling()



