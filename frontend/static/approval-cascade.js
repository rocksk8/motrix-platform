/* approval-cascade.js — 同一人連任多層簽核的前端共用判斷（2026-09-15）
 *
 * 使用者要求：「當某位主管同時為兩層以上簽核人，只要跳通知做確認，可直接簽核
 * 兩次以上，避免重複簽核兩次的狀態」。
 *
 * 作法是前端算出「按下去之後還會連續輪到自己幾層」，把層數寫進原本就有的那個
 * 確認視窗（不多跳第二個視窗），使用者確認即帶 `cascade: true` 給後端，由後端
 * 重新驗證一次再一次蓋完那幾層（見 helpers/tiered_approval.py::plan_self_cascade()）。
 * 前端這份只負責「要不要在確認訊息裡講、要不要帶旗標」，**權限判斷一律以後端為準**。
 *
 * 條件刻意跟後端同一套、而且保守：只收「簽下去之後這一層一定完成」的層。
 *   - 預設語意（報價單／出貨單／請款單／完工單／兩種憑據）：該層剩下未簽核的
 *     只有自己（或自己正在代理的人）。還有別人要簽就停——跨過去等於替別人決定。
 *   （2026-09-25 起所有單據同一種判斷：同層每一位都要依序簽完，原本額外支出的 completesOnFirst 已移除。）
 *
 * 各頁面用法：
 *   const nos = MotrixApproval.selfCascadeTiers(tiers, currentTier, me, delegatedFor)
 *   confirmMsg += MotrixApproval.cascadeNote(nos)          // 講清楚會一起簽掉哪幾層
 *   body: JSON.stringify({ ..., cascade: nos.length > 0 })
 *
 * ── 簽核二擇一 S5：核准前的「維持／編輯」選擇（報價單；quotation-form 與 approval-queue 共用同一支）──
 *   const flags = MotrixApproval.flagsFor(detail.approveReview, entryUser, me)   // 空陣列 ⇒ 不跳窗，走原本的確認視窗
 *   const pick  = await MotrixApproval.askChoice({ flags, changedBlocks, newReasons, needNote, canEdit, summary, extra })
 *   //   pick＝null（取消）｜{choice:'edit'}｜{choice:'keep', note}
 *   body: { ..., expectedFp, choice: 'keep', confirmNote: pick.note }
 *   // 伺服器為準：409＋X-Approve-Flags（或 X-Approve-Need-Note）＝畫面資料過期，重載後再問一次（MotrixApproval.conflictInfo(resp)）
 */
