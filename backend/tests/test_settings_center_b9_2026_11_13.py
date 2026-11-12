"""選單去工程師化 批次 9：設定中心彙整（共用分類資料檔）＋「?」說明＋守門（2026-11-13）。

守門的重點（不是只驗現況，而是日後新增欄位／群組沒有歸類或沒有說明就會紅）：
  ① 每個設定群組恰好屬於一個分類；分類資料檔本身結構合格。
  ② 每個設定欄位要嘛在「標籤已夠清楚」白名單、要嘛有說明；說明三段不可為空、不得含工程用語（禁用詞：共用來源＝backend/tools/ux_audit_config.json；
     該檔還沒落地時改用程式內建清單，不略過；內建清單與共用檔逐項同步由測試守住）。
  ③ 分類數、群組數、欄位數由測試輸出，不手寫在文件。
"""
import json
import os

import pytest

from helpers import menu_categories as MC
from helpers import settings_help as SH
from helpers import settings_registry as sr

_UX_CFG = os.path.join(os.path.dirname(__file__), "..", "tools", "ux_audit_config.json")


def _all_fields():
    from helpers import settings_groups  # noqa: F401  登錄群組
    return ["%s.%s" % (g, f["key"]) for g, m in sr.groups().items() if not g.startswith("zz_") for f in m["fields"]]


def _real_groups():
    from helpers import settings_groups  # noqa: F401
    return [g for g in sr.groups() if not g.startswith("zz_")]


# ── ① 分類資料檔 ─────────────────────────────────────────────────────────────

def test_category_file_is_valid_and_every_group_belongs_to_exactly_one_category():
    d = MC.default_data()
    assert MC.validate(d) == [], MC.validate(d)
    groups = set(_real_groups())
    mapped = {k.split(":", 1)[1] for k in d["items"] if k.startswith("settings_group:")}
    assert groups - mapped == set(), "這些設定群組沒有歸類（請加進 core/menu_categories_l1.json）：%s" % sorted(groups - mapped)
    assert mapped - groups == set(), "分類資料檔裡有已不存在的設定群組：%s" % sorted(mapped - groups)
    # 一個項目只能有一個分類＝dict 的鍵唯一；再確認沒有群組以不同種類前綴重複登記
    keys = [k for k in d["items"] if k.startswith("settings_group:")]
    assert len(keys) == len(set(keys))
    cats = {}
    for k, it in d["items"].items():
        cats.setdefault(it["category"], []).append(k)
    print("\n分類 %d 類；設定群組 %d 組；欄位 %d 個；各類群組數：%s" % (
        len(d["categories"]), len(groups), len(_all_fields()), {c["key"]: len(cats.get(c["key"], [])) for c in d["categories"]}))


def test_the_14_open_custom_feature_switches_are_collected_in_one_place():
    d = MC.default_data()
    sw = [g for g in _real_groups() if g.startswith("builder_") or g == "list_prefs"]
    assert len(sw) == 14, sw
    for g in sw:
        it = d["items"]["settings_group:" + g]
        assert it["category"] == "custom" and it["section"] == "開放哪些客製功能", g


def test_every_group_has_a_plain_blurb_and_when_and_a_valid_status():
    d = MC.default_data()
    for k, it in d["items"].items():
        if k.startswith("settings_group:"):
            assert it["blurb"].strip() and it["when"].strip(), k
            assert it["status"] in ("keep", "related", "legacy"), k
    assert {"company", "people", "flow", "numbering", "notify", "data", "custom"} <= {c["key"] for c in d["categories"]}


def test_override_renames_reorders_and_validates_and_empty_override_is_the_default(client, make_user):
    base = MC.effective({})
    assert base["items"]["settings_group:uploads"]["category"] == "data"
    new = MC.set_override({"items": {"settings_group:uploads": {"name": "上傳限制（公司版）", "order": 5, "category": "company"}},
                           "categories": {"company": {"name": "公司基本規則", "order": 1}}}, user="t")
    assert new["items"]["settings_group:uploads"]["category"] == "company"
    eff = MC.effective()
    assert eff["items"]["settings_group:uploads"]["category"] == "company" and eff["categories"][0]["name"] == "公司基本規則"
    view = MC.categories_view("settings_group", {"uploads": "上傳容量"})
    names = {it["id"]: it["name"] for c in view for it in c["items"]}
    assert names["uploads"] == "上傳限制（公司版）"
    for bad in ({"items": {"settings_group:nope": {"name": "x"}}}, {"categories": {"zzz": {"name": "x"}}},
                {"items": {"settings_group:uploads": {"name": "<b>x</b>"}}}, {"items": {"settings_group:uploads": {"category": "nope"}}},
                {"items": {"settings_group:uploads": {"order": "1"}}}, {"items": {"settings_group:uploads": {"color": "red"}}}, {"other": {}}, []):
        with pytest.raises(ValueError):
            MC.set_override(bad)
    MC.set_override({"items": {"settings_group:uploads": None}, "categories": {"company": None}})
    assert MC.effective()["items"]["settings_group:uploads"]["category"] == "data"


