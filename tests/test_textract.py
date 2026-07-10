"""Tests for the AWS Textract AnalyzeExpense parser + OCR-aware validation.

Runs fully offline against the bundled sample response (no AWS, no network).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.textract_extract import load_response, structure_from_expense_response  # noqa: E402
from pipeline.validate import validate  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "..", "sample_data", "textract_analyzeexpense_INV-1003.json")


class TestTextractParser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inv, cls.ocr = structure_from_expense_response(load_response(SAMPLE))

    def test_summary_fields_mapped(self):
        self.assertEqual(self.inv.invoice_number, "INV-1003")
        self.assertEqual(self.inv.vendor, "Sunrise Logistics GmbH")
        self.assertEqual(self.inv.bill_to, "Meridian Foods")
        self.assertEqual(self.inv.currency, "EUR")

    def test_numeric_fields_parsed_from_currency_text(self):
        self.assertEqual(self.inv.subtotal, 1330.0)
        self.assertEqual(self.inv.tax, 252.7)
        self.assertEqual(self.inv.total, 1632.7)

    def test_line_items_parsed(self):
        self.assertEqual(len(self.inv.line_items), 3)
        self.assertEqual(self.inv.line_items[0].amount, 960.0)

    def test_ocr_report(self):
        self.assertIn("tax", self.ocr["low_fields"])   # tax read at 88.5%
        self.assertAlmostEqual(self.ocr["min"], 0.885, places=3)

    def test_validation_catches_total_and_flags_ocr(self):
        r = validate(self.inv, ocr=self.ocr)
        self.assertTrue(r.needs_review)
        codes = [i.code for i in r.issues]
        self.assertIn("total_mismatch", codes)          # arithmetic error caught
        self.assertIn("low_ocr_confidence", codes)       # low OCR confidence surfaced

    def test_clean_ocr_does_not_force_review(self):
        # A clean invoice with high OCR confidence should stay auto-postable.
        from pipeline.schema import Invoice
        good = Invoice.from_dict({
            "invoice_number": "X", "invoice_date": "2026-01-01", "vendor": "V",
            "currency": "USD",
            "line_items": [{"description": "a", "quantity": 1, "unit_price": 10, "amount": 10}],
            "subtotal": 10, "tax": 0, "total": 10,
        })
        r = validate(good, ocr={"min": 0.98, "avg": 0.99, "low_fields": []})
        self.assertFalse(r.needs_review)


if __name__ == "__main__":
    unittest.main(verbosity=2)
