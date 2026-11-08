# -*- coding: utf-8 -*-
"""守門：列舉前端 JS 的測試一律走 `tests/_frontend_sources.py`。

為什麼：模組專屬 JS 住在 `backend/modules/<key>/js/`（STAGE-C-DESIGN §3，網址仍是 `/js/<檔名>`）。
只 glob `frontend/js` 或 `rglob frontend` 的守門，在 JS 搬進模組之後會**安靜地少掃**：一份掃不到的檔與一份乾淨的檔，
在結果上長得一樣（BL 守門對象被搬走那一類）。這題把『新寫的列舉沒走共用入口』變成紅燈。

範圍：只含 JS 目錄（`frontend/js`、`frontend/static`）。頁面（.html）不在這裡——頁面沒有搬進模組。
允許清單 `ALLOWED`：每一項要有理由；**清單內的檔如果已經沒有直接列舉了也會紅**（清單不准放過期）。
"""
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]

# 直接列舉 JS 的寫法：glob/rglob 的樣式以 .js 結尾；或對 `... / "js"`、`... / "static"` 目錄呼叫 glob/rglob/iterdir；或沿用 STATIC_GLOB
_PATTERNS = (
    re.compile(r"""\b(?:r?glob)\(\s*[^)]*\*\.js["']"""),
    re.compile(r"""["'](?:js|static)["']\s*\)\s*\.(?:r?glob|iterdir)\("""),
    re.compile(r"""\bSTATIC_GLOB\b"""),
)

#: 本檔自己與共用入口不算
_SELF = {"tests/platform/test_no_direct_js_enumeration_2026_11_08.py", "tests/_frontend_sources.py"}

#: 直接列舉但有正當理由的檔 ⇒ 理由。
ALLOWED = {
    "tests/platform/test_legal_amount_rounding_guard.py":
        "自帶模組感知的列舉（_js_files 另掃 modules/<key>/js/）；STAGE-C 前就有，先不動它的邏輯",
    "tests/test_alpine_double_init_2026_09_23.py":
        "替身 frontend 樹（_fake_frontend 只複製 static／js 當固定對照）；真實母體由 tools/check_double_init.py 的 MODULE_JS_GLOB 一併掃",
    "tests/platform/test_module_assets_contract_2026_11_08.py":
        "契約題本身就是在核對『module.json 宣告 ⇔ modules/<key>/js/ 的實際檔案』，必須獨立於共用列舉自己走一次目錄",
    "tests/test_map_overlay_contract_2026_09_28.py":
        "掃的是 modules/*/pages/*overlay*.js（地圖覆蓋層，不是 /js 資產）",
    # case-management-*.js 還在 frontend/js（尚未搬進 case 模組）。C 車搬 case 時這 9 支改走 _frontend_sources。
    "tests/test_case_page_parts_2026_09_24.py": "case 尚未搬（C 車）；現在掃得到",
    "tests/test_case_page_no_native_dialogs_2026_09_24.py": "case 尚未搬（C 車）；現在掃得到",
    "tests/test_case_page_p4b_dialogs_2026_09_24.py": "case 尚未搬（C 車）；現在掃得到",
    "tests/test_case_page_wording_2026_09_24.py": "case 尚未搬（C 車）；現在掃得到",
    "tests/test_cm12_p3_prep_2026_09_24.py": "case 尚未搬（C 車）；現在掃得到",
    "tests/test_money_round_half_up_2026_09_26.py": "case 尚未搬（C 車）；現在掃得到",
    "modules/arap/tests/test_money_round_half_up_2026_09_26_from_tests.py": "case 尚未搬（C 車）；現在掃得到",
    "modules/payroll/tests/test_payroll_money_round_half_up_2026_09_26.py": "case 尚未搬（C 車）；現在掃得到",
    "modules/subcontract/tests/test_money_round_half_up_2026_09_26.py": "case 尚未搬（C 車）；現在掃得到",
}


def _test_files():
    files = list((BACKEND / "tests").rglob("*.py")) + list((BACKEND / "modules").glob("*/tests/**/*.py"))
    return sorted(p for p in files if "__pycache__" not in p.parts)


