# -*- coding: utf-8 -*-
"""瀏覽器端對端（含截圖）：營運報表「與總帳差異」頁籤（MONEY-FLOWS §9 L4，2026-10-01）。

每個控制項都操作、驗**畫面數字＝伺服器回應＝預先算好的值**（不是只驗有畫面）：頁籤按鈕、年度下拉、現金／權責切換；
差額原因（分桶）區塊；總帳模組不在 ⇒ 顯示說明而不是 0；沒有財務檢視權限 ⇒ 顯示錯誤而不是空表。
報表側以 monkeypatch 固定（live_server 與測試同行程），總帳側種真實傳票。截圖：暫存夾，事後複製到 D:\\開發測試檔\\shots\\wip-w2-recon3\\。"""
import os
import re
import tempfile
from datetime import date

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

def _year():
    return date.today().year   # 呼叫時才取，避免跨年夜與伺服器日期不一致
_SEQ = [0]
_LINKED = []          # 個人外包（已關聯勞報單）金額替身；預設空 ⇒ 其餘題不受影響


def _shot(page, name):
    try:
        d = os.path.join(os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "w2-shots"), "wip-w2-recon3")
        os.makedirs(d, exist_ok=True)
        page.screenshot(path=os.path.join(d, name + ".png"), full_page=True)
    except Exception:  # noqa: BLE001
        pass


def _v(conn, d, lines, status="已過帳", kind="manual", origin=""):
    _SEQ[0] += 1
    cur = conn.execute(
        "INSERT INTO vouchers_all(voucher_no, voucher_date, category, summary, status, created_by, created_at, updated_at, kind, origin)"
        " VALUES (?,?, '轉','s',?, 't','n','n', ?, ?)", ("E2LD-%s-%03d" % (d.replace("-", ""), _SEQ[0]), d,
                                                            "已核准" if status == "已過帳" else status, kind, origin))
    for i, (code, dr, cr) in enumerate(lines, 1):
        conn.execute("INSERT INTO voucher_lines(voucher_id,line_no,account_code,debit,credit) VALUES (?,?,?,?,?)", (cur.lastrowid, i, code, dr, cr))
    if status == "已過帳":
        conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (cur.lastrowid,))
    conn.commit()


def _seed_gl():
    import db
    from modules.accounting.ledger import roles as ROLES
    c = db.get_db()
    try:
        ROLES.ensure_meta(c)
        c.commit()
        _v(c, "%d-02-05" % _year(), [("1113", 1050, 0), ("4111", 0, 1000), ("2204", 0, 50)])
        _v(c, "%d-02-06" % _year(), [("5811", 500, 0), ("1268", 25, 0), ("2171", 0, 525)], origin="gl:E04", kind="auto")
        _v(c, "%d-02-07" % _year(), [("1191", 200, 0), ("4111", 0, 200)], status="草稿", origin="gl:E03", kind="auto")
        _v(c, "%d-02-08" % _year(), [("6112", 100, 0), ("1113", 0, 100)])
    finally:
        c.close()


def _patch_report(monkeypatch):
    """只替「與總帳差異」端點固定報表側數字：把 ledger_diff 模組裡的 `R` 換成代理（其餘屬性照舊委派給真的報表模組），
    **不**動報表模組本身——否則同一頁的其他報表請求會被簽章不同的假函式弄成 500。"""
    from modules.analytics.api import reports as R
    from modules.analytics.api import ledger_diff as LD

    def _income(a, b, d=None):
        return [{"amount": 1250}] if a[:7] == "%d-02" % _year() else []

    def _expenses(year, dept=None, basis="cash", conn=None):
        return {"monthly": [dict({"month": "%d-%02d" % (year, m), "contractor": 0, "equipment": 0, "material": 0, "other": 0},
                                 **({"contractor": 525, "other": 140} if (year, m) == (_year(), 2) else {})) for m in range(1, 13)]}

    class _Rec:
        @staticmethod
        def accrual_income_items(c, a, b, d):
            return [{"amount": 1000}] if a[:7] == "%d-02" % _year() else []

        @staticmethod
        def individual_linked_entries(c, basis):
            return list(_LINKED)

    class _Proxy:
        _collect_income_items = staticmethod(_income)
        _collect_expenses = staticmethod(_expenses)
        _recognition = staticmethod(lambda: _Rec)

        def __getattr__(self, name):
            return getattr(R, name)

    monkeypatch.setattr(LD, "R", _Proxy())


def _num(text):
    t = (text or "").replace(",", "").replace("NT$", "").replace("−", "-").strip()
    m = re.search(r"-?\d+", t)
    return int(m.group(0)) if m else None


