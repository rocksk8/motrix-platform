"""部署儀表板（2026-09-08 新增）——本機網頁 GUI，包裝既有的
build_deploy_package.ps1 / apply_update.ps1 / rollback_update.ps1，
把「打包→推送→套用」跟「查看正式機狀態」跟「手動回滾」變成按鈕點選。

只綁 127.0.0.1，絕不對外網卡監聽——密碼只在單次請求的記憶體生命週期內
存在（寫進子行程 stdin 後立即捨棄，不落地、不進 log、不進歷史紀錄檔）。

啟動：
    cd backend
    python tools/deploy_dashboard.py
瀏覽器打開 http://127.0.0.1:8765

見 MOTRIX-ERP-QUICK.md §12 2026-09-08 條目與 backend/tools/_dashboard_remote.ps1
（實際透過 WinRM 對正式機執行動作的腳本，這裡的 Python 只負責背景執行緒
管理／串流輸出／歷史紀錄，不直接碰 WinRM）。
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import requests
import urllib3
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import deploy_insights  # 同目錄；CORE-SPEC §9e D2／D6／D7 的純函式

# 正式機是自簽憑證（見 https_setup.ps1），這裡查狀態用的 verify=False 本來
# 就是刻意跳過驗證（跟 apply_update.ps1 的 curl.exe -k 是同一件事），關掉
# urllib3 每次都印的 InsecureRequestWarning，避免洗版這個小工具自己的輸出。
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 2026-09-11：所有 subprocess 一律帶這個旗標。本檔正常情況下是由 pythonw.exe
# 啟動的（桌面捷徑／ctl 小程式都是），**主行程本身沒有主控台**，於是每呼叫一次
# console 程式（git.exe、powershell.exe）Windows 就會替它配一個新的主控台視窗
# ——畫面上就是「CMD 視窗一直閃一下又關掉」。`/api/dev-status` 被前端每 15 秒
# 輪詢一次、而它一次跑 4 個 git，所以閃得特別勤。
#
# ⚠️ 先前看不到這個現象，是因為當時的捷徑指向 uv venv 的假 pythonw（實際是
# console 版 trampoline，見 §14.3c），它帶著一個常駐主控台，子行程直接附掛上去
# 就不會另開視窗。把捷徑改成真正的 GUI pythonw 之後，常駐視窗沒了，這個一直
# 存在的缺陷才浮出來——**不是新問題，是原本被那個常駐視窗蓋住了**。
#
# `deploy_dashboard_ctl.pyw` 從一開始就有這個旗標，這裡是補齊同一件事。
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

TOOLS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TOOLS_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent
#: 部署包裡模組清單的檔名：與打包端（tools/platform/product_select.py）同一個定義
def _lock_name():
    import importlib.util
    src = PROJECT_ROOT / "tools" / "platform" / "product_select.py"
    try:
        spec = importlib.util.spec_from_file_location("_product_select_for_dashboard", src)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.LOCK_NAME
    except Exception:
        return "modules.lock.json"
_LOCK_NAME = _lock_name()
DEPLOY_PACKAGES_DIR = PROJECT_ROOT / "deploy_packages"
HISTORY_PATH = TOOLS_DIR / "deploy_dashboard_history.json"
HISTORY_PENDING_PATH = TOOLS_DIR / "deploy_dashboard_history.pending.jsonl"   # 主檔被占用時的暫存（H-S1）
# 2026-09-08（複查後新增）：job 輸出原本只存記憶體，這個小工具本身重啟
# （例如改完程式碼要重載）就整個消失——當晚實際發生過好幾次，每次重啟
# 儀表板都得請使用者重新複製貼上先前的畫面內容才留得住紀錄。改成每個
# deploy/rollback job 同時逐行寫進磁碟，重啟儀表板／事後複查都還找得到。
DEPLOY_LOGS_DIR = TOOLS_DIR / "deploy_logs"

PROD_HOST = "172.16.10.177"
PROD_BASE_URL = f"https://{PROD_HOST}:666"

app = FastAPI(title="MOTRIX 部署儀表板")

# ══════════════════════════════════════════════════════════════════════════
# 🔴🔴 只接受本機的請求（2026-09-22 §8 HC1）
# ══════════════════════════════════════════════════════════════════════════
#
# ## ☠️ 原本的「防線」在一個不一定會執行的分支裡
# ```python
# if __name__ == "__main__":
#     uvicorn.run(app, host="127.0.0.1", port=8765)   # ← 綁本機
# ```
# **`uvicorn deploy_dashboard:app --host 0.0.0.0` 根本不會執行那一行。**
# 🔑 而**這個專案的 ERP 本體就是那樣起的**：
# ```
# autostart.bat:31   uvicorn main:app --host 0.0.0.0
# restart.bat:40     同上
# start.bat:27       同上
# ```
# ⇒ 📌 **同一台機器上的人，用同一個習慣去起這支工具，
#       `/api/deploy` 與 `/api/rollback` 就是無驗證的。**
#
# 這 13 支路由裡沒有任何一支做請求層檢查（實查：`request.client`／
# middleware／`Depends`／`_require_*` 全部 0 處），而它們做的事是
# **部署與回滾正式機**。
#
# ## 🔑 判準：防線要在**請求**這一層，不在**啟動**那一層
# 啟動參數是「這一次怎麼起它」，而請求檢查是「不管怎麼起，誰打得到」。
# ⇒ 前者是一個習慣，後者是一個性質。

#: 什麼算「本機」。**只有這兩個**。
#: ⚠️ 刻意不含 `"testclient"`（`TestClient` 的預設來源）——
#: ☠️ 放行它的話，反向控制那一題會**永遠綠**，而那道門形同虛設。
#: 📌 測試要驗正向路徑時，用 `TestClient(app, client=("127.0.0.1", 1))`。
LOCAL_CLIENT_HOSTS = frozenset({"127.0.0.1", "::1"})


def _is_local(client) -> bool:
    """這個請求是不是從本機來的。**拿不到來源就當成不是**（fail closed）。

    🔑 「我不知道它從哪來」不可以被當成「它從本機來」——
    那正是今天在 `SEND_UNKNOWN` 上裁過的同一件事：
    **一個沒有確認的結果不可以被當成通過。**
    """
    host = getattr(client, "host", None) if client else None
    return bool(host) and host in LOCAL_CLIENT_HOSTS


_NOT_LOCAL_DETAIL = (
    "部署儀表板只接受本機（127.0.0.1）的請求。"
    "它可以部署與回滾正式機，所以不對外開放。"
    "要遠端使用請改用 SSH／RDP 連到這台機器之後從本機開啟。"
)


@app.middleware("http")
async def _local_only(request, call_next):
    """所有 HTTP 請求都要來自本機。

    ⚠️ **這一層蓋不到 WebSocket** —— `@app.middleware("http")` 只吃 http scope。
    ⇒ `/ws/prod-status` 自己也要檢查一次（見那支函式）。
    🔑 「一道只有一層、而第二層明著不覆蓋的防線」是今天記過兩次的形狀。
    """
    if not _is_local(request.client):
        return JSONResponse(status_code=403, content={"detail": _NOT_LOCAL_DETAIL})
    return await call_next(request)

# ── 背景 job 追蹤（記憶體內，重啟這個小工具就重置——完整輸出另外落地在
#    DEPLOY_LOGS_DIR，重啟後記憶體內的即時串流會不見，但檔案還在）──────
_jobs_lock = threading.Lock()
_jobs: dict = {}  # job_id -> {"status": "running"|"succeeded"|"failed", "lines": [...], "action": str}

# 2026-09-08（複查後新增）：同一晚實際發生過使用者在前一次部署還沒跑完、
# 或剛失敗完幾秒內就又按了一次部署，兩個 apply_update.ps1／WinRM session
# 同時搶 port 666 的風險原本完全沒有防護。同一時間只允許一個 deploy/
# rollback job 在跑，第二個請求直接 409 拒絕，不排隊、不覆蓋。
_active_job_lock = threading.Lock()
_active_job_id: str | None = None


# ══════════════════════════════════════════════════════════════════
# `::RESULT::` 協定（P0-00，B.md §九 定版）
# ══════════════════════════════════════════════════════════════════
#
# 🔴 這一段取代「用結束碼判定 ＋ 掃關鍵字」那個組合，理由是它**低報失敗**：
# `apply_update.ps1:545` 在健康檢查**失敗**的 `-SkipAutoRollback` 分支 `exit 0`，
# 而那一段印的是「略過**自動回滾**」——舊防線找的是「**已**自動回滾」，差一個字
# ⇒ 儀表板把它記成 **成功**，而正式機上跑的是一個沒過健康檢查的版本。
#
# 🔑 而舊防線**沒有壞**：它是照當時已知的兩種輸出寫的，
#    `-SkipAutoRollback` 是同一天稍後才長出的第三個出口。
#    ⇒ 關鍵字比對是**散文比對**：它要求每一條新出口的作者，記得把字寫成
#      守門認得的形狀 —— 而那是同一個形狀的第三次（〈散文對工具是隱形的〉）。
RESULT_PROTOCOL_VERSION = 2

#: 一行、無前後空白、大小寫固定、欄位順序固定。
#: 🔴 `service` 是**必填**：少了它整行比不上 ⇒ 落進 fail-closed。
#: 🔑 那是刻意的 —— 「印了一半的結果行」與「沒印」一樣不可信。
_RESULT_RE = re.compile(
    r"^::RESULT:: v=(\d+) status=(\S+) rolled_back=(\S+) service=(\S+)"
    r" exit=(-?\d+)\s*$",
    re.M)

#: 握手行：**正在跑的那一份腳本**看得懂 v2 協定。
_PROTOCOL_RE = re.compile(r"^::PROTOCOL:: v=(\d+)\s*$", re.M)

#: `service` 的值域。只講**觀察到的事實**，不講推論。
_SERVICE_VALUES = frozenset({"up", "down", "unknown"})

#: 🔴 **值域封閉**，與 `apply_update.ps1` 的 15 條出口 **1:1**。
#: 🔑 1:1 是刻意的：新增出口時**沒有現成的值可以借**
#:    ⇒ 作者必須加一個新值 ⇒ **而加新值會被這裡的值域檢查看到**。
#: ☠️ 值域一旦開放，這裡就只能再回去猜字串 ＝ **換個地方做關鍵字比對**。
_STATUS_SUCCEEDED = frozenset({
    "checkonly_ok",                 # :140  -CheckOnly 且 ping 成功
    "success",                      # :646  正常成功
    "rollback_ok",                  # rollback_update.ps1 正常完成
})
_STATUS_FAILED = frozenset({
    "not_prod_machine",             # :131
    "bad_args",                     # :148
    "package_missing",              # :151
    "package_invalid",              # :155
    "duplicate_version",            # :172
    "backup_failed",                # :228  正式庫尚未被觸碰
    "migration_dryrun_failed",      # :276  正式庫尚未被觸碰
    "user_cancelled",               # :311
    "copy_failed_backend",          # :358  🔴 半套用、沒有人還原、服務已停
    "copy_failed_frontend",         # :361  🔴 同上
    "checkonly_failed",             # :143
    "unhealthy_not_rolled_back",    # :545  🔴 P0-00 本尊：exit 0 而它是失敗
    "unhealthy_rolled_back",        # :621
    # rollback_update.ps1 那一側
    "rollback_not_prod_machine", "rollback_snapshot_missing",
    "rollback_db_snapshot_missing", "rollback_user_cancelled",
    "rollback_failed",
})
_STATUS_ALL = _STATUS_SUCCEEDED | _STATUS_FAILED

#: 舊的關鍵字比對 —— **留著當第二道，不要拿掉。**
#: 🔑 理由不是它準，是**兩道獨立的防線不會同時因為同一個原因失效**。
#: ☠️ 「改用新方法就把舊的刪掉」會讓一個本來有兩層的地方安靜地變成一層。
_LEGACY_FAIL_RE = re.compile(r"更新失敗|已自動回滾|\[FAIL\]")

#: 🔴 **哪些動作要講這個協定：預設「要」。**
#: ☠️ 反過來寫成白名單的話，日後新增一個動作**忘了加進去**就會安靜地
#:    退回舊行為 —— 而那正是這一整件事要修的東西。
#: ⇒ 只有這裡列出來的可以不講，而每一個都要寫理由。
#: 🔴 **收不到握手時可以退回舊判定的動作** —— 只有 `rollback`，而它有機制層的理由。
#:
#: ☠️ `_dashboard_remote.ps1` 的 `rollback` 分支（`:149-170`）**沒有**預先複製
#:    套件裡的 `backend\tools\*`（那段只在 `deploy` 分支的 `:98-104`）
#:    ⇒ 新的 `rollback_update.ps1` **只能靠一次成功的部署**才會上正式機。
#: ⇒ 而危險的順序正是最可能發生的那一條：
#:      部署失敗 ⇒ 自動回滾用套用前快照蓋回去 ⇒ 正式機的 tools **退回舊版**
#:      ⇒ 使用者手動回滾 ⇒ 舊腳本不印那些行
#:      ⇒ 無條件 fail-closed 會把它記成「回滾失敗」
#:      ⇒ **而那一刻使用者最需要的正是「回滾到底成功了沒」**
#:
#: ⚠️ **`deploy` 不在這裡，而那是有理由的不對稱，不要「統一」掉**：
#:    deploy 有預先複製 ⇒ 跑的一定是新版 ⇒ 收不到握手代表**真的有問題**
#:    （例如包裡缺 `backend\tools\`，那段複製會安靜跳過）
#:    ⇒ 對 deploy 而言「收不到握手」本身就是一個要擋下來的訊號。
_PROTOCOL_LEGACY_FALLBACK = {"rollback"}

#: `decide_outcome` 認得的動作。**不在這裡面的一律拋錯**（§42b）。
#: ⚠️ `build` 刻意**不在**：它走 `_PROTOCOL_EXEMPT`，根本不該走到判定這一支。
_KNOWN_ACTIONS = {"deploy", "rollback"}

_PROTOCOL_EXEMPT = {
    # `build` 跑的是本機打包（`build_deploy_package.ps1`），**完全不碰正式機**
    # ⇒ `rolled_back` 對它沒有意義，硬要它印一個 `not_applied` 只是噪音。
    # ⚠️ 而它的失敗本來就擋得住：打包腳本任何一步失敗都 `exit 1`。
    "build",
}


#: 🔴 **同一個機器值，兩個動作講不同的話**（§41a）。
#:
#: ☠️ 統一成一句的話，回滾前的畫面會說「**正式機沒有被碰過**」，
#:    而它剛剛才被一次失敗的部署動過 —— 🔑 而使用者正是在**剛出事、
#:    正在回滾**的時候看它。
#:
#: 🔑 **參考點不同**，不是措辭不同：
#:      deploy 的 not_applied   ＝ 正式機完全沒被碰過
#:      rollback 的 not_applied ＝ 還原沒開始，維持在按回滾之前的樣子
#: ⇒ 所以**不可以**寫成「基本文案 ＋（回滾）」那種後綴 ——
#:   那樣兩個動作不同了，而意思沒變。
_ROLLED_BACK_TEXT = {
    "deploy": {
        "not_applied": "正式機沒有被碰過。",
        "applied": "新版已經完整寫進正式機。",
        "applied_no_restore": "新版只寫了一半就中斷，而且沒有還原。",
        # 🔴 `restoring` 在 **deploy 表裡也要有**，而且不可以借用
        # `applied_no_restore` 那一句 —— 那一句含「**而且沒有還原**」，
        # ☠️ 方向相反：自動回滾（`apply_update.ps1:632`）正在還原，
        #    而那一次操作使用者按的是**部署** ⇒ 畫面查的是 deploy 這張表。
        "restoring": "正在把套用前的版本寫回正式機，還沒有做完。",
        "restored": "已還原到套用前的版本。",
        "restored_unhealthy": "已還原到套用前的版本，但它仍然沒有回應。",
    },
    "rollback": {
        "not_applied": "還原沒有開始，正式機維持在你按回滾之前的樣子。",
        "applied": "正式機上是還原之前的那一版，這次回滾沒有改動它。",
        "applied_no_restore": "還原做到一半就中斷了，正式機現在不是完整的任何一版。",
        "restoring": "正在把快照寫回正式機，還沒有做完。",
        "restored": "已經還原到你選的那個快照。",
        "restored_unhealthy": "已經還原到你選的那個快照，但它仍然沒有回應。",
    },
}


def parse_result_line(output: str):
    """把**最後一行** `::RESULT::` 拆成 dict，沒有就回 `None`。

    ⚠️ 與 `decide_outcome` 共用同一個 `_RESULT_RE` —— **不要在這裡另寫一份**。
    ☠️ 兩份正則會分岔，而分岔之後「判定說失敗、畫面說成功」，
       兩邊各自都看起來很合理。
    """
    found = _RESULT_RE.findall(output or "")
    if not found:
        return None
    version, status, rolled_back, service, exit_field = found[-1]
    return {"v": version, "status": status, "rolledBack": rolled_back,
            "service": service, "exit": exit_field}


def describe_rolled_back(value: str, action: str) -> str:
    """把 `rolled_back` 的機器值變成人話。**同一個值，兩個動作講不同的話。**

    🔴 這支函式存在的唯一理由是 §44 那個根因：
    `rolled_back` 在兩支腳本裡曾經回答**兩個不同的問題** ——
    ```
    甲「磁碟上現在是什麼」   乙「這一次執行改動了什麼」
    ```
    §44 採**讀法乙**，機器值因此統一成一份；
    ☠️ **而參考點仍然不同** —— 同樣是「這一次沒有改動磁碟」：
    ```
    deploy    正式機**完全沒被碰過**
    rollback  還原**沒開始**，而正式機通常剛被一次失敗的部署動過
    ```
    ⇒ 機器值一份、人話兩份。**這裡就是那個「兩份」。**

    ⚠️ 認不得的值也要給得出話 —— 這支函式在畫面路徑上，
    ☠️ 回空字串的話使用者看到一片空白，而他分不出那是「沒有資料」還是「狀態正常」。
    """
    # 🔴 **認不得的 `action` 要明著說認不得，不可以靜默退回 deploy 的文案。**
    #
    # ☠️ 先前這裡是 `.get(action) or _ROLLED_BACK_TEXT["deploy"]` ——
    #    `action="rollback "`（多一個空白）、`"Rollback"`、甚至 `None`
    #    都會拿到 deploy 的那一句「**正式機沒有被碰過**」，
    #    而它可能剛剛才被一次失敗的部署動過。**逐字就是 §41a 要防的那句話。**
    # 🔑 而我加那個 `or` 的動機是「不要回空字串」——
    #    **它順便吞掉了「認不得」**（〈防護的副作用落在盲側〉）。
    #
    # 🔴 **分界是「誰錯了」**（§56），不是「哪一側」：
    # ```
    # action 不認得 ⇒ **我們自己的 bug**
    #                 它由我們的碼從一個封閉集合寫入，沒見過的值代表程式錯了
    #                 ⇒ **拋錯**，讓它當場爆
    # value  不認得 ⇒ **對面送上來的資料有問題**
    #                 正式機上的 ps1 可能是舊的、或印錯了
    #                 ⇒ **顯示「看不懂」並讓它被看見**，不可以爆
    # ```
    # ☠️ 反過來的話：value 拋錯 ⇒ 一份壞掉的輸出讓**整個畫面空白**，
    #    而使用者連「回滾成功了沒」都看不到 —— 那是最不能出事的時刻。
    # ☠️ 而 action 不拋錯 ⇒ 靜默退回 deploy 的文案 ⇒ 畫面說
    #    「正式機沒有被碰過」，而它剛剛才被一次失敗的部署動過。
    # ⚠️ 兩處都用 `in` 判斷，**不要用 `or`**（§54d）：
    # ☠️ `or` 會把「沒有這個鍵」與「鍵在而值是空字串」合併成同一種處置
    #    ⇒ 哪天有人把某個值的文案暫時留空，畫面會說「狀態回報看不懂（applied）」
    #    —— 🔑 **一個看起來像正確處理的錯誤訊息**，而實情是有人把文案刪了。
    # 📌 〈null 不等於 0〉：合併之後錯誤看起來完全正常，所以沒有人報修。
    if action not in _ROLLED_BACK_TEXT:
        raise ValueError(
            "describe_rolled_back() 不認得 action=%r（認得的有 %s）——"
            "這個值由我們自己的碼寫入，沒見過的值代表程式錯了，"
            "不是正式機送上來的資料有問題。"
            % (action, "、".join(sorted(_ROLLED_BACK_TEXT))))
    table = _ROLLED_BACK_TEXT[action]
    if value not in table:
        return "狀態回報看不懂（%s）——這不是預期的值。" % value
    text = table[value]
    if not text.strip():
        return "這個狀態（%s）的說明是空的——文案表漏填了，不是狀態有問題。" % value
    return text


def used_legacy_protocol(output: str, action: str) -> bool:
    """這一次的判定**是不是用舊協定做的**。

    🔴 存在的理由是「退化必須看得見」：
    ```
    有握手的成功   結果行說 success，而那一份腳本**保證會印**
    舊判定的成功   結束碼是 0，而**我們不知道它有沒有真的做完**
    ```
    ☠️ 兩者在畫面上長得一樣，而使用者正是在**剛出事、正在回滾**時看它 ——
    🔑 那是最不該讓他誤以為事情已經確認好的時刻。

    ⚠️ 三種情形不是兩種：
    ```
    rollback 無握手 ⇒ True
    rollback 有握手 ⇒ False   ← 少了這一條，「每次都標」的實作會綠，
                                而**每次都出現的警告與沒有警告是同一件事**
    deploy          ⇒ False   它有預先複製，不走那條退路
    ```
    """
    return (action in _PROTOCOL_LEGACY_FALLBACK
            and not protocol_handshake_seen(output))


def protocol_handshake_seen(output: str) -> bool:
    """輸出裡有沒有 `::PROTOCOL:: v=2`。

    🔑 它回答的是「**正在跑的那一份腳本**看不看得懂 v2」，
    不是「這次成功了沒」。兩者混在一起的話，一支舊腳本的成功會被當成
    協定成立，而它根本沒有印結果行。
    """
    m = _PROTOCOL_RE.search(output or "")
    return bool(m) and m.group(1) == str(RESULT_PROTOCOL_VERSION)


def _legacy_outcome(returncode: int, output: str) -> str:
    """舊判定：結束碼 ＋ 關鍵字第二道。

    ⚠️ 這**不是**「比較寬鬆的版本」，它是**2026-09-22 之前的全部** ——
    而 P0-00 正是因為它低報失敗才存在（`:545` 那條 `exit 0`）。
    ⇒ 只在「對方腳本太舊、根本不會印結果行」時用它，**而畫面要明著標出來**。
    """
    if returncode != 0:
        return "failed"
    if _LEGACY_FAIL_RE.search(output or ""):
        return "failed"
    return "succeeded"


def decide_outcome(returncode: int, output: str,
                   action: str = "deploy") -> str:
    """這一次部署到底是成功還是失敗。回 `"succeeded"` 或 `"failed"`。

    ## 🔴 `exit=0` 不等於成功

    `unhealthy_not_rolled_back`（`apply_update.ps1:545`）的結束碼**就是 0** ——
    健康檢查沒過、而 `-SkipAutoRollback` 讓它不回滾 ⇒ 新程式碼留在正式機上。
    ☠️ 用結束碼判的話，那一次會被記成成功，**而沒有人會來看**。

    ## ⚠️ `action` 預設 `"deploy"`（**嚴格的那一邊**）

    🔑 與 `_PROTOCOL_EXEMPT` 寫成例外清單同一個方向：**豁免要舉手，不是預設。**
    ⇒ 呼叫端忘了傳 `action`，拿到的是嚴格判定，**而不是退路**。

    ## 🔴 fail-closed：撈不到結果行 ⇒ 失敗

    現在的形狀是「沒比對到關鍵字 ＋ 結束碼 0 ⇒ 成功」＝ **fail-open**，
    而「**新增一條出口時忘記印那一行**」是**預設會發生**的事，不是例外。
    ⇒ fail-open 時那條新出口會安靜地全部記成成功；
      fail-closed 時它在第一次被走到就紅。
    """
    # 🔴 **沒見過的動作要當場爆，不可以回傳一個判定**（§42b）。
    #
    # ☠️ 回傳的話，那個判定是**猜的** —— 而它會被寫進部署歷史。
    # 🔑 〈計數器要有落點〉的變體：「`build` 哪天真的接進 dashboard，
    #    **誰會記得回來加**？」靠「以後記得」＝沒有落點。
    # ⇒ 拋錯讓那一天當場爆，**不需要任何人記得**。
    # 📌 而它同時讓「不加 `build ⇒ False` 那個案例」這個決定變成**安全的**：
    #    遺漏變成不可能，不是靠一題去守。〈修作法不要修結果〉。
    #
    # ⚠️ 訊息裡要有那個 action 的名字 —— 排錯的人拿到的第一份線索就是這句話。
    if action not in _KNOWN_ACTIONS:
        raise ValueError(
            "decide_outcome() 不認得 action=%r（認得的有 %s）——"
            "一個沒見過的動作拿不到判定，因為那個判定會是猜的。"
            % (action, "、".join(sorted(_KNOWN_ACTIONS))))
    text = output or ""
    # 🔴 **只有明著開了 fallback 的動作**（目前只有 `rollback`）才走這條，
    # 而條件是**連握手都收不到** —— 收得到握手卻沒有結果行，仍然是 fail-closed。
    # 🔑 那個區別重要：握手在＝腳本是新的＝它有能力印結果行
    #    ⇒ 沒印就是真的出事了，不是版本舊。
    if used_legacy_protocol(text, action):
        return _legacy_outcome(returncode, text)
    found = _RESULT_RE.findall(text)
    if not found:
        return "failed"                      # 🔴 fail-closed
    # ⚠️ 取**最後一行**：`apply_update.ps1` 會呼叫別的腳本，而那些也可能印
    #    `::RESULT::` —— 取第一行的話**子行程的結果會蓋掉真正的那一條出口**。
    version, status, _rolled_back, service, _exit_field = found[-1]
    if version != str(RESULT_PROTOCOL_VERSION):
        # 跑的不是我們送過去那一份（正式機上那一支比較舊）
        # ⇒ 舊的那一份印不出新的狀態值，拿它的輸出去判等於在猜。
        return "failed"
    if status not in _STATUS_ALL:
        # 含 ps1 的預設值 `unknown`（忘記給狀態就印它）。
        return "failed"
    if service not in _SERVICE_VALUES:
        # 值域外的 `service` 代表這一行不是我們認得的那個協定產生的。
        return "failed"
    if status not in _STATUS_SUCCEEDED:
        return "failed"
    # ⚠️ 兩個訊號矛盾時一律往失敗倒：結果行說成功而結束碼非 0，
    #    代表有一條路徑印錯了 —— 而「印錯」不可以蓋掉一個真實的非 0 結束碼。
    if returncode != 0:
        return "failed"
    # 第二道：舊的關鍵字比對。同上，矛盾時當失敗。
    if _LEGACY_FAIL_RE.search(text):
        return "failed"
    return "succeeded"


#: S-U01（2026-09-25 C 稽核）：WinRM 掛住不回時 job 會永遠 running、鎖永遠不放。
#: 每個動作一個上限（分鐘）。回滾的上限一定比轉換長（稽核 A-1：原本回滾落在預設 20，比轉換 45 還短）。
_JOB_TIMEOUT_MIN = {
    "build": 90, "deploy": 45, "rollback": 60,
    "upgrade-push": 30, "upgrade-stop-services": 15, "upgrade-start-services": 15,
    "upgrade-backup": 90, "upgrade-convert": 45,
    "upgrade-rollback-code": 60, "upgrade-rollback-full": 90, "upgrade-rollback-full-preview": 10,
}
_JOB_TIMEOUT_DEFAULT_MIN = 20

#: 會在正式機上「改東西、而且不是原子」的動作：逾時**不自動中止**（稽核 A-1：砍掉本機 PowerShell 會讓
#: 遠端的回滾／轉換停在一半）。改成標記逾時、鎖不放，由人看過 log 後按「解除鎖定」（要寫原因）。
_NO_KILL_ON_TIMEOUT = frozenset({
    "deploy", "rollback", "upgrade-stop-services", "upgrade-start-services",
    "upgrade-backup", "upgrade-convert", "upgrade-rollback-code", "upgrade-rollback-full",
})


def _start_watchdog(proc, job_id: str, action: str):
    limit = _JOB_TIMEOUT_MIN.get(action, _JOB_TIMEOUT_DEFAULT_MIN) * 60
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["pid"] = proc.pid

    def _watch():
        try:
            proc.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            if action in _NO_KILL_ON_TIMEOUT:
                msg = (f"[逾時] {action} 超過 {limit // 60} 分鐘還沒結束。本機**仍在等待**，沒有中止任何東西——"
                       "正式機上的動作可能仍在進行，中止會讓它停在一半。⚠ 不要重按；先看「查看正式機 log」與健康檢查，"
                       "確認正式機已經停下來之後，再按「解除鎖定」（要寫原因）。")
            else:
                msg = (f"[逾時] {action} 超過 {limit // 60} 分鐘沒有結束，已中止本機這一側（這個動作不改正式機）。"
                       "先用健康檢查確認正式機狀態。")
            with _jobs_lock:
                if job_id in _jobs:
                    _jobs[job_id]["lines"].append(msg)
                    _jobs[job_id]["timedOut"] = True
            if action not in _NO_KILL_ON_TIMEOUT:
                _kill_tree(proc.pid)
    threading.Thread(target=_watch, daemon=True).start()


def _kill_tree(pid: int):
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=CREATE_NO_WINDOW)


def _final_status(job_id: str, ok: bool) -> str:
    """B-3：逾時與失敗分開——「逾時」的意思是正式機狀態不明，處置跟「失敗」不同。"""
    if _jobs.get(job_id, {}).get("timedOut"):
        return "timeout"
    return "succeeded" if ok else "failed"


def _run_job(job_id: str, action: str, cmd: list, input_text: str = None):
    global _active_job_id
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "lines": [], "action": action}

    DEPLOY_LOGS_DIR.mkdir(exist_ok=True)
    log_path = DEPLOY_LOGS_DIR / f"{time.strftime('%Y%m%d_%H%M%S')}_{action}_{job_id[:8]}.log"

    try:
        with log_path.open("a", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE if input_text is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(PROJECT_ROOT),
                creationflags=CREATE_NO_WINDOW,
            )
            if input_text is not None:
                proc.stdin.write(input_text)
                proc.stdin.close()
            _start_watchdog(proc, job_id, action)

            for line in proc.stdout:
                stripped = line.rstrip("\n")
                with _jobs_lock:
                    _jobs[job_id]["lines"].append(stripped)
                log_file.write(stripped + "\n")
                log_file.flush()
            proc.wait()

        joined = "\n".join(_jobs[job_id]["lines"])
        if action in _PROTOCOL_EXEMPT:
            # 不講協定的動作（見 `_PROTOCOL_EXEMPT` 的理由）走舊路：
            # 結束碼 ＋ 關鍵字第二道。
            # ⚠️ 這一條**不是**「以後再說」——`build` 不碰正式機，
            #    `rolled_back` 對它沒有意義。
            outcome = _legacy_outcome(proc.returncode, joined)
            # ⚠️ `build` 是**豁免**不是**退化** —— 它從來就不講這個協定。
            # ☠️ 標成 legacy 的話那句警告會在**每一次打包**出現，
            #    而一個每次都出現的警告與沒有警告是同一件事。
            legacy = False
        else:
            # 🔴 判定**經過** `decide_outcome`，不是在這裡重寫一次。
            # ☠️ 一支接縫寫好了而沒有人呼叫，跟沒有寫是一樣的
            #    （`reminder_stage()` 那次：四題全綠而產品碼零呼叫者）。
            legacy = used_legacy_protocol(joined, action)
            outcome = decide_outcome(proc.returncode, joined, action=action)
            if legacy:
                # 🔴 **退化必須看得見。** 少了這一行，一次「用舊協定判的」
                # 與一次「用新協定判的」在畫面上完全相同 ——
                # ☠️ 而靜默的退化正是這一整件事要修的東西。
                _jobs[job_id]["lines"].append(
                    "[注意] 正式機上的腳本沒有回報 v2 協定"
                    "（`::PROTOCOL:: v=2`）——**本次以舊版協定判定**："
                    "只看結束碼與關鍵字，判不出「健康檢查沒過但沒回滾」那一種。"
                    "下一次成功部署之後就會恢復。")
        # 🔴 **把結果行留給畫面** —— 判定是二元的，而使用者要的是
        # 「正式機現在怎樣」。少了這一段，`describe_rolled_back()` 會是一支
        # **沒有人呼叫的接縫**（`reminder_stage()` 那次的形狀）。
        parsed = parse_result_line(joined)
        with _jobs_lock:
            _jobs[job_id]["status"] = "timeout" if _jobs[job_id].get("timedOut") else outcome
            _jobs[job_id]["legacyProtocol"] = legacy
            _jobs[job_id]["result"] = parsed
            # ⚠️ 只有**講協定的動作**才問文案 —— `describe_rolled_back`
            # 對沒見過的 `action` 會拋錯（§56，那是刻意的），
            # 而 `build` 不在那張表裡。
            # 📌 `parsed` 對 `build` 本來就是 `None`（它不印結果行），
            #    這裡多一道是因為**「本來就是」是一個會變的事實**。
            _jobs[job_id]["rolledBackText"] = (
                describe_rolled_back(parsed["rolledBack"], action)
                if (parsed and action in _ROLLED_BACK_TEXT) else "")

        if action in ("deploy", "rollback"):
            # S-P01（2026-09-25 C 稽核）：原本這裡的 `success` 從未賦值 ⇒ 每一次部署／回滾在這一行 NameError，
            # 歷史從來沒寫進去，「15 分鐘內剛失敗」的警告因此永遠不觸發。成功的定義就是上面判定的 outcome。
            _append_history(action, job_id, outcome == "succeeded", str(log_path))
    finally:
        # 不管上面成功、失敗、還是中途拋例外，只要是這個 job 占著鎖，
        # 一定要釋放——否則儀表板重啟前這把鎖會卡死，之後所有部署/回滾
        # 請求永遠拿到「已經有工作在跑」的 409。
        if action in ("deploy", "rollback"):
            with _active_job_lock:
                if _active_job_id == job_id:
                    _active_job_id = None


def _log_remote_failure(action: str, text: str) -> None:
    """遠端失敗的原文寫進 deploy_logs/remote_<action>_last_error.txt（gitignored）：
    畫面上的訊息使用者看得到、開發端看不到；排查不可以靠請使用者截圖。"""
    try:
        DEPLOY_LOGS_DIR.mkdir(exist_ok=True)
        (DEPLOY_LOGS_DIR / f"remote_{action}_last_error.txt").write_text(
            time.strftime("%Y-%m-%d %H:%M:%S") + "\n" + text + "\n", encoding="utf-8")
    except OSError:
        pass


def _remote_error(proc) -> str:
    """遠端腳本失敗時給畫面的訊息：stdout 與 stderr 都要帶。
    2026-09-25 使用者實跑只看到「連線失敗」——PowerShell 未攔截的例外只寫 stderr，原本整段被丟掉。"""
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    parts = [x[-1500:] for x in (out, err) if x]
    return "\n".join(parts) if parts else f"連線失敗（exit {proc.returncode}，沒有任何輸出）"


def _ps_cmd(script_path: Path, named_args: dict = None) -> list:
    """組出呼叫某支 .ps1 的 powershell 指令列表，並強制 Console 輸出用 UTF-8
    （這台機器的預設主控台編碼不是 UTF-8，Write-Host 的中文字不強制轉碼會
    亂碼，見 MOTRIX-ERP-QUICK.md 的 Windows locale 編碼陷阱記錄）。

    named_args 是 {參數名: 值} 的 dict（不是攤平的 flat list）——**參數名本身
    是我自己寫死的固定字串，直接原樣輸出、不加引號，PowerShell 才認得出這是
    參數旗標**；只有「值」需要用單引號跳脫（值可能來自使用者輸入）。之前的
    版本把參數名跟值混在同一個 list 裡、統一加引號，導致 `-Action` 被包成
    `'-Action'` 這個純字串常值，PowerShell 認不出是旗標，改去綁定成第一個
    位置參數的值，撞上 ValidateSet 驗證失敗（2026-09-08 實際發生過，見
    MOTRIX-ERP-QUICK.md §12 條目）。"""
    args_str = ""
    if named_args:
        parts = []
        for name, value in named_args.items():
            escaped = str(value).replace("'", "''")
            parts.append(f"-{name} '{escaped}'")
        args_str = " " + " ".join(parts)
    inner = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
        f"& '{script_path}'{args_str}"
    )
    return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", inner]


# 2026-09-08 安全性複查補上：package/snapshotTimestamp 都會被直接拼進檔案
# 路徑（deploy/rollback 兩條路徑），這個工具雖然只綁 loopback、外部攻擊者
# 連不到，但仍不該省略基本輸入驗證——限定只能是「乾淨的資料夾名稱」
# （字母/數字/底線/連字號），擋掉任何含路徑分隔符或 `..` 的路徑穿越嘗試。
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _is_safe_name(value: str) -> bool:
    return bool(value) and bool(_SAFE_NAME_RE.match(value)) and ".." not in value


_history_lock = threading.Lock()


def _append_history(action: str, job_id: str, success: bool, log_path: str = ""):
    entry = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "success": success,
        "logPath": log_path,
    }
    # 讀→改→寫要在鎖內、寫入要原子（暫存檔＋os.replace）：解除鎖定端點與 job 收尾執行緒會同時寫，
    # 原本兩個 write_text 交錯 ⇒ 合法 JSON 後面接上另一次較長寫入的殘字、且其中一筆遺失（2026-09-26 B 反向控制時抓到）。
    # 讀取端（/api/history、最近失敗警告）也要拿同一把鎖：Windows 上目標檔被開著時 os.replace 丟 PermissionError，
    # 第一版只鎖寫入端 ⇒ 儀表板輪詢時 300 次寫入掉 145 筆（D 稽核 2026-09-26）。行程外的人（防毒、手動開檔）擋住時短暫重試，
    # 仍不行就直接覆寫——鎖內沒有別的寫入者，直接寫不會交錯；寧可不原子也不掉筆。
    with _history_lock:
        # 讀不到 ≠ 空清單（D 稽核 H-S1：讀檔丟一次 PermissionError ⇒ 原本把 200 筆蓋成 1 筆，而寫回後又讀得懂，警告也不會出現）：
        # 被占用 ⇒ 重試後仍不行就把這一筆記到旁邊的 pending 檔、不碰主檔；讀不懂 ⇒ 先封存壞檔再開新檔。
        history = _read_history_locked()
        if history is _UNREADABLE_BUSY:
            with open(HISTORY_PENDING_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return
        if history is None:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            try:
                os.replace(HISTORY_PATH, HISTORY_PATH.with_name(f"{HISTORY_PATH.name}.corrupt-{stamp}"))
            except OSError:
                pass
            history = [{"time": entry["time"], "action": f"歷史紀錄讀不懂，已封存為 {HISTORY_PATH.name}.corrupt-{stamp}，從這一筆重新開始",
                        "success": False, "logPath": ""}]
        # pending 的落點（D 稽核 H-S2）：主檔讀得到的下一次寫入就依時間併回，寫成功後刪檔
        had_pending = HISTORY_PENDING_PATH.exists()
        history = _merge_pending(history, _read_pending_locked())
        history.insert(0, entry)
        text = json.dumps(history[:200], ensure_ascii=False, indent=2)
        tmp = HISTORY_PATH.with_name(f"{HISTORY_PATH.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(text, encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(tmp, HISTORY_PATH)
                break
            except PermissionError:
                time.sleep(0.05 * (attempt + 1))
        else:
            HISTORY_PATH.write_text(text, encoding="utf-8")
            try:
                tmp.unlink()
            except OSError:
                pass
        if had_pending:
            try:
                HISTORY_PENDING_PATH.unlink()
            except OSError:
                pass        # 刪不掉 ⇒ 下次再併一次；_merge_pending 去重，不會重複列


_UNREADABLE_BUSY = object()     # 被別的行程占用、重試後仍讀不到（內容未知，不可以當成空的覆寫）


def _read_history_locked():
    """呼叫端必須持有 _history_lock。檔案不存在 ⇒ []；被占用讀不到 ⇒ _UNREADABLE_BUSY；讀得到但不是合法 JSON 清單 ⇒ None。"""
    if not HISTORY_PATH.exists():
        return []
    for attempt in range(5):
        try:
            text = HISTORY_PATH.read_text(encoding="utf-8")
            break
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
        except FileNotFoundError:
            return []
    else:
        return _UNREADABLE_BUSY
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, list) else None


def _read_pending_locked() -> list:
    """呼叫端必須持有 _history_lock。主檔被占用時另存的紀錄（一行一筆 JSON）；沒有 ⇒ []。"""
    if not HISTORY_PENDING_PATH.exists():
        return []
    out = []
    try:
        lines = HISTORY_PENDING_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def _merge_pending(history: list, pending: list) -> list:
    """pending 放在最前面（新到舊）：主檔每次寫入都先併掉 pending，所以 pending 裡的一定比主檔裡的新；
    不依 time 排序（秒級時間戳在同一秒會並列，排不出先後）。同一筆（時間＋動作＋結果＋log 都相同）只留一份——pending 刪不掉時下次再併也不會重複。"""
    if not pending:
        return history
    def k(e):
        return (e.get("time"), e.get("action"), e.get("success"), e.get("logPath"))
    seen = {k(e) for e in history}
    extra = [e for e in pending if k(e) not in seen]
    return list(reversed(extra)) + history


def _read_history():
    """讀取端用：讀不到（占用或壞檔）一律 None；還沒併回的 pending 一併列出（畫面與警告看到的是完整的紀錄）。"""
    with _history_lock:
        h = _read_history_locked()
        if h is _UNREADABLE_BUSY or h is None:
            return None
        return _merge_pending(h, _read_pending_locked())


def _try_acquire_job_lock(job_id: str) -> bool:
    """同一時間只允許一個 deploy/rollback job 在跑，避免兩個 apply_update.ps1
    ／WinRM session 同時搶正式機 port 666（2026-09-08 當晚複查時發現完全
    沒有這層防護，使用者在前一次還沒跑完或剛失敗完幾秒內就可能又按一次）。"""
    global _active_job_id
    with _active_job_lock:
        if _active_job_id is not None:
            return False
        _active_job_id = job_id
        return True


def _recent_failure_warning() -> str:
    """檢查最近一筆部署/回滾歷史紀錄，如果是 15 分鐘內的失敗，回傳一段
    警告文字給前端的二次確認卡片顯示——2026-09-08 當晚實際發生連續三次
    盲目重試都沒先看清楚上一次到底發生什麼事，這裡至少在畫面上提醒一次。"""
    history = _read_history()
    if history is None:
        # 讀不到不等於「沒有失敗」：說出來，不靜默放行（唯讀動作的缺口要輸出）
        return "⚠ 部署歷史紀錄讀不到（deploy_dashboard_history.json），無法確認上一次部署／回滾的結果；請先看 deploy_logs 再決定是否執行。"
    if not history:
        return ""
    last = history[0]
    if last.get("success"):
        return ""
    try:
        last_time = time.mktime(time.strptime(last["time"], "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return ""
    if time.time() - last_time > 15 * 60:
        return ""
    return f"⚠️ 上一次{last.get('action', '操作')}（{last.get('time', '')}）失敗了，還沒查清楚原因就再試,可能會讓正式機被反覆停/啟服務。確定要繼續嗎？"


# ── 靜態頁面 ──────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return FileResponse(str(TOOLS_DIR / "deploy_dashboard.html"))


# ── 狀態查詢（不需要密碼）──────────────────────────────────────────────────

@app.get("/api/dev-status")
def dev_status():
    def _git(*args):
        try:
            return subprocess.run(
                ["git", *args], cwd=str(PROJECT_ROOT), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=10,
                creationflags=CREATE_NO_WINDOW,
            ).stdout.strip()
        except Exception:
            return ""

    branch = _git("branch", "--show-current")
    commit = _git("log", "-1", "--format=%h %s")
    dirty = bool(_git("status", "--porcelain", "--", "backend", "frontend"))
    # §9e D7：原本寫死 origin/master；新版在 platform 分支 ⇒ 取目前分支的上游，沒有上游回 None 不猜
    upstream, ahead = deploy_insights.upstream_ahead(PROJECT_ROOT)
    return {"branch": branch, "commit": commit, "dirty": dirty, "upstream": upstream, "aheadOfOrigin": ahead}


def _check_prod_status() -> dict:
    """實際打正式機的健康檢查＋版本查詢，REST 端點跟 WebSocket 共用同一份
    邏輯，避免以後改一邊忘了改另一邊（這個專案已經在部署工具腳本本身踩過
    好幾次這種「兩份副本沒同步」的坑）。"""
    healthy = False
    try:
        r = requests.get(f"{PROD_BASE_URL}/api/ping", verify=False, timeout=5)
        healthy = r.ok
    except Exception:
        pass

    deployed = {}
    try:
        r2 = requests.get(f"{PROD_BASE_URL}/api/system/deployed-version", verify=False, timeout=5)
        if r2.ok:
            deployed = r2.json()
    except Exception:
        pass

    return {"healthy": healthy, "deployed": deployed, "checkedAt": time.strftime("%Y-%m-%d %H:%M:%S")}


@app.get("/api/prod-status")
def prod_status():
    return _check_prod_status()


# ── 正式機狀態即時推送（WebSocket，2026-09-08 新增）──────────────────────────
# 先前是前端每 15 秒 fetch 一次 /api/prod-status，畫面關掉分頁 setInterval
# 自然停止，但仍是「輪詢」而非「主機主動推」，部署/回滾剛結束的那個當下
# 最多要等到下一次輪詢才會更新畫面。改成 WebSocket：連線期間伺服器每幾秒
# 主動推一次最新狀態，前端收到任何訊息（例如部署 job 剛結束）也可以直接
# 送一個字串要求立即重新檢查一次，不用等下一個週期——雙向、即時，分頁關閉
# （連線自然斷線）就自動停止背景檢查，不會留下孤兒輪詢迴圈。
@app.websocket("/ws/prod-status")
async def ws_prod_status(websocket: WebSocket):
    # 🔴 **WebSocket 不經過 `@app.middleware("http")`** —— 要自己檢查一次。
    # ⚠️ 少了這一行，HTTP 那一面關起來了而這一面還開著，
    # 🔑 而「關起來了」這件事在畫面上完全看不出差別。
    if not _is_local(websocket.client):
        await websocket.close(code=1008)      # 1008 = policy violation
        return
    await websocket.accept()
    try:
        while True:
            with _active_job_lock:
                busy = _active_job_id is not None
            if busy:
                # 2026-09-08（複查後新增）：部署/回滾期間正式機正在重啟服務，
                # 這時候本來就有 apply_update.ps1 自己的健康檢查在對同一個
                # loopback 端點連續打，儀表板這條額外的背景輪詢只是再疊加
                # 一批短命連線，對「正式機剛切換新版還在起服務」這個脆弱
                # 時刻沒有幫助，純粹增加連線churn。job 進行期間暫停實際打
                # 正式機，改回傳一個「部署中」狀態，job 結束後自動恢復。
                status = {"healthy": None, "deployed": {}, "checkedAt": time.strftime("%Y-%m-%d %H:%M:%S"), "paused": True}
            else:
                status = await asyncio.to_thread(_check_prod_status)
            await websocket.send_json(status)
            try:
                # 4 秒週期性推送；期間如果前端主動送任何訊息（例如「剛好有
                # 一個部署 job 結束了，馬上重查一次」），提前中斷等待、立刻
                # 重新檢查一輪，不用乾等到下一個週期。
                await asyncio.wait_for(websocket.receive_text(), timeout=4)
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        # 瀏覽器分頁關閉／重新整理／手動斷線都會走到這裡，迴圈直接結束，
        # 不會有背景工作繼續留著空轉。
        pass


@app.get("/api/packages")
def list_packages():
    packages = []
    if DEPLOY_PACKAGES_DIR.exists():
        for d in sorted(DEPLOY_PACKAGES_DIR.iterdir(), reverse=True):
            manifest_path = d / "deploy_manifest.json"
            if manifest_path.exists():
                try:
                    # build_deploy_package.ps1 用 PowerShell Set-Content -Encoding
                    # UTF8 寫檔，這台機器的 Windows PowerShell 5.1 會加 BOM——
                    # utf-8-sig 才能正確處理（純 utf-8 遇到 BOM 會直接丟例外）。
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
                except Exception:
                    manifest = {}
                # §9e D3：包了哪些模組（9c① 的 modules.lock.json）。讀不到就明說，不當成「全部」
                lock = None
                # 稽核 D-1：打包把 lock 寫在 <包>/backend/（product_select.apply）；位置與檔名跟它共用同一個定義
                lp = d / "backend" / _LOCK_NAME
                if lp.exists():
                    try:
                        lk = json.loads(lp.read_text(encoding="utf-8-sig"))
                        lock = {"product": lk.get("product"), "kind": lk.get("kind"),
                                "modules": {k: (v or {}).get("version") for k, v in (lk.get("modules") or {}).items()}}
                    except Exception:
                        lock = {"error": "modules.lock.json 讀不懂"}
                packages.append({"folder": d.name, "path": str(d), **manifest, "lock": lock})
    return packages


PRODUCTS_DIR = PROJECT_ROOT / "product"
#: 最近一次健康檢查讀到的正式機 Python 版本與套件（gitignored）
PROD_ENV_PATH = TOOLS_DIR / "prod_env.json"


def _products():
    out = []
    for p in sorted(PRODUCTS_DIR.glob("*.json")) if PRODUCTS_DIR.exists() else []:
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
            out.append({"name": p.stem, "description": d.get("description", ""), "modules": d.get("modules", [])})
        except Exception:
            out.append({"name": p.stem, "error": "產品設定檔讀不懂"})
    return out


@app.get("/api/products")
def list_products():
    """§9e D3：可以打包的產品設定檔（product/*.json）。"""
    return _products()


@app.get("/api/history")
def get_history():
    history = _read_history()
    return [] if history is None else history


# ── 背景 job 查詢 ────────────────────────────────────────────────────────

@app.get("/api/jobs/{job_id}")
def job_status(job_id: str, since: int = 0):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return JSONResponse(status_code=404, content={"detail": "找不到這個工作"})
        return {
            "status": job["status"],
            "action": job["action"],
            # 🔑 〈計數器要有落點〉：設了旗標而畫面上沒有它，
            # 它從來不會被看見 —— 而那與「沒有退化」長得一模一樣。
            "legacyProtocol": job.get("legacyProtocol", False),
            # 🔑 〈計數器要有落點〉：算了而畫面拿不到，等於沒算。
            "result": job.get("result"),
            "rolledBackText": job.get("rolledBackText", ""),
            "lines": job["lines"][since:],
            "totalLines": len(job["lines"]),
            "timedOut": bool(job.get("timedOut")),
        }


class ReleaseIn(BaseModel):
    reason: str


@app.post("/api/jobs/{job_id}/release")
def release_timed_out_job(job_id: str, body: ReleaseIn):
    """稽核 A-1：不自動中止的動作逾時後，由人確認正式機已停下來，再解除鎖定（要寫原因、留紀錄）。"""
    global _active_job_id
    reason = (body.reason or "").strip()
    if len(reason) < 6:
        return JSONResponse(status_code=400, content={"detail": "解除鎖定必須寫明原因（例如：已從 log 確認正式機回滾完成）"})
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return JSONResponse(status_code=404, content={"detail": "找不到這個工作"})
        if not job.get("timedOut") or job["status"] != "running":
            return JSONResponse(status_code=409, content={"detail": "只有逾時而且仍在等待中的工作可以解除鎖定"})
        pid = job.get("pid")
        job["lines"].append(f"[解除鎖定] {reason}")
        job["status"] = "timeout"
    if pid:
        _kill_tree(pid)
    _append_history(f"解除鎖定（{job['action']} 逾時）：{reason}", job_id, False)
    with _active_job_lock:
        if _active_job_id == job_id:
            _active_job_id = None
    return {"released": True}


@app.get("/api/pre-deploy-check")
def pre_deploy_check():
    """部署/回滾按鈕跳出二次確認卡片前，前端會先查這支端點：目前有沒有
    別的 deploy/rollback job 正在跑（busy），以及上一筆歷史紀錄是不是
    15 分鐘內的失敗（warning）。"""
    with _active_job_lock:
        busy = _active_job_id is not None
    return {"busy": busy, "warning": _recent_failure_warning()}


# ── 打包 ─────────────────────────────────────────────────────────────────

#: modtest --full 依 commit 分檔寫的全量結果（<完整 SHA>.json）。2026-09-26：原本只讀單一的 .last_full.json，
#: 任何 worktree 跑的全量都會蓋掉它（C 的 ok=False 蓋掉上一輪）⇒ 閘門改讀「這個 commit 的那一份」。
FULL_RESULTS_DIR = PROJECT_ROOT / "tools" / "platform" / "full_results"


def _head_full_sha() -> str:
    try:
        return deploy_insights._git(PROJECT_ROOT, "rev-parse", "HEAD").strip()
    except RuntimeError:
        return ""


@app.get("/api/build-gate")
def build_gate():
    """§9e D6：要打包的 HEAD 有沒有全綠的全量。前端在打包按鈕旁顯示；非 ok 時打包預設擋下。"""
    head = _head_full_sha()
    return {"head": head, **deploy_insights.last_full(deploy_insights.full_result_path(FULL_RESULTS_DIR, head), head)}


@app.get("/api/module-changes")
def module_changes(package: str = "", base: str = "", head: str = ""):
    """§9e D2：這一包會改到哪些模組。
    head：部署包 manifest 的 commit（或直接指定）；base：預設取正式機已部署的 commit（或直接指定）。
    任一端拿不到 ⇒ 400 並說明，不猜。"""
    if package:
        if not _is_safe_name(package):
            return JSONResponse(status_code=400, content={"detail": "無效的部署包名稱"})
        mp = DEPLOY_PACKAGES_DIR / package / "deploy_manifest.json"
        try:
            head = json.loads(mp.read_text(encoding="utf-8-sig")).get("commit", "") or head
        except Exception:
            return JSONResponse(status_code=400, content={"detail": f"讀不到部署包的 manifest：{mp}"})
    if not base:
        base = (_check_prod_status().get("deployed") or {}).get("commit", "")
    if not base or not head:
        return JSONResponse(status_code=400, content={
            "detail": "缺少比較基準：" + ("正式機已部署版本查不到（連不上或從未套用過部署包）" if not base else "沒有指定部署包或 commit")})
    for c in (base, head):
        if not re.fullmatch(r"[0-9a-fA-F]{7,40}", c):
            return JSONResponse(status_code=400, content={"detail": f"不是 commit：{c}"})
    try:
        return deploy_insights.module_changes(PROJECT_ROOT, base, head)
    except RuntimeError as e:
        return JSONResponse(status_code=400, content={"detail": f"這個 repo 不認得該 commit：{e}"})


class BuildIn(BaseModel):
    #: 全量沒有全綠仍要打包時必須明確勾選（例如緊急修補）；會記進歷史紀錄
    overrideTestGate: bool = False
    overrideReason: str = ""
    #: §9e D3：產品設定檔名稱（product/<name>.json）；預設 full，與 build_deploy_package.ps1 相同
    product: str = "full"


@app.post("/api/build")
def start_build(body: BuildIn = None):
    body = body or BuildIn()
    valid = {p["name"] for p in _products() if "error" not in p}
    if not _is_safe_name(body.product) or body.product not in valid:
        return JSONResponse(status_code=400, content={
            "detail": f"沒有這個產品設定檔：{body.product}（可選：{'、'.join(sorted(valid)) or '無'}）"})
    gate = build_gate()
    if gate["state"] != "ok" and not body.overrideTestGate:
        return JSONResponse(status_code=409, content={
            "detail": f"測試閘門未通過：{gate['detail']}。先跑全量（modtest --full），或勾選「略過測試閘門」並寫明原因。",
            "gate": gate})
    job_id = uuid.uuid4().hex
    if gate["state"] != "ok":
        # 略過閘門一定要有理由、一定留痕跡：沒寫理由的略過 = 沒有人做過決定
        reason = (body.overrideReason or "").strip()
        if len(reason) < 6:
            return JSONResponse(status_code=400, content={"detail": "略過測試閘門必須寫明原因（至少 6 個字）"})
        _append_history(f"打包略過測試閘門：{reason}（閘門狀態：{gate['detail']}）", job_id, False)
    cmd = _ps_cmd(TOOLS_DIR / "build_deploy_package.ps1", {"Product": body.product})
    threading.Thread(target=_run_job, args=(job_id, "build", cmd), daemon=True).start()
    return {"jobId": job_id}


# ── 部署 ─────────────────────────────────────────────────────────────────

class DeployIn(BaseModel):
    package: str  # deploy_packages/ 底下的資料夾名稱
    username: str
    password: str
    confirm: bool = False
    # 2026-09-08 新增：健康檢查機制這一晚已證實會用好幾種不同方式誤判，
    # 導致明明程式碼跟 pytest 都沒問題卻連續被自動回滾。這個選項讓套用後
    # 健康檢查失敗時不自動回滾，改成需要人工確認——db/程式碼快照仍然照常
    # 建立，只是「自動判定→自動回滾」這段換成人工決定。預設關閉，不是
    # 日常部署的預設行為，只在已經反覆確認健康檢查本身不可靠時才勾選。
    skipAutoRollback: bool = False
    #: §9e D1：10 分鐘內沒有通過的健康檢查時，必須明確勾選「我已確認正式機狀態」
    healthAck: bool = False


@app.post("/api/deploy")
def start_deploy(body: DeployIn):
    if not body.confirm:
        return JSONResponse(status_code=400, content={"detail": "需要先在網頁上完成二次確認（confirm 必須為 true）"})
    if not _health_gate_ok() and not body.healthAck:
        return JSONResponse(status_code=409, content={
            "detail": "部署前健康檢查：10 分鐘內沒有通過的紀錄。請先按「部署前健康檢查」；若確認問題與這次部署無關，勾選「我已確認正式機狀態」後再部署。"})
    if not _is_safe_name(body.package):
        return JSONResponse(status_code=400, content={"detail": "無效的部署包名稱"})
    package_path = DEPLOY_PACKAGES_DIR / body.package
    if not package_path.exists():
        return JSONResponse(status_code=400, content={"detail": f"找不到部署包：{package_path}"})

    job_id = uuid.uuid4().hex
    if not _try_acquire_job_lock(job_id):
        return JSONResponse(status_code=409, content={"detail": "已經有一個部署/回滾工作正在執行，請等它結束再試"})
    if not _health_gate_ok():
        _append_history(f"部署未通過健康檢查但已人工確認（{body.package}）", job_id, False)
    named_args = {"Action": "deploy", "Username": body.username, "PackagePath": str(package_path)}
    if body.skipAutoRollback:
        named_args["SkipAutoRollback"] = "true"
    cmd = _ps_cmd(TOOLS_DIR / "_dashboard_remote.ps1", named_args)
    threading.Thread(
        target=_run_job, args=(job_id, "deploy", cmd, body.password + "\n"), daemon=True
    ).start()
    return {"jobId": job_id}


# ── 回滾 ─────────────────────────────────────────────────────────────────

class RollbackIn(BaseModel):
    snapshotTimestamp: str
    username: str
    password: str
    confirm: bool = False


@app.post("/api/rollback")
def start_rollback(body: RollbackIn):
    if not body.confirm:
        return JSONResponse(status_code=400, content={"detail": "需要先在網頁上完成二次確認（confirm 必須為 true）"})
    if not _is_safe_name(body.snapshotTimestamp):
        return JSONResponse(status_code=400, content={"detail": "無效的快照時間戳"})

    job_id = uuid.uuid4().hex
    if not _try_acquire_job_lock(job_id):
        return JSONResponse(status_code=409, content={"detail": "已經有一個部署/回滾工作正在執行，請等它結束再試"})
    cmd = _ps_cmd(
        TOOLS_DIR / "_dashboard_remote.ps1",
        {"Action": "rollback", "Username": body.username, "SnapshotTimestamp": body.snapshotTimestamp},
    )
    threading.Thread(
        target=_run_job, args=(job_id, "rollback", cmd, body.password + "\n"), daemon=True
    ).start()
    return {"jobId": job_id}


class SnapshotsIn(BaseModel):
    username: str
    password: str


@app.post("/api/snapshots")
def list_snapshots(body: SnapshotsIn):
    """跟 deploy/rollback 不同，這個是同步呼叫（不用背景 job）——單純列一份
    清單，通常幾秒內就回來，不需要即時串流進度。"""
    cmd = _ps_cmd(TOOLS_DIR / "_dashboard_remote.ps1", {"Action": "list-snapshots", "Username": body.username})
    try:
        proc = subprocess.run(
            cmd, input=body.password + "\n", capture_output=True, text=True,
            encoding="utf-8", errors="replace", cwd=str(PROJECT_ROOT), timeout=60,
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return JSONResponse(status_code=504, content={"detail": "連線正式機逾時"})

    if proc.returncode != 0:
        return JSONResponse(status_code=502, content={"detail": _remote_error(proc)})

    # 輸出裡混著「連線正式機...」這類 Write-Host 進度行，且 ConvertTo-Json
    # 預設會跨多行印出——_dashboard_remote.ps1 在 JSON 前印了固定的
    # "===JSON===" 分隔標記，直接切出標記之後的區塊就是完整 JSON。
    marker = "===JSON==="
    if marker in proc.stdout:
        json_text = proc.stdout.split(marker, 1)[1].strip()
        try:
            data = json.loads(json_text)
            return data if isinstance(data, list) else [data]
        except Exception:
            pass
    return JSONResponse(status_code=502, content={"detail": "無法解析正式機回傳的快照清單", "raw": proc.stdout})


#: 最近一次健康檢查結果（記憶體內）：部署前必須有「10 分鐘內、通過」的一筆，否則要明確確認
_last_health = {"at": 0.0, "ok": False}
HEALTH_VALID_SECONDS = 600


class HealthIn(BaseModel):
    username: str
    password: str


def _run_remote_json(action: str, username: str, password: str, timeout=90):
    cmd = _ps_cmd(TOOLS_DIR / "_dashboard_remote.ps1", {"Action": action, "Username": username})
    try:
        proc = subprocess.run(cmd, input=password + "\n", capture_output=True, text=True,
                              encoding="utf-8", errors="replace", cwd=str(PROJECT_ROOT), timeout=timeout,
                              creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return None, "連線正式機逾時"
    if proc.returncode != 0:
        _log_remote_failure(action, _remote_error(proc))
        return None, _remote_error(proc)
    marker = "===JSON==="
    if marker not in proc.stdout:
        _log_remote_failure(action, _remote_error(proc))
        return None, "正式機回傳內容沒有 JSON 區塊"
    try:
        return json.loads(proc.stdout.split(marker, 1)[1].strip()), None
    except Exception:
        return None, "無法解析正式機回傳的 JSON"


@app.post("/api/prod-health")
def prod_health(body: HealthIn):
    """§9e D1：部署前健康檢查（唯讀）。結果記在記憶體，部署時檢查是否 10 分鐘內通過。"""
    facts, err = _run_remote_json("health", body.username, body.password)
    if err:
        _last_health.update(at=time.time(), ok=False)
        return JSONResponse(status_code=502, content={"detail": err})
    verdict = deploy_insights.evaluate_health(facts)
    # 正式機的 Python 環境落地成檔：開發機的專案 venv 要對齊它（B 的 .venv 題依此重建）
    # 寫不出來要明說：2026-09-25 第一次實跑版本沒拿到、檔沒寫出，而畫面一個字都沒提
    if facts.get("pythonVersion"):
        try:
            PROD_ENV_PATH.write_text(json.dumps({
                "capturedAt": facts.get("checkedAt"), "pythonVersion": facts.get("pythonVersion"),
                "pythonPath": facts.get("pythonPath"), "pythonSource": facts.get("pythonSource"),
                "pipFreeze": facts.get("pipFreeze") or []}, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as e:
            verdict["warnings"].append(f"正式機 Python 環境寫不進 {PROD_ENV_PATH.name}：{e}")
    _last_health.update(at=time.time(), ok=verdict["ok"])
    return {**verdict, "facts": facts}


def _health_gate_ok() -> bool:
    return _last_health["ok"] and (time.time() - _last_health["at"]) <= HEALTH_VALID_SECONDS


# ── V9 → 新版升級精靈（CORE-SPEC §9e D4）─────────────────────────────────
#
# 每一步是固定名稱（_dashboard_remote.ps1 -Action upgrade -Step <名稱>），由人逐步按、逐步確認。
# ⚠️ 不走 `_run_job`：那支的判定屬於 deploy/rollback 的 v2 協定，而 `_PROTOCOL_EXEMPT` 被釘成只有 build
#    （豁免是便宜的變綠路徑）。升級步驟另走這支，判定更嚴格：只認遠端腳本的結束碼，
#    而遠端腳本拿不到 upgrade.py 的結束碼標記時自己就 exit 1（fail closed）。

UPGRADE_STEPS = ("push", "stop-services", "preflight", "backup", "convert", "verify",
                 "start-services", "rollback-code", "rollback-full-preview", "rollback-full")
#: 會讓正式機停止服務或改動程式／資料的步驟：需要健康檢查通過或人工確認（同部署）
_UPGRADE_GUARDED = {"stop-services"}


class UpgradeStepIn(BaseModel):
    step: str
    package: str
    backupStamp: str
    username: str
    password: str
    confirm: bool = False
    #: rollback-full 會丟掉轉換後寫入的資料 ⇒ 必須另外輸入 FULL
    confirmText: str = ""
    healthAck: bool = False


def _run_upgrade_job(job_id: str, action: str, cmd: list, input_text: str, stamp: str = ""):
    global _active_job_id
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "lines": [], "action": action}
    DEPLOY_LOGS_DIR.mkdir(exist_ok=True)
    log_path = DEPLOY_LOGS_DIR / f"{time.strftime('%Y%m%d_%H%M%S')}_{action}_{job_id[:8]}.log"
    success = False
    try:
        with log_path.open("a", encoding="utf-8") as log_file:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace", cwd=str(PROJECT_ROOT),
                                    creationflags=CREATE_NO_WINDOW)
            proc.stdin.write(input_text)
            proc.stdin.close()
            _start_watchdog(proc, job_id, action)
            for line in proc.stdout:
                s = line.rstrip("\n")
                with _jobs_lock:
                    _jobs[job_id]["lines"].append(s)
                log_file.write(s + "\n")
                log_file.flush()
            proc.wait()
        success = proc.returncode == 0
    finally:
        with _jobs_lock:
            _jobs[job_id]["status"] = _final_status(job_id, success)
        _append_history(action, job_id, success, str(log_path))
        if stamp and action.startswith("upgrade-"):
            _record_step(stamp, action[len("upgrade-"):], success)
        with _active_job_lock:
            if _active_job_id == job_id:
                _active_job_id = None


# S-U06（2026-09-25 C 稽核）：備份時間戳原本在前端產生 ⇒ 頁面重整後 UI 再也指不到原本的備份。
# 改成伺服器端的「這一輪升級」紀錄：時間戳由伺服器產生並落地，重整或重啟儀表板都還在；
# 同一時間只能有一輪；要開新的一輪，必須先寫明原因結束舊的。
UPGRADE_SESSION_PATH = TOOLS_DIR / "upgrade_session.json"
_upgrade_session_lock = threading.Lock()


def _load_session():
    try:
        return json.loads(UPGRADE_SESSION_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        # 讀不懂 ≠ 沒有：不可以當成沒有而讓人開新的一輪（那會失去舊備份的指向）
        return {"corrupt": True}


def _save_session(s):
    tmp = UPGRADE_SESSION_PATH.with_name(UPGRADE_SESSION_PATH.name + ".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, UPGRADE_SESSION_PATH)


class ResetCorruptIn(BaseModel):
    reason: str


@app.post("/api/upgrade/session/reset-corrupt")
def reset_corrupt_session(body: ResetCorruptIn):
    """稽核 B-2：紀錄檔讀不懂時原本永遠卡住。封存原檔（不刪，留給人工查看它原本指到哪一份備份），
    要寫原因並記歷史，之後才能開新的一輪。"""
    reason = (body.reason or "").strip()
    if len(reason) < 6:
        return JSONResponse(status_code=400, content={"detail": "封存讀不懂的升級紀錄必須寫明原因"})
    with _upgrade_session_lock:
        cur = _load_session()
        if not cur or not cur.get("corrupt"):
            return JSONResponse(status_code=409, content={"detail": "升級紀錄可以正常讀取，不需要封存"})
        dest = UPGRADE_SESSION_PATH.with_name(f"upgrade_session.corrupt-{time.strftime('%Y%m%d_%H%M%S')}.json")
        os.replace(UPGRADE_SESSION_PATH, dest)
    _append_history(f"封存讀不懂的升級紀錄 → {dest.name}：{reason}", "session", False)
    return {"archivedAs": dest.name}


def _record_step(stamp: str, step: str, ok: bool):
    with _upgrade_session_lock:
        cur = _load_session()
        if cur and cur.get("stamp") == stamp:
            cur.setdefault("steps", {})[step] = {"ok": ok, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
            _save_session(cur)


class SessionNewIn(BaseModel):
    package: str


class SessionCloseIn(BaseModel):
    reason: str


@app.get("/api/upgrade/session")
def get_upgrade_session():
    return _load_session() or {}


@app.post("/api/upgrade/session")
def new_upgrade_session(body: SessionNewIn):
    if not _is_safe_name(body.package) or not (DEPLOY_PACKAGES_DIR / body.package).exists():
        return JSONResponse(status_code=400, content={"detail": "找不到這個部署包"})
    with _upgrade_session_lock:
        cur = _load_session()
        if cur and (cur.get("corrupt") or not cur.get("closedAt")):
            return JSONResponse(status_code=409, content={
                "detail": ("升級紀錄檔讀不出來，請先人工確認 upgrade_session.json" if cur.get("corrupt") else
                           "已經有一輪升級還沒結束（備份時間戳 %s）。要開新的一輪，先寫明原因結束它。" % cur.get("stamp", "?")),
                "session": cur})
        s = {"stamp": time.strftime("%Y%m%d_%H%M%S"), "package": body.package,
             "createdAt": time.strftime("%Y-%m-%d %H:%M:%S"), "steps": {}, "closedAt": None}
        _save_session(s)
    _append_history(f"開始一輪升級（{body.package}，備份時間戳 {s['stamp']}）", "session", True)
    return s


@app.post("/api/upgrade/session/close")
def close_upgrade_session(body: SessionCloseIn):
    reason = (body.reason or "").strip()
    if len(reason) < 4:
        return JSONResponse(status_code=400, content={"detail": "結束這一輪升級必須寫明原因"})
    with _upgrade_session_lock:
        cur = _load_session()
        if not cur or cur.get("corrupt") or cur.get("closedAt"):
            return JSONResponse(status_code=400, content={"detail": "目前沒有進行中的升級"})
        with _active_job_lock:
            busy = _active_job_id is not None
        if busy:
            return JSONResponse(status_code=409, content={"detail": "有工作正在執行，等它結束再關"})
        cur["closedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        cur["closeReason"] = reason
        _save_session(cur)
    _append_history(f"結束一輪升級（備份時間戳 {cur.get('stamp')}）：{reason}", "session", True)
    return cur


@app.post("/api/upgrade/step")
def upgrade_step(body: UpgradeStepIn):
    if body.step not in UPGRADE_STEPS:
        return JSONResponse(status_code=400, content={"detail": f"未知的升級步驟：{body.step}"})
    if not body.confirm:
        return JSONResponse(status_code=400, content={"detail": "需要先在網頁上確認這一步"})
    if not _is_safe_name(body.package) or not _is_safe_name(body.backupStamp):
        return JSONResponse(status_code=400, content={"detail": "部署包名稱或備份時間戳不合法"})
    cur = _load_session()
    if (not cur or cur.get("corrupt") or cur.get("closedAt")
            or cur.get("stamp") != body.backupStamp or cur.get("package") != body.package):
        return JSONResponse(status_code=409, content={
            "detail": "這一步不屬於目前進行中的那一輪升級（或升級紀錄讀不出來）。請重新整理頁面，以伺服器上的紀錄為準。"})
    package_path = DEPLOY_PACKAGES_DIR / body.package
    if not package_path.exists():
        return JSONResponse(status_code=400, content={"detail": f"找不到部署包：{package_path}"})
    # 9b 稽核順帶發現（2026-09-25）：完整回滾一律帶 --yes ⇒「會失去哪些資料」只出現在 log，人在確認前看不到。
    # 改成：這一輪必須先跑過「預覽」（唯讀，列出清單），而且預覽要在最近一次轉換之後，才准完整回滾。
    if body.step == "rollback-full":
        steps = cur.get("steps") or {}
        pv, cv = steps.get("rollback-full-preview") or {}, steps.get("convert") or {}
        if not pv.get("ok") or (cv.get("at") and (pv.get("at") or "") < cv["at"]):
            return JSONResponse(status_code=409, content={
                "detail": "完整回滾前，必須先按「預覽完整回滾」看過會失去的資料清單（而且要在最近一次轉換之後）。"})
    if body.step == "rollback-full" and body.confirmText != "FULL":
        return JSONResponse(status_code=400, content={
            "detail": "完整回滾會丟掉轉換後寫入的所有資料，必須在確認欄輸入 FULL。多數情況請先用「只回程式」。"})
    if body.step in _UPGRADE_GUARDED and not _health_gate_ok() and not body.healthAck:
        return JSONResponse(status_code=409, content={
            "detail": "停服務之前需要 10 分鐘內通過的部署前健康檢查，或勾選「我已確認正式機狀態」。"})
    job_id = uuid.uuid4().hex
    if not _try_acquire_job_lock(job_id):
        return JSONResponse(status_code=409, content={"detail": "已經有一個部署／回滾／升級工作正在執行，請等它結束"})
    if body.step in _UPGRADE_GUARDED and not _health_gate_ok():
        _append_history(f"升級停服務：未通過健康檢查但已人工確認（{body.package}）", job_id, False)
    cmd = _ps_cmd(TOOLS_DIR / "_dashboard_remote.ps1", {
        "Action": "upgrade", "Step": body.step, "Username": body.username,
        "PackagePath": str(package_path), "BackupStamp": body.backupStamp})
    threading.Thread(target=_run_upgrade_job,
                     args=(job_id, f"upgrade-{body.step}", cmd, body.password + "\n", body.backupStamp), daemon=True).start()
    return {"jobId": job_id}


class LogTailIn(BaseModel):
    username: str
    password: str
    lines: int = 300


@app.post("/api/log-tail")
def log_tail(body: LogTailIn):
    """純讀取正式機 server.log 最後 N 行，供 apply_update.ps1 健康檢查失敗
    （healthy=False, log 錯誤筆數=N）時人工診斷用——不動任何東西，跟
    list_snapshots 是同一種同步呼叫模式。"""
    cmd = _ps_cmd(
        TOOLS_DIR / "_dashboard_remote.ps1",
        {"Action": "tail-log", "Username": body.username, "Lines": str(body.lines)},
    )
    try:
        proc = subprocess.run(
            cmd, input=body.password + "\n", capture_output=True, text=True,
            encoding="utf-8", errors="replace", cwd=str(PROJECT_ROOT), timeout=60,
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return JSONResponse(status_code=504, content={"detail": "連線正式機逾時"})

    if proc.returncode != 0:
        return JSONResponse(status_code=502, content={"detail": _remote_error(proc)})

    marker = "===JSON==="
    if marker in proc.stdout:
        json_text = proc.stdout.split(marker, 1)[1].strip()
        try:
            data = json.loads(json_text)
            # _dashboard_remote.ps1 現在回傳單一字串（join 過的整段 log），
            # 不是陣列——這裡切回逐行陣列，前端 join('\n') 顯示邏輯不用改。
            if isinstance(data, str):
                return data.split("\n") if data else []
            return data if isinstance(data, list) else [data]
        except Exception:
            pass
    return JSONResponse(status_code=502, content={"detail": "無法解析正式機回傳的 log", "raw": proc.stdout})


class CheckOnlyIn(BaseModel):
    username: str
    password: str


@app.post("/api/check-only")
def check_only(body: CheckOnlyIn):
    """遠端跑 apply_update.ps1 -CheckOnly——純測健康檢查機制本身（一次
    curl.exe 對正式機 127.0.0.1:666 的呼叫），不動備份/停服/部署/回滾。"""
    cmd = _ps_cmd(TOOLS_DIR / "_dashboard_remote.ps1", {"Action": "check-only", "Username": body.username})
    try:
        proc = subprocess.run(
            cmd, input=body.password + "\n", capture_output=True, text=True,
            encoding="utf-8", errors="replace", cwd=str(PROJECT_ROOT), timeout=60,
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return JSONResponse(status_code=504, content={"detail": "連線正式機逾時"})

    if proc.returncode != 0:
        return JSONResponse(status_code=502, content={"detail": _remote_error(proc)})

    marker = "===JSON==="
    if marker in proc.stdout:
        json_text = proc.stdout.split(marker, 1)[1].strip()
        try:
            data = json.loads(json_text)
            if isinstance(data, str):
                return data.split("\n") if data else []
            return data if isinstance(data, list) else [data]
        except Exception:
            pass
    return JSONResponse(status_code=502, content={"detail": "無法解析正式機回傳的結果", "raw": proc.stdout})


if __name__ == "__main__":
    # 📌 綁 127.0.0.1 **留著**，而它不再是唯一的防線 ——
    # 現在就算有人用 `--host 0.0.0.0` 起它，請求層那道也會擋下來。
    # 🔑 兩層都要有：這一層擋「監聽在哪」，那一層擋「誰打得到」。
    if sys.stdout is not None:     # pythonw 沒有 stdout：print 會丟例外，伺服器起不來（2026-09-25 實測）
        print("MOTRIX 部署儀表板：http://127.0.0.1:8765")
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
