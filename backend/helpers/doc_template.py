# -*- coding: utf-8 -*-
"""L1 輸出引擎：版型定義（資料）＋單據視圖（資料）⇒ HTML（P2，CUSTOMIZATION-SPEC §3.4）。

版型只能使用 `BLOCKS` 裡登記的積木；所有值一律跳脫；不執行版型提供的任何程式。
計算（金額、稅、狀態…）只在單據視圖裡做——版型不能改核心欄位與計算（§1 裁示）。
"""
import json
import os
import re

from core import paths as _paths

# 主題與頁尾腳本：逐字取自 P2 改版前的開票申請憑據 builder（輸出必須逐位元組相同）
_VOUCHER_STANDARD_CSS = '  *{box-sizing:border-box;margin:0;padding:0}\n  body{font-family:"Microsoft JhengHei","PMingLiU",serif;font-size:13px;color:#0A0A0A;line-height:1.6;background:#fff}\n  #root{padding:24px 32px;position:relative}\n  .wm{position:absolute;inset:0;pointer-events:none;z-index:5;overflow:hidden;display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(4,1fr);align-items:center;justify-items:center;box-sizing:border-box}\n  .wm-item{transform:rotate(-28deg);white-space:nowrap;user-select:none;text-align:center;line-height:1.5}\n  .wm-item b{display:block;font-size:19px;font-weight:900;letter-spacing:.14em;color:rgba(185,28,28,.09)}\n  .wm-item small{display:block;font-size:10px;font-weight:700;letter-spacing:.07em;color:rgba(185,28,28,.07)}\n  .preview-banner{margin-bottom:12px;padding:7px 12px;background:#EFF6FF;border:1px solid #BFDBFE;border-radius:5px;font-size:11px;color:#1E40AF;letter-spacing:.02em}\n  @page{size:A4;margin:0 13mm 12mm 13mm;@bottom-center{content:counter(page);font-family:Arial,sans-serif;font-size:9px;color:#aaa}}\n  @media print{html,body{margin:0;padding:0;background:#fff}#root{padding:15mm 0 0}.sign{page-break-inside:avoid}tr{page-break-inside:avoid}}\n  .accent-bar{height:3px;background:#0A0A0A;margin-bottom:18px}\n  .header{display:flex;justify-content:space-between;align-items:flex-start;padding-bottom:14px;border-bottom:1px solid #0A0A0A;margin-bottom:16px}\n  .co-name{font-size:15px;font-weight:700;letter-spacing:.06em}\n  .co-sub{font-size:10px;color:#888;margin-top:3px;font-family:Arial,sans-serif;letter-spacing:.02em}\n  .doc-title{font-size:22px;font-weight:700;letter-spacing:.18em;text-align:right}\n  .meta{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;margin-bottom:14px;font-size:12px;background:#FAFAF8;padding:10px 12px;border-radius:4px;border:1px solid #EDEAE4}\n  .meta span{color:#888;font-family:Arial,sans-serif;font-size:11px}\n  .boxes{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px}\n  .box{background:#FAFAF8;border:1px solid #EDEAE4;border-radius:4px;padding:11px 13px}\n  .box-title{font-size:9px;font-family:Arial,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:#999;font-weight:600;margin-bottom:8px}\n  .row{display:flex;gap:6px;margin-bottom:4px;font-size:12px}\n  .label{color:#888;min-width:72px;flex-shrink:0;font-size:11px}\n  .val{color:#0A0A0A;font-weight:500}\n  .section-label{font-size:9px;font-family:Arial,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:#999;font-weight:600;margin-bottom:7px;display:flex;align-items:center;gap:8px}\n  .section-label::after{content:"";flex:1;height:1px;background:#EDEAE4}\n  table{width:100%;border-collapse:collapse;margin-bottom:14px}\n  thead th{background:#0A0A0A;color:#F5F4F0;padding:8px 9px;text-align:left;font-size:11px;font-weight:500;font-family:Arial,sans-serif;letter-spacing:.04em}\n  thead th.r{text-align:right}\n  tbody td{padding:8px 9px;border-bottom:1px solid #EDEAE4;font-size:12px}\n  tbody tr:last-child td{border-bottom:none}\n  tbody tr:nth-child(even) td{background:#FAFAF8}\n  td.r{text-align:right;font-family:Arial,sans-serif}\n  .total-box{display:flex;justify-content:flex-end;margin-bottom:16px}\n  .total-table{width:280px;font-size:12px}\n  .total-table .row{display:flex;justify-content:space-between;padding:4px 0}\n  .total-table .grand{font-size:15px;font-weight:700;border-top:1px solid #0A0A0A;padding-top:8px;margin-top:4px}\n  .sign{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}\n  .sign-box{border:1px solid #EDEAE4;border-radius:4px;padding:16px 18px;min-height:110px;display:flex;flex-direction:column}\n  .sign-label{font-size:9px;color:#999;font-family:Arial,sans-serif;letter-spacing:.1em;text-transform:uppercase;margin-bottom:8px}\n  .sign-line{flex:1;border-bottom:1px solid #ccc;margin:10px 0}\n  .sign-date{font-size:10px;color:#999;font-family:Arial,sans-serif}\n  .footer{text-align:center;font-size:10px;color:#999;margin-top:18px;padding-top:12px;border-top:1px solid #EDEAE4;font-family:Arial,sans-serif;letter-spacing:.04em}\n'

