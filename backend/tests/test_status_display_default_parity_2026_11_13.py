# -*- coding: utf-8 -*-
"""UX P1（2026-11-13）：『待審核』畫面一律顯示『待簽核』（使用者裁示；資料鍵不變）。

旗標 builder_status_display 關閉時，前端 `MotrixStatus.label()` 也要用內建預設（DEFAULTS），
所以後端 `status_display.defaults()` 與 JS 的 `DEFAULTS` 必須逐字一致——這題守住兩邊不會各改各的。
純函式＋node，可用 --noconftest 單跑。
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.abspath(os.path.join(HERE, ".."))
FRONT = os.path.abspath(os.path.join(BACKEND, "..", "frontend"))
sys.path.insert(0, BACKEND)
from helpers import status_display as S  # noqa: E402

NODE = shutil.which("node")


def _node(code):
    r = subprocess.run([NODE, "-e", code], cwd=FRONT, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_js_builtin_defaults_equal_backend_defaults():
    js = _node("global.window=undefined;const S=require('./static/status-chip.js');console.log(JSON.stringify(S.DEFAULTS))")
    d = S.defaults()
    assert js, "JS DEFAULTS 不可為空"
    for k, e in js.items():
        assert k in d, k
        assert e["label"] == d[k]["label"], (k, "label 兩邊不一致")
        assert e.get("names", {}) == d[k]["names"], (k, "names 兩邊不一致")
    # 反向：後端凡是『label 與鍵不同』或『有情境簡稱』且屬於這次改名的鍵，JS 都要有（finalized 等舊的由頁面自己的 fallback 保留，不在此列）
    renamed = [k for k in d if d[k]["label"] != k and "待審核" in k]
    for k in renamed:
        assert k in js, k


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_flag_off_label_shows_new_default_but_data_key_is_unchanged():
    out = _node("global.window=undefined;const S=require('./static/status-chip.js');"
                "console.log(JSON.stringify([S.label('待審核'),S.label('待審核','quote_list','審核中'),S.label('待審核','case','舊字'),S.label('差額待審核','cashier','差額待審核'),"
                "S.chipClass('待審核'),S.tone('待審核'),S.label('草稿'),S.label('已核准','case','原字')]))")
    assert out == ["待簽核", "待簽核", "待簽核", "差額待簽核", "st-chip st-chip--pending", "pending", "草稿", "原字"]
    assert "待審核" in S.STATUS_KEYS and "差額待審核" in S.STATUS_KEYS, "資料鍵必須保留，只改顯示"


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_admin_override_still_beats_builtin_default():
    payload = {"enabled": True, "statuses": S.effective_table({"statuses": {"待審核": {"label": "排隊簽核"}}}), "changed": {"待審核": ["label"]}}
    out = _node("global.window=undefined;const S=require('./static/status-chip.js');S.apply(%s);console.log(JSON.stringify([S.label('待審核'),S.label('待審核','case','x')]))"
                % json.dumps(payload, ensure_ascii=False))
    assert out == ["排隊簽核", "排隊簽核"]
