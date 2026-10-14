# -*- coding: utf-8 -*-
"""U0b 寫入路由回應鍵集金標（執行器）。案例在 `write_golden_cases/cases_*.py`（各檔提供 CASES 與 WAIVE）。

規則（對應風險 #1／#2）：
- 每條 /api/ 寫入路由（取自已提交的 route_inventory.json）必須在某個 CASES 或 WAIVE 裡，且不得兩邊都有、不得指向不存在的路由。
- WAIVE 總數 ≤ `WAIVE_CAP`（只准降低，手改）。
- 案例以斷言狀態碼的方式記錄（預設 2xx）；鍵集與 `write_golden_baseline.json` 逐項比對，分『消失／新增』。
- 洩漏檢查：內部欄位名不得出現在任何回應。
重錄：`U0B_RECORD=1 python -m pytest tests/platform/test_write_golden.py -q`；
產生『其餘豁免』檔（凍結時由整合者執行）：`U0B_GEN_WAIVE=1 ... -k coverage`。
"""
import importlib
import json
import os
import pkgutil
from pathlib import Path

import pytest

from tests.platform import _response_keys as RK
from tests.platform import _write_golden as WG

HERE = Path(__file__).parent
BASELINE = HERE / "write_golden_baseline.json"
INVENTORY = HERE / "route_inventory.json"
REST = HERE / "write_golden_cases" / "cases_zz_rest.py"
WAIVE_CAP = 470          # 整合者在凍結時設成實際數字;之後只准降低（470＝468＋cases_stage_templates.py 的 2 條有理由豁免，S-ST2 凍結後新增的路由）
CASES_FLOOR = 0              # 同上：整合者設成實際案例數，防止案例檔整批消失


def _load(skip_rest=False):
    skip_rest = skip_rest or os.environ.get("U0B_SKIP_REST") == "1"      # 作者自測:略過整合者產生的 cases_zz_rest
    pkg = importlib.import_module("tests.platform.write_golden_cases")
    cases, waive, owner = {}, {}, {}
    for m in pkgutil.iter_modules(pkg.__path__):
        if not m.name.startswith("cases_") or (skip_rest and m.name == "cases_zz_rest"):
            continue
        mod = importlib.import_module(pkg.__name__ + "." + m.name)
        for c in getattr(mod, "CASES", []):
            assert c["key"] not in cases, "案例重複：%s（%s、%s）" % (c["key"], owner[c["key"]], m.name)
            cases[c["key"]] = c
            owner[c["key"]] = m.name
        for k, why in getattr(mod, "WAIVE", {}).items():
            assert k not in waive, "豁免重複：%s" % k
            assert str(why).strip(), "豁免要寫理由：%s" % k
            waive[k] = why
            owner.setdefault(k, m.name)
    return cases, waive


def _write_routes():
    inv = json.loads(INVENTORY.read_text(encoding="utf-8"))["endpoints"]
    return {k: v for k, v in inv.items() if v["w"] and k.split(" ", 1)[1].startswith("/api/")}


def test_coverage_every_write_route_is_case_or_waived():
    routes = _write_routes()
    if os.environ.get("U0B_SKIP_REST") == "1":
        pytest.skip("作者自測模式:覆蓋率由整合者在凍結時檢查")
    if os.environ.get("U0B_GEN_WAIVE") == "1":
        cases, waive = _load(skip_rest=True)
        rest = WG.uncovered(routes, cases, waive)
        body = ['# -*- coding: utf-8 -*-', '"""自動產生（U0b 凍結時）：尚未有案例的寫入路由。只准縮小——補案例後從這裡刪除。"""',
                'WAIVE = {']
        body += ['    %r: "not yet covered (U0b freeze)",' % k for k in rest]
        body.append("}")
        REST.write_text("\n".join(body) + "\n", encoding="utf-8")
        pytest.skip("已寫入 %s：%d 條" % (REST.name, len(rest)))
    cases, waive = _load()
    both = sorted(set(cases) & set(waive))
    assert not both, "同時在案例與豁免：%s" % both[:10]
    stale = sorted((set(cases) | set(waive)) - set(routes))
    assert not stale, "案例／豁免指向盤點裡沒有的寫入路由：%s" % stale[:10]
    assert WG.uncovered(routes, cases, waive) == [], "寫入路由既無案例也未豁免：%s" % WG.uncovered(routes, cases, waive)[:20]
    assert len(waive) <= WAIVE_CAP, "豁免清單變長了（%d > %d）：只准縮小" % (len(waive), WAIVE_CAP)
    assert len(cases) >= CASES_FLOOR, "案例數 %d 低於下限 %d" % (len(cases), CASES_FLOOR)


