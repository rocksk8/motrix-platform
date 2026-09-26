"""`attachments.for_document`（主持裁示 M06-b，2026-09-26；docs/platform/plans/ATTACHMENTS-PLAN.md）。

傳票帶入附件的九類來源由各擁有模組提供（M01 案件 6 類、M04 外包工班 2 類、M05 應收應付 1 類），
M06 `helpers/voucher_attachments.py` 不再直讀別組的表。
- 取用方只讀 M06 自己的表（dep_scan 的 SQL 解析，與 dep_graph 同一份）；合成正對照／反向控制
- 在場的提供者：類型聯集 ⊆ 白名單、兩兩不重疊；模組全在 ⇒ 聯集＝白名單（取代原本 import 時的 assert）
- 提供者不在：候選不列那幾類、說出是哪個模組不在；帶入 400 並說明（不回空清單）
本檔在任何模組不在時也要綠（期望值依 module_installed 決定）。
- 權限（稽核 D AT-M1，主持裁示 (b)）：契約帶 `user`，提供者依原單據的讀取權限過濾；同樣有傳票權限、但看不到該案件的人
  列不出、預覽不到、帶不進那一筆（反向控制）；壞 JSON 一律明說（AT-S2，含案件動態）。
"""
import ast
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

from core import registry, source_tree
from tests.platform.test_case_stage_connectors import _without

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import dep_scan  # noqa: E402

#: M01 ④(c)（主持裁示）：題目本身就是驗 M01（案件）的行為 ⇒ M01 不在的安裝包略過；理由逐題寫在 reason
def needs_case(reason):
    return pytest.mark.skipif(not source_tree.module_installed("modules/case/"),
                              reason="需要案件模組（M01）：" + reason)


CAP = "attachments.for_document"
ROOT = {"id": 0, "username": "att_root", "role": "superadmin", "modules": []}   # 驗清單內容用（權限另有題）


def _groups():
    return json.loads((REPO / "docs" / "platform" / "modules.json").read_text(encoding="utf-8"))["modules"]


def foreign_tables(src, own, known):
    """原始碼裡讀寫到、而不屬於 `own` 的已知表。"""
    r, w, _ddl, _dyn = dep_scan.sql_tables(dep_scan.string_chunks(ast.parse(src)), known)
    return sorted((r | w) - set(own))


def test_positive_and_reverse_control_of_the_table_scan():
    known = {"vouchers_all", "voucher_attachments", "contractor_dispatches", "quotations"}
    own = {"vouchers_all", "voucher_attachments"}
    ok = 'x = "SELECT 1 FROM voucher_attachments va JOIN vouchers_all v ON v.id = va.voucher_id"\n'
    assert foreign_tables(ok, own, known) == []
    bad = ok + 'y = "SELECT files_json FROM contractor_dispatches WHERE id = ?"\n'
    assert foreign_tables(bad, own, known) == ["contractor_dispatches"]


def test_voucher_attachments_reads_no_foreign_tables():
    groups = _groups()
    own = set(groups["M06"]["tables"])
    known = {t for g in groups.values() for t in g.get("tables", [])}
    assert {"quotations", "contractor_dispatches", "invoice_vouchers"} <= known, "modules.json 讀不到表 ⇒ 會假綠"
    src = (source_tree.BACKEND / "helpers" / "voucher_attachments.py").read_text(encoding="utf-8")
    assert foreign_tables(src, own, known) == []


def _present():
    return [p for p in registry.providers(CAP).values()]


def test_providers_cover_the_whitelist_without_overlap(client):
    """client 夾具＝載入器已掛好在場的模組。"""
    from helpers import voucher_attachments as va
    assert set(va._SOURCE_OWNERS) == set(va.SOURCE_TYPES), "缺席說明的對照表要涵蓋整份白名單"
    seen = {}
    for name, prov in registry.providers(CAP).items():
        for st in prov.SOURCE_TYPES:
            assert st in va.SOURCE_TYPES, "%s 提供了白名單外的類型 %s" % (name, st)
            assert st not in seen, "%s 同時由 %s 與 %s 提供" % (st, seen[st], name)
            seen[st] = name
    owner_path = {"case": "modules/case/api/quotations.py", "arap": "modules/arap/api/invoice_vouchers.py",
                  "subcontract": "modules/subcontract/api/vendor_contractors.py"}
    want = {st for st, (key, _l, _w) in va._SOURCE_OWNERS.items() if source_tree.module_installed(owner_path[key])}
    assert set(seen) == want, "在場的提供者沒有涵蓋該在的類型：少 %s" % sorted(want - set(seen))


