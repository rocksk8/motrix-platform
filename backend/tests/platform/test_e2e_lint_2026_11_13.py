# -*- coding: utf-8 -*-
"""e2e 靜態規則（read-after-action）的契約題。規則本身在 tests/platform/_e2e_lint.py。

為什麼有這條：2026-11-11 `assert x.is_visible()` 輸給 Alpine x-show 一個影格 ⇒ 偶發紅；
`assert not x.is_visible()` 更糟——動作後立刻讀到「還沒出現」⇒ 假綠燈。已修的測試靠人記得；這條讓新寫的 e2e 不會再犯。
"""
import json

import pytest

from tests.platform import _e2e_lint as E


def _hits(src, rel="tests/test_e2e_x.py"):
    return sorted(E.scan_source(rel, src))


def _wrap(body):
    return "def test_a(page):\n" + "".join("    " + l + "\n" for l in body.strip("\n").splitlines())


# ── 該抓的（正對照）────────────────────────────────────────────────────────────

@pytest.mark.parametrize("body,read", [
    ('page.click("#go")\nassert page.locator("#ok").is_visible()', "is_visible"),
    ('page.click("#go")\nassert not page.locator("#ok").is_visible()', "is_visible"),       # 假綠燈版本
    ('page.locator("#go").click()\nassert "OK" in page.locator("#msg").inner_text()', "inner_text"),
    ('page.click("#go")\nassert page.locator(".row").count() == 3', "count"),
    ('page.press("#q", "Enter")\nx = page.text_content("#r")', "text_content"),
    ('page.click("#go")\npage.wait_for_timeout(500)\nassert page.locator("#ok").is_visible()', "is_visible"),   # 固定睡眠不是同步點
    ('import time\npage.click("#go")\ntime.sleep(1)\nassert page.locator("#ok").is_visible()', "is_visible"),
    ('page.fill("#q", "x")\nassert page.locator("#hint").is_hidden()', "is_hidden"),         # fill 之後讀「別的元素」的可見性
    ('page.click("#a")\nif cond:\n    assert page.locator("#ok").is_visible()', "is_visible"),   # 巢狀區塊
    ('for i in range(3):\n    page.click("#a")\n    assert page.get_attribute("#a", "x") == "1"', "get_attribute"),
    ('page.click("#go")\nwait_until_saved(page)\nassert page.locator("#ok").is_visible()', "is_visible"),   # 名字含 wait 不算等待（沒有同檔定義＝看不到內容）
])
def test_unwaited_read_after_action_is_flagged(body, read):
    got = _hits(_wrap(body))
    assert got and all("::" + read + "#" in g for g in got), got


# ── 不該抓的（負對照）────────────────────────────────────────────────────────────

@pytest.mark.parametrize("body", [
    'page.click("#go")\npage.locator("#ok").wait_for(state="visible")\nassert page.locator("#ok").is_visible()',
    'page.click("#go")\nexpect(page.locator("#ok")).to_be_visible()\nassert page.locator("#ok").is_visible()',
    'page.click("#go")\npage.wait_for_selector("#ok")\nassert page.inner_text("#ok") == "OK"',
    'page.click("#go")\npage.wait_for_function("() => 1")\nassert page.locator(".row").count() == 3',
    'page.click("#go")\npage.wait_for_load_state()\nassert page.locator(".row").count() == 3',
    'page.click("#go")\nwith page.expect_response("**/api/x"):\n    pass\nassert page.locator(".row").count() == 3',
    'assert page.locator("#ok").is_visible()\npage.click("#go")',                              # 讀在動作之前
    'page.goto("/x")\nassert page.locator("#ok").is_visible()',                               # goto 不是本規則的動作
    'page.fill("#q", "x")\nassert page.input_value("#q") == "x"',                             # fill 後讀同一個值：同步、確定
    'page.check("#c")\nassert page.is_checked("#c")',
])
def test_waited_or_not_racy_reads_are_not_flagged(body):
    assert _hits(_wrap(body)) == []


def test_click_then_input_value_is_still_flagged_but_fill_then_input_value_is_not():
    assert _hits(_wrap('page.click("#q")\nassert page.input_value("#q") == "x"'))
    assert not _hits(_wrap('page.fill("#q", "x")\nassert page.input_value("#q") == "x"'))
    assert _hits(_wrap('page.fill("#q", "x")\npage.click("#go")\nassert page.input_value("#q") == ""'))      # 中間有 async 動作


