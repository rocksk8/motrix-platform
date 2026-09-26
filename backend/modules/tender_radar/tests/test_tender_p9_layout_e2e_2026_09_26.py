# -*- coding: utf-8 -*-
"""D4 後半（CUSTOMIZATION-SPEC §8.3）：用排版器調整內建模組（標案雷達）的列表欄位與表單區塊，並依角色套用。

一條細線（瀏覽器操作；斷言打在伺服器狀態＝ui_definitions、user_list_prefs、/api/layout 的回應，畫面只當作「套上了」的證據）：
  ① 超級管理員在標案雷達頁按「編輯版面」（同一頁）：列表隱藏一欄、拖曳一欄、改一欄標題；表單把欄位移到另一個區塊、區塊改名
     ⇒ 存草稿 ⇒ 看差異 ⇒ 發布（公司預設）
  ② 同一個排版器切到「角色：管理員」（以公司預設為起點）再多隱藏一欄 ⇒ 發布；右上角以「業務」「管理員」預覽
  ③ 管理員看到角色版面；業務（另一個角色）看到的仍然是公司預設
  ④ 公司預設再發布一版 ⇒ 還原第 1 版 ⇒ 畫面跟著回去
另外：個人層只能隱藏可顯示欄位、調整順序（核心欄位與上層隱藏的欄位碰不到）；發布被後端擋下時問題標回面板上的那一項；
打 API 排入未登記的點 ⇒ 被拒；手機寬度下發布後的版面可讀、排版器入口不出現。

- 等待一律等終點狀態（<html data-layout-state>、#ml-editor 的 data-busy／data-state、面板 data-busy），不用 sleep。
"""
import json
import re

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._map_tiles import block_tiles  # noqa: E402
from tests._mapiso import no_tile_probe  # noqa: E402,F401  （fixture：頁面會畫地圖）

MOD = "tender_radar"
KEY = "module:" + MOD
PG = MOD + ":tender-radar.html"
COL = PG + "/list:tenders/column:"
PW = "P9-Pass-123"

READY = "() => document.documentElement.dataset.layoutState === 'ready' && document.querySelectorAll('table[data-layout-list=tenders] tbody tr').length > 0"
IDLE = "() => { const e = document.getElementById('ml-editor'); return !!e && e.dataset.busy === '0' }"
ED_STATE = "(s) => { const e = document.getElementById('ml-editor'); return !!e && e.dataset.busy === '0' && e.dataset.state === s }"
HEADS = "() => [...document.querySelectorAll('table[data-layout-list=tenders] thead th')].map(e => e.dataset.col)"


def _db():
    import db
    return db.get_db()


def _seed():
    conn = _db()
    try:
        for i in (1, 2):
            conn.execute("INSERT INTO tenders (case_no, name, org, location, fetched_at) VALUES (?, ?, ?, '台中市', '2026-09-26')",
                         ("P9-T-%d" % i, "P9標案%d" % i, "P9機關"))
        conn.execute("INSERT INTO tender_watches (name, keywords, excludes, org, budget_min, budget_max, enabled, created_at, updated_at) "
                     "VALUES ('P9條件', ?, '[]', '', NULL, NULL, 1, '2026-09-26T00:00:00', '2026-09-26T00:00:00')",
                     (json.dumps(["監視器"], ensure_ascii=False),))
        conn.commit()
    finally:
        conn.close()


def _rows(scope, status="published"):
    conn = _db()
    try:
        return [(r["version"], json.loads(r["body_json"])) for r in conn.execute(
            "SELECT version, body_json FROM ui_definitions WHERE kind='layout' AND key=? AND scope=? AND status=? ORDER BY version",
            (KEY, scope, status)).fetchall()]
    finally:
        conn.close()


