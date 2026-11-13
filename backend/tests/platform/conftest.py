# -*- coding: utf-8 -*-
"""tests/platform 共用夾具（2026-11-13 chore/test-prune，D3＋D7）。

「讀整個真實 repo」的守門題共用的唯讀資料放在 `tests/platform/_shared_repo.py`（原始碼每個行程只讀一次；parse 後的檔每個測試模組一次、模組結束就釋放——見下面 `_release_parsed_files`）；
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


@pytest.fixture(scope="module", autouse=True)
def _release_parsed_files():
    """F3（h10 審查）：全部 backend 檔 parse 後約 1 GB（實測 995 MB／2183 檔）。留到行程結束 ⇒ 每個 xdist worker 各佔 1 GB。
    共用的好處（test_ship_tier 63 題只 parse 一次）在**同一個模組內**就拿得到，所以模組一結束就放掉；下一個要用的模組再 parse 一次。"""
    yield
    SR.release_parsed_files()
