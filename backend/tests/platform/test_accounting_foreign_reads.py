"""M06 會計傳票讀別組的表：已知例外只准變少、到期自己觸發（主持裁示 M06-a、d；M06-PLAN §5）。

比照 `test_case_access_l1.py` 的 KNOWN_L1：
① `modules/accounting/**`（`source_tree.module_files`，排除 tests）的 SQL（`dep_scan.sql_tables`，與 dep_graph 同一份）
   讀到的表，扣掉本模組 `module.json` 的 `data.tables` 與 L1 的表 ⇒ 別組的表；不在基線 ⇒ 紅。
② 基線每一筆寫明到期的 capability；那個 capability 已被程式碼提供（`code_capabilities`，與
   test_integration_points_registered 同一個掃描）⇒ 紅「提供者已在，改走它並自基線刪除」。
   到期觸發的是**提供者出現**，不是日期；刪條目的 commit 引用觸發它的那一班列車（RUN-PLAN §6）。
③ 基線條目已經不讀那張表／檔案不在 ⇒ 紅（基線跟著縮，CA-S3）。
M06 不在（模組拿掉，或 M06 搬遷前）⇒ ①～③ 略過；反向控制用合成資料，永遠照跑。
"""
import ast
import json
import sys
from pathlib import Path

import pytest

from core import source_tree
from tests.platform.test_integration_points_registered import code_capabilities

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import dep_scan  # noqa: E402

MODULE = "modules/accounting"

#: 檔（相對 backend）⇒ {別組的表: (擁有的模組 key, 到期的 capability)}。只准變少。
#: a：M06-a（M01 提供 case.summary／case.extra_expenses 前）
#: d（accounting_export 讀 contractor_payment_vouchers）2026-09-26 到期刪除：c-ip14-paid 的 paid_between 已帶入本疊（本守門的到期題觸發）
#: a'：vouchers.py 的 JV21 支出來源與 by-case 派工段讀 M04 的派工表。主持裁示（2026-09-26）：IP-15 走派工清單的模組權限，
#:     只持 finance 的會計會悄悄少列 ⇒ 由 C 在 IP-15 新增「成本檢視」（放行 finance／cashier，只回金額、日期、案件、廠商名稱）；
#:     做好之前保留直讀。到期能力名暫記 `dispatch.cost_for_case`，C 定名後同步改這裡（M06-PLAN §5 a' 列）
KNOWN_FOREIGN_READS = {
    MODULE + "/api/vouchers.py": {
        "quotations": ("case", "case.summary"),
        "case_extra_expenses": ("case", "case.extra_expenses"),
        "contractor_dispatches": ("subcontract", "dispatch.cost_for_case"),
        "vendor_contractors": ("subcontract", "dispatch.cost_for_case"),
    },
}

#: L1 的表（任何模組都可以讀）。只放 M06 真的在讀的，新增要有理由。
L1_TABLES = {"users"}


def own_tables(module_dir):
    """本模組自己的表：module.json 的 `data.tables`（有分類的）＋頂層 `tables`＋`views`（VIEW 不分類）。"""
    m = json.loads((Path(module_dir) / "module.json").read_text(encoding="utf-8"))
    data = m.get("data") or {}
    return {t["name"] for t in data.get("tables", [])} | set(m.get("tables", [])) | set(m.get("views", []))


def foreign_reads(sources, own, known, l1=L1_TABLES):
    """sources：{相對路徑: 原始碼} ⇒ {相對路徑: 別組的表集合}（只列非空）。known：全部的表（dep_scan.known_tables）。"""
    out = {}
    for rel, src in sources.items():
        r, _w, _ddl, _dyn = dep_scan.sql_tables(dep_scan.string_chunks(ast.parse(src)), known)
        got = set(r) - own - l1
        if got:
            out[rel] = got
    return out


def excess(found, known=KNOWN_FOREIGN_READS):
    return sorted("%s 讀 %s（不在基線）" % (f, t) for f, ts in found.items() for t in sorted(ts - set(known.get(f, {}))))