def _pref(username, list_key="tenders"):
    conn = _db()
    try:
        r = conn.execute("SELECT sort_mode, custom_order FROM user_list_prefs WHERE username=? AND list_key=?",
                         (username, "layout-cols.%s.%s" % (MOD, list_key))).fetchone()
        return (r["sort_mode"], json.loads(r["custom_order"])) if r else None
    finally:
        conn.close()


def _users(make_user):
    make_user(username="p9_boss", password=PW, role="superadmin")
    make_user(username="p9_admin", password=PW, role="admin", modules=["dashboard", "tender_radar", "dev_crm"])
    make_user(username="p9_sales", password=PW, role="sales", modules=["dashboard", "tender_radar", "dev_crm"])


def _open(e2e_browser, base, username, width=1440):
    page = e2e_browser.new_context(viewport={"width": width, "height": 900}).new_page()
    block_tiles(page)
    page.on("dialog", lambda d: d.accept())
    sess = inject_login(page, base, username, PW)
    page.goto(base + "/pages/tender-radar.html")
    page.wait_for_function(READY, timeout=20000)
    return page, sess


def _api(page, base, sess, path, method="GET", body=None):
    h = {"Authorization": "Bearer " + sess["token"], "Content-Type": "application/json"}
    r = page.request.fetch(base + path, method=method, headers=h, data=json.dumps(body) if body is not None else None)
    return r.status, (r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text())


def _editor(page):
    page.get_by_test_id("ml-edit-open").click()
    page.wait_for_function(IDLE)
    page.wait_for_function("() => Alpine.$data(document.getElementById('ml-editor')).work !== null")
    return page.locator("#ml-editor")


def _item(ed, section, field):
    return ed.get_by_test_id(section).locator(".ml-ed__item[data-field=%s]" % field)


def _relabel(loc, text):
    box = loc.locator("input[type=text]").first
    box.fill(text)
    box.blur()


def _scope(page, ed, value):
    # 等「這個範圍載入完成」本身（data-loaded-scope），不只等 busy＝0：busy 在切換的當下可能還沒翻成 1（O7）
    ed.get_by_test_id("ml-scope").select_option(value)
    page.wait_for_function("(v) => { const e = document.getElementById('ml-editor');"
                           " return !!e && e.dataset.busy === '0' && e.dataset.loadedScope === v }", arg=value)


def _publish(page, ed, note):
    ed.get_by_test_id("ml-note").fill(note)
    ed.get_by_test_id("ml-publish").click()
    page.wait_for_function(ED_STATE, arg="published", timeout=15000)


def _order(page, sel):
    return int(page.evaluate("(s) => getComputedStyle(document.querySelector(s)).order", sel))


