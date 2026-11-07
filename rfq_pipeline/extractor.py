"""Rule-based extraction of RFQ data from text, PDF and Excel sources.

Every extractor returns the same shape:
    {"header": {field: value}, "lines": [ {line_no, part_number, description,
     quantity, unit, target_price, delivery_date} ], "source": "<file name>"}
"""
import re
from pathlib import Path

import openpyxl
import pdfplumber

from .parsing_utils import parse_date, parse_number, parse_quantity, detect_currency

# ---- header fields: label regexes (English + some German) -------------------
LABELS = {
    "rfq_id": r"RFQ\s*(?:No\.?|Number|Nr\.?|ID|Ref(?:erence)?\.?)|Request for Quotation\s*(?:No\.?|Number)?|Anfrage[\s\-]*(?:Nr\.?|Nummer)|Reference",
    "requester_company": r"Company|Customer|Requester|Buyer Company|Firma|Kunde",
    "contact_name": r"Contact(?: Person)?|Buyer|Ansprechpartner|Name",
    "contact_email": r"E-?mail|Contact E-?mail",
    "country": r"Country|Land",
    "rfq_date": r"RFQ Date|Issue Date|Date|Datum",
    "deadline": r"Quot(?:e|ation) Deadline|Response Deadline|Quote Due|Due Date|Submit(?:ted)? By|Deadline|Bid Due|Angebotsfrist",
    "incoterms": r"Incoterms?",
    "currency": r"Currency|W\u00e4hrung",
    "payment_terms": r"Payment Terms?|Zahlungsbedingungen",
    "delivery_location": r"Delivery (?:Location|Address|To)|Ship To|Lieferort",
}
DATE_FIELDS = {"rfq_date", "deadline"}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# ---- line-item columns (for tables) -----------------------------------------
COLS = {
    "line_no": r"^(?:pos\.?|line|item|no\.?|#)$",
    "part_number": r"part\s*(?:no\.?|number)|p/n|material|article|artikel|sku|item code|ref",
    "description": r"description|bezeichnung|designation",
    "quantity": r"qty|quantity|menge",
    "unit": r"^unit$|uom|einheit",
    "target_price": r"target price|price|preis",
    "delivery_date": r"delivery date|required date|need by|lieferdatum|requested delivery",
}

KNOWN_UNITS = {"pcs", "pc", "ea", "unit", "units", "set", "sets", "stk", "st", "kg", "m"}

# one text line like: "10 | BKR6E-11 | Spark plug | 500 pcs | 1.85 | 2026-12-01"
LINE_RE = re.compile(
    r"^\s*(?P<line_no>\d{1,3})[\s|;]+"
    r"(?P<part>(?=[A-Z0-9\-/\.]*\d)[A-Z0-9][A-Z0-9\-/\.]{3,})[\s|;]+"
    r"(?P<desc>.+?)[\s|;]+"
    r"(?P<qty>\d[\d.,]*)[\s|;]*(?P<unit>[A-Za-z]{2,6})\b"
    r"(?:[\s|;]+(?:[A-Z]{3}\s*|[\u20ac$]\s*)?(?P<price>\d[\d.,]*))?"
    r"(?:[\s|;]+(?P<date>\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4}))?",
    re.I,
)


def _empty():
    return {"header": {}, "lines": [], "source": ""}


# ---------------------------------------------------------------------------
def extract_header_from_text(text):
    header = {}
    for field, labels in LABELS.items():
        m = re.search(rf"(?im)^[ \t>*-]*(?:{labels})[ \t]*:[ \t]*(.+?)[ \t]*$", text)
        if m:
            header[field] = m.group(1).strip()
    # subject-line fallback for the RFQ id
    if "rfq_id" not in header:
        m = re.search(r"(?i)\bRFQ[\s\-#:]*([A-Z0-9][A-Z0-9\-/]{4,})", text)
        if m:
            header["rfq_id"] = m.group(1)
    if "contact_email" not in header:
        m = EMAIL_RE.search(text)
        if m:
            header["contact_email"] = m.group(0)
    if "currency" not in header:
        cur = detect_currency(text)
        if cur:
            header["currency"] = cur
    return _normalise_header(header)


def _normalise_header(h):
    out = {}
    for k, v in h.items():
        if v in (None, ""):
            continue
        out[k] = parse_date(v) if k in DATE_FIELDS else str(v).strip()
        if out[k] is None:
            del out[k]
    if "contact_email" in out:
        m = EMAIL_RE.search(out["contact_email"])
        out["contact_email"] = m.group(0).lower() if m else out["contact_email"]
    if "currency" in out:
        out["currency"] = detect_currency(out["currency"]) or out["currency"].upper()[:3]
    return out


