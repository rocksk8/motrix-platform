# -*- coding: utf-8 -*-
"""正式機狀態快照（唯讀）——PROD-DEV-CHANNEL.md §3 的 `status\\latest.json` 由這支產生。

用法（正式機 Claude 依開發機要求執行）：
  python backend\\tools\\prod_status_snapshot.py [--root <安裝目錄>] [--port 666]
         [--archive-root <雲端存檔根目錄>] [--out <輸出檔>]

🔴 嚴格唯讀：
  - 安裝目錄內**不開任何寫入**；不 import 產品程式（import 會寫 __pycache__、import main 有副作用）⇒ 只用標準庫；
  - 不啟停服務、不讀資料庫（雲端存檔根目錄的「設定值」在 DB 裡 ⇒ 不讀，改為 --archive-root 或與
    archive._detect_archive_base 同規則掃磁碟機，並在 backups.archive_root_source 註明是哪一種）；
  - 唯一的寫入是 --out：只寫到明確指定的檔、且不可在安裝目錄內；先 .tmp 再 os.replace。
每一個來源讀不到 ⇒ 該欄 null，原因寫進 errors[欄位]；不因單一來源失敗而中止。
輸出只含白名單欄位（不含個資、金鑰、帳密、token）。
"""
import argparse
import json
import os
import re
import shutil
import socket
import ssl
import string
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime

sys.dont_write_bytecode = True

SCHEMA = 1
DEFAULT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ARCHIVE_SUBPATH = os.path.join("我的雲端硬碟", "系統存檔")        # 與 archive._ARCHIVE_SUBPATH 同
_DATE_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_APPLY_RESULT = re.compile(r"^apply_update_(\d{8}_\d{6})\.result\.json$")
_ALERT_LOG = re.compile(r"^\d{4}-\d{2}-\d{2}\.log$")
_REASON_MAX = 200


def _read_json(path):
    with open(path, "r", encoding="utf-8-sig") as f:          # apply_update.ps1 以 PS5.1 UTF8（含 BOM）寫
        return json.load(f)


def _mtime_iso(path):
    return datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="seconds")


def _err(e):
    return "%s: %s" % (type(e).__name__, e)


# ── 各來源（每支回傳值；失敗丟例外，由 collect 記進 errors）──────────────────────────
def deployed_commit(root):
    p = os.path.join(root, "backend", ".deployed_commit.json")
    if not os.path.isfile(p):
        raise FileNotFoundError("沒有 backend\\.deployed_commit.json")
    d = _read_json(p)
    return d.get("commit"), {k: d.get(k) for k in ("commit_short", "branch", "applied_at", "built_at")}


def modules(root):
    p = os.path.join(root, "backend", "logs", "module_states.json")
    if not os.path.isfile(p):
        raise FileNotFoundError("沒有 backend\\logs\\module_states.json（服務這一版啟動過才會有）")
    d = _read_json(p)
    return {"started_at": d.get("started_at"),
            "modules": [{"key": m.get("key"), "version": m.get("version"), "state": m.get("state")}
                        for m in (d.get("modules") or [])]}


def last_apply(root):
    logs = os.path.join(root, "backend", "logs")
    names = sorted(n for n in (os.listdir(logs) if os.path.isdir(logs) else []) if _APPLY_RESULT.match(n))
    if not names:
        raise FileNotFoundError("backend\\logs 沒有 apply_update_*.result.json")
    d = _read_json(os.path.join(logs, names[-1]))
    return {"timestamp": d.get("timestamp") or _APPLY_RESULT.match(names[-1]).group(1),
            "status": d.get("status"), "rolled_back": d.get("rolled_back"), "service": d.get("service"),
            "exit": d.get("exit"), "result_file": names[-1]}


def archive_root(arg):
    """⇒ (路徑, 來源)。與 archive._detect_archive_base 同規則；DB 裡的「儲存位置」設定不讀（唯讀原則）。"""
    if arg is not None:
        return arg, "arg"
    for letter in string.ascii_uppercase:
        cand = "%s:\\%s" % (letter, _ARCHIVE_SUBPATH)
        if os.path.isdir(cand):
            return cand, "auto_scan"
    return None, "auto_scan"


