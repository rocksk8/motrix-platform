# -*- coding: utf-8 -*-
"""費用單據（A2）在案件額外支出表上的共用規則：類型代碼、單號、明細金額、`data_json`／`lines_json` 的驗證與合併。

契約來源：D:\\開發測試檔\\plan-expense-a2.md §7（W1 2026-10-01 定案）。純函式、不碰資料庫（單號配號除外，要傳連線）。
**L1 的 `helpers.expense_types.validate_values`（A2-2）到位後，`normalize_lines`／`is_payable_kind` 各換成一行委派**——所以讀取點都集中在這裡。

下游效應（R1）：`total_cost`（＝Σ 明細 amount，整數 TWD）是營運報表支出、總帳應付、出納付款金額的唯一來源；
明細與 data 只做保存與顯示，不直接被金流讀。
"""
import json
from datetime import date

from fastapi import HTTPException

from helpers.legal_params import round_half_up

#: 已知類型（kind=''＝舊版案件額外支出，不在這裡）。W1 的 register_kind（A2-0）到位後改讀定義表。
KINDS = ("purchase_req", "purchase_order", "travel", "petty_cash")
KIND_PREFIX = {"purchase_req": "PR", "purchase_order": "PO", "travel": "TE", "petty_cash": "PC"}
#: 請購單只是核准文件（不進 IP-100、不入營運報表支出）；其餘類型核准後進出納
_PAYABLE_KINDS = frozenset({"purchase_order", "travel", "petty_cash"})

#: `data_json` 的平台保留鍵（定義可另外用任意鍵）。`dept` 同步寫入 `department_id` 欄。
RESERVED_DATA_KEYS = ("applicant", "dept", "cost_dept", "req_date", "pay_date", "urgency", "pay_terms", "remit_date")

MAX_LINES = 200
MAX_DATA_BYTES = 20000
MAX_LINES_BYTES = 200000
MAX_TEXT = 500


def is_payable_kind(kind: str) -> bool:
    """這個類型核准後要不要進出納待付款。kind=''（舊版）＝今天的行為＝要。"""
    return (kind or "") == "" or kind in _PAYABLE_KINDS


def payable_sql(alias: str = "") -> str:
    """SQL 片段：只留「核准後要進金流」的列（kind='' 或 payable 類型）。請購單（purchase_req）不進應付／營運報表支出／出納。
    片段只含本檔常數（不含使用者輸入）。"""
    p = (alias + ".") if alias else ""
    return "(%skind = '' OR %skind IN (%s))" % (p, p, ",".join("'%s'" % k for k in sorted(_PAYABLE_KINDS)))


def check_kind(kind: str) -> str:
    kind = (kind or "").strip()
    if kind and kind not in KINDS:
        raise HTTPException(400, "不認得的單據類型：%s" % kind[:40])
    return kind


def _num(v, label, allow_none=False):
    if v is None or v == "":
        if allow_none:
            return None
        raise HTTPException(400, "%s必須是數字" % label)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise HTTPException(400, "%s必須是數字" % label)
    if v != v or v in (float("inf"), float("-inf")):
        raise HTTPException(400, "%s必須是有限的數字" % label)
    return v


def normalize_lines(lines) -> tuple:
    """明細列 ⇒ `(乾淨的列, total_cost)`。

    金額權威（W1 §7.1）：列上 `qty` 與 `unitCost` **都是**數字 ⇒ `amount = round_half_up(qty × unitCost)`（前端的 amount 不採用）；
    否則 `amount` 是權威（數字、≥0）。`total_cost = Σ amount`，每列先四捨五入到元。
    定義自訂的明細欄（任何未知鍵）**原樣保留**，不得丟（沉默丟資料清單第一條）。
    """
    if lines is None:
        lines = []
    if not isinstance(lines, list):
        raise HTTPException(400, "明細必須是陣列")
    if len(lines) > MAX_LINES:
        raise HTTPException(400, "明細最多 %d 列" % MAX_LINES)
    out, total = [], 0
    for i, raw in enumerate(lines, 1):
        if not isinstance(raw, dict):
            raise HTTPException(400, "第 %d 列格式不對" % i)
        row = dict(raw)                                          # 未知鍵原樣保留
        for k in ("category", "accountCode", "summary", "invoiceNo"):
            if k in row and row[k] is not None:
                if not isinstance(row[k], str):
                    raise HTTPException(400, "第 %d 列 %s 必須是文字" % (i, k))
                row[k] = row[k].strip()
                if len(row[k]) > MAX_TEXT:
                    raise HTTPException(400, "第 %d 列 %s 太長（上限 %d 字）" % (i, k, MAX_TEXT))
        qty = _num(row.get("qty"), "第 %d 列數量" % i, allow_none=True)
        unit = _num(row.get("unitCost"), "第 %d 列單價" % i, allow_none=True)
        if qty is not None and unit is not None:
            if qty < 0 or unit < 0:
                raise HTTPException(400, "第 %d 列數量與單價不能為負" % i)
            amount = round_half_up(qty * unit)
        else:
            amt = _num(row.get("amount"), "第 %d 列金額" % i)
            if amt < 0:
                raise HTTPException(400, "第 %d 列金額不能為負" % i)
            amount = round_half_up(amt)
        row["amount"] = amount
        total += amount
        out.append(row)
    return out, total


