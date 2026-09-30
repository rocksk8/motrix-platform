// module-builder-consts.js — 模組建構器的共用常數與零件註冊（W1 建構器第三輪：自 module-builder.html 內嵌腳本拆出，
// 程式檔超過 1500 行要拆，PLAYBOOK §G-瓶頸）。零件檔（core／form／flow／output）各自 `MotrixMB.parts.push(function (MB) { return {…} })`，
// `moduleBuilderPage()`（core）把各零件的資料與方法合併成同一個 Alpine 元件。
window.MotrixMB = (function () {
  var KEY_RE = /^[a-z][a-z0-9_]{1,39}$/
  var FIELD_KEY_RE = /^[a-z][a-z0-9_]{0,39}$/
      //: 顯示名稱（型別本身一律來自目錄；沒有對照的就顯示原代號）
  var TYPE_LABELS = { text: '文字', number: '數字', date: '日期', select: '下拉選單', checkbox: '勾選（是／否）', formula: '公式（唯讀）', ref: '參照' }
      //: 積木與參數的顯示名稱（只影響畫面文字；有哪些積木、哪些參數一律來自目錄 outputBlockSpecs／outputBlockItemSpecs）
  var BLOCK_LABELS = { identity_header: '抬頭（公司身分＋標題）', accent_bar: '色條', meta: '資料列', banner: '提示橫幅',
                           approval_sign: '簽核欄', identity_footer: '頁尾（公司身分）', watermark: '浮水印', boxes: '資訊框',
                           when: '條件分支', items_table: '明細表', amount_box: '金額框', totals: '合計表', sign_boxes: '手寫簽名欄',
                           doc_header: '文件抬頭', section_title: '段落標題', part: '分段', kv_table: '欄位表', footer_text: '頁尾文字', text_page: '文字頁' }
  var PARAM_LABELS = { title: '標題', label: '標籤', path: '資料', format: '格式', text: '文字', small: '小字', count: '重複次數',
                           unless: '條件成立就不印', fields: '資料列', boxes: '資訊框', rows: '列', columns: '欄', source: '清單',
                           hide_when_empty: '沒有資料就不印', equals: '等於', in: '屬於其中之一', then: '成立時', else: '不成立時',
                           row_label: '列標籤', style: '樣式', align: '對齊', width: '寬度', brand_path: '品牌', grand: '總計列',
                           date_label: '日期標籤', name_path: '簽名人', date_path: '日期', subtitle_path: '副標題', info: '資訊列',
                           name: '名稱', class: '樣式類別', page_break: '另起一頁', cells: '格', th: '欄名', colspan: '跨欄', tag: '標籤樣式', when: '條件' }
  var FORMAT_LABELS = { text: '文字', str: '原樣', money: '金額', date10: '日期' }
      // 縮圖導覽（BUILDER-UX §1）：7 格（使用者 2026-09-27 第二輪：欄位＋版面合成「表單」）；流程／簽核／通知三格都在第 4 步，
      // 點下去捲到對應區塊（data-step 1、2、4、5、6 不變，沒有 3）
  var NAV = [
        { id: 'basic', label: '基本', step: 1, thumb: 'basic' },
        { id: 'form', label: '表單', step: 2, thumb: 'fields' },
        { id: 'workflow', label: '流程', step: 4, anchor: 'mb-sec-workflow', thumb: 'workflow' },
        { id: 'approval', label: '簽核', step: 4, anchor: 'mb-sec-approval', thumb: 'approval', alias: true },
        { id: 'notify', label: '通知', step: 4, anchor: 'mb-sec-notify', thumb: 'notify', alias: true },
        { id: 'output', label: '輸出', step: 5, thumb: 'output' },
        { id: 'publish', label: '發布', step: 6, thumb: 'publish' }
      ]
      // 欄位型別的 icon（inline SVG，不用圖示字型、不用 CDN）；catalog 多出沒對照的型別 ⇒ 通用 icon（仍可使用）
  var _SVG = function (d) { return '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">' + d + '</svg>' }
  var TYPE_ICONS = {
        text: _SVG('<path d="M3 4h10M8 4v9"/>'),
        number: _SVG('<path d="M4 6h9M3 10h9M6.5 3 5 13M11 3 9.5 13"/>'),
        date: _SVG('<rect x="2.5" y="3.5" width="11" height="10" rx="1.5"/><path d="M2.5 7h11M5.5 2v3M10.5 2v3"/>'),
        select: _SVG('<rect x="2.5" y="4" width="11" height="8" rx="1.5"/><path d="m9 7 1.5 1.5L12 7"/>'),
        checkbox: _SVG('<rect x="2.5" y="2.5" width="11" height="11" rx="2"/><path d="m5 8 2 2 4-4"/>'),
        formula: _SVG('<path d="M9.5 2.5c-1.5 0-2 1-2.3 2.5L5.8 12c-.3 1.4-.9 1.8-2 1.8M5 6.5h5M10 9.5l3 3M13 9.5l-3 3"/>'),
        ref: _SVG('<path d="M6.5 9.5 9.5 6.5M7 4.5l1-1a2.5 2.5 0 0 1 3.5 3.5l-1 1M9 11.5l-1 1a2.5 2.5 0 0 1-3.5-3.5l1-1"/>')
      }
  var TYPE_ICON_GENERIC = _SVG('<rect x="2.5" y="2.5" width="11" height="11" rx="2"/><path d="M5.5 8h5"/>')
  var STEPS = [{ n: 1, label: '基本' }, { n: 2, label: '表單' }, { n: 4, label: '流程' }, { n: 5, label: '輸出' }, { n: 6, label: '發布' }]

      function clone(x) { return JSON.parse(JSON.stringify(x)) }

  return {
    KEY_RE: KEY_RE, FIELD_KEY_RE: FIELD_KEY_RE, TYPE_LABELS: TYPE_LABELS, BLOCK_LABELS: BLOCK_LABELS, PARAM_LABELS: PARAM_LABELS,
    FORMAT_LABELS: FORMAT_LABELS, NAV: NAV, TYPE_ICONS: TYPE_ICONS, TYPE_ICON_GENERIC: TYPE_ICON_GENERIC, STEPS: STEPS, clone: clone,
    svg: _SVG, parts: []
  }
})()
