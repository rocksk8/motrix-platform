# -*- coding: utf-8 -*-
"""e2e 的判定不看檔名（wip/b-modtest-batch，主持派工）。

背景：第十班第 1 批重跑時，`test_tender_p9_layout_e2e`（是 e2e、檔名不是 test_e2e_*）被依檔名當成非 e2e，以 -n 4 跑。
2026-09-26 實數：有 e2e marker 而檔名不是 test_e2e_* 的 36 檔／100 題；檔名是 test_e2e_* 而沒有 marker 的 5 檔／24 題。
全量（-m e2e／not e2e）、逐題死線、硬上限都看 **marker**；modtest 的 worker 上限看 test_map 的 kind（同判準，
test_map 沒有那一檔時用 test_map.file_is_e2e 看內容）。這裡守：
① 執行期：用了瀏覽器夾具（new_context／e2e_browser）或模組 import playwright 的題，一定帶 e2e marker（否則沒有死線、全量跑在 -n 4 那段）；
② 有 e2e marker 的檔，test_map 判成 e2e；③ 判定與檔名無關（反向控制）。
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"
sys.path.insert(0, str(REPO / "tools" / "platform"))
import test_map as TM  # noqa: E402

_BROWSER_FIXTURES = ("new_context", "e2e_browser")

#: collect-only 探針（寫到 tmp，以 -p 載入）：每題 ⇒ 是否用瀏覽器、是否有 e2e marker
_PROBE = '''
import json, os
def pytest_collection_finish(session):
    rows = []
    for it in session.items:
        fx = set(getattr(it, "fixturenames", ()) or ())
        mod = getattr(it, "module", None)
        pw = bool(mod) and any(str(getattr(v, "__module__", "") or "").startswith("playwright")
                               for v in vars(mod).values())
        rows.append({"nodeid": it.nodeid, "browser": bool(fx & set(%r)) or pw,
                     "marked": it.get_closest_marker("e2e") is not None})
    with open(os.environ["E2E_PROBE_OUT"], "w", encoding="utf-8") as f:
        json.dump(rows, f)
''' % (_BROWSER_FIXTURES,)


def _collect(tmp_path, cwd, args):
    from tests._subproc import utf8_env
    (tmp_path / "e2e_cls_probe.py").write_text(_PROBE, encoding="utf-8")
    out = tmp_path / "rows.json"
    env = utf8_env(PYTHONPATH=str(tmp_path), E2E_PROBE_OUT=str(out))
    r = subprocess.run([sys.executable, "-m", "pytest", *args, "--collect-only", "-q", "-p", "e2e_cls_probe",
                        "-p", "no:cacheprovider", "--basetemp=%s" % (tmp_path / "bt")],
                       cwd=str(cwd), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=300)
    assert out.is_file(), "探針沒有寫出結果：\n" + (r.stdout + r.stderr)[-1500:]
    return json.loads(out.read_text(encoding="utf-8"))


def _unmarked_browser(rows):
    return sorted(r["nodeid"] for r in rows if r["browser"] and not r["marked"])


def test_every_browser_test_carries_the_e2e_marker(tmp_path):
    """① 全部題（tests＋modules）collect-only：用瀏覽器的題都有 e2e marker。正對照：用瀏覽器的題不是 0。"""
    rows = _collect(tmp_path, BACKEND, ["tests", "modules"])
    browser = [r for r in rows if r["browser"]]
    assert len(browser) > 100, "用瀏覽器的題只有 %d —— 探針量不到東西" % len(browser)
    bad = _unmarked_browser(rows)
    assert not bad, ("這些題用了瀏覽器卻沒有 @pytest.mark.e2e（沒有逐題死線、全量跑在非 e2e 那段 -n 4）：\n  "
                     + "\n  ".join(bad[:30]))
    marked_files = {"backend/" + r["nodeid"].split("::")[0].replace("\\", "/") for r in rows if r["marked"]}
    not_e2e = sorted(f for f in marked_files if not TM.file_is_e2e(REPO / f))
    assert not not_e2e, "② 有 e2e marker 而 test_map 判不成 e2e：%s" % not_e2e


def test_an_unmarked_browser_test_is_caught(tmp_path):
    """反向控制：合成一題用 e2e_browser 夾具而沒有 marker（檔名也不是 test_e2e_*）⇒ 被列出；加了 marker ⇒ 不列。"""
    root = tmp_path / "suite"
    root.mkdir()
    (root / "conftest.py").write_text(
        "import pytest\n@pytest.fixture\ndef e2e_browser():\n    return object()\n"
        "def pytest_configure(config):\n    config.addinivalue_line('markers', 'e2e: x')\n", encoding="utf-8")
    (root / "test_plain_name.py").write_text(
        "import pytest\ndef test_uses_browser(e2e_browser):\n    pass\n"
        "@pytest.mark.e2e\ndef test_marked(e2e_browser):\n    pass\n"
        "def test_no_browser():\n    pass\n", encoding="utf-8")
    rows = _collect(tmp_path, root, ["."])
    assert _unmarked_browser(rows) == ["test_plain_name.py::test_uses_browser"], rows


def test_classification_ignores_the_file_name(tmp_path):
    """③ 反向控制：file_is_e2e 看內容不看檔名——不叫 test_e2e_* 的 e2e 檔 ⇒ True；叫 test_e2e_* 的普通檔 ⇒ False。"""
    cases = {
        "test_marker_only.py": ("import pytest\n@pytest.mark.e2e\ndef test_a():\n    pass\n", True),
        "test_module_mark.py": ("import pytest\npytestmark = pytest.mark.e2e\ndef test_a():\n    pass\n", True),
        "test_fixture_only.py": ("def test_a(e2e_browser):\n    pass\n", True),
        "test_ctx_only.py": ("def test_a(new_context):\n    pass\n", True),
        "test_imports_pw.py": ("from playwright.sync_api import sync_playwright\ndef test_a():\n    pass\n", True),
        "test_e2e_but_plain.py": ("def test_a():\n    assert 1\n", False),
    }
    for name, (src, want) in cases.items():
        p = tmp_path / name
        p.write_text(src, encoding="utf-8")
        assert TM.file_is_e2e(p) is want, (name, want)


def test_modtest_cap_follows_content_not_name(monkeypatch):
    """modtest 的 worker 上限：test_map 沒有那一檔時看內容（同 file_is_e2e），不看檔名。"""
    spec = importlib.util.spec_from_file_location("_modtest_e2ecls", REPO / "tools" / "platform" / "modtest.py")
    MT = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(MT)
    for k in (MT.PARTIAL_ENV, MT.E2E_ENV):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv(MT.PARTIAL_ENV, "4")
    p9 = "backend/modules/tender_radar/tests/test_tender_p9_layout_e2e_2026_09_26.py"
    hard = "backend/tests/test_e2e_hard_cap_2026_09_25.py"
    assert MT.partial_cap([p9], {"tests": {}}) == MT.e2e_max_workers()
    assert MT.partial_cap([hard], {"tests": {}}) == 4
