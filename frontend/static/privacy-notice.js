// R3 個資蒐集告知（個資法 §8 I；CUSTOMIZATION-SPEC §9.3）：列印告知書的共用元件（L1）。
// 告知文字由 GET /api/legal-params/privacy-notice 提供（公司設定頁的文字；空白＝範本）。
(function () {
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    })
  }

  async function load(token) {
    const r = await fetch('/api/legal-params/privacy-notice', { headers: { Authorization: 'Bearer ' + token } })
    if (!r.ok) throw new Error('讀不到個資告知文字（' + r.status + '）')
    return r.json()
  }

  // 告知書 HTML：公司名稱＋告知文字＋當事人姓名＋簽名欄
  function documentHtml(notice, subjectName) {
    const today = new Date().toISOString().slice(0, 10)
    return '<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="UTF-8"><title>個人資料蒐集告知書</title>' +
      '<style>body{font-family:"Microsoft JhengHei",sans-serif;margin:32px;color:#111;line-height:1.8;font-size:14px}' +
      'h1{font-size:18px;text-align:center;margin-bottom:4px}.co{text-align:center;color:#444;margin-bottom:18px}' +
      '.txt{white-space:pre-wrap}.sign{margin-top:36px;display:grid;grid-template-columns:1fr 1fr;gap:24px}' +
      '.sign div{border-bottom:1px solid #333;padding-bottom:4px}</style></head><body>' +
      '<h1>個人資料蒐集告知書</h1><div class="co" data-company>' + esc(notice.company || '') + '</div>' +
      '<div class="txt" data-notice-text>' + esc(notice.text || '') + '</div>' +
      '<div class="sign"><div>當事人：<span data-subject>' + esc(subjectName || '') + '</span></div>' +
      '<div>簽名：</div><div>日期：' + today + '</div><div>告知人：</div></div>' +
      '<div style="margin-top:18px;font-size:11px;color:#777">告知文字版本 ' + esc(notice.hash || '') + '</div>' +
      '</body></html>'
  }

  // 開新視窗並列印（呼叫端要在使用者點擊的當下呼叫，否則會被擋彈出視窗）
  function print(notice, subjectName) {
    const w = window.open('', '_blank')
    if (!w) { alert('瀏覽器擋住了彈出視窗，請允許本站開啟新視窗後再列印'); return null }
    w.document.open()
    w.document.write(documentHtml(notice, subjectName))
    w.document.close()
    w.focus()
    try { w.print() } catch (e) {}
    return w
  }

  window.MotrixPrivacyNotice = { load: load, documentHtml: documentHtml, print: print }
})()
