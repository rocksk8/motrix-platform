/* 共用檔案預覽（L1 前端；設計稿 proposal-attachments-search-preview.md §3，P1）。
 *
 * 從傳票頁 JV28 的頁內預覽窗抽出：全系統上傳檔案的預覽都用這一個元件，不再各頁各自 window.open／新分頁／photo-token。
 *
 *   MotrixFilePreview.open({
 *     items,             // [{filename, mime, size, ...任意欄位}]
 *     index,             // 起始（預設 0）
 *     fetchBlob(item, type)  // 回 Promise<ArrayBuffer|Blob>；呼叫端決定打哪支端點（元件不知道業務）。type＝我們判定的 MIME
 *     meta(item),        // 視窗下方一行文字（可省）
 *     actions,           // [{label(字串或 fn(item))), testid, enabled(item), run(item), ghost}]（例：傳票「帶入附件」「取消」）
 *     download,          // 預設 true：下方有「下載」按鈕（一律 octet-stream，瀏覽器不會把它當網頁開）
 *     nav,               // 預設 items.length>1：◀ ▶ 與 ←→ 切換
 *     opener,            // 關閉後焦點回去的元素（省略＝開啟當下的 activeElement）
 *     testids,           // 覆寫 data-testid（傳票頁沿用舊名）；省略＝預設 file-preview-*
 *     onClose()
 *   })
 *   MotrixFilePreview.kind(item)   // 'image' | 'pdf' | 'sheet' | 'doc' | 'download'（純函式，可單測）
 *   MotrixFilePreview.close() / .refresh() / .setStatus(text) / .isOpen() / .current()
 *   MotrixFilePreview.openFile(item[, extra])  // 一行開單一檔案（預設 byUploadsPath）；withMime(item)：沒有 mime 的白名單儲存補 mime
 *   MotrixFilePreview.byUploadsPath(item)  // 預設取檔轉接器：Authorization 標頭打 /api/uploads/{item.path}（不換 photo-token）
 *   MotrixFilePreview.openInNewTab(item, fetchBlob)  // 「另開新分頁」（出納要保留的行為）：在使用者手勢內先開空白分頁再導向 blob
 *
 * 內嵌規則（不放寬）：
 *   ☠️ 只有 image／pdf 內嵌；SVG／HTML／其他一律不內嵌（在我們的網域執行上傳者的腳本）。
 *   ⚠️ mime 取自上傳者宣稱的 content-type ⇒ 可以是假的，所以「副檔名 ＋ mime」兩者都符合才內嵌，缺一不可。
 *   🔑 blob 建立時明確指定 type（用我們判定的，不用回應標頭的）；關閉或切換一律 revoke；回應回來時已切換／關閉就丟棄。
 *   docx／xlsx 等（sheet／doc）＝檔案卡＋下載；伺服器端表格／文字預覽是 P4，不在這裡。
 */