@pytest.mark.e2e
def test_layout_editor_role_override_and_restore(live_server, make_user, no_tile_probe, e2e_browser):
    _seed()
    _users(make_user)
    boss, boss_sess = _open(e2e_browser, live_server, "p9_boss")
    assert boss.evaluate(HEADS)[:4] == ["marked", "org", "caseNo", "name"]           # 程式預設＝module.json 登記順序
    ed = _editor(boss)

    # ① 公司預設：列表隱藏「地點」、把「截止投標」拖到「機關」前面、「招標方式」改名；表單把「機關」移到「條件」區塊、區塊改名
    _item(ed, "ml-list-tenders", "location").locator("input[type=checkbox]").uncheck()
    _item(ed, "ml-list-tenders", "deadline").drag_to(_item(ed, "ml-list-tenders", "org"))
    _relabel(_item(ed, "ml-list-tenders", "tenderMethod"), "方式")
    assert _item(ed, "ml-list-tenders", "org").locator("input[type=checkbox]").is_disabled()   # 核心欄位不可隱藏
    _item(ed, "ml-form-watch", "org").locator("select").select_option("0")
    _relabel(ed.get_by_test_id("ml-form-watch").locator(".ml-ed__item[data-point-id$='section:scope']"), "範圍")
    heads = boss.evaluate(HEADS)                                                     # 同一頁即時預覽草稿
    assert "location" not in heads and heads[:3] == ["marked", "deadline", "org"], heads

    ed.get_by_test_id("ml-save").click()
    boss.wait_for_function(ED_STATE, arg="saved")
    (_v, draft), = _rows("company", "draft")
    ed.get_by_test_id("ml-diff-btn").click()
    diff = ed.get_by_test_id("ml-diff").inner_text()
    assert "「地點」：隱藏" in diff and "「方式」" in diff and "範圍" in diff, diff
    _publish(boss, ed, "P9 公司版面")
    (v1, body1), = _rows("company")
    assert v1 == 1 and body1 == draft and _rows("company", "draft") == []
    ops = body1["ops"]
    assert {"op": "hide", "target": COL + "location"} in ops
    assert {"op": "relabel", "target": COL + "tenderMethod", "label": "方式"} in ops
    reorder = [o for o in ops if o["op"] == "reorder" and o["target"] == PG + "/list:tenders"][0]
    assert reorder["order"][:3] == [COL + "marked", COL + "deadline", COL + "org"]
    assert {"op": "move", "target": PG + "/form:watch/field:org", "to": PG + "/form:watch/section:main", "index": 3} in ops
    assert {"op": "relabel", "target": PG + "/form:watch/section:scope", "label": "範圍"} in ops

    # ② 角色覆寫（管理員）：以公司預設為起點，多隱藏「採購性質」
    _scope(boss, ed, "role:admin")
    assert "以公司預設為起點" in ed.inner_text()
    _item(ed, "ml-list-tenders", "procurementType").locator("input[type=checkbox]").uncheck()
    _publish(boss, ed, "管理員少一欄")
    (rv, rbody), = _rows("role:admin")
    assert rv == 1 and {"op": "hide", "target": COL + "procurementType"} in rbody["ops"]
    assert {"op": "hide", "target": COL + "location"} in rbody["ops"]

    # 右上角「以角色預覽」：業務＝公司預設、管理員＝角色版面
    ed.get_by_test_id("ml-preview-role").select_option("sales")
    boss.wait_for_function(IDLE)
    heads = boss.evaluate(HEADS)
    assert "procurementType" in heads and "location" not in heads, heads
    ed.get_by_test_id("ml-preview-role").select_option("admin")
    boss.wait_for_function(IDLE)
    assert "procurementType" not in boss.evaluate(HEADS)
    ed.get_by_test_id("ml-close").click()

    # ③ 伺服器：管理員＝角色版面、業務＝公司預設
    admin, admin_sess = _open(e2e_browser, live_server, "p9_admin")
    sales, sales_sess = _open(e2e_browser, live_server, "p9_sales")
    assert _api(admin, live_server, admin_sess, "/api/layout/" + MOD)[1]["source"] == "role:admin v1"
    assert _api(sales, live_server, sales_sess, "/api/layout/" + MOD)[1]["source"] == "company v1"
    a_heads, s_heads = admin.evaluate(HEADS), sales.evaluate(HEADS)
    assert "procurementType" not in a_heads and "location" not in a_heads, a_heads
    assert "procurementType" in s_heads and "location" not in s_heads, s_heads
    assert sales.locator("th[data-col=tenderMethod]").inner_text() == "方式"
    assert sales.locator("[data-layout-section='watch:scope']").inner_text() == "範圍"
    # 表單：機關移到「條件」區塊（CSS order 在「範圍」區塊標題之前）
    o = {k: _order(sales, sel) for k, sel in (("excludes", "[data-layout-field='watch:excludes']"),
                                               ("org", "[data-layout-field='watch:org']"),
                                               ("scope", "[data-layout-section='watch:scope']"),
                                               ("budgetMin", "[data-layout-field='watch:budgetMin']"))}
    assert o["excludes"] < o["org"] < o["scope"] < o["budgetMin"], o                 # 條件：…排除詞、機關 ｜範圍：預算…
    assert sales.get_by_test_id("ml-edit-open").count() == 0                         # 非超級管理員沒有排版器

    # ④ 公司預設發布第 2 版（地點打開）⇒ 還原第 1 版 ⇒ 畫面跟著回去
    ed = _editor(boss)
    _scope(boss, ed, "company")                                                      # 面板記得上次的範圍（角色）⇒ 切回公司
    _item(ed, "ml-list-tenders", "location").locator("input[type=checkbox]").check()
    _publish(boss, ed, "地點打開")
    assert [v for v, _ in _rows("company")] == [1, 2]
    # O7：只看「多了一版」不夠——第 2 版必須恰好是「第 1 版拿掉地點的 hide」（擋「與第 1 版相同」也擋「整個空了」，AUDIT-B-host-O7 S-2）
    want_v2 = [o for o in ops if o != {"op": "hide", "target": COL + "location"}]
    assert _rows("company")[1][1]["ops"] == want_v2, _rows("company")[1][1]["ops"]
    sales.reload()
    sales.wait_for_function(READY)
    assert "location" in sales.evaluate(HEADS)
    ed.locator(".ml-ed__ver[data-version='1'] button").click()
    boss.wait_for_function(ED_STATE, arg="restored")
    rows = _rows("company")
    assert [v for v, _ in rows] == [1, 2, 3] and rows[2][1] == rows[0][1]            # 還原＝舊版再發布成新版，不改歷史
    sales.reload()
    sales.wait_for_function(READY)
    assert "location" not in sales.evaluate(HEADS)
    assert _api(sales, live_server, sales_sess, "/api/layout/" + MOD)[1]["source"] == "company v3"
    ed.get_by_test_id("ml-close").click()
    assert "location" not in boss.evaluate(HEADS)                                    # 超級管理員自己的畫面（公司 v3）也回去


