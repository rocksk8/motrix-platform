# -*- coding: utf-8 -*-
"""去識別化 S4：sale 包剪裁與投影（tools/platform/deid_project.py＋product/sale_prune.json）。

反向控制：標記不是恰好一組 ⇒ 丟例外（不猜）；基準前後的 manifest 條目各自照規則；剪裁設定不准剪到出貨必需的檔；
sale 包裡出現 docs/windows、交接文件、drill 工具、own_payload、tests 一律被 verify 擋下。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import deid_project as P  # noqa: E402
import deid_scan as S  # noqa: E402

CFG = P.load_config()


def _write(root, files):
    for rel, text in files.items():
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    return Path(root)


# ── glob／剪檔 ──────────────────────────────────────────────────────────────────────

def test_glob_semantics():
    assert P.matches("docs/platform/a/b.md", ["docs/**"]) and P.matches("docs/x.md", ["docs/**"])
    assert P.matches("tools/platform/x.py", ["tools/platform/**"]) and not P.matches("tools/other/x.py", ["tools/platform/**"])
    assert P.matches("a.md", ["*.md"]) and not P.matches("dir/a.md", ["*.md"]), "* 不跨目錄"
    assert P.matches("backend/tests/x/y.py", ["backend/tests/**"])
    assert P.matches(".gitignore", [".gitignore"]) and not P.matches("sub/.gitignore", [".gitignore"])


def test_plan_remove_respects_keep():
    files = ["tools/platform/upgrade.py", "tools/platform/modtest.py", "tools/platform/deid_scan.py", "docs/platform/a.md", "backend/main.py"]
    assert sorted(P.plan_remove(files, CFG)) == ["docs/platform/a.md", "tools/platform/deid_scan.py", "tools/platform/modtest.py"]


def test_config_never_removes_what_the_running_product_needs():
    """守門：剪裁設定不得涵蓋 backend／frontend（除 pytest.ini）與升級精靈需要的四支工具。"""
    for rel in ("backend/main.py", "backend/db.py", "backend/core/upgrade.py", "backend/helpers/auth.py", "frontend/pages/login.html",
                "backend/modules/case/module.json", "backend/version_manifest.json", "tools/platform/upgrade.py", "tools/platform/module_update.py",
                "tools/platform/product_select.py", "tools/platform/ship_tier.py", "product/full.json", "DEPLOY.md", "start_server.ps1"):
        assert P.plan_remove([rel], CFG) == [], rel


# ── 剪段 ─────────────────────────────────────────────────────────────────────────────

SRC = "a = 1\n# >>> OWN-ONLY:x\nSECRET = 'v'\n# <<< OWN-ONLY:x\nb = 2\n"


def test_cut_replaces_exactly_the_marked_region_including_markers():
    out = P.cut_text(SRC, "x", "SECRET = None")
    assert out == "a = 1\nSECRET = None\nb = 2\n"


@pytest.mark.parametrize("src", ["a=1\n", SRC + SRC, SRC.replace("# <<< OWN-ONLY:x\n", ""), SRC.replace("# >>> OWN-ONLY:x\n", "")])
def test_cut_refuses_anything_but_exactly_one_pair(src):
    with pytest.raises(P.ProjectError):
        P.cut_text(src, "x", "SECRET = None")


def test_apply_cuts_keeps_crlf(tmp_path):
    p = tmp_path / "f.py"
    p.write_bytes(SRC.replace("\n", "\r\n").encode("utf-8"))
    P.apply_cuts(tmp_path, [{"path": "f.py", "name": "x", "stub": "SECRET = None"}])
    assert p.read_bytes() == b"a = 1\r\nSECRET = None\r\nb = 2\r\n"


# ── manifest 投影 ─────────────────────────────────────────────────────────────────────

def test_sort_key_matches_the_product_and_handles_letter_rollover():
    sys.path.insert(0, str(REPO / "backend"))
    from helpers.startup import version_sort_key as prod
    for v in ("2026-09-30a", "2026-09-30z", "2026-09-30aa", "2026-10-01", "bad", ""):
        assert P.version_sort_key(v) == prod(v)
    assert P.version_sort_key("2026-09-30aa") > P.version_sort_key("2026-09-30z")


def test_projection_generic_up_to_the_baseline_and_overlay_after_it():
    ents = [{"module": "m", "version": "2026-09-29z", "date": "d", "time": "t", "content": "識別資料1"},
            {"module": "m", "version": "2026-09-30a", "date": "d", "time": "t", "content": "識別資料2"},
            {"module": "m", "version": "2026-09-30aa", "date": "d", "time": "t", "content": "識別資料3"},
            {"module": "n", "version": "2026-09-30aa", "date": "d", "time": "t", "content": "原文"}]
    out = P.project_entries(ents, "2026-09-30a", {"m|2026-09-30aa": "去識別後的內文"})
    assert [e["content"] for e in out] == [P.GENERIC_CONTENT, P.GENERIC_CONTENT, "去識別後的內文", "原文"]
    assert all({k: v for k, v in a.items() if k != "content"} == {k: v for k, v in b.items() if k != "content"} for a, b in zip(ents, out)), "版本鍵不可動"
    assert ents[0]["content"] == "識別資料1", "不改輸入"


def test_project_manifest_writes_one_entry_per_line_and_reports_changes(tmp_path):
    ents = [{"module": "m", "version": "2026-09-01", "date": "d", "time": "t", "content": "x"}, {"module": "m", "version": "2026-10-01", "date": "d", "time": "t", "content": "y"}]
    root = _write(tmp_path, {P.MANIFEST_REL: json.dumps(ents)})
    n = P.project_manifest(root, dict(CFG, manifest_baseline="2026-09-30"), {})
    text = (root / P.MANIFEST_REL).read_text(encoding="utf-8")
    assert n == 1 and json.loads(text)[0]["content"] == P.GENERIC_CONTENT and json.loads(text)[1]["content"] == "y" and text.count("\n") == 4


def test_the_committed_baseline_is_not_ahead_of_the_manifest():
    """基準只能等於或落後於 manifest 最新版（超前 ⇒ 之後出的條目都會被當成基準前而洗掉）。"""
    ents = json.loads((REPO / "backend" / "version_manifest.json").read_text(encoding="utf-8"))
    newest = max((e["version"] for e in ents), key=P.version_sort_key)
    assert P.version_sort_key(CFG["manifest_baseline"]) <= P.version_sort_key(newest)


# ── verify 的反向控制 ─────────────────────────────────────────────────────────────────

def _mini_pkg(tmp_path):
    return _write(tmp_path / "pkg", {
        "backend/core/upgrade.py": "x = 1\n# sale 包：不含任何公司預設值（升級精靈不回填公司資料；本段在 own 包才有）。\nV9_COMPANY_DEFAULTS = {}\n"
                                   "def _is_our_install(profile: dict) -> bool:\n    return False\n",
        P.MANIFEST_REL: P.dump_manifest([{"module": "m", "version": "2026-09-01", "date": "d", "time": "t", "content": P.GENERIC_CONTENT}]),
        "backend/main.py": "pass\n",
        "DEPLOY.md": "客戶版 <安裝目錄>\n", "DR-SOP.md": "客戶版 <安裝目錄>\n", "HTTPS-DEPLOY-CHECKLIST.md": "客戶版 <安裝目錄>\n"})


def test_verify_accepts_a_clean_pruned_package(tmp_path):
    assert P.verify_tree(_mini_pkg(tmp_path), CFG) == []


@pytest.mark.parametrize("extra", ["docs/windows/STATE.md", "docs/platform/PLAYBOOK.md", "NEXT-SESSION.md", "MULTIWIN-PROTOCOL.md", ".claude/settings.json",
                                   "tools/platform/deid_scan.py", "tools/platform/own_payload.py", "tools/platform/upgrade_drill.py",
                                   "backend/migrations_frozen/own_payload.json", "backend/tests/test_x.py", "NETWORK-PLAN-MODULE-DESIGN.md", "CHANGELOG.md"])
def test_verify_rejects_forbidden_paths(tmp_path, extra):
    root = _mini_pkg(tmp_path)
    _write(root, {extra: "x\n"})
    assert any(extra in p for p in P.verify_tree(root, CFG)), extra


def test_verify_rejects_the_original_internal_docs_and_missing_customer_docs(tmp_path):
    root = _mini_pkg(tmp_path)
    (root / "DEPLOY.md").write_text("這一包新增了標案雷達，路徑寫死在正式機安裝目錄", encoding="utf-8")        # 原檔沒被取代
    assert any("DEPLOY.md" in p and "不是客戶版" in p for p in P.verify_tree(root, CFG))
    (root / "DR-SOP.md").unlink()
    assert any("DR-SOP.md" in p and "不存在" in p for p in P.verify_tree(root, CFG))


def test_replace_overwrites_from_the_in_package_source_and_refuses_a_missing_source(tmp_path):
    root = _write(tmp_path, {"DEPLOY.md": "原檔", "product/sale_docs/DEPLOY.md": "客戶版"})
    assert P.apply_replacements(root, {"DEPLOY.md": "product/sale_docs/DEPLOY.md"}) == ["DEPLOY.md"]
    assert (root / "DEPLOY.md").read_text(encoding="utf-8") == "客戶版"
    with pytest.raises(P.ProjectError):
        P.apply_replacements(root, {"DEPLOY.md": "product/sale_docs/NOPE.md"})


def test_verify_rejects_leftover_own_only_and_unprojected_manifest(tmp_path):
    root = _mini_pkg(tmp_path)
    (root / "backend/core/upgrade.py").write_text("# >>> OWN-ONLY:x\nA = 1\n# <<< OWN-ONLY:x\n", encoding="utf-8")
    assert any("OWN-ONLY" in p for p in P.verify_tree(root, CFG))
    root2 = _mini_pkg(tmp_path / "b")
    (root2 / P.MANIFEST_REL).write_text(P.dump_manifest([{"module": "m", "version": "2026-09-01", "date": "d", "time": "t", "content": "識別資料"}]), encoding="utf-8")
    assert any("未投影" in p for p in P.verify_tree(root2, CFG))


# ── 整合：從 git 重算（HEAD） ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def sale_tree(tmp_path_factory):
    out = tmp_path_factory.mktemp("sale") / "pkg"
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    src = subprocess.run(["git", "-C", str(REPO), "show", head + ":backend/core/upgrade.py"], capture_output=True, text=True, encoding="utf-8").stdout
    assert "OWN-ONLY:v9-company-defaults" in src and "OWN-ONLY:is-our-install" in src, "HEAD 的 core/upgrade.py 還沒有 OWN-ONLY 標記（先 commit）"
    rep = P.rebuild(head, out)
    return out, rep


def test_rebuilt_sale_package_passes_verify_and_has_no_company_literals_in_upgrade(sale_tree):
    root, rep = sale_tree
    assert P.verify_tree(root, CFG) == [], P.verify_tree(root, CFG)
    assert rep["removed"] > 100 and len(rep["cuts"]) == 2 and rep["manifest_projected"] > 100 and len(rep["replaced"]) == 3
    assert not (root / "product" / "sale_docs").exists(), "客戶版文件的來源目錄不可留在 sale 包"
    for doc in ("DEPLOY.md", "DR-SOP.md", "HTTPS-DEPLOY-CHECKLIST.md"):
        assert "<安裝目錄>" in (root / doc).read_text(encoding="utf-8") and [h for h in S.scan(root) if h.path == doc] == [], doc
    hits = [h for h in S.scan(root) if h.path == "backend/core/upgrade.py"]
    assert hits == [], hits


def test_cut_upgrade_module_behaves_as_a_non_own_install(sale_tree, tmp_path):
    import importlib.util
    import sqlite3
    root, _ = sale_tree
    spec = importlib.util.spec_from_file_location("_sale_upgrade", root / "backend" / "core" / "upgrade.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.V9_COMPANY_DEFAULTS == {} and m._is_our_install({"tax_id": "60575481"}) is False
    db = tmp_path / "t.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE system_settings (key TEXT PRIMARY KEY, value_json TEXT)")
    c.execute("INSERT INTO system_settings VALUES ('company_profile', ?)", (json.dumps({"tax_id": "60575481"}),))
    c.commit()
    c.close()
    r = m.fill_company_profile_blanks(str(db))
    assert r["filled"] == {} and r["skipped"]


def test_rebuild_is_deterministic(sale_tree, tmp_path):
    root, _ = sale_tree
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    P.rebuild(head, tmp_path / "again")
    assert P.tree_digest(root) == P.tree_digest(tmp_path / "again")


def test_the_own_tree_is_untouched_by_the_markers_only_comments():
    """own 包不剪：標記只是註解，模組 import 出來仍有本公司預設值（升級回填照舊）。"""
    sys.path.insert(0, str(REPO / "backend"))
    from core import upgrade as U
    assert U.V9_COMPANY_DEFAULTS and U._is_our_install({"tax_id": U.V9_COMPANY_DEFAULTS["tax_id"]}) is True
