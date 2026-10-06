# -*- coding: utf-8 -*-
"""第 44 班：採購單「從請購單帶入」e2e（payment-request.html ＋ 後端）。

管理員在案件下開採購單：挑選器只列同案件已核准的請購單 ⇒ 多張請購單各勾一項、各帶部分數量 ⇒ 與手填列混在同一張單 ⇒ 改單價出現價差提示
⇒ 送審後資料庫的 prDocCode／prLine／prQty／data.fromPr 都對；再開一張採購單，挑選器的「已採購／剩餘」已扣掉第一張的認領量。
觀測點＝畫面（DOM）＋資料庫（case_extra_expenses）。⚙️ 突變：拿掉前端的剩餘量上限 ⇒ 超量帶入沒有被擋 ⇒ 紅。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402
from tests.test_e2e_expense_form_a24_2026_10_01 import _fill, _join_dept, _q, _seed, _wait_done, _x  # noqa: E402

pytestmark = [requires_module("case", "請款＝M01 額外支出"), requires_module("accounting", "費用類別下拉（W4 G2）")]

NO = "MQ-T44PO-001"


def _pr_row(adm, code, lines):
    _x("INSERT INTO case_extra_expenses (quote_no, kind, doc_code, category, description, qty, unit, unit_cost, total_cost, status, created_by,"
       " created_by_name, created_at, updated_at, lines_json, data_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
       (NO, "purchase_req", code, "雜項", "請購" + code, 1, "", 0, 0, "已核准", adm, adm, "2026-10-01T00:00:00", "2026-10-01T00:00:00",
        json.dumps(lines, ensure_ascii=False), "{}"))


def _open_po(page, live_server, adm):
    inject_login(page, live_server, adm[0], adm[1])
    page.goto(live_server + "/pages/payment-request.html")
    page.wait_for_selector("#pr-type-card", state="visible", timeout=15000)
    page.fill("#pr-case-q", "MQ-T44PO")
    page.click('[data-case-pick="%s"]' % NO)
    page.select_option("#pr-type", "purchase_order")
    page.wait_for_selector("#pr-pr-picker", state="visible", timeout=15000)


@pytest.mark.e2e
def test_po_mixes_lines_from_two_prs_with_partial_qty_and_flags_price_changes(live_server, make_user, new_context):
    _seed()
    adm = make_user(username="t44po_adm", role="superadmin")      # 財務金額可視＝財務角色或最高管理者；admin 不複製單價
    _join_dept(adm[0], make_user(username="t44po_mgr", role="admin")[0])
    _x("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag,"
       " sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (NO, "已送出", "T44客戶", "機房", 100000, 95238, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "", "[]"))
    _pr_row(adm[0], "PR-T44-A", [{"category": "OFFICE", "summary": "線材", "qty": 10, "unitCost": 100}, {"category": "OFFICE", "summary": "插座", "qty": 5, "unitCost": 200}])
    _pr_row(adm[0], "PR-T44-B", [{"category": "OFFICE", "summary": "螺絲", "qty": 4, "unitCost": 50}])
    page = new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    _open_po(page, live_server, adm)
    assert page.locator('[data-pr-doc="PR-T44-A"]').count() == 1 and page.locator('[data-pr-doc="PR-T44-B"]').count() == 1
    _fill(page)                                                              # 一列手填（沒連請購單）

    # 超量帶入被擋：A 第 1 項只剩 10
    page.check('[data-pr-line="PR-T44-A#1"] input[type=checkbox]')
    page.fill('[data-testid="pr-pr-qty-PR-T44-A-1"]', "11")
    page.click("#pr-pr-add")
    assert "最多還能帶入" in page.locator("[data-testid=pr-pr-err]").text_content()

    # 各帶一部分：A#1 帶 6、B#1 帶 4（全量）
    page.fill('[data-testid="pr-pr-qty-PR-T44-A-1"]', "6")
    page.check('[data-pr-line="PR-T44-B#1"] input[type=checkbox]')
    page.click("#pr-pr-add")
    assert page.locator("[data-testid=pr-pr-err]").text_content().strip() == ""
    rows = page.locator('#pr-df [data-table="lines"] tbody tr')
    assert rows.count() == 3                                                 # 手填 1 ＋ 請購單 2
    assert not page.locator("#pr-pr-diff").is_visible()                      # 價格照抄 ⇒ 無價差提示

    # 改 A#1 的單價 ⇒ 出現價差提示
    rows.nth(1).locator('td[data-col="unitCost"] input').fill("120")
    page.wait_for_selector("#pr-pr-diff", state="visible", timeout=5000)
    assert "PR-T44-A" in page.locator("#pr-pr-diff").text_content()

    page.click("#pr-t-submit")
    _wait_done(page)
    po = _q("SELECT * FROM case_extra_expenses WHERE kind='purchase_order' AND quote_no=? ORDER BY id DESC LIMIT 1", (NO,))[0]
    assert po["status"] != "草稿"
    lines = json.loads(po["lines_json"])
    linked = {(l["prDocCode"], l["prLine"]): l for l in lines if l.get("prDocCode")}
    assert set(linked) == {("PR-T44-A", 1), ("PR-T44-B", 1)}
    assert linked[("PR-T44-A", 1)]["qty"] == 6 and linked[("PR-T44-A", 1)]["prQty"] == 10 and float(linked[("PR-T44-A", 1)]["unitCost"]) == 120
    assert linked[("PR-T44-B", 1)]["qty"] == 4 and float(linked[("PR-T44-B", 1)]["unitCost"]) == 50      # 價格複製
    assert sorted(json.loads(po["data_json"])["fromPr"]) == ["PR-T44-A", "PR-T44-B"]
    assert sum(1 for l in lines if not l.get("prDocCode")) == 1

    # 再開一張：挑選器已扣掉第一張的認領量（A#1 剩 4、B#1 剩 0 且不可勾）
    page2 = new_context().new_page()
    _open_po(page2, live_server, adm)
    a1 = page2.locator('[data-pr-line="PR-T44-A#1"] td')
    assert [a1.nth(i).text_content().strip() for i in (2, 3, 4)] == ["10", "6", "4"]
    assert page2.locator('[data-pr-line="PR-T44-B#1"] input[type=checkbox]').is_disabled()
    assert not errors, errors
