"""網路拓樸圖產生（network_plan_topology.py）測試：純函式邏輯 + preview API
+ 確認已嵌入 PDF 匯出（見 network_plan_export.py::build_plan_html）+ 防呆行為
（單一設備資料錯誤不拖垮整張圖／埠數上限／重複設備名稱／連線對象打字誤植等）。"""
import network_plan_topology as topo


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


_SAMPLE = {
    "devices": [
        {"name": "B1F_1", "category": "交換器", "model": "AT-x230-28GT",
         "portsCopper": 24, "portsSfp": 4, "location": "B1F機櫃"},
        {"name": "B1F_2", "category": "交換器", "model": "AT-x230-28GT",
         "portsCopper": 24, "portsSfp": 4, "location": "B1F機櫃"},
        {"name": "AP-01", "category": "無線AP"},  # 非交換器，應被忽略
    ],
    "switchPorts": [
        {"device": "B1F_1", "portNo": "1", "endpoint": "B1F Uplink", "portProfile": "Uplink",
         "linkDevice": "ISP路由器（未列出）"},
        {"device": "B1F_1", "portNo": "2", "endpoint": "A01", "portProfile": "A系列"},
        {"device": "B1F_1", "portNo": "24", "endpoint": "幹線", "portProfile": "Trunk",
         "linkDevice": "B1F_2", "linkPort": "1"},
        {"device": "B1F_2", "portNo": "1", "endpoint": "幹線 Trunk"},
        {"device": "B1F_2", "portNo": "2", "endpoint": "C01", "portProfile": "C系列"},
        {"device": "B1F_2", "portNo": "3"},  # endpoint 空 → spare，不應出現在圖上文字
    ],
}


def test_no_switches_returns_none():
    r = topo.build_topology_svg({"devices": [], "switchPorts": []})
    assert r == {"html": None, "warnings": []}
    r2 = topo.build_topology_svg({"devices": [{"name": "AP-01", "category": "無線AP"}]})
    assert r2["html"] is None


def test_builds_svg_with_faceplates_and_cables():
    r = topo.build_topology_svg(_SAMPLE)
    html = r["html"]
    assert html and "<svg" in html
    assert r["warnings"] == []
    assert "B1F_1" in html and "B1F_2" in html
    assert "A01" in html and "C01" in html
    # 交換器對交換器的連線只畫一條（不因兩端各自宣告而重複）
    assert html.count("B1F_1 P24") == 1
    # 未列出的上行目標畫成外部方塊
    assert "ISP路由器" in html
    # 相同 portProfile 的圖例只出現一次
    assert html.count(">Trunk<") == 1
    # PoE 未勾選則不應出現徽章
    assert "⚡PoE" not in html


def test_dedupes_bidirectional_link_declaration():
    data = {
        "devices": [
            {"name": "SW-A", "category": "交換器", "portsCopper": 8, "portsSfp": 0},
            {"name": "SW-B", "category": "交換器", "portsCopper": 8, "portsSfp": 0},
        ],
        "switchPorts": [
            {"device": "SW-A", "portNo": "1", "endpoint": "up", "linkDevice": "SW-B", "linkPort": "1"},
            {"device": "SW-B", "portNo": "1", "endpoint": "up", "linkDevice": "SW-A", "linkPort": "1"},
        ],
    }
    html = topo.build_topology_svg(data)["html"]
    assert html.count("SW-A P1") == 1  # 雙邊互相宣告同一條線，不畫兩條


def test_poe_badge_shown_when_flagged():
    data = {"devices": [{"name": "SW-A", "category": "交換器", "portsCopper": 8, "portsSfp": 0, "poe": True}]}
    html = topo.build_topology_svg(data)["html"]
    assert "⚡PoE" in html


def test_bad_port_count_skips_only_that_switch_not_the_whole_diagram():
    """單一設備埠數欄位打錯（非數字），其餘交換器仍要正常畫出——防呆重點：
    不能因為一台壞掉就讓整張拓樸圖消失。"""
    data = {
        "devices": [
            {"name": "OK-SW", "category": "交換器", "portsCopper": 8, "portsSfp": 0},
            {"name": "BAD-SW", "category": "交換器", "portsCopper": "abc", "portsSfp": 0},
        ],
        "switchPorts": [
            {"device": "OK-SW", "portNo": "1", "endpoint": "客戶端A"},
        ],
    }
    r = topo.build_topology_svg(data)
    assert r["html"] is not None
    assert "OK-SW" in r["html"]
    assert "BAD-SW" not in r["html"]
    assert any("BAD-SW" in w and "格式" in w for w in r["warnings"])


def test_all_switches_bad_returns_none_with_warnings():
    data = {"devices": [{"name": "BAD-SW", "category": "交換器", "portsCopper": -5}]}
    r = topo.build_topology_svg(data)
    assert r["html"] is None
    assert r["warnings"]


def test_port_count_clamped_to_max_with_warning():
    data = {"devices": [{"name": "HUGE-SW", "category": "交換器", "portsCopper": 99999, "portsSfp": 999}]}
    r = topo.build_topology_svg(data)
    assert r["html"] is not None
    assert any("超過上限" in w for w in r["warnings"])


