# -*- coding: utf-8 -*-
"""T64 切片 B（D2）：共用顯示格式器 frontend/static/motrix-format.js。
- 預設（設定全是 default／讀不到）⇒ 與被取代的原運算式逐字相同（用 node 逐值比對；語系跟著 node 的預設語系，與瀏覽器同理，兩邊用同一個）；
- 選項（千分位 none／固定小數位／日期樣式）只在設定值合法時生效，不認得的值 ⇒ 預設；
- 格式器壞掉／缺席 ⇒ 頁面印原值，不留白（內嵌後備）；
- 已遷移的頁面不再有裸的 toLocaleString／toLocaleDateString（正反兩面：lint 本身要抓得到裸呼叫）。
只用 node（沒有就略過）；不開瀏覽器。"""
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
MIGRATED = ["pages/quotation-form.html", "pages/quotations.html", "pages/case-management.html", "pages/cashier.html",
            "js/cashier.js", "js/case-management-dispatch.js", "js/case-management-exec.js", "js/case-management-fin.js",
            "js/case-management-mchange.js", "js/case-management-xexp.js"]
_RAW = re.compile(r"\.toLocale(?:Date)?String\(")


def _node(code):
    out = subprocess.run([NODE, "-e", code], capture_output=True, text=True, encoding="utf-8", cwd=str(FRONT))
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


_PRE = ("global.window={addEventListener(){}};global.localStorage={_d:{},getItem(k){return this._d[k]||null},"
        "setItem(k,v){this._d[k]=v},removeItem(k){delete this._d[k]}};require('./static/motrix-format.js');const F=window.MotrixFormat;")


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_defaults_equal_the_original_expressions():
    code = _PRE + """
const nums=[0,-0,1,-1,12,999,1000,1234567,-1234567,1234.5,0.1+0.2,1e21,123456789012,0.000001,NaN,Infinity,-Infinity,99999.995,'12','',true];
const bad=[];
for(const v of nums){ if(F.num(v)!==v.toLocaleString()) bad.push(['num',String(v)]);
  if(typeof v==='number' && F.num(v,{locale:'en-US',maxFrac:4})!==v.toLocaleString('en-US',{maximumFractionDigits:4})) bad.push(['en',String(v)]);
  if(F.money(v)!==v.toLocaleString()) bad.push(['money',String(v)]);}
const dates=[new Date(2026,0,5,3,4,5),new Date(2026,11,31,23,59,59),new Date(1999,5,15,12,0,0)];
for(const d of dates){
  if(F.date(d)!==d.toLocaleDateString('zh-TW')) bad.push(['date']);
  if(F.dt(d,'plain')!==d.toLocaleString('zh-TW')) bad.push(['plain']);
  if(F.dt(d,'full')!==d.toLocaleString('zh-TW',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})) bad.push(['full']);
  if(F.dt(d,'short')!==d.toLocaleString('zh-TW',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})) bad.push(['short']);
  if(F.dt(d,'sec')!==d.toLocaleString('zh-TW',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'})) bad.push(['sec']);
}
console.log(JSON.stringify({bad,n:nums.length}));"""
    r = _node(code)
    assert r["bad"] == [] and r["n"] >= 20


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_null_and_garbage_never_throw_and_never_blank_a_real_value():
    code = _PRE + """
const o=[F.num(null),F.num(undefined),F.date(null),F.dt(undefined,'full'),F.date('x'),F.dt('x','full'),F.num({}),F.status('洽談中'),F.status(undefined)];
console.log(JSON.stringify(o));"""
    o = _node(code)
    assert o[:4] == ["", "", "", ""]
    assert o[4] == "x" and o[5] == "x" and o[6] == "[object Object]" and o[7] == "洽談中" and o[8] is None


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_options_apply_only_when_valid_and_unknown_values_fall_back_to_defaults():
    code = _PRE + """
const d=new Date(2026,0,5,3,4,5), base=F.num(1234567.891), baseD=F.date(d);
F._configure({thousands:'none'}); const none=F.num(1234567);
F._configure({decimals:'2'}); const two=F.num(1234.5); const dateSame=F.date(d);
F._configure({decimals:'0'}); const zero=F.num(1234.56);
F._configure({dateStyle:'iso'}); const iso=F.date(d);
F._configure({dateStyle:'slash'}); const slash=F.date(d);
F._configure({thousands:'banana',decimals:'7',dateStyle:'x'}); const junk=[F.num(1234567.891),F.date(d)];
F._configure({}); const back=[F.num(1234567.891),F.date(d)];
F._configure({thousands:'none',decimals:'2'}); const str=F.num('1,234');   // 非數字：不套數字選項，原樣
F.setStatusLabels({'成案':'已成立'});
console.log(JSON.stringify({base,baseD,none,two,dateSame,zero,iso,slash,junk,back,str,st:[F.status('成案'),F.status('其他')]}));"""
    r = _node(code)
    assert r["none"] == "1234567" and r["two"].endswith(".50") and r["zero"] in ("1,235", "1235")
    assert r["iso"] == "2026-01-05" and r["slash"] == "2026/01/05"
    assert r["junk"] == [r["base"], r["baseD"]] and r["back"] == [r["base"], r["baseD"]]
    assert r["str"] == "1,234" and r["st"] == ["已成立", "其他"]


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_a_broken_formatter_prints_the_raw_value_not_blank():
    code = _PRE + """
const evil={toLocaleString(){throw new Error('boom')},toLocaleDateString(){throw new Error('boom')},toString(){return 'RAW'}};
console.log(JSON.stringify([F.num(evil),F.date(evil),F.dt(evil,'full')]));"""
    assert _node(code) == ["RAW", "RAW", "RAW"]


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_inline_fallback_in_every_migrated_page_prints_the_raw_value_when_the_script_is_missing():
    pages = ["quotation-form.html", "quotations.html", "case-management.html", "cashier.html"]
    expect = _node("console.log(JSON.stringify((1234567).toLocaleString()))")
    for name in pages:
        html = page_file(name).read_text(encoding="utf-8")
        assert 'src="../static/motrix-format.js"' in html, name
        m = re.search(r"<script>/\* 後備：格式器沒載入時[^*]*\*/(.*?)</script>", html, re.S)
        assert m, name
        code = ("global.window={};" + m.group(1) + ";const F=window.MotrixFormat;"
                "const d=new Date(2026,0,5,3,4,5);"
                "console.log(JSON.stringify([F.num(1234567),F.num(null),F.num({toLocaleString(){throw 1},toString(){return 'RAW'}}),"
                "F.date(d)===d.toLocaleDateString('zh-TW'),F.dt(d,'full')===d.toLocaleString('zh-TW'),F.status('x')]))")
        assert _node(code) == [expect, "", "RAW", True, True, "x"], name


