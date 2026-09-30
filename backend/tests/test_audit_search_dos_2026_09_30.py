# -*- coding: utf-8 -*-
"""歷史紀錄搜尋的成本上限（安全審查 W3 #5，2026-09-30）：LIKE 跳脫、輸入截斷、offset 上限、總數上限。"""
import pytest


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _insert_many(rows):
    import db
    c = db.get_db()
    try:
        c.executemany(
            "INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail,"
            "module,case_no,ref_no,result,reason_code,status_code) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        c.commit()
    finally:
        c.close()


def _row(i, label="t", user="u1"):
    return ("2026-09-01T10:00:00", 1, user, "U", "quotation.create", "quotation", "MQ-202609-001", label, "{}",
            "quotation", "MQ-202609-001", "", "ok", "", 0)


@pytest.fixture()
def auditor(client, make_user):
    u, p = make_user(username="dos_auditor", role="superadmin", modules=[])
    return _login(client, u, p)


def test_like_wildcards_in_q_are_literal(client, auditor):
    """`%`／`_` 是字面值：搜 `100%` 只找到含「100%」的列，不是全部。**反向控制**：拿掉跳脫 ⇒ 這題紅。"""
    _insert_many([_row(0, "折扣 100% 完成"), _row(1, "折扣 1000 完成"), _row(2, "a_b"), _row(3, "axb")])
    get = lambda q: client.get("/api/audit-log", params={"q": q}, headers=auditor).json()["items"]
    assert [i["target_label"] for i in get("100%")] == ["折扣 100% 完成"]
    assert [i["target_label"] for i in get("a_b")] == ["a_b"]
    assert len(get("%")) == 1 and get("%")[0]["target_label"] == "折扣 100% 完成"      # 單獨的 % 只匹配含 % 的列
    assert get("\\") == []                                                             # 反斜線不造成 SQL 錯誤


def test_user_prefix_wildcards_are_literal(client, auditor):
    _insert_many([_row(0, user="alice"), _row(1, user="al_ice"), _row(2, user="bob")])
    r = client.get("/api/audit-log", params={"user": "al_"}, headers=auditor).json()["items"]
    assert [i["username"] for i in r] == ["al_ice"]                                    # `_` 不是單字元萬用


def test_text_filters_are_truncated_to_100_chars(client, auditor):
    """超過 100 字的文字篩選值被截斷（**反向控制**：拿掉截斷 ⇒ 這題紅：200 字的 q 不再匹配前 100 字相同的那一列）。"""
    _insert_many([_row(0, "a" * 100)])
    hit = client.get("/api/audit-log", params={"q": "a" * 100 + "zzz"}, headers=auditor).json()["items"]
    assert [i["target_label"] for i in hit] == ["a" * 100]


def test_oversized_inputs_are_truncated_not_crashing(client, auditor):
    big = "x" * 8_000
    for k in ("q", "user", "action", "module", "case_no", "ref_no", "date_from", "date_to"):
        r = client.get("/api/audit-log", params={k: big}, headers=auditor)
        assert r.status_code == 200, (k, r.status_code)


def test_offset_is_capped_and_total_is_capped(client, auditor, monkeypatch):
    from routers import system as S
    monkeypatch.setattr(S, "_AUDIT_COUNT_CAP", 50)
    monkeypatch.setattr(S, "_AUDIT_OFFSET_MAX", 30)
    _insert_many([_row(i, "t%d" % i) for i in range(120)])
    j = client.get("/api/audit-log", params={"limit": 10}, headers=auditor).json()
    assert j["total"] == 50 and j["totalCapped"] is True                               # 只數到上限
    deep = client.get("/api/audit-log", params={"limit": 10, "offset": 10**9}, headers=auditor).json()
    same = client.get("/api/audit-log", params={"limit": 10, "offset": 30}, headers=auditor).json()
    assert [i["id"] for i in deep["items"]] == [i["id"] for i in same["items"]]         # offset 被夾到上限
    kept = client.get("/api/audit-log", params={"limit": 10, "before_id": j["items"][-1]["id"]}, headers=auditor).json()
    assert kept["items"] and kept["items"][0]["id"] < j["items"][-1]["id"]              # keyset 不受 offset 上限影響


def test_small_result_is_exact_and_not_marked_capped(client, auditor):
    base = client.get("/api/audit-log", headers=auditor).json()["total"]                 # 登入本身也留稽核列
    _insert_many([_row(i) for i in range(7)])
    j = client.get("/api/audit-log", headers=auditor).json()
    assert j["total"] == base + 7 and j["totalCapped"] is False
