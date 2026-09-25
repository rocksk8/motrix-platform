# -*- coding: utf-8 -*-
"""P1 能力目錄＋P3 模組可自訂點（CUSTOMIZATION-SPEC §5、§8.2）。

- schema：正對照（合法的過）＋反向控制（逐項弄壞 ⇒ 擋，且指出位置）
- loader：格式錯誤 ⇒ 模組不載入並說明原因；沒有 customization ⇒ 照常載入
- 目錄：合成模組登記的每一個點都列得出來；引用程式沒有提供的端點／版型的點不列、改列 problems
- 排版守門：只能動登記過的點、只能做該點允許的操作（核心欄位不可隱藏或改名）
- 端點：僅超級管理員；已載入的真實模組逐一驗「登記＝列出、沒有 problems」（不點名任何 L2 模組）

正對照一律用合成模組（MODULE-GUIDE §7：不綁特定 L2 模組）。
"""
import copy
import json

import pytest
from fastapi import APIRouter

from core import catalog, customization as C, events, loader, registry


# ── 合成模組 ────────────────────────────────────────────────────────────────

def _manifest():
    """六類可自訂點各至少一項的合法描述。"""
    return {
        "key": "zz_syn", "name": "合成", "version": "1.0.0", "core": ">=1.0,<2.0",
        "permissions": ["zz_syn"],
        "pages": [{"path": "zz-syn.html", "menu": {"group": "business", "label": "合成頁", "icon": "box", "order": 10}}],
        "customization": {
            "schema": 1,
            "fields": {
                "doc": [{"key": "docNo", "label": "單號", "core": True},
                        {"key": "amount", "label": "金額", "core": True},
                        {"key": "note", "label": "備註", "core": False},
                        {"key": "tag", "label": "標籤", "core": False}],
                "other": [{"key": "x", "label": "X", "core": False}],
            },
            "pages": [{
                "page": "zz-syn.html",
                "lists": [{"key": "docs", "label": "單據清單", "entity": "doc", "columns": [
                    {"field": "docNo", "visible": True}, {"field": "amount", "visible": True},
                    {"field": "note", "visible": False}]}],
                "forms": [{"key": "doc", "label": "單據", "entity": "doc", "sections": [
                    {"key": "a", "label": "基本", "fields": ["docNo", "amount"]},
                    {"key": "b", "label": "其他", "fields": ["note", "tag"]}]},
                    {"key": "other", "label": "另一張", "entity": "other", "sections": [
                        {"key": "a", "label": "A", "fields": ["x"]}]}],
                "actions": [{"key": "save", "label": "儲存", "endpoint": "POST /api/zz-syn/docs", "perm": "zz_syn"},
                            {"key": "edit", "label": "編輯"},
                            {"key": "del", "label": "刪除", "endpoint": "DELETE /api/zz-syn/docs/{doc_id}"}],
                "menus": [{"key": "row", "label": "列操作", "items": ["edit", "del"]}],
                "exports": [{"key": "xlsx", "label": "匯出 Excel", "endpoint": "GET /api/zz-syn/export", "format": "xlsx"}],
            }],
            "outputs": [{"key": "voucher", "label": "憑據", "template": "zz_tpl"}],
        },
    }


def _router():
    r = APIRouter()

    @r.post("/api/zz-syn/docs")
    def _save():
        """存一筆。"""

    @r.delete("/api/zz-syn/docs/{doc_id}")
    def _del(doc_id: int, authorization: str = None):
        pass

    @r.get("/api/zz-syn/export")
    def _export(q: str = None):
        pass
    return r


def _problems_at(m):
    return [p["path"] for p in C.validate_manifest(m)]


# ── schema：正對照 ──────────────────────────────────────────────────────────

def test_valid_synthetic_manifest_passes():
    assert C.validate_manifest(_manifest()) == []


def test_manifest_without_customization_is_not_blocked_by_loader_schema():
    m = _manifest()
    m.pop("customization")
    assert C.validate_manifest(m) == []


def test_empty_categories_are_valid_when_written_out():
    m = _manifest()
    pg = m["customization"]["pages"][0]
    for k in C.PAGE_KINDS:
        pg[k] = []
    m["customization"]["outputs"] = []
    assert C.validate_manifest(m) == []


