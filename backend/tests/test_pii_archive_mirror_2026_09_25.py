# -*- coding: utf-8 -*-
"""勞報單（F2 個資）上雲：獨立、權限更窄的資料夾（2026-09-25 使用者裁示；MODULE-GUIDE §3.2）。

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


def test_folder_is_beside_the_general_archive_not_inside(pii, isolated_archive):
    root, _src, _a = pii
    assert os.path.dirname(root) == os.path.dirname(isolated_archive)
    assert not root.startswith(isolated_archive + os.sep)


def test_missing_folder_is_never_created_and_nothing_uploads(pii):
    root, _src, alerts = pii
    assert archive._mirror_pii_archives() == 0
    assert not os.path.exists(root), "程式自己建了個資資料夾——權限會繼承上層（更寬）"
    assert alerts and alerts[0][0] == "ERROR" and "只有本機一份" in alerts[0][1] and root in alerts[0][1]
    assert archive.pii_archive_status()["state"] == "missing"


def test_ready_folder_receives_payslips(pii):
    root, _src, alerts = pii
    os.makedirs(root)                                 # 人預先建立（並收窄權限）
    assert archive._mirror_pii_archives() == 1
    assert os.path.isfile(os.path.join(root, archive._PII_PAYSLIP_SUBDIR, "PS-202609-001_1.pdf"))
    assert archive._mirror_pii_archives() == 0         # 增量：沒變就不再複製
    assert not alerts


def test_payslips_do_not_go_into_the_general_pdf_mirror(pii, isolated_archive):
    root, _src, _a = pii
    os.makedirs(root)
    archive._mirror_pdf_archives()
    archive._mirror_pii_archives()
    for dp, _dn, fns in os.walk(isolated_archive):
        assert "PS-202609-001_1.pdf" not in fns, dp


def test_alert_is_edge_triggered(pii):
    root, _src, alerts = pii
    archive._mirror_pii_archives()
    archive._mirror_pii_archives()
    archive._mirror_pii_archives()
    assert len(alerts) == 1, "狀態沒變卻重複告警"
    os.makedirs(root)
    archive._mirror_pii_archives()                    # missing → ready：不告警，記狀態
    assert len(alerts) == 1
    assert (_get_setting(archive._PII_STATE_KEY) or {}).get("state") == "ready"
    shutil.rmtree(root)
    archive._mirror_pii_archives()                    # ready → missing：再告警一次
    assert len(alerts) == 2


def test_object_storage_backend_does_not_upload_and_alerts(pii, monkeypatch):
    _root, _src, alerts = pii
    monkeypatch.setattr(archive, "_active_backend", lambda: "s3")
    uploaded = []
    monkeypatch.setattr(archive, "_cloud_copy_file", lambda *a: uploaded.append(a))
    assert archive._mirror_pii_archives() == 0
    assert not uploaded
    assert alerts and "S3" in alerts[0][1]


def test_cloud_off_machine_does_nothing_and_stays_quiet(pii, monkeypatch):
    root, _src, alerts = pii
    os.makedirs(root)
    monkeypatch.setattr(archive, "cloud_archive_enabled", lambda: False)
    assert archive._mirror_pii_archives() == 0
    assert not alerts
    assert archive.pii_archive_status()["state"] == "cloud_off"


def test_status_endpoint_is_superadmin_only_and_reports_live_state(client, make_user, pii):
    root, _src, _a = pii
    u, p = make_user("pii_sa", "Pii-Pass-123", role="superadmin")[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    r = client.get("/api/settings/pii-archive-status", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200, r.text
    assert r.json()["live"]["state"] == "missing" and r.json()["live"]["path"] == root
    a, ap = make_user("pii_admin", "Pii-Pass-123", role="admin")[:2]
    tok2 = client.post("/api/auth/login", json={"username": a, "password": ap}).json()["token"]
    assert client.get("/api/settings/pii-archive-status",
                      headers={"Authorization": "Bearer " + tok2}).status_code == 403


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


def test_general_rows_drop_f2_fields_and_merge_restores_the_original(client):
    from db import get_db
    conn = get_db()
    try:
        _seed_pii(conn)
        tables = archive._daily_backup_tables()
        for fname in archive._F2_FIELDS:
            original = _rows(conn, tables[fname])
            general = [archive._general_row(fname, dict(r)) for r in original]
            blob = str(general)
            for bad in _F2_SENTINELS:
                assert bad not in blob, (fname, bad)
            merged, missing = archive.merge_general_and_pii(fname, general, original)
            assert missing == []
            assert merged == original, fname              # 一般＋個資 合回＝原表（逐欄相等）
    finally:
        conn.close()


def test_merge_without_pii_copy_keeps_general_and_reports_missing(client):
    from db import get_db
    conn = get_db()
    try:
        _seed_pii(conn)
        original = _rows(conn, archive._daily_backup_tables()["承攬人員"])
        general = [archive._general_row("承攬人員", dict(r)) for r in original]
        merged, missing = archive.merge_general_and_pii("承攬人員", general, [])
        assert merged == general and sorted(missing) == sorted(r["id"] for r in original)
    finally:
        conn.close()


def test_unparseable_payslip_json_is_not_copied_verbatim_into_general():
    row = {"id": 1, "data_json": '{"contractorIdNumber": "' + _IDNO + '", broken'}
    out = archive._general_row("薪資單", row)
    assert _IDNO not in str(out) and out["data_json"] == archive._F2_UNPARSEABLE


def test_pii_field_labels_point_at_the_declared_tables():
    """_F2_FIELDS 的標籤必須存在，且那支 SQL 查的真的是宣告的表（改名時這裡先紅）。"""
    tables = archive._daily_backup_tables()
    for fname, spec in archive._F2_FIELDS.items():
        assert fname in tables, fname
        assert ("FROM " + spec["table"]) in tables[fname], (fname, tables[fname])


def _walk_files(root):
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            yield os.path.join(dp, fn)


def test_general_cloud_tree_has_no_db_no_f2_no_f3(client, isolated_archive, monkeypatch):
    """🔴 守門：一般雲端目錄底下**不可以有 .db**，也不可以出現 F2 內容或 F3 祕密；個資資料夾才有。"""
    from db import get_db
    from helpers.settings import _get_setting as _gs
    pii_root = os.path.join(os.path.dirname(isolated_archive), archive._PII_ARCHIVE_DIRNAME)
    os.makedirs(pii_root)
    conn = get_db()
    try:
        _seed_pii(conn)
    finally:
        conn.close()
    en = _gs("email_notify", {}) or {}
    _set_setting("email_notify", {**en, "smtp_password": _SMTP_PW})
    monkeypatch.setattr(archive, "_write_backup_alert", lambda *a, **k: None)

    archive._daily_backup()
    archive._weekly_backup()

    sentinels = _F2_SENTINELS + (_TOTP, _SMTP_PW)
    for path in _walk_files(isolated_archive):
        assert not path.endswith((".db", ".db-wal", ".db-shm")), "一般雲端目錄出現整庫檔：%s" % path
        with open(path, "rb") as fh:
            blob = fh.read().decode("utf-8", "replace")
        for s in sentinels:
            assert s not in blob, "一般雲端目錄的 %s 含 %r" % (path, s[:20])

    # 正對照：個資資料夾真的收到了整庫與 F2 完整列
    from datetime import date as _d
    day = os.path.join(pii_root, "每日備份", _d.today().isoformat())
    assert os.path.isfile(os.path.join(day, "motrix_erp.db"))
    pii_blob = open(os.path.join(day, "承攬人員.json"), encoding="utf-8").read()
    assert _IMG in pii_blob
    assert _IDNO in open(os.path.join(day, "薪資單.json"), encoding="utf-8").read()


def test_without_pii_folder_the_db_is_not_copied_anywhere_in_the_cloud(client, isolated_archive, monkeypatch):
    """個資資料夾未建立 ⇒ 雲端**沒有**整庫備份（不退回一般資料夾），而且有告警。"""
    alerts = []
    monkeypatch.setattr(archive, "_write_backup_alert", lambda r, level="WARN": alerts.append((level, r)))
    archive._daily_backup()
    parent = os.path.dirname(isolated_archive)
    assert not [p for p in _walk_files(isolated_archive) if p.endswith(".db")]
    assert not os.path.exists(os.path.join(parent, archive._PII_ARCHIVE_DIRNAME))
    assert any("個資資料夾未建立" in r for _l, r in alerts)


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


def test_voucher_snapshot_personnel_accounts_are_f2(client):
    snap = _json.dumps({"vendorName": "V", "bankCode": "812", "bankAccountNumber": _V_ACCT,
                        "bankAccountName": _V_NAME, "bankPassbookImage": _IMG,
                        "personnel": [{"id": 1, "name": "外包", "bankCode": "812",
                                       "bankAccountName": _P_NAME, "bankAccountNumber": _P_ACCT,
                                       "bankPassbookImage": _IMG}]}, ensure_ascii=False)
    row = {"id": 7, "voucher_no": "CV-1", "snapshot_json": snap}
    g = archive._general_row("承攬付款憑據", dict(row))
    for bad in (_P_ACCT, _P_NAME, _V_ACCT, _V_NAME, "data:image"):
        assert bad not in str(g), bad
    gs = _json.loads(g["snapshot_json"])
    assert gs["personnel"][0] == {"id": 1, "name": "外包", "bankCode": "812"}   # 機構資訊與其餘欄位留著
    # 最上層＝協力廠商（承攬商本身）：O-9 裁示屬 F2 ⇒ 帳戶三鍵拿掉，機構資訊留著
    assert {k: gs[k] for k in ("vendorName", "bankCode")} == {"vendorName": "V", "bankCode": "812"}
    assert not {"bankAccountNumber", "bankAccountName", "bankPassbookImage"} & set(gs)
    merged, missing = archive.merge_general_and_pii("承攬付款憑據", [g], [row])
    assert missing == [] and merged == [row]
    assert archive._general_row("承攬付款憑據", {"id": 1, "snapshot_json": "{broken"})["snapshot_json"] \
        == archive._F2_UNPARSEABLE


def test_key_scan_positive_control_sees_a_personnel_account():
    """掃描器的正對照：把快照原樣（沒有去個資）放進一般樹的形狀 ⇒ 要亮。"""
    out = set()
    _f2_key_hits(_json.dumps({"personnel": [{"bankAccountNumber": _P_ACCT}]}), "snapshot_json",
                 _f2_json_keys(), out)
    assert out == {"snapshot_json.personnel[].bankAccountNumber"}


# ── S-5：檢查之後才消失 ⇒ 寫入失敗並告警，不建回來 ─────────────────────────────

def test_pii_folder_vanishing_mid_mirror_is_not_recreated(pii, monkeypatch):
    """P3：pii_archive_status 看到資料夾存在 ⇒ 資料夾被移除 ⇒ 寫入。修正前：makedirs 把它建回來。"""
    root, _src, alerts = pii
    os.makedirs(root)
    real_status = archive.pii_archive_status

    def status_then_vanish():
        st = real_status()
        shutil.rmtree(root)                           # 檢查之後、寫入之前
        return st
    monkeypatch.setattr(archive, "pii_archive_status", status_then_vanish)
    assert archive._mirror_pii_archives() == 0
    assert not os.path.exists(root), "資料夾在寫入途中消失，程式把它建回來了"
    assert any(level == "ERROR" and "寫入途中消失" in r for level, r in alerts), alerts


def test_pii_folder_vanishing_before_daily_json_export(pii, client, monkeypatch):
    root, _src, alerts = pii
    os.makedirs(root)
    real_status = archive.pii_archive_status

    def status_then_vanish():
        st = real_status()
        shutil.rmtree(root)
        return st
    monkeypatch.setattr(archive, "pii_archive_status", status_then_vanish)
    from db import get_db
    conn = get_db()
    try:
        assert archive._pii_daily_json_export(conn, "2026-09-25", "now") is None
    finally:
        conn.close()
    assert not os.path.exists(root)
    assert any("寫入途中消失" in r for _l, r in alerts), alerts


def test_pii_ensure_dir_creates_only_below_an_existing_root(pii):
    root, _src, _a = pii
    with pytest.raises(archive.PiiFolderMissing):
        archive._pii_ensure_dir(os.path.join(root, "每日備份", "2026-09-25"))
    with pytest.raises(archive.PiiFolderMissing):
        archive._pii_ensure_dir(root)                    # 目標就是根目錄本身：沒有子層可建，也要失敗
    assert not os.path.exists(root)
    os.makedirs(root)
    archive._pii_ensure_dir(os.path.join(root, "每日備份", "2026-09-25"))    # 正對照：底下可以建
    assert os.path.isdir(os.path.join(root, "每日備份", "2026-09-25"))
    with pytest.raises(ValueError):
        archive._pii_ensure_dir(os.path.dirname(root))                         # 個資資料夾以外不歸它管


def test_pii_folder_vanishing_between_check_and_mkdir(pii, monkeypatch):
    """競態的最窄處：根目錄的 isdir 檢查通過之後、建第一層子資料夾之前才消失 ⇒ 仍然不可以建回來
    （`os.mkdir` 不建上層；`makedirs` 會）。"""
    root, _src, _a = pii
    os.makedirs(root)
    real_isdir = os.path.isdir
    fired = []

    def isdir_then_vanish(path):
        r = real_isdir(path)
        if r and not fired and os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(root)):
            fired.append(path)
            shutil.rmtree(root)
        return r
    monkeypatch.setattr(archive.os.path, "isdir", isdir_then_vanish)
    with pytest.raises(archive.PiiFolderMissing):
        archive._pii_ensure_dir(os.path.join(root, "每日備份", "2026-09-25"))
    monkeypatch.undo()
    assert fired, "前提：檢查確實發生在消失之前"
    assert not os.path.exists(root), "檢查之後才消失的個資資料夾被建回來了"


def test_pii_folder_vanishing_during_daily_backup_is_not_recreated(pii, client, monkeypatch):
    """整輪每日備份（整庫 .db、個資 JSON、勞報單鏡像三條寫入路徑）：第一次檢查之後資料夾就消失 ⇒ 全程不建回來。"""
    root, _src, alerts = pii
    os.makedirs(root)
    real_status = archive.pii_archive_status
    fired = []

    def status_then_vanish():
        st = real_status()
        if not fired:                                  # 只消失一次：之後被建回來就留著，才看得到
            fired.append(1)
            shutil.rmtree(root)
        return st if st["state"] != "missing" else {**st, "state": "ready"}   # 讓每一條路徑都以為還在
    monkeypatch.setattr(archive, "pii_archive_status", status_then_vanish)
    archive._daily_backup()
    assert not os.path.exists(root), "每日備份途中把個資資料夾建回來了"
    assert any("寫入途中消失" in r for _l, r in alerts), alerts
