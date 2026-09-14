"""PDF 存檔納入雲端每日備份鏡像測試（2026-09-07）。見 archive.py::_mirror_pdf_archives()
docstring——QUICK.md §11 已知限制條目：報價單/出貨單/承攬商匯款申請/發票開立簽核單/
請款單/結案報表這 6 類 PDF 檔案各自存在專案根目錄獨立資料夾，過去 `_mirror_uploads()`
完全掃不到，只有資料表本身有每日 JSON 備份，PDF 檔案本身從未被備份過。
"""
import archive
import cloud_storage
from tests.test_cloud_storage_2026_09_07 import FakeS3Client, _install_fake_s3


def test_pdf_archive_dirs_reflects_configured_paths(client, monkeypatch, tmp_path):
    """要呼叫 pdf_gen.py 的 getter 而不是直接猜預設路徑——superadmin 可能把
    base path 改到公司共用網路磁碟等自訂位置，備份要跟著實際生效的路徑走。"""
    import pdf_gen
    custom_path = str(tmp_path / "custom_quote_pdf")
    monkeypatch.setattr(pdf_gen, "_get_pdf_base", lambda: custom_path)

    dirs = dict(archive._pdf_archive_dirs())
    assert dirs["報價單"] == custom_path


def test_mirror_pdf_archives_copies_all_six_categories(client, monkeypatch, tmp_path):
    fake = FakeS3Client()
    _install_fake_s3(monkeypatch, fake)

    import pdf_gen
    category_dirs = {}
    for i, getter in enumerate([
        "_get_pdf_base", "_get_shipping_pdf_base", "_get_contractor_voucher_pdf_base",
        "_get_invoice_voucher_pdf_base", "_get_payment_request_pdf_base", "_get_case_closing_pdf_base",
    ]):
        d = tmp_path / f"pdf_cat_{i}"
        d.mkdir()
        (d / "MQ-202609-001.pdf").write_bytes(b"%PDF-fake-content")
        category_dirs[getter] = str(d)
        monkeypatch.setattr(pdf_gen, getter, lambda d=str(d): d)

    total = archive._mirror_pdf_archives()

    assert total == 6
    for subdir in ("報價單", "出貨單", "承攬商匯款申請", "開票申請憑據", "請款單", "結案報表"):
        key = f"motrix-erp-backups/PDF存檔鏡像/{subdir}/MQ-202609-001.pdf"
        assert key in fake.objects, f"missing {key}"
        assert fake.objects[key] == b"%PDF-fake-content"


def test_mirror_pdf_archives_skips_unchanged_on_rerun(client, monkeypatch, tmp_path):
    fake = FakeS3Client()
    _install_fake_s3(monkeypatch, fake)

    import pdf_gen
    quote_dir = tmp_path / "quote_pdf"
    quote_dir.mkdir()
    (quote_dir / "MQ-1.pdf").write_bytes(b"content")
    for getter in ["_get_pdf_base", "_get_shipping_pdf_base", "_get_contractor_voucher_pdf_base",
                   "_get_invoice_voucher_pdf_base", "_get_payment_request_pdf_base",
                   "_get_case_closing_pdf_base"]:
        monkeypatch.setattr(pdf_gen, getter, lambda: str(tmp_path / "empty"))
    monkeypatch.setattr(pdf_gen, "_get_pdf_base", lambda: str(quote_dir))

    assert archive._mirror_pdf_archives() == 1
    assert archive._mirror_pdf_archives() == 0, "unchanged PDF should not be re-uploaded"


def test_mirror_pdf_archives_noop_when_no_dirs_exist(client, monkeypatch, tmp_path):
    fake = FakeS3Client()
    _install_fake_s3(monkeypatch, fake)
    import pdf_gen
    for getter in ["_get_pdf_base", "_get_shipping_pdf_base", "_get_contractor_voucher_pdf_base",
                   "_get_invoice_voucher_pdf_base", "_get_payment_request_pdf_base",
                   "_get_case_closing_pdf_base"]:
        monkeypatch.setattr(pdf_gen, getter, lambda: str(tmp_path / "does-not-exist"))

    assert archive._mirror_pdf_archives() == 0
    assert fake.objects == {}


def test_daily_backup_triggers_pdf_mirror_alongside_uploads_mirror(client, monkeypatch, tmp_path):
    """確認 `_daily_backup()` 真的有掛上這個新步驟，不是寫了函式但沒接進排程。"""
    calls = []
    monkeypatch.setattr(archive, "_mirror_uploads", lambda: calls.append("uploads") or 0)
    monkeypatch.setattr(archive, "_mirror_pdf_archives", lambda: calls.append("pdf") or 0)
    monkeypatch.setattr(archive, "_archive_base", lambda: str(tmp_path))  # 讓 _archive_ok() 為 True

    archive._daily_backup()

    assert "uploads" in calls
    assert "pdf" in calls