_FIT_A4_SCRIPT = '<script>window.addEventListener("load",function(){var r=document.getElementById("root");if(!r)return;var A4H=Math.round(267/25.4*96);var h=r.scrollHeight;if(h>A4H){var s=A4H/h;if(s>=0.70){document.body.style.zoom=s.toFixed(4);}}});</script>'


class TemplateError(ValueError):
    """版型定義有錯（未知積木、缺參數…）。訊息指出是哪一塊。"""


# ── 取值與格式 ──────────────────────────────────────────────────────────────

def _esc(s) -> str:
    """與既有 builder 相同的跳脫（& < > 與換行）。非字串一律先轉字串。"""
    if s is None:
        s = ""
    if not isinstance(s, str):
        s = str(s)
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')


def _get(data: dict, path: str, default=""):
    cur = data
    for part in str(path).split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def _money(n) -> str:
    return f'{n:,.0f}' if isinstance(n, (int, float)) and not isinstance(n, bool) else '0'


def _fmt(value, how: str = "text") -> str:
    """格式化並跳脫。格式目錄：text／str／money／date10／ntd。"""
    if how == "money":
        return _money(value)
    if how == "date10":
        return _esc((value or "")[:10])
    if how == "str":
        return _esc(str(value))
    if how == "text":
        return _esc(value or "")
    if how == "ntd":
        try:
            n = int(value or 0)
        except (TypeError, ValueError):
            n = 0
        return "NT$ %s" % format(n, ",") if n else "NT$ 0"
    raise TemplateError("未知格式：%r" % how)


def _cond(data: dict, c) -> bool:
    if not isinstance(c, dict) or "path" not in c:
        raise TemplateError("條件必須是 {path, equals} 或 {path, in}：%r" % (c,))
    v = _get(data, c["path"], None)
    if "equals" in c:
        return v == c["equals"]
    if "in" in c:
        return v in c["in"]
    if c.get("present") is True:
        return v not in (None, "", False, [], {})
    raise TemplateError("條件缺 equals／in／present：%r" % (c,))


def _text(data: dict, text: str) -> str:
    """靜態文字（跳脫）＋ `{path}`／`{path|預設}` 佔位（值跳脫；值空白時用預設）。"""
    out, i = [], 0
    for m in re.finditer(r"\{([A-Za-z0-9_.]+)(?:\|([^}]*))?\}", text):
        out.append(_esc(text[i:m.start()]))
        out.append(_esc(_get(data, m.group(1), None) or (m.group(2) or "")))
        i = m.end()
    out.append(_esc(text[i:]))
    return "".join(out)


# ── 積木 ───────────────────────────────────────────────────────────────────

