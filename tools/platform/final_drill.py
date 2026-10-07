# -*- coding: utf-8 -*-
"""D7 最終轉移升級驗證（RUN-PLAN §3）：用 V9 開發目錄的**複本**，照 UPGRADE-RUNBOOK 走一次完整的升級與兩種回滾。

  python tools/platform/final_drill.py [--v9-dir C:\\Users\\hichan\\Desktop\\MOTRIX-ERP] [--drill-root D:\\開發測試檔\\MOTRIX-FINAL-DRILL]
                                       [--package <部署包目錄> | --new-rev origin/platform]
                                       [--report docs/platform/FINAL-DRILL-REPORT.md] [--keep-install]

步驟（每一步記耗時、結果、雜湊）：
  1. 備份來源：V9 開發目錄的資料庫以**唯讀連線**＋Online Backup 複製到 `<drill-root>/source-backup/`，資料目錄逐檔複製，附雜湊清單。
  2. 建演練安裝目錄：整份複製成 `<drill-root>/v9-install/`（不含 .git／node_modules／venv／deploy_packages），資料庫一樣走 Online Backup；
     放開發機標記（`.no_email_send`、`.no_cloud_archive`）；補一份今天的本機快照（開發機的 V9 沒有每日排程，預檢要求今天或昨天有 `.done`）。
  3. 新版程式：`--package`（build_deploy_package.ps1 打出來的部署包）；沒給 ⇒ `git archive <--new-rev>`（報告會註明不是部署包）。
  4. 升級：預檢 → 備份＋試還原 → 轉換 → 驗證（新版啟動 ping）。
  5. 冒煙：在轉換後的目錄啟動新版，用演練專用的超級管理員登入，逐一打主要頁面與 API（報價、案件、傳票、獎金、出納、報表、模組管理、自訂模組）；
     同一個服務上驗**缺席明說**（S-1，`explain_absence`）：availability＝已安裝模組、INTEGRATION-POINTS「對方不在時」的說明、
     L1 頁面 200、無參數 GET 全掃不回 5xx。
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
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import upgrade as T  # noqa: E402
import upgrade_drill as UD  # noqa: E402
U = T.U

DEFAULT_V9 = r"C:\Users\hichan\Desktop\MOTRIX-ERP"
DEFAULT_ROOT = r"D:\開發測試檔\MOTRIX-FINAL-DRILL"  # 2026-09-29 使用者：開發測試目錄不直接建在 D 槽根目錄
_SKIP_DIRS = {".git", "node_modules", "__pycache__", "deploy_packages", ".pytest_cache"}
_DB_SUFFIXES = (".db", ".db-wal", ".db-shm", ".db-journal")
#: 冒煙收到 428 ＝ 本公司資料閘門擋住（演練設定有誤），不是產品端點壞了；報告要分開寫
GATE_428 = "428 company_setup_required：本公司資料閘門未通過（演練設定問題，非端點錯誤）"
DRILL_ADMIN = ("final_drill_admin", "Final-Drill-Pass-2026!")

#: 冒煙（D7-CHECKLIST §4，主持 2026-09-26）：分兩部分。
#: ①**共用清單** SMOKE：只放 L1 與「還沒搬進 modules/」的功能（它們一定在包內），(名稱, 方法, 路徑)，200 才算過；
#:   不可以放任何已搬遷模組的路徑（守門：test_smoke_core_has_no_paths_of_migrated_modules——原本寫死的
#:   /pages/bonus.html 沒帶 key，payroll 搬走後 core-only 必紅，第 7 次前哨抓到）。功能搬進模組時，把它的條目從這裡拿掉、
#:   改在該模組的 module.json 宣告 provides.probes。
#: ②**模組部分**由安裝包裡的 modules/<key>/module.json 產生：provides.probes（GET）＋pages（/pages/<path>）。
#:   modules.json 登記了、包裡沒有 ⇒「不在安裝包」（合法略過，明列）；包裡有、沒宣告 probes ⇒ 判不過
#:   （沒宣告的模組不可以進正式 D7）；包裡有、key 沒登記 ⇒ 判不過（打錯字或改名）。
SMOKE = [
    ("首頁", "GET", "/"), ("登入頁", "GET", "/pages/login.html"),
    ("模組管理", "GET", "/api/system/modules"), ("自訂模組清單", "GET", "/api/custom-modules"),
    ("版本", "GET", "/api/system/version"),
    ("定義文件庫", "GET", "/api/definitions/custom_module"),         # 第二批（P8 缺口 #5）已合回
]
# 2026-09-26（A，M06 搬遷）：「傳票列表 /api/vouchers」「傳票頁 /pages/voucher.html」拿掉，改由 modules/accounting/module.json
#   的 provides.probes＋pages 產生（本表不可以放已搬遷模組的路徑）。
# 2026-09-27（C，M01 ②搬遷；第十二班列車）：「報價單列表 /api/quotations」「案件管理頁 /pages/case-management.html」
#   同理拿掉，改由 modules/case/module.json 的 provides.probes＋pages 產生。
# 〔更正 2026-09-26 主持〕原本的「出納待付 /api/cashier/payable-queue」拿掉：它在 M04 不在時依 IP-14 設計回 404
# （附 CONTRACTOR_MISSING 說明），不是「一定 200」的共用項；M05 搬遷時由 M05 宣告自己的 probes。


#: 模組 key 的登記表（repo 層級，與「這棵樹裡有沒有那個資料夾」無關）
MODULES_JSON = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                            "docs", "platform", "modules.json")
UNREGISTERED = "未在 docs/platform/modules.json 登記"
UNDECLARED = "沒有宣告 provides.probes（不可以進正式 D7，D7-CHECKLIST §4）"
ABSENT = "不在安裝包"
NOT_MIGRATED = "尚未搬進 modules/（以 L1 形式在包內，由共用清單涵蓋）"


def registered_module_keys(path=None) -> set:
    with open(path or MODULES_JSON, encoding="utf-8") as f:
        data = json.load(f)
    return {g.get("key") for g in (data.get("modules") or {}).values() if g.get("key")}


def migrated_module_keys(path=None) -> set:
    """已搬進 modules/ 的模組 key：modules.json 群組有 key、而且單位含 `mod:`（與 check_group_keys 同判準）。
    有 key 但還沒有 mod: 單位的（M01、M03、M05、M06 在搬遷前）是「尚未搬遷」，不是「不在安裝包」（D 稽核 S-1）。"""
    with open(path or MODULES_JSON, encoding="utf-8") as f:
        data = json.load(f)
    return {g.get("key") for g in (data.get("modules") or {}).values()
            if g.get("key") and any(str(u).startswith("mod:") for u in g.get("units") or [])}


def smoke_plan(backend_dir: str, registered=None, migrated=None) -> list:
    """⇒ [(名稱, 方法, 路徑, 略過原因或 None)]：共用清單 SMOKE＋包內每個模組的 probes 與頁面＋登記了卻不在包內的模組。
    略過原因含 UNREGISTERED 或 UNDECLARED 的，smoke_ok 判不過（不是合法的略過）；含 ABSENT 的是合法略過（明列）。"""
    registered = registered_module_keys() if registered is None else set(registered)
    plan = [(name, method, path, None) for name, method, path in SMOKE]
    mods = os.path.join(backend_dir, "modules")
    present = sorted(d for d in (os.listdir(mods) if os.path.isdir(mods) else [])
                     if os.path.isfile(os.path.join(mods, d, "module.json")))
    for key in present:
        if key not in registered:
            plan.append(("模組 %s" % key, "GET", "modules/%s" % key, "模組 key %s %s" % (key, UNREGISTERED)))
            continue
        with open(os.path.join(mods, key, "module.json"), encoding="utf-8") as f:
            m = json.load(f)
        probes = (m.get("provides") or {}).get("probes") or []
        if not probes:
            plan.append(("模組 %s" % key, "GET", "modules/%s" % key, "模組 %s %s" % (key, UNDECLARED)))
        for path in probes:
            plan.append(("%s：%s" % (key, path), "GET", path, None))
        for pg in m.get("pages") or []:
            plan.append(("%s 頁面 %s" % (key, pg["path"]), "GET", "/pages/" + pg["path"], None))
    migrated = migrated_module_keys() if migrated is None else set(migrated)
    for key in sorted(registered - set(present)):
        why = ABSENT if key in migrated else NOT_MIGRATED
        plan.append(("模組 %s" % key, "GET", "modules/%s" % key, "模組 %s %s" % (key, why)))
    return plan


#: 缺席模組的宣告從哪裡讀：產生安裝包的那棵 repo（包裡已經沒有那個模組的 module.json）
SOURCE_MODULES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                              "backend", "modules")
NO_SOURCE_DECL = "不在安裝包，但來源樹也找不到它的 module.json ⇒ 無法驗證缺席時回 404"
EMPTY_DECL = "不在安裝包，而它的 module.json 沒有宣告任何 probes 或頁面 ⇒ 缺席時沒有東西可驗（稽核 D 建議：空宣告判紅）"


def absent_probe_plan(backend_dir: str, source_modules=None, registered=None, migrated=None) -> list:
    """「不在安裝包」（已搬遷、登記了、包裡沒有）的模組 ⇒ 它在來源樹 module.json 宣告的 probes 與頁面，每一項**期望 404**。
    ⇒ [(名稱, 方法, 路徑, 期望狀態碼)]；來源樹找不到宣告 ⇒ 期望狀態碼放 None（smoke 判不過，NO_SOURCE_DECL）。
    〔主持裁示（D7 前哨第 8 次觀察）：原本這些模組只列成合法略過，沒有實際打，D7-CHECKLIST §3 要求 probes／removed_pages 回 404〕
    尚未搬遷（NOT_MIGRATED）的不在這裡：它們以 L1 形式在包內，由共用清單涵蓋。"""
    registered = registered_module_keys() if registered is None else set(registered)
    migrated = migrated_module_keys() if migrated is None else set(migrated)
    source_modules = SOURCE_MODULES if source_modules is None else source_modules
    mods = os.path.join(backend_dir, "modules")
    present = {d for d in (os.listdir(mods) if os.path.isdir(mods) else [])
               if os.path.isfile(os.path.join(mods, d, "module.json"))}
    plan = []
    for key in sorted((registered & migrated) - present):
        decl = os.path.join(source_modules, key, "module.json")
        if not os.path.isfile(decl):
            plan.append(("缺席模組 %s" % key, "GET", "modules/%s" % key, None))
            continue
        with open(decl, encoding="utf-8") as f:
            m = json.load(f)
        probes = (m.get("provides") or {}).get("probes") or []
        pages = m.get("pages") or []
        if not probes and not pages:
            plan.append(("缺席模組 %s（空宣告）" % key, "GET", "modules/%s" % key, None))
            continue
        for path in probes:
            plan.append(("缺席 %s：%s" % (key, path), "GET", path, 404))
        for pg in pages:
            plan.append(("缺席 %s 頁面 %s" % (key, pg["path"]), "GET", "/pages/" + pg["path"], 404))
    return plan


# ── 缺席明說（S-1：FINAL-DRILL-REPORT §5、AUDIT-D-D7-drill §4；原本只在臨時腳本 d7-tools\d7_extra.py）──────────────
# 冒煙那一步的服務上（V9 真實資料轉換後）再驗三件事：①L1 在模組缺席時明說（availability＋INTEGRATION-POINTS「對方不在時」）；
# ②L1 頁面 200；③無路徑參數的 GET 全掃不回 5xx。
# 🔴 兩條判準照 D 2b8afa60 審定（第一版 d7_extra 寫錯過、造成假紅，不可以改回去）：
#   1. availability 只列安裝包內的模組：清單的 key 必須＝已安裝模組、而且都 loaded；**缺席的 key 不在清單裡才對**
#      （system.py docstring、STATES-PLATFORM P-FE-02；缺席的明說由 P-FE-03 與缺席 404 負責，不是這支端點）。
#   2. IP-98（應收應付的收入項）只在**現金口徑**（basis=cash）用得到；權責口徑不用 arap（INTEGRATION-POINTS IP-98 原文），
#      不可以在權責口徑要求「應收應付模組未安裝」。

#: 全掃排除：會連外、長連線、會觸發備份／寄信／封存、或產大檔（與 d7_extra 相同）
CRAWL_EXCLUDE = ("backup", "cloud", "archive", "mail", "email", "send", "geocod", "/api/map", "stream", "events",
                 "sse", "restart", "shutdown", "update-check", "deploy", "sync", "download", "/pdf", "excel",
                 "export", "print", "reminder-run", "run-now", "self-test", "selftest", "diagnos", "cert", "logs/tail",
                 "nominatim", "weather", "tender")
_EXPENSES = "/api/reports/expenses-monthly?year=2026&month=2026-09&basis="
ARAP_ABSENT = "應收應付模組未安裝"


def installed_modules(backend_dir: str) -> tuple:
    """⇒ (模組 key 的集合, 來源)。安裝包有 `modules.lock.json` ⇒ 以它為準（建包時選配的結果）；沒有（git archive 模式）
    ⇒ 包內有 module.json 的資料夾。這是獨立於被檢查端點的訊號（§G5 #15）：availability 的判準拿它來比，不拿端點自己的回應。"""
    lock = os.path.join(backend_dir, "modules.lock.json")
    if os.path.isfile(lock):
        with open(lock, encoding="utf-8-sig") as f:
            return set((json.load(f).get("modules") or {})), "modules.lock.json"
    mods = os.path.join(backend_dir, "modules")
    return ({d for d in (os.listdir(mods) if os.path.isdir(mods) else [])
             if os.path.isfile(os.path.join(mods, d, "module.json"))}, "modules/ 資料夾")


