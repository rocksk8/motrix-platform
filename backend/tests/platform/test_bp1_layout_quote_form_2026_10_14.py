# -*- coding: utf-8 -*-
"""Q1：報價單表單（quotation-form.html）的非金額區塊——基、客戶、案件、條件——接上 P9 版面引擎，預設關閉。

1. 登記：module.json 通過驗證；fallback＝登記順序；核心欄位如耦合文件 §3.2；沒有金額欄；每個登記欄位在頁面上都有 fShown／fo／fLabel 綁定。
2. 旗標關閉：預設 False；頁面 deferred；綁定函式回中性值（node 實跑）；initLayout 在旗標為假／讀不到時不啟動版面。
3. 旗標開啟：node 實跑 ⇒ 啟動版面各一次。
4. 核心欄位不能隱藏（發布 422）；非核心可隱藏／改名／重排；發布→再發布→還原。
5. 受限角色：版面發布前後，同一個角色從同一支 API 拿到一模一樣的內容。
6. OFF 守門：旗標綁定的 x-show 不得掛在帶行內 display 的元素上（Alpine 會洗掉行內 display）。
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
PAGE_NAME = "quotation-form.html"
BASE = "/api/definitions/layout/module:case"

FORMS = {
    "qbasic": ["quoteNo", "locationId", "quoteDate", "validDays", "version", "salesPerson", "salesPhone", "salesEmail"],
    "qcustomer": ["customerName", "customerTaxId", "contactName", "contactPhone", "contactEmail", "contactFax", "deliveryAddress"],
    "qproject": ["projectName", "deliveryLocation"],
    "qterms": ["paymentTerms", "deliveryTerms", "acceptanceTerms", "warrantyTerms", "afterSales"],
}
ENTITY = {"qbasic": "qinfo", "qcustomer": "qcustomer", "qproject": "qproject", "qterms": "qterms"}
NONCORE = {"version", "contactEmail", "contactFax", "deliveryLocation", "paymentTerms", "deliveryTerms", "acceptanceTerms", "warrantyTerms", "afterSales"}
CORE = {f for fs in FORMS.values() for f in fs} - NONCORE


def _page():
    return source_tree.page_file(PAGE_NAME).read_text(encoding="utf-8")


def _manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _reg():
    m = _manifest()
    pg = [p for p in m["customization"]["pages"] if p["page"] == PAGE_NAME][0]
    return pg, m["customization"]["fields"]


# ── 1. 登記 ────────────────────────────────────────────────────────────────
def test_manifest_valid_order_and_core_flags():
    assert customization.validate_manifest(_manifest()) == []
    pg, fields = _reg()
    assert pg["lists"] == []
    assert {f["form"] if "form" in f else f["key"]: [fld for s in f["sections"] for fld in s["fields"]] for f in pg["forms"]} == FORMS
    for form, fs in FORMS.items():
        flags = {x["key"]: x["core"] for x in fields[ENTITY[form]]}
        assert list(flags) == fs
        assert {k for k, v in flags.items() if v} == set(fs) & CORE


def test_no_money_fields_are_registered():
    _, fields = _reg()
    money = re.compile(r"price|amount|cost|fee|total|tax(?!Id)|margin|discount|金額|單價|成本|費|毛利|稅額|折扣")
    keys = [(e, f["key"], f["label"]) for e in ENTITY.values() for f in fields[e]]
    assert [k for k in keys if money.search(k[1]) or money.search(k[2])] == []


def test_every_registered_field_and_section_is_bound_in_the_page():
    src = _page()
    for form, fs in FORMS.items():
        for f in fs:
            assert "fShown('%s', '%s')" % (form, f) in src and "fo('%s', '%s')" % (form, f) in src, (form, f)
            assert "fLabel('%s', '%s'," % (form, f) in src, (form, f)
        assert "secLabel('%s'," % form in src
    fb = re.search(r"fallback:\s*\{\s*forms:\s*\{(.*?)\}\s*\}", src, re.S).group(1)
    got = {m.group(1): re.findall(r"'([^']+)'", m.group(2)) for m in re.finditer(r"(\w+):\s*\[([^\]]*)\]", fb)}
    assert got == FORMS                                                              # fallback＝登記順序
    for tag in ("custom-layout.js", "layout-runtime.js", "layout-editor.js", "def-governance.js"):
        assert tag in src


def test_money_and_signing_areas_have_no_layout_bindings():
    src = _page()
    # 品項、合計、簽署、成本面板的區段：從「三、品項明細」到「五」之前、以及「六」之後，不可以出現版面綁定
    a, b = src.index("三、品項明細"), src.index("<!-- 五")
    c = src.index('<div class="section-num">六</div>')
    for seg in (src[a:b], src[c:c + 60000]):
        assert "fShown(" not in seg and "fLabel(" not in seg and "secLabel(" not in seg


def test_flag_default_off(client):
    from helpers import settings_registry as SR
    assert SR.get("builder_layout", "quotation_form") is False


# ── 2/3. 旗標關閉／開啟（node 實跑）────────────────────────────────────────
_HARNESS = r"""
const fs = require('fs')
const calls = { fetch: [], start: 0, mount: 0, slot: 0, selectors: [], cf: 0 }
global.window = global
global.localStorage = { getItem(k) { return k === 'motrix_session' ? JSON.stringify({ token: 't', role: 'superadmin' }) : null } }
global.location = { href: '', search: '' }
const PAGE_SRC = fs.readFileSync(process.argv[1], 'utf8')
const exists = (sel) => sel.split(',').map(x => x.trim()).some(t => t.startsWith('.') ? new RegExp('class="[^"]*\\b' + t.slice(1) + '\\b[^"]*"').test(PAGE_SRC)
  : t.startsWith('#') ? PAGE_SRC.includes('id="' + t.slice(1) + '"') : new RegExp('<' + t + '[\\s>]').test(PAGE_SRC))
