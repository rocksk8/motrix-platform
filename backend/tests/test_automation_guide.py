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
    # 2026-09-13（模組權限稽核第二輪）：讀取端點現在要求「自動化系統選型導覽」
    # 檢視模組（或編輯模組）。權限目錄裡本來就有這個可勾選項，先前後端沒有讀，
    # 等於勾掉也照樣看得到——這次補上，所以測試帳號要帶模組。
    user, pw = make_user(username="viewer1", role="viewer", modules=["automation_guide"])
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


def test_view_requires_view_module_but_not_edit_module(client, make_user):
    """檢視只需要**檢視**模組，不需要編輯模組——這是這支測試原本要守的重點。

    2026-09-13 改動：原本的規格是「檢視只要登入就好」，後端完全不讀
    `automation_guide` 這個檢視模組（雖然權限目錄一直提供它、側欄也一直用它決定
    要不要顯示選單）。使用者裁示「逐一補後端檢查」後，檢視需要檢視模組或編輯模組。
    """
    user, pw = make_user(username="eng1", role="engineer", modules=["automation_guide"])
    token = _login(client, user, pw)
    r = client.get("/api/automation-guide/categories", headers=_auth(token))
    assert r.status_code == 200, r.text

    # 沒有任何導覽模組的帳號讀不到（先前這行會是 200）
    nobody, nobody_pw = make_user(username="eng1_nomod", role="engineer", modules=["case_manage"])
    token2 = _login(client, nobody, nobody_pw)
    assert client.get("/api/automation-guide/categories",
                      headers=_auth(token2)).status_code == 403

    # 只有編輯模組的帳號仍讀得到——否則會變成「改得動卻讀不到」
    editor, editor_pw = make_user(username="eng1_editonly", role="engineer",
                                  modules=["automation_guide_edit"])
    token3 = _login(client, editor, editor_pw)
    assert client.get("/api/automation-guide/categories",
                      headers=_auth(token3)).status_code == 200


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
