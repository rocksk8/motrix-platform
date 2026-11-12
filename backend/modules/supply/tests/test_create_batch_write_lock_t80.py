"""T80 R5：create_batch 的『序號重複檢查』與 INSERT 之間要有寫鎖（先 SELECT 再迴圈 INSERT 是 TOCTOU）。

併發的另一個進貨剛好先寫入同序號 ⇒ 這邊的 INSERT 丟 IntegrityError，原本沒有 rollback／close，寫鎖留到 GC。
觀測點：重複序號檢查那一刻，這條連線是不是已經在寫交易內（`in_transaction`）。
另驗：序號撞到時（IntegrityError）鎖會被放掉。
"""
import gc
import sqlite3

import pytest

import db
from modules.supply.api import inventory
from tests.test_stock_batch_payment_2026_09_01 import _auth, _login


class _Spy:
    """轉發給真連線，記下每一句 SQL 送出當下是否已在交易內。"""

    def __init__(self, conn, log):
        self._c, self._log = conn, log

    def execute(self, sql, *a, **k):
        self._log.append((" ".join(sql.split())[:48], self._c.in_transaction))
        return self._c.execute(sql, *a, **k)

    def __getattr__(self, name):
        return getattr(self._c, name)


def _setup(client, make_user):
    u, p = make_user(username="t80_admin", role="superadmin")
    token = _login(client, u, p)
    r = client.post("/api/parts", headers=_auth(token), json={"part_no": "T80-P", "name": "t80", "category": "其他", "cost": 1})
    assert r.status_code == 201, r.text
    return token


def test_dup_check_runs_inside_write_transaction(client, make_user, monkeypatch):
    token = _setup(client, make_user)
    log = []
    real = inventory.get_db
    monkeypatch.setattr(inventory, "get_db", lambda: _Spy(real(), log))
    r = client.post("/api/inventory/batches", headers=_auth(token),
                    json={"part_no": "T80-P", "serials": [{"serial_no": "T80-SN1"}], "cost": 1})
    assert r.status_code == 201, r.text
    dup = [x for x in log if x[0].startswith("SELECT serial_no FROM stock_items")]
    assert dup, log
    assert dup[0][1] is True, "序號重複檢查時還沒拿寫鎖（TOCTOU）：%r" % (log,)


def test_integrity_error_mid_insert_releases_lock(client, make_user, monkeypatch):
    token = _setup(client, make_user)
    real = inventory.get_db
    # 模擬併發：重複檢查看不到、但 INSERT 撞 UNIQUE ⇒ 讓檢查那句回空
    class _NoDup(_Spy):
        def execute(self, sql, *a, **k):
            if "serial_no IN" in sql:
                class _R:
                    def fetchall(self_):
                        return []
                self._c.execute("SELECT 1")
                return _R()
            return self._c.execute(sql, *a, **k)
    c0 = db.get_db()
    c0.execute("INSERT INTO stock_items (part_no, serial_no, status, batch_no, cost, created_by, created_at, updated_at) "
               "VALUES ('T80-P','T80-SN2','in_stock','PO-X',1,'t','n','n')")
    c0.commit()
    c0.close()
    monkeypatch.setattr(inventory, "get_db", lambda: _NoDup(real(), []))
    with pytest.raises(sqlite3.IntegrityError):          # 既有行為：裸 IntegrityError 往上拋（TestClient 預設把伺服器例外丟回來）
        client.post("/api/inventory/batches", headers=_auth(token),
                    json={"part_no": "T80-P", "serials": [{"serial_no": "T80-SN2"}], "cost": 1})
    gc.disable()                                          # 排除『剛好被 GC 回收』：鎖必須是 write_txn 放的
    try:
        _assert_lock_free()
    finally:
        gc.enable()


def _assert_lock_free():
    c = sqlite3.connect(db.DB_PATH, timeout=0.4)
    try:
        c.execute("INSERT INTO stock_batches (batch_no, part_no, created_at, updated_at) VALUES ('T80-OK','T80-P','n','n')")
        c.commit()
    finally:
        c.close()
