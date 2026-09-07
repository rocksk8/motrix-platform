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
from fastapi import FastAPI
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

PROD_HOST = "172.16.10.177"
PROD_BASE_URL = f"https://{PROD_HOST}:666"

app = FastAPI(title="MOTRIX 部署儀表板")

# ── 背景 job 追蹤（記憶體內，重啟這個小工具就重置，不需要持久化）──────────
_jobs_lock = threading.Lock()
_jobs: dict = {}  # job_id -> {"status": "running"|"succeeded"|"failed", "lines": [...], "action": str}


def _run_job(job_id: str, action: str, cmd: list, input_text: str = None):
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "lines": [], "action": action}

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
        with _jobs_lock:
            _jobs[job_id]["lines"].append(line.rstrip("\n"))
    proc.wait()

    success = proc.returncode == 0
    with _jobs_lock:
        _jobs[job_id]["status"] = "succeeded" if success else "failed"

    if action in ("deploy", "rollback"):
        _append_history(action, job_id, success)


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


def _append_history(action: str, job_id: str, success: bool):
    entry = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "success": success,
    }
    history = []
    if HISTORY_PATH.exists():
        try:
            history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            history = []
    history.insert(0, entry)
    HISTORY_PATH.write_text(json.dumps(history[:200], ensure_ascii=False, indent=2), encoding="utf-8")


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


@app.get("/api/prod-status")
def prod_status():
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

    return {"healthy": healthy, "deployed": deployed}


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
    cmd = _ps_cmd(
        TOOLS_DIR / "_dashboard_remote.ps1",
        {"Action": "deploy", "Username": body.username, "PackagePath": str(package_path)},
    )
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


if __name__ == "__main__":
    print("MOTRIX 部署儀表板：http://127.0.0.1:8765")
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
