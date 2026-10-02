# -*- coding: utf-8 -*-
"""叫料匯款申請的出納整合（31-C 匯款切片）：IP-100 `payables.pending`（名稱 `case_material`）、IP-102 `remit.reviews`（名稱 `case_material`）、
IP-9 `expense.entries`（名稱 `remit_fee_case_material`）。出納（M05）不用改：沿用既有名稱空間，「請款待付款」自動出現這些申請。

契約為加法（設計 §3.4）：`key`＝申請 id（每張申請一列）；`pending()` 回該申請的**剩餘應付**（`amount`＝申請金額 − 累計實付）；
`mark_paid` 每次記一筆付款明細並回累計與剩餘（分次付款：未結清的申請留在待付款）。
差額（實付超過剩餘＝多付）的審核以**付款明細**為單位：`remit.reviews` 的 key＝明細 id。
欄位可見：出納為了付款看得到客戶、專案、品名、金額、供應商；帳戶只給遮罩（末 4 碼），完整帳戶只經 `payee_info`（出納專用端點、每次看都留稽核）。
"""
from modules.case import material_payment as MP
from modules.case.recognition import _approved_at

_FIELD_NOTE = "材料申請匯款"


def _mask(bank, account) -> str:
    acct = str(account or "").strip()
    if not acct and not (bank or "").strip():
        return ""
    return ("%s ****%s" % ((bank or "").strip(), acct[-4:])).strip()


def _title(snap, code) -> str:
    return "材料申請｜%s（%s）" % (snap.get("itemName") or "", code)


class _Payables:
    """IP-100 提供者（名稱 `case_material`）。"""

    #: 出納端點 `payee-bank`：完整帳號只給最高管理者與出納（`cashier` 模組）；一般管理員只看遮罩（32 班；其他請款來源未啟用此規則）
    FULL_ACCOUNT_STRICT = True

    @staticmethod
    def payee_info(conn, key) -> dict:
        """出納付款前看收款人資料（完整，只給出納端點）。查無或不是已核准 ⇒ LookupError。"""
        pay = MP.get(conn, key)
        if not pay or pay["status"] != MP.S_APPROVED:
            raise LookupError("找不到這張匯款申請")
        sn = MP.snapshot_of(pay)
        return {"payeeType": "vendor", "payeeName": sn.get("bankAccountName") or sn.get("supplierName") or "", "payeeUsername": "",
                "bank": ("%s %s" % (sn.get("bankCode") or "", sn.get("bankName") or "")).strip(), "account": sn.get("bankAccountNumber") or ""}

    @staticmethod
    def pending(conn) -> list:
        out = []
        for r in conn.execute("SELECT p.*, q.customer_name, q.project_name FROM case_material_payments p"
                              " LEFT JOIN quotations q ON q.quote_no = p.quote_no WHERE p.status=? ORDER BY p.id", (MP.S_APPROVED,)).fetchall():
            pay = dict(r)
            remaining = MP.remaining_of(conn, pay)
            if remaining <= 0:
                continue
            sn = MP.snapshot_of(pay)
            out.append({
                "key": str(pay["id"]), "sourceLabel": MP.SOURCE_LABEL, "quoteNo": pay["quote_no"] or "",
                "customerName": r["customer_name"] or "", "projectName": r["project_name"] or "",
                "title": _title(sn, pay["doc_code"]), "amount": remaining, "payee": sn.get("supplierName") or "",
                "requestedBy": pay["created_by"] or "", "kind": "material_payment", "docCode": pay["doc_code"], "payeeType": "vendor",
                "payeeUsername": "", "payeeBank": _mask(("%s %s" % (sn.get("bankCode") or "", sn.get("bankName") or "")).strip(), sn.get("bankAccountNumber")),
                "payTerms": "", "remitDate": "", "expenseDate": "", "approvedAt": (pay["approved_at"] or "")[:10] or _approved_at(pay["approval_json"]) or "",
                "invoiceDate": "", "invoiceNo": "", "invoiceFiles": 0, "files": 0,
                "applied": float(pay["amount_approved"] or 0), "paid": MP.paid_total(conn, pay["id"]), "seq": pay["seq"]})
        return out

    @staticmethod
    def paid(conn, start, end) -> list:
        """付款日在 [start, end] 的付款明細（出納執行紀錄用）；一筆明細一列。"""
        out = []
        for r in conn.execute("SELECT l.*, p.quote_no, p.doc_code, p.snapshot_json, p.amount_approved FROM case_material_payment_lines l"
                              " JOIN case_material_payments p ON p.id = l.payment_id WHERE substr(l.paid_at,1,10) BETWEEN ? AND ? ORDER BY l.paid_at, l.id",
                              (start, end)).fetchall():
            sn = MP.snapshot_of({"snapshot_json": r["snapshot_json"]})
            out.append({"key": "%s/%s" % (r["payment_id"], r["id"]), "sourceLabel": MP.SOURCE_LABEL, "quoteNo": r["quote_no"] or "",
                        "title": _title(sn, r["doc_code"]), "payable": float(r["amount_approved"] or 0), "actual": float(r["amount"] or 0),
                        "fee": float(r["fee"] or 0), "paidAt": (r["paid_at"] or "")[:10], "review": r["remit_review"] or ""})
        return out

    @staticmethod
    def mark_paid(conn, key, paid_date, user, remit=None) -> dict:
        """登錄一筆付款明細（分次付款）。查無 ⇒ LookupError；不是已核准／已結清 ⇒ ValueError（呼叫端轉 404／409）。不 commit（呼叫端）。
        原子：先拿寫鎖（`begin_write`；已在交易內則沿用）再讀剩餘額——兩位出納同時按，後到的看到的是更新後的剩餘。"""
        from core.txn import begin_write
        begin_write(conn)
        return dict(MP.add_line(conn, key, paid_date, user, remit), paidDate=paid_date)