def _b_watermark(b, data, parts):
    if b.get("unless") and _cond(data, b["unless"]):
        return "\n"
    item = '<div class="wm-item"><b>%s</b><small>%s</small></div>' % (_esc(b["text"]), _esc(b["small"]))
    return '<div class="wm">' + item * int(b.get("count", 12)) + '</div>' + "\n"


def _b_accent_bar(b, data, parts):
    return '<div class="accent-bar"></div>\n'


def _b_identity_header(b, data, parts):
    return ('<div class="header">\n  <div>\n' + parts["identity_head"]() +
            '  </div>\n  <div>\n    <div class="doc-title">%s</div>\n  </div>\n</div>\n' % _esc(b["title"]))


def _b_meta(b, data, parts):
    rows = []
    for f in b["fields"]:
        v = _fmt(_get(data, f["path"]), f.get("format", "text"))
        if f.get("style") == "strong_mono":
            v = '<strong style="font-family:Arial,sans-serif">%s</strong>' % v
        rows.append('  <div><span>%s</span>%s</div>\n' % (_esc(f["label"]), v))
    return '<div class="meta">\n' + "".join(rows) + '</div>\n'


def _b_banner(b, data, parts):
    if b.get("unless") and _cond(data, b["unless"]):
        return "\n"
    return '<div class="preview-banner">%s</div>' % _text(data, b["text"]) + "\n"


def _b_boxes(b, data, parts):
    out = ['<div class="boxes">\n']
    for box in b["boxes"]:
        out.append('  <div class="box">\n    <div class="box-title">%s</div>\n' % _esc(box["title"]))
        for r in box["rows"]:
            out.append('    <div class="row"><span class="label">%s</span><span class="val">%s</span></div>\n'
                       % (_esc(r["label"]), _fmt(_get(data, r["path"]), r.get("format", "text"))))
        out.append('  </div>\n')
    out.append('</div>\n')
    return "".join(out)


def _b_when(b, data, parts):
    branch = b.get("then", []) if _cond(data, b) else b.get("else", [])
    return render_blocks(branch, data, parts)


def _th(c):
    attrs = (' class="r"' if c.get("align") == "right" else "") + \
            (' style="width:%s"' % c["width"] if c.get("width") else "")
    return '<th%s>%s</th>' % (attrs, _esc(c["title"]))


def _td(c, row, index):
    how = c.get("format", "text")
    if how == "index":
        v = str(index)
    elif how == "spec_brand":
        spec, brand = _get(row, c["path"]), _get(row, c.get("brand_path", "brand"))
        v = _esc(spec) + (("　" + _esc(brand)) if brand else "")
    else:
        v = _fmt(_get(row, c["path"]), how)
    return ('<td class="r">%s</td>' if c.get("align") == "right" else '<td>%s</td>') % v


def _b_items_table(b, data, parts):
    items = _get(data, b["source"], []) or []
    body = "".join('<tr>' + "".join(_td(c, it, i) for c in b["columns"]) + '</tr>'
                   for i, it in enumerate(items, 1))
    if b.get("hide_when_empty") and not body:
        return ""
    return ('<div class="section-label">%s</div>\n' % _esc(b["label"]) +
            '<table>\n  <thead><tr>' + "".join(_th(c) for c in b["columns"]) + '</tr></thead>\n' +
            '  <tbody>%s</tbody>\n</table>\n' % body)


def _b_amount_box(b, data, parts):
    return ('<div class="section-label">%s</div>\n' % _esc(b["label"]) +
            '<div class="boxes" style="grid-template-columns:1fr">\n  <div class="box">\n'
            '    <div class="row"><span class="label">%s</span>'
            '<span class="val" style="font-size:16px;font-weight:700;font-family:Arial,sans-serif">'
            'NT$ %s</span></div>\n  </div>\n</div>\n' % (_esc(b["row_label"]), _money(_get(data, b["path"], 0))))


def _b_totals(b, data, parts):
    rows = "".join(
        '  <div class="row%s"><span>%s</span><span style="font-family:Arial,sans-serif">NT$ %s</span></div>\n'
        % (" grand" if r.get("grand") else "", _esc(r["label"]), _money(_get(data, r["path"], 0)))
        for r in b["rows"])
    return '<div class="total-box"><div class="total-table">\n' + rows + '</div></div>\n'


