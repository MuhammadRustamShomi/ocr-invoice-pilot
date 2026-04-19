"""
FastAPI application — OCR Invoice extraction endpoints.
"""
import os
import json
import base64
import uuid
import time
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

from fastapi import FastAPI, File, UploadFile, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

# Ensure UTF-8 output on Windows (prevents charmap errors from EasyOCR progress bars)
import sys
if sys.stdout.encoding != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logger.add(
    os.getenv("LOG_FILE", "logs/ocr_pilot.log"),
    rotation="10 MB",
    retention="7 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {module}:{line} | {message}",
)

API_KEY = os.getenv("API_KEY", "ocr-pilot-key-2026")
MAX_FILE_MB = 20
STATS_FILE = Path("logs/stats.json")

app = FastAPI(title="OCR Invoice Pilot", version="1.0.0")

UNPROTECTED_PATHS = {"/health", "/stats", "/docs", "/openapi.json", "/redoc"}


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Reject protected routes without a valid X-API-Key before body parsing."""
    async def dispatch(self, request: Request, call_next):
        if request.url.path not in UNPROTECTED_PATHS:
            key = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
            if not key or key != API_KEY:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or missing API key."},
                )
        return await call_next(request)


app.add_middleware(APIKeyMiddleware)

# Semaphore: only 1 OCR job runs at a time (CPU-bound, not thread-safe for concurrency)
# Queues up concurrent requests so none time out
import asyncio
_ocr_semaphore: asyncio.Semaphore = None

# In-memory rate limit tracker: {ip: [timestamps]}
_rate_tracker: dict = defaultdict(list)

# In-memory stats (also persisted to stats.json)
_stats = {
    "total_processed": 0,
    "total_success": 0,
    "total_failed": 0,
    "total_needs_review": 0,
    "avg_confidence": 0.0,
    "avg_processing_time": 0.0,
    "last_updated": "",
}

# Lazy-loaded singletons
_ocr_engine = None
_field_extractor = None
_confidence_scorer = None
_sheets_writer = None


def get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        from core.ocr_engine import OCREngine
        _ocr_engine = OCREngine(gpu=False)
    return _ocr_engine


def get_field_extractor():
    global _field_extractor
    if _field_extractor is None:
        from core.field_extractor import FieldExtractor
        _field_extractor = FieldExtractor()
    return _field_extractor


def get_confidence_scorer():
    global _confidence_scorer
    if _confidence_scorer is None:
        from core.confidence_scorer import ConfidenceScorer
        _confidence_scorer = ConfidenceScorer()
    return _confidence_scorer


def get_sheets_writer():
    global _sheets_writer
    if _sheets_writer is None:
        from core.sheets_writer import SheetsWriter
        _sheets_writer = SheetsWriter()
        _sheets_writer.connect()
    return _sheets_writer


def _load_stats():
    global _stats
    if STATS_FILE.exists():
        try:
            with open(STATS_FILE, encoding="utf-8") as f:
                _stats.update(json.load(f))
        except Exception:
            pass


def _save_stats():
    _stats["last_updated"] = datetime.now(timezone.utc).isoformat()
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(_stats, f, indent=2)
    except Exception as exc:
        logger.error(f"Failed to save stats: {exc}")


def _update_stats(confidence: float, success: bool, needs_review: bool, proc_time: float):
    _stats["total_processed"] += 1
    if success:
        _stats["total_success"] += 1
    else:
        _stats["total_failed"] += 1
    if needs_review:
        _stats["total_needs_review"] += 1
    n = _stats["total_processed"]
    prev_conf = _stats["avg_confidence"]
    _stats["avg_confidence"] = round(
        (prev_conf * (n - 1) + confidence) / n, 2
    )
    prev_time = _stats["avg_processing_time"]
    _stats["avg_processing_time"] = round(
        (prev_time * (n - 1) + proc_time) / n, 2
    )
    _save_stats()


def _check_rate_limit(ip: str) -> bool:
    """Return True if request allowed (< 60/min)."""
    now = time.time()
    window = [t for t in _rate_tracker[ip] if now - t < 60]
    _rate_tracker[ip] = window
    if len(window) >= 60:
        return False
    _rate_tracker[ip].append(now)
    return True


def _validate_api_key(x_api_key: str):
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


def _validate_file_type(data: bytes) -> str:
    """Check magic bytes. Returns mime type or raises 415."""
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"%PDF":
        return "application/pdf"
    raise HTTPException(status_code=415, detail="Unsupported file type. Allowed: PNG, JPEG, PDF.")


def _process_file(file_bytes: bytes, filename: str, preprocessing_level: int = 0) -> dict:
    mime = _validate_file_type(file_bytes)
    suffix = ".pdf" if mime == "application/pdf" else ".png"

    engine = get_ocr_engine()
    extractor = get_field_extractor()
    scorer = get_confidence_scorer()

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        if mime == "application/pdf":
            pages = engine.extract_from_pdf(tmp_path)
            raw_text = "\n".join(p["raw_text"] for p in pages)
            ocr_confidence = sum(p["confidence"] for p in pages) / max(len(pages), 1)
            proc_time = sum(p["processing_time"] for p in pages)
        else:
            ocr_result = engine.extract_text(tmp_path, preprocessing_level=preprocessing_level)
            raw_text = ocr_result["raw_text"]
            ocr_confidence = ocr_result["confidence"]
            proc_time = ocr_result["processing_time"]
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    fields = extractor.extract_all(raw_text)
    scoring = scorer.score_extraction(fields, ocr_confidence)

    return {
        "status": "success",
        "filename": filename,
        "fields": fields,
        "confidence": scoring["overall"],
        "low_confidence_fields": scoring["low_confidence_fields"],
        "processing_time_seconds": round(proc_time, 3),
        "needs_review": scoring["needs_review"],
    }


@app.on_event("startup")
async def startup():
    global _ocr_semaphore
    _ocr_semaphore = asyncio.Semaphore(1)  # serialize OCR on CPU
    _load_stats()
    logger.info("OCR Invoice API started.")
    print("OCR Invoice API ready — http://127.0.0.1:8000/docs")
    # Pre-warm OCR model in background so first request is not slow
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _prewarm_ocr)


def _prewarm_ocr():
    """Load EasyOCR model at startup so first request is not slow."""
    try:
        import numpy as np
        engine = get_ocr_engine()
        engine._get_reader()
        # Run one tiny inference to fully initialise CUDA/CPU pipelines
        blank = np.ones((50, 200), dtype=np.uint8) * 255
        engine._run_ocr(blank)
        logger.success("OCR model pre-warmed — ready for requests.")
    except Exception as exc:
        logger.warning(f"OCR pre-warm failed (non-fatal): {exc}")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/stats")
def stats():
    _load_stats()
    return _stats


@app.post("/extract")
async def extract(
    request: Request,
    file: UploadFile = File(...),
    x_api_key: str = Header(None),
    x_preprocessing_level: str = Header(None),
):
    _validate_api_key(x_api_key)

    client_ip = request.client.host
    if not _check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Max 60 requests/minute.")

    content = await file.read()
    if len(content) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File too large. Max {MAX_FILE_MB} MB.")

    try:
        preprocessing_level = int(x_preprocessing_level or 0)
    except ValueError:
        preprocessing_level = 0

    request_id = str(uuid.uuid4())
    logger.info(f"Extract request | id={request_id} | file={file.filename} | size={len(content)} | prep={preprocessing_level}")

    try:
        # Serialize OCR calls — CPU can only do one at a time efficiently
        async with _ocr_semaphore:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: _process_file(content, file.filename or "upload",
                                            preprocessing_level=preprocessing_level)
            )
        result["request_id"] = request_id

        # Write to Sheets
        writer = get_sheets_writer()
        sheet_ok = writer.write_result(result)
        result["sheet_written"] = sheet_ok

        _update_stats(result["confidence"], True, result["needs_review"],
                      result["processing_time_seconds"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Extract failed | id={request_id} | error={exc}")
        _update_stats(0.0, False, False, 0.0)
        return JSONResponse(status_code=500, content={
            "error": str(exc), "status": "failed", "request_id": request_id
        })


@app.post("/extract-batch")
async def extract_batch(
    request: Request,
    x_api_key: str = Header(None),
):
    _validate_api_key(x_api_key)

    client_ip = request.client.host
    if not _check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded.")

    body = await request.json()
    if not isinstance(body, list):
        raise HTTPException(status_code=400, detail="Expected a JSON list of base64 images.")
    if len(body) > 10:
        raise HTTPException(status_code=400, detail="Max 10 images per batch.")

    results = []
    loop = asyncio.get_event_loop()
    for item in body:
        try:
            filename = item.get("filename", "batch_upload")
            b64_data = item.get("data", "")
            file_bytes = base64.b64decode(b64_data)
            async with _ocr_semaphore:
                result = await loop.run_in_executor(
                    None, lambda fb=file_bytes, fn=filename: _process_file(fb, fn)
                )
            get_sheets_writer().write_result(result)
            results.append(result)
        except Exception as exc:
            results.append({"status": "failed", "error": str(exc)})

    return {"batch_results": results, "count": len(results)}


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8000"))
    uvicorn.run("api.main:app", host=host, port=port, reload=True)
