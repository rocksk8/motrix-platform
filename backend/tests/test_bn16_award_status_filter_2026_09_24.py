"""`BN16` · 獎金分潤單依狀態切換顯示（簽核／撥付／作廢三個維度）。

使用者原話：「獎金單可區分草稿、送審中、已審核、未撥付、已撥付多種狀態，可切換顯示」。
分類在前端（`frontend/js/bonus.js` 的 `awardCategory`／`filteredAwards`／`awardCounts`），
⇒ 用 **node 真的跑那一支檔**（比照 `test_dashboard_stats_merge_2026_09_22.py` 的做法），
   不是用 regex 猜它的行為。

驗：
① 「送審中」同時收「待審核」與「簽核中」兩個 status（它是集合的名字，不是第五個值）
② 已核准未撥付 ／ 已撥付 由撥付欄位推導；標記撥付後同一張單換到「已撥付」
③ 計數與列表同源：每一個頁籤的 `awardCounts()` ＝ `filteredAwards()` 的筆數；四類加總＝可見全部
④ 作廢預設不顯示，勾「顯示已作廢」之後才出現
⑤ 結構：整支檔只打一次 `/api/bonus/awards`（計數沒有自己的資料來源）
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
JS = ROOT / "frontend" / "js" / "bonus.js"

AWARDS = [
    {"id": 1, "status": "草稿", "voided_at": ""},
    {"id": 2, "status": "待審核", "voided_at": ""},
    {"id": 3, "status": "簽核中", "voided_at": ""},
    {"id": 4, "status": "已核准", "voided_at": "", "voucher_no_payment": ""},
    {"id": 5, "status": "已核准", "voided_at": "", "voucher_no_payment": "PAY-1"},
    {"id": 6, "status": "已核准", "voided_at": "2026-09-24T00:00:00", "voucher_no_payment": ""},
]


def _run(expr_js):
    node = shutil.which("node")
    if not node:
        pytest.skip("這台機器沒有 node —— ⚠️ skip 不是驗過")
    script = (
        "const vm=require('vm');const fs=require('fs');"
        "const ctx={window:{},document:{addEventListener(){}},localStorage:{getItem(){return null}},"
        "console,fetch(){return Promise.reject(new Error('no net'))}};vm.createContext(ctx);"
        "vm.runInContext(fs.readFileSync(%s,'utf8'),ctx);"
        "const p=vm.runInContext('bonusPage()',ctx);p.awards=%s;"
        "const out=(function(p){%s})(p);process.stdout.write(JSON.stringify(out));"
        % (json.dumps(str(JS)), json.dumps(AWARDS, ensure_ascii=False), expr_js))
    r = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, "node 跑不起來：%s" % r.stderr[-500:]
    return json.loads(r.stdout)


def test_bn16_pending_holds_both_pending_statuses():
    got = _run("return p.awards.map(a=>[a.id,p.awardCategory(a)])")
    cat = dict((i, c) for i, c in got)
    assert cat[2] == cat[3] == "pending", "「送審中」要同時收待審核與簽核中：%r" % cat
    assert cat[1] == "draft" and cat[4] == "approved_unpaid" and cat[5] == "paid", cat


def test_bn16_marking_paid_moves_the_award_to_the_paid_tab():
    got = _run("const a=p.awards[3];const before=p.awardCategory(a);"
               "a.paid_manually_at='2026-09-24';return [before,p.awardCategory(a)]")
    assert got == ["approved_unpaid", "paid"], "標記撥付後沒有換頁籤：%r" % got


def test_bn16_counts_and_lists_come_from_the_same_array():
    got = _run(
        "const res={};p.includeVoided=false;const c=p.awardCounts();"
        "for(const k of ['draft','pending','approved_unpaid','paid']){p.awardFilter=k;"
        "res[k]=[c[k],p.filteredAwards().length]};"
        "p.awardFilter='all';res.all=[Object.values(c).reduce((x,y)=>x+y,0),p.filteredAwards().length];"
        "return res")
    for k, (count, listed) in got.items():
        assert count == listed, "頁籤 %s 計數 %d 而列出 %d —— 計數與列表不同源" % (k, count, listed)


def test_bn16_voided_awards_are_hidden_until_asked_for():
    got = _run("p.awardFilter='all';p.includeVoided=false;const a=p.filteredAwards().map(x=>x.id);"
               "p.includeVoided=true;const b=p.filteredAwards().map(x=>x.id);return [a,b]")
    hidden, shown = got
    assert 6 not in hidden and 6 in shown, "作廢單的顯示切換不對：預設 %r、勾選後 %r" % (hidden, shown)


def test_bn16_the_page_fetches_the_award_list_exactly_once():
    src = JS.read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("//"))
    # ⚠️ 只數**讀清單**的那種（沒有 `method:`）—— 同檔另有一支 `POST /api/bonus/awards`（建立），
    #    第一版連它一起數 ⇒ 報 2 而產品是對的（量尺太寬，量到的不是要量的東西）。
    hits = [m for m in re.finditer(r"fetch\(\s*['\"]/api/bonus/awards(?:\?[^'\"]*)?['\"]", code)
            if "method:" not in code[m.end():m.end() + 80]]
    assert len(hits) == 1, (
        "`/api/bonus/awards` 清單在 bonus.js 被打了 %d 次 —— 計數若有自己的資料來源，"
        "數字與列表會分岔。" % len(hits))
