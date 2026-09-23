# -*- coding: utf-8 -*-
"""BR3：模組層的 if／try 包住路由註冊（唯讀，只報不改）。

判準：**在 import 當下決定「這支端點存不存在」** 的地方。
  => 開關在啟動之後才設 => 那支端點根本不存在 => 畫面 404/405
  => 而它看起來像「這個功能沒做」

用 ast 不用 grep（regex 會撿到註解裡的幽靈）。

## 已知限制（照 port_provenance 的做法，限制寫在輸出裡）
  L1 只認「模組層的 if/try 子樹裡有 router 裝飾器或 include_router」。
     工廠函式裡（def make_router(): ...）的條件註冊看不到 —— 那不是 import 當下決定的，
     但若那個工廠在模組層被呼叫，效果一樣。**未涵蓋。**
  L2 端點路徑取的是**裝飾器裡的字面值** ＋ 同檔 APIRouter(prefix=...)。
     路徑用變數或 f-string 組出來的取不到（會標「路徑未解析」）。
  L3 「關掉時畫面看到 404 還是 405」是**靜態推定**：同一路徑有沒有別的方法被註冊。
     沒有實際打過那個端點（那需要造 session，界線內不做）。
  L4 前端呼叫點用字串比對找，**串接出來的網址找不到**（例：'/api/x/' + id）。
     所以「前端沒有呼叫點」這句話是**弱結論**，反向（有呼叫點）才是強結論。
"""
import ast
import glob
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\hichan\Desktop\MOTRIX-ERP"
SKIP = ("tests", "tools", "rollback_snapshots", "scripts", "deploy_packages")
HTTP = ("get", "post", "put", "patch", "delete", "head", "options")


def rd(p):
    return io.open(p, encoding="utf-8", errors="replace").read()


def in_scope(p):
    parts = os.path.relpath(p, ROOT).replace("\\", "/").split("/")
    return not any(s in parts for s in SKIP)


def route_of(node):
    """FunctionDef 的裝飾器是不是 router.<method>('path')？回 (method, path|None)。"""
    out = []
    for d in getattr(node, "decorator_list", []):
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) \
           and d.func.attr in HTTP:
            base = d.func.value
            base_name = base.id if isinstance(base, ast.Name) else \
                (base.attr if isinstance(base, ast.Attribute) else "?")
            if base_name not in ("router", "app", "r"):
                continue
            path = None
            if d.args and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str):
                path = d.args[0].value
            out.append((d.func.attr.upper(), path, base_name))
    return out


def includes_of(node):
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
           and n.func.attr == "include_router":
            out.append(n.lineno)
    return out


def prefix_of(tree):
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "APIRouter":
            for kw in n.keywords:
                if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                    return kw.value.value
    return ""


def all_registered_paths():
    """全專案「無條件註冊」的 (path, method)，用來判斷關掉時是 404 還是 405。"""
    reg = set()
    for f in FILES:
        try:
            tree = ast.parse(rd(f))
        except SyntaxError:
            continue
        pre = prefix_of(tree)
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for m, path, _b in route_of(n):
                    if path is not None:
                        reg.add(((pre + path) if not path.startswith("/api") else path, m))
    return reg


FILES = [p for p in glob.glob(os.path.join(ROOT, "backend", "**", "*.py"), recursive=True)
         if in_scope(p)]


def frontend_refs(path):
    """前端有沒有字串比對得到的呼叫點。"""
    if not path:
        return []
    hits = []
    for f in glob.glob(os.path.join(ROOT, "frontend", "**", "*"), recursive=True):
        if not f.endswith((".js", ".html")) or "vendor" in f.replace("\\", "/"):
            continue
        s = rd(f)
        if path in s:
            ln = s.count("\n", 0, s.index(path)) + 1
            hits.append((os.path.relpath(f, ROOT).replace("\\", "/"), ln))
    return hits


def main():
    print("=== BR3 母體 ===")
    print("  掃 %d 支 .py（backend，排除 %s）" % (len(FILES), "／".join(SKIP)))
    REG = all_registered_paths()
    print("  全專案解析得到的 (路徑,方法) 組合 = %d" % len(REG))

    found = []
    for f in FILES:
        try:
            tree = ast.parse(rd(f))
        except SyntaxError:
            continue
        rel = os.path.relpath(f, ROOT).replace("\\", "/")
        pre = prefix_of(tree)
        for stmt in tree.body:                     # **只看模組層**
            if not isinstance(stmt, (ast.If, ast.Try)):
                continue
            routes, incs = [], includes_of(stmt)
            for n in ast.walk(stmt):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for m, path, base in route_of(n):
                        routes.append((m, path, base, n.lineno, n.name))
            if not routes and not incs:
                continue
            cond = ""
            if isinstance(stmt, ast.If):
                try:
                    cond = ast.unparse(stmt.test)
                except Exception:
                    cond = "(無法還原)"
            else:
                cond = "try/except（import 失敗就不註冊）"
            found.append((rel, stmt.lineno, type(stmt).__name__, cond, pre, routes, incs))

    print()
    print("=== ① 同族：模組層 if／try 包住路由註冊 = **%d 處** ===" % len(found))
    for rel, ln, kind, cond, pre, routes, incs in found:
        print()
        print("  ── %s:%d  (%s)" % (rel, ln, kind))
        print("     條件：%s" % cond[:120])
        if pre:
            print("     router prefix = %r" % pre)
        for m, path, base, rln, name in routes:
            full = path if (path or "").startswith("/api") else (pre + (path or ""))
            other = sorted({mm for pp, mm in REG if pp == full and mm != m})
            verdict = "405（同路徑有 %s）" % ",".join(other) if other else "404（這個路徑沒有別的方法）"
            fr = frontend_refs(full)
            print("     %-6s %-46s def %s (:%d)" % (m, full or "（路徑未解析）", name, rln))
            print("            關掉時推定 => %s" % verdict)
            print("            前端呼叫點 => %s" % (", ".join("%s:%d" % x for x in fr) if fr else "字串比對找不到（弱結論，見 L4）"))
        for i in incs:
            print("     include_router @ :%d" % i)

    print()
    print("=== ⚙️ 正對照：tender_radar.py:598 必須在上面 ===")
    got = [x for x in found if "tender_radar" in x[0]]
    print("  tender_radar 命中 %d 處 %s" % (len(got), "✅" if got else "🔴 這把尺無效"))

    print()
    print("=== ③ 不同族（分開報）：模組層讀環境變數但**不是**路由註冊 ===")
    for f in FILES:
        try:
            tree = ast.parse(rd(f))
        except SyntaxError:
            continue
        rel = os.path.relpath(f, ROOT).replace("\\", "/")
        for stmt in tree.body:
            src = ""
            try:
                src = ast.unparse(stmt)
            except Exception:
                continue
            if ("getenv" in src or "environ" in src) and isinstance(stmt, (ast.If, ast.Assign, ast.Expr)):
                has_route = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and route_of(n)
                                for n in ast.walk(stmt))
                if not has_route:
                    print("  %s:%d  %s" % (rel, stmt.lineno, src.split("\n")[0][:110]))

    print()
    print("=== 已知限制（照 BR2 的做法，寫在輸出裡）===")
    print(__doc__.split("## 已知限制")[1].rstrip())


main()
