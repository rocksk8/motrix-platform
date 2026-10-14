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
    assert c({}, {"已核准": {"label": "已確認"}}) == "loosen"
    monkeypatch.setitem(S._SEMANTIC, "已核准", "plain")                           # 把語意拿掉 ⇒ 結果翻面，證明比較器真的看語意
    assert c({}, {"已核准": {"label": "已確認"}}) == "neutral"


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
