# -*- coding: utf-8 -*-
"""建構器第三輪 S3（2026-09-30）：欄位可見（fields[].access.visibleTo）與選單可見（menu.visibleTo），後端強制。
看不到的欄位：單據讀取、列表、建立／修改／送出的回應、即時計算、輸出，一律拿掉；他存檔時不會把看不到的欄位清空；
公式洩漏與必填受限欄位在發布時擋下；選單可見只影響誰看得到入口（不設＝不變，反向控制）。"""
import pytest

KEY = "b3acc"


def _login(client, make_user, name, role="user", modules=None):
    u, p = make_user(name, "Custom-Pass-123", role=role, modules=modules)[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return u, {"Authorization": "Bearer " + tok}


def _body(**over):
    b = {"name": "可見測試", "permission": "custom." + KEY, "numbering": {"prefix": "AC", "period": "none", "digits": 3},
         "fields": [{"key": "title", "label": "標題", "type": "text", "required": True, "dataClass": "T1"},
                    {"key": "cost", "label": "成本", "type": "number", "dataClass": "T1", "access": {"visibleTo": {"users": ["b3a_boss"]}}},
                    {"key": "memo", "label": "備註", "type": "text", "dataClass": "T1"}],
         "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿"}, {"key": "done", "label": "完成", "final": True}],
                      "transitions": [{"key": "submit", "label": "送出", "from": "draft", "to": "done"}]}}
    b.update(over)
    return b


def _publish(client, h, body, key=KEY):
    r = client.put("/api/definitions/custom_module/%s/draft" % key, headers=h, json={"body": body}).json()
    if r["problems"]:
        return r["problems"]
    assert client.post("/api/definitions/custom_module/%s/publish" % key, headers=h, json={}).status_code == 200
    return []


@pytest.fixture()
def world(client, make_user):
    boss, hb = _login(client, make_user, "b3a_boss", role="superadmin")
    staff, hs = _login(client, make_user, "b3a_staff", modules=["custom." + KEY])
    assert _publish(client, hb, _body()) == []
    r = client.post("/api/custom/%s/records" % KEY, headers=hb, json={"values": {"title": "T", "cost": 123, "memo": "m"}})
    assert r.status_code == 200 and r.json()["data"]["cost"] == 123
    return client, hb, hs, r.json()["record_no"]


def test_read_list_output_hide_restricted_values_for_others_but_not_for_the_listed_user(world):
    client, hb, hs, no = world
    assert client.get("/api/custom/%s/records/%s" % (KEY, no), headers=hb).json()["data"]["cost"] == 123
    rec = client.get("/api/custom/%s/records/%s" % (KEY, no), headers=hs).json()
    assert "cost" not in rec["data"] and "cost" not in rec["view"]["fields"] and "cost" not in rec["view"] and rec["hiddenFields"] == ["cost"]
    assert rec["data"]["memo"] == "m"
    rows = client.get("/api/custom/%s/records" % KEY, headers=hs).json()
    assert rows and all("cost" not in r["data"] for r in rows)
    assert client.get("/api/custom/%s/records" % KEY, headers=hb).json()[0]["data"]["cost"] == 123
    html_staff = client.get("/api/custom/%s/records/%s/output" % (KEY, no), headers=hs).text
    assert "123" not in html_staff.replace("AC-123", "")
    assert "123" in client.get("/api/custom/%s/records/%s/output" % (KEY, no), headers=hb).text


def test_restricted_user_cannot_write_or_clear_the_hidden_field(world):
    client, hb, hs, no = world
    # 建立：他送來的 cost 被丟掉
    r = client.post("/api/custom/%s/records" % KEY, headers=hs, json={"values": {"title": "S", "cost": 999}})
    assert r.status_code == 200 and "cost" not in r.json()["data"]
    assert "cost" not in client.get("/api/custom/%s/records/%s" % (KEY, r.json()["record_no"]), headers=hb).json()["data"]
    # 修改（草稿）：他存檔不會清掉、也不能改 cost
    upd = client.put("/api/custom/%s/records/%s" % (KEY, no), headers=hs, json={"values": {"title": "T2", "cost": 1}})
    # 草稿只有建立者或超管可改（U14）⇒ 403；這裡改用建立者本人
    assert upd.status_code == 403
    mine = client.post("/api/custom/%s/records" % KEY, headers=hb, json={"values": {"title": "B", "cost": 50}}).json()["record_no"]
    r2 = client.put("/api/custom/%s/records/%s" % (KEY, mine), headers=hb, json={"values": {"title": "B2", "cost": 60}})
    assert r2.json()["data"]["cost"] == 60


