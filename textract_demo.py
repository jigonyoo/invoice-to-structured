#!/usr/bin/env python3
"""Scanned invoice -> AWS Textract -> validated structured data (demo).

Shows the same trust layer running on a SCANNED / image invoice, using AWS
Textract's AnalyzeExpense as the OCR/extraction front-end instead of a text-PDF
reader. Textract's per-field OCR confidence is folded into the review decision.

Default (offline): parses a bundled AnalyzeExpense response so it runs with no
AWS account. To run it live on your own scan:

    export AWS_ACCESS_KEY_ID=...  AWS_SECRET_ACCESS_KEY=...  AWS_DEFAULT_REGION=us-east-1
    python textract_demo.py --image path/to/scanned_invoice.png

Free tier covers 1,000 AnalyzeExpense pages/month.
"""
from __future__ import annotations

import argparse

from pipeline.textract_extract import (
    load_response,
    structure_from_expense_response,
    structure_with_textract,
)
from pipeline.validate import validate

SAMPLE = "sample_data/textract_analyzeexpense_INV-1003.json"


def main(argv=None):
    p = argparse.ArgumentParser(description="Scanned invoice -> Textract -> validated data")
    p.add_argument("--image", help="live mode: a scanned invoice image/PDF (needs AWS creds)")
    p.add_argument("--response", default=SAMPLE,
                   help="offline mode: a saved AnalyzeExpense JSON response")
    args = p.parse_args(argv)

    if args.image:
        print(f"Calling AWS Textract AnalyzeExpense on {args.image} ...")
        inv, ocr = structure_with_textract(args.image)
        source = f"AWS Textract (live): {args.image}"
    else:
        inv, ocr = structure_from_expense_response(load_response(args.response))
        source = f"AWS Textract response (offline): {args.response}"

    result = validate(inv, ocr=ocr)
    d = inv.to_dict()

    print(f"\nSource: {source}")
    print(f"OCR confidence  avg={ocr['avg']}  min={ocr['min']}  "
          f"low-confidence fields={ocr['low_fields'] or 'none'}\n")
    print(f"  Vendor    : {d['vendor']}")
    print(f"  Invoice # : {d['invoice_number']}   Date: {d['invoice_date']}   Bill to: {d['bill_to']}")
    print(f"  Currency  : {d['currency']}")
    for li in d["line_items"]:
        print(f"    - {li['description'][:40]:40}  {li['quantity']} x {li['unit_price']} = {li['amount']}")
    print(f"  Subtotal/Tax/Total: {d['subtotal']} / {d['tax']} / {d['total']}\n")

    status = "NEEDS HUMAN REVIEW" if result.needs_review else "auto-postable"
    print(f"Decision: {status}   (confidence {round(result.confidence, 3)})")
    for i in result.issues:
        print(f"  -> {i.severity}: {i.message}")
    if not result.issues:
        print("  -> no issues")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
