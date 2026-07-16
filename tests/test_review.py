import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline.review import ReviewThresholds, calibrate, review_batch, route_record


def record(confidence=1.0, needs_review=False, issues=None, extraction=1.0):
    return {"doctype": "invoice", "record_id": "X-1", "extraction_confidence": extraction,
            "validation": {"confidence": confidence, "needs_review": needs_review, "issues": issues or []}}


NOW = lambda: datetime(2026, 7, 16, tzinfo=timezone.utc)


class TestReview(unittest.TestCase):
    def test_calibration_multiplies_signals(self):
        self.assertEqual(calibrate(0.9, {"confidence": 0.8}), 0.72)

    def test_clean_auto_accept(self):
        self.assertEqual(route_record(record(), clock=NOW)["decision"], "auto_accept")

    def test_rule_error_needs_review_with_explanation(self):
        issue = {"code": "total_mismatch", "severity": "error", "message": "Totals differ"}
        routed = route_record(record(0.66, True, [issue]), clock=NOW)
        self.assertEqual(routed["decision"], "needs_review")
        self.assertEqual(routed["audit_log"][0]["timestamp"], "2026-07-16T00:00:00Z")
        self.assertIn("Totals differ", routed["explanation"])

    def test_both_signals_below_floor_reject(self):
        self.assertEqual(route_record(record(0.2, True, extraction=0.3), clock=NOW)["decision"], "reject")

    def test_configurable_thresholds(self):
        routed = route_record(record(0.85), ReviewThresholds(auto_accept=0.9, reject=0.3), NOW)
        self.assertEqual(routed["decision"], "needs_review")

    def test_batch_metrics_and_queue(self):
        issue = {"code": "duplicate_transaction", "severity": "error", "message": "Duplicate"}
        result = review_batch([record(), record(0.5, True, [issue])], clock=NOW)
        self.assertEqual(result["metrics"]["auto_accept_rate"], 0.5)
        self.assertEqual(result["metrics"]["review_rate"], 0.5)
        self.assertEqual(result["metrics"]["top_failure_reasons"][0]["code"], "duplicate_transaction")
        self.assertEqual(len(result["review_queue"]), 1)


if __name__ == "__main__":
    unittest.main()
