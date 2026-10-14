# -*- coding: utf-8 -*-
"""S-X2 狀態顯示名稱與顏色（旗標 builder_status_display.enabled 預設關）。純函式／node 題可用 --noconftest 單跑。
- 預設表＝今天：色調與 static/status-chip.js 的 MAP 逐鍵相同（用 node 實際讀 JS），情境簡稱＝報價單列表既有的 審核中／已退回／執行中／待決定
- 驗證器：鍵由程式擁有（未知鍵、改鍵一律拒絕）；色調限調色盤；非核准語意不可用官方用語（預設值除外）；核准／付款語意只能用對應色調；未知欄位拒絕
- 比較器：核准／付款類改名改色＝放寬，其餘＝中性；看不懂＝放寬；突變正對照
- changed_fields：只列與預設不同的欄位
- JS：旗標關／未載入 ⇒ label 原值、chipClass 同 MAP；載入後只有『被改過的欄位』覆寫畫面原本的字與色（badgeClass／label 的 fallback）
- 需要資料庫的題（寫好未跑）：端點旗標關回 {enabled:false}；開啟＋發布後回表；核准類改名走待核准"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from helpers import status_display as S

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT.parent / "frontend"
NODE = shutil.which("node")


def node(code):
    out = subprocess.run([NODE, "-e", code], capture_output=True, text=True, encoding="utf-8", cwd=str(FRONT))
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# ── 預設表＝今天 ───────────────────────────────────────────────────────────────
@pytest.mark.skipif(not NODE, reason="需要 node")
def test_default_tones_equal_the_status_chip_map():
    js = node("const S=require('./static/status-chip.js');console.log(JSON.stringify(S.MAP))")
    d = S.defaults()
    for k, t in js.items():
        assert k in d and d[k]["tone"] == t, k                          # JS 表裡的每個鍵 Python 這邊都有、色調相同
    for k in S.STATUS_KEYS:
        if k in S.defaults() and S._GROUP[k] == "approval":
            assert js.get(k) == d[k]["tone"], k                          # approval 群組的鍵 JS 也都有


def test_default_context_names_are_todays_strings():
    d = S.defaults()
    assert d["待審核"]["names"]["quote_list"] == "審核中" and d["已拒絕"]["names"]["quote_list"] == "已退回"
    assert d["已成案"]["names"]["quote_list"] == "執行中" and d["已提供"]["names"]["quote_list"] == "待決定"
    assert d["已核准"]["label"] == "已核准" and d["草稿"]["label"] == "草稿" and S.changed_fields(d) == {}


def test_keys_are_code_owned_and_unique():
    assert len(set(S.STATUS_KEYS)) == len(S.STATUS_KEYS) and "已核准" in S.STATUS_KEYS and "已成案" in S.STATUS_KEYS


# ── 驗證器 ─────────────────────────────────────────────────────────────────────
def v(statuses):
    return S.validate_table({"statuses": statuses})


def test_valid_examples():
    assert S.validate_table({}) == [] and v({}) == []
    assert v({"草稿": {"label": "起草中", "tone": "pending", "order": 5, "names": {"case": "起草"}}}) == []
    assert v({"待核准": {}}) == []                                          # 預設標籤含『核准』也合格（預設值除外）


@pytest.mark.parametrize("bad", [
    {"不存在": {"label": "x"}}, {"草稿": {"label": ""}}, {"草稿": {"label": " 前後空白 "}}, {"草稿": {"label": "字" * 13}},
    {"草稿": {"tone": "hotpink"}}, {"草稿": {"tone": "#ff0000"}}, {"草稿": {"order": -1}}, {"草稿": {"order": 1000}}, {"草稿": {"order": True}},
    {"草稿": {"extra": 1}}, {"草稿": {"names": {"nowhere": "x"}}}, {"草稿": {"names": {"case": ""}}}, {"草稿": "x"},
])
def test_invalid_entries_are_rejected(bad):
    assert v(bad)


def test_top_level_shape_and_key():
    for body in (None, [], "x", {"statuses": []}, {"statuses": {}, "hooks": 1}):
        assert S.validate_table(body)
    assert S.validate_table({"statuses": {}}, "other")


@pytest.mark.parametrize("word", ["已核准", "核准中", "批准", "核可", "已簽核", "簽核完成", "審核通過"])
def test_official_words_are_banned_on_non_approved_keys(word):
    assert any("官方用語" in p["message"] for p in v({"待審核": {"label": word}}))
    assert any("官方用語" in p["message"] for p in v({"草稿": {"names": {"case": word}}}))


def test_approved_and_paid_tone_rules():
    assert any("色調" in p["message"] for p in v({"草稿": {"tone": "approved"}}))              # 一般狀態不能裝成『已核准』綠
    assert any("色調" in p["message"] for p in v({"待審核": {"tone": "paid"}}))
    assert v({"已核准": {"tone": "rejected"}})                                                   # 已核准不能改成紅
    assert v({"已核准": {"tone": "approved"}}) == []
    assert v({"已付款": {"tone": "approved"}}) == [] and v({"已付款": {"tone": "void"}})
    assert v({"finalized": {"tone": "approved"}}) == []                                         # 預設就是 approved 的 plain 鍵：維持預設可以


def test_validator_never_raises():
    class Evil:
        def __getitem__(self, k):
            raise RuntimeError

    assert isinstance(S.validate_table(Evil()), list)


# ── 比較器 ─────────────────────────────────────────────────────────────────────
def c(old, new):
    return S.compare({"statuses": old}, {"statuses": new})[0]


def test_compare_directions():
    assert c({}, {}) == "neutral"
    assert c({}, {"草稿": {"label": "起草"}}) == "neutral"
    assert c({}, {"待審核": {"names": {"quote_list": "等待中"}}}) == "neutral"
    assert c({}, {"已核准": {"label": "已確認"}}) == "loosen"                   # 核准語意改名
    assert c({}, {"已付款": {"label": "已結清"}}) == "loosen"                   # 付款語意改名
    assert c({"已核准": {"label": "已確認"}}, {}) == "loosen"                   # 還原回預設也是變動（保守）
    assert S.compare(None, {"statuses": {}})[0] == "loosen" and S.compare({"statuses": {"x": {}}}, {})[0] == "loosen"
    assert S.compare({}, {"statuses": {"已核准": {"label": "已確認"}}})[1]


def test_compare_mutation_control(monkeypatch):
    assert c({}, {"已核准": {"label": "放行"}}) == "loosen"
    monkeypatch.setitem(S._SEMANTIC, "已核准", "plain")                           # 把語意拿掉 ⇒ 結果翻面，證明比較器真的看語意
    monkeypatch.setitem(S._TONE0, "已核准", "neutral")                            # （語意改成一般後預設色調也要跟著不是綠，否則驗證器先擋）
    assert c({}, {"已核准": {"label": "放行"}}) == "neutral"


def test_changed_fields_lists_only_differences():
    t = S.effective_table({"statuses": {"草稿": {"label": "起草", "tone": "pending"}, "待審核": {"names": {"quote_list": "等待中", "case": "待審"}}}})
    ch = S.changed_fields(t)
    assert ch == {"草稿": ["label", "tone"], "待審核": ["names.case", "names.quote_list"]}


def test_effective_table_ignores_garbage_and_keeps_all_keys():
    t = S.effective_table({"statuses": {"草稿": {"tone": "nope", "label": 5, "order": True}, "不存在": {"label": "x"}}})
    assert set(t) == set(S.STATUS_KEYS) and t["草稿"] == S.defaults()["草稿"]


def test_public_payload_off_is_minimal(monkeypatch):
    assert S.public_payload() == {"enabled": False}
    monkeypatch.setattr(S, "enabled", lambda conn=None: False)
    assert S.public_payload(object()) == {"enabled": False}


def test_flag_group_is_registered_with_the_off_default():
    from helpers import settings_registry as SR
    import helpers.settings_groups  # noqa: F401
    assert SR.get("builder_status_display", "enabled") == 0 and S.flag_on() is False and S.enabled() is False


def test_pipeline_wiring_loosens_approved_renames():
    from routers import def_pipeline as P
    assert "status_display" in P.ACTIVE_KINDS and P.ACTIVE_KINDS[:2] == ("custom_fields", "layout")
    assert P.classify("status_display", {}, {"statuses": {"已核准": {"label": "已確認"}}})[0] == "loosen"
    assert P.classify("status_display", {}, {"statuses": {"草稿": {"label": "起草"}}})[0] == "neutral"


# ── 前端函式（node）──────────────────────────────────────────────────────────
JS_PRELUDE = "global.window=undefined;const S=require('./static/status-chip.js');"


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_js_off_and_unloaded_behaviour_is_todays():
    out = node(JS_PRELUDE + """console.log(JSON.stringify([S.label('待審核'), S.label('待審核','quote_list'), S.label('待審核','quote_list','審核中'), S.label(null), S.label(undefined,'x','y'),
      S.chipClass('已核准'), S.chipClass('不存在'), S.chipClass(null), S.badgeClass('草稿','badge--draft'), S.badgeClass('草稿'), S.apply(null), S.apply({enabled:false}), S.apply({enabled:true})]))""")
    assert out == ["待審核", "待審核", "審核中", "", "y", "st-chip st-chip--approved", "st-chip", "st-chip", "badge--draft", "", False, False, False]


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_js_loaded_table_overrides_only_changed_fields():
    payload = {"enabled": True, "statuses": S.effective_table({"statuses": {"草稿": {"label": "起草", "tone": "pending"}, "待審核": {"names": {"quote_list": "等待中"}}, "已核准": {"label": "已確認"}}}),
               "changed": {"草稿": ["label", "tone"], "待審核": ["names.quote_list"], "已核准": ["label"]}}
    out = node(JS_PRELUDE + "S.apply(%s);" % json.dumps(payload, ensure_ascii=False) + """console.log(JSON.stringify([
      S.label('草稿'), S.label('草稿','case'), S.chipClass('草稿'), S.badgeClass('草稿','badge--draft'),
      S.label('待審核','quote_list','審核中'), S.label('待審核','case'), S.label('待審核'), S.chipClass('待審核'),
      S.label('已核准'), S.label('簽核中','case','簽核中'), S.chipClass('簽核中'), S.badgeClass('簽核中','badge--signing'),
      S.label('不存在','case','原字')]))""")
    assert out == ["起草", "起草", "st-chip st-chip--pending", "badge--pending",
                   "等待中", "待審核", "待審核", "st-chip st-chip--pending",
                   "已確認", "簽核中", "st-chip st-chip--signing", "badge--signing",
                   "原字"]


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_js_default_alias_is_kept_when_only_the_main_label_changes():
    payload = {"enabled": True, "statuses": S.effective_table({"statuses": {"待審核": {"label": "排隊中"}}}), "changed": {"待審核": ["label"]}}
    out = node(JS_PRELUDE + "S.apply(%s);" % json.dumps(payload, ensure_ascii=False) + "console.log(JSON.stringify([S.label('待審核','quote_list','審核中'), S.label('待審核','case','待審核'), S.label('待審核')]))")
    assert out == ["審核中", "排隊中", "排隊中"]          # 報價單列表有預設簡稱 ⇒ 簡稱優先；其他情境用新名稱


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_js_load_is_silent_on_failure_and_when_flag_is_off():
    out = node("global.window=undefined;global.localStorage={getItem:()=>JSON.stringify({token:'t'})};"
               "let calls=[];global.fetch=(u,o)=>{calls.push(u);return Promise.resolve({ok:true,json:()=>Promise.resolve({enabled:false})})};"
               "const S=require('./static/status-chip.js');S.load().then(r=>{console.log(JSON.stringify([r,calls,S.label('待審核')]))})")
    assert out == [False, ["/api/status-display"], "待審核"]
    out = node("global.window=undefined;global.localStorage={getItem:()=>JSON.stringify({token:'t'})};global.fetch=()=>Promise.reject(new Error('x'));"
               "const S=require('./static/status-chip.js');S.load().then(r=>console.log(JSON.stringify([r,S.chipClass('已核准')])))")
    assert out == [False, "st-chip st-chip--approved"]


def test_status_chip_map_still_has_the_t51_vocabulary():
    src = (FRONT / "static/status-chip.js").read_text(encoding="utf-8")
    for w in ("草稿", "待審核", "待核准", "簽核中", "已核准", "已駁回", "已退回", "已拒絕", "已付款", "已匯款", "已作廢", "已取消", "已撤回", "已撤銷"):
        assert "'%s'" % w in src, w


# ── 需要資料庫（寫好未跑）─────────────────────────────────────────────────────
@pytest.fixture()
def sa(client, make_user):
    u, p = make_user(username="sd_sa", role="superadmin")[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _set(group, values):
    import db
    from helpers import settings_registry as SR
    c = db.get_db()
    try:
        SR.publish(group, values, reason="t62", user="t62", conn=c)
        c.commit()
    finally:
        c.close()


def test_endpoint_flag_off_returns_the_minimal_payload(client, sa):
    assert client.get("/api/status-display", headers=sa).json() == {"enabled": False}
    assert client.get("/api/status-display").status_code in (401, 403)


def test_endpoint_with_flag_on_serves_the_published_table_and_loosening_goes_pending(client, sa):
    _set("builder_governance", {"enabled": 1})
    _set("builder_status_display", {"enabled": 1})
    j = client.get("/api/status-display", headers=sa).json()
    assert j["enabled"] is True and j["changed"] == {} and set(j["statuses"]) == set(S.STATUS_KEYS)
    url = "/api/definitions/status_display/default"
    assert client.put(url + "/draft", headers=sa, json={"body": {"statuses": {"草稿": {"label": "起草"}}}}).status_code == 200
    pv = client.get("/api/def-governance/status_display/default/impact", headers=sa).json()["previewHash"]
    r = client.post(url + "/publish", headers=sa, json={"note": "t", "preview_hash": pv})
    assert r.status_code == 200 and "pending" not in r.json()                            # 一般狀態改名：中性，立即
    assert client.get("/api/status-display", headers=sa).json()["changed"] == {"草稿": ["label"]}
    assert client.put(url + "/draft", headers=sa, json={"body": {"statuses": {"已核准": {"label": "已確認"}}}}).status_code == 200
    pv = client.get("/api/def-governance/status_display/default/impact", headers=sa).json()["previewHash"]
    r = client.post(url + "/publish", headers=sa, json={"note": "t", "preview_hash": pv}).json()
    assert r.get("pending") is True                                                      # 核准類改名：放寬 ⇒ 待第二位核准


# ── 04 審查（S-X2 commit 1）：M1 官方用語繞過、M2 反應式、S1 原型鍵、S2 精算完結 ─────────────────────────────
@pytest.mark.parametrize("text", [
    "核​准", "核­准", "核⁠准", "核͏准", "核ㅤ准",                      # 看不見的字元拆開官方用語
    "核準", "已通過", "通過", "已批示", "已准", "准予", "已確認", "已生效", "簽核通過", "OK", "ｏｋ", "Ｏk",   # 變體、近義、全形
])
def test_m1_official_wording_bypasses_are_rejected(text):
    assert v({"待審核": {"label": text}}), repr(text)
    assert v({"草稿": {"names": {"case": text}}}), repr(text)


@pytest.mark.parametrize("text", ["待確認", "未通過", "等待核准", "尚未生效"])
def test_m1_waiting_and_negative_wording_is_allowed(text):
    assert v({"草稿": {"label": text}}) == [], text


@pytest.mark.parametrize("key,text", [("待審核", "已付款"), ("待審核", "已匯款"), ("草稿", "已完結"), ("草稿", "已結算"), ("草稿", "已定稿"),
                                     ("待審核", "已核准"), ("簽核中", "精算完結"), ("草稿", "已 付款".replace(" ", ""))])
def test_m1_a_plain_key_cannot_take_an_approved_or_paid_meaning(key, text):
    assert any("含有" in p["message"] or "官方用語" in p["message"] for p in v({key: {"label": text}})), (key, text)
    assert v({key: {"names": {"case": text}}}), (key, text)


def test_m1_names_cannot_collide_within_a_context():
    assert any("重複" in p["message"] for p in v({"草稿": {"label": "待審核"}}))                        # 草稿 顯示成 待審核（預設情境撞到）
    assert any("重複" in p["message"] for p in v({"待審核": {"names": {"case": "簽核中"}}}))            # 案件情境撞到 簽核中
    assert v({"草稿": {"label": "起草中"}}) == []                                                       # 沒撞就過
    assert v({"待審核": {}}) == [] and v({"已拒絕": {}}) == []                                         # 沒改的欄位不檢查（預設值本身有 已退回 重複）


def test_m1_an_approved_key_cannot_be_renamed_to_a_plain_keys_name_either():
    assert v({"已核准": {"label": "草稿"}})


def test_s2_finalized_is_approved_semantic():
    assert S._SEMANTIC["finalized"] == "approved" and S.compare({"statuses": {}}, {"statuses": {"finalized": {"label": "放行"}}})[0] == "loosen"
    assert v({"finalized": {"tone": "rejected"}}) and v({"draft": {"tone": "approved"}})


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_m2_first_render_before_load_updates_after_apply():
    """模擬 Alpine：effect 裡讀 label()，之後 apply() 載入表 ⇒ effect 必須重跑。反應式持有者要在第一次讀取時就存在。"""
    code = """
