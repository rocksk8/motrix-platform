# -*- coding: utf-8 -*-
"""建包／階段測試工具鏈「預設無視窗」守門：背景（無主控台）執行時，每個 git／python／powershell 子行程會彈一個主控台視窗。

規則（靜態，AST）：`tools/platform/*.py` 與 `backend/tools/build_test_reuse.py` 內只要有 `subprocess.run/Popen/check_output/call/check_call`，
該檔必須 (a) 在入口呼叫 `nowindow.install()`，或 (b) 每個呼叫都明列 `creationflags=`；否則紅。
另：conftest 必須安裝（pytest 與 xdist worker 的所有子行程），且 Windows 上 `subprocess.Popen` 真的被換掉。
正對照：合成原始碼——沒旗標的呼叫必須被抓、有 install／有旗標的必須放行。
"""
import ast
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
_CALLS = {"run", "Popen", "check_output", "call", "check_call"}
#: 不在規則內：本身就是「視窗」工具／純函式模組（有自己的視窗語意）
EXEMPT = {"tools/platform/nowindow.py", "tools/platform/window_probe.py",
          "tools/platform/failfast.py"}        # failfast＝pytest 外掛，只在已安裝的 pytest 行程（conftest）內執行


def unflagged(src):
    """⇒ (有 subprocess 呼叫?, 沒帶 creationflags 的呼叫行號, 檔案有沒有 nowindow.install)。"""
    tree = ast.parse(src)
    calls, bad = 0, []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in _CALLS \
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "subprocess":
            calls += 1
            if not any(k.arg == "creationflags" or k.arg is None for k in n.keywords):         # **kw 視為可能帶
                bad.append(n.lineno)
    installs = "nowindow" in src and ".install()" in src
    return calls, bad, installs


def verdict(src):
    calls, bad, installs = unflagged(src)
    return bool(calls and bad and not installs), bad


def test_scanner_positive_control():
    assert verdict("import subprocess\nsubprocess.run(['git'])\n")[0] is True
    assert verdict("import subprocess\nsubprocess.Popen(['x'], creationflags=8)\n")[0] is False
    assert verdict("import subprocess\nif __name__=='__main__':\n    import nowindow\n    nowindow.install()\nsubprocess.run(['git'])\n")[0] is False
    assert verdict("import os\nos.system('x')\n")[0] is False                                   # 沒有 subprocess 呼叫


def _targets():
    out = sorted((ROOT / "tools" / "platform").glob("*.py")) + [ROOT / "backend" / "tools" / "build_test_reuse.py"]
    return [p for p in out if p.relative_to(ROOT).as_posix() not in EXEMPT]


def test_build_toolchain_subprocess_calls_are_windowless():
    bad = []
    for p in _targets():
        flagged, lines = verdict(p.read_text(encoding="utf-8"))
        if flagged:
            bad.append("%s：第 %s 行" % (p.relative_to(ROOT).as_posix(), "、".join(map(str, lines[:5]))))
    assert not bad, "這些工具的 subprocess 呼叫沒帶 creationflags，檔案也沒有 nowindow.install()（背景執行會彈主控台視窗）：\n" + "\n".join(bad)


def test_conftest_installs_nowindow():
    src = (ROOT / "backend" / "conftest.py").read_text(encoding="utf-8")
    assert "import nowindow" in src and "_nowindow.install()" in src


@pytest.mark.skipif(os.name != "nt", reason="只有 Windows 有主控台視窗問題")
@pytest.mark.skipif(os.environ.get("MOTRIX_SHOW_WINDOWS") == "1", reason="使用者明確要看視窗")
def test_popen_is_patched_in_this_pytest_process():
    import subprocess
    assert getattr(subprocess.Popen, "_motrix_nowindow", False) is True


@pytest.mark.skipif(os.name != "nt", reason="只有 Windows 有主控台視窗問題")
def test_child_of_a_consoleless_parent_gets_no_console_window_after_install(tmp_path):
    """機制本身：父行程沒有主控台（DETACHED_PROCESS）時，沒裝 nowindow 的子行程會得到一個可見的主控台視窗
    （實測：GetConsoleWindow()≠0 且可見）；裝了 ⇒ 0。這裡只驗「裝了」那一側（沒裝那一側會真的閃一個視窗，留在 docs 的實測紀錄）。"""
    import json
    import subprocess
    out = tmp_path / "r.json"
    child = tmp_path / "child.py"
    child.write_text(
        "import subprocess, sys, json\n"
        "sys.path.insert(0, %r)\nimport nowindow; nowindow.install()\n"
        "code = 'import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())'\n"
        "r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True).stdout.strip()\n"
        "open(%r, 'w').write(json.dumps(r))\n" % (str(ROOT / "tools" / "platform"), str(out)), encoding="utf-8")
    subprocess.Popen([sys.executable, str(child)], creationflags=0x00000008 | 0x00000200, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait()          # 父：沒有主控台（DETACHED）；本行程的 Popen 已被 conftest 補旗標，所以明列 DETACHED 才不被改
    assert json.loads(out.read_text()) == "0"