def test_helper_in_same_file_that_waits_counts_as_a_wait_but_a_non_waiting_helper_does_not():
    src = (
        "def _saved(page):\n    page.wait_for_selector('#saved')\n\n"
        "def _outer(page):\n    _saved(page)\n\n"
        "def _noop(page):\n    return 1\n\n"
        "def test_a(page):\n    page.click('#go')\n    _outer(page)\n    assert page.locator('#ok').is_visible()\n\n"
        "def test_b(page):\n    page.click('#go')\n    _noop(page)\n    assert page.locator('#ok').is_visible()\n")
    got = _hits(src)
    assert len(got) == 1 and "::test_b::is_visible#1" in got[0], got


def test_exemption_comment_needs_a_reason():
    ok = _wrap('page.click("#go")\nassert page.locator("#ok").is_visible()  # e2e-lint: ok click 的 handler 同步改 DOM')
    bare = _wrap('page.click("#go")\nassert page.locator("#ok").is_visible()  # e2e-lint: ok')
    prev_line = _wrap('page.click("#go")\n# e2e-lint: ok 前一行的 click 是同步 handler\nassert page.locator("#ok").is_visible()')
    assert _hits(ok) == [] and _hits(prev_line) == []
    assert _hits(bare), "沒寫理由的豁免不算"


def test_each_read_gets_a_stable_id_without_line_numbers():
    a = _wrap('page.click("#go")\nassert page.locator("#a").is_visible()\nassert page.locator("#b").is_visible()')
    b = "# 上面多一行註解不應改變 id\n\n" + a
    ids_a, ids_b = _hits(a), _hits(b)
    assert ids_a == ids_b and len(ids_a) == 2 and ids_a[0].endswith("is_visible#1") and ids_a[1].endswith("is_visible#2")


def test_method_and_nested_function_names_are_part_of_the_id():
    src = "class TestX:\n    def test_a(self, page):\n        page.click('#go')\n        assert page.is_visible('#ok')\n"
    assert _hits(src) == ["tests/test_e2e_x.py::TestX.test_a::is_visible#1"]


def test_syntax_error_is_reported_not_silently_skipped():
    got = _hits("def broken(:\n")
    assert got and "<syntax>" in got[0]


# ── 真實檔案樹 + 基準（只准縮小）──────────────────────────────────────────────────

def test_scanner_actually_sees_the_e2e_files():
    files = E.browser_files()
    assert len(files) > 150, "掃到的瀏覽器測試檔太少：選檔壞了？"
    assert all("e2e" in p.name.lower() or E._BROWSER_RE.search(p.read_text(encoding="utf-8", errors="replace")) for p in files)


def test_no_new_unwaited_reads_after_actions_in_e2e_tests():
    cur = E.scan_all()
    base = E.load_baseline()
    new = sorted(k for k in cur if k not in base)
    assert not new, (
        "e2e 測試在動作（click／fill…）之後不等待就直接讀 UI 狀態，跟前端更新賽跑（偶發紅；`assert not …is_visible()` 還會假綠燈）。\n"
        "改成：`loc.wait_for(state=\"visible\")`／`expect(loc).to_be_visible()`／`page.wait_for_function(...)` 之後再讀；\n"
        "若前面的動作確實是同步的，在該行或上一行加 `# e2e-lint: ok <理由>`。違規：\n  " + "\n  ".join("%s（第 %d 行）" % (k, cur[k]) for k in new))


def test_baseline_only_shrinks_fixed_entries_must_be_removed():
    cur = E.scan_all()
    stale = sorted(k for k in E.load_baseline() if k not in cur)
    assert not stale, ("基準裡這些違規已經不存在（修好了或測試改名了）——從基準刪掉，免得被拿去藏新的違規："
                       "`cd backend && python -m tests.platform._e2e_lint --shrink`\n  " + "\n  ".join(stale))


def test_baseline_file_is_one_entry_per_line_sorted_and_loadable():
    text = E.BASELINE_PATH.read_text(encoding="utf-8")
    obj = json.loads(text)
    assert list(obj) == ["entries"] and all(v == 1 for v in obj["entries"].values())
    assert text == E.dump(obj["entries"]), "基準檔排版不是 _e2e_lint.dump 的格式（一筆一行、依 id 排序）：用 --shrink 重寫"


def test_baseline_ids_do_not_point_at_missing_files():
    for k in E.load_baseline():
        assert (E.BACKEND / k.split("::")[0]).is_file(), k


# ── hichan-3 審查（M3／M4／L）─────────────────────────────────────────────────

