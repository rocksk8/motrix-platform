# -*- coding: utf-8 -*-
"""請求冪等鍵（`Idempotency-Key` 標頭）：弱訊號下「回應掉了、伺服器其實已經存好」時，重送不會產生第二份資料。

[單位] helper:idempotency    [層] L1    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] Call, HEADER, REPLAY_HEADER, RETENTION_DAYS, STALE_SECONDS, begin, parse_key, replay_response, request_hash, run, run_sync
[不變式] ①沒帶 `Idempotency-Key` ⇒ 行為與沒有這個機制時逐位元相同。②重播不執行處理函式（不存檔、不寫資料、不通知、不稽核）。
    ③key 只在同一使用者（username）內唯一。④finish／abort 只動「自己這一代」的列（created_at 世代柵欄）；被 stale 接手取代者變 no-op。
    ⑤表 `idempotency_keys`（core migration，只增）：主鍵 (username, key)；`req_hash`＝請求內容指紋；`state` in_progress／done；7 天前的列在寫入時順手清。
[契約題] backend/tests/test_idempotency_2026_11_11.py

## 為什麼要有

手機外勤（T80c）在弱訊號下要「重試」。上傳類端點每次都用新的 uuid 檔名、新增一列資料，沒有任何「這個請求處理過了嗎」的判斷：
回應在路上掉了、前端重送 ⇒ 同一張照片／同一則留言存兩份。冪等鍵讓前端重試沿用同一把 key，伺服器認得「這個請求我做過」。

## 協定（選填；沒帶標頭＝行為與沒有這個機制時逐位元相同）

| 情況 | 行為 |
|---|---|
| 新 key | 寫 `in_progress`（立刻 commit，別的請求看得到）→ 呼叫端照常處理 → 成功 `finish()` 存回應 |
| 同 key＋同端點＋同內容指紋＋`done` | **重播**儲存的回應（同狀態碼、同內容；`Idempotent-Replay: true`）；**不再存檔、不再寫資料、不再發通知** |
| 同 key，但端點或內容指紋不同 | 422（同一把 key 不能拿去送不同的東西） |
| 同 key＋`in_progress`、未滿 `STALE_SECONDS` | 409 ＋ `Retry-After`（前端稍後重試） |
| `in_progress` 已超過 `STALE_SECONDS` | 視為上次處理到一半就死了：接手重做（重新蓋上新的時間戳＝新的「世代」） |
| 處理中丟例外（含 4xx） | `abort()` 刪掉那一列：修正內容後可以用同一把 key 重送 |
| 處理中被取消（`CancelledError`） | 預設留著 `in_progress`（結果不明，等 stale 接手）；處理函式「所有 await 都在寫入之前」的端點傳 `abort_on_cancel=True` ⇒ 取消時直接釋放，用戶端斷線重試不必等 stale |

**世代柵欄（fencing）**：每次寫入列（新建或接手）都把當下的 `created_at` 字串記在 `Call` 上；`finish()`／`abort()` 的 WHERE 都帶 `created_at=<我的世代>`。
被接手取代的原請求之後才 finish／abort ⇒ rowcount 0 ⇒ 什麼都不做（不會刪掉接手者的列、也不會用舊回應蓋掉接手者的回應）。

key 只在「同一個使用者（username）」內唯一（別人的 key 與你的互不影響，也看不到）。7 天前的列在寫入時順手清掉（不另開排程）。

## 已知限制

- **超過 `STALE_SECONDS`（120 秒）仍在跑的請求會被接手 ⇒ 可能雙寫**（原請求其實跑完了，資料已寫；接手者又做一次）。冪等層擋不住這個。
  外勤用形狀 B（一個請求一張照片、文字先存），單一請求的處理時間是秒級，120 秒有很大餘裕；若日後有更慢的端點要套用，先量處理時間再決定。
- **key 必須隨內容更換**：`request_hash` 對檔案只看（檔名, 大小）——手機常把拍照都叫 `image.jpg`，同一把 key 夾不同內容但同大小的機率極低、但不是零。
  前端規格：每個請求（每張照片、每次新的送出）一把新 key，只有「同一個請求的重試」沿用。
- async 端點用 `run()`：begin／finish／abort 都在 threadpool 跑（它們是同步 SQLite，`BEGIN IMMEDIATE` 遇到別人握鎖會等；不可以卡住事件迴圈）。
- 檔案是在 INSERT 之前存的（既有行為）：行程在「存檔之後、寫入之前」死掉會留孤兒檔；冪等鍵不改變這點。
- `finish()` 失敗（極少見）只記 log、不讓請求失敗（資料已經寫好了）；代價是那一次之後的重送會被當成新請求。
"""
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from core.txn import write_txn
from db import get_db

