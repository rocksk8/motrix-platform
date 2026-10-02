# -*- coding: utf-8 -*-
"""報價單「客戶回簽單」上傳（第 29 班新增，使用者：「報價單成案要能上傳客戶報價回簽單」）。

端點＝既有的 `POST/DELETE /api/quotations/{no}/signed-files`（`modules/case/api/quotations.py`），本批只補規則：
- 狀態閘：報價單「已送出」（完成簽核）之後才能上傳；草稿／待審核／簽核中／已退回／已作廢 ⇒ 400（不是 200 後靜默丟檔），並寫稽核。
  成案、已結案、成案撤回都不改報價單狀態 ⇒ 仍可補傳，既有檔不動。
- 權限矩陣：業務／協作者／admin+ 可傳可看；外人（有報價單模組但不是該案成員）與唯讀角色 ⇒ 404（看不到＝不存在）。
- 刪除（行為變更）：上傳者本人或 admin+；沒有 `uploaderUsername` 的舊檔只有 admin+；找不到 id ⇒ 404；路徑被竄改 ⇒ 409 且不碰磁碟。
- 路徑：實體檔名由伺服器產生（不沿用使用者檔名）、一律落在 uploads 之內；類型 pdf／jpg／png；大小上限同其他附件。
- 檔案中心（P3 提供者 quotation_signed）可見性＝案件可見性：外人搜不到、打不開；刪除後立刻消失。
- 稽核：上傳／刪除／被擋各一筆，內容有檔名、不含伺服器絕對路徑。
"""
import json
import os

import pytest

import db
import helpers.uploads as UP

# conftest 一般把檔頭檢查換成「一律符合」（既有題用假內容）；本檔都是真檔頭，並要驗偽裝（內容是 exe、副檔名 pdf）被擋 ⇒ 用真的檢查
pytestmark = pytest.mark.upload_magic

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
Q = "MQ-SB-001"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _x(sql, args=()):
    c = db.get_db()
    try:
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid
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


def _quote(no, status="已送出", deal="已成案", owner=None, collabs=()):
    _x("INSERT OR REPLACE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, sales_person_id, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
       (no, status, "客戶", "工程", 1000, 952, json.dumps({"dealTag": deal}), "2026-01-01T00:00:00", "2026-01-01T00:00:00", deal,
        _uid(owner) if owner else None, owner or "", json.dumps([_uid(c) for c in collabs])))


@pytest.fixture
def world(client, make_user):
    H = {}
    for name, role, mods in (("sb_owner", "sales", ["quotation"]), ("sb_collab", "sales", ["quotation"]), ("sb_admin", "admin", None),
                             ("sb_outsider", "sales", ["quotation", "case_manage"]), ("sb_viewer", "viewer", [])):
        u, p = make_user(username=name, role=role, modules=mods)
        H[name] = _login(client, u, p)
    _quote(Q, owner="sb_owner", collabs=("sb_collab",))
    return H


def _up(client, h, no=Q, name="back.png", data=PNG, mime="image/png", extra=()):
    return client.post("/api/quotations/%s/signed-files" % no, headers=h, files=[("files", (name, data, mime)), *extra])


def _files(no=Q):
    return json.loads(_q("SELECT signed_files_json FROM quotations WHERE quote_no=?", (no,))[0]["signed_files_json"] or "[]")


def _audits(action):
    return _q("SELECT username, target_id, detail FROM audit_log WHERE action=? ORDER BY id", (action,))


# ── 狀態閘 ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["草稿", "待審核", "簽核中", "已退回", "已作廢"])
def test_upload_before_the_quote_is_sent_is_refused_and_audited(client, world, status):
    _quote("MQ-SB-%s" % abs(hash(status)), status=status, deal="", owner="sb_owner")
    no = "MQ-SB-%s" % abs(hash(status))
    r = _up(client, world["sb_owner"], no)
    assert r.status_code == 400 and "已送出" in r.json()["detail"], (status, r.status_code, r.text)
    assert _files(no) == []                                                      # 沒有靜默丟檔、也沒有半寫入
    assert [a for a in _audits("quotation.upload_signed_files_denied") if a["target_id"] == no]


@pytest.mark.parametrize("deal", ["已成案", "已結案", "未成案", "已提供", ""])
def test_sent_quote_accepts_upload_whatever_the_deal_tag(client, world, deal):
    """成案前（客戶剛簽回）、成案、已結案、成案撤回後都可傳——閘門是報價單狀態，不是成案標籤。"""
    no = "MQ-SB-D%d" % abs(hash(deal))
    _quote(no, status="已送出", deal=deal, owner="sb_owner")
    r = _up(client, world["sb_owner"], no)
    assert r.status_code == 201 and r.json()["added"] == 1, (deal, r.text)


