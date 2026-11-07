"""Score the extraction against ground truth, per format.  Needs: python make_testset.py first.
    python evaluate.py            # rules only
    python evaluate.py --llm      # rules + local LLM fallback (needs Ollama running)"""
import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

FIELDS = ["rfq_id", "requester_company", "contact_email", "deadline", "lines"]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="testset")
    ap.add_argument("--llm", action="store_true")
    a = ap.parse_args()
    from rfq_pipeline.pipeline import extract_any
    from rfq_pipeline.validation import validate_header
    truth = json.loads((Path(a.dir) / "ground_truth.json").read_text())
    score, count, secs = defaultdict(lambda: defaultdict(int)), defaultdict(int), defaultdict(float)
    import time
    for fname, gt in truth.items():
        t0 = time.time()
        m = extract_any(Path(a.dir) / fname)
        if a.llm and validate_header(m):
            from rfq_pipeline.llm_fallback import fill_missing
            m = fill_missing(m)
        secs[gt["format"]] += time.time() - t0
        h = m["header"]
        got_lines = {(l["part_number"].upper(), l["quantity"]) for l in m["lines"]}
        want_lines = {(l["part_number"], l["quantity"]) for l in gt["lines"]}
        ok = {"rfq_id": gt["rfq_id"] is None or h.get("rfq_id") == gt["rfq_id"],
              "requester_company": str(h.get("requester_company", "")).lower() == gt["requester_company"].lower(),
              "contact_email": h.get("contact_email") == gt["contact_email"],
              "deadline": str(h.get("deadline")) == gt["deadline"], "lines": got_lines == want_lines}
        count[gt["format"]] += 1
        for f, v in ok.items():
            score[gt["format"]][f] += int(v)
    print(f"{'format':12s} {'n':>3s} " + " ".join(f"{f[:11]:>11s}" for f in FIELDS) + "   sec/rfq")
    tot = defaultdict(int)
    for fmt in count:
        print(f"{fmt:12s} {count[fmt]:>3d} " + " ".join(f"{100 * score[fmt][f] / count[fmt]:>10.0f}%" for f in FIELDS)
              + f"   {secs[fmt] / count[fmt]:.2f}")
        for f in FIELDS:
            tot[f] += score[fmt][f]
    n = sum(count.values())
    print(f"{'ALL':12s} {n:>3d} " + " ".join(f"{100 * tot[f] / n:>10.0f}%" for f in FIELDS))
