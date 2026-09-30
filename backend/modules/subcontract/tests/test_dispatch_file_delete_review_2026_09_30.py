"""N1（2026-09-30）：承攬商報價單附件刪除＝申請刪除、要審核（走案件既有簽核層級：報價單的流程設定）。

- 核可前檔案保留並帶 deleteRequest（畫面標「刪除待審」）；核可（走完全部簽核層）才刪檔；退回＝清掉申請、檔案留著。
- 沒設簽核層：最高管理者自己申請 ⇒ 直接刪（舊行為）；其他管理員申請 ⇒ 只有最高管理者能核可。
- 有簽核層：只有當層排序最前的未簽人能核可／退回；同一檔案重複申請 409。
"""
import io
import json

from modules.subcontract.tests.test_dispatch_file_uploads import _auth, _login, _make_dispatch, _png_file


def _upload(client, token, did):
    r = client.post(f"/api/contractor-dispatches/{did}/files", headers=_auth(token), files={"files": _png_file()})
    assert r.status_code == 201, r.text
    return r.json()["files"][0]["id"]


def _files(client, token, did):
    return client.get(f"/api/contractor-dispatches/{did}", headers=_auth(token)).json()["files"]


def _set_flow(tiers):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                     ("unified_approval_flow", json.dumps({"includeSubmitterManagerTier": False, "tiers": tiers}),
                      "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def test_admin_request_stays_until_superadmin_approves_when_no_tiers(client, make_user):
    a, apw = make_user(username="n1_admin", role="admin")
    s, spw = make_user(username="n1_boss", role="superadmin")
    ta, ts = _login(client, a, apw), _login(client, s, spw)
    did = _make_dispatch(client, ta, "MQ-N1-001")
    fid = _upload(client, ta, did)
    url = f"/api/contractor-dispatches/{did}/files/{fid}"
    r = client.request("DELETE", url, headers=_auth(ta), json={"reason": "傳錯檔"})
    assert r.status_code == 200 and r.json()["pending"] is True and r.json()["deleted"] is False, r.text
    f = _files(client, ta, did)
    assert len(f) == 1 and f[0]["deleteRequest"]["reason"] == "傳錯檔" and f[0]["deleteRequest"]["requestedBy"] == "n1_admin"
    # 重複申請
    assert client.request("DELETE", url, headers=_auth(ta), json={"reason": "x"}).status_code == 409
    # 申請人（一般管理員）自己不能核可
    assert client.post(url + "/delete-approve", headers=_auth(ta)).status_code == 403
    # 最高管理者核可 ⇒ 刪檔
    r = client.post(url + "/delete-approve", headers=_auth(ts))
    assert r.status_code == 200 and r.json()["deleted"] is True, r.text
    assert _files(client, ta, did) == []
    # 已沒有待審的申請
    assert client.post(url + "/delete-approve", headers=_auth(ts)).status_code == 409


def test_reject_keeps_file_and_clears_request(client, make_user):
    a, apw = make_user(username="n1_admin", role="admin")
    s, spw = make_user(username="n1_boss", role="superadmin")
    ta, ts = _login(client, a, apw), _login(client, s, spw)
    did = _make_dispatch(client, ta, "MQ-N1-002")
    fid = _upload(client, ta, did)
    url = f"/api/contractor-dispatches/{did}/files/{fid}"
    assert client.request("DELETE", url, headers=_auth(ta), json={"reason": "重複"}).status_code == 200
    r = client.post(url + "/delete-reject", headers=_auth(ts), json={"note": "還要用"})
    assert r.status_code == 200, r.text
    f = _files(client, ta, did)
    assert len(f) == 1 and "deleteRequest" not in f[0]
    assert client.post(url + "/delete-reject", headers=_auth(ts)).status_code == 409


def test_superadmin_without_tiers_deletes_directly(client, make_user):
    s, spw = make_user(username="n1_boss", role="superadmin")
    ts = _login(client, s, spw)
    did = _make_dispatch(client, ts, "MQ-N1-003")
    fid = _upload(client, ts, did)
    r = client.request("DELETE", f"/api/contractor-dispatches/{did}/files/{fid}", headers=_auth(ts), json={})
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert _files(client, ts, did) == []


def test_with_tiers_only_current_approver_decides_and_all_tiers_needed(client, make_user):
    a, apw = make_user(username="n1_admin", role="admin")
    m1, m1pw = make_user(username="n1_mgr1", role="admin")
    m2, m2pw = make_user(username="n1_mgr2", role="admin")
    ta, t1, t2 = _login(client, a, apw), _login(client, m1, m1pw), _login(client, m2, m2pw)
    import db
    conn = db.get_db()
    try:
        ids = {r["username"]: r["id"] for r in conn.execute("SELECT id, username FROM users")}
    finally:
        conn.close()
    _set_flow([{"order": 0, "approvers": [{"userId": ids[m1], "username": m1, "displayName": "主管一"}]},
               {"order": 1, "approvers": [{"userId": ids[m2], "username": m2, "displayName": "主管二"}]}])
    did = _make_dispatch(client, ta, "MQ-N1-004")
    fid = _upload(client, ta, did)
    url = f"/api/contractor-dispatches/{did}/files/{fid}"
    assert client.request("DELETE", url, headers=_auth(ta), json={"reason": "改版"}).status_code == 200
    assert client.post(url + "/delete-approve", headers=_auth(ta)).status_code == 403          # 申請人不是簽核人
    assert client.post(url + "/delete-approve", headers=_auth(t2)).status_code == 403          # 第二層還沒輪到
    r = client.post(url + "/delete-approve", headers=_auth(t1))
    assert r.status_code == 200 and r.json()["deleted"] is False, r.text                       # 第一層簽完、檔案還在
    assert len(_files(client, ta, did)) == 1
    assert client.post(url + "/delete-approve", headers=_auth(t1)).status_code == 403          # 第一層不能再簽第二層
    r = client.post(url + "/delete-approve", headers=_auth(t2))
    assert r.status_code == 200 and r.json()["deleted"] is True, r.text
    assert _files(client, ta, did) == []
    _set_flow([])


def test_delete_request_is_audited(client, make_user):
    a, apw = make_user(username="n1_admin", role="admin")
    ta = _login(client, a, apw)
    did = _make_dispatch(client, ta, "MQ-N1-005")
    fid = _upload(client, ta, did)
    assert client.request("DELETE", f"/api/contractor-dispatches/{did}/files/{fid}", headers=_auth(ta),
                          json={"reason": "稽核用"}).status_code == 200
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT target_label FROM audit_log WHERE action='vendor.dispatch.delete_file_request'").fetchone()
    finally:
        conn.close()
    assert row and "稽核用" in row["target_label"]


def test_requester_cannot_decide_own_delete_request(client, make_user):
    """M4：申請人（有簽核層、自己剛好是簽核人）不能核可／退回自己的申請；反向控制：另一位簽核人可以。"""
    a, apw = make_user(username="own_admin", role="admin")
    m, mpw = make_user(username="own_mgr", role="admin")
    ta, tm = _login(client, a, apw), _login(client, m, mpw)
    import db
    conn = db.get_db()
    try:
        ids = {r["username"]: r["id"] for r in conn.execute("SELECT id, username FROM users")}
    finally:
        conn.close()
    _set_flow([{"order": 0, "approvers": [{"userId": ids[a], "username": a, "displayName": "甲"},
                                          {"userId": ids[m], "username": m, "displayName": "乙"}]}])
    did = _make_dispatch(client, ta, "MQ-N1-006")
    fid = _upload(client, ta, did)
    url = f"/api/contractor-dispatches/{did}/files/{fid}"
    assert client.request("DELETE", url, headers=_auth(ta), json={"reason": "r"}).status_code == 200
    assert client.post(url + "/delete-approve", headers=_auth(ta)).status_code == 403
    assert client.post(url + "/delete-reject", headers=_auth(ta)).status_code == 403
    assert len(_files(client, ta, did)) == 1 and _files(client, ta, did)[0].get("deleteRequest")
    _set_flow([])


def _queue_items(client, token):
    body = client.get("/api/approval-queue", headers=_auth(token)).json()
    items = [i for g in body["queue"] for i in g["items"]]          # 依送審人分組
    return [i for i in items if i.get("type") == "dispatch_file_delete"]


def test_delete_request_goes_into_approval_queue_and_detail(client, make_user):
    """簽核佇列：待審的刪除申請是一張卡（type dispatch_file_delete）；佇列詳情可開；count 計入；核可後從佇列消失。"""
    a, apw = make_user(username="q_admin", role="admin")
    s, spw = make_user(username="q_boss", role="superadmin")
    ta, ts = _login(client, a, apw), _login(client, s, spw)
    import db
    conn = db.get_db()
    try:                                     # 佇列只列「案件真的存在」的單（孤兒單不列），所以要有這個案件
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
                     " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     ("MQ-N1-007", "已送出", "佇列客", "佇列專案", 1, 1, "{}", "2026-01-01T00:00:00",
                      "2026-01-01T00:00:00", "已成案", "2026-06-01"))
        conn.commit()
    finally:
        conn.close()
    did = _make_dispatch(client, ta, "MQ-N1-007")
    fid = _upload(client, ta, did)
    url = f"/api/contractor-dispatches/{did}/files/{fid}"
    assert client.request("DELETE", url, headers=_auth(ta), json={"reason": "佇列題"}).status_code == 200
    mine = _queue_items(client, ts)
    assert len(mine) == 1 and mine[0]["quoteNo"] == f"{did}:{fid}" and mine[0]["linkedQuoteNo"] == "MQ-N1-007"
    assert mine[0]["dispatchId"] == did and mine[0]["fileId"] == fid and mine[0]["reason"] == "佇列題"
    d = client.get("/api/approval-queue/detail", params={"type": "dispatch_file_delete", "id": f"{did}:{fid}"},
                   headers=_auth(ts))
    assert d.status_code == 200, d.text
    assert any(f["value"] == "佇列題" for f in d.json()["fields"]) and d.json()["files"]
    c = client.get("/api/approval-queue/count", headers=_auth(ts))
    assert c.status_code == 200, c.text
    assert client.post(url + "/delete-approve", headers=_auth(ts)).status_code == 200
    assert _queue_items(client, ts) == []
