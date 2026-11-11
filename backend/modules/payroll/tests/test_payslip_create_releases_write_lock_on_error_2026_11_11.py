# -*- coding: utf-8 -*-
"""`POST /api/payslips`（create_payslip）在任何錯誤路徑都不能把資料庫寫鎖留著（2026-11-11）。

起因：`tests/test_strict_bool_sites_t49.py::test_payslip_union_insurance_flag_changes_withholding_so_it_must_be_strict`
在乾淨的 train 上穩定紅（單獨跑也紅、不是 xdist／並行造成）：第一個 POST 回 422（`contractorHasUnionInsurance:"false"` 字串，
`body_flag` 丟 422），第二個 POST 卡滿 busy timeout 後 500「database is locked」。

真因：create_payslip 一開頭 `INSERT INTO payslip_seq … ON CONFLICT DO NOTHING` 就開了寫交易（sqlite3 的隱式 BEGIN），
之後 `body_flag` 的 422（以及 `int(grossAmount)` 的 ValueError 等任何沒預期的錯）丟出去時**沒有 rollback、沒有關連線** ⇒
寫鎖留到連線被垃圾回收，這段時間所有其他寫入都卡。這是產品 bug（使用者連點兩次、或同時有人存檔就會撞到），不是測試環境問題。
修法：整段交易包進 `core.txn.write_txn`（`update_payslip` 在稽核 D-2 已用同一招），區塊內任何例外都 rollback＋關連線。

這支題直接量「錯誤回應之後，別的連線能不能立刻拿寫鎖」，不依賴後面的請求去撞。
"""
import sqlite3

import pytest

import db


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _write_lock_is_free() -> bool:
    c = sqlite3.connect(db.DB_PATH, timeout=0.3)
    try:
        c.execute("BEGIN IMMEDIATE")
        c.rollback()
        return True
    except sqlite3.OperationalError as e:
        if "locked" in str(e):
            return False
        raise
    finally:
        c.close()


def _body(**over):
    d = {"contractorName": "測試承攬人", "incomeType": "9A", "grossAmount": 35000, "contractorNationality": "本國籍",
         "contractorHasUnionInsurance": False, "slipDate": "2026-12-20"}
    d.update(over)
    return {"data": d}


@pytest.fixture()
def su(client, make_user):
    u, p = make_user(username="pslock_su", role="superadmin")
    return _login(client, u, p)


@pytest.mark.parametrize("label,body,expect", [
    ("字串旗標（body_flag 422）", _body(contractorHasUnionInsurance="false"), 422),
    ("金額不是數字（int() ValueError，未預期的錯）", _body(grossAmount="abc"), None),      # 回 4xx／5xx 都行：重點是鎖要放掉
    ("勞報單號格式錯（400）", dict(_body(), slip_no="BAD-NO"), 400),
])
def test_failed_create_payslip_does_not_leave_the_write_lock(client, su, label, body, expect):
    assert _write_lock_is_free(), "前置：一開始鎖是空的"
    try:
        r = client.post("/api/payslips", json=body, headers=su)
        status = r.status_code
    except Exception:                       # TestClient 預設把未處理的例外往外丟（真伺服器是 500）
        status = 500
    if expect is not None:
        assert status == expect, (label, status)
    else:
        assert status >= 400, (label, status)
    assert _write_lock_is_free(), "%s：錯誤回應之後寫鎖還被留著（create_payslip 沒 rollback／關連線）" % label


def test_create_payslip_still_works_right_after_a_422(client, su):
    """原本的症狀：422 之後立刻再 POST 一次合法的，要馬上成功（不是等 busy timeout 再 500）。"""
    r = client.post("/api/payslips", json=_body(contractorHasUnionInsurance="false"), headers=su)
    assert r.status_code == 422, r.text[:200]
    r2 = client.post("/api/payslips", json=_body(), headers=su)
    assert r2.status_code in (200, 201), r2.text[:200]
    assert _write_lock_is_free()