global.window={};
const subs=new Set(); let cur=null;
window.Alpine={reactive:(o)=>new Proxy(o,{get(t,k){ if(cur) subs.add(cur); return t[k] }, set(t,k,v){ t[k]=v; subs.forEach(f=>f()); return true }})};
const S=require('./static/status-chip.js');
let rendered=[];
function effect(){ cur=effect; rendered.push(S.label('草稿')+'|'+S.chipClass('草稿')); cur=null }
effect();
S.apply({enabled:true,statuses:%s,changed:{'草稿':['label','tone']}});
console.log(JSON.stringify(rendered));
""" % json.dumps(S.effective_table({"statuses": {"草稿": {"label": "起草", "tone": "pending"}}}), ensure_ascii=False)
    out = node(code)
    assert out == ["草稿|st-chip st-chip--draft", "起草|st-chip st-chip--pending"]


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_s1_prototype_named_statuses_do_not_throw():
    out = node(JS_PRELUDE + "S.apply({enabled:true,statuses:{},changed:{}});console.log(JSON.stringify(['constructor','toString','__proto__','hasOwnProperty'].map(k=>[S.label(k),S.chipClass(k),S.badgeClass(k,'x')])))")
    assert out == [[k, "st-chip", "x"] for k in ("constructor", "toString", "__proto__", "hasOwnProperty")]


# ── 編輯面板（靜態檢查；沒有 DOM 的環境不跑互動）─────────────────────────────────
def test_editor_follows_the_project_rules():
    import re
    src = (FRONT / "js/status-display-editor.js").read_text(encoding="utf-8")
    assert not re.search(r"(?<![\w.])(confirm|alert|prompt)\(", src), "不用原生對話框"
    assert "MotrixDefGovernance.review" in src and "preview_hash: pvh" in src                      # 發布一定經影響預覽
    assert "r.data.pending === true" in src and "核准前不會生效" in src                             # 放寬如實說待核准
    assert "role !== 'superadmin'" in src and "available()" in src                                  # 其他人連探測都不送
    assert "data-state" in src and "data-busy" in src
    assert src.count("esc(") > 10 and "innerHTML" in src                                            # 所有插入的文字都轉義
    assert "各畫面有自己的簡稱" in src or "只改顯示名稱不會蓋掉它" in src                                # 簡稱優先於顯示名稱：面板明說
    assert "type=\"color\"" not in src and "type='color'" not in src                                    # 沒有自由色碼輸入（顏色只能從色盤下拉選）


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_editor_script_loads_without_side_effects():
    out = node("global.window={};global.document=undefined;require('./js/status-display-editor.js');console.log(JSON.stringify([typeof window.MotrixStatusEditor.open, typeof window.MotrixStatusEditor.mountEntry]))")
    assert out == ["function", "function"]


# ── 第一批消費者（報價單列表、案件管理）：靜態＋node 檢查 ───────────────────────────
def test_quotations_list_goes_through_the_helper_with_the_old_function_as_base():
    src = (FRONT / "pages/quotations.html").read_text(encoding="utf-8")
    assert "_dealDisplayBase(q)" in src and "S.label(key, 'quote_list', r.text)" in src and "S.badgeClass(key, r.cls)" in src
    assert "this.initStatusDisplay()" in src and "MotrixPublicFlags.read(['builder_status_display'])" in src
    for tag in ("public-flags.js", "status-chip.js", "status-display-editor.js"):
        assert tag in src
    # 原本的對照一字不改（旗標關時就是它）
    base = src.split("_dealDisplayBase(q) {")[1].split("\n      },")[0]
    for line in ("{ text: '審核中', cls: 'badge--pending' }", "{ text: '已退回', cls: 'badge--rejected' }", "{ text: '執行中', cls: 'badge--running' }",
                 "{ text: '待決定', cls: 'badge--sent' }", "{ text: '報價中', cls: 'badge--sent' }", "{ text: s || '—', cls: '' }"):
        assert line in base, line


def test_case_page_text_goes_through_stlabel_without_touching_logic():
    src = (FRONT / "pages/case-management.html").read_text(encoding="utf-8")
    assert src.count("stLabel(c.deal_tag, 'case')") == 2 and "stLabel('已成案', 'case')" in src
    assert "stLabel('finalized', 'case', '已定稿')" in src and "stLabel('draft', 'case', '草稿')" in src
    assert "c.deal_tag==='已結案' ? 'cm-card__tag--closed'" in src                                  # class／邏輯仍用原值
    assert "'builder_layout', 'builder_custom_fields', 'builder_status_display'" in src and "this.initStatusDisplay(g.builder_status_display)" in src
    core = (FRONT / "js/case-management-core.js").read_text(encoding="utf-8")
    assert "stLabel(raw, ctx, fallback)" in core and "initStatusDisplay(flag)" in core and "flag.enabled !== 1" in core


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_quotation_list_function_is_identical_off_and_overrides_only_changed_when_on():
    import re
    src = (FRONT / "pages/quotations.html").read_text(encoding="utf-8")
    body = src.split("_dealDisplayBase(q) {")[1].split("\n      },")[0]
    wrapper = src.split("dealDisplayStatus(q) {")[1].split("\n      },")[0]
    code = "global.window={};const S=require('./static/status-chip.js');window.MotrixStatus=S;" + \
           "const base=function(q){" + body + "\n};" + \
           "const disp=function(q){const self={_dealDisplayBase:base};return (function(q){" + wrapper + "}).call(self,q)};" + \
           "const cases=[{status:'草稿'},{status:'待審核'},{status:'簽核中'},{status:'已核准'},{status:'已取消'},{status:'已拒絕'},{status:'已送出',deal_tag:'已成案'},{status:'已送出',deal_tag:'已提供'},{status:'已送出',deal_tag:'未成案'},{status:'已送出',deal_tag:'已結案'},{status:'已送出'},{status:'已確認'},{status:'weird'},{}];" + \
           "const off=cases.map(c=>JSON.stringify(disp(c))===JSON.stringify(base(c)));" + \
           "S.apply({enabled:true,statuses:%s,changed:{'待審核':['label'],'已成案':['names.quote_list','tone']}});" % json.dumps(S.effective_table({"statuses": {"待審核": {"label": "排隊中"}, "已成案": {"names": {"quote_list": "施工中"}, "tone": "signing"}}}), ensure_ascii=False) + \
           "console.log(JSON.stringify([off.every(Boolean), disp({status:'待審核'}), disp({status:'已送出',deal_tag:'已成案'}), disp({status:'草稿'})]))"
    out = node(code)
    assert out[0] is True                                                                              # 未載入表時 14 種輸入都與原函式逐字相同
    assert out[1] == {"text": "審核中", "cls": "badge--pending"}                                       # 只改了 label、報價單列表有自己的簡稱 ⇒ 維持簡稱
    assert out[2] == {"text": "施工中", "cls": "badge--signing"}                                       # 改了簡稱與色調 ⇒ 兩者都換
    assert out[3] == {"text": "草稿", "cls": "badge--draft"}


# ── 04 第二輪（M1 未關、M3、S4）──────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "核 准", "已 核 准", "核·准", "核-准", "核.准", "核/准", "核_准",                                  # 分隔字元拆開
    "已审核通过", "审核通过", "通过", "已签核", "确认", "已承認", "已認可", "已同意", "承认",             # 簡體、同義
    "Approved", "APPROVED", "approve", "a p p r o v e d", "Ok", "ＯＫ", "okay", "Granted",           # 英文、全形
])
def test_m1b_separator_script_and_english_bypasses_are_rejected(text):
    assert v({"已駁回": {"label": text}}), repr(text)
    assert v({"已駁回": {"names": {"cashier": text}}}), repr(text)


@pytest.mark.parametrize("text", ["✅", "☑", "✔已審", "✓", "😀草稿", "ОК", "ᴏᴋ", "あ", "\ud800x", "草\tx"])
def test_m1b_characters_outside_the_allowlist_are_rejected(text):
    assert any("看不見" in p["message"] or "只能用" in p["message"] for p in v({"已駁回": {"label": text}})), repr(text)


@pytest.mark.parametrize("text", ["待已核准", "待審核已核准", "未知已核准", "待 已核准", "等待已確認", "待核准已核准"])
def test_m1b_the_negator_exemption_needs_exactly_one_official_word(text):
    assert v({"已駁回": {"label": text}}), repr(text)


@pytest.mark.parametrize("text", ["未通過", "等待確認", "尚未生效", "不批准", "待確認", "等待 核准"])
def test_m1b_plain_waiting_phrases_are_still_allowed(text):
    assert v({"已駁回": {"label": text}}) == [], text


@pytest.mark.parametrize("text", ["已 付款", "已付款.", "已付款(重)", "已匯 款", "已 匯款.", "已結清", "已付清", "已入帳", "已完結.", "精算 完結", "已 定稿"])
def test_m1b_paid_and_settled_wording_with_separators_is_rejected_on_plain_keys(text):
    assert v({"待審核": {"label": text}}), repr(text)
    assert v({"簽核中": {"names": {"case": text}}}), repr(text)


def test_m3_lone_surrogates_are_rejected_not_a_500():
    for bad in ("\ud800x", "x\udfff", "\ud83d"):
        assert v({"草稿": {"label": bad}})
    body = json.loads('{"statuses": {"草稿": {"label": "\\ud800x"}}}')                                  # json.loads 會產生孤立代理字元
    probs = S.validate_table(body)
    assert probs
    assert S.compare({"statuses": {}}, body)[0] == "loosen"
    json.dumps(probs, ensure_ascii=False).encode("utf-8")                                          # 錯誤訊息本身可以編成 utf-8（回應時不會炸）


def test_m1b_ordinary_good_names_pass():
    for ok in ("起草中", "排隊中", "施工中", "待處理", "Draft (new)", "第一批", "A/B 測試"):
        assert v({"草稿": {"label": ok}}) == [], ok


def test_s4_editor_escapes_attribute_values():
    src = (FRONT / "js/status-display-editor.js").read_text(encoding="utf-8")
    assert "esc(c) + ':' + esc(k)" in src and "'<option value=\"' + esc(t) + '\"'" in src


# ── 第二批消費者：出納、請款單、報表 ─────────────────────────────────────────────────
def test_batch2_keys_are_code_owned_display_only():
    d = S.defaults()
    assert d["已收款"]["tone"] == "paid" and S._SEMANTIC["已收款"] == "paid" and S._SEMANTIC["差額已核可"] == "approved"
    assert d["待收款"]["tone"] == "pending" and d["差額待審核"]["tone"] == "pending"
    assert S.compare({"statuses": {}}, {"statuses": {"已收款": {"label": "款已入帳"}}})[0] == "loosen"       # 付款類改名 = 放寬
    assert S.compare({"statuses": {}}, {"statuses": {"差額已核可": {"label": "差額放行"}}})[0] == "loosen"    # 核准類改名 = 放寬
    assert S.compare({"statuses": {}}, {"statuses": {"待收款": {"label": "等收款"}}})[0] == "neutral"
    assert v({"待收款": {"label": "已收款"}}) and v({"差額待審核": {"label": "差額已核可"}})                   # 一般狀態不能冒用


def test_batch2_pages_wire_the_helper_without_changing_logic():
    cash = (FRONT / "pages/cashier.html").read_text(encoding="utf-8")
    assert "stLabel(it.received ? '已收款' : '待收款', 'cashier')" in cash and ":class=\"it.received ? 'rb-received' : 'rb-pending'\"" in cash
    assert "public-flags.js" in cash and "status-chip.js" in cash
    js = (FRONT / "js/cashier.js").read_text(encoding="utf-8")
    assert "window.MotrixStatus.init()" in js and "this.stLabel(raw, 'cashier', raw)" in js and "decision === 'approve'" in js
    pr = (FRONT / "pages/payment-request.html").read_text(encoding="utf-8")
    assert "MotrixStatus.label(e.status, 'cashier')" in pr and "e.status === '已核准'" in pr and "MotrixStatus.chipClass(e.status)" in pr
    form = (FRONT / "pages/payment-request-form.html").read_text(encoding="utf-8")
    assert "MotrixStatus.badgeClass(this.q.status, base)" in form
    rep = (FRONT / "pages/reports.html").read_text(encoding="utf-8")
    assert rep.count("stLabel(it.dealTag, 'report')") == 2 and rep.count("stLabel(c.dealTag, 'report')") == 2 and "stLabel(mc.dealTag, 'report')" in rep
    assert "stLabel('finalized', 'report', '已結算')" in rep and "stLabel('finalized', 'report', '已定稿')" in rep       # 兩處今天就不同：各自保留 fallback
    assert ":class=\"it.dealTag==='已結案'?'rb-closed':'rb-active'\"" in rep                                          # class 與判斷不動
    assert "window.MotrixStatus.init()" in (FRONT / "js/reports.js").read_text(encoding="utf-8")


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_batch2_expressions_equal_the_old_ones_when_the_table_is_not_loaded():
    code = """global.window={};const M=require('./static/status-chip.js');window.MotrixStatus=M;
