# -*- coding: utf-8 -*-
"""S1c／S5 前置能力（SPEC §15.A）：轉接器、json 欄位、非數值 loosen="both"、跨欄檢查帶連線、external 群組、
待生效衝突（pending_exists／supersede）、到期生效的每群組 SAVEPOINT、金額／法遵嚴格讀取。"""
import json

import pytest

from db import get_db
from helpers import config_ledger as L
from helpers import settings_groups  # noqa: F401
from helpers import settings_registry as R

GJ, GA, GB, GX = "zz_s5_json", "zz_s5_ok", "zz_s5_bad", "zz_s5_ext"
STORE = {}


def _doc_field(**kw):
    base = dict(question="這份清單要放什麼？", label="清單", help="測試用的整份清單。", impact="影響之後使用這份清單的畫面。",
                risk="money", risk_text="清單改錯會影響金額。", loosen="both",
                impact_scope={"documents": ["測試單據"], "roles": ["測試角色"], "amounts": "不影響已開出的金額", "reversible": True, "effective": "pending"})
    base.update(kw)
    return R.SettingDef("doc", "json", [], **base)


def _adapter(name, fail_write=False, norm=None):
    def read(conn):
        return {"doc": json.loads(json.dumps(STORE[name]))} if name in STORE else {}

    def write(conn, values, old=None):
        if fail_write:
            raise RuntimeError("舊儲存寫入失敗")
        STORE[name] = values["doc"]
        STORE[name + ":old"] = (old or {}).get("doc")
    return R.Adapter(read, write, norm)


@pytest.fixture()
def conn(client, make_user):
    make_user(username="s5_a", role="superadmin")
    make_user(username="s5_b", role="superadmin")
    STORE.clear()
    R.invalidate()
    R.register_group(GJ, "整份清單測試", [_doc_field()], help="測試用群組。", risk="money", legacy_adapter=_adapter(GJ, norm=lambda v: sorted(v, key=lambda x: str(x))))
    c = get_db()
    yield c
    for g in (GJ, GA, GB, GX):
        R._GROUPS.pop(g, None)
    c.close()
    R.invalidate()


def test_json_field_roundtrips_through_the_adapter_and_passes_old_to_write(conn):
    STORE[GJ] = ["a"]
    assert R.get_group(GJ, conn=conn)["doc"] == ["a"]                                     # 讀走轉接器（舊儲存）
    R.publish(GJ, {"doc": ["b", "a"]}, reason="r", user="s5_a", conn=conn, expected_values={"doc": ["a"]})
    # 非數值 both ⇒ 任何變更都進待生效，舊儲存此刻不變
    assert STORE[GJ] == ["a"]
    assert [r["field"] for r in L.pending(conn, "setting:" + GJ)] == ["doc"]


def test_json_cas_is_canonical_key_order_does_not_matter_but_content_does(conn):
    STORE[GJ] = [{"x": 1, "y": 2}]
    R.publish(GJ, {"doc": [{"x": 1, "y": 3}]}, reason="r", user="s5_a", conn=conn, expected_values={"doc": [{"y": 2, "x": 1}]})   # 鍵順序不同 ⇒ 仍相符
    with pytest.raises(R.SettingConflict):
        R.publish(GJ, {"doc": [{"x": 9}]}, reason="r", user="s5_a", conn=conn, expected_values={"doc": [{"x": 2, "y": 2}]})
    assert not R._same_value([1], [True])                                                  # 巢狀布林與數字不混
    assert not R._same_value({"a": 1}, {"a": True})


def test_json_size_limit_refuses_oversized_documents(conn):
    big = ["x" * 100] * 200                                                                 # > 15000 字
    with pytest.raises(R.SettingError) as ei:
        R.publish(GJ, {"doc": big}, reason="r", user="s5_a", conn=conn)
    assert "太大" in str(ei.value.problems)


def test_adapter_normalize_runs_before_compare_and_validate(conn):
    STORE[GJ] = ["a", "b"]
    out = R.plan(GJ, {"doc": ["b", "a"]}, conn=conn)                                       # 正規化後相同 ⇒ 沒有變更
    assert out["ok"] and [f["kind"] for f in out["fields"]] == ["unchanged"]


def test_loosen_both_on_non_numeric_goes_through_pending_not_immediate(conn):
    f = R.SettingDef("mode", "str", "a", question="用哪種模式？", label="模式", help="測試用。", impact="影響測試。", risk="money", risk_text="會影響金額。",
                     loosen="both", impact_scope={"documents": ["測試單據"], "roles": ["測試角色"], "amounts": "不影響已開出的金額", "reversible": True, "effective": "pending"})
    R.register_group(GA, "模式測試", [f], help="測試用群組。", risk="money")
    out = R.publish(GA, {"mode": "b"}, reason="r", user="s5_a", conn=conn)
    assert R.get(GA, "mode", conn=conn) == "a" and out.get("pending")


