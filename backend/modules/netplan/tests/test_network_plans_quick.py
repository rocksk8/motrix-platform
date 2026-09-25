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
    import modules.netplan.export as npe
    html = npe.build_topology_only_html(_SAMPLE, title="測試拓樸圖", floor_tag="1F", footer="")
    assert "測試拓樸圖" in html
    assert "1F" in html
    assert "<svg" in html


def test_build_topology_only_html_uses_dynamic_single_page_not_a4():
    """2026-09-06 使用者要求「格式跟分頁方式要完全一樣」，改回比照原始個案
    腳本 b1f_topology.py：不用固定 A4（取代 2026-09-04 當時的 A4 直版版本），
    改用頁尾 script 於 load+字型 ready 後量測實際內容尺寸，動態產生剛好等於
    內容大小的 @page（永遠一頁、無頁碼）。"""
    import modules.netplan.export as npe
    html = npe.build_topology_only_html(_SAMPLE, title="測試", floor_tag="", footer="")
    assert "size:A4" not in html
    assert "fitPageToContent" in html
    assert "documentElement.scrollHeight" in html


def test_build_topology_only_html_model_tag_reflects_uniform_ports():
    """單一型號＋所有交換器銅埠/SFP埠數一致時，型號徽章比照原腳本樣式帶上
    埠數字樣；資料裡本來就只有一台 SW-Q1（8 銅埠＋2 SFP），視為一致。"""
    import modules.netplan.export as npe
    html = npe.build_topology_only_html(_SAMPLE, title="測試", floor_tag="", footer="")
    assert "AT-x230-18GT" in html
    assert "8×GbE" in html and "2×SFP" in html


def test_build_topology_only_html_includes_text_port_table():
    """使用者要求：圖旁要有文字敘述，不能只有圖——文字版埠位對照表要包含每個
    交換器的埠號、連接對象等欄位標題，以及範例資料裡的實際內容。"""
    import modules.netplan.export as npe
    html = npe.build_topology_only_html(_SAMPLE, title="測試", floor_tag="", footer="")
    assert "埠位對照表" in html or "SW-Q1" in html
    assert "連接對象／端點" in html
    assert "客戶端A" in html
    assert "Spare" in html  # 未使用的埠也要列出（比照原始腳本）


def test_build_topology_text_summary_html_lists_all_ports_including_spares():
    import modules.netplan.topology as topo
    data = {
        "devices": [{"name": "SW-A", "category": "交換器", "portsCopper": 4, "portsSfp": 1}],
        "switchPorts": [{"device": "SW-A", "portNo": "1", "endpoint": "客戶端X", "portProfile": "A"}],
    }
    html = topo.build_topology_text_summary_html(data)
    assert "客戶端X" in html
    assert html.count("Spare") == 4  # port 2,3,4 空 + SFP1 空 = 4 個 Spare
    assert "<table>" in html


def test_build_topology_text_summary_html_empty_when_no_switches():
    import modules.netplan.topology as topo
    assert topo.build_topology_text_summary_html({}) == ""


def test_build_topology_only_html_no_switches_shows_placeholder_not_crash():
    import modules.netplan.export as npe
    html = npe.build_topology_only_html({}, title="空的", floor_tag="", footer="")
    assert "空的" in html
    assert "<svg" not in html
