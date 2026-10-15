# -*- coding: utf-8 -*-
"""Q2：報價單管理頁（quotations.html）清單欄位＋案件頁分頁列接上 P9 版面引擎，預設關閉。

1. 登記：清單 quotes（10 欄）與分頁 tabs（9 個）；核心如設計；每個登記欄位在頁面上有綁定；金額／毛利率欄的儲存格運算式沒被動到（遮蔽仍由資料決定）。
2. 旗標關閉：綁定函式回中性值（node 實跑）；initLayout 在旗標假／讀不到時不啟動；旗標開啟啟動一次；編輯器錨點真的存在於頁面。
3. 分頁列：額外支出維持 canSeeFinancial()、全部附件維持 fileCenterOn（版面只能再收窄）；精算連結固定排最後；:style 一律物件形式。
4. 版面：核心不可隱藏（422）；非核心可隱藏／改名；用真的版面 runtime（node）驗證隱藏與改名生效；受限角色 API 回應不變。
5. OFF 守門：旗標綁定的 x-show 不得掛在帶行內 display 的元素。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core import customization, source_tree

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "backend" / "modules" / "case" / "module.json"
NODE = shutil.which("node")
BASE = "/api/definitions/layout/module:case"

QUOTES = ["quoteNo", "customer", "project", "amount", "margin", "validDays", "filler", "status", "dealTag", "date"]
QUOTES_CORE = {"quoteNo", "customer", "status", "dealTag"}
TABS = ["biz", "exec", "dispatch", "shipping", "completion", "feed", "allfiles", "fin", "xexp"]
TABS_CORE = {"biz"}


def _page(name):
    return source_tree.page_file(name).read_text(encoding="utf-8")


def _manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _list(page, key):
    pg = [p for p in _manifest()["customization"]["pages"] if p["page"] == page][0]
    return [x for x in pg["lists"] if x["key"] == key][0]


# ── 1. 登記 ──────────────────────────────────────────────────────────────
def test_manifest_valid_order_and_core():
    m = _manifest()
    assert customization.validate_manifest(m) == []
    for page, key, entity, cols, core in (("quotations.html", "quotes", "quote", QUOTES, QUOTES_CORE), ("case-management.html", "tabs", "tab", TABS, TABS_CORE)):
        lst = _list(page, key)
        assert lst["entity"] == entity and [c["field"] for c in lst["columns"]] == cols
        flags = {f["key"]: f["core"] for f in m["customization"]["fields"][entity]}
        assert list(flags) == cols and {k for k, v in flags.items() if v} == core


def test_quotes_page_binds_every_column_and_keeps_money_cells_untouched():
    src = _page("quotations.html")
    for f in QUOTES:
        assert "<th x-show=\"cShown('%s')\"" % f in src and "cLabel('%s'," % f in src, f
        assert "<td x-show=\"cShown('%s')\"" % f in src, f
    # 金額與毛利率儲存格的運算式不變（沒有權限＝後端不給值＝顯示「—」）；版面只加 x-show
    assert """<td x-show="cShown('amount')" class="num" style="font-weight:600" x-text="q.total > 0 ? 'NT$ ' + MotrixFormat.num(Math.round(q.total)) : '—'"></td>""" in src
    assert """x-text="q.direct_margin_pct ? q.direct_margin_pct.toFixed(1) + '%' : '—'\"""" in src
    fb = re.search(r"fallback:\s*\{\s*lists:\s*\{\s*quotes:\s*\[([^\]]*)\]", src).group(1)
    assert re.findall(r"'([^']+)'", fb) == QUOTES
    for tag in ("public-flags.js", "custom-layout.js", "layout-runtime.js", "layout-editor.js", "def-governance.js"):
        assert tag in src
    assert re.search(r"MotrixLayout\.init\(\{[^}]*deferred:\s*true", src, re.S) and "/api/layout" not in src


