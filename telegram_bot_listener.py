import json
import os
import re
import sys
import time
import shutil
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
STORE_FILE = "bot_store.json"  # favorit, URL terakhir, & settings persisten

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
    "msg_id": None,       # Pesan progres yang di-edit
    "driver_holder": {},  # {'driver': <selenium webdriver>} -- dipakai job_stop
                           # untuk mematikan browser secara langsung supaya
                           # Cancel/Stop benar-benar berhenti, bukan cuma
                           # menunggu chapter yang sedang jalan selesai.
}

job_cancel_event = threading.Event()

DEFAULT_SETTINGS = {
    "auto_convert_pdf": False,   # kalau ON, tombol "✅ Download" otomatis convert ke PDF juga
    "parallel_download": False,  # OFF = 4 worker (aman), ON = 10 worker (lebih cepat, lebih berat)
    "auto_cleanup": True,        # jalankan pembersihan gambar penutup/promosi otomatis
    "notify_download": True,     # kirim notifikasi Telegram terpisah start/finish/error (bot.*)
    "notify_convert": True,
    "notify_error": True,
    "base_dir": "Komik",
}

store_lock = threading.Lock()


def _default_store():
    return {"last_url": None, "favorites": [], "settings": dict(DEFAULT_SETTINGS)}


def load_store():
    with store_lock:
        if not os.path.exists(STORE_FILE):
            return _default_store()
        try:
            with open(STORE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return _default_store()
        base = _default_store()
        base.update({k: v for k, v in data.items() if k in base})
        base["settings"] = {**DEFAULT_SETTINGS, **data.get("settings", {})}
        return base


def save_store(store):
    with store_lock:
        try:
            with open(STORE_FILE, "w", encoding="utf-8") as f:
                json.dump(store, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[WARN] Gagal menyimpan {STORE_FILE}: {e}")


def get_setting(key):
    return load_store()["settings"].get(key, DEFAULT_SETTINGS.get(key))


def set_setting(key, value):
    store = load_store()
    store["settings"][key] = value
    save_store(store)


def set_last_url(url, title):
    store = load_store()
    store["last_url"] = {"url": url, "title": title}
    save_store(store)


def get_last_url():
    return load_store().get("last_url")


def add_favorite(url, title):
    store = load_store()
    favs = store["favorites"]
    if any(f["url"] == url for f in favs):
        return False
    favs.append({"url": url, "title": title})
    store["favorites"] = favs[:50]
    save_store(store)
    return True


def remove_favorite(idx):
    store = load_store()
    favs = store["favorites"]
    if 0 <= idx < len(favs):
        favs.pop(idx)
        store["favorites"] = favs
        save_store(store)
        return True
    return False


def get_favorites():
    return load_store().get("favorites", [])


def is_job_active():
    with job_state_lock:
        return job_state.get("active", False)


def try_activate_job(job_type):
    """Check-and-set ATOMIK untuk job_state['active'], dilindungi
    job_state_lock yang sama dipakai di seluruh modul ini.

    Sebelumnya dispatcher melakukan ini dalam DUA langkah terpisah:
    is_job_active() dulu (baca), baru nanti job_state['active'] = True
    di dalam thread background (tulis) -- dengan jeda di antaranya berupa
    beberapa pemanggilan fungsi + request HTTP (answer_cq) + overhead start
    thread itu sendiri. Kalau user menekan tombol Download/Convert dua kali
    dengan sangat cepat (sebelum thread pertama sempat menulis
    active=True), KEDUA klik bisa membaca active=False dan sama-sama lolos
    -> dua job (dua instance Chrome) jalan bersamaan.

    Fungsi ini menggabungkan baca+tulis jadi satu operasi yang dilindungi
    lock yang sama, dipanggil SEBELUM thread dimulai, sehingga tidak ada
    lagi jeda antara pengecekan dan penguncian slot job.

    Return True kalau slot job berhasil diambil (job_state['active'] baru
    saja diset True oleh pemanggilan ini) -- pemanggil WAJIB memulai thread
    setelah ini, dan WAJIB memanggil release_job_slot() kalau ternyata batal
    (misal validasi input gagal sebelum threading.Thread(...).start()).
    Return False kalau sudah ada job lain yang aktif.
    """
    with job_state_lock:
        if job_state.get("active"):
            return False
        job_state["active"] = True
        job_state["job_type"] = job_type
        return True


def release_job_slot():
    """Lepaskan slot job yang sudah diambil try_activate_job() tapi
    ternyata batal dimulai (mis. URL belum diisi / sesi kadaluarsa),
    supaya job_state tidak 'nyangkut' active=True selamanya padahal tidak
    ada thread yang benar-benar jalan."""
    with job_state_lock:
        job_state["active"] = False


def get_job_type():
    with job_state_lock:
        return job_state.get("job_type")


def log_crash(context, exc):
    err_text = f"[{datetime.now()}] {context}: {exc}\n{traceback.format_exc()}\n"
    print(f"[ERROR] {err_text}")
    try:
        with open(CRASH_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(err_text)
    except Exception:
        pass


# ============================================================
# UI HELPERS & FORMATTING
# ============================================================

def send_or_edit(chat_id, text, reply_markup=None, msg_id=None, state=None):
    data = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)

    try:
        if msg_id:
            edit_data = dict(data)
            edit_data["message_id"] = msg_id
            resp = requests.post(f"{API_URL}/editMessageText", json=edit_data, timeout=10).json()
            if resp.get("ok"):
                return msg_id
            desc = resp.get("description", "")
            if "message is not modified" in desc:
                return msg_id
            print(f"[WARN] editMessageText gagal, kirim pesan baru: {desc}")
        resp = requests.post(f"{API_URL}/sendMessage", json=data, timeout=10).json()
        if resp.get("ok"):
            new_id = resp["result"]["message_id"]
            if state is not None:
                state["msg_id"] = new_id
            return new_id
        print(f"[WARN] sendMessage gagal: {resp}")
    except Exception as e:
        print(f"[ERROR] API Telegram: {e}")
    return None

def answer_cq(cq_id, text="", alert=False):
    if not cq_id:
        return
    try:
        requests.post(
            f"{API_URL}/answerCallbackQuery",
            json={"callback_query_id": cq_id, "text": text, "show_alert": alert},
            timeout=10,
        )
    except Exception as e:
        print(f"[ERROR] answerCallbackQuery gagal: {e}")

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


def _on(flag):
    return "✅ ON" if flag else "⬜ OFF"


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
    st = get_state(chat_id)
    st["state"] = "IDLE"
    if msg_id:
        st["msg_id"] = msg_id
    new_msg_id = send_or_edit(chat_id, text, markup, msg_id, state=st)
    if not msg_id and new_msg_id:
        st["msg_id"] = new_msg_id

def show_download_menu(chat_id, msg_id):
    last = get_last_url()
    last_label = f"📋 Terakhir: {last['title'][:18]}" if last else "📋 URL Terakhir (kosong)"
    fav_count = len(get_favorites())
    fav_label = f"⭐ Favorit ({fav_count})"

    text = format_header("📥 Download Comic") + "Masukkan URL comic yang ingin diunduh.\n\nAtau gunakan pilihan berikut:"
    markup = {
        "inline_keyboard": [
            [{"text": last_label, "callback_data": "dl_last_url"}, {"text": fav_label, "callback_data": "dl_favorites"}],
            [{"text": "⬅️ Kembali", "callback_data": "nav_main"}]
        ]
    }
    st = get_state(chat_id)
    st["state"] = "WAIT_URL"
    if msg_id:
        st["msg_id"] = msg_id
    send_or_edit(chat_id, text, markup, msg_id, state=st)


def show_range_prompt(chat_id, msg_id, data):
    text = format_header("📑 Pilih Range Chapter")
    text += f"Judul\n{data.get('title', '-')}\n\n"
    text += "Ketik salah satu format berikut sebagai pesan:\n"
    text += "  • 12          -> chapter 12 saja\n"
    text += "  • 12-45       -> chapter 12 sampai 45\n"
    text += "  • all         -> semua chapter (default lama)\n\n"
    text += "Atau tekan tombol di bawah untuk langsung ambil semua."
    markup = {
        "inline_keyboard": [
            [{"text": "📦 Semua Chapter", "callback_data": "dl_range_all"}],
            [{"text": "❌ Batal", "callback_data": "nav_main"}]
        ]
    }
    st = get_state(chat_id)
    st["state"] = "WAIT_RANGE"
    st["data"] = data
    if msg_id:
        st["msg_id"] = msg_id
    send_or_edit(chat_id, text, markup, msg_id, state=st)


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
            [{"text": "🔁 Ubah Range", "callback_data": "dl_change_range"}, {"text": "⭐ Simpan Favorit", "callback_data": "dl_fav_add"}],
            [{"text": "⚙️ Advanced", "callback_data": "dl_advanced"}, {"text": "❌ Cancel", "callback_data": "nav_main"}]
        ]
    }
    st = get_state(chat_id)
    if msg_id:
        st["msg_id"] = msg_id
    send_or_edit(chat_id, text, markup, msg_id, state=st)

