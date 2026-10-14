# -*- coding: utf-8 -*-
"""報價送審的另外兩個門檻改成設定 `quote_approval.max_valid_days`（預設 30＝今天）與 `quote_approval.discount_review_above`（預設 0＝今天：任何折讓都列）。
同 `min_item_margin_pct` 的做法：預設＝今天寫死的值（格子逐項相同）、嚴格讀取（讀不到／不合法 ⇒ 最嚴，不是預設）、放寬方向（調大／調高）走待核准、
伺服器送審時重算、頁面經 GET /api/project-margin/config 取同一組數字。不是 5% 的稅別是法定稅別，**不在這裡設定**（鎖死）。
- 預設 ⇒ 判定與文字和過去逐位元相同（有效天數×折讓 的格子）
- 突變控制：把 `>` 改成 `>=` 載入一份變異的 quote_terms，邊界格必須翻面
- 前端 checkApproval() 的實際原始碼片段（從頁面抽出，用 node 執行）與後端在 門檻×值 的格子上逐格相同
"""
import itertools
import json
import re
import shutil
import subprocess
import types
from pathlib import Path

import pytest

from core.source_tree import page_file
from modules.case import quote_terms as QT

ROOT = Path(__file__).resolve().parents[2]
NODE = shutil.which("node")
PAGE = page_file("quotation-form.html")
DAYS = [None, 0, 1, 29, 30, 30.0001, 31, "45", "abc", True, -1, 365, 366]
DISCOUNTS = [None, 0, -5, 0.5, 1, 99, 100, 101, "100", "abc", True]
SHOW = [True, False, None, 1, "x"]
LIMITS = [30, 1, 7, 90, 365]
ABOVES = [0, 100, 5000, 100000000]


def base(days=30, discount=0, show=False):
    return {"validDays": days, "taxRate": 5, "items": [], "showDiscount": show, "discount": discount}


def days_reasons(q):
    return [r for r in QT.compute_approval_reasons(q, [], "") if r.startswith("有效期限")]


def disc_reasons(q):
    return [r for r in QT.compute_approval_reasons(q, [], "") if r.startswith("含折讓")]


def legacy_days(q):
    return [f"有效期限 {QT._js_str(q.get('validDays'))} 天（超過 30 天）"] if QT._js_num(q.get("validDays")) > 30 else []


def legacy_disc(q):
    return [f"含折讓（NT${QT._js_locale_number(QT._js_num(q.get('discount')))}）"] if QT._js_truthy(q.get("showDiscount")) and QT._js_num(q.get("discount")) > 0 else []


@pytest.fixture()
def lim(monkeypatch):
    def set_(days=30, above=0, margin=30.0):
        monkeypatch.setattr(QT, "max_valid_days", lambda: days)
        monkeypatch.setattr(QT, "discount_review_above", lambda: above)
        monkeypatch.setattr(QT, "min_item_margin_pct", lambda: margin)
    return set_


@pytest.mark.parametrize("d", DAYS)
def test_default_30_days_is_identical_to_the_old_hard_coded_behavior(lim, d):
    lim()
    q = base(days=d)
    assert days_reasons(q) == legacy_days(q)


@pytest.mark.parametrize("show,disc", list(itertools.product(SHOW, DISCOUNTS)))
def test_default_zero_discount_threshold_is_identical_to_the_old_behavior(lim, show, disc):
    lim()
    q = base(discount=disc, show=show)
    assert disc_reasons(q) == legacy_disc(q)


@pytest.mark.parametrize("n,d", list(itertools.product(LIMITS, DAYS)))
def test_days_limit_decides_and_the_text_carries_it(lim, n, d):
    lim(days=n)
    got = days_reasons(base(days=d))
    flagged = QT._js_num(d) > n
    assert bool(got) == flagged
    if flagged:
        assert got == [f"有效期限 {QT._js_str(d)} 天（超過 {n} 天）"]


