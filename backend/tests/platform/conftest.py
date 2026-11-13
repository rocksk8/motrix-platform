# -*- coding: utf-8 -*-
"""tests/platform 共用夾具（2026-11-13 chore/test-prune，D3＋D7）。

「讀整個真實 repo」的守門題共用的唯讀資料放在 `tests/platform/_shared_repo.py`（每個行程只讀、只 parse 一次）；
這裡只是把它包成夾具，給新題用：

- `real_backend_sources`：{repo 相對路徑: 原始碼}（唯讀）。
- `new_real_ship_repo`：工廠，每次回一個全新的 `ship_tier.Repo`（used_* 各自一份，已解析檔共用）。
"""
import pytest

from tests.platform import _shared_repo as SR


@pytest.fixture(scope="session")
def real_backend_sources():
    return SR.real_sources()


@pytest.fixture(scope="session")
def new_real_ship_repo():
    return SR.new_real_repo