@pytest.mark.e2e
def test_personal_layer_only_hides_and_reorders(live_server, make_user, no_tile_probe, e2e_browser):
    _seed()
    _users(make_user)
    boss, boss_sess = _open(e2e_browser, live_server, "p9_boss")
    for path, body in (("/draft", {"body": {"ops": [{"op": "hide", "target": COL + "location"}]}}), ("/publish", {})):
        st, _ = _api(boss, live_server, boss_sess, "/api/definitions/layout/%s%s" % (KEY, path),
                     "PUT" if path == "/draft" else "POST", body)
        assert st == 200
    sales, sales_sess = _open(e2e_browser, live_server, "p9_sales")
    panel = sales.get_by_test_id("ml-personal-tenders")
    panel.get_by_test_id("ml-personal-open").click()
    rows = panel.locator(".ml-pop__row")
    fields = rows.evaluate_all("els => els.map(e => e.dataset.field)")
    assert "location" not in fields                                                  # 公司隱藏的欄位個人打不開
    assert panel.locator(".ml-pop__row[data-field=org] input").is_disabled()         # 核心欄位不可隱藏
    panel.locator(".ml-pop__row[data-field=publishedAt] input").uncheck()
    panel.locator(".ml-pop__row[data-field=name] button[title=上移]").click()
    with sales.expect_response(lambda r: "/api/list-prefs/" in r.url and r.request.method == "PUT") as resp:
        panel.get_by_test_id("ml-personal-save").click()
    assert resp.value.status == 200
    sales.wait_for_function("() => document.querySelector('[data-testid=ml-personal-tenders]').dataset.busy === '0'")
    mode, order = _pref("p9_sales")
    assert mode == "columns" and "-publishedAt" in order and order.index("name") < order.index("caseNo"), order
    heads = sales.evaluate(HEADS)
    assert "publishedAt" not in heads and heads.index("name") < heads.index("caseNo"), heads
    assert _rows("company") and len(_rows("company")) == 1                           # 個人層不動公司／角色層

    # 反向控制：直接打清單偏好企圖隱藏核心欄位、打開公司隱藏的欄位 ⇒ 套用時不理
    st, _ = _api(sales, live_server, sales_sess, "/api/list-prefs/layout-cols.%s.tenders" % MOD, "PUT",
                 {"sortMode": "columns", "sortDir": "desc", "customOrder": ["-org", "location", "-caseNo"]})
    assert st == 200
    sales.reload()
    sales.wait_for_function(READY)
    heads = sales.evaluate(HEADS)
    assert "org" in heads and "caseNo" in heads and "location" not in heads, heads
    # 非超級管理員不能寫公司／角色層
    st, _ = _api(sales, live_server, sales_sess, "/api/definitions/layout/%s/draft" % KEY, "PUT", {"body": {"ops": []}})
    assert st == 403
    # 別人的畫面不受業務的個人設定影響
    admin, _ = _open(e2e_browser, live_server, "p9_admin")
    assert "publishedAt" in admin.evaluate(HEADS)


