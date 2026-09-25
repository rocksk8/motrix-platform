"""頁面路徑集中（階段 C／C2，STAGE-C-DESIGN §5）：`frontend/pages` 的寫死位置只准變少。

頁面會搬進 modules/<key>/pages/；讀頁面原始碼的測試與工具要改用 `core.source_tree.page_file()`／`page_files()`。
☠️ 自己 glob `frontend/pages/*.html` 的守門，頁面搬走後會**安靜地少掃**那些頁面——斷言沒變、照樣綠。

基線 page_path_baseline.json：{檔案: 寫死次數}。規則：
  - 不在基線的檔：0 次
  - 在基線的檔：不可以多；**變少了就要同一個 commit 更新基線**（棘輪，免得空出來的額度被別人用掉）
  - 允許：core/source_tree.py、core/paths.py（定義處）、core/pages.py（對照規則本身）、本檔（樣本字串）
重產基線：python backend/tests/platform/test_page_paths_centralized.py --update
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BASELINE = Path(__file__).with_name("page_path_baseline.json")
ALLOWED = {"backend/core/source_tree.py", "backend/core/pages.py", "backend/core/paths.py",
           "backend/tests/platform/test_page_paths_centralized.py",   # 本檔的樣本字串
           "backend/tests/platform/test_core_paths.py"}               # core.paths 每個常數的預期值對照表
SCAN_ROOTS = ("backend", "tools")
SKIP_PARTS = {"__pycache__", "node_modules", ".git"}

#: `"frontend" / "pages"`、`frontend/pages`、`"frontend", "pages"`、`FRONTEND_DIR / "pages"`、`_FRONTEND / 'pages'`
#: 單一交替式：同一處只算一次（`_FRONTEND / 'pages'` 由第一支抓；第二支只收帶後綴的 `FRONTEND_DIR` 之類）
#: 第三支（2026-09-26，A 的新題以 `root / "pages" / "cashier.html"` 繞過前兩支）：任何 `"pages" / "x.html"`
PATTERN = re.compile(r"frontend['\"]?\s*[/\\,]\s*['\"]?pages|\b_?FRONTEND\w+\s*[/,]\s*['\"]pages['\"]"
                     r"|(?<!frontend)(?<!FRONTEND)['\"]pages['\"]\s*/\s*['\"][\w.-]+\.html['\"]", re.I)


def count(text):
    return len(PATTERN.findall(text))


def scan(repo=REPO):
    """{repo 相對路徑: 次數}（只列 >0）。"""
    out = {}
    for root in SCAN_ROOTS:
        base = Path(repo) / root
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.suffix not in (".py", ".ps1") or not p.is_file():
                continue
            rel = p.relative_to(repo)
            if SKIP_PARTS & set(rel.parts) or any(part.startswith(".venv") for part in rel.parts):
                continue
            n = count(p.read_text(encoding="utf-8-sig", errors="replace"))
            if n:
                out[rel.as_posix()] = n
    return out


def problems(found, baseline, allowed=ALLOWED):
    msgs = []
    for f, n in sorted(found.items()):
        if f in allowed:
            continue
        b = baseline.get(f, 0)
        if n > b:
            msgs.append("%s：寫死 frontend/pages %d 處（基線 %d）⇒ 改用 core.source_tree.page_file()／page_files()" % (f, n, b))
    for f, b in sorted(baseline.items()):
        n = found.get(f, 0)
        if n < b:
            msgs.append("%s：已降到 %d 處（基線 %d）⇒ 同一個 commit 重產基線（--update）" % (f, n, b))
    return msgs


def test_page_paths_only_decrease():
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    msgs = problems(scan(), baseline)
    assert not msgs, "\n".join(msgs)


def test_scanner_sees_a_known_hardcoded_path():
    """正對照：product_select 目前確實寫死 frontend/pages（刪模組頁面時）——掃不到就代表掃描器壞了。"""
    assert scan().get("tools/platform/product_select.py", 0) >= 1


def test_page_file_resolves_l1_and_module_pages():
    from core import source_tree
    assert source_tree.page_file("login.html") == source_tree.FRONTEND_PAGES / "login.html"
    for d in source_tree.module_dirs():
        m = json.loads((d / "module.json").read_text(encoding="utf-8"))
        for p in m.get("pages") or []:
            assert source_tree.page_file(p["path"]).is_file()
    names = {p.name for p in source_tree.page_files()}
    assert "login.html" in names and "index.html" not in names   # index.html 在 frontend/ 根，不是頁面目錄


def test_rc_page_file_rejects_bad_and_missing_names():
    import pytest
    from core import source_tree
    for bad in ("../frontend/index.html", "nope.html", "x.htm"):
        with pytest.raises(FileNotFoundError):
            source_tree.page_file(bad)


def test_rc_page_files_includes_moved_pages(tmp_path, monkeypatch):
    """反向控制：模組資料夾裡的頁面也要列進 page_files()——只 glob frontend/pages 會漏掉它（本守門要防的事）。"""
    from core import source_tree
    fp = tmp_path / "frontend" / "pages"
    fp.mkdir(parents=True)
    (fp / "a.html").write_text("", encoding="utf-8")
    mod = tmp_path / "modules" / "m"
    (mod / "pages").mkdir(parents=True)
    (mod / "pages" / "b.html").write_text("", encoding="utf-8")
    (mod / "module.json").write_text(json.dumps({"key": "m", "pages": [{"path": "b.html"}]}), encoding="utf-8")
    monkeypatch.setattr(source_tree, "FRONTEND_PAGES", fp)
    monkeypatch.setattr(source_tree, "module_dirs", lambda: [mod])
    assert [p.name for p in source_tree.page_files()] == ["a.html", "b.html"]
    assert source_tree.page_file("b.html") == mod / "pages" / "b.html"


def test_rc_new_hardcoded_file_is_caught():
    found = {"backend/tests/test_new.py": 1}
    assert any("test_new.py" in m for m in problems(found, {}))


def test_rc_more_than_baseline_is_caught():
    assert problems({"a.py": 3}, {"a.py": 2})


def test_rc_decrease_requires_baseline_update():
    assert any("重產基線" in m for m in problems({"a.py": 1}, {"a.py": 2}))
    assert any("重產基線" in m for m in problems({}, {"a.py": 2}))


def test_rc_allowed_files_are_exempt():
    assert problems({"backend/core/source_tree.py": 5}, {}) == []


def test_rc_every_pattern_is_detected():
    """每一種寫法各自被抓到、而且只算一次（修改 PATTERN 時不可以悄悄漏掉其中一種）。"""
    samples = ['ROOT / "frontend" / "pages" / "x.html"', "p = 'frontend/pages/x.html'", "'frontend\\pages'",
               'os.path.join(ROOT, "frontend", "pages")', 'FRONTEND_DIR / "pages"', "_FRONTEND / 'pages' / name",
               'os.path.join(FRONTEND_DIR, "pages")', 'root / "pages" / "cashier.html"']
    for s in samples:
        assert count(s) == 1, s
    assert count('ROOT / "frontend" / "static"') == 0 and count('mod / "pages"') == 0


if __name__ == "__main__" and "--update" in sys.argv:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # 主控台預設 cp932／cp950 會炸在中文
    found = {f: n for f, n in scan().items() if f not in ALLOWED}
    BASELINE.write_text(json.dumps(found, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print("已重產基線：%d 檔、%d 處" % (len(found), sum(found.values())))
