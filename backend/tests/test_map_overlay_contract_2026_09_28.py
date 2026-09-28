# -*- coding: utf-8 -*-
"""IP-101 `map.overlay`（L1）：覆蓋層清單與腳本網址由 L1 依已載入模組的宣告產生；覆蓋層腳本只准用契約。

LODGING-NEARBY.md §3.6.1 守門 ③④⑤⑧（①②⑥⑦ 在 tests/test_e2e_map_overlay_contract_2026_09_28.py）。
用合成模組（registry snapshot／restore＋暫存 MODULES_DIR），不綁任何真的 L2 模組（MODULE-GUIDE §7）。
"""
import re
from pathlib import Path

import pytest

from core import loader, registry
from core.registry import LoadedModule, ModuleSpec
from helpers import map_overlays
from tests.test_custom_records_no_js_html_sink_2026_09_28 import check, sink_sites

REPO = Path(__file__).resolve().parents[2]
JS_OK = "window.MotrixMapOverlay.register('zz', {mount: function (api) { api.panel('合成') }, unmount: function () {}})\n"


@pytest.fixture()
def synth(tmp_path, monkeypatch):
    """合成模組資料夾＋登錄；回傳 load(key, decl, files)。"""
    snap = registry.snapshot()
    monkeypatch.setattr(loader, "MODULES_DIR", str(tmp_path))

    def load(key, decl, files=None):
        pages = tmp_path / key / "pages"
        pages.mkdir(parents=True, exist_ok=True)
        for name, text in (files or {}).items():
            (pages / name).write_text(text, encoding="utf-8")
        registry.register(LoadedModule(key=key, manifest={"key": key, "map_overlays": decl}, spec=ModuleSpec(key=key)))
    yield load
    registry.restore(snap)


def _keys():
    return [o["key"] for o in map_overlays.declared_overlays() if o["module"].startswith("zz")]


# ── ④ 腳本網址只由 L1 組出 ─────────────────────────────────────────────────────

def test_valid_declaration_is_listed_with_l1_built_same_origin_url(synth):
    synth("zz_mod", [{"key": "zz", "label": "合成", "script": "zz-overlay.js"}], {"zz-overlay.js": JS_OK})
    got = [o for o in map_overlays.declared_overlays() if o["module"] == "zz_mod"]
    assert got == [{"key": "zz", "label": "合成", "module": "zz_mod", "scriptUrl": "/map-overlays/zz_mod/zz-overlay.js"}]


@pytest.mark.parametrize("decl", [
    {"key": "zz", "label": "合成", "script": "https://evil.example/x.js"},
    {"key": "zz", "label": "合成", "script": "../x.js"},
    {"key": "zz", "label": "合成", "script": "sub/x.js"},
    {"key": "zz", "label": "合成", "script": "missing.js"},                 # 檔不存在
    {"key": "ZZ", "label": "合成", "script": "zz-overlay.js"},               # key 不合格式
    {"key": "zz", "label": "", "script": "zz-overlay.js"},
    {"key": "zz", "label": "合成", "script": "zz-overlay.js", "scriptUrl": "https://evil.example/x.js"},   # 提供者自帶網址 ⇒ 忽略
])
def test_invalid_declarations_are_not_listed(synth, decl, caplog):
    synth("zz_bad", [decl], {"zz-overlay.js": JS_OK})
    listed = [o for o in map_overlays.declared_overlays() if o["module"] == "zz_bad"]
    if "scriptUrl" in decl:                      # 其餘欄位合法 ⇒ 列，但網址是 L1 組的
        assert listed and listed[0]["scriptUrl"] == "/map-overlays/zz_bad/zz-overlay.js"
    else:
        assert listed == []


def test_duplicate_overlay_key_second_is_not_listed(synth):
    synth("zz_a", [{"key": "zz", "label": "甲", "script": "a.js"}], {"a.js": JS_OK})
    synth("zz_b", [{"key": "zz", "label": "乙", "script": "b.js"}], {"b.js": JS_OK})
    got = [o for o in map_overlays.declared_overlays() if o["key"] == "zz"]
    assert [o["module"] for o in got] == ["zz_a"]


def test_not_loaded_module_is_not_listed(synth):
    synth("zz_mod", [{"key": "zz", "label": "合成", "script": "zz-overlay.js"}], {"zz-overlay.js": JS_OK})
    registry._LOADED.pop("zz_mod")
    assert "zz" not in _keys()


# ── 腳本路由與清單端點 ──────────────────────────────────────────────────────────

