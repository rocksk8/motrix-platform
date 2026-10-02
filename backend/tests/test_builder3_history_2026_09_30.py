# -*- coding: utf-8 -*-
"""建構器第三輪 S5（2026-09-30）：單據「送簽→退回→修改重送」的修訂紀錄（-R1、-R2）與差異。
- `record_no` 不變；顯示單號首次送簽不帶尾碼、被退回後重送＝-R1、再退回再送＝-R2（列表／詳情／輸出都用顯示單號）
- 每次送簽寫一列不可變快照（欄位值＋定義版本），決定（核可／退回＋原因）回填同一列
- 差異逐欄位（明細表逐列逐欄）、看不到的欄位不出現在快照差異裡；與讀單同權限
- 沒有簽核層的流程不產生快照、不帶尾碼（反向控制）"""
import json

import pytest

KEY = "b3hist"


def _login(client, make_user, name, role="user", modules=None):
    u, p = make_user(name, "Custom-Pass-123", role=role, modules=modules)[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _db(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _body(**over):
    f = lambda k, l, t, **kw: dict({"key": k, "label": l, "type": t, "dataClass": "T1"}, **kw)
    b = {"name": "修訂測試", "permission": "custom." + KEY, "numbering": {"prefix": "RV", "period": "none", "digits": 3},
         "fields": [f("title", "標題", "text", required=True), f("amt", "金額", "number"),
                    f("secret", "內部備註", "text", access={"visibleTo": {"users": ["b3h_boss"]}}),
                    f("lines", "明細", "table", columns=[{"key": "name", "label": "品名", "type": "text"}, {"key": "qty", "label": "數量", "type": "number"}])],
         "workflow": {"initial": "draft",
                      "states": [{"key": "draft", "label": "草稿"},
                                 {"key": "pending", "label": "簽核中", "approval": {"tiers": [{"approvers": [{"username": "b3h_appr"}]}],
                                                                                    "on_approved": "done", "on_rejected": "draft"}},
                                 {"key": "done", "label": "完成", "final": True}],
                      "transitions": [{"key": "submit", "label": "送簽", "from": "draft", "to": "pending"}]}}
    b.update(over)
    return b


@pytest.fixture()
def world(client, make_user):
    boss = _login(client, make_user, "b3h_boss", role="superadmin")
    appr = _login(client, make_user, "b3h_appr", role="user", modules=[])
    staff = _login(client, make_user, "b3h_staff", modules=["custom." + KEY])
    r = client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=boss, json={"body": _body()}).json()
    assert r["problems"] == [], r["problems"]
    assert client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=boss, json={}).status_code == 200
    return client, boss, appr, staff


def _new(client, h, **vals):
    r = client.post("/api/custom/%s/records" % KEY, headers=h, json={"values": dict({"title": "T"}, **vals)})
    assert r.status_code == 200, r.text
    return r.json()["record_no"]


def _post(client, h, no, what, note=""):
    path = "transitions/submit" if what == "submit" else what
    r = client.post("/api/custom/%s/records/%s/%s" % (KEY, no, path), headers=h, json={"note": note})
    assert r.status_code == 200, r.text
    return r.json()


def _get(client, h, no):
    return client.get("/api/custom/%s/records/%s" % (KEY, no), headers=h).json()


def test_first_submission_has_no_suffix_and_a_rejected_resubmission_becomes_r1_then_r2(world):
    client, boss, appr, staff = world
    no = _new(client, staff, amt=100)
    assert _get(client, staff, no)["displayNo"] == no
    _post(client, staff, no, "submit")
    rec = _get(client, staff, no)
    assert rec["displayNo"] == no and rec["revision"] == 0                        # 首次送簽：不帶尾碼
    _post(client, appr, no, "reject", "金額不對")
    assert _get(client, staff, no)["status"] == "draft"
    client.put("/api/custom/%s/records/%s" % (KEY, no), headers=staff, json={"values": {"title": "T", "amt": 120}})
    _post(client, staff, no, "submit")
    rec = _get(client, staff, no)
    assert rec["displayNo"] == no + "-R1" and rec["record_no"] == no and rec["revision"] == 1
    assert rec["view"]["recordNo"] == no + "-R1" and rec["view"]["baseRecordNo"] == no    # 輸出抬頭顯示 -R1
    _post(client, appr, no, "reject", "還是不對")
    client.put("/api/custom/%s/records/%s" % (KEY, no), headers=staff, json={"values": {"title": "T", "amt": 130}})
    _post(client, staff, no, "submit")
    assert _get(client, staff, no)["displayNo"] == no + "-R2"
    rows = client.get("/api/custom/%s/records" % KEY, headers=staff).json()
    assert [(r["record_no"], r["displayNo"]) for r in rows] == [(no, no + "-R2")]
    html = client.get("/api/custom/%s/records/%s/output" % (KEY, no), headers=staff).text
    assert no + "-R2" in html


def test_snapshots_keep_each_submission_and_fill_the_decision(world):
    client, boss, appr, staff = world
    no = _new(client, staff, amt=100)
    _post(client, staff, no, "submit")
    _post(client, appr, no, "reject", "金額不對")
    client.put("/api/custom/%s/records/%s" % (KEY, no), headers=staff, json={"values": {"title": "T", "amt": 120}})
    _post(client, staff, no, "submit")
    _post(client, appr, no, "approve", "OK")
    revs = client.get("/api/custom/%s/records/%s/revisions" % (KEY, no), headers=staff).json()
    assert revs["current"]["displayNo"] == no + "-R1" and revs["current"]["status"] == "done"
    r0, r1 = revs["revisions"][1], revs["revisions"][0]                            # 新的在前
    assert (r0["revision"], r0["decision"], r0["note"], r0["decidedBy"]) == (0, "rejected", "金額不對", "b3h_appr")
    assert (r1["revision"], r1["decision"], r1["note"], r1["displayNo"]) == (1, "approved", "OK", no + "-R1")
    assert r0["defVersion"] == 1 and r0["submittedBy"] == "b3h_staff"
    snap = _db("SELECT revision, data_json FROM custom_record_snapshots WHERE module_key=? ORDER BY revision", (KEY,))
    assert [(s["revision"], json.loads(s["data_json"])["amt"]) for s in snap] == [(0, 100), (1, 120)]      # 各版內容都保留


