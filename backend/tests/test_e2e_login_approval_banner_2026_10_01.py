# -*- coding: utf-8 -*-
"""登入的「待簽核」橫幅：只在真的有待我簽的項目時跳；簽過之後再登入不再跳（使用者 2026-10-01 回報）。

橫幅數字＝/api/approval-queue/count（與角標同一份）。反向控制：簽過之後我另外塞一筆**未讀**的 approval_request 通知列
（模擬別的簽核流程沒標已讀），橫幅仍不可以跳——舊實作（數未讀通知列）會在這裡紅。
"""
import json
from datetime import datetime

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_notice_banners_2026_09_25 import _pending_approval, _session_only  # noqa: E402

BANNER = "#approval-notif-banner"


def _login_headers(client, u):
    d = client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()
    return {"Authorization": "Bearer " + d["token"]}


def _open_after_login(live_server, client, new_context, user):
    """新 context ＝新分頁狀態（sessionStorage 清空）＝剛登入。回 (page, 這次載入拿到的待簽數)。"""
    ctx = new_context(viewport={"width": 1440, "height": 900})
    _session_only(client, ctx, user)
    page = ctx.new_page()
    with page.expect_response(lambda r: "/api/approval-queue/count" in r.url) as resp:
        page.goto(f"{live_server}/pages/quotations.html")
    return page, resp.value.json()["count"]


@pytest.mark.e2e
def test_banner_shows_while_pending_and_not_after_signing(live_server, client, make_user, new_context):
    u = make_user(username="lp_user", role="admin")
    make_user(username="nb_requester", role="admin")
    _pending_approval(u[0])
    # ① 有待簽：登入後跳出，數字＝真實待簽數
    page, count = _open_after_login(live_server, client, new_context, u)
    assert count == 1
    page.locator(BANNER).wait_for(state="visible", timeout=10000)
    assert page.locator(BANNER + " b").inner_text() == "1"
    # ② 簽掉
    r = client.post("/api/quotations/MQ-NB-PEND-lp_user/approve", headers=_login_headers(client, u), json={})
    assert r.status_code == 200, r.text
    # 模擬別的簽核流程沒把通知標已讀：塞一筆未讀 approval_request（舊實作會因此再跳）
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO notifications (username, type, ref_id, ref_label, message, is_read, created_at) VALUES (?,?,?,?,?,0,?)",
                     (u[0], "approval_request", "MQ-NB-PEND-lp_user", "MQ-NB-PEND-lp_user", "待簽核", datetime.now().isoformat()))
        conn.commit()
    finally:
        conn.close()
    # ③ 再登入（新分頁狀態）：待簽數 0 ⇒ 不跳（橫幅延遲 0.9 秒出現，多等 1.5 秒確認「不會出現」）
    page2, count2 = _open_after_login(live_server, client, new_context, u)
    assert count2 == 0
    page2.wait_for_timeout(1500)
    assert page2.locator(BANNER).count() == 0, "簽過了，登入還是跳「待簽核」橫幅"
