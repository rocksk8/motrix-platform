"""Server-side PDF generation via Edge headless print."""
import json
import os
import re
import tempfile
import logging
from datetime import datetime, date

from db import (
    get_db, is_demo_mode, DEMO_PDF_ARCHIVE_DIR, DEMO_SHIPPING_PDF_ARCHIVE_DIR,
    DEMO_CONTRACTOR_VOUCHER_PDF_ARCHIVE_DIR, DEMO_INVOICE_VOUCHER_PDF_ARCHIVE_DIR,
    DEMO_PAYMENT_REQUEST_PDF_ARCHIVE_DIR, DEMO_CASE_CLOSING_PDF_ARCHIVE_DIR,
)
from helpers import _get_edge_path, _get_setting, payment_item_amounts, notify_case_closing_report, run_edge_pdf

from core import paths as _paths

logger = logging.getLogger(__name__)

_PDF_BASE_DEFAULT = _paths.PDF_ARCHIVES["quotation"][1]

_SHIPPING_PDF_BASE_DEFAULT = _paths.PDF_ARCHIVES["shipping"][1]


def _get_pdf_base() -> str:
    # demo 帳號：一律存至隔離目錄（reset_demo_db() 每次登入清空），
    # 絕不寫入真實設定的 pdf_base_path（可能是公司共用網路磁碟）
    if is_demo_mode():
        return DEMO_PDF_ARCHIVE_DIR
    configured = (_get_setting("pdf_base_path") or "").strip()
    return configured if configured else _PDF_BASE_DEFAULT


def _get_shipping_pdf_base() -> str:
    if is_demo_mode():
        return DEMO_SHIPPING_PDF_ARCHIVE_DIR
    configured = (_get_setting("shipping_pdf_base_path") or "").strip()
    return configured if configured else _SHIPPING_PDF_BASE_DEFAULT


_CONTRACTOR_VOUCHER_PDF_BASE_DEFAULT = _paths.PDF_ARCHIVES["contractor_voucher"][1]

_INVOICE_VOUCHER_PDF_BASE_DEFAULT = _paths.PDF_ARCHIVES["invoice_voucher"][1]


def _get_contractor_voucher_pdf_base() -> str:
    if is_demo_mode():
        return DEMO_CONTRACTOR_VOUCHER_PDF_ARCHIVE_DIR
    configured = (_get_setting("contractor_voucher_pdf_base_path") or "").strip()
    return configured if configured else _CONTRACTOR_VOUCHER_PDF_BASE_DEFAULT


def _get_invoice_voucher_pdf_base() -> str:
    if is_demo_mode():
        return DEMO_INVOICE_VOUCHER_PDF_ARCHIVE_DIR
    configured = (_get_setting("invoice_voucher_pdf_base_path") or "").strip()
    return configured if configured else _INVOICE_VOUCHER_PDF_BASE_DEFAULT


_PAYMENT_REQUEST_PDF_BASE_DEFAULT = _paths.PDF_ARCHIVES["payment_request"][1]


def _get_payment_request_pdf_base() -> str:
    if is_demo_mode():
        return DEMO_PAYMENT_REQUEST_PDF_ARCHIVE_DIR
    configured = (_get_setting("payment_request_pdf_base_path") or "").strip()
    return configured if configured else _PAYMENT_REQUEST_PDF_BASE_DEFAULT


_CASE_CLOSING_PDF_BASE_DEFAULT = _paths.PDF_ARCHIVES["case_closing"][1]


def _get_case_closing_pdf_base() -> str:
    if is_demo_mode():
        return DEMO_CASE_CLOSING_PDF_ARCHIVE_DIR
    configured = (_get_setting("case_closing_pdf_base_path") or "").strip()
    return configured if configured else _CASE_CLOSING_PDF_BASE_DEFAULT


def _tax_line_label(q: dict) -> str:
    """報價 PDF 稅額那一行的標籤（AC1）：依稅別；舊 1～4% 單照舊寫稅率。"""
    from helpers.quotations import quote_tax_type
    kind = quote_tax_type(q)
    if kind == "zero":
        return "營業稅（零稅率）"
    if kind == "exempt":
        return "免稅"
    return "營業稅 %s%%" % q.get("taxRate", 5)


def _build_quote_html(q: dict, tot: dict, internal: bool = False,
                      show_watermark: bool = False, watermark_text: str = '未成案 · 報價單僅供瀏覽',
                      watermark_font_size: int = 30,
                      show_notice: bool = False, notice_text: str = '') -> str:
    # 🔑 QL7：抬頭從**這一筆單據所屬的據點**取值，一支函式取一次。
    # ⚠️ 取不到 `locationId` ⇒ `location_identity(None)` 落在主要據點，
    #    那是既有安裝（只有一個據點、或根本沒設過）的正確行為。
    # 🔴 `QL25`（依據使用者 2026-09-23 裁示，翻掉這一段原本的 `QL10`
    #    註解——**只對報價單**，`QL10` 本身沒有被推翻，見下）：
    #    報價單回答的是「**當初報的是什麼**」，與薪資單（`QL16`）同一類，
    #    要在送出那一刻凍結，不是每次重印都變。`apply_snapshot()` 疊在
    #    即時值上，只覆蓋抬頭五欄——銀行四欄**這裡本來就沒有**（報價單
    #    版型沒有匯款帳號欄位，`QL10` 管的是請款單那幾支，原封不動）。
    _ident = apply_snapshot(location_identity(_location_of(q)), q)
    def esc(s):
        return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')
    ps = q.get('pdfShow') or {}

    items = q.get('items', [])
    has_notes = any((it.get('notes') or '').strip() for it in items if it.get('type') != 'header')
    item_rows = ''
    real_idx = 0
    for i, item in enumerate(items):
        if item.get('type') == 'header':
            colspan = (9 if internal else 7) - (0 if has_notes else 1)
            item_rows += (
                f'<tr style="background:#EFF6FF">'
                f'<td style="text-align:center;color:#93C5FD;font-size:10px">§</td>'
                f'<td colspan="{colspan}" style="font-weight:700;font-size:12px;color:#1D4ED8;padding:6px 8px">'
                f'{esc(item.get("description",""))}</td>'
                f'</tr>'
            )
            continue
        real_idx += 1
        up  = item.get('unitPrice', 0)
        amt = item.get('amount', 0)
        if internal:
            cost   = item.get('cost', 0) or 0
            margin = item.get('margin', 0) or 0
            item_rows += (
                f'<tr>'
                f'<td>{real_idx}</td>'
                f'<td>{esc(item.get("description",""))}</td>'
                f'<td>{esc(item.get("brand",""))}</td>'
                f'<td class="r">{item.get("qty","")}</td>'
                f'<td>{esc(item.get("unit",""))}</td>'
                f'<td class="r cost-cell">{("NT$ " + f"{int(cost):,}") if cost else ""}</td>'
                f'<td class="r cost-cell">{f"{margin*100:.1f}%" if margin else ""}</td>'
                f'<td class="r">{("NT$ " + f"{int(up):,}") if up else ""}</td>'
                f'<td class="r">{("NT$ " + f"{int(amt):,}") if amt else ""}</td>'
                + (f'<td>{esc(item.get("notes",""))}</td>' if has_notes else '') +
                f'</tr>'
            )
        else:
            item_rows += (
                f'<tr>'
                f'<td>{real_idx}</td>'
                f'<td>{esc(item.get("description",""))}</td>'
                f'<td>{esc(item.get("brand",""))}</td>'
                f'<td class="r">{item.get("qty","")}</td>'
                f'<td>{esc(item.get("unit",""))}</td>'
                f'<td class="r">{("NT$ " + f"{int(up):,}") if up else ""}</td>'
                f'<td class="r">{("NT$ " + f"{int(amt):,}") if amt else ""}</td>'
                + (f'<td>{esc(item.get("notes",""))}</td>' if has_notes else '') +
                f'</tr>'
            )

    subtotal = tot.get('subtotal', 0)
    pretax   = tot.get('pretax', 0)
    tax      = tot.get('tax', 0)
    total    = tot.get('total', 0)
    freight  = q.get('freight', 0) or 0
    discount = q.get('discount', 0) or 0

    freight_row  = f'<div class="total-row"><span>運費</span><span>NT$ {int(freight):,}</span></div>' if freight else ''
    discount_row = f'<div class="total-row"><span style="color:#DC2626">折讓</span><span style="color:#DC2626">-NT$ {int(discount):,}</span></div>' if discount else ''

    def term_block(title, text, span_full=False):
        t = (text or '').strip()
        if not t:
            return ''
        cls = 'term-item term-item--full' if span_full else 'term-item'
        return f'<div class="{cls}"><div class="term-title">{esc(title)}</div><div class="term-block">{esc(t)}</div></div>'

    # 雙欄排版（2026-08-26 視覺優化）：付款/交貨一排、保固/售後一排，篇幅通常
    # 最長的驗收標準獨立跨欄滿版，避免跟另一欄長度差太多造成版面失衡。
    terms_html  = term_block('付款條件', q.get('paymentTerms', ''))
    terms_html += term_block('交貨條件', q.get('deliveryTerms', ''))
    terms_html += term_block('保固條件', q.get('warrantyTerms', ''))
    terms_html += term_block('售後服務', q.get('afterSales', ''))
    terms_html += term_block('驗收標準', q.get('acceptanceTerms', ''), span_full=True)

    terms_section = (
        '<div class="terms"><div class="section-label" style="margin-bottom:8px">五、報價條件</div>'
        f'<div class="terms-grid">{terms_html}</div></div>'
    ) if terms_html.strip() else ''

    return (
        '<!DOCTYPE html>\n'
        '<html lang="zh-Hant">\n'
        '<head>\n'
        '<meta charset="UTF-8">\n'
        f'<title>{esc(q.get("quoteNo",""))} 報價單</title>\n'
        '<style>\n'
        '  *{box-sizing:border-box;margin:0;padding:0}\n'
        '  body{font-family:"Microsoft JhengHei","PMingLiU",serif;font-size:13px;color:#0A0A0A;line-height:1.6;background:#fff}\n'
        '  #root{padding:24px 32px}\n'
        '  @page{size:A4;margin:0 13mm 12mm 13mm;'
        '@bottom-left{content:none}@bottom-right{content:none}'
        '@bottom-center{content:counter(page);font-family:Arial,sans-serif;font-size:9px;color:#aaa}}\n'
        '  @media print{html,body{margin:0;padding:0;background:#fff}#root{padding:15mm 0 0}.sign{page-break-inside:avoid}.totals{page-break-inside:avoid}.totals-group{page-break-inside:avoid}.terms{page-break-inside:avoid}tr{page-break-inside:avoid}}\n'
        '  .cost-cell{background:#FFF8F0}\n'
        '  .cost-banner{background:#FFF3E0;border:1px solid #F59E0B;border-radius:4px;padding:6px 12px;font-size:10px;color:#92400E;margin-bottom:10px;font-family:Arial,sans-serif;letter-spacing:.04em}\n'
        '  .accent-bar{height:3px;background:#0A0A0A;margin-bottom:18px}\n'
        '  .header{display:flex;justify-content:space-between;align-items:flex-start;padding-bottom:14px;border-bottom:1px solid #0A0A0A;margin-bottom:16px}\n'
        '  .co-name{font-size:15px;font-weight:700;letter-spacing:.06em}\n'
        '  .co-sub{font-size:10px;color:#888;margin-top:3px;font-family:Arial,sans-serif;letter-spacing:.02em}\n'
        '  .doc-title{font-size:24px;font-weight:700;letter-spacing:.24em;text-align:right}\n'
        '  .meta{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;margin-bottom:12px;font-size:12px;background:#FAFAF8;padding:10px 12px;border-radius:4px;border:1px solid #EDEAE4}\n'
        '  .meta span{color:#888;font-family:Arial,sans-serif;font-size:11px}\n'
        '  .boxes{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}\n'
        '  .box{background:#FAFAF8;border:1px solid #EDEAE4;border-radius:4px;padding:9px 12px}\n'
        '  .box-title{font-size:9px;font-family:Arial,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:#999;font-weight:600;margin-bottom:6px}\n'
        '  .row{display:flex;gap:6px;margin-bottom:3px;font-size:12px}\n'
        '  .label{color:#888;min-width:72px;flex-shrink:0;font-size:11px}\n'
        '  .val{color:#0A0A0A;font-weight:500}\n'
        '  .section-label{font-size:9px;font-family:Arial,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:#999;font-weight:600;margin-bottom:7px;display:flex;align-items:center;gap:8px}\n'
        '  .section-label::after{content:"";flex:1;height:1px;background:#EDEAE4}\n'
        '  table{width:100%;border-collapse:collapse;margin-bottom:14px}\n'
        '  thead th{background:#0A0A0A;color:#F5F4F0;padding:8px 9px;text-align:center;font-size:11px;font-weight:500;font-family:Arial,sans-serif;letter-spacing:.04em}\n'
        '  thead th.r{text-align:center}\n'
        '  tbody td{padding:8px 9px;border-bottom:1px solid #EDEAE4;font-size:12px;text-align:center}\n'
        '  tbody tr:last-child td{border-bottom:none}\n'
        '  tbody tr:nth-child(even) td{background:#FAFAF8}\n'
        '  td.r{text-align:center;font-family:Arial,sans-serif}\n'
        '  .totals{max-width:290px;margin-left:auto;border:1px solid #EDEAE4;border-radius:4px;overflow:hidden;margin-bottom:16px}\n'
        '  .total-row{display:flex;justify-content:space-between;padding:7px 13px;border-bottom:1px solid #F0EEE9;font-size:12px}\n'
        '  .total-row:last-child{border-bottom:none;font-weight:700;font-size:14px;background:#F5F4F0;border-top:1.5px solid #0A0A0A}\n'
        '  .total-row span:last-child{font-family:Arial,sans-serif}\n'
        '  .terms{margin-bottom:16px}\n'
        '  .terms-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}\n'
        '  .term-item{background:#FAFAF8;border:1px solid #EDEAE4;border-radius:4px;padding:9px 12px}\n'
        '  .term-item--full{grid-column:1/-1}\n'
        '  .term-block{font-size:9px;color:#666;line-height:1.6}\n'
        '  .term-title{font-size:9px;color:#999;font-weight:600;font-family:Arial,sans-serif;letter-spacing:.1em;text-transform:uppercase;margin-bottom:4px}\n'
        '  .sign{max-width:52%;margin-top:0}\n'
        '  .sign-box{border:1px solid #EDEAE4;border-radius:4px;padding:16px 18px;min-height:100px;display:flex;flex-direction:column}\n'
        '  .sign-label{font-size:9px;color:#999;font-family:Arial,sans-serif;letter-spacing:.1em;text-transform:uppercase;margin-bottom:8px}\n'
        '  .footer{text-align:center;font-size:10px;color:#999;margin-top:18px;padding-top:12px;border-top:1px solid #EDEAE4;font-family:Arial,sans-serif;letter-spacing:.04em}\n'
        + (
        '  .wm-overlay{position:fixed;top:-30%;left:-30%;width:160%;height:160%;'
        'display:flex;flex-direction:column;gap:56px;transform:rotate(-30deg);'
        'pointer-events:none;z-index:9999;overflow:hidden}\n'
        f'  .wm-row{{display:flex;gap:48px;white-space:nowrap;font-size:{watermark_font_size}px;font-weight:800;'
        'color:rgba(0,0,0,.08);font-family:"Microsoft JhengHei",Arial,sans-serif;letter-spacing:.06em}}\n'
        '  @media print{.wm-overlay{position:fixed}}\n'
        if show_watermark else '')
        + (
        '  .notice-bar{background:#FEE2E2;border:1.5px solid #FCA5A5;border-radius:5px;'
        'padding:9px 14px;margin-bottom:14px;display:flex;align-items:center;gap:8px;'
        'color:#DC2626;font-size:12px;font-weight:700;font-family:"Microsoft JhengHei",Arial,sans-serif;'
        'letter-spacing:.04em}\n'
        '  @media print{.notice-bar{-webkit-print-color-adjust:exact;print-color-adjust:exact}}\n'
        if show_notice else '')
        + '</style>\n'
        '</head>\n'
        '<body>\n'
        + (
        '<div class="wm-overlay">'
        + (''.join(f'<div class="wm-row">'
                   + (f'<span>{watermark_text}</span>' * 6)
                   + '</div>' for _ in range(10)))
        + '</div>\n'
        if show_watermark else '')
        + '<div id="root">\n'
        '<div class="accent-bar"></div>\n'
        + (
        f'<div class="notice-bar">'
        f'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">'
        f'<path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>'
        f'<line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
        f'{notice_text}</div>\n'
        if show_notice else '')
        + '<div class="header">\n'
        '  <div>\n'
        + _identity_head(_ident) +
        '  </div>\n'
        '  <div>\n'
        '    <div class="doc-title">報　價　單</div>\n'
        '  </div>\n'
        '</div>\n'
        '<div class="meta">\n'
        f'  <div><span>報價編號：</span><strong style="font-family:Arial,sans-serif">{esc(q.get("quoteNo",""))}</strong></div>\n'
        f'  <div><span>報價日期：</span>{esc(q.get("quoteDate",""))}</div>\n'
        f'  <div><span>有效期限：</span>{q.get("validDays",30)} 日內</div>\n'
        f'  <div><span>報　價　人：</span>{esc(q.get("salesPerson",""))}</div>\n'
        f'  <div><span>電　　　話：</span>{esc(q.get("salesPhone",""))}</div>\n'
        f'  <div><span>E-mail：</span>{esc(q.get("salesEmail",""))}</div>\n'
        '</div>\n'
        '<div class="boxes">\n'
        '  <div class="box">\n'
        '    <div class="box-title">一、客戶資訊</div>\n'
        f'    <div class="row"><span class="label">公司名稱</span><span class="val">{esc(q.get("customerName",""))}</span></div>\n'
        + (f'    <div class="row"><span class="label">統一編號</span><span class="val">{esc(q.get("customerTaxId",""))}</span></div>\n' if ps.get('taxId', True) else '')
        + (f'    <div class="row"><span class="label">聯絡人</span><span class="val">{esc(q.get("contactName",""))}</span></div>\n' if ps.get('contactName', True) else '')
        + (f'    <div class="row"><span class="label">電話 / 分機</span><span class="val">{esc(q.get("contactPhone",""))}</span></div>\n' if ps.get('contactPhone', True) else '')
        + (f'    <div class="row"><span class="label">E-mail</span><span class="val">{esc(q.get("contactEmail",""))}</span></div>\n' if ps.get('contactEmail', True) else '')
        + (f'    <div class="row"><span class="label">傳真</span><span class="val">{esc(q.get("contactFax",""))}</span></div>\n' if ps.get('contactFax', False) else '')
        + (f'    <div class="row"><span class="label">送貨地址</span><span class="val">{esc(q.get("deliveryAddress",""))}</span></div>\n' if ps.get('deliveryAddress', True) else '')
        + '  </div>\n'
        '  <div class="box">\n'
        '    <div class="box-title">二、案件資訊</div>\n'
        f'    <div class="row"><span class="label">案件名稱</span><span class="val">{esc(q.get("projectName",""))}</span></div>\n'
        f'    <div class="row"><span class="label">交貨地點</span><span class="val">{esc(q.get("deliveryLocation",""))}</span></div>\n'
        '  </div>\n'
        '</div>\n'
        + (f'<div class="cost-banner">⚠ 內部版（含成本）— 請勿對外提供</div>\n' if internal else '')
        + '<div class="section-label">三、項目明細</div>\n'
        '<table>\n'
        '  <thead>\n'
        '    <tr>\n'
        '      <th style="width:28px">#</th>\n'
        '      <th style="width:190px">品名 / 規格說明</th>\n'
        '      <th style="width:110px">廠牌 / 型號</th>\n'
        '      <th class="r" style="width:48px">數量</th>\n'
        '      <th style="width:70px">單位</th>\n'
        + ('      <th class="r cost-cell" style="width:100px">單位成本</th>\n'
           '      <th class="r cost-cell" style="width:64px">毛利率</th>\n' if internal else '')
        + '      <th class="r" style="width:120px">單價（未稅額）</th>\n'
        '      <th class="r" style="width:120px">金額（未稅）</th>\n'
        + ('      <th style="width:72px">備註</th>\n' if has_notes else '')
        + '    </tr>\n'
        '  </thead>\n'
        + f'  <tbody>{item_rows}</tbody>\n'
        '</table>\n'
        '<div class="totals-group">\n'
        '<div class="section-label" style="margin-bottom:8px;margin-top:14px;color:#666">四、報價合計</div>\n'
        '<div class="totals">\n'
        f'  <div class="total-row"><span>品項小計</span><span>NT$ {int(subtotal):,}</span></div>\n'
        f'  {freight_row}\n'
        f'  {discount_row}\n'
        f'  <div class="total-row"><span>稅前合計</span><span>NT$ {int(pretax):,}</span></div>\n'
        f'  <div class="total-row"><span>{_tax_line_label(q)}</span><span>NT$ {int(tax):,}</span></div>\n'
        f'  <div class="total-row"><span>總　計</span><span>NT$ {int(total):,}</span></div>\n'
        '</div>\n'
        '</div>\n'
        f'{terms_section}\n'
        '<div style="height:32px"></div>\n'
        '<div class="sign">\n'
        '  <div class="sign-box">\n'
        '    <div class="sign-label">買方確認 · 簽章</div>\n'
        f'    <div style="font-size:12px;color:#333;flex:1">{esc(q.get("customerName",""))}</div>\n'
        '  </div>\n'
        '</div>\n'
        '<div class="footer">\n'
        + _identity_foot(_ident) +
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


def _pdf_audit(quote_no: str, success: bool, detail: str = "", actor: str = "", action_type: str = ""):
    try:
        conn = get_db()
        now  = datetime.now().isoformat()
        label = f"{quote_no} PDF {'生成成功' if success else '生成失敗'}"
        if action_type:
            label = f"{quote_no}【{action_type}】PDF {'生成成功' if success else '生成失敗'}"
        conn.execute(
            "INSERT INTO audit_log "
            "(at, username, display_name, action, target_type, target_id, target_label, detail) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (now, actor or "system", actor or "系統自動", "pdf.auto_generate", "quotation", quote_no,
             label,
             json.dumps({"success": success, "detail": detail, "actor": actor, "actionType": action_type},
                        ensure_ascii=False))
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── 單據版本索引（2026-09-14 使用者要求：「產生當下自動備存一個，如果有編修，
#    需保留原始單據跟編輯紀錄在系統」）────────────────────────────────────────
#
# 存檔的 PDF 本來就一直都在（`{pdf_base}/{YYYY-MM-DD}/` 底下），問題是**系統裡
# 查不到**：唯一的紀錄在 audit_log 的 `pdf.auto_generate` detail 裡，而 audit_log
# 有 730 天保留期（archive._prune_audit_log），兩年後索引會消失、檔案卻還在，
# 等於有備存卻找不到。而且沒有任何頁面列得出「這張單有哪幾個版本」。
#
# 改成把索引寫進報價單自己的 data_json.docVersions[]：
#   ・跟著單據走，單據在索引就在，不受 audit_log 保留期影響
#   ・自動被每日 JSON 備份與整庫備份收錄（不需要另外處理）
#   ・不需要新資料表（比照 editHistory 的既有慣例）
#
# 路徑**存相對於 PDF base 的相對路徑**，不是絕對路徑——superadmin 可以改
# `pdf_base_path`（可能指到公司共用網路碟），存絕對路徑會在改設定那天整批失效。

_DOC_VERSION_MAX = 500      # 單張單據的版本索引上限，防病態情況把 data_json 撐爆


def _record_doc_version(quote_no: str, action_type: str, actor: str,
                        pdf_path: str) -> None:
    """把剛存好的 PDF 追加進 quotations.data_json 的 docVersions[]。

    失敗一律吞掉（只留 log）：PDF 已經實際存在磁碟上了，索引寫不進去是可惜、
    不是災難，不該讓它把呼叫端的背景執行緒炸掉。

    併發：PDF 產生由 EDGE_PDF_SEMAPHORE 節流，同一張單同時跑兩份的機會很低，
    但仍用 BEGIN IMMEDIATE 把「讀-改-寫」包成一個寫入交易，避免兩個背景執行緒
    同時讀到同一份 data_json、後寫的把前一筆版本紀錄蓋掉。
    """
    try:
        base = _get_pdf_base()
        try:
            rel = os.path.relpath(pdf_path, base)
        except ValueError:          # 跨磁碟機時 relpath 會炸
            rel = os.path.basename(pdf_path)

        conn = get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
            if not row:
                conn.rollback()
                return
            data = json.loads(row["data_json"] or "{}")
            versions = data.get("docVersions")
            if not isinstance(versions, list):
                versions = []
            versions.append({
                "seq":       len(versions) + 1,
                "at":        datetime.now().isoformat(),
                "event":     action_type,
                "by":        actor or "",
                "file":      rel.replace("\\", "/"),
                "size":      os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0,
            })
            data["docVersions"] = versions[-_DOC_VERSION_MAX:]
            conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?",
                         (json.dumps(data, ensure_ascii=False), quote_no))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception("_record_doc_version failed for %s", quote_no)