def extract_lines_from_text(text):
    lines = []
    for raw in text.splitlines():
        m = LINE_RE.match(raw)
        if m:
            lines.append({
                "line_no": int(m["line_no"]),
                "part_number": m["part"].upper(),
                "description": m["desc"].strip(" |;"),
                "quantity": parse_quantity(m["qty"]),
                "unit": m["unit"].lower() if m["unit"].lower() in KNOWN_UNITS else "pcs",  # OCR noise ('pes') -> pcs
                "target_price": parse_number(m["price"]),
                "delivery_date": parse_date(m["date"]),
            })
    return lines


def extract_from_text(text, source=""):
    r = _empty()
    r["header"] = extract_header_from_text(text)
    r["lines"] = extract_lines_from_text(text)
    r["source"] = source
    r["text"] = text
    return r


# ---------------------------------------------------------------------------
def _map_header_row(cells):
    """Return {col_index: field} if this row looks like a line-item table header."""
    mapping = {}
    for i, c in enumerate(cells):
        t = str(c or "").strip().lower()
        if not t:
            continue
        for field, pat in COLS.items():
            if field not in mapping.values() and re.search(pat, t):
                mapping[i] = field
                break
    return mapping if {"part_number", "quantity"} <= set(mapping.values()) else None


def _rows_to_lines(rows):
    lines, mapping = [], None
    for row in rows:
        if mapping is None:
            mapping = _map_header_row(row)
            continue
        rec = {f: row[i] if i < len(row) else None for i, f in mapping.items()}
        if not rec.get("part_number") or parse_quantity(rec.get("quantity")) is None:
            continue
        lines.append({
            "line_no": parse_number(rec.get("line_no")) or len(lines) + 1,
            "part_number": str(rec["part_number"]).strip().upper(),
            "description": (str(rec.get("description") or "")).replace("\n", " ").strip(),
            "quantity": parse_quantity(rec.get("quantity")),
            "unit": (str(rec.get("unit") or "pcs")).strip().lower(),
            "target_price": parse_number(rec.get("target_price")),
            "delivery_date": parse_date(rec.get("delivery_date")),
        })
    return lines


def extract_from_pdf(path):
    path = Path(path)
    r = _empty()
    r["source"] = path.name
    text_parts, table_lines = [], []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text_parts.append(page.extract_text() or "")
            for table in page.extract_tables():
                table_lines += _rows_to_lines(table)
    text = "\n".join(text_parts)
    if len(text.strip()) < 30:                      # image-only PDF -> try free OCR (Tesseract)
        from .ocr import ocr_pdf
        ocr_text = ocr_pdf(path)
        if ocr_text.strip():
            text, table_lines = ocr_text, []
            r["ocr_used"] = True
    r["text"] = text
    r["header"] = extract_header_from_text(text)
    r["lines"] = table_lines or extract_lines_from_text(text)
    r["scanned_pdf_suspected"] = len(text.strip()) < 30
    return r


def extract_from_excel(path):
    path = Path(path)
    r = _empty()
    r["source"] = path.name
    wb = openpyxl.load_workbook(path, data_only=True)
    header_raw, rows_all = {}, []
    for ws in wb.worksheets:
        rows = [[c for c in row] for row in ws.iter_rows(values_only=True)]
        rows_all += rows
        for row in rows:
            cells = [c for c in row if c not in (None, "")]
            if len(cells) < 2 or _map_header_row(row):
                continue
            label = str(cells[0]).strip().rstrip(":")
            for field, labels in LABELS.items():
                if field not in header_raw and re.fullmatch(labels, label, re.I):
                    header_raw[field] = cells[1]
                    break
    r["header"] = _normalise_header(header_raw)
    r["lines"] = _rows_to_lines(rows_all)
    if "currency" not in r["header"]:
        blob = " ".join(str(c) for row in rows_all for c in row if c)
        cur = detect_currency(blob)
        if cur:
            r["header"]["currency"] = cur
    return r


# ---------------------------------------------------------------------------
def merge(records):
    """Combine several extractions of one RFQ (email body + attachments).
    Attachments (PDF/Excel) take priority over the email body for conflicts."""
    merged = {"header": {}, "lines": [], "sources": [], "text": "\n\n".join(r.get("text", "") for r in records)}
    for rec in records:  # records are ordered: attachments first, body last
        merged["sources"].append(rec["source"])
        for k, v in rec["header"].items():
            merged["header"].setdefault(k, v)
        if rec["lines"] and not merged["lines"]:
            merged["lines"] = rec["lines"]
    merged["scanned_pdf_suspected"] = any(r.get("scanned_pdf_suspected") for r in records)
    merged["ocr_used"] = any(r.get("ocr_used") for r in records)
    return merged
