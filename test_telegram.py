import json
import os
import sys
import time
import threading
import traceback
from datetime import datetime

import requests

from notification_manager import TelegramNotifier
import convert as converter
from comic_downloader import UniversalComicDownloader, list_downloaded_comics

CONFIG_FILE = "notification_config.json"
OFFSET_FILE = "telegram_listener_offset.txt"
CRASH_LOG_FILE = "listener_crash.log"

# ============================================================
# CONFIG & FONDASI
# ============================================================

def load_telegram_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"[FATAL] {CONFIG_FILE} tidak ditemukan.")
        sys.exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    telegram = config.get("telegram", {})
    return telegram.get("bot_token"), str(telegram.get("chat_id"))

BOT_TOKEN, ALLOWED_CHAT_ID = load_telegram_config()
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

bot = TelegramNotifier()
progress_downloader = UniversalComicDownloader()

# State Management
state_lock = threading.Lock()
user_states = {}  # Format: {chat_id: {"state": "IDLE", "msg_id": 123, "data": {}}}

# Job Status
job_state_lock = threading.Lock()
job_state = {
    "active": False,
    "job_type": None,
    "activity": None,
    "url": None,
    "comic_name": None,
    "start_ch": None,
    "end_ch": None,
    "total": 0,
    "completed": 0,
    "start_time": None,
    "msg_id": None, # Pesan progres yang di-edit
}

job_cancel_event = threading.Event()
download_thread = None
convert_thread = None

# ============================================================
# UI HELPERS & FORMATTING
# ============================================================

def send_or_edit(chat_id, text, reply_markup=None, msg_id=None):
    """Mengirim pesan baru jika msg_id None, atau mengedit jika ada."""
    data = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    
    try:
        if msg_id:
            data["message_id"] = msg_id
            requests.post(f"{API_URL}/editMessageText", json=data, timeout=10)
        else:
            resp = requests.post(f"{API_URL}/sendMessage", json=data, timeout=10).json()
            if resp.get("ok"):
                return resp["result"]["message_id"]
    except Exception as e:
        print(f"[ERROR] API Telegram: {e}")
    return None

def answer_cq(cq_id, text="", alert=False):
    requests.post(f"{API_URL}/answerCallbackQuery", json={"callback_query_id": cq_id, "text": text, "show_alert": alert})

def format_header(title):
    return f"=========================\n{title}\n=========================\n\n"

def build_progress_bar(current, total, length=12):
    if total <= 0: return "░" * length, 0
    percent = current / total
    filled = int(length * percent)
    bar = "█" * filled + "░" * (length - filled)
    return bar, int(percent * 100)

