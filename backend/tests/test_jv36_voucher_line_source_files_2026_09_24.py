# -*- coding: utf-8 -*-
"""`JV36` · 摘要連帶來源的已上傳檔案（取代 `JV33` 的「文字接續」）。

使用者逐字更正：「我說的摘要要能帶動已上傳檔案，是別的意思……例如我的摘要是 XXX，
我點選 XXX 的時候它下方能自動連帶 XXX 內有的上傳檔案」。表單：「只顯示、勾選才帶入」。
權威原文：`SPEC-JV28-ATTACHMENT-PREVIEW.md`「JV36」節＋ A 2026-09-24 裁示。

```
面板點案件／支出項 XXX ⇒ 該行摘要覆蓋成 XXX 名稱＋記住來源（voucher_lines.source_type／source_key）
該行下方列出 XXX 的已上傳檔案：可預覽；勾選才複製成傳票附件（bringIn）；已帶入顯示「已帶入」
重開傳票 ⇒ 依已存的來源重新帶出清單
N12：選支出項時該行借貸都空白 ⇒ 金額帶入借方
預覽端點（A 准，條件）：type 只收三種；fileId 只在該來源清單裡找（跨來源 404）；
  走 resolve_picks 白名單＋abs_path；_require_voucher_access（非傳票權限 403）
```
"""
import json
import os

import pytest

VOUCHERS = "/api/vouchers"
QUOTE = "MQ-JV36-001"
_LINES = [{"account_code": "6111", "debit": 5000, "credit": 0},
          {"account_code": "1113", "debit": 0, "credit": 5000}]


def _png():
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (30, 20), (20, 120, 200)).save(buf, format="PNG")
    return buf.getvalue()


def _put_file(rel, data):
    from helpers.uploads import UPLOADS_ROOT
    full = os.path.join(UPLOADS_ROOT, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as f:
        f.write(data)


def _seed(seed_extra_expense):
    """一個案件（回簽檔 1 個）＋兩筆額外支出（各有 1 張單據）。回 `(exp1_id, exp2_id)`。"""
    import db
    _put_file("jv36/signed.png", _png())
    _put_file("jv36/exp1.png", _png())
    _put_file("jv36/exp2.png", _png())
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax,"
            " data_json, created_at, updated_at, signed_files_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (QUOTE, "已結案", "JV36客戶", "JV36案", 1000, 952, "{}",
             "2026-09-01T00:00:00", "2026-09-01T00:00:00",
             json.dumps([{"id": "sig1", "filename": "回簽.png", "path": "jv36/signed.png",
                          "mime": "image/png"}])))
        conn.commit()
    finally:
        conn.close()
    e1 = seed_extra_expense(QUOTE, total_cost=5000, category="運費", description="吊車運費",
                            expense_date="2026-09-10", doc_no="AB12345678",
                            files=[{"id": "f1", "filename": "吊車單據.png", "path": "jv36/exp1.png",
                                    "mime": "image/png"}])
    e2 = seed_extra_expense(QUOTE, total_cost=800, category="其他", description="雜支",
                            expense_date="2026-09-11",
                            files=[{"id": "f2", "filename": "雜支單據.png", "path": "jv36/exp2.png",
                                    "mime": "image/png"}])
    return e1, e2


def _hdr(client, make_user, username, modules=("cashier",), role="superadmin"):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


# ══════════════════════════════════════════════════════════════════════
# API：清單、預覽端點的範圍與權限
# ══════════════════════════════════════════════════════════════════════

def test_jv36_the_line_source_lists_only_that_sources_files(client, make_user, seed_extra_expense):
    e1, e2 = _seed(seed_extra_expense)
    hdr = _hdr(client, make_user, "jv36_list")
    r = client.get(VOUCHERS + "/line-source-files", headers=hdr,
                   params={"source_type": "extra_expense", "ref": str(e1)})
    assert r.status_code == 200, r.text[:200]
    names = [f["filename"] for f in r.json()["files"]]
    assert names == ["吊車單據.png"], "額外支出 %s 的檔案清單是 %r" % (e1, names)
    r = client.get(VOUCHERS + "/line-source-files", headers=hdr,
                   params={"source_type": "case", "ref": QUOTE})
    assert "回簽.png" in [f["filename"] for f in r.json()["files"]], r.json()