def _dispatch_types():
    from helpers import voucher_attachments as va
    return [st for st, (key, _l, _w) in va._SOURCE_OWNERS.items() if key == "subcontract"]


def test_absent_provider_is_named_not_silent(client, monkeypatch):
    """合成：拿掉外包工班的提供者 ⇒ 候選不列那兩類、`unavailable_sources` 說出是誰、帶入與列檔 400 並說明。"""
    from helpers import voucher_attachments as va
    _without(monkeypatch, CAP, "subcontract")
    assert not set(_dispatch_types()) & set(va._providers())
    reasons = [u["reason"] for u in va.unavailable_sources()]
    assert any("外包工班模組未安裝" in r and "派工單" in r and "承攬商發票" in r for r in reasons), reasons
    for st in _dispatch_types():
        with pytest.raises(HTTPException) as ei:
            va.source_files(None, st, "1", ROOT)
        assert ei.value.status_code == 400 and "外包工班模組未安裝" in ei.value.detail
        with pytest.raises(HTTPException) as ei:
            va.resolve_picks(None, [{"type": st, "docNo": "1", "fileId": "x"}], ROOT)
        assert "外包工班模組未安裝" in ei.value.detail


@needs_case('前提是所有提供者都在（含 M01 的案件附件）')
def test_everything_present_means_nothing_unavailable(client):
    from helpers import voucher_attachments as va
    if not source_tree.module_installed("modules/subcontract/api/vendor_contractors.py"):
        pytest.skip("外包工班不在這個安裝包 ⇒ 本來就會有一筆缺席說明")
    if not source_tree.module_installed("modules/arap/api/invoice_vouchers.py"):
        pytest.skip("應收應付不在這個安裝包 ⇒ 本來就會有一筆缺席說明")
    assert va.unavailable_sources() == []


@needs_case('種子資料與 case 參數都是 M01 的報價單')
@pytest.mark.parametrize("name", ["case", "arap"])
def test_l1_side_providers_refuse_to_swallow_broken_json(client, name):
    """M01、M05 的提供者（M04 的在模組測試裡）：壞 JSON ⇒ AttachmentSourceError；單據不存在 ⇒ []。
    AT-S2：案件動態（多列併起來）與 caseRecord 內的三類（payment_item、material、material_invoice）都要驗。"""
    import db
    from helpers.uploads import AttachmentSourceError
    if name == "arap" and not source_tree.module_installed("modules/arap/api/invoice_vouchers.py"):
        pytest.skip("應收應付不在這個安裝包 ⇒ 沒有這個提供者")
    prov = registry.providers(CAP).get(name)
    assert prov is not None, "%s 的提供者沒有登記" % name
    conn = db.get_db()
    try:
        if name == "case":
            conn.execute("INSERT INTO quotations (quote_no, status, data_json, signed_files_json, created_at, updated_at)"
                         " VALUES ('ATT-BAD','草稿','{壞','{壞','2026-01-01','2026-01-01')")
            conn.execute("INSERT INTO case_updates (quote_no, author, content, files_json, created_at) VALUES ('ATT-BAD', 'att', 'x', '{壞', '2026-01-01')")
            for st, doc in (("quotation_signed", "ATT-BAD"), ("case_update", "ATT-BAD"), ("payment_item", "ATT-BAD_0"),
                            ("material", "ATT-BAD_0"), ("material_invoice", "ATT-BAD_0"), ("material", "ATT-BAD")):
                with pytest.raises(AttachmentSourceError):
                    prov.files(conn, st, doc, ROOT)
            assert prov.files(conn, "quotation_signed", "NO-SUCH", ROOT) == []
        else:
            conn.execute("INSERT INTO quotations (quote_no, status, data_json, created_at, updated_at)"
                         " VALUES ('ATT-IV','草稿','{}','2026-01-01','2026-01-01')")
            conn.execute("INSERT INTO invoice_vouchers (voucher_no, quote_no, issued_files_json, created_at, updated_at)"
                         " VALUES ('IV-ATT-BAD','ATT-IV','{壞','2026-01-01','2026-01-01')")
            with pytest.raises(AttachmentSourceError):
                prov.files(conn, "invoice_voucher", "IV-ATT-BAD", ROOT)
            assert prov.files(conn, "invoice_voucher", "NO-SUCH", ROOT) == []
            assert prov.doc_nos_for_case(conn, "invoice_voucher", "ATT-IV", ROOT) == ["IV-ATT-BAD"]
    finally:
        conn.close()


