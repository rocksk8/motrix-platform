# -*- coding: utf-8 -*-
"""M3 T2（T57）：擇一方案資料模型＋唯一計入集合（profit_guard.counted_items）、驗證、伺服器自有欄位、設定中心群組 quote_alt。
純函式題不需要 client；端點題沿用 test_quote_server_owned_fields_t54 的登入樣式。"""
import json

import pytest
from fastapi import HTTPException

import db
from helpers import settings_registry as R
from helpers import settings_groups as SG
from modules.case import alt_policy
from modules.case import profit_guard as PG


def _it(id_, qty, price, cost, group=None, **kw):
    d = {"id": id_, "qty": qty, "unitPrice": price, "cost": cost, "amount": qty * price}
    if group is not None:
        d["altGroup"] = group
    d.update(kw)
    return d


def _plain():
    return {"items": [_it("a", 2, 1000, 600), _it("h", 0, 0, 0, type="header"), _it("b", 1, 500, 300)], "discount": 100, "freight": 50, "taxRate": 5}


def _alt(picks=None):
    q = {"items": [_it("a", 2, 1000, 600), _it("x1", 1, 3000, 2000, "投影機"), _it("x2", 1, 5000, 3500, "投影機"),
                   _it("y1", 4, 100, 60, "線材"), _it("y2", 4, 150, 90, "線材")], "taxRate": 5, "totalsByAlt": True}
    if picks is not None:
        q["altPicks"] = picks
    return q


def _profit(q):
    t = PG.server_totals(q)
    return t, PG.server_profit(dict(q, tot=t), 25, 2, pretax=t["pretax"], total=t["total"])


# --- A 計算 ---------------------------------------------------------------

def test_no_altgroup_is_bitwise_unchanged():
    q = _plain()
    assert PG.counted_items(q) == q["items"]
    t, p = _profit(q)
    assert t["subtotal"] == sum(PG.item_amount(i) for i in q["items"])
    assert p["totalCost"] == 2 * 600 + 300


def test_unselected_groups_excluded_from_totals_and_cost():
    q = _alt()
    assert [i["id"] for i in PG.counted_items(q)] == ["a"]
    t, p = _profit(q)
    assert t["subtotal"] == 2000
    assert p["totalCost"] == 1200 and p["inputVat"] == 60


def test_selected_equals_plain_quote_with_picked_items():
    q = _alt({"投影機": "x2", "線材": "y1"})
    plain = {"items": [_it("a", 2, 1000, 600), _it("x2", 1, 5000, 3500), _it("y1", 4, 100, 60)], "taxRate": 5}
    assert _profit(q) == _profit(plain)


def test_partial_pick_counts_only_picked_group():
    assert [i["id"] for i in PG.counted_items(_alt({"投影機": "x1"}))] == ["a", "x1"]


def test_pick_pointing_to_other_group_or_missing_counts_nothing():
    assert [i["id"] for i in PG.counted_items(_alt({"投影機": "y1", "線材": "zzz"}))] == ["a"]


def test_group_name_trimmed_and_blank_is_not_alt():
    q = {"items": [_it("a", 1, 100, 50, "  "), _it("b", 1, 100, 50, " G "), _it("c", 1, 100, 50, "G")], "totalsByAlt": True}
    assert [i["id"] for i in PG.counted_items(q)] == ["a"]
    assert [i["id"] for i in PG.counted_items(q, {"G": "c"})] == ["a", "c"]


def test_picks_argument_overrides_stored_picks():
    q = _alt({"投影機": "x1"})
    assert [i["id"] for i in PG.counted_items(q, {"投影機": "x2"})] == ["a", "x2"]


def test_counted_items_does_not_mutate_input():
    q = _alt({"投影機": "x1"})
    snap = json.dumps(q, sort_keys=True)
    PG.counted_items(q)
    PG.counted_items(q, {"線材": "y2"})
    assert json.dumps(q, sort_keys=True) == snap


# --- 驗證（422）----------------------------------------------------------------

def test_validate_ok_for_plain_and_alt():
    PG.validate_alt(_plain(), 10)
    PG.validate_alt(_alt(), 10)


def _raises_422(q, limit=10):
    with pytest.raises(HTTPException) as e:
        PG.validate_alt(q, limit)
    assert e.value.status_code == 422
    return e.value.detail


def test_validate_single_item_group():
    q = _alt()
    q["items"].pop(2)
    _raises_422(q)


def test_validate_totals_flag_must_be_real_bool():
    q = _alt()
    q["totalsByAlt"] = "yes"
    _raises_422(q)
    q["totalsByAlt"] = 1
    _raises_422(q)


def test_validate_group_must_be_text():
    q = _alt()
    q["items"][0]["altGroup"] = 5
    _raises_422(q)


def test_validate_header_cannot_be_alt():
    q = _alt()
    q["items"].append(_it("h2", 0, 0, 0, "投影機", type="header"))
    _raises_422(q)


