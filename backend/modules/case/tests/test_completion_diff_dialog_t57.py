# -*- coding: utf-8 -*-
"""完工單「從報價單重新帶入」差異視窗（第 57 班 A8 收尾）的靜態守門。行為測試（瀏覽器）列在 FOLLOWUPS：需要安靜的機器。"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SRC = (REPO / "frontend/pages/completion-note-form.html").read_text(encoding="utf-8")


def _block(start, end):
    return SRC[SRC.index(start):SRC.index(end, SRC.index(start))]


def test_reprefill_opens_the_dialog_only_when_there_are_items_and_differences():
    body = _block("async reprefill() {", "_openDiff(res) {")
    assert "if (!this.form.items.length) { this._mergeQuoteItems(res, true); return }" in body
    assert "this._openDiff(res)" in body


def test_diff_has_three_kinds_and_only_quantity_updates_start_unchecked():
    body = _block("_openDiff(res) {", "applyDiff() {")
    for kind in ("kind: 'add'", "kind: 'remove'", "kind: 'qty'"):
        assert kind in body
    assert body.count("checked: true") == 2 and body.count("checked: false") == 1          # 數量更新預設不勾（避免蓋掉現場填的數字）
    assert "this._mergeQuoteItems(res, true)" in body                                        # 沒差異 ⇒ 只更新已完工數與同步戳記


def test_apply_never_touches_unchecked_rows_and_syncs_the_fingerprint():
    body = _block("applyDiff() {", "// 畫面上顯示的標題")
    assert "if (!d.checked) continue" in body
    assert "this._quoteFp = res.fingerprint" in body                                        # 明確套用才會送出同步戳記
    assert "this.dirty = true" in body
    assert "items.filter(x => x.quoteItemId !== d.id)" in body                               # 移除只動『帶入的列』，手動新增的列沒有 quoteItemId


def test_dialog_markup_exists_and_shows_no_price_words():
    assert 'data-testid="cnf-diff-modal"' in SRC and 'data-testid="cnf-diff-apply"' in SRC
    for word in ("單價", "金額", "unitPrice", "價格"):
        assert word not in SRC, word
