# -*- coding: utf-8 -*-
"""IP-100 `payables.pending`：M01 的待付款申請（INTEGRATION-POINTS；2026-09-27 使用者裁示請款流程）。

[單位] case:payables    [層] L2（M01）    [穩定度] 契約（IP-100 v1）
[公開介面] _Payables.pending(conn), _Payables.mark_paid(conn, key, paid_date, user)
[不變式] 只列「已核准、付款日空白」的案件額外支出；登錄付款＝寫回同一筆的 paid_date ⇒ 從清單消失、月支出現金口徑改用這一天
[契約題] modules/case/tests/test_payreq_2026_09_27.py、modules/arap/tests/test_cashier_pending_payables_2026_09_27.py

**欄位可見**（使用者 2026-09-28 裁示，稽核 A AB-S2）：出納為了付款，看得到客戶、專案、事由、金額、請款人——
不因為出納本身看不到該案件而遮蔽（與 IP-14 承攬商匯款待付款同一做法）。

出納（M05）不直接讀本模組的表：列清單、登錄付款都經這個提供者（出納通常看不到案件本身——案件的擁有者規則不放行出納）。
"""
import json
import math
from datetime import datetime

from modules.case import expense_forms as _EF
from modules.case.recognition import _approved_at

SOURCE_LABEL = "案件支出申請"


def _col(r, name, default=""):
    try:
        return r[name]
    except (IndexError, KeyError):
        return default


def _files(raw):
    try:
        v = json.loads(raw or "[]")
        return v if isinstance(v, list) else []
    except (TypeError, ValueError):
        return []


#: 費用單據（kind≠''）的類型名稱；出納清單／執行紀錄的標題用它，不用舊版專用的 `category`（費用單據的 category 是預設值「其他」）
_KIND_LABEL = {"purchase_req": "請購單", "purchase_order": "採購單", "travel": "差旅費用請款單", "petty_cash": "零用金支付單"}


def _title(r) -> str:
    """出納看的標題：費用單據＝「<類型名稱>｜<第一筆品項摘要>」（description 由明細第一筆摘要自動帶入）；舊版額外支出＝「<類別>｜<說明>」。"""
    kind = _col(r, "kind") or ""
    if kind:
        return "%s｜%s" % (_KIND_LABEL.get(kind, "費用單據"), r["description"] or "")
    return "%s｜%s" % (r["category"] or "其他", r["description"] or "")


def _payee_name(r) -> str:
    """出納看的收款人：另存的收款人（`payee_name`，出納／銀行資料）優先；費用單據依類型取表單上填的——採購單＝廠商（data.vendor）、零用金＝支付對象（data.payee）；
    其餘（差旅等）與舊版額外支出照舊（付款人／填寫人）。**只改顯示名稱**，不碰收款人類型與銀行資料（類型表單沒有收集廠商銀行帳號——產品待決）。"""
    name = _col(r, "payee_name") or ""
    if name:
        return name
    kind = _col(r, "kind") or ""
    key = {"purchase_order": "vendor", "petty_cash": "payee"}.get(kind)
    if key:
        try:
            v = (json.loads(_col(r, "data_json") or "{}") or {}).get(key)
        except (TypeError, ValueError):
            v = None
        if isinstance(v, str) and v.strip():
            return v.strip()
    return r["payer_name"] or r["created_by_name"] or ""


#: 收款對象填在表單上、單據本身沒有收款帳戶資料的費用單據類型（採購單＝廠商、零用金＝支付對象）
_FORM_PAYEE_KEYS = {"purchase_order": "vendor", "petty_cash": "payee"}
PAYEE_NOTE = "廠商收款帳戶資料未收集：請向申請人確認收款帳戶後再付款（系統不會把申請人的員工帳戶當成這筆的收款帳戶）"


def _form_payee(r) -> bool:
    """這筆的收款人是「表單上填的對象」（採購單廠商、零用金支付對象），而且沒有另存的收款人／銀行資料。"""
    return bool(_FORM_PAYEE_KEYS.get(_col(r, "kind") or "")) and not (_col(r, "payee_name") or "").strip() and not (
        (_col(r, "payee_bank") or "").strip() or (_col(r, "payee_account") or "").strip())


