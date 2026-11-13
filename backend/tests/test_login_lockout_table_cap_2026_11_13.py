# -*- coding: utf-8 -*-
"""LG-S6（T80 稽核 AUDIT-16，2026-11-13）：登入鎖定表 `_rl_state` 的上限要是硬的、清表成本要攤提。

舊行為：超過 `_RL_MAX_ENTRIES` 後只丟「沒鎖定且 1 小時沒再失敗」的列；一小時內灌大量不同前綴時
這些列都不 stale ⇒ 表繼續長，而且**每次失敗登入**都掃整張表（O(n)）卻丟不掉任何東西。
"""
import time

import pytest

import routers.auth as auth


class _CountingDict(dict):
    """數 `.items()`（＝整張表掃描）被呼叫幾次。"""
    scans = 0

    def items(self):
        type(self).scans += 1
        return super().items()


@pytest.fixture()
def small_table(monkeypatch):
    monkeypatch.setattr(auth, "_RL_MAX_ENTRIES", 50)
    monkeypatch.setattr(auth, "_RL_PRUNE_BATCH", 10, raising=False)
    monkeypatch.setattr(auth, "_rl_prune_next_at", 51, raising=False)
    _CountingDict.scans = 0
    monkeypatch.setattr(auth, "_rl_state", _CountingDict())
    monkeypatch.setattr(auth, "_rl_db_write", lambda *a, **k: None)     # 不碰資料庫
    return auth._rl_state


def _fail_once(i):
    auth._rl_fail("10.%d.%d.1" % (i // 250, i % 250), "u")


def test_lg_s6_flood_within_the_stale_window_cannot_grow_the_table_past_the_cap(small_table):
    for i in range(1000):                       # 全都是「剛剛才失敗」＝沒有任何一列 stale
        _fail_once(i)
        assert len(small_table) <= 50, "第 %d 次失敗後表長 %d，超過硬上限" % (i + 1, len(small_table))


def test_lg_s6_pruning_is_amortised_not_a_scan_per_failed_login(small_table):
    n = 1000
    for i in range(n):
        _fail_once(i)
    # 每 _RL_PRUNE_BATCH(10) 次新增才清一次表（一次清表＝2 次 .items()：stale 掃描＋未鎖定排序）；舊行為是超過上限後每次失敗都掃
    assert _CountingDict.scans <= 2 * (n // 10) + 10, "清表掃描 %d 次／%d 次失敗：不是攤提" % (_CountingDict.scans, n)
    assert _CountingDict.scans >= 1, "對照：確實有掃描發生（否則這題量不到東西）"


def test_lg_s6_locked_rows_survive_the_flood_and_the_oldest_unlocked_go_first(small_table):
    victim = "192.0.2.77"
    for _ in range(auth._LOGIN_MAX_FAILS):
        auth._rl_fail(victim, "u")
    with pytest.raises(Exception) as ei:
        auth._rl_check(victim)
    assert getattr(ei.value, "status_code", None) == 429, "前提：victim 已被鎖"
    for i in range(1000):
        _fail_once(i)
    with pytest.raises(Exception) as ei:
        auth._rl_check(victim)
    assert getattr(ei.value, "status_code", None) == 429, "被鎖的列被清表丟掉了＝等於解除鎖定"
    keys = set(small_table)
    assert auth._rl_key("10.3.249.1") in keys, "最新的未鎖定列要留著"
    assert auth._rl_key("10.0.0.1") not in keys, "最久沒失敗的未鎖定列要先丟"


def test_lg_s6_when_only_locked_rows_remain_the_scan_is_still_not_every_failure(small_table, monkeypatch):
    """全是鎖定列（無從丟）時表可以暫時超過上限，但不可以退化成每次失敗都掃。"""
    now = time.monotonic()
    for i in range(80):
        small_table["10.9.%d.1" % i] = {"fails": 0, "locked_until": now + 900, "last_fail": now}
    _CountingDict.scans = 0
    for i in range(200):
        _fail_once(i)
    assert _CountingDict.scans <= 2 * (200 // 10) + 10, "全鎖定列時退化成逐次掃描：%d 次" % _CountingDict.scans
    assert all(("10.9.%d.1" % i) in small_table for i in range(80)), "鎖定列一列都不能少"
