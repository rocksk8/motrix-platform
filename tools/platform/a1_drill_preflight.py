"""A1 M1 演練的「不可能碰到正式機，而且要能證明」防線（PM 裁示 2026-11-14）。

三道，全部不主動連線正式機（不 ping、不連 TCP；可達性只看本機路由表，且只當資訊、不當放行條件）：
  1. 演練前（`check`）：排程工作「MOTRIX ERP Server Autostart」不存在；演練路徑不含 V9.0 且在 a1-drill 底下；
     6766／8766 沒人聽、正式 ERP 埠 666 本機沒人聽；本機沒有正式機的 IP。
  2. 安裝建好、啟動之前（`static_scan`）：掃演練目錄裡的設定與腳本副本（.ps1 .bat .cmd .env .ini .cfg .toml .yaml .yml .json），
     不得出現正式機位址、V9.0、或任何非本機的 ERP 位址；`apply_update.ps1` 副本的 `$ProdRoot`／`$Port`、`autostart.bat` 的埠與綁定位址必須指向演練。
  3. 演練期間（`ConnectionMonitor`）：每 2 秒用 netstat -ano 查演練程序樹（含子行程；Get-NetTCPConnection 在這台機器上查不到任何東西，會變成假綠燈，所以不用）有沒有連往任何非本機位址；
     一發現就殺掉整個程序樹、寫紀錄、演練中止。紀錄逐次落檔，演練報告附上它並寫明「整段演練對正式機 N 連線」。
     取樣有間隔：極短暫（<2 秒）的連線理論上可能漏看——所以第 1、2 道（沒有任何指向正式機的設定、ERP 位址只准本機）才是主要保證。

用法：
  python tools/platform/a1_drill_preflight.py [--root D:\\Claude-pm\\a1-drill\\<時間戳>]   # 只做第 1 道，結束碼 0＝可以建演練
  python tools/platform/a1_drill_preflight.py --scan <演練目錄> [--erp-port 6766]            # 第 2 道
「無法確認＝不通過」。
"""
import argparse
import errno
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

TASK_NAME = "MOTRIX ERP Server Autostart"
PROD_IP = "172.16.10.177"
ERP_PORT = 6766
DASH_PORT = 8766
PROD_ERP_PORT = 666
DRILL_BASE = r"D:\Claude-pm\a1-drill"

_REFUSED_ERRNOS = {errno.ECONNREFUSED, 10061}                          # 10061＝WSAECONNREFUSED：本機沒人聽
CONFIG_EXTS = {".ps1", ".bat", ".cmd", ".env", ".ini", ".cfg", ".toml", ".yaml", ".yml", ".json"}
# 隨產品出貨、本來就寫著正式機路徑／位址的檔案，而且**演練不會執行它們**（逐一列名、可審；新增的檔案提到正式機一律不通過）。
# 演練會執行或改寫的 apply_update.ps1、rollback_update.ps1、autostart.bat **不在這份名單**：它們必須是改寫後的演練副本。
KNOWN_PRODUCT_FILES = {
    r"backend\setup_autostart_task.ps1", r"backend\setup_heartbeat_task.ps1", r"backend\version_manifest.json",
    r"backend\tools\apply_module_update.ps1", r"backend\tools\fetch_root_ca.ps1", r"backend\tools\https_setup.ps1",
    r"backend\tools\setup_passkey_client.ps1",
    r"firewall_setup.bat",          # 隨產品出貨的防火牆規則（內網 172.16.10.0/23 允許進站）；演練不執行它
}
SKIP_DIRS = {".git", "node_modules", "__pycache__", "logs", ".venv", "venv", "docs", "tests", "frontend", "_rehearsal_work"}


class DrillAbort(Exception):
    """防線沒過 ⇒ 不可以演練（或演練中止）。str(e) 是逐項原因。"""


class Probes:
    """所有碰到本機環境的動作都在這裡（測試換掉它）。**沒有任何一個會對外連線。**"""

    def scheduled_task_exists(self, name):
        ps = "if (Get-ScheduledTask -TaskName '%s' -ErrorAction SilentlyContinue) { 'EXISTS' } else { 'ABSENT' }" % name.replace("'", "''")
        r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        out = (r.stdout or "").strip()
        if r.returncode != 0 or out not in ("EXISTS", "ABSENT"):
            raise RuntimeError("PowerShell 查詢排程工作沒有得到明確答案（rc=%s，輸出=%r，錯誤=%r）" % (r.returncode, out[:80], (r.stderr or "")[:120]))
        return out == "EXISTS"

    def is_listening(self, port):
        """本機有人在聽這個埠嗎？只連 127.0.0.1。⇒ True／False；無法判斷丟例外。"""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(6)                                      # Windows 對關閉的埠會重試 SYN 約 2 秒才回「被拒」
        try:
            rc = s.connect_ex(("127.0.0.1", port))
        finally:
            s.close()
        if rc == 0:
            return True
        if rc in _REFUSED_ERRNOS:
            return False
        b = socket.socket(socket.AF_INET, socket.SOCK_STREAM)        # 連線沒有明確答案 ⇒ 試著獨占這個埠：綁得上＝沒人聽
        try:
            b.bind(("127.0.0.1", port))
            return False
        except OSError as e:
            if e.errno in (errno.EADDRINUSE, 10048, 10013):          # 10048＝WSAEADDRINUSE；10013＝WSAEACCES（獨占綁定被占用時也可能回這個）
                return True
            raise RuntimeError("測 127.0.0.1:%d 得到無法判斷的結果 connect errno=%s，bind=%s" % (port, rc, e))
        finally:
            b.close()

    def local_ips(self):
        return {info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None)}

    def route_info(self, ip):
        """被動：本機路由表怎麼走（Find-NetRoute 只做路由選擇，不送封包）。⇒ 一行文字；查不到回 None。只當資訊。"""
        ps = ("$r = Find-NetRoute -RemoteIPAddress '%s' -ErrorAction SilentlyContinue | Select-Object -First 1; "
              "if ($r) { 'ROUTE interface#' + $r.InterfaceIndex + ' via ' + $r.NextHop } else { 'NOROUTE' }") % ip
        r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        out = (r.stdout or "").strip().splitlines()
        return out[-1] if out and r.returncode == 0 else None


# ── 第 1 道：演練前 ──────────────────────────────────────────────────────────

def _path_problem(root):
    p = str(root)
    low = p.lower().replace("/", "\\")
    if "v9.0" in low:
        return "演練目錄路徑含 V9.0（V9 以路徑判斷正式機）：%s" % p
    if not os.path.isabs(p):
        return "演練目錄不是絕對路徑：%s" % p
    if not low.startswith(DRILL_BASE.lower() + "\\"):
        return "演練目錄不在 %s 底下：%s" % (DRILL_BASE, p)
    if ".." in low.split("\\"):
        return "演練目錄含 ..：%s" % p
    return None


PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "FTP_PROXY")
# 演練程序只帶這些環境變數（其餘一律不繼承：MOTRIX_*、代理、雲端金鑰…）；PATH 是為了找得到 powershell／git／robocopy。
ENV_WHITELIST = ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PATH", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
                 "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "COMPUTERNAME", "USERNAME", "NUMBER_OF_PROCESSORS",
                 "PROCESSOR_ARCHITECTURE", "OS", "SYSTEMDRIVE", "HOMEDRIVE", "HOMEPATH")
_PROD_SUBNET = re.compile(r"\b172\.16\.10\.\d{1,3}\b")


def env_problems(environ, prod_ip=PROD_IP, allow_hosts=()):
    """目前環境變數有沒有指向非本機的值（會被子行程繼承）⇒ [說明]。`allow_hosts`＝明確放行的主機名（B7 用保留網域 example.invalid）。"""
    allow = {h.lower() for h in allow_hosts}
    out = []
    for k, v in sorted((environ or {}).items()):
        ku, vs = str(k).upper(), str(v)
        if prod_ip in vs or _PROD_SUBNET.search(vs):
            out.append("環境變數 %s 含正式機網段位址" % k)
            continue
        if ku in PROXY_VARS and ku != "NO_PROXY" and vs.strip():
            out.append("環境變數 %s 設了代理（%s）：連線可能被繞出去" % (k, vs[:60]))
            continue
        if ku.startswith("MOTRIX_"):
            for m in _URL.finditer(vs):
                if (m.group(2).lower() not in _LOOPBACK_HOSTS and m.group(2).lower() not in allow) or m.group(1):
                    out.append("環境變數 %s 指向非本機位址：%s" % (k, m.group(0)[:80]))
    return out


def sanitized_env(erp_port=ERP_PORT, dash_port=DASH_PORT, environ=None, extra=None, allow_hosts=()):
    """演練程序的乾淨環境：只帶白名單變數，再由這裡明確設定 127.0.0.1 的位址與離線 pip；`extra` 最後蓋上（也不得帶非本機位址）。"""
    src = {str(k).upper(): (str(k), str(v)) for k, v in (os.environ if environ is None else environ).items()}
    env = {src[w][0]: src[w][1] for w in ENV_WHITELIST if w in src}
    env.update({
        "MOTRIX_DELIVERY_ERP_URL": "http://127.0.0.1:%d" % erp_port,
        "MOTRIX_TRAIN": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
        "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_CONFIG_FILE": "NUL",
        "GIT_CONFIG_GLOBAL": "NUL", "GIT_CONFIG_NOSYSTEM": "1",          # 使用者層的 .gitconfig／pip.ini（USERPROFILE 在白名單）可能設代理 ⇒ 不讀
        "MOTRIX_DISABLE_SCHEDULERS": "1", "MOTRIX_CLOUD_ARCHIVE": "off", "MOTRIX_EMAIL_SEND": "off",
    })
    env.update(extra or {})
    bad = env_problems(env, allow_hosts=allow_hosts)
    if bad:
        raise DrillAbort("演練環境變數不乾淨：" + "；".join(bad))
    return env


def check(root, probes=None, erp_port=ERP_PORT, dash_port=DASH_PORT, prod_ip=PROD_IP, environ=None):
    """⇒ [(項目, 通過 True／False, 說明)]。每一項各自抓例外：查不出來 ＝ 不通過。不連線任何非本機位址。"""
    pr = probes or Probes()
    rows = []

    def run(label, fn):
        try:
            ok, detail = fn()
        except Exception as e:                                              # noqa: BLE001 — 無法確認＝不通過
            ok, detail = False, "無法確認：%s" % e
        rows.append((label, bool(ok), detail))

    def task():
        exists = pr.scheduled_task_exists(TASK_NAME)
        return (not exists), ("本機沒有排程工作「%s」" % TASK_NAME if not exists else "本機有排程工作「%s」：套用腳本會去啟動它（別的安裝）" % TASK_NAME)
    run("排程工作不存在", task)

    def path():
        prob = _path_problem(root)
        return prob is None, (prob or "路徑 %s 不含 V9.0、在 %s 底下" % (root, DRILL_BASE))
    run("演練路徑", path)

    for label, port, why in (("ERP 埠 %d 沒人聽" % erp_port, erp_port, "演練 ERP 的埠已被占用"),
                             ("儀表板埠 %d 沒人聽" % dash_port, dash_port, "演練儀表板的埠已被占用"),
                             ("正式 ERP 埠 %d 本機沒人聽" % PROD_ERP_PORT, PROD_ERP_PORT, "本機有東西在聽正式 ERP 的埠，這台可能就是正式機或有別的 ERP 在跑")):
        def port_free(port=port, why=why):
            listening = pr.is_listening(port)
            return (not listening), ("沒有人在聽 %d" % port if not listening else "%s（%d）" % (why, port))
        run(label, port_free)

    def not_prod_host():
        mine = pr.local_ips()
        return prod_ip not in mine, ("本機不是正式機（沒有正式機的 IP）" if prod_ip not in mine else "本機就是正式機的 IP ⇒ 絕對不能在這台演練")
    run("本機不是正式機", not_prod_host)

    def env_clean():
        bad = env_problems(os.environ if environ is None else environ, prod_ip)
        return (not bad), ("目前環境變數沒有指向非本機的值（演練程序另用乾淨環境啟動）" if not bad else "；".join(bad))
    run("環境變數沒有指向非本機", env_clean)
    return rows


def route_note(probes=None, prod_ip=PROD_IP):
    """資訊行（不影響放行）：本機路由表有沒有到正式機網段的路。被動查詢；不送任何封包。"""
    try:
        info = (probes or Probes()).route_info(prod_ip)
    except Exception as e:                                                  # noqa: BLE001
        info = None
        err = str(e)
    else:
        err = ""
    if info is None:
        return "路由表查詢無結果%s（資訊用，不影響放行）" % (("：" + err) if err else "")
    return "本機路由表對正式機網段的結果：%s（資訊用：有路由代表理論上連得到，所以才需要第 2、3 道防線）" % info


def require_ok(root, probes=None, **kw):
    """演練器入口的第一步：任何一項不過就丟 DrillAbort（演練不開始）。⇒ rows。"""
    rows = check(root, probes, **kw)
    bad = [r for r in rows if not r[1]]
    if bad:
        raise DrillAbort("演練環境檢查未通過，不執行演練：\n" + "\n".join("  ✗ %s：%s" % (b[0], b[2]) for b in bad))
    return rows


