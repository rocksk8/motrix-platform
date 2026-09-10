"""2026-09-10 稽核：router 檔案與 main.py 註冊的一致性。

起因：`routers/projects.py` 定義了 19 支端點，但 commit `6089a8f`（專案管理併入
案件管理）把它從 main.py 的 import/include_router 移除後，檔案本身留了下來。
架構地圖因此寫成「僅保留舊 API 供內部沿用」——實際上那 19 支全部 404。
沒有任何機制會提醒「這個 router 檔案已經接不到系統上」。

這支測試把「哪些 router 是刻意不註冊的」變成一份**明確的白名單**：
新增 router 忘了 include 會被擋下來；要下線某個 router 則必須來這裡補一筆，
順便留下為什麼。兩個方向都不會再無聲發生。
"""
import ast
import glob
import io
import os
import re

BE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 刻意保留檔案、但不註冊進 main.py 的 router：{模組名: 原因}
#
# 目前是空的——`projects.py`（2026-08-26 專案管理併入案件管理、commit 6089a8f
# 從 main.py 移除註冊）曾經是唯一一筆，它的 592 行死碼已於 2026-09-10 直接刪除，
# 所以不需要白名單豁免了。這個機制刻意留著：下次再有「下線但檔案先留著」的情況，
# 必須來這裡補一筆寫明原因，不會像 projects.py 那樣無聲存在兩週還被架構地圖
# 寫成「僅保留舊 API 供內部沿用」（實際上 19 支端點全部 404）。
RETIRED_ROUTERS = {}


def _main_src():
    return io.open(os.path.join(BE, "main.py"), encoding="utf-8").read()


def _router_modules():
    return {
        os.path.splitext(os.path.basename(f))[0]
        for f in glob.glob(os.path.join(BE, "routers", "*.py"))
        if not os.path.basename(f).startswith("__")
    }


def _included():
    return set(re.findall(r'app\.include_router\(\s*(\w+)\.router', _main_src()))


def test_every_router_file_is_registered_or_explicitly_retired():
    """每個 routers/*.py 不是被 include_router，就是列在 RETIRED_ROUTERS。"""
    unregistered = _router_modules() - _included() - set(RETIRED_ROUTERS)
    assert not unregistered, (
        f"這些 router 檔案沒有註冊進 main.py，端點全部不可達：{sorted(unregistered)}。\n"
        f"若是新增功能忘了 include_router，請補上；"
        f"若是刻意下線，請在本檔 RETIRED_ROUTERS 補一筆並寫明原因。"
    )


def test_retired_routers_really_are_not_registered():
    """反向：白名單裡的模組若哪天又接回去了，這份名單就該同步移除，
    否則名單會慢慢腐化成沒人信的擺設。"""
    still_listed = set(RETIRED_ROUTERS) & _included()
    assert not still_listed, (
        f"這些模組已經重新註冊回 main.py，請從 RETIRED_ROUTERS 移除：{sorted(still_listed)}"
    )


def test_retired_router_files_still_exist_or_are_delisted():
    """白名單只列還存在的檔案：檔案真的被刪掉後，名單也該清掉。"""
    ghosts = set(RETIRED_ROUTERS) - _router_modules()
    assert not ghosts, (
        f"RETIRED_ROUTERS 列了不存在的檔案，請清除：{sorted(ghosts)}"
    )


def test_imported_routers_are_all_included():
    """import 進來卻沒 include 的中間狀態最容易漏（改到一半忘了收尾）。"""
    imported = set()
    for m in re.finditer(r'^from routers import (.+)$', _main_src(), re.M):
        for name in m.group(1).split(","):
            imported.add(name.strip())
    missing = imported - _included()
    assert not missing, f"這些 router 被 import 但沒有 include_router：{sorted(missing)}"
