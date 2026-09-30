# -*- coding: utf-8 -*-
"""傳票摘要的來源（案件、已上傳檔案、支出項）與案件相關傳票的取用。

2026-09-30（W4 總帳 P1）自 vouchers.py **純搬移**（行為不變）。
"""
import datetime as _dt
import json
import os
from datetime import datetime

from fastapi import APIRouter, Body, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from urllib.parse import quote

from db import get_db
# 🔑 科目代號的規則**只有一份** —— 借用既有那一支，不在這裡再寫。
#    （router 互相 import 在這個 repo 是既有做法，實查 7 處。）
from modules.accounting.api.accounting_export import validate_account_code
# `JV21`：承攬商派工的 grandTotal（含稅費用＋外包人員）算法**只有一份**——在 M04，
# 經 IP-15 成本檢視 `dispatch.cost_for_case` 取用（2026-09-26 起；原本經 IP-1 `dispatch.row`＋自己讀派工表），
# 不 import M04 的私有函式、不讀 M04 的表。
# ⚠️ **不要自己重算**：`total_amount` 少了稅、也少了外包人員費用，`ACC-BN6 §3` 已經踩過這個坑。
from core import registry as _registry
from helpers import _require_user, _tok, _audit, require_any_module
from helpers.edit_log import append_edit_log, MissingOldValue
from helpers.tiered_approval import (
    approval_flow_setting_key, setting_to_active_tiers,
    UnresolvedManagerError, active_delegators_for,
)
from helpers import _get_setting
from helpers.uploads import save_document_files
from modules.accounting.voucher_pdf import (
    export_voucher_pdf, preview_html, classify_attachment_kind,
)
from modules.accounting.voucher_attachments import (
    resolve_picks, copy_into, abs_path, case_attachments,
    line_source_files, LINE_SOURCES, EXPENSE_LINE_SOURCES, expense_line_uses, unavailable_sources, hidden_sources, CaseNotVisible, CASE_NOT_FOUND,
)
from modules.accounting.ledger import periods as _ledger_periods
from modules.accounting.voucher import (
    EDITABLE_STATUSES, can_edit, describe_balance, get_voucher,
    next_voucher_no, post_voucher, can_send_back, next_revision_no,
    diff_lines, approval_done, parse_approval_json, VoucherChainUnreadable,
    normalize_amount_lines, classify_category,
)



#: 摘要來源的頁籤（`§159b` (7) 使用者原話：「摘要部分也要有分頁選單
#: 帶入案件跟哪些已上傳檔案」；第三格是 `JV21`）。**可數完備**：少一個
#: 使用者會報修，而多一個**不會有人報修** —— 那表示有人加了來源而沒有人
#: 決定它的格式。
SUMMARY_TABS = ("案件", "已上傳檔案", "支出項")

#: M01 不在（沒有 case.summary）時的說明
CASES_UNAVAILABLE = "案件模組未安裝：無法從案件帶入摘要。"

#: 清單長度上限。案件會一直長，而這是一個**選單**不是報表。
_SOURCE_LIMIT = 50


def case_summary(customer_name, quote_no):
    """案件來源帶入的那個字串（`§164`）。

    ```
    某客戶報價單MQ-YYYYMM-NNN
    ```

    ## 🔴 取不到的那一段**省略**，不是留一個洞

    `§164` 逐字：「取不到廠商或發票號的欄位就省略那一段，**不要填空字串佔位**」。
    ☠️ 填佔位的樣子很具體，而它**不會報錯**：
    ```
    「3/30  AB12345678」      <= 兩個空白（廠商是空的）
    「3/30 None AB12345678」  <= Python 的 %s
    「3/30 undefined …」      <= JS 的樣板字串
    ```
    ⇒ 使用者只會覺得「怎麼多一個空格」，然後手動刪掉，**每一張單都刪一次**。

    ## ⚠️ 省略的是**缺的那一段**，不是整個字串

    客戶取不到 ⇒ 仍然要帶得出報價單號那一段。
    ☠️ 整串變空的話，使用者點了來源而摘要欄沒反應 —— 那讀起來像「壞了」。

    ## 🔑 字串在**後端**組，不在 JS

    ```
    格式寫在 JS   => JV5 的 PDF 匯出讀不到它 => 兩邊會長不一樣
    格式寫在後端  => 兩邊同一個來源
    ```
    """
    parts = []
    name = (customer_name or "").strip()
    no = (quote_no or "").strip()
    if name:
        parts.append(name)
    if no:
        parts.append("報價單" + no)
    return "".join(parts)


def _fmt_money(n):
    """`NT$` 後面接的數字：整數就不印小數點（傳票版面其餘金額欄一律整數）。"""
    n = float(n or 0)
    if n == int(n):
        return "%d" % int(n)
    return ("%.2f" % n).rstrip("0").rstrip(".")


