"""
Google Drive Upload Module
==========================
Upload PDF files to Google Drive using service account authentication.

Setup:
1. Create a Google Cloud project at https://console.cloud.google.com
2. Enable Google Drive API
3. Create a Service Account and download the JSON key
4. Create a folder on your personal Google Drive
5. Share that folder with the service account email (from the JSON)
6. Set GitHub Secrets:
   - GDRIVE_SA_JSON: base64-encoded service account JSON
   - GDRIVE_FOLDER_ID: the Google Drive folder ID
"""

import os
import json
import base64

SCOPES = ['https://www.googleapis.com/auth/drive.file']

_uploader_instance = None


def get_uploader():
    """Lazy singleton for GDriveUploader."""
    global _uploader_instance
    if _uploader_instance is None:
        _uploader_instance = GDriveUploader()
    return _uploader_instance


class GDriveUploader:
    def __init__(self):
        self.service = None
        self.folder_id = None
        self._initialized = False

    def _init_service(self):
        if self._initialized:
            return True

        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError:
            print("[ERROR] google-api-python-client belum terinstall. Jalankan: pip install google-api-python-client google-auth google-auth-oauthlib")
            return False

        sa_json_b64 = os.environ.get("GDRIVE_SA_JSON", "")
        self.folder_id = os.environ.get("GDRIVE_FOLDER_ID", "")

        if not sa_json_b64:
            print("[ERROR] GDRIVE_SA_JSON environment variable tidak ditemukan.")
            return False

        if not self.folder_id:
            print("[ERROR] GDRIVE_FOLDER_ID environment variable tidak ditemukan.")
            return False

        try:
            sa_info = json.loads(base64.b64decode(sa_json_b64).decode("utf-8"))
            creds = service_account.Credentials.from_service_account_info(sa_info, scopes=SCOPES)
            self.service = build("drive", "v3", credentials=creds)
            self._initialized = True
            print(f"[INFO] Google Drive terhubung. Folder ID: {self.folder_id[:12]}...")
            return True
        except Exception as e:
            print(f"[ERROR] Gagal inisialisasi Google Drive: {e}")
            return False

    def upload_file(self, file_path, subfolder_name=None):
        """Upload file ke Google Drive.

        Args:
            file_path: Path lokal file yang akan di-upload
            subfolder_name: Nama subfolder di dalam folder utama (opsional)

        Returns:
            dict dengan keys: success, file_id, link, name, size_mb
            atau None jika gagal
        """
        if not self._init_service():
            return None

        try:
            from googleapiclient.http import MediaFileUpload
        except ImportError:
            print("[ERROR] google-api-python-client belum terinstall.")
            return None

        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        size_mb = file_size / 1048576

        # Tentukan parent folder
        parent_id = self.folder_id
        if subfolder_name:
            subfolder_id = self._find_or_create_folder(subfolder_name, parent_id)
            if subfolder_id:
                parent_id = subfolder_id

        file_metadata = {
            "name": file_name,
            "parents": [parent_id],
        }

        mime_types = {
            ".pdf": "application/pdf",
            ".cbz": "application/zip",
            ".epub": "application/epub+zip",
        }
        ext = os.path.splitext(file_name)[1].lower()
        mime_type = mime_types.get(ext, "application/octet-stream")

        media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)

        try:
            result = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id, webViewLink",
            ).execute()

            file_id = result.get("id")

            # Buat link shareable
            self.service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
            ).execute()

            link = result.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")

            print(f"[INFO] Upload berhasil: {file_name} ({size_mb:.1f} MB)")
            print(f"[INFO] Link: {link}")

            return {
                "success": True,
                "file_id": file_id,
                "link": link,
                "name": file_name,
                "size_mb": round(size_mb, 1),
            }

        except Exception as e:
            print(f"[ERROR] Upload gagal ({file_name}): {e}")
            return None

    def upload_folder(self, folder_path):
        """Upload semua PDF di folder ke Google Drive.

        Returns:
            List of upload results
        """
        if not self._init_service():
            return []

        results = []
        if not os.path.isdir(folder_path):
            return results

        for file_name in sorted(os.listdir(folder_path)):
            if file_name.lower().endswith(".pdf"):
                file_path = os.path.join(folder_path, file_name)
                result = self.upload_file(file_path)
                if result:
                    results.append(result)

        return results

    def _find_or_create_folder(self, folder_name, parent_id):
        """Cari folder berdasarkan nama di parent_id. Buat jika belum ada."""
        try:
            # Cari folder yang sudah ada
            query = (
                f"'{parent_id}' in parents and "
                f"name='{folder_name}' and "
                f"mimeType='application/vnd.google-apps.folder' and "
                f"trashed=false"
            )
            result = self.service.files().list(q=query, fields="files(id)").execute()
            files = result.get("files", [])
            if files:
                return files[0]["id"]

            # Buat folder baru
            folder_metadata = {
                "name": folder_name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            }
            folder = self.service.files().create(body=folder_metadata, fields="id").execute()
            print(f"[INFO] Folder dibuat di Drive: {folder_name}")
            return folder.get("id")

        except Exception as e:
            print(f"[WARN] Gagal find/create folder '{folder_name}': {e}")
            return parent_id

    def get_storage_info(self):
        """Info storage Drive (untuk debug)."""
        if not self._init_service():
            return None
        try:
            about = self.service.about().get(fields="storageQuota").execute()
            quota = about.get("storageQuota", {})
            used = int(quota.get("usage", 0)) / (1024**3)
            limit = int(quota.get("limit", 0)) / (1024**3)
            return {"used_gb": round(used, 2), "limit_gb": round(limit, 2)}
        except Exception:
            return None
