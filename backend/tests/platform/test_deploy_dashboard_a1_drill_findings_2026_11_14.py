"""2026-11-14 A1 演練抓到的兩個產品缺陷（正式機同樣會發生）：
1. 確認框的刪除計畫試算（_delivery_summary）跑暫存包自己的 apply_plan.py，沒加 -B ⇒ .pyc 寫進暫存包 ⇒ 預演後完整性重驗判「清單外多出的檔」而擋下。
2. 預演畫面等 `x.rehearsing === false`，伺服器閒置時回 null ⇒ 永遠等不到，畫面停在「預演中…」。"""
import importlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend" / "tools"))

# HC1c：這個檔名可以直接 import 儀表板；用 importlib 取該檔的 dd 與重用既有夾具，和 test_a1_auto_apply 同一做法
dd = importlib.import_module("tests.platform." + "test_deploy_dashboard_delivery_2026_09_28").dd

HTML = (REPO / "backend" / "tools" / "deploy_dashboard.html").read_text(encoding="utf-8")


def _fake_staged(tmp_path):
    staged = tmp_path / "staged"
    tools = staged / "payload" / "backend" / "tools"
    core = staged / "payload" / "backend" / "core"
    tools.mkdir(parents=True)
    core.mkdir(parents=True)
    (core / "__init__.py").write_text("", encoding="utf-8")
    (core / "upgrade.py").write_text("X = 1\n", encoding="utf-8")
    (tools / "apply_plan.py").write_text(
        "import json, os, sys\n"
        "sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))\n"
        "import core.upgrade\n"                                   # 和真的 apply_plan 一樣：import 暫存包自己的 backend
        "out = sys.argv[sys.argv.index('--out') + 1]\n"
        "json.dump({'delete': [], 'added': []}, open(out, 'w'))\n", encoding="utf-8")
    return staged


def test_delivery_summary_leaves_no_pyc_in_staged_package(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    monkeypatch.setattr(dd, "DELIVERY_INSTALL_ROOT", tmp_path / "inst")
    (tmp_path / "inst" / "backend").mkdir(parents=True)
    staged = _fake_staged(tmp_path)
    out = dd._delivery_summary(str(staged))
    assert out["deleteCount"] == 0 and out["addedCount"] == 0, out      # 工具真的跑過了（不是被略過而假綠）
    assert not list(staged.rglob("__pycache__")) and not list(staged.rglob("*.pyc"))


def test_delivery_summary_positive_control_pyc_would_appear_without_dash_b(tmp_path, monkeypatch):
    """正對照：同一個假包用「不加 -B」的方式跑，確實會留下 .pyc ⇒ 上一題的斷言有鑑別力。"""
    import subprocess
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    staged = _fake_staged(tmp_path)
    plan = staged / "payload" / "backend" / "tools" / "apply_plan.py"
    subprocess.run([sys.executable, str(plan), "plan", "--out", str(tmp_path / "o.json")], check=True)
    assert list(staged.rglob("*.pyc"))


def test_rehearse_ui_poll_accepts_server_idle_null():
    line = [ln for ln in HTML.splitlines() if "rehearse/status" in ln and "dlPollJson" in ln]
    assert len(line) == 1
    assert "=== false" not in line[0] and "!x.rehearsing" in line[0]


def test_server_idle_rehearsing_is_null_so_ui_predicate_must_be_falsy_not_false(monkeypatch):
    monkeypatch.setattr(dd, "_delivery_state", {"prepared": {}, "running": False, "last": None, "rehearsals": {}, "rehearsing": None, "preparing": False})
    s = json.loads(json.dumps(dd.delivery_rehearse_status(name="x")))   # 走 JSON：Python None → JS null
    assert s["rehearsing"] is None
