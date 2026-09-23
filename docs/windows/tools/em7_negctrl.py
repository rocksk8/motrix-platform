# -*- coding: utf-8 -*-
"""負對照壞了 => 量「迴圈有在數」那 20 個裡，有幾個的計數**其實不是在數被跳過的那一筆**。

判準收緊：要算「跳過看得見」，記錄動作必須
  (a) 在 except handler 內，或
  (b) 在**同一層**迴圈本體（不是更內層的迴圈），且出現在 try 之後
否則就是「數的是別的東西」。
"""
import ast, glob, io, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SP = r"C:\Users\hichan\AppData\Local\Temp\claude\C--Users-hichan\c0588b23-65c8-4872-9062-09101ec9fdb3\scratchpad"
s = io.open(os.path.join(SP,"em4_scan4.py"), encoding="utf-8").read().replace("\nmain()\n","\n")
V4 = {"__name__":"v4"}; exec(compile(s,"em4_scan4.py","exec"), V4)
G = V4["G"]; ROOT = V4["ROOT"]
REC = ("append","add","extend")

def rec_nodes(scope):
    out = []
    for n in ast.walk(scope):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in REC:
            out.append(n)
        elif isinstance(n, ast.AugAssign):
            out.append(n)
    return out

def inner_loops(lp):
    return [n for n in ast.walk(lp) if isinstance(n,(ast.For,ast.While)) and n is not lp]

rows = []
for f in [p for p in glob.glob(os.path.join(ROOT,"backend","**","*.py"), recursive=True) if G["in_scope"](p)]:
    try: tree = ast.parse(G["rd"](f))
    except SyntaxError: continue
    rel = os.path.relpath(f, ROOT).replace("\\","/")
    loops = [n for n in ast.walk(tree) if isinstance(n,(ast.For,ast.While))]
    for t in ast.walk(tree):
        if not isinstance(t, ast.Try): continue
        for h in t.handlers:
            if G["says"](h): continue
            rk, rtext = G["ret_kind"](h)
            if not rtext.startswith(("continue","break")): continue
            lp = None
            for c in loops:
                if c.lineno <= t.lineno <= (getattr(c,"end_lineno",c.lineno) or c.lineno):
                    if lp is None or c.lineno > lp.lineno: lp = c
            if lp is None: continue
            allrec = rec_nodes(lp)
            if not allrec: continue          # 那是原本的 18 那批
            # 收緊：記錄動作必須在 handler 內，或在同層迴圈本體且行號 > try
            inner = inner_loops(lp)
            def in_inner(n):
                return any(il.lineno <= n.lineno <= (getattr(il,"end_lineno",il.lineno) or il.lineno) for il in inner)
            good = [n for n in allrec
                    if (h.lineno <= n.lineno <= (getattr(h,"end_lineno",h.lineno) or h.lineno))
                    or (not in_inner(n) and n.lineno > t.lineno)]
            rows.append((rel, h.lineno, G["encl"](tree,h.lineno).name if G["encl"](tree,h.lineno) else "?",
                         len(allrec), len(good)))
print("=== 「迴圈有在數」那一批：收緊判準後重算 ===")
print("  總數 %d" % len(rows))
bad = [r for r in rows if r[4] == 0]
print("  其中**記錄動作根本不在該跳過的那一層／那一段** = **%d** => 它們其實屬於 EM7" % len(bad))
for r in bad:
    print("     %s:%d  %-36s 迴圈內記錄 %d 個，但沒有一個在數被跳過的那一筆" % (r[0], r[1], r[2], r[3]))
print()
print("  仍然算「跳過看得見」的 = %d" % (len(rows)-len(bad)))
for r in rows:
    if r[4] > 0:
        print("     %s:%d  %-36s 合格記錄 %d" % (r[0], r[1], r[2], r[4]))
