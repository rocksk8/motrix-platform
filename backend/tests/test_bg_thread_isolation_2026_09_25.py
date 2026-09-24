"""前一題的背景執行緒不可以寫進下一題的庫（測試隔離）。

☠️ 2026-09-25：產品的背景工作（結案產 PDF、寄信、備份…）在題目結束後仍在跑；它每次 `get_db()` 讀的是
   「當下的」`db.DB_PATH`。題目結束、`client` 換成下一題的庫之後，它就寫進下一題的庫。
   看得到的症狀：建包 -n 6 下範本等價題多一筆 audit_log、先前抽樣的 `no such table: users`。
   ⚠️ 產品端沒有這個問題：正式機的 DB_PATH 整個行程不變。這是測試隔離的缺口。
🔑 修在測試端：`client` 收尾時（還原 DB_PATH 之前）等這一題啟動的背景執行緒結束。
"""
import os

from tests._subproc import run_python, utf8_env

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_a_late_background_write_lands_in_its_own_tests_db_not_the_next_one(tmp_path):
    """🔴 兩題依序在同一個行程：第一題起一個晚寫的背景執行緒，第二題開始後它才寫 ⇒ 不可以落到第二題的庫。"""
    proc = run_python(["-m", "pytest", os.path.join("tests", "_bg_leak_probe.py"), "-q", "-p", "no:cacheprovider",
                       "-p", "no:randomly", f"--basetemp={tmp_path / 'probe'}"],
                      cwd=BACKEND, env=utf8_env(), timeout=240)
    assert "2 passed" in proc.stdout, "前一題的背景寫入落到下一題的庫：\n" + proc.stdout[-1500:]
