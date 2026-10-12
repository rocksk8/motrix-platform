# -*- coding: utf-8 -*-
"""完工單「從報價單帶入項目」的純函式（設計：docs/platform/plans/COMPLETION-NOTE-QUOTE-ITEMS-T56.md）。

[單位] mod:case/completion_sync    [層] L2（案件模組內部）
[不變式] ①只讀不寫；②**回給前端的品項鍵＝程式明列的允許清單 ∩ 非金額欄位**（`ITEM_MONEY_KEYS` 結構性排除；以後報價單新增任何欄位預設都不出）；
    ③累計（已完工數）每次即時算、不快取不存單據；④指紋只含非金額欄位，金額變動不觸發也不洩漏；⑤完工單不存任何金額。
"""
import hashlib
import json
import math

from helpers.financial_mask import ITEM_MONEY_KEYS

#: 程式明列的允許清單（不是目錄的「公開」類別——單價對客戶是公開卻仍是金額）。新增欄位要在這裡明列，並確認不是金額。
ALLOWED_ITEM_KEYS = ("id", "type", "description", "brand", "qty", "unit")
#: 實際輸出的鍵＝允許清單 ∩ 非金額（即使有人把金額鍵加進允許清單也出不去）
SAFE_ITEM_KEYS = tuple(k for k in ALLOWED_ITEM_KEYS if k not in ITEM_MONEY_KEYS)

#: 報價單狀態閘：只有「已送出」（含已成案／已結案，那是 deal_tag）可帶入
GATE_EDITING = ("草稿", "待審核", "簽核中")
GATE_DEAD = ("已取消", "已拒絕")
#: 計入「已完工數」的完工單狀態（比照出貨單 RESERVED／SHIPPED：草稿與退回不計）
COUNTED_NOTE_STATUSES = ("待審核", "簽核中", "已核准")
COUNTED_ITEM_STATUSES = ("完成", "部分完成")
ITEM_ID_MAX = 64


class SourceUnavailable(Exception):
    """報價單『計入哪些品項』判斷失敗（擇一方案的計入函式存在卻丟例外）：不可降級為全部品項，否則會把客戶沒選的方案帶進完工單。"""


