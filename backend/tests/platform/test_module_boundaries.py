"""模組邊界守門（CORE-SPEC §8「邊界守門」；modtest 每次必跑本目錄）。

① L2 之間的 import 邊只准變少（基線 l2_import_baseline.json）
② 每個 router／helper／page 剛好歸屬一組（docs/platform/modules.json）
③ L2 表只由擁有它的組直接寫入；例外列 table_write_exceptions.json，只准變少

相依圖每次現場掃描原始碼（dep_scan.build），不讀已提交的 dep_graph.json。
每一條斷言都有對應的反向控制（檔尾）：突變後同一個判定函式必須報出來。
"""
import copy
import json
import shutil

import pytest

from tests.platform import _boundaries as B


@pytest.fixture(scope="module")
def dep_scan():
    return B.load_dep_scan()


@pytest.fixture(scope="module")
def units(dep_scan):
    return B.scan_units(dep_scan)


@pytest.fixture(scope="module")
def groups():
    assert B.MODULES_JSON.exists(), "缺 docs/platform/modules.json（分組的唯一來源）"
    return B.Groups.load()


@pytest.fixture(scope="module")
def baseline():
    return json.loads(B.BASELINE.read_text(encoding="utf-8"))["edges"]


@pytest.fixture(scope="module")
def exceptions():
    return json.loads(B.EXCEPTIONS.read_text(encoding="utf-8"))["exceptions"]


def _fmt(items):
    return "\n  " + "\n  ".join(items)


# ── 掃描器正對照：圖是空的時候每一條都會綠 ───────────────────────────────

def test_scanner_sees_the_codebase(units):
    kinds = {u["kind"] for u in units.values()}
    assert {"router", "helper", "page", "table"} <= kinds
    assert "helper:quotations" in units["router:quotations"]["imports"]
    assert "quotations" in units["router:quotations"]["tables_w"]


# ── ① ─────────────────────────────────────────────────────────────────────

def test_no_new_l2_cross_imports(units, groups, baseline):
    new, _ = B.check_import_baseline(units, groups, baseline)
    assert not new, ("新增了 L2 跨組 import（只准變少；改走 L1 或連接器，見 CORE-SPEC §5）：" + _fmt(new))


def test_baseline_has_no_vanished_edges(units, groups, baseline):
    _, gone = B.check_import_baseline(units, groups, baseline)
    assert not gone, ("這些跨組邊已經不存在，請從基線刪掉（python backend/tests/platform/_boundaries.py --prune）："
                      + _fmt(gone))


def test_edges_of_modules_not_installed_are_not_vanished(units, groups, baseline):
    """反向控制：來源是沒裝的模組（`mod:<不存在的 key>/…`）⇒ 不算消失；來源是一般單位 ⇒ 照報（合成邊，不綁真實模組）。"""
    fake_mod = "M99 mod:zz_not_installed/api -> M01 helper:quotations"
    fake_router = "M99 router:zz_not_there -> M01 helper:quotations"
    _, gone = B.check_import_baseline(units, groups, list(baseline) + [fake_mod, fake_router])
    assert fake_mod not in gone and fake_router in gone, gone


# ── ② ─────────────────────────────────────────────────────────────────────

def test_every_router_helper_page_has_exactly_one_owner(units, groups):
    unowned, dup, _ = B.check_ownership(units, groups)
    assert not unowned, "未歸屬任何組（加進 docs/platform/modules.json）：" + _fmt(unowned)
    assert not dup, "歸屬超過一組：" + _fmt(dup)


def test_modules_json_lists_only_existing_units(units, groups):
    _, _, stale = B.check_ownership(units, groups)
    assert not stale, "modules.json 列了但掃描不到（已刪或改名）：" + _fmt(stale)


def test_every_listed_table_has_single_owner(units, groups):
    bad = B.l2_tables_without_owner(units, groups)
    assert not bad, "表歸屬 0 或多組（③ 依表歸屬判定，歸屬錯了 ③ 就沒在驗）：" + _fmt(bad)


# ── ③ ─────────────────────────────────────────────────────────────────────

