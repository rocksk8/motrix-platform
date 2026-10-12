# -*- coding: utf-8 -*-
"""報價單「專案毛利%」（T57；設計 docs/platform/plans/QUOTE-PROJECT-GROSS-MARGIN-T56.md）：純函式／靜態題（不啟動 Edge）。
端點題（逐面可見度、不回寫）在 test_project_margin_endpoints_2026_10_13.py。"""
import json
import pathlib
import random
import shutil
import subprocess

import pytest

from helpers import financial_mask as FM
from helpers import profit_rules as PR
from helpers import settings_registry as R
from modules.case import profit_guard as PG

ROOT = pathlib.Path(__file__).resolve().parents[2]
VEC = json.loads((pathlib.Path(__file__).parent / "data" / "project_margin_vectors.json").read_text(encoding="utf-8"))
NODE = shutil.which("node")


# --- 黃金向量（後端／前端共用）---------------------------------------------------------------

@pytest.mark.parametrize("c", VEC["cases"], ids=[c["name"] for c in VEC["cases"]])
def test_backend_matches_golden_vectors(c):
    r = PR.project_margin(c["pretax"], c["cost"])
    assert r["pct"] == c["expect"]["pct"] and r["amount"] == c["expect"]["amount"]


def test_uncosted_items_vector():
    assert PR.uncosted_items(VEC["uncosted"]["items"]) == VEC["uncosted"]["expect"]


def test_ties_round_away_from_zero_and_none_is_not_zero():
    assert PR.project_margin(2000, 1755)["pct"] == 12.3 and PR.project_margin(2000, 2245)["pct"] == -12.3
    assert PR.project_margin(0, 5)["pct"] is None and PR.project_margin(-1, 0)["pct"] is None
    assert PR.project_margin(1000, 1500)["pct"] == -50.0                       # 虧損回負數、不補零
    assert PR.project_margin(1000, float("nan"))["pct"] is None and PR.project_margin(True, 1)["pct"] is None


_JS = r"""
const fs = require('fs')
const P = require(process.argv[2])
const v = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'))
const out = v.cases.map(c => { const r = P.projectMargin(c.pretax, c.cost); return { amount: r.amount, pct: r.pct } })
out.push({ uncosted: P.uncostedItems(v.uncosted.items) })
process.stdout.write(JSON.stringify(out))
"""


