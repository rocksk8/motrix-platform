# -*- coding: utf-8 -*-
"""W3 #2：輸出版型的儲存型 XSS。版型（超級管理員可存）裡的 class／width／count／colspan 會落進 HTML 屬性或決定輸出量，
`_esc` 沒跳脫引號＝可跳出屬性塞事件處理。修法：`_esc` 跳脫 `"`／`'`；屬性值走白名單（`_css_class`／`_css_width`／`_int_in`）；
儲存驗證（`problems`）與渲染用同一組檢查，壞值存不進去、也渲染不出去。
"""
import pytest

from helpers import doc_template as dt

PAYLOADS = ['x" onmouseover="alert(1)', "x' onfocus='alert(1)", 'x"><script>alert(1)</script>', "a b\nc", "", "x;y"]


def _kv(cls=None, row_cls=None, cell_cls=None, colspan=None):
    cell = {"text": "v"}
    if cell_cls is not None:
        cell["class"] = cell_cls
    if colspan is not None:
        cell["colspan"] = colspan
    row = {"cells": [cell]}
    if row_cls is not None:
        row["class"] = row_cls
    b = {"type": "kv_table", "rows": [row]}
    if cls is not None:
        b["class"] = cls
    return b


def _tpl(block):
    return {"theme": "voucher_standard", "blocks": [block]}


def test_esc_escapes_quotes():
    assert dt._esc('a"b\'c') == "a&quot;b&#x27;c"
    assert dt._esc("<&>") == "&lt;&amp;&gt;"          # 既有行為不變


@pytest.mark.parametrize("bad", [p for p in PAYLOADS if p])
@pytest.mark.parametrize("where", ["table", "row", "cell"])
def test_bad_class_is_rejected_at_render_and_at_save(bad, where):
    kw = {"table": {"cls": bad}, "row": {"row_cls": bad}, "cell": {"cell_cls": bad}}[where]
    b = _kv(**kw)
    with pytest.raises(dt.TemplateError):
        dt.render_blocks([b], {}, {})
    probs = dt.problems(_tpl(b))
    assert any("class" in p["message"] for p in probs), probs


def test_good_class_passes():
    b = _kv(cls="tbl a-1", row_cls="r_1", cell_cls="c-x")
    html = dt.render_blocks([b], {}, {})
    assert 'class="tbl a-1"' in html and 'class="r_1"' in html and 'class="c-x"' in html
    assert dt.problems(_tpl(b)) == []


@pytest.mark.parametrize("bad", ['12%" onmouseover="alert(1)', "expression(alert(1))", "12%;background:url(x)", "", "-5px", "1e9"])
def test_bad_width_is_rejected(bad):
    b = {"type": "items_table", "label": "L", "source": "items", "columns": [{"title": "t", "path": "p", "width": bad}]}
    if bad == "":
        return                                          # 空字串＝沒設寬度（略過）
    with pytest.raises(dt.TemplateError):
        dt.render_blocks([b], {"items": []}, {})
    assert any("width" in p["message"] for p in dt.problems(_tpl(b)))


@pytest.mark.parametrize("ok", ["12%", "80px", "30mm", "10.5%", "8em"])
def test_good_width_passes(ok):
    b = {"type": "items_table", "label": "L", "source": "items", "columns": [{"title": "t", "path": "p", "width": ok}]}
    assert ('style="width:%s"' % ok) in dt.render_blocks([b], {"items": []}, {})


@pytest.mark.parametrize("bad", [0, -1, 61, 10 ** 9, "x", True, None])
def test_watermark_count_is_bounded(bad):
    b = {"type": "watermark", "text": "T", "small": "s", "count": bad}
    with pytest.raises(dt.TemplateError):
        dt.render_blocks([b], {}, {})
    assert any("count" in p["message"] for p in dt.problems(_tpl(b)))


@pytest.mark.parametrize("bad", [0, 21, "2\" onclick=\"x", 10 ** 9])
def test_colspan_is_bounded(bad):
    with pytest.raises(dt.TemplateError):
        dt.render_blocks([_kv(colspan=bad)], {}, {})
    assert any("colspan" in p["message"] for p in dt.problems(_tpl(_kv(colspan=bad))))


def test_data_and_label_payloads_never_break_out_of_text_or_attributes():
    """欄位值與版型文字（title／label）帶 `"`／`'`／`<script>`：只會以實體出現，不會長出標籤或屬性。"""
    evil = '"><img src=x onerror=alert(1)>\'"'
    blocks = [{"type": "boxes", "boxes": [{"title": evil, "rows": [{"label": evil, "path": "v"}]}]},
              {"type": "section_title", "text": evil}, {"type": "footer_text", "text": "{v}"}]
    html = dt.render_blocks(blocks, {"v": evil}, {})
    assert "<img" not in html
    assert html.count("&quot;") >= 3 and "&lt;img" in html
