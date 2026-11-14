"""權限矩陣「角色與功能」群組標題要有正式名稱（T86 F3，2026-11-14）。

能力鍵第一段是「單元鍵」（case／crm／payroll／supply），`unitLabel` 原本用功能鍵對照表（module_registry）查，
查不到一律變成「（未命名功能）」，每位最高管理者看到的每個群組標題都是這句。
觀測點：真實載入的模組（不替換能力清單）經 GET /api/permmatrix/matrix 回的 caps[].unitLabel 與前端分組用的欄位。
正對照：宣告檔有名稱的單元標題＝該名稱；對不到名稱的備援（單元鍵不在任何登錄）仍是舊行為。
"""
import json
from pathlib import Path

from helpers import perm_text as T

BACKEND = Path(__file__).resolve().parents[1]


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _declared_names():
    out = {}
    for f in (BACKEND / "modules").glob("*/module.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        out[f.parent.name] = d.get("name")
    return out


def test_every_group_title_is_a_real_name_not_unnamed(client, make_user):
    u, p = make_user(username="pm_unit_sa", role="superadmin", modules=[])
    h = _login(client, u, p)
    r = client.get("/api/permmatrix/matrix", headers=h)
    assert r.status_code == 200, r.text
    caps = r.json()["caps"]
    units = {c["unit"] for c in caps}
    assert len(units) >= 3, f"真實載入的模組至少有幾個單元宣告能力（否則這題沒有東西可驗）：{units}"
    names = _declared_names()
    for c in caps:
        assert "未命名" not in c["unitLabel"], f"{c['unit']} 的群組標題顯示成「{c['unitLabel']}」"
        assert c["unitLabel"] == names[c["unit"]], f"{c['unit']} 的標題應等於宣告檔名稱：{c['unitLabel']}"
        assert c["unit"] == c["key"].split(".")[0], "權限鍵與單元欄位沒變"


def test_effective_view_uses_the_same_unit_names(client, make_user):
    sa, sp = make_user(username="pm_unit_sa2", role="superadmin", modules=[])
    other, _op = make_user(username="pm_unit_u", role="sales", modules=[])
    h = _login(client, sa, sp)
    import db
    conn = db.get_db()
    try:
        uid = conn.execute("SELECT id FROM users WHERE username='pm_unit_u'").fetchone()["id"]
    finally:
        conn.close()
    r = client.get(f"/api/permmatrix/users/{uid}/effective", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["caps"] and all("未命名" not in c["unitLabel"] for c in r.json()["caps"])


def test_fallback_for_unknown_unit_is_unchanged():
    from modules.permmatrix import views as V
    assert V._unit_label("no_such_unit", {}) == "（未命名功能）", "完全對不到名稱才退回舊備援"
    assert V._unit_label("case", {"case": "案件"}) == "案件"
    assert V._unit_label("case_manage", {}) == T.module_label("case_manage"), "功能鍵仍走舊對照表"
