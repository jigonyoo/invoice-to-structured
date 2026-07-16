#!/usr/bin/env python3
"""Run one deterministic HITL gate over invoice, PO, and bank-statement records."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline.doctypes.bank_statement import structure_offline as bank_structure, validate_bank_statement
from pipeline.doctypes.po import structure_offline as po_structure, validate_po
from pipeline.review import review_batch
from pipeline.schema import Invoice
from pipeline.validate import validate


FIXED_TIME = lambda: datetime(2026, 7, 16, tzinfo=timezone.utc)


def build_records():
    invoice = Invoice.from_dict({"invoice_number": "INV-DEMO", "vendor": "Synthetic Vendor",
        "invoice_date": "2026-07-01", "currency": "USD",
        "line_items": [{"description": "Service", "quantity": 1, "unit_price": 100, "amount": 100}],
        "subtotal": 100, "tax": 0, "total": 100})
    po = po_structure(Path("sample_data/po/PO-3002-math-error.json").read_text())
    bank = bank_structure(Path("sample_data/bank_statement/BANK-4003-duplicate.json").read_text())
    return [
        {"doctype": "invoice", "record_id": invoice.invoice_number, "extraction_confidence": 1.0,
         "validation": validate(invoice).to_dict()},
        {"doctype": "po", "record_id": po.po_number, "extraction_confidence": po.extraction_confidence,
         "validation": validate_po(po).to_dict()},
        {"doctype": "bank_statement", "record_id": bank.account, "extraction_confidence": bank.extraction_confidence,
         "validation": validate_bank_statement(bank).to_dict()},
    ]


def main():
    result = review_batch(build_records(), clock=FIXED_TIME)
    output = Path("sample_output/review")
    output.mkdir(parents=True, exist_ok=True)
    (output / "review_summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["metrics"], indent=2))
    for row in result["records"]:
        print(f"{row['doctype']:<16} {row['record_id']:<12} {row['decision']:<13} {row['calibrated_confidence']}")
    print(f"Wrote {output / 'review_summary.json'}")
    return result


if __name__ == "__main__":
    main()
