/* 勞報單「選派發」可搜尋下拉的共用邏輯（第 55 班）。payslips.html（詳情）與 payslip-form.html（新增）共用。
 * 用法：在頁面 Alpine 資料裡 `...MotrixDispatchPicker.mixin({ contractorId: () => …, slipNo: () => …, onPick: (item) => … })`，
 * 畫面用 `dp.*` 狀態與 `dpSearch()`／`dpPick(item)`／`dpToggleAll()`／`dpOpen()`。
 * 畫面文字集中在 LABELS（日後要讓管理者改字，從這裡接）；不顯示任何代碼或編號欄位名。 */
(function (root) {
  var LABELS = {
    placeholder: '搜尋派發（派發編號、案件、廠商）',
    showAll: '顯示全部派發',
    showRoster: '只看這位受領人的派發',
    linked: '已關聯',
    linkedHere: '已連到這張勞報單',
    offRoster: '受領人不在此派發名單',
    empty: '沒有符合的派發',
    emptyRoster: '這位受領人目前沒有被排進派發，可改按「顯示全部派發」搜尋',
    loadMore: '載入更多',
    loading: '搜尋中…',
    failed: '無法讀取派發清單，請稍後再試',
    statusLabels: { sent: '已送出', confirmed: '已確認', pending_acceptance: '待驗收', accepted: '已驗收', completed: '已完成' }
  };
  var DELAY_MS = 300;

  function mixin(opt) {
    var timer = null, seq = 0;
    return {
      dp: { q: '', items: [], open: false, loading: false, includeAll: false, hasMore: false, notice: '', searched: false },
      dpLabels: LABELS,
      dpStatusLabel: function (s) { return LABELS.statusLabels[s] || s || ''; },
      dpOpen: function () { this.dp.open = true; if (!this.dp.searched) this.dpSearch(); },
      dpClose: function () { this.dp.open = false; },
      dpTyping: function () { var self = this; clearTimeout(timer); timer = setTimeout(function () { self.dpSearch(); }, DELAY_MS); },
      dpToggleAll: function () { this.dp.includeAll = !this.dp.includeAll; this.dpSearch(); },
      dpSearch: async function (more) {
        var mine = ++seq, dp = this.dp, cid = opt.contractorId ? opt.contractorId.call(this) : null;
        var slip = opt.slipNo ? opt.slipNo.call(this) : '';
        dp.loading = true; dp.notice = '';
        var url = '/api/payslip-dispatch-options?q=' + encodeURIComponent(dp.q || '') + '&offset=' + (more ? dp.items.length : 0)
          + (cid ? '&contractor_id=' + encodeURIComponent(cid) : '') + ((dp.includeAll || !cid) ? '&include_all=true' : '')
          + (slip ? '&slip_no=' + encodeURIComponent(slip) : '');
        try {
          var r = await fetch(url, { headers: { Authorization: 'Bearer ' + this.session.token } });
          if (mine !== seq) return;                                  // 後發的搜尋已取代這一次
          if (!r.ok) { dp.notice = LABELS.failed; if (!more) dp.items = []; return; }
          var b = await r.json();
          dp.items = more ? dp.items.concat(b.items || []) : (b.items || []);
          dp.hasMore = !!b.hasMore; dp.notice = b.notice || ''; dp.searched = true;
        } catch (e) { if (mine === seq) { dp.notice = LABELS.failed; if (!more) dp.items = []; } }
        finally { if (mine === seq) dp.loading = false; }
      },
      // 能不能選：已連到這張的、有選受領人但不在名單內的不能選（伺服器另擋）
      dpPickable: function (it) { return !it.linkedToThis && it.onRoster !== false; },
      dpReason: function (it) { return it.linkedToThis ? LABELS.linkedHere : (it.onRoster === false ? LABELS.offRoster : ''); },
      dpPick: function (it) {
        if (!this.dpPickable(it)) return;
        this.dp.open = false;
        if (opt.onPick) opt.onPick.call(this, it, this.dp.includeAll);
      }
    };
  }
  root.MotrixDispatchPicker = { LABELS: LABELS, mixin: mixin };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.MotrixDispatchPicker;
})(typeof window !== 'undefined' ? window : globalThis);
