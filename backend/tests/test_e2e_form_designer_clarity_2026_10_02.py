# -*- coding: utf-8 -*-
"""表單設計器的「看得懂」守門（FORM-DESIGNER-DESIGN §6 R3、§8 G-D1／G-D3）。

G-D1 清晰度：右側面板每個設定列（`.fd-row`）與每個開關（`.fd-switch`）都要有「一句說明＋例子」——文字裡有「例」或「使用者會看到」；
     每種欄位種類（含明細表欄展開、計算器各個計算器）都逐一選過。沒有說明＋例子的選項不准上畫面。
G-D3 詞彙：左／中／右畫面文字不得出現內部名詞（代碼、參照、dataClass、options、formula、locked、editableBy、optionsFrom…）；
     例外：「進階公式」這個標籤（舊文字公式的標示）、以及「進階設定」摺疊區（預設收合，內容不在可見文字裡）。
反向控制：把一個設定列的說明拿掉 ⇒ 檢查函式要抓到。
"""
import json
import re

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._builder_nav import go_step  # noqa: E402

KEY = "fd_clarity"
BANNED = re.compile(r"代碼|參照|dataClass|options|formula|locked|editableBy|optionsFrom|\bkey\b|\bref\b|json", re.I)

#: 把整個右側面板的設定列掃一遍；回傳缺說明／例子的列的文字
AUDIT_JS = """() => {
  const bad = []
  for (const r of document.querySelectorAll('.fd-right .fd-row, .fd-right .fd-switch')) {
    if (r.closest('details.fd-adv:not([open])')) continue
    const t = r.innerText || ''
    if (!/例|使用者會看到/.test(t)) bad.push(t.trim().slice(0, 60))
  }
  return bad
}"""


def _field(key, label, typ, **kw):
    f = {"key": key, "label": label, "type": typ, "dataClass": "T1"}
    f.update(kw)
    return f


def _body():
    return {"name": "清晰度測試", "icon": "", "permission": "custom." + KEY,
            "numbering": {"prefix": "FC", "date": "YYYYMMDD", "digits": 4},
            "fields": [_field("t1", "文字", "text"), _field("t2", "長文字", "textarea"), _field("n1", "數量", "number"), _field("n2", "單價", "number"),
                       _field("d1", "出發日", "date"), _field("d2", "返回日", "date"), _field("dr", "區間", "daterange"),
                       _field("s1", "選單", "select", options=["甲", "乙"]), _field("r1", "圓點", "radio", options=["甲", "乙"]),
                       _field("c1", "勾", "checkbox"), _field("u1", "人員", "ref", target="users"), _field("p1", "部門", "ref", target="departments"),
                       _field("f1", "檔案", "file"), _field("i1", "圖片", "image"), _field("fx", "計算", "formula", formula=""),
                       _field("lines", "明細", "table", minRows=0, maxRows=200, addLabel="新增一列",
                              columns=[{"key": "item", "label": "項目", "type": "text"}, {"key": "kind", "label": "類別", "type": "select", "options": ["甲"]},
                                       {"key": "qty", "label": "數量", "type": "number"}, {"key": "unitCost", "label": "單價", "type": "number"},
                                       {"key": "amount", "label": "小計", "type": "formula", "formula": "round_half_up(qty * unitCost)"}])],
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿", "final": True}], "transitions": []},
            "ui": {"form": {"groups": []}, "list": {"columns": []}}}


@pytest.fixture()
def designer(live_server, client, make_user, new_context):
    user = make_user(username="fdc_sa", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": user[0], "password": user[1]}).json()["token"]
    r = client.put("/api/definitions/custom_module/%s/draft" % KEY, json={"body": _body()}, headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200, r.text
    page = new_context(viewport={"width": 1600, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, user[0], user[1])
    page.goto("%s/pages/module-builder.html?key=%s&designer=1" % (live_server, KEY))
    page.wait_for_selector("#mb-step-1", state="visible")
    go_step(page, 2)
    page.wait_for_selector(".fd .fd-paper", state="visible", timeout=20000)
    page.errors = errors
    return page


def _visible_text(page):
    return page.inner_text(".fd").replace("進階公式", "")


@pytest.mark.e2e
def test_every_field_kind_and_calculator_has_a_one_liner_and_an_example_on_every_setting(designer):
    page = designer
    for key in ("t1", "t2", "n1", "d1", "dr", "s1", "r1", "c1", "u1", "p1", "f1", "i1", "fx", "lines"):
        page.click('.fd-fld[data-key="%s"]' % key)
        page.wait_for_selector('.fd-right [data-fd="label"]')
        assert page.evaluate(AUDIT_JS) == [], key
        assert not BANNED.search(_visible_text(page)), (key, BANNED.search(_visible_text(page)).group(0))
    # 自動計算：每個計算器都選一遍（含各自的參數列）
    page.click('.fd-fld[data-key="fx"]')
    for calc in ("sumtable", "sum", "tax", "mul", "pct", "sub", "days"):
        page.click('.fd-right input[data-fd="calc"][value="%s"]' % calc)
        page.wait_for_selector('.fd-right .fd-box--in')
        assert page.evaluate(AUDIT_JS) == [], calc
        assert not BANNED.search(_visible_text(page)), calc
    # 稅額計算的各個分支（含稅拆稅、自己填稅率）
    page.click('.fd-right input[data-fd="calc"][value="tax"]')
    page.select_option('.fd-right [data-fd="cpMode"]', "split")
    page.select_option('.fd-right [data-fd="cpRate"]', "custom")
    assert page.evaluate(AUDIT_JS) == []
    # 明細表：展開每一欄（選單欄、數字欄、自動計算欄）
    page.click('.fd-fld[data-key="lines"]')
    for i in range(5):
        page.click('.fd-right [data-col-open="%d"]' % i)
        assert page.evaluate(AUDIT_JS) == [], "明細欄 %d" % i
        assert not BANNED.search(_visible_text(page)), "明細欄 %d" % i
    assert not page.errors, page.errors


@pytest.mark.e2e
def test_every_left_palette_tile_has_a_plain_name_and_a_one_liner(designer):
    page = designer
    tiles = page.evaluate("() => [...document.querySelectorAll('.fd-left .fd-tile')].map(t => [t.querySelector('b').textContent.trim(), t.querySelector('small').textContent.trim()])")
    assert len(tiles) >= 12, tiles
    for name, desc in tiles:
        assert name and desc, (name, desc)
        assert not BANNED.search(name + desc), (name, desc)


@pytest.mark.e2e
def test_the_audit_catches_a_setting_without_an_example_reverse_control(designer):
    page = designer
    page.click('.fd-fld[data-key="t1"]')
    page.wait_for_selector('.fd-right [data-fd="label"]')
    assert page.evaluate(AUDIT_JS) == []
    page.evaluate("() => { const r = document.querySelector('.fd-right .fd-row'); r.querySelectorAll('.fd-why').forEach(n => n.remove()) }")
    assert page.evaluate(AUDIT_JS) != [], "拿掉說明與例子後檢查要抓到"
