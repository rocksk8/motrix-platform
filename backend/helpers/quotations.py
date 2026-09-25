"""Quotation hot-path field sync helpers."""
import json
import logging
import os
import re
import traceback
from datetime import date, datetime

from fastapi import HTTPException

from core import txn as _txn
from helpers import row_access


# Prefer real columns; fall back to data_json for rows not yet re-saved (pre-v6 backward compat).
# IMPORTANT: never use bare `SELECT deal_tag` — always use SQL_DEAL_TAG to correctly read pre-v6 rows.
SQL_DEAL_TAG = "COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '')"
SQL_SETTLE_STATUS = (
    "COALESCE(NULLIF(settle_status,''), json_extract(data_json,'$.settlement.status'), '')"
)


# ── M01 案件可見性：登錄到 L1 row_access（DEPENDENCY-MAP §0-5）──────────────────
# 取代原 `_check_quotation_owner()`（單筆）與 routers/quotations.py `_visible_case_filter_sql()`
# （SQL）兩份各自實作；兩種形式現在由同一份宣告推導，等價由 tests/test_row_access_2026_09_25.py 守。
#   owner：admin+／本人業務（sales_person_id）／舊資料（id 為 NULL 比顯示名稱）／assigned_user_ids
#   read ：owner＋持 cashier 模組者（CM14b，2026-09-24 使用者裁示「讀得到，但只能改收款」）
# 🔑 這段在模組層：啟動時經 routers.quotations → helpers 匯入即登錄；M01 搬進 modules/ 時一起帶走。
#    沒登錄時 row_access 一律 fail closed（只會少看到，不會多看到）。
CASE_ACCESS = row_access.OwnerRule(
    owner_id_col="sales_person_id",
    legacy_name_col="sales_person",
    id_list_cols=("assigned_user_ids",),
    lenient_json=False,
    read_bypass_modules=("cashier",),
    deny_message="無權限存取其他業務的報價單",
)
row_access.register("case", CASE_ACCESS)


def is_document_approver(data_json: str, user: dict, conn) -> bool:
    """這個人是否在這張單的簽核名單裡（任何一層），或本人就是送審申請人。

    含目前有效的簽核代理人——代理人在簽核路徑上處處被視同本人
    （`check_approve_permission()` 等），檢視權限沒有理由是例外。
    """
    from helpers.tiered_approval import active_tiers, active_delegators_for
    try:
        parsed = json.loads(data_json or "{}") or {}
    except Exception:
        return False
    # 兩種存法都吃：報價單／三種憑證流存成 `data_json.approval`；案件額外支出
    # 存成獨立欄位 `approval_json`（內容就是 approval 物件本身，沒有外層包裝）。
    appr = parsed.get("approval") if isinstance(parsed.get("approval"), dict) else parsed
    names = {a["username"] for tier in (active_tiers(appr) or [])
             for a in (tier.get("approvers") or []) if a.get("username")}
    if appr.get("requestedBy"):
        names.add(appr["requestedBy"])
    if user["username"] in names:
        return True
    try:
        return bool(set(active_delegators_for(conn, user["username"])) & names)
    except Exception:
        return False


def case_access_allowed(conn, q, user: dict, *, allow_approver: bool = False,
                        allow_module: str = None) -> bool:
    """單一案件列 `q`（需含 sales_person_id、sales_person、assigned_user_ids、data_json）准不准這個人動。
    規則只有這一份：row_access `case`／scope="owner"，否則 `allow_module`，否則（`allow_approver`）簽核人。
    `guard_case_access()` 與 `routers/quotations.py::_guard_case()` 都呼叫這一支（稽核 Y-5）。"""
    if row_access.visible("case", user, q, scope="owner"):
        return True
    from helpers.auth import user_has_module
    return bool((allow_module and user_has_module(user, allow_module))
                or (allow_approver and is_document_approver(q["data_json"], user, conn)))


