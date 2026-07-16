"""Purchase-order extraction, schema, and deterministic validation."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date

from pipeline.schema import _clean, _num, _num_or_none
from pipeline.validate import Issue, TOL


PO_JSON_SCHEMA = {
    "po_number": "string", "vendor": "string", "order_date": "YYYY-MM-DD",
    "delivery_date": "YYYY-MM-DD", "currency": "3-letter ISO code",
    "line_items": [{"sku": "string", "desc": "string", "qty": "number",
                    "unit_price": "number", "line_total": "number"}],
    "subtotal": "number", "tax": "number", "shipping": "number", "grand_total": "number",
}


@dataclass
class POLineItem:
    sku: str
    desc: str
    qty: float
    unit_price: float
    line_total: float


@dataclass
class PurchaseOrder:
    po_number: str | None = None
    vendor: str | None = None
    order_date: str | None = None
    delivery_date: str | None = None
    currency: str | None = None
    line_items: list[POLineItem] = field(default_factory=list)
    subtotal: float | None = None
    tax: float | None = None
    shipping: float | None = None
    grand_total: float | None = None
    extraction_confidence: float = 1.0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, raw):
        return cls(
            po_number=_clean(raw.get("po_number")), vendor=_clean(raw.get("vendor")),
            order_date=_clean(raw.get("order_date")), delivery_date=_clean(raw.get("delivery_date")),
            currency=_clean(raw.get("currency")),
            line_items=[POLineItem(_clean(x.get("sku")) or "", _clean(x.get("desc")) or "",
                                  _num(x.get("qty")), _num(x.get("unit_price")),
                                  _num(x.get("line_total"))) for x in raw.get("line_items") or []],
            subtotal=_num_or_none(raw.get("subtotal")), tax=_num_or_none(raw.get("tax")),
            shipping=_num_or_none(raw.get("shipping")), grand_total=_num_or_none(raw.get("grand_total")),
            extraction_confidence=float(raw.get("extraction_confidence", 1.0)),
        )


@dataclass
class POValidation:
    confidence: float
    needs_review: bool
    issues: list[Issue]

    def to_dict(self):
        return {"confidence": self.confidence, "needs_review": self.needs_review,
                "issues": [x.to_dict() for x in self.issues]}


def structure_offline(text: str) -> PurchaseOrder:
    """Parse deterministic JSON text; bundled samples require no key or network."""
    return PurchaseOrder.from_dict(json.loads(text))


def structure_with_llm(text: str, model="gpt-4o-mini") -> PurchaseOrder:
    from openai import OpenAI
    prompt = ("Extract this purchase order as JSON. Do not correct printed arithmetic or invent fields. "
              f"Schema: {json.dumps(PO_JSON_SCHEMA)}\nDOCUMENT:\n{text}")
    response = OpenAI().chat.completions.create(
        model=model, temperature=0, response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
    )
    return PurchaseOrder.from_dict(json.loads(response.choices[0].message.content))


def structure(text: str, mode="auto", model="gpt-4o-mini"):
    use_llm = mode == "llm" or (mode == "auto" and os.getenv("OPENAI_API_KEY"))
    return (structure_with_llm(text, model), f"llm:{model}") if use_llm else (structure_offline(text), "offline-json")


def validate_po(po: PurchaseOrder) -> POValidation:
    issues = []
    for name in ("po_number", "vendor", "order_date", "delivery_date", "currency",
                 "subtotal", "grand_total"):
        if getattr(po, name) in (None, ""):
            issues.append(Issue(f"missing_{name}", "error", f"Missing required field: {name}"))
    if not po.line_items:
        issues.append(Issue("no_line_items", "error", "No line items were extracted"))
    line_sum = 0.0
    for index, item in enumerate(po.line_items, 1):
        expected = round(item.qty * item.unit_price, 2)
        line_sum += item.line_total
        if abs(item.line_total - expected) > TOL:
            issues.append(Issue("line_math", "error", f"Line {index}: {item.line_total} != {item.qty} x {item.unit_price} = {expected}"))
        if not item.sku or not item.desc:
            issues.append(Issue("missing_line_field", "error", f"Line {index}: sku and desc are required"))
    if po.subtotal is not None and abs(round(line_sum, 2) - po.subtotal) > TOL:
        issues.append(Issue("subtotal_mismatch", "error", f"Line items sum to {round(line_sum, 2)} but subtotal is {po.subtotal}"))
    if po.subtotal is not None and po.grand_total is not None:
        expected = round(po.subtotal + (po.tax or 0) + (po.shipping or 0), 2)
        if abs(expected - po.grand_total) > TOL:
            issues.append(Issue("grand_total_mismatch", "error", f"subtotal + tax + shipping = {expected} but grand_total is {po.grand_total}"))
    if po.order_date and po.delivery_date:
        try:
            if date.fromisoformat(po.delivery_date) < date.fromisoformat(po.order_date):
                issues.append(Issue("delivery_before_order", "error", "delivery_date is earlier than order_date"))
        except ValueError:
            issues.append(Issue("date_format", "error", "order_date and delivery_date must be ISO YYYY-MM-DD"))
    if po.currency and (len(po.currency) != 3 or po.currency.upper() != po.currency):
        issues.append(Issue("currency_format", "error", "currency must be one uppercase 3-letter ISO code"))
    confidence = max(0.0, round(min(po.extraction_confidence, 1.0) - sum(0.34 if x.severity == "error" else 0.08 for x in issues), 3))
    return POValidation(confidence, bool(issues) or confidence < 0.8, issues)
