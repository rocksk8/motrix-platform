"""U8（2026-11-14）案件記錄存檔的稽核：空存檔不留「案件更新」，有改動的那筆記下改了哪些分段／欄位。

正式機 90 天有 286 筆「案件更新」，同一人 10 分鐘內 >3 次出現 27 個時段；查程式碼＋沙箱量測：
自動存檔（打字停 1.5 秒）本來就是一次一筆，另外「沒改任何東西按儲存」也各留一筆空稽核（detail 為 {}）。
裁示：沒有變動 ⇒ 不寫入、不備份、不記稽核；稽核 detail 放實際變動的分段／欄位；
**不合併**（稽核一事件一筆、時間完整）。
"""
from tests._requires import requires_module  # noqa: E402
import json

pytestmark = requires_module("case", "打 M01（案件）的 case-record 端點")

NO = "MQ-202611-801"


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _seed():
    import db
    cr = {"payment": {"items": [{"id": 1, "type": "訂金款", "pct": 30, "amount": 30000.0, "received": False, "note": ""}]},
          "materials": [{"id": 1, "name": "原料", "qty": 1}],
          "contract": {"signed": False, "terms": "", "amount": 100},
          "stages": [{"id": 9, "label": "伺服器階段"}]}
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json,"
            " created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客", "案", json.dumps({"caseRecord": cr}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        conn.commit()
    finally:
        conn.close()
    return cr


def _rows():
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM audit_log WHERE action='case.update' AND target_id=? ORDER BY id", (NO,)).fetchall()]
    finally:
        conn.close()


def _updated_at():
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT updated_at FROM quotations WHERE quote_no=?", (NO,)).fetchone()["updated_at"]
    finally:
        conn.close()


def _patch(client, h, body):
    return client.patch(f"/api/quotations/{NO}/case-record", json=body, headers=h)


def test_noop_segment_save_writes_nothing_and_keeps_response_shape(client, make_user, monkeypatch):
    import modules.case.api.quotations as Q
    backups = []
    monkeypatch.setattr(Q, "_backup_quotation", lambda no: backups.append(no))
    h = _login(client, *make_user(username="u8a", role="superadmin"))
    cr = _seed()
    before = _updated_at()
    for _ in range(3):                                                    # 連按三次「儲存」、什麼都沒改
        r = _patch(client, h, {"segments": {"materials": cr["materials"]}, "base": {"materials": cr["materials"]}})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok"] is True and j["updated_at"] == before             # 回應形狀不變；updated_at 不動
        assert j["saved"] == {"materials": cr["materials"]}               # 前端用它當新基準
    assert _rows() == [], "沒有變動不可以記稽核"
    assert _updated_at() == before, "沒有變動不可以動 updated_at"
    assert backups == [], "沒有變動不可以備份"


def test_empty_segments_and_whole_package_identical_write_nothing(client, make_user):
    h = _login(client, *make_user(username="u8b", role="superadmin"))
    _seed()
    r = _patch(client, h, {"segments": {}, "base": {}, "defaults": {}})
    assert r.status_code == 200, r.text
    # 舊的整包格式：內容與資料庫一致（stages 由伺服器維護，送什麼都不採用）
    import db
    conn = db.get_db()
    try:
        cur = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])["caseRecord"]
    finally:
        conn.close()
    r = _patch(client, h, {"case_record": dict(cur)})
    assert r.status_code == 200, r.text
    assert _rows() == []


def test_real_change_is_one_row_with_changed_segments_and_fields_only_names(client, make_user):
    h = _login(client, *make_user(username="u8c", role="superadmin"))
    cr = _seed()
    r = _patch(client, h, {"segments": {"contract": {**cr["contract"], "terms": "機密條款 123", "signed": True},
                                        "materials": [{"id": 1, "name": "改過", "qty": 2}]},
                           "base": {"contract": cr["contract"], "materials": cr["materials"]}})
    assert r.status_code == 200, r.text
    rows = _rows()
    assert len(rows) == 1
    d = json.loads(rows[0]["detail"])
    assert d["segments"] == ["contract", "materials"]
    assert d["fields"] == {"contract": ["signed", "terms"]}               # 物件分段列欄位；列表分段只列分段
    assert "機密條款" not in rows[0]["detail"] and "改過" not in rows[0]["detail"], "只記名稱、不記值"
    assert rows[0]["case_no"] == NO and rows[0]["module"]                 # 既有的衍生欄位照舊