def guard_case_access(conn, quote_no: str, user: dict, *, allow_approver: bool = False,
                      allow_module: str = None):
    """「用 quote_no 直接取單一案件」的共用守門（2026-09-13 模組權限稽核）。

    `quote_no` 可列舉（`MQ-YYYYMM-NNN`），少了這道就是 IDOR。規則是 `row_access`
    的 `case`／scope="owner"（見上方 `CASE_ACCESS`）：admin+ 直通，否則必須是該案業務或
    `assigned_user_ids` 裡的協作者。放在 helpers 而不是某支 router，是因為需要它的地方橫跨
    `quotations.py`／`case_action_items.py`／完工單／出貨單／三種憑證流／網路架構
    規劃書——2026-09-10 `_check_quotation_owner()` 從 router 搬到這裡的理由完全相同
    （當時是叫料 API 忘了加，把同一個 IDOR 又開了一次）。

    `allow_module`：案件執行面（階段、拜訪、動態、完工單／出貨單清單…）額外放行
    具該模組的人。⚠️ 這條不是偷懶——實測開發機 26 張報價單，`assigned_user_ids`
    有值的是 0 張，「指派協作者」實務上沒被使用過，純擁有者規則會讓 engineer 角色
    對全部案件的存取權變成 0。金額面（精算、應收應付）不放寬。

    `allow_approver`：簽核路徑上的人（含代理人）也放行，給單據 PDF 下載用。

    擋下來時順手把連線關掉：呼叫端清一色是「conn = get_db() → 操作 → close()」的
    直線寫法，沒有 try/finally。
    """
    q = conn.execute(
        "SELECT sales_person_id, sales_person, assigned_user_ids, data_json "
        "FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    if not q:
        _txn.safe_close(conn)
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    if not case_access_allowed(conn, q, user, allow_approver=allow_approver, allow_module=allow_module):
        _txn.safe_close(conn)
        raise HTTPException(403, CASE_ACCESS.deny_message)
    return q


def norm_at(s: str) -> str:
    """統一時間格式（部分表用 'YYYY-MM-DDTHH:MM:SS[.ffffff]'，部分用空白分隔且無
    微秒），確保跨來源合併排序正確。2026-08-28：抽成共用函式——原本 dashboard.py
    的活動動態（首頁）跟 quotations.py::list_case_updates()（案件管理「動態」Tab）
    是同一種「合併多張表、依 created_at 字串排序」的動態牆邏輯，前者已經套用這個
    正規化，後者原本只對其中一個來源（audit_log）做了同樣的處理、其餘四個來源
    （case_updates／work_logs／daily_task_completions／dev_logs）維持各自原始格式
    直接排序——dev_logs 存的是空白分隔格式，跟其餘多數來源的 'T' 分隔格式排序時
    永遠排在同一天其他來源之前（ASCII 空白 0x20 < 'T' 0x54），不管實際時間點是
    幾點，導致同一天有業務開發記錄時動態牆順序會錯亂。兩處統一改呼叫這支共用
    函式，不要再各自處理一部分來源就以為排序沒問題。"""
    return (s or "").replace("T", " ")[:19]


def _steps_to_tiers(steps: list) -> list:
    """Convert old single-approver steps list to modern tiers list (no status fields)."""
    return [
        {
            "order": i,
            "approvers": [{
                "userId":      s.get("userId", 0),
                "username":    s.get("username", ""),
                "displayName": s.get("displayName", s.get("username", "")),
            }],
        }
        for i, s in enumerate(steps)
    ]


# ── 營業稅（AC1，2026-09-24 使用者：「會計稅率1~4%取消，直接依法規進行，用現金折讓就好」）──
#
# 營業稅法 §14 I（逐字）：「…分別按第七條或第十條規定計算其銷項稅額，尾數不滿通用貨幣
# 一元者，按四捨五入計算」；§7 零稅率、§8 免稅。
# ⇒ 稅別只有三種；稅額＝round_half_up(銷售額 × 5%)。報價、開票申請、稅務匯出同一算法。
# 業務讓價走報價的「折讓」欄位，不再用調低稅率。

#: 報價稅別。`legacy` 不是可選的稅別，是「已停用的 1～4%」舊單的讀取結果。
TAX_TYPES = ("taxable", "zero", "exempt")
TAX_TYPE_LABELS = {"taxable": "應稅 5%", "zero": "零稅率", "exempt": "免稅"}
LEGAL_TAX_RATE = 0.05
LEGACY_TAX_NOTE = "非法定稅率，請會計確認"


def round_half_up(n, rate=1) -> int:
    """四捨五入到元（Python 內建 round 是銀行家捨入：round(490.5) == 490）。

    轉呼叫 L1 `helpers.legal_params.round_half_up`（金額捨入的唯一來源；X-VAT，2026-09-26）。
    保留這個名字是因為既有呼叫端（recognition、reports）從這裡 import。
    """
    from helpers.legal_params import round_half_up as _rhu
    return _rhu(n, rate)


def quote_tax_type(data: dict) -> str:
    """報價的稅別。沒有 `taxType` 的舊資料（不做 migration）：稅率 0 ⇒ 免稅（原選項標籤就是
    「0%（免稅）」）、1～4 ⇒ `legacy`（已停用，數字不改、輸出標示）、其餘 ⇒ 應稅。"""
    data = data or {}
    t = data.get("taxType")
    if t in TAX_TYPES:
        return t
    rate = data.get("taxRate")
    if rate is None or rate == "":
        return "taxable"
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        return "taxable"
    if rate == 0:
        return "exempt"
    if 0 < rate < 5:
        return "legacy"
    return "taxable"


def validate_quote_tax(q: dict) -> None:
    """報價存檔（建立／修改）時的稅別檢查：只能是法定稅別，且稅別與稅率一致。

    舊的 1～4% 單再編輯存檔時必須改選法定稅別（hichan-0a 代裁）；案件記錄、收款等
    其他存檔路徑不經過這裡 ⇒ 舊單仍可收款、登錄發票。
    """
    q = q or {}
    t = q.get("taxType")
    if t not in (None, "") and t not in TAX_TYPES:
        raise HTTPException(400, "稅別不正確（只能是應稅 5%、零稅率或免稅）")
    kind = quote_tax_type(q)
    if kind == "legacy":
        raise HTTPException(400, "此報價使用已停用的稅率 %s%%，請改選法定稅別（應稅 5%%、零稅率或免稅）後再存檔"
                            % q.get("taxRate"))
    if t in TAX_TYPES:
        try:
            rate = float(q.get("taxRate", 5 if t == "taxable" else 0))
        except (TypeError, ValueError):
            rate = -1
        if rate != (5 if t == "taxable" else 0):
            raise HTTPException(400, "稅別與稅率不一致（應稅為 5%%，零稅率與免稅為 0%%）")


# ── R2（2026-09-25，CUSTOMIZATION-SPEC §9.2）：零稅率、免稅要有依據 ─────────────────
#
# 選項與檢查在 L1 `helpers.legal_params`（開票申請等其他模組共用）；這裡只決定「報價何時必填」。
from helpers.legal_params import TAX_BASIS_OPTIONS, tax_basis_error, tax_basis_label  # noqa: E402,F401


def validate_tax_basis(q: dict, status) -> None:
    """報價存檔：零稅率／免稅且**不是草稿** ⇒ 依據必填（草稿可先存，自動存檔不被擋）。
    應稅單的 taxBasis 移除（避免殘留的依據被印出來）。"""
    q = q if isinstance(q, dict) else {}
    kind = quote_tax_type(q)
    if kind not in ("zero", "exempt"):
        q.pop("taxBasis", None)
        return
    if (status or q.get("status") or "草稿") == "草稿":
        return
    err = tax_basis_error(kind, q.get("taxBasis"))
    if err:
        raise HTTPException(400, err)


def tax_split(sales, tax_type: str) -> tuple:
    """(銷售額, 稅額)。應稅 ⇒ 稅額＝round_half_up(銷售額 × 5%)；零稅率／免稅 ⇒ 0。

    ⚠️ `legacy` 不在這裡處理：舊 1～4% 單不改數字，由呼叫端沿用原本的算法並標示。
    """
    sales = round_half_up(sales)
    if tax_type == "taxable":
        return sales, round_half_up(sales, LEGAL_TAX_RATE)
    if tax_type in ("zero", "exempt"):
        return sales, 0
    raise ValueError("tax_split 不處理稅別 %r（舊 1～4% 單由呼叫端沿用原算法）" % tax_type)


def _invoice_amount(v):
    """發票金額欄位：空＝沒填（None）；否則必須是非負整數（新台幣元）。"""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, bool):
        raise HTTPException(400, "發票金額格式不正確")
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise HTTPException(400, "發票金額格式不正確")
    if f < 0 or f != int(f):
        raise HTTPException(400, "發票金額以新台幣元為單位，不可有小數或負數")
    return int(f)


