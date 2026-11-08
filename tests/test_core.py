"""Run:  python tests/test_core.py   (or: python -m pytest -q tests)"""
import json
import shutil
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))

import pandas as pd

from rfq_pipeline import config, db
from rfq_pipeline.decision import decide_rfq
from rfq_pipeline.drafting import numbers_ok
from rfq_pipeline.extractor import extract_from_text
from rfq_pipeline.parsing_utils import parse_date, parse_number, parse_quantity
from rfq_pipeline.pipeline import process_inbox


def sandbox():
    tmp = Path(tempfile.mkdtemp())
    config.ATTACHMENT_DIR = tmp / "att"; config.DB_PATH = tmp / "rfq.db"
    return tmp


def test_parsing():
    assert parse_number("1.850,00") == 1850 and parse_number("2.35") == 2.35 and parse_number("abc") is None
    assert parse_quantity("1.500") == 1500 and parse_quantity("1,500") == 1500 and parse_quantity("2.5") == 2.5
    assert parse_date("2026-12-01") == date(2026, 12, 1) and parse_date("15.12.2026") == date(2026, 12, 15)
    assert parse_date("04/11/2026") == date(2026, 11, 4)


def test_text_extraction():
    r = extract_from_text("RFQ Number: RFQ-9\nCompany: ACME GmbH\nQuotation Deadline: 20.11.2026\n"
                          "10 | BKR6E-11 | Spark plug | 1.500 pcs | 1,85\n")
    assert r["header"]["rfq_id"] == "RFQ-9" and r["header"]["deadline"] == date(2026, 11, 20)
    assert r["lines"][0]["quantity"] == 1500 and r["lines"][0]["target_price"] == 1.85


def _line(**kw):
    base = {"line_no": 10, "part_number": "X1", "quantity": 100, "unit": "pcs", "target_price": None,
            "delivery_date": None, "flags": [], "matched": {"part_number": "X1", "category": "Spark plug"}}
    return {**base, **kw}


SUP = pd.DataFrame([{"part_number": "X1", "supplier": "Fast", "unit_cost": 2.0, "lead_time_days": 5, "moq": 10, "reliability": .9},
                    {"part_number": "X1", "supplier": "Cheap", "unit_cost": 1.5, "lead_time_days": 40, "moq": 10, "reliability": .9}])
MARG = {"Spark plug": 0.20}


def test_decision_feasibility_and_pricing():
    today = date(2026, 11, 1)
    # slow supplier cannot meet a date 20 days away -> Fast wins even though Cheap is cheaper
    ln = _line(delivery_date=today + timedelta(days=20))
    res = decide_rfq([ln], SUP, MARG, today)
    assert ln["best_supplier"] == "Fast" and ln["offer_price"] == 2.5          # 2.0 / (1 - 0.20)
    # no date -> Cheap wins on combined score? (cost 0.5*1 + lead 0.3*0.125 + rel 0.2*0.9) vs Fast (0.5*0.75+0.3+0.18)
    ln2 = _line()
    decide_rfq([ln2], SUP, MARG, today)
    assert ln2["best_supplier"] == "Fast"
    # customer target below minimum margin -> offered at the floor (10%)
    ln3 = _line(target_price=1.0)
    res3 = decide_rfq([ln3], SUP, MARG, today)
    assert ln3["offer_price"] == round(2.0 / 0.9, 2) and "minimum" in ln3["reason"]
    # nobody can make the date -> flagged, recommendation changes
    ln4 = _line(delivery_date=today + timedelta(days=4))
    res4 = decide_rfq([ln4], SUP, MARG, today)
    assert "cannot be met" in " ".join(ln4["flags"]) and "later delivery" in res4["recommendation"]
    assert res["margin_pct"] is not None


def test_draft_number_guard():
    base = "10. X1 - 100 pcs x 2.50 EUR = 250.00 EUR\nTotal: 250.00 EUR"
    assert numbers_ok(base, "Dear customer, 10. X1 - 100 pcs x 2.50 EUR = 250.00 EUR. Total: 250.00 EUR")
    assert not numbers_ok(base, "Dear customer, special price 2.10 EUR!")


