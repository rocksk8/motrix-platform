// 獎金分潤（`FN2`）。
//
// 🔴 可見性由**後端**決定，這裡不做任何過濾。
//    `§七`：管理者看全部／本人只看自己那一列／其他人看不到。
//    ☠️ 前端過濾是假的：值仍然在 API 回應裡，打開開發者工具就看得到
//       **全公司每個人領多少**。
//    ⇒ 這一支只負責「把後端給的東西畫出來」，而 `isManager` 也是後端說的。
//
// 🔴 **兩級權限，兩道不同的閘**（`SPEC-BN1-PLAN §2`）
//
//    POST /api/bonus/items   require_superadmin=True   <= **只有 superadmin**
//    POST /api/bonus/awards  _is_manager               <= superadmin ＋ admin
//
//    ☠️ 用 `isManager` 擋「新增項目」入口的後果：`admin` 看得到按鈕、
//       按下去收到 **403** —— 而這個模組已經確立「按下去之前就該知道答案」。
//    ⚠️ 而兩個旗標都**來自後端**，這一支不自己判 `role`：
//       抄一份 `require_superadmin` 到 JS 就是**規則有兩份**。

//: `PERSON_SOURCES` 的中文標示。
//: ⚠️ 查不到就**原樣顯示那個值**，不要顯示空白 ——
//:    後端加了新來源而這裡忘了補標示時，畫面會露出一個看得懂的線索，
//:    而空白會被當成「這個項目壞了」。
var BN_SOURCE_LABEL = {
  'sales_person': '業務（案件負責業務）',
  'case_stages.assigned_to': '各執行階段負責人',
  'group': '群組（後勤等複數人員）',
}