def _quote_watermark_kwargs(status: str, deal_tag: str) -> dict:
    """報價單浮水印／提示的規則（2026-09-24 抽出）：PDF 與畫面預覽共用同一份，
    兩邊才不會各自判斷而長得不一樣。"""
    show_wm      = (deal_tag == "未成案") or (status != "已送出")
    is_unsettled = deal_tag == "未成案"
    return dict(
        show_watermark=show_wm,
        watermark_text="本案報價未成立　僅供存查備存" if is_unsettled else "報價單預覽稿　尚未正式生效",
        watermark_font_size=18 if is_unsettled else 28,
        show_notice=is_unsettled,
        notice_text="本案報價未成立，此份文件僅供存查備存使用，請勿對外提供或引用",
    )


def build_quote_preview_html(q: dict, status: str, deal_tag: str, internal: bool = False) -> str:
    """畫面預覽用：與 generate_pdf_bytes() 產生 PDF 的 HTML 是同一支 builder、同一組浮水印規則。
    （2026-09-24：原本預覽是前端另畫一份版面，與 PDF 有 9 處可見差異。）"""
    html = _build_quote_html(q, q.get("tot", {}) or {}, internal=internal,
                             **_quote_watermark_kwargs(status or "", deal_tag or ""))
    # 預覽顯示在 sandbox iframe（不同源），主頁量不到內容高度 ⇒ 由內容回報。
    # 只加在預覽，PDF 那份 HTML 不含這段；它不改變版面。
    report = ('<script>window.addEventListener("load",function(){setTimeout(function(){'
              'var r=document.documentElement;var z=parseFloat(document.body.style.zoom||"1")||1;'
              'parent.postMessage({motrixPreviewHeight:r.scrollHeight*z},"*")},0)});</script>')
    return html.replace("</body>", report + "</body>", 1) if "</body>" in html else html + report


def generate_pdf_bytes(quote_no: str, internal: bool = False) -> bytes:
    """Edge Headless 產生 PDF 並以 bytes 回傳（供 API 下載使用）。"""
    edge = _get_edge_path()
    conn = get_db()
    row  = conn.execute(
        # QL7：`location_id` 是**欄位**，不在 `data_json` 裡 —— 不撈的話
        # 8 支 builder 拿到的永遠是空的，而每一份真實單據都印總公司抬頭。
        "SELECT data_json, status, deal_tag, location_id FROM quotations "
        "WHERE quote_no=?", (quote_no,)
    ).fetchone()
    conn.close()
    if not row:
        raise ValueError("報價單不存在")
    q            = json.loads(row["data_json"] or "{}")
    # 用欄位覆蓋 payload：`data_json` 裡若有舊的 `locationId`，**欄位才是權威**。
    q["locationId"] = row["location_id"] or ""
    deal_tag     = row["deal_tag"] or q.get("dealTag") or ""
    status       = row["status"] or ""
    html_content = _build_quote_html(q, q.get("tot", {}), internal=internal,
                                     **_quote_watermark_kwargs(status, deal_tag))
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
                try: os.unlink(p)
                except Exception: pass


# ── 勞報單 PDF ────────────────────────────────────────────────────────────────

# §9 QL：單據抬頭從據點取值。**解析不在這個檔裡** ——
# `pdf_gen.py` 不可以知道 `company_profile` 的地址結構（BR2b），
# 所以它只 import 一個函式，問「這份單的抬頭是什麼」。
# ⚠️ 用 `from ... import` 而不是 `import module`：這幾支要留在本模組的
# 命名空間裡，C 的題用 `monkeypatch.setattr(pdf_gen, "location_identity", …)`
# 換掉它們來驗「8 支 builder 有沒有真的去取值」。
from helpers.company_identity import (      # noqa: E402
    DEFAULT_IDENTITY, location_identity, _location_of, apply_snapshot,
)


def _identity_head(ident: dict) -> str:
    """單據抬頭那三行。**縮排與字元逐字保留改版前的樣子**（QL6）。

    ⚠️ 第三行的分隔符是**全形空白 ＋ ｜**，不是半形 ——
    ☠️ 換成半形的話所有既有單據的那一行都會變，而沒有人會說得出是哪一次改的。
    """
    third = "統一編號：%s　｜　電話：%s　｜　%s" % (
        ident.get("tax_id", ""), ident.get("phone", ""), ident.get("email", ""))
    return (
        '    <div class="co-name">%s</div>\n'
        '    <div class="co-sub">%s</div>\n'
        '    <div class="co-sub" style="margin-top:4px">%s</div>\n'
        % (ident.get("company_name", ""), ident.get("company_name_en", ""),
           third))


def _identity_foot(ident: dict) -> str:
    """頁尾那一行（完整版：英文名 ＋ 中文名 ｜ email ｜ Tel ｜ 統編）。"""
    return "  %s %s ｜ %s ｜ Tel: %s ｜ 統一編號: %s\n" % (
        ident.get("company_name_en", ""),
        # ⚠️ 頁尾用的是**不含「股份有限公司」的短名**。改版前寫死的是「允碩整合集創」，
        # 🔑 而那是 `company_name` 去掉尾綴 —— 這裡只去掉既有那幾種尾綴，
        #    使用者自己填的名字原樣印出去，不要替他猜。
        _short_name(ident.get("company_name", "")),
        ident.get("email", ""), ident.get("phone", ""), ident.get("tax_id", ""))


def _identity_foot_short(ident: dict) -> str:
    """頁尾那一行（短版：只有英文名與中文短名）。"""
    return "%s %s\n</div>\n" % (
        ident.get("company_name_en", ""),
        _short_name(ident.get("company_name", "")))


#: 頁尾短名（2026-09-25 A8c：移到 helpers/company_identity.short_name，唯一來源）
from helpers.company_identity import short_name as _short_name  # noqa: E402


def _build_payslip_html(d: dict) -> str:
    def esc(s): return (s or '').replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('\n','<br>')
    def amt(n): return f"NT$ {int(n):,}" if n else "NT$ 0"
    def pct(r): return (f"{r*100:.2f}".rstrip('0').rstrip('.') + '%') if r else '0%'

    # QL16：薪資單的抬頭**繼續讀開單時的快照**（`payslips.data_json`）。
    #
    # 判準是**這份單據有沒有已經交到外面的人手上**（A 2026-09-22 裁定）：
    # 薪資單已經交給員工，員工可能拿去報稅或貸款
    # => 重印**必須重現當初發出去的那一份**，公司改名搬家之後也一樣。
    # QL10（讀即時值）套的是還在流程裡的案件文件 ——
    # 匯款帳號要回答「**現在**該匯到哪」，而薪資單的抬頭回答的是
    # 「**當初是誰付的**」。**那不是同一個問題。**
    company  = d.get('companyName', '')
    tax_id   = d.get('companyTaxId', '')
    contact  = d.get('companyContactInfo', '')

    # QL17：舊薪資單的 `data_json` 根本**沒有**這三個欄位時怎麼辦。
    #
    # 三條路，A 明著排除了其中兩條：
    #   X 安靜地用即時值補   => 一份看起來像正本、而抬頭是今天的文件。
    #                          **它不會報錯，而它在說謊。**
    #   X 直接拒絕重印       => 擋掉所有舊薪資單的合法重印，代價太大。
    #   O 用即時值，**而且在文件上標明**
    # 〈降級之後它還是會動〉：降級可以，**而降級必須看得見** ——
    # 真正要擋的是「**安靜**」那兩個字，不是「即時值」。
    _reprint_note = ''
    if not (company or tax_id or contact):
        _live = location_identity(None)      # QL8：人事文件沒有所屬據點 => 主要據點
        company = _live.get('company_name', '')
        tax_id = _live.get('tax_id', '')
        contact = '｜'.join(
            x for x in (_live.get('phone', ''), _live.get('email', '')) if x)
        _reprint_note = (
            '<div style="margin:6px 0 10px;padding:6px 10px;border:1px solid #999;'
            'background:#F5F5F5;font-size:8.5pt;color:#333;line-height:1.6">'
            '※ 本件甲方抬頭為<strong>現行</strong>公司資料，'
            '非開單當時的紀錄（這份單據建立時未留存抬頭）。'
            '</div>\n')
    cname    = d.get('contractorName', '')
    cid_no   = d.get('contractorIdNumber', '')
    cphone   = d.get('contractorPhone', '')
    cemail   = d.get('contractorEmail', '')
    caddr    = d.get('contractorAddress', '')
    cnat     = d.get('contractorNationality', '本國籍')
    cunion   = d.get('contractorHasUnionInsurance', False)
    cline    = ''  # LINE ID removed from output

    content  = d.get('serviceContent', '')
    s_start  = d.get('serviceStartDate', '')
    s_end    = d.get('serviceEndDate', '')
    period   = f"{s_start} ～ {s_end}" if s_start and s_end else (s_start or s_end or '—')
    itype    = d.get('incomeType', '')
    isubtype = d.get('incomeSubtype', '')
    slip_date= d.get('slipDate', '')
    slip_no  = d.get('slipNo', '')
    remarks  = d.get('remarks', '')
    gross    = int(d.get('grossAmount', 0))
    pay_m    = d.get('paymentMethod', '匯款')

    calc     = d.get('calc', {})
    tax_w    = int(calc.get('taxWithheld', 0))
    nhi_s    = int(calc.get('nhiSupplement', 0))
    net_a    = int(calc.get('netAmount', gross))
    tax_r    = calc.get('taxRate', 0)
    nhi_r    = calc.get('nhiRate', 0)

    bank_code = d.get('bankCode', '')
    bank_name = d.get('bankName', '')
    bank_bran = d.get('bankBranch', '')
    bank_acct = d.get('bankAccountName', '')
    bank_no   = d.get('bankAccountNumber', '')

    itype_labels = {'50': '50－薪資所得', '9A': '9A－執行業務所得', '9B': '9B－稿費版稅演講鐘點費'}
    itype_label  = itype_labels.get(itype, itype)
    if isubtype: itype_label += f'（{esc(isubtype)}）'

    is_resident = cnat != '外國籍（未滿183天）'
    tax_note = ''
    if tax_w > 0:
        if is_resident:
            tax_note = f'（達起扣門檻，代扣繳 {pct(tax_r)}）'
        else:
            tax_note = f'（非居住者，代扣繳 {pct(tax_r)}）'
    else:
        tax_note = '（未達起扣門檻，免扣繳）'

    nhi_note = ''
    if nhi_s > 0:
        nhi_note = f'（代扣二代健保補充保費 {pct(nhi_r)}）'
    elif cunion:
        nhi_note = '（職業工會投保，免扣二代健保）'
    else:
        nhi_note = '（未達門檻，免扣繳）'

    id_card_front  = d.get('_id_card_front', '')
    id_card_back   = d.get('_id_card_back', '')
    bank_passbook  = d.get('_bank_passbook', '')

    remarks_section = ''
    if remarks:
        remarks_section = (
            '\n<div class="section-title">六、備註</div>'
            f'\n<table><tr><td style="white-space:pre-wrap">{esc(remarks)}</td></tr></table>'
        )

    passbook_section = ''
    if bank_passbook:
        passbook_section = f"""
<div style="page-break-before:always;padding:14mm 14mm 10mm;
            font-family:'微軟正黑體','Microsoft JhengHei',sans-serif;color:#111">
  <div style="font-size:14pt;font-weight:700;letter-spacing:2px;
              border-bottom:2px solid #333;padding-bottom:6px;margin-bottom:14px">
    附件：乙方銀行存簿影本
  </div>
  <table style="width:100%;border-collapse:collapse;font-size:10pt;margin-bottom:14px">
    <tr>
      <th style="background:#f0f0f0;border:1px solid #555;padding:5px 8px;
                 font-weight:600;width:100px;white-space:nowrap">受領人</th>
      <td style="border:1px solid #555;padding:5px 8px">{esc(cname)}</td>
      <th style="background:#f0f0f0;border:1px solid #555;padding:5px 8px;
                 font-weight:600;width:100px;white-space:nowrap">帳號</th>
      <td style="border:1px solid #555;padding:5px 8px;font-family:monospace">{esc(bank_no)}</td>
    </tr>
    <tr>
      <th style="background:#f0f0f0;border:1px solid #555;padding:5px 8px;
                 font-weight:600;white-space:nowrap">銀行／分行</th>
      <td colspan="3" style="border:1px solid #555;padding:5px 8px">{esc(' '.join(x for x in (bank_code, bank_name) if x))}{('／' + esc(bank_bran)) if bank_bran else ''}</td>
    </tr>
    <tr>
      <th style="background:#f0f0f0;border:1px solid #555;padding:5px 8px;
                 font-weight:600;white-space:nowrap">所屬勞報單</th>
      <td colspan="3" style="border:1px solid #555;padding:5px 8px;
                              font-family:monospace">{esc(slip_no)}</td>
    </tr>
  </table>
  <div style="text-align:center">
    <img src="{bank_passbook}" style="max-width:100%;max-height:340px;
         object-fit:contain;border:1px solid #ccc;border-radius:4px">
  </div>
  <div style="text-align:center;font-size:8pt;color:#888;margin-top:8px">
    本影本係依法留存，僅供勞務報酬匯款核對使用
  </div>
</div>"""

    id_card_section = ''
    if id_card_front or id_card_back:
        if id_card_front and id_card_back:
            images_html = (
                '<div style="display:flex;gap:14px">'
                f'<div style="flex:1;text-align:center">'
                f'<img src="{id_card_front}" style="max-width:100%;max-height:220px;'
                f'object-fit:contain;border:1px solid #ccc;border-radius:4px">'
                f'<div style="font-size:9pt;color:#666;margin-top:4px">正面</div></div>'
                f'<div style="flex:1;text-align:center">'
                f'<img src="{id_card_back}" style="max-width:100%;max-height:220px;'
                f'object-fit:contain;border:1px solid #ccc;border-radius:4px">'
                f'<div style="font-size:9pt;color:#666;margin-top:4px">反面</div></div>'
                '</div>'
            )
        else:
            img = id_card_front or id_card_back
            images_html = (
                f'<div style="text-align:center">'
                f'<img src="{img}" style="max-width:100%;max-height:300px;'
                f'object-fit:contain;border:1px solid #ccc;border-radius:4px">'
                f'</div>'
            )
        id_card_section = f"""
<div style="page-break-before:always;padding:14mm 14mm 10mm;
            font-family:'微軟正黑體','Microsoft JhengHei',sans-serif;color:#111">
  <div style="font-size:14pt;font-weight:700;letter-spacing:2px;
              border-bottom:2px solid #333;padding-bottom:6px;margin-bottom:14px">
    附件：乙方身分證影本
  </div>
  <table style="width:100%;border-collapse:collapse;font-size:10pt;margin-bottom:14px">
    <tr>
      <th style="background:#f0f0f0;border:1px solid #555;padding:5px 8px;
                 font-weight:600;width:100px;white-space:nowrap">姓名</th>
      <td style="border:1px solid #555;padding:5px 8px">{esc(cname)}</td>
      <th style="background:#f0f0f0;border:1px solid #555;padding:5px 8px;
                 font-weight:600;width:100px;white-space:nowrap">證件號碼</th>
      <td style="border:1px solid #555;padding:5px 8px">{esc(cid_no)}</td>
    </tr>
    <tr>
      <th style="background:#f0f0f0;border:1px solid #555;padding:5px 8px;
                 font-weight:600;white-space:nowrap">所屬勞報單</th>
      <td colspan="3" style="border:1px solid #555;padding:5px 8px;
                              font-family:monospace">{esc(slip_no)}</td>
    </tr>
  </table>
  {images_html}
  <div style="text-align:center;font-size:8pt;color:#888;margin-top:8px">
    本影本係依法留存，僅供扣繳憑單申報使用
  </div>
</div>"""

    bank_row = ''
    if pay_m == '匯款':
        bank_row = f"""
        <tr><th>匯款銀行</th>
          <td colspan="3">{esc(bank_code)} {esc(bank_name)} {esc(bank_bran)}</td></tr>
        <tr><th>匯款帳戶</th>
          <td colspan="3">戶名：{esc(bank_acct)}｜帳號：{esc(bank_no)}</td></tr>"""

    return f"""<!DOCTYPE html><html lang="zh-TW"><head><meta charset="UTF-8">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
@page{{size:A4;margin:0}}
body{{font-family:"微軟正黑體","Microsoft JhengHei",sans-serif;font-size:11pt;color:#111;background:#fff}}
#root{{padding:14mm 14mm}}
.hdr{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px}}
.hdr-mid{{flex:1;text-align:center}}
h1{{font-size:18pt;font-weight:700;letter-spacing:4px;margin:0 0 2px 0}}
.hdr-info{{text-align:right;font-size:9pt;color:#444;min-width:150px;line-height:1.8;
           border:1px solid #999;padding:5px 8px;border-radius:3px}}
table{{width:100%;border-collapse:collapse;margin-bottom:10px}}
th,td{{border:1px solid #555;padding:5px 8px;vertical-align:top}}
th{{background:#f0f0f0;font-weight:600;width:100px;white-space:nowrap}}
.section-title{{background:#d0d8e8;font-weight:700;font-size:10pt;padding:4px 8px;
                border:1px solid #555;margin-top:8px;margin-bottom:0}}
.amount-row th{{width:160px}}
.amount-row td{{font-size:12pt}}
.net{{background:#fff8e1;font-weight:700;font-size:13pt}}
.note-cell{{font-size:9pt;color:#555}}
.sign{{display:flex;gap:20px;margin-top:14px}}
.sign-box{{flex:1;border:1px solid #555;padding:10px 12px}}
.sign-box .label{{font-size:9pt;color:#555;margin-bottom:4px}}
.sign-line{{height:50px;border-bottom:1px solid #aaa;margin-bottom:4px}}
.sign-name{{font-size:9pt;color:#444}}
.footer{{text-align:center;font-size:8pt;color:#888;margin-top:10px;border-top:1px solid #ccc;padding-top:6px}}
.tag{{display:inline-block;border:1px solid #555;padding:1px 8px;font-size:9pt;margin-right:4px}}
</style></head><body>
<div id="root">
<div class="hdr">
  <div style="min-width:150px"></div>
  <div class="hdr-mid">
    <h1>勞　務　報　酬　單</h1>
    <div style="font-size:9pt;color:#666">{esc(company)}</div>
  </div>
  <div class="hdr-info">
    單號：{esc(slip_no)}<br>
    日期：{esc(slip_date)}
  </div>
</div>

<div class="section-title">一、甲方（給付單位）</div>
{_reprint_note}<table>
  <tr><th>公司名稱</th><td colspan="3">{esc(company)}</td></tr>
  <tr><th>統一編號</th><td>{esc(tax_id)}</td>
      <th>聯絡資訊</th><td>{esc(contact)}</td></tr>
</table>

<div class="section-title">二、乙方（受領報酬人）</div>
<table>
  <tr><th>姓　　名</th><td>{esc(cname)}</td>
      <th>證件號碼</th><td>{esc(cid_no)}</td></tr>
  <tr><th>電　　話</th><td>{esc(cphone)}</td>
      <th>電子信箱</th><td>{esc(cemail)}</td></tr>
  <tr><th>通訊地址</th><td colspan="3">{esc(caddr)}</td></tr>
  <tr><th>國　　籍</th><td colspan="3">{esc(cnat)}</td></tr>
  <tr><th>職業工會</th>
      <td colspan="3">{'<span class="tag">✓ 已投保職業工會</span>' if cunion else '未投保'}</td></tr>
</table>

<div class="section-title">三、勞務內容</div>
<table>
  <tr><th>服務期間</th><td colspan="3">{esc(period)}</td></tr>
  <tr><th>勞務內容</th><td colspan="3">{esc(content)}</td></tr>
  <tr><th>所得類別</th><td colspan="3">{esc(itype_label)}</td></tr>
</table>

<div class="section-title">四、金額明細</div>
<table class="amount-row">
  <tr><th>應付總額</th><td>{amt(gross)}</td><td class="note-cell" colspan="2"></td></tr>
  <tr><th>代扣所得稅</th><td>{amt(tax_w)}</td>
      <td class="note-cell" colspan="2">{esc(tax_note)}</td></tr>
  <tr><th>二代健保費</th><td>{amt(nhi_s)}</td>
      <td class="note-cell" colspan="2">{esc(nhi_note)}</td></tr>
  <tr class="net"><th>實　發　金　額</th><td colspan="3">{amt(net_a)}</td></tr>
</table>

<div class="section-title">五、付款方式</div>
<table>
  <tr><th>付款方式</th><td colspan="3"><span class="tag">{esc(pay_m)}</span></td></tr>
  {bank_row}
</table>
{remarks_section}
<div class="sign">
  <div class="sign-box">
    <div class="label">乙方簽名／蓋章</div>
    <div class="sign-line"></div>
    <div class="sign-name">{esc(cname)}</div>
  </div>
  <div class="sign-box">
    <div class="label">甲方代表人</div>
    <div class="sign-line"></div>
    <div class="sign-name">&nbsp;</div>
  </div>
</div>
<div class="footer">
  {esc(company)}｜統編：{esc(tax_id)}｜{esc(contact)}
</div>
</div>
{id_card_section}
{passbook_section}
<script>
window.addEventListener("load",function(){{
  var r=document.getElementById("root");if(!r)return;
  var A4H=Math.round(297/25.4*96);
  var h=r.scrollHeight;
  if(h>A4H){{var s=A4H/h;if(s>=0.50){{r.style.zoom=s.toFixed(4);}}}}
}});
</script>
</body></html>"""