def test_each_real_save_is_its_own_row_not_merged(client, make_user):
    """裁示：稽核一事件一筆、時間完整——不做合併。"""
    h = _login(client, *make_user(username="u8d", role="superadmin"))
    cr = _seed()
    base = cr["materials"]
    for i in range(3):
        new = [{"id": 1, "name": f"v{i}", "qty": 1}]
        r = _patch(client, h, {"segments": {"materials": new}, "base": {"materials": base}})
        assert r.status_code == 200, r.text
        base = new
    rows = _rows()
    assert len(rows) == 3
    assert [json.loads(x["detail"])["segments"] for x in rows] == [["materials"]] * 3
    assert rows[0]["at"] <= rows[1]["at"] <= rows[2]["at"]


def test_change_then_identical_resave_adds_no_second_row(client, make_user):
    h = _login(client, *make_user(username="u8e", role="superadmin"))
    cr = _seed()
    new = [{"id": 1, "name": "改過", "qty": 1}]
    assert _patch(client, h, {"segments": {"materials": new}, "base": {"materials": cr["materials"]}}).status_code == 200
    assert _patch(client, h, {"segments": {"materials": new}, "base": {"materials": new}}).status_code == 200
    assert len(_rows()) == 1


# ── h11 審查補強（F1／型別嚴格） ──────────────────────────────────────────────

def test_semi_unlocked_closed_case_noop_save_creates_no_change_request(client, make_user):
    """已結案半解鎖：空存檔不可以排進審核（不建變更申請列、不寄信、不記 case.change_requested）；真改動照常排隊。"""
    import db
    from tests.test_case_semi_unlock import _make_closed_case
    h = _login(client, *make_user(username="u8f", role="superadmin"))
    _make_closed_case(quote_no=NO)
    assert client.post(f"/api/quotations/{NO}/case-unlock", headers=h).status_code == 200
    conn = db.get_db()
    try:
        cur = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])["caseRecord"]
        n0 = conn.execute("SELECT COUNT(*) FROM case_change_requests").fetchone()[0]
        a0 = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='case.change_requested'").fetchone()[0]
    finally:
        conn.close()
    for body in ({"case_record": {k: v for k, v in cur.items() if k != "stages"}},
                 {"segments": {"materials": cur["materials"]}, "base": {"materials": cur["materials"]}}):
        r = _patch(client, h, body)
        assert r.status_code == 200, r.text
        assert not r.json().get("pending"), r.json()
    conn = db.get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM case_change_requests").fetchone()[0] == n0
        assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='case.change_requested'").fetchone()[0] == a0
    finally:
        conn.close()
    # 真的改了 ⇒ 照常排審核
    r = _patch(client, h, {"case_record": {"materials": [{"name": "改過", "files": [], "invoiceFiles": []}]}})
    assert r.status_code == 200 and r.json()["pending"] is True


def test_bool_vs_number_change_is_not_mistaken_for_no_change(client, make_user):
    """Python 的 0==False、1==True：0→false 這種改動不可以被當成「沒變」而丟掉。"""
    h = _login(client, *make_user(username="u8g", role="superadmin"))
    cr = _seed()
    base = {"contract": cr["contract"]}
    r = _patch(client, h, {"segments": {"contract": {**cr["contract"], "signed": 0}}, "base": base})   # False → 0
    assert r.status_code == 200, r.text
    got = _cr_contract()
    assert got["signed"] == 0 and got["signed"] is not False
    assert len(_rows()) == 1


def _cr_contract():
    import db
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])["caseRecord"]["contract"]
    finally:
        conn.close()


def test_defaults_fill_is_listed_as_initial_not_as_a_user_change(client, make_user):
    """頁面替還沒有的分段補預設值（defaults）：稽核列 segments 不含它（不是使用者改動），另列 initial。"""
    h = _login(client, *make_user(username="u8h", role="superadmin"))
    cr = _seed()
    r = _patch(client, h, {"segments": {}, "base": {}, "defaults": {"roles": {"sales": "x"}, "notes": "預設"}})
    assert r.status_code == 200, r.text
    rows = _rows()
    assert len(rows) == 1
    d = json.loads(rows[0]["detail"])
    assert d["segments"] == [] and d["initial"] == ["notes", "roles"], d
    # 真改動＋補預設同時發生：segments 只列真改動
    r = _patch(client, h, {"segments": {"materials": [{"id": 1, "name": "改", "qty": 1}]}, "base": {"materials": cr["materials"]},
                           "defaults": {"warrantyNote": "預設"}})
    assert r.status_code == 200, r.text
    d = json.loads(_rows()[-1]["detail"])
    assert d["segments"] == ["materials"] and d["initial"] == ["warrantyNote"], d