def format_rows(rows):
    return "\n".join("  %s %s：%s" % ("✓" if ok else "✗", label, detail) for label, ok, detail in rows)


# ── 第 2 道：靜態掃描 ───────────────────────────────────────────────────────

_URL_LINE = re.compile(r"(?i)(erp[_-]?url|errurl|\$erpurl|base[_-]?url|DELIVERY_ERP)")
_URL = re.compile(r"(?i)https?://([^\s/\"'`:<>@]+@)?(\[[0-9a-f:]+\]|[A-Za-z0-9._-]+)(?::\d+)?")
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


def _scan_text(rel, text, prod_ip, extra_patterns):
    out = []
    low = text.lower()
    if prod_ip in text:
        out.append((rel, "出現正式機位址"))
    elif _PROD_SUBNET.search(text):
        out.append((rel, "出現正式機網段位址（172.16.10.x）"))
    if "v9.0" in low:
        out.append((rel, "出現 V9.0（正式機路徑）"))
    for pat in extra_patterns or ():
        if pat and pat.lower() in low:
            out.append((rel, "出現指定的禁用字串 %r" % pat))
    for line in text.splitlines():
        if _URL_LINE.search(line):
            for m in _URL.finditer(line):
                if m.group(2).lower() not in _LOOPBACK_HOSTS or m.group(1):
                    out.append((rel, "ERP 位址不是本機：%s" % m.group(0)[:80]))
    return out


def iter_config_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix.lower() in CONFIG_EXTS or fn.lower().startswith(".env"):
                yield p


def static_scan(root, erp_port=ERP_PORT, prod_ip=PROD_IP, extra_patterns=(), dash_port=DASH_PORT, expect_root=None):
    """掃演練目錄的設定與腳本副本。⇒ {"files", "findings": [(相對路徑, 說明)], "allowed_product_files": [...]}；有任何 finding 就不可以演練。
    不讀程式原始碼（.py／.js）與文件資料夾：那是正式機也有的同一份程式，不是這次演練的設定。"""
    root = Path(root)
    findings, n, allowed = [], 0, []
    known = {k.lower() for k in KNOWN_PRODUCT_FILES}
    for p in iter_config_files(root):
        n += 1
        rel = str(p.relative_to(root))
        if rel.lower() in known:
            allowed.append(rel)
            continue
        try:
            text = p.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as e:
            findings.append((rel, "讀不了，無法確認：%s" % e))
            continue
        findings += _scan_text(rel, text, prod_ip, extra_patterns)
    findings += _ps1_findings(root, erp_port, expect_root)
    findings += _autostart_findings(root, erp_port)
    if n == 0:
        findings.append(("", "演練目錄裡沒有任何設定檔可掃，無法確認（目錄是否建好？）"))
    return {"files": n, "findings": findings, "allowed_product_files": allowed}


# 產品程式碼（.py／.js／.html）裡寫著正式機位址的檔案：**逐一列名、說明為什麼不會連線**；名單外的檔案出現正式機位址 ⇒ 擋下（不是資訊）。
CODE_PROD_ALLOWED = {
    r"backend\helpers\email_notify.py": "舊版預設連結位址常數（只組信件連結；演練 Email 全關：.no_email_send／MOTRIX_EMAIL_SEND=off）",
    r"backend\main.py": "CORS 白名單字串，不是連線",
    r"backend\routers\system.py": "註解",
    r"backend\tools\deploy_dashboard.html": "畫面文字，沒有連線",
    r"tools\platform\a1_drill_preflight.py": "偵測用的位址常數（演練安裝副本裡不會被執行）",
}
# 隨 git archive 出貨時被 export-ignore 的正式機遠端腳本：演練安裝與包裡**不可以有**（有就擋）。
EXPORT_IGNORED_ABSENT = (r"backend\tools\_dashboard_remote.ps1", r"backend\tools\check_prod_drift.ps1")
_PROD_CODE_RE = re.compile(r"172\.16\.1[01]\.\d{1,3}")


def code_prod_literals(root, prod_ip=PROD_IP):
    """產品程式碼（.py／.js／.html）裡寫著正式機位址（或 172.16.10／11 網段）的檔案（相對路徑，排序）。"""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in (SKIP_DIRS - {"tests"}) | {"site-packages", "node_modules"}]
        for fn in filenames:
            if fn.lower().endswith((".py", ".js", ".html")):
                p = Path(dirpath) / fn
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if prod_ip in text or _PROD_CODE_RE.search(text):
                    out.append(str(p.relative_to(root)))
    return sorted(out)


def code_literal_findings(root, prod_ip=PROD_IP):
    """阻擋式：⇒ (findings, allowed)。findings＝名單外出現正式機位址的程式檔，加上不該存在的 export-ignore 腳本；allowed＝[(檔, 理由)]（報告逐一列出）。"""
    allow = {k.lower(): v for k, v in CODE_PROD_ALLOWED.items()}
    findings, allowed = [], []
    for rel in code_prod_literals(root, prod_ip):
        if rel.lower() in allow:
            allowed.append((rel, allow[rel.lower()]))
        else:
            findings.append((rel, "程式碼裡有正式機位址，且不在已知名單（演練副本必須先改寫成本機死路，或審過後加進名單）"))
    for rel in EXPORT_IGNORED_ABSENT:
        if (Path(root) / rel).exists():
            findings.append((rel, "這支正式機遠端腳本應該被 export-ignore 擋在安裝與包之外，卻存在"))
    return findings, allowed


def _ps1_findings(root, erp_port, expect_root=None):
    out = []
    for name in ("apply_update.ps1", "rollback_update.ps1"):            # 套用和「回復到套用前」（B5 演練會真的執行）兩支都要是演練副本
        out += _one_ps1_findings(root, name, erp_port, expect_root)
    return out


def _one_ps1_findings(root, name, erp_port, expect_root=None):
    ps1 = Path(root) / "backend" / "tools" / name
    rel = "backend\\tools\\" + name
    if not ps1.is_file():
        return [(rel, "找不到腳本副本，無法確認 $ProdRoot／$Port")]
    text = ps1.read_text(encoding="utf-8-sig", errors="replace")
    roots = re.findall(r'^\$ProdRoot = "(.*)"\s*$', text, re.M)
    ports = re.findall(r"^\$Port = (\d+)\s*$", text, re.M)
    if len(roots) != 1 or len(ports) != 1:
        return [(rel, "`$ProdRoot`／`$Port` 不是各恰好一行（%d／%d）⇒ 無法確認" % (len(roots), len(ports)))]
    out = []
    if os.path.normcase(os.path.normpath(roots[0].replace("`$", "$"))) != os.path.normcase(os.path.normpath(str(expect_root or root))):
        out.append((rel, "$ProdRoot 沒有指向演練目錄：%s" % roots[0]))
    if int(ports[0]) != erp_port:
        out.append((rel, "$Port 不是演練埠 %d：%s" % (erp_port, ports[0])))
    return out


