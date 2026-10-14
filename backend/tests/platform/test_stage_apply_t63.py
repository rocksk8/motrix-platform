# -*- coding: utf-8 -*-
"""S-ST2：套用案件階段樣板（設計 docs/platform/plans/CASE-STAGE-TEMPLATE-INVESTIGATION-T62.md）。

①純計算 `modules.case.stage_apply.plan`：日期、比例只在空案件帶入、附加只補缺的種類、前置階段換 id、不合法輸入
②端點：旗標關 ⇒ 404（和今天一樣）；dryRun 不寫入；套用＝複製（stage_key／ratio_bp／dependsOn／日期）；權限；重複套用的保護
③整包存檔守門：舊前端（階段沒有 stageKey）整包存檔 ⇒ DB 的 stage_key／ratio_bp 不被洗掉；INSERT 分支只收合法鍵
④沒用樣板的案件：回應與鏡像沒有 stageKey 這個鍵（和今天一模一樣）
⑤資源回收桶：stage_key 刪除 → 還原後還在
⑥migration v9：冪等、欄位 NULL、舊列不補值
"""
import json
import sqlite3

import pytest

from core import source_tree
from helpers import stage_templates as ST
from modules.case import stage_apply as SA

needs_case = pytest.mark.skipif(not source_tree.module_installed("modules/case/"), reason="需要案件模組（M01）")

TPL = {"version": 1, "label": "標準施工案", "stages": [
    {"key": "survey", "label": "現場勘查", "offsetDays": 0, "durationDays": 3, "ratioBp": 0, "dependsOn": []},
    {"key": "install", "label": "設備安裝", "offsetDays": 3, "durationDays": 14, "ratioBp": 7000, "dependsOn": ["survey"]},
    {"key": "accept", "label": "驗收", "offsetDays": 17, "durationDays": 2, "ratioBp": 3000, "dependsOn": ["install"]}]}
NO_RATIO = {**TPL, "stages": [{k: v for k, v in s.items() if k != "ratioBp"} for s in TPL["stages"]]}


# ── ① 純計算 ─────────────────────────────────────────────────────────────
def test_plan_dates_and_ratio_on_empty_case():
    p = SA.plan(TPL, "2026-10-01", "new", [])
    got = [(s["key"], s["startDate"], s["dueDate"], s["ratioBp"]) for s in p["stages"]]
    assert got == [("survey", "2026-10-01", "2026-10-04", 0), ("install", "2026-10-04", "2026-10-18", 7000),
                   ("accept", "2026-10-18", "2026-10-20", 3000)]
    assert p["notes"] == [] and p["skipped"] == []
    assert p["stages"][1]["dependsOn"] == ["survey"] and p["stages"][1]["existingDeps"] == []


def test_plan_append_skips_ratio_and_existing_kinds():
    p = SA.plan(TPL, "2026-10-01", "append", [{"id": 5, "stage_key": "survey"}, {"id": 6, "stage_key": None}])
    assert [s["key"] for s in p["stages"]] == ["install", "accept"]
    assert all(s["ratioBp"] is None for s in p["stages"])                 # 附加模式不帶比例（金流）
    assert p["skipped"] == ["survey"]
    assert p["stages"][0]["existingDeps"] == [5] and p["stages"][0]["dependsOn"] == []
    assert any("比例" in n for n in p["notes"]) and any("現場勘查" in n and "survey" not in n for n in p["notes"])


def test_plan_no_ratio_template_has_no_ratio_note():
    p = SA.plan(NO_RATIO, "2026-10-01", "append", [{"id": 1, "stage_key": None}])
    assert not any("比例" in n for n in p["notes"])


def test_plan_new_mode_refuses_when_case_has_stages():
    with pytest.raises(SA.PlanError):
        SA.plan(TPL, "2026-10-01", "new", [{"id": 1, "stage_key": None}])