global.document = { addEventListener() {}, getElementById() { return null },
  querySelector(sel) { calls.selectors.push(sel); return exists(sel) ? { insertAdjacentHTML() { calls.slot++ } } : null } }
const stub = () => new Proxy(function () {}, { get: () => stub(), apply: () => ({}) })
for (const n of ['MotrixPrivacyNotice','MotrixDate','LegalRound','ProfitRules','AltItems','MarginTone','Sortable','MotrixFilePreview','MotrixApprovalCascade']) window[n] = stub()
window.MotrixLayout = { init() {}, start() { calls.start++ } }
window.MotrixLayoutEditor = { mount() { calls.mount++ } }
window.MotrixCustomFields = { start() { calls.cf++ } }
let FLAG = %(flag)s
let CF = %(cf)s
global.fetch = async (url) => { calls.fetch.push(String(url)); if (FLAG === 'fail') throw new Error('x')
  return { ok: FLAG !== 'http', json: async () => ({ groups: { builder_layout: { quotation_form: FLAG === true }, builder_custom_fields: { enabled: CF } } }) } }
eval(fs.readFileSync(process.argv[2], 'utf8'))          // public-flags.js
const code = fs.readFileSync(process.argv[1], 'utf8')
const scripts = [...code.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).filter(s => s.includes('function quotationForm'))
eval(scripts[scripts.length - 1] + '\n;global.__f = quotationForm')
const o = Object.assign({}, global.__f())
o.$nextTick = async () => {}
o.session = { token: 't' }
;(async () => {
  const neutral = { shown: o.fShown('qcustomer', 'contactFax'), order: o.fo('qcustomer', 'contactFax'), label: o.fLabel('qcustomer', 'contactFax', '傳真'), sec: o.secLabel('qcustomer', '客戶資訊') }
  await o.initLayout.call(o)
  console.log(JSON.stringify({ layoutOn: o.layoutOn, calls, neutral }))
})().catch(e => { console.error(String(e)); process.exit(1) })
"""


def _node(flag, cf="false"):
    out = subprocess.run([NODE, "-e", _HARNESS % dict(flag=flag, cf=cf), str(source_tree.page_file(PAGE_NAME)), str(ROOT / "frontend/static/public-flags.js")],
                         capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    return json.loads(out.stdout.decode("utf-8"))


@pytest.mark.skipif(NODE is None, reason="沒有 node")
@pytest.mark.parametrize("flag", ["false", "'http'", "'fail'"])
def test_flag_off_or_unreadable_changes_nothing(flag):
    r = _node(flag)
    assert r["layoutOn"] is False and r["neutral"] == {"shown": True, "order": {}, "label": "傳真", "sec": "客戶資訊"}      # 綁定函式回中性值
    assert r["calls"]["start"] == 0 and r["calls"]["mount"] == 0 and r["calls"]["slot"] == 0
    f = r["calls"]["fetch"]
    assert f[0] == "/api/settings-center/public?groups=builder_layout,builder_custom_fields,builder_stage_templates"      # 一個共用 GET 取三個旗標（S-ST2 起多 builder_stage_templates，同一個請求）
    assert all(u.startswith("/api/settings-center/public?groups=") for u in f)                                     # 失敗時才逐組重試（仍只讀設定）
    if flag == "false":
        assert len(f) == 1
    assert r["calls"]["cf"] == 0                                                                                   # 自訂欄位旗標關 ⇒ 不去讀欄位定義


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_flag_on_starts_layout_once():
    r = _node("true")
    assert r["layoutOn"] is True and r["calls"]["start"] == 1 and r["calls"]["mount"] == 1 and r["calls"]["slot"] == 1


def test_page_defers_the_layout_request():
    src = _page()
    assert re.search(r"MotrixLayout\.init\(\{[^}]*deferred:\s*true", src, re.S) and "/api/layout" not in src
    body = src[src.index("async initLayout()"):]
    assert body.index("quotation_form !== true) return") < body.index("MotrixLayout.start()")


# ── 4/5. 版面：核心、發布、還原；受限角色 ──────────────────────────────────
def _h(client, make_user, name, role, modules=None):
    u, p = make_user(name, "Lay-Pass-123", role=role, modules=modules)[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _fld(form, field):
    return "case:%s/form:%s/field:%s" % (PAGE_NAME, form, field)


def _publish(client, h, ops):
    r = client.put(BASE + "/draft", headers=h, params={"scope": "company"}, json={"body": {"ops": ops}})
    assert r.status_code == 200, r.text
    return client.post(BASE + "/publish", headers=h, params={"scope": "company"}, json={"note": "t"})


def test_point_ids_exist_and_core_cannot_be_hidden_or_renamed(client, make_user):
    boss = _h(client, make_user, "qf_boss", "superadmin")
    pts = client.get("/api/layout/case", headers=boss).json()["points"]
    ids = {p["id"] for p in pts}
    for form, fs in FORMS.items():
        for f in fs:
            assert _fld(form, f) in ids, (form, f)
    for core in sorted(CORE):
        form = next(k for k, v in FORMS.items() if core in v)
        assert _publish(client, boss, [{"op": "hide", "target": _fld(form, core)}]).status_code == 422, core
        assert _publish(client, boss, [{"op": "relabel", "target": _fld(form, core), "label": "x"}]).status_code == 422, core
    assert client.get(BASE + "?scope=company", headers=boss).json().get("latest") is None


def test_noncore_fields_can_be_hidden_renamed_reordered_and_restored(client, make_user):
    boss = _h(client, make_user, "qf_boss2", "superadmin")
    v1 = [{"op": "hide", "target": _fld("qcustomer", "contactFax")}, {"op": "hide", "target": _fld("qterms", "afterSales")}]
    v2 = [{"op": "relabel", "target": _fld("qterms", "warrantyTerms"), "label": "保固與維護"}]
    assert _publish(client, boss, v1).status_code == 200
    assert _publish(client, boss, v2).status_code == 200
    eff = client.get("/api/layout/case", headers=boss).json()
    assert [o for o in eff["ops"] if o["target"].startswith("case:" + PAGE_NAME)] == v2
    r = client.post(BASE + "/restore/1", headers=boss, params={"scope": "company"}, json={"note": "back"})
    assert r.status_code == 200, r.text
    eff = client.get("/api/layout/case", headers=boss).json()
    assert [o for o in eff["ops"] if o["target"].startswith("case:" + PAGE_NAME)] == v1


def test_non_superadmin_cannot_publish(client, make_user):
    admin = _h(client, make_user, "qf_admin", "admin")
    assert client.put(BASE + "/draft", headers=admin, params={"scope": "company"}, json={"body": {"ops": []}}).status_code in (401, 403)


def test_restricted_role_gets_the_same_api_answer_before_and_after_a_layout(client, make_user):
    boss = _h(client, make_user, "qf_boss3", "superadmin")
    low = _h(client, make_user, "qf_low", "engineer", modules=[])
    before = client.get("/api/quotations", headers=low)
    ops = [{"op": "hide", "target": _fld("qcustomer", "contactFax")}]
    assert _publish(client, boss, ops).status_code == 200
    after = client.get("/api/quotations", headers=low)
    assert (after.status_code, after.json()) == (before.status_code, before.json())             # 版面不改資料、不改權限


# ── 6. OFF 守門：flag 綁定的 x-show 不掛在帶行內 display 的元素 ───────────────────
def test_flag_gated_x_show_has_no_static_inline_display():
    bad = []
    for m in re.finditer(r"<[a-zA-Z][^<>]*?>", _page(), re.S):
        tag = m.group(0)
        xs = re.search(r'x-show="([^"]*)"', tag)
        if not xs or not re.search(r"\b[lf]Shown\(|\blayoutOn\b", xs.group(1)):
            continue
        st = re.search(r'(?<![:\w-])style="([^"]*)"', tag)
        if st and re.search(r"(^|;)\s*display\s*:", st.group(1)):
            bad.append(re.sub(r"\s+", " ", tag)[:120])
    assert not bad, bad


def test_registry_entry_and_notes_are_in_the_single_registry():
    reg = json.loads((ROOT / "frontend" / "static" / "layout-pages.json").read_text(encoding="utf-8"))
    e = [x for x in reg if x["flag"] == "quotation_form"][0]
    assert (e["module"], e["page"]) == ("case", PAGE_NAME)
    text = " ".join(e["notes"]) + e["impact"]
    assert "PDF" in text and "照樣" in text and "金額" in text                                  # 編輯器會明講：改名／隱藏不改 PDF、金額不在範圍


def test_toolbar_anchor_really_exists_in_the_page_and_style_binding_is_object_form():
    """04 審查：這頁沒有 .pg__t／h1；編輯器入口必須用頁面真的有的錨點。:style 一律用物件形式（字串形式會整串覆蓋，洗掉 x-show 的 display:none）。"""
    src = _page()
    assert "document.querySelector('.form-toolbar__left')" in src and 'class="form-toolbar__left"' in src
    assert "querySelector('.pg__t" not in src and "querySelector('h1" not in src
    assert re.search(r"fo\(form, f\) \{ return this\.layoutOn \? \{ order:", src)
    assert not re.search(r"'order:'", src[src.index("fShown(form, f)"):src.index("async initLayout()")])      # 不再回 'order:N' 字串
    for m in re.finditer(r':style="fo\(', src):
        tag = src[src.rfind("<div", 0, m.start()):m.start()]
        assert 'x-show="' in tag                                                                            # 每個 :style="fo(..)" 都和 x-show 同一個元素（物件形式才安全）


_RUNTIME = r"""
const fs = require('fs')
const payloads = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'))
global.window = global
const listeners = []
global.localStorage = { getItem(k) { return k === 'motrix_session' ? JSON.stringify({ token: 't', role: 'superadmin' }) : null } }
global.document = { addEventListener(n, f) { if (n === 'alpine:init') listeners.push(f) }, getElementById() { return null }, head: { appendChild() {} },
  documentElement: { setAttribute() {} }, querySelectorAll() { return [] }, createElement() { return { id: '', textContent: '' } } }