def generate_payslip_pdf_bytes(slip_no: str) -> bytes:
    edge = _get_edge_path()
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, contractor_id FROM payslips WHERE slip_no=?", (slip_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise ValueError("勞報單不存在")
    id_card_front = ""
    id_card_back  = ""
    bank_passbook = ""
    if row["contractor_id"]:
        con = conn.execute(
            "SELECT id_card_image, id_card_image_back, bank_passbook_image FROM contractors WHERE id=?",
            (row["contractor_id"],)
        ).fetchone()
        if con:
            id_card_front = con["id_card_image"] or ""
            id_card_back  = con["id_card_image_back"] or ""
            bank_passbook = con["bank_passbook_image"] or ""
    conn.close()
    d = json.loads(row["data_json"] or "{}")
    d["_id_card_front"] = id_card_front
    d["_id_card_back"]  = id_card_back
    d["_bank_passbook"] = bank_passbook
    html_content = _build_payslip_html(d)
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
            raise ValueError("Edge 未產生 PDF 檔案")
        with open(tmp_pdf, 'rb') as f:
            return f.read()
    finally:
        for p in (tmp_html, tmp_pdf):
            if p:
                try: os.unlink(p)
                except Exception: pass


def _generate_quotation_pdf(quote_no: str, actor: str = '', action_type: str = '簽核'):
    """
    Generate and save a PDF backup for a quotation.

    actor       — display name of the person who triggered this (approver / editor)
    action_type — one of '簽核', '結案', '修改'

    Filename pattern: {quote_no}_{action_type}_{YYYYMMDD}_{actor}.pdf
    The actor part is omitted when empty.
    """
    try:
        edge = _get_edge_path()
    except RuntimeError as e:
        logger.warning("Edge not found, PDF generation skipped: %s", e)
        _pdf_audit(quote_no, False, str(e), actor, action_type)
        return

    # sanitise actor for Windows filename (strip forbidden chars, limit length)
    safe_actor = re.sub(r'[\\/:*?"<>|\s]', '_', actor or '').strip('_')[:20]

    tmp_html = None
    pdf_path = ""
    try:
        conn = get_db()
        row = conn.execute(
            # QL7：`location_id` 是**欄位**，不在 `data_json` 裡 —— 不撈的話
        # 8 支 builder 拿到的永遠是空的，而每一份真實單據都印總公司抬頭。
        "SELECT data_json, status, deal_tag, location_id FROM quotations "
        "WHERE quote_no=?", (quote_no,)
        ).fetchone()
        conn.close()
        if not row:
            return
        q        = json.loads(row["data_json"] or "{}")
        q["locationId"] = row["location_id"] or ""      # QL7：欄位才是權威
        deal_tag = row["deal_tag"] or q.get("dealTag") or ""
        status   = row["status"] or ""
        show_wm      = (deal_tag == "未成案") or (status != "已送出")
        wm_text      = "本案報價未成立　僅供存查備存" if deal_tag == "未成案" else "報價單預覽稿　尚未正式生效"
        is_unsettled = deal_tag == "未成案"
        tot          = q.get("tot", {})
        html_content = _build_quote_html(q, tot, show_watermark=show_wm, watermark_text=wm_text,
                                         watermark_font_size=18 if is_unsettled else 28,
                                         show_notice=is_unsettled,
                                         notice_text="本案報價未成立，此份文件僅供存查備存使用，請勿對外提供或引用")

        # 時間戳到「秒」（2026-09-14 改）——原本只到「日」，靠 `_2`…`_19` 後綴避開
        # 同日同人的第 2～19 次。**第 20 次會靜默覆蓋掉當天的第一份**：迴圈找不到
        # 空位時 pdf_path 仍是最初那個 base_name.pdf。對「保留原始單據」來說，被蓋
        # 掉的偏偏就是最早、最該留的那一份。帶秒數之後不再需要那個後綴迴圈；
        # 極罕見的同秒撞名仍保留一層數字後綴當保險。
        stamp   = datetime.now().strftime('%Y%m%d_%H%M%S')
        out_dir = os.path.join(_get_pdf_base(), date.today().isoformat())
        os.makedirs(out_dir, exist_ok=True)

        # build filename: MQ-202507-001_已簽核_20260716_143052_Jeff.pdf
        if safe_actor:
            base_name = f"{quote_no}_{action_type}_{stamp}_{safe_actor}"
        else:
            base_name = f"{quote_no}_{action_type}_{stamp}"

        pdf_path = os.path.join(out_dir, f"{base_name}.pdf")
        n = 2
        while os.path.exists(pdf_path):
            pdf_path = os.path.join(out_dir, f"{base_name}_{n}.pdf")
            n += 1

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.html', encoding='utf-8', delete=False
        ) as f:
            f.write(html_content)
            tmp_html = f.name

        file_url = 'file:///' + tmp_html.replace('\\', '/')
        run_edge_pdf(
            [edge, '--headless', '--disable-gpu', '--no-sandbox',
             f'--print-to-pdf={pdf_path}',
             '--no-pdf-header-footer',
             '--run-all-compositor-stages-before-draw',
             file_url]
        )
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
            logger.info("PDF saved: %s", pdf_path)
            _pdf_audit(quote_no, True, pdf_path, actor, action_type)
            _record_doc_version(quote_no, action_type, actor, pdf_path)
        else:
            logger.warning("PDF not created for %s (Edge ran but no output file)", quote_no)
            _pdf_audit(quote_no, False, "Edge 執行完畢但未產生 PDF 檔案", actor, action_type)
    except Exception as e:
        logger.exception("_generate_quotation_pdf failed for %s", quote_no)
        _pdf_audit(quote_no, False, str(e), actor, action_type)
    finally:
        if tmp_html:
            try:
                os.unlink(tmp_html)
            except Exception:
                pass


# ── 出貨單 PDF ────────────────────────────────────────────────────────────────

def _build_shipping_html(n: dict) -> str:
    # 🔑 QL7：抬頭從**這一筆單據所屬的據點**取值，一支函式取一次。
    # ⚠️ 取不到 `locationId` ⇒ `location_identity(None)` 落在主要據點，
    #    那是既有安裝（只有一個據點、或根本沒設過）的正確行為。
    # 🔴 `QL25`（依據使用者 2026-09-23 裁示）：這份單據的抬頭要跟著
    #    報價單送出那一刻凍結的快照走（若有）——`apply_snapshot()` 疊
    #    在即時值上，只覆蓋抬頭五欄。銀行欄位不受影響：`QL10` 沒有被
    #    翻掉，它管的是別的欄位，此處若有銀行欄位仍然一律即時值。
    _ident = apply_snapshot(location_identity(_location_of(n)), n)
    def esc(s):
        return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')

    items = n.get('items', [])
    item_rows = ''
    real_idx = 0
    for item in items:
        if item.get('type') == 'header':
            item_rows += (
                f'<tr style="background:#EFF6FF">'
                f'<td style="text-align:center;color:#93C5FD;font-size:10px">§</td>'
                f'<td colspan="5" style="font-weight:700;font-size:12px;color:#1D4ED8;padding:6px 8px">'
                f'{esc(item.get("description",""))}</td>'
                f'</tr>'
            )
            continue
        real_idx += 1
        item_rows += (
            f'<tr>'
            f'<td>{real_idx}</td>'
            f'<td>{esc(item.get("description",""))}</td>'
            f'<td>{esc(item.get("brand",""))}</td>'
            f'<td class="r">{item.get("qty","")}</td>'
            f'<td>{esc(item.get("unit",""))}</td>'
            f'<td>{esc(item.get("notes",""))}</td>'
            f'</tr>'
        )

    is_signed = bool(n.get('isSigned') or n.get('is_signed'))
    signed_note = ''
    if is_signed:
        signed_by = esc(n.get('signedBy') or n.get('signed_by') or '')
        signed_at = esc((n.get('signedAt') or n.get('signed_at') or '')[:16].replace('T', ' '))
        signed_note = f'<div style="font-size:10px;color:#16A34A;margin-top:6px">✓ 已回簽　{signed_by}　{signed_at}</div>'

    notes = (n.get('notes') or '').strip()
    notes_section = (
        f'<div class="terms"><div class="section-label" style="margin-bottom:8px">備註</div>'
        f'<div class="term-block">{esc(notes)}</div></div>'
    ) if notes else ''

    is_final = n.get('status') == '已核准'
    watermark_html = '' if is_final else (
        '<div class="wm">' + ''.join(
            '<div class="wm-item"><b>出貨單預覽稿</b><small>尚未正式核准</small></div>'
            for _ in range(12)
        ) + '</div>'
    )
    banner_html = '' if is_final else (
        f'<div class="preview-banner">⚠ 此為出貨單預覽稿（目前狀態：{esc(n.get("status") or "草稿")}），'
        f'尚未正式核准，請勿對外提供或引用</div>'
    )

    return (
        '<!DOCTYPE html>\n'
        '<html lang="zh-Hant">\n'
        '<head>\n'
        '<meta charset="UTF-8">\n'
        f'<title>{esc(n.get("noteNo",""))} 出貨單</title>\n'
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
        '  .term-block{font-size:11px;color:#444;line-height:1.8;white-space:pre-wrap}\n'
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
        + _identity_head(_ident) +
        '  </div>\n'
        '  <div>\n'
        '    <div class="doc-title">出　貨　單</div>\n'
        '  </div>\n'
        '</div>\n'
        '<div class="meta">\n'
        f'  <div><span>出貨單號：</span><strong style="font-family:Arial,sans-serif">{esc(n.get("noteNo",""))}</strong></div>\n'
        f'  <div><span>出貨日期：</span>{esc(n.get("shipDate",""))}</div>\n'
        f'  <div><span>關聯報價單：</span>{esc(n.get("quoteNo",""))}</div>\n'
        '</div>\n'
        f'{banner_html}\n'
        '<div class="boxes">\n'
        '  <div class="box">\n'
        '    <div class="box-title">一、客戶資訊</div>\n'
        f'    <div class="row"><span class="label">客戶名稱</span><span class="val">{esc(n.get("customerName",""))}</span></div>\n'
        f'    <div class="row"><span class="label">收件人</span><span class="val">{esc(n.get("recipient",""))}</span></div>\n'
        f'    <div class="row"><span class="label">送貨地址</span><span class="val">{esc(n.get("deliveryAddress",""))}</span></div>\n'
        '  </div>\n'
        '  <div class="box">\n'
        '    <div class="box-title">二、案件資訊</div>\n'
        f'    <div class="row"><span class="label">案件名稱</span><span class="val">{esc(n.get("projectName",""))}</span></div>\n'
        '  </div>\n'
        '</div>\n'
        '<div class="section-label">三、出貨品項</div>\n'
        '<table>\n'
        '  <thead>\n'
        '    <tr>\n'
        '      <th style="width:28px">#</th>\n'
        '      <th>品名 / 規格說明</th>\n'
        '      <th>廠牌 / 型號</th>\n'
        '      <th class="r" style="width:56px">數量</th>\n'
        '      <th style="width:48px">單位</th>\n'
        '      <th style="width:120px">備註</th>\n'
        '    </tr>\n'
        '  </thead>\n'
        + f'  <tbody>{item_rows}</tbody>\n'
        '</table>\n'
        f'{notes_section}\n'
        '<div class="sign">\n'
        '  <div class="sign-box">\n'
        '    <div class="sign-label">客戶簽收 · 簽章</div>\n'
        '    <div class="sign-line"></div>\n'
        f'    <div class="sign-date">簽收日期：＿＿＿＿＿＿＿＿＿＿</div>\n'
        f'    {signed_note}\n'
        '  </div>\n'
        '  <div class="sign-box">\n'
        '    <div class="sign-label">本公司出貨 · 經手人</div>\n'
        '    <div class="sign-line"></div>\n'
        '    <div class="sign-date">出貨日期：＿＿＿＿＿＿＿＿＿＿</div>\n'
        '  </div>\n'
        '</div>\n'
        '<div class="footer">\n'
        + _identity_foot(_ident) +
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


def _shipping_pdf_audit(note_no: str, success: bool, detail: str = "", actor: str = "", action_type: str = ""):
    try:
        conn = get_db()
        now  = datetime.now().isoformat()
        label = f"{note_no} PDF {'生成成功' if success else '生成失敗'}"
        if action_type:
            label = f"{note_no}【{action_type}】PDF {'生成成功' if success else '生成失敗'}"
        conn.execute(
            "INSERT INTO audit_log "
            "(at, username, display_name, action, target_type, target_id, target_label, detail) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (now, actor or "system", actor or "系統自動", "pdf.auto_generate", "shipping_note", note_no,
             label,
             json.dumps({"success": success, "detail": detail, "actor": actor, "actionType": action_type},
                        ensure_ascii=False))
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _shipping_note_dict(row) -> dict:
    n = dict(row)
    n["items"] = json.loads(n.pop("items_json", None) or "[]")
    n["noteNo"] = n.get("note_no", "")
    n["quoteNo"] = n.get("quote_no", "")
    n["shipDate"] = n.get("ship_date", "")
    n["customerName"] = n.get("customer_name", "")
    n["projectName"] = n.get("project_name", "")
    n["deliveryAddress"] = n.get("delivery_address", "")
    n["isSigned"] = bool(n.get("is_signed"))
    n["signedBy"] = n.get("signed_by", "")
    n["signedAt"] = n.get("signed_at", "")
    return n


def generate_shipping_pdf_bytes(note_no: str) -> bytes:
    """Edge Headless 產生出貨單 PDF 並以 bytes 回傳（供 API 下載使用）。"""
    edge = _get_edge_path()
    conn = get_db()
    row  = conn.execute("SELECT * FROM shipping_notes WHERE note_no=?", (note_no,)).fetchone()
    conn.close()
    if not row:
        raise ValueError("出貨單不存在")
    n = _shipping_note_dict(row)
    html_content = _build_shipping_html(n)
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
                try: os.unlink(p)
                except Exception: pass


def _generate_shipping_pdf(note_no: str, actor: str = '', action_type: str = '簽核'):
    """存檔＋稽核版出貨單 PDF 產生，於全部簽核完成後背景觸發。"""
    try:
        edge = _get_edge_path()
    except RuntimeError as e:
        logger.warning("Edge not found, shipping PDF generation skipped: %s", e)
        _shipping_pdf_audit(note_no, False, str(e), actor, action_type)
        return

    safe_actor = re.sub(r'[\\/:*?"<>|\s]', '_', actor or '').strip('_')[:20]

    tmp_html = None
    pdf_path = ""
    try:
        conn = get_db()
        row = conn.execute("SELECT * FROM shipping_notes WHERE note_no=?", (note_no,)).fetchone()
        conn.close()
        if not row:
            return
        n = _shipping_note_dict(row)
        html_content = _build_shipping_html(n)

        today   = date.today().strftime('%Y%m%d')
        out_dir = os.path.join(_get_shipping_pdf_base(), date.today().isoformat())
        os.makedirs(out_dir, exist_ok=True)

        if safe_actor:
            base_name = f"{note_no}_{action_type}_{today}_{safe_actor}"
        else:
            base_name = f"{note_no}_{action_type}_{today}"

        pdf_path = os.path.join(out_dir, f"{base_name}.pdf")
        if os.path.exists(pdf_path):
            for i in range(2, 20):
                candidate = os.path.join(out_dir, f"{base_name}_{i}.pdf")
                if not os.path.exists(candidate):
                    pdf_path = candidate
                    break

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.html', encoding='utf-8', delete=False
        ) as f:
            f.write(html_content)
            tmp_html = f.name

        file_url = 'file:///' + tmp_html.replace('\\', '/')
        run_edge_pdf(
            [edge, '--headless', '--disable-gpu', '--no-sandbox',
             f'--print-to-pdf={pdf_path}',
             '--no-pdf-header-footer',
             '--run-all-compositor-stages-before-draw',
             file_url]
        )
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
            logger.info("Shipping PDF saved: %s", pdf_path)
            _shipping_pdf_audit(note_no, True, pdf_path, actor, action_type)
        else:
            logger.warning("Shipping PDF not created for %s (Edge ran but no output file)", note_no)
            _shipping_pdf_audit(note_no, False, "Edge 執行完畢但未產生 PDF 檔案", actor, action_type)
    except Exception as e:
        logger.exception("_generate_shipping_pdf failed for %s", note_no)
        _shipping_pdf_audit(note_no, False, str(e), actor, action_type)
    finally:
        if tmp_html:
            try:
                os.unlink(tmp_html)
            except Exception:
                pass


