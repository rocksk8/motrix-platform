# -*- coding: utf-8 -*-
"""case v11（2026-11-13，估價單獨立條款）：把「目前報價單的條款設定」複製成估價單的初始值。

- `system_settings.quote_terms_presets`（條款組）→ `estimate_terms_presets`；`default_payment_terms`（預設付款條件）→ `estimate_default_payment_terms`。
  使用者：「報價單有獨立條款，估價單也要」「升級時把估價單條款的初始值複製成目前報價單的條款，讓既有行為不變，之後兩邊各自改」。
- 只在估價單那把鍵**還不存在**時複製（冪等；已經有人設過估價單條款就不蓋）；報價單的鍵一個位元都不動。
  報價單沒設過（鍵不存在）⇒ 估價單也不建鍵＝兩邊同樣落到內建預設文字，之後各自設各自的。
- 表不在 ⇒ 回原因字串＝未完成（下次啟動再補）；不自己 commit、不 import 會演進的程式碼（只用 SQL）。
- 回退：只進不退；舊程式不認得 estimate_* 兩個鍵（多出來的設定列沒有人讀）⇒ 回滾程式碼不需動資料。
"""
import json
from datetime import datetime

_PAIRS = (("quote_terms_presets", "estimate_terms_presets"),
          ("default_payment_terms", "estimate_default_payment_terms"))


def up(conn):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='system_settings'").fetchone():
        return "system_settings 表不存在，估價單條款初始值這次不複製、下次啟動再試"
    for src, dst in _PAIRS:
        if conn.execute("SELECT 1 FROM system_settings WHERE key=?", (dst,)).fetchone():
            continue                                                    # 估價單條款已存在 ⇒ 不蓋
        row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (src,)).fetchone()
        if row is None:
            continue                                                    # 報價單沒設過 ⇒ 兩邊都用內建預設
        conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?)",
                     (dst, row[0], datetime.now().isoformat()))
    return None