def _item(r):
    files = _files(r["files_json"])
    return {
        "key": str(r["id"]), "sourceLabel": SOURCE_LABEL,
        "quoteNo": r["quote_no"] or "", "customerName": _col(r, "customer_name") or "", "projectName": _col(r, "project_name") or "",
        "title": _title(r),
        "amount": float(r["total_cost"] or 0),
        "payee": _payee_name(r), "requestedBy": r["created_by_name"] or "",
        # 費用單據（A2）：類型、單號、收款人類型、付款條件／匯款日（採購單由出納核准後填）；舊列＝kind ''
        "kind": _col(r, "kind") or "", "docCode": _col(r, "doc_code") or "", "payeeType": _col(r, "payee_type") or "",
        "payeeUsername": "" if _form_payee(r) else _payee_username(r),               # 表單收款對象（廠商）不是員工：不去查申請人的員工帳戶
        "payeeNote": PAYEE_NOTE if _form_payee(r) else "", "payeeBank": _mask_bank(_col(r, "payee_bank"), _col(r, "payee_account")),
        "payTerms": _col(r, "pay_terms") or "", "remitDate": _col(r, "remit_date") or "",
        "plannedPayDate": _col(r, "planned_pay_date") or "",           # 預定付款日（2026-10-05；''＝沒填；提醒信／行事曆依它）
        "expenseDate": (r["expense_date"] or "")[:10], "approvedAt": _approved_at(r["approval_json"]) or "",
        "invoiceDate": (_col(r, "invoice_date") or "")[:10], "invoiceNo": _col(r, "invoice_no") or "",
        "invoiceFiles": sum(1 for f in files if isinstance(f, dict) and f.get("kind") == "invoice"),
        "files": len(files),
        # 出納看得到每個附件的名稱／大小／類別（唯讀；2026-10-06 t44-attach-views）；**不含 path**——開檔走 file_open（綁單據、出納端點串流）
        "fileList": _file_list(r),
    }


_IDX = "idx-"


def _file_list(r) -> list:
    """出納看的附件清單：不含 path。沒有 id 的舊筆合成 `idx-<在原陣列的位置>`（`file_entries` 的 id 會退回 path ⇒ 不能直接用）。"""
    from helpers.approval_queue import file_entries
    out = []
    for i, f in enumerate(_files(r["files_json"])):
        if not isinstance(f, dict):
            continue
        got = file_entries(json.dumps([f]), "other")
        if not got:
            continue
        e = {k: v for k, v in got[0].items() if k != "path"}
        e["id"] = str(f.get("id")) if f.get("id") else _IDX + str(i)
        out.append(e)
    return out


def _pick(files, file_id):
    """`file_id` 對應的那一筆：先比 id；沒有 id 的舊筆用合成的 `idx-<位置>`。"""
    from helpers.uploads import pick_file
    hit = pick_file(files, file_id)
    if hit is not None:
        return hit
    fid = str(file_id)
    if fid.startswith(_IDX) and fid[len(_IDX):].isdigit():
        i = int(fid[len(_IDX):])
        if 0 <= i < len(files) and isinstance(files[i], dict) and not files[i].get("id"):
            return files[i]
    return None


def _payee_username(r) -> str:
    """員工收款人的帳號（查銀行資料表用）：單據 data.applicant → 支出人帳號 → 建立者；廠商／無 ⇒ ''。"""
    if (_col(r, "payee_type") or "") == "vendor":
        return ""
    try:
        d = json.loads(_col(r, "data_json") or "{}")
    except Exception:
        d = {}
    return str(d.get("applicant") or r["payer_username"] or r["created_by"] or "")


def _mask_bank(bank, account) -> str:
    """清單上的銀行資料只給遮罩（末 4 碼）；完整帳號只經出納專用端點、每次看都留稽核。"""
    acct = str(account or "").strip()
    if not acct and not (bank or "").strip():
        return ""
    return ("%s ****%s" % ((bank or "").strip(), acct[-4:])).strip()