# ── 承攬商匯款申請 ────────────────────────────────────────────────────────────

def _voucher_sign_html(appr: dict) -> str:
    """簽核歷程 HTML 區塊，出貨單 PDF 沒有這段（出貨單簽核歷程只存在系統內），
    但財務申請需要在紙本上就能看到完整簽核歷程，故獨立為共用小工具。"""
    def esc(s):
        return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    tiers = (appr or {}).get('tiers') or []
    if not tiers:
        return ''
    rows = ''
    for i, t in enumerate(tiers):
        for a in (t.get('approvers') or []):
            status = a.get('status') or 'pending'
            mark = '✓ 已簽核' if status == 'approved' else '－ 待簽核'
            at = (a.get('approvedAt') or '')[:16].replace('T', ' ')
            rows += (
                f'<tr><td>第 {i+1} 層</td><td>{esc(a.get("displayName") or a.get("username") or "")}</td>'
                f'<td>{mark}</td><td style="font-family:Arial,sans-serif">{esc(at)}</td></tr>'
            )
    return (
        '<div class="section-label">簽核歷程</div>'
        '<table><thead><tr><th>層級</th><th>簽核人</th><th>狀態</th><th>簽核時間</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )


def _build_contractor_voucher_html(v: dict) -> str:
    # 🔑 QL7：抬頭從**這一筆單據所屬的據點**取值，一支函式取一次。
    # ⚠️ 取不到 `locationId` ⇒ `location_identity(None)` 落在主要據點，
    #    那是既有安裝（只有一個據點、或根本沒設過）的正確行為。
    # 🔴 `QL25`（依據使用者 2026-09-23 裁示）：這份單據的抬頭要跟著
    #    報價單送出那一刻凍結的快照走（若有）——`apply_snapshot()` 疊
    #    在即時值上，只覆蓋抬頭五欄。銀行欄位不受影響：`QL10` 沒有被
    #    翻掉，它管的是別的欄位，此處若有銀行欄位仍然一律即時值。
    _ident = apply_snapshot(location_identity(_location_of(v)), v)
    def esc(s):
        return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')
    def money(n):
        return f'{n:,.0f}' if isinstance(n, (int, float)) else '0'

    items = v.get('items') or []
    item_rows = ''
    for i, it in enumerate(items, 1):
        item_rows += (
            f'<tr><td>{i}</td><td>{esc(it.get("description",""))}</td>'
            f'<td class="r">{money(it.get("amount", 0))}</td></tr>'
        )

    def bank_card(title, name_label, name_val, tax_id, bank_code, bank_name, bank_branch,
                  account_name, account_number, passbook, amount_label='', amount_val=None):
        img_html = (
            f'<div style="margin-top:8px"><img src="{esc(passbook)}" '
            f'style="max-width:260px;max-height:160px;border:1px solid #EDEAE4;border-radius:4px;display:block"></div>'
        ) if passbook else ''
        amount_row = (
            f'    <div class="row"><span class="label">{esc(amount_label)}</span>'
            f'<span class="val" style="font-family:Arial,sans-serif">{money(amount_val)}</span></div>\n'
        ) if amount_label else ''
        tax_row = (
            f'    <div class="row"><span class="label">統一編號</span><span class="val">{esc(tax_id)}</span></div>\n'
        ) if tax_id else ''
        return (
            f'  <div class="box">\n    <div class="box-title">{esc(title)}</div>\n'
            f'    <div class="row"><span class="label">{esc(name_label)}</span><span class="val">{esc(name_val)}</span></div>\n'
            f'{tax_row}'
            f'{amount_row}'
            f'    <div class="row"><span class="label">銀行</span><span class="val">{esc(bank_code)} {esc(bank_name)}</span></div>\n'
            f'    <div class="row"><span class="label">分行</span><span class="val">{esc(bank_branch)}</span></div>\n'
            f'    <div class="row"><span class="label">戶名</span><span class="val">{esc(account_name)}</span></div>\n'
            f'    <div class="row"><span class="label">帳號</span><span class="val" style="font-family:Arial,sans-serif">{esc(account_number)}</span></div>\n'
            f'{img_html}\n'
            '  </div>\n'
        )

    personnel = v.get('personnel') or []
    personnel_cards_html = ''
    if personnel:
        cards = ''.join(
            bank_card(
                f'外包人員：{p.get("name","")}', '備註', p.get('note', ''), '',
                p.get('bankCode', ''), p.get('bankName', ''), p.get('bankBranch', ''),
                p.get('bankAccountName', ''), p.get('bankAccountNumber', ''), p.get('bankPassbookImage', ''),
                amount_label='派工金額', amount_val=p.get('amount', 0)
            )
            for p in personnel
        )
        personnel_cards_html = (
            '<div class="section-label">四、外包人員匯款資訊</div>\n'
            f'<div class="boxes" style="grid-template-columns:repeat(2,1fr)">\n{cards}</div>\n'
        )

    applicant_name = (v.get('approval') or {}).get('requestedByDisplay') or v.get('createdBy', '')
    applicant_date = ((v.get('approval') or {}).get('requestedAt') or v.get('createdAt') or '')[:10]

    is_final = v.get('status') == '已核准'
    watermark_html = '' if is_final else (
        '<div class="wm">' + ''.join(
            '<div class="wm-item"><b>申請預覽稿</b><small>尚未正式核准</small></div>'
            for _ in range(12)
        ) + '</div>'
    )
    banner_html = '' if is_final else (
        f'<div class="preview-banner">⚠ 此為承攬商匯款申請預覽稿（目前狀態：{esc(v.get("status") or "草稿")}），'
        f'尚未正式核准，請勿提供財務單位辦理匯款</div>'
    )
    paid_note = ''
    paid_date = ''
    if v.get('isPaid'):
        paid_by = esc(v.get('paidBy') or '')
        paid_at_raw = v.get('paidAt') or ''
        paid_at = esc(paid_at_raw[:16].replace('T', ' '))
        paid_date = esc(paid_at_raw[:10])
        paid_note = f'<div style="font-size:10px;color:#16A34A;margin-top:6px">✓ 已匯款　{paid_by}　{paid_at}</div>'

    return (
        '<!DOCTYPE html>\n<html lang="zh-Hant">\n<head>\n<meta charset="UTF-8">\n'
        f'<title>{esc(v.get("voucherNo",""))} 承攬商匯款申請</title>\n'
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
        '  @page{size:A4;margin:0 13mm 12mm 13mm;@bottom-center{content:counter(page);font-family:Arial,sans-serif;font-size:9px;color:#aaa}}\n'
        '  @media print{html,body{margin:0;padding:0;background:#fff}#root{padding:15mm 0 0}.sign{page-break-inside:avoid}tr{page-break-inside:avoid}}\n'
        '  .accent-bar{height:3px;background:#0A0A0A;margin-bottom:18px}\n'
        '  .header{display:flex;justify-content:space-between;align-items:flex-start;padding-bottom:14px;border-bottom:1px solid #0A0A0A;margin-bottom:16px}\n'
        '  .co-name{font-size:15px;font-weight:700;letter-spacing:.06em}\n'
        '  .co-sub{font-size:10px;color:#888;margin-top:3px;font-family:Arial,sans-serif;letter-spacing:.02em}\n'
        '  .doc-title{font-size:22px;font-weight:700;letter-spacing:.18em;text-align:right}\n'
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
        '  .total-box{display:flex;justify-content:flex-end;margin-bottom:16px}\n'
        '  .total-table{width:280px;font-size:12px}\n'
        '  .total-table .row{display:flex;justify-content:space-between;padding:4px 0}\n'
        '  .total-table .grand{font-size:15px;font-weight:700;border-top:1px solid #0A0A0A;padding-top:8px;margin-top:4px}\n'
        '  .sign{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}\n'
        '  .sign-box{border:1px solid #EDEAE4;border-radius:4px;padding:16px 18px;min-height:110px;display:flex;flex-direction:column}\n'
        '  .sign-label{font-size:9px;color:#999;font-family:Arial,sans-serif;letter-spacing:.1em;text-transform:uppercase;margin-bottom:8px}\n'
        '  .sign-line{flex:1;border-bottom:1px solid #ccc;margin:10px 0}\n'
        '  .sign-date{font-size:10px;color:#999;font-family:Arial,sans-serif}\n'
        '  .footer{text-align:center;font-size:10px;color:#999;margin-top:18px;padding-top:12px;border-top:1px solid #EDEAE4;font-family:Arial,sans-serif;letter-spacing:.04em}\n'
        '</style>\n</head>\n<body>\n<div id="root">\n'
        f'{watermark_html}\n'
        '<div class="accent-bar"></div>\n'
        '<div class="header">\n  <div>\n'
        + _identity_head(_ident) +
        '  </div>\n  <div>\n    <div class="doc-title">承攬商匯款申請</div>\n  </div>\n</div>\n'
        '<div class="meta">\n'
        f'  <div><span>申請單號：</span><strong style="font-family:Arial,sans-serif">{esc(v.get("voucherNo",""))}</strong></div>\n'
        f'  <div><span>建立日期：</span>{esc((v.get("createdAt") or "")[:10])}</div>\n'
        f'  <div><span>關聯案件：</span>{esc(v.get("quoteNo",""))}</div>\n'
        '</div>\n'
        f'{banner_html}\n'
        '<div class="boxes">\n'
        '  <div class="box">\n    <div class="box-title">一、承攬商資訊</div>\n'
        f'    <div class="row"><span class="label">名稱</span><span class="val">{esc(v.get("vendorName","") or "（無承攬商，純外包人員）")}</span></div>\n'
        f'    <div class="row"><span class="label">統一編號</span><span class="val">{esc(v.get("vendorTaxId",""))}</span></div>\n'
        f'    <div class="row"><span class="label">發票號碼</span><span class="val">{esc(v.get("invoiceNo",""))}</span></div>\n'
        f'    <div class="row"><span class="label">應付款日期</span><span class="val">{esc(v.get("payableDate","") or "未指定")}</span></div>\n'
        + (f'    <div class="row"><span class="label">廠商發票</span><span class="val">'
           f'{esc("、".join(f.get("filename","") for f in (v.get("invoiceFiles") or [])))}</span></div>\n'
           if v.get('invoiceFiles') else '')
        + '  </div>\n'
        '  <div class="box">\n    <div class="box-title">二、匯款帳戶資訊</div>\n'
        f'    <div class="row"><span class="label">銀行</span><span class="val">{esc(v.get("bankCode",""))} {esc(v.get("bankName",""))}</span></div>\n'
        f'    <div class="row"><span class="label">分行</span><span class="val">{esc(v.get("bankBranch",""))}</span></div>\n'
        f'    <div class="row"><span class="label">戶名</span><span class="val">{esc(v.get("bankAccountName",""))}</span></div>\n'
        f'    <div class="row"><span class="label">帳號</span><span class="val" style="font-family:Arial,sans-serif">{esc(v.get("bankAccountNumber",""))}</span></div>\n'
        + (f'    <div style="margin-top:8px"><img src="{esc(v.get("bankPassbookImage",""))}" '
           f'style="max-width:260px;max-height:160px;border:1px solid #EDEAE4;border-radius:4px;display:block"></div>\n'
           if v.get('bankPassbookImage') else '')
        + '  </div>\n</div>\n'
        '<div class="section-label">三、派發品項明細</div>\n'
        '<table>\n  <thead><tr><th style="width:28px">#</th><th>品項說明</th><th class="r" style="width:100px">金額</th></tr></thead>\n'
        f'  <tbody>{item_rows}</tbody>\n</table>\n'
        f'{personnel_cards_html}'
        '<div class="total-box"><div class="total-table">\n'
        f'  <div class="row"><span>承攬商未稅小計</span><span style="font-family:Arial,sans-serif">{money(v.get("totalAmount",0))}</span></div>\n'
        f'  <div class="row"><span>營業稅（{round((v.get("taxRate") or 0)*100)}%）</span><span style="font-family:Arial,sans-serif">{money(v.get("taxAmount",0))}</span></div>\n'
        f'  <div class="row"><span>外包人員小計（不計稅）</span><span style="font-family:Arial,sans-serif">{money(v.get("personnelTotal",0))}</span></div>\n'
        f'  <div class="row grand"><span>應付總額</span><span style="font-family:Arial,sans-serif">NT$ {money(v.get("grandTotal",0))}</span></div>\n'
        '</div></div>\n'
        f'{_voucher_sign_html(v.get("approval") or {})}\n'
        '<div class="sign">\n'
        '  <div class="sign-box">\n    <div class="sign-label">財務單位 · 匯款確認</div>\n'
        f'    <div class="sign-line"></div>\n    <div class="sign-date">匯款日期：{paid_date or "＿＿＿＿＿＿＿＿＿＿"}</div>\n'
        f'    {paid_note}\n  </div>\n'
        '  <div class="sign-box">\n    <div class="sign-label">申請人 · 經手人</div>\n'
        f'    <div style="font-size:13px;font-weight:600;color:#0A0A0A;margin:2px 0 8px">{esc(applicant_name)}</div>\n'
        f'    <div class="sign-line"></div>\n    <div class="sign-date">申請日期：{esc(applicant_date) or "＿＿＿＿＿＿＿＿＿＿"}</div>\n  </div>\n'
        '</div>\n'
        '<div class="footer">\n'
        + _identity_foot(_ident) +
        '</div>\n'
        '</div>\n'
        '<script>window.addEventListener("load",function(){var r=document.getElementById("root");if(!r)return;'
        'var A4H=Math.round(267/25.4*96);var h=r.scrollHeight;'
        'if(h>A4H){var s=A4H/h;if(s>=0.70){document.body.style.zoom=s.toFixed(4);}}});</script>\n'
        '</body>\n</html>'
    )


def _voucher_pdf_audit(voucher_no: str, target_type: str, success: bool, detail: str = "",
                       actor: str = "", action_type: str = ""):
    try:
        conn = get_db()
        now  = datetime.now().isoformat()
        label = f"{voucher_no} PDF {'生成成功' if success else '生成失敗'}"
        if action_type:
            label = f"{voucher_no}【{action_type}】PDF {'生成成功' if success else '生成失敗'}"
        conn.execute(
            "INSERT INTO audit_log "
            "(at, username, display_name, action, target_type, target_id, target_label, detail) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (now, actor or "system", actor or "系統自動", "pdf.auto_generate", target_type, voucher_no,
             label,
             json.dumps({"success": success, "detail": detail, "actor": actor, "actionType": action_type},
                        ensure_ascii=False))
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _display_name_for_username(username: str) -> str:
    """建立憑證/申請時只存了帳號名稱（created_by），PDF 上要印顯示名稱不是帳號——
    查無使用者（例如帳號後來被刪除）才退回帳號名稱本身，至少不要整欄空白。"""
    if not username:
        return ""
    try:
        conn = get_db()
        row = conn.execute("SELECT display_name FROM users WHERE username=?", (username,)).fetchone()
        conn.close()
        return (row["display_name"] if row else "") or username
    except Exception:
        return username


def _contractor_voucher_dict(row) -> dict:
    d = dict(row)
    snap = json.loads(d.pop("snapshot_json", None) or "{}")
    appr = (json.loads(d.pop("data_json", None) or "{}") or {}).get("approval") or {}
    out = {**snap}
    out["voucherNo"] = d.get("voucher_no", "")
    out["quoteNo"] = d.get("quote_no", "")
    out["status"] = d.get("status", "")
    out["isPaid"] = bool(d.get("is_paid"))
    out["paidBy"] = d.get("paid_by", "")
    out["paidAt"] = d.get("paid_at", "")
    out["createdBy"] = _display_name_for_username(d.get("created_by", ""))
    out["createdAt"] = d.get("created_at", "")
    out["approval"] = appr
    return out


def generate_contractor_voucher_pdf_bytes(voucher_no: str) -> bytes:
    """Edge Headless 產生承攬商匯款申請 PDF 並以 bytes 回傳（供 API 下載使用）。"""
    edge = _get_edge_path()
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM contractor_payment_vouchers WHERE voucher_no=?", (voucher_no,)
    ).fetchone()
    conn.close()
    if not row:
        raise ValueError("申請不存在")
    v = _contractor_voucher_dict(row)
    html_content = _build_contractor_voucher_html(v)
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
                try: os.unlink(p)
                except Exception: pass


