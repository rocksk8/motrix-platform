# -*- coding: utf-8 -*-
"""public-flags.js：一次讀多個公開設定群組；某個群組讀不到（hidden／未登錄 404、敏感 403）不拖垮其他旗標。
node 真的執行 + 真的端點（GET /api/settings-center/public 對 hidden 群組整個回 404 是既有行為，這裡鎖住不變）。"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
JS = ROOT / "frontend" / "static" / "public-flags.js"
NODE = shutil.which("node")

HARNESS = r"""
const fs = require('fs')
global.window = global
global.localStorage = { getItem() { return JSON.stringify({ token: 'tk' }) } }
const urls = []
const GOOD = { builder_layout: { suppliers: true }, builder_custom_fields: { enabled: true }, builder_actions: { enabled: false } }
let BAD = JSON.parse(process.argv[2])        // 讓哪些群組讀不到
global.fetch = async (url) => {
  urls.push(String(url))
  const names = String(url).split('groups=')[1].split(',')
  if (names.some(n => BAD.includes(n))) return { ok: false, status: 404, json: async () => ({}) }
  const groups = {}; names.forEach(n => { groups[n] = GOOD[n] })
  return { ok: true, status: 200, json: async () => ({ groups }) }
}
eval(fs.readFileSync(process.argv[1], 'utf8'))
;(async () => {
  const out = await window.MotrixPublicFlags.read(['builder_layout', 'builder_custom_fields', 'builder_actions'])
  console.log(JSON.stringify({ out, urls }))
})()
"""


def _run(bad):
    r = subprocess.run([NODE, "-e", HARNESS, str(JS), json.dumps(bad)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not NODE, reason="沒有 node")
def test_all_readable_is_one_request_with_the_same_url_as_before():
    r = _run([])
    assert r["urls"] == ["/api/settings-center/public?groups=builder_layout,builder_custom_fields,builder_actions"]
    assert r["out"]["builder_layout"] == {"suppliers": True}


@pytest.mark.skipif(not NODE, reason="沒有 node")
def test_one_unreadable_group_does_not_kill_the_others():
    r = _run(["builder_actions"])
    assert r["out"] == {"builder_layout": {"suppliers": True}, "builder_custom_fields": {"enabled": True}}   # 版面旗標仍讀得到
    assert len(r["urls"]) == 1 + 3                       # 合併請求失敗 ⇒ 逐組各一個
    r = _run(["builder_layout", "builder_custom_fields", "builder_actions"])
    assert r["out"] == {}                                # 全部讀不到 ⇒ 空物件（呼叫端當旗標關閉），不丟例外


def test_endpoint_keeps_its_strict_behaviour_for_existing_callers(client, make_user):
    """端點本身不變：群組不存在 ⇒ 整個 404（既有行為，頁面自己做逐組退路）；存在的群組照回。"""
    u, p = make_user(username="pf_sales", role="sales")
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    assert client.get("/api/settings-center/public?groups=builder_layout", headers=h).status_code == 200
    assert client.get("/api/settings-center/public?groups=builder_layout,no_such_group", headers=h).status_code == 404
    both = client.get("/api/settings-center/public?groups=builder_layout,builder_custom_fields,builder_actions", headers=h)
    assert both.status_code == 200 and set(both.json()["groups"]) == {"builder_layout", "builder_custom_fields", "builder_actions"}


# ── T87：暫時性失敗要重試、重試後仍失敗要讓使用者看得到（c2_personal_prefs 偶發的產品面）────────────────────

HARNESS_TRANSIENT = r"""
const fs = require('fs')
global.window = global
global.localStorage = { getItem() { return JSON.stringify({ token: 'tk' }) } }
const mode = process.argv[2]            // throw | 503 | 429 | 404
const failFirst = parseInt(process.argv[3], 10)     // 前幾次請求失敗（99＝一直失敗）
let calls = 0
const toasts = [], events = []
window.MotrixUI = { toast: (m, o) => toasts.push([m, o]) }
window.dispatchEvent = (e) => events.push(e.type)
global.fetch = async (url) => {
  calls++
  if (calls <= failFirst) {
    if (mode === 'throw') throw new Error('aborted')
    return { ok: false, status: parseInt(mode, 10), json: async () => ({}) }
  }
  return { ok: true, status: 200, json: async () => ({ groups: { list_view: { cases_personal_page_size: 1 } } }) }
}
eval(fs.readFileSync(process.argv[1], 'utf8'))
;(async () => {
  const out = await window.MotrixPublicFlags.read(['list_view'], { timeoutMs: 50 })
  console.log(JSON.stringify({ out, calls, toasts, events, failed: window.MotrixFlagsFailed || [] }))
})()
"""


def _run_transient(mode, fail_first):
    r = subprocess.run([NODE, "-e", HARNESS_TRANSIENT, str(JS), mode, str(fail_first)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not NODE, reason="沒有 node")
@pytest.mark.parametrize("mode", ["throw", "503", "429"])
def test_transient_failures_are_retried_and_recover_without_bothering_the_user(mode):
    r = _run_transient(mode, 2)
    assert r["out"] == {"list_view": {"cases_personal_page_size": 1}} and r["calls"] == 3, "前兩次暫時性失敗、第三次成功：旗標要讀得到"
    assert r["toasts"] == [] and r["events"] == [] and r["failed"] == []


@pytest.mark.skipif(not NODE, reason="沒有 node")
@pytest.mark.parametrize("mode", ["throw", "503"])
def test_persistent_transient_failure_is_visible_not_silent(mode):
    r = _run_transient(mode, 99)
    assert r["out"] == {} and r["calls"] == 3, "最多 1+2 次；結果仍是空（呼叫端行為不變）"
    assert r["failed"] == ["list_view"] and r["events"] == ["motrix:flags-failed"]
    assert len(r["toasts"]) == 1 and "讀取失敗" in r["toasts"][0][0] and r["toasts"][0][1] == {"kind": "error"}, "使用者要看得到功能被關掉的原因"


HARNESS_HANG = r"""
const fs = require('fs')
global.window = global
global.localStorage = { getItem() { return JSON.stringify({ token: 'tk' }) } }
let calls = 0
const toasts = []
window.MotrixUI = { toast: (m, o) => toasts.push([m, o]) }
global.fetch = async (url, opt) => {            // 伺服器卡住：每個請求都拖到被 AbortController 中止
  calls++
  return await new Promise((res, rej) => { opt.signal.addEventListener('abort', () => rej(new Error('aborted'))) })
}
eval(fs.readFileSync(process.argv[1], 'utf8'))
;(async () => {
  const names = JSON.parse(process.argv[2])
  const t0 = Date.now()
  const out = await window.MotrixPublicFlags.read(names, { timeoutMs: 400, deadlineMs: 900 })
  await window.MotrixPublicFlags.read(names, { timeoutMs: 50, deadlineMs: 100 })      // 第二次呼叫：失敗清單不能重複記同一個群組
  console.log(JSON.stringify({ out, calls, ms: Date.now() - t0, toasts: toasts.length, failed: window.MotrixFlagsFailed || [] }))
})()
"""


@pytest.mark.skipif(not NODE, reason="沒有 node")
def test_a_hanging_server_is_bounded_by_the_overall_deadline_and_is_not_hit_by_a_split_stage():
    """h11 F2：重試、合併、逐組拆分三層不能乘起來——有總期限；合併請求暫時性失敗就不再逐組補打（不放大對掙扎中伺服器的負載）。"""
    r = subprocess.run([NODE, "-e", HARNESS_HANG, str(JS), json.dumps(["a", "b", "c", "d", "e", "f", "g", "h"])], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["out"] == {} and out["ms"] < 3000, "總期限 0.9 s＋第二次呼叫 0.1 s：不能因為 8 個群組乘上重試而拖長：%s" % out
    assert out["calls"] <= 6, "合併請求最多 3 次（期限內更少）＋第二次呼叫最多 3 次；不得有逐組的 8 個請求：%s" % out
    assert out["toasts"] == 1 and sorted(out["failed"]) == ["a", "b", "c", "d", "e", "f", "g", "h"], "每個群組只記一次（去重）、toast 每頁一次"


@pytest.mark.skipif(not NODE, reason="沒有 node")
def test_not_found_means_hidden_group_so_no_retry_and_no_warning():
    r = _run_transient("404", 99)
    assert r["out"] == {} and r["calls"] == 1 and r["toasts"] == [] and r["failed"] == [], "404／403＝這個群組不給你看，是設定不是故障"


# ── h11 F1：個人偏好讀取失敗 ≠ 沒有偏好——load() 回 null，頁面不開放編輯（否則存檔會把已存的偏好蓋成預設）────────────

LV_JS = ROOT / "frontend" / "static" / "list-view-prefs.js"

HARNESS_LV = r"""
const fs = require('fs')
global.window = global
global.document = {}
const mode = process.argv[2], failFirst = parseInt(process.argv[3], 10)
let calls = 0
global.fetch = async (url, opt) => {
  calls++
  if (calls <= failFirst) {
    if (mode === 'throw') throw new Error('network')
    return { ok: false, status: parseInt(mode, 10), json: async () => ({}) }
  }
  return { ok: true, status: 200, json: async () => ({ sortMode: 'view', sortDir: 'desc', customOrder: ['hide=amount', 'order=date,quoteNo', 'tab=all', 'size=50'] }) }
}
eval(fs.readFileSync(process.argv[1], 'utf8'))
;(async () => {
  const out = await window.MotrixListView.load('tk', 'case_list.view')
  console.log(JSON.stringify({ out, calls }))
})()
"""


def _run_lv(mode, fail_first):
    r = subprocess.run([NODE, "-e", HARNESS_LV, str(LV_JS), mode, str(fail_first)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not NODE, reason="沒有 node")
@pytest.mark.parametrize("mode", ["throw", "503", "401", "404"])
def test_lv_load_failure_is_null_never_default_prefs(mode):
    r = _run_lv(mode, 99)
    assert r["out"] is None, "讀取失敗必須回 null：回預設值會讓頁面以為『沒有偏好』而開放編輯，存檔就蓋掉已存的偏好"
    assert r["calls"] == (3 if mode in ("throw", "503") else 1), "暫時性失敗最多試 3 次；401／404 不重試"


@pytest.mark.skipif(not NODE, reason="沒有 node")
@pytest.mark.parametrize("mode", ["throw", "503"])
def test_lv_load_recovers_from_a_transient_failure(mode):
    r = _run_lv(mode, 2)
    assert r["calls"] == 3 and r["out"] == {"hidden": ["amount"], "order": ["date", "quoteNo"], "tab": "all", "size": 50}


def test_pages_do_not_open_the_panel_when_prefs_failed_to_load_and_save_is_single_flight():
    """兩頁的接線：load 回 null ⇒ 不設 lvReady（入口與面板都靠 lvReady 顯示）；存檔進行中按鈕停用且不重入。"""
    cm = (ROOT / "frontend" / "js" / "case-management-list.js").read_text(encoding="utf-8")
    from core import source_tree
    q = source_tree.page_file("quotations.html").read_text(encoding="utf-8")
    cmh = source_tree.page_file("case-management.html").read_text(encoding="utf-8")
    assert "const loaded = await LV.load(tk, 'case_list.view')" in cm and "if (loaded) {" in cm
    assert "const loaded = await LV.load(tk, 'quotations.view')" in q and "if (!loaded) {" in q
    for src in (cm, q):
        assert "if (this.lvSaving) return" in src and "this.lvSaving = true" in src
    for html in (cmh, q):                               # 兩顆按鈕（儲存／還原預設）都在存檔進行中停用——以標籤結構判斷，不數文字出現幾次
        btns = [b for b in re.findall(r"<button\s[^>]*>", html) if "lvSave(" in b]
        assert len(btns) == 2 and all(re.search(r':disabled="lvSaving"', b) for b in btns)


HARNESS_NOTICE = r"""
const fs = require('fs')
global.window = global
global.localStorage = { getItem() { return JSON.stringify({ token: 'tk' }) } }
const appended = [], timers = []
global.document = { body: { appendChild: (el) => { el.parentNode = global.document.body; appended.push(el) }, removeChild: (el) => { el.parentNode = null } },
  createElement: () => ({ attrs: {}, style: {}, setAttribute(k, v) { this.attrs[k] = v } }) }
