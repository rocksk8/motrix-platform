# -*- coding: utf-8 -*-
"""治理契約 v1：對 def_pipeline.ACTIVE_KINDS 的每個種類參數化，走真 HTTP 驗證『跨種類都該成立』的治理性質。

草稿→發布→待核准→核准→套用／還原，兩位 superadmin（A 提交、B 核准）：
  P1 loosen_needs_approval   已發布 B；草稿 L（比 B 寬）發布 ⇒ 待核准，live 不變
  P2 tighten_is_direct       已發布 B；草稿 T（比 B 窄）發布 ⇒ 直接生效
  P3 restore_parity          B 已發布→T 直接發布→還原到 B（比 live 寬）⇒ 待核准，live 不變
  P4 neutral_is_direct       已發布 B；草稿 N（只差顯示字）發布 ⇒ 直接生效
  P5 impact_matches_diff     已發布 B＋草稿 L：impact.changeCount == len(D.diff(B, L))，且不 500
  P6 role_first_publish      公司層 B 已發布；role:sales 首發 L（比公司層寬）⇒ 待核准，且 D.resolve(role) 仍是公司層
  P7 approval_path           待核准的 L：提交者自己不能核准；第二位核准＋套用後 live 內容 == L
  S1 名單一致性（COMPARATORS／預覽名單／ROLE_AWARE）  S2 每個 ACTIVE kind 有種子  S3 寫入已發布狀態的入口只有已知 7 個
  S4 種子欄位完整（缺欄位必須列在 KNOWN_SEED_GAPS，不得悄悄略過）

『目前已知、尚未處理』的缺口一律寫成釘死的表（KNOWN_*）：新出現＝紅燈（要有人決定），修掉了也＝紅燈（要把表縮小）。
不是缺口、只是『這條性質不適用於該 kind』的，也要列表並附原因（KNOWN_P3_NOT_APPLICABLE），不得靠略過。

新增一個 ACTIVE kind 時：在 gov_contract_seeds/ 補一份種子（base 必填；loose／tight／neutral 能給就給），S2 會擋沒有種子的。
v2 backlog（不在本版）：list_pref_policy 的 kind 專屬對抗種子（global.default 與 overlay 交互作用）；
角色層首發直接生效的 4 個 kind（見 KNOWN_LATENT_ROLE_FIRST_PUBLISH）等該 kind 真的要做角色層支援時一併處理。
"""
import importlib
import json
import re
from pathlib import Path

import pytest

SEEDS_DIR = Path(__file__).resolve().parent / "gov_contract_seeds"

FLAG_GROUPS = ("builder_governance", "builder_layout", "builder_rules", "builder_menu", "builder_custom_fields", "builder_actions",
               "builder_slots", "builder_exports", "builder_option_lists", "builder_status_display", "builder_notify",
               "builder_stage_templates", "list_prefs")


def _load_seeds():
    out = []
    for f in sorted(SEEDS_DIR.glob("seeds_*.json")):
        out += json.loads(f.read_text(encoding="utf-8"))             # 讀不動就讓整支紅，不吞例外
    return out


SEEDS = _load_seeds()
REQUIRED = ("loose", "tight", "neutral")
_ids = ["%s[%s]" % (s["kind"], s["key"]) for s in SEEDS]


@pytest.fixture(scope="module", autouse=True)
def _restore_definition_registries(_app):
    """本檔會登記 kind（SETUP 的 import、G.kinds() 惰性登記，部分要開旗標才登記）；登記表是行程內全域狀態，
    收尾必須還原成進場時的樣子，否則後面假設『kind 未登記』的測試（例如 test_notify_actions_t63）會紅。
    用 module 範圍而不是每題還原：kind 的登記靠 import 副作用，import 只會跑一次，每題清掉後下一題就找不到 kind。
    依賴 _app：user_buttons／expense_types／remit_kinds 在 import 時就登記，要先讓 main 載完再拍快照，否則還原會把它們一併抹掉。"""
    from core import definitions as D
    from core import spine as SP
    snap = [(t, dict(t)) for t in (D._EXTRA_KINDS, D._VALIDATORS, D._DEFAULTS, SP._KIND_GATES)]      # noqa: SLF001
    # SP._KIND_GATES（核心 spine 的 kind 開關登記）也是行程內全域狀態：案例走到 ensure_kind() 會登記，沒還原就留給同 worker 的後續檔
    # （T84 汙染偵測器 tools/platform/pollution_detector.py 抓到的洩漏）。
    yield
    for t, saved in snap:
        t.clear()
        t.update(saved)


