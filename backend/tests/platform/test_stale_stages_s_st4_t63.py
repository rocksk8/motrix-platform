# -*- coding: utf-8 -*-
"""S-ST4：報價單整包存檔（PUT /api/quotations/{no}）不再依用戶端手上的 stages 改動 case_stages
（docs/platform/plans/CASE-STAGE-STALE-SAVE-ANALYSIS-T63.md）。

舊分頁（表單載入時的 caseRecord.stages）存檔：別人套用／刪除／勾選完成過的階段不被蓋掉、不復活、不被刪；
data_json 裡的 caseRecord.stages 換回表內現況；沒帶 caseRecord／stages 鍵的舊單行為不變；樂觀鎖 409 照舊。
"""
import json

import pytest

from core import source_tree

pytestmark = pytest.mark.skipif(not source_tree.module_installed("modules/case/"), reason="需要案件模組（M01）")


def _login(client, make_user, name):
    u, pw = make_user(username=name, role="superadmin")[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}


def _q(sql, *args):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _draft(client, h, no):
    """直接寫一張草稿（草稿不被狀態鎖擋），再用端點建階段。"""
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)", (no, "草稿", "客", "案", 1000, 952, json.dumps({"caseRecord": {}}), "2026-01-01T00:00:00", "2026-01-01T00:00:00", ""))
        conn.commit()
    finally:
        conn.close()
    ids = []
    for label in ("甲", "乙", "丙"):
        ids.append(client.post("/api/quotations/%s/stages" % no, headers=h, json={"label": label}).json()["id"])
    return ids


def _stale_copy(no):
    return json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", no)[0]["data_json"])


def test_stale_put_keeps_server_stages(client, make_user):
    h = _login(client, make_user, "st4_a")
    no = "MQ-ST4-A"
    a, b, c = _draft(client, h, no)
    stale = _stale_copy(no)                                                            # 舊分頁載入時的樣子：甲乙丙、都沒完成
    assert [s["label"] for s in stale["caseRecord"]["stages"]] == ["甲", "乙", "丙"]
    # 別的分頁／別人：刪掉乙、勾選甲完成、新增丁
    assert client.delete("/api/quotations/%s/stages/%d" % (no, b), headers=h).status_code == 200
    assert client.put("/api/quotations/%s/stages/%d" % (no, a), headers=h, json={"done": True, "doneAt": "2026-10-01"}).status_code == 200
    d = client.post("/api/quotations/%s/stages" % no, headers=h, json={"label": "丁"}).json()["id"]
    before = _q("SELECT id, label, done, done_at FROM case_stages WHERE quote_no=? ORDER BY sort_order", no)
    # 舊分頁存檔（不帶 _expectedUpdatedAt）：階段還是舊的那份
    r = client.put("/api/quotations/" + no, headers=h, json={"status": "草稿", "data": stale})
    assert r.status_code == 200, r.text
    after = _q("SELECT id, label, done, done_at FROM case_stages WHERE quote_no=? ORDER BY sort_order", no)
    assert after == before                                                             # 乙沒復活、甲仍完成、丁還在、丙沒被刪
    assert [x["label"] for x in after] == ["甲", "丙", "丁"] and after[0]["done"] == 1 and d in [x["id"] for x in after]
    mirror = _stale_copy(no)["caseRecord"]["stages"]
    assert [s["id"] for s in mirror] == [x["id"] for x in after] and mirror[0]["done"] is True      # data_json 換回表內現況


def test_stale_expected_updated_at_still_409(client, make_user):
    h = _login(client, make_user, "st4_b")
    no = "MQ-ST4-B"
    _draft(client, h, no)
    stale = _stale_copy(no)
    stale["_expectedUpdatedAt"] = "2000-01-01T00:00:00"
    r = client.put("/api/quotations/" + no, headers=h, json={"status": "草稿", "data": stale})
    assert r.status_code == 409


def test_put_without_stages_key_is_unchanged(client, make_user):
    h = _login(client, make_user, "st4_c")
    no = "MQ-ST4-C"
    ids = _draft(client, h, no)
    data = _stale_copy(no)
    data["caseRecord"].pop("stages")
    r = client.put("/api/quotations/" + no, headers=h, json={"status": "草稿", "data": data})
    assert r.status_code == 200
    assert [x["id"] for x in _q("SELECT id FROM case_stages WHERE quote_no=? ORDER BY sort_order", no)] == ids       # 表不動
    assert "stages" not in _stale_copy(no)["caseRecord"]                                                           # 和過去一樣：用戶端沒送就不補
