# -*- coding: utf-8 -*-
"""路由與出口盤點（U0b-T1）：app 的每條端點（方法＋路徑）、是否寫入、路徑參數數、是否有請求本文；
另掃原始碼的 `SELECT *` 出口（按區域計數）。不是測試檔（底線開頭）；用法見 test_route_inventory.py。

寫入路由＝方法含 POST／PUT／PATCH／DELETE 的端點（一條路徑掛多個方法 ⇒ 每個方法各算一條）。
"""
import re
from pathlib import Path

WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")
_IGNORED_METHODS = ("HEAD", "OPTIONS")
BACKEND = Path(__file__).resolve().parents[2]

#: 區域 → 要掃的路徑（相對 backend/）。modules／routers／helpers／core 掃目錄（不含 tests）；archive 為單檔。
SELECT_STAR_AREAS = {
    "modules": "modules", "archive": "archive.py", "routers": "routers", "helpers": "helpers", "core": "core",
    "main_db": ("main.py", "db.py"),
}
_SELECT_STAR = re.compile(r"select\s+(?:distinct\s+)?(?:\w+\.)?\*", re.I)


def build_inventory(app) -> dict:
    """{"METHOD /path": {"w": 是否寫入, "pp": 路徑參數數, "body": 是否有請求本文參數}}（只含 /api/ 之外也列，供全貌；以 /api/ 為準另計）。"""
    from tests._routes import all_routes
    out = {}
    for path, methods, r in all_routes(app):
        dep = getattr(r, "dependant", None)
        pp = len(getattr(dep, "path_params", None) or [])
        body = bool(getattr(dep, "body_params", None))
        for m in sorted(set(methods) - set(_IGNORED_METHODS)):
            out["%s %s" % (m, path)] = {"w": m in WRITE_METHODS, "pp": pp, "body": body}
    return dict(sorted(out.items()))


def summarize(inv: dict) -> dict:
    api = {k: v for k, v in inv.items() if k.split(" ", 1)[1].startswith("/api/")}
    return {
        "endpoints_total": len(inv), "endpoints_api": len(api),
        "write_total": sum(1 for v in inv.values() if v["w"]),
        "write_api": sum(1 for v in api.values() if v["w"]),
        "get_api": sum(1 for k in api if k.startswith("GET ")),
        "distinct_paths_api": len({k.split(" ", 1)[1] for k in api}),
        "write_with_body_api": sum(1 for v in api.values() if v["w"] and v["body"]),
        "write_with_path_param_api": sum(1 for v in api.values() if v["w"] and v["pp"]),
    }


def _py_files(spec):
    for s in ((spec,) if isinstance(spec, str) else spec):
        p = BACKEND / s
        if p.is_file():
            yield p
        else:
            for f in sorted(p.rglob("*.py")):
                if "tests" not in f.relative_to(BACKEND).parts and "__pycache__" not in f.parts:
                    yield f


def count_select_star() -> dict:
    """{區域: 出現次數}；跨行的 `SELECT\n *` 也算。同一規則寫死在這裡，數字才可重現。"""
    out = {}
    for area, spec in SELECT_STAR_AREAS.items():
        n = 0
        for f in _py_files(spec):
            n += len(_SELECT_STAR.findall(f.read_text(encoding="utf-8", errors="replace")))
        out[area] = n
    return out