(function () {
  var IMAGE = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp' }
  var PDF = { '.pdf': 'application/pdf' }
  var SHEET = { '.xls': 1, '.xlsx': 1, '.csv': 1 }
  var DOC = { '.doc': 1, '.docx': 1 }

  function extOf(name) {
    name = String(name || '').toLowerCase()
    var dot = name.lastIndexOf('.')
    return dot >= 0 ? name.slice(dot) : ''
  }

  function mimeOf(item) { return String((item && item.mime) || '').toLowerCase().split(';')[0].trim() }

  function kind(item) {
    var ext = extOf(item && item.filename)
    var mime = mimeOf(item)
    if (IMAGE[ext] && IMAGE[ext] === mime) return 'image'
    if (PDF[ext] && PDF[ext] === mime) return 'pdf'
    if (SHEET[ext]) return 'sheet'
    if (DOC[ext]) return 'doc'
    return 'download'
  }

  function typeOf(item, k) { return k === 'image' ? IMAGE[extOf(item.filename)] : 'application/pdf' }

  function fileSize(n) {
    var v = Number(n) || 0
    if (!v) return ''
    if (v < 1024) return v + ' B'
    if (v < 1024 * 1024) return (v / 1024).toFixed(1) + ' KB'
    return (v / 1024 / 1024).toFixed(1) + ' MB'
  }

  function authHeader() {
    var s = {}
    try { s = JSON.parse(localStorage.getItem('motrix_session') || '{}') } catch (e) {}
    return { Authorization: 'Bearer ' + (s.token || '') }
  }

  function byUploadsPath(item) {
    var rel = String((item && item.path) || '')
    return fetch('/api/uploads/' + rel.split('/').map(encodeURIComponent).join('/'), { headers: authHeader() }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status)
      return r.arrayBuffer()
    })
  }

  function toBlob(data, type) {
    if (data && typeof data.arrayBuffer === 'function' && !(data instanceof ArrayBuffer)) {
      return data.arrayBuffer().then(function (buf) { return new Blob([buf], { type: type }) })
    }
    return Promise.resolve(new Blob([data], { type: type }))
  }

  // 伺服器端已用副檔名白名單（jpg／jpeg／png／pdf）擋掉其他上傳的儲存位置（/api/uploads、勞報單簽回）：檔案 metadata 沒有 mime 時，
  // 副檔名就是白名單保證過的那一半 ⇒ 補上對應 mime，才能內嵌。已有 mime 的不動（仍要與副檔名一致才內嵌）。
  function withMime(it) {
    if (!it || it.mime) return it
    var ext = extOf(it.filename || it.name || it.path)
    var m = IMAGE[ext] || PDF[ext]
    return m ? Object.assign({}, it, { filename: it.filename || it.name || String(it.path || '').split('/').pop(), mime: m }) : Object.assign({}, it, { filename: it.filename || it.name || String(it.path || '').split('/').pop() })
  }

  // 一行開檔：單一檔案（{path, filename, mime?, size?}），預設走 /api/uploads/{path}（Authorization 標頭，權限由擁有模組的 uploads.path_access 判斷）。
  function openFile(it, extra) {
    return open(Object.assign({ items: [withMime(it)], index: 0, nav: false, fetchBlob: byUploadsPath }, extra || {}))
  }

  var STYLE_ID = 'fp-style'
  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return
    var st = document.createElement('style')
    st.id = STYLE_ID
    st.textContent =
      '.fp-stage{position:relative;display:flex;align-items:center;justify-content:center}' +
      '.fp-nav{position:absolute;top:50%;transform:translateY(-50%);width:36px;height:36px;border-radius:50%;border:1px solid var(--border-light);background:#fff;font-size:16px;cursor:pointer}' +
      '.fp-nav--prev{left:4px}.fp-nav--next{right:4px}' +
      '.fp-img{max-width:calc(100% - 96px);max-height:calc(70vh / var(--fz,1));object-fit:contain}' +
      '.fp-pdf{width:calc(100% - 96px);height:calc(70vh / var(--fz,1));border:1px solid var(--border-light)}' +
      '.fp-meta{font-size:12px;color:var(--text-secondary);margin-right:auto}' +
      '.fp-hint{font-size:11px;color:var(--text-secondary);font-weight:400}' +
      '.fp-err{margin:10px 0;padding:9px 11px;border:1px solid #FCA5A5;background:#FEF2F2;border-radius:var(--radius);font-size:12px;color:#7F1D1D;line-height:1.7}' +
      '.fp-card{padding:24px}' +
      '.fp-foot-actions{display:flex;gap:8px;align-items:center}'
    document.head.appendChild(st)
  }

  var DEFAULT_IDS = { overlay: 'file-preview', close: 'file-preview-close', prev: 'file-preview-prev', next: 'file-preview-next',
                      img: 'file-preview-img', pdf: 'file-preview-pdf', meta: 'file-preview-meta', download: 'file-preview-download' }

  var S = null   // 目前開著的預覽狀態；null＝關閉

  function el(tag, attrs, text) {
    var e = document.createElement(tag)
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'class') e.className = attrs[k]
      else if (k === 'testid') e.setAttribute('data-testid', attrs[k])
      else e.setAttribute(k, attrs[k])
    })
    if (text !== undefined && text !== null) e.textContent = text
    return e
  }

  function item() { return S ? S.items[S.idx] : null }

  function revoke() {
    if (S && S.url) { URL.revokeObjectURL(S.url); S.url = '' }
  }

  function ids() { return Object.assign({}, DEFAULT_IDS, (S && S.opts.testids) || {}) }

  function render() {
    if (!S) return
    var it = item()
    var T = ids()
    var root = S.root
    root.setAttribute('data-testid', T.overlay)
    root.innerHTML = ''
    var box = el('div', { class: 'modal-box', role: 'dialog', 'aria-modal': 'true' })
    S.box = box
    var head = el('div', { class: 'modal-head' })
    head.appendChild(el('span', { class: 'modal-head__title' }, (it ? it.filename : '') + '　（' + (S.idx + 1) + ' / ' + S.items.length + '）'))
    var closeBtn = el('button', { class: 'modal-close', testid: T.close, type: 'button' }, '×')
    closeBtn.addEventListener('click', close)
    head.appendChild(closeBtn)
    box.appendChild(head)

    var body = el('div', { class: 'modal-body', style: 'text-align:center' })
    if (S.loading) body.appendChild(el('div', { class: 'fp-hint' }, '載入中…'))
    if (S.err) body.appendChild(el('div', { class: 'fp-err' }, S.err))
    var stage = el('div', { class: 'fp-stage' })
    if (S.nav) {
      var prev = el('button', { class: 'fp-nav fp-nav--prev', testid: T.prev, type: 'button', 'aria-label': '上一個' }, '◀')
      prev.addEventListener('click', function () { step(-1) })
      stage.appendChild(prev)
    }
    if (S.kind === 'image' && S.url) {
      var img = el('img', { class: 'fp-img', testid: T.img, alt: '' })
      img.src = S.url
      stage.appendChild(img)
    } else if (S.kind === 'pdf' && S.url) {
      var fr = el('iframe', { class: 'fp-pdf', testid: T.pdf, title: '附件預覽' })
      fr.src = S.url
      stage.appendChild(fr)
    }
    if (S.nav) {
      var next = el('button', { class: 'fp-nav fp-nav--next', testid: T.next, type: 'button', 'aria-label': '下一個' }, '▶')
      next.addEventListener('click', function () { step(1) })
      stage.appendChild(next)
    }
    body.appendChild(stage)
    if (it && (S.kind === 'download' || S.kind === 'sheet' || S.kind === 'doc')) {
      var card = el('div', { class: 'fp-card', 'data-fp-card': S.kind })
      card.appendChild(el('div', {}, it.filename))
      card.appendChild(el('div', { class: 'fp-hint' }, [fileSize(it.size), it.mime || '未知類型'].filter(Boolean).join('　')))
      card.appendChild(el('div', { class: 'fp-hint' }, '這個類型不在頁面上直接顯示，請下載後開啟。'))
      body.appendChild(card)
    }
    box.appendChild(body)

    var foot = el('div', { class: 'modal-foot' })
    foot.appendChild(el('span', { class: 'fp-meta', testid: T.meta }, S.opts.meta && it ? (S.opts.meta(it) || '') : ''))
    var acts = el('span', { class: 'fp-foot-actions' })
    if (S.status) acts.appendChild(el('span', { class: 'fp-status vc-err', style: 'margin:0;padding:4px 8px' }, S.status))
    ;(S.opts.actions || []).forEach(function (a) {
      var label = typeof a.label === 'function' ? a.label(it) : a.label
      var b = el('button', { class: 'btn btn-sm' + (a.ghost ? ' btn-ghost' : ''), type: 'button' }, label)
      if (a.testid) b.setAttribute('data-testid', a.testid)
      if (a.enabled && !a.enabled(it)) b.disabled = true
      b.addEventListener('click', function () {
        Promise.resolve().then(function () { return a.run(item()) }).catch(function (e) { setStatus(e && e.message ? e.message : String(e)) })
      })
      acts.appendChild(b)
    })
    if (S.download) {
      var dl = el('button', { class: 'btn btn-sm', testid: T.download, type: 'button' }, '下載')
      dl.addEventListener('click', function () { download(item()) })
      acts.appendChild(dl)
    }
    foot.appendChild(acts)
    box.appendChild(foot)
    root.appendChild(box)
  }

  function load(idx) {
    revoke()
    var it = S.items[idx]
    if (!it) return Promise.resolve()
    S.idx = idx
    S.err = ''
    S.status = ''
    S.kind = kind(it)
    var seq = ++S.seq
    if (S.kind !== 'image' && S.kind !== 'pdf') { S.loading = false; render(); return Promise.resolve() }
    S.loading = true
    render()
    var type = typeOf(it, S.kind)
    return Promise.resolve().then(function () { return S.opts.fetchBlob(it, type) }).then(function (data) { return toBlob(data, type) }).then(function (blob) {
      if (!S || S.seq !== seq) return                       // 回來時已切到別的檔或關掉了 ⇒ 丟掉這一份
      S.url = URL.createObjectURL(blob)
    }).catch(function (e) {
      if (!S || S.seq !== seq) return
      S.err = '取得附件失敗（' + (e && e.message ? e.message : e) + '）。'
    }).then(function () {
      if (!S || S.seq !== seq) return
      S.loading = false
      render()
      focusFirst(false)
    })
  }

  function step(d) {
    if (!S || !S.nav) return Promise.resolve()
    var n = S.items.length
    return load((S.idx + d + n) % n)
  }

  function download(it) {
    if (!it) return Promise.resolve()
    return Promise.resolve().then(function () { return S.opts.fetchBlob(it, 'application/octet-stream') })
      .then(function (data) { return toBlob(data, 'application/octet-stream') }).then(function (blob) {
        var url = URL.createObjectURL(blob)
        var a = document.createElement('a')
        a.href = url
        a.download = it.filename || 'attachment'
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        setTimeout(function () { URL.revokeObjectURL(url) }, 1000)
      }).catch(function (e) { setStatus('下載失敗（' + (e && e.message ? e.message : e) + '）。') })
  }

  function setStatus(text) {
    if (!S) return
    S.status = text || ''
    render()
  }

  function focusables() {
    if (!S || !S.box) return []
    return Array.prototype.slice.call(S.box.querySelectorAll('button, [href], iframe, [tabindex]:not([tabindex="-1"])'))
      .filter(function (e) { return !e.disabled && e.offsetParent !== null })
  }

  function focusFirst(force) {
    if (!S || !S.box) return
    if (!force && S.box.contains(document.activeElement)) return       // 換檔重畫時焦點還在視窗內就不搶
    var cancel = (S.opts.actions || []).filter(function (a) { return a.testid && /cancel/.test(a.testid) })[0]
    var first = (cancel && S.box.querySelector('[data-testid="' + cancel.testid + '"]')) || S.box.querySelector('[data-testid="' + ids().close + '"]')
    if (first) first.focus()
  }

  function onKey(ev) {
    if (!S) return
    if (ev.key === 'Escape') { ev.stopPropagation(); ev.preventDefault(); close(); return }
    if (ev.key === 'ArrowLeft' && S.nav) { step(-1); return }
    if (ev.key === 'ArrowRight' && S.nav) { step(1); return }
    if (ev.key === 'Tab') {
      var f = focusables()
      if (!f.length) { ev.preventDefault(); return }
      var first = f[0], last = f[f.length - 1]
      var inside = S.box.contains(document.activeElement)
      if (ev.shiftKey && (document.activeElement === first || !inside)) { ev.preventDefault(); last.focus() }
      else if (!ev.shiftKey && (document.activeElement === last || !inside)) { ev.preventDefault(); first.focus() }
    }
  }

  function close() {
    if (!S) return
    revoke()
    var s = S
    S = null
    s.seq++                                                             // 進行中的載入回來時當作已關閉
    if (s.root && s.root.parentNode) s.root.parentNode.removeChild(s.root)
    if (typeof s.opts.onClose === 'function') s.opts.onClose()
    var back = s.opener
    if (back && back.focus && document.contains(back)) setTimeout(function () { back.focus({ preventScroll: true }) }, 0)
  }

  function open(opts) {
    opts = opts || {}
    if (S) close()
    var items = (opts.items || []).slice()
    if (!items.length || typeof opts.fetchBlob !== 'function') return Promise.resolve()
    ensureStyle()
    var root = el('div', { class: 'modal-overlay', style: 'z-index:300' })
    root.style.display = 'flex'
    root.addEventListener('click', function (ev) { if (ev.target === root) close() })
    root.addEventListener('keydown', onKey)
    S = { opts: opts, items: items, idx: Math.max(0, Math.min(items.length - 1, opts.index || 0)), root: root, box: null, url: '', kind: '',
          err: '', status: '', loading: false, seq: 0, nav: opts.nav !== undefined ? !!opts.nav : items.length > 1,
          download: opts.download !== undefined ? !!opts.download : true, opener: opts.opener || document.activeElement }
    document.body.appendChild(root)
    render()
    focusFirst(true)
    return load(S.idx)
  }

  // 「另開新分頁」（出納勞報單簽回檔要保留）：window.open 必須在使用者手勢內同步呼叫，所以先開空白分頁、取到檔再導向；
  // 只有 image／pdf 才導向 blob（其餘類型分頁直接關掉、改走下載），失敗時關掉空白分頁。
  function openInNewTab(it, fetchBlob) {
    var k = kind(it)
    if (k !== 'image' && k !== 'pdf') return Promise.reject(new Error('這個類型不在瀏覽器內直接顯示，請下載後開啟'))
    var w = window.open('', '_blank')
    return Promise.resolve().then(function () { return fetchBlob(it, typeOf(it, k)) }).then(function (data) { return toBlob(data, typeOf(it, k)) }).then(function (blob) {
      var url = URL.createObjectURL(blob)
      if (w) w.location = url
      setTimeout(function () { URL.revokeObjectURL(url) }, 60000)        // 分頁載入後就不需要了；60 秒是給慢機器
    }).catch(function (e) { if (w) w.close(); throw e })
  }

  window.MotrixFilePreview = {
    open: open, close: close, refresh: function () { if (S) render() }, setStatus: setStatus,
    isOpen: function () { return !!S }, current: function () { return item() },
    kind: kind, fileSize: fileSize, withMime: withMime, openFile: openFile, byUploadsPath: byUploadsPath, openInNewTab: openInNewTab, authHeader: authHeader
  }
})()
