# -*- coding: utf-8 -*-
"""選單紅色數字 `GET /api/reads/module-counts`：一次掃描、數字不變、回應有上限。

hichan-8d 追 e2e 逾時量到「module-counts 約 2 秒」。量測（2026-09-24）：
```
開發庫 audit_log 2358 筆、無索引      10 個模組各查一次，SQL 合計 2.3 ms
TestClient（開發庫複本）              module-counts ≈ 60 ms、/api/auth/me ≈ 21 ms
瀏覽器 request timing（乾淨環境）     伺服器段 70～200 ms，為同頁 API 的 2～5 倍；重現不出 2 秒
合成 5 萬筆（修正前）                 中位數 111 ms
```
⇒ 2 秒推斷是 `-n 6` 負載下 CPU 競爭放大了本來就最慢的那一支；伺服器端能做的是把
「每個模組各掃一次 audit_log、再經另一支端點重複驗 session」收成一次。

## 🔴 誠實記錄：時間上限那一題在修正前**也是綠的**

5 萬筆時修正前 111 ms，而上限是 300 ms ⇒ 它不是「先紅」的題，是回歸守門。
「先紅」的是掃描次數那一題（修正前 10 次）。門檻沒有為了變紅而調低。
"""
import json
import random
import statistics
import time
from datetime import datetime, timedelta

import pytest


def _hdr(client, make_user, username, role="superadmin"):
    u, p = make_user(username=username, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _seed(rows):
    import db
    conn = db.get_db()
    try:
        conn.executemany(
            "INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,"
            "target_label,detail) VALUES (?,?,?,?,?,?,?,?,?)",
            [(at, None, u, u, a, "t", "1", "", "{}") for at, u, a in rows])
        conn.commit()
    finally:
        conn.close()


def test_module_counts_scan_audit_log_once(client, make_user, monkeypatch):
    """修正前：每個模組各一句 `SELECT COUNT(*) FROM audit_log`（10 次）。"""
    import db
    h = _hdr(client, make_user, "alice")
    seen = []
    real = db.get_db

    def traced():
        conn = real()
        conn.set_trace_callback(lambda sql: seen.append(sql))
        return conn

    monkeypatch.setattr(db, "get_db", traced)
    import routers.item_reads as ir
    monkeypatch.setattr(ir, "get_db", traced, raising=False)
    import routers.system as sy
    monkeypatch.setattr(sy, "get_db", traced, raising=False)
    r = client.get("/api/reads/module-counts", headers=h)
    assert r.status_code == 200, r.text
    scans = [s for s in seen if "audit_log" in s and s.lstrip().upper().startswith("SELECT")]
    assert len(scans) == 1, "應該一次掃完，實際 %d 次：\n%s" % (len(scans), "\n".join(scans))


def test_counts_equal_the_per_module_definition(client, make_user):
    """等價對照：一次掃描算出來的數字，必須與原本逐模組的定義（`audit_module_counts`）完全相同。"""
    from routers.system import _MODULE_ACTION_PREFIXES, audit_module_counts
    h = _hdr(client, make_user, "alice")
    make_user(username="bob", role="admin")
    now = datetime.now()
    # alice 看過 customer 是 1 小時前；其他模組沒有紀錄 ⇒ 往回 7 天
    client.post("/api/reads", json={"kind": "module", "key": "customer"}, headers=h)
    import db
    conn = db.get_db()
    conn.execute("UPDATE item_reads SET read_at=? WHERE username='alice' AND kind='module'",
                 ((now - timedelta(hours=1)).isoformat(),))
    conn.commit()
    conn.close()
    rows = []
    for mod, prefixes in _MODULE_ACTION_PREFIXES.items():
        for p in prefixes:
            for dt in (timedelta(minutes=5), timedelta(hours=3), timedelta(days=3), timedelta(days=10)):
                rows.append(((now - dt).isoformat(), "bob", p + "update"))
                rows.append(((now - dt).isoformat(), "alice", p + "update"))   # 本人：不算
    rows.append(((now - timedelta(minutes=1)).isoformat(), "bob", "dev_case.delete"))  # 排除清單
    rows.append(((now - timedelta(minutes=1)).isoformat(), "bob", "auth.login"))       # 不屬任何模組
    _seed(rows)

    got = client.get("/api/reads/module-counts", headers=h).json()
    default = (now - timedelta(days=7)).isoformat()
    since = {m: default for m in _MODULE_ACTION_PREFIXES}
    since["customer"] = (now - timedelta(hours=1)).isoformat()
    want = audit_module_counts(body={"modules": since}, authorization=h["Authorization"])
    assert got == want
    assert got["customer"] == 1 and got["quotation"] == 3     # 量尺：數字不是全 0
    assert got["dev_crm"] == 6                                # 兩個前綴 × 3，delete 被排除


def test_module_counts_stays_fast_with_50k_audit_rows(client, make_user):
    """回歸守門（修正前也綠，見檔頭）：5 萬筆 audit_log，伺服器端中位數 < 300 ms。"""
    h = _hdr(client, make_user, "alice")
    acts = ["quotation.update", "customer.update", "dev_case.update", "work_log.create",
            "daily_task.update", "payment.mark", "device.update", "supplier.update",
            "tender_watch.update", "case_stage.update", "auth.login", "deal_tag.change"]
    now = datetime.now()
    rnd = random.Random(7)
    _seed([((now - timedelta(minutes=rnd.randint(0, 60 * 24 * 120))).isoformat(),
            "u%d" % (i % 20), rnd.choice(acts)) for i in range(50000)])
    ts = []
    for _ in range(7):
        t = time.perf_counter()
        r = client.get("/api/reads/module-counts", headers=h)
        ts.append((time.perf_counter() - t) * 1000)
        assert r.status_code == 200
    assert statistics.median(ts) < 300, ts