@pytest.mark.skipif(not NODE, reason="沒有 node：前端等值題略過")
def test_frontend_twin_equals_backend_vectors(tmp_path):
    runner = tmp_path / "run_pm.js"
    runner.write_text(_JS, encoding="utf-8")
    cp = subprocess.run([NODE, str(runner), str(ROOT / "frontend/static/profit-rules.js"),
                         str(pathlib.Path(__file__).parent / "data" / "project_margin_vectors.json")],
                        capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert cp.returncode == 0, cp.stderr
    got = json.loads(cp.stdout)
    exp = [dict(amount=c["expect"]["amount"], pct=c["expect"]["pct"]) for c in VEC["cases"]] + [{"uncosted": VEC["uncosted"]["expect"]}]
    bad = [(c["name"], g, e) for c, g, e in zip(VEC["cases"], got, exp) if g != e]
    assert not bad and got[-1] == exp[-1], bad[:3]


@pytest.mark.skipif(not NODE, reason="沒有 node")
def test_frontend_twin_agrees_with_backend_on_random_inputs(tmp_path):
    rnd = random.Random(20261013)
    pairs = []
    for _ in range(300):
        p = rnd.choice([rnd.randint(1, 5_000_000), round(rnd.uniform(1, 90000), 2)])
        c = rnd.choice([rnd.randint(0, 6_000_000), round(rnd.uniform(0, 100000), 2), 0.7 * rnd.randint(1, 900)])
        pairs.append((p, c))
    js = "const P=require(process.argv[2]);const a=JSON.parse(process.argv[3]);process.stdout.write(JSON.stringify(a.map(x=>P.projectMargin(x[0],x[1]).pct)))"
    runner = tmp_path / "rnd.js"
    runner.write_text(js, encoding="utf-8")
    cp = subprocess.run([NODE, str(runner), str(ROOT / "frontend/static/profit-rules.js"), json.dumps(pairs)],
                        capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert cp.returncode == 0, cp.stderr
    assert json.loads(cp.stdout) == [PR.project_margin(p, c)["pct"] for p, c in pairs]


# --- 與直接毛利的恆等關係：差異恰為進項稅 --------------------------------------------------------

def test_difference_to_direct_profit_is_exactly_the_input_vat():
    rnd = random.Random(7)
    for _ in range(60):
        items = [{"id": str(i), "qty": rnd.choice([1, 2, 3, 0.5]), "unitPrice": rnd.randint(100, 20000), "cost": rnd.randint(0, 15000)} for i in range(rnd.randint(1, 6))]
        q = {"items": items, "taxRate": 5, "discount": rnd.choice([0, 100]), "freight": rnd.choice([0, 250])}
        t = PG.server_totals(q)
        p = PG.server_profit(dict(q, tot=t), 25, 2, pretax=t["pretax"], total=t["total"])
        pm = PG.quote_project_margin(q)
        assert pm["amount"] - p["directProfit"] == pytest.approx(p["inputVat"], abs=1e-6)


def test_quote_project_margin_recomputes_from_items_not_from_client_tot():
    q = {"items": [{"id": "a", "qty": 1, "unitPrice": 1000, "cost": 600}, {"id": "b", "qty": 1, "unitPrice": 2000, "cost": 1500},
                   {"id": "g", "qty": 1, "unitPrice": 0, "cost": ""}], "taxRate": 5,
         "tot": {"pretax": 999999, "totalCost": 1}}                                  # 被竄改的用戶端 tot 不採用
    r = PG.quote_project_margin(q)
    assert r["pct"] == 30.0 and r["amount"] == 900 and r["uncosted_items"] == 1


def test_alt_switch_and_picks_flow_through_counted_items():
    items = [{"id": "a", "qty": 1, "unitPrice": 1000, "cost": 600},
             {"id": "x1", "qty": 1, "unitPrice": 3000, "cost": 2000, "altGroup": "G"},
             {"id": "x2", "qty": 1, "unitPrice": 5000, "cost": 3500, "altGroup": "G"}]
    off = {"items": items, "taxRate": 5}
    assert PG.quote_project_margin(off)["pct"] == round((9000 - 6100) / 9000 * 100, 1)           # 開關沒開：全部計入
    on = dict(off, totalsByAlt=True)
    assert PG.quote_project_margin(on)["pct"] == 40.0                                                # 未選：只有一般品項
    assert PG.quote_project_margin(dict(on, altPicks={"G": "x2"}))["pct"] == round((6000 - 4100) / 6000 * 100, 1)


# --- 遮蔽機制 ------------------------------------------------------------------------------------

def test_project_margin_key_is_registered_in_masking_list_and_mask_row_nulls_it():
    assert "project_margin_pct" in FM.QUOTATION_MONEY_COLS
    row = {"total": 1, "pretax": 2, "direct_margin_pct": 3, "net_margin_pct": 4, "project_margin_pct": 5}
    FM.mask_row(row)
    assert row["project_margin_pct"] is None


def test_prepare_discards_client_supplied_values():
    q = {"items": [{"id": "a", "qty": 1, "unitPrice": 100, "cost": 50}], "taxRate": 5, "project_margin_pct": 99, "projectMargin": 98,
         "tot": {"project_margin_pct": 97, "projectMargin": 96}}
    try:
        PG.prepare(q, {"role": "superadmin", "username": "x"}, None, "")
    except Exception:
        pass                                                                     # 設定庫在純測試環境可能取不到；丟棄動作在最前面，已先發生
    assert "project_margin_pct" not in q and "projectMargin" not in q
    assert "project_margin_pct" not in q["tot"] and "projectMargin" not in q["tot"]


# --- 設定（框架登錄）---------------------------------------------------------------------------------

def test_warn_threshold_is_a_registered_setting_default_off_and_plain_language():
    g = R.groups()["project_margin"]
    f = {x["key"]: x for x in g["fields"]}["warn_pct"]
    assert f["default"] == 0 and f["min"] == 0 and f["max"] == 100 and f["risk"] == "none"
    for t in (f["question"], f["label"], f["help"], f["impact"]):
        assert t and "warn_pct" not in t and "project_margin" not in t
    assert R.get("project_margin", "warn_pct", now="2000-01-01T00:00:00") == 0
    assert R.validate_values("project_margin", {"warn_pct": 101}, partial=True)
    assert R.validate_values("project_margin", {"warn_pct": 20}, partial=True) == []


# --- 顯示層（靜態）---------------------------------------------------------------------------------------

FORM = (ROOT / "frontend" / "pages" / "quotation-form.html").read_text(encoding="utf-8")
CASE = (ROOT / "frontend" / "pages" / "case-management.html").read_text(encoding="utf-8")


def test_form_block_is_inside_the_cost_panel_and_not_stored():
    panel = FORM[FORM.index('<div class="cost-panel" x-show="showCostCols">'): FORM.index("<!-- 隱藏成本時的簡易摘要 -->")]
    assert 'data-testid="qf-project-margin"' in panel and "projectMarginText()" in panel          # 只在成本分機（成本權限）內
    assert "this.tot.project" not in FORM and "tot.projectMargin" not in FORM and "q.project_margin" not in FORM    # 不進 tot、不進單據
    assert "不含進項稅、管銷分攤、公益捐款與保留款" in FORM


def test_case_page_line_is_gated_by_existing_financial_flag():
    i = CASE.index('data-testid="cm-project-margin"')
    assert "canSeeFinancial()" in CASE[i - 200: i + 60]


def test_customer_outputs_never_mention_project_margin():
    src = (ROOT / "backend" / "pdf_gen.py").read_text(encoding="utf-8")
    assert "專案毛利" not in src and "project_margin" not in src
    for f in ("alt_view.py",):
        assert "project_margin" not in (ROOT / "backend" / "modules" / "case" / f).read_text(encoding="utf-8")


def test_customer_pdf_html_has_no_project_margin(client):
    import pdf_gen
    q = {"quoteNo": "MQ-PM-1", "customerName": "客", "taxRate": 5,
         "items": [{"id": "a", "qty": 1, "unitPrice": 1000, "cost": 600, "amount": 1000, "description": "x", "unit": "式"}]}
    for internal in (False, True):
        html = pdf_gen._build_quote_html(q, PG.server_totals(q), internal=internal)
        assert "專案毛利" not in html
