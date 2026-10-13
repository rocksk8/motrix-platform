# -*- coding: utf-8 -*-
"""BP-1 治理面板的前端證據（node 直接執行 def-governance.js 與兩個編輯器的零件，不開瀏覽器；沒有真瀏覽器可用，這組測試就是證據）。
- 旗標關（available 回 false）：govOn 維持 false、頁面上的入口都以 x-show="govOn" 把關、面板元件不會自己出現
- 旗標開：帳本／差異／影響預覽都渲染；唯讀面板不出現還原；非唯讀的還原要兩段確認，確認後才以『正確的版本』呼叫既有還原路由
- 現行驗證器不接受的舊版：不給還原按鈕、說明原因；放寬警示文字一定顯示
- 兩個編輯器的 openGov 以正確的 kind／key／scope／tab／readonly 開面板"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core import source_tree

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "frontend" / "js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="需要 node")

PANEL_HARNESS = r"""
const fs = require('fs')
const inp = JSON.parse(process.argv[2])
const els = {}
function mk(tag) { return { tag, id: '', attrs: {}, innerHTML: '', listeners: {}, setAttribute(k, v) { this.attrs[k] = v }, getAttribute(k) { return this.attrs[k] },
  addEventListener(t, f) { this.listeners[t] = f }, remove() { delete els[this.id] }, appendChild(c) { els[c.id] = c } } }
