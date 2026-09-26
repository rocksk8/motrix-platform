"""CA-O4（M01-PLAN §3-8 ①）：L1 原本直接 import／直接寫 M01 的三處，改經 M01 提供者。

① `case.default_terms`：L1 `routers/system` 的條款端點；M01 不在 ⇒ 預設條款 404 並明說、付款條件預設空字串（不是舊內容）
② `case.doc_version`：L1 `pdf_gen` 產生 PDF 後的版本紀錄；pdf_gen 不再寫 quotations；M01 不在 ⇒ 不記、不丟例外
③ `case.recognition.won_month_map`：M08 報表的成案月份；M01 不在 ⇒ {}
正對照：提供者在時各自回 M01 的內容（`test_doc_versions_2026_09_14.py` 另驗版本紀錄寫入）。
"""
import ast
import json
from pathlib import Path

from core import registry, source_tree

BACKEND = Path(__file__).resolve().parents[2]


def _hide(monkeypatch, cap):
    orig = registry.single_provider
    monkeypatch.setattr(registry, "single_provider", lambda c: None if c == cap else orig(c))


def _h(client, make_user):
    u, p = make_user("m01l1_u", "Conn-Pass-123", role="admin")[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def test_default_terms_come_from_m01_and_say_when_absent(client, make_user, monkeypatch):
    from modules.case.quote_terms import DEFAULT_TERMS
    from routers import system
    h = _h(client, make_user)
    ok = client.get("/api/settings/quote-terms-defaults", headers=h)
    assert ok.status_code == 200 and ok.json() == DEFAULT_TERMS
    assert client.get("/api/settings/payment-terms", headers=h).json()["text"] == DEFAULT_TERMS["paymentTerms"]
    _hide(monkeypatch, "case.default_terms")
    r = client.get("/api/settings/quote-terms-defaults", headers=h)
    assert r.status_code == 404 and r.json()["detail"] == system.QUOTE_TERMS_UNAVAILABLE
    assert client.get("/api/settings/payment-terms", headers=h).json()["text"] == ""


def test_pdf_gen_does_not_write_m01_tables():
    src = (BACKEND / "pdf_gen.py").read_text(encoding="utf-8")
    strings = [n.value for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not [s for s in strings if "UPDATE quotations" in s or "INSERT INTO quotations" in s]


def test_doc_version_without_m01_is_skipped(client, tmp_path, monkeypatch):
    import db
    import pdf_gen
    monkeypatch.setattr(pdf_gen, "_get_pdf_base", lambda: str(tmp_path))
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    conn = db.get_db()
    conn.execute("INSERT INTO quotations (quote_no, status, data_json, created_at, updated_at) "
                 "VALUES ('MQ-M01L1-1','草稿','{}','2026-09-26','2026-09-26')")
    conn.commit()
    conn.close()
    _hide(monkeypatch, "case.doc_version")
    pdf_gen._record_doc_version("MQ-M01L1-1", "建立", "x", str(pdf))
    conn = db.get_db()
    try:
        data = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no='MQ-M01L1-1'").fetchone()[0])
    finally:
        conn.close()
    assert "docVersions" not in data


def test_won_month_map_goes_through_case_recognition(client, monkeypatch):
    import db
    if not source_tree.module_installed("modules/analytics/"):
        return
    from modules.case import quotations as q
    from modules.analytics.api import reports as rp
    monkeypatch.setattr(q, "quote_won_month_map", lambda conn: {"MQ-X": "2026-09"})
    conn = db.get_db()
    try:
        assert rp.quote_won_month_map(conn) == {"MQ-X": "2026-09"}
        _hide(monkeypatch, "case.recognition")
        assert rp.quote_won_month_map(conn) == {}
    finally:
        conn.close()
