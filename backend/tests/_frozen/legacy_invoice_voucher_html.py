# -*- coding: utf-8 -*-
"""凍結的正對照：P2 改版前的 `pdf_gen._build_invoice_voucher_html`（逐字抽取自 platform，2026-09-25）。

🔴 不可以修改這支檔：它是「版型化之後輸出與改版前逐位元組相同」的比對基準。
   抬頭／頁尾／簽核紀錄三個片段仍呼叫 pdf_gen 現行的共用函式（那些不在 P2 範圍）。
"""
from pdf_gen import apply_snapshot, location_identity, _location_of, _identity_head, _identity_foot, _voucher_sign_html  # noqa: F401


def legacy_build_invoice_voucher_html(v: dict) -> str:
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
    selected_items = v.get('selectedItems') or []
    quote_items = v.get('quoteItems') or []

    if scope == 'items':
        scope_label = '自訂品項'
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
            '<div class="section-label">三、申請品項明細（未稅，稅額另計，見下方總額）</div>\n'
            '<table>\n  <thead><tr><th style="width:24px">#</th><th>品名 / 規格</th>'
            '<th class="r" style="width:44px">數量</th><th style="width:40px">單位</th>'
            '<th class="r" style="width:70px">單價（未稅）</th><th class="r" style="width:90px">金額（未稅）</th></tr></thead>\n'
            f'  <tbody>{sel_rows}</tbody>\n</table>\n'
        )
        quote_items_html = ''   # 已選品項本身就是要開的內容，不用再重複列一次全部報價品項參考
    else:
        scope_label = '自訂金額'
        items_table_html = (
            '<div class="section-label">三、申請金額</div>\n'
            '<div class="boxes" style="grid-template-columns:1fr">\n'
            '  <div class="box">\n'
            f'    <div class="row"><span class="label">申請金額（含稅）</span>'
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
                '<div class="section-label">四、開票品項參考（報價單內容）</div>\n'
                '<table>\n  <thead><tr><th style="width:24px">#</th><th>品名 / 規格</th>'
                '<th class="r" style="width:44px">數量</th><th style="width:40px">單位</th>'
                '<th class="r" style="width:70px">單價</th><th class="r" style="width:90px">金額</th></tr></thead>\n'
                f'  <tbody>{quote_item_rows}</tbody>\n</table>\n'
            )

    applicant_name = (v.get('approval') or {}).get('requestedByDisplay') or v.get('createdBy', '')
    applicant_date = ((v.get('approval') or {}).get('requestedAt') or v.get('createdAt') or '')[:10]

    is_final = v.get('status') == '已核准'
    watermark_html = '' if is_final else (
        '<div class="wm">' + ''.join(
            '<div class="wm-item"><b>憑據預覽稿</b><small>尚未正式核准</small></div>'
            for _ in range(12)
        ) + '</div>'
    )
    banner_html = '' if is_final else (
        f'<div class="preview-banner">⚠ 此為開票申請憑據預覽稿（目前狀態：{esc(v.get("status") or "草稿")}），'
        f'尚未正式核准，請勿提供財務單位辦理開票</div>'
    )

    return (
        '<!DOCTYPE html>\n<html lang="zh-Hant">\n<head>\n<meta charset="UTF-8">\n'
        f'<title>{esc(v.get("voucherNo",""))} 開票申請憑據</title>\n'
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
        '  </div>\n  <div>\n    <div class="doc-title">開票申請憑據</div>\n  </div>\n</div>\n'
        '<div class="meta">\n'
        f'  <div><span>憑據單號：</span><strong style="font-family:Arial,sans-serif">{esc(v.get("voucherNo",""))}</strong></div>\n'
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
        f'    <div class="row"><span class="label">申請範圍</span><span class="val">{esc(scope_label)}</span></div>\n'
        '  </div>\n</div>\n'
        f'{items_table_html}'
        '<div class="total-box"><div class="total-table">\n'
        f'  <div class="row"><span>未稅小計</span><span style="font-family:Arial,sans-serif">NT$ {money(pretax_amount)}</span></div>\n'
        f'  <div class="row"><span>營業稅</span><span style="font-family:Arial,sans-serif">NT$ {money(tax_amount)}</span></div>\n'
        f'  <div class="row grand"><span>申請開票總額（含稅）</span><span style="font-family:Arial,sans-serif">NT$ {money(requested_amount)}</span></div>\n'
        '</div></div>\n'
        f'{quote_items_html}'
        f'{_voucher_sign_html(v.get("approval") or {})}\n'
        '<div class="sign">\n'
        '  <div class="sign-box">\n    <div class="sign-label">財務單位 · 開票確認</div>\n'
        '    <div class="sign-line"></div>\n    <div class="sign-date">開票日期：＿＿＿＿＿＿＿＿＿＿</div>\n  </div>\n'
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