@pytest.mark.parametrize("base", ["", "2026-13-01", "10/01/2026", None, "2026-10-1x"])
def test_plan_rejects_bad_base_date(base):
    with pytest.raises(SA.PlanError):
        SA.plan(TPL, base, "new", [])


def test_plan_rejects_bad_mode_and_empty_template():
    with pytest.raises(SA.PlanError):
        SA.plan(TPL, "2026-10-01", "replace", [])
    with pytest.raises(SA.PlanError):
        SA.plan({"stages": []}, "2026-10-01", "new", [])


def test_plan_all_present_in_append_is_a_noop_with_note():
    ex = [{"id": i, "stage_key": k} for i, k in enumerate(["survey", "install", "accept"], 1)]
    p = SA.plan(TPL, "2026-10-01", "append", ex)
    assert p["stages"] == [] and any("沒有需要補上" in n for n in p["notes"])


# ── ② 端點 ───────────────────────────────────────────────────────────────
def _login(client, make_user, name, role="superadmin", modules=None):
    u, pw = make_user(username=name, role=role, **({"modules": modules} if modules is not None else {}))[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}


def _case(no):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
                     "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (no, "已送出", "樣板客戶", "樣板工程", 1000, 952, "{}",
                      "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        conn.commit()
    finally:
        conn.close()


def _q(sql, *args):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _publish_tpl(key, body):
    import db
    from core import definitions as D
    ST.ensure_kind()
    conn = db.get_db()
    try:
        D.save_draft(conn, ST.KIND, key, "company", body, user="t")
        D.publish(conn, ST.KIND, key, "company", note="t", user="t")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(ST, "enabled", lambda conn=None: True)
    from modules.case.api import quotations as q
    monkeypatch.setattr(q, "spawn_bg_thread", lambda target, args=(), **kw: None)


URL = "/api/quotations/%s/stages/apply-template"


@needs_case
def test_flag_off_is_404_and_writes_nothing(client, make_user, monkeypatch):
    monkeypatch.setattr(ST, "enabled", lambda conn=None: False)
    h = _login(client, make_user, "st2_off")
    _case("MQ-ST2-OFF")
    r = client.post(URL % "MQ-ST2-OFF", headers=h, json={"template": "std", "mode": "new"})
    assert r.status_code == 404
    assert _q("SELECT * FROM case_stages WHERE quote_no=?", "MQ-ST2-OFF") == []


@needs_case
def test_dry_run_then_apply_copies_everything(client, make_user, on):
    h = _login(client, make_user, "st2_apply")
    _case("MQ-ST2-A")
    _publish_tpl("std", TPL)
    d = client.post(URL % "MQ-ST2-A", headers=h, json={"template": "std", "mode": "new", "baseDate": "2026-10-01", "dryRun": True})
    assert d.status_code == 200, d.text
    assert [s["key"] for s in d.json()["stages"]] == ["survey", "install", "accept"] and "created" not in d.json()
    assert _q("SELECT * FROM case_stages WHERE quote_no=?", "MQ-ST2-A") == []        # dryRun 不寫入
    r = client.post(URL % "MQ-ST2-A", headers=h, json={"template": "std", "mode": "new", "baseDate": "2026-10-01"})
    assert r.status_code == 200, r.text
    rows = _q("SELECT id, label, sort_order, start_date, due_date, ratio_bp, stage_key, depends_on, done FROM case_stages "
              "WHERE quote_no=? ORDER BY sort_order", "MQ-ST2-A")
    assert [(x["label"], x["stage_key"], x["start_date"], x["due_date"], x["ratio_bp"], x["done"]) for x in rows] == [
        ("現場勘查", "survey", "2026-10-01", "2026-10-04", 0, 0), ("設備安裝", "install", "2026-10-04", "2026-10-18", 7000, 0),
        ("驗收", "accept", "2026-10-18", "2026-10-20", 3000, 0)]
    assert json.loads(rows[1]["depends_on"]) == [rows[0]["id"]] and json.loads(rows[2]["depends_on"]) == [rows[1]["id"]]
    assert [c["stageKey"] for c in r.json()["created"]] == ["survey", "install", "accept"]
    mirror = json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", "MQ-ST2-A")[0]["data_json"])["caseRecord"]["stages"]
    assert [m.get("stageKey") for m in mirror] == ["survey", "install", "accept"]       # 鏡像帶著種類鍵
    # 再套一次（new）⇒ 409，不重複建立
    again = client.post(URL % "MQ-ST2-A", headers=h, json={"template": "std", "mode": "new", "baseDate": "2026-10-01"})
    assert again.status_code == 409 and len(_q("SELECT id FROM case_stages WHERE quote_no=?", "MQ-ST2-A")) == 3


