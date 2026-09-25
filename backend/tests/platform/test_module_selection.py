"""CORE-SPEC §9c ②授權 ③管理者啟停（2026-09-25 裁示：授權單位＝module.json 的 license_key；
啟停重啟後生效；頁面只提示不提供重啟）。

A 載入器：優先順序 未授權＞停用；兩者都不 import 模組；壞模組不拖垮其他
B 授權判斷（純函式）：開關關閉＝不檢查；'*'；license_key；整體授權被擋
C 啟動時讀停用清單：主庫不存在不可以被建出空檔；讀不到 ⇒ 視為沒有停用
D 這個行程的 API：切換只改「重啟後」，目前狀態與端點不變（重啟後生效）；權限；未授權不可切
E 子行程＝真的重啟：停用／未授權 ⇒ 端點 404、選單列為不可用、資料列數不變；兩者同時 ⇒ 未授權
"""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from core import loader, registry
from helpers import licensing as lic
from helpers import module_switches as ms

BACKEND = Path(__file__).resolve().parents[2]


def _auth(client, make_user, name="ms_sa", role="superadmin"):
    u, p = make_user(username=name, role=role, modules=[])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    return {"Authorization": "Bearer " + r.json()["token"]}


# ── A 載入器 ─────────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_registry():
    snap = registry.snapshot()
    registry._reset()
    yield
    registry.restore(snap)


def _synthetic_pkg(tmp_path, names, license_keys=None, pkg_name="zzsel"):
    """每題用不同的套件名：同名套件已在 sys.modules 裡，會讀到上一題的舊檔。"""
    pkg = tmp_path / pkg_name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    for n in names:
        d = pkg / n
        d.mkdir()
        man = {"key": n, "name": n, "version": "0.0.1", "core": ">=1.0,<2.0", "pages": [{"path": n + ".html"}]}
        if license_keys and n in license_keys:
            man["license_key"] = license_keys[n]
        (d / "module.json").write_text(json.dumps(man), encoding="utf-8")
        body = ("raise RuntimeError('壞掉的模組')\n" if n.endswith("broken") else
                "from core.registry import ModuleSpec\nMODULE = ModuleSpec(key=%r)\n" % n)
        (d / "__init__.py").write_text(body, encoding="utf-8")
    return pkg


def test_loader_priority_and_no_import(tmp_path, monkeypatch, isolated_registry):
    names = ["zz_ok", "zz_nolic", "zz_off", "zz_both", "zz_broken", "zz_custom"]
    pkg = _synthetic_pkg(tmp_path, names, license_keys={"zz_custom": "custom-sku"})
    monkeypatch.syspath_prepend(str(tmp_path))
    seen = []

    def check(manifest):
        seen.append(manifest.get("license_key") or manifest["key"])
        ok = manifest["key"] not in ("zz_nolic", "zz_both")
        return ok, "" if ok else "未授權：測試"

    loader.load_all(str(pkg), "zzsel", license_check=check, disabled=frozenset({"zz_off", "zz_both"}))
    st = {s["key"]: s["state"] for s in registry.module_states()}
    assert st == {"zz_ok": "loaded", "zz_nolic": "unlicensed", "zz_off": "disabled", "zz_both": "unlicensed",
                  "zz_broken": "failed", "zz_custom": "loaded"}
    assert "zz_nolic" in registry.failed() and "zz_both" in registry.failed()       # 未授權記進 failed()＋原因
    assert "zz_off" not in registry.failed()                                           # 停用不是失敗
    for n in ("zz_nolic", "zz_off", "zz_both"):
        assert "zzsel.%s" % n not in sys.modules, n                                    # 沒有 import
    assert "custom-sku" in seen                                                        # license_key 傳進檢查
    assert {s["key"]: s["pages"] for s in registry.module_states()}["zz_off"] == ["zz_off.html"]


