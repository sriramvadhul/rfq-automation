"""SQLite storage: the single source of truth. Excel is rebuilt from it; the dashboard reads it."""
import sqlite3
from datetime import datetime
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS rfqs(
  rfq_id TEXT PRIMARY KEY, received_at TEXT, requester TEXT, contact TEXT, email TEXT, country TEXT,
  rfq_date TEXT, deadline TEXT, incoterms TEXT, currency TEXT, payment_terms TEXT, delivery_location TEXT,
  status TEXT, recommendation TEXT, flags TEXT, sources TEXT, llm_fields TEXT,
  offer_value REAL, cost_value REAL, margin_pct REAL, draft TEXT,
  human_status TEXT DEFAULT 'Pending', reviewed_at TEXT, processing_seconds REAL);
CREATE TABLE IF NOT EXISTS lines(
  id INTEGER PRIMARY KEY AUTOINCREMENT, rfq_id TEXT, line_no INTEGER, part_input TEXT, part_number TEXT,
  description TEXT, qty REAL, unit TEXT, target_price REAL, delivery_date TEXT, match_score REAL,
  best_supplier TEXT, unit_cost REAL, offer_price REAL, margin_pct REAL, lead_time_days INTEGER,
  reason TEXT, flags TEXT);
CREATE TABLE IF NOT EXISTS options(
  id INTEGER PRIMARY KEY AUTOINCREMENT, rfq_id TEXT, line_no INTEGER, supplier TEXT, unit_cost REAL,
  lead_time_days INTEGER, moq INTEGER, reliability REAL, feasible INTEGER, score REAL, chosen INTEGER);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, rfq_id TEXT, level TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS feedback(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, rfq_id TEXT, field TEXT, old_value TEXT, new_value TEXT);
CREATE TABLE IF NOT EXISTS processed_files(hash TEXT PRIMARY KEY, name TEXT, ts TEXT);
"""


def now():
    return datetime.now().isoformat(timespec="seconds")


def connect(path=None):
    path = Path(path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # dashboard can read while the watcher writes
    conn.executescript(SCHEMA)
    return conn


def iso(d):
    return d.isoformat() if hasattr(d, "isoformat") else d


def rfq_exists(conn, rfq_id):
    return conn.execute("SELECT 1 FROM rfqs WHERE rfq_id=?", (rfq_id,)).fetchone() is not None


def file_seen(conn, h):
    return conn.execute("SELECT 1 FROM processed_files WHERE hash=?", (h,)).fetchone() is not None


def mark_file(conn, h, name):
    conn.execute("INSERT OR IGNORE INTO processed_files VALUES (?,?,?)", (h, name, now()))
    conn.commit()


def log_event(conn, rfq_id, level, message):
    conn.execute("INSERT INTO events(ts,rfq_id,level,message) VALUES (?,?,?,?)", (now(), rfq_id, level, message))
    conn.commit()


def insert_rfq(conn, rec, lines, options):
    cols = ["rfq_id", "received_at", "requester", "contact", "email", "country", "rfq_date", "deadline",
            "incoterms", "currency", "payment_terms", "delivery_location", "status", "recommendation",
            "flags", "sources", "llm_fields", "offer_value", "cost_value", "margin_pct", "draft",
            "processing_seconds"]
    conn.execute(f"INSERT INTO rfqs({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                 [iso(rec.get(c)) for c in cols])
    for ln in lines:
        conn.execute("""INSERT INTO lines(rfq_id,line_no,part_input,part_number,description,qty,unit,target_price,
                        delivery_date,match_score,best_supplier,unit_cost,offer_price,margin_pct,lead_time_days,reason,flags)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     [rec["rfq_id"], ln["line_no"], ln["part_input"], ln.get("part_number"), ln.get("description"),
                      ln["quantity"], ln["unit"], ln["target_price"], iso(ln["delivery_date"]), ln.get("match_score"),
                      ln.get("best_supplier"), ln.get("unit_cost"), ln.get("offer_price"), ln.get("margin_pct"),
                      ln.get("lead_time_days"), ln.get("reason"), "; ".join(ln.get("flags", []))])
    for o in options:
        conn.execute("""INSERT INTO options(rfq_id,line_no,supplier,unit_cost,lead_time_days,moq,reliability,feasible,score,chosen)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                     [rec["rfq_id"], o["line_no"], o["supplier"], o["unit_cost"], o["lead_time_days"], o["moq"],
                      o["reliability"], int(o["feasible"]), o["score"], int(o["chosen"])])
    conn.commit()


def set_human_status(conn, rfq_id, status):
    conn.execute("UPDATE rfqs SET human_status=?, reviewed_at=? WHERE rfq_id=?", (status, now(), rfq_id))
    conn.commit()


def save_draft(conn, rfq_id, new_text):
    """Saving an edited draft also records the human correction (feedback loop)."""
    old = conn.execute("SELECT draft FROM rfqs WHERE rfq_id=?", (rfq_id,)).fetchone()["draft"]
    if old != new_text:
        conn.execute("INSERT INTO feedback(ts,rfq_id,field,old_value,new_value) VALUES (?,?,?,?,?)",
                     (now(), rfq_id, "draft", old, new_text))
        conn.execute("UPDATE rfqs SET draft=? WHERE rfq_id=?", (new_text, rfq_id))
        conn.commit()