const stLabel=(raw,ctx,fb)=>window.MotrixStatus.label(raw,ctx,fb);
const out=[];
for (const received of [true,false]) out.push([ stLabel(received ? '已收款' : '待收款','cashier'), received ? '已收款' : '待收款' ]);
const remit=(s)=>{const raw=s==='pending'?'差額待審核':(s==='approved'?'差額已核可':'');return raw?stLabel(raw,'cashier',raw):''};
const remitOld=(s)=>s==='pending'?'差額待審核':(s==='approved'?'差額已核可':'');
for (const s of ['pending','approved','',null,undefined,'weird']) out.push([remit(s),remitOld(s)]);
for (const st of ['finalized','draft','',null]) {
  out.push([st==='finalized'?stLabel('finalized','report','已結算'):stLabel('draft','report','草稿'), st==='finalized'?'已結算':'草稿']);
  out.push([st==='finalized'?stLabel('finalized','report','已定稿'):stLabel('draft','report','草稿'), st==='finalized'?'已定稿':'草稿']);
}
for (const t of ['已成案','已結案','未成案','已提供','','x']) out.push([stLabel(t,'report'), t]);
console.log(JSON.stringify(out.every(p=>p[0]===p[1])));"""
    assert node(code) is True


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_batch2_loaded_table_changes_only_what_the_admin_changed():
    table = S.effective_table({"statuses": {"待收款": {"label": "等收款"}, "差額待審核": {"names": {"cashier": "差額覆核中"}}, "已結案": {"names": {"report": "完結"}}}})
    changed = S.changed_fields(table)
    code = "global.window={};const M=require('./static/status-chip.js');window.MotrixStatus=M;M.apply({enabled:true,statuses:%s,changed:%s});" % (
        json.dumps(table, ensure_ascii=False), json.dumps(changed, ensure_ascii=False)) + \
        "console.log(JSON.stringify([M.label('待收款','cashier'),M.label('已收款','cashier'),M.label('差額待審核','cashier','差額待審核'),M.label('差額已核可','cashier','差額已核可'),M.label('已結案','report'),M.label('已結案','case'),M.label('已成案','report')]))"
    assert node(code) == ["等收款", "已收款", "差額覆核中", "差額已核可", "完結", "已結案", "已成案"]


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_init_reads_the_flag_once_and_loads_only_when_on():
    code = """global.window={};global.localStorage={getItem:()=>JSON.stringify({token:'t'})};