@pytest.fixture
def world(client, make_user, monkeypatch):
    from helpers import settings_registry as SR
    _orig = SR._defaults

    def _defs(group):
        out = _orig(group)
        if group in FLAG_GROUPS and "enabled" in out:
            out = dict(out, enabled=1)
        return out
    monkeypatch.setattr(SR, "_defaults", _defs)
    monkeypatch.setattr(SR, "confirm_period_days", lambda conn=None: 0)
    # 各 kind 惰性登記
    from routers import def_governance as G
    G.kinds()

    def login(name):
        u, pw = make_user(username=name, role="superadmin")[:2]
        return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}
    return {"c": client, "a": login("kp_admin_a"), "b": login("kp_admin_b")}


# 各 kind 的惰性登記：該模組 import 之後 kind 才存在（呼叫端是產品程式的 import 順序，這裡照做）
SETUP = {
    "rule_set": ("helpers.rule_sets", "ensure_registered"),
    "attachment_slot": ("helpers.attachment_slots", "enabled"),
    "export_template": ("modules.daily_tasks.api", None),
    "list_pref_policy": ("modules.supply.api.suppliers", None),
    "status_display": ("helpers.status_display", "ensure_registered"),
}


def _setup(seed):
    spec = SETUP.get(seed["kind"])
    if spec:
        mod = importlib.import_module(spec[0])
        if spec[1]:
            getattr(mod, spec[1])()


def _prep(world, seed):
    _setup(seed)
    from routers import def_governance as G
    G.kinds()
    from core import definitions as D
    assert seed["kind"] in D.kinds(), "kind 未登記：%s" % seed["kind"]


def _url(kind, key):
    return "/api/definitions/%s/%s" % (kind, key)


def _draft(w, kind, key, scope, body, who="a"):
    r = w["c"].put(_url(kind, key) + "/draft?scope=" + scope, json={"body": body}, headers=w[who])
    assert r.status_code == 200, ("存草稿失敗", r.status_code, r.text[:300])
    assert r.json().get("problems") in ([], None), ("草稿有問題", r.json().get("problems"))
    return r.json()


def _publish(w, kind, key, scope, body, who="a"):
    d = _draft(w, kind, key, scope, body, who)
    payload = {"note": "k", "base_etag": d.get("etag")}
    imp = w["c"].get("/api/def-governance/%s/%s/impact?scope=%s" % (kind, key, scope.replace(":", "%3A")), headers=w[who])     # 看過影響預覽（部分 kind 發布必帶 preview_hash）
    if imp.status_code == 200 and imp.json().get("previewHash"):
        payload["preview_hash"] = imp.json()["previewHash"]
    return w["c"].post(_url(kind, key) + "/publish?scope=" + scope, json=payload, headers=w[who])


def _is_pending(r):
    if r.status_code != 200:
        return None
    j = r.json()
    return bool(j.get("pending") or j.get("status") == "submitted")


def _live(kind, key, scope="company"):
    from core import definitions as D
    from db import get_db
    conn = get_db()
    try:
        return D.get(conn, kind, key, scope)
    finally:
        conn.close()


def _pending_ids(w, kind, key, scope):
    r = w["c"].get("/api/def-pipeline/pending", headers=w["a"])
    assert r.status_code == 200, r.text[:200]
    return [i for i in r.json()["items"] if i["kind"] == kind and i["key"] == key and i["scope"] == scope]


def _approve_and_activate(w, kind, key, scope, submitter="a", approver="b"):
    items = _pending_ids(w, kind, key, scope)
    assert items, "沒有待核准項"
    cid = items[-1]["id"]
    r1 = w["c"].post("/api/def-pipeline/changes/%d/approve" % cid, json={"reason": "k"}, headers=w[approver])
    assert r1.status_code == 200, ("核准失敗", r1.status_code, r1.text[:200])
    r2 = w["c"].post("/api/def-pipeline/changes/%d/activate" % cid, json={}, headers=w[approver])
    assert r2.status_code == 200, ("套用失敗", r2.status_code, r2.text[:300])
    return r2.json()


def _establish(w, seed, scope="company"):
    """讓 base 在 scope 成為 live（首發若被判放寬就走第二位核准＋套用）。⇒ (首發是否待核准, live 列)"""
    kind, key = seed["kind"], seed["key"]
    r = _publish(w, kind, key, scope, seed["base"])
    assert r.status_code == 200, ("首發失敗", r.status_code, r.text[:300])
    pend = _is_pending(r)
    if pend:
        _approve_and_activate(w, kind, key, scope)
    live = _live(kind, key, scope)
    assert live and live["body"] == seed["base"], ("establish 後 live 不等於 base", live and live.get("body"))
    return pend, live


