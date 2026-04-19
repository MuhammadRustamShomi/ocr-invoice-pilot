"""
Security helpers — API key verification, rate limiting, file type validation.
"""
import os
import time
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY", "ocr-pilot-key-2026")
_rate_tracker: dict = defaultdict(list)

# File magic bytes
_MAGIC = {
    b"\x89PNG": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"%PDF": "application/pdf",
}


def verify_api_key(key: str) -> bool:
    return bool(key) and key == API_KEY


def check_rate_limit(ip: str, limit: int = 60, window: int = 60) -> bool:
    """Return True if request is allowed (under limit per window seconds)."""
    now = time.time()
    timestamps = [t for t in _rate_tracker[ip] if now - t < window]
    _rate_tracker[ip] = timestamps
    if len(timestamps) >= limit:
        return False
    _rate_tracker[ip].append(now)
    return True


def validate_file_type(file_bytes: bytes) -> str | None:
    """
    Check magic bytes to determine file type.
    Returns mime type string or None if unsupported.
    """
    for magic, mime in _MAGIC.items():
        if file_bytes[:len(magic)] == magic:
            return mime
    return None
