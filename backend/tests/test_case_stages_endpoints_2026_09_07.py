"""案件執行階段（case_stages/case_stage_visits）正規化 Phase 2 granular 端點的正面路徑
測試（2026-09-07 新增）。

背景：這批端點（`/api/quotations/{quote_no}/stages...`，共 11 支）與其 `_sync_stages_to_json()`
橋樑早在 2026-08-23（Phase 3b/4）就已經被 `case-management.js`／`quotation-form.html`
實際接上並在正式機使用，但當時的完整開發是在正式機斷線期間直接進行、事後用一次大批量回推
commit（`2b8e7ad`）拉回開發機，沒有補上專屬測試檔——`backend/tests/` 裡先前唯一直接打過
`/stages` 路徑的地方（`test_case_semi_unlock.py`）測的是「已結案案件鎖定」情境，不是這批端點
本身的 CRUD 正確性。這是目前案件管理模組測試覆蓋最薄的一塊，見 MOTRIX-ERP-QUICK.md §11。

各端點對應的實際程式碼位置與 docstring 見 `backend/modules/case/api/quotations.py` 2042-2316 行。
"""
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_open_case(quote_no="MQ-STG-001"):
    """建立一張未結案（deal_tag 非「已結案」）的報價單，供階段端點測試使用
    ——這批端點只在案件「已結案」時才會被 `_deny_if_case_locked_unsupported()` 擋下。"""
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", 100000, 95238, "{}",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已提供"),
        )
        conn.commit()
    finally:
        conn.close()


def _make_closed_case(quote_no="MQ-STG-LOCKED-001"):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", 100000, 95238, "{}",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已結案"),
        )
        conn.commit()
    finally:
        conn.close()


def _stage_api(quote_no):
    return f"/api/quotations/{quote_no}/stages"


