# -*- coding: utf-8 -*-
"""D7 最終轉移升級驗證（RUN-PLAN §3）：用 V9 開發目錄的**複本**，照 UPGRADE-RUNBOOK 走一次完整的升級與兩種回滾。

  python tools/platform/final_drill.py [--v9-dir C:\\Users\\hichan\\Desktop\\MOTRIX-ERP] [--drill-root D:\\MOTRIX-FINAL-DRILL]
                                       [--package <部署包目錄> | --new-rev origin/platform]
                                       [--report docs/platform/FINAL-DRILL-REPORT.md] [--keep-install]

步驟（每一步記耗時、結果、雜湊）：
  1. 備份來源：V9 開發目錄的資料庫以**唯讀連線**＋Online Backup 複製到 `<drill-root>/source-backup/`，資料目錄逐檔複製，附雜湊清單。
  2. 建演練安裝目錄：整份複製成 `<drill-root>/v9-install/`（不含 .git／node_modules／venv／deploy_packages），資料庫一樣走 Online Backup；
     放開發機標記（`.no_email_send`、`.no_cloud_archive`）；補一份今天的本機快照（開發機的 V9 沒有每日排程，預檢要求今天或昨天有 `.done`）。
  3. 新版程式：`--package`（build_deploy_package.ps1 打出來的部署包）；沒給 ⇒ `git archive <--new-rev>`（報告會註明不是部署包）。
  4. 升級：預檢 → 備份＋試還原 → 轉換 → 驗證（新版啟動 ping）。
  5. 冒煙：在轉換後的目錄啟動新版，用演練專用的超級管理員登入，逐一打主要頁面與 API（報價、案件、傳票、獎金、出納、報表、模組管理、自訂模組）。
  6. 回滾：用**第一份**備份「完整回滾」→ 與 source-backup 比對邏輯內容 → V9 啟動 ping；再轉換一次 → 「只回程式」→ V9 啟動 ping。
  7. 報告：`--report`（Markdown）；演練安裝目錄預設刪除，`source-backup` 保留到使用者回來（RUN-PLAN §3-7）。

🔴 安全
- **V9 開發目錄只讀不寫**：資料庫用 `mode=ro` 開；不在它底下建任何檔。
- 演練路徑不可以含 `V9.0`（V9 以安裝路徑判斷正式機、會真的寄信）；啟動一律帶 SAFE_ENV（不跑排程、不上雲、不寄信）。
- 不連正式機、不讀 G:。
"""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import upgrade as T  # noqa: E402
import upgrade_drill as UD  # noqa: E402
U = T.U

DEFAULT_V9 = r"C:\Users\hichan\Desktop\MOTRIX-ERP"
DEFAULT_ROOT = r"D:\MOTRIX-FINAL-DRILL"
_SKIP_DIRS = {".git", "node_modules", "__pycache__", "deploy_packages", ".pytest_cache"}
_DB_SUFFIXES = (".db", ".db-wal", ".db-shm", ".db-journal")
DRILL_ADMIN = ("final_drill_admin", "Final-Drill-Pass-2026!")