def test_case_update_broken_json_is_said_not_swallowed(client):
    """AT-S2（D 的突變 AT5 原本存活）：案件動態的附件資料壞掉 ⇒ 帶入端 400 並說出是哪一類，不是空清單。"""
    import db
    from helpers import voucher_attachments as va
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, data_json, created_at, updated_at)"
                     " VALUES ('ATT-CU','草稿','{}','2026-01-01','2026-01-01')")
        conn.execute("INSERT INTO case_updates (quote_no, author, content, files_json, created_at) VALUES ('ATT-CU', 'att', 'x', '{壞', '2026-01-01')")
        with pytest.raises(HTTPException) as ei:
            va.source_files(conn, "case_update", "ATT-CU", ROOT)
        assert ei.value.status_code == 400 and "案件動態" in ei.value.detail
    finally:
        conn.close()


# ── 權限（稽核 D AT-M1，主持裁示 (b)）──────────────────────────────────────────

def _seed_case_with_file(quote_no, owner_id=None):
    import db
    import os
    import helpers.uploads as up
    rel = "att_perm/%s.png" % quote_no
    full = os.path.join(up.UPLOADS_ROOT, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as f:
        f.write(b"x")
    meta = [{"id": "f1", "filename": "sign.png", "path": rel}]
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, data_json, signed_files_json, created_at, updated_at,"
                     " sales_person_id) VALUES (?,?,?,?,?,?,?)",
                     (quote_no, "已送出", "{}", json.dumps(meta), "2026-01-01", "2026-01-01", owner_id))
        conn.commit()
    finally:
        conn.close()


def _hdr(client, make_user, name, role, modules):
    u, p = make_user(username=name, role=role, modules=modules)
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


@needs_case('驗 M01 案件附件依案件可見性')
def test_voucher_users_only_see_attachments_of_cases_they_can_read(client, make_user):
    """同樣有傳票權限（finance）：看得到案件的人（案件業務）列得出、帶得進；看不到的人列不出、預覽不到、帶不進（403）。
    （AT-M1c 前「看得到」用 case_manage 充當；回簽檔改用案件頁的規則後 case_manage 不再放行，改用擁有者。）"""
    inside = _hdr(client, make_user, "att_in", "engineer", ["finance"])
    _seed_case_with_file("ATT-PERM-1", owner_id=_user("att_in")["id"])
    outside = _hdr(client, make_user, "att_out", "engineer", ["finance"])
    url = "/api/vouchers/line-source-files?source_type=case&ref=ATT-PERM-1"
    got_in = client.get(url, headers=inside)
    assert got_in.status_code == 200 and [f["fileId"] for f in got_in.json()["files"]] == ["f1"], got_in.text
    got_out = client.get(url, headers=outside)
    assert got_out.status_code == 200 and got_out.json()["files"] == [], "看不到案件的人不可以列出它的附件"
    prev = client.get("/api/vouchers/line-source-file?source_type=case&ref=ATT-PERM-1&file_id=f1", headers=outside)
    assert prev.status_code in (403, 404), prev.status_code
    lines = [{"account_code": "6111", "debit": 100, "credit": 0, "summary": "a"},
             {"account_code": "1113", "debit": 0, "credit": 100, "summary": "b"}]
    for h, want in ((outside, 403), (inside, 200)):
        v = client.post("/api/vouchers", headers=h, json={"summary": "AT-M1", "lines": lines})
        assert v.status_code == 200, v.text[:200]
        r = client.post("/api/vouchers/%s/attachments" % v.json()["id"], headers=h,
                        json={"picks": [{"type": "quotation_signed", "docNo": "ATT-PERM-1", "fileId": "f1"}]})
        assert r.status_code == want, (want, r.status_code, r.text[:200])


