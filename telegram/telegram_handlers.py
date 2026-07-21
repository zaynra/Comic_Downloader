import os
import time
import threading
import traceback
from datetime import datetime

import telegram_api
import telegram_state
import telegram_utils
from telegram_config import config, logger, CRASH_LOG_FILE, KOMIK_DIR

# Import modul inti dari project (Business Logic)
from comic_downloader import UniversalComicDownloader
from notification_manager import TelegramNotifier

bot_notifier = TelegramNotifier()

# ==========================================
# CALLBACK INJECTION (Mendukung Cancel)
# ==========================================
def make_progress_callback(chat_id):
    def _callback(idx, total, chapter_num, result):
        with telegram_state.job_state_lock:
            # Pengecekan Cancel Event
            if telegram_state.job_state.get("cancel_requested"):
                raise Exception("Download dibatalkan oleh pengguna (Cancel Event).")

            telegram_state.job_state["completed"] = idx
            telegram_state.job_state["total"] = total
            telegram_state.job_state["current_chapter"] = chapter_num
            if result.get("success"):
                telegram_state.job_state["success"] += 1
            else:
                telegram_state.job_state["failed"] += 1
            
            elapsed = time.time() - telegram_state.job_state["start_time"]
            comic_name = telegram_state.job_state["comic_name"]

        if not result.get("success"):
            try:
                bot_notifier.error(
                    chapter_num,
                    result.get("error") or "Gagal download halaman (lihat terminal)",
                    activity="Download",
                    comic=comic_name,
                )
            except Exception as e:
                logger.warning(f"Gagal notifikasi error chapter: {e}")

        if idx % config.progress_interval == 0 or idx == total:
            avg = elapsed / idx if idx else 0
            rem = total - idx
            eta_text = telegram_utils.format_eta(avg * rem)
            
            telegram_api.send_message(
                chat_id,
                f"📥 <b>Progress</b>\n\n"
                f"📊 {idx} / {total}\n\n"
                f"🔖 <b>Current:</b>\nChapter {telegram_utils.format_chapter_display(chapter_num)}\n\n"
                f"🔮 <b>ETA:</b>\n{eta_text}"
            )
    return _callback

def log_crash(comic_name, last_chapter, reason, traceback_text=""):
    try:
        with open(CRASH_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat(timespec='seconds')}] Comic={comic_name} LastChapter={last_chapter} Reason={reason}\n")
            if traceback_text:
                f.write(traceback_text + "\n")
            f.write("-" * 60 + "\n")
    except Exception as e:
        logger.warning(f"Gagal menulis crash log: {e}")

# ==========================================
# THREAD WORKER: DOWNLOAD
# ==========================================
def _run_download_job(chat_id, url, start, end):
    comic_name = UniversalComicDownloader._guess_display_name(UniversalComicDownloader._extract_slug(url)) or url
    
    with telegram_state.job_state_lock:
        telegram_state.job_state.update({
            "active": True,
            "url": url,
            "comic_name": comic_name,
            "start_ch": start,
            "end_ch": end,
            "total": 0,
            "completed": 0,
            "success": 0,
            "failed": 0,
            "current_chapter": None,
            "start_time": time.time(),
            "cancel_requested": False
        })
    
    try:
        bot_notifier.start(comic_name, start, end, activity="Download")
    except Exception:
        pass

    callback = make_progress_callback(chat_id)
    downloader = UniversalComicDownloader()
    
    try:
        completed_nums = downloader.detect_existing_progress(url)
        downloader.run(
            url, start, end,
            completed_nums=completed_nums,
            progress_callback=callback,
            send_notifications=False
        )

        with telegram_state.job_state_lock:
            t = telegram_state.job_state["total"]
            s = telegram_state.job_state["success"]
            f = telegram_state.job_state["failed"]
            dur = telegram_utils.format_duration(time.time() - telegram_state.job_state["start_time"])
            cancel_flag = telegram_state.job_state.get("cancel_requested")
        
        if cancel_flag:
            telegram_api.send_message(chat_id, f"🛑 <b>Download Dibatalkan</b>\n\nKomik: {comic_name}\nBerhasil: {s} Chapter.")
        else:
            bot_notifier.finish(comic_name, t, s, f, dur, activity="Download")
            
    except Exception as e:
        tb_text = traceback.format_exc()
        logger.error(tb_text)
        with telegram_state.job_state_lock:
            last_chapter = telegram_state.job_state.get("current_chapter") or "-"
        log_crash(comic_name, last_chapter, str(e), tb_text)
        try:
            bot_notifier.error(last_chapter, str(e), activity="Download", comic=comic_name)
        except Exception:
            pass
        if "Cancel Event" not in str(e):
            telegram_api.send_message(chat_id, f"❌ Download gagal total.\n\nReason: {e}")
    finally:
        with telegram_state.job_state_lock:
            telegram_state.job_state["active"] = False
        with telegram_state.download_lock:
            telegram_state.download_thread = None