def _b_approval_sign(b, data, parts):
    return parts["approval_sign"]() + "\n"


def _b_sign_boxes(b, data, parts):
    if b.get("variant") == "named":
        out = ['<div class="sign">\n']
        for s in b["boxes"]:
            name = _esc(_get(data, s["name_path"])) if s.get("name_path") else "&nbsp;"
            out.append('  <div class="sign-box">\n    <div class="label">%s</div>\n    <div class="sign-line"></div>\n'
                       '    <div class="sign-name">%s</div>\n  </div>\n' % (_esc(s["label"]), name))
        out.append('</div>\n')
        return "".join(out)
    out = ['<div class="sign">\n']
    for s in b["boxes"]:
        out.append('  <div class="sign-box">\n    <div class="sign-label">%s</div>\n' % _esc(s["label"]))
        if s.get("name_path"):
            out.append('    <div style="font-size:13px;font-weight:600;color:#0A0A0A;margin:2px 0 8px">%s</div>\n'
                       % _esc(_get(data, s["name_path"])))
        date = _esc(_get(data, s["date_path"])) if s.get("date_path") else ""
        out.append('    <div class="sign-line"></div>\n    <div class="sign-date">%s%s</div>\n  </div>\n'
                   % (_esc(s["date_label"]), date or _BLANK_LINE))
    out.append('</div>\n')
    return "".join(out)


def _b_doc_header(b, data, parts):
    """置中大標題＋副標（公司名）＋右上資訊框（單號、日期…）。勞報單那一種抬頭。"""
    info = "<br>\n".join("    %s%s" % (_esc(f.get("label", "")), _fmt(_get(data, f["path"]), f.get("format", "text")))
                         for f in b.get("info", []))
    sub = ('    <div style="font-size:9pt;color:#666">%s</div>\n' % _esc(_get(data, b["subtitle_path"]))
           if b.get("subtitle_path") else "")
    return ('<div class="hdr">\n  <div style="min-width:150px"></div>\n  <div class="hdr-mid">\n'
            '    <h1>%s</h1>\n%s  </div>\n  <div class="hdr-info">\n%s\n  </div>\n</div>\n'
            % (_esc(b["title"]), sub, info))


def _b_section_title(b, data, parts):
    return '<div class="section-title">%s</div>\n' % _text(data, b["text"])


def _b_part(b, data, parts):
    """呼叫端（pdf_gen）提供的片段：抬頭／附件頁／重印註記這類呈現規則只在程式一處的東西。"""
    fn = parts.get(b["name"])
    if fn is None:
        raise TemplateError("未知片段 %r（這份單據提供：%s）" % (b["name"], "、".join(sorted(parts)) or "無"))
    return fn()


_CELL_STYLES = {"pre_wrap": "white-space:pre-wrap"}


def _cell(c, data):
    if "th" in c:
        return "<th>%s</th>" % _esc(c["th"])
    if "text" in c:
        v = _text(data, c["text"])
    else:
        v = _fmt(_get(data, c["path"]), c.get("format", "text")) if c.get("path") else ""
    if c.get("tag"):
        v = '<span class="tag">%s</span>' % v
    attrs = ""
    if c.get("class"):
        attrs += ' class="%s"' % _esc(c["class"])
    if c.get("style"):
        if c["style"] not in _CELL_STYLES:
            raise TemplateError("未知儲存格樣式：%r（可用：%s）" % (c["style"], "、".join(_CELL_STYLES)))
        attrs += ' style="%s"' % _CELL_STYLES[c["style"]]
    if c.get("colspan"):
        attrs += ' colspan="%d"' % int(c["colspan"])
    return "<td%s>%s</td>" % (attrs, v)


def _b_kv_table(b, data, parts):
    """表頭欄＋值欄的表格（每列由儲存格組成；列可以帶 when／unless 條件）。"""
    rows = []
    for r in b["rows"]:
        if r.get("when") and not _cond(data, r["when"]):
            continue
        if r.get("unless") and _cond(data, r["unless"]):
            continue
        cls = ' class="%s"' % _esc(r["class"]) if r.get("class") else ""
        rows.append("  <tr%s>%s</tr>\n" % (cls, "".join(_cell(c, data) for c in r["cells"])))
    cls = ' class="%s"' % _esc(b["class"]) if b.get("class") else ""
    return "<table%s>\n%s</table>\n" % (cls, "".join(rows))


