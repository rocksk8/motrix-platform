# -*- coding: utf-8 -*-
"""T86 U4：前端不送注定失敗（404）的請求（正式機 30／90 天 log：def-governance `_probe/ledger` ×10、plan-view、versions、
material-order-approvals、company/tax、webauthn-config ×32）。

逐項核對後的處置：
  - def-governance 探測：改問永遠 200 的 `_available`，非最高管理者不送，同頁同 kind 只問一次（見 test_def_governance_*）；
  - 報價單 plan-view：新建中、還沒存過的單據（單號是前端先產生的）後端沒有這一列 ⇒ 一定 404 ⇒ 不問；存檔成功那一刻才問；
  - 報價單 versions：本來就擋新單（`isNewRecord`），只在單據載入成功後才問——這裡守住；
  - webauthn-config：2026-11-11 已改成先問 `/api/system/webauthn-config-status`（永遠 200），這裡守住不退化；
  - company/tax：404 是「查無此統編」的真實答案（使用者輸入的統編），不是前端的錯；前端已先擋非 8 碼，429 另有訊息。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

FRONT = Path(__file__).resolve().parents[2] / "frontend"
from core.source_tree import page_file  # noqa: E402

QF = page_file("quotation-form.html")
CPS = page_file("company-profile-settings.html")
NODE = shutil.which("node")

PLAN_HARNESS = r"""
const fs = require('fs'); const src = fs.readFileSync(process.argv[1], 'utf8'); const inp = JSON.parse(process.argv[2])
const a = src.indexOf('      async loadPlan(')
const body = src.slice(a, src.indexOf('\n      },\n', a) + 9)
const calls = []
global.fetch = async (url) => { calls.push(url); return { ok: true, status: 200, json: async () => ({ groups: [] }) } }
const o = new Function('return {' + body.replace(/,\s*$/, '') + '}')()
Object.assign(o, { q: { quoteNo: inp.quoteNo }, isNewRecord: inp.isNew, showCostCols: inp.cost, plan: { picks: {}, combosOpen: false, loading: false, error: '', data: null }, API: '/api', session: { token: 't' } })
;(async () => { await o.loadPlan(inp.justSaved); console.log(JSON.stringify(calls)) })()
"""


def _plan_calls(**kw):
    inp = {"quoteNo": "MQ-2611-001", "isNew": False, "cost": True, "justSaved": False}
    inp.update(kw)
    out = subprocess.run([NODE, "-e", PLAN_HARNESS, str(QF), json.dumps(inp)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not NODE, reason="需要 node")
@pytest.mark.parametrize("kw,n", [
    ({"isNew": True}, 0),                       # 新建中：後端沒有這一列 ⇒ 不問
    ({"isNew": True, "justSaved": True}, 1),    # 剛存檔成功（isNewRecord 還沒翻）⇒ 問
    ({"isNew": False}, 1),                      # 已存的單據 ⇒ 問
    ({"isNew": False, "cost": False}, 0),       # 沒展開成本欄（或沒成本權限）⇒ 不問
    ({"quoteNo": ""}, 0),
])
def test_plan_view_is_only_requested_for_a_record_the_server_has(kw, n):
    calls = _plan_calls(**kw)
    assert len(calls) == n, calls
    if n:
        assert calls[0].startswith("/api/quotations/MQ-2611-001/plan-view")


def test_first_save_still_refreshes_the_plan():
    s = QF.read_text(encoding="utf-8")
    assert "this.loadPlan(true)" in s and "async loadPlan(justSaved)" in s


def test_versions_are_only_requested_for_a_saved_record():
    s = QF.read_text(encoding="utf-8")
    a = s.index("async loadDocVersions()")
    assert "if (!this.q.quoteNo || this.isNewRecord)" in s[a:a + 400]
    for m in re.finditer(r"this\.loadDocVersions\(\)", s):
        pass
    assert s.count("this.loadDocVersions()") == 3            # 兩條載入路徑成功後＋存檔後；沒有別的呼叫點


def test_webauthn_config_is_only_read_after_the_always_200_status_endpoint_says_enabled():
    s = CPS.read_text(encoding="utf-8")
    a = s.index("async loadWebauthnConfig()")
    block = s[a:s.index("async saveWebauthnConfig()")]
    assert block.index("fetch('/api/system/webauthn-config-status')") < block.index("fetch('/api/settings/webauthn-config'")
    assert "if (!enabled) return" in block
    # 讀取（GET）設定的點只有這一處；PATCH 是使用者按儲存才送
    gets = [m.start() for m in re.finditer(r"fetch\('/api/settings/webauthn-config'", s)]
    assert len(gets) == 2 and gets[0] > a            # 一個 GET（在 loadWebauthnConfig 內）、一個 PATCH（save）
    for p in ("login.html", "my-account.html"):
        t = page_file(p).read_text(encoding="utf-8")
        assert "/api/settings/webauthn-config'" not in t and "/api/settings/webauthn-config`" not in t


@pytest.mark.parametrize("page", ("customers.html", "suppliers.html", "vendor-contractors.html"))
def test_tax_id_lookup_is_only_sent_for_a_full_8_digit_number(page):
    s = page_file(page).read_text(encoding="utf-8")
    a = s.index("/company/tax/")
    head = s[max(0, a - 900):a]
    assert re.search(r"\\d\{8\}", head), page