def _autostart_findings(root, erp_port):
    bat = Path(root) / "backend" / "autostart.bat"
    rel = "backend\\autostart.bat"
    if not bat.is_file():
        return [(rel, "找不到演練用的 autostart.bat，無法確認埠與綁定位址")]
    text = bat.read_text(encoding="utf-8-sig", errors="replace")
    out = []
    if not re.search(r"--port %d\b" % erp_port, text):
        out.append((rel, "autostart.bat 沒有 --port %d" % erp_port))
    if "--host 127.0.0.1" not in text:
        out.append((rel, "autostart.bat 沒有只綁 127.0.0.1"))
    return out


def require_static_ok(root, **kw):
    res = static_scan(root, **kw)
    if res["findings"]:
        raise DrillAbort("演練目錄靜態掃描未通過（掃了 %d 個設定檔），不啟動演練：\n%s" % (
            res["files"], "\n".join("  ✗ %s：%s" % f for f in res["findings"])))
    return res


# ── 第 3 道：動態監看 ───────────────────────────────────────────────────────

# 程序樹＝根程序（編排器自己、它起的程序、聽著演練埠的程序）＋所有子孫＋「命令列或執行檔路徑含演練目錄」的程序
# （父程序死了、被重新掛到別處的孤兒子行程也抓得到；`$PID`＝取樣用的這個 powershell 自己，不算）。
_TREE_PS = r"""
$roots = @(%(pids)s)
$needle = '%(needle)s'
$me = %(me)d
$all = Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId, CommandLine, ExecutablePath
$byId = @{}; foreach ($p in $all) { $byId[[int]$p.ProcessId] = $p }
$anc = New-Object 'System.Collections.Generic.HashSet[int]'
$cur = $me; $guard = 0
while ($byId.ContainsKey($cur) -and $guard -lt 64) { $guard++; $par = [int]$byId[$cur].ParentProcessId; if ($par -le 0 -or $anc.Contains($par) -or $par -eq $cur) { break }; [void]$anc.Add($par); $cur = $par }
$tree = New-Object 'System.Collections.Generic.HashSet[int]'
$hits = @()
foreach ($r in $roots) { if ([int]$r -gt 4) { [void]$tree.Add([int]$r) } }
if ($needle.Length -gt 0) { foreach ($p in $all) { if ([int]$p.ProcessId -ne [int]$PID -and ((($p.CommandLine -and $p.CommandLine.IndexOf($needle, [StringComparison]::OrdinalIgnoreCase) -ge 0)) -or (($p.ExecutablePath -and $p.ExecutablePath.IndexOf($needle, [StringComparison]::OrdinalIgnoreCase) -ge 0)))) { [void]$tree.Add([int]$p.ProcessId); $hits += @{ id = [int]$p.ProcessId; name = [string]$p.Name } } } }
foreach ($a in $anc) { [void]$tree.Remove([int]$a) }
$grew = $true
while ($grew) { $grew = $false; foreach ($p in $all) { if ([int]$p.ParentProcessId -gt 4 -and $tree.Contains([int]$p.ParentProcessId) -and -not $tree.Contains([int]$p.ProcessId)) { [void]$tree.Add([int]$p.ProcessId); $grew = $true } } }
[void]$tree.Remove([int]$PID)
foreach ($low in @(0,4)) { [void]$tree.Remove([int]$low) }
foreach ($a in $anc) { [void]$tree.Remove([int]$a) }
ConvertTo-Json -Compress -Depth 4 @{ tree = @($tree); ancestors = @($anc); needle = @($hits) }
"""
# ── 殺程序的白名單（PM 2026-11-14）：只殺「編排器自己啟動並記錄（pid＋建立時間）的程序」與它們的後代 ──────────────────
# 上面的 _TREE_PS 只用來「觀察」（連線取樣）；**任何殺程序的動作都只准用這個擁有清單**，不從根程序往下掃、不從埠或命令列撈。
# 唯一的補充：命令列含「本次演練目錄」（含時間戳、全機唯一）、名稱在 OWN_NAMES 內、建立時間不早於演練開始的程序
# （套用腳本自己重啟的 autostart 迴圈與 ERP 是孤兒、父程序已不在，只靠後代追不到）。
MIN_KILL_PID = 1000
PROTECTED_NAMES = {"system", "system idle process", "registry", "secure system", "memory compression", "smss.exe", "csrss.exe", "wininit.exe",
                   "services.exe", "lsass.exe", "winlogon.exe", "svchost.exe", "conhost.exe", "explorer.exe", "fontdrvhost.exe", "dwm.exe"}
OWN_NAMES = ("cmd.exe", "python.exe", "pythonw.exe", "powershell.exe", "pwsh.exe", "uvicorn.exe")
_OWNED_PS = r"""
$recs = @(%(recs)s)
$needle = '%(needle)s'
$me = %(me)d
$start = [long]%(start)d
$ownNames = @(%(ownnames)s)
$protNames = @(%(protnames)s)
$all = Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId, Name, CommandLine, CreationDate
$byId = @{}; foreach ($p in $all) { $byId[[int]$p.ProcessId] = $p }
function Ticks($p) { if ($p.CreationDate) { [long]$p.CreationDate.ToUniversalTime().Ticks } else { [long]0 } }
$anc = New-Object 'System.Collections.Generic.HashSet[int]'
$cur = $me; $guard = 0
while ($byId.ContainsKey($cur) -and $guard -lt 64) { $guard++; $par = [int]$byId[$cur].ParentProcessId; if ($par -le 0 -or $anc.Contains($par) -or $par -eq $cur) { break }; [void]$anc.Add($par); $cur = $par }
$own = New-Object 'System.Collections.Generic.HashSet[int]'
foreach ($r in $recs) { $pr = $r.Split(':'); $id = [int]$pr[0]; if ($byId.ContainsKey($id) -and (Ticks $byId[$id]) -eq [long]$pr[1]) { [void]$own.Add($id) } }
$needleRe = '(?i)' + [regex]::Escape($needle) + '($|[\\\s"''/])'
function ParentOk($p) { $pp = [int]$p.ParentProcessId; if (-not $byId.ContainsKey($pp)) { return $true }; return ((Ticks $byId[$pp]) -gt (Ticks $p)) }
if ($needle.Length -gt 0) { foreach ($p in $all) { if ([int]$p.ProcessId -ne [int]$PID -and ($ownNames -contains ([string]$p.Name).ToLower()) -and $p.CommandLine -and [regex]::IsMatch([string]$p.CommandLine, $needleRe) -and (Ticks $p) -ge $start -and (ParentOk $p)) { [void]$own.Add([int]$p.ProcessId) } } }
foreach ($a in $anc) { [void]$own.Remove([int]$a) }
$grew = $true
while ($grew) { $grew = $false; foreach ($p in $all) { $pp = [int]$p.ParentProcessId; if ($pp -ge %(minpid)d -and $own.Contains($pp) -and -not $own.Contains([int]$p.ProcessId) -and (Ticks $p) -ge (Ticks $byId[$pp])) { [void]$own.Add([int]$p.ProcessId); $grew = $true } } }
$out = @()
foreach ($id in $own) { if ($id -lt %(minpid)d -or $id -eq $me -or $id -eq [int]$PID -or $anc.Contains($id) -or -not $byId.ContainsKey($id)) { continue }; $n = ([string]$byId[$id].Name).ToLower(); if ($protNames -contains $n) { continue }; $out += @{ id = $id; name = $n; created = (Ticks $byId[$id]) } }
ConvertTo-Json -Compress -Depth 4 @{ owned = @($out) }
"""