def _b_footer_text(b, data, parts):
    return '<div class="footer">\n  %s\n</div>\n' % _text(data, b["text"])


def _b_text_page(b, data, parts):
    """另起一頁的整段文字（例：個資蒐集告知）。保留換行。"""
    brk = "page-break-before:always;" if b.get("page_break", True) else ""
    return ('<div style="%spadding:14mm 14mm 10mm;font-family:\'微軟正黑體\',\'Microsoft JhengHei\',sans-serif;color:#111">\n'
            '  <div style="font-size:14pt;font-weight:700;letter-spacing:2px;border-bottom:2px solid #333;'
            'padding-bottom:6px;margin-bottom:14px">%s</div>\n'
            '  <div style="font-size:10pt;line-height:1.8;white-space:pre-wrap">%s</div>\n</div>\n'
            % (brk, _esc(b["title"]), _esc(_get(data, b["path"])).replace("<br>", "\n")))


def _b_identity_footer(b, data, parts):
    return '<div class="footer">\n' + parts["identity_foot"]() + '</div>\n'


#: 積木目錄（v1）。版型只能使用這裡登記的型別（CUSTOMIZATION-SPEC §3.4）。
BLOCKS = {
    "watermark": _b_watermark, "accent_bar": _b_accent_bar, "identity_header": _b_identity_header,
    "meta": _b_meta, "banner": _b_banner, "boxes": _b_boxes, "when": _b_when,
    "items_table": _b_items_table, "amount_box": _b_amount_box, "totals": _b_totals,
    "approval_sign": _b_approval_sign, "sign_boxes": _b_sign_boxes, "identity_footer": _b_identity_footer,
    "doc_header": _b_doc_header, "section_title": _b_section_title, "part": _b_part, "kv_table": _b_kv_table,
    "footer_text": _b_footer_text, "text_page": _b_text_page,
}
#: 欄位值格式目錄（`format`）；表格欄另有 `index`（列號）、`spec_brand`（規格＋品牌）
FORMATS = ("text", "str", "money", "date10", "ntd")
COLUMN_FORMATS = FORMATS + ("index", "spec_brand")