def _same(a, b):
    return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)


# 種子缺的欄位（該 kind 在那個方向做不出合法內容）：釘死；多缺或補上都紅，不得悄悄少跑
KNOWN_SEED_GAPS = {("status_display", "tight")}


def _has(*names):
    return [(s, i) for s, i in zip(SEEDS, _ids) if all(s.get(n) for n in names)]


def _P(*names):
    xs = _has(*names)
    return pytest.mark.parametrize("seed", [x[0] for x in xs], ids=[x[1] for x in xs])


@_P("loose")
def test_p1_loosen_needs_approval(world, seed):
    def f():
        _prep(world, seed)
        pend0, live0 = _establish(world, seed)
        r = _publish(world, seed["kind"], seed["key"], "company", seed["loose"])
        assert r.status_code == 200, (r.status_code, r.text[:300])
        assert _is_pending(r), ("放寬內容被直接發布了", r.json())
        live = _live(seed["kind"], seed["key"])
        assert _same(live["body"], seed["base"]) and live["version"] == live0["version"], "待核准時 live 被動到"
        return "first_publish_pending=%s" % pend0
    f()


@_P("tight")
def test_p2_tighten_is_direct(world, seed):
    def f():
        _prep(world, seed)
        _establish(world, seed)
        r = _publish(world, seed["kind"], seed["key"], "company", seed["tight"])
        assert r.status_code == 200, (r.status_code, r.text[:300])
        assert _is_pending(r) is False, ("收緊被送審", r.json())
        assert _same(_live(seed["kind"], seed["key"])["body"], seed["tight"]), "收緊沒有生效"
    f()


@_P("neutral")
def test_p4_neutral_is_direct(world, seed):
    def f():
        _prep(world, seed)
        _establish(world, seed)
        r = _publish(world, seed["kind"], seed["key"], "company", seed["neutral"])
        assert r.status_code == 200, (r.status_code, r.text[:300])
        assert _is_pending(r) is False, ("中性變更被送審", r.json())
    f()


def _restore(w, kind, key, scope, version, who="a"):
    imp = w["c"].get("/api/def-governance/%s/%s/impact?scope=%s&version=%d" % (kind, key, scope.replace(":", "%3A"), version), headers=w[who])
    payload = {"note": "k"}
    if imp.status_code == 200 and imp.json().get("previewHash"):
        payload["preview_hash"] = imp.json()["previewHash"]
    return w["c"].post(_url(kind, key) + "/restore/%d?scope=%s" % (version, scope), json=payload, headers=w[who])


# P3 不適用的 kind：從『收緊版』回到『基準版』在該 kind 的 comparator 下不算放寬，所以還原本來就可直接生效。
# 這不是缺口；表釘死，避免 comparator 改了而沒人發現。
# （option_list 曾在這裡：重新啟用判為中性。使用者 2026-11-08 裁示重新啟用＝放寬、要二次核准，已移出——現在 P3 對它也成立。）
KNOWN_P3_NOT_APPLICABLE = {}


@_P("tight")
def test_p3_restore_parity(world, seed):
    def f():
        _prep(world, seed)
        from routers.def_pipeline import classify
        cls = classify(seed["kind"], seed["tight"], seed["base"])[0]
        na = seed["kind"] in KNOWN_P3_NOT_APPLICABLE
        assert (cls != "loosen") == na, ("P3 適用性表與 comparator 不符（表要跟著改）", seed["kind"], cls, "表內" if na else "表外")
        if na:
            pytest.skip("%s：comparator 認為 tight→base 是 %s，不是放寬；還原不會送審——%s" % (seed["kind"], cls, KNOWN_P3_NOT_APPLICABLE[seed["kind"]]))
        _, live0 = _establish(world, seed)
        r = _publish(world, seed["kind"], seed["key"], "company", seed["tight"])
        assert r.status_code == 200 and _is_pending(r) is False, ("前置：收緊應直接生效", r.status_code, r.text[:200])
        rr = _restore(world, seed["kind"], seed["key"], "company", live0["version"])
        assert rr.status_code == 200, ("還原失敗", rr.status_code, rr.text[:300])
        assert _is_pending(rr), ("還原到較寬的版本被直接生效", rr.json())
        assert _same(_live(seed["kind"], seed["key"])["body"], seed["tight"]), "還原待核准時 live 被動到"
    f()


