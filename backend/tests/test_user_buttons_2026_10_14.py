# -*- coding: utf-8 -*-
"""T61 S6：使用者自訂按鈕（供應商頁工具列先導）——契約題。設計：docs/platform/plans/T61-S6-ACTION-CATALOG-DESIGN.md。

證明的事：
1. 旗標 `builder_actions.enabled` 關閉（預設）＝今天：按鈕端點回空、目錄／預覽 404、頁面不多任何東西。
2. 驗證器：只有 navigate／export；不認得的鍵、外部網址、javascript:、不在選單上的頁面、排除頁、未登記的匯出、危險標籤、超量、未知插槽都擋；正對照合法定義通過。
3. 按鈕**不授權**：沒有匯出權限的人，伺服器端的按鈕清單就不含那顆匯出（逐顆用檢視者權限過濾）；直接打匯出端點照樣 403（有沒有按鈕都一樣）；
   端點路徑來自目錄、不來自使用者存的定義。
4. 預覽唯讀（不寫任何資料）、套指定使用者的真實權限、只有最高管理者。
5. 頁面插槽與插槽表雙向一致（附正對照）；按鈕文字用 x-text 渲染。
"""
import json
import re
from pathlib import Path

import pytest

from core import source_tree

ROOT = Path(__file__).resolve().parents[2]
KIND = "user_buttons"
DEF = "/api/definitions/user_buttons/module:supply"
SLOT = "suppliers.html/toolbar"
EXPORT_ID = "subcontract:roster"


