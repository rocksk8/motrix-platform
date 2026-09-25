# -*- coding: utf-8 -*-
"""core.paths 契約（DATA-COMPAT §4 A-1）。

① 每個位置的值與 V9 原位置相同（原地讀取＝不搬任何東西）。
   期望值用「本測試檔自己的位置」推回 backend/，**不 import core.paths 來算期望值**
   ——否則錨點算錯時期望值會跟著錯，斷言驗到的是自己（〈假綠燈〉）。
② 主庫不存在 ⇒ 拒絕；只有明確旗標放行。
"""
import logging
import os

import pytest

from core import paths

#: backend/tests/platform/test_core_paths.py ⇒ 上三層是 backend/
BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(BACKEND)


def _same(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


# V9 原位置（DATA-COMPAT §1，逐列對照）
V9_LOCATIONS = {
    "DB_PATH": os.path.join(BACKEND, "motrix_erp.db"),
    "DEMO_DB_PATH": os.path.join(BACKEND, "motrix_erp_demo.db"),
    "STATIC_DATA_DIR": os.path.join(BACKEND, "data"),
    "UPLOADS_ROOT": os.path.join(ROOT, "uploads"),
    "PROJECT_PHOTOS_DIR": os.path.join(ROOT, "uploads", "projects"),
    "DEMO_PROJECT_PHOTOS_DIR": os.path.join(ROOT, "uploads", "_demo_projects"),
    "DEMO_UPLOADS_DIR": os.path.join(ROOT, "uploads", "_demo_uploads"),
    "DEMO_PDF_ARCHIVE_DIR": os.path.join(BACKEND, "_demo_pdf_archive"),
    "DEMO_PAYSLIP_ARCHIVE_DIR": os.path.join(BACKEND, "_demo_payslip_archive"),
    "DEMO_SHIPPING_PDF_ARCHIVE_DIR": os.path.join(BACKEND, "_demo_shipping_pdf_archive"),
    "DEMO_CONTRACTOR_VOUCHER_PDF_ARCHIVE_DIR": os.path.join(BACKEND, "_demo_contractor_voucher_pdf_archive"),
    "DEMO_INVOICE_VOUCHER_PDF_ARCHIVE_DIR": os.path.join(BACKEND, "_demo_invoice_voucher_pdf_archive"),
    "DEMO_PAYMENT_REQUEST_PDF_ARCHIVE_DIR": os.path.join(BACKEND, "_demo_payment_request_pdf_archive"),
    "DEMO_CASE_CLOSING_PDF_ARCHIVE_DIR": os.path.join(BACKEND, "_demo_case_closing_pdf_archive"),
    "LOCAL_DB_BACKUP_DIR": os.path.join(BACKEND, "db_backups"),
    "BACKUP_ALERT_DIR": os.path.join(ROOT, "backup_alerts"),
    "NO_CLOUD_MARKER": os.path.join(ROOT, ".no_cloud_archive"),
    # 不是 V9 既有位置：2026-09-25 新增（email 改用標記判定，取代安裝路徑）
    "NO_EMAIL_SEND_MARKER": os.path.join(ROOT, ".no_email_send"),
    "LOGS_DIR": os.path.join(BACKEND, "logs"),
    "SERVER_LOG": os.path.join(BACKEND, "logs", "server.log"),
    "HEARTBEAT_CONFIG": os.path.join(BACKEND, "heartbeat_config.json"),
    "LICENSE_PATH": os.path.join(BACKEND, "license.key"),
    "CERT_PEM": os.path.join(BACKEND, "certs", "cert.pem"),
    "INITIAL_ADMIN_CREDENTIALS": os.path.join(BACKEND, ".initial_admin_credentials.txt"),
    "INITIAL_DEMO_CREDENTIALS": os.path.join(BACKEND, ".initial_demo_credentials.txt"),
    "BUILD_COMMIT_FILE": os.path.join(BACKEND, ".build_commit"),
    "DEPLOYED_COMMIT_FILE": os.path.join(BACKEND, ".deployed_commit.json"),
    "VERSION_MANIFEST": os.path.join(BACKEND, "version_manifest.json"),
    # V9 c83dae6e 的 backend/autostart.bat（排程工作啟動它；Python 不讀它）
    "AUTOSTART_BAT": os.path.join(BACKEND, "autostart.bat"),
    "FRONTEND_DIR": os.path.join(ROOT, "frontend"),
    "FRONTEND_PAGES_DIR": os.path.join(ROOT, "frontend", "pages"),
}

V9_PDF = {
    "quotation": ("pdf_base_path", os.path.join(ROOT, "報價單PDF")),
    "shipping": ("shipping_pdf_base_path", os.path.join(ROOT, "出貨單PDF")),
    "contractor_voucher": ("contractor_voucher_pdf_base_path", os.path.join(ROOT, "承攬商匯款申請PDF")),
    "invoice_voucher": ("invoice_voucher_pdf_base_path", os.path.join(ROOT, "開票申請憑據PDF")),
    "payment_request": ("payment_request_pdf_base_path", os.path.join(ROOT, "請款單PDF")),
    "case_closing": ("case_closing_pdf_base_path", os.path.join(ROOT, "結案報表PDF")),
    "payslip": ("payslip_archive_path", os.path.join(BACKEND, "export_archive")),
}


@pytest.mark.parametrize("name", sorted(V9_LOCATIONS))
def test_location_equals_v9(name):
    assert _same(getattr(paths, name), V9_LOCATIONS[name]), (name, getattr(paths, name))


def test_pdf_archives_equal_v9():
    assert set(paths.PDF_ARCHIVES) == set(V9_PDF)
    for k, (key, d) in V9_PDF.items():
        got_key, got_dir = paths.PDF_ARCHIVES[k]
        assert got_key == key, k
        assert _same(got_dir, d), (k, got_dir)


def test_every_public_path_is_covered():
    """paths 新增了位置卻沒進對照表 ⇒ 紅（對照表是這支契約的範圍）。"""
    public = {n for n, v in vars(paths).items()
              if n.isupper() and isinstance(v, str) and n not in ("NEW_DB_FLAG", "BACKEND_DIR", "INSTALL_ROOT", "CERTS_DIR")}
    assert public == set(V9_LOCATIONS), public ^ set(V9_LOCATIONS)


# ── require_db ────────────────────────────────────────────────────────────

def test_require_db_existing_passes(tmp_path):
    p = tmp_path / "x.db"
    p.write_bytes(b"")
    paths.require_db(str(p), env={})


def test_require_db_missing_refuses(tmp_path):
    p = tmp_path / "missing.db"
    with pytest.raises(paths.DatabaseMissing) as ei:
        paths.require_db(str(p), env={})
    assert str(p) in str(ei.value) and paths.NEW_DB_FLAG in str(ei.value)
    assert not p.exists()                      # 拒絕時不可以順手建檔


@pytest.mark.parametrize("val", ["", "0", "true", "yes", " 1x"])
def test_require_db_only_exact_flag_allows(tmp_path, val):
    with pytest.raises(paths.DatabaseMissing):
        paths.require_db(str(tmp_path / "m.db"), env={paths.NEW_DB_FLAG: val})


def test_require_db_flag_allows_new(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="core.paths"):
        paths.require_db(str(tmp_path / "m.db"), env={paths.NEW_DB_FLAG: "1"})
    assert "全新安裝" in caplog.text


def test_require_db_flag_left_on_warns(tmp_path, caplog):
    p = tmp_path / "x.db"
    p.write_bytes(b"")
    with caplog.at_level(logging.WARNING, logger="core.paths"):
        paths.require_db(str(p), env={paths.NEW_DB_FLAG: "1"})
    assert "請移除旗標" in caplog.text