def test_jv36_the_preview_endpoint_is_scoped_and_guarded(client, make_user, seed_extra_expense):
    e1, e2 = _seed(seed_extra_expense)
    hdr = _hdr(client, make_user, "jv36_prev")
    ok = client.get(VOUCHERS + "/line-source-file", headers=hdr,
                    params={"source_type": "extra_expense", "ref": str(e1), "file_id": "f1"})
    assert ok.status_code == 200 and ok.content[:4] == b"\x89PNG", (ok.status_code, ok.content[:8])
    assert ok.headers["content-type"].startswith("application/octet-stream"), ok.headers
    # 跨來源：f2 屬於另一筆支出 ⇒ 404
    r = client.get(VOUCHERS + "/line-source-file", headers=hdr,
                   params={"source_type": "extra_expense", "ref": str(e1), "file_id": "f2"})
    assert r.status_code == 404, "跨來源撈到了別筆的檔：%s" % r.status_code
    # 不在三種之內的 type ⇒ 400（檔案層級的 type 也不行）
    for bad in ("quotation_signed", "pending_case_change", "x"):
        r = client.get(VOUCHERS + "/line-source-file", headers=hdr,
                       params={"source_type": bad, "ref": QUOTE, "file_id": "sig1"})
        assert r.status_code == 400, "type %r 沒有擋：%s" % (bad, r.status_code)
    # 非傳票權限 ⇒ 403
    other = _hdr(client, make_user, "jv36_sales", modules=("quotations",), role="admin")
    r = client.get(VOUCHERS + "/line-source-file", headers=other,
                   params={"source_type": "extra_expense", "ref": str(e1), "file_id": "f1"})
    assert r.status_code == 403, "非傳票權限讀到來源檔：%s" % r.status_code


def test_jv36_a_path_escaping_uploads_is_refused(client, make_user, seed_extra_expense):
    """⚙️ 誘餌要**真的存在**：在上傳根目錄**外面**放一個檔，路徑指過去——
    指向一個不存在的檔的話，沒有擋也會 404，這一題就證明不了任何事。"""
    from helpers.uploads import UPLOADS_ROOT
    _seed(seed_extra_expense)
    secret = os.path.join(os.path.dirname(os.path.realpath(UPLOADS_ROOT)), "jv36_secret.txt")
    with open(secret, "wb") as f:
        f.write(b"JV36-SECRET")
    evil = seed_extra_expense(QUOTE, total_cost=1, description="路徑穿越",
                              files=[{"id": "ev", "filename": "x.png", "path": "../jv36_secret.txt"}])
    hdr = _hdr(client, make_user, "jv36_trav")
    r = client.get(VOUCHERS + "/line-source-file", headers=hdr,
                   params={"source_type": "extra_expense", "ref": str(evil), "file_id": "ev"})
    assert r.status_code in (400, 404) and b"JV36-SECRET" not in r.content, (
        "路徑穿越沒有擋：%s %s" % (r.status_code, r.content[:60]))


def test_jv36_lines_remember_their_source_and_bad_sources_are_refused(client, make_user,
                                                                     seed_extra_expense):
    e1, _e2 = _seed(seed_extra_expense)
    hdr = _hdr(client, make_user, "jv36_save")
    lines = [dict(_LINES[0], summary="吊車", source_type="extra_expense", source_key=str(e1)),
             dict(_LINES[1])]
    r = client.post(VOUCHERS, headers=hdr, json={"summary": "JV36", "lines": lines})
    assert r.status_code == 200, r.text[:200]
    vid = r.json()["id"]
    got = [(l["source_type"], l["source_key"]) for l in client.get(
        "%s/%s" % (VOUCHERS, vid), headers=hdr).json()["lines"]]
    assert got == [("extra_expense", str(e1)), ("", "")], got
    # 只換來源（摘要、金額都不變）也要寫回
    lines[0]["source_type"], lines[0]["source_key"] = "case", QUOTE
    r = client.put("%s/%s" % (VOUCHERS, vid), headers=hdr, json={"lines": lines})
    assert r.status_code == 200, r.text[:200]
    got = [(l["source_type"], l["source_key"]) for l in client.get(
        "%s/%s" % (VOUCHERS, vid), headers=hdr).json()["lines"]]
    assert got[0] == ("case", QUOTE), "只改來源沒有寫回：%r" % got
    lines[0]["source_type"] = "quotation_signed"
    r = client.put("%s/%s" % (VOUCHERS, vid), headers=hdr, json={"lines": lines})
    assert r.status_code == 422 and "第 1 行" in r.json().get("detail", ""), r.text[:200]


# ══════════════════════════════════════════════════════════════════════
# 畫面
# ══════════════════════════════════════════════════════════════════════

pw = pytest.importorskip("playwright.sync_api")
from tests.test_voucher_preview_export_feedback_2026_09_23 import _login  # noqa: E402

_D = "Alpine.$data(document.querySelector('[x-data]'))"


def _open_with_case(page, live_server, token, vid):
    page.goto(f"{live_server}/pages/voucher.html?id={vid}")
    page.wait_for_function("() => %s.id == %d" % (_D, vid), timeout=15000)
    page.click('[data-testid="summary-source-tab"]:text-is("案件")')
    page.click(f'[data-testid="summary-source-item"]:has-text("{QUOTE}")')
    page.locator("textarea[x-model='l.summary']").nth(1).click()
    page.locator('[data-testid="summary-panel-expense"]').first.wait_for(state="visible", timeout=15000)