let urls=[];
window.MotrixPublicFlags={read:async(g)=>{urls.push('flags:'+g.join(','));return {builder_status_display:{enabled:%s}}}};
global.fetch=(u)=>{urls.push(u);return Promise.resolve({ok:true,json:()=>Promise.resolve({enabled:false})})};
const M=require('./static/status-chip.js');
Promise.all([M.init(),M.init()]).then(r=>console.log(JSON.stringify([r,urls])));"""
    assert node(code % "0") == [[False, False], ["flags:builder_status_display"]]                         # 旗標關：只讀旗標一次，不載入表
    assert node(code % "1") == [[False, False], ["flags:builder_status_display", "/api/status-display"]]    # 旗標開：多一個載入請求（這裡 server 回 enabled:false 所以仍是 False）


# ── 第三批消費者：精算頁、傳票頁 ─────────────────────────────────────────────────
def test_batch3_posted_key_is_approved_semantic_and_outside_the_chip_map_group():
    assert S._SEMANTIC["已過帳"] == "approved" and S._GROUP["已過帳"] == "voucher" and S.defaults()["已過帳"]["tone"] == "approved"
    assert S.compare({"statuses": {}}, {"statuses": {"已過帳": {"label": "已入帳"}}})[0] == "loosen"
    assert v({"待審核": {"label": "已過帳"}}) and v({"待審核": {"label": "已 過 帳"}})                    # 一般狀態不能冒用


def test_batch3_pages_wire_the_helper_without_changing_logic():
    st = (FRONT / "pages/settlement.html").read_text(encoding="utf-8")
    assert "stLabel('draft', 'settlement', '精算草稿')" in st and "stLabel('finalized', 'settlement', '精算完結')" in st
    assert "settlement.status === 'finalized'" in st and "window.MotrixStatus.init()" in st and "status-chip.js" in st
    vo = (FRONT / "pages/voucher.html").read_text(encoding="utf-8")
    assert vo.count("stLabel(") == 3 and "v.status === '已過帳' ? 'posted'" in vo and "status === '已過帳' ? 'posted'" in vo
    js = (FRONT / "js/voucher.js").read_text(encoding="utf-8")
    assert "stLabel(raw, ctx, fallback)" in js and "window.MotrixStatus.init()" in js and "get canEdit() { return this.status === '草稿' && !this.voidedAt }" in js


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_batch3_voucher_and_settlement_expressions_equal_the_old_ones_when_not_loaded():
    code = """global.window={};const M=require('./static/status-chip.js');window.MotrixStatus=M;
