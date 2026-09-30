# -*- coding: utf-8 -*-
"""瀏覽器端對端：總帳 P1 兩個頁面（會計期間與結帳、帳簿報表）真的載得起來、按得動。

觀測點沿用 test_e2e_account_tree 的三格：①網路層無 4xx/5xx ②無 pageerror ③畫面真的有內容；
再加「動作的終點狀態」——按下結帳後驗 DOM 的狀態徽章與資料庫，不驗 Alpine 模型、不等某一趟請求。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

import db  # noqa: E402


def _open(page, base, user, pw, path):
    bad, errs = [], []
    page.on("response", lambda r: bad.append((r.status, r.url)) if r.status >= 400 else None)
    page.on("pageerror", lambda e: errs.append(str(e)))
    inject_login(page, base, user, pw)
    bad.clear()
    page.goto("%s/pages/%s" % (base, path))
    return bad, errs


def _seed(date, lines, status="已過帳"):
    conn = db.get_db()
    try:
        n = conn.execute("SELECT COUNT(*) FROM vouchers_all").fetchone()[0] + 700
        cur = conn.execute(
            "INSERT INTO vouchers_all(voucher_no, voucher_date, category, summary, status, created_by, created_at, updated_at)"
            " VALUES (?,?, '轉', 'e2e', ?, 't','n','n')", ("%s-%d" % (date.replace("-", ""), n), date, "已核准" if status == "已過帳" else status))
        vid = cur.lastrowid
        for i, (code, d, c) in enumerate(lines, 1):
            conn.execute("INSERT INTO voucher_lines(voucher_id,line_no,account_code,debit,credit) VALUES (?,?,?,?,?)", (vid, i, code, d, c))
        if status == "已過帳":
            conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (vid,))
        conn.commit()
        return conn.execute("SELECT voucher_no FROM vouchers_all WHERE id=?", (vid,)).fetchone()[0]
    finally:
        conn.close()


@pytest.mark.e2e
def test_periods_page_create_year_close_and_reopen_needs_reason(live_server, make_user, e2e_browser):
    user, pw = make_user(username="e2e_gl_periods", role="superadmin")
    page = e2e_browser.new_page()
    bad, errs = _open(page, live_server, user, pw, "ledger-periods.html")
    page.wait_for_selector("[data-testid=lp-new-year]")

    page.fill("[data-testid=lp-new-year]", "2161")
    page.click("[data-testid=lp-create-year]")
    page.wait_for_selector("[data-testid=lp-period-2161-12]")                    # 12 個期間都畫出來
    assert page.locator("[data-testid^=lp-period-2161-]").count() == 12
    assert "已建立" in page.locator("[data-testid=lp-notice]").inner_text()

    conn = db.get_db()
    try:
        pid = conn.execute("SELECT id FROM gl_periods WHERE year=2161 AND period_no=3").fetchone()[0]
    finally:
        conn.close()
    row = page.locator("[data-testid=lp-period-2161-3]")
    row.locator("[data-testid=lp-close]").click()
    page.wait_for_selector("[data-testid=lp-dialog]", state="visible")
    assert "更早的期間" in page.locator("[data-testid=lp-dialog]").inner_text()   # 前面兩期還沒結：要明說，並要求確認
    page.click("[data-testid=lp-submit]")                                         # 沒確認就送出 ⇒ 被擋
    page.wait_for_selector("[data-testid=lp-dlg-error]", state="visible")
    page.check("[data-testid=lp-accept]")
    page.click("[data-testid=lp-submit]")
    page.wait_for_function("() => [...document.querySelectorAll('[data-testid=lp-period-2161-3] .lp-tag')].some(e => e.textContent.trim() === '已結帳')")

    conn = db.get_db()
    try:
        assert conn.execute("SELECT status FROM gl_periods WHERE year=2161 AND period_no=3").fetchone()[0] == "closed"
    finally:
        conn.close()

    row.locator("[data-testid=lp-reopen]").click()
    page.click("[data-testid=lp-submit]")                                         # 不填理由
    page.wait_for_selector("[data-testid=lp-dlg-error]", state="visible")
    assert "理由" in page.locator("[data-testid=lp-dlg-error]").inner_text()
    page.fill("[data-testid=lp-reason]", "補一張漏的傳票")
    page.click("[data-testid=lp-submit]")
    page.wait_for_function("() => [...document.querySelectorAll('[data-testid=lp-period-2161-3] .lp-tag')].some(e => e.textContent.trim() === '開放')")

    # 唯一允許的失敗請求＝本題刻意觸發的兩次 400（沒確認提醒就結帳、重開沒填理由）；其餘任何 4xx/5xx 都是頁面壞了
    assert sorted(u.split("/api/ledger/")[1] for s, u in bad if s == 400) == ["periods/%d/close" % pid, "periods/%d/reopen" % pid], bad
    assert not [b for b in bad if b[0] != 400], "開期間頁時有非預期的請求失敗：%s" % bad[:4]
    assert not errs, "頁面丟了例外：%s" % errs[:3]


@pytest.mark.e2e
def test_periods_page_opening_preview_shows_imbalance(live_server, make_user, e2e_browser):
    user, pw = make_user(username="e2e_gl_open", role="superadmin")
    page = e2e_browser.new_page()
    bad, errs = _open(page, live_server, user, pw, "ledger-periods.html")
    page.wait_for_selector("[data-testid=lp-op-text]")
    page.fill("[data-testid=lp-op-text]", "科目,借方,貸方\n1113,\"5,000\",\n3111,,4000")
    page.click("[data-testid=lp-op-preview]")
    page.wait_for_selector("[data-testid=lp-op-diff]", state="visible")
    assert "1,000" in page.locator("[data-testid=lp-op-diff]").inner_text()      # 差額被指出，不是靜默通過
    page.fill("[data-testid=lp-op-text]", "1113,5000,\n3111,,5000")
    page.click("[data-testid=lp-op-preview]")
    page.wait_for_function("() => !document.querySelector('[data-testid=lp-op-diff]') || document.querySelector('[data-testid=lp-op-diff]').offsetParent === null")
    assert not bad and not errs, (bad[:3], errs[:3])


@pytest.mark.e2e
def test_reports_page_trial_balance_drill_down_and_unbalanced_banner(live_server, make_user, e2e_browser):
    user, pw = make_user(username="e2e_gl_rep", role="superadmin")
    no = _seed("2162-04-10", [("1113", 1234, 0), ("4111", 0, 1234)])
    page = e2e_browser.new_page()
    bad, errs = _open(page, live_server, user, pw, "ledger-reports.html")
    page.wait_for_selector("[data-testid=lr-start]")
    page.wait_for_selector("[data-testid=lr-tb-table]")            # 先等頁面初次自動載入完成，再輸入條件（否則初次載入會拿到輸入到一半的日期）
    page.fill("[data-testid=lr-start]", "2162-04-01")
    page.fill("[data-testid=lr-end]", "2162-04-30")
    page.click("[data-testid=lr-run]")
    # 等終點狀態（新條件的數字出現）；頁面初次載入的空試算表也有這張 table，不能只等它存在
    page.wait_for_function("() => { const t = document.querySelector('[data-testid=lr-tb-table]'); return t && t.innerText.includes('1,234') }")
    tb = page.locator("[data-testid=lr-tb-table]").inner_text()
    assert "銀行存款" in tb and "1,234" in tb                                     # 正對照：已知傳票在試算表出現
    assert not page.locator("[data-testid=lr-unbalanced]").is_visible()

    page.locator("[data-testid=lr-tb-table] tr", has_text="銀行存款").first.click()   # 逐層點入總分類帳
    page.wait_for_selector("[data-testid=lr-gl-table]")
    assert no in page.locator("[data-testid=lr-gl-table]").inner_text()

    # 反向控制：壞帳（不平衡）必須顯示紅色警告，不可被吸收
    _seed("2162-05-10", [("1113", 500, 0), ("4111", 0, 400)])
    page.click("[data-testid=lr-tab-tb]")
    page.fill("[data-testid=lr-start]", "2162-05-01")
    page.fill("[data-testid=lr-end]", "2162-05-31")
    page.click("[data-testid=lr-run]")
    page.wait_for_selector("[data-testid=lr-unbalanced]", state="visible")

    # 含未過帳：勾選後出現預覽警語
    page.check("[data-testid=lr-drafts]")
    page.wait_for_selector("[data-testid=lr-drafts-warn]", state="visible")
    assert not bad, "開帳簿報表頁時有請求失敗：%s" % bad[:4]
    assert not errs, "頁面丟了例外：%s" % errs[:3]


@pytest.mark.e2e
def test_reports_page_requires_the_ledger_modules(live_server, make_user, e2e_browser):
    user, pw = make_user(username="e2e_gl_none", role="staff", modules=[])
    page = e2e_browser.new_page()
    _open(page, live_server, user, pw, "ledger-reports.html")
    # 2026-09-30：頁面補載 sidebar.js（原本漏載 ⇒ 沒有頂列／logo）後，沒權限改由平台共用的頁面守門
    # 顯示「你沒有這個頁面的權限」（#no-module-notice，與其他模組頁一致），不再是頁內的 lr-error。
    page.wait_for_selector("#no-module-notice", state="visible")
    assert "權限" in page.locator("#no-module-notice").inner_text()                # 沒權限＝明說，不是空白頁


# ── B1：報表設定頁 ──────────────────────────────────────────────────────

@pytest.mark.e2e
def test_settings_page_renders_check_and_saves_a_cashflow_class(live_server, make_user, e2e_browser):
    user, pw = make_user(username="e2e_gl_settings", role="superadmin")
    page = e2e_browser.new_page()
    bad, errs = _open(page, live_server, user, pw, "ledger-settings.html")
    page.wait_for_selector("[data-testid=ls-accounts-table]")
    page.wait_for_selector("[data-testid=ls-check-ok]", state="visible")           # 預設設定完整：綠燈
    page.fill("[data-testid=ls-search]", "1191")
    page.wait_for_selector("[data-testid=ls-row-1191]")
    row = page.locator("[data-testid=ls-row-1191]")
    assert row.locator("[data-testid=ls-cf-select]").input_value() == "operating"

    row.locator("[data-testid=ls-cf-select]").select_option("investing")
    page.wait_for_selector("[data-testid=ls-notice]", state="visible")
    conn = db.get_db()
    try:                                                                           # 終點狀態：資料庫真的改了
        assert conn.execute("SELECT cashflow_class FROM gl_account_meta WHERE code='1191'").fetchone()[0] == "investing"
        conn.execute("UPDATE gl_account_meta SET cashflow_class='operating' WHERE code='1191'")
        conn.commit()
    finally:
        conn.close()
    assert not bad, "開報表設定頁時有請求失敗：%s" % bad[:4]
    assert not errs, "頁面丟了例外：%s" % errs[:3]


@pytest.mark.e2e
def test_settings_page_shows_a_problem_account_and_the_warning(live_server, make_user, e2e_browser):
    user, pw = make_user(username="e2e_gl_settings2", role="superadmin")
    conn = db.get_db()
    try:
        conn.execute("INSERT OR IGNORE INTO account_items(code, level, name, parent_code, source) VALUES ('1998', 4, 'e2e 無群組科目', NULL, 'statutory')")
        conn.commit()
    finally:
        conn.close()
    page = e2e_browser.new_page()
    _open(page, live_server, user, pw, "ledger-settings.html")
    page.wait_for_selector("[data-testid=ls-missing-fs]", state="visible")         # 反向控制：缺歸屬要明說，不是綠燈
    assert "1998" in page.locator("[data-testid=ls-missing-fs]").inner_text()
    assert "1998" in page.locator("[data-testid=ls-missing-cf]").inner_text()
    assert page.locator("[data-testid=ls-check-ok]").count() == 0 or not page.locator("[data-testid=ls-check-ok]").is_visible()
    page.check("[data-testid=ls-only-problems]")
    page.wait_for_selector("[data-testid=ls-row-1998]")
    assert page.locator("[data-testid^=ls-row-]").count() == 1


# ── B2：財務報表頁 ──────────────────────────────────────────────────────

@pytest.mark.e2e
def test_statements_page_balance_sheet_income_statement_and_unmapped_banner(live_server, make_user, e2e_browser):
    user, pw = make_user(username="e2e_gl_stmt", role="superadmin")
    _seed("2171-01-05", [("1113", 100000, 0), ("3111", 0, 100000)])
    _seed("2171-01-10", [("1191", 10500, 0), ("4111", 0, 10000), ("2204", 0, 500)])
    _seed("2171-01-20", [("6112", 1000, 0), ("1113", 0, 1000)])
    page = e2e_browser.new_page()
    bad, errs = _open(page, live_server, user, pw, "ledger-statements.html")
    page.wait_for_selector("[data-testid=st-as-of]")
    page.fill("[data-testid=st-as-of]", "2171-01-31")
    page.click("[data-testid=st-run]")
    page.wait_for_selector("[data-testid=st-bs-table]")
    # 等終點狀態（新日期的數字出現），不是等第一次自動載入留下的舊畫面（那次是今天、全 0、也是平衡的）
    page.wait_for_function("() => { const e = document.querySelector('[data-testid=st-bs-total-assets] td.num'); return e && e.textContent.trim() === '109,500' }")
    page.wait_for_selector("[data-testid=st-bs-ok]", state="visible")                # 對帳通過的綠燈
    assert page.locator("[data-testid=st-bs-total-le] td.num").first.inner_text().strip() == "109,500"   # 資產 ＝ 負債＋權益（含本期損益 9,000）
    assert not page.locator("[data-testid=st-bs-unbalanced]").is_visible()
    page.locator("[data-testid=st-bs-line-BS_CA_AR]").click()                         # 點列展開科目明細
    page.wait_for_function("() => document.body.innerText.includes('1191 應收帳款')")

    page.click("[data-testid=st-tab-is]")
    page.fill("[data-testid=st-start]", "2171-01-01")
    page.fill("[data-testid=st-end]", "2171-01-31")
    page.click("[data-testid=st-run]")
    page.wait_for_function("() => { const e = document.querySelector('[data-testid=st-is-line-IS_NI] td.num'); return e && e.textContent.trim() === '9,000' }")
    page.wait_for_selector("[data-testid=st-is-ok]", state="visible")

    # 反向控制：有餘額卻沒有報表列的科目 ⇒ 紅色橫幅並點名，不可被吸收
    conn = db.get_db()
    try:
        conn.execute("UPDATE gl_account_meta SET fs_line='' WHERE code='1191'")
        conn.commit()
    finally:
        conn.close()
    page.click("[data-testid=st-tab-bs]")
    page.click("[data-testid=st-run]")
    page.wait_for_selector("[data-testid=st-bs-unbalanced]", state="visible")
    assert "1191" in page.locator("[data-testid=st-bs-unbalanced]").inner_text()
    conn = db.get_db()
    try:
        conn.execute("UPDATE gl_account_meta SET fs_line='BS_CA_AR' WHERE code='1191'")
        conn.commit()
    finally:
        conn.close()
    assert not bad, "開財務報表頁時有請求失敗：%s" % bad[:4]
    assert not errs, "頁面丟了例外：%s" % errs[:3]


# ── 底層一次到位：總帳作業（功能旗標中樞）────────────────────────────────

@pytest.mark.e2e
def test_hub_page_lists_features_and_toggle_shows_and_hides_the_tab(live_server, make_user, e2e_browser):
    user, pw = make_user(username="e2e_gl_hub", role="superadmin")
    page = e2e_browser.new_page()
    bad, errs = _open(page, live_server, user, pw, "ledger-hub.html")
    page.wait_for_selector("[data-testid=hb-features]")
    page.wait_for_selector("[data-testid=hb-row-engine_drafts]")
    assert page.locator("[data-testid=hb-none]").is_visible()                       # 預設全關：明說「沒有已開啟的功能」
    assert page.locator("[data-testid=hb-tab-engine_drafts]").count() == 0

    page.locator("[data-testid=hb-row-engine_drafts] [data-testid=hb-toggle]").click()
    page.wait_for_selector("[data-testid=hb-tab-engine_drafts]", state="visible")           # 開啟 ⇒ 頁籤出現
    page.wait_for_selector("[data-testid=hb-body]", state="visible")
    page.wait_for_selector("[data-testid=hb-engine]", state="visible")                   # 分錄草稿頁籤有自己的內容
    conn = db.get_db()
    try:
        assert conn.execute("SELECT value FROM gl_settings WHERE key='feature.engine_drafts'").fetchone()[0] == "1"
    finally:
        conn.close()

    page.locator("[data-testid=hb-row-engine_drafts] [data-testid=hb-toggle]").click()
    page.wait_for_function("() => !document.querySelector('[data-testid=hb-tab-engine_drafts]')")
    assert not bad, "開總帳作業頁時有請求失敗：%s" % bad[:4]
    assert not errs, "頁面丟了例外：%s" % errs[:3]


# ── B5：年度結轉與決算 ────────────────────────────────────────────────────

@pytest.mark.e2e
def test_hub_unbuilt_features_show_in_development_and_cannot_be_enabled(live_server, make_user, e2e_browser):
    user, pw = make_user(username="e2e_gl_hub_ready", role="superadmin")
    page = e2e_browser.new_page()
    bad, errs = _open(page, live_server, user, pw, "ledger-hub.html")
    page.wait_for_selector("[data-testid=hb-features]")
    for key in ("fixed_assets", "invoice_adjustments", "custom_records", "backfill", "inventory_cost"):
        assert page.locator("[data-testid=hb-status-%s]" % key).inner_text() == "開發中", key
        assert page.locator("[data-testid=hb-row-%s] [data-testid=hb-toggle]" % key).is_disabled(), key
    for key in ("engine_drafts", "tax401", "withholding", "source_annotations"):
        assert page.locator("[data-testid=hb-status-%s]" % key).inner_text() in ("未開啟", "已開啟"), key
        assert page.locator("[data-testid=hb-row-%s] [data-testid=hb-toggle]" % key).is_enabled(), key
    assert not bad and not errs


@pytest.mark.e2e
def test_periods_page_year_closing_generate_close_and_reopen(live_server, make_user, e2e_browser):
    from modules.accounting.ledger import periods as P
    user, pw = make_user(username="e2e_gl_year", role="superadmin")
    y = 2196
    conn = db.get_db()
    try:
        P.create_year(conn, y, "t")
        conn.commit()
    finally:
        conn.close()
    _seed("%d-01-05" % y, [("1113", 100000, 0), ("3111", 0, 100000)])
    _seed("%d-01-10" % y, [("1191", 10500, 0), ("4111", 0, 10000), ("2204", 0, 500)])
    _seed("%d-01-20" % y, [("6112", 1000, 0), ("1113", 0, 1000)])
    conn = db.get_db()
    try:
        for n in range(1, 12):
            P.close_period(conn, conn.execute("SELECT id FROM gl_periods WHERE year=? AND period_no=?", (y, n)).fetchone()[0], "acc", accept_warnings=True)
        conn.commit()
    finally:
        conn.close()
    page = e2e_browser.new_page()
    bad, errs = _open(page, live_server, user, pw, "ledger-periods.html")
    page.wait_for_selector("[data-testid=lp-closing-%d]" % y)
    page.click("[data-testid=lp-closing-%d]" % y)
    page.wait_for_selector("[data-testid=lp-closing-dialog]", state="visible")
    assert page.locator("[data-testid=lp-closing-ni]").inner_text().strip() == "9,000"           # 收入 10,000 − 租金 1,000

    page.click("[data-testid=lp-closing-close]")                                                # 還沒結轉就決算 ⇒ 被擋並說明
    page.wait_for_selector("[data-testid=lp-closing-error]", state="visible")
    assert "損益科目還有餘額" in page.locator("[data-testid=lp-closing-error]").inner_text()

    page.click("[data-testid=lp-closing-generate]")
    page.wait_for_selector("[data-testid=lp-closing-done]", state="visible")
    page.wait_for_function("() => document.querySelector('[data-testid=lp-closing-existing]') && document.querySelector('[data-testid=lp-closing-existing]').textContent.includes('草稿')")
    conn = db.get_db()
    try:                                                                                        # 走過簽核後過帳（測試直接改狀態）
        assert conn.execute("SELECT COUNT(*) FROM vouchers_all WHERE kind='closing' AND voided_at='' AND voucher_date LIKE ?", ("%d-%%" % y,)).fetchone()[0] == 2
        conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE kind='closing' AND voided_at='' AND voucher_date LIKE ?", ("%d-%%" % y,))
        conn.commit()
    finally:
        conn.close()
    page.check("[data-testid=lp-closing-accept]")
    page.click("[data-testid=lp-closing-close]")
    page.wait_for_function("() => document.querySelector('[data-testid=lp-year-status-%d]').textContent.trim() === '已決算'" % y)
    conn = db.get_db()
    try:
        assert conn.execute("SELECT status FROM gl_fiscal_years WHERE year=?", (y,)).fetchone()[0] == "closed"
    finally:
        conn.close()

    page.fill("[data-testid=lp-closing-reason]", "會計師要求調整")
    page.click("[data-testid=lp-closing-reopen]")
    page.wait_for_function("() => document.querySelector('[data-testid=lp-year-status-%d]').textContent.trim() === '年度進行中'" % y)
    conn = db.get_db()
    try:
        assert conn.execute("SELECT status FROM gl_fiscal_years WHERE year=?", (y,)).fetchone()[0] == "open"
        assert conn.execute("SELECT COUNT(*) FROM vouchers_all WHERE kind='closing' AND voided_at='' AND voucher_date LIKE ?", ("%d-%%" % y,)).fetchone()[0] == 0
    finally:
        conn.close()
    # 唯一允許的 4xx＝本題刻意觸發的「還沒結轉就決算」400
    assert [b for b in bad if b[0] != 400] == [], bad[:4]
    assert not errs, "頁面丟了例外：%s" % errs[:3]


# ── C1：總帳作業的「分錄草稿」頁籤 ────────────────────────────────────────

@pytest.mark.e2e
def test_hub_engine_tab_runs_lists_and_batch_confirms(live_server, make_user, e2e_browser):
    import json as _json
    from datetime import datetime as _dtm
    user, pw = make_user(username="e2e_gl_engine", role="superadmin")
    items = [{"id": "p1", "type": "全額", "amount": 10500, "invoiceNo": "EE12345678", "invoiceDate": "2172-09-10",
              "received": True, "receivedAt": "2172-09-15", "actualAmount": 10485, "feeAmount": 15}]
    conn = db.get_db()
    try:
        now = _dtm.now().isoformat()
        data = {"quoteNo": "MQ-E2E-C1", "dealTag": "已成案", "caseRecord": {"payment": {"items": items}}}
        conn.execute("INSERT INTO quotations (quote_no, status, total, pretax, data_json, created_at, updated_at, customer_name) VALUES (?,?,?,?,?,?,?,?)",
                     ("MQ-E2E-C1", "已成案", 10500, 10000, _json.dumps(data, ensure_ascii=False), now, now, "甲公司"))
        conn.execute("INSERT INTO gl_settings(key,value) VALUES ('feature.engine_drafts','1') ON CONFLICT(key) DO UPDATE SET value='1'")
        conn.commit()
    finally:
        conn.close()
    page = e2e_browser.new_page()
    bad, errs = _open(page, live_server, user, pw, "ledger-hub.html")
    page.wait_for_selector("[data-testid=hb-tab-engine_drafts]")
    page.click("[data-testid=hb-tab-engine_drafts]")
    page.wait_for_selector("[data-testid=hb-engine]", state="visible")
    assert page.locator("[data-testid=hb-eng-empty]").is_visible()
    page.fill("[data-testid=hb-eng-start]", "2172-09-01")
    page.fill("[data-testid=hb-eng-end]", "2172-09-30")
    page.click("[data-testid=hb-eng-run]")
    page.wait_for_function("() => document.querySelectorAll('[data-testid^=hb-eng-row-]').length >= 2")           # E01＋E03
    table = page.locator("[data-testid=hb-eng-table]").inner_text()
    assert "E01" in table and "E03" in table and "草稿待確認" in table and "MQ-E2E-C1::EE12345678" in table
    assert "尚未接入" in page.locator("[data-testid=hb-engine]").inner_text() or "未安裝" in page.locator("[data-testid=hb-engine]").inner_text()   # 其他來源明說缺席

    page.click("text=全選草稿")
    page.click("[data-testid=hb-eng-all]")
    page.wait_for_function("() => document.querySelector('[data-testid=hb-eng-counts]').textContent.includes('已過帳')")
    conn = db.get_db()
    try:                                                                                    # 終點狀態：傳票真的過帳、試算表看得到應收
        st = [r[0] for r in conn.execute("SELECT status FROM vouchers_all WHERE origin LIKE 'gl:%' AND voucher_date LIKE '2172-09-%'")]
        assert st and set(st) == {"已過帳"}
    finally:
        conn.close()
    assert not bad, "開總帳作業（分錄草稿）時有請求失敗：%s" % bad[:4]
    assert not errs, "頁面丟了例外：%s" % errs[:3]