def process_created(pid):
    """某 pid 目前的建立時間（UTC ticks）；查不到 ⇒ None。啟動後立刻記，殺之前拿來確認「還是同一個程序」（pid 會被重複使用）。"""
    ps = "$p = Get-CimInstance Win32_Process -Filter 'ProcessId=%d'; if ($p -and $p.CreationDate) { [string][long]$p.CreationDate.ToUniversalTime().Ticks }" % int(pid)
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = (r.stdout or "").strip().splitlines()
    try:
        return int(out[-1]) if out and r.returncode == 0 else None
    except ValueError:
        return None


def now_ticks(slack_seconds=5):
    return int((time.time() - slack_seconds + 62135596800) * 10_000_000)


def killable(pid, name=""):
    """硬性規則：pid < 1000、名稱是系統／殼層程序 ⇒ 永遠不殺。"""
    return int(pid) >= MIN_KILL_PID and str(name).lower() not in PROTECTED_NAMES


def owned_processes(records, base, start_ticks, me=None):
    """⇒ [{id, name, created}]：records＝[(pid, 建立時間ticks)]（編排器啟動時記下的）。只含「建立時間相符的記錄程序」＋它們的後代＋命令列含演練目錄的白名單程序；
    再套一次硬性規則（PowerShell 與 Python 兩邊各一次）。**查詢失敗 ⇒ 丟例外（呼叫端什麼都不殺）**。"""
    recs = ",".join("'%d:%d'" % (int(p), int(t)) for p, t in records if t)
    script = _OWNED_PS % {"recs": recs, "needle": str(base).replace("'", "''"), "me": me or os.getpid(), "start": int(start_ticks),
                          "ownnames": ",".join("'%s'" % n for n in OWN_NAMES), "protnames": ",".join("'%s'" % n for n in sorted(PROTECTED_NAMES)),
                          "minpid": MIN_KILL_PID}
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError("查擁有清單失敗（PowerShell rc=%s）：%s" % (r.returncode, (r.stderr or "")[:120]))
    doc = json.loads(r.stdout.strip().splitlines()[-1])
    items = doc.get("owned") or []
    if isinstance(items, dict):
        items = [items]
    return [{"id": int(i["id"]), "name": str(i["name"]), "created": int(i["created"])} for i in items
            if killable(i["id"], i["name"]) and int(i["id"]) != (me or os.getpid())]


# 連線清單用 `netstat -ano`：這台機器上 Get-NetTCPConnection 什麼都查不到（CIM MSFT_NetTCPConnection 是空的），
# 用它監看會永遠「0 連線」＝假綠燈；netstat 正常。所以取樣前一定先做正對照（見 positive_control）。
_NETSTAT_LINE = re.compile(r"^\s*TCP\s+(\S+)\s+(\S+)\s+(\S+)\s+(\d+)\s*$", re.I)
_NETSTAT_UDP = re.compile(r"^\s*UDP\s+(\S+)\s+(\S+)\s+(\d+)\s*$", re.I)


def _split_hostport(s):
    host, _sep, port = s.rpartition(":")
    return host.strip("[]").split("%")[0], (int(port) if port.isdigit() else 0)          # fe80::1%12


def parse_netstat(text):
    """`netstat -ano` 輸出 ⇒ [{"pid", "local", "remote", "port", "state", "proto"}]：只有 TCP（不含 LISTENING）。
    **UDP 一律不算連線**：這台機器的 `netstat -ano` 對 UDP 只列綁定位址、外部位址永遠是 `*:*`（看不到對端）⇒ 監看器看不到 UDP／ICMP，
    報告明講；UDP 行只用在 `listening_pids`（找演練埠的擁有者）。"""
    out = []
    for line in text.splitlines():
        m = _NETSTAT_LINE.match(line)
        if m:
            local, remote, state, pid = m.groups()
            if state.upper() == "LISTENING":
                continue
            host, port = _split_hostport(remote)
            out.append({"pid": int(pid), "local": local, "remote": host, "port": port, "state": state, "proto": "TCP"})
    return out


def listening_pids(text, ports):
    """`netstat -ano` ⇒ 在聽這些埠的程序 pid 集合（TCP LISTENING；UDP 綁定）。演練埠的擁有者一律算演練程序。"""
    ports = {int(p) for p in ports}
    out = set()
    for line in text.splitlines():
        m = _NETSTAT_LINE.match(line)
        if m and m.group(3).upper() == "LISTENING" and _split_hostport(m.group(1))[1] in ports:
            out.add(int(m.group(4)))
            continue
        u = _NETSTAT_UDP.match(line)
        if u and _split_hostport(u.group(1))[1] in ports:
            out.add(int(u.group(3)))
    return out


_LOOPBACK_ADDRS = {"127.0.0.1", "::1", "0.0.0.0", "::", "::ffff:127.0.0.1"}


def is_loopback_addr(a):
    a = (a or "").strip().lower()
    return a in _LOOPBACK_ADDRS or a.startswith("127.")


def violations(conns, prod_ip=PROD_IP):
    """連線清單 ⇒ [{...連線, "kind": "prod"|"non_loopback"}]。連往正式機位址標 prod，其餘非本機標 non_loopback。"""
    out = []
    for c in conns or []:
        if not is_loopback_addr(c.get("remote")):
            out.append(dict(c, kind="prod" if c.get("remote") == prod_ip else "non_loopback"))
    return out


