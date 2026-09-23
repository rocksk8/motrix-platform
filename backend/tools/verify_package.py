# -*- coding: utf-8 -*-
"""驗包：同一個比對器，先在工作樹跑正對照，再在包上跑。

原作 D（`rg6.py`，2026-09-22），本檔為落地版。**六項修正見下方「與 rg6 的差異」。**

## 為什麼要同一支跑兩邊

「包裡 0 個命中」有兩種成因 —— (a) 包是乾淨的 (b) **我的掃描壞了／指錯根目錄**。
分辨它們的唯一辦法，是同一個比對器**在已知有東西的地方先命中**。
⇒ 正對照沒過，整份報告作廢，**不得解讀包側的 0**。

## 與 `rg6.py` 的差異（A 列四項、D 加兩項）

```
① 寫死的 WT 路徑        ⇒ 從 __file__ 往上推兩層（本檔住在 backend/tools/）
② 會漂移的門檻          ⇒ db>=40／backend 根層 db>=3 改成**逐一列具名檔**
                          ☠️ 數量門檻一增減就失真，**而失真方向是變得更容易通過**
③ 讀包不讀工作樹        ⇒ 判準只看包裡那一份；工作樹那一份**只用來比對**
④ == expected version   ⇒ 新增 --expect-db-version，不一致就 FAIL
⑤ 🔴 永遠 exit 0         ⇒ 收集 FAIL，最後 sys.exit(1)
                          ☠️「印了紅字而回 0」= 當守門用時它永遠不會擋住任何東西
⑥ 🔴 PROVENANCE 缺檔 return ⇒ 改成記一筆 FAIL 然後**繼續跑**
                          ☠️ 一個缺檔會讓後面的擋關**安靜消失**
```

## 📌 四件是刻意的，改的時候不要拿掉

```
· 兩次掃描的**排除清單不同**是刻意的：工作樹要排掉 deploy_packages/（否則包中有包），
  包側不排除任何東西（判準是「檔案在不在包裡」）
  ⇒ 報告逐字印出兩次的根目錄與排除清單，**不可以寫成「完全相同的掃描」**
· `_demo_` 用**路徑分段**比對不是子字串
  （子字串會把 test_upload_demo_isolation.py 誤判成 _demo_ 目錄，實測踩到過）
· PROVENANCE 解析**逐行定錨行首**
  （早一版貪婪的 [^0-9a-fA-F]{0,60} 吃掉檔名首字 → 鍵變 eaflet.js → 五個檔全被誤判）
· 空目錄 `os.walk` 走不到 ⇒ backend/_demo_* 要用目錄列舉另算

用法:
    python verify_package.py [<包目錄>] [--expect-db-version 92]
    省略包目錄則取最新一包。
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── ① 不寫死路徑：本檔住在 <repo>/backend/tools/ ─────────────────
#    ⚠️ 用 realpath 先解開 symlink，否則從別處連結過來時會往上推到錯的地方。
WT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
PKGROOT = os.path.join(WT, "deploy_packages")

WT_SKIP = {".git", "deploy_packages", "node_modules", "__pycache__", ".venv", "venv"}
PKG_SKIP = set()          # 包側不排除任何東西：判準是「檔案在不在包裡」


# ══════════════════════════════════════════════════════════════════
# ⑤ FAIL 收集器 —— 沒有它，這支腳本印了紅字還是回 0
# ══════════════════════════════════════════════════════════════════
class Report(object):
    """收集失敗，最後決定結束碼。

    🔑 〈修檔腳本要有 assert〉：**印成功訊息與真的成功是兩件事。**
    ☠️ `rg6.py` 整支沒有任何 `sys.exit()` ⇒ 當守門用時它永遠不擋東西 ——
       而「有一道守門」與「有一道永遠回綠的守門」在流程圖上長得一模一樣。
    """

    def __init__(self):
        self.fails = []
        self.voided = False        # 正對照沒過 ⇒ 包側結論不可解讀

    def fail(self, gate, detail):
        self.fails.append((gate, detail))
        print("  🔴 FAIL  %s —— %s" % (gate, detail))

    def void(self, why):
        self.voided = True
        self.fail("正對照", why)

    def finish(self):
        print()
        print("=" * 74)
        if self.voided:
            print("🔴 正對照不成立 ⇒ **整份報告作廢**，包側的數字不論多少都不可解讀。")
        if not self.fails:
            print("✅ 全部通過（0 項 FAIL）")
            return 0
        print("🔴 共 %d 項 FAIL：" % len(self.fails))
        for gate, detail in self.fails:
            print("   · %-28s %s" % (gate, detail))
        return 1


R = Report()


def _ext(*exts):
    return lambda rel, name: name.lower().endswith(exts)


# ---- 不該出現的：代號, 說明, 比對函式 ----
BAD = [
    ("db-sqlite", "資料庫檔", _ext(".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3")),
    ("pem-key-crt", "憑證／私鑰", _ext(".pem", ".key", ".crt", ".pfx", ".p12")),
    ("private_key", "檔名含 private_key",
     lambda r, n: "private_key" in n.lower()),
    ("license.key", "授權金鑰檔", lambda r, n: n.lower() == "license.key"),
    ("certs-dir", "certs/ 目錄下",
     lambda r, n: re.search(r"(^|[\\/])certs[\\/]", r, re.I) is not None),
    # ⚠️ 必須比對「路徑分段」而非子字串：子字串會把
    #    test_upload_demo_isolation.py 誤判成 _demo_ 目錄（實測踩到過）
    ("_demo_", "_demo_ 目錄",
     lambda r, n: any(seg.lower().startswith("_demo_")
                      for seg in re.split(r"[\\/]", r))),
    ("logs-dir", "logs/ 目錄下",
     lambda r, n: any(seg.lower() == "logs" for seg in re.split(r"[\\/]", r)[:-1])),
    ("log-file", "*.log 檔（任何位置）", lambda r, n: n.lower().endswith(".log")),
    ("dotenv", ".env 檔",
     lambda r, n: n.lower() == ".env" or n.lower().startswith(".env.")),
    ("pycache", "__pycache__", lambda r, n: "__pycache__" in r.lower()),
]

# ---- 不該給客戶的「能力」（不是檔案欄）----
CAPABILITY = {
    "deploy_dashboard.py": "未認證的 POST /api/deploy + /api/rollback",
    "deploy_dashboard.html": "上面那支的前端",
    "issue_license.py": "授權簽發器（產品裡放發證機）",
    "build_deploy_package.ps1": "打包器",
    "apply_update.ps1": "更新器（本案設計上必須在）",
}
INTERNAL_DOC = [
    "MULTIWIN-PROTOCOL.md", "AGENT-HANDOFF-TEMPLATE.md", "GITFLOW.md",
    "DR-SOP.md", "MOTRIX-ERP-ARCHITECTURE-MAP.md",
]
MUST_EXIST = ["autostart.bat", "DEPLOY.md"]

# ══════════════════════════════════════════════════════════════════
# ② 正對照：**逐一列具名檔**，不用數量門檻
# ══════════════════════════════════════════════════════════════════
# ☠️ rg6 原本用 `db 總數 >= 40`／`backend 根層 db >= 3`。那是「今天這棵樹的
#    數字」—— `db_backups/` 一增減它就失真，**而失真的方向是變得更容易通過**
#    （多一個備份就永遠 PASS）⇒ 〈判準的寬窄都會騙人〉裡「太寬」的那一側。
# 🔑 改成點名：每一個都必須被**對應的那條規則**抓到，少一個就作廢。
#
# ⚠️ **這些是真實的開發檔，不是誘餌** —— 它們哪一天被搬走或改名，正對照
#    就會失效，而失效的樣子是「報告作廢」不是「安靜放行」（方向是安全的）。
#    📌 D 的下一件事是放**故意留著的誘餌**並把正對照改釘在誘餌上
#       ——〈盤點工具的正對照〉：正對照釘在真檔案上，真檔案消失那天它就失效。
POSITIVE_CONTROL = [
    # (要被哪條規則抓到, 相對路徑（以 repo 根為準）)
    ("db-sqlite",   "motrix_erp.db"),
    ("db-sqlite",   os.path.join("backend", "motrix.db")),
    ("db-sqlite",   os.path.join("backend", "motrix_erp.db")),
    ("db-sqlite",   os.path.join("backend", "motrix_erp_demo.db")),
    ("private_key", os.path.join("backend", "tools",
                                 "_license_private_key_dev.pem")),
]


def walk(root, skip):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            yield os.path.relpath(full, root), fn, full


def scan(root, skip):
    print("=" * 74)
    print("掃描根目錄：%s" % root)
    print("排除清單  ：%s" % (", ".join(sorted(skip)) if skip
                              else "（無，不排除任何目錄）"))
    hits = dict((k, []) for k, _, _ in BAD)
    allrel = []
    for rel, name, _full in walk(root, skip):
        allrel.append(rel)
        for key, _desc, fn in BAD:
            if fn(rel, name):
                hits[key].append(rel)
    print("檔案總數  ：%d" % len(allrel))
    print("-" * 74)
    for key, desc, _ in BAD:
        print("  %-14s %-20s %5d" % (key, desc, len(hits[key])))
    return hits, allrel


def positive_control(wt_hits):
    """② 逐一列具名檔。**每一個都要被對應的規則抓到。**"""
    print("-" * 74)
    print("  正對照（逐一列具名檔，不用數量門檻）：")
    missing = []
    for rule, rel in POSITIVE_CONTROL:
        norm = rel.replace("/", os.sep).lower()
        found = any(h.lower() == norm for h in wt_hits[rule])
        print("    %-12s %-46s %s"
              % (rule, rel, "✅ 抓到" if found else "🔴 沒抓到"))
        if not found:
            missing.append("%s（應被 %s 抓到）" % (rel, rule))
    # 第三個鑑別維度：logs —— 用**存在性**不用數量（數量一樣會漂移）
    for rule, label in (("logs-dir", "logs/ 目錄下有檔案"),
                        ("log-file", "有 *.log 檔")):
        n = len(wt_hits[rule])
        print("    %-12s %-46s %s" % (rule, label,
                                      "✅ %d 個" % n if n else "🔴 一個都沒有"))
        if not n:
            missing.append(label)
    if missing:
        R.void("這些在工作樹裡應該被抓到卻沒抓到：" + "；".join(missing)
               + " ⇒ 掃描器可能壞了或指錯根目錄")
    else:
        print("  ⇒ ✅ 正對照成立，包側的數字可以解讀")
    return not missing


def _db_version_facts(path):
    """從一份 `db.py` 取三個**互相獨立**的版本來源。

    🔑 只印 `CURRENT_VERSION` 證明不了什麼 —— 那是一個整數，
    改它不需要真的加一支 migration（〈守門守的對象被搬走〉）。
    ⇒ 三個來源必須一致：
       ① `CURRENT_VERSION` 字面值
       ② `len(_MIGRATIONS)`
       ③ 最後一筆的函式名前綴 `_mNNN_`
    """
    with io.open(path, "r", encoding="utf-8", errors="replace") as fh:
        src = fh.read()
    out = {"path": path}
    m = re.search(r"^CURRENT_VERSION\s*=\s*(\d+)", src, re.M)
    out["current"] = int(m.group(1)) if m else None
    try:
        i = src.index("_MIGRATIONS = [")
        block = src[i:src.index("]", i)]
        entries = re.findall(r"^\s*(_m\d+_[A-Za-z0-9_]+)\s*,", block, re.M)
    except ValueError:
        entries = []
    out["count"] = len(entries)
    out["last"] = entries[-1] if entries else None
    mm = re.match(r"_m(\d+)_", out["last"] or "")
    out["last_num"] = int(mm.group(1)) if mm else None
    return out


def check_db_version(pkg, expect):
    """③④ 判準**只看包裡那一份**；工作樹那一份只用來比對。

    ## 🔴 `VP1`：沒給 `--expect-db-version` ⇒ **FAIL**，不是印個警告就算

    ☠️ 先前這裡只 `print` 一行警告然後繼續 ⇒ 摘要印「✅ 全部通過」、結束碼 0
    ⇒ **呼叫端忘了帶參數，那道版本擋關就安靜關掉，而管線全綠。**
    🔑 〈散文對工具是隱形的〉在這裡是字面上的：**那行 `print` 對呼叫端不存在**
       —— 自動化讀的是結束碼。
    ⚠️ 而它與 `P0-00` 是同一個形狀：**「新增一條路徑而忘記回報」是預設會發生的事。**

    ## ⚠️ **刻意沒有**「明著略過」的逃生口

    D 的原始規格有一條「明著略過版本比對」的旗標（降級為只驗三源一致）。
    ☠️ 而它是 `VP2`，不是 `VP1` —— A 裁 `VP2`–`VP4` 留在 `NEXT`，
    而 `test_vp2_vp3_the_unwritten_items_are_named_not_forgotten` 是一條**絆線**：
    它 grep 那個旗標的名字，**斷言它還不在這個檔裡**。
    ⚠️ 所以這段註解**刻意不寫出那個字**——我第一次寫的時候寫了，
       而絆線照樣紅：**它比對的是字面，分不出「實作」與「解釋它不存在的註解」**。
       📌 §6 那一條的同一個形狀：一個寫得好的註解，讓一個粗糙的比對產生假陽性。
    🔑 ⇒ 接縫出現的那一天它會紅，**逼人回來把那一項寫成真的題目**。
    ⚠️ **代價寫明**：在 `VP2` 落地之前，手動臨時查驗**也必須**帶
       `--expect-db-version`，沒有略過的辦法。那是刻意的。
    """
    pkg_db = os.path.join(pkg, "backend", "db.py")
    wt_db = os.path.join(WT, "backend", "db.py")

    if not os.path.isfile(pkg_db):
        R.fail("db 版本", "包裡沒有 backend/db.py（%s）" % pkg_db)
        return
    f = _db_version_facts(pkg_db)
    print("  包內    CURRENT_VERSION=%s  len(_MIGRATIONS)=%s  最後一筆=%s"
          % (f["current"], f["count"], f["last"]))
    consistent = (f["current"] is not None
                  and f["current"] == f["count"] == f["last_num"])
    if consistent:
        print("          三者一致 ✅")
    else:
        R.fail("db 版本三源一致",
               "包內 CURRENT_VERSION=%s／len=%s／最後一筆=%s 不一致"
               % (f["current"], f["count"], f["last"]))

    # ④ 與外部期望值比較
    if expect is None:
        # 📌 `deploy_manifest.json` **不帶 db 版本**（實查：只有 commit／branch／
        #    built_at／version_manifest_latest／durations_sec／tests／env）
        #    ⇒ 期望值只能由呼叫端給，這裡推不出來。
        R.fail("db 版本期望值未指定",
               "沒有給 --expect-db-version ⇒ 無從判斷包裡的 db.py 是不是"
               "應該的那個版本。（明著略過的選項是 VP2，尚未實作。）")
    elif f["current"] != expect:
        R.fail("db 版本 == 期望值",
               "包內是 %s，而期望是 %s" % (f["current"], expect))
    else:
        print("  包內版本 == 期望值 %s ✅" % expect)

    # ③ 工作樹**只用來比對**，不作為判準來源
    if not os.path.isfile(wt_db):
        print("  （工作樹沒有 backend/db.py，略過比對）")
        return
    b = _db_version_facts(wt_db)
    print("  工作樹  CURRENT_VERSION=%s  len(_MIGRATIONS)=%s  最後一筆=%s"
          "　← **只用來比對，不是判準來源**"
          % (b["current"], b["count"], b["last"]))
    same = ((f["current"], f["count"], f["last"])
            == (b["current"], b["count"], b["last"]))
    if same:
        print("  包 vs 工作樹：相同 ✅")
    else:
        # A 於凍結握手升為擋關：這不是資訊，是「包不是這棵樹打出來的」
        R.fail("包 vs 工作樹",
               "db.py 三源不同 ⇒ **這個包不是這棵樹打出來的**"
               "（守門跑在工作樹上、包的內容來自 git archive，兩邊都會說自己對）")


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("package", nargs="?", default=None,
                    help="包目錄；省略則取最新一包")
    ap.add_argument("--expect-db-version", type=int, default=None,
                    help="包內 db.py 的 CURRENT_VERSION 應該是多少（不給就 FAIL）")
    args = ap.parse_args()

    pkg = args.package
    if not pkg:
        if not os.path.isdir(PKGROOT):
            print("🔴 找不到 deploy_packages/：%s" % PKGROOT)
            sys.exit(1)
        names = sorted(os.listdir(PKGROOT))
        if not names:
            print("🔴 deploy_packages/ 是空的")
            sys.exit(1)
        pkg = os.path.join(PKGROOT, names[-1])
    if not os.path.isdir(pkg):
        print("🔴 包目錄不存在：%s" % pkg)
        sys.exit(1)

    print("repo 根：%s　（從 __file__ 往上推兩層，不是寫死的）" % WT)
    print("受測包：%s" % pkg)
    print()

    print("### (1) 正對照（工作樹）—— 沒過則整份作廢")
    wt_hits, _ = scan(WT, WT_SKIP)
    positive_control(wt_hits)
    # 空目錄 os.walk 走不到檔案 ⇒ 另算
    bk = os.path.join(WT, "backend")
    if os.path.isdir(bk):
        dd = sorted(d for d in os.listdir(bk)
                    if d.startswith("_demo_")
                    and os.path.isdir(os.path.join(bk, d)))
        print("  ⚠️ 空目錄 os.walk 走不到 ⇒ 目錄列舉另算："
              "backend/_demo_* %d 個 %s" % (len(dd), dd))
    print()

    print("### (2) 包側同一比對器")
    pkg_hits, pkg_all = scan(pkg, PKG_SKIP)
    print("-" * 74)
    clean = True
    for key, desc, _ in BAD:
        if pkg_hits[key]:
            clean = False
            R.fail("包側 %s" % key,
                   "%s 有 %d 個命中，例如 %s"
                   % (desc, len(pkg_hits[key]), pkg_hits[key][0]))
            for r in pkg_hits[key][:12]:
                print("       %s" % r)
            if len(pkg_hits[key]) > 12:
                print("       … 另 %d 個" % (len(pkg_hits[key]) - 12))
    if clean:
        print("  ✅ 包側 %d 類全部 0 命中" % len(BAD))
    print()

    lower = dict((r.replace("\\", "/").lower(), r) for r in pkg_all)

    def find(name):
        t = name.lower()
        return [v for k, v in lower.items() if k.endswith("/" + t) or k == t]

    print("### (3) 能力欄（不是檔案欄）")
    for name, why in CAPABILITY.items():
        found = find(name)
        print("  %-28s %-8s %s" % (name, "在包裡" if found else "不在", why))
        for f in found:
            print("       -> %s" % f)
    print()
    print("### (3b) 內部流程文件")
    for name in INTERNAL_DOC:
        found = find(name)
        print("  %-36s %s" % (name, found[0] if found else "不在"))
    md_top = sorted(f for f in pkg_all
                    if f.lower().endswith(".md") and os.sep not in f)
    print("  包根層 .md 共 %d 個" % len(md_top))
    tests = [f for f in pkg_all if re.match(r"backend[\\/]tests[\\/]", f, re.I)]
    print("  backend/tests/ 檔案 %d 個%s"
          % (len(tests), "" if tests else "（不在包裡）"))
    dotgit = [f for f in pkg_all if re.split(r"[\\/]", f)[0].lower() == ".git"]
    print("  .git/ 檔案 %d 個" % len(dotgit))
    if dotgit:
        R.fail("包側 .git", ".git/ 被打進包裡了（%d 個檔）" % len(dotgit))
    print()

    print("### (4) 必須存在")
    for name in MUST_EXIST:
        found = find(name)
        if not found:
            R.fail("必須存在", "%s 不在包裡" % name)
            continue
        print("  %-20s OK     %s" % (name, found[0]))
    print()

    print("### (4a) 排除清單 ∩ MUST_EXIST（🔴 擋關，見 SCOPE.md PK1 節）")
    check_exclusion_vs_must_exist()
    print()

    # 🔴 `VP6`：autostart.bat 的**內容**要被驗，不是只驗存在。
    #    ⚠️ 抽成函式而不是留在上面那個迴圈裡 —— 內嵌的話
    #       **只有整支跑起來才驗得到**，而那正是 `VP1` 那次的形狀。
    print("### (4b) autostart.bat 內容（🔴 擋關）")
    check_autostart(pkg)
    print()

    print("### (5) Leaflet SHA vs PROVENANCE.md（兩側都自己算）")
    # ⑥ 缺檔不可以 return —— 一個缺檔會讓第 6 節整段**安靜消失**
    check_provenance(pkg, lower)
    print()

    print("### (6) 包內 db.py 的版本（🔴 擋關）")
    check_db_version(pkg, args.expect_db_version)

    sys.exit(R.finish())


#: `autostart.bat` 必須帶的兩個開關。
#:
#: ☠️ 兩者少了的症狀都是「**功能安靜地不存在**」——
#:    少 `MOTRIX_TENDER_RADAR` ⇒ 標案雷達整個不跑，而系統一切正常
#:    少 `MOTRIX_GEO`          ⇒ 地址永遠換不到座標，地圖上什麼都沒有
#: 🔑 沒有錯誤、沒有紅字 ⇒ **不會有人報修。**
AUTOSTART_SWITCHES = ("MOTRIX_TENDER_RADAR", "MOTRIX_GEO")

#: 反斜線。**刻意用 `chr(92)` 而不是字面值。**
#:
#: ☠️ 我在這一支上踩過：用修檔腳本把 `[\\/]` 寫進來，而轉義被吃掉一層
#:    ⇒ 檔案裡變成 `[\/]` ⇒ 在字元類別裡那只是「斜線」，**不含反斜線**
#:    ⇒ 一條 `C:\…` 的正常路徑被判成「不是絕對路徑」。
#: 🔑 而它紅在**正對照**上（一份真的 autostart 被拒），所以當場就看得見；
#:    若我只寫了三個「該擋的」而沒有正對照，這個錯會安靜地讓**每一包都紅**。
_BS = chr(92)


def _looks_absolute(path):
    """看不看得出是一條絕對路徑。**不比對任何路徑字面值。**

    ⚠️ 不用 `os.path.isabs()`：它跟**跑驗包的那台機器**的作業系統走，
       而我們要判斷的是**目標機器**上的路徑 ——
    ☠️ 在 Linux 上 `os.path.isabs("C:\\…")` 是 `False` ⇒ 同一個包
       在不同機器上驗會得到不同結論，而那比不驗更糟。
    """
    if not path:
        return False
    if path[0] in (_BS, "/"):          # UNC (\\server) 或 POSIX 絕對路徑
        return True
    return len(path) >= 3 and path[1] == ":" and path[2] in (_BS, "/")


#: 一條 `cd` 指令，抓它的目標路徑（可帶 `/d`、可帶引號）。
_CD_RE = re.compile(r'^\s*cd\s+(?:/d\s+)?"?([^"\r\n]*)"?\s*$', re.IGNORECASE)


def check_autostart(pkg):
    r"""`VP6`：`autostart.bat` **不是只驗存在**。

    ## ☠️ 現況：只把 `set ` 開頭的行**印出來**

    `print` 不是 `R.fail` —— 它一個斷言都沒有。
    D 實測：把 `autostart.bat` 清成 **0 bytes**，驗包仍然 **EXIT=0**。

    ## 🔴 而正式機路徑**結構上看不到**

    ```
    set MOTRIX_TENDER_RADAR=1                      <= 舊過濾器看得到
    cd /d "C:\Users\Motrix\Desktop\V9.0\backend"   <= **它看不到**
    ```
    🔑 那是〈只留「可執行行」的過濾器〉的極端版：**它只留一種可執行行**，
       而路徑住在另一種。
    ☠️ D 實測：兩個開關還在、`set` 行數還是 4，**只改路徑** ⇒ 驗包 EXIT=0
       ⇒ 那台機器會 `cd` 到不存在的目錄 ⇒ uvicorn 起不來 ⇒
       **而排程每 5 秒重試一次，log 一直長。**

    ## ⚠️ 判準**不綁路徑字面值**

    綁了就是把驗包綁死在一台機器上 —— 換一台部署就永遠紅。
    ⇒ 釘的是：**有一條 `cd`、它的路徑非空、而且看得出是絕對路徑。**

    ## ⚙️ 兩個開關要**各自指名**

    ```
    兩個都少   多半是檔案壞了／被清空        => 一看就知道
    **少一個** 是有人**手動註解掉**其中一行  => 而它看起來完全正常
    ```
    🔑 只驗「至少有一個」的話，後者永遠不會被抓到。
    """
    path = None
    for root, _dirs, files in os.walk(pkg):
        for f in files:
            if f.lower() == "autostart.bat":
                path = os.path.join(root, f)
                break
        if path:
            break
    if path is None:
        R.fail("autostart 內容", "autostart.bat 不在包裡 ⇒ 這一項無法檢驗（**不是 PASS**）")
        return

    with io.open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    lines = text.splitlines()

    for sw in AUTOSTART_SWITCHES:
        # ⚠️ 只看**沒有被註解掉**的行：`rem` 或 `::` 開頭的不算數 ——
        #    「被註解掉」正是這一題要抓的那一種。
        live = [ln for ln in lines
                if not re.match(r"^\s*(rem\b|::)", ln, re.IGNORECASE)]
        hit = [ln for ln in live if re.search(r"^\s*set\s+%s\s*=" % sw, ln,
                                               re.IGNORECASE)]
        if not hit:
            R.fail("autostart 開關",
                   "autostart.bat 沒有設定 %s ⇒ 那個功能在那台機器上"
                   "**安靜地不會跑**" % sw)

    cds = [m.group(1).strip() for m in
           (_CD_RE.match(ln) for ln in lines) if m]
    if not cds:
        R.fail("autostart 路徑",
               "autostart.bat 裡沒有任何 cd 指令 ⇒ uvicorn 會在錯的目錄啟動")
    else:
        target = cds[-1]
        if not target:
            R.fail("autostart 路徑",
                   "autostart.bat 的 cd 目標是**空的** ⇒ 那台機器會 cd 到錯的地方，"
                   "uvicorn 起不來而排程一直重試")
        elif not _looks_absolute(target):
            # 🔑 不比對字面值，只問「看不看得出是絕對路徑」。
            R.fail("autostart 路徑",
                   "autostart.bat 的 cd 目標不是絕對路徑（%r）⇒ "
                   "啟動目錄會跟著排程的工作目錄跑" % target)
    print("  autostart.bat  %s" % path)
    print("       開關 %d／%d　cd 目標 %r"
          % (sum(1 for sw in AUTOSTART_SWITCHES
                 if re.search(r"^\s*set\s+%s\s*=" % sw, text, re.I | re.M)),
             len(AUTOSTART_SWITCHES), cds[-1] if cds else None))


def _export_ignore_patterns(gitattributes_path):
    """解析 `.gitattributes` 裡的 `export-ignore` 規則，回傳 pattern 字串清單。

    只認得「`<pattern> export-ignore`」這個形狀（同一行還可能有其他屬性，
    只要 `export-ignore` 是其中一個 token 就算）；不解析 gitignore 萬用字元的
    完整語意 —— 呼叫端只需要「這條 pattern 蓋不蓋得到某個具體檔案」，
    見 `_pattern_covers`。
    """
    patterns = []
    with io.open(gitattributes_path, "r", encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            parts = ln.split()
            if len(parts) >= 2 and "export-ignore" in parts[1:]:
                patterns.append(parts[0])
    return patterns


def _pattern_covers(pattern, rel_path):
    """`pattern`（`.gitattributes` 裡的一條）蓋不蓋得到 `rel_path`（repo 根為準的
    相對路徑，`/` 分隔）。

    ⚠️ 只處理本檔 `.gitattributes` 裡實際會出現的兩種錨定形狀 ——
    目錄（尾巴 `/`，如 `docs/windows/`）與單一檔案（帶或不帶開頭 `/`，
    一定含目錄路徑，如 `/CHANGELOG.md`／`docs/UI-BACKLOG.md`）。
    **不支援** `*.ext` 這種裸萬用字元或不帶路徑的裸檔名 pattern
    ——本檔目前沒有這種寫法，真的出現時寧可比對不到也不要猜。
    """
    p = pattern.lstrip("/")
    rel = rel_path.replace("\\", "/").lstrip("/")
    if p.endswith("/"):
        p = p.rstrip("/")
        return rel == p or rel.startswith(p + "/")
    return rel == p


def _find_in_tree(root, name, skip):
    """在 `root` 下找檔名為 `name` 的所有檔案，回傳相對 `root` 的路徑（`/` 分隔）。"""
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        if name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            hits.append(rel.replace("\\", "/"))
    return hits


def check_exclusion_vs_must_exist():
    """🔴 不變量：`export-ignore` 排除清單 ∩ `MUST_EXIST` = 空集合。

    背景見 `docs/windows/SCOPE.md`「PK1」節：`MUST_EXIST` 是**打包產出物的
    消費端**（本工具自己要求包裡一定要有），與「執行期會讀它」是同一類危險，
    只是消費者換成我們自己的驗包工具 —— 排除清單若不小心蓋到它，
    包會**永遠過不了驗包**，而症狀只會是這裡的 FAIL，不會是別的地方。

    ⚠️ `MUST_EXIST` 會長，這裡**不把今天的兩個值抄下來**——直接讀
    `verify_package.py` 自己的 `MUST_EXIST` 清單與工作樹當下的
    `.gitattributes`，交集永遠是**現算的**。
    """
    ga_path = os.path.join(WT, ".gitattributes")
    if not os.path.isfile(ga_path):
        R.fail("排除清單 vs MUST_EXIST", ".gitattributes 不存在（%s）⇒ 無法驗證交集" % ga_path)
        return
    patterns = _export_ignore_patterns(ga_path)
    print("  .gitattributes 裡 export-ignore 規則共 %d 條" % len(patterns))
    for name in MUST_EXIST:
        paths = _find_in_tree(WT, name, WT_SKIP)
        if not paths:
            R.fail("MUST_EXIST 找不到來源",
                   "%s 在工作樹裡找不到，無法驗證它會不會被排除掉" % name)
            continue
        for rel in paths:
            hit = [p for p in patterns if _pattern_covers(p, rel)]
            if hit:
                R.fail("排除清單 ∩ MUST_EXIST",
                       "%s（%s）同時是 MUST_EXIST 又被 export-ignore 蓋到：%s"
                       % (name, rel, "、".join(hit)))
            else:
                print("    %-20s %-40s 沒有被任何 export-ignore 蓋到 ✅" % (name, rel))


def check_provenance(pkg, lower):
    prov = [v for k, v in lower.items() if k.endswith("provenance.md")]
    if not prov:
        # ⑥ 記一筆 FAIL 然後**繼續跑**（原本這裡 `return`）
        R.fail("PROVENANCE", "PROVENANCE.md 不在包裡 ⇒ 這一項無法檢驗（**不是 PASS**）")
        return
    print("  %s" % prov[0])
    with io.open(os.path.join(pkg, prov[0]), "r", encoding="utf-8",
                 errors="replace") as fh:
        text = fh.read()
    # ⚠️ 早一版用 ([0-9a-fA-F]{64})[^0-9a-fA-F]{0,60}(檔名) —— 貪婪的
    #    [^0-9a-fA-F] 把 "leaflet" 的首字 l 吃掉，鍵變成 eaflet.js，
    #    於是五個檔全被判成「PROVENANCE 沒宣告」。**那是假陰性，不是缺宣告。**
    #    ⇒ 逐行、定錨在行首的 <64hex> <路徑>。
    declared = {}
    for ln in text.splitlines():
        m = re.match(r"\s*([0-9a-fA-F]{64})\s+(\S+)", ln)
        if m:
            declared[os.path.basename(m.group(2)).lower()] = (
                m.group(1).lower(), m.group(2))
    print("  PROVENANCE 解析出 %d 筆 sha256：%s" % (len(declared), sorted(declared)))
    if len(declared) != 5:
        R.fail("PROVENANCE 解析",
               "預期 5 筆，解析出 %d 筆 ⇒ **先懷疑解析，不要先懷疑檔案**"
               % len(declared))
    leaf = [v for k, v in lower.items() if "leaflet" in k]
    print("  包裡 leaflet 相關檔 %d 個" % len(leaf))
    checked = 0
    for rel in sorted(leaf):
        with open(os.path.join(pkg, rel), "rb") as fh:
            blob = fh.read()
        h = hashlib.sha256(blob).hexdigest()
        base = os.path.basename(rel).lower()
        ent = declared.get(base)
        if ent is None:
            verdict = "PROVENANCE 未宣告此檔（本身不是缺陷：PROVENANCE.md 自己不在清單內）"
        elif ent[0] == h:
            verdict = "相符（宣告路徑 %s）" % ent[1]
            checked += 1
        else:
            verdict = "🔴 不符 宣告=%s" % ent[0][:16]
            R.fail("Leaflet SHA", "%s 的 sha256 與 PROVENANCE 宣告不符" % base)
        print("    %-24s %8d bytes  %s  %s"
              % (os.path.basename(rel), len(blob), h[:16], verdict))
    print("  => 五檔比對通過 %d / %d" % (checked, len(declared)))
    if declared and checked != len(declared):
        R.fail("Leaflet SHA", "只有 %d/%d 檔比對通過" % (checked, len(declared)))


if __name__ == "__main__":
    main()
