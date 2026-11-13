# -*- coding: utf-8 -*-
"""一條龍 P4b（旗標 onepipe.entry_unify）：完工單「施工紀錄預填」`GET /api/completion-notes/case-prefill`。

- 旗標關 ⇒ 404（與端點不存在相同）；開 ⇒ `startDate`＝這個案件各階段出勤紀錄裡最早的一天、`workSummary`＝案件上的工作日誌逐行「日期　內容」。
- 唯讀：呼叫前後 work_logs／case_stage_visits／completion_notes 列數不變。
- 負向（紀錄不因此變得可看）：與建立完工單同一道閘＝管理員；現場人員（即使是案件成員）403、沒登入 401／403；
  不存在的案件 404；回應只有 startDate、workSummary 兩個鍵（沒有時數、照片、記錄人、金額）；別的案件的日誌不混進來。
- 上限：筆數與字數超過 ⇒ 截斷並加「…（其餘請見案件動態）」。
"""
import json

from tests._requires import requires_module

pytestmark = requires_module("case", "本檔打 M01（案件）的完工單預填端點")

NO = "MQ-P4B-001"
OTHER = "MQ-P4B-002"
URL = "/api/completion-notes/case-prefill"


def _flag(monkeypatch, on):
    from helpers import onepipe_flags
    monkeypatch.setattr(onepipe_flags, "flag_on", lambda field, conn=None: bool(on) and field == "entry_unify")


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _uid(username):
    import db
    c = db.get_db()
    try:
        return c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
    finally:
        c.close()


def _seed(assigned=(), visits=(), logs=(), no=NO):
    """visits＝[(日期, 人次)]（全放同一個階段）；logs＝[(日期, 內容)]；logs 的內容含 amount 之類的欄位無關——work_logs 只有日期、內容、時數、照片。"""
    import db
    now = "2026-01-01T00:00:00"
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (no, "已送出", "預填客戶", "預填工程", 424242, 400000, json.dumps({"dealTag": "已成案"}, ensure_ascii=False), now, now, "已成案",
                   json.dumps([_uid(u) for u in assigned])))
        cur = c.execute("INSERT INTO case_stages (quote_no, label, sort_order, created_at, updated_at) VALUES (?,?,?,?,?)", (no, "施工", 1, now, now))
        sid = cur.lastrowid
        for d, n in visits:
            c.execute("INSERT INTO case_stage_visits (stage_id, visit_date, visit_people, note, created_at) VALUES (?,?,?,?,?)", (sid, d, n, "", now))
        uid = c.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
        for d, t in logs:
            c.execute("INSERT INTO work_logs (log_date, user_id, content, hours, created_at, created_by, case_no) VALUES (?,?,?,?,?,?,?)", (d, uid, t, 7.5, now, uid, no))
        c.commit()
    finally:
        c.close()


def _counts():
    import db
    c = db.get_db()
    try:
        return tuple(c.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in ("work_logs", "case_stage_visits", "completion_notes"))
    finally:
        c.close()


def _admin(make_user, client, name="p4b_adm"):
    return _login(client, *make_user(username=name, role="admin"))


def test_flag_off_is_404_like_a_missing_route(client, make_user, monkeypatch):
    _flag(monkeypatch, False)
    h = _admin(make_user, client)
    _seed(visits=[("2026-03-02", 2)], logs=[("2026-03-02", "拉線")])
    r = client.get(URL, params={"quote_no": NO}, headers=h)
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


def test_flag_on_prefills_earliest_visit_and_logs_in_date_order(client, make_user, monkeypatch):
    _flag(monkeypatch, True)
    h = _admin(make_user, client)
    _seed(visits=[("2026-03-05", 2), ("2026-03-02", 3), ("", 1)],
          logs=[("2026-03-05", "收尾\n清潔"), ("2026-03-02", "拉線  到二樓"), ("2026-03-03", "   ")])
    _seed(no=OTHER, visits=[("2025-01-01", 9)], logs=[("2025-01-01", "別的案件")])
    before = _counts()
    r = client.get(URL, params={"quote_no": NO}, headers=h)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["startDate"] == "2026-03-02"
    assert b["workSummary"].split("\n") == ["2026-03-02　拉線 到二樓", "2026-03-05　收尾 清潔"], "依日期排序、內容壓成一行、空內容略過"
    assert "別的案件" not in b["workSummary"]
    assert set(b) == {"startDate", "workSummary"}, "回應只有日期與日誌文字"
    assert "7.5" not in json.dumps(b) and "424242" not in json.dumps(b)
    assert _counts() == before, "唯讀：不寫任何東西"


def test_no_records_gives_empty_strings(client, make_user, monkeypatch):
    _flag(monkeypatch, True)
    h = _admin(make_user, client)
    _seed()
    assert client.get(URL, params={"quote_no": NO}, headers=h).json() == {"startDate": "", "workSummary": ""}


def test_site_staff_member_and_anonymous_and_missing_case_are_refused(client, make_user, monkeypatch):
    _flag(monkeypatch, True)
    staff = make_user(username="p4b_staff", role="engineer", modules=["case_manage"])
    _seed(assigned=["p4b_staff"], logs=[("2026-03-02", "拉線")])
    hs = _login(client, *staff)
    assert client.get(URL, params={"quote_no": NO}, headers=hs).status_code == 403, "案件成員的現場人員也不因此看到預填（與建立完工單同一道閘）"
    assert client.get(URL, params={"quote_no": NO}).status_code in (401, 403)
    h = _admin(make_user, client)
    assert client.get(URL, params={"quote_no": "NO-SUCH-CASE"}, headers=h).status_code == 404
    assert client.get(URL, headers=h).status_code == 422


def test_long_logs_are_truncated_with_a_pointer_to_the_case_feed(client, make_user, monkeypatch):
    from modules.case.api import completion_notes as cn
    _flag(monkeypatch, True)
    h = _admin(make_user, client)
    _seed(logs=[("2026-03-%02d" % (i % 28 + 1), "工" * 300) for i in range(12)])
    ws = client.get(URL, params={"quote_no": NO}, headers=h).json()["workSummary"]
    assert ws.endswith("…（其餘請見案件動態）")
    assert len(ws) <= cn._PREFILL_MAX_CHARS + 40
