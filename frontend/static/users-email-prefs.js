/* users.html 編輯視窗的「Email 通知偏好」矩陣（T86，2026-11-14；設定改版 S2-PAGE-CONTRACT）。
 *
 * 原則：
 *  1. 資料還是 `form.notificationMuted`（退訂清單：空＝全收）；存檔仍是使用者表單的「儲存」一起送 `notification_muted`（鍵與值不變）。
 *     矩陣的操作**只改這份表單狀態、不直接打伺服器**——所以沒有草稿列：點格子／批次／群組快捷都立刻反映在表單上，表單「儲存」才寫入帳號。
 *  2. 只有「此帳號收得到」的類型能動（receivable）；收不到的列出但反灰（由「信件與通知收件設定」決定）。
 *  3. 與本人入口（my-account.html，S6）同一條規則：只有業務類（lowRisk）能批次；簽核／系統技術類逐項設定，取消勾選要先確認。
 *     最後一位最高管理者不能退訂系統技術類由伺服器在表單儲存時擋（PUT /api/users/{id}），畫面照常顯示伺服器的錯誤。
 *  4. 批次（勾選列的批次列、群組「全收／全不收」）：確認視窗 → 套用 → 「復原這一批」（只在那一批改到的項目還是套用後的狀態才復原）。
 * 用法：usersPage() 回傳物件時 spread `...window.usersEmailPrefsMixin()`；載完 `allNotifyTypes` 後呼叫 emailPrefsMount()；關視窗呼叫 emailPrefsDestroy()。
 * 依賴：static/settings-matrix.js（SettingsMatrix）、css/settings-matrix.css。 */