def invoice_amounts(item: dict):
    """收款項上登錄的發票未稅／稅額；兩欄都有才回 (未稅, 稅額)，否則 None。"""
    p = _invoice_amount((item or {}).get("invoicePretax"))
    t = _invoice_amount((item or {}).get("invoiceTax"))
    return (p, t) if p is not None and t is not None else None


def validate_invoice_amounts(item: dict) -> None:
    """AC1（使用者選 (a)）：收款登錄發票時選填「發票未稅／稅額」。

    - 兩欄都填 ⇒ 稅務匯出以它為準；都不填 ⇒ 用算式。
    - **只填一欄 ⇒ 拒存**：一半的發票金額不能作為申報依據，而它會讓人以為已經登錄了。
    - 兩欄合計 ≠ 該期金額 ⇒ **只提示、不擋**（提示在畫面；發票本來就可能與約定金額差 ±1）。
    """
    p = _invoice_amount((item or {}).get("invoicePretax"))
    t = _invoice_amount((item or {}).get("invoiceTax"))
    if (p is None) != (t is None):
        raise HTTPException(400, "發票未稅與稅額要一起填寫（只填一欄無法作為申報依據）")


def payment_item_amounts(total: float, pay_items: list, pretax: float = None,
                          apply_tax_exempt: bool = True) -> list:
    """Return the effective **receivable** amount for each payment item, in order.

    Trusts each item's stored `amount` field when present — that's what the
    editing UI (case-management.js) actually saved after the user finished
    adjusting percentages/amounts, and is the source of truth. Only falls back
    to reconstructing from `pct` for legacy rows that predate the `amount`
    field being written, with the first item absorbing whatever rounding
    remainder is left over from the rest (so the sum always equals `total`
    exactly). Every backend spot that lists/reports on payment items
    (dashboard.py receivables, reports.py financial reports/PDF/Excel) must
    use this — duplicating the pct-reconstruction formula in each place is
    what let dashboard/reports drift out of sync with what the edit UI
    actually saved (and with each other, if the copies ever diverge).

    2026-08-28: an item with `taxExempt=True` (approved tax write-off, see
    routers/quotations.py::approve_payment_writeoff()) is only actually
    receivable at its untaxed value — the customer no longer owes the tax
    portion. approve_payment_writeoff() only ever sets the taxExempt flag and
    never touches the stored `amount` itself, so without this the raw
    (still tax-inclusive) `amount` silently kept flowing into every
    backend-wide rollup that calls this shared helper (reports.py, AR aging,
    dashboard.py receivables) even after a write-off was approved — case-
    management.js already got this right client-side via itemAmountPretax(),
    this brings the shared backend helper in line with it. Conversion mirrors
    the frontend formula exactly (item's share of the quote's untaxed/taxed
    ratio, not a flat 5% assumption): pretax_amount = amount * pretax / total.
    Callers that don't have `pretax` handy yet keep the old (unexempted)
    behavior for taxExempt items rather than guessing — better to under-fix
    a rarely-hit call site than divide by an unknown ratio.

    apply_tax_exempt=False（2026-09-02 新增）：回傳「原始開立金額」，不套用
    上述沖銷折算。這行為上是刻意分岔的兩個問題——「客戶現在還欠多少錢」
    （AR/收款/dashboard 要的答案，taxExempt 後金額變小）跟「這筆款項當初
    實際開立的統一發票金額是多少」（稅務匯出/T100 傳票要的答案，taxExempt
    是核准沖銷之後才發生的內部應收帳款減讓，不會、也不能追溯改變已經對
    國稅局申報過的銷項稅額）完全是两回事，把稅額沖銷後的「應收金額」直接
    當成「已開立發票金額=0 稅額」拿去做稅務申報用途，會讓已開立、已產生
    法定稅捐義務的發票在申報文件上憑空消失（見 routers/reports.py::
    _collect_tax_invoices() 呼叫點的說明）。"""
    if not pay_items:
        return []
    others = sum(
        p["amount"] if p.get("amount") is not None else round_half_up(total * (p.get("pct") or 0) / 100)
        for p in pay_items[1:]
    )
    out = []
    for idx, pi in enumerate(pay_items):
        if pi.get("amount") is not None:
            amt = pi["amount"]
        elif idx == 0:
            amt = int(total - others)
        else:
            amt = round_half_up(total * (pi.get("pct") or 0) / 100)
        if apply_tax_exempt and pi.get("taxExempt") and pretax and total:
            amt = round_half_up(amt * pretax / total)
        out.append(amt)
    return out


