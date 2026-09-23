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
    // ⇒ 所以 `pickTab()` **只換頁籤，一個字都不寫回分錄**；
    //   唯一會寫進 `l.summary` 的是 `applySource()`，而它只在**點一筆來源**時跑。
    sourceTab: '案件',
    sources: {},
    sourceNotes: {},
    sourcesLoaded: false,
    sourceErr: '',
    //: 頁籤②「已上傳檔案」要先知道**是哪一個案件** —— 憑證掛在案件底下。
    sourceQuote: '',
    //: `JV18`：展開中的「已計算」明細是哪一筆（`tabItems()` 的索引），
    //: `-1` = 都沒展開。⚠️ 用索引不用布林——同時只能展開一筆，展開下一筆
    //: 要先把上一筆收起來，不然清單會越展越長。
    usedInfoOpen: -1,
    //: `JV21`：支出項頁籤裡展開中的品項／人員明細是哪一筆，`-1` = 都沒展開。
    //: 同 `usedInfoOpen` 的理由，各自獨立（切頁籤時兩個都重置，見 `pickTab()`）。
    expandedExpense: -1,

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
      await this.loadList()
      await this.loadSources()
      // 深連結：`voucher.html?id=12` 直接開那一張。
      const m = /[?&]id=(\d+)/.exec(window.location.search || '')
      if (m) await this.open(Number(m[1]))
    },

    // ── 摘要來源 ────────────────────────────────────────────────────

    async loadSources() {
      // ⚙️ **只在載入時拿一次** —— 切頁籤不重新打，也不重新帶入。
      try {
        const q = this.sourceQuote
          ? '?quote_no=' + encodeURIComponent(this.sourceQuote) : ''
        const r = await fetch('/api/vouchers/summary-sources' + q,
                              { headers: this._auth() })
        if (!r.ok) throw new Error('HTTP ' + r.status)
        const d = await r.json()
        this.sources = d.tabs || {}
        this.sourceNotes = d.notes || {}
        this.sourcesLoaded = true
      } catch (e) {
        this.sourceErr = '摘要來源載入失敗（' + e.message + '）。摘要仍然可以手動填寫。'
      }
    },

    tabNames() { return Object.keys(this.sources || {}) },

    tabItems() { return (this.sources || {})[this.sourceTab] || [] },

    tabNote() { return (this.sourceNotes || {})[this.sourceTab] || '' },

    // `JV18`：使用者原話「計算過的內容須…」= 已被別張傳票帶入過。
    // 只標記，不擋——已計算的候選一樣按得下去（後端也沒有加新的拒絕，
    // 同一條規則：擋住會把作廢重開那條合法路踩死）。
    // ⚠️ 紅字要**點得開**，不做成 tooltip（手機版是另一份頁面，會漏掉）。
    toggleUsedInfo(si) {
      this.usedInfoOpen = (this.usedInfoOpen === si) ? -1 : si
    },

    // `JV21`：支出項頁籤裡，承攬商派工那一筆展開成品項／人員兩種子列
    // （額外支出沒有子列，`items` 是空陣列，展不開）。
    // 同一套「用索引記哪一筆展開」的做法，理由同 `toggleUsedInfo()`：
    // 同時只能展開一筆，展開下一筆前先把上一筆收起來。
    toggleExpenseExpand(si) {
      this.expandedExpense = (this.expandedExpense === si) ? -1 : si
    },

    // `usedAt`／`uploaded_at` 是 ISO 字串，這裡只取到分鐘，不需要秒。
    fmtDateTime(s) {
      return String(s || '').replace('T', ' ').slice(0, 16)
    },

    // 🔴 **只換頁籤，什麼都不寫回分錄。**
    //    ☠️ 在這裡順手帶入的話，使用者切走再切回來，**他打的字會被蓋掉**，
    //       而畫面上一切正常 —— 他只會覺得「我剛剛好像打過」。
    pickTab(name) {
      this.sourceTab = name
      this.usedInfoOpen = -1
      this.expandedExpense = -1
    },

    //: 帶入到 `summaryTarget` 那一行。**唯一會寫進 `l.summary` 的地方。**
    applySource(it) {
      if (!this.canEdit) return
      const s = (it && (it.summary || it.text)) || ''
      if (!s) return
      let i = this.summaryTarget
      if (!this.lines[i]) { this.addLine(); i = this.lines.length - 1 }
      // ⚠️ 覆蓋那一行的摘要 —— 而**只有使用者點了來源才會走到這裡**。
      this.lines[i].summary = s
      // 🔑 順手記下是哪一個案件，頁籤②（可帶入的憑證）才有範圍。
      //    ⚠️ 重新拿來源**不會**再寫一次摘要：`loadSources()` 只換資料，
      //       寫進 `l.summary` 的**只有這一支**。
      if (it && it.quote_no && it.quote_no !== this.sourceQuote) {
        this.sourceQuote = it.quote_no
        this.loadSources()
      }
    },

    focusLine(i) { this.summaryTarget = i },

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
      const r = await fetch(
        '/api/vouchers/' + this.id + '/attachments/' + encodeURIComponent(a.file_id),
        { headers: this._auth() })
      if (!r.ok) throw new Error('HTTP ' + r.status)
      return new Blob([await r.arrayBuffer()], { type: type })
    },

    // 預覽 modal 的狀態。`url` 只在 image／pdf 時才有；關閉或切換時 revoke。
    attPv: { open: false, idx: -1, kind: '', url: '', err: '', loading: false },

    openAttachment(a) {
      // `JV16` 那份清單（預覽窗內）與編輯頁清單**共用同一個頁內預覽窗**，不再 window.open。
      return this.openAttPreview(a)
    },

    async openAttPreview(a) {
      const idx = this.attachments.indexOf(a)
      if (idx < 0) return
      this.attPv.open = true
      await this._loadAttPv(idx)
    },

    _revokeAttPv() {
      if (this.attPv.url) URL.revokeObjectURL(this.attPv.url)
      this.attPv.url = ''
    },

    async _loadAttPv(idx) {
      this._revokeAttPv()
      const a = this.attachments[idx]
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

    attPvItem() { return this.attachments[this.attPv.idx] || null },

    stepAttPv(d) {
      const n = this.attachments.length
      if (!n) return
      return this._loadAttPv((this.attPv.idx + d + n) % n)
    },

    closeAttPv() {
      this._revokeAttPv()
      this.attPv.open = false
      this.attPv.idx = -1
      this.attPv.kind = ''
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
        }
      })
      this.lines = ls.length ? ls : [{ account_code: '', account_name: '', summary: '', debit: '', credit: '' }]
      // 🔴 三格印的是**人名**，不是 token。
      //    後端 `signatures_of()` 回 `{格名: {by, at}}`，而 `by` 是 `username`
      //    —— 2026-09-23 修過一次：舊碼存的是 `_tok(auth)` 的**原始 bearer token**，
      //    而這一格會把那串 64 字元印在「製票」上。
      const s = d.signatures || {}
      this.signs = Object.keys(s).map(function (k) { return { label: k, by: (s[k] || {}).by || '' } })
      this.attachments = d.attachments || []
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
                  attachment: '附件', status: '狀態', voucher_no: '單號', lines: '分錄' }
      if (m[f]) return m[f]
      const mm = /^lines\[(\d+)\](?:\.(\w+))?$/.exec(f || '')
      if (mm) {
        const col = { account_code: '科目', summary: '摘要', debit: '借方', credit: '貸方' }[mm[2]] || ''
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

    voidIt() {
      // 🔑 沒有理由的作廢等於沒有留痕：事後沒有人回得出為什麼（後端直接回 400）。
      return this._act('/void', { reason: this.reason },
        function () { return '已作廢。原單仍留在系統裡，可在清單勾選「含已作廢」查看。' })
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
      this.lines.push({ account_code: '', account_name: '', summary: '', debit: '', credit: '' })
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
      try {
        const r = await fetch('/api/account-items', { headers: this._auth() })
        if (!r.ok) return
        const d = await r.json()
        const hit = this._find(d.tree || [], code)
        if (hit) this.lines[i].account_name = hit.name
      } catch (e) { /* 帶不出來就讓使用者自己填 */ }
    },

    _find(nodes, code) {
      for (const n of nodes) {
        if (n.code === code) return n
        const r = this._find(n.children || [], code)
        if (r) return r
      }
      return null
    },

    // 🔑 合計在前端即時算，**而它只是顯示** ——
    //    能不能過帳由後端 `check_balance()` 決定（A 明著交代）。
    //    ☠️ 前端自己判的話就是第二份判準，而它會在某天與後端不一致 ⇒
    //       使用者看到「畫面說可以，按下去被拒絕」。
    // `JV29`：與 `helpers/voucher.py::CATEGORY_TITLES` 同一組名稱。
    // 還沒存過的新單沒有判斷結果 ⇒ 說清楚什麼時候會有，不要先印一個「轉帳傳票」。
    get kindTitle() {
      if (!this.id) return '（存檔後依分錄判斷）'
      return { '收': '收入傳票', '支': '支出傳票', '轉': '轉帳傳票' }[this.category] || '傳票'
    },

    get totalDebit() { return this.lines.reduce((s, l) => s + this._amt(l.debit), 0) },
    get totalCredit() { return this.lines.reduce((s, l) => s + this._amt(l.credit), 0) },

    fmt(n) {
      if (n === undefined || n === null) return ''
      return Math.round(n).toLocaleString()
    },

    shortDate(s) { return (s || '').slice(0, 10) },
  }
}
