# -*- coding: utf-8 -*-
"""報價單規格文件（備註事項 B：規格 PDF 併入）的後端：上傳／刪除端點、清單與 mergeFiles 驗證、下載與存檔版的併入、資料夾登記守門。

純併檔函式的單元測試在 `test_pdf_merge_2026_11_17.py`；這裡鎖的是整條線：
① 上傳：只收 PDF；單檔不合格不拖垮整批；加密／壞檔／零頁可存但狀態不是 ok；上限（10 檔／單檔／合計）
② 閘門：與 PUT 報價單同一條狀態鎖；外人 404
③ 刪除：檔案清單＋mergeFiles 同一個寫交易（失敗＝全部還在）；commit 之後才刪實體檔；路徑被竄改不碰磁碟
④ 輸出：沒選＝逐位元不變；下載端點併入、略過原因放標頭（不印進 PDF）；存檔版就地併入並記 mergeSkipped
⑤ 登記守門：上傳資料夾有讀取規則、數量上限、附件目錄類別、回收筒；migration 0013 冪等
"""
import io
import json
import os
import re
import sqlite3
from urllib.parse import unquote

import pypdf
import pytest

import db
import helpers.uploads as UP
from modules.case.api import quotation_specs as QS

pytestmark = pytest.mark.upload_magic              # 真檔頭檢查：偽裝成 pdf 的文字檔要被擋

Q = "MQ-SP-001"


# ── 工具 ──────────────────────────────────────────────────────────────────────

def _pdf(pages=1, encrypt=False):
    w = pypdf.PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    if encrypt:
        w.encrypt("pw")
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def _npages(b):
    return len(pypdf.PdfReader(io.BytesIO(b)).pages)


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _x(sql, args=()):
    c = db.get_db()
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def _q(sql, args=()):
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _uid(username):
    return _q("SELECT id FROM users WHERE username=?", (username,))[0]["id"]


def _quote(no=Q, status="草稿", owner="sp_owner", data=None):
    _x("INSERT OR REPLACE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, sales_person_id, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
       (no, status, "客戶", "工程", 1000, 952, json.dumps(data or {}), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "",
        _uid(owner), owner, "[]"))


@pytest.fixture
def world(client, make_user):
    H = {}
    for name, role, mods in (("sp_owner", "sales", ["quotation"]), ("sp_admin", "admin", None),
                             ("sp_outsider", "sales", ["quotation", "case_manage"]), ("sp_viewer", "viewer", [])):
        u, p = make_user(username=name, role=role, modules=mods)
        H[name] = _login(client, u, p)
    _quote()
    return H


def _up(client, h, files, no=Q):
    return client.post("/api/quotations/%s/spec-files" % no, headers=h,
                       files=[("files", (n, d, "application/pdf")) for n, d in files])


def _specs(no=Q):
    return json.loads(_q("SELECT spec_files_json FROM quotations WHERE quote_no=?", (no,))[0]["spec_files_json"] or "[]")


def _data(no=Q):
    return json.loads(_q("SELECT data_json FROM quotations WHERE quote_no=?", (no,))[0]["data_json"] or "{}")


