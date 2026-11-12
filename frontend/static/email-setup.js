/* 寄信帳號卡片（選單去工程師化 批次 3，2026-11-13）：從 notification-settings.html 抽出的獨立元件。
 * [單位] static:email-setup   [層] L2   [穩定度] 實驗
 * 用法：頁面放 <div id="email-setup-mount"></div>，並在 Alpine 載入之前（同步）載入本檔；
 *       本檔把卡片的 HTML 放進 mount，Alpine 啟動時再接手（x-data="emailSetupCard()"）。
 * 資料：GET／PUT /api/settings/email-notify、POST /api/settings/email-notify/test。
 * 與 LINE 卡（lineNotifyCard）互不相干——LINE 的人改 notification-settings.html 時不會碰到這個檔。 */
(function () {
  'use strict'

  var TEMPLATE = [
    '<!-- 設定狀態 checklist -->',
    '<div class="ns-card">',
    '  <div class="ns-card-head">',
    '    <div class="ns-card-head-title">設定狀態</div>',
    '    <span x-show="allReady" style="font-size:12px;color:var(--success);font-weight:600">● 已就緒</span>',
    '    <span x-show="!allReady" style="font-size:12px;color:var(--warning);font-weight:600"',
    '          x-text="\'尚有 \' + (checks.length - readyCount) + \' 項待完成\'"></span>',
    '  </div>',
    '  <div class="ns-card-body" style="padding-top:8px;padding-bottom:8px">',
    '    <template x-for="c in checks" :key="c.label">',
    '      <div class="ns-check-row">',
    '        <div :style="c.ok ? \'color:#15803D\' : \'color:var(--text-dim)\'" style="flex-shrink:0;margin-top:1px">',
    '          <template x-if="c.ok">',
    '            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
    '          </template>',
    '          <template x-if="!c.ok">',
    '            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
    '          </template>',
    '        </div>',
    '        <div style="flex:1">',
    '          <div style="font-size:13px;font-weight:500"',
    '               :style="c.ok ? \'color:var(--text-main)\' : \'color:var(--text-secondary)\'"',
    '               x-text="c.label"></div>',
    '          <div x-show="!c.ok" x-text="c.hint"',
    '               style="font-size:12px;color:var(--warning);margin-top:2px"></div>',
    '        </div>',
    '        <span class="ns-check-badge"',
    '              :style="c.ok ? \'background:#D1FAE5;color:#065F46\' : \'background:#FEF3C7;color:#92400E\'"',
    '              x-text="c.ok ? \'完成\' : \'待設定\'"></span>',
    '      </div>',
    '    </template>',
    '  </div>',
    '</div>',
    '',
    '<!-- SMTP 設定 -->',
    '<div class="ns-card">',
    '  <div class="ns-card-head">',
    '    <div class="ns-card-head-title">Gmail SMTP 設定</div>',
    '    <span x-show="saved" x-transition style="font-size:12px;color:var(--success);font-weight:600">已儲存</span>',
    '  </div>',
    '  <div class="ns-card-body">',
    '',
    '    <!-- 啟用開關 -->',
    '    <div class="ns-toggle">',
    '      <input type="checkbox" id="chk-enabled" x-model="cfg.enabled" style="width:16px;height:16px;cursor:pointer">',
    '      <label for="chk-enabled">啟用 Email 通知</label>',
    '      <span x-show="!cfg.enabled" style="font-size:12px;color:var(--text-dim)">(目前關閉)</span>',
    '      <span x-show="cfg.enabled" style="font-size:12px;color:var(--success);font-weight:600">(已啟用)</span>',
    '    </div>',
    '',
    '    <!-- 開發機測試模式（2026-08-26 新增）：這個設定值存在本機 DB，不隨部署流程移動到正式機，只需要在開發機自己開啟即可 -->',
    '    <details data-testid="ns-dev-section" style="margin-bottom:12px">',
    '      <summary style="cursor:pointer;font-size:12px;color:var(--text-dim)">開發用設定（一般使用不需要）</summary>',
    '      <div class="ns-toggle" style="margin-top:8px" data-testid="ns-dev-mode-row">',
    '        <input data-saved-field type="checkbox" id="chk-dev-mode" x-model="cfg.dev_mode" style="width:16px;height:16px;cursor:pointer">',
    '        <label for="chk-dev-mode">開發機測試模式（寄出信件標題加註「【開發機測試】」）</label>',
    '        <span x-show="cfg.dev_mode" style="font-size:12px;color:var(--warning);font-weight:600">(測試模式已開啟)</span>',
    '      </div>',
    '    </details>',
    '',
    '    <div class="ns-desc">',
    '      請使用 Gmail <strong>應用程式密碼</strong>（App Password），而非 Google 帳號的登入密碼。<br>',
    '      取得方式：Google 帳戶 → 安全性 → 兩步驟驗證 → 應用程式密碼',
    '    </div>',
    '',
    '    <div class="ns-row">',
    '      <div class="ns-field">',
    '        <label>寄件人 Email（Gmail 帳號）</label>',
    '        <input type="text" x-model="cfg.smtp_user" placeholder="your@gmail.com">',
    '      </div>',
    '      <div class="ns-field">',
    '        <label>應用程式密碼（App Password）</label>',
    '        <input type="password" x-model="cfg.smtp_password" placeholder="16 碼應用程式密碼">',
    '      </div>',
    '    </div>',
    '',
    '    <div class="ns-row">',
    '      <div class="ns-field">',
    '        <label>SMTP 主機</label>',
    '        <input type="text" x-model="cfg.smtp_host" placeholder="smtp.gmail.com">',
    '      </div>',
    '      <div class="ns-field">',
    '        <label>SMTP 連接埠</label>',
    '        <input type="number" x-model.number="cfg.smtp_port" placeholder="587">',
    '      </div>',
    '    </div>',
    '',
    '    <div class="ns-row">',
    '      <div class="ns-field">',
    '        <label>寄件人顯示名稱</label>',
    '        <input type="text" x-model="cfg.from_name" placeholder="MOTRIX ERP">',
    '      </div>',
    '      <div class="ns-field">',
    '        <label>系統網址（信件中的連結前綴）</label>',
    '        <input type="text" x-model="cfg.base_url" placeholder="例：https://erp.你的公司.com" data-testid="ns-base-url">',
    '        <div class="ns-desc" style="margin-top:4px;color:var(--warning)" x-show="baseUrlWarn()" x-text="baseUrlWarn()" data-testid="ns-base-url-warn"></div>',
    '      </div>',
    '    </div>',
    '',
    '    <!-- 管理員收件人（自動從使用者管理讀取） -->',
    '    <div class="ns-field" style="margin-bottom:16px">',
    '      <label>管理員通知對象（全員通過、精算完結）</label>',
    '      <div class="ns-email-tags-wrap">',
    '        <template x-if="cfg.admin_email_preview && cfg.admin_email_preview.length">',
    '          <template x-for="email in cfg.admin_email_preview" :key="email">',
    '            <span class="ns-email-tag" style="background:#EAF7EF;color:#15803D">',
    '              <span x-text="email"></span>',
    '            </span>',
    '          </template>',
    '        </template>',
    '        <template x-if="!cfg.admin_email_preview || !cfg.admin_email_preview.length">',
    '          <span style="font-size:12px;color:var(--text-dim);padding:4px 2px">',
    '            尚未設定（請至「使用者管理」為 admin / superadmin 帳號填寫 Email）',
    '          </span>',
    '        </template>',
    '      </div>',
    '      <div style="font-size:12px;color:var(--text-dim);margin-top:6px">',
    '        自動讀取角色為 <strong>管理員</strong> 或 <strong>最高管理者</strong> 且已填寫 Email 的使用者，無需手動維護',
    '      </div>',
    '    </div>',
    '',
    '    <div class="ns-actions">',
    '      <button class="btn btn-primary" @click="save()" :disabled="saving">',
    '        <span x-show="!saving">儲存設定</span>',
    '        <span x-show="saving">儲存中…</span>',
    '      </button>',
    '      <button class="btn btn-ghost" @click="testEmail()" :disabled="testing || !cfg.enabled">',
    '        <span x-show="!testing">寄送測試信</span>',
    '        <span x-show="testing">寄送中…</span>',
    '      </button>',
    '    </div>',
    '',
    '    <div x-show="msg" x-text="msg" x-transition',
    '         :style="isError ? \'color:var(--danger)\' : \'color:var(--success)\'"',
    '         style="font-size:13px;margin-top:12px;font-weight:600"></div>',
    '  </div>',
    '</div>',
  ].join('\n')

  function token() {
    try { return (JSON.parse(localStorage.getItem('motrix_session') || '{}') || {}).token || '' } catch (e) { return '' }
  }

  window.emailSetupCard = function emailSetupCard() {
    return {
      cfg: {
        enabled: false,
        smtp_host: 'smtp.gmail.com',
        smtp_port: 587,
        smtp_user: '',
        smtp_password: '',
        from_name: 'MOTRIX ERP',
        base_url: '',
        dev_mode: false,
        admin_email_preview: [],
      },
      saving: false,
      testing: false,
      saved: false,
      msg: '',
      isError: false,

      // 系統網址的白話提醒：沒填、是這台電腦自己（localhost）、或是公司內部才連得到的位址（私有 IP、.local／.lan 之類的內部名稱、單一名稱的主機）
      baseUrlWarn() {
        const u = String(this.cfg.base_url || '').trim()
        if (!u) return '還沒有填系統網址：信件裡的按鈕會沒有連結，收信的人只能自己打開系統。'
        let h = ''
        try { h = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(u) ? u : 'https://' + u).hostname.toLowerCase().replace(/^\[|\]$/g, '') } catch (e) { return '這個網址看起來不完整，請填完整網址（例：https://erp.你的公司.com）。' }
        const m4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(h)
        if (m4) {
          const o = m4.slice(1).map(Number)
          if (o.some(n => n > 255)) return '這個網址看起來不完整，請填完整網址（例：https://erp.你的公司.com）。'
          if (o[0] === 127) return '這是這台電腦自己的位址：只有在這台電腦上點信裡的連結才打得開。若同事要從別台電腦或手機點，請改成他們連得到的網址。'
          if (o[0] === 10 || (o[0] === 172 && o[1] >= 16 && o[1] <= 31) || (o[0] === 192 && o[1] === 168) || (o[0] === 169 && o[1] === 254) || (o[0] === 100 && o[1] >= 64 && o[1] <= 127))
            return '這是公司內部網路的位址：人在公司外（或沒連公司網路）時，點信裡的連結會打不開。'
          return ''
        }
        if (h === '::1' || h === 'localhost' || h.endsWith('.localhost')) return '這是這台電腦自己的位址：只有在這台電腦上點信裡的連結才打得開。若同事要從別台電腦或手機點，請改成他們連得到的網址。'
        if (/^(fc|fd|fe80)/.test(h) && h.includes(':')) return '這是公司內部網路的位址：人在公司外（或沒連公司網路）時，點信裡的連結會打不開。'
        if (!h.includes('.') || /\.(local|lan|internal|intranet|home|localdomain|home\.arpa)$/.test(h)) return '這看起來是公司內部才認得的名稱：人在公司外（或沒連公司網路）時，點信裡的連結會打不開。'
        return ''
      },

      get checks() {
        return [
          {
            label: 'Email 通知已啟用',
            ok: !!this.cfg.enabled,
            hint: '請開啟「啟用 Email 通知」開關後儲存',
          },
          {
            label: 'Gmail 寄件帳號',
            ok: !!(this.cfg.smtp_user && this.cfg.smtp_user.trim()),
            hint: '請填寫 Gmail 帳號（例：your@gmail.com）',
          },
          {
            label: '應用程式密碼（App Password）',
            ok: !!(this.cfg.smtp_password && this.cfg.smtp_password.trim()),
            hint: '請填寫 16 碼 App Password（Google 帳戶 → 安全性 → 兩步驟驗證）',
          },
          {
            label: '管理員收件人 Email',
            ok: !!(this.cfg.admin_email_preview && this.cfg.admin_email_preview.length > 0),
            hint: '請至「使用者管理」為管理員或最高管理者帳號填寫 Email 欄位',
          },
        ]
      },
      get readyCount() { return this.checks.filter(c => c.ok).length },
      get allReady() { return this.readyCount === this.checks.length },

      // 🔴 Alpine 3 看到資料物件有 init() 就會**自己叫一次**；不要再另外寫 x-init，否則跑兩遍，
      //    第二次的回應晚一步抵達，會把使用者這段期間改過的欄位用伺服器上的舊值無聲蓋回去。
      _initDone: false,

      async init() {
        if (this._initDone) return
        this._initDone = true
        const tk = token()
        if (!tk) return                      // 沒登入：頁面的 auth-guard 會處理導向
        const r = await fetch('/api/settings/email-notify', { headers: { Authorization: 'Bearer ' + tk } })
        if (r.ok) {
          const data = await r.json()
          this.cfg = { ...this.cfg, ...data }
          if (!Array.isArray(this.cfg.admin_email_preview)) this.cfg.admin_email_preview = []
          // 2026-11-13：伺服器沒存系統網址時，預填你現在開的這個網址（不寫死任何一台機器；按「儲存」才生效）
          // （用 localhost／127.x 開頁時不預填：那只有這台電腦連得到，預填反而誤導）
          if (!this.cfg.base_url && !/^(localhost|127\.|\[?::1)/i.test(location.hostname)) this.cfg.base_url = location.origin
        }
      },

      async save() {
        this.saving = true; this.msg = ''
        const { admin_email_preview: _preview, ...payload } = this.cfg
        const r = await fetch('/api/settings/email-notify', {
          method: 'PUT',
          headers: { Authorization: 'Bearer ' + token(), 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        this.saving = false
        if (r.ok) {
          this.msg = '設定已儲存'; this.isError = false
          this.saved = true; setTimeout(() => this.saved = false, 3000)
        } else {
          const d = await r.json().catch(() => ({}))
          this.msg = d.detail || '儲存失敗'; this.isError = true
        }
        setTimeout(() => this.msg = '', 4000)
      },

      async testEmail() {
        this.testing = true; this.msg = ''
        const r = await fetch('/api/settings/email-notify/test', {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + token() },
        })
        this.testing = false
        const d = await r.json().catch(() => ({}))
        if (r.ok) {
          this.msg = '測試信已寄出，請至管理員信箱確認'; this.isError = false
        } else {
          this.msg = d.detail || '寄送失敗，請確認 SMTP 設定'; this.isError = true
        }
        setTimeout(() => this.msg = '', 6000)
      },
    }
  }

  function mount() {
    var host = document.getElementById('email-setup-mount')
    if (!host || host.getAttribute('data-mounted')) return
    host.setAttribute('data-mounted', '1')
    host.setAttribute('x-data', 'emailSetupCard()')
    host.innerHTML = TEMPLATE
  }
  // 同步載入時 mount 通常已在 DOM（腳本放在 mount 之後）；否則等 DOMContentLoaded（早於 deferred 的 Alpine 啟動）
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount)
  else mount()
})()