def test_case_page_tab_bindings():
    src = _page("case-management.html")
    for f in TABS:
        assert "tShown('%s')" % f in src and "tOrder('%s')" % f in src and "tLabel('%s'," % f in src, f
    assert "x-show=\"canSeeFinancial() && tShown('xexp')\"" in src                       # 金額權限優先
    assert "x-show=\"fileCenterOn && tShown('allfiles')\"" in src
    assert ':style="tTail()"' in src and 'data-testid="cm-tab-settlement"' in src
    fb = re.search(r"tabs:\s*\[([^\]]*)\]", src[src.index("MotrixLayout.init"):]).group(1)
    assert re.findall(r"'([^']+)'", fb) == TABS
    for body in re.findall(r"  (?:tOrder|tTail)\([^)]*\) \{[^\n]*", src):
        assert "'order:" not in body and "{ order:" in body or body.strip().startswith("tTail") and "{ order: 999 }" in body


def test_flag_default_off(client):
    from helpers import settings_registry as SR
    assert SR.get("builder_layout", "quotations") is False


# ── 2. 旗標關閉／開啟（node）───────────────────────────────────────────────
_HARNESS = r"""
const fs = require('fs')
const calls = { fetch: [], start: 0, mount: 0, slot: 0, selectors: [] }
global.window = global
global.localStorage = { getItem(k) { return k === 'motrix_session' ? JSON.stringify({ token: 't', role: 'superadmin' }) : null } }
global.location = { href: '', search: '' }
const PAGE_SRC = fs.readFileSync(process.argv[1], 'utf8')
const exists = (sel) => sel.split(',').map(x => x.trim()).some(t => t.startsWith('.') ? new RegExp('class="[^"]*\\b' + t.slice(1) + '\\b[^"]*"').test(PAGE_SRC) : PAGE_SRC.includes('id="' + t.slice(1) + '"'))
global.document = { addEventListener() {}, getElementById() { return null },
  querySelector(sel) { calls.selectors.push(sel); return exists(sel) ? { insertAdjacentHTML() { calls.slot++ } } : null } }
const stub = () => new Proxy(function () {}, { get: () => stub(), apply: () => ({}) })
for (const n of ['MotrixPrivacyNotice','MotrixDate','Sortable','MotrixMargin','MotrixListSort']) window[n] = stub()
window.MotrixLayout = { init() {}, start() { calls.start++ } }
window.MotrixLayoutEditor = { mount() { calls.mount++ } }
let FLAG = %(flag)s
global.fetch = async (url) => { calls.fetch.push(String(url)); if (FLAG === 'fail') throw new Error('x')
  return { ok: FLAG !== 'http', json: async () => ({ groups: { builder_layout: { quotations: FLAG === true } } }) } }
eval(fs.readFileSync(process.argv[2], 'utf8'))          // public-flags.js
const scripts = [...PAGE_SRC.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).filter(s => s.includes('function quotationList'))
eval(scripts[scripts.length - 1] + '\n;global.__f = quotationList')
const o = global.__f()
o.$nextTick = async () => {}
o.session = { token: 't' }
;(async () => {
  const neutral = { shown: o.cShown('amount'), label: o.cLabel('amount', '金額（含稅）') }
  await o.initLayout.call(o)
  console.log(JSON.stringify({ layoutOn: o.layoutOn, calls, neutral }))
})().catch(e => { console.error(String(e)); process.exit(1) })
"""