def normalize_data(data, existing: dict = None) -> dict:
    """`data_json`：必須是物件；與既有值**合併**（前端只送一部分也不會丟掉沒送的鍵；值為 None ⇒ 明確刪除該鍵）。"""
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise HTTPException(400, "欄位資料必須是物件")
    merged = dict(existing or {})
    for k, v in data.items():
        if not isinstance(k, str) or len(k) > 80:
            raise HTTPException(400, "欄位鍵不合法")
        if v is None:
            merged.pop(k, None)
        else:
            merged[k] = v
    if len(json.dumps(merged, ensure_ascii=False)) > MAX_DATA_BYTES:
        raise HTTPException(400, "欄位資料太大（上限 %d 字元）" % MAX_DATA_BYTES)
    return merged


def current_def_version(conn, kind: str) -> int:
    """目前生效的類型定義版本（W1 `helpers.expense_types.get_type`；公司發布版的版本號，沒發布過＝程式預設＝0）。
    單據在**建立**與**送審**當下把它釘在列上（`def_version`）：之後定義改了，這張單據的輸出／驗證仍依它自己的版本，不被改版牽動。
    W1 的模組不在（舊環境）或查無此類型 ⇒ 0（＝程式預設），不擋流程。"""
    if not kind:
        return 0
    try:
        from helpers import expense_types as _ET
    except ImportError:
        return 0
    t = _ET.get_type(conn, kind)
    try:
        return int(t["version"]) if t else 0
    except (TypeError, ValueError, KeyError):
        return 0


def prepare_submit(conn, lines: list) -> list:
    """送審當下處理明細的費用類別（W4 合約 2026-10-01）：
    1. 提供者 `expense.categories` 在 ⇒ 每列的 `category`（代碼或名稱）必須是**啟用中**的類別，否則 400（狀態不變）；
       通過的列寫入 `categoryCode`（代碼，改名不會壞）＋`categoryName`（顯示快照）。提供者不在，或提供者回**空清單**（尚未設定任何費用類別）⇒ 不驗證、不加。
    2. 提供者 `gl.category_account` 在 ⇒ 寫入唯讀的 `accountCode` 快照（**只供顯示**：過帳時總帳從事件行的 category 重新解，之後改對照表以新的為準）；
       解不出來（None）⇒ 空字串。提供者不在 ⇒ 不動。
    草稿可以放任何類別；只有送審擋。回新的明細列（不改傳入的）。"""
    from core import registry
    cats_fn = registry.providers("expense.categories").get("accounting")
    acct_fn = registry.providers("gl.category_account").get("accounting")
    out = [dict(l) for l in (lines or [])]
    if cats_fn is not None:
        cats = cats_fn(conn) or []
        by_code = {c["code"]: c["name"] for c in cats}
        by_name = {c["name"]: c["code"] for c in cats}
        for i, l in (enumerate(out, 1) if cats else ()):      # 清單是空的＝公司還沒設定費用類別 ⇒ 不驗證（不擋人；總帳以既有 category_unmapped 備註落到預設科目）；有 ≥1 個啟用類別就嚴格驗證
            v = (l.get("categoryCode") or l.get("category") or "").strip()
            if v in by_code:
                code = v
            elif v in by_name:
                code = by_name[v]
            else:
                raise HTTPException(400, "第 %d 列的費用類別「%s」不是啟用中的類別，請重新選擇" % (i, v[:40]))
            l["categoryCode"], l["categoryName"] = code, by_code[code]
    if acct_fn is not None:
        for l in out:
            key = l.get("categoryCode") or l.get("category") or ""
            l["accountCode"] = (acct_fn(conn, key) or "") if key else ""
    return out


