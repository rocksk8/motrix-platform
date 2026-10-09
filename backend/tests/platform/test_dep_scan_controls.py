"""dep_scan 的正對照：在合成樹上驗，不綁任何真實 L2 模組（MODULE-GUIDE 測試規則）。

拿掉任何一個 L2 模組，掃描器都不可以自判「不可信」而讓所有守門停擺。
"""
import inspect
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import dep_scan  # noqa: E402


def test_synthetic_controls_pass():
    assert dep_scan.positive_controls() == []


def test_controls_do_not_name_any_real_l2_unit():
    """正對照的原始碼裡不可以出現真實 L2 單位的名稱（出現了＝又綁回特定模組）。"""
    m = json.loads((REPO / "docs" / "platform" / "modules.json").read_text(encoding="utf-8"))
    l2_units = {u for g in m["modules"].values() for u in g["units"]}
    assert l2_units, "modules.json 讀不到任何 L2 單位——這題就什麼都沒驗"      # 正對照
    src = "".join(inspect.getsource(f) for f in (dep_scan.positive_controls, dep_scan._synthetic_checks))
    src += json.dumps(dep_scan.SYNTHETIC_MODULES) + json.dumps(dep_scan.SYNTHETIC_FILES)
    leaked = sorted(u for u in l2_units if u in src)
    assert leaked == []


def test_controls_catch_a_broken_scanner(monkeypatch):
    """反向控制：掃描器壞掉時正對照必須紅（否則「OK」不代表什麼）。"""
    monkeypatch.setattr(dep_scan, "helper_reexports", lambda: {})
    assert dep_scan.positive_controls()


def _ownership_errors(tmp_path, drop_prefix=None):
    """合成樹上跑路由歸屬檢查；drop_prefix＝從 zz_mod 組的 api_prefixes 拿掉的前綴（製造「未宣告」）。"""
    with dep_scan.use_root(tmp_path):
        U = dep_scan.build_synthetic(tmp_path)["units"]
        mj = tmp_path / "docs" / "platform" / "modules.json"
        if drop_prefix:
            m = json.loads(mj.read_text(encoding="utf-8"))
            m["modules"]["MC"]["api_prefixes"] = [p for p in m["modules"]["MC"]["api_prefixes"] if p != drop_prefix]
            mj.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        return dep_scan.check_route_ownership(U, mj)


def test_second_apirouter_variable_is_part_of_route_ownership(tmp_path):
    """端點稽核 W1a（2026-10-09）：`list_router = APIRouter(prefix=…)` 這種不叫 `router` 的變數，路由也要進歸屬檢查。
    正對照（list_router 當範本）：宣告了前綴 ⇒ 0 錯誤；沒宣告 ⇒ 抓到「歸屬不明」。"""
    assert _ownership_errors(tmp_path / "ok") == []
    errs = _ownership_errors(tmp_path / "undeclared", drop_prefix="/api/zz-pub")
    assert any("/api/zz-pub/list" in e and "歸屬不明" in e for e in errs), errs
    assert not any("/api/zz-mod/run" in e for e in errs), errs      # router 自己的路由不受 list_router 的 prefix 影響


def test_controls_catch_a_scanner_that_only_reads_the_variable_named_router(monkeypatch):
    """反向控制：把掃描器退回「只認名為 router 的變數」⇒ 正對照必須紅（否則上一題的綠不代表什麼）。"""
    real = dep_scan._router_vars
    monkeypatch.setattr(dep_scan, "_router_vars", lambda tree: {k: v for k, v in real(tree).items() if k == "router"})
    assert dep_scan.positive_controls()