@needs_case('逐一驗含 M01 的每個提供者')
def test_each_provider_refuses_a_reader_who_cannot_see_the_case(client):
    """每個在場的提供者：看不到案件的人 ⇒ AttachmentNotVisible（不是回空清單冒充「沒有附件」）；
    列單號時逐張過濾的提供者（開票申請）可以回「不列」。"""
    import db
    from helpers.uploads import AttachmentNotVisible
    _seed_case_with_file("ATT-PERM-2")
    nobody = {"id": 999999, "username": "att_nobody", "role": "engineer", "modules": []}
    conn = db.get_db()
    try:
        for name, prov in registry.providers(CAP).items():
            for st in prov.SOURCE_TYPES:
                try:
                    got = prov.doc_nos_for_case(conn, st, "ATT-PERM-2", nobody)
                except AttachmentNotVisible:
                    continue
                # 逐張依原單據規則過濾的提供者（開票申請，AT-M1b）：讀不到的不列
                assert got == [], (name, st, got)
        with pytest.raises(AttachmentNotVisible):
            registry.providers(CAP)["case"].files(conn, "quotation_signed", "ATT-PERM-2", nobody)
    finally:
        conn.close()


# ── AT-M1b（稽核 D 複核）：每一類用原單據**自己的**讀取規則，附件的可見範圍不可以比原單據寬 ─────────

def _seed_extra_expense_file(quote_no):
    import db
    import os
    import helpers.uploads as up
    rel = "att_perm/%s-ee.png" % quote_no
    full = os.path.join(up.UPLOADS_ROOT, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as f:
        f.write(b"x")
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, data_json, created_at, updated_at)"
                     " VALUES (?,?,?,?,?)", (quote_no, "已送出", "{}", "2026-01-01", "2026-01-01"))
        eid = conn.execute("INSERT INTO case_extra_expenses (quote_no, files_json) VALUES (?, ?)",
                           (quote_no, json.dumps([{"id": "e1", "filename": "ee.png", "path": rel}]))).lastrowid
        conn.commit()
        return str(eid)
    finally:
        conn.close()


@needs_case('驗 M01 額外支出附件的可見範圍＝M01 額外支出頁')
def test_extra_expense_attachments_are_not_wider_than_the_extra_expense_pages(client, make_user):
    """D 的探針（AT-M1b）：非擁有者、持有 case_manage＋finance 的業務 ⇒ 額外支出自己的端點 403，
    經傳票也列不出、預覽不到、帶不進那一筆附件（原本：自己端點 403、經傳票 200 且列出）。"""
    eid = _seed_extra_expense_file("ATT-EE-1")
    probe = _hdr(client, make_user, "att_ee_probe", "sales", ["case_manage", "finance"])
    own = client.get("/api/quotations/ATT-EE-1/extra-expenses", headers=probe)
    assert own.status_code == 404, ("前提：額外支出自己的端點擋這個人", own.status_code)
    got = client.get("/api/vouchers/line-source-files?source_type=case&ref=ATT-EE-1", headers=probe)
    assert got.status_code == 200, got.text[:200]
    assert [f for f in got.json()["files"] if f.get("type") == "extra_expense"] == [], got.json()["files"]
    prev = client.get("/api/vouchers/line-source-file?source_type=case&ref=ATT-EE-1&file_id=e1", headers=probe)
    assert prev.status_code in (403, 404), prev.status_code
    lines = [{"account_code": "6111", "debit": 100, "credit": 0, "summary": "a"},
             {"account_code": "1113", "debit": 0, "credit": 100, "summary": "b"}]
    v = client.post("/api/vouchers", headers=probe, json={"summary": "AT-M1b", "lines": lines})
    assert v.status_code == 200, v.text[:200]
    r = client.post("/api/vouchers/%s/attachments" % v.json()["id"], headers=probe,
                    json={"picks": [{"type": "extra_expense", "docNo": eid, "fileId": "e1"}]})
    assert r.status_code == 403, (r.status_code, r.text[:200])
    # 正對照：額外支出自己的端點放行的人（admin），經傳票也列得出
    import db
    _hdr(client, make_user, "att_ee_admin", "admin", None)
    admin = _user("att_ee_admin")
    conn = db.get_db()
    try:
        prov = registry.providers(CAP)["case"]
        assert prov.doc_nos_for_case(conn, "extra_expense", "ATT-EE-1", admin) == [eid]
        assert [m["id"] for m in prov.files(conn, "extra_expense", eid, admin)] == ["e1"]
    finally:
        conn.close()


