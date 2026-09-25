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


@pytest.mark.parametrize("mfacts", [
    {"disabledRaw": "null"}, {"disabledRaw": "{}"}, {"disabledRaw": '"x"'}, {"disabledRaw": "[1]"},
    {"lockRaw": "[]"}, {"lockRaw": '"x"'}, {"lockRaw": '{"modules": []}'}, {"lockRaw": '{"modules": {"m": 1}}'},
    {"installed": {"key": "m", "version": "1"}}, {"installed": "x"}, {"installed": [1, None]},
    {"logLines": "模組 m 1 已載入"}, {"logLines": [None, 3]},
])
def test_unexpected_types_become_warnings_not_crashes(mfacts):
    # 稽核 D-2：正式機的檔與 DB 內容型別不可信；崩潰會讓上一次的「通過」繼續有效
    s = di.summarize_modules({"lockRaw": LOCK, "disabledRaw": "[]", "installed": [], "logLines": [], **mfacts})
    assert isinstance(s["rows"], list) and isinstance(s["warnings"], list)


def test_bad_disabled_list_is_a_warning():
    for raw in ("null", "{}", '"x"'):
        s = di.summarize_modules({"lockRaw": LOCK, "disabledRaw": raw})
        assert any("停用清單讀不懂" in w for w in s["warnings"]), raw


def test_unlicensed_state_parsed_from_the_real_loader_line():
    # 稽核 D-3：用 core/loader.py 真正的 log 格式，不自己編
    import re as _re
    src = (Path(dd.PROJECT_ROOT) / "backend" / "core" / "loader.py").read_text(encoding="utf-8")
    fmt = _re.search(r'"(模組 %s 未載入（未授權）[^"]*)"', src).group(1)
    line = "2026-09-25 WARNING " + (fmt % ("m", "授權檔沒有 m") if fmt.count("%s") == 2 else fmt % "m")
    s = di.summarize_modules({"installed": [{"key": "m", "version": "1"}], "lockRaw": None, "logLines": [line]})
    assert s["rows"][0]["state"] == "未授權"
    assert not any("載入失敗" in w for w in s["warnings"])


@pytest.mark.parametrize("mfacts,expect", [
    ({"disabledRaw": None, "disabledError": None, "dbMissing": True}, "找不到 motrix_erp.db"),
    ({"disabledRaw": None, "disabledError": ""}, "讀不到正式機的停用清單"),
    ({"disabledRaw": None}, "沒有取得正式機的停用清單"),
])
def test_unreadable_disabled_list_is_never_silent(mfacts, expect):
    # 稽核 D-6：讀不到≠沒有停用
    s = di.summarize_modules({"lockRaw": LOCK, **mfacts})
    assert any(expect in w for w in s["warnings"]), s["warnings"]


def test_missing_python_version_is_a_warning():
    facts = {"alertActive": False, "latestDbBackup": {"name": "x", "at": "2099-01-01T00:00:00"},
             "disks": [{"name": "C", "freeGB": 100}], "installDrive": "C", "port666Listen": 1,
             "devMarkers": [], "piiFolders": ["x"], "pythonVersion": None, "pythonError": "找不到 python"}
    v = di.evaluate_health(facts)
    assert any("沒有取得正式機的 Python 版本" in w and "找不到 python" in w for w in v["warnings"])


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


def m_is_ro(script):
    # 稽核 D-4：讀 DB 一定是唯讀連線（內容比對驗不到——任何 SELECT 都不改內容）
    return "?mode=ro" in Path(script).read_text(encoding="utf-8")


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
    # 服務用的 python 從 autostart.bat 取（正式機 WinRM 工作階段的 PATH 沒有 python，2026-09-25 實測）
    base = Path(sys.base_prefix)
    (root / "backend" / "autostart.bat").write_text(
        '"' + str(base / "Scripts" / "uvicorn.exe") + '" main:app --port 666'+'\r\n', encoding="utf-8")
    db = root / "backend" / "motrix_erp.db"
    c = sqlite3.connect(db)
    c.execute("PRAGMA journal_mode=WAL")                         # 稽核 D-4：正式庫是 WAL
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
    assert isinstance(facts["pythonVersion"], str) and facts["pythonVersion"].startswith("Python 3")
    assert facts["pythonSource"] == "autostart.bat" and Path(facts["pythonPath"]) == base / "python.exe"
    assert all("://" not in x for x in facts["pipFreeze"])      # 稽核 D-5：不帶 URL（可能含帳密）
    assert m_is_ro(script)
    assert isinstance(facts["pipFreeze"], list) and all(isinstance(x, str) for x in facts["pipFreeze"])
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


def test_single_installed_module_as_dict_is_still_listed():
    # ConvertTo-Json 會把單元素陣列拆成物件：只裝了一個模組的正式機要照樣列出來，不是「讀不懂」
    s = di.summarize_modules({"installed": {"key": "m", "version": "1"}, "lockRaw": None, "logLines": []})
    assert [r["key"] for r in s["rows"]] == ["m"]
    assert not any("讀不懂" in w for w in s["warnings"])


def test_fact_errors_become_warnings():
    facts = {"alertActive": False, "latestDbBackup": {"name": "x", "at": "2099-01-01T00:00:00"},
             "disks": [{"name": "C", "freeGB": 100}], "installDrive": "C", "port666Listen": 1,
             "devMarkers": [], "piiFolders": ["x"], "factErrors": ["Get-NetTCPConnection 失敗"]}
    assert any("Get-NetTCPConnection 失敗" in w for w in di.evaluate_health(facts)["warnings"])