# P8／P9：預覽名單不是裝飾——名單內的 kind，發布／還原不帶『看過的』預覽雜湊 ⇒ 409 preview_required（旗標開）；帶了才放行。
# 『名單內』以行為判斷（走 HTTP 的結果），名單本身是否齊全由 S1 守。選用強制名單（_OPT_IN_PREVIEW_KINDS）預設不強制，兩個方向都釘住。
def _enforced_kinds():
    from routers import definitions as R
    return set(R._PREVIEW_ENFORCED_KINDS)


@_P("base")
def test_p8_publish_requires_seen_preview_when_enforced(world, seed):
    def f():
        _prep(world, seed)
        from routers import definitions as R
        kind, key = seed["kind"], seed["key"]
        d = _draft(world, kind, key, "company", seed["base"])
        bare = world["c"].post(_url(kind, key) + "/publish?scope=company", json={"note": "k", "base_etag": d.get("etag")}, headers=world["a"])
        if kind in _enforced_kinds():
            assert bare.status_code == 409 and (bare.json().get("code") == "preview_required"), (
                "名單內的 kind 不帶預覽雜湊也能發布（伺服端沒強制）", kind, bare.status_code, bare.text[:200])
            stale = world["c"].post(_url(kind, key) + "/publish?scope=company", json={"note": "k", "preview_hash": "not-the-draft-stamp"}, headers=world["a"])
            assert stale.status_code == 409 and stale.json().get("code") == "preview_stale", (kind, stale.status_code, stale.text[:200])
            ok = _publish(world, kind, key, "company", seed["base"])                       # 帶『看過』的雜湊 ⇒ 放行
            assert ok.status_code == 200, ("看過預覽後應能發布", kind, ok.status_code, ok.text[:300])
        else:
            assert kind in R._OPT_IN_PREVIEW_KINDS, ("既不在強制名單、也不在選用名單（S1 應該已經紅）", kind)
            if kind == "rule_set":      # 規則功能開著（本檔把 builder_rules.enabled 打開）就一律要先預覽——見 definitions._preview_enforced
                assert bare.status_code == 409 and bare.json().get("code") == "preview_required", (kind, bare.status_code, bare.text[:200])
            else:
                assert bare.status_code == 200, ("選用強制預設不強制：不帶雜湊應照常發布", kind, bare.status_code, bare.text[:200])
    f()


@_P("base")
def test_p9_restore_requires_seen_preview_when_enforced(world, seed):
    def f():
        _prep(world, seed)
        kind, key = seed["kind"], seed["key"]
        if kind not in _enforced_kinds():
            pytest.skip("%s 不在強制名單（選用強制，預設不強制）" % kind)
        alt = next((seed[n] for n in ("tight", "neutral", "loose") if seed.get(n)), None)      # 任何一份與 base 不同的內容就夠（要有第二個版本可還原）
        assert alt is not None, "種子沒有任何與 base 不同的內容"
        _, live0 = _establish(world, seed)
        r = _publish(world, kind, key, "company", alt)
        if r.status_code != 200 or _is_pending(r):
            if _is_pending(r):
                _approve_and_activate(world, kind, key, "company")
            else:
                pytest.fail(("前置：第二版發布失敗", r.status_code, r.text[:200]))
        bare = world["c"].post(_url(kind, key) + "/restore/%d?scope=company" % live0["version"], json={"note": "k"}, headers=world["a"])
        assert bare.status_code == 409 and bare.json().get("code") == "preview_required", (
            "名單內的 kind 不帶預覽雜湊也能還原", kind, bare.status_code, bare.text[:200])
        rr = _restore(world, kind, key, "company", live0["version"])                       # 帶『看過這一版』的雜湊 ⇒ 不再被預覽把關擋
        assert rr.status_code == 200, ("看過預覽後還原應被受理（生效或待核准）", kind, rr.status_code, rr.text[:300])
    f()