def test_creator_without_access_edits_own_draft_and_hidden_value_survives(client, make_user):
    boss, hb = _login(client, make_user, "b3a_boss", role="superadmin")
    staff, hs = _login(client, make_user, "b3a_staff2", modules=["custom." + KEY])
    assert _publish(client, hb, _body()) == []
    no = client.post("/api/custom/%s/records" % KEY, headers=hs, json={"values": {"title": "S"}}).json()["record_no"]
    # 超管補上成本（超管可改他人草稿）
    assert client.put("/api/custom/%s/records/%s" % (KEY, no), headers=hb, json={"values": {"title": "S", "cost": 77}}).status_code == 200
    # 建立者（看不到成本）再存 ⇒ 成本仍是 77
    r = client.put("/api/custom/%s/records/%s" % (KEY, no), headers=hs, json={"values": {"title": "S3", "cost": 1}})
    assert r.status_code == 200 and "cost" not in r.json()["data"]
    assert client.get("/api/custom/%s/records/%s" % (KEY, no), headers=hb).json()["data"]["cost"] == 77
    assert client.get("/api/custom/%s/records/%s" % (KEY, no), headers=hb).json()["data"]["title"] == "S3"


def test_publish_blocks_formula_leak_and_required_restricted_field(client, make_user):
    _u, hb = _login(client, make_user, "b3a_boss", role="superadmin")
    leak = _body()
    leak["fields"].append({"key": "dbl", "label": "兩倍", "type": "formula", "formula": "cost * 2", "dataClass": "T1"})
    probs = _publish(client, hb, leak)
    assert probs and any("洩漏" in p["message"] for p in probs)
    leak["fields"][-1]["access"] = {"visibleTo": {"users": ["b3a_boss"]}}                          # 公式欄同樣受限 ⇒ 過
    assert _publish(client, hb, leak) == []
    req = _body()
    req["fields"][1]["required"] = True
    probs = _publish(client, hb, req, key="b3acc2")
    assert probs and any("必填欄位不可以設成只有部分人" in p["message"] for p in probs)


def test_compute_preview_hides_restricted_formula_values(client, make_user):
    _u, hb = _login(client, make_user, "b3a_boss", role="superadmin")
    _s, hs = _login(client, make_user, "b3a_staff3", modules=["custom." + KEY])
    b = _body()
    b["fields"][1]["type"] = "number"
    b["fields"].append({"key": "dbl", "label": "兩倍", "type": "formula", "formula": "cost * 2", "dataClass": "T1", "access": {"visibleTo": {"users": ["b3a_boss"]}}})
    assert _publish(client, hb, b) == []
    boss = client.post("/api/custom/%s/compute" % KEY, headers=hb, json={"values": {"title": "x", "cost": 5}}).json()
    assert boss["computed"]["dbl"] == 10
    staff = client.post("/api/custom/%s/compute" % KEY, headers=hs, json={"values": {"title": "x", "cost": 5}}).json()
    assert "dbl" not in staff["computed"]


def test_menu_visible_to_filters_the_module_list_and_unset_changes_nothing(client, make_user):
    _u, hb = _login(client, make_user, "b3a_boss", role="superadmin")
    _s, hs = _login(client, make_user, "b3a_staff4", modules=["custom." + KEY])
    assert _publish(client, hb, _body()) == []
    assert KEY in [m["key"] for m in client.get("/api/custom-modules", headers=hs).json()]            # 沒設 ⇒ 有權限的人都看得到
    b = _body(menu={"group": "測試", "visibleTo": {"users": ["b3a_boss"]}})
    assert _publish(client, hb, b) == []
    assert KEY not in [m["key"] for m in client.get("/api/custom-modules", headers=hs).json()]
    assert KEY in [m["key"] for m in client.get("/api/custom-modules", headers=hb).json()]