def explain_plan(present, first_quote=None) -> list:
    """⇒ [(IP, 說明, 路徑, 期望狀態碼, [回應必須含的字串])]；只列適用於這個選配的條（依 INTEGRATION-POINTS「對方不在時」）。
    full（全部在）⇒ 空清單。需要單號的條（IP-12、IP-15/18/22）在庫裡沒有報價單時：IP-12 用不存在的單號（案件缺席時
    查無與缺席同一個 404 說明），IP-15/18/22 不列。"""
    present = set(present)
    P = lambda k: k in present  # noqa: E731
    A = lambda k: k not in present  # noqa: E731
    out = []
    if A("payroll"):
        out.append(("IP-16", "L1 獎金入口：薪資獎金缺席", "/api/system/bonus-module-status", 200,
                    ['"enabled":false', "薪資獎金模組未安裝"]))
    if A("case"):
        out.append(("IP-91", "L1 報價預設條款：案件缺席", "/api/settings/quote-terms-defaults", 404, ["案件模組未安裝"]))
    if P("arap") and A("subcontract"):
        out.append(("IP-14", "出納待付：外包工班缺席", "/api/cashier/payable-queue", 404, ["外包工班模組未安裝"]))
    if P("arap") and A("payroll"):
        out.append(("IP-8", "出納獎金佇列：薪資獎金缺席", "/api/cashier/bonus-queue", 200,
                    ['"available":false', "薪資獎金模組未安裝"]))
    if P("analytics") and A("arap"):
        out.append(("IP-99", "稅務匯出：應收應付缺席", "/api/reports/tax-export?year=2026", 404, [ARAP_ABSENT]))
        # 判準 2：只在現金口徑要求（權責口徑不用 arap）
        out.append(("IP-98", "支出／收入報表（現金口徑）：應收應付缺席", _EXPENSES + "cash", 200, [ARAP_ABSENT]))
    if P("analytics") and A("case"):
        out.append(("IP-95", "支出／收入報表（權責口徑）：案件缺席", _EXPENSES + "accrual", 200, ["案件模組未安裝"]))
    if P("analytics") and P("case") and A("subcontract"):
        out.append(("IP-1", "支出報表：外包工班缺席", _EXPENSES + "accrual", 200, ["外包工班模組未安裝"]))
    if P("netplan") and A("case"):
        out.append(("IP-12", "規劃書依案件查詢：案件缺席",
                    "/api/quotations/%s/network-plan" % urllib.parse.quote(first_quote or "Q-NONE"), 404, ["案件模組未安裝"]))
    if P("accounting"):
        need = [msg for key, msg in (("subcontract", "外包工班模組未安裝"), ("arap", ARAP_ABSENT),
                                     ("supply", "採購・庫存・出貨模組未安裝")) if A(key)]
        if need:
            out.append(("IP-14/99/20", "T100 預覽：來源模組缺席",
                        "/api/reports/t100-export/preview?start=2026-01-01&end=2026-09-30", 200, need))
    if P("case") and first_quote:
        need = [msg for key, msg in (("subcontract", "外包工班模組未安裝"), ("supply", "採購・庫存・出貨模組未安裝"),
                                     ("accounting", "會計傳票模組未安裝")) if A(key)]
        if need:
            out.append(("IP-15/18/22", "案件整包：各段缺席",
                        "/api/quotations/%s/case-bundle" % urllib.parse.quote(first_quote), 200, need))
    if P("payroll") and A("accounting"):
        out.append(("IP-2", "獎金傳票科目：會計缺席", "/api/bonus/cases/voucher-accounts", 200, ["會計模組未安裝"]))
    return out