# ── schema：反向控制（每一項各自會被擋，而且指出位置）──────────────────────

def _mut(fn):
    def apply(m):
        fn(m["customization"])
        return m
    return apply


_PG = lambda c: c["pages"][0]  # noqa: E731

NEGATIVE = [
    ("customization 不是物件", lambda m: m.update(customization=[]), "customization"),
    ("缺 schema", _mut(lambda c: c.pop("schema")), "customization"),
    ("看不懂的 schema", _mut(lambda c: c.update(schema=2)), "customization.schema"),
    ("schema 用布林", _mut(lambda c: c.update(schema=True)), "customization.schema"),
    ("不認得的頂層鍵", _mut(lambda c: c.update(extra=1)), "customization.extra"),
    ("缺 outputs", _mut(lambda c: c.pop("outputs")), "customization"),
    ("fields 不是物件", _mut(lambda c: c.update(fields=[])), "customization.fields"),
    ("欄位缺 core", _mut(lambda c: c["fields"]["doc"][0].pop("core")), "customization.fields.doc[0]"),
    ("core 用字串", _mut(lambda c: c["fields"]["doc"][0].update(core="yes")), "customization.fields.doc[0].core"),
    ("欄位多一個鍵", _mut(lambda c: c["fields"]["doc"][0].update(width=3)), "customization.fields.doc[0].width"),
    ("欄位 key 不合法", _mut(lambda c: c["fields"]["doc"][0].update(key="1bad")), "customization.fields.doc[0].key"),
    ("欄位 label 空白", _mut(lambda c: c["fields"]["doc"][0].update(label=" ")), "customization.fields.doc[0].label"),
    ("欄位重複", _mut(lambda c: c["fields"]["doc"].append({"key": "note", "label": "再一次", "core": False})), "customization.fields.doc"),
    ("實體沒有欄位", _mut(lambda c: c["fields"].update(other=[])), "customization.fields.other"),
    ("頁面不在 pages[]", _mut(lambda c: _PG(c).update(page="nope.html")), "customization.pages[0].page"),
    ("頁面缺 exports", _mut(lambda c: _PG(c).pop("exports")), "customization.pages[0]"),
    ("頁面缺 menus", _mut(lambda c: _PG(c).pop("menus")), "customization.pages[0]"),
    ("列表欄位不存在", _mut(lambda c: _PG(c)["lists"][0]["columns"].append({"field": "ghost", "visible": True})),
     "customization.pages[0].lists[0].columns[3].field"),
    ("列表 visible 非布林", _mut(lambda c: _PG(c)["lists"][0]["columns"][0].update(visible="y")),
     "customization.pages[0].lists[0].columns[0].visible"),
    ("列表沒有欄", _mut(lambda c: _PG(c)["lists"][0].update(columns=[])), "customization.pages[0].lists[0].columns"),
    ("列表實體不存在", _mut(lambda c: _PG(c)["lists"][0].update(entity="ghost")), "customization.pages[0].lists[0].entity"),
    ("表單欄位不存在", _mut(lambda c: _PG(c)["forms"][0]["sections"][0]["fields"].append("ghost")),
     "customization.pages[0].forms[0].sections[0].fields[2]"),
    ("同一欄位放兩個區塊", _mut(lambda c: _PG(c)["forms"][0]["sections"][1]["fields"].append("docNo")),
     "customization.pages[0].forms[0].sections"),
    ("按鈕端點格式錯", _mut(lambda c: _PG(c)["actions"][0].update(endpoint="/api/zz-syn/docs")),
     "customization.pages[0].actions[0].endpoint"),
    ("按鈕權限不在 permissions", _mut(lambda c: _PG(c)["actions"][0].update(perm="root")),
     "customization.pages[0].actions[0].perm"),
    ("按鈕 key 重複", _mut(lambda c: _PG(c)["actions"].append({"key": "save", "label": "又一個"})),
     "customization.pages[0].actions"),
    ("選單項目不是按鈕", _mut(lambda c: _PG(c)["menus"][0]["items"].append("ghost")),
     "customization.pages[0].menus[0].items[2]"),
    ("選單沒有項目", _mut(lambda c: _PG(c)["menus"][0].update(items=[])), "customization.pages[0].menus[0].items"),
    ("匯出缺端點", _mut(lambda c: _PG(c)["exports"][0].pop("endpoint")), "customization.pages[0].exports[0]"),
    ("匯出格式不認得", _mut(lambda c: _PG(c)["exports"][0].update(format="docx")),
     "customization.pages[0].exports[0].format"),
    ("輸出缺版型", _mut(lambda c: c["outputs"][0].update(template="")), "customization.outputs[0].template"),
    ("輸出 key 重複", _mut(lambda c: c["outputs"].append(dict(c["outputs"][0]))), "customization.outputs"),
]


