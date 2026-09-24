"""案件管理頁分檔的結構守門（CM12 P1，2026-09-24）。

app() 由 case-management-*.js 各自登記的成員組合（Object.defineProperties 依載入順序），
所以：① 成員名不可在兩個檔裡重複——後載的會靜默蓋掉先載的，而沒有任何錯誤；
② 頁面必須載入每一支分檔，而且 core 最先（它定義 app() 與 CM_PARTS）；
③ 舊的單檔 case-management.js 不可以回來（兩份並存時頁面只載其中一份，另一份會被改了卻沒人用）。
用 node 實際載入各檔取成員名，不用正規式猜。
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = ROOT / "frontend" / "js"
PAGE = ROOT / "frontend" / "pages" / "case-management.html"
PARTS = sorted(JS_DIR.glob("case-management-*.js"))

NODE_SCRIPT = r"""
const fs = require('fs'), vm = require('vm')
const out = {}
for (const f of process.argv.slice(1)) {
  const ctx = { window: { innerWidth: 1200, addEventListener() {} }, document: {}, localStorage: { getItem() { return null } }, console }
  vm.createContext(ctx)
  vm.runInContext('var window = globalThis.window', ctx)
  vm.runInContext(fs.readFileSync(f, 'utf8'), ctx, { filename: f })
  const parts = ctx.window.CM_PARTS || []
  out[f] = parts.flatMap(p => Object.getOwnPropertyNames(p()))
}
console.log(JSON.stringify(out))
"""


def test_the_single_file_is_gone_and_parts_exist():
    assert not (JS_DIR / "case-management.js").exists()
    assert len(PARTS) >= 10, [p.name for p in PARTS]


def test_page_loads_every_part_with_core_first():
    html = PAGE.read_text(encoding="utf-8")
    srcs = re.findall(r'<script src="\.\./js/(case-management-[a-z]+\.js)"', html)
    assert srcs and srcs[0] == "case-management-core.js", srcs
    assert sorted(srcs) == sorted(p.name for p in PARTS), (srcs, [p.name for p in PARTS])
    assert '<script src="../js/case-management.js"' not in html


@pytest.mark.skipif(shutil.which("node") is None, reason="需要 node 才能實際載入各檔")
def test_no_member_name_is_defined_in_two_parts():
    r = subprocess.run(["node", "-e", NODE_SCRIPT, *map(str, PARTS)], capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    names = json.loads(r.stdout)
    seen = {}
    dup = []
    for f, ns in names.items():
        assert ns, f"{pathlib.Path(f).name} 沒有登記任何成員"
        for n in ns:
            if n in seen:
                dup.append((n, pathlib.Path(seen[n]).name, pathlib.Path(f).name))
            seen[n] = f
    assert not dup, f"成員名重複（後載的會蓋掉先載的）：{dup}"
    assert len(seen) >= 600, len(seen)