def ip98_basis_violations(plan) -> list:
    """判準 2 的守門：要求「應收應付模組未安裝」的 expenses-monthly 條目，口徑必須是 cash ⇒ 違反的條目清單。"""
    return [row for row in plan if row[2].startswith(_EXPENSES) and ARAP_ABSENT in row[4]
            and not row[2].endswith("basis=cash")]


def availability_verdict(status, body: str, present) -> dict:
    """判準 1：清單的 key＝已安裝模組、而且都 loaded。缺席的 key **不在**清單裡才對（P-FE-02）。"""
    present = set(present)
    out = {"status": status}
    try:
        j = json.loads(body)
    except (TypeError, ValueError):
        out.update(ok=False, body=str(body)[:300])
        return out
    keys = set(j) if isinstance(j, dict) else set()
    not_loaded = sorted(k for k, v in (j.items() if isinstance(j, dict) else ())
                        if not isinstance(v, dict) or v.get("state") != "loaded")
    out["keys_vs_installed"] = {"extra": sorted(keys - present), "missing": sorted(present - keys)}
    out["not_loaded"] = not_loaded
    out["ok"] = status == 200 and isinstance(j, dict) and keys == present and not not_loaded
    return out


def absence_verdict(status, body: str, expect, needles) -> dict:
    """狀態碼等於期望、而且回應含每一句說明（忽略空白：JSON 序列化的 `": "` 與 `":"` 都算）。"""
    compact = str(body).replace(" ", "")
    lacking = [n for n in needles if n.replace(" ", "") not in compact]
    return {"status": status, "expect": expect, "lacking": lacking, "ok": status == expect and not lacking}


