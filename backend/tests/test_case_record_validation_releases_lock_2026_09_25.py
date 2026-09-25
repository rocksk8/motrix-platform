"""案件存檔驗證不過（400）時，要放掉寫鎖（關閉連線）。

☠️ 2026-09-25（存檔排隊修正後 e2e 一半機率 500「database is locked」）：`update_case_record` 一開頭
   `BEGIN IMMEDIATE`；之後 `validate_invoice_amounts`／`validate_invoice_no` 丟 400 時沒有關連線
   ⇒ 寫鎖留到連線被回收為止。正式機同樣會發生：有人存了只填一欄的發票，其他人的寫入被鎖住最多 30 秒後 500。
   以前 400 之後沒人立刻再寫所以看不出來；存檔排隊改成「失敗後仍以最新狀態重送」就撞上。
量法：包住 get_db 追蹤這一次請求用的連線，400 回來時它必須已關閉（不在交易裡）。
"""
import sqlite3

import routers.quotations as q
from tests.test_case_money_mask_2026_09_24 import NO, _db_data, _login, _seed


class _Tracked:
    def __init__(self, conn):
        self._c = conn
        self.closed = False

    def close(self):
        self.closed = True
        return self._c.close()

    def __getattr__(self, name):
        return getattr(self._c, name)


def test_a_rejected_invoice_save_releases_the_write_lock(client, make_user, monkeypatch):
    u, pw = make_user(username="lock_rel", role="superadmin")
    _seed(assigned=[])
    h = _login(client, u, pw)
    base = _db_data()["caseRecord"]["payment"]
    half = __import__("json").loads(__import__("json").dumps(base))
    half["items"][1]["invoicePretax"] = 6000          # 只填一欄 ⇒ 400

    seen = []
    original = q.get_db

    def tracked_get_db():
        c = _Tracked(original())
        seen.append(c)
        return c
    monkeypatch.setattr(q, "get_db", tracked_get_db)
    r = client.patch(f"/api/quotations/{NO}/case-record", headers=h,
                     json={"segments": {"payment": half}, "base": {"payment": base}, "defaults": {}})
    assert r.status_code == 400, r.text
    assert seen, "探針沒有攔到連線"
    leaked = [c for c in seen if not c.closed]
    assert not leaked, "驗證不過回 400，但連線沒有關閉（BEGIN IMMEDIATE 的寫鎖留著）"

    # 反向：之後另一條連線立刻拿得到寫鎖
    other = sqlite3.connect(__import__("db").DB_PATH, timeout=1)
    try:
        other.execute("BEGIN IMMEDIATE")
        other.rollback()
    finally:
        other.close()
