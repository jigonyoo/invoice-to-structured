import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline.doctypes.po import PurchaseOrder, structure_offline, validate_po


def make(**updates):
    raw = {"po_number": "PO-1", "vendor": "Synthetic Supply Co", "order_date": "2026-07-01",
           "delivery_date": "2026-07-10", "currency": "USD",
           "line_items": [{"sku": "A-1", "desc": "Widget", "qty": 2, "unit_price": 10, "line_total": 20}],
           "subtotal": 20, "tax": 2, "shipping": 3, "grand_total": 25}
    raw.update(updates)
    return PurchaseOrder.from_dict(raw)


class TestPurchaseOrder(unittest.TestCase):
    def test_clean_auto_accept(self):
        self.assertFalse(validate_po(make()).needs_review)

    def test_line_and_total_math(self):
        bad = make(line_items=[{"sku": "A", "desc": "W", "qty": 2, "unit_price": 10, "line_total": 19}])
        codes = [x.code for x in validate_po(bad).issues]
        self.assertIn("line_math", codes)
        self.assertIn("subtotal_mismatch", codes)

    def test_missing_field_and_date_order(self):
        result = validate_po(make(vendor=None, delivery_date="2026-06-30"))
        self.assertTrue(result.needs_review)
        self.assertIn("missing_vendor", [x.code for x in result.issues])
        self.assertIn("delivery_before_order", [x.code for x in result.issues])

    def test_offline_json(self):
        po = structure_offline(json.dumps(make().to_dict()))
        self.assertEqual(po.po_number, "PO-1")


if __name__ == "__main__":
    unittest.main()