def _login(client, make_user, name, role, modules=None):
    u, p = make_user(name, "Lay-Pass-123", role=role, modules=modules)[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _flag(on):
    import db
    from helpers import settings_registry as SR
    conn = db.get_db()
    try:
        SR.publish("builder_actions", {"enabled": on}, reason="測試", user="ub_test", conn=conn)
        conn.commit()
    finally:
        conn.close()
    SR.invalidate("builder_actions")


def _validate(client, h, buttons, key="module:supply", extra=None):
    body = {"buttons": buttons}
    body.update(extra or {})
    r = client.post("/api/definitions/user_buttons/%s/validate" % key, headers=h, json={"body": body})
    assert r.status_code == 200, r.text
    return r.json()["problems"]


def _publish(client, h, buttons):
    r = client.put(DEF + "/draft", headers=h, params={"scope": "company"}, json={"body": {"buttons": buttons}})
    assert r.status_code == 200 and not r.json().get("problems"), r.text
    r = client.post(DEF + "/publish", headers=h, params={"scope": "company"}, json={"note": "t"})
    assert r.status_code == 200, r.text


def _nav(page, key="b1", label="開頁"):
    return {"key": key, "slot": SLOT, "label": label, "action": {"type": "navigate", "page": page}}


def _exp(key="b2", label="外包名冊", export=EXPORT_ID):
    return {"key": key, "slot": SLOT, "label": label, "action": {"type": "export", "export": export}}


def _boss_pages(client, h):
    _flag(True)
    return [p["page"] for p in client.get("/api/user-buttons/catalog", headers=h).json()["pages"]]


# ── 1. 旗標關閉 ────────────────────────────────────────────────────────────
def test_flag_default_off_everything_is_empty_or_404(client, make_user):
    from helpers import settings_registry as SR
    assert SR.get("builder_actions", "enabled") is False
    h = _login(client, make_user, "ub_boss", "superadmin")
    r = client.get("/api/user-buttons/supply/suppliers.html", headers=h)
    assert r.status_code == 200 and r.json() == {"enabled": False, "buttons": []}
    assert client.get("/api/user-buttons/catalog", headers=h).status_code == 404
    assert client.post("/api/user-buttons/supply/suppliers.html/preview", headers=h, json={"buttons": []}).status_code == 404
    assert client.get("/api/user-buttons/supply/suppliers.html").status_code == 401
    assert client.get("/api/user-buttons/supply/no_such.html", headers=h).status_code == 404       # 不是登記的頁面


def test_flag_off_published_definition_is_not_served(client, make_user):
    h = _login(client, make_user, "ub_boss1", "superadmin")
    pages = _boss_pages(client, h)
    _publish(client, h, [_nav(pages[0])])
    _flag(False)
    assert client.get("/api/user-buttons/supply/suppliers.html", headers=h).json() == {"enabled": False, "buttons": []}


# ── 2. 驗證器 ──────────────────────────────────────────────────────────────
def test_validator_accepts_a_legal_definition(client, make_user):
    h = _login(client, make_user, "ub_boss2", "superadmin")
    pages = _boss_pages(client, h)
    assert _validate(client, h, [_nav(pages[0]), _exp()]) == []
    assert _validate(client, h, []) == []


@pytest.mark.parametrize("mutate,needle", [
    (lambda b: b["action"].update(type="post"), "動作類型只能是"),
    (lambda b: b["action"].update(type="navigate", href="https://evil.example"), "不認得的鍵"),
    (lambda b: b["action"].update(url="javascript:alert(1)"), "不認得的鍵"),
    (lambda b: b["action"].update(page="https://evil.example/x.html"), "不是可開啟的頁面"),
    (lambda b: b["action"].update(page="javascript:alert(1)"), "不是可開啟的頁面"),
    (lambda b: b["action"].update(page="login.html"), "不是可開啟的頁面"),
    (lambda b: b["action"].update(page="no-such-page.html"), "不是可開啟的頁面"),
    (lambda b: b["action"].update(page="suppliers.html?x=1"), "不是可開啟的頁面"),
    (lambda b: b.update(label="<img src=x onerror=alert(1)>"), "不可含"),
    (lambda b: b.update(label='he said "hi"'), "不可含"),
    (lambda b: b.update(label="字" * 21), "最多 20 字"),
    (lambda b: b.update(label="   "), "不可以空白"),
    (lambda b: b.update(slot="suppliers.html/footer"), "不是登記的插槽"),
    (lambda b: b.update(slot="customers.html/toolbar"), "不是登記的插槽"),
    (lambda b: b.update(key="x1"), "b 加數字"),
    (lambda b: b.update(onclick="alert(1)"), "不認得的鍵"),
])
def test_validator_rejects_navigate_variants(client, make_user, mutate, needle):
    h = _login(client, make_user, "ub_boss3", "superadmin")
    pages = _boss_pages(client, h)
    b = _nav(pages[0])
    mutate(b)
    probs = _validate(client, h, [b])
    assert any(needle in p["message"] for p in probs), probs


@pytest.mark.parametrize("export,needle", [
    ("nope:roster", "不是已登記的匯出"),
    ("subcontract:nope", "不是已登記的匯出"),
    ("/api/contractors/export", "不是已登記的匯出"),
    ("POST /api/quotations", "不是已登記的匯出"),
])
def test_validator_rejects_exports_that_are_not_in_the_catalog(client, make_user, export, needle):
    h = _login(client, make_user, "ub_boss4", "superadmin")
    _boss_pages(client, h)
    probs = _validate(client, h, [_exp(export=export)])
    assert any(needle in p["message"] for p in probs), probs


def test_validator_limits_and_module_and_top_level_keys(client, make_user):
    h = _login(client, make_user, "ub_boss5", "superadmin")
    pages = _boss_pages(client, h)
    seven = [_nav(pages[0], key="b%d" % i, label="按鈕%d" % i) for i in range(1, 8)]
    assert any("每個插槽最多" in p["message"] for p in _validate(client, h, seven))
    dup = [_nav(pages[0]), _nav(pages[0])]
    assert any("重複" in p["message"] for p in _validate(client, h, dup))
    assert any("不認得的鍵" in p["message"] for p in _validate(client, h, [], extra={"script": "x"}))
    assert _validate(client, h, [], key="module:no_such_module")[0]["message"].startswith("模組未載入")
    r = client.post("/api/definitions/user_buttons/notmodule/validate", headers=h, json={"body": {"buttons": []}})
    assert r.json()["problems"][0]["message"].startswith("key 必須是")


# ── 3. 按鈕不授權 ──────────────────────────────────────────────────────────
def _users(client, make_user):
    boss = _login(client, make_user, "ub_boss6", "superadmin")
    low = _login(client, make_user, "ub_low", "sales", modules=[])
    holder = _login(client, make_user, "ub_holder", "admin", modules=["contractor_list", "procurement"])
    return boss, low, holder


def test_server_filters_the_button_list_per_viewer_and_buttons_do_not_widen_access(client, make_user):
    boss, low, holder = _users(client, make_user)
    _flag(True)
    from helpers import user_buttons as UB
    low_pages = set(UB._nav_pages([], False))                                         # noqa: SLF001
    cat = client.get("/api/user-buttons/catalog", headers=boss).json()
    only_boss = [p["page"] for p in cat["pages"] if p["page"] not in low_pages]
    assert only_boss, "測試前提：要有一頁最高管理者看得到、低權限者看不到"
    assert any(e["id"] == EXPORT_ID for e in cat["exports"])
    # 直接打匯出端點：低權限 403（發布按鈕之前）
    assert client.get("/api/contractors/export", headers=low).status_code == 403
    _publish(client, boss, [_nav(only_boss[0], key="b1", label="只有老闆能開"), _exp(key="b2")])
    # 伺服器端清單：低權限者看不到那兩顆；老闆兩顆都有；持有 contractor_list 者有匯出
    got = lambda h: client.get("/api/user-buttons/supply/suppliers.html", headers=h).json()
    assert got(low) == {"enabled": True, "buttons": []}
    assert [b["key"] for b in got(boss)["buttons"]] == ["b1", "b2"]
    assert [b["key"] for b in got(holder)["buttons"] if b["type"] == "export"] == ["b2"]
    exp = [b for b in got(boss)["buttons"] if b["type"] == "export"][0]
    assert exp["endpoint"] == "/api/contractors/export" and exp["format"] == "xlsx"           # 端點路徑來自目錄
    # 按鈕發布之後，低權限者直接呼叫匯出端點仍是 403（按鈕沒有放寬任何東西）；持有權限者本來就能匯
    assert client.get("/api/contractors/export", headers=low).status_code == 403
    assert client.get("/api/contractors/export", headers=holder).status_code == 200


def test_endpoint_path_comes_from_the_catalog_not_from_the_stored_definition(client, make_user):
    """即使有人繞過驗證器、直接把定義寫進資料庫（含惡意的端點／頁面／標籤），伺服器給前端的清單仍只含目錄裡的目標。"""
    import db
    boss, low, holder = _users(client, make_user)
    _flag(True)
    evil = {"buttons": [
        {"key": "b1", "slot": SLOT, "label": "<b>x</b>", "action": {"type": "export", "export": EXPORT_ID, "endpoint": "/api/users"}},
        {"key": "b2", "slot": SLOT, "label": "壞頁", "action": {"type": "navigate", "page": "https://evil.example/"}},
        {"key": "b3", "slot": SLOT, "label": "壞匯出", "action": {"type": "export", "export": "x:y"}},
        {"key": "b4", "slot": SLOT, "label": "壞類型", "action": {"type": "delete", "page": "x.html"}},
    ]}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO ui_definitions (kind, key, scope, version, status, body_json, created_by, created_at) "
                     "VALUES ('user_buttons', 'module:supply', 'company', 1, 'published', ?, 't', '2026-10-14T00:00:00')",
                     (json.dumps(evil, ensure_ascii=False),))
        conn.commit()
    finally:
        conn.close()
    got = client.get("/api/user-buttons/supply/suppliers.html", headers=holder).json()["buttons"]
    assert [b["key"] for b in got] == ["b1"]                                                  # 只有目錄內的匯出留下
    assert got[0]["endpoint"] == "/api/contractors/export" and "evil" not in json.dumps(got)
    assert got[0]["label"] == "<b>x</b>"                                                      # 標籤原樣給（前端用 x-text 當文字）


