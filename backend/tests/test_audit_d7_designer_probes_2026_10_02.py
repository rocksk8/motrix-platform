# -*- coding: utf-8 -*-
"""第 31 班表單設計器稽核探針（d7；audit/train31-designer-c7 清單 A 組）。作者自審項目不含在內：本檔由稽核員另寫，不隨產品出貨。"""
import json
import re
from pathlib import Path

import pytest

FRONT = Path(__file__).resolve().parents[2] / "frontend"
ALLOWED_KEYS = {"token", "label", "why", "example", "applies_to", "lockable", "needs_context", "requires_time"}


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_A2_only_superadmin_can_write_definition_drafts(client, make_user):
    sa, sp = make_user(username="aud_sa", role="superadmin")
    adm, ap = make_user(username="aud_adm", role="admin")
    usr, up = make_user(username="aud_usr", role="sales")
    hs, ha, hu = _login(client, sa, sp), _login(client, adm, ap), _login(client, usr, up)
    for kind, key in (("expense_type", "travel"), ("custom_module", "zz_probe")):
        url = "/api/definitions/%s/%s/draft" % (kind, key)
        for name, h in (("admin", ha), ("user", hu), ("anon", {})):
            r = client.put(url, json={"body": {"x": 1}}, headers=h)
            assert r.status_code in (401, 403), (kind, name, r.status_code, r.text[:200])      # 沿用既有權限：非 superadmin 不可寫
        r = client.put(url, json={"body": {"x": 1}}, headers=hs)
        assert r.status_code != 403, (kind, "superadmin 反向控制：同一支端點 superadmin 不是 403", r.status_code, r.text[:200])


def test_A3_prefill_sources_is_metadata_only_and_needs_login(client, make_user):
    import db
    usr, up = make_user(username="aud_pf_user", role="sales")
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag)"
                     " VALUES (?,?,?,?,?,?,?,?,?,?)", ("MQ-AUD-PF", "已送出", "機密客戶有限公司", "機密專案", 1, 1, "{}", "2031-01-01", "2031-01-01", "已成案"))
        conn.commit()
    finally:
        conn.close()
    assert client.get("/api/platform/prefill-sources").status_code in (401, 403)             # 未登入
    r = client.get("/api/platform/prefill-sources", headers=_login(client, usr, up))
    assert r.status_code == 200, r.text
    data = r.json()
    items = data if isinstance(data, list) else data.get("sources") or data.get("items") or []
    assert items, data
    for it in items:
        assert set(it) <= ALLOWED_KEYS, set(it) - ALLOWED_KEYS                                # 只有中繼資料欄位
    blob = json.dumps(data, ensure_ascii=False)
    for secret in ("機密客戶有限公司", "機密專案", "MQ-AUD-PF", "aud_pf_user", up):
        assert secret not in blob, secret                                                     # 不含任何人員、客戶、案件資料、密碼


FORBIDDEN = re.compile(r"\bfetch\s*\(|XMLHttpRequest|window\.open\s*\(|\beval\s*\(|new\s+Function\b|document\.write\s*\(")


def _strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(^|[^:\\])//[^\n]*", r"\1", src)


def test_A4_components_make_no_requests_and_use_no_dynamic_code():
    for name in ("static/form-designer.js", "static/form-designer-model.js"):
        src = (FRONT / name).read_text(encoding="utf-8")
        hits = FORBIDDEN.findall(_strip_comments(src))
        assert not hits, (name, hits)
    # 反向控制：掃描器對一段有 fetch／eval 的文字必須命中
    assert FORBIDDEN.findall(_strip_comments("const x = 1 // fetch(\n fetch('/a'); eval('1')")) == ["fetch(", "eval("]


def test_A4b_host_adapters_report_what_they_call():
    """轉接層（宿主頁的接線）可以發請求——列出來給報告，不當缺陷；但不可有動態碼。"""
    for name in ("js/module-builder-designer.js", "js/expense-types-designer.js"):
        src = _strip_comments((FRONT / name).read_text(encoding="utf-8"))
        assert not re.findall(r"\beval\s*\(|new\s+Function\b|document\.write\s*\(", src), name
