# -*- coding: utf-8 -*-
"""全站守門：元件成員名不得蓋住 Object.prototype 的成員（fix/settings-center-valueof；使用者兩次回報設定中心單選沒選取、數字框空白）。

根因：元件方法叫 `valueOf` ⇒ 與 Object.prototype.valueOf 同名；Alpine 的範圍代理用 Reflect.has（含原型鏈）找名稱，x-for 範圍裡的 `valueOf(f)` 解析到繼承來的原生函式。
2026-11-14（S2）：設定中心頁已改成矩陣表外框、不再用 Alpine，原本在這個檔、綁在 `settingsCenterPage()` 上的 node 行為題（輸入元件顯示目前值、舊 bug 對照題）隨舊頁退場；
「輸入元件顯示目前值」改由 e2e（test_e2e_settings_center_shell_2026_11_14）以真實瀏覽器驗；本檔只留全站靜態守門（其他 Alpine 頁仍適用）。
"""
import re

from core import source_tree
from tests import _frontend_sources as FS


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