def test_non_superadmin_cannot_edit_or_publish_definitions(client, make_user):
    _, low, holder = _users(client, make_user)
    for h in (low, holder):
        r = client.put(DEF + "/draft", headers=h, params={"scope": "company"}, json={"body": {"buttons": []}})
        assert r.status_code in (401, 403)
        assert client.get("/api/user-buttons/catalog", headers=h).status_code in (403, 404)


# ── 4. 預覽 ────────────────────────────────────────────────────────────────
def test_preview_is_read_only_applies_the_real_permissions_and_is_superadmin_only(client, make_user):
    import db
    boss, low, holder = _users(client, make_user)
    _flag(True)
    pages = [p["page"] for p in client.get("/api/user-buttons/catalog", headers=boss).json()["pages"]]
    draft = {"buttons": [_nav(pages[0]), _exp()]}

    def snapshot():
        conn = db.get_db()
        try:
            return conn.execute("SELECT COUNT(*), COALESCE(MAX(id),0) FROM ui_definitions").fetchone()[:]
        finally:
            conn.close()
    before = snapshot()
    url = "/api/user-buttons/supply/suppliers.html/preview"
    r = client.post(url, headers=boss, json=dict(draft, user="ub_low"))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["user"] == "ub_low" and d["role"] == "sales"
    assert any(h["key"] == "b2" and "匯出" in h["reason"] for h in d["hidden"])           # 低權限者沒有匯出權限 ⇒ 說明原因
    assert not any(v["key"] == "b2" for v in d["visible"])
    r = client.post(url, headers=boss, json=dict(draft, user="ub_holder"))
    assert [v["key"] for v in r.json()["visible"] if v["type"] == "export"] == ["b2"]
    assert client.post(url, headers=boss, json=dict(draft, user="no_such_user")).status_code == 404
    assert client.post(url, headers=boss, json={"buttons": [{"key": "b1"}]}).status_code == 422             # 草稿不合法
    assert client.post(url, headers=low, json=draft).status_code in (401, 403)
    assert tuple(snapshot()) == tuple(before)                                                                       # 唯讀：沒有寫任何定義（稽核日誌會記被拒的呼叫，不算）


