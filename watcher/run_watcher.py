"""
Run the folder watcher. Usage: python watcher/run_watcher.py
Watches inbox/ for new invoice files and sends them to the OCR API.
"""
import sys
import os
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

os.chdir(Path(__file__).parent.parent)

from watcher.folder_watcher import InvoiceWatcher

if __name__ == "__main__":
    print("=" * 50)
    print("  OCR Invoice Watcher")
    print("=" * 50)
    watcher = InvoiceWatcher()
    watcher.start()
