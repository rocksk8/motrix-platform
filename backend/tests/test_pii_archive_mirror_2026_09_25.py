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


def _seed_pii(conn):
    conn.execute("INSERT INTO contractors (name, id_number, id_card_image, id_card_image_back, "
                 "bank_passbook_image, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                 ("哨兵承攬", "B987654321", _IMG, _IMG, _IMG, "2026-09-25", "2026-09-25"))
    data = {"slipNo": "PS-202609-009", "contractorName": "哨兵承攬", "contractorIdNumber": _IDNO,
            "contractorAddress": "哨兵地址", "contractorPhone": "0900-SENTINEL",
            "contractorEmail": "sentinel@example.invalid", "grossAmount": 1000}
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
            for bad in (_IMG, "data:image", _IDNO, "哨兵地址", "0900-SENTINEL", "sentinel@example.invalid"):
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

    sentinels = (_IMG, "data:image", _IDNO, _TOTP, _SMTP_PW)
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
