# -*- coding: utf-8 -*-
"""支出申請「新增申請」的附件挑選器（第44班）：每次挑的檔「累加」而不是整批取代、可移除、超過 10 個前端先擋；
附件被伺服器擋下（格式／檔頭不符）時草稿已建好，修正後重按沿用同一張草稿——不會多建一份。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402

pytestmark = [requires_module("case", "支出申請＝M01 額外支出")]

NO = "MQ-APK-001"


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _x(sql, args=()):
    import db
    conn = db.get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _png(tmp_path, name, pad=64):
    p = tmp_path / name
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * pad)
    return str(p)


def _items(page, kind="other"):
    return page.locator('[data-attach="%s"] [data-attach-item]' % kind)


@pytest.mark.e2e
@pytest.mark.upload_magic          # 要驗伺服器真的擋假 PDF（conftest 預設把檔頭判定換成一律符合）
def test_picker_accumulates_removes_caps_and_retries_on_the_same_draft(live_server, make_user, new_context, tmp_path):
    eng = make_user(username="apk_eng", role="sales")
    eng_id = _q("SELECT id FROM users WHERE username=?", (eng[0],))[0]["id"]
    _x("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (NO, "已送出", "挑檔客戶", "機房", 100000, 95238, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00",
        "2026-01-01T00:00:00", "已成案", "", json.dumps([eng_id])))
    page = new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, eng[0], eng[1])
    page.goto(live_server + "/pages/payment-request.html")
    page.fill("#pr-case-q", "MQ-APK")
    page.click('[data-case-pick="%s"]' % NO)
    page.wait_for_selector("#pr-form", state="visible")
    page.wait_for_function("() => document.querySelectorAll('#pr-category option').length > 1")
    page.fill("#pr-date", "2031-08-01")
    page.fill("#pr-amount", "1200")
    page.fill("#pr-desc", "挑檔測試")

    # ① 累加：分兩次挑，兩個都在（原本第二次會取代第一次）
    a, b = _png(tmp_path, "a.png"), _png(tmp_path, "b.png")
    page.set_input_files("#pr-files", a)
    assert _items(page).count() == 1
    page.set_input_files("#pr-files", b)
    assert _items(page).count() == 2, "第二次挑檔要累加，不是取代"
    # ② 同一個檔重複挑 ⇒ 不重複加；不合規格的檔 ⇒ 前端擋下並說明
    page.set_input_files("#pr-files", b)
    assert _items(page).count() == 2
    exe = tmp_path / "evil.exe"
    exe.write_bytes(b"MZ" + b"0" * 30)
    page.set_input_files("#pr-files", str(exe))
    assert _items(page).count() == 2
    assert "格式不支援" in page.locator('[data-attach="other"] .pr-err').inner_text()
    # ③ 移除
    page.locator('[data-attach="other"] [data-attach-item="a.png"] button').click()
    assert _items(page).count() == 1
    page.set_input_files("#pr-files", a)
    assert _items(page).count() == 2
    # ④ 超過 10 個（附件＋發票合計）前端先擋
    many = [_png(tmp_path, "m%02d.png" % i, pad=64 + i) for i in range(10)]
    page.set_input_files("#pr-files", many)
    assert _items(page).count() == 10, "合計最多 10 個"
    assert "最多 10 個" in page.locator('[data-attach="other"] .pr-err').inner_text()
    for i in range(8):                                            # 清回 2 個（a、b）以便下面的重試題
        page.locator('[data-attach="other"] [data-attach-item^="m"] button').first.click()
    assert _items(page).count() == 2

    # ⑤ 伺服器擋下（假 PDF：副檔名對、檔頭不對）⇒ 草稿已建好；移除壞檔後重按 ⇒ 沿用同一張，只有一份
    bad = tmp_path / "fake.pdf"
    bad.write_text("this is not a pdf")
    page.set_input_files("#pr-files", str(bad))
    assert _items(page).count() == 3
    page.click("#pr-save-draft")
    page.wait_for_function("() => document.getElementById('pr-error') && document.getElementById('pr-error').offsetParent !== null", timeout=15000)
    msg = page.locator("#pr-error").inner_text()
    assert "已建立" in msg and "不會重複建立" in msg, msg
    rows = _q("SELECT id, files_json FROM case_extra_expenses WHERE quote_no=?", (NO,))
    assert len(rows) == 1 and json.loads(rows[0]["files_json"]) == [], "整批被擋：草稿在、檔案一個都沒存（沒有孤兒檔）"
    assert _items(page).count() == 3, "挑選器保留，使用者只要移除壞檔"
    page.wait_for_function("() => document.getElementById('pr-new').dataset.busy === '0'")
    page.locator('[data-attach="other"] [data-attach-item="fake.pdf"] button').click()
    page.click("#pr-save-draft")
    page.wait_for_selector('#pr-result[data-status="草稿"]', timeout=15000)
    rows = _q("SELECT id, files_json FROM case_extra_expenses WHERE quote_no=?", (NO,))
    assert len(rows) == 1, "重按沿用同一張草稿，不會多建一份"
    assert sorted(f["filename"] for f in json.loads(rows[0]["files_json"])) == ["a.png", "b.png"]
    assert _items(page).count() == 0, "送出成功後挑選器清空"
    assert not errors, errors
