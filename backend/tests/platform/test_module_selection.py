"""CORE-SPEC §9c ②授權 ③管理者啟停（2026-09-25 裁示：授權單位＝module.json 的 license_key；
啟停重啟後生效；頁面只提示不提供重啟）。

A 載入器：優先順序 未授權＞停用；兩者都不 import 模組；壞模組不拖垮其他；授權檢查未啟用要標出來（A-3）
B 授權判斷（純函式）：開關關閉＝不檢查；'*'；license_key；整體授權被擋；modules 只接受 list[str]（B-2）
C 啟動時讀停用清單：主庫不存在不可以被建出空檔；讀不到 ⇒ 視為沒有停用；切換是原子的（C-4）
D 這個行程的 API：切換只改「重啟後」，目前狀態與端點不變（重啟後生效）；權限；未授權不可切
E 子行程＝真的重啟：停用／未授權 ⇒ 端點 404、選單列為不可用、排程不跑、資料列數不變；兩者同時 ⇒ 未授權；
  開回來 ⇒ 200、排程跑、資料還在；modules 是空的（core-only）⇒ 管理 API 照常

🔴 C 組以後一律用合成模組，不綁任何真實的 L2 模組（MODULE-GUIDE §7；AUDIT-X-9c A-2：綁 tender_radar 時，
   拿掉它＝core-only 產品就有 7 題紅）。靜態反向控制見 test_no_real_l2_module_named_here。
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
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


def test_loader_reads_modules_dir_at_call_time(tmp_path, monkeypatch, isolated_registry):
    """A-2 的接縫：`load_all()` 不帶參數時讀**呼叫當下**的 MODULES_DIR／MODULES_PACKAGE
    （main.py 就是不帶參數呼叫）⇒ 子行程能在 import main 之前換成合成模組樹。"""
    pkg = _synthetic_pkg(tmp_path, ["zz_late"], pkg_name="zzsel_late")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(loader, "MODULES_DIR", str(pkg))
    monkeypatch.setattr(loader, "MODULES_PACKAGE", "zzsel_late")
    assert [m.key for m in loader.load_all()] == ["zz_late"]


# ── B 授權判斷 ────────────────────────────────────────────────────────────────
# （這一組只把 key 當字串比對，不 import、不打端點，不受「模組在不在」影響）

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
    # B-2：modules 只接受 list[str]——字串會變成子字串比對
    ({"key": "tender_radar"}, {**OK, "modules": "tender_radar_pro"}, True, False, "格式不正確"),
    ({"key": "tender_radar"}, {**OK, "modules": "xtender_radarx"}, True, False, "格式不正確"),
    ({"key": "tender_radar"}, {**OK, "modules": "*"}, True, False, "格式不正確"),
    ({"key": "tender_radar"}, {**OK, "modules": {"tender_radar": 1}}, True, False, "格式不正確"),
    ({"key": "tender_radar"}, {**OK, "modules": ["tender_radar", 3]}, True, False, "格式不正確"),
    ({"key": "tender_radar"}, {**OK, "modules": ["tender_radar_pro"]}, True, False, "未包含"),
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

def test_license_not_checked_is_visible_in_state(tmp_path, monkeypatch, isolated_registry):
    """A-3：開發模式（授權檢查未啟用）⇒ 狀態標「授權檢查未啟用」。寫在 note，不寫在 reason
    （reason 非空＝有問題）。反向：授權檢查有啟用且通過 ⇒ note 是空的。"""
    pkg = _synthetic_pkg(tmp_path, ["zz_n1", "zz_n2"], pkg_name="zzsel_note")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(lic, "LICENSE_GATE_ENABLED", False)
    loader.load_all(str(pkg), "zzsel_note", license_check=lic.module_license_check, disabled=frozenset({"zz_n2"}))
    st = {s["key"]: s for s in registry.module_states()}
    assert (st["zz_n1"]["state"], st["zz_n1"]["reason"], st["zz_n1"]["note"]) == \
        ("loaded", "", lic.MODULE_LICENSE_NOT_CHECKED)
    assert st["zz_n2"]["state"] == "disabled" and st["zz_n2"]["note"] == lic.MODULE_LICENSE_NOT_CHECKED

    registry._reset()
    monkeypatch.setattr(lic, "LICENSE_GATE_ENABLED", True)
    monkeypatch.setattr(lic, "verify_license", lambda blob=None: {**OK, "modules": ["*"]})
    loader.load_all(str(pkg), "zzsel_note", license_check=lic.module_license_check)
    assert [(s["state"], s["note"]) for s in registry.module_states()] == [("loaded", ""), ("loaded", "")]


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
    c.execute("INSERT INTO system_settings VALUES ('modules_disabled', '[\"zz_x\", \" \", 3]', '')")
    c.commit()
    assert ms.read_disabled_at_startup(str(p)) == frozenset({"zz_x"})
    c.execute("UPDATE system_settings SET value_json='{壞' WHERE key='modules_disabled'")
    c.commit()
    c.close()
    assert ms.read_disabled_at_startup(str(p)) == frozenset()


def test_concurrent_toggles_do_not_lose_updates(client, monkeypatch):
    """C-4：兩位 superadmin 同時停用兩個不同的模組 ⇒ 兩個都要在清單裡。
    讓兩條執行緒都停在「讀完、還沒寫」那一點（_normalize 裡等對方）：沒有鎖時兩者都讀到空清單，
    後寫的蓋掉先寫的；有鎖時第二條在 BEGIN IMMEDIATE 等，第一條等不到對方（逾時）就照寫。"""
    barrier = threading.Barrier(2, timeout=1.5)
    real = ms._normalize
    armed = [2]
    lock = threading.Lock()

    def slow_normalize(value):
        out = real(value)
        with lock:
            go = armed[0] > 0
            armed[0] -= 1
        if go:
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass
        return out

    monkeypatch.setattr(ms, "_normalize", slow_normalize)
    errs = []

    def run(k):
        try:
            ms.set_enabled(k, False)
        except Exception as e:                                          # noqa: BLE001
            errs.append(e)

    ts = [threading.Thread(target=run, args=(k,)) for k in ("zz_c4_a", "zz_c4_b")]
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    monkeypatch.setattr(ms, "_normalize", real)
    assert not errs, errs
    assert ms.configured_disabled() == ["zz_c4_a", "zz_c4_b"]


# ── D 這個行程的 API ──────────────────────────────────────────────────────────

@pytest.fixture
def synthetic_loaded(tmp_path, monkeypatch, client):
    """這個行程裡多一個「已載入」的合成模組 zz_toggle（有路由 GET /api/zz-toggle/ping），題後還原。
    路由插在最前面（StaticFiles 掛在 "/"，接在它後面的路由永遠輪不到），題後依物件身分移除。"""
    pkg = _synthetic_pkg(tmp_path, [], pkg_name="zzsel_toggle")
    d = pkg / "zz_toggle"
    d.mkdir()
    (d / "module.json").write_text(json.dumps({"key": "zz_toggle", "name": "合成切換", "version": "0.0.1",
                                               "core": ">=1.0,<2.0", "pages": [{"path": "zz-toggle.html"}]}),
                                   encoding="utf-8")
    (d / "__init__.py").write_text(
        "from fastapi import APIRouter\nfrom core.registry import ModuleSpec\nrouter = APIRouter()\n"
        "@router.get('/api/zz-toggle/ping')\ndef ping():\n    return {'ok': True}\n"
        "MODULE = ModuleSpec(key='zz_toggle', routers=[router])\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    snap = registry.snapshot()
    routes = client.app.router.routes
    added = []
    try:
        loader.load_all(str(pkg), "zzsel_toggle")                      # 疊加：不清掉這個行程原有的模組
        assert registry.is_loaded("zz_toggle"), registry.failed()
        for r in registry._LOADED["zz_toggle"].spec.routers[0].routes:
            routes.insert(0, r)
            added.append(r)
        yield "zz_toggle"
    finally:
        for r in added:
            routes.remove(r)
        registry.restore(snap)


def test_toggle_is_pending_until_restart(client, make_user, synthetic_loaded):
    key, ping = synthetic_loaded, "/api/zz-toggle/ping"
    h = _auth(client, make_user)
    rows = {m["key"]: m for m in client.get("/api/system/modules", headers=h).json()["modules"]}
    assert rows[key]["state"] == "loaded" and not rows[key]["pendingRestart"]
    assert client.get(ping, headers=h).status_code == 200

    r = client.put("/api/system/modules/" + key, headers=h, json={"enabled": False})
    assert r.status_code == 200 and r.json()["restartRequired"] is True, r.text
    row = r.json()["module"]
    assert (row["state"], row["afterRestart"], row["pendingRestart"]) == ("loaded", "disabled", True)
    assert client.get(ping, headers=h).status_code == 200                           # 重啟前照舊
    assert "zz-toggle.html" not in client.get("/api/system/modules/unavailable-pages",
                                              headers=h).json()["pages"]

    r = client.put("/api/system/modules/" + key, headers=h, json={"enabled": True})
    assert r.json()["restartRequired"] is False and not r.json()["module"]["pendingRestart"]
    assert ms.configured_disabled() == []


def test_toggle_permissions_and_unknown(client, make_user, synthetic_loaded):
    h = _auth(client, make_user)
    assert client.put("/api/system/modules/no_such_module", headers=h, json={"enabled": False}).status_code == 404
    hv = _auth(client, make_user, name="ms_admin", role="admin")
    assert client.get("/api/system/modules", headers=hv).status_code == 403
    assert client.put("/api/system/modules/" + synthetic_loaded, headers=hv,
                      json={"enabled": False}).status_code == 403
    assert client.get("/api/system/modules/unavailable-pages", headers=hv).status_code == 200   # 選單用：登入即可


def test_unlicensed_cannot_be_toggled(client, make_user, synthetic_loaded):
    key = synthetic_loaded
    h = _auth(client, make_user)
    st = dict(registry._STATES[key])
    registry._STATES[key] = {**st, "state": "unlicensed", "reason": "未授權：測試"}  # fixture 的 restore 還原
    r = client.put("/api/system/modules/" + key, headers=h, json={"enabled": True})
    assert r.status_code == 400 and "未授權" in r.text


def test_admin_api_shows_the_license_note(client, make_user, synthetic_loaded):
    """A-3：管理頁看得到「授權檢查未啟用」——note 走 /api/system/modules 的每一列，reason 仍是空的
    （不可以被當成錯誤）；頁面顯示在狀態格，並在頂端提示一次。"""
    key = synthetic_loaded
    registry._STATES[key] = {**registry._STATES[key], "note": lic.MODULE_LICENSE_NOT_CHECKED}
    h = _auth(client, make_user)
    row = {m["key"]: m for m in client.get("/api/system/modules", headers=h).json()["modules"]}[key]
    assert (row["state"], row["reason"], row["note"], row["canToggle"]) == \
        ("loaded", "", lic.MODULE_LICENSE_NOT_CHECKED, True)
    page = (BACKEND.parent / "frontend" / "pages" / "module-settings.html").read_text(encoding="utf-8")
    assert "x-text=\"m.note\"" in page and "data-testid=\"ms-license-note\"" in page


def test_page_and_sidebar_wiring():
    fe = BACKEND.parent / "frontend"
    page = (fe / "pages" / "module-settings.html").read_text(encoding="utf-8")
    assert "/api/system/modules" in page and "重新啟動服務後才生效" in page
    assert not re.search(r"fetch\([^)]*restart", page, re.I)                        # 不打任何重啟端點
    assert not re.search(r"<button[^>]*>[^<]*重(新)?啟", page)                        # 沒有重啟按鈕
    sb = (fe / "static" / "sidebar.js").read_text(encoding="utf-8")
    assert "/api/system/modules/unavailable-pages" in sb and "module-settings.html" in sb
    assert sb.count("_applyUnavailablePages()") >= 2                                  # 選單重建後再套用


# ── E 子行程＝真的重啟 ────────────────────────────────────────────────────────

_GATE_MODULE = """import os
from fastapi import APIRouter
from core.registry import ModuleSpec

