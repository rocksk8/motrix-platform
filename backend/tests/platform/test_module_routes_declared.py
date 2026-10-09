# -*- coding: utf-8 -*-
"""每條路由都要歸在自己模組的宣告底下（第 49 班 W1c-P4）。

`provides.api_prefixes`（前綴）＋ `provides.routes`（明列的個別路由，可含 `{參數}`、結尾 `/*`）要涵蓋該模組檔案定義的**每一條**執行期路由——
demo 庫該模組升級未完成時，中介層靠這份宣告回清楚的 404；沒宣告的路由會直接撞到缺表的 500。
路由表取自執行中的 app（`effective_route_contexts`），端點函式經 `inspect.unwrap` 找回真正的檔案（匯出包裝器會把它歸到 helpers/xlsx_out）。
"""
import inspect
import json
import os

from fastapi.routing import APIRoute

from helpers.module_startup import _pattern_hit

BE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _runtime_routes(app):
    for r in app.routes:
        if isinstance(r, APIRoute):
            yield r.path, r.endpoint
        elif hasattr(r, "effective_route_contexts"):
            for c in r.effective_route_contexts():
                if getattr(c.original_route, "methods", None) and c.endpoint is not None:
                    yield c.path, c.endpoint


def _owner(endpoint):
    try:
        f = os.path.relpath(inspect.getsourcefile(inspect.unwrap(endpoint)), BE).replace("\\", "/")
    except Exception:
        return None
    parts = f.split("/")
    return parts[1] if parts[0] == "modules" and len(parts) > 2 else None


def covers(prov: dict, path: str) -> bool:
    for p in prov.get("api_prefixes") or []:
        if path == p or path.startswith(p.rstrip("/") + "/"):
            return True
    return any(_pattern_hit(r, path) for r in prov.get("routes") or [])


def test_every_module_route_is_covered_by_its_own_prefixes_or_routes(client):
    manifests = {}
    for k in os.listdir(os.path.join(BE, "modules")):
        mj = os.path.join(BE, "modules", k, "module.json")
        if os.path.isfile(mj):
            manifests[k] = (json.load(open(mj, encoding="utf-8")).get("provides") or {})
    gaps, seen = [], 0
    for path, ep in _runtime_routes(client.app):
        k = _owner(ep)
        if k is None or k not in manifests:
            continue
        seen += 1
        if not covers(manifests[k], path):
            gaps.append("%s  ← modules/%s（%s）" % (path, k, ep.__name__))
    assert seen > 300, "路由表讀不到（掃描器壞了）：%d" % seen
    assert not gaps, "這些路由不在自己模組的 api_prefixes／routes 底下（demo 缺席訊息會漏接）：\n  " + "\n  ".join(sorted(set(gaps)))


def test_scanner_positive_control():
    prov = {"api_prefixes": ["/api/a"], "routes": ["/api/q/{no}/x", "/api/z/*"]}
    assert covers(prov, "/api/a") and covers(prov, "/api/a/b") and covers(prov, "/api/q/Q1/x") and covers(prov, "/api/z") and covers(prov, "/api/z/1/2")
    assert not covers(prov, "/api/ab") and not covers(prov, "/api/q/Q1/y") and not covers(prov, "/api/q/Q1/x/more") and not covers(prov, "/api/zz")


def test_demo_absent_reason_prefers_the_most_specific_declaration(monkeypatch):
    from core import registry
    from helpers import module_startup as ms
    case = registry.LoadedModule(key="zzcase", manifest={"provides": {"api_prefixes": ["/api/quotations"]}}, spec=registry.ModuleSpec(key="zzcase"))
    net = registry.LoadedModule(key="zznet", manifest={"provides": {"api_prefixes": ["/api/network-plans"], "routes": ["/api/quotations/{quote_no}/network-plan"]}},
                                spec=registry.ModuleSpec(key="zznet"))
    real = registry.loaded
    monkeypatch.setattr(registry, "loaded", lambda: real() + [case, net])
    monkeypatch.setattr(ms, "_DEMO_ABSENT", {"zzcase": "案件缺席", "zznet": "規劃書缺席"})
    assert ms.demo_absent_reason("/api/quotations/Q1/network-plan") == "規劃書缺席"
    assert ms.demo_absent_reason("/api/quotations/Q1") == "案件缺席"
    assert ms.demo_absent_reason("/api/network-plans/3") == "規劃書缺席"
    assert ms.demo_absent_reason("/api/other") is None
    monkeypatch.setattr(ms, "_DEMO_ABSENT", {"zzcase": "案件缺席"})          # netplan 沒缺席 ⇒ 該路徑算 case 的前綴（舊行為）
    assert ms.demo_absent_reason("/api/quotations/Q1/network-plan") == "案件缺席"
