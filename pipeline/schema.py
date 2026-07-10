"""Target schema for a structured invoice.

Plain dataclasses (no third-party dependency) so the whole pipeline runs on a
clean Python 3.10+ install. The same JSON shape is what the LLM is asked to
return, so the offline heuristic extractor and the LLM extractor are
interchangeable.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


# The JSON schema handed to the LLM (OpenAI JSON mode). Kept in one place so the
# prompt and the dataclasses never drift apart.
INVOICE_JSON_SCHEMA = {
    "vendor": "string - company that issued the invoice",
    "vendor_address": "string or null",
    "invoice_number": "string",
    "invoice_date": "string YYYY-MM-DD or as printed",
    "due_date": "string YYYY-MM-DD or null",
    "bill_to": "string or null - customer name",
    "currency": "3-letter ISO code, e.g. USD/GBP/EUR",
    "line_items": [
        {
            "description": "string",
            "quantity": "number",
            "unit_price": "number",
            "amount": "number (quantity * unit_price)",
        }
    ],
    "subtotal": "number or null",
    "tax": "number or null",
    "total": "number or null",
}


@dataclass
class LineItem:
    description: str
    quantity: float
    unit_price: float
    amount: float


@dataclass
class Invoice:
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    vendor: Optional[str] = None
    vendor_address: Optional[str] = None
    bill_to: Optional[str] = None
    currency: Optional[str] = None
    line_items: list[LineItem] = field(default_factory=list)
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    total: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Invoice":
        items = [
            LineItem(
                description=str(li.get("description", "")).strip(),
                quantity=_num(li.get("quantity")),
                unit_price=_num(li.get("unit_price")),
                amount=_num(li.get("amount")),
            )
            for li in (d.get("line_items") or [])
        ]
        return cls(
            invoice_number=_clean(d.get("invoice_number")),
            invoice_date=_clean(d.get("invoice_date")),
            due_date=_clean(d.get("due_date")),
            vendor=_clean(d.get("vendor")),
            vendor_address=_clean(d.get("vendor_address")),
            bill_to=_clean(d.get("bill_to")),
            currency=_clean(d.get("currency")),
            line_items=items,
            subtotal=_num_or_none(d.get("subtotal")),
            tax=_num_or_none(d.get("tax")),
            total=_num_or_none(d.get("total")),
        )


def _clean(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _num(v) -> float:
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    return float(str(v).replace(",", "").replace("$", "").strip() or 0)


def _num_or_none(v):
    if v is None or v == "":
        return None
    try:
        return _num(v)
    except ValueError:
        return None
