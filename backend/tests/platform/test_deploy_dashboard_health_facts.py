# -*- coding: utf-8 -*-
"""正式機健康事實收集（_prod_health_facts.ps1）對假的安裝根目錄直接跑（CORE-SPEC §9e D1、S-P02）。"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import deploy_dashboard as dd  # noqa: E402

SCRIPT = Path(dd.TOOLS_DIR) / "_prod_health_facts.ps1"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="PowerShell 腳本只在 Windows 跑")


def _facts(root: Path) -> dict:
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
                        "-Root", str(root), "-Port", "1"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def _mk(root: Path, rel: str, text: str = "x", mtime: float = None):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    if mtime:
        os.utime(p, (mtime, mtime))
    return p


def test_only_daily_snapshot_with_done_counts(tmp_path):
    """S-P02：pre_update_* 或沒有 .done 的日期資料夾，不可以讓「最近備份」變新。"""
    import time
    old = time.time() - 5 * 86400
    _mk(tmp_path, "backend/db_backups/2026-09-20/.done", mtime=old)
    _mk(tmp_path, "backend/db_backups/2026-09-24/motrix_erp.db")          # 沒有 .done：做到一半
    _mk(tmp_path, "backend/db_backups/pre_update_20260925/motrix_erp.db")  # 部署前快照：最新，但不算
    f = _facts(tmp_path)
    assert f["latestDbBackup"]["name"] == "2026-09-20"


def test_no_daily_snapshot_is_reported_as_none(tmp_path):
    _mk(tmp_path, "backend/db_backups/pre_update_20260925/motrix_erp.db")
    assert _facts(tmp_path)["latestDbBackup"] is None


def test_alert_and_dev_markers_are_collected(tmp_path):
    _mk(tmp_path, "backup_alerts/BACKUP_ALERT.txt", "雲端路徑不存在\n第二行")
    _mk(tmp_path, ".no_email_send")
    f = _facts(tmp_path)
    assert f["alertActive"] is True and f["alertText"].startswith("雲端路徑不存在")
    assert f["devMarkers"] == [".no_email_send"]


def test_evaluator_consumes_real_script_output(tmp_path):
    """端到端：真的腳本輸出餵給判斷規則，pre_update 不會讓健康檢查變綠。"""
    import deploy_insights as di
    _mk(tmp_path, "backend/db_backups/pre_update_20260925/motrix_erp.db")
    v = di.evaluate_health(_facts(tmp_path))
    assert not v["ok"] and any("找不到任何本機資料庫備份" in p for p in v["problems"])