# P9b：P9 只驗伺服端；編輯器（前端）自己的還原有沒有帶預覽雜湊，以前沒人盯（export-editor／option-list-editor 就送 {}，旗標開時 409）。
# 靜態守門：凡是 frontend 裡呼叫 `/restore/` 的檔，如果它處理的 kind 有任何一個在強制名單內，這個呼叫所在的函式（從最近的函式宣告行到呼叫後 3 行）
# 必須出現 preview_hash／previewRestore。不夠細（只看文字、不跑瀏覽器），所以每個編輯器另有 node 假 fetch 的行為題；這題是『新編輯器忘了』的網。
# ⚠️ 不能用固定行數視窗：同一個檔的發布函式就在還原函式上面、也有 preview_hash，視窗會被它蓋住（第一版就這樣漏掉 export-editor）。
_RESTORE_CALL = re.compile(r"/restore/")
_HASH_TOKENS = ("preview_hash", "previewRestore")
_FUNC_START = re.compile(
    r"\bfunction\b"                                                                   # function doRestore(v) {
    r"|^\s*(?:async\s+)?[A-Za-z_$][\w$]*\s*\([^)]*\)\s*\{\s*$"                  # 物件方法縮寫  async doRestore(v) {
    r"|^\s*[A-Za-z_$][\w$]*\s*:\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"            # 屬性形箭頭  doRestore: async (v) =>
    r"|^\s*(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=" r"\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>")  # 賦值箭頭  const doRestore = async (v) =>
NL = chr(10)
_DYNAMIC_DEFS = re.compile(r"""['"]/api/definitions/['"]\s*\+""")                       # 泛用 helper：'/api/definitions/' + kind + …（檔裡沒有任何 kind 字面）


def _strip_comments(text: str) -> str:
    """去掉 /* */ 與行首／空白後的 // 註解（保留換行，行號不變）；註解裡寫 `// TODO: add preview_hash` 不能讓檢查放行。
    ⚠️ 不處理字串裡的 `//`（網址前面不是空白，不會被當註解）；HTML 內嵌 <script> 不在掃描範圍（目前沒有還原呼叫在 html）。"""
    text = re.sub(r"/\*.*?\*/", lambda m: NL * m.group(0).count(NL), text, flags=re.S)
    return re.sub(r"(^|\s)//.*$", r"\1", text, flags=re.M)


def _restore_sites_without_hash(files: dict, enforced: set) -> list:
    """files＝{路徑: 內容}；⇒ [(路徑, 行號)]：呼叫 /restore/、（可能）處理強制名單內的 kind、所在函式裡卻沒有預覽雜湊字樣。
    範圍＝檔裡有強制 kind 的字面，或用動態拼接 '/api/definitions/' + … 的泛用 helper。/restore/ 字面只會出現在還原呼叫與註解（註解已剝掉），所以不再要求附近有 POST。"""
    bad = []
    for path, raw in sorted(files.items()):
        text = _strip_comments(raw)
        if not (any(("'%s'" % k) in text or ('"%s"' % k) in text or ("definitions/%s/" % k) in text for k in enforced) or _DYNAMIC_DEFS.search(text)):
            continue                                            # 這個檔不碰任何強制名單內的 kind（例如 layout／custom_fields：選用強制）
        lines = text.splitlines()
        for i, ln in enumerate(lines):
            if _RESTORE_CALL.search(ln):
                j = next((k for k in range(i, -1, -1) if _FUNC_START.search(lines[k])), 0)      # 這個呼叫所在函式的宣告行
                near = NL.join(lines[j:i + 4])
                if not any(tok in near for tok in _HASH_TOKENS):
                    bad.append((path, i + 1))
    return bad


def _frontend_js():
    """全部前端 JS（frontend/** ∪ 模組自有 backend/modules/<key>/js/**）：一律走共用列舉，JS 搬進模組後才不會安靜漏掃（test_no_direct_js_enumeration）。"""
    from tests import _frontend_sources as FS
    return {FS.js_rel(p): p.read_text(encoding="utf-8", errors="replace") for p in FS.all_js()}


def test_p9b_editor_restore_calls_carry_a_preview_hash():
    files = _frontend_js()
    assert len(files) > 30 and any(("/restore/" in t) for t in files.values()), "沒掃到前端檔／沒有任何還原呼叫——這題什麼都沒驗"      # 正對照
    bad = _restore_sites_without_hash(files, _enforced_kinds())
    assert not bad, ("這些前端還原呼叫在強制預覽名單內的 kind 上沒帶 preview_hash（旗標開時會 409 preview_required）：", bad)


