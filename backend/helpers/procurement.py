"""採購前置時間與採購建議狀態的判定（2026-09-21，第 3 輪）。

**這裡全部是純函式，不碰 DB、不碰 request。** 抽出來的理由不是整潔：
`routers/suppliers.py`／`parts.py`／`inventory.py` 三邊都要用同一套判定，
**讓三邊被迫走同一支函式**，而不是各自寫一份再規定它們寫一樣。
三邊各自都對、合起來錯，是最難發現的一種。

## 這一支在防的那個錯

**前置時間未知時，`eta` 必須是 `None`——不是今天，也不是 0。**

`0` 跟 `None` 在畫面上都會顯示成「今天到貨」，而那是一個**看起來很正常的錯誤答案**：
採購人員會照著它去排程，沒有任何東西會提醒他那是猜的。
架構地圖 §6.6 當初刻意不做 ETA，理由正是「系統從未追蹤前置時間」；
現在補了欄位，但**沒填的那些仍然是未知**，不可以因為欄位存在就假裝算得出來。

`0` 是有意義的值（現貨、當天可出），所以它跟「未知」必須是兩個不同的東西。
⚠️ 這代表**任何地方都不可以用真假值判斷前置時間**（`if lead_time:`），
因為 `0` 是假值——一律用 `is None`。
"""
from datetime import date, timedelta

from fastapi import HTTPException

# 採購循環的三個狀態，**順序就是它們必須被經歷的順序**。
STATUS_SUGGESTED = "suggested"   # 建議採購（預設）
STATUS_ORDERED   = "ordered"     # 已下單，東西在路上
STATUS_RECEIVED  = "received"    # 已到貨，這一輪結束

STATUS_SEQUENCE = (STATUS_SUGGESTED, STATUS_ORDERED, STATUS_RECEIVED)


def today():
    """今天（本地日期）。**這支存在的唯一理由，是讓測試換得掉它。**

    ⚠️ 它**不是**在修任何 bug。`date.today()` 取的本來就是本地日期，
    台灣的日界線沒有算錯過。A 於 2026-09-21 更正了原本的說法，**而我自己也複驗過**
    （開發單原文是「請 B 確認呼叫端取的是本地日期」，那是派給我的，不能只轉述）：
      本機與 UTC 位移 +8；拿本地 03:00 當對照（那個時刻兩種解讀差一天，
      現在這個時刻兩者同日、比了證明不了任何事）；
      `date.today() == datetime.fromtimestamp(time.time()).date()` 為真 ⇒ 走本地。
    純粹是因為：`compute_eta(lead, today)` 的 `today` 已經是參數，但**呼叫端**
    仍然直接叫 `date.today()`，於是端點回傳的 `eta` 沒辦法用固定日期驗，
    驗收條件 4 只驗得到純函式那一半。

    ⚠️ **要換掉它必須 monkeypatch `helpers.procurement.today`，
    而呼叫端必須寫成 `procurement.today()` 而不是 `from ... import today`** ——
    後者會在 import 當下把函式物件複製進呼叫端的命名空間，換不掉。
    這跟 `_PUBKEY_DEV`／`LICENSE_PATH` 是同一件事（見 `helpers/licensing.py` 開頭）。
    """
    return date.today()


def clean_lead_time(value):
    """驗前置時間。`None` 原樣放行（＝未知），負數擋掉。

    **不要把 `None` 轉成 0**。呼叫端若想「沒填就當 0」，那個決定要寫在呼叫端
    而且要有理由——在這裡偷偷轉掉的話，整個系統就再也分不出「現貨」與「不知道」。
    """
    if value is None:
        return None
    try:
        days = int(value)
    except (TypeError, ValueError):
        raise HTTPException(422, "前置時間必須是整數天數；未知請留空")
    if days < 0:
        raise HTTPException(422, "前置時間不可為負數；未知請留空，不要填 0")
    return days


def resolve_lead_time(part_lead_time, supplier_lead_time):
    """解析前置時間：**料號層級覆寫供應商層級**，兩邊都沒有就是未知。

    為什麼料號可以覆寫供應商：同一家供應商的現貨品項與訂製品項差很多，
    供應商層級只是一個合理的預設值。

    ⚠️ **這裡一定要用 `is not None`，不可以用 `or`。**
    `0` 是假值，寫成 `part_lead_time or supplier_lead_time` 的話，
    一個「現貨、當天可出」（0 天）的料號會**安靜地掉到供應商的天數去**，
    而且兩個都是合法數字，畫面上看不出任何異常。
    """
    if part_lead_time is not None:
        return part_lead_time
    if supplier_lead_time is not None:
        return supplier_lead_time
    return None


