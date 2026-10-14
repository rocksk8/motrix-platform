# -*- coding: utf-8 -*-
"""OFF 狀態 golden（報價單表單、報價單清單；已寫、未跑）：旗標全部預設（關）時，畫面文字與請求清單要和 golden 逐項相同。

做法：種子資料固定 → 開頁 → 等網路靜止 → 取「看得到的文字」與「同源請求清單（method＋路徑＋排序後查詢，已排序）」→ 與
tests/e2e_on_state/golden/<名稱>.json 比對。第一次（或改版後要重錄）：`MOTRIX_RECORD_GOLDEN=1 pytest tests/e2e_on_state/test_off_state_golden.py -m e2e`，
把產生的 golden 檔交給審查（內容就是「旗標關閉時使用者看到什麼、瀏覽器打了哪些請求」）。
比對時正規化：日期（YYYY-MM-DD、YYYY/MM/DD、時間戳）、埠號、token；請求清單不含字型／圖片。
在【基底樹（尚未合入 T62 版面線）】和【合入後】各錄一份比對，兩份必須相同，才證明「旗標關閉＝與過去逐項相同」。
"""
import json
import os
import re
from pathlib import Path

import pytest

from tests._requires import requires_module
from tests.e2e_on_state._common import DATA_JS, Requests, inject_login, seed_draft_quote

pytestmark = [pytest.mark.e2e, requires_module("case", "報價單頁")]
GOLDEN = Path(__file__).resolve().parent / "golden"
RECORD = os.environ.get("MOTRIX_RECORD_GOLDEN") == "1"
_DATE = re.compile(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?")


_BUILD = re.compile(r"(?<![0-9a-f])[0-9a-f]{7,12}(?= · 啟動)")


def _norm_text(s):
    s = _DATE.sub("<日期>", s)
    s = _BUILD.sub("<build>", s)                                     # 頁尾 build 短 hash 每個 commit 都不同
    return [ln.strip() for ln in s.splitlines() if ln.strip()]


def _norm_reqs(items):
    return [re.sub(r"(token|_)=[^&]*", r"\1=<x>", i) for i in items]


# T62 在旗標【關閉】時多出來的請求，逐條列出（PM 裁示 2026-10-15：允許清單，不做延後載入重構）。
# 理由：全是「讀旗標」的 GET 與靜態資源（頁面載入版面／自訂欄位／狀態顯示的腳本），旗標關閉時不呈現任何東西、使用者看到的畫面與 platform 相同。
# 任何不在這份清單裡的新請求都會讓測試失敗；寫入（非 GET）一律不准。
_JS = ["GET /js/def-governance.js", "GET /static/custom-layout.js", "GET /static/layout-editor.js", "GET /static/layout-runtime.js", "GET /static/public-flags.js"]
ALLOWED_EXTRA = {
    "quotation_form_off": set(_JS + [
        "GET /api/settings-center/public?groups=builder_layout,builder_custom_fields,builder_stage_templates",
        "GET /static/custom-fields.js"]),
    "quotations_list_off": set(_JS + [
        "GET /api/settings-center/public?groups=builder_layout",
        "GET /api/settings-center/public?groups=builder_status_display",
        "GET /js/status-display-editor.js",
        "GET /static/status-chip.js"]),
}


def _compare(name, snap):
    f = GOLDEN / (name + ".json")
    if RECORD:
        f.parent.mkdir(exist_ok=True)
        f.write_text(json.dumps(snap, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return
    assert f.exists(), "還沒有 golden：先用 MOTRIX_RECORD_GOLDEN=1 錄一份（%s）" % f
    want = json.loads(f.read_text(encoding="utf-8"))
    from collections import Counter
    got_c, want_c = Counter(snap["requests"]), Counter(want["requests"])
    missing = want_c - got_c
    extra = got_c - want_c
    assert not missing, "platform 有的請求在 T62 關閉狀態消失了：%s" % sorted(missing)                       # (b) 資料端點的請求一個都不能少
    assert set(extra) <= ALLOWED_EXTRA[name], "不在允許清單的新請求：%s" % sorted(set(extra) - ALLOWED_EXTRA[name])   # (a)
    assert all(r.startswith("GET ") for r in extra), "多出來的請求有寫入：%s" % sorted(r for r in extra if not r.startswith("GET "))   # (c)
    assert snap["text"] == want["text"], "OFF 狀態的畫面文字變了"                                           # (b) 畫面文字與 platform 逐項相同


def _snapshot(page, reqs, ready_js):
    page.wait_for_function(ready_js, timeout=20000)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)
    text = page.evaluate("""() => { const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); const out = []; let n;
        while ((n = w.nextNode())) { const e = n.parentElement; if (!e || ['SCRIPT', 'STYLE', 'TEMPLATE', 'NOSCRIPT'].includes(e.tagName)) continue;
          if (e.offsetParent === null && getComputedStyle(e).position !== 'fixed') continue; const t = n.textContent.trim(); if (t) out.push(t) } return out.join('\\n') }""")
    return {"text": _norm_text(text), "requests": _norm_reqs(reqs.sorted())}


def test_quotation_form_off_golden(live_server, make_user, new_context):
    u = make_user(username="off_qf", role="superadmin")
    qn = seed_draft_quote()
    ctx = new_context()
    page = ctx.new_page()
    inject_login(page, live_server, u[0], u[1])
    reqs = Requests(page, live_server)
    page.goto("%s/pages/quotation-form.html?id=%s" % (live_server, qn))
    snap = _snapshot(page, reqs, "() => %s.q && %s.q.quoteNo === '%s'" % (DATA_JS, DATA_JS, qn))
    # 旗標關閉的直接證據：沒有自訂欄位區塊、沒有版面編輯器入口、沒有 /api/layout 與自訂欄位請求
    assert page.locator("[data-testid=cf-section]").count() == 0
    assert not any("/api/layout" in r or "/api/custom-fields" in r or "stage-templates" in r for r in snap["requests"]), snap["requests"]
    _compare("quotation_form_off", snap)


def test_quotations_list_off_golden(live_server, make_user, new_context):
    u = make_user(username="off_ql", role="superadmin")
    seed_draft_quote()
    ctx = new_context()
    page = ctx.new_page()
    inject_login(page, live_server, u[0], u[1])
    reqs = Requests(page, live_server)
    page.goto(live_server + "/pages/quotations.html")
    snap = _snapshot(page, reqs, "() => %s.loading === false" % DATA_JS)
    heads = page.evaluate("() => [...document.querySelectorAll('thead th')].filter(t => t.offsetParent !== null).map(t => t.textContent.trim())")
    assert heads[:4] == ["報價單號", "客戶名稱", "案件名稱", "金額（含稅）"], heads                   # 預設欄位與順序
    assert not any("/api/layout" in r for r in snap["requests"]), snap["requests"]
    _compare("quotations_list_off", snap)
