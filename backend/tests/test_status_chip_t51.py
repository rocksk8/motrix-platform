# -*- coding: utf-8 -*-
"""第 51 班：單據狀態晶片 `.st-chip`（「我的申請」清單：已核准／已駁回不再是同一個灰色）。

使用者回報（附截圖）：清單裡所有狀態徽章都是同一個灰色，「已核准」與「已駁回」看起來一模一樣。
釘住：① 每個狀態有各自的顏色類別，且已核准／已駁回／待審核／已作廢兩兩不同（類別與實際 token 都不同）
      ② 晶片 CSS 只用語意 token、沒有寫死色碼 ③ 淺色與深色兩組 token 的對比都 ≥ 4.5:1（WCAG AA，逐組算）
      ④ 狀態對照表（status-chip.js）只有一份、含完整詞彙，未知狀態不誤上色 ⑤ 頁面確實用它（標記釘）⑥ 瀏覽器端：
      實際算出來的底色／字色，已核准 ≠ 已駁回 ≠ 已作廢 ≠ 待審核。
"""
import json
import os
import re
import shutil
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CSS = os.path.join(ROOT, "frontend", "css", "style.css")
JS = os.path.join(ROOT, "frontend", "static", "status-chip.js")
from core import source_tree as _st  # noqa: E402
PAGE = str(_st.page_file("payment-request.html"))
FORM = str(_st.page_file("payment-request-form.html"))

TONES = ("draft", "pending", "signing", "approved", "rejected", "paid", "void")


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def _chip_rules():
    css = _read(CSS)
    out = {}
    for m in re.finditer(r"\.st-chip(--[a-z]+)?\s*\{([^}]*)\}", css):
        out[(m.group(1) or "")[2:]] = m.group(2)
    return out


def _vars(css, dark):
    """:root 的 --name: #hex; 對照；深色＝淺色再疊上 :root[data-theme="dark"] 的值（後定義的蓋前面）。"""
    light, drk = {}, {}
    for m in re.finditer(r"(:root(?:\[data-theme=\"dark\"\])?)\s*\{([^}]*)\}", css):
        target = drk if "dark" in m.group(1) else light
        for k, v in re.findall(r"(--[a-z0-9-]+)\s*:\s*(#[0-9A-Fa-f]{6})\b", m.group(2)):
            target[k] = v
    return {**light, **drk} if dark else light


