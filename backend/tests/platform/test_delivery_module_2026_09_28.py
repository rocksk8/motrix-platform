# -*- coding: utf-8 -*-
"""B55 S4：單模組包走同一套簽章交付（delivery.py kind＝module；設計 docs/platform/MODULE-UPDATE-DELIVERY.md §1.1～§1.4）。

全部在 tmp 模擬交付資料夾與安裝目錄——不碰真的雲端資料夾、不碰正式機。
正對照：好的模組包發布、驗證都過；反向控制：沒基準／沒跑題／題不綠／正式機工具太舊或沒有／基準不符／preflight 不過／
改 kind ⇒ 簽章不符／不認得的 kind——各自不通過。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend" / "tools"))
import delivery as D  # noqa: E402
from tests.platform.test_delivery_2026_09_28 import JUDGE, _keys  # noqa: E402

PAGES_DIR = "frontend/" + "pages"      # 合成包的頁面目錄（資料，不是讀 repo 的頁面）
BASE = "a" * 40
BUILT = "b" * 40
TOOL_VER = "2026-09-28a"


def _mod_pkg(tmp, tests=None, base=BASE, tier="module", key="zz"):
    """module_update.ship 的產物形狀（lock 欄位）：模組資料夾＋宣告頁面＋module-update.lock.json。"""
    p = tmp / ("modpkg_" + key)
    (p / "backend" / "modules" / key).mkdir(parents=True)
    (p / "backend" / "modules" / key / "api.py").write_text("X = 1\n", encoding="utf-8")
    (p / PAGES_DIR).mkdir(parents=True)
    (p / PAGES_DIR / "zz.html").write_text("<p>zz</p>\n", encoding="utf-8")
    lock = {"lock_version": 1, "kind": "module_update", "built_from": BUILT, "prod_base_commit": base, "tier": tier,
            "modules": {key: {"version": "1.1.0", "core": ">=1.0,<2.0", "sha256": "0" * 64}},
            "tests": tests if tests is not None else {"passed": 12, "failed": 0, "errors": 0, "seconds": 3.0, "line": "12 passed"}}
    (p / D.MODULE_LOCK).write_text(json.dumps(lock), encoding="utf-8")
    return p


def _tools(tmp, version=TOOL_VER):
    d = tmp / "devtools"
    d.mkdir(parents=True, exist_ok=True)
    if version:
        (d / "apply_module_update.version.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    return d


def _install(tmp, commit=BASE, tool_version=TOOL_VER, with_tool=True):
    root = tmp / "install"
    (root / "backend" / "tools").mkdir(parents=True)
    (root / "backend" / ".deployed_commit.json").write_text("﻿" + json.dumps({"commit": commit}), encoding="utf-8")
    if tool_version:
        (root / "backend" / "tools" / "apply_module_update.version.json").write_text(
            json.dumps({"version": tool_version}), encoding="utf-8")
    if with_tool:
        (root / "tools" / "platform").mkdir(parents=True)
        (root / "tools" / "platform" / "module_update.py").write_text("# installed\n", encoding="utf-8")
    return root


@pytest.fixture()
def env(tmp_path, monkeypatch):
    root = tmp_path / "交付"
    root.mkdir()
    priv, pub = _keys()
    monkeypatch.setattr(D, "DELIVERY_PUBKEY_PEM", pub)
    return {"tmp": tmp_path, "root": root, "priv": priv, "pub": pub, "staging": tmp_path / "staging",
            "tools": _tools(tmp_path)}


def _ok_runner(calls=None):
    def run(cmd):
        if calls is not None:
            calls.append(cmd)
        return 0, 'MODULE_UPDATE_RESULT {"ok": true, "key": "zz", "from_version": "1.0.0", "to_version": "1.1.0", "has_migrations": true}\n'
    return run


def _publish_stage(env, **kw):
    name = D.publish(str(_mod_pkg(env["tmp"], **kw)), str(env["root"]), env["priv"], tools_dir=str(env["tools"]))
    env["staging"].mkdir(exist_ok=True)
    return name, D.stage(str(env["root"]), name, str(env["staging"]))


# ── 發布 ─────────────────────────────────────────────────────────────────

def test_publish_module_package_is_signed_and_typed(env):
    name, staged = _publish_stage(env)
    assert name.endswith("_" + BUILT[:8] + "_mod-zz") and D.NAME_RE.match(name)
    meta = json.loads(Path(staged, D.META_JSON).read_text(encoding="utf-8"))
    assert meta["kind"] == "module" and meta["module"]["key"] == "zz" and meta["module"]["prod_base_commit"] == BASE
    assert meta["min_apply_module_script"] == TOOL_VER
    assert not Path(staged, D.PAYLOAD, "backend", "tools").exists(), "單模組包不帶工具"
    row = D.scan(str(env["root"]))[0]
    assert row["kind"] == "module" and row["module"]["key"] == "zz"


@pytest.mark.parametrize("kw, match", [
    ({"base": ""}, "正式機基準"),
    ({"tier": "full"}, "第②級"),
    ({"tests": {"skipped": "run_tests=False"}}, "第②級測試全綠"),
    ({"tests": {"passed": 3, "failed": 1}}, "第②級測試全綠"),
    ({"tests": {"passed": 0}}, "第②級測試全綠"),
])
def test_publish_refuses_packages_not_shipped_properly(env, kw, match):
    with pytest.raises(D.DeliveryError, match=match):
        D.publish(str(_mod_pkg(env["tmp"], **kw)), str(env["root"]), env["priv"], tools_dir=str(env["tools"]))
    assert not os.listdir(env["root"]) or not os.listdir(os.path.join(env["root"], "packages"))


def test_publish_refuses_without_dev_tool_version(env):
    with pytest.raises(D.DeliveryError, match="套用工具版本"):
        D.publish(str(_mod_pkg(env["tmp"])), str(env["root"]), env["priv"], tools_dir=str(_tools(env["tmp"] / "x", None)))


def test_full_packages_now_carry_kind_full(env):
    from tests.platform.test_delivery_2026_09_28 import _pkg
    name = D.publish(str(_pkg(env["tmp"])), str(env["root"]), env["priv"])
    meta = json.loads(Path(env["root"], "packages", name, D.META_JSON).read_text(encoding="utf-8"))
    assert meta["kind"] == "full"


# ── 驗證（正式機）────────────────────────────────────────────────────────────

def test_verify_module_ok_uses_installed_module_update(env):
    _name, staged = _publish_stage(env)
    install = _install(env["tmp"])
    calls = []
    r = D.verify_staged(staged, str(install), module_runner=_ok_runner(calls))
    assert r["ok"] and r["kind"] == "module", r["problems"]
    assert calls and calls[0][1] == os.path.join(str(install), "tools", "platform", "module_update.py"), "要跑**已安裝**的那一份"
    assert "--require-base" in calls[0]
    assert any("1.0.0 → 1.1.0" in n and "migration" in n for n in r["notes"])


@pytest.mark.parametrize("install_kw, match", [
    ({"tool_version": None}, "沒有單模組套用工具"),
    ({"tool_version": "2026-09-27z"}, "比這個包需要的"),
    ({"with_tool": False}, "tools/platform/module_update.py"),
    ({"commit": "c" * 40}, "是對正式機"),
])
def test_verify_module_refusals(env, install_kw, match):
    _name, staged = _publish_stage(env)
    install = _install(env["tmp"], **install_kw)
    calls = []
    r = D.verify_staged(staged, str(install), module_runner=_ok_runner(calls))
    assert not r["ok"] and any(match in p for p in r["problems"]), r["problems"]
    assert not calls, "前面的檢查不過就不跑 preflight"


def test_verify_module_preflight_failure_is_a_problem(env):
    _name, staged = _publish_stage(env)
    install = _install(env["tmp"])
    r = D.verify_staged(staged, str(install), module_runner=lambda cmd: (
        2, 'MODULE_UPDATE_RESULT {"ok": false, "error": "not licensed"}\n'))
    assert not r["ok"] and any("not licensed" in p for p in r["problems"])
    r = D.verify_staged(staged, str(install), module_runner=lambda cmd: (0, "no result line\n"))
    assert not r["ok"] and any("沒有結果行" in p for p in r["problems"])


def test_changing_kind_breaks_the_signature(env):
    """kind 在簽章範圍內：把 module 改成 full（想繞過單模組檢查）⇒ 簽章不符。"""
    _name, staged = _publish_stage(env)
    p = Path(staged, D.META_JSON)
    meta = json.loads(p.read_text(encoding="utf-8"))
    meta["kind"] = "full"
    p.write_bytes(json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8"))
    calls = []
    r = D.verify_staged(staged, str(_install(env["tmp"])), module_runner=_ok_runner(calls))
    assert not r["ok"] and any("簽章不符" in x for x in r["problems"])
    assert not calls


def test_unknown_kind_is_refused(env):
    assert pytest.raises(D.DeliveryError, D.package_kind, {"kind": "hotfix"})
    assert D.package_kind({}) == "full", "缺席 ⇒ full（本欄位之前發布的包）"


def test_bad_signature_never_runs_preflight(env, monkeypatch):
    _name, staged = _publish_stage(env)
    monkeypatch.setattr(D, "DELIVERY_PUBKEY_PEM", _keys()[1])        # 換一把公鑰 ⇒ 驗不過
    calls = []
    r = D.verify_staged(staged, str(_install(env["tmp"])), module_runner=_ok_runner(calls))
    assert not r["ok"] and not calls, "不在不信任的包上執行 preflight"


# ── 套用分派與結果 ────────────────────────────────────────────────────────────

def test_apply_module_runs_installed_script_and_copies_no_tools(env):
    _name, staged = _publish_stage(env)
    install = _install(env["tmp"])
    tools_before = sorted(p.name for p in (install / "backend" / "tools").iterdir())
    verified = D.verify_staged(staged, str(install), module_runner=_ok_runner())
    ran = []

    def fake(cmd):
        ran.append(cmd)
        logs = install / "backend" / "logs"
        logs.mkdir(exist_ok=True)
        (logs / "apply_module_update_20990101_000000.result.json").write_text(json.dumps(
            {"protocol": 2, "status": "success", "rolled_back": "applied", "service": "up", "exit": 0,
             "kind": "module", "module_key": "zz", "to_version": "1.1.0", "prod_base_commit": BASE}), encoding="utf-8")
        return 0, "::RESULT:: v=2 status=success rolled_back=applied service=up exit=0\n"

    r = D.apply_staged(staged, str(install), verified, JUDGE, run=fake)
    assert r["outcome"] == "succeeded", r
    assert ran[0][-4].endswith("apply_module_update.ps1") and ran[0][-4].startswith(str(install))
    assert sorted(p.name for p in (install / "backend" / "tools").iterdir()) == tools_before, "單模組包不可以複製任何工具"


def test_module_results_are_overlays_not_prod_commit(env):
    res = env["root"] / "results"
    res.mkdir()
    full = "20260928_100000_" + BASE[:8] + "_full"
    mod = "20260928_110000_" + BUILT[:8] + "_mod-zz"
    old = "20260928_090000_" + "c" * 8 + "_mod-zz"
    (res / (full + ".result.json")).write_text(json.dumps({"outcome": "succeeded", "commit": BASE, "finished_at": "2026-09-28T10:05:00"}), encoding="utf-8")
    (res / (mod + ".result.json")).write_text(json.dumps({"outcome": "succeeded", "commit": BUILT, "kind": "module", "module_key": "zz",
                                                          "to_version": "1.1.0", "prod_base_commit": BASE, "finished_at": "2026-09-28T11:05:00"}), encoding="utf-8")
    (res / (old + ".result.json")).write_text(json.dumps({"outcome": "succeeded", "commit": "c" * 40, "kind": "module", "module_key": "yy",
                                                          "to_version": "9", "prod_base_commit": "d" * 40, "finished_at": "2026-09-28T09:05:00"}), encoding="utf-8")
    assert D.latest_prod_commit(str(env["root"]))["commit"] == BASE, "模組包不改變正式機 commit"
    ov = D.module_overlays(str(env["root"]))
    assert set(ov) == {"zz"} and ov["zz"]["version"] == "1.1.0", "基準不是目前完整包的覆蓋 ⇒ 過期不算"


def test_write_back_carries_module_fields(env):
    out = D.write_back(str(env["root"]), "20260928_110000_" + BUILT[:8] + "_mod-zz",
                       {"status": "success", "kind": "module", "module_key": "zz", "from_version": "1.0.0", "to_version": "1.1.0",
                        "prod_base_commit": BASE, "commit": BUILT}, "succeeded", host="H")
    rec = json.loads(Path(out).read_text(encoding="utf-8"))
    assert rec["kind"] == "module" and rec["module_key"] == "zz" and rec["prod_base_commit"] == BASE


# ── 正式機一定有 module_update.py（主持裁示：REQUIRED_PKG_FILES 守門）────────────────

def test_required_pkg_files_include_module_tools():
    sys.path.insert(0, str(REPO / "tools" / "platform"))
    import product_select as PS
    for rel in ("tools/platform/module_update.py", "tools/platform/product_select.py"):
        assert rel in PS.REQUIRED_PKG_FILES
        assert (REPO / rel).is_file()
    r = subprocess.run(["git", "-C", str(REPO), "check-attr", "export-ignore", "--",
                        "tools/platform/module_update.py", "tools/platform/product_select.py"], capture_output=True, text=True)
    assert r.returncode == 0 and "set" not in r.stdout, "不可以被 export-ignore（完整包要帶）：%s" % r.stdout


# ── 稽核 D S4-S1：工具版本以格式比較，不用字串比 ──────────────────────────────────────

def test_tool_version_key_orders_and_rejects_bad_format():
    k = D.tool_version_key
    assert k("2026-09-28") < k("2026-09-28a") < k("2026-09-28b") < k("2026-09-29") < k("2026-10-01")
    for bad in ("2026-9-3", "v1", "", None, "2026-09-28ab", "2026-09-28A"):
        assert k(bad) is None, bad


def test_verify_refuses_unparseable_tool_versions(env):
    _name, staged = _publish_stage(env)
    install = _install(env["tmp"], tool_version="2026-9-30")
    r = D.verify_staged(staged, str(install), module_runner=_ok_runner())
    assert not r["ok"] and any("格式不認得" in p for p in r["problems"])


# ── 正式機沒有儀表板：CLI writeback（主持裁示）───────────────────────────────────

@pytest.mark.parametrize("res, outcome", [
    ({"status": "success", "exit": 0}, "succeeded"),
    ({"status": "success", "exit": 1}, "failed"),
    ({"status": "module_unhealthy_rolled_back", "exit": 1}, "failed"),
    ({"status": "checkonly_ok", "exit": 0}, "failed"),
    (None, "failed"),
    ({"unreadable": "x"}, "failed"),
])
def test_cli_outcome_is_fail_closed(res, outcome):
    assert D.outcome_from_result(res) == outcome


def test_cli_writeback_reads_the_result_file_and_writes_back(env):
    install = _install(env["tmp"])
    logs = install / "backend" / "logs"
    logs.mkdir()
    (logs / "apply_module_update_20260928_200000.result.json").write_text(json.dumps(
        {"status": "success", "exit": 0, "rolled_back": "applied", "service": "up", "kind": "module", "module_key": "zz",
         "to_version": "1.1.0", "prod_base_commit": BASE, "commit": BUILT, "finished_at": "2026-09-28 20:01:00"}), encoding="utf-8")
    name = "20260928_195000_" + BUILT[:8] + "_mod-zz"
    rc = D.main(["writeback", "--root", str(env["root"]), "--name", name, "--install-root", str(install)])
    assert rc == 0
    rec = json.loads((env["root"] / "results" / (name + ".result.json")).read_text(encoding="utf-8"))
    assert rec["outcome"] == "succeeded" and rec["kind"] == "module" and rec["module_key"] == "zz"
    assert D.module_overlays(str(env["root"])) == {}, "沒有完整包紀錄 ⇒ 覆蓋算不出來（不猜）"
