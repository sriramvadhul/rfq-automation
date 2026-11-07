"""Generate N FICTIONAL RFQs in six formats plus ground_truth.json (the correct answers).
    python make_testset.py --n 30            # writes to ./testset
    python make_testset.py --n 12 --out inbox   # drop straight into the inbox
Formats: email_en, email_de (German labels, European numbers), pdf, excel, email_pdf, freetext (no labels)."""
import argparse
import json
import random
from datetime import date, timedelta
from email.message import EmailMessage
from pathlib import Path

import openpyxl
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from make_reference_data import PARTS

CUSTOMERS = [("Autoteile Nord GmbH", "Germany", "Lena Brandt", "autoteile-nord.test"),
             ("Kfz-Handel Mueller GmbH", "Germany", "Hans Mueller", "kfz-mueller.test"),
             ("Mecanique Dupont SAS", "France", "Marie Dupont", "mecanique-dupont.test"),
             ("Iberia Recambios S.L.", "Spain", "Carlos Mendez", "iberia-recambios.test"),
             ("Auto Czesci Polska Sp. z o.o.", "Poland", "Piotr Nowak", "autoczesci.test"),
             ("Nordic Motor Parts AB", "Sweden", "Elin Berg", "nordic-motor.test"),
             ("Alpine Ersatzteile AG", "Switzerland", "Jonas Keller", "alpine-ersatz.test"),
             ("Benelux Car Supplies BV", "Netherlands", "Sanne de Vries", "benelux-car.test")]
FORMATS = ["email_en", "email_de", "pdf", "excel", "email_pdf", "freetext"]
QTYS = [100, 250, 500, 1000, 1500, 2400, 5000]


def make_rfq(i, rnd, today):
    comp, country, contact, dom = rnd.choice(CUSTOMERS)
    lines = []
    for n, part in enumerate(rnd.sample(PARTS, rnd.randint(1, 4)), 1):
        pn, desc, _, base = part
        lines.append({"line_no": n * 10, "part_number": pn, "description": desc, "quantity": rnd.choice(QTYS),
                      "target_price": round(base * rnd.uniform(1.0, 1.6), 2),
                      "delivery_date": today + timedelta(days=rnd.randint(14, 70))})
    return {"rfq_id": f"RFQ-2026-{3000 + i}", "requester_company": comp, "country": country,
            "contact_name": contact, "contact_email": f"{contact.split()[0].lower()}@{dom}",
            "rfq_date": today - timedelta(days=rnd.randint(0, 4)),
            "deadline": today + timedelta(days=rnd.randint(1, 25)),
            "incoterms": rnd.choice(["DAP", "FCA", "EXW"]), "currency": "EUR",
            "payment_terms": rnd.choice(["30 days net", "45 days net", "60 days net"]),
            "delivery_location": f"{country} warehouse", "lines": lines}


def save_eml(path, subject, sender, body, attach=None):
    m = EmailMessage()
    m["Subject"], m["From"], m["To"] = subject, sender, "rfq@example-supplier.test"
    m.set_content(body)
    if attach:
        m.add_attachment(Path(attach).read_bytes(), maintype="application", subtype="pdf", filename=Path(attach).name)
    Path(path).write_bytes(bytes(m))


def body_en(r):
    rows = "\n".join(f"{l['line_no']} | {l['part_number']} | {l['description']} | {l['quantity']} pcs | "
                     f"{l['target_price']:.2f} | {l['delivery_date']}" for l in r["lines"])
    return (f"Dear Sir or Madam,\n\nplease quote for the items below.\n\nRFQ Number: {r['rfq_id']}\n"
            f"Company: {r['requester_company']}\nContact Person: {r['contact_name']}\nE-Mail: {r['contact_email']}\n"
            f"Country: {r['country']}\nDate: {r['rfq_date']}\nQuotation Deadline: {r['deadline']}\n"
            f"Incoterms: {r['incoterms']}\nCurrency: EUR\nPayment Terms: {r['payment_terms']}\n"
            f"Delivery Location: {r['delivery_location']}\n\nPos | Part No | Description | Qty | Target Price | Delivery Date\n"
            f"{rows}\n\nBest regards\n{r['contact_name']}\n")


def body_de(r):
    de = lambda d: d.strftime("%d.%m.%Y")
    rows = "\n".join(f"{l['line_no']} | {l['part_number']} | {l['description']} | {l['quantity']:,} pcs".replace(",", ".")
                     + f" | {str(l['target_price']).replace('.', ',')} | {de(l['delivery_date'])}" for l in r["lines"])
    return (f"Sehr geehrte Damen und Herren,\n\nbitte senden Sie uns ein Angebot.\n\nAnfrage-Nr: {r['rfq_id']}\n"
            f"Firma: {r['requester_company']}\nAnsprechpartner: {r['contact_name']}\nE-Mail: {r['contact_email']}\n"
            f"Land: {r['country']}\nDatum: {de(r['rfq_date'])}\nAngebotsfrist: {de(r['deadline'])}\n"
            f"Incoterms: {r['incoterms']}\nW\u00e4hrung: EUR\nZahlungsbedingungen: {r['payment_terms']}\n"
            f"Lieferort: {r['delivery_location']}\n\nPos | Artikel | Bezeichnung | Menge | Preis | Lieferdatum\n{rows}\n\n"
            f"Mit freundlichen Gruessen\n{r['contact_name']}\n")


