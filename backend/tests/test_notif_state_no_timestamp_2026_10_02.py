# -*- coding: utf-8 -*-
"""notif.js 的元件狀態不可存「時間戳」：頁面狀態比對（test_e2e_case_switch_state：切換後的狀態＝重開的狀態）與序列化會看到它，
每次都不同。待簽數的抓取節流時間放模組層變數 `_approvalFetchedAt`（2026-10-01 紅點功能留下的 `this._approvalAt` 造成建包 e2e 紅燈）。"""
import re
from pathlib import Path

NOTIF = Path(__file__).resolve().parents[2] / "frontend" / "static" / "notif.js"
#: 把現在時間存進元件（this.<名稱> = Date.now()／new Date()）
STATE_TIMESTAMP = re.compile(r"this\.\w*(?:At|Time|Ts|Stamp)\w*\s*=\s*(?:Date\.now\(\)|new Date\()")


def test_notif_components_keep_no_timestamp_in_their_state():
    assert STATE_TIMESTAMP.findall(NOTIF.read_text(encoding="utf-8")) == []


def test_reverse_control_the_pattern_catches_a_state_timestamp():
    assert STATE_TIMESTAMP.search("this._approvalAt = Date.now()")
    assert STATE_TIMESTAMP.search("this.lastFetchTime = new Date().getTime()")
    assert not STATE_TIMESTAMP.search("_approvalFetchedAt = Date.now()")          # 模組層變數：允許
