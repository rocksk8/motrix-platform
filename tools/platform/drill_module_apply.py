"""B55 S6：單模組更新演練（設計 docs/platform/MODULE-UPDATE-DELIVERY.md §7）。正式機條件：排程開、GEO 開、有待辦。

用法：
  python tools/platform/drill_module_apply.py --ps1 <apply_module_update.ps1> [--port 6755] [--commit HEAD] [--keep]
                                              [--only A,B,C] [--skip-ship-tests]

做什麼（全部在 %TEMP%\\motrix-drill-b55\\<時間>\\ 底下；路徑不含 V9.0）：
  1. 安裝：git archive <commit> ⇒ install\\；product_select 選配 full（寫 modules.lock.json）；.deployed_commit.json；
     .deployed_files.json（apply_plan 基準）；.no_email_send／.no_cloud_archive；演練用 autostart.bat
     （埠＝--port、只綁 127.0.0.1、MOTRIX_GEO=1、**不**設 MOTRIX_DISABLE_SCHEDULERS、MOTRIX_TENDER_RADAR 關：不連政府網站）。
     第一次啟動建新庫；再塞 3 筆待定位的標案（背景定位會真的問 Nominatim，每秒 1 次）。
  2. 套用腳本：把 --ps1 複製成 install\\backend\\tools\\apply_module_update.ps1，**只改寫 `$ProdRoot`、`$Port` 兩行**
     （改寫前後逐行比對，多一行就拒絕；稽核 D DB-S2：正式機的腳本沒有任何繞過分支）。
  3. 演練分支（git worktree，演練完刪）：
     A 成功：tender_radar 頁面文案＋修正版號 ⇒ ship（含第②級測試）⇒ 簽章發布到演練交付資料夾 ⇒ stage ⇒ verify ⇒ ps1
     B 自動回滾：模組 __init__ 在「uvicorn 已載入」時丟例外 ⇒ 疊加樹乾跑（沒有 uvicorn）載得起來、真的啟動時載入失敗
               ⇒ 健檢判模組沒載入 ⇒ 自動回滾（期待 module_unhealthy_rolled_back、restored、雜湊回到套用前）
     D 手動回滾（B55F-M1）：同 A 的改動 ⇒ 套用成功 ⇒ `-Rollback -ModuleKey tender_radar -Yes`（預設只回程式、資料庫保留）
               ⇒ 期待 module_rollback_ok、雜湊回到套用前、舊版已載入、服務 up
     C 乾跑擋下：多一支回「未完成原因」的 migration ⇒ migration_dryrun_failed、正式機（演練安裝）沒被碰
  4. 報告：stdout 最後一行 JSON；--keep 以外全部清掉（服務一律停掉）。
⚠ 本機若有排程工作「MOTRIX ERP Server Autostart」⇒ 拒絕（ps1 的 Start-InstallService 會去啟動它，而那是別的安裝）。
"""
import argparse
import io
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "backend" / "tools"))

KEY = "tender_radar"
TASK_NAME = "MOTRIX ERP Server Autostart"
PROD_ROOT_LINE = re.compile(r'^\$ProdRoot = ".*"\s*$', re.M)
PORT_LINE = re.compile(r'^\$Port = \d+\s*$', re.M)
RESULT_RE = re.compile(r"^::RESULT:: v=2 status=(\S+) rolled_back=(\S+) service=(\S+) exit=(-?\d+)\s*$", re.M)


class DrillError(Exception):
    pass


def _git(*args, repo=REPO, binary=False, check=True):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if check and r.returncode != 0:
        raise DrillError("git %s 失敗：%s" % (" ".join(args), r.stderr.decode("utf-8", "replace").strip()))
    return r.stdout if binary else r.stdout.decode("utf-8").strip()


def _rmtree(p):
    def _clear(func, path, _exc):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    if Path(p).exists():
        shutil.rmtree(str(p), onerror=_clear)


# ── 安全檢查 ────────────────────────────────────────────────────────────────

def refuse_if_task_exists():
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                        "if (Get-ScheduledTask -TaskName '%s' -ErrorAction SilentlyContinue) { 'EXISTS' }" % TASK_NAME],
                       capture_output=True, text=True)
    if "EXISTS" in r.stdout:
        raise DrillError("本機有排程工作「%s」：ps1 的 Start-InstallService 會啟動它（別的安裝）⇒ 不演練" % TASK_NAME)


# ── 2. 套用腳本的演練副本 ──────────────────────────────────────────────────────

