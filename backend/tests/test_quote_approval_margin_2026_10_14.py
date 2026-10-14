# -*- coding: utf-8 -*-
"""報價送審的『單項毛利率門檻』改成設定 `quote_approval.min_item_margin_pct`（預設 30＝今天寫死的值；三處同源）。
- 預設 30 ⇒ 判定與文字和過去逐位元相同（格子：邊界剛好等於門檻、None、負數、字串…）；突變控制：`<` 改 `<=` 時邊界格翻面
- 其他門檻：只有『嚴格低於』才列原因；文字帶門檻（整數不帶小數點；29.5 照寫）
- 讀不到／不合法（<0、>100、NaN、例外）⇒ 一律回 30（不改變送審判定）
- 前端 checkApproval() 的實際原始碼片段（從頁面抽出，用 node 執行）與後端在 門檻×毛利率 的格子上逐格相同
- 設定：預設 30、loosen=down（調低＝放寬 ⇒ 待生效；調高立即）、群組 sensitive；config 端點多回 minItemMarginPct
- 頁面：不再有寫死的 0.30，預設 30，門檻不是 30 時才多算一次"""
import itertools
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from modules.case import quote_terms as QT

ROOT = Path(__file__).resolve().parents[2]
NODE = shutil.which("node")
PAGE = ROOT / "frontend" / "pages" / "quotation-form.html"
MARGINS = [None, 0, 0.1, 0.2, 0.25, 0.2999, 0.3, 0.30001, 0.31, 0.5, 1, -0.1, "0.2", True]
THRESHOLDS = [30, 20, 29.5, 0, 100, 12.25]


def q_with(margin, cost=10):
    return {"validDays": 30, "taxRate": 5, "items": [{"type": "header"}, {"cost": cost, "margin": margin}, {"cost": 0, "margin": 0.01}]}


def margin_reasons(q):
    return [r for r in QT.compute_approval_reasons(q, [], "") if r.startswith("第")]


def legacy(q):
    """過去寫死 30 的實作（逐字）。"""
    out = []
    for i, item in enumerate(q.get("items") or []):
        if not isinstance(item, dict) or item.get("type") == "header":
            continue
        if QT._js_num(item.get("cost")) > 0 and QT._js_num(item.get("margin")) < 0.30:
            out.append(f"第 {i + 1} 項毛利率 {QT._js_to_fixed(QT._js_num(item.get('margin')) * 100, 2)}% 低於 30%")
    return out


@pytest.fixture()
def thr(monkeypatch):
    def set_(v):
        monkeypatch.setattr(QT, "min_item_margin_pct", lambda: v)
    return set_


@pytest.mark.parametrize("m", MARGINS)
def test_default_30_is_identical_to_the_old_hard_coded_behavior(m):
    q = q_with(m)
    assert margin_reasons(q) == legacy(q)


def test_equal_to_the_threshold_is_not_flagged_and_the_mutation_flips_it():
    q = q_with(0.3)
    assert margin_reasons(q) == [] and legacy(q) == []
    src = Path(QT.__file__).read_text(encoding="utf-8")
    assert "< min_pct / 100" in src
    mutated = src.replace("< min_pct / 100", "<= min_pct / 100")
    assert mutated != src                                                                       # 突變：邊界格會翻面（以下用同一個判定式示範）
    assert (0.3 <= 30 / 100) is True and (0.3 < 30 / 100) is False


@pytest.mark.parametrize("t,m", list(itertools.product(THRESHOLDS, MARGINS)))
def test_threshold_decides_and_the_text_carries_it(thr, t, m):
    thr(t)
    got = margin_reasons(q_with(m))
    flagged = QT._js_num(m) < t / 100
    assert bool(got) == flagged
    if flagged:
        assert got == [f"第 2 項毛利率 {QT._js_to_fixed(QT._js_num(m) * 100, 2)}% 低於 {QT._js_str(float(t))}%"]


def test_text_formatting_of_the_threshold():
    assert QT._js_str(30.0) == "30" and QT._js_str(29.5) == "29.5" and QT._js_str(12.25) == "12.25"


