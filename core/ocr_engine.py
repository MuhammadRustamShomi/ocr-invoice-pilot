"""
OCR Engine — wraps EasyOCR (or pytesseract fallback) with image preprocessing.
"""
import os
import time
from pathlib import Path

import cv2
import numpy as np
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

logger.add(
    os.getenv("LOG_FILE", "logs/ocr_pilot.log"),
    rotation="10 MB",
    retention="7 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {module}:{line} | {message}",
)

_OCR_BACKEND = None


def _load_backend():
    global _OCR_BACKEND
    if _OCR_BACKEND is not None:
        return _OCR_BACKEND
    try:
        import easyocr  # noqa: F401
        _OCR_BACKEND = "easyocr"
        logger.info("OCR backend: EasyOCR")
    except ImportError:
        try:
            import pytesseract  # noqa: F401
            _OCR_BACKEND = "pytesseract"
            logger.info("OCR backend: pytesseract")
        except ImportError:
            _OCR_BACKEND = "none"
            logger.error("No OCR backend available. Install easyocr or pytesseract.")
    return _OCR_BACKEND


class OCREngine:
    def __init__(self, languages: list = None, gpu: bool = False):
        if languages is None:
            languages = ["en"]
        self.languages = languages
        self.gpu = gpu
        self._reader = None
        self._backend = _load_backend()
        logger.info(f"OCREngine initialised | backend={self._backend} | gpu={gpu}")

    def _get_reader(self):
        if self._reader is None and self._backend == "easyocr":
            import easyocr
            logger.info("Loading EasyOCR model (may download ~100 MB on first run)...")
            self._reader = easyocr.Reader(self.languages, gpu=self.gpu, verbose=False)
            logger.info("EasyOCR model loaded.")
        return self._reader

    def _deskew(self, image: np.ndarray) -> np.ndarray:
        gray = image if len(image.shape) == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        lines = cv2.HoughLines(edges, 1, np.pi / 180, 100)
        if lines is None:
            return image
        angles = []
        for line in lines[:20]:
            rho, theta = line[0]
            angle = (theta * 180 / np.pi) - 90
            if abs(angle) < 10:
                angles.append(angle)
        if not angles:
            return image
        median_angle = float(np.median(angles))
        if abs(median_angle) < 0.5:
            return image
        h, w = image.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), median_angle, 1.0)
        return cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_REPLICATE)

    def _denoise(self, image: np.ndarray) -> np.ndarray:
        # medianBlur is ~400x faster than fastNlMeansDenoising with comparable quality
        return cv2.medianBlur(image, 3)

    def _increase_contrast(self, image: np.ndarray) -> np.ndarray:
        gray = image if len(image.shape) == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        return clahe.apply(gray)

    def _otsu_binarize(self, image: np.ndarray) -> np.ndarray:
        gray = image if len(image.shape) == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return binary

    def _upscale(self, image: np.ndarray, scale: float = 2.0) -> np.ndarray:
        h, w = image.shape[:2]
        return cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)

    def _resize_for_ocr(self, image: np.ndarray, max_width: int = 745) -> np.ndarray:
        """Scale down wide images to cap OCR time while preserving readability."""
        h, w = image.shape[:2]
        if w <= max_width:
            return image
        scale = max_width / w
        new_w, new_h = max_width, int(h * scale)
        return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)

    def preprocess_image(self, image_path: str) -> np.ndarray:
        image = cv2.imread(str(image_path))
        if image is None:
            raise FileNotFoundError(f"Could not load image: {image_path}")
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        deskewed = self._deskew(gray)
        contrasted = self._increase_contrast(deskewed)
        # Resize after full-quality preprocessing so thin text strokes survive.
        # _denoise is intentionally skipped here — medianBlur destroys sub-pixel
        # strokes at the scaled-down resolution; noisy images use levels 1–3 fallback.
        return self._resize_for_ocr(contrasted)

    def _run_ocr(self, processed_image: np.ndarray):
        if self._backend == "easyocr":
            reader = self._get_reader()
            results = reader.readtext(processed_image)
            blocks, confidences, lines = [], [], []
            for (bbox, text, conf) in results:
                blocks.append({"text": text, "confidence": conf * 100, "bbox": bbox})
                confidences.append(conf * 100)
                lines.append(text)
            raw_text = "\n".join(lines)
            confidence = float(np.mean(confidences)) if confidences else 0.0
            return raw_text, blocks, confidence

        elif self._backend == "pytesseract":
            import pytesseract
            from PIL import Image as PILImage
            pil_image = PILImage.fromarray(processed_image)
            data = pytesseract.image_to_data(pil_image, output_type=pytesseract.Output.DICT)
            blocks, confidences, lines_map = [], [], {}
            for i in range(len(data["text"])):
                conf = int(data["conf"][i])
                text = data["text"][i].strip()
                if conf > 0 and text:
                    confidences.append(conf)
                    key = (data["block_num"][i], data["line_num"][i])
                    lines_map.setdefault(key, []).append(text)
                    blocks.append({"text": text, "confidence": float(conf), "bbox": []})
            raw_text = "\n".join(" ".join(words) for words in lines_map.values())
            confidence = float(np.mean(confidences)) if confidences else 0.0
            return raw_text, blocks, confidence

        else:
            raise RuntimeError("No OCR backend available. Install easyocr or pytesseract + Tesseract binary.")

    def extract_text(self, image_path: str, preprocessing_level: int = 0) -> dict:
        """
        Run OCR on a single image.
        preprocessing_level: 0=standard, 1=OTSU, 2=upscale, 3=raw
        Returns: {"raw_text": str, "blocks": list, "confidence": float, "processing_time": float}
        """
        start = time.time()
        path = str(image_path)
        try:
            if preprocessing_level == 3:
                image = cv2.imread(path)
                processed = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            elif preprocessing_level == 2:
                image = cv2.imread(path)
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                processed = self._increase_contrast(self._denoise(self._upscale(gray)))
            elif preprocessing_level == 1:
                image = cv2.imread(path)
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                processed = self._otsu_binarize(gray)
            else:
                processed = self.preprocess_image(path)

            raw_text, blocks, confidence = self._run_ocr(processed)
            elapsed = time.time() - start
            logger.info(f"OCR done | file={Path(path).name} | conf={confidence:.1f}% | time={elapsed:.2f}s")
            return {"raw_text": raw_text, "blocks": blocks,
                    "confidence": confidence, "processing_time": elapsed}
        except Exception as exc:
            elapsed = time.time() - start
            logger.error(f"OCR failed | file={Path(path).name} | error={exc}")
            return {"raw_text": "", "blocks": [], "confidence": 0.0,
                    "processing_time": elapsed, "error": str(exc)}

    def extract_from_pdf(self, pdf_path: str) -> list:
        """Convert each PDF page to image and run OCR. Returns list of page results."""
        import fitz
        results = []
        doc = fitz.open(str(pdf_path))
        logger.info(f"PDF OCR | file={Path(pdf_path).name} | pages={len(doc)}")
        for page_num, page in enumerate(doc):
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
            img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
            tmp_path = Path("logs") / f"_tmp_page_{page_num}.png"
            cv2.imwrite(str(tmp_path), img_array)
            page_result = self.extract_text(str(tmp_path))
            page_result["page"] = page_num + 1
            results.append(page_result)
            tmp_path.unlink(missing_ok=True)
        doc.close()
        return results


if __name__ == "__main__":
    import sys
    print("Testing OCREngine...")
    engine = OCREngine(gpu=False)
    sample_dir = Path("samples/invoices")
    images = list(sample_dir.glob("*.png"))[:3]
    if not images:
        print("No sample images found. Run samples/generate_samples.py first.")
        sys.exit(1)
    confidences = []
    for img in images:
        result = engine.extract_text(str(img))
        conf = result["confidence"]
        confidences.append(conf)
        print(f"  {img.name}: confidence={conf:.1f}%, time={result['processing_time']:.2f}s")
        print(f"    Preview: {result['raw_text'][:80].replace(chr(10), ' ')}")
    print(f"\nAverage confidence: {sum(confidences)/len(confidences):.1f}%")
    print("OCREngine test complete.")
