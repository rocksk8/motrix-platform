# -*- coding: utf-8 -*-
"""L1 寫入交易：寫鎖、區塊保證、「拿鎖之後讀過」的觀測（2026-09-25 自 helpers/quotations.py 下沉）。

[單位] plat:txn    [層] L0    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] begin_write, lock_state, read_under_lock, safe_close, strict_db_guards, watch_reads, write_txn
[不變式] 「讀 → 改 → 整包寫回」的路徑，讀之前先 begin_write()；已在交易內的呼叫端行為不變；不認識任何業務表
[契約題] tests/platform/test_core_events.py, tests/test_begin_only_via_begin_write_2026_09_25.py
[注意] 拿著寫鎖時不可以 await 慢動作；strict_db_guards() 預設不 raise（只有 MOTRIX_STRICT_DB_GUARDS=1 才 raise）

下沉原因：16 支 router 為了交易鎖而 import 案件 helper ⇒ 所有模組經由它依賴「案件」
（DEPENDENCY-MAP §0-4）。這裡不認識任何業務表：要觀測「拿鎖之後讀過某欄位」的模組
自己用 `watch_reads()` 登記判斷式（例：案件登記 quotations.data_json）。
"""
import os
import threading

#: begin_write 開的寫交易：id(conn) -> {"conn": conn, "read": {watch_name: bool}}
#: ⚠️ sqlite3.Connection 不能掛屬性、也不支援弱參照 ⇒ 以 id 為鍵並保留連線本身比對（避免 id 重用誤判），
#:    每次 begin_write 時清掉已關閉的連線。
_WRITE_TXNS = {}

#: watch_name -> predicate(sql) ；由模組在匯入時登記
_READ_WATCHERS = {}


def watch_reads(name: str, predicate) -> None:
    """登記「拿鎖之後讀過」的判斷式；`read_under_lock(conn, name)` 查結果。"""
    _READ_WATCHERS[name] = predicate


def strict_db_guards() -> bool:
    """資料庫結構守門違規時要不要 raise。

    🔴 預設**不** raise（記 ERROR＋堆疊、照寫）：產品會賣給客戶自架，不可以用安裝路徑猜「這是不是正式機」——
    客戶裝在別處就會被當成開發環境而 raise，直接擋住客戶存檔（2026-09-25 裁示）。
    只有明確設了 MOTRIX_STRICT_DB_GUARDS=1 才 raise：conftest 在測試啟動時設（漏網之魚在題目裡就紅）；
    開發機要嚴格可自行設。每次呼叫才讀，測試可以用 monkeypatch 切換。"""
    return os.environ.get("MOTRIX_STRICT_DB_GUARDS") == "1"


def safe_close(conn) -> None:
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass


def _prune_write_txns():
    for k, st in list(_WRITE_TXNS.items()):
        try:
            st["conn"].total_changes          # 已關閉 ⇒ ProgrammingError
        except Exception:                      # noqa: BLE001
            _WRITE_TXNS.pop(k, None)


def begin_write(conn) -> bool:
    """讀資料之前先拿寫鎖（還不在交易裡才 `BEGIN IMMEDIATE`）；回傳這裡有沒有開交易。

    🔴 2026-09-25 lost update 稽核：整包寫回的路徑不比對 updated_at。
    sqlite3 不為 SELECT 開交易 ⇒ 交易外讀到的是快照，讀與寫之間別人 commit 的修改會被整包蓋回。
    ⇒ 凡是「讀 → 改 → 整包寫回」的路徑，讀之前都要先呼叫這裡；已在交易裡的呼叫端行為不變。
    ⚠️ 拿著寫鎖時不可以 await 慢動作（例如寫上傳檔）：那段時間所有寫入都會被卡住 ⇒ 先做完慢動作，
    再拿鎖、重讀、只套用自己的那一筆修改。"""
    if conn.in_transaction:
        return False
    conn.execute("BEGIN IMMEDIATE")
    _prune_write_txns()
    st = {"conn": conn, "read": {name: False for name in _READ_WATCHERS},
          "thread": threading.get_ident()}   # core.events 用：同一條執行緒還開著寫交易時不可以發佈事件
    _WRITE_TXNS[id(conn)] = st

    def _trace(sql, _st=st):
        for name, pred in _READ_WATCHERS.items():
            if not _st["read"].get(name) and pred(sql):
                _st["read"][name] = True
    conn.set_trace_callback(_trace)
    return True


def lock_state(conn):
    """回傳 (是否在 begin_write 開的寫交易內, 狀態 dict 或 None)。"""
    st = _WRITE_TXNS.get(id(conn))
    mine = bool(st and st["conn"] is conn)
    return (mine and conn.in_transaction), (st if mine else None)


def read_under_lock(conn, name: str) -> bool:
    ok, st = lock_state(conn)
    return bool(ok and st["read"].get(name))


class write_txn:
    """`with write_txn(conn): ...` ＝ begin_write ＋「區塊內任何例外 ⇒ rollback 並關閉連線」。

    🔴 2026-09-25（bf 3b3504ba 抓到的那一型）：拿了寫鎖之後的路徑丟例外（HTTPException 或任何沒預期的錯）
    而沒關連線 ⇒ 寫鎖留到連線被回收，其他人的寫入卡 30 秒後 500「database is locked」。
    逐處在 raise 前手寫 conn.close() 會漏（被呼叫的函式丟出來的例外看不到）⇒ 用區塊保證。
    正常離開區塊時什麼都不做：commit／close 照舊由呼叫端決定（同一條連線之後可能還要用）。"""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        begin_write(self.conn)
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            # ⚠️ 收尾絕不可以蓋掉原本的例外：很多路徑在 raise 4xx 之前已經自己 conn.close()，
            #    對已關閉的連線讀 in_transaction／rollback 會丟 ProgrammingError（2026-09-25 回歸實測 17 題）。
            try:
                self.conn.rollback()
            except Exception:         # noqa: BLE001  已關閉／沒有交易 ⇒ 沒有鎖要放
                pass
            try:
                self.conn.close()     # 已關過也無妨
            except Exception:         # noqa: BLE001
                pass
        return False
