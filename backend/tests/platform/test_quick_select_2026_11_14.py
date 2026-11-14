# -*- coding: utf-8 -*-
"""author_gate --quick 的選題（tools/platform/quick_select.py；T87 A2）。純函式＋注入 grep，不碰 git、不跑 pytest。

要釘住的不變式：
  * 整合守門組的規則只有 preflight_guards.json 一份（這裡用小設定驗行為，另有一題驗真實設定的結構）。
  * T0–T3 一律要跑；T4 依預算由後往前砍，**每個被砍的都在 skipped**（輸出必須寫「未跑」，不能看起來像通過）。
  * 字面值反查只認「被刪掉、且沒有在新增行重新出現」的字；測試檔自己的改動不算；太通用的字不選（寫進 notes）。
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))

import quick_select as Q  # noqa: E402

CFG = [
    {"id": "changelog", "label": "CHANGELOG", "paths": ["tests/platform/test_changelog.py"], "watch": ["backend/modules/*/CHANGELOG.md"], "min_tests": 5},
    {"id": "wide", "label": "寬", "paths": ["tests/test_wide.py"], "watch": ["backend/**"], "min_tests": 5},
    {"id": "static_scans2", "label": "全倉靜態掃描", "paths": ["tests/test_big_*.py"], "watch": ["frontend/**"], "min_tests": 650},
]
TREE = ["backend/tests/platform/test_changelog.py", "backend/tests/test_wide.py", "backend/tests/test_big_1.py", "backend/tests/test_big_2.py",
        "backend/tests/test_old_wording.py", "backend/tests/test_pattern_guard.py", "backend/tests/test_own.py", "backend/tests/test_changed.py"]

DIFF = """diff --git a/frontend/pages/x.html b/frontend/pages/x.html
--- a/frontend/pages/x.html
+++ b/frontend/pages/x.html
@@ -1,2 +1,2 @@
-<span>您尚無待簽核的單據</span>
-<span>仍然存在的字面值文字</span>
+<span>尚無您需要簽核的項目</span>
+<span>仍然存在的字面值文字</span>
diff --git a/backend/tests/test_changed.py b/backend/tests/test_changed.py
--- a/backend/tests/test_changed.py
+++ b/backend/tests/test_changed.py
@@ -1 +1 @@
-assert "測試檔自己刪掉的字面值"
+assert True
"""


def _groups():
    return Q.groups_from_tree(CFG, TREE)


def _plan(grep_map, *, changed=None, budget_s=10_000, a2=None, a4=None, t4=None, sec=lambda f: 10.0):
    grep = lambda tok: list(grep_map.get(tok, []))      # noqa: E731
    return Q.plan_quick(changed=changed or ["frontend/pages/x.html"], diff_text=DIFF, tree_files=TREE, a2=a2 or [], a4=a4 or [],
                        extra_t4=t4 or [], repo=".", ref=None, seconds_fn=sec, workers=1, budget_s=budget_s, groups=_groups(), grep_fn=grep)


# ── 整合守門組（觸發規則）────────────────────────────────────────────────

def test_groups_resolve_against_the_git_tree_not_the_disk():
    g = _groups()
    assert g["changelog"]["files"] == ["backend/tests/platform/test_changelog.py"]
    assert g["static_scans2"]["heavy"] is True and g["wide"]["heavy"] is False
    assert g["static_scans2"]["files"] == ["backend/tests/test_big_1.py", "backend/tests/test_big_2.py"]


def test_a_group_is_triggered_only_by_files_its_watch_globs_match():
    trig = dict(Q.triggered_groups(["backend/modules/case/CHANGELOG.md"], _groups()))
    assert "changelog" in trig and "wide" in trig and "static_scans2" not in trig
    none = Q.triggered_groups(["docs/x.md"], _groups())
    assert none == []


def test_narrow_watch_matches_sort_before_wide_ones():
    order = [gid for gid, _ in Q.triggered_groups(["backend/modules/case/CHANGELOG.md"], _groups())]
    assert order.index("changelog") < order.index("wide")


def test_heavy_groups_are_reported_as_not_run_never_silently_dropped():
    plan = _plan({}, changed=["frontend/pages/x.html"])
    assert any(s["tier"] == "T1" and "static_scans2" in s["item"] and "太大" in s["reason"] for s in plan["skipped"]), plan["skipped"]
    assert "backend/tests/test_big_1.py" not in plan["files"]


def test_real_preflight_config_loads_and_every_group_has_watch_and_paths():
    groups = Q.load_groups()
    assert len(groups) >= 20
    for g in groups:
        assert g["paths"] and g.get("label"), g["id"]
        assert g.get("watch"), "整合守門組 %s 沒有 watch：沒有觸發條件的組在 quick 永遠不會被選到" % g["id"]
    ids = {g["id"] for g in groups}
    assert set(Q.HEAVY_GROUPS) <= ids, "HEAVY_GROUPS 指到不存在的組（被改名？）"


# ── 字面值反查 ──────────────────────────────────────────────────────────

def test_diff_literals_keeps_only_text_that_really_disappeared_from_source_files():
    lits = Q.diff_literals(DIFF)
    assert "您尚無待簽核的單據" in lits
    assert "仍然存在的字面值文字" not in lits, "刪掉又在新增行重新出現的字，測試不會因此紅"
    assert "測試檔自己刪掉的字面值" not in lits, "測試檔自己的改動不是『來源變了』"


def test_diff_literals_prefers_long_and_drops_substrings_of_kept_ones():
    d = ("diff --git a/frontend/a.html b/frontend/a.html\n--- a/frontend/a.html\n+++ b/frontend/a.html\n@@ -1 +1 @@\n"
         "-<p>這是一整句很長的舊文案內容</p> <b>舊文案內容</b>\n+<p>新</p>\n")
    lits = Q.diff_literals(d)
    assert lits[0] == "這是一整句很長的舊文案內容" and "舊文案內容" not in lits


def test_diff_literals_reads_docs_and_markdown_but_ignores_paths_outside_the_source_roots():
    doc = "diff --git a/docs/x.md b/docs/x.md\n--- a/docs/x.md\n+++ b/docs/x.md\n@@ -1 +1 @@\n-這是文件裡刪掉的舊文案\n+新\n"
    assert Q.diff_literals(doc) == ["這是文件裡刪掉的舊文案"], "測試會讀 CHANGELOG／MODULE-GUIDE 之類的文件文字（S3）"
    other = "diff --git a/misc/x.md b/misc/x.md\n--- a/misc/x.md\n+++ b/misc/x.md\n@@ -1 +1 @@\n-這是範圍外檔案的舊文案\n+新\n"
    assert Q.diff_literals(other) == []


def test_literal_hits_become_t2_and_generic_literals_are_noted_not_selected():
    generic = ["backend/tests/test_g%d.py" % i for i in range(Q.LITERAL_MAX_HITS + 1)]
    plan = _plan({"您尚無待簽核的單據": ["backend/tests/test_old_wording.py"]})
    assert plan["tiers"]["T2"]["files"] == ["backend/tests/test_old_wording.py"]
    assert "您尚無待簽核的單據" in plan["tiers"]["T2"]["why"]["backend/tests/test_old_wording.py"]
    plan2 = _plan({"您尚無待簽核的單據": generic})
    assert plan2["tiers"]["T2"]["files"] == []
    assert any("太通用" in n for n in plan2["notes"]), plan2["notes"]


# ── 優先層與預算 ──────────────────────────────────────────────────────────

def test_tiers_are_ordered_and_a_file_belongs_to_its_first_tier_only():
    plan = _plan({"您尚無待簽核的單據": ["backend/tests/test_old_wording.py", "backend/tests/test_changed.py"]},
                 changed=["backend/modules/case/CHANGELOG.md", "frontend/pages/x.html"],
                 a2=["backend/tests/test_pattern_guard.py", "backend/tests/test_wide.py"], a4=["backend/tests/test_changed.py"],
                 t4=["backend/tests/test_own.py", "backend/tests/test_old_wording.py"])
    t = plan["tiers"]
    assert t["T0"]["files"] == ["backend/tests/test_changed.py"]
    assert "backend/tests/platform/test_changelog.py" in t["T1"]["files"] and "backend/tests/test_wide.py" in t["T1"]["files"]
    assert t["T2"]["files"] == ["backend/tests/test_old_wording.py"]           # test_changed 已在 T0
    assert t["T3"]["files"] == ["backend/tests/test_pattern_guard.py"]          # test_wide 已在 T1
    assert t["T4"]["files"] == ["backend/tests/test_own.py"]                    # test_old_wording 已在 T2
    assert len(plan["files"]) == len(set(plan["files"]))


def test_budget_cuts_only_t4_and_lists_every_cut_file_as_not_run():
    t4 = ["backend/tests/test_own_%d.py" % i for i in range(6)]
    plan = _plan({}, a4=["backend/tests/test_changed.py"], t4=t4, budget_s=35, sec=lambda f: 10.0)      # 必跑 10 s；T4 每檔 10 s ⇒ 只容得下 2 檔
    assert plan["tiers"]["T4"]["run"] == t4[:2]
    cut = [s for s in plan["skipped"] if s["tier"] == "T4"]
    assert [s["item"] for s in cut] == t4[2:] and all("未跑" in s["reason"] for s in cut)
    assert plan["files"][-2:] == t4[:2] and not any(f in plan["files"] for f in t4[2:])


def test_must_tiers_are_never_cut_over_budget_only_warned():
    plan = _plan({}, a4=["backend/tests/test_changed.py"], a2=["backend/tests/test_pattern_guard.py"], t4=["backend/tests/test_own.py"], budget_s=5)
    assert "backend/tests/test_changed.py" in plan["files"] and "backend/tests/test_pattern_guard.py" in plan["files"]
    assert plan["tiers"]["T4"]["run"] == []
    assert any("已超過預算" in n for n in plan["notes"]), plan["notes"]


def test_format_plan_says_not_run_when_something_was_cut():
    plan = _plan({}, a4=["backend/tests/test_changed.py"], t4=["backend/tests/test_own.py"], budget_s=5)
    text = Q.format_plan(plan)
    assert "未跑" in text and "不是通過" in text and "T4" in text


def test_reference_keys_use_page_js_and_tool_names_but_skip_generic_ones():
    keys = Q.reference_keys(["frontend/pages/settlement.html", "frontend/static/sidebar.js", "frontend/index.html", "tools/platform/core_major_bump.py",
                             "backend/tests/test_x.py", "backend/modules/case/api/quotes.py"])
    assert keys == ["core_major_bump", "settlement.html", "sidebar.js"]


# ── 反向探針（測試字面值 ⊂ 被刪文字）與 quick 專用觸發組 ─────────────────────────

def test_test_tokens_catch_a_test_that_asserts_a_substring_of_the_removed_source_text():
    d = ("diff --git a/frontend/pages/y.html b/frontend/pages/y.html\n--- a/frontend/pages/y.html\n+++ b/frontend/pages/y.html\n@@ -1 +1 @@\n"
         "-<p>您沒有任何變動可儲存</p>\n+<p>目前沒有可儲存的內容</p>\n")
    lits = Q.diff_literals(d, {"沒有任何變動", "完全無關的字面值", "目前沒有可儲存的內容"})
    assert "沒有任何變動" in lits, "測試只斷言來源整句的一小段：只拿整句去 grep 會漏（T86 c03909aa6 的主要型態）"
    assert "完全無關的字面值" not in lits and "目前沒有可儲存的內容" not in lits


def test_without_test_tokens_diff_literals_behaves_as_before():
    assert Q.diff_literals(DIFF) == Q.diff_literals(DIFF, None) == Q.diff_literals(DIFF, set())


def test_quick_extra_groups_cover_the_t86_red_types_preflight_watches_missed():
    tree = ["backend/tests/platform/test_module_boundaries.py", "backend/tests/platform/test_e2e_lint_2026_11_13.py",
            "backend/tests/platform/test_page_paths_centralized.py", "backend/tests/platform/test_no_direct_js_enumeration_2026_11_08.py"]
    groups = Q.groups_from_tree(Q.load_groups(), tree)
    trig = lambda changed: {g for g, _ in Q.triggered_groups(changed, groups)}      # noqa: E731
    assert "q_boundaries" in trig(["backend/routers/bootstrap.py"])
    assert {"q_e2e_lint", "q_page_paths"} <= trig(["backend/modules/case/tests/test_dev_crm_ux_batch_a_t86_2026_11_14.py"])
    assert not ({"q_boundaries", "q_e2e_lint", "q_page_paths"} & trig(["docs/x.md"]))
    assert groups["q_boundaries"]["files"] == ["backend/tests/platform/test_module_boundaries.py"]


def test_extra_groups_do_not_override_preflight_ids_and_can_be_switched_off():
    ids = [g["id"] for g in Q.load_groups()]
    assert len(ids) == len(set(ids))
    assert not any(g["id"].startswith("q_") for g in Q.load_groups(extra=False))


# ── h11 審查（M1／M3／S1／S2／S4）與 PM 補充（路由／頁面→測試、e2e 最後）────────────

def _file_diff(path, removed, added):
    return "diff --git a/%s b/%s\n--- a/%s\n+++ b/%s\n@@ -1 +1 @@\n%s%s" % (
        path, path, path, path, "".join("-%s\n" % r for r in removed), "".join("+%s\n" % a for a in added))


def test_m1_generic_literal_selects_the_narrowest_subset_and_lists_the_rest_as_not_run():
    same_module = ["backend/modules/case/tests/test_m%d.py" % i for i in range(2)]
    others = ["backend/tests/test_o%d.py" % i for i in range(Q.LITERAL_MAX_HITS)]
    diff = _file_diff("backend/modules/case/api/q.py", ["msg = '這是一句舊的提示文字'"], ["msg = '新'"])
    plan_diff = Q.plan_quick(changed=["backend/modules/case/api/q.py"], diff_text=diff, tree_files=TREE, a2=[], a4=[], extra_t4=[], repo=".", ref=None,
                             seconds_fn=lambda f: 1.0, workers=1, budget_s=10_000, groups=_groups(),
                             grep_fn=lambda tok: (same_module + others) if tok == "這是一句舊的提示文字" else [])
    assert set(plan_diff["tiers"]["T2"]["files"]) == set(same_module), "只選同模組目錄的測試"
    cut = [s for s in plan_diff["skipped"] if s["tier"] == "T2" and "太通用" in s["reason"]]
    assert cut and "未跑" in cut[0]["reason"] and "其餘 %d 檔未選題" % len(others) in cut[0]["reason"], plan_diff["skipped"]


def test_m1_truncated_literals_and_unavailable_reverse_probe_are_listed_as_not_run(monkeypatch):
    many = ["    x = '字面值第%03d個舊文案'" % i for i in range(Q.MAX_LITERALS + 5)]
    diff = _file_diff("frontend/pages/z.html", [m.strip() for m in many], [])
    plan = Q.plan_quick(changed=["frontend/pages/z.html"], diff_text=diff, tree_files=TREE, a2=[], a4=[], extra_t4=[], repo=".", ref=None,
                        seconds_fn=lambda f: 1.0, workers=1, budget_s=10_000, groups=_groups(), grep_fn=lambda tok: [])
    assert any(s["tier"] == "T2" and "截斷" in s["reason"] and "未跑" in s["reason"] for s in plan["skipped"]), plan["skipped"]
    monkeypatch.setattr(Q, "load_test_tokens", lambda repo, ref=None: None)
    plan2 = Q.plan_quick(changed=["frontend/pages/x.html"], diff_text=DIFF, tree_files=TREE, a2=[], a4=[], extra_t4=[], repo=str(REPO), ref=None,
                         seconds_fn=lambda f: 1.0, workers=1, budget_s=10_000, groups=_groups(), grep_fn=None)
    assert any("反向探針" in s["item"] and "未跑" in s["reason"] for s in plan2["skipped"]), plan2["skipped"]


def test_m3_deleted_or_renamed_paths_trigger_groups_and_name_references_but_never_reach_pytest():
    groups = _groups()
    plan = Q.plan_quick(changed=[], deleted=["backend/modules/case/CHANGELOG.md", "frontend/pages/old_page.html"], diff_text="", tree_files=TREE, a2=[], a4=[],
                        extra_t4=[], repo=".", ref=None, seconds_fn=lambda f: 1.0, workers=1, budget_s=10_000, groups=groups,
                        grep_fn=lambda tok: ["backend/tests/test_old_wording.py"] if tok == "old_page.html" else [])
    assert "backend/tests/platform/test_changelog.py" in plan["tiers"]["T1"]["files"], "刪掉的檔的舊路徑也要觸發守門組"
    assert "backend/tests/test_old_wording.py" in plan["tiers"]["T4"]["files"], "引用舊檔名的測試要被選到（FileNotFound 型紅燈）"
    assert not any(f.endswith((".md", ".html")) for f in plan["files"])


def test_s1_removed_literal_that_reappears_in_another_file_still_counts_for_the_file_it_left():
    d = (_file_diff("frontend/pages/a.html", ["<p>這是被搬走的舊文案</p>"], []) +
         _file_diff("frontend/pages/b.html", [], ["<p>這是被搬走的舊文案</p>"]))
    assert "這是被搬走的舊文案" in Q.diff_literals(d), "同一個字出現在別的檔的新增行，不代表原本那個檔還有它"
    same = _file_diff("frontend/pages/a.html", ["<p>這是留在原檔的舊文案</p>"], ["<p>這是留在原檔的舊文案</p>"])
    assert Q.diff_literals(same) == []


def test_s2_hits_in_helpers_and_conftest_are_not_run_as_tests_and_are_listed():
    hits, skipped = Q.split_helper_hits({"backend/tests/test_a.py": ["x"], "backend/tests/conftest.py": ["y"], "backend/tests/_helper.py": ["z"]},
                                        ".", None, grep_fn=lambda t: [])
    assert list(hits) == ["backend/tests/test_a.py"]
    assert {s["item"] for s in skipped} == {"backend/tests/conftest.py", "backend/tests/_helper.py"} and all("未跑" in s["reason"] for s in skipped)


def test_s4_short_labels_attributes_and_camel_identifiers_are_literals():
    toks = Q.literals_of(['<button id="btn-save" class="btn primary" x-model="loadItems">儲存</button>', "const retryCount = 1; const maxAttempts = 3"])
    assert {"儲存", "btn-save", "loadItems", "retryCount", "maxAttempts", "primary"} <= toks
    assert "const" not in toks and "retry" not in toks, "純小寫短字、識別字的片段不當字面值"


def test_route_changes_select_the_tests_that_call_those_routes_and_e2e_goes_last(tmp_path):
    src = ("from fastapi import APIRouter\nrouter = APIRouter(prefix='/api/quotations')\n\n"
           "@router.put('/{no}')\ndef put_q(no):\n    return 1\n\n@router.get('/summary')\ndef summary():\n    return 2\n")
    assert Q.routes_in_ranges(src, [(5, 6)]) == ["/api/quotations/"], "只有改到的路由；固定前綴（{no} 之前）"
    assert Q.routes_in_ranges(src, [(9, 9)]) == ["/api/quotations/summary"]
    assert Q.routes_in_ranges(src, [(1, 1)]) == []
    (tmp_path / "backend" / "routers").mkdir(parents=True)
    (tmp_path / "backend" / "routers" / "q.py").write_text(src, encoding="utf-8")
    tests = {"/api/quotations/": ["backend/tests/test_e2e_q.py", "backend/tests/test_q_api.py"]}
    diff = ("diff --git a/backend/routers/q.py b/backend/routers/q.py\n--- a/backend/routers/q.py\n+++ b/backend/routers/q.py\n"
            "@@ -5,2 +5,2 @@\n-    return 0\n+    return 1\n")
    plan = Q.plan_quick(changed=["backend/routers/q.py"], diff_text=diff, tree_files=TREE, a2=[], a4=[], extra_t4=[], repo=str(tmp_path), ref=None,
                        seconds_fn=lambda f: 1.0, workers=1, budget_s=10_000, groups=_groups(), grep_fn=lambda tok: tests.get(tok, []))
    assert plan["routes"] == ["/api/quotations/"]
    assert plan["tiers"]["T4"]["files"] == ["backend/tests/test_q_api.py", "backend/tests/test_e2e_q.py"], "打這個路由的測試進 T4，e2e 排最後"


def test_t4_orders_e2e_last_so_the_budget_cuts_e2e_first_and_says_so():
    t4 = ["backend/tests/test_e2e_a.py", "backend/tests/test_b.py", "backend/tests/test_e2e_c.py", "backend/tests/test_d.py"]
    plan = _plan({}, a4=[], t4=t4, budget_s=2, sec=lambda f: 1.0)
    assert plan["tiers"]["T4"]["files"] == ["backend/tests/test_b.py", "backend/tests/test_d.py", "backend/tests/test_e2e_a.py", "backend/tests/test_e2e_c.py"]
    assert plan["tiers"]["T4"]["run"] == ["backend/tests/test_b.py", "backend/tests/test_d.py"]
    assert {s["item"] for s in plan["skipped"] if s["tier"] == "T4"} == {"backend/tests/test_e2e_a.py", "backend/tests/test_e2e_c.py"}


def test_n1_over_budget_is_a_flag_in_the_plan_and_in_the_text():
    plan = _plan({}, a4=["backend/tests/test_changed.py"], budget_s=5, sec=lambda f: 60.0)
    assert plan["over_budget"] is True and "超過預算" in Q.format_plan(plan)
    assert _plan({}, a4=["backend/tests/test_changed.py"], budget_s=10_000)["over_budget"] is False