def _generate_contractor_voucher_pdf(voucher_no: str, actor: str = '', action_type: str = '簽核'):
    """存檔＋稽核版承攬商匯款申請 PDF 產生，於全部簽核完成後背景觸發。"""
    try:
        edge = _get_edge_path()
    except RuntimeError as e:
        logger.warning("Edge not found, contractor voucher PDF generation skipped: %s", e)
        _voucher_pdf_audit(voucher_no, "contractor_payment_voucher", False, str(e), actor, action_type)
        return

    safe_actor = re.sub(r'[\\/:*?"<>|\s]', '_', actor or '').strip('_')[:20]
    tmp_html = None
    pdf_path = ""
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM contractor_payment_vouchers WHERE voucher_no=?", (voucher_no,)
        ).fetchone()
        conn.close()
        if not row:
            return
        v = _contractor_voucher_dict(row)
        html_content = _build_contractor_voucher_html(v)

        today   = date.today().strftime('%Y%m%d')
        out_dir = os.path.join(_get_contractor_voucher_pdf_base(), date.today().isoformat())
        os.makedirs(out_dir, exist_ok=True)

        base_name = f"{voucher_no}_{action_type}_{today}_{safe_actor}" if safe_actor \
            else f"{voucher_no}_{action_type}_{today}"
        pdf_path = os.path.join(out_dir, f"{base_name}.pdf")
        if os.path.exists(pdf_path):
            for i in range(2, 20):
                candidate = os.path.join(out_dir, f"{base_name}_{i}.pdf")
                if not os.path.exists(candidate):
                    pdf_path = candidate
                    break

        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', encoding='utf-8', delete=False) as f:
            f.write(html_content)
            tmp_html = f.name

        file_url = 'file:///' + tmp_html.replace('\\', '/')
        run_edge_pdf(
            [edge, '--headless', '--disable-gpu', '--no-sandbox',
             f'--print-to-pdf={pdf_path}',
             '--no-pdf-header-footer',
             '--run-all-compositor-stages-before-draw',
             file_url]
        )
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
            logger.info("Contractor voucher PDF saved: %s", pdf_path)
            _voucher_pdf_audit(voucher_no, "contractor_payment_voucher", True, pdf_path, actor, action_type)
        else:
            logger.warning("Contractor voucher PDF not created for %s (Edge ran but no output file)", voucher_no)
            _voucher_pdf_audit(voucher_no, "contractor_payment_voucher", False,
                               "Edge 執行完畢但未產生 PDF 檔案", actor, action_type)
    except Exception as e:
        logger.exception("_generate_contractor_voucher_pdf failed for %s", voucher_no)
        _voucher_pdf_audit(voucher_no, "contractor_payment_voucher", False, str(e), actor, action_type)
    finally:
        if tmp_html:
            try:
                os.unlink(tmp_html)
            except Exception:
                pass


# ── 開票申請憑據 ──────────────────────────────────────────────────────────────

def _invoice_voucher_view(v: dict) -> dict:
    """開票申請憑據的**單據視圖**（P2）：計算只在這裡，版型只能引用這些欄位（CUSTOMIZATION-SPEC §3.4）。"""
    appr = v.get('approval') or {}
    scope = v.get('scope') or 'amount'
    return {
        **v,
        "scope": scope,
        "scopeLabel": '自訂品項' if scope == 'items' else '自訂金額',
        "amount": v.get('amount', 0) or 0,
        "pretaxAmount": v.get('pretaxAmount', 0) or 0,
        "taxAmount": v.get('taxAmount', 0) or 0,
        "selectedItems": v.get('selectedItems') or [],
        "quoteItems": v.get('quoteItems') or [],
        "applicantName": appr.get('requestedByDisplay') or v.get('createdBy', ''),
        "applicantDate": (appr.get('requestedAt') or v.get('createdAt') or '')[:10],
        "approval": appr,
    }


def _build_invoice_voucher_html(v: dict, template: dict = None) -> str:
    """開票申請憑據（P2 起由「版型定義＋單據視圖」產生；預設版型 helpers/output_templates/invoice_voucher.json）。

    `template` 給了就用它（P5 版面定義的公司／角色覆寫版）；否則用隨程式出貨的預設版型。
    與改版前的 builder 逐位元組相同（tests/_frozen/legacy_invoice_voucher_html.py 為永久正對照）。
    """
    from helpers import doc_template as _dt
    # 🔑 QL7／QL25：抬頭從這一筆單據所屬的據點取值，並疊上報價單送出時凍結的抬頭快照（同改版前）
    _ident = apply_snapshot(location_identity(_location_of(v)), v)
    view = _invoice_voucher_view(v)
    parts = {
        "identity_head": lambda: _identity_head(_ident),
        "identity_foot": lambda: _identity_foot(_ident),
        "approval_sign": lambda: _voucher_sign_html(view["approval"]),
    }
    return _dt.render(template or _dt.load_default("invoice_voucher"), view, parts)


def _invoice_voucher_dict(row) -> dict:
    d = dict(row)
    snap = json.loads(d.pop("snapshot_json", None) or "{}")
    appr = (json.loads(d.pop("data_json", None) or "{}") or {}).get("approval") or {}
    out = {**snap}
    out["voucherNo"] = d.get("voucher_no", "")
    out["quoteNo"] = d.get("quote_no", "")
    out["scope"] = d.get("scope", "amount")
    out["amount"] = float(d.get("amount") or 0)
    out["status"] = d.get("status", "")
    out["createdBy"] = _display_name_for_username(d.get("created_by", ""))
    out["createdAt"] = d.get("created_at", "")
    out["approval"] = appr
    return out


def generate_invoice_voucher_pdf_bytes(voucher_no: str) -> bytes:
    """Edge Headless 產生開票申請憑據 PDF 並以 bytes 回傳（供 API 下載使用）。"""
    edge = _get_edge_path()
    conn = get_db()
    row = conn.execute("SELECT * FROM invoice_vouchers WHERE voucher_no=?", (voucher_no,)).fetchone()
    conn.close()
    if not row:
        raise ValueError("憑據不存在")
    v = _invoice_voucher_dict(row)
    html_content = _build_invoice_voucher_html(v)
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
                try: os.unlink(p)
                except Exception: pass


def _generate_invoice_voucher_pdf(voucher_no: str, actor: str = '', action_type: str = '簽核'):
    """存檔＋稽核版開票申請憑據 PDF 產生，於全部簽核完成後背景觸發。"""
    try:
        edge = _get_edge_path()
    except RuntimeError as e:
        logger.warning("Edge not found, invoice voucher PDF generation skipped: %s", e)
        _voucher_pdf_audit(voucher_no, "invoice_voucher", False, str(e), actor, action_type)
        return

    safe_actor = re.sub(r'[\\/:*?"<>|\s]', '_', actor or '').strip('_')[:20]
    tmp_html = None
    pdf_path = ""
    try:
        conn = get_db()
        row = conn.execute("SELECT * FROM invoice_vouchers WHERE voucher_no=?", (voucher_no,)).fetchone()
        conn.close()
        if not row:
            return
        v = _invoice_voucher_dict(row)
        html_content = _build_invoice_voucher_html(v)

        today   = date.today().strftime('%Y%m%d')
        out_dir = os.path.join(_get_invoice_voucher_pdf_base(), date.today().isoformat())
        os.makedirs(out_dir, exist_ok=True)

        base_name = f"{voucher_no}_{action_type}_{today}_{safe_actor}" if safe_actor \
            else f"{voucher_no}_{action_type}_{today}"
        pdf_path = os.path.join(out_dir, f"{base_name}.pdf")
        if os.path.exists(pdf_path):
            for i in range(2, 20):
                candidate = os.path.join(out_dir, f"{base_name}_{i}.pdf")
                if not os.path.exists(candidate):
                    pdf_path = candidate
                    break

        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', encoding='utf-8', delete=False) as f:
            f.write(html_content)
            tmp_html = f.name

        file_url = 'file:///' + tmp_html.replace('\\', '/')
        run_edge_pdf(
            [edge, '--headless', '--disable-gpu', '--no-sandbox',
             f'--print-to-pdf={pdf_path}',
             '--no-pdf-header-footer',
             '--run-all-compositor-stages-before-draw',
             file_url]
        )
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
            logger.info("Invoice voucher PDF saved: %s", pdf_path)
            _voucher_pdf_audit(voucher_no, "invoice_voucher", True, pdf_path, actor, action_type)
        else:
            logger.warning("Invoice voucher PDF not created for %s (Edge ran but no output file)", voucher_no)
            _voucher_pdf_audit(voucher_no, "invoice_voucher", False,
                               "Edge 執行完畢但未產生 PDF 檔案", actor, action_type)
    except Exception as e:
        logger.exception("_generate_invoice_voucher_pdf failed for %s", voucher_no)
        _voucher_pdf_audit(voucher_no, "invoice_voucher", False, str(e), actor, action_type)
    finally:
        if tmp_html:
            try:
                os.unlink(tmp_html)
            except Exception:
                pass


# ── 請款單 ────────────────────────────────────────────────────────────────────

_PAYMENT_STAGE_LABELS = {
    "full":       "全額",
    "deposit":    "訂金款",
    "delivery":   "交貨款",
    "acceptance": "驗收款",
    "final":      "尾款",
}


def _build_payment_request_html(v: dict) -> str:
    # 🔑 QL7：抬頭從**這一筆單據所屬的據點**取值，一支函式取一次。
    # ⚠️ 取不到 `locationId` ⇒ `location_identity(None)` 落在主要據點，
    #    那是既有安裝（只有一個據點、或根本沒設過）的正確行為。
    # 🔴 `QL25`（依據使用者 2026-09-23 裁示）：這份單據的抬頭要跟著
    #    報價單送出那一刻凍結的快照走（若有）——`apply_snapshot()` 疊
    #    在即時值上，只覆蓋抬頭五欄。銀行欄位不受影響：`QL10` 沒有被
    #    翻掉，它管的是別的欄位，此處若有銀行欄位仍然一律即時值。
    _ident = apply_snapshot(location_identity(_location_of(v)), v)
    def esc(s):
        return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')
    def money(n):
        return f'{n:,.0f}' if isinstance(n, (int, float)) else '0'

    scope = v.get('scope') or 'amount'
    requested_amount = v.get('amount', 0) or 0
    pretax_amount = v.get('pretaxAmount', 0) or 0
    tax_amount = v.get('taxAmount', 0) or 0
    ratio_pct = v.get('ratioPct', 0) or 0
    selected_items = v.get('selectedItems') or []
    quote_items = v.get('quoteItems') or []
    # 請款範圍：客戶端只需要看業務語意分類（全額/訂金款/交貨款/驗收款/尾款），
    # scope（amount/items）純粹是內部金額計算方式，不對外顯示。
    scope_label = _PAYMENT_STAGE_LABELS.get(v.get('stage') or '', '未分類')

    if scope == 'items':
        sel_rows = ''
        for i, it in enumerate(selected_items, 1):
            spec = it.get('description', '')
            brand = it.get('brand', '')
            sel_rows += (
                f'<tr><td>{i}</td><td>{esc(spec)}{("　" + esc(brand)) if brand else ""}</td>'
                f'<td class="r">{esc(str(it.get("qty","")))}</td><td>{esc(it.get("unit",""))}</td>'
                f'<td class="r">{money(it.get("unitPrice",0))}</td><td class="r">{money(it.get("amount",0))}</td></tr>'
            )
        items_table_html = (
            '<div class="section-label">三、請款品項明細（未稅，稅額另計，見下方總額）</div>\n'
            '<table>\n  <thead><tr><th style="width:24px">#</th><th>品名 / 規格</th>'
            '<th class="r" style="width:44px">數量</th><th style="width:40px">單位</th>'
            '<th class="r" style="width:70px">單價（未稅）</th><th class="r" style="width:90px">金額（未稅）</th></tr></thead>\n'
            f'  <tbody>{sel_rows}</tbody>\n</table>\n'
        )
        quote_items_html = ''
    else:
        items_table_html = (
            '<div class="section-label">三、請款金額</div>\n'
            '<div class="boxes" style="grid-template-columns:1fr">\n'
            '  <div class="box">\n'
            f'    <div class="row"><span class="label">請款金額（含稅）</span>'
            f'<span class="val" style="font-size:16px;font-weight:700;font-family:Arial,sans-serif">'
            f'NT$ {money(requested_amount)}</span></div>\n'
            '  </div>\n</div>\n'
        )
        quote_item_rows = ''
        for i, it in enumerate(quote_items, 1):
            spec = it.get('description', '')
            brand = it.get('brand', '')
            quote_item_rows += (
                f'<tr><td>{i}</td><td>{esc(spec)}{("　" + esc(brand)) if brand else ""}</td>'
                f'<td class="r">{esc(str(it.get("qty","")))}</td><td>{esc(it.get("unit",""))}</td>'
                f'<td class="r">{money(it.get("unitPrice",0))}</td><td class="r">{money(it.get("amount",0))}</td></tr>'
            )
        quote_items_html = ''
        if quote_item_rows:
            quote_items_html = (
                '<div class="section-label">四、報價品項參考</div>\n'
                '<table>\n  <thead><tr><th style="width:24px">#</th><th>品名 / 規格</th>'
                '<th class="r" style="width:44px">數量</th><th style="width:40px">單位</th>'
                '<th class="r" style="width:70px">單價</th><th class="r" style="width:90px">金額</th></tr></thead>\n'
                f'  <tbody>{quote_item_rows}</tbody>\n</table>\n'
            )

    def term_block(title, text):
        t = (text or '').strip()
        if not t:
            return ''
        return (f'<div style="margin-bottom:10px"><div class="section-label" style="margin-bottom:3px">{esc(title)}</div>'
                f'<div style="font-size:11px;color:#0A0A0A;line-height:1.7">{esc(t)}</div></div>')

    # 收款帳戶資訊（2026-08-24 新增）：緊接在總額之後，讀者算完應付金額的下一步
    # 就是要匯款，比照大型企業/上市櫃公司請款單慣例把匯款帳戶放在明顯位置，
    # 不要埋在條款/簽核區塊後面才看到。company_profile 未填任何一個銀行欄位時
    # 整段不顯示（新裝機/尚未設定時不留一個空殼區塊）。
    # 🔴🔴 QL9：銀行欄位改讀**這一筆單據所屬的據點**，不是全公司唯一那一組。
    # ☠️ 這是使用者要這個功能的原因：**分公司開的請款單不能印總公司的帳號** ——
    #    而客戶會照著上面那串數字匯款。
    # 📌 `location_identity()` 逐欄落空：分公司沒填銀行欄位就沿用主要據點的，
    #    所以既有安裝（只有一個據點）行為完全不變。
    bank_rows = [
        ('銀行名稱', _ident.get('bank_name', '')),
        ('分行名稱', _ident.get('bank_branch', '')),
        ('戶　　名', _ident.get('bank_account_name', '')),
        ('帳　　號', _ident.get('bank_account_number', '')),
    ]
    bank_rows = [(label, val) for label, val in bank_rows if (val or '').strip()]
    bank_info_section = ''
    if bank_rows:
        bank_rows_html = ''.join(
            f'    <div class="row"><span class="label">{esc(label)}</span>'
            f'<span class="val" style="font-family:Arial,sans-serif">{esc(val)}</span></div>\n'
            for label, val in bank_rows
        )
        bank_info_section = (
            '<div class="section-label">五、收款帳戶資訊</div>\n'
            '<div class="boxes" style="grid-template-columns:1fr;margin-bottom:14px">\n'
            '  <div class="box" style="border-color:#0A0A0A">\n'
            f'{bank_rows_html}'
            '  </div>\n</div>\n'
        )

    terms = v.get('terms') or {}
    terms_html  = term_block('付款條件', terms.get('paymentTerms', ''))
    terms_html += term_block('交貨條件', terms.get('deliveryTerms', ''))
    terms_html += term_block('驗收標準', terms.get('acceptanceTerms', ''))
    terms_html += term_block('保固條件', terms.get('warrantyTerms', ''))
    terms_section = (
        f'<div class="section-label">{"六" if bank_rows else "五"}、請款條件</div>' + terms_html
    ) if terms_html.strip() else ''

    is_final = v.get('status') == '已核准'
    watermark_html = '' if is_final else (
        '<div class="wm">' + ''.join(
            '<div class="wm-item"><b>請款單預覽稿</b><small>尚未正式核准</small></div>'
            for _ in range(12)
        ) + '</div>'
    )
    banner_html = '' if is_final else (
        f'<div class="preview-banner">⚠ 此為請款單預覽稿（目前狀態：{esc(v.get("status") or "草稿")}），'
        f'尚未正式核准，請勿提供給客戶辦理請款</div>'
    )

    return (
        '<!DOCTYPE html>\n<html lang="zh-Hant">\n<head>\n<meta charset="UTF-8">\n'
        f'<title>{esc(v.get("requestNo",""))} 請款單</title>\n'
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
        '  @page{size:A4;margin:0 13mm 12mm 13mm;@bottom-center{content:counter(page);font-family:Arial,sans-serif;font-size:9px;color:#888}}\n'
        '  @media print{html,body{margin:0;padding:0;background:#fff}#root{padding:15mm 0 0}tr{page-break-inside:avoid}}\n'
        '  .accent-bar{height:3px;background:#0A0A0A;margin-bottom:18px}\n'
        '  .header{display:flex;justify-content:space-between;align-items:flex-start;padding-bottom:14px;border-bottom:1px solid #0A0A0A;margin-bottom:16px}\n'
        '  .co-name{font-size:15px;font-weight:700;letter-spacing:.06em}\n'
        '  .co-sub{font-size:10px;color:#888;margin-top:3px;font-family:Arial,sans-serif;letter-spacing:.02em}\n'
        '  .doc-title{font-size:22px;font-weight:700;letter-spacing:.18em;text-align:right}\n'
        '  .meta{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;margin-bottom:14px;font-size:12px;background:#FAFAF8;padding:10px 12px;border-radius:4px;border:1px solid #EDEAE4}\n'
        '  .meta span{color:#888;font-family:Arial,sans-serif;font-size:11px}\n'
        '  .boxes{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px}\n'
        '  .box{background:#FAFAF8;border:1px solid #EDEAE4;border-radius:4px;padding:11px 13px}\n'
        '  .box-title{font-size:9px;font-family:Arial,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:#888;font-weight:600;margin-bottom:8px}\n'
        '  .row{display:flex;gap:6px;margin-bottom:4px;font-size:12px}\n'
        '  .label{color:#888;min-width:72px;flex-shrink:0;font-size:11px}\n'
        '  .val{color:#0A0A0A;font-weight:500}\n'
        '  .section-label{font-size:9px;font-family:Arial,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:#888;font-weight:600;margin-bottom:7px;display:flex;align-items:center;gap:8px}\n'
        '  .section-label::after{content:"";flex:1;height:1px;background:#EDEAE4}\n'
        '  table{width:100%;border-collapse:collapse;margin-bottom:14px}\n'
        '  thead th{background:#0A0A0A;color:#F5F4F0;padding:8px 9px;text-align:left;font-size:11px;font-weight:500;font-family:Arial,sans-serif;letter-spacing:.04em}\n'
        '  thead th.r{text-align:right}\n'
        '  tbody td{padding:8px 9px;border-bottom:1px solid #EDEAE4;font-size:12px}\n'
        '  tbody tr:last-child td{border-bottom:none}\n'
        '  tbody tr:nth-child(even) td{background:#FAFAF8}\n'
        '  td.r{text-align:right;font-family:Arial,sans-serif}\n'
        '  .total-box{display:flex;justify-content:flex-end;margin-bottom:16px}\n'
        '  .total-table{width:280px;font-size:12px}\n'
        '  .total-table .row{display:flex;justify-content:space-between;padding:4px 0}\n'
        '  .total-table .grand{font-size:15px;font-weight:700;border-top:1px solid #0A0A0A;padding-top:8px;margin-top:4px}\n'
        '  .footer{text-align:center;font-size:10px;color:#888;margin-top:18px;padding-top:12px;border-top:1px solid #EDEAE4;font-family:Arial,sans-serif;letter-spacing:.04em}\n'
        '</style>\n</head>\n<body>\n<div id="root">\n'
        f'{watermark_html}\n'
        '<div class="accent-bar"></div>\n'
        '<div class="header">\n  <div>\n'
        + _identity_head(_ident) +
        '  </div>\n  <div>\n    <div class="doc-title">請款單</div>\n  </div>\n</div>\n'
        '<div class="meta">\n'
        f'  <div><span>請款單號：</span><strong style="font-family:Arial,sans-serif">{esc(v.get("requestNo",""))}</strong></div>\n'
        f'  <div><span>建立日期：</span>{esc((v.get("createdAt") or "")[:10])}</div>\n'
        f'  <div><span>關聯案件：</span>{esc(v.get("quoteNo",""))}</div>\n'
        '</div>\n'
        f'{banner_html}\n'
        '<div class="boxes">\n'
        '  <div class="box">\n    <div class="box-title">一、客戶資訊</div>\n'
        f'    <div class="row"><span class="label">客戶名稱</span><span class="val">{esc(v.get("customerName",""))}</span></div>\n'
        f'    <div class="row"><span class="label">統一編號</span><span class="val">{esc(v.get("customerTaxId",""))}</span></div>\n'
        '  </div>\n'
        '  <div class="box">\n    <div class="box-title">二、案件資訊</div>\n'
        f'    <div class="row"><span class="label">案件名稱</span><span class="val">{esc(v.get("projectName",""))}</span></div>\n'
        f'    <div class="row"><span class="label">請款範圍</span><span class="val">{esc(scope_label)}</span></div>\n'
        '  </div>\n</div>\n'
        f'{items_table_html}'
        '<div class="total-box"><div class="total-table">\n'
        f'  <div class="row"><span>未稅小計</span><span style="font-family:Arial,sans-serif">NT$ {money(pretax_amount)}</span></div>\n'
        f'  <div class="row"><span>營業稅</span><span style="font-family:Arial,sans-serif">NT$ {money(tax_amount)}</span></div>\n'
        f'  <div class="row grand"><span>請款總額（含稅）</span><span style="font-family:Arial,sans-serif">NT$ {money(requested_amount)}</span></div>\n'
        '</div></div>\n'
        f'{quote_items_html}'
        f'{bank_info_section}'
        f'{terms_section}\n'
        '<div class="footer">\n'
        + _identity_foot(_ident) +
        '</div>\n'
        '</div>\n'
        '<script>window.addEventListener("load",function(){var r=document.getElementById("root");if(!r)return;'
        'var A4H=Math.round(267/25.4*96);var h=r.scrollHeight;'
        'if(h>A4H){var s=A4H/h;if(s>=0.70){document.body.style.zoom=s.toFixed(4);}}});</script>\n'
        '</body>\n</html>'
    )


