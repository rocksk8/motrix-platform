"""A2-0 底層預留 #7：`helpers.doc_render.render_document`（版型＋單據視圖 ⇒ HTML；核可狀態由程式決定）。
① 已核可：沒有未核可標示；單號／欄位值進內文
② `unapproved`：紅色橫幅＋每頁標示（版型沒放 banner 積木也一樣），冪等
③ 自訂模組的 `render_view` 與 `render_document` 同一份輸出（委派，不是第二份實作）
④ 未知主題 ⇒ TemplateError（不是靜默空白）
反向控制：把 `unapproved` 分支拿掉 ⇒ ② 必須紅。"""
import pytest

from helpers import doc_template as dt
from helpers.doc_render import render_document

TPL = {"key": "t", "version": 1, "theme": "voucher_standard", "title": {"path": "recordNo", "suffix": " 測試單"},
       "blocks": [{"type": "identity_header", "title": "測試單"},
                  {"type": "meta", "fields": [{"label": "單號", "path": "recordNo"}, {"label": "事由", "path": "fields.reason"}]},
                  {"type": "approval_sign"}, {"type": "identity_footer"}]}


def _view(**kw):
    v = {"recordNo": "PR-20261001-0001", "statusLabel": "簽核中", "status": "pending", "fields": {"reason": "買線材"}, "approval": {}}
    v.update(kw)
    return v


def test_approved_document_has_no_unapproved_marks():
    html = render_document(TPL, _view(unapproved=False))
    assert "PR-20261001-0001" in html and "買線材" in html
    assert 'data-unapproved' not in html and "data-unapproved-wm" not in html


def test_unapproved_document_gets_banner_and_every_page_mark_even_without_banner_block():
    assert not any(b["type"] == "unapproved_banner" for b in TPL["blocks"])
    html = render_document(TPL, _view(unapproved=True))
    assert 'data-unapproved="1"' in html and 'data-unapproved-wm="1"' in html and "簽核中" in html
    assert dt.inject_unapproved(html, "x", "y") == html                       # 冪等


def test_custom_modules_render_view_delegates_to_render_document():
    from helpers import custom_modules as CM
    body = {"name": "測試單", "fields": [{"key": "reason", "label": "事由", "type": "text"}], "output": {"template": TPL}}
    v = _view(unapproved=True)
    assert CM.render_view(body, v) == render_document(TPL, v)


def test_unknown_theme_is_an_error():
    with pytest.raises(dt.TemplateError):
        render_document(dict(TPL, theme="nope"), _view())
