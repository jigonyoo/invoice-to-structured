#!/usr/bin/env python3
"""Batch a folder of invoice PDFs into validated, structured data.

Usage:
    python run.py                          # process sample_data/ (offline, no key)
    python run.py --input path/to/pdfs     # your own folder
    python run.py --mode llm               # force the OpenAI extractor (needs key)

Outputs (in --output, default ./output):
    structured.json    full records: extraction + validation per file
    structured.csv     one flat row per invoice (for a sheet / ERP import)
    review_queue.csv   only the invoices a human must check, with reasons

A human reviews review_queue.csv before anything is posted. That gate is the
point: automate the confident rows, escalate the rest.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys

from pipeline.doctypes.po import structure as structure_po, validate_po
from pipeline.doctypes.bank_statement import structure as structure_bank, validate_bank_statement


def process_file(path: str, mode: str, model: str) -> dict:
    # Keep PDF dependencies isolated so PO/bank JSON demos remain stdlib-only.
    from pipeline.extract import extract_text, structure
    from pipeline.validate import validate

    text = extract_text(path)
    inv, engine = structure(text, mode=mode, model=model)
    result = validate(inv)
    return {
        "file": os.path.basename(path),
        "engine": engine,
        "invoice": inv.to_dict(),
        "validation": result.to_dict(),
    }


def process_json_file(path: str, doctype: str, mode: str, model: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    if doctype == "po":
        document, engine = structure_po(text, mode=mode, model=model)
        validation = validate_po(document)
        record_id = document.po_number
    else:
        document, engine = structure_bank(text, mode=mode, model=model)
        validation = validate_bank_statement(document)
        record_id = document.account
    return {"file": os.path.basename(path), "doctype": doctype, "record_id": record_id,
            "engine": engine, "document": document.to_dict(), "validation": validation.to_dict()}


def write_json_outputs(records: list[dict], out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "structured.json"), "w", encoding="utf-8") as handle:
        json.dump(records, handle, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, "review_queue.csv"), "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["file", "doctype", "record_id", "confidence", "severity", "code", "reason"])
        for record in records:
            if not record["validation"]["needs_review"]:
                continue
            for issue in record["validation"]["issues"]:
                writer.writerow([record["file"], record["doctype"], record["record_id"],
                                 record["validation"]["confidence"], issue["severity"],
                                 issue["code"], issue["message"]])


def write_outputs(records: list[dict], out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "structured.json"), "w") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    flat_cols = [
        "file", "invoice_number", "vendor", "bill_to", "invoice_date", "due_date",
        "currency", "subtotal", "tax", "total", "line_item_count",
        "confidence", "needs_review", "engine",
    ]
    with open(os.path.join(out_dir, "structured.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=flat_cols)
        w.writeheader()
        for r in records:
            inv, val = r["invoice"], r["validation"]
            w.writerow({
                "file": r["file"],
                "invoice_number": inv["invoice_number"],
                "vendor": inv["vendor"],
                "bill_to": inv["bill_to"],
                "invoice_date": inv["invoice_date"],
                "due_date": inv["due_date"],
                "currency": inv["currency"],
                "subtotal": inv["subtotal"],
                "tax": inv["tax"],
                "total": inv["total"],
                "line_item_count": len(inv["line_items"]),
                "confidence": val["confidence"],
                "needs_review": val["needs_review"],
                "engine": r["engine"],
            })

    with open(os.path.join(out_dir, "review_queue.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file", "invoice_number", "confidence", "severity", "code", "reason"])
        for r in records:
            if not r["validation"]["needs_review"]:
                continue
            issues = r["validation"]["issues"] or [
                {"severity": "warning", "code": "low_confidence", "message": "Below review threshold"}
            ]
            for i in issues:
                w.writerow([
                    r["file"], r["invoice"]["invoice_number"],
                    r["validation"]["confidence"], i["severity"], i["code"], i["message"],
                ])


def print_summary(records: list[dict]) -> None:
    total = len(records)
    review = sum(1 for r in records if r["validation"]["needs_review"])
    auto = total - review
    print(f"\nProcessed {total} invoice(s):  {auto} auto-postable  |  {review} need review\n")
    print(f"{'FILE':<16}{'INVOICE':<12}{'TOTAL':>12}  {'CONF':>5}  STATUS")
    print("-" * 60)
    for r in records:
        inv, val = r["invoice"], r["validation"]
        status = "REVIEW" if val["needs_review"] else "auto"
        tot = f"{inv['currency'] or ''} {inv['total']}"
        print(f"{r['file']:<16}{str(inv['invoice_number'] or ''):<12}{tot:>12}  "
              f"{val['confidence']:>5}  {status}")
        for i in val["issues"]:
            print(f"    -> {i['severity']}: {i['message']}")


def main(argv=None):
    p = argparse.ArgumentParser(description="Validated document -> structured data pipeline")
    p.add_argument("--doctype", choices=["invoice", "po", "bank_statement"], default="invoice")
    p.add_argument("--input", help="input folder or glob (defaults to bundled samples for doctype)")
    p.add_argument("--output", default="output", help="output directory")
    p.add_argument("--mode", choices=["auto", "offline", "llm"], default="auto",
                   help="auto = LLM if OPENAI_API_KEY set, else offline heuristic")
    p.add_argument("--model", default="gpt-4o-mini", help="OpenAI model for llm mode")
    args = p.parse_args(argv)

    input_path = args.input or ("sample_data" if args.doctype == "invoice" else f"sample_data/{args.doctype}")
    suffix = ".pdf" if args.doctype == "invoice" else ".json"
    pattern = input_path if input_path.endswith(suffix) else os.path.join(input_path, f"*{suffix}")
    files = sorted(glob.glob(pattern))
    if not files:
        print(f"No {suffix} files found at {pattern!r}", file=sys.stderr)
        return 1

    if args.doctype == "invoice":
        records = [process_file(fp, args.mode, args.model) for fp in files]
        write_outputs(records, args.output)
        print_summary(records)
    else:
        records = [process_json_file(fp, args.doctype, args.mode, args.model) for fp in files]
        write_json_outputs(records, args.output)
        auto = sum(not row["validation"]["needs_review"] for row in records)
        print(f"Processed {len(records)} {args.doctype} document(s): {auto} auto_accept | {len(records)-auto} needs_review")
    names = "structured.json, structured.csv, review_queue.csv" if args.doctype == "invoice" else "structured.json, review_queue.csv"
    print(f"\nWrote {names} to ./{args.output}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
