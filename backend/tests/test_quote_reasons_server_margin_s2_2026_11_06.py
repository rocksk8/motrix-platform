# -*- coding: utf-8 -*-
"""S2（報價單簽核二擇一提案）：伺服器自己算品項毛利、原因集合比對。純函式，不碰資料庫（門檻用 monkeypatch 固定）。

- `server_item_margin(cost, unitPrice)`：只吃成本與單價；誠實資料與前端 `parseFloat((1 − cost×1.05/unitPrice).toFixed(4))` 逐位相同
- `with_server_margins` 不改傳入的資料、不信品項上的 `margin`
- `compute_approval_reason_entries` 的文字與順序逐字同 `compute_approval_reasons`（重構不改語意）
- `diff_reason_entries`：新增／消失／同鍵異文／不變；品項以 id 為鍵（插入、換位置不誤報）
"""
import copy
import itertools

import pytest

from modules.case import quote_terms as QT


@pytest.fixture(autouse=True)
def fixed_thresholds(monkeypatch):
    monkeypatch.setattr(QT, "min_item_margin_pct", lambda: 30.0)
    monkeypatch.setattr(QT, "max_valid_days", lambda: 30)
    monkeypatch.setattr(QT, "discount_review_above", lambda: 0)
    monkeypatch.setattr(QT, "load_terms_settings", lambda: ([], QT.DEFAULT_TERMS["paymentTerms"]))


def _q(items, **over):
    d = {"validDays": 30, "taxRate": 5, "items": items}
    d.update(QT.DEFAULT_TERMS)
    d.update(over)
    return d


def _it(id_, cost, price, margin, **kw):
    return dict({"id": id_, "type": "item", "qty": 1, "cost": cost, "unitPrice": price, "margin": margin}, **kw)


# ── server_item_margin ────────────────────────────────────────────────────────

@pytest.mark.parametrize("cost,price,want", [
    (700, 1000, 0.265),
    (1000, 1500, 0.3),            # 1 − 1050/1500 = 0.3 剛好
    (100, 150, 0.3),
    (900, 1000, 0.055),
    (100, 100, -0.05),            # 賠本
    (1000, 10, -104.0),           # 負很多也不截斷
    ("700", "1000", 0.265),       # 字串數字（JS Number() 語意）
])
def test_server_margin_values(cost, price, want):
    assert QT.server_item_margin(cost, price) == pytest.approx(want, abs=1e-9)


def test_server_margin_rounds_to_4_decimals_like_the_frontend():
    # 1 − 100×1.05/150.01 = 0.30004… ⇒ 前端 toFixed(4)＝0.3000，不能被判成「低於 30%」
    v = QT.server_item_margin(100, 150.01)
    assert v == 0.3
    # 1 − 100×1.05/149.99 = 0.29995… ⇒ 0.3000（四捨五入）；再低一點才真的低於
    assert QT.server_item_margin(100, 149.99) == 0.3
    assert QT.server_item_margin(100, 149.9) == 0.2995


@pytest.mark.parametrize("cost", [0, -5, None, "", "abc", float("nan"), False])
def test_no_cost_means_no_margin_concept(cost):
    assert QT.server_item_margin(cost, 1000) is None


@pytest.mark.parametrize("price", [-1, None, "", "abc", float("nan"), False])
def test_cost_without_valid_price_is_minus_100_percent(price):
    assert QT.server_item_margin(100, price) == QT.NO_PRICE_MARGIN == -1.0


@pytest.mark.parametrize("price", [0, 0.0, "0", " 0 "])
def test_gift_with_explicit_zero_price_is_not_judged(price):
    """贈品（成本>0、單價明確 0）＝今天的行為：不列毛利原因 ⇒ None。"""
    assert QT.server_item_margin(100, price) is None


