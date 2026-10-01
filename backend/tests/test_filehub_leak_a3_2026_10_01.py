# -*- coding: utf-8 -*-
"""檔案中心 P3 的洩漏守門（讀取路徑 ＝ 洩漏風險；主持 2026-10-01 的四個條件）：

① 每個提供者的 `search()`／`count()` 與 `open()` 用同一道可讀規則，**含路徑綁單據**（`upload_path_key`）：
   塞進別張單據資料夾的路徑（W3 的攻擊面）打不開，也不會被列出來。
② 反向題：沒模組／不是案件擁有者／只有別的財務模組（看不到金額類單據）的人，命中 0、分類數字 0（count 不洩漏「存在」），
   而且回應裡連檔名都不出現；正對照：有權的人列得出來（否則上面全部是假綠燈）。
   **突變**：把某個提供者的可讀判斷拿掉 ⇒ 同一支偵測函式必須抓到洩漏（偵測器本身有被驗過）。
③ 項目只有固定鍵（沒有 path、沒有收款銀行／帳號欄位）：單據上有收款帳號時，搜尋回應的任何地方都找不到那串數字。
④ 新增的讀取路由已登記 case_read_scope（見 tests/platform/test_case_read_scope.py 的守門）。
"""
import json
import os

import pytest

from helpers import attachment_search as S
from helpers import uploads as up
from tests.test_attachments_open_2026_09_30 import PNG, Q, _login, _open, _uid, money_docs, world  # noqa: F401  (money_docs／world 是 fixture)

QS = "MQ-LK-SH"