#: 積木參數規格（建構器／排版器依它產生屬性面板；P8 缺口 #4）。每個參數：型別、必填、說明。
#: 型別：`text`（字串）、`int`、`bool`、`path`（視圖路徑）、`cond`（`{path, equals}` 或 `{path, in}`）、
#: `list:<子項名稱>`（子項規格見 `items`）、`blocks`（巢狀積木清單）
_P = lambda type_, required=False, desc="": {"type": type_, "required": required, "desc": desc}  # noqa: E731
BLOCK_SPECS = {
    "watermark": {"desc": "滿版浮水印（例：預覽稿）", "params": {
        "text": _P("text", True, "大字"), "small": _P("text", True, "小字"), "count": _P("int", False, "重複次數（預設 12）"),
        "unless": _P("cond", False, "條件成立就不印")}},
    "accent_bar": {"desc": "頁首色條", "params": {}},
    "identity_header": {"desc": "公司抬頭＋單據標題（抬頭取自公司資料）", "params": {"title": _P("text", True, "單據標題")}},
    "meta": {"desc": "單據資訊列（編號、日期…）", "params": {"fields": _P("list:field", True)}},
    "banner": {"desc": "提示橫幅；文字可用 {路徑|預設}", "params": {
        "text": _P("text", True), "unless": _P("cond", False, "條件成立就不印")}},
    "boxes": {"desc": "並排的資訊框", "params": {"boxes": _P("list:box", True)}},
    "when": {"desc": "條件分支", "params": {
        "path": _P("path", True), "equals": _P("text", False), "in": _P("list:text", False),
        "then": _P("blocks", False), "else": _P("blocks", False)}},
    "items_table": {"desc": "明細表", "params": {
        "source": _P("path", True, "清單的路徑"), "label": _P("text", True, "表格上方的標題"),
        "columns": _P("list:column", True), "hide_when_empty": _P("bool", False, "沒有資料就整段不印")}},
    "amount_box": {"desc": "單一金額框", "params": {
        "label": _P("text", True), "row_label": _P("text", True), "path": _P("path", True)}},
    "totals": {"desc": "合計表", "params": {"rows": _P("list:total_row", True)}},
    "approval_sign": {"desc": "系統簽核歷程（誰、何時簽）", "params": {}},
    "sign_boxes": {"desc": "手寫簽名欄", "params": {"boxes": _P("list:sign_box", True),
                                                "variant": _P("text", False, "named＝標籤＋簽名線＋姓名（勞報單）")}},
    "identity_footer": {"desc": "公司頁尾（取自公司資料）", "params": {}},
    "doc_header": {"desc": "置中大標題＋副標＋右上資訊框", "params": {
        "title": _P("text", True), "subtitle_path": _P("path", False), "info": _P("list:field", False)}},
    "section_title": {"desc": "段落標題列；文字可用 {路徑|預設}", "params": {"text": _P("text", True)}},
    "part": {"desc": "程式提供的片段（抬頭、附件頁、重印註記…）", "params": {"name": _P("text", True, "片段名稱")}},
    "kv_table": {"desc": "表頭＋值的表格；列可帶條件", "params": {
        "class": _P("text", False), "rows": _P("list:row", True)}},
    "footer_text": {"desc": "頁尾一行文字；可用 {路徑|預設}", "params": {"text": _P("text", True)}},
    "text_page": {"desc": "另起一頁的整段文字（保留換行）", "params": {
        "title": _P("text", True), "path": _P("path", True), "page_break": _P("bool", False, "預設另起一頁")}},
}
#: `list:<子項>` 的子項規格
BLOCK_ITEM_SPECS = {
    "field": {"label": _P("text", True), "path": _P("path", True), "format": _P("text", False, "、".join(FORMATS)),
              "style": _P("text", False, "strong_mono＝等寬粗體")},
    "box": {"title": _P("text", True), "rows": _P("list:field", True)},
    "column": {"title": _P("text", True), "path": _P("path", False, "format＝index 時不用"),
               "format": _P("text", False, "、".join(COLUMN_FORMATS)), "align": _P("text", False, "right＝靠右"),
               "width": _P("text", False, "例：12%"), "brand_path": _P("path", False, "spec_brand 用")},
    "total_row": {"label": _P("text", True), "path": _P("path", True), "grand": _P("bool", False, "總計列加粗")},
    "sign_box": {"label": _P("text", True), "date_label": _P("text", False, "variant≠named 時必填"),
                 "name_path": _P("path", False), "date_path": _P("path", False)},
    "row": {"cells": _P("list:cell", True), "class": _P("text", False), "when": _P("cond", False), "unless": _P("cond", False)},
    "cell": {"th": _P("text", False, "表頭儲存格的文字"), "path": _P("path", False), "text": _P("text", False, "可用 {路徑}"),
             "format": _P("text", False, "、".join(FORMATS)), "colspan": _P("int", False), "class": _P("text", False),
             "tag": _P("bool", False, "包成標籤"), "style": _P("text", False, "pre_wrap")},
}

#: 手寫簽名欄沒有值時的底線
_BLANK_LINE = "＿＿＿＿＿＿＿＿＿＿"


def render_blocks(blocks, data, parts) -> str:
    out = []
    for n, b in enumerate(blocks):
        t = b.get("type") if isinstance(b, dict) else None
        fn = BLOCKS.get(t)
        if fn is None:
            raise TemplateError("第 %d 塊：未知積木 %r（積木目錄：%s）" % (n + 1, t, "、".join(sorted(BLOCKS))))
        try:
            out.append(fn(b, data, parts))
        except KeyError as e:
            raise TemplateError("第 %d 塊（%s）缺參數 %s" % (n + 1, t, e)) from None
    return "".join(out)


