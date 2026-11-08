# -*- coding: utf-8 -*-
"""前端 JS 的唯一列舉入口（測試用）。

為什麼要有：模組專屬 JS 住在 `backend/modules/<key>/js/`（STAGE-C-DESIGN §3；網址仍是 `/js/<檔名>`）。
只 `glob frontend/js` 或 `rglob frontend` 的守門，在 JS 搬進模組之後會**安靜地少掃**——
一份掃不到的檔與一份乾淨的檔，在結果上長得一樣。所以列舉 JS 一律走這裡；
`test_no_direct_js_enumeration` 會擋沒走這裡的新寫法。

頁面（.html）不在這裡：頁面位置一律經 `core.source_tree.page_files()`／`page_file()`。

[公開介面] FRONTEND, all_js, frontend_js, top_js, module_js, js_path, js_rel, display
"""
from pathlib import Path

from core import source_tree

FRONTEND = source_tree.BACKEND.parent / "frontend"


def frontend_js():
    """frontend 底下所有 .js（遞迴；不含 vendor 第三方函式庫）。"""
    return sorted(p for p in FRONTEND.rglob("*.js") if "vendor" not in p.parts)


def module_js():
    """各模組自有的 .js（`backend/modules/<key>/js/**`；不含 tests）。"""
    out = []
    for d in source_tree.module_dirs():
        jd = d / "js"
        if jd.is_dir():
            out += [p for p in jd.rglob("*.js") if "vendor" not in p.parts]
    return sorted(out)


def top_js():
    """頁面直接載入的專屬 JS：`frontend/js/*.js`（第一層）∪ 模組自有 .js。不含 `frontend/static`。"""
    return sorted((FRONTEND / "js").glob("*.js")) + module_js()


def all_js():
    """frontend 的 .js ∪ 模組自有 .js（依實體路徑排序、去重）。"""
    seen, out = set(), []
    for p in frontend_js() + module_js():
        r = p.resolve()
        if r not in seen:
            seen.add(r)
            out.append(p)
    return sorted(out, key=js_rel)


def js_rel(p):
    """顯示用的相對路徑：frontend 底下 ⇒ 相對 frontend（`js/x.js`）；模組底下 ⇒ `backend/modules/<key>/js/x.js`。"""
    p = Path(p)
    try:
        return p.resolve().relative_to(FRONTEND.resolve()).as_posix()
    except ValueError:
        return "backend/" + source_tree.rel(p)


def display(p):
    """訊息用路徑：frontend 底下 ⇒ `frontend/js/x.js`；模組底下 ⇒ `backend/modules/<key>/js/x.js`。"""
    r = js_rel(p)
    return r if r.startswith("backend/") else "frontend/" + r


def js_path(name):
    """`/js/<name>`（或 `static/<name>`）對應的實體檔：模組版優先，其次 frontend/js、frontend/static。找不到 ⇒ FileNotFoundError。"""
    name = str(name).replace("\\", "/")
    base = name.split("/")[-1]
    for d in source_tree.module_dirs():
        f = d / "js" / base
        if f.is_file():
            return f
    for sub in ("js", "static"):
        f = FRONTEND / sub / base
        if f.is_file():
            return f
    raise FileNotFoundError(name)
