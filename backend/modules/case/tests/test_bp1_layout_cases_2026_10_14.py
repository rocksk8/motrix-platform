# -*- coding: utf-8 -*-
"""BP-1 第二頁：案件管理頁的案件清單（卡片）接上 P9 版面引擎（顯示／順序／業務標題），預設關閉。

要證明的事：
1. 登記與 fallback 一致；每個登記的項目在卡片上都有綁定（不會有登記了卻沒作用的項目）。
2. 旗標關閉：預設 False；頁面 deferred、不打 /api/layout；旗標關閉時所有綁定函式回中性值（lShown＝true、lo＝''）＝畫面不變（用 node 真的執行）。
3. 旗標開啟後：隱藏／順序依版面（node 真的執行）；核心欄位（案號、狀態）不能隱藏；發布→還原。
4. 金額與權限：受限角色（有案件但沒有財務檢視）的清單 API 金額為空、moneyMasked；發布「顯示金額」的版面後仍然如此（版面不改資料）。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
from core import source_tree   # noqa: E402  頁面路徑一律經 source_tree（守門 test_page_paths_centralized）
PAGE = source_tree.page_file("case-management.html")
MANIFEST = HERE.parent / "module.json"

KEY = "module:case"
BASE = "/api/definitions/layout/" + KEY
COL = "case:case-management.html/list:cases/column:"
LIST = "case:case-management.html/list:cases"
CORE = ("quoteNo", "dealTag")
NONCORE = ("customer", "sales", "amount", "stageProgress", "date")


def _page():
    return PAGE.read_text(encoding="utf-8")


def _registered():
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    pg = [p for p in m["customization"]["pages"] if p["page"] == "case-management.html"][0]
    return [c["field"] for c in pg["lists"][0]["columns"]], m["customization"]["fields"]["case"]


def _part_source():
    src = _page()
    i = src.index("// BP-1：案件清單（卡片）可自訂版面")
    a = src.rindex("<script>", 0, i)
    return src[a + len("<script>"):src.index("</script>", i)]


# ── 1. 登記 ────────────────────────────────────────────────────────────────
def test_manifest_registration_is_valid():
    from core import customization
    assert customization.validate_manifest(json.loads(MANIFEST.read_text(encoding="utf-8"))) == []


def test_fallback_equals_registered_order_and_core_flags():
    cols, fields = _registered()
    fb = re.search(r"fallback:\s*\{\s*lists:\s*\{\s*cases:\s*\[([^\]]*)\]", _page())
    assert fb and re.findall(r"'([^']+)'", fb.group(1)) == cols
    assert [f["key"] for f in fields if f["core"]] == list(CORE)


def test_every_registered_item_is_bound_on_the_card():
    src = _page()
    card = src[src.index('<div class="cm-card" :class="{selected'):src.index("<!-- CM6")]
    assert "lo('quoteNo')" in card and "lo('dealTag')" in card
    for f in NONCORE:
        assert "lShown('%s')" % f in card, "卡片沒有綁定 %s（登記了卻沒作用）" % f
        assert "lo('%s')" % f in card


def test_original_card_content_is_still_there():
    """旗標關閉時看到的內容：金額遮蔽、階段進度、業務前綴、點擊與批次選取都還在。"""
    src = _page()
    card = src[src.index('<div class="cm-card" :class="{selected'):src.index("<!-- CM6")]
    for needle in ("c.moneyMasked ? '—' : 'NT$ '", "@click=\"selectCase(c.quote_no)\"", 'data-testid="batch-check"',
                   "missingDocTags(c)", "isUnread(c)", "c.stage_overdue > 0", "cm-card__date"):
        assert needle in card, needle


# ── 2. 旗標關閉 ────────────────────────────────────────────────────────────
def test_flag_default_off_and_page_is_deferred():
    from helpers import settings_registry as SR
    assert SR.get("builder_layout", "case_management") is False
    src = _page()
    part = _part_source()
    assert re.search(r"MotrixLayout\.init\(\{[^}]*deferred:\s*true", part, re.S)
    assert part.count("MotrixLayout.start()") == 1
    body = part[part.index("async initLayout()"):]
    assert body.index("case_management !== true) return") < body.index("MotrixLayout.start()")
    assert "/api/layout" not in src


NODE = shutil.which("node")


def _run_node(js):
    out = subprocess.run([NODE, "-e", js], capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    return json.loads(out.stdout.decode("utf-8"))


_HARNESS = r"""
const code = %(code)s
global.window = global
window.CM_PARTS = []
window.MotrixLayout = { init() {}, start() {} }
let COLS = %(cols)s
window.Alpine = { store() { return { cols() { return COLS }, colLabel(l, f, d) { return d } } }, $data() { return {} } }
global.document = { addEventListener() {} }
global.localStorage = { getItem() { return null } }
eval(code)
const o = Object.assign({}, window.CM_PARTS[0]())
%(body)s
"""


def _node(body, cols="[]"):
    return _run_node(_HARNESS % {"code": json.dumps(_part_source()), "cols": cols, "body": body})


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_flag_off_every_binding_is_neutral():
    """旗標關閉（layoutOn=false）：所有綁定回中性值 ⇒ 卡片的顯示與樣式與先前相同。"""
    r = _node("console.log(JSON.stringify({show: ['quoteNo','dealTag','customer','sales','amount','stageProgress','date'].map(f => o.lShown(f)),"
              " lo: ['quoteNo','customer','amount','date'].map(f => o.lo(f)), head: o.loHead(), foot: o.loFooter(), label: o.lLabel('sales', '業務')}))")
    assert r["show"] == [True] * 7 and r["lo"] == [""] * 4 and r["head"] == "" and r["foot"] == "" and r["label"] == "業務"


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_flag_on_follows_the_layout_order_and_hides():
    cols = json.dumps([{"field": f} for f in ("quoteNo", "dealTag", "date", "customer", "amount")])      # sales、stageProgress 被隱藏；日期移到前面
    r = _node("o.layoutOn = true\nconsole.log(JSON.stringify({show: ['customer','sales','amount','stageProgress','date'].map(f => o.lShown(f)),"
              " lo: ['date','customer','amount'].map(f => o.lo(f)), head: o.loHead(), foot: o.loFooter()}))", cols)
    assert r["show"] == [True, False, True, False, True]
    assert r["lo"] == ["order:3", "order:4", "order:5"] and r["head"] == "order:-1"
    assert r["foot"] == "order:3"                                           # 底部一列＝金額／進度／日期中最前面的（日期）


# ── 3. 版面：核心、發布、還原 ───────────────────────────────────────────────
def _h(client, make_user, name, role, modules=None):
    u, p = make_user(name, "Lay-Pass-123", role=role, modules=modules)[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _publish(client, h, ops, scope="company"):
    r = client.put(BASE + "/draft", headers=h, params={"scope": scope}, json={"body": {"ops": ops}})
    assert r.status_code == 200, r.text
    return client.post(BASE + "/publish", headers=h, params={"scope": scope}, json={"note": "t"})


def _eff(client, h):
    return client.get("/api/layout/case", headers=h).json()


@pytest.mark.parametrize("core", CORE)
def test_core_items_cannot_be_hidden(client, make_user, core):
    h = _h(client, make_user, "bp1c_boss1", "superadmin")
    r = _publish(client, h, [{"op": "hide", "target": COL + core}])
    assert r.status_code == 422, r.text
    assert client.get(BASE + "?scope=company", headers=h).json().get("latest") is None


def test_hide_reorder_publish_restore_and_default(client, make_user):
    boss = _h(client, make_user, "bp1c_boss2", "superadmin")
    ids = {p["id"] for p in _eff(client, boss)["points"]}
    assert all(COL + c in ids for c in CORE + NONCORE)
    v1 = [{"op": "hide", "target": COL + "stageProgress"}]
    v2 = [{"op": "relabel", "target": COL + "sales", "label": "負責業務"},
          {"op": "reorder", "target": LIST, "order": [COL + c for c in ("quoteNo", "dealTag", "date", "customer", "sales", "amount", "stageProgress")]}]
    assert _publish(client, boss, v1).status_code == 200
    assert _publish(client, boss, v2).status_code == 200
    assert _eff(client, boss)["ops"] == v2
    r = client.post("/api/definitions/layout/%s/restore/1" % KEY, headers=boss, params={"scope": "company"}, json={"note": "back"})
    assert r.status_code == 200, r.text
    assert _eff(client, boss)["ops"] == v1
    assert _publish(client, boss, []).status_code == 200                      # 還原到預設＝發布空操作
    assert _eff(client, boss)["ops"] == []


def test_non_superadmin_cannot_publish(client, make_user):
    admin = _h(client, make_user, "bp1c_admin3", "admin")
    r = client.put(BASE + "/draft", headers=admin, params={"scope": "company"}, json={"body": {"ops": []}})
    assert r.status_code in (401, 403)


# ── 4. 金額與權限：版面不改資料 ─────────────────────────────────────────────
def test_restricted_role_stays_masked_even_when_layout_shows_amount(client, make_user):
    """受限角色（工程師，被指派到案件但沒有財務檢視）的案件清單：金額為空、moneyMasked。
    發布一個『顯示並調到最前面的金額』版面後，API 回傳不變——版面只決定已收到的資料怎麼排，不能讓被遮蔽的欄位出現。"""
    import db
    from tests.platform import _response_keys as RK
    boss = _h(client, make_user, "bp1c_boss4", "superadmin")
    u, p = make_user("bp1c_eng4", "Lay-Pass-123", role="engineer")[:2]
    eng = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    conn = db.get_db()
    try:
        RK.seed_every_table(conn)
        uid = conn.execute("SELECT id FROM users WHERE username=?", ("bp1c_eng4",)).fetchone()[0]
        conn.execute("UPDATE quotations SET assigned_user_ids=?, total=12345", (str([uid]),))
        conn.commit()
    finally:
        conn.close()
    before = client.get("/api/quotations?limit=5", headers=eng).json()["items"]
    assert before and before[0]["total"] is None and before[0]["moneyMasked"] is True
    seen_by_boss = client.get("/api/quotations?limit=5", headers=boss).json()["items"][0]
    assert seen_by_boss["total"] == 12345                                    # 對照組：有權限的人看得到
    ops = [{"op": "show", "target": COL + "amount"}, {"op": "move", "target": COL + "amount", "index": 0}]
    assert _publish(client, boss, ops).status_code == 200
    assert client.get("/api/quotations?limit=5", headers=eng).json()["items"] == before
    # 頁面：金額的顯示仍由 moneyMasked 決定（版面綁定只管顯示與順序）
    assert "c.moneyMasked ? '—' : 'NT$ '" in _page()


# ── 5. 案件資訊表單（合約資訊、專案期間）──────────────────────────────────
FORM_FIELDS = {"contract": ("deliveryAddress", "deliveryTerms", "contactPerson", "contactPhone"), "timeline": ("startDate", "endDate")}
FORM_CORE = {"contactPerson", "contactPhone", "startDate"}              # 現場聯絡人與電話（個資告知相關）、開始日期不能隱藏


def test_form_registration_matches_page_bindings():
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    cz = m["customization"]
    pg = [p for p in cz["pages"] if p["page"] == "case-management.html"][0]
    assert {f["key"]: list(f["sections"][0]["fields"]) for f in pg["forms"]} == {k: list(v) for k, v in FORM_FIELDS.items()}
    core = {f["key"] for k in FORM_FIELDS for f in cz["fields"][k] if f["core"]}
    assert core == FORM_CORE
    src = _page()
    for form, fields in FORM_FIELDS.items():
        for f in fields:
            assert "fo('%s', '%s')" % (form, f) in src and "fLabel('%s', '%s'" % (form, f) in src, f
            if f not in FORM_CORE:
                assert "fShown('%s', '%s')" % (form, f) in src, f
        assert "secLabel('%s'" % form in src


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_form_bindings_are_neutral_when_flag_off():
    r = _node("console.log(JSON.stringify({show: o.fShown('contract', 'deliveryAddress'), fo: o.fo('contract', 'deliveryAddress'),"
              " label: o.fLabel('contract', 'deliveryAddress', '交貨 / 安裝地址'), sec: o.secLabel('contract', '合約資訊')}))")
    assert r == {"show": True, "fo": "", "label": "交貨 / 安裝地址", "sec": "合約資訊"}


_FORM_STORE = r"""
window.Alpine = { store() { return {
  cols() { return [] }, colLabel(l, f, d) { return d },
  fieldShown(form, f) { return f !== 'deliveryTerms' },
  fieldOrder(form, f) { return ({deliveryAddress: 4, deliveryTerms: 3, contactPerson: 1, contactPhone: 2})[f] || 0 },
  fieldLabel(form, f, d) { return f === 'contactPhone' ? '電話（現場）' : d },
  sections(form) { return [{ label: form === 'contract' ? '合約' : '期間' }] },
} }, $data() { return {} } }
"""


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_form_bindings_follow_the_layout_when_flag_on():
    js = _HARNESS % {"code": json.dumps(_part_source()), "cols": "[]",
                     "body": _FORM_STORE + "const o2 = Object.assign({}, window.CM_PARTS[0]()); o2.layoutOn = true\n"
                     "console.log(JSON.stringify({shown: ['deliveryAddress','deliveryTerms'].map(f => o2.fShown('contract', f)),"
                     " fo: ['contactPerson','contactPhone','deliveryAddress'].map(f => o2.fo('contract', f)),"
                     " label: o2.fLabel('contract', 'contactPhone', '聯絡電話'), keep: o2.fLabel('contract', 'contactPerson', '現場聯絡人'),"
                     " sec: o2.secLabel('contract', '合約資訊')}))"}
    r = _run_node(js)
    assert r == {"shown": [True, False], "fo": ["order:1", "order:2", "order:4"], "label": "電話（現場）", "keep": "現場聯絡人", "sec": "合約"}


@pytest.mark.parametrize("core", sorted(FORM_CORE))
def test_form_core_fields_cannot_be_hidden(client, make_user, core):
    h = _h(client, make_user, "bp1c_boss6" + core[:3], "superadmin")
    form = "timeline" if core == "startDate" else "contract"
    r = _publish(client, h, [{"op": "hide", "target": "case:case-management.html/form:%s/field:%s" % (form, core)}])
    assert r.status_code == 422, r.text


def test_form_noncore_field_can_be_hidden_and_renamed(client, make_user):
    h = _h(client, make_user, "bp1c_boss7", "superadmin")
    pts = {p["id"] for p in _eff(client, h)["points"]}
    t = "case:case-management.html/form:contract/field:deliveryTerms"
    assert t in pts, sorted(x for x in pts if "form:" in x)[:6]
    ops = [{"op": "hide", "target": t},
           {"op": "relabel", "target": "case:case-management.html/form:contract/field:deliveryAddress", "label": "施工地址"}]
    assert _publish(client, h, ops).status_code == 200
    assert _eff(client, h)["ops"] == ops