def rewrite_ps1(text, root, port):
    """只改寫 `$ProdRoot`、`$Port` 兩行 ⇒ (新內容, 改了哪幾行)。多改或少改 ⇒ DrillError（DB-S2）。"""
    if len(PROD_ROOT_LINE.findall(text)) != 1 or len(PORT_LINE.findall(text)) != 1:
        raise DrillError("ps1 裡 `$ProdRoot = \"…\"`／`$Port = …` 不是各恰好一行 ⇒ 不改寫（不猜）")
    root_line = '$ProdRoot = "%s"' % str(root).replace("$", "`$")
    new = PROD_ROOT_LINE.sub(lambda _m: root_line, text)              # 函式：路徑裡的反斜線不可以被當成跳脫
    new = PORT_LINE.sub(lambda _m: "$Port = %d" % int(port), new)
    a, b = text.splitlines(), new.splitlines()
    changed = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    if len(a) != len(b) or len(changed) != 2 or not all(PROD_ROOT_LINE.match(a[i]) or PORT_LINE.match(a[i]) for i in changed):
        raise DrillError("演練副本相對正式腳本的差異不只 $ProdRoot／$Port 兩行（%s）⇒ 拒絕" % changed)
    return new, changed


def install_ps1(src, root, port):
    raw = Path(src).read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    new, changed = rewrite_ps1(text, root, port)
    dst = Path(root) / "backend" / "tools" / "apply_module_update.ps1"
    dst.write_bytes((b"\xef\xbb\xbf" if bom else b"") + new.encode("utf-8"))   # PS 5.1：含中文的 .ps1 要有 BOM
    ver = Path(src).with_name("apply_module_update.version.json")
    if ver.is_file():
        shutil.copy2(ver, dst.with_name(ver.name))
    return dst, changed


# ── 1. 演練安裝 ───────────────────────────────────────────────────────────────

AUTOSTART = r"""@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set MOTRIX_GEO=1
set MOTRIX_CREATE_NEW_DB=1
cd /d "{backend}"
if not exist "{backend}\logs" mkdir "{backend}\logs"
:loop
echo [%date% %time%] MOTRIX ERP starting... >> "{backend}\logs\server.log"
"{python}" -m uvicorn main:app --port {port} --host 127.0.0.1 --log-level info >> "{backend}\logs\server.log" 2>&1
echo [%date% %time%] MOTRIX ERP stopped (exit code %errorlevel%). restart in 5s... >> "{backend}\logs\server.log"
timeout /t 5 /nobreak >nul
goto loop
"""


def make_install(commit, root, port, python=sys.executable):
    root = Path(root)
    root.mkdir(parents=True)
    tar = _git("archive", "--format=tar", commit, binary=True)
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(root)
    import product_select as PS
    PS.apply(root, PS.load_product("full"))
    full = _git("rev-parse", commit)
    (root / "backend" / ".deployed_commit.json").write_text(json.dumps({"commit": full, "built_at": time.strftime("%Y-%m-%d %H:%M:%S")}),
                                                            encoding="utf-8")
    sys.path.insert(0, str(root / "backend" / "tools"))
    import apply_plan as AP
    u = AP.load_classifier(str(root))
    AP.write_baseline(str(root), {"commit": full, "package_files": AP.package_files(str(root), u)})
    for marker in (".no_email_send", ".no_cloud_archive"):
        (root / marker).write_text("drill\n", encoding="utf-8")
    (root / "backend" / "autostart.bat").write_text(
        AUTOSTART.format(backend=root / "backend", python=python, port=port), encoding="utf-8")
    return root


def ping(port, timeout=3):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/ping" % port, timeout=timeout) as r:
            return r.status == 200
    except Exception:                                       # noqa: BLE001
        return False


def start(root, port, wait=90):
    """同 ps1 的 Start-InstallService 後備路徑：cmd /c autostart.bat（沒有排程工作）。"""
    flags = 0x00000008 | 0x00000200                          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "cmd.exe"), "/c",
                      str(Path(root) / "backend" / "autostart.bat")], cwd=str(Path(root) / "backend"),
                     creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t0 = time.time()
    while time.time() - t0 < wait:
        if ping(port):
            return time.time() - t0
        time.sleep(2)
    raise DrillError("演練服務 %d 秒內沒起來（看 %s）" % (wait, Path(root) / "backend" / "logs" / "server.log"))


