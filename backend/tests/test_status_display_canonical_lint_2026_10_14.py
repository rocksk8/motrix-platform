# -*- coding: utf-8 -*-
"""T63 守門：狀態的『顯示名稱』只能用來顯示，邏輯（SQL／總帳／獎金／篩選／請求本文）一律用原始值。純靜態掃描＋node 小題，不需要資料庫。
1. 後端：除白名單外，任何後端模組都不得引用 `helpers.status_display`——SQL、總帳、獎金讀不到顯示名稱。
2. 前端：`MotrixStatus.label(`／`stLabel(` 的呼叫不得出現在判斷或請求位置（x-show／x-if／:disabled／x-model／@click…、比較運算子兩側、
   .filter／.find／.some／.includes／indexOf、if／while 條件、JSON.stringify／body:）；只能出現在 x-text、:title 這類純顯示位置。
3. 正對照：故意違規的範例字串必須被抓到（掃描器壞了不能假綠）；dev-crm 必須被掃到。
4. dev-crm：表未載入時 `stLabel(raw)` 與原本直接印原值逐字相同；新鍵登錄、『未成案』不重複；選項 value＝原文字。"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core.source_tree import page_file, page_files
from helpers import status_display as S

BACKEND = Path(__file__).resolve().parents[1]
FRONT = BACKEND.parent / "frontend"
NODE = shutil.which("node")

# 可以引用 status_display 的後端檔（登錄、公開端點、設定中心的治理流程、設定群組）
BACKEND_ALLOWED = {
    "helpers/status_display.py", "routers/status_display.py", "routers/def_governance.py", "routers/def_pipeline.py",
    "helpers/settings_groups.py", "main.py",
}


def _backend_files():
    for p in BACKEND.rglob("*.py"):
        rel = p.relative_to(BACKEND).as_posix()
        if rel.startswith(("tests/", "tools/", ".venv")) or "/tests/" in rel or "__pycache__" in rel:
            continue
        yield rel, p


def test_no_backend_module_outside_the_whitelist_uses_the_display_table():
    bad = []
    for rel, p in _backend_files():
        if rel in BACKEND_ALLOWED:
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        if re.search(r"\bstatus_display\b", src):
            bad.append(rel)
    assert bad == [], "這些後端模組引用了狀態顯示表（SQL／總帳／獎金必須用原始值）：%s" % bad


def test_the_whitelist_files_exist():
    names = {rel for rel, _ in _backend_files()}
    missing = BACKEND_ALLOWED - names
    assert not missing, "白名單裡的檔案不存在（改名或搬走了？）：%s" % sorted(missing)


# ── 前端 ───────────────────────────────────────────────────────────────────────
_CALL = re.compile(r"(?:MotrixStatus\.label|(?:this\.)?stLabel)\(")
_FORBIDDEN_ATTR = {"x-show", "x-if", "x-model", "x-effect", ":disabled", ":hidden", ":value", ":checked", ":selected", "@click", "@change", "@input", "@submit", "x-bind:disabled", "x-bind:hidden", "x-bind:value"}
_CMP_BEFORE = re.compile(r"(===?|!==?|<=|>=|[<>])\s*$")
_CMP_AFTER = re.compile(r"^\s*(===?|!==?|<=|>=|[<>])")
_CTX_BEFORE = re.compile(r"\.(?:filter|find|findIndex|some|every|includes|indexOf|startsWith|endsWith)\([^)]*$|\b(?:if|while)\s*\([^)]*$|JSON\.stringify\([^)]*$|\bbody\s*:[^,}]*$|\bstatus\s*:\s*$")
_ATTR = re.compile(r"""([:@]?[A-Za-z][\w:.\-]*)\s*=\s*"[^"]*$""")


def _call_end(line, start):
    depth = 0
    for i in range(start, len(line)):
        c = line[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    return len(line)


def lint_text(text):
    """⇒ [(行號, 原因, 該行)]。每個 label 呼叫逐一檢查。"""
    out = []
    for no, line in enumerate(text.splitlines(), 1):
        for m in _CALL.finditer(line):
            before, end = line[:m.start()], _call_end(line, m.end() - 1)
            after = line[end:]
            why = None
            if _CMP_BEFORE.search(before) or _CMP_AFTER.match(after):
                why = "比較運算子的一側"
            elif _CTX_BEFORE.search(before):
                why = "判斷／篩選／請求位置"
            else:
                a = _ATTR.search(before)
                if a and a.group(1) in _FORBIDDEN_ATTR:
                    why = "屬性 %s（判斷或事件）" % a.group(1)
            if why:
                out.append((no, why, line.strip()[:160]))
    return out


def _frontend_files():
    for p in page_files():
        yield p
    for sub in ("js", "static"):
        for p in (FRONT / sub).rglob("*"):
            if p.suffix in (".html", ".js") and "vendor" not in p.parts:
                yield p


def test_display_labels_are_never_used_in_logic_positions():
    bad, scanned = [], []
    for p in _frontend_files():
        txt = p.read_text(encoding="utf-8", errors="replace")
        if _CALL.search(txt):
            scanned.append(p.name)
        for no, why, line in lint_text(txt):
            bad.append("%s:%d %s｜%s" % (p.name, no, why, line))
    assert len(scanned) >= 8 and "dev-crm.html" in scanned, "掃描器沒掃到該掃的檔案：%s" % scanned
    assert bad == [], "顯示名稱被用在判斷或請求位置（必須用原始值）：\n" + "\n".join(bad)


@pytest.mark.parametrize("sample", [
    '<div x-show="stLabel(c.status) === \'成案\'">',
    '<div x-show="MotrixStatus.label(c.status, \'case\') != \'\'">',
    '<template x-if="stLabel(c.status)">',
    "const hit = list.filter(c => stLabel(c.status) === q)",
    "if (this.stLabel(c.status)) { go() }",
    "body: JSON.stringify({ status: stLabel(s) })",
    '<select x-model="stLabel(form.status)">',
    '<option :value="stLabel(k)">',
    "list.some(c => c.x == MotrixStatus.label(s))",
])
def test_positive_control_the_scanner_catches_deliberate_violations(sample):
    assert lint_text(sample), "掃描器沒抓到故意的違規：" + sample


@pytest.mark.parametrize("sample", [
    '<span x-text="stLabel(c.status)"></span>',
    '<span :title="stLabel(c.status)" x-text="c.status ? stLabel(c.status) : \'\'"></span>',
    "return window.MotrixStatus ? window.MotrixStatus.label(raw, ctx, fallback) : raw",
    '<option value="成案" x-text="stLabel(\'成案\')">成案</option>',
])
def test_negative_control_display_positions_are_allowed(sample):
    assert lint_text(sample) == [], sample


# ── dev-crm ────────────────────────────────────────────────────────────────────
DEVCRM = page_file("dev-crm.html")
DEV_STATUSES = ["洽談中", "成案", "未成案", "暫擱置"]


def test_new_keys_are_registered_once_and_default_to_todays_words():
    for k in ("洽談中", "成案", "暫擱置"):
        assert S.STATUS_KEYS.count(k) == 1 and S._GROUP[k] == "devcase" and S._SEMANTIC[k] == "plain", k
    assert S.STATUS_KEYS.count("未成案") == 1 and S._GROUP["未成案"] == "deal", "『未成案』沿用 deal 鍵，不重複登錄"
    d = S.defaults()
    for k in DEV_STATUSES:
        assert d[k]["label"] == k and d[k]["tone"] == "neutral", k


def test_the_page_keeps_logic_on_raw_values_and_options_keep_raw_value_attrs():
    html = DEVCRM.read_text(encoding="utf-8")
    for k in DEV_STATUSES:
        assert re.search(r'<option value="%s" x-text="stLabel\(\'%s\'\)">%s</option>' % (k, k, k), html), k
    assert "filterStatus==='成案'" in html and "this.caseCount('未成案')" in html and "c.status === '洽談中'" in html
    assert "body: JSON.stringify({ status })" in html, "狀態更新請求仍送原始值"
    assert "static/status-chip.js" in html and "static/public-flags.js" in html and "MotrixStatus.init()" in html


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_devcrm_stlabel_equals_the_raw_value_when_the_table_is_not_loaded():
    html = DEVCRM.read_text(encoding="utf-8")
    m = re.search(r"^\s*(stLabel\(raw\) \{.*\}),\s*$", html, re.M)
    assert m, "找不到 dev-crm 的 stLabel"
    code = ("global.window={};const M=require('./static/status-chip.js');window.MotrixStatus=M;"
            "const o={" + m.group(1) + "};"
            "const raws=%s.concat(['', null, undefined, '其他']);"
            "const off=raws.map(r=>o.stLabel(r)===(r==null?'':String(r)));"
            # 載入一份只改『成案』的表 ⇒ 只有被改過的欄位生效、其他維持原值
            "M.apply({enabled:true,statuses:{'成案':{label:'已成立',names:{}}},changed:{'成案':['label']}});"
            "const on=%s.map(r=>o.stLabel(r));"
            "console.log(JSON.stringify([off,on]))") % (json.dumps(DEV_STATUSES, ensure_ascii=False), json.dumps(DEV_STATUSES, ensure_ascii=False))
    out = subprocess.run([NODE, "-e", code], capture_output=True, text=True, encoding="utf-8", cwd=str(FRONT))
    assert out.returncode == 0, out.stderr
    off, on = json.loads(out.stdout)
    assert all(off), "表未載入時必須逐字等於原值"
    assert on == ["洽談中", "已成立", "未成案", "暫擱置"]
