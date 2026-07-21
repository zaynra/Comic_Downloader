import time
import threading

# ==========================================
# CONVERSATION STATES
# ==========================================
STATE_IDLE = "IDLE"
STATE_WAIT_DOWNLOAD_URL = "WAIT_DOWNLOAD_URL"
STATE_WAIT_DOWNLOAD_START = "WAIT_DOWNLOAD_START"
STATE_WAIT_DOWNLOAD_END = "WAIT_DOWNLOAD_END"
STATE_WAIT_DOWNLOAD_CONFIRM = "WAIT_DOWNLOAD_CONFIRM"
STATE_WAIT_CONVERT_COMIC = "WAIT_CONVERT_COMIC"
STATE_WAIT_CONVERT_END = "WAIT_CONVERT_END"
STATE_WAIT_CONVERT_CONFIRM = "WAIT_CONVERT_CONFIRM"

CONVERSATION_TIMEOUT = 300  # 5 Menit Timeout

# user_states dictionary format:
# { "chat_id": {"state": STATE_X, "data": {...}, "timestamp": 123456789} }
user_states = {}
user_states_lock = threading.Lock()

# ==========================================
# JOB STATES (SINGLE JOB PROTECTION)
# ==========================================
job_state_lock = threading.Lock()
job_state = {
    "active": False,
    "url": None,
    "comic_name": None,
    "start_ch": None,
    "end_ch": None,
    "total": 0,
    "completed": 0,
    "success": 0,
    "failed": 0,
    "current_chapter": None,
    "start_time": None,
}

download_thread = None
download_lock = threading.Lock()


def get_user_state(chat_id):
    """Mengambil status percakapan user saat ini beserta datanya."""
    with user_states_lock:
        state_info = user_states.get(chat_id)
        if not state_info:
            return STATE_IDLE, {}
        
        # Evaluasi Timeout
        if time.time() - state_info.get("timestamp", 0) > CONVERSATION_TIMEOUT:
            del user_states[chat_id]
            return STATE_IDLE, {}
        
        return state_info.get("state", STATE_IDLE), state_info.get("data", {})

def set_user_state(chat_id, state, data=None):
    """Menetapkan status percakapan baru untuk user."""
    with user_states_lock:
        if state == STATE_IDLE:
            if chat_id in user_states:
                del user_states[chat_id]
        else:
            user_states[chat_id] = {
                "state": state,
                "data": data or {},
                "timestamp": time.time()
            }

def clear_user_state(chat_id):
    """Membersihkan status percakapan user (kembali ke IDLE)."""
    set_user_state(chat_id, STATE_IDLE)

def update_user_data(chat_id, key, value):
    """Memperbarui kunci spesifik di dalam data percakapan user."""
    with user_states_lock:
        if chat_id in user_states:
            user_states[chat_id]["data"][key] = value
            user_states[chat_id]["timestamp"] = time.time()