def stop(root, port):
    """停掉這個演練安裝的迴圈與服務（命令列含它的 autostart.bat／聽它的埠）。"""
    bat = str(Path(root) / "backend" / "autostart.bat").lower()
    ps = ("$bat = '%s'; $port = %d; $t = @(); "
          "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'cmd.exe' -and $_.CommandLine -and $_.CommandLine.ToLower().Contains($bat) } | ForEach-Object { $t += $_.ProcessId }; "
          "Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object { $t += $_.OwningProcess }; "
          "$t | Sort-Object -Unique | ForEach-Object { taskkill /PID $_ /T /F | Out-Null }; 'STOPPED ' + ($t -join ',')") % (bat.replace("'", "''"), port)
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    return r.stdout.strip()


def _ubn_ok(s):
    """統一編號檢查碼（同 helpers.company_setup.ubn_valid；演練工具不匯入安裝目錄的程式）。"""
    w = (1, 2, 1, 2, 1, 2, 4, 1)
    total = sum(int(d) * k // 10 + int(d) * k % 10 for d, k in zip(s, w))
    return total % 5 == 0 or (s[6] == "7" and (total + 1) % 5 == 0)


def _api(port, path, data=None, token=None, method=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=body, headers=headers,
                                 method=method or ("POST" if body is not None else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]


def setup_company(root, port):
    """本公司資料設定閘門（E4，COMPANY-SETUP-GATE §3.2）走**正式路徑**：新庫的最高管理員（臨時密碼）登入 → 改密碼 →
    設定頁存檔並「確認本公司資料」（PUT /api/settings/company-profile，confirmIdentity=true）→ status＝configured。
    公司資料是演練用的虛構資料（不命中開發者指紋 ⇒ 不需要開發者簽章檔）。回 status 回應。"""
    cred = (Path(root) / "backend" / ".initial_admin_credentials.txt").read_text(encoding="utf-8")
    user = re.search(r"帳號:\s*(\S+)", cred).group(1)
    pw = re.search(r"臨時密碼:\s*(\S+)", cred).group(1)
    s, b = _api(port, "/api/auth/login", {"username": user, "password": pw})
    if s != 200:
        raise DrillError("演練管理員登入失敗：%s %s" % (s, b))
    new_pw = "Drill-%d-Pass!9" % port
    s, b2 = _api(port, "/api/auth/change-password", {"current_password": pw, "new_password": new_pw},
                 token=b["token"], method="PATCH")
    if s != 200:
        raise DrillError("改密碼失敗：%s %s" % (s, b2))
    s, b = _api(port, "/api/auth/login", {"username": user, "password": new_pw})
    token = b["token"] if s == 200 else None
    tax = next("%08d" % n for n in range(10000000, 10001000) if _ubn_ok("%08d" % n))
    s, b3 = _api(port, "/api/settings/company-profile",
                 {"name": "演練測試股份有限公司", "tax_id": tax, "contact_info": "Tel: 04-2345-6789",
                  "confirmIdentity": True}, token=token, method="PUT")
    if s != 200:
        raise DrillError("本公司資料存檔／確認失敗：%s %s" % (s, b3))
    s, st = _api(port, "/api/settings/company-setup/status", token=token)
    if s != 200 or not (isinstance(st, dict) and st.get("configured")):
        raise DrillError("確認後 status 不是 configured：%s %s" % (s, st))
    return st


def seed_backlog(root, n=3):
    """待定位的標案（機關名稱）：背景定位第一輪就會去查（GEO 開、排程開＝正式機條件）。"""
    db = Path(root) / "backend" / "motrix_erp.db"
    conn = sqlite3.connect(str(db))
    try:
        for i in range(n):
            conn.execute("INSERT INTO tenders (case_no, name, org, location, fetched_at) VALUES (?,?,?,?,?)",
                         ("DRILL-%03d" % i, "演練標案 %d" % i, ["臺中市政府", "臺北市政府", "國立臺灣大學"][i % 3], None,
                          time.strftime("%Y-%m-%dT%H:%M:%S")))
        conn.commit()
    finally:
        conn.close()


# ── 3. 演練用的模組改動 ──────────────────────────────────────────────────────

def _bump(ver):
    parts = [int(x) for x in re.findall(r"\d+", ver)] + [0, 0, 0]
    return "%d.%d.%d" % (parts[0], parts[1], parts[2] + 1)


def _vkey(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v or "0")))


def installed_version(root, key=KEY):
    """演練安裝目前的模組版本（modules.lock.json）；讀不到 ⇒ None。"""
    try:
        e = (json.loads((Path(root) / "backend" / "modules.lock.json").read_text(encoding="utf-8")).get("modules") or {}).get(key)
    except (OSError, ValueError):
        return None
    return e.get("version") if isinstance(e, dict) else e


