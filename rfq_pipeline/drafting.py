"""Quote email drafts. The numbers come from the decision engine; an optional local LLM may polish the
wording, but its output is discarded if it contains any number that is not in the template."""
import re

from . import config


def template_draft(rfq_id, header, lines, offer_value):
    name = header.get("contact_name") or "Sir or Madam"
    rows, notes = [], []
    for ln in lines:
        if ln.get("offer_price") is None:
            rows.append(f"{ln['line_no']}. {ln['part_input']} - price to be confirmed")
            continue
        days = ln["lead_time_days"] + config.TRANSIT_BUFFER_DAYS
        total = ln["quantity"] * ln["offer_price"]
        rows.append(f"{ln['line_no']}. {ln['part_number']} ({ln.get('description') or ''}) - "
                    f"{ln['quantity']:,.0f} {ln['unit']} x {ln['offer_price']:.2f} EUR = {total:,.2f} EUR, "
                    f"delivery in about {days} days")
        if any("cannot be met" in f for f in ln["flags"]):
            notes.append(f"Line {ln['line_no']}: your requested delivery date cannot be met; the date above is our earliest.")
    terms = []
    if header.get("incoterms"):
        terms.append(f"Incoterms: {header['incoterms']}")
    if header.get("payment_terms"):
        terms.append(f"Payment terms: {header['payment_terms']}")
    body = [f"Subject: Quotation for {rfq_id}", "", f"Dear {name},", "",
            f"Thank you for your request {rfq_id}. We are pleased to offer:", ""] + rows + \
           ["", f"Total: {offer_value:,.2f} EUR (prices in EUR, excl. VAT)"]
    if terms:
        body += ["", "; ".join(terms)]
    if notes:
        body += [""] + notes
    body += ["", "This offer is valid for 30 days.", "", "Best regards,", config.SENDER_NAME]
    return "\n".join(body)


NUM = re.compile(r"\d[\d,]*\.?\d*")


def numbers_ok(original, rewritten):
    """Every number in the LLM version must also be in the template (no invented figures)."""
    norm = lambda t: {n.replace(",", "") for n in NUM.findall(t)}
    return norm(rewritten) <= norm(original)


def draft_quote(rfq_id, header, lines, offer_value, use_llm=False):
    base = template_draft(rfq_id, header, lines, offer_value)
    if not use_llm:
        return base
    try:
        from .llm_fallback import chat
        out = chat("Rewrite this quotation email to sound polished and friendly. Keep every number, part number, "
                   "date and term exactly as written. Do not add facts. Return only the email text.\n\n" + base)
        return out.strip() if numbers_ok(base, out) and "Subject:" in out else base
    except Exception:
        return base
