# -*- coding: utf-8 -*-
"""登入後回到原本要去的頁面（含 ?q=）——第 45 班小項。

背景：通知鈴鐺／信件裡的連結（例如 `bonus.html?q=單號`）在未登入或 session 過期時打開，各頁一律轉到 `login.html`，登入後固定落在首頁，
查詢字串就丟了（第 44 班步驟檔「獎金分潤頁不讀 ?q=」的實際原因不是頁面不讀，而是這條路徑：頁面程式從 2026-09-24 起就會讀 ?q=）。
做法（只動前端、不碰伺服器授權）：`static/auth-guard.js`（每個頁面最前面的同步守衛）在轉去登入頁之前把「原本的網址」記到 sessionStorage；
`pages/login.html` 登入成功後只在它是**同站絕對路徑**時才回去，否則照舊去首頁。
用 node 直接執行這兩段程式（不開瀏覽器）；沒有 node 就略過。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GUARD = REPO / "frontend" / "static" / "auth-guard.js"
LOGIN = REPO / "frontend" / "pages" / "login.html"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="需要 node")

GUARD_HARNESS = r"""
const fs = require('fs'); const src = fs.readFileSync(process.argv[2], 'utf8'); const inp = JSON.parse(process.argv[3])
const store = {}; const out = { replaced: null, stored: null, removed: false }
const ls = { getItem: k => inp.session ? JSON.stringify(inp.session) : null, removeItem: k => { out.removed = true } }
const ss = { setItem: (k, v) => { out.stored = [k, v] }, getItem: () => null }
const loc = { pathname: inp.pathname, search: inp.search || '', hash: inp.hash || '', replace: u => { out.replaced = u } }
const doc = { createElement: () => ({}), head: { appendChild() {} }, getElementById: () => null }
const win = { MOTRIX_PREVIEW: inp.preview }
const f = new Function('window', 'location', 'localStorage', 'sessionStorage', 'document', 'fetch', 'setTimeout', 'clearTimeout', src)
const fetchFn = () => inp.me === 401 ? Promise.resolve({ ok: false }) : Promise.resolve({ ok: true })
f(win, loc, ls, ss, doc, fetchFn, (fn) => 0, () => {})
setTimeout(() => console.log(JSON.stringify(out)), 20)
"""

TARGET_HARNESS = r"""
const fs = require('fs'); const html = fs.readFileSync(process.argv[2], 'utf8'); const inp = JSON.parse(process.argv[3])
const m = html.match(/\/\/ return-to:begin[^\n]*\n([\s\S]*?)\/\/ return-to:end/)
if (!m) { console.log('NOMARK'); process.exit(0) }
const obj = eval('({' + m[1].trim().replace(/,\s*$/, '') + '})')
let removed = false
const sessionStorage = { getItem: () => inp.stored, removeItem: () => { removed = true } }
const fn = new Function('sessionStorage', 'obj', 'return obj._returnTarget.call(obj)')
console.log(JSON.stringify({ target: fn(sessionStorage, obj), removed }))
"""


def _guard(**kw):
    r = subprocess.run([NODE, "-e", GUARD_HARNESS, "x", str(GUARD), json.dumps(kw)], capture_output=True, text=True,
                       encoding="utf-8", timeout=30, check=True)
    return json.loads(r.stdout.strip().splitlines()[-1])


def _target(stored):
    r = subprocess.run([NODE, "-e", TARGET_HARNESS, "x", str(LOGIN), json.dumps({"stored": stored})], capture_output=True,
                       text=True, encoding="utf-8", timeout=30, check=True)
    return json.loads(r.stdout.strip().splitlines()[-1])


# ── auth-guard：轉去登入頁之前記下原本的網址 ─────────────────────────────────────

def test_no_session_remembers_the_full_url_then_goes_to_login():
    r = _guard(pathname="/pages/bonus.html", search="?q=BN-1", hash="", session=None)
    assert r["replaced"] == "login.html" and r["stored"] == ["motrix_return_to", "/pages/bonus.html?q=BN-1"]


def test_expired_session_also_remembers_it():
    r = _guard(pathname="/pages/quotation-form.html", search="?id=Q-9", session={"token": "t"}, me=401)
    assert r["replaced"] == "login.html" and r["removed"] and r["stored"][1] == "/pages/quotation-form.html?id=Q-9"


def test_valid_session_stores_nothing_and_does_not_redirect():
    r = _guard(pathname="/pages/bonus.html", search="?q=BN-1", session={"token": "t"}, me=200)
    assert r["replaced"] is None and r["stored"] is None


def test_the_login_pages_themselves_are_never_remembered():
    assert _guard(pathname="/pages/login.html", session=None)["stored"] is None
    assert _guard(pathname="/pages/login-qr-approve.html", session=None)["stored"] is None


def test_index_uses_the_pages_login_path_and_still_remembers():
    r = _guard(pathname="/index.html", session=None)
    assert r["replaced"] == "pages/login.html" and r["stored"][1] == "/index.html"


def test_builder_preview_is_untouched():
    r = _guard(pathname="/pages/custom-records.html", search="?preview=1", session=None, preview=True)
    assert r["replaced"] is None and r["stored"] is None


# ── login：只回到「同站絕對路徑」，其餘一律首頁 ──────────────────────────────────────

@pytest.mark.parametrize("stored", ["/pages/bonus.html?q=BN-1", "/pages/case-management.html?no=A%20B#tab", "/index.html", "/"])
def test_login_returns_to_a_same_site_path(stored):
    r = _target(stored)
    assert r == {"target": stored, "removed": True}


@pytest.mark.parametrize("stored", [None, "", "//evil.example/x", "/\\evil.example", "https://evil.example/", "javascript:alert(1)",
                                    "pages/bonus.html", "../index.html", "/pages/bonus.html?q=a b", "/pages/login.html?x=1",
                                    "/pages/login-qr-approve.html", "/pages/x.html\nSet-Cookie: a=b"])
def test_login_refuses_anything_else_and_goes_home(stored):
    r = _target(stored)
    assert r["target"] == "../index.html" and r["removed"] is True            # 用過（或無效）就清掉，不會殘留到下一次登入


def test_login_calls_the_helper_on_both_redirect_paths():
    src = LOGIN.read_text(encoding="utf-8")
    assert src.count("this._returnTarget()") == 2
    assert "window.location.href = '../index.html'" not in src and "if (res.ok) window.location.href = '../index.html'" not in src
