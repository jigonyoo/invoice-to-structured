"""Extraction: PDF -> raw text -> structured Invoice.

Two interchangeable structurers:

* ``structure_with_llm``  - production path. Sends the raw text to an OpenAI
  model in JSON mode and maps the result onto the schema. Needs OPENAI_API_KEY.
* ``structure_offline``   - dependency-free heuristic parser. Lets the whole
  pipeline (and the validation layer, which is the real differentiator) run and
  be demonstrated without any API key or network call.

``structure`` picks the LLM path when a key is available, else falls back to the
offline parser, so ``python run.py`` always produces output.
"""
from __future__ import annotations

import json
import os
import re

import pdfplumber

from .schema import INVOICE_JSON_SCHEMA, Invoice

_MONEY = r"[\d,]+\.\d{2}"


def extract_text(pdf_path: str) -> str:
    """Concatenate text from every page of a PDF."""
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Offline heuristic parser (no dependencies, no network)                      #
# --------------------------------------------------------------------------- #
def structure_offline(text: str) -> Invoice:
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    inv = Invoice()

    if lines:
        inv.vendor = re.sub(r"\s*INVOICE\s*$", "", lines[0]).strip() or None
        if len(lines) > 1 and not re.match(r"(?i)invoice\s*#", lines[1]):
            inv.vendor_address = lines[1].strip()

    joined = "\n".join(lines)
    m = re.search(r"(?i)invoice\s*#\s*:?\s*([A-Za-z0-9\-/]+)", joined)
    if m:
        inv.invoice_number = m.group(1)
    m = re.search(r"(?i)invoice date\s*:?\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", joined)
    if m:
        inv.invoice_date = m.group(1)
    m = re.search(r"(?i)due date\s*:?\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", joined)
    if m:
        inv.due_date = m.group(1)
    # In a two-column layout the customer name sits in the right column, on the
    # same line as "Invoice date: <date>  <Customer Name>".
    m = re.search(r"(?i)invoice date\s*:?\s*[0-9]{4}-[0-9]{2}-[0-9]{2}\s+(.+)$", joined, re.M)
    if m:
        inv.bill_to = m.group(1).strip() or None

    # currency from any of the totals lines
    m = re.search(r"\b([A-Z]{3})\s+" + _MONEY, joined)
    if m:
        inv.currency = m.group(1)

    # line items: "<desc> <qty> <unit_price> <amount>"
    item_re = re.compile(r"^(.*?)\s+(\d+)\s+(" + _MONEY + r")\s+(" + _MONEY + r")$")
    for ln in lines:
        if re.search(r"(?i)^(subtotal|tax|total|description)\b", ln):
            continue
        mm = item_re.match(ln)
        if mm:
            desc, qty, up, amt = mm.groups()
            inv.line_items.append(
                Invoice.from_dict(
                    {
                        "line_items": [
                            {
                                "description": desc.strip(),
                                "quantity": qty,
                                "unit_price": up,
                                "amount": amt,
                            }
                        ]
                    }
                ).line_items[0]
            )

    cur = r"(?:[A-Z]{3}\s*)?"
    inv.subtotal = _grab_line(lines, r"(?i)^subtotal\b", cur)
    inv.tax = _grab_line(lines, r"(?i)^tax\b", cur)
    inv.total = _grab_line(lines, r"(?i)^total\b", cur)  # anchored -> not "Subtotal"
    return inv


def _grab_line(lines, label_re, cur):
    """Find the last money value on the first line whose start matches label_re."""
    for ln in lines:
        if re.match(label_re, ln.strip()):
            m = re.search(cur + "(" + _MONEY + r")\s*$", ln)
            if m:
                return float(m.group(1).replace(",", ""))
    return None


# --------------------------------------------------------------------------- #
# LLM parser (production path)                                                 #
# --------------------------------------------------------------------------- #
def structure_with_llm(text: str, model: str = "gpt-4o-mini") -> Invoice:
    from openai import OpenAI  # lazy import so offline mode needs no dependency

    client = OpenAI()
    schema_hint = json.dumps(INVOICE_JSON_SCHEMA, indent=2)
    prompt = (
        "You are an accounts-payable data extractor. Extract the invoice below "
        "into a strict JSON object with exactly these keys and shapes:\n"
        f"{schema_hint}\n\n"
        "Rules: numbers as numbers (no currency symbols or thousands commas); "
        "use null for anything not present; do not invent values; each line "
        "item's amount should be what is printed on the invoice, even if it "
        "looks inconsistent (validation happens downstream).\n\n"
        f"INVOICE TEXT:\n{text}"
    )
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
    )
    data = json.loads(resp.choices[0].message.content)
    return Invoice.from_dict(data)


def structure(text: str, mode: str = "auto", model: str = "gpt-4o-mini"):
    """Return (Invoice, engine_name)."""
    use_llm = mode == "llm" or (mode == "auto" and os.getenv("OPENAI_API_KEY"))
    if use_llm:
        return structure_with_llm(text, model=model), f"llm:{model}"
    return structure_offline(text), "offline-heuristic"
