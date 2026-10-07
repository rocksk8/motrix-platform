# -*- coding: utf-8 -*-
"""請款單端的「自動帶入」驗證與解析（`helpers.expense_types` ⇄ `helpers.prefill_sources`，2e 的註冊表）。

註冊表整合前，這裡用測試內的替身（`ET._PREFILL_OVERRIDE`）驗**請款單這一側的接線**：
① 定義驗證：帶 `default: {"$": …}` 的欄位逐個交給 `check_field(field, mount_has_case=True, locked=…, path="fields[i]")`，問題原樣帶出；沒有註冊表時行為不變
② 建立：`fill_defaults(defn, values, ctx, prior=None)`，ctx 帶「上一次填過」的鉤子；locked 以伺服器值為準
③ 修改（prior＝舊單 data）：**不重新解析任何來源**——locked 沿用舊值（別人改單不會讓「申請人本人」之類換人）；有註冊表時把 prior 原樣交給它
④ `last_value_hook`：只查本人在該類型最近的單據（Python 解 JSON，不用 json_extract），空值跳過，任何錯誤 ⇒ None
反向控制：把 validate_values 的 prior 忽略掉 ⇒ ③ 必須紅（見該題註解）。"""
import json
from types import SimpleNamespace

import pytest

import db
from helpers import expense_types as ET
from tests.platform.test_expense_types_2026_10_01 import _dept, actors  # noqa: F401  (actors 是 fixture)


@pytest.fixture(autouse=True)
def _no_registry_leak():
    yield
    ET._PREFILL_OVERRIDE = None


def _stub(calls, problems=None, fill=None):
    def check_field(field, *, mount_has_case=True, locked=None, path=""):
        calls.append(("check", field.get("key"), mount_has_case, locked, path))
        return (problems or {}).get(field.get("key"), [])

    def make_ctx(conn, viewer, *, requester=None, case=None, module_key="", last_value=None, now=None):
        return {"viewer": viewer, "case": case, "last_value": last_value}

    def fill_defaults(body, values, ctx, *, prior=None):
        calls.append(("fill", prior, ctx["case"], callable(ctx["last_value"])))
        out = dict(values)
        if fill:
            out.update(fill(prior))
        return out
    return SimpleNamespace(check_field=check_field, make_ctx=make_ctx, fill_defaults=fill_defaults)


def _defn_with(default_fields):
    d = ET._default_for("travel")
    d["fields"] = [dict(f) for f in d["fields"] if f["key"] not in {x["key"] for x in default_fields}] + default_fields
    return d


def test_definition_validation_passes_each_default_field_to_the_registry_and_surfaces_its_problems():
    calls = []
    extra = [{"key": "boss", "label": "主管", "type": "ref", "target": "users", "default": {"$": "requesterManager"}, "locked": True},
             {"key": "memo", "label": "備忘", "type": "text", "default": {"$": "lastUsed"}}]
    d = _defn_with(extra)
    ET._PREFILL_OVERRIDE = _stub(calls, problems={"memo": [{"path": "fields[9]", "message": "這個來源不能和「不能改」並用"}]})
    problems = ET.validate_expense_type(d, "travel")
    assert {"path": "fields[9]", "message": "這個來源不能和「不能改」並用"} in problems
    checked = {c[1]: c for c in calls if c[0] == "check"}
    assert checked["boss"][2] is True and checked["boss"][3] is True                      # mount_has_case=True、locked 帶進去
    assert checked["memo"][3] is False
    assert checked["boss"][4].startswith("fields[")                                        # path 用欄位在 fields 的位置
    assert "lines" not in checked                                                          # 沒有 default 的欄位不送


def test_without_a_registry_definition_validation_is_unchanged():
    ET._PREFILL_OVERRIDE = None
    for code in ET.DEFAULT_KINDS:
        assert ET.validate_expense_type(ET._default_for(code), code) == []


