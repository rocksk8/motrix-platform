/* approval-settings.html 的「複製簽核流程」（設定矩陣 S4c；後端 POST /api/approval/flows/copy[/preview]，邏輯在 helpers/approval_flow_copy.py）。
 *
 * 原則：
 *  1. 這個面板**不算任何東西**：每個目標會不會變、為什麼略過、目前有幾件單據在簽核中、其中幾件會改用新流程，全由伺服器的預覽回答；前端只負責顯示與送出。
 *  2. 先預覽、再確認、才寫入：選目標只是選；按「預覽」才送請求，預覽什麼都不寫；確認視窗**先講進行中單據件數**，再給「套用」。
 *  3. 預覽之後流程有人改過 ⇒ 伺服器回 409，提示重新預覽，不照過期預覽寫入。
 *  4. 所有動態文字用 x-text（類型名稱來自頁面登記表）。
 * 用法：approvalSettingsApp() 回傳物件時 spread `...window.approvalFlowCopyMixin()`；頁面要有 `session.token`、`docTypeOrder`、`docTypeMeta`、`_toast()`、`loadAllFlows()`。
 * §13 豁免條件（與批次權限同）：任何一次點擊都不寫入，只有確認視窗的「套用」才寫；確認視窗逐一點名目標與進行中件數；預覽之前沒有任何東西被改。 */
(function () {
  window.approvalFlowCopyMixin = function () {
    return {
      afc: { open: false, source: '', sel: {}, plan: null, busy: false, error: '' },

      afcLabel(key) { return key === 'unified' ? '統一簽核流程' : (this.docTypeMeta[key] || key) },
      afcTargets() { return (this.docTypeOrder || []).filter(k => k !== this.afc.source) },
      afcOpen(source) { this.afc = { open: true, source, sel: {}, plan: null, busy: false, error: '' } },
      afcClose() { this.afc.open = false },
      afcSelected() { return this.afcTargets().filter(k => this.afc.sel[k]) },
      afcCanPreview() { return !this.afc.busy && this.afcSelected().length > 0 },
      afcBack() { this.afc.plan = null; this.afc.error = '' },
      _afcHeaders() { return { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token } },
      async _afcPost(path, body) {
        const r = await fetch('/api/approval/flows/copy' + path, { method: 'POST', headers: this._afcHeaders(), body: JSON.stringify(body) })
        const d = await r.json().catch(() => ({}))
        if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : '操作失敗（' + r.status + '）')
        return d
      },
      afcBody() { return { source: this.afc.source, targets: this.afcSelected() } },
      async afcPreview() {
        const a = this.afc
        if (!this.afcCanPreview()) return
        a.busy = true; a.error = ''
        try { a.plan = await this._afcPost('/preview', this.afcBody()) } catch (e) { a.error = e.message } finally { a.busy = false }
      },
      // 確認視窗第一句：先講進行中單據（件數全由伺服器算；沒有就明說沒有）
      afcInflightText() {
        const p = this.afc.plan
        if (!p) return ''
        const s = p.summary
        if (!s.changed) return ''
        let t
        if (!s.inflightTotal) t = '目前沒有進行中的單據，複製後只影響之後送出的單據。'
        else t = '目前有 ' + s.inflightTotal + ' 件單據正在簽核中：其中 ' + s.inflightUsingFlow + ' 件沒有自己的簽核層，複製後會改用新流程；其餘 ' +
          (s.inflightTotal - s.inflightUsingFlow) + ' 件照送審當時的流程簽完，不受影響。'
        if (!p.inflightComplete) t += '（有些模組沒有回應，件數可能不完整。）'
        return t
      },
      afcLineText(t) {
        if (t.status === 'skipped') return '略過：' + t.note
        if (t.status === 'nochange') return '不變：' + t.note
        return '目前：' + t.before + ' → 複製後：' + t.after + '；進行中 ' + t.inflight.total + ' 件（' + t.inflight.usingFlow + ' 件改用新流程）'
      },
      afcSummaryText() {
        const s = (this.afc.plan || {}).summary
        if (!s) return ''
        return '將複製到 ' + s.changed + ' 類、不變 ' + s.unchanged + ' 類、略過 ' + s.skipped + ' 類'
      },
      async afcApply() {
        const a = this.afc
        if (!a.plan || a.busy || !a.plan.summary.changed) return
        a.busy = true; a.error = ''
        try {
          const d = await this._afcPost('', Object.assign(this.afcBody(), { planHash: a.plan.planHash }))
          a.open = false
          this._toast('已複製「' + this.afcLabel(a.source) + '」到 ' + d.applied.length + ' 類單據')
          await this.loadAllFlows()
        } catch (e) { a.error = e.message } finally { a.busy = false }
      },
    }
  }
})()