def body_free(r):
    items = " and ".join(f"{l['quantity']} x {l['part_number']}" for l in r["lines"])
    d = r["lines"][0]["delivery_date"]
    return (f"Hi team,\n\ncould you please quote {items}? We need the goods by {d.strftime('%d %B %Y')}. "
            f"Please get back to us by {r['deadline'].strftime('%d %B %Y')}.\n\nThanks,\n{r['contact_name']}\n"
            f"{r['requester_company']}\n")


def make_pdf(path, r):
    st = getSampleStyleSheet()
    meta = [f"RFQ Number: {r['rfq_id']}", f"Company: {r['requester_company']}", f"Contact Person: {r['contact_name']}",
            f"Email: {r['contact_email']}", f"Country: {r['country']}", f"RFQ Date: {r['rfq_date']}",
            f"Quotation Deadline: {r['deadline']}", f"Incoterms: {r['incoterms']}", "Currency: EUR",
            f"Payment Terms: {r['payment_terms']}"]
    data = [["Pos", "Part Number", "Description", "Qty", "Unit", "Target Price", "Delivery Date"]] + \
           [[l["line_no"], l["part_number"], l["description"], f"{l['quantity']:,}", "pcs",
             f"{l['target_price']:.2f}", str(l["delivery_date"])] for l in r["lines"]]
    t = Table(data, repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.6, colors.black), ("FONTSIZE", (0, 0), (-1, -1), 8)]))
    SimpleDocTemplate(str(path), pagesize=A4).build(
        [Paragraph("REQUEST FOR QUOTATION", st["Title"])] + [Paragraph(x, st["Normal"]) for x in meta] + [Spacer(1, 12), t])


def make_excel(path, r):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "RFQ"
    kv = [("RFQ No.", r["rfq_id"]), ("Company", r["requester_company"]), ("Contact", r["contact_name"]),
          ("E-mail", r["contact_email"]), ("Country", r["country"]), ("RFQ Date", r["rfq_date"].strftime("%d/%m/%Y")),
          ("Quote Deadline", r["deadline"].strftime("%d/%m/%Y")), ("Incoterms", r["incoterms"]),
          ("Currency", "EUR"), ("Payment Terms", r["payment_terms"]), ("Delivery To", r["delivery_location"])]
    for i, (k, v) in enumerate(kv, 1):
        ws.cell(row=i, column=1, value=k + ":")
        ws.cell(row=i, column=2, value=v)
    for c, h in enumerate(["Item", "Part Number", "Description", "Qty", "Unit", "Target Price", "Delivery Date"], 1):
        ws.cell(row=14, column=c, value=h)
    for i, l in enumerate(r["lines"], 15):
        for c, v in enumerate([l["line_no"], l["part_number"], l["description"], l["quantity"], "pcs",
                               l["target_price"], l["delivery_date"].strftime("%d/%m/%Y")], 1):
            ws.cell(row=i, column=c, value=v)
    wb.save(path)


def generate(n, out, seed=42, today=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rnd, today, truth = random.Random(seed), today or date.today(), {}
    for i in range(n):
        fmt, r = FORMATS[i % len(FORMATS)], make_rfq(i, rnd, today)
        sender = f"{r['contact_name']} <{r['contact_email']}>"
        name = f"{i:02d}_{fmt}"
        if fmt == "email_en":
            fname = f"{name}.eml"; save_eml(out / fname, f"RFQ {r['rfq_id']}", sender, body_en(r))
        elif fmt == "email_de":
            fname = f"{name}.eml"; save_eml(out / fname, f"Anfrage {r['rfq_id']}", sender, body_de(r))
        elif fmt == "pdf":
            fname = f"{name}.pdf"; make_pdf(out / fname, r)
        elif fmt == "excel":
            fname = f"{name}.xlsx"; make_excel(out / fname, r)
        elif fmt == "email_pdf":
            pdf = out / f"_att_{i:02d}.pdf"; make_pdf(pdf, r)
            att = out / f"rfq_{r['rfq_id']}.pdf"; pdf.rename(att)
            fname = f"{name}.eml"; save_eml(out / fname, "RFQ attached", sender, "Hello, please find our RFQ attached.", att)
            att.unlink()
        else:
            fname = f"{name}.eml"; save_eml(out / fname, "quote request", sender, body_free(r))
            r["rfq_id"] = None                      # free-text emails carry no RFQ number
            r["deadline"] = r["deadline"]
        truth[fname] = {"format": fmt, "rfq_id": r["rfq_id"], "requester_company": r["requester_company"],
                        "contact_email": r["contact_email"], "deadline": r["deadline"].isoformat(),
                        "lines": [{"part_number": l["part_number"], "quantity": l["quantity"]} for l in r["lines"]]}
    (out / "ground_truth.json").write_text(json.dumps(truth, indent=1))
    return truth


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--out", default="testset")
    a = ap.parse_args()
    t = generate(a.n, a.out)
    print(f"{len(t)} RFQs written to {a.out}/ (ground_truth.json = correct answers)")