def _payment_request_dict(row) -> dict:
    d = dict(row)
    snap = json.loads(d.pop("snapshot_json", None) or "{}")
    appr = (json.loads(d.pop("data_json", None) or "{}") or {}).get("approval") or {}
    out = {**snap}
    out["requestNo"] = d.get("request_no", "")
    out["quoteNo"] = d.get("quote_no", "")
    out["scope"] = d.get("scope", "amount")
    out["stage"] = d.get("stage", "")
    out["amount"] = float(d.get("amount") or 0)
    out["ratioPct"] = float(d.get("ratio_pct") or 0)
    out["terms"] = json.loads(d.get("terms_json") or "{}")
    out["status"] = d.get("status", "")
    out["createdBy"] = _display_name_for_username(d.get("created_by", ""))
    out["createdAt"] = d.get("created_at", "")
    out["approval"] = appr
    return out


def generate_payment_request_pdf_bytes(request_no: str) -> bytes:
    """Edge Headless 產生請款單 PDF 並以 bytes 回傳（供 API 下載使用）。"""
    edge = _get_edge_path()
    conn = get_db()
    row = conn.execute("SELECT * FROM payment_requests WHERE request_no=?", (request_no,)).fetchone()
    conn.close()
    if not row:
        raise ValueError("請款單不存在")
    v = _payment_request_dict(row)
    html_content = _build_payment_request_html(v)
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
                try: os.unlink(p)
                except Exception: pass


def _generate_payment_request_pdf(request_no: str, actor: str = '', action_type: str = '簽核'):
    """存檔＋稽核版請款單 PDF 產生，於全部簽核完成後背景觸發。"""
    try:
        edge = _get_edge_path()
    except RuntimeError as e:
        logger.warning("Edge not found, payment request PDF generation skipped: %s", e)
        _voucher_pdf_audit(request_no, "payment_request", False, str(e), actor, action_type)
        return

    safe_actor = re.sub(r'[\\/:*?"<>|\s]', '_', actor or '').strip('_')[:20]
    tmp_html = None
    pdf_path = ""
    try:
        conn = get_db()
        row = conn.execute("SELECT * FROM payment_requests WHERE request_no=?", (request_no,)).fetchone()
        conn.close()
        if not row:
            return
        v = _payment_request_dict(row)
        html_content = _build_payment_request_html(v)

        today   = date.today().strftime('%Y%m%d')
        out_dir = os.path.join(_get_payment_request_pdf_base(), date.today().isoformat())
        os.makedirs(out_dir, exist_ok=True)

        base_name = f"{request_no}_{action_type}_{today}_{safe_actor}" if safe_actor \
            else f"{request_no}_{action_type}_{today}"
        pdf_path = os.path.join(out_dir, f"{base_name}.pdf")
        if os.path.exists(pdf_path):
            for i in range(2, 20):
                candidate = os.path.join(out_dir, f"{base_name}_{i}.pdf")
                if not os.path.exists(candidate):
                    pdf_path = candidate
                    break

        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', encoding='utf-8', delete=False) as f:
            f.write(html_content)
            tmp_html = f.name

        file_url = 'file:///' + tmp_html.replace('\\', '/')
        run_edge_pdf(
            [edge, '--headless', '--disable-gpu', '--no-sandbox',
             f'--print-to-pdf={pdf_path}',
             '--no-pdf-header-footer',
             '--run-all-compositor-stages-before-draw',
             file_url]
        )
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
            logger.info("Payment request PDF saved: %s", pdf_path)
            _voucher_pdf_audit(request_no, "payment_request", True, pdf_path, actor, action_type)
        else:
            logger.warning("Payment request PDF not created for %s (Edge ran but no output file)", request_no)
            _voucher_pdf_audit(request_no, "payment_request", False,
                               "Edge 執行完畢但未產生 PDF 檔案", actor, action_type)
    except Exception as e:
        logger.exception("_generate_payment_request_pdf failed for %s", request_no)
        _voucher_pdf_audit(request_no, "payment_request", False, str(e), actor, action_type)
    finally:
        if tmp_html:
            try:
                os.unlink(tmp_html)
            except Exception:
                pass


# ── 案件結案報表（案件完結時內部財務/執行進度綜合報告，2026-08-25）────────────