def show_advanced_download(chat_id, msg_id):
    parallel_on = get_setting("parallel_download")
    text = format_header("Advanced Download") + "Silakan pilih mode download."
    markup = {
        "inline_keyboard": [
            [{"text": "📥 Download Images", "callback_data": "dl_run_standard"}, {"text": "📄 Download PDF", "callback_data": "dl_run_pdf"}],
            [{"text": f"⚡ Parallel Download: {_on(parallel_on)}", "callback_data": "adv_toggle_parallel"}],
            [{"text": "🧹 Bersihkan Cache Junk-Signature", "callback_data": "adv_clear_cache"}],
            [{"text": "⬅️ Back", "callback_data": "nav_download"}]
        ]
    }
    st = get_state(chat_id)
    if msg_id:
        st["msg_id"] = msg_id
    send_or_edit(chat_id, text, markup, msg_id, state=st)

def show_status_menu(chat_id, msg_id):
    with job_state_lock:
        active = job_state["active"]
        job_type = job_state["job_type"]
        completed = job_state["completed"]
        total = job_state["total"]

    text = format_header("📊 Download Status")
    if not active:
        text += "Tidak ada proses yang sedang berjalan.\n\nRunning: 0\nWaiting: 0"
    else:
        bar, percent = build_progress_bar(completed, total)
        text += f"Sistem sedang menjalankan tugas:\nJenis: {job_type}\n{bar} {percent}%\nProgress: {completed}/{total}"

    action_row = [{"text": "⛔ Hentikan Job Aktif", "callback_data": "job_stop"}] if active else \
                 [{"text": "🗑 Bersihkan listener_crash.log", "callback_data": "status_clear_log"}]

    markup = {
        "inline_keyboard": [
            [{"text": "📈 Detail Job", "callback_data": "status_detail"}],
            action_row,
            [{"text": "⬅️ Back", "callback_data": "nav_main"}]
        ]
    }
    st = get_state(chat_id)
    if msg_id:
        st["msg_id"] = msg_id
    send_or_edit(chat_id, text, markup, msg_id, state=st)