def test_end_to_end_and_dedup():
    from make_testset import generate
    tmp = sandbox(); inbox = tmp / "inbox"
    generate(6, inbox)                          # one RFQ per format
    s = process_inbox(inbox, tmp / "rfq.db", tmp / "m.xlsx", use_llm=False, verbose=False)
    assert s["added"] == 6 and s["needs_review"] == 1 and s["errors"] == 0, s     # free-text needs the LLM
    assert (tmp / "m.xlsx").exists()
    assert process_inbox(inbox, tmp / "rfq.db", tmp / "m.xlsx", use_llm=False, verbose=False)["skipped"] == 6
    # same RFQ id re-sent with different bytes -> duplicate, not added twice
    eml = next(inbox.glob("00_*.eml"))
    (inbox / "resend.eml").write_bytes(eml.read_bytes().replace(b"Subject: RFQ", b"Subject: REMINDER RFQ"))
    s2 = process_inbox(inbox, tmp / "rfq.db", tmp / "m.xlsx", use_llm=False, verbose=False)
    assert s2["duplicates"] == 1 and s2["added"] == 0, s2
    conn = db.connect(tmp / "rfq.db")
    assert conn.execute("SELECT COUNT(*) FROM rfqs").fetchone()[0] == 6
    db.save_draft(conn, "RFQ-2026-3000", "edited"); db.set_human_status(conn, "RFQ-2026-3000", "Approved")
    assert conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 1
    conn.close()
    shutil.rmtree(tmp, ignore_errors=True)


def test_llm_fallback_with_mock_server():
    import mock_ollama
    from make_testset import generate
    tmp = sandbox(); inbox = tmp / "inbox"
    truth = generate(6, inbox)
    gt = truth["05_freetext.eml"]
    reply = {"header": {"rfq_id": None, "requester_company": gt["requester_company"], "contact_name": "Test",
                        "contact_email": None, "deadline": gt["deadline"]},
             "lines": [{"line_no": i + 1, "part_number": l["part_number"], "quantity": l["quantity"], "unit": "pcs"}
                       for i, l in enumerate(gt["lines"])]}
    srv, url = mock_ollama.start(reply)
    config.OLLAMA_URL = url
    for f in inbox.iterdir():                   # keep only the free-text email
        if f.name != "05_freetext.eml":
            f.unlink()
    s = process_inbox(inbox, tmp / "rfq.db", tmp / "m.xlsx", use_llm=True, verbose=False)
    conn = db.connect(tmp / "rfq.db")
    row = conn.execute("SELECT * FROM rfqs").fetchone()
    n_lines = conn.execute("SELECT COUNT(*) FROM lines").fetchone()[0]
    assert s["added"] == 1 and n_lines == len(gt["lines"]), (s, n_lines)
    assert "lines" in row["llm_fields"] and row["status"] == "Needs review"      # LLM output is always flagged
    assert row["requester"] == gt["requester_company"] and row["offer_value"] > 0
    conn.close(); srv.shutdown(); shutil.rmtree(tmp, ignore_errors=True)


def test_ocr_on_scanned_pdf():
    import shutil as sh
    import os
    if not (sh.which("tesseract") or os.path.exists("C:/Program Files/Tesseract-OCR/tesseract.exe")):
        print("SKIP test_ocr_on_scanned_pdf (Tesseract not installed)"); return
    import io
    import pymupdf
    from PIL import Image
    from make_testset import generate
    from rfq_pipeline.extractor import extract_from_pdf
    tmp = Path(tempfile.mkdtemp()); truth = generate(3, tmp)
    pdf = tmp / "02_pdf.pdf"
    png = pymupdf.open(str(pdf))[0].get_pixmap(dpi=200).tobytes("png")
    Image.open(io.BytesIO(png)).convert("RGB").save(tmp / "scan.pdf", resolution=200)   # image only, no text layer
    r = extract_from_pdf(tmp / "scan.pdf")
    want = {(l["part_number"], l["quantity"]) for l in truth["02_pdf.pdf"]["lines"]}
    assert r.get("ocr_used") and {(l["part_number"], l["quantity"]) for l in r["lines"]} == want
    assert r["header"]["rfq_id"] == truth["02_pdf.pdf"]["rfq_id"]
    shutil.rmtree(tmp, ignore_errors=True)


def test_dashboard_sees_new_rfqs_live():
    from streamlit.testing.v1 import AppTest
    from make_testset import generate
    tmp = sandbox(); inbox = tmp / "inbox"
    generate(6, inbox)
    files = sorted(p for p in inbox.iterdir() if p.suffix != ".json")
    hold = tmp / "later"; hold.mkdir()
    for f in files[3:]:
        shutil.move(f, hold / f.name)
    process_inbox(inbox, tmp / "rfq.db", tmp / "m.xlsx", use_llm=False, verbose=False)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not at.exception
    assert dict((m.label, m.value) for m in at.metric)["RFQs processed"] == "3"
    for f in hold.iterdir():                    # "new emails arrive"
        shutil.move(f, inbox / f.name)
    process_inbox(inbox, tmp / "rfq.db", tmp / "m.xlsx", use_llm=False, verbose=False)
    at.run()                                    # what the 5-second auto-refresh does
    assert dict((m.label, m.value) for m in at.metric)["RFQs processed"] == "6"
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("PASS", name)
    print("all tests passed")