def _get(base, path, token=None, timeout=30):
    """⇒ (狀態碼, 本文)；連線失敗 ⇒ (例外名稱, 訊息)（不是 int，判定一律不過）。"""
    r = urllib.request.Request(base + path, headers={"Authorization": "Bearer " + token} if token else {})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:                                      # noqa: BLE001
        return type(e).__name__, str(e)


def _first_quote(backend_dir: str):
    """庫裡最新一張報價單的單號（唯讀連線）；沒有表或沒有資料 ⇒ None。"""
    db = os.path.join(backend_dir, "motrix_erp.db")
    if not os.path.isfile(db):
        return None
    try:
        c = sqlite3.connect("file:%s?mode=ro" % Path(db).as_posix(), uri=True)
    except sqlite3.Error:
        return None
    try:
        row = c.execute("SELECT quote_no FROM quotations WHERE quote_no IS NOT NULL AND quote_no<>'' "
                        "ORDER BY id DESC LIMIT 1").fetchone()
    except sqlite3.Error:
        row = None
    finally:
        c.close()
    return row[0] if row else None


def explain_absence(base: str, token: str, backend_dir: str) -> dict:
    """在跑著的新版上驗缺席明說（S-1）。⇒ {installed, availability, absence, pages, crawl, ok}。"""
    present, source = installed_modules(backend_dir)
    first_quote = _first_quote(backend_dir)
    out = {"installed": sorted(present), "installed_from": source, "first_quote": first_quote}
    s, b = _get(base, "/api/system/modules/availability", token)
    out["availability"] = availability_verdict(s, b, present)
    out["absence"] = []
    for ip, name, path, expect, needles in explain_plan(present, first_quote):
        s, b = _get(base, path, token)
        out["absence"].append({"ip": ip, "name": name, "path": path, **absence_verdict(s, b, expect, needles),
                               "body": b[:400]})
    with open(os.path.join(backend_dir, "core", "l1_pages.json"), encoding="utf-8-sig") as f:
        l1 = json.load(f)
    out["pages"] = []
    for p in (l1.get("pages") if isinstance(l1, dict) else l1) or []:
        pth = p if isinstance(p, str) else (p.get("path") or p.get("page"))
        if not pth:
            continue
        url = pth if pth.startswith("/") else "/pages/" + pth
        s, _b = _get(base, url)
        out["pages"].append({"path": url, "status": s, "ok": s == 200})
    s, b = _get(base, "/openapi.json", token)
    crawl = {"openapi": s, "checked": 0, "excluded": [], "by_status": {}, "bad": []}
    if s == 200:
        for path, ops in sorted(json.loads(b).get("paths", {}).items()):
            if "get" not in ops or "{" in path:
                continue
            if any(x in path.lower() for x in CRAWL_EXCLUDE):
                crawl["excluded"].append(path)
                continue
            s2, b2 = _get(base, path, token, timeout=20)
            crawl["checked"] += 1
            crawl["by_status"][str(s2)] = crawl["by_status"].get(str(s2), 0) + 1
            if not isinstance(s2, int) or s2 >= 500:
                crawl["bad"].append({"path": path, "status": s2, "body": b2[:300]})
    crawl["ok"] = s == 200 and crawl["checked"] > 0 and not crawl["bad"]
    out["crawl"] = crawl
    out["ok"] = explain_ok(out)
    return out