global.window = {}
global.localStorage = { getItem: () => JSON.stringify({ token: 'tok' }) }
global.document = { createElement: mk, getElementById: (i) => els[i] || null, head: { appendChild(c) { els[c.id] = c } }, body: { appendChild(c) { els[c.id] = c } } }
const calls = []
global.fetch = async (url, o) => {
  calls.push({ url, method: (o && o.method) || 'GET', body: o && o.body, auth: o && o.headers && o.headers.Authorization })
  const route = Object.keys(inp.routes).find(k => url.indexOf(k) >= 0)
  const r = inp.routes[route] || { status: 404, body: {} }
  return { ok: r.status < 400, status: r.status, json: async () => r.body }
}
global.window.confirm = global.confirm = () => { throw new Error('native confirm used') }
;(0, eval)(fs.readFileSync(process.argv[3], 'utf8'))
const G = window.MotrixDefGovernance
const click = (act) => els['dg-panel'].listeners.click({ target: { closest: () => ({ getAttribute: () => act }) } })
;(async () => {
  const out = {}
  for (const step of inp.steps) {
    if (step.do === 'available') out['available_' + step.kind] = await G.available(step.kind)
    if (step.do === 'open') { await G.open(step.opts); out.html = els['dg-panel'].innerHTML }
    if (step.do === 'click') { await click(step.act); out.html = els['dg-panel'] ? els['dg-panel'].innerHTML : '' }
    if (step.do === 'panel') out.panelExists = !!els['dg-panel']
  }
  out.calls = calls; out.restoredArg = global.__restored || null
  console.log(JSON.stringify(out))
})()
"""

LEDGER = {"status": 200, "body": {"live": 3, "hasDraft": True, "pendingReview": False, "warnings": ["還原不會判斷這一版比現在寬鬆還是嚴格"],
          "versions": [{"version": 3, "status": "published", "note": "", "by": "u", "at": "t", "isLive": True, "restorable": False, "validNow": None},
                       {"version": 2, "status": "published", "note": "第二版", "by": "u", "at": "t", "isLive": False, "restorable": True, "validNow": True},
                       {"version": 1, "status": "published", "note": "", "by": "u", "at": "t", "isLive": False, "restorable": True, "validNow": False}]}}
DIFF = {"status": 200, "body": {"a": "2", "b": "live", "changes": [{"op": "change", "path": "fields[0].label", "old": "<b>舊</b>", "new": "新"}]}}
IMPACT = {"status": 200, "body": {"hasDraft": True, "liveVersion": 3, "nextVersion": 4, "changeCount": 1, "changes": [{"op": "add", "path": "x", "new": 1}],
          "validation": {"ok": False, "problems": [{"path": "fields[0]", "message": "壞了"}]}, "otherScopes": [{"scope": "role:admin", "latestVersion": 1}],
          "declared": {"screens": "報價單表單", "customerVisible": False, "roleOverridesPresent": True}, "frozenRecords": 7, "note": "n"}}
RESTORE_OK = {"status": 200, "body": {"version": 4}}


def _panel(steps, routes=None):
    r = dict(routes or {})                                                      # 較具體的覆寫路由放前面（harness 取第一個符合的）
    for k, v in (("/ledger", LEDGER), ("/diff", DIFF), ("/impact", IMPACT), ("/restore/", RESTORE_OK)):
        r.setdefault(k, v)
    out = subprocess.run([NODE, "-e", PANEL_HARNESS, "x", json.dumps({"steps": steps, "routes": r}), str(JS / "def-governance.js")],
                         capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@needs_node
@pytest.mark.parametrize("status,expected", [(404, False), (401, False), (403, False), (400, True), (200, True)])
def test_available_is_false_when_the_flag_is_off_or_not_allowed(status, expected):
    """旗標關＝後端 404；未登入／非最高管理者＝401／403 ⇒ 編輯器不顯示入口。開啟後以不存在的 key 探測會得到 400（通過把關）。"""
    r = _panel([{"do": "available", "kind": "expense_type"}], {"/_probe/": {"status": status, "body": {}}})
    assert r["available_expense_type"] is expected
    assert "/api/def-governance/expense_type/_probe/ledger" in r["calls"][0]["url"] and r["calls"][0]["auth"] == "Bearer tok"
    assert r["calls"][0]["method"] == "GET"                                    # 探測只讀


@needs_node
def test_nothing_is_rendered_until_open_is_called():
    r = _panel([{"do": "panel"}])
    assert r["panelExists"] is False and r["calls"] == []


@needs_node
def test_panel_renders_ledger_warning_and_diff_and_impact_without_native_dialogs():
    r = _panel([{"do": "open", "opts": {"kind": "layout", "key": "module:a", "readonly": True}},
                {"do": "click", "act": "cmp:2"}])
    assert "還原不會判斷這一版比現在寬鬆還是嚴格" in r["html"] and "目前生效：第 3 版" in r["html"]      # 警示一定顯示
    assert "&lt;b&gt;舊&lt;/b&gt;" in r["html"] and "<b>舊</b>" not in r["html"]                    # 差異內容轉義
    assert "/diff?scope=company&a=2&b=live" in r["calls"][-1]["url"]
    r2 = _panel([{"do": "open", "opts": {"kind": "expense_type", "key": "travel", "tab": "impact", "readonly": True}}])
    assert "共 1 處變更" in r2["html"] and "<b>7</b> 張單據凍結在生效中的第 3 版" in r2["html"] and "驗證不通過" in r2["html"] and "role:admin 第 1 版" in r2["html"]
    assert "/api/def-governance/expense_type/travel/impact?scope=company" in r2["calls"][0]["url"]


@needs_node
def test_readonly_panel_has_no_restore_and_invalid_old_version_cannot_be_restored():
    ro = _panel([{"do": "open", "opts": {"kind": "layout", "key": "module:a", "readonly": True}}])
    assert 'data-dg="restore:' not in ro["html"]
    rw = _panel([{"do": "open", "opts": {"kind": "layout", "key": "module:a"}}])
    assert 'data-dg="restore:2"' in rw["html"]                                          # 第 2 版現行驗證通過 ⇒ 可還原
    assert 'data-dg="restore:1"' not in rw["html"] and "現行驗證不通過，無法還原" in rw["html"]  # 第 1 版現行驗證不過 ⇒ 沒有按鈕、說明原因


@needs_node
def test_restore_needs_two_clicks_then_posts_the_right_version_to_the_existing_route():
    r = _panel([{"do": "open", "opts": {"kind": "output_template", "key": "k1", "scope": "role:admin"}},
                {"do": "click", "act": "restore:2"}])
    assert 'data-dg="restore-yes:2"' in r["html"] and 'data-dg="restore-no"' in r["html"]
    assert not [c for c in r["calls"] if c["method"] == "POST"]                         # 第一下只是確認，沒有送出
    r = _panel([{"do": "open", "opts": {"kind": "output_template", "key": "k1", "scope": "role:admin"}},
                {"do": "click", "act": "restore:2"}, {"do": "click", "act": "restore-no"}])
    assert not [c for c in r["calls"] if c["method"] == "POST"] and 'data-dg="restore:2"' in r["html"]
    r = _panel([{"do": "open", "opts": {"kind": "output_template", "key": "k1", "scope": "role:admin"}},
                {"do": "click", "act": "restore:2"}, {"do": "click", "act": "restore-yes:2"}])
    posts = [c for c in r["calls"] if c["method"] == "POST"]
    assert len(posts) == 1
    assert posts[0]["url"] == "/api/definitions/output_template/k1/restore/2?scope=role%3Aadmin"   # 既有還原路由、正確的版本與範圍
    assert json.loads(posts[0]["body"]) == {"note": "還原第 2 版"}
    assert r["calls"][-1]["url"].startswith("/api/def-governance/output_template/k1/ledger")          # 還原後重新讀帳本


@needs_node
def test_failed_restore_shows_the_server_reason_and_does_not_claim_success():
    r = _panel([{"do": "open", "opts": {"kind": "layout", "key": "module:a"}}, {"do": "click", "act": "restore:2"}, {"do": "click", "act": "restore-yes:2"}],
               {"/restore/": {"status": 422, "body": {"detail": "第 2 版在目前的環境驗證不通過，無法還原", "problems": [{"message": "欄位不存在"}]}}})
    assert "無法還原：欄位不存在" in r["html"] or "驗證不通過，無法還原：欄位不存在" in r["html"]


# ── 兩個編輯器的入口 ────────────────────────────────────────────────────────────
EDITOR_HARNESS = r"""
const fs = require('fs')
const inp = JSON.parse(process.argv[2])
global.window = { MotrixFormPreview: null }
global.localStorage = { getItem: () => '{}' }
global.document = { addEventListener() {}, querySelector() { return null }, getElementById() { return null } }
const opened = []
if (inp.stub) window.MotrixDefGovernance = { available: async () => false, open: (o) => opened.push(o) }
for (const f of process.argv.slice(3)) (0, eval)(fs.readFileSync(f, 'utf8'))
let page
if (inp.which === 'et') page = expenseTypesPage()
else if (inp.which === 'rk') page = remitKindsPage()
else { page = moduleBuilderPage() }
page.key = 'k1'
const out = { govOn: page.govOn }
page.openGov('impact'); out.opened = opened
console.log(JSON.stringify(out))
"""


def _editor(which, files, stub=True):
    out = subprocess.run([NODE, "-e", EDITOR_HARNESS, "x", json.dumps({"which": which, "stub": stub})] + [str(JS / f) for f in files],
                         capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@needs_node
def test_expense_type_editor_entry_is_off_by_default_and_opens_the_read_only_panel_with_the_right_args():
    r = _editor("et", ["expense-types.js"])
    assert r["govOn"] is False                                                           # 沒有探測成功之前（旗標關＝永遠）不顯示
    assert r["opened"] == [{"kind": "expense_type", "key": "k1", "scope": "company", "title": "費用單據類型：k1", "tab": "impact", "readonly": True}]


@needs_node
def test_remit_kinds_editor_entry_is_off_by_default_and_opens_the_read_only_panel_with_the_right_args():
    r = _editor("rk", ["remit-kinds-settings.js"])
    assert r["govOn"] is False
    assert r["opened"] == [{"kind": "remit_kinds", "key": "default", "scope": "company", "title": "匯款款別", "tab": "impact", "readonly": True}]
    assert _editor("rk", ["remit-kinds-settings.js"], stub=False)["opened"] == []


@needs_node
def test_module_builder_entry_is_off_by_default_and_opens_the_read_only_panel_with_the_right_args():
    r = _editor("mb", ["module-builder-consts.js", "module-builder-core.js", "module-builder-output.js"])
    assert r["govOn"] is False
    assert r["opened"] == [{"kind": "custom_module", "key": "k1", "scope": "company", "title": "自訂模組：k1", "tab": "impact", "readonly": True}]


@needs_node
def test_editors_do_not_fail_when_the_panel_script_is_missing():
    assert _editor("et", ["expense-types.js"], stub=False)["opened"] == []
    assert _editor("mb", ["module-builder-consts.js", "module-builder-core.js", "module-builder-output.js"], stub=False)["opened"] == []


def test_page_entries_are_gated_by_govon_and_load_the_panel_script():
    for page, ids in (("expense-types.html", ("et-gov-impact", "et-gov-ledger")), ("remit-kinds-settings.html", ("rk-gov-impact", "rk-gov-ledger")), ("module-builder.html", ("mb-gov-impact", "mb-gov-ledger"))):
        html = source_tree.page_file(page).read_text(encoding="utf-8")
        for i in ids:
            m = re.search(r'<button[^>]*(?:id|data-testid)="%s"[^>]*>' % i, html)
            assert m and 'x-show="govOn' in m.group(0), (page, i)                         # 入口一律由 govOn 把關（關＝不顯示）
        assert '<script src="../js/def-governance.js"></script>' in html
