"""Rebuild the Excel master workbook from the database (formulas for all calculated columns)."""
import os
from datetime import date, datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

FONT = "Arial"
HEADER = ["RFQ ID", "Received", "Requester", "Contact", "Email", "Country", "RFQ Date", "Deadline", "Incoterms",
          "Currency", "Payment Terms", "Delivery Location", "Status", "Recommendation", "Flags", "Source Files",
          "Line Items", "Offer Value (EUR)", "Cost (EUR)", "Margin %"]
LINES = ["RFQ ID", "Line", "Part (as received)", "Matched Part", "Description", "Qty", "Unit", "Target Price",
         "Requested Delivery", "Best Supplier", "Unit Cost", "Offer Price", "Offer Value", "Cost Value",
         "Margin %", "Reason", "Flags"]
EVENTS = ["Time", "RFQ ID", "Level", "Message"]
W = {"RFQ_Header": [18, 12, 28, 20, 28, 12, 12, 12, 10, 9, 18, 24, 14, 30, 40, 34, 10, 16, 14, 10],
     "RFQ_Lines": [18, 6, 16, 16, 24, 9, 6, 11, 14, 24, 10, 10, 14, 14, 9, 60, 40],
     "Events": [20, 18, 9, 80]}


def _d(v):
    try:
        return date.fromisoformat(v) if v else None
    except (TypeError, ValueError):
        return None


def _hdr(ws, cols, widths):
    for i, name in enumerate(cols, 1):
        c = ws.cell(row=1, column=i, value=name)
        c.font = Font(name=FONT, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3864")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = widths[i - 1]
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}1"


def _row(ws, r, values, dates=(), fmts=None):
    for i, v in enumerate(values, 1):
        c = ws.cell(row=r, column=i, value=v)
        c.font = Font(name=FONT, size=10)
        if i in dates:
            c.number_format = "yyyy-mm-dd"
        if fmts and i in fmts:
            c.number_format = fmts[i]


def export_workbook(conn, path):
    path = Path(path)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    wh, wl, we = (wb.create_sheet(n) for n in ("RFQ_Header", "RFQ_Lines", "Events"))
    _hdr(wh, HEADER, W["RFQ_Header"]); _hdr(wl, LINES, W["RFQ_Lines"]); _hdr(we, EVENTS, W["Events"])
    for r, q in enumerate(conn.execute("SELECT * FROM rfqs ORDER BY received_at, rfq_id"), 2):
        _row(wh, r, [q["rfq_id"], _d((q["received_at"] or "")[:10]), q["requester"], q["contact"], q["email"],
                     q["country"], _d(q["rfq_date"]), _d(q["deadline"]), q["incoterms"], q["currency"],
                     q["payment_terms"], q["delivery_location"], q["status"], q["recommendation"], q["flags"],
                     q["sources"], f"=COUNTIF(RFQ_Lines!A:A,A{r})",
                     f"=SUMIFS(RFQ_Lines!M:M,RFQ_Lines!A:A,A{r})", f"=SUMIFS(RFQ_Lines!N:N,RFQ_Lines!A:A,A{r})",
                     f'=IF(R{r}>0,(R{r}-S{r})/R{r},"")'],
             dates=(2, 7, 8), fmts={18: "#,##0.00", 19: "#,##0.00", 20: "0.0%"})
        if q["status"] == "Needs review":
            wh.cell(row=r, column=13).fill = PatternFill("solid", fgColor="FFF2CC")
    for r, q in enumerate(conn.execute("SELECT * FROM lines ORDER BY rfq_id, line_no"), 2):
        _row(wl, r, [q["rfq_id"], q["line_no"], q["part_input"], q["part_number"], q["description"], q["qty"],
                     q["unit"], q["target_price"], _d(q["delivery_date"]), q["best_supplier"], q["unit_cost"],
                     q["offer_price"], f'=IF(AND(ISNUMBER(F{r}),ISNUMBER(L{r})),F{r}*L{r},"")',
                     f'=IF(AND(ISNUMBER(F{r}),ISNUMBER(K{r})),F{r}*K{r},"")',
                     f'=IF(ISNUMBER(M{r}),(M{r}-N{r})/M{r},"")', q["reason"], q["flags"]],
             dates=(9,), fmts={6: "#,##0", 8: "#,##0.00", 11: "#,##0.00", 12: "#,##0.00", 13: "#,##0.00",
                               14: "#,##0.00", 15: "0.0%"})
    for r, q in enumerate(conn.execute("SELECT * FROM events ORDER BY id"), 2):
        _row(we, r, [q["ts"], q["rfq_id"], q["level"], q["message"]])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.xlsx")
    wb.save(tmp)
    os.replace(tmp, path)       # raises PermissionError if the file is open in Excel on Windows