@pytest.mark.parametrize("why,mutate,where", NEGATIVE, ids=[n[0] for n in NEGATIVE])
def test_broken_manifest_is_rejected_with_its_location(why, mutate, where):
    m = _manifest()
    mutate(m)                                   # 就地修改
    paths = _problems_at(m)
    assert paths, "%s：應該被擋" % why
    assert where in paths, "%s：問題位置 %s 不含 %s" % (why, paths, where)


def test_require_valid_raises_with_reason():
    m = _manifest()
    m["customization"]["schema"] = 9
    with pytest.raises(ValueError, match="customization"):
        C.require_valid(m)


# ── loader：格式錯誤 ⇒ 不載入並說明原因 ────────────────────────────────────

@pytest.fixture
def clean_registry():
    snap = registry.snapshot()
    registry._reset()
    yield
    registry.restore(snap)


def _pkg(tmp_path, pkg, mods):
    root = tmp_path / pkg
    root.mkdir()
    (root / "__init__.py").write_text("", encoding="utf-8")
    for key, manifest in mods.items():
        d = root / key
        d.mkdir()
        (d / "module.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        (d / "__init__.py").write_text("from core.registry import ModuleSpec\nMODULE = ModuleSpec(key=%r)\n" % key,
                                       encoding="utf-8")
    return root


def test_loader_refuses_module_with_broken_customization(tmp_path, monkeypatch, clean_registry):
    good = _manifest()
    good.update(key="good")
    bad = copy.deepcopy(good)
    bad.update(key="bad")
    bad["customization"]["pages"][0]["lists"][0]["columns"][0]["field"] = "ghost"
    plain = {"key": "plain", "core": ">=1.0,<2.0"}
    root = _pkg(tmp_path, "zz_cust_pkg", {"good": good, "bad": bad, "plain": plain})
    monkeypatch.syspath_prepend(str(tmp_path))
    loaded = {m.key for m in loader.load_all(str(root), "zz_cust_pkg")}
    assert loaded == {"good", "plain"}
    states = {s["key"]: s for s in registry.module_states()}
    assert states["bad"]["state"] == registry.STATE_FAILED
    assert "customization" in states["bad"]["reason"] and "ghost" in states["bad"]["reason"]


# ── 能力目錄：合成模組 ─────────────────────────────────────────────────────

@pytest.fixture
def synthetic_catalog(clean_registry):
    ev = events.snapshot()
    cat = catalog.snapshot()
    m = _manifest()
    spec = registry.ModuleSpec(key="zz_syn", routers=[_router()],
                               providers={("zz.cap", "zz_syn"): lambda: None})
    registry.register(registry.LoadedModule(key="zz_syn", manifest=m, spec=spec))
    events.declare("zz_syn.done", "zz_syn", 1, ["docNo"], "合成事件")
    catalog.register_section("outputs", "helpers.doc_template",
                             lambda: {"themes": ["t"], "blocks": ["b"], "templates": [{"key": "zz_tpl"}]})
    yield m
    events.restore(ev)
    catalog.restore(cat)


def _mod(cat, key):
    return next(x for x in cat["modules"] if x["key"] == key)


