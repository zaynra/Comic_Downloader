"""
Streaming PDF Downloader
========================
Download comic chapter -> convert to PDF immediately -> delete images.
Only PDF files are kept, no image folders remain.

Usage:
    python streaming_pdf_downloader.py <url> [start_ch] [end_ch]

Or import and use:
    from streaming_pdf_downloader import StreamingPDFDownloader
    dl = StreamingPDFDownloader()
    dl.run("https://example.com/comic/title", start_ch=1, end_ch=50)
"""

import os
import sys
import time
import re
import json
import shutil
import tempfile
import threading
import traceback
from datetime import datetime

from comic_downloader import (
    UniversalComicDownloader,
    ComicDownloaderCore,
    resolve_adapter,
    list_downloaded_comics,
)
import convert as converter
from notification_manager import TelegramNotifier

bot = TelegramNotifier()


class StreamingPDFDownloader:
    """Download each chapter, convert to PDF immediately, then delete images."""

    def __init__(self, max_workers=6):
        self.core = ComicDownloaderCore(max_workers=max_workers)
        self._unknown_counter = 0
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def is_cancelled(self):
        return self._cancel_event.is_set()

    def format_chapter_folder(self, chap_num):
        if chap_num is None or chap_num <= 0:
            self._unknown_counter += 1
            return f"Chapter_Unknown_{self._unknown_counter}"
        if float(chap_num).is_integer():
            return f"{int(chap_num):04d}"
        integer_part, _, decimal_part = f"{chap_num:g}".partition('.')
        return f"{int(integer_part):04d}.{decimal_part}"

    def _convert_and_delete(self, chapter_folder, result_dir, chapter_label):
        """Convert a downloaded chapter folder to PDF, then delete the folder.

        Returns (success: bool, output_path: str or None).
        """
        output_name = converter.format_chapter_pdf_filename(chapter_label)
        output_path = os.path.join(result_dir, output_name)

        # Skip if PDF already exists
        if os.path.isfile(output_path):
            print(f"      PDF sudah ada, skip: {output_name}")
            self._cleanup_folder(chapter_folder)
            return True, output_path

        try:
            ok = converter.convert_chapter_to_pdf(chapter_folder, output_path)
            if ok and os.path.isfile(output_path):
                size_mb = os.path.getsize(output_path) / 1048576
                print(f"      PDF tersimpan: {output_name} ({size_mb:.1f} MB)")
                self._cleanup_folder(chapter_folder)
                return True, output_path
            else:
                print(f"      [WARN] Convert gagal untuk {chapter_folder}")
                return False, None
        except Exception as e:
            print(f"      [ERROR] Convert error: {e}")
            return False, None

    def _cleanup_folder(self, folder):
        """Delete chapter folder and all its contents (images)."""
        try:
            if os.path.isdir(folder):
                shutil.rmtree(folder)
        except Exception as e:
            print(f"      [WARN] Gagal hapus folder {folder}: {e}")

    def _get_completed_nums(self, base_folder):
        """Get chapter numbers that already have PDFs in Result/."""
        numbers = set()
        result_dir = os.path.join(base_folder, "Result")
        if os.path.isdir(result_dir):
            for f in os.listdir(result_dir):
                if f.lower().endswith(".pdf"):
                    m = re.search(r'(\d+(?:\.\d+)?)', os.path.splitext(f)[0])
                    if m:
                        numbers.add(float(m.group(1)))
        return numbers

    def run(self, series_url, start_ch=1, end_ch=9999,
            progress_callback=None, send_notifications=True,
            notify_on_error=True, base_dir="Komik"):
        """
        Download chapters one by one. Each chapter is:
        1. Downloaded to a temp folder (with all junk filtering)
        2. Converted to PDF immediately
        3. Images deleted, PDF saved to Result/

        Args:
            series_url: Comic URL
            start_ch: First chapter number
            end_ch: Last chapter number
            progress_callback: fn(chapter_num, total, result_dict) called after each chapter
            send_notifications: Send Telegram start/finish notifications
            notify_on_error: Send Telegram error notifications per chapter
            base_dir: Root folder for comics

        Returns:
            dict with keys: total, success, failed, cancelled, pdfs
        """
        self._cancel_event.clear()
        self._unknown_counter = 0

        adapter = resolve_adapter(self.core, series_url)

        # Get title
        driver = self.core.get_driver(enable_images=False)
        try:
            title = adapter.get_title(driver, series_url)
        finally:
            driver.quit()

        base_folder = os.path.join(base_dir, title)
        os.makedirs(base_folder, exist_ok=True)
        result_dir = converter.get_result_dir(base_folder)

        print(f"[INFO] Mode     : Streaming PDF (download -> convert -> hapus gambar)")
        print(f"[INFO] Judul    : {title}")
        print(f"[INFO] Folder   : {base_folder}")
        print(f"[INFO] PDF Dir  : {result_dir}")
        print(f"[INFO] Range    : {start_ch} - {end_ch}\n")

        # Get chapter list
        driver = self.core.get_driver(enable_images=False)
        try:
            chapters = adapter.get_chapters(driver, series_url)
        finally:
            driver.quit()

        if not chapters:
            print("[ERROR] Tidak ada chapter ditemukan.")
            return {"total": 0, "success": 0, "failed": 0, "cancelled": False, "pdfs": []}

        # Filter to requested range and skip already-converted
        completed_nums = self._get_completed_nums(base_folder)
        to_download = []
        skipped = []

        for url in chapters:
            num = adapter.get_chapter_num(url)
            if num <= 0 or not (start_ch <= num <= end_ch):
                continue
            if num in completed_nums:
                skipped.append(num)
                continue
            to_download.append((num, url))

        # Deduplicate
        seen = set()
        deduped = []
        for num, url in to_download:
            if num not in seen:
                seen.add(num)
                deduped.append((num, url))
        to_download = sorted(deduped, key=lambda x: x[0])

        if skipped:
            preview = ", ".join(f"{n:g}" for n in sorted(skipped)[:10])
            more = f" (+{len(skipped) - 10} lainnya)" if len(skipped) > 10 else ""
            print(f"[INFO] Skip {len(skipped)} chapter sudah ada (PDF): {preview}{more}\n")

        if not to_download:
            print(f"[WARN] Tidak ada chapter baru dalam range {start_ch}-{end_ch}.")
            return {"total": 0, "success": 0, "failed": 0, "cancelled": False, "pdfs": []}

        total = len(to_download)
        print(f"[INFO] Akan mendownload + convert {total} chapter\n")

        if send_notifications:
            try:
                bot.start(title, start_ch, end_ch)
            except Exception:
                pass

        run_start = time.time()
        success_count = 0
        failed_count = 0
        cancelled_flag = False
        pdfs_created = []

        # Shared browser for all chapters (reuse for speed)
        shared_driver = self.core.get_driver(enable_images=True)

        try:
            for idx, (num, url) in enumerate(to_download, 1):
                if self._cancel_event.is_set():
                    print("[INFO] Dibatalkan oleh user.")
                    cancelled_flag = True
                    break

                label = f"{num:g}"
                print(f"[{idx}/{total}] Chapter {label}")

                # --- STEP 1: Download to temp folder ---
                tmp_folder = tempfile.mkdtemp(prefix=f"ch_{label}_")
                try:
                    result = self._download_single_chapter(
                        adapter, url, tmp_folder, shared_driver,
                        auto_cleanup=True, cancel_event=self._cancel_event,
                    )
                except Exception as e:
                    print(f"      [ERROR] Download gagal: {e}")
                    if notify_on_error:
                        try:
                            bot.error(num, str(e))
                        except Exception:
                            pass
                    failed_count += 1
                    self._cleanup_folder(tmp_folder)
                    if progress_callback:
                        progress_callback(num, total, {"success": False, "pages": 0})
                    continue

                if result.get("cancelled"):
                    cancelled_flag = True
                    self._cleanup_folder(tmp_folder)
                    break

                if not result.get("success"):
                    print(f"      [WARN] Download gagal (0 gambar)")
                    failed_count += 1
                    self._cleanup_folder(tmp_folder)
                    if progress_callback:
                        progress_callback(num, total, result)
                    continue

                print(f"      Downloaded: {result['pages']} halaman ({result['size_mb']:.1f} MB)")

                # --- STEP 2: Convert to PDF ---
                chap_folder_name = os.path.basename(tmp_folder)
                # Rename temp folder to proper chapter folder name inside base_folder
                proper_name = self.format_chapter_folder(num)
                proper_folder = os.path.join(base_folder, proper_name)

                # If proper folder already exists (shouldn't, but safety check), use temp name
                if os.path.exists(proper_folder) and os.listdir(proper_folder):
                    proper_folder = tmp_folder
                else:
                    # Move from temp to proper location
                    try:
                        if os.path.exists(proper_folder):
                            shutil.rmtree(proper_folder)
                        shutil.move(tmp_folder, proper_folder)
                        tmp_folder = None  # Don't cleanup since we moved it
                    except Exception as e:
                        print(f"      [WARN] Gagal rename folder: {e}")
                        proper_folder = tmp_folder

                chapter_label = converter.get_chapter_label(proper_name)
                ok, pdf_path = self._convert_and_delete(proper_folder, result_dir, chapter_label)

                if ok:
                    success_count += 1
                    pdfs_created.append(pdf_path)
                else:
                    failed_count += 1

                if progress_callback:
                    progress_callback(num, total, result)

        finally:
            try:
                shared_driver.quit()
            except Exception:
                pass
            # Cleanup any leftover temp folders
            if tmp_folder and os.path.isdir(tmp_folder):
                self._cleanup_folder(tmp_folder)

        elapsed = time.time() - run_start
        mins, secs = divmod(int(elapsed), 60)

        summary = {
            "total": total,
            "success": success_count,
            "failed": failed_count,
            "cancelled": cancelled_flag,
            "pdfs": pdfs_created,
        }

        print(f"\n{'='*50}")
        print(f"Selesai dalam {mins}m {secs}s")
        print(f"Berhasil : {success_count}")
        print(f"Gagal    : {failed_count}")
        print(f"PDF      : {len(pdfs_created)} file")
        print(f"Folder   : {result_dir}")
        print(f"{'='*50}")

        if send_notifications:
            try:
                if cancelled_flag:
                    bot.finish(title, success_count, total)
                elif failed_count == 0:
                    bot.finish(title, success_count, total)
                else:
                    bot.finish(title, success_count, total)
            except Exception:
                pass

        return summary

    def _download_single_chapter(self, adapter, chap_url, dest_folder, driver,
                                  auto_cleanup=True, cancel_event=None):
        """Download a single chapter to dest_folder. Returns result dict.

        This reuses the same junk-filtering logic as UniversalComicDownloader:
        - adapter.get_chapter_images() applies DOM pruning, sequential extraction,
          URL validation, aspect ratio checks, and junk signature filtering.
        - cleanup_chapter_folder() removes trailing junk post-download.
        """
        os.makedirs(dest_folder, exist_ok=True)

        try:
            valid_imgs = adapter.get_chapter_images(driver, chap_url, cancel_event=cancel_event)

            if cancel_event and cancel_event.is_set():
                return {"success": False, "pages": 0, "total": 0, "size_mb": 0.0, "cancelled": True}

            if not valid_imgs:
                return {"success": False, "pages": 0, "total": 0, "size_mb": 0.0}

            # Write manifest
            manifest = [{"page": idx, "url": src} for idx, src in enumerate(valid_imgs, 1)]
            try:
                with open(os.path.join(dest_folder, "chapter_manifest.json"), "w") as f:
                    json.dump(manifest, f, indent=4, ensure_ascii=False)
            except Exception:
                pass

            # Build download tasks
            import urllib.parse
            tasks = []
            for idx, src in enumerate(valid_imgs, 1):
                ext = os.path.splitext(urllib.parse.urlparse(src).path)[1] or '.jpg'
                path = os.path.join(dest_folder, f"{idx:03d}{ext}")
                tasks.append((src, path))

            stats = self.core.download_images(tasks)
            total = len(valid_imgs)

            if stats['ok'] > 0 and auto_cleanup and hasattr(adapter, "cleanup_chapter_folder"):
                try:
                    adapter.cleanup_chapter_folder(dest_folder)
                except Exception:
                    pass

            return {
                "success": stats['ok'] > 0,
                "pages": stats['ok'],
                "total": total,
                "size_mb": stats['size'] / 1048576,
            }

        except Exception:
            return {"success": False, "pages": 0, "total": 0, "size_mb": 0.0}


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python streaming_pdf_downloader.py <url> [start_ch] [end_ch]")
        print("Example: python streaming_pdf_downloader.py https://example.com/comic/my-comic 1 50")
        sys.exit(1)

    url = sys.argv[1]
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    end = int(sys.argv[3]) if len(sys.argv) > 3 else 9999

    dl = StreamingPDFDownloader()
    result = dl.run(url, start_ch=start, end_ch=end)

    print(f"\nResult: {json.dumps(result, indent=2)}")