#: 勞報單的樣式與外框（P2 第二份單據，2026-09-26；抽取自改版前的 builder，驗收見 CUSTOMIZATION-SPEC §3.4）
_PAYSLIP_CSS = '*{box-sizing:border-box;margin:0;padding:0}\n@page{size:A4;margin:0}\nbody{font-family:"微軟正黑體","Microsoft JhengHei",sans-serif;font-size:11pt;color:#111;background:#fff}\n#root{padding:14mm 14mm}\n.hdr{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px}\n.hdr-mid{flex:1;text-align:center}\nh1{font-size:18pt;font-weight:700;letter-spacing:4px;margin:0 0 2px 0}\n.hdr-info{text-align:right;font-size:9pt;color:#444;min-width:150px;line-height:1.8;\n           border:1px solid #999;padding:5px 8px;border-radius:3px}\ntable{width:100%;border-collapse:collapse;margin-bottom:10px}\nth,td{border:1px solid #555;padding:5px 8px;vertical-align:top}\nth{background:#f0f0f0;font-weight:600;width:100px;white-space:nowrap}\n.section-title{background:#d0d8e8;font-weight:700;font-size:10pt;padding:4px 8px;\n                border:1px solid #555;margin-top:8px;margin-bottom:0}\n.amount-row th{width:160px}\n.amount-row td{font-size:12pt}\n.net{background:#fff8e1;font-weight:700;font-size:13pt}\n.note-cell{font-size:9pt;color:#555}\n.sign{display:flex;gap:20px;margin-top:14px}\n.sign-box{flex:1;border:1px solid #555;padding:10px 12px}\n.sign-box .label{font-size:9pt;color:#555;margin-bottom:4px}\n.sign-line{height:50px;border-bottom:1px solid #aaa;margin-bottom:4px}\n.sign-name{font-size:9pt;color:#444}\n.footer{text-align:center;font-size:8pt;color:#888;margin-top:10px;border-top:1px solid #ccc;padding-top:6px}\n.tag{display:inline-block;border:1px solid #555;padding:1px 8px;font-size:9pt;margin-right:4px}\n'
_PAYSLIP_SCRIPT = '<script>\nwindow.addEventListener("load",function(){\n  var r=document.getElementById("root");if(!r)return;\n  var A4H=Math.round(297/25.4*96);\n  var h=r.scrollHeight;\n  if(h>A4H){var s=A4H/h;if(s>=0.50){r.style.zoom=s.toFixed(4);}}\n});\n</script>'

#: 主題：`css`；可選的外框 `frame`＝(開頭, css 之後到 #root 開頭, #root 結尾到 after_root 之間, 結尾)。
#: 沒有 frame ⇒ 用 render() 的預設外框（開票憑據那一種，逐位元組不變）。
THEMES = {
    "voucher_standard": {"css": _VOUCHER_STANDARD_CSS},
    "payslip": {"css": _PAYSLIP_CSS,
                "frame": ('<!DOCTYPE html><html lang="zh-TW"><head><meta charset="UTF-8">\n<style>\n', '</style></head><body>\n<div id="root">\n', "</div>\n", "\n" + _PAYSLIP_SCRIPT + "\n</body></html>")},
}


def render(template: dict, data: dict, parts: dict) -> str:
    """版型定義＋單據視圖 ⇒ 完整 HTML（交給 Edge 轉 PDF）。

    `parts`：由呼叫端（pdf_gen）注入的共用片段 `identity_head`／`identity_foot`／`approval_sign`，
    本檔不 import pdf_gen（避免循環；那三段的呈現規則仍只在 pdf_gen 一處）。
    """
    theme = THEMES.get(template.get("theme"))
    if theme is None:
        raise TemplateError("未知主題：%r" % template.get("theme"))
    if theme.get("frame"):
        # 主題自帶外框；`after_root` 是 #root 之外的積木（例：另起一頁的附件）
        start, after_css, close_root, end = theme["frame"]
        body = render_blocks(template.get("blocks") or [], data, parts)
        after = render_blocks(template.get("after_root") or [], data, parts)
        return start + theme["css"] + after_css + body + close_root + after + end
    title = template.get("title") or {}
    head = ('<!DOCTYPE html>\n<html lang="zh-Hant">\n<head>\n<meta charset="UTF-8">\n'
            '<title>%s%s</title>\n' % (_esc(_get(data, title.get("path", ""))), _esc(title.get("suffix", ""))) +
            '<style>\n' + theme["css"] + '</style>\n</head>\n<body>\n<div id="root">\n')
    body = render_blocks(template.get("blocks") or [], data, parts)
    tail = '</div>\n' + (_FIT_A4_SCRIPT + '\n' if template.get("fit_a4", True) else '') + '</body>\n</html>'
    return head + body + tail