def test_reverting_the_deal_tag_keeps_the_files_and_still_allows_upload(client, world):
    assert _up(client, world["sb_owner"]).status_code == 201
    _x("UPDATE quotations SET deal_tag='未成案' WHERE quote_no=?", (Q,))            # 成案撤回
    assert len(_files()) == 1                                                       # 既有檔不消失
    assert _up(client, world["sb_collab"], name="again.pdf", data=PDF, mime="application/pdf").status_code == 201
    assert len(_files()) == 2


def test_the_state_gate_is_what_blocks_drafts(client, world, monkeypatch):
    """反向控制：把閘門放寬到含「草稿」⇒ 草稿就傳得進去（證明上面的 400 真的是這道閘門擋的）。"""
    import modules.case.api.quotations as QA
    _quote("MQ-SB-GATE", status="草稿", deal="", owner="sb_owner")
    assert _up(client, world["sb_owner"], "MQ-SB-GATE").status_code == 400
    monkeypatch.setattr(QA, "SIGNED_BACK_STATUSES", ("已送出", "草稿"))
    assert _up(client, world["sb_owner"], "MQ-SB-GATE").status_code == 201


# ── 權限矩陣 ────────────────────────────────────────────────────────────────

def test_permission_matrix_upload_and_list(client, world):
    ok = {"sb_owner": 201, "sb_collab": 201, "sb_admin": 201, "sb_outsider": 404, "sb_viewer": 404}
    for who, code in ok.items():
        r = _up(client, world[who], name="by-%s.png" % who)
        assert r.status_code == code, (who, r.status_code, r.text)
    assert client.post("/api/quotations/%s/signed-files" % Q, files=[("files", ("x.png", PNG, "image/png"))]).status_code == 401
    names = {f["filename"] for f in _files()}
    assert names == {"by-sb_owner.png", "by-sb_collab.png", "by-sb_admin.png"}        # 外人／唯讀的一個都沒進去
    for who in ("sb_owner", "sb_collab", "sb_admin"):
        got = client.get("/api/quotations/%s" % Q, headers=world[who])
        assert got.status_code == 200 and len(got.json()["signed_files"]) == 3, who
    for who in ("sb_outsider", "sb_viewer"):                                         # 外人連列表都看不到（看不到＝不存在）
        assert client.get("/api/quotations/%s" % Q, headers=world[who]).status_code == 404, who
    assert client.get("/api/quotations/MQ-NOPE", headers=world["sb_outsider"]).status_code == 404       # 與「不存在」同一個答案


def test_each_file_records_uploader_and_time(client, world):
    f = _up(client, world["sb_owner"]).json()["files"][0]
    assert f["uploaderUsername"] == "sb_owner" and f["uploadedBy"] and f["uploadedAt"] and "path" in f


# ── 刪除 ────────────────────────────────────────────────────────────────────

def _disk(f):
    return os.path.join(UP.UPLOADS_ROOT, *f["path"].split("/"))


def test_delete_rules_uploader_or_admin_and_physical_removal(client, world):
    mine = _up(client, world["sb_owner"], name="o.png").json()["files"][0]
    theirs = _up(client, world["sb_admin"], name="a.png").json()["files"][0]
    collab = _up(client, world["sb_collab"], name="c.png").json()["files"][0]
    url = lambda f: "/api/quotations/%s/signed-files/%s" % (Q, f["id"])
    assert client.delete(url(theirs), headers=world["sb_owner"]).status_code == 403          # 擁有者刪不了別人（admin）上傳的
    assert client.delete(url(mine), headers=world["sb_collab"]).status_code == 403           # 協作者刪不了別人的
    assert client.delete(url(mine), headers=world["sb_outsider"]).status_code == 404         # 外人：看不到＝不存在
    assert client.delete(url(mine), headers=world["sb_viewer"]).status_code == 404
    assert client.delete(url(mine)).status_code == 401
    assert os.path.isfile(_disk(mine)) and len(_files()) == 3                                # 被擋的一個都沒刪
    assert client.delete(url(mine), headers=world["sb_owner"]).status_code == 200            # 上傳者本人
    assert not os.path.exists(_disk(mine)) and mine["id"] not in {f["id"] for f in _files()}  # 檔＋清單列一起消失
    assert client.delete(url(collab), headers=world["sb_admin"]).status_code == 200          # admin 刪別人的
    assert not os.path.exists(_disk(collab))
    assert client.delete(url(mine), headers=world["sb_owner"]).status_code == 404            # 刪不存在的 id
    assert client.delete("/api/quotations/%s/signed-files/%s" % (Q, "x" * 8), headers=world["sb_admin"]).status_code == 404
    assert [a for a in _audits("quotation.delete_signed_file")]                              # 刪除寫稽核
    assert [a for a in _audits("quotation.delete_signed_file_denied")]                       # 被擋也可查


