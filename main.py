"""Usage:
    python main.py                        # process ./inbox once
    python main.py --fetch-email          # download unread RFQ emails (IMAP) first
    python main.py --watch                # keep running, check every 30 s (use --interval to change)
    python main.py --watch --llm          # also use the local Ollama model for messy RFQs
"""
import argparse
import os
import time
from datetime import datetime


def cycle(fetch, verbose):
    from rfq_pipeline import config
    from rfq_pipeline.pipeline import process_inbox
    if fetch:
        from rfq_pipeline.email_intake import fetch_unread
        n = fetch_unread()
        if n:
            print(f"[{datetime.now():%H:%M:%S}] fetched {n} new email(s)")
    stats = process_inbox(verbose=verbose)
    if verbose or stats["added"] or stats["errors"] or stats["duplicates"]:
        print(f"[{datetime.now():%H:%M:%S}] {stats}")
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch-email", action="store_true")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=int, default=30, help="seconds between checks")
    ap.add_argument("--llm", action="store_true", help="use local LLM (Ollama) for gaps and draft polishing")
    a = ap.parse_args()
    if a.llm:
        os.environ["RFQ_USE_LLM"] = "1"          # must be set before config is imported
    from rfq_pipeline import config
    if not a.watch:
        cycle(a.fetch_email, verbose=True)
        print(f"Database: {config.DB_PATH}\nWorkbook: {config.OUTPUT_XLSX}")
    else:
        print(f"Watching {config.INBOX} every {a.interval}s (LLM {'on' if config.USE_LLM else 'off'}). Ctrl+C to stop.")
        while True:
            try:
                cycle(a.fetch_email, verbose=False)
            except Exception as exc:               # network/IMAP hiccups must not kill the watcher
                print(f"[{datetime.now():%H:%M:%S}] error: {exc}")
            time.sleep(a.interval)