def stale(found, files, known=KNOWN_FOREIGN_READS):
    out = []
    for f, tables in known.items():
        for t in tables:
            if f not in files:
                out.append("%s：檔案不在 ⇒ 自基線刪除" % f)
                break
            if t not in found.get(f, set()):
                out.append("%s 已不讀 %s ⇒ 自基線刪除" % (f, t))
    return out


def expired(provided, known=KNOWN_FOREIGN_READS):
    return sorted("%s 讀 %s：提供者 %s 已在（%s）⇒ 改走它並自基線刪除" % (f, t, cap, owner)
                  for f, ts in known.items() for t, (owner, cap) in ts.items() if cap in provided)


def _module_sources():
    d = source_tree.BACKEND / MODULE
    return {source_tree.rel(p): p.read_text(encoding="utf-8") for p in source_tree.module_files(d)}


def _require_module():
    if not source_tree.module_installed(MODULE + "/x.py"):
        pytest.skip("M06 不在（模組拿掉，或 M06 搬遷前）：本模組沒有讀別組的表")


def test_accounting_reads_of_other_modules_only_shrink():
    _require_module()
    found = foreign_reads(_module_sources(), own_tables(source_tree.BACKEND / MODULE), set(dep_scan.known_tables()))
    bad = excess(found)
    assert not bad, ("M06 新增讀別組的表——要讀別組的資料，經擁有者的提供者（INTEGRATION-POINTS）：\n  "
                     + "\n  ".join(bad))


def test_accounting_foreign_reads_baseline_is_not_stale():
    _require_module()
    src = _module_sources()
    bad = stale(foreign_reads(src, own_tables(source_tree.BACKEND / MODULE), set(dep_scan.known_tables())), set(src))
    assert not bad, "基線過期：\n  " + "\n  ".join(bad)


def test_accounting_foreign_reads_expire_when_the_provider_exists():
    _require_module()
    provided, _ = code_capabilities({source_tree.rel(p): p.read_text(encoding="utf-8")
                                     for p in source_tree.product_files()})
    bad = expired(provided)
    assert not bad, "到期：\n  " + "\n  ".join(bad)


# ── 反向控制（合成資料；M06 在不在都照跑）─────────────────────────────────────

_K = {"quotations", "vouchers_all", "users", "payslips", "case_updates"}


def test_positive_and_reverse_control_of_the_scan():
    f = MODULE + "/api/vouchers.py"
    base = {f: 'conn.execute("SELECT * FROM quotations q JOIN vouchers_all v ON v.id=q.id")\n'
               'conn.execute("SELECT name FROM users")\n'}
    found = foreign_reads(base, {"vouchers_all"}, _K)
    assert found == {f: {"quotations"}}, found                    # 自己的表、L1 的表不算
    assert excess(found) == []                                    # 在基線 ⇒ 過
    more = dict(base)
    more[f] += 'conn.execute("SELECT * FROM payslips")\n'
    assert excess(foreign_reads(more, {"vouchers_all"}, _K)) == ["%s 讀 payslips（不在基線）" % f]
    new_file = {MODULE + "/service/x.py": 'conn.execute("SELECT 1 FROM case_updates")\n'}
    assert excess(foreign_reads(new_file, set(), _K)) == ["%s/service/x.py 讀 case_updates（不在基線）" % MODULE]


def test_positive_and_reverse_control_of_stale_and_expiry():
    f = MODULE + "/api/vouchers.py"
    found = {f: {"quotations", "case_extra_expenses", "contractor_dispatches", "vendor_contractors"}}
    assert stale(found, set(found)) == []
    shrunk = dict(found, **{f: found[f] - {"quotations"}})
    assert stale(shrunk, set(found)) == ["%s 已不讀 quotations ⇒ 自基線刪除" % f]
    assert stale(found, set()) == ["%s：檔案不在 ⇒ 自基線刪除" % f]
    assert expired(set()) == []
    got = expired({"dispatch.cost_for_case"})
    assert len(got) == 2 and all("dispatch.cost_for_case" in g for g in got), got
    provided, _ = code_capabilities({"x.py": 'registry.provide("case.summary", "case", X)\n'})
    assert [g for g in expired(provided) if "quotations" in g], "code_capabilities 的提供者要能觸發到期"
