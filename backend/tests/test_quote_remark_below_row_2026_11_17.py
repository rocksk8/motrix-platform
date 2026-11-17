# -*- coding: utf-8 -*-
"""報價單（含估價單）品項表：備註一律移到該品項下方整列，取消窄窄的「備註」欄（2026-11-17，使用者裁示）。

- 有備註 ⇒ 品項列下一列 <tr class="remark-row">，從「品名」欄（# 欄之後）橫跨到最右；客戶版 colspan=6、內部版（含成本／毛利率）colspan=8
- 備註欄表頭不再出現；分組標題列 colspan 與欄數一致（客戶版 6、內部版 8）
- 換行保留（<br>）、HTML 逸出
- 備註列與品項列不拆頁（break-after／break-before: avoid）；斑馬紋以品項為單位（備註列與上方品項同色）
- 整張單都沒有備註 ⇒ 輸出沒有任何新 class／CSS（與 pdf_golden 逐位元相同的前提）
"""
import re
from html.parser import HTMLParser

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


# ── 以結構讀 HTML／CSS（不靠文字子字串定位或計數；T87 A2 規則）──
_VOID = {"col", "br", "meta", "img", "hr", "input", "link"}


class _N:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.kids = tag, dict(attrs), parent, []
        self.cls = set((self.attrs.get("class") or "").split())

    @property
    def text(self):
        return "".join(k if isinstance(k, str) else k.text for k in self.kids)

    def walk(self):
        for k in self.kids:
            if isinstance(k, _N):
                yield k
                yield from k.walk()

    def all(self, tag):
        return [n for n in self.walk() if n.tag == tag]


