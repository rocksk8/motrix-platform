# -*- coding: utf-8 -*-
"""A29 突變執行器：套一個字串替換 → 跑指定測試 → 還原該檔（git checkout 單檔）。用法：mut.py <樹> <檔> <舊> <新> <測試...>"""
import os
import subprocess
import sys

tree, rel, old, new = sys.argv[1:5]
tests = sys.argv[5:]
PY = r"D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe"
path = os.path.join(tree, rel)
src = open(path, encoding="utf-8", newline="").read()
crlf = "\r\n" in src
s = src.replace("\r\n", "\n")
assert s.count(old) == 1, "舊字串出現 %d 次（要剛好 1 次）" % s.count(old)
mut = s.replace(old, new, 1)
open(path, "w", encoding="utf-8", newline="").write(mut.replace("\n", "\r\n") if crlf else mut)
try:
    chk = subprocess.run([PY, "-c", "import ast,sys;ast.parse(open(sys.argv[1],encoding='utf-8').read())", path], capture_output=True, text=True)
    if chk.returncode:
        print("COMPILE-RED（突變本身語法錯，不算）", chk.stderr[:200]); sys.exit(2)
    bt = os.path.join(os.environ["TEMP"], "motrix-pytest-a29mut-adhoc")
    r = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp=" + bt, "--tb=no", "-x"] + tests,
                       cwd=os.path.join(tree, "backend"), capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = [l for l in r.stdout.splitlines() if ("passed" in l or "failed" in l or l.startswith("FAILED"))]
    print("RESULT:", "RED（被抓到）" if r.returncode == 1 else ("GREEN（沒被抓到＝假綠燈）" if r.returncode == 0 else "exit %d" % r.returncode), "|", " / ".join(tail)[:300])
finally:
    subprocess.run(["git", "checkout", "--", rel], cwd=tree)
    subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", os.path.join(os.environ["TEMP"], "motrix-pytest-a29mut-adhoc")], capture_output=True)
