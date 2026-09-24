"""報價單條款預設值與「特殊條件（需審核原因）」判準（2026-09-24，N13）。

## 唯一來源
`DEFAULT_TERMS` 原本只存在 `quotation-form.html` 的前端常數。N13 使用者裁示「預設條款搬到
後端當唯一來源」⇒ 搬到這裡；前端改向 `GET /api/settings/quote-terms-defaults` 取，
`routers/system.py` 的 `DEFAULT_PAYMENT_TERMS` 也改成引用這裡。

## 判準是移植，不是新訂
`compute_approval_reasons()` 逐條移植前端 `checkApproval()`（quotation-form.html），
連字串格式都照搬（JS 的 `toFixed(2)`、`toLocaleString()`、`trim()`、寬鬆比較）。
送審時由後端重算、覆蓋前端送來的 `approval.reasons`——簽核人看到的原因不能由送件人決定。

⚠️ 已知且使用者 2026-09-24 裁示接受的限制：
- 毛利率只看品項的 `margin` 欄位（使用者原話「只看毛利率欄位」）。`margin` 可以假造，
  搭配真實的低單價仍能隱瞞低毛利
- 「第 N 項」的 N 是含區段標題在內的陣列位置（照移植），與 PDF 的項次（不含標題）不同
"""
import math
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

DEFAULT_TERMS = {
    'paymentTerms': (
        '本專案總價款分三期給付，本報價不含運費與關稅，前述相關衍生費用由買方另行負擔。\n'
        '第一期：定金款（總價款50%），買方給付本期款項後，本專案即確認執行，賣方應開立憑證予買方。\n'
        '第二期：交貨款（總價款30%），設備運抵買方指定地點並完成硬體點交後，賣方得開立憑證請款，付款方式為賣方提交憑證之次月份25日支付。\n'
        '第三期：驗收款（總價款20%），設備安裝、系統設定及缺失改善完成，並經買方驗收合格後，賣方得開立憑證請款，付款方式為賣方提交憑證之次月份25日支付。'
    ),
    'deliveryTerms': (
        '送達買方指定地點；特殊地點或時段另計。'
    ),
    'acceptanceTerms': (
        '設備硬體自運抵交貨當日起即進行外觀與數量之點交；系統與安裝之最終驗收，依報價單雙方確認之規格與缺改清單辦理。\n'
        '若因非可歸責於賣方之現場因素（如買方場地未備妥、裝潢延宕、原廠及代理商物件/設備到貨延宕等），致部分項目未能即時完成設定或測試，不影響已交付設備及已完成安裝部分之驗收效力。針對不影響系統主要運作功能之輕微瑕疵、文件補正或教育訓練補充，買方不得拒絕簽認驗收單。買賣標的物之利益及危險，自交付時起，均由買受人承受負擔。\n'
        '賣方完成設備安裝與基礎設定並通知買方後，買受人應按物之性質，依通常程序從速檢查其所受領之物。如買方對完成內容有疑義，應於賣方通知之日起七日內以書面具體提出；逾期未辦理驗收或怠於為通知者，視為承認其所受領之物並驗收合格。此外，設備或系統若未經正式驗收程序，但買方已逕行投入實際業務營運或使用者，亦視同驗收完成。'
    ),
    'warrantyTerms': (
        '設備依原廠保固公告內容為主。保固期間內之硬體故障，賣方將協助買方聯繫原廠進行處理；惟若屬非設備本身硬體瑕疵（如人為損壞、天災、不當使用、買方自行變更設定、架構等）或需賣方派員至現場排解之技術服務，賣方得另行收取檢修與出勤服務費用。'
    ),
    'afterSales': (
        '上班時段電話/E-mail技術支援；到場服務依當時報價計費。'
    ),
}

TERMS_FIELD_DEFS = (
    ("paymentTerms", "付款條件"),
    ("deliveryTerms", "交貨條件"),
    ("acceptanceTerms", "驗收標準"),
    ("warrantyTerms", "保固條件"),
    ("afterSales", "售後服務"),
)

_NO_REASON = "標準報價單送出"

# JS String.prototype.trim() 去掉的字元（WhiteSpace ＋ LineTerminator）。
# Python 的 str.strip() 不去 U+FEFF，另外 JS 不去 U+001C–U+001F 而 Python 會，所以自己列。
_JS_WS = ("\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008"
          "\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff")


def _js_trim(s: str) -> str:
    return s.strip(_JS_WS)


def _js_num(v) -> float:
    """JS 的 Number() 轉型（只用在比較）：null／''／false → 0；true → 1；數字字串 → 值；其餘 NaN。"""
    if v is None or v is False:
        return 0.0
    if v is True:
        return 1.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        t = _js_trim(v)
        if t == "":
            return 0.0
        try:
            return float(t)
        except ValueError:
            return math.nan
    return math.nan


def _js_truthy(v) -> bool:
    if isinstance(v, float) and math.isnan(v):
        return False
    return bool(v)


