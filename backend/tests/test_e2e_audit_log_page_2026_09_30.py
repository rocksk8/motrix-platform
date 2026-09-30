# -*- coding: utf-8 -*-
"""歷史紀錄頁（R2：頁面與每個新按鈕都驗）：分層樹預設近 90 天並顯示範圍、「擴大到 366 天」按鈕、模組下拉／只看失敗／清除、下鑽。
斷言打在 DOM 與送出的請求；截圖存 repo 內 logs/e2e-shots/（再由人搬到 D:/開發測試檔/shots/wip-w2-audit-dos/）。"""
import os
from datetime import datetime, timedelta

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

SHOTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "e2e-shots", "wip-w2-audit-dos")


def _seed():
    import db
    c = db.get_db()
    try:
        def at(n):
            # 2026-10-01 教訓：原本固定 10:00，凌晨 00:00～10:00 跑時「今天 10:00」在未來、被查詢窗口（到現在為止）排除 ⇒ 測試只在白天綠。
            # 改 00:00:01：任何時刻都已經過去。
            return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%dT00:00:01")
        rows = [(at(3), "quotation.create", "quotation", "MQ-202609-001", "ok", ""), (at(4), "quotation.approve", "quotation", "MQ-202609-001", "ok", ""),
                (at(6), "voucher.create", "voucher", "MQ-202609-002", "ok", ""), (at(2), "fail.POST", "voucher", "MQ-202609-002", "fail", "conflict"),
                (at(250), "quotation.create", "quotation", "MQ-202601-009", "ok", "")]
        for a, act, mod, case, res, reason in rows:
            c.execute("INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail,module,case_no,ref_no,result,reason_code,status_code)"
                      " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (a, 1, "seed", "種子", act, mod, case, act, "{}", mod, case, "", res, reason, 409 if res == "fail" else 0))
        c.commit()
    finally:
        c.close()


def _shot(page, name):
    os.makedirs(SHOTS, exist_ok=True)
    with open(os.path.join(SHOTS, name), "wb") as f:
        f.write(page.screenshot())


@pytest.mark.e2e
def test_audit_log_page_window_widen_filters_and_drill(live_server, new_context, make_user):
    user = make_user(username="alp_sa", role="superadmin", modules=[])
    _seed()
    errors = []
    page = new_context().new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    reqs = []
    page.on("request", lambda r: reqs.append(r.url) if "/api/audit-log/tree" in r.url else None)
    inject_login(page, live_server, user[0], user[1])
    page.goto(live_server + "/pages/audit-log.html")
    win = page.locator('[data-testid="tree-window"]')
    win.wait_for(state="visible", timeout=20000)
    assert "預設近 90 天" in win.inner_text()
    # 預設視窗：250 天前那筆不在樹裡（模組「報價單」只有近 90 天的 2 筆）
    page.wait_for_selector(".drill-node")
    node = page.locator(".drill-node", has_text="報價單").first
    assert "2" in node.inner_text() and "3" not in node.inner_text().replace("2", "", 1)
    _shot(page, "audit-log-default-window.png")
    # 「擴大到 366 天」：樹重新載入、送出的請求帶 date_from（約 366 天前）、250 天前那筆進來
    page.locator('[data-testid="tree-widen"]').click()
    page.wait_for_function("() => !document.querySelector('[data-testid=tree-window]').innerText.includes('預設近')", timeout=10000)
    assert any("date_from=" in u for u in reqs[-2:]), reqs
    page.wait_for_function("() => { const n = [...document.querySelectorAll('.drill-node')].find(x => x.innerText.includes('報價單')); return n && n.innerText.includes('3') }", timeout=10000)
    _shot(page, "audit-log-widened.png")
    # 只看失敗：清單只剩失敗列、上方原因 chip 出現
    page.locator(".seg button", has_text="只看失敗").click()
    page.wait_for_function("() => document.querySelectorAll('.tl-item.is-fail').length > 0 && document.querySelectorAll('.tl-item:not(.is-fail)').length === 0", timeout=10000)
    assert page.locator(".chip").count() >= 1
    # 清除：回到全部、視窗回預設
    page.get_by_text("清除", exact=True).click()
    page.wait_for_function("() => document.querySelector('[data-testid=tree-window]').innerText.includes('預設近')", timeout=10000)
    assert page.locator(".tl-item").count() >= 3
    # 下鑽：點模組「傳票」⇒ 麵包屑出現、樹變成案件層
    page.locator(".drill-node", has_text="傳票").first.click()
    page.wait_for_selector(".crumb a >> text=傳票", timeout=10000)
    page.wait_for_selector(".drill-node:has-text('MQ-202609-002')", timeout=10000)                 # 樹載入是非同步的
    assert page.locator(".drill-node", has_text="MQ-202609-002").count() == 1
    assert not errors, errors