#: 冒煙：(名稱, 方法, 路徑[, 模組 key])。200 才算過；頁面用 GET。
#: 帶模組 key 的條目：該模組不在安裝包（`backend/modules/<key>/module.json` 不存在）⇒ 記成「略過：模組不在包內」，
#: 明寫在結果裡，不算過也不算不過（M08 反向控制：產品選配拿掉某模組時，演練不可以因為它而紅，也不可以默默少一項）。
#: 尚未搬進 modules/ 的功能不帶 key（它們一定在包內）；搬遷時補上。
SMOKE = [
    ("首頁", "GET", "/"), ("登入頁", "GET", "/pages/login.html"),
    ("報價單列表", "GET", "/api/quotations"), ("案件管理頁", "GET", "/pages/case-management.html"),
    ("傳票列表", "GET", "/api/vouchers"), ("傳票頁", "GET", "/pages/voucher.html"),
    ("獎金分潤項目", "GET", "/api/bonus/items", "payroll"), ("獎金分潤頁", "GET", "/pages/bonus.html"),
    ("出納待付", "GET", "/api/cashier/payable-queue", "arap"), ("請款單列表", "GET", "/api/payment-requests", "arap"),
    ("營運報表", "GET", "/api/reports/financial", "analytics"), ("營運報表頁", "GET", "/pages/reports.html", "analytics"),
    ("模組管理", "GET", "/api/system/modules"), ("自訂模組清單", "GET", "/api/custom-modules"),
    ("版本", "GET", "/api/system/version"),
    ("定義文件庫", "GET", "/api/definitions/custom_module"),         # 第二批（P8 缺口 #5）已合回
]


def smoke_plan(backend_dir: str) -> list:
    """SMOKE ⇒ [(名稱, 方法, 路徑, 略過原因或 None)]；略過原因只有「模組不在包內」一種。"""
    plan = []
    for entry in SMOKE:
        name, method, path = entry[:3]
        key = entry[3] if len(entry) > 3 else None
        absent = key and not os.path.isfile(os.path.join(backend_dir, "modules", key, "module.json"))
        plan.append((name, method, path, ("模組 %s 不在安裝包" % key) if absent else None))
    return plan


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ro_backup(src: str, dst: str) -> None:
    """來源**一個位元組都不寫**的備份：先把 .db 與既有的 -wal 以位元組複製到暫存，再從暫存做 Online Backup。

    ☠️ 不能直接開來源：WAL 模式的庫，連 `mode=ro` 的連線都會在來源目錄建出 `-wal`／`-shm`（本檔的測試抓到）。
    ⚠ 複製的那一瞬間來源不可以有人在寫 ⇒ 呼叫端先確認 V9 沒有在跑（`main()` 檢查 port 666）。"""
    import tempfile
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="d7-ro-")
    try:
        copy = os.path.join(tmp, os.path.basename(src))
        shutil.copyfile(src, copy)
        for side in ("-wal",):
            if os.path.exists(src + side):
                shutil.copyfile(src + side, copy + side)
        s = sqlite3.connect(copy)
        d = sqlite3.connect(dst)
        try:
            s.backup(d)
        finally:
            d.close()
            s.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _walk(root: str):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in _SKIP_DIRS and not d.startswith(".venv")]
        for fn in fns:
            yield os.path.join(dp, fn)


def _dbs(root: str) -> list:
    return sorted(os.path.relpath(p, root) for p in _walk(root) if p.endswith(".db")
                  and "db_backups" not in Path(p).parts and "rollback_snapshots" not in Path(p).parts)


class _Stop(Exception):
    pass


def _must(rep):
    if not rep["steps"][-1]["ok"]:
        raise _Stop(rep["steps"][-1]["name"])


def step(rep, name):
    """`with step(rep, "名稱") as s:` ⇒ 記耗時與例外；s 是這一步的結果 dict。"""
    class _S:
        def __enter__(self):
            self.t0 = time.monotonic()
            self.s = {"name": name, "ok": None}
            rep["steps"].append(self.s)
            print("[D7] %s …" % name, flush=True)
            return self.s

        def __exit__(self, et, ev, tb):
            self.s["seconds"] = round(time.monotonic() - self.t0, 1)
            if et is not None:
                self.s["ok"], self.s["error"] = False, "%s: %s" % (et.__name__, ev)
            elif self.s["ok"] is None:
                self.s["ok"] = True
            print("[D7] %s ⇒ %s（%.1f 秒）" % (name, "OK" if self.s["ok"] else "失敗", self.s["seconds"]), flush=True)
            return et is not None and not isinstance(ev, KeyboardInterrupt)
    return _S()


