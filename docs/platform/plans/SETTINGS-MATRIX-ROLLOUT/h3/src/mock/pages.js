/* 第 2、3 頁籤的小互動（假資料；只示範畫面行為，不呼叫任何 API） */
(function () {
  const dirty = new WeakMap();
  const META = {
    'pg-approval': ['簽核設定', '簽核人、業務', true], 'pg-delegates': ['簽核代理人', '被代理人與代理人', false], 'pg-expense': ['支出申請類型', '申請支出的同仁', false],
    'pg-remit': ['匯款款別', '出納', true], 'pg-ledger': ['報表設定（科目歸屬）', '財務', true], 'pg-legal': ['法規參數', '最高管理者、開立勞報單的人', true], 'pg-acct': ['會計科目', '財務', true],
    'ot-bonus': ['獎金分潤預設比例', '最高管理者、之後新建獎金草稿的人', false, false], 'ot-voucher': ['傳票科目對應', '財務', true, true], 'ot-deduct': ['獎金扣繳與補充保費', '領獎金的人、財務', true, true],
    'ot-oh': ['管銷與公益金計算方式', '業務、財務', true, true], 'ot-target': ['年度營運目標', '看報表的人', false, false], 'ot-t100': ['T100 科目代號', '財務', true, true], 'ot-terms': ['報價條款與付款條件', '業務', false, false]
  };
  const origs = new Map();
  function remember(el) {
    if (origs.has(el)) return;
    origs.set(el, el.hasAttribute('data-sw') ? el.getAttribute('aria-checked') : el.type === 'checkbox' ? el.checked : el.tagName === 'SELECT' ? el.selectedIndex : el.value);
  }
  function mark(el) {
    const pg = el.closest('.pg'); if (!pg) return;
    remember(el);
    const set = dirty.get(pg) || new Set(); set.add(el); dirty.set(pg, set);
    const td = el.closest('td'); if (td) td.classList.add('chg-cell');
    const bar = pg.querySelector('[data-bar]');
    if (bar) { bar.classList.remove('hide'); bar.querySelector('.cnt').textContent = '已改 ' + set.size + ' 處，尚未儲存（也算進上方的儲存列）'; const pb = bar.querySelector('.btn.primary'); if (pb) pb.setAttribute('data-act', 'openSave'); }
    const m = META[pg.id] || [pg.id, '相關同仁', false];
    if (window.pageDirty) window.pageDirty(pg.id, set.size, m[0], m[1], m[2], !!m[3]);
  }
  window.pageClear = function () {
    origs.forEach((v, el) => { if (el.hasAttribute('data-sw')) el.setAttribute('aria-checked', v); else if (el.type === 'checkbox') el.checked = v; else if (el.tagName === 'SELECT') el.selectedIndex = v; else el.value = v; });
    origs.clear();
    document.querySelectorAll('.chg-cell').forEach(c => { const i = c.querySelector('[data-base]'); if (!i || String(i.value) === i.dataset.base) c.classList.remove('chg-cell'); });
    document.querySelectorAll('[data-bar]').forEach(b => b.classList.add('hide'));
    document.querySelectorAll('.pg').forEach(pg => dirty.delete(pg));
  };
  document.addEventListener('change', e => { const t = e.target; if (t.matches && t.matches('[data-d]')) mark(t); });
  document.addEventListener('input', e => { const t = e.target; if (t.matches && t.matches('[data-d][type=number],[data-d][type=text],textarea[data-d]')) mark(t); if (t.matches && t.matches('[data-split]')) split(); });
  function split() {
    const sum = Array.from(document.querySelectorAll('[data-split]')).reduce((a, x) => a + (Number(x.value) || 0), 0);
    const m = document.getElementById('splitmsg'), ok = Math.abs(sum - 100) < 0.001;
    m.innerHTML = '三類比例合計：<b>' + sum + '%</b> ' + (ok ? '✔' : '<span class="err">必須是 100%，存檔鈕暫時不能按</span>');
    const b = document.getElementById('bonusSave'); if (b) b.disabled = !ok;
  }
  document.addEventListener('click', e => {
    const t = e.target.closest('button,[data-sw]'); if (!t) return;
    if (t.hasAttribute('data-sw')) { t.setAttribute('aria-checked', t.getAttribute('aria-checked') === 'true' ? 'false' : 'true'); mark(t); return; }
    if (t.dataset.dfilter) {
      document.querySelectorAll('[data-dfilter]').forEach(b => b.setAttribute('aria-pressed', b === t));
      document.querySelectorAll('#dtab tbody tr').forEach(r => r.classList.toggle('hide', t.dataset.dfilter !== 'all' && r.dataset.s !== t.dataset.dfilter));
    }
    if (t.dataset.tree) {
      document.querySelectorAll('[data-tree]').forEach(b => b.setAttribute('aria-pressed', b === t));
      const lv = Number(t.dataset.tree);
      document.querySelectorAll('#tree .l2').forEach(x => x.classList.toggle('hide', lv < 2));
      document.querySelectorAll('#tree .l3').forEach(x => x.classList.toggle('hide', lv < 3));
    }
    if (t.hasAttribute('data-ledfilter')) {
      const on = t.getAttribute('aria-pressed') !== 'true'; t.setAttribute('aria-pressed', on); t.textContent = on ? '顯示全部' : '只看有問題的';
      document.querySelectorAll('#ledtab tbody tr').forEach(r => r.classList.toggle('hide', on && !r.dataset.bad));
    }
    if (t.id === 'ledapply') {
      const rows = Array.from(document.querySelectorAll('.ledchk:checked')).map(c => c.closest('tr'));
      const a = document.getElementById('ledrow').selectedIndex, b = document.getElementById('ledcf').selectedIndex;
      rows.forEach(r => { const s = r.querySelectorAll('select'); if (a > 0) { s[0].selectedIndex = 0; s[0].innerHTML = '<option>' + document.getElementById('ledrow').value + '</option>'; mark(s[0]); } if (b > 0) { s[1].innerHTML = '<option>' + document.getElementById('ledcf').value + '</option>'; mark(s[1]); } r.classList.remove('warnrow'); delete r.dataset.bad; });
    }
    if (t.dataset.wizard === 'oh') document.getElementById('ohwiz').classList.toggle('hide');
  });
  document.addEventListener('change', e => {
    if (e.target.classList && e.target.classList.contains('ledchk')) {
      const n = document.querySelectorAll('.ledchk:checked').length; document.getElementById('ledcnt').textContent = '已選 ' + n + ' 個科目';
    }
  });
  // 法規參數：與前一版不同的格自動變色
  document.querySelectorAll('[data-base]').forEach(i => { if (String(i.value) !== i.dataset.base) i.closest('td').classList.add('chg-cell'); });
  split();
})();
