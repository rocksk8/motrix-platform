# -*- coding: utf-8 -*-
"""部署儀表板的 prod-status 在升級工具轉換之後回新版 commit（IMPROVEMENT-REPORT §6；2026-09-28）。

轉換寫的部署標記見 test_upgrade_deployed_marker_2026_09_27.py；這裡驗儀表板那一端（檔名以 test_deploy_dashboard 開頭：
HC1c 只准這種檔 import 儀表板）。
"""
import os
import sys
from datetime import datetime
from pathlib import Path

from core import upgrade as U
from tests.platform.test_core_upgrade import inst, new_src  # noqa: F401  （夾具）
from tests.platform.test_upgrade_deployed_marker_2026_09_27 import MARK, NEW_SHA, _manifest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import deploy_dashboard as dd  # noqa: E402


class _R:
    def __init__(self, body):
        self.ok, self._b = True, body

    def json(self):
        return self._b


def test_prod_status_reports_the_converted_commit(inst, new_src, tmp_path, monkeypatch):
    """轉換（寫標記）⇒ 正式機的 deployed-version 端點讀它 ⇒ 儀表板 prod-status 的 deployed.commit＝新版 commit。"""
    _manifest(new_src)
    U.backup(inst, str(tmp_path / "bk"))
    U.replace_program(inst, new_src)
    assert U.write_deployed_marker(inst, new_src, now=datetime(2026, 9, 28, 0, 30))["written"]
    from routers import auth as A
    monkeypatch.setattr(A, "_DEPLOYED_MARKER_PATH", os.path.join(inst, MARK))
    monkeypatch.setattr(dd.requests, "get",
                        lambda url, **kw: _R(A.system_deployed_version() if url.endswith("/api/system/deployed-version") else {}))
    st = dd._check_prod_status()
    assert st["healthy"] and st["deployed"]["commit"] == NEW_SHA and st["deployed"]["commit_short"] == "abc1234d"