const realSetTimeout = global.setTimeout
global.setTimeout = (fn, ms) => { if (ms === 6000) { timers.push(fn); return 0 } return realSetTimeout(fn, ms) }
global.fetch = async () => ({ ok: false, status: 503, json: async () => ({}) })
eval(fs.readFileSync(process.argv[1], 'utf8'))
eval(fs.readFileSync(process.argv[1], 'utf8'))          // 同一頁引入兩次：第二份不能再啟用（否則提示會出現兩次）
;(async () => {
  await window.MotrixPublicFlags.read(['list_view'], { timeoutMs: 50 })
  await window.MotrixPublicFlags.read(['list_view'], { timeoutMs: 50 })
  const first = appended[0] || null
  timers.forEach(fn => fn())
  console.log(JSON.stringify({ n: appended.length, role: first && first.attrs.role, text: first && first.textContent, gone: first && first.parentNode === null }))
})()
"""


@pytest.mark.skipif(not NODE, reason="沒有 node")
def test_without_ui_js_a_fallback_notice_node_appears_once_and_goes_away():
    """h5：public-flags.js 用到的 18 頁裡 13 頁沒載入 ui.js（含報價單清單）——提示不能只靠 MotrixUI.toast。"""
    r = subprocess.run([NODE, "-e", HARNESS_NOTICE, str(JS)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["n"] == 1, "兩次讀取失敗、同一頁引入兩次，也只能有一則提示：%s" % out
    assert out["role"] == "alert" and "讀取失敗" in out["text"] and out["gone"] is True


HARNESS_LV_SAVE = r"""
const fs = require('fs')
global.window = global
global.document = {}
const realSetTimeout = global.setTimeout
global.setTimeout = (fn, ms, ...a) => realSetTimeout(fn, ms === 10000 ? 50 : ms, ...a)          // 10 秒逾時縮成 50 ms
global.fetch = (url, opt) => new Promise((res, rej) => { if (opt && opt.signal) opt.signal.addEventListener('abort', () => rej(new Error('aborted'))) })     // 永遠不回應
eval(fs.readFileSync(process.argv[1], 'utf8'))
;(async () => {
  const t0 = Date.now()
  const ok = await window.MotrixListView.save('tk', 'case_list.view', window.MotrixListView.empty())
  console.log(JSON.stringify({ ok, fast: Date.now() - t0 < 5000 }))
})()
"""


@pytest.mark.skipif(not NODE, reason="沒有 node")
def test_lv_save_that_never_answers_gives_up_and_returns_false():
    """h11：存檔期間按鈕停用；PUT 掛住不能讓它們永遠停用 ⇒ save() 逾時（10 秒）就中止並回 false（頁面顯示儲存失敗、按鈕恢復）。"""
    r = subprocess.run([NODE, "-e", HARNESS_LV_SAVE, str(LV_JS)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.strip().splitlines()[-1]) == {"ok": False, "fast": True}
