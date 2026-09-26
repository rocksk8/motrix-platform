# -*- coding: utf-8 -*-
"""M01 案件：完工單 PDF 樣板（2026-09-25 自 pdf_gen.py 搬出，DEPENDENCY-MAP §3 #1）。

pdf_gen（L1）只保留引擎與共用抬頭；完工單的版面與資料整形屬於案件模組，
L1 不再 import modules.case.api.completion_notes。抬頭／頁尾經 `_pg.<name>` 晚綁定取用。
"""
import json
import os
import tempfile
from datetime import datetime, date

import pdf_gen as _pg
from db import get_db
from helpers import _get_edge_path, run_edge_pdf


# ── 完工單 PDF（2026-09-12 交辦）────────────────────────────────────────────────
#
# 版面比照出貨單（`_build_shipping_html`），內容改成台灣工程業完工單慣例。CSS 刻意
# 各自帶一份而不抽共用——本檔 7 個 builder 本來就都是這樣，抽共用要動到已經在正式
# 機用的既有文件，風險不成比例。
#
# 跟出貨單版面上最大的差別是多了三個敘述性區塊（施工說明／測試與檢驗結果／
# **遺留事項**）。遺留事項那塊刻意做成紅框顯眼樣式：完工不等於零缺失，這一欄被
# 忽略正是日後驗收爭議的來源。

