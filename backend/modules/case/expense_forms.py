# -*- coding: utf-8 -*-
"""費用單據（A2）在案件額外支出表上的共用規則：類型代碼、單號、明細金額、`data_json`／`lines_json` 的驗證與合併。

契約來源：D:\\開發測試檔\\plan-expense-a2.md §7（W1 2026-10-01 定案）。純函式、不碰資料庫（單號配號除外，要傳連線）。
**L1 的 `helpers.expense_types.validate_values`（A2-2）到位後，`normalize_lines`／`is_payable_kind` 各換成一行委派**——所以讀取點都集中在這裡。

下游效應（R1）：`total_cost`（＝Σ 明細 amount，整數 TWD）是營運報表支出、總帳應付、出納付款金額的唯一來源；
明細與 data 只做保存與顯示，不直接被金流讀。
"""
import json

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


def next_doc_code(conn, kind: str, today: str) -> str:
    """`{前綴}-{YYYYMMDD}-{NNNN}`（W1 §7.3）。呼叫端要已持有寫鎖（begin_write），否則兩個人同時開單會撞號（doc_code 另有唯一索引擋）。"""
    prefix = KIND_PREFIX[kind]
    stem = "%s-%s-" % (prefix, today.replace("-", ""))
    row = conn.execute("SELECT MAX(doc_code) FROM case_extra_expenses WHERE doc_code LIKE ? AND LENGTH(doc_code)=?",
                       (stem + "%", len(stem) + 4)).fetchone()
    last = int(row[0][-4:]) if row and row[0] else 0
    return "%s%04d" % (stem, last + 1)