const stores = {}
global.Alpine = { store(n, v) { if (v !== undefined) stores[n] = v; return stores[n] } }
global.fetch = async (url) => { const u = String(url); const key = u.indexOf('role=') >= 0 ? 'preview' : 'live'
  return { ok: true, json: async () => payloads[key] } }
const stub = () => new Proxy(function () {}, { get: () => stub(), apply: () => ({}) })
for (const n of ['MotrixPrivacyNotice','MotrixDate','LegalRound','ProfitRules','AltItems','MarginTone','Sortable','MotrixFilePreview','MotrixApprovalCascade']) window[n] = stub()
eval(fs.readFileSync(process.argv[2], 'utf8'))          // custom-layout.js
eval(fs.readFileSync(process.argv[3], 'utf8'))          // layout-runtime.js
MotrixLayout.init({ module: 'case', page: 'quotation-form.html', deferred: true, fallback: { forms: {} } })
listeners.forEach(f => f())
const code = fs.readFileSync(process.argv[1], 'utf8')
const scripts = [...code.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).filter(s => s.includes('function quotationForm'))
eval(scripts[scripts.length - 1] + '\n;global.__f = quotationForm')
const o = Object.assign({}, global.__f())
o.layoutOn = true
const view = () => ({ cf: [o.fShown('qcustomer', 'contactFax'), o.fo('qcustomer', 'contactFax')],
  addr: [o.fShown('qcustomer', 'deliveryAddress'), o.fo('qcustomer', 'deliveryAddress')],
  cn: [o.fShown('qcustomer', 'customerName'), o.fo('qcustomer', 'customerName')],
  lab: o.fLabel('qterms', 'warrantyTerms', '保固條件') })
