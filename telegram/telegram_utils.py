import re
import html

# ==========================================
# VALIDATORS
# ==========================================

def is_valid_url(url):
    """Validasi format URL dasar."""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    regex = re.compile(
        r'^(?:http|ftp)s?://' 
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|' 
        r'localhost|' 
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})' 
        r'(?::\d+)?' 
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return re.match(regex, url) is not None

def format_url(url):
    """Memastikan URL diawali dengan protokol yang benar."""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url

def parse_chapter_number(text):
    """Mengonversi input teks menjadi float valid untuk chapter, atau None."""
    try:
        return float(text.strip())
    except ValueError:
        return None

def format_chapter_display(num):
    """Menampilkan angka chapter tanpa desimal .0 jika bulat."""
    if num is None:
        return "-"
    if isinstance(num, float) and num.is_integer():
        return str(int(num))
    return f"{num:g}"

# ==========================================
# FORMATTERS
# ==========================================

def escape_html(text):
    """Meloloskan karakter HTML khusus untuk mode parse Telegram HTML."""
    return html.escape(str(text), quote=False)

def format_eta(seconds):
    """Mengubah estimasi detik menjadi format terbaca."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h} Hours {m} Minutes"
    if m > 0:
        return f"{m} Minutes"
    return f"{s} Seconds"

def format_duration(elapsed_seconds):
    """Mengubah durasi detik menjadi string jam/menit/detik yang ringkas."""
    h, rem = divmod(int(elapsed_seconds), 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

def format_status_message(job_state, elapsed):
    """Menyusun string balasan untuk command /status sesuai format."""
    comic_name = job_state["comic_name"]
    current_chapter = job_state["current_chapter"]
    completed = job_state["completed"]
    total = job_state["total"]

    if total == 0:
        return (
            f"📖 <b>Comic</b>\n{escape_html(comic_name)}\n\n"
            f"🔄 <b>Status</b>\nBaru mulai, belum ada data progres chapter.\n\n"
            f"⏱ <b>Elapsed Time</b>\n{format_duration(elapsed)}"
        )

    remaining = max(0, total - completed)
    avg_per_chapter = elapsed / completed if completed else 0
    eta_text = format_eta(avg_per_chapter * remaining)
    
    current_display = format_chapter_display(current_chapter)

    return (
        f"📖 <b>Comic</b>\n{escape_html(comic_name)}\n\n"
        f"🔖 <b>Current Chapter</b>\n{current_display}\n\n"
        f"📊 <b>Completed</b>\n{completed} / {total}\n\n"
        f"⏳ <b>Remaining</b>\n{remaining}\n\n"
        f"🔮 <b>ETA</b>\n{eta_text}\n\n"
        f"⏱ <b>Elapsed Time</b>\n{format_duration(elapsed)}"
    )

# ==========================================
# KEYBOARD BUILDERS
# ==========================================

def build_inline_keyboard(buttons, columns=1):
    """
    Membangun dictionary inline_keyboard Telegram.
    Format input buttons: list of dict -> [{"text": "Tombol 1", "callback_data": "data1"}]
    """
    keyboard = []
    row = []
    for btn in buttons:
        row.append(btn)
        if len(row) == columns:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return {"inline_keyboard": keyboard}