import requests
import json
from telegram_config import config, logger

API_URL = f"https://api.telegram.org/bot{config.bot_token}"

def get_updates(offset):
    try:
        resp = requests.get(
            f"{API_URL}/getUpdates",
            params={"offset": offset, "timeout": 30},
            timeout=35,
        )
        resp.raise_for_status()
        return resp.json().get("result", [])
    except requests.exceptions.RequestException as e:
        logger.error(f"Gagal polling Telegram: {e}")
        return []

def send_message(chat_id, text, reply_markup=None, parse_mode="HTML", disable_web_page_preview=True):
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup) if isinstance(reply_markup, dict) else reply_markup

    try:
        resp = requests.post(f"{API_URL}/sendMessage", data=data, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Gagal send_message: {e}")
        return None

def edit_message_text(chat_id, message_id, text, reply_markup=None, parse_mode="HTML", disable_web_page_preview=True):
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup) if isinstance(reply_markup, dict) else reply_markup

    try:
        resp = requests.post(f"{API_URL}/editMessageText", data=data, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Gagal edit_message_text: {e}")
        return None

def delete_message(chat_id, message_id):
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
    }
    try:
        resp = requests.post(f"{API_URL}/deleteMessage", data=data, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Gagal delete_message: {e}")
        return None

def answer_callback_query(callback_query_id, text=None, show_alert=False):
    data = {
        "callback_query_id": callback_query_id,
        "show_alert": show_alert,
    }
    if text:
        data["text"] = text

    try:
        resp = requests.post(f"{API_URL}/answerCallbackQuery", data=data, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Gagal answer_callback_query: {e}")
        return None

def send_chat_action(chat_id, action="typing"):
    data = {
        "chat_id": chat_id,
        "action": action,
    }
    try:
        resp = requests.post(f"{API_URL}/sendChatAction", data=data, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Gagal send_chat_action: {e}")
        return None

def set_my_commands(commands):
    data = {
        "commands": json.dumps(commands)
    }
    try:
        resp = requests.post(
            f"{API_URL}/setMyCommands", 
            headers={"Content-Type": "application/json"}, 
            data=json.dumps(data), 
            timeout=15
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Gagal set_my_commands: {e}")
        return None