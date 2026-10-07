# -*- coding: utf-8 -*-
"""離線工具共用：把資料庫綁定到明確的檔案，而且**絕不建立空庫**。

[單位] tool:_dbbind    [層] 部署工具
[公開介面] bind, connect_path, require_file
[不變式] 路徑不存在 ⇒ SystemExit(2)，不呼叫 sqlite3.connect（它會在那個路徑悄悄建一個 0 byte 的檔）；
    給了 --db ⇒ 只動 db.DB_PATH（本行程），不碰 DEMO_DB_PATH。

為什麼（第 46 班）：離線工具沒給 --db 時走 db.get_db() ⇒ 在 <包>/backend/ 下建出空的 motrix_erp.db，
    暫存包（staging）因此多出一個空庫，之後被當成「正式機資料庫」帶走或讓 verify_package 誤判。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def require_file(path):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                        # noqa: BLE001
        pass
    if not path or not os.path.isfile(path):
        print("找不到資料庫檔：%s（不建立空檔；請用 --db 指到要讀的庫）" % (path or "（未指定）"), file=sys.stderr)
        raise SystemExit(2)
    return path


def bind(path=None):
    """綁定 db.DB_PATH（給了 path 才改）並確認檔案存在；回最後使用的路徑。"""
    parent = os.path.dirname(_HERE)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    import db
    if path:
        db.DB_PATH = path
    return require_file(db.DB_PATH)


def connect_path(path):
    """sqlite3 連到 path（Row 工廠）；檔案不存在 ⇒ 拒絕。"""
    import sqlite3
    conn = sqlite3.connect(require_file(path))
    conn.row_factory = sqlite3.Row
    return conn
