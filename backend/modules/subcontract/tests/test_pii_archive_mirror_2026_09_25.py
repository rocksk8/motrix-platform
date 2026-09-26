# -*- coding: utf-8 -*-
"""需要外包工班（M04）的題：刪掉 modules/subcontract 時隨模組消失（PLAYBOOK §B-11，稽核 D M04-M1）。

（2026-09-26 自 tests/test_pii_archive_mirror_2026_09_25.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
勞報單（F2 個資）上雲：獨立、權限更窄的資料夾（2026-09-25 使用者裁示；MODULE-GUIDE §3.2）。

🔴 核心性質：**程式永不自動建立 `系統存檔_個資`**——自動建的資料夾繼承上層分享權限（更寬），
   而且會成功、不報錯。不存在 ⇒ 不上傳 ⇒ 告警（邊緣觸發：狀態改變才記）。
"""
import os
import shutil

import pytest

import archive
from core import paths
from helpers.settings import _get_setting, _set_setting


@pytest.fixture()
def pii(isolated_archive, tmp_path, monkeypatch):
    """回傳 (個資根目錄路徑, 勞報單來源目錄)；來源放一張假勞報單。"""
    src = tmp_path / "export_archive"
    src.mkdir()
    (src / "PS-202609-001_1.pdf").write_bytes(b"%PDF-1.4 fake")
    _set_setting(paths.PDF_ARCHIVES["payslip"][0], str(src))
    alerts = []
    monkeypatch.setattr(archive, "_write_backup_alert", lambda reason, level="WARN": alerts.append((level, reason)))
    root = os.path.join(os.path.dirname(isolated_archive), archive._PII_ARCHIVE_DIRNAME)
    return root, src, alerts


# ══════════════════════════════════════════════════════════════════════════════
# 使用者裁示①（2026-09-25）：F2 欄位只進個資資料夾；一般份排除；還原時合回
# 使用者裁示 (a)：整庫 .db 只放個資資料夾
# ══════════════════════════════════════════════════════════════════════════════
_IMG = "data:image/jpeg;base64,/9j/SENTINEL_IMAGE_BYTES"
_IDNO = "A123456789_SENTINEL"
_TOTP = "TOTPSENTINELBASE32XX"
_SMTP_PW = "smtp-sentinel-password"
_C_IDNO, _C_PHONE, _C_MAIL = "B987654321_SENTINEL", "0911-CPHONE", "c-sentinel@example.invalid"
_C_ADDR, _C_LINE, _C_ACCT = "承攬哨兵地址", "line-sentinel", "000123456789SENTINEL"
#: 一般份（去個資）不可以出現的值——承攬人員與勞報單兩張表的全部 F2 欄位
_F2_SENTINELS = (_IMG, "data:image", _IDNO, "哨兵地址", "0900-SENTINEL", "sentinel@example.invalid",
                 _C_IDNO, _C_PHONE, _C_MAIL, _C_ADDR, _C_LINE, _C_ACCT, "哨兵戶名")


def _seed_pii(conn):
    conn.execute("INSERT INTO contractors (name, id_number, phone, email, address, line_id, "
                 "bank_code, bank_account_name, bank_account_number, id_card_image, id_card_image_back, "
                 "bank_passbook_image, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 ("哨兵承攬", _C_IDNO, _C_PHONE, _C_MAIL, _C_ADDR, _C_LINE, "812", "哨兵戶名", _C_ACCT,
                  _IMG, _IMG, _IMG, "2026-09-25", "2026-09-25"))
    data = {"slipNo": "PS-202609-009", "contractorName": "哨兵承攬", "contractorIdNumber": _IDNO,
            "contractorAddress": "哨兵地址", "contractorPhone": "0900-SENTINEL",
            "contractorEmail": "sentinel@example.invalid", "contractorLineId": _C_LINE,
            "bankAccountName": "哨兵戶名", "bankAccountNumber": _C_ACCT, "grossAmount": 1000}
    import json as _j
    conn.execute("INSERT INTO payslips (slip_no, contractor_name, data_json, created_at, updated_at) "
                 "VALUES (?,?,?,?,?)", ("PS-202609-009", "哨兵承攬", _j.dumps(data, ensure_ascii=False),
                                        "2026-09-25", "2026-09-25"))
    conn.execute("UPDATE users SET totp_secret=? WHERE id=(SELECT MIN(id) FROM users)", (_TOTP,))
    conn.commit()


def _rows(conn, sql):
    return [dict(r) for r in conn.execute(sql).fetchall()]


def _walk_files(root):
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            yield os.path.join(dp, fn)


# ══════════════════════════════════════════════════════════════════════════════
# 稽核 X-9b M-3：F2 值被複製進別的表（承攬付款憑據 snapshot_json.personnel[]）
# 稽核 X-9b S-5：個資資料夾在「檢查之後、寫入之前」消失 ⇒ 不可以被建回來
# ══════════════════════════════════════════════════════════════════════════════
import json as _json

