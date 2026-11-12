# -*- coding: utf-8 -*-
"""日誌分流、輪替、保留期、噪音（2026-11-13，正式機 server.log 53 MB；設計見 helpers/log_setup.py 檔頭）。

守的事：
① access 只進 access.log、應用程式訊息只進 app.log（ERROR 兩邊都有），不互相混。
② server.log（console 兜底）：WARNING 以上照寫；INFO 只在開機期間照寫——**部署腳本的健康檢查讀 server.log 的開機那一段**，不能全關。
③ 輪替由行程自己做（不經過外部 handle）、輪替出來的舊檔 gzip；輪替失敗不丟例外、不每筆重試。
④ 任何檔打不開 ⇒ 分流整個不啟用、console 不被動到（日誌設定不可以變成起不來的理由）。
⑤ WinError 10054 噪音只計數、不寫 traceback；別種例外照舊完整記錄。
⑥ 保留期只刪「輪替出來的舊檔」，現行檔與 server.log.rotating 永遠不刪。
"""
import gzip
import io
import logging
import os
import time

import pytest

from helpers import log_setup as ls


@pytest.fixture()
def split(tmp_path):
    """裝上分流；並替 uvicorn／uvicorn.access 補上假的 console handler（真的 uvicorn 沒在跑）。"""
    root, uv, acc = logging.getLogger(), logging.getLogger("uvicorn"), logging.getLogger("uvicorn.access")
    consoles = {}
    added = []
    for name, lg in (("uvicorn", uv), ("access", acc)):
        buf = io.StringIO()
        h = logging.StreamHandler(buf)
        h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        lg.addHandler(h)
        consoles[name] = buf
        added.append((lg, h))
    root_buf = io.StringIO()
    root_h = logging.StreamHandler(root_buf)                    # basicConfig 的 root console handler
    root_h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    root.addHandler(root_h)
    added.append((root, root_h))
    consoles["root"] = root_buf
    old_uv_level, old_acc_level, old_root_level = uv.level, acc.level, root.level
    root.setLevel(logging.INFO)                    # 正式機 main.py 的 basicConfig(level=INFO)；pytest 預設是 WARNING
    uv.setLevel(logging.INFO)
    acc.setLevel(logging.INFO)
    uv_prop, acc_prop = uv.propagate, acc.propagate
    uv.propagate = acc.propagate = False           # 真 uvicorn 的設定
    inst = ls.install(str(tmp_path), max_bytes=4000, backups=3)
    assert inst is not None
    try:
        yield tmp_path, inst, consoles
    finally:
        inst.uninstall()
        for lg, h in added:
            lg.removeHandler(h)
        uv.setLevel(old_uv_level)
        acc.setLevel(old_acc_level)
        root.setLevel(old_root_level)
        uv.propagate, acc.propagate = uv_prop, acc_prop


