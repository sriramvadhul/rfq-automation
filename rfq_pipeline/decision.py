"""Decision engine: pure, explainable rules (no LLM). For each requested line it
  1. lists supplier options, 2. drops those that cannot meet the requested delivery date,
  3. scores the rest (cost / lead time / reliability), 4. prices the offer from the margin rules,
  5. explains the choice in one sentence."""
from datetime import date

import pandas as pd

from . import config


def load_reference(data_dir=None):
    d = data_dir or config.DATA_DIR
    suppliers = pd.read_csv(f"{d}/supplier_prices.csv")
    margins = pd.read_csv(f"{d}/margin_rules.csv").set_index("category")["target_margin"].to_dict()
    return suppliers, margins


def _price(cost, target_price, target_margin):
    std = cost / (1 - target_margin)
    floor = cost / (1 - config.MIN_MARGIN)
    if target_price is None:
        return std, "standard margin"
    if target_price >= std:
        return target_price, "customer target meets standard margin"
    if target_price >= floor:
        return target_price, "customer target is below standard margin but above the minimum"
    return floor, "customer target is below the minimum margin - offered at the minimum"


def decide_line(ln, suppliers, margins, today, weights):
    m = ln.get("matched")
    if not m:
        return []
    opts = suppliers[suppliers["part_number"] == m["part_number"]].to_dict("records")
    if not opts:
        ln["flags"].append("no supplier data for this part")
        return []
    days_avail = None
    if ln.get("delivery_date"):
        days_avail = (ln["delivery_date"] - today).days - config.TRANSIT_BUFFER_DAYS
    for o in opts:
        o["feasible"] = days_avail is None or o["lead_time_days"] <= days_avail
    pool = [o for o in opts if o["feasible"]]
    late = not pool
    if late:  # nobody can make the date -> show the fastest as a fallback and flag it
        pool = [min(opts, key=lambda o: o["lead_time_days"])]
        ln["flags"].append("requested delivery date cannot be met by any supplier")
    min_cost = min(o["unit_cost"] for o in pool)
    min_lead = max(1, min(o["lead_time_days"] for o in pool))
    for o in opts:
        o["score"] = 0.0
    for o in pool:
        o["score"] = round(weights["cost"] * min_cost / o["unit_cost"]
                           + weights["lead_time"] * min_lead / max(1, o["lead_time_days"])
                           + weights["reliability"] * o["reliability"], 4)
    best = max(pool, key=lambda o: o["score"])
    tm = margins.get(m["category"], config.DEFAULT_TARGET_MARGIN)
    offer, price_note = _price(best["unit_cost"], ln.get("target_price"), tm)
    offer = round(offer, 2)
    ln.update(best_supplier=best["supplier"], unit_cost=best["unit_cost"], offer_price=offer,
              lead_time_days=best["lead_time_days"], margin_pct=round((offer - best["unit_cost"]) / offer, 4))
    if ln["margin_pct"] < tm - 1e-9:
        ln["flags"].append(f"margin {ln['margin_pct']:.0%} below standard {tm:.0%}")
    if ln["quantity"] and ln["quantity"] < best["moq"]:
        ln["flags"].append(f"quantity below supplier MOQ ({best['moq']})")
    why = []
    if best["unit_cost"] == min_cost:
        why.append("lowest cost")
    if best["lead_time_days"] == min(o["lead_time_days"] for o in pool):
        why.append("shortest lead time")
    ln["reason"] = (f"{best['supplier']}: cost {best['unit_cost']:.2f}, {best['lead_time_days']} days lead time, "
                    f"reliability {best['reliability']:.0%}; best of {len(pool)} usable option(s)"
                    f"{' (' + ', '.join(why) + ')' if why else ''}; {price_note}.")
    for o in opts:
        o["chosen"] = o is best
        o["line_no"] = ln["line_no"]
    return opts


def decide_rfq(lines, suppliers, margins, today=None, weights=None):
    today = today or date.today()
    weights = weights or config.DECISION_WEIGHTS
    options = []
    for ln in lines:
        options += decide_line(ln, suppliers, margins, today, weights)
    priced = [ln for ln in lines if ln.get("offer_price") is not None]
    offer = sum(ln["quantity"] * ln["offer_price"] for ln in priced)
    cost = sum(ln["quantity"] * ln["unit_cost"] for ln in priced)
    margin = (offer - cost) / offer if offer else None
    if not lines:
        rec = "Check data - no line items found"
    elif len(priced) < len(lines):
        rec = "Check data - some parts could not be priced"
    elif any("cannot be met" in f for ln in lines for f in ln["flags"]):
        rec = "Quote with later delivery or decline"
    elif margin is not None and margin < config.MIN_MARGIN + 1e-9:
        rec = "Decline or renegotiate (margin at minimum)"
    elif any("below standard" in f for ln in lines for f in ln["flags"]):
        rec = "Quote - margin below standard"
    else:
        rec = "Quote"
    return {"options": options, "offer_value": round(offer, 2), "cost_value": round(cost, 2),
            "margin_pct": round(margin, 4) if margin is not None else None, "recommendation": rec}
