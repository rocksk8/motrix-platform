# -*- coding: utf-8 -*-
"""第 51 班：題目通過就刪該題 tmp_path（conftest.cleanup_tmp_if_passed）；失敗保留、MOTRIX_KEEP_TMP=1 關閉。"""
import types

from conftest import cleanup_tmp_if_passed


def _node(tmp_path, passed, with_arg=True):
    d = tmp_path / "case"
    d.mkdir()
    (d / "f.txt").write_text("x")
    return d, types.SimpleNamespace(_motrix_call_passed=passed, funcargs=({"tmp_path": d} if with_arg else {}))


def test_passed_test_directory_is_removed(tmp_path):
    d, node = _node(tmp_path, True)
    assert cleanup_tmp_if_passed(node) is True and not d.exists()


def test_failed_test_directory_is_kept(tmp_path):
    d, node = _node(tmp_path, False)
    assert cleanup_tmp_if_passed(node) is False and (d / "f.txt").exists()


def test_keep_switch_and_missing_tmp_path_are_respected(tmp_path, monkeypatch):
    d, node = _node(tmp_path, True)
    monkeypatch.setenv("MOTRIX_KEEP_TMP", "1")
    assert cleanup_tmp_if_passed(node) is False and d.exists()
    monkeypatch.delenv("MOTRIX_KEEP_TMP")
    _d2 = types.SimpleNamespace(_motrix_call_passed=True, funcargs={})
    assert cleanup_tmp_if_passed(_d2) is False


def test_teardown_error_keeps_the_directory(tmp_path):
    d, node = _node(tmp_path, True)
    node._motrix_teardown_failed = True
    assert cleanup_tmp_if_passed(node) is False and (d / "f.txt").exists()