def explain_ok(out) -> bool:
    """四項都要有結果而且通過；少了任何一項（沒跑到）⇒ 不過，不是當成沒事。L1 頁面必須至少一頁。"""
    return (bool((out.get("availability") or {}).get("ok"))
            and isinstance(out.get("absence"), list) and all(x.get("ok") for x in out["absence"])
            and bool(out.get("pages")) and all(x.get("ok") for x in out["pages"])
            and bool((out.get("crawl") or {}).get("ok")))


def smoke_verdict(out) -> bool:
    """冒煙整體：原本的 smoke_ok，**而且**缺席明說通過；沒有 explain（沒跑到）⇒ 不過。"""
    return smoke_ok(out) and bool((out.get("explain") or {}).get("ok"))


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


def ensure_drill_company(install: str) -> dict:
    """演練複本的本公司資料確認（E4 閘門，COMPANY-SETUP-GATE）：沒有確認紀錄 ⇒ 白名單外的 /api 一律 428，冒煙全紅。
    只寫演練複本的庫與識別檔（完整回滾會還原庫）；用非開發者、非示範的虛構公司＋通過檢查碼的統編。
    舊程式（沒有 helpers/company_setup.py）⇒ 回 skipped，不當作失敗。"""
    backend = os.path.join(install, "backend")
    if not os.path.isfile(os.path.join(backend, "helpers", "company_setup.py")):
        return {"skipped": "這份程式沒有本公司資料閘門"}
    code = ("import json,sqlite3;from helpers import company_setup as C;"
            "tax=next('%%08d'%%n for n in range(10000000,10001000) if C.ubn_valid('%%08d'%%n));"
            "c=sqlite3.connect('motrix_erp.db');"
            "C._set(c,'company_profile',{'name':'演練測試有限公司','tax_id':tax,'contact_info':'Tel: 02-0000-0000 final-drill@example.invalid'});"
            "r=C.confirm(c,%r);c.commit();"
            "print(json.dumps({'tax':tax,'via':r['via'],'gate':C.status(c).get('configured')}))" % DRILL_ADMIN[0])
    out = json.loads(_py_in(backend, code).splitlines()[-1])
    assert out["gate"], "演練公司資料確認後閘門仍未通過：%s" % out
    return out


