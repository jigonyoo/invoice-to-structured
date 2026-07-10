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
   invoice  (text PDF  ── or ──  scanned / photo)
        │
        ▼
  1. Extract               pdfplumber (text)  ── or ──  AWS Textract (scanned)
        │
        ▼
  2. Structure to schema   OpenAI (JSON mode) / offline heuristic / Textract AnalyzeExpense
        │                  vendor, invoice #, dates, line items, totals, currency (+ OCR confidence)
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
| Textract | **scanned / photographed** invoices | yes (AWS creds) |

The extractors all return the same schema, so the validation layer and outputs
are identical regardless of how the fields were pulled. The extraction source is
swappable; the trust layer is constant.

## Scanned / image documents (AWS Textract)

Most real accounts-payable documents are scans or phone photos, not text PDFs.
`pipeline/textract_extract.py` uses AWS Textract's purpose-built `AnalyzeExpense`
API to read those, maps the result onto the same `Invoice` schema, and — because
Textract returns a per-field OCR confidence — folds that confidence into the
review decision. A maths-clean invoice whose fields were read with low OCR
confidence is still escalated to a human.

```bash
# Offline: parses a bundled AnalyzeExpense response, no AWS account needed.
python textract_demo.py

# Live on your own scan (AWS free tier = 1,000 pages/month):
export AWS_ACCESS_KEY_ID=...  AWS_SECRET_ACCESS_KEY=...  AWS_DEFAULT_REGION=us-east-1
python textract_demo.py --image path/to/scanned_invoice.png
```

Offline demo output (a scanned copy of INV-1003):

```
OCR confidence  avg=0.959  min=0.885  low-confidence fields=['tax']
...
Decision: NEEDS HUMAN REVIEW   (confidence 0.58)
  -> error: subtotal 1330.0 + tax 252.7 = 1582.7 but total is 1632.7
  -> warning: OCR confidence below 90% for field: tax
```

Two independent trust signals fire on one scanned image: the arithmetic is wrong
**and** a key field was read with low OCR confidence — both routed to review.

## Project layout

```
pipeline/
  schema.py           Invoice / LineItem dataclasses + the JSON shape the LLM targets
  extract.py          PDF → text, and text → Invoice (LLM or offline heuristic)
  textract_extract.py scanned/image → AWS Textract AnalyzeExpense → Invoice + OCR confidence
  validate.py         deterministic checks (+ optional OCR confidence) → needs_review  ← the core
run.py                batch a folder of text PDFs → structured.json / .csv / review_queue.csv
textract_demo.py      one scanned invoice → Textract → validated data (offline sample or live)
tests/                unit tests for the validation engine and the Textract parser
scripts/              generate the synthetic sample invoices
sample_data/          fictional invoices (one with a deliberate error) + a sample Textract response
sample_output/        committed snapshot of a run
```

## Tests

```bash
python -m unittest discover -s tests -v
```

Covers clean invoices, total/subtotal/line-math mismatches, missing fields,
empty line items, date-format warnings, rounding tolerance, the Textract
AnalyzeExpense parser, and OCR-confidence-driven review.

## Notes

- All sample data is fictional; no client data is included.
- Extends naturally to other document types (purchase orders, bank statements,
  delivery notes) — same extract → validate → route shape.
- Human-in-the-loop by design: the review queue is a feature, not a fallback.

## License

MIT
