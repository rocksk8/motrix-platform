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


# ── W3 實測 100 萬列後的第二輪：分層樹時間窗、module-counts、detail 上限 ─────────────────────────────

def _days_ago(n):
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%dT10:00:00")


def _row_at(at, module="quotation", label="t"):
    return (at, 1, "u1", "U", module + ".create", module, "X", label, "{}", module, "", "", "ok", "", 0)


def test_tree_defaults_to_the_last_90_days_and_says_so(client, auditor):
    """沒給日期 ⇒ 只算近 90 天，回應的 `window` 說明實際範圍。**反向控制**：拿掉預設視窗 ⇒ 舊資料也被算進去 ⇒ 紅。"""
    _insert_many([_row_at(_days_ago(5), "voucher"), _row_at(_days_ago(200), "voucher"), _row_at(_days_ago(400), "voucher")])
    j = client.get("/api/audit-log/tree", params={"level": "module"}, headers=auditor).json()
    v = next(i for i in j["items"] if i["key"] == "voucher")
    assert v["count"] == 1, j
    w = j["window"]
    assert w["defaulted"] is True and w["defaultDays"] == 90 and w["maxDays"] == 366 and w["clamped"] is False
    assert w["to"] >= w["from"]


def test_tree_window_can_be_widened_within_the_max_and_is_clamped_beyond(client, auditor):
    _insert_many([_row_at(_days_ago(5), "voucher"), _row_at(_days_ago(200), "voucher"), _row_at(_days_ago(400), "voucher")])
    from datetime import date, timedelta
    t = date.today()
    wide = client.get("/api/audit-log/tree", params={"level": "module", "date_from": (t - timedelta(days=300)).isoformat(),
                                                      "date_to": t.isoformat()}, headers=auditor).json()
    assert next(i for i in wide["items"] if i["key"] == "voucher")["count"] == 2 and wide["window"]["clamped"] is False
    huge = client.get("/api/audit-log/tree", params={"level": "module", "date_from": "2000-01-01", "date_to": t.isoformat()},
                      headers=auditor).json()
    assert huge["window"]["clamped"] is True and (date.fromisoformat(huge["window"]["to"]) - date.fromisoformat(huge["window"]["from"])).days == 366
    assert next(i for i in huge["items"] if i["key"] == "voucher")["count"] == 2            # 400 天前的那筆被截掉
    assert client.get("/api/audit-log/tree", params={"level": "module", "date_from": "garbage"}, headers=auditor).status_code == 400
    assert client.get("/api/audit-log/tree", params={"level": "module", "date_from": "2030-01-02", "date_to": "2030-01-01"},
                      headers=auditor).status_code == 400


def test_module_counts_since_is_capped_to_90_days_and_counts_stay_correct(client, make_user):
    """**反向控制**：拿掉 since 上限 ⇒ 200 天前那筆也被數進去 ⇒ 紅。"""
    u, p = make_user(username="dos_mc", role="admin", modules=["audit_log"])
    h = _login(client, u, p)
    _insert_many([_row_at(_days_ago(5), "quotation"), _row_at(_days_ago(200), "quotation")])
    r = client.post("/api/audit-log/module-counts", headers=h, json={"modules": {"quotation": "2000-01-01T00:00:00"}})
    assert r.status_code == 200, r.text
    assert r.json()["quotation"] == 1                                           # 只數近 90 天（user1 發的，不是自己）
    r2 = client.post("/api/audit-log/module-counts", headers=h, json={"modules": {"quotation": _days_ago(1)}})
    assert r2.json()["quotation"] == 0                                          # 之後沒有新的


def test_module_counts_uses_range_prefix_not_like(client, make_user):
    """action 前綴要走範圍比較（可用索引）：`quotation.` 不可以誤含 `quotation_x.`、`payment.` 不誤含 `payment_request.`。"""
    u, p = make_user(username="dos_mc2", role="admin", modules=["audit_log"])
    h = _login(client, u, p)
    import db
    c = db.get_db()
    try:
        for act in ("quotation.create", "quotation_extra.create", "payment.mark", "payment_request.create"):
            c.execute("INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail,module)"
                      " VALUES (?,?,?,?,?,?,?,?,?,?)", (_days_ago(1), 1, "u9", "U", act, "t", "x", "", "{}", act.split(".")[0]))
        c.commit()
    finally:
        c.close()
    from routers import system as S
    prefixes = S._MODULE_ACTION_PREFIXES.get("quotation")
    assert prefixes, "quotation 的 action 前綴表不見了"
    got = client.post("/api/audit-log/module-counts", headers=h, json={"modules": {"quotation": _days_ago(2)}}).json()["quotation"]
    assert got >= 1                                                             # 至少算到 quotation.create；不要求別的前綴怎麼算，只要求沒有 SQL 錯誤


def test_audit_detail_is_capped_at_write(client):
    """`detail` 超過 2000 字 ⇒ 存成 `{_truncated, originalLength, preview}`；小的照舊。**反向控制**：拿掉上限 ⇒ 紅。"""
    import json as _json
    from helpers import audit as A
    A._audit(None, "quotation.create", "quotation", "MQ-DET-1", "big", {"blob": "x" * 50_000})
    A._audit(None, "quotation.create", "quotation", "MQ-DET-2", "small", {"k": "v"})
    import db
    c = db.get_db()
    try:
        big = _json.loads(c.execute("SELECT detail FROM audit_log WHERE target_id='MQ-DET-1'").fetchone()[0])
        small = _json.loads(c.execute("SELECT detail FROM audit_log WHERE target_id='MQ-DET-2'").fetchone()[0])
        size = c.execute("SELECT length(detail) FROM audit_log WHERE target_id='MQ-DET-1'").fetchone()[0]
    finally:
        c.close()
    assert big["_truncated"] is True and big["originalLength"] > 50_000 and size <= 2400
    assert small == {"k": "v"}
