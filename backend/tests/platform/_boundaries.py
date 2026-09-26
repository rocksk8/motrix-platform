"""模組邊界守門的判定邏輯（純函式）。test_module_boundaries.py 與反向控制共用同一套。

資料來源：
  相依圖   tools/platform/dep_scan.py 的 build()——每次現場掃描原始碼，不讀已提交的 dep_graph.json
           （讀檔會在「改了程式、沒重產 json」時給假綠燈）
  分組     docs/platform/modules.json：{"L1":{units,tables},"modules":{"M01":{key,name,units,tables,api_prefixes}},
           "retired":{...}}（retired 可省略；列在其中的單位視為已歸屬、待刪除）
  基線     l2_import_baseline.json：目前允許存在的 L2 跨組 import 邊，只准變少
  白名單   table_write_exceptions.json：L2 表被非擁有組直接寫入的例外，只准變少

維護基線（只能刪不能加）：
  python backend/tests/platform/_boundaries.py --prune    刪掉已消失的邊／例外
  python backend/tests/platform/_boundaries.py --init     僅在基線檔不存在時建立
"""
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MODULES_JSON = REPO / "docs" / "platform" / "modules.json"
DEP_SCAN = REPO / "tools" / "platform" / "dep_scan.py"
BASELINE = HERE / "l2_import_baseline.json"
EXCEPTIONS = HERE / "table_write_exceptions.json"

#: 每個都必須剛好歸屬一組（mod＝backend/modules/<key>/ 內的檔、plat＝backend/core/ 的 L0 平台）
OWNED_KINDS = ("router", "helper", "page", "mod", "plat")