def _case_closing_report_data(quote_no: str) -> dict:
    """彙整結案報表所需的全部資料。財務數字（損益分析）一律直接讀
    data_json.settlement.summary 這份精算存檔當下寫入的快照，不在這裡重新計算——
    跟財務 Tab／營運報表共用同一份權威來源，避免三處顯示互相對不上（見
    helpers/quotations.py 對 dispatchTotal 快照 vs 即時重算的既有說明）。"""
    conn = get_db()
    row = conn.execute("""
        SELECT quote_no, customer_name, project_name, sales_person, quote_date,
               total, pretax, net_margin_pct, status,
               COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') AS deal_tag,
               COALESCE(NULLIF(settle_status,''), json_extract(data_json,'$.settlement.status'), '') AS settle_status,
               data_json, created_at
        FROM quotations WHERE quote_no=?
    """, (quote_no,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("案件不存在")

    d   = json.loads(row["data_json"] or "{}")
    cr  = d.get("caseRecord") or {}
    settlement = d.get("settlement") or {}

    # 2026-09-11：額外支出搬到 case_extra_expenses 表（DB v75）。結案報表是對外／
    # 存查用的最終文件，**不能再讀 data_json 的 settlement.extraItems**——那份現在
    # 只是搬移前的唯讀備份、不會再更新，讀它會讓報表停在搬移當下的舊數字。
    # 帶 status 出來是為了在報表上標示「送審中」：這些金額已計入成本（使用者指定），
    # 但對外文件必須讓看的人知道它還沒完成簽核。
    settlement["extraItems"] = [{
        "category":    r2["category"] or "",
        "description": r2["description"] or "",
        "totalCost":   float(r2["total_cost"] or 0),
        "expenseDate": r2["expense_date"] or "",
        "docNo":       r2["doc_no"] or "",
        "status":      r2["status"],
        "payerName":   r2["payer_name"] or "",
        "files":       json.loads(r2["files_json"] or "[]"),
    } for r2 in conn.execute(
        "SELECT * FROM case_extra_expenses WHERE quote_no=? ORDER BY id", (quote_no,)
    ).fetchall()]

    # 成案日期／結案日期：取 audit_log 裡 deal_tag.change 事件的最新一次時間戳
    # （比 quote_date 更能反映案件實際進度，跟 quote_won_month_map 同一套精神）
    won_at = closed_at = ""
    for r in conn.execute(
        "SELECT at, detail FROM audit_log WHERE action='deal_tag.change' AND target_id=? ORDER BY at ASC",
        (quote_no,)
    ).fetchall():
        try:
            detail = json.loads(r["detail"] or "{}")
        except Exception:
            continue
        if detail.get("to") == "已成案":
            won_at = r["at"]
        elif detail.get("to") == "已結案":
            closed_at = r["at"]

    # 收款明細：跟 reports.py::_collect() 用同一套 payment_item_amounts() 換算，
    # 避免另外重寫一次 pct→金額的公式又跟其他報表的數字兜不起來。
    #
    # 2026-09-10：`pretax` 先前漏傳。該參數是 2026-08-28 為了「已核准稅額沖銷
    # （taxExempt=True）的款項只剩未稅金額應收」而加的，當時掃過 reports.py／
    # dashboard.py 的 12 個呼叫點卻沒掃到本檔，導致結案報表 PDF 對已沖銷款項
    # 顯示含稅金額，跟畫面／Excel／營運報表同一筆案件兩個數字。helpers 那邊
    # docstring 說的「拿不到 pretax 就維持舊行為」不適用於這裡——SELECT 本來
    # 就有撈 pretax（見上方查詢），純粹是漏接。
    total = row["total"] or 0
    pay   = (cr.get("payment") or {}).get("items", [])
    payment_rows = []
    if pay:
        amounts = payment_item_amounts(total, pay, row["pretax"])
        for idx, pi in enumerate(pay):
            amt = amounts[idx]
            payment_rows.append({
                "type":         pi.get("type") or f"第{idx+1}期",
                "pct":          pi.get("pct") or 0,
                "amount":       amt,
                "received":     bool(pi.get("received")),
                "receivedAt":   (pi.get("receivedAt") or "")[:10],
                "actualAmount": pi.get("actualAmount"),
                "feeAmount":    pi.get("feeAmount") or 0,
                "invoiceNo":    pi.get("invoiceNo", ""),
                "note":         pi.get("note", ""),
            })

    # 執行進度：直接查 case_stages（已結案案件不再出現在 stage_board() 的
    # WHERE deal_tag='已成案' 條件裡，所以這裡不能重用那支端點，得自己查）
    stage_rows = conn.execute(
        "SELECT label, start_date, due_date, done, done_at, assigned_to, "
        "(SELECT MIN(visit_date) FROM case_stage_visits WHERE stage_id=case_stages.id AND visit_date!='') AS visit_start, "
        "(SELECT MAX(visit_date) FROM case_stage_visits WHERE stage_id=case_stages.id AND visit_date!='') AS visit_end "
        "FROM case_stages WHERE quote_no=? ORDER BY sort_order, id",
        (quote_no,)
    ).fetchall()
    dn_map = {
        r["username"]: (r["display_name"] or r["username"])
        for r in conn.execute("SELECT username, display_name FROM users").fetchall()
    }
    today = date.today().isoformat()
    stages = []
    for r in stage_rows:
        done = bool(r["done"])
        due  = r["due_date"] or ""
        assigned = [u for u in json.loads(r["assigned_to"] or "[]") if u]
        stages.append({
            "label":         r["label"] or "（未命名階段）",
            "startDate":     r["start_date"] or "",
            "dueDate":       due,
            "doneAt":        (r["done_at"] or "")[:10],
            "visitStart":    r["visit_start"] or "",
            "visitEnd":      r["visit_end"] or "",
            "done":          done,
            "overdue":       (not done) and bool(due) and due < today,
            "assignedNames": [dn_map.get(u, u) for u in assigned],
        })

    # 承攬商／外包派發明細（排除已取消，比照精算頁「唯讀讀取」的既有規則；
    # status 存的是英文代碼 draft/sent/confirmed/pending_acceptance/accepted/
    # completed/cancelled，見 routers/vendor_contractors.py::_STATUS_LABELS）
    dispatch_rows = conn.execute("""
        SELECT cd.dispatch_date, cd.scope, cd.total_amount, cd.status, cd.invoice_no,
               vc.name AS vendor_name
        FROM contractor_dispatches cd LEFT JOIN vendor_contractors vc ON vc.id = cd.vendor_id
        WHERE cd.quote_no=? AND cd.status != 'cancelled'
        ORDER BY cd.dispatch_date
    """, (quote_no,)).fetchall()
    _dispatch_status_labels = {
        "draft": "草稿", "sent": "已送出", "confirmed": "已確認",
        "pending_acceptance": "待驗收", "accepted": "已驗收",
        "completed": "完工", "cancelled": "已取消",
    }
    dispatches = [{
        "vendorName": r["vendor_name"] or "（外包人員）",
        "date":       r["dispatch_date"] or "",
        "scope":      r["scope"] or "",
        "amount":     r["total_amount"] or 0,
        "status":     _dispatch_status_labels.get(r["status"] or "draft", r["status"] or ""),
        "invoiceNo":  r["invoice_no"] or "",
    } for r in dispatch_rows]

    conn.close()

    return {
        "quoteNo":      row["quote_no"],
        "customer":     row["customer_name"] or "",
        "project":      row["project_name"] or "",
        "salesPerson":  row["sales_person"] or "",
        "quoteDate":    row["quote_date"] or "",
        "wonAt":        won_at[:10] if won_at else "",
        "closedAt":     closed_at[:10] if closed_at else "",
        "dealTag":      row["deal_tag"] or "",
        "settleStatus": row["settle_status"] or "",
        "total":        total,
        "pretax":       row["pretax"] or 0,
        "taxAmount":    total - (row["pretax"] or 0),
        "paymentRows":  payment_rows,
        "receivedTotal": sum((pr["actualAmount"] if pr["actualAmount"] is not None else pr["amount"])
                             for pr in payment_rows if pr["received"]),
        "settlement":   settlement,
        "stages":       stages,
        "dispatches":   dispatches,
    }


def _build_case_closing_html(data: dict) -> str:
    # 🔑 QL7：抬頭從**這一筆單據所屬的據點**取值，一支函式取一次。
    # ⚠️ 取不到 `locationId` ⇒ `location_identity(None)` 落在主要據點，
    #    那是既有安裝（只有一個據點、或根本沒設過）的正確行為。
    # 🔴 `QL25`（依據使用者 2026-09-23 裁示）：這份單據的抬頭要跟著
    #    報價單送出那一刻凍結的快照走（若有）——`apply_snapshot()` 疊
    #    在即時值上，只覆蓋抬頭五欄。銀行欄位不受影響：`QL10` 沒有被
    #    翻掉，它管的是別的欄位，此處若有銀行欄位仍然一律即時值。
    _ident = apply_snapshot(location_identity(_location_of(data)), data)
    def esc(s):
        return (str(s) if s is not None else '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')

    def money(n):
        return f'{n:,.0f}' if isinstance(n, (int, float)) else '0'

    s = data.get("settlement") or {}
    summary = s.get("summary") or {}
    is_finalized = s.get("status") == "finalized"

    # ── 一、收款明細 ──────────────────────────────────────────────────────────
    pay_rows_html = ""
    for pr in data["paymentRows"]:
        recv_cls = "#15803D" if pr["received"] else "#9CA3AF"
        recv_txt = "已收款" if pr["received"] else "未收款"
        net_amt  = (pr["actualAmount"] if pr["actualAmount"] is not None else pr["amount"]) - (pr["feeAmount"] or 0)
        pay_rows_html += (
            f'<tr><td>{esc(pr["type"])}</td>'
            f'<td class="r">{pr["pct"]}%</td>'
            f'<td class="r">{money(pr["amount"])}</td>'
            f'<td class="c" style="color:{recv_cls};font-weight:600">{recv_txt}</td>'
            f'<td class="c">{esc(pr["receivedAt"]) or "—"}</td>'
            f'<td class="r">{money(net_amt) if pr["received"] else "—"}</td>'
            f'<td>{esc(pr["invoiceNo"])}</td>'
            f'<td>{esc(pr["note"])}</td></tr>'
        )
    collection_rate = round(data["receivedTotal"] / data["total"] * 100, 1) if data["total"] > 0 else 0
    _no_pay_row = '<tr><td colspan="8" class="c" style="color:#9CA3AF">無款項明細資料</td></tr>'
    payment_section = (
        '<div class="section-label">二、收款明細</div>'
        '<table><thead><tr><th>期別</th><th class="r">比例</th><th class="r">應收金額</th>'
        '<th class="c">狀態</th><th class="c">收款日期</th><th class="r">實收淨額</th>'
        '<th>發票號碼</th><th>備註</th></tr></thead>'
        f'<tbody>{pay_rows_html or _no_pay_row}</tbody></table>'
        '<div class="total-box"><div class="total-table">'
        f'<div class="row"><span>已收金額</span><span>{money(data["receivedTotal"])}</span></div>'
        f'<div class="row grand"><span>收款率</span><span>{collection_rate}%</span></div>'
        '</div></div>'
    )

    # ── 三、損益分析 ──────────────────────────────────────────────────────────
    if is_finalized:
        prof_diff = int(summary.get("profitDiff", 0) or 0)
        diff_clr  = "#15803D" if prof_diff >= 0 else "#DC2626"
        diff_ppts = round(float(summary.get("netMarginPct") or 0) - float(summary.get("origNetMarginPct") or 0), 1)
        settle_date = s.get("settlementDate", "") or ""
        settle_by   = s.get("finalizedBy", "") or ""
        profit_section = f"""
<div class="section-label">三、損益分析（精算完結 · 精算日期：{esc(settle_date) or '—'}　完結人：{esc(settle_by) or '—'}）</div>
<div class="profit-grid">
  <table>
    <thead><tr><th colspan="2" class="c" style="background:#F9FAFB;color:#374151">原始報價預估</th></tr></thead>
    <tbody>
      <tr><td>報價稅前收入</td><td class="r">{money(summary.get("quotedPretax"))}</td></tr>
      <tr><td>原始成本（料件）</td><td class="r">{money(summary.get("origTotalCost"))}</td></tr>
      <tr><td class="bold">原始直接毛利</td><td class="r bold">{money(summary.get("origDirectProfit"))}</td></tr>
      <tr><td>原始毛利率</td><td class="r">{float(summary.get("origMarginPct") or 0):.1f}%</td></tr>
      <tr><td>管銷分攤（10%）</td><td class="r red">− {money(summary.get("origAdminCost"))}</td></tr>
      <tr><td>公益捐款（1%）</td><td class="r red">− {money(summary.get("origCharity"))}</td></tr>
      <tr class="bold-row"><td>原始預估淨利</td><td class="r">{money(summary.get("origNetProfit"))}</td></tr>
      <tr><td>原始預估淨利率</td><td class="r">{float(summary.get("origNetMarginPct") or 0):.1f}%</td></tr>
    </tbody>
  </table>
  <table>
    <thead><tr><th colspan="2" class="c" style="background:#FFFBEB;color:#92400E">實際成本精算</th></tr></thead>
    <tbody>
      <tr><td>報價稅前收入</td><td class="r">{money(summary.get("quotedPretax"))}</td></tr>
      <tr><td>品項實際成本</td><td class="r orange">{money(summary.get("itemActualTotal"))}</td></tr>
      <tr><td>額外支出</td><td class="r orange">{money(summary.get("extraTotal"))}</td></tr>
      <tr><td>承攬商派發成本</td><td class="r orange">{money(summary.get("dispatchTotal"))}</td></tr>
      <tr class="bold-row"><td>實際總成本</td><td class="r orange bold">{money(summary.get("totalActualCost"))}</td></tr>
      <tr><td>真實毛利</td><td class="r {'green' if int(summary.get('grossProfit',0) or 0)>=0 else 'red'}">{money(summary.get("grossProfit"))}</td></tr>
      <tr><td>真實毛利率</td><td class="r">{float(summary.get("grossMarginPct") or 0):.1f}%</td></tr>
      <tr><td>管銷分攤（10%）</td><td class="r red">− {money(summary.get("adminCost"))}</td></tr>
      <tr><td>公益捐款（1%）</td><td class="r red">− {money(summary.get("charityDonation"))}</td></tr>
      <tr class="bold-row"><td>真實淨利</td><td class="r {'green' if int(summary.get('netProfit',0) or 0)>=0 else 'red'}">{money(summary.get("netProfit"))}</td></tr>
      <tr><td>真實淨利率</td><td class="r bold" style="color:{'#15803D' if float(summary.get('netMarginPct',0) or 0)>=20 else '#B45309' if float(summary.get('netMarginPct',0) or 0)>=0 else '#DC2626'}">{float(summary.get("netMarginPct") or 0):.1f}%</td></tr>
    </tbody>
  </table>
</div>
<div class="diff-banner" style="background:{'#F0FDF4' if prof_diff>=0 else '#FFF1F2'};border-color:{'#86EFAC' if prof_diff>=0 else '#FECACA'};color:{diff_clr}">
  {'真實淨利比原始預估高' if prof_diff>=0 else '真實淨利比原始預估低'} NT$ {abs(prof_diff):,}（{'+' if diff_ppts>=0 else ''}{diff_ppts:.1f} ppts）
</div>"""
    else:
        profit_section = (
            '<div class="section-label">三、損益分析</div>'
            '<div class="notice-banner">⚠ 本案尚未完成成本精算（settlement 未 finalized），'
            '以下僅列報價階段的預估數字，實際成本、真實毛利／淨利待精算完結後才會顯示。</div>'
            '<div class="total-box" style="justify-content:flex-start"><div class="total-table" style="width:320px">'
            f'<div class="row"><span>報價稅前收入</span><span>{money(data["pretax"])}</span></div>'
            f'<div class="row"><span>預估淨毛利率</span><span>{float(summary.get("netMarginPct") or 0):.1f}%</span></div>'
            '</div></div>'
        )

    # 四～七是條件式區塊（成本品項／額外支出／派發明細／執行進度都可能沒資料
    # 而整段不顯示），中文數字用一個 iterator 依「實際有顯示的區塊」動態發號，
    # 避免固定寫死「四、五、六、七」在某段被跳過時，編號出現斷層（例如沒有
    # 派發資料時直接從「五」跳到「七」）。
    _cn_nums = iter(["四", "五", "六", "七"])

    # ── 成本品項明細 ─────────────────────────────────────────────────────────
    item_rows_html = "".join(
        f'<tr><td>{esc(it.get("origDescription") or "（無品名）")}</td>'
        f'<td>{esc(it.get("origBrand"))}</td>'
        f'<td class="r">{money(it.get("actualTotalCost")) if it.get("actualTotalCost") else "未填寫"}</td></tr>'
        for it in (s.get("items") or [])
    )
    _no_item_row = '<tr><td colspan="3" class="c" style="color:#9CA3AF">無成本品項資料</td></tr>'
    items_section = (
        f'<div class="section-label">{next(_cn_nums)}、成本品項明細</div>'
        '<table><thead><tr><th>品項</th><th style="width:120px">廠牌</th><th class="r" style="width:110px">實際成本</th></tr></thead>'
        f'<tbody>{item_rows_html or _no_item_row}</tbody></table>'
    ) if s.get("items") else ""

    # ── 額外支出明細 ─────────────────────────────────────────────────────────
    # 單號欄（2026-09-09 新增）：額外支出的憑證編號，會計對帳時要靠它回頭找到
    # 實體憑證，結案報表是對外/存查用的最終文件，這裡沒有就等於帳上有金額卻查
    # 不到憑證出處。舊資料沒有這個欄位，顯示 "—"。
    extra_rows_html = "".join(
        f'<tr><td>{esc(ex.get("category"))}</td><td>{esc(ex.get("description")) or "—"}</td>'
        f'<td class="r">{money(ex.get("totalCost")) if ex.get("totalCost") else "—"}</td>'
        f'<td class="c">{esc(ex.get("expenseDate")) or "—"}</td>'
        f'<td class="c">{esc(ex.get("docNo")) or "—"}</td>'
        f'<td class="c">{esc(ex.get("payerName")) or "—"}</td>'
        # 未核准的要在對外文件上標出來——金額已計入，但看報表的人有權知道它還沒簽完
        f'<td class="c">{esc(ex.get("status")) or "—"}</td>'
        f'<td>{esc("、".join(f.get("filename","") for f in (ex.get("files") or []))) or "—"}</td></tr>'
        for ex in (s.get("extraItems") or [])
    )
    _no_extra_row = '<tr><td colspan="8" class="c" style="color:#9CA3AF">無額外支出資料</td></tr>'
    extras_section = (
        f'<div class="section-label">{next(_cn_nums)}、額外支出明細</div>'
        '<table><thead><tr><th style="width:90px">類別</th><th>說明</th><th class="r" style="width:100px">金額</th>'
        '<th style="width:88px">支出日期</th><th style="width:92px">單號</th>'
        '<th style="width:84px">支出人</th><th style="width:72px">狀態</th><th>發票/收據附件</th></tr></thead>'
        f'<tbody>{extra_rows_html or _no_extra_row}</tbody></table>'
    ) if s.get("extraItems") else ""

    # ── 承攬商／外包派發明細 ────────────────────────────────────────────────
    dispatch_rows_html = "".join(
        f'<tr><td>{esc(dp["vendorName"])}</td><td>{esc(dp["date"])}</td><td>{esc(dp["scope"])}</td>'
        f'<td class="c">{esc(dp["status"])}</td><td class="r">{money(dp["amount"])}</td></tr>'
        for dp in data["dispatches"]
    )
    dispatch_section = (
        f'<div class="section-label">{next(_cn_nums)}、承攬商／外包派發明細</div>'
        '<table><thead><tr><th>承攬商／人員</th><th style="width:90px">派發日期</th><th>派發範圍</th>'
        '<th class="c" style="width:70px">狀態</th><th class="r" style="width:100px">金額</th></tr></thead>'
        f'<tbody>{dispatch_rows_html}</tbody></table>'
    ) if data["dispatches"] else ""

    # ── 執行進度 ─────────────────────────────────────────────────────────────
    def _stage_period(st):
        if st["visitStart"] or st["visitEnd"]:
            a, b = st["visitStart"] or "—", st["visitEnd"] or "—"
            return f'{a} ～ {b}' if a != b else a
        if st["startDate"] or st["dueDate"]:
            return f'{st["startDate"] or "—"} ～ {st["dueDate"] or "—"}'
        return "—"
    stage_rows_html = "".join(
        f'<tr><td>{esc(st["label"])}</td><td>{_stage_period(st)}</td>'
        f'<td class="c">{esc(st["doneAt"]) or "—"}</td>'
        f'<td class="c" style="color:{"#15803D" if st["done"] else "#DC2626" if st["overdue"] else "#9CA3AF"};font-weight:600">'
        f'{"✓ 已完成" if st["done"] else "⚠ 逾期" if st["overdue"] else "進行中"}</td>'
        f'<td>{esc("、".join(st["assignedNames"]))}</td></tr>'
        for st in data["stages"]
    )
    _no_stage_row = '<tr><td colspan="5" class="c" style="color:#9CA3AF">無執行進度階段資料</td></tr>'
    stages_section = (
        f'<div class="section-label">{next(_cn_nums)}、執行進度</div>'
        '<table><thead><tr><th>階段</th><th style="width:150px">期間</th><th class="c" style="width:90px">完成日期</th>'
        '<th class="c" style="width:80px">狀態</th><th style="width:120px">負責人</th></tr></thead>'
        f'<tbody>{stage_rows_html or _no_stage_row}</tbody></table>'
    ) if data["stages"] else ""

    memo_section = (
        f'<div class="section-label">精算備註</div><div class="memo-box">{esc(s.get("memo"))}</div>'
    ) if (s.get("memo") or "").strip() else ""

    gen_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    return (
        '<!DOCTYPE html>\n<html lang="zh-Hant">\n<head>\n<meta charset="UTF-8">\n'
        f'<title>{esc(data["quoteNo"])} 案件結案報表</title>\n'
        '<style>\n'
        '  *{box-sizing:border-box;margin:0;padding:0}\n'
        '  body{font-family:"Microsoft JhengHei","PMingLiU",serif;font-size:12px;color:#0A0A0A;line-height:1.6;background:#fff}\n'
        '  #root{padding:24px 32px}\n'
        '  @page{size:A4;margin:0 13mm 12mm 13mm;@bottom-center{content:counter(page);font-family:Arial,sans-serif;font-size:9px;color:#aaa}}\n'
        '  @media print{html,body{margin:0;padding:0;background:#fff}#root{padding:15mm 0 0}tr{page-break-inside:avoid}'
        '.profit-grid,.diff-banner,.sign{page-break-inside:avoid}}\n'
        '  .accent-bar{height:3px;background:#0A0A0A;margin-bottom:18px}\n'
        '  .header{display:flex;justify-content:space-between;align-items:flex-start;padding-bottom:14px;border-bottom:1px solid #0A0A0A;margin-bottom:16px}\n'
        '  .co-name{font-size:15px;font-weight:700;letter-spacing:.06em}\n'
        '  .co-sub{font-size:10px;color:#888;margin-top:3px;font-family:Arial,sans-serif;letter-spacing:.02em}\n'
        '  .doc-title{font-size:22px;font-weight:700;letter-spacing:.18em;text-align:right}\n'
        '  .meta{display:grid;grid-template-columns:repeat(3,1fr);gap:6px 4px;margin-bottom:16px;font-size:12px;'
        'background:#FAFAF8;padding:10px 12px;border-radius:4px;border:1px solid #EDEAE4}\n'
        '  .meta span{color:#888;font-family:Arial,sans-serif;font-size:11px}\n'
        '  .section-label{font-size:11px;font-weight:700;letter-spacing:.04em;color:#111;margin:16px 0 7px;'
        'display:flex;align-items:center;gap:8px}\n'
        '  .section-label::after{content:"";flex:1;height:1px;background:#EDEAE4}\n'
        '  table{width:100%;border-collapse:collapse;margin-bottom:10px}\n'
        '  thead th{background:#0A0A0A;color:#F5F4F0;padding:7px 8px;text-align:left;font-size:10.5px;font-weight:500;'
        'font-family:Arial,sans-serif;letter-spacing:.03em}\n'
        '  tbody td{padding:6px 8px;border-bottom:1px solid #EDEAE4;font-size:11.5px}\n'
        '  tbody tr:last-child td{border-bottom:none}\n'
        '  tbody tr:nth-child(even) td{background:#FAFAF8}\n'
        '  td.r,th.r{text-align:right;font-family:Arial,sans-serif}\n'
        '  td.c,th.c{text-align:center}\n'
        '  td.bold{font-weight:700}\n'
        '  td.red{color:#DC2626}\n'
        '  td.green{color:#15803D}\n'
        '  td.orange{color:#92400E}\n'
        '  tr.bold-row td{border-top:1.5px solid #E5E7EB;font-weight:700}\n'
        '  .total-box{display:flex;justify-content:flex-end;margin-bottom:14px}\n'
        '  .total-table{width:260px;font-size:12px}\n'
        '  .total-table .row{display:flex;justify-content:space-between;padding:4px 0;font-family:Arial,sans-serif}\n'
        '  .total-table .grand{font-size:14px;font-weight:700;border-top:1px solid #0A0A0A;padding-top:6px;margin-top:2px}\n'
        '  .profit-grid{display:grid;grid-template-columns:1fr 1fr;gap:0;border:1px solid #E5E7EB;border-radius:4px;overflow:hidden}\n'
        '  .profit-grid table{margin-bottom:0}\n'
        '  .profit-grid table:first-child{border-right:1px solid #E5E7EB}\n'
        '  .profit-grid td{padding:5px 10px;font-size:11px}\n'
        '  .diff-banner{margin-top:0;border:1px solid;border-top:none;border-radius:0 0 4px 4px;padding:7px 12px;'
        'font-size:11.5px;font-weight:600;margin-bottom:14px}\n'
        '  .notice-banner{background:#FFFBEB;border:1px solid #FDE68A;color:#92400E;border-radius:4px;'
        'padding:8px 12px;font-size:11px;margin-bottom:10px}\n'
        '  .memo-box{background:#F9FAFB;border:1px solid #E5E7EB;border-radius:4px;padding:10px 12px;font-size:11.5px;'
        'color:#374151;margin-bottom:14px;white-space:pre-wrap}\n'
        '  .sign{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:22px}\n'
        '  .sign-box{border:1px solid #EDEAE4;border-radius:4px;padding:16px 18px;min-height:100px;display:flex;flex-direction:column}\n'
        '  .sign-label{font-size:9px;color:#999;font-family:Arial,sans-serif;letter-spacing:.1em;text-transform:uppercase;margin-bottom:8px}\n'
        '  .sign-line{flex:1;border-bottom:1px solid #ccc;margin:10px 0}\n'
        '  .sign-date{font-size:10px;color:#999;font-family:Arial,sans-serif}\n'
        '  .footer{text-align:center;font-size:10px;color:#999;margin-top:18px;padding-top:12px;border-top:1px solid #EDEAE4;'
        'font-family:Arial,sans-serif;letter-spacing:.04em}\n'
        '</style>\n</head>\n<body>\n<div id="root">\n'
        '<div class="accent-bar"></div>\n'
        '<div class="header">\n  <div>\n'
        + _identity_head(_ident) +
        '  </div>\n  <div>\n    <div class="doc-title">案件結案報表</div>\n'
        f'    <div class="co-sub" style="text-align:right;margin-top:4px">產出時間：{gen_at}</div>\n  </div>\n</div>\n'
        '<div class="meta">\n'
        f'  <div><span>案號：</span><strong style="font-family:Arial,sans-serif">{esc(data["quoteNo"])}</strong></div>\n'
        f'  <div><span>客戶：</span>{esc(data["customer"])}</div>\n'
        f'  <div><span>專案：</span>{esc(data["project"])}</div>\n'
        f'  <div><span>業務員：</span>{esc(data["salesPerson"])}</div>\n'
        f'  <div><span>報價日期：</span>{esc(data["quoteDate"])}</div>\n'
        f'  <div><span>成案日期：</span>{esc(data["wonAt"]) or "—"}</div>\n'
        f'  <div><span>結案日期：</span>{esc(data["closedAt"]) or "—"}</div>\n'
        f'  <div><span>精算狀態：</span>{"已完結精算" if is_finalized else "尚未完成精算"}</div>\n'
        '</div>\n'
        '<div class="section-label">一、收入與合約金額</div>\n'
        '<div class="total-box" style="justify-content:flex-start"><div class="total-table" style="width:320px">\n'
        f'  <div class="row"><span>合約總額（含稅）</span><span>NT$ {money(data["total"])}</span></div>\n'
        f'  <div class="row"><span>稅前收入</span><span>NT$ {money(data["pretax"])}</span></div>\n'
        f'  <div class="row grand"><span>營業稅（5%）</span><span>NT$ {money(data["taxAmount"])}</span></div>\n'
        '</div></div>\n'
        f'{payment_section}\n'
        f'{profit_section}\n'
        f'{items_section}\n'
        f'{extras_section}\n'
        f'{dispatch_section}\n'
        f'{stages_section}\n'
        f'{memo_section}\n'
        '<div class="sign">\n'
        '  <div class="sign-box">\n    <div class="sign-label">案件負責人 · 完結確認</div>\n'
        f'    <div class="sign-line"></div>\n    <div class="sign-date">完結日期：{esc(data["closedAt"]) or "＿＿＿＿＿＿＿＿＿＿"}</div>\n  </div>\n'
        '  <div class="sign-box">\n    <div class="sign-label">財務主管 · 覆核</div>\n'
        '    <div class="sign-line"></div>\n    <div class="sign-date">覆核日期：＿＿＿＿＿＿＿＿＿＿</div>\n  </div>\n'
        '</div>\n'
        '<div class="footer">\n  本文件含案件內部財務與成本資訊，僅供內部留存查核使用，不對外提供 ｜ '
        + _identity_foot_short(_ident) +
        '</div>\n</body>\n</html>'
    )


def generate_case_closing_pdf_bytes(quote_no: str) -> bytes:
    """Edge Headless 產生案件結案報表 PDF 並以 bytes 回傳（供 API 下載使用）。"""
    edge = _get_edge_path()
    data = _case_closing_report_data(quote_no)
    html_content = _build_case_closing_html(data)
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
                try: os.unlink(p)
                except Exception: pass


def _generate_case_closing_pdf(quote_no: str, actor: str = '', action_type: str = '結案報表'):
    """存檔＋稽核版案件結案報表 PDF 產生，於案件標記已結案後背景觸發。"""
    try:
        edge = _get_edge_path()
    except RuntimeError as e:
        logger.warning("Edge not found, case closing report PDF generation skipped: %s", e)
        _pdf_audit(quote_no, False, str(e), actor, action_type)
        return

    safe_actor = re.sub(r'[\\/:*?"<>|\s]', '_', actor or '').strip('_')[:20]

    tmp_html = None
    pdf_path = ""
    try:
        data = _case_closing_report_data(quote_no)
        html_content = _build_case_closing_html(data)

        today   = date.today().strftime('%Y%m%d')
        out_dir = os.path.join(_get_case_closing_pdf_base(), date.today().isoformat())
        os.makedirs(out_dir, exist_ok=True)

        if safe_actor:
            base_name = f"{quote_no}_{action_type}_{today}_{safe_actor}"
        else:
            base_name = f"{quote_no}_{action_type}_{today}"

        pdf_path = os.path.join(out_dir, f"{base_name}.pdf")
        if os.path.exists(pdf_path):
            for i in range(2, 20):
                candidate = os.path.join(out_dir, f"{base_name}_{i}.pdf")
                if not os.path.exists(candidate):
                    pdf_path = candidate
                    break

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.html', encoding='utf-8', delete=False
        ) as f:
            f.write(html_content)
            tmp_html = f.name

        file_url = 'file:///' + tmp_html.replace('\\', '/')
        run_edge_pdf(
            [edge, '--headless', '--disable-gpu', '--no-sandbox',
             f'--print-to-pdf={pdf_path}',
             '--no-pdf-header-footer',
             '--run-all-compositor-stages-before-draw',
             file_url]
        )
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
            logger.info("Case closing report PDF saved: %s", pdf_path)
            _pdf_audit(quote_no, True, pdf_path, actor, action_type)
            try:
                with open(pdf_path, 'rb') as f:
                    pdf_bytes = f.read()
                notify_case_closing_report(quote_no, data.get("customer", ""), data.get("project", ""), pdf_bytes)
            except Exception:
                logger.exception("notify_case_closing_report failed for %s", quote_no)
        else:
            logger.warning("Case closing report PDF not created for %s (Edge ran but no output file)", quote_no)
            _pdf_audit(quote_no, False, "Edge 執行完畢但未產生 PDF 檔案", actor, action_type)
    except Exception as e:
        logger.exception("_generate_case_closing_pdf failed for %s", quote_no)
        _pdf_audit(quote_no, False, str(e), actor, action_type)
    finally:
        if tmp_html:
            try:
                os.unlink(tmp_html)
            except Exception:
                pass


# ── 專案執行報告（2026-08-26 專案管理併入案件管理）─────────────────────────────
# 跟結案報表（_case_closing_report_data）同一套資料組裝風格，但：①任何時候都能
# 匯出，不檢查是否已結案；②內容聚焦「執行過程」而非財務損益——執行進度、叫料
# 管控、代辦事項兩階段簽核狀態、工作日誌時間軸（含照片，用檔名/上傳者列出，不
# 內嵌圖檔，避免大量圖片讓 PDF 過大且拖慢 Edge headless 轉檔）、近期動態摘要。

def _project_execution_report_data(quote_no: str) -> dict:
    conn = get_db()
    row = conn.execute("""
        SELECT quote_no, customer_name, project_name, sales_person, quote_date,
               COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') AS deal_tag,
               data_json, assigned_user_ids
        FROM quotations WHERE quote_no=?
    """, (quote_no,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("案件不存在")

    d  = json.loads(row["data_json"] or "{}")
    cr = d.get("caseRecord") or {}

    dn_map = {
        r["username"]: (r["display_name"] or r["username"])
        for r in conn.execute("SELECT username, display_name FROM users").fetchall()
    }
    uid_name_map = {
        r["id"]: (r["display_name"] or r["username"])
        for r in conn.execute("SELECT id, username, display_name FROM users").fetchall()
    }

    # 執行進度：跟 _case_closing_report_data() 同一段查詢
    stage_rows = conn.execute(
        "SELECT label, start_date, due_date, done, done_at, assigned_to, "
        "(SELECT MIN(visit_date) FROM case_stage_visits WHERE stage_id=case_stages.id AND visit_date!='') AS visit_start, "
        "(SELECT MAX(visit_date) FROM case_stage_visits WHERE stage_id=case_stages.id AND visit_date!='') AS visit_end "
        "FROM case_stages WHERE quote_no=? ORDER BY sort_order, id",
        (quote_no,)
    ).fetchall()
    today = date.today().isoformat()
    stages = []
    for r in stage_rows:
        done = bool(r["done"])
        due  = r["due_date"] or ""
        assigned = [u for u in json.loads(r["assigned_to"] or "[]") if u]
        stages.append({
            "label":         r["label"] or "（未命名階段）",
            "startDate":     r["start_date"] or "",
            "dueDate":       due,
            "doneAt":        (r["done_at"] or "")[:10],
            "visitStart":    r["visit_start"] or "",
            "visitEnd":      r["visit_end"] or "",
            "done":          done,
            "overdue":       (not done) and bool(due) and due < today,
            "assignedNames": [dn_map.get(u, u) for u in assigned],
        })

    # 叫料管控
    materials = [{
        "name":     m.get("name") or m.get("description") or "（未命名料件）",
        "spec":     m.get("spec") or "",
        "qty":      m.get("qty") or "",
        "status":   m.get("status") or "",
        "eta":      m.get("eta") or "",
    } for m in (cr.get("materials") or [])]

    # 代辦事項（兩階段簽核）
    action_items = [{
        "text":           r["text"],
        "status":         r["status"],
        "stage1Approver": r["stage1_approver"] or "",
        "stage1At":       (r["stage1_at"] or "")[:16],
        "stage2Approver": r["stage2_approver"] or "",
        "stage2At":       (r["stage2_at"] or "")[:16],
    } for r in conn.execute(
        "SELECT * FROM case_action_items WHERE quote_no=? ORDER BY sort_order, id", (quote_no,)
    ).fetchall()]

    # 工作日誌時間軸（含照片，僅列檔名/上傳者，不內嵌圖檔）
    work_logs = []
    for r in conn.execute(
        "SELECT log_date, user_id, content, hours, photos, contact_type FROM work_logs "
        "WHERE case_no=? ORDER BY log_date DESC, id DESC", (quote_no,)
    ).fetchall():
        photos = json.loads(r["photos"] or "[]")
        work_logs.append({
            "logDate":  r["log_date"] or "",
            "author":   uid_name_map.get(r["user_id"], "未知"),
            "content":  r["content"] or "",
            "hours":    r["hours"],
            "contactType": r["contact_type"] or "",
            "photoCount": len(photos),
            "photoNames": [p.get("filename", "") for p in photos],
        })

    # 近期動態摘要（人工留言，最新 15 則；工作日誌已在上方獨立列出，這裡不重複）
    feed = [{
        "author":  dn_map.get(r["author"], r["author"]),
        "content": r["content"],
        "at":      r["created_at"],
    } for r in conn.execute(
        "SELECT author, content, created_at FROM case_updates WHERE quote_no=? "
        "ORDER BY created_at DESC LIMIT 15", (quote_no,)
    ).fetchall()]

    assigned_names = [dn_map.get(uid_name_map.get(uid, ""), uid_name_map.get(uid, str(uid)))
                       for uid in json.loads(row["assigned_user_ids"] or "[]")]

    conn.close()
    return {
        "quoteNo":      row["quote_no"],
        "customer":     row["customer_name"] or "",
        "project":      row["project_name"] or "",
        "salesPerson":  row["sales_person"] or "",
        "quoteDate":    row["quote_date"] or "",
        "dealTag":      row["deal_tag"] or "",
        "assignedNames": assigned_names,
        "stages":       stages,
        "materials":    materials,
        "actionItems":  action_items,
        "workLogs":     work_logs,
        "feed":         feed,
    }


def _build_project_execution_report_html(data: dict) -> str:
    # 🔑 QL7：抬頭從**這一筆單據所屬的據點**取值，一支函式取一次。
    # ⚠️ 取不到 `locationId` ⇒ `location_identity(None)` 落在主要據點，
    #    那是既有安裝（只有一個據點、或根本沒設過）的正確行為。
    # 🔴 `QL25`（依據使用者 2026-09-23 裁示）：這份單據的抬頭要跟著
    #    報價單送出那一刻凍結的快照走（若有）——`apply_snapshot()` 疊
    #    在即時值上，只覆蓋抬頭五欄。銀行欄位不受影響：`QL10` 沒有被
    #    翻掉，它管的是別的欄位，此處若有銀行欄位仍然一律即時值。
    _ident = apply_snapshot(location_identity(_location_of(data)), data)
    def esc(s):
        return (str(s) if s is not None else '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')

    def _stage_period(st):
        if st["visitStart"] or st["visitEnd"]:
            a, b = st["visitStart"] or "—", st["visitEnd"] or "—"
            return f'{a} ～ {b}' if a != b else a
        if st["startDate"] or st["dueDate"]:
            return f'{st["startDate"] or "—"} ～ {st["dueDate"] or "—"}'
        return "—"

    stage_rows_html = "".join(
        f'<tr><td>{esc(st["label"])}</td><td>{_stage_period(st)}</td>'
        f'<td class="c">{esc(st["doneAt"]) or "—"}</td>'
        f'<td class="c" style="color:{"#15803D" if st["done"] else "#DC2626" if st["overdue"] else "#9CA3AF"};font-weight:600">'
        f'{"✓ 已完成" if st["done"] else "⚠ 逾期" if st["overdue"] else "進行中"}</td>'
        f'<td>{esc("、".join(st["assignedNames"]))}</td></tr>'
        for st in data["stages"]
    )
    _no_stage_row = '<tr><td colspan="5" class="c" style="color:#9CA3AF">無執行進度階段資料</td></tr>'
    stages_section = (
        '<div class="section-label">一、執行進度</div>'
        '<table><thead><tr><th>階段</th><th style="width:150px">期間</th><th class="c" style="width:90px">完成日期</th>'
        '<th class="c" style="width:80px">狀態</th><th style="width:120px">負責人</th></tr></thead>'
        f'<tbody>{stage_rows_html or _no_stage_row}</tbody></table>'
    )

    mat_rows_html = "".join(
        f'<tr><td>{esc(m["name"])}</td><td>{esc(m["spec"])}</td><td class="c">{esc(m["qty"])}</td>'
        f'<td class="c">{esc(m["status"]) or "—"}</td><td class="c">{esc(m["eta"]) or "—"}</td></tr>'
        for m in data["materials"]
    )
    _no_mat_row = '<tr><td colspan="5" class="c" style="color:#9CA3AF">無叫料管控資料</td></tr>'
    materials_section = (
        '<div class="section-label">二、叫料管控</div>'
        '<table><thead><tr><th>料件</th><th>規格</th><th class="c" style="width:70px">數量</th>'
        '<th class="c" style="width:90px">狀態</th><th class="c" style="width:100px">預計到貨</th></tr></thead>'
        f'<tbody>{mat_rows_html or _no_mat_row}</tbody></table>'
    )

    def _item_status(it):
        if it["status"] == "done":
            return '<span style="color:#15803D;font-weight:600">✓ 已完成</span>'
        if it["status"] == "stage1_done":
            return '<span style="color:#B45309;font-weight:600">工程已確認，待業務確認</span>'
        return '<span style="color:#9CA3AF">待確認</span>'
    item_rows_html = "".join(
        f'<tr><td>{esc(it["text"])}</td><td class="c">{_item_status(it)}</td>'
        f'<td>{esc(it["stage1Approver"]) or "—"}{"　" + esc(it["stage1At"]) if it["stage1At"] else ""}</td>'
        f'<td>{esc(it["stage2Approver"]) or "—"}{"　" + esc(it["stage2At"]) if it["stage2At"] else ""}</td></tr>'
        for it in data["actionItems"]
    )
    _no_item_row = '<tr><td colspan="4" class="c" style="color:#9CA3AF">無待辦事項資料</td></tr>'
    action_items_section = (
        '<div class="section-label">三、待辦事項（兩階段簽核）</div>'
        '<table><thead><tr><th>事項</th><th class="c" style="width:180px">狀態</th>'
        '<th style="width:160px">工程主管確認</th><th style="width:160px">業務主管確認</th></tr></thead>'
        f'<tbody>{item_rows_html or _no_item_row}</tbody></table>'
    )

    wl_rows_html = "".join(
        f'<tr><td class="c" style="width:90px">{esc(wl["logDate"])}</td><td style="width:90px">{esc(wl["author"])}</td>'
        f'<td>{esc(wl["content"])}</td><td class="c" style="width:90px">{esc(wl["contactType"]) or "—"}</td>'
        f'<td class="c" style="width:70px">{wl["photoCount"] or "—"}</td></tr>'
        for wl in data["workLogs"]
    )
    _no_wl_row = '<tr><td colspan="5" class="c" style="color:#9CA3AF">無工作日誌資料</td></tr>'
    work_logs_section = (
        '<div class="section-label">四、工作日誌</div>'
        '<table><thead><tr><th class="c">日期</th><th>記錄人</th><th>內容</th><th class="c">聯絡事項</th><th class="c">照片數</th></tr></thead>'
        f'<tbody>{wl_rows_html or _no_wl_row}</tbody></table>'
    )

    feed_rows_html = "".join(
        f'<tr><td class="c" style="width:130px">{esc((f["at"] or "")[:16])}</td>'
        f'<td style="width:90px">{esc(f["author"])}</td><td>{esc(f["content"])}</td></tr>'
        for f in data["feed"]
    )
    _no_feed_row = '<tr><td colspan="3" class="c" style="color:#9CA3AF">無動態留言紀錄</td></tr>'
    feed_section = (
        '<div class="section-label">五、近期動態（最新 15 則留言）</div>'
        '<table><thead><tr><th class="c">時間</th><th>發布人</th><th>內容</th></tr></thead>'
        f'<tbody>{feed_rows_html or _no_feed_row}</tbody></table>'
    )

    gen_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    return (
        '<!DOCTYPE html>\n<html lang="zh-Hant">\n<head>\n<meta charset="UTF-8">\n'
        f'<title>{esc(data["quoteNo"])} 專案執行報告</title>\n'
        '<style>\n'
        '  *{box-sizing:border-box;margin:0;padding:0}\n'
        '  body{font-family:"Microsoft JhengHei","PMingLiU",serif;font-size:12px;color:#0A0A0A;line-height:1.6;background:#fff}\n'
        '  #root{padding:24px 32px}\n'
        '  @page{size:A4;margin:0 13mm 12mm 13mm;@bottom-center{content:counter(page);font-family:Arial,sans-serif;font-size:9px;color:#aaa}}\n'
        '  @media print{html,body{margin:0;padding:0;background:#fff}#root{padding:15mm 0 0}tr{page-break-inside:avoid}}\n'
        '  .accent-bar{height:3px;background:#0A0A0A;margin-bottom:18px}\n'
        '  .header{display:flex;justify-content:space-between;align-items:flex-start;padding-bottom:14px;border-bottom:1px solid #0A0A0A;margin-bottom:16px}\n'
        '  .co-name{font-size:15px;font-weight:700;letter-spacing:.06em}\n'
        '  .co-sub{font-size:10px;color:#888;margin-top:3px;font-family:Arial,sans-serif;letter-spacing:.02em}\n'
        '  .doc-title{font-size:22px;font-weight:700;letter-spacing:.18em;text-align:right}\n'
        '  .meta{display:grid;grid-template-columns:repeat(3,1fr);gap:6px 4px;margin-bottom:16px;font-size:12px;'
        'background:#FAFAF8;padding:10px 12px;border-radius:4px;border:1px solid #EDEAE4}\n'
        '  .meta span{color:#888;font-family:Arial,sans-serif;font-size:11px}\n'
        '  .section-label{font-size:11px;font-weight:700;letter-spacing:.04em;color:#111;margin:16px 0 7px;'
        'display:flex;align-items:center;gap:8px}\n'
        '  .section-label::after{content:"";flex:1;height:1px;background:#EDEAE4}\n'
        '  table{width:100%;border-collapse:collapse;margin-bottom:10px}\n'
        '  thead th{background:#0A0A0A;color:#F5F4F0;padding:7px 8px;text-align:left;font-size:10.5px;font-weight:500;'
        'font-family:Arial,sans-serif;letter-spacing:.03em}\n'
        '  tbody td{padding:6px 8px;border-bottom:1px solid #EDEAE4;font-size:11.5px}\n'
        '  tbody tr:last-child td{border-bottom:none}\n'
        '  tbody tr:nth-child(even) td{background:#FAFAF8}\n'
        '  td.r,th.r{text-align:right;font-family:Arial,sans-serif}\n'
        '  td.c,th.c{text-align:center}\n'
        '  .footer{text-align:center;font-size:10px;color:#999;margin-top:18px;padding-top:12px;border-top:1px solid #EDEAE4;'
        'font-family:Arial,sans-serif;letter-spacing:.04em}\n'
        '</style>\n</head>\n<body>\n<div id="root">\n'
        '<div class="accent-bar"></div>\n'
        '<div class="header">\n  <div>\n'
        + _identity_head(_ident) +
        '  </div>\n  <div>\n    <div class="doc-title">專案執行報告</div>\n'
        f'    <div class="co-sub" style="text-align:right;margin-top:4px">產出時間：{gen_at}</div>\n  </div>\n</div>\n'
        '<div class="meta">\n'
        f'  <div><span>案號：</span><strong style="font-family:Arial,sans-serif">{esc(data["quoteNo"])}</strong></div>\n'
        f'  <div><span>客戶：</span>{esc(data["customer"])}</div>\n'
        f'  <div><span>專案：</span>{esc(data["project"])}</div>\n'
        f'  <div><span>業務員：</span>{esc(data["salesPerson"])}</div>\n'
        f'  <div><span>案件狀態：</span>{esc(data["dealTag"]) or "—"}</div>\n'
        f'  <div><span>分配成員：</span>{esc("、".join(data["assignedNames"])) or "—"}</div>\n'
        '</div>\n'
        f'{stages_section}\n'
        f'{materials_section}\n'
        f'{action_items_section}\n'
        f'{work_logs_section}\n'
        f'{feed_section}\n'
        '<div class="footer">\n  本文件彙整案件執行過程資訊，僅供內部留存查核使用 ｜ '
        + _identity_foot_short(_ident) +
        '</div>\n</body>\n</html>'
    )


def generate_project_execution_report_pdf_bytes(quote_no: str) -> bytes:
    """Edge Headless 產生專案執行報告 PDF 並以 bytes 回傳（供 API 下載使用），
    任何時候皆可產出，不像結案報表限已結案案件。"""
    edge = _get_edge_path()
    data = _project_execution_report_data(quote_no)
    html_content = _build_project_execution_report_html(data)
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
                try: os.unlink(p)
                except Exception: pass