@needs_case
def test_append_only_adds_missing_kinds_without_ratio(client, make_user, on):
    h = _login(client, make_user, "st2_append")
    _case("MQ-ST2-B")
    _publish_tpl("std", TPL)
    manual = client.post("/api/quotations/MQ-ST2-B/stages", headers=h, json={"label": "手動階段"}).json()
    assert "stageKey" not in manual                                                      # 沒用樣板 ⇒ 回應沒有這個鍵
    r = client.post(URL % "MQ-ST2-B", headers=h, json={"template": "std", "mode": "append", "baseDate": "2026-10-01"})
    assert r.status_code == 200, r.text
    rows = _q("SELECT label, stage_key, ratio_bp FROM case_stages WHERE quote_no=? ORDER BY sort_order", "MQ-ST2-B")
    assert [x["stage_key"] for x in rows] == [None, "survey", "install", "accept"]
    assert all(x["ratio_bp"] is None for x in rows)                                      # 附加模式不帶比例
    assert any("比例" in n for n in r.json()["notes"])
    r2 = client.post(URL % "MQ-ST2-B", headers=h, json={"template": "std", "mode": "append", "baseDate": "2026-10-01"})
    assert r2.status_code == 200 and r2.json()["created"] == [] and len(_q("SELECT id FROM case_stages WHERE quote_no=?", "MQ-ST2-B")) == 4


@needs_case
def test_unknown_template_bad_date_and_permission(client, make_user, on):
    h = _login(client, make_user, "st2_perm")
    hn = _login(client, make_user, "st2_noperm", "engineer", modules=["customer"])        # 非 admin、不是業務、沒有 case_manage
    hm = _login(client, make_user, "st2_cm", "engineer", modules=["case_manage"])
    ha = _login(client, make_user, "st2_admin", "admin", modules=["customer"])
    _case("MQ-ST2-C")
    _publish_tpl("std", TPL)
    assert client.post(URL % "MQ-ST2-C", headers=h, json={"template": "nope", "mode": "new"}).status_code == 404
    assert client.post(URL % "MQ-ST2-C", headers=h, json={"template": "std", "mode": "new", "baseDate": "2026/10/01"}).status_code == 400
    # 看不到＝不存在（M01-O1，_guard_case／deny_case）：沒有權限的人拿到 404，跟查無此案同一個回應；權限規則與 create_case_stage 相同
    assert client.post(URL % "MQ-ST2-C", headers=hn, json={"template": "std", "mode": "new"}).status_code == 404
    assert client.post(URL % "MQ-ST2-C", headers=hm, json={"template": "std", "mode": "new", "dryRun": True}).status_code == 200      # case_manage 放行（執行面）
    assert client.post(URL % "MQ-ST2-C", headers=ha, json={"template": "std", "mode": "new", "dryRun": True}).status_code == 200      # admin+ 直通（owner scope 的 bypass），與新增階段一致
    assert client.post("/api/quotations/MQ-ST2-C/stages", headers=hn, json={"label": "x"}).status_code == 404                        # 對照：既有端點同一個結果
    assert client.post(URL % "MQ-ST2-C", json={"template": "std", "mode": "new"}).status_code in (401, 403)
    assert _q("SELECT id FROM case_stages WHERE quote_no=?", "MQ-ST2-C") == []


