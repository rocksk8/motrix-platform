# -*- coding: utf-8 -*-
"""D E4-O1（2026-09-28）：一般 in-process `client` fixture 的 import main 不可以寫這棵樹的首次安裝帳密檔。

原本 `init_default_admin()`／`init_demo_account()` 在 import main 時把 `backend/.initial_admin_credentials.txt`、
`.initial_demo_credentials.txt` 寫在樹上 ⇒ 共用主樹的那兩個檔一直被測試改寫（開發機自己的初始帳密被換掉）。
conftest 在 import main 之前把兩個路徑導到 session 暫存；這裡驗導向本身、以及「真的寫一次」落在哪裡。
"""
import os
from pathlib import Path

from core import paths as _paths

BACKEND = Path(__file__).resolve().parents[1]
TREE_FILES = (BACKEND / ".initial_admin_credentials.txt", BACKEND / ".initial_demo_credentials.txt")


def _state():
    return {p.name: (os.path.getmtime(p) if p.exists() else None) for p in TREE_FILES}


def _in_tree(path):
    return Path(path).resolve().is_relative_to(BACKEND)


def test_client_import_main_redirects_both_credential_files(client):
    import helpers.auth as auth
    import helpers.startup as startup
    for p in (auth._CREDENTIALS_FILE, startup._DEMO_CREDENTIALS_FILE):
        assert not _in_tree(p), "帳密檔仍指向這棵樹：%s" % p


def test_writing_credentials_under_client_does_not_touch_the_tree(client):
    """真的寫一次（init_default_admin 用的同一支），樹上兩個檔前後不變；寫進去的是暫存那一份。"""
    import helpers.auth as auth
    before = _state()
    written = auth._write_initial_credentials("e4o1_probe", "not-a-real-password")
    assert _state() == before, "寫帳密檔動到了這棵樹（D E4-O1）"
    assert written and not _in_tree(written) and Path(written).is_file()


def test_reverse_control_the_default_path_is_in_the_tree():
    """反向控制：沒有導向時的預設位置（core.paths）確實在這棵樹 ⇒ 上面兩題的判準分得出兩種情況。"""
    assert _in_tree(_paths.INITIAL_ADMIN_CREDENTIALS) and _in_tree(_paths.INITIAL_DEMO_CREDENTIALS)