class _P(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = self.cur = _N("#root", [], None)

    def handle_starttag(self, tag, attrs):
        n = _N(tag, attrs, self.cur)
        self.cur.kids.append(n)
        if tag not in _VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.kids.append(_N(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, d):
        self.cur.kids.append(d)


def _parse(html):
    p = _P()
    p.feed(html)
    p.close()
    return p.root


class _Row:
    def __init__(self, tr):
        self.cls = tr.cls
        self.cells = [c for c in tr.kids if isinstance(c, _N) and c.tag == "td"]
        self.spans = [int(c.attrs.get("colspan", 1)) for c in self.cells]
        self.text = tr.text


def _tbody_rows(html):
    """品項表 tbody 的每一列（依序）。"""
    tb = _parse(html).all("tbody")[0]
    return [_Row(tr) for tr in tb.all("tr")]


def _remarks(rows):
    return [r for r in rows if "remark-row" in r.cls]


def _ths(html):
    return _parse(html).all("thead")[0].all("th")


def _rbox_lines(html):
    """每個備註方框的內容，依 <br> 切成行（文字已還原逸出）；方框裡出現未逸出的標籤會留下 [tag] 記號讓比對失敗。"""
    out = []
    for n in _parse(html).walk():
        if n.tag == "div" and "rbox" in n.cls:
            lines = [""]
            for k in n.kids[1:]:                                   # 第 0 個是「備註」小標
                if isinstance(k, str):
                    lines[-1] += k
                elif k.tag == "br":
                    lines.append("")
                else:
                    lines[-1] += "[%s]" % k.tag
            out.append(lines)
    return out


def _css_rules(html):
    """<style> 內每條規則 ⇒ [(選擇器, 宣告)]，依出現順序。"""
    css = "".join(st.text for st in _parse(html).all("style"))
    return [(m.group(1).strip(), m.group(2).strip()) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)]


def _rule_pos(rules, sel, body=None):
    return [i for i, (a, b) in enumerate(rules) if a == sel and (body is None or b == body)]


def test_remark_goes_below_the_item_row_full_width():
    h = _html(_q())
    assert "<th style=\"width:72px\">備註</th>" not in h
    rows = _tbody_rows(h)
    rem = _remarks(rows)
    assert [r.spans for r in rem] == [[1, 6], [1, 6]]           # 長備註與短備註「含安裝」一律下移；第一格是 # 欄的空格
    assert all(r.cells[0].text == "" for r in rem)
    assert _rbox_lines(h) == [[LONG], ["含安裝"]]
    # 品項列之後緊接備註列：品項0（無備註）→ 品項1 → 備註 → 品項2 → 備註
    pos = {n: next(i for i, r in enumerate(rows) if n in r.text and "remark-row" not in r.cls) for n in ("品項0", "品項1", "品項2")}
    assert "remark-row" in rows[pos["品項1"] + 1].cls and LONG in rows[pos["品項1"] + 1].text
    assert "remark-row" in rows[pos["品項2"] + 1].cls and "含安裝" in rows[pos["品項2"] + 1].text
    assert "remark-row" not in rows[pos["品項0"] + 1].cls


def test_internal_version_spans_to_cost_columns():
    h = _html(_q(), internal=True)
    rows = _tbody_rows(h)
    assert [r.spans[1] for r in _remarks(rows)] == [8, 8]
    assert [r.spans for r in rows if "VMS" in r.text and "remark-row" not in r.cls] == [[1, 8]]   # 分組標題列也是 8（共 9 欄）
    assert len(_ths(h)) == 9


def test_header_colspan_matches_column_count():
    ext = _html(_q())
    group = [r for r in _tbody_rows(ext) if r.spans == [1, 6] and "remark-row" not in r.cls]
    assert len(group) == 1 and "VMS" in group[0].text
    assert "font-weight:700" in group[0].cells[1].attrs["style"]
    assert len(_ths(ext)) == 7


def test_newlines_kept_and_html_escaped():
    h = _html(_q(("第一行\n第二行 <b>&", "")))
    assert "第一行<br>第二行 &lt;b&gt;&amp;" in h
    assert "<b>&" not in h.replace("<b>備註</b>", "")


def test_remark_rows_do_not_split_across_pages_and_zebra_follows_item():
    h = _html(_q())
    assert "tr.has-below{page-break-after:avoid;break-after:avoid}" in h
    assert "tr.remark-row{page-break-before:avoid;break-before:avoid}" in h
    rows = _tbody_rows(h)
    # 列序：分組(1) 品項0(2,偶數→z) 品項1(3) 備註 品項2(4,偶數→z) 備註 ⇒ 備註列與上方品項同色
    kinds = {tuple(sorted(r.cls)) for r in rows}
    assert {("z",), ("has-below",), ("has-below", "z"), ("remark-row",), ("remark-row", "z")} <= kinds
    for i, r in enumerate(rows):
        if "remark-row" in r.cls:
            assert ("z" in r.cls) == ("z" in rows[i - 1].cls) and "has-below" in rows[i - 1].cls, (i, r.cls, rows[i - 1].cls)


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
        rows = _tbody_rows(h)
        assert [r.spans[1] for r in _remarks(rows)] == [int(span), int(span)]
        body = " ".join(r.text for r in rows)
        assert LONG in body and "含安裝" in body
        heads = _ths(h)
        assert len(heads) == ncols                                          # 沒有備註欄
        assert "備註" not in [th.text.strip() for th in heads]


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
    root = _parse(h)
    assert any("items" in t.cls for t in root.all("table"))
    cols = root.all("col")
    assert len(cols) == 7
    assert all(c.attrs.get("style", "").startswith("width:") and c.attrs["style"].endswith("%") for c in cols)    # 每欄百分比（頁面縮放時等比）
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
    assert len(_parse(h).all("col")) == 9 and "padding-left:5px;padding-right:5px" in h


def test_widths_do_not_depend_on_header_text():
    """欄寬只看品項資料（h17 讓「廠牌 / 型號」欄名可自訂）：函式只收 items／internal／total，改欄名不影響欄寬。"""
    import inspect
    assert list(inspect.signature(pdf_gen._quote_col_widths).parameters) == ["items", "internal", "total"]


def test_cost_cell_tint_wins_over_every_zebra_rule():
    """PM：內部版成本／毛利率格要每一列都淡橘底，不被灰色斑馬紋蓋過。同權重時後寫的贏 ⇒ 橘底規則必須在所有斑馬規則（nth-child、.z）之後；
    有備註、沒備註都一樣；客戶版沒有成本欄，不加這條。"""
    for q in (_q(), _q(("", "", ""))):
        h = _html(q, internal=True)
        rules = _css_rules(h)
        tint = _rule_pos(rules, "tbody tr td.cost-cell", "background:#FFF8F0")
        zebra = _rule_pos(rules, "tbody tr:nth-child(even) td") + _rule_pos(rules, "tbody tr.z td")
        assert len(tint) == 1 and zebra and all(tint[0] > z for z in zebra), (tint, zebra)
    assert "tbody tr td.cost-cell" not in _html(_q())


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
        pcts = [float(c.attrs["style"][len("width:"):-1]) for c in _parse(cg).all("col")]
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
        rules = _css_rules(h)
        dark = _rule_pos(rules, "thead th.cost-cell", "background:#0A0A0A")
        tint = _rule_pos(rules, ".cost-cell", "background:#FFF8F0")
        assert dark and tint and tint[0] < dark[0]                                  # 表頭深底規則在淡橘底之後（同權重以上）
        assert len([th for th in _ths(h) if {"r", "cost-cell"} <= th.cls]) == 2
    assert "thead th.cost-cell" not in _html(_q())                         # 客戶版沒有成本欄，輸出不動


def test_remark_box_uses_only_colors_already_in_the_quote_stylesheet():
    """使用者：備註的風格要跟報價單一致。.rbox 的每個色票都必須在報價單其他地方（條款方框、小標、徽章…）出現過。"""
    h = _html(_q())
    rules = _css_rules(h)
    rbox = [b for a, b in rules if a.startswith(".rbox")]
    other = "\n".join(b for a, b in rules if not a.startswith(".rbox"))
    other += "\n".join(n.attrs.get("style", "") for n in _parse(h).walk())          # 內嵌樣式（徽章等）
    colors = set(re.findall(r"#[0-9A-Fa-f]{3,6}\b", "\n".join(rbox)))
    assert colors, rbox
    for c in colors:
        assert c.lower() in other.lower(), (c, "報價單其他地方沒用過的顏色")
    assert "border-radius:4px" in "".join(rbox)


def test_adjusted_layout_neutralises_header_width_hints():
    """欄寬調整時 <th style=width> 的預設提示作廢（否則品名欄 th 的 190px 會把剩餘寬度按比例攤給所有欄）。"""
    h = _html(_rows(brand="SR-S-VMS-Mini2-516-AID04", name="主機"))
    assert "table.items thead th{width:auto!important}" in h




# ───────────── 備註排版選項：每個品項各自選「依輸入換行（wrap，預設）」或「連成一行（inline）」─────────────
MULTI = "智慧人形偵測 4 路\n每一路攝影機一套 AI 授權\n\n  含 ONVIF 錄影授權 x16  "


def _with_layout(layout, notes=MULTI, extra=None):
    q = _q((notes,))
    if layout is not ...:
        q["items"][1]["notesLayout"] = layout
    if extra:
        q["items"].append(extra)
    return q


def _rbox(h):
    return _rbox_lines(h)


def test_wrap_is_the_default_and_old_documents_render_byte_identically():
    no_key = _html(_with_layout(...))
    assert _html(_with_layout("wrap")) == no_key                       # 明寫 wrap ＝ 沒有這個鍵
    assert _rbox(no_key) == [["智慧人形偵測 4 路", "每一路攝影機一套 AI 授權", "", "  含 ONVIF 錄影授權 x16"]]      # 原樣保留換行（外圍空白由 strip 去掉）
    assert "notesLayout" not in no_key


def test_inline_flattens_newlines_into_one_run_joined_by_fullwidth_space():
    h = _html(_with_layout("inline"))
    assert _rbox(h) == [["智慧人形偵測 4 路　每一路攝影機一套 AI 授權　含 ONVIF 錄影授權 x16"]]     # 空行丟掉、每行去頭尾空白；一整段、沒有換行
    bodies = [b for a, b in _css_rules(h) if a == ".rbox"]
    assert bodies and all("white-space:nowrap" not in b for b in bodies)                  # 沒有強制不折行：排滿自然折行
    rem = _remarks(_tbody_rows(h))
    assert len(rem) == 1 and rem[0].spans[1] == 6


def test_inline_escapes_html_and_is_per_item():
    q = _with_layout("inline", notes="<b>x</b>\n&y", extra={"type": "item", "id": "i9", "description": "另一項", "brand": "B",
                                                          "unit": "台", "qty": 1, "unitPrice": 1, "amount": 1, "cost": 1,
                                                          "margin": 0, "notes": "第一行\n第二行"})
    h = _html(q)
    boxes = _rbox(h)
    assert boxes[0] == ["<b>x</b>　&y"]                                                   # 第一項：一行到底；標籤與 & 都是純文字（已逸出）
    assert boxes[1] == ["第一行", "第二行"]                                                  # 第二項沒選 ⇒ 預設換行：各品項各自選


def test_unknown_layout_values_fall_back_to_wrap_when_rendering():
    base = _html(_with_layout(...))
    for bad in ("INLINE", "inline ", "x", 1, None, True, ["inline"], {"a": 1}):
        assert _html(_with_layout(bad)) == base, bad


def test_inline_without_a_remark_adds_nothing():
    q = _q(("", "", ""))
    q["items"][1]["notesLayout"] = "inline"
    assert _html(q) == _html(_q(("", "", "")))


def test_estimate_shares_the_layout_option():
    for internal in (False, True):
        q = _with_layout("inline")
        q["docType"] = "estimate"
        assert _rbox(_html(q, internal=internal)) == [["智慧人形偵測 4 路　每一路攝影機一套 AI 授權　含 ONVIF 錄影授權 x16"]]


def test_server_cleans_unknown_layout_values_and_leaves_old_items_alone():
    from helpers import quote_item_notes as N
    d = {"items": [{"id": 1, "notes": "a"}, {"id": 2, "notesLayout": "inline"}, {"id": 3, "notesLayout": "wrap"},
                   {"id": 4, "notesLayout": "bogus"}, {"id": 5, "notesLayout": None}, {"id": 6, "notesLayout": 7}, "junk", None]}
    N.clean_items(d)
    assert d["items"][0] == {"id": 1, "notes": "a"}                                       # 沒這個鍵：原樣不動
    assert d["items"][1]["notesLayout"] == "inline" and d["items"][2]["notesLayout"] == "wrap"
    assert all("notesLayout" not in d["items"][i] for i in (3, 4, 5))                      # 不認得 ⇒ 清掉（＝預設）
    for junk in (None, {}, {"items": "x"}, []):
        N.clean_items(junk)                                                               # 垃圾輸入不爆
    assert N.layout_of({"notesLayout": "inline"}) == "inline" and N.layout_of(None) == "wrap"
