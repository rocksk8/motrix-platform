# -*- coding: utf-8 -*-
"""V7：派發單行 id（前端 `Date.now()+Math.random()` 產生的浮點數，經 JSON 存進 items_json）的行鍵，Python 正規化必須與 JS `String(x)` 逐字相同。
頁面不自己算行鍵（直接用後端回的 lineKey），但派發表單與其他前端會用 String(id)，兩端分歧就會對不上；用 node 實際跑同一組向量。沒有 node 就跳過。"""
import json
import random
import shutil
import subprocess
import time

import pytest

from modules.case import dispatch_lines as DL

NODE = shutil.which("node")


def _vectors():
    rnd = random.Random(20261107)
    v = [1.0, 1, 0, -0.0, 17.5, 100.0, 0.1, 0.5, 1e21, 1e20, 123456789012345680000.0, 1.5e-7, 1e-7, 0.000001, 1e-5, -3.0, 2.5e22, 12345.678,
         1730000000000.5, 1730000000000.1234, 9007199254740993, 2 ** 53]
    for _ in range(300):
        v.append(time.time() * 1000 + rnd.random())
        v.append(rnd.random() * 10 ** rnd.randint(-8, 22))
    return v


@pytest.mark.skipif(NODE is None, reason="沒有 node，跳過跨語言比對")
def test_numeric_line_keys_match_js_string():
    vals = _vectors()
    payload = json.dumps(vals)                                                 # 與 items_json 同一條路：Python 寫 JSON、JS 解析
    js = subprocess.run([NODE, "-e", "const v=JSON.parse(process.argv[1]);console.log(JSON.stringify(v.map(x=>String(x))))", payload],
                        capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert js.returncode == 0, js.stderr
    want = json.loads(js.stdout)
    got = [DL.raw_key(json.loads(payload)[i]) for i in range(len(vals))]        # 先經 JSON 往返，與正式路徑相同（整數值浮點會變 int）
    bad = [(vals[i], got[i], want[i]) for i in range(len(vals)) if got[i] != want[i] and not (got[i] == "0" and want[i] == "0")]
    assert not bad, bad[:5]


@pytest.mark.skipif(NODE is None, reason="沒有 node，跳過跨語言比對")
def test_string_ids_and_encoding_match_js_rules():
    cases = ["abc", "  spaced  ", "a#b", "50%", "%23", "a%b#c", "中文", ""]
    js = subprocess.run([NODE, "-e", "const v=JSON.parse(process.argv[1]);console.log(JSON.stringify(v.map(s=>String(s).trim().replace(/%/g,'%25').replace(/#/g,'%23'))))",
                         json.dumps(cases)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert js.returncode == 0, js.stderr
    assert [DL.line_key(c) for c in cases] == json.loads(js.stdout)
    for c in cases:                                                            # 編碼後可放進 ref，且互為反函數
        k = DL.line_key(c)
        if k:
            p = DL.parse_ref(DL.format_ref(7, k, 2))
            assert p and p["key"] == k and DL.decode_key(k) == c.strip()


def test_frontend_amount_rule_matches_backend_parse():
    """頁面 `_cents()`（最多 2 位小數、容許浮點雜訊、>0）與後端 `parse_amount` 對同一組向量的結論相同。"""
    if NODE is None:
        pytest.skip("沒有 node")
    from core import source_tree
    html = source_tree.page_file("settlement.html").read_text(encoding="utf-8")
    start = html.index("    _cents(s) {")
    end = html.index("    // 完整的列（品項＋合法金額）才寫進 offsets", start)
    fn = html[start:end].strip().rstrip(",")
    cases = [0.1 + 0.2, 33.33, 33.333, 0, -1, "12.5", "abc", "", 100, "1e2", 0.005, 1.005, 2000, "1200", " 800 "]
    script = "const o={%s};const v=JSON.parse(process.argv[1]);console.log(JSON.stringify(v.map(x=>o._cents(x))))" % fn
    js = subprocess.run([NODE, "-e", script, json.dumps(cases)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert js.returncode == 0, js.stderr
    assert [DL.parse_amount(c) for c in cases] == json.loads(js.stdout)
