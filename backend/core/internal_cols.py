# -*- coding: utf-8 -*-
"""L0 內部欄位剝除（U0a 洩漏防線；設計 docs/platform/plans/FRAMEWORK-ORG-UNITS-T57.md §14.10 #4）。

[單位] plat:internal_cols    [層] L0    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] INTERNAL_COLS, InternalColsMiddleware, is_internal, strip_headers, strip_internal_cols, strip_row
[不變式] ①只用標準函式庫。②單位鍵欄位（owner_unit_id、unit_id、legal_entity_id）是**內部欄位**：表加欄後，`SELECT *` 會把它們帶進 API 回應、匯出檔與健檢雜湊；
    本模組是唯一的剝除點，使用者看得見的輸出一律經它。③**沒有任何『輸出內部欄位』的開關**：日後要給有權限者看單位，請用另一個欄位名（例 `unitName`），
    不要在這裡開洞。④中介層只動 `application/json`、未壓縮、有 content-length 且不大於上限的回應；其他（檔案下載、串流、壓縮、非 JSON）原樣通過、不緩衝。
[契約題] backend/tests/platform/test_internal_cols.py
"""
import json
import logging

INTERNAL_COLS = ("owner_unit_id", "unit_id", "legal_entity_id")
_INTERNAL = frozenset(INTERNAL_COLS)
_NEEDLES = (b"unit_id", b"legal_entity_id")                                       # owner_unit_id 與 unit_id 都含 `unit_id`
_MAX_BODY = 16 * 1024 * 1024                                                        # 緩衝上限；超過原樣通過並記錯誤（不緩衝大檔）

_log = logging.getLogger("motrix.internal_cols")


def is_internal(name) -> bool:
    return isinstance(name, str) and name in _INTERNAL


def strip_internal_cols(obj):
    """遞迴剝除 dict 的內部鍵（list／tuple 逐項處理）；沒有內部鍵時回傳原物件本身（不複製）。"""
    if isinstance(obj, dict):
        if any(k in _INTERNAL for k in obj if isinstance(k, str)):
            return {k: strip_internal_cols(v) for k, v in obj.items() if not (isinstance(k, str) and k in _INTERNAL)}
        changed = False
        out = {}
        for k, v in obj.items():
            nv = strip_internal_cols(v)
            changed = changed or nv is not v
            out[k] = nv
        return out if changed else obj
    if isinstance(obj, list):
        new = [strip_internal_cols(v) for v in obj]
        return new if any(a is not b for a, b in zip(new, obj)) else obj
    if isinstance(obj, tuple):
        new = tuple(strip_internal_cols(v) for v in obj)
        return new if any(a is not b for a, b in zip(new, obj)) else obj
    return obj


def strip_row(row) -> dict:
    """單列（dict 或 sqlite3.Row）→ 不含內部欄位的 dict。"""
    d = dict(row)
    return {k: v for k, v in d.items() if k not in _INTERNAL}


def strip_headers(columns) -> list:
    """欄名／表頭清單 → 不含內部欄位的 list（保序）。"""
    return [c for c in columns if not is_internal(c)]


class InternalColsMiddleware:
    """純 ASGI 中介層（不是 BaseHTTPMiddleware：不吞串流、不多一層任務）。

    只在 `application/json`、無 `content-encoding`、`content-length` ≤ _MAX_BODY 時緩衝；快路徑＝本文裡找不到 `unit_id`／`legal_entity_id` 位元組就原樣送出，
    不做 JSON 解析。命中才解析→剝除→重新序列化（與 FastAPI JSONResponse 相同的緊湊格式）→更新 content-length。解析失敗原樣送出並記錄。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        state = {"buffer": False, "start": None, "chunks": []}

        async def _send(message):
            t = message["type"]
            if t == "http.response.start":
                headers = {k.lower(): v for k, v in message.get("headers", [])}
                ctype = headers.get(b"content-type", b"")
                clen = headers.get(b"content-length")
                if (ctype.startswith(b"application/json") and b"content-encoding" not in headers
                        and clen is not None and clen.isdigit() and int(clen) <= _MAX_BODY):
                    state["buffer"] = True
                    state["start"] = message
                    return
                if ctype.startswith(b"application/json") and (clen is None or (clen.isdigit() and int(clen) > _MAX_BODY)):
                    _log.error("JSON 回應無法緩衝檢查內部欄位（無 content-length 或超過上限）：%s", scope.get("path"))
                await send(message)
                return
            if t == "http.response.body" and state["buffer"]:
                state["chunks"].append(message.get("body", b""))
                if message.get("more_body"):
                    return
                body = b"".join(state["chunks"])
                start = state["start"]
                if any(n in body for n in _NEEDLES):
                    try:
                        data = json.loads(body)
                        new = strip_internal_cols(data)
                        if new is not data:
                            body = json.dumps(new, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    except ValueError:
                        _log.error("JSON 回應含單位欄位字樣但解析失敗，原樣送出：%s", scope.get("path"))
                headers = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"]
                headers.append((b"content-length", str(len(body)).encode("ascii")))
                await send({**start, "headers": headers})
                await send({"type": "http.response.body", "body": body})
                return
            await send(message)

        await self.app(scope, receive, _send)
