# -*- coding: utf-8 -*-
"""T60 S4：採購管理頁、設備登載頁、承攬商管理頁接上 P9 版面引擎（顯示／順序／標題），預設關閉。

與供應商頁（BP-1 第一刀）同一套做法，每頁證明：
1. 登記＝fallback＝頁面標題預設一致；每個登記的欄位都有畫法；核心欄位清單正確。
2. 旗標關閉：預設 False；頁面 deferred；原表格容器只多一個 `!layoutOn` 綁定；`initLayout()`（node 真的執行）
   旗標為假／讀不到時不呼叫 MotrixLayout.start()、不改 layoutOn、不打 /api/layout。
3. 旗標開啟：node 真的執行 ⇒ layoutOn=true、掛編輯器、啟動版面各一次。
4. 核心欄位不能隱藏（發布 422）；非核心可隱藏／改名／重排；發布→再發布→還原。
5. 受限角色：版面發布前後，同一個角色從同一支 API 拿到的狀態與內容完全相同（版面不改資料／權限）。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PAGES = ROOT / "frontend" / "pages"
MODS = ROOT / "backend" / "modules"
NODE = shutil.which("node")

# page → (module, list key, entity, flag field, core fields, factory name, original-container binding, API for the restricted-role control)
CFG = {
    "procurement.html": dict(module="analytics", key="materials", entity="material", flag="procurement",
                             core={"name", "status", "quoteNo"}, factory="app", orig='<div class="table-scroll" x-show="!layoutOn">',
                             api="/api/materials-summary", restricted=dict(role="sales", modules=[])),
    "devices.html": dict(module="analytics", key="devices", entity="device", flag="devices",
                         core={"name", "expiryDate", "warrantyStatus"}, factory="devicesPage", orig='<div class="table-scroll" x-show="!layoutOn">',
                         api="/api/devices", restricted=dict(role="sales", modules=[])),
    # BP-1／S3：客戶頁（L1 共用主檔頁面；擁有者是虛擬的 core，登記檔 core/l1_customization.json）。核心欄位 D6：公司名稱、統一編號、狀態
    "customers.html": dict(module="core", key="customers", entity="customer", flag="customers",
                           core={"name", "taxId", "status"}, factory="customersPage", orig='<div class="table-scroll" x-show="!layoutOn">',
                           api="/api/customers", restricted=dict(role="engineer", modules=[])),
    "vendor-contractors.html": dict(module="subcontract", key="vendors", entity="vendor", flag="vendor_contractors",
                                    core={"name", "taxId", "active"}, factory="vendorContractorsPage",
                                    orig='<div class="table-scroll" x-show="!loading && !layoutOn">',
                                    api="/api/vendor-contractors", restricted=dict(role="engineer", modules=["procurement"])),
}
PARAMS = sorted(CFG)


def _page(name):
    return (PAGES / name).read_text(encoding="utf-8")


def _manifest(cfg):
    if cfg["module"] == "core":
        return json.loads((ROOT / "backend" / "core" / "l1_customization.json").read_text(encoding="utf-8"))
    return json.loads((MODS / cfg["module"] / "module.json").read_text(encoding="utf-8"))


def _registered(name, cfg):
    m = _manifest(cfg)
    pg = [p for p in m["customization"]["pages"] if p["page"] == name][0]
    lst = [x for x in pg["lists"] if x["key"] == cfg["key"]][0]
    return [c["field"] for c in lst["columns"]], m["customization"]["fields"][cfg["entity"]]


# ── 1. 登記 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", PARAMS)
def test_manifest_is_valid_and_core_flags_match(name):
    from core import customization
    cfg = CFG[name]
    assert customization.validate_manifest(_manifest(cfg)) == []
    cols, fields = _registered(name, cfg)
    assert {f["key"] for f in fields if f["core"]} == cfg["core"]
    assert [f["key"] for f in fields] == cols


@pytest.mark.parametrize("name", PARAMS)
def test_fallback_labels_and_cells_match_registration(name):
    cfg = CFG[name]
    cols, fields = _registered(name, cfg)
    src = _page(name)
    fb = re.search(r"fallback:\s*\{\s*lists:\s*\{\s*%s:\s*\[([^\]]*)\]" % cfg["key"], src)
    assert fb and re.findall(r"'([^']+)'", fb.group(1)) == cols
    lbl = re.search(r"layoutLabel\(f\)\s*\{\s*return \(\{(.*?)\}\)\[f\]", src, re.S)
    assert lbl
    assert dict(re.findall(r"(\w+):\s*'([^']+)'", lbl.group(1))) == {f["key"]: f["label"] for f in fields}
    for c in cols:
        assert ("c.field === '%s'" % c in src) or ("col.field === '%s'" % c in src), "%s 欄沒有畫法（登記了卻是空白）" % c


@pytest.mark.parametrize("name", PARAMS)
def test_no_money_columns_are_registered(name):
    _, fields = _registered(name, CFG[name])
    money = re.compile(r"price|amount|cost|fee|total|金額|價|成本|費|薪|款")
    exempt = {"quoteCount"}                  # 客戶頁「累計報價」是**件數**（顯示「N 份」），不是金額；下面有專題鎖住
    assert [f["key"] for f in fields if (money.search(f["key"]) or money.search(f["label"])) and f["key"] not in exempt] == []


# ── 2. 旗標關閉 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", PARAMS)
def test_page_wiring_is_deferred_and_original_table_is_kept(name):
    cfg = CFG[name]
    src = _page(name)
    for tag in ('custom-layout.js', 'layout-runtime.js', 'layout-editor.js', 'def-governance.js'):
        assert tag in src
    assert re.search(r"MotrixLayout\.init\(\{[^}]*deferred:\s*true", src, re.S)
    assert src.count("MotrixLayout.start()") == 1
    body = src[src.index("async initLayout()"):]
    assert body.index("%s !== true) return" % cfg["flag"]) < body.index("MotrixLayout.start()")
    assert "/api/layout" not in src                                         # 版面請求只經由 runtime
    assert cfg["orig"] in src, "原表格容器的綁定不對（旗標關閉時必須照原樣顯示）"
    assert "$store.layout" not in src[src.index(cfg["orig"]):src.index(cfg["orig"]) + 3000].split("</table>")[0]   # 原表格不讀版面


def test_flag_defaults_are_off(client):
    from helpers import settings_registry as SR
    for cfg in CFG.values():
        assert SR.get("builder_layout", cfg["flag"]) is False


_HARNESS = r"""
const fs = require('fs')
const calls = { fetch: [], start: 0, mount: 0, slot: 0 }
global.window = global
global.localStorage = { getItem(k) { return k === 'motrix_session' ? JSON.stringify({ token: 't', role: 'superadmin' }) : null } }
global.location = { href: '' }
global.document = { addEventListener() {}, querySelector() { return { insertAdjacentHTML() { calls.slot++ } } } }
window.MotrixLayout = { init() {}, start() { calls.start++ } }
window.MotrixLayoutEditor = { mount() { calls.mount++ } }
window.MotrixGovLookup = { alpineState() { return {} } }          // 承攬商頁在建立元件時展開它
window.MotrixPrivacyNotice = { subjectState() { return {} }, contactsState() { return {} }, load: async () => null }
let FLAG = %(flag_value)s
global.fetch = async (url) => { calls.fetch.push(String(url)); if (FLAG === 'fail') throw new Error('x')
  return { ok: FLAG !== 'http', json: async () => ({ groups: { builder_layout: { %(flag)s: FLAG === true } } }) } }