def _set_merge(ids, no=Q):
    d = _data(no)
    if ids:
        d["mergeFiles"] = ids
    else:
        d.pop("mergeFiles", None)
    _x("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), no))


def _abs(entry):
    return os.path.join(UP.UPLOADS_ROOT, *entry["path"].split("/"))


# ── ① 上傳 ────────────────────────────────────────────────────────────────────

def test_upload_ok_returns_public_list_without_paths_and_stores_under_own_folder(client, world):
    r = _up(client, world["sp_owner"], [("規格.pdf", _pdf(3))])
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["mergeFiles"] == [] and j["rejected"] == [] and len(j["specFiles"]) == 1
    f = j["specFiles"][0]
    assert f["name"] == "規格.pdf" and f["pages"] == 3 and f["status"] == "ok" and len(f["id"]) == 32
    assert "path" not in f and "abs_path" not in f
    st = _specs()[0]
    assert st["id"] == f["id"] and st["path"].startswith("quotation_specs/%s/" % Q) and os.path.isfile(_abs(st))
    assert set(st) == {"id", "name", "path", "size", "pages", "status", "uploadedAt", "uploadedBy"}


def test_one_bad_file_does_not_fail_the_batch(client, world):
    r = _up(client, world["sp_owner"], [("a.pdf", _pdf(1)), ("note.txt", b"hello"), ("fake.pdf", b"MZ not a pdf"), ("e.pdf", b"")])
    assert r.status_code == 200, r.text
    j = r.json()
    assert [f["name"] for f in j["specFiles"]] == ["a.pdf"]
    got = {x["name"]: x["reason"] for x in j["rejected"]}
    assert got == {"note.txt": "not_pdf", "fake.pdf": "invalid", "e.pdf": "empty"}
    assert all(x["reason"] in QS.REJECT_REASONS for x in j["rejected"])
    assert len(_specs()) == 1
    assert len(os.listdir(os.path.dirname(_abs(_specs()[0])))) == 1                # 被擋的檔沒有留在磁碟上


def test_all_rejected_is_still_200_and_changes_nothing(client, world):
    r = _up(client, world["sp_owner"], [("x.txt", b"x")])
    assert r.status_code == 200 and r.json()["specFiles"] == [] and r.json()["rejected"][0]["reason"] == "not_pdf"
    assert _specs() == []


def test_encrypted_and_empty_pdfs_are_stored_with_non_ok_status(client, world):
    empty = io.BytesIO()
    pypdf.PdfWriter().write(empty)
    r = _up(client, world["sp_owner"], [("enc.pdf", _pdf(2, encrypt=True)), ("zero.pdf", empty.getvalue()), ("ok.pdf", _pdf(1))])
    assert r.status_code == 200, r.text
    assert {f["name"]: f["status"] for f in r.json()["specFiles"]} == {"enc.pdf": "encrypted", "zero.pdf": "empty", "ok.pdf": "ok"}


def test_limit_of_ten_files(client, world):
    r = _up(client, world["sp_owner"], [("f%d.pdf" % i, _pdf(1)) for i in range(12)])
    assert r.status_code == 200
    j = r.json()
    assert len(j["specFiles"]) == 10 and [x["reason"] for x in j["rejected"]] == ["too_many", "too_many"]
    r2 = _up(client, world["sp_owner"], [("more.pdf", _pdf(1))])
    assert r2.json()["rejected"][0]["reason"] == "too_many" and len(_specs()) == 10


def test_single_file_size_and_total_limits(client, world, monkeypatch):
    big = _pdf(1) + b"\n%" + b"0" * 5000
    monkeypatch.setattr(UP, "_MAX_FILE_SIZE", 4000)
    r = _up(client, world["sp_owner"], [("big.pdf", big), ("small.pdf", _pdf(1))])
    assert {x["name"]: x["reason"] for x in r.json()["rejected"]} == {"big.pdf": "too_large"}
    monkeypatch.setattr(UP, "_MAX_FILE_SIZE", UP._DEFAULT_MAX_FILE_SIZE)
    monkeypatch.setattr(QS, "MAX_SPEC_TOTAL_BYTES", len(_pdf(1)) + 10)            # 只容得下一份
    r = _up(client, world["sp_owner"], [("second.pdf", _pdf(1))])
    assert r.json()["rejected"][0]["reason"] == "over_total" and len(_specs()) == 1


def test_upload_does_not_touch_updated_at_or_merge_files(client, world):
    before = _q("SELECT updated_at FROM quotations WHERE quote_no=?", (Q,))[0]["updated_at"]
    _up(client, world["sp_owner"], [("a.pdf", _pdf(1))])
    assert _q("SELECT updated_at FROM quotations WHERE quote_no=?", (Q,))[0]["updated_at"] == before     # 開著的表單的 _expectedUpdatedAt 不會因此 409
    assert "mergeFiles" not in _data()


# ── ② 閘門 ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status,ok", [("草稿", True), ("已退回", True), ("待審核", False), ("簽核中", False), ("已送出", False),
                                       ("已成案", False), ("已結案", False), ("已拒絕", False)])