class _Payables:
    """IP-100 提供者（多提供者，名稱 `case`）。"""

    @staticmethod
    def payee_info(conn, key) -> dict:
        """出納付款前看「收款人資料」：單據上手填的收款人／銀行／帳號（完整，只給出納端點）與員工帳號。查無 ⇒ LookupError。"""
        try:
            exp_id = int(key)
        except (TypeError, ValueError):
            raise LookupError("找不到這筆申請")
        r = conn.execute("SELECT * FROM case_extra_expenses WHERE id=?", (exp_id,)).fetchone()
        if not r or not _EF.is_payable_kind(r["kind"] or "") or r["status"] != "已核准":
            raise LookupError("找不到這筆申請")
        if _form_payee(r):                     # 採購單廠商／零用金支付對象：名稱與清單一致；不退回申請人的員工收款帳戶（否則廠商的錢會被導向申請人的帳戶）
            return {"payeeType": "vendor", "payeeName": _payee_name(r), "payeeUsername": "", "bank": "", "account": "", "note": PAYEE_NOTE}
        return {"payeeType": _col(r, "payee_type") or "", "payeeName": _payee_name(r),
                "payeeUsername": _payee_username(r), "bank": _col(r, "payee_bank") or "", "account": _col(r, "payee_account") or ""}

    @staticmethod
    def file_open(conn, key, file_id):
        """出納開待付款申請的附件（唯讀）：只認「還在出納待付款清單上」的那一筆（已核准、未登錄付款、可付款類型），檔案 id 必須在那一筆
        自己的 files_json、路徑必須屬於這張單據的資料夾（與附件目錄 `open()` 同一道綁定）。回 `OpenedFile`；任一不符 ⇒ LookupError。"""
        from helpers.uploads import opened_upload_file
        from modules.case.attachments import _path_bound_to_doc
        try:
            exp_id = int(key)
        except (TypeError, ValueError):
            raise LookupError("找不到這筆申請")
        r = conn.execute("SELECT * FROM case_extra_expenses WHERE id=? AND status = '已核准' AND COALESCE(paid_date, '') = '' AND "
                         + _EF.payable_sql(), (exp_id,)).fetchone()
        if r is None:
            raise LookupError("找不到這筆申請")
        entry = _pick(_files(r["files_json"]), file_id)
        if entry is None or not _path_bound_to_doc(conn, "extra_expense", exp_id, entry):
            raise LookupError("找不到這個檔案")
        opened = opened_upload_file(entry)
        if opened is None:
            raise LookupError("找不到這個檔案")
        return opened

    @staticmethod
    def pending(conn) -> list:
        rows = conn.execute(
            "SELECT e.*, q.customer_name, q.project_name FROM case_extra_expenses e"
            " LEFT JOIN quotations q ON q.quote_no = e.quote_no"
            " WHERE e.status = '已核准' AND COALESCE(e.paid_date, '') = '' AND " + _EF.payable_sql("e") + " ORDER BY e.id").fetchall()
        return [_item(r) for r in rows]

    @staticmethod
    def paid(conn, start, end) -> list:
        """付款日在 [start, end] 的申請（出納執行紀錄用）：`[{key, sourceLabel, quoteNo, title, payable, actual, fee, paidAt, review}]`。"""
        return [{"key": str(r["id"]), "sourceLabel": SOURCE_LABEL, "quoteNo": r["quote_no"] or "",
                 "title": _title(r),
                 "payable": float(r["total_cost"] or 0),
                 "actual": float(r["total_cost"] or 0) if r["remit_actual"] is None else float(r["remit_actual"]),
                 "fee": float(r["remit_fee"] or 0), "paidAt": (r["paid_date"] or "")[:10], "review": r["remit_review"] or ""}
                for r in conn.execute(
                    "SELECT * FROM case_extra_expenses WHERE status='已核准' AND substr(paid_date, 1, 10) BETWEEN ? AND ?"
                    " AND " + _EF.payable_sql() +
                    " ORDER BY paid_date, id", (start, end)).fetchall()]

    @staticmethod
    def mark_paid(conn, key, paid_date, user, remit=None) -> dict:
        """寫回付款日與實付／手續費（`remit`＝請求 body 的 actualAmount／hasFee／fee；W1，實付≠應付 ⇒ 差額待審核）。查無 ⇒ LookupError；不是已核准或已登錄過 ⇒ ValueError（呼叫端各自轉 404／409）。不 commit（呼叫端）。

        原子（稽核 A AB-S1）：先用帶條件的 UPDATE（已核准、付款日空白）寫，`rowcount==0` 才回頭讀原因——
        兩位出納同時按「登錄付款」，後到的那位拿到「已被登錄」，不會蓋掉前者的付款日。"""
        try:
            exp_id = int(key)
        except (TypeError, ValueError):
            raise LookupError("找不到這筆申請")
        row = conn.execute("SELECT total_cost, kind, pay_terms, remit_date FROM case_extra_expenses WHERE id=?", (exp_id,)).fetchone()
        if not row:
            raise LookupError("找不到這筆申請")
        if not _EF.is_payable_kind(row["kind"] or ""):
            raise ValueError("這類單據（請購單）只是核准文件，不進出納付款")
        rm = parse_remit(remit, row["total_cost"])
        pay = _EF.parse_payout(row["kind"] or "", row["pay_terms"], row["remit_date"], remit, paid_date)   # 採購單：匯款日＋付款條件必填
        cur = conn.execute(
            "UPDATE case_extra_expenses SET paid_date=?, updated_at=?, updated_by_name=?,"
            " remit_actual=?, remit_fee=?, remit_review=?, remit_review_by='', remit_review_at='', remit_review_note='',"
            " pay_method=?, pay_account_code=?, pay_terms=?, remit_date=?, paid_by=?"
            " WHERE id=? AND status='已核准' AND COALESCE(paid_date, '')=''",
            (paid_date, datetime.now().isoformat(timespec="seconds"),
             user.get("display_name") or user.get("username") or "", rm["actual"], rm["fee"], rm["review"],
             pay["pay_method"], pay["pay_account_code"], pay["pay_terms"], pay["remit_date"], user.get("username") or "", exp_id))
        r = conn.execute("SELECT id, quote_no, status, paid_date, total_cost, category, description, payer_name"
                         " FROM case_extra_expenses WHERE id=?", (exp_id,)).fetchone()
        if cur.rowcount == 0:
            if not r:
                raise LookupError("找不到這筆申請")
            if r["status"] != "已核准":
                raise ValueError("這筆申請還沒核准，不能登錄付款")
            raise ValueError("這筆申請已被登錄付款日 %s（可能是另一位出納剛登錄）" % (r["paid_date"] or ""))
        _full = conn.execute("SELECT kind, doc_code, created_by, approval_json FROM case_extra_expenses WHERE id=?", (exp_id,)).fetchone()
        if _full is not None and (_full["kind"] or ""):                      # 費用單據（A2-7）：通知申請人已付款；kind='' 不寄
            from modules.case import expense_notify as _XN
            try:
                _req = (json.loads(_full["approval_json"] or "{}") or {}).get("requestedBy") or _full["created_by"] or ""
            except (TypeError, ValueError):
                _req = _full["created_by"] or ""
            _XN.fire("paid", conn, _full, requester=_req)
        # title／payee（2026-09-30 加欄位、相容）：出納登錄付款後推行事曆「支出付款」用
        return {"quoteNo": r["quote_no"], "key": str(exp_id), "amount": float(r["total_cost"] or 0), "paidDate": paid_date,
                "actual": rm["actual"], "fee": rm["fee"], "diff": rm["diff"], "remitReview": rm["review"],
                "title": "%s｜%s" % (r["category"] or "其他", r["description"] or ""), "payee": r["payer_name"] or ""}