def summarize_payment_items(total: float, pay_items: list, pretax: float = None) -> dict:
    """單一案件的應收／已收／未收彙總＋逐筆明細（2026-09-09 新增，供案件財務
    「應收應付」總覽用）。

    金額一律透過既有的 payment_item_amounts() 取得（含 taxExempt 沖銷折算），
    **不要在呼叫端自己重寫 pct 反推公式**——「這個案件還有多少錢沒收」原本在
    三個地方各自算過一次：case-management.js 的 receivedTotal()/feeTotal()/
    netReceivedTotal()/outstandingTotal() 這組 getter、reports.py::_collect()、
    以及案件財務總覽，這支函式是為了避免第三份實作而抽出來的。各欄位語意刻意
    跟前端那組 getter 逐一對應（見下方註解），兩邊數字才會一致——財務 Tab 的
    總覽跟「案件資訊」Tab 的款項明細顯示的是同一批款項，對不起來使用者會第一
    眼就發現。

    回傳 items[] 的欄位形狀比照 reports.py::_collect() 的收款明細（amount／
    received／actualAmount／feeAmount／netAmount 同語意），日後若要把這裡的
    結果餵進報表類的彙總，不需要再做一次欄位轉換。
    """
    amounts = payment_item_amounts(total, pay_items, pretax)
    receivable = collected = fee_total = net_collected = outstanding = 0
    items = []
    for idx, pi in enumerate(pay_items or []):
        amt  = amounts[idx]
        rcvd = bool(pi.get("received"))
        aa   = pi.get("actualAmount")
        fee  = pi.get("feeAmount") or 0
        # 已收款項的「實際入帳淨額」：有填實收金額就用實收（匯差/短收），
        # 沒填就用應收金額，再扣掉手續費——對應前端 netReceivedTotal()。
        net  = ((aa if aa is not None else amt) - fee) if rcvd else None
        receivable += amt
        if rcvd:
            collected     += amt          # 對應前端 receivedTotal()（用應收金額，非實收）
            fee_total     += fee          # 對應前端 feeTotal()
            net_collected += net          # 對應前端 netReceivedTotal()
        else:
            outstanding   += amt          # 對應前端 outstandingTotal()
        items.append({
            "idx":          idx,
            "type":         pi.get("type", f"第{idx + 1}期"),
            "pct":          pi.get("pct") or 0,
            "amount":       amt,
            "received":     rcvd,
            "receivedAt":   (pi.get("receivedAt") or "")[:10],
            "receivedBy":   pi.get("receivedBy", ""),
            "expectedReceiptDate": pi.get("expectedReceiptDate", ""),
            "actualAmount": aa,
            "feeAmount":    fee,
            "netAmount":    net,
            "invoiceNo":    pi.get("invoiceNo", ""),
            "invoiceDate":  pi.get("invoiceDate", ""),
            "feeNote":      pi.get("feeNote", ""),
            "note":         pi.get("note", ""),
            "taxExempt":    bool(pi.get("taxExempt")),
        })
    return {
        "receivableTotal":  receivable,
        "collectedTotal":   collected,
        "feeTotal":         fee_total,
        "netCollected":     net_collected,
        # max(0, ...)：比照前端 outstandingTotal()，避免舊資料金額為負時顯示負的未收
        "outstandingTotal": max(0, outstanding),
        "items":            items,
    }