# ── ③ 整包存檔守門（舊前端不帶 stageKey）────────────────────────────────────
@needs_case
def test_whole_record_save_keeps_stage_key_and_ratio(client, make_user, on):
    from modules.case.api import quotations as q
    import db
    h = _login(client, make_user, "st2_guard")
    _case("MQ-ST2-G")
    _publish_tpl("std", TPL)
    client.post(URL % "MQ-ST2-G", headers=h, json={"template": "std", "mode": "new", "baseDate": "2026-10-01"})
    before = _q("SELECT id, stage_key, ratio_bp FROM case_stages WHERE quote_no=? ORDER BY sort_order", "MQ-ST2-G")
    # 舊前端整包存檔：陣列裡的階段沒有 stageKey／ratioBp
    old = [{"id": b["id"], "label": "改過的名稱%d" % i, "done": False, "startDate": "2026-11-01", "dueDate": "2026-11-02"} for i, b in enumerate(before)]
    conn = db.get_db()
    try:
        q._sync_json_stages_to_table(conn, "MQ-ST2-G", old)
        conn.commit()
    finally:
        conn.close()
    after = _q("SELECT id, stage_key, ratio_bp FROM case_stages WHERE quote_no=? ORDER BY sort_order", "MQ-ST2-G")
    assert after == before                                                              # 種類鍵與比例沒被洗掉
    assert _q("SELECT label FROM case_stages WHERE id=?", before[0]["id"])[0]["label"] == "改過的名稱0"   # 其他欄位照舊更新


@needs_case
def test_whole_record_insert_branch_only_takes_valid_keys(client, make_user, on):
    from modules.case.api import quotations as q
    import db
    _case("MQ-ST2-H")
    conn = db.get_db()
    try:
        q._sync_json_stages_to_table(conn, "MQ-ST2-H", [
            {"id": 9001, "label": "a", "stageKey": "survey"}, {"id": 9002, "label": "b", "stageKey": "Bad Key!"},
            {"id": 9003, "label": "c"}, {"id": 9004, "label": "d", "stageKey": 7}, {"id": 9005, "label": "e", "stageKey": "survey" + chr(10)}])
        conn.commit()
    finally:
        conn.close()
    assert [r["stage_key"] for r in _q("SELECT stage_key FROM case_stages WHERE quote_no=? ORDER BY sort_order", "MQ-ST2-H")] == ["survey", None, None, None, None]


# ── ⑤ 資源回收桶 ─────────────────────────────────────────────────────────
@needs_case
def test_recycle_roundtrip_keeps_stage_key():
    import db
    from modules.case import recycle_adapter as RA
    _case("MQ-ST2-R")
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, done_at, start_date, due_date, assigned_to, depends_on, "
                     "created_at, updated_at, stage_key, ratio_bp) VALUES ('MQ-ST2-R','x',0,0,'','','','[]','[]','t','t','accept',3000)")
        snap = RA._rows(conn, "case_stages", "quote_no=?", ("MQ-ST2-R",))
        assert snap[0]["stage_key"] == "accept"
        conn.execute("DELETE FROM case_stages WHERE quote_no='MQ-ST2-R'")
        RA._insert(conn, "case_stages", snap[0], drop_id=True)
        row = conn.execute("SELECT stage_key, ratio_bp FROM case_stages WHERE quote_no='MQ-ST2-R'").fetchone()
        assert (row["stage_key"], row["ratio_bp"]) == ("accept", 3000)
        # 舊快照（沒有 stage_key 這一欄）也能還原 ⇒ NULL
        old = {k: v for k, v in snap[0].items() if k != "stage_key"}
        conn.execute("DELETE FROM case_stages WHERE quote_no='MQ-ST2-R'")
        RA._insert(conn, "case_stages", old, drop_id=True)
        assert conn.execute("SELECT stage_key FROM case_stages WHERE quote_no='MQ-ST2-R'").fetchone()["stage_key"] is None
        conn.rollback()
    finally:
        conn.close()


