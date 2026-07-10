# Invoice → Validated Structured Data

Turn messy invoice PDFs into clean, **validated** structured data (JSON + CSV),
and automatically route only the trustworthy rows for auto-posting while sending
anything suspicious to a human review queue.

> Anyone can prompt an LLM to spit out JSON from a document. The hard part —
> and the part an accounts-payable team actually pays for — is knowing **which
> rows they can trust**. This pipeline adds a deterministic validation layer on
> top of extraction, so every invoice comes with a confidence score and a clear
> reason when it needs a human.

Built by Jigon Yoo — data / AI-automation engineer. AI does the extraction, a
human owns the review gate.

---

## What it does

```
   PDF invoice
        │
        ▼
  1. Extract text            pdfplumber
        │
        ▼
  2. Structure to schema     OpenAI (JSON mode)  ── or ──  offline heuristic
        │                    vendor, invoice #, dates, line items, totals, currency
        ▼
  3. Validate (deterministic)
        │   • line amount  == qty × unit price
        │   • Σ line items == subtotal
        │   • subtotal+tax == total
        │   • required fields present, date format sane
        │   → confidence score + needs_review flag
        ▼
  4. Output
        structured.json   full record per file
        structured.csv    one flat row per invoice  → sheet / ERP import
        review_queue.csv   only the rows a human must check, with reasons
```

The validation step (3) is the differentiator. It runs no LLM and no network,
so it is fully deterministic, testable, and reproducible.

## Quickstart

```bash
pip install -r requirements.txt

# Offline demo — no API key needed. Runs on the bundled sample invoices.
python run.py

# Your own invoices, using the LLM extractor:
cp .env.example .env        # add OPENAI_API_KEY
python run.py --input path/to/invoices --mode llm
```

Sample run (bundled `sample_data/`, offline mode):

```
Processed 3 invoice(s):  2 auto-postable  |  1 need review

FILE            INVOICE            TOTAL   CONF  STATUS
------------------------------------------------------------
INV-1001.pdf    INV-1001       GBP 691.2    1.0  auto
INV-1002.pdf    INV-1002      USD 3780.0    1.0  auto
INV-1003.pdf    INV-1003      EUR 1632.7   0.66  REVIEW
    -> error: subtotal 1330.0 + tax 252.7 = 1582.7 but total is 1632.7
```

INV-1003 has a total that does not equal subtotal + tax, so it is caught and
routed to the review queue instead of being silently posted. See
[`sample_output/`](sample_output/) for the exact JSON/CSV this produces.

## Why the validation layer matters

A raw extractor will happily return `total: 1632.70` because that is what the
document says — even when the arithmetic is wrong. Downstream, that becomes a
mispaid invoice. Here, the same row comes back with:

```json
{
  "invoice_number": "INV-1003",
  "confidence": 0.66,
  "needs_review": true,
  "issues": [
    {"code": "total_mismatch", "severity": "error",
     "message": "subtotal 1330.0 + tax 252.7 = 1582.7 but total is 1632.7"}
  ]
}
```

Confident invoices flow straight through; only the exceptions cost human time.

## Extraction modes

| Mode | When | Needs key |
|------|------|-----------|
| `offline` | demo / text-based PDFs / no key | no |
| `llm` | production, varied real-world layouts | yes (`OPENAI_API_KEY`) |
| `auto` (default) | LLM if a key is present, else offline | — |

The two extractors return the same schema, so the validation layer and outputs
are identical regardless of how the fields were pulled.

## Project layout

```
pipeline/
  schema.py      Invoice / LineItem dataclasses + the JSON shape the LLM targets
  extract.py     PDF → text, and text → Invoice (LLM or offline)
  validate.py    deterministic checks → confidence + needs_review  ← the core
run.py           batch a folder → structured.json / .csv / review_queue.csv
tests/           unit tests for the validation engine
scripts/         generate the synthetic sample invoices
sample_data/     3 fictional invoices (one with a deliberate error)
sample_output/   committed snapshot of a run
```

## Tests

```bash
python -m unittest discover -s tests -v
```

Covers clean invoices, total/subtotal/line-math mismatches, missing fields,
empty line items, date-format warnings, and rounding tolerance.

## Notes

- All sample data is fictional; no client data is included.
- Extends naturally to other document types (purchase orders, bank statements,
  delivery notes) — same extract → validate → route shape.
- Human-in-the-loop by design: the review queue is a feature, not a fallback.

## License

MIT
