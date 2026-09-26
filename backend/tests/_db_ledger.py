"""測試用連線帳本：在 `sqlite3.connect` 這一層記「開了幾個、關了幾個」。

為什麼在這一層（稽核 ⑰ M-1）：只換 `db.get_db` 這個名字，`from db import get_db` 在 import 當下就綁了原函式
（helpers/settings.py、helpers/auth.py …），經它們開的連線帳本一個都看不到——豁免題照樣判 0。
`db.get_db`／`db_conn` 最後都呼叫 `sqlite3.connect`（以模組屬性取用），換掉它就看得到所有經 db 開的連線。

用法：
    book = install(monkeypatch)          # {"open": n, "closed": n}
    book["open"] = book["closed"] = 0    # 歸零後再打端點
    explode_in(monkeypatch, path_suffix) # 讓「呼叫堆疊經過某個原始檔」的查詢丟例外（驗中途失敗也關連線）
"""
import inspect
import sqlite3


class _Boom(Exception):
    pass


def _norm(path):
    return str(path).replace("\\", "/").lower()


def install(monkeypatch):
    book = {"open": 0, "closed": 0, "stacks": []}
    real = sqlite3.connect

    class _Tracked(sqlite3.Connection):
        def close(self):
            if not getattr(self, "_ledger_closed", False):
                self._ledger_closed = True
                book["closed"] += 1
            return super().close()

    def _connect(*a, **kw):
        kw.setdefault("factory", _Tracked)
        conn = real(*a, **kw)
        if isinstance(conn, _Tracked):
            book["open"] += 1
            book["stacks"].append({_norm(f.filename) for f in inspect.stack(0)[1:]})
        return conn

    monkeypatch.setattr(sqlite3, "connect", _connect)
    book["_class"] = _Tracked
    return book


def reset(book):
    book["open"] = book["closed"] = 0
    book["stacks"] = []
    book.pop("exploded", None)


def opened_from(book, source_file):
    """歸零之後，呼叫堆疊經過 `source_file`（端點所在的原始檔）的連線數——端點「自己」開的，
    含它呼叫的 helper 開的；中介層（驗 token、活動紀錄）開的不算。"""
    target = _norm(source_file)
    return sum(1 for st in book["stacks"] if target in st)


def explode_in(monkeypatch, book, source_file):
    """呼叫堆疊裡有 `source_file`（端點所在的原始檔）的 execute 一律丟例外；中介層（驗 token）不受影響。"""
    real_execute = sqlite3.Connection.execute
    target = str(source_file).replace("\\", "/").lower()

    def _execute(self, *a, **kw):
        if any(f.filename.replace("\\", "/").lower() == target for f in inspect.stack(0)[1:]):
            book["exploded"] = book.get("exploded", 0) + 1
            raise _Boom("查詢中途爆炸")
        return real_execute(self, *a, **kw)

    monkeypatch.setattr(book["_class"], "execute", _execute)
