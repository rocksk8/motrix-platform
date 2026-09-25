// R3 個資蒐集告知（個資法 §8 I；CUSTOMIZATION-SPEC §9.3）：列印告知書的共用元件（L1）。
// 告知文字由 GET /api/legal-params/privacy-notice 提供（公司設定頁的文字；空白＝範本）。
(function () {
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    })
  }

  // purpose：'contractor'（預設，承攬人員／勞報單）、'contact'（客戶／供應商／承攬商聯絡人）、'user'（使用者帳號）
  async function load(token, purpose) {
    const q = purpose ? ('?purpose=' + encodeURIComponent(purpose)) : ''
    const r = await fetch('/api/legal-params/privacy-notice' + q, { headers: { Authorization: 'Bearer ' + token } })
    if (!r.ok) throw new Error('讀不到個資告知文字（' + r.status + '）')
    return r.json()
  }

  // 告知書 HTML：公司名稱＋告知文字＋當事人姓名＋簽名欄
  function documentHtml(notice, subjectName) {
    // 稽核 S-2：當事人簽名的日期用台北時間（toISOString() 是 UTC，台灣 00:00～07:59 會印成前一天）
    const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
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

  // 多位聯絡人的告知狀態（客戶／供應商表單；2026-09-26）。用法：`...MotrixPrivacyNotice.contactsState()`。
  //   privacyAcks：已記錄的 {聯絡人id: 紀錄}（伺服器來的）；privacyAckReq：這次勾了「已告知」的 {聯絡人id: true}。
  //   紀錄不放進表單資料（form）：表單整包會存進 data_json，紀錄只能由伺服器寫。
  function contactsState() {
    return {
      privacyNotice: null,
      privacyAcks: {},
      privacyAckReq: {},
      async pnLoadNotice() {
        try { this.privacyNotice = await load(this.session.token, 'contact') } catch (e) { this.privacyNotice = null }
      },
      pnReset() { this.privacyAcks = {}; this.privacyAckReq = {} },
      async pnLoadAcks(url) {
        this.pnReset()
        try {
          const r = await fetch(url, { headers: { Authorization: 'Bearer ' + this.session.token } })
          if (r.ok) this.privacyAcks = (await r.json()).acks || {}
        } catch (e) {}
      },
      pnAck(ct) { return this.privacyAcks[String(ct.id)] || null },
      pnReq(ct) { return !!this.privacyAckReq[String(ct.id)] },
      pnSetReq(ct, on) { this.privacyAckReq = Object.assign({}, this.privacyAckReq, { [String(ct.id)]: !!on }) },
      pnPrint(ct) { if (this.privacyNotice) print(this.privacyNotice, (ct && ct.name) || '') },
      // 存檔成功後呼叫：把勾了「已告知」的聯絡人逐一記錄；失敗丟例外（呼叫端不關視窗，讓使用者重試）
      async pnRecordRequested(baseUrl, contacts) {
        for (const ct of (contacts || [])) {
          const k = String(ct.id)
          if (!this.privacyAckReq[k] || this.privacyAcks[k]) continue
          const r = await fetch(baseUrl + '/contacts/' + encodeURIComponent(k) + '/privacy-notice/ack', {
            method: 'POST', headers: { Authorization: 'Bearer ' + this.session.token } })
          if (!r.ok) throw new Error('聯絡人「' + (ct.name || k) + '」的個資告知紀錄寫入失敗（' + r.status + '）')
          this.privacyAcks = Object.assign({}, this.privacyAcks, { [k]: (await r.json()).ack })
          this.pnSetReq(ct, false)
        }
      },
    }
  }

  window.MotrixPrivacyNotice = { load: load, documentHtml: documentHtml, print: print, contactsState: contactsState }
})()