def _build_completion_html(n: dict) -> str:
    # 🔑 QL7：抬頭從**這一筆單據所屬的據點**取值，一支函式取一次。
    # ⚠️ 取不到 `locationId` ⇒ `location_identity(None)` 落在主要據點，
    #    那是既有安裝（只有一個據點、或根本沒設過）的正確行為。
    # 🔴 `QL25`（依據使用者 2026-09-23 裁示）：這份單據的抬頭要跟著
    #    報價單送出那一刻凍結的快照走（若有）——`apply_snapshot()` 疊
    #    在即時值上，只覆蓋抬頭五欄。銀行欄位不受影響：`QL10` 沒有被
    #    翻掉，它管的是別的欄位，此處若有銀行欄位仍然一律即時值。
    # 經 _pg 取：測試以 monkeypatch.setattr(pdf_gen, "location_identity", …) 換掉據點身分
    _ident = _pg.apply_snapshot(_pg.location_identity(_pg._location_of(n)), n)
    def esc(s):
        return (str(s) if s is not None else '').replace('&', '&amp;').replace('<', '&lt;') \
            .replace('>', '&gt;').replace('\n', '<br>')

    # 可自訂標題（2026-09-12）：使用者覆寫值已在 _note_public()/_completion_note_dict()
    # 疊過預設值，這裡直接用。預設用語刻意中性——公司除了工程還有專案、零組件販售、
    # 系統設定、網路架構、防火牆等業務，第一版全是「施工」講不通。
    L = n.get('labels') or {}

    def lab(key, fallback):
        v = L.get(key)
        return esc(v) if isinstance(v, str) and v.strip() else fallback

    _STATUS_STYLE = {
        '完成':     'color:#15803D;font-weight:600',
        '部分完成': 'color:#B45309;font-weight:600',
        '未施作':   'color:#B91C1C;font-weight:600',
    }

    items = n.get('items', [])
    item_rows = ''
    real_idx = 0
    for item in items:
        if item.get('type') == 'header':
            item_rows += (
                f'<tr style="background:#EFF6FF">'
                f'<td style="text-align:center;color:#93C5FD;font-size:10px">§</td>'
                f'<td colspan="5" style="font-weight:700;font-size:12px;color:#1D4ED8;padding:6px 8px">'
                f'{esc(item.get("description", ""))}</td>'
                f'</tr>'
            )
            continue
        real_idx += 1
        st = item.get('status') or '完成'
        item_rows += (
            f'<tr>'
            f'<td>{real_idx}</td>'
            f'<td>{esc(item.get("description", ""))}</td>'
            f'<td class="r">{esc(item.get("qty", ""))}</td>'
            f'<td>{esc(item.get("unit", ""))}</td>'
            f'<td style="{_STATUS_STYLE.get(st, "")}">{esc(st)}</td>'
            f'<td>{esc(item.get("notes", ""))}</td>'
            f'</tr>'
        )
    if not item_rows:
        item_rows = '<tr><td colspan="6" style="text-align:center;color:#999">（無完工項目）</td></tr>'

    def block(title, content, danger=False):
        if not (content or '').strip():
            return ''
        style = ('border:1px solid #FECACA;background:#FEF2F2;color:#7F1D1D'
                 if danger else 'border:1px solid #EDEAE4;background:#FAFAF8;color:#444')
        return (f'<div class="terms"><div class="section-label" style="margin-bottom:8px">{title}</div>'
                f'<div class="term-block" style="{style};border-radius:4px;padding:10px 12px">'
                f'{esc(content)}</div></div>')

    # 工期：開工～完工的天數（含首尾），兩個日期都有才算
    duration = ''
    sd, cd = (n.get('startDate') or '')[:10], (n.get('completionDate') or '')[:10]
    if sd and cd:
        try:
            from datetime import date as _d
            days = (_d.fromisoformat(cd) - _d.fromisoformat(sd)).days + 1
            duration = f'{days} 天'
        except ValueError:
            duration = ''

    # 保固月數留空／填 0 → 整列不印（比照報價單「條件留空就不印」的既有慣例，
    # 不另外開一個顯示旗標）。零組件販售、系統設定那類單子常常沒有保固可言。
    warranty_row = ''
    if n.get('warrantyMonths'):
        if n.get('warrantyStart') and n.get('warrantyEnd'):
            warranty_line = (f'{esc(n["warrantyStart"])} ～ {esc(n["warrantyEnd"])}'
                             f'（{esc(n.get("warrantyMonths", ""))} 個月）')
        else:
            warranty_line = f'{esc(n.get("warrantyMonths"))} 個月（自完工日起算）'
        warranty_row = (f'<div class="row"><span class="label">保固期間</span>'
                        f'<span class="val">{warranty_line}</span></div>')

    is_signed = bool(n.get('isSigned'))
    signed_note = ''
    if is_signed:
        signed_note = (f'<div style="font-size:10px;color:#16A34A;margin-top:6px">✓ 客戶已驗收簽回　'
                       f'{esc(n.get("signedBy", ""))}　'
                       f'{esc((n.get("signedAt") or "")[:16].replace("T", " "))}</div>')

    is_final = n.get('status') == '已核准'
    watermark_html = '' if is_final else (
        '<div class="wm">' + ''.join(
            '<div class="wm-item"><b>完工單預覽稿</b><small>尚未正式核准</small></div>'
            for _ in range(12)) + '</div>')
    banner_html = '' if is_final else (
        f'<div class="preview-banner">⚠ 此為完工單預覽稿（目前狀態：'
        f'{esc(n.get("status") or "草稿")}），尚未正式核准，請勿對外提供或引用</div>')

    return (
        '<!DOCTYPE html>\n'
        '<html lang="zh-Hant">\n'
        '<head>\n'
        '<meta charset="UTF-8">\n'
        f'<title>{esc(n.get("noteNo", ""))} 完工單</title>\n'
        '<style>\n'
        '  *{box-sizing:border-box;margin:0;padding:0}\n'
        '  body{font-family:"Microsoft JhengHei","PMingLiU",serif;font-size:13px;color:#0A0A0A;line-height:1.6;background:#fff}\n'
        '  #root{padding:24px 32px;position:relative}\n'
        '  .wm{position:absolute;inset:0;pointer-events:none;z-index:5;overflow:hidden;display:grid;'
        'grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(4,1fr);align-items:center;justify-items:center;box-sizing:border-box}\n'
        '  .wm-item{transform:rotate(-28deg);white-space:nowrap;user-select:none;text-align:center;line-height:1.5}\n'
        '  .wm-item b{display:block;font-size:19px;font-weight:900;letter-spacing:.14em;color:rgba(185,28,28,.09)}\n'
        '  .wm-item small{display:block;font-size:10px;font-weight:700;letter-spacing:.07em;color:rgba(185,28,28,.07)}\n'
        '  .preview-banner{margin-bottom:12px;padding:7px 12px;background:#EFF6FF;border:1px solid #BFDBFE;'
        'border-radius:5px;font-size:11px;color:#1E40AF;letter-spacing:.02em}\n'
        '  @page{size:A4;margin:0 13mm 12mm 13mm;'
        '@bottom-left{content:none}@bottom-right{content:none}'
        '@bottom-center{content:counter(page);font-family:Arial,sans-serif;font-size:9px;color:#aaa}}\n'
        '  @media print{html,body{margin:0;padding:0;background:#fff}#root{padding:15mm 0 0}.sign{page-break-inside:avoid}.terms{page-break-inside:avoid}tr{page-break-inside:avoid}}\n'
        '  .accent-bar{height:3px;background:#0A0A0A;margin-bottom:18px}\n'
        '  .header{display:flex;justify-content:space-between;align-items:flex-start;padding-bottom:14px;border-bottom:1px solid #0A0A0A;margin-bottom:16px}\n'
        '  .co-name{font-size:15px;font-weight:700;letter-spacing:.06em}\n'
        '  .co-sub{font-size:10px;color:#888;margin-top:3px;font-family:Arial,sans-serif;letter-spacing:.02em}\n'
        '  .doc-title{font-size:24px;font-weight:700;letter-spacing:.24em;text-align:right}\n'
        '  .meta{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;margin-bottom:14px;font-size:12px;background:#FAFAF8;padding:10px 12px;border-radius:4px;border:1px solid #EDEAE4}\n'
        '  .meta span{color:#888;font-family:Arial,sans-serif;font-size:11px}\n'
        '  .boxes{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px}\n'
        '  .box{background:#FAFAF8;border:1px solid #EDEAE4;border-radius:4px;padding:11px 13px}\n'
        '  .box-title{font-size:9px;font-family:Arial,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:#999;font-weight:600;margin-bottom:8px}\n'
        '  .row{display:flex;gap:6px;margin-bottom:4px;font-size:12px}\n'
        '  .label{color:#888;min-width:72px;flex-shrink:0;font-size:11px}\n'
        '  .val{color:#0A0A0A;font-weight:500}\n'
        '  .section-label{font-size:9px;font-family:Arial,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:#999;font-weight:600;margin-bottom:7px;display:flex;align-items:center;gap:8px}\n'
        '  .section-label::after{content:"";flex:1;height:1px;background:#EDEAE4}\n'
        '  table{width:100%;border-collapse:collapse;margin-bottom:14px}\n'
        '  thead th{background:#0A0A0A;color:#F5F4F0;padding:8px 9px;text-align:left;font-size:11px;font-weight:500;font-family:Arial,sans-serif;letter-spacing:.04em}\n'
        '  thead th.r{text-align:right}\n'
        '  tbody td{padding:8px 9px;border-bottom:1px solid #EDEAE4;font-size:12px}\n'
        '  tbody tr:last-child td{border-bottom:none}\n'
        '  tbody tr:nth-child(even) td{background:#FAFAF8}\n'
        '  td.r{text-align:right;font-family:Arial,sans-serif}\n'
        '  .terms{margin-bottom:16px}\n'
        '  .term-block{font-size:11px;line-height:1.8;white-space:pre-wrap}\n'
        '  .sign{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}\n'
        '  .sign-box{border:1px solid #EDEAE4;border-radius:4px;padding:16px 18px;min-height:110px;display:flex;flex-direction:column}\n'
        '  .sign-label{font-size:9px;color:#999;font-family:Arial,sans-serif;letter-spacing:.1em;text-transform:uppercase;margin-bottom:8px}\n'
        '  .sign-line{flex:1;border-bottom:1px solid #ccc;margin:10px 0}\n'
        '  .sign-date{font-size:10px;color:#999;font-family:Arial,sans-serif}\n'
        '  .footer{text-align:center;font-size:10px;color:#999;margin-top:18px;padding-top:12px;border-top:1px solid #EDEAE4;font-family:Arial,sans-serif;letter-spacing:.04em}\n'
        '</style>\n'
        '</head>\n'
        '<body>\n'
        '<div id="root">\n'
        f'{watermark_html}\n'
        '<div class="accent-bar"></div>\n'
        '<div class="header">\n'
        '  <div>\n'
        + _pg._identity_head(_ident) +
        '  </div>\n'
        '  <div>\n'
        '    <div class="doc-title">完　工　單</div>\n'
        '  </div>\n'
        '</div>\n'
        '<div class="meta">\n'
        f'  <div><span>完工單號：</span><strong style="font-family:Arial,sans-serif">{esc(n.get("noteNo", ""))}</strong></div>\n'
        f'  <div><span>完工日期：</span>{esc(n.get("completionDate", ""))}</div>\n'
        f'  <div><span>案件名稱：</span>{esc(n.get("projectName", ""))}</div>\n'
        '</div>\n'
        f'{banner_html}\n'
        '<div class="boxes">\n'
        '  <div class="box">\n'
        f'    <div class="box-title">{lab("sectionCustomer", "一、客戶與服務地點")}</div>\n'
        f'    <div class="row"><span class="label">客戶名稱</span><span class="val">{esc(n.get("customerName", ""))}</span></div>\n'
        f'    <div class="row"><span class="label">驗收人</span><span class="val">'
        f'{esc(n.get("recipient", ""))}'
        f'{("　" + esc(n.get("contactPhone", ""))) if n.get("contactPhone") else ""}</span></div>\n'
        f'    <div class="row"><span class="label">{lab("siteLabel", "服務地點")}</span><span class="val">{esc(n.get("siteAddress", ""))}</span></div>\n'
        '  </div>\n'
        '  <div class="box">\n'
        f'    <div class="box-title">{lab("sectionPeriod", "二、執行期間與保固")}</div>\n'
        f'    <div class="row"><span class="label">案件編號</span><span class="val">{esc(n.get("quoteNo", ""))}</span></div>\n'
        f'    <div class="row"><span class="label">執行期間</span><span class="val">'
        f'{esc(sd) or "—"} ～ {esc(cd) or "—"}{("　（" + duration + "）") if duration else ""}</span></div>\n'
        f'    {warranty_row}\n'
        f'    <div class="row"><span class="label">{lab("managerLabel", "負責人")}</span><span class="val">{esc(n.get("siteManager", ""))}</span></div>\n'
        '  </div>\n'
        '</div>\n'
        f'<div class="section-label">{lab("sectionItems", "三、完成項目明細")}</div>\n'
        '<table>\n'
        '  <thead>\n'
        '    <tr>\n'
        '      <th style="width:28px">#</th>\n'
        f'      <th>{lab("itemColumn", "項目 / 規格說明")}</th>\n'
        '      <th class="r" style="width:56px">數量</th>\n'
        '      <th style="width:48px">單位</th>\n'
        '      <th style="width:72px">完成狀態</th>\n'
        '      <th style="width:120px">備註</th>\n'
        '    </tr>\n'
        '  </thead>\n'
        f'  <tbody>{item_rows}</tbody>\n'
        '</table>\n'
        + block(lab('sectionSummary', '四、執行說明'), n.get('workSummary', ''))
        + block(lab('sectionTest', '五、測試與檢驗結果'), n.get('testResult', ''))
        + block(lab('sectionPending', '六、待辦與未完成事項'), n.get('pendingItems', ''), danger=True)
        + block('備註', n.get('notes', ''))
        + '<div class="sign">\n'
        '  <div class="sign-box">\n'
        f'    <div class="sign-label">{lab("signOwner", "客戶驗收 · 簽章")}</div>\n'
        '    <div class="sign-line"></div>\n'
        '    <div class="sign-date">驗收日期：＿＿＿＿＿＿＿＿＿＿</div>\n'
        f'    {signed_note}\n'
        '  </div>\n'
        '  <div class="sign-box">\n'
        f'    <div class="sign-label">{lab("signVendor", "執行單位 · 負責人")}</div>\n'
        '    <div class="sign-line"></div>\n'
        f'    <div class="sign-date">完工日期：{esc(cd) or "＿＿＿＿＿＿＿＿＿＿"}</div>\n'
        '  </div>\n'
        '</div>\n'
        '<div class="footer">\n'
        + _pg._identity_foot(_ident) +
        '</div>\n'
        '</div>\n'
        '<script>\n'
        'window.addEventListener("load",function(){\n'
        '  var r=document.getElementById("root");if(!r)return;\n'
        '  var A4H=Math.round(267/25.4*96);\n'
        '  var h=r.scrollHeight;\n'
        '  if(h>A4H){var s=A4H/h;if(s>=0.70){document.body.style.zoom=s.toFixed(4);}}\n'
        '});\n'
        '</script>\n'
        '</body>\n'
        '</html>'
    )


