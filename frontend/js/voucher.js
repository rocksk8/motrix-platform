// 傳票版面（`VC4a` 骨架 → `JV1`／`JV2` 接線）。
//
// 版面照使用者提供的實例 `docs/reference/傳票-實例-20260330-006.pdf`
// （逐欄分析在 `STATE.md §103b`）—— **不是照我想像的傳票長相**。
//
// 🔴 **這一輪把九支端點接上頁面**（`§181` 的關鍵路徑）。
//    在這之前：後端九支端點全在且有題，而這一頁只打 `company-profile`／
//    `account-items`，唯一的 `@click` 是 `addLine()`（本地，不送出）
//    ⇒ **使用者打開傳票頁存不了任何東西**。
//    🔑 而那種狀態最難察覺：畫面完整、欄位能打、合計會動 —— 它看起來是做完的。
//
// ⚠️ **不用 `confirm()`／`prompt()`**：瀏覽器的原生對話框會擋住整個頁面事件，
//    而作廢與退回都需要一段**理由**（後端沒有理由直接回 400）⇒ 用行內輸入框。

function voucherPage() {
  return {
    // ── 單據 ──
    id: 0,                // 0 ＝ 尚未儲存的新單
    company: '',
    voucherNo: '',        // 🔴 由後端產生，前端不發號
    voucherDate: '',
    category: '轉',
    //: `N6`：類別是否手動指定過（手動過的，改分錄不再自動覆蓋）。
    categoryManual: false,
    status: '草稿',
    note: '',
    lines: [],
    // `JV31`：[{label, by}]，順序照後端 `signatures`（製票 → 各層 → 記帳）。
    signs: [],
    voidedAt: '',
    //: `JV8`：**有明確意圖才顯示編輯畫面** —— 按「新增傳票」或從清單點開一張。
    //: ☠️ 一進來就是空白表單的話，使用者以為自己在建一張單，打了一半離開，
    //:    **而什麼都沒有被建出來**。
    editing: false,

    // ── 清單 ──
    list: [],
    listLoaded: false,
    includeVoided: false,

    // ── 摘要來源（`JV7`）──
    //
    // 🔴 **帶入是起點不是終點。**
    //    `§164`：那張實例 PDF 的三行摘要沒有一行是同一個格式，而三行裡兩行都有的
    //    「事由」**沒有來源可以帶** ⇒ 一定要手打。
    //    ⇒ 帶入只是**省打字**，帶完之後那一格仍然要打得動。
    // ☠️ 最容易寫錯的實作是「**切頁籤時重新帶入**」—— 它看起來像功能正常
    //    （點哪個頁籤就帶哪個，很合理），而使用者打完字去看一眼附件清單、
    //    切回來，**他打的字沒了**。
    // ⇒ 寫進 `l.summary` 的只有 `panelPick()`，而它只在**點一筆來源**時跑；瀏覽來源
    //   （換一行、看檔案、開預覽）一個字都不寫回分錄。
    //   📌 2026-09-25：頁籤區（`pickTab`／`applySource`）隨使用者裁定移除，收進分錄下方的帶入來源區塊。
    sources: {},
    sourceNotes: {},
    sourceUnavailable: [],   // 稽核 X-1：整類來源缺席（模組未安裝）
    sourcesLoaded: false,
    //: 摘要來源**正在載入**（每一次，含選了案件之後那一次）。`sourcesLoaded` 只代表「載過一次」。
    sourcesLoading: false,
    sourceErr: '',
    //: 頁籤②「已上傳檔案」要先知道**是哪一個案件** —— 憑證掛在案件底下。
    sourceQuote: '',
    //: `JV18`：展開中的「已計算」明細是哪一個檔（`srcFileKey()`），`-1` = 都沒展開。
    //: ⚠️ 同時只能展開一筆，展開下一筆要先把上一筆收起來，不然清單會越展越長。
    usedInfoOpen: -1,

    // ── 附件（`JV3`）──
    //
    // 🔴 帶入 ＝ **後端複製一份檔案**，不是引用。
    //    引用的話，別人刪掉來源附件 ⇒ **一張已過帳傳票的憑證消失**。
    // ⚠️ 而前端**只送 `(type, docNo, fileId)`，不送路徑** ——
    //    送路徑等於開一個任意檔案讀取。
    attachments: [],
    // `JV22`：退回與編修的長期紀錄（唯讀；來源是 GET /api/vouchers/{id}/edit-log）
    editLog: [],
    editLogErr: '',
    attErr: '',
    attMsg: '',
    uploading: false,
    exporting: false,
    //: `JV10`：原視窗預覽（`§228`）。previewHtml 是後端 `/preview` 端點
    //: 回的**整份 HTML 文件**，塞進 `<iframe srcdoc>`，不是 innerHTML。
    previewOpen: false,
    previewLoading: false,
    previewHtml: '',
    //: 帶入要寫到**哪一行**。預設第一行；使用者點過哪一格的摘要就換到那一行。
    summaryTarget: 0,

    // ── 狀態 ──
    loadError: '',
    actionErr: '',
    actionMsg: '',
    busy: false,
    //: 退回／作廢的理由輸入框（`''` ＝ 沒有展開）。
    askReason: '',
    reason: '',
    //: `JV34⑤`：作廢時勾「作廢並重開」。
    reopenOnVoid: false,
    //: `JV34①`：科目選單（含停用，標「（停用）」）。
    accountOptions: [],
    _accountsLoaded: false,
    //: `JV34②`：目前 focus 在哪一行（補平差額填這一行）。
    curLine: 0,
    //: `JV34④`：清單篩選。
    filterKw: '',
    filterFrom: '',
    filterTo: '',
    filterStatus: '',

    // 只有草稿可編輯（`SPEC-VOUCHER.md §一`）。
    // ⚠️ 這裡是**畫面的方便**，不是防線：真正的擋關在後端 `can_edit(status)`。
    get canEdit() { return this.status === '草稿' && !this.voidedAt },

    //: 這張單存過了沒。**新單與既有單能做的事不同**，而畫面上要看得出來。
    get isSaved() { return this.id > 0 },

    _token() {
      try {
        return (JSON.parse(localStorage.getItem('motrix_session') || '{}').token) || ''
      } catch (e) { return '' }
    },

    _auth() { return { Authorization: 'Bearer ' + this._token() } },

    _jsonAuth() {
      return { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() }
    },

    async init() {
      // `JV28`：附件清單一換（開單、上傳、刪除）就重建縮圖。
      this.$watch('attachments', () => this.loadThumbs())
      // 🔁 日期**可選，預設今天**（使用者 2026-09-23 改裁）。
      //    舊裁示「建檔當天且不可編輯」已被推翻 —— 月結補登是會計的日常。
      this.voucherDate = new Date().toLocaleDateString('sv-SE')   // YYYY-MM-DD（本地時區）
      for (let i = 0; i < 3; i++) this.addLine()
      await this.loadCompany()
      this.loadAccounts()
      await this.loadList()
      await this.loadSources()
      // 深連結：`voucher.html?id=12` 直接開那一張。
      const m = /[?&]id=(\d+)/.exec(window.location.search || '')
      if (m) await this.open(Number(m[1]))
    },

    // ── 摘要來源 ────────────────────────────────────────────────────

    async loadSources() {
      // ⚙️ **只在載入時拿一次** —— 切頁籤不重新打，也不重新帶入。
      // 🔴 選了案件之後會再打一次：那一趟回來之前，帶入面板的支出項區要說「載入中…」，
      //    不可以沿用上一趟的「請先選一個案件」（案件明明已經選了）。
      // ⚠️ 先渲染再非同步載入＝競態：發請求當下記住是哪一個案件，回來不符就整包丟掉
      //    （使用者在回應回來之前又換了案件）。
      const quote = this.sourceQuote
      this.sourcesLoading = true
      try {
        const q = quote ? '?quote_no=' + encodeURIComponent(quote) : ''
        const r = await fetch('/api/vouchers/summary-sources' + q,
                              { headers: this._auth() })
        if (!r.ok) throw new Error('HTTP ' + r.status)
        const d = await r.json()
        if (quote !== this.sourceQuote) return
        this.sources = d.tabs || {}
        this.sourceNotes = d.notes || {}
        // 模組不在（unavailable）與因權限沒列出（hidden）都要明說，不可以跟「沒有」長得一樣
        this.sourceUnavailable = (d.unavailable || []).concat(d.hidden || [])
        this.sourcesLoaded = true
      } catch (e) {
        if (quote !== this.sourceQuote) return
        this.sourceErr = '摘要來源載入失敗（' + e.message + '）。摘要仍然可以手動填寫。'
      } finally {
        if (quote === this.sourceQuote) this.sourcesLoading = false
      }
    },

    // `usedAt`／`uploaded_at` 是 ISO 字串，這裡只取到分鐘，不需要秒。
    fmtDateTime(s) {
      return String(s || '').replace('T', ' ').slice(0, 16)
    },

    // `JV33`：點（focus）哪一行摘要，帶入面板就對著那一行。
    focusLine(i) {
      this.summaryTarget = i
      this.panelLine = i
      // `JV36`（使用者：「點選 XXX 的時候它下方能自動連帶 XXX 內有的上傳檔案」）：這一行已有來源 ⇒
      // 右欄換成那個來源的檔案。📌 只換右欄顯示，**不寫摘要**（JV7：瀏覽不可以蓋掉使用者打的字）。
      const l = this.lines[i]
      if (!l || !l.source_type || !l.source_key) return
      if (this.srcSel.type === l.source_type && this.srcSel.key === String(l.source_key)) return
      this.srcSel = { type: l.source_type, key: String(l.source_key),
                      label: l.source_type === 'case' ? String(l.source_key) : (l.summary || String(l.source_key)) }
      this.loadLineFiles(l.source_type, l.source_key).then(() => this.loadSrcThumbs())
    },

    // ── `JV33` 帶入面板 ─────────────────────────────────────────────
    //
    // 使用者逐字：「我點傳票的摘要他也能自動帶入已上傳檔案跟支出項，不用每次來回點閱」。
    // ⇒ 摘要格 focus 時，**同時**列出「本傳票已上傳檔案」與「支出項」，不用切頁籤。
    // 🔴 面板的帶入是**接續**：摘要空白 ⇒ 填入；非空 ⇒ 以「；」接在後面。
    //    ⚠️ 只限面板——上面的頁籤區 `applySource()` 維持覆蓋（A 裁示，JV7／JV21 不翻面）。
    // ⚠️ 面板不在 blur 時關：點面板本身就會讓摘要格 blur，那樣永遠點不到。
    // 📌 「連金額一起帶入」這一輪不做（決定填借方還是貸方＝金額，待確認 N12）。
    panelLine: -1,
    panelMsg: '',   // `JV21`：帶入被擋時的說明

    // `JV36`：支出項的來源鍵——承攬商派工（含其品項／人員子列）＝派工 id，額外支出＝id。
    panelExpenses() {
      const out = []
      for (const it of ((this.sources || {})['支出項'] || [])) {
        const st = it.kind === 'contractor_dispatch' ? 'contractor_dispatch' : 'extra_expense'
        const key = String(it.id || '')
        // `JV21`：被**其他**未作廢傳票帶入過的（本張自己不算）
        const usedBy = (it.usedBy || []).filter(u => u.voucherId !== this.id)
        out.push({ summary: it.summary || '', child: false, source_type: st, source_key: key,
                   amount: it.amount, usedBy })
        for (const ch of (it.items || [])) {
          out.push({ summary: ch.summary || '', child: true, source_type: st, source_key: key,
                     amount: ch.amount, usedBy })
        }
      }
      return out.filter(function (e) { return e.summary && e.source_key })
    },

    panelCases() {
      return ((this.sources || {})['案件'] || []).map(function (it) {
        return { summary: it.summary || it.quote_no, source_type: 'case',
                 source_key: it.quote_no || '', customer_name: it.customer_name || '' }
      }).filter(function (e) { return e.source_key })
    },

    panelExpenseNote() { return (this.sourceNotes || {})['支出項'] || '' },

    // `JV36`：選 XXX ⇒ 那一行摘要**覆蓋**成 XXX 的名稱，並記住來源；下方帶出 XXX 的已上傳檔案。
    //   📌 更正留著：`JV33` 原本是「空白填入、非空以；接續」——使用者 2026-09-24 更正
    //      「我說的摘要要能帶動已上傳檔案，是別的意思……我點選 XXX 的時候它下方能自動連帶
    //      XXX 內有的上傳檔案」⇒ 拿掉接續。
    //   `N12`（使用者：「要，限空白行帶入借方」）：選支出項時，那一行借貸都空白 ⇒ 金額帶入**借方**；
    //      金額不是正整數元 ⇒ 不帶（不自行進位）。
    panelPick(e) {
      if (!this.canEdit || this.panelLine < 0 || !e) return
      const l = this.lines[this.panelLine]
      if (!l) return
      // `JV21`（使用者：「擋下，除非前一張已作廢」）：前端先擋，後端為準（同一套判定）。
      this.panelMsg = ''
      if (e.source_type !== 'case') {
        if ((e.usedBy || []).length) {
          this.panelMsg = '這筆支出已帶入傳票 ' + e.usedBy.map(u => u.voucherNo).join('、')
            + '（未作廢）；同一筆支出只能帶入一張傳票，如需重新帶入，請先作廢該張傳票。'
          return
        }
        const dup = this.lines.findIndex((x, i) => i !== this.panelLine
          && x.source_type === e.source_type && String(x.source_key) === String(e.source_key))
        if (dup >= 0) {
          this.panelMsg = '這筆支出已經在第 ' + (dup + 1) + ' 行帶入過，同一筆支出只能記一次。'
          return
        }
      }
      l.summary = e.summary
      l.source_type = e.source_type
      l.source_key = e.source_key
      // 2026-09-25（使用者：「同一案件按下支出項，只有第一筆金額會連動，第二筆不會」→ 裁示「同一行替換：金額跟著換」）：
      //   原本只在「借貸都空白」時帶入 ⇒ 同一行換成第二筆支出時，借方還是第一筆的金額，摘要與金額對不上。
      //   ⇒ 這一行的借方是**上一次自動帶入、而且使用者沒改過**的值時，換支出項就跟著換成新的金額；
      //      使用者手改過（或載入時就有的金額）⇒ 仍然不動（N12「不蓋掉人打的數字」不變）。
      //   `_autoDebit` 只存在畫面上，不送後端（存檔的欄位是逐欄挑的）。
      if (e.source_type !== 'case' && !String(l.credit || '').trim()) {
        const blank = !String(l.debit || '').trim()
        const autoUntouched = l._autoDebit != null && String(l.debit || '') === l._autoDebit
        if (blank || autoUntouched) {
          const a = this.parseAmount(e.amount)
          if (!a.err && a.v > 0) { l.debit = String(a.v); l._autoDebit = l.debit }
          else if (autoUntouched) { l.debit = ''; l._autoDebit = null }   // 新的一筆沒有可帶的金額 ⇒ 不留上一筆的
        }
      }
      // 稽核 D H-S3（2026-09-26）：同一行從自動帶入的支出換成「案件」時，摘要已經是案件，金額卻還是上一筆支出的
      //   ⇒ 借方仍是上一次自動帶入、沒被手改過的值 ⇒ 清空（手改過的照舊不動）。
      if (e.source_type === 'case' && l._autoDebit != null && String(l.debit || '') === l._autoDebit) {
        l.debit = ''; l._autoDebit = null
      }
      if (e.source_type === 'case' && e.source_key !== this.sourceQuote) {
        this.sourceQuote = e.source_key
        this.loadSources()
      }
      return this.loadLineFiles(e.source_type, e.source_key)
    },

    // ── 帶入來源區塊（2026-09-25，分錄下方：左案件、右已上傳檔案；取代右側面板）─────────
    //    區塊常駐（草稿時），帶入的目標是最後聚焦的那一行摘要；還沒點過摘要格就是第 1 行。
    srcTargetLine() {
      if (this.panelLine >= 0) return this.panelLine
      return this.summaryTarget >= 0 ? this.summaryTarget : 0
    },

    _ensureSrcTarget() {
      if (this.panelLine < 0) this.panelLine = this.srcTargetLine()
      if (!this.lines[this.panelLine]) { this.addLine(); this.panelLine = this.lines.length - 1 }
    },

    // 右欄顯示的是**目前選中的來源**（點案件 ⇒ 該案；點支出項 ⇒ 那一筆支出）的已上傳檔案。
    // 📌 2026-09-25：每行摘要底下的 JV36 清單拿掉後，支出項自己的檔案改在這裡看、這裡帶入。
    srcSel: { type: '', key: '', label: '' },

    // 點選被 JV21 擋下（已被其他傳票帶入／同一張裡重複）時 panelPick 不改那一行，右欄也不換。
    _selectSrc(e, loading) {
      if (!loading) return null
      this.srcSel = { type: e.source_type, key: String(e.source_key),
                      label: e.source_type === 'case' ? e.source_key : (e.summary || e.source_key) }
      return loading
    },

    async pickSrcCase(e) {
      if (!this.canEdit || !e) return
      this._ensureSrcTarget()
      const loading = this._selectSrc(e, this.panelPick(e))
      this.keepSummaryFocus()          // 先把焦點還給摘要格（使用者可以接著打字），檔案在背景載入
      if (!loading) return
      await loading
      this.loadSrcThumbs()
    },

    async srcPick(e) {
      if (!this.canEdit || !e) return
      this._ensureSrcTarget()
      const loading = this._selectSrc(e, this.panelPick(e))
      this.keepSummaryFocus()
      if (!loading) return
      await loading
      this.loadSrcThumbs()
    },

    srcState() {
      if (!this.srcSel.key) return { loading: false, files: [], err: '' }
      return this.lineFiles({ source_type: this.srcSel.type, source_key: this.srcSel.key })
    },

    srcFiles() { return this.srcState().files || [] },

    srcFileKey(f) { return f.type + '|' + f.docNo + '|' + f.fileId },

    _srcFileUrl(f) {
      return '/api/vouchers/line-source-file?source_type=' + encodeURIComponent(this.srcSel.type)
        + '&ref=' + encodeURIComponent(this.srcSel.key) + '&file_id=' + encodeURIComponent(f.fileId)
    },

    // 右欄縮圖：只給內嵌得了的圖片（同 JV28 的判準）；換來源時舊的 revoke。
    srcThumbs: {},

    async loadSrcThumbs() {
      const old = this.srcThumbs
      Object.keys(old).forEach(function (k) { URL.revokeObjectURL(old[k]) })
      this.srcThumbs = {}
      const sel = this.srcSel
      for (const f of this.srcFiles()) {
        if (f.exists === false || this.attKind(f) !== 'image') continue
        try {
          const type = this._ATT_IMAGE[f.filename.toLowerCase().slice(f.filename.lastIndexOf('.'))]
          const blob = await this._fetchAttBlob({ _url: this._srcFileUrl(f) }, type)
          if (sel !== this.srcSel) return               // 換了來源：這一批作廢
          this.srcThumbs = Object.assign({}, this.srcThumbs, { [this.srcFileKey(f)]: URL.createObjectURL(blob) })
        } catch (e) { /* 縮圖失敗不擋清單：點開預覽會說出錯誤 */ }
      }
    },

    async openSrcPreview(i) {
      const list = this.srcFiles().map(f => Object.assign({}, f, { _url: this._srcFileUrl(f) }))
      if (!list[i]) return
      this.attErr = ''
      this.attPv.mode = 'src'
      this.attPv.list = list
      this.attPv.ext = null
      this.attPv.open = true
      this._focusAttPv()
      await this._loadAttPv(i)
    },

    async bringFromPreview() {
      const f = this.attPvItem()
      if (!f || this.isBrought(f)) return
      await this.bringIn(f)
      if (this.isBrought(f)) this.closeAttPv()      // 失敗就留在視窗裡，錯誤顯示在下方
    },

    // ── `JV36`：各行來源的已上傳檔案（只列出；勾選才帶入）─────────────
    lineSrc: {},

    _srcKey(st, key) { return st + ':' + key },

    lineFiles(l) {
      return this.lineSrc[this._srcKey(l.source_type, l.source_key)]
        || { loading: false, files: [], err: '' }
    },

    async loadLineFiles(st, key) {
      if (!st || !key) return
      const k = this._srcKey(st, key)
      this.lineSrc = Object.assign({}, this.lineSrc, { [k]: { loading: true, files: [], err: '', unavailable: [] } })
      try {
        const r = await fetch('/api/vouchers/line-source-files?source_type=' + encodeURIComponent(st)
                              + '&ref=' + encodeURIComponent(key), { headers: this._auth() })
        const d = await r.json().catch(function () { return {} })
        if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status))
        this.lineSrc = Object.assign({}, this.lineSrc,
          { [k]: { loading: false, files: d.files || [], err: '', unavailable: (d.unavailable || []).concat(d.hidden || []) } })
      } catch (e) {
        this.lineSrc = Object.assign({}, this.lineSrc,
          { [k]: { loading: false, files: [], err: '來源檔案載入失敗（' + e.message + '）。' } })
      }
    },

    isBrought(f) {
      return (this.attachments || []).some(function (a) {
        return a.source_type === f.type && a.source_doc_no === f.docNo && a.source_file_id === f.fileId
      })
    },

    // 勾選 ⇒ 複製成傳票附件（沿用 `bringIn`，原檔被刪傳票仍保留）；失敗就把勾拿掉。
    // 點來源帶入後焦點回到那一行的摘要格：並排時使用者不必離開分錄就能接著打字（2026-09-25）。
    keepSummaryFocus() {
      const i = this.panelLine >= 0 ? this.panelLine : this.summaryTarget
      if (i == null || i < 0) return
      this.$nextTick(() => {
        const t = document.querySelectorAll('textarea[x-model="l.summary"]')[i]
        if (t) t.focus({ preventScroll: true })
      })
    },

    // ── 附件（`JV3`）──────────────────────────────────────────────

    async uploadAttachments(ev) {
      this.attErr = ''
      this.attMsg = ''
      const input = ev && ev.target
      const files = (input && input.files) || []
      if (!files.length || !this.id) return
      if (this.uploading) return
      this.uploading = true
      try {
        const fd = new FormData()
        for (const f of files) fd.append('files', f)
        // ⚠️ **不要自己設 Content-Type** —— multipart 的 boundary 由瀏覽器產生，
        //    手動設的話 boundary 會缺，而後端解析出 0 個檔案。
        const r = await fetch('/api/vouchers/' + this.id + '/attachments', {
          method: 'POST', headers: this._auth(), body: fd,
        })
        const d = await r.json().catch(function () { return {} })
        if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status))
        this.attachments = d.attachments || []
        this.attMsg = '已上傳 ' + (d.added || 0) + ' 個附件。'
      } catch (e) {
        this.attErr = e.message
      } finally {
        this.uploading = false
        // 🔑 清掉 input 的值，否則**同一個檔案選第二次不會觸發 change**。
        if (input) input.value = ''
      }
    },

    //: 從來源帶入一筆憑證。**只送 (type, docNo, fileId)**。
    //: ☠️ 送路徑等於開一個任意檔案讀取 —— 路徑由後端自己組。
    async bringIn(it) {
      this.attErr = ''
      this.attMsg = ''
      if (!this.id || !it) return
      if (this.uploading) return
      this.uploading = true
      try {
        const r = await fetch('/api/vouchers/' + this.id + '/attachments', {
          method: 'POST',
          headers: this._jsonAuth(),
          body: JSON.stringify({ picks: [
            { type: it.type, docNo: it.docNo, fileId: it.fileId },
          ] }),
        })
        const d = await r.json().catch(function () { return {} })
        if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status))
        this.attachments = d.attachments || []
        // ⚠️ 後端回的 `warning` **直接顯示**，不要在這裡重寫文案：
        //    那一句說的是「哪幾筆的上傳者／時間是空的」，規則只有一份。
        this.attMsg = d.warning || '已帶入 1 個附件。'
      } catch (e) {
        this.attErr = e.message
      } finally {
        this.uploading = false
      }
    },

    // 🔴 刪除是**軟刪**：DB 標記已刪，而**實體檔留著**（使用者裁定 `§163` ②）。
    //    而「離開草稿就不可刪」由後端擋 —— 這裡只負責不顯示那顆鈕。
    async deleteAttachment(a) {
      this.attErr = ''
      this.attMsg = ''
      if (!this.id || !a) return
      try {
        const r = await fetch('/api/vouchers/' + this.id
                              + '/attachments/' + encodeURIComponent(a.file_id), {
          method: 'DELETE', headers: this._auth(),
        })
        const d = await r.json().catch(function () { return {} })
        if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status))
        this.attachments = (this.attachments || []).filter(function (x) {
          return x.file_id !== a.file_id
        })
        this.attMsg = '已移除「' + (a.filename || '') + '」。檔案本身仍保留在系統裡。'
      } catch (e) {
        this.attErr = e.message
      }
    },

    // ── 匯出 PDF（`JV5`）────────────────────────────────────────────
    //
    // 🔴 兩個動作，不是一個：「只印本體」與「含附件」。
    //    ☠️ 只接一個的話，使用者以為印出來的就是全部。
    // ⚠️ 而**未併入的附件畫面也要說**，不能只有 PDF 裡有 ——
    //    呼叫端要靠回應的 header 才分得出「完整」與「缺了東西」。

    // 🔴 `JV11`：預覽**隨時可看**（不看簽核狀態），沒有閘門要擋——那支端點
    //    本來就是後端唯一沒有簽核檢查的那一個（`§228`：與匯出分成兩支端點，
    //    穿不過去也不必穿，它本來就對所有狀態開放）。
    async openPreview() {
      if (!this.id || this.previewLoading) return
      this.previewOpen = true
      this.previewLoading = true
      this.previewHtml = ''
      try {
        const r = await fetch('/api/vouchers/' + this.id + '/preview', {
          headers: this._auth(),
        })
        if (!r.ok) {
          let msg = 'HTTP ' + r.status
          try { msg = (await r.json()).detail || msg } catch (e) { /* 不是 JSON */ }
          throw new Error(msg)
        }
        this.previewHtml = await r.text()
      } catch (e) {
        // 🔑 iframe 沒有內容時使用者只會看到一片空白 —— 把錯誤訊息
        //    直接做成一份最小的 HTML 塞進 srcdoc，讓它也在 iframe 裡顯示，
        //    而不是讓 previewLoading 卡住或整個 modal 空白看不出原因。
        this.previewHtml = '<body style="font-family:sans-serif;padding:24px;'
          + 'color:#B91C1C">預覽失敗：' + this._esc(e.message) + '</body>'
      } finally {
        this.previewLoading = false
      }
    },

    //: `srcdoc` 塞進去的錯誤訊息只能是純文字，避免使用者輸入或後端訊息
    //: 裡剛好帶 HTML 特殊字元時被當成標籤解析。
    _esc(s) {
      return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
      })
    },

    async exportPdf(withAttachments) {
      this.attErr = ''
      this.attMsg = ''
      if (!this.id || this.exporting) return
      this.exporting = true
      try {
        const q = withAttachments ? '?with_attachments=1' : ''
        const r = await fetch('/api/vouchers/' + this.id + '/pdf-download' + q, {
          headers: this._auth(),
        })
        if (!r.ok) {
          // 🔑 失敗時後端回的是 JSON 不是 PDF ⇒ 讀得出那句話就用它。
          let msg = 'HTTP ' + r.status
          try { msg = (await r.json()).detail || msg } catch (e) { /* 不是 JSON */ }
          throw new Error(msg)
        }
        const blob = await r.blob()
        // ⚠️ `download` 屬性要配 blob URL；用完**一定要 revoke**，
        //    否則每匯出一次就在記憶體裡留一份整包 PDF。
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = 'voucher-' + (this.voucherNo || this.id) + '.pdf'
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)

        const n = Number(r.headers.get('X-Voucher-Missing-Attachments') || 0)
        if (n > 0) {
          // 🔴 **畫面也要說**：只印在紙上的話，使用者要翻到最後一頁才知道。
          let names = ''
          try {
            names = decodeURIComponent(
              r.headers.get('X-Voucher-Missing-Attachment-Names') || '')
          } catch (e) { /* 解不開就只報筆數 */ }
          this.attErr = '已匯出，而有 ' + n + ' 個附件沒有併進去'
            + (names ? ('：' + names) : '')
            + '。PDF 最後一頁列出了它們；這些附件仍然登記在這張傳票上。'
        } else {
          this.attMsg = withAttachments ? '已匯出（含附件）。' : '已匯出。'
        }
      } catch (e) {
        this.attErr = '匯出失敗（' + e.message + '）。'
      } finally {
        this.exporting = false
      }
    },

    //: 這一筆附件是**帶入的**還是**當場上傳的**。畫面上要分得出來。
    attFrom(a) { return (a && a.source_type) ? '帶入' : '上傳' },

    //: `JV16③`：`mergeKind` 由後端算（`voucher_pdf.py::classify_attachment_kind()`），
    //: 這裡只是換成看得懂的字，不重寫副檔名判斷。
    mergeKindLabel(kind) {
      return {
        image: '預計併入（圖片）',
        pdf: '預計併入（PDF）',
        unsupported: '不支援的格式，不會併入',
      }[kind] || ''
    },

    // `JV16②`：`<img src>`／`<a href>` 帶不了 `Authorization` header，
    // 最省力的錯法是把 token 塞進 query string——**不可以**，那條網址
    // 會被 uvicorn access log 永久記錄在 `logs/server.log`。
    // ⇒ fetch 帶 header 拿 blob。
    // 📌 更正留著：`JV16` 原本把 blob 指給 `window.open` 開新分頁；`JV28` 改成頁內預覽窗
    //    （`window.open` 在 await 之後已不是使用者手勢，且會離開傳票畫面）。
    // ── `JV28`：附件頁內預覽（取代 window.open） ─────────────────────
    //
    // 使用者逐字：「在傳票上，已上傳檔案要能夠預覽，只有名稱無法辨別」。
    // 🔴 安全界線（`SPEC-JV28 §3`）：**只有**下面兩張表列出的類型可以內嵌，
    //    而且伺服器存的 mime **與**副檔名兩者都要符合；只看一個就不內嵌。
    //    ☠️ SVG／HTML 內嵌 ＝ 在我們的網域執行上傳者的腳本 ⇒ 一律只給下載。
    //    ⚠️ mime 取自上傳者宣稱的 content-type（`helpers/uploads.py`）⇒ 它可以是假的，
    //       所以副檔名是另一半，缺一不可。
    // 🔑 blob 建立時**明確指定 type**（用我們判定的那個，不用回應標頭的），不讓瀏覽器猜。
    _ATT_IMAGE: { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                  '.gif': 'image/gif', '.webp': 'image/webp' },
    _ATT_PDF: { '.pdf': 'application/pdf' },

    attKind(a) {
      const name = String((a && a.filename) || '').toLowerCase()
      const dot = name.lastIndexOf('.')
      const ext = dot >= 0 ? name.slice(dot) : ''
      const mime = String((a && a.mime) || '').toLowerCase().split(';')[0].trim()
      if (this._ATT_IMAGE[ext] && this._ATT_IMAGE[ext] === mime) return 'image'
      if (this._ATT_PDF[ext] && this._ATT_PDF[ext] === mime) return 'pdf'
      return 'download'
    },

    async _fetchAttBlob(a, type) {
      // `JV36`：來源檔（還沒帶入）帶著自己的 `_url`。
      const url = a._url
        || '/api/vouchers/' + this.id + '/attachments/' + encodeURIComponent(a.file_id)
      const r = await fetch(url, { headers: this._auth() })
      if (!r.ok) throw new Error('HTTP ' + r.status)
      return new Blob([await r.arrayBuffer()], { type: type })
    },

    // 預覽 modal 的狀態。`url` 只在 image／pdf 時才有；關閉或切換時 revoke。
    // mode：'att'＝本傳票附件（只看）、'src'＝分錄下方的來源檔（可帶入，list 是那一案的檔案）、
    //       'ext'＝JV36 單一來源檔（每行的勾選清單）。
    attPv: { open: false, idx: -1, kind: '', url: '', err: '', loading: false, ext: null, mode: 'att', list: null },

    openAttachment(a) {
      // `JV16` 那份清單（預覽窗內）與編輯頁清單**共用同一個頁內預覽窗**，不再 window.open。
      return this.openAttPreview(a)
    },

    async openAttPreview(a) {
      const idx = this.attachments.indexOf(a)
      if (idx < 0) return
      this.attPv.mode = 'att'
      this.attPv.list = null
      this.attPv.ext = null
      this.attPv.open = true
      this._focusAttPv()
      await this._loadAttPv(idx)
    },

    // `JV36`：預覽一個還沒帶入的來源檔（同一個預覽窗、同一套內嵌規則）。
    async openExtPreview(item) {
      this.attPv.mode = 'ext'
      this.attPv.list = null
      this.attPv.ext = item
      this.attPv.open = true
      this._focusAttPv()
      await this._loadAttPv(-1)
    },

    attPvItems() { return this.attPv.list || this.attachments || [] },

    // 視窗下方：來源檔寫「案件單號・上傳日期」；附件寫來源與大小。
    attPvMeta() {
      const it = this.attPvItem()
      if (!it) return ''
      if (this.attPv.mode === 'src') {
        const at = String(it.uploadedAt || '').slice(0, 10)
        const who = this.srcSel.type === 'case' ? '案件 ' + this.srcSel.key : this.srcSel.label
        return who + (at ? '　上傳 ' + at : '')
      }
      return this.attPv.mode === 'att' ? (this.fileSize(it.size) || '') : ''
    },

    // MotrixUI 的鍵盤規則：打開時焦點進視窗、Tab 鎖在視窗內、關閉後焦點回到原位。
    _attPvOpener: null,

    _focusAttPv() {
      this._attPvOpener = document.activeElement
      this.$nextTick(() => {
        const box = this.$refs.attPvBox
        const first = box && (box.querySelector('[data-testid="att-pv-cancel"]')
                              || box.querySelector('[data-testid="voucher-att-close"]'))
        if (first) first.focus()
      })
    },

    trapAttPvTab(ev) {
      const box = this.$refs.attPvBox
      if (!box) return
      const f = Array.from(box.querySelectorAll('button, [href], iframe, [tabindex]:not([tabindex="-1"])'))
        .filter(el => !el.disabled && el.offsetParent !== null)
      if (!f.length) { ev.preventDefault(); return }
      const first = f[0], last = f[f.length - 1]
      const inside = box.contains(document.activeElement)
      if (ev.shiftKey && (document.activeElement === first || !inside)) { ev.preventDefault(); last.focus() }
      else if (!ev.shiftKey && (document.activeElement === last || !inside)) { ev.preventDefault(); first.focus() }
    },

    _revokeAttPv() {
      if (this.attPv.url) URL.revokeObjectURL(this.attPv.url)
      this.attPv.url = ''
    },

    async _loadAttPv(idx) {
      this._revokeAttPv()
      const a = this.attPv.ext || this.attPvItems()[idx]
      if (!a) return
      this.attPv.idx = idx
      this.attPv.err = ''
      this.attPv.kind = this.attKind(a)
      if (this.attPv.kind === 'download') return
      this.attPv.loading = true
      try {
        const type = this.attPv.kind === 'image'
          ? this._ATT_IMAGE[a.filename.toLowerCase().slice(a.filename.lastIndexOf('.'))]
          : 'application/pdf'
        const blob = await this._fetchAttBlob(a, type)
        // 回來時若已經切到別的附件或關掉了，丟掉這一份（先渲染再非同步載入的競態）。
        if (!this.attPv.open || this.attPv.idx !== idx) return
        this.attPv.url = URL.createObjectURL(blob)
      } catch (e) {
        this.attPv.err = '取得附件失敗（' + e.message + '）。'
      } finally {
        this.attPv.loading = false
      }
    },

    attPvItem() { return this.attPv.ext || this.attPvItems()[this.attPv.idx] || null },

    stepAttPv(d) {
      const n = this.attPvItems().length
      if (!this.attPv.open || !n || this.attPv.ext) return
      return this._loadAttPv((this.attPv.idx + d + n) % n)
    },

    closeAttPv() {
      if (!this.attPv.open) return
      this._revokeAttPv()
      this.attPv.open = false
      this.attPv.ext = null
      this.attPv.list = null
      this.attPv.mode = 'att'
      this.attPv.idx = -1
      this.attPv.kind = ''
      const back = this._attPvOpener
      this._attPvOpener = null
      if (back && back.focus && document.contains(back)) this.$nextTick(() => back.focus({ preventScroll: true }))
    },

    async downloadAttachment(a) {
      if (!a) return
      try {
        // 下載一律用 octet-stream：就算伺服器存的是 image/svg+xml，瀏覽器也不會把它當網頁打開。
        const blob = await this._fetchAttBlob(a, 'application/octet-stream')
        const url = URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.download = a.filename || 'attachment'
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
        setTimeout(function () { URL.revokeObjectURL(url) }, 1000)
      } catch (e) {
        this.attPv.err = '下載失敗（' + e.message + '）。'
      }
    },

    // 縮圖（約 48px）：只給內嵌得了的圖片；每次附件清單換了就重建，舊的 revoke。
    attThumbs: {},

    async loadThumbs() {
      const old = this.attThumbs
      Object.keys(old).forEach(function (k) { URL.revokeObjectURL(old[k]) })
      this.attThumbs = {}
      const vid = this.id
      for (const a of this.attachments || []) {
        if (this.attKind(a) !== 'image') continue
        try {
          const type = this._ATT_IMAGE[a.filename.toLowerCase().slice(a.filename.lastIndexOf('.'))]
          const blob = await this._fetchAttBlob(a, type)
          if (vid !== this.id) return
          this.attThumbs = Object.assign({}, this.attThumbs, { [a.file_id]: URL.createObjectURL(blob) })
        } catch (e) { /* 縮圖失敗不擋清單：檔名仍可點開預覽，那裡會說出錯誤 */ }
      }
    },


    fileSize(n) {
      const v = Number(n) || 0
      if (!v) return ''
      if (v < 1024) return v + ' B'
      if (v < 1024 * 1024) return (v / 1024).toFixed(1) + ' KB'
      return (v / 1024 / 1024).toFixed(1) + ' MB'
    },

    async loadCompany() {
      // ⚠️ 抬頭從設定讀。**不要寫死** —— 這個 repo 已經寫死在 14 個檔、56 行。
      try {
        const r = await fetch('/api/settings/company-profile', { headers: this._auth() })
        if (!r.ok) throw new Error('HTTP ' + r.status)
        this.company = (await r.json()).name || ''
      } catch (e) {
        // 🔑 抬頭讀不到**不該讓整頁不能用** —— 它只是版面上的一行字。
        //    而它也不可以靜默：使用者要看得出來是「沒設定」還是「讀失敗」。
        this.loadError = '公司抬頭讀取失敗（' + e.message + '）。版面其餘部分仍可使用。'
      }
    },

    // ── 清單 ────────────────────────────────────────────────────────

    async loadList() {
      try {
        const q = this.includeVoided ? '?include_voided=true' : ''
        const r = await fetch('/api/vouchers' + q, { headers: this._auth() })
        if (!r.ok) throw new Error('HTTP ' + r.status)
        const d = await r.json()
        this.list = d.vouchers || []
        this.listLoaded = true
      } catch (e) {
        this.loadError = '傳票清單載入失敗（' + e.message + '）。請重新整理，若持續發生請回報。'
      }
    },

    async toggleVoided() {
      this.includeVoided = !this.includeVoided
      await this.loadList()
    },

    // ── 讀一張 ──────────────────────────────────────────────────────

    //: 讀一張單。`keepMsg` ＝ 保留目前的成功／錯誤訊息。
    //: 🔴 **不加這個參數的話，成功訊息會被自己洗掉**：
    //:    三條成功路徑都是「設定訊息 -> 重讀這張單」，而重讀的第一件事
    //:    就是清訊息 ⇒ 使用者按下儲存，畫面**什麼都不說**。
    //: ☠️ 而「什麼都不說」與「壞掉了」長得一樣 —— 他會再按一次。
    //: ⚙️ 從清單點開另一張時**不傳它**（要清掉上一張的訊息）。
    async open(vid, keepMsg) {
      if (!keepMsg) this._clearMsg()
      try {
        const r = await fetch('/api/vouchers/' + vid, { headers: this._auth() })
        const d = await r.json().catch(function () { return {} })
        if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status))
        this._apply(d)
      } catch (e) {
        this.actionErr = e.message
      }
    },

    _apply(d) {
      this.editing = true
      this.id = d.id || 0
      this.voucherNo = d.voucher_no || ''
      this.voucherDate = d.voucher_date || this.voucherDate
      this.category = d.category || '轉'
      this.categoryManual = !!d.category_manual
      this.status = d.status || '草稿'
      this.note = d.summary || ''
      this.voidedAt = d.voided_at || ''
      // ⚠️ 後端沒有分錄時給三行空的，讓畫面不是一片空白；
      //    **而有分錄時一行都不補** —— 補出來的空行會被當成使用者打的。
      const ls = (d.lines || []).map(function (l) {
        return {
          account_code: l.account_code || '',
          account_name: l.account_name || '',
          summary: l.summary || '',
          // 🔑 0 要顯示成**空白**不是 `0`：使用者的實例上，借方有數字時
          //    貸方那一格是留白的。而 `0` 在會計上是一個有意義的數字。
          debit: l.debit ? String(l.debit) : '',
          credit: l.credit ? String(l.credit) : '',
          // `JV36`：這一行的摘要來自哪一筆（重開時依它重新帶出來源檔案清單）
          source_type: l.source_type || '',
          source_key: l.source_key || '',
        }
      })
      this.lines = ls.length ? ls : [{ account_code: '', account_name: '', summary: '', debit: '', credit: '', source_type: '', source_key: '' }]
      // 🔴 三格印的是**人名**，不是 token。
      //    後端 `signatures_of()` 回 `{格名: {by, at}}`，而 `by` 是 `username`
      //    —— 2026-09-23 修過一次：舊碼存的是 `_tok(auth)` 的**原始 bearer token**，
      //    而這一格會把那串 64 字元印在「製票」上。
      const s = d.signatures || {}
      this.signs = Object.keys(s).map(function (k) { return { label: k, by: (s[k] || {}).by || '' } })
      this.attachments = d.attachments || []
      // `JV36`：依已存的來源重新帶出各行的來源檔案清單。
      for (const l of this.lines) if (l.source_type) this.loadLineFiles(l.source_type, l.source_key)
      this.summaryTarget = 0
      this.editLog = []
      this.editLogErr = ''
      if (this.id) this.loadEditLog()
      // 🔑 網址帶上 `?id=`，**重新整理會回到同一張單**。
      //    ☠️ 少了它：使用者改完摘要、存檔、按 F5 ⇒ 回到一張空白新單
      //       ⇒ 他會以為「剛剛存的不見了」。
      //    ⚠️ 用 `replaceState` 不是 `pushState`：這不是一次導覽，
      //       上一頁不該退回到同一張單的前一個狀態。
      try {
        if (this.id && window.history && window.history.replaceState) {
          window.history.replaceState({}, '', 'voucher.html?id=' + this.id)
        }
      } catch (e) { /* 網址更新失敗不影響任何功能 */ }
    },

    // ── `JV22`：退回與編修（唯讀） ──────────────────────────────────
    //
    // 使用者原話：「傳票如果有退回，需顯示上次退回跟這次編修的內容，長期記憶，
    // 這個不能刪除」⇒ 成對顯示（一次退回 ＋ 其後的編修），不是流水帳。
    // ⚠️ 這一區**沒有任何編輯或刪除控制項**：一個看起來像備註欄的東西，
    //    下一個人會很自然地加上編輯功能（`SPEC-JV22 §6`）。

    async loadEditLog() {
      const vid = this.id
      try {
        const r = await fetch('/api/vouchers/' + vid + '/edit-log', { headers: this._auth() })
        const d = await r.json().catch(function () { return {} })
        if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status))
        // 🔑 回來時若已經換了一張單，整包丟掉（先渲染再非同步載入的競態）。
        if (vid !== this.id) return
        this.editLog = d.entries || []
      } catch (e) {
        if (vid !== this.id) return
        this.editLogErr = '退回與編修紀錄載入失敗（' + e.message + '）。'
      }
    },

    _isSendBack(e) {
      return (e.changes || []).some(function (c) {
        return c.field === 'status' && c.to === '草稿'
      })
    },

    // 由新到舊：每一組＝一次退回 ＋ 它之後、下一次退回之前的所有編修。
    editGroups() {
      const out = []
      let cur = null
      for (const e of this.editLog || []) {
        if (this._isSendBack(e)) {
          cur = { back: e, edits: [] }
          out.push(cur)
        } else if (cur) {
          for (const c of e.changes || []) cur.edits.push({ at: e.at, by: e.byName || e.by, c: c })
        }
      }
      return out.reverse()
    },

    backField(e, name) {
      const c = (e.changes || []).find(function (x) { return x.field === name })
      return c || { from: '', to: '' }
    },

    editFieldLabel(f) {
      const m = { summary: '摘要', voucher_date: '傳票日期', category: '傳票別',
                  category_manual: '傳票別判斷方式',
                  attachment: '附件', status: '狀態', voucher_no: '單號', lines: '分錄' }
      if (m[f]) return m[f]
      const mm = /^lines\[(\d+)\](?:\.(\w+))?$/.exec(f || '')
      if (mm) {
        const col = { account_code: '科目', summary: '摘要', debit: '借方', credit: '貸方', source: '摘要來源' }[mm[2]] || ''
        return '第 ' + (Number(mm[1]) + 1) + ' 行分錄' + (col ? ' ' + col : '')
      }
      return f
    },

    editValue(v) {
      if (v === null || v === undefined || v === '') return '（空）'
      if (typeof v === 'object') return JSON.stringify(v)
      return String(v)
    },

    // ── 建立／儲存 ──────────────────────────────────────────────────

    newVoucher() {
      this._clearMsg()
      this.editing = true
      this.id = 0
      this.voucherNo = ''
      this.voucherDate = new Date().toLocaleDateString('sv-SE')
      this.category = '轉'
      this.categoryManual = false
      this.status = '草稿'
      this.note = ''
      this.voidedAt = ''
      this.lines = []
      for (let i = 0; i < 3; i++) this.addLine()
      // 新單還沒有簽核資料 ⇒ 先畫內建兩層的版面（製票／覆核／主管／記帳），都是空的。
      this.signs = ['製票', '覆核', '主管', '記帳'].map(function (k) { return { label: k, by: '' } })
      this.summaryTarget = 0
      // ⚠️ 網址上的 `?id=` 要一起拿掉，否則按 F5 會跳回剛才那一張，
      //    而使用者以為自己在開新單。
      try {
        if (window.history && window.history.replaceState) {
          window.history.replaceState({}, '', 'voucher.html')
        }
      } catch (e) { /* 忽略 */ }
    },

    // `JV32`：一格金額 ⇒ { v: 整數 } 或 { err: 原因 }。規則與後端
    // `helpers/voucher.py::parse_amount()` 相同（後端是權威，前端先擋是為了當場說清楚）。
    // ☠️ 原本是 `Number(x) || 0`：`Number("1,000")` 是 NaN ⇒ 存成 0，畫面還說「已儲存」。
    parseAmount(raw) {
      if (raw === null || raw === undefined) return { v: 0 }
      const text = String(raw)
        .replace(/[０-９]/g, function (c) { return String.fromCharCode(c.charCodeAt(0) - 0xFEE0) })
        .replace(/，/g, ',').replace(/．/g, '.').replace(/－/g, '-')
        .trim().replace(/[,\s]/g, '')
      if (text === '') return { v: 0 }
      const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec(text)
      if (!m) return { err: '金額格式看不懂（「' + String(raw).trim() + '」）' }
      if (m[3] && /[1-9]/.test(m[3])) return { err: '金額以新台幣元為單位，不可有小數' }
      if (m[1]) return { err: '金額不可以是負數' }
      return { v: parseInt(m[2], 10) }
    },

    _amt(raw) { const r = this.parseAmount(raw); return r.err ? 0 : r.v },

    //: 送給後端的分錄。**過濾掉整行空白的**，否則一張三行的單會存進三筆空分錄。
    // ⚠️ 行號要跟後端訊息對得上 ⇒ 問題清單用**過濾後**的行號（後端看到的就是這一組）。
    _payloadRows() {
      return this.lines.filter(function (l) {
        return (l.account_code || '').trim() || (l.summary || '').trim()
          || String(l.debit || '').trim() || String(l.credit || '').trim()
      })
    },

    _amountProblems() {
      const self = this
      const out = []
      this._payloadRows().forEach(function (l, i) {
        const errs = []
        const d = self.parseAmount(l.debit), c = self.parseAmount(l.credit)
        if (d.err) errs.push('借方' + d.err)
        if (c.err) errs.push('貸方' + c.err)
        if (!errs.length && d.v && c.v) errs.push('借方與貸方只能填其中一邊')
        if (errs.length) out.push('第 ' + (i + 1) + ' 行：' + errs.join('；'))
      })
      return out.length ? out.join('。') + '。' : ''
    },

    _payloadLines() {
      const self = this
      return this._payloadRows().map(function (l) {
        return {
          account_code: (l.account_code || '').trim(),
          summary: (l.summary || '').trim(),
          // ⚠️ 空字串送 0，而畫面上仍然留白。
          debit: self._amt(l.debit),
          credit: self._amt(l.credit),
          source_type: l.source_type || '',
          source_key: l.source_key || '',
        }
      })
    },

    async save() {
      this._clearMsg()
      if (this.busy) return
      // `JV32`：金額有問題 ⇒ 當場說出第幾行、不送出（後端也會擋，這裡是讓使用者不必等一趟）。
      const bad = this._amountProblems()
      if (bad) { this.actionErr = bad; return }
      if (this.isSaved) {
        await this._saveExisting()
        return
      }
      this.busy = true
      try {
        const r = await fetch('/api/vouchers', {
          method: 'POST',
          headers: this._jsonAuth(),
          body: JSON.stringify({
            voucher_date: this.voucherDate,
            category: this.category,
            category_manual: this.categoryManual,
            summary: this.note,
            lines: this._payloadLines(),
          }),
        })
        const d = await r.json().catch(function () { return {} })
        if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status))
        this.actionMsg = '已儲存草稿，傳票號碼 ' + d.voucher_no + '。'
        await this.open(d.id, true)
        await this.loadList()
      } catch (e) {
        this.actionErr = e.message
      } finally {
        this.busy = false
      }
    },

    // 🔴 既有草稿：**四樣一起送**（日期／類別／備註／分錄）。
    //
    // ⚠️ `lines` 這個鍵**有帶就代表要覆寫整組** —— 後端用 `"lines" in body`
    //    判斷（鍵在不在），不是用值的真假：送 `lines: []` 是「清空分錄」，
    //    與「沒提到分錄」是兩件事。
    // 📌 這條路 2026-09-23 之前是壞的：`PUT` 只吃三個欄位而不碰 `voucher_lines`
    //    ⇒ 回 200、單子還在、**而分錄原封不動**。
    //    ☠️ 那種壞法不會被報修：使用者下次打開看到舊數字，
    //       **會懷疑自己記錯了**，不會懷疑系統。
    async _saveExisting() {
      this.busy = true
      try {
        const r = await fetch('/api/vouchers/' + this.id, {
          method: 'PUT',
          headers: this._jsonAuth(),
          body: JSON.stringify({
            voucher_date: this.voucherDate,
            category: this.category,
            category_manual: this.categoryManual,
            summary: this.note,
            lines: this._payloadLines(),
          }),
        })
        const d = await r.json().catch(function () { return {} })
        if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status))
        // ⚠️ 講「項」不是「欄位」：`changed` 現在含**分錄的逐行異動**，
        //    而那不是單據上的欄位。數字對而名詞錯的話，使用者會去找那兩個欄位。
        this.actionMsg = d.changed ? ('已儲存（' + d.changed + ' 項異動）。') : '沒有任何異動。'
        await this.open(this.id, true)
        await this.loadList()
      } catch (e) {
        this.actionErr = e.message
      } finally {
        this.busy = false
      }
    },

    // ── 流程動作（送審／簽核／退回／過帳／作廢）──────────────────────
    //
    // 🔑 這五支全部**不在前端判可不可以做** —— 只依後端回的 `status` 決定按鈕
    //    顯不顯示，而按下去能不能成立由後端說。
    // ☠️ 前端自己判就是第二份判準，它會在某天與後端不一致 ⇒
    //    使用者看到「畫面說可以，按下去被拒絕」。

    async _act(path, body, okMsg) {
      this._clearMsg()
      if (this.busy || !this.id) return
      this.busy = true
      try {
        const r = await fetch('/api/vouchers/' + this.id + path, {
          method: 'POST',
          headers: this._jsonAuth(),
          body: JSON.stringify(body || {}),
        })
        const d = await r.json().catch(function () { return {} })
        if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status))
        this.actionMsg = okMsg(d)
        this.askReason = ''
        this.reason = ''
        await this.open(this.id, true)
        await this.loadList()
        return d
      } catch (e) {
        this.actionErr = e.message
      } finally {
        this.busy = false
      }
    },

    submit() { return this._act('/submit', {}, function () { return '已送出審核。' }) },

    approve() {
      // ⚠️ 兩層簽核（`§161` 寫死）：覆核 → 主管。**下一格是誰由後端算**，
      //    這裡只把它回報的新狀態印出來。
      return this._act('/approve', {}, function (d) { return '已簽核，目前狀態：' + d.status + '。' })
    },

    post() {
      // 🔴 借貸平不平衡由後端 `describe_balance()` 判。
      //    ☠️ 前端先擋的話，兩份判準會在某天分岔。
      return this._act('/post', {}, function () { return '已過帳。' })
    },

    sendBack() {
      // 🔴 退回要三件一起：狀態回草稿 ＋ 清除簽核 ＋ **單號升版 -Rn**。
      //    少了升版的話，同一張被退兩次看不出來（`§103e`：財務不可接受）。
      return this._act('/send-back', { reason: this.reason },
        function (d) { return '已退回修改，新單號 ' + (d.voucher_no || '') + '。' })
    },

    async voidIt() {
      // 🔑 沒有理由的作廢等於沒有留痕：事後沒有人回得出為什麼（後端直接回 400）。
      // `JV34⑤`：勾了「作廢並重開」⇒ 後端另開一張草稿（照抄分錄與附件），成功後直接打開新單。
      const reopen = !!this.reopenOnVoid
      const d = await this._act('/void', { reason: this.reason, reopen: reopen }, function (r) {
        return reopen && r.new_voucher_no
          ? '已作廢，並重開為 ' + r.new_voucher_no + '（草稿）。'
          : '已作廢。原單仍留在系統裡，可在清單勾選「含已作廢」查看。'
      })
      this.reopenOnVoid = false
      if (d && d.new_id) await this.open(d.new_id, true)
    },

    openReason(kind) {
      this._clearMsg()
      this.askReason = kind
      this.reason = ''
    },

    cancelReason() { this.askReason = ''; this.reason = '' },

    _clearMsg() { this.actionErr = ''; this.actionMsg = '' },

    // ── 分錄 ────────────────────────────────────────────────────────

    addLine() {
      // 🔑 金額預設是**空字串不是 0** —— 使用者的實例上，借方有數字時
      //    貸方那一格是**留白**的，不是印一個 0。
      //    ☠️ 印 0 的話，一張只有三行的傳票看起來像有六個金額；
      //       而「0」在會計上是一個**有意義的數字**，不等於「沒有填」。
      this.lines.push({ account_code: '', account_name: '', summary: '', debit: '', credit: '', source_type: '', source_key: '' })
    },

    removeLine(i) {
      if (!this.canEdit) return
      this.lines.splice(i, 1)
      if (!this.lines.length) this.addLine()
    },

    async fillName(i) {
      // 輸入科目代號後帶出名稱。
      // ⚠️ 帶不出來時**不要清空使用者打的東西**，也不要擋他繼續打 ——
      //    代號對不對由後端在儲存時判（`validate_account_code`）。
      const code = (this.lines[i].account_code || '').trim()
      if (!code) { this.lines[i].account_name = ''; return }
      // `JV34①`：名稱欄唯讀 ⇒ 一律由代號帶出（選單已載入就查選單，不再每次打一趟）。
      if (!this._accountsLoaded) await this.loadAccounts()
      const hit = this.accountOptions.find(function (a) { return a.code === code })
      this.lines[i].account_name = hit ? (hit.name + (hit.active ? '' : '（停用）')) : ''
    },

    // `JV34①`：科目選單（含停用）。選項的 value 是代號、label 是「代號 名稱」，
    // 瀏覽器的 datalist 對兩者都做子字串比對 ⇒ 打代號或名稱都搜得到。
    async loadAccounts() {
      try {
        const r = await fetch('/api/account-items?include_inactive=true', { headers: this._auth() })
        if (!r.ok) return
        const d = await r.json()
        const out = []
        const walk = function (nodes) {
          for (const n of nodes || []) {
            const active = n.is_active === undefined ? true : !!n.is_active
            out.push({ code: n.code, name: n.name, active: active,
                       label: n.code + ' ' + n.name + (active ? '' : '（停用）') })
            walk(n.children)
          }
        }
        walk(d.tree || [])
        this.accountOptions = out
        this._accountsLoaded = true
      } catch (e) { /* 選單載不到仍可手打代號，存檔時後端會驗 */ }
    },

    // `JV34②`：最後一行按 Enter ⇒ 新增一行並跳到新行的科目欄。
    onEnter(ev, i) {
      if (!this.canEdit || i !== this.lines.length - 1) return
      ev.preventDefault()
      this.addLine()
      this.$nextTick(() => {
        const rows = this.$root.querySelectorAll("tbody tr input[list='vc-accounts']")
        const el = rows[rows.length - 1]
        if (el) el.focus()
      })
    },

    // `JV34②`：補平差額——只在目前這一行借貸都空白、而差額 ≠ 0 時可按；差額填在合計較少的那一側。
    get canBalance() {
      const l = this.lines[this.curLine]
      if (!this.canEdit || !l) return false
      if (String(l.debit || '').trim() || String(l.credit || '').trim()) return false
      return this.totalDebit !== this.totalCredit
    },

    fillBalance() {
      if (!this.canBalance) return
      const l = this.lines[this.curLine]
      const diff = this.totalDebit - this.totalCredit
      if (diff > 0) l.credit = String(diff)
      else l.debit = String(-diff)
    },

    // `JV29`：與 `helpers/voucher.py::CATEGORY_TITLES` 同一組名稱。
    // 還沒存過的新單沒有判斷結果 ⇒ 說清楚什麼時候會有，不要先印一個「轉帳傳票」。
    get kindTitle() {
      if (!this.id && !this.categoryManual) return '（存檔後依分錄判斷）'
      return { '收': '收入傳票', '支': '支出傳票', '轉': '轉帳傳票' }[this.category] || '傳票'
    },

    // `N6`：類別選單的值——自動模式是 'auto'，手動模式是那個類別。
    //    選「恢復自動判斷」⇒ 存檔時伺服器依分錄重算；選一個類別 ⇒ 手動，之後改分錄不覆蓋。
    get kindChoice() { return this.categoryManual ? this.category : 'auto' },
    set kindChoice(v) {
      if (v === 'auto') { this.categoryManual = false; return }
      this.category = v
      this.categoryManual = true
    },

    // `JV34④`：清單篩選（關鍵字比對號碼或摘要；日期區間含頭尾；狀態含「已作廢」）。
    get filteredList() {
      const kw = (this.filterKw || '').trim()
      const from = this.filterFrom, to = this.filterTo, st = this.filterStatus
      return (this.list || []).filter(function (v) {
        if (kw && !((v.voucher_no || '').includes(kw) || (v.summary || '').includes(kw))) return false
        const d = (v.voucher_date || '').slice(0, 10)
        if (from && d < from) return false
        if (to && d > to) return false
        const vs = v.voided_at ? '已作廢' : v.status
        if (st && vs !== st) return false
        return true
      })
    },

    // 🔑 合計在前端即時算，**而它只是顯示** ——
    //    能不能過帳由後端 `check_balance()` 決定（A 明著交代）。
    //    ☠️ 前端自己判的話就是第二份判準，而它會在某天與後端不一致 ⇒
    //       使用者看到「畫面說可以，按下去被拒絕」。
    get totalDebit() { return this.lines.reduce((s, l) => s + this._amt(l.debit), 0) },
    get totalCredit() { return this.lines.reduce((s, l) => s + this._amt(l.credit), 0) },

    fmt(n) {
      if (n === undefined || n === null) return ''
      return Math.round(n).toLocaleString()
    },

    shortDate(s) { return (s || '').slice(0, 10) },
  }
}