const code = fs.readFileSync(process.argv[1], 'utf8')
const scripts = [...code.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).filter(s => s.includes('%(factory)s'))
eval(scripts[scripts.length - 1] + '\n;global.__f = %(factory)s')
const o = Object.assign({}, global.__f())
o.$nextTick = async () => {}
;(async () => {
  await o.initLayout.call(o)
  console.log(JSON.stringify({ layoutOn: o.layoutOn, calls, labelDefault: o.layoutLabel('zzz') }))
})().catch(e => { console.error(String(e)); process.exit(1) })
"""


def _node(name, flag_value):
    cfg = CFG[name]
    js = _HARNESS % dict(flag=cfg["flag"], factory=cfg["factory"], flag_value=flag_value)
    out = subprocess.run([NODE, "-e", js, str(PAGES / name)], capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    return json.loads(out.stdout.decode("utf-8"))


@pytest.mark.skipif(NODE is None, reason="沒有 node")
@pytest.mark.parametrize("name", PARAMS)
@pytest.mark.parametrize("flag_value", ["false", "'http'", "'fail'"])
def test_flag_off_or_unreadable_changes_nothing(name, flag_value):
    """旗標為假、讀取失敗（HTTP 錯誤／斷線）：不啟動版面、不掛編輯器、不插入編輯位置、layoutOn 維持 false；唯一的請求是讀旗標。"""
    r = _node(name, flag_value)
    assert r["layoutOn"] is False
    assert r["calls"]["start"] == 0 and r["calls"]["mount"] == 0 and r["calls"]["slot"] == 0
    assert r["calls"]["fetch"] == ["/api/settings-center/public?groups=builder_layout"]


@pytest.mark.skipif(NODE is None, reason="沒有 node")
@pytest.mark.parametrize("name", PARAMS)
def test_flag_on_starts_layout_once(name):
    r = _node(name, "true")
    assert r["layoutOn"] is True
    assert r["calls"]["start"] == 1 and r["calls"]["mount"] == 1 and r["calls"]["slot"] == 1
    assert r["calls"]["fetch"] == ["/api/settings-center/public?groups=builder_layout"]       # 版面本身的請求由 runtime（這裡是假的）發


# ── 3/4. 版面：核心、發布、還原；受限角色 ──────────────────────────────────
def _h(client, make_user, name, role, modules=None):
    u, p = make_user(name, "Lay-Pass-123", role=role, modules=modules)[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _base(cfg):
    return "/api/definitions/layout/module:%s" % cfg["module"]


def _col(name, cfg, field):
    return "%s:%s/list:%s/column:%s" % (cfg["module"], name, cfg["key"], field)


def _publish(client, h, cfg, ops, scope="company"):
    r = client.put(_base(cfg) + "/draft", headers=h, params={"scope": scope}, json={"body": {"ops": ops}})
    assert r.status_code == 200, r.text
    return client.post(_base(cfg) + "/publish", headers=h, params={"scope": scope}, json={"note": "t"})


def _eff(client, h, cfg):
    return client.get("/api/layout/" + cfg["module"], headers=h).json()


@pytest.mark.parametrize("name", PARAMS)
def test_core_cannot_be_hidden_but_noncore_can_be_hidden_renamed_reordered_and_restored(client, make_user, name):
    cfg = CFG[name]
    cols, _ = _registered(name, cfg)
    boss = _h(client, make_user, "s4_boss_" + cfg["flag"], "superadmin")
    ids = {p["id"] for p in _eff(client, boss, cfg)["points"]}
    assert all(_col(name, cfg, c) in ids for c in cols)
    for core in sorted(cfg["core"]):
        r = _publish(client, boss, cfg, [{"op": "hide", "target": _col(name, cfg, core)}])
        assert r.status_code == 422, (core, r.text)
    assert client.get(_base(cfg) + "?scope=company", headers=boss).json().get("latest") is None
    noncore = [c for c in cols if c not in cfg["core"]]
    v1 = [{"op": "hide", "target": _col(name, cfg, noncore[0])}]
    v2 = [{"op": "relabel", "target": _col(name, cfg, noncore[1]), "label": "改名"},
          {"op": "reorder", "target": "%s:%s/list:%s" % (cfg["module"], name, cfg["key"]), "order": [_col(name, cfg, c) for c in reversed(cols)]}]
    assert _publish(client, boss, cfg, v1).status_code == 200
    assert _publish(client, boss, cfg, v2).status_code == 200
    assert _eff(client, boss, cfg)["ops"] == v2
    r = client.post("/api/definitions/layout/module:%s/restore/1" % cfg["module"], headers=boss, params={"scope": "company"}, json={"note": "back"})
    assert r.status_code == 200, r.text
    assert _eff(client, boss, cfg)["ops"] == v1
    assert _publish(client, boss, cfg, []).status_code == 200                 # 還原到預設＝發布空操作
    assert _eff(client, boss, cfg)["ops"] == []


@pytest.mark.parametrize("name", PARAMS)
def test_non_superadmin_cannot_publish(client, make_user, name):
    cfg = CFG[name]
    admin = _h(client, make_user, "s4_admin_" + cfg["flag"], "admin")
    r = client.put(_base(cfg) + "/draft", headers=admin, params={"scope": "company"}, json={"body": {"ops": []}})
    assert r.status_code in (401, 403)


@pytest.mark.parametrize("name", PARAMS)
def test_restricted_role_gets_the_same_api_answer_before_and_after_a_layout(client, make_user, name):
    """版面只決定『已收到的資料』怎麼排，不改權限也不改資料：受限角色發布前後從同一支 API 拿到一模一樣的狀態與內容。"""
    cfg = CFG[name]
    boss = _h(client, make_user, "s4_boss2_" + cfg["flag"], "superadmin")
    rs = cfg["restricted"]
    low = _h(client, make_user, "s4_low_" + cfg["flag"], rs["role"], modules=rs["modules"])
    before = client.get(cfg["api"], headers=low)
    assert before.status_code in (200, 403)
    if before.status_code == 200:
        assert before.json() in ([], {"items": []})                           # 非管理員：沒有資料
    cols, _ = _registered(name, cfg)
    ops = [{"op": "show", "target": _col(name, cfg, c)} for c in cols if c not in cfg["core"]]
    assert _publish(client, boss, cfg, ops).status_code == 200
    after = client.get(cfg["api"], headers=low)
    assert (after.status_code, after.json()) == (before.status_code, before.json())


def test_customers_quote_count_is_a_count_not_money():
    src = _page("customers.html")
    cell = src[src.index("col.field === 'quoteCount'"):].split("</template>")[0]
    assert "c.quoteCount + ' 份'" in cell and not re.search(r"total|amount|toLocaleString|NT\$", cell)