@needs_case('開票申請掛在 M01 案件上（前提用 M01 端點）')
def test_invoice_voucher_attachments_keep_the_amount_layer(client, make_user):
    """開票申請自己的規則多一道金額層（AT-M1b）：看得到案件、但看不到金額的人（engineer，case_manage＋finance）
    自己的端點 403 ⇒ 提供者不列、`files()` 拒絕（D 的 V3：拿掉 `files()` 的檢查要轉紅）；
    持有 financial_view 的人兩邊都放行（正對照）。"""
    if not source_tree.module_installed("modules/arap/api/invoice_vouchers.py"):
        pytest.skip("應收應付不在這個安裝包 ⇒ /api/invoice-vouchers 端點不存在")
    import db
    from helpers.uploads import AttachmentNotVisible
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, data_json, created_at, updated_at)"
                     " VALUES ('ATT-IV-P','已送出','{}','2026-01-01','2026-01-01')")
        conn.execute("INSERT INTO invoice_vouchers (voucher_no, quote_no, issued_files_json, created_at, updated_at)"
                     " VALUES ('IV-ATT-P','ATT-IV-P',?,'2026-01-01','2026-01-01')",
                     (json.dumps([{"id": "i1", "filename": "iv.pdf", "path": "att_perm/iv.pdf"}]),))
        conn.commit()
    finally:
        conn.close()
    no_amt = _hdr(client, make_user, "att_iv_noamt", "engineer", ["case_manage", "finance"])
    amt = _hdr(client, make_user, "att_iv_amt", "engineer", ["case_manage", "finance", "financial_view"])
    assert client.get("/api/invoice-vouchers/IV-ATT-P", headers=no_amt).status_code == 403, "前提：自己的端點擋金額層"
    assert client.get("/api/invoice-vouchers/IV-ATT-P", headers=amt).status_code == 200
    u_no, u_amt = _user("att_iv_noamt"), _user("att_iv_amt")   # 與登入後 _require_user 同一份欄位（modules 是 JSON 字串）
    prov = registry.providers(CAP)["arap"]
    conn = db.get_db()
    try:
        assert prov.doc_nos_for_case(conn, "invoice_voucher", "ATT-IV-P", u_no) == []
        with pytest.raises(AttachmentNotVisible):
            prov.files(conn, "invoice_voucher", "IV-ATT-P", u_no)
        assert prov.doc_nos_for_case(conn, "invoice_voucher", "ATT-IV-P", u_amt) == ["IV-ATT-P"]
        assert [m["id"] for m in prov.files(conn, "invoice_voucher", "IV-ATT-P", u_amt)] == ["i1"]
    finally:
        conn.close()
    got = client.get("/api/vouchers/line-source-files?source_type=case&ref=ATT-IV-P", headers=no_amt)
    assert got.status_code == 200 and [f for f in got.json()["files"] if f.get("type") == "invoice_voucher"] == []


