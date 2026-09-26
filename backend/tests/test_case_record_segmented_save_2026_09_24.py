"""案件記錄分段存（CM1，2026-09-24）：PATCH /api/quotations/{no}/case-record 帶 segments/base。

過去整包取代 caseRecord ⇒ 後存者靜默蓋掉前一個人的改動。分段存只替換改到的分段；
那一段在資料庫的現值與呼叫端基準不同就整筆 409、不寫入。瀏覽器端對端見
test_e2e_case_concurrent_edit_2026_09_24.py。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

NO = "MQ-SEG-001"


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _seed(extra=None):
    import db
    cr = {"payment": {"items": [{"id": 1, "type": "訂金款", "pct": 30, "amount": 30000.0,
                                 "received": False, "note": ""}]},
          "materials": [{"id": 1, "name": "原料", "qty": 1}],
          "stages": [{"id": 9, "label": "伺服器階段"}]}
    cr.update(extra or {})
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


def _cr():
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()
    finally:
        conn.close()
    return json.loads(row["data_json"])["caseRecord"]


def _patch(client, h, body):
    return client.patch(f"/api/quotations/{NO}/case-record", json=body, headers=h)


def test_segment_saved_and_other_segments_untouched(client, make_user):
    h = _login(client, *make_user(username="seg1", role="admin"))
    cr = _seed()
    mats = [{"id": 1, "name": "改過", "qty": 1}]
    r = _patch(client, h, {"segments": {"materials": mats}, "base": {"materials": cr["materials"]}})
    assert r.status_code == 200, r.text
    got = _cr()
    assert got["materials"] == mats
    assert got["payment"] == cr["payment"]
    assert got["stages"] == cr["stages"]


def test_stale_base_is_409_and_nothing_written(client, make_user):
    h = _login(client, *make_user(username="seg2", role="admin"))
    cr = _seed()
    stale = [{"id": 1, "name": "我以為的原值", "qty": 1}]
    r = _patch(client, h, {"segments": {"materials": [{"id": 1, "name": "新", "qty": 2}],
                                        "contract": {"deliveryAddress": "X"}},
                           "base": {"materials": stale, "contract": None}})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["segments"] == ["materials"]
    got = _cr()
    assert got["materials"] == cr["materials"]
    assert "contract" not in got, "同一筆裡沒衝突的分段也不可以寫入（整筆拒絕）"


def test_integral_float_in_db_matches_int_from_browser(client, make_user):
    h = _login(client, *make_user(username="seg3", role="admin"))
    _seed()
    # 資料庫存 30000.0，瀏覽器 JSON 來回後是 30000
    base = {"items": [{"id": 1, "type": "訂金款", "pct": 30, "amount": 30000, "received": False, "note": ""}]}
    new = json.loads(json.dumps(base))
    new["items"][0]["note"] = "改"
    r = _patch(client, h, {"segments": {"payment": new}, "base": {"payment": base}})
    assert r.status_code == 200, r.text
    assert _cr()["payment"]["items"][0]["note"] == "改"


def test_stages_in_segments_ignored(client, make_user):
    h = _login(client, *make_user(username="seg4", role="admin"))
    cr = _seed()
    r = _patch(client, h, {"segments": {"stages": []}, "base": {"stages": []}})
    assert r.status_code == 200, r.text
    assert _cr()["stages"] == cr["stages"]


def test_defaults_written_only_when_absent_and_existing_value_adopted(client, make_user):
    h = _login(client, *make_user(username="seg5", role="admin"))
    _seed({"roles": {"sales": "先存的人"}})
    r = _patch(client, h, {"segments": {}, "base": {},
                           "defaults": {"roles": {"sales": ""}, "contract": {"deliveryAddress": ""}}})
    assert r.status_code == 200, r.text
    got = _cr()
    assert got["roles"] == {"sales": "先存的人"}, "預設值不可以蓋掉資料庫已有的分段"
    assert got["contract"] == {"deliveryAddress": ""}
    assert r.json()["adopted"] == {"roles": {"sales": "先存的人"}}


def test_legacy_whole_record_format_still_accepted(client, make_user):
    h = _login(client, *make_user(username="seg6", role="admin"))
    cr = _seed()
    new = dict(cr, materials=[{"id": 1, "name": "舊格式", "qty": 1}])
    r = _patch(client, h, {"case_record": new})
    assert r.status_code == 200, r.text
    assert _cr()["materials"][0]["name"] == "舊格式"


def test_non_admin_receipt_change_via_segment_still_blocked(client, make_user):
    h = _login(client, *make_user(username="seg7", role="sales"))
    cr = _seed()
    new = json.loads(json.dumps(cr["payment"]))
    new["items"][0]["received"] = True
    new["items"][0]["receivedAt"] = "2026-09-01"
    r = _patch(client, h, {"segments": {"payment": new}, "base": {"payment": cr["payment"]}})
    assert r.status_code == 403, r.text
    assert _cr()["payment"]["items"][0]["received"] is False