def test_edit_gate_matches_put_quotation_state_lock(client, world, status, ok):
    _quote(status=status)
    r = _up(client, world["sp_owner"], [("a.pdf", _pdf(1))])
    assert (r.status_code == 200) is ok, (status, r.status_code, r.text)
    assert len(_specs()) == (1 if ok else 0)


def test_gate_tuple_is_the_same_literal_as_put_quotation():
    """`quotation_specs.EDIT_LOCKED_STATUSES` 與 `update_quotation` 內的 `_LOCKED` 必須一致（後者是區域變數，無法 import）。"""
    src = open(os.path.join(os.path.dirname(QS.__file__), "quotations.py"), encoding="utf-8").read()
    m = re.search(r"_LOCKED = \(([^)]*)\)", src)
    assert m, "找不到 update_quotation 的 _LOCKED"
    assert tuple(re.findall(r'"([^"]+)"', m.group(1))) == QS.EDIT_LOCKED_STATUSES


def test_status_changing_during_upload_rolls_the_files_back(client, world, monkeypatch):
    """上傳途中報價單被送審（狀態在存檔後、寫鎖內重驗）⇒ 403、剛存的檔收回、清單不變。"""
    real = QS.save_document_files

    async def _save_then_lock(*a, **k):
        out = await real(*a, **k)
        _x("UPDATE quotations SET status='待審核' WHERE quote_no=?", (Q,))
        return out

    monkeypatch.setattr(QS, "save_document_files", _save_then_lock)
    r = _up(client, world["sp_owner"], [("a.pdf", _pdf(1))])
    assert r.status_code == 403, r.text
    assert _specs() == []
    d = os.path.join(UP.UPLOADS_ROOT, "quotation_specs", Q)
    assert not os.path.isdir(d) or os.listdir(d) == []


def test_outsider_and_viewer_get_404_admin_allowed(client, world):
    assert _up(client, world["sp_viewer"], [("a.pdf", _pdf(1))]).status_code in (403, 404)
    assert _up(client, world["sp_outsider"], [("a.pdf", _pdf(1))]).status_code == 404
    assert _up(client, world["sp_admin"], [("a.pdf", _pdf(1))]).status_code == 200
    assert client.delete("/api/quotations/%s/spec-files/%s" % (Q, _specs()[0]["id"]), headers=world["sp_outsider"]).status_code == 404
    assert len(_specs()) == 1


def test_unknown_quote_is_404(client, world):
    assert _up(client, world["sp_admin"], [("a.pdf", _pdf(1))], no="MQ-NOPE").status_code == 404


# ── ③ 刪除 ────────────────────────────────────────────────────────────────────

def _seed_two(client, world):
    j = _up(client, world["sp_owner"], [("a.pdf", _pdf(1)), ("b.pdf", _pdf(2))]).json()
    ids = [f["id"] for f in j["specFiles"]]
    _set_merge(ids)
    return ids


def test_delete_removes_file_list_entry_and_merge_id_together(client, world):
    a, b = _seed_two(client, world)
    ent = {f["id"]: f for f in _specs()}
    r = client.delete("/api/quotations/%s/spec-files/%s" % (Q, a), headers=world["sp_owner"])
    assert r.status_code == 200, r.text
    assert [f["id"] for f in r.json()["specFiles"]] == [b] and r.json()["mergeFiles"] == [b]
    assert not os.path.exists(_abs(ent[a])) and os.path.exists(_abs(ent[b]))
    assert _data()["mergeFiles"] == [b] and [f["id"] for f in _specs()] == [b]


