"""Score extraction against ground truth, per format/variant.
    python evaluate.py                                  # easy set, rules only
    python evaluate.py --llm                            # rules + local LLM fallback (Ollama must be running)
    python evaluate.py --dir testset_hard --llm --details   # hard set, and list every wrong answer
Where the ground truth is null (value not in the email), inventing a value counts as an error."""
import argparse
import json
import re
import time
from collections import defaultdict
from pathlib import Path

FIELDS = ["rfq_id", "requester_company", "contact_email", "deadline", "lines"]
norm_part = lambda s: re.sub(r"[^A-Z0-9]", "", str(s).upper())


def score_one(m, gt):
    h = m["header"]
    got = {(norm_part(l["part_number"]), l["quantity"]) for l in m["lines"]}
    want = {(norm_part(l["part_number"]), l["quantity"]) for l in gt["lines"]}
    def field(key, expected, eq=lambda a, b: a == b):
        value = h.get(key)
        if expected is None:
            return value is None, value
        return value is not None and eq(value, expected), value
    ok, seen = {}, {}
    ok["rfq_id"], seen["rfq_id"] = field("rfq_id", gt["rfq_id"])
    ok["requester_company"], seen["requester_company"] = field(
        "requester_company", gt["requester_company"], lambda a, b: str(a).lower() == b.lower())
    ok["contact_email"], seen["contact_email"] = field("contact_email", gt["contact_email"])
    ok["deadline"], seen["deadline"] = field("deadline", gt["deadline"], lambda a, b: str(a) == b)
    ok["lines"], seen["lines"] = got == want, sorted(got)
    return ok, seen, sorted(want)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="testset")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--details", action="store_true", help="print every wrong field")
    a = ap.parse_args()
    from rfq_pipeline.pipeline import extract_any
    from rfq_pipeline.validation import validate_header
    truth = json.loads((Path(a.dir) / "ground_truth.json").read_text())
    score, count, secs, wrong = defaultdict(lambda: defaultdict(int)), defaultdict(int), defaultdict(float), []
    for fname, gt in truth.items():
        t0 = time.time()
        m = extract_any(Path(a.dir) / fname)
        if a.llm and validate_header(m):
            from rfq_pipeline.llm_fallback import fill_missing
            m = fill_missing(m)
        secs[gt["format"]] += time.time() - t0
        ok, seen, want_lines = score_one(m, gt)
        count[gt["format"]] += 1
        for f, v in ok.items():
            score[gt["format"]][f] += int(v)
            if not v:
                want = want_lines if f == "lines" else gt[f]
                wrong.append((fname, f, seen[f], want))
    w = max(len(f) for f in count) + 1
    print(f"{'format':{w}s} {'n':>3s} " + " ".join(f"{f[:11]:>11s}" for f in FIELDS) + "   sec/rfq")
    tot = defaultdict(int)
    for fmt in count:
        print(f"{fmt:{w}s} {count[fmt]:>3d} " + " ".join(f"{100 * score[fmt][f] / count[fmt]:>10.0f}%" for f in FIELDS)
              + f"   {secs[fmt] / count[fmt]:.2f}")
        for f in FIELDS:
            tot[f] += score[fmt][f]
    n = sum(count.values())
    print(f"{'ALL':{w}s} {n:>3d} " + " ".join(f"{100 * tot[f] / n:>10.0f}%" for f in FIELDS))
    if a.details and wrong:
        print(f"\n{len(wrong)} wrong field(s):")
        for fname, f, got, want in wrong:
            print(f"  {fname:28s} {f:18s} got={got!s:.60}  want={want!s:.60}")