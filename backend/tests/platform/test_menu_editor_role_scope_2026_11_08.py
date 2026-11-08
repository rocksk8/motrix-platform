# -*- coding: utf-8 -*-
"""T78 選單編輯器（menu-editor.js）的角色層：node 以假 DOM／假 fetch 驅動真正的檔案。

- 公司層：四處呼叫的 scope 仍是 company、預覽請求不帶 scope（與過去逐位元相同）
- 角色層：角色層還沒有 ⇒ 以『現行公司層』為起頭（copied）；發布只送有改動的模組；四處呼叫都帶 scope=role%3A<角色>；預覽帶 scope＋該角色的在職帳號
- 讀不到角色層 ⇒ 整個讀取失敗（不可把空的當起頭：角色層會整份取代公司層）
- 切換範圍有未發布調整時要確認；取消就留在原範圍
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

EDITOR = Path(__file__).resolve().parents[3] / "frontend" / "static" / "menu-editor.js"
NODE = shutil.which("node")

_HARNESS = r"""
const fs = require('fs')
function mk() { return { firstChild: {}, setAttribute() {}, appendChild() {}, addEventListener() {}, remove() {}, querySelector() { return null }, textContent: '', style: {} } }
global.document = { createElement: mk, getElementById: () => null, head: mk(), body: mk() }
global.localStorage = { getItem: () => null }
global.window = global
let confirmAnswer = true, confirmAsked = 0
global.confirm = () => { confirmAsked++; return confirmAnswer }
const scenario = process.argv[2]
const calls = []
const COMPANY_A = [{ op: 'relabel', target: 'ma:a.html/sidebar', label: '公司名' }, { op: 'hide', target: 'ma:other.html' }]
global.fetch = async (url, opt) => {
  const m = (opt && opt.method) || 'GET'
  const body = opt && opt.body ? JSON.parse(opt.body) : undefined
  calls.push({ m, url, body })
  const ok = (j) => ({ ok: true, status: 200, json: async () => j })
  if (m === 'GET' && url === '/api/platform/menu') return ok({ groups: [{ key: 'g', label: 'G', items: [{ module: 'ma', href: 'a.html', label: 'A' }, { module: 'mb', href: 'b.html', label: 'B' }, { module: 'mc', href: 'c.html', label: 'C' }] }] })
  if (m === 'GET' && url === '/api/settings/role-labels') return ok({ admin: '管理員', sales: '業務' })
  if (m === 'GET' && url === '/api/definitions/layout') return ok([{ key: 'module:mb', scope: 'role:sales', latestVersion: 2, hasDraft: false }, { key: 'module:mb', scope: 'company', latestVersion: 1 }])
  if (m === 'GET' && url === '/api/users') return ok([{ username: 'ad_off', role: 'admin', active: 0 }, { username: 'ad1', role: 'admin', active: 1, displayName: '小管' }, { username: 'sl1', role: 'sales', active: 1 }])
  if (m === 'GET' && url.indexOf('/api/definitions/layout/module:ma?scope=company') === 0) return ok({ draft: null, latest: { body: { ops: COMPANY_A } } })
  if (m === 'GET' && url.indexOf('/api/definitions/layout/module:mb?scope=company') === 0) return ok({ draft: null, latest: { body: { ops: [] } } })
  if (m === 'GET' && url.indexOf('/api/definitions/layout/module:ma?scope=role%3Aadmin') === 0) {
    if (scenario === 'role_read_fails') return { ok: false, status: 500, json: async () => ({ detail: '壞了' }) }
    return ok({ draft: null, latest: null })                       // admin 在 ma 還沒有角色層
  }
  if (m === 'GET' && url.indexOf('/api/definitions/layout/module:mb?scope=role%3Aadmin') === 0) return ok({ draft: null, latest: { body: { ops: [{ op: 'hide', target: 'mb:b.html/sidebar' }] } } })   // admin 在 mb 已有角色層
  if (m === 'PUT') return ok({ etag: 'e1' })
  if (m === 'POST' && /publish/.test(url)) return ok({ version: 3 })
  if (m === 'POST' && url === '/api/platform/menu/preview') return ok({ user: (body && body.user) || 'me', role: 'admin', current: [], preview: [], skipped: [] })
  return ok({})
}
eval(fs.readFileSync(process.argv[1], 'utf8'))
const E = window.MotrixMenuEditor, st = E._state
const A = 'ma:a.html/sidebar', B = 'mb:b.html/sidebar'
const out = (x) => console.log(JSON.stringify(Object.assign({ calls: calls.map(c => c.m + ' ' + c.url) }, x)))
;(async () => {
  await E.open()
  if (scenario === 'company') {
    st.work[A].label = '新A'; st.touched = true
    await E._preview()
    const pv = calls.filter(c => c.url === '/api/platform/menu/preview')[0]
    await E._publish()
    await new Promise(r => setTimeout(r, 30))
    out({ previewBody: pv.body, writes: calls.filter(c => c.m !== 'GET' && c.url !== '/api/platform/menu/preview').map(c => c.m + ' ' + c.url), msg: st.msg })
  } else if (scenario === 'role' || scenario === 'role_read_fails') {
    await E._switchScope('role:admin')
    if (scenario === 'role_read_fails') return out({ msg: st.msg, bad: st.msgBad, scope: st.scope })
    const snap = { copiedMa: st.mods.ma.copied, copiedMb: st.mods.mb.copied, workA: st.work[A].label, hiddenB: st.work[B].hidden, who: st.who, roles: st.roles.map(r => r.key), layers: Object.keys(st.roleLayers) }
    st.work[A].label = '管理員名'; st.touched = true
    await E._preview()
    const pv = calls.filter(c => c.url === '/api/platform/menu/preview')[0]
    await E._publish()
    await new Promise(r => setTimeout(r, 30))
    out({ snap, previewBody: pv.body, writes: calls.filter(c => c.m !== 'GET').filter(c => c.url !== '/api/platform/menu/preview').map(c => ({ m: c.m, url: c.url, ops: c.body && c.body.body && c.body.body.ops })), msg: st.msg, scopeAfter: st.scope })
  } else if (scenario === 'will_publish') {
    await E._switchScope('role:admin')
    const none = E._willPublish()
    st.work[A].label = '只改名'
    const renameOnly = E._willPublish()
    st.work[A].label = 'A'
    const g = st.order.g; const i = g.indexOf(A); g.splice(i, 1); g.splice(i + 1, 0, A)      // 只把 A 往下移一格
    const moved = E._willPublish()
    out({ none, renameOnly, moved })
  } else if (scenario === 'switch_confirm') {
    st.work[A].label = '改了'; st.touched = true
    confirmAnswer = false
    await E._switchScope('role:admin')
    const stayed = st.scope
    confirmAnswer = true
    await E._switchScope('role:admin')
    out({ stayed, now: st.scope, asked: confirmAsked, touchedAfter: st.touched })
  } else if (scenario === 'role_no_user') {
    await E._switchScope('role:sales')                             // sl1 在職 ⇒ 有帳號；改選沒有帳號的角色
    await E._switchScope('role:viewer')
    st.touched = true; await E._preview()
    out({ who: st.who, msg: st.msg, bad: st.msgBad, previews: calls.filter(c => c.url === '/api/platform/menu/preview').length })
  }
})().catch(e => { console.error(String(e && e.stack || e)); process.exit(1) })
"""


def _run(scenario):
    out = subprocess.run([NODE, "-e", _HARNESS, str(EDITOR), scenario], capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    return json.loads(out.stdout.decode("utf-8"))


pytestmark = pytest.mark.skipif(NODE is None, reason="沒有 node")


def test_company_scope_requests_are_unchanged():
    r = _run("company")
    assert "scope" not in r["previewBody"], "公司層預覽請求不帶 scope（與過去逐位元相同）"
    assert "GET /api/definitions/layout/module:ma?scope=company" in r["calls"]
    assert r["writes"] == ["PUT /api/definitions/layout/module:ma/draft?scope=company", "POST /api/definitions/layout/module:ma/publish?scope=company"], "只送有改動的 ma"
    assert r["msg"].startswith("已發布（1 個模組的版面）。重新整理頁面即可看到新的側欄。"), r["msg"]


def test_role_scope_starts_from_company_layer_and_publishes_only_changed_modules():
    r = _run("role")
    s = r["snap"]
    assert s["copiedMa"] is True and s["copiedMb"] is False, "ma 沒有 admin 角色層 ⇒ 以公司層起頭；mb 已有角色層 ⇒ 用它自己的"
    assert s["workA"] == "公司名" and s["hiddenB"] is True, "工作副本＝起頭的那一層（角色層自己的 hide 也要帶出來）"
    assert s["who"] == "ad1", "預覽身分＝該角色的在職帳號（略過停用的 ad_off、別的角色的 sl1）"
    assert "admin" in s["roles"] and s["layers"] == ["sales"], "有角色層的角色會被標出來"
    assert r["previewBody"]["scope"] == "role:admin" and r["previewBody"]["user"] == "ad1"
    w = r["writes"]
    assert [x["m"] + " " + x["url"] for x in w] == ["PUT /api/definitions/layout/module:ma/draft?scope=role%3Aadmin",
                                                    "POST /api/definitions/layout/module:ma/publish?scope=role%3Aadmin"], "mb 沒動 ⇒ 不建立／不改它的角色層"
    ops = w[0]["ops"]
    assert {"op": "relabel", "target": "ma:a.html/sidebar", "label": "管理員名"} in ops
    assert {"op": "hide", "target": "ma:other.html"} in ops, "公司層在 ma 的其他（非側欄）操作要一併帶進角色層，否則角色層一發布就整份取代、這些操作會消失"
    assert "角色「管理員」的角色層" in r["msg"] or "管理員的角色層" in r["msg"], r["msg"]


def test_role_layer_read_failure_aborts_instead_of_starting_from_empty():
    r = _run("role_read_fails")
    assert r["bad"] is True and r["msg"].startswith("讀取失敗"), r


def test_will_publish_lists_the_modules_that_get_a_role_layer():
    """K 審建議修：『沒動的模組不建層』只在群組順序沒被改時成立——調整群組內順序，同群組所有模組都會建立角色層。
    面板用 willPublish() 在發布前列出將寫入的模組（與 doPublish 同一個判準）；只改名只列被改的那一個。"""
    r = _run("will_publish")
    assert r["none"] == [] and r["renameOnly"] == ["ma"]
    assert sorted(r["moved"]) == ["ma", "mb", "mc"], "移動順序 ⇒ 同群組的模組都要發 move（位置式），所以都會建立／更新角色層"


def test_switching_scope_with_unpublished_edits_asks_first():
    r = _run("switch_confirm")
    assert r["stayed"] == "company" and r["now"] == "role:admin" and r["asked"] == 2 and r["touchedAfter"] is False


def test_role_without_active_user_cannot_preview():
    r = _run("role_no_user")
    assert r["who"] == "" and r["bad"] is True and "在職帳號" in r["msg"] and r["previews"] == 0, r
