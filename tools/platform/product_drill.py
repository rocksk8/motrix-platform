"""9c① 演練：把一個部署包複製到暫存位置、啟動、確認回應，並檢查 M11（任一 L2 模組）端點在或不在。

用法：
  python tools/platform/product_drill.py --pkg <部署包目錄> --port 6701 [--keep]
輸出一份 JSON（stdout 最後一行），並以 exit code 表示成敗。
判定：
  - /api/ping 在時限內回 200
  - 讀包內 backend/modules.lock.json：列了的模組 ⇒ 它 module.json `provides.probes` 列的 GET 端點回 200；
    沒列（被排除）的模組 ⇒ 那些端點回 404，頁面（removed_pages）回 404
  - `provides.probes` 是模組**自己宣告**的演練端點（真的 GET 路由，模組在時回 200）。不用 api_prefixes 的前綴本身：
    前綴常常不是端點（`/api/dashboard`、`/api/reports` 在模組在時也 404）⇒ 完整產品假紅、排除時假綠（稽核 ⑰ M-3）
  - 沒宣告 probes 的模組：不打端點、不判紅，但列在輸出 `undeclared_probes`（缺口要看得到；主持 2026-09-26 過渡裁示）
  - 登入用新庫自動建立的 superadmin 臨時密碼（backend/.initial_admin_credentials.txt）
隔離：複製到暫存位置後才啟動；根目錄放 .no_email_send、.no_cloud_archive；MOTRIX_DISABLE_SCHEDULERS=1；
      MOTRIX_CREATE_NEW_DB=1（全新空庫）；只綁 127.0.0.1。結束一律關閉服務、刪暫存（--keep 保留）。
"""
import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def _req(url, data=None, token=None, timeout=10, method=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method or ("POST" if body else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except OSError as e:
        return None, str(e)


def _rmtree(p):
    def _clear(func, path, _exc):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    shutil.rmtree(str(p), onerror=_clear)


def _kill_tree(proc):
    if proc.poll() is None:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            pass


def probe_plan(mods_src, lock):
    """⇒ ([(模組, 在不在包內, "GET"／"page", 路徑)], [沒宣告 provides.probes 的模組])。純函式（不連線）。"""
    plan, undeclared = [], []
    installed = lock.get("modules") or {}
    for d in sorted(p for p in Path(mods_src).iterdir() if (p / "module.json").is_file()):
        m = json.loads((d / "module.json").read_text(encoding="utf-8"))
        present = d.name in installed
        probes = (m.get("provides") or {}).get("probes")
        if not probes:
            undeclared.append(d.name)
        for path in probes or []:
            plan.append((d.name, present, "GET", path))
        for page in m.get("pages", []):
            plan.append((d.name, present, "page", page["path"]))
    return plan, undeclared


def drill(pkg, port, keep=False):
    pkg = Path(pkg)
    lock = json.loads((pkg / "backend" / "modules.lock.json").read_text(encoding="utf-8"))
    run = Path(tempfile.gettempdir()) / ("motrix-drill-%s-%d" % (lock.get("product"), port))
    if run.exists():
        _rmtree(run)
    shutil.copytree(pkg, run)
    (run / ".no_email_send").write_text("drill\n", encoding="utf-8")
    (run / ".no_cloud_archive").write_text("", encoding="utf-8")
    env = dict(os.environ, MOTRIX_CREATE_NEW_DB="1", MOTRIX_DISABLE_SCHEDULERS="1", PYTHONIOENCODING="utf-8")
    log = open(run / "drill_server.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
                            cwd=str(run / "backend"), env=env, stdout=log, stderr=subprocess.STDOUT)
    base = "http://127.0.0.1:%d" % port
    result = {"product": lock.get("product"), "lock_modules": sorted(lock.get("modules") or {}),
              "excluded": lock.get("excluded"), "checks": [], "ok": False}
    try:
        t0 = time.time()
        status = None
        while time.time() - t0 < 120:
            status, _ = _req(base + "/api/ping", timeout=3)
            if status == 200 or proc.poll() is not None:
                break
            time.sleep(1)
        result["ping"] = status
        result["startup_seconds"] = round(time.time() - t0, 1)
        if status != 200:
            result["error"] = "ping 沒有回 200（%s）；server exit=%s" % (status, proc.poll())
            return result
        cred = (run / "backend" / ".initial_admin_credentials.txt").read_text(encoding="utf-8")
        user = re.search(r"帳號:\s*(\S+)", cred).group(1)
        pw = re.search(r"臨時密碼:\s*(\S+)", cred).group(1)
        s, body = _req(base + "/api/auth/login", {"username": user, "password": pw})
        token = json.loads(body).get("token") if s == 200 else None
        result["login"] = s
        if not token:
            result["error"] = "登入失敗：%s %s" % (s, body[:200])
            return result
        # 新庫的管理員是臨時密碼（must_change_password=1）⇒ 中介層對其他端點一律 403，
        # 分不出「路由沒掛」與「還沒改密碼」⇒ 先改密碼、重新登入，再打模組端點。
        new_pw = "Drill-%d-Pass!9" % port
        s2, b2 = _req(base + "/api/auth/change-password", {"current_password": pw, "new_password": new_pw},
                      token=token, method="PATCH")
        result["change_password"] = s2
        s3, b3 = _req(base + "/api/auth/login", {"username": user, "password": new_pw})
        token = json.loads(b3).get("token") if s3 == 200 else None
        if s2 != 200 or not token:
            result["error"] = "改密碼或重新登入失敗：%s %s／%s %s" % (s2, b2[:150], s3, b3[:150])
            return result
        # 正對照：一支確定存在的 L1 端點要回 200，證明 token 真的能用（否則 404／403 都不能解讀）
        s4, _ = _req(base + "/api/auth/me", token=token)
        result["control_me"] = s4
        if s4 != 200:
            result["error"] = "正對照 /api/auth/me 回 %s" % s4
            return result
        all_ok = True
        mods_src = Path(__file__).resolve().parents[2] / "backend" / "modules"
        plan, undeclared = probe_plan(mods_src, lock)
        result["undeclared_probes"] = undeclared
        for mod, present, kind, path in plan:
            if kind == "GET":
                st, _ = _req(base + path, token=token)
            else:
                st, _ = _req(base + "/pages/" + path)
            ok = (st == 404) if not present else (st == 200)
            all_ok &= ok
            result["checks"].append({"module": mod, "installed": present, kind: path, "status": st, "ok": ok})
        result["ok"] = all_ok and bool(result["checks"])
        return result
    finally:
        _kill_tree(proc)
        log.close()
        if not keep:
            time.sleep(1)
            _rmtree(run)
        result["run_dir"] = str(run) + ("（保留）" if keep else "（已刪除）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg", required=True)
    ap.add_argument("--port", type=int, default=6701)
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    r = drill(a.pkg, a.port, a.keep)
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