def _feb(page, year=None):
    row = page.locator('[data-testid="gldiff-table"] tr[data-month="%d-02"]' % (year or _year()))
    row.wait_for(timeout=15000)
    return [_num(x) for x in row.locator("td").all_inner_texts()[1:]]      # 收入 報表/總帳/差額、支出 報表/總帳/差額、待處理


def _open(page, live_server):
    page.goto(live_server + "/pages/reports.html")
    try:
        page.locator('[data-testid="tab-gldiff"]').wait_for(timeout=20000)
    except Exception:
        _shot(page, "debug")
        print("BODY:", page.inner_text("body")[:400].replace(chr(10), " | "), "TABS:", page.locator(".tab").count(), page.locator('[data-testid="tab-gldiff"]').count())
        raise


@pytest.mark.e2e
def test_tab_year_and_basis_controls_show_the_computed_numbers(live_server, make_user, e2e_browser, monkeypatch):
    _seed_gl()
    _patch_report(monkeypatch)
    u = make_user(username="e2ld_sa", role="superadmin", modules=[])
    page = e2e_browser.new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    reqs = []
    page.on("request", lambda r: reqs.append(r.url) if "/api/reports/ledger-diff" in r.url else None)
    inject_login(page, live_server, u[0], u[1])
    _open(page, live_server)
    assert page.locator('[data-testid="gldiff-panel"]').is_hidden()          # 沒點頁籤前不載入
    assert not reqs
    # 頁籤按鈕 ⇒ 載入（現金）
    page.locator('[data-testid="tab-gldiff"]').click()
    page.locator('[data-testid="gldiff-panel"]').wait_for(state="visible", timeout=10000)
    assert _feb(page) == [1250, 1000, 250, 665, 600, 65, 0]
    assert any("basis=cash" in r and ("year=%d" % _year()) in r for r in reqs), reqs
    # 差額原因：收入有未過帳草稿 200、手工 −1000；支出稅額 25
    bk = page.locator('[data-buckets="%d-02"]' % _year()).inner_text()
    assert "總帳未過帳草稿" in bk and "200" in bk and "稅額" in bk and "25" in bk
    tot = page.locator('[data-testid="gldiff-total"] td').all_inner_texts()
    assert [_num(x) for x in tot[1:4]] == [1250, 1000, 250]
    _shot(page, "01-cash")
    # 權責（未稅）切換：收入報表改 1000 ⇒ 差額 0
    page.locator('[data-testid="gldiff-basis-accrual"]').click()
    page.wait_for_function("() => document.querySelector('[data-testid=gldiff-basis-accrual]').classList.contains('on')", timeout=10000)
    page.wait_for_function("(y) => { const r = document.querySelector('[data-testid=gldiff-table] tr[data-month=\"' + y + '-02\"]'); return r && r.children[1].innerText.replace(/[^0-9]/g,'') === '1000' }", arg=_year(), timeout=10000)
    assert any("basis=accrual" in r for r in reqs[-2:]), reqs
    assert _feb(page)[:3] == [1000, 1000, 0]
    _shot(page, "02-accrual")
    # 回現金
    page.locator('[data-testid="gldiff-basis-cash"]').click()
    page.wait_for_function("(y) => { const r = document.querySelector('[data-testid=gldiff-table] tr[data-month=\"' + y + '-02\"]'); return r && r.children[1].innerText.replace(/[^0-9]/g,'') === '1250' }", arg=_year(), timeout=10000)
    # 年度下拉：去年 ⇒ 請求帶 year=去年、表格重載（二月沒資料）
    page.select_option('[data-testid="gldiff-year"]', str(_year() - 1))
    page.wait_for_function("() => true")
    page.wait_for_timeout(800)
    assert any(("year=%d" % (_year() - 1)) in r for r in reqs[-2:]), reqs
    assert _feb(page, _year() - 1)[:6] == [0, 0, 0, 0, 0, 0]                          # 去年二月沒有任何資料
    _shot(page, "03-previous-year")
    page.select_option('[data-testid="gldiff-year"]', str(_year()))
    page.wait_for_timeout(800)
    assert _feb(page) == [1250, 1000, 250, 665, 600, 65, 0]
    assert not errors, errors


@pytest.mark.e2e
def test_gl_module_absent_shows_notice_not_zero(live_server, make_user, e2e_browser, monkeypatch):
    _patch_report(monkeypatch)
    from modules.analytics.api import ledger_diff as LD
    monkeypatch.setattr(LD._registry, "providers", lambda cap: {} if cap == "ledger.month_totals" else {})
    u = make_user(username="e2ld_sa2", role="superadmin", modules=[])
    page = e2e_browser.new_context().new_page()
    inject_login(page, live_server, u[0], u[1])
    _open(page, live_server)
    page.locator('[data-testid="tab-gldiff"]').click()
    page.locator('[data-testid="gldiff-unavailable"]').wait_for(timeout=15000)
    assert "總帳不可用" in page.inner_text('[data-testid="gldiff-unavailable"]')
    row = page.locator('[data-testid="gldiff-table"] tr[data-month="%d-02"]' % _year())
    row.wait_for(timeout=10000)
    assert _num(row.locator("td").nth(1).inner_text()) == 1250                # 報表欄照常
    _shot(page, "04-gl-absent")


