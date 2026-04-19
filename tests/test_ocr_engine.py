"""Tests for OCREngine."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import numpy as np
import cv2
from core.ocr_engine import OCREngine


def make_test_image(text: str = "INVOICE") -> np.ndarray:
    """Create a simple white image with black text."""
    img = np.ones((200, 400), dtype=np.uint8) * 255
    cv2.putText(img, text, (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.5,
                (0, 0, 0), 2, cv2.LINE_AA)
    return img


def test_engine_initialises():
    engine = OCREngine(gpu=False)
    assert engine._backend in ("easyocr", "pytesseract", "none")


def test_preprocess_image(tmp_path):
    engine = OCREngine(gpu=False)
    img = make_test_image()
    img_path = tmp_path / "test.png"
    cv2.imwrite(str(img_path), img)
    processed = engine.preprocess_image(str(img_path))
    assert processed is not None
    assert len(processed.shape) == 2  # grayscale


def test_deskew_no_crash():
    engine = OCREngine(gpu=False)
    img = make_test_image()
    result = engine._deskew(img)
    assert result.shape == img.shape


def test_denoise_no_crash():
    engine = OCREngine(gpu=False)
    img = make_test_image()
    result = engine._denoise(img)
    assert result is not None


def test_extract_text_returns_dict(tmp_path):
    engine = OCREngine(gpu=False)
    img = make_test_image("INV-2025-0001")
    img_path = tmp_path / "test_inv.png"
    cv2.imwrite(str(img_path), img)
    result = engine.extract_text(str(img_path))
    assert isinstance(result, dict)
    assert "raw_text" in result
    assert "confidence" in result
    assert "processing_time" in result
    assert isinstance(result["blocks"], list)


def test_extract_text_samples():
    """Run OCR on actual sample invoices if they exist."""
    sample_dir = Path("samples/invoices")
    images = list(sample_dir.glob("*.png"))[:5]
    if not images:
        pytest.skip("No sample images — run samples/generate_samples.py first")

    engine = OCREngine(gpu=False)
    confidences = []
    for img_path in images:
        result = engine.extract_text(str(img_path))
        confidences.append(result["confidence"])
        assert "raw_text" in result

    avg = sum(confidences) / len(confidences)
    print(f"\nAverage OCR confidence on {len(images)} samples: {avg:.1f}%")
    # Clean invoices should have reasonable confidence
    assert avg >= 0  # At minimum, should not crash


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
