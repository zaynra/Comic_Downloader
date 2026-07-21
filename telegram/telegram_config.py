import json
import os
import sys
import logging

CONFIG_FILE = "notification_config.json"
OFFSET_FILE = "telegram_listener_offset.txt"
CRASH_LOG_FILE = "listener_crash.log"
KOMIK_DIR = "Komik"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("TelegramBot")

class BotConfig:
    def __init__(self):
        self.bot_token = None
        self.chat_id = None
        self.progress_interval = 10
        self.load_config()

    def load_config(self):
        if not os.path.exists(CONFIG_FILE):
            logger.error(f"[FATAL] {CONFIG_FILE} tidak ditemukan.")
            sys.exit(1)

        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config_data = json.load(f)
        except Exception as e:
            logger.error(f"[FATAL] {CONFIG_FILE} tidak valid: {e}")
            sys.exit(1)

        telegram_cfg = config_data.get("telegram", {})
        self.bot_token = telegram_cfg.get("bot_token")
        self.chat_id = str(telegram_cfg.get("chat_id")) if telegram_cfg.get("chat_id") else None

        is_global_enabled = config_data.get("enabled", False)
        is_telegram_enabled = telegram_cfg.get("enabled", False)

        if not (is_global_enabled and is_telegram_enabled and self.bot_token and self.chat_id):
            logger.error(
                "[FATAL] Telegram belum aktif/lengkap di notification_config.json "
                "(pastikan 'enabled' true, dan 'bot_token' serta 'chat_id' terisi)."
            )
            sys.exit(1)

        notification_cfg = config_data.get("notification", {})
        try:
            self.progress_interval = max(1, int(notification_cfg.get("progress_interval", 10)))
        except (ValueError, TypeError):
            self.progress_interval = 10

    def load_offset(self):
        if os.path.exists(OFFSET_FILE):
            try:
                with open(OFFSET_FILE, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    return int(content) if content else None
            except Exception as e:
                logger.warning(f"Gagal membaca offset file: {e}")
                return None
        return None

    def save_offset(self, offset):
        try:
            with open(OFFSET_FILE, "w", encoding="utf-8") as f:
                f.write(str(offset))
        except Exception as e:
            logger.warning(f"Gagal menyimpan offset: {e}")

config = BotConfig()