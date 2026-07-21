import time
import traceback
import sys

# Import Arsitektur Internal Telegram
from telegram_config import config, logger
import telegram_api
import telegram_handlers

# Mapping Perintah Langsung ke Handler
COMMAND_HANDLERS = {
    "/start": telegram_handlers.handle_start,
    "/help": telegram_handlers.handle_help,
    "/status": telegram_handlers.handle_status,
    "/download": telegram_handlers.handle_download,
    "/cancel": telegram_handlers.handle_cancel,
    "/convert": telegram_handlers.handle_convert,
}

def dispatch(chat_id, text):
    """Mengarahkan teks mentah ke Command Handler atau Text Router (Wizard)"""
    text = (text or "").strip()
    
    # Deteksi perintah (Command)
    if text.startswith("/"):
        parts = text.split()
        cmd = parts[0].lower()
        if "@" in cmd:
            cmd = cmd.split("@", 1)[0]  # Bersihkan suffix bot
            
        args = parts[1:]
        handler = COMMAND_HANDLERS.get(cmd)
        if handler:
            handler(chat_id, args)
        else:
            telegram_api.send_message(chat_id, "❌ Unknown Command.")
    else:
        # Jika bukan command, arahkan ke Message Router (Untuk State Wizard)
        telegram_handlers.handle_message(chat_id, text)

def main():
    offset = config.load_offset()

    # Pembersihan Backlog (Pesan basi saat Bot mati)
    if offset is None:
        initial_updates = telegram_api.get_updates(0)
        if initial_updates:
            offset = initial_updates[-1]["update_id"] + 1
        else:
            offset = 0
        config.save_offset(offset)
        logger.info(f"First run terdeteksi -- {len(initial_updates)} pesan lama dibersihkan.")

    logger.info("Telegram bot listener started. Menunggu pesan...")

    while True:
        updates = telegram_api.get_updates(offset)

        for update in updates:
            offset = update["update_id"] + 1
            config.save_offset(offset)

            # Route 1: Callback Query (Tombol Inline)
            if "callback_query" in update:
                cb = update["callback_query"]
                chat_id = str(cb.get("message", {}).get("chat", {}).get("id"))
                if chat_id == config.chat_id:
                    telegram_handlers.handle_callback_query(chat_id, cb["id"], cb.get("data", ""))
                continue

            # Route 2: Standard Message
            message = update.get("message") or update.get("edited_message")
            if not message:
                continue

            chat_id = str(message.get("chat", {}).get("id"))
            text = message.get("text", "")

            # Filter Whitelist
            if chat_id != config.chat_id:
                logger.warning(f"Pesan dari chat_id tidak dikenal ({chat_id}), diabaikan.")
                continue

            logger.info(f"Input diterima: {text!r}")
            try:
                # Trigger Indikator Mengetik
                telegram_api.send_chat_action(chat_id, "typing")
                dispatch(chat_id, text)
            except Exception:
                traceback.print_exc()
                telegram_api.send_message(chat_id, "⚠️ Terjadi error internal saat memproses instruksi.")

        time.sleep(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\nProses dihentikan (Ctrl+C). Bot listener keluar dengan bersih.")
        sys.exit(0)