def _js_str(v) -> str:
    """模板字串 `${v}` 的轉字串。"""
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, float):
        if math.isnan(v):
            return "NaN"
        if v.is_integer() and abs(v) < 1e21:
            return str(int(v))
        return repr(v)
    return str(v)


def _js_to_fixed(x: float, digits: int) -> str:
    """Number.prototype.toFixed：對二進位的精確值四捨五入，平手取較大（非銀行家捨入）。"""
    if math.isnan(x):
        return "NaN"
    q = Decimal(x).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    s = format(q, "f")
    return "0." + "0" * digits if s.startswith("-") and float(q) == 0 else s


def _js_locale_number(x: float) -> str:
    """toLocaleString()（zh-TW／en-US 相同）：千分位、最多 3 位小數、去尾零。"""
    q = Decimal(x).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    sign = "-" if q < 0 else ""
    q = abs(q)
    ip, _, fp = format(q, "f").partition(".")
    fp = fp.rstrip("0")
    ip = f"{int(ip):,}"
    return sign + ip + ("." + fp if fp else "")


def _preset_by_key(presets: list, key) -> Optional[dict]:
    for p in presets or []:
        if isinstance(p, dict) and p.get("key") == key:
            return p
    return None


def _terms_baseline(q: dict, presets: list, default_payment_terms: str) -> dict:
    p = _preset_by_key(presets, q.get("termsPresetKey"))
    if p:
        return p
    return {
        "paymentTerms":    default_payment_terms or DEFAULT_TERMS["paymentTerms"],
        "deliveryTerms":   DEFAULT_TERMS["deliveryTerms"],
        "acceptanceTerms": DEFAULT_TERMS["acceptanceTerms"],
        "warrantyTerms":   DEFAULT_TERMS["warrantyTerms"],
        "afterSales":      DEFAULT_TERMS["afterSales"],
    }


def _text(v) -> str:
    """`(x || '')` 之後再 `.trim()`：falsy → ''，其餘轉字串。"""
    return _js_trim(_js_str(v)) if _js_truthy(v) else ""


def compute_approval_reasons(q: dict, presets: list, default_payment_terms: str) -> list:
    """移植 quotation-form.html::checkApproval()（不含「已核准就清空」那一段——送審時不會是已核准）。"""
    reasons = []
    if _js_num(q.get("validDays")) > 30:
        reasons.append(f"有效期限 {_js_str(q.get('validDays'))} 天（超過 30 天）")
    for i, item in enumerate(q.get("items") or []):
        if not isinstance(item, dict) or item.get("type") == "header":
            continue
        if _js_num(item.get("cost")) > 0 and _js_num(item.get("margin")) < 0.30:
            reasons.append(f"第 {i + 1} 項毛利率 {_js_to_fixed(_js_num(item.get('margin')) * 100, 2)}% 低於 30%")
    if _js_truthy(q.get("showDiscount")) and _js_num(q.get("discount")) > 0:
        reasons.append(f"含折讓（NT${_js_locale_number(_js_num(q.get('discount')))}）")
    tax_rate = q["taxRate"] if "taxRate" in q else 5
    if _js_num(tax_rate) < 5:
        # AC1：零稅率／免稅是法定稅別，原因寫稅別；舊 1～4% 單維持原文字（前端同一份，parity 題守）。
        from helpers.quotations import quote_tax_type, TAX_TYPE_LABELS
        kind = quote_tax_type(q)
        if kind in ("zero", "exempt"):
            reasons.append(f"稅別為{TAX_TYPE_LABELS[kind]}（非應稅 5%）")
        else:
            reasons.append(f"調整營業稅額為 {_js_str(tax_rate)}%（標準 5%）")
    base = _terms_baseline(q, presets, default_payment_terms)
    changed = [label for key, label in TERMS_FIELD_DEFS if _text(q.get(key)) != _text(base.get(key))]
    if changed:
        p = _preset_by_key(presets, q.get("termsPresetKey"))
        reasons.append(f"報價條件已修改，與條款組「{_js_str(p.get('name'))}」不同（{'、'.join(changed)}）" if p
                       else f"報價條件已修改，非預設內容（{'、'.join(changed)}）")
    return reasons


def submit_reasons(q: dict, submitter_display: str, presets: list, default_payment_terms: str) -> list:
    """送審時寫進 approval.reasons 的完整內容（移植 confirmSubmit() 的組法）：
    沒有特殊條件 ⇒「標準報價單送出」；代理送出那一行放最前面。
    代理與否沿用前端帶的 `delegateSubmitter`，但**送出人的名字用伺服器的登入身分**。"""
    reasons = compute_approval_reasons(q, presets, default_payment_terms) or [_NO_REASON]
    appr = q.get("approval") or {}
    if appr.get("delegateSubmitter"):
        note = _js_trim(str(appr.get("delegateNote") or ""))
        reasons.insert(0, f"代理送出：由 {submitter_display} 代 {_js_str(q.get('salesPerson'))} 送出"
                          + (f"，原因：{note}" if note else ""))
    return reasons
