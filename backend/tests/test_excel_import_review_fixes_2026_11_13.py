# -*- coding: utf-8 -*-
"""Excel 匯入審查修正（hichan-4 對 c03d12f6a 的審查 M1～M7、L1～L5；PM 裁示 2026-11-13）。純 API 題，不開瀏覽器。

M1 統編相同但名稱不同 ⇒ 「需確認」，預設不寫、勾選（row.confirm=true）才寫
M2 預覽回每列舊→新差異與 planHash；寫入帶 planHash，預覽後資料有變 ⇒ 409；沒帶 ⇒ 400
M3 只有 dryRun 明確是 false 才寫入，其他一律只是預覽
M4 備註＝追加（換行＋〔Excel 匯入 日期〕＋新內容），內容已在裡面就不重複加
M5 廠牌格自己是「廠牌 / 型號」⇒ 先拆開再合併（不會變三段）
M7 舊的整包 PUT：沒帶的伺服器端欄位（拜訪／別名／啟用、料號成本單位等）沿用，不是清掉；整包送回的行為不變
L  聯絡人上限與鍵白名單、損毀 data_json 只跳過該列、料號不分大小寫、數字上限、稽核／通知失敗不影響回應
"""
import json

import pytest

_MAKE_USER_DEFAULT_ROLE = "superadmin"