def test_broken_override_entries_are_ignored_not_fatal():
    ov = {"items": {"settings_group:uploads": {"name": "", "category": "nope", "order": True}, "settings_group:ghost": {"name": "x"}}, "categories": "bad"}
    eff = MC.effective(ov)
    assert eff["items"]["settings_group:uploads"]["category"] == "data" and "settings_group:ghost" not in eff["items"]


# ── ② 說明資料檔與守門 ───────────────────────────────────────────────────────

def _uncovered(fields, data):
    h, wl = set(data["help"]), set(data["label_clear"])
    return sorted(set(fields) - h - wl), sorted(h & wl), sorted((h | wl) - set(fields))


def test_every_setting_field_is_either_label_clear_or_has_help():
    missing, both, unknown = _uncovered(_all_fields(), SH.system_data())
    assert not missing, "這些設定欄位既沒有「?」說明、也不在「標籤已夠清楚」白名單（請在 core/settings_help.json 補說明或加入 label_clear）：%s" % missing
    assert not both, "同時在說明與白名單：%s" % both
    assert not unknown, "說明資料檔裡有已不存在的欄位：%s" % unknown
    d = SH.system_data()
    print("\n欄位 %d：有說明 %d、標籤已夠清楚（白名單）%d" % (len(_all_fields()), len(d["help"]), len(d["label_clear"])))


def test_a_new_field_without_help_or_whitelist_is_red():
    """負向對照：守門真的會抓到沒說明的新欄位（守門自己是活的）。"""
    missing, _b, _u = _uncovered(_all_fields() + ["zz_new_group.new_field"], SH.system_data())
    assert missing == ["zz_new_group.new_field"]


def test_help_texts_have_three_non_empty_sections_and_no_markup():
    bad = {}
    for k, e in SH.system_data()["help"].items():
        p = SH.problems_in(e, terms=None)
        if p:
            bad[k] = p
    assert not bad, bad
    assert SH.problems_in({"what": "", "when": "x", "impact": "y"}, terms=None), "空字串必須被擋"
    assert SH.problems_in({"what": "a", "when": "b"}, terms=None), "缺一段必須被擋"
    assert SH.problems_in({"what": "a", "when": "b", "impact": "c", "extra": "d"}, terms=None)
    assert SH.problems_in({"what": "<b>a</b>", "when": "b", "impact": "c"}, terms=None)


def test_help_texts_contain_no_engineering_terms():
    t = SH.forbidden_terms()
    assert t and t["forbidden"], "禁用詞清單永遠有內容（共用檔不存在時用內建清單）"
    bad = {k: SH.problems_in(e, terms=t) for k, e in SH.system_data()["help"].items()}
    bad = {k: v for k, v in bad.items() if v}
    assert not bad, bad


def test_forbidden_term_matching_works(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"forbidden_terms": [{"term": "token", "ci": True}, {"term": "SMTP", "ci": False}],
                               "deprecated_terms": [{"term": "待審核", "use": "待簽核"}]}), encoding="utf-8")
    monkeypatch.setenv("MOTRIX_UX_AUDIT_CONFIG", str(cfg))
    t = SH.forbidden_terms()
    assert t and ("token", True) in t["forbidden"]
    ok = {"what": "這是什麼", "when": "什麼時候", "impact": "會怎樣"}
    assert SH.problems_in(ok, terms=t) == []
    assert any("Token" in x or "token" in x for x in SH.problems_in({**ok, "what": "給你的 Token"}, terms=t)), "不分大小寫"
    assert not any("smtp" in x for x in SH.problems_in({**ok, "what": "用 smtp"}, terms=t)), "區分大小寫的詞不誤判"
    assert any("待簽核" in x for x in SH.problems_in({**ok, "impact": "進入待審核"}, terms=t)), "舊用語要提示新用語"
    monkeypatch.setenv("MOTRIX_UX_AUDIT_CONFIG", str(tmp_path / "missing.json"))
    t2 = SH.forbidden_terms()
    assert t2 and ("SMTP", False) in t2["forbidden"] and ("webhook", True) in t2["forbidden"], "共用檔不存在 ⇒ 用內建清單，不略過"
    assert any("webhook" in x for x in SH.problems_in({**ok, "what": "填 Webhook 位址"})), "內建清單真的擋得到"


