# -*- coding: utf-8 -*-
"""儀表板 D5：正式機模組狀態（CORE-SPEC §9e）。判斷規則＋對假安裝根目錄實跑 PowerShell 事實收集。"""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import deploy_dashboard as dd  # noqa: E402
import deploy_insights as di  # noqa: E402

LOCK = json.dumps({"lock_version": 1, "kind": "full_package",
                   "modules": {"tender_radar": {"version": "1.0.1"}, "bonus": {"version": "2.0.0"}}})


def test_states_from_log_and_lock_consistency():
    s = di.summarize_modules({
        "installed": [{"key": "tender_radar", "version": "1.0.1"}, {"key": "extra", "version": "0.1"}],
        "lockRaw": LOCK, "disabledRaw": '["extra"]',
        "logLines": ["2026-09-25 INFO 模組 tender_radar 1.0.1 已載入",
                     "2026-09-25 INFO 模組 extra 未載入：管理者已停用（資料保留）"]})
    rows = {r["key"]: r for r in s["rows"]}
    assert rows["tender_radar"]["state"] == "已載入"
    assert rows["extra"]["state"] == "未載入" and "停用清單內" in rows["extra"]["reason"]
    assert any("bonus 在 lock 裡、卻沒有安裝" in w for w in s["warnings"])
    assert any("extra 已安裝、卻不在 lock 裡" in w for w in s["warnings"])
    assert not any("載入失敗" in w for w in s["warnings"])          # 停用不是失敗


def test_failed_module_and_version_mismatch_warn():
    s = di.summarize_modules({
        "installed": [{"key": "tender_radar", "version": "1.0.0"}],
        "lockRaw": json.dumps({"modules": {"tender_radar": {"version": "1.0.1"}}}),
        "logLines": ["模組 tender_radar 未載入：requires core >=2.0, have 1.2"]})
    assert any("版本與 lock 不一致" in w for w in s["warnings"])
    assert any("載入失敗：requires core" in w for w in s["warnings"])


def test_no_log_means_unknown_not_loaded():
    s = di.summarize_modules({"installed": [{"key": "m", "version": "1"}], "lockRaw": None, "logLines": []})
    assert s["rows"][0]["state"].startswith("不明") and any("沒有 modules.lock.json" in w for w in s["warnings"])


def test_module_warnings_do_not_block_deploy():
    facts = {"alertActive": False, "latestDbBackup": {"name": "x", "at": "2099-01-01T00:00:00"},
             "disks": [{"name": "C", "freeGB": 100}], "installDrive": "C", "port666Listen": 1,
             "devMarkers": [], "piiFolders": ["x"],
             "modules": {"installed": [{"key": "m", "version": "1"}], "lockRaw": None, "logLines": []}}
    v = di.evaluate_health(facts)
    assert v["ok"] and v["modules"][0]["key"] == "m" and v["warnings"]


@pytest.mark.skipif(os.name != "nt", reason="PowerShell 腳本只在 Windows 跑")
def test_facts_script_collects_modules_from_a_fake_install(tmp_path):
    root = tmp_path
    (root / "backend" / "modules" / "tender_radar").mkdir(parents=True)
    (root / "backend" / "modules" / "tender_radar" / "module.json").write_text(
        json.dumps({"key": "tender_radar", "version": "1.0.1"}), encoding="utf-8")
    (root / "modules.lock.json").write_text(LOCK, encoding="utf-8")
    (root / "backend" / "logs").mkdir()
    (root / "backend" / "logs" / "server.log").write_text(
        "2026-09-25 INFO 模組 tender_radar 1.0.1 已載入\n其他行\n", encoding="utf-8")
    (root / "backend" / ".deployed_commit.json").write_text('{"commit": "abc"}', encoding="utf-8")
    db = root / "backend" / "motrix_erp.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE system_settings (key TEXT PRIMARY KEY, value_json TEXT)")
    c.execute("INSERT INTO system_settings VALUES ('modules_disabled', '[\"bonus\"]')")
    c.commit(); c.close()
    script = Path(dd.TOOLS_DIR) / "_prod_health_facts.ps1"
    cmd = f"[Console]::OutputEncoding=[System.Text.Encoding]::GetEncoding(932); & '{script}' -Root '{root}' -Port 1"
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert r.returncode == 0, r.stderr
    facts = json.loads(r.stdout.strip().splitlines()[-1])
    # Get-Content -Raw 的字串帶附加屬性，ConvertTo-Json 會把它變成物件（測試抓到）⇒ 原始檔內容必須是字串
    assert isinstance(facts["deployedRaw"], str) and json.loads(facts["deployedRaw"]) == {"commit": "abc"}
    m = facts["modules"]
    assert isinstance(m["lockRaw"], str) and all(isinstance(x, str) for x in m["logLines"])
    assert m["installed"] == [{"key": "tender_radar", "version": "1.0.1"}] or m["installed"] == {"key": "tender_radar", "version": "1.0.1"}
    assert json.loads(m["disabledRaw"]) == ["bonus"]
    rows = {x["key"]: x for x in di.summarize_modules(
        {**m, "installed": m["installed"] if isinstance(m["installed"], list) else [m["installed"]]})["rows"]}
    assert rows["tender_radar"]["state"] == "已載入"
    assert rows["bonus"]["installedVersion"] is None
    # DB 以唯讀模式讀：檔案內容不可以被改動
    assert sqlite3.connect(db).execute("SELECT value_json FROM system_settings").fetchone()[0] == '["bonus"]'