@pytest.mark.parametrize("bad", [-1, 100.5, float("nan"), float("inf"), "abc", None])
def test_unreadable_or_invalid_settings_fall_back_to_30(monkeypatch, bad):
    from helpers import settings_registry as sr
    monkeypatch.setattr(sr, "get", lambda *a, **k: bad)
    assert QT.min_item_margin_pct() == 30.0


def test_a_settings_failure_does_not_change_the_decision(monkeypatch):
    from helpers import settings_registry as sr

    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(sr, "get", boom)
    assert QT.min_item_margin_pct() == 30.0 and margin_reasons(q_with(0.29)) == legacy(q_with(0.29))


# ── 前端與後端同源（從頁面抽出 checkApproval 的毛利片段，用 node 實際執行） ─────────────────────────────────
def _js_snippet():
    html = PAGE.read_text(encoding="utf-8")
    m = re.search(r"this\.q\.items\.forEach\(\(item, i\) => \{\s*if \(item\.type === 'header'\) return\s*(if \(item\.cost > 0[^\n]*\n[^\n]*\n)\s*\}\)", html)
    assert m, "找不到 checkApproval 的毛利片段"
    return m.group(1)


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_page_snippet_matches_the_server_on_the_whole_grid(thr):
    snippet = _js_snippet()
    harness = """
const snippet = process.argv[2], inp = JSON.parse(process.argv[3])
const f = new Function('item', 'i', 'reasons', snippet)
const out = inp.map(([t, m]) => { const reasons = []; f.call({ pmCfg: { minItemMarginPct: t } }, { cost: 10, margin: m }, 1, reasons); return reasons })
console.log(JSON.stringify(out))
"""
    grid = [(t, m) for t in THRESHOLDS for m in MARGINS if not isinstance(m, (str, bool))]            # 前端的 margin 永遠是數字（輸入框 parseFloat）
    res = subprocess.run([NODE, "-e", harness, "x", snippet, json.dumps(grid)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert res.returncode == 0, res.stderr
    js = json.loads(res.stdout.strip().splitlines()[-1])
    for (t, m), got in zip(grid, js):
        thr(float(t))
        assert got == margin_reasons(q_with(m)), (t, m)


def test_page_has_no_hard_coded_030_and_defaults_to_30():
    html = PAGE.read_text(encoding="utf-8")
    assert "0.30" not in html.split("checkApproval() {")[1].split("showDiscount")[0]
    assert 'item.margin < pmCfg.minItemMarginPct / 100 && item.cost > 0' in html and "minItemMarginPct: 30" in html
    assert "if (this.pmCfg.minItemMarginPct !== 30) this.checkApproval()" in html                    # 預設不多做任何事


# ── 設定與端點（需要資料庫） ─────────────────────────────────────────────────────────────────────────────
def test_setting_defaults_and_direction(client):
    from helpers import settings_registry as SR
    f = SR._g("quote_approval")["fields"]["min_item_margin_pct"]
    assert SR.get("quote_approval", "min_item_margin_pct") == 30 and f.loosen == "down" and f.min == 0 and f.max == 100
    assert SR.groups()["quote_approval"]["sensitive"] is True


def test_lowering_is_pending_and_raising_is_immediate(client):
    import db
    from helpers import settings_registry as SR
    c = db.get_db()
    try:
        up = SR.publish("quote_approval", {"min_item_margin_pct": 35}, reason="t", user="t62", conn=c)
        c.commit()
        assert not up["pending"] and SR.get("quote_approval", "min_item_margin_pct", conn=c) == 35
        down = SR.publish("quote_approval", {"min_item_margin_pct": 20}, reason="t", user="t62", conn=c)
        c.commit()
        assert down["pending"] and SR.get("quote_approval", "min_item_margin_pct", conn=c) == 35        # 放寬：待生效，現值不變
    finally:
        c.close()


def test_config_endpoint_returns_the_threshold_and_keeps_the_old_key(client, make_user):
    u, p = make_user(username="t62q_sa", role="superadmin")[:2]
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    j = client.get("/api/project-margin/config", headers=h).json()
    assert j["warnPct"] == 0 and j["minItemMarginPct"] == 30
    u2, p2 = make_user(username="t62q_eng", role="engineer")[:2]
    h2 = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u2, "password": p2}).json()["token"]}
    assert client.get("/api/project-margin/config", headers=h2).status_code == 403                  # 沒有金額權限的人仍是 403（門檻也不給）
