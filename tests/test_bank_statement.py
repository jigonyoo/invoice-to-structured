import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline.doctypes.bank_statement import BankStatement, structure_offline, validate_bank_statement


def make(**updates):
    raw = {"account": "****1234", "period": {"start": "2026-06-01", "end": "2026-06-30"},
           "opening_balance": 1000, "closing_balance": 1125,
           "transactions": [{"date": "2026-06-02", "desc": "Deposit", "debit": None, "credit": 200, "balance": 1200},
                            {"date": "2026-06-03", "desc": "Utility", "debit": 75, "credit": None, "balance": 1125}]}
    raw.update(updates)
    return BankStatement.from_dict(raw)


class TestBankStatement(unittest.TestCase):
    def test_clean_auto_accept(self):
        self.assertFalse(validate_bank_statement(make()).needs_review)

    def test_closing_and_running_mismatch(self):
        bad = make(closing_balance=999)
        codes = [x.code for x in validate_bank_statement(bad).issues]
        self.assertIn("closing_balance_mismatch", codes)

    def test_duplicate_detected(self):
        tx = {"date": "2026-06-02", "desc": "Deposit", "debit": None, "credit": 200, "balance": 1200}
        result = validate_bank_statement(make(transactions=[tx, tx], closing_balance=1400))
        self.assertIn("duplicate_transaction", [x.code for x in result.issues])
        self.assertTrue(result.needs_review)

    def test_date_order(self):
        txs = make().to_dict()["transactions"]
        txs[1]["date"] = "2026-06-01"
        self.assertIn("date_order", [x.code for x in validate_bank_statement(make(transactions=txs)).issues])

    def test_offline_json(self):
        self.assertEqual(structure_offline(json.dumps(make().to_dict())).account, "****1234")


if __name__ == "__main__":
    unittest.main()
