# -*- coding: utf-8 -*-
"""報價單條款標題（census #5 / S-Q2）：報價單五個條款區塊的標題，管理者只能從預設清單挑（付款條件→付款方式…）。

[單位] helper:clause_titles    [層] L1    [穩定度] 實作
[公開介面] CLAUSE_KEYS, CLAUSE_PRESETS, EXPORT_ID, active_titles, freeze, title, titles_for
[不變式] 匯出範本 `case:quotation-clause-titles`（kind export_template；`builder_exports.enabled` 且 `builder_governance.enabled` 才生效）。
    旗標關／沒有已發布範本 ⇒ 標題＝程式裡原本寫死的字（`CLAUSE_PRESETS` 每組的第一個），PDF／表單／送審原因文字逐位元相同。
    **送審時凍結**：報價單送審（`quotations._apply_server_submit_reasons`）當下，若範本生效就把五個標題存進 `data_json.clauseTitles`；
    之後這張單據的 PDF／表單一律用凍結的標題（客戶看到的文字不因事後改範本而變）；草稿用目前的範本。凍結值再驗證一次（不在預設清單裡 ⇒ 忽略）。
    只改標題，不改條款本文、不改順序；欄位鍵（paymentTerms…）不變。任何標題的變更都是放寬（客戶可見文字），走治理核准。
[契約題] tests/platform/test_clause_titles_t62.py
"""
from helpers import export_templates as ET

EXPORT_ID = "case:quotation-clause-titles"
#: 條款鍵 → 可選標題（第一個＝今天寫死的字＝預設）。清單由使用者／法務確認後定稿。
CLAUSE_PRESETS = {
    "paymentTerms": ("付款條件", "付款方式", "款項約定"),
    "deliveryTerms": ("交貨條件", "交付條件", "出貨條件"),
    "acceptanceTerms": ("驗收標準", "驗收條件", "驗收方式"),
    "warrantyTerms": ("保固條件", "保固說明", "保固內容"),
    "afterSales": ("售後服務及備註說明", "售後服務", "備註說明"),
}
CLAUSE_KEYS = tuple(CLAUSE_PRESETS)

ET.register_export(
    EXPORT_ID, label="報價單條款標題（PDF 與表單）", formats=("pdf",), columns=[], sample_rows=[], caps=(), titles=CLAUSE_PRESETS,
    sample_html=("<!doctype html><html><body style=\"font-family:sans-serif;padding:16mm\"><h2>五、報價條件（樣本頁）</h2>"
                 "<p>下面是五個條款區塊的標題；條款內容不受影響。</p></body></html>"))


def _defaults() -> dict:
    return {k: v[0] for k, v in CLAUSE_PRESETS.items()}


def _merged(base: dict, over: dict) -> dict:
    out = dict(base)
    out.update(over)
    return out


def _clean(raw) -> dict:
    """只收『在預設清單裡』的標題（其餘忽略）。"""
    out = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k in CLAUSE_PRESETS and v in CLAUSE_PRESETS[k]:
                out[k] = v
    return out


def active_titles(conn=None):
    """⇒ 目前生效的五個標題 `{鍵: 標題}`；旗標關／沒有已發布範本 ⇒ None。"""
    tpl = ET.resolve(EXPORT_ID, conn)
    if tpl is None:
        return None
    return _merged(_defaults(), _clean(tpl.get("titles")))


def titles_for(data=None, conn=None) -> dict:
    """某張報價單該用的五個標題：已凍結（`data.clauseTitles`）> 目前範本 > 程式預設。"""
    frozen = _clean((data or {}).get("clauseTitles")) if isinstance(data, dict) else {}
    if frozen:
        return _merged(_defaults(), frozen)
    return active_titles(conn) or _defaults()


def title(key, data=None, conn=None) -> str:
    return titles_for(data, conn)[key]


def freeze(q) -> None:
    """送審當下呼叫：範本生效 ⇒ 把標題存進 `q["clauseTitles"]`；沒生效 ⇒ 移除舊的凍結值（重新送審時以目前為準）。"""
    if not isinstance(q, dict):
        return
    t = active_titles()
    if t is None:
        q.pop("clauseTitles", None)
    else:
        q["clauseTitles"] = t
