// 下載檔名的前端單一入口（A7 第一期；設計 DOWNLOAD-FILENAME-CASE-T56.md r6 §2.3）。
// 為什麼需要：頁面用 fetch（帶 Bearer）→ blob → <a download> 下載，這條路上瀏覽器不會看回應標頭，
// 檔名只能由這裡指定；後端 helpers/download_name.py 是檔名的唯一來源，這裡只負責「讀回應的 Content-Disposition」。
// 用法：
//   var name = MotrixDownload.nameFrom(resp, 'fallback.pdf')        // 預覽時先取名，之後 a.download = name
//   await MotrixDownload.save(resp, 'fallback.pdf')                  // 取 blob 並下載
//   MotrixDownload.saveBlob(blob, name)
// 規則：filename*（RFC 8187，只認 UTF-8）優先；其次 filename="…"；都沒有才用 fallback。名稱再淨化一次（去路徑分隔符與控制字元）。
(function () {
  function decodeStar(v) {
    // 例：UTF-8''%E5%AE%8C%E5%B7%A5%E5%96%AE.pdf
    var q = /^([A-Za-z0-9._-]+)'[^']*'(.*)$/.exec(v)
    if (!q || q[1].toUpperCase() !== 'UTF-8') return ''
    try { return decodeURIComponent(q[2]) } catch (e) { return '' }
  }

  function parseDisposition(header) {
    if (!header) return ''
    var star = /filename\*\s*=\s*([^;]+)/i.exec(header)
    if (star) {
      var s = decodeStar(star[1].trim().replace(/^"|"$/g, ''))
      if (s) return s
    }
    var quoted = /(?:^|[;\s])filename\s*=\s*"((?:[^"\\]|\\.)*)"/i.exec(header)
    if (quoted) return quoted[1].replace(/\\(.)/g, '$1')
    var bare = /(?:^|[;\s])filename\s*=\s*([^;]+)/i.exec(header)
    return bare ? bare[1].trim() : ''
  }

  function cleanName(name) {
    // 去路徑分隔符與控制字元；空白合一；去前後空白與結尾的點
    var s = String(name == null ? '' : name).replace(/[\\/\u0000-\u001f\u007f]/g, '_').replace(/\s+/g, ' ').trim()
    return s.replace(/[. ]+$/, '')
  }

  function nameFrom(response, fallback) {
    // 永不丟例外：標頭解析失敗就用 fallback（下載不能因為取名而失敗）
    try {
      var h = response && response.headers && response.headers.get ? response.headers.get('Content-Disposition') : ''
      var n = cleanName(parseDisposition(h))
      if (n) return n
    } catch (e) { /* fall through */ }
    return cleanName(fallback) || 'download'
  }

  function saveBlob(blob, name) {
    var url = URL.createObjectURL(blob)
    var a = document.createElement('a')
    a.href = url
    a.download = cleanName(name) || 'download'
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(function () { URL.revokeObjectURL(url) }, 1000)
  }

  async function save(response, fallback) {
    var name = nameFrom(response, fallback)
    saveBlob(await response.blob(), name)
    return name
  }

  var api = { parseDisposition: parseDisposition, cleanName: cleanName, nameFrom: nameFrom, saveBlob: saveBlob, save: save }
  if (typeof window !== 'undefined') window.MotrixDownload = api
  if (typeof module !== 'undefined' && module.exports) module.exports = api
})()
