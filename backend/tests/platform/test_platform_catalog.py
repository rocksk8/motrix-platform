# -*- coding: utf-8 -*-
"""P1 能力目錄＋P3 模組可自訂點（CUSTOMIZATION-SPEC §5、§8.2）。

- schema：正對照（合法的過）＋反向控制（逐項弄壞 ⇒ 擋，且指出位置）
- loader：格式錯誤 ⇒ 模組不載入並說明原因；沒有 customization ⇒ 照常載入
- 目錄：合成模組登記的每一個點都列得出來；引用程式沒有提供的端點／版型的點不列、改列 problems
- 排版守門：只能動 `catalog.layout_points()` 的點（唯一入口；藏起的點、未載入模組的點都擋）、
  只能做該點允許的操作（核心欄位不可隱藏或改名）、只能帶該操作認得的鍵、move 有容器限制、
  select_template 只能選程式提供的版型
- 單一入口守門：`customization._raw_points`／`_check_ops` 只准在 `core.catalog._module_points`／`check_layout` 呼叫
- 端點：僅超級管理員；已載入的真實模組逐一驗「登記＝列出、沒有 problems」（不點名任何 L2 模組）

正對照一律用合成模組（MODULE-GUIDE §7：不綁特定 L2 模組）。
突變清單與預期轉紅的題：同目錄 `_mutations_p1p3.md`。
"""
import ast
import copy
import json
from pathlib import Path

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
    want = {p["id"] for p in C._raw_points(synthetic_catalog)}
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
    pts = {p["id"]: p for p in catalog.layout_points("zz_syn")}
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


# ── 排版守門：只能動 layout_points() 的點 ───────────────────────────────────

BASE = "zz_syn:zz-syn.html"


def _check(ops, key="zz_syn"):
    return catalog.check_layout(key, ops)


def _paths(ops, key="zz_syn"):
    return [p["path"] for p in _check(ops, key)]


def test_layout_on_registered_points_passes(synthetic_catalog):
    ops = [
        {"op": "hide", "target": BASE + "/list:docs/column:note"},
        {"op": "move", "target": BASE + "/list:docs/column:docNo", "to": BASE + "/list:docs"},
        {"op": "relabel", "target": BASE + "/action:save", "label": "存檔"},
        {"op": "move", "target": BASE + "/form:doc/field:note", "to": BASE + "/form:doc/section:a"},
        {"op": "move", "target": BASE + "/form:doc/field:docNo", "to": BASE + "/form:doc/section:b", "index": 0},
        {"op": "move", "target": BASE + "/form:doc/section:b", "to": BASE + "/form:doc"},
        {"op": "move", "target": BASE + "/action:save", "to": BASE + "/menu:row"},
        {"op": "hide", "target": BASE + "/export:xlsx"},
        {"op": "select_template", "target": "zz_syn:output:voucher", "template": "zz_tpl"},
        {"op": "move", "target": BASE + "/sidebar", "index": 2},
        {"op": "hide", "target": BASE + "/sidebar"},
        {"op": "reorder", "target": BASE + "/list:docs",
         "order": [BASE + "/list:docs/column:" + f for f in ("note", "docNo", "amount")]},
        {"op": "reorder", "target": BASE + "/menu:row", "order": [BASE + "/action:del", BASE + "/action:edit"]},
        {"op": "add_section", "target": BASE + "/form:doc", "key": "c", "label": "新區塊"},
    ]
    assert _check(ops) == []


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
    # P-M2：版型
    ("選不存在的版型", {"op": "select_template", "target": "zz_syn:output:voucher", "template": "no_such"}, "[0].template"),
    ("選版型沒給版型", {"op": "select_template", "target": "zz_syn:output:voucher"}, "[0]"),
    # P-S1：容器限制
    ("區塊移到按鈕底下", {"op": "move", "target": BASE + "/form:doc/section:a", "to": BASE + "/action:save"}, "[0].to"),
    ("區塊移到別張表單", {"op": "move", "target": BASE + "/form:doc/section:a", "to": BASE + "/form:other"}, "[0].to"),
    ("按鈕移到區塊", {"op": "move", "target": BASE + "/action:save", "to": BASE + "/form:doc/section:a"}, "[0].to"),
    ("匯出換容器", {"op": "move", "target": BASE + "/export:xlsx", "to": BASE + "/menu:row"}, "[0].to"),
    ("選單換容器", {"op": "move", "target": BASE + "/menu:row", "to": BASE + "/form:doc"}, "[0].to"),
    ("側欄換群組", {"op": "move", "target": BASE + "/sidebar", "to": BASE + "/list:docs"}, "[0].to"),
    ("側欄改名", {"op": "relabel", "target": BASE + "/sidebar", "label": "X"}, "[0].op"),
    ("index 為負", {"op": "move", "target": BASE + "/sidebar", "index": -1}, "[0].index"),
    # P-S2：不認得的鍵
    ("不認得的鍵", {"op": "hide", "target": BASE + "/action:save", "evil": 1}, "[0].evil"),
    ("鍵名打錯", {"op": "relabel", "target": BASE + "/action:save", "lable": "存檔"}, "[0].lable"),
    ("側欄帶群組鍵", {"op": "move", "target": BASE + "/sidebar", "group": "finance"}, "[0].group"),
    ("reorder 少一個", {"op": "reorder", "target": BASE + "/list:docs",
                      "order": [BASE + "/list:docs/column:docNo"]}, "[0].order"),
    ("reorder 夾帶別的點", {"op": "reorder", "target": BASE + "/menu:row",
                         "order": [BASE + "/action:del", BASE + "/action:save"]}, "[0].order"),
    ("新增區塊撞名", {"op": "add_section", "target": BASE + "/form:doc", "key": "a", "label": "A"}, "[0].key"),
]