def direct_hits(text):
    """原始碼文字 ⇒ 直接列舉 JS 的行 [(行號, 內容)]（註解與 docstring 行也算，寧可多報）。"""
    return [(i, line.strip()) for i, line in enumerate(text.splitlines(), 1)
            if any(p.search(line) for p in _PATTERNS) and not line.lstrip().startswith("#")]


def test_scanner_positive_control():
    """掃描樣式要抓得到各種寫法；走共用入口的不能誤報。"""
    bad = [
        'files = sorted((ROOT / "frontend" / "js").glob("case-management-*.js"))',
        'for p in FRONTEND.rglob("*.js"):',
        'x = list((FRONTEND / "static").iterdir())',
        'g = glob.glob(STATIC_GLOB)',
    ]
    good = [
        'files = FS.all_js()',
        'for p in FS.module_js():',
        'pages = sorted(_FRONTEND.glob("pages/*.html"))',
    ]
    for line in bad:
        assert direct_hits(line), line
    for line in good:
        assert not direct_hits(line), line


def test_js_is_enumerated_only_through_the_shared_entry():
    found = {}
    for p in _test_files():
        rel = p.relative_to(BACKEND).as_posix()
        if rel in _SELF:
            continue
        hits = direct_hits(p.read_text(encoding="utf-8", errors="replace"))
        if hits:
            found[rel] = hits
    new = {r: h[:3] for r, h in found.items() if r not in ALLOWED}
    stale = sorted(r for r in ALLOWED if r not in found)
    assert not new, ("直接列舉前端 JS 而沒走 tests/_frontend_sources.py（模組自有 js 會被安靜略過）；"
                     "改走 FS.all_js()／FS.module_js()，或在 ALLOWED 附理由：%s" % new)
    assert not stale, ("ALLOWED 內的檔已經沒有直接列舉了——請從清單移除（清單不准放過期）：%s" % stale)


# ── 共用入口本身的正對照：它少列一個檔，所有走它的守門就一起少掃，而且不會有任何一題變紅 ──────────────────────

def test_shared_entry_lists_exactly_the_module_js_files_that_exist(tmp_path, monkeypatch):
    """合成模組樹：module_js／top_js／all_js／js_path 都要看得到模組自有 JS；vendor 與 tests 底下的不算。"""
    from core import source_tree
    from tests import _frontend_sources as FS
    mods = tmp_path / "modules"
    for key, files in (("zz_a", ["js/a.js", "js/b.js", "js/vendor/v.js", "tests/t.js"]), ("zz_b", ["js/c.js"]), ("zz_none", [])):
        (mods / key).mkdir(parents=True)
        (mods / key / "module.json").write_text("{}", encoding="utf-8")
        for f in files:
            (mods / key / f).parent.mkdir(parents=True, exist_ok=True)
            (mods / key / f).write_text("1", encoding="utf-8")
    monkeypatch.setattr(source_tree, "module_dirs", lambda: sorted(p for p in mods.iterdir() if (p / "module.json").is_file()))
    names = lambda ps: sorted(p.name for p in ps)          # noqa: E731
    assert names(FS.module_js()) == ["a.js", "b.js", "c.js"]
    assert {"a.js", "b.js", "c.js"} <= set(names(FS.top_js()))
    assert {"a.js", "b.js", "c.js"} <= set(names(FS.all_js()))
    assert FS.js_path("c.js") == mods / "zz_b" / "js" / "c.js"


def test_shared_entry_matches_an_independent_walk_of_the_real_tree():
    """真實樹：FS.module_js() ＝ 另一種寫法（os.walk）數出來的 backend/modules/*/js/**.js（不含 vendor）。"""
    import os
    from tests import _frontend_sources as FS
    mods = BACKEND / "modules"
    expect = set()
    for d in sorted(mods.iterdir()) if mods.is_dir() else []:
        if not (d / "module.json").is_file():
            continue
        for root, dirs, files in os.walk(d / "js"):
            dirs[:] = [x for x in dirs if x != "vendor"]
            expect |= {(Path(root) / f).resolve() for f in files if f.endswith(".js")}
    assert {p.resolve() for p in FS.module_js()} == expect
    assert expect <= {p.resolve() for p in FS.all_js()}
