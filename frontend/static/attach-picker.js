/* 附件挑選器（第44班；支出申請「新增申請」用，之後別的單據表單可共用）。
 *
 * 為什麼有它：原本是 <input type="file" multiple>，每次重新挑檔都會「整批取代」上一次的選擇——
 * 手機一次只能拍／挑一張，所以怎麼挑都只剩最後一個檔。這裡改成「累加」：每次挑的檔加進清單，
 * 可逐一移除，送出前先在前端擋掉不合規格的（副檔名、單檔大小、數量、一次送出合計大小）。
 * 伺服器端（helpers/uploads.py UPLOAD_LIMITS_BY_SUBFOLDER）一樣會擋，這裡只是讓人早點看到原因。
 *
 * 用法：var pk = AttachPicker.create({ peers: () => [otherPicker] })；
 *   挑檔 pk.add(fileList)；移除 pk.remove(i)；上傳用 pk.raw()（File 陣列）；上傳成功後 pk.clear()。
 *   `peers`：同一張單據的其他挑選器（例如「附件」與「發票」兩個框），數量與合計大小要一起算。
 * 純函式庫，不依賴 Alpine；回傳的物件放進 Alpine 的 data 就會有反應性。
 */
(function () {
  var MB = 1024 * 1024
  var DEFAULTS = { maxFiles: 10, maxFileBytes: 20 * MB, maxTotalBytes: 50 * MB, exts: ['.jpg', '.jpeg', '.png', '.pdf'], peers: null }
  var seq = 0

  function extOf(name) { var m = /\.[^./\\]+$/.exec(String(name || '')); return m ? m[0].toLowerCase() : '' }
  function fmtSize(n) {
    n = Number(n) || 0
    return n >= MB ? (n / MB).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB'
  }
  function isImage(name) { var e = extOf(name); return e === '.jpg' || e === '.jpeg' || e === '.png' }

  function create(opts) {
    var o = Object.assign({}, DEFAULTS, opts || {})
    return {
      files: [],            // [{ id, file, url }]（url＝圖片縮圖用的 object URL）
      err: '',
      opts: o,
      count: function () { return this.files.length },
      totalBytes: function () { return this.files.reduce(function (s, x) { return s + (x.file.size || 0) }, 0) },
      _peers: function () { return (typeof o.peers === 'function' ? o.peers() : o.peers) || [] },
      groupCount: function () { return this.count() + this._peers().reduce(function (s, p) { return s + p.count() }, 0) },
      groupBytes: function () { return this.totalBytes() + this._peers().reduce(function (s, p) { return s + p.totalBytes() }, 0) },
      accept: function () { return o.exts.join(',') },
      add: function (list) {
        var msgs = [], self = this
        Array.prototype.slice.call(list || []).forEach(function (f) {
          var name = f.name || '', ext = extOf(name)
          if (o.exts.indexOf(ext) < 0) { msgs.push('「' + name + '」格式不支援（只收 ' + o.exts.join('、').replace(/\./g, '') + '）'); return }
          if (!f.size) { msgs.push('「' + name + '」是空檔'); return }
          if (f.size > o.maxFileBytes) { msgs.push('「' + name + '」超過單檔上限 ' + Math.round(o.maxFileBytes / MB) + 'MB'); return }
          if (self.files.some(function (x) { return x.file.name === name && x.file.size === f.size && x.file.lastModified === f.lastModified })) return   // 同一個檔重複挑 ⇒ 略過
          if (self.groupCount() >= o.maxFiles) { msgs.push('最多 ' + o.maxFiles + ' 個附件，「' + name + '」未加入'); return }
          if (self.groupBytes() + f.size > o.maxTotalBytes) { msgs.push('一次送出合計最多 ' + Math.round(o.maxTotalBytes / MB) + 'MB，「' + name + '」未加入'); return }
          var url = ''
          try { if (isImage(name) && window.URL && URL.createObjectURL) url = URL.createObjectURL(f) } catch (e) { url = '' }
          self.files.push({ id: 'ap' + (++seq), file: f, url: url })
        })
        this.err = msgs.join('；')
        return this.files.length
      },
      remove: function (i) {
        var x = this.files[i]
        if (x && x.url) { try { URL.revokeObjectURL(x.url) } catch (e) { /* ignore */ } }
        this.files.splice(i, 1)
        this.err = ''
      },
      clear: function () {
        this.files.forEach(function (x) { if (x.url) { try { URL.revokeObjectURL(x.url) } catch (e) { /* ignore */ } } })
        this.files = []
        this.err = ''
      },
      raw: function () { return this.files.map(function (x) { return x.file }) },
    }
  }

  window.AttachPicker = { create: create, fmtSize: fmtSize, extOf: extOf }
})()