def _exec(sql, args=()):
    import db
    c = db.get_db()
    try:
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def _put(rel):
    full = os.path.join(up.UPLOADS_ROOT, *rel.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    open(full, "wb").write(PNG)


def _search(client, h, **params):
    return client.get("/api/filehub/search", headers=h, params=params)


def _flat(obj):
    return json.dumps(obj, ensure_ascii=False)


@pytest.fixture
def lk(client, make_user):
    """五種擁有者各一張單據，每張兩個檔：一個在自己的資料夾（可見）、一個路徑被塞到別張單據的資料夾（planted）。"""
    H = {}
    for name, role, mods in (("lk_admin", "superadmin", []), ("lk_none", "sales", ["file_center"]),
                             ("lk_otherfin", "sales", ["file_center", "payslip"])):
        u, p = make_user(username=name, role=role, modules=mods)
        H[name] = _login(client, u, p)
    owner_id = None
    _exec("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at,"
          " updated_at, deal_tag, sales_person) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
          (QS, "已送出", "客戶", "工程", 1, 1, json.dumps({"dealTag": "已成案"}), "n", "n", "已成案", "someone_else"))
    seen = []

    def two(folder, key, own_name, bad_name):
        own, bad = "%s/%s/%s" % (folder, key, own_name), "%s/ZZ-OTHER-9/%s" % (folder, bad_name)
        _put(own)
        _put(bad)
        return [{"id": "own1", "filename": own_name, "path": own, "size": len(PNG), "uploadedBy": "amy", "uploadedAt": "2026-09-30T10:00:00"},
                {"id": "bad1", "filename": bad_name, "path": bad, "size": len(PNG), "uploadedBy": "amy", "uploadedAt": "2026-09-30T10:00:01"}]
    _exec("INSERT INTO shipping_notes (note_no, quote_no, signed_files_json) VALUES (?,?,?)",
          ("SN-LK-1", QS, json.dumps(two("shipping_notes", "SN-LK-1", "lk-ship-own.png", "lk-ship-planted.png"))))
    _exec("INSERT INTO invoice_vouchers (voucher_no, quote_no, issued_files_json) VALUES (?,?,?)",
          ("IV-LK-1", QS, json.dumps(two("invoice_vouchers", "IV-LK-1", "lk-inv-own.png", "lk-inv-planted.png"))))
    vend = _exec("INSERT INTO vendor_contractors (name) VALUES (?)", ("LK廠商",))
    did = _exec("INSERT INTO contractor_dispatches (quote_no, vendor_id) VALUES (?,?)", (QS, vend))
    _exec("UPDATE contractor_dispatches SET files_json=? WHERE id=?",
          (json.dumps(two("contractor_dispatches", str(did), "lk-disp-own.png", "lk-disp-planted.png")), did))
    cid = _exec("INSERT INTO dev_cases (case_name, created_at, updated_at, converted_quote_no) VALUES (?,?,?,?)", ("LK開發案", "n", "n", QS))
    _exec("INSERT INTO dev_logs (case_id, log_date, log_by, files_json, created_at) VALUES (?,?,?,?,?)",
          (cid, "2026-09-30", 1, json.dumps(two("dev_logs", str(cid), "lk-dev-own.png", "lk-dev-planted.png")), "n"))
    seen += ["lk-ship-own.png", "lk-inv-own.png", "lk-disp-own.png", "lk-dev-own.png"]
    return H, {"own_names": seen, "planted": ["lk-ship-planted.png", "lk-inv-planted.png", "lk-disp-planted.png", "lk-dev-planted.png"],
               "did": did, "cid": cid}


def _hits(client, h, q="lk-", **kw):
    r = _search(client, h, q=q, size=50, **kw)
    assert r.status_code == 200, r.text
    return r.json()


# ── ① 路徑綁單據：列得出來的 ⇒ 打得開；被塞進來的既打不開也不列 ──────────────────────────

def test_positive_control_owner_side_lists_each_providers_own_file_and_can_open_it(client, lk):
    H, info = lk
    names = {i["filename"] for i in _hits(client, H["lk_admin"])["items"]}
    assert set(info["own_names"]) <= names, names                              # 正對照：有權的人四種來源的檔都列得出來


def test_planted_paths_are_neither_listed_nor_openable(client, lk):
    H, info = lk
    body = _hits(client, H["lk_admin"])
    assert not set(info["planted"]) & {i["filename"] for i in body["items"]}, "被塞進別張單據資料夾的檔不可以被列出來"
    for it in body["items"]:                                                   # 核心題：列得出來的都打得開
        assert _open(client, H["lk_admin"], it["sourceType"], it["docNo"], it["fileId"]).status_code == 200, it
    for t, doc in (("shipping_note", "SN-LK-1"), ("invoice_voucher", "IV-LK-1"), ("contractor_dispatch", str(info["did"])), ("dev_log", None)):
        if doc is None:
            continue
        assert _open(client, H["lk_admin"], t, doc, "bad1").status_code == 404           # 與搜尋同一道：開不了


# ── ② 沒權限的人：0 筆、分類數字 0、連檔名都不出現 ──────────────────────────────────────

def _leaks(client, h, names):
    """偵測函式：回這個人看得到的 lk- 檔名（含 items、facets 的任何位置）。突變題用同一支。"""
    body = _hits(client, h)
    text = _flat(body)
    shown = [n for n in names if n in text]
    return shown, body


def test_users_without_access_get_zero_hits_zero_counts_and_no_filenames(client, lk):
    H, info = lk
    for who in ("lk_none", "lk_otherfin"):            # 有「檔案中心」模組，但不是這些單據的讀者（含只有別的財務模組的人）
        shown, body = _leaks(client, H[who], info["own_names"] + info["planted"])
        assert shown == [], (who, shown)
        assert body["items"] == [], who
        by = body["facets"]["byType"]
        assert not any(by.get(t, 0) for t in ("shipping_note", "invoice_voucher", "contractor_dispatch", "contractor_invoice", "dev_log")), (who, by)
        scoped = _hits(client, H[who], quote_no=QS)                            # 帶案件號也一樣
        assert scoped["items"] == [] and not any(scoped["facets"]["byType"].values()), who
    shown, _ = _leaks(client, H["lk_admin"], info["own_names"])
    assert set(shown) == set(info["own_names"]), "正對照：有權的人看得到"


def test_mutation_dropping_a_readable_check_is_detected(client, lk, monkeypatch):
    """突變：把出貨單提供者的可讀判斷拿掉 ⇒ 沒權限的人就看到檔名 ⇒ 偵測函式必須抓到（否則上面的 0 筆題不能信）。"""
    H, info = lk
    import modules.supply.attachments as sup
    assert _leaks(client, H["lk_none"], ["lk-ship-own.png"])[0] == []           # 突變前：乾淨
    monkeypatch.setattr(sup, "case_documents_readable", lambda *a, **k: True)
    assert _leaks(client, H["lk_none"], ["lk-ship-own.png"])[0] == ["lk-ship-own.png"], "拿掉可讀判斷卻沒被抓到 ⇒ 偵測器壞了"


def test_mutation_dropping_the_path_ownership_filter_is_detected(client, lk, monkeypatch):
    """突變：路徑綁單據的過濾拿掉 ⇒ 被塞進來的檔就被列出來 ⇒ 偵測得到。"""
    H, info = lk
    assert "lk-ship-planted.png" not in _flat(_hits(client, H["lk_admin"]))
    monkeypatch.setattr(S, "owned", lambda *a, **k: True)
    assert "lk-ship-planted.png" in _flat(_hits(client, H["lk_admin"]))


# ── 金額類（勞報單、傳票）：只有 cashier／finance／superadmin；看得到別的財務模組不算 ───────────────

def _grant_file_center(*names):
    import db
    c = db.get_db()
    try:
        for n in names:
            mods = json.loads(c.execute("SELECT modules FROM users WHERE username=?", (n,)).fetchone()["modules"] or "[]")
            c.execute("UPDATE users SET modules=? WHERE username=?", (json.dumps(sorted(set(mods) | {"file_center"})), n))
        c.commit()
    finally:
        c.close()


def test_money_categories_zero_hits_and_zero_counts_for_everyone_else(client, money_docs):
    H, info = money_docs
    _grant_file_center("mn_cashier", "mn_finance", "mn_other_fin", "mn_none")          # 全域瀏覽需要「檔案中心」模組；資料權限另算
    for who in ("mn_cashier", "mn_super"):
        body = _search(client, H[who], q="signed", size=50).json()
        assert any(i["sourceType"] == "payslip_signed" for i in body["items"]), who               # 正對照
    for who in ("mn_other_fin", "mn_none", "mn_finance"):
        r = _search(client, H[who], q="signed", size=50)
        if r.status_code == 403:                                                # 沒有檔案中心模組：連全域都進不去
            continue
        body = r.json()
        assert not any(i["sourceType"] == "payslip_signed" for i in body["items"]), who
        assert not body["facets"]["byType"].get("payslip_signed", 0), who
        assert "signed.pdf" not in _flat(body) and info["slip"] not in _flat(body), who
    v = _search(client, H["mn_finance"], q="a1", size=50)
    if v.status_code == 200:
        assert any(i["sourceType"] == "voucher" for i in v.json()["items"])                  # finance 看得到傳票附件（正對照）


def test_voucher_attachment_with_a_planted_path_is_not_listed(client, money_docs):
    H, info = money_docs
    _grant_file_center("mn_cashier")
    v1, v2 = info["vids"]
    _exec("UPDATE voucher_attachments SET path=? WHERE voucher_id=? AND file_id='file2'", ("voucher_attachments/%d/a1.png" % v1, v2))
    body = _search(client, H["mn_cashier"], q="a2", size=50).json() if _search(client, H["mn_cashier"], q="a2").status_code == 200 else {"items": []}
    assert not any(i["filename"] == "a2.png" for i in body.get("items", [])), "路徑指向別張傳票資料夾的附件不可以被列出來"
    assert _open(client, H["mn_cashier"], "voucher", str(v2), "file2").status_code == 404


# ── ③ 項目不帶收款銀行／帳號 ───────────────────────────────────────────────────────────────

def test_items_never_carry_payee_bank_or_account(client, lk, make_user):
    H, info = lk
    assert not any(k for k in S.ITEM_KEYS if any(w in k.lower() for w in ("bank", "account", "payee", "path")))
    u, p = make_user(username="lk_xe", role="admin", modules=None)
    h = _login(client, u, p)
    _put("case_extra_expense/%s_77/lk-xe.png" % QS)
    secret_acct, secret_bank = "0123-4567-8901-2345", "測試銀行南港分行"
    _exec("INSERT INTO case_extra_expenses (id, quote_no, category, description, qty, unit, unit_cost, total_cost, status, created_by,"
          " created_by_name, created_at, updated_at, payee_type, payee_name, payee_bank, payee_account, files_json) "
          "VALUES (77,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (QS, "差旅", "LK支出", 1, "", 100, 100, "已核准", "lk_xe", "lk_xe", "n", "n", "employee", "王小明", secret_bank, secret_acct,
           json.dumps([{"id": "x1", "filename": "lk-xe.png", "path": "case_extra_expense/%s_77/lk-xe.png" % QS, "kind": "other"}])))
    body = _search(client, h, quote_no=QS, size=50).json()
    assert any(i["filename"] == "lk-xe.png" for i in body["items"]), "正對照：額外支出附件列得出來"
    assert secret_acct not in _flat(body) and secret_bank not in _flat(body) and "王小明" not in _flat(body)