# ── W1（2026-09-30）：匯款實付／手續費／差額審核（規則同 M04 `modules/subcontract/remit.py`，模組之間不互相 import ⇒ 各寫一份）──

REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
FEE_CATEGORY = "匯款手續費"


class RemitForbidden(ValueError):
    """自己登錄的付款不能自己核可／退回（呼叫端轉 403）。"""
    status = 403


class BadRemit(ValueError):
    """實付／手續費格式不對（呼叫端轉 400，不是 409）。"""
    status = 400


def _num(v, label):
    if isinstance(v, bool) or v is None or (isinstance(v, str) and not v.strip()):
        raise BadRemit("%s格式不正確" % label)
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise BadRemit("%s格式不正確" % label)
    if not math.isfinite(f):
        raise BadRemit("%s格式不正確" % label)
    return round(f + 0.0, 2)


def parse_remit(body, payable):
    """⇒ `{actual, fee, diff, review}`；實付不帶＝應付；手續費要勾 hasFee 才算（公司自付、不參與比對）；格式不對 ⇒ ValueError。"""
    body = body or {}
    payable = round(float(payable or 0), 2)
    raw = body.get("actualAmount", body.get("actual_amount"))
    actual = payable if raw in (None, "") else _num(raw, "實付金額")
    if actual <= 0:
        raise BadRemit("實付金額必須大於 0")
    fee = 0.0
    if body.get("hasFee", body.get("has_fee")):
        fee = _num(body.get("fee", body.get("remit_fee")), "手續費")
        if fee < 0:
            raise BadRemit("手續費不可為負數")
    diff = round(actual - payable, 2)
    return {"actual": actual, "fee": fee, "diff": diff, "review": REVIEW_PENDING if diff != 0 else ""}


