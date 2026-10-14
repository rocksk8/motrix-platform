# -*- coding: utf-8 -*-
"""BP-1 第一刀：供應商管理頁接上 P9 版面引擎（管理者可自訂列表欄位的顯示／順序／標題），預設關閉。

要證明的事：
1. 登記與 fallback 一致（module.json 的欄位順序＝頁面的 fallback＝頁面標題預設文字）。
2. 旗標關閉：設定預設 False、頁面不發版面請求（deferred 模式、只在讀到旗標為 True 後才 start）、原本的表格原封不動。
3. 旗標開啟後的版面：核心欄位不能隱藏（反向控制）、非核心可隱藏／改名／重排；發布→再發布→還原到第一版→回到預設（空操作）。
4. 金額與權限：版面不改變 API 回傳的資料——非管理員的供應商清單仍是空的；沒有供應商權限的人讀不到設定與版面以外的任何東西。
5. 預覽草稿（編輯器）只換 view、不存任何東西。
"""
import json
import re
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
from core import source_tree   # noqa: E402  頁面路徑一律經 source_tree（守門 test_page_paths_centralized）
PAGE = source_tree.page_file("suppliers.html")
EDITOR = ROOT / "frontend" / "static" / "layout-editor.js"
RUNTIME = ROOT / "frontend" / "static" / "layout-runtime.js"
MANIFEST = HERE.parent / "module.json"

KEY = "module:supply"
BASE = "/api/definitions/layout/" + KEY
COL = "supply:suppliers.html/list:suppliers/column:"
LIST = "supply:suppliers.html/list:suppliers"
CORE = ("name", "active")
NONCORE = ("alias", "taxId", "category", "contact", "phone", "currency", "paymentTerms")


def _page():
    return PAGE.read_text(encoding="utf-8")


def _registered_columns():
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    pg = [p for p in m["customization"]["pages"] if p["page"] == "suppliers.html"][0]
    return [c["field"] for c in pg["lists"][0]["columns"]], m["customization"]["fields"]["supplier"]


# ── 1. 登記與 fallback ──────────────────────────────────────────────────────
def test_manifest_registration_is_valid():
    from core import customization
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert customization.validate_manifest(m) == []


def test_fallback_order_equals_registered_order_and_labels_equal():
    cols, fields = _registered_columns()
    src = _page()
    fb = re.search(r"fallback:\s*\{\s*lists:\s*\{\s*suppliers:\s*\[([^\]]*)\]", src)
    assert fb, "頁面沒有 fallback"
    assert re.findall(r"'([^']+)'", fb.group(1)) == cols
    lbl = re.search(r"layoutLabel\(f\)\s*\{\s*return \(\{(.*?)\}\)\[f\]", src, re.S)
    assert lbl
    page_labels = dict(re.findall(r"(\w+):\s*'([^']+)'", lbl.group(1)))
    assert page_labels == {f["key"]: f["label"] for f in fields}
    assert [f["key"] for f in fields if f["core"]] == list(CORE)


def test_every_registered_column_has_a_cell_in_the_layout_table():
    cols, _ = _registered_columns()
    src = _page()
    for c in cols:
        assert "c.field === '%s'" % c in src, "版面表格沒有 %s 欄的畫法（欄位會顯示成空白）" % c


# ── 2. 旗標關閉 ─────────────────────────────────────────────────────────────
def test_flag_default_is_off(client, make_user):
    from helpers import settings_registry as SR
    assert SR.get("builder_layout", "suppliers") is False


def test_page_is_deferred_and_only_starts_after_flag_is_read_true():
    src = _page()
    assert re.search(r"MotrixLayout\.init\(\{[^}]*deferred:\s*true", src, re.S)
    # start() 只出現在 initLayout() 裡，且在讀到旗標為 true 之後
    assert src.count("MotrixLayout.start()") == 1
    body = src[src.index("async initLayout()"):src.index("async init() {")]
    assert body.index("suppliers !== true) return") < body.index("MotrixLayout.start()")
    # 版面請求只能經由 runtime（頁面不自己打 /api/layout）
    assert "/api/layout" not in src
    rt = RUNTIME.read_text(encoding="utf-8")
    assert "if (!c.deferred) load()" in rt and "start: function () { return load() }" in rt


def test_original_table_is_untouched():
    """原本的表格（旗標關閉時看到的）逐字還在：十一個表頭、列的點擊與編輯／日誌按鈕。"""
    src = _page()
    start = src.index('<table class="data-table">')
    block = src[start:src.index("</table>", start)]
    for th in ("公司名稱", "內部簡稱", "統一編號", "類型", "主要聯絡人", "電話", "幣別", "付款條件", "狀態"):
        assert "<th>%s</th>" % th in block
    assert '@click="selectSupplier(s)"' in block and '@click.stop="openEdit(s)"' in block
    assert "x-for=\"s in filtered\"" in block
    assert "$store.layout" not in block                               # 原表格不讀版面


