# -*- coding: utf-8 -*-
"""升級工具轉換後寫部署標記（IMPROVEMENT-REPORT §6；2026-09-27）。

原本只有 apply_update.ps1 寫 `backend/.deployed_commit.json`；V9 → 新版走 upgrade.py convert，標記沒寫
⇒ `/api/system/deployed-version` 與部署儀表板的 prod-status 轉換後仍回 V9 的 commit。
① convert 寫標記（格式同 apply_update.ps1：commit、commit_short、branch、applied_at、built_at），來源＝新版包的
   deploy_manifest.json → backend/.build_commit；都沒有 ⇒ 不寫、說明原因（不猜）。
② 端到端：轉換後 deployed-version 端點與 prod-status 回新 commit。
③ 轉換驗證不把標記的改變當成「設定被改寫」；其他設定照樣抓。
④ 兩種回滾都把標記還原成備份的那一份（V9 沒有 ⇒ 刪掉）；沒還原 ⇒ verify_rollback 報出來。
"""
import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from core import upgrade as U
from tests.platform.test_core_upgrade import _write, inst, new_src  # noqa: F401  （夾具）

MARK = "backend/.deployed_commit.json"
NEW_SHA = "abc1234def5678900000000000000000000000ff"
V9_MARK = {"commit": "v9v9v9v9", "commit_short": "v9v9v9v", "branch": "master",
           "applied_at": "2026-09-01 10:00:00", "built_at": "2026-09-01 09:00:00"}


def _manifest(src, **over):
    m = {"commit": NEW_SHA, "commit_short": "abc1234d", "branch": "platform", "product": "full",
         "built_at": "2026-09-27 21:00:00", **over}
    # 打包腳本用 PS 5.1 `Set-Content -Encoding UTF8` ⇒ 帶 BOM
    Path(src, "deploy_manifest.json").write_bytes(b"\xef\xbb\xbf" + json.dumps(m).encode("utf-8"))


def _mark(root):
    p = Path(root, MARK)
    return json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else None


def _convert(inst, new_src, bd, with_v9_mark=True):
    if with_v9_mark:
        _write(inst, MARK, json.dumps(V9_MARK).encode("utf-8"))
    m = U.backup(inst, bd)
    U.replace_program(inst, new_src)
    U.add_missing_settings(os.path.join(inst, "backend", "motrix_erp.db"))
    rep = U.write_deployed_marker(inst, new_src, now=datetime(2026, 9, 27, 23, 30, 0))
    return m, rep


def test_convert_writes_the_marker_from_the_package_manifest(inst, new_src, tmp_path):
    _manifest(new_src)
    m, rep = _convert(inst, new_src, str(tmp_path / "bk"))
    assert rep["written"] and rep["source"] == "deploy_manifest.json"
    assert _mark(inst) == {"commit": NEW_SHA, "commit_short": "abc1234d", "branch": "platform",
                           "applied_at": "2026-09-27 23:30:00", "built_at": "2026-09-27 21:00:00"}
    assert U.verify_conversion(inst, m) == [], "轉換本身寫的標記不算「設定被改寫」"


def test_marker_falls_back_to_build_commit_and_never_guesses(inst, new_src, tmp_path):
    _write(new_src, "backend/.build_commit", NEW_SHA.encode("ascii"))
    _m, rep = _convert(inst, new_src, str(tmp_path / "bk"))
    assert rep["written"] and rep["source"] == ".build_commit" and _mark(inst)["commit"] == NEW_SHA
    os.remove(os.path.join(new_src, "backend", ".build_commit"))
    rep2 = U.write_deployed_marker(inst, new_src)
    assert rep2 == {"written": False, "reason": "新版來源沒有 deploy_manifest.json 也沒有 backend/.build_commit"}
    assert _mark(inst)["commit"] == NEW_SHA, "不寫就是不動，不是清空"


def test_other_config_changes_are_still_caught(inst, new_src, tmp_path):
    """反向控制：排除只限部署標記——license.key 被改照樣是「設定檔被改寫」。"""
    _manifest(new_src)
    m, _rep = _convert(inst, new_src, str(tmp_path / "bk"))
    _write(inst, "backend/license.key", b"changed")
    assert any("設定檔被改寫" in p and "license.key" in p for p in U.verify_conversion(inst, m))


def test_after_conversion_deployed_version_reports_the_new_commit(inst, new_src, tmp_path, monkeypatch):
    """轉換後的安裝，/api/system/deployed-version 回新 commit（部署儀表板 prod-status 那一段在
    test_deploy_dashboard_prod_status_after_upgrade_2026_09_28.py——只有那個檔名准 import 儀表板，HC1c）。"""
    _manifest(new_src)
    _convert(inst, new_src, str(tmp_path / "bk"))
    from routers import auth as A
    monkeypatch.setattr(A, "_DEPLOYED_MARKER_PATH", os.path.join(inst, MARK))
    served = A.system_deployed_version()
    assert served["commit"] == NEW_SHA and served["commit_short"] == "abc1234d"


@pytest.mark.parametrize("mode", ["code", "full"])
@pytest.mark.parametrize("had_mark", [True, False], ids=["v9_had_marker", "v9_no_marker"])
def test_rollback_puts_the_marker_back(inst, new_src, tmp_path, mode, had_mark):
    _manifest(new_src)
    bd = str(tmp_path / "bk")
    _convert(inst, new_src, bd, with_v9_mark=had_mark)
    assert _mark(inst)["commit"] == NEW_SHA
    assert U.rollback(inst, bd, mode) == []
    assert _mark(inst) == (V9_MARK if had_mark else None)


def test_verify_rollback_catches_a_marker_left_at_the_new_version(inst, new_src, tmp_path):
    """反向控制：程式回到 V9、標記卻還是新版 ⇒ verify_rollback 要報出來（code 模式不比對設定，這一項要單獨比）。"""
    _manifest(new_src)
    bd = str(tmp_path / "bk")
    _convert(inst, new_src, bd)
    assert U.rollback(inst, bd, "code") == []
    _write(inst, MARK, json.dumps({"commit": NEW_SHA}).encode("utf-8"))
    assert any("部署標記" in p for p in U.verify_rollback(inst, U.load_manifest(bd), "code"))


def test_cli_convert_records_and_announces_the_marker(inst, new_src, tmp_path, monkeypatch, capsys):
    """CLI：convert 寫標記並記進 conversion_log；沒有來源時印出警告（不是靜默）。"""
    from tests.platform.test_core_upgrade import _backup_verified, _tool
    T = _tool(monkeypatch)
    bd = str(tmp_path / "bk")
    _backup_verified(T, inst, bd)
    rep = T.convert(inst, bd, new_src)
    assert rep["deployed_marker"]["written"] is False
    log = json.loads(Path(bd, "conversion_log.json").read_text(encoding="utf-8"))
    assert log["deployed_marker"]["written"] is False
    monkeypatch.setattr(T, "convert", lambda *a: rep)
    T.cmd_convert(type("A", (), {"root": inst, "backup_dir": bd, "new_source": new_src})())
    assert "沒有寫部署標記" in capsys.readouterr().out
