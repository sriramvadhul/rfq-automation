"""Central settings. Environment variables override where noted."""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
INBOX = BASE / "inbox"                       # drop .eml / .pdf / .xlsx / .txt files here
ATTACHMENT_DIR = INBOX / "attachments"
DATA_DIR = BASE / "data"                     # part master, supplier prices, margin rules
TESTSET_DIR = BASE / "testset"
DB_PATH = BASE / "output" / "rfq.db"         # source of truth (SQLite)
OUTPUT_XLSX = BASE / "output" / "RFQ_Master.xlsx"   # rebuilt from the database after each cycle

# --- validation ---
REQUIRED_HEADER_FIELDS = ["rfq_id", "requester_company", "contact_email", "deadline"]
MATCH_CUTOFF = 0.84          # fuzzy part-number match threshold (1.0 = exact)
MAX_SANE_QTY = 100_000

# --- decision engine ---
MIN_MARGIN = 0.10            # never offer below this margin (on selling price)
DEFAULT_TARGET_MARGIN = 0.20
TRANSIT_BUFFER_DAYS = 3      # shipping time added on top of supplier lead time
DECISION_WEIGHTS = {"cost": 0.5, "lead_time": 0.3, "reliability": 0.2}
SENDER_NAME = os.getenv("RFQ_SENDER", "Sales Team")

# --- local LLM (Ollama, free). Off by default ---
USE_LLM = os.getenv("RFQ_USE_LLM", "0") == "1"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

# --- IMAP (use an app password; set via environment variables) ---
IMAP_HOST = os.getenv("RFQ_IMAP_HOST", "imap.gmail.com")
IMAP_USER = os.getenv("RFQ_IMAP_USER", "")
IMAP_PASSWORD = os.getenv("RFQ_IMAP_PASSWORD", "")
IMAP_FOLDER = os.getenv("RFQ_IMAP_FOLDER", "INBOX")
