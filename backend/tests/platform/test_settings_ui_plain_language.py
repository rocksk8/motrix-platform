# -*- coding: utf-8 -*-
"""零技術門檻守門（使用者 2026-10-10，CORE-SPEC／MODULE-GUIDE §15.8–15.10）：設定畫面不得露出代碼、內部鍵、列舉字；
每個欄位與選項都要有問句、說明與影響說明（缺 ⇒ 登錄當下就失敗）。

掃描對象：①登錄的所有使用者可見字串（群組名稱與說明、欄位問句／標籤／說明／影響／風險提示／確認句、選項標籤與影響）；
②設定中心頁面模板的靜態文字。判準：英文字母連續兩個以上的詞若不在白名單 ⇒ 紅燈（內部鍵、snake_case、camelCase、allow／forbid／in_bin 之類列舉字
全部會被抓到）。⚠️ 守門只抓得到裸露的鍵與列舉字，措辭好不好懂要靠人看（MODULE-GUIDE §15 稽核者檢查表）。
"""
import os
import re

import pytest

from helpers import settings_groups  # noqa: F401
from helpers import settings_registry as R

ALLOW = {"MOTRIX", "PDF", "MB", "GB", "KB", "OK", "Excel", "Word", "Google", "QR", "ID"}
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
PAGE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "pages", "settings-center.html")


def raw_words(text):
    """文字裡不在白名單的英文詞（含內部鍵、列舉字）。"""
    return [w for w in _WORD.findall(text or "") if w not in ALLOW]


def visible_strings():
    out = []
    for g, m in R.groups().items():
        if g.startswith("zz_"):
            continue
        out += [("群組 %s 名稱" % g, m["label"]), ("群組 %s 說明" % g, m["help"])]
        for f in m["fields"]:
            for k in ("question", "label", "help", "impact", "riskText", "effect", "unit"):
                out.append(("%s.%s.%s" % (g, f["key"], k), f.get(k) or ""))
            for c in f["choices"]:
                out += [("%s.%s 選項標籤" % (g, f["key"]), c["label"]), ("%s.%s 選項影響" % (g, f["key"]), c["impact"])]
    return out


def template_text(html):
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?s)<!--.*?-->", " ", html)
    html = re.sub(r"""(?s)<(?:[^>"']|"[^"]*"|'[^']*')*>""", " ", html)       # 引號內的 > （例如 Alpine 的 =>）不結束標籤
    return html


def test_registry_strings_have_no_raw_keys():
    bad = [(where, raw_words(t)) for where, t in visible_strings() if raw_words(t)]
    assert not bad, "畫面文字出現裸露的鍵或英文列舉字：%s" % bad[:5]


def test_every_field_has_plain_language_texts():
    for g, m in R.groups().items():
        if g.startswith("zz_"):
            continue
        for f in m["fields"]:
            for k in ("question", "label", "help", "impact"):
                assert R._zh(f[k]), "%s.%s 缺少繁中%s" % (g, f["key"], k)
            if f["risk"] in ("money", "legal", "security") or f["requiresPending"]:
                assert R._zh(f["riskText"]), "%s.%s 高風險卻沒有白話風險提示" % (g, f["key"])


def test_page_template_has_no_raw_words():
    html = open(PAGE, encoding="utf-8").read()
    assert not raw_words(template_text(html)), raw_words(template_text(html))


# --- 正對照（守門本身能抓到壞的）與反對照（正常文字不誤報） ---------------------

@pytest.mark.parametrize("text", ["audit_log_keep_days", "允許 allow 這個動作", "狀態是 in_bin", "capabilityKey 請選擇", "forbid"])
def test_positive_control_raw_words_are_caught(text):
    assert raw_words(text)


@pytest.mark.parametrize("text", ["稽核紀錄要保留幾天？", "單檔大小上限 20 MB", "備份成 PDF 檔", "MOTRIX 專案管理系統"])
def test_negative_control_plain_text_passes(text):
    assert not raw_words(text)


def test_positive_control_template_scan_sees_text_nodes():
    assert raw_words(template_text("<div>顯示 audit_log_keep_days 給使用者</div>"))
    assert not raw_words(template_text('<div x-text="g.label" class="sc-card">設定中心</div><script>var x_y = 1</script>'))
    assert not raw_words(template_text('<template x-for="f in xs.filter(x => !x.adv)">進階</template>'))      # 屬性值裡的 =>


# --- 登錄當下的必填驗證 ---------------------------------------------------------

_OK = dict(question="要設多少？", label="某個設定", help="這是說明。", impact="影響之後的單據。")


@pytest.mark.parametrize("drop", ["question", "label", "help", "impact"])
def test_missing_required_text_fails_at_registration(drop):
    kw = dict(_OK)
    kw[drop] = ""
    with pytest.raises(ValueError):
        R.SettingDef("k", "int", 1, **kw)


def test_english_only_text_is_not_enough():
    with pytest.raises(ValueError):
        R.SettingDef("k", "int", 1, **dict(_OK, label="limit"))


def test_risky_field_needs_risk_text():
    with pytest.raises(ValueError):
        R.SettingDef("k", "int", 1, risk="money", **_OK)
    R.SettingDef("k", "int", 1, risk="money", risk_text="調高後可核准更大的金額。", **_OK)


def test_choice_needs_label_and_impact():
    with pytest.raises(ValueError):
        R.SettingDef("k", "str", "a", choices=[("a", "甲方案", "")], **_OK)
    R.SettingDef("k", "str", "a", choices=[("a", "甲方案", "影響之後的單據。")], **_OK)


def test_group_needs_chinese_name_and_help():
    with pytest.raises(ValueError):
        R.register_group("zz_bad", "bad", [], help="說明文字。")
    assert "zz_bad" not in R._GROUPS
