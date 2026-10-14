# -*- coding: utf-8 -*-
"""T60 S8：版面排版器（layout-editor.js）不得使用瀏覽器原生對話框，改用頁內的兩段式確認／提示。

原生 alert／confirm 會擋住整頁事件、不隨深色模式、e2e 只能盲接（同案件頁 CM12 P4 的理由）。
① 靜態：layout-editor.js（剝註解）沒有 alert( ／confirm( ／prompt(；附合成樣本正對照。
② 行為（node 真的執行元件）：_ask 回 Promise<boolean>，確定＝true、取消＝false；連問兩次，前一個視為取消；
   提示（_notice）只有「知道了」；關閉面板時放掉等待中的確認（視為取消）。
③ 樣板：頁首有確認列，按鈕有 data-testid。發布與還原都經 _ask，取消就不送請求。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
EDITOR = ROOT / "frontend" / "static" / "layout-editor.js"
NATIVE = re.compile(r"(?:(?<![\w.$])|(?<=window\.))(alert|confirm|prompt)\s*\(")
NODE = shutil.which("node")


def _strip(s):
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", r"\1", line) for line in s.split("\n"))


def _calls(text):
    return [m.group(1) for line in _strip(text).split("\n") for m in NATIVE.finditer(line)]


def test_scanner_positive_control():
    sample = "alert('a')\nif (!confirm('b')) return\nwindow.prompt('c')\nawait this._ask('d')\n// confirm('註解')\n"
    assert _calls(sample) == ["alert", "confirm", "prompt"]


def test_layout_editor_has_no_native_dialogs():
    assert _calls(EDITOR.read_text(encoding="utf-8")) == []


def test_template_has_the_ask_bar_and_publish_restore_use_it():
    src = EDITOR.read_text(encoding="utf-8")
    for tid in ("ml-ask", "ml-ask-yes", "ml-ask-no"):
        assert 'data-testid="%s"' % tid in src
    pub = src[src.index("async _publish()"):src.index("async _restore(")]
    assert "await this._ask(" in pub and pub.index("await this._ask(") < pub.index("'/publish?scope='")     # 取消就不送發布請求
    res = src[src.index("async _restore("):]
    res = res[:res.index("this._j(")]
    assert "await this._ask(" in res                                                                       # 先問，才送還原請求


_HARNESS = r"""
const fs = require('fs')
global.window = global
global.document = { addEventListener() {}, body: { classList: { add() {}, remove() {} } }, getElementById() { return null } }
window.MotrixCustomLayout = {}
window.MotrixLayout = { show() {}, config() { return { module: 'x', page: 'p' } } }
eval(fs.readFileSync(process.argv[1], 'utf8'))
const c = window.MotrixLayoutEditor.component()
;(async () => {
%s
})().catch(e => { console.error(String(e)); process.exit(1) })
"""


def _node(body):
    out = subprocess.run([NODE, "-e", _HARNESS % body, str(EDITOR)], capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    return json.loads(out.stdout.decode("utf-8"))


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_ask_resolves_true_on_yes_false_on_no_and_clears_the_bar():
    r = _node("""
  const p1 = c._ask('發布嗎？'); const shown = c.askBar && c.askBar.text; c.answer(true); const a = await p1
  const p2 = c._ask('還原嗎？'); c.answer(false); const b = await p2
  console.log(JSON.stringify({ shown, a, b, after: c.askBar }))""")
    assert r == {"shown": "發布嗎？", "a": True, "b": False, "after": None}


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_a_second_question_cancels_the_first_and_close_cancels_the_pending_one():
    r = _node("""
  const p1 = c._ask('一'); const p2 = c._ask('二'); const first = await p1; c.answer(true); const second = await p2
  const p3 = c._ask('三'); c.close(); const third = await p3
  console.log(JSON.stringify({ first, second, third, bar: c.askBar, open: c.open }))""")
    assert r == {"first": False, "second": True, "third": False, "bar": None, "open": False}


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_notice_has_only_an_ok_button_and_closes_the_panel():
    r = _node("""
  c._notice('排版器只在桌機使用'); const during = { open: c.open, notice: c.askBar.notice, text: c.askBar.text }
  c.answer(true)
  console.log(JSON.stringify({ during, open: c.open, bar: c.askBar }))""")
    assert r == {"during": {"open": True, "notice": True, "text": "排版器只在桌機使用"}, "open": False, "bar": None}
