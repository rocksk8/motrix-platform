# -*- coding: utf-8 -*-
"""T87 A1 M1 演練編排器（drill plan：D:\\Claude-pm\\t87-design\\A1-M1-drill-plan.md）。

在 `D:\\Claude-pm\\a1-drill\\<時間戳>\\` 建一份「備份式」安裝副本（基底＝本分支頭＝T86 凍結頭＋A1），再做一個只存在演練 worktree 的假 T87 包，
用 Playwright 驅動儀表板「6. 套用更新」，從按同意到完成零人工介入；故意放壞的包都要在對應步驟停下並留白話報告。
**基底說明（報告必寫）：這等於「T87 用步驟檔把 A1 裝上正式機，之後 T88 才是第一次 A1 半自動套用」——演練模擬的就是 T88 那一步。**

矩陣：G（完整成功）、B1（簽章錯）、B2a（包帶 pyc）、B2b（準備後暫存包被塞檔）、B3（db.py 版本與預期不符）、B4（遷移失敗，預演擋下）、
B5（事後驗證不過、不自動回滾，並在演練機真的執行回復指令）、B6（預演後正式庫結構變動）、B7（系統位址不是本機）。

**演練絕不碰正式機**（PM 裁示 c；不改防火牆，改成可證明）：
  ① 呼叫順序寫死在 `a1_drill_preflight.DrillGuard`：check → scan → control（監看器正對照）→ start（監看）；任何啟動／驅動演練程序的動作都先 `guard.ready()`。
  ② 本檔**不直接**起任何子行程（測試 grep 釘住）：所有子行程只走 `guard.launch`（演練程序）與 `guard.run_tool`（建置工具），都用乾淨環境（白名單變數、
     MOTRIX_DELIVERY_ERP_URL 只指 127.0.0.1、pip 離線）。有測試 grep 釘住。
     **唯一例外**：Playwright 的 node driver 只能繼承本行程環境，故驅動前先清空並重設環境（`os.environ.clear()`＋`--no-proxy-server`）；它是本行程的子行程，
     仍在監看器的樹內（監看器看得到、也只會殺白名單內的程序）。
  ③ 演練期間 `ConnectionMonitor` 每 2 秒查演練程序的 TCP 連線，一有非本機連線就殺程序、中止；取樣連續失敗兩次也中止並標「未證明」。
     殺程序走嚴格白名單（只殺本編排器自己起的「pid＋建立時間」紀錄與其後代，加窄範圍孤兒；pid<1000、系統／shell 程序名一律不殺；查詢失敗＝不殺）。
  ④ 儀表板的 PROD_HOST／PROD_BASE_URL 在演練副本改成本機死路（出貨包本就 export-ignore 此檔，則記為「不存在」）；`code_literal_findings` 對任何未列名單的
     程式碼正式機位址阻擋。
報告寫明「整段演練對正式機 N 連線」（有證明才印；否則寫「未證明」）。

用法：
  python tools/platform/a1_drill.py --dry-build           # 只建安裝副本、假 T87 包、做靜態掃描；不起服務、不開瀏覽器
  python tools/platform/a1_drill.py [--only G,B1,...]     # 完整演練（需 40–60 分鐘安靜窗口，先跟 hichan-4 排）
結束碼：0＝矩陣全部符合預期且監看器有證明；1＝有情境不符；2＝防線沒過或中止（沒開跑／中途中止）。
"""
import argparse
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import tarfile
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "backend" / "tools"))

import a1_drill_preflight as PF  # noqa: E402
import drill_module_apply as DMA  # noqa: E402

ERP_PORT, DASH_PORT = PF.ERP_PORT, PF.DASH_PORT
BASE_ROOT = PF.DRILL_BASE
REPORT_ROOT = r"D:\Claude-pm\a1-drill-reports"
SCENARIOS = ("G", "B1", "B2a", "B2b", "B3", "B4", "B5", "B6", "B7")
EXAMPLE_HOST = "example.invalid"                        # RFC 6761 保留網域：永遠解析不到；B7 專用
MIGRATION_NAME = "0006_a1_drill_probe"
PROBE_TABLE = "a1_drill_probe"

BASE_STATEMENT = ("演練的「T86」基底＝`feat/t87-a1-m1-h7` 頭（＝T86 凍結頭＋A1）。這等於「T87 用步驟檔把 A1 裝上正式機，"
                  "之後 T88 才是第一次 A1 半自動套用」——本演練模擬的就是 T88 那一步（假 T87 包＝T88 的替身）。")
DEVIATIONS = [
    "演練資料庫是**全新資料庫**（基底程式啟動時建立、經正式路徑設定本公司資料），不是正式資料的備份副本：不把任何真實資料放進演練目錄。"
    "代價：預演／遷移的耗時與資料量只當量級，不能當正式機預估。",
    "簽章公鑰換成演練金鑰（安裝副本與假 T87 包的 delivery.py 同換；驗不到正式簽章金鑰本身）。",
    "套用與回復腳本（apply_update.ps1、rollback_update.ps1）與 autostart.bat 是演練副本：只改寫 `$ProdRoot`／`$Port` 兩行與演練用的啟動設定；"
    "假 T87 包裡的這三個檔也是同樣的演練副本（否則套用後安裝目錄會變回指向正式機路徑）。",
    "Email／LINE／雲端存檔／排程在演練機全部關閉：只驗站內通知與稽核列；Email 路徑只能驗到「被抑制」。",
    "pip 離線（PIP_NO_INDEX=1）：演練 venv 已滿足 requirements，套用腳本照常執行 pip 步驟。",
]