def test_flag_off_page_has_no_layout_dom_at_load():
    src = _page()
    head = src[:src.index("<script src=\"../static/record-link.js\">")]
    assert "data-layout-editor-slot" not in head and "data-layout-list" not in head      # 編輯位置與版面表格只在旗標開啟後由 JS 插入


# ── 3. 版面：核心欄位、發布、還原 ───────────────────────────────────────────
def _h(client, make_user, name, role, modules=None):
    u, p = make_user(name, "Lay-Pass-123", role=role, modules=modules)[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _publish(client, h, ops, scope="company"):
    r = client.put(BASE + "/draft", headers=h, params={"scope": scope}, json={"body": {"ops": ops}})
    assert r.status_code == 200, r.text
    return client.post(BASE + "/publish", headers=h, params={"scope": scope}, json={"note": "t"})


def _eff(client, h, role=None):
    return client.get("/api/layout/supply", headers=h, params={"role": role} if role else None).json()


def test_points_are_registered_for_the_page(client, make_user):
    h = _h(client, make_user, "bp1_boss0", "superadmin")
    ids = {p["id"] for p in _eff(client, h)["points"]}
    for c in CORE + NONCORE:
        assert COL + c in ids


@pytest.mark.parametrize("core", CORE)
def test_core_columns_cannot_be_hidden(client, make_user, core):
    """反向控制：核心欄位（公司名稱、狀態）不能隱藏；發布被擋、沒有任何發布版。"""
    h = _h(client, make_user, "bp1_boss1", "superadmin")
    r = _publish(client, h, [{"op": "hide", "target": COL + core}])
    assert r.status_code == 422, r.text
    assert client.get(BASE + "?scope=company", headers=h).json().get("latest") is None


def test_core_column_can_be_moved_but_not_hidden(client, make_user):
    h = _h(client, make_user, "bp1_boss2", "superadmin")
    assert _publish(client, h, [{"op": "move", "target": COL + "name", "index": 2}]).status_code == 200


def test_noncore_hide_relabel_reorder_publish_and_apply_per_role(client, make_user):
    boss = _h(client, make_user, "bp1_boss3", "superadmin")
    admin = _h(client, make_user, "bp1_admin3", "admin")
    ops = [{"op": "hide", "target": COL + "currency"},
           {"op": "relabel", "target": COL + "taxId", "label": "統編"},
           {"op": "reorder", "target": LIST,
            "order": [COL + c for c in ("name", "taxId", "alias", "category", "contact", "phone", "paymentTerms", "currency", "active")]}]
    assert _publish(client, boss, ops).status_code == 200
    got = _eff(client, admin)
    assert got["source"] == "company v1" and got["ops"] == ops and not got["dropped"]


def test_publish_two_versions_then_restore_first_then_back_to_default(client, make_user):
    boss = _h(client, make_user, "bp1_boss4", "superadmin")
    v1 = [{"op": "hide", "target": COL + "currency"}]
    v2 = [{"op": "hide", "target": COL + "phone"}]
    assert _publish(client, boss, v1).status_code == 200
    assert _publish(client, boss, v2).status_code == 200
    assert _eff(client, boss)["ops"] == v2
    r = client.post("/api/definitions/layout/%s/restore/1" % KEY, headers=boss, params={"scope": "company"}, json={"note": "back"})
    assert r.status_code == 200, r.text
    assert _eff(client, boss)["ops"] == v1                                   # 還原到第 1 版（＝再發布一版，內容同第 1 版）
    # 「還原到預設」＝發布一版空操作：有效操作為空，畫面＝程式預設
    assert _publish(client, boss, []).status_code == 200
    got = _eff(client, boss)
    assert got["ops"] == [] and got["source"].startswith("company")


def test_non_superadmin_cannot_publish_or_preview_other_roles(client, make_user):
    admin = _h(client, make_user, "bp1_admin5", "admin")
    assert client.put(BASE + "/draft", headers=admin, params={"scope": "company"}, json={"body": {"ops": []}}).status_code in (401, 403)
    assert client.get("/api/layout/supply", headers=admin, params={"role": "sales"}).status_code == 403


# ── 4. 金額與權限：版面不改資料 ─────────────────────────────────────────────
def test_layout_does_not_change_what_the_api_returns(client, make_user):
    """版面只決定『已經收到的欄位』怎麼排。非管理員的供應商清單本來是空的，發布任何版面之後仍是空的；管理員拿到的資料不變。"""
    boss = _h(client, make_user, "bp1_boss6", "superadmin")
    sales = _h(client, make_user, "bp1_sales6", "sales", modules=["procurement"])
    before_boss = client.get("/api/suppliers", headers=boss).json()
    before_sales = client.get("/api/suppliers", headers=sales).json()
    ops = [{"op": "relabel", "target": COL + "taxId", "label": "統編"}, {"op": "hide", "target": COL + "currency"}]
    assert _publish(client, boss, ops).status_code == 200
    assert client.get("/api/suppliers", headers=boss).json() == before_boss
    assert client.get("/api/suppliers", headers=sales).json() == before_sales == []


def test_registered_columns_carry_no_money_fields():
    """這一頁登記的欄位沒有金額：之後若有人把金額欄加進登記，必須先回頭看遮蔽規則（此題提醒他）。"""
    _, fields = _registered_columns()
    money = re.compile(r"price|amount|cost|fee|total|金額|價|成本|費")
    assert [f["key"] for f in fields if money.search(f["key"]) or money.search(f["label"])] == []


def test_public_flag_read_needs_login_and_flag_group_is_not_sensitive(client, make_user):
    assert client.get("/api/settings-center/public?groups=builder_layout").status_code == 401
    sales = _h(client, make_user, "bp1_sales7", "sales")
    r = client.get("/api/settings-center/public?groups=builder_layout", headers=sales)
    assert r.status_code == 200 and r.json()["groups"]["builder_layout"]["suppliers"] is False


def test_flag_turns_on_through_the_normal_settings_path(client, make_user):
    """旗標走設定登錄的唯一寫入口（帳本＋稽核）；寫入後一般使用者讀得到 True。"""
    import db
    from helpers import settings_registry as SR
    boss = _h(client, make_user, "bp1_boss8", "superadmin")
    sales = _h(client, make_user, "bp1_sales8", "sales")
    conn = db.get_db()
    try:
        out = SR.publish("builder_layout", {"suppliers": True}, reason="測試", user="bp1_boss8", conn=conn)
        conn.commit()
    finally:
        conn.close()
    assert out["changed"] is True
    SR.invalidate("builder_layout")
    r = client.get("/api/settings-center/public?groups=builder_layout", headers=sales)
    assert r.json()["groups"]["builder_layout"]["suppliers"] is True
    conn = db.get_db()
    try:
        n = conn.execute("SELECT COUNT(*) FROM config_changes WHERE domain LIKE 'setting:builder_layout%'").fetchone()[0]
    finally:
        conn.close()
    assert n >= 1                                                            # 進了變更帳本
    assert client.get("/api/settings-center/groups/builder_layout", headers=boss).status_code == 200


# ── 5. 預覽草稿（編輯器）────────────────────────────────────────────────────
def test_draft_role_preview_is_opt_in_and_only_swaps_the_view():
    ed = EDITOR.read_text(encoding="utf-8")
    i = ed.index("async previewAs()")
    body = ed[i:ed.index("window.MotrixLayoutEditor", i)]
    assert "previewDraft" in body and "viaDraft" in body
    # 預覽路徑只呼叫 show（換 view）與讀取；不呼叫任何寫入（PUT／POST／DELETE／saveDraft／publish）
    assert not re.search(r"method:\s*'(PUT|POST|DELETE|PATCH)'|saveDraft\(|publish\(", body)
    # 預設不勾：沒勾選時行為與原本相同（顯示該角色已發布的版面）
    assert "previewDraft: false" in ed
    # 草稿只在『草稿影響得到這個角色』時才用
    assert "this.scope === 'role:' + this.previewRole" in body and "this.scope === 'company'" in body
    assert "mount: mount" in ed and "document.getElementById('ml-editor')" in ed         # 編輯器只掛一次


def test_governance_preview_is_guarded_and_runs_before_the_publish_request():
    """治理影響預覽（builder_governance）：只在 MotrixDefGovernance 存在且 available() 為真時才呼叫；在 publish POST 之前；
    取消就不發布。頁面有載入 def-governance.js（沒載入＝完全略過，行為與先前相同）。"""
    ed = EDITOR.read_text(encoding="utf-8")
    i = ed.index("async _publish()")
    body = ed[i:ed.index("async _restore(", i)]
    assert body.index("MotrixDefGovernance.available('layout')") < body.index("MotrixDefGovernance.review(") < body.index("'/publish?scope='")
    assert "window.MotrixDefGovernance &&" in body
    assert re.search(r"已取消發布'; this\.busy = false; return", body)
    assert '<script src="../js/def-governance.js"></script>' in _page()
