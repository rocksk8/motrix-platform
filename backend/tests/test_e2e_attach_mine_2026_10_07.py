# -*- coding: utf-8 -*-
"""支出申請「我的申請」附件（第44班）：申請人在 草稿／待審核／已駁回 可加、可刪；核准後只剩「補發票」（沒有加入／刪除按鈕）；
HEIC 原檔可挑、可上傳（Chromium 解不開就原檔傳），檢視＝下載。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402

pytestmark = [requires_module("case", "支出申請＝M01 額外支出")]

NO = "MQ-AMN-001"
HEIC = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00" + b"0" * 64


def _db(sql, args=(), fetch=False):
    import db
    conn = db.get_db()
    try:
        cur = conn.execute(sql, args)
        conn.commit()
        return cur.fetchall() if fetch else cur.lastrowid
    finally:
        conn.close()


def _png(tmp_path, name, pad=64):
    p = tmp_path / name
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * pad)
    return str(p)


@pytest.mark.e2e
def test_mine_add_delete_by_status_and_heic(live_server, make_user, new_context, tmp_path, seed_extra_expense):
    eng = make_user(username="amn_eng", role="sales")
    eng_id = _db("SELECT id FROM users WHERE username=?", (eng[0],), fetch=True)[0]["id"]
    _db("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
        " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (NO, "已送出", "附件客戶", "機房", 100000, 95238, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00",
         "2026-01-01T00:00:00", "已成案", "", json.dumps([eng_id])))
    ids = {}
    for st in ("草稿", "待審核", "已駁回", "已核准"):
        ids[st] = seed_extra_expense(NO, total_cost=500, description="附件列-" + st, status=st)
        _db("UPDATE case_extra_expenses SET created_by=? WHERE id=?", (eng[0], ids[st]))
    page = new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, eng[0], eng[1])
    page.goto(live_server + "/pages/payment-request.html?tab=mine")
    page.wait_for_selector('#pr-mine[data-loaded="1"]')

    def cell(st):
        return page.locator('[data-attach-cell="%d"]' % ids[st])

    def files(st):
        return cell(st).locator("[data-attach-file]")

    # 核准後：沒有「加入附件」表單、沒有刪除；只剩補發票
    assert cell("已核准").locator("[data-attach-add-form]").count() == 0
    assert page.locator('[data-invoice-form="%d"]' % ids["已核准"]).count() == 1

    for st in ("草稿", "待審核", "已駁回"):
        page.locator('[data-attach-input="%d"]' % ids[st]).set_input_files(_png(tmp_path, "p_%d.png" % ids[st]))
        page.locator('[data-attach-add="%d"]' % ids[st]).click()
        page.wait_for_function("([id]) => document.querySelectorAll('[data-attach-cell=\"' + id + '\"] [data-attach-file]').length === 1", arg=[str(ids[st])])
        assert files(st).count() == 1
        assert cell(st).locator("[data-attach-del]").count() == 1
    # 刪除
    cell("草稿").locator("[data-attach-del]").click()
    page.wait_for_function("([id]) => document.querySelectorAll('[data-attach-cell=\"' + id + '\"] [data-attach-file]').length === 0", arg=[str(ids["草稿"])])
    assert json.loads(_db("SELECT files_json FROM case_extra_expenses WHERE id=?", (ids["草稿"],), fetch=True)[0]["files_json"]) == []

    # HEIC：挑得進去、上傳成功（原檔，.heic），檢視＝下載
    h = tmp_path / "IMG_0001.HEIC"
    h.write_bytes(HEIC)
    page.locator('[data-attach-input="%d"]' % ids["草稿"]).set_input_files(str(h))
    page.locator('[data-attach-add="%d"]' % ids["草稿"]).click()
    page.wait_for_function("([id]) => document.querySelectorAll('[data-attach-cell=\"' + id + '\"] [data-attach-file]').length === 1", arg=[str(ids["草稿"])])
    stored = json.loads(_db("SELECT files_json FROM case_extra_expenses WHERE id=?", (ids["草稿"],), fetch=True)[0]["files_json"])
    assert len(stored) == 1 and stored[0]["path"].lower().endswith((".heic", ".jpg"))
    with page.expect_download() as dl:
        cell("草稿").locator("[data-attach-dl]").click()
    assert dl.value.suggested_filename
    assert not errors, errors
