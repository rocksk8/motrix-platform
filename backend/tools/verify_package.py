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
            print("✅ 全部通過（%d 項 FAIL）" % 0)
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
    """③④ 判準**只看包裡那一份**；工作樹那一份只用來比對。"""
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
        print("  ⚠️ 未給 --expect-db-version ⇒ **只驗了「三源自己一致」**，"
              "沒有驗「它是不是應該的那個版本」。")
        print("     📌 `deploy_manifest.json` 不帶 db 版本（實查：只有 "
              "commit／branch／built_at／version_manifest_latest／"
              "durations_sec／tests／env）⇒ 期望值只能由呼叫端給。")
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
                    help="包內 db.py 的 CURRENT_VERSION 應該是多少（不給則只驗三源一致）")
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
        if name == "autostart.bat":
            p = os.path.join(pkg, found[0])
            with io.open(p, "r", encoding="utf-8", errors="replace") as fh:
                sets = [ln.strip() for ln in fh
                        if ln.strip().lower().startswith("set ")]
            print("       set 行 %d 條：" % len(sets))
            for s in sets:
                print("         %s" % s)
    print()

    print("### (5) Leaflet SHA vs PROVENANCE.md（兩側都自己算）")
    # ⑥ 缺檔不可以 return —— 一個缺檔會讓第 6 節整段**安靜消失**
    check_provenance(pkg, lower)
    print()

    print("### (6) 包內 db.py 的版本（🔴 擋關）")
    check_db_version(pkg, args.expect_db_version)

    sys.exit(R.finish())


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
