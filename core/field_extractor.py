"""
Field Extractor — extracts structured invoice fields from raw OCR text using
regex patterns and heuristics.
"""
import re
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger


class FieldExtractor:

    # Currency pattern: optional symbol ($, £, €, S, 8 — common OCR misreads of $)
    # Uses named groups to capture the prefix and the number separately
    _CURRENCY_RE = re.compile(
        r"([\$£€]|(?<!\d)[S8](?=\d))?\s*"          # optional currency prefix
        r"(\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\d+(?:\.\d{2})?)"  # numeric amount
    )

    # Date patterns
    _DATE_PATTERNS = [
        (re.compile(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b"), "dmy_or_mdy"),
        (re.compile(r"\b(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})\b"), "ymd"),
        (re.compile(
            r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\s+(\d{4})\b", re.IGNORECASE), "dmonthy"),
        (re.compile(
            r"\b(January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})\b",
            re.IGNORECASE), "monthdY"),
        (re.compile(
            r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})\b",
            re.IGNORECASE), "dmonthy_short"),
    ]

    _MONTH_MAP = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4,
        "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }

    def extract_all(self, raw_text: str) -> dict:
        result = {
            "vendor_name":    self.extract_vendor_name(raw_text),
            "invoice_number": self.extract_invoice_number(raw_text),
            "invoice_date":   self.extract_date(raw_text),
            "due_date":       self.extract_due_date(raw_text),
            "line_items":     self.extract_line_items(raw_text),
            "subtotal":       self.extract_subtotal(raw_text),
            "tax":            self.extract_tax(raw_text),
            "total_amount":   self.extract_total(raw_text),
        }

        # Vision API often reads two-column financial summaries column-by-column:
        #   Subtotal:          becomes  Subtotal:\n
        #   Tax (15%):                  Tax (15%):\n
        #   Grand Total:                Grand Total:\n
        #                               $2,220.00\n  ← actually Subtotal
        #                               $333.00\n    ← actually Tax
        #                               $2,553.00    ← actually Grand Total
        # The block extractor detects this pattern and maps by position.
        block = self._extract_financial_block(raw_text)
        if len(block) == 3:
            # Full block found — override individual results (positional mapping is reliable)
            result.update(block)
        else:
            for field in ("subtotal", "tax", "total_amount"):
                if not result[field] and block.get(field):
                    result[field] = block[field]

        return result

    def extract_vendor_name(self, raw_text: str) -> Optional[str]:
        company_indicators = ["ltd", "llc", "inc", "corp", "co.", "limited",
                               "incorporated", "company", "group", "services",
                               "solutions", "technologies", "consulting"]
        lines = [ln.strip() for ln in raw_text.split("\n") if ln.strip()]
        # Look for line with company indicator
        for line in lines[:10]:
            low = line.lower()
            if any(ind in low for ind in company_indicators):
                return line
        # Fallback: first non-empty non-numeric line
        for line in lines[:5]:
            if line and not re.match(r"^[\d\W]+$", line) and len(line) > 3:
                return line
        return None

    def extract_invoice_number(self, raw_text: str) -> Optional[str]:
        # Direct patterns — return the full match (no label context needed)
        direct_patterns = [
            r"\bINV[-\s/]?\d{4}[-\s/]?\d{2,6}\b",
            r"\bINV[-\s/]\d+\b",
        ]
        for pat in direct_patterns:
            m = re.search(pat, raw_text, re.IGNORECASE)
            if m:
                return m.group(0).strip()

        # Label-based: use capturing group to return only the value, not the label.
        # [:\.\s\n]+ handles "No:", "No.\n", "No:\n", "No: " etc. — including next line.
        label_patterns = [
            r"Invoice\s*(?:#|No\.?|Number|ID|Num)[:\.\s\n]+([\w][\w\-/]{2,})",
            r"Inv\.?\s*(?:#|No\.?|Number)[:\.\s\n]+([\w][\w\-/]{2,})",
            r"(?:Bill|Order)\s*(?:No\.?|Number|#)[:\.\s\n]+([\w][\w\-/]{2,})",
        ]
        for pat in label_patterns:
            m = re.search(pat, raw_text, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                if val and len(val) >= 3:
                    return val

        # Last resort: bare # followed by digits
        m = re.search(r"#\s*(\d{4,})", raw_text)
        if m:
            return m.group(1).strip()
        return None

    def extract_date(self, raw_text: str) -> Optional[str]:
        date_labels = [
            r"Invoice\s*Date[:\s]*",
            r"Date\s*Issued[:\s]*",
            r"Issued[:\s]*",
            r"Date[:\s]*",
        ]
        for label in date_labels:
            # Same line — [^\n] never crosses a newline boundary
            m = re.search(label + r"([^\n]{0,60})", raw_text, re.IGNORECASE)
            if m:
                date = self._parse_date_from_text(m.group(1))
                if date:
                    return date
            # Value on the next line (Vision API often splits label from value)
            m = re.search(label + r"[^\n]{0,10}\n\s*([^\n]{0,60})", raw_text, re.IGNORECASE)
            if m:
                date = self._parse_date_from_text(m.group(1))
                if date:
                    return date
        return self._parse_date_from_text(raw_text)

    def extract_due_date(self, raw_text: str) -> Optional[str]:
        labels = [
            r"(?:Payment\s*)?Due\s*Date[:\s]*",
            r"Payment\s*Due[:\s]*",
            r"Due\s*By[:\s]*",
            r"Pay\s*By[:\s]*",
        ]
        for label in labels:
            m = re.search(label + r"([^\n]{0,60})", raw_text, re.IGNORECASE)
            if m:
                date = self._parse_date_from_text(m.group(1))
                if date:
                    return date
            m = re.search(label + r"[^\n]{0,10}\n\s*([^\n]{0,60})", raw_text, re.IGNORECASE)
            if m:
                date = self._parse_date_from_text(m.group(1))
                if date:
                    return date
        return None

    def extract_total(self, raw_text: str) -> Optional[str]:
        for label in [r"Grand\s*Total[:\s]*", r"Total\s*Due[:\s]*",
                      r"Total\s*Amount[:\s]*", r"Amount\s*Due[:\s]*"]:
            amt = self._extract_labeled_amount(raw_text, label)
            if amt:
                return amt
        # Generic "Total:" — require large enough number (not tax rate)
        for m in re.finditer(r"\bTotal[:\s]*(.{0,40})", raw_text, re.IGNORECASE):
            snippet = m.group(1).strip()
            if re.search(r"[\$£€S]\s*\d{2,}|\d{3,}", snippet):
                amt = self._extract_currency_amount(snippet)
                if amt and float(amt.replace(",", "").lstrip("$£€S")) >= 10:
                    return amt
        return None

    def extract_tax(self, raw_text: str) -> Optional[str]:
        for label in [r"Tax\s*Amount[:\s]*", r"Tax\s*\(\d+%\)[:\s]*",
                      r"VAT[:\s]*", r"GST[:\s]*", r"Tax[:\s]*"]:
            amt = self._extract_labeled_amount(raw_text, label)
            if amt:
                try:
                    # Reject if it looks like a percentage rate (< 100 and no decimal context)
                    val = float(str(amt).replace(",", "").lstrip("$£€S"))
                    if val >= 1.0:
                        return amt
                except ValueError:
                    return amt
        return None

    def extract_subtotal(self, raw_text: str) -> Optional[str]:
        for label in [r"Sub\s*Total[:\s]*", r"Subtotal[:\s]*", r"Net\s*Amount[:\s]*"]:
            amt = self._extract_labeled_amount(raw_text, label)
            if amt:
                return amt
        return None

    def extract_line_items(self, raw_text: str) -> list:
        """
        Look for table-like lines: description followed by numbers (qty, price, total).
        Returns list of dicts: {"description": str, "qty": float, "unit_price": float, "total": float}
        """
        items = []
        # Pattern: text followed by 2-4 numbers (possibly with currency symbols)
        line_item_re = re.compile(
            r"^(.+?)\s+(\d+(?:\.\d+)?)\s+[\$£€]?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s+[\$£€]?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)$"
        )
        skip_words = {"subtotal", "sub total", "total", "tax", "vat", "gst",
                      "discount", "shipping", "freight", "amount due", "grand total"}
        for line in raw_text.split("\n"):
            line = line.strip()
            if not line or len(line) < 5:
                continue
            if any(sw in line.lower() for sw in skip_words):
                continue
            m = line_item_re.match(line)
            if m:
                try:
                    items.append({
                        "description": m.group(1).strip(),
                        "qty": float(m.group(2)),
                        "unit_price": float(m.group(3).replace(",", "")),
                        "total": float(m.group(4).replace(",", "")),
                    })
                except ValueError:
                    pass
        return items

    def _extract_currency_amount(self, text: str) -> Optional[str]:
        """Extract and normalise a currency amount from text."""
        m = self._CURRENCY_RE.search(text)
        if m:
            num_str = m.group(2).replace(",", "")
            try:
                val = float(num_str)
                if val >= 1.0:
                    # Always return as $amount for consistency
                    return f"${m.group(2)}"
            except ValueError:
                pass
        return None

    def _extract_labeled_amount(self, raw_text: str, label_pattern: str) -> Optional[str]:
        """
        Extract a currency amount associated with a label.
        Checks the same line AND the next line (handles OCR multi-line splits).
        """
        # Same line — [^\n] never crosses a newline boundary
        m = re.search(label_pattern + r"([^\n]{0,60})", raw_text, re.IGNORECASE)
        if m:
            amt = self._extract_currency_amount(m.group(1))
            if amt:
                return amt

        # Value on next line — [^\n]{0,10} = any trailing text on label line (before newline)
        # then \n + optional whitespace + the amount on the next line
        m2 = re.search(
            label_pattern + r"[^\n]{0,10}\n\s*([\$£€S]?\s*\d[\d,\.]*)",
            raw_text, re.IGNORECASE
        )
        if m2:
            amt = self._extract_currency_amount(m2.group(1))
            if amt:
                return amt

        return None

    def _parse_date_from_text(self, text: str) -> Optional[str]:
        for pattern, fmt in self._DATE_PATTERNS:
            m = pattern.search(text)
            if not m:
                continue
            try:
                if fmt == "dmy_or_mdy":
                    a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    # Assume DD/MM/YYYY if day > 12, else try both
                    if a > 12:
                        dt = datetime(year, b, a)
                    else:
                        dt = datetime(year, a, b)
                elif fmt == "ymd":
                    dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                elif fmt == "dmonthy":
                    month = self._MONTH_MAP.get(m.group(2).lower())
                    if not month:
                        continue
                    dt = datetime(int(m.group(3)), month, int(m.group(1)))
                elif fmt == "monthdY":
                    month = self._MONTH_MAP.get(m.group(1).lower())
                    if not month:
                        continue
                    dt = datetime(int(m.group(3)), month, int(m.group(2)))
                elif fmt == "dmonthy_short":
                    month = self._MONTH_MAP.get(m.group(2).lower())
                    if not month:
                        continue
                    dt = datetime(int(m.group(3)), month, int(m.group(1)))
                else:
                    continue
                return self._normalize_date(dt.strftime("%Y-%m-%d"))
            except (ValueError, KeyError):
                continue
        return None

    def _normalize_date(self, date_str: str) -> Optional[str]:
        """Accept YYYY-MM-DD and return same; convert other formats."""
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            return date_str
        for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
            except ValueError:
                pass
        return None


    # ── label-to-field mapping used by _extract_financial_block ─────────────
    _FIN_LABELS = [
        ("subtotal",     [r"sub\s*total", r"subtotal", r"net\s*amount"]),
        ("tax",          [r"tax(?:\s*\(\d+%\))?", r"vat(?:\b)", r"gst(?:\b)"]),
        ("total_amount", [
            r"grand\s*total", r"total\s*due", r"amount\s*due",
            r"total\s*amount", r"balance\s*due", r"(?<![a-z])total(?![a-z])",
        ]),
    ]

    def _extract_financial_block(self, raw_text: str) -> dict:
        """
        Detect Vision-API two-column reads where all labels appear before all values.
        Scans for a run of label-only lines immediately followed by a run of
        amount-only lines; maps them 1:1 by position.
        Returns a dict with up to three keys: subtotal, tax, total_amount.
        """
        result: dict = {}
        lines = [ln.strip() for ln in raw_text.split("\n")]

        for start in range(len(lines)):
            labels_run: list = []
            i = start

            # Collect consecutive label-only lines (line identifies a field, no amount embedded)
            while i < len(lines):
                ln = lines[i]
                if not ln:
                    i += 1
                    continue
                matched_field = None
                for field, patterns in self._FIN_LABELS:
                    if any(re.search(p, ln, re.IGNORECASE) for p in patterns):
                        # Reject if the line itself already contains a currency amount
                        if not re.search(r"[\$£€]\s*\d|\d{3,}", ln):
                            matched_field = field
                            break
                if matched_field:
                    labels_run.append(matched_field)
                    i += 1
                else:
                    break

            if len(labels_run) < 2:
                continue

            # Collect amount lines immediately following the label run
            amounts_run: list = []
            j = i
            while j < len(lines) and len(amounts_run) < len(labels_run):
                ln = lines[j]
                if not ln:
                    j += 1
                    continue
                amt = self._extract_currency_amount(ln)
                if amt:
                    amounts_run.append(amt)
                    j += 1
                else:
                    break

            if len(amounts_run) == len(labels_run):
                for field, amt in zip(labels_run, amounts_run):
                    result[field] = amt
                if len(result) >= 2:
                    break  # Good enough match found

        return result


if __name__ == "__main__":
    extractor = FieldExtractor()
    sample_text = """
    Acme Corp Ltd
    Invoice #: INV-2025-0042
    Invoice Date: 15/03/2025
    Due Date: 14/04/2025

    Description          Qty   Unit Price   Total
    Web Design Services  2     500.00       1000.00
    Hosting Setup        1     150.00       150.00

    Subtotal: $1,150.00
    Tax: $172.50
    Grand Total: $1,322.50
    """
    result = extractor.extract_all(sample_text)
    for field, value in result.items():
        print(f"  {field}: {value}")
    print("\nFieldExtractor test complete.")
