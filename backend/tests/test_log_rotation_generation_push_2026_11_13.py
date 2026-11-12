# -*- coding: utf-8 -*-
"""server.log 輪替：清空成功之後推世代失敗，舊內容不可以消失、log 不可以說謊（hichan-6 審查 M-L，2026-11-13）。

清空成功後舊內容只存在 `server.log.rotating`。推世代（砍最舊、往後推、暫存檔改名 .1）任何一步丟 OSError 時：
舊版整段在外層 `except Exception` 裡，結果是 ① 只留一行 exception、② 下一輪的 `copy2` 直接覆蓋 .rotating ⇒ 那一代資料永久遺失。
現在：推世代失敗 ⇒ 暫存檔保留（或改名 .1）、log 寫明副本在哪；下一輪開始先接手上一輪殘留的 .rotating，不覆蓋。
純檔案操作，不需要 cmd.exe，所有平台都跑。"""
import os

import archive


def _log(tmp_path, body=b"A" * 300):
    p = tmp_path / "server.log"
    p.write_bytes(body)
    return p


def _fail_replace_when(monkeypatch, predicate):
    real = os.replace

    def fake(src, dst, *a, **k):
        if predicate(str(src), str(dst)):
            raise PermissionError(13, "simulated sharing violation", str(dst))
        return real(src, dst, *a, **k)

    monkeypatch.setattr(archive.os, "replace", fake)


def test_push_failure_after_truncate_keeps_the_old_content_and_says_so(tmp_path, monkeypatch, caplog):
    log = _log(tmp_path, b"OLD-CONTENT" * 30)
    (tmp_path / "server.log.1").write_bytes(b"gen1")
    # 把 .1 往後推成 .2 時被擋（例如 .2 被防毒／備份軟體開著）
    _fail_replace_when(monkeypatch, lambda s, d: s.endswith("server.log.1") and d.endswith("server.log.2"))
    archive._SERVER_LOG_ROTATE_WARN_AT.clear()
    with caplog.at_level("INFO", logger=archive.logger.name):
        res = archive._rotate_server_log_if_large(str(log), max_bytes=100, keep=3)
    assert res is True, "檔案確實已清空，回傳要如實"
    assert log.read_bytes() == b"", "前提：清空已經成功"
    rotating = tmp_path / "server.log.rotating"
    assert rotating.read_bytes() == b"OLD-CONTENT" * 30, "清空後舊內容只存在 .rotating——不可以消失"
    assert (tmp_path / "server.log.1").read_bytes() == b"gen1", "沒推成功的世代原封不動"
    msgs = [r.getMessage() for r in caplog.records]
    assert not any("rotated" in m for m in msgs), "沒推完世代不可以說 rotated：%r" % msgs
    assert any("推世代失敗" in m and "server.log.rotating" in m for m in msgs), "log 要寫明副本在哪：%r" % msgs


def test_push_failure_renames_the_copy_to_dot_one_when_that_slot_is_free(tmp_path, monkeypatch, caplog):
    log = _log(tmp_path, b"OLD" * 100)
    calls = {"n": 0}
    real = os.replace

    def fake(src, dst, *a, **k):
        # 第一次呼叫（_promote 裡的 tmp→.1）失敗，之後（fallback 的改名）放行
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(13, "simulated", str(dst))
        return real(src, dst, *a, **k)

    monkeypatch.setattr(archive.os, "replace", fake)
    archive._SERVER_LOG_ROTATE_WARN_AT.clear()
    with caplog.at_level("INFO", logger=archive.logger.name):
        assert archive._rotate_server_log_if_large(str(log), max_bytes=100, keep=3) is True
    assert (tmp_path / "server.log.1").read_bytes() == b"OLD" * 100
    assert not (tmp_path / "server.log.rotating").exists()


def test_remove_oldest_failure_also_keeps_the_content(tmp_path, monkeypatch):
    log = _log(tmp_path, b"OLD" * 100)
    for g in (1, 2, 3):
        (tmp_path / f"server.log.{g}").write_bytes(b"gen%d" % g)
    real = os.remove

    def fake(p, *a, **k):
        if str(p).endswith("server.log.3"):
            raise PermissionError(13, "simulated", str(p))
        return real(p, *a, **k)

    monkeypatch.setattr(archive.os, "remove", fake)
    archive._SERVER_LOG_ROTATE_WARN_AT.clear()
    assert archive._rotate_server_log_if_large(str(log), max_bytes=100, keep=3) is True
    assert (tmp_path / "server.log.rotating").read_bytes() == b"OLD" * 100
    for g in (1, 2, 3):
        assert (tmp_path / f"server.log.{g}").read_bytes() == b"gen%d" % g, "砍最舊失敗時其他世代不可以被動到"


def test_leftover_rotating_is_promoted_not_overwritten_by_the_next_round(tmp_path):
    """上一輪留下的 .rotating（唯一的一份舊內容）在下一輪必須先變成 .1，再做這輪的輪替；舊版 copy2 直接把它蓋掉。"""
    log = _log(tmp_path, b"NEW" * 100)
    (tmp_path / "server.log.rotating").write_bytes(b"PREVIOUS-ONLY-COPY")
    archive._SERVER_LOG_ROTATE_WARN_AT.clear()
    assert archive._rotate_server_log_if_large(str(log), max_bytes=100, keep=3) is True
    assert (tmp_path / "server.log.1").read_bytes() == b"NEW" * 100
    assert (tmp_path / "server.log.2").read_bytes() == b"PREVIOUS-ONLY-COPY", "上一輪那份要保存下來（推到 .2）"
    assert not (tmp_path / "server.log.rotating").exists()


def test_leftover_rotating_is_promoted_even_when_the_log_is_small(tmp_path):
    log = _log(tmp_path, b"x")
    (tmp_path / "server.log.rotating").write_bytes(b"PREVIOUS-ONLY-COPY")
    assert archive._rotate_server_log_if_large(str(log), max_bytes=10_000, keep=3) is False
    assert (tmp_path / "server.log.1").read_bytes() == b"PREVIOUS-ONLY-COPY"
    assert log.read_bytes() == b"x"


def test_leftover_that_cannot_be_promoted_blocks_the_round_instead_of_being_overwritten(tmp_path, monkeypatch):
    log = _log(tmp_path, b"NEW" * 100)
    (tmp_path / "server.log.rotating").write_bytes(b"PREVIOUS-ONLY-COPY")
    _fail_replace_when(monkeypatch, lambda s, d: s.endswith("server.log.rotating"))
    archive._SERVER_LOG_ROTATE_WARN_AT.clear()
    assert archive._rotate_server_log_if_large(str(log), max_bytes=100, keep=3) is False
    assert (tmp_path / "server.log.rotating").read_bytes() == b"PREVIOUS-ONLY-COPY", "接手失敗時不可以去動它"
    assert log.read_bytes() == b"NEW" * 100, "本輪不輪替（不複製、不清空）"
