"""Harder FICTIONAL free-text RFQs with ground truth.  Run:
    python make_hard_testset.py --n 5          # 5 emails per variant -> ./testset_hard
    python evaluate.py --dir testset_hard --llm
Variants: short, german_free, part_format, thread, vague_date, bullet_list, footer_noise.
Ground truth uses null where the email does NOT state a value: inventing one counts as an error."""
import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

from make_testset import CUSTOMERS, PARTS, save_eml

DE = "%d.%m.%Y"


def eom_next(today):
    """Last day of next month."""
    y, m = today.year, today.month + 2
    if m > 12:
        y, m = y + 1, m - 12
    return date(y, m, 1) - timedelta(days=1)


def pick(rnd, k):
    return [(p[0], rnd.choice([100, 250, 500, 1000, 1500, 2400])) for p in rnd.sample(PARTS, k)]


def v_short(c, items, d, dl, today, rnd):
    (p, q), first = items[0], c["name"].split()[0]
    return "urgent", f"Hi, need {q} {p} asap.\n\n{first}", None, None, [(p, q)]


def v_german_free(c, items, d, dl, today, rnd):
    its = " und ".join(f"{q} St\u00fcck {p}" for p, q in items)
    body = (f"Guten Tag,\n\nbitte senden Sie uns ein Angebot f\u00fcr {its}. Wir ben\u00f6tigen die Ware bis zum {d.strftime(DE)}. "
            f"Das Angebot erwarten wir bis sp\u00e4testens {dl.strftime(DE)}.\n\nFreundliche Gr\u00fc\u00dfe\n{c['name']}\n{c['company']}")
    return "Anfrage", body, c["company"], dl, items


def v_part_format(c, items, d, dl, today, rnd):
    def fmt(p):
        return rnd.choice([p.lower(), p.replace("-", " "), p.replace("-", ""), p])
    its = " and ".join(f"{q} pcs {fmt(p)}" for p, q in items)
    body = (f"Hello,\n\nplease quote {its}, delivery by {d.strftime(DE)}. Reply by {dl.strftime(DE)} please.\n"
            f"Regards\n{c['name']}, {c['company']}")
    return "quote please", body, c["company"], dl, items


def v_thread(c, items, d, dl, today, rnd):
    (p, q) = items[0]
    old_p = next(x[0] for x in PARTS if x[0] != p)
    body = (f"Yes, please go ahead and quote {q} x {p}. We need your offer by {dl.strftime('%d %B %Y')}.\n\n"
            f"{c['name']}\n{c['company']}\n\nOn {(today - timedelta(days=20)).strftime(DE)} Sales wrote:\n"
            f"> Hello {c['name'].split()[0]},\n> here is our earlier enquiry. Quotation Deadline: {(today - timedelta(days=20)).isoformat()}\n"
            f"> At that time we asked about 100 x {old_p}.")
    return "Re: enquiry", body, c["company"], dl, [(p, q)]


def v_vague_date(c, items, d, dl, today, rnd):
    (p, q) = items[0]
    body = (f"Hello,\n\nwe would like a quotation for {q} x {p}. Please send it by the end of next month.\n\n"
            f"Best\n{c['name']}\n{c['company']}")
    return "quotation", body, c["company"], eom_next(today), [(p, q)]


def v_bullet_list(c, items, d, dl, today, rnd):
    styles = [lambda p, q: f"- {p} x{q}", lambda p, q: f"- {p} ({q} pcs)", lambda p, q: f"* {q} pcs of {p}"]
    rows = "\n".join(rnd.choice(styles)(p, q) for p, q in items)
    body = (f"Hi,\n\nwe need the following:\n{rows}\n\nPlease quote by {dl.isoformat()}.\n"
            f"Thanks, {c['name']} / {c['company']}")
    return "need prices", body, c["company"], dl, items


def v_footer_noise(c, items, d, dl, today, rnd):
    (p, q) = items[0]
    body = (f"Dear team,\n\ncould you quote {q} x {p}? We need the offer by {dl.strftime('%d %B %Y')}.\n\n"
            f"Kind regards\n{c['name']}\n{c['company']}\n\n--\nThis message is confidential. Autoteile Konzern Holding AG, "
            f"registered office Stuttgart, Managing Directors: A. Beispiel, B. Muster. Please contact info@konzern-holding.test "
            f"for questions about this disclaimer.")
    return "price request", body, c["company"], dl, [(p, q)]


VARIANTS = {"short": v_short, "german_free": v_german_free, "part_format": v_part_format, "thread": v_thread,
            "vague_date": v_vague_date, "bullet_list": v_bullet_list, "footer_noise": v_footer_noise}


def generate_hard(n_per_variant=5, out="testset_hard", seed=11, today=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rnd, today, truth, i = random.Random(seed), today or date.today(), {}, 0
    for name, fn in VARIANTS.items():
        for _ in range(n_per_variant):
            comp, country, contact, dom = rnd.choice(CUSTOMERS)
            c = {"company": comp, "name": contact, "email": f"{contact.split()[0].lower()}@{dom}"}
            items = pick(rnd, rnd.randint(1, 3))
            d, dl = today + timedelta(days=rnd.randint(20, 60)), today + timedelta(days=rnd.randint(3, 25))
            subject, body, req, deadline, lines = fn(c, items, d, dl, today, rnd)
            fname = f"{i:02d}_{name}.eml"
            save_eml(out / fname, subject, f"{contact} <{c['email']}>", body)
            truth[fname] = {"format": name, "rfq_id": None, "requester_company": req, "contact_email": c["email"],
                            "deadline": deadline.isoformat() if deadline else None,
                            "lines": [{"part_number": p, "quantity": q} for p, q in lines]}
            i += 1
    (out / "ground_truth.json").write_text(json.dumps(truth, indent=1))
    return truth


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5, help="emails per variant")
    ap.add_argument("--out", default="testset_hard")
    a = ap.parse_args()
    t = generate_hard(a.n, a.out)
    print(f"{len(t)} hard RFQs ({len(VARIANTS)} variants x {a.n}) written to {a.out}/")