# ── ⑥ migration v9 ───────────────────────────────────────────────────────
def _migration():
    import importlib
    return importlib.import_module("modules.case.migrations.0009_stage_key")


def test_migration_is_idempotent_and_leaves_old_rows_null():
    m = _migration()
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE case_stages (id INTEGER PRIMARY KEY, quote_no TEXT, label TEXT)")
    c.execute("INSERT INTO case_stages (quote_no, label) VALUES ('Q','old')")
    assert m.up(c) is None and m.up(c) is None                                          # 冪等
    cols = {r[1] for r in c.execute("PRAGMA table_info(case_stages)")}
    assert {"stage_key", "ratio_bp"} <= cols
    assert c.execute("SELECT stage_key, ratio_bp FROM case_stages").fetchone() == (None, None)


def test_migration_reports_missing_table_instead_of_raising():
    c = sqlite3.connect(":memory:")
    assert isinstance(_migration().up(c), str)


# ── ⑦ 案件頁（靜態）──────────────────────────────────────────────────────
def _read(rel):
    from pathlib import Path
    return (Path(__file__).resolve().parents[3] / rel).read_text(encoding="utf-8")


def _page(name):
    from core import source_tree
    return source_tree.page_file(name).read_text(encoding="utf-8")


def test_case_page_wiring_is_flag_gated_and_registered():
    html = _page("case-management.html")
    js = _read("frontend/js/case-management-exec.js")
    mod = json.loads(_read("backend/modules/case/module.json"))
    # 旗標：同一次設定請求（附在名單最後面）；關著 ⇒ stOn=false ⇒ 按鈕與對話框都不顯示、不送請求
    assert "'builder_status_display', 'builder_stage_templates'], { token: s.token })" in html
    assert 'x-show="stOn && aShown(\'applyStageTemplate\')"' in html and "stOn: false," in js
    assert "stInit()" in js and "/templates`" in js                      # 樣板清單只在按下按鈕時才讀
    assert "confirm(" not in js[js.index("async stOpen"):js.index("async addStage")]   # 不用原生對話框
    # 登記為案件頁的 action（排版器可隱藏／改名）
    acts = json.dumps(mod, ensure_ascii=False)
    assert '"applyStageTemplate"' in acts


@needs_case
def test_preview_endpoint_superadmin_only_and_validates(client, make_user, on):
    h = _login(client, make_user, "st2_pv")
    hn = _login(client, make_user, "st2_pvn", "admin", modules=["customer"])
    url = "/api/quotations/stage-templates/preview"
    ok = client.post(url, headers=h, json={"key": "std", "template": TPL, "baseDate": "2026-10-01"})
    assert ok.status_code == 200 and [s["key"] for s in ok.json()["stages"]] == ["survey", "install", "accept"]
    bad = client.post(url, headers=h, json={"key": "std", "template": {**TPL, "stages": [{**TPL["stages"][0], "ratioBp": 5000}] + TPL["stages"][1:]}})
    assert bad.status_code == 422 and bad.json()["detail"]["problems"]
    assert client.post(url, headers=hn, json={"key": "std", "template": TPL}).status_code in (401, 403)


@needs_case
def test_templates_list_endpoint_and_flag_off(client, make_user, monkeypatch):
    h = _login(client, make_user, "st2_list")
    _case("MQ-ST2-L")
    monkeypatch.setattr(ST, "enabled", lambda conn=None: False)
    assert client.get("/api/quotations/MQ-ST2-L/stages/templates", headers=h).status_code == 404
    monkeypatch.setattr(ST, "enabled", lambda conn=None: True)
    _publish_tpl("std", TPL)
    items = client.get("/api/quotations/MQ-ST2-L/stages/templates", headers=h).json()["items"]
    assert {"key": "std", "label": "標準施工案", "stageCount": 3, "hasRatio": True} in items