def test_legacy_file_without_uploader_can_only_be_deleted_by_admin(client, world):
    f = _up(client, world["sb_owner"], name="old.png").json()["files"][0]
    legacy = dict(f)
    legacy.pop("uploaderUsername")
    _x("UPDATE quotations SET signed_files_json=? WHERE quote_no=?", (json.dumps([legacy]), Q))
    url = "/api/quotations/%s/signed-files/%s" % (Q, f["id"])
    assert client.delete(url, headers=world["sb_owner"]).status_code == 403
    assert client.delete(url, headers=world["sb_admin"]).status_code == 200


def test_delete_is_not_loose_reverse_control(client, world, monkeypatch):
    """反向控制：把刪除規則換成舊的「看得到就能刪」⇒ 協作者就刪得掉擁有者的檔（證明上面的 403 是這條規則擋的）。"""
    import modules.case.api.quotations as QA
    f = _up(client, world["sb_owner"]).json()["files"][0]
    url = "/api/quotations/%s/signed-files/%s" % (Q, f["id"])
    assert client.delete(url, headers=world["sb_collab"]).status_code == 403
    real = QA._require_user
    monkeypatch.setattr(QA, "_require_user", lambda auth: dict(real(auth), role="admin"))     # 模擬規則被放寬成 admin
    assert client.delete(url, headers=world["sb_collab"]).status_code == 200


def test_tampered_path_is_refused_and_nothing_outside_is_touched(client, world, tmp_path):
    f = _up(client, world["sb_owner"]).json()["files"][0]
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    bad = dict(f, path=str(victim))                                                         # 清單被竄改：路徑指到 uploads 外
    _x("UPDATE quotations SET signed_files_json=? WHERE quote_no=?", (json.dumps([bad]), Q))
    r = client.delete("/api/quotations/%s/signed-files/%s" % (Q, f["id"]), headers=world["sb_admin"])
    assert r.status_code == 409 and victim.exists() and len(_files()) == 1                  # 不碰磁碟、清單也不動
    other = dict(f, path="quotations/MQ-OTHER-9/zz.png")                                     # 指到別張報價單的資料夾
    _x("UPDATE quotations SET signed_files_json=? WHERE quote_no=?", (json.dumps([other]), Q))
    assert client.delete("/api/quotations/%s/signed-files/%s" % (Q, f["id"]), headers=world["sb_admin"]).status_code == 409


# ── 檔名／類型／大小 ─────────────────────────────────────────────────────────

def test_hostile_filenames_cannot_leave_the_quotation_folder(client, world, tmp_path):
    root = os.path.realpath(UP.UPLOADS_ROOT)
    for name in ("../../x.png", "..\\..\\x.png", "C:\\x.png", "\\\\host\\share\\x.png", "a.png:evil", "CON.png", "a" * 300 + ".png"):
        r = _up(client, world["sb_owner"], name=name)
        if r.status_code == 201:
            f = r.json()["files"][0]
            real = os.path.realpath(_disk(f))
            assert os.path.commonpath([root, real]) == root, name                            # 一定在 uploads 之內
            assert f["path"].startswith("quotations/%s/" % Q) and ".." not in f["path"] and ":" not in f["path"], (name, f["path"])
        else:
            assert 400 <= r.status_code < 500, (name, r.status_code)
    assert not (tmp_path / "x.png").exists()


@pytest.mark.parametrize("name,data,mime", [("a.exe", b"MZ" + b"0" * 64, "application/octet-stream"), ("a.html", b"<script>1</script>", "text/html"),
                                             ("a.svg", b"<svg onload=1/>", "image/svg+xml"), ("a.pdf.exe", PDF, "application/pdf"),
                                             ("fake.pdf", b"MZ" + b"0" * 64, "application/pdf"), ("empty.pdf", b"", "application/pdf")])
def test_disallowed_types_are_refused(client, world, name, data, mime):
    r = _up(client, world["sb_owner"], name=name, data=data, mime=mime)
    assert 400 <= r.status_code < 500, (name, r.status_code, r.text)
    assert _files() == []
    assert "uploads" not in r.text and UP.UPLOADS_ROOT not in r.text                        # 回應不洩露伺服器路徑