AUTOSTART_A1 = r"""@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set MOTRIX_DISABLE_SCHEDULERS=1
set MOTRIX_CLOUD_ARCHIVE=off
set MOTRIX_EMAIL_SEND=off
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

PUBKEY_RE = re.compile(r"(DELIVERY_PUBKEY_PEM = \()(.*?)(\n\)|\n    \))", re.S)


class DrillError(Exception):
    pass


# ── 純函式：安裝／包的改寫 ──────────────────────────────────────────────────────

def harden_tree(tree, inst, port, python):
    """把一棵樹（演練安裝，或假 T87 包的內容）裡的 apply_update.ps1、rollback_update.ps1 只改 `$ProdRoot`／`$Port` 兩行指向演練安裝，
    並放演練用 autostart.bat（只綁 127.0.0.1、演練埠、SAFE 環境）。⇒ {檔名: 改了哪幾行}。"""
    tools = Path(tree) / "backend" / "tools"
    out = {}
    for name in ("apply_update.ps1", "rollback_update.ps1"):
        p = tools / name
        raw = p.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        new, changed = DMA.rewrite_ps1(raw.decode("utf-8-sig"), inst, port)
        p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + new.encode("utf-8"))
        out[name] = changed
    # 發布守門要求「腳本內容雜湊＝登記檔」：演練副本改了兩行，登記檔的雜湊跟著更新（版號不動——演練副本與包裡的版號一致，套用不會想換腳本）。
    import delivery as D
    reg = tools / "apply_update.version.json"
    doc = json.loads(reg.read_text(encoding="utf-8-sig"))
    doc["sha256"] = D.ps1_digest((tools / "apply_update.ps1").read_bytes())
    reg.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (Path(tree) / "backend" / "autostart.bat").write_text(
        AUTOSTART_A1.format(backend=Path(inst) / "backend", python=python, port=port), encoding="utf-8")
    out["deploy_dashboard.py"] = rewrite_dashboard_prod(tree)
    return out


_DASH_HOST_RE = re.compile(r'^PROD_HOST = "172\.16\.10\.177"[ \t]*(?=\r?$)', re.M)
_DASH_URL_RE = re.compile(r'^PROD_BASE_URL = f"https://\{PROD_HOST\}:666"[ \t]*(?=\r?$)', re.M)
DEAD_END_HOST, DEAD_END_PORT = "127.0.0.1", 9          # 本機「丟棄」埠：沒人聽，連線立刻被拒；不出本機


def rewrite_dashboard_prod(tree):
    """預防（h11 必修）：儀表板在「交付資料夾沒設定成功」時會自己用 requests 打 PROD_BASE_URL（正式機）。
    演練副本（安裝與包內容）一律把 PROD_HOST／PROD_BASE_URL 改成本機死路；兩行都要「恰好一處」，否則拒絕演練。⇒ 改寫的行數。"""
    p = Path(tree) / "backend" / "tools" / "deploy_dashboard.py"
    if not p.exists():          # 出貨包（git archive）把它 export-ignore：沒有這個檔＝沒有這條路（preflight 的程式碼位址檢查仍會擋別處的正式機位址）
        return 0
    text = p.read_bytes().decode("utf-8")
    if len(_DASH_HOST_RE.findall(text)) != 1 or len(_DASH_URL_RE.findall(text)) != 1:
        raise DrillError("deploy_dashboard.py 的 PROD_HOST／PROD_BASE_URL 不是各恰好一行 ⇒ 不改寫、不演練（不猜）")
    text = _DASH_HOST_RE.sub(lambda _m: 'PROD_HOST = "%s"' % DEAD_END_HOST, text)
    text = _DASH_URL_RE.sub(lambda _m: 'PROD_BASE_URL = f"http://{PROD_HOST}:%d"' % DEAD_END_PORT, text)
    p.write_bytes(text.encode("utf-8"))
    return 2


def swap_pubkey(tree, pub_pem):
    """演練樹的 delivery.py 只換公鑰（正式那份內建真公鑰；演練沒有那把私鑰）。"""
    dp = Path(tree) / "backend" / "tools" / "delivery.py"
    src = dp.read_text(encoding="utf-8")
    new, n = PUBKEY_RE.subn(lambda m: m.group(1) + repr(pub_pem.encode("ascii")) + m.group(3), src, count=1)
    if n != 1:
        raise DrillError("找不到 DELIVERY_PUBKEY_PEM 的定義，無法換成演練公鑰")
    dp.write_text(new, encoding="utf-8")


def flip_signature(droot, name):
    """B1：改簽章檔的 1 個字元。⇒ 簽章檔路徑。"""
    import delivery as D
    p = Path(droot) / "packages" / name / D.SIG
    text = p.read_text(encoding="ascii")
    p.write_text(("B" if text[:1] != "B" else "A") + text[1:], encoding="ascii")
    return p


def add_pyc(tree):
    """B2a／B2b：放一個 `__pycache__\\x.pyc`。"""
    d = Path(tree) / "backend" / "__pycache__"
    d.mkdir(parents=True, exist_ok=True)
    (d / "a1_drill_x.cpython-312.pyc").write_bytes(b"\x00\x00\x00\x00drill")
    return d


def bump_db_version(tree):
    """B3：包裡 db.py 的 CURRENT_VERSION 加一（與已安裝版本的期望不一致）。⇒ (舊, 新)。"""
    p = Path(tree) / "backend" / "db.py"
    src = p.read_text(encoding="utf-8")
    m = re.search(r"^CURRENT_VERSION = (\d+)", src, re.M)
    if not m:
        raise DrillError("找不到 db.py 的 CURRENT_VERSION")
    old = int(m.group(1))
    p.write_text(src[:m.start()] + "CURRENT_VERSION = %d" % (old + 1) + src[m.end():], encoding="utf-8")
    return old, old + 1


def strip_dev_pubkey(pkg):
    """與 build_deploy_package.ps1 Step 5.52 相同（LG-O1）：正式公鑰非空 ⇒ 包內不帶開發公鑰。"""
    import pubkey_policy as PP
    lic = Path(pkg) / PP.LICENSING_REL
    new_src, _changed = PP.strip_source(PP._read(str(lic)))
    with open(str(lic), "w", encoding="utf-8", newline="") as f:
        f.write(new_src)
    left = PP.policy_problems(PP._read(str(lic)))
    if left:
        raise DrillError("演練包 licensing.py 仍違反 LG-O1：%s" % "；".join(left))


MIGRATION_OK = '''# -*- coding: utf-8 -*-
"""A1 演練用：建一張 a1_drill_probe 表（假 T87 的最小真實 schema 變更；只存在演練 worktree，不出貨）。"""


def up(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS a1_drill_probe (id INTEGER PRIMARY KEY, note TEXT)")
    return None
'''
MIGRATION_FAIL = '''# -*- coding: utf-8 -*-
"""A1 演練 B4 用：遷移丟例外（預演必須擋下，正式庫不動）。"""


def up(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS a1_drill_probe (id INTEGER PRIMARY KEY, note TEXT)")
    raise RuntimeError("A1 演練 B4：故意失敗的遷移")
'''


def apply_fake_t87_edits(wt, variant):
    """在演練 worktree 裡做假 T87 的改動（crm 模組加 migration 0006、版號加一、CHANGELOG、a1_expectations.json）。
    variant：good｜b4（遷移失敗）｜b5（預期檔要求一個不存在的檔，事後驗證會不過）。"""
    wt = Path(wt)
    mdir = wt / "backend" / "modules" / "crm"
    (mdir / "migrations" / (MIGRATION_NAME + ".py")).write_text(MIGRATION_FAIL if variant == "b4" else MIGRATION_OK, encoding="utf-8")
    init = mdir / "__init__.py"
    src = init.read_text(encoding="utf-8")
    a = '_m0005 = importlib.import_module("modules.crm.migrations.0005_dev_case_expected")\n'
    b = "(5, _m0005.up)]"
    if src.count(a) != 1 or src.count(b) != 1:
        raise DrillError("crm 的 __init__.py 形狀變了（找不到 migration 0005 的錨點）⇒ 演練器要改寫法")
    src = src.replace(a, a + '_m0006 = importlib.import_module("modules.crm.migrations.%s")\n' % MIGRATION_NAME)
    src = src.replace(b, "(5, _m0005.up), (6, _m0006.up)]")
    init.write_text(src, encoding="utf-8")
    mj = mdir / "module.json"
    man = json.loads(mj.read_text(encoding="utf-8"))
    old = man["version"]
    parts = [int(x) for x in re.findall(r"\d+", old)] + [0, 0, 0]
    new_ver = "%d.%d.%d" % (parts[0], parts[1], parts[2] + 1)
    mtxt = mj.read_text(encoding="utf-8").replace('"version": "%s"' % old, '"version": "%s"' % new_ver, 1)
    anchor = '"dev_log_directive_target"]'
    if mtxt.count(anchor) == 1:                                         # 模組宣告自己的表（沒宣告的表可能被模組載入守門擋）
        mtxt = mtxt.replace(anchor, '"dev_log_directive_target", "%s"]' % PROBE_TABLE)
    mj.write_text(mtxt, encoding="utf-8")
    json.loads(mtxt)
    cl = mdir / "CHANGELOG.md"
    body = cl.read_text(encoding="utf-8")
    first = body.index("\n## ")
    cl.write_text(body[:first] + "\n## %s — A1 演練（假 T87，不出貨）\n- 演練用改動：migration 6 建立 a1_drill_probe。\n" % new_ver + body[first:], encoding="utf-8")
    exp = {"pages": ["/api/ping"], "auth_required": [{"method": "GET", "path": "/api/auth/me"}],
           "files": ["backend/modules/crm/migrations/%s.py" % MIGRATION_NAME]}
    if variant == "b5":
        exp["files"].append("backend/a1_drill_expected_but_missing.txt")
    (wt / "backend" / "a1_expectations.json").write_text(json.dumps(exp, ensure_ascii=False, indent=1), encoding="utf-8")
    return new_ver


# ── 純函式：證據 ────────────────────────────────────────────────────────────────

_DIGEST_SKIP_DIRS = {"logs", "__pycache__", "uploads", ".git", "node_modules"}
_DIGEST_SKIP_SUFFIX = (".db", ".db-wal", ".db-shm", ".db-journal", ".pyc", ".log")


def tree_digest(root):
    """安裝目錄「程式碼」的雜湊：略過 logs／__pycache__／資料庫檔／上傳檔（它們本來就會變）。⇒ (sha256, 檔數)。"""
    h, n = hashlib.sha256(), 0
    base = Path(root)
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d.lower() not in _DIGEST_SKIP_DIRS)
        for fn in sorted(filenames):
            if fn.lower().endswith(_DIGEST_SKIP_SUFFIX) or fn.startswith(".initial_admin"):
                continue
            p = Path(dirpath) / fn
            try:
                data = p.read_bytes()
            except OSError:
                data = b"<unreadable>"
            h.update(str(p.relative_to(base)).lower().encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
            n += 1
    return h.hexdigest(), n


def db_file_hash(db_path):
    """資料庫主檔＋-wal 的雜湊（嚴格：位元組完全相同）。"""
    h = hashlib.sha256()
    for suffix in ("", "-wal"):
        p = Path(str(db_path) + suffix)
        h.update(p.read_bytes() if p.is_file() else b"<none>")
    return h.hexdigest()


def db_logical_digest(db_path, skip_tables=("sessions", "audit_log", "notifications")):
    """資料庫「邏輯內容」雜湊（唯讀開啟；略過本來就會變的表）：資料庫檔位元組會被讀取／checkpoint 改動時用它判斷資料有沒有動。"""
    conn = sqlite3.connect("file:%s?mode=ro" % Path(db_path).as_posix(), uri=True, timeout=30)
    try:
        h = hashlib.sha256()
        for (name, sql) in conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
            h.update(("T:%s:%s\n" % (name, sql)).encode("utf-8"))
            if name in skip_tables:
                continue
            for row in conn.execute('SELECT * FROM "%s" ORDER BY 1' % name.replace('"', '""')):
                h.update(repr(row).encode("utf-8"))
        return h.hexdigest()
    finally:
        conn.close()


def db_query(db_path, sql, args=()):
    conn = sqlite3.connect("file:%s?mode=ro" % Path(db_path).as_posix(), uri=True, timeout=30)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def read_audit_rows(inst):
    p = Path(inst) / "backend" / "logs" / "a1_audit.jsonl"
    if not p.is_file():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def blocked_reports(inst):
    """⇒ [(檔名, 內容)]，舊到新。"""
    d = Path(inst) / "backend" / "logs"
    return [(f.name, f.read_text(encoding="utf-8")) for f in sorted(d.glob("a1_report_blocked_*.md"))] if d.is_dir() else []


_ROLLBACK_RE = re.compile(r'^powershell -ExecutionPolicy Bypass -File "(?P<script>[^"\r\n;|&<>`$%]+?rollback_update\.ps1)" -SnapshotTimestamp (?P<ts>[0-9A-Za-z_\-]+)$')


def parse_rollback_command(cmd, inst):
    """B5 執行前驗證（h11）：報告上的回復指令必須**逐字**符合 auto_apply.rollback_hint 的格式（單一 powershell -File 指令、沒有 ; | & > < ` $ % 或換行），
    腳本路徑解析後必須就是演練安裝的 backend\\tools\\rollback_update.ps1。⇒ (argv, None) 或 (None, 拒絕原因)。
    我們自己組 argv（不把報告文字交給 shell）；加 -Yes（人手在提示輸入 Y 的替身；不加會卡在確認）。不帶 -IncludeDatabase。"""
    if not cmd:
        return None, "報告裡沒有回復指令"
    m = _ROLLBACK_RE.match(cmd.strip())
    if not m:
        return None, "回復指令格式不是預期的單一 powershell -File 指令，拒絕執行：%r" % cmd[:160]
    script = Path(m.group("script"))
    want = (Path(inst) / "backend" / "tools" / "rollback_update.ps1")
    try:
        if script.resolve() != want.resolve():
            return None, "回復指令的腳本路徑不是演練安裝的 rollback_update.ps1，拒絕執行：%s" % script
    except OSError as e:
        return None, "回復指令的腳本路徑解析失敗：%s" % e
    return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(want), "-SnapshotTimestamp", m.group("ts"), "-Yes"], None


def extract_rollback_command(report_text):
    """從報告文字找「回復到套用前」的指令行（含 rollback_update.ps1 的那一行，去掉 markdown 的反引號）。找不到 ⇒ None。"""
    for line in report_text.splitlines():
        if "rollback_update.ps1" in line:
            cmd = line.strip().lstrip("-*• ").strip().strip("`").strip()
            m = re.search(r"((?:powershell|pwsh|&)[^`]*rollback_update\.ps1.*)$", cmd, re.I)
            return (m.group(1) if m else cmd).strip().strip("`")
    return None


