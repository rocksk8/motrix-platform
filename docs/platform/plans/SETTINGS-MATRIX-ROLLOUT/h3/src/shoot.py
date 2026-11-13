# -*- coding: utf-8 -*-
import sys, os
from playwright.sync_api import sync_playwright
OUT = "D:/Claude-pm/h3-matrix/docs/platform/plans/SETTINGS-MATRIX-ROLLOUT/h3"
URL = "file:///" + OUT + "/index.html"
errs = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    pg.on("console", lambda m: errs.append(("console", m.type, m.text)) if m.type in ("error", "warning") else None)
    pg.on("pageerror", lambda e: errs.append(("pageerror", str(e))))
    pg.goto(URL)
    pg.wait_for_selector(".subsec")
    pg.screenshot(path=OUT + "/shots/01-settings-center.png", full_page=False)
    # 與預設不同
    pg.click("button.chip[data-k=diff]")
    pg.wait_for_selector(".row.chg")
    pg.screenshot(path=OUT + "/shots/02-filter-changed.png")
    pg.click("button.chip[data-k=all]")
    # 利潤區：選兩列 → 批次列 → 套用建議值（確認視窗）
    pg.select_option("#secsel", "profit")
    pg.wait_for_selector("#s-p-warning")
    pg.screenshot(path=OUT + "/shots/03-profit-matrix.png")
    pg.check("#s-p-warning input[data-act=selsub]")
    pg.wait_for_selector("#batch:not(.hide)")
    pg.click("#batch button[data-m=rec]")
    pg.wait_for_selector(".dlg")
    pg.screenshot(path=OUT + "/shots/04-batch-confirm.png")
    # 套用
    ok = pg.locator("#okBtn")
    if ok.is_disabled():
        pg.check("#opsOk")
    pg.click("#okBtn")
    pg.wait_for_selector("#toast:not(.hide)")
    pg.screenshot(path=OUT + "/shots/05-batch-applied-undo.png")
    # 衝突示範
    pg.click("button[data-act=demo-conflict]")
    pg.wait_for_selector("#undoBtn")
    pg.click("#undoBtn")
    pg.wait_for_timeout(200)
    pg.screenshot(path=OUT + "/shots/06-undo-refused.png")
    # 鎖定矩陣 → 單項高風險確認
    pg.select_option("#secsel", "quote")
    pg.wait_for_selector("#s-q-alt-lock")
    pg.locator("#s-q-alt-lock").scroll_into_view_if_needed()
    pg.screenshot(path=OUT + "/shots/07-lock-matrix.png")
    pg.locator("#s-q-alt-lock button.cell:not([disabled]):not(.on)").first.click()
    pg.wait_for_selector(".dlg")
    pg.screenshot(path=OUT + "/shots/08-heavy-confirm.png")
    pg.fill("#reason", "客戶要求")
    pg.click("#okBtn")
    pg.wait_for_timeout(200)
    # 財務：帳齡
    pg.select_option("#secsel", "finance")
    pg.wait_for_selector("#s-f-reports")
    pg.locator("#s-f-reports").scroll_into_view_if_needed()
    pg.screenshot(path=OUT + "/shots/09-finance-aging.png")
    # "?" 說明
    pg.locator("#s-f-reports .q").first.click()
    pg.wait_for_selector(".help")
    pg.screenshot(path=OUT + "/shots/10-help.png")
    pg.keyboard.press("Escape")
    # 頁籤 2 / 3
    pg.click("button.tab[data-t=t2]"); pg.wait_for_selector("#pg-approval")
    pg.screenshot(path=OUT + "/shots/11-pages-approval-remit.png", full_page=False)
    pg.locator("#pg-remit").scroll_into_view_if_needed()
    pg.locator("#pg-remit input[type=checkbox]").first.click()
    pg.screenshot(path=OUT + "/shots/12-pages-remit.png")
    pg.locator("#pg-legal").scroll_into_view_if_needed()
    pg.screenshot(path=OUT + "/shots/13-pages-legal.png")
    pg.click("button.tab[data-t=t3]"); pg.wait_for_selector("#ot-bonus")
    pg.screenshot(path=OUT + "/shots/14-outside-center.png")
    # 手機
    pg.set_viewport_size({"width": 390, "height": 800})
    pg.click("button.tab[data-t=t1]")
    pg.select_option("#secsel", "finance")
    pg.wait_for_selector("#s-f-cashier")
    pg.locator("#s-f-cashier").scroll_into_view_if_needed()
    pg.screenshot(path=OUT + "/shots/15-phone-cards.png")
    ov = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    print("horizontal overflow px (t1 phone):", ov)
    pg.click("button.tab[data-t=t2]")
    ov2 = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    print("horizontal overflow px (t2 phone):", ov2)
    b.close()
print("errors:", errs)
