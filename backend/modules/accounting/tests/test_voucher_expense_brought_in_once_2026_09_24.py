# -*- coding: utf-8 -*-
"""同一筆支出只能帶入一張（未作廢的）傳票。

使用者裁示（2026-09-24，KNOWN-GAPS ②）：「擋下，除非前一張已作廢」；前後端都擋、以後端為準，
訊息寫出前一張傳票號。在此之前系統**不擋**，唯一的防線是附件那一側的紅字標記（JV18）。

## 判定＝紅字標記同一套規則（抽成共用 helper，hichan-0a 核准）
```
作廢的傳票不算       作廢重開是合法流程（新單會複製分錄的來源）
空的來源鍵不算       沒有來源的分錄彼此不可以被判成「重複」
```
範圍：分錄來源為**額外支出**、**承攬商派工**（案件 `case` 本來就可以被很多張傳票引用）。

## 已知限制（照實寫）
JV36 之前的分錄沒有記來源（`source_key` 空）⇒ **偵測不到**，不回填。
"""
import json

import pytest

from modules.accounting.tests.test_jv36_voucher_line_source_files_2026_09_24 import (  # noqa: F401
    _seed, _hdr, _LINES, VOUCHERS, QUOTE)


def _lines(source_type, key):
    return [dict(_LINES[0], summary="支出", source_type=source_type, source_key=str(key)),
            dict(_LINES[1])]


def _create(client, hdr, lines):
    return client.post(VOUCHERS, headers=hdr, json={"summary": "JV21", "lines": lines})


def _voucher_no(client, hdr, vid):
    return client.get("%s/%s" % (VOUCHERS, vid), headers=hdr).json()["voucher_no"]


def test_the_same_expense_cannot_go_into_a_second_voucher(client, make_user, seed_extra_expense):
    e1, _e2 = _seed(seed_extra_expense)
    hdr = _hdr(client, make_user, "jv21_a")
    r = _create(client, hdr, _lines("extra_expense", e1))
    assert r.status_code == 200, r.text[:200]
    first_no = _voucher_no(client, hdr, r.json()["id"])
    r = _create(client, hdr, _lines("extra_expense", e1))
    assert r.status_code == 409, r.text[:200]
    assert first_no in r.json()["detail"], "訊息要寫出前一張傳票號"


def test_after_the_first_voucher_is_voided_the_expense_can_be_brought_in_again(
        client, make_user, seed_extra_expense):
    e1, _e2 = _seed(seed_extra_expense)
    hdr = _hdr(client, make_user, "jv21_b")
    vid = _create(client, hdr, _lines("extra_expense", e1)).json()["id"]
    r = client.post("%s/%s/void" % (VOUCHERS, vid), headers=hdr, json={"reason": "開錯"})
    assert r.status_code == 200, r.text[:200]
    r = _create(client, hdr, _lines("extra_expense", e1))
    assert r.status_code == 200, r.text[:200]


def test_the_same_expense_twice_in_one_voucher_is_refused(client, make_user, seed_extra_expense):
    e1, _e2 = _seed(seed_extra_expense)
    hdr = _hdr(client, make_user, "jv21_c")
    lines = [dict(_LINES[0], summary="一", source_type="extra_expense", source_key=str(e1)),
             dict(_LINES[0], summary="二", source_type="extra_expense", source_key=str(e1)),
             dict(_LINES[1], credit=10000)]
    r = _create(client, hdr, lines)
    assert r.status_code == 409, r.text[:200]


def test_editing_lines_is_checked_too_but_a_voucher_does_not_clash_with_itself(
        client, make_user, seed_extra_expense):
    e1, e2 = _seed(seed_extra_expense)
    hdr = _hdr(client, make_user, "jv21_d")
    a = _create(client, hdr, _lines("extra_expense", e1)).json()["id"]
    b = _create(client, hdr, _lines("extra_expense", e2)).json()["id"]
    # 自己再存一次（來源不變）⇒ 不擋
    r = client.put("%s/%s" % (VOUCHERS, a), headers=hdr, json={"lines": _lines("extra_expense", e1)})
    assert r.status_code == 200, r.text[:200]
    # 把 B 改成帶入 A 已帶入的那一筆 ⇒ 擋
    r = client.put("%s/%s" % (VOUCHERS, b), headers=hdr, json={"lines": _lines("extra_expense", e1)})
    assert r.status_code == 409, r.text[:200]


def test_a_case_source_is_not_limited_to_one_voucher(client, make_user, seed_extra_expense):
    """案件本身（`case`）不是支出項，本來就可以被多張傳票引用。"""
    _seed(seed_extra_expense)
    hdr = _hdr(client, make_user, "jv21_e")
    assert _create(client, hdr, _lines("case", QUOTE)).status_code == 200
    assert _create(client, hdr, _lines("case", QUOTE)).status_code == 200


def test_lines_without_a_source_never_clash(client, make_user, seed_extra_expense):
    _seed(seed_extra_expense)
    hdr = _hdr(client, make_user, "jv21_f")
    assert _create(client, hdr, [dict(l) for l in _LINES]).status_code == 200
    assert _create(client, hdr, [dict(l) for l in _LINES]).status_code == 200