@pytest.mark.parametrize("why,op,where", LAYOUT_NEGATIVE, ids=[n[0] for n in LAYOUT_NEGATIVE])
def test_layout_touching_unregistered_or_forbidden_is_rejected(synthetic_catalog, why, op, where):
    assert where in _paths([op]), why


def _hide_del_endpoint(m):
    """稽核探針：刪除按鈕的端點改成路由裡沒有的 ⇒ 程式沒有提供這個按鈕。"""
    m["customization"]["pages"][0]["actions"][2]["endpoint"] = "DELETE /api/zz-syn/nope"


def test_hidden_point_is_rejected_by_layout_guard(synthetic_catalog):
    """P-M1 探針：引用不存在端點的按鈕，目錄藏起來，守門也要擋（hide／relabel／move 都擋）。"""
    _hide_del_endpoint(synthetic_catalog)
    gone = BASE + "/action:del"
    assert gone not in {p["id"] for p in catalog.layout_points("zz_syn")}
    for op in ({"op": "hide", "target": gone}, {"op": "relabel", "target": gone, "label": "X"},
               {"op": "move", "target": gone, "to": BASE + "/menu:row"}):
        assert _paths([op]) == ["[0].target"], op


def test_menu_drops_hidden_buttons(synthetic_catalog):
    """P-M1：選單項目不可以引用被藏起的按鈕（目錄與守門同一份）。"""
    _hide_del_endpoint(synthetic_catalog)
    menu = next(p for p in catalog.layout_points("zz_syn") if p["id"] == BASE + "/menu:row")
    assert menu["items"] == [BASE + "/action:edit"]
    assert _mod(catalog.build(), "zz_syn")["points"] == catalog.layout_points("zz_syn")
    # 用原本的順序 reorder（含藏起的按鈕）⇒ 擋
    assert _paths([{"op": "reorder", "target": BASE + "/menu:row",
                    "order": [BASE + "/action:edit", BASE + "/action:del"]}]) == ["[0].order"]


def test_menu_with_all_buttons_hidden_is_hidden(synthetic_catalog):
    _hide_del_endpoint(synthetic_catalog)
    synthetic_catalog["customization"]["pages"][0]["menus"][0]["items"] = ["del"]
    mod = _mod(catalog.build(), "zz_syn")
    assert BASE + "/menu:row" not in {p["id"] for p in mod["points"]}
    assert BASE + "/menu:row" in {p["point"] for p in mod["problems"]}
    assert _paths([{"op": "hide", "target": BASE + "/menu:row"}]) == ["[0].target"]


def test_unloaded_module_points_are_rejected(synthetic_catalog):
    """P-M1：模組沒有載入（停用／未授權／失敗）⇒ 它的點不可以通過守門。"""
    off = copy.deepcopy(synthetic_catalog)
    off["key"] = "zz_off"
    registry.set_state("zz_off", registry.STATE_DISABLED, "停用", manifest=off)
    op = {"op": "hide", "target": "zz_off:zz-syn.html/action:edit"}
    assert catalog.layout_points("zz_off") == []
    assert not any(p["id"].startswith("zz_off:") for p in catalog.layout_points())
    assert _paths([op], "zz_off") == ["[0].target"]
    assert _paths([op], None) == ["[0].target"]
    # 正對照：同一份描述載入之後就通過
    registry.register(registry.LoadedModule(key="zz_off", manifest=off,
                                            spec=registry.ModuleSpec(key="zz_off", routers=[_router()])))
    assert _check([op], "zz_off") == []
    # 指定模組 ⇒ 只看那個模組的點（別的模組已載入也不算）
    assert _paths([op], "zz_syn") == ["[0].target"]


def test_action_moves_only_into_same_page_menu(synthetic_catalog):
    """P-S1：按鈕只能放進同一頁的頁內選單（別頁的選單 ⇒ 擋）。"""
    m = synthetic_catalog
    m["pages"].append({"path": "zz-syn2.html"})
    m["customization"]["pages"].append({"page": "zz-syn2.html", "lists": [], "forms": [], "exports": [],
                                        "actions": [{"key": "go", "label": "前往"}],
                                        "menus": [{"key": "more", "label": "更多", "items": ["go"]}]})
    assert C.validate_manifest(m) == []
    other = "zz_syn:zz-syn2.html/menu:more"
    assert _paths([{"op": "move", "target": BASE + "/action:save", "to": other}]) == ["[0].to"]
    assert _check([{"op": "move", "target": "zz_syn:zz-syn2.html/action:go", "to": other}]) == []


