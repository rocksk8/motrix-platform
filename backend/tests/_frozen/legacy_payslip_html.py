# -*- coding: utf-8 -*-
"""凍結的正對照：P2 改版前的 `pdf_gen._build_payslip_html`（逐字抽取自 platform，2026-09-26）。

🔴 不可以修改這支檔：它是勞報單版型化之後輸出的比對基準。
   抬頭沒有快照時的現行值仍呼叫 pdf_gen 現行的 `location_identity`（那不在 P2 範圍）。
"""
from pdf_gen import location_identity  # noqa: F401


def legacy_build_payslip_html(d: dict) -> str:
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
