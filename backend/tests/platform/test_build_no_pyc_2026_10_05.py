# -*- coding: utf-8 -*-
"""建包不得把 .pyc 帶進部署包的靜態守門（第44班；第40班的包裡有 tools/platform/__pycache__/product_select.cpython-312.pyc）。

build_deploy_package.ps1 要做到三件事（逐條有反向控制：突變腳本文字 ⇒ 轉紅）：
  ① Step 5（git archive）起設 `$env:PYTHONDONTWRITEBYTECODE = "1"`——之後所有 Python 步驟（產品選配、不出貨清單、版本紀錄精簡、驗證）都不寫 .pyc；
  ② 這個設定在**所有 pytest 呼叫之後**才出現（測試階段保留 .pyc 快取，省建包時間）；
  ③ 產品選配 `product_select.py apply` 之前有明確設定，且包內有 __pycache__ 的保險清掃（先於「不出貨清單」那一步）。
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PS1 = REPO / "backend" / "tools" / "build_deploy_package.ps1"
if not PS1.is_file():
    pytest.skip("build_deploy_package.ps1 不在這個安裝包", allow_module_level=True)
TEXT = PS1.read_text(encoding="utf-8-sig")
_SET = re.compile(r'\$env:PYTHONDONTWRITEBYTECODE\s*=\s*"1"')


def _check(text):
    """⇒ 問題清單（空＝通過）。純函式，反向控制用突變過的文字呼叫它。"""
    bad = []
    sets = [m.start() for m in _SET.finditer(text)]
    step5 = text.find("# --- Step 5: 用 git archive")
    apply_pos = text.find("& $pyExe $productSelect apply")
    last_pytest = max((m.start() for m in re.finditer(r"& \$pyExe -m pytest", text)), default=-1)
    if step5 < 0 or apply_pos < 0 or last_pytest < 0:
        return ["找不到 Step 5／產品選配／pytest 呼叫（腳本結構變了，守門要跟著改）"]
    if not sets:
        return ["沒有設 $env:PYTHONDONTWRITEBYTECODE = \"1\""]
    if not any(step5 <= s < apply_pos for s in sets):
        bad.append("Step 5 到產品選配之間沒有設 PYTHONDONTWRITEBYTECODE")
    if not any(s < apply_pos and s > step5 and apply_pos - s < 1500 for s in sets):
        bad.append("產品選配 apply 之前沒有（就近）明確設 PYTHONDONTWRITEBYTECODE")
    if any(s < last_pytest for s in sets):
        bad.append("PYTHONDONTWRITEBYTECODE 不可早於最後一個 pytest 呼叫（測試階段要保留 .pyc 快取）")
    sweep = text.find("__pycache__", apply_pos)
    export_ignore = text.find("export_ignore_list.py")
    if sweep < 0 or not (apply_pos < sweep < export_ignore):
        bad.append("產品選配之後、不出貨清單之前沒有 __pycache__ 清掃")
    return bad


def test_script_keeps_pyc_out_of_the_package():
    assert _check(TEXT) == []


@pytest.mark.parametrize("mut,name", [
    (lambda t: _SET.sub('$env:PYTHONDONTWRITEBYTECODE = "0"', t), "整個設定改成 0"),
    (lambda t: _SET.sub("", t), "拿掉設定"),
    (lambda t: _SET.sub("", t) + '\n$env:PYTHONDONTWRITEBYTECODE = "1"\n', "設定被挪到腳本最後（apply 之前沒設）"),
    (lambda t: '$env:PYTHONDONTWRITEBYTECODE = "1"\n' + t, "設定被挪到腳本最前面（連測試階段都不寫 .pyc）"),
    (lambda t: t.replace("__pycache__", "__nothing__"), "拿掉清掃"),
])
def test_reverse_control_mutations_turn_red(mut, name):
    assert _check(mut(TEXT)), "突變「%s」應該讓守門轉紅" % name
