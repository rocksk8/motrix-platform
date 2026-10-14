# -*- coding: utf-8 -*-
"""L1 共用主檔頁面（客戶頁）的可自訂點：虛擬擁有者 `core`（core/l1_customization.json）——不是模組、不可停用，但版面端點與驗證器認得它。

證明：登記檔通過 validate_manifest；核心欄位 D6（公司名稱、統一編號、狀態）不可隱藏；`layout_points(None)` 不含 core（原有目錄不變）；
GET /api/layout/core 對任何登入者可讀自己角色的版面；發布／套用走既有的版面管線；不存在的模組鍵仍 404。
"""
import json
from pathlib import Path

import pytest

from core import catalog, customization

ROOT = Path(__file__).resolve().parents[3]
PREFIX = "core:customers.html/list:customers/column:"
CORE = ("name", "taxId", "status")
OTHER = ("alias", "contact", "phone", "industry", "owner", "quoteCount", "lastContact")


def test_registry_file_is_valid_and_has_no_menu_endpoints_or_outputs():
    m = json.loads((ROOT / "backend" / "core" / "l1_customization.json").read_text(encoding="utf-8"))
    assert customization.validate_manifest(m) == [] and m["key"] == "core"
    assert m["customization"]["outputs"] == [] and not any("menu" in p for p in m["pages"])           # 側欄仍只由 menu_l1.json 管
    cols = [c["field"] for c in m["customization"]["pages"][0]["lists"][0]["columns"]]
    assert cols == ["name", "alias", "taxId", "contact", "phone", "industry", "owner", "quoteCount", "lastContact", "status"]
    assert {f["key"] for f in m["customization"]["fields"]["customer"] if f["core"]} == set(CORE)
    assert "amount" not in json.dumps(m) and "total" not in json.dumps(m)                           # 客戶頁沒有金額欄；累計報價是件數


def test_points_core_flags_and_owner_rules():
    pts = catalog.layout_points("core")
    ids = {p["id"] for p in pts}
    assert {PREFIX + c for c in CORE + OTHER} <= ids
    assert all(p["core"] for p in pts if p.get("field") in CORE) and not any(p["core"] for p in pts if p.get("field") in OTHER)
    assert catalog.owner_loaded("core") is True and catalog.owner_loaded("no_such_mod") is False
    assert not [p for p in catalog.layout_points() if p["id"].startswith("core:")]                    # 原有「全部模組」目錄不含虛擬擁有者


@pytest.mark.parametrize("field", CORE)
def test_core_fields_cannot_be_hidden(field):
    assert catalog.check_layout("core", [{"op": "hide", "target": PREFIX + field}])


@pytest.mark.parametrize("field", OTHER)
def test_other_fields_can_be_hidden_relabeled_and_moved(field):
    assert catalog.check_layout("core", [{"op": "hide", "target": PREFIX + field}]) == []
    assert catalog.check_layout("core", [{"op": "relabel", "target": PREFIX + field, "label": "x"}]) == []


@pytest.fixture()
def hdr(client, make_user):
    def mk(name, role):
        u, p = make_user(username=name, role=role)
        return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    return mk


def test_layout_endpoint_serves_core_and_applies_a_published_layout(client, hdr):
    sa, sales = hdr("l1_sa", "superadmin"), hdr("l1_sales", "sales")
    r = client.get("/api/layout/core", headers=sales)
    assert r.status_code == 200 and r.json()["module"] == "core" and r.json()["ops"] == [] and len(r.json()["points"]) == 11
    assert client.get("/api/layout/core").status_code == 401
    assert client.get("/api/layout/no_such_mod", headers=sales).status_code == 404
    base = "/api/definitions/layout/module:core"
    bad = client.put(base + "/draft", headers=sa, json={"body": {"ops": [{"op": "hide", "target": PREFIX + "taxId"}]}})
    assert bad.status_code in (200, 422) and ((bad.json().get("problems") or bad.json().get("detail")) if bad.status_code == 422 else bad.json().get("problems"))
    ok = {"ops": [{"op": "hide", "target": PREFIX + "alias"}, {"op": "relabel", "target": PREFIX + "owner", "label": "業務"}]}
    assert client.put(base + "/draft", headers=sa, json={"body": ok}).status_code == 200
    assert client.post(base + "/publish", headers=sa, json={"note": "n"}).status_code == 200
    ops = client.get("/api/layout/core", headers=sales).json()["ops"]
    assert {"op": "hide", "target": PREFIX + "alias"} in ops and any(o["op"] == "relabel" for o in ops)