class ConnectionMonitor:
    """每 `interval` 秒查演練程序的 TCP 連線（UDP／ICMP 看不到，報告明講）；非本機連線 ⇒ 殺程序、記下、`tripped`。紀錄每次取樣都落檔（jsonl）。

    演練程序＝`roots_fn()` 給的根程序（編排器自己與它起的程序）＋聽著演練埠的程序＋以上所有子孫＋命令列／執行檔路徑含演練目錄的程序（孤兒也抓）。
    取樣失敗：連續 `MAX_CONSECUTIVE_ERRORS` 次 ⇒ 殺程序、演練中止、報告標「未證明」；只要有失敗過，報告就不會印「N 連線」的保證句。
    `sampler(roots)` 預設用 PowerShell 取程序集合＋`netstat -ano`；測試換假的。**開跑前先呼叫 `positive_control()`。**"""

    MAX_CONSECUTIVE_ERRORS = 2

    def __init__(self, log_path, roots_fn, interval=2.0, sampler=None, killer=None, prod_ip=PROD_IP, clock=time.time,
                 drill_root=None, ports=(ERP_PORT, DASH_PORT), owned_fn=None):
        self.owned_fn = owned_fn                  # 殺程序只准殺它回傳的 pid（白名單）；None＝只套硬性規則（測試用）
        self.log_path, self.roots_fn, self.interval = Path(log_path), roots_fn, interval
        self.drill_root, self.ports = str(drill_root or ""), tuple(ports)
        self.sampler, self.killer, self.prod_ip, self.clock = sampler or self._ps_sample, killer or self._ps_kill, prod_ip, clock
        self.ticks = self.errors = self.consecutive_errors = self.prod_hits = self.other_hits = self.max_conns = 0
        self.tripped = None
        self.unproven = None                      # 字串：為什麼「沒有證明」
        self.tree_seen = set()
        self._needle_logged = set()
        self._last_tree = []
        self._ancestors = []
        self._stop = False
        self._thread = None
        self._control_done = False

    def _ps_sample(self, pids):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        net = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, creationflags=flags)
        if net.returncode != 0 or "TCP" not in net.stdout:
            raise RuntimeError("監看取樣（netstat）失敗 rc=%s" % net.returncode)
        roots = set(int(p) for p in pids) | listening_pids(net.stdout, self.ports)
        script = _TREE_PS % {"pids": ",".join(str(int(p)) for p in sorted(roots)) or "", "needle": self.drill_root.replace("'", "''"), "me": os.getpid()}
        r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, creationflags=flags)
        if r.returncode != 0 or not r.stdout.strip():
            raise RuntimeError("監看取樣（程序樹）失敗 rc=%s %s" % (r.returncode, (r.stderr or "")[:120]))
        doc = json.loads(r.stdout.strip().splitlines()[-1])
        tree = [int(x) for x in ([doc["tree"]] if isinstance(doc["tree"], int) else (doc["tree"] or []))]
        anc = [int(x) for x in ([doc["ancestors"]] if isinstance(doc["ancestors"], int) else (doc["ancestors"] or []))]
        mine = set(tree)
        nd = doc.get("needle") or []
        nd = [nd] if isinstance(nd, dict) else nd
        return {"tree": tree, "ancestors": anc, "needle": [{"id": int(x["id"]), "name": str(x["name"])} for x in nd],
                "conns": [c for c in parse_netstat(net.stdout) if c["pid"] in mine]}

    @staticmethod
    def _ps_kill(tree):
        for pid in sorted(tree, reverse=True):                              # 呼叫端（_kill）已套白名單與硬性規則；清單已含後代，不用 /T
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def _log(self, rec):
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _kill(self, tree):
        """殺程序。白名單：只殺 `owned_fn()`（編排器啟動並記錄、建立時間相符的程序＋後代）裡的 pid；pid < 1000、編排器自己與它所有祖先一律不殺
        （`taskkill /T` 殺祖先會連編排器一起殺掉）。被略過的記在紀錄裡；查不到擁有清單 ⇒ 什麼都不殺（已中止演練，由收尾處理）。"""
        protected = {os.getpid()} | set(self._ancestors)
        tree = [int(p) for p in tree]
        skipped = sorted(p for p in tree if p in protected or p < MIN_KILL_PID)
        keep = [p for p in tree if p not in protected and p >= MIN_KILL_PID]
        if self.owned_fn is not None:
            try:
                owned = {int(p) for p in self.owned_fn()}
            except Exception as e:                                          # noqa: BLE001
                self._log({"t": round(self.clock(), 1), "kill_error": "擁有清單查詢失敗，不殺任何程序：%s" % str(e)[:160]})
                return
            skipped += sorted(p for p in keep if p not in owned)
            keep = [p for p in keep if p in owned]
        if skipped:
            self._log({"t": round(self.clock(), 1), "event": "NOT_KILLED", "pids": sorted(set(skipped)), "why": "編排器自己／祖先／pid<%d／不在擁有清單" % MIN_KILL_PID})
        try:
            self.killer(keep)
        except Exception as e:                                              # noqa: BLE001 — 殺不掉也要記
            self._log({"t": round(self.clock(), 1), "kill_error": str(e)[:200]})

    def tick(self):
        """取樣一次。⇒ 違規清單（空＝乾淨）。取樣失敗記下；連續失敗達上限 ⇒ 殺程序並標未證明（`unproven`）。"""
        self.ticks += 1
        roots = list(self.roots_fn())
        try:
            snap = self.sampler(roots)
        except Exception as e:                                              # noqa: BLE001
            self.errors += 1
            self.consecutive_errors += 1
            self._log({"t": round(self.clock(), 1), "error": str(e)[:200], "consecutive": self.consecutive_errors})
            if self.consecutive_errors >= self.MAX_CONSECUTIVE_ERRORS and not (self.unproven or self.tripped):
                self.unproven = "連續 %d 次取樣失敗（最後一次：%s）⇒ 無法證明沒有連線，已中止演練" % (self.consecutive_errors, str(e)[:120])
                self._kill(list(set(self._last_tree) | set(int(r) for r in roots)))
                self._log({"t": round(self.clock(), 1), "event": "UNPROVEN", "reason": self.unproven})
            return []
        self.consecutive_errors = 0
        self._last_tree = list(snap.get("tree") or [])
        self._ancestors = list(snap.get("ancestors") or self._ancestors)
        self.tree_seen |= set(self._last_tree)
        for nd in snap.get("needle") or []:                                 # 只因命令列含演練目錄而被納入的程序：記名稱與 pid（外部程式剛好開著演練路徑時，誤判才查得出來）
            if nd["id"] not in self._needle_logged:
                self._needle_logged.add(nd["id"])
                self._log({"t": round(self.clock(), 1), "event": "NEEDLE_MATCH", "pid": nd["id"], "name": nd["name"]})
        conns = snap.get("conns") or []
        self.max_conns = max(self.max_conns, len(conns))
        bad = violations(conns, self.prod_ip)
        self.prod_hits += sum(1 for b in bad if b["kind"] == "prod")
        self.other_hits += sum(1 for b in bad if b["kind"] != "prod")
        self._log({"t": round(self.clock(), 1), "tree": len(self._last_tree), "conns": len(conns), "violations": bad})
        if bad and not self.tripped:
            self.tripped = bad
            self._kill(self._last_tree or roots)
            self._log({"t": round(self.clock(), 1), "event": "TRIPPED", "violations": bad})
        return bad

    def positive_control(self):
        """演練開始前必做：本行程自己開一條本機連線，取樣器必須看得到它；看不到＝監看器是瞎的（這台機器的 Get-NetTCPConnection 就是），
        不能拿來證明「0 連線」⇒ DrillAbort。⇒ True。"""
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        cli = socket.create_connection(srv.getsockname())
        conn, _ = srv.accept()
        try:
            snap = self.sampler([os.getpid()])
        finally:
            cli.close()
            conn.close()
            srv.close()
        if not any(is_loopback_addr(c.get("remote")) for c in (snap.get("conns") or [])):
            raise DrillAbort("連線監看器的正對照沒過：看不到本行程剛開的一條本機連線，這個監看器是瞎的，不能用來證明沒有連到正式機")
        self._control_done = True
        return True

    @property
    def control_done(self):
        return self._control_done

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive() and not self._stop)

    def start(self):
        import threading

        def loop():
            while not self._stop and not self.tripped and not self.unproven:
                self.tick()
                end = self.clock() + self.interval
                while not self._stop and self.clock() < end:
                    time.sleep(0.2)
        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop = True
        if self._thread:
            self._thread.join(timeout=15)

    def check_clean(self):
        """演練各步驟之間呼叫：被中止（連線違規、或取樣連續失敗＝未證明）就丟 DrillAbort。"""
        if self.tripped:
            raise DrillAbort("監看器發現演練程序連往非本機位址，已殺掉程序並中止：%s" % json.dumps(self.tripped, ensure_ascii=False))
        if self.unproven:
            raise DrillAbort("監看器無法證明沒有連到正式機：%s" % self.unproven)

    @property
    def proven(self):
        """整段演練「有證明」＝至少取樣過、從沒失敗、沒中止。"""
        return self.ticks > 0 and self.errors == 0 and not self.tripped and not self.unproven

    def summary(self):
        s = {"ticks": self.ticks, "sample_errors": self.errors, "max_connections_seen": self.max_conns,
             "prod_connections": self.prod_hits, "non_loopback_connections": self.other_hits, "processes_seen": len(self.tree_seen),
             "interval_seconds": self.interval, "tripped": bool(self.tripped), "proven": self.proven,
             "unproven_reason": self.unproven, "log": str(self.log_path)}
        limits = ("範圍：只有 TCP 連線；UDP（這台機器的 netstat 看不到 UDP 對端）與 ICMP 看不到。取樣有間隔，極短暫連線可能漏看，"
                  "主要保證是靜態掃描與位址只准本機。")
        if self.proven:
            s["statement"] = "整段演練對正式機 %d 連線（非本機連線 %d 次；共取樣 %d 次，每 %g 秒一次）。%s" % (
                self.prod_hits, self.other_hits, self.ticks, self.interval, limits)
        else:
            why = self.unproven or ("取樣失敗 %d 次" % self.errors if self.errors else "沒有取樣過")
            seen = ("已取樣到對正式機的連線 %d 次" % self.prod_hits) if self.prod_hits else "已取樣的結果沒看到對正式機的連線"
            s["statement"] = "未證明：%s（共取樣 %d 次，失敗 %d 次）；%s，但失敗的空檔無法確認。%s" % (why, self.ticks, self.errors, seen, limits)
        return s


