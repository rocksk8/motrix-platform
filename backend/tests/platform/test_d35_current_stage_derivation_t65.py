# -*- coding: utf-8 -*-
"""D-35 驗證（T65）：案件清單卡片徽章『待 <current_stage>』的來源怎麼衍生——特徵測試（characterization），不改任何程式。

衍生式（modules/case/api/quotations.py，清單 SELECT 與匯出各一份）：
    current_stage = (SELECT label FROM case_stages WHERE quote_no=… AND done=0 ORDER BY sort_order LIMIT 1)
前端（case-management.html）：deal_tag=='已成案' 且 current_stage 有值 ⇒ 『待 <current_stage>』，否則 stLabel('已成案')。
所以徽章 = 『依 sort_order 的第一筆未完成階段』，與階段是否『真的還該做』無關：殘留（過期分頁／舊資料）的未完成列會被當成目前階段。
"""
import json

import pytest

from core import source_tree

pytestmark = pytest.mark.skipif(not source_tree.module_installed("modules/case/"), reason="需要案件模組（M01）")

NOW = "2026-01-01T00:00:00"


def _login(client, make_user, name):
    u, pw = make_user(username=name, role="superadmin")[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}


def _case(no, stages):
    """已成案的案件＋直接寫入 case_stages（label, sort_order, done）——用來重現各種資料狀態。"""
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)", (no, "已送出", "客", "案", 1000, 952, json.dumps({"dealTag": "已成案", "caseRecord": {}}), NOW, NOW, "已成案"))
        for label, order, done in stages:
            conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, created_at, updated_at) VALUES (?,?,?,?,?,?)", (no, label, order, done, NOW, NOW))
        conn.commit()
    finally:
        conn.close()


def _row(client, h, no):
    r = client.get("/api/quotations?deal_tag=已成案&q=%s&limit=20" % no, headers=h)
    assert r.status_code == 200, r.text
    rows = [x for x in r.json()["items"] if x["quote_no"] == no]
    assert len(rows) == 1
    return rows[0]


def _badge(row):
    """與 case-management.html 卡片徽章同式（只看輸入：deal_tag、current_stage）。"""
    return "待 " + row["current_stage"] if row["deal_tag"] == "已成案" and row["current_stage"] else "已成案"


def test_first_undone_stage_by_sort_order_is_the_badge(client, make_user):
    h = _login(client, make_user, "d35_a")
    _case("MQ-D35-A", [("甲", 1, 1), ("丙", 3, 0), ("乙", 2, 0)])                     # 插入順序 ≠ sort_order
    row = _row(client, h, "MQ-D35-A")
    assert (row["current_stage"], row["stage_total"], row["stage_done"]) == ("乙", 3, 1)
    assert _badge(row) == "待 乙"


def test_all_stages_done_or_no_stages_reads_plain_won(client, make_user):
    h = _login(client, make_user, "d35_b")
    _case("MQ-D35-B1", [("甲", 1, 1), ("乙", 2, 1)])
    _case("MQ-D35-B2", [])
    for no in ("MQ-D35-B1", "MQ-D35-B2"):
        row = _row(client, h, no)
        assert row["current_stage"] is None and _badge(row) == "已成案"                # 全部做完但尚未結案：仍顯示『已成案』


def test_leftover_undone_row_becomes_the_badge_even_when_real_stages_are_done(client, make_user):
    """S-ST4 之前的舊分頁存檔會把已刪除／已完成的階段『復活』成 done=0 的殘列（S-ST4 之後不再產生，但舊資料裡可能還有）。
    衍生式沒有任何『這列是殘留』的資訊 ⇒ 徽章顯示『待 殘留階段』。這是資料問題的外顯，不是衍生式寫錯；程式沒有辦法分辨。"""
    h = _login(client, make_user, "d35_c")
    _case("MQ-D35-C", [("甲", 1, 1), ("乙", 2, 1), ("已刪除又復活的階段", 9, 0)])
    row = _row(client, h, "MQ-D35-C")
    assert row["current_stage"] == "已刪除又復活的階段" and row["stage_done"] == 2 and row["stage_total"] == 3
    assert _badge(row) == "待 已刪除又復活的階段"


def test_leftover_row_with_a_lower_sort_order_hides_the_real_current_stage(client, make_user):
    h = _login(client, make_user, "d35_d")
    _case("MQ-D35-D", [("殘留（舊分頁復活）", 0, 0), ("甲", 1, 1), ("乙", 2, 0)])
    row = _row(client, h, "MQ-D35-D")
    assert row["current_stage"] == "殘留（舊分頁復活）"                                  # 真正的目前階段『乙』被蓋掉
    assert _badge(row) == "待 殘留（舊分頁復活）"


def test_tie_on_sort_order_has_no_tie_break(client, make_user):
    """ORDER BY sort_order 沒有第二排序鍵：同值時取哪一列由 SQLite 決定（實務上是先建立的），不是契約。端點建階段時 sort_order 單調遞增，正常不會同值。"""
    h = _login(client, make_user, "d35_e")
    _case("MQ-D35-E", [("先", 5, 0), ("後", 5, 0)])
    assert _row(client, h, "MQ-D35-E")["current_stage"] in ("先", "後")


def test_endpoint_created_stages_never_tie_and_deleting_the_current_one_moves_the_badge(client, make_user):
    h = _login(client, make_user, "d35_f")
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)", ("MQ-D35-F", "草稿", "客", "案", 1000, 952, json.dumps({"dealTag": "已成案", "caseRecord": {}}), NOW, NOW, "已成案"))
        conn.commit()
    finally:
        conn.close()
    ids = [client.post("/api/quotations/MQ-D35-F/stages", headers=h, json={"label": n}).json()["id"] for n in ("甲", "乙", "丙")]
    assert _row(client, h, "MQ-D35-F")["current_stage"] == "甲"
    assert client.put("/api/quotations/MQ-D35-F/stages/%d" % ids[0], headers=h, json={"done": True, "doneAt": "2026-10-01"}).status_code == 200
    assert _row(client, h, "MQ-D35-F")["current_stage"] == "乙"
    assert client.delete("/api/quotations/MQ-D35-F/stages/%d" % ids[1], headers=h).status_code == 200
    assert _row(client, h, "MQ-D35-F")["current_stage"] == "丙"
