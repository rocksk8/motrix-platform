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
#: UX P1 之前就存在、顯示字交給各頁 fallback 的舊鍵（凍結；見 test_legacy_fallback_key_list_is_frozen）
LEGACY_PAGE_FALLBACK_KEYS = {"finalized", "draft", "已拒絕", "已成案", "已提供"}


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
    # 反向（L2，hichan-9 審查）：**後端預設表裡每一個**「某情境顯示的字 ≠ 鍵本身」的鍵，JS 都要有——
    # 唯一的例外是下面這份 UX P1 之前就存在、刻意交給各頁 fallback 的舊鍵（不准再增加；新的改名一律進 JS DEFAULTS）。
    for k in d:
        shows_other = any(t != k for t in S._texts(d, k).values())
        if shows_other and k not in LEGACY_PAGE_FALLBACK_KEYS:
            assert k in js, "後端預設把『%s』顯示成別的字，但 JS DEFAULTS 沒有（旗標關閉時畫面會不一致）" % k


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_js_label_equals_backend_text_in_every_context_for_every_default_key():
    """逐鍵逐情境：JS 有的鍵 ⇒ label(k, ctx) 與後端 `_texts` 完全相同；JS 沒有的鍵 ⇒ 回頁面給的 fallback（舊鍵）。"""
    d = S.defaults()
    ctxs = ["default"] + list(S.CONTEXTS)
    out = _node("global.window=undefined;const S=require('./static/status-chip.js');const ks=%s,cs=%s,r={};"
                "for(const k of ks){r[k]={};for(const c of cs){r[k][c]=S.label(k,c==='default'?undefined:c,'__FB__')}}console.log(JSON.stringify(r))"
                % (json.dumps(list(d), ensure_ascii=False), json.dumps(ctxs)))
    js_keys = _node("global.window=undefined;const S=require('./static/status-chip.js');console.log(JSON.stringify(Object.keys(S.DEFAULTS)))")
    for k in d:
        texts = S._texts(d, k)
        for c in ctxs:
            if k in js_keys:
                assert out[k][c] == texts[c], (k, c, out[k][c], texts[c])
            else:
                assert out[k][c] == "__FB__", (k, c, "JS 沒有這個鍵卻改了字")


def test_legacy_fallback_key_list_is_frozen():
    """舊鍵清單只能是 UX P1 之前就有非恆等預設的那幾個；有人想把新鍵塞進來躲過反向契約，這題會擋。"""
    assert LEGACY_PAGE_FALLBACK_KEYS == {"finalized", "draft", "已拒絕", "已成案", "已提供"}


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