def num(v) -> float:
    """數量解析：非數字、非有限、負數 ⇒ 0。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f if math.isfinite(f) and f > 0 else 0.0


def item_id(it) -> str:
    """報價品項的字串編號；沒有（舊資料）或超長 ⇒ ''（無法追蹤）。"""
    v = (it or {}).get("id")
    if isinstance(v, bool) or v is None:
        return ""
    s = str(v).strip()
    return s if 0 < len(s) <= ITEM_ID_MAX else ""


def gate_message(status: str):
    """報價單狀態閘：可帶入回 None，否則回白話原因（呼叫端用 409）。"""
    if status == "已送出":
        return None
    if status in GATE_EDITING:
        return "報價單還在編輯或簽核中，項目可能還會變，請等報價送出後再帶入"
    if status in GATE_DEAD:
        return "這張報價單已取消或被拒絕，不能帶入項目"
    return "報價單目前的狀態不能帶入項目"


def source_items(data: dict, *, include_headers: bool = True) -> list:
    """報價單目前計入的品項（只留允許清單內的非金額欄位）。M3 之後 `profit_guard.counted_items` 存在時改用它（擇一單只取選定）；之前＝全部品項。"""
    items = (data or {}).get("items") or []
    from modules.case import profit_guard as _pg
    fn = getattr(_pg, "counted_items", None)                               # 函式不存在（M3 前）⇒ 全部品項；存在卻失敗 ⇒ 關閉（不帶任何東西）
    if callable(fn):
        try:
            items = fn(data) or []
        except Exception as e:                                             # noqa: BLE001
            raise SourceUnavailable(str(e)) from e
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        is_header = it.get("type") == "header"
        if is_header and not include_headers:
            continue
        row = {k: it.get(k) for k in SAFE_ITEM_KEYS if k in it}
        row["type"] = "header" if is_header else ""
        row["id"] = item_id(it)
        row["description"] = str(it.get("description") or "")
        if not is_header:
            row["brand"] = str(it.get("brand") or "")
            row["qty"] = num(it.get("qty"))
            row["unit"] = str(it.get("unit") or "")
        else:
            for k in ("brand", "qty", "unit"):
                row.pop(k, None)
        out.append(row)
    return out


def unselected_alt_groups(data: dict) -> list:
    """擇一單（`totalsByAlt` 開啟）中客戶尚未選定的組別名；非擇一單／M3 前 ⇒ []。與 `profit_guard.counted_items` 同一個口徑
    （選定＝`altPicks[組]` 指到該組內存在的品項）。判斷失敗 ⇒ SourceUnavailable（失敗關閉）。"""
    try:
        from modules.case import profit_guard as _pg
        active, groups_fn = getattr(_pg, "alt_active", None), getattr(_pg, "alt_groups", None)
        if not (callable(active) and callable(groups_fn) and active(data)):
            return []
        picks = (data or {}).get("altPicks")
        # 與 profit_guard.counted_items 同一個正規化：組名去頭尾空白、值轉字串、空值不算選定
        picks = {str(k).strip(): str(v) for k, v in picks.items() if v not in (None, "")} if isinstance(picks, dict) else {}
        out = []
        for g, its in groups_fn(data).items():
            pick = picks.get(g)
            if pick is None or not any(str(i.get("id")) == pick for i in its):
                out.append(g)
        return out
    except Exception as e:                                                 # noqa: BLE001
        raise SourceUnavailable(str(e)) from e


def fingerprint(items: list) -> str:
    """來源集合的非金額指紋（id／type／description／brand／qty／unit；品牌會變成帶入的品名，所以算）。金額變動不改指紋。"""
    canon = [[it.get("id") or "", it.get("type") or "", it.get("description") or "", it.get("brand") or "",
              it.get("qty") if it.get("type") != "header" else 0, it.get("unit") or ""] for it in items]
    return hashlib.sha256(json.dumps(canon, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:32]


def completed_qty_by_item(conn, quote_no: str, exclude_note: str = "") -> dict:
    """{報價品項編號: 已完工數}：其他完工單（待審核／簽核中／已核准）中同一 quoteItemId 且狀態為完成／部分完成的數量合計。
    同一編號出現多列全部相加；header 忽略；非數字／負數／未施作計 0。"""
    marks = ",".join("?" * len(COUNTED_NOTE_STATUSES))
    rows = conn.execute("SELECT note_no, items_json FROM completion_notes WHERE quote_no=? AND status IN (%s)" % marks,
                        (quote_no,) + COUNTED_NOTE_STATUSES).fetchall()
    out = {}
    for r in rows:
        if exclude_note and r["note_no"] == exclude_note:
            continue
        try:
            items = json.loads(r["items_json"] or "[]")
        except ValueError:
            continue
        for it in items:
            if not isinstance(it, dict) or it.get("type") == "header":
                continue
            qid = it.get("quoteItemId")
            if not isinstance(qid, str) or not qid or it.get("status") not in COUNTED_ITEM_STATUSES:
                continue
            out[qid] = out.get(qid, 0.0) + num(it.get("qty"))
    return out


def with_progress(items: list, done: dict) -> list:
    """每個非標題品項加 alreadyCompleted／remaining；無編號的舊品項 `tracked=False`（不算入累計）。"""
    out = []
    for it in items:
        row = dict(it)
        if it.get("type") != "header":
            qid = it.get("id") or ""
            row["tracked"] = bool(qid)
            row["alreadyCompleted"] = done.get(qid, 0.0) if qid else 0.0
            row["remaining"] = max(0.0, (it.get("qty") or 0.0) - row["alreadyCompleted"]) if qid else it.get("qty") or 0.0
        out.append(row)
    return out


def over_quota(items: list, source: list, done: dict) -> list:
    """本張完工單各來源品項「本張＋他單」超過報價數量者 ⇒ [(說明, 超量)]；供『擋下』政策用。"""
    qty = {s["id"]: s.get("qty") or 0.0 for s in source if s.get("type") != "header" and s.get("id")}
    mine = {}
    for it in items or []:
        if not isinstance(it, dict) or it.get("type") == "header":
            continue
        qid = it.get("quoteItemId")
        if isinstance(qid, str) and qid in qty and it.get("status") in COUNTED_ITEM_STATUSES:
            mine[qid] = mine.get(qid, 0.0) + num(it.get("qty"))
    out = []
    for qid, m in mine.items():
        extra = m + done.get(qid, 0.0) - qty[qid]
        if extra > 1e-9:
            name = next((s["description"] for s in source if s.get("id") == qid), qid)
            out.append((name, extra))
    return out
