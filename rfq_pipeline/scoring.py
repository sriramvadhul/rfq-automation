"""Priority ranking for the dashboard (which RFQ to look at first). 0-100 score from four factors."""
from datetime import date

import pandas as pd

DEFAULT_WEIGHTS = {"urgency": 0.40, "value": 0.30, "margin": 0.20, "completeness": 0.10}


def load_rfqs(conn):
    df = pd.read_sql("SELECT * FROM rfqs", conn)
    for c in ("deadline", "rfq_date", "received_at"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


def recommend_action(row):
    if row["status"] == "Needs review":
        return "Fix data first"
    d = row["days_left"]
    if pd.isna(d):
        return "Check deadline"
    if d < 0:
        return "Overdue"
    if d <= 3:
        return "Respond now"
    if row["score"] >= 70:
        return "Prioritise"
    if row["score"] >= 45:
        return "Quote this week"
    return "Standard queue"


def rank(df, weights=None, today=None):
    if df.empty:
        return df
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    tot = sum(w.values()) or 1
    today = pd.Timestamp(today or date.today())
    d = df.copy()
    d["days_left"] = (d["deadline"] - today).dt.days
    # urgency: due today/overdue = 1.0 ... 14+ days away = 0.0 (unknown deadline = 0.3)
    d["urgency"] = d["days_left"].apply(lambda x: 0.3 if pd.isna(x) else min(1.0, max(0.0, 1 - x / 14)))
    d["value_rank"] = d["offer_value"].fillna(0).rank(pct=True)
    d["margin_rank"] = d["margin_pct"].fillna(0).rank(pct=True)
    d["completeness"] = d["status"].apply(lambda s: 0.4 if s == "Needs review" else 1.0)
    d["score"] = (100 * (w["urgency"] * d["urgency"] + w["value"] * d["value_rank"]
                         + w["margin"] * d["margin_rank"] + w["completeness"] * d["completeness"]) / tot).round(0)
    d["action"] = d.apply(recommend_action, axis=1)
    return d.sort_values(["score", "offer_value"], ascending=False).reset_index(drop=True)
