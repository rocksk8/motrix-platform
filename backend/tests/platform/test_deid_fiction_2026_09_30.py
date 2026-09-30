# -*- coding: utf-8 -*-
"""去識別化 S3：虛構值登記檔 `deid_fiction.json` 與 `deid_fiction.py`（取值規則＋登記檔驗證），以及掃描器為 S3 做的三項收斂。

登記檔是明文的虛構值 ⇒ 每筆都要過 §2.1 取值規則，否則有人可以把真實值登記成「虛構」讓掃描器放行——所以規則本身要有反向控制。
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import deid_fiction as F  # noqa: E402
import deid_scan as S  # noqa: E402

REGISTRY = REPO / "tools" / "platform" / "deid_fiction.json"


def _tree(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


# ── 登記檔本身 ─────────────────────────────────────────────────────────────────────

def test_the_committed_registry_passes_every_rule():
    entries = F.load(REGISTRY)
    assert len(entries) >= 15, "登記檔空了或被砍：既有範例值（頁面 placeholder、範本樣式）都要在裡面"
    assert F.problems(entries) == []


def test_the_committed_registry_covers_the_examples_the_product_ships():
    """正對照：產品裡已知一定存在的虛構範例要真的被登記檔涵蓋——掃描該檔時不再有命中。"""
    fiction = F.load(REGISTRY)
    tree = {"frontend/pages/p.html": '<input placeholder="例：範例科技股份有限公司"> <input placeholder="例：02-0000-0000"> <input placeholder="地址，例：範例市示範區範例路1號">\n',
            "backend/x.py": '"""格式例：MQ-202501-001 或 DN-202508-001"""\n'}
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root = _tree(Path(d), tree)
        assert S.scan(root)                                                  # 沒登記時有命中（掃描器沒壞）
        assert S.scan(root, fiction=fiction) == []


def test_registered_fiction_does_not_hide_a_real_lookalike(tmp_path):
    """登記的是「這個值」，不是「這個樣式」：換一個像的值照擋。"""
    fiction = F.load(REGISTRY)
    root = _tree(tmp_path, {"a.html": "例：範例科技股份有限公司　真實：海天整合股份有限公司　電話 02-0000-0000／04-3610-6566\n"})
    kinds = sorted((h.kind for h in S.scan(root, fiction=fiction)))
    assert kinds == ["company_pattern", "phone_pattern"], kinds


# ── 取值規則（反向控制：每一類都要能擋下真實樣子的值）──────────────────────────────────

@pytest.mark.parametrize("kind,value,ok", [
    ("phone_pattern", "02-0000-0000", True), ("phone_pattern", "02-0000-9999", True), ("phone_pattern", "0900-000-000", True),
    ("phone_pattern", "02-1234-5678", False), ("phone_pattern", "04-3610-6566", False), ("phone_pattern", "0912-345-678", False),
    ("email", "svc@example.com", True), ("email", "a@x.test", True), ("email", "xxxxx@group.calendar.google.com", True),
    ("email", "boss@gmail.com", False), ("email", "info@company.com", False), ("email", "yyyyy@group.calendar.google.com", False),
    ("company_pattern", "範例科技股份有限公司", True), ("company_pattern", "演練測試股份有限公司", True),
    ("company_pattern", "海天整合股份有限公司", False), ("company_pattern", "小林機械廠股份有限公司", False),
    ("address_pattern", "範例市示範區範例路1號", True), ("address_pattern", "台北市信義區市府路1號", False),
    ("docno_pattern", "MQ-202501-001", True), ("docno_pattern", "IV-202609-0001", True), ("docno_pattern", "MQ-202501-001-R1", True),
    ("docno_pattern", "MQ-202607-045", False), ("docno_pattern", "MQ-202608-009", False),
    ("taxid_pattern", "00000000", True), ("taxid_pattern", "12345678", False),
    ("person", "王示範", False), ("secret_literal", "hunter2x", False), ("credential_pattern", "abc12345", False),
])
def test_value_rules(kind, value, ok):
    assert (F.value_problem(kind, value, {}) == "") is ok, (kind, value, F.value_problem(kind, value, {}))


def test_taxid_needs_a_gcis_check_date_unless_it_is_the_reserved_value():
    valid = next("1234560%d" % d for d in range(10) if S.tw_tax_id_valid("1234560%d" % d))
    assert F.value_problem("taxid_pattern", valid, {}) != ""
    assert F.value_problem("taxid_pattern", valid, {"gcis_checked": "2026-09-30"}) == ""
    assert F.value_problem("taxid_pattern", valid, {"gcis_checked": "yesterday"}) != ""


# ── 登記檔驗證與 CLI ────────────────────────────────────────────────────────────────

def test_problems_catch_tampering_missing_reason_and_duplicates():
    good = F.make_entry("company_pattern", "範例甲股份有限公司", "r")
    assert F.problems([good]) == []
    assert F.problems([dict(good, value_id="deadbeef")])                                         # 手改 value_id
    assert F.problems([dict(good, reason="")])                                                   # 沒理由
    assert F.problems([good, dict(good)])                                                        # 重複
    assert F.problems([F.make_entry("company_pattern", "海天整合股份有限公司", "r")])           # 真實樣子的值不能登記
    assert F.problems([dict(good, kind="person")])                                               # 不收的類別


def test_cli_add_refuses_a_real_looking_value_and_writes_nothing(tmp_path, capsys):
    f = tmp_path / "f.json"
    assert F.main(["--file", str(f), "add", "--kind", "phone_pattern", "--value", "04-3610-6566", "--reason", "x"]) == 1
    assert "DEID_FICTION_REFUSED" in capsys.readouterr().out and not f.exists()
    assert F.main(["--file", str(f), "add", "--kind", "phone_pattern", "--value", "02-0000-0001", "--reason", "範例"]) == 0
    assert json.loads(f.read_text(encoding="utf-8"))[0]["value_id"] == S.value_code("phone_pattern", "02-0000-0001")
    assert F.main(["--file", str(f), "check"]) == 0


def test_cli_check_fails_on_a_hand_edited_registry(tmp_path, capsys):
    f = tmp_path / "f.json"
    e = F.make_entry("email", "a@example.com", "r")
    e["value"] = "boss@gmail.com"                                                                # 改明文、沒改 value_id
    f.write_text(json.dumps([e]), encoding="utf-8")
    assert F.main(["--file", str(f), "check"]) == 1
    assert "DEID_FICTION_FAIL" in capsys.readouterr().out


# ── 掃描器為 S3 做的三項收斂（誤判來源）──────────────────────────────────────────────────

def test_scanner_ignores_versions_dates_uuids_and_cache_busters(tmp_path):
    root = _tree(tmp_path, {"a.html": '<link href="style.css?v=20260828a"> chart.js@4.4.0 Mbps@2.4GHz pkg@host-name.co1 "\\n@router.get" '
                                      "day = 86400000; d = 20260801; id = 03000200-0400-0500\n"})
    assert S.scan(root) == []


def test_scanner_still_catches_the_real_shaped_ones_next_to_them(tmp_path):
    valid = next("1234560%d" % d for d in range(10) if S.tw_tax_id_valid("1234560%d" % d))
    root = _tree(tmp_path, {"a.txt": "統編 %s；信箱 boss@corp-demo.co\n" % valid})
    assert sorted(h.kind for h in S.scan(root)) == ["email", "taxid_pattern"]


def test_vendor_files_skip_the_pattern_layer_only(tmp_path):
    valid = next("1234560%d" % d for d in range(10) if S.tw_tax_id_valid("1234560%d" % d))
    root = _tree(tmp_path, {"frontend/static/vendor/lib/min.js": "var a=%s;var b='x@y-corp.co';\n" % valid,
                            "frontend/static/app.js": "var a=%s;\n" % valid})
    assert [(h.path, h.kind) for h in S.scan(root)] == [("frontend/static/app.js", "taxid_pattern")]


def test_unix_home_paths_are_matched_only_from_the_path_start(tmp_path):
    root = _tree(tmp_path, {"a.py": 'u = "https://www.example.org/se/home/mobile/x"\np = "/home/alice/proj"\n'})
    hits = S.scan(root)
    assert [(h.line, h.kind) for h in hits] == [(2, "dev_path")]