def case_extra_expenses(conn, quote_no: str) -> list:
    """把一張案件的額外支出攤成月度支出彙總用的逐筆資料（讀 `case_extra_expenses` 表）。

    2026-09-11 從 `settlement_extra_expenses(data)` 改名並改讀新表（migration v75
    把資料從 `settlement.extraItems` 搬出來了）。**改名是刻意的**：若沿用舊名只改
    實作，任何漏改的呼叫端會安靜地拿到空陣列，報表數字直接歸零卻不會報錯。

    以下是從舊版保留下來、仍然成立的規則——

    2026-09-09 修：`dashboard.py::dashboard_monthly()` 與 `reports.py::_collect_expenses()`
    原本只撈 `settlement.status='finalized'` 的案件，代表**精算還在草稿階段的額外支出
    完全不會出現在任何月度支出數字裡**。但實際作業順序是「支出當下就先填，案件整個
    結束後才做精算完結」，中間可能隔好幾個月——這段期間當月已經花掉的錢在報表與首頁
    上等於憑空消失。改成**只要填了就算**。

    歸月日期依序取：
      1. `expense_date`（憑證日期，最準）
      2. `created_at`（填寫日期）
    兩者都沒有就跳過——真的無從判斷是哪個月，硬塞會污染月報。
    （舊版還會退回精算完結／最後存檔時間，新表每一筆一定有 created_at，不需要那兩層。）

    **`pending` 的定義 2026-09-11 改了**：舊版是「精算尚未完結」，現在是
    **「送審尚未核准」**（status 不是「已核准」）。使用者指定的規則是
    **送審中的項目照樣算進成本，但畫面要提醒還沒簽完**——所以這裡照樣回傳金額，
    由呼叫端決定怎麼標示。不要因為 pending 就把它濾掉，那會讓當月數字又對不上，
    正是 2026-09-09 修過的那個問題。
    """
    rows = conn.execute(
        "SELECT category, description, total_cost, expense_date, created_at, doc_no, "
        "       files_json, status "
        "FROM case_extra_expenses WHERE quote_no=? ORDER BY id", (quote_no,)
    ).fetchall()

    out = []
    for r in rows:
        cost = float(r["total_cost"] or 0)
        if not cost:
            continue
        item_date = (r["expense_date"] or r["created_at"] or "").strip()
        if not item_date:
            continue
        try:
            files = json.loads(r["files_json"] or "[]")
        except Exception:
            files = []
        out.append({
            "date":     item_date[:10],
            "month":    item_date[:7],
            "cost":     cost,
            "category": r["category"] or "其他",
            "desc":     r["description"] or "",
            "docNo":    r["doc_no"] or "",
            "files":    files,
            "status":   r["status"],
            "pending":  r["status"] != "已核准",
        })
    return out


