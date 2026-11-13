# -*- coding: utf-8 -*-
"""S1b（SETTINGS-MATRIX-ROLLOUT）：共用核心 `settings-matrix.js` 的 C6「?」說明／C7 來源／C8 與預設不同／C11 欄頭選取／通知預覽——node 真的執行。

證明（不連瀏覽器、不連後端；假的最小 DOM，驗輸出的 HTML 字串）：
  · 全部是選填：沒給 help／source／diff／colSelect／notifyPreview 時，輸出完全沒有新標記（LINE 事件頁行為不變）。
  · 「?」只在有內容的列出現；四段順序固定、空段略過、全空不畫；內容一律跳脫（含 `<script>`／`<img onerror>`）。
  · 來源徽章只有五種；認不得的 kind 不顯示（核心不替 host 編造「個人」）；「預設：X［還原預設］」只在與預設不同時出現；canReset=false 不給還原鈕。
  · 「與預設不同」篩選晶片自動出現、篩選真的過濾；欄頭選取只出現在宣告了 colSelect 的 switch／chips 欄。
  · 預設文案沒有禁用詞（確認期間、影子、閘門、true／false）。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
JS = ROOT / "frontend" / "static" / "settings-matrix.js"
CSS = ROOT / "frontend" / "css" / "settings-matrix.css"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="需要 node")

_RT = r"""
const fs = require('fs')
global.window = global
const store = { warns: [] }
console.warn = (m) => store.warns.push(String(m))
global.document = { addEventListener() {}, removeEventListener() {}, activeElement: null, querySelectorAll() { return [] },
  createElement() { return { innerHTML: '', style: {}, appendChild() {}, addEventListener() {} } }, body: { appendChild() {} } }
eval(fs.readFileSync(process.argv[1], 'utf8'))
const SM = global.SettingsMatrix
function fakeEl() {
  const cl = new Set()
  return { innerHTML: '', classList: { add: (c) => cl.add(c), remove: (c) => cl.delete(c), toggle: (c, on) => (on ? cl.add(c) : cl.delete(c)) },
    addEventListener() {}, removeEventListener() {}, contains() { return false }, querySelector() { return null }, querySelectorAll() { return [] } }
}
function render(cfg) { const el = fakeEl(); const mx = SM.mount(el, cfg); return { html: el.innerHTML, mx, el } }
const rows = [
  { key: 'a.one', name: '甲一', group: 'G', on: true, def: true, help: { what: '這是什麼', when: '何時改', impact: '影響', recommend: '建議' }, src: { kind: 'default' } },
  { key: 'a.two', name: '乙二<img src=x onerror=alert(1)>', group: 'G', on: false, def: false, help: { what: '<script>alert(1)</script>\n第二行', when: '', impact: '', recommend: '' },
    src: { kind: 'company', by: '王經理<b>', at: '11/13', reason: '成本調整' } },
  { key: 'a.three', name: '丙三', group: 'G', on: true, def: false, help: null, src: { kind: 'pending', until: '11/20 生效' } },
  { key: 'a.four', name: '丁四', group: 'G', on: true, def: false, help: { what: '', when: '', impact: '', recommend: '' }, src: { kind: 'wat' }, noReset: true },
]
const base = () => ({ rows: rows.slice(), groups: ['G'], rowKey: (r) => r.key, rowName: (r) => r.name, rowGroup: (r) => r.group,
  columns: [{ id: 'on', type: 'switch', label: '開關', get: (r) => r.on, set: () => {} }] })
