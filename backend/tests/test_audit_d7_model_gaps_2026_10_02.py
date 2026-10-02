# -*- coding: utf-8 -*-
"""第 31 班設計器稽核（d7）H 組突變補洞：M2（setListed 一律 push 到尾端）與 M6（localProblems 不檢查禁用字眼）原本沒有任何題會紅。
下面兩題是會抓到它們的題（本檔隨稽核報告交給作者併入 test_form_designer_model；在未突變的樹上必須綠）。"""
import pytest

from tests.test_form_designer_model_2026_10_02 import M  # noqa: F401  （夾具）

pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.e2e


def test_setListed_inserts_after_the_nearest_shown_predecessor_not_at_the_end(M):
    d = {"fields": [{"key": k, "label": k, "type": "text"} for k in "abcd"], "ui": {"form": {"groups": []}, "list": {"columns": ["a", "d"]}}}
    out = M.call("(() => { const x = M.clone(a); M.setListed(x, 'b', true); return x.ui.list.columns })()", d)
    assert out == ["a", "b", "d"], "b 的前一個已顯示欄位是 a ⇒ 插在 a 後面、d 前面（不是接在最後）"
    out = M.call("(() => { const x = M.clone(a); M.setListed(x, 'c', true); return x.ui.list.columns })()", {**d, "ui": {"form": {"groups": []}, "list": {"columns": ["b", "d"]}}})
    assert out == ["b", "c", "d"]


def test_localProblems_flags_banned_words_in_field_names_and_column_labels(M):
    d = {"fields": [{"key": "bank_no", "label": "銀行帳號", "type": "text"}, {"key": "ok", "label": "備註", "type": "text"},
                    {"key": "lines", "label": "明細", "type": "table", "columns": [{"key": "c1", "label": "收款銀行", "type": "text"}]}]}
    out = M.call("M.localProblems(a, { bannedWords: /銀行|帳號/ }).map(p => p.path)", d)
    assert "fields[0].label" in out and "fields[2].columns[0].label" in out and "fields[1].label" not in out, out
    assert M.call("M.localProblems(a, {}).map(p => p.path)", d) == [], "沒有 caps 時不檢查禁用字眼（正對照）"