def test_deleting_the_last_selected_file_removes_the_merge_key(client, world):
    j = _up(client, world["sp_owner"], [("a.pdf", _pdf(1))]).json()
    fid = j["specFiles"][0]["id"]
    _set_merge([fid])
    r = client.delete("/api/quotations/%s/spec-files/%s" % (Q, fid), headers=world["sp_owner"])
    assert r.json() == {"specFiles": [], "staged": [], "mergeFiles": []}
    assert "mergeFiles" not in _data()                                             # 沒選＝不存這個鍵（不是空陣列）


def test_delete_keeps_updated_at(client, world):
    a, _b = _seed_two(client, world)
    before = _q("SELECT updated_at FROM quotations WHERE quote_no=?", (Q,))[0]["updated_at"]
    client.delete("/api/quotations/%s/spec-files/%s" % (Q, a), headers=world["sp_owner"])
    assert _q("SELECT updated_at FROM quotations WHERE quote_no=?", (Q,))[0]["updated_at"] == before


def test_delete_failure_rolls_back_list_merge_ids_and_file(client, world, monkeypatch):
    """風險 4：刪檔＋清單＋mergeFiles 同一個寫交易——mergeFiles 那一步失敗 ⇒ 三者都在、實體檔也在。"""
    a, b = _seed_two(client, world)
    ent = {f["id"]: f for f in _specs()}
    import modules.case.quotations as MQ

    def boom(*a_, **k):
        raise RuntimeError("simulated failure while rewriting data_json")

    monkeypatch.setattr(MQ, "save_quotation_json", boom)
    with pytest.raises(RuntimeError):
        client.delete("/api/quotations/%s/spec-files/%s" % (Q, a), headers=world["sp_owner"])
    assert [f["id"] for f in _specs()] == [a, b]
    assert _data()["mergeFiles"] == [a, b]
    assert os.path.exists(_abs(ent[a]))


def test_delete_unknown_id_404_and_other_quotes_id_not_reachable(client, world):
    _quote("MQ-SP-002")
    other = _up(client, world["sp_owner"], [("o.pdf", _pdf(1))], no="MQ-SP-002").json()["specFiles"][0]["id"]
    assert client.delete("/api/quotations/%s/spec-files/%s" % (Q, other), headers=world["sp_owner"]).status_code == 404
    assert len(_specs("MQ-SP-002")) == 1


def test_delete_with_tampered_path_is_409_and_touches_nothing(client, world):
    fid = _up(client, world["sp_owner"], [("a.pdf", _pdf(1))]).json()["specFiles"][0]["id"]
    ent = _specs()[0]
    victim = os.path.join(UP.UPLOADS_ROOT, "quotation_specs", "MQ-SP-OTHER")
    os.makedirs(victim, exist_ok=True)
    vf = os.path.join(victim, "keep.pdf")
    open(vf, "wb").write(_pdf(1))
    ent["path"] = "quotation_specs/MQ-SP-OTHER/keep.pdf"                           # 資料被竄改：指到別張單的檔
    _x("UPDATE quotations SET spec_files_json=? WHERE quote_no=?", (json.dumps([ent]), Q))
    r = client.delete("/api/quotations/%s/spec-files/%s" % (Q, fid), headers=world["sp_owner"])
    assert r.status_code == 409 and os.path.exists(vf) and len(_specs()) == 1


def test_delete_blocked_when_quote_is_locked(client, world):
    fid = _up(client, world["sp_owner"], [("a.pdf", _pdf(1))]).json()["specFiles"][0]["id"]
    _x("UPDATE quotations SET status='已送出' WHERE quote_no=?", (Q,))
    assert client.delete("/api/quotations/%s/spec-files/%s" % (Q, fid), headers=world["sp_owner"]).status_code == 403
    assert len(_specs()) == 1


