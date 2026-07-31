"""Server-side PDF generation via Edge headless print."""
import json
import os
import re
import subprocess
import tempfile
import logging
from datetime import datetime, date

from db import get_db, is_demo_mode, DEMO_PDF_ARCHIVE_DIR, DEMO_SHIPPING_PDF_ARCHIVE_DIR
from helpers import _get_edge_path, _get_setting

logger = logging.getLogger(__name__)

_PDF_BASE_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "報價單PDF",
)

_SHIPPING_PDF_BASE_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "出貨單PDF",
)


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


def _build_quote_html(q: dict, tot: dict, internal: bool = False,
                      show_watermark: bool = False, watermark_text: str = '未成案 · 報價單僅供瀏覽',
                      watermark_font_size: int = 30,
                      show_notice: bool = False, notice_text: str = '') -> str:
    def esc(s):
        return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')
    ps = q.get('pdfShow') or {}

    items = q.get('items', [])
    item_rows = ''
    real_idx = 0
    for i, item in enumerate(items):
        if item.get('type') == 'header':
            colspan = 9 if internal else 7
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
                f'<td>{esc(item.get("notes",""))}</td>'
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
                f'<td>{esc(item.get("notes",""))}</td>'
                f'</tr>'
            )

    subtotal = tot.get('subtotal', 0)
    pretax   = tot.get('pretax', 0)
    tax      = tot.get('tax', 0)
    total    = tot.get('total', 0)
    tax_rate = q.get('taxRate', 5)
    freight  = q.get('freight', 0) or 0
    discount = q.get('discount', 0) or 0

    freight_row  = f'<div class="total-row"><span>運費</span><span>NT$ {int(freight):,}</span></div>' if freight else ''
    discount_row = f'<div class="total-row"><span style="color:#DC2626">折讓</span><span style="color:#DC2626">-NT$ {int(discount):,}</span></div>' if discount else ''

    def term_block(title, text):
        t = (text or '').strip()
        if not t:
            return ''
        return f'<div style="margin-bottom:10px"><div class="term-title">{esc(title)}</div><div class="term-block">{esc(t)}</div></div>'

    terms_html  = term_block('付款條件', q.get('paymentTerms', ''))
    terms_html += term_block('交貨條件', q.get('deliveryTerms', ''))
    terms_html += term_block('驗收標準', q.get('acceptanceTerms', ''))
    terms_html += term_block('保固條件', q.get('warrantyTerms', ''))
    terms_html += term_block('售後服務', q.get('afterSales', ''))

    terms_section = (
        '<div class="terms"><div class="section-label" style="margin-bottom:8px">五、報價條件</div>'
        + terms_html + '</div>'
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
        '  @media print{html,body{margin:0;padding:0;background:#fff}#root{padding:15mm 0 0}.sign{page-break-inside:avoid}.totals{page-break-inside:avoid}.terms{page-break-inside:avoid}tr{page-break-inside:avoid}}\n'
        '  .cost-cell{background:#FFF8F0}\n'
        '  .cost-banner{background:#FFF3E0;border:1px solid #F59E0B;border-radius:4px;padding:6px 12px;font-size:10px;color:#92400E;margin-bottom:10px;font-family:Arial,sans-serif;letter-spacing:.04em}\n'
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
        '  .totals{max-width:290px;margin-left:auto;border:1px solid #EDEAE4;border-radius:4px;overflow:hidden;margin-bottom:16px}\n'
        '  .total-row{display:flex;justify-content:space-between;padding:7px 13px;border-bottom:1px solid #F0EEE9;font-size:12px}\n'
        '  .total-row:last-child{border-bottom:none;font-weight:700;font-size:14px;background:#F5F4F0;border-top:1.5px solid #0A0A0A}\n'
        '  .total-row span:last-child{font-family:Arial,sans-serif}\n'
        '  .terms{margin-bottom:16px}\n'
        '  .term-block{font-size:11px;color:#444;line-height:1.8}\n'
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
        '    <div class="co-name">允碩整合集創股份有限公司</div>\n'
        '    <div class="co-sub">MOTRIX Synergy Integration Corp.</div>\n'
        '    <div class="co-sub" style="margin-top:4px">統一編號：60575481　｜　電話：04-3602-2818　｜　info@miactw.com</div>\n'
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
        '      <th>品名 / 規格說明</th>\n'
        '      <th>廠牌 / 型號</th>\n'
        '      <th class="r" style="width:48px">數量</th>\n'
        '      <th style="width:38px">單位</th>\n'
        + ('      <th class="r cost-cell" style="width:100px">單位成本</th>\n'
           '      <th class="r cost-cell" style="width:64px">毛利率</th>\n' if internal else '')
        + '      <th class="r" style="width:120px">單價（未稅額）</th>\n'
        '      <th class="r" style="width:120px">金額（未稅）</th>\n'
        '      <th style="width:72px">備註</th>\n'
        '    </tr>\n'
        '  </thead>\n'
        + f'  <tbody>{item_rows}</tbody>\n'
        '</table>\n'
        '<div class="section-label" style="margin-bottom:8px;margin-top:14px;color:#666">四、報價合計</div>\n'
        '<div class="totals">\n'
        f'  <div class="total-row"><span>品項小計</span><span>NT$ {int(subtotal):,}</span></div>\n'
        f'  {freight_row}\n'
        f'  {discount_row}\n'
        f'  <div class="total-row"><span>稅前合計</span><span>NT$ {int(pretax):,}</span></div>\n'
        f'  <div class="total-row"><span>營業稅 {tax_rate}%</span><span>NT$ {int(tax):,}</span></div>\n'
        f'  <div class="total-row"><span>總　計</span><span>NT$ {int(total):,}</span></div>\n'
        '</div>\n'
        f'{terms_section}\n'
        '<div style="height:32px"></div>\n'
        '<div class="sign">\n'
        '  <div class="sign-box">\n'
        '    <div class="sign-label">買方確認 · 簽章蓋印</div>\n'
        f'    <div style="font-size:12px;color:#333;flex:1">{esc(q.get("customerName",""))}</div>\n'
        '  </div>\n'
        '</div>\n'
        '<div class="footer">\n'
        '  MOTRIX Synergy Integration Corp. 允碩整合集創 ｜ info@miactw.com ｜ Tel: 04-3602-2818 ｜ 統一編號: 60575481\n'
        '</div>\n'
        '</div>\n'
        '<script>\n'
        'window.addEventListener("load",function(){\n'
        '  var r=document.getElementById("root");if(!r)return;\n'
        '  var A4H=Math.round(267/25.4*96);\n'
        '  var h=r.scrollHeight;\n'
        '  if(h>A4H){var s=A4H/h;if(s>=0.70){r.style.zoom=s.toFixed(4);}}\n'
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


def generate_pdf_bytes(quote_no: str, internal: bool = False) -> bytes:
    """Edge Headless 產生 PDF 並以 bytes 回傳（供 API 下載使用）。"""
    edge = _get_edge_path()
    conn = get_db()
    row  = conn.execute(
        "SELECT data_json, status, deal_tag FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    conn.close()
    if not row:
        raise ValueError("報價單不存在")
    q            = json.loads(row["data_json"] or "{}")
    deal_tag     = row["deal_tag"] or q.get("dealTag") or ""
    status       = row["status"] or ""
    show_wm      = (deal_tag == "未成案") or (status != "已送出")
    wm_text      = "本案報價未成立　僅供存查備存" if deal_tag == "未成案" else "報價單預覽稿　尚未正式生效"
    is_unsettled = deal_tag == "未成案"
    html_content = _build_quote_html(q, q.get("tot", {}), internal=internal,
                                     show_watermark=show_wm, watermark_text=wm_text,
                                     watermark_font_size=18 if is_unsettled else 28,
                                     show_notice=is_unsettled,
                                     notice_text="本案報價未成立，此份文件僅供存查備存使用，請勿對外提供或引用")
    tmp_html = tmp_pdf = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', encoding='utf-8', delete=False) as f:
            f.write(html_content)
            tmp_html = f.name
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            tmp_pdf = f.name
        file_url = 'file:///' + tmp_html.replace('\\', '/')
        subprocess.run(
            [edge, '--headless', '--disable-gpu', '--no-sandbox',
             f'--print-to-pdf={tmp_pdf}',
             '--no-pdf-header-footer',
             '--run-all-compositor-stages-before-draw',
             file_url],
            timeout=40, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
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

def _build_payslip_html(d: dict) -> str:
    def esc(s): return (s or '').replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('\n','<br>')
    def amt(n): return f"NT$ {int(n):,}" if n else "NT$ 0"
    def pct(r): return (f"{r*100:.2f}".rstrip('0').rstrip('.') + '%') if r else '0%'

    company  = d.get('companyName', '')
    tax_id   = d.get('companyTaxId', '')
    contact  = d.get('companyContactInfo', '')
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
            '\n<div class="section-title">六、備注</div>'
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
<table>
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
        subprocess.run(
            [edge, '--headless', '--disable-gpu', '--no-sandbox',
             f'--print-to-pdf={tmp_pdf}',
             '--no-pdf-header-footer',
             '--run-all-compositor-stages-before-draw',
             file_url],
            timeout=40, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
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
            "SELECT data_json, status, deal_tag FROM quotations WHERE quote_no=?", (quote_no,)
        ).fetchone()
        conn.close()
        if not row:
            return
        q        = json.loads(row["data_json"] or "{}")
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

        today   = date.today().strftime('%Y%m%d')
        out_dir = os.path.join(_get_pdf_base(), date.today().isoformat())
        os.makedirs(out_dir, exist_ok=True)

        # build filename: MQ-202507-001_已簽核_20260716_Jeff.pdf
        if safe_actor:
            base_name = f"{quote_no}_{action_type}_{today}_{safe_actor}"
        else:
            base_name = f"{quote_no}_{action_type}_{today}"

        pdf_path = os.path.join(out_dir, f"{base_name}.pdf")
        if os.path.exists(pdf_path):
            for n in range(2, 20):
                candidate = os.path.join(out_dir, f"{base_name}_{n}.pdf")
                if not os.path.exists(candidate):
                    pdf_path = candidate
                    break

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.html', encoding='utf-8', delete=False
        ) as f:
            f.write(html_content)
            tmp_html = f.name

        file_url = 'file:///' + tmp_html.replace('\\', '/')
        subprocess.run(
            [edge, '--headless', '--disable-gpu', '--no-sandbox',
             f'--print-to-pdf={pdf_path}',
             '--no-pdf-header-footer',
             '--run-all-compositor-stages-before-draw',
             file_url],
            timeout=40, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
            logger.info("PDF saved: %s", pdf_path)
            _pdf_audit(quote_no, True, pdf_path, actor, action_type)
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

    return (
        '<!DOCTYPE html>\n'
        '<html lang="zh-Hant">\n'
        '<head>\n'
        '<meta charset="UTF-8">\n'
        f'<title>{esc(n.get("noteNo",""))} 出貨單</title>\n'
        '<style>\n'
        '  *{box-sizing:border-box;margin:0;padding:0}\n'
        '  body{font-family:"Microsoft JhengHei","PMingLiU",serif;font-size:13px;color:#0A0A0A;line-height:1.6;background:#fff}\n'
        '  #root{padding:24px 32px}\n'
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
        '<div class="accent-bar"></div>\n'
        '<div class="header">\n'
        '  <div>\n'
        '    <div class="co-name">允碩整合集創股份有限公司</div>\n'
        '    <div class="co-sub">MOTRIX Synergy Integration Corp.</div>\n'
        '    <div class="co-sub" style="margin-top:4px">統一編號：60575481　｜　電話：04-3602-2818　｜　info@miactw.com</div>\n'
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
        '    <div class="sign-label">客戶簽收 · 簽章蓋印</div>\n'
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
        '  MOTRIX Synergy Integration Corp. 允碩整合集創 ｜ info@miactw.com ｜ Tel: 04-3602-2818 ｜ 統一編號: 60575481\n'
        '</div>\n'
        '</div>\n'
        '<script>\n'
        'window.addEventListener("load",function(){\n'
        '  var r=document.getElementById("root");if(!r)return;\n'
        '  var A4H=Math.round(267/25.4*96);\n'
        '  var h=r.scrollHeight;\n'
        '  if(h>A4H){var s=A4H/h;if(s>=0.70){r.style.zoom=s.toFixed(4);}}\n'
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
        subprocess.run(
            [edge, '--headless', '--disable-gpu', '--no-sandbox',
             f'--print-to-pdf={tmp_pdf}',
             '--no-pdf-header-footer',
             '--run-all-compositor-stages-before-draw',
             file_url],
            timeout=40, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
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
        subprocess.run(
            [edge, '--headless', '--disable-gpu', '--no-sandbox',
             f'--print-to-pdf={pdf_path}',
             '--no-pdf-header-footer',
             '--run-all-compositor-stages-before-draw',
             file_url],
            timeout=40, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
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
