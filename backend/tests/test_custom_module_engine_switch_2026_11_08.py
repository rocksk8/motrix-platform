# -*- coding: utf-8 -*-
"""P8 自訂模組引擎總開關（`builder_custom_modules.enabled`，預設 0＝關；T78）。

關著只擋「建立」（這個 key 還沒有任何已發布版本的 custom_module：存草稿／發布／還原／核可送審版本）→ 403；
已發布模組的既有單據、查詢，以及它自己的草稿／發布完全不受影響。開著＝與過去相同。前端：關著隱藏建立入口（見 test_e2e 版本）。
測試環境預設把開關的預設值開起來（conftest），所以這個檔每題標 `custom_switch_default` 回到正式預設，再明確發布 0／1。
"""
import re
from pathlib import Path

import pytest

import db
from core import source_tree
from helpers import settings_registry as SR

pytestmark = pytest.mark.custom_switch_default

KEY, NEW = "swold", "swnew"


def _login(client, make_user, name, role="superadmin"):
    u, p = make_user(name, "Custom-Pass-123", role=role)[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _flag(on):
    c = db.get_db()
    try:
        SR.publish("builder_custom_modules", {"enabled": 1 if on else 0}, reason="t78", user="t78", conn=c)
        c.commit()
    finally:
        c.close()


def _body(key, name="開關測試"):
    f = lambda k, l, t, **kw: dict({"key": k, "label": l, "type": t, "dataClass": "T1"}, **kw)
    return {"name": name, "permission": "custom." + key, "numbering": {"prefix": "SW", "period": "none", "digits": 3},
            "fields": [f("title", "標題", "text", required=True)],
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿"}, {"key": "done", "label": "完成", "final": True}],
                         "transitions": [{"key": "submit", "label": "送出", "from": "draft", "to": "done"}]}}


def _draft(client, h, key, **kw):
    return client.put("/api/definitions/custom_module/%s/draft" % key, headers=h, json={"body": _body(key, **kw)})


def _publish(client, h, key):
    return client.post("/api/definitions/custom_module/%s/publish" % key, headers=h, json={})


@pytest.fixture()
def boss(client, make_user):
    return _login(client, make_user, "sw_boss")


def test_default_is_off_in_production_defaults(client):
    c = db.get_db()
    try:
        from helpers.settings_strict import strict_value
        assert strict_value(c, "builder_custom_modules", "enabled") == 0
    finally:
        c.close()
    f = SR._g("builder_custom_modules")["fields"]["enabled"]
    assert f.default == 0


def test_off_blocks_creating_a_new_module_draft_and_publish_and_restore(client, boss):
    _flag(False)
    r = _draft(client, boss, NEW)
    assert r.status_code == 403 and "尚未開放建立" in r.text, r.text[:200]
    assert _publish(client, boss, NEW).status_code == 403
    assert client.post("/api/definitions/custom_module/%s/restore/1" % NEW, headers=boss, json={}).status_code == 403
    c = db.get_db()
    try:
        assert c.execute("SELECT COUNT(*) FROM ui_definitions WHERE kind='custom_module' AND key=?", (NEW,)).fetchone()[0] == 0     # 什麼都沒寫進去
    finally:
        c.close()


def test_off_blocks_publishing_a_never_published_draft_that_existed_before(client, boss):
    """開著時存好草稿、之後關掉：從未發布過的草稿不能靠『發布』變成新模組。"""
    _flag(True)
    assert _draft(client, boss, NEW).status_code == 200
    _flag(False)
    assert _publish(client, boss, NEW).status_code == 403
    _flag(True)
    assert _publish(client, boss, NEW).status_code == 200                    # 開回來照舊可發布


def test_on_allows_creating_as_before(client, boss):
    _flag(True)
    r = _draft(client, boss, NEW)
    assert r.status_code == 200 and r.json().get("problems") == [], r.text[:200]
    assert _publish(client, boss, NEW).status_code == 200


def test_off_does_not_touch_published_modules_or_their_records(client, boss):
    _flag(True)
    assert _draft(client, boss, KEY).status_code == 200 and _publish(client, boss, KEY).status_code == 200
    rec = client.post("/api/custom/%s/records" % KEY, headers=boss, json={"values": {"title": "舊單"}})
    assert rec.status_code == 200, rec.text
    no = rec.json()["record_no"]
    _flag(False)
    # 既有單據：讀、列表、新增單據照舊
    assert client.get("/api/custom/%s/records" % KEY, headers=boss).status_code == 200
    assert client.get("/api/custom/%s/records/%s" % (KEY, no), headers=boss).status_code == 200
    assert client.post("/api/custom/%s/records" % KEY, headers=boss, json={"values": {"title": "關閉後新單"}}).status_code == 200
    # 已發布模組自己的草稿與新版本發布照舊（關閉不是下架）
    assert _draft(client, boss, KEY, name="改名").status_code == 200
    assert _publish(client, boss, KEY).status_code == 200
    assert client.get("/api/definitions/custom_module/%s" % KEY, headers=boss).json()["latest"]["version"] == 2
    # 但另開新的 key 仍被擋
    assert _draft(client, boss, NEW).status_code == 403


def test_off_blocks_approving_a_submitted_version_of_a_never_published_module(client, boss):
    """核可送審版本的路徑也不能變成建立新模組的後門（沒有已發布版本 ⇒ 403，在任何審核判斷之前）。"""
    _flag(False)
    r = client.post("/api/custom-modules/%s/definition/1/approve" % NEW, headers=boss, json={})
    assert r.status_code == 403, r.text[:200]


def test_unreadable_switch_fails_closed_with_503(client, boss, monkeypatch):
    _flag(False)
    import helpers.settings_strict as ss

    def _boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(ss, "strict_value", _boom)
    assert _draft(client, boss, NEW).status_code == 503


def test_non_custom_module_kinds_and_other_roles_unaffected(client, boss, make_user):
    _flag(False)
    other = _login(client, make_user, "sw_user", role="user")
    assert client.put("/api/definitions/custom_module/%s/draft" % NEW, headers=other, json={"body": _body(NEW)}).status_code in (401, 403)   # 非最高管理者本來就不行（不是開關造成）


# ── 前端：關著隱藏建立入口（靜態＋行為合約；瀏覽器版見 test_e2e_custom_module_engine_switch）──

_ROOT = Path(__file__).resolve().parents[2] / "frontend"


def test_module_builder_page_hides_create_entry_when_flag_off_static_contract():
    html = source_tree.page_file("module-builder.html").read_text(encoding="utf-8")
    core = (_ROOT / "js" / "module-builder-core.js").read_text(encoding="utf-8")
    assert "public-flags.js" in html                                                           # 旗標讀取器有載入
    assert re.search(r'x-show="createOn"[^>]*data-testid="mb-create-row"', html)                 # 建立列只在開著時顯示
    assert 'data-testid="mb-create-off"' in html and 'x-show="!createOn"' in html                # 關著時顯示說明
    assert "builder_custom_modules" in core and "createOn" in core
    assert re.search(r"if \(!this\.createOn\) \{ this\.keyErr", core)                           # 即使直接帶 ?key= 也不進範本挑選
    # 既有模組清單的『開啟』不受開關影響
    assert ':data-open-module="m.key" @click="openKey(m.key)"' in html