def schema_gap(v9_backend: str, new_backend: str) -> dict:
    """V9 程式的 schema 版本（db.CURRENT_VERSION）對照新版認得的 V9 基準（db.V9_BASELINE）。
    V9 > 基準 ⇒ V9 啟動（完整回滾後的 6a）會把庫升到 V9 的版本，之後新版 init_db 以 SchemaNewerThanBaseline 拒絕（第 6b 步），
    成因是 V9 維護期新增的 migration 沒有同號追進新版 db._MIGRATIONS。只讀兩份 db.py 文字，不 import。"""
    def num(path, name):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                m = re.search(r"^%s\s*=\s*(\d+)" % name, f.read(), re.M)
            return int(m.group(1)) if m else None
        except OSError:
            return None
    v9 = num(os.path.join(v9_backend, "db.py"), "CURRENT_VERSION")
    base = num(os.path.join(new_backend, "db.py"), "V9_BASELINE")
    out = {"v9_current_version": v9, "new_v9_baseline": base}
    out["ok"] = v9 is not None and base is not None and v9 <= base
    if not out["ok"]:
        out["reason"] = ("讀不到版本號" if v9 is None or base is None else
                         "V9 程式 schema v%d > 新版基準 v%d：V9 的 migration %d～%d 沒有追進新版 db._MIGRATIONS；"
                         "第 6a 步 V9 啟動會把庫升到 v%d，第 6b 步再轉換會被拒絕" % (v9, base, base + 1, v9, v9))
    return out