def make_variant(worktree, variant, at_least=None):
    """at_least：新版本號至少要高於它（同一個演練安裝連續跑多場時，前一場可能已經把版本升上去）。"""
    """在演練 worktree 裡改 tender_radar ⇒ 回新版本號。"""
    mdir = Path(worktree) / "backend" / "modules" / KEY
    mj = mdir / "module.json"
    man = json.loads(mj.read_text(encoding="utf-8"))
    base_ver = man["version"]
    if at_least and _vkey(at_least) > _vkey(base_ver):
        base_ver = at_least
    new_ver = _bump(base_ver)
    text = mj.read_text(encoding="utf-8").replace('"version": "%s"' % man["version"], '"version": "%s"' % new_ver, 1)
    mj.write_text(text, encoding="utf-8")
    cl = mdir / "CHANGELOG.md"
    body = cl.read_text(encoding="utf-8")
    first = body.index("\n## ")
    cl.write_text(body[:first] + "\n## %s — 演練（B55 S6 %s，不出貨）\n- 演練用改動\n" % (new_ver, variant) + body[first:],
                  encoding="utf-8")
    if variant in ("A", "D"):
        import ship_tier as ST                              # 宣告頁面的目錄由 core.paths 取得（test_page_paths_centralized）
        page = Path(worktree) / ST.PAGES_REL / man["pages"][0]["path"]
        page.write_text(page.read_text(encoding="utf-8") + "\n<!-- B55 drill %s -->\n" % variant, encoding="utf-8")
    elif variant == "B":
        init = mdir / "__init__.py"
        init.write_text("import sys as _drill_sys\nif 'uvicorn' in _drill_sys.modules:\n"
                        "    raise RuntimeError('B55 演練 B：真的啟動時載入失敗（乾跑沒有 uvicorn，載得起來）')\n"
                        + init.read_text(encoding="utf-8"), encoding="utf-8")
    elif variant == "C":
        init = mdir / "__init__.py"
        src = init.read_text(encoding="utf-8")
        anchor = 'MODULE = ModuleSpec(\n    key="tender_radar",\n'
        if "migrations=" in src or src.count(anchor) != 1:
            raise DrillError("tender_radar 的 ModuleSpec 形狀變了（已有 migrations 或找不到錨點）⇒ 演練 C 要改寫法")
        src = src.replace(anchor, anchor + "    migrations=[(1, _drill_not_now)],\n", 1)
        src = src.replace("MODULE = ModuleSpec(", "def _drill_not_now(conn):\n    return 'B55 演練 C：這次做不了'\n\n\nMODULE = ModuleSpec(", 1)
        init.write_text(src, encoding="utf-8")
    return new_ver


# ── 4. 跑 ps1 ────────────────────────────────────────────────────────────────

def run_ps1(root, pkg, timeout=20 * 60, args=None):
    """args：取代預設的 `-PackagePath <pkg> -Yes`（例：回滾模式 `-Rollback -ModuleKey <key> -Yes`）。"""
    ps1 = Path(root) / "backend" / "tools" / "apply_module_update.ps1"
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")    # ps1 的 `python` 用專案 venv
    t0 = time.time()
    r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1),
                        *(args if args is not None else ["-PackagePath", str(pkg), "-Yes"])],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, env=env)
    out = r.stdout + r.stderr
    m = RESULT_RE.findall(out)
    res = dict(zip(("status", "rolled_back", "service", "exit"), m[-1])) if m else None
    logs = Path(root) / "backend" / "logs"
    files = sorted(logs.glob("apply_module_update_*.result.json")) if logs.is_dir() else []
    rj = json.loads(files[-1].read_text(encoding="utf-8-sig")) if files else None
    return {"returncode": r.returncode, "seconds": round(time.time() - t0, 1), "result": res, "result_json": rj,
            "tail": out[-3000:]}