class _RemitReviews:
    """IP-102 提供者（名稱 `case_material`）：多付（實付 > 剩餘）的付款明細待審核；核可＝保留，退回＝刪除該筆明細（回待付款）。"""

    @staticmethod
    def pending(conn):
        out = []
        for r in conn.execute("SELECT l.*, p.quote_no, p.doc_code, p.snapshot_json, p.amount_approved, q.customer_name FROM case_material_payment_lines l"
                              " JOIN case_material_payments p ON p.id = l.payment_id LEFT JOIN quotations q ON q.quote_no = p.quote_no"
                              " WHERE l.remit_review=? ORDER BY l.id", (MP.REVIEW_PENDING,)).fetchall():
            sn = MP.snapshot_of({"snapshot_json": r["snapshot_json"]})
            before = MP.paid_total(conn, r["payment_id"]) - float(r["amount"] or 0)             # 這一筆之前的累計
            payable = MP.r2(float(r["amount_approved"] or 0) - before)                       # 這一筆登錄時的剩餘應付
            out.append({"key": str(r["id"]), "sourceLabel": MP.SOURCE_LABEL, "quoteNo": r["quote_no"] or "", "customerName": r["customer_name"] or "",
                        "payee": sn.get("supplierName") or "", "payable": payable, "actual": float(r["amount"] or 0),
                        "diff": max(0.0, MP.r2(float(r["amount"] or 0) - payable)),          # 只有多付才有差額；手續費偏高的覆核是 0 "fee": float(r["fee"] or 0), "paidAt": (r["paid_at"] or "")[:10],
                        "paidBy": r["paid_by"] or "",
                        "reason": "手續費偏高（超過 %g）" % MP.FEE_REVIEW_OVER if float(r["fee"] or 0) > MP.FEE_REVIEW_OVER and float(r["amount"] or 0) <= payable + 0.005 else ""})
        return out

    @staticmethod
    def decide(conn, key, decision, user, note=""):
        from core.txn import begin_write
        begin_write(conn)
        return MP.decide_line(conn, key, decision, user, note)


def _expense_entries(conn, start, end):
    """IP-9：付款日在 [start, end] 的叫料匯款手續費（一筆明細一筆；多付未審核的標 pending）。"""
    out = []
    for r in conn.execute("SELECT l.*, p.quote_no, p.doc_code, p.snapshot_json FROM case_material_payment_lines l"
                          " JOIN case_material_payments p ON p.id = l.payment_id WHERE l.fee > 0 AND substr(l.paid_at,1,10) BETWEEN ? AND ?"
                          " ORDER BY l.paid_at, l.id", (start, end)).fetchall():
        sn = MP.snapshot_of({"snapshot_json": r["snapshot_json"]})
        out.append({"date": (r["paid_at"] or "")[:10], "quoteNo": r["quote_no"] or "",
                    "desc": "%s｜%s（匯款申請 %s）" % (MP.FEE_CATEGORY, sn.get("supplierName") or "材料申請", r["doc_code"]),
                    "amount": float(r["fee"]), "category": MP.FEE_CATEGORY, "pending": r["remit_review"] == MP.REVIEW_PENDING})
    return out
