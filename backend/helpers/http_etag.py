# -*- coding: utf-8 -*-
"""讀取端點的 ETag／304（T86 U7：首頁請求量最高；回到分頁會重打同幾支，內容多半沒變）。

用法（端點多帶一個 `request: Request`）：
    return json_etag(request, payload)                         # 內容沒變 ⇒ 304、沒有 body
    return json_etag(request, payload, volatile=("generatedAt",))   # 這些頂層鍵只是時間戳，不算「內容有變」

為什麼這樣做是安全的：
  - ETag 由「這一次、這位使用者」算出的回應內容雜湊而來；只有內容逐位相同才會 304，所以不會把別人的內容給誰，
    也不會讓舊資料多活一秒——每次請求仍然現算（省的是傳輸與前端重畫，不是後端計算）。
  - `Cache-Control: private, no-cache`：瀏覽器可存、但每次都要向伺服器驗證；`Vary: Authorization` 擋共用快取。
  - 瀏覽器 fetch() 會自動帶 If-None-Match，304 時直接給呼叫端原本那份 200 內容，前端程式不用改。
"""
import hashlib
import json

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response

CACHE_CONTROL = "private, no-cache"


def _digest(payload, volatile) -> str:
    body = payload
    if volatile and isinstance(payload, dict):
        body = {k: v for k, v in payload.items() if k not in volatile}
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return '"%s"' % hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def json_etag(request: Request, payload, *, volatile=()) -> Response:
    payload = jsonable_encoder(payload)
    etag = _digest(payload, volatile)
    headers = {"ETag": etag, "Cache-Control": CACHE_CONTROL, "Vary": "Authorization"}
    inm = request.headers.get("if-none-match") or ""
    if inm and (inm.strip() == "*" or etag in [t.strip().removeprefix("W/") for t in inm.split(",")]):
        return Response(status_code=304, headers=headers)
    return JSONResponse(payload, headers=headers)