# ── ④ validate_merge_files ────────────────────────────────────────────────────

SPECS = [{"id": "a"}, {"id": "b"}, {"id": "c"}]


def test_validate_merge_files_cleans_in_order():
    assert QS.validate_merge_files(["c", "x", "a", "c", "a"], SPECS) == ["c", "a"]       # 未知 id 靜默丟、重複只留第一個、保序
    assert QS.validate_merge_files([], SPECS) == []
    assert QS.validate_merge_files(["a"], json.dumps(SPECS)) == ["a"]                  # 也收 spec_files_json 字串
    assert QS.validate_merge_files(["a"], "not json") == []


@pytest.mark.parametrize("bad", [None, "a", {"a": 1}, 5, ["a", 1], ["a", None], [["a"]], ["x%d" % i for i in range(11)]])
def test_validate_merge_files_rejects_malformed_with_400(bad):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        QS.validate_merge_files(bad, SPECS)
    assert e.value.status_code == 400


# ── ⑤ merge_for_download ──────────────────────────────────────────────────────

def _row(no=Q):
    return _q("SELECT quote_no, data_json, spec_files_json FROM quotations WHERE quote_no=?", (no,))[0]


def test_merge_for_download_without_merge_files_is_byte_identical(client, world):
    _up(client, world["sp_owner"], [("a.pdf", _pdf(2))])
    body = _pdf(1)
    out, sk = QS.merge_for_download(_row(), body)
    assert out is body and sk == []                                                # 有檔案但沒選 ⇒ 不動


def test_merge_for_download_merges_in_merge_files_order_and_reports_skips(client, world):
    j = _up(client, world["sp_owner"], [("a.pdf", _pdf(1)), ("b.pdf", _pdf(2)), ("e.pdf", _pdf(1, encrypt=True)), ("c.pdf", _pdf(3))]).json()
    ids = {f["name"]: f["id"] for f in j["specFiles"]}
    os.remove(_abs(next(s for s in _specs() if s["name"] == "c.pdf")))              # 清單有、磁碟沒有
    _set_merge([ids["b.pdf"], ids["e.pdf"], ids["c.pdf"], ids["a.pdf"], "ghost"])
    out, sk = QS.merge_for_download(_row(), _pdf(1))
    assert _npages(out) == 1 + 2 + 1
    assert sk == [{"id": ids["e.pdf"], "name": "e.pdf", "reason": "encrypted"}, {"id": ids["c.pdf"], "name": "c.pdf", "reason": "missing"}]


def test_merge_for_download_never_opens_non_ok_status_files(client, world, monkeypatch):
    j = _up(client, world["sp_owner"], [("e.pdf", _pdf(1, encrypt=True))]).json()
    _set_merge([j["specFiles"][0]["id"]])
    import modules.case.pdf_merge as PM

    def _no(*a, **k):
        raise AssertionError("不該再去開狀態非 ok 的檔")

    monkeypatch.setattr(PM, "probe_pdf", _no)
    out, sk = QS.merge_for_download(_row(), _pdf(1))
    assert _npages(out) == 1 and [s["reason"] for s in sk] == ["encrypted"]


def test_path_pointing_outside_own_folder_is_missing_not_merged(client, world):
    fid = _up(client, world["sp_owner"], [("a.pdf", _pdf(1))]).json()["specFiles"][0]["id"]
    ent = _specs()[0]
    ent["path"] = "quotations/MQ-OTHER/x.pdf"
    _x("UPDATE quotations SET spec_files_json=? WHERE quote_no=?", (json.dumps([ent]), Q))
    _set_merge([fid])
    out, sk = QS.merge_for_download(_row(), _pdf(1))
    assert _npages(out) == 1 and sk[0]["reason"] == "missing"


# ── ⑥ 下載端點與存檔版 ───────────────────────────────────────────────────────