def _user(username):
    import db
    conn = db.get_db()
    try:
        return dict(conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone())
    finally:
        conn.close()


# ── AT-M1c（稽核 D 複核）：存在報價單上的四類用案件頁的讀取規則——不寬也不嚴 ─────────────────

_LINES = [{"account_code": "6111", "debit": 100, "credit": 0, "summary": "a"},
          {"account_code": "1113", "debit": 0, "credit": 100, "summary": "b"}]


def _pick(client, h, quote_no):
    v = client.post("/api/vouchers", headers=h, json={"summary": "AT-M1c", "lines": _LINES})
    assert v.status_code == 200, v.text[:200]
    return client.post("/api/vouchers/%s/attachments" % v.json()["id"], headers=h,
                       json={"picks": [{"type": "quotation_signed", "docNo": quote_no, "fileId": "f1"}]})


@needs_case('驗 M01 報價單附件的可見範圍＝M01 案件頁')
def test_quotation_attachments_are_not_wider_than_the_case_page(client, make_user):
    """寬（D 實測外洩）：case_manage 非擁有者 ⇒ 案件頁 403 ⇒ 經傳票不列回簽檔、預覽不到、帶入 403。"""
    _seed_case_with_file("ATT-QP-1")
    h = _hdr(client, make_user, "att_qp_cm", "engineer", ["case_manage", "finance"])
    assert client.get("/api/quotations/ATT-QP-1", headers=h).status_code == 404, "前提：案件頁擋 case_manage 非擁有者"
    got = client.get("/api/vouchers/line-source-files?source_type=case&ref=ATT-QP-1", headers=h)
    assert got.status_code == 200 and [f for f in got.json()["files"] if f.get("type") == "quotation_signed"] == [], got.text
    prev = client.get("/api/vouchers/line-source-file?source_type=case&ref=ATT-QP-1&file_id=f1", headers=h)
    assert prev.status_code in (403, 404), prev.status_code
    assert _pick(client, h, "ATT-QP-1").status_code == 403


@needs_case('驗 M01 報價單附件的可見範圍＝M01 案件頁')
def test_quotation_attachments_are_not_stricter_than_the_case_page(client, make_user):
    """嚴（D 實測出納帶不進）：cashier 非擁有者 ⇒ 案件頁 200（CM14b）⇒ 經傳票列得出回簽檔、帶入 200。"""
    _seed_case_with_file("ATT-QP-2")
    h = _hdr(client, make_user, "att_qp_cash", "engineer", ["cashier", "finance"])
    assert client.get("/api/quotations/ATT-QP-2", headers=h).status_code == 200, "前提：案件頁放行 cashier"
    got = client.get("/api/vouchers/line-source-files?source_type=case&ref=ATT-QP-2", headers=h)
    assert got.status_code == 200, got.text[:200]
    assert [f["fileId"] for f in got.json()["files"] if f.get("type") == "quotation_signed"] == ["f1"], got.json()["files"]
    assert _pick(client, h, "ATT-QP-2").status_code == 200
    # 四類都走案件頁規則（不只回簽檔）：提供者層直接驗
    import db
    from helpers.uploads import AttachmentNotVisible
    make_user(username="att_qp_cm2", role="engineer", modules=["case_manage"])
    cash, cm = _user("att_qp_cash"), _user("att_qp_cm2")
    prov = registry.providers(CAP)["case"]
    conn = db.get_db()
    try:
        for st in ("quotation_signed", "payment_item", "material", "material_invoice"):
            prov.doc_nos_for_case(conn, st, "ATT-QP-2", cash)                   # 不丟 ⇒ 放行
            with pytest.raises(AttachmentNotVisible):
                prov.doc_nos_for_case(conn, st, "ATT-QP-2", cm)
        prov.doc_nos_for_case(conn, "case_update", "ATT-QP-2", cm)              # 案件動態維持 case_manage 規則
        with pytest.raises(AttachmentNotVisible):
            prov.doc_nos_for_case(conn, "case_update", "ATT-QP-2", cash)
    finally:
        conn.close()
