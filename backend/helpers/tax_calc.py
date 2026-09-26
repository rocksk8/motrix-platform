"""稅額純函式（L1；2026-09-26 自 M01 `helpers/quotations.py` 下沉，主持核准「T」）。

為什麼在 L1：報價稅別、5% 拆稅、收款項金額是**純計算**（輸入是報價單 JSON，不讀表），而使用者遍布
L1（pdf_gen）、M05（出納、開票申請）、M08（報表、儀表板）與 receivables。放在 M01 時，這些使用者
全都是對 M01 的跨組相依，M01 拿掉時 L1 也會把 `helpers.quotations` 載入（CA-O4 的一半）。

契約（守門 tests/platform/test_tax_calc_contract.py）：
- 不讀表、不 import `db`（沒有 SQL，沒有 `.execute`）
- 不 import M01（helpers.quotations／recognition／quote_terms／case_*、routers.*）
- `helpers.quotations` 的同名名稱是這裡的同一個物件（別名）

函式本體與原本逐字相同（唯一例外：tax_split 的錯誤訊息 % 跳脫，見該處）；金額捨入唯一來源仍是 `helpers.legal_params.round_half_up`（X-VAT）。
"""
#: L1 公開介面的底線名稱（b-g1 的 G1 顯式宣告）：`_invoice_amount` 被 M01 `helpers/quotations.validate_invoice_amounts` 使用
__l1_public__ = ("_invoice_amount",)

from fastapi import HTTPException

from helpers.legal_params import round_half_up

__all__ = ["TAX_TYPES", "TAX_TYPE_LABELS", "LEGAL_TAX_RATE", "LEGACY_TAX_NOTE",
           "quote_tax_type", "tax_split", "invoice_amounts", "payment_item_amounts"]

#: 報價稅別。`legacy` 不是可選的稅別，是「已停用的 1～4%」舊單的讀取結果。
TAX_TYPES = ("taxable", "zero", "exempt")
TAX_TYPE_LABELS = {"taxable": "應稅 5%", "zero": "零稅率", "exempt": "免稅"}
LEGAL_TAX_RATE = 0.05
LEGACY_TAX_NOTE = "非法定稅率，請會計確認"


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


def tax_split(sales, tax_type: str) -> tuple:
    """(銷售額, 稅額)。應稅 ⇒ 稅額＝round_half_up(銷售額 × 5%)；零稅率／免稅 ⇒ 0。

    ⚠️ `legacy` 不在這裡處理：舊 1～4% 單不改數字，由呼叫端沿用原本的算法並標示。
    """
    sales = round_half_up(sales)
    if tax_type == "taxable":
        return sales, round_half_up(sales, LEGAL_TAX_RATE)
    if tax_type in ("zero", "exempt"):
        return sales, 0
    # 〔修正（T，2026-09-26）：原句「1～4% 單」的 % 沒跳脫 ⇒ 丟 TypeError 而不是這個 ValueError；呼叫端都先排除 legacy，行為面無影響〕
    raise ValueError("tax_split 不處理稅別 %r（舊 1～4%% 單由呼叫端沿用原算法）" % tax_type)


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


# 2026-09-26 自 M01 `helpers/quotations.py` 逐字下沉（CA-O4；純函式，M08 報表用）；M01 保留同名別名
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
