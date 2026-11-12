/* 寄信帳號卡片（選單去工程師化 批次 3，2026-11-13）：從 notification-settings.html 抽出的獨立元件。
 * [單位] static:email-setup   [層] L2   [穩定度] 實驗
 * 用法：頁面放 <div id="email-setup-mount"></div>，並在 Alpine 載入之前（同步）載入本檔；
 *       本檔把卡片的 HTML 放進 mount，Alpine 啟動時再接手（x-data="emailSetupCard()"）。
 * 資料：GET／PUT /api/settings/email-notify、POST /api/settings/email-notify/test。
 * 與 LINE 卡（lineNotifyCard）互不相干——LINE 的人改 notification-settings.html 時不會碰到這個檔。 */
(function () {
  'use strict'

  // 精靈卡（3 步）；下面的 TEMPLATE 是舊的「設定狀態＋手動填寫」兩張卡，保留當作進階設定
  var WIZARD = [
    '<!-- 寄信帳號精靈（3 步）：選信箱服務 → 貼信箱與密碼 → 寄測試信給自己，按「我收到了」才啟用 -->',
    '<div class="ns-card" data-testid="es-wizard-card">',
    '  <div class="ns-card-head">',
    '    <div class="ns-card-head-title">設定公司寄信帳號</div>',
    '    <span x-show="wz.done || (!wz.open && cfg.enabled && cfg.smtp_user)" style="font-size:12px;color:var(--success);font-weight:600" data-testid="es-status-on">● 已啟用</span>',
    '  </div>',
    '  <div class="ns-card-body">',
    '',
    '    <!-- 已設定好：只顯示摘要，要改再展開 -->',
    '    <div x-show="!wz.open" data-testid="es-summary">',
    '      <div style="font-size:13px;margin-bottom:10px">',
    '        目前的寄件信箱：<strong x-text="cfg.smtp_user || \'（尚未設定）\'"></strong>',
    '        <span x-show="cfg.enabled" style="color:var(--success);font-weight:600">（Email 通知已啟用）</span>',
    '        <span x-show="!cfg.enabled" style="color:var(--warning);font-weight:600">（尚未啟用）</span>',
    '      </div>',
    '      <button class="btn btn-ghost" @click="wzOpen()" data-testid="es-reopen">重新設定寄信帳號</button>',
    '    </div>',
    '',
    '    <div x-show="wz.open" data-testid="es-steps">',
    '      <div class="ns-desc" style="margin-bottom:12px">',
    '        只要 3 步：選信箱服務 → 填信箱與密碼 → 系統寄一封測試信給你，你收到就完成。',
    '        <strong x-text="\'第 \' + wz.step + \' 步／共 3 步\'" data-testid="es-step-label"></strong>',
    '      </div>',
    '',
    '      <!-- 第 1 步 -->',
    '      <div x-show="wz.step === 1" data-testid="es-step1">',
    '        <div style="font-size:13px;font-weight:600;margin-bottom:8px">你的公司用哪一種信箱？</div>',
    '        <div style="display:grid;gap:8px">',
    '          <template x-for="p in providers" :key="p.key">',
    '            <label style="display:flex;gap:8px;align-items:flex-start;border:1px solid var(--border,#ddd);border-radius:8px;padding:10px;cursor:pointer"',
    '                   :style="wz.provider === p.key ? \'border-color:var(--primary,#2563EB);background:rgba(37,99,235,.06)\' : \'\'">',
    '              <input type="radio" name="es-provider" :value="p.key" x-model="wz.provider" :data-testid="\'es-provider-\' + p.key" style="margin-top:3px">',
    '              <span>',
    '                <span style="font-weight:600" x-text="p.label"></span>',
    '                <span x-show="p.note" style="display:block;font-size:12px;color:var(--text-dim)" x-text="p.note"></span>',
    '              </span>',
    '            </label>',
    '          </template>',
    '        </div>',
    '        <div class="ns-actions" style="margin-top:12px">',
    '          <button class="btn btn-primary" @click="wzNext1()" :disabled="!wz.provider" data-testid="es-next1">下一步</button>',
    '        </div>',
    '      </div>',
    '',
    '      <!-- 第 2 步 -->',
    '      <div x-show="wz.step === 2" data-testid="es-step2">',
    '        <div style="font-size:13px;font-weight:600;margin-bottom:8px" x-text="\'填寫「\' + (curProv.label || \'\') + \'」的信箱與密碼\'"></div>',
    '        <div class="ns-row">',
    '          <div class="ns-field">',
    '            <label>寄件人信箱（完整的 Email）</label>',
    '            <input type="text" x-model="wz.user" :placeholder="curProv.userHint" autocomplete="off" data-testid="es-user">',
    '          </div>',
    '          <div class="ns-field">',
    '            <label x-text="curProv.passwordLabel"></label>',
    '            <input type="password" x-model="wz.password" autocomplete="new-password" :placeholder="wz.hasSavedPw ? \'已儲存（不改就留空）\' : \'\'" data-testid="es-password">',
    '          </div>',
    '        </div>',
    '        <div class="ns-desc" x-text="curProv.passwordHelp" data-testid="es-password-help"></div>',
    '        <div class="ns-desc" x-show="curProv.helpUrl">',
    '          <a :href="curProv.helpUrl" target="_blank" rel="noopener" x-text="curProv.helpLabel + \'（會開新分頁）\'" data-testid="es-help-link"></a>',
    '        </div>',
    '        <div class="ns-row" x-show="wz.provider === \'other\'" data-testid="es-other-fields">',
    '          <div class="ns-field">',
    '            <label>寄信主機</label>',
    '            <input type="text" x-model="wz.host" placeholder="例：mail.你的公司.com" data-testid="es-host">',
    '          </div>',
    '          <div class="ns-field">',
    '            <label>連接埠</label>',
    '            <input type="number" x-model.number="wz.port" placeholder="587" data-testid="es-port">',
    '          </div>',
    '        </div>',
    '        <div class="ns-desc" x-show="wz.provider === \'other\'">這兩個值（寄信主機、連接埠）請向信箱或網域代管廠商詢問，常見的連接埠是 587 或 465。</div>',
    '        <div class="ns-field" style="margin-top:6px">',
    '          <label>系統網址（信件裡的連結會指向這裡）</label>',
    '          <input type="text" x-model="wz.baseUrl" placeholder="例：https://erp.你的公司.com" data-testid="es-base-url">',
    '          <div class="ns-desc" style="margin-top:4px;color:var(--warning)" x-show="wzBaseWarn()" data-testid="es-base-url-warn">',
    '            <span x-text="wzBaseWarn()"></span> 外部收件人打不開這個連結，請填公司對外網址。',
    '          </div>',
    '        </div>',
    '        <div x-show="wz.needEmail" class="ns-field" data-testid="es-need-email">',
    '          <label>你的帳號還沒有 Email：請填你的 Email（測試信會寄到這裡，也會存回你的帳號）</label>',
    '          <input type="text" x-model="wz.recipient" placeholder="例：you@公司.com" data-testid="es-recipient">',
    '        </div>',
    '        <div x-show="wz.err" style="margin-top:8px;color:var(--danger);font-size:13px;font-weight:600" x-text="wz.err" data-testid="es-err2"></div>',
    '        <div class="ns-actions" style="margin-top:12px">',
    '          <button class="btn btn-ghost" @click="wz.step = 1">上一步</button>',
    '          <button class="btn btn-primary" @click="wzSendTest()" :disabled="wz.sending" data-testid="es-next2">',
    '            <span x-show="!wz.sending">下一步：寄測試信給我</span><span x-show="wz.sending">寄送中…</span>',
    '          </button>',
    '        </div>',
    '      </div>',
    '',
    '      <!-- 第 3 步 -->',
    '      <div x-show="wz.step === 3" data-testid="es-step3">',
    '        <!-- 成功 -->',
    '        <div x-show="wz.sentTo && !wz.done" data-testid="es-sent">',
    '          <div style="font-size:14px;font-weight:600;margin-bottom:6px">測試信已寄到 <span x-text="wz.sentTo" data-testid="es-sent-to"></span></div>',
    '          <div class="ns-desc">請到這個信箱確認有沒有收到（沒收到請也看一下垃圾信件匣）。收到之後按「我收到了」，系統就會開始寄通知信。</div>',
    '          <div class="ns-actions" style="margin-top:12px">',
    '            <button class="btn btn-primary" @click="wzActivate()" :disabled="wz.activating" data-testid="es-got-it">我收到了，啟用通知</button>',
    '            <button class="btn btn-ghost" @click="wzSendTest()" :disabled="wz.sending">沒收到，重寄一次</button>',
    '          </div>',
    '        </div>',
    '        <!-- 失敗 -->',
    '        <div x-show="wz.fail" data-testid="es-fail">',
    '          <div style="font-size:14px;font-weight:700;color:var(--danger);margin-bottom:6px" x-text="wz.fail && wz.fail.title" data-testid="es-fail-title"></div>',
    '          <div class="ns-desc" x-text="wz.fail && wz.fail.hint" data-testid="es-fail-hint"></div>',
    '          <div class="ns-actions" style="margin-top:12px">',
    '            <button class="btn btn-ghost" @click="wz.step = 2; wz.fail = null" data-testid="es-back">回上一步修改</button>',
    '            <button class="btn btn-primary" @click="wzSendTest()" :disabled="wz.sending">再試一次</button>',
    '            <button class="btn btn-ghost" x-show="wz.fail && wz.fail.ticket" @click="wz.showTicket = !wz.showTicket" data-testid="es-ticket-btn">產生設定單</button>',
    '          </div>',
    '          <div x-show="wz.showTicket && wz.fail && wz.fail.ticket" style="margin-top:12px" data-testid="es-ticket">',
    '            <div style="font-size:13px;font-weight:600;margin-bottom:4px" x-text="wz.fail && wz.fail.ticket && wz.fail.ticket.title"></div>',
    '            <pre id="es-ticket-text" style="white-space:pre-wrap;border:1px solid var(--border,#ddd);border-radius:8px;padding:10px;font-size:12px" x-text="wz.fail && wz.fail.ticket && wz.fail.ticket.text" data-testid="es-ticket-text"></pre>',
    '            <div class="ns-actions">',
    '              <button class="btn btn-ghost" @click="wzCopyTicket()" data-testid="es-ticket-copy">複製</button>',
    '              <button class="btn btn-ghost" @click="wzPrintTicket()">列印</button>',
    '              <a class="btn btn-ghost" :href="wzMailto()" data-testid="es-ticket-mail">用郵件寄給資訊廠商</a>',
    '            </div>',
    '            <div class="ns-desc" x-show="wz.copied" style="color:var(--success)">已複製</div>',
    '          </div>',
    '        </div>',
    '        <!-- 完成 -->',
    '        <div x-show="wz.done" data-testid="es-done">',
    '          <div style="font-size:14px;font-weight:700;color:var(--success)">寄信帳號已啟用：之後的簽核、退回、精算完結通知都會自動寄出。</div>',
    '          <div class="ns-actions" style="margin-top:12px"><button class="btn btn-ghost" @click="wz.open = false">關閉</button></div>',
    '        </div>',
    '      </div>',
    '    </div>',
    '',
    '  </div>',
    '</div>',
  ].join('\n')

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
    '    <div class="ns-card-head-title">進階設定（手動填寫）</div>',
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

      // ── 精靈（3 步）──────────────────────────────────────────────────────────
      providers: [],
      wz: {
        open: false, step: 1, provider: 'gmail', user: '', password: '', hasSavedPw: false, host: '', port: 587, baseUrl: '', recipient: '',
        needEmail: false, sending: false, activating: false, sentTo: '', fail: null, err: '', done: false, showTicket: false, copied: false,
      },
      get curProv() { return this.providers.find(p => p.key === this.wz.provider) || {} },
      wzOpen() {
        this.wz = { ...this.wz, open: true, step: 1, fail: null, err: '', sentTo: '', done: false, showTicket: false, needEmail: false }
      },
      wzNext1() { if (this.wz.provider) { this.wz.step = 2; this.wz.err = '' } },
      wzBaseWarn() {
        const keep = this.cfg.base_url
        this.cfg.base_url = this.wz.baseUrl
        const w = this.baseUrlWarn()
        this.cfg.base_url = keep
        return w
      },
      _wzBody() {
        const w = this.wz
        return {
          provider: w.provider, smtp_user: (w.user || '').trim(),
          smtp_password: w.password || (w.hasSavedPw ? '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022' : ''),
          smtp_host: w.provider === 'other' ? (w.host || '').trim() : '', smtp_port: w.provider === 'other' ? (w.port || 587) : (this.curProv.port || 587),
          base_url: (w.baseUrl || '').trim(), recipient: (w.recipient || '').trim(),
        }
      },
      async wzSendTest() {
        const w = this.wz
        w.sending = true; w.err = ''; w.fail = null; w.copied = false
        let r, d = {}
        try {
          r = await fetch('/api/settings/email-notify/wizard/test-me', {
            method: 'POST', headers: { Authorization: 'Bearer ' + token(), 'Content-Type': 'application/json' }, body: JSON.stringify(this._wzBody()),
          })
          d = await r.json().catch(() => ({}))
        } catch (e) { r = { ok: false, status: 0 }; d = { detail: '連不上系統，請確認這台電腦的網路後再試一次。' } }
        w.sending = false
        if (r.ok) {
          // 測試成功只代表「這份候選設定能寄」；到按下「我收到了」才寫進正式設定，所以密碼先留著給「重寄」用，這裡不重讀設定
          w.sentTo = d.sent_to || ''; w.step = 3; w.needEmail = false
          return
        }
        if (d.needEmail) { w.needEmail = true; w.err = d.detail || ''; w.step = 2; return }
        if (r.status === 502 || d.category) { w.fail = { title: d.title || d.detail || '寄信失敗', hint: d.hint || '', ticket: d.ticket || null }; w.sentTo = ''; w.step = 3; return }
        w.err = d.detail || '寄送失敗，請確認設定'; w.step = 2
      },
      async wzActivate() {
        const w = this.wz
        w.activating = true
        let r, d = {}
        try {
          r = await fetch('/api/settings/email-notify/wizard/activate', { method: 'POST', headers: { Authorization: 'Bearer ' + token() } })
          d = await r.json().catch(() => ({}))
        } catch (e) { r = { ok: false } }
        w.activating = false
        if (r.ok) { w.done = true; w.password = ''; w.hasSavedPw = true; await this._reloadCfg(); return }
        w.sentTo = ''; w.fail = { title: d.detail || '啟用失敗，請重新寄一次測試信', hint: '', ticket: null }
      },
      async _reloadCfg() {
        try {
          const r = await fetch('/api/settings/email-notify', { headers: { Authorization: 'Bearer ' + token() } })
          if (r.ok) { const data = await r.json(); this.cfg = { ...this.cfg, ...data }; if (!Array.isArray(this.cfg.admin_email_preview)) this.cfg.admin_email_preview = [] }
        } catch (e) { /* 重新整理頁面即可 */ }
      },
      wzCopyTicket() {
        const txt = (this.wz.fail && this.wz.fail.ticket && this.wz.fail.ticket.text) || ''
        const done = () => { this.wz.copied = true; setTimeout(() => { this.wz.copied = false }, 2000) }
        try { navigator.clipboard.writeText(txt).then(done, () => {}) } catch (e) { /* 瀏覽器不允許時，請用手動選取複製 */ }
      },
      wzPrintTicket() {
        const tk = this.wz.fail && this.wz.fail.ticket
        if (!tk) return
        const win = window.open('', '_blank')
        if (!win) return
        const pre = win.document.createElement('pre')
        pre.style.cssText = 'white-space:pre-wrap;font:14px/1.6 sans-serif'
        pre.textContent = tk.text
        win.document.title = tk.title
        win.document.body.appendChild(pre)
        win.print()
      },
      wzMailto() {
        const tk = this.wz.fail && this.wz.fail.ticket
        return tk ? ('mailto:?subject=' + encodeURIComponent(tk.title) + '&body=' + encodeURIComponent(tk.text)) : '#'
      },

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
        try {
          const pr = await fetch('/api/settings/email-notify/providers', { headers: { Authorization: 'Bearer ' + tk } })
          if (pr.ok) this.providers = (await pr.json()).providers || []
        } catch (e) { /* 清單讀不到：精靈第 1 步會是空的，進階設定仍可手動填寫 */ }
        const w = this.wz
        w.user = this.cfg.smtp_user || ''
        w.hasSavedPw = !!(this.cfg.smtp_password)
        w.baseUrl = this.cfg.base_url || ''
        const hit = this.providers.find(p => p.host && p.host === this.cfg.smtp_host)
        w.provider = hit ? hit.key : (this.cfg.smtp_user && this.cfg.smtp_host ? 'other' : 'gmail')
        if (w.provider === 'other') { w.host = this.cfg.smtp_host || ''; w.port = this.cfg.smtp_port || 587 }
        w.open = !(this.cfg.enabled && this.cfg.smtp_user)            // 還沒設定好 ⇒ 預設展開精靈；設定好了只顯示摘要
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
    host.innerHTML = WIZARD + TEMPLATE
  }
  // 同步載入時 mount 通常已在 DOM（腳本放在 mount 之後）；否則等 DOMContentLoaded（早於 deferred 的 Alpine 啟動）
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount)
  else mount()
})()
