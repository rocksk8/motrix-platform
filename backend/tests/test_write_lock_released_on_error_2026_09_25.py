"""拿了寫鎖（BEGIN IMMEDIATE）之後丟例外 ⇒ 寫鎖一定要釋放（2026-09-25，bf 3b3504ba 那一型；W-6「database is locked」成因）。

範圍：承攬商匯款申請建立、開票憑據建立、請款單建立／修改——這 4 處原本拿鎖之後的路徑沒有被 try/finally 保護，
中途遇到沒預期的例外 ⇒ 寫鎖留到連線被回收，其他人的寫入卡 30 秒後 500。
探針：把模組裡的 get_db 換成代理連線，BEGIN IMMEDIATE 之後的**第一個** SQL 就丟例外
（不必準備整套前置資料，只要通過拿鎖之前的驗證）。握著例外（traceback 還引用 frame）時，另一條連線 1 秒內要拿得到寫鎖。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
skip_module_unless("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')   # 本檔在模組層就 import M01（或 import 會略過的題檔）
import pytest

import modules.case.api.quotations as q
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


class _BoomAfterBegin:
    def __init__(self, conn):
        self._c, self._armed = conn, False

    def execute(self, sql, *a, **k):
        if self._armed:
            raise RuntimeError("拿了寫鎖之後的意外錯誤（探針）")
        cur = self._c.execute(sql, *a, **k)
        if isinstance(sql, str) and sql.strip().upper().startswith("BEGIN IMMEDIATE"):
            self._armed = True
        return cur

    def __getattr__(self, name):
        return getattr(self._c, name)


def _lock_is_free():
    import db
    conn = db.get_db()
    try:
        conn.execute("PRAGMA busy_timeout = 1000")
        conn.execute("BEGIN IMMEDIATE")
        conn.rollback()
        return True
    except Exception as e:                                 # noqa: BLE001
        return repr(e)
    finally:
        conn.close()


CASES = {
    # 外包工班的端點以模組路徑字串登記：模組不在這個安裝包時不 import（PLAYBOOK §B-11，稽核 D M04-M1）
    "contractor_voucher_create": ("modules.subcontract.api.contractor_vouchers", "post", "/api/contractor-vouchers", {"dispatch_id": 1}),
    "invoice_voucher_create": ("modules.arap.api.invoice_vouchers", "post", "/api/invoice-vouchers", {"quote_no": "MQ-X", "scope": "amount", "amount": 100}),
    "payment_request_create": ("modules.arap.api.payment_requests", "post", "/api/payment-requests",
                               {"quote_no": "MQ-X", "scope": "amount", "stage": "full", "amount": 100}),
    "payment_request_update": ("modules.arap.api.payment_requests", "put", "/api/payment-requests/PR-X", {"scope": "amount", "stage": "full", "amount": 100}),
    # lost update C 組新包進 write_txn 的三支（讀之前就拿鎖 ⇒ 拿鎖後出錯也要放）
    "quotation_status": (q, "patch", "/api/quotations/MQ-X/status", {"status": "已送出"}),
    "quotation_recall": (q, "post", "/api/quotations/MQ-X/recall", None),
    "quotation_reject": (q, "post", "/api/quotations/MQ-X/reject", {"note": "x"}),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_an_error_after_begin_immediate_releases_the_write_lock(client, make_user, monkeypatch, case):
    mod, method, path, body = CASES[case]
    if isinstance(mod, str):
        from core import source_tree
        if not source_tree.module_installed(mod.replace(".", "/") + ".py"):
            pytest.skip("%s 的模組不在這個安裝包（PLAYBOOK §B-11）" % mod)
        import importlib
        mod = importlib.import_module(mod)
    u, pw = make_user(username="wl_" + case[:16], role="superadmin")
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}
    real = mod.get_db
    made = []

    def _proxy_get_db(*a, **k):
        p = _BoomAfterBegin(real(*a, **k))
        made.append(p)
        return p
    monkeypatch.setattr(mod, "get_db", _proxy_get_db)
    with pytest.raises(RuntimeError) as excinfo:          # 握著例外，貼近正式機
        getattr(client, method)(path, headers=h, **({"json": body} if body is not None else {}))
    assert "探針" in str(excinfo.value)
    assert any(p._armed for p in made), "前提：探針要在拿了寫鎖之後才觸發"
    free = _lock_is_free()
    assert free is True, ("丟例外之後寫鎖沒有釋放（連線沒關）", free)
