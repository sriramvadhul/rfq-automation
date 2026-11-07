"""Orchestration: inbox file -> extract -> (LLM fill) -> match parts -> decide -> draft -> database -> Excel."""
import email
import hashlib
import re
import time
from datetime import date
from email import policy
from pathlib import Path

from . import config, db, export
from .decision import decide_rfq, load_reference
from .drafting import draft_quote
from .extractor import extract_from_excel, extract_from_pdf, extract_from_text, merge
from .validation import PartMaster, annotate_lines, validate_header

_EXPORT_PENDING = False   # set when Excel was locked; retried next cycle
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _extract_file(path: Path):
    ext = path.suffix.lower()
    if ext == ".pdf":
        return extract_from_pdf(path)
    if ext in (".xlsx", ".xlsm"):
        return extract_from_excel(path)
    return extract_from_text(path.read_text(errors="ignore"), path.name)


def extract_eml(path: Path):
    """Attachments first (they win conflicts), email body last."""
    msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    config.ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    for part in msg.iter_attachments():
        name = part.get_filename() or ""
        if name.lower().endswith((".pdf", ".xlsx", ".xlsm")):
            dest = config.ATTACHMENT_DIR / f"{path.stem}__{name}"
            dest.write_bytes(part.get_payload(decode=True))
            rec = _extract_file(dest)
            rec["source"] = f"{path.name}>{name}"
            records.append(rec)
    body = msg.get_body(preferencelist=("plain",))
    full = f"Subject: {msg['subject'] or ''}\nFrom: {msg['from'] or ''}\n\n{body.get_content() if body else ''}"
    rec = extract_from_text(full, path.name)
    if "contact_email" not in rec["header"]:
        m = EMAIL_RE.search(msg["from"] or "")
        if m:
            rec["header"]["contact_email"] = m.group(0).lower()
    records.append(rec)
    return merge(records)


def extract_any(path: Path):
    return extract_eml(path) if path.suffix.lower() == ".eml" else merge([_extract_file(path)])


def _process_one(path, h, conn, master, suppliers, margins, today, use_llm):
    t0 = time.time()
    merged = extract_any(path)
    hard = validate_header(merged)
    if use_llm and hard:
        from .llm_fallback import fill_missing
        merged = fill_missing(merged)
        hard = validate_header(merged)          # re-check after the LLM filled gaps
    hard += annotate_lines(merged["lines"], master)
    header = merged["header"]
    rfq_id = header.get("rfq_id") or f"UNKNOWN-{h[:6].upper()}"
    if db.rfq_exists(conn, rfq_id):
        db.log_event(conn, rfq_id, "warning", f"Duplicate RFQ id from {path.name} - not added again")
        return rfq_id, "duplicate"
    result = decide_rfq(merged["lines"], suppliers, margins, today)
    flags = [f for ln in merged["lines"] for f in ln["flags"]] + merged.get("notes", [])
    if header.get("currency") and header["currency"] != "EUR":
        flags.append(f"RFQ currency {header['currency']} - offer is in EUR, no FX applied")
    if merged.get("llm_fields"):
        flags.append("LLM-filled fields to verify: " + ", ".join(merged["llm_fields"]))
    status = "Needs review" if (hard or merged.get("llm_fields")) else "Ready"
    rec = {"rfq_id": rfq_id, "received_at": db.now(), "requester": header.get("requester_company"),
           "contact": header.get("contact_name"), "email": header.get("contact_email"),
           "country": header.get("country"), "rfq_date": header.get("rfq_date"), "deadline": header.get("deadline"),
           "incoterms": header.get("incoterms"), "currency": header.get("currency"),
           "payment_terms": header.get("payment_terms"), "delivery_location": header.get("delivery_location"),
           "status": status, "recommendation": result["recommendation"],
           "flags": "; ".join(dict.fromkeys(hard + flags)), "sources": ", ".join(merged["sources"]),
           "llm_fields": ", ".join(merged.get("llm_fields", [])), "offer_value": result["offer_value"],
           "cost_value": result["cost_value"], "margin_pct": result["margin_pct"]}
    rec["draft"] = draft_quote(rfq_id, header, merged["lines"], result["offer_value"], use_llm)
    rec["processing_seconds"] = round(time.time() - t0, 2)
    db.insert_rfq(conn, rec, merged["lines"], result["options"])
    db.log_event(conn, rfq_id, "info" if status == "Ready" else "review",
                 f"{path.name}: {status} - {result['recommendation']}" + (f" | {rec['flags']}" if hard else ""))
    return rfq_id, status


def process_inbox(inbox=None, db_path=None, xlsx=None, data_dir=None, today=None, use_llm=None, verbose=True):
    inbox = Path(inbox or config.INBOX)
    use_llm = config.USE_LLM if use_llm is None else use_llm
    data_dir = Path(data_dir or config.DATA_DIR)
    conn = db.connect(db_path)
    master = PartMaster(data_dir / "part_master.csv")
    suppliers, margins = load_reference(data_dir)
    stats = {"added": 0, "needs_review": 0, "duplicates": 0, "skipped": 0, "errors": 0}
    files = sorted(p for p in inbox.iterdir()
                   if p.is_file() and p.suffix.lower() in (".eml", ".pdf", ".xlsx", ".xlsm", ".txt"))
    for path in files:
        h = hashlib.sha256(path.read_bytes()).hexdigest()
        if db.file_seen(conn, h):
            stats["skipped"] += 1
            continue
        try:
            rfq_id, status = _process_one(path, h, conn, master, suppliers, margins, today or date.today(), use_llm)
            key = {"duplicate": "duplicates", "Needs review": "needs_review"}.get(status)
            stats["added" if status != "duplicate" else "duplicates"] += 1
            if key == "needs_review":
                stats["needs_review"] += 1
            if verbose:
                print(f"{path.name:36s} -> {rfq_id:18s} {status}")
        except Exception as exc:                      # a bad file must never stop the watcher
            stats["errors"] += 1
            db.log_event(conn, None, "error", f"{path.name}: {type(exc).__name__}: {exc}")
            if verbose:
                print(f"{path.name:36s} -> ERROR {exc}")
        db.mark_file(conn, h, path.name)
    global _EXPORT_PENDING
    if stats["added"] or stats["duplicates"] or stats["errors"] or _EXPORT_PENDING:
        try:
            export.export_workbook(conn, xlsx or config.OUTPUT_XLSX)
            _EXPORT_PENDING = False
        except PermissionError:
            _EXPORT_PENDING = True
            db.log_event(conn, None, "warning", "Excel file is open - export skipped, will retry next cycle")
    conn.close()
    return stats