const stLabel=(raw,ctx,fb)=>window.MotrixStatus.label(raw,ctx,fb);
const out=[];
for (const voided of ['', null, '2026-10-01T00:00:00'])
  for (const status of ['草稿','待審核','簽核中','已核准','已過帳','',null,undefined])
    out.push([stLabel(voided ? '已作廢' : status), voided ? '已作廢' : status]);
out.push([stLabel('draft','settlement','精算草稿'),'精算草稿'],[stLabel('finalized','settlement','精算完結'),'精算完結']);
console.log(JSON.stringify(out.every(p=>(p[0]==null?'':p[0])===(p[1]==null?'':p[1]))));"""
    assert node(code) is True


def test_batch3_voucher_filter_options_show_the_label_but_keep_the_raw_value():
    vo = (FRONT / "pages/voucher.html").read_text(encoding="utf-8")
    assert '<option :value="st" x-text="stLabel(st)"></option>' in vo and 'x-model="filterStatus"' in vo
    assert vo.count("stLabel(") == 3                                                              # 列表、標題、篩選選項
    src = (FRONT / "pages/case-management.html").read_text(encoding="utf-8")
    rep = (FRONT / "pages/reports.html").read_text(encoding="utf-8")
    assert "stLabel('finalized', 'case', '已定稿')" in src and "stLabel('finalized', 'report', '已定稿')" in rep and "stLabel('finalized', 'report', '已結算')" in rep