def test_loader_without_gates_loads_everything(tmp_path, monkeypatch, isolated_registry):
    pkg = _synthetic_pkg(tmp_path, ["zz_a", "zz_b"], pkg_name="zzsel_nogate")
    monkeypatch.syspath_prepend(str(tmp_path))
    loader.load_all(str(pkg), "zzsel_nogate")
    assert [s["state"] for s in registry.module_states()] == ["loaded", "loaded"]


# ── B 授權判斷 ────────────────────────────────────────────────────────────────

OK = {"reason": "ok", "modules": ["tender_radar"], "kind": "subscription"}


@pytest.mark.parametrize("manifest,status,gate,expect_ok,reason_has", [
    ({"key": "tender_radar"}, {}, False, True, "授權檢查未啟用"),                        # 開發模式：不檢查
    ({"key": "tender_radar"}, OK, True, True, ""),
    ({"key": "case"}, OK, True, False, "case"),
    ({"key": "case"}, {**OK, "modules": ["*"]}, True, True, ""),
    ({"key": "folder", "license_key": "tender_radar"}, OK, True, True, ""),           # license_key 優先
    ({"key": "tender_radar", "license_key": "sku"}, OK, True, False, "sku"),
    ({"key": "tender_radar"}, {"reason": "missing", "modules": None}, True, False, "未授權"),   # 整體被擋
    ({"key": "tender_radar"}, {**OK, "reason": "expired", "kind": "perpetual"}, True, True, ""),  # 永久過期不擋
])
def test_module_licensed(manifest, status, gate, expect_ok, reason_has):
    ok, reason = lic.module_licensed(manifest, status, gate)
    assert ok is expect_ok and reason_has in reason


def test_gate_off_never_reads_the_key(monkeypatch):
    """開發模式照既有規則：開關關閉時連 verify_license 都不呼叫。"""
    monkeypatch.setattr(lic, "LICENSE_GATE_ENABLED", False)
    monkeypatch.setattr(lic, "verify_license", lambda blob=None: pytest.fail("不該讀金鑰"))
    assert lic.module_license_check({"key": "x"}) == (True, lic.MODULE_LICENSE_NOT_CHECKED)


# ── C 啟動時讀停用清單 ────────────────────────────────────────────────────────

def test_read_disabled_never_creates_the_db(tmp_path):
    missing = tmp_path / "nope.db"
    assert ms.read_disabled_at_startup(str(missing)) == frozenset()
    assert not missing.exists(), "讀不存在的主庫時不可以建出空檔（會讓 require_db 守門失效）"


def test_read_disabled_values(tmp_path):
    p = tmp_path / "m.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE other (x)")
    c.commit()
    assert ms.read_disabled_at_startup(str(p)) == frozenset()                          # 表還沒建
    c.execute("CREATE TABLE system_settings (key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT)")
    c.execute("INSERT INTO system_settings VALUES ('modules_disabled', '[\"tender_radar\", \" \", 3]', '')")
    c.commit()
    assert ms.read_disabled_at_startup(str(p)) == frozenset({"tender_radar"})
    c.execute("UPDATE system_settings SET value_json='{壞' WHERE key='modules_disabled'")
    c.commit()
    c.close()
    assert ms.read_disabled_at_startup(str(p)) == frozenset()


# ── D 這個行程的 API ──────────────────────────────────────────────────────────