# ── 報告 ────────────────────────────────────────────────────────────────────────

def render_report(ctx):
    """DRILL-REPORT.md（純函式；ctx 是 dict，見 Drill.run）。"""
    mon = ctx.get("monitor") or {}
    L = ["# A1 M1 演練報告", "",
         "- 時間戳：%s　基底 commit：`%s`" % (ctx.get("stamp"), ctx.get("commit")),
         "- 演練目錄：`%s`（結束後已刪；報告留在這裡）" % ctx.get("base"),
         "- **基底說明**：" + BASE_STATEMENT, ""]
    L += ["## 對正式機的連線（可證明）", ""]
    if mon:
        L += ["- **%s**" % mon.get("statement", "（沒有監看資料）"),
              "- 取樣 %s 次、失敗 %s 次、看過的最多連線數 %s、看過的程序 %s 個；紀錄：`%s`" % (
                  mon.get("ticks"), mon.get("sample_errors"), mon.get("max_connections_seen"), mon.get("processes_seen"), mon.get("log")),
              "- 有證明：%s" % ("是" if mon.get("proven") else "**否（未證明）**")]
    else:
        L.append("- 監看器沒有啟動（演練沒有開跑）⇒ **未證明**；沒有任何演練程序被啟動。")
    L += ["", "### 防線", ""]
    for label, ok, detail in ctx.get("preflight") or []:
        L.append("- %s %s：%s" % ("✓" if ok else "✗", label, detail))
    if ctx.get("route_note"):
        L.append("- ℹ " + ctx["route_note"])
    sc = ctx.get("static_scan")
    if sc:
        L.append("- 靜態掃描：演練安裝掃了 %d 個設定檔，%d 項問題；隨產品出貨且演練不執行的已知檔（逐一列名）：%s" % (
            sc.get("files", 0), len(sc.get("findings") or []), "、".join(sc.get("allowed_product_files") or []) or "無"))
    if ctx.get("package_scans"):
        L.append("- 靜態掃描（已發布的假 T87 包內容）：%s" % "；".join("%s：%d 檔 %d 項問題" % (k, v["files"], len(v["findings"])) for k, v in ctx["package_scans"].items()))
    if ctx.get("code_literals") is not None:
        L.append("- 程式碼裡的正式機位址（阻擋式；名單外一律不開跑）：已知且逐一說明的 %d 個——" % len(ctx["code_literals"]))
        for rel, why in ctx["code_literals"]:
            L.append("  - `%s`：%s" % (rel, why))
    if ctx.get("dashboard_rewrite") == "absent":
        L.append("- 儀表板 deploy_dashboard.py：出貨包（git archive）已 export-ignore，演練安裝裡沒有這個檔＝沒有它打正式機的路（改寫 0 行；名單外的正式機位址仍由程式碼位址檢查阻擋）。")
    elif ctx.get("dashboard_rewrite"):
        L.append("- 儀表板的 PROD_HOST／PROD_BASE_URL 已在演練副本（安裝與包內容）改寫成本機死路 127.0.0.1:9（預防：交付資料夾沒設定成功時它也只會打到死路）。")
    if ctx.get("export_ignored_absent"):
        L.append("- 隨 git archive 被 export-ignore 的正式機遠端腳本（%s）：安裝與包內容裡都不存在（已檢查）。" % "、".join(ctx["export_ignored_absent"]))
    L += ["", "## 與正式機不同的地方（偏離）", ""] + ["- " + d for d in DEVIATIONS]
    L += ["", "## 矩陣結果", "", "| # | 情境 | 預期 | 結果 | 秒 |", "|---|---|---|---|---|"]
    for r in ctx.get("results") or []:
        mark = {True: "✅ 符合", False: "❌ 不符", None: "⚠ 未跑"}[r.get("passed")]
        L.append("| %s | %s | %s | %s | %s |" % (r["id"], r["title"], r["expected"].replace("|", "／"), mark, r.get("seconds", "")))
    for r in ctx.get("results") or []:
        L += ["", "### %s %s" % (r["id"], r["title"]), "", "- 預期：%s" % r["expected"], "- 實際：%s" % r.get("observed", "")]
        for label, ok, detail in r.get("checks") or []:
            L.append("  - %s %s：%s" % ("✓" if ok else "✗", label, detail))
        if r.get("error"):
            L.append("  - ⚠ 例外：%s" % r["error"])
    if ctx.get("abort"):
        L += ["", "## 中止", "", "- " + ctx["abort"]]
    L += ["", "## 收尾", "", "- " + (ctx.get("cleanup") or "（沒有收尾資訊）"), "- 耗時：%s 秒" % ctx.get("seconds", ""), ""]
    return "\n".join(L)


