"""Mkungi AI v0: identify the document type from its text.

Keyword scoring is the baseline; a trained classifier replaces it in phase 4
without changing the call site.
"""

from __future__ import annotations

import re

DOC_TYPES: dict[str, list[str]] = {
    "invoice": ["invoice", "tax invoice", "invoice no", "amount due", "bill to"],
    "quotation": ["quotation", "quote no", "valid until", "proforma"],
    "receipt": ["receipt", "received with thanks", "amount paid", "cash sale"],
    "delivery_note": ["delivery note", "delivered by", "received by", "dn no"],
    "goods_received_note": ["goods received", "grn", "received in good condition"],
    "purchase_order": ["purchase order", "po no", "order date", "ship to"],
    "payroll": ["payroll", "payslip", "gross pay", "net pay", "paye"],
    "asset_register": ["asset register", "asset tag", "serial no", "depreciation"],
    "bank_reconciliation": ["bank reconciliation", "unpresented", "outstanding deposits", "balance per bank"],
    "financial_statement": ["balance sheet", "income statement", "statement of financial position", "cash flow"],
    "inventory_sheet": ["inventory", "stock count", "qty on hand", "reorder level"],
    "timesheet": ["timesheet", "hours worked", "overtime", "time in"],
    "petty_cash_voucher": ["petty cash", "voucher no", "paid to"],
}

# Types whose content is mostly a grid convert best to Excel.
SPREADSHEET_TYPES = {
    "payroll",
    "asset_register",
    "bank_reconciliation",
    "inventory_sheet",
    "timesheet",
}


def classify(text: str) -> str:
    lowered = re.sub(r"\s+", " ", text.lower())
    scores = {t: sum(lowered.count(k) for k in kws) for t, kws in DOC_TYPES.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


def recommended_format(doc_type: str) -> str:
    return "xlsx" if doc_type in SPREADSHEET_TYPES else "docx"