def test_gift_not_listed_even_with_forged_low_client_margin_and_nogift_forged_high_still_caught(monkeypatch):
    gift = _q([_it(1, 100, 0, 0.0)])                     # 贈品，用戶端 margin 寫 0
    assert QT.server_reason_entries(gift, [], "") == []
    assert QT.with_server_margins(gift)["items"][0]["margin"] == QT.GIFT_MARGIN
    nogift = _q([{"id": 1, "cost": 100, "margin": 0.99}])   # 不送單價（不是明確 0）仍被抓
    assert [e["key"] for e in QT.server_reason_entries(nogift, [], "")] == ["margin:id:1"]
    # 嚴格門檻 100%：贈品（1.0）也不被列（今天 margin=100% 的贈品同樣不列）
    monkeypatch.setattr(QT, "min_item_margin_pct", lambda: 100.0)
    assert QT.server_reason_entries(gift, [], "") == []


def test_server_margin_signature_has_no_client_margin_input():
    import inspect
    assert list(inspect.signature(QT.server_item_margin).parameters) == ["cost", "unit_price"]


# ── with_server_margins ──────────────────────────────────────────────────────

def test_forged_margin_is_replaced_and_original_untouched():
    q = _q([{"type": "header", "description": "區段"}, _it(1, 900, 1000, 0.9), _it(2, 0, 50, 0.01), _it(3, 100, 0, 0.0)])
    before = copy.deepcopy(q)
    out = QT.with_server_margins(q)
    assert q == before, "不改傳入的資料（存進 data_json 的仍是用戶端欄位）"
    assert out["items"][1]["margin"] == 0.055
    assert out["items"][0] == q["items"][0], "區段標題不動"
    assert out["items"][2]["margin"] == 0.01, "沒成本的品項不動（本來就不判毛利）"
    assert out["items"][3]["margin"] == QT.GIFT_MARGIN, "贈品不信用戶端 margin"


def test_with_server_margins_tolerates_garbage():
    assert QT.with_server_margins({"items": None}) == {"items": None}
    assert QT.with_server_margins({"items": ["x", None, 3]})["items"] == ["x", None, 3]
    assert QT.with_server_margins({}) == {}


# ── 原因：偽造 margin 擋得住 ─────────────────────────────────────────────────

def test_forged_margin_with_real_low_price_is_listed():
    q = _q([_it(7, 900, 1000, 0.9)])                    # 前端欄位說 90%，實際單價只有 5.5%
    assert QT.compute_approval_reasons(q, [], "") == [], "（舊路徑：信 margin 欄位 ⇒ 看不到＝T62 缺口）"
    got = [e["text"] for e in QT.server_reason_entries(q, [], "")]
    assert got == ["第 1 項毛利率 5.50% 低於 30%"]


def test_honest_item_not_listed_and_omitted_unit_price_does_not_hide_it():
    ok = _q([_it(1, 700, 1500, 0.99)])                  # 1 − 735/1500 = 51%
    assert QT.server_reason_entries(ok, [], "") == []
    hidden = _q([{"id": 1, "cost": 700, "margin": 0.99}])   # 不送 unitPrice 想躲過重算 ⇒ 視為無單價
    assert [e["text"] for e in QT.server_reason_entries(hidden, [], "")] == ["第 1 項毛利率 -100.00% 低於 30%"]


# ── entries 與 compute_approval_reasons 逐字相同 ─────────────────────────────

_VARIANTS = [
    {}, {"validDays": 60}, {"showDiscount": True, "discount": 12345.5}, {"taxRate": 0, "taxType": "zero", "taxBasis": {"code": "7-1", "note": ""}},
    {"deliveryTerms": "改過"}, {"paymentTerms": "改過", "warrantyTerms": "改過2"},
]


@pytest.mark.parametrize("over,margin", list(itertools.product(_VARIANTS, [0.1, 0.3, 0.5, None, "0.2"])))
def test_entries_text_equals_legacy_reasons(over, margin):
    q = _q([{"type": "header"}, _it(1, 100, 150, margin), _it(2, 50, 90, 0.5)], **over)
    ents = QT.compute_approval_reason_entries(q, [], "")
    assert [e["text"] for e in ents] == QT.compute_approval_reasons(q, [], "")
    assert len({e["key"] for e in ents}) == len(ents), "鍵不重複"