;(async () => {
  await MotrixLayout.start()
  const live = view()
  const fl = await MotrixLayout.fetchLayout('sales')
  const st = MotrixCustomLayout.applyOps(fl.points, 'quotation-form.html', fl.ops).state
  MotrixLayout.show(st, 'preview', 'sales')
  const prev = view()
  MotrixLayout.show(null)
  const back = view()
  console.log(JSON.stringify({ live, prev, back }))
})().catch(e => { console.error(String(e)); process.exit(1) })
"""


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_hide_and_reorder_in_one_publish_then_switching_preview_role_keeps_hidden_hidden(client, make_user, tmp_path):
    """04 的 ON 狀態提醒：同一次發布『隱藏一個欄位＋重排其他欄位』，再切換預覽角色／回到自己的版面——隱藏的要一直是隱藏，順序是物件形式的 order。"""
    boss = _h(client, make_user, "qf_boss4", "superadmin")
    sec = "case:%s/form:qcustomer/section:main" % PAGE_NAME
    ops = [{"op": "hide", "target": _fld("qcustomer", "contactFax")},
           {"op": "relabel", "target": _fld("qterms", "warrantyTerms"), "label": "保固與維護"},
           {"op": "move", "target": _fld("qcustomer", "deliveryAddress"), "to": sec, "index": 0}]
    assert _publish(client, boss, ops).status_code == 200
    live = client.get("/api/layout/case", headers=boss).json()
    prev = client.get("/api/layout/case?role=sales", headers=boss).json()
    assert prev["ops"] == live["ops"]                                                   # 公司層版面：各角色看到同一份
    pf = tmp_path / "payloads.json"
    pf.write_text(json.dumps({"live": live, "preview": prev}), encoding="utf-8")
    out = subprocess.run([NODE, "-e", _RUNTIME, str(source_tree.page_file(PAGE_NAME)), str(ROOT / "frontend/static/custom-layout.js"),
                          str(ROOT / "frontend/static/layout-runtime.js"), str(pf)], capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    r = json.loads(out.stdout.decode("utf-8"))
    for phase in ("live", "prev", "back"):
        v = r[phase]
        assert v["cf"][0] is False, phase                                               # 隱藏的欄位在每個階段都是隱藏（含切換預覽角色之後）
        assert v["cn"][0] is True and v["addr"][0] is True
        assert isinstance(v["addr"][1], dict) and isinstance(v["cn"][1], dict) and "order" in v["addr"][1]    # 物件形式，不是 'order:N' 字串
        assert v["lab"] == "保固與維護"
    assert r["live"]["addr"][1]["order"] < r["live"]["cn"][1]["order"]                  # 搬到最前面的欄位排在前
    assert r["prev"] == r["live"] == r["back"]


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_custom_fields_start_only_when_their_own_flag_is_on_independent_of_the_layout_flag():
    r = _node("false", cf="true")
    assert r["calls"]["cf"] == 1 and r["layoutOn"] is False and r["calls"]["start"] == 0          # 版面旗標關、自訂欄位旗標開：只起自訂欄位
    r = _node("true", cf="true")
    assert r["calls"]["cf"] == 1 and r["layoutOn"] is True and r["calls"]["start"] == 1


# ── Q3：自訂欄位區塊 ──────────────────────────────────────────────────────
def test_custom_field_block_sits_inside_the_case_info_section_and_is_flag_guarded():
    src = _page()
    a = src.index('<div class="section-num">二</div>')
    b = src.index("<!-- 三、品項明細 -->")
    sec = src[a:b]
    assert 'data-testid="cf-section"' in sec and "$store.cf && $store.cf.enabled" in sec          # 旗標開啟才畫；在『二、案件資訊』裡
    for t in ("text", "date", "select", "checkbox"):
        assert "f.type === '%s'" % t in sec
    assert 'class="form-input"' in sec and ':disabled="cfLocked()"' in sec                         # 輸入框沿用鎖定樣式；勾選框另綁鎖定
    assert "MotrixCustomFields.init({ recordType: 'quotation'" in src and "deferred: true" in src.split("recordType: 'quotation'")[1].split("})")[0]
    assert "/api/custom-fields" not in re.sub(r"//[^\n]*", "", src.replace("<!--", "//").replace("-->", ""))        # 頁面本身不打（只有程式庫在旗標開啟後才打）
    for tag in ("public-flags.js", "custom-fields.js"):
        assert tag in src


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_cf_get_set_follow_the_no_value_no_key_rule():
    js = _HARNESS.split("const code = ")[0].replace("let FLAG = %(flag)s", "let FLAG = true").replace("let CF = %(cf)s", "let CF = false")
    js += r"""
