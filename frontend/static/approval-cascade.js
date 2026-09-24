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

  window.MotrixApproval = { selfCascadeTiers, cascadeNote, signedToast };
})();