def _att_count(page):
    return page.evaluate("() => %s.attachments.length" % _D)


@pytest.mark.e2e
def test_jv36_picking_an_expense_lists_its_files_and_ticking_brings_one_in(
        live_server, client, make_user, seed_extra_expense, e2e_browser):
    e1, _e2 = _seed(seed_extra_expense)
    u, p = make_user(username="jv36_page", role="superadmin", modules=["cashier"])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    hdr = {"Authorization": "Bearer " + r.json()["token"]}
    r = client.post(VOUCHERS, headers=hdr, json={"summary": "JV36", "lines": [
        {"account_code": "1113", "debit": 0, "credit": 5000}, {"account_code": "6111"}]})
    vid = r.json()["id"]
    browser = e2e_browser
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    token = _login(page, live_server, u, p)["token"]   # PERF #5：注入登入後頁面停在空白頁，token 取回傳值
    _open_with_case(page, live_server, token, vid)
    page.locator("textarea[x-model='l.summary']").nth(1).fill("原本的摘要")
    page.click('[data-testid="summary-panel-expense"]:has-text("吊車運費")')
    line = page.evaluate("() => %s.lines[1]" % _D)
    files = page.locator('[data-testid="line-source-files"]').first
    files.locator('[data-testid="line-source-file-open"]:has-text("吊車單據.png")').wait_for(
        state="visible", timeout=10000)
    before = _att_count(page)
    print("JV36 頁面實測：選支出項 ⇒ 摘要 %r、來源 %r/%r、借方 %r；清單出現、附件數 %d"
          % (line["summary"], line["source_type"], line["source_key"], line["debit"], before))
    assert line["summary"].startswith("吊車運費") and "原本的摘要" not in line["summary"], (
        "摘要應該被覆蓋成支出項名稱（不再接續）：%r" % line["summary"])
    assert (line["source_type"], line["source_key"]) == ("extra_expense", str(e1)), line
    assert line["debit"] == "5000", "N12：借貸空白的行，金額應該帶入借方：%r" % line["debit"]
    assert before == 0, "只列出、沒勾選，附件數就變了：%d" % before

    files.locator('[data-testid="line-source-file-open"]:has-text("吊車單據.png")').click()
    page.wait_for_selector('[data-testid="voucher-att-preview-img"]', state="visible", timeout=10000)
    page.click('[data-testid="voucher-att-close"]')

    files.locator('[data-testid="line-source-file-check"]').first.check()
    page.wait_for_function("() => %s.attachments.length === 1" % _D, timeout=10000)
    assert files.locator('[data-testid="line-source-file-brought"]:visible').count() == 1

    page.click('[data-testid="voucher-save"]')
    page.wait_for_function("() => !%s.busy" % _D, timeout=10000)
    page.reload()
    page.wait_for_function("() => %s.id == %d" % (_D, vid), timeout=15000)
    again = page.locator('[data-testid="line-source-files"] [data-testid="line-source-file-open"]')
    again.first.wait_for(state="visible", timeout=10000)
    print("JV36 頁面實測：存檔重開 ⇒ 清單 %r、附件數 %d" % (again.all_inner_texts(), _att_count(page)))
    assert again.all_inner_texts() == ["吊車單據.png"]
    assert _att_count(page) == 1


@pytest.mark.e2e
def test_jv36_picking_a_case_lists_the_case_files_and_keeps_existing_amounts(
        live_server, client, make_user, seed_extra_expense, e2e_browser):
    _seed(seed_extra_expense)
    u, p = make_user(username="jv36_case", role="superadmin", modules=["cashier"])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    hdr = {"Authorization": "Bearer " + r.json()["token"]}
    r = client.post(VOUCHERS, headers=hdr, json={"summary": "JV36", "lines": _LINES})
    vid = r.json()["id"]
    browser = e2e_browser
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    token = _login(page, live_server, u, p)["token"]   # PERF #5：注入登入後頁面停在空白頁，token 取回傳值
    _open_with_case(page, live_server, token, vid)
    page.click('[data-testid="summary-panel-expense"]:has-text("雜支")')
    line = page.evaluate("() => %s.lines[1]" % _D)
    assert line["credit"] == "5000" and not line["debit"], (
        "N12：這一行已有金額，不可以再帶入：%r" % line)
    page.click('[data-testid="summary-panel-case"]:has-text("%s")' % QUOTE)
    line = page.evaluate("() => %s.lines[1]" % _D)
    assert (line["source_type"], line["source_key"]) == ("case", QUOTE), line
    page.locator('[data-testid="line-source-file-open"]:has-text("回簽.png")').wait_for(
        state="visible", timeout=10000)
