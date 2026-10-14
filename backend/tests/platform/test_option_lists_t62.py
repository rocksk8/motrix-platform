# -*- coding: utf-8 -*-
"""census #4 選項清單（kind option_list）：模型與驗證、OFF 逐項等於今天的清單、遮蔽／權限、治理（中性／收緊）、料件分類實際生效。
設定 builder_option_lists.enabled 預設關，且必須同時開啟 builder_governance 才生效。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from helpers import option_lists as OL

ROOT = Path(__file__).resolve().parents[3]
NODE = shutil.which("node")


def _body(vals):
    return {"version": 1, "values": vals}


def _v(value, label=None, **kw):
    return dict({"value": value, "label": label or value}, **kw)


DEFAULT_CT = [_v("一般", "一般客戶"), _v("VIP", "VIP 客戶"), _v("潛在", "潛在客戶")]
DEFAULT_PC = [_v(d["value"], d["value"], prefix=d["prefix"]) for d in OL.BUILTIN["part_category"]["defaults"]]


def _bad(key, body, live=None):
    return OL.definition_problems(key, body, live={} if live is None else live)


def _paths(p):
    return {x["path"] for x in p}


# ── OFF = 今天寫死的清單（逐項對照前端／後端原始碼）────────────────────────────────
def test_builtin_defaults_equal_the_hard_coded_lists_in_the_pages_and_backend():
    from helpers.part_catalog import PART_CATEGORIES
    cust = (ROOT / "frontend" / "pages" / "customers.html").read_text(encoding="utf-8")
    sup = (ROOT / "frontend" / "pages" / "suppliers.html").read_text(encoding="utf-8")
    ct = re.search(r"CUSTOMER_TYPES:\s*\[([^\]]*)\]", cust).group(1)
    assert [x.strip().strip("'") for x in ct.split(",")] == [d["value"] for d in OL.BUILTIN["customer_type"]["defaults"]]
    sc = re.search(r"SUPPLIER_CATEGORIES:\s*\[([^\]]*)\]", sup).group(1)
    assert [x.strip().strip("'") for x in sc.split(",")] == [d["value"] for d in OL.BUILTIN["supplier_category"]["defaults"]]
    labels = re.findall(r'<option value="(一般|VIP|潛在)">([^<]+)</option>', cust)
    # 客戶頁原本的下拉文字（已改成清單渲染，這裡對照 CUSTOMER_TYPE_ITEMS 與預設）
    items = re.search(r"CUSTOMER_TYPE_ITEMS:\s*\[(.*?)\],\n", cust, re.S).group(1)
    pairs = re.findall(r"value:\s*'([^']+)',\s*label:\s*'([^']+)'", items)
    assert pairs == [(d["value"], d["label"]) for d in OL.BUILTIN["customer_type"]["defaults"]] and labels == []
    assert [(d["value"], d["prefix"]) for d in OL.BUILTIN["part_category"]["defaults"]] == [(c["name"], c["prefix"]) for c in PART_CATEGORIES]


def test_effective_is_the_default_when_off_and_part_catalog_is_unchanged(monkeypatch):
    from helpers import part_catalog as PC
    monkeypatch.setattr(OL, "enabled", lambda conn=None: False)
    for k, spec in OL.BUILTIN.items():
        assert OL.effective(k) == [dict(d, disabled=False) for d in spec["defaults"]]
    assert PC.categories() == PC.PART_CATEGORIES, "旗標關 ⇒ 料件分類與寫死的清單逐項相同"
    assert PC.prefix_for("交換器") == "SW" and PC.prefix_for("不存在") is None
    assert OL.lists_for_menu() is None, "旗標關 ⇒ 選單回應不帶 optionLists"


def test_setting_default_is_off_and_registered():
    from helpers import settings_groups  # noqa: F401
    from helpers import settings_registry as SR
    f = {x["key"]: x for x in SR.groups()["builder_option_lists"]["fields"]}["enabled"]
    assert f["default"] == 0 and (f["min"], f["max"]) == (0, 1)


def test_enabled_needs_governance_and_fails_closed(monkeypatch):
    import helpers.settings_registry as SR
    vals = {"builder_option_lists": 1, "builder_governance": 0}
    monkeypatch.setattr(SR, "get", lambda g, f, conn=None: vals[g])
    assert OL.enabled() is False
    vals["builder_governance"] = 1
    assert OL.enabled() is True
    monkeypatch.setattr(SR, "get", lambda g, f, conn=None: (_ for _ in ()).throw(RuntimeError("x")))
    assert OL.enabled() is False


# ── 驗證 ──────────────────────────────────────────────────────────────────
def test_defaults_are_valid_and_new_values_can_be_added_relabelled_reordered_disabled():
    assert _bad("customer_type", _body(DEFAULT_CT)) == []
    ok = _body([_v("潛在", "潛在客戶（開發中）"), _v("一般", "一般客戶"), _v("VIP", "VIP 客戶", disabled=True), _v("合作夥伴")])
    assert _bad("customer_type", ok) == [], "新增、改名、重排、停用都可以"


@pytest.mark.parametrize("vals,path", [
    ([], "values"),
    ([_v("一般", "一般客戶"), _v("VIP", "VIP 客戶")], "values"),                                   # 少了預設的「潛在」
    (DEFAULT_CT + [_v("一般", "另一個")], "values[3].value"),                                      # 值重複
    (DEFAULT_CT + [_v("新", "一般客戶")], "values[3].label"),                                      # 顯示名稱重複
    (DEFAULT_CT + [_v("=SUM(1)")], "values[3].value"),
    (DEFAULT_CT + [_v("{x}")], "values[3].value"),
    (DEFAULT_CT + [_v("a​b")], "values[3].value"),
    (DEFAULT_CT + [_v("aㅤb")], "values[3].value"),
    (DEFAULT_CT + [_v("x" * 21)], "values[3].value"),
    (DEFAULT_CT + [_v(" 空白")], "values[3].value"),
    (DEFAULT_CT + [dict(_v("新"), prefix="ABC")], "values[3].prefix"),                           # customer_type 沒有 prefix
    (DEFAULT_CT + [dict(_v("新"), onclick="x")], "values[3].onclick"),
    ([dict(d, disabled=True) for d in DEFAULT_CT], "values"),                                    # 全部停用
    (DEFAULT_CT + [dict(_v("新"), disabled="yes")], "values[3].disabled"),
])
def test_validator_rejects(vals, path):
    assert path in _paths(_bad("customer_type", _body(vals))), _bad("customer_type", _body(vals))


def test_validator_top_level_and_unknown_list():
    assert "version" in _paths(_bad("customer_type", {"version": 2, "values": DEFAULT_CT}))
    assert "x" in _paths(_bad("customer_type", {"version": 1, "values": DEFAULT_CT, "x": 1}))
    assert _bad("nope", _body(DEFAULT_CT)) and _bad("customer_type", [1])
    assert "values" in _paths(_bad("customer_type", _body([_v("v%d" % i) for i in range(41)] + DEFAULT_CT)))


def test_published_values_cannot_be_removed_or_renamed_only_disabled():
    live = {"一般": _v("一般", "一般客戶"), "VIP": _v("VIP", "VIP 客戶"), "潛在": _v("潛在", "潛在客戶"), "合作夥伴": _v("合作夥伴")}
    without = _body(DEFAULT_CT)                                                                  # 少了已發布的「合作夥伴」
    p = OL.definition_problems("customer_type", without, live=live)
    assert any("合作夥伴" in x["message"] and "不能刪除" in x["message"] for x in p)
    disabled = _body(DEFAULT_CT + [_v("合作夥伴", disabled=True)])
    assert OL.definition_problems("customer_type", disabled, live=live) == [], "改成停用就可以"


def test_lists_that_are_matched_by_name_elsewhere_cannot_be_relabelled():
    ok = _body(DEFAULT_PC + [dict(_v("工程服務"), prefix="SRV")])
    assert _bad("part_category", ok) == [], "料件分類可以新增（要給前綴）"
    renamed = _body([dict(DEFAULT_PC[0], label="網路設備")] + DEFAULT_PC[1:])
    assert "values[0].label" in _paths(_bad("part_category", renamed)), "報表／科目對照用名稱比對 ⇒ 不能改顯示名稱"
    for bad_prefix in ("net", "N", "TOOLONG", "N1", ""):
        assert "values[6].prefix" in _paths(_bad("part_category", _body(DEFAULT_PC + [dict(_v("甲"), prefix=bad_prefix)]))), bad_prefix
    assert "values[6].prefix" in _paths(_bad("part_category", _body(DEFAULT_PC + [dict(_v("甲"), prefix="NET")]))), "前綴不能重複"
    changed = _body([dict(DEFAULT_PC[0], prefix="NW")] + DEFAULT_PC[1:])
    assert any("前綴不能改" in x["message"] for x in _bad("part_category", changed)), "預設分類的前綴不能改（已經有料號在用）"
    assert _bad("part_unit", _body([_v("台"), _v("個")])) == [] and "values[0].label" in _paths(_bad("part_unit", _body([_v("台", "台灣"), _v("個")])))


def test_preview_lists_the_screens_that_use_the_list_and_flags_disabled_values():
    pv = OL.preview("customer_type", _body(DEFAULT_CT + [_v("合作夥伴"), _v("暫停", disabled=True)]))
    assert pv["usedBy"] and any("客戶類型" in u for u in pv["usedBy"])
    assert pv["added"] == ["合作夥伴", "暫停"] and pv["disabled"] == ["暫停"]
    assert any("停用" in w for w in pv["warnings"]) and any("不統計" in w for w in pv["warnings"])
    with pytest.raises(ValueError):
        OL.preview("customer_type", _body([]))
    with pytest.raises(LookupError):
        OL.preview("nope", _body(DEFAULT_CT))


def test_pipeline_classes():
    from routers.def_pipeline import classify
    a = _body(DEFAULT_CT)
    assert classify("option_list", a, _body([_v("潛在", "潛在客戶"), _v("一般", "一般客戶"), _v("VIP", "貴賓客戶")]))[0] == "neutral", "重排／改名 ⇒ 中性"
    assert classify("option_list", a, _body(DEFAULT_CT + [_v("合作夥伴")]))[0] == "neutral", "新增選項 ⇒ 中性（只影響下拉怎麼列）"
    assert classify("option_list", a, _body([_v("一般", "一般客戶"), _v("VIP", "VIP 客戶", disabled=True), _v("潛在", "潛在客戶")]))[0] == "tighten"
    assert classify("option_list", a, dict(a, extra=1))[0] == "loosen"
    assert classify("option_list", _body(DEFAULT_PC), _body([dict(DEFAULT_PC[0], prefix="NW")] + DEFAULT_PC[1:]))[0] == "loosen"


# ── API ───────────────────────────────────────────────────────────────────
def _login(client, make_user, name, role="superadmin", modules=None):
    u, pw = make_user(username=name, role=role, **({"modules": modules} if modules is not None else {}))[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}


def _flag(monkeypatch, on, governance=False):
    monkeypatch.setattr(OL, "enabled", lambda conn=None: on)
    import routers.def_governance as G
    import routers.def_pipeline as P
    import routers.definitions as DF
    monkeypatch.setattr(G, "enabled", lambda conn=None: governance)
    monkeypatch.setattr(P, "enabled", lambda conn=None: governance)
    monkeypatch.setattr(DF, "_governance_enabled", lambda conn=None: governance)


def _publish(client, hd, key, body, preview_hash=None, note="t"):
    url = "/api/definitions/option_list/%s" % key
    s = client.put(url + "/draft?scope=company", json={"body": body}, headers=hd)
    assert s.status_code == 200, s.text
    p = {"note": note}
    if preview_hash:
        p["preview_hash"] = preview_hash
    return client.post(url + "/publish?scope=company", json=p, headers=hd)


def test_status_and_preview_endpoints_permissions(client, make_user, monkeypatch):
    h_sa = _login(client, make_user, "ol_sa1")
    h_ad = _login(client, make_user, "ol_ad1", "admin", modules=["customer"])
    url = "/api/option-lists/customer_type/%s"
    _flag(monkeypatch, False)
    assert client.get(url % "status", headers=h_sa).json() == {"enabled": False, "canEdit": False}
    assert client.post(url % "preview", json={"template": _body(DEFAULT_CT)}, headers=h_sa).status_code == 404
    _flag(monkeypatch, True)
    s = client.get(url % "status", headers=h_sa).json()
    assert s["enabled"] and s["canEdit"] and s["current"][0]["value"] == "一般" and s["usedBy"]
    assert client.get(url % "status", headers=h_ad).json() == {"enabled": True, "canEdit": False}
    assert client.post(url % "preview", json={"template": _body(DEFAULT_CT)}, headers=h_ad).status_code == 403
    assert client.post(url % "preview", json={"template": _body(DEFAULT_CT)}).status_code in (401, 403)
    assert client.get("/api/option-lists/nope/status", headers=h_sa).status_code == 404
    assert client.post(url % "preview", json={"template": _body([])}, headers=h_sa).status_code == 422
    ok = client.post(url % "preview", json={"template": _body(DEFAULT_CT + [_v("合作夥伴")])}, headers=h_sa)
    assert ok.status_code == 200 and ok.json()["added"] == ["合作夥伴"]


def test_definitions_are_admin_only_and_kind_is_lazy(client, make_user, monkeypatch):
    import core.definitions as D
    h_sa = _login(client, make_user, "ol_sa2")
    h_ad = _login(client, make_user, "ol_ad2", "admin", modules=["customer"])
    saved = D._EXTRA_KINDS.pop(OL.KIND, None)
    try:
        _flag(monkeypatch, False)
        assert OL.KIND not in [k["kind"] for k in client.get("/api/definition-kinds", headers=h_sa).json()["kinds"]]
        _flag(monkeypatch, True)
        assert OL.KIND in [k["kind"] for k in client.get("/api/definition-kinds", headers=h_sa).json()["kinds"]]
        d = "/api/definitions/option_list/customer_type"
        assert client.get(d + "?scope=company", headers=h_ad).status_code in (401, 403)
        assert client.put(d + "/draft?scope=company", json={"body": _body(DEFAULT_CT)}, headers=h_ad).status_code in (401, 403)
        _flag(monkeypatch, False)
        v = client.post(d + "/validate", json={"body": _body(DEFAULT_CT)}, headers=h_sa)
        assert v.status_code == 200 and any(OL.OFF_REASON in p["message"] for p in v.json()["problems"])
    finally:
        D._EXTRA_KINDS.pop(OL.KIND, None)
        if saved is not None:
            D._EXTRA_KINDS[OL.KIND] = saved


def test_menu_response_carries_published_lists_for_everyone_and_the_editor_key_for_superadmin_only(client, make_user, monkeypatch):
    h_sa = _login(client, make_user, "ol_sa3")
    h_ad = _login(client, make_user, "ol_ad3", "admin", modules=["customer"])
    _flag(monkeypatch, False)
    for h in (h_sa, h_ad):
        m = client.get("/api/platform/menu", headers=h).json()
        assert "optionLists" not in m and "builderOptionLists" not in m
    _flag(monkeypatch, True)
    m = client.get("/api/platform/menu", headers=h_sa).json()
    assert m.get("builderOptionLists") is True and "optionLists" not in m, "開了但沒發布 ⇒ 沒有 optionLists（頁面照用預設）"
    assert "builderOptionLists" not in client.get("/api/platform/menu", headers=h_ad).json()
    r = _publish(client, h_sa, "customer_type", _body([_v("一般", "一般客戶"), _v("VIP", "貴賓客戶"), _v("潛在", "潛在客戶"), _v("合作夥伴")]))
    assert r.status_code == 200 and not r.json().get("pending"), r.text
    for h in (h_sa, h_ad):
        ol = client.get("/api/platform/menu", headers=h).json()["optionLists"]
        assert [x["value"] for x in ol["customer_type"]] == ["一般", "VIP", "潛在", "合作夥伴"] and ol["customer_type"][1]["label"] == "貴賓客戶"
        assert set(ol) == {"customer_type"}, "只帶已發布的清單"
    _flag(monkeypatch, False)
    assert "optionLists" not in client.get("/api/platform/menu", headers=h_ad).json(), "旗標關回去 ⇒ 不再帶"


def test_governance_neutral_publishes_immediately_tighten_too_and_removal_is_blocked(client, make_user, monkeypatch):
    h = _login(client, make_user, "ol_sa4")
    _flag(monkeypatch, True, governance=True)
    url = "/api/definitions/option_list/supplier_category"
    sup = [_v(x) for x in ("原廠", "代理商", "製造商", "服務商", "其他")]
    client.put(url + "/draft?scope=company", json={"body": _body(sup + [_v("經銷商")])}, headers=h)
    no_hash = client.post(url + "/publish?scope=company", json={"note": "x"}, headers=h)
    assert no_hash.status_code == 409 and no_hash.json()["code"] == "preview_required"
    hash_ = client.get("/api/def-governance/option_list/supplier_category/impact?scope=company", headers=h).json()["previewHash"]
    r = client.post(url + "/publish?scope=company", json={"note": "x", "preview_hash": hash_}, headers=h)
    assert r.status_code == 200 and not r.json().get("pending"), "新增選項是中性 ⇒ 不用第二位核准"
    client.put(url + "/draft?scope=company", json={"body": _body(sup)}, headers=h)                 # 少了已發布的「經銷商」
    bad = client.post(url + "/validate", json={"body": _body(sup)}, headers=h).json()["problems"]
    assert any("經銷商" in p["message"] and "不能刪除" in p["message"] for p in bad)
    dis = _body(sup + [_v("經銷商", disabled=True)])
    client.put(url + "/draft?scope=company", json={"body": dis}, headers=h)
    h2 = client.get("/api/def-governance/option_list/supplier_category/impact?scope=company", headers=h).json()["previewHash"]
    r2 = client.post(url + "/publish?scope=company", json={"note": "停用", "preview_hash": h2}, headers=h)
    assert r2.status_code == 200 and not r2.json().get("pending"), "停用＝收緊 ⇒ 立即生效"


def test_part_category_list_drives_the_parts_endpoint_and_prefix(client, make_user, monkeypatch):
    h = _login(client, make_user, "ol_sa5")
    _flag(monkeypatch, False)
    off = client.get("/api/parts/categories", headers=h).json()
    from helpers.part_catalog import PART_CATEGORIES
    assert off == {"items": PART_CATEGORIES}, "旗標關 ⇒ 回應與今天逐位元相同"
    _flag(monkeypatch, True)
    new = _body(DEFAULT_PC + [dict(_v("工程服務"), prefix="SRV")])
    assert _publish(client, h, "part_category", new).status_code == 200
    items = client.get("/api/parts/categories", headers=h).json()["items"]
    assert items[-1] == {"name": "工程服務", "prefix": "SRV"} and len(items) == 7
    r = client.post("/api/parts", json={"name": "顧問費", "category": "工程服務"}, headers=h)
    assert r.status_code == 201 and r.json()["part_no"].startswith("SRV-"), r.text
    dis = _body([dict(x, disabled=True) if x["value"] == "其他" else x for x in new["values"]])
    assert _publish(client, h, "part_category", dis).status_code == 200
    names = [c["name"] for c in client.get("/api/parts/categories", headers=h).json()["items"]]
    assert "其他" not in names and "網通設備" in names, "停用的分類新增／編輯時不能再選"


# ── 前端（node）────────────────────────────────────────────────────────────
@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_motrix_options_returns_the_page_defaults_when_there_is_no_published_list_and_the_list_otherwise():
    js = r"""
    const fs = require('fs'); global.window = global
    eval(fs.readFileSync(process.argv[1], 'utf8'))
    const O = window.MotrixOptions, D = [{ value: '一般', label: '一般客戶' }, { value: 'VIP', label: 'VIP 客戶' }]
    const off = { values: O.values('customer_type', ['一般', 'VIP']), options: O.options('customer_type', D, '舊值'), first: O.firstValue('part_unit', '台'), custom: O.custom('customer_type') }
    window.MOTRIX_OPTION_LISTS = { customer_type: [{ value: '一般', label: '一般客戶', disabled: false }, { value: 'VIP', label: '貴賓', disabled: true }, { value: '新', label: '新', disabled: false }], part_unit: [{ value: '個', label: '個', disabled: true }, { value: '組', label: '組', disabled: false }] }
    const on = { values: O.values('customer_type', ['x']), opt: O.options('customer_type', D, 'VIP'), opt2: O.options('customer_type', D, '更舊'), first: O.firstValue('part_unit', '台'), custom: O.custom('customer_type'), other: O.values('supplier_category', ['原廠']) }
    console.log(JSON.stringify({ off, on }))
    """
    out = subprocess.run([NODE, "-e", js, str(ROOT / "frontend" / "static" / "option-lists.js")], capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:800]
    r = json.loads(out.stdout.decode("utf-8"))
    assert r["off"] == {"values": ["一般", "VIP"], "options": [{"value": "一般", "label": "一般客戶"}, {"value": "VIP", "label": "VIP 客戶"}], "first": "台", "custom": False}, "沒發布 ⇒ 完全是頁面的預設，不加任何項目"
    assert r["on"]["values"] == ["一般", "新"] and r["on"]["first"] == "組" and r["on"]["custom"] is True
    assert [o["value"] for o in r["on"]["opt"]] == ["一般", "新", "VIP"] and r["on"]["opt"][-1]["label"] == "貴賓（已停用）", "編輯舊資料時，已停用的值仍列出來"
    assert r["on"]["opt2"][-1]["label"] == "更舊（舊值）"
    assert r["on"]["other"] == ["原廠"], "沒發布的清單照預設"


def test_pages_wire_the_lists_and_declare_the_editor_meta_but_do_not_load_the_editor_script():
    for page, ids in (("customers", "customer_type"), ("suppliers", "supplier_category"), ("parts", "part_category,part_unit")):
        src = (ROOT / "frontend" / "pages" / (page + ".html")).read_text(encoding="utf-8")
        assert '<script src="../static/option-lists.js"></script>' in src, page
        assert '<meta name="motrix-option-lists" content="%s">' % ids in src, page
        assert "option-list-editor.js" not in src, "頁面不直接載入編輯器（關著時不能多請求）"
        assert "motrix-options" in src and "optVer" in src
    sb = (ROOT / "frontend" / "static" / "sidebar.js").read_text(encoding="utf-8")
    assert "d.optionLists" in sb and "d.builderOptionLists" in sb and "/static/option-list-editor.js" in sb
    parts = (ROOT / "frontend" / "pages" / "parts.html").read_text(encoding="utf-8")
    assert parts.count("unit: this.defaultUnit()") == 1 and "unit: '台', cost: 0, listPrice: 0, safetyStock: 0, category: '', note: '', saving: false" in parts