@pytest.mark.e2e
def test_publish_problems_are_marked_on_the_item_and_unregistered_points_are_refused(live_server, make_user, no_tile_probe,
                                                                                      e2e_browser):
    _seed()
    _users(make_user)
    boss, boss_sess = _open(e2e_browser, live_server, "p9_boss")
    # 反向控制：打 API 排入未登記的點 ⇒ 發布 422、沒有發布版
    st, _ = _api(boss, live_server, boss_sess, "/api/definitions/layout/%s/draft" % KEY, "PUT",
                 {"body": {"ops": [{"op": "hide", "target": COL + "ghostColumn"}]}})
    assert st == 200
    st, body = _api(boss, live_server, boss_sess, "/api/definitions/layout/%s/publish" % KEY, "POST", {})
    assert st == 422 and body["problems"][0]["path"] == "ops[0].target", body
    assert _rows("company") == []
    _api(boss, live_server, boss_sess, "/api/definitions/layout/%s/draft" % KEY, "DELETE")

    # 繞過面板的檢查送出空白標籤 ⇒ 後端 check_layout 擋下 ⇒ 問題標在那一項上、沒有發布
    ed = _editor(boss)
    boss.evaluate("() => { const d = Alpine.$data(document.getElementById('ml-editor'));"
                  " d.work.lists.tenders.columns.find(c => c.field === 'location').label = '  ' }")
    ed.get_by_test_id("ml-publish").click()
    boss.wait_for_function(ED_STATE, arg="problems")
    bad = _item(ed, "ml-list-tenders", "location")
    assert "is-bad" in bad.get_attribute("class")
    assert "label" in ed.locator(".ml-ed__prob:visible").first.inner_text()
    assert _rows("company") == []


@pytest.mark.e2e
def test_published_layout_is_readable_on_mobile(live_server, make_user, no_tile_probe, e2e_browser):
    _seed()
    _users(make_user)
    boss, boss_sess = _open(e2e_browser, live_server, "p9_boss")
    for path, body in (("/draft", {"body": {"ops": [{"op": "hide", "target": COL + "location"},
                                                     {"op": "relabel", "target": COL + "tenderMethod", "label": "方式"}]}}),
                       ("/publish", {})):
        assert _api(boss, live_server, boss_sess, "/api/definitions/layout/%s%s" % (KEY, path),
                    "PUT" if path == "/draft" else "POST", body)[0] == 200
    phone, _ = _open(e2e_browser, live_server, "p9_sales", width=390)
    heads = phone.evaluate(HEADS)
    assert "location" not in heads and phone.locator("th[data-col=tenderMethod]").inner_text() == "方式"
    # 頁面本身不橫向捲動（寬表格在 .table-scroll 裡捲）
    assert phone.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")
    mboss, _ = _open(e2e_browser, live_server, "p9_boss", width=390)
    assert not mboss.get_by_test_id("ml-edit-open").is_visible()                    # 排版器只在桌機