def logical_digest(db_path: str) -> str:
    """資料庫的邏輯內容雜湊（iterdump 逐行）：位元組會因 Online Backup 的標頭計數器而不同，邏輯內容不會。"""
    if not os.path.isfile(db_path):             # connect 會默默建一個空庫 ⇒ 兩邊都不在時會「相同」
        raise FileNotFoundError(db_path)
    h = hashlib.sha256()
    c = sqlite3.connect(db_path)
    try:
        for line in c.iterdump():
            h.update(line.encode("utf-8") + b"\n")
    finally:
        c.close()
    return h.hexdigest()


def backup_source(v9: str, dest: str) -> dict:
    files = {}
    for rel in _dbs(v9):
        ro_backup(os.path.join(v9, rel), os.path.join(dest, rel))
        files[rel] = sha256(os.path.join(dest, rel))
    data = U.inventory(v9, kinds=("data",))
    for rel in data:
        if rel.endswith(_DB_SUFFIXES):
            continue
        dst = os.path.join(dest, "data", rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(v9, rel), dst)
    manifest = {"at": datetime.now().isoformat(timespec="seconds"), "source": v9, "db": files,
                "data": {k: v for k, v in data.items() if not k.endswith(_DB_SUFFIXES)}}
    with open(os.path.join(dest, "source_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    return {"db": files, "data_files": len(manifest["data"])}


def build_install(v9: str, install: str) -> dict:
    assert "V9.0" not in install, "演練路徑含 V9.0：%s" % install
    n = 0
    for full in _walk(v9):
        rel = os.path.relpath(full, v9)
        if rel.endswith(_DB_SUFFIXES):
            continue
        dst = os.path.join(install, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(full, dst)
        n += 1
    for rel in _dbs(v9):
        ro_backup(os.path.join(v9, rel), os.path.join(install, rel))
    # 開發機的舊備份告警（例：開發機沒有掛雲端 ⇒「找不到雲端備份路徑」）會讓預檢擋下。
    # 正式機升級前要由人處理；演練複本裡封存它，並把內容寫進報告（不是刪掉、也不是假裝沒有）。
    dev_alert = None
    alert = os.path.join(install, "backup_alerts", "BACKUP_ALERT.txt")
    if os.path.exists(alert):
        with open(alert, encoding="utf-8", errors="replace") as f:
            dev_alert = f.read(600)
        os.replace(alert, os.path.join(install, "backup_alerts", "BACKUP_ALERT.drill-archived.txt"))
    for marker in (".no_email_send", ".no_cloud_archive"):
        with open(os.path.join(install, marker), "w", encoding="utf-8") as f:
            f.write("D7 final drill")
    snap = os.path.join(install, "backend", "db_backups", date.today().isoformat())
    os.makedirs(snap, exist_ok=True)
    U.online_backup(os.path.join(install, "backend", "motrix_erp.db"), os.path.join(snap, "motrix_erp.db"))
    with open(os.path.join(snap, ".done"), "w", encoding="utf-8") as f:
        f.write("D7 final drill")
    return {"files": n, "db": _dbs(install), "dev_alert_archived": dev_alert}


def _py_in(backend: str, code: str) -> str:
    env = {**os.environ, **T.SAFE_ENV}
    r = subprocess.run([sys.executable, "-c", code], cwd=backend, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=180)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return r.stdout.strip()


def ensure_drill_admin(install: str) -> None:
    """演練專用的超級管理員（只在演練複本裡；不需要改密碼、沒有 TOTP）。"""
    backend = os.path.join(install, "backend")
    code = ("import json,sqlite3;from datetime import datetime;from helpers.auth import _hash_pw;"
            "from helpers.module_registry import SUPERADMIN_DEFAULT as S;"
            "c=sqlite3.connect('motrix_erp.db');u,p=%r,%r;"
            "c.execute('DELETE FROM users WHERE username=?',(u,));"
            "c.execute(\"INSERT INTO users (username,password_hash,display_name,role,email,modules,active,created_at,must_change_password)"
            " VALUES (?,?,?,?,?,?,1,?,0)\",(u,_hash_pw(p),'D7 演練','superadmin','',json.dumps(list(S)),datetime.now().isoformat()));"
            "c.commit();print('OK')" % DRILL_ADMIN)
    assert _py_in(backend, code).endswith("OK")


def smoke(install: str) -> dict:
    port = UD.free_port()
    env = {**os.environ, **T.SAFE_ENV}
    log = open(os.path.join(install, "backend", "logs", "final_drill_smoke.log"), "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
                            cwd=os.path.join(install, "backend"), env=env, stdout=log, stderr=subprocess.STDOUT)
    base = "http://127.0.0.1:%d" % port
    out = {"port": port, "checks": []}
    try:
        t0 = time.monotonic()
        while time.monotonic() - t0 < 180:
            try:
                urllib.request.urlopen(base + "/api/ping", timeout=2)
                break
            except Exception:                                   # noqa: BLE001
                time.sleep(1)
        req = urllib.request.Request(base + "/api/auth/login", method="POST",
                                     data=json.dumps({"username": DRILL_ADMIN[0], "password": DRILL_ADMIN[1]}).encode(),
                                     headers={"Content-Type": "application/json"})
        token = json.loads(urllib.request.urlopen(req, timeout=10).read())["token"]
        for name, method, path, skipped in smoke_plan(os.path.join(install, "backend")):
            if skipped:
                out["skipped"] = out.get("skipped", []) + [{"name": name, "path": path, "reason": skipped}]
                continue
            r = urllib.request.Request(base + path, method=method, headers={"Authorization": "Bearer " + token})
            try:
                code = urllib.request.urlopen(r, timeout=30).status
            except urllib.error.HTTPError as e:
                code = e.code
            except Exception as e:                              # noqa: BLE001
                code = "%s" % type(e).__name__
            out["checks"].append({"name": name, "path": path, "status": code, "ok": code == 200})
    finally:
        T._stop(proc)
        log.close()
    out["ok"] = bool(out["checks"]) and all(c["ok"] for c in out["checks"])
    return out


#: 第一份備份＝轉換前的原始 V9 庫（完整回滾唯一正確的基準，稽核 D K-M1）；第二份＝再轉換前的狀態（只回程式用）
FIRST_BACKUP, SECOND_BACKUP = "upgrade-backup", "upgrade-backup-2"
DRILL_DIRS = ("v9-install", "new", FIRST_BACKUP, SECOND_BACKUP)


def full_rollback_step(root: str) -> dict:
    """6a 完整回滾（K-M1）：以**第一份**備份還原，V9 啟動**之前**比對主庫與 source-backup 的邏輯內容。
    還原有問題或內容不相等 ⇒ 判失敗、不啟動 V9（在不對的庫上啟動只會多寫東西，讓現場更難看懂）。"""
    install = os.path.join(root, "v9-install")
    out = {"backup": FIRST_BACKUP}
    out["problems"] = U.rollback(install, os.path.join(root, FIRST_BACKUP), "full", {})
    out["logical_equal_to_source"] = (
        logical_digest(os.path.join(install, "backend", "motrix_erp.db"))
        == logical_digest(os.path.join(root, "source-backup", "backend", "motrix_erp.db")))
    if out["problems"] or not out["logical_equal_to_source"]:
        out["v9_ping"] = {"ok": False, "skipped": "還原有問題或與原始庫不相等，不啟動 V9"}
    else:
        r = T.start_and_ping(install, UD.free_port())
        out["v9_ping"] = {k: v for k, v in r.items() if k != "log"}
    out["ok"] = not out["problems"] and out["logical_equal_to_source"] and bool(out["v9_ping"].get("ok"))
    return out


def cleanup(root: str, ok: bool, keep: bool) -> list:
    """K-S3：全部通過（且沒有 --keep-install）才刪演練目錄；失敗時**保留**，回傳保留的路徑寫進報告，
    由人看完再刪（下一次執行會因 v9-install 已存在而拒絕，不會蓋掉現場）。source-backup 一律保留。"""
    present = [os.path.join(root, d) for d in DRILL_DIRS if os.path.exists(os.path.join(root, d))]
    if ok and not keep:
        for d in present:
            shutil.rmtree(d, ignore_errors=True)
        return []
    return present


def write_report(rep: dict, path: str) -> None:
    lines = ["# D7 最終轉移升級驗證報告", "",
             "> 產生：`tools/platform/final_drill.py`（%s）。來源：`%s`（只讀）；演練目錄：`%s`。" % (rep["at"], rep["v9_dir"], rep["drill_root"]),
             "> 新版程式：%s" % rep["new_source"],
             "> 冒煙用的演練帳號：`%s`（只插入演練複本的庫；完整回滾時隨原始庫一起還原掉）" % rep.get("drill_admin", DRILL_ADMIN[0]),
             "", "## 結果", "",
             "| # | 步驟 | 結果 | 耗時（秒） | 摘要 |", "|---|---|---|---|---|"]
    for i, s in enumerate(rep["steps"], 1):
        summary = {k: v for k, v in s.items() if k not in ("name", "ok", "seconds")}
        text = json.dumps(summary, ensure_ascii=False)
        lines.append("| %d | %s | %s | %s | %s |" % (i, s["name"], "✅" if s["ok"] else "❌", s.get("seconds", ""),
                                                  (text[:400] + "…") if len(text) > 400 else text))
    lines += ["", "## 總判定", "", "**%s**" % ("通過" if rep["ok"] else "未通過（見上表 ❌ 的步驟）"), ""]
    if rep.get("stopped_at"):
        lines += ["> 在「%s」失敗後停止：後面的步驟沒有意義，而且不應在壞掉的狀態上繼續動作。" % rep["stopped_at"], ""]
    if rep.get("kept_for_diagnosis"):
        lines += ["> 演練目錄**保留**供排查（確認後手動刪除；刪之前再跑一次會被拒絕）：",
                  *["> - `%s`" % d for d in rep["kept_for_diagnosis"]], ""]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--v9-dir", default=DEFAULT_V9)
    ap.add_argument("--drill-root", default=DEFAULT_ROOT)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--package")
    g.add_argument("--new-rev", default="origin/platform")
    ap.add_argument("--report", default=str(T.REPO / "docs" / "platform" / "FINAL-DRILL-REPORT.md"))
    ap.add_argument("--keep-install", action="store_true")
    a = ap.parse_args(argv)
    root = os.path.abspath(a.drill_root)
    assert "V9.0" not in root, "演練路徑含 V9.0"
    assert not os.path.exists(os.path.join(root, "v9-install")), \
        "演練目錄已有 v9-install（上次失敗時保留供排查，或用了 --keep-install）：看完後手動刪除 %s" % root
    assert not T.port_open(666), "port 666 有服務在跑：先停掉 V9 開發機的伺服器（複製資料庫時不可以有人在寫）"
    rep = {"at": datetime.now().isoformat(timespec="seconds"), "v9_dir": a.v9_dir, "drill_root": root, "steps": [],
           "new_source": ("部署包 `%s`" % a.package) if a.package else ("`git archive %s`（不是部署包）" % a.new_rev)}
    install, backup_dir = os.path.join(root, "v9-install"), os.path.join(root, FIRST_BACKUP)
    try:
        with step(rep, "1 備份來源（唯讀）") as s:
            s.update(backup_source(a.v9_dir, os.path.join(root, "source-backup")))
        _must(rep)
        with step(rep, "2 建演練安裝目錄") as s:
            s.update(build_install(a.v9_dir, install))
        _must(rep)
        new_src = a.package
        if not new_src:
            with step(rep, "3 取新版程式") as s:
                new_src = os.path.join(root, "new")
                os.makedirs(new_src)
                UD.git_export(a.new_rev, new_src)
                s["rev"] = subprocess.run(["git", "-C", str(T.REPO), "rev-parse", a.new_rev],
                                          capture_output=True, text=True).stdout.strip()
            _must(rep)
        with step(rep, "4a 預檢") as s:
            pf = U.preflight(install, v9_port_open=False, require_no_dev_markers=False)
            s.update(problems=pf["problems"]); s["ok"] = pf["ok"]
        _must(rep)
        with step(rep, "4b 備份＋試還原") as s:
            m = U.backup(install, backup_dir)
            s["files"], s["db"] = len(m["files"]), list(m["db"])
            s["problems"] = U.verify_backup_restorable(backup_dir); s["ok"] = not s["problems"]
            T._write_log(backup_dir, "backup_verify.json", {"problems": s["problems"]})   # 轉換只認已驗證的備份
        _must(rep)
        with step(rep, "4c 轉換") as s:
            s.update(T.convert(install, backup_dir, new_src))
            s["ok"] = bool(s.get("migrate", {}).get("ok", True))
        _must(rep)
        with step(rep, "4d 驗證（新版啟動）") as s:
            s["problems"] = T.verify(install, backup_dir, UD.free_port()); s["ok"] = not s["problems"]
        _must(rep)
        with step(rep, "5 冒煙") as s:
            ensure_drill_admin(install)
            s["drill_admin"] = DRILL_ADMIN[0] + "（只存在演練複本；完整回滾會把它一起還原掉）"
            s.update(smoke(install))
        # 稽核 D K-M1：完整回滾要用**第一份**備份（轉換前的 V9 庫），而且要證明還原後與原始庫邏輯內容相同。
        # 比對在 V9 啟動之前做（V9 一啟動就會寫每日掃描日期之類的執行期狀態）。
        with step(rep, "6a 完整回滾（第一份備份）") as s:
            s.update(full_rollback_step(root))
        _must(rep)
        backup2 = os.path.join(root, SECOND_BACKUP)
        with step(rep, "6b 再轉換（只回程式前）") as s:
            U.backup(install, backup2)
            s["backup_problems"] = U.verify_backup_restorable(backup2)
            T._write_log(backup2, "backup_verify.json", {"problems": s["backup_problems"]})
            if s["backup_problems"]:
                raise RuntimeError("第二次備份試還原不通過：%s" % s["backup_problems"])
            s.update(T.convert(install, backup2, new_src))
            s["verify"] = T.verify(install, backup2, UD.free_port()); s["ok"] = not s["verify"]
        _must(rep)
        with step(rep, "6c 只回程式") as s:
            code, log = T.rollback_and_ping(install, backup2, "code", UD.free_port())
            s.update(exit=code, problems=log["problems"], v9_ping=log["v9_ping"])
            s["ok"] = code == 0 and not log["problems"] and (log["v9_ping"] or {}).get("ok")
        _must(rep)
    except _Stop as e:
        rep["stopped_at"] = str(e)
    finally:
        rep["ok"] = bool(rep["steps"]) and all(s["ok"] for s in rep["steps"]) and "stopped_at" not in rep
        rep["drill_admin"] = DRILL_ADMIN[0]
        try:
            rep["kept_for_diagnosis"] = cleanup(root, rep["ok"], a.keep_install)
        finally:
            write_report(rep, a.report)
            with open(os.path.join(root, "final_drill.json"), "w", encoding="utf-8") as f:
                json.dump(rep, f, ensure_ascii=False, indent=1, default=str)
            print("[D7] 報告：%s；總判定：%s" % (a.report, "通過" if rep["ok"] else "未通過"))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