def test_create_calls_fill_defaults_with_no_prior_and_the_last_value_hook(actors):
    calls = []
    ET._PREFILL_OVERRIDE = _stub(calls, fill=lambda prior: {"place": "國內"})
    did = _dept()
    defn = ET._default_for("travel")
    conn = db.get_db()
    try:
        data = {"applicant": actors["other"], "dept": str(did), "cost_dept": str(did), "city": "台北", "period": {"from": "2026-10-01", "to": "2026-10-02"}}
        clean, _l, _t, problems = ET.validate_values(conn, defn, data, [{"category": "交通", "summary": "高鐵", "amount": 10}], viewer=actors["me"],
                                                     case={"customer": "甲", "project": "乙"}, type_code="travel")
        fills = [c for c in calls if c[0] == "fill"]
        assert fills == [("fill", None, {"customer": "甲", "project": "乙"}, True)]
        assert clean["place"] == "國內"                                                          # 替身填的值有進結果（缺其他必填的回報不在這題要驗的範圍）
    finally:
        conn.close()


def test_update_does_not_reresolve_and_locked_keeps_the_stored_value(actors):
    """反向控制：validate_values 若忽略 prior（照建立那樣重填）⇒ applicant 變成修改者 ⇒ 這題紅。"""
    did = _dept()
    defn = ET._default_for("travel")
    conn = db.get_db()
    try:
        prior = {"applicant": actors["other"], "req_date": "2026-09-01", "dept": str(did)}
        data = {"applicant": "someone_else", "req_date": "", "dept": str(did), "cost_dept": str(did), "place": "國內", "city": "台北",
                "period": {"from": "2026-10-01", "to": "2026-10-02"}}
        clean, _l, _t, problems = ET.validate_values(conn, defn, data, [{"category": "交通", "summary": "高鐵", "amount": 10}],
                                                     viewer=actors["me"], prior=prior)
        assert clean["applicant"] == actors["other"], "修改時 locked 欄位要沿用舊值，不是換成修改的人"
        assert not clean.get("req_date"), "修改時不重新解析「今天」"
        assert any(p["key"] == "req_date" for p in problems), "req_date 必填：不重填就該回報缺值"
    finally:
        conn.close()


def test_update_with_a_registry_hands_prior_through_untouched(actors):
    calls = []
    ET._PREFILL_OVERRIDE = _stub(calls)
    did = _dept()
    defn = ET._default_for("travel")
    prior = {"applicant": actors["other"], "req_date": "2026-09-01"}
    conn = db.get_db()
    try:
        ET.validate_values(conn, defn, {"dept": str(did)}, [], viewer=actors["me"], prior=prior)
        assert [c for c in calls if c[0] == "fill"][0][1] == prior
    finally:
        conn.close()


def _insert_doc(conn, who, kind, data):
    conn.execute("INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, status, created_by,"
                 " created_by_name, created_at, updated_at, files_json, kind, data_json) VALUES ('-','x','d',1,'',1,1,'草稿',?,?,'2026-10-01','2026-10-01','[]',?,?)",
                 (who, who, kind, json.dumps(data, ensure_ascii=False)))


def test_last_value_hook_reads_only_my_latest_nonempty_value_for_this_type(client):
    # client：每題一個已建好 schema（含 case 模組表）的隔離庫。沒有它時，若這題是 xdist worker 的第一題，db.get_db() 連到預設路徑、
    # 建出空庫 ⇒ no such table: case_extra_expenses（第 46 班查明，origin/platform 同樣會；順序相依，不是產品問題）
    conn = db.get_db()
    try:
        _insert_doc(conn, "lv_me", "travel", {"place": "台北出差"})
        _insert_doc(conn, "lv_me", "travel", {"place": ""})                              # 較新但空 ⇒ 跳過
        _insert_doc(conn, "lv_other", "travel", {"place": "別人的"})
        _insert_doc(conn, "lv_me", "petty_cash", {"place": "別的類型"})
        conn.commit()
        fn = ET.last_value_hook("travel")
        assert fn(conn, {"username": "lv_me"}, "place") == "台北出差"
        assert fn(conn, {"username": "lv_nobody"}, "place") is None
        assert fn(conn, {"username": "lv_me"}, "missing_key") is None
        assert ET.last_value_hook("")(conn, {"username": "lv_me"}, "place") is None
        assert ET.last_value_hook("travel")(None, {"username": "lv_me"}, "place") is None           # 連線壞了 ⇒ None，不丟例外
    finally:
        conn.close()