@pytest.mark.parametrize("a,disc", list(itertools.product(ABOVES, DISCOUNTS)))
def test_discount_threshold_decides_only_strictly_above(lim, a, disc):
    lim(above=a)
    got = disc_reasons(base(discount=disc, show=True))
    assert bool(got) == (QT._js_num(disc) > 0 and QT._js_num(disc) > a)


def _mutant(old, new):
    src = Path(QT.__file__).read_text(encoding="utf-8")
    assert src.count(old) == 1, old
    mod = types.ModuleType("qt_mutant")
    mod.__file__ = QT.__file__
    exec(compile(src.replace(old, new), QT.__file__, "exec"), mod.__dict__)
    return mod


def test_mutation_controls_flip_the_boundary_cells(monkeypatch):
    """邊界格：天數剛好等於上限、折讓剛好等於門檻 ⇒ 不列；把比較改成 >= 載入一份變異的 quote_terms，邊界格必須翻面。"""
    def pin(mod):
        monkeypatch.setattr(mod, "max_valid_days", lambda: 30)
        monkeypatch.setattr(mod, "discount_review_above", lambda: 100)
        monkeypatch.setattr(mod, "min_item_margin_pct", lambda: 30.0)
        return mod
    q = base(days=30, discount=100, show=True)
    ok = pin(QT).compute_approval_reasons(q, [], "")
    assert not any(r.startswith(("有效期限", "含折讓")) for r in ok)
    m1 = pin(_mutant("> _max_days:", ">= _max_days:"))
    assert any(r.startswith("有效期限") for r in m1.compute_approval_reasons(q, [], "")), "突變 >= 後邊界格翻面"
    m2 = pin(_mutant("> discount_review_above():", ">= discount_review_above():"))
    assert any(r.startswith("含折讓") for r in m2.compute_approval_reasons(q, [], "")), "突變 >= 後邊界格翻面"


@pytest.mark.parametrize("fn,bad,strictest", [
    ("max_valid_days", [0, 366, -1, float("nan"), float("inf"), "abc", None, True, [1]], 1),
    ("discount_review_above", [-1, 100000001, float("nan"), float("inf"), "abc", None, True, {"a": 1}], 0),
])
def test_invalid_values_converge_to_the_strictest_not_to_the_default(monkeypatch, fn, bad, strictest):
    monkeypatch.setattr("db.get_db", lambda: type("C", (), {"close": lambda self: None})())
    for b in bad:
        monkeypatch.setattr("helpers.settings_strict.strict_value", lambda conn, g, f, _b=b: _b)
        assert getattr(QT, fn)() == strictest, (fn, b)


@pytest.mark.parametrize("fn,strictest", [("max_valid_days", 1), ("discount_review_above", 0)])
def test_a_read_failure_converges_to_the_strictest(monkeypatch, fn, strictest):
    def boom(*a, **k):
        raise RuntimeError("database is locked")
    monkeypatch.setattr("helpers.settings_strict.strict_value", boom)
    monkeypatch.setattr("db.get_db", lambda: type("C", (), {"close": lambda self: None})())
    assert getattr(QT, fn)() == strictest
    if fn == "max_valid_days":
        monkeypatch.setattr(QT, "min_item_margin_pct", lambda: 30.0)
        assert days_reasons(base(days=2)) == ["有效期限 2 天（超過 1 天）"], "讀不到 ⇒ 最嚴：2 天也要列"