def test_l2_tables_written_only_by_owner(units, groups, exceptions):
    extra, _ = B.check_table_writes(units, groups, exceptions)
    assert not extra, ("L2 表被非擁有組直接寫入（改走擁有組的連接器，見 DEPENDENCY-MAP §4）：" + _fmt(extra))


def test_write_exceptions_still_occur(units, groups, exceptions):
    _, gone = B.check_table_writes(units, groups, exceptions)
    assert not gone, ("白名單裡這些寫入已不存在，請刪掉（python backend/tests/platform/_boundaries.py --prune）："
                      + _fmt(gone))


def test_write_exceptions_cite_a_source(exceptions):
    missing = ["%s <- %s" % (e["table"], e["writer"]) for e in exceptions if not e.get("ref")]
    assert not missing, "白名單每一筆都要寫出處（ref）：" + _fmt(missing)


def test_write_exceptions_are_classified(exceptions):
    """kind=frozen：凍結 migration（只有 core:db），永久保留；kind=debt：拆模組時逐筆清掉。"""
    bad = ["%s <- %s kind=%r" % (e["table"], e["writer"], e.get("kind")) for e in exceptions
           if e.get("kind") not in ("frozen", "debt") or (e.get("kind") == "frozen") != (e["writer"] == "core:db")]
    assert not bad, "kind 必須是 frozen（僅 core:db 凍結 migration）或 debt：" + _fmt(bad)


# ══════════════════════════════════════════════════════════════════════════
# 反向控制：每一條斷言用的判定函式，在突變後必須報出突變
# ══════════════════════════════════════════════════════════════════════════

def _pick_new_cross_edge(units, groups, baseline):
    """找一對 L2 router（不同組），其間目前沒有邊。"""
    routers = sorted((groups.owner(n), n) for n, u in units.items()
                     if u["kind"] == "router" and groups.owner(n) in groups.l2)
    base = set(baseline)
    for g1, r1 in routers:
        for g2, r2 in routers:
            if g1 != g2 and "%s %s -> %s %s" % (g1, r1, g2, r2) not in base:
                return g1, r1, g2, r2
    pytest.fail("找不到可突變的 router 對")


def test_rc_new_cross_import_is_caught(units, groups, baseline):
    g1, r1, g2, r2 = _pick_new_cross_edge(units, groups, baseline)
    mut = copy.deepcopy(units)
    mut[r1]["imports"].append(r2)
    before, _ = B.check_import_baseline(units, groups, baseline)
    new, _ = B.check_import_baseline(mut, groups, baseline)
    assert set(new) - set(before) == {"%s %s -> %s %s" % (g1, r1, g2, r2)}


def test_rc_vanished_baseline_edge_is_caught(units, groups, baseline):
    live = sorted(B.l2_import_edges(units, groups) & set(baseline))
    if not live:
        pytest.skip("基線裡沒有仍存在的邊可拿來突變")
    edge = live[0]
    src, dst = edge.split(" -> ")
    src_u, dst_u = src.split(" ", 1)[1], dst.split(" ", 1)[1]
    mut = copy.deepcopy(units)
    mut[src_u]["imports"] = [d for d in mut[src_u]["imports"] if d != dst_u]
    _, before = B.check_import_baseline(units, groups, baseline)
    _, gone = B.check_import_baseline(mut, groups, baseline)
    assert set(gone) - set(before) == {edge}


def test_rc_unowned_router_is_caught(units, groups):
    mut = copy.deepcopy(units)
    mut["router:zz_mutant"] = {"kind": "router", "path": "backend/routers/zz_mutant.py", "imports": []}
    before, _, _ = B.check_ownership(units, groups)
    unowned, _, _ = B.check_ownership(mut, groups)
    assert set(unowned) - set(before) == {"router:zz_mutant"}


def test_rc_double_owned_page_is_caught(units):
    data = json.loads(B.MODULES_JSON.read_text(encoding="utf-8"))
    page = next(u for u in data["L1"]["units"] if u.startswith("page:"))
    some_l2 = sorted(data["modules"])[0]
    data["modules"][some_l2]["units"].append(page)
    _, before, _ = B.check_ownership(units, B.Groups.load())
    _, dup, _ = B.check_ownership(units, B.Groups(data))
    added = set(dup) - set(before)
    assert len(added) == 1 and added.pop().startswith(page + ": ")