#: 預設版型目錄（隨程式出貨）。錨點用 core.paths（守門：產品碼不可用 __file__ 算路徑）
_TEMPLATE_DIR = _paths.backend("helpers", "output_templates")


def load_default(key: str) -> dict:
    """隨程式出貨的預設版型（`helpers/output_templates/<key>.json`）。覆寫版（公司／角色）由 P5 版面定義提供。"""
    with open(os.path.join(_TEMPLATE_DIR, key + ".json"), encoding="utf-8") as f:
        return json.load(f)


def validate(template: dict, sample_view: dict = None) -> list:
    """版型驗證：回問題清單（空＝通過）。檢查積木型別、主題；給了視圖樣本就列出引用不到的欄位。"""
    return [p["message"] for p in problems(template, sample_view)]


def problems(template: dict, sample_view: dict = None) -> list:
    """同 `validate`，但每一項帶**位置**：`[{"path": "blocks[3].then[0]", "message": …}]`（建構器／排版器標出錯在哪，§8）。"""
    out = []
    if template.get("theme") not in THEMES:
        out.append({"path": "theme", "message": "未知主題：%r" % template.get("theme")})

    def walk(blocks, where, path):
        for n, b in enumerate(blocks or []):
            here = "%s[%d]" % (path, n)
            t = b.get("type") if isinstance(b, dict) else None
            if t not in BLOCKS:
                out.append({"path": here + ".type", "message": "%s第 %d 塊：未知積木 %r" % (where, n + 1, t)})
                continue
            if t == "when":
                walk(b.get("then"), where + "when/then ", here + ".then")
                walk(b.get("else"), where + "when/else ", here + ".else")
            if sample_view is not None:
                for p in _paths_of(b):
                    if _get(sample_view, p, _MISSING) is _MISSING:
                        out.append({"path": here, "message": "%s第 %d 塊（%s）引用不到欄位 %s" % (where, n + 1, t, p)})
    walk(template.get("blocks"), "", "blocks")
    walk(template.get("after_root"), "頁後 ", "after_root")
    return out


_MISSING = object()


def _paths_of(b):
    t = b["type"]
    if t in ("meta",):
        return [f["path"] for f in b.get("fields", [])]
    if t == "boxes":
        return [r["path"] for box in b.get("boxes", []) for r in box.get("rows", [])]
    if t in ("items_table",):
        return [b["source"]]
    if t in ("amount_box",):
        return [b["path"]]
    if t == "totals":
        return [r["path"] for r in b.get("rows", [])]
    if t == "when":
        return [b["path"]]
    if t == "sign_boxes":
        return [p for s in b.get("boxes", []) for p in (s.get("name_path"), s.get("date_path")) if p]
    if t == "doc_header":
        return [x for x in [b.get("subtitle_path")] + [f.get("path") for f in b.get("info", [])] if x]
    if t == "kv_table":
        out = []
        for row in b.get("rows", []):
            out += [c[k]["path"] for k in ("when", "unless") for c in [row] if isinstance(c.get(k), dict)]
            out += [c["path"] for c in row.get("cells", []) if c.get("path")]
            out += [m for c in row.get("cells", []) if c.get("text") for m in _placeholders(c["text"])]
        return out
    if t in ("section_title", "footer_text", "banner"):
        return _placeholders(b.get("text", ""))
    if t == "text_page":
        return [b["path"]]
    return []


def _placeholders(text):
    return [m.group(1) for m in re.finditer(r"\{([A-Za-z0-9_.]+)(?:\|[^}]*)?\}", text or "")]