# ── 04 審查修正（r4）──────────────────────────────────────────────────────
def test_plan_wraps_broken_published_content_as_400():
    for bad in ({"stages": [{"key": "a"}]}, {"stages": [{"key": "a", "label": "x", "offsetDays": "x", "durationDays": 1}]},
                {"stages": "nope"}, {"stages": [None]}, {"stages": [{"key": "a", "label": "x", "offsetDays": 1, "durationDays": 1, "dependsOn": 5}]}):
        with pytest.raises(SA.PlanError) as e:
            SA.plan(bad, "2026-10-01", "new", [])
        assert e.value.status == 400
    with pytest.raises(SA.PlanError) as e:
        SA.plan(TPL, "2026-10-01", "new", [{"id": 1, "stage_key": None, "label": "x"}])
    assert e.value.status == 409


def test_plan_append_warns_about_same_name_manual_stage():
    p = SA.plan(TPL, "2026-10-01", "append", [{"id": 1, "stage_key": None, "label": " 驗收 "}])
    assert any("兩個同名" in n and "驗收" in n for n in p["notes"])
    q = SA.plan(TPL, "2026-10-01", "append", [{"id": 1, "stage_key": "accept", "label": "驗收"}])
    assert not any("兩個同名" in n for n in q["notes"])


@needs_case
@pytest.mark.parametrize("val", ["true", 1, "1", "false", 0, [], {}])
def test_dry_run_must_be_a_boolean(client, make_user, on, val):
    h = _login(client, make_user, "st2_dry%s" % abs(hash(str(val)) % 1000))
    _case("MQ-ST2-D%d" % (abs(hash(str(val))) % 100000))
    no = "MQ-ST2-D%d" % (abs(hash(str(val))) % 100000)
    _publish_tpl("std", TPL)
    r = client.post(URL % no, headers=h, json={"template": "std", "mode": "new", "baseDate": "2026-10-01", "dryRun": val})
    assert r.status_code == 400
    assert _q("SELECT id FROM case_stages WHERE quote_no=?", no) == []             # 非布林 ⇒ 什麼都沒寫


@needs_case
def test_write_takes_the_lock_before_reading_stages_but_preview_does_not(client, make_user, on, monkeypatch):
    from modules.case.api import quotations as q
    h = _login(client, make_user, "st2_lock")
    _case("MQ-ST2-K")
    _publish_tpl("std", TPL)
    seen = []
    real = q.begin_write
    monkeypatch.setattr(q, "begin_write", lambda c: (seen.append(1), real(c))[1])
    client.post(URL % "MQ-ST2-K", headers=h, json={"template": "std", "mode": "new", "baseDate": "2026-10-01", "dryRun": True})
    assert seen == []                                                               # 預覽不拿寫鎖
    r = client.post(URL % "MQ-ST2-K", headers=h, json={"template": "std", "mode": "new", "baseDate": "2026-10-01"})
    assert r.status_code == 200 and seen == [1, 1]       # 第一次＝套用前先拿寫鎖（讀現有階段之前）；第二次＝commit 後 _sync_stages_to_json 鏡像寫回自己再拿一次
    # 第二個（等同兩個同時請求裡慢的那個）看到的是第一個已寫入的階段 ⇒ 409，不會再建一組
    r2 = client.post(URL % "MQ-ST2-K", headers=h, json={"template": "std", "mode": "new", "baseDate": "2026-10-01"})
    assert r2.status_code == 409 and len(_q("SELECT id FROM case_stages WHERE quote_no=?", "MQ-ST2-K")) == 3
    assert sum(x["ratio_bp"] or 0 for x in _q("SELECT ratio_bp FROM case_stages WHERE quote_no=?", "MQ-ST2-K")) == 10000


