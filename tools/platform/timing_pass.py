# -*- coding: utf-8 -*-
"""計時門檻題的『安靜序列段』（第 51 班，SPEEDUP-IO-T50 §3）。

[單位] tool:timing_pass    [層] 部署工具
用法：python tools/platform/timing_pass.py [--list] [-- <額外的 pytest 參數>]
做什麼：單一程序（`-p no:xdist`）只跑掛 `@pytest.mark.timing` 的題——它們斷言牆鐘門檻（例：核准 < 200 ms、稽核搜尋 0.3 s、import main 不得等排程），
  在平行段與別的視窗的負載下會假紅（第 49 班 437 ms）。**跑的時候機器上不要有別的重工作**；門檻一個都沒放寬。
結束碼＝pytest 的結束碼（0 全綠）。`--list` 只列出會跑哪些題（collect-only）。
⚠️ 目前『沒有接進官方閘門』：平行段仍照舊跑這些題（所以閘門強度沒有下降）；要接進建包流程（平行段 `-m "not e2e and not timing"` ＋這一段）
  需要主持裁示並同步 build_deploy_package.ps1／build_test_reuse.py／modtest 的段別計數，見 SPEEDUP-IO-T50.md。
"""
import os
import subprocess
import sys

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    extra = []
    if "--" in argv:
        i = argv.index("--")
        argv, extra = argv[:i], argv[i + 1:]
    cmd = [sys.executable, "-m", "pytest", "-q", "-m", "timing", "-p", "no:xdist", "-p", "no:cacheprovider"]
    if "--list" in argv:
        cmd += ["--collect-only", "-q"]
    cmd += extra
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(cmd, cwd=BACKEND, creationflags=flags).returncode


if __name__ == "__main__":
    sys.exit(main())
