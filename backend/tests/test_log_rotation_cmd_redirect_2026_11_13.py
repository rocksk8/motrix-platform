"""`server.log` 輪替在 Windows `cmd.exe` 的 `>>` 重導向下的行為（2026-11-13，正式機 11-11 起每 2 小時一次 PermissionError）。

根因（在 Windows 上實測）：`cmd.exe` 的 `>> file` 開檔**不給寫入共用** ⇒ 別的 handle 開寫入（`open(r+b)`／`open(ab)`）
`PermissionError [Errno 13]`、`os.replace`／`os.remove` `WinError 32`；**只有讀可以**（`shutil.copy2` 成功）。
舊版 copytruncate 因此「複製成功、清空失敗」，每輪白複製 50 MB 並把舊世代擠掉。

⚠️ 既有的 `test_writer_holding_append_handle_continues_correctly_after_rotation` 用 Python 自己 `open(path, "a")` 當寫入端——
Python 的 `open` 給寫入共用，所以那題在這個問題上**永遠是綠的**（假綠燈：測試的寫入端 ≠ 正式機的寫入端）。
本檔用真的 `cmd.exe /c … >> file 2>&1` 當寫入端。只在 Windows 跑（正式機就是 Windows）。
"""
import inspect
import os
import subprocess
import sys
import time

import pytest

import archive

pytestmark = pytest.mark.skipif(os.name != "nt", reason="cmd.exe 的 `>>` 重導向只有 Windows 有")


def _child_source(log_path, result_path, max_bytes=2000, keep=3, mode="own"):
    """子行程：stdout／stderr 被 cmd 的 `>>` 導進 log_path；把 archive 裡輪替用的三個函式原始碼抽出來執行（不 import archive——它要整個應用）。"""
    funcs = "\n\n".join(inspect.getsource(f) for f in (archive._stdio_fd_of, archive._truncate_log_in_place, archive._rotate_server_log_if_large))
    head = (
        "import os, shutil, time, logging, sys\n"
        "logger = logging.getLogger('child')\n"
        "_SERVER_LOG_PATH = %r\n_SERVER_LOG_MAX_BYTES = %d\n_SERVER_LOG_KEEP_GENERATIONS = %d\n_SERVER_LOG_ROTATE_WARN_AT = {}\n"
        % (log_path, max_bytes, keep)
    )
    body = (
        "for i in range(200):\n    print('before-rotation line %03d' % i, flush=True)\n"
        "res = _rotate_server_log_if_large(" + repr(log_path) + ", max_bytes=" + str(max_bytes) + ", keep=" + str(keep) + ")\n"
        "print('after-rotation line A', flush=True)\n"
        "print('after-rotation line B', file=sys.stderr, flush=True)\n"
        "open(" + repr(result_path) + ", 'w').write(repr(res))\n"
    )
    return head + funcs + "\n\n" + body


def _run_under_cmd_redirect(tmp_path, child_src):
    """跟 autostart.bat 同一種啟動方式：`python child.py >> server.log 2>&1`，由 cmd.exe 開檔。"""
    child = tmp_path / "child.py"
    child.write_text(child_src, encoding="utf-8")
    log = tmp_path / "server.log"
    bat = tmp_path / "run.bat"
    bat.write_text('@echo off\r\necho [boot] starting >> "%s"\r\n"%s" "%s" >> "%s" 2>&1\r\n' % (log, sys.executable, child, log), encoding="utf-8")
    r = subprocess.run(["cmd.exe", "/c", str(bat)], capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr[:300]


def test_rotation_works_when_cmd_redirect_owns_the_log(tmp_path):
    log = tmp_path / "server.log"
    result = tmp_path / "result.txt"
    _run_under_cmd_redirect(tmp_path, _child_source(str(log), str(result)))
    assert result.read_text() == "True", "輪替沒有成功（清空這一步被 cmd 的 `>>` 擋住＝11-11 起的 PermissionError）"
    raw = log.read_bytes()
    assert b"\x00" not in raw, "清空後寫入位置沒歸零：檔案前面被補了 NUL（實測舊偏移量會補 N 個 NUL）"
    text = raw.decode("utf-8")
    assert "after-rotation line A" in text and "after-rotation line B" in text, "輪替後 stdout／stderr 的新輸出要落在清空後的新檔裡"
    assert "before-rotation line 000" not in text, "輪替前的內容應該已搬走"
    archived = (tmp_path / "server.log.1").read_text(encoding="utf-8")
    assert "before-rotation line 000" in archived and "before-rotation line 199" in archived
    assert not (tmp_path / "server.log.rotating").exists()


def test_other_process_cannot_truncate_but_leaves_everything_untouched(tmp_path, caplog):
    """舊版的實際症狀：本行程不是寫入端（外部另開檔）⇒ 清空被擋。要求：回 False、原檔與既有世代原封不動、沒有暫存檔留下、
    只發一次 WARNING（不是每輪都 ERROR＋堆疊）。"""
    log = tmp_path / "server.log"
    holder = tmp_path / "holder.py"
    holder.write_text("import time\nfor i in range(400):\n    print('held line', i, 'x' * 40, flush=True)\n    time.sleep(0.05)\n", encoding="utf-8")
    bat = tmp_path / "run.bat"
    bat.write_text('@echo off\r\n"%s" "%s" >> "%s" 2>&1\r\n' % (sys.executable, holder, log), encoding="utf-8")
    (tmp_path / "server.log.1").write_bytes(b"gen1-keep-me")
    (tmp_path / "server.log.2").write_bytes(b"gen2-keep-me")
    proc = subprocess.Popen(["cmd.exe", "/c", str(bat)])
    try:
        deadline = time.time() + 15
        while time.time() < deadline and (not log.exists() or log.stat().st_size < 400):
            time.sleep(0.1)
        assert log.stat().st_size >= 400, "前提：寫入端已經寫了東西"
        before_size = log.stat().st_size
        caplog.clear()
        with caplog.at_level("WARNING", logger=archive.logger.name):
            archive._SERVER_LOG_ROTATE_WARN_AT.clear()
            assert archive._rotate_server_log_if_large(str(log), max_bytes=100, keep=3) is False
            assert archive._rotate_server_log_if_large(str(log), max_bytes=100, keep=3) is False
        assert log.stat().st_size >= before_size, "清空失敗時原檔不可以被動到"
        assert (tmp_path / "server.log.1").read_bytes() == b"gen1-keep-me", "清空失敗時不可以推世代（舊版會把 .1 換成白複製的那份、把更舊的擠掉）"
        assert (tmp_path / "server.log.2").read_bytes() == b"gen2-keep-me"
        assert not (tmp_path / "server.log.3").exists()
        assert not (tmp_path / "server.log.rotating").exists(), "暫存檔要清掉"
        warns = [r for r in caplog.records if "輪替沒成功" in r.getMessage()]
        errs = [r for r in caplog.records if r.levelname == "ERROR"]
        assert len(warns) == 1, "24 小時內同一個檔只提示一次：%r" % [r.getMessage() for r in caplog.records]
        assert not errs, "不要每輪都 ERROR＋堆疊"
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_stdio_fd_of_is_none_for_a_file_that_is_not_our_stdout(tmp_path):
    p = tmp_path / "plain.log"
    p.write_bytes(b"x")
    assert archive._stdio_fd_of(str(p)) is None
    assert archive._stdio_fd_of(str(tmp_path / "missing.log")) is None