def test_builtin_terms_stay_in_sync_with_the_shared_file():
    """內建的「共用」那份是從 hichan-7 的 ux_audit_config.json 複製的：共用檔存在時，內建每一項都必須還在共用檔裡（共用檔改了就要同步內建）。"""
    if not os.path.exists(_UX_CFG):
        pytest.skip("backend/tools/ux_audit_config.json 還沒落地（hichan-7 的 feat/ux-p0-p1-text 分支）：落地後這題自動比對；沒有共用檔時守門用內建清單，不受影響")
    shared = SH.shared_terms_file()
    assert shared
    missing_f = [x for x in SH.BUILTIN_SHARED_TERMS["forbidden"] if x not in shared["forbidden"]]
    missing_d = [x for x in SH.BUILTIN_SHARED_TERMS["deprecated"] if x not in shared["deprecated"]]
    assert not missing_f and not missing_d, "內建清單有共用檔沒有的詞（共用檔改過？請同步 helpers/settings_help.py）：%s %s" % (missing_f, missing_d)
    new_f = [x for x in shared["forbidden"] if x not in SH.BUILTIN_SHARED_TERMS["forbidden"]]
    assert not new_f, "共用檔新增了禁用詞，內建清單要一起加：%s" % new_f


def test_override_api_rejects_engineering_terms_even_when_the_shared_file_is_absent(client, make_user, tmp_path, monkeypatch):
    monkeypatch.setenv("MOTRIX_UX_AUDIT_CONFIG", str(tmp_path / "missing.json"))
    sa = _login(client, make_user, "b9_sa_term")
    body = {"retention.audit_log_keep_days": {"what": "請填 SMTP token JSON webhook", "when": "何時", "impact": "影響"}}
    r = client.put("/api/menu/settings-help/override", headers=sa, json=body)
    assert r.status_code == 400 and "工程用語" in r.text, r.text


# ── 名稱／說明不可含看不見的字元 ──────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["\u200b", "名\u200b稱", "\u202e名稱", "名\u0000稱", "\u2028", "\u00a0", "   ", "\u3000"])
def test_hidden_or_blank_names_are_rejected(bad, client, make_user):
    with pytest.raises(ValueError):
        MC.set_override({"items": {"settings_group:uploads": {"name": bad}}})
    sa = _login(client, make_user, "b9_sa_hid")
    assert client.put("/api/menu/categories/override", headers=sa, json={"items": {"settings_group:uploads": {"name": bad}}}).status_code == 400


def test_hidden_characters_in_help_text_are_rejected_but_normal_punctuation_and_newlines_are_fine():
    ok = {"what": "這是什麼，說明：可以有「引號」與（括號）。\n第二行", "when": "何時", "impact": "影響"}
    assert SH.problems_in(ok, terms=None) == []
    for bad in ("說\u200b明", "說明\u202e", "說明\x00"):
        assert SH.problems_in({**ok, "what": bad}, terms=None), repr(bad)
    assert SH.has_hidden_chars("\u200b") and SH.has_hidden_chars("") and not SH.has_hidden_chars("上傳限制")


# ── 稽核：寫入者是真實帳號，並記哪些項目被改 ──────────────────────────────────

