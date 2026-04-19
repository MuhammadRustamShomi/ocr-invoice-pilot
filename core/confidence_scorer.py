"""
Confidence Scorer — scores extraction results and flags low-confidence fields.
"""
import re
import os
from typing import Optional

from loguru import logger
from dotenv import load_dotenv

load_dotenv()

THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "70"))


class ConfidenceScorer:

    def score_extraction(self, fields: dict, ocr_confidence: float) -> dict:
        """
        Returns:
            {
                "overall": float,
                "field_scores": {field: float},
                "low_confidence_fields": [str],
                "needs_review": bool
            }
        """
        field_scores = {}
        for field_name, value in fields.items():
            field_scores[field_name] = self._score_field(field_name, value)

        # Incorporate cross-field consistency
        self._apply_consistency_bonus(fields, field_scores)

        # Blend field scores with OCR confidence
        if field_scores:
            avg_field = sum(field_scores.values()) / len(field_scores)
        else:
            avg_field = 0.0
        overall = (avg_field * 0.6 + ocr_confidence * 0.4)

        low_confidence_fields = [f for f, s in field_scores.items() if s < THRESHOLD]
        needs_review = overall < THRESHOLD or len(low_confidence_fields) >= 2

        return {
            "overall": round(overall, 1),
            "field_scores": {k: round(v, 1) for k, v in field_scores.items()},
            "low_confidence_fields": low_confidence_fields,
            "needs_review": needs_review,
        }

    def _score_field(self, field_name: str, value) -> float:
        """Score a single field 0–100."""
        if value is None or value == [] or value == "":
            return 0.0

        score = 40.0  # Present

        # Format validation (+30)
        if field_name == "invoice_number":
            if re.search(r"[\w\-]{4,}", str(value)):
                score += 30.0
        elif field_name in ("invoice_date", "due_date"):
            if re.match(r"^\d{4}-\d{2}-\d{2}$", str(value)):
                score += 30.0
            else:
                score += 10.0
        elif field_name in ("total_amount", "subtotal", "tax"):
            if re.search(r"\d+\.?\d*", str(value)):
                score += 30.0
        elif field_name == "vendor_name":
            if len(str(value)) >= 3:
                score += 20.0
            if len(str(value)) >= 6:
                score += 10.0
        elif field_name == "line_items":
            if isinstance(value, list) and len(value) > 0:
                score += 30.0
            else:
                score = 40.0  # Empty list is acceptable
        else:
            if value:
                score += 30.0

        return min(score, 100.0)

    def _apply_consistency_bonus(self, fields: dict, scores: dict) -> None:
        """
        If subtotal + tax ≈ total_amount, give +30 bonus to all three fields.
        Modifies scores in-place.
        """
        subtotal = self._parse_amount(fields.get("subtotal"))
        tax = self._parse_amount(fields.get("tax"))
        total = self._parse_amount(fields.get("total_amount"))

        if subtotal is not None and tax is not None and total is not None:
            expected = subtotal + tax
            if abs(expected - total) / max(total, 0.01) < 0.05:  # within 5%
                for key in ("subtotal", "tax", "total_amount"):
                    scores[key] = min(scores.get(key, 0) + 30.0, 100.0)
                logger.info("Consistency check passed: subtotal + tax ≈ total")
            else:
                logger.warning(
                    f"Consistency check failed: {subtotal} + {tax} = {expected} ≠ {total}"
                )

    @staticmethod
    def _parse_amount(value) -> Optional[float]:
        if value is None:
            return None
        m = re.search(r"\d{1,3}(?:,\d{3})*(?:\.\d{2})?", str(value))
        if m:
            try:
                return float(m.group(0).replace(",", ""))
            except ValueError:
                pass
        return None


if __name__ == "__main__":
    scorer = ConfidenceScorer()
    fields = {
        "vendor_name": "Acme Corp Ltd",
        "invoice_number": "INV-2025-0042",
        "invoice_date": "2025-03-15",
        "due_date": "2025-04-14",
        "line_items": [{"description": "Web Design", "qty": 2, "unit_price": 500, "total": 1000}],
        "subtotal": "$1,150.00",
        "tax": "$172.50",
        "total_amount": "$1,322.50",
    }
    result = scorer.score_extraction(fields, ocr_confidence=85.0)
    print(f"Overall confidence: {result['overall']}%")
    print(f"Needs review: {result['needs_review']}")
    print(f"Low confidence fields: {result['low_confidence_fields']}")
    for field, score in result["field_scores"].items():
        print(f"  {field}: {score}%")
    print("\nConfidenceScorer test complete.")
