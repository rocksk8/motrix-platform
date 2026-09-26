"""產生檔一致性：dep_graph.json、test_map.json 必須等於現場重產；modules.json 歸屬錯誤必須是 0（比照 UNIT-INDEX 的 --check）。

為什麼（2026-09-26 主持派工）：
- modtest 選題讀這兩份產生檔；過期 ⇒ 新搬的模組檔在圖裡查不到 ⇒ 選題安靜地漏（01:02 之後一度沒人重產，稽核 ⑰ S-2 少選約 49 檔）
- 三支 js（custom-layout、custom-modules-nav、legal-round）未歸屬跟著第二班列車合回，兩班全量都綠：
  tests/platform 的歸屬題只看 router／helper／page／mod／plat（`_boundaries.OWNED_KINDS`），而 `dep_scan --check-modules`
  的 ASSIGNED_KINDS 含 js——同一件事兩份定義。這裡直接呼叫 dep_scan.check_modules（單一定義），不另外列種類。
修法：`python tools/platform/dep_scan.py`、`python tools/platform/test_map.py` 重產後一起提交；歸屬錯誤改 docs/platform/modules.json。
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import dep_scan as D  # noqa: E402
import test_map as TM  # noqa: E402


@pytest.fixture(scope="module")
def graph():
    return D.build()


def _graph_text(g):
    return json.dumps(g, ensure_ascii=False, indent=1, sort_keys=True) + "\n"      # 與 dep_scan.main 寫檔同格式


def test_dep_graph_json_is_current(graph):
    committed = D.OUT.read_text(encoding="utf-8") if D.OUT.exists() else ""
    assert _graph_text(graph) == committed, "docs/platform/dep_graph.json 過期 ⇒ python tools/platform/dep_scan.py 重產後提交"


def test_test_map_json_is_current():
    assert TM.main(["--check"]) == 0, "docs/platform/test_map.json 過期 ⇒ python tools/platform/test_map.py 重產後提交"


def test_modules_json_has_no_ownership_errors(graph):
    errors, _edges = D.check_modules(graph)
    assert not errors, "modules.json 歸屬錯誤（dep_scan --check-modules）：\n  " + "\n  ".join(errors)


# ── 反向控制 ──────────────────────────────────────────────────────────────────

def test_rc_an_unassigned_js_is_an_ownership_error(graph):
    """合成：圖裡多一支沒人認領的 js ⇒ 歸屬錯誤要列出它（第一版的歸屬題看不到 js）。"""
    g = dict(graph, units=dict(graph["units"]))
    g["units"]["js:static/zz_unowned_probe.js"] = {"kind": "js", "path": "frontend/static/zz_unowned_probe.js",
                                                  "imports": [], "routers_called": []}
    errors, _ = D.check_modules(g)
    assert any(e.startswith("js:static/zz_unowned_probe.js") for e in errors), errors


def test_rc_stale_dep_graph_is_detected(graph):
    """合成：已提交的那份少一個單位 ⇒ 不一致。"""
    g = dict(graph, units=dict(graph["units"]))
    g["units"].pop(sorted(g["units"])[0])
    assert _graph_text(g) != _graph_text(graph)


def test_rc_stale_test_map_is_detected(tmp_path, monkeypatch):
    """合成：把比對對象換成一份過期的 test_map.json ⇒ --check 回 1。"""
    stale = tmp_path / "test_map.json"
    stale.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(TM, "OUT", stale)
    assert TM.main(["--check"]) == 1


def test_boundaries_owned_kinds_follow_dep_scan():
    """單一定義：tests/platform 的歸屬題看的種類＝dep_scan 的 ASSIGNED_KINDS（不可以再各走各的）。"""
    from tests.platform import _boundaries as B
    assert set(B.OWNED_KINDS) == set(D.ASSIGNED_KINDS)