def test_pdf_download_merges_and_sets_skipped_header_only_when_needed(client, world, monkeypatch):
    import modules.case.api.quotations as QA
    monkeypatch.setattr(QA, "generate_pdf_bytes", lambda no, internal=False: _pdf(1))
    j = _up(client, world["sp_owner"], [("a.pdf", _pdf(2)), ("e.pdf", _pdf(1, encrypt=True))]).json()
    ids = {f["name"]: f["id"] for f in j["specFiles"]}
    url = "/api/quotations/%s/pdf-download" % Q
    r = client.get(url, headers=world["sp_owner"])                                  # 沒選
    assert r.status_code == 200 and _npages(r.content) == 1 and "X-Pdf-Merge-Skipped" not in r.headers
    _set_merge([ids["a.pdf"]])
    r = client.get(url, headers=world["sp_owner"])                                  # 全併入
    assert _npages(r.content) == 3 and "X-Pdf-Merge-Skipped" not in r.headers
    _set_merge([ids["a.pdf"], ids["e.pdf"]])
    r = client.get(url, headers=world["sp_owner"])                                  # 有略過
    assert _npages(r.content) == 3
    assert json.loads(unquote(r.headers["X-Pdf-Merge-Skipped"])) == [{"id": ids["e.pdf"], "name": "e.pdf", "reason": "encrypted"}]
    text = "".join((p.extract_text() or "") for p in pypdf.PdfReader(io.BytesIO(r.content)).pages)
    assert "encrypted" not in text and "e.pdf" not in text                           # 原因不印在客戶的 PDF 上
    det = json.loads(_q("SELECT detail FROM audit_log WHERE action='quotation.export_pdf' AND target_id=? ORDER BY id DESC LIMIT 1", (Q,))[0]["detail"])
    assert det["mergeSkipped"] == [{"name": "e.pdf", "reason": "encrypted"}]