(function () {
  'use strict'
  var NOT_IN_SCOPE = '此帳號不在收件範圍，由「信件與通知收件設定」決定。'
  var NO_BATCH = '簽核與系統技術類通知須逐項勾選，無法批次調整。'

  window.usersEmailPrefsMixin = function () {
    var mx = null                                   // 不放進 Alpine 的反應式狀態：重繪才不會被自己觸發

    return {
      // 一行總覽：共幾項、收幾項、不收幾項、不在收件範圍幾項（讀 allNotifyTypes＋form.notificationMuted，Alpine 會跟著更新）
      emailPrefsStatText: function () {         // 不用 getter：spread（`...mixin`）會把 getter 當場求值、之後不再更新
        var all = this.allNotifyTypes || [], muted = this.form.notificationMuted || []
        var out = all.filter(function (t) { return !t.receivable }).length
        var on = all.filter(function (t) { return t.receivable && muted.indexOf(t.key) < 0 }).length
        var off = all.length - out - on
        return all.length ? ('共 ' + all.length + ' 項：收 ' + on + '、不收 ' + off + (out ? '、不在收件範圍 ' + out : '')) : ''
      },

      _emailRows: function () {
        var muted = this.form.notificationMuted || []
        return (this.allNotifyTypes || []).map(function (t) {
          var low = t.lowRisk === true || t.category === 'business'                    // 兩個欄位都沒有（舊伺服器）⇒ 當非業務類，不開放批次
          return {
            key: t.key, name: t.label, group: t.group, category: t.category || '', lowRisk: !!low, receivable: !!t.receivable,
            receive: !!t.receivable && muted.indexOf(t.key) < 0,
            selectable: !!t.receivable && !!low,
            selectableReason: !t.receivable ? NOT_IN_SCOPE : (low ? '' : NO_BATCH),
          }
        })
      },

      // 把 keys 設成「收」或「不收」；只動收得到的項目；回 {key: 套用後的 receive}（只含真的有變的）
      _emailApply: function (keys, receive) {
        var muted = this.form.notificationMuted, by = {}, changed = {}
        ;(this.allNotifyTypes || []).forEach(function (t) { by[t.key] = t })
        keys.forEach(function (k) {
          var t = by[k]
          if (!t || !t.receivable) return
          var i = muted.indexOf(k)
          if (receive && i >= 0) { muted.splice(i, 1); changed[k] = true }
          else if (!receive && i < 0) { muted.push(k); changed[k] = false }
        })
        return changed
      },

      emailPrefsMount: function () {
        var box = document.getElementById('up-email-box')
        if (!box || !window.SettingsMatrix) return
        this.emailPrefsDestroy()
        var self = this, esc = window.SettingsMatrix.esc
        var rows = this._emailRows()
        if (!rows.length) { box.innerHTML = ''; return }
        var cats = []
        rows.forEach(function (r) { if (cats.indexOf(r.group) < 0) cats.push(r.group) })
        function riskDialog(r) {
          return [{
            title: '不寄這類通知？', danger: true, okLabel: '仍要不收',
            html: '<div class="mx-danger-box">取消後，此帳號<b>不會再收到「' + esc(r.name) + '」的 Email</b>，相關提醒或告警可能因此漏掉。</div>' +
              '<div class="mx-mute">這是簽核或系統技術類通知；請確認有其他人或其他管道（系統內通知、LINE）會處理。</div>',
          }]
        }
        function done(changed, verb) {
          var n = Object.keys(changed).length
          return { applied: changed, message: n ? ('已' + verb + ' ' + n + ' 項（按下方「儲存變更」後才會寫入此帳號）。') : '這些項目已是此狀態，無須變動。' }
        }
        mx = window.SettingsMatrix.mount(box, {
          rows: rows, groups: cats,
          rowKey: function (r) { return r.key }, rowName: function (r) { return r.name }, rowGroup: function (r) { return r.group },
          rowSub: function (r) { return r.receivable ? '' : NOT_IN_SCOPE },
          rowTags: function (r) { return r.lowRisk ? [] : [{ text: r.category === 'system' ? '系統技術' : '簽核', tone: 'warn' }] },
          nameLabel: 'Email 通知', searchPlaceholder: '搜尋通知名稱',
          searchText: function (r) { return r.name + ' ' + r.group },
          groupSummary: function (g, all) {
            var rc = all.filter(function (e) { return e.receivable })
            return '收 ' + rc.filter(function (e) { return e.receive }).length + '／共 ' + rc.length + (rc.length < all.length ? '（另 ' + (all.length - rc.length) + ' 項不在收件範圍）' : '')
          },
          columns: [{
            id: 'recv', type: 'switch', label: '要收', width: 64,
            get: function (r) { return r.receive },
            disabled: function (r) { return r.receivable ? false : NOT_IN_SCOPE },
            confirm: function (r, v) { return (!v && !r.lowRisk) ? riskDialog(r) : [] },
            set: function (r, v) { self._emailApply([r.key], v) },
          }],
          filters: [
            { id: 'on', label: '有收', test: function (r) { return r.receive } },
            { id: 'off', label: '不收', test: function (r) { return r.receivable && !r.receive } },
            { id: 'out', label: '不在收件範圍', test: function (r) { return !r.receivable } },
          ],
          batch: {
            groupActions: [{ action: 'on', label: '全收' }, { action: 'off', label: '全不收' }],
            groupActionsEnabled: true,
            actions: [
              { id: 'on', label: '都收', run: function (keys) { return done(self._emailApply(keys, true), '設為收') } },
              { id: 'off', label: '都不收', run: function (keys) { return done(self._emailApply(keys, false), '設為不收') } },
            ],
            snapshot: function (keys) {
              var s = {}, muted = self.form.notificationMuted || []
              keys.forEach(function (k) { s[k] = muted.indexOf(k) < 0 ? 1 : 0 })
              return s
            },
            restore: function (snap, res) {
              var applied = (res && res.applied) || {}, muted = self.form.notificationMuted || []
              var moved = Object.keys(applied).filter(function (k) { return (muted.indexOf(k) < 0) !== applied[k] })
              if (moved.length) return Promise.reject(new Error('有 ' + moved.length + ' 項在這一批之後又被改過，不能整批復原，請逐項調整。'))   // 不可同步 throw：元件在 click 裡直接呼叫 restore，同步例外會讓元件卡在忙碌、也沒有提示
              Object.keys(applied).forEach(function (k) { self._emailApply([k], !applied[k]) })
            },
          },
          reload: function () { return Promise.resolve(self._emailRows()) },
        })
      },

      emailPrefsDestroy: function () {
        if (mx) { try { mx.destroy() } catch (e) { /* 容器已被移除 */ } mx = null }
      },
    }
  }
})()
