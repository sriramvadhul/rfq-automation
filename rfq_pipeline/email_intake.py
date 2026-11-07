"""Pull unread emails over IMAP and save them as .eml files in the inbox folder.
Gmail: enable 2-step verification, create an App Password, set env vars
RFQ_IMAP_USER / RFQ_IMAP_PASSWORD. Outlook/Office365 company mailboxes often block IMAP
basic auth - ask IT or use the Graph API instead."""
import imaplib
import re

from . import config


def fetch_unread(subject_filter="RFQ"):
    if not (config.IMAP_USER and config.IMAP_PASSWORD):
        raise SystemExit("Set RFQ_IMAP_USER and RFQ_IMAP_PASSWORD environment variables first.")
    config.INBOX.mkdir(parents=True, exist_ok=True)
    saved = 0
    with imaplib.IMAP4_SSL(config.IMAP_HOST) as imap:
        imap.login(config.IMAP_USER, config.IMAP_PASSWORD)
        imap.select(config.IMAP_FOLDER)
        _, data = imap.search(None, "UNSEEN", "SUBJECT", f'"{subject_filter}"')
        for num in data[0].split():
            _, msg_data = imap.fetch(num, "(RFC822)")
            raw = msg_data[0][1]
            name = re.sub(r"[^\w.-]", "_", f"mail_{num.decode()}.eml")
            (config.INBOX / name).write_bytes(raw)
            imap.store(num, "+FLAGS", "\\Seen")
            saved += 1
    return saved