def show_library_menu(chat_id, msg_id):
    base_dir = get_setting("base_dir")
    comics = list_downloaded_comics(base_dir)

    if not comics:
        text = format_header("📚 Library") + f"Belum ada komik yang terdownload di folder {base_dir}/."
        markup = {"inline_keyboard": [[{"text": "⬅️ Back", "callback_data": "nav_main"}]]}
        st = get_state(chat_id)
        st["state"] = "IDLE"
        if msg_id:
            st["msg_id"] = msg_id
        send_or_edit(chat_id, text, markup, msg_id, state=st)
        return

    text = format_header("📚 Library") + f"{len(comics)} komik terdownload. Pilih untuk melihat detail:"
    buttons = [
        [{"text": f"📖 {name}", "callback_data": f"lib_pick_{idx}"}]
        for idx, name in enumerate(comics)
    ]
    buttons.append([{"text": "⬅️ Back", "callback_data": "nav_main"}])
    markup = {"inline_keyboard": buttons}

    st = get_state(chat_id)
    st["state"] = "WAIT_LIBRARY_PICK"
    st["data"] = {"comics": comics}
    if msg_id:
        st["msg_id"] = msg_id
    send_or_edit(chat_id, text, markup, msg_id, state=st)


def show_library_detail(chat_id, msg_id, comic_name):
    base_dir = get_setting("base_dir")
    comic_folder = os.path.join(base_dir, comic_name)
    chapter_folders = [
        d for d in os.listdir(comic_folder)
        if os.path.isdir(os.path.join(comic_folder, d)) and d not in converter.OUTPUT_FOLDER_CANDIDATES
    ] if os.path.isdir(comic_folder) else []

    result_dir = converter.get_result_dir(comic_folder) if os.path.isdir(comic_folder) else None
    pdf_count = 0
    if result_dir and os.path.isdir(result_dir):
        pdf_count = len([f for f in os.listdir(result_dir) if f.lower().endswith(".pdf")])

    text = format_header(f"📖 {comic_name}")
    text += f"Chapter (folder gambar)\n{len(chapter_folders)}\n\n"
    text += f"PDF sudah dikonversi\n{pdf_count}"

    markup = {
        "inline_keyboard": [
            [{"text": "🔄 Convert ke PDF", "callback_data": "lib_convert"}],
            [{"text": "🗑 Hapus Komik Ini", "callback_data": "lib_delete_ask"}],
            [{"text": "⬅️ Back", "callback_data": "nav_library"}]
        ]
    }
    send_or_edit(chat_id, text, markup, msg_id)


def show_library_delete_confirm(chat_id, msg_id, comic_name):
    text = format_header("🗑 Hapus Komik") + f"Yakin ingin menghapus SELURUH folder\n{comic_name}\n(gambar + PDF)?\n\nTindakan ini tidak bisa dibatalkan."
    markup = {
        "inline_keyboard": [
            [{"text": "✅ Ya, Hapus", "callback_data": "lib_delete_confirm"}, {"text": "❌ Batal", "callback_data": "lib_delete_cancel"}]
        ]
    }
    send_or_edit(chat_id, text, markup, msg_id)


def show_settings_menu(chat_id, msg_id):
    s = load_store()["settings"]
    text = format_header("⚙️ Settings") + f"Konfigurasi Downloader\n\nFolder Download: {s['base_dir']}/"
    markup = {
        "inline_keyboard": [
            [{"text": f"📄 Auto Convert PDF: {_on(s['auto_convert_pdf'])}", "callback_data": "set_toggle_auto_convert_pdf"}],
            [{"text": f"⚡ Parallel Download: {_on(s['parallel_download'])}", "callback_data": "set_toggle_parallel_download"}],
            [{"text": f"🧹 Auto Cleanup: {_on(s['auto_cleanup'])}", "callback_data": "set_toggle_auto_cleanup"}],
            [{"text": "🔔 Notification", "callback_data": "nav_notification"}],
            [{"text": "⬅️ Back", "callback_data": "nav_main"}]
        ]
    }
    st = get_state(chat_id)
    if msg_id:
        st["msg_id"] = msg_id
    send_or_edit(chat_id, text, markup, msg_id, state=st)

def show_notification_menu(chat_id, msg_id):
    s = load_store()["settings"]
    text = format_header("🔔 Notification")
    text += f"Download Finished\n{_on(s['notify_download'])}\n\n"
    text += f"Convert Finished\n{_on(s['notify_convert'])}\n\n"
    text += f"Error Notification\n{_on(s['notify_error'])}\n\n"
    text += "(Ini mengatur notifikasi Telegram TERPISAH dari pesan progres di bot ini)"
    markup = {
        "inline_keyboard": [
            [{"text": "Toggle Download", "callback_data": "notif_toggle_download"}],
            [{"text": "Toggle Convert", "callback_data": "notif_toggle_convert"}],
            [{"text": "Toggle Error", "callback_data": "notif_toggle_error"}],
            [{"text": "⬅️ Back", "callback_data": "nav_settings"}]
        ]
    }
    st = get_state(chat_id)
    if msg_id:
        st["msg_id"] = msg_id
    send_or_edit(chat_id, text, markup, msg_id, state=st)