# ── 5. 頁面插槽與渲染 ──────────────────────────────────────────────────────
def _page():
    return source_tree.page_file("suppliers.html").read_text(encoding="utf-8")


def _slots_in_html(html):
    return set(re.findall(r'data-button-slot="([a-z0-9_-]+)"', html))


def test_scanner_positive_control():
    assert _slots_in_html('<div data-button-slot="toolbar"></div><p data-button-slot="x_1">') == {"toolbar", "x_1"}
    assert _slots_in_html("<div></div>") == set()


def test_declared_slots_and_page_html_agree_in_both_directions():
    from helpers import user_buttons as UB
    declared = {k for (m, p), ss in UB.SLOTS.items() if p == "suppliers.html" for k in ss}
    assert declared == _slots_in_html(_page()) == {"toolbar"}
    for (m, p), ss in UB.SLOTS.items():                                                       # 每個登記的頁面都真的存在於該模組
        assert source_tree.page_file(p).exists()


def test_slot_template_renders_labels_as_text_and_is_flag_guarded():
    src = _page()
    i = src.index('<div data-button-slot="toolbar"')
    tpl = src[src.rindex("<template", 0, i):src.index("</template>\n      <button class=\"btn btn-primary\" @click=\"openCreate()\"", i)]
    assert "$store.ub && $store.ub.enabled" in tpl
    assert 'x-text="b.label"' in tpl and "x-html" not in tpl and "innerHTML" not in tpl
    assert "MotrixUserButtons.run(b)" in tpl and ":disabled=\"$store.ub.busy || $store.ub.mode !== 'live'\"" in tpl
    assert '<script src="../static/user-buttons.js"></script>' in src
    assert "MotrixUserButtons.init({ module: 'supply', page: 'suppliers.html'" in src


def test_registered_export_is_a_get_without_parameters_and_its_perm_is_declared():
    from helpers import user_buttons as UB
    ex = UB._exports()[EXPORT_ID]                                                              # noqa: SLF001
    assert ex["endpoint"] == "GET /api/contractors/export" and ex["perm"] == "contractor_list" and ex["format"] == "xlsx"
    assert "{" not in ex["path"] and "?" not in ex["path"]


def test_only_allow_listed_get_exports_become_button_targets(monkeypatch):
    """module.json 登記了匯出 ≠ 可以變成按鈕：必須在 BUTTON_EXPORTS 允許清單內，且路徑是 /api/ 底下無參數的單純路徑。"""
    from core import registry
    from helpers import user_buttons as UB
    base = UB._exports()                                                                         # noqa: SLF001
    assert set(base) == {EXPORT_ID} == set(UB.BUTTON_EXPORTS)

    class _M:
        def __init__(self, key, ex):
            self.key = key
            self.manifest = {"customization": {"pages": [{"page": "x.html", "exports": [ex]}]}}
    cases = [("modx", {"key": "sidefx", "label": "會改資料的 GET", "endpoint": "GET /api/x/do-something", "format": "xlsx"}),        # 不在允許清單
             ("subcontract", {"key": "roster", "label": "外包名冊", "endpoint": "GET /api/../etc/passwd", "format": "xlsx"}),       # 路徑不合
             ("subcontract", {"key": "roster", "label": "外包名冊", "endpoint": "GET /static/x.xlsx", "format": "xlsx"}),
             ("subcontract", {"key": "roster", "label": "外包名冊", "endpoint": "POST /api/contractors/export", "format": "xlsx"})]
    for mkey, ex in cases:
        monkeypatch.setattr(registry, "loaded", lambda mkey=mkey, ex=ex: [_M(mkey, ex)])
        assert UB._exports() == {}, ex                                                          # noqa: SLF001
    monkeypatch.setattr(registry, "loaded", lambda: [_M("subcontract", {"key": "roster", "label": "外包名冊", "endpoint": "GET /api/contractors/export", "format": "xlsx"})])
    assert list(UB._exports()) == [EXPORT_ID]                                                   # noqa: SLF001 正對照
