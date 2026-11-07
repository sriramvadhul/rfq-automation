"""RFQ Cockpit - live dashboard.   Run:  streamlit run app.py   (and python main.py --watch in another terminal)"""
import pandas as pd
import streamlit as st

from rfq_pipeline import config, db
from rfq_pipeline.scoring import DEFAULT_WEIGHTS, load_rfqs, rank

st.set_page_config(page_title="RFQ Cockpit", layout="wide")
st.title("RFQ Cockpit")

with st.sidebar:
    st.header("Priority weights")
    w = {"urgency": st.slider("Deadline urgency", 0.0, 1.0, DEFAULT_WEIGHTS["urgency"], 0.05),
         "value": st.slider("Order value", 0.0, 1.0, DEFAULT_WEIGHTS["value"], 0.05),
         "margin": st.slider("Margin", 0.0, 1.0, DEFAULT_WEIGHTS["margin"], 0.05),
         "completeness": st.slider("Data completeness", 0.0, 1.0, DEFAULT_WEIGHTS["completeness"], 0.05)}
    st.header("Live updates")
    live = st.checkbox("Auto-refresh every 5 s", value=True)
    st.header("Time-saving assumptions")
    manual_min = st.number_input("Minutes per RFQ done manually (3 people)", 5, 240, 45)
    review_min = st.number_input("Minutes to review a flagged RFQ", 1, 60, 10)
    ok_min = st.number_input("Minutes to approve a clean RFQ", 1, 30, 2)


def money(x):
    return "-" if pd.isna(x) else f"{x:,.0f}"