def test_catalog_lists_every_registered_point_of_a_module(synthetic_catalog):
    cat = catalog.build()
    mod = _mod(cat, "zz_syn")
    want = {p["id"] for p in C.points(synthetic_catalog)}
    got = {p["id"] for p in mod["points"]}
    assert got == want and mod["problems"] == []
    kinds = {p["kind"] for p in mod["points"]}
    # §8.2 六類＋側欄＋欄位／區塊
    assert {"list", "form", "section", "field", "action", "menu", "export", "output", "sidebar"} <= kinds
    assert mod["coreFields"] == {"doc": ["docNo", "amount"], "other": []}
    ids = {e["id"] for e in mod["endpoints"]}
    assert ids == {"POST /api/zz-syn/docs", "DELETE /api/zz-syn/docs/{doc_id}", "GET /api/zz-syn/export"}
    ex = next(e for e in mod["endpoints"] if e["id"] == "GET /api/zz-syn/export")
    assert ex["params"]["query"] == ["q"]
    assert any(p["capability"] == "zz.cap" and p["module"] == "zz_syn" for p in cat["providers"])
    ev = next(e for e in cat["events"] if e["name"] == "zz_syn.done")
    assert ev["fields"] == ["docNo"] and ev["version"] == 1
    assert cat["outputs"]["available"] and cat["catalogVersion"] == catalog.CATALOG_VERSION


def test_core_and_display_fields_get_different_ops(synthetic_catalog):
    pts = {p["id"]: p for p in C.points(synthetic_catalog)}
    core = pts["zz_syn:zz-syn.html/list:docs/column:docNo"]
    disp = pts["zz_syn:zz-syn.html/list:docs/column:note"]
    assert core["core"] is True and "hide" not in core["ops"] and "relabel" not in core["ops"]
    assert disp["core"] is False and {"hide", "relabel", "move"} <= set(disp["ops"])


def test_point_with_missing_endpoint_is_hidden_and_reported(synthetic_catalog):
    """程式沒有提供的選項不可以出現：登記了端點而路由不存在 ⇒ 不列在 points、列在 problems。"""
    synthetic_catalog["customization"]["pages"][0]["exports"][0]["endpoint"] = "GET /api/zz-syn/nothing"
    mod = _mod(catalog.build(), "zz_syn")
    bad = "zz_syn:zz-syn.html/export:xlsx"
    assert bad not in {p["id"] for p in mod["points"]}
    assert [p["point"] for p in mod["problems"]] == [bad]


def test_output_with_missing_template_is_hidden_and_reported(synthetic_catalog):
    synthetic_catalog["customization"]["outputs"][0]["template"] = "no_such"
    mod = _mod(catalog.build(), "zz_syn")
    assert "zz_syn:output:voucher" not in {p["id"] for p in mod["points"]}
    assert mod["problems"][0]["point"] == "zz_syn:output:voucher"


def test_output_points_are_problems_when_output_engine_absent(synthetic_catalog):
    catalog.restore({})
    cat = catalog.build()
    assert cat["outputs"]["available"] is False
    assert "zz_syn:output:voucher" in {p["point"] for p in _mod(cat, "zz_syn")["problems"]}


def test_expected_sections_without_owner_are_listed_as_gaps(synthetic_catalog):
    """欄位型別與公式函式由 P4／P8 擁有；擁有者不在 ⇒ 明說是缺口，不自己補一份。"""
    catalog.restore({})
    cat = catalog.build()
    for name in catalog.EXPECTED_SECTIONS:
        assert cat[name]["available"] is False and cat[name]["items"] == []
        assert name in {g["section"] for g in cat["gaps"]}


def test_registered_section_is_served_and_projectable(synthetic_catalog):
    catalog.register_section("fieldTypes", "zz.owner", lambda: ["text", "number"])
    cat = catalog.build()
    assert cat["fieldTypes"] == {"available": True, "owner": "zz.owner", "items": ["text", "number"]}
    assert catalog.section("fieldTypes") == ["text", "number"]
    assert "fieldTypes" not in {g["section"] for g in cat["gaps"]}


def test_two_owners_for_one_section_is_an_error(synthetic_catalog):
    """唯一來源：同一個區段不可以有兩個擁有者（第二個來源在登記當下就被擋）。"""
    catalog.register_section("formulaFunctions", "zz.a", lambda: [])
    catalog.register_section("formulaFunctions", "zz.a", lambda: [])       # 同一擁有者重新匯入：可以
    with pytest.raises(ValueError, match="formulaFunctions"):
        catalog.register_section("formulaFunctions", "zz.b", lambda: [])


def test_broken_section_does_not_break_catalog(synthetic_catalog):
    def boom():
        raise RuntimeError("壞了")
    catalog.register_section("fieldTypes", "zz.owner", boom)
    cat = catalog.build()
    assert cat["fieldTypes"]["available"] is False and "壞了" in cat["fieldTypes"]["reason"]
    assert _mod(cat, "zz_syn")["points"]