def test_p9b_scanner_positive_control():
    """掃描器本身要抓得到、也不亂抓：沒雜湊＝抓；有雜湊／previewRestore＝不抓；不碰強制 kind 的檔＝不抓。"""
    enforced = {"export_template", "option_list"}
    no_hash = NL.join(["function doRestore(v) {", "  return api('POST', '/api/definitions/export_template/x/restore/' + v, {})", "}"])
    with_hash = NL.join(["function doRestore(v) {", "  var rb = { preview_hash: h }",
                         "  return api('POST', '/api/definitions/export_template/x/restore/' + v, rb)", "}"])
    via_panel = NL.join(["async function r(v) {", "  var h = await G.previewRestore(o, v)",
                         "  return api('POST', '/api/definitions/option_list/x/restore/' + v, {})", "}"])
    other_kind = NL.join(["function doRestore(v) {", "  return api('POST', '/api/definitions/layout/x/restore/' + v, {})", "}"])
    got = _restore_sites_without_hash({"a.js": no_hash, "b.js": with_hash, "c.js": via_panel, "d.js": other_kind}, enforced)
    assert got == [("a.js", 2)], got
    # 反向控制（第一版的漏洞）：同檔裡『上面』的發布函式有 preview_hash，不能蓋住下面沒帶的還原函式
    sibling = NL.join(["function doPublish() {", "  body.preview_hash = h", "}", "function doRestore(v) {",
                       "  return api('POST', '/api/definitions/export_template/x/restore/' + v, {})", "}"])
    assert _restore_sites_without_hash({"e.js": sibling}, enforced) == [("e.js", 5)]
    # K 審 hichan-2 的三個探針（各一行 case）：
    arrow = NL.join(["function doPublish() {", "  body.preview_hash = h", "}",
                     "const doRestore = async (v) => {", "  return api('POST', '/api/definitions/export_template/x/restore/' + v, {})", "}"])
    assert _restore_sites_without_hash({"f.js": arrow}, enforced) == [("f.js", 5)], "賦值箭頭函式不能被上一個函式蓋住"
    fetch_multi = NL.join(["async function doRestore(v) {", "  return fetch('/api/definitions/option_list/x/restore/' + v,", "    { method: 'POST', body: '{}' })", "}"])
    assert _restore_sites_without_hash({"g.js": fetch_multi}, enforced) == [("g.js", 2)], "POST 在後面幾行的 fetch 不能漏"
    generic = NL.join(["async function restore(o, v) {", "  return call('POST', '/api/definitions/' + o.kind + '/' + o.key + '/restore/' + v, {})", "}"])
    assert _restore_sites_without_hash({"h.js": generic}, enforced) == [("h.js", 2)], "泛用 helper（動態拼 kind、檔裡沒有 kind 字面）也在範圍內"
    commented = NL.join(["function doRestore(v) {", "  // TODO: add preview_hash", "  return api('POST', '/api/definitions/export_template/x/restore/' + v, {})", "}"])
    assert _restore_sites_without_hash({"i.js": commented}, enforced) == [("i.js", 3)], "註解裡的 preview_hash 不算"
    ok_arrow = NL.join(["const doRestore = async (v) => {", "  var rb = { preview_hash: h }", "  return api('POST', '/api/definitions/export_template/x/restore/' + v, rb)", "}"])
    assert _restore_sites_without_hash({"j.js": ok_arrow}, enforced) == [], "有雜湊的箭頭函式不該誤報"


@_P("loose")
def test_p5_impact_matches_diff(world, seed):
    def f():
        _prep(world, seed)
        _establish(world, seed)
        _draft(world, seed["kind"], seed["key"], "company", seed["loose"])
        r = world["c"].get("/api/def-governance/%s/%s/impact?scope=company" % (seed["kind"], seed["key"]), headers=world["a"])
        assert r.status_code == 200, ("impact 失敗", r.status_code, r.text[:300])
        from core import definitions as D
        want = len(D.diff(seed["base"], seed["loose"]))
        assert r.json()["changeCount"] == want, ("impact 的差異數與 D.diff 不同", r.json()["changeCount"], want)
    f()


# 判準獨立於被測的名單：執行期真的依角色讀不同層的 kind＝D.resolve(..., role) 的呼叫端（core/catalog.py 的 layout、list_pref_policy.policy_for）。
# S1 另外檢查它與 def_governance.ROLE_AWARE_KINDS 一致。
RUNTIME_ROLE_READERS = ("layout", "list_pref_policy")
# option_list：2026-11-08 補上合法 loose 種子後才被 P6 掃到；執行期只讀 company 層，角色層首發目前無實際效果（同上，做角色層支援時一併處理）。
KNOWN_LATENT_ROLE_FIRST_PUBLISH = {"rule_set", "attachment_slot", "case_stage_template", "option_list"}


