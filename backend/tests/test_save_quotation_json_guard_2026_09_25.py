"""save_quotation_json 的結構守門：讀 data_json 之前沒先 begin_write ⇒ 紅（lost update 稽核後開啟，2026-09-25）。

放行條件：這條連線的寫交易是 begin_write 開的，而且拿鎖之後讀過 quotations.data_json。
違規時：預設記 ERROR＋堆疊並照寫（產品會賣給客戶自架，不可以用安裝路徑猜正式機而擋住客戶存檔）；
設了 MOTRIX_STRICT_DB_GUARDS=1 才 raise（conftest 在測試啟動時設）。
"""
import json
import logging

import pytest

import helpers.quotations as hq
from tests.test_case_money_mask_2026_09_24 import NO, _seed


@pytest.fixture()
def strict(monkeypatch):
    monkeypatch.setenv("MOTRIX_STRICT_DB_GUARDS", "1")


def _read(conn):
    return json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()[0])


def test_outside_any_transaction_is_refused(client, strict):
    import db
    _seed(assigned=[])
    conn = db.get_db()
    try:
        d = _read(conn)
        with pytest.raises(RuntimeError, match="不在寫交易內"):
            hq.save_quotation_json(conn, NO, d)
    finally:
        conn.close()


def test_a_transaction_opened_implicitly_by_another_write_is_refused(client, strict):
    """交易外讀 → 寫了別的表（交易被隱式開啟）→ 整包寫回：in_transaction 為 True 也不可以放行。"""
    import db
    _seed(assigned=[])
    conn = db.get_db()
    try:
        d = _read(conn)
        conn.execute("UPDATE quotations SET updated_at=updated_at WHERE quote_no=?", (NO,))
        assert conn.in_transaction
        with pytest.raises(RuntimeError, match="不是 begin_write 開的"):
            hq.save_quotation_json(conn, NO, d)
    finally:
        conn.close()


def test_reading_before_begin_write_without_rereading_is_refused(client, strict):
    import db
    _seed(assigned=[])
    conn = db.get_db()
    try:
        d = _read(conn)                      # 鎖外讀
        hq.begin_write(conn)                 # 之後才拿鎖、沒重讀
        with pytest.raises(RuntimeError, match="拿鎖之後沒有讀過"):
            hq.save_quotation_json(conn, NO, d)
    finally:
        conn.close()


def test_read_under_the_write_lock_is_allowed(client):
    import db
    _seed(assigned=[])
    conn = db.get_db()
    try:
        hq.begin_write(conn)
        d = _read(conn)
        d["_ok"] = 1
        hq.save_quotation_json(conn, NO, d)
        conn.commit()
    finally:
        conn.close()
    conn = db.get_db()
    try:
        assert _read(conn).get("_ok") == 1
    finally:
        conn.close()


def test_without_the_strict_flag_it_logs_an_error_and_still_writes(client, monkeypatch, caplog):
    """預設（未設旗標，例如客戶自架的任何安裝路徑）：記 ERROR＋堆疊，資料照寫。"""
    import db
    _seed(assigned=[])
    monkeypatch.delenv("MOTRIX_STRICT_DB_GUARDS", raising=False)
    conn = db.get_db()
    try:
        d = _read(conn)
        d["_default"] = 1
        with caplog.at_level(logging.ERROR, logger=hq.__name__):
            hq.save_quotation_json(conn, NO, d)       # 交易外：違規，但不可以擋
        conn.commit()
    finally:
        conn.close()
    errs = [r for r in caplog.records if r.levelno >= logging.ERROR and "lost update" in r.getMessage()]
    assert errs, "未設旗標時要記 ERROR"
    assert "save_quotation_json" in errs[0].getMessage() and "File " in errs[0].getMessage(), "ERROR 要附呼叫堆疊"
    conn = db.get_db()
    try:
        assert _read(conn).get("_default") == 1, "未設旗標時不可以因守門擋住寫入"
    finally:
        conn.close()


def test_with_the_strict_flag_it_raises(client, strict):
    import db
    _seed(assigned=[])
    conn = db.get_db()
    try:
        with pytest.raises(RuntimeError, match="lost update"):
            hq.save_quotation_json(conn, NO, _read(conn))
    finally:
        conn.close()