def test_expense_sources_say_which_voucher_already_took_them(client, make_user, seed_extra_expense):
    """前端標紅字要的資料：支出項頁籤的每一筆帶出 `usedBy`（前一張傳票號）。"""
    e1, e2 = _seed(seed_extra_expense)
    hdr = _hdr(client, make_user, "jv21_g")
    vid = _create(client, hdr, _lines("extra_expense", e1)).json()["id"]
    no = _voucher_no(client, hdr, vid)
    r = client.get("%s/summary-sources?quote_no=%s" % (VOUCHERS, QUOTE), headers=hdr)
    assert r.status_code == 200, r.text[:200]
    from modules.accounting.api.vouchers import SUMMARY_TABS
    exp = {(x["kind"], str(x["id"])): x for x in r.json()["tabs"][SUMMARY_TABS[2]]}
    assert [u["voucherNo"] for u in exp[("extra_expense", str(e1))]["usedBy"]] == [no]
    assert exp[("extra_expense", str(e2))]["usedBy"] == []


# ── 附件那一側（紅字標記）行為不變：改呼叫共用 helper 前後輸出相同 ─────────────

def test_attachment_red_mark_output_is_unchanged(client):
    """`_used_map` 的輸出形狀與規則（作廢不算、軟刪不算、三欄空字串不算）照舊。"""
    import db
    from modules.accounting.voucher_attachments import _used_map
    conn = db.get_db()
    try:
        def v(no, voided=""):
            cur = conn.execute(
                "INSERT INTO vouchers_all (voucher_no, voucher_date, created_by, created_at, updated_at,"
                " voided_at) VALUES (?,?,?,?,?,?)", (no, "2026-09-24", "x", "t", "t", voided))
            return cur.lastrowid

        def att(vid, st, dn, fid, at, deleted=""):
            conn.execute(
                "INSERT INTO voucher_attachments (voucher_id, file_id, filename, path, source_type,"
                " source_doc_no, source_file_id, uploaded_by, uploaded_at, deleted_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (vid, "%s-%s-%s" % (vid, fid, at), "f", "p", st, dn, fid, "x", at, deleted))
        a, b, c = v("V-A"), v("V-B"), v("V-C", voided="2026-09-24T10:00:00")
        att(a, "extra_expense", "5", "f1", "2026-09-24T09:00:00")
        att(b, "extra_expense", "5", "f1", "2026-09-24T11:00:00")
        att(c, "extra_expense", "5", "f1", "2026-09-24T12:00:00")          # 作廢 ⇒ 不算
        att(a, "extra_expense", "6", "f2", "2026-09-24T09:00:00", deleted="t")  # 軟刪 ⇒ 不算
        att(a, "", "", "", "2026-09-24T09:00:00")                         # 直接上傳 ⇒ 不算
        conn.commit()
        got = _used_map(conn)
    finally:
        conn.close()
    assert got == {("extra_expense", "5", "f1"): [
        {"voucherNo": "V-B", "voucherId": b, "usedAt": "2026-09-24T11:00:00"},
        {"voucherNo": "V-A", "voucherId": a, "usedAt": "2026-09-24T09:00:00"},
    ]}


# ══════════════════════════════════════════════════════════════════════
# 畫面：帶入面板標紅字＋前一張傳票號；點了會被擋並說明
# ══════════════════════════════════════════════════════════════════════

pw = pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login as _login  # noqa: E402,F401
from modules.accounting.tests.test_jv36_voucher_line_source_files_2026_09_24 import _open_with_case, _D  # noqa: E402


@pytest.mark.e2e
def test_the_panel_marks_a_taken_expense_and_refuses_to_bring_it_in(
        live_server, client, make_user, seed_extra_expense, e2e_browser):
    e1, _e2 = _seed(seed_extra_expense)
    u, p = make_user(username="jv21_page", role="superadmin", modules=["cashier"])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    hdr = {"Authorization": "Bearer " + r.json()["token"]}
    first = _create(client, hdr, _lines("extra_expense", e1)).json()
    r = client.post(VOUCHERS, headers=hdr, json={"summary": "第二張", "lines": [
        {"account_code": "1113", "debit": 0, "credit": 5000}, {"account_code": "6111"}]})
    vid = r.json()["id"]
    browser = e2e_browser
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    token = _login(page, live_server, u, p)["token"]   # PERF #5：注入登入後頁面停在空白頁，token 取回傳值
    _open_with_case(page, live_server, token, vid)
    item = page.locator('[data-testid="summary-panel-expense"]:has-text("吊車運費")').first
    mark = item.locator('[data-testid="expense-used"]')
    mark.wait_for(state="visible", timeout=10000)
    assert first["voucher_no"] in mark.inner_text()
    item.click()
    msg = page.locator('[data-testid="summary-panel-msg"]')
    msg.wait_for(state="visible", timeout=5000)
    assert first["voucher_no"] in msg.inner_text()
    line = page.evaluate("() => %s.lines[1]" % _D)
    assert (line.get("source_type") or "") == "", "被擋下來的支出不可以寫進分錄：%r" % line