def _lum(hexv):
    r, g, b = (int(hexv[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _ratio(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _pair(rule, vars_):
    bg = re.search(r"background:\s*var\((--[a-z0-9-]+)\)", rule)
    fg = re.search(r"(?<![a-z-])color:\s*var\((--[a-z0-9-]+)\)", rule)
    assert bg and fg, rule
    return bg.group(1), fg.group(1), vars_[bg.group(1)], vars_[fg.group(1)]


def test_every_tone_has_a_rule_and_only_uses_tokens():
    rules = _chip_rules()
    assert set(TONES) <= set(rules), set(TONES) - set(rules)
    for name, body in rules.items():
        assert not re.search(r"#[0-9A-Fa-f]{3,8}\b", body), "晶片 CSS 不可寫死色碼（用語意 token）：%s %s" % (name, body)
        assert not re.search(r"rgba?\(", body), name


def test_approved_rejected_pending_void_are_pairwise_different_tokens():
    rules = _chip_rules()
    v = _vars(_read(CSS), dark=False)
    pairs = {t: _pair(rules[t], v)[:2] for t in ("approved", "rejected", "pending", "void", "signing", "paid")}
    seen = {}
    for t, p in pairs.items():
        assert p not in seen.values(), (t, p, seen)
        seen[t] = p
    # 實際色值也不同（不只是 token 名不同）
    vals = {t: _pair(rules[t], v)[2:] for t in pairs}
    assert len(set(vals.values())) == len(vals), vals
    assert vals["approved"][0] != vals["rejected"][0] and vals["approved"][1] != vals["rejected"][1]


@pytest.mark.parametrize("dark", [False, True])
def test_contrast_is_at_least_aa_in_light_and_dark_tokens(dark):
    rules = _chip_rules()
    v = _vars(_read(CSS), dark=dark)
    bad = []
    for t in TONES:
        bgn, fgn, bg, fg = _pair(rules[t], v)
        r = _ratio(bg, fg)
        if r < 4.5:
            bad.append((t, bgn, bg, fgn, fg, round(r, 2)))
    assert not bad, ("深色" if dark else "淺色", bad)
    bgn, fgn, bg, fg = _pair(rules[""], v)                      # 基底（未知狀態）
    assert _ratio(bg, fg) >= 4.5, ("base", bg, fg)


def test_the_contrast_check_can_fail():
    """反向控制：算對比的函式抓得到不及格的組合（淺灰字在白底）。"""
    assert _ratio("#FFFFFF", "#9CA3AF") < 4.5
    assert _ratio("#FFFFFF", "#6B7280") >= 4.5


# ── 狀態對照（JS）──────────────────────────────────────────────

def _node(expr):
    node = shutil.which("node")
    if not node:
        pytest.skip("沒有 node")
    code = "var m=require(%s);process.stdout.write(JSON.stringify(%s))" % (json.dumps(JS.replace("\\", "/")), expr)
    r = subprocess.run([node, "-e", code], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_chip_class_vocabulary():
    got = _node("['草稿','待審核','待核准','簽核中','已核准','已駁回','已退回','已拒絕','已付款','已匯款','已作廢','已取消','已撤回','已撤銷'].map(function(s){return m.chipClass(s)})")
    assert got == ["st-chip st-chip--draft", "st-chip st-chip--pending", "st-chip st-chip--pending", "st-chip st-chip--signing",
                   "st-chip st-chip--approved", "st-chip st-chip--rejected", "st-chip st-chip--rejected", "st-chip st-chip--rejected",
                   "st-chip st-chip--paid", "st-chip st-chip--paid", "st-chip st-chip--void", "st-chip st-chip--void",
                   "st-chip st-chip--void", "st-chip st-chip--void"]


def test_approved_and_rejected_never_share_a_class_and_unknown_is_neutral():
    got = _node("[m.chipClass('已核准'), m.chipClass('已駁回'), m.chipClass('不知道的狀態'), m.chipClass(null), m.chipClass(undefined), m.chipClass(' 已核准 '), m.chipClass('toString')]")
    assert got[0] != got[1]
    assert got[2] == got[3] == got[4] == got[6] == "st-chip"
    assert got[5] == got[0]


def test_every_mapped_tone_has_a_css_rule():
    tones = set(_node("Object.keys(m.MAP).map(function(k){return m.MAP[k]})"))
    assert tones <= set(_chip_rules()), tones - set(_chip_rules())


# ── 頁面標記釘 ───────────────────────────────────────────────

def test_payment_request_list_uses_the_chip_not_the_grey_class():
    page = _read(PAGE)
    assert 'MotrixStatus.chipClass(e.status)' in page
    assert 'class="pr-st"' not in page and ".pr-st" not in page, "清單的狀態不可再用同色的 pr-st"
    assert page.index("status-chip.js") < page.index("alpine-"), "對照表要在 Alpine 之前載入（否則第一次渲染 MotrixStatus 未定義）"


def test_other_badge_maps_know_rejected_and_void():
    form = _read(FORM)
    assert "'已駁回': 'badge--rejected'" in form and "'已作廢': 'badge--lost'" in form
    for name in ("case-management-dispatch.js", "case-management-fin.js", "case-management-shipping.js"):
        s = _read(os.path.join(ROOT, "frontend", "js", name))
        assert "'已駁回': 'badge--rejected'" in s and "'已作廢': 'badge--lost'" in s, name
        assert "'已核准': 'badge--approved' }[s]" not in s, name + " 還有舊的 4 狀態對照表"


# ── 瀏覽器：實際算出來的顏色 ─────────────────────────────────

from tests._requires import requires_module  # noqa: E402


@pytest.mark.e2e
@requires_module("case", "支出申請＝M01 額外支出")
def test_e2e_chips_render_with_different_colours(live_server, make_user, new_context, seed_extra_expense):
    pytest.importorskip("playwright.sync_api")
    from tests._e2e_login import inject_login
    import db
    eng = make_user(username="chip_eng", role="sales")
    conn = db.get_db()
    try:
        eng_id = conn.execute("SELECT id FROM users WHERE username=?", (eng[0],)).fetchone()[0]
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
                     " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     ("MQ-CHIP-001", "已送出", "晶片客戶", "機房", 100000, 95238, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00",
                      "2026-01-01T00:00:00", "已成案", "", json.dumps([eng_id])))
        conn.commit()
    finally:
        conn.close()
    ids = {}
    for st in ("已核准", "已駁回", "已作廢", "待審核", "草稿"):
        i = seed_extra_expense("MQ-CHIP-001", total_cost=500, description="chip-" + st, status=st)
        conn = db.get_db()
        try:
            conn.execute("UPDATE case_extra_expenses SET created_by=? WHERE id=?", (eng[0], i))
            conn.commit()
        finally:
            conn.close()
        ids[st] = i
    page = new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, eng[0], eng[1])
    page.goto(live_server + "/pages/payment-request.html?tab=mine")
    page.wait_for_selector('#pr-mine[data-loaded="1"]')
    look = {}
    for st, i in ids.items():
        el = page.locator('[data-st-chip="%d"]' % i)
        assert el.inner_text() == st
        look[st] = el.evaluate("e => { const c = getComputedStyle(e); return [e.className, c.backgroundColor, c.color] }")
    assert "st-chip--approved" in look["已核准"][0] and "st-chip--rejected" in look["已駁回"][0]
    assert "st-chip--void" in look["已作廢"][0] and "st-chip--pending" in look["待審核"][0] and "st-chip--draft" in look["草稿"][0]
    colours = {st: (v[1], v[2]) for st, v in look.items()}
    assert len(set(colours.values())) == len(colours), colours               # 五個狀態五組（底色，字色）彼此不同
    assert colours["已核准"][0] != colours["已駁回"][0] and colours["已核准"][1] != colours["已駁回"][1]
    assert not errors, errors
