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

# 正式機是自簽憑證（見 https_setup.ps1），這裡查狀態用的 verify=False 本來
# 就是刻意跳過驗證（跟 apply_update.ps1 的 curl.exe -k 是同一件事），關掉
# urllib3 每次都印的 InsecureRequestWarning，避免洗版這個小工具自己的輸出。
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TOOLS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TOOLS_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent
DEPLOY_PACKAGES_DIR = PROJECT_ROOT / "deploy_packages"
HISTORY_PATH = TOOLS_DIR / "deploy_dashboard_history.json"
# 2026-09-08（複查後新增）：job 輸出原本只存記憶體，這個小工具本身重啟
# （例如改完程式碼要重載）就整個消失——當晚實際發生過好幾次，每次重啟
# 儀表板都得請使用者重新複製貼上先前的畫面內容才留得住紀錄。改成每個
# deploy/rollback job 同時逐行寫進磁碟，重啟儀表板／事後複查都還找得到。
DEPLOY_LOGS_DIR = TOOLS_DIR / "deploy_logs"

PROD_HOST = "172.16.10.177"
PROD_BASE_URL = f"https://{PROD_HOST}:666"

app = FastAPI(title="MOTRIX 部署儀表板")

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
            )
            if input_text is not None:
                proc.stdin.write(input_text)
                proc.stdin.close()

            for line in proc.stdout:
                stripped = line.rstrip("\n")
                with _jobs_lock:
                    _jobs[job_id]["lines"].append(stripped)
                log_file.write(stripped + "\n")
                log_file.flush()
            proc.wait()

        success = proc.returncode == 0
        if success:
            # 2026-09-08（保險）：即使 _dashboard_remote.ps1 已修好結束碼傳遞，
            # 這裡再加一道獨立防線——掃輸出文字本身有沒有出現「明明失敗」的
            # 字樣，兩者矛盾時一律當失敗處理。不是為了取代結束碼判定，是避免
            # 同一類「exit code 沒接住真實結果」的漏洞以後又用不同方式重演。
            joined = "\n".join(_jobs[job_id]["lines"])
            if re.search(r"更新失敗|已自動回滾|\[FAIL\]", joined):
                success = False
        with _jobs_lock:
            _jobs[job_id]["status"] = "succeeded" if success else "failed"

        if action in ("deploy", "rollback"):
            _append_history(action, job_id, success, str(log_path))
    finally:
        # 不管上面成功、失敗、還是中途拋例外，只要是這個 job 占著鎖，
        # 一定要釋放——否則儀表板重啟前這把鎖會卡死，之後所有部署/回滾
        # 請求永遠拿到「已經有工作在跑」的 409。
        if action in ("deploy", "rollback"):
            with _active_job_lock:
                if _active_job_id == job_id:
                    _active_job_id = None


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


def _append_history(action: str, job_id: str, success: bool, log_path: str = ""):
    entry = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "success": success,
        "logPath": log_path,
    }
    history = []
    if HISTORY_PATH.exists():
        try:
            history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            history = []
    history.insert(0, entry)
    HISTORY_PATH.write_text(json.dumps(history[:200], ensure_ascii=False, indent=2), encoding="utf-8")


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
    if not HISTORY_PATH.exists():
        return ""
    try:
        history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return ""
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
            ).stdout.strip()
        except Exception:
            return ""

    branch = _git("branch", "--show-current")
    commit = _git("log", "-1", "--format=%h %s")
    dirty = bool(_git("status", "--porcelain", "--", "backend", "frontend"))
    ahead_raw = _git("rev-list", "--count", "origin/master..HEAD")
    try:
        ahead = int(ahead_raw)
    except ValueError:
        ahead = None
    return {"branch": branch, "commit": commit, "dirty": dirty, "aheadOfOrigin": ahead}


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
                packages.append({"folder": d.name, "path": str(d), **manifest})
    return packages


@app.get("/api/history")
def get_history():
    if not HISTORY_PATH.exists():
        return []
    try:
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


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
            "lines": job["lines"][since:],
            "totalLines": len(job["lines"]),
        }


@app.get("/api/pre-deploy-check")
def pre_deploy_check():
    """部署/回滾按鈕跳出二次確認卡片前，前端會先查這支端點：目前有沒有
    別的 deploy/rollback job 正在跑（busy），以及上一筆歷史紀錄是不是
    15 分鐘內的失敗（warning）。"""
    with _active_job_lock:
        busy = _active_job_id is not None
    return {"busy": busy, "warning": _recent_failure_warning()}


# ── 打包 ─────────────────────────────────────────────────────────────────

@app.post("/api/build")
def start_build():
    job_id = uuid.uuid4().hex
    cmd = _ps_cmd(TOOLS_DIR / "build_deploy_package.ps1")
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


@app.post("/api/deploy")
def start_deploy(body: DeployIn):
    if not body.confirm:
        return JSONResponse(status_code=400, content={"detail": "需要先在網頁上完成二次確認（confirm 必須為 true）"})
    if not _is_safe_name(body.package):
        return JSONResponse(status_code=400, content={"detail": "無效的部署包名稱"})
    package_path = DEPLOY_PACKAGES_DIR / body.package
    if not package_path.exists():
        return JSONResponse(status_code=400, content={"detail": f"找不到部署包：{package_path}"})

    job_id = uuid.uuid4().hex
    if not _try_acquire_job_lock(job_id):
        return JSONResponse(status_code=409, content={"detail": "已經有一個部署/回滾工作正在執行，請等它結束再試"})
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
        )
    except subprocess.TimeoutExpired:
        return JSONResponse(status_code=504, content={"detail": "連線正式機逾時"})

    if proc.returncode != 0:
        return JSONResponse(status_code=502, content={"detail": proc.stdout.strip() or "連線失敗"})

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
        )
    except subprocess.TimeoutExpired:
        return JSONResponse(status_code=504, content={"detail": "連線正式機逾時"})

    if proc.returncode != 0:
        return JSONResponse(status_code=502, content={"detail": proc.stdout.strip() or "連線失敗"})

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
        )
    except subprocess.TimeoutExpired:
        return JSONResponse(status_code=504, content={"detail": "連線正式機逾時"})

    if proc.returncode != 0:
        return JSONResponse(status_code=502, content={"detail": proc.stdout.strip() or "連線失敗"})

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
    print("MOTRIX 部署儀表板：http://127.0.0.1:8765")
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