class _RemitReviews:
    """IP-102 `remit.reviews` 提供者（名稱 `case`）：額外支出的差額待審核清單、核可／退回（退回＝回待付款）。"""

    @staticmethod
    def pending(conn):
        return [{"key": str(r["id"]), "sourceLabel": SOURCE_LABEL, "quoteNo": r["quote_no"] or "",
                 "customerName": r["customer_name"] or "", "payee": r["payer_name"] or r["created_by_name"] or "",
                 "payable": float(r["total_cost"] or 0), "actual": float(r["remit_actual"]),
                 "diff": round(float(r["remit_actual"]) - float(r["total_cost"] or 0), 2),
                 "fee": float(r["remit_fee"] or 0), "paidAt": (r["paid_date"] or "")[:10], "paidBy": r["updated_by_name"] or ""}
                for r in conn.execute(
                    "SELECT e.*, q.customer_name FROM case_extra_expenses e LEFT JOIN quotations q ON q.quote_no = e.quote_no"
                    " WHERE e.remit_review=? AND COALESCE(e.paid_date, '') != '' AND e.remit_actual IS NOT NULL ORDER BY e.id",
                    (REVIEW_PENDING,)).fetchall()]

    @staticmethod
    def decide(conn, key, decision, user, note=""):
        if decision not in ("approve", "reject"):
            raise BadRemit("decision 必須為 approve 或 reject")
        try:
            exp_id = int(key)
        except (TypeError, ValueError):
            raise LookupError("找不到這筆申請")
        r = conn.execute("SELECT id, quote_no, remit_review, updated_by_name FROM case_extra_expenses WHERE id=?",
                         (exp_id,)).fetchone()
        if not r:
            raise LookupError("找不到這筆申請")
        # W1 稽核 M4：登錄付款的人不能自己核可／退回自己的差額（updated_by_name 存顯示名稱，帳號與顯示名稱都比）
        if r["remit_review"] == REVIEW_PENDING and (r["updated_by_name"] or "") in (
                user.get("username") or "\0", user.get("display_name") or "\0"):
            raise RemitForbidden("這筆付款是您自己登錄的，差額需由其他財務角色成員或最高管理者審核")
        now = datetime.now().isoformat(timespec="seconds")
        who = user.get("display_name") or user.get("username") or ""
        if decision == "approve":
            cur = conn.execute(
                "UPDATE case_extra_expenses SET remit_review=?, remit_review_by=?, remit_review_at=?, remit_review_note=?,"
                " updated_at=?, updated_by_name=? WHERE id=? AND remit_review=?",
                (REVIEW_APPROVED, who, now, note, now, who, exp_id, REVIEW_PENDING))
        else:
            cur = conn.execute(
                "UPDATE case_extra_expenses SET paid_date='', remit_actual=NULL, remit_fee=0, remit_review='',"
                " remit_review_by='', remit_review_at='', remit_review_note='', updated_at=?, updated_by_name=?"
                " WHERE id=? AND remit_review=?", (now, who, exp_id, REVIEW_PENDING))
        if cur.rowcount == 0:
            raise ValueError("這筆申請不是待審核狀態（可能已被處理）")
        out = {"quoteNo": r["quote_no"], "key": str(exp_id), "decision": decision}
        if decision == "reject":                                   # 退回＝回待付款 ⇒ 行事曆「付款待辦」要重建；出納端 commit 後 upsert（事件內容不含金額）
            from modules.case import payable_calendar as PC
            row = conn.execute("SELECT e.*, q.customer_name AS _c, q.project_name AS _p FROM case_extra_expenses e"
                               " LEFT JOIN quotations q ON q.quote_no = e.quote_no WHERE e.id=?", (exp_id,)).fetchone()
            if row is not None and PC.eligible(row):
                title, desc, day = PC.compose(row, row["_c"] or "", row["_p"] or "")
                out["payableEvent"] = (PC.CODE, title, desc, day, PC.event_key(exp_id))
        return out


def _expense_entries(conn, start, end):
    """IP-9：付款日在 [start, end] 的額外支出匯款手續費（一筆申請一筆）。"""
    return [{"date": (r["paid_date"] or "")[:10], "quoteNo": r["quote_no"] or "",
             "desc": "%s｜%s｜%s" % (FEE_CATEGORY, r["category"] or "其他", r["description"] or ""),
             "amount": float(r["remit_fee"]), "category": FEE_CATEGORY, "pending": r["remit_review"] == REVIEW_PENDING}
            for r in conn.execute(
                "SELECT quote_no, category, description, paid_date, remit_fee, remit_review FROM case_extra_expenses"
                " WHERE remit_fee > 0 AND substr(paid_date, 1, 10) BETWEEN ? AND ? ORDER BY paid_date, id",
                (start, end)).fetchall()]