_INVOICE_NO_RE = re.compile(r"^[A-Z]{2}\d{8}$")


def validate_invoice_no(conn, invoice_no: str, exclude_quote_no: str = None,
                         exclude_idx: int = None, exclude_item_id=None) -> None:
    """統一發票號碼格式檢查（2 碼英文字軌＋8 碼流水號，如 AB12345678）＋重複
    偵測（同一組號碼已經填在別的案件/期別上）——2026-09-02 稽核發現這個欄位
    過去完全是自由文字，格式錯誤或複製貼上打錯號碼、甚至真的重複開立，系統
    都不會有任何提示，而重複發票號碼正是國稅局查核時最先抓的稽核紅旗。
    空字串（尚未開立）視為合法，直接放行。

    排除「自己這筆」有兩種呼叫情境：mark_payment()（PATCH .../payment/{idx}，
    出納快速登錄用）逐筆改動、當下的陣列位置就是穩定的，用 exclude_idx 即可；
    update_case_record()（PATCH .../case-record，案件管理財務Tab 整包存檔，
    是使用者實際填發票號碼最常用的路徑）品項可能同時被新增/刪除/重新排序，
    陣列位置不可靠，要用品項自己的 id（case-management.js 建立品項時固定會
    帶，見該檔 addPaymentItem() 附近註解）比對，改傳 exclude_item_id。兩者
    只會用其中一種，exclude_item_id 有值時優先信任它。"""
    inv = (invoice_no or "").strip()
    if not inv:
        return
    if not _INVOICE_NO_RE.match(inv.upper()):
        raise HTTPException(
            400, f"發票號碼格式錯誤（{invoice_no}），需為 2 碼英文字軌＋8 碼數字，例如 AB12345678"
        )
    rows = conn.execute(
        "SELECT quote_no, json_extract(data_json,'$.caseRecord.payment.items') AS pay_json "
        "FROM quotations WHERE json_extract(data_json,'$.caseRecord.payment.items') IS NOT NULL"
    ).fetchall()
    for r in rows:
        try:
            items = json.loads(r["pay_json"] or "[]")
        except Exception:
            continue
        for i, it in enumerate(items):
            if (it.get("invoiceNo") or "").strip().upper() != inv.upper():
                continue
            if r["quote_no"] == exclude_quote_no:
                if exclude_item_id is not None and it.get("id") == exclude_item_id:
                    continue
                if exclude_item_id is None and exclude_idx is not None and i == exclude_idx:
                    continue
            raise HTTPException(
                400, f"發票號碼 {invoice_no} 已用於案件 {r['quote_no']} 第{i + 1}期款項，請確認是否重複或填錯"
            )