@_P("loose")
def test_p6_role_first_publish(world, seed):
    def f():
        _prep(world, seed)
        _establish(world, seed)
        r = _publish(world, seed["kind"], seed["key"], "role:sales", seed["loose"])
        if r.status_code != 200:
            # 執行期讀角色層的 kind 一定要收角色層首發；被拒＝無法驗證，不能當通過
            assert seed["kind"] not in RUNTIME_ROLE_READERS, ("執行期讀角色層的 kind 卻拒收角色層首發", r.status_code, r.text[:200])
            return "role scope rejected %s %s" % (r.status_code, r.text[:120])          # 其他 kind 不收角色層：不算缺陷
        direct = not _is_pending(r)
        if seed["kind"] in RUNTIME_ROLE_READERS:
            assert not direct, ("角色層首發比公司層寬卻直接生效", r.json())      # 執行期真的讀角色層：這是繞過第二位核准
        else:
            # 執行期不讀角色層：目前無實際效果，已知 4 個直接生效（backlog：做角色層支援時一併處理）。表釘死兩個方向。
            assert direct == (seed["kind"] in KNOWN_LATENT_ROLE_FIRST_PUBLISH), (
                "角色層首發行為與 KNOWN_LATENT_ROLE_FIRST_PUBLISH 不符（新增＝新缺口；變成待核准＝表可以縮小）", seed["kind"], direct)
            if direct:
                return "LATENT（已知）"
        from core import definitions as D
        from db import get_db
        conn = get_db()
        try:
            body, src = D.resolve(conn, seed["kind"], seed["key"], "sales")
        finally:
            conn.close()
        assert _same(body, seed["base"]), ("待核准的角色層已經被 resolve 讀到", src)
    f()


@_P("loose")
def test_p7_approval_path(world, seed):
    def f():
        _prep(world, seed)
        _, live0 = _establish(world, seed)
        r = _publish(world, seed["kind"], seed["key"], "company", seed["loose"])
        assert _is_pending(r), "前置：放寬應待核准"
        items = _pending_ids(world, seed["kind"], seed["key"], "company")
        cid = items[-1]["id"]
        r0 = world["c"].post("/api/def-pipeline/changes/%d/approve" % cid, json={"reason": "self"}, headers=world["a"])
        assert r0.status_code == 409, ("提交者自己核准應被擋（409），不是別的錯誤", r0.status_code, r0.text[:200])
        assert [i["id"] for i in _pending_ids(world, seed["kind"], seed["key"], "company")] == [cid], "自核准被擋後，待核准項應原樣還在"
        assert _same(_live(seed["kind"], seed["key"])["body"], seed["base"]), "自核准被擋後 live 被動到"
        _approve_and_activate(world, seed["kind"], seed["key"], "company")
        live = _live(seed["kind"], seed["key"])
        assert _same(live["body"], seed["loose"]) and live["version"] > live0["version"], "核准套用後 live 不等於送審內容"
    f()


# ── 靜態／結構性質（不走 HTTP）─────────────────────────────────────────────
# 每個 ACTIVE kind 都必須在兩份預覽名單之一（T79 補齊：原本 attachment_slot／case_stage_template／list_pref_policy／notify_template／status_display
# 五個 kind 不在任何名單，繞過編輯器直接打 API 可以不看預覽就發布）。新 kind 沒進名單＝紅（要決定進哪份）。沒有「已知缺口」表了。


def test_s1_kind_lists_are_consistent(world):
    """名單一致性：COMPARATORS 的鍵＝ACTIVE_KINDS；每個 ACTIVE kind 都在兩份預覽名單之一（已知缺口除外）；
    ROLE_AWARE_KINDS ⊆ ACTIVE_KINDS 且等於本檔獨立列的『執行期讀角色層』名單。"""
    from routers import def_pipeline as P, def_governance as G, definitions as R
    act, cmp_, pe, oi, ra = set(P.ACTIVE_KINDS), set(P.COMPARATORS), set(R._PREVIEW_ENFORCED_KINDS), set(R._OPT_IN_PREVIEW_KINDS), set(G.ROLE_AWARE_KINDS)
    problems = []
    if act != cmp_:
        problems.append(("ACTIVE != COMPARATORS", sorted(act ^ cmp_)))
    miss = {k for k in act if k not in pe and k not in oi}
    if miss:
        problems.append(("這些 ACTIVE kind 不在任何預覽名單（發布不需要先看預覽）：加進 definitions._PREVIEW_ENFORCED_KINDS 或 _OPT_IN_PREVIEW_KINDS", sorted(miss)))
    if not ra <= act:
        problems.append(("ROLE_AWARE 不在 ACTIVE", sorted(ra - act)))
    if ra != set(RUNTIME_ROLE_READERS):
        problems.append(("ROLE_AWARE_KINDS 與執行期讀角色層的 kind 不同", sorted(ra ^ set(RUNTIME_ROLE_READERS))))
    both = sorted(pe & oi)
    if both:
        problems.append(("同時在兩份預覽名單", both))
    assert not problems, problems


