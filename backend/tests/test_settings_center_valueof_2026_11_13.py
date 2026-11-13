# -*- coding: utf-8 -*-
"""設定中心輸入元件顯示目前值（fix/settings-center-valueof；使用者兩次回報：單選沒有選取、數字輸入框是空的，但旁邊寫「目前：…」）。

根因：元件方法叫 `valueOf` ⇒ 與 Object.prototype.valueOf 同名。Alpine 的範圍代理用 Reflect.has（含原型鏈）找名稱，
x-for 迴圈範圍裡的 `valueOf(f)` 解析到繼承來的原生函式，回傳範圍物件 ⇒ 所有輸入元件拿不到目前值。改名 `curVal`。
這裡以 node 在「與 Alpine 同樣的範圍代理」下求值頁面上真正的綁定式：int／float／str／選項（數字碼、字串碼）／bool 各一個「顯示目前值」的題目，
含舊 bug 的對照題（證明題目抓得到）與全站守門（元件方法名不得蓋住 Object.prototype 的成員）。
"""
import json
import os
import re
import shutil
import subprocess

import pytest

from core import source_tree
from tests import _frontend_sources as FS

# 頁面位置一律經 core.source_tree（頁面可能住在模組的 pages/ 底下）；JS 列舉一律經 tests/_frontend_sources
PAGE = str(source_tree.page_file("settings-center.html"))


NODE = shutil.which("node")


def _need_node():
    """前端行為題要 node。列車／出貨閘門（`MOTRIX_TRAIN=1`）下找不到 node ⇒ **紅**（不是略過：略過會讓這個 bug 在沒 node 的機器上悄悄出貨）；
    一般開發機沒有 node ⇒ 略過並說明。"""
    if NODE:
        return
    if os.environ.get("MOTRIX_TRAIN") == "1":
        pytest.fail("MOTRIX_TRAIN=1 但找不到 node：設定中心前端行為題不能略過（請安裝 node，或讓閘門機的 PATH 找得到 node）")
    pytest.skip("沒有 node，前端行為題略過（一般開發機；列車閘門下會紅）")

_HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const html = fs.readFileSync(input.page, 'utf8');
const at = html.indexOf('function settingsCenterPage'); const m = [null, html.slice(html.lastIndexOf('<script>', at) + 8, html.indexOf('</script>', at))];
const listeners = {};
const sandbox = { window: { addEventListener: (n, fn) => { listeners[n] = fn } }, localStorage: { getItem: () => null }, location: { hash: '' },
                  document: {}, fetch: async () => { throw new Error('no network') }, setTimeout, clearTimeout, console };
