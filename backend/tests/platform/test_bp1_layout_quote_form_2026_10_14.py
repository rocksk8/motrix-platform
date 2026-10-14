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
const calls = { fetch: [], start: 0, mount: 0, slot: 0 }
global.window = global
global.localStorage = { getItem(k) { return k === 'motrix_session' ? JSON.stringify({ token: 't', role: 'superadmin' }) : null } }
global.location = { href: '', search: '' }
global.document = { addEventListener() {}, getElementById() { return null }, querySelector() { return { insertAdjacentHTML() { calls.slot++ } } } }
const stub = () => new Proxy(function () {}, { get: () => stub(), apply: () => ({}) })
for (const n of ['MotrixPrivacyNotice','MotrixDate','LegalRound','ProfitRules','AltItems','MarginTone','Sortable','MotrixFilePreview','MotrixApprovalCascade']) window[n] = stub()
window.MotrixLayout = { init() {}, start() { calls.start++ } }
window.MotrixLayoutEditor = { mount() { calls.mount++ } }
let FLAG = %(flag)s
global.fetch = async (url) => { calls.fetch.push(String(url)); if (FLAG === 'fail') throw new Error('x')
  return { ok: FLAG !== 'http', json: async () => ({ groups: { builder_layout: { quotation_form: FLAG === true } } }) } }
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


def _node(flag):
    out = subprocess.run([NODE, "-e", _HARNESS % dict(flag=flag), str(source_tree.page_file(PAGE_NAME))], capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    return json.loads(out.stdout.decode("utf-8"))


@pytest.mark.skipif(NODE is None, reason="沒有 node")
@pytest.mark.parametrize("flag", ["false", "'http'", "'fail'"])
def test_flag_off_or_unreadable_changes_nothing(flag):
    r = _node(flag)
    assert r["layoutOn"] is False and r["neutral"] == {"shown": True, "order": "", "label": "傳真", "sec": "客戶資訊"}      # 綁定函式回中性值
    assert r["calls"]["start"] == 0 and r["calls"]["mount"] == 0 and r["calls"]["slot"] == 0
    assert r["calls"]["fetch"] == ["/api/settings-center/public?groups=builder_layout"]


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
