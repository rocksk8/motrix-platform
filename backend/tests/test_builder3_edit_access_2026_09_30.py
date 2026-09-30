# -*- coding: utf-8 -*-
"""建構器第三輪 S3 補完（2026-09-30）：
① 欄位「改得到」（access.editableTo）：看得到但改不到的欄位，送來的值與既有值不同 ⇒ 403（列出欄位）；沒動＝照常（表單整份回送不會誤傷）
   改得到蘊含看得到；看不到的欄位仍是丟掉他的值、不洩漏存在
② 模組選單可見（menu.visibleTo）不只藏選單：直接打單據端點也 404（不洩漏模組存在）；簽核人走自己的讀單路徑不受影響"""
import pytest

from helpers import custom_builder_support as S

KEY = "b3edit"


def _login(client, make_user, name, role="user", modules=None):
    u, p = make_user(name, "Custom-Pass-123", role=role, modules=modules)[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _body(**over):
    b = {"name": "改權測試", "permission": "custom." + KEY, "numbering": {"prefix": "ED", "period": "none", "digits": 3},
         "fields": [{"key": "title", "label": "標題", "type": "text", "required": True, "dataClass": "T1"},
                    {"key": "approved_amt", "label": "核定金額", "type": "number", "dataClass": "T1",
                     "access": {"editableTo": {"users": ["b3e_fin"]}}},
                    {"key": "secret", "label": "內部備註", "type": "text", "dataClass": "T1",
                     "access": {"visibleTo": {"users": ["b3e_fin"]}, "editableTo": {"users": ["b3e_fin"]}}}],
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


def test_can_edit_and_can_see_rules_editable_implies_visible():
    f = {"key": "x", "access": {"visibleTo": {"users": ["a"]}, "editableTo": {"users": ["b"]}}}
    boss = {"role": "superadmin", "username": "z"}
    assert S.can_see_field(f, {"role": "user", "username": "a"}) and not S.can_edit_field(f, {"role": "user", "username": "a"})
    assert S.can_see_field(f, {"role": "user", "username": "b"}) and S.can_edit_field(f, {"role": "user", "username": "b"})   # 改得到蘊含看得到
    assert not S.can_see_field(f, {"role": "user", "username": "c"}) and not S.can_edit_field(f, {"role": "user", "username": "c"})
    assert S.can_see_field(f, boss) and S.can_edit_field(f, boss)
    g = {"key": "y", "access": {"editableTo": {"roles": ["admin"]}}}                                # 只設改：看得到的人（所有人）不一定改得到
    assert S.can_see_field(g, {"role": "user", "username": "a"}) and not S.can_edit_field(g, {"role": "user", "username": "a"})
    assert S.can_edit_field({"key": "z"}, {"role": "user", "username": "a"})                        # 沒設 ⇒ 不變


def test_guard_writes_unchanged_passes_changed_is_listed_hidden_is_dropped():
    body = _body()
    user = {"role": "user", "username": "staff"}
    vals, bad = S.guard_writes(body, {"title": "T", "approved_amt": 100, "secret": "x"}, {"approved_amt": 100, "secret": "old"}, user)
    assert bad == [] and vals == {"title": "T", "approved_amt": 100, "secret": "old"}                # 沒動＝過；看不到的沿用既有
    _v, bad = S.guard_writes(body, {"title": "T", "approved_amt": 999}, {"approved_amt": 100}, user)
    assert [b["key"] for b in bad] == ["approved_amt"]
    _v, bad = S.guard_writes(body, {"title": "T", "approved_amt": 5}, None, user)                    # 新單填了不能改的欄位
    assert [b["key"] for b in bad] == ["approved_amt"]
    _v, bad = S.guard_writes(body, {"title": "T", "approved_amt": ""}, None, user)                   # 空對空＝沒動
    assert bad == []
    _v, bad = S.guard_writes(body, {"title": "T", "approved_amt": 5}, None, {"role": "user", "username": "b3e_fin"})
    assert bad == []


def test_api_returns_403_for_a_changed_uneditable_field_and_allows_the_finance_user(client, make_user):
    hb = _login(client, make_user, "b3e_boss", role="superadmin")
    hs = _login(client, make_user, "b3e_staff", modules=["custom." + KEY])
    hf = _login(client, make_user, "b3e_fin", modules=["custom." + KEY])
    assert _publish(client, hb, _body()) == []
    r = client.post("/api/custom/%s/records" % KEY, headers=hs, json={"values": {"title": "T", "approved_amt": 500}})
    assert r.status_code == 403 and "核定金額" in r.text                                              # 不是靜默丟掉
    no = client.post("/api/custom/%s/records" % KEY, headers=hs, json={"values": {"title": "T"}}).json()["record_no"]
    # 財務（改得到，且看得到）補上核定金額——他不是建立者、草稿只有建立者或超管能改（U14）⇒ 由超管代改
    assert client.put("/api/custom/%s/records/%s" % (KEY, no), headers=hb, json={"values": {"title": "T", "approved_amt": 500, "secret": "s"}}).status_code == 200
    # 建立者整份回送（含看得到但沒動的核定金額）＝沒動 ⇒ 過；看不到的內部備註不出現在回應
    got = client.get("/api/custom/%s/records/%s" % (KEY, no), headers=hs).json()
    assert got["data"]["approved_amt"] == 500 and "secret" not in got["data"]
    ok = client.put("/api/custom/%s/records/%s" % (KEY, no), headers=hs, json={"values": {"title": "T2", "approved_amt": 500}})
    assert ok.status_code == 200 and ok.json()["data"]["title"] == "T2"
    bad = client.put("/api/custom/%s/records/%s" % (KEY, no), headers=hs, json={"values": {"title": "T2", "approved_amt": 1}})
    assert bad.status_code == 403
    assert client.get("/api/custom/%s/records/%s" % (KEY, no), headers=hb).json()["data"] == {"title": "T2", "approved_amt": 500, "secret": "s"}
    # 財務新建單可以填核定金額與內部備註
    fin = client.post("/api/custom/%s/records" % KEY, headers=hf, json={"values": {"title": "F", "approved_amt": 7, "secret": "z"}})
    assert fin.status_code == 200 and fin.json()["data"]["secret"] == "z"


def test_required_and_editable_restricted_is_a_publish_problem(client, make_user):
    hb = _login(client, make_user, "b3e_boss", role="superadmin")
    b = _body()
    b["fields"][1]["required"] = True
    probs = _publish(client, hb, b, key="b3edit2")
    assert probs and any("看得到或改得到" in p["message"] for p in probs) and probs[0]["path"].startswith("fields[")
    b2 = _body()
    b2["fields"][1]["access"] = {"editableTo": {"roles": ["nope"]}}
    assert any("不認得的角色" in p["message"] for p in _publish(client, hb, b2, key="b3edit3"))


def test_menu_visible_to_also_blocks_direct_api_calls_but_not_the_approver_path(client, make_user):
    hb = _login(client, make_user, "b3e_boss", role="superadmin")
    hs = _login(client, make_user, "b3e_staff", modules=["custom." + KEY])
    b = _body(menu={"group": "測試", "visibleTo": {"users": ["b3e_boss"]}})
    assert _publish(client, hb, b) == []
    no = client.post("/api/custom/%s/records" % KEY, headers=hb, json={"values": {"title": "T"}}).json()["record_no"]
    assert client.get("/api/custom/%s/meta" % KEY, headers=hs).status_code == 404                    # 有模組權限但選單不對他開放 ⇒ 直接打也 404
    assert client.get("/api/custom/%s/records" % KEY, headers=hs).status_code == 404
    assert client.post("/api/custom/%s/records" % KEY, headers=hs, json={"values": {"title": "x"}}).status_code == 404
    assert client.get("/api/custom/%s/records/%s" % (KEY, no), headers=hs).status_code in (403, 404)
    assert client.get("/api/custom/%s/meta" % KEY, headers=hb).status_code == 200
    # 反向控制：沒設 visibleTo ⇒ 有權限就能用
    b2 = _body()
    assert _publish(client, hb, b2) == []
    assert client.get("/api/custom/%s/meta" % KEY, headers=hs).status_code == 200
