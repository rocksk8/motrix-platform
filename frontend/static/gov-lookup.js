/* 政府登記資料「依公司名稱」查詢（GCIS Proxy）— 客戶／供應商／承攬商三頁共用
 *
 * 2026-09-10：後端 `GET /api/company/search?q=` 從一開始就存在，但三個頁面都只接了
 * `/api/company/tax/{id}`（統編查詢）——使用者必須先知道確切統編才查得到，
 * 想用公司名稱找就只能自己去經濟部網站查完再回來貼。這支把缺的那半接上。
 *
 * 為什麼抽成共用檔：三頁的統編查詢已經各自有一份幾乎一模一樣的實作（連錯誤訊息
 * 文字都相同），本專案吃過好幾次「同一段邏輯散在多處、改一半忘了其餘」的虧
 * （見 MOTRIX-ERP-QUICK.md 各處「12 個呼叫點全部更新」的紀錄）。所以「查詢 +
 * 錯誤對應」這段完全相同的邏輯只寫一次；「帶入表單」各頁欄位名不同
 * （customers 用 taxId、vendor-contractors 用 tax_id，客戶頁還會推斷產業別），
 * 那部分維持各頁自己處理，由呼叫端傳 apply callback。
 */
(function () {
  'use strict';

  function fetchWithTimeout(url, opts, ms) {
    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, ms || 12000);
    return fetch(url, Object.assign({}, opts, { signal: ctrl.signal }))
      .then(function (r) { clearTimeout(timer); return r; })
      .catch(function (e) { clearTimeout(timer); throw e; });
  }

  window.MotrixGovLookup = {
    MIN_LEN: 2,

    /**
     * 依公司名稱查詢，回傳統一形狀的結果，不丟例外——呼叫端只要看 ok 就好。
     *   成功：{ ok: true,  results: [{name, taxId, status}, ...] }
     *   失敗：{ ok: false, status: <HTTP 狀態或 0>, msg: '<可直接顯示的訊息>' }
     * status 0 代表逾時／網路層失敗；401 由呼叫端自行決定要不要登出。
     */
    searchByName: function (q, token) {
      var query = (q || '').trim();
      if (query.length < this.MIN_LEN) {
        return Promise.resolve({
          ok: false, status: 0,
          msg: '公司名稱至少輸入 ' + this.MIN_LEN + ' 個字'
        });
      }
      return fetchWithTimeout(
        '/api/company/search?q=' + encodeURIComponent(query),
        { headers: { Authorization: 'Bearer ' + token } },
        12000
      ).then(function (r) {
        if (r.ok) {
          return r.json().then(function (list) {
            return { ok: true, results: Array.isArray(list) ? list : [] };
          });
        }
        if (r.status === 401) return { ok: false, status: 401, msg: '登入已過期' };
        if (r.status === 503) {
          return { ok: false, status: 503,
                   msg: '政府資料庫連線失敗，請確認伺服器對外網路或稍後再試' };
        }
        if (r.status === 422 || r.status === 400) {
          return { ok: false, status: r.status, msg: '查詢字串不合法，請換個關鍵字' };
        }
        return { ok: false, status: r.status,
                 msg: '政府資料庫查詢失敗，請稍後再試或手動輸入' };
      }).catch(function () {
        return { ok: false, status: 0, msg: '查詢逾時，請確認網路連線' };
      });
    },

    /**
     * 給 Alpine 頁面 spread 進 x-data 用的一組狀態＋方法。
     * 呼叫端必須自己提供：
     *   this.session.token          — 認證
     *   this.lookupMsg / lookupOk   — 沿用各頁既有的訊息列，不另外做一套
     *   this.govApply(d)            — 把 {name, taxId} 帶進該頁的表單
     *   this.logout()（選用）        — 401 時呼叫，沒有就導回登入頁
     */
    alpineState: function () {
      return {
        govNameQ: '',
        govSearching: false,
        govResults: null,      // null = 還沒查過；[] = 查過但沒結果

        async govSearchByName() {
          this.govSearching = true;
          this.govResults = null;
          this.lookupMsg = '';
          this.lookupOk = false;
          var res = await window.MotrixGovLookup.searchByName(
            this.govNameQ, this.session.token);
          this.govSearching = false;
          if (res.ok) {
            this.govResults = res.results;
            if (!res.results.length) {
              this.lookupMsg = '查無符合的公司／商業登記，請換關鍵字或手動輸入';
              this.lookupOk = false;
            }
            return;
          }
          if (res.status === 401) {
            if (typeof this.logout === 'function') this.logout();
            else location.href = 'login.html';
            return;
          }
          this.lookupMsg = res.msg;
          this.lookupOk = false;
        },

        govPick(d) {
          this.govResults = null;
          this.govNameQ = '';
          this.govApply(d);
        },

        govClearResults() {
          this.govResults = null;
        },
      };
    },
  };
})();
