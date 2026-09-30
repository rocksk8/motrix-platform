/* approval-return.js — 預覽裡的「退回修改」共用元件（使用者 2026-09-30，第 27 班）
 *
 * 規則：尚未核可的單據，PDF 預覽上有紅色「未核可・僅供預覽」；**有權決定這一張的人**在預覽視窗裡可以直接「退回修改」。
 * 這裡不重做退回流程：各頁面把「原本那支退回端點」包成 post(reason) 傳進來，本元件只負責
 *   ① 判斷要不要顯示按鈕（canDecide：只是顯示用，權限一律以後端為準）
 *   ② 跳出原因視窗（原因必填；空白不送）
 *   ③ 把後端的錯誤（403／400…）原文顯示在視窗裡，不吞掉
 * 後端同樣強制原因必填（helpers.tiered_approval.require_reject_reason，400），稽核由各端點自己寫。
 *
 * 用法：
 *   MotrixApprovalReturn.ask({
 *     title: '退回修改：請款單 PR-202609-001',
 *     post: async (reason) => fetch(url, {method:'POST', headers, body: JSON.stringify({ note: reason })}),  // 回 Response
 *     onDone: () => { ...關預覽、重載列表... },
 *   })
 *   MotrixApprovalReturn.canDecide(approval, session, delegatedFor)   // approval＝單據的 approval 物件（tiers／currentTier）
 *   await MotrixApprovalReturn.loadDelegators(token)                   // 代理中的人（快取）
 */
(function () {
  var _delegated = null;

  function canDecide(approval, session, delegatedFor, opts) {
    if (!session) return false;
    approval = approval || {};
    var tiers = approval.tiers || approval.steps || [];
    // 最高管理者可退回任何一張；例外：會計傳票有簽核鏈時最高管理者不特權（opts.superadminBypass=false）
    if (session.role === 'superadmin' && (!opts || opts.superadminBypass !== false || !tiers.length)) return true;
    var cur = approval.currentTier || 0;
    if (!tiers.length || cur >= tiers.length) return false;
    var names = ((tiers[cur] || {}).approvers || []).map(function (a) { return a && a.username; });
    var me = session.username;
    var deleg = delegatedFor || _delegated || [];
    return names.indexOf(me) >= 0 || names.some(function (n) { return deleg.indexOf(n) >= 0; });
  }

  async function loadDelegators(token) {
    if (_delegated) return _delegated;
    try {
      var r = await fetch('/api/approval-queue', { headers: { Authorization: 'Bearer ' + token } });
      var d = r.ok ? await r.json() : {};
      _delegated = d.myDelegatedFor || [];
    } catch (e) { _delegated = []; }
    return _delegated;
  }

  function el(tag, attrs, text) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (text != null) e.textContent = text;
    return e;
  }

  function ask(opts) {
    opts = opts || {};
    var prev = document.querySelector('[data-testid="return-dialog"]');
    if (prev) prev.remove();
    var overlay = el('div', { 'data-testid': 'return-dialog', style: 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:600;display:flex;align-items:center;justify-content:center;padding:20px' });
    var box = el('div', { role: 'dialog', 'aria-modal': 'true', style: 'background:#fff;border-radius:12px;width:100%;max-width:440px;padding:18px 20px;box-shadow:0 16px 48px rgba(0,0,0,.25);font-family:var(--font-zh,sans-serif)' });
    box.appendChild(el('div', { style: 'font-size:15px;font-weight:700;margin-bottom:4px' }, opts.title || '退回修改'));
    box.appendChild(el('div', { style: 'font-size:12px;color:#6B6B6B;margin-bottom:10px' }, opts.hint || '單據會退回草稿，申請人修改後可重新送審。退回原因必填，會寫進稽核。'));
    var ta = el('textarea', { 'data-testid': 'return-reason', rows: '4', placeholder: '退回原因（必填）', style: 'width:100%;box-sizing:border-box;border:1px solid #D4D4D4;border-radius:6px;padding:8px;font-size:13px;font-family:inherit' });
    box.appendChild(ta);
    var err = el('div', { 'data-testid': 'return-error', style: 'color:#B91C1C;font-size:12px;min-height:16px;margin-top:6px' });
    box.appendChild(err);
    var row = el('div', { style: 'display:flex;justify-content:flex-end;gap:8px;margin-top:8px' });
    var cancel = el('button', { type: 'button', 'data-testid': 'return-cancel', style: 'padding:7px 14px;border:1px solid #D4D4D4;border-radius:7px;background:#fff;cursor:pointer;font-size:13px' }, '取消');
    var ok = el('button', { type: 'button', 'data-testid': 'return-confirm', style: 'padding:7px 14px;border:1px solid #DC2626;border-radius:7px;background:#DC2626;color:#fff;cursor:pointer;font-size:13px;font-weight:600' }, '確認退回');
    row.appendChild(cancel); row.appendChild(ok); box.appendChild(row);
    overlay.appendChild(box); document.body.appendChild(overlay);
    ta.focus();
    function close() { overlay.remove(); document.removeEventListener('keydown', onKey, true); }
    function onKey(e) { if (e.key === 'Escape') { e.stopPropagation(); close(); } }
    document.addEventListener('keydown', onKey, true);
    cancel.addEventListener('click', close);
    var busy = false;
    ok.addEventListener('click', async function () {
      if (busy) return;
      var reason = (ta.value || '').trim();
      if (!reason) { err.textContent = '退回要填原因'; ta.focus(); return; }
      busy = true; ok.disabled = true; err.textContent = '';
      try {
        var r = await opts.post(reason);
        if (r && r.ok === false) {
          var d = await r.json().catch(function () { return {}; });
          err.textContent = '退回失敗：' + (d.detail || r.status);
          busy = false; ok.disabled = false; return;
        }
        close();
        if (opts.onDone) opts.onDone(reason);
      } catch (e) {
        err.textContent = '網路錯誤：' + e.message;
        busy = false; ok.disabled = false;
      }
    });
  }

  window.MotrixApprovalReturn = { ask: ask, canDecide: canDecide, loadDelegators: loadDelegators };
})();
