"""
Generate 25 dummy invoice PNG images + 5 PDF invoices using ReportLab.
Saves to samples/invoices/ with a manifest.json ground-truth file.
"""
import json
import random
import io
from datetime import datetime, timedelta
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from PIL import Image, ImageFilter
import numpy as np

OUTPUT_DIR = Path("samples/invoices")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

VENDORS = [
    "Acme Solutions Ltd",
    "BlueSky Technologies Inc",
    "Greenfield Consulting Corp",
    "Horizon Services LLC",
    "Maple Leaf Group Co.",
    "NovaTech Systems Ltd",
    "Pinnacle Services Inc",
    "Quantum Innovations Corp",
    "Riverside Consulting LLC",
    "Summit Digital Solutions Ltd",
]

ITEMS_POOL = [
    ("Web Development Services", 800.00),
    ("Graphic Design", 450.00),
    ("SEO Optimization", 350.00),
    ("Cloud Hosting (Monthly)", 120.00),
    ("Database Administration", 600.00),
    ("IT Support (hrs)", 85.00),
    ("Software License", 299.00),
    ("Data Analysis Report", 750.00),
    ("Project Management", 500.00),
    ("Security Audit", 1200.00),
    ("Network Setup", 400.00),
    ("Content Writing", 200.00),
    ("Mobile App Development", 2000.00),
    ("API Integration", 650.00),
    ("Training Session (hrs)", 150.00),
]

TAX_RATE = 0.15


def random_date(start_year=2025, end_year=2026):
    start = datetime(start_year, 1, 1)
    end = datetime(end_year, 12, 31)
    delta = end - start
    return start + timedelta(days=random.randint(0, delta.days))


def generate_invoice_data(index: int) -> dict:
    vendor = random.choice(VENDORS)
    inv_date = random_date()
    due_date = inv_date + timedelta(days=30)
    inv_number = f"INV-{inv_date.year}-{index:04d}"

    num_items = random.randint(2, 5)
    selected = random.sample(ITEMS_POOL, num_items)
    line_items = []
    for desc, unit_price in selected:
        qty = random.randint(1, 5)
        total = round(qty * unit_price, 2)
        line_items.append({
            "description": desc,
            "qty": qty,
            "unit_price": unit_price,
            "total": total,
        })

    subtotal = round(sum(item["total"] for item in line_items), 2)
    tax = round(subtotal * TAX_RATE, 2)
    grand_total = round(subtotal + tax, 2)

    return {
        "vendor_name": vendor,
        "invoice_number": inv_number,
        "invoice_date": inv_date.strftime("%Y-%m-%d"),
        "due_date": due_date.strftime("%Y-%m-%d"),
        "line_items": line_items,
        "subtotal": f"${subtotal:,.2f}",
        "tax": f"${tax:,.2f}",
        "total_amount": f"${grand_total:,.2f}",
    }


def render_invoice_to_pdf_bytes(data: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                             rightMargin=2*cm, leftMargin=2*cm,
                             topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story = []

    vendor_style = ParagraphStyle("Vendor", fontSize=14, fontName="Helvetica-Bold", spaceAfter=2)
    header_style = ParagraphStyle("Header", fontSize=20, fontName="Helvetica-Bold",
                                   spaceAfter=6, alignment=TA_LEFT)
    normal = styles["Normal"]

    story.append(Paragraph(data["vendor_name"], vendor_style))
    story.append(Paragraph("INVOICE", header_style))
    story.append(Spacer(1, 0.3*cm))

    meta_data = [
        ["Invoice Number:", data["invoice_number"], "Invoice Date:", data["invoice_date"]],
        ["", "", "Due Date:", data["due_date"]],
    ]
    meta_table = Table(meta_data, colWidths=[4*cm, 5*cm, 4*cm, 4*cm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 0.5*cm))

    li_headers = ["Description", "Qty", "Unit Price", "Total"]
    li_rows = [li_headers]
    for item in data["line_items"]:
        li_rows.append([
            item["description"],
            str(item["qty"]),
            f"${item['unit_price']:,.2f}",
            f"${item['total']:,.2f}",
        ])
    li_table = Table(li_rows, colWidths=[9*cm, 2*cm, 3.5*cm, 3.5*cm])
    li_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(li_table)
    story.append(Spacer(1, 0.5*cm))

    totals_data = [
        ["", "Subtotal:", data["subtotal"]],
        ["", f"Tax ({int(TAX_RATE*100)}%):", data["tax"]],
        ["", "Grand Total:", data["total_amount"]],
    ]
    totals_table = Table(totals_data, colWidths=[9*cm, 4*cm, 5*cm])
    totals_table.setStyle(TableStyle([
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("FONTNAME", (1, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("LINEABOVE", (1, -1), (-1, -1), 1.5, colors.black),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph("Thank you for your business!", normal))

    doc.build(story)
    return buf.getvalue()


def pdf_to_png(pdf_bytes: bytes, dpi: int = 150) -> Image.Image:
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    pix = page.get_pixmap(matrix=mat)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    doc.close()
    return img


def add_noise(img: Image.Image, amount: float = 0.04) -> Image.Image:
    arr = np.array(img, dtype=np.float32)
    noise = np.random.normal(0, amount * 255, arr.shape)
    noisy = np.clip(arr + noise, 0, 255).astype(np.uint8)
    result = Image.fromarray(noisy)
    return result.filter(ImageFilter.GaussianBlur(radius=0.8))


def add_rotation(img: Image.Image, angle: float) -> Image.Image:
    return img.rotate(angle, expand=False, fillcolor=(255, 255, 255))


def generate_all_samples():
    manifest = {}
    print("Generating 25 sample invoice PNGs...")
    random.seed(42)

    for i in range(1, 26):
        data = generate_invoice_data(i)
        pdf_bytes = render_invoice_to_pdf_bytes(data)
        img = pdf_to_png(pdf_bytes, dpi=150)

        filename = f"invoice_{i:03d}.png"
        out_path = OUTPUT_DIR / filename

        if i <= 15:
            img.save(out_path, "PNG")
            category = "clean"
        elif i <= 20:
            angle = random.uniform(-2.0, 2.0)
            add_rotation(img, angle).save(out_path, "PNG")
            category = "rotated"
        else:
            add_noise(img).save(out_path, "PNG")
            category = "noisy"

        manifest[filename] = {**data, "category": category}
        print(f"  [{i:02d}/25] {filename} ({category})")

    manifest_path = OUTPUT_DIR / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Manifest saved: {manifest_path}")
    return manifest


def generate_pdf_invoices(count: int = 5):
    print(f"\nGenerating {count} PDF invoices...")
    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

    for i in range(1, count + 1):
        data = generate_invoice_data(100 + i)
        pdf_bytes = render_invoice_to_pdf_bytes(data)
        filename = f"invoice_pdf_{i:03d}.pdf"
        (OUTPUT_DIR / filename).write_bytes(pdf_bytes)
        manifest[filename] = {**data, "category": "pdf"}
        print(f"  [{i}/{count}] {filename}")

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Manifest updated: {manifest_path}")


if __name__ == "__main__":
    generate_all_samples()
    generate_pdf_invoices(count=5)
    png_count = len(list(OUTPUT_DIR.glob("invoice_*.png")))
    pdf_count = len(list(OUTPUT_DIR.glob("invoice_pdf_*.pdf")))
    print(f"\nDone: {png_count} PNG + {pdf_count} PDF invoices in {OUTPUT_DIR}")
    print("Sample generation complete!")
