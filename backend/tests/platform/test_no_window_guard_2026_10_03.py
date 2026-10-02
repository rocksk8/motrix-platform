# -*- coding: utf-8 -*-
"""建包／階段測試工具鏈「預設無視窗」守門：背景（無主控台）執行時，每個 git／python／powershell 子行程會彈一個主控台視窗。

規則（靜態，AST）：`tools/platform/*.py` 與 `backend/tools/build_test_reuse.py` 內只要有 `subprocess.run/Popen/check_output/call/check_call`，
該檔必須 (a) 在入口呼叫 `nowindow.install()`，或 (b) 每個呼叫都明列 `creationflags=`；否則紅。
另：conftest 必須安裝（pytest 與 xdist worker 的所有子行程），且 Windows 上 `subprocess.Popen` 真的被換掉。
正對照：合成原始碼——沒旗標的呼叫必須被抓、有 install／有旗標的必須放行。
"""
import ast
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
_CALLS = {"run", "Popen", "check_output", "call", "check_call"}
#: 不在規則內：本身就是「視窗」工具／純函式模組（有自己的視窗語意）
EXEMPT = {"tools/platform/nowindow.py", "tools/platform/window_probe.py",
          "tools/platform/failfast.py"}        # failfast＝pytest 外掛，只在已安裝的 pytest 行程（conftest）內執行


def _aliases(tree):
    """⇒ (subprocess 模組別名集合, 直接 from-import 進來的呼叫名集合, 是否 import os)。"""
    mods, names = set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name == "subprocess":
                    mods.add(a.asname or "subprocess")
        elif isinstance(n, ast.ImportFrom) and n.module == "subprocess":
            for a in n.names:
                if a.name in _CALLS:
                    names.add(a.asname or a.name)
    return mods, names


def _install_called(tree):
    """真的會執行的 `nowindow.install()`：不在函式／lambda／類別內（模組層或 `if __name__ == "__main__":` 內才算），
    且檔案有 import nowindow（任何別名）。⇒ 只在註解／字串／沒被呼叫的函式裡提到 install 不算。"""
    aliases = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            aliases |= {a.asname or a.name for a in n.names if a.name == "nowindow"}
        elif isinstance(n, ast.ImportFrom) and n.module == "nowindow":
            aliases |= {a.asname or a.name for a in n.names if a.name == "install"}
    if not aliases:
        return False

    def walk(node):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                continue
            if isinstance(ch, ast.Call):
                f = ch.func
                if (isinstance(f, ast.Attribute) and f.attr == "install" and isinstance(f.value, ast.Name) and f.value.id in aliases)                         or (isinstance(f, ast.Name) and f.id in aliases):
                    return True
            if walk(ch):
                return True
        return False
    return walk(tree)


def unflagged(src):
    """⇒ (有子行程呼叫?, 沒帶 creationflags 的呼叫行號, 檔案是否真的呼叫 nowindow.install)。
    呼叫＝`subprocess.run/Popen/check_output/call/check_call`（含 `import subprocess as sp`、`from subprocess import run`）與 `os.system/os.popen`。"""
    tree = ast.parse(src)
    mods, names = _aliases(tree)
    calls, bad = 0, []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        hit = False
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            hit = (f.value.id in mods and f.attr in _CALLS) or (f.value.id == "os" and f.attr in ("system", "popen"))
        elif isinstance(f, ast.Name):
            hit = f.id in names
        if hit:
            calls += 1
            if not any(k.arg == "creationflags" or k.arg is None for k in n.keywords):         # **kw 視為可能帶
                bad.append(n.lineno)
    return calls, bad, _install_called(tree)


def verdict(src):
    calls, bad, installs = unflagged(src)
    return bool(calls and bad and not installs), bad


def test_scanner_positive_control():
    assert verdict("import subprocess\nsubprocess.run(['git'])\n")[0] is True
    assert verdict("import subprocess\nsubprocess.Popen(['x'], creationflags=8)\n")[0] is False
    assert verdict("import subprocess\nif __name__=='__main__':\n    import nowindow\n    nowindow.install()\nsubprocess.run(['git'])\n")[0] is False
    assert verdict("import os\nos.system('x')\n")[0] is True   # os.system 也算
    assert verdict("import subprocess\n# nowindow.install()\nsubprocess.run(['git'])\n")[0] is True   # c7 S-2：只在註解提到
    assert verdict("import subprocess\nimport nowindow\ndef never():\n    nowindow.install()\nsubprocess.run(['git'])\n")[0] is True   # 沒被呼叫的函式裡
    assert verdict("import subprocess\nimport nowindow\nx = 'nowindow.install()'\nsubprocess.run(['git'])\n")[0] is True   # 只在字串
    assert verdict("from subprocess import run\nrun(['git'])\n")[0] is True   # from-import
    assert verdict("import subprocess as sp\nsp.run(['git'])\n")[0] is True   # 別名
    assert verdict("import subprocess as sp\nimport nowindow as nw\nnw.install()\nsp.run(['git'])\n")[0] is False   # 別名＋真的呼叫
    assert verdict("import os\nx = 1\n")[0] is False   # 沒有子行程呼叫


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


def test_every_installer_snippet_resolves_to_the_real_nowindow_dir():
    """c7 S-1：入口片段的 `parents[N] / "tools" / "platform"` 算錯會讓 `import nowindow` 失敗、被 `except ImportError: pass` 吞掉，
    守門仍綠但視窗回來。逐檔把片段算一遍，結果目錄必須真的有 nowindow.py。"""
    rx = re.compile(r'_p\.Path\(__file__\)\.resolve\(\)\.parents\[(\d)\]( / "tools" / "platform")?')
    bad, seen = [], 0
    for p in _targets():
        m = rx.search(p.read_text(encoding="utf-8"))
        if not m:
            continue
        seen += 1
        d = p.resolve().parents[int(m.group(1))]
        if m.group(2):
            d = d / "tools" / "platform"
        if not (d / "nowindow.py").is_file():
            bad.append("%s → %s" % (p.relative_to(ROOT).as_posix(), d))
    assert seen >= 20, "找不到入口片段（樣式變了？）"
    assert not bad, "入口片段的路徑算不到 nowindow.py：\n" + "\n".join(bad)
