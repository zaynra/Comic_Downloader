import requests
import json
import os
import html
from datetime import datetime

CONFIG_FILE = "notification_config.json"


def _fmt_num(n):
    """
    Rapikan angka chapter untuk ditampilkan: 273.0 -> '273', 4.5 -> '4.5'.
    Kalau n bukan angka (mis. nama grup di mode multi-folder-merge, atau
    label chapter non-numerik), kembalikan apa adanya sebagai string.
    """
    try:
        f = float(n)
    except (TypeError, ValueError):
        return str(n)
    if f.is_integer():
        return str(int(f))
    return f"{f:g}"


def _esc(s):
    """Escape karakter HTML supaya judul komik/alasan error tidak merusak formatting Telegram."""
    return html.escape(str(s), quote=False)


class TelegramNotifier:

    def __init__(self):

        self.enabled = False
        self.token = None
        self.chat_id = None

        self.load_config()

    def load_config(self):

        if not os.path.exists(CONFIG_FILE):
            print("Notification config tidak ditemukan")
            return

        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            print(f"Notification config tidak valid: {e}")
            return

        if not config.get("enabled"):
            return

        telegram = config.get("telegram", {})

        self.token = telegram.get("bot_token")
        self.chat_id = telegram.get("chat_id")
        self.enabled = bool(telegram.get("enabled") and self.token and self.chat_id)

        if not self.enabled:
            print("Notifikasi Telegram tidak aktif (cek 'enabled'/'bot_token'/'chat_id' di config).")

    def send(self, message):

        if not self.enabled:
            return

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"

        data = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            response = requests.post(
                url,
                data=data,
                timeout=10
            )
            if response.status_code != 200:
                print("Telegram Error:", response.text)

        except Exception as e:
            print("Telegram Error:", e)

    # ------------------------------------------------------------------
    # NOTIFIKASI: MULAI PROSES
    # ------------------------------------------------------------------
    def start(self, comic, start, end, activity="Download"):

        now = datetime.now().strftime("%H:%M:%S")

        message = (
            f"🚀 <b>{_esc(activity)} Started</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📖 <b>Comic</b>\n"
            f"   {_esc(comic)}\n\n"
            f"📑 <b>Chapter Range</b>\n"
            f"   {_fmt_num(start)} → {_fmt_num(end)}\n\n"
            f"🕐 <b>Time</b>\n"
            f"   {now}"
        )

        self.send(message)

    # ------------------------------------------------------------------
    # NOTIFIKASI: SELESAI PROSES (rekapitulasi)
    # ------------------------------------------------------------------
    def finish(self, comic, total, success, failed, duration, activity="Download"):

        now = datetime.now().strftime("%H:%M:%S")

        rate = (success / total * 100) if total else 0
        status_icon = "🎉" if failed == 0 else "⚠️"
        status_label = "Finished" if failed == 0 else "Finished (with errors)"

        # Progress bar sederhana 10 blok, proporsional terhadap success rate.
        filled = round(rate / 10)
        bar = "▰" * filled + "▱" * (10 - filled)

        message = (
            f"{status_icon} <b>{_esc(activity)} {status_label}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📖 <b>Comic</b>\n"
            f"   {_esc(comic)}\n\n"
            f"📊 <b>Result</b>\n"
            f"   ✅ Success : {success}\n"
            f"   ❌ Failed  : {failed}\n"
            f"   📦 Total   : {total} chapter\n\n"
            f"   {bar}  {rate:.0f}%\n\n"
            f"⏱ <b>Duration</b>\n"
            f"   {duration}\n\n"
            f"🕐 <b>Time</b>\n"
            f"   {now}"
        )

        self.send(message)

    # ------------------------------------------------------------------
    # NOTIFIKASI: ERROR PER-CHAPTER
    # ------------------------------------------------------------------
    def error(self, chapter, reason, activity="Download", comic=None):

        now = datetime.now().strftime("%H:%M:%S")

        comic_line = f"📖 <b>Comic</b>\n   {_esc(comic)}\n\n" if comic else ""

        message = (
            f"❌ <b>{_esc(activity)} Error</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{comic_line}"
            f"📑 <b>Chapter</b>\n"
            f"   {_fmt_num(chapter)}\n\n"
            f"🧾 <b>Reason</b>\n"
            f"   {_esc(reason)}\n\n"
            f"🕐 <b>Time</b>\n"
            f"   {now}"
        )

        self.send(message)