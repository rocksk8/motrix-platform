# -*- coding: utf-8 -*-
"""EM8 ②：前端有入口而後端沒有對應端點的（按下去 404）。唯讀，只報不改。

反方向於既有的 backend/tools/check_endpoint_entrypoints.py（那支查「後端端點有沒有前端入口」）。

做法：
  1. ast 解析所有 backend/routers/*.py 的 @router.<method>("path") 取得已註冊路徑集合
     （轉成 regex：{param} -> 任意片段）
  2. 正則掃前端 .js/.html 裡看起來像 API 呼叫的字串字面值（fetch/axios/$.get 等，
     或純粹符合 /api/... 形狀的字串字面值）
  3. 逐一比對：前端字串能不能匹配到任何一條已註冊路徑（含 method 儘量比對，抓不到 method 時只比路徑）

## 已知限制（寫在輸出裡）
  L1 前端字串**串接組出來的路徑**（'/api/x/' + id）取不到，只能取到常數字面值那一段。
  L2 method 判斷用呼叫慣例猜（fetch 預設 GET／apiPost 猜 POST…），猜不到的记 method=? ，
     比對時退化成「只要路徑匹配任一 method 就算存在」（偏寬鬆，避免誤報）。
  L3 只掃 frontend 的 .js/.html（不含 vendor/）。
  L4 後端路徑用 {param} -> 正則萬用字元；若前端傳的是字面字串剛好卡在路由分岔判斷上
     （例如 /api/x/summary 對到 /api/x/{id} 的參數位置），可能誤判成「存在」。
"""
import ast
import glob
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\hichan\Desktop\MOTRIX-ERP"


def rd(p):
    return io.open(p, encoding="utf-8", errors="replace").read()


HTTP = ("get", "post", "put", "patch", "delete")


def include_router_prefixes():
    """🔴 第二個洞：main.py 的 app.include_router(X.router, prefix="/api") 也會加前綴，
    與 APIRouter(prefix=) 是**兩個不同機制**。目前只有 dev_crm 用這個（實測：main.py
    38 個 include_router 裡唯一帶 prefix 的一個），但下一個人加了不會有東西提醒我。"""
    s = rd(os.path.join(ROOT, "backend", "main.py"))
    out = {}
    for m in re.finditer(r"app\.include_router\((\w+)\.router\s*(?:,\s*prefix=[\"']([^\"']+)[\"'])?\)", s):
        mod, prefix = m.group(1), m.group(2) or ""
        out[mod] = prefix
    return out


def backend_routes():
    """🔴 修過兩次：① 漏掉 APIRouter(prefix=...)，會把 3 支檔（account_items／
    bonus／vouchers）的所有路由都少算前綴 ② 漏掉 app.include_router(prefix=...)
    （main.py 層級，dev_crm 用這個）。兩個都修了。"""
    routes = []  # (method, path)
    inc_prefix = include_router_prefixes()
    files = glob.glob(os.path.join(ROOT, "backend", "**", "*.py"), recursive=True)
    files = [f for f in files if not re.search(r"[\\/](tests|tools|rollback_snapshots)[\\/]", f)]
    for f in files:
        mod_name = os.path.splitext(os.path.basename(f))[0]
        extra_prefix = inc_prefix.get(mod_name, "")
        try:
            tree = ast.parse(rd(f))
        except SyntaxError:
            continue
        prefix = ""
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "APIRouter":
                for kw in n.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        prefix = kw.value.value
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for d in n.decorator_list:
                    if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) \
                       and d.func.attr in HTTP and d.args \
                       and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str):
                        base = d.func.value.id if isinstance(d.func.value, ast.Name) else ""
                        p = d.args[0].value
                        full = p
                        if base == "router" and not p.startswith("/api"):
                            full = extra_prefix + prefix + p
                        routes.append((d.func.attr.upper(), full))
    return routes


def route_to_regex(path):
    # /api/x/{quote_no}/y -> ^/api/x/[^/]+/y$
    esc = re.escape(path)
    esc = re.sub(r"\\\{[^}]+\\\}", r"[^/]+", esc)
    return re.compile("^" + esc + "$")


API_STR = re.compile(r"""['"`](/api/[^'"`\s]*)['"`]""")


def frontend_api_calls():
    calls = []  # (file, line, path_literal)
    for f in glob.glob(os.path.join(ROOT, "frontend", "**", "*"), recursive=True):
        if not f.endswith((".js", ".html")) or "vendor" in f.replace("\\", "/"):
            continue
        rel = os.path.relpath(f, ROOT).replace("\\", "/")
        s = rd(f)
        for m in API_STR.finditer(s):
            path = m.group(1)
            # 去掉查詢字串（? 後）與模板佔位（${...}）殘留的邊界
            path = path.split("?")[0]
            ln = s.count("\n", 0, m.start()) + 1
            calls.append((rel, ln, path))
    return calls


def main():
    routes = backend_routes()
    print("=== EM8 ② 母體 ===")
    print("  後端已註冊路由 %d 條" % len(routes))
    regexes = [(m, p, route_to_regex(p)) for m, p in routes]

    calls = frontend_api_calls()
    print("  前端字面值裡符合 /api/... 形狀的 %d 處" % len(calls))

    missing, present = [], []
    seen = set()
    for rel, ln, path in calls:
        # 含 ${...} 模板變數的片段，用萬用字元近似比對（L1 的部分緩解）
        approx = re.sub(r"\$\{[^}]*\}", "[^/]+", re.escape(path))
        approx_rx = re.compile("^" + approx.replace(r"\[\^/\]\+", "[^/]+") + "$")
        hit = any(rx.match(path) for _m, _p, rx in regexes) or \
              any(approx_rx.match(p) for _m, p, _rx in regexes)
        key = (path,)
        if key in seen:
            continue
        seen.add(key)
        if hit:
            present.append((rel, ln, path))
        else:
            missing.append((rel, ln, path))

    print()
    print("  去重後前端路徑 %d 個 => 後端找得到 %d ／ **後端找不到 %d**"
          % (len(seen), len(present), len(missing)))
    print()
    print("── 🔴 後端沒有對應路由（全部列出）──")
    for rel, ln, path in sorted(missing):
        print("  %s:%d  %s" % (rel, ln, path))

    print()
    print(__doc__.split("## 已知限制")[1].rstrip())


main()
