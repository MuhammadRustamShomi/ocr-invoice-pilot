"""
Folder Watcher — monitors inbox/ for new invoices and sends them to the API.
"""
import os
import time
import shutil
from datetime import datetime
from pathlib import Path

import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from loguru import logger
from dotenv import load_dotenv
from colorama import Fore, Style, init as colorama_init

load_dotenv()
colorama_init(autoreset=True)

logger.add(
    os.getenv("LOG_FILE", "logs/ocr_pilot.log"),
    rotation="10 MB",
    retention="7 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {module}:{line} | {message}",
)

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf"}
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
API_URL = f"http://{os.getenv('API_HOST', '127.0.0.1')}:{os.getenv('API_PORT', '8000')}"
API_KEY = os.getenv("API_KEY", "ocr-pilot-key-2026")


class InvoiceEventHandler(FileSystemEventHandler):
    def __init__(self, watcher: "InvoiceWatcher"):
        self._watcher = watcher

    def on_created(self, event):
        if not event.is_directory:
            self._watcher.on_new_file(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._watcher.on_new_file(event.dest_path)


class InvoiceWatcher:
    def __init__(
        self,
        inbox: str = None,
        processed: str = None,
        failed: str = None,
        api_url: str = None,
        api_key: str = None,
    ):
        self.inbox = Path(inbox or os.getenv("INBOX_FOLDER", "inbox"))
        self.processed = Path(processed or os.getenv("PROCESSED_FOLDER", "processed"))
        self.failed = Path(failed or os.getenv("FAILED_FOLDER", "failed"))
        self.api_url = api_url or API_URL
        self.api_key = api_key or API_KEY
        self._observer = None
        self._consecutive_failures = 0
        self._in_progress: set = set()  # prevent double-processing same file

        for folder in (self.inbox, self.processed, self.failed):
            folder.mkdir(parents=True, exist_ok=True)

    def start(self) -> None:
        print(f"{Fore.CYAN}Watching {self.inbox}/ for new invoices... Press Ctrl+C to stop{Style.RESET_ALL}")
        logger.info(f"Watcher started | inbox={self.inbox}")

        event_handler = InvoiceEventHandler(self)
        self._observer = Observer()
        self._observer.schedule(event_handler, str(self.inbox), recursive=False)
        self._observer.start()

        # Also poll on startup for files already in inbox
        self._process_existing()

        try:
            while True:
                time.sleep(1)
                # Fallback poll every 5 seconds
                self._process_existing()
                time.sleep(4)
        except KeyboardInterrupt:
            self.stop()

    def _process_existing(self):
        for f in self.inbox.iterdir():
            if f.is_file() and f.suffix.lower() in ALLOWED_EXTENSIONS and f.name != ".gitkeep":
                self.on_new_file(str(f))

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join()
        logger.info("Watcher stopped.")
        print(f"{Fore.YELLOW}Watcher stopped.{Style.RESET_ALL}")

    def on_new_file(self, file_path: str) -> None:
        path = Path(file_path)
        if not path.exists():
            return
        # Skip if already being processed (prevents event + poll double-trigger)
        key = str(path.resolve())
        if key in self._in_progress:
            return
        self._in_progress.add(key)
        try:
            self._handle_file(path)
        finally:
            self._in_progress.discard(key)

    def _handle_file(self, path: Path) -> None:
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            logger.warning(f"Unsupported file type: {path.name} — moving to failed/")
            self._move_file(str(path), str(self.failed))
            self._consecutive_failures += 1
            self._check_consecutive_failures()
            return

        logger.info(f"New file detected: {path.name}")
        print(f"{Fore.CYAN}[DETECTED] {path.name}{Style.RESET_ALL}")

        time.sleep(0.5)  # Wait for file to finish writing

        result = None
        for attempt in range(1, MAX_RETRIES + 1):
            # Each retry uses a more aggressive preprocessing level (0=standard, 1=OTSU, 2=upscale)
            preprocessing_level = min(attempt - 1, 2)
            result = self._send_to_api(str(path), preprocessing_level=preprocessing_level)
            if result is not None and result.get("status") == "success":
                break
            if attempt < MAX_RETRIES:
                logger.warning(f"Retry {attempt}/{MAX_RETRIES} for {path.name} (preprocessing={preprocessing_level+1})")
                time.sleep(2)

        if result is None:
            logger.error(f"All retries failed for {path.name}")
            self._move_file(str(path), str(self.failed))
            self._consecutive_failures += 1
            self._check_consecutive_failures()
            print(f"{Fore.RED}[FAILED] {path.name} — moved to failed/{Style.RESET_ALL}")
            return

        dest = self._move_file(str(path), str(self.processed))
        self._consecutive_failures = 0

        confidence = result.get("confidence", 0)
        needs_review = result.get("needs_review", False)
        total = result.get("fields", {}).get("total_amount", "N/A")
        vendor = result.get("fields", {}).get("vendor_name", "N/A")

        color = Fore.GREEN if not needs_review else Fore.YELLOW
        print(f"{color}[OK] {path.name} | vendor={vendor} | total={total} | "
              f"conf={confidence:.1f}% | review={needs_review}{Style.RESET_ALL}")
        logger.success(
            f"Processed: {path.name} | confidence={confidence:.1f}% | needs_review={needs_review}"
        )

    def _send_to_api(self, file_path: str, preprocessing_level: int = 0) -> dict | None:
        path = Path(file_path)
        try:
            with open(path, "rb") as f:
                files = {"file": (path.name, f, "application/octet-stream")}
                headers = {
                    "X-API-Key": self.api_key,
                    "X-Preprocessing-Level": str(preprocessing_level),
                }
                resp = requests.post(
                    f"{self.api_url}/extract",
                    files=files,
                    headers=headers,
                    timeout=120,
                )
            if resp.status_code == 200:
                return resp.json()
            logger.error(f"API returned {resp.status_code}: {resp.text[:200]}")
            return None
        except requests.exceptions.ConnectionError:
            logger.error(f"Cannot connect to API at {self.api_url}")
            return None
        except Exception as exc:
            logger.error(f"API call failed: {exc}")
            return None

    def _move_file(self, src: str, dest_folder: str) -> str:
        src_path = Path(src)
        dest_path = Path(dest_folder) / src_path.name
        if dest_path.exists():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest_path = Path(dest_folder) / f"{src_path.stem}_{ts}{src_path.suffix}"
        try:
            shutil.move(str(src_path), str(dest_path))
            logger.info(f"Moved: {src_path.name} → {dest_folder}/")
        except Exception as exc:
            logger.error(f"Move failed: {exc}")
        return str(dest_path)

    def _check_consecutive_failures(self):
        if self._consecutive_failures >= 3:
            msg = (f"WARNING: {self._consecutive_failures} consecutive failures! "
                   "Check logs for details.")
            print(f"{Fore.RED}{Style.BRIGHT}{msg}{Style.RESET_ALL}")
            logger.error(msg)


if __name__ == "__main__":
    watcher = InvoiceWatcher()
    watcher.start()