def compute_eta(lead_time_days, today):
    """預計到貨日（ISO 日期字串）。**前置時間未知 → `None`。**

    `today` 是參數不是 `date.today()`：算日期的邏輯要能用固定日期驗，
    否則測試只能拿 `date.today()` 當預期值——那是拿同一個式子驗它自己。
    """
    if lead_time_days is None:
        return None
    return (today + timedelta(days=lead_time_days)).isoformat()


def effective_status(stored_status, below_threshold):
    """這個料號**現在實際上**處在採購循環的哪一步。

    ⚠️ **狀態表不參與清單的過濾，這支函式也不做過濾。**
    清單永遠由庫存算出來；狀態只是附註。
    旗標是人設的、會過期；真實狀態是算出來的、會自己更新——
    **旗標不可以蓋過真實狀態**（協定 §5b）。

    `received` ＋ 庫存仍低於水位 ＝ **新的一輪**：
    上一輪的貨收到了，庫存卻還是不夠（叫少了），那本來就該再建議一次。
    若照「`received` 就永久不再出現」做，這個料號會從此安靜地消失在採購清單上，
    而且不會有任何訊息說明為什麼。
    """
    if not stored_status:
        return STATUS_SUGGESTED
    if stored_status == STATUS_RECEIVED and below_threshold:
        return STATUS_SUGGESTED
    if stored_status not in STATUS_SEQUENCE:
        # 沒見過的值：當成還沒處理，而不是當成已完成。
        # 猜「已完成」會讓一筆該採購的東西消失；猜「未處理」最壞只是多顯示一列。
        return STATUS_SUGGESTED
    return stored_status


def effective_cycle(stored_row, below_threshold):
    """把資料表那一列翻譯成「**這一輪**實際的樣子」。

    回 `{status, ordered_at, ordered_by, received_at, received_by, new_cycle}`。

    ⚠️ **這支存在的理由，是我第一版真的寫錯過。**
    第一版只有 `effective_status()`：清單那邊算出 `status="suggested"`（新的一輪），
    卻把**上一輪的** `ordered_at` 原樣回傳——畫面上就變成
    「這一輪還沒下單，但下單時間是 3 天前」。狀態欄對、時間欄對、合起來是錯的。

    新的一輪就是新的一輪：上一輪的時間戳**不屬於它**，一律清空。
    清單與狀態轉移端點都走這一支，兩邊就不可能各算各的。
    """
    stored = dict(stored_row or {})
    status = effective_status(stored.get("status"), below_threshold)
    new_cycle = stored.get("status") == STATUS_RECEIVED and status == STATUS_SUGGESTED
    if new_cycle:
        return {"status": status, "ordered_at": "", "ordered_by": "",
                "received_at": "", "received_by": "", "new_cycle": True}
    return {
        "status":      status,
        "ordered_at":  stored.get("ordered_at") or "",
        "ordered_by":  stored.get("ordered_by") or "",
        "received_at": stored.get("received_at") or "",
        "received_by": stored.get("received_by") or "",
        "new_cycle":   False,
    }


def validate_transition(current, target):
    """狀態只能**往前走一步**。跳階要被拒絕，不是靜默接受。

    `suggested → received` 被擋住的理由不是潔癖：那代表「沒有人按過下單」，
    而下單日是後面追料、對帳、算前置時間準不準的唯一依據。
    靜默接受的話，那一格會永遠是空的，而且沒有人知道它為什麼是空的。
    """
    if target not in STATUS_SEQUENCE:
        raise HTTPException(
            422, f"狀態只能是 {'／'.join(STATUS_SEQUENCE)}，收到的是 {target!r}")
    here = STATUS_SEQUENCE.index(current)
    there = STATUS_SEQUENCE.index(target)
    if there == here:
        raise HTTPException(409, f"這筆採購建議已經是「{target}」了")
    if there != here + 1:
        raise HTTPException(
            409,
            f"不可以從「{current}」直接跳到「{target}」，"
            f"必須先經過「{STATUS_SEQUENCE[here + 1]}」"
        )
    return target
