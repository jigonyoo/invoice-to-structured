"""Deterministic unit tests for the validation engine.

Run: python -m unittest discover -s tests   (no third-party deps needed)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.schema import Invoice  # noqa: E402
from pipeline.validate import validate  # noqa: E402


def make(**over):
    base = dict(
        invoice_number="INV-1",
        invoice_date="2026-06-01",
        vendor="Acme",
        currency="USD",
        line_items=[
            {"description": "Widget", "quantity": 2, "unit_price": 10.0, "amount": 20.0},
            {"description": "Gadget", "quantity": 1, "unit_price": 5.0, "amount": 5.0},
        ],
        subtotal=25.0,
        tax=2.5,
        total=27.5,
    )
    base.update(over)
    return Invoice.from_dict(base)


class TestValidate(unittest.TestCase):
    def test_clean_invoice_is_auto_postable(self):
        r = validate(make())
        self.assertEqual(r.confidence, 1.0)
        self.assertFalse(r.needs_review)
        self.assertEqual(r.errors, [])

    def test_total_mismatch_flagged(self):
        r = validate(make(total=99.0))
        self.assertTrue(r.needs_review)
        self.assertIn("total_mismatch", [i.code for i in r.errors])

    def test_line_math_error_flagged(self):
        items = [{"description": "X", "quantity": 3, "unit_price": 10.0, "amount": 20.0}]
        r = validate(make(line_items=items, subtotal=20.0, tax=0.0, total=20.0))
        self.assertIn("line_math", [i.code for i in r.errors])
        self.assertTrue(r.needs_review)

    def test_subtotal_mismatch_flagged(self):
        r = validate(make(subtotal=999.0, tax=0.0, total=999.0))
        self.assertIn("subtotal_mismatch", [i.code for i in r.errors])

    def test_missing_required_field_flagged(self):
        r = validate(make(vendor=None))
        self.assertIn("missing_vendor", [i.code for i in r.errors])
        self.assertTrue(r.needs_review)

    def test_no_line_items_flagged(self):
        r = validate(make(line_items=[], subtotal=0.0, tax=0.0, total=0.0))
        self.assertIn("no_line_items", [i.code for i in r.errors])

    def test_bad_date_is_warning_not_error(self):
        r = validate(make(invoice_date="June 1, 2026"))
        self.assertIn("date_format", [i.code for i in r.warnings])
        # a lone warning should not, by itself, raise a hard error
        self.assertNotIn("date_format", [i.code for i in r.errors])

    def test_rounding_within_tolerance_passes(self):
        items = [{"description": "X", "quantity": 3, "unit_price": 3.333, "amount": 10.0}]
        r = validate(make(line_items=items, subtotal=10.0, tax=0.0, total=10.0))
        self.assertEqual(r.errors, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