def render():
    conn = db.connect()
    raw = load_rfqs(conn)
    if raw.empty:
        st.info("No RFQs yet. Put files in `inbox/` and run `python main.py` (or `--watch`).")
        return
    df = rank(raw, w)
    t_queue, t_metrics, t_log = st.tabs(["Queue", "Impact metrics", "Event log"])

    with t_queue:
        open_df = df[df["human_status"] == "Pending"]
        k = st.columns(5)
        k[0].metric("Pending RFQs", len(open_df))
        k[1].metric("Respond now (<=3 days)", int((open_df["action"] == "Respond now").sum()))
        k[2].metric("Need data review", int((open_df["status"] == "Needs review").sum()))
        k[3].metric("Pending offer value (EUR)", money(open_df["offer_value"].sum()))
        mp = (open_df["offer_value"] * open_df["margin_pct"].fillna(0)).sum() / open_df["offer_value"].sum() \
            if open_df["offer_value"].sum() else 0
        k[4].metric("Weighted margin", f"{mp:.1%}")
        show_all = st.checkbox("Include approved / rejected", value=False)
        view = df if show_all else open_df
        view = view.rename(columns={"rfq_id": "RFQ ID", "requester": "Requester", "country": "Country",
                                    "deadline": "Deadline", "days_left": "Days left", "offer_value": "Offer (EUR)",
                                    "margin_pct": "Margin", "status": "Status", "recommendation": "Engine says",
                                    "human_status": "Review", "score": "Priority", "action": "Action"})
        cols = ["Priority", "Action", "RFQ ID", "Requester", "Country", "Deadline", "Days left", "Offer (EUR)",
                "Margin", "Engine says", "Status", "Review"]
        ev = st.dataframe(view[cols], hide_index=True, width="stretch", on_select="rerun",
                          selection_mode="single-row", key="queue",
                          column_config={"Priority": st.column_config.ProgressColumn("Priority", min_value=0, max_value=100, format="%d"),
                                         "Deadline": st.column_config.DateColumn("Deadline"),
                                         "Offer (EUR)": st.column_config.NumberColumn(format="%.0f"),
                                         "Margin": st.column_config.NumberColumn(format="percent")})
        sel = ev.selection.rows
        if not sel:
            st.caption("Select a row to see the recommended suppliers, the draft reply and to approve or reject.")
        else:
            row = view.iloc[sel[0]]
            rid = row["RFQ ID"]
            st.divider()
            st.subheader(f"{rid} - {row['Requester'] if isinstance(row['Requester'], str) else 'unknown requester'}")
            if row["Status"] == "Needs review":
                st.warning(raw.loc[raw.rfq_id == rid, "flags"].iloc[0] or "Needs review")
            elif raw.loc[raw.rfq_id == rid, "flags"].iloc[0]:
                st.info(raw.loc[raw.rfq_id == rid, "flags"].iloc[0])
            lines = pd.read_sql("SELECT line_no AS Line, part_input AS 'As received', part_number AS Part, qty AS Qty, "
                                "target_price AS 'Target', best_supplier AS 'Best supplier', unit_cost AS Cost, "
                                "offer_price AS Offer, ROUND(margin_pct*100,1) AS 'Margin %', lead_time_days AS 'Lead days', "
                                "reason AS Why FROM lines WHERE rfq_id=? ORDER BY line_no", conn, params=(rid,))
            st.markdown("**Recommended option per line**")
            st.dataframe(lines, hide_index=True, width="stretch")
            with st.expander("All supplier options considered"):
                st.dataframe(pd.read_sql("SELECT line_no AS Line, supplier AS Supplier, unit_cost AS Cost, "
                                         "lead_time_days AS 'Lead days', moq AS MOQ, reliability AS Reliability, "
                                         "feasible AS 'Meets date', ROUND(score,3) AS Score, chosen AS Chosen "
                                         "FROM options WHERE rfq_id=? ORDER BY line_no, score DESC", conn, params=(rid,)),
                             hide_index=True, width="stretch")
            left, right = st.columns([2, 1])
            with left:
                draft = st.text_area("Draft reply (editable)", raw.loc[raw.rfq_id == rid, "draft"].iloc[0] or "",
                                     height=330, key=f"draft-{rid}")
                if st.button("Save edited draft", key=f"save-{rid}"):
                    db.save_draft(conn, rid, draft)
                    st.toast("Draft saved (edit recorded as feedback)")
            with right:
                st.markdown("**Contact & terms**")
                for label, col in (("Contact", "contact"), ("Email", "email"), ("Incoterms", "incoterms"),
                                   ("Payment", "payment_terms"), ("Deliver to", "delivery_location"),
                                   ("Sources", "sources"), ("LLM-filled", "llm_fields")):
                    v = raw.loc[raw.rfq_id == rid, col].iloc[0]
                    st.write(f"**{label}:** {v if isinstance(v, str) and v else '-'}")
                st.markdown("**Your decision**")
                b = st.columns(2)
                if b[0].button("Approve", key=f"ok-{rid}", type="primary"):
                    db.set_human_status(conn, rid, "Approved"); st.rerun(scope="fragment")
                if b[1].button("Reject", key=f"no-{rid}"):
                    db.set_human_status(conn, rid, "Rejected"); st.rerun(scope="fragment")
                st.caption(f"Current: {row['Review']}")

    with t_metrics:
        n = len(raw)
        flagged = int((raw["status"] == "Needs review").sum())
        manual_h = n * manual_min / 60
        auto_h = ((n - flagged) * ok_min + flagged * review_min) / 60
        m = st.columns(4)
        m[0].metric("RFQs processed", n)
        m[1].metric("Fully automatic (no flags)", f"{(n - flagged) / n:.0%}")
        m[2].metric("Avg. processing time", f"{raw['processing_seconds'].mean():.1f} s")
        m[3].metric("Hours saved (assumption-based)", f"{manual_h - auto_h:,.1f} h")
        m = st.columns(4)
        m[0].metric("Total offer value (EUR)", money(raw["offer_value"].sum()))
        m[1].metric("Approved", int((raw["human_status"] == "Approved").sum()))
        m[2].metric("Rejected", int((raw["human_status"] == "Rejected").sum()))
        m[3].metric("Draft edits by humans", int(pd.read_sql("SELECT COUNT(*) c FROM feedback", conn)["c"][0]))
        st.caption("Hours saved = RFQs x manual minutes minus automatic handling + review time. "
                   "Change the assumptions in the sidebar; measure the real manual time before quoting this figure.")
        st.bar_chart(raw["recommendation"].value_counts(), horizontal=True)

    with t_log:
        st.dataframe(pd.read_sql("SELECT ts AS Time, rfq_id AS 'RFQ ID', level AS Level, message AS Message "
                                 "FROM events ORDER BY id DESC LIMIT 200", conn), hide_index=True, width="stretch")
    conn.close()


st.fragment(run_every=5 if live else None)(render)()