def test_valid_values_are_read_as_integers(monkeypatch):
    monkeypatch.setattr("db.get_db", lambda: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr("helpers.settings_strict.strict_value", lambda conn, g, f: 45.0 if f == "max_valid_days" else 5000.0)
    assert QT.max_valid_days() == 45 and isinstance(QT.max_valid_days(), int)
    assert QT.discount_review_above() == 5000 and isinstance(QT.discount_review_above(), int)


def test_the_discount_setting_is_not_read_when_there_is_no_discount(monkeypatch):
    called = []
    monkeypatch.setattr(QT, "max_valid_days", lambda: 30)
    monkeypatch.setattr(QT, "min_item_margin_pct", lambda: 30.0)
    monkeypatch.setattr(QT, "discount_review_above", lambda: called.append(1) or 0)
    QT.compute_approval_reasons(base(discount=0, show=True), [], "")
    QT.compute_approval_reasons(base(discount=500, show=False), [], "")
    assert called == [], "沒有折讓就不讀設定（與今天一樣）"


# ── 前端與後端同源 ────────────────────────────────────────────────────────
def _snippets():
    html = PAGE.read_text(encoding="utf-8")
    d = re.search(r"(if \(this\.q\.validDays > this\.pmCfg\.maxValidDays\)\n\s*reasons\.push\([^\n]*\))", html)
    c = re.search(r"(if \(this\.q\.showDiscount && this\.q\.discount > 0 && this\.q\.discount > this\.pmCfg\.discountReviewAbove\)\n\s*reasons\.push\([^\n]*\))", html)
    assert d and c, "找不到 checkApproval 的有效天數／折讓片段"
    return d.group(1), c.group(1)


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_page_snippets_match_the_server_on_the_grid(lim):
    sd, sc = _snippets()
    harness = """
const [sd, sc, inp] = [process.argv[2], process.argv[3], JSON.parse(process.argv[4])]
const fd = new Function('reasons', sd), fc = new Function('reasons', sc)
const out = inp.map(([kind, cfg, q]) => { const reasons = []; (kind === 'days' ? fd : fc).call({ q, pmCfg: cfg }, reasons); return reasons })
console.log(JSON.stringify(out))
"""
    num = lambda x: not isinstance(x, (str, bool)) or x is None        # 前端的輸入框值是數字（或 null）
    grid = [("days", {"maxValidDays": n, "discountReviewAbove": 0}, {"validDays": d}) for n in LIMITS for d in DAYS if num(d) and d is not None]
    grid += [("disc", {"maxValidDays": 30, "discountReviewAbove": a}, {"showDiscount": s, "discount": x}) for a in ABOVES for s in (True, False) for x in DISCOUNTS if num(x) and x is not None]
    res = subprocess.run([NODE, "-e", harness, "x", sd, sc, json.dumps(grid)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert res.returncode == 0, res.stderr
    js = json.loads(res.stdout.strip().splitlines()[-1])
    assert len(js) == len(grid)
    for (kind, cfg, q), got in zip(grid, js):
        if kind == "days":
            lim(days=cfg["maxValidDays"])
            exp = days_reasons(base(days=q["validDays"]))
        else:
            lim(above=cfg["discountReviewAbove"])
            exp = disc_reasons(base(discount=q["discount"], show=q["showDiscount"]))
            exp = [e.replace(",", ",") for e in exp]
        norm = lambda xs: [re.sub(r"NT\$[\d,\.]+", "NT$#", x) for x in xs]               # 千分位格式由原有的 parity 題守；這裡驗『列或不列』與有效天數文字
        assert norm(got) == norm(exp), (kind, cfg, q, got, exp)


def test_page_has_no_hard_coded_30_in_the_check_and_defaults_to_today():
    html = PAGE.read_text(encoding="utf-8")
    body = html.split("checkApproval() {")[1].split("const taxRate")[0]
    assert "> 30" not in body and "超過 30 天" not in body
    assert "maxValidDays: 30, discountReviewAbove: 0" in html
    assert "q.validDays > pmCfg.maxValidDays" in html and "'超過 ' + pmCfg.maxValidDays + ' 天需主管審核'" in html
    assert "this.pmCfg.minItemMarginPct !== 30 || this.pmCfg.maxValidDays !== 30 || this.pmCfg.discountReviewAbove !== 0" in html, "預設不多做任何事"


def test_non_five_percent_tax_is_a_statutory_rule_and_stays_hard_coded():
    src = Path(QT.__file__).read_text(encoding="utf-8")
    assert "_js_num(tax_rate) < 5" in src and "非應稅 5%" in src and "標準 5%" in src
    from helpers import settings_groups  # noqa: F401
    from helpers import settings_registry as SR
    keys = {f["key"] for f in SR.groups()["quote_approval"]["fields"]}
    assert keys == {"min_item_margin_pct", "max_valid_days", "discount_review_above"}, "稅別判斷（營業稅法）不開放設定"


# ── 設定與端點（需要資料庫） ────────────────────────────────────────────────
def test_settings_defaults_limits_and_directions(client):
    from helpers import settings_registry as SR
    g = SR._g("quote_approval")["fields"]
    d, a = g["max_valid_days"], g["discount_review_above"]
    assert SR.get("quote_approval", "max_valid_days") == 30 and (d.min, d.max, d.loosen) == (1, 365, "up")
    assert SR.get("quote_approval", "discount_review_above") == 0 and (a.min, a.max, a.loosen) == (0, 100000000, "up")
    assert SR.groups()["quote_approval"]["sensitive"] is True


def test_raising_is_pending_and_lowering_is_immediate(client):
    import db
    from helpers import settings_registry as SR
    c = db.get_db()
    try:
        down = SR.publish("quote_approval", {"max_valid_days": 14}, reason="t", user="t62", conn=c)
        c.commit()
        assert not down["pending"] and SR.get("quote_approval", "max_valid_days", conn=c) == 14, "調小＝更嚴＝立即"
        up = SR.publish("quote_approval", {"max_valid_days": 60}, reason="t", user="t62", conn=c)
        c.commit()
        assert up["pending"] and SR.get("quote_approval", "max_valid_days", conn=c) == 14, "調大＝放寬＝待生效，現值不變"
        up2 = SR.publish("quote_approval", {"discount_review_above": 1000}, reason="t", user="t62", conn=c)
        c.commit()
        assert up2["pending"] and SR.get("quote_approval", "discount_review_above", conn=c) == 0
    finally:
        c.close()


def test_config_endpoint_returns_all_three_and_keeps_the_old_keys(client, make_user):
    u, p = make_user(username="t62t_sa", role="superadmin")[:2]
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    j = client.get("/api/project-margin/config", headers=h).json()
    assert j["warnPct"] == 0 and j["minItemMarginPct"] == 30 and j["maxValidDays"] == 30 and j["discountReviewAbove"] == 0
    u2, p2 = make_user(username="t62t_eng", role="engineer")[:2]
    h2 = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u2, "password": p2}).json()["token"]}
    assert client.get("/api/project-margin/config", headers=h2).status_code == 403, "沒有金額權限的人仍是 403（門檻也不給）"


def test_a_tightened_limit_survives_a_locked_database_and_defaults_only(client, monkeypatch):
    import db
    from core import definitions as D
    from helpers import settings_registry as SR
    c = db.get_db()
    try:
        SR.publish("quote_approval", {"max_valid_days": 14}, reason="t", user="t62", conn=c)
        c.commit()
    finally:
        c.close()
    assert QT.max_valid_days() == 14
    monkeypatch.setenv("MOTRIX_SETTINGS_DEFAULTS_ONLY", "1")
    assert QT.max_valid_days() == 14, "逃生口只換掉 settings_registry.get 的結果，不能把上限放回 30"
    real = D.get

    def locked(conn, kind, *a, **k):
        if kind == SR.KIND:
            raise RuntimeError("database is locked")
        return real(conn, kind, *a, **k)
    monkeypatch.setattr(D, "get", locked)
    assert QT.max_valid_days() == 1 and QT.discount_review_above() == 0, "讀不到 ⇒ 最嚴"


def test_defaults_when_nothing_is_stored(client):
    assert QT.max_valid_days() == 30 and QT.discount_review_above() == 0