_P_ACCT, _P_NAME = "555000999888SENTINEL", "外包哨兵戶名"
_V_ACCT = "VENDOR-ACCT-424242"
_V_NAME = "協力哨兵戶名"          # 稽核 X-9b O-9：協力廠商（承攬商本身）的帳戶也是 F2


def _f2_json_keys():
    """F2 鍵名（JSON 欄位裡出現就算個資）：由 `_F2_FIELDS` 推導——contractors 欄名（snake 與 camel）＋
    各 JSON 規格的鍵。phone／email／address 這三個字太泛（客戶、廠商、公司的聯絡欄也叫這個名字），
    不列入鍵名掃描；它們由哨兵值掃描負責。"""
    def camel(n):
        head, *rest = n.split("_")
        return head + "".join(w.title() for w in rest)
    keys = set()
    for spec in archive._F2_FIELDS.values():
        for c in spec.get("columns", ()):
            keys |= {c, camel(c)}
        if "json" in spec:
            keys |= set(spec["json"][1])
        if "json_list" in spec:
            keys |= set(spec["json_list"][2])
    return keys - {"phone", "email", "address"}


#: 一般份裡**有人決定過**可以留著的 F2 鍵名位置：(檔名, 欄位.路徑) → 理由。
#: 每一條都必須在本題的資料裡真的出現（沒出現 ⇒ 紅：這張清單不可以變成「全部寫進來就綠」）。
_F2_KEY_ALLOWED = {
    # 稽核 X-9b O-9（2026-09-25 使用者表單裁示「當成個資分流」）：協力廠商（承攬商本身）的帳戶
    # 原本列在這裡照一般表匯出，裁示後移出、改宣告在 `_F2_FIELDS`。目前沒有任何一條例外。
}
_PLACEHOLDERS = {archive._IMAGE_PLACEHOLDER, archive._F2_UNPARSEABLE}


def _f2_key_hits(value, path, keys, out):
    """遞迴找 JSON 內容裡、鍵名屬 F2、值不是空的位置。字串值若本身是 JSON 物件／陣列就展開。"""
    if isinstance(value, str) and value[:1] in "{[":
        try:
            value = _json.loads(value)
        except ValueError:
            return
    if isinstance(value, dict):
        for k, v in value.items():
            sub = "%s.%s" % (path, k) if path else k
            if k in keys and isinstance(v, str) and v.strip() and v not in _PLACEHOLDERS:
                out.add(sub)
            _f2_key_hits(v, sub, keys, out)
    elif isinstance(value, list):
        for v in value:
            _f2_key_hits(v, path + "[]", keys, out)


def _general_f2_key_hits(tree):
    keys = _f2_json_keys()
    hits = set()
    for path in _walk_files(tree):
        if not path.endswith(".json"):
            continue
        fname = os.path.splitext(os.path.basename(path))[0]
        with open(path, encoding="utf-8") as fh:
            doc = _json.load(fh)
        for row in (doc.get("data") if isinstance(doc, dict) else None) or []:
            if not isinstance(row, dict):
                continue
            for col, v in row.items():
                found = set()
                if isinstance(v, str) and v[:1] in "{[":         # 只掃 JSON 欄位（快照、data_json…）
                    _f2_key_hits(v, col, keys, found)
                hits |= {(fname, h) for h in found}
    return hits


def _voucher_via_api(client, make_user):
    """外包人員（F2 來源）→ 協力廠商 → 派工（personnel_json 指向外包人員）→ **真正的建立憑據 API**。
    哨兵值怎麼傳進憑據快照由產品程式決定，不由測試指定。"""
    from db import get_db
    conn = get_db()
    try:
        cid = conn.execute(
            "INSERT INTO contractors (name, bank_code, bank_account_name, bank_account_number, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?)",
            ("外包哨兵", "812", _P_NAME, _P_ACCT, "2026-09-25", "2026-09-25")).lastrowid
        conn.commit()
    finally:
        conn.close()
    u, p = make_user("x9b_m3_sa", "X9b-Pass-123", role="superadmin")[:2]
    h = {"Authorization": "Bearer " + client.post("/api/auth/login",
                                                  json={"username": u, "password": p}).json()["token"]}
    r = client.post("/api/vendor-contractors", headers=h,
                    json={"name": "哨兵工作室", "data": {"bankCode": "812", "bankAccountNumber": _V_ACCT,
                                                       "bankAccountName": _V_NAME}})
    assert r.status_code == 201, r.text
    r = client.post("/api/contractor-dispatches", headers=h, json={
        "quote_no": "MQ-X9B-M3", "vendor_id": r.json()["id"], "status": "completed",
        "items_json": [{"description": "x", "qty": 1, "unit": "式", "unitPrice": 100, "amount": 100}],
        "personnel_json": [{"id": cid, "name": "外包哨兵", "amount": 100}]})
    assert r.status_code == 201, r.text
    r = client.post("/api/contractor-vouchers", headers=h, json={"dispatch_id": r.json()["id"]})
    assert r.status_code == 201, r.text
    conn = get_db()
    try:
        snap = conn.execute("SELECT snapshot_json FROM contractor_payment_vouchers WHERE voucher_no=?",
                            (r.json()["voucher_no"],)).fetchone()[0]
    finally:
        conn.close()
    assert _P_ACCT in snap, "前提：產品把外包人員帳號凍結進了快照（這題要驗的傳遞路徑）"
    assert _V_ACCT in snap and _V_NAME in snap, "前提：產品把協力廠商帳戶凍結進了快照最上層（O-9）"
    return snap


