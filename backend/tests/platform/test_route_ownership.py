"""modules.json 的「個別路由明列歸屬」（優先於前綴）與路由歸屬檢查（主持裁示 2026-09-26，RUN-PLAN §5 D1 M06 步驟表 ②）。

起因：M06 的 /api/reports/t100-export*、/api/settings/t100-export-config 掛在 M08 與 L1 的前綴底下，裁示**不改網址**
（V9 轉移、書籤、外部呼叫）⇒ 由 modules.json 明列那幾條路由屬於 M06。判定順序：先看明列，沒有才看前綴。
合成的 modules.json 與單位（不綁真實模組）。
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import dep_scan as D  # noqa: E402


def _groups(tmp_path, g6_routes=None, g8_routes=None, g6_prefixes=("/api/vouchers",)):
    m = {"L1": {"units": ["router:sys"], "api_prefixes": ["/api/settings"]},
         "modules": {
             "M06": {"key": "acc", "units": ["router:acc_export"], "api_prefixes": list(g6_prefixes)},
             "M08": {"key": "ana", "units": ["router:reports"], "api_prefixes": ["/api/reports"]}}}
    if g6_routes is not None:
        m["modules"]["M06"]["routes"] = g6_routes
    if g8_routes is not None:
        m["modules"]["M08"]["routes"] = g8_routes
    p = tmp_path / "modules.json"
    p.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    return p


UNITS = {
    "router:acc_export": {"kind": "router", "routes": [
        {"method": "GET", "path": "/api/reports/t100-export/vouchers"},
        {"method": "GET", "path": "/api/settings/t100-export-config"},
        {"method": "GET", "path": "/api/vouchers"}]},
    "router:reports": {"kind": "router", "routes": [{"method": "GET", "path": "/api/reports/financial"}]},
    "router:sys": {"kind": "router", "routes": [{"method": "GET", "path": "/api/settings/misc"}]},
}


def test_explicit_routes_take_precedence_over_prefixes(tmp_path):
    """正對照：M06 明列 t100 的兩條（前綴屬於 M08／L1）⇒ 沒有錯誤；M06 自己的前綴 /api/vouchers 照常。"""
    p = _groups(tmp_path, g6_routes=["/api/reports/t100-export*", "/api/settings/t100-export-config"])
    assert D.check_route_ownership(UNITS, p) == []


def test_rc_route_without_explicit_listing_and_foreign_prefix_is_an_error(tmp_path):
    """沒有明列 ⇒ 看前綴：t100 的路由前綴不在 M06 ⇒ 歸屬不明。"""
    errs = D.check_route_ownership(UNITS, _groups(tmp_path))
    assert any("/api/reports/t100-export/vouchers" in e and "歸屬不明" in e for e in errs), errs
    assert any("/api/settings/t100-export-config" in e and "歸屬不明" in e for e in errs), errs


def test_rc_explicit_route_that_does_not_exist_in_the_group_is_an_error(tmp_path):
    """反向控制①（主持指定）：明列的路由不存在於該模組 ⇒ 紅。"""
    p = _groups(tmp_path, g6_routes=["/api/reports/t100-export*", "/api/settings/t100-export-config",
                                     "/api/reports/t100-typo"])
    errs = D.check_route_ownership(UNITS, p)
    assert any("'/api/reports/t100-typo'" in e and "不存在" in e for e in errs), errs


def test_rc_same_route_listed_by_two_groups_is_an_error(tmp_path):
    """反向控制②（主持指定）：同一條路由被兩個模組明列 ⇒ 紅。"""
    p = _groups(tmp_path, g6_routes=["/api/reports/t100-export*", "/api/settings/t100-export-config"],
                g8_routes=["/api/reports/t100-export/vouchers"])
    errs = D.check_route_ownership(UNITS, p)
    assert any("多個群組明列" in e and "/api/reports/t100-export/vouchers" in e for e in errs), errs


def test_rc_explicit_listing_cannot_claim_another_groups_route(tmp_path):
    """明列不可以把別人的路由搶過來：M08 明列 M06 router 裡的路由 ⇒ 紅。"""
    p = _groups(tmp_path, g6_routes=["/api/reports/t100-export*", "/api/settings/t100-export-config"],
                g8_routes=["/api/vouchers"])
    errs = D.check_route_ownership(UNITS, p)
    assert any("M08" in e and "'/api/vouchers'" in e and "別的群組" in e for e in errs), errs


def test_route_patterns():
    assert D._route_matches("/api/reports/t100-export*", "/api/reports/t100-export/vouchers")
    assert D._route_matches("/api/a/b", "/api/a/b") and not D._route_matches("/api/a/b", "/api/a/b/c")


def test_real_tree_has_no_route_ownership_errors():
    """真實的樹：每一條路由都有歸屬（明列或前綴）。"""
    g = D.build()
    assert D.check_route_ownership(g["units"]) == []
