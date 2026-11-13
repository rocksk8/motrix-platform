# -*- coding: utf-8 -*-
"""S1c：設定登錄表逐欄 CAS（`publish(..., expected_values=)`＋`SettingConflict`＋路由 409）。

規則（SPEC §5-5）：在 begin_write 之後、寫入前，逐欄比對目前**生效值**（含已到時的待生效覆蓋層）；
只比對有列出的欄位——同群組別的欄位被別人改，不誤拒；不符 ⇒ 什麼都不寫。
"""
import pytest

from db import get_db
from helpers import config_ledger as L
from helpers import settings_groups  # noqa: F401
from helpers import settings_registry as R

G = "zz_cas_s1c"


def _hdr(client, make_user, name="cas_sa"):
    username, password = make_user(username=name, role="superadmin")
    tok = client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]
    return {"Authorization": "Bearer " + tok}


@pytest.fixture()
def grp(client, make_user):
    make_user(username="cas_b", role="superadmin")
    c = get_db()
    R.invalidate()
    R.register_group(G, "逐欄比對測試群組", [
        R.SettingDef("cap", "int", 10, min=1, max=1000, risk="security", loosen="up", question="上限要設多少？", label="上限",
                     help="測試用的上限。", impact="影響之後的操作，調大屬放寬。", risk_text="調大後門檻變低。"),
        R.SettingDef("note_days", "int", 5, min=1, max=100, risk="ops", question="提醒幾天前寄？", label="提醒天數",
                     help="測試用。", impact="只影響提醒時間。"),
    ], help="測試用的設定群組。", risk="security")
    yield c
    R._GROUPS.pop(G, None)
    R.clear_edition_bounds()
    c.close()
    R.invalidate()


def test_matching_expected_values_write_normally(grp):
    out = R.publish(G, {"note_days": 7}, reason="r", user="cas_a", conn=grp, expected_values={"note_days": 5})
    assert out["changed"] and R.get(G, "note_days", conn=grp) == 7


def test_other_field_changed_by_someone_else_is_not_a_conflict(grp):
    R.publish(G, {"cap": 5}, reason="r", user="cas_x", conn=grp)                           # 別人改了 cap（收緊＝立即）
    out = R.publish(G, {"note_days": 9}, reason="r", user="cas_a", conn=grp, expected_values={"note_days": 5})
    assert out["changed"] and R.get(G, "note_days", conn=grp) == 9


def test_same_field_changed_is_refused_names_the_author_and_writes_nothing(grp):
    R.publish(G, {"note_days": 8}, reason="別人先改", user="cas_x", conn=grp)
    before = len(L.history(grp, "setting:" + G, G))
    with pytest.raises(R.SettingConflict) as ei:
        R.publish(G, {"note_days": 9}, reason="r", user="cas_a", conn=grp, expected_values={"note_days": 5})
    e = ei.value
    assert e.keys == ["note_days"] and e.by == "cas_x" and e.at
    assert R.get(G, "note_days", conn=grp) == 8 and len(L.history(grp, "setting:" + G, G)) == before   # 沒寫任何東西（含帳本）


def test_conflict_origin_falls_back_to_system_default_when_the_ledger_has_no_record(grp):
    with pytest.raises(R.SettingConflict) as ei:
        R.publish(G, {"cap": 5}, reason="r", user="cas_a", conn=grp, expected_values={"cap": 99})
    assert ei.value.by == "系統預設" and ei.value.at == ""


def test_expected_value_compares_against_the_effective_value_including_due_pending(grp, monkeypatch):
    monkeypatch.setattr(R, "confirm_period_days", lambda conn=None: 0)                     # 待生效當下就到時
    out = R.publish(G, {"cap": 50}, reason="放寬", user="cas_x", conn=grp)                  # 調大＝放寬 ⇒ 待生效
    for p in out["pending"]:
        if p["approvalsRequired"]:
            assert L.approve(grp, p["id"], "cas_b")["ok"]
    grp.commit()
    assert R.get(G, "cap", conn=grp) == 50                                                  # 生效值含到時的待生效
    with pytest.raises(R.SettingConflict):
        R.publish(G, {"cap": 20}, reason="r", user="cas_a", conn=grp, expected_values={"cap": 10})     # 儲存值還是 10，但生效值是 50
    R.publish(G, {"cap": 20}, reason="r", user="cas_a", conn=grp, expected_values={"cap": 50})


def test_numbers_compare_across_int_and_float_but_not_bool(grp):
    assert R.publish(G, {"note_days": 6}, reason="r", user="cas_a", conn=grp, expected_values={"note_days": 5.0})["changed"]
    assert R._same_value(1, 1.0) and not R._same_value(1, True) and not R._same_value(True, 1)       # noqa: SLF001


def test_unknown_expected_field_is_an_input_error_not_a_conflict(grp):
    with pytest.raises(R.SettingError):
        R.publish(G, {"note_days": 6}, reason="r", user="cas_a", conn=grp, expected_values={"nope": 1})


def test_undo_is_a_cas_write_back_of_the_previous_value(grp):
    R.publish(G, {"note_days": 8}, reason="r", user="cas_a", conn=grp, expected_values={"note_days": 5})
    R.publish(G, {"note_days": 5}, reason="復原批次", user="cas_a", conn=grp, expected_values={"note_days": 8})   # 復原＝以套用後的值為期望
    assert R.get(G, "note_days", conn=grp) == 5
    R.publish(G, {"note_days": 8}, reason="別人又改", user="cas_x", conn=grp)
    with pytest.raises(R.SettingConflict):                                                   # 之後又被改 ⇒ 復原被拒，不蓋掉別人的
        R.publish(G, {"note_days": 5}, reason="復原批次", user="cas_a", conn=grp, expected_values={"note_days": 7})


def test_route_returns_409_with_the_shared_conflict_shape(client, make_user):
    h = _hdr(client, make_user)
    r = client.post("/api/settings-center/groups/change_control",
                    json={"values": {"confirm_period_days": 14}, "reason": "測試", "expectedValues": {"confirm_period_days": 3}}, headers=h)
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert d["code"] == "conflict" and d["keys"][0]["key"] == "confirm_period_days" and d["keys"][0]["name"]
    assert d["by"] and "at" in d and d["message"]
    bad = client.post("/api/settings-center/groups/change_control",
                      json={"values": {"confirm_period_days": 14}, "reason": "測試", "expectedValues": [1]}, headers=h)
    assert bad.status_code == 400