def test_override_audit_rows_carry_the_real_actor_and_changed_keys(client, make_user):
    from db import get_db
    sa = _login(client, make_user, "b9_sa_aud")
    assert client.put("/api/menu/categories/override", headers=sa, json={"items": {"settings_group:uploads": {"name": "上傳限制"}}}).status_code == 200
    hb = {"retention.audit_log_keep_days": {"what": "新說明", "when": "何時", "impact": "影響"}}
    assert client.put("/api/menu/settings-help/override", headers=sa, json=hb).status_code == 200
    c = get_db()
    rows = {r["action"]: r for r in c.execute("SELECT username, action, detail FROM audit_log WHERE action IN ('menu_categories.override','settings_help.override')").fetchall()}
    c.close()
    assert set(rows) == {"menu_categories.override", "settings_help.override"}
    for r in rows.values():
        assert r["username"] == "b9_sa_aud", "稽核列要有真實帳號，用帳號搜尋才找得到"
    d1 = json.loads(rows["menu_categories.override"]["detail"])
    d2 = json.loads(rows["settings_help.override"]["detail"])
    assert d1["changed"]["items"] == ["settings_group:uploads"] and d2["keys"] == ["retention.audit_log_keep_days"]
    assert "上傳限制" not in rows["menu_categories.override"]["detail"] and "新說明" not in rows["settings_help.override"]["detail"], "只記哪些被改，不記文字內容"


# ── GET /api/menu/categories：設定中心群組只給最高管理者 ───────────────────────

def test_categories_api_hides_settings_group_names_from_non_superadmins(client, make_user):
    sa = _login(client, make_user, "b9_sa_cat")
    ad = _login(client, make_user, "b9_ad_cat", "admin")
    sales = _login(client, make_user, "b9_sales_cat", "sales")
    full = client.get("/api/menu/categories", headers=sa).json()
    assert any(k.startswith("settings_group:") for k in full["items"]) and full["categories"]
    for h in (ad, sales):
        j = client.get("/api/menu/categories", headers=h).json()
        assert not any(k.startswith("settings_group:") for k in j["items"]), "設定群組名稱／說明只給最高管理者"
        assert "上傳" not in json.dumps(j, ensure_ascii=False) or j["categories"] == []


# ── help_view：範例不重複、單一最高管理者的提示 ────────────────────────────────

def test_help_view_does_not_repeat_example_equal_to_default_and_explains_single_superadmin():
    fv = {f["key"]: f for f in sr.field_views("quote_alt")}
    v = SH.help_view("quote_alt", fv["note_template"], {})
    assert v["suggest"].count("擇一方案選擇") == 1, v["suggest"]
    hits = [k for k, e in SH.system_data()["help"].items() if "另一位最高管理者" in e["impact"]]
    assert hits, "前提：有說明提到要另一位最高管理者"
    g, f = hits[0].split(".", 1)
    fvs = {x["key"]: x for x in sr.field_views(g)}
    assert "使用者管理" in SH.help_view(g, fvs[f], {})["impact"]


# ── help_view：第四段由欄位 metadata 產生 ─────────────────────────────────────

def test_fourth_section_comes_from_field_metadata_not_hand_written():
    fv = {f["key"]: f for f in sr.field_views("retention")}
    v = SH.help_view("retention", fv["cloud_monthly_keep_days"], {})
    assert v["what"] and v["when"] and v["impact"] and v["suggest"]
    assert "系統預設" in v["suggest"] and "例如：0＝永久保留" in v["suggest"]
    assert not any("系統預設" in x for x in SH.system_data()["help"]["retention.cloud_monthly_keep_days"].values()), "第四段不手寫進資料檔"
    wl = SH.help_view("uploads", {f["key"]: f for f in sr.field_views("uploads")}["max_file_mb"], {})
    assert wl == {"labelClear": True, "missing": False}


def test_company_help_override_wins_and_bad_override_falls_back(client, make_user):
    key = "retention.local_db_keep_days"
    SH.set_override({key: {"what": "公司自己的說法", "when": "想改的時候", "impact": "影響很小"}}, user="t")
    h = SH.help_for(key)
    assert h["what"] == "公司自己的說法" and h["custom"] is True
    for bad in ({"nope.field": {"what": "a", "when": "b", "impact": "c"}}, {key: {"what": "", "when": "b", "impact": "c"}}, {}, {key: {"what": "a"}}):
        with pytest.raises(ValueError):
            SH.set_override(bad)
    assert SH.help_for(key, {key: {"what": "", "when": "b", "impact": "c"}})["custom"] is False, "不合格的覆寫在讀取時被忽略"
    SH.set_override({key: None})
    assert SH.help_for(key)["custom"] is False


# ── API ──────────────────────────────────────────────────────────────────────