def test_general_tree_has_no_f2_copied_into_other_tables(client, make_user, isolated_archive, monkeypatch):
    """🔴 守門（稽核 X-9b M-3、O-9）：走真正的建立 API（協力廠商、憑據）→ 每日＋週＋月備份 → 掃一般樹。
    ① 哨兵值（外包人員帳戶、協力廠商帳戶）不可以出現在一般樹的任何檔案——**與允許清單無關**；
    ② 所有 JSON 欄位（快照等）裡，F2 鍵名有值的位置都必須在 `_F2_KEY_ALLOWED`（有人決定過），
       而且清單裡的每一條都要真的出現（反向控制：不可以靠把位置全寫進清單變綠）。"""
    pii_root = os.path.join(os.path.dirname(isolated_archive), archive._PII_ARCHIVE_DIRNAME)
    os.makedirs(pii_root)
    snap = _voucher_via_api(client, make_user)
    monkeypatch.setattr(archive, "_write_backup_alert", lambda *a, **k: None)
    archive._daily_backup()
    archive._weekly_backup()

    from datetime import date as _d
    # 正對照：一般樹確實有每日、月備份的協力廠商與憑據 JSON（掃描有對象；週備份不含這兩張表）
    for layer in ("每日備份", "月備份"):
        found = [p for p in _walk_files(isolated_archive)
                 if layer in p and os.path.basename(p) in ("協力廠商.json", "承攬付款憑據.json")]
        assert len(found) == 2, (layer, found)
    for path in _walk_files(isolated_archive):
        with open(path, "rb") as fh:
            blob = fh.read().decode("utf-8", "replace")
        for s in (_P_ACCT, _P_NAME, _V_ACCT, _V_NAME):
            assert s not in blob, "一般雲端目錄的 %s 含帳戶哨兵 %r" % (path, s)
    hits = _general_f2_key_hits(isolated_archive)
    undecided = {h for h in hits if h not in _F2_KEY_ALLOWED}
    assert not undecided, "一般份的 JSON 欄位裡有 F2 鍵名且有值、沒有人決定過：%s" % sorted(undecided)
    unused = set(_F2_KEY_ALLOWED) - hits
    assert not unused, "允許清單裡這幾條本題沒有出現（過期或寫錯，清單不可以只增不減）：%s" % sorted(unused)

    # 正對照：個資資料夾收到了完整快照與協力廠商完整列
    pii_day = os.path.join(pii_root, "每日備份", _d.today().isoformat())
    voucher_blob = open(os.path.join(pii_day, "承攬付款憑據.json"), encoding="utf-8").read()
    assert _P_ACCT in voucher_blob and _V_ACCT in voucher_blob and _V_NAME in voucher_blob
    vendor_blob = open(os.path.join(pii_day, "協力廠商.json"), encoding="utf-8").read()
    assert _V_ACCT in vendor_blob and _V_NAME in vendor_blob
    assert _json.loads(snap)["personnel"][0]["bankAccountNumber"] == _P_ACCT


# ── S-5：檢查之後才消失 ⇒ 寫入失敗並告警，不建回來 ─────────────────────────────


def test_written_general_and_pii_files_merge_back_to_the_tables(client, make_user, isolated_archive, monkeypatch):
    """稽核 X-9b O-6：合回用的是**每日備份實際寫出的檔**（一般份＋個資份），不是記憶體裡的原始列。"""
    from datetime import date as _d
    from db import get_db
    pii_root = os.path.join(os.path.dirname(isolated_archive), archive._PII_ARCHIVE_DIRNAME)
    os.makedirs(pii_root)
    conn = get_db()
    try:
        _seed_pii(conn)
    finally:
        conn.close()
    _voucher_via_api(client, make_user)
    monkeypatch.setattr(archive, "_write_backup_alert", lambda *a, **k: None)
    archive._daily_backup()
    day = _d.today().isoformat()
    general_dir = [dp for dp, _dn, fns in os.walk(isolated_archive)
                   if "承攬人員.json" in fns and day in dp]
    assert len(general_dir) == 1, general_dir
    tables = archive._daily_backup_tables()
    conn = get_db()
    try:
        for fname in archive._F2_FIELDS:
            general = _json.load(open(os.path.join(general_dir[0], fname + ".json"), encoding="utf-8"))["data"]
            pii_rows = _json.load(open(os.path.join(pii_root, "每日備份", day, fname + ".json"),
                                       encoding="utf-8"))["data"]
            original = [dict(r) for r in conn.execute(tables[fname]).fetchall()]
            assert original, fname
            merged, missing = archive.merge_general_and_pii(fname, general, pii_rows)
            assert missing == [] and merged == original, fname
    finally:
        conn.close()