# ── 工作日誌照片（P3 原本沒有的第八個提供者）與「每個提供者都有 search／count」的契約 ──────────────

def test_every_registered_catalog_provider_has_search_and_count():
    from core import registry
    missing = [k for k, p in registry.providers(up.ATTACHMENTS_CATALOG).items() if not (hasattr(p, "search") and hasattr(p, "count"))]
    assert missing == [], "這些提供者沒有 search／count（檔案中心會說『這一類沒有列入』）：%s" % missing


def test_work_log_photo_search_equals_open_for_every_user_and_hides_gps(client, world):
    H, _, _ = world
    r = client.post("/api/work-logs", headers=H["ct_admin"], json={"log_date": "2026-09-30", "content": "x", "hours": 1, "case_no": Q,
                                                                "user_id": _uid("ct_admin")})
    assert r.status_code in (200, 201), r.text
    wid = r.json()["id"]
    pr = client.post(f"/api/work-logs/{wid}/photos", headers=H["ct_admin"], files=[("files", ("a.png", PNG, "image/png"))])
    assert pr.status_code == 201, pr.text
    import db
    c = db.get_db()
    try:
        photos = json.loads(c.execute("SELECT photos FROM work_logs WHERE id=?", (wid,)).fetchone()["photos"])
    finally:
        c.close()
    pid = photos[0]["id"]
    seen_by_someone = False
    for who in H:
        rr = _search(client, H[who], quote_no=Q, types="work_log_photo", size=50)
        assert rr.status_code == 200, (who, rr.text)
        listed = [i for i in rr.json()["items"] if i["sourceType"] == "work_log_photo" and i["fileId"] == pid]
        can_open = _open(client, H[who], "work_log_photo", str(wid), pid).status_code == 200
        assert bool(listed) == can_open, ("搜尋與開檔不一致", who, bool(listed), can_open)          # 核心題
        if not can_open:
            assert pid not in _flat(rr.json()) and not rr.json()["facets"]["byType"].get("work_log_photo", 0), who   # 不列、不計數
        seen_by_someone = seen_by_someone or can_open
    assert seen_by_someone                                                                          # 正對照
    photos[0]["gps"], photos[0]["watermark"] = "25.0330,121.5654", "WM-SECRET-TEXT"                  # 真的有值才驗得出「沒外帶」
    c = db.get_db()
    try:
        c.execute("UPDATE work_logs SET photos=? WHERE id=?", (json.dumps(photos), wid))
        c.commit()
    finally:
        c.close()
    body = _flat(_search(client, H["ct_admin"], quote_no=Q).json())
    assert pid in body, "正對照：照片列得出來"
    assert "25.0330" not in body and "121.5654" not in body and "WM-SECRET-TEXT" not in body        # 照片的 GPS／浮水印欄位不外帶
    # 路徑被塞到別則日誌的資料夾 ⇒ 不列
    forged = dict(photos[0], id="forged1", path=photos[0]["path"].replace("worklog_%d" % wid, "worklog_%d" % (wid + 999)))
    c = db.get_db()
    try:
        c.execute("UPDATE work_logs SET photos=? WHERE id=?", (json.dumps(photos + [forged]), wid))
        c.commit()
    finally:
        c.close()
    ids = {i["fileId"] for i in _search(client, H["ct_admin"], quote_no=Q, types="work_log_photo", size=50).json()["items"]}
    assert pid in ids and "forged1" not in ids


