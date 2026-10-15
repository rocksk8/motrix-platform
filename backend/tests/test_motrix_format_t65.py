# -*- coding: utf-8 -*-
"""T65 格式器遷移（其餘頁面）：沒有裸的 toLocale*String、每頁在自己的腳本前載入格式器、dt() 接受選項物件且與舊寫法逐字相同。

[單位] test:motrix_format_t65   [層] L1   [穩定度] 實驗
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core.source_tree import page_file

BACKEND = Path(__file__).resolve().parents[1]
FRONT = BACKEND.parent / "frontend"
NODE = shutil.which("node")
_RAW = re.compile(r"\.toLocale(?:Date|Time)?String\(")
_FALLBACK = re.compile(r"[ ]*<script>/\* 後備：格式器沒載入時.*?</script>\r?\n", re.S)

PAGES = ["index.html"] + ["pages/%s.html" % p for p in (
    "settlement payslips bonus voucher bonus-corrections payslip-form payment-request-form payment-request contractors "
    "reports inventory approval-queue tender-radar ledger-reports ledger-hub ledger-periods ledger-statements parts "
    "lodging-records quotation-form").split()]
JS = ["js/reports.js", "js/bonus.js", "js/voucher.js", "js/ledger-reports.js", "js/ledger-hub.js", "js/ledger-periods.js",
      "js/ledger-statements.js", "static/definition-form.js"]
# voucher.js 的兩處 toLocaleDateString('sv-SE') 是產生 YYYY-MM-DD「值」（不是顯示），刻意保留
KEEP = {"js/voucher.js": 2}


def _strip(rel):
    return _FALLBACK.sub("", (FRONT / rel).read_text(encoding="utf-8"))


def test_no_raw_tolocale_left_in_migrated_files_and_lint_sees_them():
    for rel in PAGES + JS:
        hits = _RAW.findall(_strip(rel))
        assert len(hits) == KEEP.get(rel, 0), "%s 還有 %d 處裸的 toLocale*String" % (rel, len(hits))
    assert _RAW.search("d.toLocaleTimeString('zh-TW')")                # 正對照


def test_pages_load_formatter_first_and_pages_add_no_ui_format_request():
    for rel in PAGES:
        html = (FRONT / rel).read_text(encoding="utf-8")
        assert html.index("motrix-format.js") - html.index("<script") < 50, rel
        assert rel.endswith("quotation-form.html") or "ui_format" not in html, "%s：這批頁面沒有既有的公開設定請求，只讀快取，不得為此新增請求" % rel
    # 載入這些 js 的頁面也必須載入格式器
    for js, pg in (("bonus.js", "bonus.html"), ("voucher.js", "voucher.html"), ("reports.js", "reports.html"),
                   ("ledger-hub.js", "ledger-hub.html"), ("ledger-periods.js", "ledger-periods.html"),
                   ("ledger-reports.js", "ledger-reports.html"), ("ledger-statements.js", "ledger-statements.html"),
                   ("definition-form.js", "payment-request.html")):
        assert "motrix-format.js" in page_file(pg).read_text(encoding="utf-8"), (js, pg)


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_dt_with_option_object_equals_the_old_calls_and_fallback_accepts_objects():
    code = r"""
global.window={};global.localStorage={getItem(){return null}};require('./static/motrix-format.js');const F=window.MotrixFormat;
const d=new Date(2026,9,15,13,5,9),o1={hour:'2-digit',minute:'2-digit'},o2={month:'2-digit',day:'2-digit'},o3={hour:'2-digit',minute:'2-digit',hour12:false},o4={hour12:false};
console.log(JSON.stringify([F.dt(d,o1)===d.toLocaleTimeString('zh-TW',o1),F.dt(d,o2)===d.toLocaleDateString('zh-TW',o2),
 F.dt(d,o3)===d.toLocaleTimeString('zh-TW',o3),F.dt(d,o4)===d.toLocaleString('zh-TW',o4),F.dt(d,'plain')===d.toLocaleString('zh-TW'),
 F.num('1234',{locale:'zh-TW'})==='1234'.toLocaleString('zh-TW'),F.num(NaN)===NaN.toLocaleString()]))"""
    out = subprocess.run([NODE, "-e", code], capture_output=True, text=True, encoding="utf-8", cwd=str(FRONT))
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == [True] * 7
    html = (FRONT / "pages/settlement.html").read_text(encoding="utf-8")
    fb = _FALLBACK.search(html).group(0)
    assert "typeof s==='object'" in fb
    code2 = "global.window={};" + re.sub(r"^\s*<script>|</script>\s*$", "", fb) + \
        ";const d=new Date(2026,9,15,13,5);const o={hour:'2-digit',minute:'2-digit'};console.log(JSON.stringify(window.MotrixFormat.dt(d,o)===d.toLocaleString('zh-TW',o)))"
    out2 = subprocess.run([NODE, "-e", code2], capture_output=True, text=True, encoding="utf-8")
    assert out2.returncode == 0, out2.stderr
    assert json.loads(out2.stdout) is True
