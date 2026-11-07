"""Part-number matching against the master list, plus sanity checks."""
import difflib
import re
from pathlib import Path

import pandas as pd

from . import config


def norm(s):
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


class PartMaster:
    def __init__(self, csv_path):
        df = pd.read_csv(csv_path)
        self.by_key = {norm(r.part_number): r._asdict() for r in df.itertuples(index=False)}

    def match(self, text):
        key = norm(text)
        if key in self.by_key:
            return {**self.by_key[key], "score": 1.0}
        close = difflib.get_close_matches(key, list(self.by_key), n=1, cutoff=config.MATCH_CUTOFF)
        if close:
            score = difflib.SequenceMatcher(None, key, close[0]).ratio()
            return {**self.by_key[close[0]], "score": round(score, 2)}
        return None


def annotate_lines(lines, master):
    """Adds matched part number / category / flags to each line. Returns hard issues."""
    issues = []
    for ln in lines:
        ln["part_input"] = ln["part_number"]
        ln.setdefault("flags", [])
        m = master.match(ln["part_number"])
        if m is None:
            ln["flags"].append("unknown part number")
            issues.append(f"Line {ln['line_no']}: unknown part '{ln['part_number']}'")
            ln["matched"] = None
        else:
            ln["matched"] = m
            ln["part_number"] = m["part_number"]
            ln["match_score"] = m["score"]
            ln["description"] = ln.get("description") or m["description"]
            if m["score"] < 1.0:
                ln["flags"].append(f"fuzzy match {ln['part_input']} -> {m['part_number']} ({m['score']:.0%})")
        q = ln["quantity"]
        if q is None or q <= 0 or q > config.MAX_SANE_QTY:
            ln["flags"].append("unusual quantity")
            issues.append(f"Line {ln['line_no']}: unusual quantity {q}")
    return issues


def validate_header(merged):
    issues = [f"Missing {f}" for f in config.REQUIRED_HEADER_FIELDS if not merged["header"].get(f)]
    if not merged["lines"]:
        issues.append("No line items found")
    if merged.get("scanned_pdf_suspected"):
        issues.append("PDF has no readable text (scanned?) - OCR unavailable or failed")
    return issues