const code = fs.readFileSync(process.argv[1], 'utf8')
const scripts = [...code.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).filter(s => s.includes('function quotationForm'))
eval(scripts[scripts.length - 1] + '\n;global.__f = quotationForm')
const o = global.__f()
o.setDirty = () => { o.dirty = (o.dirty || 0) + 1 }
const out = {}
o.q.customFields = undefined
o.cfSet('f1', '甲'); out.a = JSON.stringify(o.q.customFields)
o.cfSet('f2', true); out.b = JSON.stringify(o.q.customFields)
o.cfSet('f1', ''); out.c = JSON.stringify(o.q.customFields)
o.cfSet('f2', false); out.d = ('customFields' in o.q); out.dirty = o.dirty
o.q.status = '已送出'; o.unlocked = false; out.locked = o.cfLocked(); o.unlocked = true; out.unlocked = o.cfLocked()
out.get = o.cfGet('zzz')
console.log(JSON.stringify(out))
"""
    out = subprocess.run([NODE, "-e", js, str(source_tree.page_file(PAGE_NAME)), str(ROOT / "frontend/static/public-flags.js")], capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    r = json.loads(out.stdout.decode("utf-8"))
    assert r["a"] == '{"f1":"甲"}' and r["c"] == '{"f2":true}' and r["d"] is False and r["locked"] is True and r["unlocked"] is False