# ── 費用單據（kind≠''）的附件＝金額：案件的一般讀者（業務）看不到；舊版額外支出不受影響 ──────────────────────

def _make_expense(client, h, kind):
    body = {"description": "舊式" if not kind else "", "category": "差旅", "qty": 1, "unitCost": 100}
    if kind:
        body.update({"kind": kind, "data": {"applicant": "ct_admin"}, "lines": [{"category": "差旅", "summary": "高鐵", "amount": 4321}]})
    r = client.post(f"/api/quotations/{Q}/extra-expenses", headers=h, json=body)
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    f = client.post(f"/api/quotations/{Q}/extra-expenses/{eid}/files", headers=h, files=[("files", ("receipt-4321.png", PNG, "image/png"))],
                    data={"kind": "invoice"})
    assert f.status_code == 201, f.text
    return eid, f.json()["files"][-1]["id"]


def test_typed_expense_attachments_are_hidden_from_ordinary_case_readers_but_legacy_ones_are_not(client, world):
    H, _, _ = world
    typed, tfid = _make_expense(client, H["ct_admin"], "travel")
    legacy, lfid = _make_expense(client, H["ct_admin"], "")
    owner = H["ct_owner"]                                                                  # 該案業務：案件讀者，但不是申請人／簽核人
    names = lambda h: {i["filename"] for i in _search(client, h, quote_no=Q, types="extra_expense", size=50).json()["items"]}
    # 舊版額外支出：維持原行為（案件讀者看得到、打得開）
    assert _open(client, owner, "extra_expense", str(legacy), lfid).status_code == 200
    assert "receipt-4321.png" in names(owner)
    # 費用單據：業務不列、不計數、打不開、檔名不外露
    body = _search(client, owner, quote_no=Q, types="extra_expense", size=50).json()
    assert _open(client, owner, "extra_expense", str(typed), tfid).status_code == 404
    typed_items = [i for i in body["items"] if i["docNo"] == str(typed)]
    assert typed_items == [], typed_items
    allc = _search(client, owner, quote_no=Q, size=50).json()
    assert allc["facets"]["byType"].get("extra_expense", 0) == 1, allc["facets"]["byType"]        # 只剩舊式那一筆（不洩漏費用單據的存在）
    # 正對照：申請人／管理員打得開也列得出來
    assert _open(client, H["ct_admin"], "extra_expense", str(typed), tfid).status_code == 200
    assert any(i["docNo"] == str(typed) for i in _search(client, H["ct_admin"], quote_no=Q, types="extra_expense", size=50).json()["items"])