def test_port_number_beyond_switch_capacity_dropped_with_warning():
    data = {
        "devices": [{"name": "SW-A", "category": "交換器", "portsCopper": 8, "portsSfp": 0}],
        "switchPorts": [
            {"device": "SW-A", "portNo": "99", "endpoint": "應該被忽略"},
            {"device": "SW-A", "portNo": "1", "endpoint": "正常"},
        ],
    }
    r = topo.build_topology_svg(data)
    assert "應該被忽略" not in r["html"]
    assert "正常" in r["html"]
    assert any("SW-A P99" in w for w in r["warnings"])


def test_duplicate_device_name_warns_and_keeps_first():
    data = {
        "devices": [
            {"name": "DUP-SW", "category": "交換器", "portsCopper": 8, "portsSfp": 0, "location": "第一筆"},
            {"name": "DUP-SW", "category": "交換器", "portsCopper": 8, "portsSfp": 0, "location": "第二筆"},
        ],
    }
    r = topo.build_topology_svg(data)
    assert "第一筆" in r["html"]
    assert "第二筆" not in r["html"]
    assert any("重複" in w for w in r["warnings"])


def test_unmatched_device_in_switch_ports_warns():
    data = {
        "devices": [{"name": "SW-A", "category": "交換器", "portsCopper": 8, "portsSfp": 0}],
        "switchPorts": [{"device": "SW-A-打錯", "portNo": "1", "endpoint": "x"}],
    }
    r = topo.build_topology_svg(data)
    assert any("SW-A-打錯" in w for w in r["warnings"])


def test_case_mismatch_link_device_warns_as_possible_typo():
    data = {
        "devices": [
            {"name": "SW-A", "category": "交換器", "portsCopper": 8, "portsSfp": 0},
            {"name": "sw-b", "category": "交換器", "portsCopper": 8, "portsSfp": 0},
        ],
        "switchPorts": [
            {"device": "SW-A", "portNo": "1", "endpoint": "up", "linkDevice": "SW-B", "linkPort": "1"},
        ],
    }
    r = topo.build_topology_svg(data)
    assert any("僅大小寫" in w for w in r["warnings"])
    assert "SW-B" in r["html"]  # 仍照原樣畫成外部方塊，不強行猜測配對


def test_long_labels_are_truncated_not_left_to_overflow():
    long_name = "非常非常非常長的目的地設備名稱超過原本設計預期"
    data = {
        "devices": [{"name": "SW-A", "category": "交換器", "portsCopper": 8, "portsSfp": 0}],
        "switchPorts": [{"device": "SW-A", "portNo": "1", "endpoint": long_name}],
    }
    html = topo.build_topology_svg(data)["html"]
    assert "…" in html  # 顯示文字已截斷加省略號
    assert f"<title>{long_name}</title>" in html  # 完整文字仍保留在 tooltip 裡，供 hover 查看
    assert html.count(long_name) == 1  # 完整長字串只出現在 <title> 一次，可見的 <text> 內容沒有塞完整長字串


def test_topology_preview_endpoint(client, make_user):
    eng_user, eng_pw = make_user(username="topo_eng", role="engineer", modules=["netplan_edit"])
    token = _login(client, eng_user, eng_pw)

    created = client.post("/api/network-plans", headers=_auth(token), json={"siteName": "拓樸測試案場"})
    assert created.status_code == 201, created.text
    plan_no = created.json()["planNo"]
    plan_id = next(p["id"] for p in client.get("/api/network-plans", headers=_auth(token)).json()
                   if p["planNo"] == plan_no)

    # 未落地存檔，直接送草稿資料即可預覽
    r = client.post(f"/api/network-plans/{plan_id}/topology-preview", headers=_auth(token),
                     json={"data": _SAMPLE})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "<svg" in body["svg"]
    assert body["warnings"] == []

    # 空資料回 200 但 svg 為 null，不當成錯誤
    empty = client.post(f"/api/network-plans/{plan_id}/topology-preview", headers=_auth(token),
                         json={"data": {}})
    assert empty.status_code == 200
    assert empty.json()["svg"] is None
    assert empty.json()["warnings"] == []

    # 埠數格式錯誤仍回 200（不是伺服器錯誤），並帶警告
    bad = client.post(f"/api/network-plans/{plan_id}/topology-preview", headers=_auth(token),
                       json={"data": {"devices": [{"name": "X", "category": "交換器", "portsCopper": "abc"}]}})
    assert bad.status_code == 200
    assert bad.json()["svg"] is None
    assert bad.json()["warnings"]

    missing = client.post("/api/network-plans/999999/topology-preview", headers=_auth(token),
                           json={"data": {}})
    assert missing.status_code == 404


def test_pdf_export_embeds_topology_when_switches_present(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    created = client.post("/api/network-plans", headers=_auth(token), json={"siteName": "拓樸PDF測試"})
    plan_no = created.json()["planNo"]
    plan_id = next(p["id"] for p in client.get("/api/network-plans", headers=_auth(token)).json()
                   if p["planNo"] == plan_no)
    client.put(f"/api/network-plans/{plan_id}", headers=_auth(token), json={"data": _SAMPLE})

    import network_plan_export as npe
    plan = client.get(f"/api/network-plans/{plan_id}", headers=_auth(token)).json()
    html = npe.build_plan_html(plan)
    assert "網路拓樸圖" in html
    assert "<svg" in html