def test_pdf_download_survives_unexpected_merge_error(client, world, monkeypatch):
    """附件問題不可以讓報價單下載失敗：合併丟出非預期例外 ⇒ 回本體、200。"""
    import modules.case.api.quotations as QA
    monkeypatch.setattr(QA, "generate_pdf_bytes", lambda no, internal=False: _pdf(1))
    fid = _up(client, world["sp_owner"], [("a.pdf", _pdf(2))]).json()["specFiles"][0]["id"]
    _set_merge([fid])
    import modules.case.pdf_merge as PM
    monkeypatch.setattr(PM, "merge_pdf_bytes", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bug")))
    r = client.get("/api/quotations/%s/pdf-download" % Q, headers=world["sp_owner"])
    assert r.status_code == 200 and _npages(r.content) == 1


def test_archived_version_gets_merged_in_place_and_records_merge_skipped(client, world, tmp_path, monkeypatch):
    import pdf_gen
    monkeypatch.setattr(pdf_gen, "_get_pdf_base", lambda: str(tmp_path))
    j = _up(client, world["sp_owner"], [("a.pdf", _pdf(2)), ("e.pdf", _pdf(1, encrypt=True))]).json()
    ids = {f["name"]: f["id"] for f in j["specFiles"]}
    _set_merge([ids["a.pdf"], ids["e.pdf"]])
    day = tmp_path / "2026-11-17"
    day.mkdir()
    pdf = day / "v1.pdf"
    pdf.write_bytes(_pdf(1))
    pdf_gen._record_doc_version(Q, "已簽核", "某人", str(pdf))
    v = _data()["docVersions"][-1]
    assert _npages(pdf.read_bytes()) == 3 and v["size"] == len(pdf.read_bytes())
    assert v["mergeSkipped"] == [{"id": ids["e.pdf"], "name": "e.pdf", "reason": "encrypted"}]
    # 沒略過 ⇒ 沒有 mergeSkipped 這個鍵
    _set_merge([ids["a.pdf"]])
    pdf2 = day / "v2.pdf"
    pdf2.write_bytes(_pdf(1))
    pdf_gen._record_doc_version(Q, "修改", "某人", str(pdf2))
    v2 = _data()["docVersions"][-1]
    assert _npages(pdf2.read_bytes()) == 3 and "mergeSkipped" not in v2


def test_archived_version_without_merge_files_is_untouched(client, world, tmp_path, monkeypatch):
    import pdf_gen
    monkeypatch.setattr(pdf_gen, "_get_pdf_base", lambda: str(tmp_path))
    _up(client, world["sp_owner"], [("a.pdf", _pdf(2))])
    pdf = tmp_path / "x.pdf"
    raw = b"%PDF-1.4 not parseable but must stay byte-identical"
    pdf.write_bytes(raw)
    pdf_gen._record_doc_version(Q, "建立", "某人", str(pdf))
    assert pdf.read_bytes() == raw and "mergeSkipped" not in _data()["docVersions"][-1]


def test_archived_merge_failure_leaves_original_file_and_still_records_version(client, world, tmp_path, monkeypatch):
    import pdf_gen
    monkeypatch.setattr(pdf_gen, "_get_pdf_base", lambda: str(tmp_path))
    fid = _up(client, world["sp_owner"], [("a.pdf", _pdf(2))]).json()["specFiles"][0]["id"]
    _set_merge([fid])
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(_pdf(1))
    import modules.case.pdf_merge as PM
    monkeypatch.setattr(PM, "merge_pdf_bytes", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bug")))
    pdf_gen._record_doc_version(Q, "建立", "某人", str(pdf))
    assert _npages(pdf.read_bytes()) == 1 and len(_data()["docVersions"]) == 1
    assert not [p for p in os.listdir(tmp_path) if p.endswith(".tmp")]


# ── ⑦ 單筆 GET ────────────────────────────────────────────────────────────────

def test_single_get_has_spec_files_without_paths_and_without_raw_column(client, world):
    _up(client, world["sp_owner"], [("a.pdf", _pdf(2))])
    r = client.get("/api/quotations/%s" % Q, headers=world["sp_owner"])
    assert r.status_code == 200
    j = r.json()
    assert "spec_files_json" not in j
    assert len(j["specFiles"]) == 1 and "path" not in j["specFiles"][0] and j["specFiles"][0]["pages"] == 2
    assert "uploads" not in json.dumps(j["specFiles"]) and "quotation_specs" not in json.dumps(j["specFiles"])


# ── ⑧ 登記守門（風險 5）──────────────────────────────────────────────────────

def test_folder_is_registered_for_limits_read_rule_catalog_and_recycle():
    from modules.case import attachments as A
    assert UP.UPLOAD_LIMITS_BY_SUBFOLDER["quotation_specs"] == {"max_files": 10, "max_request_bytes": 50 * 1024 * 1024}
    assert UP.limits_for("quotation_specs")["max_files"] == 10
    assert "quotation_specs" in A._CasePathAccess.FOLDERS and A._CasePathAccess._FOLDER_SOURCE["quotation_specs"] == "quotation_spec"
    assert "quotation_spec" in A._CaseCatalog.CATEGORIES
    assert "quotation_spec" not in A._CaseAttachments.SOURCE_TYPES               # 傳票可帶入的白名單：規格 PDF 不是傳票佐證，只進檔案目錄
    assert A._CATALOG_FOLDER["quotation_spec"] == "quotation_specs" and A._READ_RULE["quotation_spec"] is A.case_page_readable
    assert A._CaseCatalog.CATEGORIES["quotation_spec"]["label"] == "報價單規格文件"
    import inspect
    from modules.case import recycle_adapter as RA
    src = inspect.getsource(RA.QuotationAdapter)
    assert src.count("spec_files_json") >= 2                                         # 進回收筒（搬檔）與還原（換路徑）都認得它


def test_path_access_follows_case_readability(client, world):
    from modules.case import attachments as A
    ent = _up(client, world["sp_owner"], [("a.pdf", _pdf(1))]) and _specs()[0]
    folder, no, fname = ent["path"].split("/")
    c = db.get_db()
    try:
        def can(username):
            u = dict(c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone())
            u["modules"] = json.loads(u.get("modules") or "[]") if isinstance(u.get("modules"), str) else u.get("modules")
            return A._CasePathAccess.readable(c, folder, [no, fname], u)
        assert can("sp_owner") and can("sp_admin")
        assert not can("sp_outsider")
        assert not A._CasePathAccess.readable(c, folder, ["MQ-NOPE", fname], {"username": "sp_admin", "role": "admin"})
    finally:
        c.close()


def test_catalog_opens_the_file_for_owner_and_hides_from_outsider(client, world):
    ent = _up(client, world["sp_owner"], [("規格書.pdf", _pdf(1))]) and _specs()[0]
    from modules.case import attachments as A
    c = db.get_db()
    try:
        def user(name):
            return dict(c.execute("SELECT * FROM users WHERE username=?", (name,)).fetchone())
        got = A._CaseCatalog.open(c, user("sp_owner"), "quotation_spec", Q, ent["id"])
        assert got is not None and got.filename == "規格書.pdf" and got.mime == "application/pdf" and os.path.isfile(got.abs_path)
        with pytest.raises(UP.AttachmentNotVisible):
            A._CaseCatalog.open(c, user("sp_outsider"), "quotation_spec", Q, ent["id"])
        assert A._CaseCatalog.open(c, user("sp_owner"), "quotation_spec", "MQ-NOPE", ent["id"]) is None
        ent2 = dict(ent, path="quotations/%s/x.pdf" % Q)                               # 路徑不屬於自己的資料夾 ⇒ 當作沒有
        assert not A._path_bound_to_doc(c, "quotation_spec", Q, ent2)
        assert A._path_bound_to_doc(c, "quotation_spec", Q, ent)
    finally:
        c.close()


def test_router_is_registered_with_both_endpoints(client):
    spec = client.app.openapi()["paths"]                                            # 與 route_table_golden 同一個列舉法（路由在子 app 內，app.routes 看不到）
    assert "post" in spec["/api/quotations/{quote_no}/spec-files"]
    assert "delete" in spec["/api/quotations/{quote_no}/spec-files/{file_id}"]


# ── ⑨ migration 0013 ─────────────────────────────────────────────────────────

def _m13():
    import importlib
    return importlib.import_module("modules.case.migrations.0013_quote_spec_files")


def test_migration_0013_adds_column_idempotently_with_default():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE quotations (id INTEGER PRIMARY KEY, quote_no TEXT)")
    c.execute("INSERT INTO quotations (quote_no) VALUES ('A')")
    assert _m13().up(c) is None and _m13().up(c) is None
    cols = {r[1]: r for r in c.execute("PRAGMA table_info(quotations)")}
    assert cols["spec_files_json"][2] == "TEXT" and cols["spec_files_json"][3] == 1 and cols["spec_files_json"][4] == "'[]'"
    assert c.execute("SELECT spec_files_json FROM quotations").fetchone()[0] == "[]"          # 既有列回填
    c.execute("INSERT INTO quotations (quote_no) VALUES ('B')")                              # 舊程式 INSERT 不帶它也成立
    assert c.execute("SELECT spec_files_json FROM quotations WHERE quote_no='B'").fetchone()[0] == "[]"


def test_migration_0013_without_table_returns_reason_instead_of_raising():
    assert isinstance(_m13().up(sqlite3.connect(":memory:")), str)


def test_real_database_has_the_column(client):
    cols = {r["name"]: r for r in _q("PRAGMA table_info(quotations)")}
    assert "spec_files_json" in cols and cols["spec_files_json"]["notnull"] == 1
