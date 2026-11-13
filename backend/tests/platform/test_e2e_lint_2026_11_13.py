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
    'page.click("#go")\nwait_until_saved(page)\nassert page.locator("#ok").is_visible()',     # 名字含 wait
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
    files = E.e2e_files()
    assert len(files) > 50, "掃到的 e2e 檔太少：glob 壞了？"
    assert all("e2e" in p.name for p in files)
    assert not any(p.parts[-3:-1] == ("tests", "platform") for p in files)


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
