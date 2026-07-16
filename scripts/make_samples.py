"""Generate synthetic invoice PDFs and JSON documents for the demo.

All data here is fictional. No client data is used, so the sample repo is safe
to publish publicly. One invoice (INV-1003) contains an intentional arithmetic
error so the validation engine visibly flags it for human review.
"""
import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parents[1] / "sample_data"
OUT.mkdir(parents=True, exist_ok=True)


def write_json_samples(folder, documents):
    target = OUT / folder
    target.mkdir(parents=True, exist_ok=True)
    for filename, document in documents.items():
        (target / filename).write_text(json.dumps(document, indent=2), encoding="utf-8")


def money(v):
    return f"{v:,.2f}"


def draw_invoice(path, meta, lines, currency="USD", tax_rate=0.0, break_total=False):
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    x = 20 * mm
    y = h - 25 * mm

    c.setFont("Helvetica-Bold", 20)
    c.drawString(x, y, meta["vendor"])
    c.setFont("Helvetica", 9)
    c.drawString(x, y - 6 * mm, meta["vendor_addr"])
    c.setFont("Helvetica-Bold", 22)
    c.setFillColor(colors.HexColor("#334155"))
    c.drawRightString(w - 20 * mm, y, "INVOICE")
    c.setFillColor(colors.black)

    y -= 20 * mm
    c.setFont("Helvetica", 10)
    c.drawString(x, y, f"Invoice #: {meta['invoice_number']}")
    c.drawString(x, y - 5 * mm, f"Invoice date: {meta['invoice_date']}")
    c.drawString(x, y - 10 * mm, f"Due date: {meta['due_date']}")
    c.drawRightString(w - 20 * mm, y, "Bill to:")
    c.drawRightString(w - 20 * mm, y - 5 * mm, meta["bill_to"])
    c.drawRightString(w - 20 * mm, y - 10 * mm, meta["bill_to_addr"])

    # table header
    y -= 22 * mm
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(colors.HexColor("#334155"))
    c.rect(x, y - 2 * mm, w - 40 * mm, 7 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.drawString(x + 2 * mm, y, "Description")
    c.drawRightString(x + 108 * mm, y, "Qty")
    c.drawRightString(x + 135 * mm, y, "Unit price")
    c.drawRightString(w - 22 * mm, y, "Amount")
    c.setFillColor(colors.black)

    subtotal = 0.0
    c.setFont("Helvetica", 9)
    for ln in lines:
        y -= 7 * mm
        amount = round(ln["qty"] * ln["unit_price"], 2)
        subtotal += amount
        c.drawString(x + 2 * mm, y, ln["description"])
        c.drawRightString(x + 108 * mm, y, str(ln["qty"]))
        c.drawRightString(x + 135 * mm, y, money(ln["unit_price"]))
        c.drawRightString(w - 22 * mm, y, money(amount))

    subtotal = round(subtotal, 2)
    tax = round(subtotal * tax_rate, 2)
    total = round(subtotal + tax, 2)
    # intentional error: print a wrong total to trigger the validator
    printed_total = total + 50.00 if break_total else total

    y -= 12 * mm
    c.setFont("Helvetica", 10)
    c.drawRightString(x + 135 * mm, y, "Subtotal:")
    c.drawRightString(w - 22 * mm, y, f"{currency} {money(subtotal)}")
    y -= 6 * mm
    c.drawRightString(x + 135 * mm, y, f"Tax ({tax_rate*100:.0f}%):")
    c.drawRightString(w - 22 * mm, y, f"{currency} {money(tax)}")
    y -= 7 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(x + 135 * mm, y, "Total due:")
    c.drawRightString(w - 22 * mm, y, f"{currency} {money(printed_total)}")

    c.setFont("Helvetica-Oblique", 8)
    c.drawString(x, 20 * mm, meta.get("terms", "Payment due within 30 days."))
    c.showPage()
    c.save()


def main():
    draw_invoice(
        OUT / "INV-1001.pdf",
        {
            "vendor": "Northwind Supplies Ltd.",
            "vendor_addr": "14 Harbour Road, Manchester, M1 2AB, UK",
            "invoice_number": "INV-1001",
            "invoice_date": "2026-06-03",
            "due_date": "2026-07-03",
            "bill_to": "Aurora Retail Group",
            "bill_to_addr": "88 King Street, Leeds, LS1 2HL",
            "terms": "Payment due within 30 days. Bank: Northwind, IBAN GB00 XXXX.",
        },
        [
            {"description": "Thermal receipt rolls (box of 50)", "qty": 12, "unit_price": 18.50},
            {"description": "Barcode label sheets (pack of 100)", "qty": 30, "unit_price": 6.20},
            {"description": "Handheld scanner cradle", "qty": 4, "unit_price": 42.00},
        ],
        currency="GBP",
        tax_rate=0.20,
    )

    draw_invoice(
        OUT / "INV-1002.pdf",
        {
            "vendor": "Cedar & Co. Consulting",
            "vendor_addr": "500 Market St, Suite 12, San Francisco, CA 94105",
            "invoice_number": "INV-1002",
            "invoice_date": "2026-06-11",
            "due_date": "2026-06-25",
            "bill_to": "Bluepeak Ventures",
            "bill_to_addr": "27 Mission Bay Blvd, San Francisco, CA",
            "terms": "Net 14. Late payments subject to 1.5% monthly interest.",
        },
        [
            {"description": "Discovery workshop (half day)", "qty": 2, "unit_price": 750.00},
            {"description": "Process mapping deliverable", "qty": 1, "unit_price": 1200.00},
            {"description": "Follow-up advisory hours", "qty": 6, "unit_price": 180.00},
        ],
        currency="USD",
        tax_rate=0.0,
    )

    # INV-1003 has a deliberately wrong printed total -> validator must flag it.
    draw_invoice(
        OUT / "INV-1003.pdf",
        {
            "vendor": "Sunrise Logistics GmbH",
            "vendor_addr": "Lagerstrasse 9, 20095 Hamburg, Germany",
            "invoice_number": "INV-1003",
            "invoice_date": "2026-06-18",
            "due_date": "2026-07-18",
            "bill_to": "Meridian Foods",
            "bill_to_addr": "Hafencity 4, Hamburg",
            "terms": "Payment due within 30 days.",
        },
        [
            {"description": "Pallet freight Hamburg -> Rotterdam", "qty": 8, "unit_price": 120.00},
            {"description": "Cold-chain surcharge", "qty": 8, "unit_price": 35.00},
            {"description": "Customs handling", "qty": 1, "unit_price": 90.00},
        ],
        currency="EUR",
        tax_rate=0.19,
        break_total=True,
    )
    po_base = {
        "po_number": "PO-3001", "vendor": "Fictional Office Supply Co.",
        "order_date": "2026-07-01", "delivery_date": "2026-07-15", "currency": "USD",
        "line_items": [{"sku": "CHAIR-01", "desc": "Ergonomic chair", "qty": 4, "unit_price": 225, "line_total": 900},
                       {"sku": "DESK-02", "desc": "Standing desk", "qty": 2, "unit_price": 480, "line_total": 960}],
        "subtotal": 1860, "tax": 148.8, "shipping": 75, "grand_total": 2083.8,
        "extraction_confidence": 0.98,
    }
    po_math = json.loads(json.dumps(po_base)); po_math["po_number"] = "PO-3002"; po_math["line_items"][1]["line_total"] = 900
    po_missing = json.loads(json.dumps(po_base)); po_missing["po_number"] = "PO-3003"; po_missing["vendor"] = None; po_missing["delivery_date"] = "2026-06-29"; po_missing["extraction_confidence"] = 0.72
    write_json_samples("po", {"PO-3001-clean.json": po_base, "PO-3002-math-error.json": po_math,
                              "PO-3003-missing-low-confidence.json": po_missing})
    bank_base = {
        "account": "****4821", "period": {"start": "2026-06-01", "end": "2026-06-30"},
        "opening_balance": 2500, "closing_balance": 2975,
        "transactions": [
            {"date": "2026-06-03", "desc": "Synthetic Client Payment", "debit": None, "credit": 800, "balance": 3300},
            {"date": "2026-06-10", "desc": "Fictional Cloud Hosting", "debit": 125, "credit": None, "balance": 3175},
            {"date": "2026-06-21", "desc": "Synthetic Office Rent", "debit": 200, "credit": None, "balance": 2975}],
        "extraction_confidence": 0.99,
    }
    bank_balance = json.loads(json.dumps(bank_base)); bank_balance["closing_balance"] = 2875
    bank_duplicate = json.loads(json.dumps(bank_base)); bank_duplicate["transactions"].append(json.loads(json.dumps(bank_duplicate["transactions"][1]))); bank_duplicate["closing_balance"] = 2850
    write_json_samples("bank_statement", {"BANK-4001-clean.json": bank_base,
                                          "BANK-4002-balance-error.json": bank_balance,
                                          "BANK-4003-duplicate.json": bank_duplicate})
    print("Wrote:", *[p.name for p in sorted(OUT.glob("*.pdf"))])


if __name__ == "__main__":
    main()