def test_output_points_need_output_engine(synthetic_catalog):
    """P-M2：outputs 區段不在 ⇒ 輸出點不在 layout_points、select_template 一律擋（與 output_problems 同一判準）。"""
    catalog.restore({})
    op = {"op": "select_template", "target": "zz_syn:output:voucher", "template": "zz_tpl"}
    assert "zz_syn:output:voucher" not in {p["id"] for p in catalog.layout_points("zz_syn")}
    assert _paths([op]) == ["[0].target"]


def test_select_template_choices_come_from_output_engine(synthetic_catalog):
    """可選版型＝目錄 outputs 區段的 templates（不是模組自己寫的那一個）。"""
    catalog.restore({})
    catalog.register_section("outputs", "helpers.doc_template",
                             lambda: {"templates": [{"key": "zz_tpl"}, {"key": "zz_tpl2"}]})
    out = next(p for p in catalog.layout_points("zz_syn") if p["kind"] == "output")
    assert out["templates"] == ["zz_tpl", "zz_tpl2"]
    assert _check([{"op": "select_template", "target": out["id"], "template": "zz_tpl2"}]) == []


# ── 單一入口守門：沒有別的取點路徑 ─────────────────────────────────────────

_BACKEND = Path(__file__).resolve().parents[2]
_PRIVATE = ("_raw_points", "_check_ops")
#: 唯一允許的呼叫點：{檔案: {私有函式: 允許呼叫它的函式}}
_ALLOWED = {"core/catalog.py": {"_raw_points": "_module_points", "_check_ops": "check_layout"}}


def _private_uses(source):
    """一個檔案裡用到 `_raw_points`／`_check_ops` 的地方 ⇒ [(名字, 所在函式)]（屬性、名稱、import 都算）。"""
    found = []

    def walk(node, fn):
        for ch in ast.iter_child_nodes(node):
            f = ch.name if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
            if isinstance(ch, ast.Attribute) and ch.attr in _PRIVATE:
                found.append((ch.attr, fn))
            elif isinstance(ch, ast.Name) and ch.id in _PRIVATE:
                found.append((ch.id, fn))
            elif isinstance(ch, ast.ImportFrom) and any(a.name in _PRIVATE for a in ch.names):
                found.append(("import", fn))
            walk(ch, f)
    walk(ast.parse(source), None)
    return found


def _entry_violations(files):
    bad = []
    for rel, src in files:
        if rel == "core/customization.py":
            continue
        allowed = _ALLOWED.get(rel, {})
        for name, fn in _private_uses(src):
            if fn is None or allowed.get(name) != fn:       # 模組層一律不准（None 不可以等於「沒有登記」）
                bad.append("%s：%s 在 %s" % (rel, name, fn or "模組層"))
    return bad


def _product_files():
    out = []
    for p in _BACKEND.rglob("*.py"):
        parts = p.relative_to(_BACKEND).parts
        if "tests" in parts or any(x.startswith(".") for x in parts):
            continue
        out.append((p.relative_to(_BACKEND).as_posix(), p.read_text(encoding="utf-8")))
    return out


def test_only_one_way_to_get_points():
    """P-M1：目錄與守門只經過 layout_points()；未過濾的點在產品碼裡沒有別的取法。"""
    files = _product_files()
    assert _entry_violations(files) == []
    # 舊的公開名稱不可以回來（回來就是第二個入口）
    assert not hasattr(C, "points") and not hasattr(C, "check_layout")
    # build() 與 layout_points() 都走 _module_points；check_layout 走 layout_points
    calls = {}
    for node in ast.walk(ast.parse(dict(files)["core/catalog.py"])):
        if isinstance(node, ast.FunctionDef):
            calls[node.name] = {c.func.id for c in ast.walk(node)
                                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "_module_points" in calls["build"] and "_module_points" in calls["layout_points"]
    assert "layout_points" in calls["check_layout"]


def test_entry_guard_positive_control():
    """守門的正對照：別處呼叫未過濾的點 ⇒ 亮；允許處換到別的函式 ⇒ 亮。"""
    leak = "from core import customization\ndef f(m):\n    return customization._raw_points(m)\n"
    assert _entry_violations([("routers/zz.py", leak)]) == ["routers/zz.py：_raw_points 在 f"]
    wrong_fn = "def build():\n    return customization._raw_points({})\n"
    assert _entry_violations([("core/catalog.py", wrong_fn)]) == ["core/catalog.py：_raw_points 在 build"]
    imp = "from core.customization import _check_ops\n"
    assert _entry_violations([("helpers/zz.py", imp)]) == ["helpers/zz.py：import 在 模組層"]
    assert any(rel == "core/catalog.py" for rel, _ in _product_files())      # 掃描範圍含已知的那一個


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
        assert {p["id"] for p in entry["points"]} == {p["id"] for p in C._raw_points(m.manifest)}, m.key
        assert entry["points"] == catalog.layout_points(m.key), m.key        # 目錄與守門同一份