def test_page_fallback_columns_match_module_registration():
    """頁面的 fallback（版面讀不到時的欄位順序）必須等於 module.json 登記的列表欄——
    CUSTOMIZATION-SPEC §3.9「⚠ 未守門：登記內容與頁面實際畫面一致」在本頁改由登記渲染後的守門。"""
    import re
    from core import source_tree
    from pathlib import Path
    html = source_tree.page_file("tender-radar.html").read_text(encoding="utf-8")
    man = json.loads((Path(__file__).resolve().parents[1] / "module.json").read_text(encoding="utf-8"))
    lists = {lst["key"]: [c["field"] for c in lst["columns"]]
             for pg in man["customization"]["pages"] if pg["page"] == "tender-radar.html" for lst in pg["lists"]}
    block = re.search(r"fallback: \{ lists: \{(.*?)\} \}", html, re.S).group(1)
    got = {k: re.findall(r"'([A-Za-z]+)'", v) for k, v in re.findall(r"(\w+): \[([^\]]*)\]", block)}
    assert got == lists
    # 每一個登記的欄都有畫法（x-if 分支），沒有登記的欄不會被畫
    for field in lists["tenders"]:
        assert "c.field === '%s'" % field in html, field


# ── O7：切換範圍的載入期間（2026-09-26 第五班全量抓到：發布第 2 版後表頭仍是第 1 版）───────────────────
# 成因：載入中編輯區仍可操作，載入回來整份覆蓋 ⇒ 修改靜默消失、照樣發布成與上一版相同的一版；
#       連切兩次時，較早發出、較晚回來的回應蓋掉後來選的範圍。

ED_ATTR = "() => { const e = document.getElementById('ml-editor'); return e ? {busy: e.dataset.busy, scope: e.dataset.scope," \
          " loaded: e.dataset.loadedScope, done: +e.dataset.loadsDone} : null }"


def _hold(page, scope):
    """把 GET /api/definitions/layout/…?scope=<scope> 攔住，直到呼叫回傳的 release()。"""
    held = []
    enc = scope.replace(":", "%3A")
    page.route(lambda url: "/api/definitions/layout/" in url and ("scope=" + enc) in url, lambda route: held.append(route))

    def release():
        while not held:
            page.wait_for_timeout(50)
        for r in held:
            r.continue_()
    return held, release


@pytest.mark.e2e
def test_editor_is_not_editable_while_a_scope_is_loading(live_server, make_user, no_tile_probe, e2e_browser):
    _seed()
    _users(make_user)
    boss, _ = _open(e2e_browser, live_server, "p9_boss")
    ed = _editor(boss)
    held, release = _hold(boss, "role:admin")
    ed.get_by_test_id("ml-scope").select_option("role:admin")
    boss.wait_for_function("() => document.getElementById('ml-editor').dataset.busy === '1'")
    box = _item(ed, "ml-list-tenders", "location").locator("input[type=checkbox]")
    before = box.is_checked()
    assert box.is_visible() and boss.evaluate("() => document.querySelector('#ml-editor .ml-ed__body').inert") is True
    from playwright.sync_api import TimeoutError as PwTimeout
    with pytest.raises(PwTimeout):                      # 載入中：點不到（inert），不可以改到即將被覆蓋的舊狀態
        box.click(timeout=1500)
    release()
    boss.wait_for_function("() => { const e = document.getElementById('ml-editor');"
                           " return e.dataset.busy === '0' && e.dataset.loadedScope === 'role:admin' }")
    assert box.is_checked() == before
    box.click()                                         # 正對照：載入完成後可以改
    assert box.is_checked() != before