def latest_done(base):
    """<base>\\<yyyy-mm-dd>\\.done 最新的一個 ⇒ {date, done_at}；只列一層、只 stat，不遞迴。"""
    if not os.path.isdir(base):
        raise FileNotFoundError("目錄不存在：%s" % base)
    for name in sorted((n for n in os.listdir(base) if _DATE_DIR.match(n)), reverse=True):
        marker = os.path.join(base, name, ".done")
        if os.path.isfile(marker):
            return {"date": name, "done_at": _mtime_iso(marker)}
    raise FileNotFoundError("沒有任何日期資料夾含 .done：%s" % base)


def newest_alert(root, since):
    """backup_alerts\\<yyyy-mm-dd>.log（archive._write_backup_alert 逐行 `時間\\t等級\\t原因`）裡
    時間 > since 的最新一筆；since 為 None ⇒ 全部裡最新一筆。沒有 ⇒ None。另附黏著警示檔是否存在。"""
    d = os.path.join(root, "backup_alerts")
    sticky = os.path.join(d, "BACKUP_ALERT.txt")
    info = {"sticky_alert_file": os.path.isfile(sticky),
            "sticky_alert_at": _mtime_iso(sticky) if os.path.isfile(sticky) else None, "newest": None}
    if not os.path.isdir(d):
        return info
    best = None
    for n in sorted(x for x in os.listdir(d) if _ALERT_LOG.match(x)):
        if since and n[:10] < since[:10]:
            continue
        with open(os.path.join(d, n), "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.rstrip("\r\n").split("\t", 2)
                if len(parts) < 3 or (since and parts[0] <= since):
                    continue
                if best is None or parts[0] >= best[0]:
                    best = parts
    if best:
        info["newest"] = {"timestamp": best[0], "level": best[1], "reason": best[2][:_REASON_MAX]}
    return info


def http_probe(root, port, timeout):
    scheme = "https" if os.path.isfile(os.path.join(root, "backend", "certs", "cert.pem")) else "http"
    base = "%s://127.0.0.1:%d" % (scheme, port)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE                            # 只打本機 loopback（同 _healthcheck_ping.py）
    out = {"base_url": base, "ping": None, "api_version": None, "errors": {}}
    try:
        with urllib.request.urlopen(base + "/api/ping", timeout=timeout, context=ctx) as r:
            out["ping"] = getattr(r, "status", None) or r.getcode()
    except urllib.error.HTTPError as e:
        out["ping"] = e.code
    except Exception as e:
        out["errors"]["ping"] = _err(e)
    try:
        with urllib.request.urlopen(base + "/api/system/version", timeout=timeout, context=ctx) as r:
            v = json.loads(r.read().decode("utf-8"))
            out["api_version"] = v.get("version")
    except Exception as e:
        out["errors"]["api_version"] = _err(e)
    return out


def pids_on_port(port):
    if os.name != "nt":
        raise OSError("只支援 Windows（netstat -ano）")
    r = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, timeout=20)
    text = r.stdout.decode("utf-8", errors="replace")
    pids = set()
    for line in text.splitlines():
        cols = line.split()
        # TCP  0.0.0.0:666  0.0.0.0:0  LISTENING  1234（狀態字可能被語系翻譯 ⇒ 以遠端 *:0 判斷在聽）
        if len(cols) >= 5 and cols[0].upper() == "TCP" and cols[1].rsplit(":", 1)[-1] == str(port) \
                and cols[2].rsplit(":", 1)[-1] == "0" and cols[-1].isdigit():
            pids.add(int(cols[-1]))
    return sorted(pids)