def test_files_are_selected_by_content_not_only_by_name(tmp_path, monkeypatch):
    (tmp_path / "tests" / "platform").mkdir(parents=True)
    (tmp_path / "venv").mkdir()
    bad = "def test_a(page):\n    page.click('#a')\n    assert page.is_visible('#b')\n"
    (tmp_path / "tests" / "test_plain_name.py").write_text("def test_x(e2e_browser):\n    pass\n" + bad, encoding="utf-8")    # e2e_browser 夾具
    (tmp_path / "tests" / "platform" / "test_in_platform.py").write_text("from playwright.sync_api import sync_playwright\n" + bad, encoding="utf-8")
    (tmp_path / "tests" / "test_np.py").write_text("def t(b):\n    p = b.new_page()\n" + bad, encoding="utf-8")
    (tmp_path / "tests" / "test_marked.py").write_text("import pytest\n@pytest.mark.e2e\ndef t():\n    pass\n" + bad, encoding="utf-8")
    (tmp_path / "tests" / "test_not_browser.py").write_text(bad, encoding="utf-8")                                                  # 沒有瀏覽器線索 ⇒ 不掃
    (tmp_path / "venv" / "test_e2e_vendored.py").write_text(bad, encoding="utf-8")                                                  # 虛擬環境 ⇒ 不掃
    monkeypatch.setattr(E, "BACKEND", tmp_path)
    got = sorted(p.name for p in E.browser_files())
    assert got == ["test_in_platform.py", "test_marked.py", "test_np.py", "test_plain_name.py"]
    assert len(E.scan_all()) == 4


def test_click_inside_expect_block_counts_as_waited_after_the_block():
    assert _hits(_wrap('with page.expect_response("**/api/x"):\n    page.click("#go")\nassert page.locator(".row").count() == 3')) == []
    assert _hits(_wrap('with page.expect_navigation():\n    page.click("#go")\nassert page.is_visible("#ok")')) == []
    # 區塊「裡面」還沒等過就讀，照樣違規；區塊之後又動作也照樣違規
    assert _hits(_wrap('with page.expect_response("**/api/x"):\n    page.click("#go")\n    assert page.is_visible("#ok")'))
    assert _hits(_wrap('with page.expect_response("**/api/x"):\n    page.click("#a")\npage.click("#b")\nassert page.is_visible("#ok")'))


def test_a_helper_named_wait_that_only_polls_the_database_is_not_a_ui_wait():
    src = ("def _wait_db(pred):\n    import time\n    time.sleep(0.1)\n    return pred()\n\n"
           "def test_a(page):\n    page.click('#go')\n    _wait_db(lambda: True)\n    assert page.locator('#ok').is_visible()\n")
    assert _hits(src)


def test_polling_helper_called_with_a_lambda_that_reads_the_ui_is_a_wait():
    src = ("def _wait(pred):\n    import time\n    time.sleep(0.1)\n    return pred()\n\n"
           "def test_a(page):\n    page.click('#go')\n    _wait(lambda: page.locator('#ok').is_visible())\n    assert page.locator('#ok').is_visible()\n")
    assert _hits(src) == []


def test_helper_is_judged_by_content_wait_then_click_does_not_count():
    waits_then_clicks = ("def _go(p):\n    p.wait_for_selector('#a')\n    p.click('#a')\n\n"
                         "def test_a(page):\n    _go(page)\n    assert page.locator('#ok').is_visible()\n")
    clicks_then_waits = ("def _go(p):\n    p.click('#a')\n    p.wait_for_selector('#b')\n\n"
                         "def test_a(page):\n    page.click('#x')\n    _go(page)\n    assert page.locator('#ok').is_visible()\n")
    assert _hits(waits_then_clicks.replace("_go(page)\n    assert", "page.click('#x')\n    _go(page)\n    assert"))   # 最後一步是 click ⇒ _go 不算等待
    assert _hits(clicks_then_waits) == []


def test_imported_helpers_need_the_whitelist():
    import ast
    assert _hits(_wrap('page.click("#go")\nwait_dialog(page)\nassert page.locator("#ok").is_visible()')) == []
    assert _hits(_wrap('page.click("#go")\nsome_other_wait(page)\nassert page.locator("#ok").is_visible()'))
    assert {"wait_logged_in", "wait_dialog"} == set(E.WAIT_HELPER_WHITELIST)
    for mod, fn in (("_e2e_login.py", "wait_logged_in"), ("_ui_dialogs.py", "wait_dialog")):       # 白名單裡的函式真的等
        tree = ast.parse((E.BACKEND / "tests" / mod).read_text(encoding="utf-8"))
        f = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fn][0]
        assert any(E._is_wait_name(E._call_name(c)) for c in ast.walk(f) if isinstance(c, ast.Call)), fn