def _node(flag):
    out = subprocess.run([NODE, "-e", _HARNESS % dict(flag=flag), str(source_tree.page_file("quotations.html")), str(ROOT / "frontend/static/public-flags.js")],
                         capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    return json.loads(out.stdout.decode("utf-8"))


@pytest.mark.skipif(NODE is None, reason="沒有 node")
@pytest.mark.parametrize("flag", ["false", "'http'", "'fail'"])
def test_quotations_flag_off_or_unreadable_changes_nothing(flag):
    r = _node(flag)
    assert r["layoutOn"] is False and r["neutral"] == {"shown": True, "label": "金額（含稅）"}
    assert r["calls"]["start"] == 0 and r["calls"]["mount"] == 0 and r["calls"]["slot"] == 0
    assert r["calls"]["fetch"] == ["/api/settings-center/public?groups=builder_layout"]            # 唯一多出的請求＝共用的設定 GET


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_quotations_flag_on_starts_layout_once_with_a_real_anchor():
    r = _node("true")
    assert r["layoutOn"] is True and r["calls"]["start"] == 1 and r["calls"]["mount"] == 1 and r["calls"]["slot"] == 1
    assert r["calls"]["selectors"] == [".page-header__title"] and 'class="page-header__title"' in _page("quotations.html")


# ── 3/4. 版面（API＋真的 runtime）─────────────────────────────────────────
def _h(client, make_user, name, role, modules=None):
    u, p = make_user(name, "Lay-Pass-123", role=role, modules=modules)[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _col(page, lkey, field):
    return "case:%s/list:%s/column:%s" % (page, lkey, field)


def _publish(client, h, ops):
    r = client.put(BASE + "/draft", headers=h, params={"scope": "company"}, json={"body": {"ops": ops}})
    assert r.status_code == 200, r.text
    return client.post(BASE + "/publish", headers=h, params={"scope": "company"}, json={"note": "t"})


@pytest.mark.parametrize("page,lkey,cols,core", [("quotations.html", "quotes", QUOTES, QUOTES_CORE), ("case-management.html", "tabs", TABS, TABS_CORE)])
def test_core_cannot_be_hidden_noncore_can_and_restore(client, make_user, page, lkey, cols, core):
    boss = _h(client, make_user, "q2_boss_" + lkey, "superadmin")
    ids = {p["id"] for p in client.get("/api/layout/case", headers=boss).json()["points"]}
    assert all(_col(page, lkey, c) in ids for c in cols)
    for c in sorted(core):
        assert _publish(client, boss, [{"op": "hide", "target": _col(page, lkey, c)}]).status_code == 422, c
        assert _publish(client, boss, [{"op": "relabel", "target": _col(page, lkey, c), "label": "x"}]).status_code == 422, c
    noncore = [c for c in cols if c not in core]
    v1 = [{"op": "hide", "target": _col(page, lkey, noncore[0])}]
    v2 = [{"op": "relabel", "target": _col(page, lkey, noncore[1]), "label": "改名"}]
    assert _publish(client, boss, v1).status_code == 200 and _publish(client, boss, v2).status_code == 200
    mine = lambda: [o for o in client.get("/api/layout/case", headers=boss).json()["ops"] if o["target"].startswith("case:%s/list:%s/" % (page, lkey))]    # noqa: E731
    assert mine() == v2
    assert client.post(BASE + "/restore/1", headers=boss, params={"scope": "company"}, json={"note": "b"}).status_code == 200
    assert mine() == v1


_RUNTIME = r"""
const fs = require('fs')
const payload = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'))
global.window = global
const listeners = []
global.localStorage = { getItem(k) { return k === 'motrix_session' ? JSON.stringify({ token: 't', role: 'superadmin' }) : null } }
global.document = { addEventListener(n, f) { if (n === 'alpine:init') listeners.push(f) }, getElementById() { return null }, head: { appendChild() {} },
  documentElement: { setAttribute() {} }, querySelectorAll() { return [] }, createElement() { return { id: '', textContent: '' } } }
const stores = {}
global.Alpine = { store(n, v) { if (v !== undefined) stores[n] = v; return stores[n] } }
global.fetch = async () => ({ ok: true, json: async () => payload })
eval(fs.readFileSync(process.argv[1], 'utf8')); eval(fs.readFileSync(process.argv[2], 'utf8'))
MotrixLayout.init({ module: 'case', page: process.argv[4], deferred: true, fallback: { lists: {} } })
listeners.forEach(f => f())
;(async () => {
  await MotrixLayout.start()
  const L = Alpine.store('layout')
  console.log(JSON.stringify({ cols: L.cols(process.argv[5]).map(c => c.field), label: L.colLabel(process.argv[5], process.argv[6], 'DEFAULT') }))
})().catch(e => { console.error(String(e)); process.exit(1) })
"""


@pytest.mark.skipif(NODE is None, reason="沒有 node")
@pytest.mark.parametrize("page,lkey,hide,rename", [("quotations.html", "quotes", "validDays", "filler"), ("case-management.html", "tabs", "feed", "exec")])
def test_real_runtime_applies_hide_and_relabel(client, make_user, tmp_path, page, lkey, hide, rename):
    boss = _h(client, make_user, "q2_rt_" + lkey, "superadmin")
    assert _publish(client, boss, [{"op": "hide", "target": _col(page, lkey, hide)}, {"op": "relabel", "target": _col(page, lkey, rename), "label": "新名稱"}]).status_code == 200
    pf = tmp_path / "p.json"
    pf.write_text(json.dumps(client.get("/api/layout/case", headers=boss).json()), encoding="utf-8")
    out = subprocess.run([NODE, "-e", _RUNTIME, str(ROOT / "frontend/static/custom-layout.js"), str(ROOT / "frontend/static/layout-runtime.js"), str(pf), page, lkey, rename],
                         capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    r = json.loads(out.stdout.decode("utf-8"))
    base = QUOTES if lkey == "quotes" else TABS
    assert r["cols"] == [c for c in base if c != hide] and r["label"] == "新名稱"


def test_restricted_role_gets_the_same_api_answer_before_and_after(client, make_user):
    boss = _h(client, make_user, "q2_boss_r", "superadmin")
    low = _h(client, make_user, "q2_low", "engineer", modules=[])
    before = client.get("/api/quotations", headers=low)
    assert _publish(client, boss, [{"op": "show", "target": _col("quotations.html", "quotes", "amount")},
                                   {"op": "show", "target": _col("quotations.html", "quotes", "margin")}]).status_code == 200
    after = client.get("/api/quotations", headers=low)
    assert (after.status_code, after.json()) == (before.status_code, before.json())              # 版面「顯示金額欄」不改任何人拿到的資料


# ── 5. OFF 守門 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", ["quotations.html", "case-management.html"])
def test_flag_gated_x_show_has_no_static_inline_display(name):
    bad = []
    for m in re.finditer(r"<[a-zA-Z][^<>]*?>", _page(name), re.S):
        tag = m.group(0)
        xs = re.search(r'x-show="([^"]*)"', tag)
        if not xs or not re.search(r"\b(?:[lfctT]Shown|cShown|tShown)\(|\blayoutOn\b", xs.group(1)):
            continue
        st = re.search(r'(?<![:\w-])style="([^"]*)"', tag)
        if st and re.search(r"(^|;)\s*display\s*:", st.group(1)):
            bad.append(re.sub(r"\s+", " ", tag)[:120])
    assert not bad, bad


def test_registry_entries_say_what_layout_does_not_change():
    reg = {e["flag"]: e for e in json.loads((ROOT / "frontend" / "static" / "layout-pages.json").read_text(encoding="utf-8"))}
    q = reg["quotations"]
    assert (q["module"], q["page"]) == ("case", "quotations.html")
    txt = " ".join(q["notes"]) + q["impact"]
    assert "PDF" in txt and "順序" in txt and "金額" in txt
    assert any("分頁" in n for n in reg["case_management"]["notes"])


def test_quotations_colspans_follow_the_visible_column_count():
    src = _page("quotations.html")
    assert 'colspan="12"' not in src and src.count(':colspan="colSpan()"') == 3
    assert "colSpan() { return 12 - (this.layoutOn ?" in src                  # 關閉時恆為 12（與先前相同）


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_hidden_active_tab_falls_back_to_the_case_info_tab():
    """04：目前分頁被版面隱藏（?tab=、記住的分頁…）⇒ 退回案件資訊，不留一個沒有頁籤的內容面板。"""
    from modules.case.tests import test_bp1_layout_cases_2026_10_14 as T
    cols = json.dumps([{"field": f} for f in TABS if f != "feed"])
    r = T._node("o.layoutOn = true\n"
                "const out = {}\n"
                "o.activeTab = 'feed'; o.tabFix(); out.hidden = o.activeTab\n"
                "o.activeTab = 'exec'; o.tabFix(); out.visible = o.activeTab\n"
                "o.activeTab = 'zzz'; o.tabFix(); out.unknown = o.activeTab\n"
                "o.layoutOn = false; o.activeTab = 'feed'; o.tabFix(); out.off = o.activeTab\n"
                "console.log(JSON.stringify(out))", cols)
    assert r == {"hidden": "biz", "visible": "exec", "unknown": "zzz", "off": "feed"}
    assert 'class="cm-tabs" x-effect="tabFix()"' in _page("case-management.html")