function bonusPage() {
  return {
    loaded: false,
    loadError: '',
    awards: [],
    //: `BONUS_MODULE_ENABLED`（`SPEC-BN21.md`）：獎金池算法目前會算錯錢
    //: （三組各自獨立算比例，沒有加總檢查），出貨暫停使用。`init()` 第一件
    //: 事就問後端，關著的話**不載入任何資料**——不是「載入了但擋著看」，
    //: 是根本不打那些會回 403／算錯數字的端點。
    moduleDisabled: false,
    //: **看得到別人那幾列嗎**（後端 `GET /awards` 的 `is_manager`
    //: ＝ `role === 'superadmin'`，`BN9` 之後不含 `admin`）。
    isManager: false,
    //: **按得到「產生獎金分潤單」嗎**（後端的 `can_create_award`
    //: ＝ superadmin 或 admin）。
    //: 🔴 與 `isManager` 分開，因為 `admin` 這兩格答案**不一樣**：
    //:    他產生得了獎金分潤單，而他看不到別人領多少。
    //: ☠️ 用 `isManager` 擋入口的話，`admin` 會看不到一個他按得動的按鈕
    //:    —— 而那是一個沒有人要求的權限變更（反過來就是 `bonus.html:158`
    //:    那一條：看得到按鈕、按下去收 403）。
    canCreateAward: false,

    // ── `BN16`：獎金分潤單狀態篩選 ──
    //: 'all' ／ 'draft' ／ 'pending'（送審中：待審核＋簽核中）／
    //: 'approved_unpaid'（已核准・未撥付）／ 'paid'。
    awardFilter: 'all',
    //: 「顯示已作廢」——沿用既有 `GET /awards?include_voided=` 的資料，
    //: 這裡純粹是前端要不要把已作廢的列進可見集合，不重新打 API。
    includeVoided: false,

    // ── 獎金項目（`SPEC-BN1-PLAN §2`）──
    items: [],
    itemsLoaded: false,
    personSources: [],
    newItem: { name: '', person_source: '', person_source_ref: null },
    itemMsg: '',
    itemErr: '',
    savingItem: false,

    // ── `BN14`：獎金模組自己建的群組（例：後勤單位）──
    //: 閘門與獎金項目同一道（後端 require_superadmin），畫面上也共用
    //: 同一個 `isManager` 判斷，不在這裡另外判 role。
    groups: [],
    groupsLoaded: false,
    groupErr: '',
    groupMsg: '',
    newGroupName: '',
    savingGroup: false,
    //: 每個群組自己的「加成員」輸入框，用 group id 當 key——
    //: 共用一個字串的話，展開第二個群組會蓋掉第一個正在打的字。
    newMemberInput: {},
    savingMember: {},

    // ── `BN18`：產生獎金分潤單時手動指定人員 ──
    //: 使用者原話「產生獎金單時能手動指定人」——`case_stages.assigned_to`
    //: 今天 100% 是空的，這條路是目前唯一走得通的方式（見規格 §5b）。
    //: 挑人**只能從清單選**（`§3` 硬性要求），不是打字輸入。
    allUsers: [],
    allUsersLoaded: false,
    //: 能不能在本頁新增獎金項目。**來自後端**（`GET /items` 的 `can_edit`
    //: ＝ `role === 'superadmin'`），不是在這裡判 `role` 算出來的。
    //: 📌 名字不照抄 `can_edit`：那個名字說不出「edit 什麼」，
    //:    而這一頁同時還有「產生獎金分潤單」那一種寫入。
    canManageItems: false,

    // ── 案件下拉（`BN5`）──
    //: `GET /awards/candidates` 給的候選清單，每筆 `{quote_no,
    //: customer_name, project_name, netProfit, selectable, reason}`。
    //: ⚠️ 淨利<=0／精算舊格式／已有有效獎金分潤單的案件**都在裡面**，不是
    //: 只有可選的——後端不濾，這裡也不濾，只是 `<option disabled>`。
    candidates: [],
    candidatesLoaded: false,
    candidatesErr: '',

    // ── 產生獎金分潤單（`BN1`）──
    planQuote: '',
    plan: null,
    planErr: '',
    planning: false,
    creating: false,
    createMsg: '',
    createErr: '',
    //: `{ bonus_item_id: { use, total, people: { username: pct } } }`
    //: ☠️ 這裡面的單位全部是**百分比**，送出前才換成基點。
    alloc: {},

    _token() {
      // ⚠️ token 存在 `motrix_session` 這個 JSON 裡，不是一個同名的獨立鍵。
      //    （2026-09-23 踩過一次：拿錯會靜默回 null ⇒ 401 ⇒ 整頁空白。）
      try {
        return (JSON.parse(localStorage.getItem('motrix_session') || '{}').token) || ''
      } catch (e) { return '' }
    },

    _auth() { return { Authorization: 'Bearer ' + this._token() } },

    _jsonAuth() {
      return { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() }
    },

    // 🔴 Alpine 3 看到資料物件有 init() 就會**自己叫一次**，
    //    而 body 上那個明著呼叫初始化的屬性會再叫一次 ⇒ **跑兩遍**。
    // ☠️ 後果不只是 API 發兩次：第二次的回應晚一步抵達，
    //    會把使用者這段期間改過的欄位用伺服器上的舊值**無聲蓋回去**。
    _initDone: false,

    async init() {
      if (this._initDone) return
      this._initDone = true
      try {
        const r = await fetch('/api/system/bonus-module-status', { headers: this._auth() })
        const d = r.ok ? await r.json() : null
        if (d && !d.enabled) { this.moduleDisabled = true; this.loaded = true; return }
      } catch (e) { /* 查不到就照常載入——不要因為這支旗標打不到而把整個模組擋掉 */ }
      await this.loadAwards()
      // 🔴 `BN2`：`GET /items` 現在只有最高管理者讀得到 ⇒ 不是管理者就**不要打**。
      //    ⚠️ 而判斷用**後端回的 `is_manager`**（`loadAwards()` 拿到的），
      //       不是在這裡判 `role` —— 那會是規則的第二份。
      //    📌 而還是有可能拿到 403（`is_manager` 與 `require_superadmin` 是
      //       兩道閘，`BN9` 之前 admin 兩者不一致）⇒ 錯誤訊息要說得出是權限，
      //       而且它**放在區塊外**（見 `bonus.html` 那一段）。
      // `BN14`：群組管理與獎金項目**同一道閘**（`isManager`）——
      // 動線是「先有群組才能在項目上選它」，所以群組要在項目之前載入
      // （順序不影響畫面，但語意上這裡先寫）。
      if (this.isManager) await this.loadGroups()
      if (this.isManager) await this.loadItems()
      // `BN5`：候選清單與「產生獎金分潤單」同一道閘（canCreateAward =
      // _is_manager），不是 isManager——admin 按得到「產生」，
      // 他也要看得到下拉可以選什麼。
      if (this.canCreateAward) await this.loadCandidates()
      // `BN18`：手動指定的挑人清單，同一道閘（會用到這份清單的按鈕
      // 也是 canCreateAward 那一批人）。
      if (this.canCreateAward) await this.loadUsers()
    },

    async loadUsers() {
      try {
        const r = await fetch('/api/users', { headers: this._auth() })
        if (!r.ok) throw new Error('HTTP ' + r.status)
        const d = await r.json()
        // 只給挑得到的人——已停用的帳號不該出現在清單裡讓人誤選
        // （後端 `_validate_manual_people()` 也會擋，這裡先幫忙濾掉，
        // 兩層各自的道理見〈不可以只在前端擋〉那條規則：這層是體驗，
        // 後端那層才是真正擋住的）。
        this.allUsers = (d || []).filter(function (u) { return u.active })
        this.allUsersLoaded = true
      } catch (e) {
        // 挑人清單載入失敗不擋整頁——只是手動指定這個功能用不了，
        // 其餘照常的來源仍然可以用。
      }
    },

    async loadCandidates() {
      try {
        const r = await fetch('/api/bonus/awards/candidates', { headers: this._auth() })
        if (r.status === 403) {
          // 🔴 「沒有可選的案件」與「你沒有權限」不可以合成一句——
          //    合成的話，沒有權限的人會去找案件，而問題不在那裡。
          this.candidatesErr = '您沒有產生獎金分潤單的權限。'
          return
        }
        if (!r.ok) throw new Error('HTTP ' + r.status)
        const d = await r.json()
        this.candidates = d.items || []
        this.candidatesLoaded = true
      } catch (e) {
        this.candidatesErr = '案件清單載入失敗（' + e.message + '）。請重新整理，若持續發生請回報。'
      }
    },

    async loadAwards() {
      try {
        // `BN16`：一律帶 `include_voided=1` 拿到**完整集合**——「顯示已
        // 作廢」核取方塊與四個狀態頁籤都在前端對同一份 `this.awards`
        // 過濾，不因為勾選而重新打 API。這樣「作廢單是不是被藏起來了」
        // 這件事前端永遠算得出來（§6 的空狀態措辭需要這個前提），也讓
        // 「計數不可以有自己的資料來源」（§5）在結構上更難被破壞——
        // 連「換一個查詢參數重打」都不會發生。
        const r = await fetch('/api/bonus/awards?include_voided=1', { headers: this._auth() })
        if (r.status === 403) {
          this.loadError = '您沒有檢視獎金分潤的權限。若需要存取，請聯絡系統管理員。'
          return
        }
        if (!r.ok) throw new Error('HTTP ' + r.status)
        const d = await r.json()
        this.awards = d.awards || []
        this.isManager = !!d.is_manager
        this.canCreateAward = !!d.can_create_award
        this.loaded = true
      } catch (e) {
        // 🔑 說出是哪一支壞了：使用者回報時那句話是唯一的線索。
        this.loadError = '獎金資料載入失敗（' + e.message + '）。請重新整理，若持續發生請回報。'
      }
    },

    // ── `BN16`：獎金分潤單狀態篩選 ───────────────────────────────────
    //
    // 使用者原話：「獎金單可區分草稿、送審中、已審核、未撥付、已撥付
    // 多種狀態，可切換顯示」。使用者另裁：「已審核」＝已核准且未撥付
    // ——那是他的待辦清單（該付錢的那幾張），不是單純的狀態顯示。
    //
    // 🔴 「送審中」是**集合的名字**，不是第五個 status 值——待審核／
    // 簽核中兩個字串在列上仍然逐字顯示，不發明新詞（`§2`）。

    // 三個維度：簽核狀態、撥付、是否作廢——後兩者都是**推導**，不是
    // 新欄位，跟 `isAwardPaid()` 同一條規則（讀既有欄位，不猜）。
    awardCategory(a) {
      if (a.status === '草稿') return 'draft'
      if (a.status === '待審核' || a.status === '簽核中') return 'pending'
      if (a.status === '已核准' && !this.isAwardPaid(a)) return 'approved_unpaid'
      if (this.isAwardPaid(a)) return 'paid'
      return ''
    },

    // `§7①`：作廢是第三個維度，併進頁籤（交集）不是獨立一區——一張
    // 已核准後作廢的單，仍然出現在「已核准・未撥付」裡，靠列上明著
    // 標「已作廢」分辨（不能只靠灰色／刪除線，那些在列印、截圖、色弱
    // 時全部失效——`bonus.html` 的 `.bn-voided` 已經是逐字顯示）。
    filteredAwards() {
      const byVoid = (this.awards || []).filter(
        function (a) { return this.includeVoided || !a.voided_at }.bind(this))
      if (this.awardFilter === 'all') return byVoid
      const cat = this.awardFilter
      return byVoid.filter(function (a) { return this.awardCategory(a) === cat }.bind(this))
    },

    // `§5`：計數與列表用**同一個** `this.awards` 陣列算，不另打 API——
    // 那讓「數字與列出來的筆數不一致」在結構上不可能發生。
    // ⚠️ 計數跟著「顯示已作廢」那個核取方塊走（與 `filteredAwards()`
    // 同一份可見集合），不是永遠算全部。
    awardCounts() {
      const byVoid = (this.awards || []).filter(
        function (a) { return this.includeVoided || !a.voided_at }.bind(this))
      const c = { draft: 0, pending: 0, approved_unpaid: 0, paid: 0 }
      for (const a of byVoid) {
        const cat = this.awardCategory(a)
        if (cat in c) c[cat]++
      }
      return c
    },

    // `§6`：空狀態的三種原因，只說得出前兩種——第三種（非管理者看不到
    // 別人的單）**不可以講**，那個數字本身就是資訊（`BN9` 要擋的東西）。
    // 這裡完全不去猜「外面是不是還有」，只回答「我手上這份資料看不看
    // 得到東西」，第三種原因因此自然地不會被講出來，不必特別排除。
    awardEmptyMessage() {
      if (this.awardFilter === 'all') {
        if ((this.awards || []).length) return ''
        return this.isManager
          ? '目前還沒有任何獎金分潤單。獎金分潤單依案件產生，案件需要先完成精算。'
          : '目前沒有發放給您的獎金。'
      }
      const label = { draft: '草稿', pending: '送審中',
                     approved_unpaid: '已核准・未撥付', paid: '已撥付' }[this.awardFilter] || ''
      const inCategory = (this.awards || []).filter(
        function (a) { return this.awardCategory(a) === this.awardFilter }.bind(this))
      if (!inCategory.length) return '目前沒有' + label + '狀態的獎金分潤單。'
      const visible = inCategory.filter(
        function (a) { return this.includeVoided || !a.voided_at }.bind(this))
      if (!visible.length) {
        return '目前沒有' + label + '狀態的獎金分潤單。（已作廢的單未顯示，可勾選上方切換）'
      }
      return ''
    },

    // ── `BN14`：群組 ─────────────────────────────────────────────

    async loadGroups() {
      try {
        const r = await fetch('/api/bonus/groups', { headers: this._auth() })
        if (!r.ok) throw new Error('HTTP ' + r.status)
        const d = await r.json()
        this.groups = d.groups || []
        this.groupsLoaded = true
      } catch (e) {
        this.groupErr = '群組載入失敗（' + e.message + '）。請重新整理，若持續發生請回報。'
      }
    },

    // 建新項目的下拉**只給啟用中的群組**（`§7②`）——維護區塊本身
    // 仍然列出全部（含已停用），要看到它才能重新啟用。
    activeGroups() {
      return (this.groups || []).filter(function (g) { return g.is_active })
    },

    async createGroup() {
      this.groupMsg = ''
      this.groupErr = ''
      const name = (this.newGroupName || '').trim()
      if (!name || this.savingGroup) return
      this.savingGroup = true
      try {
        const r = await fetch('/api/bonus/groups', {
          method: 'POST',
          headers: this._jsonAuth(),
          body: JSON.stringify({ name: name }),
        })
        const d = await r.json().catch(function () { return {} })
        if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status))
        this.newGroupName = ''
        this.groupMsg = '已新增群組「' + name + '」。'
        await this.loadGroups()
      } catch (e) {
        this.groupErr = e.message
      } finally {
        this.savingGroup = false
      }
    },

    async toggleGroupActive(g) {
      this.groupErr = ''
      try {
        const r = await fetch('/api/bonus/groups/' + g.id + '/active', {
          method: 'PATCH',
          headers: this._jsonAuth(),
          body: JSON.stringify({ is_active: !g.is_active }),
        })
        if (!r.ok) {
          const d = await r.json().catch(function () { return {} })
          throw new Error(d.detail || ('HTTP ' + r.status))
        }
        await this.loadGroups()
      } catch (e) {
        this.groupErr = e.message
      }
    },

    async addGroupMember(g) {
      this.groupErr = ''
      const username = (this.newMemberInput[g.id] || '').trim()
      if (!username) return
      this.savingMember = Object.assign({}, this.savingMember, { [g.id]: true })
      try {
        const r = await fetch('/api/bonus/groups/' + g.id + '/members', {
          method: 'POST',
          headers: this._jsonAuth(),
          body: JSON.stringify({ username: username }),
        })
        const d = await r.json().catch(function () { return {} })
        if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status))
        this.newMemberInput = Object.assign({}, this.newMemberInput, { [g.id]: '' })
        await this.loadGroups()
      } catch (e) {
        this.groupErr = e.message
      } finally {
        this.savingMember = Object.assign({}, this.savingMember, { [g.id]: false })
      }
    },

    async removeGroupMember(g, username) {
      this.groupErr = ''
      try {
        const r = await fetch(
          '/api/bonus/groups/' + g.id + '/members/' + encodeURIComponent(username),
          { method: 'DELETE', headers: this._auth() })
        if (!r.ok) {
          const d = await r.json().catch(function () { return {} })
          throw new Error(d.detail || ('HTTP ' + r.status))
        }
        await this.loadGroups()
      } catch (e) {
        this.groupErr = e.message
      }
    },

    // ── 獎金項目 ──────────────────────────────────────────────────

    async loadItems() {
      try {
        const r = await fetch('/api/bonus/items', { headers: this._auth() })
        if (!r.ok) throw new Error('HTTP ' + r.status)
        const d = await r.json()
        this.items = d.items || []
        this.personSources = d.person_sources || []
        this.canManageItems = !!d.can_edit
        this.itemsLoaded = true
      } catch (e) {
        // 🔑 403 要說得出是**權限**，不要混進「載入失敗」那一句 ——
        //    ☠️ 「載入失敗，請重新整理」會讓一個沒有權限的人**一直重新整理**。
        this.itemErr = (String(e.message).indexOf('403') >= 0)
          ? '獎金項目只有最高管理員看得到。您仍然可以在下方看到與自己有關的獎金分潤單。'
          : '獎金項目載入失敗（' + e.message + '）。請重新整理，若持續發生請回報。'
      }
    },

    srcLabel(v) { return BN_SOURCE_LABEL[v] || v },

    activeItems() {
      // 停用的項目不給選 —— 與 `create_award` 的 `WHERE is_active = 1` 同一條。
      // ☠️ 不同的話：畫面列出已停用的項目 -> 填完比例 -> 按下去收到 400
      //    ⇒ 「先問再做」失效的具體形狀：**問過了，而答案是錯的**。
      return (this.items || []).filter(function (i) { return i.is_active })
    },

    async createItem() {
      this.itemMsg = ''
      this.itemErr = ''
      if (this.savingItem) return
      this.savingItem = true
      try {
        const r = await fetch('/api/bonus/items', {
          method: 'POST',
          headers: this._jsonAuth(),
          body: JSON.stringify(this.newItem),
        })
        const d = await r.json().catch(function () { return {} })
        if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status))
        this.newItem = { name: '', person_source: '', person_source_ref: null }
        this.itemMsg = '已新增獎金項目。'
        await this.loadItems()
      } catch (e) {
        // 📌 錯誤訊息**直接用後端回的那句**：規則只有一份，文案也只有一份。
        this.itemErr = e.message
      } finally {
        this.savingItem = false
      }
    },

    // ── 產生獎金分潤單 ────────────────────────────────────────────────
    //
    // 🔴 **人員名單由後端決定，這一支不自己組。**
    //    `POST /awards` 要 `allocations[].person_pct = { username: pct }`，
    //    而那些 username 由 `people_for_item()` 決定。資料前端其實拿得到
    //    （案件 API 有 `assignedTo`）⇒ **做得到自己算**。而那是把同一條規則
    //    抄到第二個地方：
    //      `helpers/bonus.py` 已標「已知的未來來源 quotations.assigned_user_ids」
    //      ⇒ 加它的那天：後端改、這支 JS 不會跟
    //      ⇒ 症狀是**少發一個人，而總額對得起來**
    //    ☠️ 對不起來還有人會查，**對得起來沒有人會查**。
    //    ⇒ 一律打 `GET /api/bonus/awards/plan/{quote_no}` 拿 `people`。

    toBp(v) {
      // 百分比 -> 基點（1/10000）。⚠️ **換算只有這一處。**
      // ☠️ 50% 要送 5000。送 50 的話獎金變成應得的 1/100，
      //    **而畫面上它是一個格式正確的金額** ⇒ 沒有人會把它看成錯誤。
      var n = Number(v)
      if (!isFinite(n)) return 0
      return Math.round(n * 100)
    },

    // `SPEC-BN6-BN7.md §2`：預覽結果（`POST /awards/plan/{quote_no}`），
    // 送出的分配與 `POST /awards` 完全相同，差別只有有沒有寫進資料庫。
    previewResult: null,
    previewErr: '',
    previewing: false,

    // ── `BN10`／`BN12`：獎金分潤單詳情——一個 modal，兩種資料來源 ──────
    // 使用者原話：「獎金單要跟報價單的頁面一樣……點選後可載入完整資料跟
    // 明細」「送出前後都要能看到完整明細」「一多就會亂」。
    // `detailMode`：'' 沒開／'plan' 產生階段（用 this.plan）／'award'
    // 已存在的單（用 this.awardDetail，GET /awards/{id} 來的）。
    detailMode: '',
    awardDetail: null,
    awardDetailErr: '',
    awardDetailLoading: false,

    // `settle` getter 依 `detailMode` 切換讀哪一份 settlement——**版面
    // 只有一份**（`.bn-settle` 在頁面上只出現一次），兩種模式共用它。
    // 🔴 `.bn-settle` 的子節點用 `x-show` 蓋在外層 div 上——`x-show` 只是
    //    `display:none`，元素仍然在 DOM 裡，Alpine 每個 tick 照樣求值裡面
    //    每一個 `x-text`（同 `test_ac1_write_actions` 那條「x-show 不等於
    //    x-if」的道理）。來源剛被設回 `null` 那一瞬間，裡面的
    //    `x-text="fmt(settle.quotedPretax)"` 若讀到 `null.quotedPretax`
    //    會直接炸掉——實際用 Playwright 跑過一次抓到的（`pageerror`：
    //    `Cannot read properties of null (reading 'settlement')`）。
    //    ⇒ 這支一律回一個物件（沒有值時是 `{}`），`fmt(undefined)` 本來
    //    就印「—」，順便滿足「缺欄位印—」那條規則，不必另外判斷。
    get settle() {
      if (this.detailMode === 'award') {
        return (this.awardDetail && this.awardDetail.settlement) || {}
      }
      return (this.plan && this.plan.settlement) || {}
    },

    closeDetail() {
      this.detailMode = ''
      this.awardDetail = null
      this.awardDetailErr = ''
      this.askAwardReason = ''
    },

    async openAwardDetail(awardId) {
      this.detailMode = 'award'
      this.awardDetail = null
      this.awardDetailErr = ''
      this.awardDetailLoading = true
      try {
        const r = await fetch('/api/bonus/awards/' + awardId, { headers: this._auth() })
        const d = await r.json().catch(function () { return {} })
        if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status))
        this.awardDetail = d
      } catch (e) {
        this.awardDetailErr = '獎金分潤單明細載入失敗（' + e.message + '）。'
      } finally {
        this.awardDetailLoading = false
      }
    },

    // `BN12ⓐ`：「送出前後都要能看到完整明細」——查詢一成功就直接開這個
    // modal，不必再多按一次「查看」；`§6⑩` 的「預覽」按鈕仍然保留（在
    // modal 裡），因為 modal 打開時看到的是**輸入表單**（勾選項目、填
    // 比例），「預覽」按下去才是**試算結果**，兩者不是同一件事。
    async loadPlan() {
      this.planErr = ''
      this.createMsg = ''
      this.createErr = ''
      this.plan = null
      this.alloc = {}
      // 換案件（或重新查詢同一案）時，舊的試算結果不再對得上新的畫面，
      // 不清掉的話使用者會以為那個數字是這個案件現在的預覽。
      this.previewResult = null
      this.previewErr = ''
      const q = (this.planQuote || '').trim()
      if (!q) { this.planErr = '請先輸入案件編號。'; return }
      if (this.planning) return
      this.planning = true
      try {
        const r = await fetch('/api/bonus/awards/plan/' + encodeURIComponent(q), {
          headers: this._auth(),
        })
        const d = await r.json().catch(function () { return {} })
        if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status))
        // 🔴 **先把 alloc 建好，最後才指定 plan。**
        //    ☠️ 反過來的話，`plan` 一設定 Alpine 就立刻重繪那個 x-for，
        //       而此時 `alloc` 還是空的 ⇒ `alloc[it.bonus_item_id].use`
        //       會丟 TypeError ⇒ **整個區塊消失，而主控台以外什麼都看不到**。
        //    🔑 〈先渲染再非同步載入＝競態〉的同一族：
        //       畫面能不能渲染，取決於兩個狀態誰先落地。
        const a = {}
        for (const it of d.items || []) {
          const people = {}
          // ⚙️ 預設平分：n 個人各 `(100/n)%`。
          //    ⚠️ 這只是預設值 —— 送出去的是使用者**看到的那些數字**。
          const n = (it.people || []).length
          for (const p of it.people || []) {
            people[p] = n ? Number((100 / n).toFixed(2)) : 0
          }
          // `BN18`：override 預設關——沒有明著打開的話一律走正常解析，
          // 不是「有沒有填 people」決定要不要覆寫（同後端那條規則）。
          a[it.bonus_item_id] = {
            use: false, total: '', people: people,
            override: false, manualPeople: {},
          }
        }
        this.alloc = a
        this.plan = d
        this.detailMode = 'plan'
      } catch (e) {
        this.planErr = e.message
      } finally {
        this.planning = false
      }
    },

    personSum(itemId) {
      const a = this.alloc[itemId]
      if (!a) return 0
      let s = 0
      for (const k in a.people) s += Number(a.people[k]) || 0
      return Math.round(s * 100) / 100
    },

    chosen() {
      const out = []
      for (const it of (this.plan && this.plan.items) || []) {
        const a = this.alloc[it.bonus_item_id]
        // `BN18`：手動指定時不要求 `it.ok`——那正是這個功能要解決的情況
        // （案件沒有執行人，`people_for_item()` 本來就會回 `ok=false`）。
        if (a && a.use && (it.ok || a.override)) out.push(it)
      }
      return out
    },

    // `BN18`：手動挑人清單裡勾選／取消一個人——用索引不用布林陣列，
    // 同時維護 `manualPeople`（誰被勾選）與 `people`（他的比例），
    // 取消勾選要把比例一起清掉，不留一個看不到卻還在送出去的數字。
    toggleManualPerson(itemId, username) {
      const a = this.alloc[itemId]
      if (!a) return
      if (a.manualPeople[username]) {
        delete a.manualPeople[username]
        delete a.people[username]
      } else {
        a.manualPeople[username] = true
        if (a.people[username] === undefined) a.people[username] = 0
      }
    },

    // 送出前先講的那些。
    // ⚠️ **這裡擋住不等於後端不必擋** —— 前端過濾是假的，值仍然可以直接打 API。
    //    後端才是權威：`total_pct <= 10000`、`Σperson_pct <= 10000`、不可為負。
    //    這一層只是為了不要讓使用者填完才被拒絕。
    planIssue() {
      if (!this.plan) return ''
      if (this.plan.has_active_award) {
        return '這個案件已經有一張有效的獎金分潤單，若要重發請先作廢原本那一張。'
      }
      if (!this.plan.base || !this.plan.base.ok) {
        return (this.plan.base && this.plan.base.error) || '這個案件目前算不出獎金基數。'
      }
      const picked = this.chosen()
      if (!picked.length) return '請至少勾選一個獎金項目。'
      for (const it of picked) {
        const a = this.alloc[it.bonus_item_id]
        // `BN18`：手動指定時檢查勾選的人數，不是 `it.people`（那是正常
        // 解析出來的名單，覆寫時本來就可能是空的或不相關）。
        if (a.override && !Object.keys(a.manualPeople || {}).length) {
          return '「' + it.name + '」手動指定至少要選一個人。'
        }
        const t = Number(a.total)
        if (!(t > 0)) return '「' + it.name + '」的發放比例要大於 0。'
        if (t > 100) return '「' + it.name + '」的發放比例超過 100%，獎金池會大於案件淨利。'
        const s = this.personSum(it.bonus_item_id)
        if (!(s > 0)) return '「' + it.name + '」的人員比例全部是 0，無法發放。'
        if (s > 100) {
          return '「' + it.name + '」的人員比例合計 ' + s + '% 超過 100%，公司留存會變成負數。'
        }
      }
      return ''
    },

    // `POST /awards` 與 `POST /awards/plan/{quote_no}`（預覽）送的是
    // 同一個 body 形狀（`SPEC-BN6-BN7.md §2`）——兩支呼叫都從這裡組，
    // 不各寫一份：少了這個，「預覽跟實際不一樣」的風險就分散在兩處。
    _buildAllocations() {
      const allocations = []
      for (const it of this.chosen()) {
        const a = this.alloc[it.bonus_item_id]
        const person_pct = {}
        // `BN18`：明著宣告才送覆寫旗標——不是「有沒有填 people」決定，
        // 同後端那條規則（同一個判準，兩邊都要用旗標，不是真假值）。
        if (a.override) {
          const people = Object.keys(a.manualPeople || {})
          for (const p of people) person_pct[p] = this.toBp(a.people[p])
          allocations.push({
            bonus_item_id: it.bonus_item_id,
            total_pct: this.toBp(a.total),
            person_pct: person_pct,
            person_source_override: true,
            people: people,
          })
        } else {
          // 📌 只送 `plan` 回的那些人，不送畫面上殘留的任何名字。
          for (const p of it.people) person_pct[p] = this.toBp(a.people[p])
          allocations.push({
            bonus_item_id: it.bonus_item_id,
            total_pct: this.toBp(a.total),
            person_pct: person_pct,
          })
        }
      }
      return allocations
    },

    // `§6⑩`：獎金頁的「預覽」動作——只算不寫，回的 lines／remainder
    // 與之後真的按「產生獎金分潤單」寫進資料庫的值逐筆相等（後端同一支
    // `_plan_allocations()` 算，這裡不重複驗證，錯誤訊息就是後端那句）。
    async previewAward() {
      this.previewErr = ''
      const issue = this.planIssue()
      if (issue) { this.previewErr = issue; return }
      if (this.previewing) return
      this.previewing = true
      try {
        const r = await fetch(
          '/api/bonus/awards/plan/' + encodeURIComponent(this.plan.quote_no), {
            method: 'POST',
            headers: this._jsonAuth(),
            body: JSON.stringify({ allocations: this._buildAllocations() }),
          })
        const d = await r.json().catch(function () { return {} })
        if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status))
        this.previewResult = d
      } catch (e) {
        this.previewErr = e.message
        this.previewResult = null
      } finally {
        this.previewing = false
      }
    },

    async createAward() {
      this.createMsg = ''
      this.createErr = ''
      const issue = this.planIssue()
      if (issue) { this.createErr = issue; return }
      if (this.creating) return
      this.creating = true
      try {
        const r = await fetch('/api/bonus/awards', {
          method: 'POST',
          headers: this._jsonAuth(),
          body: JSON.stringify({
            quote_no: this.plan.quote_no,
            allocations: this._buildAllocations(),
          }),
        })
        const d = await r.json().catch(function () { return {} })
        if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status))
        this.createMsg = '已產生獎金分潤單（單號 #' + d.id + '，基數 ' + this.fmt(d.base_amount) + '）。'
        // 單已經真的產生了，舊的試算結果不再是「還沒送出的預覽」。
        this.previewResult = null
        await this.loadAwards()
        await this.loadPlan()
      } catch (e) {
        this.createErr = e.message
      } finally {
        this.creating = false
      }
    },

    // ── 顯示 ──────────────────────────────────────────────────────

    fmt(n) {
      // ⚠️ `undefined` 與 `0` 是兩件事：後端對非管理者**不回** base_amount，
      //    而把它印成 0 會讓人以為那個案件沒有賺錢。
      if (n === undefined || n === null) return '—'
      return 'NT$ ' + Math.round(n).toLocaleString()
    },

    pct(bp) {
      // 比例存的是**基點**（1/10000）。畫面顯示成百分比，而算術一律在後端用整數做。
      // ☠️ 前端自己拿百分比再乘一次的話，就會出現「畫面上的數字加起來不等於總額」。
      return ((Number(bp) || 0) / 100).toFixed(2).replace(/\.00$/, '') + '%'
    },

    // `BN17`：退回記錄的時間顯示，只取到分鐘（同 `voucher.js` 的
    // `fmtDateTime()`，這裡沒有共用模組所以各自一份——同一條格式化規則，
    // 不是重複的業務規則）。
    fmtDateTime(s) {
      return String(s || '').replace('T', ' ').slice(0, 16)
    },

    // `QS1-a §3③`：`bonus_award_lines.username`／`people_for_item()` 現在
    // 回帳號，畫面要印顯示名稱——後端已經查好給的 `display_names` map
    // （`plan`／`previewResult` 各自帶一份，不在前端自己查 users 清單去
    // 對照，那會變成第二份「帳號->顯示名」邏輯）。兩份都查一次，查不到
    // 落回帳號本身（同後端 `display_names_for()` 的規則）。
    displayNameOf(username) {
      const fromPreview = this.previewResult && this.previewResult.display_names
      const fromPlan = this.plan && this.plan.display_names
      return (fromPreview && fromPreview[username])
        || (fromPlan && fromPlan[username])
        || username
    },

    // `SPEC-BN6-BN7.md §6②`：精算明細裡的百分比欄位（毛利率／淨利率）
    // 缺欄位一樣要印「—」，不是 0——理由與 fmt() 相同。
    fmtPct(n) {
      if (n === undefined || n === null) return '—'
      return Number(n).toFixed(1) + '%'
    },

    // ── `BN8`：送審／簽核／退回／標記已發放 ────────────────────────
    //
    // 🔴 這四支全部**不在前端判可不可以做** —— 只依後端回的 `a.status`
    //    決定按鈕顯不顯示，而按下去能不能成立由後端說（同 voucher.js
    //    `_act()` 那段註解的道理，這裡搬過來用在**清單裡的每一張單**）。
    // ⚠️ 不用 `confirm()`：退回與標記已發放都要一段理由，原生對話框
    //    擋住整頁事件，改用行內輸入框（同 voucher.js）。
    awardBusy: '',
    awardMsg: {},
    awardErr: {},
    askAwardReason: '',   // `'reject:12'` 或 `'markpaid:12'`；`''` = 都沒開
    awardReasonText: '',

    openAwardReason(kind, id) {
      this.askAwardReason = kind + ':' + id
      this.awardReasonText = ''
      this.awardErr[id] = ''
    },

    cancelAwardReason() {
      this.askAwardReason = ''
      this.awardReasonText = ''
    },

    async _awardAct(id, path, body, okMsg) {
      if (this.awardBusy) return
      this.awardBusy = String(id)
      this.awardErr[id] = ''
      try {
        const r = await fetch('/api/bonus/awards/' + id + path, {
          method: 'POST',
          headers: this._jsonAuth(),
          body: JSON.stringify(body || {}),
        })
        const d = await r.json().catch(function () { return {} })
        if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status))
        this.awardMsg[id] = okMsg(d)
        this.askAwardReason = ''
        this.awardReasonText = ''
        await this.loadAwards()
        // `BN10`：若這張單的詳情正開著，動作完成後**就地更新**，不必
        // 使用者自己關掉再打開——否則簽核完的畫面還停在舊狀態，
        // 看起來像按了沒反應。
        if (this.detailMode === 'award' && this.awardDetail
            && String(this.awardDetail.id) === String(id)) {
          await this.openAwardDetail(id)
        }
      } catch (e) {
        this.awardErr[id] = e.message
      } finally {
        this.awardBusy = ''
      }
    },

    submitAward(id) {
      return this._awardAct(id, '/submit', {}, function () { return '已送審。' })
    },

    approveAward(id) {
      // ⚠️ 下一格是誰、簽完沒由後端算，這裡只把它回報的新狀態印出來。
      return this._awardAct(id, '/approve', {},
        function (d) { return '已簽核，目前狀態：' + d.status + '。' })
    },

    rejectAward(id) {
      return this._awardAct(id, '/reject', { reason: this.awardReasonText },
        function () { return '已退回草稿。' })
    },

    markAwardPaid(id) {
      return this._awardAct(id, '/mark-paid', { reason: this.awardReasonText },
        function () { return '已標記為發放。' })
    },

    // `SPEC-BN8.md §93③`：「已發放」是**推導**，不是新狀態——與後端
    // `helpers/bonus.py::is_paid()` 同一條，兩條路都算（自動回填傳票號
    // ／手動標記），這裡不重寫一次規則，只是把同一個判準搬到前端讀
    // `GET /awards` 已經给的那兩個欄位（兩者對所有人都可見，不是金額）。
    isAwardPaid(a) {
      return !!(String(a.voucher_no_payment || '').trim()
        || String(a.paid_manually_at || '').trim())
    },

    // `BN7`：匯出 PDF。後端 GET /pdf-download 已經做好用印欄動態長度
    // ／顯示名稱／抬頭／閘門（草稿．待審核．簽核中擋，已核准．已作廢放）
    // ——這裡只負責把 blob 存成檔案，不重覆判斷放不放行（按下去按不按得
    // 動由後端的 400 說了算，同 voucher.js::exportPdf() 的分工）。
    async downloadAwardPdf(a) {
      if (this.awardBusy) return
      const id = a.id
      this.awardBusy = String(id)
      this.awardErr[id] = ''
      try {
        const r = await fetch('/api/bonus/awards/' + id + '/pdf-download', {
          headers: this._auth(),
        })
        if (!r.ok) {
          let msg = 'HTTP ' + r.status
          try { msg = (await r.json()).detail || msg } catch (e) { /* 不是 JSON */ }
          throw new Error(msg)
        }
        const blob = await r.blob()
        const url = URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.download = 'bonus-award-' + (a.quote_no || id) + '.pdf'
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
        URL.revokeObjectURL(url)
      } catch (e) {
        this.awardErr[id] = '匯出失敗（' + e.message + '）。'
      } finally {
        this.awardBusy = ''
      }
    },

    // `§6⑪⑫`：印欄依鏈的層數畫，鏈讀不出來時印在紙上。
    // `a.signatures` 是後端 `bonus_signatures_of()` 算好的
    // `{格名: {by, at}}`，順序就是要畫的順序（製表在前，鏈讀不出來時
    // 只有「簽核資料無法讀取」一格）——這裡不重新排序、不重新判斷。
    signatureSlots(a) {
      const sig = a.signatures || {}
      return Object.keys(sig).map(function (label) {
        return { label: label, by: sig[label].by || '', at: sig[label].at || '' }
      })
    },
  }
}
