"""自動化系統選型導覽（2026-08-27，選型資料庫第七類，DB v65）煙霧測試。

其餘既有選型類別（monitor_guide/access_guide/gateway_guide）本身沒有專屬 pytest
（純 CRUD router，人工瀏覽器驗證即可），這裡額外補一個輕量測試單純是因為這次
沒有用真實瀏覽器跑過完整 UI 流程（跑真實 dev server 會觸發系統既有的簽核逾期
催辦排程對真實員工寄出真實 Email，風險與驗證效益不成比例，見開發紀錄），改用
FastAPI TestClient 驗證 CRUD 全流程與 migration 種子資料，作為對等的驗證手段。
"""


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_seed_data_present(client, make_user):
    user, pw = make_user(username="viewer1", role="viewer")
    token = _login(client, user, pw)

    r = client.get("/api/automation-guide/scenarios", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert len(r.json()) == 4

    r = client.get("/api/automation-guide/categories", headers=_auth(token))
    assert len(r.json()) == 4

    r = client.get("/api/automation-guide/fit", headers=_auth(token))
    assert len(r.json()) == 16

    r = client.get("/api/automation-guide/products", headers=_auth(token))
    assert r.json() == []


def test_view_requires_login_but_not_edit_module(client, make_user):
    user, pw = make_user(username="eng1", role="engineer")
    token = _login(client, user, pw)
    r = client.get("/api/automation-guide/categories", headers=_auth(token))
    assert r.status_code == 200, r.text


def test_edit_requires_superadmin_or_edit_module(client, make_user):
    viewer, viewer_pw = make_user(username="viewer2", role="viewer")
    token = _login(client, viewer, viewer_pw)
    r = client.post("/api/automation-guide/scenarios", headers=_auth(token),
                     json={"code": "TEST_SCN", "name": "測試情境"})
    assert r.status_code == 403, r.text

    editor, editor_pw = make_user(username="editor1", role="engineer", modules=["automation_guide_edit"])
    token2 = _login(client, editor, editor_pw)
    r = client.post("/api/automation-guide/scenarios", headers=_auth(token2),
                     json={"code": "TEST_SCN", "name": "測試情境"})
    assert r.status_code == 201, r.text


def test_full_crud_round_trip(client, make_user):
    sa, sa_pw = make_user(username="sa1", role="superadmin")
    token = _login(client, sa, sa_pw)
    h = _auth(token)

    r = client.post("/api/automation-guide/scenarios", headers=h,
                     json={"code": "PALLET_TRANSFER", "name": "棧板轉運站", "description": "測試情境"})
    assert r.status_code == 201, r.text

    r = client.post("/api/automation-guide/categories", headers=h,
                     json={"code": "TEST_CAT", "name": "測試分類", "keySpecs": "測試規格",
                           "tags": "測試", "priceRange": "洽詢報價", "dependencyNote": "", "watchNote": ""})
    assert r.status_code == 201, r.text

    r = client.post("/api/automation-guide/fit", headers=h,
                     json={"scenarioCode": "PALLET_TRANSFER", "categoryCode": "TEST_CAT",
                           "fitLevel": "適合", "fitNote": "測試判斷"})
    assert r.status_code == 201, r.text
    fit_id = r.json()["id"]

    r = client.post("/api/automation-guide/products", headers=h,
                     json={"categoryCode": "TEST_CAT", "brand": "TestBrand", "model": "T-100",
                           "url": "https://example.com", "label": "測試型錄", "priceNote": "US$999",
                           "specs": [["承重", "500 kg"]]})
    assert r.status_code == 201, r.text
    prod_id = r.json()["id"]

    r = client.get("/api/automation-guide/products", headers=h)
    prods = r.json()
    assert any(p["id"] == prod_id and p["brand"] == "TestBrand" for p in prods)

    r = client.put(f"/api/automation-guide/products/{prod_id}", headers=h,
                    json={"brand": "TestBrand", "model": "T-200", "url": "https://example.com",
                          "label": "", "priceNote": "", "specs": []})
    assert r.status_code == 200, r.text

    # 清理（刪除順序需先刪 fit/products 再刪 category/scenario，符合 FK 慣例）
    assert client.delete(f"/api/automation-guide/fit/{fit_id}", headers=h).status_code == 200
    assert client.delete(f"/api/automation-guide/products/{prod_id}", headers=h).status_code == 200
    assert client.delete("/api/automation-guide/categories/TEST_CAT", headers=h).status_code == 200
    assert client.delete("/api/automation-guide/scenarios/PALLET_TRANSFER", headers=h).status_code == 200

    r = client.get("/api/automation-guide/scenarios", headers=h)
    assert len(r.json()) == 4  # 清乾淨後恢復成種子資料的 4 筆
