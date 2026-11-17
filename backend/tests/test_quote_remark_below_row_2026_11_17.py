# -*- coding: utf-8 -*-
"""報價單（含估價單）品項表：備註一律移到該品項下方整列，取消窄窄的「備註」欄（2026-11-17，使用者裁示）。

- 有備註 ⇒ 品項列下一列 <tr class="remark-row">，從「品名」欄（# 欄之後）橫跨到最右；客戶版 colspan=6、內部版（含成本／毛利率）colspan=8
- 備註欄表頭不再出現；分組標題列 colspan 與欄數一致（客戶版 6、內部版 8）
- 換行保留（<br>）、HTML 逸出
- 備註列與品項列不拆頁（break-after／break-before: avoid）；斑馬紋以品項為單位（備註列與上方品項同色）
- 整張單都沒有備註 ⇒ 輸出沒有任何新 class／CSS（與 pdf_golden 逐位元相同的前提）
"""
import re

import pdf_gen

LONG = "智慧人形／車形偵測 4路，每一路攝影機一套 AI 影像分析軟體授權；包含 Argo ONVIF 錄影授權 x16、AI 軟體授權金鑰 x1"


def _q(notes=("", LONG, "含安裝")):
    items = [{"type": "header", "description": "VMS", "id": "h1"}]
    for i, n in enumerate(notes):
        items.append({"type": "item", "id": f"i{i}", "description": f"品項{i}", "brand": f"BR-{i}", "unit": "台",
                      "qty": 1, "unitPrice": 100, "amount": 100, "cost": 60, "margin": 0.4, "notes": n})
    return {"quoteNo": "MQ-T-1", "customerName": "甲", "items": items}


def _html(q, internal=False):
    return pdf_gen._build_quote_html(q, {"subtotal": 300, "pretax": 300, "tax": 15, "total": 315}, internal=internal)


def _table(html):
    return html[html.index("<tbody>"):html.index("</tbody>")]


def test_remark_goes_below_the_item_row_full_width():
    h = _html(_q())
    assert "<th style=\"width:72px\">備註</th>" not in h
    rows = re.findall(r'<tr class="remark-row[^"]*"><td></td><td colspan="(\d+)"><div class="rbox"><b>備註</b>(.*?)</div></td></tr>', _table(h))
    assert [c for c, _ in rows] == ["6", "6"]                  # 長備註與短備註「含安裝」一律下移
    assert rows[0][1] == LONG and rows[1][1] == "含安裝"
    # 品項列之後緊接備註列
    t = _table(h)
    assert t.index("品項1") < t.index(LONG) < t.index("品項2") < t.index("含安裝")


def test_internal_version_spans_to_cost_columns():
    h = _html(_q(), internal=True)
    assert re.findall(r'<tr class="remark-row[^"]*"><td></td><td colspan="(\d+)"', _table(h)) == ["8", "8"]
    assert 'colspan="8"' in _table(h)                           # 分組標題列也是 8（共 9 欄）
    assert h.count("<th") - h.count("<thead") == 9


def test_header_colspan_matches_column_count():
    ext = _html(_q())
    assert '<td colspan="6" style="font-weight:700' in ext
    assert ext.count("<th") - ext.count("<thead") == 7


def test_newlines_kept_and_html_escaped():
    h = _html(_q(("第一行\n第二行 <b>&", "")))
    assert "第一行<br>第二行 &lt;b&gt;&amp;" in h
    assert "<b>&" not in h.replace("<b>備註</b>", "")


def test_remark_rows_do_not_split_across_pages_and_zebra_follows_item():
    h = _html(_q())
    assert "tr.has-below{page-break-after:avoid;break-after:avoid}" in h
    assert "tr.remark-row{page-break-before:avoid;break-before:avoid}" in h
    t = _table(h)
    # 列序：分組(1) 品項0(2,偶數→z) 品項1(3) 備註 品項2(4,偶數→z) 備註 ⇒ 備註列與上方品項同色
    assert '<tr class="z">' in t and '<tr class="has-below">' in t and '<tr class="z has-below">' in t
    assert '<tr class="remark-row z">' in t and '<tr class="remark-row">' in t


def test_no_remarks_means_no_new_markup():
    h = _html(_q(("", "", "")))
    for tok in ("remark-row", "rbox", "has-below", 'class="z"'):
        assert tok not in h
    assert "tbody tr:nth-child(even) td{background:#FAFAF8}" in h


def test_estimate_doc_type_shares_the_same_table():
    """估價單與報價單共用同一支 builder（使用者 2026-11-17 裁示「估價單一起改」）：備註同樣下移、沒有備註欄。"""
    for internal, span, ncols in ((False, "6", 7), (True, "8", 9)):
        q = _q()
        q["docType"] = "estimate"
        h = _html(q, internal=internal)
        assert "<title>MQ-T-1 估價單</title>" in h                          # 確實走的是估價單用語
        t = _table(h)
        assert re.findall(r'<tr class="remark-row[^"]*"><td></td><td colspan="(\d+)"', t) == [span, span]
        assert LONG in t and "含安裝" in t
        assert h.count("<th") - h.count("<thead") == ncols                  # 沒有備註欄
        assert ">備註</th>" not in h