def show_exit_menu(chat_id, msg_id):
    text = format_header("👋 Terima Kasih") + "Comic Downloader ditutup.\n\nGunakan /start untuk membuka kembali menu."
    st = get_state(chat_id)
    st["state"] = "EXIT"
    if msg_id:
        st["msg_id"] = msg_id
    send_or_edit(chat_id, text, None, msg_id, state=st)


def show_convert_menu(chat_id, msg_id):
    base_dir = get_setting("base_dir")
    comics = list_downloaded_comics(base_dir)

    if not comics:
        text = format_header("🔄 Convert PDF") + f"Belum ada komik yang terdownload di folder {base_dir}/."
        markup = {"inline_keyboard": [[{"text": "⬅️ Kembali", "callback_data": "nav_main"}]]}
        st = get_state(chat_id)
        st["state"] = "IDLE"
        if msg_id:
            st["msg_id"] = msg_id
        send_or_edit(chat_id, text, markup, msg_id, state=st)
        return

    text = format_header("🔄 Convert PDF") + "Pilih komik yang ingin dikonversi ke PDF:"
    buttons = [
        [{"text": f"📖 {name}", "callback_data": f"cv_pick_{idx}"}]
        for idx, name in enumerate(comics)
    ]
    buttons.append([{"text": "⬅️ Kembali", "callback_data": "nav_main"}])
    markup = {"inline_keyboard": buttons}

    st = get_state(chat_id)
    st["state"] = "WAIT_CONVERT_PICK"
    st["data"] = {"comics": comics}
    if msg_id:
        st["msg_id"] = msg_id
    send_or_edit(chat_id, text, markup, msg_id, state=st)


def show_convert_confirm(chat_id, msg_id, comic_name):
    text = format_header("🔄 Convert PDF")
    text += f"Komik\n{comic_name}\n\nChapter yang belum punya PDF akan dikonversi sekarang."
    markup = {
        "inline_keyboard": [
            [{"text": "✅ Convert Sekarang", "callback_data": "cv_run"}],
            [{"text": "❌ Batal", "callback_data": "nav_convert"}],
        ]
    }
    send_or_edit(chat_id, text, markup, msg_id)


def show_favorites_menu(chat_id, msg_id):
    favs = get_favorites()
    if not favs:
        text = format_header("⭐ Favorit") + "Belum ada favorit tersimpan.\n\nTambahkan lewat tombol \"⭐ Simpan Favorit\" di layar konfirmasi download setelah memasukkan URL."
        markup = {"inline_keyboard": [[{"text": "⬅️ Back", "callback_data": "nav_download"}]]}
        send_or_edit(chat_id, text, markup, msg_id)
        return

    text = format_header("⭐ Favorit") + "Pilih untuk mulai download:"
    buttons = [
        [{"text": f"⭐ {f['title'][:24]}", "callback_data": f"fav_pick_{idx}"},
         {"text": "🗑", "callback_data": f"fav_del_{idx}"}]
        for idx, f in enumerate(favs)
    ]
    buttons.append([{"text": "⬅️ Back", "callback_data": "nav_download"}])
    markup = {"inline_keyboard": buttons}
    send_or_edit(chat_id, text, markup, msg_id)


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
        if chat_id not in user_states:
            user_states[chat_id] = {"state": "IDLE", "msg_id": None, "data": {}}
        return user_states[chat_id]


def _guess_title(url):
    return UniversalComicDownloader._guess_display_name(UniversalComicDownloader._extract_slug(url))


def begin_range_selection(chat_id, msg_id, url, title):
    """Titik masuk bersama untuk 3 sumber URL: ketik manual, URL Terakhir,
    dan Favorit -- semuanya lanjut ke prompt pemilihan range chapter,
    bukan langsung full-range 1-9999 seperti sebelumnya."""
    set_last_url(url, title)
    data = {"url": url, "title": title}
    show_range_prompt(chat_id, msg_id, data)


def handle_url_input(chat_id, url):
    state = get_state(chat_id)
    msg_id = state.get("msg_id")

    if not url.startswith("http"):
        send_or_edit(chat_id, "❌ URL tidak valid. Harus diawali http/https.", msg_id=msg_id)
        time.sleep(2)
        show_download_menu(chat_id, msg_id)
        return

    send_or_edit(chat_id, format_header("Menganalisis URL...") + "Sedang membaca judul...", msg_id=msg_id)

    try:
        title = _guess_title(url)
    except Exception as e:
        log_crash(f"Gagal menganalisis URL: {url}", e)
        send_or_edit(
            chat_id,
            format_header("❌ Gagal Membaca URL") + f"URL:\n{url}\n\nError:\n{e}",
            {"inline_keyboard": [[{"text": "⬅️ Main Menu", "callback_data": "nav_main"}]]},
            msg_id,
        )
        set_state(chat_id, "IDLE")
        return

    begin_range_selection(chat_id, msg_id, url, title)


RANGE_SINGLE = re.compile(r'^\s*(\d+(?:\.\d+)?)\s*$')
RANGE_PAIR = re.compile(r'^\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*$')