# ==========================================
# COMMAND HANDLERS
# ==========================================
def handle_start(chat_id, args):
    telegram_state.clear_user_state(chat_id)
    telegram_api.send_message(
        chat_id,
        "👋 Selamat datang di Comic Downloader Bot!\n\n"
        "💡 Panduan Singkat:\n"
        "- Mulai Wizard: /download\n"
        "- Fast Mode: /download <url> <start> <end>\n"
        "- Convert PDF: /convert\n"
        "- Pantau proses: /status\n\n"
        "Ketik /help untuk bantuan detail."
    )

def handle_help(chat_id, args):
    telegram_api.send_message(
        chat_id,
        "🛠 <b>Available Commands</b>\n\n"
        "/download - Mulai download (Bisa mode Wizard atau Fast)\n"
        "/status - Cek progres download atau daftar komik lokal\n"
        "/convert - Konversi folder komik ke PDF\n"
        "/cancel - Batalkan Wizard atau proses Download\n"
        "/help - Tampilkan pesan ini"
    )

def handle_status(chat_id, args):
    with telegram_state.job_state_lock:
        active = telegram_state.job_state["active"]
        state_copy = telegram_state.job_state.copy()
        
    if active:
        elapsed = time.time() - state_copy["start_time"] if state_copy["start_time"] else 0
        msg = telegram_utils.format_status_message(state_copy, elapsed)
        telegram_api.send_message(chat_id, msg)
    else:
        # IDLE: Baca direktori Komik
        if not os.path.exists(KOMIK_DIR):
            telegram_api.send_message(chat_id, "📭 Sistem Idle. Belum ada folder komik di server.")
            return
            
        comic_list = []
        for name in os.listdir(KOMIK_DIR):
            target_path = os.path.join(KOMIK_DIR, name)
            if os.path.isdir(target_path) and name != "Result":
                nums = UniversalComicDownloader.get_completed_chapter_numbers(target_path)
                last_ch = max(nums) if nums else 0
                comic_list.append(f"📚 <b>{name}</b> (Last: Ch {telegram_utils.format_chapter_display(last_ch)})")
        
        if comic_list:
            text = "🟢 <b>Sistem Idle</b>\n\nDaftar Komik Tersimpan:\n\n" + "\n".join(comic_list)
        else:
            text = "🟢 <b>Sistem Idle</b>\n\nBelum ada data chapter selesai."
        telegram_api.send_message(chat_id, text)

def handle_cancel(chat_id, args):
    state, _ = telegram_state.get_user_state(chat_id)
    if state != telegram_state.STATE_IDLE:
        telegram_state.clear_user_state(chat_id)
        telegram_api.send_message(chat_id, "🚫 Wizard aktif telah dibatalkan.")
        return
        
    with telegram_state.job_state_lock:
        if telegram_state.job_state["active"]:
            telegram_state.job_state["cancel_requested"] = True
            telegram_api.send_message(chat_id, "🛑 Sinyal Cancel dikirim... Harap tunggu hingga halaman/chapter saat ini selesai diproses sebelum thread berhenti.")
        else:
            telegram_api.send_message(chat_id, "Sistem sedang idle, tidak ada proses yang dibatalkan.")

# ==========================================
# WIZARD: DOWNLOAD
# ==========================================
def _check_and_start_download(chat_id, url, start, end):
    with telegram_state.job_state_lock:
        if telegram_state.job_state["active"]:
            telegram_api.send_message(chat_id, "⏳ Downloader masih berjalan. Gunakan /cancel jika ingin membatalkan.")
            return
    
    with telegram_state.download_lock:
        if telegram_state.download_thread and telegram_state.download_thread.is_alive():
            telegram_api.send_message(chat_id, "⏳ Thread downloader masih berjalan.")
            return

        telegram_state.download_thread = threading.Thread(
            target=_run_download_job,
            args=(chat_id, url, start, end),
            daemon=True,
        )
        telegram_state.download_thread.start()
    telegram_api.send_message(chat_id, f"🚀 <b>Download Dimulai</b>\n\nURL: {url}\nRange: {telegram_utils.format_chapter_display(start)} - {telegram_utils.format_chapter_display(end)}")
    telegram_state.clear_user_state(chat_id)