def test_entry_keys():
    q = _q([{"type": "header"}, _it(7, 100, 100, 0.1), {"cost": 10, "margin": 0.1}],
           validDays=90, showDiscount=True, discount=5, deliveryTerms="x")
    keys = [e["key"] for e in QT.compute_approval_reason_entries(q, [], "")]
    assert keys == ["validDays", "margin:id:7", "margin:idx:2", "discount", "terms"]


def test_duplicate_ids_fall_back_to_index():
    q = _q([_it(1, 100, 100, 0.1), _it(1, 100, 100, 0.1)])
    assert [e["key"] for e in QT.compute_approval_reason_entries(q, [], "")] == ["margin:idx:0", "margin:idx:1"]


# ── diff ─────────────────────────────────────────────────────────────────────

def _e(k, t=None):
    return {"key": k, "text": t or k}


def test_diff_added_removed_changed_unchanged():
    old = [_e("validDays", "有效期限 60 天"), _e("margin:id:1", "第 1 項 20.00%"), _e("discount", "含折讓 5")]
    new = [_e("margin:id:1", "第 1 項 25.00%"), _e("discount", "含折讓 5"), _e("terms", "條件改過")]
    d = QT.diff_reason_entries(old, new)
    assert d["added"] == [_e("terms", "條件改過")]
    assert d["removed"] == [_e("validDays", "有效期限 60 天")]
    assert d["changed"] == [{"key": "margin:id:1", "before": "第 1 項 20.00%", "after": "第 1 項 25.00%"}]
    assert d["unchanged"] == [_e("discount", "含折讓 5")]


def test_diff_identical_and_empty_and_none():
    x = [_e("a"), _e("b")]
    d = QT.diff_reason_entries(x, x)
    assert d["added"] == d["removed"] == d["changed"] == [] and len(d["unchanged"]) == 2
    d = QT.diff_reason_entries([], x)
    assert len(d["added"]) == 2 and not d["removed"]
    d = QT.diff_reason_entries(x, None)
    assert len(d["removed"]) == 2 and not d["added"]
    assert QT.diff_reason_entries(None, None) == {"added": [], "removed": [], "changed": [], "unchanged": []}


def test_diff_accepts_plain_strings():
    d = QT.diff_reason_entries(["a", "b"], ["b", "c"])
    assert [e["key"] for e in d["added"]] == ["c"] and [e["key"] for e in d["removed"]] == ["a"]


def test_diff_end_to_end_on_edited_quote():
    base = _q([_it(1, 700, 1500, 0.5), _it(2, 100, 400, 0.7)])
    old = QT.current_reason_entries(base)
    assert old == []
    edited = copy.deepcopy(base)
    edited["items"][0]["unitPrice"] = 800            # 品項 1 被改價 ⇒ 1 − 735/800 = 8.1%
    edited["validDays"] = 90
    new = QT.current_reason_entries(edited)
    d = QT.diff_reason_entries(old, new)
    assert [e["key"] for e in d["added"]] == ["validDays", "margin:id:1"]
    assert not d["removed"] and not d["changed"]
    # 再改回來 ⇒ 兩條都消失
    d2 = QT.diff_reason_entries(new, QT.current_reason_entries(base))
    assert [e["key"] for e in d2["removed"]] == ["validDays", "margin:id:1"] and not d2["added"]


def test_diff_item_insert_does_not_misreport_when_ids_present():
    a = _q([_it(1, 100, 100, 0.1), _it(2, 100, 100, 0.1)])
    b = copy.deepcopy(a)
    b["items"].insert(0, _it(3, 100, 1000, 0.9))     # 前面插一個正常品項 ⇒ 項次全部位移，id 鍵不變
    d = QT.diff_reason_entries(QT.current_reason_entries(a), QT.current_reason_entries(b))
    assert not d["added"] and not d["removed"]
    assert [x["key"] for x in d["changed"]] == ["margin:id:1", "margin:id:2"], "只有『第 N 項』文字因位置改變，列為 changed，不是新增／消失"