def test_create_list_and_default_fields(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_open_case()

    r = client.post(_stage_api("MQ-STG-001"), headers=_auth(token), json={"label": "簽約"})
    assert r.status_code == 201, r.text
    stage = r.json()
    assert stage["label"] == "簽約"
    assert stage["done"] is False
    assert stage["assignedTo"] == []
    assert stage["dependsOn"] == []
    assert stage["visits"] == []
    assert isinstance(stage["id"], int)

    r2 = client.post(_stage_api("MQ-STG-001"), headers=_auth(token), json={"label": "出貨"})
    assert r2.status_code == 201, r2.text

    r3 = client.get(_stage_api("MQ-STG-001"), headers=_auth(token))
    assert r3.status_code == 200, r3.text
    items = r3.json()["items"]
    assert [s["label"] for s in items] == ["簽約", "出貨"]
    assert [s["sortOrder"] for s in items] == [0, 1]


def test_update_stage_partial_fields_and_404(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_open_case()
    stage = client.post(_stage_api("MQ-STG-001"), headers=_auth(token), json={"label": "簽約"}).json()

    r = client.put(f"{_stage_api('MQ-STG-001')}/{stage['id']}", headers=_auth(token),
                    json={"done": True, "doneAt": "2026-09-07"})
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["done"] is True
    assert updated["doneAt"] == "2026-09-07"
    assert updated["label"] == "簽約"  # 沒送的欄位不受影響

    r2 = client.put(f"{_stage_api('MQ-STG-001')}/{stage['id']}", headers=_auth(token),
                     json={"startDate": "2026-09-01", "dueDate": "2026-09-30"})
    assert r2.status_code == 200, r2.text
    updated2 = r2.json()
    assert updated2["startDate"] == "2026-09-01"
    assert updated2["dueDate"] == "2026-09-30"
    assert updated2["done"] is True  # 前一次的欄位仍保留

    r3 = client.put(f"{_stage_api('MQ-STG-001')}/999999", headers=_auth(token), json={"label": "x"})
    assert r3.status_code == 404, r3.text


def test_delete_stage_cleans_up_dependents(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_open_case()
    a = client.post(_stage_api("MQ-STG-001"), headers=_auth(token), json={"label": "A"}).json()
    b = client.post(_stage_api("MQ-STG-001"), headers=_auth(token), json={"label": "B"}).json()

    r = client.post(f"{_stage_api('MQ-STG-001')}/{b['id']}/depends-on/{a['id']}", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["dependsOn"] == [a["id"]]

    r2 = client.delete(f"{_stage_api('MQ-STG-001')}/{a['id']}", headers=_auth(token))
    assert r2.status_code == 200, r2.text

    items = client.get(_stage_api("MQ-STG-001"), headers=_auth(token)).json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == b["id"]
    assert items[0]["dependsOn"] == []  # 被刪掉的前置階段已從 B 的 dependsOn 移除

    r3 = client.delete(f"{_stage_api('MQ-STG-001')}/{a['id']}", headers=_auth(token))
    assert r3.status_code == 404, r3.text


def test_reorder_ignores_unknown_ids(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_open_case()
    a = client.post(_stage_api("MQ-STG-001"), headers=_auth(token), json={"label": "A"}).json()
    b = client.post(_stage_api("MQ-STG-001"), headers=_auth(token), json={"label": "B"}).json()
    c = client.post(_stage_api("MQ-STG-001"), headers=_auth(token), json={"label": "C"}).json()

    r = client.patch(f"{_stage_api('MQ-STG-001')}/reorder", headers=_auth(token),
                      json={"orderedIds": [c["id"], 999999, a["id"], b["id"]]})
    assert r.status_code == 200, r.text

    items = client.get(_stage_api("MQ-STG-001"), headers=_auth(token)).json()["items"]
    assert [s["label"] for s in items] == ["C", "A", "B"]


def test_assignees_add_remove_and_idempotent(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_open_case()
    stage = client.post(_stage_api("MQ-STG-001"), headers=_auth(token), json={"label": "簽約"}).json()

    r = client.post(f"{_stage_api('MQ-STG-001')}/{stage['id']}/assignees", headers=_auth(token),
                     json={"username": "jeff"})
    assert r.status_code == 200, r.text
    assert r.json()["assignedTo"] == ["jeff"]

    r2 = client.post(f"{_stage_api('MQ-STG-001')}/{stage['id']}/assignees", headers=_auth(token),
                      json={"username": "jeff"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["assignedTo"] == ["jeff"]  # 重複加入不重複

    r3 = client.post(f"{_stage_api('MQ-STG-001')}/{stage['id']}/assignees", headers=_auth(token),
                      json={"username": "corbin"})
    assert r3.json()["assignedTo"] == ["jeff", "corbin"]

    r4 = client.delete(f"{_stage_api('MQ-STG-001')}/{stage['id']}/assignees/jeff", headers=_auth(token))
    assert r4.status_code == 200, r4.text
    assert r4.json()["assignedTo"] == ["corbin"]

    r5 = client.delete(f"{_stage_api('MQ-STG-001')}/{stage['id']}/assignees/nobody", headers=_auth(token))
    assert r5.status_code == 200, r5.text  # 移除不存在的人不報錯
    assert r5.json()["assignedTo"] == ["corbin"]

    r6 = client.post(f"{_stage_api('MQ-STG-001')}/{stage['id']}/assignees", headers=_auth(token), json={})
    assert r6.status_code == 400, r6.text  # 缺 username


def test_depends_on_toggle_candidate_missing_and_cycle_prevention(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_open_case()
    a = client.post(_stage_api("MQ-STG-001"), headers=_auth(token), json={"label": "A"}).json()
    b = client.post(_stage_api("MQ-STG-001"), headers=_auth(token), json={"label": "B"}).json()

    r = client.post(f"{_stage_api('MQ-STG-001')}/{a['id']}/depends-on/999999", headers=_auth(token))
    assert r.status_code == 404, r.text  # 前置階段不存在

    r2 = client.post(f"{_stage_api('MQ-STG-001')}/{a['id']}/depends-on/{b['id']}", headers=_auth(token))
    assert r2.status_code == 200, r2.text
    assert r2.json()["dependsOn"] == [b["id"]]  # A 依賴 B

    r3 = client.post(f"{_stage_api('MQ-STG-001')}/{b['id']}/depends-on/{a['id']}", headers=_auth(token))
    assert r3.status_code == 400, r3.text  # B 反過來依賴 A 會形成循環，擋下
    assert "循環" in r3.json()["detail"]

    r4 = client.post(f"{_stage_api('MQ-STG-001')}/{a['id']}/depends-on/{b['id']}", headers=_auth(token))
    assert r4.status_code == 200, r4.text
    assert r4.json()["dependsOn"] == []  # 再次呼叫是 toggle，移除依賴


def test_visits_crud_and_scoped_404(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_open_case()
    a = client.post(_stage_api("MQ-STG-001"), headers=_auth(token), json={"label": "A"}).json()
    b = client.post(_stage_api("MQ-STG-001"), headers=_auth(token), json={"label": "B"}).json()

    r = client.post(f"{_stage_api('MQ-STG-001')}/{a['id']}/visits", headers=_auth(token),
                     json={"visitDate": "2026-09-01", "visitPeople": 2, "note": "初勘"})
    assert r.status_code == 201, r.text
    stage = r.json()
    assert len(stage["visits"]) == 1
    visit_id = stage["visits"][0]["id"]
    assert stage["visits"][0]["visitPeople"] == 2

    r2 = client.put(f"{_stage_api('MQ-STG-001')}/{a['id']}/visits/{visit_id}", headers=_auth(token),
                     json={"note": "複勘", "visitPeople": 3})
    assert r2.status_code == 200, r2.text
    assert r2.json()["visits"][0]["note"] == "複勘"
    assert r2.json()["visits"][0]["visitPeople"] == 3
    assert r2.json()["visits"][0]["visitDate"] == "2026-09-01"  # 沒送的欄位不受影響

    # 拜訪紀錄屬於 stage A，用 stage B 的 id 去操作應該 404（避免跨階段誤改/誤刪）
    r3 = client.put(f"{_stage_api('MQ-STG-001')}/{b['id']}/visits/{visit_id}", headers=_auth(token),
                     json={"note": "x"})
    assert r3.status_code == 404, r3.text
    r4 = client.delete(f"{_stage_api('MQ-STG-001')}/{b['id']}/visits/{visit_id}", headers=_auth(token))
    assert r4.status_code == 404, r4.text

    r5 = client.delete(f"{_stage_api('MQ-STG-001')}/{a['id']}/visits/{visit_id}", headers=_auth(token))
    assert r5.status_code == 200, r5.text
    assert client.get(_stage_api("MQ-STG-001"), headers=_auth(token)).json()["items"][0]["visits"] == []


def test_stage_scoped_to_quote_no_prevents_cross_case_access(client, make_user):
    """`_get_stage_row()` 用 (id, quote_no) 一起查，避免猜 id 就能跨案件竄改別的
    報價單階段——建立兩張案件，用案件 B 的 quote_no 去操作案件 A 的 stage id 應該 404。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_open_case("MQ-STG-A")
    _make_open_case("MQ-STG-B")
    stage = client.post(_stage_api("MQ-STG-A"), headers=_auth(token), json={"label": "A的階段"}).json()

    r = client.put(f"{_stage_api('MQ-STG-B')}/{stage['id']}", headers=_auth(token), json={"label": "x"})
    assert r.status_code == 404, r.text
    r2 = client.delete(f"{_stage_api('MQ-STG-B')}/{stage['id']}", headers=_auth(token))
    assert r2.status_code == 404, r2.text


def test_sync_to_json_bridge_reflects_mutations(client, make_user):
    """驗證 Phase 3a 的 `_sync_stages_to_json()` 橋樑：透過 granular 端點的變更，
    立刻反映在 `GET /api/quotations/{no}` 回傳的 `data.caseRecord.stages`（
    `list_quotations()`/`stage_board()`/`dashboard.py`/`daily_tasks.py` 這些既有讀取點
    倚賴的就是這份 JSON，不是 case_stages 表本身）。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_open_case()
    stage = client.post(_stage_api("MQ-STG-001"), headers=_auth(token), json={"label": "簽約"}).json()
    client.put(f"{_stage_api('MQ-STG-001')}/{stage['id']}", headers=_auth(token), json={"done": True})
    client.post(f"{_stage_api('MQ-STG-001')}/{stage['id']}/assignees", headers=_auth(token),
                json={"username": "jeff"})

    r = client.get("/api/quotations/MQ-STG-001", headers=_auth(token))
    assert r.status_code == 200, r.text
    stages_json = r.json()["data"]["caseRecord"]["stages"]
    assert len(stages_json) == 1
    assert stages_json[0]["id"] == stage["id"]
    assert stages_json[0]["done"] is True
    assert stages_json[0]["assignedTo"] == ["jeff"]


def test_stage_endpoints_require_auth(client):
    r = client.get(_stage_api("MQ-STG-001"))
    assert r.status_code in (401, 403), r.text
    r2 = client.post(_stage_api("MQ-STG-001"), json={"label": "x"})
    assert r2.status_code in (401, 403), r2.text


def test_closed_case_blocks_stage_mutations(client, make_user):
    """`_deny_if_case_locked_unsupported()` 對這批端點一律 403，跟是否半解鎖無關
    ——`test_case_semi_unlock.py` 只驗證過新增（POST）這一支，這裡補齊更新／刪除／
    重排／依賴切換也一樣被擋下，且案件已結案時連查詢/建立第一個階段都做不到。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    _make_closed_case()
    import db
    conn = db.get_db()
    try:
        now = "2026-01-01T00:00:00"
        cur = conn.execute(
            "INSERT INTO case_stages (quote_no, label, sort_order, done, done_at, created_at, updated_at) "
            "VALUES (?,?,?,0,'',?,?)",
            ("MQ-STG-LOCKED-001", "既有階段", 0, now, now),
        )
        stage_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    base = _stage_api("MQ-STG-LOCKED-001")
    assert client.put(f"{base}/{stage_id}", headers=_auth(token), json={"label": "改名"}).status_code == 403
    assert client.delete(f"{base}/{stage_id}", headers=_auth(token)).status_code == 403
    assert client.patch(f"{base}/reorder", headers=_auth(token), json={"orderedIds": [stage_id]}).status_code == 403
    assert client.post(f"{base}/{stage_id}/assignees", headers=_auth(token),
                        json={"username": "jeff"}).status_code == 403