def quote_won_month_map(conn) -> dict:
    """回傳 {quote_no: 'YYYY-MM'}，該報價單應歸入成案趨勢報表的月份
    （2026-08-24 建立，2026-08-25 修正優先順序）。

    優先用 quote_date（報價單自己的日期欄位）。2026-08-24 那版原本反過來優先
    用 audit_log 裡 action='deal_tag.change'、detail.to='已成案' 的事件時間戳，
    理由是它「每次成案動作當下就寫入、不會被後續編輯覆蓋」；但實測上線後發現
    大量舊案件是系統上線後才補登（quote_date 填的是案件本身真正的日期，例如
    2026-01/02，但補登這個動作、也就是 deal_tag 第一次被設成已成案的那個
    audit 事件，發生在補登當下的 2026-07/08），導致這些舊案件全部被錯誤歸到
    補登月份，「近 12 月成案趨勢」變成看起來業績集中爆量在系統剛上線的
    七、八月——這正是本函式原本要避免的同一種失真，只是換了個方向發生。

    因此改成：quote_date 只要不是「未來日期」（不晚於今天）就直接採用；只有
    quote_date 缺漏，或明顯異常（業務員手誤填成未來月份，例如曾實測發現一筆
    達 NT$284 萬的合約 quote_date 誤填在未來月份，導致整筆從報表的近 N 月
    範圍消失）時，才 fallback 回 audit_log 的成案時間戳。"""
    won_events: dict = {}
    for r in conn.execute(
        "SELECT at, target_id, detail FROM audit_log WHERE action='deal_tag.change' ORDER BY at ASC"
    ).fetchall():
        try:
            detail = json.loads(r["detail"] or "{}")
        except Exception:
            continue
        if detail.get("to") == "已成案":
            won_events[r["target_id"]] = r["at"]

    today_str = date.today().isoformat()
    result = {}
    for r in conn.execute(
        f"SELECT quote_no, quote_date FROM quotations WHERE {SQL_DEAL_TAG} IN ('已成案','已結案')"
    ).fetchall():
        qdate = r["quote_date"] or ""
        if qdate and qdate <= today_str:
            chosen = qdate
        else:
            chosen = won_events.get(r["quote_no"]) or qdate
        if chosen:
            result[r["quote_no"]] = chosen[:7]
    return result


def quote_hot_fields(q: dict) -> tuple:
    """Return (deal_tag, settle_status) from a quotation data dict."""
    if not isinstance(q, dict):
        return "", ""
    deal_tag = q.get("dealTag") or ""
    settle = q.get("settlement")
    settle_status = settle.get("status") or "" if isinstance(settle, dict) else ""
    return deal_tag, settle_status


