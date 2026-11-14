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


def test_diff_literals_ignores_docs_and_non_source_paths():
    d = "diff --git a/docs/x.md b/docs/x.md\n--- a/docs/x.md\n+++ b/docs/x.md\n@@ -1 +1 @@\n-這是文件裡刪掉的舊文案\n+新\n"
    assert Q.diff_literals(d) == []


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