def test_s2_every_active_kind_has_a_seed():
    from routers import def_pipeline as P
    have = {s["kind"] for s in SEEDS}
    missing = sorted(set(P.ACTIVE_KINDS) - have)
    assert not missing, ("沒有種子的 kind（在 gov_contract_seeds/ 補一份）", missing)
    extra = sorted(have - set(P.ACTIVE_KINDS))
    assert not extra, ("種子的 kind 不在 ACTIVE_KINDS", extra)


def test_s4_seed_fields_complete_or_listed():
    """種子缺 loose／tight／neutral 時，對應性質會少跑；缺口必須列在 KNOWN_SEED_GAPS，不得悄悄略過。"""
    assert all(s.get("base") for s in SEEDS), "種子缺 base"
    gaps = {(s["kind"], f) for s in SEEDS for f in REQUIRED if not s.get(f)}
    assert gaps == KNOWN_SEED_GAPS, ("種子缺欄位與 KNOWN_SEED_GAPS 不符", sorted(gaps ^ KNOWN_SEED_GAPS))


_WRITE_FUNCS = ("publish", "restore", "decide_submitted", "publish_direct")


def _write_entrances_in(source, rel):
    """一份原始碼裡把定義寫成『已發布』的呼叫點：<別名>.publish(...) 與 `from core.definitions import publish [as x]` 後的 x(...)。
    別名名單＝D／definitions／_D 加上檔內 `from core import definitions as X`／`import core.definitions as X` 取得的名字。"""
    import ast
    t = ast.parse(source)
    mods, funcs = {"D", "definitions", "_D"}, {}
    for n in ast.walk(t):
        if isinstance(n, ast.ImportFrom) and n.module == "core":
            mods |= {a.asname or a.name for a in n.names if a.name == "definitions"}
        elif isinstance(n, ast.ImportFrom) and n.module == "core.definitions":
            funcs.update({a.asname or a.name: a.name for a in n.names if a.name in _WRITE_FUNCS})
        elif isinstance(n, ast.Import):
            mods |= {a.asname for a in n.names if a.name == "core.definitions" and a.asname}
    found = []
    for n in ast.walk(t):
        if not isinstance(n, ast.Call):
            continue
        if isinstance(n.func, ast.Attribute) and n.func.attr in _WRITE_FUNCS and isinstance(n.func.value, ast.Name) and n.func.value.id in mods:
            found.append("%s:%s" % (rel, n.func.attr))
        elif isinstance(n.func, ast.Name) and n.func.id in funcs:
            found.append("%s:%s" % (rel, funcs[n.func.id]))
    return found


def test_s3_scanner_positive_control():
    """掃描器本身要抓得到：換別名、直接 import 函式都不能漏；不相干的 publish 不能誤報。"""
    src = ("from core import definitions as defs\n"
           "from core.definitions import restore as rs\n"
           "import core.definitions as cd\n"
           "defs.publish(1)\nrs(2)\ncd.decide_submitted(3)\nother.publish(4)\ndefs.get(5)\n")
    assert sorted(_write_entrances_in(src, "x.py")) == ["x.py:decide_submitted", "x.py:publish", "x.py:restore"]


def test_s3_write_entrances_are_the_known_ones():
    """誰能把定義寫成『已發布』：D.publish／D.restore／D.decide_submitted／D.publish_direct 的呼叫點（AST，排除 tests）。
    新增呼叫點＝新的寫入口，要有人看過（並確認走治理管線）。"""
    root = Path(__file__).resolve().parents[2]                          # backend/
    found = []
    for p in root.rglob("*.py"):
        rel = p.relative_to(root).as_posix()
        if rel.startswith(("tests/", "tools/", "migrations_frozen/")) or "/tests/" in rel or rel.endswith("conftest.py"):
            continue
        try:
            found += _write_entrances_in(p.read_text(encoding="utf-8"), rel)
        except SyntaxError:
            continue
    got = sorted(set(found))
    want = sorted({"helpers/custom_def_review.py:publish", "helpers/custom_def_review.py:decide_submitted", "routers/definitions.py:publish",
                   "routers/definitions.py:restore", "routers/def_pipeline.py:publish", "routers/def_pipeline.py:decide_submitted",
                   "helpers/settings_registry.py:publish_direct"})
    assert got == want, {"extra": sorted(set(got) - set(want)), "missing": sorted(set(want) - set(got))}