_log = logging.getLogger(__name__)

# 寫鎖本體在 L1 core.txn（2026-09-25 下沉）；這裡只登記案件自己要觀測的讀取：
# 拿鎖之後讀過 quotations.data_json ⇒ 之後的整包寫回是以鎖內最新資料為底。
_QUOTE_READ = "quotations.data_json"
_txn.watch_reads(_QUOTE_READ, lambda sql: "data_json" in sql and "quotations" in sql
                 and sql.lstrip()[:6].upper() == "SELECT")


def _check_read_under_write_lock(conn, quote_no):
    """save_quotation_json 的結構守門（2026-09-25 lost update 稽核後開啟）。

    放行條件：這條連線的寫交易是 core.txn.begin_write 開的，而且**拿鎖之後**讀過 quotations.data_json。
    ⚠️ 仍有的盲點：不比對讀的是不是**同一張**單、也不比對讀的是不是**這一次**要寫回的那份資料。
    違規：預設記 ERROR（含呼叫堆疊）並照寫；設了 MOTRIX_STRICT_DB_GUARDS=1（測試環境）才 raise。"""
    if _txn.read_under_lock(conn, _QUOTE_READ):
        return
    in_lock, st = _txn.lock_state(conn)
    why = ("不在寫交易內" if not conn.in_transaction else
           "寫交易不是 begin_write 開的" if st is None else "拿鎖之後沒有讀過 data_json")
    msg = f"save_quotation_json({quote_no!r})：{why}——讀 data_json 之前要先 begin_write／write_txn（lost update）"
    if _txn.strict_db_guards():
        raise RuntimeError(msg)
    _log.error("%s" + chr(10) + "%s", msg, "".join(traceback.format_stack(limit=8)))


def save_quotation_json(
    conn,
    quote_no: str,
    data: dict,
    status: str = None,
    updated_at: str = None,
) -> str:
    """Persist data_json and keep deal_tag / settle_status columns in sync.

    Optionally updates status. Returns the updated_at timestamp used.
    """
    _check_read_under_write_lock(conn, quote_no)
    now = updated_at or datetime.now().isoformat()
    deal_tag, settle_status = quote_hot_fields(data)
    if status is not None:
        conn.execute(
            "UPDATE quotations "
            "SET data_json=?, updated_at=?, deal_tag=?, settle_status=?, status=? "
            "WHERE quote_no=?",
            (json.dumps(data, ensure_ascii=False), now, deal_tag, settle_status, status, quote_no),
        )
    else:
        conn.execute(
            "UPDATE quotations "
            "SET data_json=?, updated_at=?, deal_tag=?, settle_status=? "
            "WHERE quote_no=?",
            (json.dumps(data, ensure_ascii=False), now, deal_tag, settle_status, quote_no),
        )
    return now


# ── 串接點 IP-12 `case.access`（INTEGRATION-POINTS；2026-09-26 M10 搬遷前置）──────────
# 別組（目前是 M10 網路規劃書）要「確認這個人能不能看這個案件」「讀案件的客戶／專案名稱」時走這裡，
# 不 import 本檔、也不直接讀 quotations。M01 不在 ⇒ 沒有提供者，使用方明說「案件模組未安裝」。
class _CaseAccess:
    @staticmethod
    def guard(conn, quote_no, user, allow_module=None):
        """同 guard_case_access：不存在 404、無權限 403（擋下時會關連線）；通過回單列。"""
        return guard_case_access(conn, quote_no, user, allow_module=allow_module)

    @staticmethod
    def summary(conn, quote_no):
        """{customer, project}；案件不存在 ⇒ None。"""
        row = conn.execute("SELECT customer_name, project_name FROM quotations WHERE quote_no=?",
                           (quote_no,)).fetchone()
        if row is None:
            return None
        return {"customer": row["customer_name"] or "", "project": row["project_name"] or ""}


from core import registry as _registry  # noqa: E402
_registry.provide("case.access", "case", _CaseAccess)