def test_script_route_serves_only_declared_loaded_scripts(client, synth):
    synth("zz_mod", [{"key": "zz", "label": "合成", "script": "zz-overlay.js"}],
          {"zz-overlay.js": JS_OK, "other.js": "alert(1)"})
    r = client.get("/map-overlays/zz_mod/zz-overlay.js")          # 沒有 token 也可以（<script src> 帶不了 header）
    assert r.status_code == 200 and "javascript" in r.headers["content-type"] and "MotrixMapOverlay" in r.text
    assert client.get("/map-overlays/zz_mod/other.js").status_code == 404        # 在資料夾裡但沒宣告
    assert client.get("/map-overlays/zz_mod/..%2Fmodule.json").status_code == 404
    assert client.get("/map-overlays/zz_nope/zz-overlay.js").status_code == 404
    registry._LOADED.pop("zz_mod")
    assert client.get("/map-overlays/zz_mod/zz-overlay.js").status_code == 404   # 模組未載入


def test_overlay_list_endpoint(client, make_user, synth):
    synth("zz_mod", [{"key": "zz", "label": "合成", "script": "zz-overlay.js"}], {"zz-overlay.js": JS_OK})
    assert client.get("/api/map/overlays").status_code == 401
    u, p = make_user(username="ov_user", role="sales")
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    d = client.get("/api/map/overlays", headers={"Authorization": "Bearer " + tok}).json()
    assert {"key": "zz", "label": "合成", "scriptUrl": "/map-overlays/zz_mod/zz-overlay.js"} in d["overlays"]
    assert all(set(o) == {"key", "label", "scriptUrl"} for o in d["overlays"])


# ── ③ 覆蓋層腳本不碰地圖頁內部 ／ ⑧ 不寫 HTML ──────────────────────────────────

#: 覆蓋層腳本不可以出現的字（地圖頁內部欄位、Alpine、地圖函式庫物件）
FORBIDDEN = (r"\b_map\b", r"\b_layer\b", r"\b_cluster\b", r"\b_gm\w*", r"\bAlpine\b", r"\b__x\b",
             r"\bgoogle\.maps\b", r"\bL\.\w+", r"\bmarkerClusterer\b", r"MotrixMapOverlay\._\w+")


def declared_scripts():
    """獨立訊號（PLAYBOOK §G5 #15）：各模組 module.json 宣告的覆蓋層腳本 ⇒ 實體路徑（不管存不存在）。"""
    import json
    out = []
    for mj in sorted((REPO / "backend" / "modules").glob("*/module.json")):
        decl = json.loads(mj.read_text(encoding="utf-8")).get("map_overlays") or []
        out += [mj.parent / "pages" / d["script"] for d in decl if isinstance(d, dict) and isinstance(d.get("script"), str)]
    return out


def overlay_scripts():
    """掃描對象＝宣告的腳本 ∪ 命名像覆蓋層的腳本（modules/*/pages/*overlay*.js）——不點名任何模組。"""
    globbed = set((REPO / "backend" / "modules").glob("*/pages/*overlay*.js"))
    return sorted(globbed | set(declared_scripts()))


def test_every_declared_overlay_script_exists():
    missing = [str(p) for p in declared_scripts() if not p.is_file()]
    assert not missing, missing


def forbidden_hits(text):
    return [pat for pat in FORBIDDEN if re.search(pat, text)]


def test_overlay_scripts_use_only_the_contract():
    files = overlay_scripts()
    if not files and not declared_scripts():
        pytest.skip("沒有任何模組在 module.json 宣告 map_overlays，也沒有 *overlay*.js（獨立訊號：宣告）")
    bad = {f.name: forbidden_hits(f.read_text(encoding="utf-8")) for f in files}
    assert not {k: v for k, v in bad.items() if v}, bad


def test_overlay_scripts_have_no_html_sinks():
    """LG2-S3：覆蓋層畫面板清單只准 textContent／createElement；白名單 0。L1 的 map-overlay.js 同樣 0。"""
    targets = overlay_scripts() + [REPO / "frontend" / "static" / "map-overlay.js"]
    problems = {str(f.relative_to(REPO)): check(sink_sites(f.read_text(encoding="utf-8")), {}) for f in targets}
    assert not {k: v for k, v in problems.items() if v}, problems


def test_positive_controls_for_the_scans():
    assert forbidden_hits("var m = this._map") and forbidden_hits("Alpine.$data(x)") \
        and forbidden_hits("new google.maps.Marker()") and forbidden_hits("L.marker([1,2])") \
        and forbidden_hits("MotrixMapOverlay._mount('x')")
    assert not forbidden_hits("api.addMarkers(list, {icon: 'hotel'}); var mapLabel = 1; LL.x")
    assert check(sink_sites("function paint(el, s) {\n  el.innerHTML = s\n}\n"), {})
