# -*- coding: utf-8 -*-
"""降低硬碟重複寫入（使用者 2026-09-30）：heartbeat 每 5 分鐘一次，原本正常也寫 2 行、log 永不輪替。

- 正常：狀態沒變、同一天 ⇒ 不寫 log、不重寫 state 檔；狀態改變（含壞→好）⇒ 寫；每天第一筆寫。
- 壞的狀態持續：每小時最多一筆（不淹沒，也看得出還在壞）。
- log 有大小上限（RotatingFileHandler）：heartbeat_job.log、backup_job.log。
"""
import importlib
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def hb(monkeypatch, tmp_path):
    from core import paths
    monkeypatch.setattr(paths, "LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(paths, "HEARTBEAT_CONFIG", str(tmp_path / "hb.json"))
    sys.modules.pop("heartbeat_job", None)
    mod = importlib.import_module("heartbeat_job")
    lines = []
    monkeypatch.setattr(mod.logger, "log", lambda level, msg, *a, **k: lines.append(("log", msg)))
    monkeypatch.setattr(mod.logger, "error", lambda msg, *a, **k: lines.append(("error", msg)))
    monkeypatch.setattr(mod.logger, "warning", lambda msg, *a, **k: lines.append(("warning", msg)))
    monkeypatch.setattr(mod.logger, "info", lambda msg, *a, **k: lines.append(("info", msg)))
    mod._lines = lines
    yield mod
    sys.modules.pop("heartbeat_job", None)


def _set_time(monkeypatch, mod, when):
    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return when
    monkeypatch.setattr(mod, "datetime", _DT)


def test_should_log_truth_table(hb):
    h = hb          # 用 fixture：import heartbeat_job 會在 LOGS_DIR 開 log 檔，必須先導到 tmp
    t = datetime(2026, 9, 30, 10, 5)
    assert h.should_log({}, "ok", t)                                                   # 第一筆
    same_day = {"status": "ok", "day": "2026-09-30", "hour": "2026-09-30 09"}
    assert not h.should_log(same_day, "ok", t)                                         # 正常＋同一天 ⇒ 不記
    assert h.should_log(same_day, "ok", datetime(2026, 10, 1, 0, 5))                   # 每天第一筆
    assert h.should_log(same_day, "local_down", t)                                     # 狀態改變
    down = {"status": "local_down", "day": "2026-09-30", "hour": "2026-09-30 10"}
    assert not h.should_log(down, "local_down", t)                                     # 壞的持續、同一小時 ⇒ 不記
    assert h.should_log(down, "local_down", datetime(2026, 9, 30, 11, 0))              # 每小時一筆
    assert h.should_log(down, "ok", t)                                                 # 壞→好要記


def test_normal_runs_write_one_log_line_per_day_and_one_state_write(hb, monkeypatch, tmp_path):
    Path(hb._CONFIG_PATH).write_text(json.dumps({"ping_url": "https://hc.example/x"}), encoding="utf-8")
    monkeypatch.setattr(hb, "_http_get", lambda url: True)
    for minute in (0, 5, 10, 15):
        _set_time(monkeypatch, hb, datetime(2026, 9, 30, 10, minute))
        hb.main()
    assert len(hb._lines) == 1, hb._lines
    st = Path(hb._STATE_PATH)
    assert st.is_file()
    mtime = st.stat().st_mtime_ns
    _set_time(monkeypatch, hb, datetime(2026, 9, 30, 10, 20))
    hb.main()
    assert st.stat().st_mtime_ns == mtime and len(hb._lines) == 1, "同一天正常 ⇒ 不重寫 state、不記 log"
    _set_time(monkeypatch, hb, datetime(2026, 10, 1, 0, 1))
    hb.main()
    assert len(hb._lines) == 2                                                         # 隔天第一筆


def test_failure_and_recovery_are_logged_and_a_long_outage_is_hourly(hb, monkeypatch):
    Path(hb._CONFIG_PATH).write_text(json.dumps({"ping_url": "https://hc.example/x"}), encoding="utf-8")
    up = {"v": True}
    monkeypatch.setattr(hb, "_http_get", lambda url: up["v"] or "hc.example" in url)   # 本機掛了但外部 /fail 仍可打
    for minute in (0, 5):
        _set_time(monkeypatch, hb, datetime(2026, 9, 30, 10, minute))
        hb.main()
    assert len(hb._lines) == 1                                                         # 正常，一筆
    up["v"] = False
    for minute in (10, 15, 20):
        _set_time(monkeypatch, hb, datetime(2026, 9, 30, 10, minute))
        hb.main()
    assert [k for k, _ in hb._lines].count("error") == 1, hb._lines                    # 掛了：同一小時只記一筆
    _set_time(monkeypatch, hb, datetime(2026, 9, 30, 11, 0))
    hb.main()
    assert [k for k, _ in hb._lines].count("error") == 2                               # 下一小時再記一筆（還在壞）
    up["v"] = True
    _set_time(monkeypatch, hb, datetime(2026, 9, 30, 11, 5))
    hb.main()
    assert hb._lines[-1][0] == "log" and "外部心跳打卡成功" in hb._lines[-1][1]          # 壞→好要記


def test_logs_have_a_size_cap(hb):
    for name in ("heartbeat_job.py", "backup_job.py"):
        src = (BACKEND / name).read_text(encoding="utf-8")
        assert "RotatingFileHandler" in src and "maxBytes" in src, name + " 的 log 要有大小上限"
        assert "logging.FileHandler(" not in src and "filename=_LOG_PATH" not in src, name + " 不可退回無上限的 FileHandler"
    h = hb
    assert h.LOG_MAX_BYTES <= 10 * 1024 * 1024 and h.LOG_BACKUPS <= 5
