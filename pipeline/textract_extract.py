"""Scanned / image documents -> structured Invoice via AWS Textract.

Most real accounts-payable documents are scans or phone photos, not text PDFs.
AWS Textract's purpose-built ``AnalyzeExpense`` API reads invoices and receipts
and returns typed fields (VENDOR_NAME, TOTAL, line items, ...) each with an OCR
confidence score.

This module:
  * calls AnalyzeExpense (real boto3 code, needs AWS credentials), and
  * maps the response onto the SAME ``Invoice`` schema the rest of the pipeline
    uses, so the identical deterministic validation layer runs on scanned docs.

It also returns Textract's per-field OCR confidence, which the validator folds
in: a maths-clean invoice whose fields were read with low OCR confidence still
gets escalated to a human. Extraction source (text PDF, LLM, or Textract) is
swappable; the trust layer is constant.

An offline path (``structure_from_expense_response``) parses a saved
AnalyzeExpense JSON so the whole thing runs and is testable without an AWS
account; run it live once with the free tier (1,000 pages/mo) to confirm.
"""
from __future__ import annotations

import json

from .schema import Invoice, LineItem, _num, _num_or_none

# AnalyzeExpense summary field types -> our schema field names.
SUMMARY_MAP = {
    "INVOICE_RECEIPT_ID": "invoice_number",
    "INVOICE_RECEIPT_DATE": "invoice_date",
    "DUE_DATE": "due_date",
    "VENDOR_NAME": "vendor",
    "VENDOR_ADDRESS": "vendor_address",
    "RECEIVER_NAME": "bill_to",
    "SUBTOTAL": "subtotal",
    "TAX": "tax",
    "TOTAL": "total",
    "AMOUNT_DUE": "total",  # fallback if TOTAL absent
}
_NUMERIC_FIELDS = {"subtotal", "tax", "total"}


def analyze_expense(path: str) -> dict:
    """Call AWS Textract AnalyzeExpense on a local image/PDF. Needs credentials."""
    import boto3  # lazy: offline demo/tests need neither boto3 nor a network call

    with open(path, "rb") as f:
        payload = f.read()
    client = boto3.client("textract")
    return client.analyze_expense(Document={"Bytes": payload})


def structure_with_textract(path: str):
    """Live path: Textract -> (Invoice, confidence report)."""
    return structure_from_expense_response(analyze_expense(path))


def structure_from_expense_response(resp: dict):
    """Parse an AnalyzeExpense response dict -> (Invoice, confidence_report).

    confidence_report = {"min": float, "avg": float, "low_fields": [name,...]}
    with OCR confidence on a 0-1 scale.
    """
    docs = resp.get("ExpenseDocuments") or []
    inv = Invoice()
    confs: list[float] = []
    low_fields: list[str] = []

    if not docs:
        return inv, {"min": None, "avg": None, "low_fields": []}

    doc = docs[0]

    for field in doc.get("SummaryFields", []):
        ftype = (field.get("Type") or {}).get("Text", "")
        target = SUMMARY_MAP.get(ftype)
        if not target:
            continue
        val = (field.get("ValueDetection") or {})
        text = (val.get("Text") or "").strip()
        conf = _conf(val.get("Confidence"))
        if conf is not None:
            confs.append(conf)
            if conf < 0.90:
                low_fields.append(target)
        if not text:
            continue
        if target in _NUMERIC_FIELDS:
            setattr(inv, target, _num_or_none(_strip_money(text)))
            if inv.currency is None:
                inv.currency = _detect_currency(text)
        elif getattr(inv, target) is None:  # don't overwrite (e.g. TOTAL vs AMOUNT_DUE)
            setattr(inv, target, text)

    for group in doc.get("LineItemGroups", []):
        for li in group.get("LineItems", []):
            row = {"description": "", "quantity": 0, "unit_price": 0, "amount": 0}
            for f in li.get("LineItemExpenseFields", []):
                t = (f.get("Type") or {}).get("Text", "")
                v = (f.get("ValueDetection") or {})
                txt = (v.get("Text") or "").strip()
                c = _conf(v.get("Confidence"))
                if c is not None:
                    confs.append(c)
                if t == "ITEM":
                    row["description"] = txt
                elif t == "QUANTITY":
                    row["quantity"] = _num(_strip_money(txt))
                elif t == "UNIT_PRICE":
                    row["unit_price"] = _num(_strip_money(txt))
                elif t == "PRICE":
                    row["amount"] = _num(_strip_money(txt))
            if row["description"] or row["amount"]:
                inv.line_items.append(
                    LineItem(row["description"], row["quantity"], row["unit_price"], row["amount"])
                )

    report = {
        "min": round(min(confs), 3) if confs else None,
        "avg": round(sum(confs) / len(confs), 3) if confs else None,
        "low_fields": sorted(set(low_fields)),
    }
    return inv, report


def _conf(raw):
    """Textract confidence is 0-100; normalise to 0-1."""
    if raw is None:
        return None
    try:
        return round(float(raw) / 100.0, 4)
    except (TypeError, ValueError):
        return None


def _strip_money(s: str) -> str:
    """Pull the numeric part out of values like 'EUR 1,330.00' -> '1330.00'."""
    import re

    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", s or "")
    return m.group(0).replace(",", "") if m else ""


def _detect_currency(text: str):
    if "€" in text or "EUR" in text.upper():
        return "EUR"
    if "£" in text or "GBP" in text.upper():
        return "GBP"
    if "$" in text or "USD" in text.upper():
        return "USD"
    return None


def load_response(path: str) -> dict:
    with open(path) as f:
        return json.load(f)