@pytest.fixture
def seeded(client, make_user):
    import db
    u, p = make_user(username="wg_admin", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    c = db.get_db()
    try:
        RK.seed_every_table(c)
    finally:
        c.close()
    return {"Authorization": "Bearer " + tok}


def _ordered(cases):
    """DELETE 排最後（建立／更新先於刪除）；其餘維持檔內順序。"""
    items = list(cases.values())
    return [c for c in items if not c["key"].startswith("DELETE ")] + [c for c in items if c["key"].startswith("DELETE ")]


def test_record_or_compare_write_cases(client, seeded):
    import db
    cases, _w = _load()
    if not cases:
        pytest.skip("尚無案例")
    rec = {}
    for c in _ordered(cases):
        if c.get("setup"):
            conn = db.get_db()
            try:
                c["setup"](conn)
                conn.commit()
            finally:
                conn.close()
        method = c["key"].split(" ", 1)[0]
        try:
            rec[c["key"]] = WG.record_write(client, seeded, method, c["url"], c.get("body"), tuple(c.get("expect", (2,))))
        except WG.GoldenError as e:
            pytest.fail("案例 %s 無法記錄：%s" % (c["key"], e))
    bad = {k: WG.leaked(v) for k, v in rec.items() if WG.leaked(v)}
    assert not bad, "回應含內部欄位：%s" % bad
    if os.environ.get("U0B_RECORD") == "1":
        BASELINE.write_text(json.dumps(rec, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip("已寫入 %s：%d 條" % (BASELINE.name, len(rec)))
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    miss = sorted(set(base) - set(rec))
    new = sorted(set(rec) - set(base))
    assert not miss and not new, "案例與基準不同步 missing=%s new=%s（重錄）" % (miss[:10], new[:10])
    diffs = {k: WG.key_delta(base[k], rec[k]) for k in rec
             if base[k]["s"] // 100 != rec[k]["s"] // 100 or WG.key_delta(base[k], rec[k]) != {"removed": [], "added": []}}
    assert not diffs, "回應鍵集與基準不同：%s" % json.dumps(diffs, ensure_ascii=False)[:2000]


# ── 執行器自身的正對照（不碰資料庫）────────────────────────────────────────────────

def test_runner_rules_detect_uncovered_and_overlap(monkeypatch):
    inv = {"POST /api/a": {"w": True}, "PUT /api/b": {"w": True}}
    assert WG.uncovered(inv, {}, {}) == ["POST /api/a", "PUT /api/b"]
    assert WG.uncovered(inv, {"POST /api/a": {}}, {"PUT /api/b": "r"}) == []


def test_ordering_puts_delete_last():
    cs = {"DELETE /a": {"key": "DELETE /a"}, "POST /a": {"key": "POST /a"}, "PUT /a": {"key": "PUT /a"}}
    assert [c["key"] for c in _ordered(cs)] == ["POST /a", "PUT /a", "DELETE /a"]


def test_leak_positive_control_via_record_shape():
    assert WG.leaked({"s": 200, "k": ["items[].owner_unit_id"]}) == ["items[].owner_unit_id"]
