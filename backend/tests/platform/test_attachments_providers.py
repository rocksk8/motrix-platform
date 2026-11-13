# 依第42班使用者裁示（傳票／出納／財務金額能力只屬財務角色與 superadmin；財務與出納合併），刪除 7 題原本 skip 的測試：test_voucher_users_only_see_attachments_of_cases_they_can_read、test_extra_expense_attachments_are_not_wider_than_the_extra_expense_pages、test_invoice_voucher_attachments_keep_the_amount_layer、test_quotation_attachments_are_not_wider_than_the_case_page、test_hidden_notice_carries_no_identifier_of_the_unseen_document、test_partially_visible_invoice_vouchers_list_the_visible_one、test_a_wholly_unseen_case_answers_like_a_missing_one（2026-11-13 chore/test-prune）
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
_MAKE_USER_DEFAULT_ROLE = "superadmin"      # 第42班：財務／出納不再有 admin 直通；舊題的「預設 admin 操作者」改用 superadmin（見 conftest.make_user）


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
    rel = "modules/accounting/voucher_attachments.py"                  # M06 搬遷（2026-09-26）
    if not source_tree.module_installed(rel):
        pytest.skip("會計（M06）不在：沒有取用方")
    src = (source_tree.BACKEND / rel).read_text(encoding="utf-8")
    assert foreign_tables(src, own, known) == []


def _present():
    return [p for p in registry.providers(CAP).values()]


def test_providers_cover_the_whitelist_without_overlap(client):
    """client 夾具＝載入器已掛好在場的模組。"""
    if not source_tree.module_installed("modules/accounting/"):
        pytest.skip("會計（M06）不在這個安裝包（PLAYBOOK §B-11）")
    from modules.accounting import voucher_attachments as va
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
    from modules.accounting import voucher_attachments as va
    return [st for st, (key, _l, _w) in va._SOURCE_OWNERS.items() if key == "subcontract"]


def test_absent_provider_is_named_not_silent(client, monkeypatch):
    """合成：拿掉外包工班的提供者 ⇒ 候選不列那兩類、`unavailable_sources` 說出是誰、帶入與列檔 400 並說明。"""
    if not source_tree.module_installed("modules/accounting/"):
        pytest.skip("會計（M06）不在這個安裝包（PLAYBOOK §B-11）")
    from modules.accounting import voucher_attachments as va
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
    if not source_tree.module_installed("modules/accounting/"):
        pytest.skip("會計（M06）不在這個安裝包（PLAYBOOK §B-11）")
    from modules.accounting import voucher_attachments as va
    if not source_tree.module_installed("modules/subcontract/api/vendor_contractors.py"):
        pytest.skip("外包工班不在這個安裝包 ⇒ 本來就會有一筆缺席說明")
    if not source_tree.module_installed("modules/arap/api/invoice_vouchers.py"):
        pytest.skip("應收應付不在這個安裝包 ⇒ 本來就會有一筆缺席說明")
    assert va.unavailable_sources() == []


@needs_case('case 參數是 M01 的提供者；arap 參數以 SQL 種報價單，M01 不在時開票申請提供者依 CA-M1 fail-closed（稽核 D M4-S1 建議另補題）')
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
    if not source_tree.module_installed("modules/accounting/"):
        pytest.skip("會計（M06）不在這個安裝包（PLAYBOOK §B-11）")
    import db
    from modules.accounting import voucher_attachments as va
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
    rel = "quotations/%s/sign.png" % quote_no          # 真實配置：<資料夾>/<單據鍵>/<檔>（open-bind：路徑必須在該單據自己的資料夾）
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
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, data_json, created_at, updated_at)"
                     " VALUES (?,?,?,?,?)", (quote_no, "已送出", "{}", "2026-01-01", "2026-01-01"))
        eid = conn.execute("INSERT INTO case_extra_expenses (quote_no, files_json) VALUES (?, ?)", (quote_no, "[]")).lastrowid
        rel = "case_extra_expense/%s_%s/ee.png" % (quote_no, eid)          # 真實配置（open-bind）：資料夾鍵＝<案件>_<支出 id>
        full = os.path.join(up.UPLOADS_ROOT, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(b"x")
        conn.execute("UPDATE case_extra_expenses SET files_json=? WHERE id=?",
                     (json.dumps([{"id": "e1", "filename": "ee.png", "path": rel}]), eid))
        conn.commit()
        return str(eid)
    finally:
        conn.close()


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
def test_quotation_attachments_are_not_stricter_than_the_case_page(client, make_user):
    """嚴（D 實測出納帶不進）：cashier 非擁有者 ⇒ 案件頁 200（CM14b）⇒ 經傳票列得出回簽檔、帶入 200。"""
    if not source_tree.module_installed("modules/accounting/"):
        pytest.skip("會計（M06）不在這個安裝包（PLAYBOOK §B-11）")
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


def _hidden(resp):
    """回應裡因權限沒列出的附件：{類別: 個數}（主持裁示 2026-09-26：明說，不可以靜默少列）。
    每一筆只准有 category／count／reason 三個鍵（只說類別與個數）。"""
    got = resp.json().get("hidden")
    assert isinstance(got, list), "回應要有 hidden 欄位"
    for h in got:
        assert set(h) == {"category", "count", "reason"}, ("hidden 只准回類別與個數", h)
        assert h["reason"] and str(h["count"]) in h["reason"], h
    return {h["category"]: h["count"] for h in got}


def _no_identifiers(resp, *secrets):
    """反向控制（主持裁示）：hidden 裡不可以出現看不到的那張單據的任何識別字串（單號、檔名、路徑、檔案 id）。"""
    text = json.dumps(resp.json().get("hidden"), ensure_ascii=False)
    leaked = [x for x in secrets if x in text]
    assert not leaked, ("「明說」本身不可以外洩", leaked, text)


@needs_case('source_type=case 需要 M01 的 attachments.for_document 提供者')
def test_nothing_hidden_means_hidden_is_empty(client, make_user):
    """正對照：看得到全部原單據的人（案件業務）⇒ hidden 是空清單（不是每次都亮的警告）。"""
    if not source_tree.module_installed("modules/accounting/"):
        pytest.skip("會計（M06）不在這個安裝包（PLAYBOOK §B-11）")
    h = _hdr(client, make_user, "att_hid_own", "engineer", ["finance"])
    _seed_case_with_file("ATT-HID-1", owner_id=_user("att_hid_own")["id"])
    got = client.get("/api/vouchers/line-source-files?source_type=case&ref=ATT-HID-1", headers=h)
    assert got.status_code == 200 and [f["fileId"] for f in got.json()["files"]] == ["f1"]
    assert _hidden(got) == {}


def _add_case_update_file(quote_no):
    """案件動態一筆附件：case_manage 看得到（案件動態端點的規則）⇒ 讓案件「部分看得到」。"""
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO case_updates (quote_no, author, content, files_json, created_at) VALUES (?,?,?,?,?)",
                     (quote_no, "t", "t", json.dumps([{"id": "cu1", "filename": "update.png", "path": "case_updates/%s/cu.png" % quote_no}]),
                      "2026-01-01"))
        conn.commit()
    finally:
        conn.close()