const out = %(body)s
process.stdout.write(JSON.stringify(out))
"""


def _run(body):
    p = subprocess.run([NODE, "-e", _RT % {"body": body}, str(JS)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_all_new_options_are_optional_and_leave_no_markup_behind():
    o = _run("(() => { const r = render(base()); return { html: r.html } })()")
    for needle in ('mx-help', 'data-mx="help"', 'mx-src', 'mx-dflt', 'mx-csel', 'data-mx="dreset"', 'mx-changed', '與預設不同', 'data-mx="csel"'):
        assert needle not in o["html"], needle
    assert 'data-mx="switch"' in o["html"]                                               # 既有的東西還在


def test_help_button_only_on_rows_with_content_and_sections_in_fixed_order():
    o = _run("""(() => {
      const cfg = base(); cfg.help = (r) => r.help
      const html = render(cfg).html
      return { html, count: (html.match(/data-mx="help"/g) || []).length,
        full: SM.helpHtml(rows[0].help), partial: SM.helpHtml(rows[1].help), none: SM.helpHtml(rows[3].help), nul: SM.helpHtml(null), parts: SM.helpParts(rows[0].help).map(p => p.id) } })()""")
    # 桌面表格＋手機卡片各畫一次 ⇒ 每個有內容的列出現 2 次；甲一、乙二 = 2 列 → 4
    assert o["count"] == 4
    assert 'data-mx="help" data-key="a.one"' in o["html"] and 'data-mx="help" data-key="a.two"' in o["html"]
    assert 'data-mx="help" data-key="a.three"' not in o["html"] and 'data-mx="help" data-key="a.four"' not in o["html"]   # null／全空 ⇒ 不畫
    assert o["parts"] == ["what", "when", "impact", "recommend"]
    titles = re.findall(r"<h4>([^<]+)</h4>", o["full"])
    assert titles == ["這是什麼", "什麼時候要改", "改了會影響什麼", "建議值"]
    assert o["none"] == "" and o["nul"] == ""
    assert o["partial"].count("<section") == 1 and "<script>" not in o["partial"] and "&lt;script&gt;" in o["partial"] and "<br>" in o["partial"]


def test_source_badges_exactly_five_kinds_and_unknown_kind_is_not_invented():
    o = _run("""(() => {
      const kinds = ['default', 'company', 'pending', 'legacy', 'personal'].map(k => SM.sourceInfo({ kind: k, by: '甲', at: '11/13', reason: '因', until: '11/20' }))
      const cfg = base(); cfg.source = (r) => r.src
      const html = render(cfg).html
      return { kinds, unknown: SM.sourceInfo({ kind: 'wat' }), nul: SM.sourceInfo(null), html } })()""")
    assert [k["badge"] for k in o["kinds"]] == ["預設", "公司", "等待生效", "舊位置", "個人"]
    assert o["unknown"] is None and o["nul"] is None
    assert "11/20" in o["kinds"][2]["text"] and "11/20" not in o["kinds"][1]["text"]               # 生效時間只給「等待生效」
    html = o["html"]
    assert html.count('data-testid="mx-src"') == 3 * 2                                              # 甲一、乙二、丙三有來源（丁四 kind 不認得 ⇒ 不畫）；表格＋卡片各一
    assert "來源：公司設定 · 王經理&lt;b&gt; 11/13 · 成本調整" in html and "王經理<b>" not in html
    assert ">個人<" not in html                                                                      # 這些列沒人宣告 personal ⇒ 不出現


def test_diff_mark_default_text_reset_button_and_filter():
    o = _run("""(() => {
      const cfg = base()
      cfg.diff = { isDefault: (r) => r.def, defaultText: (r) => '開啟', reset: () => {}, canReset: (r) => !r.noReset }
      const el = fakeEl(); const mx = SM.mount(el, cfg)
      const before = el.innerHTML
      mx.state().f = '__diff'; mx.setRows(rows.slice())
      return { before, filtered: el.innerHTML } })()""")
    h = o["before"]
    assert "與預設不同" in h and h.count("● 與預設不同") == 3 * 2                                     # 乙二、丙三、丁四與預設不同
    assert h.count("預設：開啟") == 3 * 2
    assert h.count('data-mx="dreset" data-key="a.two"') == 2 and h.count('data-mx="dreset" data-key="a.three"') == 2
    assert 'data-mx="dreset" data-key="a.four"' not in h                                              # canReset=false ⇒ 沒有還原鈕
    assert 'data-mx="dreset" data-key="a.one"' not in h and "mx-changed" in h                         # 等於預設的列：沒有「預設：X」也沒有還原鈕
    assert 'data-f="__diff"' in h
    f = o["filtered"]
    assert 'data-testid="mx-row-a.one"' not in f and 'data-testid="mx-row-a.two"' in f               # 篩選真的過濾掉等於預設的列


def test_untrusted_text_is_escaped_everywhere_the_new_parts_render():
    o = _run("""(() => {
      const cfg = base(); cfg.help = (r) => r.help; cfg.source = (r) => r.src
      cfg.diff = { isDefault: (r) => r.def, defaultText: () => '<script>x</script>', reset: () => {} }
      return render(cfg).html })()""")
    assert "<img src=x" not in o and "<script>" not in o and "王經理<b>" not in o
    assert "&lt;img src=x onerror=alert(1)&gt;" in o and "預設：&lt;script&gt;x&lt;/script&gt;" in o


def test_column_header_select_only_on_declared_switch_and_chips_columns():
    o = _run("""(() => {
      const cfg = base()
      cfg.columns = [
        { id: 'on', type: 'switch', label: '開關', get: (r) => r.on, set: () => {}, colSelect: { draft: () => ({}) } },
        { id: 'plain', type: 'switch', label: '另一欄', get: (r) => r.on, set: () => {} },
        { id: 'roles', type: 'chips', label: '角色', items: [{ value: 'a', label: '甲', short: '甲' }, { value: 'b', label: '乙' }], get: () => ['a'], toggle: () => {}, colSelect: { run: () => {} } },
        { id: 'sel', type: 'select', label: '選項', options: [{ value: '1', label: '一' }], get: () => '1', set: () => {}, colSelect: { run: () => {} } },
      ]
      const html = render(cfg).html
      const head = html.split('<tbody>')[0]
      return { head } })()""")
    h = o["head"]
    assert h.count('data-mx="csel"') == 3                                                             # switch×1＋chips 兩個項目；select 型不支援 ⇒ 不畫
    assert 'data-mx="csel" data-col="on"' in h and 'data-col="roles" data-val="a"' in h and 'data-col="roles" data-val="b"' in h
    assert 'data-col="plain"' not in h and 'data-col="sel"' not in h
    assert "整欄選取：開關" in h and "整欄選取：乙" in h


def test_default_labels_have_no_banned_words():
    o = _run("(() => ({ labels: SM.defaultLabels }))()")
    banned = re.compile(r"確認期間|影子|閘門|\btrue\b|\bfalse\b", re.I)
    bad = {k: v for k, v in o["labels"].items() if banned.search(str(v))}
    assert bad == {}
    for k in ("help", "helpWhat", "helpWhen", "helpImpact", "helpRecommend", "srcDefault", "srcCompany", "srcPending", "srcLegacy", "srcPersonal",
              "diffTag", "diffDefault", "diffReset", "colSelAria", "previewTitle"):
        assert k in o["labels"], k


def test_css_has_the_new_classes_and_only_uses_existing_tokens():
    css = CSS.read_text(encoding="utf-8")
    for cls in (".mx-help", ".mx-src", ".mx-dflt", ".mx-changed", ".mx-csel", ".mx-preview", ".mx-help-sec"):
        assert cls in css, cls
    tokens = set(re.findall(r"var\((--[\w-]+)", css))
    base_css = (ROOT / "frontend" / "css" / "style.css").read_text(encoding="utf-8")
    missing = sorted(t for t in tokens if t not in ("--fz", "--topbar-h") and (t + ":") not in base_css)
    assert missing == [], missing


def test_notify_preview_and_reset_paths_exist_in_source_and_go_through_confirm_and_perform():
    """互動路徑（點「?」開窗、還原預設、欄頭整欄、確認視窗的通知預覽）需要真的 DOM——e2e 在 S2 外框票一起補；這裡先鎖住接線：不得繞過既有的確認／寫入流程。"""
    src = JS.read_text(encoding="utf-8")
    assert "withPreview(dialogs, { kind: a.previewKind || 'batch'" in src and "withPreview(dialogs || [], { kind: 'draft'" in src      # 批次與草稿儲存都過預覽
    assert "perform(rn(r) + '：' + T('diffReset'), [key]" in src and "stageCell(key, function () { return DF.draft(r) })" in src      # 還原預設：立即＝perform、草稿＝併入草稿
    assert "runAction({ id: 'colsel:'" in src and "cs.draft(rowByKey(k), on, val)" in src                                           # 欄頭整欄：立即＝走批次流程（確認／略過／復原）、草稿＝逐列併入
    assert re.search(r"function colTargets\(c\) \{\s*return visKeys\(\)\.filter\(function \(k\) \{ var r = rowByKey\(k\); return r && eligibleOf\(r\)\.ok && colShown\(c, r\) && !locked\(c, r\) \}\)", src)
    # h9 review M1／N2：整欄選取取消確認後要重畫（原生核取方塊回原狀）；草稿頁絕不直接寫入
    assert "targets).then(function () { render() })" in src
    assert "if (D || !cs.run) { render(); return Promise.resolve() }" in src
    assert "if (D) return DF.draft ? stageCell(key, function () { return DF.draft(r) }) : Promise.resolve()" in src
    assert "withPreview(dialogs, { kind: 'reset', keys: [key] })" in src                          # N1：還原預設也過通知預覽