vm.createContext(sandbox);
vm.runInContext(m[1] + '\n;this.__page = settingsCenterPage;', sandbox);
// Alpine 3.17.1 的範圍代理（原樣照抄 alpine-3.17.1.min.js 的 pi）：has／get 用 Reflect.has（含原型鏈）
const pi = {
  has({ objects }, t) { return t == Symbol.unscopables ? false : objects.some(r => Object.prototype.hasOwnProperty.call(r, t) || Reflect.has(r, t)) },
  get({ objects }, t, r) { return t == 'toJSON' ? (() => {}) : Reflect.get(objects.find(n => Reflect.has(n, t)) || {}, t, r) },
  set({ objects }, t, v) { const o = objects.find(n => Reflect.has(n, t)) || objects[objects.length - 1]; o[t] = v; return true },
};
const out = [];
for (const c of input.cases) {
  const comp = sandbox.__page();
  Object.assign(comp, c.state || {});
  if (c.call) {
    let prevented = 0, e = { preventDefault() { prevented++ }, returnValue: 'unset' };
    if (c.call === 'init') {
      comp.loadGroups = async () => {}; comp.pick = async () => {}; comp.groups = [];
      comp.init().then(() => {
        const ev = { preventDefault() { prevented++ }, returnValue: 'unset' };
        listeners.beforeunload && listeners.beforeunload(ev);
        out.push({ registered: !!listeners.beforeunload, prevented, rv: ev.returnValue });
      });
      continue;
    }
    if (c.call === 'leaveGuard') { const r = comp.leaveGuard(e); out.push({ r: r === undefined ? null : r, prevented, rv: e.returnValue }); continue }
    if (c.call === 'saveSummary') { out.push(comp.saveSummary(c.arg)); continue }
  }
  const scope = new Proxy({ objects: [{ f: c.f, c: c.c }, comp] }, pi);
  const fn = new Function('scope', 'with (scope) { return (' + c.expr + ') }');
  let v;
  try { v = fn(scope) } catch (err) { v = '__ERR__' + err.message }
  out.push({ v: (v !== null && typeof v === 'object') ? '__OBJECT__' : v });
}
setTimeout(() => process.stdout.write(JSON.stringify(out)), 50);
"""


def _run_node(tmp_path, cases):
    h = tmp_path / "harness.js"
    h.write_text(_HARNESS, encoding="utf-8")
    inp = tmp_path / "in.json"
    inp.write_text(json.dumps({"page": PAGE, "cases": cases}, ensure_ascii=False), encoding="utf-8")
    p = subprocess.run([NODE, str(h), str(inp)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def _html():
    return open(PAGE, encoding="utf-8").read()


def _line(marker):
    for ln in _html().splitlines():
        if marker in ln:
            return ln
    raise AssertionError("頁面上找不到：" + marker)


def _expr(marker, attr):
    m = re.search(r'%s="([^"]+)"' % re.escape(attr), _line(marker))
    assert m, (marker, attr)
    return m.group(1).replace("&amp;", "&")


def _field(key, typ, value, **kw):
    f = {"key": key, "type": typ, "value": value, "default": value, "choices": [], "recommended": None}
    f.update(kw)
    return f


CHOICES_INT = [{"value": 0, "label": "關閉（預設）"}, {"value": 1, "label": "影子"}, {"value": 2, "label": "開啟"}]
CHOICES_STR = [{"value": "a", "label": "甲"}, {"value": "b", "label": "乙"}]


def test_every_input_type_shows_the_current_effective_value_under_alpines_scope_proxy(tmp_path):
    _need_node()
    radio_checked = _expr("'sc-choice-' + f.key", ":checked")
    radio_cls = re.search(r"'is-on': ([^}]+)\}", _line('class="sc-choice"')).group(1)
    num_value = _expr("'sc-input-' + f.key", ":value")
    bool_checked = _expr("'sc-bool-' + f.key", ":checked")
    text_value = _expr("'sc-text-' + f.key", ":value")
    cases, expect = [], []

    def add(expr, f, c, want, drafts=None):
        cases.append({"expr": expr, "f": f, "c": c, "state": {"drafts": drafts or {}}})
        expect.append(want)

    # 選項型：數字碼（使用者回報的 reconfirm_mode：目前 2＝開啟 ⇒ 只有「開啟」被選取）
    f = _field("reconfirm_mode", "int", 2, choices=CHOICES_INT)
    for c in CHOICES_INT:
        add(radio_checked, f, c, c["value"] == 2)
        add(radio_cls, f, c, c["value"] == 2)
    add(radio_checked, f, CHOICES_INT[0], True, drafts={"reconfirm_mode": 0})            # 草稿覆蓋目前值
    add(radio_checked, f, CHOICES_INT[2], False, drafts={"reconfirm_mode": 0})
    add(radio_checked, _field("m", "int", 0, choices=CHOICES_INT), CHOICES_INT[0], True)  # 代碼 0 也要能選取（假值）
    # 選項型：字串碼；伺服器給數字、選項給字串（或反過來）也要選得到
    fs = _field("s", "str", "b", choices=CHOICES_STR)
    for c in CHOICES_STR:
        add(radio_checked, fs, c, c["value"] == "b")
    add(radio_checked, _field("mix", "int", 1, choices=[{"value": "1", "label": "一"}]), {"value": "1", "label": "一"}, True)
    # 數字型 int／float（使用者回報的 confirm_period_days：目前 7 ⇒ 輸入框顯示 7）
    add(num_value, _field("confirm_period_days", "int", 7), None, 7)
    add(num_value, _field("pct", "float", 1.5), None, 1.5)
    add(num_value, _field("zero", "int", 0), None, 0)
    add(num_value, _field("confirm_period_days", "int", 7), None, 9, drafts={"confirm_period_days": 9})
    # 開關型
    add(bool_checked, _field("on", "bool", True), None, True)
    add(bool_checked, _field("off", "bool", False), None, False)
    add(bool_checked, _field("on", "bool", True), None, False, drafts={"on": False})
    # 文字型
    add(text_value, _field("name", "str", "abc"), None, "abc")
    add(text_value, _field("name", "str", "abc"), None, "xyz", drafts={"name": "xyz"})
    got = [r["v"] for r in _run_node(tmp_path, cases)]
    assert got == expect


def test_harness_reproduces_the_original_bug_valueof_resolves_to_object_prototype(tmp_path):
    """對照：舊的 `valueOf(f)` 在 x-for 範圍代理下拿到的是範圍物件（不是值）。這題證明上面的題目真的抓得到那個 bug。"""
    _need_node()
    got = _run_node(tmp_path, [{"expr": "valueOf(f)", "f": _field("k", "int", 7), "c": None, "state": {}}])
    assert got[0]["v"] == "__OBJECT__"


# Object.prototype 的成員（含舊式 __define*__／__lookup*__）：元件上同名的成員會被 Alpine 範圍代理的 Reflect.has（含原型鏈）搶先解析
_PROTO = "valueOf|toString|toLocaleString|hasOwnProperty|isPrototypeOf|propertyIsEnumerable|constructor|__proto__|__defineGetter__|__defineSetter__|__lookupGetter__|__lookupSetter__"
# 已知沒抓的寫法（靜態 regex 的限制，h5 審查列出）：`valueOf: curVal,`（值是函式參照）、`this.valueOf = function…`（init 內指派）、計算鍵 `['valueOf'](f) {`、
# `static valueOf()`、`a: 1, valueOf(f) {`（不在行首）、預設參數含巢狀括號、`Object.defineProperty(c, 'valueOf', …)`。真的遇到再補；行為題（上面）會抓到實際壞掉的頁面。
_BAD_MEMBER = re.compile(
    r"^\s*(?:(?:async\s+)?\*?\s*|(?:get|set)\s+)['\"]?(?:%(p)s)['\"]?\s*\([^)]*\)\s*\{"                                # 方法簡寫、async／generator、get／set 存取子
    r"|^\s*['\"]?(?:%(p)s)['\"]?\s*:\s*(?:async\s+)?(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)"                # name: function／async function／箭頭函式（含單參數）
    % {"p": _PROTO}, re.M)


def test_member_name_guard_catches_every_way_of_defining_a_shadowing_member_and_spares_normal_names():
    """守門自己的正對照（守門不能只在「沒東西」時綠）：每一種定義寫法都抓得到；正常名稱不誤報。"""
    bad = ["    valueOf(f) { return 1 },", "    async toString() {", "    *hasOwnProperty() {", "    get constructor() { return 1 },", "    set valueOf(v) {",
           "    valueOf: function (f) { return 1 },", "    valueOf: async function () {}", "    toString: (a, b) => a,", "    toString: x => x,", "    valueOf: async (f) => 1,",
           "    'valueOf': function () {},", '    "toString"(f) {', "    __defineGetter__(n, fn) {", "    __lookupSetter__: function (n) {}", "    get __lookupGetter__() {",
           "    isPrototypeOf: () => 1,", "    propertyIsEnumerable(k) {"]
    good = ["    curVal(f) { return 1 },", "    valueOfX(f) {", "    myToString() {", "    constructorName: function () {}", "    x.valueOf()", "    return valueOf(f)",
            "    total: 5,", "    valueOf: 5,", "    // valueOf(f) { 說明文字 }", "    getValue() {", "    gettoString() {"]
    missed = [x for x in bad if not _BAD_MEMBER.search(x)]
    flagged = [x for x in good if _BAD_MEMBER.search(x)]
    assert missed == [] and flagged == []


def test_no_alpine_component_method_shadows_an_object_prototype_member():
    """全站守門：x-data 元件的成員名不能是 Object.prototype 的成員（valueOf／toString…）：Alpine 的範圍代理會解析到繼承來的原生函式。
    抓：方法簡寫（含 async／generator）、get／set 存取子、`name: function`／箭頭函式、帶引號的鍵、`__define*__`／`__lookup*__`。"""
    hits = []
    scanned = 0
    for p in list(source_tree.page_files()) + list(FS.all_js()):
        src = open(p, encoding="utf-8", errors="ignore").read()
        scanned += 1
        hits += ["%s:%s" % (FS.js_rel(p) if p.suffix == ".js" else p.name, m.group(0).strip()[:60]) for m in _BAD_MEMBER.finditer(src)]
    assert scanned > 50, "掃到的檔太少，列舉入口可能壞了"
    assert hits == []
