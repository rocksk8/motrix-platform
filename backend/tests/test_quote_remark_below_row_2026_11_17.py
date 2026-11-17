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


# ───────────── 欄寬依內容自動分配（品名／廠牌型號，數字欄縮到剛好放得下最大金額）─────────────
def _rows(brand="HDD-8TB", name="硬碟", price=7800, notes=""):
    return {"quoteNo": "MQ-T-2", "customerName": "甲", "items": [
        {"type": "item", "id": "a", "description": name, "brand": brand, "unit": "台", "qty": 1,
         "unitPrice": price, "amount": price, "cost": int(price * .7), "margin": .3, "notes": notes}]}


def _widths(items, internal=False):
    return pdf_gen._quote_col_widths(items, internal)


def test_short_part_numbers_and_normal_amounts_leave_the_layout_untouched():
    q = _rows()
    assert _widths(q["items"]) is None and _widths(q["items"], True) is None
    h = _html(q)
    assert "<colgroup>" not in h and "table-layout" not in h and "<table>\n  <thead>" in h


def test_long_part_number_widens_brand_column_and_numeric_columns_give_way():
    q = _rows(brand="SR-S-VMS-Mini2-516-AID04", name="主機")
    w = _widths(q["items"])                                    # # 品名 廠牌 數量 單位 單價 金額
    assert len(w) == 7 and abs(sum(w) - 695) <= 1, w
    assert w[2] >= pdf_gen._est_px("SR-S-VMS-Mini2-516-AID04") + 20 and w[2] > 110
    assert w[5] <= 122 and w[6] <= 122 and w[1] >= 100        # 數字欄不比預設寬，品名欄保有最小寬度
    h = _html(q)
    assert '<table class="items">' in h and len(re.findall(r"<col[ >]", h)) == 7
    assert len(re.findall(r'<col style="width:[\d.]+%">', h)) == 7             # 每欄百分比（頁面縮放時等比）
    assert "table.items{table-layout:fixed}" in h


def test_long_name_short_part_number_widens_name_and_shrinks_brand():
    q = _rows(brand="HDD-8TB", name="監控級硬碟 8TB，7x24 小時運轉專用，含安裝與資料遷移，附原廠保固卡與出貨檢測報告")
    w = _widths(q["items"])
    assert w[1] > 190 and w[2] < 110 and w[2] >= 88 and abs(sum(w) - 695) <= 1, w


def test_big_amounts_get_their_width_and_never_below_the_need():
    q = _rows(brand="SR-S-VMS-Mini2-516-AID04", name="y", price=98765432)
    w = _widths(q["items"])
    need = int(pdf_gen._est_px("NT$ 98,765,432", num=True) + 20)
    assert w[5] >= need and w[6] >= need and abs(sum(w) - 695) <= 1, (w, need)
    wi = _widths(q["items"], internal=True)                    # # 品名 廠牌 數量 單位 成本 毛利率 單價 金額
    assert len(wi) == 9 and abs(sum(wi) - 695) <= 1 and wi[7] >= int(pdf_gen._est_px("NT$ 98,765,432", num=True) + 12)


def test_internal_version_has_nine_columns_and_tighter_padding():
    q = _rows(brand="SR-S-VMS-Mini2-516-AID04", name="主機")
    h = _html(q, internal=True)
    assert len(re.findall(r"<col[ >]", h)) == 9 and "padding-left:5px;padding-right:5px" in h


def test_widths_do_not_depend_on_header_text():
    """欄寬只看品項資料（h17 讓「廠牌 / 型號」欄名可自訂）：函式只收 items／internal／total，改欄名不影響欄寬。"""
    import inspect
    assert list(inspect.signature(pdf_gen._quote_col_widths).parameters) == ["items", "internal", "total"]


def test_cost_cell_tint_is_pinned_when_remark_rows_shift_the_zebra():
    """h19 審查：備註列讓 nth-child 奇偶錯位 ⇒ 成本欄橘底忽有忽無；有備註時成本欄底色固定（品項列橘、z 列灰）。"""
    h = _html(_q(), internal=True)
    a, b = h.index("tbody tr td.cost-cell{background:#FFF8F0}"), h.index("tbody tr.z td{background:#FAFAF8}")
    assert h.index("tbody tr:nth-child(even) td{background:none}") < a < b