@pytest.mark.parametrize("src", [
    _wrap('errors.clear()\nassert page.locator("#a").is_visible()'),                       # Python 容器的 clear() 不是動作
    _wrap('page.click("#go")\nassert page.content().count("x") == 1'),                      # str.count(x)
    _wrap('page.click("#go")\nn = items.count(3)'),
])
def test_non_playwright_clear_and_count_are_not_flagged(src):
    assert _hits(src) == []


def test_locator_count_without_arguments_is_still_flagged():
    assert _hits(_wrap('page.click("#go")\nassert page.locator(".r").count() == 3'))


def test_loop_carries_the_previous_iterations_action_into_the_next():
    assert _hits(_wrap('for i in range(3):\n    assert page.locator(".r").count() == i\n    page.click("#add")'))
    assert _hits(_wrap('for i in range(3):\n    page.click("#add")\n    page.locator(".r").nth(i).wait_for()\n    assert page.locator(".r").count() == i + 1')) == []


def test_query_selector_all_is_a_read():
    assert _hits(_wrap('page.click("#go")\nassert len(page.query_selector_all(".r")) == 3'))


@pytest.mark.parametrize("reason,ok", [("x", False), ("太短了", False), ("九個字九個字九個字", False), ("click 的 handler 同步改 DOM", True),
                                       ("0123456789", True)])
def test_exemption_reason_needs_at_least_ten_characters(reason, ok):
    src = _wrap('page.click("#go")\nassert page.locator("#ok").is_visible()  # e2e-lint: ok ' + reason)
    assert (_hits(src) == []) == ok


def test_documented_limitations_are_written_in_the_module_docstring():
    doc = E.__doc__
    for phrase in ("輔助函式「裡面」才讀 UI", "page.evaluate", "基準 id", "WAIT_HELPER_WHITELIST"):
        assert phrase in doc, phrase


# ── hichan-3 複驗留下的 L ─────────────────────────────────────────────────────────

def test_expect_prefix_is_a_wait_only_for_playwright_calls():
    assert _hits(_wrap('with page.expect_response("**/x"):\n    page.click("#go")\nassert page.is_visible("#ok")')) == []
    assert _hits(_wrap('page.click("#go")\nexpect(page.locator("#ok")).to_be_visible()\nassert page.is_visible("#ok")')) == []
    assert _hits(_wrap('page.click("#go")\nexpected_total()\nassert page.is_visible("#ok")'))            # 自己寫的函式，名字剛好 expect 開頭
    assert _hits(_wrap('page.click("#go")\nexpect_rows(page, 3)\nassert page.is_visible("#ok")'))           # 同上（不是屬性呼叫）
    assert _hits(_wrap('page.click("#go")\nhelper.expect_rows(3)\nassert page.is_visible("#ok")'))          # 屬性呼叫但不是 Playwright 的 expect_* 名單
    # 名字剛好叫 expect 的屬性呼叫（pexpect 的 child.expect("x")、自己寫的 helper.expect(3)）不是 Playwright 的等待（h3 複驗 L，T84）
    assert _hits(_wrap('page.click("#go")\nchild.expect("x")\nassert page.is_visible("#ok")'))
    assert _hits(_wrap('page.click("#go")\nhelper.expect(3)\nassert page.is_visible("#ok")'))
    # 正對照：裸的 expect(...) 仍是等待（上面第二行），且名字單獨判斷（沒給節點）時 expect 仍算等待——給 file_waiters 之類只看名字的呼叫者用
    import ast
    assert E._is_wait_name("expect") is True
    assert E._is_wait_name("expect", ast.parse("expect(x)").body[0].value) is True
    assert E._is_wait_name("expect", ast.parse("child.expect(x)").body[0].value) is False


def test_two_same_name_reads_on_one_line_get_two_ids():
    ids = _hits(_wrap('page.click("#go")\nassert page.locator("#a").is_visible() and page.locator("#b").is_visible()'))
    assert len(ids) == 2 and ids[0].endswith("is_visible#1") and ids[1].endswith("is_visible#2")
    assert ids == _hits("\n\n" + _wrap('page.click("#go")\nassert page.locator("#a").is_visible() and page.locator("#b").is_visible()')), "id 不含行號"


def test_polling_helper_with_a_lambda_that_merely_builds_a_locator_is_not_a_wait():
    src = ("def _wait(pred):\n    import time\n    time.sleep(0.1)\n    return pred()\n\n"
           "def test_a(page):\n    page.click('#go')\n    _wait(lambda: page.locator('#a'))\n    assert page.locator('#ok').is_visible()\n")
    assert _hits(src)                                       # lambda 回傳 Locator（永遠為真）⇒ 立刻返回，不是等待