def test_current_reason_entries_is_pure():
    q = _q([_it(1, 900, 1000, 0.9)], approval={"status": "pending", "reasons": ["舊"]})
    before = copy.deepcopy(q)
    QT.current_reason_entries(q)
    QT.current_reason_entries(q)
    assert q == before


# ── category_summary ─────────────────────────────────────────────────────────

def _m(key, margin):
    return {"key": key, "text": f"第 x 項毛利率 {margin * 100:.2f}% 低於 30%", "margin": margin}


def test_summary_nothing_changed():
    a = [_m("margin:idx:1", 0.2), _e("validDays")]
    s = QT.category_summary(a, a)
    assert s["needs_confirm"] is False and s["new_categories"] == []
    assert s["low_margin_items"] == {"before": 1, "after": 1, "increased": False}
    assert s["lowest_margin"] == {"before": 0.2, "after": 0.2, "lower": False}


def test_summary_new_category_needs_confirm():
    s = QT.category_summary([_m("margin:idx:1", 0.2)], [_m("margin:idx:1", 0.2), _e("discount"), _e("terms"), _e("discount")])
    assert s["new_categories"] == ["discount", "terms"] and s["needs_confirm"] is True


def test_summary_insert_a_row_shifts_idx_keys_but_is_not_a_difference():
    """報價品項沒有穩定 id ⇒ 退回 idx:；前面插一列正常品項，原低毛利項的鍵位移——diff_reason_entries 會誤報，category_summary 不會。"""
    old = [_m("margin:idx:0", 0.2), _m("margin:idx:1", 0.25)]
    new = [_m("margin:idx:1", 0.2), _m("margin:idx:2", 0.25)]
    assert QT.diff_reason_entries(old, new)["added"], "（對照：鍵位移會被 diff 當成新增）"
    s = QT.category_summary(old, new)
    assert s["needs_confirm"] is False and s["new_categories"] == []


def test_summary_more_low_margin_items():
    s = QT.category_summary([_m("margin:idx:0", 0.25)], [_m("margin:idx:0", 0.25), _m("margin:idx:1", 0.28)])
    assert s["low_margin_items"] == {"before": 1, "after": 2, "increased": True} and s["needs_confirm"] is True
    assert s["lowest_margin"]["lower"] is False


def test_summary_lowest_margin_lower_even_with_same_count():
    s = QT.category_summary([_m("margin:idx:0", 0.25)], [_m("margin:idx:0", 0.10)])
    assert s["lowest_margin"] == {"before": 0.25, "after": 0.10, "lower": True}
    assert s["low_margin_items"]["increased"] is False and s["needs_confirm"] is True


def test_summary_improvements_and_removals_do_not_need_confirm():
    old = [_m("margin:idx:0", 0.10), _e("validDays"), _e("discount")]
    new = [_m("margin:idx:0", 0.25), _e("discount", "含折讓 99999")]       # 毛利變好、有效天數類別消失、折讓金額變大（同類別）
    s = QT.category_summary(old, new)
    assert s["needs_confirm"] is False


def test_summary_empty_none_and_strings():
    assert QT.category_summary(None, None)["needs_confirm"] is False
    assert QT.category_summary([], [_m("margin:idx:0", 0.1)])["needs_confirm"] is True
    assert QT.category_summary(["a"], ["a", "b"])["new_categories"] == ["b"]


def test_summary_end_to_end_with_real_entries_and_inserted_row():
    base = _q([{"cost": 100, "unitPrice": 120}, {"cost": 100, "unitPrice": 400}])        # 無 id
    old = QT.current_reason_entries(base)
    assert [e["key"] for e in old] == ["margin:idx:0"]
    ins = copy.deepcopy(base)
    ins["items"].insert(0, {"cost": 10, "unitPrice": 1000})                               # 前面插一列正常品項
    assert QT.category_summary(old, QT.current_reason_entries(ins))["needs_confirm"] is False
    worse = copy.deepcopy(base)
    worse["items"][0]["unitPrice"] = 110
    assert QT.category_summary(old, QT.current_reason_entries(worse))["needs_confirm"] is True