def test_default_layout_for_core_exists_and_unknown_module_has_none():
    from routers import definitions as R
    assert R._default_layout("module:core") == {"ops": []}
    assert R._default_layout("module:no_such_mod") is None


def test_full_catalog_points_are_exactly_the_loaded_modules_and_never_core(client):
    """OFF 同一性：『全部模組』的點＝各已載入模組自己的點串起來；虛擬擁有者 core 不混進去，build() 也沒有 core 區段。"""
    from core import registry
    mods = sorted(registry.loaded(), key=lambda x: x.key)
    assert mods, "測試環境沒有載入任何模組（這題會是空轉）"
    expect = []
    for m in mods:
        expect += catalog.layout_points(m.key)
    assert catalog.layout_points() == expect and expect
    assert not any(p["id"].startswith("core:") for p in expect)
    built = catalog.build()
    assert "core" not in {m["key"] for m in built["modules"]}
    assert not any(p["id"].startswith("core:") for m in built["modules"] for p in m["points"])


def test_core_is_not_a_module_so_it_cannot_be_disabled_or_licensed(client, hdr):
    from core import registry
    sa = hdr("l1_sa2", "superadmin")
    assert registry.is_loaded("core") is False                                       # 不是模組
    assert not (ROOT / "backend" / "modules" / "core").exists()
    assert "core" not in {r["key"] for r in client.get("/api/system/modules", headers=sa).json()["modules"]}
    for enabled in (False, True):
        assert client.put("/api/system/modules/core", headers=sa, json={"enabled": enabled}).status_code == 404       # 沒有開關可關
    assert catalog.owner_loaded("core") is True and catalog.layout_points("core")      # 照樣可用


def test_no_module_may_take_the_reserved_owner_key_core():
    """`owner_loaded("core")` 對 core 永遠為真：若真有模組叫 core，它會被虛擬擁有者無聲蓋掉。登記表與已載入模組都不准出現這個鍵。"""
    from core import registry, source_tree
    keys = []
    for d in source_tree.module_dirs():
        keys.append(json.loads((d / "module.json").read_text(encoding="utf-8")).get("key"))
    assert keys and "core" not in keys and "core" not in {d.name for d in source_tree.module_dirs()}
    assert "core" not in {m.key for m in registry.loaded()}


def test_l1_manifest_does_not_cache_a_transient_failure(monkeypatch, tmp_path):
    good = (ROOT / "backend" / "core" / "l1_customization.json")
    monkeypatch.setattr(catalog, "_l1_cache", [])
    monkeypatch.setattr(catalog, "_l1_last_error", [0.0])
    monkeypatch.setattr(catalog, "_L1_CUSTOMIZATION", tmp_path / "missing.json")
    assert catalog.l1_manifest() == {} and catalog.layout_points("core") == []         # 讀不到 ⇒ 沒有點，但不快取
    assert catalog._l1_cache == []                                                    # noqa: SLF001
    monkeypatch.setattr(catalog, "_L1_CUSTOMIZATION", good)
    assert catalog.l1_manifest()["key"] == "core" and len(catalog.layout_points("core")) == 11   # 下一次呼叫就恢復
    monkeypatch.setattr(catalog, "_L1_CUSTOMIZATION", tmp_path / "missing.json")
    assert catalog.l1_manifest()["key"] == "core"                                      # 成功之後才快取


def test_throttled_error_log_for_a_broken_registry(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(catalog, "_l1_cache", [])
    monkeypatch.setattr(catalog, "_l1_last_error", [0.0])
    monkeypatch.setattr(catalog, "_L1_CUSTOMIZATION", tmp_path / "missing.json")
    with caplog.at_level("ERROR"):
        for _ in range(5):
            catalog.l1_manifest()
    assert len([r for r in caplog.records if "l1_customization" in r.getMessage()]) == 1
