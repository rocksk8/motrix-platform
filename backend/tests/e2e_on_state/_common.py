# -*- coding: utf-8 -*-
"""ON 狀態真瀏覽器 e2e 的共用工具（tests/e2e_on_state/；T62 版面線）。

約定（沿用 tests/test_e2e_*.py 的慣例）：fixture `live_server`（共用伺服器＋每題一份新庫）、`make_user`、`e2e_browser`／`new_context`、
`tests._e2e_login.inject_login`；題目標 `@pytest.mark.e2e`；找不到 playwright 就略過。

⚠️ 這個目錄的題「已寫、未跑」：選擇器與種子資料是對照頁面原始碼寫的，第一次實跑要以畫面為準校正。

旗標一律走**真的設定 API**（`POST /api/settings-center/groups/<群組>`，帶 reason）、版面一律走**真的定義 API**
（`PUT …/draft`＋`POST …/publish`）——不直接寫庫，才驗得到「API 開了之後頁面真的變」。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402,F401  （各檔共用匯入點）

DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"
LAYOUT_BASE = "/api/definitions/layout/module:case"
PW = "Test-Pass-123"


# ── HTTP（走 Playwright 的 APIRequestContext，打的就是 live_server）─────────────────────────────
def token_of(ctx, base, user):
    r = ctx.request.post(base + "/api/auth/login", data={"username": user[0], "password": user[1]})
    assert r.ok, r.text()
    return r.json()["token"]


def api(ctx, base, method, path, token, body=None, params=None):
    kw = {"headers": {"Authorization": "Bearer " + token, "Content-Type": "application/json"}}
    if body is not None:
        kw["data"] = json.dumps(body, ensure_ascii=False)
    if params:
        kw["params"] = params
    r = getattr(ctx.request, method.lower())(base + path, **kw)
    try:
        j = r.json()
    except Exception:                                                  # noqa: BLE001
        j = {"raw": r.text()[:300]}
    return r.status, j


def set_flag(ctx, base, token, group, field, value=1):
    """設定中心存一個旗標（立即生效的欄位）。⇒ 回應 JSON。"""
    s, j = api(ctx, base, "POST", "/api/settings-center/groups/" + group, token, {"values": {field: value}, "reason": "e2e on-state"})
    assert s == 200, (group, field, s, j)
    return j


def publish_definition(ctx, base, token, kind, key, body, scope="company"):
    """存草稿 ⇒ 發布（治理關閉時直接生效）。⇒ 發布回應 JSON。"""
    url = "/api/definitions/%s/%s" % (kind, key)
    s0, cur = api(ctx, base, "GET", url, token, params={"scope": scope})
    et = ((cur.get("draft") or {}).get("etag")) if s0 == 200 else None
    s1, j1 = api(ctx, base, "PUT", url + "/draft", token, {"body": body, "base_etag": et}, {"scope": scope})
    assert s1 == 200 and not j1.get("problems"), (kind, key, s1, j1)
    s2, j2 = api(ctx, base, "POST", url + "/publish", token, {"note": "e2e on-state"}, {"scope": scope})
    assert s2 == 200 and j2.get("pending") is not True, (kind, key, s2, j2)
    return j2


def publish_layout(ctx, base, token, ops):
    return publish_definition(ctx, base, token, "layout", "module:case", {"ops": ops})


def pid(page_name, kind, container, item=None):
    """版面點位 id：`case:<頁>/list:<清單>/column:<欄>`、`case:<頁>/form:<表單>/field:<欄>`。"""
    base = "case:%s/%s:%s" % (page_name, kind, container)
    if item is None:
        return base
    return base + "/%s:%s" % ("column" if kind == "list" else "field", item)


# ── 種子資料 ───────────────────────────────────────────────────────────────────────────────────
def seed_case(no, customer="ON狀態客戶", project="ON狀態專案"):
    """一張已成案、有一個階段的案件（案件管理頁用）。"""
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        cur = conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                           (no, "施工", 0, 0, now, now))
        cr = {"payment": {"items": []}, "stages": [{"id": cur.lastrowid, "label": "施工", "done": False}],
              "roles": {"filler": "", "sales": "", "executor": ""},
              "projectTimeline": {"startDate": "", "endDate": "", "status": "on_track"}}
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
                     " deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (no, "已送出", customer, project, 1000, 952, json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False),
                      now, now, "已成案", "2026-08-01"))
        conn.commit()
    finally:
        conn.close()


def seed_draft_quote(no_hint="ON-DRAFT"):
    """一張可編輯的草稿報價單（報價單表單／報價單清單用）：沿用 `_response_keys.seed_every_table` 種的合法資料，再把狀態改成草稿。⇒ 單號。"""
    import db
    from tests.platform import _response_keys as RK
    conn = db.get_db()
    try:
        RK.seed_every_table(conn)
        qn = conn.execute("SELECT quote_no FROM quotations ORDER BY id LIMIT 1").fetchone()[0]
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qn,)).fetchone()[0] or "{}")
        d.setdefault("caseRecord", {})
        d.update({"contactFax": "04-1234-5678", "deliveryLocation": "測試工地"})
        conn.execute("UPDATE quotations SET status='草稿', deal_tag='', customer_name='ON狀態客戶', project_name='ON狀態專案', data_json=? WHERE quote_no=?",
                     (json.dumps(d, ensure_ascii=False), qn))
        conn.commit()
    finally:
        conn.close()
    return qn


def stored_data(qn):
    import db
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qn,)).fetchone()[0] or "{}")
    finally:
        conn.close()


# ── 頁面小工具 ─────────────────────────────────────────────────────────────────────────────────
def open_case(page, base, user, no, tab="biz"):
    inject_login(page, base, user[0], user[1])
    page.goto("%s/pages/case-management.html?q=%s&tab=%s" % (base, no, tab))
    page.wait_for_function("() => %s.selected && %s.selected.quote_no === '%s'" % (DATA_JS, DATA_JS, no), timeout=20000)


def wait_layout_on(page):
    """版面引擎啟動且已套用（旗標 ON 才會成立）。"""
    page.wait_for_function("() => %s.layoutOn === true" % DATA_JS, timeout=15000)


def visible_tab_texts(page, scope_js):
    """依 CSS order 排序、只留看得到的按鈕文字。scope_js：回傳按鈕 NodeList 的 JS 運算式。"""
    return page.evaluate("""() => [...(%s)].filter(b => b.offsetParent !== null)
        .map(b => ({ t: (b.querySelector('span') || b).textContent.trim(), o: parseInt(getComputedStyle(b).order || '0', 10) }))
        .sort((a, b) => a.o - b.o).map(x => x.t)""" % scope_js)


TOP_TABS = "document.querySelectorAll('.cm-tab:not(.cm-subtabs .cm-tab)')"
SUB_TABS = "document.querySelectorAll('.cm-subtabs .cm-tab')"


def y_of(page, text):
    """某個區塊標題的垂直位置（找第一個含該字的 .cm-section-title）。"""
    box = page.locator(".cm-section-title", has_text=text).first.bounding_box()
    assert box is not None, text + " 區塊不可見"
    return box["y"]


class Requests:
    """記錄這個分頁打出去的同源請求（method＋路徑＋排序後的查詢字串），給 OFF 狀態的 golden 用。"""

    def __init__(self, page, base):
        self.base, self.items = base, []
        page.on("request", self._on)

    def _on(self, req):
        if req.resource_type in ("font", "image", "media", "websocket") or not req.url.startswith(self.base):
            return
        from urllib.parse import parse_qsl, urlsplit
        u = urlsplit(req.url)
        q = "&".join("%s=%s" % kv for kv in sorted(parse_qsl(u.query)))
        self.items.append("%s %s%s" % (req.method, u.path, ("?" + q) if q else ""))

    def sorted(self):
        return sorted(self.items)