@pytest.mark.e2e
def test_a_late_response_for_an_earlier_scope_does_not_overwrite_the_later_choice(live_server, make_user, no_tile_probe,
                                                                                   e2e_browser):
    _seed()
    _users(make_user)
    boss, _ = _open(e2e_browser, live_server, "p9_boss")
    ed = _editor(boss)
    n0 = boss.evaluate(ED_ATTR)["done"]
    held, release = _hold(boss, "role:admin")
    ed.get_by_test_id("ml-scope").select_option("role:admin")
    boss.wait_for_function("() => document.getElementById('ml-editor').dataset.busy === '1'")
    ed.get_by_test_id("ml-scope").select_option("company")
    boss.wait_for_function("(n) => +document.getElementById('ml-editor').dataset.loadsDone >= n + 1", arg=n0)
    assert boss.evaluate(ED_ATTR)["loaded"] == "company"
    release()                                           # 較早的 role:admin 回應現在才回來
    boss.wait_for_function("(n) => +document.getElementById('ml-editor').dataset.loadsDone >= n + 2", arg=n0)
    st = boss.evaluate(ED_ATTR)
    assert st["scope"] == "company" and st["loaded"] == "company" and st["busy"] == "0", st
    assert "以程式預設為起點" in ed.inner_text()          # 公司還沒有版面 ⇒ 程式預設；不是「以公司預設為起點」（角色的起點說明）



@pytest.mark.e2e
def test_role_preview_cannot_unlock_the_editor_while_a_scope_is_loading(live_server, make_user, no_tile_probe, e2e_browser):
    """AUDIT-B-host-O7 M-1：載入與預覽原本共用一個 busy ⇒ 載入中切「以角色預覽」，預覽結束就解鎖，O7 重開。"""
    _seed()
    _users(make_user)
    boss, _ = _open(e2e_browser, live_server, "p9_boss")
    ed = _editor(boss)
    held, release = _hold(boss, "role:admin")
    ed.get_by_test_id("ml-scope").select_option("role:admin")
    boss.wait_for_function("() => document.getElementById('ml-editor').dataset.busy === '1'")
    assert ed.get_by_test_id("ml-preview-role").is_disabled()          # 載入中不能切預覽
    # 就算繞過畫面直接呼叫預覽（例如舊版的事件已排入），也不可以解鎖
    boss.evaluate("""async () => { const c = Alpine.$data(document.getElementById('ml-editor'));
        c.previewRole = 'sales'; await c.previewAs(); c.previewRole = '' }""")
    st = boss.evaluate(ED_ATTR)
    assert st["busy"] == "1" and boss.evaluate("() => document.querySelector('#ml-editor .ml-ed__body').inert") is True, st
    assert ed.get_by_test_id("ml-publish").is_disabled()
    release()
    boss.wait_for_function("() => { const e = document.getElementById('ml-editor');"
                           " return e.dataset.busy === '0' && e.dataset.loadedScope === 'role:admin' }")


@pytest.mark.e2e
def test_a_failed_scope_load_keeps_the_editor_locked_and_says_so(live_server, make_user, no_tile_probe, e2e_browser):
    """AUDIT-B-host-O7 S-1：讀不到 ≠ 沒有版面——不可以顯示程式預設讓人照樣發布；鎖住並說明。"""
    _seed()
    _users(make_user)
    boss, _ = _open(e2e_browser, live_server, "p9_boss")
    ed = _editor(boss)
    n0 = boss.evaluate(ED_ATTR)["done"]
    boss.route(lambda url: "/api/definitions/layout/" in url and "scope=role%3Aadmin" in url,
               lambda route: route.fulfill(status=500, body='{"detail":"x"}', content_type="application/json"))
    ed.get_by_test_id("ml-scope").select_option("role:admin")
    boss.wait_for_function("(n) => +document.getElementById('ml-editor').dataset.loadsDone >= n + 1", arg=n0)
    e = boss.evaluate("() => { const e = document.getElementById('ml-editor'); return {err: e.dataset.loadError, busy: e.dataset.busy,"
                      " inert: e.querySelector('.ml-ed__body').inert, state: e.dataset.state} }")
    assert e == {"err": "1", "busy": "1", "inert": True, "state": "error"}, e
    assert ed.get_by_test_id("ml-publish").is_disabled()
    assert "讀取「role:admin」的版面失敗" in ed.inner_text()



