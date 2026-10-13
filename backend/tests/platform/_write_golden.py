# -*- coding: utf-8 -*-
"""寫入路由回應鍵集金標的骨架（U0b-T2/T3）。不是測試檔（底線開頭）。

只提供機制，不含任何實際金標案例（案例逐批補，豁免清單只准縮小）：
- `record_write`：以最小合法 payload 打一條寫入路由，**斷言狀態碼落在預期類別**（預設 2xx）——
  payload 不合法時 4xx 的錯誤鍵集若被記成基準，之後永遠『一致』＝假綠燈，所以這裡直接丟 GoldenError。
- `key_delta`：基準與現況的鍵差異，分『消失』與『新增』兩個方向。
- `uncovered`：盤點中的寫入路由，既不在案例也不在豁免清單者（必須為空）。
- 非決定性欄位（時間戳、自增 id、亂數）只比鍵名不比值——`key_paths` 本來就只取鍵，所以天然成立。
"""
from tests.platform._response_keys import INTERNAL, key_paths


class GoldenError(AssertionError):
    pass


def record_write(client, headers, method, url, body=None, expect=(2,)):
    """回 {"s": 狀態碼, "k": [鍵路徑]}；狀態碼類別不在 expect 或回應非 JSON ⇒ GoldenError。"""
    r = client.request(method.upper(), url, headers=headers, json=body)
    if r.status_code // 100 not in expect:
        raise GoldenError("%s %s 狀態 %s 不在預期類別 %s（payload 不合法？）：%s"
                          % (method, url, r.status_code, expect, r.text[:200]))
    try:
        data = r.json()
    except ValueError as e:
        raise GoldenError("%s %s 回應不是 JSON" % (method, url)) from e
    return {"s": r.status_code, "k": key_paths(data)}


def key_delta(base: dict, now: dict) -> dict:
    """{'removed': [...], 'added': [...]}（鍵路徑）；基準或現況為空鍵集也要回報，不吞。"""
    b, n = set(base.get("k", ())), set(now.get("k", ()))
    return {"removed": sorted(b - n), "added": sorted(n - b)}


def leaked(rec: dict) -> list:
    return [k for k in rec.get("k", []) if k.split(".")[-1].replace("[]", "") in INTERNAL]


def uncovered(inventory_endpoints: dict, case_keys, waivers) -> list:
    """盤點裡 /api/ 的寫入路由，未被案例涵蓋也未豁免者。"""
    have = set(case_keys) | set(waivers)
    return sorted(k for k, v in inventory_endpoints.items() if v["w"] and k.split(" ", 1)[1].startswith("/api/") and k not in have)