def _flush(inst):
    for h in (inst.app_handler, inst.access_handler):
        h.flush()


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _wait_for(pred, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return pred()


# ── ① 分流 ──────────────────────────────────────────────────────────────────

def test_access_goes_only_to_access_log_and_app_messages_only_to_app_log(split):
    tmp, inst, consoles = split
    logging.getLogger("uvicorn.access").info('127.0.0.1:1 - "GET /api/ping HTTP/1.1" 200')
    logging.getLogger("myapp.worker").info("APP-LINE")
    logging.getLogger("uvicorn.error").info("UVICORN-ERROR-LOGGER-LINE")
    logging.getLogger("myapp.worker").error("BOOM-LINE")
    _flush(inst)
    access, app = _read(tmp / "access.log"), _read(tmp / "app.log")
    assert "GET /api/ping" in access and "APP-LINE" not in access and "BOOM-LINE" not in access
    assert "APP-LINE" in app and "UVICORN-ERROR-LOGGER-LINE" in app and "BOOM-LINE" in app
    assert "GET /api/ping" not in app, "access 不可以混進 app.log"
    assert app.count("APP-LINE") == 1 and app.count("UVICORN-ERROR-LOGGER-LINE") == 1, "同一行不可以寫兩次"


# ── ② console（server.log 兜底）──────────────────────────────────────────────

def test_console_keeps_boot_info_then_only_warnings_and_never_access(split):
    tmp, inst, consoles = split
    uv_log = logging.getLogger("uvicorn.error")
    uv_log.info("模組 case 1.2.3 已載入")                       # 開機期間的 INFO：健康檢查要找
    uv_log.info("Uvicorn running on http://0.0.0.0:666 (Press CTRL+C to quit)")
    uv_log.info("AFTER-BOOT-INFO")
    uv_log.warning("AFTER-BOOT-WARNING")
    uv_log.error("AFTER-BOOT-ERROR")
    logging.getLogger("uvicorn.access").info('"GET /x HTTP/1.1" 200')
    out = consoles["uvicorn"].getvalue()
    assert "模組 case 1.2.3 已載入" in out and "Uvicorn running on" in out, "開機那一段一定要留在 server.log（apply_update 健康檢查靠它）"
    assert "AFTER-BOOT-INFO" not in out, "開機之後的 INFO 不該再灌進 server.log"
    assert "AFTER-BOOT-WARNING" in out and "AFTER-BOOT-ERROR" in out, "WARNING 以上永遠照寫"
    assert consoles["access"].getvalue() == "", "access 不進 console"
    # 實跑 uvicorn 抓到的洞：「Uvicorn running on」只走 uvicorn 的 handler，root 的 console 也必須跟著收斂（共用開機狀態）
    logging.getLogger("tiny").info("ROOT-AFTER-BOOT-INFO")
    logging.getLogger("tiny").warning("ROOT-AFTER-BOOT-WARNING")
    root_out = consoles["root"].getvalue()
    assert "ROOT-AFTER-BOOT-INFO" not in root_out, "root console 沒有跟著收斂：開機後的 INFO 還是灌進 server.log"
    assert "ROOT-AFTER-BOOT-WARNING" in root_out
    # app.log 仍然有全部
    _flush(inst)
    assert "AFTER-BOOT-INFO" in _read(tmp / "app.log")


def test_console_boot_window_has_a_time_limit(tmp_path):
    f = ls.ConsoleBootFilter(ls.BootState(boot_window_s=-1))     # 視窗已過
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "late info", (), None)
    assert f.filter(rec) is False
    rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "late error", (), None)
    assert f.filter(rec) is True


# ── ③ 輪替與壓縮 ────────────────────────────────────────────────────────────

def test_rotation_gzips_the_old_file_keeps_all_lines_and_caps_the_generations(split):
    tmp, inst, _ = split
    lg = logging.getLogger("myapp.rot")
    for i in range(400):
        lg.info("line-%04d %s", i, "x" * 60)
    _flush(inst)
    assert _wait_for(lambda: (tmp / "app.log.1.gz").exists() and not list(tmp.glob("*.pending")) and not list(tmp.glob("*.tmp")))
    names = sorted(p.name for p in tmp.glob("app.log*"))
    assert "app.log" in names and "app.log.1.gz" in names
    assert len([n for n in names if n.endswith(".gz")]) <= 3, "最多保留 backups 份：%r" % names
    # 所有行都還在（現行檔＋各世代），沒有因為輪替掉資料；世代數沒超過上限時一行不少
    text = _read(tmp / "app.log")
    for p in tmp.glob("app.log.*.gz"):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            text += f.read()
    assert "line-0399" in text, "最新的一行一定在"
    assert text.count("line-") <= 400
    first_gen = tmp / "app.log.1.gz"
    with gzip.open(first_gen, "rt", encoding="utf-8") as f:
        assert "line-" in f.read(), "壓縮檔要讀得回來"


def test_rollover_failure_does_not_raise_and_is_not_retried_for_every_record(tmp_path, monkeypatch, capsys):
    real = os.replace
    calls = {"n": 0}

    def fake(src, dst, *a, **k):
        if str(src).endswith("app.log"):
            calls["n"] += 1
            raise PermissionError(13, "simulated: file is used by another process", str(dst))
        return real(src, dst, *a, **k)

    monkeypatch.setattr(ls.os, "replace", fake)
    monkeypatch.setattr(logging.handlers.os, "rename", lambda *a, **k: (_ for _ in ()).throw(PermissionError(13, "sim")), raising=False)
    h = ls.GzipRotatingFileHandler(str(tmp_path / "app.log"), maxBytes=500, backupCount=3, retry_after_s=3600)
    lg = logging.Logger("isolated.rollfail")
    lg.addHandler(h)
    try:
        for i in range(100):
            lg.warning("line-%03d %s", i, "y" * 40)
        h.flush()
    finally:
        h.close()
    assert calls["n"] == 1, "輪替失敗後不可以每一筆 log 都重試（標準 RotatingFileHandler 會）：%d 次" % calls["n"]
    text = _read(tmp_path / "app.log")
    assert "line-000" in text and "line-099" in text, "輪替失敗時要繼續寫、一行都不能掉"
    assert "輪替失敗" in capsys.readouterr().err, "失敗要在 stderr 留一行（進 server.log 兜底）"


