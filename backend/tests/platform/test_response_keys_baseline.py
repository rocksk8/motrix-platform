# -*- coding: utf-8 -*-
"""U0a 回應鍵集基準（凍結條件）：每條靜態 GET 路由的 JSON 鍵路徑與匯出表頭，與『U0 之前的樹』逐項相同；內部欄位名不得出現。

記錄基準（機器空檔、在 U0 之前的父提交上）：`U0A_RECORD=1 python -m pytest tests/platform/test_response_keys_baseline.py -q`
→ 寫入 `tests/platform/response_keys_baseline.json`。之後（含 U0 遷移加欄之後）本檔比對：差異必須為空。
正對照：①故意不剝除（把中介層的剝除函式換成恆等）＋表加欄 ⇒ 記錄器必須回報洩漏；②未剝除的 csv／xlsx 表頭 ⇒ 必須回報；③下限：記到的路由數與『有列』的清單數不得過少（防止空洞）。
"""
import io
import json
import os
from pathlib import Path

import pytest

from tests.platform import _response_keys as RK

BASELINE = Path(__file__).with_name("response_keys_baseline.json")
ROUTE_FLOOR = 340            # 靜態 GET 路由記到的數量下限
ROWFUL_FLOOR = 300            # 回傳『非空鍵集』的路由下限（種子有列才有鍵）
EXPORT_FLOOR = 4             # 狀態 200 的匯出（表頭可比）下限


@pytest.fixture
def seeded(client, make_user):
    import db
    u, p = make_user(username="rk_admin", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    c = db.get_db()
    try:
        RK.seed_every_table(c)
    finally:
        c.close()
    return {"Authorization": "Bearer " + tok}


def _paths():
    import main
    return RK.get_targets(main.app)


def test_record_or_compare_against_baseline(client, seeded):
    rec = RK.record(client, seeded, _paths())
    if os.environ.get("U0A_RECORD") == "1":
        BASELINE.write_text(json.dumps(rec, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        st = {"routes": len(rec), "withkeys": sum(1 for e in rec.values() if e.get("k")),
              "exports200": sum(1 for e in rec.values() if e.get("hdr") and e["s"] == 200),
              "status0": sum(1 for e in rec.values() if e["s"] == 0), "leaks": len(RK.leaks(rec))}
        pytest.skip("基準已寫入 %s：%s" % (BASELINE.name, st))
    assert RK.leaks(rec) == [], "回應鍵集含內部欄位：%s" % RK.leaks(rec)[:10]
    assert len(rec) >= ROUTE_FLOOR, "只記到 %d 條路由（下限 %d）：記錄器可能失效" % (len(rec), ROUTE_FLOOR)
    assert sum(1 for e in rec.values() if e.get("k")) >= ROWFUL_FLOOR, "有鍵集的路由太少：種子可能沒有產生資料列"
    assert sum(1 for e in rec.values() if e.get("hdr") and e["s"] == 200) >= EXPORT_FLOOR, "可比對表頭的匯出太少"
    assert BASELINE.exists(), "缺 response_keys_baseline.json：先在 U0 之前的父提交以 U0A_RECORD=1 記錄"
    d = RK.diff(json.loads(BASELINE.read_text(encoding="utf-8")), rec)
    assert d["missing"] == [] and d["changed"] == {}, "回應鍵集與基準不同：%s" % json.dumps(d, ensure_ascii=False)[:2000]
    # added（現在才有的路由）只在同一提交新增路由時出現；那種提交必須重錄基準，所以這裡也要求空
    assert d["added"] == [], "新增了基準沒有的 GET 路由：%s（重錄基準）" % d["added"][:10]


# ── 正對照（記錄器本身不是假綠燈）────────────────────────────────────────────────────

def test_positive_control_unstripped_json_is_detected(client, seeded, monkeypatch):
    from core import internal_cols as IC      # 惰性匯入：基準要能在『還沒有 internal_cols』的父提交上記錄
    import db
    c = db.get_db()
    try:
        c.execute("ALTER TABLE customers ADD COLUMN owner_unit_id INTEGER NOT NULL DEFAULT 1")
        c.execute("INSERT INTO customers (name) VALUES ('rk_ctrl')")
        c.commit()
    finally:
        c.close()
    ok = RK.record(client, seeded, ["/api/customers"])
    assert RK.leaks(ok) == [] and ok["/api/customers"]["k"], "剝除開著 ⇒ 乾淨，且仍有鍵可比"
    monkeypatch.setattr(IC, "strip_internal_cols", lambda o: o)                           # 故意不剝除
    bad = RK.record(client, seeded, ["/api/customers"])
    assert RK.leaks(bad), "不剝除時記錄器必須回報洩漏（否則整個基準是假綠燈）"


def test_positive_control_unstripped_csv_and_xlsx_headers_are_detected():
    import openpyxl
    csv_body = "id,owner_unit_id,名稱\n1,1,甲\n".encode("utf-8")
    rec = {"/x.csv": {"s": 200, "ct": "text/csv", "hdr": RK.export_header("text/csv", csv_body)}}
    assert RK.leaks(rec) == [("/x.csv", "id,owner_unit_id,名稱")] or RK.leaks(rec) != []
    wb = openpyxl.Workbook()
    wb.active.append(["id", "unit_id", "名稱"])
    buf = io.BytesIO()
    wb.save(buf)
    ct = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    rec2 = {"/x.xlsx": {"s": 200, "ct": ct, "hdr": RK.export_header(ct, buf.getvalue())}}
    assert RK.leaks(rec2), "xlsx 表頭含 unit_id 必須被抓到"
    clean = {"/y.csv": {"s": 200, "ct": "text/csv", "hdr": RK.export_header("text/csv", "id,名稱\n".encode("utf-8"))}}
    assert RK.leaks(clean) == []


def test_diff_reports_added_removed_and_changed_keys():
    base = {"/a": {"s": 200, "k": ["x"]}, "/b": {"s": 200, "k": ["y"]}}
    now = {"/a": {"s": 200, "k": ["x", "owner_unit_id"]}, "/c": {"s": 200, "k": []}}
    d = RK.diff(base, now)
    assert d["missing"] == ["/b"] and d["added"] == ["/c"] and list(d["changed"]) == ["/a"]
    assert RK.diff(base, base) == {"missing": [], "added": [], "changed": {}}


def test_seed_every_table_creates_rows_so_lists_have_keys(client):
    import db
    c = db.get_db()
    try:
        n = RK.seed_every_table(c)
        assert n > 50
        assert c.execute("SELECT COUNT(*) FROM customers").fetchone()[0] >= 1
    finally:
        c.close()
