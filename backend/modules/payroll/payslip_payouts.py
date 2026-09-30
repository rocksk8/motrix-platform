# -*- coding: utf-8 -*-
"""勞報單對外：出納頁（IP-103 `payslip.payables`）與營運報表成本（IP-9 `expense.entries`，名稱 `payslip`）。

- `payslip.payables`（M07 → M05 出納）：對方已簽回、等出納付款的勞報單。**只回付款需要的欄位**（單號、承攬人姓名、
  所得類別、金額、簽回時間與檔案名稱）；不回身分證字號、地址、電話、銀行帳號（F2）。
  「標記已付款」不經連接器：出納頁直接打勞報單那一支 `POST /api/payslips/{單號}/mark-paid`（同一個動作只有一份實作）。
- `expense.entries`（M07 → M08 報表）：狀態＝已付款者，以**付款日期**歸月、金額取**應付總額**（gross）；已作廢、
  未付款（含已簽回）不列。權責與現金兩種口徑相同（使用者 2026-09-29 裁示）。不掛案件（quoteNo 空）⇒ 篩部門時無法歸屬而排除。

本檔在 M07 載入時登記提供者；M07 不在 ⇒ 沒有提供者，使用方照 INTEGRATION-POINTS 退化。
"""
import json

#: 報表顯示用的支出類別
EXPENSE_CATEGORY = "勞報單"


class _Payables:
    """出納頁用。在呼叫端的連線上讀，不寫。"""

    @staticmethod
    def pending(conn):
        """待付款：[{slipNo, contractor, incomeType, gross, tax, nhi, net, slipDate, signedAt, signedBy, files:[{id, filename}]}]，舊的在前。"""
        out = []
        for r in conn.execute(
                "SELECT slip_no, contractor_name, income_type, gross_amount, tax_withheld, nhi_supplement,"
                " net_amount, slip_date, signed_at, signed_by, signed_files_json FROM payslips"
                " WHERE status = '已簽回' ORDER BY signed_at, id"):
            try:
                files = json.loads(r["signed_files_json"] or "[]")
            except (TypeError, ValueError):
                files = []
            out.append({"slipNo": r["slip_no"], "contractor": r["contractor_name"] or "",
                        "incomeType": r["income_type"], "gross": int(r["gross_amount"] or 0),
                        "tax": int(r["tax_withheld"] or 0), "nhi": int(r["nhi_supplement"] or 0),
                        "net": int(r["net_amount"] or 0), "slipDate": r["slip_date"] or "",
                        "signedAt": (r["signed_at"] or "")[:10], "signedBy": r["signed_by"] or "",
                        "files": [{"id": f.get("id"), "filename": f.get("filename", "")} for f in files]})
        return out


def _expense_entries(conn, start, end):
    """付款日期在 [start, end]（YYYY-MM-DD）、狀態＝已付款的勞報單：[{date, quoteNo, desc, amount, category}]。"""
    rows = conn.execute(
        "SELECT slip_no, contractor_name, gross_amount, net_amount, payment_date, data_json FROM payslips"
        " WHERE status = '已付款' AND payment_date BETWEEN ? AND ? ORDER BY payment_date", (start, end)).fetchall()
    out = []
    for r in rows:
        gross = int(r["gross_amount"] or 0)
        desc = ("勞報單 %s %s" % (r["slip_no"], r["contractor_name"] or "")).strip()
        amount = gross
        # MONEY-FLOWS §9 L5（下游效應：營運報表現金口徑）：經承攬商匯款單付款者（R12 `paid_via_remit`），匯款單的實付
        # （net＝勞報單實付）已由現金口徑的承攬商支出（`case.recognition.dispatch_entries`，讀 `remit_actual`）計入；
        # 這裡只列匯款單沒付的代扣部分（gross − net：所得稅＋補充保費），合計剛好一次 gross，不雙計。
        try:
            via = (json.loads(r["data_json"] or "{}") or {}).get("paid_via_remit")
        except (TypeError, ValueError):
            via = None
        if via:
            amount = max(0, gross - int(r["net_amount"] or 0))
            desc += "（代扣部分；實付已列於匯款單 %s）" % via
            if amount == 0:
                continue
        out.append({"date": r["payment_date"], "quoteNo": "", "desc": desc, "amount": amount, "category": EXPENSE_CATEGORY})
    return out


# IP-103 與 IP-9（名稱 payslip）由 modules/payroll/__init__.py 的 ModuleSpec.providers 登記
