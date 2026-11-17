# -*- coding: utf-8 -*-
"""最高管理者解鎖編輯改「報價人」：伺服器以帳號重查顯示名／電話／信箱，舊→新寫進稽核、editHistory、簽核理由
（feat/quote-quoter-edit-superadmin，使用者裁示 2026-11-17：維持現有能力、只補紀錄；已送出／已成案解鎖時仍可改；草稿一般 PUT 不動）。
"""
import json

import pytest

from tests._requires import requires_module

pytestmark = requires_module("case", "本檔的題打 M01（案件）的報價單解鎖編輯端點")

NO = "MQ-QUOTER-001"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _flow(approvers_by_tier):
    from db import get_db
    conn = get_db()
    try:
        tiers = [{"approvers": [{"username": u, "display_name": u} for u in tier]} for tier in approvers_by_tier]
        conn.execute("INSERT OR REPLACE INTO system_settings (key, value_json, updated_at) VALUES (?,?,?)",
                     ("unified_approval_flow", json.dumps({"tiers": tiers, "includeSubmitterManagerTier": False}, ensure_ascii=False),
                      "2026-11-17T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _seed(status="簽核中"):
    from db import get_db
    data = {"quoteNo": NO, "customerName": "報價人客", "projectName": "報價人案", "items": [{"id": "i1", "description": "品項", "qty": 1, "price": 100}],
            "salesPerson": "原業務甲", "salesPersonUsername": "qc_old", "salesPhone": "02-1111", "salesEmail": "old@corp.example",
            "approval": {"requestedBy": "qc_req", "requestedByDisplay": "qc_req", "requestedAt": "2026-11-16T09:00:00", "currentTier": 0,
                         "tiers": [{"approvers": [{"username": "qc_a1", "displayName": "qc_a1", "status": "pending"}]}]}}
    conn = get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, sales_person, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (NO, status, "報價人客", "報價人案", 100, "原業務甲", json.dumps(data, ensure_ascii=False), "2026-11-16", "2026-11-16"))
        conn.commit()
    finally:
        conn.close()


def _state():
    from db import get_db
    conn = get_db()
    try:
        r = conn.execute("SELECT data_json, status, sales_person, sales_person_id FROM quotations WHERE quote_no=?", (NO,)).fetchone()
    finally:
        conn.close()
    return json.loads(r["data_json"]), r["status"], r["sales_person"], r["sales_person_id"]


def _audit_rows():
    from db import get_db
    conn = get_db()
    try:
        return [json.loads(r["detail"] or "{}") | {"_by": r["username"]} for r in
                conn.execute("SELECT username, detail FROM audit_log WHERE action='quotation.unlock_edit' AND target_id=?", (NO,)).fetchall()]
    finally:
        conn.close()


def _put(client, headers, **over):
    data = {"customerName": "報價人客", "projectName": "報價人案", "items": [{"id": "i1", "description": "品項", "qty": 1, "price": 100}],
            "salesPerson": "原業務甲", "salesPersonUsername": "qc_old", "salesPhone": "02-1111", "salesEmail": "old@corp.example",
            "_isUnlockEdit": True}
    data.update(over)
    return client.put(f"/api/quotations/{NO}", headers=headers, json={"status": "待審核", "data": data})


@pytest.fixture
def world(client, make_user, monkeypatch):
    from db import get_db
    from modules.case.api import quotations as Q
    users = {}
    for name, role in (("qc_req", "admin"), ("qc_a1", "admin"), ("qc_old", "admin"), ("qc_new", "admin"), ("qc_gone", "admin"),
                       ("qc_sa", "superadmin"), ("qc_plain", "admin")):
        users[name] = make_user(username=name, role=role, modules=["quotation"])
    conn = get_db()
    try:
        conn.execute("UPDATE users SET display_name=?, phone=?, email=? WHERE username='qc_old'", ("原業務甲", "02-1111", "old@corp.example"))
        conn.execute("UPDATE users SET display_name=?, phone=?, email=? WHERE username='qc_new'", ("新業務乙", "02-2222", "new@corp.example"))
        conn.execute("UPDATE users SET display_name=?, active=0 WHERE username='qc_gone'", ("已停用丙",))
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(Q, "spawn_bg_thread", lambda *a, **k: None)          # 備份／PDF／通知等背景工作略過
    _flow([["qc_a1"]])
    return {"users": users, "sa": _login(client, *users["qc_sa"]), "plain": _login(client, *users["qc_plain"])}


@pytest.mark.parametrize("status", ["簽核中", "待審核", "已送出"])
def test_unlock_change_quoter_records_old_to_new(client, world, status):
    _seed(status)
    r = _put(client, world["sa"], salesPerson="新業務乙", salesPersonUsername="qc_new", salesPhone="02-2222", salesEmail="new@corp.example")
    assert r.status_code == 200, r.text
    d, st, sp_col, _sp_id = _state()
    assert st == "待審核" and sp_col == "新業務乙"
    assert d["salesPerson"] == "新業務乙" and d["salesPersonUsername"] == "qc_new"
    assert d["salesPhone"] == "02-2222" and d["salesEmail"] == "new@corp.example"
    # editHistory：舊→新＋操作者
    h = d["editHistory"][-1]
    assert h["by"] == "qc_sa"
    assert h["quoterChange"] == {"from": "原業務甲", "fromUsername": "qc_old", "to": "新業務乙", "toUsername": "qc_new",
                                 "fromEmail": "old@corp.example", "toEmail": "new@corp.example"}
    # 簽核紀錄（簽核畫面讀 approval.reasons）看得出報價人被改過
    reasons = d["approval"]["reasons"]
    assert any("報價人變更" in x and "原業務甲" in x and "新業務乙" in x for x in reasons), reasons
    assert d["approval"]["quoterChange"]["toUsername"] == "qc_new"
    # 稽核
    rows = _audit_rows()
    assert rows and rows[-1]["_by"] == "qc_sa"
    assert rows[-1]["quoterChange"]["from"] == "原業務甲" and rows[-1]["quoterChange"]["to"] == "新業務乙"


def test_server_wins_over_client_name_phone_and_foreign_email(client, world):
    """帳號與顯示名不符：以伺服器依帳號查到的為準；偽造的電話／別人的信箱不採用。"""
    _seed()
    r = _put(client, world["sa"], salesPerson="偽造的名字", salesPersonUsername="qc_new", salesPhone="0900-FAKE", salesEmail="evil@x.example")
    assert r.status_code == 200, r.text
    d, _st, sp_col, _ = _state()
    assert d["salesPerson"] == "新業務乙" and sp_col == "新業務乙"
    assert d["salesPhone"] == "02-2222"
    assert d["salesEmail"] == "new@corp.example"
    assert d["editHistory"][-1]["quoterChange"]["to"] == "新業務乙"


@pytest.mark.parametrize("un", ["qc_nobody", "qc_gone"])
def test_unknown_or_inactive_quoter_is_400_and_nothing_changes(client, world, un):
    _seed()
    r = _put(client, world["sa"], salesPerson="任何名", salesPersonUsername=un)
    assert r.status_code == 400, r.text
    d, st, sp_col, _ = _state()
    assert st == "簽核中" and sp_col == "原業務甲" and d["salesPersonUsername"] == "qc_old"
    assert not _audit_rows()


def test_name_changed_without_username_is_400(client, world):
    _seed()
    r = _put(client, world["sa"], salesPerson="新業務乙", salesPersonUsername="")
    assert r.status_code == 400, r.text
    assert _state()[2] == "原業務甲"


def test_unchanged_quoter_keeps_snapshot_and_records_no_quoter_change(client, world):
    """報價人沒換：快照欄位維持已存值（用戶端改的名字／電話不採用），歷史與稽核沒有 quoterChange。"""
    _seed()
    r = _put(client, world["sa"], salesPerson="被竄改的名字", salesPhone="0900-FAKE")
    assert r.status_code == 200, r.text
    d, _st, sp_col, _ = _state()
    assert d["salesPerson"] == "原業務甲" and sp_col == "原業務甲" and d["salesPhone"] == "02-1111"
    assert "quoterChange" not in d["editHistory"][-1]
    assert "quoterChange" not in d["approval"] and not any("報價人變更" in x for x in d["approval"]["reasons"])
    assert "quoterChange" not in _audit_rows()[-1]


def test_non_superadmin_unlock_is_still_403(client, world):
    """回歸：只有最高管理者能走解鎖路徑；其他人帶 _isUnlockEdit 改報價人一律 403，資料不動。"""
    _seed()
    r = _put(client, world["plain"], salesPerson="新業務乙", salesPersonUsername="qc_new")
    assert r.status_code == 403, r.text
    d, st, sp_col, _ = _state()
    assert st == "簽核中" and sp_col == "原業務甲" and d["salesPersonUsername"] == "qc_old"