def _completion_note_dict(row) -> dict:
    """DB row → PDF 用的 dict。保固起訖在這裡算，PDF 與 API 走同一支
    `modules/case/api/completion_notes.py::_warranty_range()`，不要在這裡再寫一份月份加法。"""
    from modules.case.api.completion_notes import _warranty_range
    n = dict(row)
    n["items"] = json.loads(n.pop("items_json", None) or "[]")
    n["noteNo"] = n.get("note_no", "")
    n["quoteNo"] = n.get("quote_no", "")
    n["customerName"] = n.get("customer_name", "")
    n["projectName"] = n.get("project_name", "")
    n["siteAddress"] = n.get("site_address", "")
    n["startDate"] = n.get("start_date", "")
    n["completionDate"] = n.get("completion_date", "")
    n["siteManager"] = n.get("site_manager", "")
    n["contactPhone"] = n.get("contact_phone", "")
    n["workSummary"] = n.get("work_summary", "")
    n["testResult"] = n.get("test_result", "")
    n["pendingItems"] = n.get("pending_items", "")
    n["warrantyMonths"] = n.get("warranty_months", 0)
    n["warrantyStart"], n["warrantyEnd"] = _warranty_range(
        n.get("completion_date", ""), n.get("warranty_months", 0))
    n["isSigned"] = bool(n.get("is_signed"))
    n["signedBy"] = n.get("signed_by", "")
    n["signedAt"] = n.get("signed_at", "")
    # 可自訂標題：使用者覆寫疊在預設值上，跟 API 走同一支 merged_labels()
    from modules.case.api.completion_notes import merged_labels
    try:
        _dj = json.loads(n.get("data_json") or "{}") or {}
    except Exception:
        _dj = {}
    n["labels"] = merged_labels(_dj.get("labels"))
    return n