def test_estimator_matches_measured_chromium_widths():
    """字寬表由 Chromium canvas.measureText 實測（12px）：誤差要在 ±4% 內，才能把邊距收到 2px。"""
    for text, num, real in (("SR-S-VMS-Mini2-516-AID04", False, 161.4), ("Hikvision DS-2CD2143G2-IU", False, 160.6),
                            ("DS-2CD2143G2-IU", False, 106.2), ("HDD-8TB", False, 53.5),
                            ("NT$ 86,100", True, 62.7), ("NT$ 5,200", True, 56.0), ("NT$ 12,345,678", True, 86.1)):
        got = pdf_gen._est_px(text, num=num)
        assert abs(got - real) / real <= 0.04, (text, got, real)


def test_colgroup_uses_percentages_that_sum_to_100():
    """PDF 長單會被 zoom 縮放，版面寬度 ≠ 695px：欄寬用百分比，各欄等比，不會有欄被多撐出空白。"""
    for cols in ([28, 122, 184, 48, 71, 121, 121], [28, 120, 174, 35, 36, 75, 52, 93, 82]):
        cg = pdf_gen._quote_colgroup(cols)
        pcts = [float(x) for x in re.findall(r"width:([\d.]+)%", cg)]
        assert len(pcts) == len(cols) and abs(sum(pcts) - 100) < 0.002, pcts


def test_number_columns_keep_default_widths_unless_space_is_short():
    """使用者：內容夠就不要壓縮後面的數字欄。短品名＋最長料號：數量／單位／單價／金額維持預設 48／70／120／120。"""
    w = _widths(_rows(brand="SR-S-VMS-Mini2-516-AID04", name="主機")["items"])
    assert [w[3], w[4], w[5], w[6]] == [48, 71, 121, 121] or all(abs(a - b) <= 2 for a, b in zip(w[3:], (48, 70, 120, 120))), w
    assert w[2] >= pdf_gen._est_px("SR-S-VMS-Mini2-516-AID04") + 20          # 料號一行放得下
    assert w[1] < 140                                                       # 品名不會被塞成超寬
    # 長品名＋長料號：不夠用才從數字欄借，借到不比最大金額／表頭窄為止
    L = "i5 Mini2 主機（詳細規格於附件檔案），含 16 路 ONVIF 錄影授權、雙網卡、64GB 記憶體與原廠三年保固"
    w2 = _widths(_rows(brand="SR-S-VMS-Mini2-516-AID04", name=L, price=86100)["items"])
    floor = int(pdf_gen._est_px("NT$ 86,100", num=True) + 20)
    assert w2[5] < 120 and w2[5] >= max(floor, 100) and w2[6] >= floor and w2[1] > w[1], (w2, floor)


def test_internal_header_cost_cells_stay_dark():
    """PM：內部版表頭「單位成本／毛利率」被 .cost-cell 淡橘底蓋成白字配淡底看不見；表頭維持深底，淡橘底只給 tbody 的 td。"""
    for q in (_q(), _q(("", "", ""))):
        h = _html(q, internal=True)
        assert "thead th.cost-cell{background:#0A0A0A}" in h
        assert h.index(".cost-cell{background:#FFF8F0}") < h.index("thead th.cost-cell{background:#0A0A0A}")   # 同權重以上、且在後
        head = h[h.index("<thead>"):h.index("</thead>")]
        assert head.count('<th class="r cost-cell"') == 2
    assert "thead th.cost-cell" not in _html(_q())                         # 客戶版沒有成本欄，輸出不動


def test_remark_box_uses_only_colors_already_in_the_quote_stylesheet():
    """使用者：備註的風格要跟報價單一致。.rbox 的每個色票都必須在報價單其他地方（條款方框、小標、徽章…）出現過。"""
    h = _html(_q())
    css = h[h.index("<style>"):h.index("</style>")]
    rbox = [ln for ln in css.split("\n") if ln.strip().startswith(".rbox")]
    other = "\n".join(ln for ln in css.split("\n") if not ln.strip().startswith(".rbox"))
    other += h[h.index("</style>"):]                                  # 內嵌樣式（徽章等）
    colors = set(re.findall(r"#[0-9A-Fa-f]{3,6}\b", "\n".join(rbox)))
    assert colors, rbox
    for c in colors:
        assert c.lower() in other.lower() or c.lower() in h[h.index("</style>"):].lower(), (c, "報價單其他地方沒用過的顏色")
    assert "border-radius:4px" in "".join(rbox)


def test_adjusted_layout_neutralises_header_width_hints():
    """欄寬調整時 <th style=width> 的預設提示作廢（否則品名欄 th 的 190px 會把剩餘寬度按比例攤給所有欄）。"""
    h = _html(_rows(brand="SR-S-VMS-Mini2-516-AID04", name="主機"))
    assert "table.items thead th{width:auto!important}" in h