def test_cross_check_receives_the_connection_when_it_accepts_one(conn):
    seen = []

    def cc(values, conn):
        seen.append(conn)
        return [{"path": "doc", "message": "清單不得為空"}] if not values["doc"] else []

    f = _doc_field(loosen=None, risk="ops", risk_text="", impact_scope=None)
    R.register_group(GA, "跨欄測試", [f], help="測試用群組。", cross_check=cc)
    with pytest.raises(R.SettingError):
        R.publish(GA, {"doc": []}, reason="r", user="s5_a", conn=conn)
    assert seen and all(c is not None for c in seen)                                           # 預檢沒有連線時開臨時連線，不把 None 交給要查庫的檢查
    seen.clear()
    R.publish(GA, {"doc": ["k"]}, reason="r", user="s5_a", conn=conn)
    assert any(c is conn for c in seen)                                                        # 寫入時帶真正的（同交易）連線
    R._GROUPS.pop(GA)
    R.register_group(GA, "跨欄測試", [f], help="測試用群組。", cross_check=lambda v: [])         # 單參數仍可用
    assert R.publish(GA, {"doc": ["k2"]}, reason="r", user="s5_a", conn=conn)["changed"]


def test_pending_exists_blocks_silent_overwrite_of_another_actors_document(conn):
    R.publish(GJ, {"doc": ["a"]}, reason="r", user="s5_a", conn=conn)
    with pytest.raises(R.SettingConflict) as ei:
        R.publish(GJ, {"doc": ["z"]}, reason="r", user="s5_b", conn=conn)
    assert ei.value.code == "pending_exists" and ei.value.keys == ["doc"]
    out = R.publish(GJ, {"doc": ["z"]}, reason="r", user="s5_b", conn=conn, supersede=True)   # 畫面確認後才帶
    assert out["supersededRequests"]
    out = R.publish(GJ, {"doc": ["z2"]}, reason="r", user="s5_b", conn=conn)                  # 自己覆寫自己的申請不擋
    assert out["superseded"] == 1


def test_external_group_is_hidden_from_generic_routes(client, make_user, conn):
    username, password = make_user(username="s5_c", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    R.register_group(GX, "外部測試", [_doc_field(loosen=None, risk="ops", risk_text="", impact_scope=None)], help="測試用群組。", external=True)
    assert R.groups()[GX]["external"] is True
    assert client.get("/api/settings-center/groups/" + GX, headers=h).status_code == 403
    assert client.post("/api/settings-center/groups/" + GX, headers=h, json={"values": {"doc": ["q"]}, "reason": "r"}).status_code == 403
    assert client.get("/api/settings-center/public?groups=" + GX, headers=h).status_code == 404
    names = [g["group"] for g in client.get("/api/settings-center/groups", headers=h).json()["groups"]]
    assert GX not in names and GJ in names


def test_materialize_due_isolates_a_failing_adapter_to_its_own_group(conn):
    from datetime import datetime, timedelta
    later = (datetime.now() + timedelta(days=8)).isoformat(timespec="seconds")
    R.register_group(GB, "會失敗的群組", [_doc_field()], help="測試用群組。", risk="money", legacy_adapter=_adapter(GB, fail_write=True))
    R.register_group(GA, "正常的群組", [_doc_field()], help="測試用群組。", risk="money", legacy_adapter=_adapter(GA))
    R.publish(GB, {"doc": ["b"]}, reason="r", user="s5_a", conn=conn)
    R.publish(GA, {"doc": ["a"]}, reason="r", user="s5_a", conn=conn)
    conn.commit()
    for g_ in (GA, GB):
        for r_ in L.pending(conn, 'setting:' + g_):
            assert L.approve(conn, r_['id'], 's5_b')['ok']                                  # 第二位最高管理者核准
    conn.commit()
    R.materialize_due(conn, now=later)
    assert STORE[GA] == ["a"]                                                              # 其他群組照常生效
    assert [r for r in L.pending(conn, "setting:" + GB)] == []                              # 失敗群組的到期項被取消
    assert any("寫入失敗" in (r.get("reason") or "") or r["state"] == "cancelled" for r in L.history(conn, "setting:" + GB, GB))
    assert GB not in STORE and R.get_group(GB, conn=conn)["doc"] == []                      # 定義列與舊儲存不分歧


def test_strict_reader_ignores_defaults_only_flag_and_never_falls_back_to_defaults(conn, monkeypatch):
    STORE[GJ] = ["real"]
    monkeypatch.setenv("MOTRIX_SETTINGS_DEFAULTS_ONLY", "1")
    assert R.get_group(GJ, conn=conn)["doc"] == []                                          # 一般讀取：開發旗標 ⇒ 預設
    assert R.get_group_effective(GJ, conn=conn)["doc"] == ["real"]                          # 嚴格讀取：忽略旗標
    R._GROUPS[GJ]["adapter"] = R.Adapter(lambda c: (_ for _ in ()).throw(RuntimeError("讀不到")), lambda *a, **k: None)
    with pytest.raises(RuntimeError):
        R.get_group_effective(GJ, conn=conn)                                                # 連舊儲存都讀不到 ⇒ 大聲失敗，不回預設


def test_pending_page_shows_summary_not_raw_json(client, make_user, conn):
    R._GROUPS[GJ]["fields"]["doc"].summarize = lambda old, new: ["清單由 %d 項改為 %d 項" % (len(old or []), len(new or []))]
    R.publish(GJ, {"doc": ["secret-token"]}, reason="r", user="s5_a", conn=conn)
    conn.commit()
    username, password = make_user(username="s5_d", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]
    body = client.get("/api/settings-center/pending", headers={"Authorization": "Bearer " + tok})
    assert "secret-token" not in body.text and "清單由 0 項改為 1 項" in body.text