def test_allowed_types_and_multi_file_upload(client, world):
    r = client.post("/api/quotations/%s/signed-files" % Q, headers=world["sb_owner"],
                    files=[("files", ("a.png", PNG, "image/png")), ("files", ("b.pdf", PDF, "application/pdf")), ("files", ("c.jpg", b"\xff\xd8\xff\xe0" + b"0" * 64, "image/jpeg"))])
    assert r.status_code == 201 and r.json()["added"] == 3
    assert {f["filename"] for f in _files()} == {"a.png", "b.pdf", "c.jpg"}


def test_size_cap_same_as_other_attachments(client, world):
    cap = getattr(UP, "MAX_UPLOAD_BYTES", None) or getattr(UP, "MAX_FILE_BYTES", None) or 20 * 1024 * 1024
    ok = _up(client, world["sb_owner"], name="edge.pdf", data=PDF + b"0" * (cap - len(PDF)), mime="application/pdf")
    over = _up(client, world["sb_owner"], name="over.pdf", data=PDF + b"0" * (cap - len(PDF) + 1), mime="application/pdf")
    assert ok.status_code == 201, ok.text[:200]
    assert 400 <= over.status_code < 500 and len(_files()) == 1, over.status_code


# ── 稽核 ────────────────────────────────────────────────────────────────────

def test_audit_has_names_and_no_server_paths(client, world):
    f = _up(client, world["sb_owner"], name="客戶簽回.png").json()["files"][0]
    client.delete("/api/quotations/%s/signed-files/%s" % (Q, f["id"]), headers=world["sb_owner"])
    up, dl = _audits("quotation.upload_signed_files"), _audits("quotation.delete_signed_file")
    assert up and dl and up[-1]["target_id"] == Q and "客戶簽回.png" in up[-1]["detail"] + json.dumps(up[-1]) + _q("SELECT target_label FROM audit_log WHERE action='quotation.upload_signed_files'")[-1]["target_label"]
    blob = json.dumps(up + dl, ensure_ascii=False)
    assert UP.UPLOADS_ROOT not in blob and f["path"] not in blob


# ── 檔案中心（P3）可見性 ─────────────────────────────────────────────────────

def test_file_center_follows_case_visibility_and_forgets_deleted_files(client, world):
    f = _up(client, world["sb_owner"], name="fc-signed.png").json()["files"][0]
    search = lambda who: client.get("/api/filehub/search", headers=world[who], params={"quote_no": Q, "types": "quotation_signed", "size": 50})
    for who in ("sb_owner", "sb_collab", "sb_admin"):
        body = search(who).json()
        assert [i["filename"] for i in body["items"]] == ["fc-signed.png"], who
        assert body["items"][0]["sourceType"] == "quotation_signed" and "path" not in body["items"][0]
        assert client.get("/api/attachments/open", headers=world[who], params={"type": "quotation_signed", "doc": Q, "file": f["id"]}).status_code == 200
    for who in ("sb_outsider", "sb_viewer"):                                          # 外人：搜不到、計數 0、打不開
        r = search(who)
        assert r.status_code == 200
        assert r.json()["items"] == [] and not r.json()["facets"]["byType"].get("quotation_signed", 0), who
        assert "fc-signed.png" not in r.text
        assert client.get("/api/attachments/open", headers=world[who], params={"type": "quotation_signed", "doc": Q, "file": f["id"]}).status_code == 404
    assert client.delete("/api/quotations/%s/signed-files/%s" % (Q, f["id"]), headers=world["sb_admin"]).status_code == 200
    assert search("sb_owner").json()["items"] == []                                    # 刪除後立刻消失
    assert client.get("/api/attachments/open", headers=world["sb_admin"], params={"type": "quotation_signed", "doc": Q, "file": f["id"]}).status_code == 404


def test_r3_uploader_identity_is_the_username_not_the_display_name(client, world):
    """稽核 R-3：刪除規則比對的是帳號（uploaderUsername），顯示名可以重複或被改——兩個人顯示名相同也不能互刪；上傳者改名後仍能刪自己的。"""
    _x("UPDATE users SET display_name='王小明' WHERE username IN ('sb_owner','sb_collab')")           # 兩個不同帳號、同一個顯示名
    f = _up(client, world["sb_owner"], name="r3.png").json()["files"][0]
    assert f["uploadedBy"] == "王小明" and f["uploaderUsername"] == "sb_owner"
    url = "/api/quotations/%s/signed-files/%s" % (Q, f["id"])
    assert client.delete(url, headers=world["sb_collab"]).status_code == 403                        # 顯示名相同但不是上傳者 ⇒ 擋
    assert len(_files()) == 1
    _x("UPDATE users SET display_name='王大明' WHERE username='sb_owner'")                           # 上傳者之後改名
    assert client.delete(url, headers=world["sb_owner"]).status_code == 200                         # 顯示名變了仍認得（比對帳號）
    assert _files() == []
