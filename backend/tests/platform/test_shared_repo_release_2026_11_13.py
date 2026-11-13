# -*- coding: utf-8 -*-
"""_shared_repo 的已解析檔（全部 backend 約 1 GB）不能留到行程結束（h10 審查 F3）：模組結束就放掉。"""
import re
from pathlib import Path

from tests.platform import _shared_repo as SR

HERE = Path(__file__).resolve().parent


def test_release_empties_the_shared_parsed_files(monkeypatch):
    monkeypatch.setattr(SR, "real_sources", lambda: {"backend/x.py": "A = 1\n"})
    SR.release_parsed_files()
    repo = SR.new_real_repo()
    f = repo.file("backend/x.py")
    assert f is not None and SR._SHARED_FILES, "共用字典沒有被填（這題的前提不成立）"
    SR.release_parsed_files()
    assert not SR._SHARED_FILES
    assert SR.new_real_repo().file("backend/x.py") is not None, "放掉之後要能重新 parse（只是慢一次）"
    SR.release_parsed_files()


def test_conftest_releases_after_every_module():
    src = (HERE / "conftest.py").read_text(encoding="utf-8")
    m = re.search(r'@pytest\.fixture\(scope="module", autouse=True\)\s+def _release_parsed_files\(\):.*?yield\s+SR\.release_parsed_files\(\)', src, re.S)
    assert m, "tests/platform/conftest.py 沒有「模組結束就放掉已解析檔」的 autouse 夾具（每個 worker 會多佔約 1 GB）"