def dumps_lines(lines: list) -> str:
    s = json.dumps(lines, ensure_ascii=False)
    if len(s) > MAX_LINES_BYTES:
        raise HTTPException(400, "明細太大（上限 %d 字元）" % MAX_LINES_BYTES)
    return s


def department_of(data: dict, explicit=None):
    """部門 id：明確給的 `departmentId` 優先，否則取 `data.dept`（W1 §7.2：dept 鏡射到 department_id）；不是整數 ⇒ None。"""
    for v in (explicit, (data or {}).get("dept")):
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.strip().isdigit():
            return int(v.strip())
    return None


#: 付款方式（出納登錄付款時選）：總帳貸方腿由它決定（零用金貸 PETTY 1112，其餘貸銀行 1113；W4 的 E11b 讀 `pay_method`／`pay_account_code`）
PAY_METHODS = ("transfer", "cash", "petty_cash")
PAY_METHOD_LABEL = {"transfer": "轉帳", "cash": "現金", "petty_cash": "零用金"}


def parse_payout(kind: str, row_pay_terms: str, row_remit_date: str, body: dict, paid_date: str) -> dict:
    """出納登錄付款時的新欄位 ⇒ `{pay_method, pay_account_code, pay_terms, remit_date}`；不合法 ⇒ ValueError(status=400)（狀態不變）。

    - 採購單（purchase_order）：**匯款日與付款條件必填**（本次 body 有給就用，否則沿用單據上已填的；都沒有 ⇒ 400）
    - 零用金支付單（petty_cash）：付款方式**必填**（零用金／現金／轉帳）；其他類型預設轉帳（可選現金）
    - 付款科目（`payAccountCode`）選填：只做格式檢查，科目是否存在由出納端點用會計連接器驗
    下游效應（R1）：付款方式決定總帳 E11b 貸方腿（W4）；營運報表現金口徑只看付款日與實付，不受影響。"""
    body = body or {}

    def bad(msg):
        e = ValueError(msg)
        e.status = 400
        return e
    method = str(body.get("payMethod") or "").strip()
    if method and method not in PAY_METHODS:
        raise bad("付款方式只能是：%s" % "、".join(PAY_METHOD_LABEL[m] for m in PAY_METHODS))
    if kind == "petty_cash" and not method:
        raise bad("零用金支付單必須選擇付款方式（零用金／現金／轉帳）")
    method = method or "transfer"
    terms = str(body.get("payTerms") or "").strip() or (row_pay_terms or "")
    remit = str(body.get("remitDate") or "").strip() or (row_remit_date or "")
    if kind == "purchase_order":
        if not terms:
            raise bad("採購單請填寫付款條件")
        if not remit:
            raise bad("採購單請填寫匯款日")
    if len(terms) > MAX_TEXT:
        raise bad("付款條件太長（上限 %d 字）" % MAX_TEXT)
    if remit:
        try:
            date.fromisoformat(remit)
        except ValueError:
            raise bad("匯款日必須是有效的日期（YYYY-MM-DD）")
    acct = str(body.get("payAccountCode") or "").strip()
    if len(acct) > 20:
        raise bad("付款科目代碼太長")
    return {"pay_method": method, "pay_account_code": acct, "pay_terms": terms, "remit_date": remit or paid_date}


def next_doc_code(conn, kind: str, today: str) -> str:
    """`{前綴}-{YYYYMMDD}-{NNNN}`（W1 §7.3）。呼叫端要已持有寫鎖（begin_write），否則兩個人同時開單會撞號（doc_code 另有唯一索引擋）。"""
    prefix = KIND_PREFIX[kind]
    stem = "%s-%s-" % (prefix, today.replace("-", ""))
    row = conn.execute("SELECT MAX(doc_code) FROM case_extra_expenses WHERE doc_code LIKE ? AND LENGTH(doc_code)=?",
                       (stem + "%", len(stem) + 4)).fetchone()
    last = int(row[0][-4:]) if row and row[0] else 0
    return "%s%04d" % (stem, last + 1)