def load_dep_scan():
    spec = importlib.util.spec_from_file_location("_platform_dep_scan", DEP_SCAN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def scan_units(dep_scan=None):
    """現場掃描 ⇒ units dict。"""
    return (dep_scan or load_dep_scan()).build()["units"]


class Groups:
    """modules.json 的解析結果。"""

    def __init__(self, data):
        self.l2 = set(data["modules"])
        self.retired = {"retired:" + k for k in data.get("retired", {})}
        all_groups = {"L1": data["L1"]}
        all_groups.update(data["modules"])
        all_groups.update({"retired:" + k: v for k, v in data.get("retired", {}).items()})
        self.unit_groups = defaultdict(list)
        self.table_groups = defaultdict(list)
        for g, spec in all_groups.items():
            for u in spec.get("units", []):
                self.unit_groups[u].append(g)
            for t in spec.get("tables", []):
                self.table_groups[t].append(g)

    @classmethod
    def load(cls, path=MODULES_JSON):
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def owner(self, unit):
        gs = self.unit_groups.get(unit, [])
        return gs[0] if len(gs) == 1 else None

    def table_owner(self, table):
        gs = self.table_groups.get(table, [])
        return gs[0] if len(gs) == 1 else None


# ── ① L2 之間的 import 邊 ─────────────────────────────────────────────────

def l2_import_edges(units, groups):
    """{"M06 router:accounting_export -> M08 router:reports", ...}；只算 imports（python import、頁面 script）。"""
    edges = set()
    for n, u in units.items():
        src = groups.owner(n)
        if src not in groups.l2:
            continue
        for d in u.get("imports", []):
            dst = groups.owner(d)
            if dst in groups.l2 and dst != src:
                edges.add("%s %s -> %s %s" % (src, n, dst, d))
    return edges


def l1_to_l2_edges(units, groups):
    """{"L1 helper:receivables -> M01 helper:quotations", ...}：L1 單位 import L2 單位（逆向依賴，MODULE-GUIDE §1 禁止）。
    扣掉 core:main → router:（載入器掛 router，隨模組搬遷自然消失；dep_scan 也另列為「預期」）。"""
    edges = set()
    for n, u in units.items():
        if groups.owner(n) != "L1":
            continue
        for d in u.get("imports", []):
            dst = groups.owner(d)
            if dst in groups.l2 and not (n == "core:main" and d.startswith("router:")):
                edges.add("L1 %s -> %s %s" % (n, dst, d))
    return edges


def check_l1_to_l2_baseline(units, groups, baseline):
    """(新增的邊, 已消失的邊)。目標是沒裝的已登記模組（mod:<key>/…）⇒ 不算消失（同 check_import_baseline）。"""
    from core import source_tree
    cur = l1_to_l2_edges(units, groups)
    base = set(baseline)
    installed = {d.name for d in source_tree.module_dirs()}
    registered = _registered_module_keys()

    def _not_installed(edge):
        dst = edge.split(" -> ", 1)[1].split(" ", 1)[-1]
        if not dst.startswith("mod:"):
            return False
        key = dst[4:].split("/", 1)[0]
        return key not in installed and key in registered
    return sorted(cur - base), sorted(e for e in base - cur if not _not_installed(e))


def _registered_module_keys():
    """docs/platform/modules.json 登記的模組 key（repo 層級，與這棵樹裝了什麼無關）。"""
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parents[3] / "docs" / "platform" / "modules.json"
    return {g.get("key") for g in json.loads(p.read_text(encoding="utf-8")).get("modules", {}).values() if g.get("key")}


def check_import_baseline(units, groups, baseline):
    """(新增的邊, 基線裡已消失的邊)

    來源單位是 `mod:<key>/…` 而該模組不在這棵樹（反向控制、產品選配）⇒ 那條邊不是「消失」，是「沒裝」：
    不報、`--prune` 也不刪（M08 反向控制：否則在拿掉模組的樹上 prune 會把基線裡真實存在的邊刪掉）。"""
    from core import source_tree
    cur = l2_import_edges(units, groups)
    base = set(baseline)
    installed = {d.name for d in source_tree.module_dirs()}
    registered = _registered_module_keys()

    def _not_installed(edge):
        # 只有「登記過、但這棵樹沒裝」才算沒裝；key 在 modules.json 根本沒登記（改名後的殘留）⇒ 照報消失（稽核 ⑰ O-2）
        src = edge.split(" -> ", 1)[0].split(" ", 1)[-1]
        if not src.startswith("mod:"):
            return False
        key = src[4:].split("/", 1)[0]
        return key not in installed and key in registered
    return sorted(cur - base), sorted(e for e in base - cur if not _not_installed(e))


# ── ② 歸屬 ──────────────────────────────────────────────────────────────

def check_ownership(units, groups):
    """(未歸屬, 重複歸屬, modules.json 列了但掃描不到)"""
    unowned, dup = [], []
    for n, u in sorted(units.items()):
        if u.get("kind") not in OWNED_KINDS:
            continue
        gs = groups.unit_groups.get(n, [])
        if not gs:
            unowned.append(n)
        elif len(gs) > 1:
            dup.append("%s: %s" % (n, gs))
    stale = sorted(u for u in groups.unit_groups if u not in units)
    return unowned, dup, stale


# ── ③ L2 表只由擁有組直接寫入 ────────────────────────────────────────────

def foreign_writes(units, groups):
    """{"table <- writer"}：L2 表被非擁有組的單位直接寫入（tables_w，不含 DDL、不含經 helper 的遞移寫入）。"""
    out = set()
    for n, u in units.items():
        for t in u.get("tables_w", []):
            own = groups.table_owner(t)
            if own in groups.l2 and groups.owner(n) != own:
                out.add("%s <- %s" % (t, n))
    return out


def check_table_writes(units, groups, exceptions):
    """(白名單外的寫入, 白名單裡已不存在的寫入)"""
    cur = foreign_writes(units, groups)
    allowed = {"%s <- %s" % (e["table"], e["writer"]) for e in exceptions}
    return sorted(cur - allowed), sorted(allowed - cur)


def l2_tables_without_owner(units, groups):
    """modules.json 裡歸屬不明（0 或 >1 組）的表——③ 靠表歸屬判定，歸屬錯了 ③ 就沒在驗。"""
    return sorted(t for t, gs in groups.table_groups.items() if len(gs) != 1)


# ── 基線維護（只能縮小）───────────────────────────────────────────────────

def _load_list(path, key):
    return json.loads(Path(path).read_text(encoding="utf-8"))[key] if Path(path).exists() else None


def _write(path, key, items, note):
    Path(path).write_text(json.dumps({"_doc": note, key: items}, ensure_ascii=False, indent=1) + "\n",
                          encoding="utf-8", newline="\n")


def main(argv):
    mode = argv[0] if argv else ""
    if mode not in ("--init", "--prune"):
        print(__doc__)
        return 2
    units = scan_units()
    groups = Groups.load()
    edges = sorted(l2_import_edges(units, groups))
    writes = sorted(foreign_writes(units, groups))
    base = _load_list(BASELINE, "edges")
    exc = _load_list(EXCEPTIONS, "exceptions")
    if mode == "--init":
        if base is not None or exc is not None:
            print("基線／白名單已存在；--init 只在不存在時建立（避免把新增的邊洗進基線）")
            return 1
        _write(BASELINE, "edges", edges, "L2 跨組 import 邊的基線：只准變少。新增⇒守門紅；消失⇒用 --prune 刪除。")
        _write(EXCEPTIONS, "exceptions",
               [{"table": w.split(" <- ")[0], "writer": w.split(" <- ")[1], "ref": "", "kind": ""} for w in writes],
               "L2 表被非擁有組直接寫入的例外：只准變少；ref 寫出處（DEPENDENCY-MAP §4 等）。")
        print("建立：%d 條邊、%d 筆例外" % (len(edges), len(writes)))
        return 0
    # --prune：只刪，不加。刪的是「消失」的邊——與守門同一個判定（check_*_baseline 的 gone），
    # 所以「沒裝的已登記模組」的邊不會被刪；其他鍵（l1_to_l2 等）原樣保留。
    # 〔更正（2026-09-26，稽核 ⑰ S-7 時查到）：之前這裡直接比 edges、整份只寫 _doc＋edges——
    #   在拿掉模組的樹上 prune 會刪掉真實存在的邊（而 check_import_baseline 的說明寫著不會），也會把 l1_to_l2 整段洗掉〕
    raw = json.loads(BASELINE.read_text(encoding="utf-8"))
    _, gone = check_import_baseline(units, groups, raw["edges"])
    raw["edges"] = [e for e in raw["edges"] if e not in set(gone)]
    n_l1 = 0
    if "l1_to_l2" in raw:
        _, gone_l1 = check_l1_to_l2_baseline(units, groups, raw["l1_to_l2"])
        n_l1 = len(gone_l1)
        raw["l1_to_l2"] = [e for e in raw["l1_to_l2"] if e not in set(gone_l1)]
    Path(BASELINE).write_text(json.dumps(raw, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    raw_exc = json.loads(EXCEPTIONS.read_text(encoding="utf-8"))
    new_exc = [e for e in raw_exc["exceptions"] if "%s <- %s" % (e["table"], e["writer"]) in set(writes)]
    _write(EXCEPTIONS, "exceptions", new_exc, raw_exc["_doc"])
    print("刪除：%d 條 L2 邊、%d 條 L1→L2 邊、%d 筆例外" % (len(gone), n_l1, len(raw_exc["exceptions"]) - len(new_exc)))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main(sys.argv[1:]))