def exit_code(ctx):
    if ctx.get("abort") or not (ctx.get("monitor") or {}).get("proven", False) and not ctx.get("dry_build"):
        return 2
    if ctx.get("dry_build"):
        return 0 if not ctx.get("problems") else 2
    results = ctx.get("results") or []
    return 0 if results and all(r.get("passed") is True for r in results) else 1


# ── 演練器 ──────────────────────────────────────────────────────────────────────

class Check:
    """一個情境的檢查清單。"""

    def __init__(self, sid, title, expected):
        self.rec = {"id": sid, "title": title, "expected": expected, "checks": [], "observed": "", "passed": None}
        self.t0 = time.time()

    def ok(self, label, cond, detail=""):
        self.rec["checks"].append((label, bool(cond), str(detail)[:400]))
        return bool(cond)

    def done(self, observed):
        self.rec["observed"] = observed
        self.rec["passed"] = bool(self.rec["checks"]) and all(c[1] for c in self.rec["checks"])
        self.rec["seconds"] = round(time.time() - self.t0)
        return self.rec


class Drill:
    def __init__(self, args):
        self.args = args
        self.stamp = time.strftime("%Y%m%d_%H%M%S")
        self.base = Path(BASE_ROOT) / self.stamp
        self.inst = self.base / "inst"
        self.snap = self.base / "snap"
        self.droot = self.base / "delivery"
        self.staging = self.base / "motrix-staging"
        self.reports = Path(REPORT_ROOT) / self.stamp
        self.python = sys.executable
        self.port, self.dash = ERP_PORT, DASH_PORT
        self.commit = None
        self.monitor = None
        self.guard = None
        self.ctx = {"stamp": self.stamp, "base": str(self.base), "results": [], "dry_build": bool(args.dry_build), "problems": []}
        self.priv = self.pub = None
        self.fake_wt = None
        self.admin = None
        self.t0 = time.time()

    # -- 小工具 ---------------------------------------------------------------
    def log(self, msg):
        line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
        print(line, flush=True)
        try:
            with open(self.reports / "drill.log", "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def git(self, *args, cwd=None):
        rc, out = self.guard.run_tool(["git", "-C", str(cwd or REPO)] + list(args), timeout=300)
        if rc != 0:
            raise DrillError("git %s 失敗：%s" % (" ".join(args), out.strip()[:300]))
        return out.strip()

    def _make_guard(self, interval):
        self.monitor = PF.ConnectionMonitor(self.reports / "monitor.jsonl", lambda: self.guard.pids(), interval=interval,
                                            drill_root=self.base, ports=(self.port, self.dash), owned_fn=lambda: self.guard.owned_pids())
        self.guard = PF.DrillGuard(self.inst, self.monitor, erp_port=self.port, dash_port=self.dash, base=self.base)

    # -- 建置 -----------------------------------------------------------------
    def build_install(self):
        """演練安裝＝git archive（commit）＋與 build_deploy_package 相同的選配，全部經 guard.run_tool_bytes。"""
        self.log("建演練安裝（git archive %s）" % self.commit[:9])
        self.inst.mkdir(parents=True)
        rc, data, err = self.guard.run_tool_bytes(["git", "-C", str(REPO), "archive", "--format=tar", self.commit], timeout=300)
        if rc != 0:
            raise DrillError("git archive 失敗：%s" % err.decode("utf-8", "replace")[:300])
        with tarfile.open(fileobj=io.BytesIO(data)) as t:
            t.extractall(self.inst, filter="data")
        import product_select as PS
        PS.apply(self.inst, PS.load_product("full"))
        (self.inst / "backend" / ".deployed_commit.json").write_text(
            json.dumps({"commit": self.commit, "built_at": time.strftime("%Y-%m-%d %H:%M:%S")}), encoding="utf-8")
        sys.path.insert(0, str(self.inst / "backend" / "tools"))
        import apply_plan as AP
        u = AP.load_classifier(str(self.inst))
        AP.write_baseline(str(self.inst), {"commit": self.commit, "package_files": AP.package_files(str(self.inst), u)})
        for marker in (".no_email_send", ".no_cloud_archive"):
            (self.inst / marker).write_text("drill\n", encoding="utf-8")
        rewritten = harden_tree(self.inst, self.inst, self.port, self.python)
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        k = Ed25519PrivateKey.generate()
        self.priv = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        self.pub = k.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
        swap_pubkey(self.inst, self.pub)
        self.ctx["ps1_rewrite_lines"] = rewritten
        self.droot.mkdir()
        return rewritten

    def fake_commit(self, variant):
        """演練 worktree 上的 drill-only commit（不推、不併）。⇒ commit。"""
        if self.fake_wt is None:
            self.fake_wt = self.base / "fake-t87"
            self.git("-c", "core.hooksPath=NUL", "worktree", "add", "--detach", str(self.fake_wt), self.commit)
        self.git("-c", "core.hooksPath=NUL", "checkout", "-q", "--detach", self.commit, cwd=self.fake_wt)
        self.git("reset", "-q", "--hard", cwd=self.fake_wt)
        apply_fake_t87_edits(self.fake_wt, variant)
        self.git("add", "-A", cwd=self.fake_wt)
        self.git("-c", "core.hooksPath=NUL", "-c", "commit.gpgsign=false", "-c", "user.name=a1-drill", "-c", "user.email=a1-drill@example.invalid", "commit", "-q", "--no-verify", "-m", "A1 drill fake T87 (%s; not pushed)" % variant, cwd=self.fake_wt)
        return self.git("rev-parse", "HEAD", cwd=self.fake_wt)

    def make_package(self, commit, label, mutate=None):
        """假 T87 的包內容（git archive 該 commit ＋ 與 build_deploy_package 相同的選配／LG-O1／不出貨清單），並放演練副本腳本與演練公鑰。"""
        dest = self.base / "pkgs" / label
        dest.mkdir(parents=True)
        rc, data, err = self.guard.run_tool_bytes(["git", "-C", str(REPO), "archive", "--format=tar", commit], timeout=300)
        if rc != 0:
            raise DrillError("git archive 失敗：%s" % err.decode("utf-8", "replace")[:300])
        with tarfile.open(fileobj=io.BytesIO(data)) as t:
            t.extractall(dest, filter="data")
        import product_select as PS
        PS.apply(dest, PS.load_product("full"))
        strip_dev_pubkey(dest)
        import export_ignore_list as EI
        (dest / "backend" / "export_ignore.json").write_text(json.dumps(EI.build(str(REPO), commit), ensure_ascii=False, indent=1), encoding="utf-8")
        (dest / "deploy_manifest.json").write_text(json.dumps({"commit": commit, "product": "full", "built_at": datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
        harden_tree(dest, self.inst, self.port, self.python)
        swap_pubkey(dest, self.pub)
        if mutate:
            mutate(dest)
        return dest

    def publish(self, pkg, minutes):
        import delivery as D
        return D.publish(str(pkg), str(self.droot), self.priv, now=datetime(2026, 11, 14, 3, 0, 0) + timedelta(minutes=minutes),
                         tools_dir=str(self.inst / "backend" / "tools"))

    def scan_published(self, name):
        payload = self.droot / "packages" / name / "payload"
        res = PF.static_scan(payload, expect_root=self.inst)
        cf, allowed = PF.code_literal_findings(payload)             # 包內容也要過阻擋式程式碼位址檢查（含 PROD_HOST 已改寫成死路）
        res["findings"] = list(res["findings"]) + cf
        res["code_literals_allowed"] = allowed
        return res

    # -- 服務 -----------------------------------------------------------------
    def start_erp(self, wait=120):
        self.guard.launch(["cmd.exe", "/c", str(self.inst / "backend" / "autostart.bat")], self.inst / "backend", "啟動演練 ERP", detached=True)
        t0 = time.time()
        while time.time() - t0 < wait:
            self.monitor.check_clean()
            if DMA.ping(self.port):
                return round(time.time() - t0, 1)
            time.sleep(2)
        raise DrillError("演練 ERP %d 秒內沒起來（看 %s）" % (wait, self.inst / "backend" / "logs" / "server.log"))

    def start_dashboard(self, extra_env=None, allow_hosts=(), wait=60):
        env = {"PATH": str(Path(self.python).parent) + os.pathsep + os.environ.get("PATH", "")}       # 套用腳本的 `python` 用演練 venv
        env.update(extra_env or {})
        self.guard.launch([self.python, "-m", "uvicorn", "deploy_dashboard:app", "--host", "127.0.0.1", "--port", str(self.dash), "--log-level", "warning"],
                          self.inst / "backend" / "tools", "啟動演練儀表板", extra_env=env, allow_hosts=allow_hosts, detached=True)
        t0 = time.time()
        while time.time() - t0 < wait:
            self.monitor.check_clean()
            if DMA._api(self.dash, "/api/delivery/overview")[0] == 200:
                return
            time.sleep(1)
        raise DrillError("演練儀表板 %d 秒內沒起來" % wait)

    def safe_cleanup(self):
        """刪演練目錄前再確認一次路徑（直接在 BASE_ROOT 底下、含時間戳、不含 V9.0）。"""
        self.in_base(self.base)
        if "v9.0" in str(self.base).lower():
            raise PF.DrillAbort("演練目錄路徑含 V9.0，拒絕刪除：%s" % self.base)
        return DMA.cleanup(self.base)

    def stop_services(self):
        try:
            return PF.stop_drill_processes(self.base, self.guard.records, self.guard.start_ticks, log=self.log)
        except Exception as e:                                          # noqa: BLE001 — 收尾不可丟例外
            self.log("停服務出錯：%s" % e)
            return []

    def in_base(self, p):
        """防呆：任何刪除／鏡像（robocopy /MIR）的目標都必須在本次演練目錄底下，而且演練目錄本身直接在 BASE_ROOT 底下。"""
        base = Path(self.base).resolve()
        if base.parent != Path(BASE_ROOT).resolve() or base == Path(BASE_ROOT).resolve():
            raise PF.DrillAbort("演練目錄不在 %s 的直接底下：%s（拒絕刪除／鏡像）" % (BASE_ROOT, self.base))
        rp = Path(p).resolve()
        if rp != base and base not in rp.parents:
            raise PF.DrillAbort("拒絕刪除／鏡像演練目錄以外的路徑：%s" % p)
        return rp

    def robocopy(self, src, dst):
        self.in_base(src)
        self.in_base(dst)
        rc, out = self.guard.run_tool(["robocopy", str(src), str(dst), "/MIR", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/R:3", "/W:2"], timeout=1800)
        if rc >= 8:
            raise DrillError("robocopy 失敗 rc=%s：%s" % (rc, out[-300:]))

    def restore(self):
        self.stop_services()
        time.sleep(3)
        self.robocopy(self.snap, self.inst)
        self.in_base(self.staging)
        DMA._rmtree(self.staging)
        for child in list(self.droot.iterdir()) if self.droot.exists() else []:
            self.in_base(child)
            DMA._rmtree(child) if child.is_dir() else child.unlink()

    # -- 管理員、交付資料夾設定 --------------------------------------------------
    def setup_admin_and_delivery_root(self):
        cred = (self.inst / "backend" / ".initial_admin_credentials.txt").read_text(encoding="utf-8")
        user = re.search(r"帳號:\s*(\S+)", cred).group(1)
        DMA.setup_company(self.inst, self.port)
        pw = "Drill-%d-Pass!9" % self.port
        s, b = DMA._api(self.port, "/api/auth/login", {"username": user, "password": pw})
        if s != 200:
            raise DrillError("演練管理員登入失敗：%s %s" % (s, b))
        s, b2 = DMA._api(self.port, "/api/settings/storage-locations", {"archive_root": "", "pii_root": "", "delivery_root": str(self.droot)},
                         token=b["token"], method="PUT")
        if s != 200:
            raise DrillError("設定交付資料夾失敗：%s %s" % (s, b2))
        self.admin = (user, pw)

    @property
    def db(self):
        return self.inst / "backend" / "motrix_erp.db"

    # -- 瀏覽器操作 -------------------------------------------------------------
    def ui_open(self, page, name):
        page.goto("http://127.0.0.1:%d/" % self.dash)
        page.wait_for_function("(n) => Array.from(document.querySelectorAll('[data-testid=\"dl-pkg\"] option')).some(o => o.value === n)", arg=name, timeout=60000)
        page.select_option('[data-testid="dl-pkg"]', value=name)

    def ui_prepare(self, page):
        page.click('[data-testid="dl-prepare"]')
        page.wait_for_function("() => { const v = document.getElementById('dlVerify'); return v && !v.classList.contains('hidden') && v.textContent.indexOf('準備中') !== 0; }", timeout=900000)
        text = page.text_content('[data-testid="dl-verify"]') or ""
        ok = page.is_visible('[data-testid="dl-confirm"]') and text.startswith("驗證通過")
        return ok, text

    def ui_rehearse(self, page):
        page.click('[data-testid="dl-rehearse"]')
        page.wait_for_function("() => { const t = document.getElementById('dlRehearseText').textContent; return t.indexOf('預演中') !== 0 && t.indexOf('尚未預演') !== 0; }", timeout=1800000)
        text = page.text_content('[data-testid="dl-rehearse-text"]') or ""
        return text.startswith("預演通過"), text

    def ui_apply(self, page, user, pw, timeout_ms=2700000):
        page.fill('[data-testid="dl-user"]', user)
        page.fill('[data-testid="dl-pass"]', pw)
        page.check('[data-testid="dl-ack"]')
        page.click('[data-testid="dl-apply"]')
        page.wait_for_function("() => { const r = document.getElementById('dlResult'); const o = r.getAttribute('data-outcome'); return !r.classList.contains('hidden') && o && o !== 'running'; }", timeout=timeout_ms)
        return page.get_attribute('[data-testid="dl-result"]', "data-outcome"), page.text_content('[data-testid="dl-result"]') or ""

    # -- 情境 -----------------------------------------------------------------
    def fresh(self, page_factory, packages, dash_env=None, allow_hosts=()):
        """停服務 → 還原安裝快照 → 清交付與暫存 → 發布這個情境的包 → 起 ERP 與儀表板。⇒ {label: 包名}"""
        self.restore()
        names = {}
        for i, (label, builder) in enumerate(packages):
            pkg, post = builder()
            name = self.publish(pkg, self.minute)
            self.minute += 1
            if post:
                post(name)
            names[label] = name
            scan = self.scan_published(name)
            self.ctx.setdefault("package_scans", {})[name[-24:]] = {"files": scan["files"], "findings": scan["findings"]}
            if scan["findings"]:
                raise PF.DrillAbort("已發布的包內容靜態掃描未通過：%s" % scan["findings"][:3])
        self.guard.ready("起演練服務（已重新確認腳本未被改動）")
        self.start_erp()
        self.start_dashboard(dash_env, allow_hosts)
        return names

    def run_scenarios(self):
        from playwright.sync_api import sync_playwright
        wanted = [s for s in SCENARIOS if s in self.args.only]
        self.minute = 1
        commits = {}
        for v in ("good", "b4", "b5"):
            if any(s in wanted for s in {"good": ("G", "B1", "B2a", "B2b", "B3", "B6", "B7"), "b4": ("B4",), "b5": ("B5",)}[v]):
                commits[v] = self.fake_commit(v)
        self.ctx["fake_commits"] = commits
        self.guard.ready("開瀏覽器")
        clean = PF.sanitized_env(self.port, self.dash)
        saved = dict(os.environ)
        os.environ.clear()                                                  # Playwright 的 node driver 只能繼承本行程環境：這是唯一不經 guard.launch 的子行程，
        os.environ.update(clean)                                            # 所以先把本行程環境換成乾淨的（監看器把它當編排器的子孫一起看）；結束後還原
        try:
            with sync_playwright() as pw:
                self._drive_browser(pw, wanted, commits, clean)
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def _drive_browser(self, pw, wanted, commits, clean_env):
        browser = pw.chromium.launch(headless=True, env=clean_env, args=["--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1",
                                                          "--disable-background-networking", "--disable-component-update", "--disable-sync"])
        try:
            for sid in wanted:
                self.monitor.check_clean()
                self.guard.ready("跑情境 " + sid)
                self.log("── 情境 %s ──" % sid)
                ctxb = browser.new_context()
                page = ctxb.new_page()
                try:
                    rec = getattr(self, "scenario_" + sid)(page, commits)
                except PF.DrillAbort:
                    raise
                except Exception as e:                                      # noqa: BLE001 — 一個情境壞了，記下、繼續下一個
                    rec = {"id": sid, "title": sid, "expected": "（情境例外）", "checks": [], "observed": "", "passed": False,
                           "error": "%s: %s\n%s" % (type(e).__name__, e, traceback.format_exc()[-600:])}
                    self.log("情境 %s 例外：%s" % (sid, e))
                finally:
                    ctxb.close()
                self.ctx["results"].append(rec)
                self.log("情境 %s：%s" % (sid, {True: "符合", False: "不符", None: "未判定"}[rec.get("passed")]))
        finally:
            browser.close()

    def _good(self, label, mutate=None, pre=None):
        def build():
            pkg = self.make_package(self.ctx["fake_commits"]["good"], label, mutate)
            return pkg, pre
        return label, build

    def _inst_unchanged(self, chk, before, label="安裝目錄程式碼沒有被動到"):
        after = tree_digest(self.inst)
        chk.ok(label, after == before, "前 %s…（%d 檔）／後 %s…（%d 檔）" % (before[0][:10], before[1], after[0][:10], after[1]))

    def _blocked_has(self, chk, step_word, since_count, name_ok=True):
        reps = blocked_reports(self.inst)
        new = reps[since_count:]
        chk.ok("留下白話報告 a1_report_blocked_*.md（停在「%s」）" % step_word, any(step_word in t for _n, t in new), "新增 %d 份；%s" % (len(new), new[-1][0] if new else "無"))
        rows = [r for r in read_audit_rows(self.inst) if r.get("event") == "apply_blocked"]
        chk.ok("稽核有 apply_blocked", bool(rows), "%d 筆；最後一筆 step=%s" % (len(rows), rows[-1].get("step") if rows else None))
        if new:
            chk.ok("報告寫明正式系統沒有被改動", "正式系統沒有被改動" in new[-1][1], new[-1][1].splitlines()[0][:80])

    def scenario_G(self, page, commits):
        chk = Check("G", "完整成功（主驗收）", "準備→預演→帳密→同意→套用，零人工介入；事後驗證全綠；報告／result／稽核鏈／audit_log／通知齊全")
        names = self.fresh(None, [self._good("g")])
        name = names["g"]
        self.ui_open(page, name)
        ok, text = self.ui_prepare(page)
        chk.ok("準備通過", ok, text[:120])
        rok, rtext = self.ui_rehearse(page)
        chk.ok("預演通過", rok, rtext[:160])
        outcome, rtxt = self.ui_apply(page, *self.admin)
        chk.ok("畫面結果＝成功", outcome == "succeeded", "%s：%s" % (outcome, rtxt[:200]))
        res_p = self.droot / "results" / (name + ".result.json")
        res = json.loads(res_p.read_text(encoding="utf-8")) if res_p.is_file() else {}
        chk.ok("交付資料夾 results\\<包>.result.json 寫回且 outcome=succeeded", res.get("outcome") == "succeeded", "outcome=%s" % res.get("outcome"))
        logs = self.inst / "backend" / "logs"
        mds = sorted(f for f in logs.glob("a1_report_*.md") if "blocked" not in f.name)
        jss = sorted(f for f in logs.glob("a1_report_*.json"))
        chk.ok("a1_report_*.md 與 .json 都有", bool(mds) and bool(jss), "%d／%d 份" % (len(mds), len(jss)))
        if jss:
            rj = json.loads(jss[-1].read_text(encoding="utf-8"))
            same = {k: (rj.get(k), res.get(k)) for k in ("outcome", "name") if k in rj and k in res}
            chk.ok("報告 json 與 result.json 逐欄相符（outcome、name）", all(a == b for a, b in same.values()) and bool(same), str(same))
        a1p = self.droot / "results" / (name + ".a1.json")
        a1 = json.loads(a1p.read_text(encoding="utf-8")) if a1p.is_file() else {}
        head = a1.get("chain_head")
        rc, out = self.guard.run_tool([self.python, "-I", str(self.inst / "backend" / "tools" / "auto_apply.py"), "--check-audit", str(self.inst)] + ([head] if head else []), timeout=120)
        chk.ok("稽核鏈 --check-audit 通過（以 a1.json 的鏈頭為錨點）", rc == 0 and bool(head), "rc=%s head=%s %s" % (rc, (head or "")[:12], out.strip()[-120:]))
        rows = db_query(self.db, "SELECT target_label FROM audit_log WHERE action='system_update.apply' AND target_id=?", (name[:80],))
        chk.ok("ERP audit_log 有一列（標籤含套用者）", len(rows) == 1 and self.admin[0] in (rows[0][0] or ""), "%d 列；%s" % (len(rows), rows[0][0][:60] if rows else ""))
        note = db_query(self.db, "SELECT COUNT(*) FROM notifications WHERE type='system_update_result'")[0][0]
        chk.ok("站內通知有寫", note >= 1, "%d 筆" % note)
        probe = db_query(self.db, "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (PROBE_TABLE,))
        chk.ok("假 T87 的 schema 變更已套上（%s 表存在）" % PROBE_TABLE, bool(probe))
        dep = json.loads((self.inst / "backend" / ".deployed_commit.json").read_text(encoding="utf-8-sig"))
        chk.ok("安裝的 commit 已是假 T87", dep.get("commit") == commits["good"], str(dep.get("commit"))[:12])
        return chk.done("outcome=%s；停機秒數 %s" % (res.get("outcome"), res.get("downtime_seconds", "?")))

    def _bad_package_scenario(self, sid, title, expected, page, builder, post, step_word, prepare_refused=True):
        chk = Check(sid, title, expected)
        names = self.fresh(None, [("bad", builder)])
        before = tree_digest(self.inst)
        nrep = len(blocked_reports(self.inst))
        self.ui_open(page, names["bad"])
        ok, text = self.ui_prepare(page)
        chk.ok("準備被拒（沒有出現確認區），畫面有白話原因", (not ok) and len(text) > 10, text[:200])
        self._blocked_has(chk, step_word, nrep)
        self._inst_unchanged(chk, before)
        return chk.done(text[:160])

    def scenario_B1(self, page, commits):
        return self._bad_package_scenario(
            "B1", "簽章錯", "停在「準備」（驗章）；白話原因；安裝目錄不變", page,
            lambda: (self.make_package(commits["good"], "b1"), lambda n: flip_signature(self.droot, n)), None, "準備")

    def scenario_B2a(self, page, commits):
        return self._bad_package_scenario(
            "B2a", "包帶 pyc", "停在「準備」（verify_package）；白話原因", page,
            lambda: (self.make_package(commits["good"], "b2a", add_pyc), None), None, "準備")

    def scenario_B3(self, page, commits):
        return self._bad_package_scenario(
            "B3", "schema 與預期不符（db.py CURRENT_VERSION）", "停在「準備」（--expect-db-version）；白話原因", page,
            lambda: (self.make_package(commits["good"], "b3", bump_db_version), None), None, "準備")

    def scenario_B2b(self, page, commits):
        chk = Check("B2b", "準備後暫存包被塞檔", "停在「套用」要密碼之前的完整性檢查；被拒（多出檔案），沒有碰密碼")
        names = self.fresh(None, [self._good("b2b")])
        name = names["b2b"]
        self.ui_open(page, name)
        ok, text = self.ui_prepare(page)
        chk.ok("準備通過", ok, text[:100])
        rok, rtext = self.ui_rehearse(page)
        chk.ok("預演通過", rok, rtext[:100])
        before = tree_digest(self.inst)
        nrep = len(blocked_reports(self.inst))
        staged = self.staging / name / "payload"
        add_pyc(staged)
        outcome, rtxt = self.ui_apply(page, *self.admin)
        chk.ok("套用被拒（沒有開始套用）", outcome == "failed" and "沒有開始套用" in rtxt, rtxt[:200])
        chk.ok("拒絕原因是暫存包完整性（不是密碼）", "密碼" not in rtxt.split("沒有開始套用")[-1][:60] or "暫存" in rtxt, rtxt[:200])
        self._blocked_has(chk, "套用前檢查", nrep)
        self._inst_unchanged(chk, before)
        return chk.done(rtxt[:160])

    def scenario_B4(self, page, commits):
        chk = Check("B4", "遷移失敗", "停在「預演」；預演不通過；正式庫前後完全相同")
        def build():
            return self.make_package(commits["b4"], "b4"), None
        names = self.fresh(None, [("b4", build)])
        self.ui_open(page, names["b4"])
        ok, text = self.ui_prepare(page)
        chk.ok("準備通過（壞在遷移，不是包格式）", ok, text[:100])
        h0, l0 = db_file_hash(self.db), db_logical_digest(self.db)
        before = tree_digest(self.inst)
        nrep = len(blocked_reports(self.inst))
        rok, rtext = self.ui_rehearse(page)
        chk.ok("預演不通過", (not rok) and "預演未通過" in rtext, rtext[:200])
        self._blocked_has(chk, "預演", nrep)
        h1, l1 = db_file_hash(self.db), db_logical_digest(self.db)
        chk.ok("正式庫邏輯內容前後完全相同", l0 == l1, "%s… / %s…" % (l0[:10], l1[:10]))
        chk.ok("（資訊）正式庫檔案位元組前後相同", h0 == h1, "同" if h0 == h1 else "不同：ERP 閒置時的檢查點／讀取可能改動檔案；以邏輯內容為準")
        self._inst_unchanged(chk, before)
        return chk.done(rtext[:160])

    def scenario_B5(self, page, commits):
        chk = Check("B5", "事後驗證不過（不自動回滾）", "套用完成後事後驗證不過；verify_failed、不自動回滾、報告列出回復指令；在演練機真的執行後回到套用前")
        names = self.fresh(None, [("b5", lambda: (self.make_package(commits["b5"], "b5"), None))])
        name = names["b5"]
        self.ui_open(page, name)
        ok, _t = self.ui_prepare(page)
        rok, _r = self.ui_rehearse(page)
        chk.ok("準備與預演通過", ok and rok)
        code0, l0 = tree_digest(self.inst), db_logical_digest(self.db)
        outcome, rtxt = self.ui_apply(page, *self.admin)
        chk.ok("結果＝verify_failed（已套用但驗證有項目未通過）", outcome == "verify_failed", "%s：%s" % (outcome, rtxt[:200]))
        chk.ok("畫面說明系統不會自動回復", "不會自動回復" in rtxt or "不會自動回滾" in rtxt, rtxt[:160])
        dep = json.loads((self.inst / "backend" / ".deployed_commit.json").read_text(encoding="utf-8-sig"))
        chk.ok("沒有自動回滾（安裝的 commit 是假 T87）", dep.get("commit") == commits["b5"], str(dep.get("commit"))[:12])
        logs = self.inst / "backend" / "logs"
        mds = sorted(f for f in logs.glob("a1_report_*.md") if "blocked" not in f.name)
        text = mds[-1].read_text(encoding="utf-8") if mds else ""
        cmd = extract_rollback_command(text)
        chk.ok("報告列出回復到套用前的指令", bool(cmd), (cmd or "（報告裡找不到 rollback_update.ps1）")[:200])
        argv, why = parse_rollback_command(cmd, self.inst)
        if cmd:
            chk.ok("回復指令格式與路徑合格（單一指令、腳本在演練安裝內）才執行", argv is not None, why or "合格；自行組 argv 並加 -Yes，不交給 shell")
        if argv:
            self.stop_services()
            time.sleep(3)
            rc, out = self.guard.launch(argv, self.inst, "執行報告上的回復指令", wait=True, timeout=1500)
            chk.ok("回復指令執行完成", rc == 0, "rc=%s %s" % (rc, out[-200:].replace("\n", " ")))
            time.sleep(5)
            self.guard.ready("回復後檢查")
            dep2 = json.loads((self.inst / "backend" / ".deployed_commit.json").read_text(encoding="utf-8-sig"))
            code1 = tree_digest(self.inst)
            chk.ok("回復後程式碼雜湊＝套用前", code1 == code0, "%s… / %s…（commit %s）" % (code0[0][:10], code1[0][:10], str(dep2.get("commit"))[:9]))
            self.stop_services()
            time.sleep(3)
            l1 = db_logical_digest(self.db)
            chk.ok("回復後資料庫邏輯內容＝套用前", l0 == l1, "%s… / %s…" % (l0[:10], l1[:10]))
        return chk.done(rtxt[:160])

    def scenario_B6(self, page, commits):
        chk = Check("B6", "預演後正式庫被改", "停在「套用」開始前；被擋「預演之後正式庫結構已變動」，要求重新預演")
        names = self.fresh(None, [self._good("b6")])
        self.ui_open(page, names["b6"])
        ok, _t = self.ui_prepare(page)
        rok, _r = self.ui_rehearse(page)
        chk.ok("準備與預演通過", ok and rok)
        conn = sqlite3.connect(str(self.db), timeout=60)
        try:
            conn.execute("ALTER TABLE tenders ADD COLUMN a1_drill_extra TEXT")
            conn.commit()
        finally:
            conn.close()
        before = tree_digest(self.inst)
        nrep = len(blocked_reports(self.inst))
        outcome, rtxt = self.ui_apply(page, *self.admin)
        chk.ok("套用被擋（沒有開始套用），原因是正式庫結構變動", outcome == "failed" and "沒有開始套用" in rtxt and "結構" in rtxt, rtxt[:220])
        self._blocked_has(chk, "套用前檢查", nrep)
        self._inst_unchanged(chk, before)
        return chk.done(rtxt[:160])

    def scenario_B7(self, page, commits):
        chk = Check("B7", "系統位址不是本機", "停在「套用」要密碼之前；被拒；沒有任何對外連線（監看器：對正式機 0 連線）")
        names = self.fresh(None, [self._good("b7")], dash_env={"MOTRIX_DELIVERY_ERP_URL": "https://" + EXAMPLE_HOST}, allow_hosts=(EXAMPLE_HOST,))
        self.ui_open(page, names["b7"])
        ok, _t = self.ui_prepare(page)
        rok, _r = self.ui_rehearse(page)
        chk.ok("準備與預演通過", ok and rok)
        before = tree_digest(self.inst)
        nrep = len(blocked_reports(self.inst))
        prod_before, other_before = self.monitor.prod_hits, self.monitor.other_hits
        outcome, rtxt = self.ui_apply(page, *self.admin)
        chk.ok("套用被拒（沒有開始套用），原因是系統位址不是本機", outcome == "failed" and "沒有開始套用" in rtxt and "系統位址" in rtxt, rtxt[:220])
        self._blocked_has(chk, "系統位址", nrep)
        self._inst_unchanged(chk, before)
        time.sleep(self.args.interval * 2 + 1)
        chk.ok("這段期間監看器沒看到任何非本機連線", self.monitor.prod_hits == prod_before and self.monitor.other_hits == other_before and not self.monitor.tripped,
               "對正式機 %d、非本機 %d" % (self.monitor.prod_hits, self.monitor.other_hits))
        return chk.done(rtxt[:160])

    # -- 總流程 ---------------------------------------------------------------
    def run(self):
        self.reports.mkdir(parents=True, exist_ok=True)
        try:
            # ① 順序寫死：check → build → scan → control → start（沒做完就拒絕開跑）
            self._make_guard(self.args.interval)
            self.commit = self.git("rev-parse", "HEAD")
            self.ctx["commit"] = self.commit
            self.ctx["preflight"] = self.guard.check()
            self.ctx["route_note"] = PF.route_note()
            self.log("防線 1（環境檢查）通過")
            self.build_install()
            self.ctx["static_scan"] = self.guard.scan()                  # 內含阻擋式程式碼位址檢查（名單外的正式機位址 ⇒ DrillAbort）
            self.ctx["code_literals"] = self.ctx["static_scan"].get("code_literals_allowed", [])
            self.ctx["dashboard_rewrite"] = int((self.ctx.get("ps1_rewrite_lines") or {}).get("deploy_dashboard.py", 0)) or "absent"
            self.ctx["export_ignored_absent"] = list(PF.EXPORT_IGNORED_ABSENT)
            self.log("防線 2（靜態掃描）通過：%d 個設定檔" % self.ctx["static_scan"]["files"])
            if self.args.dry_build:
                self.dry_build_extra()
                return
            self.guard.control()
            self.log("防線 3（監看器正對照）通過")
            self.guard.start()
            self.log("監看器啟動（每 %g 秒）" % self.args.interval)
            self.guard.ready("起演練 ERP")
            self.start_erp()
            self.setup_admin_and_delivery_root()
            self.stop_services()
            time.sleep(3)
            self.robocopy(self.inst, self.snap)                          # 乾淨快照：每個情境從它還原
            self.run_scenarios()
        except PF.DrillAbort as e:
            self.ctx["abort"] = str(e)
            self.log("中止：%s" % e)
        except Exception as e:                                          # noqa: BLE001
            self.ctx["abort"] = "%s: %s\n%s" % (type(e).__name__, e, traceback.format_exc()[-800:])
            self.log("演練器例外：%s" % e)
        finally:
            self.finish()

    def dry_build_extra(self):
        """--dry-build：再做假 T87 的 good commit、包、發布與包內容掃描，用安裝的 verify_package 驗一次；不起服務。"""
        c = self.fake_commit("good")
        pkg = self.make_package(c, "dry")
        name = self.publish(pkg, 1)
        scan = self.scan_published(name)
        self.ctx["package_scans"] = {name[-24:]: {"files": scan["files"], "findings": scan["findings"]}}
        if scan["findings"]:
            self.ctx["problems"].append("包內容靜態掃描有問題：%s" % scan["findings"][:3])
        import delivery as D
        ver = D.installed_db_version(str(self.inst)) if hasattr(D, "installed_db_version") else None
        self.ctx["results"].append({"id": "dry", "title": "乾跑建置", "expected": "安裝、假 T87 包、發布、兩處靜態掃描都通過", "passed": not self.ctx["problems"],
                                    "observed": "包 %s；安裝的 db 版本 %s" % (name, ver), "checks": [("包內容靜態掃描", not scan["findings"], "%d 檔" % scan["files"])]})

    def finish(self):
        try:
            if self.monitor:
                self.monitor.stop()
                if self.guard is not None and "start" in getattr(self.guard, "done", ["start"]):     # 監看器真的啟動過才有摘要；乾跑／防線沒過＝沒有演練程序、不寫摘要
                    self.ctx["monitor"] = self.monitor.summary()
            self.ctx["seconds"] = round(time.time() - self.t0)
            killed = self.stop_services() if self.guard else []
            time.sleep(3)
            if self.fake_wt is not None:
                try:
                    self.git("worktree", "remove", "--force", str(self.fake_wt))
                    self.git("worktree", "prune")
                except Exception as e:                                  # noqa: BLE001
                    self.log("移除 worktree 失敗：%s" % e)
            if self.args.keep:
                self.ctx["cleanup"] = "--keep：演練目錄保留在 %s" % self.base
            else:
                self.ctx["cleanup"] = "停掉演練程序 %s；演練目錄 %s" % (killed, self.safe_cleanup())
            self.ctx["exit_code"] = exit_code(self.ctx)
            (self.reports / "DRILL-REPORT.md").write_text(render_report(self.ctx), encoding="utf-8")
            (self.reports / "drill.json").write_text(json.dumps(self.ctx, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
            self.log("報告：%s" % (self.reports / "DRILL-REPORT.md"))
        except Exception as e:                                          # noqa: BLE001
            print("收尾出錯：%s" % e, file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-build", action="store_true", help="只建安裝副本與假 T87 包並掃描，不起服務")
    ap.add_argument("--only", default=",".join(SCENARIOS), type=lambda s: [x.strip() for x in s.split(",") if x.strip()])
    ap.add_argument("--keep", action="store_true", help="結束後保留演練目錄")
    ap.add_argument("--interval", type=float, default=2.0, help="連線監看取樣間隔（秒）")
    a = ap.parse_args(argv)
    bad = [x for x in a.only if x not in SCENARIOS]
    if bad:
        ap.error("不認得的情境：%s（可用：%s）" % (bad, ",".join(SCENARIOS)))
    d = Drill(a)
    d.run()
    return d.ctx.get("exit_code", 2)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
