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
}

function bonusPage() {
  return {
    loaded: false,
    loadError: '',
    awards: [],
    isManager: false,

    // ── 獎金項目（`SPEC-BN1-PLAN §2`）──
    items: [],
    itemsLoaded: false,
    personSources: [],
    newItem: { name: '', person_source: '' },
    itemMsg: '',
    itemErr: '',
    savingItem: false,
    //: 能不能在本頁新增獎金項目。**來自後端**（`GET /items` 的 `can_edit`
    //: ＝ `role === 'superadmin'`），不是在這裡判 `role` 算出來的。
    //: 📌 名字不照抄 `can_edit`：那個名字說不出「edit 什麼」，
    //:    而這一頁同時還有「產生獎金單」那一種寫入。
    canManageItems: false,

    // ── 產生獎金單（`BN1`）──
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
      await this.loadAwards()
      // 🔴 `BN2`：`GET /items` 現在只有最高管理者讀得到 ⇒ 不是管理者就**不要打**。
      //    ⚠️ 而判斷用**後端回的 `is_manager`**（`loadAwards()` 拿到的），
      //       不是在這裡判 `role` —— 那會是規則的第二份。
      //    📌 而還是有可能拿到 403（`is_manager` 與 `require_superadmin` 是
      //       兩道閘，`BN9` 之前 admin 兩者不一致）⇒ 錯誤訊息要說得出是權限，
      //       而且它**放在區塊外**（見 `bonus.html` 那一段）。
      if (this.isManager) await this.loadItems()
    },

    async loadAwards() {
      try {
        const r = await fetch('/api/bonus/awards', { headers: this._auth() })
        if (r.status === 403) {
          this.loadError = '您沒有檢視獎金分潤的權限。若需要存取，請聯絡系統管理員。'
          return
        }
        if (!r.ok) throw new Error('HTTP ' + r.status)
        const d = await r.json()
        this.awards = d.awards || []
        this.isManager = !!d.is_manager
        this.loaded = true
      } catch (e) {
        // 🔑 說出是哪一支壞了：使用者回報時那句話是唯一的線索。
        this.loadError = '獎金資料載入失敗（' + e.message + '）。請重新整理，若持續發生請回報。'
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
          ? '獎金項目只有最高管理員看得到。您仍然可以在下方看到與自己有關的獎金單。'
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
        this.newItem = { name: '', person_source: '' }
        this.itemMsg = '已新增獎金項目。'
        await this.loadItems()
      } catch (e) {
        // 📌 錯誤訊息**直接用後端回的那句**：規則只有一份，文案也只有一份。
        this.itemErr = e.message
      } finally {
        this.savingItem = false
      }
    },

    // ── 產生獎金單 ────────────────────────────────────────────────
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

    async loadPlan() {
      this.planErr = ''
      this.createMsg = ''
      this.createErr = ''
      this.plan = null
      this.alloc = {}
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
          a[it.bonus_item_id] = { use: false, total: '', people: people }
        }
        this.alloc = a
        this.plan = d
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
        if (a && a.use && it.ok) out.push(it)
      }
      return out
    },

    // 送出前先講的那些。
    // ⚠️ **這裡擋住不等於後端不必擋** —— 前端過濾是假的，值仍然可以直接打 API。
    //    後端才是權威：`total_pct <= 10000`、`Σperson_pct <= 10000`、不可為負。
    //    這一層只是為了不要讓使用者填完才被拒絕。
    planIssue() {
      if (!this.plan) return ''
      if (this.plan.has_active_award) {
        return '這個案件已經有一張有效的獎金單，若要重發請先作廢原本那一張。'
      }
      if (!this.plan.base || !this.plan.base.ok) {
        return (this.plan.base && this.plan.base.error) || '這個案件目前算不出獎金基數。'
      }
      const picked = this.chosen()
      if (!picked.length) return '請至少勾選一個獎金項目。'
      for (const it of picked) {
        const a = this.alloc[it.bonus_item_id]
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

    async createAward() {
      this.createMsg = ''
      this.createErr = ''
      const issue = this.planIssue()
      if (issue) { this.createErr = issue; return }
      if (this.creating) return
      this.creating = true
      try {
        const allocations = []
        for (const it of this.chosen()) {
          const a = this.alloc[it.bonus_item_id]
          const person_pct = {}
          // 📌 只送 `plan` 回的那些人，不送畫面上殘留的任何名字。
          for (const p of it.people) person_pct[p] = this.toBp(a.people[p])
          allocations.push({
            bonus_item_id: it.bonus_item_id,
            total_pct: this.toBp(a.total),
            person_pct: person_pct,
          })
        }
        const r = await fetch('/api/bonus/awards', {
          method: 'POST',
          headers: this._jsonAuth(),
          body: JSON.stringify({ quote_no: this.plan.quote_no, allocations: allocations }),
        })
        const d = await r.json().catch(function () { return {} })
        if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status))
        this.createMsg = '已產生獎金單（單號 #' + d.id + '，基數 ' + this.fmt(d.base_amount) + '）。'
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
  }
}
