# -*- coding: utf-8 -*-
"""對抗式審查 feat/train-merge-tools @254d56418（hichan-3，2026-11-13）。

綠燈＝確認過沒問題的行為（--check 不寫檔、新的未範圍讀取只報告不登記、驅動例外不吃掉對方）。
xfail(strict)＝發現（修好就會 XPASS 轉紅，請同時拿掉 xfail）：
  M1 同一行兩邊都改／一邊刪一邊改的 CHANGELOG 衝突被逐行聯集「靜默解掉」：報告說「沒有要人處理」、exit 0；刪除被復活
  M2 post_route_summary 把 select_star 改寫成「目前原始碼的數字」⇒ 新增的 SELECT * 被吸收進基準（route_inventory 守門本來會紅）
  M3 e2e lint 只掃檔名含 e2e 的檔，且排除 tests/platform ⇒ 瀏覽器測試漏掃
  M4 e2e lint 把 `with page.expect_response(): click()` 之後的讀取判違規（誤報，慣用寫法），又把名字含 wait 的 DB 輪詢當成 UI 等待（漏報）
  L  豁免註解理由一個字元就過、無數量上限
"""
import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location("_h3_" + name, REPO / "tools" / "platform" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RB = _load("resolve_baselines")
MD = RB.MD

BASE = "# 紀錄\n\n## (next) — base\n- 基底 A\n- 基底 B\n\n## 1.0 — old\n- old\n"


# ── M1 ────────────────────────────────────────────────────────────────────
@pytest.mark.xfail(strict=True, reason="M1：兩邊改同一行 ⇒ 逐行聯集後當成已解決（請目視只是一行字、exit 0）")
def test_both_sides_rewrote_the_same_changelog_line_is_left_for_a_human():
    a = BASE.replace("- 基底 A", "- A 版")
    b = BASE.replace("- 基底 A", "- B 版")
    assert MD.merge_changelog(BASE, a, b) is None                    # 驅動看不懂 ⇒ 交給一般合併
    assert RB._union_changelog(BASE, a, b) is None, "兩個版本都塞進去、沒人決定"


@pytest.mark.xfail(strict=True, reason="M1：一邊刪掉一行、另一邊改同一行 ⇒ 刪除被靜默復活")
def test_one_side_deleted_a_line_the_other_edited_is_not_silently_resurrected():
    a = BASE.replace("- 基底 B\n", "")
    b = BASE.replace("- 基底 B", "- 基底 B（重要補充）")
    got = RB._union_changelog(BASE, a, b)
    assert got is None or "基底 B（重要補充）" not in got


def test_report_for_union_resolved_changelog_still_says_nothing_to_do():
    """記錄現況（綠）：聯集解掉的檔放在 resolved 而不是要人處理 ⇒ format_report 不列、main 的 exit 只看 todo。
    修 M1 時，若改成「列入要人處理」這題要跟著改。"""
    rep = {"resolved": [("backend/core/CHANGELOG.md", "驅動看不懂這個形狀，改用逐行聯集再併 (next) —— 請目視確認內容")],
           "kept_for_human": [], "regenerated": [], "notes": [], "problems": [], "tests": [], "unmerged_other": []}
    text, todo = RB.format_report(rep, False)
    assert todo is False and "沒有要人處理的項目" in text


# ── M2 ────────────────────────────────────────────────────────────────────
@pytest.mark.xfail(strict=True, reason="M2：select_star 被改成目前原始碼的數字 ⇒ 新增的 SELECT * 被吸收")
def test_post_route_summary_does_not_absorb_new_select_star(tmp_path, monkeypatch):
    inv = {"summary": {"endpoints_total": 0}, "select_star": {"modules": 288}, "endpoints": {}}
    p = tmp_path / RB.ROUTE_INV
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(inv, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    # 假裝原始碼現在有 289 個 SELECT *（有人新增了一個，沒有登記）
    fake = json.dumps({"summary": {"endpoints_total": 0}, "select_star": {"modules": 289}})
    monkeypatch.setattr(RB, "_py_run", lambda *a, **k: (0, fake + "\n", ""))
    changed, problems = RB.post_route_summary(tmp_path, False, set())
    after = json.loads(p.read_text(encoding="utf-8"))["select_star"]
    assert after == {"modules": 288} or problems, "基準被悄悄改成 289：route_inventory 的 SELECT * 守門不會再紅"


# ── 綠燈：確認過的行為 ─────────────────────────────────────────────────────
def test_check_mode_writes_nothing_even_when_a_regeneration_is_needed(tmp_path, monkeypatch):
    inv = {"summary": {"endpoints_total": 0}, "select_star": {"modules": 288}, "endpoints": {}}
    p = tmp_path / RB.ROUTE_INV
    p.parent.mkdir(parents=True)
    raw = json.dumps(inv, ensure_ascii=False, indent=1) + "\n"
    p.write_text(raw, encoding="utf-8")
    fake = json.dumps({"summary": {"endpoints_total": 0}, "select_star": {"modules": 289}})
    monkeypatch.setattr(RB, "_py_run", lambda *a, **k: (0, fake + "\n", ""))
    changed, _ = RB.post_route_summary(tmp_path, True, set())
    assert changed == [RB.ROUTE_INV] and p.read_text(encoding="utf-8") == raw


def test_new_unscoped_reads_are_reported_not_registered(tmp_path, monkeypatch):
    base = {"a::f::t": "unscoped"}
    out = json.dumps({"cur": {"a::f::t": "unscoped", "b::g::t": "unscoped"}, "base": base})
    monkeypatch.setattr(RB, "_py_run", lambda *a, **k: (0, out + "\n", ""))
    (tmp_path / "backend/tests/platform").mkdir(parents=True)
    changed, problems, notes = RB.post_unscoped(tmp_path, False, set())
    assert any("b::g::t" in x for x in problems) and not changed
    assert not (tmp_path / RB.UNSCOPED).exists()


def test_driver_exception_falls_back_to_plain_merge(monkeypatch, tmp_path):
    for n, t in (("o", BASE), ("a", BASE.replace("- 基底 A", "- A")), ("b", BASE.replace("- old", "- OLD"))):
        (tmp_path / n).write_text(t, encoding="utf-8", newline="\n")
    monkeypatch.setitem(MD.MERGERS, "changelog", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    assert MD.main(["changelog", str(tmp_path / "o"), str(tmp_path / "a"), str(tmp_path / "b")]) == 0
    merged = (tmp_path / "a").read_text(encoding="utf-8")
    assert "- A" in merged and "- OLD" in merged                      # 兩邊的改動都在（不同行 ⇒ 一般合併無衝突）


# ── e2e lint ──────────────────────────────────────────────────────────────
from tests.platform import _e2e_lint as E  # noqa: E402


def _w(body, pre=""):
    return pre + "def test_a(page):\n" + "".join("    " + l + "\n" for l in body.strip("\n").splitlines())


def _flag(src):
    return bool(E.scan_source("tests/x_e2e.py", src))


@pytest.mark.xfail(strict=True, reason="M3：只掃檔名含 e2e 的檔、且排除 tests/platform；瀏覽器測試（new_page）漏掃")
def test_every_browser_test_file_is_scanned():
    scanned = {p.resolve() for p in E.e2e_files()}
    missing = []
    for p in sorted(E.BACKEND.rglob("test_*.py")):
        rel = p.relative_to(E.BACKEND)
        if rel.parts[0] in ("venv", ".venv", "node_modules") or "__pycache__" in rel.parts or p.name == Path(__file__).name:
            continue
        if re.search(r"\bnew_page\b|sync_playwright", p.read_text(encoding="utf-8", errors="replace")) and p.resolve() not in scanned:
            missing.append(rel.as_posix())
    assert not missing, "%d 個瀏覽器測試檔沒被掃：%s" % (len(missing), missing[:5])


@pytest.mark.xfail(strict=True, reason="M4a：with expect_response(): click() 之後讀取是正確寫法，卻被判違規（誤報 ⇒ 逼人亂加豁免）")
def test_click_inside_expect_response_block_counts_as_waited():
    assert not _flag(_w('with page.expect_response("**/api/x"):\n    page.click("#go")\nassert page.locator(".row").count() == 3'))


@pytest.mark.xfail(strict=True, reason="M4b：名字含 wait 的 DB 輪詢（_wait_db）被當成 UI 等待 ⇒ 之後立刻讀 UI 不報（漏報）")
def test_db_polling_helper_named_wait_is_not_a_ui_wait():
    src = _w('page.click("#go")\n_wait_db(lambda: True)\nassert page.locator("#ok").is_visible()',
             "def _wait_db(pred):\n    import time\n    time.sleep(0.1)\n    return pred()\n")
    assert _flag(src)


@pytest.mark.xfail(strict=True, reason="M4c：helper 先等再 click（結尾是 click）、或另一個 helper 內部才讀 UI ⇒ 漏報")
@pytest.mark.parametrize("src", [
    _w('_go(page)\nassert page.locator("#ok").is_visible()', "def _go(p):\n    p.wait_for_selector('#a')\n    p.click('#a')\n"),
    _w('page.click("#go")\nassert _vis(page, "#ok")', "def _vis(p, s):\n    return p.locator(s).is_visible()\n"),
    _w('page.click("#go")\nassert len(page.query_selector_all(".r")) == 3'),
    _w('page.click("#go")\nassert page.evaluate("document.querySelectorAll(\'.r\').length") == 3'),
    _w('for i in range(3):\n    assert page.locator(".r").count() == i\n    page.click("#add")'),
])
def test_other_unwaited_reads_are_flagged(src):
    assert _flag(src)


@pytest.mark.xfail(strict=True, reason="M4d：Python 容器的 .clear()／str.count() 被當成 Playwright 動作／讀取（誤報）")
@pytest.mark.parametrize("src", [
    _w('errors.clear()\nassert page.locator("#a").is_visible()'),
    _w('page.click("#go")\nassert page.content().count("x") == 1'),
])
def test_non_playwright_clear_and_count_are_not_flagged(src):
    assert not _flag(src)


@pytest.mark.xfail(strict=True, reason="L：豁免理由一個字元就過、沒有數量上限／登記")
def test_exemption_needs_a_real_reason():
    assert _flag(_w('page.click("#go")\nassert page.locator("#ok").is_visible()  # e2e-lint: ok x'))
