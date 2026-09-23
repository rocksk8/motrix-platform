# -*- coding: utf-8 -*-
"""EM7 複核：18 處「迴圈裡靜默跳過一筆，而迴圈沒在數」逐一讀。

每一處回答：
  ① 跳過的那一筆會不會出現在**任何輸出**裡（log／回應／計數／後續查詢）
  ② 跳過它對使用者的**承諾**是什麼
  ③ 判定與依據
🔴 並且每一處都查一次「**計數器在不在別的函式裡**」（我自己標的 L7 誤判來源）：
   範圍從「迴圈子樹」放大到「整個函式」＋「函式回傳值有沒有可能帶數量」。
"""
import ast
import glob
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SP = r"C:\Users\hichan\AppData\Local\Temp\claude\C--Users-hichan\c0588b23-65c8-4872-9062-09101ec9fdb3\scratchpad"
s = io.open(os.path.join(SP, "em4_scan4.py"), encoding="utf-8").read().replace("\nmain()\n", "\n")
V4 = {"__name__": "v4"}
exec(compile(s, "em4_scan4.py", "exec"), V4)
G = V4["G"]
ROOT = V4["ROOT"]
SQL_DDL = re.compile(r"\b(ALTER\s+TABLE|CREATE\s+(TABLE|INDEX|TRIGGER|VIEW)|ADD\s+COLUMN|DROP\s+)", re.I)
MIG = re.compile(r"^_m\d{3}")
LOGN = ("logger", "log", "logging", "print", "_audit", "warning", "info", "error", "exception")


def lines_of(path):
    return io.open(path, encoding="utf-8", errors="replace").read().splitlines()


def find_sites():
    """回 [(file, handler_lineno, func, loop, tryname, tree)] —— 只取 continue/break 且迴圈沒在數。"""
    out = []
    files = [p for p in glob.glob(os.path.join(ROOT, "backend", "**", "*.py"), recursive=True)
             if G["in_scope"](p)]
    for f in files:
        try:
            tree = ast.parse(G["rd"](f))
        except SyntaxError:
            continue
        loops = [n for n in ast.walk(tree) if isinstance(n, (ast.For, ast.While))]
        for t in ast.walk(tree):
            if not isinstance(t, ast.Try):
                continue
            for h in t.handlers:
                if G["says"](h):
                    continue
                rk, rtext = G["ret_kind"](h)
                if not rtext.startswith(("continue", "break")):
                    continue
                lp = None
                for c in loops:
                    if c.lineno <= t.lineno <= (getattr(c, "end_lineno", c.lineno) or c.lineno):
                        if lp is None or c.lineno > lp.lineno:
                            lp = c
                if lp is None:
                    continue
                counted = False
                for n in ast.walk(lp):
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                       and n.func.attr in ("append", "add", "extend"):
                        counted = True
                    if isinstance(n, ast.AugAssign):
                        counted = True
                if counted:
                    continue
                out.append((f, h.lineno, G["encl"](tree, h.lineno), lp, tree))
    return out


def func_level_evidence(fn, src_lines):
    """把範圍從迴圈放大到**整個函式**：有沒有 log／計數／回傳數量。"""
    ev = {"log": [], "counter": [], "returns": []}
    if fn is None:
        return ev
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            nm = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if nm in LOGN:
                a = n.args[0].value[:60] if (n.args and isinstance(n.args[0], ast.Constant)
                                             and isinstance(n.args[0].value, str)) else ""
                ev["log"].append("%s:%d %s(%r)" % (fn.name, n.lineno, nm, a))
            elif nm in ("append", "add", "extend"):
                ev["counter"].append("%s:%d %s" % (fn.name, n.lineno, nm))
        elif isinstance(n, ast.AugAssign):
            ev["counter"].append("%s:%d +=" % (fn.name, n.lineno))
        elif isinstance(n, ast.Return) and n.value is not None:
            try:
                ev["returns"].append(ast.unparse(n.value)[:70])
            except Exception:
                pass
    return ev


def main():
    sites = find_sites()
    print("=== EM7 母體複驗：找到 %d 處（A 的號是 18）===" % len(sites))
    by_file = {}
    for f, ln, fn, lp, tree in sites:
        by_file.setdefault(os.path.relpath(f, ROOT).replace("\\", "/"), []).append((ln, fn, lp, f))
    for rel in sorted(by_file):
        print("  %-42s %d 處" % (rel, len(by_file[rel])))

    print()
    for rel in sorted(by_file):
        src = lines_of(os.path.join(ROOT, rel.replace("/", os.sep)))
        for ln, fn, lp, f in sorted(by_file[rel]):
            ev = func_level_evidence(fn, src)
            fname = fn.name if fn else "(模組層)"
            print("── %s:%d  函式 %s" % (rel, ln, fname))
            print("   for 行 :%d  %s" % (lp.lineno, src[lp.lineno - 1].strip()[:96]))
            # try 與 except 的實際內容
            lo = max(lp.lineno, ln - 4)
            for i in range(lo, min(ln + 2, len(src)) + 1):
                mark = ">>" if i == ln else "  "
                print("   %s %4d %s" % (mark, i, src[i - 1].rstrip()[:96]))
            end = getattr(lp, "end_lineno", lp.lineno) or lp.lineno
            print("   迴圈結束於 :%d，之後第一行：%s" % (end, (src[end].strip()[:90] if end < len(src) else "(檔尾)")))
            print("   🔴 函式層的證據（L7：計數器可能在迴圈外）")
            print("      log     %s" % (ev["log"][:3] if ev["log"] else "無"))
            print("      計數/收集 %s" % (ev["counter"][:3] if ev["counter"] else "無"))
            print("      回傳    %s" % (ev["returns"][:2] if ev["returns"] else "無（回 None）"))
            print()


main()
