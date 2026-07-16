"""Bank-statement extraction, schema, and deterministic reconciliation."""
from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date

from pipeline.schema import _clean, _num, _num_or_none
from pipeline.validate import Issue, TOL


BANK_JSON_SCHEMA = {
    "account": "masked account identifier", "period": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},
    "opening_balance": "number", "closing_balance": "number",
    "transactions": [{"date": "YYYY-MM-DD", "desc": "string", "debit": "number or null",
                      "credit": "number or null", "balance": "number"}],
}


@dataclass
class Transaction:
    date: str | None
    desc: str | None
    debit: float | None
    credit: float | None
    balance: float | None


@dataclass
class BankStatement:
    account: str | None = None
    period: dict = field(default_factory=dict)
    opening_balance: float | None = None
    closing_balance: float | None = None
    transactions: list[Transaction] = field(default_factory=list)
    extraction_confidence: float = 1.0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, raw):
        return cls(
            account=_clean(raw.get("account")), period=raw.get("period") or {},
            opening_balance=_num_or_none(raw.get("opening_balance")),
            closing_balance=_num_or_none(raw.get("closing_balance")),
            transactions=[Transaction(_clean(x.get("date")), _clean(x.get("desc")),
                                      _num_or_none(x.get("debit")), _num_or_none(x.get("credit")),
                                      _num_or_none(x.get("balance"))) for x in raw.get("transactions") or []],
            extraction_confidence=float(raw.get("extraction_confidence", 1.0)),
        )


@dataclass
class BankValidation:
    confidence: float
    needs_review: bool
    issues: list[Issue]

    def to_dict(self):
        return {"confidence": self.confidence, "needs_review": self.needs_review,
                "issues": [x.to_dict() for x in self.issues]}


def structure_offline(text: str) -> BankStatement:
    return BankStatement.from_dict(json.loads(text))


def structure_with_llm(text: str, model="gpt-4o-mini") -> BankStatement:
    from openai import OpenAI
    prompt = ("Extract this bank statement as JSON. Keep printed balances unchanged and do not invent fields. "
              f"Schema: {json.dumps(BANK_JSON_SCHEMA)}\nDOCUMENT:\n{text}")
    response = OpenAI().chat.completions.create(
        model=model, temperature=0, response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
    )
    return BankStatement.from_dict(json.loads(response.choices[0].message.content))


def structure(text: str, mode="auto", model="gpt-4o-mini"):
    use_llm = mode == "llm" or (mode == "auto" and os.getenv("OPENAI_API_KEY"))
    return (structure_with_llm(text, model), f"llm:{model}") if use_llm else (structure_offline(text), "offline-json")


def validate_bank_statement(statement: BankStatement) -> BankValidation:
    issues = []
    for name in ("account", "opening_balance", "closing_balance"):
        if getattr(statement, name) in (None, ""):
            issues.append(Issue(f"missing_{name}", "error", f"Missing required field: {name}"))
    for name in ("start", "end"):
        if not statement.period.get(name):
            issues.append(Issue(f"missing_period_{name}", "error", f"Missing required field: period.{name}"))
    if not statement.transactions:
        issues.append(Issue("no_transactions", "error", "No transactions were extracted"))

    previous = statement.opening_balance
    previous_date = None
    keys = []
    for index, tx in enumerate(statement.transactions, 1):
        if not tx.date or not tx.desc or tx.balance is None:
            issues.append(Issue("missing_transaction_field", "error", f"Transaction {index}: date, desc, and balance are required"))
        if tx.debit is not None and tx.credit is not None:
            issues.append(Issue("ambiguous_amount", "error", f"Transaction {index}: both debit and credit are set"))
        if tx.debit is None and tx.credit is None:
            issues.append(Issue("missing_amount", "error", f"Transaction {index}: debit or credit is required"))
        try:
            current_date = date.fromisoformat(tx.date) if tx.date else None
            if previous_date and current_date and current_date < previous_date:
                issues.append(Issue("date_order", "error", f"Transaction {index}: date is earlier than prior row"))
            previous_date = current_date or previous_date
        except ValueError:
            issues.append(Issue("date_format", "error", f"Transaction {index}: date must be ISO YYYY-MM-DD"))
        debit, credit = tx.debit or 0.0, tx.credit or 0.0
        if previous is not None and tx.balance is not None:
            expected = round(previous + credit - debit, 2)
            if abs(expected - tx.balance) > TOL:
                issues.append(Issue("running_balance_mismatch", "error", f"Transaction {index}: expected balance {expected}, printed {tx.balance}"))
            previous = tx.balance
        keys.append((tx.date, round(debit or credit, 2), (tx.desc or "").casefold().strip()))

    duplicates = [key for key, count in Counter(keys).items() if count > 1]
    for key in duplicates:
        issues.append(Issue("duplicate_transaction", "error", f"Duplicate transaction: {key[0]} | {key[2]} | {key[1]}"))
    if statement.opening_balance is not None and statement.closing_balance is not None:
        expected_close = round(statement.opening_balance + sum(x.credit or 0 for x in statement.transactions)
                               - sum(x.debit or 0 for x in statement.transactions), 2)
        if abs(expected_close - statement.closing_balance) > TOL:
            issues.append(Issue("closing_balance_mismatch", "error", f"opening + credits - debits = {expected_close}, closing is {statement.closing_balance}"))
    confidence = max(0.0, round(min(statement.extraction_confidence, 1.0) - sum(0.34 if x.severity == "error" else 0.08 for x in issues), 3))
    return BankValidation(confidence, bool(issues) or confidence < 0.8, issues)