def test_rc_stale_modules_entry_is_caught(units):
    data = json.loads(B.MODULES_JSON.read_text(encoding="utf-8"))
    data["L1"]["units"].append("helper:zz_gone")
    _, _, before = B.check_ownership(units, B.Groups.load())
    _, _, stale = B.check_ownership(units, B.Groups(data))
    assert set(stale) - set(before) == {"helper:zz_gone"}


def test_rc_foreign_table_write_is_caught(units, groups, exceptions):
    tbl = next(t for t, gs in sorted(groups.table_groups.items()) if len(gs) == 1 and gs[0] in groups.l2)
    own = groups.table_owner(tbl)
    writer = next(n for n, u in sorted(units.items())
                  if u["kind"] == "router" and groups.owner(n) in groups.l2 and groups.owner(n) != own)
    mut = copy.deepcopy(units)
    mut[writer]["tables_w"].append(tbl)
    before, _ = B.check_table_writes(units, groups, exceptions)
    extra, _ = B.check_table_writes(mut, groups, exceptions)
    assert set(extra) - set(before) == {"%s <- %s" % (tbl, writer)}


def test_rc_vanished_write_exception_is_caught(units, groups, exceptions):
    live = B.foreign_writes(units, groups)
    e = next((x for x in exceptions if "%s <- %s" % (x["table"], x["writer"]) in live), None)
    if e is None:
        pytest.skip("白名單裡沒有仍存在的寫入可拿來突變")
    mut = copy.deepcopy(units)
    mut[e["writer"]]["tables_w"] = [t for t in mut[e["writer"]]["tables_w"] if t != e["table"]]
    _, before = B.check_table_writes(units, groups, exceptions)
    _, gone = B.check_table_writes(mut, groups, exceptions)
    assert set(gone) - set(before) == {"%s <- %s" % (e["table"], e["writer"])}


def test_rc_end_to_end_through_real_source(tmp_path, dep_scan, groups, baseline):
    """真的改原始碼（沙盒複本）：加一條跨組 import、加一支無歸屬 router ⇒ 掃描器＋判定都要抓到。

    ⚠ 只在 tmp_path 裡改；dep_scan 以副本的 ROOT 重掃，不碰工作樹。
    """
    root = B.REPO
    sandbox = tmp_path / "repo"
    for sub, pats in (("backend", ("*.py", "routers/*.py", "helpers/*.py")),
                      ("frontend", ("**/*.html", "**/*.js"))):
        for pat in pats:
            for p in (root / sub).glob(pat):
                if "vendor" in p.parts:
                    continue
                dst = sandbox / p.relative_to(root)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dst)

    units0 = B.scan_units(dep_scan)
    g1, r1, g2, r2 = _pick_new_cross_edge(units0, groups, baseline)
    src_file = sandbox / units0[r1]["path"]
    src_file.write_text(src_file.read_text(encoding="utf-8-sig")
                        + "\nfrom routers import %s as _zz_mutant  # noqa\n" % r2.split(":", 1)[1],
                        encoding="utf-8")
    (sandbox / "backend" / "routers" / "zz_mutant.py").write_text(
        "from fastapi import APIRouter\nrouter = APIRouter()\n", encoding="utf-8")

    saved = {k: getattr(dep_scan, k) for k in ("ROOT", "BACKEND", "FRONTEND")}
    try:
        dep_scan.ROOT, dep_scan.BACKEND, dep_scan.FRONTEND = sandbox, sandbox / "backend", sandbox / "frontend"
        mutated = dep_scan.build()["units"]
    finally:
        for k, v in saved.items():
            setattr(dep_scan, k, v)

    new0, _ = B.check_import_baseline(units0, groups, baseline)
    unowned0, _, _ = B.check_ownership(units0, groups)
    new, _ = B.check_import_baseline(mutated, groups, baseline)
    unowned, _, _ = B.check_ownership(mutated, groups)
    assert set(new) - set(new0) == {"%s %s -> %s %s" % (g1, r1, g2, r2)}
    assert set(unowned) - set(unowned0) == {"router:zz_mutant"}
