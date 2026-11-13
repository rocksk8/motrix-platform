# -*- coding: utf-8 -*-
"""瀏覽器層級：一條龍 P4b（旗標 onepipe.entry_unify）——「登載」統一入口、階段出勤預填、完工單施工紀錄預填。

旗標關：案件頁沒有「登載」、完工單不預填、出勤送空白列、`?case_no=` 不生效（與今天相同）；
旗標開：「登載」出現（每顆只在這個人真的能做時才出現）、點「每日工作事項」帶好案件、完工單的開工日與施工說明依案件紀錄預填並提示、出勤預填今天與人次。
"""
import datetime
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01（案件）的案件管理頁、完工單頁")

NO = "MQ-P4BE2E-001"
ROOT = "document.querySelector('[x-data]')"


def _flag(on):
    import db
    from helpers import settings_groups, settings_registry as SR       # noqa: F401
    c = db.get_db()
    try:
        SR.publish("onepipe", {"entry_unify": 1 if on else 0}, reason="e2e", user="p4be2e", conn=c)
        c.commit()
    finally:
        c.close()


def _case(assigned=(), visits=(), logs=()):
    import db
    c = db.get_db()
    try:
        ids = [c.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()[0] for u in assigned]
        c.execute("INSERT OR REPLACE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, assigned_user_ids) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (NO, "已送出", "登載客戶", "登載工程", 1000, 952, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", json.dumps(ids)))
        c.execute("DELETE FROM case_stage_visits WHERE stage_id IN (SELECT id FROM case_stages WHERE quote_no=?)", (NO,))
        c.execute("DELETE FROM case_stages WHERE quote_no=?", (NO,))
        c.execute("DELETE FROM work_logs WHERE case_no=?", (NO,))
        sid = c.execute("INSERT INTO case_stages (quote_no, label, sort_order, created_at, updated_at) VALUES (?,?,?,?,?)",
                        (NO, "施工", 1, "2026-01-01T00:00:00", "2026-01-01T00:00:00")).lastrowid
        for d, n in visits:
            c.execute("INSERT INTO case_stage_visits (stage_id, visit_date, visit_people, note, created_at) VALUES (?,?,?,?,?)", (sid, d, n, "", "2026-01-01T00:00:00"))
        uid = c.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
        for d, t in logs:
            c.execute("INSERT INTO work_logs (log_date, user_id, content, hours, created_at, created_by, case_no) VALUES (?,?,?,?,?,?,?)",
                      (d, uid, t, 8, "2026-01-01T00:00:00", uid, NO))
        c.commit()
    finally:
        c.close()


def _case_page(page, live_server):
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.wait_for_selector(f"text={NO}", timeout=15000)
    page.locator(f"text={NO}").first.click()


@pytest.mark.e2e
def test_visit_prefill_is_today_and_last_head_count_only_when_flag_on(live_server, make_user, e2e_browser):
    u, p = make_user(username="p4be_visit", role="superadmin")
    _case()
    _flag(True)
    page = e2e_browser.new_page(viewport={"width": 1440, "height": 900})
    inject_login(page, live_server, u, p)
    _case_page(page, live_server)
    page.wait_for_function(f"() => Alpine.$data({ROOT}).onepipe.entryUnify === true", timeout=15000)   # 旗標已讀到
    today = datetime.date.today().isoformat()
    got = page.evaluate(f"() => {{ const d = Alpine.$data({ROOT}); return [d._visitPrefill({{visits: []}}), d._visitPrefill({{visits: [{{visitPeople: 0}}, {{visitPeople: 4}}]}})] }}")
    assert got[0] == {"visitDate": today, "visitPeople": 1}
    assert got[1] == {"visitDate": today, "visitPeople": 4}, "沿用這個階段最近一筆的人次（略過 0）"
    page.evaluate(f"() => {{ Alpine.$data({ROOT}).onepipe.entryUnify = false }}")
    assert page.evaluate(f"() => Alpine.$data({ROOT})._visitPrefill({{visits: []}})") == {}, "旗標關＝送空白列"