# ── 組裝 ─────────────────────────────────────────────────────────────────────
def collect(root, port=666, archive_arg=None, timeout=3.0):
    root = os.path.abspath(root)
    snap = {"schema": SCHEMA, "taken_at": datetime.now().isoformat(timespec="seconds"),
            "hostname": socket.gethostname(), "install_root": root,
            "deployed_commit": None, "deployed": None, "api_version": None, "ping": None, "api_base_url": None,
            "modules": None, "modules_started_at": None, "last_apply": None,
            "backups": {"archive_root": None, "archive_root_source": None, "daily_done_latest": None,
                        "local_snapshot_done_latest": None, "alerts_since": None,
                        "sticky_alert_file": None, "sticky_alert_at": None},
            "disk_free_gb": None, "port": port, "service_pids_on_666": None, "errors": {}}
    errors = snap["errors"]
    if not os.path.isdir(root):
        errors["install_root"] = "安裝目錄不存在：%s" % root

    try:
        snap["deployed_commit"], snap["deployed"] = deployed_commit(root)
    except Exception as e:
        errors["deployed_commit"] = _err(e)
    try:
        m = modules(root)
        snap["modules"], snap["modules_started_at"] = m["modules"], m["started_at"]
    except Exception as e:
        errors["modules"] = _err(e)
    try:
        snap["last_apply"] = last_apply(root)
    except Exception as e:
        errors["last_apply"] = _err(e)

    b = snap["backups"]
    try:
        ar, src = archive_root(archive_arg)
        b["archive_root"], b["archive_root_source"] = ar, src
        if ar is None:
            raise FileNotFoundError("掃不到任何磁碟機含 %s（雲端硬碟未掛載？可用 --archive-root 指定）" % _ARCHIVE_SUBPATH)
        b["daily_done_latest"] = latest_done(os.path.join(ar, "每日備份"))
    except Exception as e:
        errors["backups.daily_done_latest"] = _err(e)
    try:
        b["local_snapshot_done_latest"] = latest_done(os.path.join(root, "backend", "db_backups"))
    except Exception as e:
        errors["backups.local_snapshot_done_latest"] = _err(e)
    try:
        since = (b["daily_done_latest"] or {}).get("done_at")
        a = newest_alert(root, since)
        b["alerts_since"], b["sticky_alert_file"], b["sticky_alert_at"] = a["newest"], a["sticky_alert_file"], a["sticky_alert_at"]
        if since is None:
            errors["backups.alerts_since"] = "沒有每日 .done 時間 ⇒ alerts_since 為全部告警中最新一筆"
    except Exception as e:
        errors["backups.alerts_since"] = _err(e)

    try:
        h = http_probe(root, port, timeout)
        snap["api_base_url"], snap["ping"], snap["api_version"] = h["base_url"], h["ping"], h["api_version"]
        errors.update(h["errors"])
    except Exception as e:
        errors["ping"] = _err(e)
    try:
        snap["disk_free_gb"] = round(shutil.disk_usage(root).free / 1024 ** 3, 1)
    except Exception as e:
        errors["disk_free_gb"] = _err(e)
    try:
        snap["service_pids_on_666"] = pids_on_port(port)
    except Exception as e:
        errors["service_pids_on_666"] = _err(e)
    return snap


def _inside(path, root):
    try:
        return os.path.commonpath([os.path.normcase(os.path.abspath(path)),
                                   os.path.normcase(os.path.abspath(root))]) == os.path.normcase(os.path.abspath(root))
    except ValueError:                                         # 不同磁碟機
        return False


def write_out(snap, out, root):
    """原子寫入 --out。拒絕：在安裝目錄內、上兩層目錄不存在（只允許補建最後一層，例 status\\）。"""
    out = os.path.abspath(out)
    if _inside(out, root):
        raise ValueError("--out 不可在安裝目錄內（唯讀工具）：%s" % out)
    parent = os.path.dirname(out)
    if not os.path.isdir(parent):
        if not os.path.isdir(os.path.dirname(parent)):
            raise ValueError("--out 的上層目錄不存在：%s" % os.path.dirname(parent))
        os.mkdir(parent)
    tmp = out + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=1)
        os.replace(tmp, out)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return out


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="正式機狀態快照（唯讀）")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="安裝目錄（預設：本檔所在 backend\\tools 的上兩層）")
    ap.add_argument("--port", type=int, default=666)
    ap.add_argument("--archive-root", default=None, help="雲端存檔根目錄（…\\我的雲端硬碟\\系統存檔）；省略 ⇒ 掃磁碟機")
    ap.add_argument("--timeout", type=float, default=3.0)
    ap.add_argument("--out", default=None, help="另存 JSON（原子寫入；不可在安裝目錄內）")
    a = ap.parse_args(argv)
    snap = collect(a.root, a.port, a.archive_root, a.timeout)
    if a.out:
        try:
            snap["written_to"] = write_out(dict(snap, written_to=os.path.abspath(a.out)), a.out, os.path.abspath(a.root))
        except Exception as e:
            snap["errors"]["out"] = _err(e)
            print(json.dumps(snap, ensure_ascii=False, indent=1))
            return 2
    print(json.dumps(snap, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