def deliver(pkg, base, root, tools_dir, tests_skipped=False):
    """演練 A 的交付段：演練金鑰簽章發布 ⇒ stage ⇒ verify_staged（公鑰用演練那一把）⇒ 回 (staging 的 payload, 驗證結果)。"""
    import delivery as D
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    k = Ed25519PrivateKey.generate()
    priv = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    if tests_skipped:                                    # 只在 --skip-ship-tests 重演練時：發布端要求第②級全綠，照實標註
        lp = Path(pkg) / "module-update.lock.json"
        lock = json.loads(lp.read_text(encoding="utf-8"))
        lock["tests"] = {"passed": 1, "failed": 0, "errors": 0, "line": "演練：--skip-ship-tests（未跑第②級）"}
        lp.write_text(json.dumps(lock, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    droot = Path(base) / "交付"
    droot.mkdir()
    name = D.publish(str(pkg), str(droot), priv, tools_dir=str(tools_dir))
    staging = Path(base) / "staging"
    staging.mkdir()
    staged = D.stage(str(droot), name, str(staging))
    verify = D.verify_staged(staged, str(root), pubkey_pem=pub)
    return Path(staged) / D.PAYLOAD, {k2: verify.get(k2) for k2 in ("ok", "problems", "notes", "kind")}


def tree_hashes(root):
    import module_update as MU
    return MU._tree_hashes(root, KEY)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ps1", required=True)
    ap.add_argument("--port", type=int, default=6755)
    ap.add_argument("--commit", default="HEAD")
    ap.add_argument("--only", default="A,B,C")
    ap.add_argument("--skip-ship-tests", action="store_true", help="A 也不跑第②級測試（只在重演練時用；報告會註明）")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args(argv)
    refuse_if_task_exists()
    base = Path(tempfile.gettempdir()) / "motrix-drill-b55" / time.strftime("%Y%m%d_%H%M%S")
    if "V9.0" in str(base):
        raise DrillError("演練路徑不可以含 V9.0")
    root = base / "install"
    report = {"base": str(base), "commit": _git("rev-parse", a.commit), "drills": {}}
    wts = []
    try:
        make_install(a.commit, root, a.port)
        dst, changed = install_ps1(a.ps1, root, a.port)
        report["ps1_rewrite_lines"] = changed
        report["first_start_s"] = round(start(root, a.port), 1)
        if (root / "backend" / "helpers" / "company_setup.py").is_file():   # 含 E4 的版本：先照正式路徑設定本公司資料
            report["company_setup"] = setup_company(root, a.port)
        seed_backlog(root)
        stop(root, a.port)
        report["restart_s"] = round(start(root, a.port), 1)       # 帶待辦、排程開、GEO 開的正式機條件
        import module_update as MU
        MU._license_check = None
        for v in a.only.split(","):
            wt = base / ("wt_" + v)
            _git("worktree", "add", "--detach", str(wt), report["commit"])
            wts.append(wt)
            ver = make_variant(wt, v, installed_version(root))   # 前一場成功後安裝已是新版 ⇒ 這一場要再往上升
            _git("-c", "user.name=drill", "-c", "user.email=drill@example.invalid", "commit", "-q", "-a", "-m",
                 "B55 drill %s（不推）" % v, repo=wt)
            x = _git("rev-parse", "HEAD", repo=wt)
            before = tree_hashes(root)
            pkg = MU.ship(KEY, base / ("pkg_" + v), report["commit"], x,
                          run_tests=(v == "A" and not a.skip_ship_tests), repo=wt)
            verify = None
            if v == "A":
                # 走完整條交付：簽章發布（演練金鑰）⇒ stage ⇒ verify（已安裝 module_update 的 preflight）⇒ ps1 套 staging 的 payload
                pkg, verify = deliver(pkg, base, root, Path(a.ps1).parent, a.skip_ship_tests)
                if not verify["ok"]:
                    report["drills"][v] = {"verify": verify}
                    continue
            rec = run_ps1(root, pkg)
            rec["verify"] = verify
            after = tree_hashes(root)
            rec.update(version=ver, pkg=str(pkg), unchanged=(after == before), healthy_after=ping(a.port))
            if v == "D":
                # B55F-M1：手動回滾模式（預設只回模組程式、資料庫保留）⇒ 回到套用前
                rb = run_ps1(root, None, args=["-Rollback", "-ModuleKey", KEY, "-Yes"])
                rec["rollback"] = {k: rb.get(k) for k in ("returncode", "seconds", "result", "result_json", "tail")}
                rec["rollback"].update(back_to_before=(tree_hashes(root) == before),
                                       installed_after=installed_version(root), healthy_after=ping(a.port))
            report["drills"][v] = rec
    finally:
        report["stop"] = stop(root, a.port)
        for wt in wts:
            _git("worktree", "remove", "--force", str(wt), check=False)
        # 先把報告寫到演練目錄**外**（刪除失敗會刪掉一部分證據：〈遞迴刪除失敗≠沒刪〉），再清
        out = base.parent / (base.name + ".report.json")
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True))
        if not a.keep:
            report["cleanup"] = cleanup(base)
    return 0


def cleanup(base, tries=10):
    """服務剛停時 server.log 可能還被正在結束的行程占著 ⇒ 等一下再試；最後還刪不掉就回報、不丟例外。"""
    for _i in range(tries):
        try:
            _rmtree(base)
            return "removed"
        except OSError:
            time.sleep(3)
    return "left: %s" % base


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