def smoke(install: str) -> dict:
    port = UD.free_port()
    # 演練自己起的服務要開 API 文件（GET 全掃靠 /openapi.json 列路徑）；正式機預設關（main.MOTRIX_API_DOCS）
    env = {**os.environ, **T.SAFE_ENV, "MOTRIX_API_DOCS": "1"}
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
            out["checks"].append({"name": name, "path": path, "status": code, "ok": code == 200,
                                  **({"reason": GATE_428} if code == 428 else {})})
        for name, method, path, expect in absent_probe_plan(os.path.join(install, "backend")):
            if expect is None:
                out["checks"].append({"name": name, "path": path, "status": None, "expect": 404, "ok": False,
                                      "reason": EMPTY_DECL if "空宣告" in name else NO_SOURCE_DECL})
                continue
            r = urllib.request.Request(base + path, method=method, headers={"Authorization": "Bearer " + token})
            try:
                code = urllib.request.urlopen(r, timeout=30).status
            except urllib.error.HTTPError as e:
                code = e.code
            except Exception as e:                              # noqa: BLE001
                code = "%s" % type(e).__name__
            out["checks"].append({"name": name, "path": path, "status": code, "expect": expect, "ok": code == expect})
        out["explain"] = explain_absence(base, token, os.path.join(install, "backend"))      # S-1 缺席明說
    finally:
        T._stop(proc)
        log.close()
    out["ok"] = smoke_verdict(out)
    for c in out["checks"]:                                  # 報告摘要只留 400 字 ⇒ 紅的項目在輸出裡逐項印出
        if not c["ok"]:
            print("[D7]   冒煙紅：%s %s ⇒ %s%s" % (c["name"], c["path"], c["status"], "（%s）" % c["reason"] if c.get("reason") else ""), flush=True)
    return out