@pytest.fixture()
def api(client, make_user):
    u, p = make_user(username="imp_rev_admin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    h = {"Authorization": "Bearer " + r.json()["token"]}

    class A:
        def get(self, url):
            return client.get(url, headers=h)

        def post(self, url, body):
            return client.post(url, json=body, headers=h)

        def put(self, url, body):
            return client.put(url, json=body, headers=h)

        def patch(self, url, body):
            return client.patch(url, json=body, headers=h)

    a = A()
    a.client = client
    return a


def _cust(api, name, tax="", phone="", **data):
    r = api.post("/api/customers", {"name": name, "tax_id": tax, "phone": phone, "data": data})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _all(api):
    return api.get("/api/customers").json()


def _row(n, name, tax="", phone="", **data):
    return {"row": n, "name": name, "taxId": tax, "phone": phone, "data": data}


def _preview(api, rows, url="/api/customers/import-rows"):
    r = api.post(url, {"rows": rows, "dryRun": True})
    assert r.status_code == 200, r.text
    return r.json()


def _commit(api, rows, plan_hash, url="/api/customers/import-rows"):
    return api.post(url, {"rows": rows, "dryRun": False, "planHash": plan_hash})


# ── M1 ───────────────────────────────────────────────────────────────

def test_m1_same_tax_different_name_needs_confirmation_and_is_not_written_by_default(api):
    _cust(api, "甲公司", "12345678", phone="02-1")
    rows = [_row(2, "乙公司", "12345678", phone="02-9", email="x@example.com")]
    p = _preview(api, rows)
    assert p["updated"] == 0 and len(p["confirms"]) == 1
    c = p["confirms"][0]
    assert c["oldName"] == "甲公司" and c["name"] == "乙公司" and c["applied"] is False
    assert _commit(api, rows, p["planHash"]).status_code == 200
    cu = [x for x in _all(api) if x.get("taxId") == "12345678"][0]
    assert cu["name"] == "甲公司" and cu["phone"] == "02-1" and not cu.get("email"), "名稱不同的統編命中不可預設寫入"


def test_m1_ticked_confirm_row_is_written_but_keeps_system_name(api):
    _cust(api, "甲公司", "12345678", phone="02-1")
    rows = [dict(_row(2, "乙公司", "12345678", phone="02-9"), confirm=True)]
    p = _preview(api, rows)                       # 預覽時就帶了勾選：計入更新
    assert p["updated"] == 1 and p["confirms"][0]["applied"] is True
    r = _commit(api, rows, p["planHash"])
    assert r.status_code == 200 and r.json()["updated"] == 1
    cu = [x for x in _all(api) if x.get("taxId") == "12345678"][0]
    assert cu["name"] == "甲公司" and cu["phone"] == "02-9"


def test_m1_name_differences_that_are_only_formatting_still_match(api):
    _cust(api, "台灣大哥大股份有限公司", "11111111")
    p = _preview(api, [_row(2, "臺灣大哥大 公司", "11111111", phone="02-2")])
    assert p["updated"] == 1 and p["confirms"] == []


# ── M2 ───────────────────────────────────────────────────────────────

def test_m2_preview_lists_old_to_new_per_row(api):
    _cust(api, "既有科技", "22222222", phone="02-1", industry="資訊")
    p = _preview(api, [_row(2, "既有科技", "22222222", phone="02-2", industry="製造")])
    fields = {f["field"]: f for f in p["changes"][0]["fields"]}
    assert fields["phone"]["old"] == "02-1" and fields["phone"]["new"] == "02-2"
    assert fields["industry"]["old"] == "資訊" and fields["industry"]["new"] == "製造"


def test_m2_commit_without_plan_hash_is_rejected(api):
    rows = [_row(2, "新公司", "33333333")]
    r = api.post("/api/customers/import-rows", {"rows": rows, "dryRun": False})
    assert r.status_code == 400
    assert not [x for x in _all(api) if x.get("taxId") == "33333333"]


def test_m2_commit_after_data_changed_since_preview_returns_409(api):
    cid = _cust(api, "既有科技", "44444444", phone="02-1")
    rows = [_row(2, "既有科技", "44444444", phone="02-2")]
    p = _preview(api, rows)
    cur = api.get("/api/customers/%d" % cid).json()
    assert api.put("/api/customers/%d" % cid, {"name": "既有科技", "tax_id": "44444444", "phone": "02-7", "data": {"visits": cur.get("visits", [])}}).status_code == 200
    r = _commit(api, rows, p["planHash"])
    assert r.status_code == 409, r.text
    assert [x for x in _all(api) if x.get("taxId") == "44444444"][0]["phone"] == "02-7", "409 時不可寫入"


def test_m2_commit_with_stale_new_customer_appearing_returns_409(api):
    rows = [_row(2, "全新公司", "55555555")]
    p = _preview(api, rows)
    _cust(api, "有人先建了", "55555555")
    assert _commit(api, rows, p["planHash"]).status_code == 409


# ── M3 ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("flag", ["__missing__", True, "false", 0, "0", None, 1])
def test_m3_only_boolean_false_writes(api, flag):
    rows = [_row(2, "預覽用公司", "66666666")]
    body = {"rows": rows}
    if flag != "__missing__":
        body["dryRun"] = flag
    body["planHash"] = "x"
    r = api.post("/api/customers/import-rows", body)
    assert r.status_code == 200 and r.json()["created"] == 1
    assert not [x for x in _all(api) if x.get("taxId") == "66666666"], "dryRun=%r 不應寫入" % (flag,)
    r2 = api.post("/api/parts/import-rows", {"rows": [{"row": 2, "partNo": "NET-901", "name": "交換器"}], **({} if flag == "__missing__" else {"dryRun": flag})})
    assert r2.status_code == 200
    assert not [p for p in api.get("/api/parts").json()["items"] if p["part_no"] == "NET-901"]


# ── M4 ───────────────────────────────────────────────────────────────

def test_m4_notes_are_appended_not_overwritten_and_not_duplicated(api):
    _cust(api, "備註公司", "77777777", notes="原備註")
    rows = [_row(2, "備註公司", "77777777", notes="新備註")]
    p = _preview(api, rows)
    assert _commit(api, rows, p["planHash"]).status_code == 200
    n = [x for x in _all(api) if x.get("taxId") == "77777777"][0]["notes"]
    assert n.startswith("原備註\n〔Excel 匯入 ") and n.endswith("〕新備註"), n
    p2 = _preview(api, rows)                       # 同樣內容再匯一次：不再追加
    assert _commit(api, rows, p2["planHash"]).status_code == 200
    assert [x for x in _all(api) if x.get("taxId") == "77777777"][0]["notes"] == n


def test_m4_notes_blank_existing_gets_plain_text(api):
    _cust(api, "空備註公司", "88888888")
    rows = [_row(2, "空備註公司", "88888888", notes="第一則")]
    assert _commit(api, rows, _preview(api, rows)["planHash"]).status_code == 200
    assert [x for x in _all(api) if x.get("taxId") == "88888888"][0]["notes"] == "第一則"


# ── M5 ───────────────────────────────────────────────────────────────

def _part_rows(api):
    return {p["part_no"]: p for p in api.get("/api/parts").json()["items"]}


def test_m5_legacy_combined_brand_cell_is_split_before_merging(api):
    r = api.post("/api/parts", {"partNo": "NET-001", "name": "交換器", "brand": "Cisco / OLD-MODEL", "unit": "台", "cost": 100, "listPrice": 200, "category": "網通設備"})
    assert r.status_code == 201, r.text
    url = "/api/parts/import-rows"
    rows = [{"row": 2, "partNo": "NET-001", "brand": "Cisco / C9200"}]               # 舊格式：廠牌格含型號，型號欄空白
    p = _preview(api, rows, url)
    assert _commit(api, rows, p["planHash"], url).status_code == 200
    assert _part_rows(api)["NET-001"]["brand"] == "Cisco / C9200", "不可變成 Cisco / C9200 / OLD-MODEL"
    rows2 = [{"row": 2, "name": "新品", "brand": "Dahua / DH-1", "category": "網通設備"}]
    p2 = _preview(api, rows2, url)
    assert _commit(api, rows2, p2["planHash"], url).status_code == 200
    created = [x for x in _part_rows(api).values() if x["name"] == "新品"][0]
    assert created["brand"] == "Dahua / DH-1"
    rows3 = [{"row": 2, "partNo": "NET-001", "brand": "Cisco / C9200", "model": "C9300"}]       # 明確的型號欄優先
    assert _commit(api, rows3, _preview(api, rows3, url)["planHash"], url).status_code == 200
    assert _part_rows(api)["NET-001"]["brand"] == "Cisco / C9300"


# ── M7 ───────────────────────────────────────────────────────────────

def test_m7_put_customer_without_server_owned_keys_keeps_them(api):
    cid = _cust(api, "保留公司", "99999999", alias="舊別名", active=False)
    assert api.patch("/api/customers/%d/visits" % cid, {"visits": [{"id": 1, "date": "2026-10-01", "note": "拜訪"}]}).status_code == 200
    cur = api.get("/api/customers/%d" % cid).json()
    assert cur["visits"], "前置：拜訪紀錄存在"
    # 只送部分欄位（舊的逐列匯入的樣子）
    assert api.put("/api/customers/%d" % cid, {"name": "保留公司", "tax_id": "99999999", "phone": "02-5", "data": {"industry": "資訊"}}).status_code == 200
    after = api.get("/api/customers/%d" % cid).json()
    assert after["alias"] == "舊別名" and after["active"] is False and after["industry"] == "資訊" and after["phone"] == "02-5"
    assert after["visits"] == cur["visits"], "只送部分欄位的 PUT 洗掉了拜訪紀錄"


def test_m7_put_customer_full_body_from_edit_form_behaves_as_before(api):
    cid = _cust(api, "表單公司", "10101010", alias="舊別名", active=True, visits=[{"id": 1, "note": "a"}])
    cur = api.get("/api/customers/%d" % cid).json()
    data = {k: v for k, v in cur.items() if k not in ("id", "name", "taxId", "phone", "code", "createdAt", "updatedAt")}
    data["alias"] = "新別名"
    data["visits"] = []                            # 表單明確把拜訪清空 ⇒ 要照做
    data["active"] = False
    assert api.put("/api/customers/%d" % cid, {"name": "表單公司", "tax_id": "10101010", "phone": "", "data": data}).status_code == 200
    after = api.get("/api/customers/%d" % cid).json()
    assert after["alias"] == "新別名" and after["visits"] == [] and after["active"] is False


def test_m7_put_part_partial_body_keeps_other_fields_but_full_body_replaces(api):
    r = api.post("/api/parts", {"partNo": "CAM-007", "name": "攝影機", "brand": "Hik / DS", "unit": "支", "cost": 1200, "listPrice": 2500,
                                "category": "監控設備", "note": "原備註", "safetyStock": 5, "leadTimeDays": 7})
    assert r.status_code == 201, r.text
    pid = r.json()["id"] if "id" in r.json() else [p for p in api.get("/api/parts").json()["items"] if p["part_no"] == "CAM-007"][0]["id"]
    assert api.put("/api/parts/%d" % pid, {"name": "攝影機B"}).status_code == 200            # 只改品名
    p = _part_rows(api)["CAM-007"]
    assert (p["name"], p["brand"], p["unit"], p["cost"], p["list_price"], p["category"], p["note"]) == ("攝影機B", "Hik / DS", "支", 1200, 2500, "監控設備", "原備註")
    assert api.put("/api/parts/%d" % pid, {"partNo": "CAM-007", "name": "攝影機C", "brand": "", "unit": "台", "cost": 0, "listPrice": 0,
                                           "category": "", "note": ""}).status_code == 200      # 整包送：照送的值
    p = _part_rows(api)["CAM-007"]
    assert (p["brand"], p["unit"], p["cost"], p["list_price"], p["note"]) == ("", "台", 0, 0, "")


# ── L ────────────────────────────────────────────────────────────────

def test_l1_contacts_are_capped_and_unknown_keys_dropped(api):
    contacts = [{"id": i, "name": "人%d" % i, "phone": "1", "evil": {"x": [1] * 10}, "title": "T"} for i in range(80)]
    rows = [_row(2, "多聯絡人", "12121212", contacts=contacts)]
    assert _commit(api, rows, _preview(api, rows)["planHash"]).status_code == 200
    c = [x for x in _all(api) if x.get("taxId") == "12121212"][0]
    assert len(c["contacts"]) == 50
    assert all(set(ct) <= {"id", "name", "title", "phone", "email"} for ct in c["contacts"])


def test_l2_corrupt_data_json_skips_only_that_row(api):
    import db
    cid = _cust(api, "壞資料公司", "13131313")
    gid = _cust(api, "好公司", "14141414", phone="02-1")
    conn = db.get_db()
    try:
        conn.execute("UPDATE customers SET data_json='{not json' WHERE id=?", (cid,))
        conn.commit()
    finally:
        conn.close()
    rows = [_row(2, "壞資料公司", "13131313", phone="02-9"), _row(3, "好公司", "14141414", phone="02-2")]
    p = _preview(api, rows)
    assert p["failed"] == 1 and p["updated"] == 1 and "損毀" in p["errors"][0]
    assert _commit(api, rows, p["planHash"]).status_code == 200
    assert api.get("/api/customers/%d" % gid).json()["phone"] == "02-2"      # 列表端點本身讀不了損毀列（既有行為），所以用單筆讀


def test_l3_part_no_matches_case_and_width_insensitively(api):
    assert api.post("/api/parts", {"partNo": "NET-002", "name": "交換器", "unit": "台", "cost": 100, "category": "網通設備"}).status_code == 201
    url = "/api/parts/import-rows"
    rows = [{"row": 2, "partNo": "ｎｅｔ－002", "cost": "150"}, {"row": 3, "partNo": "net-002", "cost": "160"}]
    p = _preview(api, rows, url)
    assert p["updated"] == 1 and p["created"] == 0 and p["failed"] == 1, "第二列是同檔重複料號"
    assert _commit(api, rows[:1], _preview(api, rows[:1], url)["planHash"], url).status_code == 200
    assert _part_rows(api)["NET-002"]["cost"] == 150 and len(_part_rows(api)) == 1


def test_l4_numbers_above_cap_are_rejected(api):
    url = "/api/parts/import-rows"
    p = _preview(api, [{"row": 2, "partNo": "NET-003", "name": "x", "cost": "1e300"}, {"row": 3, "partNo": "NET-004", "name": "y", "cost": "999999999"}], url)
    assert p["failed"] == 1 and p["created"] == 1


def test_l5_audit_or_notify_failure_after_commit_does_not_turn_response_into_error(api, monkeypatch):
    import routers.customers as rc
    monkeypatch.setattr(rc, "_audit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("audit down")))
    rows = [_row(2, "稽核壞掉公司", "15151515")]
    r = _commit(api, rows, _preview(api, rows)["planHash"])
    assert r.status_code == 200 and r.json()["created"] == 1
    assert [x for x in _all(api) if x.get("taxId") == "15151515"], "資料已寫入"


# ── M6（效能；PM：1500 列超過 10 秒就要修）：批次取號、批次稽核 ─────────────────

def test_m6_batch_codes_are_unique_and_continue_after_existing_ones_and_audit_rows_are_written(api):
    import db
    _cust(api, "先有的一家", "20202020")
    before = {c["code"] for c in _all(api)}
    rows = [_row(i + 2, "批次公司%d" % i, "%08d" % (30000000 + i)) for i in range(40)]
    p = _preview(api, rows)
    assert _commit(api, rows, p["planHash"]).status_code == 200
    codes = [c["code"] for c in _all(api) if c["name"].startswith("批次公司")]
    assert len(codes) == 40 and len(set(codes)) == 40 and not (set(codes) & before)
    seqs = sorted(int(c.rsplit("-", 1)[1]) for c in codes)
    assert seqs == list(range(seqs[0], seqs[0] + 40)), "代號要連號"
    conn = db.get_db()
    try:
        n = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='customer.create' AND detail LIKE '%excel_import%'").fetchone()[0]
        s = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='customer.import'").fetchone()[0]
    finally:
        conn.close()
    assert n == 40 and s == 1, "逐客戶稽核 40 筆＋批次總數 1 筆"