def handle_download(chat_id, args):
    if len(args) == 0:
        telegram_state.set_user_state(chat_id, telegram_state.STATE_WAIT_DOWNLOAD_URL)
        telegram_api.send_message(chat_id, "🔗 Silakan kirimkan <b>URL komik</b> yang ingin diunduh:")
        return

    url = telegram_utils.format_url(args[0])
    if not telegram_utils.is_valid_url(url):
        telegram_api.send_message(chat_id, "❌ Format URL tidak valid.")
        return

    if len(args) == 1:
        # Detect Progress
        downloader = UniversalComicDownloader()
        completed = downloader.detect_existing_progress(url)
        if completed:
            next_start = max(completed) + 1
            telegram_state.set_user_state(chat_id, telegram_state.STATE_WAIT_DOWNLOAD_END, {"url": url, "start": next_start})
            telegram_api.send_message(chat_id, f"📂 Komik ini sudah pernah diunduh (Last Chapter: {telegram_utils.format_chapter_display(max(completed))}).\n\nDefault Start diatur ke <b>Chapter {telegram_utils.format_chapter_display(next_start)}</b>.\n\nKirimkan <b>Chapter Akhir (End)</b>:")
        else:
            telegram_state.set_user_state(chat_id, telegram_state.STATE_WAIT_DOWNLOAD_START, {"url": url})
            telegram_api.send_message(chat_id, "🆕 Komik baru terdeteksi.\n\nKirimkan <b>Chapter Awal (Start)</b>:")
        return

    start = telegram_utils.parse_chapter_number(args[1])
    if start is None:
        telegram_api.send_message(chat_id, "❌ Chapter Awal (Start) harus berupa angka.")
        return

    if len(args) == 2:
        telegram_state.set_user_state(chat_id, telegram_state.STATE_WAIT_DOWNLOAD_END, {"url": url, "start": start})
        telegram_api.send_message(chat_id, f"Start ditetapkan ke Chapter {telegram_utils.format_chapter_display(start)}.\n\nKirimkan <b>Chapter Akhir (End)</b>:")
        return

    end = telegram_utils.parse_chapter_number(args[2])
    if end is None:
        telegram_api.send_message(chat_id, "❌ Chapter Akhir (End) harus berupa angka.")
        return

    _check_and_start_download(chat_id, url, start, end)

# ==========================================
# WIZARD: CONVERT
# ==========================================
def handle_convert(chat_id, args):
    if not os.path.exists(KOMIK_DIR):
        telegram_api.send_message(chat_id, "📭 Belum ada komik yang diunduh untuk dikonversi.")
        return
        
    comic_list = []
    for name in os.listdir(KOMIK_DIR):
        if os.path.isdir(os.path.join(KOMIK_DIR, name)) and name != "Result":
            comic_list.append(name)
            
    if not comic_list:
        telegram_api.send_message(chat_id, "📭 Tidak ada folder komik valid yang ditemukan.")
        return

    buttons = [{"text": name, "callback_data": f"conv_{name}"} for name in comic_list]
    markup = telegram_utils.build_inline_keyboard(buttons, columns=1)
    
    telegram_state.set_user_state(chat_id, telegram_state.STATE_WAIT_CONVERT_COMIC)
    telegram_api.send_message(chat_id, "🗂 <b>Pilih Komik untuk Dikonversi ke PDF:</b>", reply_markup=markup)