def test_migrated_files_have_no_raw_tolocale_calls_and_the_lint_sees_them():
    for rel in MIGRATED:
        txt = re.sub(r"<script>/\* 後備：格式器沒載入時.*?</script>", "", (FRONT / rel).read_text(encoding="utf-8"), flags=re.S)   # 內嵌後備本身會用裸呼叫
        assert not _RAW.search(txt), "%s 還有裸的 toLocale*String（改用 MotrixFormat）" % rel
    assert _RAW.search("x.toLocaleString()") and _RAW.search("d.toLocaleDateString('zh-TW')")     # 正對照
    assert _RAW.search("new Date(a).toLocaleString('zh-TW', {})")


def test_every_migrated_page_loads_the_formatter_before_its_own_scripts():
    for name in ("quotation-form.html", "quotations.html", "case-management.html", "cashier.html"):
        html = page_file(name).read_text(encoding="utf-8")
        first_script = html.index("<script")
        assert html.index("static/motrix-format.js") - first_script < 50, "%s：格式器應是 head 的第一支 script" % name


def test_ui_format_group_is_registered_with_defaults_equal_to_today():
    from helpers import settings_registry as SR
    g = SR.groups()["ui_format"]
    assert not g["sensitive"]
    got = {f["key"]: (f["default"], f["min"], f["max"]) for f in g["fields"]}
    assert got == {"enabled": (0, 0, 1), "thousands": (0, 0, 1), "decimals": (0, 0, 2), "date_style": (0, 0, 2)}
