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

import logging
import math

from fastapi import HTTPException

from helpers.legal_params import round_half_up

__all__ = ["TAX_TYPES", "TAX_TYPE_LABELS", "LEGAL_TAX_RATE", "LEGACY_TAX_NOTE",
           "quote_tax_type", "tax_split", "invoice_amounts", "payment_item_amounts",
           "MONEY_BAD", "parse_money", "money", "amount_unknown"]

_log = logging.getLogger(__name__)

#: `parse_money` 的「填了但不是有限數字」標記（例如 "5x00"、NaN、inf、True）。
MONEY_BAD = object()


def parse_money(v):
    """款項欄位的防禦性轉換（T87 修：款項金額是字串 "5x00" 時整張報表 TypeError 500）。
    ⇒ 數字（int／float；數字字串 "5000"、"1,250.5" 轉成數字）、`None`（沒填／空白）、或 `MONEY_BAD`（填了但不是有限數字）。
    乾淨的數字原樣回傳同一個物件（既有計算結果不變）。"""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, bool):
        return MONEY_BAD
    if isinstance(v, (int, float)):
        return v if math.isfinite(v) else MONEY_BAD
    if isinstance(v, str):
        try:
            f = float(v.strip().replace(",", ""))
        except ValueError:
            return MONEY_BAD
        if not math.isfinite(f):
            return MONEY_BAD
        return int(f) if f.is_integer() else f
    return MONEY_BAD


def amount_unknown(pi) -> bool:
    """這筆款項的應收金額算不出來？＝不是物件；或金額填了但不是數字；或沒填金額、又用比例反推而比例壞掉。
    （金額有效時，比例／手續費壞掉不影響金額；`payment_item_amounts` 與報表的略過規則共用這個判斷。）"""
    if not isinstance(pi, dict):
        return True
    a = parse_money(pi.get("amount")) if "amount" in pi else None
    if a is MONEY_BAD:
        return True
    return a is None and "pct" in pi and parse_money(pi.get("pct")) is MONEY_BAD


def money(v, default=0):
    """`parse_money` 的簡化版：沒填或壞掉 ⇒ `default`（預設 0）。給「讀手續費這類欄位再相加」的地方用。"""
    n = parse_money(v)
    return default if n is None or n is MONEY_BAD else n

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


_YMD_RE = None


def norm_ymd(v) -> str:
    """把款項日期正規化成 YYYY-MM-DD（2026-09-29）。

    收款日期原本一律以字串前綴（[:7]／[:10]）與 `YYYY-MM` 比對歸月，「2026/09/01」「2026.9.1」
    「115/09/01（民國）」這類寫法會被靜默排除在該月之外（'/' 排序在 '-' 之後，區間比對也落在範圍外）。
    ⇒ 讀取端一律先過這支；儲存端也存標準格式。
    ⚠️ 讀不懂的（非空）原樣截 10 碼回傳——不假造日期；由收款資料異常清單抓出來。
    """
    global _YMD_RE
    import re
    from datetime import datetime as _dt
    if _YMD_RE is None:
        _YMD_RE = re.compile(r"^\s*(\d{3,4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})")
    s = str(v or "")
    m = _YMD_RE.match(s)
    if not m:
        return s[:10]
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if len(m.group(1)) == 3:      # 民國年
        y += 1911
    try:
        return _dt(y, mo, d).strftime("%Y-%m-%d")
    except ValueError:
        return s[:10]


def receipt_amounts(receivable: float, actual, fee) -> tuple:
    """一筆已收款項的三個金額 ⇒ `(bank, gross, fee)`（2026-09-30 使用者裁示，正式機案件 MQ-202607-045 第 2 期交貨款）。

    語意（單一來源；報表、案件財務彙總、案件結算單、T100 收款傳票都用這一支，不各寫一份）：
    - `bank`（銀行實際入帳）＝`actualAmount`（實收金額，**已扣客戶內扣手續費**）；沒填 ⇒ 應收 − 手續費（舊行為）。
    - `gross`（收入，含稅）＝`bank + fee`：客戶該付的金額，手續費是公司的費用、另列支出，**不從收入扣**。
    - 淨額＝`bank`：**不再減手續費**（實收已經是扣過的；再減一次＝手續費扣兩次）。
    損益＝`gross − fee(列費用) − 其他支出`＝`bank − 其他支出`，與銀行帳一致。
    歷史資料不改，只改計算。
    """
    fee = float(money(fee))                                   # 壞掉／沒填 ⇒ 0（T87 修：髒資料不丟例外）
    actual = parse_money(actual)
    bank = float(actual) if actual is not None and actual is not MONEY_BAD else float(money(receivable)) - fee
    return bank, bank + fee, fee


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
    # 髒資料防線（T87 修）：金額／比例不是數字 ⇒ 該筆當 0 算並記 warning，不丟例外（呼叫端各自有報表，不能因一筆壞資料整張 500）。
    # 乾淨資料不複製、不改值，結果與過去逐位相同。
    total, pretax, pay_items = _sanitize_for_amounts(total, pretax, pay_items)
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


def _sanitize_for_amounts(total, pretax, pay_items):
    """⇒ `(total, pretax, pay_items)`；髒欄位換成 0／None（只複製有改的那幾筆）。"""
    bad = 0
    t = parse_money(total)
    if t is MONEY_BAD:
        t, bad = 0, bad + 1
    pt = parse_money(pretax)
    if pt is MONEY_BAD:
        pt, bad = None, bad + 1
    fixed_items, changed = [], False
    for pi in pay_items:
        if not isinstance(pi, dict):
            fixed_items.append({"amount": 0})
            bad, changed = bad + 1, True
            continue
        patch = {}
        for k in ("amount", "pct"):
            if k in pi:
                n = parse_money(pi[k])
                if n is MONEY_BAD:
                    n, bad = 0, bad + 1
                if n is not pi[k]:
                    patch[k] = n
        if patch:
            fixed_items.append({**pi, **patch})
            changed = True
        else:
            fixed_items.append(pi)
    # 第 1 筆沒填金額＝「總額扣掉其他筆」的餘數；後面有任何一筆金額算不出來，餘數就不可信（壞的那筆會被併進第 1 筆，帳會偏大）
    # ⇒ 第 1 筆也算不出來，當 0（與報表的「略過並計數」同一條規則：算不出來 ⇒ 0＋warning）。
    if len(fixed_items) > 1 and isinstance(fixed_items[0], dict) and parse_money(fixed_items[0].get("amount")) is None             and any(amount_unknown(pi) for pi in pay_items[1:]):
        fixed_items[0] = {**fixed_items[0], "amount": 0}
        bad, changed = bad + 1, True
    if bad:
        _log.warning("款項金額／比例格式異常 %d 處，已當 0 處理（報表仍可產出，請修正原始資料）", bad)
    if t is None:
        t = 0
    if not changed and not bad and t is total:
        return total, pretax, pay_items
    return t, pt, (fixed_items if changed else pay_items)


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
        aa   = parse_money(pi.get("actualAmount"))
        aa   = None if aa is MONEY_BAD else aa
        fee  = money(pi.get("feeAmount"))
        # 已收款項的「實際入帳淨額」＝銀行入帳（receipt_amounts；實收已扣客戶內扣手續費，不再減一次；
        # 沒填實收 ⇒ 應收 − 手續費）——對應前端 netReceivedTotal()。
        net  = receipt_amounts(amt, aa, fee)[0] if rcvd else None
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
            "receivedAt":   norm_ymd(pi.get("receivedAt")),
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