@needs_case
def test_note_about_reminders_and_updated_at_bump(client, make_user, on):
    from datetime import date, timedelta
    h = _login(client, make_user, "st2_soon")
    _case("MQ-ST2-S")
    _publish_tpl("std", TPL)
    base = date.today().isoformat()
    d = client.post(URL % "MQ-ST2-S", headers=h, json={"template": "std", "mode": "new", "baseDate": base, "dryRun": True}).json()
    assert any("到期提醒" in n for n in d["notes"])                                  # survey 的迄日是 base+3 ⇒ 會被提醒
    far = (date.today() + timedelta(days=60)).isoformat()
    d2 = client.post(URL % "MQ-ST2-S", headers=h, json={"template": "std", "mode": "new", "baseDate": far, "dryRun": True}).json()
    assert not any("到期提醒" in n for n in d2["notes"])
    before = _q("SELECT updated_at FROM quotations WHERE quote_no=?", "MQ-ST2-S")[0]["updated_at"]
    assert client.post(URL % "MQ-ST2-S", headers=h, json={"template": "std", "mode": "new", "baseDate": far}).status_code == 200
    assert _q("SELECT updated_at FROM quotations WHERE quote_no=?", "MQ-ST2-S")[0]["updated_at"] > before    # N4：鏡像寫回推進案件的 updated_at


def test_preview_dialog_ignores_stale_responses_static():
    js = _read("frontend/js/case-management-exec.js")
    a = js.index("async stPreview"); b = js.index("async stApply")
    assert "d._seq" in js[a:b] and js[a:b].count("seq !== d._seq") >= 1 and "seq === d._seq" in js[a:b]
    ap = js[b:js.index("async addStage")]
    assert "d.plan.template !== d.key" in ap and "dryRun: false" in ap


def test_default_stage_seed_is_skipped_only_when_flag_on_and_template_published_static():
    core = _read("frontend/js/case-management-core.js")
    a = core.index("async _seedDefaultStagesIfEmpty")
    seed = core[a:core.index("caseReadOnly()", a)]               # 結尾要從起點之後找：第一個 caseReadOnly() 在更前面（canUploadSignedBack），切出來會是空字串
    assert "if (this._stFlag) { await this.stInit(); if (this.stTpl.length) return }" in seed        # 旗標開＋有樣板才跳過
    assert "this._stFlag === undefined && this._layoutP" in seed                                   # 旗標還沒讀完才等；讀完／關著 ⇒ 不多等
    assert seed.index("_stFlag") < seed.index("const labels = ['訂單確認'")                         # 決定在建立 5 個預設階段之前
    html = _page("case-management.html")
    assert "d._layoutP = d.initLayout()" in html and "已發布階段樣板時，沒有階段的案件不會再自動建立 5 個預設階段" in html
    form = _page("quotation-form.html")
    assert "['builder_layout', 'builder_custom_fields', 'builder_stage_templates']" in form
    f = form[form.index("async _seedDefaultStagesIfEmpty"):]
    f = f[:f.index("async doUnlock")]
    assert f.index("if (this._stFlag)") < f.index("const labels = ['訂單確認'")
    assert "/stages/templates`" in f and "_stFlag: false" in form                                  # 旗標關 ⇒ 不送這個請求


def test_user_facing_copy_is_plain_language_static():
    js = _read("frontend/js/case-management-exec.js")
    assert "stSummary()" in js and "按下「建立階段」會在這個案件新增" in js and "已有的階段不會被改動" in js
    html = _page("case-management.html")
    assert 'data-testid="st-summary"' in html and "基準日（從哪一天開始算）" in html
    ed = _read("frontend/static/stage-template-editor.js")
    assert "種類鍵" not in ed[ed.index("function problems"):ed.index("function setBody")]          # 畫面上的字不用內部術語
    assert "階段代號" in ed and "要先完成：" in ed and "持續幾天" in ed
