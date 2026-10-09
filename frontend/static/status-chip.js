// 單據狀態 → 晶片顏色類別的唯一對照（第 51 班）。CSS 在 css/style.css 的 `.st-chip`／`.st-chip--*`（全用語意 token）。
// 用法（Alpine）：<span :class="MotrixStatus.chipClass(e.status)" x-text="e.status"></span>
// 未知狀態 ⇒ 只回基底 `st-chip`（中性），不會誤上色；要新增狀態只改這張表（並補 backend/tests/test_status_chip_t51.py 的詞彙）。
(function () {
  var MAP = {
    '草稿': 'draft',
    '待審核': 'pending', '待核准': 'pending',
    '簽核中': 'signing',
    '已核准': 'approved',
    '已駁回': 'rejected', '已退回': 'rejected', '已拒絕': 'rejected',
    '已付款': 'paid', '已匯款': 'paid',
    '已作廢': 'void', '已取消': 'void', '已撤回': 'void', '已撤銷': 'void'
  }

  function tone(status) {
    var k = String(status == null ? '' : status).trim()
    return Object.prototype.hasOwnProperty.call(MAP, k) ? MAP[k] : ''
  }

  function chipClass(status) {
    var t = tone(status)
    return t ? 'st-chip st-chip--' + t : 'st-chip'
  }

  var api = { chipClass: chipClass, tone: tone, MAP: MAP }
  if (typeof window !== 'undefined') window.MotrixStatus = api
  if (typeof module !== 'undefined' && module.exports) module.exports = api
})()