def _dispatch_expense_entry(d):
    """`JV21` §3b①：一筆承攬商派工——第二層（派工本身）＋ 第三層（品項／人員）。

    ⚠️ 金額**借用 M04 連接器 `dispatch.row` 的 `grandTotal`**（含稅承攬商費用＋外包
    人員個別計費），不用 `total_amount`——那一欄少了稅、也少了人員費用
    （`§2b`：`ACC-BN6 §3` 已經踩過這個坑）。

    ## 🔴 品項與人員是**兩種不同的第三層**，鍵完全不同

    `items_json[]` 用 `description／qty／unit／unitPrice／amount`；
    `personnel_json[]` 只有 `name／amount`——不可以用同一個判斷式處理兩者，
    也不可以把兩邊的 `id` 混用（`items[].id` 是前端產生的浮點時間戳，
    `personnel[].id` 是小整數，語意不同）。⇒ 這裡改用 `(kind, index)` 識別
    子列，不碰它們各自的 `id`。

    ⚠️ 金額直接讀每一筆自己的 `amount`（`dispatch.row` 算 `grandTotal`
    用的也是同一個欄位），**不用 `unitPrice` 重算**——那一欄型別不一致
    （`6800` 與 `"12000"` 都出現過），會算的話要先擋空字串，這裡沒有這個
    必要就不引入這個風險。
    """
    # 2026-09-26（主持裁示）：輸入是 IP-15 成本檢視 `dispatch.cost_for_case` 的一筆（不再自己讀 M04 的表）。
    # 成本檢視不回外包人員姓名與 personnel ⇒ 第三層原本逐人列姓名的位置改成一行「外包人員 N 人」（金額＝人員合計）。
    vendor = (d.get("vendorName") or "").strip()
    scope = (d.get("scope") or "").strip()
    head = "－".join(p for p in (vendor, scope) if p)
    summary = "%s　NT$ %s" % (head or "承攬商派工", _fmt_money(d.get("amount")))
    if d.get("invoiceNo"):
        summary += "　發票：%s" % d["invoiceNo"]

    prefix = (vendor + "－") if vendor else ""
    children = []
    for idx, it in enumerate(d.get("items") or []):       # 成本檢視已只留有描述的品項
        desc = str(it.get("description") or "").strip()
        if not desc:
            continue
        children.append({
            "kind": "dispatch_item", "index": idx,
            "description": desc, "amount": it.get("amount") or 0,
            "summary": "%s%s　NT$ %s" % (prefix, desc, _fmt_money(it.get("amount"))),
        })
    n = int(d.get("personnelCount") or 0)
    if n:
        children.append({
            "kind": "dispatch_personnel", "index": 0,
            "name": "外包人員 %d 人" % n, "count": n, "amount": d.get("personnelTotal") or 0,
            "summary": "%s外包人員 %d 人　NT$ %s" % (prefix, n, _fmt_money(d.get("personnelTotal"))),
        })

    return {
        "kind": "contractor_dispatch",
        "id": d["id"],
        "vendorName": vendor,
        "scope": scope,
        "amount": d.get("amount") or 0,
        "invoiceNo": d.get("invoiceNo") or "",
        "summary": summary,
        "items": children,
    }


def _extra_expense_entry(row):
    """`JV21` §3b②：一筆案件額外支出——**沒有第三層**。

    A 問甲／乙後選甲（展開後只有一層，畫面說實話）：這張表自己就有
    `description／qty／unit／unit_cost` 這些「品項該有的欄位」，一筆資料
    就是一個品項，不假裝再多一層——多一層的代價是使用者點開箭頭看到一筆
    與上一層一模一樣的東西，會以為自己點錯了。
    """
    r = dict(row)
    text = str(r.get("description") or "").strip() or str(r.get("note") or "").strip()
    summary = "%s　NT$ %s" % (text or "額外支出", _fmt_money(r.get("total_cost")))
    if r.get("doc_no"):
        summary += "　憑證：%s" % r["doc_no"]
    return {
        "kind": "extra_expense",
        "id": r["id"],
        "category": r.get("category") or "",
        "description": r.get("description") or "",
        "amount": r.get("total_cost") or 0,
        "docNo": r.get("doc_no") or "",
        "summary": summary,
        "items": [],
    }


#: IP-15 成本檢視拒絕這個人（403）時的說明（主持裁示：任何來源因權限沒列出都要明說）
DISPATCH_COST_FORBIDDEN = "你沒有權限查看承攬商派工的成本：派工支出沒有列出（不是沒有）"
#: IP-15 成本檢視不在（M04 未安裝）時的說明
DISPATCH_COST_UNAVAILABLE = "外包工班模組未安裝：承攬商派工無法作為支出來源"


def _dispatch_costs(quote_no, authorization):
    """IP-15 `dispatch.cost_for_case` ⇒ (清單, 說明)。提供者不在 ⇒ ([], UNAVAILABLE)；403 ⇒ ([], FORBIDDEN)。"""
    fn = _registry.single_provider("dispatch.cost_for_case")
    if fn is None:
        return [], DISPATCH_COST_UNAVAILABLE
    try:
        return list(fn(quote_no, authorization)), ""
    except HTTPException as e:
        if e.status_code == 403:
            return [], DISPATCH_COST_FORBIDDEN
        raise


def _case_expense_sources(conn, quote_no, authorization=None):
    """`JV21` §2/§3：案件底下「有金額有發票」的支出項——目前兩種來源。

    ⚠️ **不是** `SOURCE_TYPES` 的逐種列舉：那份清單回答的是「附件能不能被
    帶入」，這裡回答的是「這是不是一筆有金額的支出」——兩個問題不同。
    叫料（`material`）在附件清單裡存在，在這裡**進不來**：`§2b` 實測
    `caseRecord.materials[]` 沒有任何金額欄位，是物流追蹤不是支出記錄，
    不是形狀問題，是它不是支出。`invoice_voucher`（開票申請）也不在
    這裡——那是開給客戶的票，不是我們的支出。
    """
    out = []
    # 承攬商派工：IP-15 成本檢視（M04 提供；不在或讀不到 ⇒ 這一類不列、呼叫端明說，額外支出照常）
    costs, _note = _dispatch_costs(quote_no, authorization)
    for d in costs:
        out.append(_dispatch_expense_entry(d))
    for row in conn.execute(
            "SELECT * FROM case_extra_expenses WHERE quote_no=? ORDER BY id",
            (quote_no,)):
        out.append(_extra_expense_entry(row))
    return out