class DrillGuard:
    """呼叫順序寫死（PM 2026-11-14）：`check`（require_ok）→ `scan`（require_static_ok）→ `control`（監看器正對照）→ `start`（啟動監看）。
    之後每次啟動／驅動任何演練程序之前呼叫 `ready(動作)`：少了任一步、監看器沒在跑、已中止、或掃過的三個要執行的腳本之後被改動 ⇒ DrillAbort（不開跑）。"""

    GUARDED = (r"backend\tools\apply_update.ps1", r"backend\tools\rollback_update.ps1", r"backend\autostart.bat")
    ORDER = ("check", "scan", "control", "start")

    def __init__(self, root, monitor, probes=None, erp_port=ERP_PORT, dash_port=DASH_PORT, environ=None, base=None):
        self.base = Path(base) if base else None          # 本次演練目錄（含時間戳）；殺程序白名單用它比對命令列
        self.root, self.monitor, self.probes = Path(root), monitor, probes
        self.erp_port, self.dash_port, self.environ = erp_port, dash_port, environ
        self.done = []
        self.rows = []
        self.scan_result = None
        self._fp = None
        self._children = []
        self.records = []                         # [(pid, 建立時間 ticks)]：啟動時記下，殺之前用來確認「還是同一個程序」
        self.start_ticks = now_ticks()

    def _need(self, step):
        i = self.ORDER.index(step)
        missing = [s for s in self.ORDER[:i] if s not in self.done]
        if missing:
            raise DrillAbort("演練步驟順序錯誤：做「%s」之前必須先完成 %s（沒做就不開跑）" % (step, "、".join(missing)))

    def _fingerprint(self):
        import hashlib
        h = hashlib.sha256()
        for rel in self.GUARDED:
            p = self.root / rel
            h.update(rel.encode("utf-8") + b"\0")
            h.update(p.read_bytes() if p.is_file() else b"<missing>")
        return h.hexdigest()

    def check(self):
        self.rows = require_ok(self.root, self.probes, erp_port=self.erp_port, dash_port=self.dash_port, environ=self.environ)
        self.done = ["check"]
        return self.rows

    def scan(self):
        self._need("scan")
        self.scan_result = require_static_ok(self.root, erp_port=self.erp_port, dash_port=self.dash_port)
        cf, allowed = code_literal_findings(self.root)
        if cf:
            raise DrillAbort("演練目錄程式碼含未列名的正式機位址，不啟動演練：" + chr(10) + chr(10).join("  ✗ %s：%s" % f for f in cf))
        self.scan_result["code_literals_allowed"] = allowed
        self._fp = self._fingerprint()
        self.done = ["check", "scan"]
        return self.scan_result

    def control(self):
        self._need("control")
        self.monitor.positive_control()
        self.done = ["check", "scan", "control"]
        return True

    def start(self):
        self._need("start")
        if not self.monitor.control_done:
            raise DrillAbort("監看器沒做過正對照，不啟動")
        me_created = process_created(os.getpid())
        if not me_created:
            raise DrillAbort("查不到編排器自己的建立時間，殺程序白名單會是空的 ⇒ 不啟動監看與演練")
        self.records.append((os.getpid(), me_created))
        self.monitor.start()
        self.done = list(self.ORDER)
        return self

    # ── 所有子行程都走這裡（a1_drill.py 自己不碰 subprocess；有測試 grep 釘住）─────────────────────
    def _env(self, extra=None, allow_hosts=()):
        env = sanitized_env(self.erp_port, self.dash_port, environ=self.environ, extra=extra, allow_hosts=allow_hosts)
        return env

    def run_tool(self, argv, cwd=None, timeout=600, extra_env=None):
        """建置階段的工具（git、robocopy、PowerShell 查詢、`--check-audit`）：乾淨環境、等它結束 ⇒ (rc, 輸出)。不啟動演練服務。"""
        r = subprocess.run([str(a) for a in argv], cwd=str(cwd) if cwd else None, env=self._env(extra_env), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    def run_tool_bytes(self, argv, cwd=None, timeout=600):
        r = subprocess.run([str(a) for a in argv], cwd=str(cwd) if cwd else None, env=self._env(), capture_output=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode, r.stdout, r.stderr

    def launch(self, argv, cwd, what, extra_env=None, allow_hosts=(), detached=False, wait=False, timeout=None):
        """啟動或驅動任何演練程序（ERP、儀表板、套用腳本、瀏覽器）的唯一入口：先 `ready()`（防線全過、監看器在跑、沒中止、腳本沒被改），
        再用 `sanitized_env()` 乾淨環境起程序。`wait=True` ⇒ (rc, 輸出)；否則回 Popen（pid 記進 `self.pids()`，給監看器當根）。"""
        self.ready(what)
        env = self._env(extra_env, allow_hosts)
        flags = (0x00000008 | 0x00000200) if detached else getattr(subprocess, "CREATE_NO_WINDOW", 0)
        kw = dict(cwd=str(cwd), env=env, creationflags=flags)
        if wait:
            pr = subprocess.Popen([str(a) for a in argv], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)
            self._children.append(pr)
            self._record(pr)
            try:
                out, _ = pr.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                subprocess.run(["taskkill", "/PID", str(pr.pid), "/T", "/F"], capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                out, _ = pr.communicate()
                return -999, (out or b"").decode("utf-8", "replace") + "\n（逾時，已終止）"
            return pr.returncode, (out or b"").decode("utf-8", "replace")
        pr = subprocess.Popen([str(a) for a in argv], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
        self._children.append(pr)
        self._record(pr)
        return pr

    def _record(self, pr):
        """記下剛啟動的程序（pid＋建立時間）。查不到建立時間 ⇒ 用手上的 Popen 把它殺掉（我們握有 handle，pid 不會錯）並中止：沒記錄就進不了殺程序白名單。"""
        created = process_created(pr.pid)
        if not created and pr.poll() is None:
            try:
                pr.kill()
            except OSError:
                pass
            raise DrillAbort("查不到剛啟動的程序（pid %d）的建立時間，無法放進殺程序白名單，已終止它並中止" % pr.pid)
        if created:
            self.records.append((pr.pid, created))

    def owned_pids(self):
        """殺程序的白名單（給監看器 `owned_fn`）：記錄過且建立時間相符的程序＋後代＋命令列含演練目錄的白名單程序；查詢失敗 ⇒ 丟例外。"""
        return [o["id"] for o in owned_processes(self.records, self.base or self.root, self.start_ticks)]

    def pids(self):
        """監看器的根程序：編排器自己＋啟動過且還活著的子行程。"""
        return [os.getpid()] + [c.pid for c in self._children if c.poll() is None]

    def ready(self, what="啟動演練程序"):
        """每個會啟動或驅動演練程序的動作之前呼叫。"""
        if self.done != list(self.ORDER):
            raise DrillAbort("不可以%s：防線步驟沒做完（已做：%s；要求順序：%s）" % (what, "、".join(self.done) or "無", "→".join(self.ORDER)))
        if not self.monitor.running and not (self.monitor.tripped or self.monitor.unproven):
            raise DrillAbort("不可以%s：連線監看器沒有在跑" % what)
        self.monitor.check_clean()
        if self._fingerprint() != self._fp:
            raise DrillAbort("不可以%s：靜態掃描之後，套用／回復腳本或 autostart.bat 被改動了，必須重新掃描" % what)
        return True


def stop_drill_processes(base, records, start_ticks, log=None, killer=None):
    """收尾：只殺 `owned_processes` 給的白名單（編排器啟動並記錄、建立時間相符的程序＋後代＋命令列含本次演練目錄的白名單程序）。
    殺之前逐一記 pid／名稱／建立時間。查詢失敗 ⇒ 丟例外、不殺任何程序。⇒ 被殺的 pid。"""
    owned = owned_processes(records, base, start_ticks)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    kill = sorted((o for o in owned if killable(o["id"], o["name"])), key=lambda o: -o["id"])
    for o in kill:
        if log:
            log("收尾殺程序 pid=%d name=%s created_ticks=%d" % (o["id"], o["name"], o["created"]))
        if killer:
            killer(o["id"])
        else:
            subprocess.run(["taskkill", "/PID", str(o["id"]), "/F"], capture_output=True, creationflags=flags)
    if log and not kill:
        log("收尾：沒有需要殺的演練程序")
    return [o["id"] for o in kill]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=DRILL_BASE + "\\preflight-check", help="演練目錄（第 1 道只檢查路徑，不建立）")
    ap.add_argument("--scan", help="第 2 道：掃這個演練目錄的設定與腳本副本")
    ap.add_argument("--erp-port", type=int, default=ERP_PORT)
    a = ap.parse_args(argv)
    if a.scan:
        res = static_scan(a.scan, erp_port=a.erp_port)
        for rel, why in res["findings"]:
            print("  ✗ %s：%s" % (rel, why))
        print("\n掃了 %d 個設定檔：%s" % (res["files"], "乾淨" if not res["findings"] else "%d 項問題 ⇒ 不可以演練" % len(res["findings"])))
        return 0 if not res["findings"] else 1
    rows = check(a.root)
    print(format_rows(rows))
    print("  ℹ " + route_note())
    bad = [r for r in rows if not r[1]]
    print("\n結果：%s" % ("全部通過，可以建演練（之後還要過靜態掃描，演練中有連線監看）" if not bad else "%d 項未通過 ⇒ 不可以演練" % len(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
