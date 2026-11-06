# -*- coding: utf-8 -*-
"""歷史紀錄頁的簽核標籤篩選（簽核二擇一 S6）：下拉選「知情核准」／「自改自簽」⇒ 請求帶 `tag`、清單只剩該標籤的列並顯示標籤徽章；清除後回到全部。
後端規則（標籤只命中各自 action、未知標籤 400、與其他篩選 AND）在 modules/case/tests/test_acceptance_s6_2026_11_07.py。"""
import json
from datetime import datetime, timedelta

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402

pytestmark = requires_module("case", "標籤字面由 M01 的簽核端點寫入")


def _seed():
    import db
    c = db.get_db()
    try:
        at = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT00:00:01")
        rows = [("quotation.approve", "MQ-202611-701", {"flags": ["reconfirm"], "choice": "keep", "tag": "informed", "confirmNote": "看過"}),
                ("quotation.approve", "MQ-202611-702", {"allDone": True}),
                ("quotation.review_edit", "MQ-202611-703", {"changes": [], "tag": "self_edit_sign", "selfEditSign": True}),
                ("quotation.review_edit", "MQ-202611-704", {"changes": []})]
        for act, case, det in rows:
            c.execute("INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail,module,case_no,ref_no,result,reason_code,status_code)"
                      " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (at, 1, "seed", "種子", act, "quotation", case, case, json.dumps(det, ensure_ascii=False), "quotation", case, case, "ok", "", 0))
        c.commit()
    finally:
        c.close()


def _cases(page):
    return page.evaluate("() => [...document.querySelectorAll('.tl-item .tl-label')].map(e => e.innerText).filter(t => /^MQ-/.test(t))")


@pytest.mark.e2e
def test_tag_select_filters_the_list_and_shows_the_badge(live_server, make_user, e2e_browser):
    u, p = make_user(username="alt_sa", role="superadmin", modules=[])
    _seed()
    page = e2e_browser.new_page()
    errors, reqs = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: reqs.append(r.url) if "/api/audit-log?" in r.url or r.url.endswith("/api/audit-log") else None)
    inject_login(page, live_server, u, p)
    page.goto(live_server + "/pages/audit-log.html")
    page.wait_for_function("() => document.querySelectorAll('.tl-item').length >= 4", timeout=20000)

    page.select_option('select[title="簽核標籤"]', "informed")
    page.wait_for_function("() => document.querySelectorAll('.tl-item').length === 1", timeout=10000)
    assert _cases(page) == ["MQ-202611-701"] and any("tag=informed" in r for r in reqs[-3:]), reqs
    assert "知情核准" in page.inner_text(".tl-item")

    page.select_option('select[title="簽核標籤"]', "self_edit_sign")
    page.wait_for_function("() => document.querySelectorAll('.tl-item').length === 1 && document.querySelector('.tl-item').innerText.includes('MQ-202611-703')", timeout=10000)
    assert "自改自簽" in page.inner_text(".tl-item") and any("tag=self_edit_sign" in r for r in reqs[-3:])

    page.get_by_text("清除", exact=True).click()                       # 清除：標籤也回「所有標籤」、清單回到全部
    page.wait_for_function("() => document.querySelectorAll('.tl-item').length >= 4", timeout=10000)
    assert page.eval_on_selector('select[title="簽核標籤"]', "e => e.value") == ""
    assert not errors, errors
