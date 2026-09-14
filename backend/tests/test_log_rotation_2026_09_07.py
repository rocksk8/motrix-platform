"""`logs/server.log` 大小輪替測試（2026-09-07）。見 archive.py::_rotate_server_log_if_large()
docstring——正式機 `autostart.bat` 用 shell `>>` 寫入這個檔案，伺服器 24/7 常駐執行，
先前完全沒有任何大小上限或輪替機制。用 copytruncate（不改檔名，原地清空）而不是
改檔名輪替，因為 `apply_update.ps1` 的健康檢查寫死讀 `logs/server.log` 這個檔名。
"""
import os

import archive


def test_no_rotation_when_file_missing(tmp_path):
    log_path = str(tmp_path / "server.log")
    assert archive._rotate_server_log_if_large(log_path, max_bytes=100, keep=3) is False


def test_no_rotation_when_below_threshold(tmp_path):
    log_path = tmp_path / "server.log"
    log_path.write_bytes(b"x" * 50)
    assert archive._rotate_server_log_if_large(str(log_path), max_bytes=100, keep=3) is False
    assert log_path.stat().st_size == 50


def test_rotation_truncates_original_and_archives_content(tmp_path):
    log_path = tmp_path / "server.log"
    original_content = b"log line\n" * 1000
    log_path.write_bytes(original_content)

    rotated = archive._rotate_server_log_if_large(str(log_path), max_bytes=100, keep=3)

    assert rotated is True
    assert log_path.stat().st_size == 0, "原檔應該原地清空（copytruncate），不是被砍掉或改名"
    archived = tmp_path / "server.log.1"
    assert archived.exists()
    assert archived.read_bytes() == original_content


def test_rotation_shifts_existing_generations_and_drops_oldest(tmp_path):
    log_path = tmp_path / "server.log"
    log_path.write_bytes(b"newest content" * 20)
    (tmp_path / "server.log.1").write_bytes(b"gen1")
    (tmp_path / "server.log.2").write_bytes(b"gen2")
    (tmp_path / "server.log.3").write_bytes(b"gen3-should-be-deleted")

    rotated = archive._rotate_server_log_if_large(str(log_path), max_bytes=100, keep=3)

    assert rotated is True
    assert (tmp_path / "server.log.1").read_bytes() == b"newest content" * 20
    assert (tmp_path / "server.log.2").read_bytes() == b"gen1"
    assert (tmp_path / "server.log.3").read_bytes() == b"gen2"
    # 原本的 .3（第 4 代）超過 keep=3 上限，應該被直接砍掉，不會變成 .4
    assert not (tmp_path / "server.log.4").exists()


def test_writer_holding_append_handle_continues_correctly_after_rotation(tmp_path):
    """模擬 autostart.bat 的 `>>` 開檔方式——同一個 file handle 開著 append 模式，
    輪替（truncate）後下一次寫入應該正確從新的（空的）結尾開始，不需要重新開檔。"""
    log_path = tmp_path / "server.log"
    log_path.write_bytes(b"x" * 200)

    with open(log_path, "a", encoding="utf-8") as writer:
        writer.write("before rotation\n")
        writer.flush()

        rotated = archive._rotate_server_log_if_large(str(log_path), max_bytes=100, keep=3)
        assert rotated is True

        writer.write("after rotation\n")
        writer.flush()

    # 輪替後透過同一個 handle 寫入的內容，應該落在清空後的新檔案裡，
    # 不會神秘消失或寫到已經被搬去 .1 的舊檔案內容裡
    final_content = log_path.read_text(encoding="utf-8")
    assert "after rotation" in final_content


def test_daily_backup_triggers_rotation_regardless_of_cloud_availability(client, monkeypatch, tmp_path):
    """_rotate_server_log_if_large() 要在 _daily_backup() 一開頭、_archive_ok()
    判斷之前就跑到，不能因為雲端磁碟機沒掛載或今天已經跑過每日備份就被跳過
    ——見 archive.py::_daily_backup() 內對應註解。"""
    log_path = tmp_path / "server.log"
    log_path.write_bytes(b"x" * (60 * 1024 * 1024))  # 超過預設 50MB 門檻
    monkeypatch.setattr(archive, "_SERVER_LOG_PATH", str(log_path))
    monkeypatch.setattr(archive, "_archive_base", lambda: "")  # 模擬雲端磁碟機未掛載

    archive._daily_backup()

    assert log_path.stat().st_size == 0
    assert (tmp_path / "server.log.1").exists()