@pytest.mark.e2e
def test_user_without_finance_view_sees_an_error_not_an_empty_table(live_server, make_user, e2e_browser, monkeypatch):
    """沒有財務檢視權限（端點 403）⇒ 頁籤顯示錯誤，不是一張空表。（以 money_visible 固定為 False 模擬；端點的 403 另有 API 題。）"""
    _patch_report(monkeypatch)
    from modules.analytics.api import ledger_diff as LD
    monkeypatch.setattr(LD, "quote_money_visible", lambda u: False)    # 第42班：端點改看報價層級判斷（財務專屬判斷另拆）
    u = make_user(username="e2ld_sa3", role="superadmin", modules=[])
    page = e2e_browser.new_context().new_page()
    inject_login(page, live_server, u[0], u[1])
    _open(page, live_server)
    page.locator('[data-testid="tab-gldiff"]').click()
    page.locator('[data-testid="gldiff-error"]').wait_for(timeout=15000)
    assert "與總帳差異載入失敗" in page.inner_text('[data-testid="gldiff-error"]')
    assert page.locator('[data-testid="gldiff-table"]').count() == 0
    _shot(page, "05-no-permission")


@pytest.mark.e2e
def test_category_level_buckets_are_shown_with_the_computed_numbers(live_server, make_user, e2e_browser, monkeypatch):
    """低風險 #3(b)：類別層級原因分桶畫在頁上。手算（現金口徑，二月；報表側固定：承攬商 525、其他 140；總帳側種：E04 500＋進項稅 25、手工費用 100）：
      承攬商 報表 525／總帳 500／差額 25：稅額 25＋個人外包 40（替身：已關聯勞報單 40）＋其餘 −40（25−25−40）
      其他   報表 140／總帳 100／差額 40：個人外包 −40＋手工傳票 −100＋其餘 180（40−(−40−100)）
    畫面數字逐項對。"""
    _seed_gl()
    _patch_report(monkeypatch)
    import sys
    monkeypatch.setattr(sys.modules[__name__], "_LINKED", [{"date": "%d-02-10" % _year(), "dispatchId": 1, "amount": 40}])
    u = make_user(username="e2ld_sa4", role="superadmin", modules=[])
    page = e2e_browser.new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, u[0], u[1])
    _open(page, live_server)
    page.locator('[data-testid="tab-gldiff"]').click()
    block = page.locator('[data-cat-buckets="%d-02"]' % _year())
    block.wait_for(timeout=15000)
    ctr = block.locator('[data-cat="contractor"]')
    oth = block.locator('[data-cat="other"]')
    ctr.wait_for(timeout=10000)
    oth.wait_for(timeout=10000)

    def buckets(loc):
        out = {}
        for i in range(loc.locator("[data-bucket]").count()):
            sp = loc.locator("[data-bucket]").nth(i)
            if not sp.is_visible():              # 0 的桶 x-show 隱藏（與月合計列同規則）
                continue
            out[sp.get_attribute("data-bucket")] = _num(sp.inner_text().rsplit(" ", 1)[-1])
        return out
    assert _num(ctr.inner_text().split("差額")[1]) == 25
    assert buckets(ctr) == {"tax": 25, "individual": 40, "residual": -40}
    assert _num(oth.inner_text().split("差額")[1]) == 40
    assert buckets(oth) == {"individual": -40, "manual": -100, "residual": 180}
    assert block.locator('[data-cat="equipment"]').count() == 0 or block.locator('[data-cat="equipment"]').is_hidden()     # 沒有差額的類別不列
    _shot(page, "06-category-buckets")
    # 權責（未稅）：稅額桶消失，個人外包仍在
    page.locator('[data-testid="gldiff-basis-accrual"]').click()
    page.wait_for_function("() => { const s = n => document.querySelector('[data-cat=contractor] [data-bucket=' + n + ']');"
                           " return s('individual') && s('individual').offsetParent !== null && (!s('tax') || s('tax').offsetParent === null) }", timeout=10000)   # 稅額桶（現金時可見）消失＝這次切換的終點
    assert buckets(block.locator('[data-cat="contractor"]')).get("individual") == 40
    assert buckets(block.locator('[data-cat="contractor"]')) == {"individual": 40, "residual": -15}          # 應計未稅：差額 25＝個人外包 40＋其餘 −15
    assert not errors, errors