def test_toggle_is_pending_until_restart(client, make_user):
    h = _auth(client, make_user)
    rows = {m["key"]: m for m in client.get("/api/system/modules", headers=h).json()["modules"]}
    assert rows["tender_radar"]["state"] == "loaded" and not rows["tender_radar"]["pendingRestart"]
    assert client.get("/api/tender-radar/status", headers=h).status_code == 200

    r = client.put("/api/system/modules/tender_radar", headers=h, json={"enabled": False})
    assert r.status_code == 200 and r.json()["restartRequired"] is True, r.text
    row = r.json()["module"]
    assert (row["state"], row["afterRestart"], row["pendingRestart"]) == ("loaded", "disabled", True)
    assert client.get("/api/tender-radar/status", headers=h).status_code == 200      # 重啟前照舊
    assert "tender-radar.html" not in client.get("/api/system/modules/unavailable-pages",
                                                 headers=h).json()["pages"]

    r = client.put("/api/system/modules/tender_radar", headers=h, json={"enabled": True})
    assert r.json()["restartRequired"] is False and not r.json()["module"]["pendingRestart"]
    assert ms.configured_disabled() == []


def test_toggle_permissions_and_unknown(client, make_user):
    h = _auth(client, make_user)
    assert client.put("/api/system/modules/no_such_module", headers=h, json={"enabled": False}).status_code == 404
    hv = _auth(client, make_user, name="ms_admin", role="admin")
    assert client.get("/api/system/modules", headers=hv).status_code == 403
    assert client.put("/api/system/modules/tender_radar", headers=hv, json={"enabled": False}).status_code == 403
    assert client.get("/api/system/modules/unavailable-pages", headers=hv).status_code == 200   # 選單用：登入即可


def test_unlicensed_cannot_be_toggled(client, make_user, monkeypatch):
    h = _auth(client, make_user)
    st = dict(registry._STATES["tender_radar"])
    monkeypatch.setitem(registry._STATES, "tender_radar", {**st, "state": "unlicensed", "reason": "未授權：測試"})
    r = client.put("/api/system/modules/tender_radar", headers=h, json={"enabled": True})
    assert r.status_code == 400 and "未授權" in r.text


def test_page_and_sidebar_wiring():
    fe = BACKEND.parent / "frontend"
    page = (fe / "pages" / "module-settings.html").read_text(encoding="utf-8")
    assert "/api/system/modules" in page and "重新啟動服務後才生效" in page
    import re
    assert not re.search(r"fetch\([^)]*restart", page, re.I)                        # 不打任何重啟端點
    assert not re.search(r"<button[^>]*>[^<]*重(新)?啟", page)                        # 沒有重啟按鈕
    sb = (fe / "static" / "sidebar.js").read_text(encoding="utf-8")
    assert "/api/system/modules/unavailable-pages" in sb and "module-settings.html" in sb
    assert sb.count("_applyUnavailablePages()") >= 2                                  # 選單重建後再套用


# ── E 子行程＝真的重啟 ────────────────────────────────────────────────────────

@pytest.mark.parametrize("gate", ["disabled", "unlicensed", "both"])
def test_after_restart_the_module_is_gone_and_data_stays(gate, tmp_path):
    env = {**os.environ, "MOTRIX_TEST_CHILD_GATE": gate, "PYTHONIOENCODING": "utf-8"}
    env.pop("PYTEST_XDIST_WORKER", None)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider", "-p", "no:xdist",
                        f"--basetemp={tmp_path / 'child'}", "tests/platform/child_module_gate.py"],
                       cwd=str(BACKEND), env=env, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300)
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "1 passed" in out, out[-3000:]
    assert "CHILD_GATE_OK %s" % gate in out, out[-2000:]


def test_registry_snapshot_restores_every_table():
    """反向控制：清空後 restore 必須把每一張表都還原（含 _STATES）。
    自己放一筆合成狀態——不依賴「這個 worker 有沒有先 import 過 main」（依賴順序的題本身就是這次的病因）。"""
    outer = registry.snapshot()
    try:
        registry.set_state("zz_snapshot_probe", registry.STATE_DISABLED, "探針")
        before = registry.snapshot()
        assert "zz_snapshot_probe" in before[2]
        registry._reset()
        assert registry.module_states() == []
        registry.restore(before)
        assert registry.snapshot() == before
    finally:
        registry.restore(outer)
    assert "zz_snapshot_probe" not in registry._STATES