logger = logging.getLogger(__name__)

HEADER = "Idempotency-Key"
REPLAY_HEADER = "Idempotent-Replay"
#: `in_progress` 超過這麼久就當作上次處理到一半就死了，可以接手
STALE_SECONDS = 120
#: 完成的列保留多久（之後在寫入時順手清掉）
RETENTION_DAYS = 7
_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{8,128}$")


def parse_key(raw):
    """標頭值 → 合法的 key 或 None（沒帶）。帶了但格式不對 ⇒ 400（不悄悄忽略：前端以為有保護其實沒有）。"""
    if raw is None or str(raw).strip() == "":
        return None
    key = str(raw).strip()
    if not _KEY_RE.match(key):
        raise HTTPException(400, "Idempotency-Key 格式不正確（8～128 個英數字、底線或連字號）")
    return key


def request_hash(*parts):
    """請求內容指紋：呼叫端把「決定這個請求是不是同一個」的內容傳進來（文字欄位、各檔的 (檔名, 大小) …）。"""
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def replay_response(call):
    """重播儲存的回應。"""
    return JSONResponse(status_code=call.replay["status"], content=call.replay["body"],
                        headers={REPLAY_HEADER: "true"})


class Call:
    """一次帶 key 的請求。`replay` 不是 None ⇒ 呼叫端直接 `return replay_response(call)`；否則照常處理，
    成功時 `call.finish(status, body)`、失敗時 `call.abort()`（用 `with call.guard():` 包起來最不會漏）。"""

    def __init__(self, username, key, replay=None, stamp=None):
        self.username, self.key, self.replay = username, key, replay
        self.stamp = stamp                 # 這個請求寫入列時的 created_at（世代）；finish／abort 只動「還是我這一代」的列
        self._closed = False

    def finish(self, status_code, body):
        if self._closed:
            return
        self._closed = True
        try:
            payload = json.dumps(body, ensure_ascii=False, default=str)
            conn = get_db()
            try:
                cur = conn.execute("UPDATE idempotency_keys SET state='done', status_code=?, response_json=? "
                                   "WHERE username=? AND key=? AND created_at=?",
                                   (int(status_code), payload, self.username, self.key, self.stamp))
                conn.commit()
                if cur.rowcount == 0:      # 已被接手（stale）或被清掉：不蓋掉接手者的狀態
                    logger.warning("idempotency: finish 時這一代已被取代（key=%s），略過", self.key)
            finally:
                conn.close()
        except Exception:  # noqa: BLE001 — 資料已經寫好了，不可以讓請求因此失敗
            logger.exception("idempotency: finish 失敗（key=%s）", self.key)

    def abort(self):
        if self._closed:
            return
        self._closed = True
        try:
            conn = get_db()
            try:
                conn.execute("DELETE FROM idempotency_keys WHERE username=? AND key=? AND state='in_progress' AND created_at=?",
                             (self.username, self.key, self.stamp))
                conn.commit()
            finally:
                conn.close()
        except Exception:  # noqa: BLE001
            logger.exception("idempotency: abort 失敗（key=%s）", self.key)

    def guard(self):
        """`with call.guard():` ⇒ 區塊內丟任何例外就 abort（然後照常往外丟）。"""
        return _Guard(self)


class _Guard:
    def __init__(self, call):
        self.call = call

    def __enter__(self):
        return self.call

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None and issubclass(exc_type, Exception):   # 取消（CancelledError）不算失敗：結果不明，留給 stale 接手
            self.call.abort()
        return False


