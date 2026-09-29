"""W3：部署儀表板「模組版本對照」與正式機系統版本（唯讀、零監聽）。"""
import importlib.util
from pathlib import Path

from starlette.testclient import TestClient

DASHBOARD = Path(__file__).resolve().parents[1] / "tools" / "deploy_dashboard.py"
LOCAL = ("127.0.0.1", 44321)


def _load(monkeypatch):
    monkeypatch.syspath_prepend(str(DASHBOARD.parent))
    spec = importlib.util.spec_from_file_location("motrix_dash_modver_under_test", DASHBOARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_module_versions_lists_dev_modules(monkeypatch):
    mod = _load(monkeypatch)
    monkeypatch.setattr(mod, "_delivered_status", lambda: {"configured": False, "available": False})
    with TestClient(mod.app, client=LOCAL) as c:
        r = c.get("/api/module-versions")
    assert r.status_code == 200
    rows = {x["key"]: x for x in r.json()["rows"]}
    assert "accounting" in rows and rows["accounting"]["dev"]      # 取自 module.json，不是猜的


def test_prod_status_reads_system_version(monkeypatch):
    mod = _load(monkeypatch)
    monkeypatch.setattr(mod, "_delivered_status", lambda: {"configured": False, "available": False})

    class R:
        ok = True
        def __init__(self, j): self._j = j
        def json(self): return self._j

    def fake_get(url, **kw):
        return R({"version": "V9-x"} if url.endswith("/api/system/version") else {"commit": "abc"})
    monkeypatch.setattr(mod.requests, "get", fake_get)
    out = mod._check_prod_status()
    assert out["systemVersion"] == {"version": "V9-x"} and out["deployed"] == {"commit": "abc"}