def test_validate_group_count_limit():
    assert "最多 1 組" in _raises_422(_alt(), 1)


def test_validate_picks_must_belong_to_group():
    for bad in ({"投影機": "y1"}, {"不存在": "x1"}, {"投影機": "a"}):
        _raises_422(_alt(bad))


# --- 伺服器自有欄位 -------------------------------------------------------------

def test_restore_ignores_client_picks_and_keeps_stored():
    q = _alt({"投影機": "x1"})
    q["altPickedBy"] = "forged"
    old = _alt({"投影機": "x2"})
    old["altPickedBy"] = "admin"
    old["altPickedAt"] = "2026-10-12T10:00:00"
    PG.restore_alt_server_fields(q, old)
    assert q["altPicks"] == {"投影機": "x2"} and q["altPickedBy"] == "admin"


def test_restore_without_stored_picks_removes_client_picks():
    q = _alt({"投影機": "x1"})
    q["altPickedAt"] = "x"
    PG.restore_alt_server_fields(q, {})
    assert "altPicks" not in q and "altPickedAt" not in q


def test_restore_prunes_stale_pick_after_regroup():
    q = _alt()
    PG.restore_alt_server_fields(q, {"altPicks": {"投影機": "gone"}, "altPickedBy": "u"})
    assert "altPicks" not in q and "altPickedBy" not in q


def test_alt_signature_changes_with_group_or_totals_flag():
    a, b = _alt(), _alt()
    assert PG._alt_signature(a) == PG._alt_signature(b)
    b["items"][1]["altGroup"] = "別組"
    assert PG._alt_signature(a) != PG._alt_signature(b)
    c = _alt()
    c["totalsByAlt"] = False
    assert PG._alt_signature(a) != PG._alt_signature(c)


# --- 設定中心 quote_alt ---------------------------------------------------------

_POLICIES = ("lock_scope", "cancel_after_deal", "move_out_of_sent", "reject_final_keep", "unlock_edit_signed",
             "approval_basis", "cancel_after_export", "cancel_after_invoice", "cancel_after_settle")


def _fields():
    return {f["key"]: f for f in R.groups()["quote_alt"]["fields"]}


def test_group_registered_with_expected_defaults():
    v = R.get_group("quote_alt", now="2000-01-01T00:00:00")
    assert v["alt_enabled"] is True and v["total_text"] == "依方案選擇" and v["note_template"] == "項次{items}為{group}擇一方案選擇"
    assert v["show_unpicked_in_pdf"] is False and v["alt_groups_max"] == 10 and v["combo_view_max"] == 24 and v["combo_view_default_open"] is False
    assert all(v[k] == 1 for k in _POLICIES)


def test_policy_fields_money_risk_with_banner_and_ordered_choices():
    by = _fields()
    for k in _POLICIES:
        f = by[k]
        assert f["risk"] == "money" and f["loosen"] == "up" and f["requiresPending"] and "高影響" in f["riskText"]
        assert [c["value"] for c in f["choices"]] == list(range(1, len(f["choices"]) + 1)), "選項代碼連續、由嚴到寬"
    assert by["total_text"]["risk"] == "legal" and by["note_template"]["risk"] == "legal"


def test_unavailable_choices_registered_but_not_selectable():
    by = _fields()
    # 消費者尚未落地的選項一律不可選，各任務在自己的 commit 開放（T9b：lock_scope②、unlock_edit_signed② 已有消費者 alt_lock／guard_update）
    assert set(SG.UNAVAILABLE_ALT_CHOICES) == set(_POLICIES) - {"lock_scope", "unlock_edit_signed"}
    assert SG.UNAVAILABLE_ALT_CHOICES["cancel_after_deal"] == (2,)          # T9：③『允許，只提醒』的消費者（取消回簽守門鏈）已落地
    for k, bad in SG.UNAVAILABLE_ALT_CHOICES.items():
        labels = {c["value"]: c["label"] for c in by[k]["choices"]}
        for b in bad:
            assert "尚未提供" in labels[b]
            problems = R.validate_values("quote_alt", {k: b}, partial=True)
            assert problems and problems[0]["path"] == k
    assert R.validate_values("quote_alt", {"cancel_after_deal": 1}, partial=True) == []
    assert R.validate_values("quote_alt", {"cancel_after_deal": 3}, partial=True) == []


def test_policy_reader_clamps_unavailable_value_to_default(monkeypatch):
    monkeypatch.setattr(R, "get", lambda g, f, **kw: 2)
    assert alt_policy.policy("cancel_after_deal") == 1
    assert alt_policy.policy("lock_scope") == 2            # T9b 已開放
    assert alt_policy.policy("approval_basis") == 1        # 尚未提供 ⇒ 夾回預設
    monkeypatch.setattr(R, "get", lambda g, f, **kw: 3)
    assert alt_policy.policy("cancel_after_deal") == 3
    with pytest.raises(KeyError):
        alt_policy.policy("total_text")


