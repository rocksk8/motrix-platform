# -*- coding: utf-8 -*-
"""一條龍 P3：案件設備頁的「出貨帶入」預填與序號歷史（旗標 `onepipe.ship_device_warranty`；決策 D4＝A）。

[單位] case:device_warranty    [層] L2    [穩定度] 實驗
[公開介面] prefill, history, start_basis, SOURCES
[決策] D4＝A：保固起始日預設取**出貨日**，沒有出貨單（直送）時依序退到到貨日→完工日；**只預填、由人確認後儲存，不自動寫入設備**；
       設定 `onepipe.warranty_start_basis`＝1 可改成完工日優先（完工日→出貨日→到貨日）。
[不變式] 唯讀（不寫任何資料、不 commit）；庫存只經 registry 的 `stock.shipped_serials`／`stock.serial_history`（IP-120／IP-121），本檔不 import supply；
         M03 不在 ⇒ `available=False`、空清單。回應沒有任何金額欄位。案件可見性（`require_case`）由呼叫端先檢查。
         `history` 只回**本案**的案件編號；其他案件的異動只留「其他案件」四個字（連同單號、原因一併遮掉）——序號可能曾經在別的客戶案件。
[預設（決策紀錄沒寫、本檔自訂）] 到貨日＝這個案件已核准材料申請中最早的到貨日；完工日＝這個案件完工單上最晚的完工日；
         已經登載成設備的序號（`caseRecord.devices[].sn`）不再出現在預填清單；保固月數不預填（商業判斷，由人填）。
"""
import json

from core import registry

SOURCES = {"ship": "出貨日", "arrival": "到貨日", "completion": "完工日"}


def start_basis(conn=None) -> int:
    """`onepipe.warranty_start_basis`：0＝出貨日優先、1＝完工日優先；讀不到 ⇒ 0。"""
    try:
        from helpers import settings_registry as SR
        return 1 if int(SR.get("onepipe", "warranty_start_basis", conn=conn)) == 1 else 0
    except Exception:                                                            # noqa: BLE001
        return 0


def _arrival_date(conn, quote_no) -> str:
    r = conn.execute("SELECT MIN(received_on) FROM case_material_approvals WHERE quote_no=? AND status='已核准' AND COALESCE(received_on,'')<>''", (quote_no,)).fetchone()
    return ((r[0] if r else "") or "")[:10]


def _completion_date(conn, quote_no) -> str:
    r = conn.execute("SELECT MAX(completion_date) FROM completion_notes WHERE quote_no=? AND COALESCE(completion_date,'')<>''", (quote_no,)).fetchone()
    return ((r[0] if r else "") or "")[:10]


def _devices(q) -> list:
    try:
        d = json.loads(q["data_json"] or "{}") or {}
    except (TypeError, ValueError):
        return []
    return [x for x in ((d.get("caseRecord") or {}).get("devices") or []) if isinstance(x, dict)]


def pick_start(basis, ship, arrival, completion):
    """⇒ `(日期, 來源鍵)`；都沒有 ⇒ `("", "")`。"""
    order = ((completion, "completion"), (ship, "ship"), (arrival, "arrival")) if basis == 1 else ((ship, "ship"), (arrival, "arrival"), (completion, "completion"))
    for v, k in order:
        if v:
            return v, k
    return "", ""


def prefill(conn, quote_no, q) -> dict:
    """⇒ `{"available", "basis", "arrivalDate", "completionDate", "missingStart", "serials": [{"partNo", "name", "serialNo", "mac", "shipDate", "noteNo", "suggestedStart", "startSource"}]}`。
    `serials`＝這個案件已出貨、還沒登載成設備、也不在目前設備清單裡的序號；`missingStart`＝設備清單中有序號但沒填保固起始日的台數（這類設備不會收到到期通知）。"""
    devices = _devices(q)
    registered = {str(d.get("sn") or "").strip().lower() for d in devices if str(d.get("sn") or "").strip()}
    missing = sum(1 for d in devices if (d.get("sn") or d.get("mac") or d.get("name")) and not str(d.get("warrantyStart") or "").strip())
    basis = start_basis(conn)
    arrival, completion = _arrival_date(conn, quote_no), _completion_date(conn, quote_no)
    out = {"available": False, "basis": basis, "arrivalDate": arrival, "completionDate": completion, "missingStart": missing, "serials": []}
    fn = registry.single_provider("stock.shipped_serials")
    if fn is None:
        return out
    res = fn(conn, quote_no) or {}
    out["available"] = True
    for s in res.get("serials") or []:
        if str(s.get("serialNo") or "").strip().lower() in registered:
            continue
        start, src = pick_start(basis, s.get("shipDate") or "", arrival, completion)
        out["serials"].append({**s, "suggestedStart": start, "startSource": SOURCES.get(src, "")})
    return out


def history(conn, quote_no, q, serial_no) -> dict:
    """⇒ `{"serialNo", "available", "since", "events": [{"event", "fromStatus", "toStatus", "quoteNo"（本案編號或「其他案件」）, "ref", "reason", "actor", "at"}]}`。
    序號必須和這個案件有**庫存關係**（庫存裡綁這個案件的已出貨／已安裝序號，或它的異動紀錄帶有本案編號）——案件設備清單裡自己打的序號不算，
    不讓人拿案件頁當全庫序號的查詢入口。不是本案的異動（含沒有案件編號的）一律遮掉 `ref`／`reason`／`actor`；別案編號只標「其他案件」（由 `stock.serial_history` 提供者依 `quote_no` 處理）。"""
    sn = str(serial_no or "").strip()
    out = {"serialNo": sn, "available": False, "since": "", "events": []}
    fn = registry.single_provider("stock.serial_history")
    if fn is None or not sn:
        return out
    out["available"] = True
    for e in fn(conn, "", sn, quote_no=quote_no) or []:
        if (e.get("quoteNo") or "") != quote_no:                                  # 再遮一次（提供者已遮；這裡不信任對方，空編號的自由文字也不外流）
            e = {**e, "quoteNo": "其他案件" if e.get("quoteNo") else "", "ref": "", "reason": "", "actor": ""}
        out["events"].append(e)
    out["since"] = out["events"][0]["at"] if out["events"] else ""
    return out
