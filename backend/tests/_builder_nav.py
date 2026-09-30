# -*- coding: utf-8 -*-
"""模組建構器 e2e 共用：頁籤導覽與新模組開啟（建構器第三輪，2026-09-30）。

第三輪把七格縮圖導覽改成頂列三個頁籤（作業資訊／表單設計／流程設計）＋「發布」抽屜；內部步驟號 1、2、4、5、6
與區段 id `#mb-step-N` 保留（沒有第 3 步）：步驟 1、5 在「作業資訊」、2 在「表單設計」、4 在「流程設計」、6 在發布抽屜。
新模組開啟前會先出「從範本開始」（空白或範本）。既有題的行為驗收不變，只換「怎麼走到那一步」——逐題改用這裡的函式。"""

TAB_OF_STEP = {1: "info", 5: "info", 2: "form", 4: "flow"}


def go_step(page, n):
    """走到內部步驟 n（等對應區段可見）。6＝發布抽屜。"""
    n = int(n)
    if n == 6:
        page.click("#mb-publish-open")
    else:
        page.click('.mb-tab[data-tab="%s"]' % TAB_OF_STEP[n])
    page.wait_for_selector("#mb-step-%d" % n, state="visible")


def start_blank(page, key):
    """在建構器首頁輸入新模組代號並開啟；出現「從範本開始」就選空白。等到 #mb-step-1 可見。"""
    page.fill("#mb-key", key)
    page.click("#mb-open")
    page.wait_for_selector("#mb-tpl-blank, #mb-step-1", state="visible")
    if page.locator("#mb-tpl-blank").count() and page.locator("#mb-tpl-blank").is_visible():
        page.click("#mb-tpl-blank")
    page.wait_for_selector("#mb-step-1", state="visible")
