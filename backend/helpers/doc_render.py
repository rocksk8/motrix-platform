# -*- coding: utf-8 -*-
"""L1 單據輸出的公開入口 `render_document`（A2-0 #7）：版型＋單據視圖 ⇒ 完整 HTML（交給 `html_to_pdf_bytes` 轉 PDF）。

[單位] helper:doc_render    [層] L1    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] render_document
[契約題] tests/platform/test_doc_render_2026_10_01.py
[不變式] 核可狀態由程式決定、不由版型決定：`view["unapproved"]` 為真 ⇒ 一律補紅色橫幅＋每頁標示（冪等）；
    抬頭／頁尾用公司身分（總公司據點）；簽核欄用與財務單據相同的共用元件

單據視圖（`view`）的約定鍵：`recordNo`（單號）、`statusLabel`／`status`、`unapproved`（bool）、`approval`（簽核 JSON）、
`fields`（版型以 `fields.<key>` 引用）；其餘鍵照版型引用。自訂模組（`custom_modules.render_view`）與 A2 費用單據共用這一支。
"""


def render_document(template: dict, view: dict) -> str:
    """版型定義＋單據視圖 ⇒ HTML。版型驗證失敗（未知主題等）⇒ `doc_template.TemplateError`。"""
    from helpers import doc_template as dt
    import pdf_gen
    ident = pdf_gen.apply_snapshot(pdf_gen.location_identity(pdf_gen._location_of({})), {})
    parts = {"identity_head": lambda: pdf_gen._identity_head(ident),
             "identity_foot": lambda: pdf_gen._identity_foot(ident),
             "approval_sign": lambda: pdf_gen._voucher_sign_html(view.get("approval") or {})}
    html = dt.render(template, view, parts)
    if not view.get("unapproved"):
        return html
    return dt.inject_unapproved(html, view.get("statusLabel") or view.get("status"), "此單據尚未核可",
                                doc_no=str(view.get("recordNo") or ""))