def _login(client, make_user, name="b9_sa", role="superadmin"):
    u, pw = make_user(username=name, role=role)
    tok = client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def test_groups_api_carries_category_section_blurb_and_field_texts(client, make_user):
    h = _login(client, make_user)
    r = client.get("/api/settings-center/groups", headers=h).json()
    by = {g["group"]: g for g in r["groups"]}
    assert by["uploads"]["category"] == "data" and by["uploads"]["blurb"] and by["uploads"]["when"]
    assert by["builder_layout"]["section"] == "開放哪些客製功能"
    assert any("單檔" in x for x in by["uploads"]["fieldTexts"])
    assert [c["key"] for c in r["categories"]][:3] == ["company", "people", "flow"]      # 只列有項目的分類（「開始使用」等之後由總覽那一批填入）
    assert all(g.get("category") for g in r["groups"] if g["group"] in set(_real_groups())), "每個群組都有分類"


def test_group_api_has_help_info_for_every_field_and_missing_is_never_true(client, make_user):
    h = _login(client, make_user)
    miss = []
    for g in _real_groups():
        d = client.get("/api/settings-center/groups/%s" % g, headers=h).json()
        if d.get("status") != "open":
            continue
        for f in d["fields"]:
            hi = f["helpInfo"]
            if hi.get("missing"):
                miss.append("%s.%s" % (g, f["key"]))
            elif not hi["labelClear"]:
                assert hi["what"] and hi["when"] and hi["impact"] and hi["suggest"], (g, f["key"])
    assert not miss, miss


def test_override_endpoints_are_superadmin_only_and_validate(client, make_user):
    sa = _login(client, make_user)
    ad = _login(client, make_user, "b9_ad", "admin")
    body = {"items": {"settings_group:uploads": {"name": "上傳限制"}}}
    assert client.put("/api/menu/categories/override", headers=ad, json=body).status_code == 403
    assert client.put("/api/menu/categories/override", headers=sa, json={"items": {"settings_group:ghost": {"name": "x"}}}).status_code == 400
    r = client.put("/api/menu/categories/override", headers=sa, json=body)
    assert r.status_code == 200 and r.json()["items"]["settings_group:uploads"]["name"] == "上傳限制"
    assert client.get("/api/menu/categories", headers=ad).status_code == 200, "分類唯讀端點登入即可"
    g = client.get("/api/settings-center/groups", headers=sa).json()["groups"]
    assert next(x for x in g if x["group"] == "uploads")["label"] == "上傳限制"
    hb = {"retention.audit_log_keep_days": {"what": "新說明", "when": "何時", "impact": "影響"}}
    assert client.put("/api/menu/settings-help/override", headers=ad, json=hb).status_code == 403
    assert client.put("/api/menu/settings-help/override", headers=sa, json={"x.y": {"what": "a", "when": "b", "impact": "c"}}).status_code == 400
    assert client.put("/api/menu/settings-help/override", headers=sa, json=hb).json()["customCount"] == 1
    d = client.get("/api/settings-center/groups/retention", headers=sa).json()
    f = next(x for x in d["fields"] if x["key"] == "audit_log_keep_days")
    assert f["helpInfo"]["what"] == "新說明" and f["helpInfo"]["custom"] is True


# ── 前端：共用元件與頁面 ──────────────────────────────────────────────────────

_FE = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")


def _read(*p):
    with open(os.path.join(_FE, *p), encoding="utf-8") as fh:
        return fh.read()


def test_hint_component_is_shared_accessible_and_text_is_not_in_the_page():
    js = _read("static", "hint-popover.js")
    for needle in ("aria-expanded", "aria-describedby", "aria-controls", "Escape", "focusin", "textContent", "MutationObserver",
                   "'dialog'", "aria-modal", "hint__backdrop", "document.body.appendChild(pop)", "restoreFocus"):
        assert needle in js, needle
    assert "role=\"tooltip\"" not in _read("pages", "settings-center.html")
    assert "innerHTML" not in js, "內容一律用 textContent 寫入"
    css = _read("css", "hint-popover.css")
    assert ".hint__btn" in css and "width: 16px" in css and ".is-sheet" in css and ".hint__backdrop" in css and "inset: -12px" in css
    html = _read("pages", "settings-center.html")
    assert "hint-popover.js" in html and "hint-popover.css" in html and 'class="hint"' in html
    for h in SH.system_data()["help"].values():
        assert h["what"] not in html, "說明文字不得寫在 HTML 裡"