def test_user_text_has_no_internal_keys():
    for f in R.groups()["quote_alt"]["fields"]:
        for t in [f["question"], f["label"], f["help"], f["impact"]] + [c["label"] for c in f["choices"]] + [c["impact"] for c in f["choices"]]:
            assert "quote_alt" not in t and "altPicks" not in t and "altGroup" not in t


# --- 端點：一般存檔不採用用戶端 altPicks、組數上限來自設定 --------------------------

def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _body(**over):
    d = {"customerName": "擇一客", "projectName": "擇一案", "salesPerson": "", "quoteDate": "2026-10-12", "taxRate": 5,
         "items": _alt()["items"], "tot": {}, "totalsByAlt": True}
    d.update(over)
    return d


def _stored(no):
    cn = db.get_db()
    try:
        return json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()["data_json"])
    finally:
        cn.close()


@pytest.fixture
def admin_h(client, make_user):
    u, p = make_user(username="alt_admin", role="admin")
    return _login(client, u, p)


def test_post_drops_client_altpicks(client, admin_h):
    r = client.post("/api/quotations", json={"status": "草稿", "data": _body(altPicks={"投影機": "x1"}, altPickedBy="forged")}, headers=admin_h)
    assert r.status_code == 201, r.text
    d = _stored(r.json()["quote_no"])
    assert "altPicks" not in d and "altPickedBy" not in d


def test_post_rejects_single_item_group(client, admin_h):
    items = _alt()["items"]
    items.pop(2)
    r = client.post("/api/quotations", json={"status": "草稿", "data": _body(items=items)}, headers=admin_h)
    assert r.status_code == 422


def test_post_group_limit_comes_from_settings(client, admin_h, monkeypatch):
    real = R.get
    monkeypatch.setattr(R, "get", lambda g, f, **kw: 1 if (g, f) == ("quote_alt", "alt_groups_max") else real(g, f, **kw))
    r = client.post("/api/quotations", json={"status": "草稿", "data": _body()}, headers=admin_h)
    assert r.status_code == 422 and "最多 1 組" in r.text


# --- T2 稽核修正（0d）-------------------------------------------------------------

def test_validate_alt_member_needs_unique_nonblank_string_id():
    for bad in (None, "", "  ", 5):
        q = _alt()
        q["items"][1]["id"] = bad
        _raises_422(q)
    q = _alt()
    q["items"][2]["id"] = q["items"][1]["id"]
    _raises_422(q)
    q = _alt()                                   # 不同組、非擇一項的重複 id 不在本規則內
    q["items"][0]["id"] = "x1"
    PG.validate_alt(q, 10)


def test_text_fields_cross_check():
    def probs(**v):
        return R.validate_values("quote_alt", v, partial=True)
    assert probs(total_text="x" * 40) == [] and probs(total_text="x" * 41)
    assert probs(note_template="x" * 201)
    assert probs(total_text="a\nb") and probs(note_template="a\x00b")
    assert probs(note_template="項次{items}為{group}") == []
    assert probs(note_template="項次{items}{other}") and probs(note_template="{group")
    assert probs(note_template="純文字") == []


def test_note_template_help_has_no_braces():
    f = _fields()["note_template"]
    assert "{" not in f["help"] and "}" not in f["help"]


def test_approval_basis_choice_texts_match_today_behavior():
    c = _fields()["approval_basis"]["choices"]
    assert "尚未提供" not in c[0]["label"] and "目前" in c[0]["label"] and "尚未提供" in c[1]["label"]


def test_completion_items_respect_picks_via_counted_items():
    """完工單／下游取『計入品項』時要尊重選定；未選整組不計入。"""
    q = _alt({"投影機": "x2"})
    assert [i["id"] for i in PG.counted_items(q)] == ["a", "x2"]
    assert [i["id"] for i in PG.counted_items(_alt())] == ["a"]


# --- 總開關 totalsByAlt（1c 2026-10-13：沒開 ⇒ 擇一組別惰性）---------------------------------

def test_switch_off_groups_are_inert_all_items_counted():
    for flag in ("absent", False, "yes", 1, None):
        q = _alt({"投影機": "x1"})
        if flag == "absent":
            q.pop("totalsByAlt")
        else:
            q["totalsByAlt"] = flag
        assert [i["id"] for i in PG.counted_items(q)] == ["a", "x1", "x2", "y1", "y2"], flag
        assert PG.alt_active(q) is False
    plain = {"items": [_it("a", 2, 1000, 600), _it("x1", 1, 3000, 2000), _it("x2", 1, 5000, 3500), _it("y1", 4, 100, 60), _it("y2", 4, 150, 90)], "taxRate": 5}
    off = _alt(); off["totalsByAlt"] = False
    assert _profit(off) == _profit(plain)


def test_switch_on_same_items_exclude_unpicked():
    assert [i["id"] for i in PG.counted_items(_alt())] == ["a"]
    assert PG.alt_active(_alt()) is True