router = APIRouter()


@router.get('/api/zz-gate/ping')
def ping():
    import db
    conn = db.get_db()
    try:
        return {'rows': conn.execute('SELECT COUNT(*) FROM zz_gate_rows').fetchone()[0]}
    finally:
        conn.close()


def _sched():
    k = 'MOTRIX_TEST_CHILD_SCHED_CALLS'
    os.environ[k] = str(int(os.environ.get(k, '0')) + 1)


MODULE = ModuleSpec(key='zz_gate', routers=[router], schedulers=[_sched])
"""


def _gate_tree(tmp_path, gate):
    """子行程用的合成模組樹。coreonly ⇒ 空的（只有套件本身）。"""
    name = "zzgate_" + gate
    pkg = tmp_path / "mods" / name
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    if gate != "coreonly":
        d = pkg / "zz_gate"
        d.mkdir()
        (d / "module.json").write_text(json.dumps({"key": "zz_gate", "name": "合成守門", "version": "0.0.1",
                                                   "core": ">=1.0,<2.0", "pages": [{"path": "zz-gate.html"}]}),
                                       encoding="utf-8")
        (d / "__init__.py").write_text(_GATE_MODULE, encoding="utf-8")
    return pkg, name


def _reenabled_settings(tmp_path, monkeypatch):
    """真的 set_enabled：先停用（確認讀得到停用）、再啟用。回庫的路徑給子行程讀。"""
    import db
    p = tmp_path / "settings.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE system_settings (key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT)")
    c.commit()
    c.close()
    monkeypatch.setattr(db, "DB_PATH", str(p))
    ms.set_enabled("zz_gate", False)
    assert ms.read_disabled_at_startup(str(p)) == frozenset({"zz_gate"}), "前提：停用有寫進去"
    ms.set_enabled("zz_gate", True)
    return p


@pytest.mark.parametrize("gate", ["disabled", "unlicensed", "both", "reenabled", "coreonly"])
def test_after_restart_the_module_is_gone_and_data_stays(gate, tmp_path, monkeypatch):
    from tests._subproc import utf8_env
    pkg, name = _gate_tree(tmp_path, gate)
    extra = {"MOTRIX_TEST_CHILD_GATE": gate, "MOTRIX_TEST_CHILD_MODULES": str(pkg),
             "MOTRIX_TEST_CHILD_PACKAGE": name, "MOTRIX_TEST_CHILD_SCHED_CALLS": None}
    if gate == "reenabled":
        extra["MOTRIX_TEST_CHILD_SETTINGS"] = str(_reenabled_settings(tmp_path, monkeypatch))
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider", "-p", "no:xdist",
                        f"--basetemp={tmp_path / 'child'}", "tests/platform/child_module_gate.py"],
                       cwd=str(BACKEND), env=utf8_env(**extra), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "1 passed" in out, out[-3000:]
    assert "CHILD_GATE_OK %s" % gate in out, out[-2000:]


def _real_modules():
    return {d.name for d in (BACKEND / "modules").iterdir() if (d / "module.json").is_file()}


def _mentions(src, keys):
    out = []
    for key in keys:
        pat = r"%s|%s|/api/%s/" % (re.escape(key), re.escape(key.replace("_", "-") + ".html"),
                                   re.escape(key.replace("_", "-")))
        out += [ln.strip() for ln in src.splitlines() if re.search(pat, ln)]
    return out


def test_no_real_l2_module_named_here():
    """A-2 反向控制（靜態）：§9c 守門的 C 組以後、子行程與 e2e，不可以點名任何真實的 L2 模組——
    點名了，拿掉那個模組（core-only 產品）守門就會紅或失效。B 組的授權純函式只把 key 當字串比對，不算。
    正對照：偵測器對原本的寫法（`/api/tender-radar/status`、`ms-state-tender_radar`）會亮。"""
    real = _real_modules()
    if not real:
        pytest.skip("這個安裝包沒有任何 L2 模組（core-only）：沒有可以被點名的模組")
    k = sorted(real)[0]
    assert _mentions("x = client.get('/api/%s/status')" % k.replace("_", "-"), real), "正對照：偵測器要認得端點"
    assert _mentions("sel = \"[data-testid='ms-state-%s']\"" % k, real), "正對照：偵測器要認得 key"
    me = Path(__file__).read_text(encoding="utf-8")
    me = me[me.index("# ── C 啟動時讀停用清單"):]
    me = me[:me.index("def _real_modules():")]
    srcs = {"test_module_selection.py（C 組以後）": me,
            "child_module_gate.py": Path(__file__).with_name("child_module_gate.py").read_text(encoding="utf-8"),
            "test_e2e_module_settings": (BACKEND / "tests" / "test_e2e_module_settings_2026_09_25.py"
                                         ).read_text(encoding="utf-8")}
    bad = ["%s: %s" % (n, ln) for n, src in srcs.items() for ln in _mentions(src, real)]
    assert not bad, "§9c 守門點名了真實的 L2 模組（MODULE-GUIDE §7）：\n" + "\n".join(bad)


def test_conftest_names_no_l2_module():
    """A-2：L1 的測試設定（backend/conftest.py）不可以 import L2 模組——它每一題都跑，
    真的模組就永遠在 sys.modules 裡，「停用後不 import」只剩合成模組驗得到。
    模組自己的夾具放 modules/<key>/tests/conftest.py。"""
    src = (BACKEND / "conftest.py").read_text(encoding="utf-8")
    hits = re.findall(r"^\s*(?:from|import)\s+modules\.\w+", src, re.M)
    hits += re.findall(r"^\s*from\s+modules\s+import\s+\w+", src, re.M)
    assert not hits, hits


# ── registry 夾具 ────────────────────────────────────────────────────────────

def _registry_tables():
    """registry 模組層級的 `_` 開頭 dict（登錄表）。_LEGACY_PROVIDERS 刻意不在 snapshot 裡（見 snapshot 的說明）。"""
    return {n: v for n, v in vars(registry).items()
            if n.startswith("_") and not n.startswith("__") and isinstance(v, dict) and n != "_LEGACY_PROVIDERS"}


def test_registry_snapshot_restores_every_table():
    """B-1：restore(snapshot()) 必須把**每一張**表還原。表的清單從 `vars(registry)` 列，不從 snapshot 自己列
    ——兩邊用同一份列舉互相比對時，snapshot 漏掉的表兩邊一起漏（X 的突變：`dict(_FAILED)`→`{}` 照綠）。
    每張表放一筆探針；不依賴「這個 worker 有沒有先 import 過 main」。"""
    tables = _registry_tables()
    assert {"_LOADED", "_FAILED", "_STATES"} <= set(tables), "正對照：至少認得已知的三張表"
    outer = registry.snapshot()
    try:
        assert len(outer) == len(tables), "snapshot 的份數 ≠ registry 的表數：%s" % sorted(tables)
        for n, t in tables.items():
            t["zz_snapshot_probe"] = {"probe": n}
        before = registry.snapshot()
        registry._reset()
        assert all(not t for t in tables.values()), "_reset 要清空每一張表"
        registry.restore(before)
        missing = [n for n, t in _registry_tables().items() if t.get("zz_snapshot_probe") != {"probe": n}]
        assert not missing, "restore 之後這幾張表的探針不見了：%s" % missing
    finally:
        registry.restore(outer)
    assert all("zz_snapshot_probe" not in t for t in _registry_tables().values())
