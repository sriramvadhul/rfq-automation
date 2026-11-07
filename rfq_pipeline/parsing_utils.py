"""Small helpers: dates, numbers, currency."""
import re
from datetime import date, datetime
from dateutil import parser as dtparser

ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def parse_date(value):
    """Return a date or None. Assumes European day-first for ambiguous input."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    m = ISO.search(s)
    if m:  # ISO first: dateutil's dayfirst flag misreads yyyy-mm-dd
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    try:
        return dtparser.parse(s, dayfirst=True, fuzzy=True).date()
    except (ValueError, OverflowError):
        return None


def parse_number(value):
    """'1,250' -> 1250 ; '1.850,00' -> 1850.0 ; '2.35' -> 2.35 ; None if not numeric."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return value
    s = re.sub(r"[^\d,.\-]", "", str(value))
    if not s or not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        thou = "." if dec == "," else ","
        s = s.replace(thou, "").replace(dec, ".")
    elif "," in s:
        s = s.replace(",", ".") if re.search(r",\d{1,2}$", s) else s.replace(",", "")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def parse_quantity(value):
    """Quantities: '1.500' and '1,500' are fifteen hundred, not 1.5."""
    if isinstance(value, (int, float)):
        return value
    s = str(value or "").strip()
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):
        return int(re.sub(r"[.,]", "", s))
    return parse_number(s)


CURRENCY_HINTS = [("EUR", r"\bEUR\b|€"), ("USD", r"\bUSD\b|\$"), ("GBP", r"\bGBP\b|£"),
                  ("JPY", r"\bJPY\b|¥"), ("PLN", r"\bPLN\b"), ("CHF", r"\bCHF\b")]


def detect_currency(text):
    for code, pat in CURRENCY_HINTS:
        if re.search(pat, text):
            return code
    return None