(function () {
  function matches(a, me, delegatedFor) {
    const u = a && a.username;
    if (!u) return false;
    return u === me || (delegatedFor || []).indexOf(u) >= 0;
  }

  /** 回傳「這一次按下去可以順便一起簽掉」的層序號（1-based，供顯示用）。 */
  // 2026-09-25：原本另有 opts.completesOnFirst（額外支出「當層任一人簽即通過」）；
  // 使用者裁示同層每一位都要依序簽完 ⇒ 已移除，只剩「剩下未簽的全是我（或我代理的人）」一種判斷。
  function selfCascadeTiers(tiers, currentTier, me, delegatedFor) {
    const list = tiers || [];
    const cur = currentTier || 0;
    if (!list.length || cur >= list.length) return [];
    // 目前這一層自己簽下去之後會不會結束？不會的話後面根本輪不到，直接不談。
    const curPending = ((list[cur] || {}).approvers || []).filter(a => a.status !== 'approved');
    if (!curPending.length) return [];
    if (!curPending.every(a => matches(a, me, delegatedFor))) return [];

    const out = [];
    for (let i = cur + 1; i < list.length; i++) {
      const pending = ((list[i] || {}).approvers || []).filter(a => a.status !== 'approved');
      if (!pending.length) break;
      if (!pending.every(a => matches(a, me, delegatedFor))) break;
      out.push(i + 1);
    }
    return out;
  }

  /** 接在既有確認訊息後面的說明，沒有可合併的層時回空字串。 */
  function cascadeNote(nos) {
    if (!nos || !nos.length) return '';
    return `\n\n⚠ 您同時是第 ${nos.join('、')} 層的簽核人，確認後將一併完成這 ${nos.length + 1} 層簽核（不需要再簽一次）。`;
  }

  /** 後端回來的 signedTiers 轉成提示文字。 */
  function signedToast(signedTiers) {
    if (!signedTiers || signedTiers.length < 2) return '';
    return `（已一併完成第 ${signedTiers.join('、')} 層）`;
  }

  // ── S5：維持／編輯彈窗 ──────────────────────────────────────────────────────────────
  const FLAG_TEXT = {
    reconfirm: '這張單的內容在你簽過之後有變動，需要你重新確認。',
    reassigned: '這張單是由最高管理者轉簽給你的，你沒有經手過前面的內容。',
    delegated: '你是以代理人身分簽核，不是原本指定的簽核人。'
  };
  const BLOCK_TEXT = {
    items: '品項', tot: '總額', customerName: '客戶名稱', projectName: '專案名稱', discount: '折讓', showDiscount: '折讓',
    taxRate: '稅率', validDays: '有效天數', paymentTerms: '付款條件', deliveryTerms: '交貨條件', acceptanceTerms: '驗收標準',
    warrantyTerms: '保固條件', afterSales: '售後服務', termsPresetKey: '條款組', quoteDate: '報價日期'
  };
  function blockLabel(k) {
    if (BLOCK_TEXT[k]) return BLOCK_TEXT[k];
    if (k.indexOf('caseRecord.') === 0) return '案件記錄（' + k.slice(11) + '）';
    return k;
  }

  /** 要跳窗的旗標集合：伺服器給的（reconfirm／reassigned，與檢視者無關）＋「按的人不是當層待簽人」＝代理。只是畫面提示——真正的強制在伺服器（409）。 */
  function flagsFor(review, entryUser, me) {
    if (!review) return [];
    const out = (review.flags || []).slice();
    if (entryUser && me && entryUser !== me && out.indexOf('delegated') < 0) out.push('delegated');
    return out;
  }

  /** 讀 409 的旗標標頭：{flags:[…], needNote:bool}；不是這類 409 回 null（呼叫端照一般錯誤處理）。 */
  function conflictInfo(resp) {
    if (!resp || resp.status !== 409 || !resp.headers) return null;
    const f = resp.headers.get('X-Approve-Flags');
    if (!f) return null;
    return { flags: f.split(',').filter(Boolean), needNote: resp.headers.get('X-Approve-Need-Note') === '1' };
  }

  function el(tag, css, text, attrs) {
    const e = document.createElement(tag);
    if (css) e.style.cssText = css;
    if (text != null) e.textContent = text;           // 一律 textContent：原因文字來自單據內容，不當 HTML
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    return e;
  }

  /**
   * 彈窗。回傳 Promise：null（取消）｜{choice:'edit'}｜{choice:'keep', note}。
   * opts: flags[], changedBlocks[], newReasons[], needNote(bool), canEdit(bool), summary(字串), extra(字串；例如連簽說明)
   * needNote＝重算後新增了需審核原因：「維持核准」要填一句說明才能按。
   */
  function askChoice(opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      const prev = document.activeElement;
      const shade = el('div', 'position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:100000;display:flex;align-items:center;justify-content:center;padding:16px',
        null, { 'data-testid': 'approve-choice-dialog' });
      const box = el('div', 'background:#fff;color:#1C1917;border-radius:10px;max-width:480px;width:100%;max-height:90vh;overflow:auto;padding:20px 22px;box-shadow:0 12px 40px rgba(0,0,0,.35);font-size:13px;line-height:1.7;font-family:inherit',
        null, { role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'approve-choice-title' });
      box.appendChild(el('div', 'font-size:15px;font-weight:700;margin-bottom:6px', '核准前請先確認', { id: 'approve-choice-title' }));
      if (opts.summary) box.appendChild(el('div', 'color:#57534E;margin-bottom:8px;white-space:pre-line', opts.summary));
      const ul = el('ul', 'margin:0 0 8px 18px;padding:0');
      (opts.flags || []).forEach(function (f) { ul.appendChild(el('li', '', FLAG_TEXT[f] || f, { 'data-flag': f })); });
      box.appendChild(ul);
      if ((opts.changedBlocks || []).length) {
        box.appendChild(el('div', 'margin-bottom:8px', '變動的區塊：' + opts.changedBlocks.map(blockLabel).join('、'), { 'data-testid': 'approve-choice-blocks' }));
      }
      if ((opts.newReasons || []).length) {
        box.appendChild(el('div', 'font-weight:600;margin-top:4px', '新增／加重的需審核原因：'));
        const rl = el('ul', 'margin:2px 0 8px 18px;padding:0;color:#B45309', null, { 'data-testid': 'approve-choice-reasons' });
        opts.newReasons.forEach(function (t) { rl.appendChild(el('li', '', t)); });
        box.appendChild(rl);
      }
      if (opts.extra) box.appendChild(el('div', 'margin:6px 0;color:#B45309;white-space:pre-line', String(opts.extra).trim()));
      let ta = null;
      if (opts.needNote) {
        box.appendChild(el('div', 'font-weight:600;margin-top:6px', '維持核准前，請寫一句確認說明（會記進稽核）：'));
        ta = el('textarea', 'width:100%;box-sizing:border-box;min-height:64px;margin-top:4px;padding:6px 8px;border:1px solid #D6D3D1;border-radius:6px;font:inherit',
          null, { maxlength: '200', 'data-testid': 'approve-choice-note', 'aria-label': '確認說明' });
        box.appendChild(ta);
      }
      const bar = el('div', 'display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap;margin-top:14px');
      const btn = function (text, css, tid) {
        return el('button', 'padding:7px 14px;border-radius:6px;border:1px solid #D6D3D1;cursor:pointer;font:inherit;' + css, text, { type: 'button', 'data-testid': tid });
      };
      const cancel = btn('取消', 'background:#fff', 'approve-choice-cancel');
      const edit = opts.canEdit ? btn('編輯內容', 'background:#fff;border-color:#4338CA;color:#4338CA', 'approve-choice-edit') : null;
      const keep = btn('維持核准', 'background:#15803D;border-color:#15803D;color:#fff', 'approve-choice-keep');
      bar.appendChild(cancel); if (edit) bar.appendChild(edit); bar.appendChild(keep);
      box.appendChild(bar);
      if (!opts.canEdit) box.appendChild(el('div', 'margin-top:8px;color:#78716C;font-size:12px', '你的身分不能在這裡直接改內容；若要修改請退回，或請有編輯權限的簽核人處理。', { 'data-testid': 'approve-choice-noedit' }));
      shade.appendChild(box);
      document.body.appendChild(shade);

      const sync = function () {
        const off = !!ta && !ta.value.trim();
        keep.disabled = off; keep.style.opacity = off ? '.45' : '1'; keep.style.cursor = off ? 'not-allowed' : 'pointer';
      };
      if (ta) ta.addEventListener('input', sync);
      sync();
      let done = false;
      const onKey = function (ev) {
        if (ev.key === 'Escape') { ev.stopPropagation(); finish(null); return; }
        if (ev.key !== 'Tab') return;                               // 焦點圈住：Tab／Shift+Tab 只在彈窗內可操作的元件間循環（不跳到背後的頁面）
        const f = Array.prototype.slice.call(box.querySelectorAll('textarea,button')).filter(function (x) { return !x.disabled; });
        ev.preventDefault();
        if (!f.length) return;
        const i = f.indexOf(document.activeElement);
        f[ev.shiftKey ? (i <= 0 ? f.length - 1 : i - 1) : (i < 0 || i === f.length - 1 ? 0 : i + 1)].focus();
      };
      function finish(v) {
        if (done) return; done = true;
        document.removeEventListener('keydown', onKey, true);
        shade.remove();
        if (prev && prev.focus) { try { prev.focus(); } catch (e) { /* 原本的焦點元素可能已不在 */ } }
        resolve(v);
      }
      document.addEventListener('keydown', onKey, true);
      cancel.addEventListener('click', function () { finish(null); });
      shade.addEventListener('mousedown', function (ev) { if (ev.target === shade) finish(null); });
      if (edit) edit.addEventListener('click', function () { finish({ choice: 'edit' }); });
      keep.addEventListener('click', function () { if (keep.disabled) return; finish({ choice: 'keep', note: ta ? ta.value.trim() : '' }); });
      (ta || keep).focus();
    });
  }

  window.MotrixApproval = { selfCascadeTiers, cascadeNote, signedToast, flagsFor, conflictInfo, askChoice, blockLabel };
})();
