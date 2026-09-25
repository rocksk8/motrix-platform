"""列出 app 的所有路由（含 include_router 進來的），新舊 FastAPI 都適用。

☠️ 2026-09-25（專案 .venv）：FastAPI 0.14x 起 `include_router` 不再把路由攤平進 `app.routes`，
   而是放一個 `_IncludedRouter`（沒有 `.path`）⇒ `[r.path for r in app.routes]` 只剩 /docs 那幾條，
   「端點存在嗎」類的測試全部判成不存在。hermes 環境的 0.133 還是攤平的，所以一直沒被發現。
"""


def all_routes(app):
    """[(path, methods, route_or_context)]：攤平後的每一條端點。"""
    out = []
    for r in app.routes:
        contexts = getattr(r, "effective_route_contexts", None)
        if callable(contexts):                      # FastAPI 0.14x：_IncludedRouter
            for c in contexts():
                out.append((c.path, set(c.methods or ()), c))
        elif hasattr(r, "path"):
            out.append((r.path, set(getattr(r, "methods", None) or ()), r))
    return out


def route_paths(app):
    return [p for p, _m, _r in all_routes(app)]
