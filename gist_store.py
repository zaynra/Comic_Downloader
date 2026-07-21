"""
Gist-based persistence for bot_store.json (favorites, recent URL, settings).
Stores data in a GitHub Gist so it survives across GitHub Actions runs.
"""
import os
import json
import requests

GIST_FILENAME = "comic_bot_store.json"
_gist_id = None


def _get_headers():
    token = os.environ.get("GITHUB_PAT")
    if not token:
        return None
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}


def _find_gist(headers):
    """Cari Gist yang sudah ada dengan filename GIST_FILENAME."""
    resp = requests.get("https://api.github.com/gists", headers=headers, params={"per_page": 100}, timeout=15)
    if resp.status_code != 200:
        return None
    for gist in resp.json():
        if GIST_FILENAME in gist.get("files", {}):
            return gist["id"]
    return None


def load_store(default_store):
    """Load store from Gist. Return default_store if Gist not found or error."""
    global _gist_id
    headers = _get_headers()
    if not headers:
        return default_store

    if not _gist_id:
        _gist_id = _find_gist(headers)

    if not _gist_id:
        return default_store

    try:
        resp = requests.get(f"https://api.github.com/gists/{_gist_id}", headers=headers, timeout=15)
        if resp.status_code == 200:
            content = resp.json()["files"][GIST_FILENAME]["content"]
            data = json.loads(content)
            merged = dict(default_store)
            merged.update({k: v for k, v in data.items() if k in default_store})
            if "settings" in data:
                merged["settings"] = {**default_store.get("settings", {}), **data.get("settings", {})}
            return merged
    except Exception as e:
        print(f"[WARN] Gagal load dari Gist: {e}")
    return default_store


def save_store(store):
    """Save store to Gist. Create Gist if not exists."""
    global _gist_id
    headers = _get_headers()
    if not headers:
        return False

    content = json.dumps(store, indent=2, ensure_ascii=False)
    payload = {
        "description": "Comic Bot Store (favorites, recent URL, settings)",
        "files": {GIST_FILENAME: {"content": content}},
    }

    try:
        if _gist_id:
            resp = requests.patch(f"https://api.github.com/gists/{_gist_id}", headers=headers, json=payload, timeout=15)
        else:
            payload["public"] = False
            resp = requests.post("https://api.github.com/gists", headers=headers, json=payload, timeout=15)
            if resp.status_code in (200, 201):
                _gist_id = resp.json()["id"]
                print(f"[INFO] Gist dibuat: {_gist_id}")

        if resp.status_code in (200, 201):
            return True
        print(f"[WARN] Gagal save ke Gist: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"[WARN] Gagal save ke Gist: {e}")
    return False
