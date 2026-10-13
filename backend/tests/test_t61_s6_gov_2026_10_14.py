# -*- coding: utf-8 -*-
"""T61 S6 治理面：使用者自訂按鈕（kind＝user_buttons）進單一發布管線（routers/def_pipeline.py）。
- 比較函式：新增匯出按鈕／改成匯出＝放寬（理由列出按鈕文字與匯出）；新增開頁＝不變；拿掉任何按鈕、匯出改開頁＝收緊；只改文字／插槽＝不變；看不懂＝放寬
- 與 3c 的編輯器對接：待核准回應的鍵（pending／version／effectiveAt／reasons）與編輯器讀的一致
- 整合測試需要 3c 的 helpers.user_buttons（kind 登記）；沒有就略過"""
import re

import pytest

from routers import def_pipeline as P

NAV = {"key": "b1", "slot": "suppliers.html/toolbar", "label": "去客戶", "action": {"type": "navigate", "page": "customers.html"}}
EXP = {"key": "b2", "slot": "suppliers.html/toolbar", "label": "匯出清單", "action": {"type": "export", "export": "supply:suppliers"}}


def _b(*buttons):
    return {"buttons": list(buttons)}


def c(old, new):
    return P.classify("user_buttons", old, new)


def test_user_buttons_is_in_the_active_list():
    assert "user_buttons" in P.ACTIVE_KINDS and "user_buttons" in P.COMPARATORS


def test_adding_an_export_button_is_loosening_and_the_reasons_name_it():
    cls, reasons = c(_b(NAV), _b(NAV, EXP))
    assert cls == "loosen" and any("匯出清單" in r and "supply:suppliers" in r for r in reasons)
    assert c(_b(), _b(EXP))[0] == "loosen" and c({}, _b(EXP))[0] == "loosen"                          # 第一次發布也一樣


def test_changing_a_button_to_export_or_to_another_export_is_loosening():
    to_export = dict(NAV, action={"type": "export", "export": "supply:suppliers"})
    cls, reasons = c(_b(NAV), _b(to_export))
    assert cls == "loosen" and any("改為匯出" in r for r in reasons)
    other = dict(EXP, action={"type": "export", "export": "supply:other"})
    assert c(_b(EXP), _b(other))[0] == "loosen"                                                       # 換一個匯出目標也是放寬
    assert c(_b(EXP), _b(EXP))[0] == "neutral"


def test_adding_navigate_is_neutral_and_removing_buttons_is_tightening():
    assert c(_b(), _b(NAV))[0] == "neutral"
    assert c(_b(NAV, EXP), _b(NAV))[0] == "tighten" and c(_b(NAV), _b())[0] == "tighten"
    back = dict(EXP, action={"type": "navigate", "page": "customers.html"})
    assert c(_b(EXP), _b(back))[0] == "tighten"                                                       # 匯出改成開頁＝收緊
    assert c(_b(NAV), _b(dict(NAV, action={"type": "navigate", "page": "orders.html"})))[0] == "neutral"


def test_label_and_slot_only_changes_are_neutral():
    assert c(_b(NAV, EXP), _b(dict(NAV, label="改個字"), dict(EXP, label="另一個名字", slot="suppliers.html/footer")))[0] == "neutral"


def test_add_export_and_remove_another_is_still_loosening_and_lists_both():
    cls, reasons = c(_b(NAV), _b(EXP))
    assert cls == "loosen" and any("新增匯出按鈕" in r for r in reasons) and any("移除按鈕" in r for r in reasons)


@pytest.mark.parametrize("bad", [None, [], "x", {"buttons": "x"}, {"buttons": ["x"]}, {"buttons": [{"key": "b1"}]},
                                 {"buttons": [NAV, NAV]}, {"buttons": [{"key": 5, "action": {}}]}])
def test_unparseable_new_definitions_are_loosening(bad):
    assert c(_b(NAV), bad)[0] == "loosen"


def test_unparseable_old_definition_is_loosening_too():
    assert c({"buttons": "x"}, _b(NAV))[0] == "loosen"                                                # 舊版看不懂就不能當成可信的比較基準


def test_unknown_action_type_and_extra_attributes_are_loosening():
    odd = dict(NAV, action={"type": "post", "url": "x"})
    assert c(_b(), _b(odd))[0] == "loosen" and c(_b(NAV), _b(dict(NAV, action=odd["action"])))[0] == "loosen"
    assert c(_b(NAV), _b(dict(NAV, secret="x")))[0] == "loosen"


def test_a_broken_comparator_still_counts_as_loosen(monkeypatch):
    monkeypatch.setitem(P.COMPARATORS, "user_buttons", lambda a, b: 1 / 0)
    assert c(_b(), _b(NAV))[0] == "loosen"


def test_pending_response_shape_matches_what_the_editor_reads(client, make_user, monkeypatch):
    """3c 的 user-buttons.js／layout-editor.js 讀：pending === true、version（整數）、effectiveAt（ISO 字串）、reasons（字串清單）。
    用真的待核准回應核對（custom_fields 走同一個 _submit_pending）。"""
    monkeypatch.setattr(P, "enabled", lambda conn=None: True)
    u, p = make_user(username="t61s6_shape", role="superadmin")
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    url = "/api/definitions/custom_fields/invoice_vouchers"
    assert client.put(url + "/draft", headers=h, json={"body": {"fields": [{"key": "f0", "label": "甲", "type": "text"}]}}).status_code == 200
    j = client.post(url + "/publish", headers=h, json={"note": "n"}).json()
    assert j["pending"] is True and isinstance(j["version"], int) and j["status"] == "submitted"
    assert isinstance(j["effectiveAt"], str) and re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$", j["effectiveAt"])
    assert isinstance(j["reasons"], list) and j["reasons"] and all(isinstance(x, str) for x in j["reasons"])
    assert isinstance(j["changeId"], int) and isinstance(j["message"], str)


def test_end_to_end_when_the_kind_is_registered(client, make_user, monkeypatch):
    from core import definitions as D
    try:
        from helpers import user_buttons as UB            # noqa: F401  3c 的 kind 登記
    except ImportError:
        pytest.skip("helpers.user_buttons 不在這條分支（3c 的 wip/t61-s6-impl-r1）")
    if "user_buttons" not in D.kinds():
        pytest.skip("user_buttons 未登記")
    monkeypatch.setattr(P, "enabled", lambda conn=None: True)
    out = {}
    for n in ("a", "b"):
        u, p = make_user(username="t61s6_" + n, role="superadmin")
        out[n] = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    url = "/api/definitions/user_buttons/module:supply"
    assert client.put(url + "/draft", headers=out["a"], json={"body": _b(EXP)}).status_code == 200
    r = client.post(url + "/publish", headers=out["a"], json={"note": "n"})
    if r.status_code == 422:
        pytest.skip("範例匯出不在目錄內：%s" % r.text[:80])
    assert r.status_code == 200 and r.json()["pending"] is True and r.json()["reasons"]