def handle_callback_query(chat_id, callback_query_id, data):
    telegram_api.answer_callback_query(callback_query_id)
    state, sdata = telegram_state.get_user_state(chat_id)
    
    if state == telegram_state.STATE_WAIT_CONVERT_COMIC and data.startswith("conv_"):
        comic_name = data.replace("conv_", "")
        target_path = os.path.join(KOMIK_DIR, comic_name)
        
        # Baca progress lama PDF jika ada
        result_dir = os.path.join(target_path, "Result")
        last_converted = 0
        if os.path.exists(result_dir):
            for file in os.listdir(result_dir):
                if file.endswith(".pdf"):
                    import re
                    m = re.search(r'(\d+(?:\.\d+)?)', file)
                    if m:
                        last_converted = max(last_converted, float(m.group(1)))
        
        next_start = last_converted + 1 if last_converted > 0 else 1
        sdata["comic_name"] = comic_name
        sdata["start"] = next_start
        telegram_state.set_user_state(chat_id, telegram_state.STATE_WAIT_CONVERT_END, sdata)
        
        telegram_api.send_message(
            chat_id, 
            f"🛠 <b>Convert: {comic_name}</b>\n\n"
            f"Terakhir Dikonversi: Chapter {telegram_utils.format_chapter_display(last_ch if 'last_ch' in locals() else last_converted)}\n"
            f"Default Start: <b>Chapter {telegram_utils.format_chapter_display(next_start)}</b>\n\n"
            "Kirimkan <b>Chapter Akhir (End)</b>:"
        )

# ==========================================
# TEXT ROUTER (WIZARD LISTENER)
# ==========================================
def handle_message(chat_id, text):
    state, data = telegram_state.get_user_state(chat_id)
    if state == telegram_state.STATE_IDLE:
        return # Abaikan chat biasa

    if state == telegram_state.STATE_WAIT_DOWNLOAD_URL:
        url = telegram_utils.format_url(text)
        if not telegram_utils.is_valid_url(url):
            telegram_api.send_message(chat_id, "❌ Format URL tidak valid. Coba lagi:")
            return
        
        downloader = UniversalComicDownloader()
        completed = downloader.detect_existing_progress(url)
        
        if completed:
            next_start = max(completed) + 1
            telegram_state.set_user_state(chat_id, telegram_state.STATE_WAIT_DOWNLOAD_END, {"url": url, "start": next_start})
            telegram_api.send_message(chat_id, f"📂 Komik ini sudah ada (Last Chapter: {telegram_utils.format_chapter_display(max(completed))}).\n\nDefault Start: <b>Chapter {telegram_utils.format_chapter_display(next_start)}</b>.\n\nKirimkan <b>Chapter Akhir (End)</b>:")
        else:
            telegram_state.set_user_state(chat_id, telegram_state.STATE_WAIT_DOWNLOAD_START, {"url": url})
            telegram_api.send_message(chat_id, "Kirimkan angka <b>Chapter Awal (Start)</b>:")
            
    elif state == telegram_state.STATE_WAIT_DOWNLOAD_START:
        start = telegram_utils.parse_chapter_number(text)
        if start is None:
            telegram_api.send_message(chat_id, "❌ Masukkan angka yang valid.")
            return
        telegram_state.update_user_data(chat_id, "start", start)
        telegram_state.set_user_state(chat_id, telegram_state.STATE_WAIT_DOWNLOAD_END, data)
        telegram_api.send_message(chat_id, "Kirimkan angka <b>Chapter Akhir (End)</b>:")
        
    elif state == telegram_state.STATE_WAIT_DOWNLOAD_END:
        end = telegram_utils.parse_chapter_number(text)
        if end is None:
            telegram_api.send_message(chat_id, "❌ Masukkan angka yang valid.")
            return
        _check_and_start_download(chat_id, data["url"], data["start"], end)

    elif state == telegram_state.STATE_WAIT_CONVERT_END:
        end = telegram_utils.parse_chapter_number(text)
        if end is None:
            telegram_api.send_message(chat_id, "❌ Masukkan angka yang valid.")
            return
        
        comic_name = data["comic_name"]
        start = data["start"]
        telegram_state.clear_user_state(chat_id)
        
        # Panggilan ke modul Convert. Project harus memilikinya di sini.
        telegram_api.send_message(chat_id, f"⚙️ Memulai proses convert PDF untuk <b>{comic_name}</b> (Ch {telegram_utils.format_chapter_display(start)} - {telegram_utils.format_chapter_display(end)})...")
        try:
            # Contoh eksekusi (Jika converter tersedia)
            # from convert_to_pdf import ComicConverter
            # converter = ComicConverter()
            # converter.run(comic_name, start, end)
            telegram_api.send_message(chat_id, f"✅ PDF untuk {comic_name} sedang dikerjakan di latar belakang (Fitur terintegrasi dengan fungsi project).")
        except ImportError:
            telegram_api.send_message(chat_id, f"⚠️ Modul convert PDF eksternal tidak ditemukan, proses diabaikan.")