def format_duration(seconds):
    m, s = divmod(max(0, int(seconds)), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def load_offset():
    if os.path.exists(OFFSET_FILE):
        try:
            with open(OFFSET_FILE, "r", encoding="utf-8") as f:
                return int(f.read().strip())
        except Exception:
            return None
    return None

def save_offset(offset):
    try:
        with open(OFFSET_FILE, "w", encoding="utf-8") as f:
            f.write(str(offset))
    except Exception as e:
        print(f"[WARN] Gagal menyimpan offset: {e}")

# ============================================================
# UI MENU RENDERERS
# ============================================================

def show_main_menu(chat_id, msg_id=None):
    text = format_header("📚 Comic Downloader") + "Selamat datang di Comic Downloader.\n\nSilakan pilih menu yang tersedia."
    markup = {
        "inline_keyboard": [
            [{"text": "📥 Download Comic", "callback_data": "nav_download"}, {"text": "🔄 Convert PDF", "callback_data": "nav_convert"}],
            [{"text": "📚 Library", "callback_data": "nav_library"}, {"text": "📊 Status", "callback_data": "nav_status"}],
            [{"text": "⚙️ Settings", "callback_data": "nav_settings"}, {"text": "❌ Exit", "callback_data": "nav_exit"}]
        ]
    }
    set_state(chat_id, "IDLE", msg_id=msg_id)
    new_msg_id = send_or_edit(chat_id, text, markup, msg_id)
    if not msg_id and new_msg_id:
        set_state(chat_id, "IDLE", msg_id=new_msg_id)

def show_download_menu(chat_id, msg_id):
    text = format_header("📥 Download Comic") + "Masukkan URL comic yang ingin diunduh.\n\nAtau gunakan pilihan berikut:"
    markup = {
        "inline_keyboard": [
            [{"text": "📋 URL Terakhir", "callback_data": "dl_last_url"}, {"text": "⭐ Favorit", "callback_data": "dl_favorites"}],
            [{"text": "⬅️ Kembali", "callback_data": "nav_main"}]
        ]
    }
    set_state(chat_id, "WAIT_URL", msg_id=msg_id)
    send_or_edit(chat_id, text, markup, msg_id)

def show_download_confirm(chat_id, msg_id, data):
    url = data.get("url", "Unknown")
    start = data.get("start", 1)
    end = data.get("end", "?")
    
    text = format_header("Comic Download")
    text += f"Judul\n{data.get('title', 'Sedang memuat...')}\n\n"
    text += f"Chapter\n{start} - {end}\n\n"
    text += f"URL\n{url}"

    markup = {
        "inline_keyboard": [
            [{"text": "✅ Download", "callback_data": "dl_run_standard"}, {"text": "📄 Download + PDF", "callback_data": "dl_run_pdf"}],
            [{"text": "⚙️ Advanced", "callback_data": "dl_advanced"}, {"text": "❌ Cancel", "callback_data": "nav_main"}]
        ]
    }
    send_or_edit(chat_id, text, markup, msg_id)

def show_advanced_download(chat_id, msg_id):
    text = format_header("Advanced Download") + "Silakan pilih mode download."
    markup = {
        "inline_keyboard": [
            [{"text": "📥 Download Images", "callback_data": "dl_run_standard"}, {"text": "📄 Download PDF", "callback_data": "dl_run_pdf"}],
            [{"text": "🖼 Download WebP", "callback_data": "stub_alert"}, {"text": "⚡ Parallel Download", "callback_data": "stub_alert"}],
            [{"text": "🧹 Bersihkan Cache", "callback_data": "stub_alert"}],
            [{"text": "⬅️ Back", "callback_data": "nav_download"}]
        ]
    }
    send_or_edit(chat_id, text, markup, msg_id)

def show_status_menu(chat_id, msg_id):
    with job_state_lock:
        active = job_state["active"]
        job_type = job_state["job_type"]
    
    text = format_header("📊 Download Status")
    if not active:
        text += "Tidak ada proses yang sedang berjalan.\n\nQueue: 0 Job\nRunning: 0\nWaiting: 0"
    else:
        text += f"Sistem sedang menjalankan tugas:\nRunning: 1 ({job_type})\nWaiting: 0"

    markup = {
        "inline_keyboard": [
            [{"text": "📋 Queue", "callback_data": "stub_alert"}, {"text": "📈 Detail", "callback_data": "stub_alert"}],
            [{"text": "🧹 Clear Queue", "callback_data": "stub_alert"}],
            [{"text": "⬅️ Back", "callback_data": "nav_main"}]
        ]
    }
    send_or_edit(chat_id, text, markup, msg_id)

def show_library_menu(chat_id, msg_id):
    text = format_header("📚 Library") + "Riwayat Download"
    markup = {
        "inline_keyboard": [
            [{"text": "📄 PDF", "callback_data": "stub_alert"}, {"text": "🖼 Images", "callback_data": "stub_alert"}],
            [{"text": "🗂 Semua", "callback_data": "stub_alert"}, {"text": "🗑 Clear", "callback_data": "stub_alert"}],
            [{"text": "⬅️ Back", "callback_data": "nav_main"}]
        ]
    }
    send_or_edit(chat_id, text, markup, msg_id)

def show_settings_menu(chat_id, msg_id):
    text = format_header("⚙️ Settings") + "Konfigurasi Downloader"
    markup = {
        "inline_keyboard": [
            [{"text": "📂 Folder Download", "callback_data": "stub_alert"}, {"text": "📄 Auto Convert PDF", "callback_data": "stub_alert"}],
            [{"text": "🔔 Notification", "callback_data": "nav_notification"}, {"text": "⚡ Parallel Download", "callback_data": "stub_alert"}],
            [{"text": "🧹 Auto Cleanup", "callback_data": "stub_alert"}],
            [{"text": "⬅️ Back", "callback_data": "nav_main"}]
        ]
    }
    send_or_edit(chat_id, text, markup, msg_id)

def show_notification_menu(chat_id, msg_id):
    text = format_header("🔔 Notification") + "Download Finished\n✅ ON\n\nConvert Finished\n✅ ON\n\nError Notification\n✅ ON"
    markup = {
        "inline_keyboard": [[{"text": "Toggle ON / OFF", "callback_data": "stub_alert"}], [{"text": "⬅️ Back", "callback_data": "nav_settings"}]]
    }
    send_or_edit(chat_id, text, markup, msg_id)

def show_exit_menu(chat_id, msg_id):
    text = format_header("👋 Terima Kasih") + "Comic Downloader ditutup.\n\nGunakan /start untuk membuka kembali menu."
    set_state(chat_id, "EXIT", msg_id=msg_id)
    send_or_edit(chat_id, text, None, msg_id)

# ============================================================
# STATE MANAGEMENT
# ============================================================

def set_state(chat_id, state, msg_id=None, data=None):
    with state_lock:
        current = user_states.get(chat_id, {})
        user_states[chat_id] = {
            "state": state,
            "msg_id": msg_id if msg_id else current.get("msg_id"),
            "data": data if data else current.get("data", {})
        }

def get_state(chat_id):
    with state_lock:
        return user_states.get(chat_id, {"state": "IDLE", "msg_id": None, "data": {}})

def handle_url_input(chat_id, url):
    state = get_state(chat_id)
    msg_id = state.get("msg_id")

    if not url.startswith("http"):
        send_or_edit(chat_id, "❌ URL tidak valid. Harus diawali http/https.", msg_id=msg_id)
        time.sleep(2)
        show_download_menu(chat_id, msg_id)
        return

    send_or_edit(chat_id, format_header("Menganalisis URL...") + "Sedang membaca chapter...", msg_id=msg_id)
    
    title = UniversalComicDownloader._guess_display_name(UniversalComicDownloader._extract_slug(url))
    data = {"url": url, "start": 1, "end": 9999, "title": title}
    
    set_state(chat_id, "WAIT_CONFIRM", data=data)
    show_download_confirm(chat_id, msg_id, data)

# ============================================================
# BACKGROUND JOBS & LIVE PROGRESS
# ============================================================

def real_time_progress_callback(chat_id, msg_id):
    def _callback(idx, total, label, result):
        with job_state_lock:
            job_state["completed"] = idx
            job_state["total"] = total
            elapsed = time.time() - job_state["start_time"]
            speed = (idx / elapsed) if elapsed > 0 else 0
            remaining = total - idx
            eta = format_duration(remaining / speed if speed > 0 else 0)
            
            bar, percent = build_progress_bar(idx, total)
            activity = job_state.get("activity", "Downloading")
            
        text = format_header(f"📥 {activity}...")
        text += f"{bar}\n{percent}%\n\n"
        text += f"Progress\nChapter {idx} / {total}\n\n"
        text += f"Current Chapter\n{label}\n\n"
        text += f"Speed\n{speed:.1f} ch/s\n\n"
        text += f"ETA\n{eta}"

        markup = {"inline_keyboard": [[{"text": "⏸ Pause", "callback_data": "job_pause"}, {"text": "⛔ Stop", "callback_data": "job_stop"}]]}
        
        if idx % max(1, (total//10)) == 0 or idx == total:
            send_or_edit(chat_id, text, markup, msg_id)

    return _callback

def _run_download_task(chat_id, url, start, end, msg_id):
    with job_state_lock:
        job_state.update({"active": True, "job_type": "download", "activity": "Downloading", "start_time": time.time(), "msg_id": msg_id})
    
    job_cancel_event.clear()
    callback = real_time_progress_callback(chat_id, msg_id)
    downloader = UniversalComicDownloader()
    title = UniversalComicDownloader._guess_display_name(UniversalComicDownloader._extract_slug(url))
    
    try:
        completed_nums = downloader.detect_existing_progress(url)
        stats = downloader.run(url, start, end, completed_nums=completed_nums, progress_callback=callback, send_notifications=False, cancel_event=job_cancel_event)
        
        text = format_header("✅ Download Selesai")
        text += f"Judul\n{title}\n\nChapter\n{start} - {end}\n\nStatus\nBerhasil: {stats['success']} | Gagal: {stats['failed']}"
        markup = {
            "inline_keyboard": [
                [{"text": "📄 Convert ke PDF", "callback_data": "stub_alert"}, {"text": "📂 Buka Folder", "callback_data": "stub_alert"}],
                [{"text": "⬅️ Main Menu", "callback_data": "nav_main"}]
            ]
        }
        send_or_edit(chat_id, text, markup, msg_id)
        set_state(chat_id, "IDLE")
        
    except Exception as e:
        send_or_edit(chat_id, format_header("❌ Error") + str(e), {"inline_keyboard": [[{"text": "⬅️ Main Menu", "callback_data": "nav_main"}]]}, msg_id)
    finally:
        with job_state_lock:
            job_state["active"] = False

def start_download_ui(chat_id):
    state = get_state(chat_id)
    data = state.get("data", {})
    msg_id = state.get("msg_id")
    
    if job_state.get("active"):
        answer_cq(None, "Proses lain masih berjalan!", True)
        return

    threading.Thread(target=_run_download_task, args=(chat_id, data["url"], data["start"], data["end"], msg_id), daemon=True).start()

# ============================================================
# DISPATCHER
# ============================================================

def dispatch(update):
    cq = update.get("callback_query")
    if cq:
        chat_id = str(cq["message"]["chat"]["id"])
        if chat_id != ALLOWED_CHAT_ID: return
        msg_id = cq["message"]["message_id"]
        data = cq["data"]
        cq_id = cq["id"]

        if data == "nav_main":
            answer_cq(cq_id)
            show_main_menu(chat_id, msg_id)
        elif data == "nav_download":
            answer_cq(cq_id)
            show_download_menu(chat_id, msg_id)
        elif data == "nav_convert":
            answer_cq(cq_id, "Masuk menu Convert PDF")
        elif data == "nav_library":
            answer_cq(cq_id)
            show_library_menu(chat_id, msg_id)
        elif data == "nav_status":
            answer_cq(cq_id)
            show_status_menu(chat_id, msg_id)
        elif data == "nav_settings":
            answer_cq(cq_id)
            show_settings_menu(chat_id, msg_id)
        elif data == "nav_notification":
            answer_cq(cq_id)
            show_notification_menu(chat_id, msg_id)
        elif data == "nav_exit":
            answer_cq(cq_id)
            show_exit_menu(chat_id, msg_id)
            
        elif data == "dl_advanced":
            answer_cq(cq_id)
            show_advanced_download(chat_id, msg_id)
        elif data == "dl_run_standard":
            answer_cq(cq_id, "Memulai Download...")
            start_download_ui(chat_id)
        
        elif data == "job_stop":
            answer_cq(cq_id, "Menghentikan proses...", True)
            job_cancel_event.set()
        elif data == "job_pause":
            answer_cq(cq_id, "Fitur Pause akan segera hadir", True)
            
        elif data == "stub_alert" or data in ["dl_last_url", "dl_favorites", "dl_run_pdf"]:
            answer_cq(cq_id, "Fitur ini masih dalam tahap pengembangan UI.", True)
        return

    msg = update.get("message")
    if msg:
        chat_id = str(msg["chat"]["id"])
        if chat_id != ALLOWED_CHAT_ID: return
        text = msg.get("text", "").strip()
        
        requests.post(f"{API_URL}/deleteMessage", json={"chat_id": chat_id, "message_id": msg["message_id"]})

        if text == "/start":
            show_main_menu(chat_id)
            return

        state = get_state(chat_id).get("state")
        if state == "WAIT_URL":
            handle_url_input(chat_id, text)

# ============================================================
# MAIN LOOP
# ============================================================

def main():
    offset = load_offset() or 0
    print("[INFO] Telegram Bot UI Inline Keyboard Berjalan.")
    while True:
        try:
            resp = requests.get(f"{API_URL}/getUpdates", params={"offset": offset, "timeout": 30}, timeout=35).json()
            for update in resp.get("result", []):
                offset = update["update_id"] + 1
                save_offset(offset)
                dispatch(update)
        except Exception as e:
            time.sleep(2)
        time.sleep(1)

if __name__ == "__main__":
    main()
