"""Local LLM helper (Ollama). Used for (1) filling fields the rules missed and (2) polishing drafts.
The LLM never decides prices or suppliers; it only reads and writes text."""
import json
import urllib.request
from datetime import date

from . import config
from .parsing_utils import parse_date, parse_number, parse_quantity

HEADER_KEYS = ["rfq_id", "requester_company", "contact_name", "contact_email", "country",
               "rfq_date", "deadline", "incoterms", "currency", "payment_terms", "delivery_location"]

EXTRACT_PROMPT = """You extract data from a customer's Request for Quotation (RFQ) in any language.
Today is {today}. Return ONLY valid JSON in exactly this shape:
{{"header": {{"rfq_id": null, "requester_company": null, "contact_name": null, "contact_email": null,
 "country": null, "rfq_date": null, "deadline": null, "incoterms": null, "currency": null,
 "payment_terms": null, "delivery_location": null}},
 "lines": [{{"line_no": 1, "part_number": null, "description": null, "quantity": null,
 "unit": "pcs", "target_price": null, "delivery_date": null}}]}}
Rules: dates as YYYY-MM-DD (day-first when ambiguous, resolve words like "end of month" using today's date).
"deadline" = the date by which the supplier must send the quotation. "delivery_date" = when goods are wanted.
Use null when a value is not stated. Never guess or invent values. Part numbers exactly as written.

RFQ TEXT:
"""


def chat(prompt, json_mode=False, timeout=180):
    payload = {"model": config.OLLAMA_MODEL, "stream": False,
               "messages": [{"role": "user", "content": prompt}],
               "options": {"temperature": 0}}
    if json_mode:
        payload["format"] = "json"
    req = urllib.request.Request(config.OLLAMA_URL, json.dumps(payload).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)["message"]["content"]


def llm_extract(text):
    raw = chat(EXTRACT_PROMPT.format(today=date.today().isoformat()) + text[:12000], json_mode=True)
    return json.loads(raw)


def fill_missing(merged):
    """Adds ONLY what the rules missed. Records which fields came from the LLM so a human can verify them."""
    merged.setdefault("llm_fields", [])
    merged.setdefault("notes", [])
    try:
        data = llm_extract(merged.get("text", ""))
    except Exception as exc:  # Ollama not running, bad JSON, timeout ...
        merged["notes"].append(f"LLM unavailable: {type(exc).__name__}")
        return merged
    for k in HEADER_KEYS:
        v = (data.get("header") or {}).get(k)
        if v in (None, "", "null") or k in merged["header"]:
            continue
        val = parse_date(v) if k in ("rfq_date", "deadline") else str(v).strip()
        if val:
            merged["header"][k] = val.lower() if k == "contact_email" else val
            merged["llm_fields"].append(k)
    if not merged["lines"]:
        for i, ln in enumerate(data.get("lines") or [], 1):
            qty = parse_quantity(ln.get("quantity"))
            if ln.get("part_number") and qty is not None:
                merged["lines"].append({
                    "line_no": ln.get("line_no") or i,
                    "part_number": str(ln["part_number"]).upper().strip(),
                    "description": ln.get("description") or "",
                    "quantity": qty,
                    "unit": (ln.get("unit") or "pcs").lower(),
                    "target_price": parse_number(ln.get("target_price")),
                    "delivery_date": parse_date(ln.get("delivery_date")),
                })
        if merged["lines"]:
            merged["llm_fields"].append("lines")
    return merged