def test_diff_between_revisions_and_current_including_table_rows(world):
    client, boss, appr, staff = world
    no = _new(client, staff, amt=100, lines=[{"name": "A", "qty": 1}, {"name": "B", "qty": 2}])
    _post(client, staff, no, "submit")
    _post(client, appr, no, "reject", "改一下")
    client.put("/api/custom/%s/records/%s" % (KEY, no), headers=staff,
               json={"values": {"title": "T2", "amt": 100, "lines": [{"name": "A", "qty": 5}, {"name": "B", "qty": 2}, {"name": "C", "qty": 3}]}})
    _post(client, staff, no, "submit")
    d = client.get("/api/custom/%s/records/%s/revisions/diff" % (KEY, no), headers=staff, params={"a": "0", "b": "1"}).json()
    by = {c["key"]: c for c in d["changes"]}
    assert d["a"] == "首次送簽" and d["b"] == "R1" and set(by) == {"title", "lines"}          # amt 沒變不列
    assert (by["title"]["old"], by["title"]["new"], by["title"]["op"]) == ("T", "T2", "change")
    assert by["lines"]["rows"] == [{"index": 0, "op": "change", "cols": {"qty": {"old": 1, "new": 5}}},
                                   {"index": 2, "op": "add", "cols": {"name": {"old": None, "new": "C"}, "qty": {"old": None, "new": 3}}}]
    cur = client.get("/api/custom/%s/records/%s/revisions/diff" % (KEY, no), headers=staff, params={"a": "1", "b": "current"}).json()
    assert cur["changes"] == [] and cur["b"] == "目前"
    assert client.get("/api/custom/%s/records/%s/revisions/diff" % (KEY, no), headers=staff, params={"a": "9", "b": "current"}).status_code == 404
    assert client.get("/api/custom/%s/records/%s/revisions/diff" % (KEY, no), headers=staff, params={"a": "x", "b": "current"}).status_code == 400


def test_hidden_fields_never_appear_in_revision_diffs(world):
    client, boss, appr, staff = world
    no = _new(client, boss, secret="v1")
    _post(client, boss, no, "submit")
    _post(client, appr, no, "reject", "x")
    client.put("/api/custom/%s/records/%s" % (KEY, no), headers=boss, json={"values": {"title": "T", "secret": "v2"}})
    _post(client, boss, no, "submit")
    seen_by_boss = client.get("/api/custom/%s/records/%s/revisions/diff" % (KEY, no), headers=boss, params={"a": "0", "b": "1"}).json()
    assert [c["key"] for c in seen_by_boss["changes"]] == ["secret"]
    seen_by_staff = client.get("/api/custom/%s/records/%s/revisions/diff" % (KEY, no), headers=staff, params={"a": "0", "b": "1"})
    assert seen_by_staff.status_code == 200 and seen_by_staff.json()["changes"] == []          # 看不到的欄位：差異裡也沒有
    assert "v1" not in seen_by_staff.text and "v2" not in seen_by_staff.text


def test_approver_without_module_permission_can_read_revisions_but_a_stranger_cannot(world, make_user, client):
    client_, boss, appr, staff = world
    no = _new(client, staff)
    _post(client, staff, no, "submit")
    assert client.get("/api/custom/%s/records/%s/revisions" % (KEY, no), headers=appr).status_code == 200      # 簽核人（沒有模組權限）
    stranger = _login(client, make_user, "b3h_stranger", modules=[])
    assert client.get("/api/custom/%s/records/%s/revisions" % (KEY, no), headers=stranger).status_code == 403
    assert client.get("/api/custom/%s/records/%s/revisions/diff" % (KEY, no), headers=stranger).status_code == 403


def test_workflow_without_approval_tiers_creates_no_snapshots_and_no_suffix(client, make_user):
    boss = _login(client, make_user, "b3h_boss", role="superadmin")
    b = _body()
    b["workflow"]["states"][1].pop("approval")
    b["workflow"]["states"][1]["final"] = False
    b["workflow"]["transitions"].append({"key": "finish", "label": "完成", "from": "pending", "to": "done"})
    key = "b3hist2"
    b["permission"] = "custom." + key
    assert client.put("/api/definitions/custom_module/%s/draft" % key, headers=boss, json={"body": b}).json()["problems"] == []
    assert client.post("/api/definitions/custom_module/%s/publish" % key, headers=boss, json={}).status_code == 200
    no = client.post("/api/custom/%s/records" % key, headers=boss, json={"values": {"title": "x"}}).json()["record_no"]
    assert client.post("/api/custom/%s/records/%s/transitions/submit" % (key, no), headers=boss, json={}).status_code == 200
    assert _db("SELECT COUNT(*) AS n FROM custom_record_snapshots WHERE module_key=?", (key,))[0]["n"] == 0
    assert client.get("/api/custom/%s/records/%s" % (key, no), headers=boss).json()["displayNo"] == no
    assert client.get("/api/custom/%s/records/%s/revisions" % (key, no), headers=boss).json()["revisions"] == []