# ── 排版守門：只能動登記過的點 ──────────────────────────────────────────────

def _pts():
    return C.points(_manifest())


BASE = "zz_syn:zz-syn.html"


def test_layout_on_registered_points_passes():
    ops = [
        {"op": "hide", "target": BASE + "/list:docs/column:note"},
        {"op": "move", "target": BASE + "/list:docs/column:docNo", "to": BASE + "/list:docs"},
        {"op": "relabel", "target": BASE + "/action:save", "label": "存檔"},
        {"op": "move", "target": BASE + "/form:doc/field:note", "to": BASE + "/form:doc/section:a"},
        {"op": "move", "target": BASE + "/form:doc/field:docNo", "to": BASE + "/form:doc/section:b"},
        {"op": "hide", "target": BASE + "/export:xlsx"},
        {"op": "select_template", "target": "zz_syn:output:voucher"},
        {"op": "move", "target": BASE + "/sidebar"},
    ]
    assert C.check_layout(_pts(), ops) == []


LAYOUT_NEGATIVE = [
    ("程式沒有提供的欄位", {"op": "hide", "target": BASE + "/list:docs/column:ghost"}, "[0].target"),
    ("程式沒有提供的按鈕", {"op": "move", "target": BASE + "/action:print"}, "[0].target"),
    ("程式沒有提供的匯出", {"op": "move", "target": BASE + "/export:pdf"}, "[0].target"),
    ("隱藏核心欄位", {"op": "hide", "target": BASE + "/list:docs/column:docNo"}, "[0].op"),
    ("改名核心欄位", {"op": "relabel", "target": BASE + "/form:doc/field:amount", "label": "X"}, "[0].op"),
    ("不認得的操作", {"op": "delete", "target": BASE + "/action:save"}, "[0].op"),
    ("欄位搬到別張表單", {"op": "move", "target": BASE + "/form:doc/field:note", "to": BASE + "/form:other/section:a"}, "[0].to"),
    ("列表欄位搬到表單", {"op": "move", "target": BASE + "/list:docs/column:note", "to": BASE + "/form:doc/section:a"}, "[0].to"),
    ("搬到不存在的地方", {"op": "move", "target": BASE + "/form:doc/field:note", "to": BASE + "/form:doc/section:zz"}, "[0].to"),
    ("改名給空白", {"op": "relabel", "target": BASE + "/action:save", "label": ""}, "[0].label"),
]


@pytest.mark.parametrize("why,op,where", LAYOUT_NEGATIVE, ids=[n[0] for n in LAYOUT_NEGATIVE])
def test_layout_touching_unregistered_or_forbidden_is_rejected(why, op, where):
    assert where in [p["path"] for p in C.check_layout(_pts(), [op])], why


# ── HTTP 端點與真實模組 ────────────────────────────────────────────────────

def _hdr(client, make_user, username, role):
    u, p = make_user(username=username, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_catalog_endpoint_superadmin_only(client, make_user):
    assert client.get("/api/platform/catalog").status_code == 401
    for role in ("admin", "sales"):
        h = _hdr(client, make_user, "cat_" + role, role)
        assert client.get("/api/platform/catalog", headers=h).status_code == 403
    h = _hdr(client, make_user, "cat_root", "superadmin")
    r = client.get("/api/platform/catalog", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert {m["key"] for m in body["modules"]} == {m.key for m in registry.loaded()}
    assert body["outputs"]["available"] is True           # L1 輸出引擎一定在
    assert body["coreVersion"] == registry.CORE_VERSION


def test_every_loaded_module_lists_all_its_points_without_problems(client):
    """任取已載入且有登記可自訂點的模組（不點名）：登記的點全部列出、沒有引用不存在的端點或版型。"""
    import main  # noqa: F401  確保 platform_catalog 已登記 outputs 區段
    mods = [m for m in registry.loaded() if isinstance((m.manifest or {}).get("customization"), dict)]
    if not mods:
        pytest.skip("沒有任何已載入模組登記 customization ⇒ 無對象")
    cat = catalog.build()
    for m in mods:
        entry = _mod(cat, m.key)
        assert entry["problems"] == [], (m.key, entry["problems"])
        assert {p["id"] for p in entry["points"]} == {p["id"] for p in C.points(m.manifest)}, m.key