def handle_range_input(chat_id, text):
    state = get_state(chat_id)
    msg_id = state.get("msg_id")
    data = state.get("data", {})

    if "url" not in data:
        show_download_menu(chat_id, msg_id)
        return

    low = text.strip().lower()
    if low in ("all", "semua"):
        start, end = 1, 9999
    else:
        m_pair = RANGE_PAIR.match(text)
        m_single = RANGE_SINGLE.match(text)
        if m_pair:
            start, end = float(m_pair.group(1)), float(m_pair.group(2))
            if start > end:
                start, end = end, start
        elif m_single:
            start = end = float(m_single.group(1))
        else:
            send_or_edit(
                chat_id,
                "❌ Format tidak dikenali. Ketik contoh: 12  atau  12-45  atau  all",
                msg_id=msg_id,
            )
            return

    data["start"] = start
    data["end"] = end
    set_state(chat_id, "WAIT_CONFIRM", msg_id=msg_id, data=data)
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

        markup = {"inline_keyboard": [[{"text": "⛔ Stop", "callback_data": "job_stop"}]]}

        if idx % max(1, (total//10)) == 0 or idx == total:
            send_or_edit(chat_id, text, markup, msg_id)

    return _callback

def _run_download_task(chat_id, url, start, end, msg_id, also_convert=False):
    settings = load_store()["settings"]
    also_convert = also_convert or settings["auto_convert_pdf"]
    max_workers = 10 if settings["parallel_download"] else 4

    job_type = "download_pdf" if also_convert else "download"
    driver_holder = {}
    with job_state_lock:
        # NOTE: job_state["active"] SUDAH diset True secara atomik oleh
        # try_activate_job() di dispatcher, SEBELUM thread ini dimulai --
        # lihat penjelasan di definisi try_activate_job(). Baris ini hanya
        # melengkapi field lain (job_type, activity, start_time, dst), bukan
        # lagi titik pertama yang "membuka slot" job.
        job_state.update({
            "active": True, "job_type": job_type, "activity": "Downloading",
            "start_time": time.time(), "msg_id": msg_id,
            "completed": 0, "total": 0, "driver_holder": driver_holder,
        })

    job_cancel_event.clear()
    callback = real_time_progress_callback(chat_id, msg_id)
    downloader = UniversalComicDownloader(max_workers=max_workers)
    title = _guess_title(url)

    try:
        completed_nums = downloader.detect_existing_progress(url, komik_root=settings["base_dir"])
        stats = downloader.run(
            url, start, end, completed_nums=completed_nums,
            progress_callback=callback, send_notifications=settings["notify_download"],
            # notify_on_error sekarang TERPISAH dari notify_download -- dulu
            # notifikasi error per-chapter ikut mati kalau "Download Finished"
            # notif di-OFF-kan, dan toggle "Error Notification" sendiri di
            # menu Notification tidak berpengaruh apa pun. Sekarang keduanya
            # independen sesuai toggle masing-masing.
            notify_on_error=settings["notify_error"],
            cancel_event=job_cancel_event, base_dir=settings["base_dir"],
            auto_cleanup=settings["auto_cleanup"], driver_holder=driver_holder,
        )

        base_folder = os.path.join(settings["base_dir"], title)
        conv_success, conv_failed = None, None

        if also_convert and not job_cancel_event.is_set():
            with job_state_lock:
                job_state["activity"] = "Converting"
            send_or_edit(
                chat_id,
                format_header("🔄 Mengonversi ke PDF...") + f"Komik\n{title}",
                None, msg_id,
            )
            conv_success, conv_failed = _convert_comic_folder(base_folder)

        if stats.get("cancelled"):
            text = format_header("⛔ Download Dihentikan")
            text += f"Judul\n{title}\n\nDihentikan oleh user pada chapter ke-{stats['success'] + stats['failed']}/{stats['total']}."
        else:
            text = format_header("✅ Download Selesai")
            text += f"Judul\n{title}\n\nChapter\n{start} - {end}\n\n"
            text += f"Download -> Berhasil: {stats['success']} | Gagal: {stats['failed']}"
            if conv_success is not None:
                text += f"\nConvert  -> Berhasil: {conv_success} | Gagal: {conv_failed}"

        markup = {
            "inline_keyboard": [
                [{"text": "📄 Convert ke PDF", "callback_data": "nav_convert"}, {"text": "⭐ Simpan Favorit", "callback_data": "stub_fav_from_result"}],
                [{"text": "⬅️ Main Menu", "callback_data": "nav_main"}]
            ]
        }
        send_or_edit(chat_id, text, markup, msg_id)
        set_state(chat_id, "IDLE", data={"url": url, "title": title, "start": start, "end": end})

    except Exception as e:
        log_crash(f"Download task gagal (chat {chat_id}, url {url})", e)
        send_or_edit(
            chat_id,
            format_header("❌ Error") + str(e),
            {"inline_keyboard": [[{"text": "⬅️ Main Menu", "callback_data": "nav_main"}]]},
            msg_id,
        )
    finally:
        with job_state_lock:
            job_state["active"] = False
            job_state["driver_holder"] = {}

def start_download_ui(chat_id, also_convert=False):
    state = get_state(chat_id)
    data = state.get("data", {})
    msg_id = state.get("msg_id")

    if "url" not in data:
        # Slot job sudah diambil try_activate_job() oleh dispatcher sebelum
        # fungsi ini dipanggil, tapi ternyata batal mulai (sesi kadaluarsa) --
        # WAJIB dilepas lagi supaya job_state tidak nyangkut active=True
        # padahal tidak ada thread yang benar-benar berjalan.
        release_job_slot()
        send_or_edit(
            chat_id,
            format_header("❌ Error") + "Sesi kadaluarsa atau URL belum diisi.\nSilakan mulai ulang dari /start.",
            {"inline_keyboard": [[{"text": "⬅️ Main Menu", "callback_data": "nav_main"}]]},
            msg_id,
        )
        set_state(chat_id, "IDLE")
        return

    threading.Thread(
        target=_run_download_task,
        args=(chat_id, data["url"], data.get("start", 1), data.get("end", 9999), msg_id, also_convert),
        daemon=True,
    ).start()


def _convert_comic_folder(comic_folder):
    chapters = converter.scan_chapter_folders(comic_folder)
    result_dir = converter.get_result_dir(comic_folder)
    completed_names = converter.get_completed_chapter_names(result_dir)

    to_convert = [
        c for c in chapters
        if converter.get_chapter_label(os.path.basename(c)) not in completed_names
    ]

    success, failed = 0, 0
    for chapter_dir in to_convert:
        chapter_name = os.path.basename(chapter_dir)
        chapter_label = converter.get_chapter_label(chapter_name)
        output_path = os.path.join(result_dir, converter.format_chapter_pdf_filename(chapter_label))
        if converter.convert_chapter_to_pdf(chapter_dir, output_path):
            success += 1
        else:
            failed += 1

    return success, failed


def _run_convert_task(chat_id, comic_name, msg_id):
    settings = load_store()["settings"]
    with job_state_lock:
        # Sama seperti _run_download_task -- job_state["active"] sudah
        # diset True secara atomik oleh try_activate_job() di dispatcher
        # sebelum thread ini dimulai. Baris ini melengkapi field lainnya.
        job_state.update({
            "active": True, "job_type": "convert", "activity": "Converting",
            "start_time": time.time(), "msg_id": msg_id, "comic_name": comic_name,
            "completed": 0, "total": 0, "driver_holder": {},
        })
    job_cancel_event.clear()

    comic_folder = os.path.join(settings["base_dir"], comic_name)

    try:
        chapters = converter.scan_chapter_folders(comic_folder)
        result_dir = converter.get_result_dir(comic_folder)
        completed_names = converter.get_completed_chapter_names(result_dir)
        to_convert = [
            c for c in chapters
            if converter.get_chapter_label(os.path.basename(c)) not in completed_names
        ]
        total = len(to_convert)

        if total == 0:
            text = format_header("🔄 Convert PDF")
            text += f"Komik\n{comic_name}\n\nSemua chapter sudah punya PDF, tidak ada yang perlu dikonversi."
            send_or_edit(chat_id, text, {"inline_keyboard": [[{"text": "⬅️ Main Menu", "callback_data": "nav_main"}]]}, msg_id)
            set_state(chat_id, "IDLE")
            return

        success, failed = 0, 0
        for idx, chapter_dir in enumerate(to_convert, 1):
            if job_cancel_event.is_set():
                break

            with job_state_lock:
                job_state["completed"] = idx - 1
                job_state["total"] = total

            chapter_name = os.path.basename(chapter_dir)
            chapter_label = converter.get_chapter_label(chapter_name)
            output_path = os.path.join(result_dir, converter.format_chapter_pdf_filename(chapter_label))

            if converter.convert_chapter_to_pdf(chapter_dir, output_path):
                success += 1
            else:
                failed += 1

            bar, percent = build_progress_bar(idx, total)
            text = format_header("🔄 Converting...")
            text += f"{bar}\n{percent}%\n\nChapter {idx}/{total}\nSaat ini: {chapter_name}"
            markup = {"inline_keyboard": [[{"text": "⛔ Stop", "callback_data": "job_stop"}]]}
            if idx % max(1, (total // 10)) == 0 or idx == total:
                send_or_edit(chat_id, text, markup, msg_id)

        if job_cancel_event.is_set():
            text = format_header("⛔ Convert Dihentikan")
            text += f"Komik\n{comic_name}\n\nBerhasil: {success} | Gagal: {failed} (dihentikan sebelum selesai)"
        else:
            text = format_header("✅ Convert Selesai")
            text += f"Komik\n{comic_name}\n\nBerhasil: {success} | Gagal: {failed}"

        if settings["notify_convert"]:
            try:
                bot.finish(comic_name, total, success, failed, "-", activity="Convert")
            except Exception:
                pass

        send_or_edit(chat_id, text, {"inline_keyboard": [[{"text": "⬅️ Main Menu", "callback_data": "nav_main"}]]}, msg_id)
        set_state(chat_id, "IDLE")

    except Exception as e:
        log_crash(f"Convert task gagal (chat {chat_id}, comic {comic_name})", e)
        send_or_edit(
            chat_id,
            format_header("❌ Error") + str(e),
            {"inline_keyboard": [[{"text": "⬅️ Main Menu", "callback_data": "nav_main"}]]},
            msg_id,
        )
    finally:
        with job_state_lock:
            job_state["active"] = False
            job_state["driver_holder"] = {}


def stop_active_job():
    """Cancel SEUTUHNYA: set cancel_event (dicek loop antar-chapter) DAN
    langsung matikan browser Selenium yang sedang jalan (kalau job-nya
    download), supaya operasi yang sedang berlangsung di dalam satu
    chapter (scroll/render halaman) langsung terputus, bukan menunggu
    sampai chapter itu selesai sendiri."""
    job_cancel_event.set()
    with job_state_lock:
        driver = job_state.get("driver_holder", {}).get("driver")
    if driver:
        try:
            driver.quit()
        except Exception:
            pass


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
            answer_cq(cq_id)
            show_convert_menu(chat_id, msg_id)
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

        elif data == "dl_change_range":
            answer_cq(cq_id)
            state = get_state(chat_id)
            show_range_prompt(chat_id, msg_id, state.get("data", {}))

        elif data == "dl_range_all":
            answer_cq(cq_id)
            state = get_state(chat_id)
            d = state.get("data", {})
            d["start"], d["end"] = 1, 9999
            set_state(chat_id, "WAIT_CONFIRM", msg_id=msg_id, data=d)
            show_download_confirm(chat_id, msg_id, d)

        elif data == "dl_fav_add":
            state = get_state(chat_id)
            d = state.get("data", {})
            if "url" in d and add_favorite(d["url"], d.get("title", d["url"])):
                answer_cq(cq_id, "⭐ Ditambahkan ke Favorit.")
            else:
                answer_cq(cq_id, "Sudah ada di Favorit sebelumnya.", True)

        elif data == "dl_run_standard":
            # Check-and-set ATOMIK (lihat try_activate_job) -- menggantikan
            # pola lama is_job_active() (baca) lalu job_state["active"]=True
            # di dalam thread (tulis) yang punya jeda/race window.
            if not try_activate_job("download"):
                answer_cq(cq_id, "⚠️ Proses lain masih berjalan!", True)
            else:
                answer_cq(cq_id, "Memulai Download...")
                start_download_ui(chat_id, also_convert=False)

        elif data == "dl_run_pdf":
            if not try_activate_job("download_pdf"):
                answer_cq(cq_id, "⚠️ Proses lain masih berjalan!", True)
            else:
                answer_cq(cq_id, "Memulai Download + Convert PDF...")
                start_download_ui(chat_id, also_convert=True)

        elif data == "dl_last_url":
            last = get_last_url()
            if not last:
                answer_cq(cq_id, "Belum ada riwayat URL.", True)
                return
            answer_cq(cq_id)
            begin_range_selection(chat_id, msg_id, last["url"], last["title"])

        elif data == "dl_favorites":
            answer_cq(cq_id)
            show_favorites_menu(chat_id, msg_id)

        elif data.startswith("fav_pick_"):
            answer_cq(cq_id)
            favs = get_favorites()
            try:
                idx = int(data.replace("fav_pick_", ""))
            except ValueError:
                idx = -1
            if 0 <= idx < len(favs):
                begin_range_selection(chat_id, msg_id, favs[idx]["url"], favs[idx]["title"])
            else:
                show_favorites_menu(chat_id, msg_id)

        elif data.startswith("fav_del_"):
            try:
                idx = int(data.replace("fav_del_", ""))
            except ValueError:
                idx = -1
            remove_favorite(idx)
            answer_cq(cq_id, "Dihapus dari Favorit.")
            show_favorites_menu(chat_id, msg_id)

        elif data == "adv_toggle_parallel":
            new_val = not get_setting("parallel_download")
            set_setting("parallel_download", new_val)
            answer_cq(cq_id, f"Parallel Download: {'ON' if new_val else 'OFF'}")
            show_advanced_download(chat_id, msg_id)

        elif data == "adv_clear_cache":
            try:
                if os.path.exists("junk_signatures.json"):
                    os.remove("junk_signatures.json")
                answer_cq(cq_id, "Cache junk-signature dibersihkan.")
            except Exception as e:
                answer_cq(cq_id, f"Gagal membersihkan: {e}", True)
            show_advanced_download(chat_id, msg_id)

        elif data.startswith("cv_pick_"):
            answer_cq(cq_id)
            state = get_state(chat_id)
            comics = state.get("data", {}).get("comics", [])
            try:
                idx = int(data.replace("cv_pick_", ""))
            except ValueError:
                idx = -1
            if 0 <= idx < len(comics):
                comic_name = comics[idx]
                set_state(chat_id, "WAIT_CONVERT_CONFIRM", msg_id=msg_id, data={"comics": comics, "selected": comic_name})
                show_convert_confirm(chat_id, msg_id, comic_name)
            else:
                show_convert_menu(chat_id, msg_id)

        elif data == "cv_run":
            state = get_state(chat_id)
            comic_name = state.get("data", {}).get("selected")
            if not comic_name:
                answer_cq(cq_id, "Pilih komik dulu.", True)
                show_convert_menu(chat_id, msg_id)
            elif not try_activate_job("convert"):
                # Check-and-set ATOMIK, sama seperti dl_run_standard/dl_run_pdf
                # di atas -- menutup race window yang sama untuk tombol Convert.
                answer_cq(cq_id, "⚠️ Proses lain masih berjalan!", True)
            else:
                answer_cq(cq_id, "Memulai Convert...")
                threading.Thread(
                    target=_run_convert_task,
                    args=(chat_id, comic_name, msg_id),
                    daemon=True,
                ).start()

        elif data.startswith("lib_pick_"):
            answer_cq(cq_id)
            state = get_state(chat_id)
            comics = state.get("data", {}).get("comics", [])
            try:
                idx = int(data.replace("lib_pick_", ""))
            except ValueError:
                idx = -1
            if 0 <= idx < len(comics):
                comic_name = comics[idx]
                set_state(chat_id, "WAIT_LIBRARY_PICK", msg_id=msg_id, data={"comics": comics, "selected": comic_name})
                show_library_detail(chat_id, msg_id, comic_name)
            else:
                show_library_menu(chat_id, msg_id)

        elif data == "lib_convert":
            answer_cq(cq_id)
            state = get_state(chat_id)
            comic_name = state.get("data", {}).get("selected")
            if comic_name:
                show_convert_confirm(chat_id, msg_id, comic_name)
                set_state(chat_id, "WAIT_CONVERT_CONFIRM", msg_id=msg_id,
                          data={"comics": [comic_name], "selected": comic_name})
            else:
                show_library_menu(chat_id, msg_id)

        elif data == "lib_delete_ask":
            answer_cq(cq_id)
            state = get_state(chat_id)
            comic_name = state.get("data", {}).get("selected")
            if comic_name:
                show_library_delete_confirm(chat_id, msg_id, comic_name)
            else:
                show_library_menu(chat_id, msg_id)

        elif data == "lib_delete_confirm":
            state = get_state(chat_id)
            comic_name = state.get("data", {}).get("selected")
            base_dir = get_setting("base_dir")
            if comic_name:
                try:
                    shutil.rmtree(os.path.join(base_dir, comic_name))
                    answer_cq(cq_id, "🗑 Komik dihapus.")
                except Exception as e:
                    answer_cq(cq_id, f"Gagal menghapus: {e}", True)
            show_library_menu(chat_id, msg_id)

        elif data == "lib_delete_cancel":
            answer_cq(cq_id)
            state = get_state(chat_id)
            comic_name = state.get("data", {}).get("selected")
            show_library_detail(chat_id, msg_id, comic_name)

        elif data == "set_toggle_auto_convert_pdf":
            new_val = not get_setting("auto_convert_pdf")
            set_setting("auto_convert_pdf", new_val)
            answer_cq(cq_id, f"Auto Convert PDF: {'ON' if new_val else 'OFF'}")
            show_settings_menu(chat_id, msg_id)

        elif data == "set_toggle_parallel_download":
            new_val = not get_setting("parallel_download")
            set_setting("parallel_download", new_val)
            answer_cq(cq_id, f"Parallel Download: {'ON' if new_val else 'OFF'}")
            show_settings_menu(chat_id, msg_id)

        elif data == "set_toggle_auto_cleanup":
            new_val = not get_setting("auto_cleanup")
            set_setting("auto_cleanup", new_val)
            answer_cq(cq_id, f"Auto Cleanup: {'ON' if new_val else 'OFF'}")
            show_settings_menu(chat_id, msg_id)

        elif data == "notif_toggle_download":
            new_val = not get_setting("notify_download")
            set_setting("notify_download", new_val)
            answer_cq(cq_id, f"Download Finished notif: {'ON' if new_val else 'OFF'}")
            show_notification_menu(chat_id, msg_id)

        elif data == "notif_toggle_convert":
            new_val = not get_setting("notify_convert")
            set_setting("notify_convert", new_val)
            answer_cq(cq_id, f"Convert Finished notif: {'ON' if new_val else 'OFF'}")
            show_notification_menu(chat_id, msg_id)

        elif data == "notif_toggle_error":
            new_val = not get_setting("notify_error")
            set_setting("notify_error", new_val)
            answer_cq(cq_id, f"Error notif: {'ON' if new_val else 'OFF'}")
            show_notification_menu(chat_id, msg_id)

        elif data == "status_detail":
            with job_state_lock:
                snap = dict(job_state)
            snap.pop("driver_holder", None)
            lines = "\n".join(f"{k}: {v}" for k, v in snap.items() if v is not None)
            answer_cq(cq_id)
            send_or_edit(chat_id, format_header("📈 Detail Job") + (lines or "Tidak ada job aktif."),
                         {"inline_keyboard": [[{"text": "⬅️ Back", "callback_data": "nav_status"}]]}, msg_id)

        elif data == "status_clear_log":
            try:
                if os.path.exists(CRASH_LOG_FILE):
                    os.remove(CRASH_LOG_FILE)
                answer_cq(cq_id, "Log dibersihkan.")
            except Exception as e:
                answer_cq(cq_id, f"Gagal: {e}", True)
            show_status_menu(chat_id, msg_id)

        elif data == "job_stop":
            answer_cq(cq_id, "Menghentikan proses...", True)
            stop_active_job()

        elif data == "stub_fav_from_result":
            state = get_state(chat_id)
            d = state.get("data", {})
            if "url" in d and add_favorite(d["url"], d.get("title", d["url"])):
                answer_cq(cq_id, "⭐ Ditambahkan ke Favorit.")
            else:
                answer_cq(cq_id, "Sudah ada di Favorit / data tidak ditemukan.", True)

        else:
            answer_cq(cq_id, "Perintah tidak dikenali.", True)
        return

    msg = update.get("message")
    if msg:
        chat_id = str(msg["chat"]["id"])
        if chat_id != ALLOWED_CHAT_ID: return
        text = msg.get("text", "").strip()

        try:
            requests.post(f"{API_URL}/deleteMessage", json={"chat_id": chat_id, "message_id": msg["message_id"]}, timeout=5)
        except Exception:
            pass

        if text == "/start":
            show_main_menu(chat_id)
            return

        state = get_state(chat_id).get("state")
        if state == "WAIT_URL":
            handle_url_input(chat_id, text)
        elif state == "WAIT_RANGE":
            handle_range_input(chat_id, text)

# ============================================================
# MAIN LOOP
# ============================================================

def main():
    offset = load_offset() or 0
    print("[INFO] Telegram Bot UI Inline Keyboard Berjalan.")
    try:
        while True:
            try:
                resp = requests.get(
                    f"{API_URL}/getUpdates",
                    params={"offset": offset, "timeout": 30}, timeout=35,
                ).json()
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"[ERROR] getUpdates gagal: {e}")
                time.sleep(2)
                continue

            for update in resp.get("result", []):
                offset = update["update_id"] + 1
                save_offset(offset)
                try:
                    dispatch(update)
                except Exception as e:
                    log_crash(f"dispatch gagal untuk update_id={update.get('update_id')}", e)

            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] Bot dihentikan manual (Ctrl+C).")

if __name__ == "__main__":
    main()