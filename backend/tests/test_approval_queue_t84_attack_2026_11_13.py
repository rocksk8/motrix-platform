# -*- coding: utf-8 -*-
"""T84 簽核頁重排（feat/ux-t84-approval-queue @ 6bc619f7b）對抗式測試（作者 hichan-3，2026-11-13；hichan-7 修好後併入、拿掉 xfail）。

綠燈＝作者宣稱成立（沒有新的寫入路徑；單欄／空狀態條件；摘要格不寫入；reasons 只收字串、XSS 安全）。
原本 xfail(strict) 的兩項，T84 修正後已轉為一般測試：
  G 佇列讀取失敗（500／403／斷線）時，頁面會說「目前沒有待簽核的單」（空狀態把錯誤講成『沒事』）
  H 摘要格 role=button 只綁 Enter，沒綁空白鍵（鍵盤操作的按鈕慣例是 Enter＋Space）
"""
import json
import re

import pytest

from core import source_tree

pytest.importorskip("playwright.sync_api")


def _page():
    return source_tree.page_file("approval-queue.html").read_text(encoding="utf-8")


def _func_body(src: str, name: str) -> str:
    i = src.index(name)
    return src[i:i + 2600]


# ── 綠燈：沒有新的寫入路徑 ───────────────────────────────────────────────
def test_new_ui_adds_no_fetch_and_no_write_call():
    """T84 新增的介面（摘要格、空狀態、reasons 標籤、scrollToCol）不得打任何 API：整支頁面的 fetch 呼叫與重排前相同。"""
    import subprocess
    old = subprocess.run(["git", "show", "d72cfef93~1:" + "/".join(("frontend", "pages", "approval-queue.html"))],   # git 歷史裡的舊路徑（不是讀現行頁面），所以不走 page_file()
                         capture_output=True, cwd=str(__import__("pathlib").Path(__file__).resolve().parents[2]), check=True).stdout.decode("utf-8")
    def calls(s):
        return sorted(re.findall(r"fetch\(`?\$\{API\}([^`'\")]+)", s))
    new = calls(_page())
    base = calls(old)
    new = sorted(c.replace("/api/settings/company-profile", "/settings/company-profile") for c in new)   # D2：唯一允許的差異（補 /api 前綴）
    assert new == base, sorted(set(new) ^ set(base))
    sc = _page().split("scrollToCol(which) {")[1].split("queue: []")[0]
    assert "fetch(" not in sc and "XMLHttpRequest" not in sc


def test_kpi_tiles_and_empty_state_only_navigate():
    s = _page()
    for tid in ("aq-kpi-mine", "aq-kpi-flow"):
        seg = s.split('data-testid="%s"' % tid)[1][:260]
        handlers = re.findall(r'@(?:click|keydown\.enter)="([^"]+)"', seg)
        assert handlers and all(h.startswith("scrollToCol(") for h in handlers), handlers
    empty = s.split('data-testid="aq-empty"')[1].split('<div class="aq-runway"')[0]
    assert "@click" not in empty and "fetch" not in empty
    assert set(re.findall(r'href="([^"]+)"', empty)) == {"daily-tasks.html", "quotations.html", "../index.html"}


# ── 綠燈：reasons 是 XSS 安全的純文字 ────────────────────────────────────
def test_reason_chips_render_as_text_not_html():
    s = _page()
    seg = s.split('data-testid="aq-why"')[1][:700]
    assert "x-html" not in seg and 'x-text="rs"' in seg and ':title="rs"' in seg
    assert "innerHTML" not in _func_body(s, "reasonsOf(item)")


@pytest.mark.e2e
def test_reasons_with_markup_and_non_strings_do_not_inject_or_crash(live_server, make_user, new_page, login_as):
    import db
    u = make_user(username="t84a_xss", role="superadmin")
    at = "2026-11-10T09:00:00"
    evil = '<img src=x onerror="window.__pwn=1">'
    data = {"quoteNo": "MQ-T84A-X", "approval": {"requestedBy": "someone", "requestedAt": at, "currentTier": 0,
            "reasons": [evil, 42, None, {"a": 1}, "  ", "正常原因", "第四項", "第五項"],
            "tiers": [{"approvers": [{"username": "t84a_xss", "displayName": "x", "status": "pending"}]}]}}
    c = db.get_db()
    c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, "
              "updated_at, deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
              ("MQ-T84A-X", "待審核", "客戶", "專案", 1000, 952, json.dumps(data, ensure_ascii=False), at, at, "", "someone", "[]"))
    c.commit()
    c.close()
    page = new_page(viewport={"width": 1440, "height": 900})
    page.on("dialog", lambda d: d.accept())
    login_as(page, u)
    page.goto(f"{live_server}/pages/approval-queue.html")
    why = page.locator("[data-testid='aq-item-MQ-T84A-X']").first.locator("[data-testid=aq-why]")
    why.wait_for(state="visible", timeout=20000)
    assert page.evaluate("window.__pwn") is None
    tags = why.locator(".aq-reason-tag").all_inner_texts()
    assert tags == [evil, "正常原因"]                         # 只收字串、空白丟掉、前兩項
    assert "還有 2 項" in why.inner_text()


# ── 已修（原 xfail）────────────────────────────────────────────────────────────
def test_atk_queue_load_failure_must_not_look_like_an_empty_queue_static():
    body = _page().split("async loadQueue() {")[1].split("// ── 轉簽")[0]
    assert "r.ok" in body or "loadError" in body or "queueError" in body, "loadQueue 沒有任何失敗處理，錯誤會被畫成『沒有待簽核』"


@pytest.mark.e2e
def test_atk_queue_500_shows_no_all_clear_message(live_server, make_user, new_page, login_as):
    u = make_user(username="t84a_500", role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 900})
    page.route("**/api/approval-queue", lambda route: route.fulfill(status=500, content_type="application/json",
                                                                   body=json.dumps({"detail": "boom"})))
    login_as(page, u)
    page.goto(f"{live_server}/pages/approval-queue.html")
    page.wait_for_timeout(2500)
    empty = page.locator("[data-testid=aq-empty]")
    assert not empty.is_visible(), "佇列讀取失敗，卻顯示：" + (empty.inner_text()[:40] if empty.is_visible() else "")


def test_atk_role_button_tiles_handle_space_key():
    s = _page()
    for tid in ("aq-kpi-mine", "aq-kpi-flow"):
        seg = s.split('data-testid="%s"' % tid)[1][:260]
        assert "@keydown.space" in seg, tid
