# -*- coding: utf-8 -*-
"""T66：「複製為新報價單」後，報價單表單的拖曳排序不可失效。

根因：quotation-form.html 的 init() 複製分支在中途 `return`，漏掉尾巴那段
（預覽 $watch、預覽高度 message 監聽、nextTick(initSortable)）。
修法：尾巴抽成 `_bindLateHooks()`，複製分支與一般尾巴都呼叫；可重複呼叫、不重複綁定。

1. 複製分支在 return 之前呼叫 `_bindLateHooks()`；一般尾巴也呼叫。
2. `_bindLateHooks()` 內含 previewMode $watch、message 監聽（有「只綁一次」旗標）、nextTick(initSortable)；
   這三件事不得再以內聯形式散在 init() 其他位置。
3. `initSortable()` 重建前先銷毀舊的 `_sortable`，$watch 只登記一次。
4. 複製出來的單一定是草稿（拖曳排序只在 status='已送出' 且未解鎖時鎖定）；
   兩個複製範本建構處（表單的 copyToNew、清單的 duplicateQuote）都設 status:'草稿'，複製分支再保險一次。
"""
import re

from core import source_tree

FORM = source_tree.page_file("quotation-form.html").read_text(encoding="utf-8")
LIST = source_tree.page_file("quotations.html").read_text(encoding="utf-8")


def _block(src, start_pat, end_pat):
    m = re.search(start_pat, src)
    assert m, start_pat
    e = re.search(end_pat, src[m.end():])
    assert e, end_pat
    return src[m.start(): m.end() + e.start()]


def _init_body():
    return _block(FORM, r"\n\s*async init\(\)\s*\{", r"\n      _bindLateHooks\(\)\s*\{")


def test_copy_branch_binds_late_hooks_before_returning():
    init = _init_body()
    copy = _block(init, r"if \(matches\) \{", r"\n\s*\}\n\s*\} catch")
    assert "this._bindLateHooks()" in copy
    assert copy.index("this._bindLateHooks()") < copy.index("return"), "要在 return 之前綁"


def test_normal_tail_calls_the_same_helper_and_nothing_is_inlined_in_init():
    init = _init_body()
    assert init.count("this._bindLateHooks()") == 2, "複製分支與一般尾巴各一次"
    for inline in ("$watch('previewMode'", "addEventListener('message'", "this.initSortable()"):
        assert inline not in init, "%s 不可內聯在 init()（會讓複製分支再次漏綁）" % inline


def test_helper_is_idempotent():
    helper = _block(FORM, r"\n      _bindLateHooks\(\)\s*\{", r"\n      initSortable\(\)\s*\{")
    assert "$watch('previewMode'" in helper and "addEventListener('message'" in helper
    assert "$nextTick(() => this.initSortable())" in helper
    assert re.search(r"if \(!this\._previewHooksBound\)\s*\{\s*this\._previewHooksBound = true", helper)
    assert FORM.count("addEventListener('message'") == 1, "預覽高度監聽全頁只能在 helper 綁一次"


def test_init_sortable_rebuilds_cleanly():
    sortable = _block(FORM, r"\n      initSortable\(\)\s*\{", r"\n      logout\(\)\s*\{")
    assert re.search(r"if \(this\._sortable\)\s*\{[^}]*\.destroy\(\)", sortable)
    assert sortable.index(".destroy()") < sortable.index("Sortable.create(")
    assert re.search(r"if \(!this\._sortableWatched\)\s*\{\s*this\._sortableWatched = true", sortable)
    assert sortable.count("this.$watch(") == 2


def test_copied_quote_starts_as_draft_and_unlocked():
    assert re.search(r"const template = \{[^}]*status: '草稿'", FORM, re.S), "表單 copyToNew"
    assert re.search(r"const template = \{[^}]*status: '草稿'", LIST, re.S), "清單 duplicateQuote"
    init = _init_body()
    copy = _block(init, r"if \(matches\) \{", r"\n\s*\}\n\s*\} catch")
    assert "this.unlocked = false" in copy
    assert re.search(r"this\.q\.status === '已送出'\) this\.q\.status = '草稿'", copy)