def begin(username, key, endpoint, req_hash):
    """開始一次帶 key 的請求 → `Call`（`call.replay` 有值 ⇒ 重播）。key 為 None ⇒ 回 None（呼叫端照舊處理）。
    409／422 以 HTTPException 丟出。"""
    if key is None:
        return None
    now = datetime.now()
    conn = get_db()
    try:
        with write_txn(conn):
            _purge(conn, now)
            row = conn.execute(
                "SELECT endpoint, req_hash, state, status_code, response_json, created_at FROM idempotency_keys "
                "WHERE username=? AND key=?", (username, key)).fetchone()
            if row is None:
                stamp = now.isoformat()
                conn.execute("INSERT INTO idempotency_keys (username, key, endpoint, req_hash, state, created_at) "
                             "VALUES (?,?,?,?,'in_progress',?)", (username, key, endpoint, req_hash, stamp))
                conn.commit()
                return Call(username, key, stamp=stamp)
            if row["endpoint"] != endpoint or row["req_hash"] != req_hash:
                raise HTTPException(422, "這個 Idempotency-Key 已經用在不同的請求上，請換一個新的（或確認內容沒有被改動）")
            if row["state"] == "done":
                try:
                    body = json.loads(row["response_json"] or "null")
                except ValueError:
                    body = None
                return Call(username, key, replay={"status": int(row["status_code"] or 200), "body": body})
            age = (now - _parse(row["created_at"], now)).total_seconds()
            if age < STALE_SECONDS:
                raise HTTPException(409, "同一個請求還在處理中，請稍後再試", headers={"Retry-After": "3"})
            stamp = now.isoformat()
            conn.execute("UPDATE idempotency_keys SET created_at=? WHERE username=? AND key=?",
                         (stamp, username, key))            # 接手重做：新的世代
            conn.commit()
            return Call(username, key, stamp=stamp)
    finally:
        conn.close()


def _parse(text, default):
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return default - timedelta(seconds=STALE_SECONDS + 1)      # 讀不懂 ⇒ 當作很舊（可以接手）


def _purge(conn, now):
    cutoff = (now - timedelta(days=RETENTION_DAYS)).isoformat()
    conn.execute("DELETE FROM idempotency_keys WHERE created_at < ?", (cutoff,))


async def run(username, key, endpoint, req_hash, handler, status_code=200, abort_on_cancel=False):
    """端點的一行包裝：`return await idempotency.run(user["username"], key, "POST case_update:Q1", h, lambda: impl(...), 201)`。
    key 為 None ⇒ 直接 `await handler()`（行為與沒有這個機制時相同）；重播 ⇒ 回儲存的回應；否則執行並存回應。
    `handler` 的回傳值必須是可 JSON 序列化的（dict／list）。

    begin／finish／abort 是同步 SQLite（`BEGIN IMMEDIATE` 遇到別人握鎖會等到 busy timeout）⇒ 一律丟 threadpool，不卡事件迴圈。
    `abort_on_cancel=True`：處理被取消（用戶端斷線）時釋放這把 key——只給「所有 await 都在寫入之前」的處理函式用（取消只會在 await 點送達，
    所以取消發生時寫入一定還沒發生）；其餘維持保守：留 `in_progress` 等 stale 接手。"""
    call = await run_in_threadpool(begin, username, key, endpoint, req_hash)
    if call is None:
        return await handler()
    if call.replay is not None:
        return replay_response(call)
    try:
        result = await handler()
    except Exception:
        await run_in_threadpool(call.abort)
        raise
    except BaseException:                      # CancelledError 等
        if abort_on_cancel:
            call.abort()                       # 取消中不再 await：短短一次 SQLite 同步呼叫
        raise
    await run_in_threadpool(call.finish, status_code, result)
    return result


def run_sync(username, key, endpoint, req_hash, handler, status_code=200):
    """`run()` 的同步版（給 `def` 端點用；async 端點用 `run`）。"""
    call = begin(username, key, endpoint, req_hash)
    if call is None:
        return handler()
    if call.replay is not None:
        return replay_response(call)
    with call.guard():
        result = handler()
    call.finish(status_code, result)
    return result