@pytest.mark.e2e
def test_a_publish_whose_response_is_lost_unlocks_and_says_the_result_is_unknown(live_server, make_user, no_tile_probe,
                                                                                  e2e_browser):
    """AUDIT-B-host-O7 S-3：發布的回應沒回來（斷線）⇒ 不可以卡在 busy；要說「結果不明」並解鎖。"""
    _seed()
    _users(make_user)
    boss, _ = _open(e2e_browser, live_server, "p9_boss")
    ed = _editor(boss)
    _item(ed, "ml-list-tenders", "location").locator("input[type=checkbox]").uncheck()
    boss.route(lambda url: "/api/definitions/layout/" in url and "/publish" in url, lambda route: route.abort())
    ed.get_by_test_id("ml-note").fill("斷線")
    ed.get_by_test_id("ml-publish").click()
    boss.wait_for_function(ED_STATE, arg="error")
    assert "發布結果不明" in ed.inner_text()
    assert not ed.get_by_test_id("ml-publish").is_disabled()        # 解鎖：可以再試


@pytest.mark.e2e
def test_scope_cannot_be_switched_while_an_action_is_running(live_server, make_user, no_tile_probe, e2e_browser):
    """AUDIT-B-host-O7 O-2：發布進行中切範圍 ⇒ 後半段用新範圍、訊息標錯；進行中範圍下拉停用。"""
    _seed()
    _users(make_user)
    boss, _ = _open(e2e_browser, live_server, "p9_boss")
    ed = _editor(boss)
    _item(ed, "ml-list-tenders", "location").locator("input[type=checkbox]").uncheck()
    held = []
    boss.route(lambda url: "/api/definitions/layout/" in url and "/publish" in url, lambda route: held.append(route))
    ed.get_by_test_id("ml-note").fill("進行中")
    ed.get_by_test_id("ml-publish").click()
    while not held:
        boss.wait_for_timeout(50)
    assert ed.get_by_test_id("ml-scope").is_disabled()
    held[0].continue_()
    boss.wait_for_function(ED_STATE, arg="published", timeout=15000)
    assert not ed.get_by_test_id("ml-scope").is_disabled()
    # 讀動作的結果訊息（不讀整個面板：範圍下拉的選項文字本來就有「公司預設」，永遠成立，AUDIT-B-host-O7 O-4）
    assert re.match(r"^已發布第 \d+ 版（公司預設）$", ed.get_by_test_id("ml-msg").inner_text()), ed.get_by_test_id("ml-msg").inner_text()


@pytest.mark.e2e
def test_a_failed_scope_load_can_be_retried(live_server, make_user, no_tile_probe, e2e_browser):
    """AUDIT-B-host-O7 O-3：選同一個範圍不會觸發 change ⇒ 載入失敗要有「重試」。"""
    _seed()
    _users(make_user)
    boss, _ = _open(e2e_browser, live_server, "p9_boss")
    ed = _editor(boss)
    fail = {"on": True}

    def handler(route):
        if fail["on"]:
            route.fulfill(status=500, body='{"detail":"x"}', content_type="application/json")
        else:
            route.continue_()
    boss.route(lambda url: "/api/definitions/layout/" in url and "scope=role%3Aadmin" in url, handler)
    ed.get_by_test_id("ml-scope").select_option("role:admin")
    boss.wait_for_function("() => document.getElementById('ml-editor').dataset.loadError === '1'")
    fail["on"] = False
    ed.get_by_test_id("ml-retry").click()
    boss.wait_for_function("() => { const e = document.getElementById('ml-editor');"
                           " return e.dataset.busy === '0' && e.dataset.loadedScope === 'role:admin' && e.dataset.loadError === '0' }")
    assert not ed.get_by_test_id("ml-retry").is_visible()
