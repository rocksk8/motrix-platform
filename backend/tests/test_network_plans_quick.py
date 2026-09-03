"""快速拓樸圖產生器（不建立規劃書）測試：routers/network_plans_quick.py 的
兩個無狀態端點（preview／pdf）＋ network_plan_export.py 的獨立拓樸圖 HTML 建構。
對應使用者原本的個案腳本 b1f_topology.py 使用情境——只想畫圖，不想填整份
規劃書；這裡刻意不寫入 network_plans 資料表，資料只在前端 localStorage。"""


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


_SAMPLE = {
    "devices": [
        {"name": "SW-Q1", "category": "交換器", "portsCopper": 8, "portsSfp": 2, "model": "AT-x230-18GT"},
    ],
    "switchPorts": [
        {"device": "SW-Q1", "portNo": "1", "endpoint": "客戶端A", "portProfile": "A系列"},
    ],
}


def test_preview_requires_login(client):
    r = client.post("/api/network-plans-quick/preview", json={"data": _SAMPLE})
    assert r.status_code == 401


def test_preview_returns_svg_and_warnings(client, make_user):
    username, password = make_user(role="viewer")  # 純預覽不需要 netplan_edit，任何登入者皆可
    token = _login(client, username, password)
    r = client.post("/api/network-plans-quick/preview", headers=_auth(token), json={"data": _SAMPLE})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "<svg" in body["svg"]
    assert body["warnings"] == []


def test_preview_empty_data_returns_null_svg_not_error(client, make_user):
    username, password = make_user(role="viewer")
    token = _login(client, username, password)
    r = client.post("/api/network-plans-quick/preview", headers=_auth(token), json={"data": {}})
    assert r.status_code == 200
    assert r.json()["svg"] is None
    assert r.json()["warnings"] == []


def test_preview_does_not_persist_anything(client, make_user):
    """核心設計保證：呼叫這個端點不應該在 network_plans 資料表留下任何紀錄。"""
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    before = client.get("/api/network-plans", headers=_auth(token)).json()
    client.post("/api/network-plans-quick/preview", headers=_auth(token), json={"data": _SAMPLE})
    client.post("/api/network-plans-quick/preview", headers=_auth(token), json={"data": _SAMPLE})
    after = client.get("/api/network-plans", headers=_auth(token)).json()
    assert len(after) == len(before)


def test_pdf_endpoint(client, make_user):
    username, password = make_user(role="viewer")
    token = _login(client, username, password)
    r = client.post("/api/network-plans-quick/pdf", headers=_auth(token),
                     json={"data": _SAMPLE, "title": "測試拓樸圖", "floorTag": "1F", "footer": ""})
    if r.status_code == 503:
        return  # 此環境沒有 Microsoft Edge，比照既有測試慣例略過實際產出驗證
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert len(r.content) > 0


def test_build_topology_only_html_contains_title_and_svg():
    import network_plan_export as npe
    html = npe.build_topology_only_html(_SAMPLE, title="測試拓樸圖", floor_tag="1F", footer="")
    assert "測試拓樸圖" in html
    assert "1F" in html
    assert "<svg" in html
    assert "SW-Q1" in html


def test_build_topology_only_html_no_switches_shows_placeholder_not_crash():
    import network_plan_export as npe
    html = npe.build_topology_only_html({}, title="空的", floor_tag="", footer="")
    assert "空的" in html
    assert "<svg" not in html