def generate_completion_pdf_bytes(note_no: str) -> bytes:
    """Edge Headless 產生完工單 PDF 並以 bytes 回傳（供 API 下載）。
    流程與 `generate_shipping_pdf_bytes()` 完全相同，含 EDGE_PDF_SEMAPHORE 併發限制。"""
    edge = _get_edge_path()
    conn = get_db()
    row = conn.execute("SELECT * FROM completion_notes WHERE note_no=?", (note_no,)).fetchone()
    conn.close()
    if not row:
        raise ValueError("完工單不存在")
    html_content = _build_completion_html(_completion_note_dict(row))
    tmp_html = tmp_pdf = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', encoding='utf-8', delete=False) as f:
            f.write(html_content)
            tmp_html = f.name
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            tmp_pdf = f.name
        file_url = 'file:///' + tmp_html.replace('\\', '/')
        run_edge_pdf(
            [edge, '--headless', '--disable-gpu', '--no-sandbox',
             f'--print-to-pdf={tmp_pdf}',
             '--no-pdf-header-footer',
             '--run-all-compositor-stages-before-draw',
             file_url]
        )
        if not os.path.exists(tmp_pdf) or os.path.getsize(tmp_pdf) == 0:
            raise ValueError("Edge 執行完畢但未產生 PDF 檔案")
        with open(tmp_pdf, 'rb') as f:
            return f.read()
    finally:
        for p in (tmp_html, tmp_pdf):
            if p:
                try:
                    os.unlink(p)
                except Exception:
                    pass
