"""Validation engine - the part that makes this a *trustworthy* extractor.

Anyone can prompt an LLM to emit JSON. What a real accounts-payable team needs
is to know which of those JSON rows they can post automatically and which a
human must eyeball. This module runs deterministic checks over an extracted
``Invoice`` and returns:

* a per-field / per-rule list of issues (error vs warning),
* a confidence score in [0, 1],
* a ``needs_review`` flag that routes low-trust invoices to a human queue.

None of this calls an LLM or the network, so it is fully reproducible and
testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .schema import Invoice

# Money comparisons: tolerate sub-cent rounding only.
TOL = 0.01
# Required fields for an invoice to be auto-postable.
REQUIRED = ["invoice_number", "vendor", "invoice_date", "currency", "total"]
# Below this confidence, always send to a human even if no hard error fired.
REVIEW_THRESHOLD = 0.80
# Per-field OCR confidence (0-1) under this is a warning; a lowest-field score
# under the hard floor forces review even on an arithmetically clean invoice.
OCR_WARN = 0.90
OCR_FLOOR = 0.80


@dataclass
class Issue:
    code: str
    severity: str  # "error" | "warning"
    message: str

    def to_dict(self):
        return {"code": self.code, "severity": self.severity, "message": self.message}


@dataclass
class ValidationResult:
    invoice_number: str | None
    confidence: float
    needs_review: bool
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self):
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self):
        return [i for i in self.issues if i.severity == "warning"]

    def to_dict(self):
        return {
            "invoice_number": self.invoice_number,
            "confidence": round(self.confidence, 3),
            "needs_review": self.needs_review,
            "issues": [i.to_dict() for i in self.issues],
        }


def _isclose(a, b, tol=TOL):
    return a is not None and b is not None and abs(a - b) <= tol


def validate(inv: Invoice, ocr: dict | None = None) -> ValidationResult:
    """Validate an invoice.

    ``ocr`` is the optional per-field OCR confidence report from the Textract
    extractor ({"min", "avg", "low_fields"}). When present, low OCR confidence
    can escalate an otherwise arithmetically clean invoice to human review, and
    it caps the overall confidence score. Extraction source is swappable; the
    trust logic is the same.
    """
    issues: list[Issue] = []

    # 1. Required fields present.
    for f_name in REQUIRED:
        if getattr(inv, f_name) in (None, ""):
            issues.append(Issue(f"missing_{f_name}", "error", f"Missing required field: {f_name}"))

    # 2. Invoice date sanity (YYYY-MM-DD).
    if inv.invoice_date and not _looks_like_date(inv.invoice_date):
        issues.append(
            Issue("date_format", "warning", f"invoice_date not ISO 8601: {inv.invoice_date!r}")
        )

    # 3. Per-line arithmetic: amount == quantity * unit_price.
    computed_sum = 0.0
    if not inv.line_items:
        issues.append(Issue("no_line_items", "error", "No line items were extracted"))
    for idx, li in enumerate(inv.line_items, 1):
        expected = round(li.quantity * li.unit_price, 2)
        computed_sum += li.amount
        if not _isclose(li.amount, expected):
            issues.append(
                Issue(
                    "line_math",
                    "error",
                    f"Line {idx} '{li.description[:40]}': amount {li.amount} "
                    f"!= qty {li.quantity} x unit {li.unit_price} = {expected}",
                )
            )
    computed_sum = round(computed_sum, 2)

    # 4. Sum of line amounts == subtotal (fall back to total when no subtotal).
    if inv.subtotal is not None:
        if not _isclose(computed_sum, inv.subtotal):
            issues.append(
                Issue(
                    "subtotal_mismatch",
                    "error",
                    f"Line items sum to {computed_sum} but subtotal is {inv.subtotal}",
                )
            )

    # 5. subtotal + tax == total.
    if inv.total is not None and inv.subtotal is not None:
        tax = inv.tax or 0.0
        expected_total = round(inv.subtotal + tax, 2)
        if not _isclose(expected_total, inv.total):
            issues.append(
                Issue(
                    "total_mismatch",
                    "error",
                    f"subtotal {inv.subtotal} + tax {tax} = {expected_total} "
                    f"but total is {inv.total}",
                )
            )

    # 6. OCR trust (only when the source is an OCR engine like Textract).
    if ocr:
        for field in ocr.get("low_fields") or []:
            issues.append(
                Issue("low_ocr_confidence", "warning",
                      f"OCR confidence below {int(OCR_WARN*100)}% for field: {field}")
            )
        if ocr.get("min") is not None and ocr["min"] < OCR_FLOOR:
            issues.append(
                Issue("ocr_below_floor", "error",
                      f"Lowest field OCR confidence {ocr['min']} is below {OCR_FLOOR}")
            )

    # 7. Confidence score: start at 1.0, penalise findings, floor at 0.
    penalty = 0.0
    for i in issues:
        penalty += 0.34 if i.severity == "error" else 0.08
    confidence = max(0.0, round(1.0 - penalty, 3))
    # OCR uncertainty caps trust: can't be more confident than the reading was.
    if ocr and ocr.get("avg") is not None:
        confidence = min(confidence, ocr["avg"])

    needs_review = bool([i for i in issues if i.severity == "error"]) or confidence < REVIEW_THRESHOLD
    return ValidationResult(
        invoice_number=inv.invoice_number,
        confidence=confidence,
        needs_review=needs_review,
        issues=issues,
    )


def _looks_like_date(s: str) -> bool:
    import re

    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", s.strip()))