def smoke_ok(out) -> bool:
    """有檢查、每一項 200、而且沒有「key 未登記」或「沒宣告 probes」的條目（那不是合法的略過）。"""
    bad = [s for s in out.get("skipped", []) if UNREGISTERED in s.get("reason", "") or UNDECLARED in s.get("reason", "")]
    if bad:
        out["unregistered_skips"] = bad
    return bool(out["checks"]) and all(c["ok"] for c in out["checks"]) and not bad


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


def explain_report_lines(rep: dict) -> list:
    """冒煙那一步的缺席明說（S-1）展開成報告段落（上表摘要只留 400 字，會被截掉）。沒跑到 ⇒ 明寫沒跑到。"""
    smoke_steps = [s for s in rep.get("steps", []) if s.get("name", "").startswith("5 ")]
    if not smoke_steps:
        return []
    ex = smoke_steps[-1].get("explain")
    lines = ["## 缺席明說（S-1）", ""]
    if not ex:
        return lines + ["**沒有結果**（冒煙在缺席明說之前就失敗了）⇒ 本項未驗。", ""]
    av = ex.get("availability") or {}
    lines += ["- 已安裝模組（%s）：%s" % (ex.get("installed_from"), ", ".join(ex.get("installed") or []) or "（無）"),
              "- availability：%s（%s）" % ("✅" if av.get("ok") else "❌",
                                            json.dumps({k: av.get(k) for k in ("status", "keys_vs_installed", "not_loaded")},
                                                       ensure_ascii=False)),
              "- L1 頁面：%d 頁，不過 %d" % (len(ex.get("pages") or []), sum(1 for p in ex.get("pages") or [] if not p.get("ok"))),
              "- 無參數 GET 全掃：%s" % json.dumps({k: (ex.get("crawl") or {}).get(k) for k in ("checked", "by_status", "bad")},
                                                   ensure_ascii=False)]
    rows = ex.get("absence") or []
    if rows:
        lines += ["", "| IP | 說明 | 路徑 | 狀態（期望） | 缺少的說明 | 結果 |", "|---|---|---|---|---|---|"]
        lines += ["| %s | %s | `%s` | %s（%s） | %s | %s |" % (r["ip"], r["name"], r["path"], r["status"], r["expect"],
                                                          "、".join(r["lacking"]) or "—", "✅" if r["ok"] else "❌")
                  for r in rows]
    else:
        lines += ["- INTEGRATION-POINTS 缺席條目：這個選配沒有適用的條（全部模組都在）"]
    return lines + [""]


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
    lines += explain_report_lines(rep)
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
        with step(rep, "3b V9 schema 對照新版基準") as s:        # 不停止：後面的步驟仍要跑，總判定照紅
            s.update(schema_gap(os.path.join(install, "backend"), os.path.join(new_src, "backend")))
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
            s["drill_company"] = ensure_drill_company(install)
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
    try:                                                              # 背景執行不彈視窗（tools/platform/nowindow.py；MOTRIX_SHOW_WINDOWS=1 可關）
        import sys as _s, pathlib as _p
        _s.path.insert(0, str(_p.Path(__file__).resolve().parents[0]))
        import nowindow as _nw
        _nw.install()
    except ImportError:
        pass
    sys.exit(main())