def test_compress_failure_keeps_the_old_content_uncompressed(tmp_path, monkeypatch):
    pending = tmp_path / "app.log.1.gz.pending"
    pending.write_bytes(b"precious old log\n")
    dest = str(tmp_path / "app.log.1.gz")
    monkeypatch.setattr(ls.gzip, "open", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    ls._compress_file(str(pending), dest)
    assert (tmp_path / "app.log.1").read_bytes() == b"precious old log\n", "壓縮失敗不可以丟資料"
    assert not pending.exists() and not (tmp_path / "app.log.1.gz").exists()


def test_leftover_pending_from_a_killed_process_is_compressed_on_next_boot(tmp_path):
    (tmp_path / "app.log.2.gz.pending").write_bytes(b"left over\n")
    assert ls.recover_pending(str(tmp_path)) == 1
    assert _wait_for(lambda: (tmp_path / "app.log.2.gz").exists() and not (tmp_path / "app.log.2.gz.pending").exists())
    with gzip.open(tmp_path / "app.log.2.gz", "rb") as f:
        assert f.read() == b"left over\n"


# ── ④ 打不開 ⇒ 不啟用、不動 console ──────────────────────────────────────────

def test_if_a_log_file_cannot_be_opened_nothing_is_changed(tmp_path, capsys):
    blocker = tmp_path / "logs_is_a_file"
    blocker.write_text("x")
    uv = logging.getLogger("uvicorn")
    before = (list(logging.getLogger().handlers), list(uv.handlers), list(logging.getLogger("uvicorn.access").handlers))
    before_filters = [list(h.filters) for h in uv.handlers]
    assert ls.install(str(blocker)) is None
    after = (list(logging.getLogger().handlers), list(uv.handlers), list(logging.getLogger("uvicorn.access").handlers))
    assert before == after and before_filters == [list(h.filters) for h in uv.handlers], "失敗時不可以改動任何 handler／filter"
    assert "沒有啟用" in capsys.readouterr().err


def test_second_file_failure_does_not_leave_the_first_handler_attached(tmp_path, monkeypatch):
    real = ls.GzipRotatingFileHandler
    made = []

    def flaky(path, *a, **k):
        if os.path.basename(path) == ls.ACCESS_LOG_NAME:
            raise PermissionError(13, "sim", path)
        h = real(path, *a, **k)
        made.append(h)
        return h

    monkeypatch.setattr(ls, "GzipRotatingFileHandler", flaky)
    root_before = list(logging.getLogger().handlers)
    assert ls.install(str(tmp_path)) is None
    assert list(logging.getLogger().handlers) == root_before
    assert made and made[0].stream is None, "第一個檔要關掉（Windows 上沒關會鎖住檔案）"


# ── ⑤ 噪音 ──────────────────────────────────────────────────────────────────

def _reset_error(winerror=10054):
    e = ConnectionResetError(10054, "遠端主機已強制關閉一個現存的連線。")
    e.winerror = winerror
    return e


def _emit_asyncio(msg, exc):
    try:
        raise exc
    except Exception:
        import sys
        logging.getLogger("asyncio").error(msg, exc_info=sys.exc_info())


def test_winerror_10054_from_call_connection_lost_is_counted_not_written(split):
    tmp, inst, _ = split
    n0 = ls.noise_count()
    for _ in range(5):
        _emit_asyncio("Exception in callback _ProactorBasePipeTransport._call_connection_lost(None)", _reset_error())
    assert ls.noise_count() == n0 + 5
    _flush(inst)
    app = _read(tmp / "app.log")
    assert "WinError" not in app and "ConnectionResetError" not in app and "_call_connection_lost" not in app


def test_other_exceptions_on_the_asyncio_logger_are_still_recorded_in_full(split):
    tmp, inst, _ = split
    n0 = ls.noise_count()
    _emit_asyncio("Exception in callback SomethingElse.run()", _reset_error())                      # 同樣的例外、不同的 callback
    _emit_asyncio("Exception in callback _ProactorBasePipeTransport._call_connection_lost(None)", _reset_error(10053))   # 別種 WinError
    _emit_asyncio("Exception in callback _ProactorBasePipeTransport._call_connection_lost(None)", RuntimeError("real bug"))
    assert ls.noise_count() == n0, "只有『WinError 10054＋_call_connection_lost』才算噪音"
    _flush(inst)
    app = _read(tmp / "app.log")
    assert "SomethingElse.run" in app and "RuntimeError: real bug" in app and app.count("Traceback") == 3


# ── ⑥ 保留期 ────────────────────────────────────────────────────────────────

def test_prune_removes_only_old_rotated_files(tmp_path):
    now = time.time()
    old, fresh = now - 40 * 86400, now - 5 * 86400
    files = {
        "access.log.1.gz": old, "access.log.2.gz": fresh, "app.log.3.gz": old, "app.log.1.gz.pending": old, "app.log.4.gz.tmp": old,
        "server.log.1": old, "server.log.2": fresh,
        # 以下全部不可以刪
        "access.log": old, "app.log": old, "server.log": old, "server.log.rotating": old,
        "backup_job.log": old, "backup_job.log.1": old, "heartbeat_job.log": old, "unrelated.txt": old, "app.log.old.bak": old,
    }
    for name, mtime in files.items():
        p = tmp_path / name
        p.write_bytes(b"x")
        os.utime(p, (mtime, mtime))
    removed = ls.prune_rotated_logs(str(tmp_path), 30, now=now)
    assert sorted(removed) == sorted(["access.log.1.gz", "app.log.3.gz", "app.log.1.gz.pending", "app.log.4.gz.tmp", "server.log.1"])
    left = {p.name for p in tmp_path.iterdir()}
    assert left == set(files) - set(removed)


@pytest.mark.parametrize("bad", [None, 0, -5, "abc", ""])
def test_prune_with_a_broken_setting_deletes_nothing(tmp_path, bad):
    p = tmp_path / "app.log.1.gz"
    p.write_bytes(b"x")
    os.utime(p, (1, 1))
    assert ls.prune_rotated_logs(str(tmp_path), bad) == []
    assert p.exists()


def test_archive_prune_reads_the_retention_setting_default_30(tmp_path):
    import archive
    now = time.time()
    old = tmp_path / "app.log.1.gz"
    mid = tmp_path / "app.log.2.gz"
    for p, age in ((old, 45), (mid, 20)):
        p.write_bytes(b"x")
        os.utime(p, (now - age * 86400, now - age * 86400))
    removed = archive._prune_old_logs(str(tmp_path))          # 沒給天數 ⇒ 讀設定登錄（預設 30）
    assert removed == ["app.log.1.gz"] and mid.exists()
    assert archive._prune_old_logs(str(tmp_path), keep_days=10) == ["app.log.2.gz"]


def test_the_retention_group_has_the_log_keep_days_setting():
    from helpers import settings_groups  # noqa: F401
    from helpers import settings_registry as R
    f = {x["key"]: x for x in R.groups()["retention"]["fields"]}["log_keep_days"]
    assert (f["default"], f["min"]) == (30, 7)
    assert R.get("retention", "log_keep_days") == 30


def test_daily_backup_calls_the_log_prune_even_when_the_cloud_is_unavailable():
    """清日誌要跟雲端備份無關（與 server.log 輪替同一個位置）——靜態檢查呼叫順序：在 `_archive_ok()` 之前。"""
    import inspect
    import archive
    src = inspect.getsource(archive._daily_backup)
    assert "_prune_old_logs()" in src and src.index("_prune_old_logs()") < src.index("_archive_ok()")


# ── 接線 ────────────────────────────────────────────────────────────────────

def test_tests_never_create_log_files_and_main_wires_the_split():
    assert ls.enabled_by_environment() is False, "pytest 底下不可以建檔（import main 不能往真的 logs 目錄開檔）"
    import main
    assert hasattr(main, "_LOG_SPLIT") and main._LOG_SPLIT is None
    src = open(main.__file__, encoding="utf-8").read()
    assert "_log_setup.attach_noise_filter()" in src and "_log_setup.install(" in src
